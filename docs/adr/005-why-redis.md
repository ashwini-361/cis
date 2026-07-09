# ADR-005: Redis for live state + Postgres for audit

> **Status:** Accepted · **Date:** 2026-07-09 · **Decider:** you · **Supersedes:** none · **Superseded by:** none
> **Related:** [ADR-001 Event bus](./001-event-bus.md) · [../ARCHITECTURE.md §1.4, §1.10](../ARCHITECTURE.md) · [../DEPLOYMENT.md](../DEPLOYMENT.md) · [../PERFORMANCE.md](../PERFORMANCE.md) · [../SECURITY.md §2](../SECURITY.md)

---

## Context

The system needs two distinct persistence responsibilities from day one:

| Job | Trait profile |
|---|---|
| 1 — Live state (`ParticipantState`, recent `Evidence` per participant, current `Verdict`s) | Hot reads/writes every 5s × every participant; ultimately-consistent; TTL-able; low read latency ≤1ms; tolerates data loss across session restart. |
| 2 — Audit + learning data (sessions, verdicts, evidences — per [`docs/ACCURACY_METRICS.md §4`](../ACCURACY_METRICS.md)) | Sequential write-only for the audit timeline; ad-hoc reads from `tune.py`; must persist across restart; queryable (SQL); needs indexing on `session_id`, `ground_truth_candidate_id`; backing store for the React dashboard confidence-curve chart. |

Redis is the textbook fit for job 1; Postgres is the textbook fit for job 2. SQLite was considered for both. Kafka was considered for an audit bus.

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| **A — Redis for live + Postgres for audit** | Mature primitives for both jobs; Redis ttl/expiration gives free evidence-staleness handling; Postgres gives a queryable store for `tune.py` and the dashboard history; both have first-class Python clients. The cross-process scale story for Redis pub/sub is documented in [ADR-001](./001-event-bus.md). | Two stores to operate; data synchronization is application-owned (resolve by writing the Postgres audit record from the realtime ticker once per tick, eventually consistent). |
| **B — SQLite for everything** | Zero operational overhead; single file; tests run on in-memory; trivially portable. | Not horizontally scalable; SQLite's write-locked database under multi-process writes is exactly the cross-process scale scenario ADR-001 leaves the door open for; poor fit for audit at >1000 verdicts / session * N sessions. |
| **C — Redis-only (live + audit timeline)** | One store. Redis lists sorted by ts = verdict timeline. | No SQL; `tune.py` would need to scan all sessions linearly; cannot index on `ground_truth_candidate_id`; audit retention becomes a purity project. Could work for toy scale; not for production post-tuning. |
| **D — Postgres-only + cached live state in Python memory** | One store. | Single-process state dies on restart — unacceptable for the 30-min interview use case; can't broadcast verdict-timeline to multiple dashboard clients. |
| **E — Plus Kafka for an event-sourced audit log** | Best eventual durability and replay; gold-standard for audit. | Massive operational overhead (3 brokers, schema registry, ops). Not justifiable at the 5s × ≤10-participant scale of a single interview. |

## Decision

**Option A — Redis (live) + Postgres (audit).** Specified in [`docs/ARCHITECTURE.md §1.4 + §1.10`](../ARCHITECTURE.md) and the schemas in [`docs/ACCURACY_METRICS.md §4.1`](../ACCURACY_METRICS.md).

Concrete policies:

1. **Redis** stores `Evidence` per `(session_id, participant_id, feature)` with 24h TTL; `ParticipantState` per `(session_id, participant_id)` with 30 min TTL post-session; the realtime ticker's in-flight `Verdict` per session with 5 min TTL.
2. **Postgres** stores `sessions`, `verdicts`, `evidences` tables (full schemas in [`docs/ACCURACY_METRICS.md §4.1`](../ACCURACY_METRICS.md)) — written once per tick from the realtime ticker via a bounded queue (≤60s lag acceptable for audit-only writes).
3. **Cross-store consistency** is eventual. The realtime ticker optimizes Redis; an async background worker drains the Postgres write queue every 500 ms. A session-end reconciler scan confirms Postgres caught up within 60 s of session end.
4. **Redis pub/sub** is the cross-process tier documented in ADR-001 — analyzer containers subscribe to event channels, never talk to Postgres directly.
5. **Operational topology** in `docker-compose.yml` (per [`docs/ROADMAP.md §0.4`](../ROADMAP.md)) spins up both services in one `docker compose up`.

## Consequences

### Positive
- Both stores are well-known; Python and CI ready today (`redis-py`, `aioredis`, `asyncpg`, `psycopg`).
- Redis TTL gives us free stale-evidence cleanup — strictly more robust than a hand-rolled GC task.
- Postgres queries enable `tune.py` to fetch labeled sessions (`WHERE ground_truth_candidate_id IS NOT NULL`) and the dashboard to render confidence-curve history (`SELECT * FROM verdicts WHERE session_id = $1 ORDER BY ts`).
- Cross-process scale story (ADR-001) works naturally with Redis pub/sub.
- Docker images exist for both stores so the prototype is reproducible.

### Negative
- Two stores means two failure modes — Redis crashes drop live state; Postgres crashes drop audit. Mitigation: each layer degrades gracefully per [ARCHITECTURE.md §4 failure mode table](../ARCHITECTURE.md). Redis-dead → in-memory asyncio queue fallback for one process; Postgres-dead → in-memory ring buffer of last 1000 verdicts.
- Slight overhead: ticker writes to Redis (≤1 ms) + enqueues Postgres (≤5 ms batched). Net worst-case verdict update cost ~ 6 ms added per tick. Measurable in [PERFORMANCE.md](../PERFORMANCE.md).
- Two connection pools to maintain. Acceptable cost for production-grade architecture.

### Neutral
- A considered variant was **Redis Streams** for the audit timeline instead of Postgres — they'd still serve the dashboard chart, but SQL is easier for hand-tuning engineers to query in ad-hoc ways. Stick with Postgres for the audit tier; Redis stays strictly for hot live state.

## Validation

- `tests/test_state_store.py` covers the `EvidenceStore.add` supersedes mechanic, ttl expiry simulation, and `ParticipantStateStore.update` round-trip.
- `tests/test_session_store.py` covers the Postgres audit table insertion and verbatim replay.
- A `tests/test_session_reconciler.py` test asserts Postgres catches up within 60 s of `SESSION_END`.

## Classification

- **Type:** Infrastructure / storage choice
- **Cost of reversal:** Medium. Swapping Redis for Memcached or Postgres for ClickHouse would be a moderate infra migration; both stores are isolated behind `EvidenceStore` / `ParticipantStateStore` / `SessionStore` classes in `app/store/`.
- **Risk if wrong:** Low. Both stores are industry-standard at the scale of this prototype. Reviewer-friendly.
