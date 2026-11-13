const {test} = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const MaleniaTabDiscovery = require("../browser-extension/tab_discovery.js");
const source = fs.readFileSync(path.join(__dirname,"../browser-extension/popup.js"),"utf8");
const flush = () => new Promise(resolve => setImmediate(resolve));

function makeNode() {
  return {disabled:false,textContent:"",className:"",value:"",attributes:{},children:[],handlers:{},
    addEventListener(type,fn){this.handlers[type]=fn;},
    setAttribute(k,v){this.attributes[k]=v;},
    appendChild(node){this.children.push(node);},
    replaceChildren(...nodes){this.children=[...nodes];}
  };
}
function setup({tabs,origins,changeOnGet,storedMappings}={}) {
  const ids=["status","share","shareAll","retry","inspect","auditStatus","discoverTabs",
    "confirmTabs","discoveryResults","discoveryStatus","mapInventory","mapDatalens","mapAsgard"];
  const nodes=Object.fromEntries(ids.map(id=>[id,makeNode()]));
  const nativeCalls=[], local={}, session={};
  let currentTabs=(tabs||[
    {id:1,title:"Orders",url:"https://inventory.example/orders?secret=1"},
    {id:2,title:"Analytics",url:"https://datalens.example/dashboard"},
    {id:3,title:"Asgard",url:"https://asgard.example/flow"}
  ]).map(x=>({...x}));
  const granted=origins||["https://inventory.example/*","https://datalens.example/*","https://asgard.example/*"];
  if(storedMappings) local.maleniaUserResourceMappings=storedMappings;
  const chrome={
    runtime:{lastError:null,sendNativeMessage(host,message,callback){nativeCalls.push({host,message,callback});}},
    tabs:{
      async query(){return currentTabs.map(x=>({...x}));},
      async get(id){
        if(changeOnGet==="closed") throw new Error("No tab");
        const tab=currentTabs.find(x=>x.id===id);
        if(!tab) throw new Error("No tab");
        if(changeOnGet==="navigated" && id===1) return {...tab,url:"https://attacker.example/phish"};
        return {...tab};
      }
    },
    permissions:{async getAll(){return {origins:[...granted]};}},
    storage:{
      local:{async get(key){return {[key]:local[key]};},async set(value){Object.assign(local,value);}},
      session:{async set(value){Object.assign(session,value);}}
    }
  };
  vm.runInNewContext(source,{document:{getElementById:id=>nodes[id],createElement:()=>makeNode()},
    chrome,URL,crypto:{randomUUID:()=>"id"},MaleniaTabDiscovery,
    setTimeout,clearTimeout,Date,Promise,console});
  return {nodes,nativeCalls,local,session,
    async connect(){nativeCalls[0].callback({ok:true,host:"com.malenia.browser"});await flush();},
    async discover(){
      for(const [id,value] of Object.entries({
        mapInventory:"https://inventory.example/orders",
        mapDatalens:"https://datalens.example/dashboard",
        mapAsgard:"https://asgard.example/flow"
      })) nodes[id].value=value;
      await nodes.discoverTabs.handlers.click();await flush();
    },
    async chooseAll(){
      for(const section of nodes.discoveryResults.children) {
        const button=section.children.find(x=>x.className==="discovery-candidate");
        if(button) {button.handlers.click();await flush();}
      }
    },
    async confirm(){await nodes.confirmTabs.handlers.click();await flush();}
  };
}

test("explicit mapping discovers current tabs and requires three user selections",async()=>{
  const p=setup();await p.connect();await p.discover();
  assert.equal(p.nodes.discoveryResults.children.length,3);
  assert.equal(p.nodes.confirmTabs.disabled,true);
  await p.chooseAll();
  assert.equal(p.nodes.confirmTabs.disabled,false);
  await p.confirm();
  assert.ok(p.local.maleniaUserResourceMappings);
  assert.deepEqual(Object.keys(p.session.maleniaConfirmedOpenTabs.confirmed).sort(),
    ["asgard","datalens","inventory"]);
  assert.equal(p.session.maleniaConfirmedOpenTabs.browserSessionOnly,true);
  assert.equal(p.nodes.discoveryStatus.className,"status ok");
});

test("duplicate candidates are shown separately and none is silently selected",async()=>{
  const p=setup({tabs:[
    {id:1,title:"Orders A",url:"https://inventory.example/orders"},
    {id:4,title:"Orders B",url:"https://inventory.example/orders/second"},
    {id:2,url:"https://datalens.example/dashboard"},
    {id:3,url:"https://asgard.example/flow"}
  ]});
  await p.connect();await p.discover();
  assert.equal(p.nodes.discoveryResults.children[0].children.filter(x=>x.className==="discovery-candidate").length,2);
  assert.equal(p.nodes.confirmTabs.disabled,true);
});

test("revoked permission prevents confirmation",async()=>{
  const p=setup({origins:["https://datalens.example/*","https://asgard.example/*"]});
  await p.connect();await p.discover();await p.chooseAll();await p.confirm();
  assert.equal(p.session.maleniaConfirmedOpenTabs,undefined);
  assert.equal(p.nodes.discoveryStatus.className,"status error");
});

test("closed tab invalidates the candidate before confirmation",async()=>{
  const p=setup({changeOnGet:"closed"});await p.connect();await p.discover();await p.chooseAll();await p.confirm();
  assert.equal(p.session.maleniaConfirmedOpenTabs,undefined);
  assert.match(p.nodes.discoveryStatus.textContent,/закрыта/);
});

test("navigation after discovery invalidates the candidate before confirmation",async()=>{
  const p=setup({changeOnGet:"navigated"});await p.connect();await p.discover();await p.chooseAll();await p.confirm();
  assert.equal(p.session.maleniaConfirmedOpenTabs,undefined);
  assert.match(p.nodes.discoveryStatus.textContent,/изменилась/);
});

test("query strings and fragments are not stored in confirmed tab references",async()=>{
  const p=setup();await p.connect();await p.discover();await p.chooseAll();await p.confirm();
  const saved=JSON.stringify(p.session.maleniaConfirmedOpenTabs);
  assert.doesNotMatch(saved,/secret|\?/);
});
