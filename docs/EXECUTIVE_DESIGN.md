# Executive Design — Sherlock Candidate Identification System

> **Audience:** Reviewer (Priya @ Sherlock; engineering review panel) — start here.
> **Length:** ~2–3 pages. Every section links out to the deeper doc.
> **Status legend:** ✅ Implemented · 🚧 Prototype (works, not hardened) · 🔮 Future Work
> **Last updated:** 2026-07-09

---

## 1. The One-Sentence Pitch

`cis` is a **real-time multi-signal evidence-fusion system** that identifies which participant in a live interview is the candidate, assigning a continuous confidence score and a human-readable explanation, refusing to commit when evidence is insufficient.

## 2. The Cluster of Ideas (in 60 seconds)

The PDF brief's largest signal is the bonus line:

> Use multiple weak signals instead of relying on one rule.

That sentence eliminates face-only, voice-only, name-only, and LLM-only solutions. It invites the autonomous-systems pattern: many decoupled sensors emit normalized evidence, a fusion engine combines them, an explainer renders the decision back to a human. We built that, plus a graceful-uncertainty escape valve so the system can hold the verdict at "still deciding" instead of forcing a guess.

- **Thesis & rubric traceability:** [docs/APPROACH.md](./APPROACH.md)
- **System shape:** [docs/ARCHITECTURE.md](./ARCHITECTURE.md) · [docs/ARCHITECTURE.svg](./ARCHITECTURE.svg)
- **Per-signal spec:** [docs/SIGNALS.md](./SIGNALS.md)

## 3. What's Implemented vs. Prototype vs. Future

| Component | Status | Where |
|---|---|---|
| Multi-signal weighted fusion (v1) | ✅ | [docs/ARCHITECTURE.md §1.6](./ARCHITECTURE.md) |
| 5s realtime ticker + WebSocket dashboard | ✅ | [docs/ARCHITECTURE.md §1.5](./ARCHITECTURE.md) |
| Threshold + margin gate ("still deciding" state) | ✅ | [docs/DATA_CONTRACT.md §5.2](./DATA_CONTRACT.md) |
| 10 analyzers (3 disabled by default) | ✅ spec · 🚧 code | [docs/SIGNALS.md](./SIGNALS.md) |
| Mock adapter + 3 reference scenarios | ✅ spec · 🚧 scripts | [docs/MOCK_DATA_FORMAT.md](./MOCK_DATA_FORMAT.md) |
| Zoom OAuth + Recording API + per-track Whisper | 🚧 | [docs/PLATFORM_INTEGRATION.md §2](./PLATFORM_INTEGRATION.md) |
| Google Meet Recording API + Chrome extension fallback | 🚧 | [docs/PLATFORM_INTEGRATION.md §3](./PLATFORM_INTEGRATION.md) |
| React dashboard | 🚧 | [docs/ARCHITECTURE.md §1.9](./ARCHITECTURE.md) |
| Vision analyzer (face consistency, inert weight=0) | 🚧 | [docs/SIGNALS.md §8](./SIGNALS.md) |
| 20–50 synthetic-session empirical harness | 🔮 | [docs/EVALUATION.md §A1](./EVALUATION.md) |
| Bayesian v2 fusion (after ≥20 labeled sessions) | 🔮 | [docs/EVOLUTION.md](./EVOLUTION.md) |
| Online learning via Thompson sampling | 🔮 | [docs/EVOLUTION.md](./EVOLUTION.md) |
| Teams adapter | 🔮 | [docs/PLATFORM_INTEGRATION.md §9](./PLATFORM_INTEGRATION.md) |

## 4. How to Read This Repository (5 minutes)

Reviewers should read in this order; each doc is self-contained.

1. **This doc** — orientation.
2. **[docs/APPROACH.md](./APPROACH.md)** — the thesis, the rubric traceability matrix, the self-critical review *(2 pages)*.
3. **[docs/ARCHITECTURE.md](./ARCHITECTURE.md)** + **[docs/ARCHITECTURE.svg](./ARCHITECTURE.svg)** — system shape; sequence diagrams for cold-start, mid-call, rename, insufficient-evidence *(PDF Deliverable #4)*.
4. **[docs/TRADEOFFS.md](./TRADEOFFS.md)** — face-recognition, Bayesian-first, rule-engine, LLM-only options we explicitly rejected, with pros/cons.
5. **[docs/adr/](./adr/)** — five short ADRs capturing the highest-leverage design decisions (Event Bus, weighted fusion, not-face-recognition, Whisper, Redis).
6. **[docs/SIGNALS.md](./SIGNALS.md)** — per-signal spec with scoring curves, edge cases, calibration needs.
7. **[docs/DATA_CONTRACT.md](./DATA_CONTRACT.md)** — the wire schemas, hard analyzer rules, error classes.
8. **[docs/EVALUATION.md](./EVALUATION.md)** — test methodology, edge cases tested, accuracy baseline, limitations, and the extended 20–50 synthetic-session empirical harness *(PDF Deliverable #5)*.
9. **[docs/ACCURACY_METRICS.md](./ACCURACY_METRICS.md)** — precision@1, time-to-decision, stability, latency definitions + `tune.py` algorithm.
10. **[docs/RISKS.md](./RISKS.md)** — risk register with impact × probability × mitigation × residual.
11. **[docs/EVOLUTION.md](./EVOLUTION.md)** — V1 → V1.1 → V2 Bayesian → V3 Online Learning → Production trajectory.
12. **[docs/PLATFORM_INTEGRATION.md](./PLATFORM_INTEGRATION.md)** — Zoom and Meet adapter contracts.
13. **[docs/MOCK_DATA_FORMAT.md](./MOCK_DATA_FORMAT.md)** — JSON schema for replayable recordings + 3 reference scenarios.
14. **[docs/ROADMAP.md](./ROADMAP.md)** — 12-day phase plan with do-done criteria and commands.
15. Operations docs: **[docs/API_SPECIFICATION.md](./API_SPECIFICATION.md)** · **[docs/SECURITY.md](./SECURITY.md)** · **[docs/DEPLOYMENT.md](./DEPLOYMENT.md)** · **[docs/PERFORMANCE.md](./PERFORMANCE.md)**.

## 5. The Numbers (v1 baseline + extended harness target)

From **[docs/EVALUATION.md §4](./EVALUATION.md)** and **[docs/ACCURACY_METRICS.md §7](./ACCURACY_METRICS.md)**:

| Metric | v1.0 baseline (3 authored mock scenarios) | Extended synthetic harness target (20–50 sessions) |
|---|---|---|
| precision@1 | 1.00 (by construction) | ≥ 0.90 |
| recall@1 | 1.00 | ≥ 0.85 |
| F1 | 1.00 | ≥ 0.87 |
| time-to-decision p50 | 250 s | ≤ 300 s |
| time-to-decision p90 | 350 s | ≤ 600 s |
| decision stability (flips/session) | 0 | ≤ 2 |
| false-positive rate (forced wrong decisions) | 0 | ≤ 1% |
| latency (event → dashboard, p95) | 435 ms | ≤ 1.5 s |

The v1 column is by construction (recordings authored with the expected verdict). The purpose of the extended **synthetic-session generator** (a Python script drafted in [EVALUATION.md §A1](./EVALUATION.md)) is to **stop relying on authored scenarios** and report generalization metrics on randomized participant orders, renames, observers, and webcam-state transitions.

## 6. The 5 PDF Deliverables Map

| # | PDF Deliverable | Artifact in this repo |
|---|---|---|
| 1 | Working demo | `docker compose up` + `app.main:app` uvicorn + React dashboard. 3 mock scenarios drive it. |
| 2 | Short demo video (5–10 min) | Script in [docs/EVALUATION.md §10](./EVALUATION.md). |
| 3 | GitHub repository (README, setup, assumptions) | [README.md](../README.md) at the repo root. |
| 4 | Architecture diagram | [docs/ARCHITECTURE.svg](./ARCHITECTURE.svg) |
| 5 | Evaluation writeup (tests, edge cases, accuracy, limitations) | [docs/EVALUATION.md](./EVALUATION.md) |

## 7. The 6 PDF Bonus Points

| Bonus | Status | Where |
|---|---|---|
| Multiple weak signals | ✅ | 10 analyzers per [docs/SIGNALS.md](./SIGNALS.md) |
| Confidence score | ✅ | `Verdict.confidence` per [docs/DATA_CONTRACT.md §5](./DATA_CONTRACT.md) |
| Explain why selected | ✅ | `Verdict.reasons[]` + `rejected_hypotheses` per [docs/DATA_CONTRACT.md §5.1](./DATA_CONTRACT.md) |
| Gracefully handle uncertainty | ✅ | `is_decision=False` + threshold + margin gate per [docs/DATA_CONTRACT.md §5.2](./DATA_CONTRACT.md) |
| Work in real time | ✅ | 5s ticker; observed p50 latency 435 ms per [docs/EVALUATION.md §6](./EVALUATION.md) |
| Continue learning as more data becomes available | 🔮 | `weights.json` schema + `tune.py` scaffold; real update requires ≥20 labeled sessions — see [docs/EVOLUTION.md](./EVOLUTION.md) v2 path |

## 8. Honest Disclosure — What This Submission Is Not

(Per PDF p3 spirit; full list in [docs/EVALUATION.md §7](./EVALUATION.md).)

- **Not** a production-fraud-detection system. It's a candidate-identification prototype for the internship challenge.
- **Not** tested on real interviews at scale; only 3 mock scenarios + 1 Zoom + 1 Meet existence-proof demos.
- **Not** shipping with a Bayesian fusion engine enabled; v1.0 weighted (hand-tuned weights) until ≥20 labeled sessions exist for prior calibration.
- **Not** enabling the vision analyzer; weight=0.00 by default. Face *consistency* is implemented as a stretch; face *recognition* is explicitly rejected per [docs/adr/003-why-not-face-recognition.md](./adr/003-why-not-face-recognition.md).
- **Not** claiming empirical accuracy on real-world interviews; we disclose this in [docs/EVALUATION.md §7.1](./EVALUATION.md) and outline the 20–50-session empirical harness roadmap to honestly establish that number.

## 9. Submission Target

```
To: priya@sherlock.sh
Subject: Sherlock Internship Challenge — {Your Name}
```

Repository: <TBD — placeholder for `https://github.com/{user}/cis`>
Template in [docs/EVALUATION.md §11](./EVALUATION.md).

---

> **Stop reading here.** The next doc, [docs/APPROACH.md](./APPROACH.md), is the full thesis with rubric matrix and self-critical review.
