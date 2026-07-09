"""EventBus: in-process asyncio.Queue fan-out + optional Redis pub/sub.

Per docs/ARCHITECTURE.md §1.2 and docs/DATA_CONTRACT.md §2.3.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from app.schema import Event, EventType

logger = logging.getLogger(__name__)

Callback = Callable[[Event], Awaitable[None]]


class _Subscription:
    """One subscriber's private FIFO queue + consumer task."""

    def __init__(self, callback: Callback) -> None:
        self.callback = callback
        self.queue: asyncio.Queue[Event] = asyncio.Queue()
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._consume())

    async def _consume(self) -> None:
        while True:
            event = await self.queue.get()
            try:
                await self.callback(event)
            except Exception:
                logger.exception("subscriber callback raised for event %s", event.type)
            finally:
                self.queue.task_done()

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass


class EventBus:
    """Per-source FIFO + dedupe event bus.

    Redis pub/sub is optional and lazy: constructing or publishing on a bus
    with no `redis_url` never attempts network I/O.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url
        self._redis: Any = None
        self.subscribers: dict[EventType, list[_Subscription]] = defaultdict(list)
        self.sequences_seen: set[tuple[str, int]] = set()

    def _get_redis(self) -> Any:
        if self._redis is None and self._redis_url is not None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self._redis_url)
        return self._redis

    async def publish(self, event: Event) -> None:
        key = (event.envelope.source, event.envelope.sequence)
        if key in self.sequences_seen:
            return  # duplicate (source, sequence) per DATA_CONTRACT.md §2.3 — dropped
        self.sequences_seen.add(key)

        redis_client = self._get_redis()
        if redis_client is not None:
            await redis_client.publish(f"events:{event.type.value}", event.model_dump_json())

        for sub in self.subscribers[event.type]:
            sub.start()
            await sub.queue.put(event)

    def subscribe(self, event_types: list[EventType], callback: Callback) -> None:
        sub = _Subscription(callback)
        for et in event_types:
            self.subscribers[et].append(sub)

    async def unsubscribe(self, event_types: list[EventType], callback: Callback) -> None:
        for et in event_types:
            remaining = []
            for sub in self.subscribers[et]:
                if sub.callback is callback:
                    await sub.stop()
                else:
                    remaining.append(sub)
            self.subscribers[et] = remaining

    async def close(self) -> None:
        for subs in self.subscribers.values():
            for sub in subs:
                await sub.stop()
        if self._redis is not None:
            await self._redis.aclose()
