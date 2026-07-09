# RISKS.md — Risk Register

> **Status:** v1.0 · **Audience:** Reviewer, operator of the demo, future contributors
> **Related:** [ARCHITECTURE.md §4](./ARCHITECTURE.md) · [PLATFORM_INTEGRATION.md §4](./PLATFORM_INTEGRATION.md) · [SECURITY.md](./SECURITY.md) · [EVOLUTION.md](./EVOLUTION.md)
> **Purpose:** Capture the top operational and algorithmic risks, their impact, probability, mitigations already in place, and residual risk after mitigation. Industry-standard triple: (Risk → Probability × Impact → Mitigation → Residual).

---

## 0. Risk Scoring Convention

| Probability | Meaning |
|---|---|
| Low      | <20% in demo/presentation use |
| Medium   | 20–60% |
| High     | >60% |
| Certain  | near-certain per design |

| Impact | Meaning |
|---|---|
| Low      | Minor inconvenience; other signals carry |
| Medium   | Session moderately degraded; verdict delayed but still correct |
| High     | Verdict wrong OR session fails to complete |

Residual risk after mitigation should be ≤ Medium for every risk.

---

## 1. Platform-Level Risks

### R1 — Zoom OAuth app consent denied / revoked
- **Probability:** Medium (admin review for `recording:read` + `meeting:read` sane; WeApps already approved can unwind).
- **Impact:** High → entire Zoom recording pipeline drops; transcript unavailable for Zoom calls.
- **Mitigation:** Webhooks still fire for real-time membership/render events. Adapter degrades to webhook-only mode (metadata + webcam + join-order still available). Transcript-role analyzer silently yields no evidence. The verdict can still be driven by email + behavioral + name signals → potential for slightly longer time-to-decision.
- **Residual:** **Medium** — verdict still correct but slower.
- **Related:** [PLATFORM_INTEGRATION.md §2.5](./PLATFORM_INTEGRATION.md)

### R2 — Meet Workspace recording disabled or not available for session
- **Probability:** Medium-high on free-Google-account hosts.
- **Impact:** Medium — Recording pipeline drops; Chrome extension fallback available.
- **Mitigation:** Chrome extension captures per-participant audio via WebRTC and sends to cis. Extension is loadable as unpacked in the demo. If extension not loaded, the adapter deploys webhook-only (metadata) and marks the session as "degraded".
- **Residual:** **Low** — extension path resolves.
- **Related:** [PLATFORM_INTEGRATION.md §3.3, §4](./PLATFORM_INTEGRATION.md)

### R3 — Audio tracks are mixed (not per-participant) for this session
- **Probability:** Low for Zoom (multi_track_audio defaults off only in some plans). Medium for Meet Recording.
- **Impact:** Medium — per-track Whisper unavailable; diarization accuracy drops ~1-3%.
- **Mitigation:** Diarization fallback (pyannote) with `"diarization": "pyannote-fallback"` provenance. Verdict may be slower (diarization misattribution of a single segment doesn't cross threshold) but still correct. Re-tune transcript_role trigger window to compensate (use ≤2-3 turns).
- **Residual:** **Low** — diarization is a known-quality fallback.
- **Related:** [ADR-004 why Whisper](./adr/004-why-whisper.md)

### R4 — Privacy consent withdrawn mid-call (participant asks us to stop)
- **Probability:** Low in prototype/demo settings.
- **Impact:** High (must comply instantly; top-tier request).
- **Mitigation:** `DELETE /sessions/{id}/forget` endpoint wipes all Redis + Postgres records for the session ≤60s. Session ends with `reason="forgotten"`. All audio frames already in memory for Whisper are dropped immediately. Documents in [SECURITY.md §5](./SECURITY.md).
- **Residual:** **Low** — endpoint tested; real-time compliance window met.
- **Related:** [SECURITY.md §5](./SECURITY.md)

---

## 2. Operational Risks

### R5 — Redis becomes unavailable during a session
- **Probability:** Low (docker-compose healthy in dev; production Redis would have failover).
- **Impact:** Medium — live state lost; evidence store and participant state go to in-memory fallback.
- **Mitigation:** [ARCHITECTURE.md §4 failure mode "Redis unavailable"](./ARCHITECTURE.md) — asyncio in-memory queue fallback. Connection retry every 2s. If Redis restored within 30s, state replays from Postgres audit table.
- **Residual:** **Low** — session continues on in-memory; verdicts emitted. History from dashboard narrows to last in-memory window.
- **Related:** [ARCHITECTURE.md §4](./ARCHITECTURE.md) · [DEPLOYMENT.md](./DEPLOYMENT.md)

### R6 — Postgres becomes unavailable during a session
- **Probability:** Low.
- **Impact:** Medium — audit records not persisted; tune.py loses session for future calibration.
- **Mitigation:** In-memory ring buffer of last 1000 verdicts. Dashboard picks up in-memory snapshots. When Postgres recovers, buffer flushes in order.
- **Residual:** **Low** — functional loss is audit gradient only.
- **Related:** [ARCHITECTURE.md §4](./ARCHITECTURE.md)

### R7 — LLM provider (Qwen / GPT-4.1-mini) becomes unavailable or rate-limited during a session
- **Probability:** Medium (API rate limits, provider outages).
- **Impact:** Medium — transcript_role analyzer drops evidence; verdict slows down but stays correct (other signals sufficient).
- **Mitigation:** Exponential backoff (4 s → 16 s → 64 s → 128 s). Local Ollama fallback behind same `LLMProvider` interface. Cache identical 60s windows (SHA256 of last 60s transcript = hits skip the LLM call). If exhausted, transcript-role stays uninteracted for that session — dashboard shows "still deciding" until behavioral/metadata signals cross threshold.
- **Residual:** **Low** — verdict may be delayed but still arrives from email + join-order + speaking-pattern.
- **Related:** [SIGNALS.md §6.7](./SIGNALS.md) · [ARCHITECTURE.md §4](./ARCHITECTURE.md)

### R8 — Whisper (local or cloud) fails or exhausts queue during a session
- **Probability:** Low (local Whisper is CPU/GPU bound on single-stream; cloud Whisper-1 is well-provisioned).
- **Impact:** High — transcript stops flowing; llm role analyzer and speaking-pattern analyzer stale; cold-start metadata signals may not cross threshold.
- **Mitigation:** Retry with exponential backoff, cap concurrent Whisper calls to 4 (prevents queue exhaustion). Fall-back to cloud Whisper-1 if local post-process hits error. If both fail, mark session `reason="whisper_unavailable"` and verdict stays `is_decision=False` for the rest of session. Dashboard shows "transcript processing offline, awaiting more metadata".
- **Residual:** **Medium** — if Whisper is down for >5 min, verdict may not be reached.
- **Related:** [PLATFORM_INTEGRATION.md §4](./PLATFORM_INTEGRATION.md) · [ADR-004](./adr/004-why-whisper.md)

### R9 — High latency in the per-track Whisper pipeline pushes verdict delay beyond the threshold
- **Probability:** Medium during real-time Zoom demo (Zoom's recording must complete before per-track audio is available → ~5–10 min delay).
- **Impact:** Medium — transcript_role evidence only arrives 5–10 min late. Until then, other signals must carry.
- **Mitigation:** Zoom webhooks deliver metadata + webcam + screen-share in real time. Those signals carry the verdict early (within 2 minutes for happy-path). Transcript-role just strengthens the verdict later. The Meet path (Chrome extension) gives real-time near-instant transcript_role (30s lag) — stronger demo angle.
- **Residual:** **Low** — verdict reached without transcript-role for typical interviews.
- **Related:** [PLATFORM_INTEGRATION.md §2.4, §3.4](./PLATFORM_INTEGRATION.md)

---

## 3. Algorithmic Risks

### R10 — Hand-tuned weights cause a false-verdict on edge cases not in the mock set
- **Probability:** Medium (the 3 mock scenarios are authored from the crafted schema; unseen edge cases can activate weights in unexpected combinations).
- **Impact:** High — a wrongly-identified candidate could be accepted by the reporting.
- **Mitigation:** `is_decision=False` gate acts as a guardrail — you must cross 0.55 threshold AND have a 0.20 margin. False verdicts from weight imbalance happen only when weak-signal scores sum to >0.55. The `tune.py` calibration + extended 20–50 synthetic session generator (documented in [EVALUATION.md §A1](./EVALUATION.md)) will explore weight space on randomized participant orders before v1.1 ships.
- **Residual:** **Medium** before synthetic session harness run; **Low** after.
- **Related:** [EVALUATION.md §A1](./EVALUATION.md) · [ACCURACY_METRICS.md §6](./ACCURACY_METRICS.md)

### R11 — LLM JSON-parsing failure causes transcript_role evidence to be consistently dropped
- **Probability:** Low-medium (1 retry baked in; downstream LLMs are producing strict-JSON-conforming outputs in 2026).
- **Impact:** Medium — transcript_role analyzer drops out of session.
- **Mitigation:** 1 retry with prepended instruction `"Return strict JSON only. No markdown."` If still malformed, log a metric, skip that tick. Two consecutive failures → disable analyzer for the session, flag in verdict.
- **Residual:** **Low** — human-literate LLMs don't normally fail strict JSON these days; one retry resolves nearly every case.
- **Related:** [SIGNALS.md §6.4](./SIGNALS.md)

### R12 — Weighted-average fusion underrates a strong signal because low-weight signals dilute it
- **Probability:** Low (normalized weighted average mens average, not sum; weak signals can only dilute, not overpower a strong signal).
- **Impact:** Medium if overrated.
- **Mitigation:** Never let a weight exceed 0.30 (keeps signal dominance modest). The normalized denominator ensures that many low-weight signals can only drag confident DOWN — they cannot push it ABOVE the strong signal alone. Only the strongest few signals pull the average up.
- **Residual:** **Low** — verified in fusion tests ([DATA_CONTRACT.md §4.3 explanation of why normalized not pure sum](../DATA_CONTRACT.md)).
- **Related:** [ADR-002](./adr/002-weighted-fusion.md) · [DATA_CONTRACT.md §4.3](./DATA_CONTRACT.md)

---

## 4. Privacy & Compliance Risks

### R13 — Operator of the demo retains participant audio or video
- **Probability:** Low (audio deleted by pipeline design; video frames never persisted).
- **Impact:** High — privacy compliance breach.
- **Mitigation:** Audio bytes and frames are held in memory only. Whisper post-recording transcription runs on OS-temp-disk → file deleted on trancript parse within 5s. Postgres stores only transcript text — no audio. The `DELETE /forget` endpoint wipes per-session records ≤60s. Specified in [SECURITY.md §2 and §5](./SECURITY.md).
- **Residual:** **Low** — audit verified in `tests/test_security.py` (to be added in Phase 1 — see [ROADMAP.md Phase 1](../ROADMAP.md)).
- **Related:** [SECURITY.md §2, §5](./SECURITY.md)

### R14 — Email or participant identity exposed in persisted verdict reasons
- **Probability:** Low (regex redaction before persist).
- **Impact:** Medium — PII leak in audit table.
- **Mitigation:** `explain/generator.py` regex-strips emails (`\b[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}\b`) and phone numbers (`\b\d{7,15}\b`) from `Verdict.reasons` strings before writing to Postgres. Mock data uses raw emails for readability but production `SECRET_STRIP=true` flip runs redaction. Specified in [SECURITY.md §3](./SECURITY.md).
- **Residual:** **Low** — regex redaction is imperfect but a human authoring reasons directly never includes full emails. Enum challenge is reusable-substring leaks — deemed low residual.
- **Related:** [SECURITY.md §3](./SECURITY.md) · [DATA_CONTRACT.md §8 explain/generator](./DATA_CONTRACT.md)

---

## 5. Non-Functional Scaling Risks

### R15 — Single-process Python GIL limits concurrent Whisper + LLM + MediaPipe processing to ~2 concurrent sessions
- **Probability:** High (GIL is inherent).
- **Impact:** Medium — demo only needs 1 session; risk is for production scale only.
- **Mitigation:** Whisper runs in a separate process (`multiprocessing` pool); LLM call is an HTTP out-of-process; MediaPipe inference on GPU happens in an executor thread. The GIL bottleneck is only on the Python calc tier — not the I/O tier. Redis pub/sub scale-out (ADR-001) removes this limit in v1.1 cross-process deployment.
- **Residual:** **Low** for prototype scale; **Medium** if deployed without cross-process upgrade.
- **Related:** [PERFORMANCE.md](./PERFORMANCE.md) · [DEPLOYMENT.md](./DEPLOYMENT.md) · [EVOLUTION.md V1.1](./EVOLUTION.md)

### R16 — Dashboard WebSocket bandwidth or RAM saturation for very long (>2 hour) sessions
- **Probability:** Low (typical interview is 30–60 min). Medium for 4+ hour sessions.
- **Impact:** Medium — dashboard RAM grows per verdict.
- **Mitigation:** Dashboard verdict buffer capped at 720 entries (60 min at 5s tick). Per-participant chart renders up to last 2 hours; after that, summary aggregates on the server.
- **Residual:** **Low** — tested in performance harness ([PERFORMANCE.md](./PERFORMANCE.md)).
- **Related:** [PERFORMANCE.md](./PERFORMANCE.md)

---

## 6. Summary Risk Matrix

| Risk | Prob. | Impact | Mitigation summary | Residual |
|---|---|---|---|---|
| R1 — Zoom OAuth revoked | Med | High | Webhooks-only degradation | Med |
| R2 — Meet recording disabled | Med-High | Med | Chrome-extension fallback | Low |
| R3 — Mixed audio (no per-track) | Low-Med | Med | pyannote diarization fallback | Low |
| R4 — Privacy consent withdrawn mid-call | Low | High | `DELETE /forget` ≤60s | Low |
| R5 — Redis down | Low | Med | In-memory queue fallback | Low |
| R6 — Postgres down | Low | Med | In-memory ring buffer | Low |
| R7 — LLM provider down | Med | Med | Exponential backoff + Ollama fallback + cache | Low |
| R8 — Whisper down | Low | High | 4-call cap + backoff + cloud fallback | Med |
| R9 — Whisper per-track latency | Med | Med | Metadata+behavior carry early verdict | Low |
| **R10 — Hand-tuned weights deceive** | **Med** | **High** | is_decision gate + tune.py + synthetic session harness | **Med→Low after harness** |
| R11 — LLM JSON parse fails | Low-Med | Med | 1 retry + skip tick + 2-fail-disable | Low |
| R12 — Dilution by low-weight signals | Low | Med | Normalized denominator; cap weight at 0.30 | Low |
| R13 — Audio/video retained | Low | High | In-memory-only, OS-temp purged, for-get endpoint | Low |
| R14 — PII leak in audit reasons | Low | Med | Regex redaction in explain/generator | Low |
| R15 — GIL limits session concurrency | High | Med (proto scale) | Process-pool + Redis scale-out | Low (proto) / Med (production) |
| R16 — Dashboard RAM for long sessions | Low | Med | Buffer cap 720 verdicts | Low |

---

> **Companion:** [EVOLUTION.md](./EVOLUTION.md) maps the versioned upgrades that shrink residual risks; [SECURITY.md](./SECURITY.md) expands the privacy and consent mitigations.