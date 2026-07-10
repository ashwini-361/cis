"""Accuracy metrics — pure functions over verdict lists.

Implements docs/ACCURACY_METRICS.md §1–§2:
  - ``precision_at_1`` / ``precision_at_1_at_decision``
  - ``time_to_decision``
  - ``flips``
  - ``ScenarioReport`` / ``DatasetSummary`` / ``summarize``

No pipeline code lives here; all functions accept a ``list[Verdict]``
that the caller obtained by replaying a recording through ``run_session``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.schema import Verdict

# ---------------------------------------------------------------------------
# Scalar metrics
# ---------------------------------------------------------------------------


def precision_at_1(verdicts: list[Verdict], ground_truth: str | None) -> float:
    """1.0 if the *final* verdict's ``candidate_id`` matches ground truth."""
    if not verdicts or ground_truth is None:
        return 0.0
    return 1.0 if verdicts[-1].candidate_id == ground_truth else 0.0


def precision_at_1_at_decision(
    verdicts: list[Verdict], ground_truth: str | None
) -> float | None:
    """Same as :func:`precision_at_1` but at the *first* ``is_decision=True`` verdict.

    Returns ``None`` if no decidable verdict was ever emitted.
    """
    if ground_truth is None:
        return None
    first_dec = next((v for v in verdicts if v.is_decision), None)
    if first_dec is None:
        return None
    return 1.0 if first_dec.candidate_id == ground_truth else 0.0


def time_to_decision(verdicts: list[Verdict]) -> float | None:
    """``ts`` of the first ``is_decision=True`` verdict; ``None`` if never decided."""
    return next((v.ts for v in verdicts if v.is_decision), None)


def flips(verdicts: list[Verdict]) -> int:
    """Count ``candidate_id`` transitions *after* the first decidable verdict.

    A flip is a change in who the top candidate is once the system has
    already committed. Zero flips = stable after first decision.
    """
    first_dec_idx = next((i for i, v in enumerate(verdicts) if v.is_decision), None)
    if first_dec_idx is None:
        return 0
    after = verdicts[first_dec_idx:]
    return sum(
        1
        for i in range(1, len(after))
        if after[i].candidate_id != after[i - 1].candidate_id
    )


# ---------------------------------------------------------------------------
# Aggregate types
# ---------------------------------------------------------------------------


@dataclass
class ScenarioReport:
    """Per-scenario metrics computed from a replay verdict list."""

    scenario_id: str
    ground_truth_id: str | None
    final_candidate_id: str | None
    precision_at_1: float
    precision_at_1_at_decision: float | None
    time_to_decision: float | None
    flips: int
    # runner_up_confidence at first decision verdict; None if no decision.
    runner_up_confidence: float | None


@dataclass
class DatasetSummary:
    """Dataset-level aggregate over a list of ScenarioReports."""

    precision_at_1: float
    time_to_decision_p50: float | None
    time_to_decision_p90: float | None
    flips_mean: float
    scenario_reports: list[ScenarioReport] = field(default_factory=list)


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    """Nearest-rank percentile (1-based rank, 0-based Python index)."""
    if not sorted_vals:
        return None
    idx = math.ceil(p / 100.0 * len(sorted_vals)) - 1
    idx = max(0, min(idx, len(sorted_vals) - 1))
    return sorted_vals[idx]


def summarize(reports: list[ScenarioReport]) -> DatasetSummary:
    """Aggregate per-scenario reports into a dataset-level summary."""
    if not reports:
        return DatasetSummary(
            precision_at_1=0.0,
            time_to_decision_p50=None,
            time_to_decision_p90=None,
            flips_mean=0.0,
        )
    pa1 = sum(r.precision_at_1 for r in reports) / len(reports)
    ttds = sorted(r.time_to_decision for r in reports if r.time_to_decision is not None)
    flips_mean = sum(r.flips for r in reports) / len(reports)
    return DatasetSummary(
        precision_at_1=pa1,
        time_to_decision_p50=_percentile(ttds, 50),
        time_to_decision_p90=_percentile(ttds, 90),
        flips_mean=flips_mean,
        scenario_reports=list(reports),
    )
