// inject.js -- runs in the page's MAIN world (per manifest.json), NOT the
// isolated content-script world, so it can see and patch the page's own
// `RTCPeerConnection` constructor. This is the mechanism
// docs/PLATFORM_INTEGRATION.md §3.4 specifies: "the extension exposes the
// per-participant MediaStreamTrack directly via RTCPeerConnection.ontrack
// inspection (Meet uses WebRTC internally)".
//
// Audio recording strategy: we use MediaRecorder.stop() + immediate restart
// every RECORDING_INTERVAL_MS instead of MediaRecorder.start(timeslice).
// With timeslicing, Chrome emits fragmented WebM blobs where only the first
// blob contains the WebM initialization segment. Later blobs are orphan Cluster
// elements that PyAV/FFmpeg cannot decode as standalone files. Calling stop()
// causes MediaRecorder to emit one complete, self-contained WebM file per
// interval, which faster-whisper decodes correctly every time.
(() => {
  const NativeRTCPeerConnection = window.RTCPeerConnection;
  if (!NativeRTCPeerConnection) return;

  let connectionCounter = 0;
  const RECORDING_INTERVAL_MS = 25000; // 25s per complete WebM file

  function chooseMimeType() {
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

  function startOneCycle(stream, connectionId, onDone) {
    const mimeType = chooseMimeType();
    const opts = mimeType ? { mimeType } : {};
    let recorder;
    try {
      recorder = new MediaRecorder(stream, opts);
    } catch (err) {
      window.postMessage(
        { source: "cis-inject", kind: "track-error", connectionId, message: String(err) },
        "*"
      );
      return null;
    }

    const cycleStartSec = performance.now() / 1000;

    recorder.ondataavailable = async (event) => {
      if (event.data.size === 0) return;
      const buffer = await event.data.arrayBuffer();
      const cycleEndSec = performance.now() / 1000;
      window.postMessage(
        {
          source: "cis-inject",
          kind: "audio-chunk",
          connectionId,
          startSec: cycleStartSec,
          endSec: cycleEndSec,
          buffer,
        },
        "*",
        [buffer]
      );
      if (typeof onDone === "function") onDone();
    };

    recorder.onerror = () => {
      if (typeof onDone === "function") onDone();
    };

    recorder.start(); // no timeslice
    return recorder;
  }

  function startRecordingTrack(track, connectionId) {
    const stream = new MediaStream([track]);
    let activeRecorder = null;
    let cycleTimer = null;
    let stopped = false;

    function scheduleCycle() {
      if (stopped) return;
      activeRecorder = startOneCycle(stream, connectionId, () => {
        activeRecorder = null;
        if (!stopped) {
          setTimeout(scheduleCycle, 50);
        }
      });
      if (activeRecorder) {
        cycleTimer = setTimeout(() => {
          if (activeRecorder && activeRecorder.state === "recording") {
            activeRecorder.stop(); // triggers ondataavailable with complete file
          }
        }, RECORDING_INTERVAL_MS);
      }
    }

    scheduleCycle();

    track.addEventListener("ended", () => {
      stopped = true;
      if (cycleTimer) clearTimeout(cycleTimer);
      if (activeRecorder && activeRecorder.state !== "inactive") {
        activeRecorder.stop();
      }
    });
  }

  class PatchedRTCPeerConnection extends NativeRTCPeerConnection {
    constructor(...args) {
      super(...args);
      const connectionId = `pc-${connectionCounter++}`;
      window.postMessage({ source: "cis-inject", kind: "connection-created", connectionId }, "*");

      this.addEventListener("track", (event) => {
        if (event.track.kind !== "audio") return;
        window.postMessage(
          { source: "cis-inject", kind: "track-added", connectionId, trackId: event.track.id },
          "*"
        );
        startRecordingTrack(event.track, connectionId);
      });
    }
  }

  window.RTCPeerConnection = PatchedRTCPeerConnection;
})();
