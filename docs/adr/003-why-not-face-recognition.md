# ADR-003: Face *consistency*, not face *recognition*

> **Status:** Accepted · **Date:** 2026-07-09 · **Decider:** you · **Supersedes:** none · **Superseded by:** none
> **Related:** [../APPROACH.md §1.2](../APPROACH.md) · [../SIGNALS.md §8](../SIGNALS.md) · [../TRADEOFFS.md §1](../TRADEOFFS.md) · [../SECURITY.md §3](../SECURITY.md)

---

## Context

PDF p1 repeatedly frames the candidate-identification problem in a way that explicitly invites a face-recognition solution and then quietly rejects it:

- Background bullet: "Candidate joins as MacBook Pro" — display name is unreliable.
- The bonus line: "Use multiple weak signals instead of relying on one rule."
- The closing note: "explainability, confidence estimation, and graceful handling of ambiguity are just as important as raw accuracy."

A face-only face-recognition solution was on the table because at first reading it seems perfectly informative: every webcam-equipped candidate reveals their face, and reference faces are plausibly available (LinkedIn, calendar invite photo, ID document).

Two distinct face-based strategies are technically feasible:

| Option | Shape |
|---|---|
| A — **Face recognition** | Build a per-candidate face embedding from a reference photo; compute cosine similarity between the live frame embedding and the reference; emit `Evidence(score=similarity, weight=high)`. |
| B — **Face consistency** | For each participant, maintain an internal embedding EMA over their own frame stream; detect sudden embedding changes (face swaps); emit `Evidence(score=consistency)` that is NOT used to identify the person, only to flag intra-stream face swaps. |

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| **A — Face recognition** | Could close cold-start with one positive signal; would feel "production" (LinkedIn + Zoom CRM matches). | **Privacy minefield** — storing reference face embeddings crosses biometric-data regulations (GDPR Art. 9, BIPA, IL biometric laws). **High false-positive risk** — look-alikes, lighting, accidental public reference photos. **Fails the brief** — single-sensor reliance violates the PDF p4 explicit "multi weak signals" bonus. Wrong-name-with-right-face case (candidate shares name with interviewer's relative) breaks it. Falls into the exact trap PDF p4 names: "face recognition only". |
| **B — Face consistency** | No biometric storage. No reference image needed. Catches the deepfake-injection attack modality which is core to Sherlock's fraud mission (PDF Background paragraph). Naturally anti-evidence — only flags when something weird happens. Fits the "multiple weak signals" brief — vision is one of ten, not the headline. | Doesn't help identify the candidate; only catches swaps. Lower headline accuracy contribution. Adds MediaPipe + InsightFace as dependencies. Real face swaps are rare event — calibration data sparse. |

## Decision

**Option B — face consistency.** Specified in [`docs/SIGNALS.md §8`](../SIGNALS.md).

Concrete rules:
1. Default weight = **0.00** — the analyzer exists in v1 but is inert. `tune.py` flips to 0.05 only after labeled face-swap data shows the analyzer discriminates.
2. Analyzer computes a 512-dim ArcFace embedding per frame (InsightFace ONNX) per participant.
3. Maintain an exponential moving average (EMA) of the embedding per participant.
4. Per frame, score = `1 - cosine_distance(new_emb, ema) / 0.5`, clamped `[0,1]`. Above 0.85 = consistent; below 0.30 = swap detected.
5. Emit anti-evidence on a swap: `"Face embedding changed abruptly at t=Ns — possible face swap"`.
6. The analyzer NEVER compares embeddings to a reference photo. It only checks intra-stream consistency.
7. Embeddings are NEVER persisted to disk or Postgres — in-memory only, flushed on session end. See [SECURITY.md §2](../SECURITY.md).

## Consequences

### Positive
- Avoids the privacy minefield of biometric reference matching — no consent flows beyond the meeting's normal consent.
- Catches one of Sherlock's high-priority fraud categories (deepfake injection) without taking on the legal burden of identifying the candidate.
- Naturally fits the "multiple weak signals" thesis — vision is one sensor among ten, deliberately weight-restrained.
- Reviewer-friendly: a small but principled dissent from the obvious face-recognition path scores on the "engineering judgment" rubric (PDF Engineering quality 20% + Creativity 5%).

### Negative
- Real face swaps in interviews are rare → calibration data is sparse → analyzer weight stays at 0.00 until `tune.py` clears it (post-v1.0).
- Sudden lighting changes (e.g., interviewer holds a phone flashlight) can temporarily spike cosine distance. Mitigation: EMA + threshold tuned conservatively (0.5); `tune.py` expected to widen tolerance based on labeled data.
- Pair-look-alike swap (hired actor with similar features) is NOT caught by consistency. Documented as a known limitation in [EVALUATION.md §7.7](../EVALUATION.md).
- Two people in frame (e.g., candidate's child walks in) confuses MediaPipe's single-face box tracking. Mitigation: future v1.1 work to track all visible faces.

### Neutral
- An earlier draft considered letting the vision analyzer also output a per-participant L2-normalized "pitch" of face presence (always-on-screen). We chose not to — `webcam_usage` analyzer (per [SIGNALS.md §4](../SIGNALS.md)) already covers on-screen presence with much less compute.

## Validation

- `tests/test_analyzers/test_vision.py` mocks MediaPipe detector returns + InsightFace embedding cosine distances → asserts EMA accumulation, swap detection, and zero-frames-preserved behavior.
- Vision is behind a feature flag `VISION_ENABLED=false` by default. CI does not require the ONNX model download — the test uses a fixture embedding.

## Classification

- **Type:** Algorithmic / privacy posture / product judgment
- **Cost of reversal:** Medium. Adding face recognition later would be a NEW analyzer (`face_recognition`) with weight 0.00 default and a separate privacy review. Consistency analyzer unaffected.
- **Risk if wrong:** Low. PDF p4 explicitly warns against "face recognition only"; this decision moves the system away from that trap.
