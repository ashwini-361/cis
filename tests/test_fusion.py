"""Fusion math + ticker tests per docs/ROADMAP.md §3.1."""

from __future__ import annotations

import asyncio

import pytest

from app.explain.generator import Explainer
from app.fusion.engine import apply_supersedes, decide, fuse
from app.realtime.ticker import ticker
from app.schema import Evidence, ParticipantState, RejectedHypothesis, Verdict
from app.store.state import ParticipantStateStore


def test_fuse_cold_start_returns_zero() -> None:
    assert fuse([], t=0.0) == 0.0


def test_fuse_single_sticky_evidence() -> None:
    evidence = Evidence(
        session_id="s",
        participant_id="p",
        feature="email_match",
        source="src",
        score=0.8,
        weight=0.3,
        reason="matched",
        ts=0.0,
        expires_at=None,
    )
    assert fuse([evidence], t=100.0) == pytest.approx(0.8)


def test_fuse_decay_over_time() -> None:
    # A single evidence term always normalizes back to its own score regardless
    # of decay (decay appears in both numerator and denominator and cancels).
    # Decay is only observable relative to a second, non-decaying term.
    half_life = 300.0
    sticky = Evidence(
        session_id="s",
        participant_id="p",
        feature="email_match",
        source="src",
        score=0.0,
        weight=0.30,
        reason="baseline",
        ts=0.0,
        expires_at=None,
    )
    decaying = Evidence(
        session_id="s",
        participant_id="p",
        feature="transcript_role",
        source="src",
        score=1.0,
        weight=0.30,
        reason="answered",
        ts=0.0,
        expires_at=half_life,
    )
    assert fuse([sticky, decaying], t=0.0) == pytest.approx(0.5)
    assert fuse([sticky, decaying], t=half_life * 10) == pytest.approx(0.0, abs=1e-3)


def test_fuse_multiple_evidence_weighted_average() -> None:
    e1 = Evidence(
        session_id="s",
        participant_id="p",
        feature="email_match",
        source="src",
        score=1.0,
        weight=0.30,
        reason="matched",
        ts=0.0,
        expires_at=None,
    )
    e2 = Evidence(
        session_id="s",
        participant_id="p",
        feature="join_order",
        source="src",
        score=0.5,
        weight=0.05,
        reason="joined first",
        ts=0.0,
        expires_at=None,
    )
    expected = (0.30 * 1.0 * 1.0 + 0.05 * 0.5 * 1.0) / (0.30 * 1.0 + 0.05 * 1.0)
    assert fuse([e1, e2], t=0.0) == pytest.approx(expected)


def test_apply_supersedes_drops_older_same_participant_feature() -> None:
    old = Evidence(
        session_id="s",
        participant_id="P1",
        feature="webcam_usage",
        source="src",
        score=0.9,
        weight=0.05,
        reason="on",
        ts=0.0,
        expires_at=60.0,
    )
    new = Evidence(
        session_id="s",
        participant_id="P1",
        feature="webcam_usage",
        source="src",
        score=1.0,
        weight=0.05,
        reason="still on",
        ts=60.0,
        expires_at=120.0,
        supersedes="webcam_usage",
    )
    other_participant = Evidence(
        session_id="s",
        participant_id="P2",
        feature="webcam_usage",
        source="src",
        score=0.2,
        weight=0.05,
        reason="off",
        ts=0.0,
        expires_at=60.0,
    )
    result = apply_supersedes([old, new, other_participant])
    assert old not in result
    assert new in result
    assert other_participant in result


def test_explainer_render_top_reasons_and_rejected_hypothesis() -> None:
    top_evidence = [
        Evidence(
            session_id="s", participant_id="P1", feature="email_match", source="metadata_analyzer",
            score=1.0, weight=0.30, reason="Email matched calendar metadata", ts=0.0,
        ),
        Evidence(
            session_id="s", participant_id="P1", feature="join_order", source="join_order_analyzer",
            score=0.5, weight=0.05, reason="Joined first", ts=0.0,
        ),
        Evidence(
            session_id="s", participant_id="P1", feature="webcam_usage", source="webcam_analyzer",
            score=0.0, weight=0.05, reason="Webcam never active", ts=0.0,
        ),
    ]
    top_state = ParticipantState(
        session_id="s", participant_id="P1", display_name="Ashwini", join_ts=0.0,
        confidence=0.9, raw_evidence=top_evidence,
    )
    runner_evidence = [
        Evidence(
            session_id="s", participant_id="P3", feature="transcript_role",
            source="transcript_role_analyzer", score=0.1, weight=0.25,
            reason="Transcript indicates interviewer", ts=0.0,
        ),
    ]
    runner_state = ParticipantState(
        session_id="s", participant_id="P3", display_name="Priya", join_ts=0.0,
        confidence=0.2, raw_evidence=runner_evidence,
    )

    reasons, rejected = Explainer().render(top_state, runner_state)

    assert reasons[0] == "Email matched calendar metadata (+0.300)"
    # zero-contribution evidence is excluded
    assert all("Webcam never active" not in r for r in reasons)
    assert rejected == [
        RejectedHypothesis(
            participant_id="P3",
            display_name="Priya",
            confidence=0.2,
            top_negative_reasons=["Transcript indicates interviewer"],
        )
    ]


def test_explainer_render_no_runner_up() -> None:
    top_state = ParticipantState(
        session_id="s", participant_id="P1", display_name="Ashwini", join_ts=0.0, confidence=0.9,
    )
    reasons, rejected = Explainer().render(top_state, None)
    assert reasons == []
    assert rejected == []


def test_decide_no_participants_returns_not_deciding() -> None:
    verdict = decide("sess_1", "mock", [], t=0.0, explainer=Explainer())
    assert verdict.is_decision is False
    assert verdict.not_deciding_reason == "no participants"
    assert verdict.candidate_id is None


def test_decide_below_threshold_returns_not_deciding() -> None:
    state = ParticipantState(
        session_id="sess_1", participant_id="P1", display_name="Ashwini", join_ts=0.0,
        confidence=0.42,
    )
    verdict = decide("sess_1", "mock", [state], t=12.3, explainer=Explainer())
    assert verdict.is_decision is False
    assert "threshold" in verdict.not_deciding_reason
    assert verdict.candidate_id is None


def test_decide_margin_too_small_returns_not_deciding() -> None:
    top = ParticipantState(
        session_id="sess_1", participant_id="P1", display_name="Ashwini", join_ts=0.0,
        confidence=0.60,
    )
    runner = ParticipantState(
        session_id="sess_1", participant_id="P3", display_name="Priya", join_ts=0.0,
        confidence=0.55,
    )
    verdict = decide("sess_1", "mock", [top, runner], t=0.0, explainer=Explainer())
    assert verdict.is_decision is False
    assert "margin" in verdict.not_deciding_reason


def test_decide_decidable_verdict_uses_explainer() -> None:
    top_evidence = [
        Evidence(
            session_id="sess_1", participant_id="P1", feature="email_match",
            source="metadata_analyzer", score=1.0, weight=0.30,
            reason="Email matched calendar metadata", ts=0.0,
        ),
    ]
    top = ParticipantState(
        session_id="sess_1", participant_id="P1", display_name="Ashwini", join_ts=0.0,
        confidence=0.97, raw_evidence=top_evidence,
    )
    runner = ParticipantState(
        session_id="sess_1", participant_id="P3", display_name="Priya", join_ts=0.0,
        confidence=0.45,
    )
    verdict = decide("sess_1", "zoom", [top, runner], t=300.4, explainer=Explainer())

    assert verdict.is_decision is True
    assert verdict.candidate_id == "P1"
    assert verdict.candidate_name == "Ashwini"
    assert verdict.confidence == pytest.approx(0.97)
    assert verdict.runner_up_id == "P3"
    assert verdict.margin == pytest.approx(0.52)
    assert verdict.reasons == ["Email matched calendar metadata (+0.300)"]
    assert len(verdict.rejected_hypotheses) == 1
    assert verdict.analyzer_count == 1
    assert verdict.total_evidence == 1


async def test_participant_state_store_in_memory_roundtrip() -> None:
    store = ParticipantStateStore()
    state = ParticipantState(
        session_id="sess_1", participant_id="P1", display_name="Ashwini", join_ts=0.0
    )
    assert await store.get("sess_1", "P1") is None
    await store.set(state)
    fetched = await store.get("sess_1", "P1")
    assert fetched == state
    all_states = await store.get_all("sess_1")
    assert all_states == [state]


async def test_ticker_recomputes_on_each_tick() -> None:
    call_count = 0
    clock_value = 0.0
    stop_event = asyncio.Event()

    def clock() -> float:
        return clock_value

    async def sleep_fn(interval: float) -> None:
        nonlocal call_count, clock_value
        call_count += 1
        clock_value += interval
        if call_count >= 3:
            stop_event.set()

    evidence = Evidence(
        session_id="sess_1",
        participant_id="P1",
        feature="email_match",
        source="metadata_analyzer",
        score=1.0,
        weight=0.30,
        reason="matched",
        ts=0.0,
        expires_at=None,
    )

    async def get_evidences(participant_id: str) -> list[Evidence]:
        return [evidence]

    broadcast_calls: list[Verdict] = []

    async def broadcast(verdict: Verdict) -> None:
        broadcast_calls.append(verdict)

    state_store = ParticipantStateStore()
    await ticker(
        session_id="sess_1",
        platform="mock",
        participant_ids=["P1"],
        get_evidences=get_evidences,
        state_store=state_store,
        stop_event=stop_event,
        explainer=Explainer(),
        broadcast=broadcast,
        clock=clock,
        sleep_fn=sleep_fn,
        interval=5.0,
    )

    assert call_count == 3
    state = await state_store.get("sess_1", "P1")
    assert state is not None
    assert state.confidence == pytest.approx(fuse([evidence], clock_value))
    assert state.last_recompute_ts == clock_value
    assert state.total_evidence == 1

    assert len(broadcast_calls) == 3
    assert broadcast_calls[-1].session_id == "sess_1"
