const HOST_NAME = "com.workpilot.browser";
const statusNode = document.getElementById("status");
const shareButton = document.getElementById("share");

function setStatus(message, kind = "") {
  statusNode.textContent = message;
  statusNode.className = "status" + (kind ? " " + kind : "");
}

function sendNativeMessage(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage(HOST_NAME, message, (response) => {
      const error = chrome.runtime.lastError;
      if (error) {
        reject(new Error(error.message));
        return;
      }
      if (!response || typeof response !== "object") {
        reject(new Error("Native host вернул пустой ответ."));
        return;
      }
      resolve(response);
    });
  });
}

async function connect() {
  try {
    const response = await sendNativeMessage({ type: "hello" });
    if (!response.ok || response.host !== HOST_NAME) {
      throw new Error(response.error || "Не удалось проверить Native Messaging host.");
    }
    setStatus("Malenia подключён. Выберите вкладку для передачи.", "ok");
    shareButton.disabled = false;
  } catch (error) {
    setStatus("Нет соединения с Malenia. Проверьте установку Native Messaging host.", "error");
    shareButton.disabled = true;
  }
}

shareButton.addEventListener("click", async () => {
  shareButton.disabled = true;
  setStatus("Передаём только активную вкладку…");
  try {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (!tab || typeof tab.url !== "string") {
      throw new Error("Не удалось получить адрес активной вкладки.");
    }

    const page = new URL(tab.url);
    if (page.protocol !== "http:" && page.protocol !== "https:") {
      throw new Error("Можно передавать только обычные HTTP(S)-страницы.");
    }

    // Do not send query parameters or fragments: they may contain private tokens.
    const safeUrl = page.origin + page.pathname;
    const response = await sendNativeMessage({
      type: "share_active_tab",
      request_id: crypto.randomUUID(),
      tab: {
        title: typeof tab.title === "string" ? tab.title.slice(0, 300) : "",
        url: safeUrl
      }
    });

    if (!response.ok) {
      throw new Error(response.error || "Malenia не принял вкладку.");
    }
    setStatus("Вкладка передана в Malenia.", "ok");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Не удалось передать вкладку.", "error");
  } finally {
    shareButton.disabled = false;
  }
});

void connect();
