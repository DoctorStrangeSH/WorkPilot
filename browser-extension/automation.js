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

  // Public, fixed diagnostic codes: never persist raw site exceptions or URLs.
  const SAFE_FAILURE_CODES = new Set([
    "invalid_inventory_search_keys", "unmapped_search_form", "invalid_search",
    "unsafe_search_target", "unverified_search_result_identity",
    "unmapped_search_results", "changed_search_schema", "too_many_search_rows",
    "virtualized_or_incomplete_grid", "navigation_outside_allowed_origin",
    "search_origin_mismatch", "unexpected_document", "empty_page",
    "unmapped_paginated_table", "pagination_cycle", "pagination_limit",
    "changed_table_schema", "too_many_rows", "native_host_rejected",
    "page_timeout", "tab_closed", "unsupported_search_form",
    "dynamic_search_ui", "unsupported_dynamic_search",
    "dynamic_search_no_result_update", "dynamic_search_unchanged_table"
  ]);
  function reasonCode(error) {
    return error instanceof Error && SAFE_FAILURE_CODES.has(error.message) ?
      error.message : "site_or_browser_error";
  }

  const MAX_SEARCHES = 20;
  // Optimization only: the Python reconciliation engine remains authoritative.
  // We may avoid sending a cargo code to Asgard only with complete, exact
  // evidence of a later successful scan at the approved SC.
  function asgardSearchKeys(inventory, datalens) {
    if (!inventory || !datalens || !Array.isArray(inventory.rows) ||
        !Array.isArray(datalens.rows) || !Array.isArray(inventory.columns) ||
        !Array.isArray(datalens.columns)) return null;
    const invFields = ["cargo_place", "inventory_date"];
    const scanFields = ["main_partner_code_original", "sc_id", "result", "scanned_at"];
    if (!invFields.every(x => inventory.columns.includes(x)) ||
        !scanFields.every(x => datalens.columns.includes(x))) return null;
    const col = (table, field) => table.columns.indexOf(field);
    const unresolved = [];
    for (const row of inventory.rows) {
      if (!Array.isArray(row)) return null;
      const cargo = row[col(inventory, "cargo_place")];
      const cutoff = row[col(inventory, "inventory_date")];
      if (typeof cargo !== "string" || !/^[A-Za-z0-9_.-]{1,128}$/.test(cargo) ||
          typeof cutoff !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(cutoff) ||
          !Number.isFinite(Date.parse(cutoff)) ||
          new Date(cutoff).toISOString().slice(0, 10) !== cutoff) return null;
      const matching = datalens.rows.filter(scan => Array.isArray(scan) &&
        scan[col(datalens, "main_partner_code_original")] === cargo &&
        scan[col(datalens, "sc_id")] === "101366" &&
        scan[col(datalens, "result")] === "OK");
      const valid = matching.every(scan => {
        const raw = scan[col(datalens, "scanned_at")];
        return typeof raw === "string" &&
          /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}/.test(raw) &&
          Number.isFinite(Date.parse(raw));
      });
      if (!valid || !matching.some(scan => scan[col(datalens, "scanned_at")].slice(0, 10) > cutoff)) {
        unresolved.push(cargo);
      }
    }
    return unresolved;
  }
  async function exactGetSearch(chromeApi, tabId, role, cargo, origin) {
    if (!["datalens", "asgard"].includes(role) ||
        typeof cargo !== "string" || !/^[A-Za-z0-9_.-]{1,128}$/.test(cargo)) {
      throw new Error("invalid_search");
    }
    const results = await chromeApi.scripting.executeScript({
      target: {tabId},
      func: (resourceRole, code) => {
        const fieldName = resourceRole === "datalens" ?
          "main_partner_code_original" : "cargo_place";
        const allForms = [...document.querySelectorAll("form")];
        const forms = allForms.filter(form =>
          form.method.toLowerCase() === "get" &&
          form.querySelectorAll('input[type="password"],input[type="hidden"]').length === 0 &&
          form.querySelectorAll('input[name="' + fieldName + '"]').length === 1 &&
          form.querySelectorAll("input[name]").length === 1);
        if (forms.length !== 1) {
          // Report the type of unsupported UI, never labels, form values or URLs.
          const standaloneSearch = [...document.querySelectorAll(
            'input[type="search"],input[role="searchbox"]'
          )].some(input => !input.closest("form") &&
            (input.getAttribute("aria-label") || input.getAttribute("name") || "").trim() ===
              fieldName);
          const kind = standaloneSearch ? "dynamic_search_ui" :
            allForms.length ? "unsupported_search_form" : "unmapped_search_form";
          return {origin: location.origin, kind};
        }
        const form = forms[0];
        const input = form.querySelector('input[name="' + fieldName + '"]');
        if (!["search", "text"].includes(input.type.toLowerCase())) return null;
        const action = new URL(form.getAttribute("action") || location.href, location.href);
        if (action.origin !== location.origin || action.protocol !== "https:" ||
            action.username || action.password || action.hash || action.search) return null;
        action.searchParams.set(fieldName, code);
        return {origin: location.origin, url: action.href};
      },
      args: [role, cargo]
    });
    const result = results?.[0]?.result;
    if (!result || result.origin !== origin || typeof result.url !== "string") {
      const kind = result?.origin === origin && [
        "unsupported_search_form", "dynamic_search_ui"
      ].includes(result.kind) ? result.kind : "unmapped_search_form";
      throw new Error(kind);
    }
    const target = new URL(result.url);
    if (target.protocol !== "https:" || target.origin !== origin ||
        target.username || target.password || target.hash ||
        target.searchParams.size !== 1 ||
        target.searchParams.get(role === "datalens" ?
          "main_partner_code_original" : "cargo_place") !== cargo) {
      throw new Error("unsafe_search_target");
    }
    await chromeApi.tabs.update(tabId, {url: target.href});
  }

  async function reactiveSearch(chromeApi, tabId, role, cargo, origin) {
    if (!["datalens", "asgard"].includes(role) ||
        typeof cargo !== "string" || !/^[A-Za-z0-9_.-]{1,128}$/.test(cargo)) {
      throw new Error("invalid_search");
    }
    const results = await chromeApi.scripting.executeScript({
      target: {tabId},
      func: async (resourceRole, code) => {
        const fieldName = resourceRole === "datalens" ?
          "main_partner_code_original" : "cargo_place";
        // No form submission, Enter/keyboard shortcuts, clicks or scripts from the site.
        // Accept ONLY a standalone, visible, labelled search-as-you-type field.
        const matches = [...document.querySelectorAll(
          'input[type="search"],input[role="searchbox"]'
        )].filter(input => {
          if (input.closest("form") || input.disabled || input.readOnly ||
              input.type.toLowerCase() === "password") return false;
          const label = (input.getAttribute("aria-label") ||
            input.getAttribute("name") || "").trim();
          return label === fieldName && input.getClientRects().length > 0;
        });
        if (matches.length !== 1) return {origin: location.origin, status: "ambiguous"};
        const input = matches[0];
        // Observe a matching result table, not unrelated spinners/navigation.
        const expected = resourceRole === "datalens" ?
          ["main_partner_code_original", "sc_id", "result", "scanned_at"] :
          ["cargo_place", "status"];
        const containers = [...document.querySelectorAll(
          'table,[role="grid"],[role="table"]'
        )].filter(node => {
          const heads = [...node.querySelectorAll(
            'th,[role="columnheader"]'
          )].map(cell => cell.innerText.trim());
          return expected.every(header => heads.includes(header));
        });
        if (containers.length !== 1) {
          return {origin: location.origin, status: "unsupported"};
        }
        // Prove the result table actually changed; a loading-spinner or
        // unrelated mutation is not evidence of an updated result set.
        const before = containers[0].innerText;
        if (typeof before !== "string" || before.length > 16000) {
          return {origin: location.origin, status: "unsupported"};
        }
        // Use the native setter so common controlled React/Vue inputs see the update.
        const setter = Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype, "value")?.set;
        if (typeof setter !== "function") {
          return {origin: location.origin, status: "unsupported"};
        }
        const result = await new Promise(resolve => {
          let settled = false, changed = false, settleTimer;
          const finish = status => {
            if (settled) return;
            settled = true;
            clearTimeout(deadline);
            clearTimeout(settleTimer);
            observer.disconnect();
            const after = containers[0].innerText;
            resolve({origin: location.origin, status:
              status === "updated" && typeof after === "string" && after !== before ?
                "updated" : status === "updated" ? "unchanged_table" : status});
          };
          const observer = new MutationObserver(() => {
            if (settled) return;
            changed = true;
            clearTimeout(settleTimer);
            // Wait for the grid to settle instead of reading its loading frame.
            settleTimer = setTimeout(() => finish("updated"), 400);
          });
          observer.observe(containers[0], {subtree: true, childList: true,
            characterData: true});
          const deadline = setTimeout(() => finish(changed ? "updated" : "unchanged"), 6000);
          setter.call(input, code);
          input.dispatchEvent(new Event("input", {bubbles: true}));
        });
        return result;
      },
      args: [role, cargo]
    });
    const outcome = results?.[0]?.result;
    if (!outcome || outcome.origin !== origin ||
        outcome.status !== "updated") {
      throw new Error(outcome?.status === "unchanged" ?
        "dynamic_search_no_result_update" :
        outcome?.status === "unchanged_table" ?
          "dynamic_search_unchanged_table" : "unsupported_dynamic_search");
    }
  }

  async function visit(chromeApi, role, url, sendNative, searchKey = null) {
    let tabId;
    try {
      const tab = await chromeApi.tabs.create({url, active: false});
      if (!Number.isInteger(tab.id)) throw new Error("invalid_tab");
      tabId = tab.id;
      if (searchKey !== null) {
        await waitLoaded(chromeApi, tabId);
        const current = await chromeApi.tabs.get(tabId);
        if (new URL(current.url || "").origin !== new URL(url).origin) {
          throw new Error("search_origin_mismatch");
        }
        try {
          await exactGetSearch(chromeApi, tabId, role, searchKey, new URL(url).origin);
        } catch (error) {
          if (!(error instanceof Error) || error.message !== "dynamic_search_ui") {
            throw error;
          }
          await reactiveSearch(chromeApi, tabId, role, searchKey, new URL(url).origin);
        }
      }
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
            // Accessible ARIA grids are common in SPA dashboards. Read only
            // fully rendered rows with exact headers; never invent missing rows.
            let incomplete = false;
            if (!table) {
              for (const grid of document.querySelectorAll('[role="grid"],[role="table"]')) {
                const rows = [...grid.querySelectorAll('[role="row"]')];
                const head = rows[0] ?
                  [...rows[0].querySelectorAll('[role="columnheader"]')]
                    .map(cell => cell.innerText.trim()) : [];
                if (!required.every(name => head.includes(name)) || head.length > 20) continue;
                const declared = grid.getAttribute("aria-rowcount");
                const count = declared === null ? null : Number(declared);
                // ARIA grids frequently virtualize unseen rows. Only an
                // explicit matching total count is acceptable evidence.
                if (declared === null || !Number.isInteger(count) || count !== rows.length) {
                  incomplete = true; break;
                }
                const bodyRows = rows.slice(1);
                if (bodyRows.length > 100) {
                  incomplete = true; break;
                }
                const entries = [];
                let malformed = false;
                for (const row of bodyRows) {
                  const cells = [...row.querySelectorAll('[role="gridcell"],[role="cell"]')];
                  if (cells.length !== head.length) { malformed = true; break; }
                  entries.push(cells.map(cell => cell.innerText.trim().slice(0, 256)));
                }
                if (malformed || head.some(c => c.length > 256)) {
                  incomplete = true; break;
                }
                table = {columns: head, rows: entries};
                break;
              }
            }
            const nextAnchor = document.querySelector("a[rel~='next'][href]");
            return {
              origin: location.origin,
              text: typeof text === "string" ? text.slice(0, 16000) : "",
              table,
              incomplete,
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
        if (snapshot.incomplete) throw new Error("virtualized_or_incomplete_grid");
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

  async function run(chromeApi, input, sendNative, onProgress, options = {}) {
    const targets = normalizeTargets(input);
    const results = [];
    const snapshots = {};
    if (options.seedInventory !== undefined) {
      const seed = options.seedInventory;
      if (!seed || JSON.stringify(seed.columns) !== JSON.stringify(["cargo_place", "inventory_date"]) ||
          !Array.isArray(seed.rows) || seed.rows.length < 1 ||
          seed.rows.length > MAX_SEARCHES ||
          seed.rows.some(row => !Array.isArray(row) || row.length !== 2 ||
            typeof row[0] !== "string" || !/^[A-Za-z0-9_.-]{1,128}$/.test(row[0]) ||
            typeof row[1] !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(row[1]) ||
            !Number.isFinite(Date.parse(row[1])) ||
            new Date(row[1]).toISOString().slice(0,10) !== row[1]) ||
          new Set(seed.rows.map(row => row[0])).size !== seed.rows.length) {
        throw new Error("invalid_inventory_search_keys");
      }
      snapshots.inventory = {columns:["cargo_place","inventory_date"],
        rows:seed.rows.map(row => [...row])};
    }
    for (const role of ROLES) {
      await onProgress({phase: "reading", role, results: [...results]});
      if (role === "inventory" && snapshots.inventory) {
        results.push({role,status:"read",characters:0,pages:0});
        await onProgress({phase:"reading",role,results:[...results]});
        continue;
      }
      try {
        const inventoryKeys = snapshots.inventory?.rows?.map(row =>
          row[snapshots.inventory.columns.indexOf("cargo_place")]);
        const searchKeys = role !== "inventory" && options.exactGetSearch ?
          (role === "asgard" ? asgardSearchKeys(snapshots.inventory, snapshots.datalens) ??
            inventoryKeys : inventoryKeys) : null;
        if (role !== "inventory" && options.exactGetSearch &&
            (!Array.isArray(searchKeys) || (role !== "asgard" && !searchKeys.length) ||
             searchKeys.length > MAX_SEARCHES || new Set(searchKeys).size !== searchKeys.length ||
             searchKeys.some(key => typeof key !== "string" ||
               !/^[A-Za-z0-9_.-]{1,128}$/.test(key)))) {
          throw new Error("invalid_inventory_search_keys");
        }
        if (role === "asgard" && Array.isArray(searchKeys) && !searchKeys.length) {
          snapshots.asgard = {columns:["cargo_place", "status"],rows:[]};
          results.push({role, status:"read", characters:0, pages:0});
          await onProgress({phase:"reading",role,results:[...results]});
          continue;
        }
        const keys = searchKeys || [null];
        let table = null, characters = 0, pages = 0;
        for (const key of keys) {
          const visitResult = await visit(chromeApi, role, targets[role], sendNative, key);
          if (options.exactGetSearch && !visitResult.table) {
            throw new Error("unmapped_search_results");
          }
          if (key !== null) {
            const codeField = role === "datalens" ?
              "main_partner_code_original" : "cargo_place";
            const column = visitResult.table.columns.indexOf(codeField);
            if (column < 0 || visitResult.table.rows.some(row =>
                !Array.isArray(row) || row[column] !== key)) {
              throw new Error("unverified_search_result_identity");
            }
          }
          characters += visitResult.characters;
          pages += visitResult.pages;
          if (visitResult.table) {
            if (!table) table = {columns: visitResult.table.columns,
              rows: [...visitResult.table.rows]};
            else {
              if (table.columns.length !== visitResult.table.columns.length ||
                  table.columns.some((col, i) => col !== visitResult.table.columns[i])) {
                throw new Error("changed_search_schema");
              }
              table.rows.push(...visitResult.table.rows);
              if (table.rows.length > 100) throw new Error("too_many_search_rows");
            }
          }
        }
        if (table) snapshots[role] = table;
        results.push({role, status: "read", characters, pages});
      } catch (error) {
        // Only constant known codes are allowed in persisted progress. Browser errors
        // often contain a URL, which may include cargo identifiers or session data.
        results.push({role, status: "needs_attention", reason: reasonCode(error)});
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
      ...(!reconciliation && complete ? {reason:"reconciliation_unavailable"} : {}),
      ...(reconciliation ? {reconciliation} : {})};
    await onProgress(summary);
    return summary;
  }
  return {ROLES, MAX_TEXT, MAX_PAGES, MAX_SEARCHES, normalizeTargets, origins, nextPage, exactGetSearch, reactiveSearch, asgardSearchKeys, reasonCode, waitLoaded, run};
})();
