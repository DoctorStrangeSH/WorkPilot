const HOST_NAME = "com.workpilot.browser";
const RESPONSE_TIMEOUT_MS = 5000;
const statusNode = document.getElementById("status");
const shareButton = document.getElementById("share");
const retryButton = document.getElementById("retry");
let busy = false;
let connected = false;

function setStatus(message, kind = "") {
  statusNode.textContent = message;
  statusNode.className = "status" + (kind ? " " + kind : "");
}

function updateButtons() {
  shareButton.disabled = busy || !connected;
  retryButton.disabled = busy;
  retryButton.textContent = connected ? "Проверить соединение" : "Повторить подключение";
}

function bridgeError(code) {
  const error = new Error(code);
  error.bridgeCode = code;
  return error;
}

function diagnostic(error, sharing = false) {
  switch (error.bridgeCode) {
    case "not_found": return "Хост Malenia не найден. Выполните проверенную регистрацию Browser Bridge и перезапустите браузер.";
    case "forbidden": return "Браузер запретил подключение. Проверьте ID расширения и политики Native Messaging; не меняйте политики организации самостоятельно.";
    case "timeout": return sharing
      ? "Ответ не получен за 5 секунд. Вкладка могла сохраниться — проверьте раздел «Браузер» в Malenia перед повторной передачей."
      : "Хост не ответил за 5 секунд. Проверьте установку и повторите подключение.";
    case "disconnected": return sharing
      ? "Соединение прервано. Проверьте в Malenia, сохранилась ли вкладка, затем повторите подключение."
      : "Хост завершил соединение. Проверьте установку и повторите подключение.";
    default: return "Не удалось проверить ответ Browser Bridge. Проверьте установку и повторите подключение.";
  }
}

function classifyNativeError(message) {
  if (/host not found|not registered/i.test(message)) return bridgeError("not_found");
  if (/forbidden|not allowed|access.*denied|blocked/i.test(message)) return bridgeError("forbidden");
  return bridgeError("disconnected");
}

function sendNativeMessage(message) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(bridgeError("timeout"));
    }, RESPONSE_TIMEOUT_MS);
    const finish = (error, response) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) reject(error);
      else resolve(response);
    };
    try {
      chrome.runtime.sendNativeMessage(HOST_NAME, message, (response) => {
        // Always read lastError, including after timeout, to consume browser errors.
        const error = chrome.runtime.lastError;
        if (error) finish(classifyNativeError(error.message || ""));
        else if (!response || typeof response !== "object") finish(bridgeError("protocol"));
        else finish(null, response);
      });
    } catch {
      finish(bridgeError("disconnected"));
    }
  });
}

async function connect() {
  if (busy) return;
  busy = true;
  connected = false;
  updateButtons();
  setStatus("Проверяем соединение…");
  try {
    const response = await sendNativeMessage({ type: "hello" });
    if (!response.ok || response.host !== HOST_NAME) throw bridgeError("protocol");
    connected = true;
    setStatus("Malenia подключена. Можно поделиться текущей вкладкой.", "ok");
  } catch (error) {
    setStatus(diagnostic(error), "error");
  } finally {
    busy = false;
    updateButtons();
  }
}

retryButton.addEventListener("click", () => void connect());
shareButton.addEventListener("click", async () => {
  if (busy || !connected) return;
  busy = true;
  updateButtons();
  setStatus("Передаём только активную вкладку…");
  let sending = false;
  try {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (!tab || typeof tab.url !== "string") throw new Error("Не удалось получить адрес активной вкладки.");
    let page;
    try { page = new URL(tab.url); }
    catch { throw new Error("Не удалось проверить адрес вкладки."); }
    if (page.protocol !== "http:" && page.protocol !== "https:") {
      throw new Error("Можно передавать только обычные HTTP(S)-страницы.");
    }
    if (page.username || page.password) throw new Error("Нельзя передавать адреса со встроенными логином или паролем.");
    sending = true;
    const response = await sendNativeMessage({
      type: "share_active_tab",
      request_id: crypto.randomUUID(),
      tab: { title: typeof tab.title === "string" ? tab.title.slice(0, 300) : "", url: page.origin + page.pathname }
    });
    if (!response.ok) throw bridgeError("protocol");
    setStatus("Вкладка передана в Malenia.", "ok");
  } catch (error) {
    if (sending) {
      connected = false;
      setStatus(diagnostic(error, true), "error");
    } else {
      // Do not display a browser exception: it could include the unsanitized URL.
      const safe = ["Не удалось получить адрес активной вкладки.", "Не удалось проверить адрес вкладки.",
        "Можно передавать только обычные HTTP(S)-страницы.", "Нельзя передавать адреса со встроенными логином или паролем."];
      setStatus(safe.includes(error.message) ? error.message : "Не удалось прочитать текущую вкладку. Откройте расширение на обычной HTTP(S)-странице.", "error");
    }
  } finally {
    busy = false;
    updateButtons();
  }
});

void connect();
