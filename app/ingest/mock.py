"""MockAdapter per docs/MOCK_DATA_FORMAT.md and docs/ROADMAP.md §Phase 2."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.ingest.base import IngestAdapter
from app.schema import Event, EventEnvelope, EventType, SessionEnvelope

SleepFn = Callable[[float], Awaitable[None]]


class _CandidateMeta(BaseModel):
    name: str
    email: str


class _InterviewerMeta(BaseModel):
    name: str
    email: str | None = None


class _ScheduleMeta(BaseModel):
    start_wall_clock: str
    expected_duration_min: int
    calendar_invite_id: str | None = None


class _RecordingMetadata(BaseModel):
    candidate: _CandidateMeta
    interviewers: list[_InterviewerMeta]
    schedule: _ScheduleMeta


class _MockRecording(BaseModel):
    """Loose validation of the top-level recording JSON per MOCK_DATA_FORMAT.md §1."""

    version: str
    scenario_id: str
    platform: str
    session: SessionEnvelope
    metadata: _RecordingMetadata
    participants: list[dict[str, Any]]
    events: list[dict[str, Any]]
    transcript_segments: list[dict[str, Any]] = []
    expected_output: dict[str, Any]


class MockAdapter(IngestAdapter):
    """Replays a recorded mock session as a deterministic Event stream.

    `sleep_fn` is dependency-injected so tests can replay 30-minute recordings
    in milliseconds while production/demo use keeps real-time pacing.
    """

    def __init__(self, recording_path: Path, sleep_fn: SleepFn = asyncio.sleep) -> None:
        self._recording = _MockRecording.model_validate(
            json.loads(recording_path.read_text())
        )
        self.source = f"mock.{self._recording.scenario_id}"
        self.sleep_fn = sleep_fn
        self._session_envelope: SessionEnvelope | None = None
        self._ended = False

    @property
    def expected_output(self) -> dict[str, Any]:
        return self._recording.expected_output

    async def start_session(self, session_envelope: SessionEnvelope) -> None:
        self._session_envelope = session_envelope

    async def stream_events(self) -> AsyncIterator[Event]:
        if self._session_envelope is None:
            raise RuntimeError("start_session() must be called before stream_events()")

        session_id = self._recording.session.session_id
        sequence = 0
        previous_ts = 0.0

        def make_envelope(ts: float) -> EventEnvelope:
            return EventEnvelope(
                session_id=session_id,
                ts=ts,
                wall_clock=datetime.now(UTC).isoformat(),
                platform="mock",
                source=self.source,
                sequence=sequence,
            )

        yield Event(
            type=EventType.SESSION_START,
            envelope=make_envelope(0.0),
            payload={"expected_participants": self._recording.session.expected_participants},
        )
        sequence += 1

        metadata = self._recording.metadata
        yield Event(
            type=EventType.METADATA_CANDIDATE,
            envelope=make_envelope(0.0),
            payload={
                "name": metadata.candidate.name,
                "email": metadata.candidate.email,
                "calendar_invite_id": metadata.schedule.calendar_invite_id,
            },
        )
        sequence += 1

        yield Event(
            type=EventType.METADATA_SCHEDULE,
            envelope=make_envelope(0.0),
            payload={
                "start_wall_clock": metadata.schedule.start_wall_clock,
                "expected_duration_min": metadata.schedule.expected_duration_min,
                "interviewer_names": [i.name for i in metadata.interviewers],
            },
        )
        sequence += 1

        yield Event(
            type=EventType.METADATA_INTERVIEWERS,
            envelope=make_envelope(0.0),
            payload={
                "names": [i.name for i in metadata.interviewers],
                "emails": [i.email for i in metadata.interviewers if i.email is not None]
                or None,
            },
        )
        sequence += 1

        transcript_as_events = [
            {
                "type": EventType.TRANSCRIPT_SEGMENT.name,
                "ts": segment["start_sec"],
                "payload": segment,
            }
            for segment in self._recording.transcript_segments
        ]
        merged = sorted(
            [*self._recording.events, *transcript_as_events],
            key=lambda entry: entry["ts"],
        )

        for entry in merged:
            delay = max(0.0, entry["ts"] - previous_ts)
            await self.sleep_fn(delay)
            previous_ts = entry["ts"]
            yield Event(
                type=EventType[entry["type"]],
                envelope=make_envelope(entry["ts"]),
                payload=entry["payload"],
            )
            sequence += 1

        yield Event(
            type=EventType.SESSION_END,
            envelope=make_envelope(previous_ts),
            payload={"reason": "normal"},
        )

    async def end_session(self, reason: str = "normal") -> None:
        self._ended = True
