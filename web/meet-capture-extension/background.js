const OFFSCREEN_URL = "offscreen.html";
const FALLBACK_GRACE_MS = 8000;

let activeTabId = null;
let currentSessionId = null;
let receivedAnyPerTrackAudio = false;
let fallbackStarted = false;
let fallbackTimer = null;

async function ensureOffscreenDocument() {
  const existing = await chrome.runtime.getContexts?.({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
  });
  if (existing && existing.length > 0) return;
  await chrome.offscreen.createDocument({
    url: OFFSCREEN_URL,
    reasons: ["USER_MEDIA"],
    justification: "Capture and stream Meet participant audio to the cis server over WebSocket.",
  });
}

async function startFallbackTabCapture(sessionId) {
  if (!activeTabId || fallbackStarted) return;
  fallbackStarted = true;
  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: activeTabId });
  chrome.runtime.sendMessage({
    target: "offscreen",
    kind: "start-fallback-capture",
    sessionId,
    streamId,
  });
}

function stopFallbackCapture() {
  if (!fallbackStarted) return;
  fallbackStarted = false;
  chrome.runtime.sendMessage({ target: "offscreen", kind: "stop-fallback-capture" });
}

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message.target === "background") {
    if (
      message.kind === "control" ||
      message.kind === "audio-chunk" ||
      message.kind === "transcript" ||
      message.kind === "diagnostic"
    ) {
      if (message.kind === "audio-chunk") {
        const wasReceivingPerTrackAudio = receivedAnyPerTrackAudio;
        receivedAnyPerTrackAudio = true;
        if (!wasReceivingPerTrackAudio) {
          stopFallbackCapture();
        }
      }
      chrome.runtime.sendMessage({ ...message, target: "offscreen" });
    }
    return;
  }

  if (message.kind === "start-capture") {
    activeTabId = sender.tab?.id ?? message.tabId ?? null;
    currentSessionId = message.sessionId;
    receivedAnyPerTrackAudio = false;
    fallbackStarted = false;
    if (fallbackTimer) clearTimeout(fallbackTimer);
    (async () => {
      await ensureOffscreenDocument();
      chrome.runtime.sendMessage({
        target: "offscreen",
        kind: "start-session",
        sessionId: message.sessionId,
        serverBaseUrl: message.serverBaseUrl,
      });
      fallbackTimer = setTimeout(() => {
        if (!receivedAnyPerTrackAudio) {
          startFallbackTabCapture(message.sessionId);
        }
      }, FALLBACK_GRACE_MS);
    })();
    return;
  }

  if (message.kind === "stop-capture") {
    if (fallbackTimer) clearTimeout(fallbackTimer);
    stopFallbackCapture();
    chrome.runtime.sendMessage({ target: "offscreen", kind: "stop-session" });
    chrome.offscreen.closeDocument().catch(() => {});
    activeTabId = null;
    currentSessionId = null;
    return;
  }
});
