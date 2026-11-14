const HOST_NAME = "com.malenia.browser";
const RESPONSE_TIMEOUT_MS = 5000;
const statusNode = document.getElementById("status");
const shareButton = document.getElementById("share");
const shareAllButton = document.getElementById("shareAll");
const retryButton = document.getElementById("retry");
const inspectButton = document.getElementById("inspect");
const auditStatus = document.getElementById("auditStatus");
let busy = false;
let connected = false;

function setStatus(message, kind = "") {
  statusNode.textContent = message;
  statusNode.className = "status" + (kind ? " " + kind : "");
}

function updateButtons() {
  shareButton.disabled = busy || !connected;
  shareAllButton.disabled = busy || !connected;
  inspectButton.disabled = busy || !connected;
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
function sanitizedTab(tab) {
  if (typeof tab?.url !== "string") return null;
  let page;
  try { page = new URL(tab.url); } catch { return null; }
  if (!["http:", "https:"].includes(page.protocol) || page.username || page.password) return null;
  let suffix = "";
  // Preserve only the numeric worksheet identity, never arbitrary parameters.
  if (page.origin === "https://docs.google.com" &&
      /^\/spreadsheets\/d\/[A-Za-z0-9_-]+\/edit\/?$/.test(page.pathname)) {
    const gids = [...page.searchParams.getAll("gid"), ...new URLSearchParams(page.hash.slice(1)).getAll("gid")];
    if (gids.length && gids.every(gid => /^\d{1,16}$/.test(gid) && gid === gids[0])) suffix = "?gid=" + gids[0];
  }
  return {title: typeof tab.title === "string" ? tab.title.slice(0, 300) : "", url: page.origin + page.pathname + suffix};
}
shareAllButton.addEventListener("click", async () => {
  if (busy || !connected) return;
  busy = true;
  updateButtons();
  setStatus("Передаём список вкладок без содержимого страниц…");
  let sent = 0;
  let attempted = false;
  try {
    const tabs = await chrome.tabs.query({});
    const candidates = tabs.map(sanitizedTab).filter(Boolean).slice(0, 100);
    if (!candidates.length) { setStatus("Не нашлось обычных HTTP(S)-вкладок."); return; }
    for (const tab of candidates) {
      attempted = true;
      const response = await sendNativeMessage({type:"share_active_tab",request_id:crypto.randomUUID(),tab});
      if (!response?.ok) throw bridgeError("protocol");
      sent += 1;
    }
    setStatus(`Передано вкладок: ${sent}. Откройте «Браузер» в Malenia.`, "ok");
  } catch (error) {
    if (attempted) connected = false;
    setStatus(`Передано ${sent} вкладок. ${diagnostic(error, attempted)}`, "error");
  } finally {
    busy = false;
    updateButtons();
  }
});
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
      tab: sanitizedTab(tab)
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

inspectButton.addEventListener("click", async () => {
  if (busy || !connected) return;
  busy = true;
  updateButtons();
  setStatus("Проверяем структуру активной вкладки…");
  try {
    const [tab] = await chrome.tabs.query({active:true,lastFocusedWindow:true});
    if (!tab || !Number.isInteger(tab.id) || typeof tab.url !== "string") throw new Error("tab");
    const page = new URL(tab.url);
    if (!["http:","https:"].includes(page.protocol) || page.username || page.password) throw new Error("url");
    const results = await chrome.scripting.executeScript({target:{tabId:tab.id},func:() => {
      const visible = el => !!(el && (el.getClientRects().length || el.getBoundingClientRect().width));
      const clean = value => String(value || "").replace(/\\s+/g," ").trim().slice(0,120);
      const headers = Array.from(document.querySelectorAll("table thead th, [role=columnheader]"))
        .filter(visible).map(el=>clean(el.innerText || el.getAttribute("aria-label"))).filter(Boolean).slice(0,40);
      const labels = Array.from(document.querySelectorAll("input:not([type=hidden]), [role=searchbox]"))
        .filter(visible).map(el=>clean(el.getAttribute("aria-label") || el.getAttribute("placeholder") ||
          (el.labels && Array.from(el.labels).map(x=>x.innerText).join(" ")))).filter(Boolean).slice(0,30);
      const body = document.body ? document.body.innerText.slice(0,5000).toLowerCase() : "";
      return {title:document.title.slice(0,300),table_headers:headers,search_labels:labels,
        has_aria_grid:!!document.querySelector('[role="grid"],[role="table"]'),
        virtualized:!!document.querySelector('[aria-rowcount], [data-virtualized="true"], .ag-virtual-list-viewport'),
        login_required:/sign in|log in|войти|авторизац|вход в аккаунт/.test(body)};
    }});
    const summary = results?.[0]?.result;
    if (!summary || typeof summary !== "object") throw new Error("snapshot");
    const response = await sendNativeMessage({type:"inspect_capabilities",request_id:crypto.randomUUID(),
      page:{url:page.origin+page.pathname,...summary}});
    if (!response?.ok || response.type!=="capabilities_inspected" || response.persisted!==false)
      throw bridgeError("protocol");
    const role = /inventa|инвент/i.test(page.hostname+" "+summary.title) ? "ИНВента" :
      /datalens|data.?lens/i.test(page.hostname+" "+summary.title) ? "DataLens" :
      /asgard|асгард/i.test(page.hostname+" "+summary.title) ? "Asgard" : "Неизвестный ресурс";
    auditStatus.textContent = role+": "+(summary.login_required?"похоже, требуется вход": "страница доступна")+
      "; заголовков: "+summary.table_headers.length+"; полей поиска: "+summary.search_labels.length+
      (summary.has_aria_grid?"; есть ARIA grid":"")+(summary.virtualized?"; вероятна виртуализация":"")+
      ". Заголовки: "+(summary.table_headers.join(" | ") || "не обнаружены")+
      ". Поля поиска: "+(summary.search_labels.join(" | ") || "не обнаружены")+
      ". Строки заказов не сохранялись.";
    auditStatus.className = "status ok";
    setStatus("Структурная диагностика завершена. Это ещё не проверка заказов.", "ok");
  } catch {
    auditStatus.textContent = "Не удалось проверить вкладку. Убедитесь, что активна обычная HTTP(S)-страница и расширению разрешён доступ.";
    auditStatus.className = "status error";
    setStatus("Проверка структуры не выполнена.", "error");
  } finally { busy=false; updateButtons(); }
});

