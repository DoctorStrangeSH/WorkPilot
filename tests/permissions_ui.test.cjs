const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const desktopRequire = Module.createRequire(path.resolve(__dirname, '../desktop/package.json'));
const ts = desktopRequire('typescript');
const React = desktopRequire('react');
const {renderToStaticMarkup} = desktopRequire('react-dom/server');
const filename = path.resolve(__dirname, '../desktop/src/PermissionsPage.tsx');
const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: {module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022},
});
const component = new Module(filename, module);
component.filename = filename;
component.paths = Module._nodeModulePaths(path.dirname(filename));
component._compile(compiled.outputText, filename);
const {PermissionsPage} = component.exports;
const request = {
  id: 'fixture', binding: 'a'.repeat(64), capability: 'browser.read_text',
  tab_id: 7, document_id: 'document-fixture', parameters: {selector: 'main'},
  status: 'pending', expires_at: 9999999999, remaining_seconds: 60,
};
const render = (overrides = {}, props = {}) => renderToStaticMarkup(React.createElement(PermissionsPage, {
  requests: [{...request, ...overrides}], connected: true, busy: false,
  onDecide() { throw new Error('Render must never submit a decision'); }, ...props,
}));

test('pending permission exposes two explicit decisions and exact action details', () => {
  const html = render();
  assert.equal((html.match(/<button/g) || []).length, 2);
  assert.doesNotMatch(html, /<button[^>]*disabled/);
  assert.match(html, /document-fixture/);
  assert.match(html, /selector/);
  assert.match(html, /main/);
});

test('approved permission exposes only revocation', () => {
  const html = render({status: 'approved'});
  assert.equal((html.match(/<button/g) || []).length, 1);
  assert.match(html, /class="danger"/);
});

test('terminal or zero-lifetime permissions expose no decision buttons', () => {
  for (const status of ['denied', 'revoked', 'consumed', 'expired']) {
    assert.doesNotMatch(render({status}), /<button/);
  }
  assert.doesNotMatch(render({remaining_seconds: 0}), /<button/);
});

test('busy or disconnected panel cannot submit a decision', () => {
  for (const props of [{busy: true}, {connected: false}]) {
    const html = render({}, props);
    assert.equal((html.match(/<button[^>]*disabled/g) || []).length, 2);
  }
});

test('document identity and parameters render as escaped text', () => {
  const html = render({document_id: '<img src=x onerror=alert(1)>',
    parameters: {selector: '<script>alert(1)</script>'}});
  assert.doesNotMatch(html, /<script>|<img/);
  assert.match(html, /&lt;script&gt;/);
});

test('empty and disconnected views have no decision buttons', () => {
  assert.doesNotMatch(render({}, {requests: []}), /<button/);
  assert.match(render({}, {requests: [], connected: false}), /role="status"/);
});
