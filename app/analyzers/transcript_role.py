"""TranscriptRoleAnalyzer: transcript_role evidence per docs/SIGNALS.md §6.

LLM provider is swappable (docs/ROADMAP.md §5.3): OpenAICompatibleProvider
wraps the already-installed `openai` client for real use; tests inject a
FakeLLMProvider test double instead (same pattern as MockAdapter.sleep_fn
and ScreenShareAnalyzer.classify). LLMProvider.complete_json is typed to
return Any rather than the doc's literal `dict`, since the LLM's actual
response is a JSON array (a `list`), not a `dict` -- see the Phase 5 plan's
discrepancy notes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.analyzers.base import Analyzer
from app.schema import Event, EventType, Evidence, SessionEnvelope, WeightTable

_WINDOW_SEC = 60.0
_MIN_SEGMENTS = 3
_EXPIRES_DELAY_SEC = 600.0
_STRICT_SUFFIX = "Return strict JSON only. No markdown."

_SYSTEM_PROMPT = (
    "You are an interview-role classifier. For each participant in the transcript "
    "below, return a JSON object with:\n"
    '  participant_id, role in {"interviewer", "candidate", "observer", "unclear"}, '
    "confidence in [0,1]\n\n"
    "Use these cues:\n"
    "- Interviewer: asks questions, sets topics, controls the flow.\n"
    "- Candidate: answers questions, talks about themselves, screen-shares their work.\n"
    "- Observer: listens, doesn't speak or speaks very briefly.\n"
    "- Unclear: insufficient evidence in this window.\n\n"
    "Return a JSON array, one entry per participant. No prose."
)


class LLMProvider(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> Any: ...


class OpenAICompatibleProvider:
    """Real provider wrapping the openai client. See docs/SIGNALS.md §6.8."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    def complete_json(self, system_prompt: str, user_prompt: str) -> Any:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        return json.loads(content) if content is not None else []


@dataclass
class _Segment:
    participant_id: str
    text: str
    start_sec: float
    end_sec: float


class TranscriptRoleAnalyzer(Analyzer):
    """Owns transcript_role (0.25). Re-fires every 5s via on_tick (LLM-backed)."""

    def __init__(self, provider: LLMProvider) -> None:
        self._weight = 0.0
        self._session_id: str | None = None
        self._provider = provider
        self._segments: list[_Segment] = []
        self._seen: set[tuple[str, int]] = set()
        self._last_cache_key: str | None = None
        self._last_result: list[dict[str, Any]] = []

    @property
    def feature(self) -> str:
        return "transcript_role"

    @property
    def source(self) -> str:
        return "transcript_role_analyzer"

    async def initialize(self, weights: WeightTable, session: SessionEnvelope) -> None:
        self._weight = weights.weights["transcript_role"]
        self._session_id = session.session_id

    async def on_event(self, event: Event) -> list[Evidence]:
        key = (event.envelope.source, event.envelope.sequence)
        if key in self._seen:
            return []
        self._seen.add(key)

        if event.type == EventType.TRANSCRIPT_SEGMENT:
            self._segments.append(
                _Segment(
                    participant_id=event.payload["participant_id"],
                    text=event.payload["text"],
                    start_sec=event.payload["start_sec"],
                    end_sec=event.payload["end_sec"],
                )
            )
            return []

        return []

    async def on_tick(self, t: float) -> list[Evidence]:
        assert self._session_id is not None, "initialize() must be called before on_tick"
        window = [s for s in self._segments if t - s.start_sec <= _WINDOW_SEC]
        if len(window) < _MIN_SEGMENTS:
            return []

        ordered = sorted(window, key=lambda s: s.start_sec)
        window_text = "\n".join(f"{s.participant_id}: {s.text}" for s in ordered)
        cache_key = hashlib.sha256(window_text.encode("utf-8")).hexdigest()

        if cache_key == self._last_cache_key:
            results = self._last_result
        else:
            segments_json = json.dumps(
                [
                    {
                        "participant_id": s.participant_id,
                        "text": s.text,
                        "start_sec": s.start_sec,
                        "end_sec": s.end_sec,
                    }
                    for s in ordered
                ]
            )
            user_prompt = f"Transcript:\n{segments_json}"
            parsed = self._call_llm(user_prompt)
            if parsed is None:
                return []
            results = parsed
            self._last_cache_key = cache_key
            self._last_result = results

        return self._results_to_evidence(results, t)

    def _call_llm(self, user_prompt: str) -> list[dict[str, Any]] | None:
        for system_prompt in (_SYSTEM_PROMPT, f"{_SYSTEM_PROMPT}\n{_STRICT_SUFFIX}"):
            try:
                raw = self._provider.complete_json(system_prompt, user_prompt)
                if isinstance(raw, str):
                    raw = json.loads(raw)
                if isinstance(raw, list):
                    return raw
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return None

    def _results_to_evidence(self, results: list[dict[str, Any]], t: float) -> list[Evidence]:
        assert self._session_id is not None
        evidences: list[Evidence] = []
        for entry in results:
            role = entry.get("role")
            participant_id = entry.get("participant_id")
            confidence = entry.get("confidence", 0.0)
            if role is None or participant_id is None or role == "unclear":
                continue
            score = confidence if role == "candidate" else 0.0
            evidences.append(
                Evidence(
                    session_id=self._session_id,
                    participant_id=participant_id,
                    feature="transcript_role",
                    source=self.source,
                    score=score,
                    weight=self._weight,
                    reason=f"LLM classified role as '{role}' (confidence {confidence:.2f})",
                    ts=t,
                    expires_at=t + _EXPIRES_DELAY_SEC,
                    supersedes="transcript_role",
                )
            )
        return evidences
