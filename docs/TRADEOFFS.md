# TRADEOFFS.md — Explicitly Rejected & Deferred Approaches

> **Status:** v1.0 · **Audience:** Reviewer (PDF Deliverable #2 demo video trade-offs section + reviewer's own assessment)
> **Related:** [APPROACH.md](./APPROACH.md) · [adr/003-why-not-face-recognition.md](./adr/003-why-not-face-recognition.md) · [adr/002-weighted-fusion.md](./adr/002-weighted-fusion.md) · [SIGNALS.md](./SIGNALS.md)
> **Purpose:** PDF p3 explicitly asks the demo video to cover trade-offs. This document provides verbatim material for the demo script and the reviewer's own reading. Each section: (approached considered) + (pros) + (cons) + (rejected or deferred + why).

---

## 1. Face Recognition

### What was considered
Build a per-candidate face embedding from a reference photo (LinkedIn, calendar invite picture, ID document). Compare live webcam frames to the reference. If cosine similarity > threshold, emit strong candidate support Evidence.

### Pros
- Could resolve cold-start in one frame (~300ms) without waiting for a transcript.
- Feels "production" — Zoom CRM + LinkedIn integration is the obvious thing a product manager would ask for.

### Cons
- **Privacy minefield.** Storing reference face embeddings crosses biometric data regulations (GDPR Article 9, Illinois' BIPA, California's soon-to-be biometric privacy law). Sherlock's own Trust & Safety posture would need a consent flow we have not built.
- **High false-positive risk.** Look-alike candidates, the same candidate appearing in two interviews under different names (finish interviews), interviewer's brother joining by mistake — all break face-recognition-only.
- **Wrong name / right face.** The PDF p1 case "interviewer enters wrong candidate name" — if they accidentally enter the WRONG candidate name into the system dashboard but the face recognition voter matches the LIVE face to the WRONG name, the system actively helps a wrong decision.
- **Fails the PDF's explicit direction.** PDF p4 bonus says "multiple weak signals instead of relying on one rule". Face-only is literally the one-rule off-ramp the PDF cautions against.

### Verdict: **Rejected**
- Face *consistency* (not recognition) is kept with weight 0.00 per [ADR-003 why-not-face-recognition](./adr/003-why-not-face-recognition.md).
- Face *recognition* as a future parallel analyzer with a separate consent flow and a higher privacy insertion bar. Documented as 🔮 future work in [EVOLUTION.md](./EVOLUTION.md).
- This trade-off is a deliberate call-out in the demo video's trade-offs section (timestamp 6:30-7:00 in [EVALUATION.md §10](./EVALUATION.md)).

---

## 2. Bayesian (Beta-Posterior) Fusion — Deferred, Not Rejected

### What was considered
Replace v1 weighted-average fusion with a proper Bayesian framework: treat each participant's `is_candidate` hypothesis as a Beta distribution. Each Evidence becomes a likelihood update on that distribution; the posterior expectation produces a **calibrated** confidence.

### Pros
- Proper uncertainty propagation — a weak signal with low score *correctly* doesn't dilute a strong signal.
- Confidences ARE calibrated to empirical accuracy once priors estimated from labeled data.
- Mathematically defensible for reviewers with a statistics background.

### Cons
- Requires per-signal priors (alpha, beta) — non-trivial to estimate out-of-box. With only 3 mock scenarios, priors would be wild guesses.
- Explainability message "Posterior on Beta(7.5, 1.5)" is much harder to tell a hiring manager viewer than "Transcript contributed +0.225".
- Tuning space doubles (10 weights → 20 alpha/beta parameters).
- Threshold + margin gate (decidable/not-decidable) would need interpolation to Bayesian space — still doable but extra engineering.

### Verdict: **Deferred to v2 (ADR-006, fall 2026)**
- v1 ships with weighted-average (ADR-002). The `Fusion` Protocol exists; switching to v2-Bayesian once `tune.py` has ≥20 labeled sessions is one PR. Specified in [ACCURACY_METRICS.md §9](./ACCURACY_METRICS.md).
- Deferred status is noted on the architecture in [EVOLUTION.md](./EVOLUTION.md) V1 → V1.1 → V2 transition.

---

## 3. Rule-Engine-Only

### What was considered
A simple rule cascade:
```
if email matches: candidate = confirmed
elif name similarity > threshold: candidate = the most-similar
elif someone shares a resume: candidate = that person
else: give up.
```

### Pros
- Trivially explainable (one rule fires → one bullet).
- Week-buildable.
- No ML model dependencies. No cloud cost.

### Cons
- **Single-rule deterministic = wrong under ambiguity.** PDF p1 cases "candidate joins as MacBook Pro" and "two Ashwini Kumar's" break the first two rules.
- **Doesn't scale in complexity.** Add a 4th, 5th participant, and the rule cascade becomes a branching IF/ELSE tree — maintaining it is quadratic pain.
- **No confidence score** — just a binary pick. PDF p4 explicitly rewards "produce a confidence score".
- **No explainability** — the rule that fired is the only answer; there's no marginal contribution weight.

### Verdict: **Rejected**
- If the goal were a five-minute hack project, rule engines matter. This assignment explicitly rewards "solutions that combine multiple sources of evidence" and rules don't combine; they cascade. Rules are treated as the prototype baseline the PDF p4 already rejects.

---

## 4. LLM-Only Decision-Making

### What was considered
Feed the full call transcript to a GPT-4-class LLM, prompt: "Which participant is the candidate?" Single call, final answer, clear output.

### Pros
- Single-LLM call — one round trip, one cost.
- LLM summarization is accurate when given full context.

### Cons
- **Latency.** 30-min transcript → 5k+ token prompt → LLM call of up to 30 seconds. PDF p4 "Work in real time" explicitly shown off by a 30s verdict interval.
- **No confidence calibration.** LLMs authors will say "candidate is P1" with certainty; the confidence score is an LLM hallucination, not an empirical calibration.
- **No graded weight per signal.** LLM-only output is "P1" not "P1 because email matched (0.30), because transcript-role classified (0.25), because..." — the PDF p6 close explicitly asks to "show us how your system reaches its conclusion", not just what it concludes.
- **Not updated every 5s.** Re-running the LLM on each transcript window would be 60× the cost of the 5s ticker.
- **Cold-start cannot be answered.** Early in the interview there isn't enough transcript for the LLM to see a candidate ← interviewer pattern; it would guess or say "unclear".

### Verdict: **Rejected**
- LLM-only is comfortable for sentiment but not for this explainability + real-time + confidence-updating brief. We use an LLM as *one sensor* (the `transcript_role` analyzer) — per [SIGNALS.md §6](./SIGNALS.md) — but explicitly not as the decision oracle. This trade-off is built into the fusion architecture in [APPROACH.md §1.2](./APPROACH.md).

---

## 5. Standalone Classifier (Softmax / Logistic Regression)

### What was considered
Train an end-to-end classifier (logistic regression, XGBoost, or a small neural net) on labelled sessions where the output is a one-hot participant-is-candidate vector.

### Pros
- Good accuracy on labeled data once enough sessions exist.
- Confidence scores natural from softmax outputs.
- Familiar pattern for ML engineers.

### Cons
- **Requires labeled data from day one.** None exists before the prototype is built.
- **Black-box to reviewers.** Weights don't decompose by signal — no transparent "email contributed +0.30".
- **Would need to retrain from scratch for each new signal** (e.g. add screen_share_content → re-train with one more feature).
- **Scaling the buffer** with a streaming model update is significantly more engineering than swapping weights.json per `tune.py`.

### Verdict: **Rejected**
- Too heavy for a prototype where we control the signal pipeline and already have per-signal weights. The fusion architecture auto-decomposes into weights the reviewer can read. If downstream Sherlock wants to retrain a branded classifier once they have >200 labeled sessions, this path opens naturally from the same verified Evidence store schema.

---

## 6. Per-Training (Not Discussed in Other Docs)

### What was considered
Periodically train a model on labeled sessions behind-the-scenes.

### Pros
- Convention.

### Cons
- Not authorized by PDF.
- Exposes a DSL-payoff for recruiter.

### Verdict: **Off-ramped**
The launch-date constraints "Make it a working demo on real platforms" naturally deprioritize per-training.

---

## 7. Summary Matrix

| Approach | Status | Where | Rationale |
|---|---|---|---|
| Face recognition | **Rejected** | ADR-003 | Privacy + PDF explicitly warns against |
| Bayesian-first | **Deferred → v2** | ADR-002 | No labeled priors yet; v1 weighted → v2 upgrade path documented |
| Rule-engine only | **Rejected** | APPROACH §1.2 | Doesn't combine signals; PDF explicitly says "use multiple weak signals" |
| LLM-only decision | **Rejected** | APPROACH §1.2 | No explainability, no real-time confidence evolution, no confidence calibration |
| End-to-end classifier | **Rejected** | — | Lacks transparent per-signal decomposition |
| Per-Training | **Out of scope** | — | Not required by PDF |
| Face consistency (inert) | **Deferred → post-tune** | SIGNALS §8 · ADR-003 | Weight 0.00 until `tune.py` validates |
| Device-name (trap) | **Permanently disabled** | SIGNALS §10 | PDF p1 explicitly names this as a trap |

---

> **Companion:** [RISKS.md](./RISKS.md) for the risk register; [EVOLUTION.md](./EVOLUTION.md) for the deferred → production roadmap.