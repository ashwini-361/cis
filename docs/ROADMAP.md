# ROADMAP.md — Build Phases, Time, Owners, Commands

> **Status:** v1.0
> **Cross-refs:** [APPROACH.md](./APPROACH.md) · [ARCHITECTURE.md](./ARCHITECTURE.md) · [DATA_CONTRACT.md](./DATA_CONTRACT.md) · [SIGNALS.md](./SIGNALS.md) · [PLATFORM_INTEGRATION.md](./PLATFORM_INTEGRATION.md) · [MOCK_DATA_FORMAT.md](./MOCK_DATA_FORMAT.md) · [ACCURACY_METRICS.md](./ACCURACY_METRICS.md) · [EVALUATION.md](./EVALUATION.md)
> **Purpose:** Phase-by-phase actionable plan with estimates, do-done criteria, and runnable commands. Adjusted from initial ChatGPT's 4–5 day estimate to 7–9 days once we add: real-platform integration with Zoom + Meet, the accuracy harness, the dashboard, demo video, and the 5 PDF deliverables.

---

## 0. Total Effort Summary

| Phase | Days | Owner | Output |
|---|---|---|---|
| **Phase 0 — Project Scaffold** | 0.5 | you | Project tree, docker-compose, pyproject, env, README skeleton |
| **Phase 1 — Core Contracts & Bus** | 0.5 | you | `app/schema.py`, `app/bus.py`, contract tests |
| **Phase 2 — Mock Adapter + First Recording** | 0.5 | you | `MockAdapter` + happy_path.json |
| **Phase 3 — Fusion Engine + Realtime Ticker** | 0.5 | you | Weighted fusion + 5s ticker + Redis state |
| **Phase 4 — Metadata + Join + Webcam + Screen Analyzers** | 1.0 | you | 4 analyzers + weights.json + unit tests |
| **Phase 5 — Speaking + Transcript-role Analyzers** | 1.5 | you | turn-taking + LLM analyzer (largest phase) |
| **Phase 6 — Vision Analyzer (optional, behind flag)** | 1.0 | you | MediaPipe + InsightFace; weight=0.00 |
| **Phase 7a — Zoom Adapter (real platform)** | 1.5 | you | OAuth + Recording API + per-track Whisper |
| **Phase 7b — Meet Adapter + Chrome extension** | 1.5 | you | Calendar/Drive + extension |
| **Phase 8 — Dashboard + WebSocket** | 0.5 | you | React + Recharts |
| **Phase 9 — Accuracy Harness + `tune.py`** | 0.5 | you | precision@1 + time-to-decision + stability |
| **Phase 10 — Deliverables Polish** | 1.0 | you | README, demo video, architecture diagram refresh, evaluation writeup |
| **TOTAL** | **10.0** | | All PDF Deliverable #1–#5 + bonus points |

Add 20% buffer → **realistic estimate: 12 days**. The buffer absorbs the LLM-prompt-iteration tack and adapter OAuth-debugging.

---

## Phase 0 — Project Scaffold

### 0.1 Do-done criteria
- `docker-compose up` brings up redis + postgres cleanly.
- `uv sync` (or equivalent) installs all dependencies.
- `pytest` runs and reports 0 tests (test infrastructure LIVE, no tests yet).
- `ruff check .` passes with no warnings.

### 0.2 Project tree

```
cis/
├── README.md
├── AGENTS.md                       # opencode agent instructions
├── pyproject.toml
├── docker-compose.yml
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── bus.py
│   ├── schema.py                   # Pydantic models (DATA_CONTRACT.md)
│   ├── store/
│   │   ├── __init__.py
│   │   ├── evidence.py
│   │   ├── state.py
│   │   └── session.py
│   ├── analyzers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── metadata.py
│   │   ├── join_order.py
│   │   ├── webcam.py
│   │   ├── speaking_pattern.py
│   │   ├── transcript_role.py
│   │   ├── vision.py
│   │   └── screen_share.py
│   ├── fusion/
│   │   ├── __init__.py
│   │   ├── engine.py               # v1-weighted
│   │   ├── bayesian.py             # v2 (stubbed for v1.0)
│   │   └── weights.py
│   ├── realtime/
│   │   ├── __init__.py
│   │   ├── ticker.py
│   │   └── updater.py
│   ├── explain/
│   │   ├── __init__.py
│   │   └── generator.py
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── mock.py
│   │   ├── zoom.py
│   │   └── meet.py
│   └── api/
│       ├── __init__.py
│       ├── routes.py
│       └── websocket.py
├── data/
│   ├── weights/
│   │   └── weights.json            # default v1.0
│   └── recordings/
│       ├── happy_path.json
│       ├── renamed_candidate.json
│       └── similar_participants.json
├── docs/
│   └── (12 docs — built in this session)
├── web/                             # React dashboard (Phase 8)
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       └── App.tsx
├── scripts/
│   └── tune.py                      # Phase 9
├── tests/
│   ├── conftest.py
│   ├── test_contract.py
│   ├── test_bus.py
│   ├── test_fusion.py
│   ├── test_analyzers/
│   ├── test_e2e_mock.py
│   └── test_accuracy_harness.py
└── .github/workflows/
    └── ci.yml
```

### 0.3 Commands

```powershell
# From I:\Project\meet\cis\
# 1. Initialize package
uv init --lib cis
uv add fastapi uvicorn redis pydantic rapidfuzz \
      faster-whisper openai pyyaml pytest pytest-asyncio ruff mypy \
      httpx websockets
uv add --dev pytest-cov

# 2. docker-compose.yml for redis + postgres
# Use snippet from §0.4 below

# 3. Bring infra up
docker compose up -d

# 4. Verify
docker compose ps
docker compose logs redis | Select-String "Ready to accept connections"
docker compose logs db | Select-String "database system is ready"
```

### 0.4 docker-compose.yml snippet

```yaml
version: "3.9"
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    command: ["redis-server", "--appendonly", "yes"]
    volumes: ["redis_data:/data"]
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: cis
      POSTGRES_PASSWORD: cis_dev
      POSTGRES_DB: cis
    ports: ["5432:5432"]
    volumes: ["pg_data:/var/lib/postgresql/data"]
volumes:
  redis_data:
  pg_data:
```

### 0.5 .env.example

```bash
REDIS_URL=redis://localhost:6379/0
POSTGRES_URL=postgres://cis:cis_dev@localhost:5432/cis

# LLM provider
LLM_PROVIDER=openai-compatible                    # | ollama
OPENAI_BASE_URL=http://localhost:1234/v1
OPENAI_API_KEY=local-dev

# Zoom OAuth
ZOOM_CLIENT_ID=
ZOOM_CLIENT_SECRET=
ZOOM_ACCOUNT_ID=
ZOOM_REDIRECT_URI=http://localhost:3000/zoom/callback

# Google Meet / Workspace
GOOGLE_APPLICATION_CREDENTIALS=./keys/meet-sa.json
GOOGLE_DELEGATED_ADMIN=user@yourdomain.com

# Whisper
WHISPER_MODEL=large-v3-turbo
WHISPER_DEVICE=cuda OR cpu
```

---

## Phase 1 — Core Contracts & Bus

### 1.1 Do-done criteria
- `app/schema.py` exports `Event`, `EventEnvelope`, `EventType`, `Evidence`, `ParticipantState`, `Verdict`, `WeightTable`, `SessionEnvelope`, `RejectedHypothesis`, plus all per-EventType payload-typed aliases.
- `app/bus.py` implements `EventBus` with sub/unsub and FIFO + dedupe per-source.
- `tests/test_contract.py` validates the schema + bus FIFO behavior.
- All Pydantic models are immutable (`model_config = ConfigDict(frozen=True)`).

### 1.2 Commands

```powershell
# Validate schema
uv run python -c "from app.schema import Evidence; print(Evidence.model_json_schema())"

# Run contract tests
uv run pytest tests/test_contract.py -v
```

### 1.3 Conformance to spec
All types per [DATA_CONTRACT.md](./DATA_CONTRACT.md) §1–§6, hardcoded defaults NOT to modify during testing.

---

## Phase 2 — Mock Adapter + happy_path Recording

### 2.1 Do-done criteria
- `MockAdapter` reads `data/recordings/happy_path.json` per [MOCK_DATA_FORMAT.md](./MOCK_DATA_FORMAT.md) §1.
- On `start_session`, emits `SESSION_START` + `METADATA_*` derived from recording.
- Replays `events[]` in order, sleeping until each `ts`, then emits.
- Test `test_mock_replay` walks the recording in `tests/test_e2e_mock.py` collecting emitted events; asserts sequence matches JSON order.

### 2.2 Author happy_path recording authoring

```powershell
# Use the snippet in MOCK_DATA_FORMAT.md §4 as the starting point.
# Save to data/recordings/happy_path.json
$recording = @'
{ ... happy_path.json content from MOCK_DATA_FORMAT.md ... }
'@
$recording | Set-Content -Path data/recordings/happy_path.json -Encoding utf8
```

### 2.3 Validation

```powershell
uv run python -m json.tool data/recordings/happy_path.json | Out-Null   # JSON parses
uv run pytest tests/test_e2e_mock.py::test_replay -v
```

---

## Phase 3 — Fusion Engine + Realtime Ticker

### 3.1 Do-done criteria
- `app/fusion/engine.py` implements `fuse(evidences, t) -> float` per [DATA_CONTRACT.md](./DATA_CONTRACT.md) §4.3.
- `app/realtime/ticker.py` runs every 5s when a session is live.
- `app/store/state.py` reads/writes `ParticipantState` to Redis.
- `tests/test_fusion.py` covers: cold-start (empty evidences → 0.0), single sticky evidence, decay over time, supersedes behavior.
- Realtime ticker test uses `pytest-asyncio` to step time mocked (dependency-injected `sleep`).

### 3.2 Fusion engine skeleton

```python
# app/fusion/engine.py
import math
from app.schema import Evidence

LAMBDA_DEFAULT = 1.0 / 300.0     # 5-min default half-life

def fuse(evidences: list[Evidence], t: float) -> float:
    numerator = 0.0
    denominator = 0.0
    for e in evidences:
        if e.expires_at is None:
            decay = 1.0
        else:
            age = max(0.0, t - e.ts)
            half_life = (e.expires_at - e.ts)
            decay = math.exp(-math.log(2) * age / half_life) if half_life > 0 else 1.0
        numerator += e.weight * e.score * decay
        denominator += e.weight * decay
    if denominator < 1e-6:
        return 0.0
    return numerator / denominator
```

### 3.3 Decider per [DATA_CONTRACT.md](./DATA_CONTRACT.md) §5.2.

---

## Phase 4 — Metadata + Join + Webcam + Screen Analyzers (1 day)

### 4.1 Analyzers to ship in this phase

```
metadata.py     # name_similarity + email_match + device_name (disabled)
join_order.py   # join_order
webcam.py       # webcam_usage
screen_share.py # screen_share_content (CLIP test stub)
```

### 4.2 Do-done criteria
- Each analyzer passes `tests/test_analyzers/test_metadata.py`, etc.
- Each analyzer integrates with the bus and emits Evidence when fed events.
- `weights.json` correctly has all feature keys.

### 4.3 Sample test

```python
# tests/test_analyzers/test_metadata.py
async def test_email_match(metadata_analyzer, mock_session):
    e = Event(type=EventType.PARTICIPANT_JOINED,
              envelope=...,
              payload={"participant_id":"P1","display_name":"Ashwini",
                       "email":"ashwini.kumar@gmail.com","join_order":1})
    evidence = await metadata_analyzer.on_event(e)
    assert any(ev.feature == "email_match" and ev.score == 1.0 for ev in evidence)
```

---

## Phase 5 — Speaking Pattern + Transcript-role Analyzers (1.5 days)

### 5.1 Why 1.5 days
- LLM provider integration: ~0.5d (provider switching, JSON parsing resilience, rate limit backoff)
- Speaking-pattern turn detection: ~0.5d
- Sliding-window state management: ~0.5d

### 5.2 Do-done criteria
- transcript_role analyzer emits Evidence per [SIGNALS.md](./SIGNALS.md) §6 with at-least 3 transcript segments.
- Speaking-pattern analyzer correctly identifies interviewer→candidate alternation in happy_path test.
- Both analyzers pass idempotency tests (re-feeding same segment → no new evidence).

### 5.3 LLMProvider abstraction

```python
# app/analyzers/transcript_role.py
class LLMProvider(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> dict: ...

class OpenAICompatibleProvider:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url
        ...
```

### 5.4 Caching to keep cost/latency low
- Cache key = SHA256 of last 60s transcript concatenation.
- On cache hit, skip the LLM call entirely.

---

## Phase 6 — Vision Analyzer (1 day, behind a flag, weight=0.00)

### 6.1 Do-done criteria
- `vision.py` runs MediaPipe Face Detection on frames, generates an InsightFace ArcFace embedding per detected face.
- Maintains per-participant EMA embedding; flags swaps.
- All features behind a feature flag `VISION_ENABLED=false` by default.
- This phase may be skipped if timeline is tight; weight=0 means the system works without it.

### 6.2 Hard rule
- Vision analyzer's `face_consistency` feature weight stays 0.00 in `weights.json` even after Phase 6 ships. `tune.py` (Phase 9) is the only path to flip it.

---

## Phase 7a — Zoom Adapter (1.5 days)

### 7a.1 Do-done criteria
- OAuth flow end-to-end with refresh token persistence to OS keychain.
- Webhook endpoint `/zoom/webhook` receives signed events and validates HMAC-SHA256.
- Recording pull after `meeting.ended` webhook: download multi-track audio + per-track Whisper transcription.
- One demo Zoom call recorded end-to-end; recording pulled, transcript assembled, fed to analyzers, verdict reached.

### 7a.2 Prerequisites
- A Zoom OAuth app registered with `meeting:read`, `recording:read`, `user:read` scopes.
- An admin-approved publishable account OR a Developer sandbox account.
- Cloud Recording enabled on the host user.

### 7a.3 Commands

```powershell
# Register webhook
$webhook_url = "https://<ngrok-url>/zoom/webhook"

uv run python scripts/register_zoom_webhook.py --url $webhook_url

# Test webhook signature verification
uv run pytest tests/test_analyzers/../ingest/test_zoom_webhook.py -v
```

---

## Phase 7b — Meet Adapter + Chrome Extension (1.5 days)

### 7b.1 Do-done criteria
- Chrome extension authored (Manifest V3) and loadable in `chrome://extensions`.
- Extension captures per-participant audio via `chrome.tabCapture` + `getUserMedia`/`RTCPeerConnection.ontrack`.
- Sends Opus chunks via WebSocket to cis app.
- One demo Meet call captured end-to-end, transcript assembled, verdict reached.

### 7b.2 Extension build

```powershell
cd web/meet-capture-extension
npm run build     # vite-based bundling for the extension
# Load unpacked from dist/
```

### 7b.3 Path selection
- If Meet's Recording API works for your Workspace edition: use Calendar + Drive path (cleaner, no extension).
- Otherwise: use extension-only path for the demo video.

---

## Phase 8 — Dashboard + WebSocket (0.5 days)

### 8.1 Do-done criteria
- React app connects to `ws://localhost:3000/sessions/{id}/stream`.
- Renders verdict card (candidate, confidence) or "still deciding" state.
- Renders per-participant confidence chart over time.
- Reason panel shows bullet list with rendered reasons, with monotonically-updating animation.

### 8.2 Stack
- Vite + React + TypeScript + Tailwind + Recharts.
- ~3 components: `<VerdictCard />`, `<TimelineChart />`, `<ReasonPanel />`.

### 8.3 Commands
```powershell
cd web
npm install
npm run dev  # hot reload on http://localhost:5173
```

---

## Phase 9 — Accuracy Harness + `tune.py` (0.5 days)

### 9.1 Do-done criteria
- `scripts/run_accuracy.py` runs fusion on all recordings in `data/recordings/`, produces a markdown table of precision@1, time-to-decision p50/p90, flip count (per [ACCURACY_METRICS.md](./ACCURACY_METRICS.md)).
- `scripts/tune.py` ingests recordings, re-weights `weights.json` per [ACCURACY_METRICS.md](./ACCURACY_METRICS.md) §6.
- One labeled mock set (3 recordings) drives a sanity run; results document baseline accuracy in [EVALUATION.md](./EVALUATION.md).

### 9.2 Commands
```powershell
uv run python scripts/run_accuracy.py --recordings data/recordings/
uv run python scripts/tune.py          # writes data/weights/weights.v1.1.json
```

---

## Phase 10 — Deliverables Polish (1 day)

### 10.1 Deliverables checklist (PDF p3–p4)

| # | Deliverable | Artifact | Source doc |
|---|---|---|---|
| 1 | Working demo | `docker compose up` + `uv run uvicorn app.main:app` + React dashboard | [README.md](../README.md) |
| 2 | 5–10 min demo video | `demo.mp4` | script in [EVALUATION.md](./EVALUATION.md) §10 |
| 3 | GitHub repo | `git remote add origin …` | [README.md](../README.md) |
| 4 | Architecture diagram | [ARCHITECTURE.svg](./ARCHITECTURE.svg) | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| 5 | Evaluation writeup | [EVALUATION.md](./EVALUATION.md) | this doc |

### 10.2 Demo video script (5–10 min, PDF Deliverable #2)

| Time | Section | What to show |
|---|---|---|
| 0:00 | Title + thesis | Show [ARCHITECTURE.svg](./ARCHITECTURE.svg); state multi-signal evidence-fusion thesis |
| 0:45 | Architecture | Walk event bus → analyzers → evidence store → fusion → dashboard using [ARCHITECTURE.svg](./ARCHITECTURE.svg) |
| 1:45 | Approach | Why "sensors not classifiers", why per-track Whisper, why v1 weighted, why "still deciding state" |
| 2:45 | Demo: mock happy_path | Run `docker compose up`, `pytest test_e2e_mock.py --recordings happy_path.json`, dashboard shows 0% → 97% over 5 minutes |
| 4:00 | Demo: mock renamed_candidate | Same setup with renamed_candidate.json; shows graceful confidence dip and recovery |
| 5:30 | Demo: real Zoom call | Brief 30s recording capture, transcript pulled, verdict reached |
| 6:00 | Demo: real Meet call | Brief 30s extension capture and verdict |
| 6:30 | Trade-offs | What we cut (face recognition, multi-platform Teams), why |
| 7:00 | What we'd improve next | v2 Bayesian fusion, vision analyzer enablement, online learning, Teams adapter |
| 8:00 | Submission | Closing note; mention GitHub link + email to priya@sherlock.sh |

### 10.3 Submission email

```
To: priya@sherlock.sh
Subject: Sherlock Internship Challenge - {your_name}
Body:
Hi Priya,
Please find my submission for the Sherlock Internship Challenge here:
https://github.com/{user}/{repo_name}

The repository contains:
- A real-time multi-signal evidence-fusion system for candidate identification
- Real Zoom + Google Meet integration
- Three mock scenarios (happy_path, renamed_candidate, similar_participants)
- Demo video: https://youtube.com/...
- Architecture diagram: docs/ARCHITECTURE.svg
- Evaluation writeup: docs/EVALUATION.md
- Docs index: README.md

Looking forward to your feedback,
{Name}
```

---

## Critical Path & Risk Register

| Step | Risk | Mitigation |
|---|---|---|
| Phase 1–3 | Schema not frozen if we iterate mid-build | Disallow schema changes after Phase 1 ends. Use git tags `schema-v1.0` for visibility. |
| Phase 5 | LLM provider latency / cost overruns | Cache transcript windows; batch 5s ticks; use Qwen / local Ollama |
| Phase 7a | Zoom OAuth sandbox account approval takes 5+ business days | Request sandbox day 1 of Phase 0 to align |
| Phase 7a | Zoom `multi_track_audio` deprecated for new OAuth apps | Verify with Zoom support before building; have diarization fallback ready (Phase 4 pr | pyannote) |
| Phase 7b | Chrome extension store review ~3 days | Distribute unpacked for demo only; document manual load steps in README |
| Phase 9 | `tune.py` not enough data (<20 labeled sessions) | For v1.0 ship WITHOUT tuning (default weights); `tune.py` runs as warm-up only |

---

## Phase-Time Gantt

```
                   DAY 1 2 3 4 5 6 7 8 9 10 11 12
Phase 0           ───
Phase 1           ──
Phase 2           ─
Phase 3           ──
Phase 4              ────────
Phase 5                     ─────────────────
Phase 6                                  ────────
Phase 7a                                 ──────────────         ← in parallel w/ Phase 6, dep once OAuth approved
Phase 7b                                          ──────────────
Phase 8                                                   ────
Phase 9                                                   ────
Phase 10                                                     ────────
                                                                ↑ buffer
```

Phases 6, 7a, 7b can run in parallel (different code, different dependencies). Phase 8 and 9 share Phase 5 as prerequisite. Phase 10 final once all above done.

---

## Commands Cheat Sheet (for [README.md](../README.md))

```powershell
# Setup
git clone https://github.com/{user}/cis.git && cd cis
uv sync
docker compose up -d

# Configure
copy .env.example .env     # then edit secrets in .env

# Run for development
uv run uvicorn app.main:app --reload --port 3000
cd web && npm run dev       # dashboard on :5173

# Run tests
uv run pytest -v
uv run pytest tests/test_contract.py -v               # contract tests
uv run pytest tests/test_e2e_mock.py -v               # end-to-end mocks

# Lint & type-check
uv run ruff check .
uv run mypy app/

# Accuracy harness (Phase 9)
uv run python scripts/run_accuracy.py --recordings data/recordings/

# Tune weights (Phase 9)
uv run python scripts/tune.py

# Demo a single mock scenario
uv run python -m app.main --scenario happy_path       # see scenario at data/recordings/
```

---

## Change Log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-07-09 | Adjusted from original 4–5 day plan to 12-day plan with real-platform integrations, dashboard, deliverables, accuracy harness. |

---

> **Next:** Read [ACCURACY_METRICS.md](./ACCURACY_METRICS.md) for what `scripts/run_accuracy.py` and `tune.py` actually compute.
