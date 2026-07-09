"""FastAPI entrypoint — session bootstrap and CLI (--scenario) land in later phases."""
from __future__ import annotations

import json
import os

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.ingest.meet import MeetAdapter
from app.ingest.zoom import ZoomAdapter, handle_url_validation, verify_webhook_signature
from app.session import SessionManager

app = FastAPI(title="cis")

# Consolidated per-session state (Phase 8) -- replaces the separate
# meet_adapters/zoom_adapters dicts from Phases 7a/7b. Populated by whoever
# starts a session (out of scope here); tests populate it directly via
# session_manager.create_session(...) + setting .ingest_adapter.
session_manager = SessionManager()


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
    session = session_manager.get_session(session_id)
    adapter = session.ingest_adapter if session is not None else None
    await websocket.accept()
    if not isinstance(adapter, MeetAdapter):
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
    session = session_manager.get_session(meeting_id)
    adapter = session.ingest_adapter if session is not None else None
    if isinstance(adapter, ZoomAdapter):
        await adapter.push_webhook_event(payload)

    return JSONResponse({"status": "ok"})


@app.websocket("/sessions/{session_id}/stream")
async def session_stream(websocket: WebSocket, session_id: str) -> None:
    """Outbound verdict stream for the dashboard, per docs/ARCHITECTURE.md §1.8.

    Verdicts arrive via SessionManager.broadcast_verdict (called by the
    realtime ticker each tick) -- this route never reads anything meaningful
    from the client, it just holds the connection open and pushes.
    """
    await websocket.accept()
    session = session_manager.get_session(session_id)
    if session is None:
        await websocket.close(code=4404, reason="unknown session_id")
        return

    if session.latest_verdict is not None:
        await websocket.send_json(session.latest_verdict.model_dump(mode="json"))
    session_manager.add_subscriber(session_id, websocket)

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        session_manager.remove_subscriber(session_id, websocket)
