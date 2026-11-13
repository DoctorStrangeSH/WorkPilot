const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const app = fs.readFileSync(path.resolve(__dirname, '../desktop/src/App.tsx'), 'utf8');

test('assistant is a first-class workspace destination', () => {
  assert.match(app, /label="Ассистент" active=\{page==="ai"\}/);
  assert.match(app, /useState<Page>\("ai"\)/);
  assert.match(app, /label="Моя рабочая среда" active=\{page==="browser"\}/);
  assert.doesNotMatch(app, /<Nav[^\n]*label="Проверка заказа"/);
  assert.doesNotMatch(app, /<Nav[^\n]*label="Список заказов"/);
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


test('connections are visible and reachable from the primary navigation', () => {
  assert.match(app, /<Nav icon=\{<Plug\/>\} label="Подключения" active=\{page==="sources"\}/);
  assert.match(app, /<SourcesPage tabs=\{data\?\.browser_tabs\?\?\[\]\} connected=\{connected\} agentBusy=\{busy\} onStartAgent=\{runAgent\}/);
  assert.match(app, /Запустить агента/);
  assert.match(app, /Google OAuth Desktop Client ID/);
});

test('sources page shows truthful connection state and generic resource onboarding', () => {
  assert.doesNotMatch(app, /<Nav[^\\n]*label="Источники"/);
  assert.match(app, /Google Sheets · ИНВента/);
  assert.match(app, /ChatGPT не передаёт свои подключения Malenia/);
  assert.match(app, /Другие рабочие системы/);
  assert.match(app, /подключение к рабочим страницам и системам/);
  assert.match(app, /Инвентаризация — первый проверочный сценарий/);
  assert.match(app, /Открыть Browser Bridge/);
  assert.doesNotMatch(app, /с каждого из трёх явно разрешённых сайтов/);
});

test('Google Sheets onboarding is explicitly read-only and calls the native connector', () => {
  assert.match(app, /Google OAuth Desktop Client ID/);
  assert.match(app, /Google Sheets подключается отдельно только для чтения/);
  assert.match(app, /connect_google_sheets/);
  assert.match(app, /get_google_sheets_status/);
  assert.doesNotMatch(app, /invoke[^\n]*read_google_sheet/);
  assert.match(app, /disconnect_google_sheets/);
  assert.match(app, /Исходные данные остаются нетронутыми/);
  assert.doesNotMatch(app, /write_google_sheet|update_google_sheet/);
});


test('expired Google refresh tokens return the user to a safe reauthorization flow', () => {
  assert.match(app, /reauthorization_required/);
  assert.match(app, /sheetsStatus\.status==="reauthorization_required"/);
  assert.match(app, /result\.client_id/);
  assert.match(app, /Требуется повторная авторизация/);
});


test('offline order-checking skill is reachable and has no write actions', () => {
  assert.doesNotMatch(app, /<Nav[^\n]*label="Проверка заказа"/);
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
  assert.doesNotMatch(app, /<Nav[^\n]*label="Список заказов"/);
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
  assert.match(native, /browser_audit, browser_audit_job, permissions/);
});

test('desktop audit launch is a real command with visible queued and running states',()=>{
  assert.match(app, /invoke\("request_browser_audit"\)/);
  assert.match(app, /data-testid="browser-audit-runner"/);
  assert.match(app, /job\?\.status==="pending"/);
  assert.match(app, /job\?\.status==="running"/);
  assert.match(app, /onRequested\(\)/);
  const native=fs.readFileSync(path.resolve(__dirname,'../desktop/src-tauri/src/main.rs'),'utf8');
  assert.match(native, /fn request_browser_audit\(/);
  assert.match(native, /\/v1\/browser\/audit-request/);
  assert.match(native, /\/v1\/browser\/audit-job/);
});

test('browser workspace displays safe progress without order identifiers',()=>{
  assert.match(app,/data-testid="browser-audit-progress"/);
  assert.match(app,/job\.completed_sources/);
  assert.match(app,/job\.attention_sources/);
  assert.match(app,/job\.failed_role/);
  assert.match(app,/Обработано источников/);
});

test('skills are a first-class reviewed workspace not an inventory-only workflow',()=>{
  assert.match(app,/label="Навыки" active=\{page==="skills"\}/);
  assert.match(app,/<SkillsPage connected=\{connected\}\/>/);
  const skills=fs.readFileSync(path.resolve(__dirname,'../desktop/src/SkillsPage.tsx'),'utf8');
  assert.match(skills,/get_skills/);
  assert.match(skills,/skill_action/);
  assert.match(skills,/Сохранить черновик/);
  assert.match(skills,/Утвердить/);
  assert.match(skills,/Веса Qwen не переобучаются/);
  const ai=fs.readFileSync(path.resolve(__dirname,'../desktop/src/AiPage.tsx'),'utf8');
  assert.match(ai,/skill_ids:reply\.skill_ids/);
  assert.match(ai,/Полезен/);
  assert.match(ai,/Не помог/);
});

test('Sherlock can suggest an editable skill but cannot activate it without review',()=>{
  const ai=fs.readFileSync(path.resolve(__dirname,'../desktop/src/AiPage.tsx'),'utf8');
  assert.match(ai,/invoke<\{suggestion:/);
  assert.match(ai,/"suggest_skill"/);
  assert.match(ai,/Сделать навык из ответа/);
  assert.match(ai,/Сохранить на проверку/);
  assert.match(ai,/Шерлок предлагает новый навык/);
  assert.match(ai,/action:"draft"/);
  const native=fs.readFileSync(path.resolve(__dirname,'../desktop/src-tauri/src/main.rs'),'utf8');
  assert.match(native,/fn suggest_skill\(/);
  assert.match(native,/\/v1\/skills\/suggest/);
});

test('Sherlock offers automatic thinking depth for complex work',()=>{
  const ai=fs.readFileSync(path.resolve(__dirname,'../desktop/src/AiPage.tsx'),'utf8');
  assert.match(ai,/setReasoningMode/);
  assert.match(ai,/reasoningMode\}\)/);
  assert.match(ai,/Автоматически — глубже для сложных задач/);
  assert.match(ai,/Глубоко — больше анализа, медленнее/);
  const native=fs.readFileSync(path.resolve(__dirname,'../desktop/src-tauri/src/main.rs'),'utf8');
  assert.match(native,/reasoning_mode: Option<String>/);
  assert.match(native,/"reasoning_mode": reasoning_mode\.unwrap_or_else/);
});
