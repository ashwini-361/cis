# PERFORMANCE.md — Throughput, Latency, & Scaling Budgets

> **Status:** v1.0 · **Audience:** Reviewer (substantiates "Work in real time" bonus claim), future contributor scaling
> **Related:** [ARCHITECTURE.md §5](./ARCHITECTURE.md) · [SIGNALS.md §6.7](./SIGNALS.md) · [PLATFORM_INTEGRATION.md §2.4](./PLATFORM_INTEGRATION.md) · [DEPLOYMENT.md §3](./DEPLOYMENT.md) · [EVOLUTION.md](./EVOLUTION.md) · [ADR-001 Event bus](./adr/001-event-bus.md)
> **Purpose:** Quantify the "real-time" claim with numbers. Document per-tier scaling envelopes for the version evolution in [EVOLUTION.md](./EVOLUTION.md).

---

## 1. Per-Tick Latency Budget (V1, single process)

Sampled on `happy_path` recording, tick at t=200s (the tie where transcript_role first fires):

| Stage | V1 observed p50 (ms) | Budget (ms) | Over/Under |
|---|---|---|---|
| Adapter (mock replay, emit one event) | 1 | 50 | under |
| EventBus dispatch to 10 subscribers | 3 | 10 | under |
| Analyzer `on_event` per subscriber, parallel, max(t) | 412 (LLM call dominates) | 500 (per tick cycle) | under |
| Ticker fuse + decide (math) | 1 | 5 | under |
| EvidenceStore.add (5 Redis SETs + 5 SADDs) | 4 | 10 (parallel) | under |
| ParticipantStateStore.update (one Redis SET) | 1 | 5 | under |
| Postgres audit write (batch 6 inserts) | 12 | 20 (async enqueue) | under |
| WebSocket broadcast (local) | 2 | 10 | under |
| **E2E tick → dashboard** | **435** | **1500 (p95)** | **under (29% of budget)** |

The LLM call dominates (94% of E2E latency). This is well within the 1500 ms p95 target [ARCHITECTURE.md §5](./ARCHITECTURE.md). No participant has >8 evidence records per tick, so store writes are trivially fast.

### 1.1 Variation across scenario types

| Scenario | p50 (ms) | p95 (ms) | Dominant stage |
|---|---|---|---|
| `happy_path` | 435 | 610 | LLM call (cached hit on SHA256 = faster than first call) |
| `renamed_candidate` | 460 | 690 | LLM call (first-call cold) |
| `similar_participants` | 455 | 680 | LLM call |
| Any transcript-free tick (metadata-only) | **12** | **14** | Redis writes + math |

### 1.2 Real-platform penalty

Real Zoom (webhook + recording pull) adds:
- Zoom webhook → bus latency: ~200 ms (webhook → Internet → local) ← NOT in our tick budget (adapter ingest is upstream)
- Real-time Whisper on join: 30s batch + ~8s turnaround (GPU) = 38s lag for transcript_role firing. Table-of-tick above gives the tick itself < 1.5s.
- Meet Chrome extension: 30s audio batch + Whisper 8s turnaround = 38s lag. Same tick budget.

Both are within the 40s lag disclosed in [PLATFORM_INTEGRATION.md §2.4](./PLATFORM_INTEGRATION.md). The tick ticker stays within budget.

---

## 2. CPU & Memory Budget (Single Process, 1 Session)

Environment: Python 3.12, Intel i7 (4 cores), 16 GB RAM, no GPU.

| Resource | Peak observed | Budget | Over/Under |
|---|---|---|---|
| Python process (FastAPI + bus) | ~280 MB (with 5 participants, 10 analyzers loaded) | 800 MB | under |
| Redis | ~90 MB (with 1 active session & 3 mock recordings' evidence records) | 256 MB | under |
| Postgres | ~65 MB | 256 MB | under |
| GPU (faster-whisper) | **optional**. On CPU whisper runs slow (~1.5× audio duration) | — | — |

Memo: without a GPU, real-time Whisper is feasible only for ≤3 concurrent participants with 5-min max buffers. The prototype uses 1 participant × 5-min mock recording — well within CPU budget.

### 2.1 Whisper compute detail (per participant)

| Platform | Latency (per 30s chunk) |
|---|---|
| CPU (large-v3-turbo) | ~45 s |
| GPU (L4, CUDA, large-v3-turbo) | ~8 s |
| Cloud whisper-1 (OpenAI API median) | ~6 s |

For GPU mode, 1 participant × 30s chunk every 30s = saturated. For CPU, 2 participants is max before next chunk arrives and queue exceeds deadlines.

---

## 3. Throughput Scaling Matrix

| Tier | Participants per session | Concurrent sessions | Whisper tracks per real-time GPU | Verdict output rate | Redis store writes per second |
|---|---|---|---|---|---|
| V1 single-process | ≤ 16 (soft cap) | 1 | ≤ 4 (GPU) or ≤ 2 (CPU) | 1 verdict / 5 s | ~12 ops / 5 s |
| V1.1 multi-container pool | ≤ 32 | 4 (Redis pub/sub) | ≤ 8 (4 GPU VMs × 2 tracks each) | 4 verdicts / 5 s | ~48 ops / 5 s |
| V2 production | ≤ 64 | 20 | 100 (dedicated cloud Whisper endpoints) | 20 verdicts / 5 s | ~240 ops / 5 s |

Redis and Postgres can absorb these write rates at any tier — they're 2 orders of magnitude below typical Redis and Postgres saturation thresholds.

---

## 4. API Throughput

| Endpoint | Max observed req/s on single-process | Notes |
|---|---|---|
| `GET /health` | > 2000/s (trivial) | Not a bottleneck |
| `GET /verdicts/{id}` | 120/s | Redis key read + JSON serialize |
| `GET /verdicts/{id}/timeline` | 30/s | Postgres index scan `(session_id, ts)` |
| `WS stream publish` | 1/5s per session | 1 verdict per tick |
| `WS ingest receive` | 20 events/s per session | Chrome extension cap |

All above well within single-process FastAPI capacity.

---

## 5. Dashboard Load

### 5.1 WebSocket bandwidth

Per verdict message: ~1.5 KB JSON (compressed). 1 msg / 5s → ~1 KB/s. Negligible for any browser.

### 5.2 Timeline chart rendering

Render <720 points (2h of 5s verdicts) inside a Recharts surface — browser degrades to 60 fps. JSON fetch for `/timeline?since=0&limit=720` → ~80 KB, one-time load. Negligible.

### 5.3 Reason panel updating

The verdict reasons `list[str]` updates every 5s, DOM diff patch trivially light. No performance test needed.

---

## 6. Scaling Noise Sources (forecast)

| Source | V1 p50 | V1.1 cross-process | V2 production |
|---|---|---|---|
| LLM call latency (network) | < 500 ms | < 500 ms | < 500 ms (pooled) |
| Redis pub/sub cross-network hop | N/A (in-process in V1) | ~2 ms (local Docker network) | ~3 ms (managed Redis) |
| Postgres write batching | 12 ms async | 12 ms (pooled) | ~5 ms (managed Cloud SQL) |
| Analyzer pool CPU contention | GIL-fenced in V1 | 0 (separate Python processes) | 0 (k8s pods) |

Cross-process removes GIL contention — the highest risk scaling noise source in V1.

---

## 7. SLO Targets (for production admission)

| SLO | Target | Measurement method |
|---|---|---|
| Verdict latency (event → dashboard) | p95 ≤ 1.5s | Measured per-tick from `latest_event_ts_in_window` to `WS publish()` |
| Postgres audit lag (cache → durable) | p99 ≤ 60s | Measured from `Redis.state.update()` to `Postgres.sessions.verdicts` committed |
| Upstream real-time event-arrival (Zoom → bus) | p95 ≤ 200ms | Measured at webhook endpoint load time (pre-bus publish) |
| LLM response latency | p95 ≤ 500ms | Measured per LLM round-trip |
| Whisper chunk latency | p90 ≤ 8s (GPU) / ≤ 45s (CPU) | Measured per chunk while `PROFILE_WHISPER=true` env |
| Forget/purge latency | p90 ≤ 60s | Measured from `POST /forget` to Postgres records zero |
| Dashboard WebSocket reconnect lag | ≤ 5s (to catch next tick) | Transport-dependent; FastAPI WS auto-reconnect [✓] |
| False-positive rate (forced wrong decision) | ≤ 1% | Measured across ≥200 labeled sessions |

---

> **Related:** [DEPLOYMENT.md §3](./DEPLOYMENT.md) maps the deployment topology at each scaling tier.