# DATA_CONTRACT.md — Wire-Level Schemas & Analyzer Interface

> **Status:** v1.0
> **Cross-refs:** [APPROACH.md](./APPROACH.md) · [SIGNALS.md](./SIGNALS.md) · [ARCHITECTURE.md](./ARCHITECTURE.md) · [MOCK_DATA_FORMAT.md](./MOCK_DATA_FORMAT.md)
> **Purpose:** Locks the wire-level types every analyzer, the fusion engine, the realtime loop, the explainer, and the dashboard speaks. Once this contract is frozen, analyzers can be built in any order by any contributor without coordination beyond this file.

---

## 0. Naming Conventions

- All field names use **`snake_case`**.
- All timestamps are **relative meeting seconds** (`float`, monotonic), not wall-clock. Wall-clock is added in `Event.envelope` only for ingest logging.
- All IDs are **strings**, even numeric ones — easier to swizzle across platforms (Zoom uses long ints, Meet uses opaque tokens).
- All booleans are explicit JSON `true`/`false`, never 0/1.
- All scores are `float` ∈ `[0.0, 1.0]`. Out-of-range values are an analyzer bug; the fusion engine clamps anyway.
- All weights are `float` ∈ `[0.0, 1.0]` and load-bearing weights sum to ≤ 1.0 across analyzers (**soft** constraint, NOT enforced — see §7).

---

## 1. Top-Level Schema Map

```
┌──────────────────────────────────────────────────────────────┐
│ EVENTS (ingest)        →  Event                                │
│ EVIDENCE (analyzers)   →  Evidence                             │
│ STATE   (live)         →  ParticipantState                     │
│ VERDICT (output)       →  Verdict                             │
│ SESSION (envelope)     →  SessionEnvelope                      │
│ WEIGHTS (tuning)       →  WeightTable                          │
└──────────────────────────────────────────────────────────────┘
```

All six are Pydantic `BaseModel`s as defined below. Every analyzer imports `Evidence` from `app/schema.py` and returns `list[Evidence]`. Nothing else.

---

## 2. `Event` — The Ingest Contract

Events flow from the platform adapter (Zoom OAuth, Meet Recording API, mock stream) into the event bus. Every event carries an envelope.

### 2.1 Pydantic schema

```python
# app/schema.py
from pydantic import BaseModel, Field
from enum import Enum
from typing import Literal, Any

class EventType(str, Enum):
    # Participant lifecycle
    PARTICIPANT_JOINED      = "participant.joined"
    PARTICIPANT_LEFT        = "participant.left"
    PARTICIPANT_RENAMED     = "participant.renamed"
    # Media state
    WEBCAM_ON               = "webcam.on"
    WEBCAM_OFF              = "webcam.off"
    SCREEN_SHARE_START      = "screen_share.start"
    SCREEN_SHARE_STOP       = "screen_share.stop"
    AUDIO_ACTIVE            = "audio.active"       # VAD-positive window
    AUDIO_SILENT            = "audio.silent"
    # Content
    AUDIO_CHUNK             = "audio.chunk"        # raw/encoded bytes for one participant
    VIDEO_FRAME             = "video.frame"        # one webcam frame
    SCREEN_FRAME            = "screen.frame"
    TRANSCRIPT_SEGMENT      = "transcript.segment" # speaker-attributed
    # External metadata (provided once at session start)
    METADATA_CANDIDATE      = "metadata.candidate" # candidate_name + candidate_email
    METADATA_SCHEDULE       = "metadata.schedule"  # interview schedule
    METADATA_INTERVIEWERS   = "metadata.interviewers"
    # Session lifecycle
    SESSION_START           = "session.start"
    SESSION_END             = "session.end"

class EventEnvelope(BaseModel):
    session_id:    str
    ts:            float           # meeting seconds
    wall_clock:    str             # ISO 8601 UTC, for ingest logging only
    platform:      Literal["zoom", "meet", "teams", "mock"]
    source:        str             # adapter id ("zoom.oauth.1", "mock.replay")
    sequence:      int             # monotonic per-source counter (for dedupe)

class Event(BaseModel):
    type:           EventType
    envelope:       EventEnvelope
    payload:        dict[str, Any] # type-specific shape — see 2.2 below
```

### 2.2 Payload shapes (per `EventType`)

| `EventType` | Payload |
|---|---|
| `PARTICIPANT_JOINED` | `{ participant_id, display_name, email?, device_name?, join_order }` |
| `PARTICIPANT_LEFT` | `{ participant_id, leave_ts }` |
| `PARTICIPANT_RENAMED` | `{ participant_id, old_name, new_name }` |
| `WEBCAM_ON`/`OFF` | `{ participant_id }` |
| `SCREEN_SHARE_START`/`STOP` | `{ participant_id }` |
| `AUDIO_ACTIVE`/`SILENT` | `{ participant_id, duration_sec }` |
| `AUDIO_CHUNK` | `{ participant_id, format: "wav"\|"opus", sample_rate, channels, base64_bytes, start_sec, end_sec }` |
| `VIDEO_FRAME` | `{ participant_id, format: "jpeg", width, height, base64_bytes }` |
| `SCREEN_FRAME` | `{ participant_id?, format: "jpeg", width, height, base64_bytes }` (note: screen-share may not be attributable to a participant on all platforms — `participant_id?` may be `None`) |
| `TRANSCRIPT_SEGMENT` | `{ participant_id, text, start_sec, end_sec, words?: [{token, start_sec, end_sec, confidence}] }` |
| `METADATA_CANDIDATE` | `{ name, email, calendar_invite_id? }` |
| `METADATA_SCHEDULE` | `{ start_wall_clock, expected_duration_min, interviewer_names: [str] }` |
| `METADATA_INTERVIEWERS` | `{ names: [str], emails?: [str] }` |
| `SESSION_START` | `{ expected_participants: [str] }` |
| `SESSION_END` | `{ reason: "normal"\|"timeout"\|"error" }` |

### 2.3 Event ordering & dedupe guarantee

- The event bus MUST guarantee **per-source FIFO** ordering on `envelope.sequence`.
- A second arrival of an event with the same `(source, sequence)` is a duplicate and MUST be dropped by the bus.
- Across sources, ordering is **not** guaranteed — analyzers must be order-tolerant (idempotent evidence emission; see §4.5).
- Mock streams emit `sequence` strictly monotonic per source.

---

## 3. `Evidence` — The Analyzer Output Contract

Every analyzer module **only** produces `Evidence` records. Nothing else.

### 3.1 Pydantic schema

```python
class Evidence(BaseModel):
    # --- identity ---
    session_id:        str
    participant_id:    str
    feature:           str             # e.g. "name_similarity", "email_match", "transcript_role"
    source:            str             # analyzer id, e.g. "transcript_role_analyzer"

    # --- scoring ---
    score:             float = Field(ge=0.0, le=1.0, description="Signal-strength in [0,1]")
    weight:            float = Field(ge=0.0, le=1.0, description="Default weight, overridable by weights.json")

    # --- provenance & explainability ---
    reason:            str             # human-readable; rendered in Verdict.reasons
    raw_payload:        dict[str, Any] = Field(default_factory=dict, exclude=True) # optional debug data
    ts:                float           # meeting seconds when evidence was generated

    # --- lifecycle ---
    expires_at:        float | None = None  # meeting seconds when this evidence should be discarded; None = sticky
    supersedes:        str | None = None    # feature key this evidence replaces (e.g. new name similarity supersedes old)
```

### 3.2 Field semantics

| Field | Type | Description |
|---|---|---|
| `session_id` | `str` | Session this evidence belongs to. |
| `participant_id` | `str` | The participant this evidence contributes to. |
| `feature` | `str` | Short snake_case identifier. Canonical list in [SIGNALS.md](./SIGNALS.md) §1. Examples: `"name_similarity"`, `"email_match"`, `"transcript_role"`, `"speaking_pattern"`, `"join_order"`, `"webcam_usage"`, `"face_consistency"`, `"screen_share_content"`, `"device_name"`, `"speaking_ratio"`. |
| `source` | `str` | Analyzer module id. Used by [EVALUATION.md](./EVALUATION.md) to attribute verdicts to specific modules. |
| `score` | `float ∈ [0,1]` | How strongly this evidence supports this participant being the candidate on THIS signal. 0 = no support, 1 = maximal. Analyzers must document their scoring curve in [SIGNALS.md](./SIGNALS.md). |
| `weight` | `float ∈ [0,1]` | Default weight. Loaded from `weights.json` at analyzer init; can be 0 (signal disabled). The fusion engine reads `evidence.weight` — analyzers should not override their loaded weight at emit time. |
| `reason` | `str` | Human-readable explanation. Renders verbatim into the verdict reason panel. Grammar guidance: start with a verb in past tense ("matched", "answered", "joined"), include the cited input. |
| `raw_payload` | `dict` (excluded from serialization) | Optional debug-only payload. NOT serialized into Redis or Postgres. Use for in-process debugging only. |
| `ts` | `float` | Meeting seconds when the analyzer decided to emit this evidence. Drives temporal decay in fusion. |
| `expires_at` | `float \| None` | Meeting seconds when this evidence is stale and should be discarded by fusion. `None` means sticky (never expires) — used for name/email/static metadata. Use a value for evidence that decays (e.g. transcript-role evidence from 10 minutes ago is less decisive than current evidence). |
| `supersedes` | `str \| None` | If a new evidence record supersedes an older one with the same feature (e.g. name_similarity recomputed after rename), set this to the feature key to remove the old one. The evidence store deletes the superseded record. |

### 3.3 Worked examples

#### Email match (sticky, full evidence)
```python
Evidence(
    session_id="sess_1",
    participant_id="P1",
    feature="email_match",
    source="metadata_analyzer",
    score=1.0,
    weight=0.30,
    reason="Participant's email ashwini@gmail.com matched calendar metadata exactly",
    ts=0.2,
    expires_at=None,                 # sticky
    supersedes=None,
)
```

#### Transcript role (decaying, 10-min half-life)
```python
Evidence(
    session_id="sess_1",
    participant_id="P2",
    feature="transcript_role",
    source="transcript_role_analyzer",
    score=0.92,
    weight=0.25,
    reason="Answered 7 of last 8 interviewer questions in Q&A turns",
    ts=143.2,
    expires_at=143.2 + 600,          # 10-minute half-life
    supersedes="transcript_role",    # replace older transcript-role evidence for P2
)
```

#### Webcam ON ongoing
```python
Evidence(
    session_id="sess_1",
    participant_id="P1",
    feature="webcam_usage",
    source="webcam_analyzer",
    score=1.0,
    weight=0.05,
    reason="Webcam has been on for 87% of the meeting",
    ts=520.1,
    expires_at=520.1 + 60,           # reassess every 60 s — webcam_analyzer re-emits on tick
    supersedes="webcam_usage",
)
```

#### Face swap (anti-evidence — score low on face_consistency)
```python
Evidence(
    session_id="sess_1",
    participant_id="P3",
    feature="face_consistency",
    source="vision_analyzer",
    score=0.0,                       # 0 = this participant is NOT a continuous single person
    weight=0.00,                     # disabled by default per SIGNALS.md #8
    reason="Face embedding changed abruptly at t=134s — possible face swap",
    ts=140.0,
    expires_at=140.0 + 300,
    supersedes="face_consistency",
)
```

### 3.4 Hard analyzer rules (enforced by `tests/test_contract.py`)

1. Every emitted `Evidence` MUST validate against the Pydantic schema above.
2. `score` MUST be in `[0.0, 1.0]`. Out-of-range → exception (analyzer bug).
3. `weight` MUST equal the value loaded from `weights.json` for that feature at init time. The fusion engine does NOT use analyzer-supplied weights; it uses the weights table — but we set `evidence.weight` on emit for logging/explainability only.
4. `reason` MUST be non-empty and ≤ 240 chars (dashboard wraps).
5. `ts` MUST be ≥ the last `ts` emitted by the same analyzer for the same participant (monotonic per `(source, participant_id)`).
6. `expires_at` if set MUST be `> ts`. Sticky (`None`) allowed only for analyzers explicitly listed in SIGNALS.md §1.
7. `supersedes` if set MUST be a `feature` key the same analyzer is allowed to own.
8. `raw_payload` MUST NOT be serialized into Redis/Postgres — the analyzer must drop it before persistence (Pydantic's `exclude=True` on the field).
9. Analyzers MUST be deterministic for a given input sequence (same events in → same evidence out). Random sources must be seeded.
10. Analyzers MUST be idempotent: re-running an event with the same sequence produces no new evidence.

---

## 4. `ParticipantState` — The Live State Contract

Maintained in Redis, keyed by `(session_id, participant_id)`. One per participant per session. Recomputed every 5s by the realtime ticker.

### 4.1 Pydantic schema

```python
class ParticipantState(BaseModel):
    session_id:        str
    participant_id:    str
    display_name:      str
    email:             str | None = None
    device_name:       str | None = None
    join_ts:           float
    is_present:        bool = True

    # --- fusion outputs ---
    confidence:        float = 0.0                       # normalized Σ(weight×score) after decay
    raw_evidence:      list[Evidence] = []               # current evidence, sorted desc by contribution
    last_recompute_ts: float = 0.0

    # --- provenance ---
    analyzer_count:    int = 0                           # how many analyzers currently hold evidence for this participant
    total_evidence:    int = 0                           # len(raw_evidence)
```

### 4.2 Lifecycle

- **Created** on `PARTICIPANT_JOINED`.
- **Updated** every 5s by `realtime/updater.py` after `fuse()` runs.
- **Marked `is_present=False`** on `PARTICIPANT_LEFT` (NOT deleted — needed for historical verdict audit).
- **Deleted** from Redis on `SESSION_END` after a 24h TTL (used for session-history audit).
- **Persisted** to PostgreSQL after each recompute (full history → enables the confidence-curve dashboard chart).

### 4.3 Confidence formula (default v1 fusion)

For participant `p` at meeting time `t`:

```
confidence(p, t) = Σ_e  ( e.weight × e.score × decay(e, t) × presence(p, t) )
                  / Σ_e  ( e.weight × decay(e, t) × presence(p, t) )
```

Where:
- `decay(e, t) = exp(-λ · (t - e.ts))` if `e.expires_at` is set (λ = 1/half_life, default half_life=300s)
- `decay(e, t) = 1.0` if `e.expires_at is None` (sticky)
- `presence(p, t) = 1.0` while `is_present = True`, ramps linearly to 0 over 30s after `PARTICIPANT_LEFT` (lets a suddenly-left candidate's confidence fade rather than zero instantly)
- If `Σ_e ( weight × decay × presence )` < 1e-6, return `confidence = 0.0` (avoid div/0). This is the cold-start state.

### 4.4 Why weighted average and not pure sum

Pure weighted sums cause confidences to drift toward 1.0 as evidence accumulates, even when most signals are weak (94 weak signals each scoring 0.5 in a 0.25-weight signal still grants `0.25 × 0.5 = 0.125` per signal — rapidly saturates). Normalized weighted average bounds `confidence ∈ [0,1]` and lets weak signals appropriately *dilute* strong ones. Reviewers expect this to behave like a probability.

The v2 Bayesian variant lives in `fusion/bayesian.py` and replaces this formula once `tune.py` has at least 20 labeled sessions to estimate priors. Specified in [ACCURACY_METRICS.md](./ACCURACY_METRICS.md) §6.

---

## 5. `Verdict` — The Output Contract

Emitted every 5s by the fusion engine onto the WebSocket bus and persisted to Postgres for the auditable timeline.

### 5.1 Pydantic schema

```python
class Verdict(BaseModel):
    # --- identity ---
    session_id:         str
    ts:                 float                 # meeting seconds
    platform:           str

    # --- decision ---
    candidate_id:       str | None            # None when is_decision=False
    candidate_name:     str | None
    confidence:         float | None          # None when is_decision=False
    runner_up_id:       str | None
    runner_up_confidence: float | None
    margin:             float | None          # confidence - runner_up_confidence, None if is_decision=False

    # --- explainability ---
    reasons:            list[str]             # bullets, ordered desc by contribution
    rejected_hypotheses: list[RejectedHypothesis] = []

    # --- lifecycle flag ---
    is_decision:        bool                  # False = below threshold OR margin too low
    not_deciding_reason: str | None = None    # populated when is_decision=False

    # --- system provenance ---
    analyzer_count:     int
    total_evidence:     int
    engine_version:     str = "v1-weighted"

class RejectedHypothesis(BaseModel):
    participant_id:     str
    display_name:       str
    confidence:         float
    top_negative_reasons: list[str]
```

### 5.2 Decision logic — the threshold + margin gate

```python
def decide(states: list[ParticipantState], t: float) -> Verdict:
    if not states:
        return Verdict(
            session_id=..., ts=t, platform=...,
            candidate_id=None, candidate_name=None, confidence=None,
            runner_up_id=None, runner_up_confidence=None, margin=None,
            reasons=["no participants yet"], is_decision=False,
            not_deciding_reason="no participants", analyzer_count=0, total_evidence=0,
        )

    sorted_states = sorted(states, key=lambda s: s.confidence, reverse=True)
    top, runner = sorted_states[0], sorted_states[1] if len(sorted_states) > 1 else None

    THRESHOLD = 0.55
    MARGIN    = 0.20

    if top.confidence < THRESHOLD:
        return Verdict(
            is_decision=False,
            candidate_id=None, candidate_name=None, confidence=None,
            margin=None,
            not_deciding_reason=f"top confidence {top.confidence:.2f} < threshold {THRESHOLD}",
            reasons=[...],
        )

    if runner is not None and (top.confidence - runner.confidence) < MARGIN:
        return Verdict(
            is_decision=False,
            candidate_id=None, confidence=None,
            margin=top.confidence - runner.confidence,
            not_deciding_reason=f"margin {top.confidence - runner.confidence:.2f} < required {MARGIN}",
            reasons=[...],
        )

    return Verdict(
        is_decision=True,
        candidate_id=top.participant_id,
        candidate_name=top.display_name,
        confidence=top.confidence,
        runner_up_id=runner.participant_id if runner else None,
        runner_up_confidence=runner.confidence if runner else None,
        margin=top.confidence - (runner.confidence if runner else 0),
        reasons=render_reasons(top.raw_evidence),
        rejected_hypotheses=[render_rejected(s) for s in sorted_states[1:3]],
    )
```

Threshold and margin are tunable in `weights.json`. Defaults chosen to balance:

- `THRESHOLD=0.55`: a single strong signal (email=0.30 score=1.0 plus one behavioral=0.25 score=0.85) just barely crosses it; pure single-metadata solutions stay below
- `MARGIN=0.20`: prevents premature lock when two candidates have similar confidence at cold-start

Tuning plan and rationale in [ACCURACY_METRICS.md](./ACCURACY_METRICS.md) §5.

### 5.3 Worked examples

#### Decidable verdict
```json
{
  "session_id": "sess_1",
  "ts": 300.4,
  "platform": "zoom",
  "candidate_id": "P1",
  "candidate_name": "Ashwini",
  "confidence": 0.97,
  "runner_up_id": "P3",
  "runner_up_confidence": 0.45,
  "margin": 0.52,
  "is_decision": true,
  "reasons": [
    "Email matched calendar metadata (+0.300)",
    "Transcript role: answered 8 of 9 interviewer questions (+0.225)",
    "Display name similarity 96% (+0.144)",
    "Speaking pattern matched candidate turn-taking (+0.120)",
    "Webcam active throughout meeting (+0.050)",
    "Screen-shared IDE / resume (+0.045)",
    "Joined first — typical candidate behavior (+0.030)"
  ],
  "rejected_hypotheses": [
    {
      "participant_id": "P3",
      "display_name": "Priya Sharma",
      "confidence": 0.45,
      "top_negative_reasons": [
        "Transcript role strongly indicates interviewer (+0.225 to interviewer-role signal)",
        "Email not provided by platform"
      ]
    },
    {
      "participant_id": "P2",
      "display_name": "MacBook Pro",
      "confidence": 0.10,
      "top_negative_reasons": [
        "Display name similarity 5% (likely device name)",
        "No Q&A participation in transcript",
        "No screen-share activity"
      ]
    }
  ],
  "analyzer_count": 6,
  "total_evidence": 11,
  "engine_version": "v1-weighted"
}
```

#### Not-deciding verdict
```json
{
  "session_id": "sess_1",
  "ts": 12.3,
  "platform": "zoom",
  "candidate_id": null,
  "candidate_name": null,
  "confidence": null,
  "runner_up_id": "P1",
  "runner_up_confidence": 0.42,
  "margin": null,
  "is_decision": false,
  "not_deciding_reason": "top confidence 0.42 < threshold 0.55",
  "reasons": [
    "Top candidate so far: P1 \"Ashwini\" (0.42)",
    "Awaiting transcript role evidence (transcript not yet available)",
    "Awaiting more Q&A turns for behavioral signals"
  ],
  "analyzer_count": 4,
  "total_evidence": 5,
  "engine_version": "v1-weighted"
}
```

### 5.4 What the dashboard renders

On each 5s verdict:
- Top card: `is_decision ? "Candidate: {candidate_name}" : "Still deciding…"`
- Confidence bar: `{confidence}` or "awaiting more evidence"
- Reason panel: bullet list of `reasons[]` (when decidable) or `not_deciding_reason` + `reasons[]` (when not)
- Per-participant mini-cards ranked by confidence, with their `runner_up_confidence` and `top_negative_reasons`

---

## 6. `WeightTable` — The Tunable Knobs

Loaded from `weights.json` at analyzer init AND by the fusion engine. Edited by hand or by `tune.py`.

### 6.1 Schema

```python
class WeightTable(BaseModel):
    version:           str                   # semver
    fusion_engine:     Literal["v1-weighted", "v2-bayesian"]
    threshold:         float = Field(ge=0.0, le=1.0)
    margin:            float = Field(ge=0.0, le=1.0)
    decay:             DecayConfig
    weights:           dict[str, float]     # feature -> weight, keys from SIGNALS.md

class DecayConfig(BaseModel):
    default_half_life_sec:   float = 300.0
    per_feature:             dict[str, float] = {}    # optional override
```

### 6.2 Default `weights.json`

```json
{
  "version": "1.0.0",
  "fusion_engine": "v1-weighted",
  "threshold": 0.55,
  "margin": 0.20,
  "decay": {
    "default_half_life_sec": 300,
    "per_feature": {
      "transcript_role": 600,
      "speaking_pattern": 300,
      "name_similarity": null,
      "email_match": null
    }
  },
  "weights": {
    "name_similarity": 0.15,
    "email_match": 0.30,
    "join_order": 0.05,
    "webcam_usage": 0.05,
    "speaking_pattern": 0.15,
    "transcript_role": 0.25,
    "speaking_ratio": 0.00,
    "face_consistency": 0.00,
    "screen_share_content": 0.05,
    "device_name": 0.00
  }
}
```

Frozen at v1.0 in this repo until `tune.py` produces a labeled-data baseline (target: ≥20 labeled sessions). Until then, face-consistency, speaking-ratio, and device-name weights stay at 0.00.

### 6.3 Weight normalization rule

The fusion engine does NOT require `Σweights = 1.0`. It uses **per-feature normalization**:

```
confidence = Σ(w_i × s_i × d_i) / Σ(w_i × d_i)
```

This means the absolute scale of weights doesn't matter, only their **ratio**. The weights above deliberately sum to 1.0 only as a UX convenience for hand-authoring. `tune.py` may output weights summing to anything else; the fusion engine handles it identically.

---

## 7. `SessionEnvelope` — Session Metadata

Emitted once on `SESSION_START`, persisted alongside participants and verdicts in Postgres `sessions` table.

```python
class SessionEnvelope(BaseModel):
    session_id:          str
    platform:            Literal["zoom", "meet", "teams", "mock"]
    start_wall_clock:    str        # ISO 8601
    expected_duration_min: int = 60
    expected_participants: list[str] = []
    ground_truth_candidate_id: str | None = None    # populated only for labeled mock sessions / past labeled sessions
    notes:               str = ""
```

`ground_truth_candidate_id` is the labeled answer for `tune.py` and for the accuracy harness in [ACCURACY_METRICS.md](./ACCURACY_METRICS.md). It is `None` for production sessions.

---

## 8. Analyzer Interface — The Contract Every Analyzer Implements

```python
# app/analyzers/base.py
from app.schema import Event, Evidence
from abc import ABC, abstractmethod

class Analyzer(ABC):
    """All analyzers implement this interface. Nothing more."""

    @property
    @abstractmethod
    def feature(self) -> str:
        """The feature key this analyzer owns (e.g. 'name_similarity')."""

    @property
    @abstractmethod
    def source(self) -> str:
        """The analyzer id used in Evidence.source (e.g. 'metadata_analyzer')."""

    @abstractmethod
    def initialize(self, weights: WeightTable, session: SessionEnvelope) -> None:
        """Called once on SESSION_START. Load weight, set up state."""

    @abstractmethod
    def on_event(self, event: Event) -> list[Evidence]:
        """Called for every event on the bus. Returns 0 or more Evidence records.
        Idempotent: re-running the same event with same envelope.sequence MUST produce no new evidence."""

    def on_tick(self, t: float) -> list[Evidence]:
        """Optional. Called every 5s by the realtime ticker. Used for analyzers that re-score on a heartbeat
        (e.g. webcam_usage recomputes camera-on ratio). Default: no-op."""
        return []

    def shutdown(self) -> None:
        """Optional cleanup. Default: no-op."""
        pass
```

### 8.1 Hard rules (enforced by `tests/test_contract.py`)

- Only **one** analyzer may own each `feature` key.
- The analyzer's `feature` MUST match a key in `weights.json`.
- `on_event` must be **idempotent** (see hard rule 10 in §3.4).
- `on_event` must be **non-blocking** (≤ 50 ms wall-clock for single event; longer work goes to a worker queue).
- Analyzers **MUST NOT** import or call other analyzers. They share only the event bus.
- Analyzers **MUST NOT** mutate `ParticipantState` directly. They only emit `Evidence`; the realtime ticker owns state.
- Analyzers **MUST NOT** depend on wall-clock time (only `event.envelope.ts`). This makes mock-stream replay deterministic.

---

## 9. Error Handling

| Error class | When | Fusion behavior |
|---|---|---|
| `EvidenceValidationError` | Pydantic schema violation on emitted Evidence | Drop the evidence; log warning with analyzer id; emit a metric |
| `AnalyzerTimeoutError` | `on_event` didn't return in 50 ms | Drop the event (let it re-attempt on next tick); log warning |
| `WeightMissingError` | Analyzer-feature has no entry in `weights.json` | Fail fast at analyzer init — refuse to start the session |
| `ConfidenceNotANumber` | A NaN appears in fusion math (divide by zero) | Return confidence = 0.0, mark `is_decision = False` with reason "fusion math produced NaN" |

---

## 10. Wire Serialization

- All schemas serialize to JSON with `model_dump_json(exclude_none=True, exclude={"raw_payload"}, by_alias=True)` style.
- camelCase boundary is NOT used — APIs expose snake_case for consistency with internal schemas.
- Datetime is always ISO 8601 UTC with `Z` suffix when serialized.
- Byte payloads (audio, video) are base64.

---

## 11. Backwards Compatibility

This contract is v1.0. Future minor versions (1.x) may add **optional** fields with safe defaults. Major version bumps (2.0) MUST be accompanied by a migration script and a clear deprecation schedule in CHANGELOG.md.

Anything that breaks:
- field renaming → major bump
- field removal → major bump
- type widening (`str → str | None`) → minor bump (safe)
- type narrowing → major bump
- new Evidence/Evidence required field → major bump
- new Evidence/Evidence optional field → minor bump (safe)

---

## 12. Test Contract

`tests/test_contract.py` runs every analyzer against synthetic Events and asserts:

1. Each emitted `Evidence` parses against the schema (no `ValidationError` raised).
2. Each `feature` value is unique across analyzers.
3. Each `feature` is present in `weights.json`.
4. Each analyzer satisfies idempotency — re-running an event with the same sequence yields no new evidence.
5. Each analyzer satisfies monotonicity — `e.ts` never decreases for the same `(source, participant_id)`.
6. Each analyzer satisfies determinism — same events in ⇒ same evidence out, given the same RNG seed.

This test file is the rubric the implementation is graded against. Code that violates any of these is rejected by CI.

---

## 13. Change Log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-07-09 | Initial contract for v1 weighted fusion. |

---

> **Next:** Read [SIGNALS.md](./SIGNALS.md) for the per-analyzer deep dive — scoring curves, edge cases, false-positive risks per signal.
