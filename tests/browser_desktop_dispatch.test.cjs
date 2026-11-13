const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

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
  assert.match(source,/chrome\.storage\.session\.get\("maleniaConfirmedOpenTabs"\)/);
  assert.match(source,/chrome\.permissions\.contains/);
  assert.match(source,/if \(running\) return;/);
  assert.match(source,/succeeded = result\.phase === "reconciled"/);
});

test('desktop audit requires fresh confirmed open tabs and exact current locations',()=>{
  assert.match(source,/MaleniaAutomation\.normalizeTargets\(rawTargets\)/);
  assert.match(source,/selectedTabs/);
  assert.match(source,/exactGetSearch:true,selectedTabs/);
  assert.match(source,/confirmedAt/);
  assert.match(source,/30 \* 60 \* 1000/);
  assert.match(source,/currentUrl\.pathname !== entry\.path/);
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
