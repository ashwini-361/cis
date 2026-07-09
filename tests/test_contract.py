"""Schema + bus contract tests per docs/DATA_CONTRACT.md and docs/ROADMAP.md §1.1."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.bus import EventBus
from app.schema import (
    DecayConfig,
    Event,
    EventEnvelope,
    EventType,
    Evidence,
    ParticipantJoinedPayload,
    ParticipantState,
    RejectedHypothesis,
    ScreenFramePayload,
    SessionEnvelope,
    Verdict,
    WeightTable,
)

# --- schema round-trips ------------------------------------------------------


def test_event_envelope_roundtrip(sample_envelope: EventEnvelope) -> None:
    dumped = sample_envelope.model_dump()
    restored = EventEnvelope.model_validate(dumped)
    assert restored == sample_envelope


def test_event_payload_parses_participant_joined(sample_envelope: EventEnvelope) -> None:
    event = Event(
        type=EventType.PARTICIPANT_JOINED,
        envelope=sample_envelope,
        payload={
            "participant_id": "P1",
            "display_name": "Ashwini",
            "email": "ashwini@gmail.com",
            "join_order": 1,
        },
    )
    parsed = event.parsed_payload()
    assert isinstance(parsed, ParticipantJoinedPayload)
    assert parsed.display_name == "Ashwini"


def test_event_payload_parses_screen_frame_without_participant(
    sample_envelope: EventEnvelope,
) -> None:
    event = Event(
        type=EventType.SCREEN_FRAME,
        envelope=sample_envelope,
        payload={"format": "jpeg", "width": 1920, "height": 1080, "base64_bytes": "xx"},
    )
    parsed = event.parsed_payload()
    assert isinstance(parsed, ScreenFramePayload)
    assert parsed.participant_id is None


def test_evidence_email_match_worked_example(sample_evidence: Evidence) -> None:
    assert sample_evidence.feature == "email_match"
    assert sample_evidence.expires_at is None


def test_evidence_transcript_role_worked_example() -> None:
    evidence = Evidence(
        session_id="sess_1",
        participant_id="P2",
        feature="transcript_role",
        source="transcript_role_analyzer",
        score=0.92,
        weight=0.25,
        reason="Answered 7 of last 8 interviewer questions in Q&A turns",
        ts=143.2,
        expires_at=143.2 + 600,
        supersedes="transcript_role",
    )
    assert evidence.expires_at is not None and evidence.expires_at > evidence.ts
    assert evidence.supersedes == "transcript_role"


def test_participant_state_construction(sample_evidence: Evidence) -> None:
    state = ParticipantState(
        session_id="sess_1",
        participant_id="P1",
        display_name="Ashwini",
        join_ts=0.0,
        raw_evidence=[sample_evidence],
        total_evidence=1,
        analyzer_count=1,
    )
    assert state.raw_evidence[0] == sample_evidence


def test_verdict_decidable_worked_example() -> None:
    verdict = Verdict(
        session_id="sess_1",
        ts=300.4,
        platform="zoom",
        candidate_id="P1",
        candidate_name="Ashwini",
        confidence=0.97,
        runner_up_id="P3",
        runner_up_confidence=0.45,
        margin=0.52,
        is_decision=True,
        reasons=["Email matched calendar metadata (+0.300)"],
        rejected_hypotheses=[
            RejectedHypothesis(
                participant_id="P3",
                display_name="Priya Sharma",
                confidence=0.45,
                top_negative_reasons=["Transcript role strongly indicates interviewer"],
            )
        ],
        analyzer_count=6,
        total_evidence=11,
    )
    assert verdict.is_decision is True
    assert verdict.engine_version == "v1-weighted"


def test_verdict_not_deciding_worked_example() -> None:
    verdict = Verdict(
        session_id="sess_1",
        ts=12.3,
        platform="zoom",
        candidate_id=None,
        candidate_name=None,
        confidence=None,
        runner_up_id="P1",
        runner_up_confidence=0.42,
        margin=None,
        is_decision=False,
        not_deciding_reason="top confidence 0.42 < threshold 0.55",
        reasons=['Top candidate so far: P1 "Ashwini" (0.42)'],
        analyzer_count=4,
        total_evidence=5,
    )
    assert verdict.is_decision is False
    assert verdict.candidate_id is None


def test_session_envelope_construction() -> None:
    session = SessionEnvelope(
        session_id="sess_1",
        platform="mock",
        start_wall_clock="2026-07-09T00:00:00Z",
    )
    assert session.expected_duration_min == 60
    assert session.expected_participants == []


def test_rejected_hypothesis_construction() -> None:
    rejected = RejectedHypothesis(
        participant_id="P2",
        display_name="MacBook Pro",
        confidence=0.10,
        top_negative_reasons=["Display name similarity 5%"],
    )
    assert rejected.confidence == 0.10


# --- frozen / immutability ---------------------------------------------------


def test_models_are_frozen(sample_envelope: EventEnvelope, sample_evidence: Evidence) -> None:
    event = Event(type=EventType.PARTICIPANT_JOINED, envelope=sample_envelope, payload={})
    participant_state = ParticipantState(
        session_id="sess_1", participant_id="P1", display_name="Ashwini", join_ts=0.0
    )
    verdict = Verdict(
        session_id="sess_1",
        ts=0.0,
        platform="mock",
        candidate_id=None,
        candidate_name=None,
        confidence=None,
        runner_up_id=None,
        runner_up_confidence=None,
        margin=None,
        reasons=[],
        is_decision=False,
        analyzer_count=0,
        total_evidence=0,
    )
    rejected = RejectedHypothesis(
        participant_id="P1", display_name="Ashwini", confidence=0.1, top_negative_reasons=[]
    )
    weight_table = WeightTable(
        version="1.0.0",
        fusion_engine="v1-weighted",
        threshold=0.55,
        margin=0.20,
        decay=DecayConfig(),
        weights={"email_match": 0.30},
    )
    session_envelope = SessionEnvelope(
        session_id="sess_1", platform="mock", start_wall_clock="2026-07-09T00:00:00Z"
    )
    joined_payload = ParticipantJoinedPayload(
        participant_id="P1", display_name="Ashwini", join_order=1
    )

    instances = [
        sample_envelope,
        sample_evidence,
        event,
        participant_state,
        verdict,
        rejected,
        weight_table,
        session_envelope,
        joined_payload,
    ]
    for instance in instances:
        first_field = next(iter(type(instance).model_fields))
        with pytest.raises(ValidationError):
            setattr(instance, first_field, getattr(instance, first_field))


# --- Evidence field constraints ----------------------------------------------


def test_evidence_score_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        Evidence(
            session_id="s",
            participant_id="p",
            feature="f",
            source="src",
            score=1.5,
            weight=0.1,
            reason="x",
            ts=0.0,
        )


def test_evidence_weight_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        Evidence(
            session_id="s",
            participant_id="p",
            feature="f",
            source="src",
            score=0.5,
            weight=-0.1,
            reason="x",
            ts=0.0,
        )


def test_evidence_reason_empty_raises() -> None:
    with pytest.raises(ValidationError):
        Evidence(
            session_id="s",
            participant_id="p",
            feature="f",
            source="src",
            score=0.5,
            weight=0.1,
            reason="",
            ts=0.0,
        )


def test_evidence_reason_too_long_raises() -> None:
    with pytest.raises(ValidationError):
        Evidence(
            session_id="s",
            participant_id="p",
            feature="f",
            source="src",
            score=0.5,
            weight=0.1,
            reason="x" * 241,
            ts=0.0,
        )


# --- WeightTable vs. committed weights.json -----------------------------------


def test_weight_table_loads_committed_weights_json(weights_json_path: Path) -> None:
    data = json.loads(weights_json_path.read_text())
    table = WeightTable.model_validate(data)
    assert table.decay.per_feature["name_similarity"] is None
    assert table.decay.per_feature["email_match"] is None
    assert table.weights["email_match"] == 0.30
    assert table.threshold == 0.55
    assert table.margin == 0.20


# --- EventBus -----------------------------------------------------------------


async def test_bus_publish_subscribe_fanout(bus: EventBus, sample_envelope: EventEnvelope) -> None:
    received: list[Event] = []

    async def callback(event: Event) -> None:
        received.append(event)

    bus.subscribe([EventType.PARTICIPANT_JOINED], callback)
    event = Event(type=EventType.PARTICIPANT_JOINED, envelope=sample_envelope, payload={})
    await bus.publish(event)

    for _ in range(100):
        if received:
            break
        await asyncio.sleep(0.01)

    assert received == [event]


async def test_bus_duplicate_source_sequence_dropped(
    bus: EventBus, sample_envelope: EventEnvelope
) -> None:
    received: list[Event] = []

    async def callback(event: Event) -> None:
        received.append(event)

    bus.subscribe([EventType.PARTICIPANT_JOINED], callback)
    event = Event(type=EventType.PARTICIPANT_JOINED, envelope=sample_envelope, payload={})
    await bus.publish(event)
    await bus.publish(event)  # same (source, sequence) -> dropped

    for _ in range(100):
        if received:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)  # allow time for a possible (incorrect) second delivery

    assert len(received) == 1


async def test_bus_per_source_fifo_ordering(bus: EventBus) -> None:
    received: list[int] = []

    async def callback(event: Event) -> None:
        received.append(event.envelope.sequence)

    bus.subscribe([EventType.PARTICIPANT_JOINED], callback)

    events = [
        Event(
            type=EventType.PARTICIPANT_JOINED,
            envelope=EventEnvelope(
                session_id="sess_1",
                ts=float(i),
                wall_clock="2026-07-09T00:00:00Z",
                platform="mock",
                source="mock.replay",
                sequence=i,
            ),
            payload={},
        )
        for i in range(5)
    ]
    for event in events:
        await bus.publish(event)

    for _ in range(100):
        if len(received) == 5:
            break
        await asyncio.sleep(0.01)

    assert received == [0, 1, 2, 3, 4]


async def test_bus_unsubscribe_stops_delivery(
    bus: EventBus, sample_envelope: EventEnvelope
) -> None:
    received: list[Event] = []

    async def callback(event: Event) -> None:
        received.append(event)

    bus.subscribe([EventType.PARTICIPANT_JOINED], callback)
    first = Event(type=EventType.PARTICIPANT_JOINED, envelope=sample_envelope, payload={})
    await bus.publish(first)
    for _ in range(100):
        if received:
            break
        await asyncio.sleep(0.01)
    assert len(received) == 1

    await bus.unsubscribe([EventType.PARTICIPANT_JOINED], callback)
    second_envelope = sample_envelope.model_copy(update={"sequence": 1})
    second = Event(type=EventType.PARTICIPANT_JOINED, envelope=second_envelope, payload={})
    await bus.publish(second)
    await asyncio.sleep(0.05)
    assert len(received) == 1


async def test_bus_no_redis_required() -> None:
    local_bus = EventBus()
    event = Event(
        type=EventType.PARTICIPANT_JOINED,
        envelope=EventEnvelope(
            session_id="sess_1",
            ts=0.0,
            wall_clock="2026-07-09T00:00:00Z",
            platform="mock",
            source="mock.replay",
            sequence=0,
        ),
        payload={},
    )
    await local_bus.publish(event)  # must not raise / attempt network I/O
