const HOST_NAME = "com.malenia.browser";
const RESPONSE_TIMEOUT_MS = 5000;
const statusNode = document.getElementById("status");
const shareButton = document.getElementById("share");
const retryButton = document.getElementById("retry");
const inspectButton = document.getElementById("inspect");
const auditButton = document.getElementById("audit");
const auditStatus = document.getElementById("auditStatus");
let busy = false;
let connected = false;

function setStatus(message, kind = "") {
  statusNode.textContent = message;
  statusNode.className = "status" + (kind ? " " + kind : "");
}

function updateButtons() {
  shareButton.disabled = busy || !connected;
  inspectButton.disabled = busy || !connected;
  auditButton.disabled = busy || !connected;
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

inspectButton.addEventListener("click", async () => {
  if (busy || !connected) return;
  busy = true;
  updateButtons();
  setStatus("Читаем открытую страницу по вашему запросу…");
  let sending = false;
  try {
    const [tab] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
    if (!tab || !Number.isInteger(tab.id) || typeof tab.url !== "string") throw new Error("No tab");
    const page = new URL(tab.url);
    if (!["http:", "https:"].includes(page.protocol) || page.username || page.password) throw new Error("Invalid URL");
    const results = await chrome.scripting.executeScript({
      target: {tabId: tab.id},
      func: () => {
        const value = document.body ? document.body.innerText : "";
        return typeof value === "string" ? value.slice(0, 16000) : "";
      }
    });
    const visibleText = results?.[0]?.result;
    if (typeof visibleText !== "string" || !visibleText.trim()) throw new Error("Empty page");
    sending = true;
    const response = await sendNativeMessage({
      type: "inspect_active_page",
      request_id: crypto.randomUUID(),
      page: {url: page.origin + page.pathname, text: visibleText}
    });
    if (!response.ok || response.type !== "page_inspected" || response.persisted !== false) throw bridgeError("protocol");
    setStatus("Локальный хост прочитал " + response.characters + " символов. Автоматическая сверка заказов пока не подключена.", "ok");
  } catch (error) {
    if (sending) {
      connected = false;
      setStatus(diagnostic(error, true), "error");
    } else {
      setStatus("Не удалось прочитать страницу. Проверьте разрешения расширения и выберите обычный сайт.", "error");
    }
  } finally {
    busy = false;
    updateButtons();
  }
});

const RESOURCE_LABELS = {inventory:"ИНВента",datalens:"DataLens",asgard:"Asgard"};
const FAILURE_LABELS = {
  unmapped_search_form: "форма поиска не распознана",
  unsupported_search_form: "сайт использует неподдерживаемую HTML-форму поиска",
  dynamic_search_ui: "сайт использует динамическое поле поиска; нужен адаптер",
  invalid_inventory_search_keys: "список грузомест не подходит для точного поиска",
  invalid_search: "неподдерживаемый идентификатор",
  unsafe_search_target: "поиск ведёт за пределы разрешённой страницы",
  unverified_search_result_identity: "результат поиска относится к другому грузоместу",
  unmapped_search_results: "не найдена таблица результатов",
  changed_search_schema: "структура таблицы меняется",
  too_many_search_rows: "слишком много результатов",
  virtualized_or_incomplete_grid: "динамическая таблица загружена не полностью",
  navigation_outside_allowed_origin: "сайт перенаправил на другой домен (возможно, нужен вход)",
  search_origin_mismatch: "страница поиска не соответствует разрешённому сайту",
  unexpected_document: "страница изменилась во время чтения",
  empty_page: "страница не содержит читаемого текста",
  unmapped_paginated_table: "не распознана таблица с несколькими страницами",
  pagination_cycle: "зациклилась навигация по страницам",
  pagination_limit: "превышен лимит страниц",
  changed_table_schema: "колонки таблицы изменились",
  too_many_rows: "превышен лимит строк",
  native_host_rejected: "локальный компонент отказался принять данные",
  page_timeout: "страница слишком долго загружается",
  tab_closed: "вкладка закрылась",
  site_or_browser_error: "не удалось прочитать сайт"
};

function showAudit(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return;
  const parts = (snapshot.results || []).map(item =>
    RESOURCE_LABELS[item.role] + ": " + (item.status === "read" ?
      "прочитано" + (Number.isInteger(item.pages) ? " (" + item.pages + " стр.)" : "") :
      "нужна проверка" + (FAILURE_LABELS[item.reason] ?
        " (" + FAILURE_LABELS[item.reason] + ")" : "")));
  const phase = snapshot.phase === "reconciled" ? "Сверка таблиц завершена (только предложения)." :
    snapshot.phase === "read_only" ? "Страницы прочитаны, но таблицы не сопоставлены. Требуется настройка структуры сайтов." :
    snapshot.phase === "needs_attention" ? "Обход завершён с ошибками." :
    "Автоматический обход выполняется.";
  const counts = snapshot.reconciliation?.summary;
  const total = snapshot.reconciliation?.total;
  const outcome = counts && Number.isInteger(total) &&
    ["found","in_progress","manual_review"].every(key => Number.isInteger(counts[key])) ?
    " Всего: " + total + "; найдено: " + counts.found +
    "; в работе: " + counts.in_progress + "; ручная проверка: " + counts.manual_review + "." : "";
  auditStatus.textContent = phase + (parts.length ? " " + parts.join("; ") : "") + outcome;
  auditStatus.className = "status" + (snapshot.phase === "reconciled" ? " ok" :
    snapshot.phase === "needs_attention" || snapshot.phase === "read_only" ? " error" : "");
}
if (chrome.storage?.local) {
  chrome.storage.local.get(["maleniaTargets","maleniaExactGetSearch"]).then(saved => {
    const targets = saved?.maleniaTargets || {};
    document.getElementById("exactSearch").checked = saved?.maleniaExactGetSearch !== false;
    for (const role of Object.keys(RESOURCE_LABELS)) {
      if (typeof targets[role] === "string") document.getElementById(role).value = targets[role];
    }
  }).catch(() => {});
}
if (chrome.storage?.session) {
  chrome.storage.session.get("maleniaAudit").then(saved => showAudit(saved?.maleniaAudit)).catch(() => {});
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "session" && changes.maleniaAudit) showAudit(changes.maleniaAudit.newValue);
  });
}
auditButton.addEventListener("click", async () => {
  if (busy || !connected) return;
  let targets, origins;
  try {
    targets = MaleniaAutomation.normalizeTargets(Object.fromEntries(
      Object.keys(RESOURCE_LABELS).map(role => [role, document.getElementById(role).value.trim()])));
    origins = MaleniaAutomation.origins(targets);
  } catch {
    auditStatus.textContent = "Укажите три HTTPS-адреса без параметров, фрагментов и паролей.";
    auditStatus.className = "status error";
    return;
  }
  busy = true;
  updateButtons();
  auditStatus.textContent = "Запрашиваем доступ только к выбранным доменам…";
  try {
    // This must be initiated directly from a user gesture. Chrome may persist per-origin approval.
    const allowed = await chrome.permissions.request({origins});
    if (!allowed) throw new Error("permission_denied");
    const exactGetSearch = document.getElementById("exactSearch").checked === true;
    const result = await chrome.runtime.sendMessage({type:"start_readonly_audit",targets,exactGetSearch});
    if (!result?.ok) throw new Error("start_refused");
    await chrome.storage.local.set({maleniaTargets:targets,maleniaExactGetSearch:exactGetSearch});
    auditStatus.textContent = "Задача запущена. Можно закрыть окно расширения; состояние появится здесь при повторном открытии.";
    auditStatus.className = "status";
  } catch {
    auditStatus.textContent = "Запуск не удался. Проверьте разрешения браузера и подключение к Malenia.";
    auditStatus.className = "status error";
  } finally {
    busy = false;
    updateButtons();
  }
});
