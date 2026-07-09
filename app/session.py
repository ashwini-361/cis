"""Session + SessionManager: consolidates per-session state per the Phase 8 plan.

Replaces the scattered `meet_adapters`/`zoom_adapters` dicts that had grown
in app/main.py across Phases 7a/7b with one coherent per-session object
(EventBus, ParticipantStateStore, WeightTable, the active ingest adapter,
connected WebSocket subscribers, and the latest broadcast Verdict).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.bus import EventBus
from app.schema import Verdict, WeightTable
from app.store.state import ParticipantStateStore

if TYPE_CHECKING:
    from app.ingest.base import IngestAdapter


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


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create_session(
        self, session_id: str, weights: WeightTable, redis_url: str | None = None
    ) -> Session:
        session = Session(
            session_id=session_id,
            bus=EventBus(redis_url=redis_url),
            state_store=ParticipantStateStore(redis_url=redis_url),
            weights=weights,
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def remove_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def add_subscriber(self, session_id: str, websocket: Any) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.subscribers.append(websocket)

    def remove_subscriber(self, session_id: str, websocket: Any) -> None:
        session = self._sessions.get(session_id)
        if session is not None and websocket in session.subscribers:
            session.subscribers.remove(websocket)

    async def broadcast_verdict(self, session_id: str, verdict: Verdict) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.latest_verdict = verdict
        dead: list[Any] = []
        for websocket in session.subscribers:
            try:
                await websocket.send_json(verdict.model_dump(mode="json"))
            except Exception:  # noqa: BLE001 -- a dead/broken client shouldn't stop the broadcast to others
                dead.append(websocket)
        for websocket in dead:
            session.subscribers.remove(websocket)
