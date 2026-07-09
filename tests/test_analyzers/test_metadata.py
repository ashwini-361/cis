"""MetadataAnalyzer tests per docs/SIGNALS.md §1-2 and docs/ROADMAP.md §4.3."""

from __future__ import annotations

from app.analyzers.metadata import MetadataAnalyzer
from app.schema import EventType, SessionEnvelope, WeightTable
from tests.test_analyzers.conftest import make_event


async def _make_analyzer(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> MetadataAnalyzer:
    analyzer = MetadataAnalyzer()
    await analyzer.initialize(weight_table, session_envelope)
    await analyzer.on_event(
        make_event(
            EventType.METADATA_CANDIDATE,
            ts=0.0,
            payload={"name": "Ashwini Kumar", "email": "ashwini.kumar@gmail.com"},
        )
    )
    return analyzer


async def test_email_match(weight_table: WeightTable, session_envelope: SessionEnvelope) -> None:
    analyzer = await _make_analyzer(weight_table, session_envelope)
    e = make_event(
        EventType.PARTICIPANT_JOINED,
        ts=1.1,
        sequence=1,
        payload={
            "participant_id": "P1",
            "display_name": "Ashwini",
            "email": "ashwini.kumar@gmail.com",
            "join_order": 1,
        },
    )
    evidence = await analyzer.on_event(e)
    assert any(ev.feature == "email_match" and ev.score == 1.0 for ev in evidence)


async def test_email_mismatch(weight_table: WeightTable, session_envelope: SessionEnvelope) -> None:
    analyzer = await _make_analyzer(weight_table, session_envelope)
    e = make_event(
        EventType.PARTICIPANT_JOINED,
        ts=1.1,
        sequence=1,
        payload={
            "participant_id": "P1",
            "display_name": "Ashwini",
            "email": "someone.else@gmail.com",
            "join_order": 1,
        },
    )
    evidence = await analyzer.on_event(e)
    assert any(ev.feature == "email_match" and ev.score == 0.0 for ev in evidence)


async def test_name_similarity_exact_match(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _make_analyzer(weight_table, session_envelope)
    e = make_event(
        EventType.PARTICIPANT_JOINED,
        ts=1.1,
        sequence=1,
        payload={"participant_id": "P1", "display_name": "Ashwini Kumar", "join_order": 1},
    )
    evidence = await analyzer.on_event(e)
    name_ev = next(ev for ev in evidence if ev.feature == "name_similarity")
    assert name_ev.score == 1.0


async def test_name_similarity_device_name_scores_zero(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _make_analyzer(weight_table, session_envelope)
    e = make_event(
        EventType.PARTICIPANT_JOINED,
        ts=1.1,
        sequence=1,
        payload={"participant_id": "P2", "display_name": "MacBook Pro", "join_order": 2},
    )
    evidence = await analyzer.on_event(e)
    name_ev = next(ev for ev in evidence if ev.feature == "name_similarity")
    assert name_ev.score == 0.0
    assert "device name" in name_ev.reason


async def test_no_evidence_when_candidate_name_missing(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = MetadataAnalyzer()
    await analyzer.initialize(weight_table, session_envelope)
    e = make_event(
        EventType.PARTICIPANT_JOINED,
        ts=1.1,
        payload={"participant_id": "P1", "display_name": "Ashwini Kumar", "join_order": 1},
    )
    evidence = await analyzer.on_event(e)
    assert evidence == []


async def test_rename_triggers_new_name_similarity_evidence(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _make_analyzer(weight_table, session_envelope)
    joined = make_event(
        EventType.PARTICIPANT_JOINED,
        ts=1.1,
        sequence=1,
        payload={"participant_id": "P1", "display_name": "Ashwini Kumar", "join_order": 1},
    )
    await analyzer.on_event(joined)

    renamed = make_event(
        EventType.PARTICIPANT_RENAMED,
        ts=200.0,
        sequence=2,
        payload={"participant_id": "P1", "old_name": "Ashwini Kumar", "new_name": "MacBook"},
    )
    evidence = await analyzer.on_event(renamed)
    name_ev = next(ev for ev in evidence if ev.feature == "name_similarity")
    assert name_ev.supersedes == "name_similarity"
    assert name_ev.score == 0.0


async def test_idempotent_replay_emits_nothing_new(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _make_analyzer(weight_table, session_envelope)
    e = make_event(
        EventType.PARTICIPANT_JOINED,
        ts=1.1,
        sequence=1,
        payload={
            "participant_id": "P1",
            "display_name": "Ashwini",
            "email": "ashwini.kumar@gmail.com",
            "join_order": 1,
        },
    )
    first = await analyzer.on_event(e)
    second = await analyzer.on_event(e)
    assert len(first) > 0
    assert second == []
