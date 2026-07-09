"""TranscriptRoleAnalyzer tests per docs/SIGNALS.md §6, using a fake LLM provider."""

from __future__ import annotations

import json
from typing import Any

from app.analyzers.transcript_role import TranscriptRoleAnalyzer
from app.schema import EventType, SessionEnvelope, WeightTable
from tests.test_analyzers.conftest import make_event


class FakeLLMProvider:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    def complete_json(self, system_prompt: str, user_prompt: str) -> Any:
        self.call_count += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


async def _feed_three_segments(analyzer: TranscriptRoleAnalyzer) -> None:
    segments = [
        ("P3", "Tell me about yourself.", 65.0, 70.0),
        ("P1", "I'm a backend engineer.", 71.0, 90.0),
        ("P3", "Why this company?", 91.5, 93.0),
    ]
    for i, (participant_id, text, start, end) in enumerate(segments):
        await analyzer.on_event(
            make_event(
                EventType.TRANSCRIPT_SEGMENT,
                ts=start,
                sequence=i,
                payload={
                    "participant_id": participant_id,
                    "text": text,
                    "start_sec": start,
                    "end_sec": end,
                },
            )
        )


async def test_emits_evidence_with_at_least_three_segments(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    provider = FakeLLMProvider(
        [[{"participant_id": "P1", "role": "candidate", "confidence": 0.92}]]
    )
    analyzer = TranscriptRoleAnalyzer(provider)
    await analyzer.initialize(weight_table, session_envelope)
    await _feed_three_segments(analyzer)

    evidence = await analyzer.on_tick(93.0)
    assert len(evidence) == 1
    assert evidence[0].participant_id == "P1"
    assert evidence[0].score == 0.92
    assert evidence[0].supersedes == "transcript_role"
    assert evidence[0].expires_at == 93.0 + 600.0


async def test_skips_tick_with_fewer_than_three_segments(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    provider = FakeLLMProvider([[]])
    analyzer = TranscriptRoleAnalyzer(provider)
    await analyzer.initialize(weight_table, session_envelope)
    await analyzer.on_event(
        make_event(
            EventType.TRANSCRIPT_SEGMENT,
            ts=65.0,
            payload={"participant_id": "P1", "text": "hi", "start_sec": 65.0, "end_sec": 66.0},
        )
    )
    evidence = await analyzer.on_tick(66.0)
    assert evidence == []
    assert provider.call_count == 0


async def test_unclear_role_skips_that_participant(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    provider = FakeLLMProvider(
        [
            [
                {"participant_id": "P1", "role": "candidate", "confidence": 0.7},
                {"participant_id": "P3", "role": "unclear", "confidence": 0.0},
            ]
        ]
    )
    analyzer = TranscriptRoleAnalyzer(provider)
    await analyzer.initialize(weight_table, session_envelope)
    await _feed_three_segments(analyzer)

    evidence = await analyzer.on_tick(93.0)
    assert len(evidence) == 1
    assert evidence[0].participant_id == "P1"


async def test_non_candidate_role_is_anti_evidence(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    provider = FakeLLMProvider(
        [[{"participant_id": "P3", "role": "interviewer", "confidence": 0.85}]]
    )
    analyzer = TranscriptRoleAnalyzer(provider)
    await analyzer.initialize(weight_table, session_envelope)
    await _feed_three_segments(analyzer)

    evidence = await analyzer.on_tick(93.0)
    assert evidence[0].score == 0.0


async def test_malformed_json_retries_once_then_skips(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    error = json.JSONDecodeError("bad", "doc", 0)
    provider = FakeLLMProvider([error, error])
    analyzer = TranscriptRoleAnalyzer(provider)
    await analyzer.initialize(weight_table, session_envelope)
    await _feed_three_segments(analyzer)

    evidence = await analyzer.on_tick(93.0)
    assert evidence == []
    assert provider.call_count == 2


async def test_cache_hit_skips_second_llm_call(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    provider = FakeLLMProvider(
        [[{"participant_id": "P1", "role": "candidate", "confidence": 0.8}]]
    )
    analyzer = TranscriptRoleAnalyzer(provider)
    await analyzer.initialize(weight_table, session_envelope)
    await _feed_three_segments(analyzer)

    first = await analyzer.on_tick(93.0)
    second = await analyzer.on_tick(94.0)  # same window content, still within 60s
    assert provider.call_count == 1
    assert first[0].score == second[0].score


async def test_idempotent_replay_does_not_double_count_segment(
    weight_table: WeightTable, session_envelope: SessionEnvelope
) -> None:
    provider = FakeLLMProvider([])
    analyzer = TranscriptRoleAnalyzer(provider)
    await analyzer.initialize(weight_table, session_envelope)
    segment_event = make_event(
        EventType.TRANSCRIPT_SEGMENT,
        ts=65.0,
        sequence=1,
        payload={"participant_id": "P1", "text": "hi", "start_sec": 65.0, "end_sec": 66.0},
    )
    first = await analyzer.on_event(segment_event)
    second = await analyzer.on_event(segment_event)
    assert first == []
    assert second == []
    assert len(analyzer._segments) == 1
