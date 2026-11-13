const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const MaleniaTabDiscovery = require('../browser-extension/tab_discovery.js');
const source = fs.readFileSync(path.join(__dirname, '../browser-extension/popup.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
function popup(url = 'https://example.com/orders?secret=remove#private', options = {}) {
  const nodes = Object.fromEntries(['status', 'share', 'shareAll', 'retry', 'inspect', 'auditStatus', 'discoverTabs', 'confirmTabs', 'inspectMappedTabs', 'discoveryResults', 'discoveryStatus', 'mapInventory', 'mapDatalens', 'mapAsgard'].map(id => [id, {
    disabled: true, textContent: '', className: '', handlers: {},
    addEventListener(type, callback) { this.handlers[type] = callback; }
  }]));
  const calls = [], timers = new Map();
  let sequence = 0, queries = 0;
  const requestedOrigins = [];
  const chrome = {
    runtime: {lastError: null, sendNativeMessage(host, message, callback) { calls.push({host, message, callback}); }},
    tabs: {async query() { queries++; return [{id: 7, title: 'x'.repeat(400), url}]; }},
    permissions: {async getAll() {return {origins: []};}, async request(value) {requestedOrigins.push(value); return options.permissionGranted !== false;}},
    storage: {local: {async get() {return {};}, async set() {}}, session: {async set() {}, async get() {return {};}}},
    scripting: {async executeScript() {if (options.pageError) throw new Error(options.pageError); return [{result:{title:'Orders',table_headers:['Order ID','Status'],tables:[{kind:'html-table',columns:['Order ID','Status'],visible_rows:3,declared_rows:3}],search_labels:['Search'],has_aria_grid:true,virtualized:false,login_required:false}}];}}
  };
  vm.runInNewContext(source, {document: {getElementById: id => nodes[id], createElement: () => ({addEventListener(){},setAttribute(){},appendChild(){}})}, chrome, URL, MaleniaTabDiscovery,
    crypto: {randomUUID: () => 'request-id'},
    setTimeout: callback => {timers.set(++sequence, callback); return sequence;},
    clearTimeout: id => timers.delete(id)});
  return {nodes, calls, timers, requestedOrigins, get queries() {return queries;},
    async reply(index, response, error) {
      chrome.runtime.lastError = error ? {message: error} : null;
      calls[index].callback(response);
      chrome.runtime.lastError = null;
      await flush();
    }, async click(id) {nodes[id].handlers.click(); await flush();},
    async timeout() {for (const [id, callback] of [...timers]) {timers.delete(id); callback();} await flush();}
  };
}
const hello = {ok: true, host: 'com.malenia.browser', capabilities:['share_active_tab','inspect_capabilities']};

test('hello and manual reconnect never read or share a tab', async () => {
  const p = popup();
  assert.equal(p.calls[0].message.type, 'hello');
  assert.equal(p.queries, 0);
  await p.reply(0, hello);
  assert.equal(p.nodes.share.disabled, false);
  await p.click('retry');
  assert.equal(p.calls[1].message.type, 'hello');
  assert.equal(p.nodes.share.disabled, true);
  await p.reply(1, hello);
  assert.equal(p.queries, 0);
  assert.equal(p.nodes.share.disabled, false);
});

test('missing host is actionable and explicit reconnect recovers', async () => {
  const p = popup();
  await p.reply(0, null, 'Specified native messaging host not found.');
  assert.match(p.nodes.status.textContent, /не найден/);
  assert.equal(p.nodes.share.disabled, true);
  assert.equal(p.nodes.retry.disabled, false);
  await p.click('retry');
  await p.reply(1, hello);
  assert.equal(p.nodes.share.disabled, false);
  assert.equal(p.queries, 0);
});

test('forbidden host is distinguished without printing raw errors', async () => {
  const p = popup();
  await p.reply(0, null, 'Access to the specified native messaging host is forbidden. secret=value');
  assert.match(p.nodes.status.textContent, /ID расширения/);
  assert.doesNotMatch(p.nodes.status.textContent, /secret=value/);
});

test('timeout unblocks retry and late callbacks cannot revive stale state', async () => {
  const p = popup();
  await p.timeout();
  assert.match(p.nodes.status.textContent, /5 секунд/);
  assert.equal(p.nodes.retry.disabled, false);
  await p.click('retry');
  await p.reply(0, hello);
  assert.equal(p.nodes.share.disabled, true);
  await p.reply(1, hello);
  assert.equal(p.nodes.share.disabled, false);
});

test('explicit share strips URL secrets, bounds title and sends once', async () => {
  const p = popup(); await p.reply(0, hello);
  await p.click('share'); await p.click('share');
  assert.equal(p.queries, 1);
  assert.equal(p.calls.length, 2);
  assert.equal(p.calls[1].message.tab.url, 'https://example.com/orders');
  assert.equal(p.calls[1].message.tab.title.length, 300);
  await p.reply(1, {ok: true});
  assert.equal(p.nodes.share.disabled, false);
});

test('sharing open tabs requires a click and sends sanitized metadata only', async () => {
  const p = popup();
  assert.equal(p.queries, 0);
  await p.reply(0, hello);
  assert.equal(p.nodes.shareAll.disabled, false);
  await p.click('shareAll');
  assert.equal(p.queries, 1);
  assert.equal(p.calls[1].message.type, 'share_active_tab');
  assert.equal(p.calls[1].message.tab.url, 'https://example.com/orders');
  assert.equal(p.calls[1].message.tab.title.length, 300);
  await p.reply(1, {ok:true});
  assert.match(p.nodes.status.textContent, /Передано вкладок: 1/);
});

test('uncertain share is never resent by reconnect', async () => {
  const p = popup(); await p.reply(0, hello); await p.click('share');
  await p.timeout();
  assert.match(p.nodes.status.textContent, /могла сохраниться/);
  assert.equal(p.nodes.share.disabled, true);
  await p.click('retry'); await p.reply(2, hello);
  assert.equal(p.calls.filter(c => c.message.type === 'share_active_tab').length, 1);
  assert.equal(p.queries, 1);
});

for (const url of ['file:///private/file', 'https://user:password@example.com/orders']) {
  test('unsafe URL is rejected without forwarding it: ' + new URL(url).protocol, async () => {
    const p = popup(url); await p.reply(0, hello); await p.click('share');
    assert.equal(p.calls.length, 1);
    assert.equal(p.nodes.share.disabled, false);
    assert.doesNotMatch(p.nodes.status.textContent, /password|private/);
  });
}

test('malformed handshake does not enable sharing', async () => {
  const p = popup(); await p.reply(0, {ok: true, host: 'unexpected'});
  assert.equal(p.nodes.share.disabled, true);
  assert.equal(p.nodes.retry.disabled, false);
});

test('page inspection requires explicit user click and never reads on handshake', async () => {
  const p = popup();
  assert.equal(p.queries, 0);
  await p.reply(0, hello);
  assert.equal(p.queries, 0);
  await p.click('inspect');
  assert.equal(p.queries, 1);
  assert.equal(p.calls[1].message.type, 'inspect_capabilities');
  assert.equal(p.calls[1].message.page.url, 'https://example.com/orders');
  assert.deepEqual(Array.from(p.calls[1].message.page.table_headers), ['Order ID','Status']);
  assert.equal(p.calls[1].message.page.tables[0].visible_rows, 3);
  assert.equal('text' in p.calls[1].message.page, false);
  await p.reply(1, {ok:true, type:'capabilities_inspected', persisted:false, page:{tables:[]}});
  assert.match(p.nodes.status.textContent, /Структурная диагностика завершена/);
  assert.match(p.nodes.auditStatus.textContent, /Order ID · Status/);
});

test('page inspection requests only the active HTTPS origin when host access is missing', async () => {
  const p = popup('https://orders.example.com/list?session=private', {
    pageError:'Cannot access contents of the page. Extension manifest must request permission.'
  });
  await p.reply(0, hello);
  await p.click('inspect');
  assert.deepEqual(p.requestedOrigins, [{origins:['https://orders.example.com/*']}]);
  assert.equal(p.calls[1].message.type, 'inspect_capabilities');
  await p.reply(1, {ok:true,type:'capabilities_inspected',persisted:false,
    page:{tables:[]}});
  assert.match(p.nodes.status.textContent, /Структурная диагностика завершена/);
  assert.doesNotMatch(p.nodes.auditStatus.textContent, /session|private/);
});

test('page inspection explains denied exact-origin permission without exposing browser error', async () => {
  const p = popup('https://orders.example.com/list?session=private', {
    pageError:'Cannot access contents of the page. Extension manifest must request permission.',
    permissionGranted:false
  });
  await p.reply(0, hello);
  await p.click('inspect');
  assert.match(p.nodes.auditStatus.textContent, /не предоставил.*доступ/);
  assert.match(p.nodes.status.textContent, /site_permission/);
  assert.doesNotMatch(p.nodes.auditStatus.textContent, /session|private|orders/);
  assert.equal(p.calls.length,1);
});

test('page inspection distinguishes local host schema rejection', async () => {
  const p = popup();
  await p.reply(0, hello);
  await p.click('inspect');
  await p.reply(1, {ok:false,error:'invalid_capability_snapshot'});
  assert.match(p.nodes.auditStatus.textContent, /Локальный агент отклонил диагностику/);
  assert.match(p.nodes.status.textContent, /host_response/);
});

test('handshake requires structural-inspection capability before enabling actions', async () => {
  const p = popup();
  await p.reply(0, {ok:true,host:'com.malenia.browser',capabilities:['share_active_tab']});
  assert.equal(p.nodes.share.disabled,true);
  assert.match(p.nodes.status.textContent,/не удалось проверить ответ/i);
});
