# ADR-001: Adopt an in-process async Event Bus as the system spine

> **Status:** Accepted · **Date:** 2026-07-09 · **Decider:** you · **Supersedes:** none · **Superseded by:** none
> **Related:** [../ARCHITECTURE.md §1.2](../ARCHITECTURE.md) · [../DATA_CONTRACT.md §2](../DATA_CONTRACT.md) · [ADR-002 Weighted fusion](./002-weighted-fusion.md) · [ADR-005 Why Redis](./005-why-redis.md)

---

## Context

The system needs to ingest events from heterogeneous meeting platforms (Zoom OAuth, Meet Recording API, Chrome extension, mock replay JSON), distribute those events to ~10 independent analyzers, persist evidence, run a 5s ticker, and broadcast verdicts over a WebSocket. The analyzers must be **decoupled** — that requirement flows directly from the PDF p4 bonus line "use multiple weak signals instead of relying on one rule": if analyzers know about each other, the "weak" property becomes illusion because they cross-contaminate.

Three architectural patterns were considered:

| Option | Shape |
|---|---|
| A — Direct method calls | Each platform adapter calls `analyzer.on_event(...)` directly per event. |
| B — Message queue (Kafka/RabbitMQ) | Adapter publishes to a broker; analyzers consume. |
| C — In-process async event bus + optional Redis pub/sub | Adapter publishes typed `Event` to a single in-process `EventBus`; analyzers subscribe by `EventType`. Redis pub/sub bridges cross-process deployments. |

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| A — Direct calls | Lowest latency (~µs); no infrastructure. | Couples every adapter to every analyzer; can't add an analyzer without editing every adapter; can't swap analyzers independently; mocks become brittle. |
| B — External broker | Cross-process scale built-in; durable; well-known patterns. | Operational overhead (Kafka cluster, RabbitMQ ops); ~10 ms per hop; new dependency for the demo; not justifiable for a sub-second pipeline. |
| C — In-process async bus + optional Redis | Zero infra for prototype; FIFO per-source + dedupe trivially implemented in Python); analyzer-per-`EventType` subscription from day 1; Redis pub/sub only adds when we need cross-process — same code-path, different transport. | Single Python process limits vertical scale (mitigation: Redis pub/sub transparently multi-process). |

## Decision

**Option C — in-process async event bus with optional Redis pub/sub.**

Concretely: `app/bus.py` exports an `EventBus` class. Adapters call `await bus.publish(event)`. Each analyzer registers `bus.subscribe([EVENT_TYPE...], self.on_event)`. The bus deduplicates by `(source, envelope.sequence)` to be defensive against platform-side replays. For cross-process scale, the same `EventBus` transparently fans out to Redis pub/sub (`aioredis.from_url(REDIS_URL)`); analyzers can run in separate containers of the same image, all subscribed to `events:{event_type}` channels. The interface stays identical.

## Consequences

### Positive
- Analyzers stay decoupled (PDF p4 "weak signals" requirement).
- Zero infra dependencies for v1 prototype (single-process); in-place path to scale via Redis only when deployed.
- One interface (`bus.publish` / `bus.subscribe`) makes adapters and analyzers trivially mockable in tests.
- Per-source FIFO + dedupe constraint is testable in `tests/test_bus.py` ([DATA_CONTRACT.md §12](../DATA_CONTRACT.md)).
- Adding a new signal is purely additive: new analyzer, new `subscribe` call, weighted entry in `weights.json`. No adapter touch.

### Negative
- Strict 5s tick latency depends on each analyzer's `on_event` returning in ≤50 ms ([DATA_CONTRACT.md §8.1](../DATA_CONTRACT.md)). A misbehaving analyzer can stall the bus. Mitigation: 50 ms contract rule + `AnalyzerTimeoutError` drop-on-miss logic.
- In a single-process deployment, GIL contention is real for CPU-heavy analyzers (vision, Whisper). Mitigation: heavy analyzers run in `asyncio` worker pools via `run_in_executor`; Whisper itself runs behind a separate process or vendor API call.
- The Redis upgrade is "designed-in but not deployed" for v1; reviewers may view this as vaporware. Mitigation: compute-budget doc [../PERFORMANCE.md](../PERFORMANCE.md) includes the exact Redis-channel design + a benchmark from the moment we deploy cross-process (target v1.1).

## Validation

- `tests/test_bus.py` confirms FIFO ordering per source, dedupe by `(source, sequence)`, and broadcast to multiple subscribers.
- `tests/test_e2e_mock.py` runs the full pipeline through the bus in single-process mode and asserts the 3 reference scenario verdicts match expected outputs ([MOCK_DATA_FORMAT.md](../MOCK_DATA_FORMAT.md)).

## Classification

- **Type:** Architectural / spine pattern
- **Cost of reversal:** High (touches every adapter and every analyzer). Decision DOC'd before code freeze to keep this cost off the table later.
- **Risk if wrong:** Medium. If we ever needed streaming-event at 100k events/sec (we don't — interview events per session are <10k), we'd swap to Kafka with the same `EventBus` interface.
