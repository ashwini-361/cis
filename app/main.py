"""FastAPI entrypoint — session bootstrap and CLI (--scenario) land in later phases."""
from __future__ import annotations

import json
import os

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.ingest.meet import MeetAdapter
from app.ingest.zoom import ZoomAdapter, handle_url_validation, verify_webhook_signature

app = FastAPI(title="cis")

# Minimal in-memory registries. Intentionally simple -- a real session
# manager is Phase 8's fuller bootstrap concern. Populated by whoever starts
# a session (out of scope here); tests populate them directly.
meet_adapters: dict[str, MeetAdapter] = {}
zoom_adapters: dict[str, ZoomAdapter] = {}  # keyed by Zoom meeting_id


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


@app.post("/zoom/webhook")
async def zoom_webhook(request: Request) -> JSONResponse:
    """Receives signed Zoom webhook events per docs/PLATFORM_INTEGRATION.md §2.2.

    Zoom's `endpoint.url_validation` handshake (sent once, during webhook
    setup) predates any secret being exchanged in-band and is answered
    without signature verification, per Zoom's own documented flow.
    """
    raw_body = await request.body()
    payload = json.loads(raw_body)

    if payload.get("event") == "endpoint.url_validation":
        secret_token = os.environ.get("ZOOM_WEBHOOK_SECRET_TOKEN", "")
        plain_token = payload["payload"]["plainToken"]
        return JSONResponse(handle_url_validation(plain_token, secret_token))

    secret_token = os.environ.get("ZOOM_WEBHOOK_SECRET_TOKEN", "")
    signature = request.headers.get("x-zm-signature", "")
    timestamp = request.headers.get("x-zm-request-timestamp", "")
    if not verify_webhook_signature(secret_token, timestamp, raw_body, signature):
        return JSONResponse({"error": "invalid signature"}, status_code=401)

    meeting_id = str(payload.get("payload", {}).get("object", {}).get("id", ""))
    adapter = zoom_adapters.get(meeting_id)
    if adapter is not None:
        await adapter.push_webhook_event(payload)

    return JSONResponse({"status": "ok"})
