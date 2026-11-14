//! Pinned official portable runtime. No installer, elevation or startup changes.
use sha2::{Digest, Sha256};
use std::{fs::{self, File}, io::{Read, Write}, path::{Path, PathBuf}, sync::Mutex, time::Duration};
static STATUS: Mutex<String> = Mutex::new(String::new());
const URL: &str = "https://github.com/ollama/ollama/releases/download/v0.40.16/ollama-windows-amd64.zip";
const SIZE: u64 = 1618244995;
const HASH: &str = "50fcf5ad54277f2fa5d173ebfc93bcb017adbc0c9ef2314daabc96ca9e6aa64e";
pub fn status() -> String { STATUS.lock().map(|s| s.clone()).unwrap_or_default() }
fn progress(s: String) { if let Ok(mut slot) = STATUS.lock() { *slot = s; } }
fn verify(path: &Path, size: u64, hash: &str) -> Result<(), String> {
    let mut file = File::open(path).map_err(|_| "Не удалось прочитать архив")?;
    if file.metadata().map_err(|_| "Не удалось проверить архив")?.len() != size { return Err("Неполная загрузка движка".into()); }
    let mut digest = Sha256::new(); let mut buf = vec![0u8; 64 * 1024];
    loop { let n = file.read(&mut buf).map_err(|_| "Ошибка чтения архива")?; if n == 0 { break; } digest.update(&buf[..n]); }
    if format!("{:x}", digest.finalize()) != hash { return Err("Контрольная сумма движка не совпала. Установка остановлена".into()); }
    Ok(())
}
fn extract(path: &Path, directory: &Path) -> Result<(), String> {
    let mut zip = zip::ZipArchive::new(File::open(path).map_err(|_| "Архив недоступен")?).map_err(|_| "Повреждённый архив")?;
    if zip.len() > 2000 { return Err("Слишком много файлов в архиве".into()); }
    let mut total = 0u64;
    for i in 0..zip.len() {
        let mut entry = zip.by_index(i).map_err(|_| "Ошибка архива")?;
        let relative = entry.enclosed_name().ok_or("Недопустимый путь в архиве")?;
        if entry.unix_mode().map(|m| m & 0o170000 == 0o120000).unwrap_or(false) { return Err("Ссылки в архиве запрещены".into()); }
        total = total.checked_add(entry.size()).ok_or("Слишком большой архив")?;
        if total > 4 * 1024 * 1024 * 1024 { return Err("Слишком большой архив".into()); }
        let target = directory.join(relative);
        if entry.is_dir() { fs::create_dir_all(&target).map_err(|_| "Не удалось создать папку")?; }
        else {
            fs::create_dir_all(target.parent().ok_or("Ошибка пути")?).map_err(|_| "Не удалось создать папку")?;
            let mut output = File::create(target).map_err(|_| "Не удалось записать движок")?;
            let written = std::io::copy(&mut entry, &mut output).map_err(|_| "Не удалось распаковать движок")?;
            if written != entry.size() { return Err("Неполный файл движка".into()); }
        }
    }
    if !directory.join("ollama.exe").is_file() || !directory.join("lib/ollama/cuda_v12/ggml-cuda.dll").is_file() { return Err("В архиве нет необходимых файлов движка".into()); }
    Ok(())
}
pub fn ensure(root: &Path) -> Result<PathBuf, String> {
    let installed = root.join("ollama-0.40.16");
    if installed.join("ollama.exe").is_file() { return Ok(installed.join("ollama.exe")); }
    fs::create_dir_all(root).map_err(|_| "Не удалось создать папку движка")?;
    #[cfg(windows)] {
        use std::os::windows::ffi::OsStrExt;
        #[link(name="kernel32")] extern "system" {
            fn GetDiskFreeSpaceExW(path: *const u16, available: *mut u64, total: *mut u64, free: *mut u64) -> i32;
        }
        let path: Vec<u16> = root.as_os_str().encode_wide().chain(Some(0)).collect();
        let (mut available, mut total, mut free) = (0u64,0u64,0u64);
        if unsafe { GetDiskFreeSpaceExW(path.as_ptr(), &mut available, &mut total, &mut free) } == 0 || available < 4 * 1024 * 1024 * 1024 {
            return Err("Для установки движка освободите минимум 4 ГБ на диске приложения".into());
        }
    }
    let stage = root.join(format!("runtime-setup-{:016x}", rand::random::<u64>()));
    fs::create_dir(&stage).map_err(|_| "Не удалось подготовить установку")?;
    let result: Result<PathBuf, String> = (|| {
        progress("Скачиваем движок: 0% (архив 1,6 ГБ; потребуется около 4 ГБ свободного места)".into());
        let archive = stage.join("runtime.zip");
        let client = reqwest::blocking::Client::builder().https_only(true).timeout(Duration::from_secs(1800)).connect_timeout(Duration::from_secs(20)).build().map_err(|_| "Не удалось начать загрузку")?;
        let mut response = client.get(URL).send().map_err(|_| "Не удалось скачать движок. Проверьте интернет")?.error_for_status().map_err(|_| "Сервер загрузки движка недоступен")?;
        let mut output = File::create(&archive).map_err(|_| "Не удалось сохранить архив")?;
        let mut buf = vec![0u8; 64 * 1024]; let mut received = 0u64; let mut percent = 0;
        loop {
            let n = response.read(&mut buf).map_err(|_| "Загрузка прервана. Повторите установку")?;
            if n == 0 { break; }
            received += n as u64;
            if received > SIZE { return Err("Размер загрузки не соответствует официальному архиву".into()); }
            output.write_all(&buf[..n]).map_err(|_| "Недостаточно места или не удалось записать архив")?;
            let next = received * 100 / SIZE;
            if next != percent { percent = next; progress(format!("Скачиваем движок: {percent}%")); }
        }
        drop(output);
        progress("Проверяем контрольную сумму движка…".into()); verify(&archive, SIZE, HASH)?;
        progress("Распаковываем движок и библиотеки NVIDIA…".into());
        let unpacked = stage.join("unpacked"); extract(&archive, &unpacked)?;
        fs::rename(unpacked, &installed).map_err(|_| "Не удалось завершить установку движка")?;
        Ok(installed.join("ollama.exe"))
    })();
    // Only our unique staging directory; never delete an existing installation.
    let _ = fs::remove_dir_all(&stage);
    progress(match &result { Ok(_) => "Движок установлен. Запускаем…".into(), Err(e) => e.clone() });
    result
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn hash_and_size_fail_closed() {
        let p = std::env::temp_dir().join(format!("malenia-hash-{}.bin", rand::random::<u64>()));
        fs::write(&p, b"abc").unwrap();
        assert!(verify(&p,3,"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad").is_ok());
        assert!(verify(&p,2,HASH).is_err()); assert!(verify(&p,3,HASH).is_err()); fs::remove_file(p).unwrap();
    }
    #[test] fn traversal_is_rejected() {
        let p = std::env::temp_dir().join(format!("malenia-zip-{}.zip", rand::random::<u64>()));
        let mut writer = zip::ZipWriter::new(File::create(&p).unwrap());
        writer.start_file("../escape.exe", zip::write::SimpleFileOptions::default()).unwrap(); writer.write_all(b"bad").unwrap(); writer.finish().unwrap();
        assert!(extract(&p, &p.with_extension("out")).is_err()); fs::remove_file(p).unwrap();
    }
}

#[cfg(test)] mod official_smoke {
    use super::*;
    #[test] #[ignore = "Downloads the official 1.6 GB runtime on a disposable Windows runner"]
    fn official_runtime_install() {
        let root = std::env::temp_dir().join(format!("malenia-runtime-ci-{:016x}",rand::random::<u64>()));
        let exe = ensure(&root).expect("official archive must download, verify and extract");
        let result = std::process::Command::new(&exe).arg("--version").output().unwrap();
        assert!(result.status.success());
        assert!(String::from_utf8_lossy(&result.stdout).contains("0.40.16") || String::from_utf8_lossy(&result.stderr).contains("0.40.16"));
        assert_eq!(ensure(&root).unwrap(),exe); // No second download.
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port(); drop(listener);
        struct Owned(std::process::Child);
        impl Drop for Owned { fn drop(&mut self) { let _ = self.0.kill(); let _ = self.0.wait(); } }
        let child = std::process::Command::new(&exe).arg("serve")
            .env("OLLAMA_HOST",format!("127.0.0.1:{port}"))
            .env("OLLAMA_MODELS",root.join("empty-models")).env("OLLAMA_NO_CLOUD","1")
            .stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null()).spawn().unwrap();
        let owned = Owned(child);
        let client = reqwest::blocking::Client::builder().no_proxy().timeout(Duration::from_secs(1)).build().unwrap();
        let mut ready = false;
        for _ in 0..40 {
            std::thread::sleep(Duration::from_millis(250));
            if client.get(format!("http://127.0.0.1:{port}/api/version")).send().ok().and_then(|r| r.json::<serde_json::Value>().ok()).and_then(|v| v.get("version").and_then(|v| v.as_str()).map(|s| s=="0.40.16")).unwrap_or(false) { ready=true; break; }
        }
        assert!(ready,"installed runtime must actually start on isolated loopback port");
        drop(owned);
        fs::remove_dir_all(root).unwrap();
    }
}
