"""AnalyzerRegistry tests."""

from __future__ import annotations

from app.analyzers.transcript_role import TranscriptRoleAnalyzer
from app.analyzers.vision import VisionAnalyzer
from app.harness.scripted_llm import ScriptedLLMProvider
from app.runtime.registry import AnalyzerRegistry, build_default


def test_build_default_returns_all_seven_analyzers(weights) -> None:
    analyzers = build_default(weights, ScriptedLLMProvider())
    assert len(analyzers) == 7
    sources = {a.source for a in analyzers}
    assert sources == {
        "transcript_role_analyzer",
        "metadata_analyzer",
        "speaking_pattern_analyzer",
        "join_order_analyzer",
        "webcam_analyzer",
        "screen_share_analyzer",
        "vision_analyzer",
    }


def test_transcript_role_receives_the_injected_llm_provider(weights) -> None:
    llm = ScriptedLLMProvider()
    analyzers = build_default(weights, llm)
    tr = next(a for a in analyzers if isinstance(a, TranscriptRoleAnalyzer))
    assert tr is not None
    # Same instance reference proves the registry wired the injected provider.
    assert tr._provider is llm  # type: ignore[attr-defined]


def test_vision_default_disabled_when_flag_omitted(weights) -> None:
    analyzers = build_default(weights, ScriptedLLMProvider())
    vision = next(a for a in analyzers if isinstance(a, VisionAnalyzer))
    assert vision._enabled is False  # type: ignore[attr-defined]


def test_vision_enabled_when_flag_true(weights) -> None:
    analyzers = build_default(weights, ScriptedLLMProvider(), vision_enabled=True)
    vision = next(a for a in analyzers if isinstance(a, VisionAnalyzer))
    assert vision._enabled is True  # type: ignore[attr-defined]


def test_registry_from_weights_file_loads_committed_weights() -> None:
    reg = AnalyzerRegistry.from_weights_file()
    assert reg.weights.version == "1.0.0"
    assert reg.weights.threshold == 0.55
    assert reg.weights.margin == 0.20
