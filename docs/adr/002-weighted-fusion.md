# ADR-002: v1 fusion is weighted-average, not Bayesian-first

> **Status:** Accepted · **Date:** 2026-07-09 · **Decider:** you · **Supersedes:** none · **Superseded by:** none (v2-Bayesian upgrade will live in ADR-006, to be drafted after `tune.py` ships)
> **Related:** [../APPROACH.md §4.3](../APPROACH.md) · [../DATA_CONTRACT.md §4.3, §5.2](../DATA_CONTRACT.md) · [../SIGNALS.md](../SIGNALS.md) · [../ACCURACY_METRICS.md §6, §9](../ACCURACY_METRICS.md) · [../EVOLUTION.md](../EVOLUTION.md)

---

## Context

The fusion engine combines N `Evidence` records per participant into a single `confidence ∈ [0,1]`. PDF grades problem-solving 25% and AI/ML approach 20%; the chosen fusion math is a top-3 decision in the rubric. PDF p3 says: "continuously update confidence", and PDF p4 explicitly rewards "produce a confidence score" — so confidence semantics matter (not just "did you pick the right person").

Two well-known options sat on the table:

| Option | Symbolic form |
|---|---|
| A — Weighted average (normalized) | `confidence = Σ (w_i · s_i · decay_i) / Σ (w_i · decay_i)` |
| B — Bayesian (Beta-prior posterior update) | `Posterior(H) ∝ Prior(H) · Π Likelihood(e_i | H)`, treated as a per-participant Beta distribution |

A third option — a single classifier (logistic regression / softmax) — was ruled out at the start because PDF p4 explicitly tells us not to rely on a single heuristic.

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| **A — Weighted average** | Trivially explainable ("email match contributes 0.30 × 1.00 = +0.30"); no priors required; deterministic; `tune.py` grid search is mechanically simple; explainability narrative writes itself. Output naturally bounded in `[0,1]`. | Subjective weights feel hand-wavy until `tune.py` validates. Confidences are NOT calibrated probabilities. |
| **B — Bayesian (Beta-prior posteriors)** | **Proper uncertainty propagation** — weak signals appropriately fail to temper strong signals. Confidence is **calibrated** (matches empirical accuracy) once priors are tuned. Mathematical elegance. | Requires calibrated per-signal priors (alpha/beta) — non-trivial out-of-box. Until ≥20 labeled sessions exist, priors are guesses that distort confidence. Explainability message "posterior on a Beta(7.5, 1.5)" is harder for a hiring manager to read than "weighted score 0.92". Tuning has more parameters (α, β per signal = 20 params vs. 10 weights). |

## Decision

**Option A — weighted-average fusion** is the v1 default. Specified in [`docs/DATA_CONTRACT.md §4.3`](../DATA_CONTRACT.md).

Concretely:
```python
def fuse(evidences, t):
    numerator = denominator = 0.0
    for e in evidences:
        decay = 1.0 if e.expires_at is None else math.exp(-math.log(2) * (t - e.ts) / (e.expires_at - e.ts))
        numerator += e.weight * e.score * decay
        denominator += e.weight * decay
    return numerator / denominator if denominator > 1e-6 else 0.0
```

The decision-gate is **threshold + margin** (`threshold = 0.55`, `margin = 0.20`) — a participant is declared the candidate only when their confidence exceeds the threshold AND exceeds the runner-up by at least the margin. Both knobs live in `weights.json`.

## Consequences

### Positive
- Confidence is interpretable in plain English in the dashboard reason panel: "Email +0.30, Transcript-role +0.225, Name similarity +0.144, ...".
- Default weights are hand-authorable and code-reviewable without a statistics background.
- A v1 reviewer can audit the math in 30 seconds.
- `tune.py` uses **coordinate descent** on the 10 weights — easy to implement, fast, won't oscillate.
- Switching to v2-Bayesian later is one JSON field (`fusion_engine: "v2-bayesian"`) plus a Bayesian engine file; both implementations sit behind the same `Fusion` Protocol. No breaking schema change.

### Negative
- Weighted-average confidences are **not calibrated** as probability estimates. A confidence of 0.85 does NOT empirically mean "85% likely". Disclosed in [EVALUATION.md §7.1](../EVALUATION.md); the demo video's "What you'd improve next" section explicitly names v2-Bayesian as the trajectory.
- Subjective weights create a risk a single over-weighted signal dominates (e.g. `email_match` at 0.30 is the highest single-signal weight). Mitigation: all weights kept ≤0.30; `tune.py` recalibrates once labeled data exists.
- Decisions are point-estimates without confidence intervals — PDF p4 "show us how your system reaches its conclusion" is harder to honor with weighted-average. Mitigation: the `reasons[]` bullets carry contribution values verbatim (`+0.225`), giving the reviewer per-signal numbers.

### Neutral
- A naive-Bayes variant (`P(candidate | e_1, ..., e_n) ∝ Π P(e_i | candidate) · P(candidate)`) was also considered and rejected because the independence assumption is violated in this dataset (transcript_role and speaking_pattern both derive from the transcript). Naive Bayes would over-confide.

## Validation

- `tests/test_fusion.py` covers cold-start (empty evidences → 0.0), single sticky evidence, decay over time, supersedes replacement, threshold-and-margin gate, and the None + `is_decision=False` graceful-uncertainty path.
- `scripts/run_accuracy.py` reports precision@1 / time-to-decision / flips across the mock scenarios.

## Classification

- **Type:** Algorithmic / system behaviour
- **Cost of reversal:** Low — the `Fusion` Protocol adds v2-Bayesian as a sibling engine; `weights.json.engine_version` selects. No analyzer changes.
- **Risk if wrong:** Medium-low. If reviewers dislike weighted-average, the upgrade path is one PR.
