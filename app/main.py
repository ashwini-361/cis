"""FastAPI entrypoint."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import Literal, cast

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
from app.schema import (
    Event,
    EventType,
    ParticipantRoleInfo,
    RoleSnapshotResponse,
    SessionEnvelope,
    TranscriptListResponse,
    TranscriptSegmentResponse,
    Verdict,
)
from app.session import SessionManager

logger = logging.getLogger(__name__)

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="cis")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
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
    candidate_name: str | None = None
    candidate_email: str | None = None
    interviewer_names: list[str] = []
    # LLM provider: real when llm_base_url or LLM_BASE_URL env var is set;
    # falls back to ScriptedLLMProvider (offline/deterministic) otherwise.
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    redis_url: str | None = None


def _make_llm_provider(body: _SessionStartBody) -> LLMProvider:
    base_url = body.llm_base_url or os.environ.get("LLM_BASE_URL")
    if base_url:
        api_key = body.llm_api_key or os.environ.get("LLM_API_KEY") or ""
        model = body.llm_model or os.environ.get("LLM_MODEL") or "gpt-4o-mini"
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
        model_size=os.environ.get("WHISPER_MODEL", "large-v3-turbo"),
        device=os.environ.get("WHISPER_DEVICE", "auto"),
        compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "default"),
    )
    return ZoomAdapter(api_client=api_client, transcriber=transcriber)


def _make_meet_adapter() -> MeetAdapter:
    transcriber = FasterWhisperTranscriber(
        model_size=os.environ.get("WHISPER_MODEL", "large-v3-turbo"),
        device=os.environ.get("WHISPER_DEVICE", "auto"),
        compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "default"),
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
        candidate_name=body.candidate_name,
        candidate_email=body.candidate_email,
        interviewer_names=body.interviewer_names,
    )

    if isinstance(adapter, MeetAdapter):
        adapter.prime_session(envelope)

    async def _broadcast(verdict: Verdict) -> None:
        await session_manager.broadcast_verdict(session_id, verdict)

    async def _record_runtime_event(event: Event) -> None:
        if event.type != EventType.TRANSCRIPT_SEGMENT:
            return
        if not event.envelope.source.endswith(".whisper"):
            return
        participant_id = str(event.payload["participant_id"])
        speaker_name: str | None = event.payload.get("speaker_name")
        if not speaker_name:
            session_obj = session_manager.get_session(session_id)
            if session_obj and session_obj.state_store:
                state = session_obj.state_store.get(session_id, participant_id)
                if state and state.display_name:
                    speaker_name = state.display_name
        session_manager.record_transcript_segment(
            session_id,
            ts=event.envelope.ts,
            participant_id=participant_id,
            text=str(event.payload["text"]),
            start_sec=float(event.payload["start_sec"]),
            end_sec=float(event.payload["end_sec"]),
            speaker_name=speaker_name,
            source="whisper",
        )

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
            transcript_store=session.transcript_store,
            broadcast=_broadcast,
            event_callback=_record_runtime_event,
        )
    )
    session.runner_task = task
    return JSONResponse({"session_id": session_id, "status": "started"})


@app.get("/sessions")
async def list_sessions_endpoint() -> JSONResponse:
    """List all active sessions."""
    return JSONResponse({"sessions": session_manager.list_sessions()})


@app.get("/sessions/{session_id}/live-debug")
async def session_live_debug_endpoint(session_id: str) -> JSONResponse:
    """Return counters and recent events for live Meet validation."""

    snapshot = session_manager.get_live_debug_snapshot(session_id)
    if snapshot is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    return JSONResponse(snapshot)


@app.get("/sessions/{session_id}/transcript")
async def get_session_transcript_endpoint(session_id: str) -> JSONResponse:
    """Return ordered transcript segments for the session."""
    session = session_manager.get_session(session_id)
    if session is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    stored_segments = session.transcript_store.get_full_transcript(session_id)
    response = TranscriptListResponse(
        session_id=session_id,
        segments=[
            TranscriptSegmentResponse(
                segment_id=seg.segment_id,
                session_id=seg.session_id,
                participant_id=seg.participant_id,
                speaker_name=seg.speaker_name,
                text=seg.text,
                start_sec=seg.start_sec,
                end_sec=seg.end_sec,
                source=seg.source,
                arrival_sequence=seg.arrival_sequence,
            )
            for seg in stored_segments
        ],
    )
    return JSONResponse(response.model_dump())


@app.get("/sessions/{session_id}/roles")
async def get_session_roles_endpoint(session_id: str) -> JSONResponse:
    """Return current participant roles and confidence."""
    session = session_manager.get_session(session_id)
    if session is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    participants = await session.state_store.get_all(session_id)
    response = RoleSnapshotResponse(
        session_id=session_id,
        participants=[
            ParticipantRoleInfo(
                participant_id=p.participant_id,
                display_name=p.display_name,
                role=p.role,
                confidence=p.confidence,
            )
            for p in participants
        ],
    )
    return JSONResponse(response.model_dump())


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

    session_manager.mark_extension_connected(
        session_id,
        ts=0.0,
        message="Meet extension connected to capture ingress",
    )

    pending_audio_meta: dict[str, object] | None = None
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            if (text := message.get("text")) is not None:
                data = json.loads(text)
                if data.get("kind") == "control":
                    payload = data["payload"]
                    session_manager.record_control_message(
                        session_id,
                        ts=float(data["ts"]),
                        control_type=str(data["type"]),
                        payload=payload,
                    )
                    await adapter.push_control_message(
                        {"type": data["type"], "ts": data["ts"], "payload": payload}
                    )
                elif data.get("kind") == "audio_chunk_meta":
                    pending_audio_meta = data
                elif data.get("kind") == "transcript":
                    session_manager.record_transcript_segment(
                        session_id,
                        ts=float(data["start_sec"]),
                        participant_id=str(data["participant_id"]),
                        text=str(data["text"]),
                        start_sec=float(data["start_sec"]),
                        end_sec=float(data["end_sec"]),
                        speaker_name=(
                            str(data["speaker_name"])
                            if data.get("speaker_name")
                            else None
                        ),
                        source="extension",
                    )
                    await adapter.push_transcript_segment(
                        {
                            "participant_id": data["participant_id"],
                            "speaker_name": data.get("speaker_name"),
                            "text": data["text"],
                            "start_sec": data["start_sec"],
                            "end_sec": data["end_sec"],
                        }
                    )
                elif data.get("kind") == "diagnostic":
                    session_manager.record_diagnostic(
                        session_id,
                        ts=float(data.get("ts", 0.0)),
                        kind=str(data.get("event", "diagnostic")),
                        message=str(data.get("message", "")),
                        payload=data.get("payload"),
                    )
            elif (raw_bytes := message.get("bytes")) is not None and pending_audio_meta is not None:
                participant_id = str(pending_audio_meta["participant_id"])
                start_sec = float(
                    cast(str | float | int, pending_audio_meta["start_sec"])
                )
                end_sec = float(
                    cast(str | float | int, pending_audio_meta["end_sec"])
                )
                session_manager.record_audio_chunk(
                    session_id,
                    ts=end_sec,
                    participant_id=participant_id,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    size_bytes=len(raw_bytes),
                )
                await adapter.push_audio_chunk(
                    participant_id=participant_id,
                    audio_bytes=raw_bytes,
                    start_sec=start_sec,
                    end_sec=end_sec,
                )
                pending_audio_meta = None
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("meet capture websocket failed for session %s", session_id)
    finally:
        session_manager.mark_extension_disconnected(
            session_id,
            ts=0.0,
            message="Meet extension disconnected from capture ingress",
        )


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
