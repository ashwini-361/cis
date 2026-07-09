"""JoinOrderAnalyzer: join_order evidence per docs/SIGNALS.md §3."""

from __future__ import annotations

from dataclasses import dataclass

from app.analyzers.base import Analyzer
from app.schema import Event, EventType, Evidence, SessionEnvelope, WeightTable

_REFIRE_DELAY_SEC = 60.0
_ANTI_EVIDENCE_SCORE = 0.10
_BASE_BY_RANK = {1: 0.60, 2: 0.30}
_BASE_DEFAULT = 0.10
_BOOST = 0.20


@dataclass
class _Participant:
    participant_id: str
    display_name: str
    join_order: int


def _score(join_order: int, display_name: str, interviewer_names: list[str] | None) -> float:
    if interviewer_names is not None and display_name in interviewer_names:
        return _ANTI_EVIDENCE_SCORE
    base = _BASE_BY_RANK.get(join_order, _BASE_DEFAULT)
    boost = _BOOST if interviewer_names is not None else 0.0
    return min(base + boost, 1.0)


class JoinOrderAnalyzer(Analyzer):
    """Owns join_order (0.05). Re-fires once, 60s after SESSION_START."""

    def __init__(self) -> None:
        self._weight = 0.0
        self._interviewer_names: list[str] | None = None
        self._session_start_ts: float | None = None
        self._session_id: str | None = None
        self._participants: dict[str, _Participant] = {}
        self._refired = False
        self._seen: set[tuple[str, int]] = set()

    @property
    def feature(self) -> str:
        return "join_order"

    @property
    def source(self) -> str:
        return "join_order_analyzer"

    async def initialize(self, weights: WeightTable, session: SessionEnvelope) -> None:
        self._weight = weights.weights["join_order"]
        self._session_id = session.session_id

    async def on_event(self, event: Event) -> list[Evidence]:
        key = (event.envelope.source, event.envelope.sequence)
        if key in self._seen:
            return []
        self._seen.add(key)

        if event.type == EventType.SESSION_START:
            self._session_start_ts = event.envelope.ts
            return []

        if event.type == EventType.METADATA_INTERVIEWERS:
            self._interviewer_names = event.payload["names"]
            return []

        if event.type == EventType.PARTICIPANT_JOINED:
            participant = _Participant(
                participant_id=event.payload["participant_id"],
                display_name=event.payload["display_name"],
                join_order=event.payload["join_order"],
            )
            self._participants[participant.participant_id] = participant
            return [self._evidence_for(participant, event.envelope.ts)]

        return []

    async def on_tick(self, t: float) -> list[Evidence]:
        if self._refired or self._session_start_ts is None:
            return []
        if t - self._session_start_ts < _REFIRE_DELAY_SEC:
            return []
        self._refired = True
        return [self._evidence_for(p, t) for p in self._participants.values()]

    def _evidence_for(self, participant: _Participant, ts: float) -> Evidence:
        score = _score(participant.join_order, participant.display_name, self._interviewer_names)
        assert self._session_id is not None, "initialize() must be called before on_event/on_tick"
        return Evidence(
            session_id=self._session_id,
            participant_id=participant.participant_id,
            feature="join_order",
            source=self.source,
            score=score,
            weight=self._weight,
            reason=f"Joined order {participant.join_order}"
            + (
                " (known interviewer)"
                if self._interviewer_names is not None
                and participant.display_name in self._interviewer_names
                else ""
            ),
            ts=ts,
            expires_at=None,
            supersedes="join_order",
        )
