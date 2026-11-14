/* Explicit one-time setup for the read-only order-checking skill. */
(() => {
  const fields = {
    inventory: document.getElementById("targetInventory"),
    datalens: document.getElementById("targetDatalens"),
    asgard: document.getElementById("targetAsgard"),
  };
  const button = document.getElementById("saveTargets");
  const status = document.getElementById("targetsStatus");
  const show = (message, kind = "") => {
    status.textContent = message;
    status.className = "status" + (kind ? " " + kind : "");
  };
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
