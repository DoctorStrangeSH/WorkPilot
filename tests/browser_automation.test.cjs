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
  assert.equal(result.phase,'read_only');
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

test('exact table evidence triggers one ephemeral reconciliation, without exposing identifiers in progress', async () => {
  const api=runner(), chrome=fakeBrowser();
  chrome.scripting.executeScript=async ({args})=>({
    inventory:{columns:['cargo_place','inventory_date'],rows:[['TEST-001','2026-09-12']]},
    datalens:{columns:['main_partner_code_original','sc_id','result','scanned_at'],
      rows:[['TEST-001','101366','OK','2026-09-15T08:00:00']]},
    asgard:{columns:['cargo_place','status'],rows:[]}
  }[args[0]] ? [{result:{origin:'https://' + ({
    inventory:'inventory.example',datalens:'analytics.example',asgard:'asgard.example'
  }[args[0]]),text:'Тестовая строка',table:{
    inventory:{columns:['cargo_place','inventory_date'],rows:[['TEST-001','2026-09-12']]},
    datalens:{columns:['main_partner_code_original','sc_id','result','scanned_at'],
      rows:[['TEST-001','101366','OK','2026-09-15T08:00:00']]},
    asgard:{columns:['cargo_place','status'],rows:[]}
  }[args[0]]}}] : []);
  const sent=[],progress=[];
  const result=await api.run(chrome,{
    inventory:'https://inventory.example/orders',
    datalens:'https://analytics.example/reports',
    asgard:'https://asgard.example/history'
  },async message=>{
    sent.push(message);
    if(message.type==='reconcile_site_tables')return {
      ok:true,type:'site_tables_reconciled',persisted:false,read_only:true,
      write_enabled:false,total:1,summary:{found:1,in_progress:0,manual_review:0}
    };
    return {ok:true,type:'page_inspected',persisted:false,characters:message.page.text.length};
  },async snapshot=>progress.push(snapshot));
  assert.equal(result.phase,'reconciled');
  assert.equal(sent.filter(x=>x.type==='reconcile_site_tables').length,1);
  assert.ok(progress.every(snapshot=>!JSON.stringify(snapshot).includes('TEST-001')));
  assert.equal(result.reconciliation.summary.found,1);
});

test('next-page URL is restricted to same HTTPS origin', () => {
  const api=runner();
  assert.equal(api.nextPage('https://inventory.example/orders',
      '?page=2'), 'https://inventory.example/orders?page=2');
  for (const unsafe of ['https://outside.example/orders', 'http://inventory.example/',
      'https://user:pass@inventory.example/', 'https://inventory.example/orders#secret',
      'https://inventory.example:9443/orders']) {
    assert.throws(() => api.nextPage('https://inventory.example/orders', unsafe));
  }
});

test('automatically follows rel-next pages and merges exact schema before read-only reconciliation', async () => {
  const api=runner(), chrome=fakeBrowser();
  const originalGet=chrome.tabs.get;
  chrome.tabs.update=async (id, {url})=>{
    const current=await originalGet(id);
    current.url=url;
    current.status='complete';
    return current;
  };
  chrome.scripting.executeScript=async ({args})=>{
    const current=await chrome.tabs.get(7);
    const page=new URL(current.url);
    const role=args[0];
    const table=role==='inventory' ? {
      columns:['cargo_place','inventory_date'],
      rows:[[page.search ? 'TEST-002' : 'TEST-001','2026-09-12']]
    } : role==='datalens' ? {
      columns:['main_partner_code_original','sc_id','result','scanned_at'],
      rows:[['TEST-001','101366','OK','2026-09-15T10:00:00'],
            ['TEST-002','101366','OK','2026-09-15T10:00:00']]
    } : {columns:['cargo_place','status'],rows:[]};
    return [{result:{origin:page.origin,text:'Видимая страница',table,
      next:role==='inventory'&&!page.search?'https://inventory.example/orders?page=2':null}}];
  };
  const calls=[],progress=[];
  const result=await api.run(chrome,{
    inventory:'https://inventory.example/orders',
    datalens:'https://analytics.example/reports',
    asgard:'https://asgard.example/history'
  },async message=>{
    calls.push(message);
    if(message.type==='reconcile_site_tables') {
      assert.equal(message.snapshots.inventory.rows.length,2);
      return {ok:true,type:'site_tables_reconciled',read_only:true,
        write_enabled:false,persisted:false,total:2,
        summary:{found:2,in_progress:0,manual_review:0}};
    }
    return {ok:true,type:'page_inspected',persisted:false,characters:message.page.text.length};
  },async snapshot=>progress.push(snapshot));
  assert.equal(result.phase,'reconciled');
  assert.equal(result.results[0].pages,2);
  assert.equal(calls.filter(x=>x.type==='inspect_active_page').length,4);
  assert.equal(chrome.stats.removed,3);
  assert.ok(progress.every(x=>!JSON.stringify(x).includes('TEST-001')));
});

test('pagination cycle never produces a partial reconciliation', async () => {
  const api=runner(), chrome=fakeBrowser();
  chrome.scripting.executeScript=async ({args})=>[{
    result:{origin:'https://' + ({
      inventory:'inventory.example',datalens:'analytics.example',asgard:'asgard.example'
    }[args[0]]),text:'Содержимое',
    table:{columns:args[0]==='inventory'?['cargo_place','inventory_date']:
      args[0]==='datalens'?['main_partner_code_original','sc_id','result','scanned_at']:
      ['cargo_place','status'],rows:[]},
    next:args[0]==='inventory'?'https://inventory.example/orders':null}
  }];
  let reconciles=0;
  const result=await api.run(chrome,{
    inventory:'https://inventory.example/orders',
    datalens:'https://analytics.example/reports',
    asgard:'https://asgard.example/history'
  },async msg=>{
    if(msg.type==='reconcile_site_tables')reconciles++;
    return {ok:true,type:'page_inspected',persisted:false,characters:msg.page.text.length};
  },async ()=>{});
  assert.equal(result.phase,'needs_attention');
  assert.equal(reconciles,0);
  assert.equal(chrome.stats.removed,3);
});

test('virtualized grid with missing rows fails closed without reconciliation', async () => {
  const api=runner(), chrome=fakeBrowser();
  chrome.scripting.executeScript=async ({args})=>[{
    result:{origin:'https://' + ({
      inventory:'inventory.example',datalens:'analytics.example',asgard:'asgard.example'
    }[args[0]]),text:'Visible rows',
      incomplete:args[0]==='inventory',
      table:{columns:args[0]==='inventory'?['cargo_place','inventory_date']:
        args[0]==='datalens'?['main_partner_code_original','sc_id','result','scanned_at']:
        ['cargo_place','status'],rows:[]},next:null}
  }];
  let reconciles=0;
  const result=await api.run(chrome,{
    inventory:'https://inventory.example/orders',
    datalens:'https://analytics.example/reports',
    asgard:'https://asgard.example/history'
  },async msg=>{
    if(msg.type==='reconcile_site_tables')reconciles++;
    return {ok:true,type:'page_inspected',persisted:false,
      characters:msg.page?.text?.length??0};
  },async()=>{});
  assert.equal(result.phase,'needs_attention');
  assert.equal(result.results[0].status,'needs_attention');
  assert.equal(reconciles,0);
  assert.equal(chrome.stats.removed,3);
});

test('ARIA grid extractor rejects known rowcount larger than rendered rows', () => {
  assert.match(source, /querySelectorAll\('\[role="grid"\],\[role="table"\]'\)/);
  assert.match(source, /count > rows\.length/);
  assert.match(source, /virtualized_or_incomplete_grid/);
  assert.match(source, /\[role="columnheader"\]/);
});
