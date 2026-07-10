const sessionInput = document.getElementById("session-id");
const serverBaseUrlInput = document.getElementById("server-base-url");
const statusEl = document.getElementById("status");

chrome.storage.local.get(["sessionId", "serverBaseUrl"], ({ sessionId, serverBaseUrl }) => {
  if (sessionId) sessionInput.value = sessionId;
  serverBaseUrlInput.value = serverBaseUrl || "http://localhost:8000";
});

document.getElementById("start").addEventListener("click", async () => {
  const sessionId = sessionInput.value.trim();
  const serverBaseUrl = serverBaseUrlInput.value.trim() || "http://localhost:8000";
  if (!sessionId) {
    statusEl.textContent = "Enter a session ID first.";
    return;
  }
  await chrome.storage.local.set({ sessionId, serverBaseUrl });
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  chrome.runtime.sendMessage({
    kind: "start-capture",
    sessionId,
    serverBaseUrl,
    tabId: tab?.id,
  });
  statusEl.textContent = `Capturing ${sessionId} to ${serverBaseUrl}`;
});

document.getElementById("stop").addEventListener("click", () => {
  chrome.runtime.sendMessage({ kind: "stop-capture" });
  statusEl.textContent = "Stopped.";
});
