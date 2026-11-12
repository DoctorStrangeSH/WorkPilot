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


test('sources page shows truthful connection state and no fake connect actions', () => {
  assert.match(app, /label="Источники" active=\{page==="sources"\}/);
  assert.match(app, /Google Sheets · ИНВента/);
  assert.match(app, /ChatGPT не передаёт свои подключения Malenia/);
  assert.match(app, /Malenia пока не читает статусы или историю коробок/);
  assert.match(app, /Передаёт только заголовок и очищенный URL/);
  assert.match(app, /Открыть Browser Bridge/);
});


test('Google Sheets onboarding is explicitly read-only and calls the native connector', () => {
  assert.match(app, /Google OAuth Desktop Client ID/);
  assert.match(app, /spreadsheets\.readonly/);
  assert.match(app, /connect_google_sheets/);
  assert.match(app, /get_google_sheets_status/);
  assert.match(app, /read_google_sheet/);
  assert.match(app, /disconnect_google_sheets/);
  assert.match(app, /Никаких изменений в таблицу не внесено/);
  assert.doesNotMatch(app, /write_google_sheet|update_google_sheet/);
});


test('expired Google refresh tokens return the user to a safe reauthorization flow', () => {
  assert.match(app, /reauthorization_required/);
  assert.match(app, /google_reauthorization_required/);
  assert.match(app, /result\.client_id/);
  assert.match(app, /Требуется повторная авторизация/);
});
