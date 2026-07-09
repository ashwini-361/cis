"""JoinOrderAnalyzer tests per docs/SIGNALS.md §3."""

from __future__ import annotations

import pytest

from app.analyzers.join_order import JoinOrderAnalyzer
from app.schema import EventType, SessionEnvelope, WeightTable
from tests.test_analyzers.conftest import make_event


async def _new_analyzer(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> JoinOrderAnalyzer:
    analyzer = JoinOrderAnalyzer()
    await analyzer.initialize(weight_table, session_envelope)
    await analyzer.on_event(
        make_event(EventType.SESSION_START, ts=0.0, payload={"expected_participants": []})
    )
    return analyzer


async def test_order_one_base_score(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _new_analyzer(weight_table, session_envelope)
    e = make_event(
        EventType.PARTICIPANT_JOINED,
        ts=1.1,
        sequence=1,
        payload={"participant_id": "P1", "display_name": "Ashwini", "join_order": 1},
    )
    evidence = await analyzer.on_event(e)
    assert evidence[0].score == 0.60


async def test_order_two_base_score(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _new_analyzer(weight_table, session_envelope)
    e = make_event(
        EventType.PARTICIPANT_JOINED,
        ts=12.7,
        sequence=1,
        payload={"participant_id": "P2", "display_name": "MacBook Pro", "join_order": 2},
    )
    evidence = await analyzer.on_event(e)
    assert evidence[0].score == 0.30


async def test_order_three_or_later_base_score(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _new_analyzer(weight_table, session_envelope)
    e = make_event(
        EventType.PARTICIPANT_JOINED,
        ts=30.4,
        sequence=1,
        payload={"participant_id": "P3", "display_name": "Priya Sharma", "join_order": 3},
    )
    evidence = await analyzer.on_event(e)
    assert evidence[0].score == 0.10


async def test_known_interviewer_gets_anti_evidence_regardless_of_order(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _new_analyzer(weight_table, session_envelope)
    await analyzer.on_event(
        make_event(
            EventType.METADATA_INTERVIEWERS,
            ts=0.0,
            sequence=1,
            payload={"names": ["Priya Sharma"], "emails": None},
        )
    )
    e = make_event(
        EventType.PARTICIPANT_JOINED,
        ts=1.0,
        sequence=2,
        payload={"participant_id": "P3", "display_name": "Priya Sharma", "join_order": 1},
    )
    evidence = await analyzer.on_event(e)
    assert evidence[0].score == 0.10


async def test_non_interviewer_gets_boost_once_interviewers_known(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _new_analyzer(weight_table, session_envelope)
    await analyzer.on_event(
        make_event(
            EventType.METADATA_INTERVIEWERS,
            ts=0.0,
            sequence=1,
            payload={"names": ["Priya Sharma"], "emails": None},
        )
    )
    e = make_event(
        EventType.PARTICIPANT_JOINED,
        ts=30.4,
        sequence=2,
        payload={"participant_id": "P3", "display_name": "Priya Sharma", "join_order": 3},
    )
    # Priya IS the interviewer -> anti-evidence, not boosted
    evidence = await analyzer.on_event(e)
    assert evidence[0].score == 0.10

    e2 = make_event(
        EventType.PARTICIPANT_JOINED,
        ts=31.0,
        sequence=3,
        payload={"participant_id": "P1", "display_name": "Ashwini", "join_order": 4},
    )
    evidence2 = await analyzer.on_event(e2)
    # Not the interviewer, order>=3 base 0.10 + boost 0.20
    assert evidence2[0].score == pytest.approx(0.30)


async def test_refires_once_60s_after_session_start(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _new_analyzer(weight_table, session_envelope)
    await analyzer.on_event(
        make_event(
            EventType.PARTICIPANT_JOINED,
            ts=1.1,
            sequence=1,
            payload={"participant_id": "P1", "display_name": "Ashwini", "join_order": 1},
        )
    )

    before = await analyzer.on_tick(30.0)
    assert before == []

    after = await analyzer.on_tick(65.0)
    assert len(after) == 1
    assert after[0].supersedes == "join_order"

    again = await analyzer.on_tick(70.0)
    assert again == []
