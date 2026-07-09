"""MeetAdapter + WebSocket ingress tests per docs/PLATFORM_INTEGRATION.md §3."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ingest.meet import MeetAdapter, SegmentDict
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

    # Crossing 30s triggers a transcription call.
    await adapter.push_audio_chunk("P1", b"chunk3", start_sec=20.0, end_sec=31.0)
    assert len(transcriber.calls) == 1
    assert transcriber.calls[0][0] == b"chunk1chunk2chunk3"

    await adapter.end_session()
    events = [event async for event in adapter.stream_events()]
    segment_events = [e for e in events if e.type == EventType.TRANSCRIPT_SEGMENT]
    assert len(segment_events) == 1
    assert segment_events[0].payload["text"] == "hello"
    assert segment_events[0].payload["participant_id"] == "P1"


def test_websocket_route_dispatches_control_and_audio() -> None:
    adapter = MeetAdapter(FakeTranscriber([]))
    session = session_manager.create_session("ws-test-session", _WEIGHT_TABLE)
    session.ingest_adapter = adapter

    received_control: list[dict[str, Any]] = []
    received_audio: list[tuple[str, bytes]] = []

    async def fake_push_control_message(raw: dict[str, Any]) -> None:
        received_control.append(raw)

    async def fake_push_audio_chunk(
        participant_id: str, audio_bytes: bytes, start_sec: float, end_sec: float
    ) -> None:
        received_audio.append((participant_id, audio_bytes))

    adapter.push_control_message = fake_push_control_message  # type: ignore[method-assign]
    adapter.push_audio_chunk = fake_push_audio_chunk  # type: ignore[method-assign]

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
    finally:
        session_manager.remove_session("ws-test-session")

    assert received_control == [
        {"type": "WEBCAM_ON", "ts": 2.0, "payload": {"participant_id": "P1"}}
    ]
    assert received_audio == [("P1", b"opus-bytes")]


def test_websocket_route_closes_unknown_session() -> None:
    client = TestClient(app)
    with client.websocket_connect("/meet/unknown-session/capture") as ws:
        with pytest.raises(Exception):  # noqa: B017 -- starlette raises on the closed connection
            ws.receive_text()
