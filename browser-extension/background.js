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
      await MaleniaAutomation.run(chrome,targets,message=>session.send(message),progress);
    } catch {
      await progress({phase:"needs_attention",results:[],error:"setup_or_connection"});
    } finally {
      session?.close();
      running=false;
    }
  })();
  return false;
});
