"""MockAdapter replay tests per docs/ROADMAP.md §2.1 and docs/MOCK_DATA_FORMAT.md §2.3."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest.mock import MockAdapter
from app.schema import Event, EventType, SessionEnvelope

HAPPY_PATH = Path(__file__).resolve().parent.parent / "data" / "recordings" / "happy_path.json"


async def _no_wait(delay: float) -> None:
    """Dependency-injected sleep_fn: skips real-time pacing for fast tests."""


async def _replay(recording_path: Path = HAPPY_PATH) -> list[Event]:
    adapter = MockAdapter(recording_path, sleep_fn=_no_wait)
    await adapter.start_session(
        SessionEnvelope(
            session_id="mock-sess-001",
            platform="mock",
            start_wall_clock="2026-07-09T09:30:00Z",
        )
    )
    return [event async for event in adapter.stream_events()]


async def test_mock_replay_session_bookends() -> None:
    events = await _replay()
    assert events[0].type == EventType.SESSION_START
    assert events[-1].type == EventType.SESSION_END


async def test_mock_replay_metadata_present_once_after_session_start() -> None:
    events = await _replay()
    metadata_types = {
        EventType.METADATA_CANDIDATE,
        EventType.METADATA_SCHEDULE,
        EventType.METADATA_INTERVIEWERS,
    }
    metadata_indices = [i for i, e in enumerate(events) if e.type in metadata_types]
    assert len(metadata_indices) == 3
    assert metadata_indices == [1, 2, 3]
    seen_types = {events[i].type for i in metadata_indices}
    assert seen_types == metadata_types


async def test_mock_replay_preserves_events_json_order() -> None:
    import json

    raw = json.loads(HAPPY_PATH.read_text())
    expected_order = [entry["type"] for entry in raw["events"]]

    events = await _replay()
    non_synthetic = {
        EventType.SESSION_START,
        EventType.SESSION_END,
        EventType.METADATA_CANDIDATE,
        EventType.METADATA_SCHEDULE,
        EventType.METADATA_INTERVIEWERS,
        EventType.TRANSCRIPT_SEGMENT,
    }
    actual_order = [e.type.name for e in events if e.type not in non_synthetic]
    assert actual_order == expected_order


async def test_mock_replay_sequence_strictly_increasing() -> None:
    events = await _replay()
    sequences = [e.envelope.sequence for e in events]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))


async def test_mock_replay_requires_start_session_first() -> None:
    adapter = MockAdapter(HAPPY_PATH, sleep_fn=_no_wait)
    with pytest.raises(RuntimeError):
        async for _ in adapter.stream_events():
            pass


async def test_mock_replay_is_idempotent() -> None:
    first = await _replay()
    second = await _replay()
    assert [e.envelope.sequence for e in first] == [e.envelope.sequence for e in second]
    assert [e.type for e in first] == [e.type for e in second]


async def test_mock_replay_transcript_segments_interleaved() -> None:
    events = await _replay()
    screen_share_start_ts = next(
        e.envelope.ts for e in events if e.type == EventType.SCREEN_SHARE_START
    )
    screen_share_stop_ts = next(
        e.envelope.ts for e in events if e.type == EventType.SCREEN_SHARE_STOP
    )
    transcript_ts_values = [
        e.envelope.ts for e in events if e.type == EventType.TRANSCRIPT_SEGMENT
    ]
    assert any(
        screen_share_start_ts < ts < screen_share_stop_ts for ts in transcript_ts_values
    )
