"""ScreenShareAnalyzer tests per docs/SIGNALS.md §9."""

from __future__ import annotations

from app.analyzers.screen_share import ScreenShareAnalyzer
from app.schema import EventType, SessionEnvelope, WeightTable
from tests.test_analyzers.conftest import make_event


async def test_start_frames_stop_emits_one_evidence_using_injected_classifier(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    def fake_classify(frames: list[object]) -> tuple[str, float]:
        return ("code editor / IDE", 0.90)

    analyzer = ScreenShareAnalyzer(classify=fake_classify)
    await analyzer.initialize(weight_table, session_envelope)

    await analyzer.on_event(
        make_event(
            EventType.SCREEN_SHARE_START,
            ts=120.0,
            sequence=1,
            payload={"participant_id": "P1", "content_label": "code editor / IDE"},
        )
    )
    await analyzer.on_event(
        make_event(
            EventType.SCREEN_FRAME,
            ts=122.0,
            sequence=2,
            payload={
                "participant_id": "P1",
                "format": "jpeg",
                "width": 100,
                "height": 100,
                "base64_bytes": "xx",
            },
        )
    )
    evidence = await analyzer.on_event(
        make_event(
            EventType.SCREEN_SHARE_STOP,
            ts=240.0,
            sequence=3,
            payload={"participant_id": "P1"},
        )
    )

    assert len(evidence) == 1
    assert evidence[0].score == 0.90
    assert "code editor / IDE" in evidence[0].reason
    assert evidence[0].expires_at == 240.0 + 300.0
    assert evidence[0].supersedes == "screen_share_content"


async def test_default_stub_classifier_used_when_none_injected(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = ScreenShareAnalyzer()
    await analyzer.initialize(weight_table, session_envelope)

    await analyzer.on_event(
        make_event(
            EventType.SCREEN_SHARE_START,
            ts=0.0,
            sequence=1,
            payload={"participant_id": "P1"},
        )
    )
    evidence = await analyzer.on_event(
        make_event(
            EventType.SCREEN_SHARE_STOP,
            ts=30.0,
            sequence=2,
            payload={"participant_id": "P1"},
        )
    )
    assert evidence[0].score == 0.20


async def test_frames_outside_active_share_are_ignored(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = ScreenShareAnalyzer()
    await analyzer.initialize(weight_table, session_envelope)

    evidence = await analyzer.on_event(
        make_event(
            EventType.SCREEN_FRAME,
            ts=5.0,
            payload={
                "participant_id": "P1",
                "format": "jpeg",
                "width": 100,
                "height": 100,
                "base64_bytes": "xx",
            },
        )
    )
    assert evidence == []
    assert analyzer._active == {}


async def test_stop_without_start_emits_nothing(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = ScreenShareAnalyzer()
    await analyzer.initialize(weight_table, session_envelope)

    evidence = await analyzer.on_event(
        make_event(
            EventType.SCREEN_SHARE_STOP,
            ts=5.0,
            payload={"participant_id": "P1"},
        )
    )
    assert evidence == []
