#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod runtime_setup;

use rand::{rngs::OsRng, RngCore};
use serde::Serialize;
use serde_json::Value;
use std::{
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::Duration,
};
use tauri::{path::BaseDirectory, Manager, State};

const API_HOST: &str = "127.0.0.1";
const API_PORT: u16 = 8765;

#[derive(Default)]
struct AgentState {
    child: Mutex<Option<Child>>,
    token: Mutex<Option<String>>,
    ai_child: Mutex<Option<Child>>,
}


impl Drop for AgentState {
    fn drop(&mut self) {
        if let Ok(slot) = self.ai_child.get_mut() {
            if let Some(mut child) = slot.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
        if let Ok(child_slot) = self.child.get_mut() {
            if let Some(mut child) = child_slot.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

#[derive(Serialize)]
struct Dashboard {
    running: bool,
    resources: Value,
    tasks: Vec<Value>,
    events: Vec<Value>,
    browser_tabs: Vec<Value>,
    browser_audit: Value,
    browser_audit_job: Value,
    permissions: Vec<Value>,
}

fn api_get(token: &str, path: &str) -> Result<Value, String> {
    reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(3))
        .no_proxy()
        .build()
        .map_err(|error| format!("Не удалось создать HTTP-клиент: {error}"))?
        .get(format!("http://{API_HOST}:{API_PORT}{path}"))
        .header("Authorization", format!("Bearer {token}"))
        .send()
        .map_err(|error| format!("Локальный агент недоступен: {error}"))?
        .error_for_status()
        .map_err(|error| format!("Ошибка локального API: {error}"))?
        .json::<Value>()
        .map_err(|error| format!("Некорректный ответ локального API: {error}"))
}

fn api_post_json(token: &str, path: &str, payload: Value, timeout: Duration) -> Result<Value, String> {
    let response = reqwest::blocking::Client::builder()
        .timeout(timeout)
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| "Не удалось создать HTTP-клиент".to_string())?
        .post(format!("http://{API_HOST}:{API_PORT}{path}"))
        .header("Authorization", format!("Bearer {token}"))
        .json(&payload)
        .send()
        .map_err(|_| "Локальный агент недоступен. Результат не подтверждён".to_string())?;
    let status = response.status();
    let body = response.json::<Value>().map_err(|_| "Некорректный ответ локального API".to_string())?;
    if !status.is_success() {
        let code = body.get("error").and_then(Value::as_str).unwrap_or("google_sheets_request_failed");
        return Err(match code {
            "windows_credential_store_unavailable" => "Хранилище секретов Windows недоступно. Токены не будут сохранены в обычных файлах.".to_string(),
            "invalid_google_oauth_client_id" => "Проверьте формат Google OAuth Desktop Client ID.".to_string(),
            "google_sheets_not_connected" => "Сначала подключите Google Sheets.".to_string(),
            "google_reauthorization_required" => "[google_reauthorization_required] Доступ Google истёк или был отозван. Подключите Google Sheets заново.".to_string(),
            "invalid_spreadsheet_id" => "Некорректный ID таблицы Google Sheets.".to_string(),
            "invalid_spreadsheet_range" => "Проверьте диапазон ячеек (например, Orders!A1:Z100).".to_string(),
            "browser_audit_already_active" => "Проверка уже ожидает запуска или выполняется.".to_string(),
            "audit_job_unavailable" => "Очередь проверки браузера временно недоступна.".to_string(),
            _ => format!("Google Sheets: {code}"),
        });
    }
    Ok(body)
}

fn agent_directory() -> Result<PathBuf, String> {
    if let Ok(path) = std::env::var("MALENIA_AGENT_DIR") {
        return Ok(PathBuf::from(path));
    }
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../agent");
    if path.exists() {
        Ok(path)
    } else {
        Err("Не найдена папка Python-агента. Укажи MALENIA_AGENT_DIR.".to_string())
    }
}

#[tauri::command]
fn start_agent(app: tauri::AppHandle, state: State<'_, AgentState>) -> Result<String, String> {
    let mut child_guard = state.child.lock().map_err(|_| "Ошибка состояния агента".to_string())?;
    if let Some(child) = child_guard.as_mut() {
        if child.try_wait().map_err(|error| error.to_string())?.is_none() {
            return Ok("Агент уже запущен".to_string());
        }
        *child_guard = None;
    }

    if std::net::TcpStream::connect((API_HOST, API_PORT)).is_ok() {
        return Err("Порт 8765 занят другим процессом. Если Malenia уже открыта, перейди в её окно. Иначе останови свой отдельно запущенный агент; чужие процессы не завершаются автоматически.".to_string());
    }

    let mut random = [0_u8; 32];
    OsRng.fill_bytes(&mut random);
    let token = random.iter().map(|byte| format!("{byte:02x}")).collect::<String>();

    let packaged_agent = app
        .path()
        .resolve("resources/malenia-agent/malenia-agent.exe", BaseDirectory::Resource)
        .ok()
        .filter(|path| path.is_file());

    let mut command = if let Some(agent_path) = packaged_agent {
        Command::new(agent_path)
    } else {
        #[cfg(debug_assertions)]
        {
            let agent_dir = agent_directory()?;
            let python = std::env::var("MALENIA_PYTHON")
                .unwrap_or_else(|_| "python".to_string());
            let mut command = Command::new(python);
            command
                .arg("-m")
                .arg("malenia")
                .env("PYTHONPATH", &agent_dir)
                .current_dir(&agent_dir);
            command
        }
        #[cfg(not(debug_assertions))]
        {
            return Err(
                "Не найден встроенный Malenia Agent. Переустанови приложение.".to_string()
            );
        }
    };

    command
        .arg("--host")
        .arg(API_HOST)
        .arg("--port")
        .arg(API_PORT.to_string())
        .env("PYTHONUNBUFFERED", "1")
        .env("MALENIA_API_TOKEN", &token)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }

    let child = command
        .spawn()
        .map_err(|error| format!("Не удалось запустить Python Agent. Проверь Python 3.11+ и PATH: {error}"))?;

    *child_guard = Some(child);
    drop(child_guard);

    for _ in 0..30 {
        thread::sleep(Duration::from_millis(200));
        {
            let mut guard = state.child.lock().map_err(|_| "Ошибка состояния агента".to_string())?;
            if let Some(child) = guard.as_mut() {
                if child.try_wait().map_err(|error| error.to_string())?.is_some() {
                    *guard = None;
                    return Err("Malenia Agent завершился при запуске. Проверь порт 8765 и установку приложения.".to_string());
                }
            }
        }
        let ready = reqwest::blocking::Client::new()
            .get(format!("http://{API_HOST}:{API_PORT}/v1/resources"))
            .header("Authorization", format!("Bearer {token}"))
            .timeout(Duration::from_millis(500))
            .send()
            .map(|response| response.status().is_success())
            .unwrap_or(false);
        if ready {
            let compatible = api_get(&token, "/v1/runtime").map(|runtime| {
                runtime.get("release").and_then(Value::as_str) == Some(env!("CARGO_PKG_VERSION"))
                    && runtime.get("protocol").and_then(Value::as_u64) == Some(1)
                    && runtime.get("capabilities").and_then(Value::as_array)
                        .map(|items| ["task_idempotency", "explicit_knowledge", "knowledge_only", "public_search", "google_sheets_readonly"].iter().all(|cap| items.iter().any(|item| item.as_str() == Some(*cap))))
                        .unwrap_or(false)
            }).unwrap_or(false);
            if !compatible {
                if let Ok(mut guard) = state.child.lock() {
                    if let Some(mut child) = guard.take() { let _ = child.kill(); let _ = child.wait(); }
                }
                return Err("Обнаружены файлы агента другой версии. Закройте Малению и повторите установку обновления".to_string());
            }
            *state.token.lock().map_err(|_| "Ошибка состояния токена".to_string())? = Some(token);
            return Ok("Локальный агент запущен".to_string());
        }
    }

    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
    Err("Агент не ответил за 6 секунд. Проверь Python и порт 8765.".to_string())
}

#[tauri::command]
fn stop_agent(state: State<'_, AgentState>) -> Result<String, String> {
    let mut child_guard = state.child.lock().map_err(|_| "Ошибка состояния агента".to_string())?;
    if let Some(mut child) = child_guard.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
    *state.token.lock().map_err(|_| "Ошибка состояния токена".to_string())? = None;
    Ok("Локальный агент остановлен".to_string())
}

#[tauri::command]
fn get_dashboard(state: State<'_, AgentState>) -> Result<Dashboard, String> {
    let token = state.token.lock().map_err(|_| "Ошибка состояния токена".to_string())?
        .clone().ok_or_else(|| "Агент не запущен".to_string())?;

    let resources = api_get(&token, "/v1/resources")?.get("resources").cloned().unwrap_or(Value::Null);
    let tasks = api_get(&token, "/v1/tasks?limit=30")?.get("tasks").and_then(Value::as_array).cloned().unwrap_or_default();
    let events = api_get(&token, "/v1/events?limit=30")?.get("events").and_then(Value::as_array).cloned().unwrap_or_default();
    let browser_tabs = api_get(&token, "/v1/browser/tabs?limit=20")?.get("tabs").and_then(Value::as_array).cloned().unwrap_or_default();

    let permissions = api_get(&token, "/v1/permissions")?.get("permissions").and_then(Value::as_array).cloned().unwrap_or_default();
    let browser_audit = api_get(&token, "/v1/browser/audit-summary")?
        .get("audit").cloned().unwrap_or(Value::Null);

    let browser_audit_job = api_get(&token, "/v1/browser/audit-job")?
        .get("job").cloned().unwrap_or(Value::Null);
    Ok(Dashboard { running: true, resources, tasks, events, browser_tabs, browser_audit, browser_audit_job, permissions })
}

#[tauri::command]
fn request_browser_audit(state: State<'_, AgentState>) -> Result<Value, String> {
    let token = state.token.lock().map_err(|_| "Состояние агента недоступно".to_string())?
        .clone().ok_or_else(|| "Сначала запустите локального агента".to_string())?;
    api_post_json(&token, "/v1/browser/audit-request", serde_json::json!({}),
        Duration::from_secs(5))
}

#[tauri::command]
fn create_task(state: State<'_, AgentState>, title: String, description: String, request_id: Option<String>) -> Result<Value, String> {
    let token = state.token.lock().map_err(|_| "Ошибка состояния токена".to_string())?
        .clone().ok_or_else(|| "Сначала запусти агента".to_string())?;
    if title.trim().is_empty() || title.chars().count() > 200 {
        return Err("Название задачи должно содержать от 1 до 200 символов".to_string());
    }
    if description.chars().count() > 2000 {
        return Err("Описание не должно превышать 2000 символов".to_string());
    }

    reqwest::blocking::Client::new()
        .post(format!("http://{API_HOST}:{API_PORT}/v1/tasks"))
        .header("Authorization", format!("Bearer {token}"))
        .json(&serde_json::json!({"title": title.trim(), "description": description, "request_id": request_id}))
        .timeout(Duration::from_secs(3))
        .send().map_err(|error| error.to_string())?
        .error_for_status().map_err(|error| error.to_string())?
        .json::<Value>().map_err(|error| error.to_string())
}

#[tauri::command]
fn cancel_task(state: State<'_, AgentState>, task_id: String) -> Result<Value, String> {
    let token = state.token.lock().map_err(|_| "Ошибка состояния токена".to_string())?
        .clone().ok_or_else(|| "Агент не запущен".to_string())?;
    let valid_uuid_shape = task_id.len() == 36 && task_id.chars().all(|ch| ch.is_ascii_hexdigit() || ch == '-');
    if !valid_uuid_shape {
        return Err("Некорректный идентификатор задачи".to_string());
    }

    reqwest::blocking::Client::new()
        .post(format!("http://{API_HOST}:{API_PORT}/v1/tasks/{task_id}/cancel"))
        .header("Authorization", format!("Bearer {token}"))
        .timeout(Duration::from_secs(3))
        .send().map_err(|error| error.to_string())?
        .error_for_status().map_err(|error| error.to_string())?
        .json::<Value>().map_err(|error| error.to_string())
}

#[tauri::command]
fn decide_permission(
    state: State<'_, AgentState>, permission_id: String, binding: String, decision: String,
) -> Result<Value, String> {
    if permission_id.len() != 36
        || !permission_id.chars().all(|ch| ch.is_ascii_hexdigit() || ch == '-')
        || binding.len() != 64
        || !binding.chars().all(|ch| ch.is_ascii_digit() || ('a'..='f').contains(&ch))
        || !matches!(decision.as_str(), "allow" | "deny" | "revoke")
    {
        return Err("Некорректное решение по разрешению".to_string());
    }
    let token = state.token.lock().map_err(|_| "Состояние агента недоступно".to_string())?
        .clone().ok_or_else(|| "Агент не запущен".to_string())?;
    let response = reqwest::blocking::Client::new()
        .post(format!("http://{API_HOST}:{API_PORT}/v1/permissions/{permission_id}/decision"))
        .header("Authorization", format!("Bearer {token}"))
        .json(&serde_json::json!({"binding": binding, "decision": decision}))
        .timeout(Duration::from_secs(3))
        .send().map_err(|_| "Доставка решения не подтверждена. Обновите список перед новой попыткой".to_string())?;
    if response.status() == reqwest::StatusCode::CONFLICT {
        return Err("Разрешение истекло, изменилось или уже обработано. Обновите список".to_string());
    }
    response.error_for_status().map_err(|_| "Решение по разрешению отклонено".to_string())?
        .json::<Value>().map_err(|_| "Некорректный ответ на решение по разрешению".to_string())
}

fn ollama_ready() -> bool {
    reqwest::blocking::Client::builder().no_proxy().timeout(Duration::from_secs(2)).build()
        .ok().and_then(|client| client.get("http://127.0.0.1:11434/api/version").send().ok())
        .filter(|response| response.status().is_success())
        .and_then(|response| response.json::<Value>().ok())
        .and_then(|value| value.get("version").and_then(Value::as_str).map(|_| ()))
        .is_some()
}

#[tauri::command]
fn get_setup_status() -> String { runtime_setup::status() }

#[tauri::command]
async fn start_local_ai(app: tauri::AppHandle) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || start_local_ai_impl(&app.state::<AgentState>()))
        .await.map_err(|_| "Ошибка подготовки движка".to_string())?
}

fn start_local_ai_impl(state: &AgentState) -> Result<String, String> {
    let mut slot = state.ai_child.lock().map_err(|_| "Состояние ИИ недоступно".to_string())?;
    if ollama_ready() { return Ok("Ollama уже работает".to_string()); }
    if std::net::TcpStream::connect(("127.0.0.1", 11434)).is_ok() {
        return Err("Порт модели занят другим процессом".to_string());
    }
    let root = PathBuf::from(std::env::var("LOCALAPPDATA").map_err(|_| "LOCALAPPDATA недоступна".to_string())?).join("Malenia");
    let standard = PathBuf::from(std::env::var("LOCALAPPDATA").unwrap_or_default()).join("Programs/Ollama/ollama.exe");
    let executable = if standard.is_file() { standard } else { runtime_setup::ensure(&root)? };
    if let Some(mut old) = slot.take() { let _ = old.kill(); let _ = old.wait(); }
    let mut command = Command::new(executable);
    command.arg("serve")
        .env("OLLAMA_HOST", "127.0.0.1:11434").env("OLLAMA_MODELS", root.join("models"))
        .env("OLLAMA_NO_CLOUD", "1").env("OLLAMA_NUM_PARALLEL", "1")
        .env("OLLAMA_MAX_LOADED_MODELS", "1").env("OLLAMA_CONTEXT_LENGTH", "2048")
        .env("OLLAMA_KEEP_ALIVE", "30s")
        .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    #[cfg(windows)]
    { use std::os::windows::process::CommandExt; command.creation_flags(0x08000000); }
    let mut child = command.spawn().map_err(|_| "Не удалось запустить Ollama".to_string())?;
    for _ in 0..20 {
        thread::sleep(Duration::from_millis(250));
        if child.try_wait().map_err(|_| "Не удалось проверить Ollama".to_string())?.is_some() { break; }
        if ollama_ready() { *slot = Some(child); return Ok("Локальная модель готова к подключению".to_string()); }
    }
    let _ = child.kill(); let _ = child.wait();
    Err("Ollama не запустился".to_string())
}

#[tauri::command]
fn get_ai_status(state: State<'_, AgentState>) -> Result<Value, String> {
    let token = state.token.lock().map_err(|_| "Состояние агента недоступно".to_string())?
        .clone().ok_or_else(|| "Сначала запустите агента".to_string())?;
    api_get(&token, "/v1/ai/status")
}

#[tauri::command]
async fn chat_ai(state: State<'_, AgentState>, model: String, messages: Value, use_knowledge: Option<bool>, knowledge_only: Option<bool>, use_web: Option<bool>) -> Result<Value, String> {
    let token = state.token.lock().map_err(|_| "Состояние агента недоступно".to_string())?
        .clone().ok_or_else(|| "Сначала запустите агента".to_string())?;
    tauri::async_runtime::spawn_blocking(move || {
        let response = reqwest::blocking::Client::new()
            .post(format!("http://{API_HOST}:{API_PORT}/v1/ai/chat"))
            .header("Authorization", format!("Bearer {token}"))
            .json(&serde_json::json!({"model": model, "messages": messages, "use_knowledge": use_knowledge.unwrap_or(true), "knowledge_only": knowledge_only.unwrap_or(false), "use_web": use_web.unwrap_or(false)}))
            .timeout(Duration::from_secs(120))
            .send().map_err(|_| "Модель не ответила. Запрос не повторён автоматически".to_string())?;
        let status = response.status();
        let body = response.json::<Value>().map_err(|_| "Некорректный ответ агента".to_string())?;
        if !status.is_success() {
            if body.get("error").and_then(Value::as_str) == Some("knowledge_answer_unverified") {
                return Err("Модель не смогла подтвердить ссылки на источники. Ответ не показан. Уточните вопрос или проверьте найденные фрагменты".to_string());
            }
            if body.get("error").and_then(Value::as_str).map(|e| e.starts_with("web_")).unwrap_or(false) {
                return Err("Интернет-поиск недоступен или вернул некорректные данные. Проверьте подключение и повторите запрос".into());
            }
            return Err(format!("Ошибка модели: {}", body.get("error").and_then(Value::as_str).unwrap_or("unavailable")));
        }
        Ok(body)
    }).await.map_err(|_| "Ошибка обработки запроса модели".to_string())?
}

#[tauri::command]
async fn install_sherlock(model: String) -> Result<String, String> {
    if !matches!(model.as_str(), "qwen3:4b" | "qwen3:8b" | "qwen3:14b") {
        return Err("Неизвестный вариант Шерлока".to_string());
    }
    tauri::async_runtime::spawn_blocking(move || {
        // Download only on an explicit click; never silently load the model.
        let required = match model.as_str() { "qwen3:14b" => 14, "qwen3:8b" => 8, _ => 5 };
        #[cfg(windows)]
        {
            #[repr(C)]
            struct MemoryStatus { length: u32, load: u32, total: u64, available: u64,
                page: u64, available_page: u64, virtual_total: u64, virtual_available: u64, extended: u64 }
            #[link(name="kernel32")]
            extern "system" { fn GlobalMemoryStatusEx(status: *mut MemoryStatus) -> i32; }
            let mut memory = MemoryStatus { length: std::mem::size_of::<MemoryStatus>() as u32,
                load:0,total:0,available:0,page:0,available_page:0,virtual_total:0,virtual_available:0,extended:0 };
            if unsafe { GlobalMemoryStatusEx(&mut memory) } == 0 || memory.available < required * 1024 * 1024 * 1024 {
                return Err(format!("Для выбранной версии освободите минимум {required} ГБ оперативной памяти. Загрузка не начата"));
            }
        }
        let response = reqwest::blocking::Client::builder().no_proxy().redirect(reqwest::redirect::Policy::none()).build().map_err(|e| e.to_string())?
            .post("http://127.0.0.1:11434/api/pull")
            .json(&serde_json::json!({"model": model, "stream": false}))
            .timeout(Duration::from_secs(1800)).send()
            .map_err(|_| "Загрузка не подтверждена. Проверьте подключение и список установленных вариантов".to_string())?;
        let ok = response.status().is_success();
        let body = response.json::<Value>().map_err(|_| "Не удалось проверить загрузку Шерлока".to_string())?;
        if !ok || body.get("status").and_then(Value::as_str) != Some("success") {
            return Err("Не удалось скачать Шерлока. Проверьте интернет, свободное место и локальный движок".to_string());
        }
        Ok("Шерлок установлен".to_string())
    }).await.map_err(|_| "Ошибка установки Шерлока".to_string())?
}

#[tauri::command]
async fn preview_order_batch(
    state: State<'_, AgentState>, rows: Vec<Value>,
) -> Result<Value, String> {
    if rows.is_empty() || rows.len() > 100 {
        return Err("Пакет должен содержать от 1 до 100 строк".to_string());
    }
    let token = state.token.lock().map_err(|_| "Состояние агента недоступно".to_string())?
        .clone().ok_or_else(|| "Сначала запустите агента".to_string())?;
    tauri::async_runtime::spawn_blocking(move || {
        api_post_json(&token, "/v1/orders/batch-preview",
            serde_json::json!({"rows": rows}),
            Duration::from_secs(15))
    }).await.map_err(|_| "Не удалось выполнить пакетную проверку".to_string())?
}

#[tauri::command]
async fn preview_order(
    state: State<'_, AgentState>, order: Value, datalens_scans: Vec<Value>,
    asgard_record: Option<Value>,
) -> Result<Value, String> {
    if datalens_scans.len() > 100 {
        return Err("Допускается не более 100 записей сканов".to_string());
    }
    let token = state.token.lock().map_err(|_| "Состояние агента недоступно".to_string())?
        .clone().ok_or_else(|| "Сначала запустите агента".to_string())?;
    tauri::async_runtime::spawn_blocking(move || {
        api_post_json(&token, "/v1/orders/preview",
            serde_json::json!({"order": order, "datalens_scans": datalens_scans, "asgard_record": asgard_record}),
            Duration::from_secs(10))
    }).await.map_err(|_| "Не удалось проверить заказ".to_string())?
}

#[tauri::command]
fn get_google_sheets_status(state: State<'_, AgentState>) -> Result<Value, String> {
    let token = state.token.lock().map_err(|_| "Состояние агента недоступно".to_string())?
        .clone().ok_or_else(|| "Сначала запустите агента".to_string())?;
    api_get(&token, "/v1/integrations/google-sheets/status")
}

#[tauri::command]
async fn connect_google_sheets(
    app: tauri::AppHandle, state: State<'_, AgentState>, client_id: String,
    client_secret: Option<String>,
) -> Result<String, String> {
    if client_id.trim().len() < 20 || client_id.len() > 300 || client_id.chars().any(|c| c.is_control()) {
        return Err("Укажите Google OAuth Desktop Client ID из Google Cloud Console".to_string());
    }
    if client_secret.as_ref().is_some_and(|secret| secret.len() > 512 || secret.chars().any(|c| c.is_control())) {
        return Err("Некорректный необязательный Client Secret".to_string());
    }
    let token = state.token.lock().map_err(|_| "Состояние агента недоступно".to_string())?
        .clone().ok_or_else(|| "Сначала запустите агента".to_string())?;
    let body = tauri::async_runtime::spawn_blocking(move || {
        api_post_json(&token, "/v1/integrations/google-sheets/connect",
            serde_json::json!({"client_id": client_id, "client_secret": client_secret}), Duration::from_secs(10))
    }).await.map_err(|_| "Ошибка запуска подключения Google Sheets".to_string())??;
    let url = body.get("authorization_url").and_then(Value::as_str)
        .ok_or_else(|| "Google OAuth не вернул ссылку авторизации".to_string())?;
    let parsed = reqwest::Url::parse(url).map_err(|_| "Некорректная ссылка Google OAuth".to_string())?;
    if parsed.scheme() != "https" || parsed.host_str() != Some("accounts.google.com")
        || parsed.path() != "/o/oauth2/v2/auth" || parsed.username() != "" || parsed.password().is_some()
        || parsed.port().is_some() || url.len() > 4096 {
        return Err("Отклонена небезопасная ссылка авторизации".to_string());
    }
    use tauri_plugin_opener::OpenerExt;
    app.opener().open_url(parsed.as_str(), None::<&str>)
        .map_err(|_| "Не удалось открыть системный браузер для Google OAuth".to_string())?;
    Ok("Открыл системный браузер. Подтвердите доступ только для чтения и вернитесь в Malenia.".to_string())
}

#[tauri::command]
async fn read_google_sheet(
    state: State<'_, AgentState>, spreadsheet_id: String, range: String,
) -> Result<Value, String> {
    let token = state.token.lock().map_err(|_| "Состояние агента недоступно".to_string())?
        .clone().ok_or_else(|| "Сначала запустите агента".to_string())?;
    tauri::async_runtime::spawn_blocking(move || {
        api_post_json(&token, "/v1/integrations/google-sheets/read",
            serde_json::json!({"spreadsheet_id": spreadsheet_id, "range": range}),
            Duration::from_secs(30))
    }).await.map_err(|_| "Ошибка чтения Google Sheets".to_string())?
}

#[tauri::command]
async fn disconnect_google_sheets(state: State<'_, AgentState>) -> Result<Value, String> {
    let token = state.token.lock().map_err(|_| "Состояние агента недоступно".to_string())?
        .clone().ok_or_else(|| "Сначала запустите агента".to_string())?;
    tauri::async_runtime::spawn_blocking(move || {
        api_post_json(&token, "/v1/integrations/google-sheets/disconnect",
            serde_json::json!({}), Duration::from_secs(10))
    }).await.map_err(|_| "Ошибка отключения Google Sheets".to_string())?
}

#[tauri::command]
fn get_knowledge(state: State<'_, AgentState>) -> Result<Value, String> {
    let token = state.token.lock().map_err(|_| "Состояние агента недоступно".to_string())?
        .clone().ok_or_else(|| "Сначала запустите агента".to_string())?;
    api_get(&token, "/v1/knowledge")
}

#[tauri::command]
async fn knowledge_action(state: State<'_, AgentState>, action: String, payload: Value) -> Result<Value, String> {
    let path = match action.as_str() {
        "search" => "/v1/knowledge/search", "save" => "/v1/knowledge", "import" => "/v1/knowledge/import", "delete" => "/v1/knowledge/delete",
        _ => return Err("Неизвестное действие с базой знаний".to_string()),
    };
    let token = state.token.lock().map_err(|_| "Состояние агента недоступно".to_string())?
        .clone().ok_or_else(|| "Сначала запустите агента".to_string())?;
    tauri::async_runtime::spawn_blocking(move || {
        let response = reqwest::blocking::Client::builder().no_proxy().redirect(reqwest::redirect::Policy::none()).build().map_err(|e| e.to_string())?
            .post(format!("http://{API_HOST}:{API_PORT}{path}"))
            .header("Authorization", format!("Bearer {token}"))
            .json(&payload).timeout(Duration::from_secs(30)).send()
            .map_err(|_| "Результат не подтверждён. Обновите список перед повтором".to_string())?;
        let status = response.status();
        let body = response.json::<Value>().map_err(|_| "Некорректный ответ агента".to_string())?;
        if !status.is_success() {
            return Err(body.get("error").and_then(Value::as_str).unwrap_or("Ошибка базы знаний").to_string());
        }
        Ok(body)
    }).await.map_err(|_| "Ошибка обработки базы знаний".to_string())?
}

#[tauri::command]
fn open_search_source(app: tauri::AppHandle, url: String) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    let parsed = reqwest::Url::parse(&url).map_err(|_| "Некорректная ссылка")?;
    let host = parsed.host_str().unwrap_or("").trim_end_matches('.');
    if !matches!(parsed.scheme(), "http" | "https") || !parsed.username().is_empty()
        || parsed.password().is_some() || !matches!(parsed.port(), None | Some(80) | Some(443))
        || !host.contains('.') || host.parse::<std::net::IpAddr>().is_ok()
        || [".local", ".localhost", ".internal", ".test", ".invalid"].iter().any(|s| host.ends_with(s))
        || url.len() > 2000 || url.chars().any(|c| c.is_control()) {
        return Err("Разрешены только публичные веб-ссылки".into());
    }
    app.opener().open_url(parsed.as_str(), None::<&str>).map_err(|_| "Не удалось открыть браузер".into())
}

fn main() {
    tauri::Builder::default()
        // Activate the original window before a second shell can own another agent.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .manage(AgentState::default())
        .invoke_handler(tauri::generate_handler![start_agent, stop_agent, get_dashboard,
            request_browser_audit, create_task, cancel_task, decide_permission, get_ai_status, chat_ai, start_local_ai, get_setup_status, open_search_source, get_knowledge, knowledge_action, install_sherlock, get_google_sheets_status, connect_google_sheets, read_google_sheet, disconnect_google_sheets, preview_order, preview_order_batch])
        .run(tauri::generate_context!())
        .expect("error while running Malenia");
}
