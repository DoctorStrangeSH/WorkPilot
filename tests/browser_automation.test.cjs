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
  assert.match(source, /count !== rows\.length/);
  assert.match(source, /virtualized_or_incomplete_grid/);
  assert.match(source, /\[role="columnheader"\]/);
});

test('opted-in GET search automatically queries both sites for inventory cargo codes', async () => {
  const api=runner(), chrome=fakeBrowser();
  const originalGet=chrome.tabs.get, urls=[];
  chrome.tabs.update=async (id,{url})=>{
    const tab=await originalGet(id);
    tab.url=url;tab.status='complete';urls.push(url);
    return tab;
  };
  chrome.scripting.executeScript=async ({args})=>{
    const tab=await originalGet(7), url=new URL(tab.url);
    if(args?.length===2) {
      const role=args[0],code=args[1];
      const field=role==='datalens'?'main_partner_code_original':'cargo_place';
      const search=new URL(url.origin + '/search');
      search.searchParams.set(field,code);
      return [{result:{origin:url.origin,url:search.href}}];
    }
    const role=args[0];
    const code=url.searchParams.get('main_partner_code_original') ||
      url.searchParams.get('cargo_place');
    const table=role==='inventory'?{
      columns:['cargo_place','inventory_date'],
      rows:[['ABC-1','2026-09-12'],['ABC-2','2026-09-12']]
    }:role==='datalens'?{
      columns:['main_partner_code_original','sc_id','result','scanned_at'],
      rows:[[code,'101366','OK','2026-09-14T08:30:00']]
    }:{columns:['cargo_place','status'],rows:[[code,'Принят на ФФ']]};
    return [{result:{origin:url.origin,text:'Visible table',table,next:null}}];
  };
  const calls=[];
  const result=await api.run(chrome,{
    inventory:'https://inventory.example/orders',
    datalens:'https://analytics.example/orders',
    asgard:'https://asgard.example/orders'
  },async msg=>{
    calls.push(msg);
    if(msg.type==='reconcile_site_tables') {
      assert.equal(msg.snapshots.datalens.rows.length,2);
      assert.equal(msg.snapshots.asgard.rows.length,2);
      return {ok:true,type:'site_tables_reconciled',read_only:true,write_enabled:false,
        persisted:false,total:2,summary:{found:2,in_progress:0,manual_review:0}};
    }
    return {ok:true,type:'page_inspected',persisted:false,characters:msg.page.text.length};
  },async()=>{}, {exactGetSearch:true});
  assert.equal(result.phase,'reconciled');
  assert.equal(urls.length,4);
  assert.equal(chrome.stats.created,5);
  assert.equal(chrome.stats.removed,5);
  assert.equal(calls.filter(m=>m.type==='reconcile_site_tables').length,1);
  assert.ok(urls.every(url=>new URL(url).searchParams.size===1));
});

test('opted-in search rejects rows belonging to a different cargo place',async()=>{
  const api=runner(), chrome=fakeBrowser();
  const originalGet=chrome.tabs.get;
  chrome.tabs.update=async (id,{url})=>{
    const tab=await originalGet(id);tab.url=url;return tab;
  };
  chrome.scripting.executeScript=async ({args})=>{
    const tab=await originalGet(7),url=new URL(tab.url);
    if(args.length===2)return [{result:{
      origin:url.origin,
      url:url.origin+'/search?main_partner_code_original=ABC-1'
    }}];
    return [{result:{origin:url.origin,text:'Visible table',next:null,
      table:args[0]==='inventory'?
        {columns:['cargo_place','inventory_date'],rows:[['ABC-1','2026-09-12']]}:
        {columns:['main_partner_code_original','sc_id','result','scanned_at'],
         rows:[['SOMEONE-ELSE','101366','OK','2026-09-14T08:30:00']]}}}];
  };
  let reconciles=0;
  const result=await api.run(chrome,{
    inventory:'https://inventory.example/orders',
    datalens:'https://analytics.example/orders',
    asgard:'https://asgard.example/orders'
  },async msg=>{
    if(msg.type==='reconcile_site_tables')reconciles++;
    return {ok:true,type:'page_inspected',persisted:false,characters:msg.page.text.length};
  },async()=>{}, {exactGetSearch:true});
  assert.equal(result.phase,'needs_attention');
  assert.equal(result.results[1].status,'needs_attention');
  assert.equal(reconciles,0);
});

test('search limits and GET-only form guard are present',()=>{
  assert.match(source,/MAX_SEARCHES = 20/);
  assert.match(source,/form\.method\.toLowerCase\(\) === "get"/);
  assert.match(source,/querySelectorAll\('input\[type="password"\],input\[type="hidden"\]'\)/);
  assert.match(source,/unverified_search_result_identity/);
});

test('browser GET-search extractor only accepts an unambiguous read-only form', async () => {
  const api=runner();
  const current='https://analytics.example/orders';
  const normalForm = (method='get', extra=false) => ({
    method,
    getAttribute:()=>'/search',
    querySelectorAll(selector) {
      if (selector.includes('password') || selector.includes('hidden')) return extra?[{}]:[];
      if (selector.includes('main_partner_code_original')) return [{type:'search'}];
      if (selector==='input[name]') return [{type:'search'}];
      return [];
    },
    querySelector:()=>({type:'search'})
  });
  let form=normalForm();
  const chrome={
    scripting:{async executeScript({func,args}) {
      const document={querySelectorAll:()=>[form]};
      const location={origin:'https://analytics.example',href:current};
      const context={document,location,URL};
      return [{result:vm.runInNewContext('('+func.toString()+')(...args)',{...context,args})}];
    }},
    tabs:{async update(_,{url}){return {url};}}
  };
  let result=await api.exactGetSearch(chrome,7,'datalens','ABC-1','https://analytics.example');
  assert.equal(result,undefined);
  for(const [method,extra] of [['post',false],['get',true]]) {
    form=normalForm(method,extra);
    await assert.rejects(
      ()=>api.exactGetSearch(chrome,7,'datalens','ABC-1','https://analytics.example'),
      /unsupported_search_form/);
  }
  await assert.rejects(
    ()=>api.exactGetSearch(chrome,7,'datalens','SECRET?','https://analytics.example'),
    /invalid_search/);
});

test('progress reports a stable safe reason code, never raw URLs or browser errors', async () => {
  const api=runner();
  const chrome=fakeBrowser('https://login.example/auth?token=SECRET');
  const reports=[];
  const result=await api.run(chrome,{
    inventory:'https://inventory.example/orders',
    datalens:'https://analytics.example/orders',
    asgard:'https://asgard.example/orders'
  },async()=>{throw Error('should not send');},async data=>reports.push(data));
  assert.equal(result.phase,'needs_attention');
  assert.equal(result.results[0].reason,'navigation_outside_allowed_origin');
  assert.ok(reports.every(data=>!JSON.stringify(data).includes('SECRET')));
  assert.ok(reports.every(data=>!JSON.stringify(data).includes('login.example')));
});

test('unexpected browser errors are reduced to generic safe reason', async () => {
  const api=runner();
  const chrome=fakeBrowser();
  chrome.scripting.executeScript=async()=>{throw new Error('Failed URL https://secret.example/?token=SENSITIVE');};
  const result=await api.run(chrome,{
    inventory:'https://inventory.example/orders',
    datalens:'https://analytics.example/orders',
    asgard:'https://asgard.example/orders'
  },async()=>{throw Error('should not send');},async()=>{});
  assert.equal(result.results[0].reason,'site_or_browser_error');
  assert.ok(!JSON.stringify(result).includes('SENSITIVE'));
});

test('dynamic search widget is recognized without reading its value or clicking it', async () => {
  const api=runner();
  const chrome={
    scripting:{async executeScript({func,args}) {
      const document={querySelectorAll:selector=>
        selector==='form'?[]:
        selector==='[role="searchbox"],input[type="search"]'?[{type:'search'}]:[]};
      const location={origin:'https://analytics.example',href:'https://analytics.example/orders'};
      return [{result:vm.runInNewContext('('+func.toString()+')(...args)',
        {document,location,URL,args})}];
    }},
    tabs:{async update(){throw Error('must not navigate');}}
  };
  await assert.rejects(()=>api.exactGetSearch(
    chrome,7,'datalens','ABC-1','https://analytics.example'),/dynamic_search_ui/);
});

test('reactive search enters exact cargo in one labelled standalone searchbox', async () => {
  const api=runner();
  let value='', dispatched=0, clicks=0, observed=false, disconnected=false;
  let notify;
  class MockInput {}
  Object.defineProperty(MockInput.prototype,'value',{set(v){value=v;},get(){return value;}});
  const input=new MockInput();
  input.type='search';input.disabled=false;input.readOnly=false;
  input.closest=()=>null;
  input.getAttribute=name=>name==='aria-label'?'main_partner_code_original':null;
  input.getClientRects=()=>[{}];
  input.dispatchEvent=()=>{dispatched++;queueMicrotask(()=>notify?.());};
  input.click=()=>{clicks++;};
  class Observer {
    constructor(fn){notify=fn;}
    observe(){observed=true;}
    disconnect(){disconnected=true;}
  }
  const chrome={
    scripting:{async executeScript({func,args}) {
      const table={querySelectorAll:()=>[
        {innerText:'main_partner_code_original'},{innerText:'sc_id'},
        {innerText:'result'},{innerText:'scanned_at'}]};
      const context={document:{body:{},querySelectorAll:selector=>
        selector.includes('table,')?[table]:[input]},
        location:{origin:'https://analytics.example'},HTMLInputElement:MockInput,
        MutationObserver:Observer,Event:class{constructor(type){this.type=type;}},
        setTimeout,clearTimeout};
      return [{result:await vm.runInNewContext('('+func.toString()+')(...args)',
        {...context,args})}];
    }}
  };
  await api.reactiveSearch(chrome,7,'datalens','ABC-1','https://analytics.example');
  assert.equal(value,'ABC-1');
  assert.equal(dispatched,1);
  assert.equal(clicks,0);
  assert.equal(observed,true);
  assert.equal(disconnected,true);
});

test('dynamic search never writes into ambiguous or form-owned controls', async () => {
  const api=runner();
  let writes=0;
  class MockInput{}
  Object.defineProperty(MockInput.prototype,'value',{set(){writes++;}});
  const input=new MockInput();
  input.type='search';input.disabled=false;input.readOnly=false;
  input.closest=()=>({tagName:'FORM'});
  input.getAttribute=()=> 'cargo_place';
  input.getClientRects=()=>[{}];
  const chrome={
    scripting:{async executeScript({func,args}) {
      const context={document:{body:{},querySelectorAll:()=>[input]},
        location:{origin:'https://asgard.example'},HTMLInputElement:MockInput,
        MutationObserver:class{},Event:class{},setTimeout,clearTimeout};
      return [{result:await vm.runInNewContext('('+func.toString()+')(...args)',
        {...context,args})}];
    }}
  };
  await assert.rejects(()=>api.reactiveSearch(
    chrome,7,'asgard','ABC-1','https://asgard.example'),/unsupported_dynamic_search/);
  assert.equal(writes,0);
});

test('reactive search refuses result updates on a foreign origin', async () => {
  const api=runner();
  const chrome={scripting:{async executeScript(){
    return [{result:{origin:'https://other.example',status:'updated'}}];
  }}};
  await assert.rejects(()=>api.reactiveSearch(
    chrome,7,'asgard','ABC-1','https://asgard.example'),/unsupported_dynamic_search/);
});
