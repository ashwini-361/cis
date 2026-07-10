"""ScriptedLLMProvider \u2014 deterministic stand-in for ``TranscriptRoleAnalyzer``.

Implements the same ``LLMProvider`` protocol the real
``OpenAICompatibleProvider`` does, but classifies roles from transcript
text using simple deterministic rules rather than an actual LLM. Reproducible
+ offline so ``scripts/run_accuracy.py`` and the harness tests never touch
the network.

Rule-of-thumb encoding the same cues the real ``_SYSTEM_PROMPT`` lists:

- **interviewer**: ends in ``?``, contains an imperative question-start verb
  ("tell", "describe", "walk me through", "what", "why", "how", "can you"),
  or has 2+ question marks in one utterance.
- **candidate**: first-person singular ("I ", "I'm", "I've", "my "), talks
  about themselves ("years of experience", "I built", etc.), or starts with
  "yes" (candidate answering before asking a follow-up).
- **observer**: didn't speak (skipped \u2014 no segment, so the analyzer already
  omits them via its OWN bookkeeping).
- **unclear**: <2 strong cues \u2192 confidence 0.0; returned to ``role: unclear``
  so the analyzer drops the record (``_results_to_evidence`` filters those).

**Aggregation**: the real LLM returns *one entry per participant* after
seeing all segments in the window (DATA_CONTRACT.md \u00a76). This provider
follows the same contract: it classifies each segment independently and then
*votes* per participant (summing confidence by role; winner-takes-all per
participant). This avoids same-tick evidence collision that would otherwise
cancel via ``apply_supersedes``.

Heuristic, by construction \u2014 ``docs/EVALUATION.md \u00a710`` already discloses
mock-data accuracy is not a generalization claim. The script is visibly a
fixture, not an LLM-quality assertion.
"""

from __future__ import annotations

import json
import re
from typing import Any

_INTERVIEWER_RE = re.compile(
    r"\?|^\s*(tell me|describe|walk me through|what |why |how |can you|do you)",
    re.IGNORECASE | re.MULTILINE,
)
_CANDIDATE_RE = re.compile(
    r"\b(i'm|i've|i am|i built|i have|i worked|i drew|i want|i'm drawn)\b|"
    r"\byears of (experience|work)\b|\bmy (current|role|experience)\b|"
    r"^\s*yes[\s,\u2014\-]",  # "Yes \u2014 ...", "Yes, ...", "Yes " at line start = candidate
    re.IGNORECASE | re.MULTILINE,
)


def _classify(text: str) -> tuple[str, float]:
    """Return (role, confidence) per the rules above."""

    iv = bool(_INTERVIEWER_RE.search(text))
    cand = bool(_CANDIDATE_RE.search(text))

    if cand and not iv:
        return ("candidate", 0.85)

    if iv and not cand:
        bonus = 0.15 if "?" in text else 0.0
        bonus += 0.15 if "?" in text and "tell" in text.lower() else 0.0
        score = min(1.0, 0.55 + bonus)
        return ("interviewer", score)

    if iv and cand:
        # A line that starts with "yes" is a candidate answering first,
        # then possibly asking a follow-up \u2014 treat as candidate regardless.
        if re.match(r"^\s*yes\b", text, re.IGNORECASE):
            return ("candidate", 0.70)
        if text.strip().endswith("?"):
            return ("interviewer", 0.65)
        return ("candidate", 0.70)

    return ("unclear", 0.0)


class ScriptedLLMProvider:
    """Deterministic transcript-role classifier. Same surface as the real provider.

    ``complete_json(system_prompt, user_prompt)`` parses the user prompt's
    segment JSON (the same shape ``TranscriptRoleAnalyzer`` builds with
    ``json.dumps([{...}])``), runs the heuristic per segment, and returns
    a JSON array of ``{participant_id, role, confidence}`` with **one entry
    per participant** \u2014 matching the real LLM's contract (the system prompt
    says "one entry per participant").

    Aggregation: classify each segment independently, sum confidence by role
    per participant, winner-takes-all.  Confidence is clamped to [0, 1].
    """

    def complete_json(self, system_prompt: str, user_prompt: str) -> Any:
        segments = _extract_segments(user_prompt)

        # Accumulate per-participant votes: {pid: {role: total_confidence}}
        votes: dict[str, dict[str, float]] = {}
        for segment in segments:
            role, confidence = _classify(segment.get("text", ""))
            pid = segment.get("participant_id", "")
            if role == "unclear" or not pid:
                continue
            votes.setdefault(pid, {})
            votes[pid][role] = votes[pid].get(role, 0.0) + confidence

        # One result per participant
        results: list[dict[str, Any]] = []
        for pid, role_scores in votes.items():
            if not role_scores:
                continue
            best_role = max(role_scores, key=lambda r: role_scores[r])
            # Clamp: multiple winning segments can push total above 1.0
            best_confidence = min(1.0, role_scores[best_role])
            results.append(
                {
                    "participant_id": pid,
                    "role": best_role,
                    "confidence": best_confidence,
                }
            )
        return results


def _extract_segments(user_prompt: str) -> list[dict[str, Any]]:
    """Pull the segment list out of the prompt the analyzer builds.

    Format produced by ``TranscriptRoleAnalyzer._call_llm``::

        f"Transcript:\\n{segments_json}"

    where ``segments_json`` is ``json.dumps([{participant_id, text, ...}])``.
    Falls back to ``[]`` for any unparsable prompt.
    """

    marker = "Transcript:\n"
    idx = user_prompt.find(marker)
    if idx == -1:
        return []
    raw = user_prompt[idx + len(marker):].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return list(parsed) if isinstance(parsed, list) else []
