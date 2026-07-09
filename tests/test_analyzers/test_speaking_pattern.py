"""SpeakingPatternAnalyzer tests per docs/SIGNALS.md §5."""

from __future__ import annotations

from app.analyzers.speaking_pattern import SpeakingPatternAnalyzer
from app.schema import EventType, SessionEnvelope, WeightTable
from tests.test_analyzers.conftest import make_event

_QA_SEGMENTS = [
    ("P3", "Hi Ashwini, thanks for jumping on. Tell me about yourself.", 65.0, 70.0),
    ("P1", "Sure. I'm a backend engineer...", 71.0, 90.0),
    ("P3", "Great. Why this company?", 91.5, 93.0),
    ("P1", "I'm drawn to the focus on fraud detection...", 93.5, 110.0),
]


async def _analyzer_with_roster(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> SpeakingPatternAnalyzer:
    analyzer = SpeakingPatternAnalyzer()
    await analyzer.initialize(weight_table, session_envelope)
    await analyzer.on_event(
        make_event(
            EventType.PARTICIPANT_JOINED,
            ts=1.1,
            sequence=1,
            payload={"participant_id": "P1", "display_name": "Ashwini", "join_order": 1},
        )
    )
    await analyzer.on_event(
        make_event(
            EventType.PARTICIPANT_JOINED,
            ts=30.4,
            sequence=2,
            payload={"participant_id": "P3", "display_name": "Priya Sharma", "join_order": 2},
        )
    )
    await analyzer.on_event(
        make_event(
            EventType.METADATA_INTERVIEWERS,
            ts=0.0,
            sequence=3,
            payload={"names": ["Priya Sharma"], "emails": None},
        )
    )
    return analyzer


async def _feed_segments(
    analyzer: SpeakingPatternAnalyzer, segments: list[tuple[str, str, float, float]]
) -> None:
    for i, (participant_id, text, start, end) in enumerate(segments):
        await analyzer.on_event(
            make_event(
                EventType.TRANSCRIPT_SEGMENT,
                ts=start,
                sequence=10 + i,
                payload={
                    "participant_id": participant_id,
                    "text": text,
                    "start_sec": start,
                    "end_sec": end,
                },
            )
        )


async def test_interviewer_to_candidate_alternation_scores_higher(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _analyzer_with_roster(weight_table, session_envelope)
    await _feed_segments(analyzer, _QA_SEGMENTS)

    evidence = await analyzer.on_tick(110.0)
    scores = {ev.participant_id: ev.score for ev in evidence}
    assert scores["P1"] > scores["P3"]


async def test_interviewer_gets_no_answered_credit(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _analyzer_with_roster(weight_table, session_envelope)
    await _feed_segments(analyzer, _QA_SEGMENTS)

    evidence = await analyzer.on_tick(110.0)
    scores = {ev.participant_id: ev.score for ev in evidence}
    assert scores["P3"] == 0.0


async def test_global_penalty_for_interviewer_to_observer_transition(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _analyzer_with_roster(weight_table, session_envelope)
    await analyzer.on_event(
        make_event(
            EventType.PARTICIPANT_JOINED,
            ts=5.0,
            sequence=4,
            payload={"participant_id": "P2", "display_name": "Alice", "join_order": 3},
        )
    )
    # Interviewer (P3) talks to observer (P2) instead of candidate (P1).
    segments = [
        ("P1", "Hi everyone.", 0.0, 2.0),
        ("P3", "Alice, any questions before we start?", 3.0, 5.0),
        ("P2", "No, all good.", 5.5, 6.0),
    ]
    await _feed_segments(analyzer, segments)

    evidence = await analyzer.on_tick(10.0)
    p1_score = next(ev.score for ev in evidence if ev.participant_id == "P1")
    assert p1_score == 0.0  # P1 got no credit and took the -0.2 dilution penalty


async def test_idempotent_replay_does_not_double_count_segment(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _analyzer_with_roster(weight_table, session_envelope)
    segment_event = make_event(
        EventType.TRANSCRIPT_SEGMENT,
        ts=65.0,
        sequence=10,
        payload={
            "participant_id": "P3",
            "text": "Hi Ashwini",
            "start_sec": 65.0,
            "end_sec": 70.0,
        },
    )
    first = await analyzer.on_event(segment_event)
    second = await analyzer.on_event(segment_event)
    assert first == []
    assert second == []
    assert len(analyzer._segments) == 1
