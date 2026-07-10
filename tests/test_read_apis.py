"""Tests for session read endpoints (/transcript, /roles, /live-debug)."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.main import app, session_manager
from app.schema import DecayConfig, ParticipantState, WeightTable

_WEIGHT_TABLE = WeightTable(
    version="1.0.0",
    fusion_engine="v1-weighted",
    threshold=0.55,
    margin=0.20,
    decay=DecayConfig(),
    weights={},
)


def test_get_transcript_and_roles_endpoints() -> None:
    session_id = "read-api-test-1"
    session = session_manager.create_session(session_id, _WEIGHT_TABLE)

    try:
        state = ParticipantState(
            session_id=session_id,
            participant_id="p1",
            display_name="Alice",
            join_ts=1.0,
            role="candidate",
            confidence=0.95,
        )
        asyncio.run(session.state_store.set(state))

        # Add transcript segments
        session.transcript_store.add_segment(
            session_id=session_id,
            participant_id="p1",
            speaker_name="Alice",
            text="Hello world",
            start_sec=1.0,
            end_sec=2.5,
            source="extension",
        )

        client = TestClient(app)

        # Test GET /transcript
        resp_transcript = client.get(f"/sessions/{session_id}/transcript")
        assert resp_transcript.status_code == 200
        data_transcript = resp_transcript.json()
        assert data_transcript["session_id"] == session_id
        assert len(data_transcript["segments"]) == 1
        assert data_transcript["segments"][0]["text"] == "Hello world"
        assert data_transcript["segments"][0]["participant_id"] == "p1"

        # Test GET /roles
        resp_roles = client.get(f"/sessions/{session_id}/roles")
        assert resp_roles.status_code == 200
        data_roles = resp_roles.json()
        assert data_roles["session_id"] == session_id
        assert len(data_roles["participants"]) == 1
        assert data_roles["participants"][0]["display_name"] == "Alice"
        assert data_roles["participants"][0]["role"] == "candidate"

        # Test GET /live-debug extended fields
        resp_debug = client.get(f"/sessions/{session_id}/live-debug")
        assert resp_debug.status_code == 200
        data_debug = resp_debug.json()
        assert "transcript_coverage" in data_debug
        assert data_debug["transcript_coverage"]["total_segments"] == 1
        assert "role_summary" in data_debug
        assert data_debug["role_summary"]["total_participants"] == 1
        assert "per_participant_mode" in data_debug
        assert data_debug["per_participant_mode"] is True

    finally:
        session_manager.remove_session(session_id)


def test_read_apis_unknown_session_returns_404() -> None:
    client = TestClient(app)
    assert client.get("/sessions/unknown-123/transcript").status_code == 404
    assert client.get("/sessions/unknown-123/roles").status_code == 404
    assert client.get("/sessions/unknown-123/live-debug").status_code == 404
