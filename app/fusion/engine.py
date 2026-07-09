"""v1-weighted fusion engine per docs/DATA_CONTRACT.md §4.3/§5.2 and docs/ROADMAP.md §3.2."""

from __future__ import annotations

import math

from app.explain.generator import Explainer
from app.schema import Evidence, ParticipantState, Verdict

_DEFAULT_THRESHOLD = 0.55
_DEFAULT_MARGIN = 0.20


def apply_supersedes(evidences: list[Evidence]) -> list[Evidence]:
    """Drop evidence superseded by a later same-participant record.

    Normally EvidenceStore's job (docs/ARCHITECTURE.md §1.4); implemented here
    as a pure helper since the real store isn't built yet. Note: a superseding
    evidence's own `feature` is typically the same key it supersedes (replacing
    the prior record for that feature), so matching must exclude the
    superseding evidence itself and only drop strictly-other, older-or-equal
    records for the same participant + feature.
    """
    to_remove: set[int] = set()
    for e in evidences:
        if e.supersedes is None:
            continue
        for other in evidences:
            if (
                other is not e
                and other.participant_id == e.participant_id
                and other.feature == e.supersedes
                and other.ts <= e.ts
            ):
                to_remove.add(id(other))
    return [e for e in evidences if id(e) not in to_remove]


def fuse(evidences: list[Evidence], t: float) -> float:
    numerator = 0.0
    denominator = 0.0
    for e in evidences:
        if e.expires_at is None:
            decay = 1.0
        else:
            age = max(0.0, t - e.ts)
            half_life = e.expires_at - e.ts
            decay = math.exp(-math.log(2) * age / half_life) if half_life > 0 else 1.0
        numerator += e.weight * e.score * decay
        denominator += e.weight * decay
    if denominator < 1e-6:
        return 0.0
    return numerator / denominator


def decide(
    session_id: str,
    platform: str,
    states: list[ParticipantState],
    t: float,
    explainer: Explainer,
    threshold: float = _DEFAULT_THRESHOLD,
    margin: float = _DEFAULT_MARGIN,
) -> Verdict:
    """The threshold+margin gate per docs/DATA_CONTRACT.md §5.2.

    Answers "who" only -- reason/rejected-hypothesis formatting ("why") is
    delegated to the injected `explainer`, kept as a separate, independently
    testable concern rather than inlined here.
    """
    all_evidence = [e for s in states for e in s.raw_evidence]
    analyzer_count = len({e.source for e in all_evidence})
    total_evidence = len(all_evidence)

    if not states:
        return Verdict(
            session_id=session_id,
            ts=t,
            platform=platform,
            candidate_id=None,
            candidate_name=None,
            confidence=None,
            runner_up_id=None,
            runner_up_confidence=None,
            margin=None,
            reasons=["no participants yet"],
            is_decision=False,
            not_deciding_reason="no participants",
            analyzer_count=0,
            total_evidence=0,
        )

    sorted_states = sorted(states, key=lambda s: s.confidence, reverse=True)
    top = sorted_states[0]
    runner = sorted_states[1] if len(sorted_states) > 1 else None
    provisional_reasons = [
        f'Top candidate so far: {top.participant_id} "{top.display_name}" ({top.confidence:.2f})'
    ]

    if top.confidence < threshold:
        return Verdict(
            session_id=session_id,
            ts=t,
            platform=platform,
            candidate_id=None,
            candidate_name=None,
            confidence=None,
            runner_up_id=runner.participant_id if runner else None,
            runner_up_confidence=runner.confidence if runner else None,
            margin=None,
            reasons=provisional_reasons,
            is_decision=False,
            not_deciding_reason=f"top confidence {top.confidence:.2f} < threshold {threshold}",
            analyzer_count=analyzer_count,
            total_evidence=total_evidence,
        )

    observed_margin = top.confidence - runner.confidence if runner is not None else top.confidence
    if runner is not None and observed_margin < margin:
        return Verdict(
            session_id=session_id,
            ts=t,
            platform=platform,
            candidate_id=None,
            candidate_name=None,
            confidence=None,
            runner_up_id=runner.participant_id,
            runner_up_confidence=runner.confidence,
            margin=observed_margin,
            reasons=provisional_reasons,
            is_decision=False,
            not_deciding_reason=f"margin {observed_margin:.2f} < required {margin}",
            analyzer_count=analyzer_count,
            total_evidence=total_evidence,
        )

    reasons, rejected_hypotheses = explainer.render(top, runner)
    return Verdict(
        session_id=session_id,
        ts=t,
        platform=platform,
        candidate_id=top.participant_id,
        candidate_name=top.display_name,
        confidence=top.confidence,
        runner_up_id=runner.participant_id if runner else None,
        runner_up_confidence=runner.confidence if runner else None,
        margin=observed_margin,
        reasons=reasons,
        rejected_hypotheses=rejected_hypotheses,
        is_decision=True,
        analyzer_count=analyzer_count,
        total_evidence=total_evidence,
    )
