"""IngestAdapter ABC per docs/PLATFORM_INTEGRATION.md §1."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.schema import Event, SessionEnvelope


class IngestAdapter(ABC):
    """All platform adapters (Zoom, Meet, Mock) implement this interface.

    `start_session` and `end_session` are side-effect-only (they cannot yield);
    `stream_events` is the sole generator and is responsible for emitting
    `SESSION_START` first and `SESSION_END` last.
    """

    @abstractmethod
    async def start_session(self, session_envelope: SessionEnvelope) -> None: ...

    @abstractmethod
    def stream_events(self) -> AsyncIterator[Event]: ...

    @abstractmethod
    async def end_session(self, reason: str = "normal") -> None: ...
