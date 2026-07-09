"""Analyzer ABC per docs/DATA_CONTRACT.md §8."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.schema import Event, Evidence, SessionEnvelope, WeightTable


class Analyzer(ABC):
    """All analyzers implement this interface. Nothing more.

    `initialize`/`on_event`/`on_tick`/`shutdown` are `async def` here even
    though docs/DATA_CONTRACT.md §8's snippet shows plain `def` -- later
    analyzers (LLM/vision calls) need real I/O, and docs/ROADMAP.md §4.3's
    own sample test awaits `on_event`.
    """

    @property
    @abstractmethod
    def feature(self) -> str:
        """The feature key this analyzer owns (e.g. 'name_similarity')."""

    @property
    @abstractmethod
    def source(self) -> str:
        """The analyzer id used in Evidence.source (e.g. 'metadata_analyzer')."""

    @abstractmethod
    async def initialize(self, weights: WeightTable, session: SessionEnvelope) -> None:
        """Called once on SESSION_START. Load weight, set up state."""

    @abstractmethod
    async def on_event(self, event: Event) -> list[Evidence]:
        """Called for every event on the bus. Returns 0 or more Evidence records.

        Idempotent: re-running the same event with the same envelope.sequence
        MUST produce no new evidence.
        """

    async def on_tick(self, t: float) -> list[Evidence]:
        """Optional. Called every 5s by the realtime ticker. Default: no-op."""
        return []

    async def shutdown(self) -> None:  # noqa: B027 -- intentional optional-override, not abstract
        """Optional cleanup. Default: no-op."""
