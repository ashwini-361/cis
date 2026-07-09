# MOCK_DATA_FORMAT.md — Recording JSON Schema & 3 Reference Scenarios

> **Status:** v1.0
> **Cross-refs:** [DATA_CONTRACT.md](./DATA_CONTRACT.md) · [ARCHITECTURE.md](./ARCHITECTURE.md) · [SIGNALS.md](./SIGNALS.md) · [PLATFORM_INTEGRATION.md](./PLATFORM_INTEGRATION.md) · [ACCURACY_METRICS.md](./ACCURACY_METRICS.md)
> **Purpose:** Defines the JSON format of recorded meetings that the `MockAdapter` replays, provides three reference scenarios that drive analyzers and the fusion loop deterministically in tests and the demo video, and lays out the data-labelling format used by `tune.py`.

---

## 0. Mock Streams as First-Class Pipeline Inputs

Mock streams are NOT a test-only artifact — they DO dual duty:

1. **Test fixtures** for the contract tests in [DATA_CONTRACT.md](./DATA_CONTRACT.md) §12 and the unit tests in [ROADMAP.md](./ROADMAP.md) Phase 6.
2. **Demo-video source** for the reproducible edge cases the PDF p3 requires us to demonstrate handling: "incorrect names / missing information / ambiguous situations" — see [APPROACH.md](./APPROACH.md) §7.

The Mock adapter replays a JSON file with `_wallclock_offset_ms = 0` (start immediately) and `–realtime` mode (each event fires at its `ts` relative to session start). It DOES NOT run faster than real time by design — keeps the demo video truthful.

---

## 1. Top-Level Recording JSON Schema

```json
{
  "$schema": "../schemas/recording.schema.json",
  "version": "1.0.0",
  "scenario_id": "happy_path",
  "platform": "mock",
  "session": {                       // SessionEnvelope — see DATA_CONTRACT.md §7
    "session_id": "mock-sess-001",
    "platform": "mock",
    "start_wall_clock": "2026-07-09T09:30:00Z",
    "expected_duration_min": 30,
    "expected_participants": ["P1", "P2", "P3"],
    "ground_truth_candidate_id": "P1",
    "notes": "Happy-path scenario: email match + transcript Q&A pattern."
  },
  "metadata": {
    "candidate": {
      "name": "Ashwini Kumar",
      "email": "ashwini.kumar@gmail.com"
    },
    "interviewers": [
      { "name": "Priya Sharma", "email": "priya@acme.corp" }
    ],
    "schedule": {
      "start_wall_clock": "2026-07-09T09:30:00Z",
      "expected_duration_min": 30,
      "calendar_invite_id": "evt_mock_1"
    }
  },
  "participants": [
    {
      "participant_id": "P1",
      "display_name": "Ashwini",
      "email": "ashwini.kumar@gmail.com",
      "device_name": null,
      "join_order": 1,
      "join_ts": 1.1,
      "leave_ts": 1800.0
    },
    {
      "participant_id": "P2",
      "display_name": "MacBook Pro",
      "email": null,
      "device_name": "MacBook Pro",
      "join_order": 2,
      "join_ts": 12.7,
      "leave_ts": 1800.0
    },
    {
      "participant_id": "P3",
      "display_name": "Priya Sharma",
      "email": "priya@acme.corp",
      "device_name": null,
      "join_order": 3,
      "join_ts": 30.4,
      "leave_ts": 1800.0
    }
  ],
  "events": [
    // list of Events — see §2 event schema below
  ],
  "transcript_segments": [
    // list of transcript segments — see §3 below
  ],
  "expected_output": {
    "decision_ts": 240.0,
    "is_decision": true,
    "candidate_id": "P1",
    "candidate_name": "Ashwini",
    "min_confidence_at_decision": 0.85,
    "max_confidence_runner_up": 0.45,
    "reasons_includes_any_of": [
      "Email matched calendar metadata",
      "Display name similarity",
      "Answered"
    ]
  }
}
```

### 1.1 Field-level semantics

| Field | Type | Required | Notes |
|---|---|---|---|
| `version` | string semver | yes | Recording format version. v1.0 frozen. |
| `scenario_id` | string slug | yes | Stays stable across versions. Used in test names. |
| `platform` | `"mock"` | yes | Always mock; real-platform recordings are not in this format. |
| `session` | object | yes | Maps 1:1 to `SessionEnvelope` in [DATA_CONTRACT.md](./DATA_CONTRACT.md) §7. |
| `metadata.candidate` | { name, email } | yes | Drives `METADATA_CANDIDATE` event + the analyzer-side email/name source. |
| `metadata.interviewers[]` | { name, email }[] | yes | Drives `METADATA_INTERVIEWERS`. ≥1 interviewer for a valid interview. |
| `participants[]` | array | yes | All participants including the candidate and interviewers. May include observers. |
| `participants[].join_order` | int ≥1 unique | yes | 1 = first joiner in the session, used by join_order analyzer. |
| `participants[].join_ts` / `leave_ts` | float sec | yes | Meeting seconds relative to session start. |
| `events[]` | event list | yes | Ordered by `envelope.sequence`. Discussed in §2. |
| `transcript_segments[]` | segment list | optional | Convenience layer; the Mock adapter emits each segment as a `TRANSCRIPT_SEGMENT` event automatically (so you don't have to write them as raw events AND segments both). |
| `expected_output` | object | yes | What the fusion should produce. Used by contract tests for assertion. |

### 1.2 `expected_output` field semantics

| Field | Type | Purpose |
|---|---|---|
| `decision_ts` | float sec | Earliest tick where `is_decision=true` is acceptable. Test asserts verdict at this tick is decidable. |
| `is_decision` | bool | Final verdict state at session end. Test asserts verdict at session end matches. |
| `candidate_id` | str \| null | Ground truth; test asserts verdict matches. |
| `candidate_name` | str \| null | For human-readable assertions. |
| `min_confidence_at_decision` | float | Test asserts `verdict.confidence >= min_confidence_at_decision` at `decision_ts`. |
| `max_confidence_runner_up` | float | Test asserts `verdict.runner_up_confidence <= max_confidence_runner_up` at session end. |
| `reasons_includes_any_of` | string[] | Test asserts at least one of these phrases appears (substring match) in `verdict.reasons`. |

---

## 2. Event Array Schema

Each entry in `events` is an `Event` per [DATA_CONTRACT.md](./DATA_CONTRACT.md) §2, but in mock-stream JSON we use a **shorthand** to avoid repeating the envelope:

```json
{
  "type": "PARTICIPANT_JOINED",
  "ts": 1.1,                                    // overrides envelope.ts
  "payload": {
    "participant_id": "P1",
    "display_name": "Ashwini",
    "email": "ashwini.kumar@gmail.com",
    "device_name": null,
    "join_order": 1
  }
}
```

The Mock adapter expands each shorthand into a full `Event` with envelope:

```python
class MockAdapter(IngestAdapter):
    def __init__(self, recording_path: Path):
        self.rec = json.loads(recording_path.read_text())
        self.source = f"mock.{self.rec['scenario_id']}"

    async def stream_events(self) -> AsyncIterator[Event]:
        seq = 0
        for entry in self.rec["events"]:
            yield Event(
                type=EventType(entry["type"]),
                envelope=EventEnvelope(
                    session_id=self.rec["session"]["session_id"],
                    ts=entry["ts"],
                    wall_clock=datetime.utcnow().isoformat() + "Z",
                    platform="mock",
                    source=self.source,
                    sequence=seq,
                ),
                payload=entry["payload"],
            )
            seq += 1
        # auto-emit SESSION_END
        yield Event(type=EventType.SESSION_END, ...)
```

`MockAdapter` also auto-emits `SESSION_START` at `ts=0`, and `METADATA_*` events from the `metadata` block. Authors don't write those by hand.

### 2.1 Allowed event types in mock recordings

| `type` | Required payload fields |
|---|---|
| `PARTICIPANT_JOINED` | `participant_id`, `display_name`, `join_ts`, `join_order`; `email?`, `device_name?` |
| `PARTICIPANT_LEFT` | `participant_id`, `leave_ts` |
| `PARTICIPANT_RENAMED` | `participant_id`, `old_name`, `new_name` |
| `WEBCAM_ON` / `OFF` | `participant_id` |
| `SCREEN_SHARE_START` / `STOP` | `participant_id`, optional `content_label` |
| `AUDIO_ACTIVE` / `SILENT` | `participant_id`, `duration_sec` |
| `VIDEO_FRAME` | (NOT in mock recordings — vision analyzer runs in real-stream test only) |
| `SCREEN_FRAME` | (NOT in mock recordings; screen-content analyzer uses label-only) |
| `TRANSCRIPT_SEGMENT` | (See §3 below — usually emitted via the convenience `transcript_segments` block) |

### 2.2 Forbidden event types in mock recordings

`METADATA_CANDIDATE`, `METADATA_SCHEDULE`, `METADATA_INTERVIEWERS`, `SESSION_START`, `SESSION_END` — all are synthesized by `MockAdapter` from the recording's top-level `metadata` + `session` blocks.

### 2.3.idempotency guarantee

`MockAdapter` deterministically pulls `seq` from the array index. Re-running the same recording yields identical `envelope.sequence` values — the contract test in [DATA_CONTRACT.md](./DATA_CONTRACT.md) §12.4 (idempotency) is checkable.

---

## 3. Transcript Segments

Transcript segments are split out from the main `events[]` for ergonomics. Each segment has the shape:

```json
{
  "participant_id": "P3",
  "text": "Tell me about your most recent project.",
  "start_sec": 65.2,
  "end_sec":   68.1
}
```

`MockAdapter` synthesizes one `TRANSCRIPT_SEGMENT` Event per entry in `transcript_segments` (with `type=TRANSCRIPT_SEGMENT`, `ts=start_sec`, payload = the entry). Segment word-level payloads (`words[]` with token timings) are NOT generated for mock recordings to keep files readable — Whisper-style accuracy is available only in real-platform tests.

### 3.1 Segments are ordered by `start_sec`

Test assertions can rely on monotonic `start_sec`. The Mock adapter emits them in array order, so authors MUST keep segments time-sorted.

### 3.2 Empty gaps are intentional silence

The Mock adapter does NOT emit `AUDIO_SILENT` events for gaps — silence is implicit between consecutive segments separated by >2s. The `speaking_pattern` analyzer treats ≥1.5s gaps as turn boundaries.

---

## 4. Reference Scenario 1: `happy_path`

**File**: `data/recordings/happy_path.json`
**Purpose**: email + name match, candidate answers clearly to interviewer's questions.
**Ground truth**: `P1` = candidate.

### 4.1 Participants
- P1 "Ashwini" (Ashwini Kumar, ashwini.kumar@gmail.com) — join order 1
- P2 "MacBook Pro" (no email — guest) — join order 2
- P3 "Priya Sharma" (interviewer) — join order 3

### 4.2 Events (selected)

```json
[
  { "type": "PARTICIPANT_JOINED", "ts":   1.1, "payload": { "participant_id": "P1", "display_name": "Ashwini", "email": "ashwini.kumar@gmail.com", "device_name": null, "join_order": 1 } },
  { "type": "WEBCAM_ON",           "ts":   2.5, "payload": { "participant_id": "P1" } },
  { "type": "PARTICIPANT_JOINED", "ts":  12.7, "payload": { "participant_id": "P2", "display_name": "MacBook Pro", "email": null, "device_name": "MacBook Pro", "join_order": 2 } },
  { "type": "PARTICIPANT_JOINED", "ts":  30.4, "payload": { "participant_id": "P3", "display_name": "Priya Sharma", "email": "priya@acme.corp", "device_name": null, "join_order": 3 } },
  { "type": "WEBCAM_ON",           "ts":  30.5, "payload": { "participant_id": "P3" } },
  { "type": "SCREEN_SHARE_START", "ts": 120.0, "payload": { "participant_id": "P1", "content_label": "code editor / IDE" } },
  { "type": "SCREEN_SHARE_STOP",  "ts": 240.0, "payload": { "participant_id": "P1" } },
  { "type": "PARTICIPANT_LEFT",   "ts":1800.0, "payload": { "participant_id": "P1", "leave_ts": 1800.0 } },
  { "type": "PARTICIPANT_LEFT",   "ts":1800.0, "payload": { "participant_id": "P2", "leave_ts": 1800.0 } },
  { "type": "PARTICIPANT_LEFT",   "ts":1800.0, "payload": { "participant_id": "P3", "leave_ts": 1800.0 } }
]
```

### 4.3 Transcript segments

```json
[
  { "participant_id": "P3", "text": "Hi Ashwini, thanks for jumping on. Tell me about yourself.", "start_sec":  65.0, "end_sec":  70.0 },
  { "participant_id": "P1", "text": "Sure. I'm a backend engineer with three years of experience, mostly in async Python...", "start_sec":  71.0, "end_sec":  90.0 },
  { "participant_id": "P3", "text": "Great. Why this company?", "start_sec":  91.5, "end_sec":  93.0 },
  { "participant_id": "P1", "text": "I'm drawn to the focus on fraud detection in real-time... ", "start_sec":  93.5, "end_sec": 110.0 },
  { "participant_id": "P3", "text": "Walk me through your most recent project.", "start_sec": 120.5, "end_sec": 124.0 },
  { "participant_id": "P1", "text": "I built Astra, a document search pipeline...", "start_sec": 125.0, "end_sec": 175.0 },
  { "participant_id": "P3", "text": "What scale did you test that at?", "start_sec": 180.0, "end_sec": 182.0 },
  { "participant_id": "P1", "text": "About 50k documents per query batch, p95 latency under 400ms.", "start_sec": 183.0, "end_sec": 200.0 },
  { "participant_id": "P3", "text": "Excellent. Any questions for me?", "start_sec": 320.0, "end_sec": 322.5 },
  { "participant_id": "P1", "text": "Yes — what's the on-call rotation look like?", "start_sec": 325.0, "end_sec": 330.0 },
  { "participant_id": "P3", "text": "One week every six weeks.", "start_sec": 332.0, "end_sec": 335.0 }
]
```

### 4.4 Expected output

```json
"expected_output": {
  "decision_ts": 200.0,
  "is_decision": true,
  "candidate_id": "P1",
  "candidate_name": "Ashwini",
  "min_confidence_at_decision": 0.85,
  "max_confidence_runner_up": 0.45,
  "reasons_includes_any_of": [
    "Email matched calendar metadata",
    "Display name similarity",
    "Answered"
  ]
}
```

---

## 5. Reference Scenario 2: `renamed_candidate`

**File**: `data/recordings/renamed_candidate.json`
**Purpose**: PDF p3 case "incorrect names" + PDF p1 example "candidate changes their display name".
**Ground truth**: P1 = candidate despite display_name mid-meeting switching to "MacBook".

### 5.1 Participants
- P1 starts as "Ashwini Kumar" → at t=200s renamed to "MacBook"
- P2 joins silently as interviewer "Priya Sharma"
- P3 joins as observer "Alice" with mic off

### 5.2 Key events

```json
[
  { "type": "PARTICIPANT_JOINED", "ts": 1.1,  "payload": { "participant_id": "P1", "display_name": "Ashwini Kumar", "email": "ashwini.kumar@gmail.com", "join_order": 1 } },
  { "type": "WEBCAM_ON",           "ts": 2.0,  "payload": { "participant_id": "P1" } },
  { "type": "PARTICIPANT_JOINED", "ts": 30.0, "payload": { "participant_id": "P2", "display_name": "Priya Sharma", "email": "priya@acme.corp", "join_order": 2 } },
  { "type": "PARTICIPANT_JOINED", "ts": 95.0, "payload": { "participant_id": "P3", "display_name": "Alice", "email": null, "join_order": 3 } },
  { "type": "PARTICIPANT_RENAMED", "ts": 200.0, "payload": { "participant_id": "P1", "old_name": "Ashwini Kumar", "new_name": "MacBook" } }
]
```

### 5.3 Transcript segments (continued)

The transcript segments continue to clearly follow interviewer → candidate → interviewer → candidate pattern with P1 answering all P2 questions. P3 (Alice) never speaks.

### 5.4 Expected output

```json
"expected_output": {
  "decision_ts": 350.0,
  "is_decision": true,
  "candidate_id": "P1",
  "candidate_name": "MacBook",
  "min_confidence_at_decision": 0.75,
  "max_confidence_runner_up": 0.40,
  "reasons_includes_any_of": [
    "Email matched calendar metadata",
    "Answered",
    "Speaking pattern"
  ]
}
```

Note: min_confidence at decision DROPS from 0.85 (happy_path) to 0.75 because the name-similarity signal that was at 1.00 drops to 0.10 on rename. The email and transcript-role signals continue to dominate. **Decision is delayed** to t=350s vs happy_path's t=200s.

---

## 6. Reference Scenario 3: `similar_participants`

**File**: `data/recordings/similar_participants.json`
**Purpose**: PDF p1 case "two similar participants" — name signals can't distinguish, only behavioral signals can.
**Ground truth**: P1 = candidate; P2 = candidate's brother with same name (homograph scenario) AND also answering some questions incorrectly.

### 6.1 Participants
- P1 joins as "Ashwini Kumar"
- P2 joins as "Ashwini Kumar" (homograph — same name, different person)
- P3 joins as interviewer

### 6.2 Key events (abbreviated)

```json
[
  { "type": "PARTICIPANT_JOINED", "ts":  1.1, "payload": { "participant_id": "P1", "display_name": "Ashwini Kumar", "email": null, "join_order": 1 } },
  { "type": "PARTICIPANT_JOINED", "ts":  3.0, "payload": { "participant_id": "P2", "display_name": "Ashwini Kumar", "email": null, "join_order": 2 } },
  { "type": "PARTICIPANT_JOINED", "ts": 30.0, "payload": { "participant_id": "P3", "display_name": "Priya Sharma", "email": "priya@acme.corp", "join_order": 3 } }
]
```

No emails (neither P1 nor P2 exposed email to Zoom platform — they joined as guests).

### 6.3 Transcript segments differentiation

Critical: the interviewer addresses the actual candidate by participant_id (not by name — the LLM doesn't depend on names):

```json
[
  { "participant_id": "P3", "text": "Welcome both! Let's get started.", "start_sec": 65.0, "end_sec": 68.0 },
  { "participant_id": "P3", "text": "P1, can you walk me through your project?", "start_sec": 70.0, "end_sec": 73.0 },
  { "participant_id": "P1", "text": "I built Astra, a document index. Latency p95 under 400ms on a 50k-batch corpus.", "start_sec": 75.0, "end_sec": 95.0 },
  { "participant_id": "P3", "text": "P2, I'll come to you in a moment.",
                                            "start_sec": 100.0, "end_sec": 102.0 },
  { "participant_id": "P2", "text": "Sorry, what's Astra?", "start_sec": 110.0, "end_sec": 113.0 }
]
```

Note: P1 is asked questions and answers confidently; P2 is referenced once and asks a confused followup. The LLM transcript-role classifier sees this and produces scores:

- `P1: candidate (0.92)`
- `P2: observer (0.70)` (anti-evidence toward candidate hypothesis)

### 6.4 Expected output

```json
"expected_output": {
  "decision_ts": 250.0,
  "is_decision": true,
  "candidate_id": "P1",
  "candidate_name": "Ashwini Kumar",
  "min_confidence_at_decision": 0.65,    // no email, no name distinguisher; only behavioral signals
  "max_confidence_runner_up": 0.30,
  "reasons_includes_any_of": [
    "Answered",
    "Speaking pattern",
    "Transcript role"
  ]
}
```

The lower min_confidence_at_decision (0.65) reflects the harder case. The `not_deciding_reason` should show "still deciding" until ~ t=250s when the LLM has enough transcript windows.

---

## 7. Reference Scenario Out-of-Scope (limitations documented in [EVALUATION.md](./EVALUATION.md))

| Scenario | Why not in v1.0 |
|---|---|
| Deepfake injection mid-call | Requires vision analyzer enabled (default weight 0.00). Tested separately in [ACCURACY_METRICS.md](./ACCURACY_METRICS.md) §7. |
| 5 silent observers joining | A `silent_observers.json` recording is generated but is NOT in the contract test set; it's available for ad-hoc testing. |
| Multi-language interview | Out of scope for v1 — LLM prompts English-only. See [ARCHITECTURE.md](./ARCHITECTURE.md) §9. |
| 100-participant meeting | Performance test — see [ACCURACY_METRICS.md](./ACCURACY_METRICS.md) §8. Not a behavioural assertion test. |

---

## 8. Recording Provenance & File Layout

```
data/recordings/
├── happy_path.json              # ground truth = P1
├── renamed_candidate.json       # ground truth = P1 (renamed)
├── similar_participants.json    # ground truth = P1
├── silent_observers.json        # ad-hoc
├── many_participants.json       # perf only, ground truth = P1
└── ../recordings.schema.json    # JSON Schema doc for validation
```

Each recording file is self-contained. The Mock adapter loads scenarios by name (`MockAdapter("happy_path")` resolves to `data/recordings/happy_path.json`).

### 8.1 JSON validation

Recordings are validated against `data/recordings.schema.json` (the JSON Schema for this format, generated from [DATA_CONTRACT.md](./DATA_CONTRACT.md)) at Mock adapter init. Tests fail fast on schema violation.

---

## 9. Labelling Format for `tune.py`

For `tune.py` to recalibrate weights, we need labeled past sessions. Each recording already contains `ground_truth_candidate_id` in `session.ground_truth_candidate_id`. `tune.py` reads the entire `data/recordings/` directory recursively and:

1. Runs fusion with current weights on each recording.
2. Records: (a) final `candidate_id` prediction vs. ground truth, (b) `decision_ts` time-to-decision, (c) margin-over-runner-up at decision.
3. Upweights features that fire early + accurately for true candidates; downweights features with high variance.
4. Writes a new `weights.json` to `data/weights/weights.v{N+1}.json`.

Requires **≥20 labeled recordings** for a meaningful update. Until that threshold, `tune.py` runs as a warmup exercise only — its recommended weights are NOT loaded into production.

Detailed tuning algorithm in [ACCURACY_METRICS.md](./ACCURACY_METRICS.md) §6.

---

## 10. Recording Authoring Style Guide

When adding new scenarios:

1. **Start from a real interview script** — don't invent artificial-sounding replies. Use interview practice sites for inspiration (e.g. "Tell me about a time you disagreed with your manager").
2. **Always include `expected_output`** — every recording must be assertable.
3. **Vary participant IDs by scenario** — never reuse `P1` across scenarios for different ground-truth roles. This catches accidental state leakage in tests.
4. **Keep `join_order` realistic** — most interviews have candidate join first or interviewer join first (rare 1-2 min early). Avoid join-order edge cases unless explicitly testing that signal.
5. **Transcript timestamps SHOULD align with event timestamps** — e.g. `SCREEN_SHARE_START.ts=120` should be near a `TRANSCRIPT_SEGMENT.start_sec` where the candidate starts describing a screen share. Discrepancies flagged in test output.
6. **≤5 minutes each** — long recordings are unwieldy for tests; the demo can loop them.

---

## 11. Change Log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-07-09 | Initial recording format + 3 reference scenarios. |

---

> **Next:** Read [ACCURACY_METRICS.md](./ACCURACY_METRICS.md) for labelled-data format, metric formulas, and `tune.py` algorithm; then [EVALUATION.md](./EVALUATION.md) for the test methodology writeup (PDF Deliverable #5).
