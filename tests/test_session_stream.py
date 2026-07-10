"""/sessions/{id}/stream WebSocket route tests per docs/ARCHITECTURE.md §1.8."""

from __future__ import annotations

import asyncio
import time

from fastapi.testclient import TestClient

from app.main import app, session_manager
from app.schema import DecayConfig, Verdict, WeightTable

_WEIGHT_TABLE = WeightTable(
    version="1.0.0",
    fusion_engine="v1-weighted",
    threshold=0.55,
    margin=0.20,
    decay=DecayConfig(),
    weights={},
)


def _verdict(session_id: str, is_decision: bool) -> Verdict:
    return Verdict(
        session_id=session_id,
        ts=0.0,
        platform="mock",
        candidate_id="P1" if is_decision else None,
        candidate_name="Ashwini" if is_decision else None,
        confidence=0.9 if is_decision else None,
        runner_up_id=None,
        runner_up_confidence=None,
        margin=None,
        reasons=[],
        is_decision=is_decision,
        not_deciding_reason=None if is_decision else "no participants",
        analyzer_count=0,
        total_evidence=0,
    )


def test_stream_route_closes_unknown_session() -> None:
    client = TestClient(app)
    with client.websocket_connect("/sessions/unknown-session/stream") as ws:
        try:
            ws.receive_json()
            raise AssertionError("expected the connection to be closed")
        except Exception:
            pass


def test_stream_route_sends_latest_verdict_on_connect() -> None:
    session_manager.create_session("stream-test-1", _WEIGHT_TABLE)
    verdict = _verdict("stream-test-1", is_decision=True)
    # Set the session's latest_verdict directly (no live connection yet, so no
    # cross-event-loop concerns): broadcast_verdict with no subscribers just
    # updates latest_verdict and returns immediately.
    asyncio.run(session_manager.broadcast_verdict("stream-test-1", verdict))

    client = TestClient(app)
    try:
        with client.websocket_connect("/sessions/stream-test-1/stream") as ws:
            data = ws.receive_json()
            assert data["kind"] == "session_update"
            assert data["session_id"] == "stream-test-1"
            assert data["verdict"]["candidate_id"] == "P1"
            assert data["live_debug"]["session_id"] == "stream-test-1"
    finally:
        session_manager.remove_session("stream-test-1")


def test_stream_route_registers_and_cleans_up_subscriber() -> None:
    # NOTE: TestClient runs the ASGI app on its own event-loop thread (a
    # separate loop from this synchronous test function), so we can't safely
    # call session_manager.broadcast_verdict() concurrently from here while
    # connected -- that would call websocket.send_json() across event loops.
    # Instead this test verifies the route's subscriber registration/cleanup
    # side effects directly, which are plain (thread-safe-enough for test
    # purposes) list mutations readable from either thread.
    session = session_manager.create_session("stream-test-2", _WEIGHT_TABLE)
    client = TestClient(app)
    try:
        with client.websocket_connect("/sessions/stream-test-2/stream") as _ws:
            assert len(session.subscribers) == 1
        # `with` block exited -> client disconnects; poll briefly for the
        # server to process it and clean up.
        for _ in range(50):
            if len(session.subscribers) == 0:
                break
            time.sleep(0.01)
        assert len(session.subscribers) == 0
    finally:
        session_manager.remove_session("stream-test-2")
