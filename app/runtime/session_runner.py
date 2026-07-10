"""SessionRunner — single replay/live entrypoint.

Drives an :class:`IngestAdapter` stream through a :class:`TickScheduler`,
returning the full verdict time-series. Live calls it with a
:class:`RealClock`; the harness + tests use a :class:`ManualClock` stepped
to each event ``ts``. Same code path either way.

Ticks are emitted on every adapter event timestamp — i.e. whenever
``ManualClock`` crosses an event boundary in the harness; in live mode
add an outer interval-trigger that calls ``scheduler.tick(clock.now())``
periodically alongside the per-event :meth:`scheduler.process_event`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from app.analyzers.base import Analyzer
from app.ingest.base import IngestAdapter
from app.runtime.clock import Clock
from app.runtime.tick_scheduler import Broadcast, TickScheduler
from app.schema import Event, EventEnvelope, EventType, SessionEnvelope, Verdict, WeightTable
from app.store.evidence import EvidenceStore
from app.store.state import ParticipantStateStore
from app.store.transcript import TranscriptStore

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

EventCallback = Callable[[Event], Awaitable[None]]


async def run_session(
    adapter: IngestAdapter,
    session_envelope: SessionEnvelope,
    platform: str,
    analyzers: list[Analyzer],
    weights: WeightTable,
    *,
    clock: Clock,
    evidence_store: EvidenceStore | None = None,
    state_store: ParticipantStateStore | None = None,
    transcript_store: TranscriptStore | None = None,
    broadcast: Broadcast | None = None,
    event_callback: EventCallback | None = None,
    threshold: float | None = None,
    margin: float | None = None,
) -> list[Verdict]:
    """Drive ``adapter`` to completion; return every ``Verdict`` produced.

    Defaults: in-memory stores (no Redis), a recording broadcast sink
    that captures verdicts into its own list (returned in
    :func:`record_verdicts`), thresholds from ``weights``.

    Per-event flow:

    - ``await scheduler.process_event(event)`` — feeds the bus/analyzers.
    - ``clock.set(event.envelope.ts)`` (caller responsibility; live
      uses a wall-clock that advances on its own).
    - ``await scheduler.tick(t)`` — runs ``on_tick``, fuse, decide,
      broadcast for that timestamp.
    """

    store = evidence_store if evidence_store is not None else EvidenceStore()
    states = state_store if state_store is not None else ParticipantStateStore()
    transcripts = transcript_store if transcript_store is not None else TranscriptStore()
    verdicts: list[Verdict] = []
    if broadcast is None:
        broadcast = _list_broadcast(verdicts)

    scheduler = TickScheduler(
        session_envelope=session_envelope,
        platform=platform,
        analyzers=analyzers,
        weights=weights,
        evidence_store=store,
        state_store=states,
        transcript_store=transcripts,
        broadcast=broadcast,
        threshold=threshold if threshold is not None else weights.threshold,
        margin=margin if margin is not None else weights.margin,
    )

    await adapter.start_session(session_envelope)
    await scheduler.initialize()
    await _inject_bootstrap_metadata(scheduler, session_envelope)

    try:
        async for event in adapter.stream_events():
            await scheduler.process_event(event)
            if event_callback is not None:
                await event_callback(event)
            t = event.envelope.ts
            _step_clock(clock, t)
            await scheduler.tick(t)
    finally:
        await adapter.end_session(reason="normal")

    return verdicts


async def _inject_bootstrap_metadata(
    scheduler: TickScheduler, session_envelope: SessionEnvelope
) -> None:
    """Seed live sessions with candidate/schedule metadata when callers provide it."""

    bootstrap_events: list[Event] = []

    if session_envelope.candidate_name is not None or session_envelope.candidate_email is not None:
        bootstrap_events.append(
            Event(
                type=EventType.METADATA_CANDIDATE,
                envelope=_bootstrap_envelope(session_envelope, sequence=-3),
                payload={
                    "name": session_envelope.candidate_name,
                    "email": session_envelope.candidate_email,
                    "calendar_invite_id": session_envelope.calendar_invite_id,
                },
            )
        )

    if session_envelope.interviewer_names:
        bootstrap_events.append(
            Event(
                type=EventType.METADATA_SCHEDULE,
                envelope=_bootstrap_envelope(session_envelope, sequence=-2),
                payload={
                    "start_wall_clock": session_envelope.start_wall_clock,
                    "expected_duration_min": session_envelope.expected_duration_min,
                    "interviewer_names": session_envelope.interviewer_names,
                },
            )
        )
        bootstrap_events.append(
            Event(
                type=EventType.METADATA_INTERVIEWERS,
                envelope=_bootstrap_envelope(session_envelope, sequence=-1),
                payload={
                    "names": session_envelope.interviewer_names,
                    "emails": [],
                },
            )
        )

    for event in bootstrap_events:
        await scheduler.process_event(event)


def _bootstrap_envelope(session_envelope: SessionEnvelope, *, sequence: int) -> EventEnvelope:
    return EventEnvelope(
        session_id=session_envelope.session_id,
        ts=0.0,
        wall_clock=session_envelope.start_wall_clock,
        platform=session_envelope.platform,
        source="session.bootstrap",
        sequence=sequence,
    )


def _step_clock(clock: Clock, t: float) -> None:
    """Advance a :class:`ManualClock` to ``t``; no-op for :class:`RealClock`.

    The :class:`Clock` protocol only exposes ``now()``; this helper uses a
    duck-typed ``current`` attribute that ``RealClock`` (wall-clock) does
    not carry and ``ManualClock`` (deterministic) does. ``getattr`` and a
    missing-attribute guard keep mypy happy without coupling callers.
    """

    if hasattr(clock, "current"):
        clock.current = t


def record_verdicts() -> tuple[Broadcast, list[Verdict]]:
    """Replace ``broadcast`` with a recording sink; returns the sink + list."""

    verdicts: list[Verdict] = []
    return _list_broadcast(verdicts), verdicts


def _list_broadcast(verdicts: list[Verdict]) -> Broadcast:
    async def _sink(verdict: Verdict) -> None:
        verdicts.append(verdict)

    return _sink


async_callable_marker = Callable[[Verdict], Awaitable[None]]
"""Type alias used to declare the broadcast shape; not exported for runtime use."""
