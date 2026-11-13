const HOST_NAME = "com.malenia.browser";
const RESPONSE_TIMEOUT_MS = 5000;
const statusNode = document.getElementById("status");
const shareButton = document.getElementById("share");
const shareAllButton = document.getElementById("shareAll");
const retryButton = document.getElementById("retry");
const inspectButton = document.getElementById("inspect");
const auditStatus = document.getElementById("auditStatus");
const inspectMappedTabsButton = document.getElementById("inspectMappedTabs");
let hasConfirmedTabs = false;
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
  inspectMappedTabsButton.disabled = busy || !hasConfirmedTabs;
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
  return {title: typeof tab.title === "string" ? tab.title.slice(0, 300) : "", url: page.origin + page.pathname};
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
  setStatus("Проверяем структуру активной вкладки…");
  let inspectedPageUrl = "";
  try {
    const [tab] = await chrome.tabs.query({active:true,lastFocusedWindow:true});
    if (!tab || !Number.isInteger(tab.id) || typeof tab.url !== "string") throw new Error("tab");
    const page = new URL(tab.url);
    inspectedPageUrl = page.href;
    if (!["http:","https:"].includes(page.protocol) || page.username || page.password) throw new Error("url");
    const results = await chrome.scripting.executeScript({target:{tabId:tab.id},func:() => {
      const visible = el => !!(el && (el.getClientRects().length || el.getBoundingClientRect().width));
      const clean = value => String(value || "").replace(/\s+/g," ").trim().slice(0,120);
      const headers = Array.from(document.querySelectorAll("table thead th, [role=columnheader]"))
        .filter(visible).map(el=>clean(el.innerText || el.getAttribute("aria-label"))).filter(Boolean).slice(0,40);
      // Capture schema only, never cell values: this lets us map real DataLens/Asgard
      // layouts without guessing selectors or transferring order data during diagnosis.
      const tables = [];
      for (const node of Array.from(document.querySelectorAll("table,[role=grid],[role=table]")).filter(visible).slice(0,12)) {
        const isGrid = node.getAttribute("role") === "grid" || node.getAttribute("role") === "table";
        const headNodes = isGrid
          ? Array.from(node.querySelectorAll('[role=columnheader]'))
          : Array.from(node.querySelectorAll("thead th")).length
            ? Array.from(node.querySelectorAll("thead th"))
            : Array.from(node.querySelector("tr")?.querySelectorAll("th") || []);
        const columns = headNodes.filter(visible).map(el=>clean(el.innerText || el.getAttribute("aria-label"))).filter(Boolean).slice(0,20);
        if (!columns.length) continue;
        const rowSelector = isGrid ? '[role=row]' : 'tbody tr';
        const visibleRows = Array.from(node.querySelectorAll(rowSelector)).filter(visible).length;
        const declaredRows = node.getAttribute("aria-rowcount");
        tables.push({kind:isGrid?"aria-grid":"html-table",columns,visible_rows:Math.min(visibleRows,1000),
          declared_rows:declaredRows && /^\d+$/.test(declaredRows)?Math.min(Number(declaredRows),1000000):null});
      }
      const labels = Array.from(document.querySelectorAll("input:not([type=hidden]), [role=searchbox]"))
        .filter(visible).map(el=>clean(el.getAttribute("aria-label") || el.getAttribute("placeholder") ||
          (el.labels && Array.from(el.labels).map(x=>x.innerText).join(" ")))).filter(Boolean).slice(0,30);
      const body = document.body ? document.body.innerText.slice(0,5000).toLowerCase() : "";
      return {title:document.title.slice(0,300),table_headers:headers,tables,search_labels:labels,
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
    const tableDetails = Array.isArray(summary.tables) ? summary.tables.map((table,index)=>
      "\\nТаблица "+(index+1)+" ("+table.kind+", строк видно: "+table.visible_rows+
      (table.declared_rows===null?"":"/"+table.declared_rows)+"): "+table.columns.join(" · ")
    ).join("") : "";
    auditStatus.textContent = role+": "+(summary.login_required?"похоже, требуется вход": "страница доступна")+
      "; таблиц: "+(summary.tables?.length||0)+"; полей поиска: "+summary.search_labels.length+
      (summary.has_aria_grid?"; есть ARIA grid":"")+(summary.virtualized?"; вероятна виртуализация":"")+
      tableDetails+"\nПереданы только заголовки и размеры, значения ячеек не читались.";
    auditStatus.className = "status ok";
    setStatus("Структурная диагностика завершена. Это ещё не проверка заказов.", "ok");
  } catch (error) {
    const raw = typeof error?.message === "string" ? error.message : "";
    const reason = /Cannot access contents|cannot be scripted|host permission|permission/i.test(raw)
      ? "У расширения пока нет доступа к содержимому этой страницы. Разреши доступ к сайту в настройках расширения и повтори проверку."
      : /chrome:\/\/|edge:\/\/|about:|chromewebstore|extensions/i.test(inspectedPageUrl || "")
        ? "Эта служебная страница браузера недоступна для чтения расширением. Открой обычную рабочую страницу."
        : /tab|frame|document/i.test(raw)
          ? "Вкладка изменилась или закрылась во время проверки. Открой её снова и повтори."
          : "Не удалось получить структуру страницы или подтвердить локальный ответ Malenia. Проверь подключение агента и доступ расширения к сайту.";
    auditStatus.textContent = reason;
    auditStatus.className = "status error";
    setStatus("Проверка не завершена. Причина указана ниже.", "error");
  } finally { busy=false; updateButtons(); }
});


/* Explicit, user-mapped discovery of tabs already open in this browser.
 * Selection is a session snapshot only; consumers must revalidate tabId + URL
 * and current host permission immediately before any future page read.
 */
const discoveryRoles = [
  {key:"inventory",label:"ИНВента",input:"mapInventory"},
  {key:"datalens",label:"DataLens",input:"mapDatalens"},
  {key:"asgard",label:"Asgard",input:"mapAsgard"}
];
const discoveryButton = document.getElementById("discoverTabs");
const confirmDiscoveryButton = document.getElementById("confirmTabs");
const discoveryResults = document.getElementById("discoveryResults");
const discoveryStatus = document.getElementById("discoveryStatus");
let discoveryMappings = null;
let discoveryResult = null;
const discoverySelections = {};

function discoveryMappingFromInput(value) {
  let url;
  try { url = new URL(value.trim()); } catch { throw new Error("Укажи полный HTTPS-адрес ресурса."); }
  if (url.protocol !== "https:" || !url.hostname || url.username || url.password || url.port) {
    throw new Error("Разрешены только HTTPS-адреса без логина, пароля и нестандартного порта.");
  }
  return {origin:url.origin,pathPrefix:url.pathname || "/"};
}

function discoverySetStatus(message, kind="") {
  discoveryStatus.textContent = message;
  discoveryStatus.className = "status" + (kind ? " " + kind : "");
}

function discoveryRefreshConfirm() {
  confirmDiscoveryButton.disabled = !discoveryRoles.every(role =>
    discoverySelections[role.key] && discoveryResult?.roles?.[role.key]?.candidates
      ?.some(candidate => candidate.tabId === discoverySelections[role.key].tabId)
  );
}

function renderDiscoveryResults(result, permissionOrigins) {
  discoveryResults.replaceChildren();
  for (const role of discoveryRoles) {
    const state = result.roles[role.key];
    const section = document.createElement("div");
    section.className = "discovery-role";
    const heading = document.createElement("strong");
    heading.textContent = role.label + ": " + (
      state.state === "not_found" ? "не найдена" :
      state.state === "unique" ? "найдена одна вкладка" : "найдено несколько вкладок"
    );
    section.appendChild(heading);
    if (!permissionOrigins.includes(discoveryMappings[role.key].origin + "/*")) {
      const note = document.createElement("div");
      note.textContent = "Нет разрешения сайта. Разреши доступ к этому домену в настройках расширения и повтори поиск.";
      section.appendChild(note);
    }
    for (const candidate of state.candidates) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "discovery-candidate";
      button.setAttribute("aria-pressed", String(
        discoverySelections[role.key]?.tabId === candidate.tabId
      ));
      button.textContent = (candidate.active ? "● Активная · " : "") +
        (candidate.title || "Без заголовка") + " · " + candidate.sanitizedUrl;
      button.addEventListener("click", () => {
        discoverySelections[role.key] = candidate;
        renderDiscoveryResults(discoveryResult, permissionOrigins);
        discoveryRefreshConfirm();
        discoverySetStatus("Выбор " + role.label + " отмечен. Подтверди все три ресурса.", "");
      });
      section.appendChild(button);
    }
    discoveryResults.appendChild(section);
  }
  discoveryRefreshConfirm();
}

discoveryButton.addEventListener("click", async () => {
  if (busy) return;
  busy = true;
  updateButtons();
  discoveryButton.disabled = true;
  discoverySetStatus("Проверяем текущие вкладки и разрешения…");
  try {
    const raw = {};
    for (const role of discoveryRoles) {
      raw[role.key] = discoveryMappingFromInput(
        document.getElementById(role.input).value
      );
    }
    discoveryMappings = MaleniaTabDiscovery.normalizeMapping(raw);
    const [tabs, permissionState] = await Promise.all([
      chrome.tabs.query({}),
      chrome.permissions.getAll()
    ]);
    const grantedOrigins = Array.isArray(permissionState?.origins)
      ? permissionState.origins : [];
    discoveryResult = MaleniaTabDiscovery.discover(tabs, discoveryMappings, grantedOrigins);
    for (const role of discoveryRoles) delete discoverySelections[role.key];
    renderDiscoveryResults(discoveryResult, grantedOrigins);
    const found = discoveryRoles.filter(role =>
      discoveryResult.roles[role.key].candidates.length > 0
    ).length;
    discoverySetStatus("Найдено ресурсов: " + found + " из 3. Ни одна вкладка не читалась.", 
      found === 3 ? "ok" : "error");
  } catch (error) {
    discoveryResult = null;
    discoveryMappings = null;
    discoveryResults.textContent = error.message === "invalid_mappings"
      ? "Не удалось проверить адреса ресурсов." : error.message;
    discoverySetStatus("Поиск не выполнен. Проверь HTTPS-адреса и повтори попытку.", "error");
  } finally {
    busy = false;
    discoveryButton.disabled = false;
    updateButtons();
  }
});

async function confirmedTabHeaderSnapshot(role, entry) {
  if (!entry || !Number.isSafeInteger(entry.tabId) || entry.tabId < 0 ||
      typeof entry.origin !== "string" || typeof entry.path !== "string") {
    throw new Error("invalid_selection");
  }
  const permission = await chrome.permissions.contains({origins:[entry.origin + "/*"]});
  if (!permission) throw new Error("permissions_missing");
  const current = await chrome.tabs.get(entry.tabId);
  if (!current || typeof current.url !== "string") throw new Error("tab_closed");
  const currentUrl = new URL(current.url);
  if (currentUrl.protocol !== "https:" || currentUrl.origin !== entry.origin ||
      currentUrl.pathname !== entry.path) throw new Error("selected_document_changed");
  const identity = await chrome.scripting.executeScript({
    target:{tabId:entry.tabId},
    func:()=>({href:location.href})
  });
  const frame = identity?.[0];
  let identityUrl;
  try { identityUrl = new URL(frame?.result?.href || ""); } catch { identityUrl = null; }
  if (!frame || frame.frameId !== 0 || typeof frame.documentId !== "string" ||
      !frame.documentId || !identityUrl || identityUrl.origin !== entry.origin ||
      identityUrl.pathname !== entry.path) throw new Error("selected_document_changed");
  const inspected = await chrome.scripting.executeScript({
    target:{tabId:entry.tabId},
    func:(resourceRole)=>{
      const normalize = values => values.map(value =>
        (value || "").trim().replace(/\\s+/g," ").slice(0,120)
      ).filter(Boolean).slice(0,20);
      const tables = [];
      for (const table of [...document.querySelectorAll("table")].slice(0,8)) {
        const first = table.querySelector("tr");
        if (!first) continue;
        const headers = normalize([...first.querySelectorAll("th,[role='columnheader']")]
          .map(cell=>cell.innerText));
        if (headers.length) tables.push(headers);
      }
      if (!tables.length) {
        for (const grid of [...document.querySelectorAll('[role="grid"],[role="table"]')].slice(0,8)) {
          const headers = normalize([...grid.querySelectorAll('[role="columnheader"]')]
            .map(cell=>cell.innerText));
          if (headers.length) tables.push(headers);
        }
      }
      return {origin:location.origin,href:location.href,tables};
    },
    args:[role]
  });
  const readFrame = inspected?.[0];
  if (!readFrame || readFrame.frameId !== 0 || readFrame.documentId !== frame.documentId) {
    throw new Error("selected_document_changed");
  }
  const after = await chrome.tabs.get(entry.tabId);
  const afterIdentity = await chrome.scripting.executeScript({
    target:{tabId:entry.tabId},func:()=>({href:location.href})
  });
  const afterFrame = afterIdentity?.[0];
  let afterUrl;
  try { afterUrl = new URL(afterFrame?.result?.href || ""); } catch { afterUrl = null; }
  if (!after || typeof after.url !== "string" ||
      new URL(after.url).origin !== entry.origin || new URL(after.url).pathname !== entry.path ||
      !afterFrame || afterFrame.frameId !== 0 || afterFrame.documentId !== frame.documentId ||
      !afterUrl || afterUrl.origin !== entry.origin || afterUrl.pathname !== entry.path ||
      !await chrome.permissions.contains({origins:[entry.origin + "/*"]})) {
    throw new Error("selected_document_changed");
  }
  const snapshot = readFrame.result;
  if (!snapshot || snapshot.origin !== entry.origin || !Array.isArray(snapshot.tables)) {
    throw new Error("invalid_header_snapshot");
  }
  return snapshot.tables;
}

inspectMappedTabsButton.addEventListener("click", async () => {
  if (busy || !hasConfirmedTabs) return;
  busy = true;
  updateButtons();
  discoverySetStatus("Читаем только заголовки таблиц выбранных вкладок. Строки заказов не читаются…");
  try {
    const stored = await chrome.storage.session.get("maleniaConfirmedOpenTabs");
    const selection = stored?.maleniaConfirmedOpenTabs;
    const roles = ["inventory","datalens","asgard"];
    if (!selection?.browserSessionOnly || !Number.isFinite(selection.confirmedAt) ||
        Date.now()-selection.confirmedAt>30*60*1000 ||
        !selection.confirmed || Object.keys(selection.confirmed).sort().join(",")!==[...roles].sort().join(",")) {
      hasConfirmedTabs=false;
      throw new Error("selection_expired");
    }
    const results = [];
    for (const role of roles) {
      const tables = await confirmedTabHeaderSnapshot(role,selection.confirmed[role]);
      results.push({role,tables});
    }
    discoveryResults.replaceChildren();
    for (const result of results) {
      const section=document.createElement("div");
      section.className="discovery-role";
      const heading=document.createElement("strong");
      heading.textContent=({inventory:"ИНВента",datalens:"DataLens",asgard:"Asgard"})[result.role];
      section.appendChild(heading);
      if (!result.tables.length) {
        const empty=document.createElement("div");
        empty.textContent="Заголовки таблиц не найдены.";
        section.appendChild(empty);
      }
      for (const [index,headers] of result.tables.entries()) {
        const line=document.createElement("div");
        line.textContent="Таблица "+(index+1)+": "+headers.join(" · ");
        section.appendChild(line);
      }
      discoveryResults.appendChild(section);
    }
    discoverySetStatus("Диагностика завершена. Прочитаны только заголовки; строки, значения ячеек и полный текст страниц не читались.", "ok");
  } catch (error) {
    const safe = error?.message==="permissions_missing" ? "Разрешение сайта отозвано. Проверь настройки расширения." :
      error?.message==="tab_closed" ? "Одна из выбранных вкладок закрыта. Найди и подтверди вкладки заново." :
      error?.message==="selected_document_changed" ? "Одна из страниц изменилась во время проверки. Повтори поиск и подтверждение." :
      "Выбор вкладок устарел или недоступен. Найди и подтверди три вкладки заново.";
    discoverySetStatus(safe,"error");
  } finally {
    busy=false;
    updateButtons();
  }
});

(async()=>{
  try {
    const stored=await chrome.storage.session.get("maleniaConfirmedOpenTabs");
    const selection=stored?.maleniaConfirmedOpenTabs;
    hasConfirmedTabs=!!selection?.browserSessionOnly && Number.isFinite(selection.confirmedAt) &&
      Date.now()-selection.confirmedAt<=30*60*1000 &&
      selection.confirmed && ["inventory","datalens","asgard"].every(role=>selection.confirmed[role]);
    updateButtons();
  } catch { hasConfirmedTabs=false; updateButtons(); }
})();

confirmDiscoveryButton.addEventListener("click", async () => {
  if (busy || !discoveryMappings || !discoveryResult) return;
  busy = true;
  updateButtons();
  confirmDiscoveryButton.disabled = true;
  try {
    const confirmed = {};
    const permissionState = await chrome.permissions.getAll();
    const grantedOrigins = Array.isArray(permissionState?.origins)
      ? permissionState.origins : [];
    for (const role of discoveryRoles) {
      const selected = discoverySelections[role.key];
      if (!selected || !grantedOrigins.includes(discoveryMappings[role.key].origin + "/*")) {
        throw new Error("Разрешение отозвано или ресурс не выбран. Выполни поиск заново.");
      }
      const current = await chrome.tabs.get(selected.tabId);
      if (!current || typeof current.url !== "string") {
        throw new Error("Одна из вкладок закрыта. Выполни поиск заново.");
      }
      const fresh = MaleniaTabDiscovery.discover(
        [current], discoveryMappings, grantedOrigins
      ).roles[role.key];
      if (fresh.state !== "unique" || fresh.candidates[0].tabId !== selected.tabId ||
          fresh.candidates[0].origin !== selected.origin ||
          fresh.candidates[0].path !== selected.path) {
        throw new Error("Одна из вкладок изменилась после поиска. Выполни поиск заново.");
      }
      confirmed[role.key] = {
        tabId:selected.tabId,
        origin:selected.origin,
        path:selected.path,
        sanitizedUrl:selected.sanitizedUrl
      };
    }
    await chrome.storage.local.set({maleniaUserResourceMappings:discoveryMappings});
    await chrome.storage.session.set({
      maleniaConfirmedOpenTabs:{confirmed,confirmedAt:Date.now(),browserSessionOnly:true}
    });
    hasConfirmedTabs=true;
    updateButtons();
    discoverySetStatus("Три вкладки подтверждены. Страницы ещё не читались; перед будущим чтением Маления повторно проверит вкладки и разрешения.", "ok");
  } catch (error) {
    const safeMessage = typeof error?.message === "string" &&
      (error.message.includes("закрыта") || error.message.includes("изменилась") ||
       error.message.includes("Разрешение отозвано"))
      ? error.message
      : "Вкладка закрыта или стала недоступна. Выполни поиск заново.";
    discoverySetStatus(safeMessage, "error");
    discoveryRefreshConfirm();
  } finally {
    busy = false;
    updateButtons();
  }
});

(async () => {
  try {
    const stored = await chrome.storage.local.get("maleniaUserResourceMappings");
    const saved = stored?.maleniaUserResourceMappings;
    if (!saved) return;
    const checked = MaleniaTabDiscovery.normalizeMapping(saved);
    for (const role of discoveryRoles) {
      const input = document.getElementById(role.input);
      input.value = checked[role.key].origin + checked[role.key].pathPrefix;
    }
  } catch {
    discoverySetStatus("Сохранённые адреса некорректны. Введи адреса ресурсов заново.", "error");
  }
})();
