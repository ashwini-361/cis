"""AnalyzerRegistry — the canonical, order-independent analyzer set.

Builds all seven weak-signal analyzers from one ``WeightTable`` plus an
injected ``LLMProvider`` (and the already-existing ``VisionBackend`` /
``ClassifyFn`` defaults, which keep their module-level defaults).

This replaces the ad-hoc per-test construction pattern that grew across
``tests/test_analyzers/`` through Phases 4–6 and gives the runtime one
place to ask for "all analyzers, properly wired, for this session's
weights and LLM provider."

Registry is deliberately *stateless*: a fresh analyzer set per call, so
sessions never share analyzer buffers (each analyzer caches its own
``_seen`` set / transcript windows; sharing those across sessions would
cross-contaminate evidence).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.analyzers.base import Analyzer
from app.analyzers.join_order import JoinOrderAnalyzer
from app.analyzers.metadata import MetadataAnalyzer
from app.analyzers.screen_share import ScreenShareAnalyzer
from app.analyzers.speaking_pattern import SpeakingPatternAnalyzer
from app.analyzers.transcript_role import LLMProvider, TranscriptRoleAnalyzer
from app.analyzers.vision import DummyVisionBackend, VisionAnalyzer
from app.analyzers.webcam import WebcamAnalyzer
from app.config import load_weights
from app.schema import WeightTable


def build_default(
    weights: WeightTable,
    llm_provider: LLMProvider,
    *,
    vision_enabled: bool = False,
) -> list[Analyzer]:
    """All analyzers, constructed with ``weights``-derived state.

    ``llm_provider`` is the single required injectable: ``transcript_role``
    cannot construct without one, and the harness swaps in a
    ``ScriptedLLMProvider`` so the live pipeline never needs a network to
    run. The other analyzers carry their own safe defaults (the
    ``ScreenShareAnalyzer`` stub classifier, the ``DummyVisionBackend``),
    so callers pass nothing for them.

    Order is the signal-strength order from docs/SIGNALS.md (strongest
    first) — harmless since analyzers run independently, but aids
    debugging when reading an evidence log in source-order.
    """

    return [
        TranscriptRoleAnalyzer(llm_provider),
        MetadataAnalyzer(),
        SpeakingPatternAnalyzer(),
        JoinOrderAnalyzer(),
        WebcamAnalyzer(),
        ScreenShareAnalyzer(),
        VisionAnalyzer(backend=DummyVisionBackend(), enabled=vision_enabled),
    ]


@dataclass(frozen=True)
class AnalyzerRegistry:
    """Bound to a ``WeightTable`` for ergonomic session construction.

    Thin around :func:`build_default`; kept as a small object so a live
    session can hold a registry instance and call ``.build(llm)``
    per session without re-reading ``weights.json`` each time.
    """

    weights: WeightTable

    @classmethod
    def from_weights_file(cls, path: Path | str | None = None) -> AnalyzerRegistry:
        return cls(weights=load_weights(path))

    def build(self, llm_provider: LLMProvider, *, vision_enabled: bool = False) -> list[Analyzer]:
        return build_default(self.weights, llm_provider, vision_enabled=vision_enabled)
