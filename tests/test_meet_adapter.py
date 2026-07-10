"""MeetAdapter + WebSocket ingress tests per docs/PLATFORM_INTEGRATION.md §3."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.ingest.meet as meet_module
from app.ingest.meet import FasterWhisperTranscriber, MeetAdapter, SegmentDict
from app.main import app, session_manager
from app.schema import DecayConfig, EventType, SessionEnvelope, WeightTable

_WEIGHT_TABLE = WeightTable(
    version="1.0.0", fusion_engine="v1-weighted", threshold=0.55, margin=0.20,
    decay=DecayConfig(), weights={},
)


class FakeTranscriber:
    def __init__(self, segments: list[SegmentDict]) -> None:
        self._segments = segments
        self.calls: list[tuple[bytes, str]] = []

    async def transcribe(self, audio_bytes: bytes, participant_id: str) -> list[SegmentDict]:
        self.calls.append((audio_bytes, participant_id))
        return self._segments


def test_faster_whisper_transcriber_closes_temp_file_before_model_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Seg:
        def __init__(self, text: str, start: float, end: float) -> None:
            self.text = text
            self.start = start
            self.end = end

    class FakeInfo:
        language = "en"
        language_probability = 0.99
        duration = 1.0

    class FakeModel:
        def __init__(self) -> None:
            self.called_with: str | None = None

        def transcribe(self, path: str) -> tuple[list[_Seg], FakeInfo]:
            self.called_with = path
            assert fake_tmp.closed is True
            return ([_Seg("hello", 0.0, 1.0)], FakeInfo())

    class FakeTmp:
        def __init__(self) -> None:
            self.name = "fake-temp.webm"
            self.closed = False
            self.written = b""

        def write(self, data: bytes) -> int:
            self.written += data
            return len(data)

        def flush(self) -> None:
            return None

        def fileno(self) -> int:
            return 123

        def close(self) -> None:
            self.closed = True

    fake_tmp = FakeTmp()
    unlinked: list[str] = []

    monkeypatch.setattr(meet_module.tempfile, "NamedTemporaryFile", lambda **_: fake_tmp)
    monkeypatch.setattr(meet_module.os, "fsync", lambda _fd: None)
    monkeypatch.setattr(meet_module.os, "unlink", lambda path: unlinked.append(path))

    transcriber = object.__new__(FasterWhisperTranscriber)
    transcriber._model = FakeModel()
    transcriber._debug_saved = False

    segments = transcriber._transcribe_sync(b"chunk-bytes")

    assert fake_tmp.written == b"chunk-bytes"
    assert transcriber._model.called_with == "fake-temp.webm"
    assert unlinked == ["fake-temp.webm"]
    assert segments == [{"text": "hello", "start_sec": 0.0, "end_sec": 1.0}]


async def _new_adapter(
    segments: list[SegmentDict] | None = None,
) -> tuple[MeetAdapter, FakeTranscriber]:
    transcriber = FakeTranscriber(segments or [])
    adapter = MeetAdapter(transcriber)
    await adapter.start_session(
        SessionEnvelope(
            session_id="meet-sess-1",
            platform="meet",
            start_wall_clock="2026-07-09T09:30:00Z",
        )
    )
    return adapter, transcriber


async def test_session_start_and_end_bookend_the_stream() -> None:
    adapter, _ = await _new_adapter()
    await adapter.end_session()

    events = [event async for event in adapter.stream_events()]
    assert events[0].type == EventType.SESSION_START
    assert events[-1].type == EventType.SESSION_END


async def test_control_message_becomes_event() -> None:
    adapter, _ = await _new_adapter()
    await adapter.push_control_message(
        {
            "type": "PARTICIPANT_JOINED",
            "ts": 1.1,
            "payload": {
                "participant_id": "P1",
                "display_name": "Ashwini",
                "email": None,
                "device_name": None,
                "join_order": 1,
            },
        }
    )
    await adapter.end_session()

    events = [event async for event in adapter.stream_events()]
    joined = next(e for e in events if e.type == EventType.PARTICIPANT_JOINED)
    assert joined.payload["participant_id"] == "P1"


async def test_audio_buffers_until_30s_then_transcribes() -> None:
    adapter, transcriber = await _new_adapter(
        segments=[{"text": "hello", "start_sec": 0.0, "end_sec": 5.0}]
    )

    # Two 10s chunks: under the 30s window, no transcription yet.
    await adapter.push_audio_chunk("P1", b"chunk1", start_sec=0.0, end_sec=10.0)
    await adapter.push_audio_chunk("P1", b"chunk2", start_sec=10.0, end_sec=20.0)
    assert transcriber.calls == []

    # Crossing 30s triggers per-chunk transcription (each chunk is now a complete WebM).
    await adapter.push_audio_chunk("P1", b"chunk3", start_sec=20.0, end_sec=31.0)
    assert len(transcriber.calls) == 3
    assert transcriber.calls[0][0] == b"chunk1"
    assert transcriber.calls[1][0] == b"chunk2"
    assert transcriber.calls[2][0] == b"chunk3"

    await adapter.end_session()
    events = [event async for event in adapter.stream_events()]
    segment_events = [e for e in events if e.type == EventType.TRANSCRIPT_SEGMENT]
    assert len(segment_events) == 3
    assert all(e.payload["text"] == "hello" for e in segment_events)
    assert all(e.payload["participant_id"] == "P1" for e in segment_events)
    # each segment's absolute_start = chunk.start_sec + segment["start_sec"] (0.0)
    assert segment_events[0].payload["start_sec"] == 0.0
    assert segment_events[1].payload["start_sec"] == 10.0
    assert segment_events[2].payload["start_sec"] == 20.0


async def test_end_session_flushes_short_audio_buffer() -> None:
    adapter, transcriber = await _new_adapter(
        segments=[{"text": "short ending", "start_sec": 0.0, "end_sec": 4.0}]
    )

    await adapter.push_audio_chunk("P1", b"chunk1", start_sec=0.0, end_sec=4.0)
    assert transcriber.calls == []

    await adapter.end_session()

    events = [event async for event in adapter.stream_events()]
    segment_events = [e for e in events if e.type == EventType.TRANSCRIPT_SEGMENT]
    assert len(transcriber.calls) == 1
    assert transcriber.calls[0][0] == b"chunk1"
    assert len(segment_events) == 1
    assert segment_events[0].payload["text"] == "short ending"
    assert segment_events[0].payload["start_sec"] == 0.0


async def test_push_transcript_segment_becomes_event() -> None:
    adapter, _ = await _new_adapter()
    await adapter.push_transcript_segment(
        {
            "participant_id": "P1",
            "text": "I built Astra and a parsing pipeline.",
            "start_sec": 12.0,
            "end_sec": 15.0,
        }
    )
    await adapter.end_session()

    events = [event async for event in adapter.stream_events()]
    segment = next(e for e in events if e.type == EventType.TRANSCRIPT_SEGMENT)
    assert segment.payload["participant_id"] == "P1"
    assert segment.payload["text"] == "I built Astra and a parsing pipeline."


def test_websocket_route_dispatches_control_audio_and_transcript() -> None:
    adapter = MeetAdapter(FakeTranscriber([]))
    session = session_manager.create_session("ws-test-session", _WEIGHT_TABLE)
    session.ingest_adapter = adapter

    received_control: list[dict[str, Any]] = []
    received_audio: list[tuple[str, bytes]] = []
    received_transcript: list[dict[str, Any]] = []

    async def fake_push_control_message(raw: dict[str, Any]) -> None:
        received_control.append(raw)

    async def fake_push_audio_chunk(
        participant_id: str, audio_bytes: bytes, start_sec: float, end_sec: float
    ) -> None:
        received_audio.append((participant_id, audio_bytes))

    async def fake_push_transcript_segment(raw: dict[str, Any]) -> None:
        received_transcript.append(raw)

    adapter.push_control_message = fake_push_control_message  # type: ignore[method-assign]
    adapter.push_audio_chunk = fake_push_audio_chunk  # type: ignore[method-assign]
    adapter.push_transcript_segment = fake_push_transcript_segment  # type: ignore[method-assign]

    control_message = {
        "kind": "control",
        "type": "WEBCAM_ON",
        "ts": 2.0,
        "payload": {"participant_id": "P1"},
    }
    client = TestClient(app)
    try:
        with client.websocket_connect("/meet/ws-test-session/capture") as ws:
            ws.send_json(control_message)
            ws.send_json(
                {
                    "kind": "audio_chunk_meta",
                    "participant_id": "P1",
                    "start_sec": 0.0,
                    "end_sec": 5.0,
                }
            )
            ws.send_bytes(b"opus-bytes")
            ws.send_json(
                {
                    "kind": "transcript",
                    "participant_id": "P1",
                    "speaker_name": "Ashwini",
                    "text": "I built Astra.",
                    "start_sec": 5.0,
                    "end_sec": 6.0,
                }
            )
            ws.send_json(
                {
                    "kind": "diagnostic",
                    "event": "content.transcript_selector_found",
                    "message": "Transcript container matched",
                    "payload": {"count": 1},
                    "ts": 7.0,
                }
            )
    finally:
        session_manager.remove_session("ws-test-session")

    assert received_control == [
        {"type": "WEBCAM_ON", "ts": 2.0, "payload": {"participant_id": "P1"}}
    ]
    assert received_audio == [("P1", b"opus-bytes")]
    assert received_transcript == [
        {
            "participant_id": "P1",
            "text": "I built Astra.",
            "start_sec": 5.0,
            "end_sec": 6.0,
        }
    ]


def test_live_debug_endpoint_reports_ingest_activity() -> None:
    adapter = MeetAdapter(FakeTranscriber([]))
    adapter.prime_session(
        SessionEnvelope(
            session_id="debug-session",
            platform="meet",
            start_wall_clock="2026-07-10T12:00:00Z",
        )
    )
    session = session_manager.create_session("debug-session", _WEIGHT_TABLE)
    session.ingest_adapter = adapter

    client = TestClient(app)
    try:
        with client.websocket_connect("/meet/debug-session/capture") as ws:
            ws.send_json(
                {
                    "kind": "control",
                    "type": "PARTICIPANT_JOINED",
                    "ts": 1.0,
                    "payload": {
                        "participant_id": "P1",
                        "display_name": "Ashwini",
                        "join_order": 1,
                    },
                }
            )
            ws.send_json(
                {
                    "kind": "audio_chunk_meta",
                    "participant_id": "P1",
                    "start_sec": 1.0,
                    "end_sec": 2.0,
                }
            )
            ws.send_bytes(b"opus")
            ws.send_json(
                {
                    "kind": "transcript",
                    "participant_id": "P1",
                    "speaker_name": "Ashwini",
                    "text": "Tell me about yourself.",
                    "start_sec": 2.0,
                    "end_sec": 3.0,
                }
            )
            ws.send_json(
                {
                    "kind": "diagnostic",
                    "event": "content.observer_started",
                    "message": "Meet DOM observers attached",
                    "payload": {},
                    "ts": 4.0,
                }
            )
        response = client.get("/sessions/debug-session/live-debug")
    finally:
        session_manager.remove_session("debug-session")

    assert response.status_code == 200
    payload = response.json()
    assert payload["control_messages"] == 1
    assert payload["audio_chunks"] == 1
    assert payload["transcript_segments"] == 1
    assert payload["extension_connections"] == 1
    assert payload["last_control_type"] == "PARTICIPANT_JOINED"
    assert payload["last_audio"]["participant_id"] == "P1"
    assert payload["last_transcript"]["speaker_name"] == "Ashwini"
    assert any(event["kind"] == "content.observer_started" for event in payload["recent_events"])


def test_websocket_route_closes_unknown_session() -> None:
    client = TestClient(app)
    with client.websocket_connect("/meet/unknown-session/capture") as ws:
        with pytest.raises(Exception):  # noqa: B017 -- starlette raises on the closed connection
            ws.receive_text()
