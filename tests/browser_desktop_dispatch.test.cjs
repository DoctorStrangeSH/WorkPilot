const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.resolve(__dirname,'../browser-extension/background.js'),'utf8');
const manifest = JSON.parse(fs.readFileSync(
  path.resolve(__dirname,'../browser-extension/manifest.json'),'utf8'));

test('browser bridge polls local desktop queue without any remote permission',()=>{
  assert.ok(manifest.permissions.includes('alarms'));
  assert.ok(manifest.permissions.includes('nativeMessaging'));
  assert.ok(!manifest.permissions.includes('cookies'));
  assert.ok(!manifest.permissions.includes('webRequest'));
  assert.match(source,/chrome\.alarms\.onAlarm\.addListener/);
  assert.match(source,/periodInMinutes:1/);
  assert.match(source,/type:"claim_browser_audit"/);
  assert.match(source,/type:"finish_browser_audit"/);
  assert.match(source,/chrome\.storage\.local\.get\(\["maleniaTargets", "maleniaExactGetSearch"\]\)/);
  assert.match(source,/chrome\.permissions\.contains/);
  assert.match(source,/if \(running\) return;/);
  assert.match(source,/succeeded = result\.phase === "reconciled"/);
});

test('extension runs desktop job only through bounded read-only walker',()=>{
  assert.match(source,/MaleniaAutomation\.normalizeTargets\(stored\.maleniaTargets\)/);
  assert.match(source,/MaleniaAutomation\.run\(chrome,targets/);
  assert.doesNotMatch(source,/chrome\.cookies|chrome\.webRequest|executeScript\(\{code:/);
  assert.doesNotMatch(source,/eval\(/);
});

test('only coarse audit progress is forwarded to the native desktop job',()=>{
  assert.match(source,/type:"update_browser_audit_progress",job_id:jobId/);
  assert.match(source,/completed_sources:results\.length/);
  assert.match(source,/attention_sources:failures\.length/);
  assert.match(source,/failed_role:failedRole/);
  assert.match(source,/MaleniaAutomation\.run\(chrome,targets,[\s\S]*message=>session\.send\(message\),report/);
  assert.doesNotMatch(source,/progress\(\{[^}]*cargo_place/);
});

function workerHarness() {
  let onMessage;
  const messages = [];
  let claims = 0;
  let closes = 0;
  const context = vm.createContext({
    importScripts() {},
    chrome: {
      runtime: {
        onMessage: {addListener(listener) { onMessage = listener; }},
        onInstalled: {addListener() {}}, onStartup: {addListener() {}}
      },
      alarms: {create() {}, onAlarm: {addListener() {}}},
      storage: {
        local: {async get() { return {maleniaTargets:{}}; }},
        session: {async set() {}}
      },
      permissions: {async contains() { return true; }}
    },
    MaleniaAutomation: {
      normalizeTargets(value) { return value; }, origins() { return []; },
      async run() { return {phase:'reconciled'}; }
    },
    testSession: {
      async send(message) {
        messages.push(message);
        if (message.type === 'hello') return {ok:true,host:'com.malenia.browser',
          capabilities:['claim_browser_audit','finish_browser_audit',
            'update_browser_audit_progress','reconcile_site_tables']};
        if (message.type === 'claim_browser_audit') {
          claims++;
          return {ok:true,job:{job_id:'job-1'}};
        }
        return {ok:true};
      },
      close() { closes++; }
    }
  });
  vm.runInContext(source, context);
  vm.runInContext('nativeSession = () => testSession', context);
  return {context, messages, claims:()=>claims, closes:()=>closes,
    poll:()=>vm.runInContext('pollDesktopAudit()',context),
    popup() {
      let response;
      onMessage({type:'start_readonly_audit',targets:{}},{},value=>{response=value;});
      return response;
    }};
}

test('desktop polling reserves worker before storage resolves and blocks popup',async()=>{
  const worker = workerHarness();
  let resume;
  worker.context.chrome.storage.local.get = () => new Promise(resolve=>{resume=resolve;});
  const first = worker.poll();
  await worker.poll();
  assert.equal(worker.popup().error,'already_running');
  assert.equal(worker.claims(),0);
  resume({maleniaTargets:{}});
  await first;
  assert.equal(worker.claims(),1);
  assert.equal(worker.closes(),1);
  assert.equal(worker.messages.find(item=>item.type==='finish_browser_audit').succeeded,true);
  worker.context.chrome.storage.local.get = async()=>({maleniaTargets:{}});
  await worker.poll();
  assert.equal(worker.claims(),2);
});

test('early exits and connection failures release desktop polling reservation',async()=>{
  for (const failure of ['no_targets','no_permission','host_failure','no_job']) {
    const worker = workerHarness();
    if (failure==='no_targets') worker.context.chrome.storage.local.get = async()=>({});
    if (failure==='no_permission') worker.context.chrome.permissions.contains = async()=>false;
    if (failure==='host_failure') worker.context.testSession.send = async()=>{throw Error('offline');};
    if (failure==='no_job') worker.context.testSession.send = async()=>({ok:true});
    await worker.poll();
    assert.equal(vm.runInContext('running',worker.context),false,failure);
    assert.equal(worker.messages.some(item=>item.type==='finish_browser_audit'),false,failure);
  }
});

test('automation failure finishes claimed job and releases worker',async()=>{
  const worker = workerHarness();
  worker.context.MaleniaAutomation.run = async()=>{throw Error('unsupported_page');};
  await worker.poll();
  assert.equal(worker.messages.find(item=>item.type==='finish_browser_audit').succeeded,false);
  assert.equal(worker.closes(),1);
  assert.equal(vm.runInContext('running',worker.context),false);
});
