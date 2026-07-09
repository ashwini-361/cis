# API_SPECIFICATION.md — REST + WebSocket Reference

> **Status:** v1.0 · **Audience:** Dashboard developer, reviewer (supports PDF Deliverable #1 working demo + #3 repo)
> **Related:** [DATA_CONTRACT.md](./DATA_CONTRACT.md) · [ARCHITECTURE.md §1.8](./ARCHITECTURE.md) · [DEPLOYMENT.md](./DEPLOYMENT.md)
> **Purpose:** Complete HTTP and WebSocket surface with schemas, error codes, and authorization model.

---

## 1. Base URL & Authentication

During dev:
```
Base: http://localhost:3000
```

All routes except `/health` require a bearer token:
```
Authorization: Bearer <API_KEY>
```
The `API_KEY` is set via `CIS_API_KEY` env var. Falls back to `demo-key` in dev mode. No OAuth flow at the API layer — that's per-platform adapter auth only.

---

## 2. REST Endpoints

### 2.1 `GET /health`

- **Purpose:** Liveness check for docker-compose orchestration.
- **Response:** `200 OK`
  ```json
  {
    "status": "healthy",
    "redis": "available",
    "postgres": "available",
    "llm_provider": "qwen",
    "version": "1.0.0"
  }
  ```
  or `503` with `"redis": "unavailable"` and `"Postgres"` if either store is down.

### 2.2 `POST /sessions`

- **Purpose:** Start a new meeting session.
- **Request body:**
  ```json
  {
    "platform": "mock",
    "scenario": "happy_path",
    "expected_duration_min": 30,
    "ground_truth_candidate_id": null
  }
  ```
  | Field | Type | Required | Notes |
  |---|---|---|---|
  | `platform` | `"mock" \| "zoom" \| "meet"` | yes | Which adapter to use. |
  | `scenario` | string | only for mock | Name of recording under `data/recordings/`. |
  | `expected_duration_min` | int | yes | Upstream-hint for TTL and watchdog. |
  | `ground_truth_candidate_id` | string \| null | optional | Only for labeled sessions; `null` for production. |
- **Response:** `201 Created`
  ```json
  {
    "session_id": "mock-sess-001",
    "platform": "mock",
    "start_wall_clock": "2026-07-09T10:30:00Z",
    "urls": {
      "stream": "/sessions/mock-sess-001/stream",
      "verdicts": "/sessions/mock-sess-001/verdicts",
      "forget": "/sessions/mock-sess-001/forget"
    }
  }
  ```
- **Errors:**
  | Status | Body | Condition |
  |---|---|---|
  | `400` | `{"error":"unknown_platform","supported":["mock","zoom","meet"]}` | platform unknown |
  | `400` | `{"error":"scenario_not_found","path":"happy_path"}` | mock recording missing |
  | `409` | `{"error":"session_already_active","current_session_id":"..."}` | ≤1 session per process in v1.0 |

### 2.3 `GET /sessions/{session_id}/verdicts`

- **Purpose:** Poll current verdict state (non-streaming).
- **Response:** Latest `Verdict` in JSON per [DATA_CONTRACT.md §5](./DATA_CONTRACT.md):
  ```json
  {
    "session_id": "mock-sess-001",
    "ts": 200.0,
    "platform": "mock",
    "candidate_id": "P1",
    "candidate_name": "Ashwini",
    "confidence": 0.97,
    "runner_up_id": "P3",
    "runner_up_confidence": 0.45,
    "margin": 0.52,
    "is_decision": true,
    "reasons": ["Email matched calendar metadata (+0.300)", ...],
    "rejected_hypotheses": [...],
    "analyzer_count": 6,
    "total_evidence": 11,
    "engine_version": "v1-weighted"
  }
  ```
- **Errors:**
  | Status | Body | Condition |
  |---|---|---|
  | `404` | `{"error":"session_not_found"}` | session_id unknown |
  | `503` | `{"error":"session_not_ready"}` | session started, verdict not computed yet |

### 2.4 `GET /sessions/{session_id}/verdicts/timeline`

- **Purpose:** Full verdict history as ordered array (for dashboard chart).
- **Query params:**
  | Param | Type | Default | Notes |
  |---|---|---|---|
  | `since` | float (seconds) | 0 | Only verdicts with ts ≥ since. |
  | `limit` | int | 500 | Max rows returned. |
  | `asc` | bool | `false` | `true` = ascending by ts. |
- **Response:** `200 OK`
  ```json
  {
    "session_id": "...",
    "verdicts": [
      { "ts": 5.0, "candidate_id": null, "confidence": null, "is_decision": false, ... },
      { "ts": 200.0, "candidate_id": "P1", "confidence": 0.97, "is_decision": true, ... }
    ]
  }
  ```
- **Errors:** Same as 2.3.

### 2.5 `POST /sessions/{session_id}/forget`

- **Purpose:** Right-to-erasure: purge all evidence and verdicts for this session within 60s. See [SECURITY.md §5](./SECURITY.md).
- **Response:** `202 Accepted`
  ```json
  { "status": "purging", "session_id": "...", "estimated_clean_by_ms": 5000 }
  ```
  Then async sweep. On completion, the session ID will be unknown → `GET /sessions/{id}/verdicts` returns `404`.

### 2.6 `GET /sessions/{session_id}/participants`

- **Purpose:** Current participant list with their confidences.
- **Response:** `200 OK`
  ```json
  {
    "session_id": "...",
    "participants": [
      {
        "participant_id": "P1",
        "display_name": "Ashwini",
        "email_present": true,
        "confidence": 0.97,
        "is_present": true
      },
      ...
    ]
  }
  ```

---

## 3. WebSocket

### 3.1 `WS /sessions/{session_id}/stream`

- **Protocol:** ws or wss (dev: ws://localhost:3000/sessions/{id}/stream)
- **Auth:** Bearer token in query: `?token=<API_KEY>` (or `Cookie: token=<API_KEY>`)
- **Sub-protocol:** none — messages are uncompressed JSON text frames.
- **Direction:** Server → client only. Client sends a simple keep-alive ping `{"ping": true}` every 30s; server responds `{"pong": true}`.
- **Messages:** One JSON frame every 5s (tick rate), containing the latest `Verdict` same shape as 2.3.
- **Connect message:** On connection, the server sends the most recent verdict immediately (cold-start or running).
- **Disconnect:** Clean disconnect OK; server re-sends missed verdicts on re-connection if session still active.
- **Errors:** If token invalid, `4001` close code with JSON `{"error":"unauthorized"}`. If session expired, `4002` `{"error":"session_ended"}`.

### 3.2 Additional WS endpoint: `WS /sessions/{session_id}/ingest`

- **Purpose:** Direct event injection (for the Meet Chrome extension to send real-time audio chunks, events, participant metadata).
- **Direction:** Client → server only.
- **Messages:** Client sends `Event` objects (same shape as [DATA_CONTRACT.md §2](./DATA_CONTRACT.md)), one per frame. The server bus validates and ingests.
- **Auth:** Bearer token in query.
- **Rate limit:** 20 events/sec maximum.

### 3.3 WebSocket timeline sequence (client lifecycle)

```
Client connects ──────── recv latest Verdict
Client wait            ...
tick (5s later) ───────── recv new Verdict
tick (5s later) ───────── recv
...                      ...
Session ends ──────────── recv final Verdict (is_decision=[true|false])
Server sends close ────── close code 1000 (normal)
```

---

## 4. Error Codes Reference

| Code | Class | HTTP | Meaning |
|---|---|---|---|
| `SESSION_NOT_FOUND` | client (4xx) | 404 | session_id not recognized. |
| `SESSION_NOT_READY` | server (5xx) | 503 | session started but verdict loop hasn't produced output yet. |
| `UNKNOWN_PLATFORM` | client (4xx) | 400 | platform not in {"mock","zoom","meet"}. |
| `SCENARIO_NOT_FOUND` | client (4xx) | 400 | mock recording JSON file missing. |
| `MISSING_AUTH` | client (4xx) | 401 | Bearer token missing or invalid. |
| `SESSION_ALREADY_ACTIVE` | client (4xx) | 409 | v1.0 single-process limit. |
| `RATE_LIMITED` | client (4xx) | 429 | Too many requests (LLM/Whisper sub-system). |
| `INTERNAL_STORE_DOWN` | server (5xx) | 503 | Redis or Postgres unavailable. |
| `INTERNAL_ANALYZER_ERROR` | server (5xx) | 500 | Analyzer raised unhandled exception. |
| `FEATURE_NOT_ENABLED` | server (5xx) | 503 | Feature flag off (e.g. vision, Bayesian). |

---

## 5. API Versioning

Endpoint paths are unversioned (v1 defaults). Future versions add `/v2/` prefix. Backward compatibility: the v1 endpoint stays for at least one transition release.

---

## 6. Rate Limits

| Path | Rate | Concurrency |
|---|---|---|
| `POST /sessions` | 1/min | 1 active session (v1 single-process) |
| `GET /health` | unlimited | — |
| `GET /sessions/{id}/verdicts` | 10/sec | — |
| `GET /sessions/{id}/verdicts/timeline` | 1/sec | — |
| `WS /sessions/{id}/stream` | 1 connection/session | unlimited dashboard clients |
| `WS /sessions/{id}/ingest` | 20 events/sec | 1 client (Chrome extension) |

---

> **Related:** [SECURITY.md](./SECURITY.md) for auth model, token rotation, and PII redaction on API payloads.