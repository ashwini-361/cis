"""MeetAdapter: Google Meet (Chrome-extension capture) ingest per docs/PLATFORM_INTEGRATION.md §3.

Real transcription uses faster-whisper (already a dependency) to decode and
transcribe the WebM/Opus audio blobs the extension sends. Tests inject a
fake Transcriber instead so the suite doesn't need to run real inference.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, TypedDict

from app.ingest.base import IngestAdapter
from app.schema import Event, EventEnvelope, EventType, SessionEnvelope

_BUFFER_WINDOW_SEC = 30.0


class SegmentDict(TypedDict):
    text: str
    start_sec: float
    end_sec: float


class Transcriber(Protocol):
    async def transcribe(self, audio_bytes: bytes, participant_id: str) -> list[SegmentDict]: ...


class FasterWhisperTranscriber:
    """Real backend: decodes the WebM/Opus blob and transcribes via faster-whisper.

    faster-whisper decodes arbitrary containers (WebM included) internally via
    `av`, so a raw file path is sufficient -- no manual PyAV decode needed.
    """

    def __init__(self, model_size: str = "large-v3-turbo", device: str = "cpu") -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_size, device=device, compute_type="int8")

    async def transcribe(self, audio_bytes: bytes, participant_id: str) -> list[SegmentDict]:
        return await asyncio.to_thread(self._transcribe_sync, audio_bytes)

    def _transcribe_sync(self, audio_bytes: bytes) -> list[SegmentDict]:
        with tempfile.NamedTemporaryFile(suffix=".webm") as tmp:
            tmp.write(audio_bytes)
            tmp.flush()
            segments, _info = self._model.transcribe(tmp.name)
            return [
                {"text": seg.text.strip(), "start_sec": seg.start, "end_sec": seg.end}
                for seg in segments
            ]


@dataclass
class _AudioBuffer:
    chunks: list[bytes] = field(default_factory=list)
    start_sec: float | None = None
    end_sec: float = 0.0

    @property
    def duration(self) -> float:
        if self.start_sec is None:
            return 0.0
        return self.end_sec - self.start_sec


class MeetAdapter(IngestAdapter):
    """Bridges Chrome-extension-captured Meet events into the Event stream.

    Control messages (participant lifecycle) arrive as MOCK_DATA_FORMAT-style
    shorthand dicts (type/ts/payload) via push_control_message, reusing the
    same shorthand shape app/ingest/mock.py already parses. Audio arrives via
    push_audio_chunk and is buffered per participant until 30s accumulate
    (docs/PLATFORM_INTEGRATION.md §3.4), then transcribed into
    TRANSCRIPT_SEGMENT events.
    """

    def __init__(self, transcriber: Transcriber) -> None:
        self._transcriber = transcriber
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._session_envelope: SessionEnvelope | None = None
        self._sequence = 0
        self._source = "meet.extension"
        self._buffers: dict[str, _AudioBuffer] = {}
        self._ended = asyncio.Event()

    def _next_envelope(self, ts: float) -> EventEnvelope:
        assert self._session_envelope is not None, "start_session() must be called first"
        envelope = EventEnvelope(
            session_id=self._session_envelope.session_id,
            ts=ts,
            wall_clock=datetime.now(UTC).isoformat(),
            platform="meet",
            source=self._source,
            sequence=self._sequence,
        )
        self._sequence += 1
        return envelope

    async def start_session(self, session_envelope: SessionEnvelope) -> None:
        self._session_envelope = session_envelope
        await self._queue.put(
            Event(
                type=EventType.SESSION_START,
                envelope=self._next_envelope(0.0),
                payload={"expected_participants": session_envelope.expected_participants},
            )
        )

    async def push_control_message(self, raw: dict[str, Any]) -> None:
        await self._queue.put(
            Event(
                type=EventType[raw["type"]],
                envelope=self._next_envelope(raw["ts"]),
                payload=raw["payload"],
            )
        )

    async def push_audio_chunk(
        self, participant_id: str, audio_bytes: bytes, start_sec: float, end_sec: float
    ) -> None:
        buffer = self._buffers.setdefault(participant_id, _AudioBuffer())
        if buffer.start_sec is None:
            buffer.start_sec = start_sec
        buffer.chunks.append(audio_bytes)
        buffer.end_sec = end_sec

        if buffer.duration >= _BUFFER_WINDOW_SEC:
            del self._buffers[participant_id]
            await self._flush_buffer(participant_id, buffer)

    async def _flush_buffer(self, participant_id: str, buffer: _AudioBuffer) -> None:
        combined = b"".join(buffer.chunks)
        segments = await self._transcriber.transcribe(combined, participant_id)
        for segment in segments:
            await self._queue.put(
                Event(
                    type=EventType.TRANSCRIPT_SEGMENT,
                    envelope=self._next_envelope(segment["start_sec"]),
                    payload={
                        "participant_id": participant_id,
                        "text": segment["text"],
                        "start_sec": segment["start_sec"],
                        "end_sec": segment["end_sec"],
                    },
                )
            )

    async def stream_events(self) -> AsyncIterator[Event]:
        while True:
            get_task: asyncio.Task[Event] = asyncio.create_task(self._queue.get())
            end_task: asyncio.Task[bool] = asyncio.create_task(self._ended.wait())
            done, _pending = await asyncio.wait(
                {get_task, end_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if get_task in done:
                end_task.cancel()
                yield get_task.result()
            else:
                get_task.cancel()
                break

        while not self._queue.empty():
            yield self._queue.get_nowait()

        yield Event(
            type=EventType.SESSION_END,
            envelope=self._next_envelope(0.0),
            payload={"reason": "normal"},
        )

    async def end_session(self, reason: str = "normal") -> None:
        self._ended.set()
