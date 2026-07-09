"""WebcamAnalyzer: webcam_usage evidence per docs/SIGNALS.md §4."""

from __future__ import annotations

from dataclasses import dataclass

from app.analyzers.base import Analyzer
from app.schema import Event, EventType, Evidence, SessionEnvelope, WeightTable

_RATIO_LOW = 0.30
_RATIO_HIGH = 0.80
_EXPIRES_DELAY_SEC = 60.0


@dataclass
class _WebcamState:
    join_ts: float
    is_on: bool = False
    on_since: float | None = None
    total_on_sec: float = 0.0


def _ratio_to_score(ratio: float) -> float:
    return max(0.0, min(1.0, (ratio - _RATIO_LOW) / (_RATIO_HIGH - _RATIO_LOW)))


class WebcamAnalyzer(Analyzer):
    """Owns webcam_usage (0.05). Re-emits every 5s via on_tick."""

    def __init__(self) -> None:
        self._weight = 0.0
        self._session_id: str | None = None
        self._participants: dict[str, _WebcamState] = {}
        self._seen: set[tuple[str, int]] = set()

    @property
    def feature(self) -> str:
        return "webcam_usage"

    @property
    def source(self) -> str:
        return "webcam_analyzer"

    async def initialize(self, weights: WeightTable, session: SessionEnvelope) -> None:
        self._weight = weights.weights["webcam_usage"]
        self._session_id = session.session_id

    async def on_event(self, event: Event) -> list[Evidence]:
        key = (event.envelope.source, event.envelope.sequence)
        if key in self._seen:
            return []
        self._seen.add(key)

        if event.type == EventType.PARTICIPANT_JOINED:
            participant_id = event.payload["participant_id"]
            self._participants[participant_id] = _WebcamState(join_ts=event.envelope.ts)
            return []

        if event.type == EventType.WEBCAM_ON:
            state = self._participants.get(event.payload["participant_id"])
            if state is not None:
                state.is_on = True
                state.on_since = event.envelope.ts
            return []

        if event.type == EventType.WEBCAM_OFF:
            state = self._participants.get(event.payload["participant_id"])
            if state is not None and state.is_on and state.on_since is not None:
                state.total_on_sec += event.envelope.ts - state.on_since
                state.is_on = False
                state.on_since = None
            return []

        return []

    async def on_tick(self, t: float) -> list[Evidence]:
        assert self._session_id is not None, "initialize() must be called before on_tick"
        evidences: list[Evidence] = []
        for participant_id, state in self._participants.items():
            active_sec = t - state.on_since if state.is_on and state.on_since is not None else 0.0
            on_sec = state.total_on_sec + active_sec
            present_sec = max(t - state.join_ts, 1e-6)
            ratio = on_sec / present_sec
            score = _ratio_to_score(ratio)
            reason = (
                "Webcam never active"
                if ratio == 0.0
                else f"Webcam active {ratio:.0%} of the meeting"
            )
            evidences.append(
                Evidence(
                    session_id=self._session_id,
                    participant_id=participant_id,
                    feature="webcam_usage",
                    source=self.source,
                    score=score,
                    weight=self._weight,
                    reason=reason,
                    ts=t,
                    expires_at=t + _EXPIRES_DELAY_SEC,
                    supersedes="webcam_usage",
                )
            )
        return evidences
