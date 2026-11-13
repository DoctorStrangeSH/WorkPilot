/* Background task, bounded to three explicitly permitted resources. */
importScripts("automation.js");
const HOST = "com.malenia.browser";
let running = false;

function nativeSession() {
  // A native messaging port keeps the MV3 worker alive while the job is active.
  const port = chrome.runtime.connectNative(HOST);
  let pending = null;
  let closed = false;
  port.onMessage.addListener(response => {
    if (!pending) return;
    const active = pending;
    pending = null;
    clearTimeout(active.timer);
    if (!response || response.request_id !== active.id) active.reject(new Error("host_protocol"));
    else active.resolve(response);
  });
  port.onDisconnect.addListener(() => {
    closed = true;
    if (pending) {
      const active = pending;
      pending = null;
      clearTimeout(active.timer);
      active.reject(new Error("host_disconnected"));
    }
  });
  return {
    send(message) {
      if (closed || pending) return Promise.reject(new Error("host_not_ready"));
      return new Promise((resolve, reject) => {
        const id = crypto.randomUUID();
        const timer = setTimeout(() => {
          if (pending && pending.id === id) {
            pending = null;
            closed = true;
            port.disconnect();
            reject(new Error("host_timeout"));
          }
        }, 5000);
        pending = {id, timer, resolve, reject};
        try { port.postMessage({...message, request_id:id}); }
        catch {
          clearTimeout(timer);
          pending = null;
          closed = true;
          reject(new Error("host_disconnected"));
        }
      });
    },
    close() {
      closed = true;
      if (pending) {
        const active = pending;
        pending = null;
        clearTimeout(active.timer);
        active.reject(new Error("host_closed"));
      }
      port.disconnect();
    }
  };
}

async function progress(snapshot) {
  // Never store page text, cargo codes, login data, or raw browser errors.
  await chrome.storage.session.set({maleniaAudit:snapshot});
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (!message || message.type !== "start_readonly_audit") return false;
  if (running) { respond({ok:false,error:"already_running"});return false; }
  let targets;
  try { targets=MaleniaAutomation.normalizeTargets(message.targets); }
  catch { respond({ok:false,error:"invalid_targets"});return false; }
  running=true;
  respond({ok:true});
  (async () => {
    let session;
    try {
      const allowed=await chrome.permissions.contains({origins:MaleniaAutomation.origins(targets)});
      if (!allowed) throw new Error("permissions_missing");
      await progress({phase:"starting",results:[]});
      session=nativeSession();
      const hello=await session.send({type:"hello"});
      if (!hello.ok || hello.host!==HOST ||
          !Array.isArray(hello.capabilities) ||
          !hello.capabilities.includes("inspect_active_page")) {
        throw new Error("unsupported_host");
      }
      await MaleniaAutomation.run(chrome,targets,message=>session.send(message),progress,
        {exactGetSearch:message.exactGetSearch === true});
    } catch {
      await progress({phase:"needs_attention",results:[],error:"setup_or_connection"});
    } finally {
      session?.close();
      running=false;
    }
  })();
  return false;
});


// Desktop-triggered jobs use a separate one-shot request queue. The extension
// wakes periodically, never accepts arbitrary URLs or page actions from desktop.
const DESKTOP_AUDIT_ALARM = "malenia-desktop-audit-check";
async function pollDesktopAudit() {
  if (running) return;
  let session;
  try {
    const [stored, sessionState] = await Promise.all([
      chrome.storage.local.get(["maleniaExactGetSearch"]),
      chrome.storage.session.get("maleniaConfirmedOpenTabs")
    ]);
    const selected = sessionState?.maleniaConfirmedOpenTabs;
    const confirmed = selected?.confirmed;
    const roles = ["inventory", "datalens", "asgard"];
    if (!selected?.browserSessionOnly || !Number.isFinite(selected.confirmedAt) ||
        Date.now() - selected.confirmedAt > 30 * 60 * 1000 ||
        !confirmed || Object.keys(confirmed).sort().join(",") !== [...roles].sort().join(",")) return;
    const rawTargets = {};
    const selectedTabs = {};
    for (const role of roles) {
      const entry = confirmed[role];
      if (!entry || !Number.isSafeInteger(entry.tabId) || entry.tabId < 0 ||
          typeof entry.origin !== "string" || typeof entry.path !== "string" ||
          !entry.path.startsWith("/") || entry.path.includes("?") || entry.path.includes("#")) return;
      let origin;
      try {
        origin = new URL(entry.origin);
        if (origin.protocol !== "https:" || origin.origin !== entry.origin ||
            origin.pathname !== "/" || origin.search || origin.hash || origin.port) return;
      } catch { return; }
      const current = await chrome.tabs.get(entry.tabId).catch(() => null);
      if (!current || typeof current.url !== "string") return;
      let currentUrl;
      try { currentUrl = new URL(current.url); } catch { return; }
      if (currentUrl.protocol !== "https:" || currentUrl.origin !== entry.origin ||
          currentUrl.pathname !== entry.path || currentUrl.username || currentUrl.password ||
          currentUrl.port) return;
      rawTargets[role] = entry.origin + entry.path;
      selectedTabs[role] = {tabId:entry.tabId,origin:entry.origin,path:entry.path};
    }
    const targets = MaleniaAutomation.normalizeTargets(rawTargets);
    if (!await chrome.permissions.contains({origins:MaleniaAutomation.origins(targets)})) return;
    session = nativeSession();
    const hello = await session.send({type:"hello"});
    if (!hello?.ok || hello.host !== HOST ||
        !hello.capabilities?.includes("claim_browser_audit") ||
        !hello.capabilities?.includes("finish_browser_audit") ||
        !hello.capabilities?.includes("update_browser_audit_progress") ||
        !hello.capabilities?.includes("reconcile_site_tables")) return;
    const claimed = await session.send({type:"claim_browser_audit"});
    const jobId = claimed?.job?.job_id;
    if (!claimed?.ok || !claimed.job || typeof jobId !== "string") return;
    running = true;
    let succeeded = false;
    try {
      await progress({phase:"starting",results:[]});
      const report = async snapshot => {
        await progress(snapshot);
        const results = snapshot.results || [];
        const failures = results.filter(item => item.status === "needs_attention");
        const failedRole = failures.length ? failures[failures.length-1].role : null;
        const currentRole = ["inventory","datalens","asgard"].includes(snapshot.role) ?
          snapshot.role : null;
        const response = await session.send({
          type:"update_browser_audit_progress",job_id:jobId,
          current_role:currentRole,completed_sources:results.length,
          attention_sources:failures.length,failed_role:failedRole
        });
        if (!response?.ok || response.type !== "browser_audit_progress_updated") {
          throw new Error("audit_progress_unavailable");
        }
      };
      // Revalidate the selected documents immediately before the read runner starts.
      for (const role of roles) {
        const entry = selectedTabs[role];
        const current = await chrome.tabs.get(entry.tabId).catch(() => null);
        if (!current || typeof current.url !== "string") throw new Error("selected_tab_unavailable");
        const page = new URL(current.url);
        if (page.protocol !== "https:" || page.origin !== entry.origin ||
            page.pathname !== entry.path) throw new Error("selected_tab_changed");
      }
      if (!await chrome.permissions.contains({origins:MaleniaAutomation.origins(targets)})) {
        throw new Error("permissions_missing");
      }
      const result = await MaleniaAutomation.run(chrome,targets,
        message=>session.send(message),report,
        {exactGetSearch:false,selectedTabs});
      succeeded = result.phase === "reconciled";
    } catch {
      await progress({phase:"needs_attention",results:[],error:"setup_or_connection"});
    } finally {
      // Never retry an unacknowledged claim automatically. The store expires it.
      try { await session.send({type:"finish_browser_audit",job_id:jobId,succeeded}); }
      catch { /* Extension may have disconnected. */ }
      running = false;
    }
  } catch { /* Host unavailable, no permissions, or extension restarting. */ }
  finally { session?.close(); }
}
function enableDesktopAuditPolling() {
  chrome.alarms.create(DESKTOP_AUDIT_ALARM,{periodInMinutes:1});
}
chrome.runtime.onInstalled.addListener(enableDesktopAuditPolling);
chrome.runtime.onStartup.addListener(enableDesktopAuditPolling);
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === DESKTOP_AUDIT_ALARM) void pollDesktopAudit();
});
enableDesktopAuditPolling();
