"""Session + SessionManager: consolidates per-session state per the Phase 8 plan.

Replaces the scattered `meet_adapters`/`zoom_adapters` dicts that had grown
in app/main.py across Phases 7a/7b with one coherent per-session object
(EventBus, ParticipantStateStore, WeightTable, the active ingest adapter,
connected WebSocket subscribers, and the latest broadcast Verdict).
"""

from __future__ import annotations

import asyncio
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
    fallback_only_mode: bool = False
    caption_transcript_active: bool = False
    last_transcript_ts: float = 0.0
    last_audio_ts: float = 0.0
    unmapped_audio_participants: set[str] = field(default_factory=set)
    mapped_audio_participants: set[str] = field(default_factory=set)
    recent_events: deque[LiveDebugEvent] = field(
        default_factory=lambda: deque(maxlen=100)
    )

    @property
    def transcribing_lag(self) -> bool:
        if self.last_audio_ts == 0.0:
            return False
        return (self.last_audio_ts - self.last_transcript_ts) > 10.0

    @property
    def audio_mapping_coverage(self) -> float:
        if self.mapped_audio_participants:
            return 1.0
        if self.unmapped_audio_participants:
            return 0.0
        return 1.0

    @property
    def transcript_source_active(self) -> bool:
        if self.caption_transcript_active:
            return True
        if self.last_transcript is not None:
            return True
        if self.last_audio_ts == 0.0:
            return False
        return not self.transcribing_lag

    def add_event(
        self, ts: float, kind: str, message: str, payload: dict[str, object] | None = None
    ) -> None:
        """Append one bounded debug event."""

        self.recent_events.append(
            LiveDebugEvent(ts=ts, kind=kind, message=message, payload=payload or {})
        )

    def snapshot(self) -> dict[str, object]:
        """Serialize the current live-debug view for the API."""

        # Transcript coverage info
        transcript_coverage = {
            "total_segments": self.transcript_segments,
            "caption_active": self.caption_transcript_active,
            "transcribing_lag": self.transcribing_lag,
        }

        return {
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
            "fallback_only_mode": self.fallback_only_mode,
            "transcript_source_active": self.transcript_source_active,
            "audio_mapping_coverage": self.audio_mapping_coverage,
            "transcribing_lag": self.transcribing_lag,
            "per_participant_mode": len(self.mapped_audio_participants) > 0,
            "transcript_coverage": transcript_coverage,
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

    def list_sessions(self) -> list[dict[str, object]]:
        """Return summary info for all active sessions."""
        result: list[dict[str, object]] = []
        for sid, sess in self._sessions.items():
            result.append({
                "session_id": sid,
                "verdict_count": sess.live_debug.verdict_count,
                "latest_candidate_id": sess.latest_verdict.candidate_id if sess.latest_verdict else None,
                "latest_candidate_name": sess.latest_verdict.candidate_name if sess.latest_verdict else None,
                "latest_confidence": sess.latest_verdict.confidence if sess.latest_verdict else None,
            })
        return result

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

    def _stream_payload(self, session_id: str) -> dict[str, object] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return {
            "kind": "session_update",
            "session_id": session_id,
            "verdict": (
                session.latest_verdict.model_dump(mode="json")
                if session.latest_verdict is not None
                else None
            ),
            "live_debug": self.get_live_debug_snapshot(session_id),
        }

    async def _broadcast_stream_payload(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        payload = self._stream_payload(session_id)
        if session is None or payload is None:
            return
        dead: list[Any] = []
        for websocket in session.subscribers:
            try:
                await websocket.send_json(payload)
            except Exception:  # noqa: BLE001
                dead.append(websocket)
        for websocket in dead:
            session.subscribers.remove(websocket)

    def _schedule_stream_update(self, session_id: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._broadcast_stream_payload(session_id))

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
        self._schedule_stream_update(session_id)

    def mark_extension_disconnected(
        self, session_id: str, *, ts: float, message: str
    ) -> None:
        """Record that the Meet extension disconnected from the ingest socket."""

        session = self._sessions.get(session_id)
        if session is None:
            return
        session.live_debug.extension_connected = False
        session.live_debug.add_event(ts, "extension.disconnected", message)
        self._schedule_stream_update(session_id)

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
        self._schedule_stream_update(session_id)

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
        session.live_debug.last_audio_ts = ts

        if participant_id == "mixed-tab-audio":
            session.live_debug.unmapped_audio_participants.add(participant_id)
            if not session.live_debug.mapped_audio_participants:
                session.live_debug.fallback_only_mode = True
        else:
            session.live_debug.mapped_audio_participants.add(participant_id)
            session.live_debug.fallback_only_mode = False
        session.live_debug.add_event(
            ts,
            "audio.chunk",
            f"audio chunk for {participant_id}",
            snapshot,
        )
        self._schedule_stream_update(session_id)

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
        source: str = "extension",
    ) -> None:
        """Increment transcript counters and retain the latest transcript preview."""

        session = self._sessions.get(session_id)
        if session is None:
            return
        # Try to get speaker name from state store if not provided
        if speaker_name is None and session.state_store is not None:
            states = session.state_store.get_all_sync(session_id)
            for s in states:
                if s.participant_id == participant_id and s.display_name:
                    speaker_name = s.display_name
                    break
        preview = text if len(text) <= 120 else f"{text[:117]}..."
        snapshot: dict[str, object] = {
            "participant_id": participant_id,
            "speaker_name": speaker_name,
            "text": preview,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "source": source,
        }
        session.live_debug.transcript_segments += 1
        session.live_debug.last_transcript = snapshot
        session.live_debug.last_transcript_ts = max(
            session.live_debug.last_transcript_ts, end_sec
        )
        session.live_debug.add_event(
            end_sec,
            "transcript.segment",
            f"transcript for {participant_id}",
            snapshot,
        )
        self._schedule_stream_update(session_id)

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
        if kind == "offscreen.fallback_started":
            session.live_debug.fallback_only_mode = True
        elif kind == "offscreen.fallback_stopped":
            session.live_debug.fallback_only_mode = False
        elif kind == "content.transcript_source_active":
            session.live_debug.caption_transcript_active = True
        elif kind == "content.transcript_source_inactive":
            session.live_debug.caption_transcript_active = False

        session.live_debug.add_event(ts, kind, message, payload)
        self._schedule_stream_update(session_id)

    def get_live_debug_snapshot(
        self, session_id: str
    ) -> dict[str, object] | None:
        """Return the serializable live-debug view for a session."""

        session = self._sessions.get(session_id)
        if session is None:
            return None
        snapshot = session.live_debug.snapshot()
        snapshot["session_id"] = session_id
        segments = session.transcript_store.get_full_transcript(session_id)
        participants = session.state_store.get_all_sync(session_id)
        snapshot["per_participant_mode"] = not session.live_debug.fallback_only_mode
        snapshot["transcript_coverage"] = {
            "total_segments": len(segments),
            "caption_active": session.live_debug.caption_transcript_active,
            "transcribing_lag": session.live_debug.transcribing_lag,
        }
        snapshot["role_summary"] = {
            "total_participants": len(participants),
            "roles": [
                {
                    "participant_id": p.participant_id,
                    "display_name": p.display_name,
                    "role": p.role,
                    "confidence": p.confidence,
                }
                for p in participants
            ],
        }
        return snapshot

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
        await self._broadcast_stream_payload(session_id)
