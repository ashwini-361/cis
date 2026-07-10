"""FastAPI entrypoint."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Literal

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.analyzers.transcript_role import LLMProvider, OpenAICompatibleProvider
from app.api import routes
from app.api.websocket import make_router
from app.config import load_weights
from app.harness.scripted_llm import ScriptedLLMProvider
from app.ingest.meet import FasterWhisperTranscriber, MeetAdapter
from app.ingest.zoom import (
    KeyringTokenStore,
    ZoomAdapter,
    ZoomAPIClient,
    ZoomAuth,
    handle_url_validation,
    verify_webhook_signature,
)
from app.runtime.clock import RealClock
from app.runtime.registry import AnalyzerRegistry
from app.runtime.session_runner import run_session
from app.schema import SessionEnvelope, Verdict
from app.session import SessionManager

app = FastAPI(title="cis")
session_manager = SessionManager()

app.include_router(routes.router)
app.include_router(make_router(session_manager))


# ---------------------------------------------------------------------------
# Session lifecycle — POST to start, DELETE to stop
# ---------------------------------------------------------------------------


class _SessionStartBody(BaseModel):
    platform: Literal["zoom", "meet"]
    expected_participants: list[str] = []
    ground_truth_candidate_id: str | None = None
    # LLM provider: real when llm_base_url or LLM_BASE_URL env var is set;
    # falls back to ScriptedLLMProvider (offline/deterministic) otherwise.
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    redis_url: str | None = None


def _make_llm_provider(body: _SessionStartBody) -> LLMProvider:
    base_url = body.llm_base_url or os.environ.get("LLM_BASE_URL")
    if base_url:
        api_key = body.llm_api_key or os.environ.get("LLM_API_KEY", "")
        model = body.llm_model or os.environ.get("LLM_MODEL", "gpt-4o-mini")
        return OpenAICompatibleProvider(base_url=base_url, api_key=api_key, model=model)
    return ScriptedLLMProvider()


def _make_zoom_adapter() -> ZoomAdapter:
    import httpx

    http_client = httpx.AsyncClient()
    auth = ZoomAuth(
        client_id=os.environ.get("ZOOM_CLIENT_ID", ""),
        client_secret=os.environ.get("ZOOM_CLIENT_SECRET", ""),
        account_id=os.environ.get("ZOOM_ACCOUNT_ID", ""),
        token_store=KeyringTokenStore(),
        http_client=http_client,
    )
    api_client = ZoomAPIClient(auth=auth, http_client=http_client)
    transcriber = FasterWhisperTranscriber(
        model_size=os.environ.get("WHISPER_MODEL", "large-v3-turbo")
    )
    return ZoomAdapter(api_client=api_client, transcriber=transcriber)


def _make_meet_adapter() -> MeetAdapter:
    transcriber = FasterWhisperTranscriber(
        model_size=os.environ.get("WHISPER_MODEL", "large-v3-turbo")
    )
    return MeetAdapter(transcriber=transcriber)


@app.post("/sessions/{session_id}")
async def start_session_endpoint(
    session_id: str, body: _SessionStartBody
) -> JSONResponse:
    """Create and start a live session.

    Constructs the full pipeline (adapter → registry → evidence store →
    TickScheduler → run_session) and runs it as a background task that
    fans verdicts into the WebSocket stream at ``/sessions/{id}/stream``.
    """
    if session_manager.get_session(session_id) is not None:
        return JSONResponse({"error": "session already exists"}, status_code=409)

    weights = load_weights()
    redis_url = body.redis_url or os.environ.get("REDIS_URL")
    session = session_manager.create_session(session_id, weights, redis_url=redis_url)

    llm = _make_llm_provider(body)
    analyzers = AnalyzerRegistry(weights).build(llm)

    adapter = _make_zoom_adapter() if body.platform == "zoom" else _make_meet_adapter()
    session.ingest_adapter = adapter

    envelope = SessionEnvelope(
        session_id=session_id,
        platform=body.platform,
        start_wall_clock=datetime.now(UTC).isoformat(),
        expected_participants=body.expected_participants,
        ground_truth_candidate_id=body.ground_truth_candidate_id,
    )

    async def _broadcast(verdict: Verdict) -> None:
        await session_manager.broadcast_verdict(session_id, verdict)

    task: asyncio.Task[list[Verdict]] = asyncio.create_task(
        run_session(
            adapter=adapter,
            session_envelope=envelope,
            platform=body.platform,
            analyzers=analyzers,
            weights=weights,
            clock=RealClock(),
            evidence_store=session.evidence_store,
            state_store=session.state_store,
            broadcast=_broadcast,
        )
    )
    session.runner_task = task
    return JSONResponse({"session_id": session_id, "status": "started"})


@app.delete("/sessions/{session_id}")
async def stop_session_endpoint(session_id: str) -> JSONResponse:
    """Cancel and remove a live session."""
    session = session_manager.get_session(session_id)
    if session is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    task = session.runner_task
    if task is not None and not task.done():
        task.cancel()
    session_manager.remove_session(session_id)
    return JSONResponse({"session_id": session_id, "status": "stopped"})


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


