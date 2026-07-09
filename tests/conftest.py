"""Shared pytest fixtures for the Phase 1 contract test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.bus import EventBus
from app.schema import EventEnvelope, Evidence


@pytest.fixture
def sample_envelope() -> EventEnvelope:
    return EventEnvelope(
        session_id="sess_1",
        ts=0.2,
        wall_clock="2026-07-09T00:00:00Z",
        platform="mock",
        source="mock.replay",
        sequence=0,
    )


@pytest.fixture
def sample_evidence() -> Evidence:
    return Evidence(
        session_id="sess_1",
        participant_id="P1",
        feature="email_match",
        source="metadata_analyzer",
        score=1.0,
        weight=0.30,
        reason="Participant's email ashwini@gmail.com matched calendar metadata exactly",
        ts=0.2,
        expires_at=None,
        supersedes=None,
    )


@pytest.fixture
def weights_json_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "weights" / "weights.json"


@pytest.fixture
def bus() -> EventBus:
    return EventBus()
