"""Shared fixtures for analyzer tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.schema import Event, EventEnvelope, EventType, SessionEnvelope, WeightTable

WEIGHTS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "weights" / "weights.json"


@pytest.fixture
def weight_table() -> WeightTable:
    return WeightTable.model_validate(json.loads(WEIGHTS_PATH.read_text()))


@pytest.fixture
def session_envelope() -> SessionEnvelope:
    return SessionEnvelope(
        session_id="sess_1",
        platform="mock",
        start_wall_clock="2026-07-09T09:30:00Z",
    )


def make_event(
    event_type: EventType,
    ts: float,
    payload: dict[str, Any],
    sequence: int = 0,
    source: str = "test",
) -> Event:
    return Event(
        type=event_type,
        envelope=EventEnvelope(
            session_id="sess_1",
            ts=ts,
            wall_clock="2026-07-09T09:30:00Z",
            platform="mock",
            source=source,
            sequence=sequence,
        ),
        payload=payload,
    )
