const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../browser-extension/popup.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
function popup(url = 'https://example.com/orders?secret=remove#private') {
  const nodes = Object.fromEntries(['status', 'share', 'retry', 'inspect'].map(id => [id, {
    disabled: true, textContent: '', className: '', handlers: {},
    addEventListener(type, callback) { this.handlers[type] = callback; }
  }]));
  const calls = [], timers = new Map();
  let sequence = 0, queries = 0;
  const chrome = {
    runtime: {lastError: null, sendNativeMessage(host, message, callback) { calls.push({host, message, callback}); }},
    tabs: {async query() { queries++; return [{id: 7, title: 'x'.repeat(400), url}]; }},
    scripting: {async executeScript() {return [{result:'Тестовая строка заказов'}];}}
  };
  vm.runInNewContext(source, {document: {getElementById: id => nodes[id]}, chrome, URL,
    crypto: {randomUUID: () => 'request-id'},
    setTimeout: callback => {timers.set(++sequence, callback); return sequence;},
    clearTimeout: id => timers.delete(id)});
  return {nodes, calls, timers, get queries() {return queries;},
    async reply(index, response, error) {
      chrome.runtime.lastError = error ? {message: error} : null;
      calls[index].callback(response);
      chrome.runtime.lastError = null;
      await flush();
    }, async click(id) {nodes[id].handlers.click(); await flush();},
    async timeout() {for (const [id, callback] of [...timers]) {timers.delete(id); callback();} await flush();}
  };
}
const hello = {ok: true, host: 'com.malenia.browser'};

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
  assert.equal(p.calls[1].message.type, 'inspect_active_page');
  assert.equal(p.calls[1].message.page.url, 'https://example.com/orders');
  assert.equal(p.calls[1].message.page.text, 'Тестовая строка заказов');
  await p.reply(1, {ok:true, type:'page_inspected', characters:23, persisted:false});
  assert.match(p.nodes.status.textContent, /Автоматическая сверка заказов пока не подключена/);
});
