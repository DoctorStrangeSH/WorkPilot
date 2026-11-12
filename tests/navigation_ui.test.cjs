const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const app = fs.readFileSync(path.resolve(__dirname, '../desktop/src/App.tsx'), 'utf8');

test('assistant is a first-class workspace destination', () => {
  assert.match(app, /label="Ассистент" active=\{page==="ai"\}/);
  assert.match(app, /Открыть ассистента/);
  assert.doesNotMatch(app, /<Nav icon=\{<FileSearch\/>\} label="Поиск"/);
});

test('queued tasks are never presented as automatically executed', () => {
  assert.match(app, /Сохранены, но ещё не выполняются автоматически/);
  assert.match(app, /не запускаются автоматически/);
});

test('the navigation groups work, knowledge, safety and system areas', () => {
  assert.match(app, /РАБОЧЕЕ ПРОСТРАНСТВО/);
  assert.match(app, /ЗНАНИЯ И БЕЗОПАСНОСТЬ/);
  assert.match(app, /СИСТЕМА/);
});
