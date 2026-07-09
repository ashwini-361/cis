// offscreen.js -- runs in the offscreen document, which (unlike the service
// worker) stays alive for the duration of a capture session. Owns: the
// WebSocket connection to the cis server, reconnect/backoff, a bounded
// send-buffer for frames that arrive while disconnected, and the
// tabCapture-based fallback MediaRecorder (used only if no per-participant
// WebRTC audio arrives within background.js's grace period).

const WS_BASE = "ws://localhost:3000";
const MAX_BACKOFF_MS = 30000;
const INITIAL_BACKOFF_MS = 1000;
const MAX_BUFFERED_FRAMES = 200; // bounded; oldest dropped past this, per plan discrepancy #8

let socket = null;
let sessionId = null;
let backoffMs = INITIAL_BACKOFF_MS;
let reconnectTimer = null;
let pendingFrames = []; // [{meta: {...}, buffer: ArrayBuffer|null}]
let fallbackRecorder = null;

function bufferFrame(meta, buffer) {
  pendingFrames.push({ meta, buffer });
  if (pendingFrames.length > MAX_BUFFERED_FRAMES) {
    pendingFrames.shift(); // drop oldest
    console.warn("cis Meet Capturer: send buffer full, dropped oldest frame");
  }
}

function flushPendingFrames() {
  while (pendingFrames.length > 0 && socket?.readyState === WebSocket.OPEN) {
    const { meta, buffer } = pendingFrames.shift();
    socket.send(JSON.stringify(meta));
    if (buffer) socket.send(buffer);
  }
}

function sendOrBuffer(meta, buffer) {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(meta));
    if (buffer) socket.send(buffer);
  } else {
    bufferFrame(meta, buffer);
  }
}

function connect() {
  if (!sessionId) return;
  socket = new WebSocket(`${WS_BASE}/meet/${sessionId}/capture`);

  socket.addEventListener("open", () => {
    backoffMs = INITIAL_BACKOFF_MS;
    flushPendingFrames();
  });

  socket.addEventListener("close", scheduleReconnect);
  socket.addEventListener("error", () => socket.close());
}

function scheduleReconnect() {
  if (!sessionId || reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF_MS);
    connect();
  }, backoffMs);
}

function stopFallbackRecorder() {
  if (fallbackRecorder && fallbackRecorder.state !== "inactive") {
    fallbackRecorder.stop();
  }
  fallbackRecorder = null;
}

async function startFallbackCapture(streamId) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId,
      },
    },
  });
  fallbackRecorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
  let chunkStartSec = performance.now() / 1000;
  fallbackRecorder.ondataavailable = async (event) => {
    if (event.data.size === 0) return;
    const buffer = await event.data.arrayBuffer();
    const nowSec = performance.now() / 1000;
    sendOrBuffer(
      {
        kind: "audio_chunk_meta",
        participant_id: "mixed-tab-audio",
        start_sec: chunkStartSec,
        end_sec: nowSec,
      },
      buffer
    );
    chunkStartSec = nowSec;
  };
  fallbackRecorder.start(5000);
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.target !== "offscreen") return;

  switch (message.kind) {
    case "start-session":
      sessionId = message.sessionId;
      connect();
      break;
    case "stop-session":
      stopFallbackRecorder();
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
      sessionId = null;
      pendingFrames = [];
      break;
    case "control":
      sendOrBuffer({ kind: "control", type: message.type, ts: message.ts, payload: message.payload }, null);
      break;
    case "audio-chunk":
      sendOrBuffer(
        {
          kind: "audio_chunk_meta",
          participant_id: message.participant_id,
          start_sec: message.start_sec,
          end_sec: message.end_sec,
        },
        new Uint8Array(message.buffer).buffer
      );
      break;
    case "start-fallback-capture":
      sessionId = sessionId || message.sessionId;
      startFallbackCapture(message.streamId).catch((err) =>
        console.error("cis Meet Capturer: fallback capture failed", err)
      );
      break;
  }
});
