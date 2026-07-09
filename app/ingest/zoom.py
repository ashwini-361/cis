"""ZoomAdapter: Zoom (Server-to-Server OAuth + webhooks + recording pull) ingest.

Per docs/PLATFORM_INTEGRATION.md §2. Reuses app.ingest.meet.Transcriber /
FasterWhisperTranscriber for the per-track Whisper step rather than
duplicating a second transcription pipeline.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from app.ingest.base import IngestAdapter
from app.ingest.meet import Transcriber
from app.schema import Event, EventEnvelope, EventType, SessionEnvelope

_TOKEN_EXPIRY_SAFETY_MARGIN_SEC = 60.0
_ZOOM_OAUTH_URL = "https://zoom.us/oauth/token"
_ZOOM_API_BASE = "https://api.zoom.us/v2"

_WEBHOOK_EVENT_MAP: dict[str, EventType] = {
    "meeting.participant_joined": EventType.PARTICIPANT_JOINED,
    "meeting.participant_left": EventType.PARTICIPANT_LEFT,
    "meeting.participant_screen_sharing_started": EventType.SCREEN_SHARE_START,
    "meeting.participant_screen_sharing_stopped": EventType.SCREEN_SHARE_STOP,
    "meeting.participant_video_started": EventType.WEBCAM_ON,
    "meeting.participant_video_stopped": EventType.WEBCAM_OFF,
}


class TokenStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...


class KeyringTokenStore:
    """Real backend: OS keychain via the `keyring` library."""

    _SERVICE_NAME = "cis-zoom"

    def get(self, key: str) -> str | None:
        import keyring

        return keyring.get_password(self._SERVICE_NAME, key)

    def set(self, key: str, value: str) -> None:
        import keyring

        keyring.set_password(self._SERVICE_NAME, key, value)


def verify_webhook_signature(
    secret_token: str, timestamp: str, raw_body: bytes, signature_header: str
) -> bool:
    """HMAC-SHA256 over `v0:{timestamp}:{raw_body}`; signature_header is `v0=<hex>`."""
    message = f"v0:{timestamp}:{raw_body.decode('utf-8')}".encode()
    expected = "v0=" + hmac.new(secret_token.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def handle_url_validation(plain_token: str, secret_token: str) -> dict[str, str]:
    """Zoom's required webhook-registration challenge-response."""
    encrypted = hmac.new(secret_token.encode(), plain_token.encode(), hashlib.sha256).hexdigest()
    return {"plainToken": plain_token, "encryptedToken": encrypted}


def map_webhook_event(zoom_event: dict[str, Any]) -> dict[str, Any] | None:
    """Zoom webhook payload -> Event shorthand dict (type/ts/payload).

    Per docs/PLATFORM_INTEGRATION.md §2.2/§2.6. Returns None for event types
    this adapter doesn't map (e.g. meeting.started, meeting.ended -- the
    latter is handled separately by ZoomAdapter.push_webhook_event to
    trigger the recording pull, not turned into a plain Event).
    """
    event_type = _WEBHOOK_EVENT_MAP.get(zoom_event.get("event", ""))
    if event_type is None:
        return None

    participant = zoom_event.get("payload", {}).get("object", {}).get("participant", {})
    ts = zoom_event.get("event_ts", time.time() * 1000) / 1000.0
    participant_id = participant.get("user_id") or participant.get("id")

    if event_type == EventType.PARTICIPANT_JOINED:
        payload = {
            "participant_id": participant_id,
            "display_name": participant.get("user_name"),
            "email": participant.get("email"),
            "device_name": participant.get("device"),
            "join_order": participant.get("join_order", 0),
        }
    elif event_type == EventType.PARTICIPANT_LEFT:
        payload = {"participant_id": participant_id, "leave_ts": ts}
    else:
        payload = {"participant_id": participant_id}

    return {"type": event_type.name, "ts": ts, "payload": payload}


class ZoomAuth:
    """Server-to-Server OAuth (account_credentials grant), per §2.1.

    No classic authorization-code OAuth support -- see the Phase 7a plan's
    discrepancy #1 for why only the Server-to-Server path is implemented.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        account_id: str,
        token_store: TokenStore,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._account_id = account_id
        self._token_store = token_store
        self._http_client = http_client
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    async def get_access_token(self) -> str:
        if self._access_token is not None and time.time() < self._expires_at:
            return self._access_token
        await self._authenticate()
        assert self._access_token is not None
        return self._access_token

    async def _authenticate(self) -> None:
        response = await self._http_client.post(
            _ZOOM_OAUTH_URL,
            params={"grant_type": "account_credentials", "account_id": self._account_id},
            auth=(self._client_id, self._client_secret),
        )
        response.raise_for_status()
        data = response.json()
        self._access_token = data["access_token"]
        self._expires_at = time.time() + data["expires_in"] - _TOKEN_EXPIRY_SAFETY_MARGIN_SEC
        self._token_store.set("access_token", self._access_token)


class ZoomAPIClient:
    def __init__(self, auth: ZoomAuth, http_client: httpx.AsyncClient) -> None:
        self._auth = auth
        self._http_client = http_client

    async def _headers(self) -> dict[str, str]:
        token = await self._auth.get_access_token()
        return {"Authorization": f"Bearer {token}"}

    async def get_recordings(self, meeting_id: str) -> list[dict[str, Any]]:
        response = await self._http_client.get(
            f"{_ZOOM_API_BASE}/meetings/{meeting_id}/recordings",
            headers=await self._headers(),
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return list(data.get("recording_files", []))

    async def download_recording_file(self, download_url: str) -> bytes:
        response = await self._http_client.get(download_url, headers=await self._headers())
        response.raise_for_status()
        return response.content


class ZoomAdapter(IngestAdapter):
    """Bridges Zoom webhook events + post-call recording pull into the Event stream."""

    def __init__(self, api_client: ZoomAPIClient, transcriber: Transcriber) -> None:
        self._api_client = api_client
        self._transcriber = transcriber
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._session_envelope: SessionEnvelope | None = None
        self._sequence = 0
        self._source = "zoom.webhook"
        self._ended = asyncio.Event()

    def _next_envelope(self, ts: float) -> EventEnvelope:
        assert self._session_envelope is not None, "start_session() must be called first"
        envelope = EventEnvelope(
            session_id=self._session_envelope.session_id,
            ts=ts,
            wall_clock=datetime.now(UTC).isoformat(),
            platform="zoom",
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

    async def push_webhook_event(self, zoom_event: dict[str, Any]) -> None:
        if zoom_event.get("event") == "meeting.ended":
            await self._pull_recording(zoom_event)
            return

        mapped = map_webhook_event(zoom_event)
        if mapped is None:
            return
        await self._queue.put(
            Event(
                type=EventType[mapped["type"]],
                envelope=self._next_envelope(mapped["ts"]),
                payload=mapped["payload"],
            )
        )

    async def _pull_recording(self, zoom_event: dict[str, Any]) -> None:
        meeting_id = zoom_event.get("payload", {}).get("object", {}).get("id")
        recordings = await self._api_client.get_recordings(str(meeting_id))
        for track in recordings:
            participant_id = track.get("recording_start_participant_id", track.get("id", "unknown"))
            audio_bytes = await self._api_client.download_recording_file(track["download_url"])
            segments = await self._transcriber.transcribe(audio_bytes, participant_id)
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
