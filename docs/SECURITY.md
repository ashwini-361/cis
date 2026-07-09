# SECURITY.md — Privacy, OAuth, Secrets, & Data Deletion

> **Status:** v1.0 · **Audience:** Reviewer (answers "what about security?" in silent before you ask), operator of the demo
> **Related:** [PLATFORM_INTEGRATION.md §5](./PLATFORM_INTEGRATION.md) · [DEPLOYMENT.md](./DEPLOYMENT.md) · [API_SPECIFICATION.md §2.5](./API_SPECIFICATION.md) · [RISKS.md §4](./RISKS.md) · [ADR-003 why-not-face-recognition](./adr/003-why-not-face-recognition.md)
> **Purpose:** Document the privacy posture, authentication model, PII handling, secrets storage, and data-deletion obligations. Protects the demo from "did you handle this?" surprises.

---

## 1. Authentication Model

### 1.1 API layer

Bearer token `CIS_API_KEY` env var. Falls back to `"demo-key"` in dev mode. All routes except `/health` require the token. No OAuth flow at the API layer — the adapters handle platform-level OAuth separately.

**Token rotation:** `POST /sessions` regenerates an inner-internal session token used for ingest WS only. Programmatic.

### 1.2 Platform layer (Zoom, Meet)

- **Zoom:** OAuth 2.0 server-to-server: `ZOOM_CLIENT_ID` + `ZOOM_CLIENT_SECRET` + `ZOOM_ACCOUNT_ID`. Scopes: `meeting:read`, `recording:read`, `user:read` (never `meeting:write`). Refresh token stored in OS keychain (`keyring` Python lib → Windows Credential Manager / macOS Keychain). `access_token` never logged.
- **Meet (Workspace path):** Google service account `.json` credential file stored in gitignored `keys/meet-sa.json`. Domain-wide delegation for Workspace admin `user@yourdomain.com` (env var). Scope: `drive.readonly`, `calendar.readonly`, `admin.directory.user.readonly`.
- **Meet (Chrome extension path):** No backend credential; the extension acts as a user-in-the-loop, sending events over the ingest WebSocket with the session token.

### 1.3 WebSocket ingest token

The ingest WS endpoint uses a short-life session token generated on `POST /sessions` and returned in the response body `"tokens": {"ingest": "..."}`. Expires with the session. The Chrome extension or adapter client stores this for one session only.

---

## 2. Minimized Data Retention

Per PDF p4 bonus "Work in real time" and Sherlock's own fraud-detection mission:

| Data type | Where it lives | Retained? | Retention window | Justification |
|---|---|---|---|---|
| Raw audio bytes (Whisper input) | OS temp disk during processing | NO, deleted ≤5s after transcription | 5 s | Per [PLATFORM_INTEGRATION.md §5](./PLATFORM_INTEGRATION.md) |
| Raw video frames (Vision input) | In memory only, in the vision analyzer process | NO, never persisted | session lifetime | No reason to retain — consumption score only |
| Screen-share frames (CLIP input) | In memory | NO, never persisted | session lifetime | Labels only extracted |
| Transcript text | Postgres `transcripts` table | YES (trimmed) | 3 months (for tune.py) | The core training data for future learning |
| Evidence scores + reasons | Postgres `evidences` table | YES | 3 months | Audit trail required for tune.py |
| Verdicts (confidence timeline) | Postgres `verdicts` table | YES | 3 months | Dashboard chart; audit required for Sherlock's own fraud pattern analysis |
| Participant emails (raw) | Mock data only | Mock data: YES (raw). Production: NO — `sha256(email)` only | Mocks: forever (readable). Prod: 3 months (hashed) | Simplicity for demo reviewers; privacy in production |
| Face embeddings (512-dim ArcFace) | In memory per session only | NO | session lifetime | Per ADR-003 — consistency only, never coherent to any reference photo |
| Participant display names | Postgres `participants` table (sessions.expected_participants + join payloads) | YES (trimmed) | 3 months | Required for dashboard rendering + verdict history navigation |
| Calendar invite metadata | Postgres `sessions` table | YES | 3 months | Reference validation for schedule signal |
| OAuth refresh tokens | OS keychain (`keyring` Python lib) | YES (encrypted at rest by OS) | indefinite (auto-refreshed) | Required for Zoom + Google Meet adapter restarts |

---

## 3. PII Redaction

The `explain/generator.py` applies a regex scrubber before persisting `Verdict.reasons[]`:

| Pattern | Replaced with | Scope |
|---|---|---|
| Email addresses `\b[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}\b` | `"[redacted email]"` | Reason strings + rejected hypothesis strings |
| Phone-like `\b\d{7,15}\b` | `"[redacted phone]"` | Same columns |
| Calander-invite IDs matching calendar URL patterns (determined to be a zoom/meta calendar pattern) | `"[redacted meeting_url]"` | Same |

In the mock data, **emails are displayed raw** so the reviewer can read the scenario. The redaction regex runs even on mock data but sends an `unredaction_log` for future scripts to re-embed.

Production mode sets `SECRET_STRIP=true` env var which forces all emails → hashes on transmit from platform adapters BEFORE the event hits the bus. The redactor then becomes a strictly in-memory filter; no raw email ever enters Postgres in production.

---

## 4. Secrets Management

| Secret | Storage | Rotation |
|---|---|---|
| `CIS_API_KEY` | `.env` file (gitignored) | Manual via updating .env + restart |
| `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET`, `ZOOM_ACCOUNT_ID` | `.env` (gitignored) | Manual via Zoom console |
| `ZOOM_WEBHOOK_SECRET` | `.env` (gitignored) | Rotated when Zoom rotates; we accept rotated token at runtime from a separate env var `ZOOM_WEBHOOK_SECRETS` with comma-separated values |
| `ZOOM_OAUTH_REFRESH_TOKEN` | OS keychain (`keyring`) + `.env` fallback for dev | Auto-rotated by `ZoomAuth.refresh()`; never git |
| `GOOGLE_APPLICATION_CREDENTIALS` file | `keys/meet-sa.json` (gitignored) | Manual via Google Cloud Console |
| `OPENAI_API_KEY` / `OLLAMA_URL` | `.env` (gitignored) | Rotated normally per provider console |

---

## 5. Data Deletion (Right-to-Erasure / Privacy Compliance)

### 5.1 `POST /sessions/{session_id}/forget`

Per [API_SPECIFICATION.md §2.5](./API_SPECIFICATION.md), this endpoint:

1. Immediately key-splits: `DELETE` from Redis all keys prefixed `ev:`, `state:`, `v:session_id`.
2. Async queues a Postgres sweep in a background worker (`forget_worker()`).
3. Sweeps `sessions`, `verdicts`, `evidences` rows for that `session_id` within ≤60 s.
4. Returns `202 Accepted` with an estimated done time.

A `GET /sessions/{session_id}/verdicts` after the sweep returns `404`.

### 5.2 Session-data bleaching (the "friend agreed to demo on Zoom, forget the data after")

A demo workflow:

```powershell
# Demo a Zoom call, then forget it entirely
uv run curl -X POST "http://localhost:3000/sessions/{id}/forget" -H "Authorization: Bearer demo-key"
```

All audio (already deleted within 5s), all transcript, all verdict history → gone within 60s. This satisfies the consent agreement with the demo partner.

### 5.3 Mock data is written by the operator from raw text — no consent needed

All mock recordings under `data/recordings/` are human-authored from synthetic names; no real candidate data. There is no "consent" needed for mock data as long as we don't republish recordings as evidence of Sherlock's own internal case law.

---

## 6. Attack Surface & Hardening

### 6.1 Zoom webhook signature verification

Zoom Webhook payloads MUST be signed with `X-Zm-Signature` using Zoom's `ZOOM_WEBHOOK_SECRET` HMAC SHA-256. Our `/zoom/webhook` endpoint:

1. Re-reads the raw request body bytes (before any JSON parse).
2. Computes `hmac_sha256(secret, raw_body_bytes)`.
3. Compares to `X-Zm-Signature-high` header (v2 signature scheme).
4. On mismatch → `401 Unauthorized` with `error: "invalid_webhook_signature"`.
5. The bus does NOT propagate unsigned events.

Test vector: `tests/test_zoom_webhook.py` uses the sample payload from Zoom's official test page (https://marketplace.zoom.us/docs/guides/guides/webhooks/verification/).

### 6.2 Meet extension WebSocket token

The Chrome extension connects over `ws://localhost:3000/sessions/{id}/ingest?token=<session_ingest_token>`. The token is one-time per session. No other client can inject ingest events for that session.

If the token is leaked to another tab, the extension-only endpoint closes with `4001 unauthorized` on mismatch.

### 6.3 Dependency audit

`uv lock` runs in CI. Dependabot / Renovate will be configured in `.github/dependabot.yml` before the repo is pushed. No dependencies with known CVs in the dependency tree after Phase 1.

---

## 7. Privacy Posture (One Slide)

| Principle | Compliance |
|---|---|
| Biometric data (faces) | Never persisted. Consistency, not recognition (ADR-003). |
| Audio data (voice prints) | Never persisted. Deleted ≤5s after transcription. |
| Transcript (speech content) | Persisted for 3 months; forget endpoint allows per-session deletion. |
| Participant identity (name, email) | Hashed in production; raw in mock for readability. |
| Calendar metadata (when, who) | Persisted 3 months; names redacted for non-candidate participants. |
| Right to erasure | `/forget` within 60s per session. |
| Cross-border data transfer | Not a current concern; all data stays on the operator's machine (docker-compose) in v1. |
| Consent | Real-platform demos are consented explicitly with the demo partner; mocks are synthetic. |

---

> **Related:** [RISKS.md §4](./RISKS.md) maps the residual privacy risks and their mitigations.