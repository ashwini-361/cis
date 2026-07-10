"""Session + SessionManager: consolidates per-session state per the Phase 8 plan.

Replaces the scattered `meet_adapters`/`zoom_adapters` dicts that had grown
in app/main.py across Phases 7a/7b with one coherent per-session object
(EventBus, ParticipantStateStore, WeightTable, the active ingest adapter,
connected WebSocket subscribers, and the latest broadcast Verdict).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.bus import EventBus
from app.schema import Verdict, WeightTable
from app.store.evidence import EvidenceStore
from app.store.state import ParticipantStateStore
from app.store.transcript import TranscriptStore

if TYPE_CHECKING:
    from app.ingest.base import IngestAdapter


@dataclass(frozen=True)
class LiveDebugEvent:
    """Bounded diagnostic entry for live-session validation."""

    ts: float
    kind: str
    message: str
    payload: dict[str, object] = field(default_factory=dict)


@dataclass
class LiveDebugState:
    """Mutable session-local counters and recent events for live Meet debugging."""

    extension_connected: bool = False
    extension_connections: int = 0
    control_messages: int = 0
    audio_chunks: int = 0
    transcript_segments: int = 0
    verdict_count: int = 0
    last_control_type: str | None = None
    last_control_payload: dict[str, object] | None = None
    last_audio: dict[str, object] | None = None
    last_transcript: dict[str, object] | None = None
    last_verdict: dict[str, object] | None = None
    recent_events: deque[LiveDebugEvent] = field(
        default_factory=lambda: deque(maxlen=100)
    )

    def add_event(
        self, ts: float, kind: str, message: str, payload: dict[str, object] | None = None
    ) -> None:
        """Append one bounded debug event."""

        self.recent_events.append(
            LiveDebugEvent(ts=ts, kind=kind, message=message, payload=payload or {})
        )

    def snapshot(self, session_id: str) -> dict[str, object]:
        """Serialize the current live-debug view for the API."""

        return {
            "session_id": session_id,
            "extension_connected": self.extension_connected,
            "extension_connections": self.extension_connections,
            "control_messages": self.control_messages,
            "audio_chunks": self.audio_chunks,
            "transcript_segments": self.transcript_segments,
            "verdict_count": self.verdict_count,
            "last_control_type": self.last_control_type,
            "last_control_payload": self.last_control_payload,
            "last_audio": self.last_audio,
            "last_transcript": self.last_transcript,
            "last_verdict": self.last_verdict,
            "recent_events": [
                {
                    "ts": event.ts,
                    "kind": event.kind,
                    "message": event.message,
                    "payload": event.payload,
                }
                for event in self.recent_events
            ],
        }


@dataclass
class Session:
    session_id: str
    bus: EventBus
    state_store: ParticipantStateStore
    weights: WeightTable
    ingest_adapter: IngestAdapter | None = None
    # list[WebSocket]; typed Any here to avoid a hard fastapi import in this module
    subscribers: list[Any] = field(default_factory=list)
    latest_verdict: Verdict | None = None
    # EvidenceStore: Phase 9A additions — the live evidence-production
    # path needs it alongside the state store. Lazy-optional like its
    # neighbors (Redis-backed when ``redis_url`` is provided; in-memory
    # otherwise). Sessions that don't drive a TickScheduler just leave
    # the store empty.
    evidence_store: EvidenceStore = field(default_factory=EvidenceStore)
    transcript_store: TranscriptStore = field(default_factory=TranscriptStore)
    # Background asyncio.Task driving the live run_session loop. Set by
    # POST /sessions/{id}; cancelled by DELETE /sessions/{id}.
    # Typed Any to avoid a hard asyncio.Task[...] import cycle here.
    runner_task: Any = None
    live_debug: LiveDebugState = field(default_factory=LiveDebugState)


class SessionManager:
    """Owns all active sessions plus lightweight live-debug state."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create_session(
        self, session_id: str, weights: WeightTable, redis_url: str | None = None
    ) -> Session:
        """Create and register a new session."""

        session = Session(
            session_id=session_id,
            bus=EventBus(redis_url=redis_url),
            state_store=ParticipantStateStore(redis_url=redis_url),
            weights=weights,
            evidence_store=EvidenceStore(redis_url=redis_url),
            transcript_store=TranscriptStore(redis_url=redis_url),
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Return a session by id, if it exists."""

        return self._sessions.get(session_id)

    def remove_session(self, session_id: str) -> None:
        """Remove a session from the registry."""

        self._sessions.pop(session_id, None)

    def add_subscriber(self, session_id: str, websocket: Any) -> None:
        """Register one verdict-stream subscriber."""

        session = self._sessions.get(session_id)
        if session is not None:
            session.subscribers.append(websocket)

    def remove_subscriber(self, session_id: str, websocket: Any) -> None:
        """Remove one verdict-stream subscriber if still present."""

        session = self._sessions.get(session_id)
        if session is not None and websocket in session.subscribers:
            session.subscribers.remove(websocket)

    def mark_extension_connected(
        self, session_id: str, *, ts: float, message: str
    ) -> None:
        """Record that the Meet extension connected to the ingest socket."""

        session = self._sessions.get(session_id)
        if session is None:
            return
        session.live_debug.extension_connected = True
        session.live_debug.extension_connections += 1
        session.live_debug.add_event(ts, "extension.connected", message)

    def mark_extension_disconnected(
        self, session_id: str, *, ts: float, message: str
    ) -> None:
        """Record that the Meet extension disconnected from the ingest socket."""

        session = self._sessions.get(session_id)
        if session is None:
            return
        session.live_debug.extension_connected = False
        session.live_debug.add_event(ts, "extension.disconnected", message)

    def record_control_message(
        self,
        session_id: str,
        *,
        ts: float,
        control_type: str,
        payload: dict[str, object],
    ) -> None:
        """Increment control counters and remember the latest control payload."""

        session = self._sessions.get(session_id)
        if session is None:
            return
        session.live_debug.control_messages += 1
        session.live_debug.last_control_type = control_type
        session.live_debug.last_control_payload = payload
        session.live_debug.add_event(ts, "control", control_type, payload)

    def record_audio_chunk(
        self,
        session_id: str,
        *,
        ts: float,
        participant_id: str,
        start_sec: float,
        end_sec: float,
        size_bytes: int,
    ) -> None:
        """Increment audio counters and record the latest audio-window metadata."""

        session = self._sessions.get(session_id)
        if session is None:
            return
        snapshot = {
            "participant_id": participant_id,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "size_bytes": size_bytes,
        }
        session.live_debug.audio_chunks += 1
        session.live_debug.last_audio = snapshot
        session.live_debug.add_event(
            ts,
            "audio.chunk",
            f"audio chunk for {participant_id}",
            snapshot,
        )

    def record_transcript_segment(
        self,
        session_id: str,
        *,
        ts: float,
        participant_id: str,
        text: str,
        start_sec: float,
        end_sec: float,
        speaker_name: str | None,
    ) -> None:
        """Increment transcript counters and retain the latest transcript preview."""

        session = self._sessions.get(session_id)
        if session is None:
            return
        preview = text if len(text) <= 120 else f"{text[:117]}..."
        snapshot: dict[str, object] = {
            "participant_id": participant_id,
            "speaker_name": speaker_name,
            "text": preview,
            "start_sec": start_sec,
            "end_sec": end_sec,
        }
        session.live_debug.transcript_segments += 1
        session.live_debug.last_transcript = snapshot
        session.live_debug.add_event(
            ts,
            "transcript.segment",
            f"transcript for {participant_id}",
            snapshot,
        )

    def record_diagnostic(
        self,
        session_id: str,
        *,
        ts: float,
        kind: str,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        """Append one live diagnostic entry from the extension/runtime."""

        session = self._sessions.get(session_id)
        if session is None:
            return
        session.live_debug.add_event(ts, kind, message, payload)

    def get_live_debug_snapshot(
        self, session_id: str
    ) -> dict[str, object] | None:
        """Return the serializable live-debug view for a session."""

        session = self._sessions.get(session_id)
        if session is None:
            return None
        return session.live_debug.snapshot(session_id)

    async def broadcast_verdict(self, session_id: str, verdict: Verdict) -> None:
        """Fan a verdict to every subscriber and update live-debug metadata."""

        session = self._sessions.get(session_id)
        if session is None:
            return
        session.latest_verdict = verdict
        session.live_debug.verdict_count += 1
        session.live_debug.last_verdict = {
            "candidate_id": verdict.candidate_id,
            "candidate_name": verdict.candidate_name,
            "confidence": verdict.confidence,
            "is_decision": verdict.is_decision,
            "ts": verdict.ts,
        }
        session.live_debug.add_event(
            verdict.ts,
            "verdict",
            "verdict broadcast",
            {
                "candidate_id": verdict.candidate_id,
                "confidence": verdict.confidence,
                "is_decision": verdict.is_decision,
            },
        )
        dead: list[Any] = []
        for websocket in session.subscribers:
            try:
                await websocket.send_json(verdict.model_dump(mode="json"))
            except Exception:  # noqa: BLE001 -- a dead/broken client shouldn't stop the broadcast to others
                dead.append(websocket)
        for websocket in dead:
            session.subscribers.remove(websocket)
