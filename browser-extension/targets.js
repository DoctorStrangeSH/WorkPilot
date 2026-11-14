/* Explicit one-time setup for the read-only order-checking skill. */
(() => {
  const fields = {
    inventory: document.getElementById("targetInventory"),
    datalens: document.getElementById("targetDatalens"),
    asgard: document.getElementById("targetAsgard"),
  };
  const button = document.getElementById("saveTargets");
  const status = document.getElementById("targetsStatus");
  const orderStatus = document.getElementById("orderAuditStatus");
  const discover = document.getElementById("discoverTargets");
  const selectors = Object.fromEntries(Object.keys(fields).map(role =>
    [role, document.getElementById("select" + role)]));
  const reasons = {
    invalid_inventory_search_keys:"Не удалось определить грузоместо для поиска",
    unmapped_search_form:"На странице не найдено подходящее поле поиска",
    unsupported_search_form:"Поиск устроен иначе, чем поддерживает адаптер",
    dynamic_search_ui:"Найден динамический поиск — нужен адаптер страницы",
    unsupported_dynamic_search:"Динамический поиск не удалось подтвердить",
    dynamic_search_no_result_update:"Таблица не обновилась после поиска",
    dynamic_search_unchanged_table:"Таблица не изменилась после поиска",
    unmapped_search_results:"Не удалось распознать таблицу результатов",
    unverified_search_result_identity:"Результат не совпал с искомым грузоместом",
    changed_search_schema:"Колонки таблицы изменились при поиске",
    virtualized_or_incomplete_grid:"Таблица неполная или использует виртуальную прокрутку",
    navigation_outside_allowed_origin:"Страница перенаправила на другой сайт",
    pagination_limit:"Не удалось безопасно прочитать все страницы",
    too_many_search_rows:"Превышен предел результатов поиска",
    native_host_rejected:"Локальное ядро отклонило данные страницы",
    reconciliation_unavailable:"Не удалось сверить данные источников: нужно подтвердить колонки",
    site_or_browser_error:"Ошибка при чтении сайта или браузера",
  };
  function renderAudit(audit) {
    if (!orderStatus || !audit || !Array.isArray(audit.results)) return;
    const labels = {inventory:"ИНВента",datalens:"DataLens",asgard:"Asgard"};
    const items = audit.results.map(item => {
      const source = labels[item.role];
      if (!source) return null;
      return item.status === "needs_attention" ?
        source+": "+(reasons[item.reason] || "Требуется проверка совместимости") :
        source+": чтение завершено";
    }).filter(Boolean);
    const end = audit.phase === "reconciled" ? "Сверка выполнена без изменений сайтов." :
      audit.phase === "read_only" ? (reasons[audit.reason] || "Только чтение: сверка не подтверждена") :
      audit.phase === "needs_attention" ? "Автоматическая проверка не завершена." : "Проверка выполняется…";
    orderStatus.textContent = [...items,end].join(" · ");
    orderStatus.className = "status"+(audit.phase === "reconciled" ? " ok" : "");
  }
  chrome.storage.session?.get("maleniaAudit").then(data => renderAudit(data?.maleniaAudit)).catch(()=>{});
  chrome.storage.onChanged?.addListener((changes,area) => {
    if (area === "session" && changes.maleniaAudit) renderAudit(changes.maleniaAudit.newValue);
  });
  const show = (message, kind = "") => {
    status.textContent = message;
    status.className = "status" + (kind ? " " + kind : "");
  };
  discover?.addEventListener("click", async () => {
    discover.disabled = true;
    try {
      const tabs = await chrome.tabs.query({});
      const pages = new Map();
      for (const tab of tabs) {
        try {
          const url = new URL(tab.url);
          const clean = url.origin + url.pathname;
          // Validate each candidate with the same rules as saved targets.
          MaleniaAutomation.normalizeTargets(Object.fromEntries(
            Object.keys(fields).map(role => [role, clean])));
          if (url.username || url.password) continue;
          if (!pages.has(clean)) pages.set(clean, {url:clean,
            title:String(tab.title || url.hostname).slice(0,120)});
        } catch { /* Internal browser pages and unsafe targets are omitted. */ }
      }
      const candidates = [...pages.values()].slice(0,100);
      for (const role of Object.keys(fields)) {
        const select = selectors[role];
        select.replaceChildren();
        const blank = document.createElement("option");
        blank.value = ""; blank.textContent = "Выберите открытую вкладку…";
        select.append(blank);
        for (const page of candidates) {
          const option = document.createElement("option");
          option.value = page.url;
          option.textContent = page.title + " · " + new URL(page.url).hostname;
          select.append(option);
        }
        select.value = pages.has(fields[role].value) ? fields[role].value : "";
      }
      show(candidates.length ? "Выбери вкладки ИНВенты, DataLens и Asgard, затем разреши чтение. Содержимое страниц ещё не читается." :
        "Открой рабочие HTTPS-вкладки в этом браузере и повтори поиск.");
    } catch { show("Не удалось получить список вкладок. Повтори поиск.", "error"); }
    finally { discover.disabled = false; }
  });
  for (const role of Object.keys(fields)) {
    selectors[role]?.addEventListener("change", () => { fields[role].value = selectors[role].value; });
  }
  const normalize = () => MaleniaAutomation.normalizeTargets(
    Object.fromEntries(Object.entries(fields).map(([role, field]) => [role, field.value.trim()])));
  chrome.storage.local.get("maleniaTargets").then(saved => {
    if (!saved?.maleniaTargets) return;
    try {
      const targets = MaleniaAutomation.normalizeTargets(saved.maleniaTargets);
      for (const role of Object.keys(fields)) fields[role].value = targets[role];
      show("Адреса сохранены. Можно запускать проверку из Малении.", "ok");
    } catch { show("Сохранённые адреса требуют повторной настройки.", "error"); }
  }).catch(() => show("Не удалось прочитать настройки браузера.", "error"));
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const targets = normalize();
      const allowed = await chrome.permissions.request({origins:MaleniaAutomation.origins(targets)});
      if (!allowed) {
        show("Разрешения не предоставлены. Адреса не сохранены.", "error");
        return;
      }
      await chrome.storage.local.set({maleniaTargets: targets, maleniaExactGetSearch:true});
      show("Готово! Запусти «Проверить первый заказ» в Малении.", "ok");
    } catch {
      // Never expose rejected URLs, credentials, or browser exception text.
      show("Проверь три HTTPS-адреса без параметров, фрагментов и встроенных паролей.", "error");
    } finally { button.disabled = false; }
  });
})();
