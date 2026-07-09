"""VisionAnalyzer: face_consistency evidence per docs/SIGNALS.md §8.

This is a face-SWAP detector, not face recognition -- it only asks "is the
face on this participant's feed still the same person as before," never
"who is this person." Deliberately minimal per docs/ROADMAP.md §6: weight
stays 0.00, disabled by default, and only the interface/dummy-backend/
feature-flag/tests are shipped here -- no real MediaPipe/InsightFace
integration (see the Phase 6 plan for why).
"""

from __future__ import annotations

import math
from typing import Any, Protocol

from app.analyzers.base import Analyzer
from app.schema import Event, EventType, Evidence, SessionEnvelope, WeightTable

_WINDOW_SEC = 60.0
_EXPIRES_DELAY_SEC = 300.0
_DISTANCE_SCALE = 0.5
_EMA_ALPHA = 0.1
_SWAP_THRESHOLD = 0.30
_CONSISTENT_THRESHOLD = 0.85

Embedding = tuple[float, ...]


class VisionBackend(Protocol):
    """The swappable boundary. Real MediaPipe+InsightFace inference is a
    future backend implementing this same interface -- not built here."""

    def extract_embedding(self, frame_payload: Any) -> Embedding | None:
        """Return an embedding, or None if no face was detected in this frame."""
        ...


class DummyVisionBackend:
    """Deterministic placeholder backend. No ML dependencies."""

    def extract_embedding(self, frame_payload: Any) -> Embedding | None:
        return (1.0, 0.0, 0.0)


_DEFAULT_BACKEND = DummyVisionBackend()


def _cosine_distance(a: Embedding, b: Embedding) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0
    return 1.0 - dot / (norm_a * norm_b)


class VisionAnalyzer(Analyzer):
    """Owns face_consistency (0.00, permanently -- see docs/ROADMAP.md §6.2)."""

    def __init__(self, backend: VisionBackend = _DEFAULT_BACKEND, enabled: bool = False) -> None:
        self._backend = backend
        self._enabled = enabled
        self._weight = 0.0
        self._session_id: str | None = None
        self._ema: dict[str, Embedding] = {}
        self._frame_scores: dict[str, list[tuple[float, float]]] = {}
        self._seen: set[tuple[str, int]] = set()

    @property
    def feature(self) -> str:
        return "face_consistency"

    @property
    def source(self) -> str:
        return "vision_analyzer"

    async def initialize(self, weights: WeightTable, session: SessionEnvelope) -> None:
        self._weight = weights.weights["face_consistency"]
        self._session_id = session.session_id

    async def on_event(self, event: Event) -> list[Evidence]:
        if not self._enabled:
            return []

        key = (event.envelope.source, event.envelope.sequence)
        if key in self._seen:
            return []
        self._seen.add(key)

        if event.type != EventType.VIDEO_FRAME:
            return []

        participant_id = event.payload["participant_id"]
        embedding = self._backend.extract_embedding(event.payload)
        if embedding is None:
            return []

        prior = self._ema.get(participant_id)
        if prior is None:
            self._ema[participant_id] = embedding
            score = 1.0
        else:
            distance = _cosine_distance(embedding, prior)
            score = max(0.0, min(1.0, 1.0 - distance / _DISTANCE_SCALE))
            self._ema[participant_id] = tuple(
                (1 - _EMA_ALPHA) * p + _EMA_ALPHA * n for p, n in zip(prior, embedding, strict=True)
            )

        self._frame_scores.setdefault(participant_id, []).append((event.envelope.ts, score))
        return []

    async def on_tick(self, t: float) -> list[Evidence]:
        if not self._enabled:
            return []
        assert self._session_id is not None, "initialize() must be called before on_tick"

        evidences: list[Evidence] = []
        for participant_id, history in self._frame_scores.items():
            window = [s for ts, s in history if t - ts <= _WINDOW_SEC]
            if not window:
                continue  # no face in the last 60s -- stay silent, not score=0
            score = sum(window) / len(window)
            if score < _SWAP_THRESHOLD:
                reason = f"Face embedding changed abruptly -- possible face swap at t={t:.1f}s"
            elif score >= _CONSISTENT_THRESHOLD:
                reason = "Face has been consistent throughout the meeting"
            else:
                reason = "Face consistency is moderate -- inconclusive"
            evidences.append(
                Evidence(
                    session_id=self._session_id,
                    participant_id=participant_id,
                    feature="face_consistency",
                    source=self.source,
                    score=score,
                    weight=self._weight,
                    reason=reason,
                    ts=t,
                    expires_at=t + _EXPIRES_DELAY_SEC,
                    supersedes="face_consistency",
                )
            )
        return evidences
