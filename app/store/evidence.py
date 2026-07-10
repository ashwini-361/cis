"""EvidenceStore per docs/DATA_CONTRACT.md §3 and docs/ARCHITECTURE.md §1.4.

Redis-backed when a ``redis_url`` is given; falls back to an in-memory
dict otherwise — same lazy-optional pattern as ``EventBus`` and
``ParticipantStateStore`` so tests and the offline harness never need
``docker compose up``.

Read semantics: ``apply_supersedes`` is the reader's job (already a pure
helper in ``app.fusion.engine``). The store simply returns the full
evidence list for a participant; ``apply_supersedes`` is invoked at the
single boundary (the ticker's ``get_evidences`` provider) so the store
stays naïve.
"""

from __future__ import annotations

from typing import Any

from app.schema import Evidence


class EvidenceStore:
    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url
        self._redis: Any = None
        # session_id -> participant_id -> [Evidence]
        self._memory: dict[str, dict[str, list[Evidence]]] = {}

    def _get_redis(self) -> Any:
        if self._redis is None and self._redis_url is not None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self._redis_url)
        return self._redis

    @staticmethod
    def _key(session_id: str, participant_id: str) -> str:
        return f"evidence:{session_id}:{participant_id}"

    async def append(self, evidence: Evidence) -> None:
        redis_client = self._get_redis()
        if redis_client is not None:
            await redis_client.rpush(self._key(evidence.session_id, evidence.participant_id),
                                     evidence.model_dump_json())
            return
        self._memory.setdefault(evidence.session_id, {}).setdefault(
            evidence.participant_id, []
        ).append(evidence)

    async def get(
        self, session_id: str, participant_id: str
    ) -> list[Evidence]:
        redis_client = self._get_redis()
        if redis_client is not None:
            raw_items = await redis_client.lrange(
                self._key(session_id, participant_id), 0, -1
            )
            return [Evidence.model_validate_json(raw) for raw in raw_items]
        return list(
            self._memory.get(session_id, {}).get(participant_id, [])
        )

    async def get_all(self, session_id: str) -> list[Evidence]:
        redis_client = self._get_redis()
        if redis_client is not None:
            # Would need a session->participants index. Not built yet —
            # the harness/offline path and the live 5s ticker both use
            # get(session, pid) (one call per participant), so the index
            # is deferred until something needs it.
            raise NotImplementedError(
                "Redis-backed get_all requires a session->participant index; "
                "deferred until a later phase needs it."
            )
        flat: list[Evidence] = []
        for by_participant in self._memory.get(session_id, {}).values():
            flat.extend(by_participant)
        return flat
