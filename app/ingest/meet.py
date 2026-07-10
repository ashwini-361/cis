"""MeetAdapter: Google Meet (Chrome-extension capture) ingest per docs/PLATFORM_INTEGRATION.md §3.

Real transcription uses faster-whisper (already a dependency) to decode and
transcribe the WebM/Opus audio blobs the extension sends. Tests inject a
fake Transcriber instead so the suite doesn't need to run real inference.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, TypedDict

from app.ingest.base import IngestAdapter
from app.schema import Event, EventEnvelope, EventType, SessionEnvelope

_BUFFER_WINDOW_SEC = 30.0

logger = logging.getLogger(__name__)


class SegmentDict(TypedDict):
    text: str
    start_sec: float
    end_sec: float


class Transcriber(Protocol):
    async def transcribe(self, audio_bytes: bytes, participant_id: str) -> list[SegmentDict]: ...


_WEBM_MAGIC = b"\x1a\x45\xdf\xa3"  # EBML header that starts every valid WebM file


class FasterWhisperTranscriber:
    """Real backend: decodes the WebM/Opus blob and transcribes via faster-whisper.

    faster-whisper decodes arbitrary containers (WebM included) internally via
    `av`, so a raw file path is sufficient -- no manual PyAV decode needed.
    """

    def __init__(
        self,
        model_size: str = "large-v3-turbo",
        device: str = "auto",
        compute_type: str = "default",
    ) -> None:
        self._model_size = model_size
        self._fallback_model_size = os.environ.get("WHISPER_FALLBACK_MODEL", "small")
        self._device = device
        self._compute_type = compute_type
        self._debug_saved = False
        self._model = self._load_model(
            model_size=model_size,
            device=device,
            compute_type=compute_type,
        )

    def _instantiate_model(self, model_size: str, device: str, compute_type: str) -> Any:
        from faster_whisper import WhisperModel  # type: ignore[import-untyped]

        return WhisperModel(model_size, device=device, compute_type=compute_type)

    def _load_model(self, model_size: str, device: str, compute_type: str) -> Any:
        try:
            model = self._instantiate_model(model_size, device, compute_type)
            self._model_size = model_size
            self._device = device
            self._compute_type = compute_type
            return model
        except Exception:
            if model_size == self._fallback_model_size:
                raise
            logger.warning(
                "Could not initialize Whisper model %s on %s/%s. Falling back to %s.",
                model_size,
                device,
                compute_type,
                self._fallback_model_size,
                exc_info=True,
            )
            model = self._instantiate_model(
                self._fallback_model_size, "cpu", "int8"
            )
            self._model_size = self._fallback_model_size
            self._device = "cpu"
            self._compute_type = "int8"
            return model

    def _reload_model(self, model_size: str, device: str, compute_type: str) -> None:
        self._model = self._load_model(
            model_size=model_size,
            device=device,
            compute_type=compute_type,
        )

    async def transcribe(self, audio_bytes: bytes, participant_id: str) -> list[SegmentDict]:
        return await asyncio.to_thread(self._transcribe_sync, audio_bytes)

    def _transcribe_sync(self, audio_bytes: bytes) -> list[SegmentDict]:
        magic = audio_bytes[:4] if len(audio_bytes) >= 4 else audio_bytes
        magic_hex = magic.hex()
        is_valid_webm = audio_bytes[:4] == _WEBM_MAGIC
        logger.info(
            "FasterWhisperTranscriber: %d bytes, magic=0x%s (%s)",
            len(audio_bytes),
            magic_hex,
            "valid WebM" if is_valid_webm else "NOT valid WebM — expected 0x1a45dfa3",
        )
        if not self._debug_saved:
            debug_path = os.path.join(tempfile.gettempdir(), "cis_debug_audio.webm")
            try:
                with open(debug_path, "wb") as f:
                    f.write(audio_bytes)
                logger.info(
                    "FasterWhisperTranscriber: debug copy saved → %s  (open with VLC/ffplay to verify)",
                    debug_path,
                )
                self._debug_saved = True
            except Exception:
                logger.exception("FasterWhisperTranscriber: could not save debug file")

        tmp = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
        try:
            tmp.write(audio_bytes)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            try:
                segments, info = self._model.transcribe(tmp.name)
            except RuntimeError as e:
                error_msg = str(e)
                if "cublas" in error_msg.lower() or "cuda" in error_msg.lower():
                    logger.warning(
                        "CUDA libraries missing (%s). Falling back to CPU for transcription. Set WHISPER_DEVICE=cpu to silence this.",
                        error_msg
                    )
                    self._reload_model(self._model_size, "cpu", "int8")
                    try:
                        segments, info = self._model.transcribe(tmp.name)
                    except RuntimeError as retry_error:
                        if self._model_size == self._fallback_model_size:
                            raise retry_error
                        logger.warning(
                            "Primary Whisper model %s still failed on CPU (%s). Falling back to %s.",
                            self._model_size,
                            retry_error,
                            self._fallback_model_size,
                        )
                        self._reload_model(self._fallback_model_size, "cpu", "int8")
                        segments, info = self._model.transcribe(tmp.name)
                else:
                    raise e
            segment_list = [
                {"text": seg.text.strip(), "start_sec": seg.start, "end_sec": seg.end}
                for seg in segments
                if seg.text.strip()
            ]
            logger.info(
                "FasterWhisperTranscriber: language=%s prob=%.2f duration=%.2fs segments=%d",
                info.language,
                info.language_probability,
                info.duration,
                len(segment_list),
            )
            return segment_list
        finally:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except FileNotFoundError:
                pass


@dataclass(frozen=True)
class _AudioChunk:
    bytes_: bytes
    start_sec: float
    end_sec: float


@dataclass
class _AudioBuffer:
    chunks: list[_AudioChunk] = field(default_factory=list)
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
        self._end_reason = "normal"
        self._started = False
        self._has_mapped_audio = False

    def _next_envelope(self, ts: float, *, source: str | None = None) -> EventEnvelope:
        assert self._session_envelope is not None, "start_session() must be called first"
        envelope = EventEnvelope(
            session_id=self._session_envelope.session_id,
            ts=ts,
            wall_clock=datetime.now(UTC).isoformat(),
            platform="meet",
            source=source or self._source,
            sequence=self._sequence,
        )
        self._sequence += 1
        return envelope

    def prime_session(self, session_envelope: SessionEnvelope) -> None:
        """Bind the session envelope early so ingress can accept frames immediately."""

        self._session_envelope = session_envelope
        self._end_reason = "normal"
        self._ended = asyncio.Event()

    async def start_session(self, session_envelope: SessionEnvelope) -> None:
        self.prime_session(session_envelope)
        if self._started:
            return
        self._started = True
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
        if participant_id != "mixed-tab-audio":
            self._has_mapped_audio = True
        elif self._has_mapped_audio:
            logger.debug("MeetAdapter skipping mixed-tab-audio chunk because mapped audio is flowing")
            return

        buffer = self._buffers.setdefault(participant_id, _AudioBuffer())
        if buffer.start_sec is None:
            buffer.start_sec = start_sec
        buffer.chunks.append(
            _AudioChunk(bytes_=audio_bytes, start_sec=start_sec, end_sec=end_sec)
        )
        buffer.end_sec = end_sec

        if buffer.duration >= _BUFFER_WINDOW_SEC:
            logger.info(
                "MeetAdapter flush threshold reached for %s: duration=%.2fs chunks=%d",
                participant_id,
                buffer.duration,
                len(buffer.chunks),
            )
            del self._buffers[participant_id]
            await self._flush_buffer(participant_id, buffer)

    async def push_transcript_segment(self, raw: dict[str, Any]) -> None:
        """Queue a transcript segment that was captured directly by the extension."""

        await self._queue.put(
            Event(
                type=EventType.TRANSCRIPT_SEGMENT,
                envelope=self._next_envelope(
                    raw["start_sec"], source="meet.transcript.extension"
                ),
                payload={
                    "participant_id": raw["participant_id"],
                    "speaker_name": raw.get("speaker_name"),
                    "text": raw["text"],
                    "start_sec": raw["start_sec"],
                    "end_sec": raw["end_sec"],
                },
            )
        )

    async def _flush_buffer(self, participant_id: str, buffer: _AudioBuffer) -> None:
        """Transcribe each complete-WebM chunk independently, then offset timestamps.

        The extension now uses MediaRecorder stop()/restart() so each chunk is a
        self-contained WebM file.  Concatenating two complete WebM files produces
        an invalid container (two EBML headers) and must be avoided.
        """
        if not buffer.chunks:
            logger.info("MeetAdapter flush skipped for %s: empty buffer", participant_id)
            return
        total_bytes = sum(len(c.bytes_) for c in buffer.chunks)
        logger.info(
            "MeetAdapter flushing %d bytes for %s across %.2fs (%d chunks — transcribing each separately)",
            total_bytes,
            participant_id,
            buffer.duration,
            len(buffer.chunks),
        )
        total_segments = 0
        for index, chunk in enumerate(buffer.chunks, start=1):
            logger.info(
                "MeetAdapter transcribing chunk %d/%d for %s: %d bytes %.2f-%.2f",
                index,
                len(buffer.chunks),
                participant_id,
                len(chunk.bytes_),
                chunk.start_sec,
                chunk.end_sec,
            )
            try:
                segments = await self._transcriber.transcribe(chunk.bytes_, participant_id)
            except Exception:
                logger.exception(
                    "MeetAdapter transcription failed for %s chunk %d/%d (%d bytes %.2f-%.2f)",
                    participant_id,
                    index,
                    len(buffer.chunks),
                    len(chunk.bytes_),
                    chunk.start_sec,
                    chunk.end_sec,
                )
                continue
            logger.info(
                "MeetAdapter transcription produced %d segments for %s chunk %d/%d",
                len(segments),
                participant_id,
                index,
                len(buffer.chunks),
            )
            total_segments += len(segments)
            for segment in segments:
                absolute_start = chunk.start_sec + segment["start_sec"]
                absolute_end = chunk.start_sec + segment["end_sec"]
                logger.info(
                    "MeetAdapter enqueuing transcript segment for %s: %.2f-%.2f %r",
                    participant_id,
                    absolute_start,
                    absolute_end,
                    segment["text"],
                )
                await self._queue.put(
                    Event(
                        type=EventType.TRANSCRIPT_SEGMENT,
                        envelope=self._next_envelope(
                            absolute_start, source="meet.transcript.whisper"
                        ),
                        payload={
                            "participant_id": participant_id,
                            "text": segment["text"],
                            "start_sec": absolute_start,
                            "end_sec": absolute_end,
                        },
                    )
                )
        logger.info(
            "MeetAdapter flush complete for %s: %d total segments across %d chunks",
            participant_id,
            total_segments,
            len(buffer.chunks),
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
            payload={"reason": self._end_reason},
        )

    async def end_session(self, reason: str = "normal") -> None:
        """Flush pending short buffers before closing the stream."""

        self._end_reason = reason
        buffers = self._buffers
        self._buffers = {}
        logger.info("MeetAdapter ending session with %d pending buffers", len(buffers))
        for participant_id, buffer in buffers.items():
            logger.info(
                "MeetAdapter final flush for %s: duration=%.2fs chunks=%d",
                participant_id,
                buffer.duration,
                len(buffer.chunks),
            )
            await self._flush_buffer(participant_id, buffer)
        self._ended.set()
