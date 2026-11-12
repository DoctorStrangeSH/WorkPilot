const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.resolve(__dirname, '../browser-extension/automation.js'), 'utf8');
function runner() {
  const ctx = {URL, setTimeout, clearTimeout};
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  return ctx.MaleniaAutomation;
}
function fakeBrowser(finalUrl = null) {
  let current = null;
  const events = {listener:null,addListener(fn){this.listener=fn;},removeListener(){this.listener=null;}};
  const stats = {created:0,removed:0,executed:0};
  return {stats, tabs:{
    onUpdated:events,
    async create({url,active}) {assert.equal(active,false); stats.created++; current={id:7,url:finalUrl || url,status:'complete'};return current;},
    async get(id){assert.equal(id,7);return current;},
    async remove(id){assert.equal(id,7);stats.removed++;}
  }, scripting:{
    async executeScript({target}) {
      assert.equal(target.tabId,7);stats.executed++;
      return [{result:{origin:new URL(current.url).origin,text:'Тестовая строка'}}];
    }
  }};
}
test('only exact three user-configured HTTPS pages, no URL secrets', () => {
  const api=runner();
  const good=api.normalizeTargets({
    inventory:'https://inventory.example/orders',
    datalens:'https://analytics.example/reports',
    asgard:'https://asgard.example/history'
  });
  assert.equal(Object.keys(good).length,3);
  assert.equal(api.origins(good).length,3);
  for(const unsafe of ['http://example.com/','https://example.com/?token=secret',
     'https://example.com/#token','https://name:password@example.com/',
     'file:///C:/private','https://localhost/orders','https://example.com:9443/orders']) {
    assert.throws(()=>api.normalizeTargets({...good,inventory:unsafe}));
  }
  assert.throws(()=>api.normalizeTargets({...good,extra:'https://example.com/'}));
});
test('automated traversal opens and closes separate background tabs without writing page data', async () => {
  const api=runner(), chrome=fakeBrowser();
  const reports=[], sent=[];
  const result=await api.run(chrome,{
    inventory:'https://inventory.example/orders',
    datalens:'https://analytics.example/reports',
    asgard:'https://asgard.example/history'
  },async msg=>{
    sent.push(msg);
    return {ok:true,type:'page_inspected',persisted:false,characters:msg.page.text.length};
  },async snapshot=>reports.push(snapshot));
  assert.equal(result.phase,'completed');
  assert.equal(chrome.stats.created,3);
  assert.equal(chrome.stats.removed,3);
  assert.equal(sent.length,3);
  assert.ok(sent.every(msg=>msg.type==='inspect_active_page'));
  assert.ok(reports.every(report=>!JSON.stringify(report).includes('Тестовая строка')));
});
test('navigation to another origin is rejected before page text is read and tab is closed', async () => {
  const api=runner(), chrome=fakeBrowser('https://login.example/auth');
  let sent=0;
  const result=await api.run(chrome,{
    inventory:'https://inventory.example/orders',
    datalens:'https://analytics.example/reports',
    asgard:'https://asgard.example/history'
  },async ()=>{sent++;return {};},async ()=>{});
  assert.equal(result.phase,'needs_attention');
  assert.equal(chrome.stats.executed,0);
  assert.equal(chrome.stats.removed,3);
  assert.equal(sent,0);
});
test('the site data is not persisted and a native rejection fails closed',async()=>{
  const api=runner(),chrome=fakeBrowser();
  const result=await api.run(chrome,{
    inventory:'https://inventory.example/orders',
    datalens:'https://analytics.example/reports',
    asgard:'https://asgard.example/history'
  },async()=>({ok:true,type:'page_inspected',persisted:true,characters:16}),async()=>{});
  assert.equal(result.phase,'needs_attention');
  assert.equal(result.results.length,3);
  assert.equal(chrome.stats.removed,3);
});
