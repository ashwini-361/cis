"""ZoomAdapter + webhook tests per docs/PLATFORM_INTEGRATION.md §2."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ingest.meet import SegmentDict
from app.ingest.zoom import (
    ZoomAdapter,
    ZoomAPIClient,
    ZoomAuth,
    handle_url_validation,
    map_webhook_event,
    verify_webhook_signature,
)
from app.main import app, zoom_adapters
from app.schema import EventType, SessionEnvelope


class FakeTokenStore:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value


class FakeTranscriber:
    def __init__(self, segments: list[SegmentDict]) -> None:
        self._segments = segments

    async def transcribe(self, audio_bytes: bytes, participant_id: str) -> list[SegmentDict]:
        return self._segments


# --- HMAC / webhook signature -------------------------------------------------


def test_verify_webhook_signature_accepts_correct_hmac() -> None:
    secret = "s3cr3t"
    timestamp = "1234567890"
    body = b'{"event":"meeting.participant_joined"}'
    message = f"v0:{timestamp}:{body.decode()}".encode()
    expected_sig = "v0=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(secret, timestamp, body, expected_sig) is True


def test_verify_webhook_signature_rejects_tampered_body() -> None:
    secret = "s3cr3t"
    timestamp = "1234567890"
    body = b'{"event":"meeting.participant_joined"}'
    message = f"v0:{timestamp}:{body.decode()}".encode()
    sig = "v0=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    tampered_body = b'{"event":"meeting.participant_left"}'
    assert verify_webhook_signature(secret, timestamp, tampered_body, sig) is False


def test_url_validation_handshake() -> None:
    secret = "s3cr3t"
    plain_token = "abc123"
    result = handle_url_validation(plain_token, secret)
    expected = hmac.new(secret.encode(), plain_token.encode(), hashlib.sha256).hexdigest()
    assert result == {"plainToken": plain_token, "encryptedToken": expected}


# --- webhook event mapping -----------------------------------------------------


def test_map_webhook_event_participant_joined() -> None:
    zoom_event = {
        "event": "meeting.participant_joined",
        "event_ts": 1000,
        "payload": {
            "object": {
                "participant": {
                    "user_id": "zoom-usr-1",
                    "user_name": "Ashwini",
                    "email": "ashwini@gmail.com",
                    "device": "Mac",
                    "join_order": 1,
                }
            }
        },
    }
    mapped = map_webhook_event(zoom_event)
    assert mapped is not None
    assert mapped["type"] == "PARTICIPANT_JOINED"
    assert mapped["payload"]["participant_id"] == "zoom-usr-1"
    assert mapped["payload"]["display_name"] == "Ashwini"


def test_map_webhook_event_participant_left() -> None:
    zoom_event = {
        "event": "meeting.participant_left",
        "event_ts": 2000,
        "payload": {"object": {"participant": {"user_id": "zoom-usr-1"}}},
    }
    mapped = map_webhook_event(zoom_event)
    assert mapped is not None
    assert mapped["type"] == "PARTICIPANT_LEFT"
    assert mapped["payload"]["participant_id"] == "zoom-usr-1"


@pytest.mark.parametrize(
    ("zoom_type", "expected_type"),
    [
        ("meeting.participant_screen_sharing_started", "SCREEN_SHARE_START"),
        ("meeting.participant_screen_sharing_stopped", "SCREEN_SHARE_STOP"),
        ("meeting.participant_video_started", "WEBCAM_ON"),
        ("meeting.participant_video_stopped", "WEBCAM_OFF"),
    ],
)
def test_map_webhook_event_media_state_events(zoom_type: str, expected_type: str) -> None:
    zoom_event = {
        "event": zoom_type,
        "event_ts": 3000,
        "payload": {"object": {"participant": {"user_id": "zoom-usr-1"}}},
    }
    mapped = map_webhook_event(zoom_event)
    assert mapped is not None
    assert mapped["type"] == expected_type
    assert mapped["payload"]["participant_id"] == "zoom-usr-1"


def test_map_webhook_event_unmapped_type_returns_none() -> None:
    assert map_webhook_event({"event": "meeting.started"}) is None


# --- ZoomAuth / ZoomAPIClient --------------------------------------------------


async def test_zoom_auth_authenticates_and_caches_token() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"access_token": "tok123", "expires_in": 3600})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        auth = ZoomAuth("id", "secret", "acct", FakeTokenStore(), client)
        token1 = await auth.get_access_token()
        token2 = await auth.get_access_token()

    assert token1 == token2 == "tok123"
    assert call_count == 1


async def test_zoom_auth_persists_via_token_store() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "tok123", "expires_in": 3600})

    store = FakeTokenStore()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        auth = ZoomAuth("id", "secret", "acct", store, client)
        await auth.get_access_token()

    assert store.get("access_token") == "tok123"


async def test_recording_pull_transcribes_each_track() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if str(request.url).endswith("/recordings"):
            return httpx.Response(
                200,
                json={
                    "recording_files": [
                        {
                            "id": "track1",
                            "download_url": "https://zoom.us/rec/track1.m4a",
                            "recording_start_participant_id": "P1",
                        }
                    ]
                },
            )
        return httpx.Response(200, content=b"fake-audio-bytes")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        auth = ZoomAuth("id", "secret", "acct", FakeTokenStore(), client)
        api_client = ZoomAPIClient(auth, client)
        transcriber = FakeTranscriber([{"text": "hello", "start_sec": 0.0, "end_sec": 5.0}])
        adapter = ZoomAdapter(api_client, transcriber)
        await adapter.start_session(
            SessionEnvelope(
                session_id="sess1", platform="zoom", start_wall_clock="2026-07-09T09:30:00Z"
            )
        )
        await adapter.push_webhook_event(
            {"event": "meeting.ended", "payload": {"object": {"id": "12345"}}}
        )
        await adapter.end_session()

        events = [event async for event in adapter.stream_events()]

    segments = [e for e in events if e.type == EventType.TRANSCRIPT_SEGMENT]
    assert len(segments) == 1
    assert segments[0].payload["text"] == "hello"
    assert segments[0].payload["participant_id"] == "P1"


# --- webhook route ---------------------------------------------------------


def test_webhook_route_answers_url_validation_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZOOM_WEBHOOK_SECRET_TOKEN", "s3cr3t")
    client = TestClient(app)
    response = client.post(
        "/zoom/webhook",
        json={"event": "endpoint.url_validation", "payload": {"plainToken": "abc123"}},
    )
    assert response.status_code == 200
    expected_encrypted = hmac.new(b"s3cr3t", b"abc123", hashlib.sha256).hexdigest()
    assert response.json() == {"plainToken": "abc123", "encryptedToken": expected_encrypted}


def test_webhook_route_rejects_bad_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZOOM_WEBHOOK_SECRET_TOKEN", "s3cr3t")
    client = TestClient(app)
    response = client.post(
        "/zoom/webhook",
        content=b'{"event": "meeting.participant_joined", "payload": {"object": {"id": "1"}}}',
        headers={
            "content-type": "application/json",
            "x-zm-signature": "v0=bad",
            "x-zm-request-timestamp": "123",
        },
    )
    assert response.status_code == 401


class _DummyAdapter:
    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []

    async def push_webhook_event(self, zoom_event: dict[str, Any]) -> None:
        self.received.append(zoom_event)


def test_webhook_route_accepts_valid_signature_and_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZOOM_WEBHOOK_SECRET_TOKEN", "s3cr3t")
    adapter = _DummyAdapter()
    zoom_adapters["42"] = adapter  # type: ignore[assignment]

    body = json.dumps(
        {
            "event": "meeting.participant_joined",
            "event_ts": 1000,
            "payload": {
                "object": {
                    "id": "42",
                    "participant": {"user_id": "P1", "user_name": "Ashwini", "join_order": 1},
                }
            },
        }
    ).encode()
    timestamp = "1234567890"
    message = f"v0:{timestamp}:{body.decode()}".encode()
    signature = "v0=" + hmac.new(b"s3cr3t", message, hashlib.sha256).hexdigest()

    client = TestClient(app)
    try:
        response = client.post(
            "/zoom/webhook",
            content=body,
            headers={
                "content-type": "application/json",
                "x-zm-signature": signature,
                "x-zm-request-timestamp": timestamp,
            },
        )
    finally:
        del zoom_adapters["42"]

    assert response.status_code == 200
    assert len(adapter.received) == 1
