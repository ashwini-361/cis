"""VisionAnalyzer tests per docs/SIGNALS.md §8."""

from __future__ import annotations

from app.analyzers.vision import Embedding, VisionAnalyzer
from app.schema import EventType, SessionEnvelope, WeightTable
from tests.test_analyzers.conftest import make_event


class FakeBackend:
    def __init__(self, embeddings: list[Embedding | None]) -> None:
        self._embeddings = list(embeddings)

    def extract_embedding(self, frame_payload: object) -> Embedding | None:
        return self._embeddings.pop(0)


def _frame_event(ts: float, sequence: int, participant_id: str = "P1"):
    return make_event(
        EventType.VIDEO_FRAME,
        ts=ts,
        sequence=sequence,
        payload={
            "participant_id": participant_id,
            "format": "jpeg",
            "width": 100,
            "height": 100,
            "base64_bytes": "xx",
        },
    )


async def test_disabled_by_default_is_a_no_op(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = VisionAnalyzer(backend=FakeBackend([(1.0, 0.0, 0.0)]))
    await analyzer.initialize(weight_table, session_envelope)
    evidence = await analyzer.on_event(_frame_event(0.0, 1))
    assert evidence == []
    tick_evidence = await analyzer.on_tick(10.0)
    assert tick_evidence == []


async def test_first_sighting_seeds_ema_with_full_score(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = VisionAnalyzer(backend=FakeBackend([(1.0, 0.0, 0.0)]), enabled=True)
    await analyzer.initialize(weight_table, session_envelope)
    await analyzer.on_event(_frame_event(0.0, 1))
    evidence = await analyzer.on_tick(1.0)
    assert evidence[0].score == 1.0


async def test_consistent_face_scores_high(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    embeddings: list[Embedding | None] = [(1.0, 0.0, 0.0)] * 5
    analyzer = VisionAnalyzer(backend=FakeBackend(embeddings), enabled=True)
    await analyzer.initialize(weight_table, session_envelope)
    for i in range(5):
        await analyzer.on_event(_frame_event(float(i), i + 1))
    evidence = await analyzer.on_tick(5.0)
    assert evidence[0].score >= 0.85


async def test_sudden_embedding_change_flags_possible_swap(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    # One consistent frame seeds the EMA, then four orthogonal (swapped) frames
    # in a row -- since the EMA only shifts 10% per frame, each post-swap frame
    # still scores near 0 against the slowly-adjusting EMA, driving the 60s
    # window's mean well below the 0.30 swap threshold.
    embeddings: list[Embedding | None] = [(1.0, 0.0, 0.0)] + [(0.0, 1.0, 0.0)] * 4
    analyzer = VisionAnalyzer(backend=FakeBackend(embeddings), enabled=True)
    await analyzer.initialize(weight_table, session_envelope)
    for i in range(5):
        await analyzer.on_event(_frame_event(float(i), i + 1))
    evidence = await analyzer.on_tick(4.0)
    assert evidence[0].score < 0.30
    assert "face swap" in evidence[0].reason


async def test_no_face_in_window_is_silent_not_zero(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = VisionAnalyzer(backend=FakeBackend([(1.0, 0.0, 0.0)]), enabled=True)
    await analyzer.initialize(weight_table, session_envelope)
    await analyzer.on_event(_frame_event(0.0, 1))
    evidence = await analyzer.on_tick(100.0)  # well past the 60s window
    assert evidence == []


async def test_idempotent_replay_does_not_double_count_frame(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    analyzer = VisionAnalyzer(backend=FakeBackend([(1.0, 0.0, 0.0)]), enabled=True)
    await analyzer.initialize(weight_table, session_envelope)
    event = _frame_event(0.0, 1)
    await analyzer.on_event(event)
    await analyzer.on_event(event)
    assert len(analyzer._frame_scores["P1"]) == 1
