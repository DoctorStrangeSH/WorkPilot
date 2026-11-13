const {test} = require("node:test");
const assert = require("node:assert/strict");
require("../browser-extension/tab_discovery.js");

const mappings = {
  inventory: {origin:"https://inventory.corp.example",pathPrefix:"/orders"},
  datalens: {origin:"https://analytics.corp.example",pathPrefix:"/"},
  asgard: {origin:"https://asgard.corp.example",pathPrefix:"/reverse-flow"}
};
const permissions = [
  "https://inventory.corp.example/*",
  "https://analytics.corp.example/*",
  "https://asgard.corp.example/*"
];

test("discovers already-open tabs only through exact user-confirmed origins and paths",()=>{
  const result=MaleniaTabDiscovery.discover([
    {id:7,windowId:1,active:true,title:"Inventory",url:"https://inventory.corp.example/orders?token=SECRET#row"},
    {id:8,windowId:1,title:"Analytics",url:"https://analytics.corp.example/dashboard"},
    {id:9,windowId:1,title:"Asgard",url:"https://asgard.corp.example/reverse-flow/box"},
    {id:10,title:"Wrong path",url:"https://inventory.corp.example/admin"},
    {id:11,title:"Lookalike host",url:"https://inventory.corp.example.attacker.test/orders"},
    {id:12,title:"Unknown",url:"https://other.corp.example/orders"}
  ],mappings,permissions);
  assert.equal(result.roles.inventory.state,"unique");
  assert.equal(result.roles.inventory.candidates[0].tabId,7);
  assert.equal(result.roles.inventory.candidates[0].sanitizedUrl,
    "https://inventory.corp.example/orders");
  assert.equal(result.roles.datalens.state,"unique");
  assert.equal(result.roles.asgard.state,"unique");
  assert.ok(!JSON.stringify(result).includes("SECRET"));
});

test("duplicate matching tabs are reported as ambiguous, never silently selected",()=>{
  const result=MaleniaTabDiscovery.discover([
    {id:20,url:"https://inventory.corp.example/orders"},
    {id:21,active:true,url:"https://inventory.corp.example/orders/today"}
  ],mappings,permissions);
  assert.equal(result.roles.inventory.state,"ambiguous");
  assert.deepEqual(result.roles.inventory.candidates.map(x=>x.tabId),[21,20]);
});

test("missing host permission means no candidate is exposed",()=>{
  const result=MaleniaTabDiscovery.discover([
    {id:7,url:"https://inventory.corp.example/orders"}
  ],mappings,[]);
  assert.equal(result.roles.inventory.state,"not_found");
});

test("rejects non-HTTPS, credential-bearing and malformed user mappings",()=>{
  for (const origin of [
    "http://inventory.corp.example",
    "https://user:pass@inventory.corp.example",
    "https://inventory.corp.example:8443",
    "https://inventory.corp.example/path"
  ]) {
    assert.throws(()=>MaleniaTabDiscovery.normalizeMapping({
      ...mappings,inventory:{origin}
    }));
  }
});

test("rejects unsafe path prefixes and unknown resource roles",()=>{
  assert.throws(()=>MaleniaTabDiscovery.normalizeMapping({
    ...mappings,inventory:{origin:mappings.inventory.origin,pathPrefix:"/orders/../admin"}
  }));
  assert.throws(()=>MaleniaTabDiscovery.normalizeMapping({...mappings,mail:{origin:"https://mail.example"}}));
});

test("ignores browser-internal pages, credentials, unsafe protocols and invalid tab IDs",()=>{
  const result=MaleniaTabDiscovery.discover([
    {id:1,url:"chrome://settings"},
    {id:2,url:"https://user:pass@inventory.corp.example/orders"},
    {id:3,url:"http://inventory.corp.example/orders"},
    {id:-1,url:"https://inventory.corp.example/orders"},
    {id:4,url:"https://inventory.corp.example/orders"}
  ],mappings,permissions);
  assert.deepEqual(result.roles.inventory.candidates.map(x=>x.tabId),[4]);
});
