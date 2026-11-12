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

  const MAX_PAGES = 5;
  function nextPage(current, raw) {
    if (typeof raw !== "string" || !raw || raw.length > 2048) throw new Error("invalid_next_page");
    const from = new URL(current);
    const to = new URL(raw, from);
    if (to.protocol !== "https:" || to.origin !== from.origin ||
        to.username || to.password || to.hash || to.port) throw new Error("unsafe_next_page");
    return to.href;
  }

  async function visit(chromeApi, role, url, sendNative) {
    let tabId;
    try {
      const tab = await chromeApi.tabs.create({url, active: false});
      if (!Number.isInteger(tab.id)) throw new Error("invalid_tab");
      tabId = tab.id;
      const visited = new Set();
      let expected = url;
      let combinedTable = null;
      let characters = 0;
      let pages = 0;
      for (let index = 0; index < MAX_PAGES; index++) {
        await waitLoaded(chromeApi, tabId);
        const current = await chromeApi.tabs.get(tabId);
        const finalUrl = new URL(current.url || "");
        if (finalUrl.origin !== new URL(url).origin || finalUrl.protocol !== "https:" ||
            finalUrl.username || finalUrl.password) throw new Error("navigation_outside_allowed_origin");
        const currentKey = finalUrl.href;
        if (visited.has(currentKey)) throw new Error("pagination_cycle");
        visited.add(currentKey);
        const results = await chromeApi.scripting.executeScript({
          target: {tabId},
          func: (resourceRole) => {
            // Only visible table text, not input values/cookies.
            const text = document.body ? document.body.innerText : "";
            const required = {
              inventory: ["cargo_place", "inventory_date"],
              datalens: ["main_partner_code_original", "sc_id", "result", "scanned_at"],
              asgard: ["cargo_place", "status"]
            }[resourceRole];
            let table = null;
            for (const element of document.querySelectorAll("table")) {
              const rows = [...element.querySelectorAll("tr")];
              const header = rows[0] ?
                [...rows[0].querySelectorAll("th")].map(c => c.innerText.trim()) : [];
              if (!required.every(name => header.includes(name)) || header.length > 20) continue;
              if (rows.length > 101 || header.some(c => c.length > 256)) continue;
              const entries = [];
              let malformed = false;
              for (const row of rows.slice(1)) {
                const cells = [...row.querySelectorAll("td")];
                if (cells.length !== header.length) { malformed = true; break; }
                entries.push(cells.map(cell => cell.innerText.trim().slice(0, 256)));
              }
              if (malformed) continue;
              table = {columns: header, rows: entries};
              break;
            }
            const nextAnchor = document.querySelector("a[rel~='next'][href]");
            return {
              origin: location.origin,
              text: typeof text === "string" ? text.slice(0, 16000) : "",
              table,
              next: nextAnchor ? nextAnchor.href : null
            };
          },
          args: [role]
        });
        const snapshot = results?.[0]?.result;
        if (!snapshot || snapshot.origin !== finalUrl.origin ||
            typeof snapshot.text !== "string" || !snapshot.text.trim()) {
          throw new Error("unexpected_document");
        }
        const text = snapshot.text;
        const response = await sendNative({
          type: "inspect_active_page",
          page: {url: finalUrl.origin + finalUrl.pathname, text},
        });
        if (!response || !response.ok || response.type !== "page_inspected" ||
            response.persisted !== false || response.characters !== text.length) {
          throw new Error("native_host_rejected");
        }
        pages++;
        characters += text.length;
        if (snapshot.table) {
          const table = snapshot.table;
          if (!Array.isArray(table.columns) || !Array.isArray(table.rows)) {
            throw new Error("invalid_table");
          }
          if (!combinedTable) {
            combinedTable = {columns: table.columns, rows: [...table.rows]};
          } else {
            if (combinedTable.columns.length !== table.columns.length ||
                combinedTable.columns.some((col, i) => col !== table.columns[i])) {
              throw new Error("changed_table_schema");
            }
            combinedTable.rows.push(...table.rows);
          }
          if (combinedTable.rows.length > 100) throw new Error("too_many_rows");
        }
        if (!snapshot.next) {
          return {role, status: "read", characters, pages, table: combinedTable};
        }
        // A pagination signal without the expected table must never produce a partial audit.
        if (!combinedTable || !snapshot.table) throw new Error("unmapped_paginated_table");
        const next = nextPage(finalUrl.href, snapshot.next);
        if (visited.has(next) || index === MAX_PAGES - 1) throw new Error("pagination_limit");
        expected = next;
        await chromeApi.tabs.update(tabId, {url: expected});
      }
      throw new Error("pagination_limit");
    } finally {
      if (tabId !== undefined) {
        try { await chromeApi.tabs.remove(tabId); } catch { /* Tab already closed. */ }
      }
    }
  }

  async function run(chromeApi, input, sendNative, onProgress) {
    const targets = normalizeTargets(input);
    const results = [];
    const snapshots = {};
    for (const role of ROLES) {
      await onProgress({phase: "reading", role, results: [...results]});
      try {
        const visitResult = await visit(chromeApi, role, targets[role], sendNative);
        if (visitResult.table) snapshots[role] = visitResult.table;
        results.push({role, status: "read", characters: visitResult.characters, pages: visitResult.pages});
      } catch {
        // Never expose or log raw page errors; some browser errors contain URLs.
        results.push({role, status: "needs_attention"});
      }
      await onProgress({phase: "reading", role, results: [...results]});
    }
    const complete = results.every(item => item.status === "read");
    let reconciliation = null;
    if (complete && ROLES.every(role => snapshots[role])) {
      try {
        const response = await sendNative({type: "reconcile_site_tables", snapshots});
        if (response?.ok && response.type === "site_tables_reconciled" &&
            response.read_only === true && response.write_enabled === false &&
            response.persisted === false) {
          reconciliation = {total: response.total, summary: response.summary};
        }
      } catch { /* Schema mismatch or old host: report no reconciliation. */ }
    }
    const summary = {phase: !complete ? "needs_attention" :
      reconciliation ? "reconciled" : "read_only", results,
      ...(reconciliation ? {reconciliation} : {})};
    await onProgress(summary);
    return summary;
  }
  return {ROLES, MAX_TEXT, MAX_PAGES, normalizeTargets, origins, nextPage, waitLoaded, run};
})();
