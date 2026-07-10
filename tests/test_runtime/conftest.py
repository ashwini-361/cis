"""Shared fixtures for Phase 9A runtime tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.analyzers.transcript_role import LLMProvider
from app.harness.scripted_llm import ScriptedLLMProvider
from app.schema import SessionEnvelope, WeightTable

WEIGHTS_JSON = (
    Path(__file__).resolve().parent.parent.parent / "data" / "weights" / "weights.json"
)


@pytest.fixture
def weights() -> WeightTable:
    return WeightTable.model_validate(json.loads(WEIGHTS_JSON.read_text()))


@pytest.fixture
def session_envelope() -> SessionEnvelope:
    return SessionEnvelope(
        session_id="rt-sess-1",
        platform="mock",
        start_wall_clock="2026-07-09T09:30:00Z",
        expected_participants=["P1", "P2", "P3"],
    )


@pytest.fixture
def scripted_llm() -> LLMProvider:
    return ScriptedLLMProvider()
