"""TickScheduler — the live-loop wiring that ties an ingest stream to
the real analyzer set, evidence store, ticker math, and verdict broadcast.

This is the piece Phases 1–8 deferred: the bus had ``publish``/``subscribe``
but nothing subscribed; the ticker existed but never called
``analyzer.on_tick``. Phase 9A closes both gaps in one place so live +
offline harness share the same code path.

Responsibilities, per tick at time ``t``:

1. Drain any events published since the previous tick through every
   analyzer's ``on_event``; append produced ``Evidence`` to the store.
2. Call every analyzer's ``on_tick(t)``; append produced ``Evidence``
   to the store (closes the orphaned-``on_tick`` regression noted in
   docs/EVALUATION.md and ACCURACY_METRICS.md).
3. Invoke ``app.fusion.engine.decide(...)`` over freshly-fused per-participant
   states and ``await broadcast(verdict)``.

Why the scheduler drives analyzers by **direct method call** rather than
``EventBus.publish``/``subscribe``: the bus is a fine pub/sub fan-out for
external consumers (Redis pub/sub, logging) but on the hot per-tick path
predictable direct calls keep evidence ordering deterministic and let
the harness get the same code path as live via an injected ``Clock`` —
no thread-of-control difference between MockAdapter (replay, ManualClock)
and ZoomAdapter (live, RealClock).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.analyzers.base import Analyzer
from app.explain.generator import Explainer
from app.fusion.engine import apply_supersedes, decide, fuse
from app.schema import (
    Event,
    EventType,
    Evidence,
    ParticipantState,
    SessionEnvelope,
    Verdict,
    WeightTable,
)
from app.store.evidence import EvidenceStore
from app.store.state import ParticipantStateStore

logger = logging.getLogger(__name__)

Broadcast = Callable[[Verdict], Awaitable[None]]


class TickScheduler:
    """Per-session scheduler. Owns the per-tick dispatch + broadcast."""

    def __init__(
        self,
        session_envelope: SessionEnvelope,
        platform: str,
        analyzers: list[Analyzer],
        weights: WeightTable,
        evidence_store: EvidenceStore,
        state_store: ParticipantStateStore,
        broadcast: Broadcast,
        threshold: float,
        margin: float,
    ) -> None:
        self._session = session_envelope
        self._platform = platform
        self._analyzers = analyzers
        self._weights = weights
        self._store = evidence_store
        self._state_store = state_store
        self._broadcast = broadcast
        self._threshold = threshold
        self._margin = margin

        self._seen_event_keys: set[tuple[str, int]] = set()
        self._participants: dict[str, str] = {}  # participant_id -> display_name

    async def initialize(self) -> None:
        """Call ``analyzer.initialize`` once on every analyzer."""

        await asyncio.gather(
            *(analyzer.initialize(self._weights, self._session) for analyzer in self._analyzers)
        )

    async def process_event(self, event: Event) -> list[Evidence]:
        """Feed one event through every analyzer's ``on_event``.

        The schedulers' own event-key dedupe is a backstop — analyzers
        each carry a private ``_seen`` set as their primary idempotency
        mechanism (docs/DATA_CONTRACT.md §8). We also track
        PARTICIPANT_JOINED / PARTICIPANT_RENAMED ourselves so
        ``tick()`` can seed *every* participant even if no fresh
        evidence has accumulated since the last tick.
        """

        produced: list[Evidence] = []

        key = (event.envelope.source, event.envelope.sequence)
        if key in self._seen_event_keys:
            return produced
        self._seen_event_keys.add(key)

        if event.type == EventType.PARTICIPANT_JOINED:
            self._participants[event.payload["participant_id"]] = event.payload["display_name"]
        elif event.type == EventType.PARTICIPANT_RENAMED:
            self._participants[event.payload["participant_id"]] = event.payload["new_name"]

        coros = [analyzer.on_event(event) for analyzer in self._analyzers]
        results = await asyncio.gather(*coros, return_exceptions=True)
        for analyzer, result in zip(self._analyzers, results, strict=True):
            if isinstance(result, BaseException):
                logger.exception(
                    "analyzer %s.on_event raised", analyzer.source, exc_info=result
                )
                continue
            for evidence in result:
                await self._store.append(evidence)
                produced.append(evidence)
        return produced

    async def tick(self, t: float) -> Verdict:
        """One fusion recomputation at time ``t``."""

        # (1) per-analyzer on_tick fan-out — closes the orphaned-tick
        # regression noted in docs/EVALUATION.md (transcript-role evidence
        # was never being emitted before Phase 9A fixed this).
        tick_coros = [analyzer.on_tick(t) for analyzer in self._analyzers]
        tick_results = await asyncio.gather(*tick_coros, return_exceptions=True)
        for analyzer, result in zip(self._analyzers, tick_results, strict=True):
            if isinstance(result, BaseException):
                logger.exception(
                    "analyzer %s.on_tick raised", analyzer.source, exc_info=result
                )
                continue
            for evidence in result:
                await self._store.append(evidence)

        # (2) per-participant: load + apply_supersedes + fuse + state update
        states: list[ParticipantState] = []
        for participant_id in sorted(self._participants):
            evidences = apply_supersedes(
                await self._store.get(self._session.session_id, participant_id)
            )
            confidence = fuse(evidences, t)
            existing = await self._state_store.get(self._session.session_id, participant_id)
            display_name = self._participants[participant_id] or (
                existing.display_name if existing is not None else participant_id
            )
            base_state = existing or ParticipantState(
                session_id=self._session.session_id,
                participant_id=participant_id,
                display_name=display_name,
                join_ts=t,
            )
            updated = base_state.model_copy(
                update={
                    "display_name": display_name,
                    "confidence": confidence,
                    "raw_evidence": evidences,
                    "last_recompute_ts": t,
                    "total_evidence": len(evidences),
                    "analyzer_count": len({e.source for e in evidences}),
                }
            )
            await self._state_store.set(updated)
            states.append(updated)

        # (3) decide + broadcast
        # Require at least as many participants as the session expects before
        # committing; prevents premature single-participant decisions that flip
        # when further participants join and dilute the margin.
        min_p = max(len(self._session.expected_participants), 1)
        verdict = decide(
            session_id=self._session.session_id,
            platform=self._platform,
            states=states,
            t=t,
            explainer=Explainer(),
            threshold=self._threshold,
            margin=self._margin,
            min_participants=min_p,
        )
        await self._broadcast(verdict)
        return verdict

    def known_participants(self) -> dict[str, str]:
        """Snapshot of participant_id -> display_name seen by the scheduler."""

        return dict(self._participants)

    async def reset(self) -> None:
        """Clear dedupe + participant state — for tests that replay the
        same recording twice over one scheduler instance."""

        self._seen_event_keys.clear()
        self._participants.clear()


def make_broadcast_sink() -> tuple[Broadcast, list[Verdict]]:
    """Build a Broadcast callable that records verdicts into the returned list."""

    verdicts: list[Verdict] = []

    async def _sink(verdict: Verdict) -> None:
        verdicts.append(verdict)

    return _sink, verdicts
