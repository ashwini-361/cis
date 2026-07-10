"""TickScheduler tests — the load-bearing regression for ``on_tick``.

The whole point of Phase 9A: analyzers must actually be called every
tick. Before this fix, ``TranscriptRoleAnalyzer`` (the strongest signal
at weight 0.25) emitted ``[]`` on every ``on_event`` — its evidence only
came via ``on_tick`` — and nothing in Phases 1–8 ever called
``on_tick``. So the documented t≈200s verdict was unreachable. These
tests prove the scheduler closes that gap.
"""

from __future__ import annotations

from app.runtime.registry import build_default
from app.runtime.tick_scheduler import TickScheduler, make_broadcast_sink
from app.schema import Event, EventEnvelope, EventType, SessionEnvelope
from app.store.evidence import EvidenceStore
from app.store.state import ParticipantStateStore
from app.store.transcript import TranscriptStore


def _envelope(
    session_id: str = "rt-sess-1",
    ts: float = 0.0,
    source: str = "test",
    sequence: int = 0,
) -> EventEnvelope:
    return EventEnvelope(
        session_id=session_id,
        ts=ts,
        wall_clock="2026-07-09T00:00:00Z",
        platform="mock",
        source=source,
        sequence=sequence,
    )


async def test_on_tick_invoked_on_every_analyzer(weights, session_envelope, scripted_llm) -> None:
    """Every analyzer's on_tick is called -- counters the orphan regression.

    TranscriptRoleAnalyzer only emits evidence via on_tick (window ≥ 3
    segments within 60s). Without on_tick-invocation, transcript_role
    evidence would simply not exist in the store after tick()."""

    broadcast, verdicts = make_broadcast_sink()
    analyzers = build_default(weights, scripted_llm)
    evidence_store = EvidenceStore()
    state_store = ParticipantStateStore()

    scheduler = TickScheduler(
        session_envelope=session_envelope,
        platform="mock",
        analyzers=analyzers,
        weights=weights,
        evidence_store=evidence_store,
        state_store=state_store,
        transcript_store=TranscriptStore(),
            broadcast=broadcast,
        threshold=weights.threshold,
        margin=weights.margin,
    )
    await scheduler.initialize()

    # Feed 3 transcript segments to seed the role-classifier window.
    events = [
        Event(
            type=EventType.TRANSCRIPT_SEGMENT,
            envelope=_envelope(ts=65.0, source="mock.test", sequence=10),
            payload={
                "participant_id": "P3",
                "text": "Tell me about yourself.",
                "start_sec": 65.0,
                "end_sec": 70.0,
            },
        ),
        Event(
            type=EventType.TRANSCRIPT_SEGMENT,
            envelope=_envelope(ts=71.0, source="mock.test", sequence=11),
            payload={
                "participant_id": "P1",
                "text": "I'm a backend engineer with three years of experience.",
                "start_sec": 71.0,
                "end_sec": 90.0,
            },
        ),
        Event(
            type=EventType.TRANSCRIPT_SEGMENT,
            envelope=_envelope(ts=91.5, source="mock.test", sequence=12),
            payload={
                "participant_id": "P3",
                "text": "Why this company?",
                "start_sec": 91.5,
                "end_sec": 93.0,
            },
        ),
    ]
    for event in events:
        await scheduler.process_event(event)

    # Tick at 100s -- past the 60s window, after the 3-segment minimum.
    await scheduler.tick(100.0)

    # transcript_role evidence must now exist -- this is the orphan regression.
    p1_evidence = await evidence_store.get(session_envelope.session_id, "P1")
    p3_evidence = await evidence_store.get(session_envelope.session_id, "P3")

    tr_features = {e.feature for e in p1_evidence + p3_evidence}
    assert "transcript_role" in tr_features, (
        "transcript_role evidence was never emitted -- on_tick is the regression proof"
    )

    # Verdict was broadcast.
    assert len(verdicts) == 1
    v = verdicts[0]
    assert v.session_id == session_envelope.session_id
    assert v.ts == 100.0


async def test_on_event_dispatches_through_every_analyzer(
    weights, session_envelope, scripted_llm
) -> None:
    """Every analyzer's on_event is called for every event (sans dedupe)."""

    broadcast, _ = make_broadcast_sink()
    analyzers = build_default(weights, scripted_llm)
    evidence_store = EvidenceStore()
    state_store = ParticipantStateStore()

    scheduler = TickScheduler(
        session_envelope=session_envelope,
        platform="mock",
        analyzers=analyzers,
        weights=weights,
        evidence_store=evidence_store,
        state_store=state_store,
        transcript_store=TranscriptStore(),
            broadcast=broadcast,
        threshold=weights.threshold,
        margin=weights.margin,
    )
    await scheduler.initialize()

    # Metadata events must precede JOIN so MetadataAnalyzer has target fields to score against.
    metadata = Event(
        type=EventType.METADATA_CANDIDATE,
        envelope=_envelope(ts=0.0, sequence=0),
        payload={
            "name": "Ashwini Kumar",
            "email": "ashwini.kumar@gmail.com",
            "calendar_invite_id": None,
        },
    )
    await scheduler.process_event(metadata)

    join_event = Event(
        type=EventType.PARTICIPANT_JOINED,
        envelope=_envelope(ts=1.0, sequence=1),
        payload={
            "participant_id": "P1",
            "display_name": "Ashwini",
            "email": "ashwini.kumar@gmail.com",
            "device_name": None,
            "join_order": 1,
        },
    )
    emitted = await scheduler.process_event(join_event)
    # MetadataAnalyzer emits name_similarity + email_match on join once
    # METADATA_CANDIDATE has primed the analyzer.
    features = {e.feature for e in emitted}
    assert "name_similarity" in features
    assert "email_match" in features


async def test_process_event_idempotent_on_replayed_envelope_key(
    weights, session_envelope, scripted_llm
) -> None:
    """Re-processing the same (source, sequence) is a no-op."""

    broadcast, _ = make_broadcast_sink()
    analyzers = build_default(weights, scripted_llm)
    evidence_store = EvidenceStore()
    state_store = ParticipantStateStore()

    scheduler = TickScheduler(
        session_envelope=session_envelope,
        platform="mock",
        analyzers=analyzers,
        weights=weights,
        evidence_store=evidence_store,
        state_store=state_store,
        transcript_store=TranscriptStore(),
            broadcast=broadcast,
        threshold=weights.threshold,
        margin=weights.margin,
    )
    await scheduler.initialize()

    event = Event(
        type=EventType.PARTICIPANT_JOINED,
        envelope=_envelope(ts=1.0, sequence=42),
        payload={
            "participant_id": "P1",
            "display_name": "Ashwini",
            "email": "ashwini.kumar@gmail.com",
            "device_name": None,
            "join_order": 1,
        },
    )
    first = await scheduler.process_event(event)
    replay = await scheduler.process_event(event)
    assert len(first) > 0
    assert replay == []


async def test_state_store_reflects_latest_fusion(weights, session_envelope, scripted_llm) -> None:
    """TickScheduler writes fresh fused states into ParticipantStateStore."""

    broadcast, _ = make_broadcast_sink()
    analyzers = build_default(weights, scripted_llm)
    evidence_store = EvidenceStore()
    state_store = ParticipantStateStore()

    scheduler = TickScheduler(
        session_envelope=session_envelope,
        platform="mock",
        analyzers=analyzers,
        weights=weights,
        evidence_store=evidence_store,
        state_store=state_store,
        transcript_store=TranscriptStore(),
            broadcast=broadcast,
        threshold=weights.threshold,
        margin=weights.margin,
    )
    await scheduler.initialize()

    event = Event(
        type=EventType.PARTICIPANT_JOINED,
        envelope=_envelope(ts=1.0, sequence=1),
        payload={
            "participant_id": "P1",
            "display_name": "Ashwini",
            "email": "ashwini.kumar@gmail.com",
            "device_name": None,
            "join_order": 1,
        },
    )
    await scheduler.process_event(event)
    await scheduler.tick(50.0)

    p1 = await state_store.get(session_envelope.session_id, "P1")
    assert p1 is not None
    assert p1.participant_id == "P1"
    assert p1.confidence > 0.0  # email_match is sticky, no decay
    assert p1.last_recompute_ts == 50.0


async def test_process_event_maps_raw_meet_audio_alias_to_named_participant(
    weights, scripted_llm
) -> None:
    base_envelope = EventEnvelope(
        session_id="meet-sess-1",
        ts=0.0,
        source="test",
        sequence=0,
        wall_clock="2026-07-09T00:00:00Z",
        platform="meet",
    )
    broadcast, _ = make_broadcast_sink()
    analyzers = build_default(weights, scripted_llm)
    transcript_store = TranscriptStore()

    scheduler = TickScheduler(
        session_envelope=SessionEnvelope(
            session_id="meet-sess-1",
            platform="meet",
            start_wall_clock="2026-07-09T00:00:00Z",
        ),
        platform="meet",
        analyzers=analyzers,
        weights=weights,
        evidence_store=EvidenceStore(),
        state_store=ParticipantStateStore(),
        transcript_store=transcript_store,
        broadcast=broadcast,
        threshold=weights.threshold,
        margin=weights.margin,
    )
    await scheduler.initialize()

    join_events = [
        Event(
            type=EventType.PARTICIPANT_JOINED,
            envelope=base_envelope.model_copy(update={"sequence": 1, "ts": 1.0}),
            payload={
                "participant_id": "spaces/meet/devices/343",
                "display_name": "Rahul",
                "email": None,
                "device_name": None,
                "join_order": 1,
            },
        ),
        Event(
            type=EventType.PARTICIPANT_JOINED,
            envelope=base_envelope.model_copy(update={"sequence": 2, "ts": 2.0}),
            payload={
                "participant_id": "spaces/meet/devices/344",
                "display_name": "devices",
                "email": None,
                "device_name": None,
                "join_order": 2,
            },
        ),
        Event(
            type=EventType.PARTICIPANT_JOINED,
            envelope=base_envelope.model_copy(update={"sequence": 3, "ts": 3.0}),
            payload={
                "participant_id": "spaces/meet/devices/345",
                "display_name": "devices",
                "email": None,
                "device_name": None,
                "join_order": 3,
            },
        ),
    ]
    for event in join_events:
        await scheduler.process_event(event)

    await scheduler.process_event(
        Event(
            type=EventType.TRANSCRIPT_SEGMENT,
            envelope=base_envelope.model_copy(
                update={"sequence": 4, "ts": 30.0, "source": "meet.transcript.whisper"}
            ),
            payload={
                "participant_id": "pc-1",
                "text": "Tell me about your background.",
                "start_sec": 30.0,
                "end_sec": 33.0,
            },
        )
    )

    transcript = transcript_store.get_full_transcript("meet-sess-1")
    assert len(transcript) == 1
    assert transcript[0].participant_id == "spaces/meet/devices/343"
    assert transcript[0].speaker_name == "Rahul"
