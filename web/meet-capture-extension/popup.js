const sessionInput = document.getElementById("session-id");
const statusEl = document.getElementById("status");

chrome.storage.local.get(["sessionId"], ({ sessionId }) => {
  if (sessionId) sessionInput.value = sessionId;
});

document.getElementById("start").addEventListener("click", async () => {
  const sessionId = sessionInput.value.trim();
  if (!sessionId) {
    statusEl.textContent = "Enter a session ID first.";
    return;
  }
  await chrome.storage.local.set({ sessionId });
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  chrome.runtime.sendMessage({ kind: "start-capture", sessionId, tabId: tab?.id });
  statusEl.textContent = `Capturing session ${sessionId}...`;
});

document.getElementById("stop").addEventListener("click", () => {
  chrome.runtime.sendMessage({ kind: "stop-capture" });
  statusEl.textContent = "Stopped.";
});
