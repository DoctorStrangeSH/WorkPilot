#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

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
}


impl Drop for AgentState {
    fn drop(&mut self) {
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
}

fn api_get(token: &str, path: &str) -> Result<Value, String> {
    reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(3))
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

fn agent_directory() -> Result<PathBuf, String> {
    if let Ok(path) = std::env::var("WORKPILOT_AGENT_DIR") {
        return Ok(PathBuf::from(path));
    }
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../agent");
    if path.exists() {
        Ok(path)
    } else {
        Err("Не найдена папка Python-агента. Укажи WORKPILOT_AGENT_DIR.".to_string())
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
        return Err("Порт 8765 уже занят. Останови другой экземпляр WorkPilot Agent.".to_string());
    }

    let mut random = [0_u8; 32];
    OsRng.fill_bytes(&mut random);
    let token = random.iter().map(|byte| format!("{byte:02x}")).collect::<String>();

    let packaged_agent = app
        .path()
        .resolve("resources/workpilot-agent/workpilot-agent.exe", BaseDirectory::Resource)
        .ok()
        .filter(|path| path.is_file());

    let mut command = if let Some(agent_path) = packaged_agent {
        Command::new(agent_path)
    } else {
        #[cfg(debug_assertions)]
        {
            let agent_dir = agent_directory()?;
            let python = std::env::var("WORKPILOT_PYTHON")
                .unwrap_or_else(|_| "python".to_string());
            let mut command = Command::new(python);
            command
                .arg("-m")
                .arg("workpilot")
                .env("PYTHONPATH", &agent_dir)
                .current_dir(&agent_dir);
            command
        }
        #[cfg(not(debug_assertions))]
        {
            return Err(
                "Не найден встроенный WorkPilot Agent. Переустанови приложение.".to_string()
            );
        }
    };

    command
        .arg("--host")
        .arg(API_HOST)
        .arg("--port")
        .arg(API_PORT.to_string())
        .env("PYTHONUNBUFFERED", "1")
        .env("WORKPILOT_API_TOKEN", &token)
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
        let ready = reqwest::blocking::Client::new()
            .get(format!("http://{API_HOST}:{API_PORT}/v1/resources"))
            .header("Authorization", format!("Bearer {token}"))
            .timeout(Duration::from_millis(500))
            .send()
            .map(|response| response.status().is_success())
            .unwrap_or(false);
        if ready {
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

    Ok(Dashboard { running: true, resources, tasks, events })
}

#[tauri::command]
fn create_task(state: State<'_, AgentState>, title: String, description: String) -> Result<Value, String> {
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
        .json(&serde_json::json!({"title": title.trim(), "description": description}))
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

fn main() {
    tauri::Builder::default()
        .manage(AgentState::default())
        .invoke_handler(tauri::generate_handler![start_agent, stop_agent, get_dashboard, create_task, cancel_task])
        .run(tauri::generate_context!())
        .expect("error while running WorkPilot");
}
