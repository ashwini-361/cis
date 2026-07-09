// background.js -- MV3 service worker. Orchestration ONLY: it does not hold
// the WebSocket or any MediaRecorder itself, since service workers can be
// killed and restarted by Chrome at any time mid-session, which would
// silently drop a live capture. All persistent capture/WebSocket state
// lives in the offscreen document (offscreen.js), which survives SW
// teardown. See the Phase 7b plan's discrepancy #1 for why.

const OFFSCREEN_URL = "offscreen.html";
const FALLBACK_GRACE_MS = 8000;

let activeTabId = null;
let receivedAnyPerTrackAudio = false;
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
  if (!activeTabId) return;
  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: activeTabId });
  chrome.runtime.sendMessage({
    target: "offscreen",
    kind: "start-fallback-capture",
    sessionId,
    streamId,
  });
}

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message.target === "background") {
    if (message.kind === "control" || message.kind === "audio-chunk") {
      if (message.kind === "audio-chunk") receivedAnyPerTrackAudio = true;
      chrome.runtime.sendMessage({ ...message, target: "offscreen" });
    }
    return;
  }

  if (message.kind === "start-capture") {
    activeTabId = sender.tab?.id ?? message.tabId ?? null;
    receivedAnyPerTrackAudio = false;
    (async () => {
      await ensureOffscreenDocument();
      chrome.runtime.sendMessage({
        target: "offscreen",
        kind: "start-session",
        sessionId: message.sessionId,
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
    chrome.runtime.sendMessage({ target: "offscreen", kind: "stop-session" });
    chrome.offscreen.closeDocument().catch(() => {});
    activeTabId = null;
    return;
  }
});
