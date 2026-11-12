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
  assert.match(app, /Ручная передача отправляет только заголовок и очищенный URL/);
  assert.match(app, /автоматический обход читает видимый текст/);
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


test('offline order-checking skill is reachable and has no write actions', () => {
  assert.match(app, /label="Проверка заказа" active=\{page==="orders"\}/);
  assert.match(app, /<OrderCheckPage connected=\{connected\}\/>/);
  const order = fs.readFileSync(path.resolve(__dirname, '../desktop/src/OrderCheckPage.tsx'), 'utf8');
  assert.match(order, /invoke<Preview>\("preview_order"/);
  assert.match(order, /"В пути"/);
  assert.match(order, /"Принят на ФФ"/);
  assert.match(order, /outcome\?\.comment/);
  assert.match(order, /ничего не отправляет в эти системы/);
  assert.match(order, /Строка в ИНВенте не изменена/);
  assert.doesNotMatch(order, /update_sheet|write_sheet|fetch\(/);
});


test('bulk Excel preview preserves source read-only and escapes formulas', () => {
  assert.match(app, /label="Список заказов" active=\{page==="order_batch"\}/);
  assert.match(app, /<OrderBatchPage connected=\{connected\}\/>/);
  const bulk = fs.readFileSync(path.resolve(__dirname, '../desktop/src/OrderBatchPage.tsx'), 'utf8');
  assert.match(bulk, /invoke<BatchResponse>\("preview_order_batch"/);
  assert.match(bulk, /navigator\.clipboard\.writeText\(report\(batch\)\)/);
  assert.match(bulk, /Ни одна строка в исходном Excel не изменена/);
  assert.match(bulk, /Максимум 100|максимум 100|100 строк/);
  assert.match(bulk, /safeCell/);
  assert.doesNotMatch(bulk, /write_google_sheet|update_google_sheet|fetch\(/);
});


test('bulk paste rejects incomplete source evidence rather than silently ignoring it', () => {
  const bulk = fs.readFileSync(path.resolve(__dirname, '../desktop/src/OrderBatchPage.tsx'), 'utf8');
  assert.match(bulk, /\(scanned\|\|sc\|\|result\).*\(!scanned\|\|!sc\|\|!result\)/);
  assert.match(bulk, /для скана нужны все три поля/);
  assert.match(bulk, /!status&&\(box\|\|history\|\|issued\)/);
  assert.match(bulk, /status!=="В пути"&&\(box\|\|history\|\|issued\)/);
  assert.match(bulk, /ID коробки и расширенная история допустимы только/);
});

test('browser workspace shows aggregate-only completed audit with no source rows', () => {
  assert.match(app, /browser_audit:BrowserAudit\|null/);
  assert.match(app, /audit=\{data\?\.browser_audit\?\?null\}/);
  assert.match(app, /data-testid="browser-audit-summary"/);
  assert.match(app, /audit\.summary\.found/);
  assert.match(app, /audit\.summary\.in_progress/);
  assert.match(app, /audit\.summary\.manual_review/);
  assert.match(app, /только предложения, не изменения статусов/);
  const native = fs.readFileSync(path.resolve(__dirname, '../desktop/src-tauri/src/main.rs'), 'utf8');
  assert.match(native, /\/v1\/browser\/audit-summary/);
  assert.match(native, /browser_audit, permissions/);
});
