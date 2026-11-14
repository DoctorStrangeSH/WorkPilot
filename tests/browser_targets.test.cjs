const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const automation = fs.readFileSync(path.resolve(__dirname,'../browser-extension/automation.js'),'utf8');
const setup = fs.readFileSync(path.resolve(__dirname,'../browser-extension/targets.js'),'utf8');
const flush = () => new Promise(resolve=>setImmediate(resolve));
function screen(granted=true) {
  const names = ['targetInventory','targetDatalens','targetAsgard','saveTargets','targetsStatus'];
  const nodes=Object.fromEntries(names.map(name=>[name,{value:'',textContent:'',className:'',disabled:false,
    addEventListener(event,handler){this[event]=handler;}}]));
  let stored=null, requested=0;
  const chrome={storage:{local:{async get(){return {};},async set(value){stored=value;}}},
    permissions:{async request({origins}){requested++; assert.equal(origins.length,3);return granted;}}};
  const ctx={URL,chrome,document:{getElementById:id=>nodes[id]}};
  vm.createContext(ctx);vm.runInContext(automation,ctx);vm.runInContext(setup,ctx);
  nodes.targetInventory.value='https://docs.google.com/spreadsheets/d/example';
  nodes.targetDatalens.value='https://analytics.example/dashboard';
  nodes.targetAsgard.value='https://asgard.example/returns';
  return {nodes,click:async()=>{await nodes.saveTargets.click();await flush();},
    get stored(){return stored;},get requested(){return requested;}};
}
test('user explicitly saves three read-only sources and requests scoped permission',async()=>{
  const ui=screen();await ui.click();
  assert.equal(ui.requested,1);
  assert.equal(ui.stored.maleniaTargets.datalens,'https://analytics.example/dashboard');
  assert.equal(ui.stored.maleniaExactGetSearch,true);
  assert.match(ui.nodes.targetsStatus.textContent,/Готово/);
});
test('denied permission never persists target URLs',async()=>{
  const ui=screen(false);await ui.click();
  assert.equal(ui.stored,null);
  assert.match(ui.nodes.targetsStatus.textContent,/не предоставлены/);
});
test('URLs with embedded credentials or query parameters fail before permission request',async()=>{
  const ui=screen();ui.nodes.targetAsgard.value='https://username:password@asgard.example/orders?token=secret';
  await ui.click();
  assert.equal(ui.requested,0);assert.equal(ui.stored,null);
  assert.doesNotMatch(ui.nodes.targetsStatus.textContent,/username|secret/);
});
