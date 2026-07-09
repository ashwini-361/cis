"""ScreenShareAnalyzer: screen_share_content evidence per docs/SIGNALS.md §9.

Real CLIP-based classification lands in Phase 6; Phase 4 wires the full
event-timing logic with an injectable stub classifier (mirrors the
LLMProvider swappable-provider pattern used by transcript_role, §6.8).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.analyzers.base import Analyzer
from app.schema import Event, EventType, Evidence, SessionEnvelope, WeightTable

_EXPIRES_DELAY_SEC = 300.0

ClassifyFn = Callable[[list[Any]], tuple[str, float]]


def _stub_classify(frames: list[Any]) -> tuple[str, float]:
    """Placeholder classifier -- matches SIGNALS.md §9.2's documented 'else' fallback."""
    return ("unclassified", 0.20)


@dataclass
class _ShareState:
    start_ts: float
    frames: list[Any] = field(default_factory=list)


class ScreenShareAnalyzer(Analyzer):
    """Owns screen_share_content (0.05)."""

    def __init__(self, classify: ClassifyFn = _stub_classify) -> None:
        self._weight = 0.0
        self._session_id: str | None = None
        self._classify = classify
        self._active: dict[str, _ShareState] = {}
        self._seen: set[tuple[str, int]] = set()

    @property
    def feature(self) -> str:
        return "screen_share_content"

    @property
    def source(self) -> str:
        return "screen_share_analyzer"

    async def initialize(self, weights: WeightTable, session: SessionEnvelope) -> None:
        self._weight = weights.weights["screen_share_content"]
        self._session_id = session.session_id

    async def on_event(self, event: Event) -> list[Evidence]:
        key = (event.envelope.source, event.envelope.sequence)
        if key in self._seen:
            return []
        self._seen.add(key)

        if event.type == EventType.SCREEN_SHARE_START:
            participant_id = event.payload["participant_id"]
            self._active[participant_id] = _ShareState(start_ts=event.envelope.ts)
            return []

        if event.type == EventType.SCREEN_FRAME:
            participant_id = event.payload.get("participant_id")
            if participant_id is not None and participant_id in self._active:
                self._active[participant_id].frames.append(event.payload)
            return []

        if event.type == EventType.SCREEN_SHARE_STOP:
            participant_id = event.payload["participant_id"]
            state = self._active.pop(participant_id, None)
            if state is None:
                return []
            assert self._session_id is not None, "initialize() must be called before on_event"
            label, score = self._classify(state.frames)
            return [
                Evidence(
                    session_id=self._session_id,
                    participant_id=participant_id,
                    feature="screen_share_content",
                    source=self.source,
                    score=score,
                    weight=self._weight,
                    reason=f"Screen-shared content classified as '{label}'",
                    ts=event.envelope.ts,
                    expires_at=event.envelope.ts + _EXPIRES_DELAY_SEC,
                    supersedes="screen_share_content",
                )
            ]

        return []
