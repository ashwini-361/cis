# CHANGELOG.md

## 2026-07-10

### Live Google Meet validation support
- Added `GET /sessions/{session_id}/live-debug` to inspect live Meet ingest health.
- Extended `WS /meet/{session_id}/capture` to accept transcript and diagnostic frames.
- Flushed short pending Meet audio buffers on session end so short validation calls still produce transcript evidence.
- Updated the Meet Chrome extension to:
  - target the running backend at `http://localhost:8000` by default,
  - allow configuring the backend URL from the popup,
  - emit best-effort transcript segments from the Meet DOM,
  - emit diagnostics for selector/capture/runtime troubleshooting.
- Fixed Windows Meet transcription temp-file handling by closing temp `.webm` files before PyAV/faster-whisper re-opens them.
- Fixed fragmented WebM audio: replaced `MediaRecorder.start(timeslice)` with a `stop()`/restart cycle in both `offscreen.js` and `inject.js` so each audio chunk is a complete, self-contained WebM file that PyAV can decode.
  - keep the WebSocket/recorder lifecycle in the offscreen document,
  - stop fallback tab capture once per-track audio arrives,
  - poll/rebind Meet DOM observers to better survive UI churn,
  - prefer stable inferred connection-to-participant mappings over reusing a stale active tile.
