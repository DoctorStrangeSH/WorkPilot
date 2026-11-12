/* Background run persists beyond the popup's lifetime; only progress metadata is stored. */
importScripts("automation.js");
const HOST = "com.malenia.browser";
let running = false;

function nativeMessage(payload) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage(HOST, payload, response => {
      const error = chrome.runtime.lastError;
      if (error || !response) reject(new Error("native_host_unavailable"));
      else resolve(response);
    });
  });
}
async function progress(snapshot) {
  // Do not persist URLs, page text, cargo identifiers or browser error strings.
  await chrome.storage.session.set({maleniaAudit: snapshot});
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (!message || message.type !== "start_readonly_audit") return false;
  if (running) { respond({ok: false, error: "already_running"}); return false; }
  let targets;
  try { targets = MaleniaAutomation.normalizeTargets(message.targets); }
  catch { respond({ok: false, error: "invalid_targets"}); return false; }
  running = true;
  respond({ok: true});
  (async () => {
    try {
      const granted = await chrome.permissions.contains({origins: MaleniaAutomation.origins(targets)});
      if (!granted) throw new Error("permissions_missing");
      await progress({phase: "starting", results: []});
      await MaleniaAutomation.run(chrome, targets, nativeMessage, snapshot => progress(snapshot));
    } catch {
      await progress({phase: "needs_attention", results: [], error: "setup_or_connection"});
    } finally {
      running = false;
    }
  })();
  return false;
});
