"""WebcamAnalyzer tests per docs/SIGNALS.md §4."""

from __future__ import annotations

import pytest

from app.analyzers.webcam import WebcamAnalyzer
from app.schema import EventType, SessionEnvelope, WeightTable
from tests.test_analyzers.conftest import make_event


async def _joined_analyzer(
    weight_table: WeightTable, session_envelope: SessionEnvelope, join_ts: float = 0.0
) -> WebcamAnalyzer:
    analyzer = WebcamAnalyzer()
    await analyzer.initialize(weight_table, session_envelope)
    await analyzer.on_event(
        make_event(
            EventType.PARTICIPANT_JOINED,
            ts=join_ts,
            payload={"participant_id": "P1", "display_name": "Ashwini", "join_order": 1},
        )
    )
    return analyzer


async def test_never_on_scores_zero(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _joined_analyzer(weight_table, session_envelope)
    evidence = await analyzer.on_tick(100.0)
    assert evidence[0].score == 0.0
    assert evidence[0].reason == "Webcam never active"


async def test_ratio_to_score_table_points(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    # present_sec = 100; drive on_sec to hit ratio 0.30, 0.55, 0.80, 1.00
    for ratio, expected_score in [(0.30, 0.0), (0.55, 0.50), (0.80, 1.0), (1.00, 1.0)]:
        analyzer = await _joined_analyzer(weight_table, session_envelope)
        await analyzer.on_event(
            make_event(
                EventType.WEBCAM_ON, ts=0.0, sequence=1, payload={"participant_id": "P1"}
            )
        )
        await analyzer.on_event(
            make_event(
                EventType.WEBCAM_OFF,
                ts=ratio * 100.0,
                sequence=2,
                payload={"participant_id": "P1"},
            )
        )
        evidence = await analyzer.on_tick(100.0)
        assert evidence[0].score == pytest.approx(expected_score, abs=1e-6)


async def test_on_tick_reemits_with_60s_expiry(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _joined_analyzer(weight_table, session_envelope)
    evidence = await analyzer.on_tick(50.0)
    assert evidence[0].expires_at == 50.0 + 60.0
    assert evidence[0].supersedes == "webcam_usage"


async def test_webcam_still_on_counts_toward_ratio(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = await _joined_analyzer(weight_table, session_envelope, join_ts=0.0)
    await analyzer.on_event(
        make_event(EventType.WEBCAM_ON, ts=20.0, sequence=1, payload={"participant_id": "P1"})
    )
    # still on at tick time: present_sec=100, on_sec=100-20=80 -> ratio 0.80 -> score 1.0
    evidence = await analyzer.on_tick(100.0)
    assert evidence[0].score == pytest.approx(1.0)

