/* An allowlisted, read-only browser visit runner. No page actions or form access. */
var MaleniaAutomation = (() => {
  const ROLES = ["inventory", "datalens", "asgard"];
  const MAX_TEXT = 16000;
  function normalizeTargets(input) {
    if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("invalid_targets");
    if (Object.keys(input).sort().join(",") !== [...ROLES].sort().join(",")) throw new Error("invalid_roles");
    const result = {};
    for (const role of ROLES) {
      const raw = input[role];
      if (typeof raw !== "string" || raw.length > 2048) throw new Error("invalid_url");
      let url;
      try { url = new URL(raw); } catch { throw new Error("invalid_url"); }
      if (url.protocol !== "https:" || !url.hostname || url.username || url.password ||
          url.search || url.hash || url.port || url.hostname === "localhost" ||
          url.hostname.endsWith(".localhost") || url.hostname.endsWith(".local")) {
        throw new Error("unsafe_target");
      }
      result[role] = url.origin + url.pathname;
    }
    return result;
  }
  const origins = targets => [...new Set(ROLES.map(role => new URL(targets[role]).origin + "/*"))];

  async function waitLoaded(chromeApi, tabId, timeoutMs = 20000) {
    return new Promise((resolve, reject) => {
      let finished = false;
      const settle = (error) => {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        chromeApi.tabs.onUpdated.removeListener(onUpdated);
        if (error) reject(error); else resolve();
      };
      const onUpdated = (id, info) => {
        if (id === tabId && info.status === "complete") settle();
      };
      const timer = setTimeout(() => settle(new Error("page_timeout")), timeoutMs);
      chromeApi.tabs.onUpdated.addListener(onUpdated);
      chromeApi.tabs.get(tabId).then(tab => {
        if (tab.status === "complete") settle();
      }).catch(() => settle(new Error("tab_closed")));
    });
  }

  async function visit(chromeApi, role, url, sendNative) {
    let tabId;
    try {
      const tab = await chromeApi.tabs.create({url, active: false});
      if (!Number.isInteger(tab.id)) throw new Error("invalid_tab");
      tabId = tab.id;
      await waitLoaded(chromeApi, tabId);
      const current = await chromeApi.tabs.get(tabId);
      const finalUrl = new URL(current.url || "");
      if (finalUrl.origin !== new URL(url).origin || finalUrl.protocol !== "https:" ||
          finalUrl.username || finalUrl.password) throw new Error("navigation_outside_allowed_origin");
      const results = await chromeApi.scripting.executeScript({
        target: {tabId},
        func: () => {
          // Only rendered text: no fields, form input values, cookies or hidden DOM.
          const text = document.body ? document.body.innerText : "";
          return typeof text === "string" ? text.slice(0, 16000) : "";
        }
      });
      const text = results?.[0]?.result;
      if (typeof text !== "string" || !text.trim()) throw new Error("empty_page");
      const response = await sendNative({
        type: "inspect_active_page",
        page: {url: finalUrl.origin + finalUrl.pathname, text},
      });
      if (!response || !response.ok || response.type !== "page_inspected" ||
          response.persisted !== false || response.characters !== text.length) {
        throw new Error("native_host_rejected");
      }
      return {role, status: "read", characters: text.length};
    } finally {
      if (tabId !== undefined) {
        try { await chromeApi.tabs.remove(tabId); } catch { /* Tab may already be closed. */ }
      }
    }
  }

  async function run(chromeApi, input, sendNative, onProgress) {
    const targets = normalizeTargets(input);
    const results = [];
    for (const role of ROLES) {
      onProgress({phase: "reading", role, results: [...results]});
      try {
        results.push(await visit(chromeApi, role, targets[role], sendNative));
      } catch {
        // Never expose or log raw page errors; some browser errors contain URLs.
        results.push({role, status: "needs_attention"});
      }
      onProgress({phase: "reading", role, results: [...results]});
    }
    const complete = results.every(item => item.status === "read");
    const summary = {phase: complete ? "completed" : "needs_attention", results};
    onProgress(summary);
    return summary;
  }
  return {ROLES, MAX_TEXT, normalizeTargets, origins, waitLoaded, run};
})();
