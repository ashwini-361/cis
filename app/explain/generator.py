"""Explainer: ParticipantState -> Verdict.reasons[] per docs/ARCHITECTURE.md §1.7.

Answers "why" a candidate was (or wasn't) chosen, kept separate from
app/fusion/engine.py's decide() (which only answers "who") -- decide() takes
an Explainer as a dependency rather than formatting reasons itself.
"""

from __future__ import annotations

from app.schema import ParticipantState, RejectedHypothesis

_MAX_REASONS = 7
_MAX_REJECTED_NEGATIVE_REASONS = 3


class Explainer:
    def render(
        self, top_state: ParticipantState, runner_state: ParticipantState | None
    ) -> tuple[list[str], list[RejectedHypothesis]]:
        reasons: list[str] = []
        sorted_evidence = sorted(
            top_state.raw_evidence, key=lambda e: e.weight * e.score, reverse=True
        )
        for evidence in sorted_evidence[:_MAX_REASONS]:
            contribution = evidence.weight * evidence.score
            if contribution > 0:
                reasons.append(f"{evidence.reason} (+{contribution:.3f})")

        rejected: list[RejectedHypothesis] = []
        if runner_state is not None:
            lowest_contribution = sorted(
                runner_state.raw_evidence, key=lambda e: e.weight * e.score
            )
            rejected.append(
                RejectedHypothesis(
                    participant_id=runner_state.participant_id,
                    display_name=runner_state.display_name,
                    confidence=runner_state.confidence,
                    top_negative_reasons=[
                        e.reason for e in lowest_contribution[:_MAX_REJECTED_NEGATIVE_REASONS]
                    ],
                )
            )

        return reasons, rejected
