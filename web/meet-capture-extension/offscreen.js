// offscreen.js -- runs in the offscreen document, which (unlike the service
// worker) stays alive for the duration of a capture session. Owns: the
// WebSocket connection to the cis server, reconnect/backoff, a bounded
// send-buffer for frames that arrive while disconnected, and the
// tabCapture-based fallback MediaRecorder (used only if no per-participant
// WebRTC audio arrives within background.js's grace period).
//
// Audio recording strategy: we use MediaRecorder.stop() + immediate restart
// every RECORDING_INTERVAL_MS instead of MediaRecorder.start(timeslice).
// With timeslicing, Chrome emits fragmented WebM blobs — only the first blob
// contains the WebM initialization segment (header + Tracks). Later blobs are
// orphan Cluster elements that PyAV/FFmpeg cannot decode as standalone files,
// and concatenating them produces an invalid container with multiple headers.
// Calling stop() causes MediaRecorder to emit one complete, self-contained
// WebM file per interval, which PyAV decodes correctly every time.

const DEFAULT_SERVER_BASE_URL = "http://localhost:8000";
const MAX_BACKOFF_MS = 30000;
const INITIAL_BACKOFF_MS = 1000;
const MAX_BUFFERED_FRAMES = 200;
const RECORDING_INTERVAL_MS = 25000; // 25s per complete WebM file

let socket = null;
let sessionId = null;
let serverBaseUrl = DEFAULT_SERVER_BASE_URL;
let backoffMs = INITIAL_BACKOFF_MS;
let reconnectTimer = null;
let pendingFrames = [];
let fallbackStream = null;
let fallbackRecorder = null;
let fallbackCycleTimer = null;

function normalizeSocketBase(rawBaseUrl) {
  const trimmed = (rawBaseUrl || DEFAULT_SERVER_BASE_URL).trim();
  if (trimmed.startsWith("ws://") || trimmed.startsWith("wss://")) {
    return trimmed.replace(/\/$/, "");
  }
  if (trimmed.startsWith("https://")) {
    return `wss://${trimmed.slice("https://".length).replace(/\/$/, "")}`;
  }
  if (trimmed.startsWith("http://")) {
    return `ws://${trimmed.slice("http://".length).replace(/\/$/, "")}`;
  }
  return `ws://${trimmed.replace(/\/$/, "")}`;
}

function bufferFrame(meta, buffer) {
  pendingFrames.push({ meta, buffer });
  if (pendingFrames.length > MAX_BUFFERED_FRAMES) {
    pendingFrames.shift();
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

function emitDiagnostic(event, message, payload = {}) {
  sendOrBuffer(
    {
      kind: "diagnostic",
      event,
      message,
      payload,
      ts: performance.now() / 1000,
    },
    null
  );
}

function connect() {
  if (!sessionId) return;
  const socketBase = normalizeSocketBase(serverBaseUrl);
  socket = new WebSocket(`${socketBase}/meet/${sessionId}/capture`);

  socket.addEventListener("open", () => {
    backoffMs = INITIAL_BACKOFF_MS;
    emitDiagnostic("offscreen.websocket_open", "Connected to cis capture ingress", {
      sessionId,
      serverBaseUrl: socketBase,
    });
    flushPendingFrames();
  });

  socket.addEventListener("close", () => {
    emitDiagnostic("offscreen.websocket_close", "Capture socket closed", {
      sessionId,
      serverBaseUrl: socketBase,
    });
    scheduleReconnect();
  });
  socket.addEventListener("error", () => {
    emitDiagnostic("offscreen.websocket_error", "Capture socket errored", {
      sessionId,
      serverBaseUrl: socketBase,
    });
    socket.close();
  });
}

function scheduleReconnect() {
  if (!sessionId || reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF_MS);
    connect();
  }, backoffMs);
}

// ---------------------------------------------------------------------------
// Fallback tab-capture recorder — stop/restart cycle to produce complete WebM
// ---------------------------------------------------------------------------

function _chooseRecorderMimeType() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/ogg",
  ];
  for (const mimeType of candidates) {
    if (MediaRecorder.isTypeSupported(mimeType)) return mimeType;
  }
  return "";
}

function _startOneCycle() {
  if (!fallbackStream || !sessionId) return;

  const mimeType = _chooseRecorderMimeType();
  const opts = mimeType ? { mimeType } : {};
  let recorder;
  try {
    recorder = new MediaRecorder(fallbackStream, opts);
  } catch (err) {
    emitDiagnostic("offscreen.fallback_recorder_error", String(err), { mimeType });
    return;
  }
  fallbackRecorder = recorder;

  const cycleStartSec = performance.now() / 1000;

  recorder.ondataavailable = async (event) => {
    if (event.data.size === 0) return;
    const buffer = await event.data.arrayBuffer();
    const cycleEndSec = performance.now() / 1000;
    emitDiagnostic("offscreen.fallback_chunk_ready", "Complete fallback audio chunk ready", {
      size_bytes: buffer.byteLength,
      duration_sec: cycleEndSec - cycleStartSec,
      mimeType: recorder.mimeType,
    });
    sendOrBuffer(
      {
        kind: "audio_chunk_meta",
        participant_id: "mixed-tab-audio",
        start_sec: cycleStartSec,
        end_sec: cycleEndSec,
      },
      buffer
    );
  };

  recorder.onerror = (event) => {
    emitDiagnostic("offscreen.fallback_recorder_error", String(event.error), { mimeType });
  };

  recorder.start(); // no timeslice — stop() will emit one complete valid file
  emitDiagnostic("offscreen.fallback_cycle_start", "Started recording cycle", {
    mimeType: recorder.mimeType,
    interval_ms: RECORDING_INTERVAL_MS,
  });

  fallbackCycleTimer = setTimeout(() => {
    if (recorder.state === "recording") {
      recorder.stop(); // triggers ondataavailable with complete WebM
    }
    // schedule next cycle after the current one's data event fires (~100ms later)
    setTimeout(() => {
      if (sessionId && fallbackStream) _startOneCycle();
    }, 150);
  }, RECORDING_INTERVAL_MS);
}

function stopFallbackRecorder() {
  if (fallbackCycleTimer) {
    clearTimeout(fallbackCycleTimer);
    fallbackCycleTimer = null;
  }
  if (fallbackRecorder && fallbackRecorder.state !== "inactive") {
    fallbackRecorder.stop();
  }
  fallbackRecorder = null;
  if (fallbackStream) {
    fallbackStream.getTracks().forEach((t) => t.stop());
    fallbackStream = null;
  }
}

async function startFallbackCapture(streamId) {
  stopFallbackRecorder();
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId,
      },
    },
  });
  fallbackStream = stream;
  emitDiagnostic("offscreen.fallback_started", "Started fallback tab audio capture", {
    sessionId,
  });
  _startOneCycle();
}

// ---------------------------------------------------------------------------
// Message handler
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message) => {
  if (message.target !== "offscreen") return;

  switch (message.kind) {
    case "start-session":
      sessionId = message.sessionId;
      serverBaseUrl = message.serverBaseUrl || serverBaseUrl || DEFAULT_SERVER_BASE_URL;
      emitDiagnostic("offscreen.session_start", "Starting capture session", {
        sessionId,
        serverBaseUrl,
      });
      connect();
      break;
    case "stop-session":
      emitDiagnostic("offscreen.session_stop", "Stopping capture session", { sessionId });
      stopFallbackRecorder();
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
      socket = null;
      sessionId = null;
      pendingFrames = [];
      break;
    case "control":
      sendOrBuffer(
        { kind: "control", type: message.type, ts: message.ts, payload: message.payload },
        null
      );
      break;
    case "transcript":
      sendOrBuffer(
        {
          kind: "transcript",
          participant_id: message.participant_id,
          speaker_name: message.speaker_name,
          text: message.text,
          start_sec: message.start_sec,
          end_sec: message.end_sec,
        },
        null
      );
      break;
    case "diagnostic":
      sendOrBuffer(
        {
          kind: "diagnostic",
          event: message.event,
          message: message.message,
          payload: message.payload || {},
          ts: message.ts || performance.now() / 1000,
        },
        null
      );
      break;
    case "audio-chunk":
      // per-track audio from inject.js — already a complete recording chunk
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
      startFallbackCapture(message.streamId).catch((err) => {
        console.error("cis Meet Capturer: fallback capture failed", err);
        emitDiagnostic("offscreen.fallback_error", String(err), { sessionId });
      });
      break;
  }
});
