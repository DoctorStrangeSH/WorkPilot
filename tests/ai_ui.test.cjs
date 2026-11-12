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
  h.find('input')[0].props.onChange({target:{value:'C:\\ChosenNotes'}});
  assert.equal(calls.filter(c=>c.command==='knowledge_action').length,0);
  h.find('button',p=>p.children==='Импортировать выбранную папку')[0].props.onClick();await tick();
  const imports=calls.filter(c=>c.command==='knowledge_action');
  assert.equal(imports.length,1);assert.equal(imports[0].args.action,'import');
  assert.equal(imports[0].args.payload.folder,'C:\\ChosenNotes');
});
