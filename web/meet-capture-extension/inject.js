// inject.js -- runs in the page's MAIN world (per manifest.json), NOT the
// isolated content-script world, so it can see and patch the page's own
// `RTCPeerConnection` constructor. This is the mechanism
// docs/PLATFORM_INTEGRATION.md §3.4 specifies: "the extension exposes the
// per-participant MediaStreamTrack directly via RTCPeerConnection.ontrack
// inspection (Meet uses WebRTC internally)".
//
// Per-track attribution is best-effort: Meet does not publish a stable,
// documented mapping from an RTCPeerConnection/track to a specific
// participant tile. We tag each captured track with a locally generated
// connection id (`pc-<n>`); content-script.js is responsible for
// correlating that id to a participant_id via DOM observation (e.g. active-
// speaker highlighting) since only it has access to the tile DOM. This
// correlation is inherently fragile against Meet UI changes and should be
// re-verified against a live call before relying on it.
(() => {
  const NativeRTCPeerConnection = window.RTCPeerConnection;
  if (!NativeRTCPeerConnection) return;

  let connectionCounter = 0;
  const CHUNK_TIMESLICE_MS = 5000;

  function startRecordingTrack(track, connectionId) {
    const stream = new MediaStream([track]);
    let recorder;
    try {
      recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
    } catch (err) {
      window.postMessage(
        { source: "cis-inject", kind: "track-error", connectionId, message: String(err) },
        "*"
      );
      return;
    }

    let chunkStartSec = performance.now() / 1000;
    recorder.ondataavailable = async (event) => {
      if (event.data.size === 0) return;
      const buffer = await event.data.arrayBuffer();
      const nowSec = performance.now() / 1000;
      window.postMessage(
        {
          source: "cis-inject",
          kind: "audio-chunk",
          connectionId,
          startSec: chunkStartSec,
          endSec: nowSec,
          buffer,
        },
        "*",
        [buffer]
      );
      chunkStartSec = nowSec;
    };
    recorder.start(CHUNK_TIMESLICE_MS);

    track.addEventListener("ended", () => {
      if (recorder.state !== "inactive") recorder.stop();
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
