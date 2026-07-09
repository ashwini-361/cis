"""ParticipantStateStore per docs/DATA_CONTRACT.md §4 and docs/ARCHITECTURE.md §1.5.

Redis-backed when a `redis_url` is given; falls back to an in-memory dict
otherwise so tests never require `docker compose up` (same lazy-optional
pattern as app/bus.py's EventBus).
"""

from __future__ import annotations

from typing import Any

from app.schema import ParticipantState


class ParticipantStateStore:
    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url
        self._redis: Any = None
        self._memory: dict[tuple[str, str], ParticipantState] = {}

    def _get_redis(self) -> Any:
        if self._redis is None and self._redis_url is not None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self._redis_url)
        return self._redis

    @staticmethod
    def _key(session_id: str, participant_id: str) -> str:
        return f"state:{session_id}:{participant_id}"

    async def get(self, session_id: str, participant_id: str) -> ParticipantState | None:
        redis_client = self._get_redis()
        if redis_client is not None:
            raw = await redis_client.get(self._key(session_id, participant_id))
            return ParticipantState.model_validate_json(raw) if raw is not None else None
        return self._memory.get((session_id, participant_id))

    async def set(self, state: ParticipantState) -> None:
        redis_client = self._get_redis()
        if redis_client is not None:
            await redis_client.set(
                self._key(state.session_id, state.participant_id), state.model_dump_json()
            )
            return
        self._memory[(state.session_id, state.participant_id)] = state

    async def get_all(self, session_id: str) -> list[ParticipantState]:
        redis_client = self._get_redis()
        if redis_client is not None:
            raise NotImplementedError(
                "Redis-backed get_all requires a session->participant index; "
                "deferred until a later phase needs it."
            )
        return [state for (sid, _), state in self._memory.items() if sid == session_id]
