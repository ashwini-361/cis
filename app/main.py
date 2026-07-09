"""FastAPI entrypoint — session bootstrap and CLI (--scenario) land in later phases."""
from __future__ import annotations

import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.ingest.meet import MeetAdapter

app = FastAPI(title="cis")

# Minimal in-memory registry mapping session_id -> MeetAdapter. Intentionally
# simple -- a real session manager is Phase 8's fuller bootstrap concern.
# Populated by whoever starts a Meet session (out of scope here); tests
# populate it directly.
meet_adapters: dict[str, MeetAdapter] = {}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.websocket("/meet/{session_id}/capture")
async def meet_capture(websocket: WebSocket, session_id: str) -> None:
    """Ingress for the Chrome extension's captured control events and audio.

    Wire protocol (per the Phase 7b plan): control/metadata arrive as JSON
    text frames; each audio chunk is a JSON `audio_chunk_meta` text frame
    immediately followed by one binary frame carrying the raw audio bytes.
    """
    adapter = meet_adapters.get(session_id)
    await websocket.accept()
    if adapter is None:
        await websocket.close(code=4404, reason="unknown session_id")
        return

    pending_audio_meta: dict[str, object] | None = None
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            if (text := message.get("text")) is not None:
                data = json.loads(text)
                if data.get("kind") == "control":
                    await adapter.push_control_message(
                        {"type": data["type"], "ts": data["ts"], "payload": data["payload"]}
                    )
                elif data.get("kind") == "audio_chunk_meta":
                    pending_audio_meta = data
            elif (raw_bytes := message.get("bytes")) is not None and pending_audio_meta is not None:
                await adapter.push_audio_chunk(
                    participant_id=pending_audio_meta["participant_id"],  # type: ignore[arg-type]
                    audio_bytes=raw_bytes,
                    start_sec=pending_audio_meta["start_sec"],  # type: ignore[arg-type]
                    end_sec=pending_audio_meta["end_sec"],  # type: ignore[arg-type]
                )
                pending_audio_meta = None
    except WebSocketDisconnect:
        pass
