"""Fusion math + ticker tests per docs/ROADMAP.md §3.1."""

from __future__ import annotations

import asyncio

import pytest

from app.fusion.engine import apply_supersedes, fuse
from app.realtime.ticker import ticker
from app.schema import Evidence, ParticipantState
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

    state_store = ParticipantStateStore()
    await ticker(
        session_id="sess_1",
        participant_ids=["P1"],
        get_evidences=get_evidences,
        state_store=state_store,
        stop_event=stop_event,
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
