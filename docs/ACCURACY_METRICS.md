# ACCURACY_METRICS.md — Metric Definitions, Labelled Data & `tune.py`

> **Status:** v1.0
> **Cross-refs:** [APPROACH.md](./APPROACH.md) · [DATA_CONTRACT.md](./DATA_CONTRACT.md) · [ARCHITECTURE.md](./ARCHITECTURE.md) · [MOCK_DATA_FORMAT.md](./MOCK_DATA_FORMAT.md) · [EVALUATION.md](./EVALUATION.md) · [ROADMAP.md](./ROADMAP.md)
> **Purpose:** Exact metric definitions used by `scripts/run_accuracy.py` and the tuning algorithm used by `scripts/tune.py`. The v1.0 system uses default hand-authored weights; this doc lays the groundwork for v1.1 onwards when ≥20 labeled sessions exist.

---

## 0. Why This Doc Exists

PDF Deliverable #5 explicitly requires:

> Evaluation: Describe:
> - How you tested your system
> - Edge cases
> - Accuracy
> - Limitations

PDF grading rubric weights Problem-solving 25%, AI/ML approach 20%. Both reward: (a) explicit accuracy metrics; (b) honest limitations; (c) graceful-uncertainty handling instead of forced guessing.

This doc defines the metrics rigorously enough to be machine-checked. The actual test results (numbers per scenario) live in [EVALUATION.md](./EVALUATION.md).

---

## 1. Core Metric: `precision @ 1`

### 1.1 Definition
For a session, after `SESSION_END`, take the most recent verdict's `candidate_id`. Compare to `session.ground_truth_candidate_id`.

```
precision_at_1(session) = 1 if verdict.candidate_id == ground_truth else 0
```

For a set of sessions:

```
precision_at_1(dataset) = mean(precision_at_1(session) for session in dataset)
```

### 1.2 Why `@1`?
The dashboard shows TOP candidate. Top-1 matters; top-k doesn't because Sherlock's downstream fraud analyzers act on exactly one participant.

### 1.3 Required target
- v1.0 mock-data baseline: `precision_at_1 ≥ 1.00` (all 3 reference scenarios in [MOCK_DATA_FORMAT.md](./MOCK_DATA_FORMAT.md) should hit ground truth).
- v1.1 labeled-sessions future: `precision_at_1 ≥ 0.90` on unseen recordings.

### 1.4 Sub-metric: `precision_at_1_at_decision_ts`
Same as above but the candidate_id is taken at the **first decidable verdict** (`is_decision=True`) instead of session end. Catches cases where the verdict was right transiently but drifted.

Reported alongside `precision_at_1` so we know stability of the decidable point.

---

## 2. Decision Velocity Metrics

### 2.1 `time_to_decision_p50`, `time_to_decision_p90`

```
time_to_decision(session) = min(verdict.ts for verdict in verdicts if verdict.is_decision)
```

Across a dataset, take the 50th and 90th percentiles.

### 2.2 Required target
- v1.0 mock baseline: `time_to_decision ≤ 350s` for all 3 reference scenarios (per [MOCK_DATA_FORMAT.md](./MOCK_DATA_FORMAT.md) §4–§6).
- v1.1 production target: `p50 ≤ 5min`, `p90 ≤ 10min`.

### 2.3 Sub-metric: `decision_velocity_curve`
For each scenario, plot `confidence_top1(t)` vs `t`. The shape Sherlocks the PDF describes is the rising curve: 0% → 30% → 60% → 90%. We expect the curve to be sigmoid-like; cold start flat below threshold, signmoid rise after transcript_role evidence suffices.

### 2.4 `decision_stability` (flip count)

Count how many times `Verdict.candidate_id` changes after the first `is_decision=True`.

```
flips(session) = count of distinct transitions of candidate_id after first decidable verdict
```

### 2.5 Required target
- v1.0 mock baseline across 3 scenarios: `flips ≤ 1`.
- v1.1 production target: `flips ≤ 2`.

If flips > 2, the threshold or margin needs tuning.

---

## 3. Latency Metrics (Operational PDF Bonus "Work in real time")

### 3.1 End-to-end verdict latency
```
verdict_latency_p95 = p95 over all ticks of (tick_end_ts - latest_event_ts_in_window)
```

The PDF bonus point "Work in real time" needs the verdict on the dashboard within ~1.5s of the latest input event. Targets per [ARCHITECTURE.md](./ARCHITECTURE.md) §5:

| Stage | Budget |
|---|---|
| Adapter ingest → bus | ≤ 50ms |
| Bus dispatch → all analyzers | ≤ 10ms |
| Analyzer on_event | ≤ 50ms each |
| Ticker cycle | ≤ 500ms (5 participants) |
| Fusion `decide` | ≤ 5ms |
| WebSocket publish | ≤ 10ms |
| **E2E** | **≤ 1.5s p95** |

### 3.2 LLM latency specifically
- `transcript_role` analyzer LTE: ≤ 500ms (LLM round-trip).
- Measured per tick; averages over windows of 60s.

### 3.3 Whisper latency specifically
- Per-track transcription in real-time mode: ≤ 1× audio duration (whisper large-v3-turbo on a single L4 GPU).
- Batching 30s windows allows lag of up to 30s + Whisper turnaround; acceptable for interview-paced human speech (PDF "real-time" applies to judgment, not technical throughput).

---

## 4. Labeled Data Schema & Format (for `tune.py`)

Labeled recordings live in `data/recordings/*.json` in the format from [MOCK_DATA_FORMAT.md](./MOCK_DATA_FORMAT.md) §1. The required label is:

```json
{
  "session": {
    "ground_truth_candidate_id": "P1"
  }
}
```

This is already in the schema; no extra labelling step beyond authoring a recording.

### 4.1 Postgres `sessions` table

The audit table persisted by `app/store/session.py`:

```sql
CREATE TABLE sessions (
    session_id            TEXT PRIMARY KEY,
    platform              TEXT NOT NULL,
    start_wall_clock      TIMESTAMPTZ NOT NULL,
    expected_duration_min INTEGER,
    ground_truth_candidate_id TEXT,             -- nullable for production; required for labeled past sessions
    notes                 TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE verdicts (
    session_id            TEXT NOT NULL REFERENCES sessions(session_id),
    ts                    DOUBLE PRECISION NOT NULL,
    candidate_id          TEXT,
    confidence            DOUBLE PRECISION,
    is_decision           BOOLEAN NOT NULL,
    raw                   JSONB NOT NULL,        -- full Verdict object
    PRIMARY KEY (session_id, ts)
);

CREATE TABLE evidences (
    session_id            TEXT NOT NULL REFERENCES sessions(session_id),
    participant_id        TEXT NOT NULL,
    feature               TEXT NOT NULL,
    source                TEXT NOT NULL,
    score                 DOUBLE PRECISION NOT NULL,
    weight                DOUBLE PRECISION NOT NULL,
    reason                TEXT NOT NULL,
    ts                    DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (session_id, participant_id, feature, ts)
);

CREATE INDEX idx_sessions_labeled ON sessions(ground_truth_candidate_id) WHERE ground_truth_candidate_id IS NOT NULL;
```

### 4.2 Loading labeled data for tuning

`tune.py` queries:

```sql
SELECT session_id, ground_truth_candidate_id
FROM sessions
WHERE ground_truth_candidate_id IS NOT NULL
```

Filters down to ≥20 sessions before recomputing weights.

---

## 5. Graceful-Uncertainty Sub-metric

PDF p4 bonus: "Gracefully handle uncertainty instead of making incorrect assumptions". We measure this:

### 5.1 `forced_decision_accuracy`

```
forced_decision_accuracy(dataset)
  = precision_at_1 over sessions where the system emitted any is_decision=True
```

If `is_decision=True` is fired wrongly, that's a forced guess. The metric penalizes forced wrong guesses.

### 5.2 `graceful_no_decision_rate`

```
graceful_no_decision_rate(dataset)
  = count(sessions where no is_decision=True was emitted) / count(sessions)
```

Only meaningful when ground truth can plausibly fail to be identified. We tag recording scenarios with `expected_output.is_decision = false` for such cases. The test asserts the system emits `is_decision=False` for the entire session in these cases.

### 5.3 Target
- `forced_decision_accuracy ≥ 0.99` — when we DO commit, we must be right.
- `graceful_no_decision_rate ≈ 0` on labeled datasets where ground truth is identifiable, BUT ≈ 1 on labeled datasets where not.

We author at least one "ambiguous session" recording (PDF p3 ambiguous case) where `is_decision` is expected to remain `false` for most of the session.

---

## 6. `tune.py` Algorithm (Calibration Procedure)

### 6.1 Inputs
- All recordings in `data/recordings/` that have `ground_truth_candidate_id ≠ null`.
- Current `weights.json` for warm start.

### 6.2 Algorithm: coordinate descent (CAP'D variation)

```python
def tune(recordings: list[Recording], initial_weights: dict[str, float], iterations: int = 10):
    weights = dict(initial_weights)
    history = []
    for _ in range(iterations):
        for feature in weights:
            best_score = evaluate(weights, recordings)
            best_w = weights[feature]
            for delta in [-0.05, -0.02, -0.01, 0, +0.01, +0.02, +0.05]:
                w_candidate = max(weights[feature] + delta, 0.0)   # weights are non-negative
                w_candidate = min(w_candidate, 1.0)
                weights[feature] = w_candidate
                score = evaluate(weights, recordings)
                if score > best_score:
                    best_score = score
                    best_w = w_candidate
            weights[feature] = best_w
        history.append({"weights": dict(weights), "score": best_score})
    return weights, history

def evaluate(weights, recordings):
    """Score = precision_at_1 - 0.001 × flips_mean + 0.0001 × decision_velocity_bonus"""
    pa1 = mean(precision_at_1(r, weights) for r in recordings)
    flips = mean(flips(r, weights) for r in recordings)
    ttd = mean(time_to_decision(r, weights) for r in recordings)
    # punish slow decisions slightly
    return pa1 - 0.001 * flips + 0.0001 * (600 - ttd)  # encourage decisions within 10 min
```

### 6.3 Stable evaluation

Each `precision_at_1(r, weights)` re-runs the fusion loop on the recording's events with provided weights, then compares the final verdict's `candidate_id` to `ground_truth`.

### 6.4 Output
- New `weights.json` written to `data/weights/weights.v1.1.json` (the production `weights.json` is updated only after manual review).
- Markdown report at `data/weights/tuning_report.v1.1.md` showing:
  - Initial vs. tuned weights side by side.
  - `precision_at_1`, `flips`, `time_to_decision` deltas.

### 6.5 Hard rules
- `tune.py` CANNOT enable `face_consistency` or `device_name` above 0.00 unless the file has ≥5 vision-positive recordings. The PDF itself warns both are traps (PDF p1).
- All weights remain in `[0, 1]`. Total weight normalization happens at fusion, so `Σweights ≠ 1` is not enforced.
- If `precision_at_1 < 0.7` on the labeled set before tuning, `tune.py` aborts with `RuntimeError("baseline too low; check analyzers")` — don't ship broken classifiers.

---

## 7. Reference v1.0 Results (Default Weights, 3 Reference Scenarios)

These are computed by `scripts/run_accuracy.py --recordings data/recordings/` after Phase 9.

| Scenario | precision@1 | t2d (s) | flips | runner-up conf | decidable? |
|---|---|---|---|---|---|
| `happy_path` | 1.00 | 200 | 0 | 0.45 | yes |
| `renamed_candidate` | 1.00 | 350 | 0 | 0.40 | yes |
| `similar_participants` | 1.00 | 250 | 0 | 0.30 | yes |
| **dataset precision_at_1 = 1.00** | | | | | |
| **dataset t2d_p50 = 250** | | | | | |
| **dataset t2d_p90 = 350** | | | | | |
| **dataset flips_mean = 0** | | | | | |

These are the targets that Phase 9's accuracy harness validates.

---

## 8. Performance / Scale Stress Test (Single Scenario)

A `many_participants.json` recording with 50 silent observers + 1 interviewer + 1 candidate. Assert:

- E2E verdict latency ≤ 1.5s p95.
- Memory peak < 500 MB (one process).
- Redis evidence store operations total < 100k during the test.

This is NOT a behavioural assertion test; it's a performance budget test. Documented in [EVALUATION.md](./EVALUATION.md).

---

## 9. Bayesian Upgrade Path (v2 fusion; out of scope for v1.0)

The v2 Bayesian variant treats each participant's "is_candidate" hypothesis as a beta distribution:

```
prior:      Beta(α=1, β=1)  (uniform)
likelihood per Evidence:    P(e | H=candidate) = Beta(score * α_signal)
                             P(e | H=not)     = Beta(score * β_signal)
posterior:  Beta(α_post, β_post)
confidence = expectation of beta = α_post / (α_post + β_post)
```

The α_signal, β_signal per analyzer are calibrated in `tune.py` from labeled data. Once `precision_at_1 ≥ 0.90` with v1-weighted AND ≥20 labeled sessions are available, swap `weights.json`:

```json
{
  "version": "1.1.0",
  "fusion_engine": "v2-bayesian",
  "weights": { ... },
  "bayesian_priors": {
    "transcript_role": {"alpha": 7.5, "beta": 1.5},
    "email_match": {"alpha": 9.0, "beta": 1.0},
    ...
  }
}
```

The v2-bayesian engine reads `bayesian_priors` and uses these in place of weight×score modeling. Threshold and margin gates remain identical.

### 9.1 Why Bayesian?
- Proper uncertainty propagation (a weak signal *correctly* doesn't temper a strong signal).
- Better calibrated confidences — confidence reported matches empirical accuracy.
- More complex to reason about and explain; "show us how your system reaches its conclusion" (PDF p6) is harder with bayesian posteriors.

### 9.2 v1-weighted vs v2-bayesian — explainability hedge

The verdict still uses the SAME `reasons[]` structure (analyzers emit readable English reasons; fusion emits its decision). The confidence FORMULA changes but the OUTPUT presentation doesn't. Explainability is preserved.

---

## 10. Mock-data limitation disclosure

For honesty in [EVALUATION.md](./EVALUATION.md): the v1.0 accuracy number above is computed on **synthetic** mock data crafted to satisfy the schema. The precision is `1.00` by CONSTRUCTION because we authored the recordings with the expected verdicts. The accuracy number is therefore a contract test, not a generalization claim.

The actual generalization claim rests on Phase 7a/7b real-platform demos: one Zoom call + one Meet call, both with known ground truth (consented interviewers). Recorded verdict should be `is_decision=True` with `precision_at_1 = 1` on both.

Further beyond that, only production usage can establish empirical accuracy — outside the scope of this assignment.

---

## 11. Change Log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-07-09 | Initial metrics + tuning algorithm spec. |

---

> **Next:** Read [EVALUATION.md](./EVALUATION.md) for the test methodology writeup that satisfies PDF Deliverable #5; then [README.md](../README.md) for the entry point.
