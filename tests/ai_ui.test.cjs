const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const localRequire = Module.createRequire(path.resolve(__dirname, '../desktop/package.json'));
const ts = localRequire('typescript');

function harness(invoke) {
  const slots = []; let cursor = 0;
  const hooks = {
    useState(initial) {const i=cursor++;if(!(i in slots))slots[i]=initial;return [slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}];},
    useRef(initial) {const i=cursor++;if(!(i in slots))slots[i]={current:initial};return slots[i];},
    useEffect(fn,deps) {const i=cursor++;if(!slots[i] || deps.some((v,n)=>v!==slots[i][n])){slots[i]=deps;fn();}},
  };
  const filename=path.resolve(__dirname,'../desktop/src/AiPage.tsx');
  const component=new Module(filename,module);
  component.filename=filename;component.paths=Module._nodeModulePaths(path.dirname(filename));
  const original=component.require.bind(component);
  component.require=name=>name==='react'?hooks:name==='@tauri-apps/api/core'?{invoke}:original(name);
  component._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,filename);
  let refreshed=0;
  const render=()=>{cursor=0;return component.exports.AiPage({connected:true,onTaskCreated:()=>refreshed++});};
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
  const input=h.find('input')[0];
  assert.equal(input.props.value,'Plan my work');
  input.props.onChange({target:{value:'Reviewed title'}});
  let save=h.find('button',p=>p.children==='Добавить в очередь')[0];
  save.props.onClick();save.props.onClick();await tick();
  assert.equal(saves.length,1);
  assert.equal(saves[0].title,'Reviewed title');
  assert.equal(saves[0].description,'Review this plan');
  assert.match(saves[0].requestId,/^[a-f0-9-]{36}$/);
  assert.equal(h.find('input')[0].props.disabled,true);
  fail=false;
  h.find('button',p=>p.children==='Добавить в очередь')[0].props.onClick();await tick();
  assert.deepEqual(saves[1],saves[0]);
  assert.equal(h.find('input').length,0);
  assert.equal(h.refreshed(),1);
});
