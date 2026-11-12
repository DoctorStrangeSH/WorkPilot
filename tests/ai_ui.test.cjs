const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const localRequire = Module.createRequire(path.resolve(__dirname, '../desktop/package.json'));
const ts = localRequire('typescript');

function harness(invoke,componentName="AiPage",props={}) {
  const slots = []; let cursor = 0;
  const hooks = {
    useState(initial) {const i=cursor++;if(!(i in slots))slots[i]=initial;return [slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}];},
    useRef(initial) {const i=cursor++;if(!(i in slots))slots[i]={current:initial};return slots[i];},
    useEffect(fn,deps) {const i=cursor++;if(!slots[i] || deps.some((v,n)=>v!==slots[i][n])){slots[i]=deps;fn();}},
  };
  const filename=path.resolve(__dirname,`../desktop/src/${componentName==='KnowledgeEditor'?'KnowledgePage':componentName}.tsx`);
  const component=new Module(filename,module);
  component.filename=filename;component.paths=Module._nodeModulePaths(path.dirname(filename));
  const original=component.require.bind(component);
  component.require=name=>name==='react'?hooks:name==='@tauri-apps/api/core'?{invoke}:name==='./KnowledgePage'?{KnowledgeEditor:()=>null}:original(name);
  component._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,filename);
  let refreshed=0;
  const render=()=>{cursor=0;return component.exports[componentName]({connected:true,onTaskCreated:()=>refreshed++,onSaved:()=>refreshed++,onCancel:()=>{},...props});};
  function all(tree,predicate) {
    if(!tree || typeof tree!=='object')return [];
    if(Array.isArray(tree))return tree.flatMap(item=>all(item,predicate));
    return [...(predicate(tree)?[tree]:[]),...all(tree.props?.children,predicate)];
  }
  const find=(type,predicate=()=>true)=>all(render(),e=>e.type===type && predicate(e.props));
  return {render,find,refreshed:()=>refreshed};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('AI answer requires explicit review; uncertain retry reuses the same ID and content',async()=>{
  const saves=[];let fail=true;
  const h=harness(async(command,args)=>{
    if(command==='get_ai_status')return {available:true,models:['qwen2.5:0.5b']};
    if(command==='chat_ai')return {message:{role:'assistant',content:'Review this plan'}};
    if(command==='create_task'){saves.push(args);if(fail)throw Error('connection lost');return {};}
    throw Error(command);
  });
  h.render();await tick();
  h.find('textarea',p=>p.id==='ai-draft')[0].props.onChange({target:{value:'Plan my work'}});
  h.find('form')[0].props.onSubmit({preventDefault(){}});await tick();
  assert.equal(saves.length,0);
  const review=h.find('button',p=>p.children==='Создать задачу из ответа')[0];
  review.props.onClick();
  const input=h.find('input',p=>p.type!=='checkbox')[0];
  assert.equal(input.props.value,'Plan my work');
  input.props.onChange({target:{value:'Reviewed title'}});
  let save=h.find('button',p=>p.children==='Добавить в очередь')[0];
  save.props.onClick();save.props.onClick();await tick();
  assert.equal(saves.length,1);
  assert.equal(saves[0].title,'Reviewed title');
  assert.equal(saves[0].description,'Review this plan');
  assert.match(saves[0].requestId,/^[a-f0-9-]{36}$/);
  assert.equal(h.find('input',p=>p.type!=='checkbox')[0].props.disabled,true);
  fail=false;
  h.find('button',p=>p.children==='Добавить в очередь')[0].props.onClick();await tick();
  assert.deepEqual(saves[1],saves[0]);
  assert.equal(h.find('input',p=>p.type!=='checkbox').length,0);
  assert.equal(h.refreshed(),1);
});


test('memory requires explicit confirmation; failed save retries identical content and ID',async()=>{
  const calls=[];let fail=true;
  const initial={id:'b1234567-1234-1234-1234-123456789abc',title:'Reviewed rule',content:'Never invent delivery address',kind:'memory'};
  const h=harness(async(command,args)=>{calls.push({command,args});if(fail)throw Error('uncertain');return {};},'KnowledgeEditor',{initial});
  h.render();await tick();assert.equal(calls.length,0);
  let button=h.find('button',p=>p.children==='Подтвердить и запомнить')[0];
  button.props.onClick();button.props.onClick();await tick();
  assert.equal(calls.length,1);
  assert.equal(calls[0].args.payload.content,initial.content);
  assert.equal(h.find('textarea')[0].props.disabled,true);
  fail=false;h.find('button',p=>p.children==='Подтвердить и запомнить')[0].props.onClick();await tick();
  assert.deepEqual(calls[1],calls[0]);assert.equal(h.refreshed(),1);
});

test('knowledge folder is never imported on render or while entering a path',async()=>{
  const calls=[];
  const h=harness(async(command,args)=>{calls.push({command,args});return command==='get_knowledge'?{records:[]}:{imported:1};},'KnowledgePage');
  h.render();await tick();
  h.find('input',p=>!!p.placeholder)[0].props.onChange({target:{value:'C:\\ChosenNotes'}});
  assert.equal(calls.filter(c=>c.command==='knowledge_action').length,0);
  h.find('button',p=>p.children==='Импортировать выбранную папку')[0].props.onClick();await tick();
  const imports=calls.filter(c=>c.command==='knowledge_action');
  assert.equal(imports.length,1);assert.equal(imports[0].args.action,'import');
  assert.equal(imports[0].args.payload.folder,'C:\\ChosenNotes');
});


test('knowledge search is explicit, does not invoke chat and discards results after disconnect',async()=>{
  let finish;const calls=[];const props={connected:true};
  const h=harness(async(command,args)=>{calls.push({command,args});if(command==='get_knowledge')return {records:[]};return new Promise(resolve=>{finish=resolve;});},'KnowledgePage',props);
  h.render();await tick();
  h.find('input',p=>p['aria-label']==='Поиск по знаниям')[0].props.onChange({target:{value:'AB-17'}});
  assert.equal(calls.filter(c=>c.command==='knowledge_action').length,0);
  const button=h.find('button',p=>p.children==='Найти в знаниях')[0];button.props.onClick();button.props.onClick();
  assert.equal(calls.filter(c=>c.command==='knowledge_action').length,1);
  assert.deepEqual(calls.at(-1).args,{action:'search',payload:{query:'AB-17'}});
  props.connected=false;h.render();
  finish({sources:[{id:'fixture',title:'Stale result',source:'note.md',excerpt:'stale',start:0,end:5}]});await tick();
  assert.equal(h.find('h3').length,0);
  assert.equal(calls.filter(c=>c.command==='chat_ai').length,0);
});

test('strict mode is explicit and disabling knowledge clears it; source metadata is not sent as chat history',async()=>{
  const calls=[];
  const h=harness(async(command,args)=>{
    if(command==='get_ai_status')return {available:true,models:['qwen3:8b']};
    if(command==='chat_ai'){calls.push(args);return {message:{role:'assistant',content:'Tokyo'},sources:[{id:'real',title:'Japan',source:'Japan.md',excerpt:'Tokyo',start:0,end:5}],answer_mode:'knowledge_only',cited_source_ids:['real']};}
    throw Error(command);
  });
  h.render();await tick();
  h.find('input',p=>p['aria-label']==='Только по знаниям')[0].props.onChange({target:{checked:true}});
  h.find('textarea',p=>p.id==='ai-draft')[0].props.onChange({target:{value:'Japan capital'}});
  h.find('form')[0].props.onSubmit({preventDefault(){}});await tick();
  assert.equal(calls[0].knowledgeOnly,true);
  h.find('input',p=>p.type==='checkbox' && !p['aria-label'])[0].props.onChange({target:{checked:false}});
  const strict=h.find('input',p=>p['aria-label']==='Только по знаниям')[0];
  assert.equal(strict.props.checked,false);assert.equal(strict.props.disabled,true);
  h.find('textarea',p=>p.id==='ai-draft')[0].props.onChange({target:{value:'Next question'}});
  h.find('form')[0].props.onSubmit({preventDefault(){}});await tick();
  assert.equal(calls[1].knowledgeOnly,false);assert.equal(calls[1].useKnowledge,false);
  assert.ok(calls[1].messages.every(m=>Object.keys(m).sort().join(',')==='content,role'));
  assert.equal(h.find('details',p=>p.className==='ai-sources').length,2);
});


test('internet search defaults off, is explicit and cannot combine with knowledge-only',async()=>{
  const calls=[];
  const h=harness(async(command,args)=>{
    if(command==='get_ai_status')return {available:true,models:['qwen3:8b']};
    if(command==='chat_ai'){calls.push(args);return {message:{role:'assistant',content:'Tokyo'},sources:[{id:'web-1',title:'Japan',source:'https://example.org',url:'https://example.org',excerpt:'Tokyo'}],answer_mode:'web',cited_source_ids:['web-1']};}
    throw Error(command);
  });
  h.render();await tick();
  assert.equal(h.find('input',p=>p['aria-label']==='Интернет-поиск')[0].props.checked,false);
  h.find('input',p=>p['aria-label']==='Только по знаниям')[0].props.onChange({target:{checked:true}});
  h.find('input',p=>p['aria-label']==='Интернет-поиск')[0].props.onChange({target:{checked:true}});
  const strict=h.find('input',p=>p['aria-label']==='Только по знаниям')[0];
  assert.equal(strict.props.checked,false);assert.equal(strict.props.disabled,true);
  h.find('textarea',p=>p.id==='ai-draft')[0].props.onChange({target:{value:'Japan capital'}});
  h.find('form')[0].props.onSubmit({preventDefault(){}});await tick();
  assert.equal(calls[0].useWeb,true);assert.equal(calls[0].knowledgeOnly,false);
  assert.equal(h.find('a')[0].props.href,'https://example.org');
});

test('model download first installs/starts runtime and stops if preparation fails',async()=>{
  const calls=[];let fail=true;
  const h=harness(async(command,args)=>{
    calls.push(command);
    if(command==='get_ai_status')return {available:false,models:[]};
    if(command==='start_local_ai' && fail)throw Error('runtime checksum failed');
    return 'ready';
  });
  h.render();await tick();
  const click=()=>h.find('button',p=>p.children==='Скачать выбранного Шерлока')[0].props.onClick();
  click();click();await tick();
  assert.equal(calls.filter(c=>c==='start_local_ai').length,1);
  assert.equal(calls.filter(c=>c==='install_sherlock').length,0);
  fail=false;click();await tick();
  assert.deepEqual(calls.slice(-3),['start_local_ai','install_sherlock','get_ai_status']);
});


test('quick-start prompts populate the composer without sending a request',async()=>{
  const calls=[];
  const h=harness(async(command,args)=>{
    calls.push({command,args});
    if(command==='get_ai_status')return {available:true,models:['qwen3:8b']};
    throw Error(command);
  });
  h.render();await tick();
  const prompt=h.find('button',p=>p.children==='Разобрать таблицу')[0];
  assert.ok(prompt);
  prompt.props.onClick();
  assert.equal(h.find('textarea',p=>p.id==='ai-draft')[0].props.value,
    'Разбери эту таблицу и кратко объясни, что означают её столбцы.');
  assert.equal(calls.filter(call=>call.command==='chat_ai').length,0);
  const settings=h.find('details',p=>(p.className||'').includes('assistant-settings'))[0];
  assert.ok(settings);
  assert.equal(settings.props.open,undefined,'advanced controls stay collapsed by default');
});
