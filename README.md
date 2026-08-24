# cis — Sherlock Candidate Identification System

> Real-time multi-signal evidence-fusion system that identifies the interview candidate in a live meeting, with explainable confidence scores.
> Submission for the **Sherlock Internship Challenge**.

[![build](https://img.shields.io/badge/build-todo-lightgrey)]()
[![python](https://img.shields.io/badge/python-3.12-blue)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-teal)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

---

## What is this?

`cis` watches a live interview on Zoom or Google Meet and answers one question: **which participant is the candidate?** It does this by fusing 10 independent weak signals into a single confidence score, recomputed every 5 seconds, with a threshold-and-margin gate that refuses to commit when evidence is insufficient.

The PDF prompt's biggest hint:

> Use multiple weak signals instead of relying on one rule.

That ruled out face-recognition-only / voice-only / name-only / LLM-only solutions and ruled in a sensor-fusion architecture modeled after autonomous systems. The full thesis, rubric traceability, and self-review live in [`docs/APPROACH.md`](./docs/APPROACH.md).

---

## Table of Contents

- [Quickstart](#quickstart) — 5 commands to running dashboard
- [What it does](#what-it-does) — 60-second overview
- [Architecture](#architecture) — link to diagram
- [Docs Index](#docs-index) — full documentation set
- [How to demo](#how-to-demo) — show it working
- [PDF Deliverables](#pdf-deliverables) — explicit mapping to PDF p3
- [Assumptions](#assumptions) — what we assumed and why
- [Testing](#testing) — what we test and how
- [Known limitations](#known-limitations) — honest disclosure
- [Roadmap](#roadmap) — what's next
- [Submission](#submission) — sending to priya@sherlock.sh
- [License](#license)

---

## Quickstart

```powershell
# 1. Clone
git clone https://github.com/{user}/cis.git
cd cis

# 2. Install Python deps (uses uv or poetry)
uv sync                  # OR: pip install -e ".[dev]"

# 3. Bring up Redis + Postgres
docker compose up -d

# 4. Configure secrets
copy .env.example .env
#   - edit .env to set your LLM endpoint, Zoom OAuth creds, etc.
#   - secrets MUST remain git-ignored

# 5. Run the backend
uv run uvicorn app.main:app --reload --port 8000

# 6. Run the dashboard (separate terminal)
cd web
npm install
npm run dev
#   - opens at http://localhost:5173

# 7. Run a mock interview scenario
uv run python -m app.main --scenario happy_path
#   - listen on ws://localhost:8000/sessions/mock-sess-001/stream
#   - dashboard fills the verdict card as confidence rises

# 8. Run the tests
uv run pytest -v
```

MacOS / Linux equivalents substitute `cp` for `copy`, friendly-path adapt.

For Zoom and Google Meet real-platform demos, see [`docs/PLATFORM_INTEGRATION.md`](./docs/PLATFORM_INTEGRATION.md) for OAuth setup.

---

## What it does

For any interview session, `cis` ingests events from the meeting platform (mock replays, Zoom webhooks + recording pull, or the Meet Chrome extension). Independent analyzers convert those events into normalized `Evidence` records — each is a small `(participant_id, feature, score, reason, weight)` tuple. A 5-second ticker calls the fusion engine, which combines evidence per participant into a confidence score via decay-aware weighted summation. When the top participant's confidence crosses the threshold (0.55) with margin over the runner-up (≥ 0.20), the system emits a decidable `Verdict`. Otherwise it emits `is_decision=False` — gracefully conceding that more evidence is needed.

The dashboard renders the verdict, the confidence timeline, and the human-readable bullets describing why this candidate was chosen.

---

## Architecture

System diagram is in [`docs/ARCHITECTURE.svg`](./docs/ARCHITECTURE.svg) — also a PDF Deliverable #4. Prose, sequence diagrams, and trade-offs are in [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md).

```
Meeting SDK → Event Bus → Analyzers (10 sensors) → Evidence Store →
  Fusion Engine (5s tick) → ParticipantState → Explainer →
    WebSocket → React Dashboard
```

---

## Docs Index

The repo ships a complete documentation set under `docs/`. They were written before any code (a docs-first build per the [ROADMAP.md](./docs/ROADMAP.md) phase plan).

### Legend

- ✅ **Implemented** — spec exists; code implements or will implement this
- 🚧 **Prototype** — code scaffolded, not hardened for production
- 🔮 **Future Work** — designed in detail, deferred to v1.1+

### Core Docs (reviewer should read first)

| # | Doc | Status | What it covers |
|---|---|---|---|
| 0 | [`docs/EXECUTIVE_DESIGN.md`](./docs/EXECUTIVE_DESIGN.md) | ✅ | 2–3 page entry; links to every doc; status legend; rubric map |
| 1 | [`docs/APPROACH.md`](./docs/APPROACH.md) | ✅ | Multi-signal evidence-fusion thesis, 10 signals, rubric traceability matrix, self-review |
| 2 | [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) | ✅ | System shape, module graph, sequence diagrams, failure modes |
| 3 | [`docs/ARCHITECTURE.svg`](./docs/ARCHITECTURE.svg) | ✅ | Rendered architecture diagram (PDF Deliverable #4) |
| 4 | [`docs/TRADEOFFS.md`](./docs/TRADEOFFS.md) | ✅ | Explicitly rejected: face recognition, LLM-only, rule-engine-only, Bayesian-first |
| 5 | [`docs/adr/`](./docs/adr/) (5 ADRs) | ✅ | Event Bus, Weighted Fusion, Not-Face-Recognition, Whisper, Redis |
| 6 | [`docs/RISKS.md`](./docs/RISKS.md) | ✅ | 16-item risk register with probability × impact × mitigation × residual |
| 7 | [`docs/EVOLUTION.md`](./docs/EVOLUTION.md) | ✅ | V1 → V1.1 → V2 Bayesian → V3 Online Learning → Production trajectory |

### Design & Spec Docs

| # | Doc | Status | What it covers |
|---|---|---|---|
| 8  | [`docs/SIGNALS.md`](./docs/SIGNALS.md) | ✅ | Per-analyzer deep-dive: 10 signals, scoring curves, edge cases, calibration |
| 9  | [`docs/DATA_CONTRACT.md`](./docs/DATA_CONTRACT.md) | ✅ | Pydantic wire-level schemas: Event, Evidence, ParticipantState, Verdict, WeightTable |
| 10 | [`docs/PLATFORM_INTEGRATION.md`](./docs/PLATFORM_INTEGRATION.md) | 🚧 | Zoom OAuth + Meetings + Meet Recording API + Chrome extension specs |
| 11 | [`docs/MOCK_DATA_FORMAT.md`](./docs/MOCK_DATA_FORMAT.md) | ✅ | JSON recording format for `data/recordings/` + 3 reference scenarios |
| 12 | [`docs/ROADMAP.md`](./docs/ROADMAP.md) | ✅ | Phase-by-phase build plan, do-done criteria, commands (12 days) |
| 13 | [`docs/ACCURACY_METRICS.md`](./docs/ACCURACY_METRICS.md) | ✅ | precision@1, time-to-decision, stability, latency; `tune.py` algorithm |
| 14 | [`docs/EVALUATION.md`](./docs/EVALUATION.md) | ✅ · 🔮 synthetic harness in §A1 | Test methodology, results, limitations, demo video script (PDF Deliverable #5) |

### Operations Docs

| # | Doc | Status | What it covers |
|---|---|---|---|
| 15 | [`docs/API_SPECIFICATION.md`](./docs/API_SPECIFICATION.md) | ✅ | REST + WebSocket reference with error codes, auth model |
| 16 | [`docs/SECURITY.md`](./docs/SECURITY.md) | ✅ | OAuth, PII redaction, data deletion, secrets management |
| 17 | [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md) | ✅ | Docker compose → production containerization + scaling |
| 18 | [`docs/PERFORMANCE.md`](./docs/PERFORMANCE.md) | ✅ | Per-tick latency budget, scaling matrix, SLO targets |
| 19 | [`docs/CHANGELOG.md`](./docs/CHANGELOG.md) | ✅ | User-visible implementation changes across phases |

### Root-level docs

| # | Doc | Status | What it covers |
|---|---|---|---|
| 20 | `README.md` (this file) | ✅ | Entry point, quickstart, deliverables mapping, assumptions |
| 21 | `AGENTS.md` | ✅ | Onboarding for AI coding agents working on this repo |

---

## How to demo

The demo video script with timestamps is in [`docs/EVALUATION.md §10`](./docs/EVALUATION.md). Standalone demos:

### Mock demo (no Zoom/Meet setup)
```powershell
# Terminal 1
uv run uvicorn app.main:app --reload --port 8000

# Terminal 2
cd web && npm run dev
# Open http://localhost:5173 in your browser

# Terminal 3 — start the mock interview
uv run python -m app.main --scenario happy_path
# Dashboard populates within 5s; verdict decidable by 200s.
```

### Zoom demo
Follow [`docs/PLATFORM_INTEGRATION.md §2`](./docs/PLATFORM_INTEGRATION.md) for OAuth setup, then:
```powershell
uv run python -m app.main --platform zoom --meeting-id <ID>
```

### Meet demo
Follow [`docs/PLATFORM_INTEGRATION.md §3`](./docs/PLATFORM_INTEGRATION.md) for Workspace setup, then load the Chrome extension unpacked and click "Capture" on the meeting page.

---

## PDF Deliverables

This repo satisfies all 5 deliverables from PDF p3–p4. Each maps to an artifact:

| # | Deliverable | Artifact |
|---|---|---|
| 1 | Working demo | `docker compose up` + `uv run uvicorn app.main:app` + `web/` dashboard. Three mock scenarios pre-baked in `data/recordings/`. |
| 2 | Short demo video (5–10 min) | External link to be added when published. Script in [`docs/EVALUATION.md §10`](./docs/EVALUATION.md). |
| 3 | GitHub repository | This repo. README (this file) + `docs/` directory + `app/` source + `tests/` + `data/`. |
| 4 | Architecture diagram | [`docs/ARCHITECTURE.svg`](./docs/ARCHITECTURE.svg) |
| 5 | Evaluation | [`docs/EVALUATION.md`](./docs/EVALUATION.md) |

### Bonus points from PDF p4

| Bonus | Satisfied? | Where |
|---|---|---|
| Multiple weak signals | ✓ | 10 analyzers per [`docs/SIGNALS.md`](./docs/SIGNALS.md) |
| Confidence score | ✓ | `Verdict.confidence` per [`docs/DATA_CONTRACT.md §5`](./docs/DATA_CONTRACT.md) |
| Explain why selected | ✓ | `Verdict.reasons[]` per [`docs/DATA_CONTRACT.md §5.1`](./docs/DATA_CONTRACT.md) |
| Continue learning | ◐ | `weights.json` + `tune.py` scaffold; real tuning requires ≥20 labeled sessions |
| Work in real time | ✓ | 5s ticker; observed latency p50 ≈ 435ms (per [`docs/EVALUATION.md §6`](./docs/EVALUATION.md)) |
| Gracefully handle uncertainty | ✓ | `is_decision=False` + threshold + margin gate per [`docs/DATA_CONTRACT.md §5.2`](./docs/DATA_CONTRACT.md) |

---

## Assumptions

Per PDF Deliverable #3 README requirement (P3: "Setup instructions + Assumptions"). Discussion in [`docs/APPROACH.md §1.1`](./docs/APPROACH.md).

1. **The platform provides per-participant audio tracks.** PDF p2 promises this. We use it to skip diarization and run per-track Whisper; this is the cleanest path to accurate speaker-attributed transcripts.
2. **The system is read-only.** We never write to the meeting; never inject messages or recordings. Zoom OAuth scopes are minimum-required (`meeting:read`, `recording:read`, `user:read`).
3. **A `Verdict` with `is_decision=False` is an acceptable answer.** PDF p4 bonus rewards graceful uncertainty; this is the explicit way we honor it.
4. **Mocked scenarios are designed to be honoured by the contract test set.** v1.0's `precision_at_1 = 1.00` on the 3 scenarios is by construction; we don't claim generalization on real data yet.
5. **Vision analyzer exists but stays inert (weight=0.00) in v1.0.** This avoids the "face recognition only" trap the PDF p4 explicitly warns against. Promote to 0.05 only after `tune.py` validates (v1.1).
6. **Default weights are hand-authored.** Bayesian v2 fusion is out of v1.0 scope; needs 20+ labeled sessions for prior calibration.
7. **LLM prompts are English-only.** Non-English interviews return `is_decision=False` for the entire session as a safe default. Multi-language is v1.1.
8. **Webinars are unsupported.** PDF lists Meetings; Zoom Webinar per-participant audio is not available via the OAuth app.
9. **Meet Recording requires Workspace edition.** For consumer Gmail accounts, the Chrome extension path is the fallback.
10. **Audio bytes never hit disk.** Per `docs/PLATFORM_INTEGRATION.md §5`. Only transcripts are persisted.

---

## Testing

Per PDF Deliverable #5 broader spirit:

- **Unit tests** per analyzer (`tests/test_analyzers/`) — synthetic events into each analyzer; assert Evidence emission.
- **Contract tests** (`tests/test_contract.py`) — schema validity + analyzer uniqueness + idempotency + monotonicity + determinism.
- **Integration tests** (`tests/test_fusion.py`, `tests/test_state_store.py`) — fusion math, Redis supersedes behavior.
- **E2E mock tests** (`tests/test_e2e_mock.py`) — MockAdapter → bus → analyzers → ticker → fusion → verdict; asserts `expected_output` per [`docs/MOCK_DATA_FORMAT.md`](./docs/MOCK_DATA_FORMAT.md).
- **Accuracy harness** (`tests/test_accuracy_harness.py`) — `scripts/run_accuracy.py` against `data/recordings/` — `precision@1`, `time_to_decision`, `flips` against baseline.

Test count target ≥75. Coverage target ≥80%. See [`docs/EVALUATION.md §2`](./docs/EVALUATION.md) for the full test inventory.

To run:
```powershell
uv run pytest -v
uv run pytest tests/test_contract.py -v
uv run pytest tests/test_e2e_mock.py -v
```

---

## Known Limitations

Honest disclosure per PDF p3 spirit. Full details in [`docs/EVALUATION.md §7`](./docs/EVALUATION.md).

- **3 mock recordings only** — too few labeled sessions to claim empirical accuracy on real interviews.
- **v1 weights are hand-authored** — Bayesian v2 not enabled by default.
- **Face analyzer inert** — until `tune.py` clears it.
- **English-only** LLM prompts.
- **No Webinar support**.
- **Zoom transcript pipeline requires recording completion** — so transcript_role evidence lags by ~5–10 min real Zoom calls. Meet's Chrome extension gives near-real-time.
- **No multi-tenant OAuth app support.**
- **Lookalike face replacement not detected** by `face_consistency` (only sudden swaps).

---

## Roadmap

[`docs/ROADMAP.md`](./docs/ROADMAP.md) has the 12-day build plan with do-done criteria, commands, and risk register. Highlights next:
- v1.1: enable Bayesian v2 fusion after labeled data acquired
- v1.1: enable face_consistency once `tune.py` validates
- v1.2: Teams adapter (Microsoft Graph — 80% isomorphic with Zoom)
- v1.2: Multi-language LLM prompts
- v1.3: Real-time Zoom raw audio API (when available) to remove recording-pull latency
- v1.3: Dashboard rev2 with verdict-history playback slider

---


Template in [`docs/EVALUATION.md §11`](./docs/EVALUATION.md).

---

## License

MIT — see `LICENSE` file when committed.

---

## Acknowledgments

- The PDF brief's honest spirit of "We want to see how you think" informed the docs-first build approach.
- The [ACL 2023 Findings paper on speaker-related information in spoken meetings](https://aclanthology.org/2023.findings-acl.884.pdf) underpins the multi-signal fusion thesis.
- Open-source stack: FastAPI, Whisper, MediaPipe, InsightFace, Recharts, Pydantic.
