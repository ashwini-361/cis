# SIGNALS.md — Per-Analyzer Deep Dive

> **Status:** v1.0
> **Cross-refs:** [APPROACH.md](./APPROACH.md) · [DATA_CONTRACT.md](./DATA_CONTRACT.md) · [ARCHITECTURE.md](./ARCHITECTURE.md) · [ACCURACY_METRICS.md](./ACCURACY_METRICS.md)
> **Purpose:** One ~80-line spec per signal: what it ingests, the scoring curve, the edge cases, the false-positive risk, the calibration data needed, and the disabled-by-default rationale where applicable.

---

## 0. Signal Registry

| # | `feature` key | `source` | Default weight | Sticky? | Half-life (s) | Calibrated? |
|---|---|---|---|---|---|---|
| 1 | `name_similarity` | `metadata_analyzer` | 0.15 | yes | — | yes |
| 2 | `email_match` | `metadata_analyzer` | 0.30 | yes | — | yes |
| 3 | `join_order` | `join_order_analyzer` | 0.05 | yes | — | yes |
| 4 | `webcam_usage` | `webcam_analyzer` | 0.05 | no | 60 | yes |
| 5 | `speaking_pattern` | `speaking_pattern_analyzer` | 0.15 | no | 300 | yes |
| 6 | `transcript_role` | `transcript_role_analyzer` | 0.25 | no | 600 | yes |
| 7 | `speaking_ratio` | `speaking_pattern_analyzer` | 0.00 | no | 300 | disabled — folded into #5 |
| 8 | `face_consistency` | `vision_analyzer` | 0.00 | no | 300 | disabled — until `tune.py` clears it |
| 9 | `screen_share_content` | `screen_share_analyzer` | 0.05 | no | 300 | yes (vision CLIP-based) |
| 10 | `device_name` | `metadata_analyzer` | 0.00 | yes | — | disabled — PDF p1 explicitly traps this |

All `feature` keys MUST appear in `weights.json`. All default weights come from [DATA_CONTRACT.md](./DATA_CONTRACT.md) §6.2.

---

## 1. `name_similarity` — Display name vs. candidate name

### 1.1 Inputs
- `METADATA_CANDIDATE` event payload: `{ name: "Ashwini Kumar" }`
- `PARTICIPANT_JOINED` event payload: `{ participant_id, display_name, ... }`
- Optional: subsequent `PARTICIPANT_RENAMED` events trigger recomputation.

### 1.2 Scoring curve
Use `rapidfuzz.fuzz.WRatio` for token-set + token-sort weighted ratio (handles "Ashwini Kumar (L1)" → "Ashwini"). Thresholds:

```
WRatio(display_name, candidate_name)
score = clamp((ratio - 60) / (100 - 60), 0.0, 1.0)
```

| ratio | score |
|---|---|
| <60 | 0.0 |
| 60 | 0.00 |
| 75 | 0.375 |
| 90 | 0.75 |
| 100 (exact) | 1.00 |

### 1.3 Evidence emission
- Fires on `PARTICIPANT_JOINED` and on any `PARTICIPANT_RENAMED` event affecting this participant.
- `supersedes = "name_similarity"` always — newest name punishes the prior.
- `expires_at = None` (sticky) — but a subsequent low similarity score on rename will REPLACE the high score.

### 1.4 Edge cases

| Case | Behavior |
|---|---|
| Candidate name missing from metadata | Skip analyzer entirely (no evidence). |
| Display name `"MacBook Pro"` vs candidate `"Ashwini Kumar"` | ratio ≈ 5 → score 0.00. Reason text: "Display name 'MacBook Pro' appears to be a device name, not the candidate". |
| Display name `"Ashwini Laptop"` vs `"Ashwini Kumar"` | ratio ≈ 78 → score 0.45. Weak support; behavioral signals take over. |
| Display name `"Ashwini Kumar (L1)"` vs `"Ashwini Kumar"` | WRatio strips punctuation → ratio 100 → score 1.00. |
| Display name `"A. Kumar"` vs `"Ashwini Kumar"` | ratio ≈ 86 → score 0.65. Moderate. |
| Unicode names (e.g. "_ATTACK_4522" → checks that the fuzz library handles emoji / mixed unicode without crashing) | The analyzer MUST use `rapidfuzz.utils.default_process` to NFKC-normalize before fuzz. |

### 1.5 False-positive risk
**HIGH** if weighted alone: PDF p1 lists "interviewer enters the wrong candidate name" — that gives a wrong-name participant a high name-similarity score. Mitigation: weight capped at 0.15; behavioral signals carry the call under wrong-name scenarios.

### 1.6 Calibration data
- Need ≥20 labeled sessions showing display_name vs. candidate_name pairs.
- Tune the threshold (60) and the curve shape.
- Per-platform normalization differs — Zoom truncates display names >64 chars; Meet has no truncation.

### 1.7 Disabled / weight-0 rationale
Not disabled — name is cheap and load-bearing when clean. But weight kept moderate.

---

## 2. `email_match` — External metadata × participant email

### 2.1 Inputs
- `METADATA_CANDIDATE` event payload: `{ email }`
- `PARTICIPANT_JOINED` event payload: `{ email?: ... }` — note: `email` is optional per platform. Zoom exposes participant email if the host authorized the SDK with `meeting:read:admin` scope; Meet rarely exposes email for external guests.

### 2.2 Scoring curve
Exact, case-insensitive match after RFC 5321 normalization (`email.lower().strip()` + Gmail `+tags` and `.`-stripping):

```
if normalize(display_email) == normalize(candidate_email):
    score = 1.00
else:
    score = 0.00
```

Binary. Partial credit is not meaningful for an email match (near-miss emails are spoofing, not the same person).

### 2.3 Evidence emission
- Fires on `PARTICIPANT_JOINED` IF and only if the platform provides `email`.
- Sticky (`expires_at=None`), no `supersedes` (one-shot).
- Reason text: `"Participant's email ashwini@gmail.com matched calendar metadata exactly"` or `"... did not match expected ashwini.k@gmail.com"`.

### 2.4 Edge cases

| Case | Behavior |
|---|---|
| Participant has no email (platform doesn't expose it for guests) | Skip analyzer. No evidence emitted. |
| Candidate email is `"ashwini+xyz@gmail.com"` | Gmail-tag-strip: collapse to `"ashwini@gmail.com"` before comparing. |
| Candidate email `"ashwini.k@gmail.com"` vs participant `"ashwini.kumar@gmail.com"` | Not equal — score 0.00. Reason notes both addresses for debugging. |
| Participant joined with the candidate's email but display_name is "MacBook Pro" | Score 1.00. Behavioral signals ADD to it. (This is the canonical case in APPROACH.md §5.) |

### 2.5 False-positive risk
**LOW** for true matches. The risk is the inverse — email *missing* on many platforms. Analyzer must degrade silently; no `email` → no evidence, not -0.30.

### 2.6 Calibration data
- Track per-platform email-availability rate (need ≥20 sessions on each of Zoom and Meet).
- If the email availability rate is <40%, consider boosting the weight of `transcript_role` to compensate.

### 2.7 Weight rationale
0.30 is the highest single-signal weight because: (a) emails are unique identifiers; (b) this is usually where candidate identity comes from in the actual production Sherlock system.

---

## 3. `join_order` — Sequence of join events

### 3.1 Inputs
- All `PARTICIPANT_JOINED` events for the session, ordered by `ts`.
- `METADATA_SCHEDULE.interviewer_names` if present (allows distinguishing "interviewer joined first" from "candidate joined first" more confidently).

### 3.2 Scoring curve
Compute the join order index for each participant. Typical interview rhythm:

```
order 1 (first joined)    → 0.60 support for candidate  (some interviews: interviewer joins first)
order 2                   → 0.30 support for candidate  (most common — interviewer → candidate)
order ≥3                  → 0.10 support for candidate  (observers / late joiners)
```

Boost if the participant is NOT in `interviewer_names` and there ARE interviewer names in metadata:

```
if interviewer_names is not None and participant_display_name not in interviewer_names:
    boost = +0.20
```

Final score is `min(base + boost, 1.0)`.

### 3.3 Evidence emission
- Fires on each `PARTICIPANT_JOINED` event BUT then re-fires with `supersedes = "join_order"` once 60s have elapsed since `SESSION_START` so the full join order is captured. Until then; the initial emissions are provisional.
- Sticky (`expires_at=None`).

### 3.4 Edge cases

| Case | Behavior |
|---|---|
| Host candidate joins first (unusual but possible) | Order 1 + no `interviewer_names` boost → score 0.60 (moderate, not decisive). |
| Observer joins first (silent) | Order 1 + low on every other signal → fusion correctly places them low. |
| Interviewer joins 5 min before candidate (common pattern) | Interviewer gets order-1 boost of 0.60 — TAINTS the interviewer's confidence. Mitigation: if the metadata `interviewer_names` lists this person, NEGATE: instead of "candidate support", emit a "NOT candidate support" with score 0.10. This is an **anti-evidence** pattern. |
| Candidate is 15 minutes late | Joins as order ≥3 → low base score (0.10), but every other signal carries the verdict. |

### 3.5 False-positive risk
**HIGH** if weighted alone — many interviews have the interviewer join first to set up. Hence weight capped at 0.05. This is purely a cold-start tiebreaker before the transcript is available.

### 3.6 Calibration data
- Track order-1 was candidate vs. order-1 was interviewer across labeled sessions.
- Use this to validate whether the `interviewer_names` boost is needed.

---

## 4. `webcam_usage` — Webcam on/off over time

### 4.1 Inputs
- `WEBCAM_ON` / `WEBCAM_OFF` events.
- Per analyzer tick (5s), the analyzer computes the on-ratio for each present participant.

### 4.2 Scoring curve

```
ratio = total_camera_on_sec / total_present_sec  (for this participant, since session start)
score = clamp((ratio - 0.30) / (0.80 - 0.30), 0.0, 1.0)
```

| on-ratio | score |
|---|---|
| 0.00 | 0.00 |
| 0.30 | 0.00 |
| 0.55 | 0.50 |
| 0.80 | 1.00 |
| 1.00 | 1.00 |

### 4.3 Evidence emission
- `on_tick` every 5s: re-emit `webcam_usage` evidence with current ratio.
- `supersedes = "webcam_usage"` — newest reading replaces prior.
- `expires_at = ts + 60` — 60-second half-life (shorter than default 300s because webcam state changes frequently).

### 4.4 Edge cases

| Case | Behavior |
|---|---|
| Webcam never on | Ratio 0 → score 0. Reason text: "Webcam never active". |
| Webcam on briefly at start, off rest of call | Ratio drops to ~0.05 → score 0. |
| Interviewer webcam off, candidate webcam on | Differentiates candidate from interviewer — exactly the use case. |
| Both off (audio-only interview) | Score 0 for both — contributes nothing. Other signals carry. |

### 4.5 False-positive risk
**MODERATE**. Some interviewers keep webcam on; some candidates keep it off (PDF p4 acknowledges "Camera off"). That's why weight = 0.05 — this is a tiebreaker.

### 4.6 Calibration data
- Track on-ratio distributions for candidates vs. interviewers vs. observers from labeled sessions.
- If candidate on-ratio median ≥0.80 and interviewer median ≤0.50, weight might be safe to bump to 0.10. Don't bump without data.

---

## 5. `speaking_pattern` — Turn-taking structure

### 5.1 Inputs
- Stream of `TRANSCRIPT_SEGMENT` events.
- The analyzer keeps a sliding window of the last 60 seconds of segments per participant.

### 5.2 Scoring curve

A "candidate turn-taking pattern" is:

```
Interviewer asked → Candidate answered → Interviewer asked → Candidate answered → ...
```

Compute per participant p:

```
1. partition segments into turns (silence gap ≥ 1.5s = new turn)
2. for each turn transition (a → b), where turn a ends and turn b begins within 2s:
   - if a == interviewer and b == p:    candidate_score += 1   (p answers interviewer)
   - if a == p and b == interviewer:   candidate_score += 0   (p asks interviewer — neutral)
   - if a == p and b == observer:     candidate_score -= 0.5  (p questions an observer — NOT interview)
   - if a == interviewer and b == observer: candidate_score -= 0.2 (interviewer questions observer — neutral for p)
3. score = clamp((candidate_score / max(candidate_score_across_participants, 1)), 0.0, 1.0)
```

Identifying "who is the interviewer": use the `transcript_role` analyzer's most recent output, OR if not yet available, treat the participant in `metadata.interviewer_names` as interviewer. Falls back to "the most-asked-questions participant" heuristic if neither available.

### 5.3 Evidence emission
- Re-fires every 5s via `on_tick` (uses sliding window of last 60s).
- `supersedes = "speaking_pattern"`.
- `expires_at = ts + 300` (5-min default half-life).

### 5.4 Edge cases

| Case | Behavior |
|---|---|
| Only 2 participants (1 interviewer + 1 candidate) | Strong alternation signal; reaches score ≈ 0.85 in 2 min. |
| 3-4 interviewers taking turns asking the candidate | Strong signal: every "interviewer → candidate" transition counts, regardless of which interviewer. |
| Candidate monologue (answering a long-form question) | Counts as one candidate turn with no transitions; analyzer keeps last 60s sliding window so monologues don't pollute. |
| Observer interrupts once | One (-0.5) penalty; minor effect due to max-normalization. |
| Candidate also asks the interviewer questions | "candidate → interviewer" transitions are neutral (don't penalize — candidates do ask clarifying questions). |

### 5.5 False-positive risk
**LOW** for true candidates (pattern is robust). **MODERATE** when two interviewers alternate asking the same observer questions (would falsely mark the observer as candidate) — muy rare in interviews.

### 5.6 Calibration data
- ≥20 labeled sessions with transcripts.
- Measure the score distribution for true candidates vs. true interviewers. If distributions overlap >30%, increase half-life (more smoothing) or drop weight.

---

## 6. `transcript_role` — LLM role classifier

### 6.1 Inputs
- Sliding 60s window of `TRANSCRIPT_SEGMENT` events.
- Optional: `metadata.interviewer_names` (improves LLM accuracy — localizes the question).

### 6.2 Scoring curve
Batch the last 60s of segments and send to the LLM with the following prompt (full prompt in code, condensed here):

```
You are an interview-role classifier. For each participant in the transcript below,
return a JSON object with:
  participant_id, role ∈ { "interviewer", "candidate", "observer", "unclear" }, confidence ∈ [0,1]

Use these cues:
- Interviewer: asks questions, sets topics, controls the flow.
- Candidate: answers questions, talks about themselves, screens-shares their work.
- Observer: listens, doesn't speak or speaks very briefly.
- Unclear: insufficient evidence in this window.

Transcript:
{segments_json}

Return a JSON array, one entry per participant. No prose.
```

Parse JSON; for each participant:

```
if role == "candidate":
    score = confidence                  # 0.70 → 0.70
elif role == "unclear":
    return None                         # no evidence this tick
else:
    score = 0.0                          # anti-evidence for "candidate" hypothesis
    reason notes the role assignment as anti-evidence
```

### 6.3 Evidence emission
- Re-fires on `on_tick` (every 5s) using newest 60s window.
- `supersedes = "transcript_role"`.
- `expires_at = ts + 600` (10-min half-life — LLM verdicts are sticky).
- `reason` includes the LLM's evidence example, e.g. `"Answered 7 of last 8 interviewer questions in Q&A turns (LLM confidence 0.92)"`.

### 6.4 Edge cases

| Case | Behavior |
|---|---|
| LLM returns malformed JSON | Retry once with `"Return strict JSON only. No markdown."` prepended. Two failures → skip the tick; no evidence emitted; log a metric. |
| Only 2 participants, both speak | LLM has decent signal even at low word counts — `confidence` ~0.6 typical. |
| 30s of silence | Skip analyzer; no transcript. |
| LLM is rate-limited | Backoff 4s; combine next 2 windows into one call. Don't retry more than 3 times per minute. |
| Candidate is interviewing (job interview where candidate also asks the interviewer; culture-fit session) | LLM may oscillate between "unclear" and "candidate". The 10-min half-life smooths this out. |
| Two interviewers + one candidate, all speak similar amounts | LLM cues on question-asking vs. question-answering — robust here. |

### 6.5 False-positive risk
**LOW** for true candidates *when the LLM is given a 60s window with ≥3 turns*. Higher risk in the first 60s when there isn't enough content. Don't emit evidence until ≥3 turns exist in the window — explicit gate.

### 6.6 Calibration data
- ≥50 labeled 60s windows with role labels for true candidate, true interviewer.
- Measure LLM accuracy (precision, recall, F1).
- If LLM accuracy < 0.85, drop weight 0.25 → 0.20.

### 6.7 Cost & latency management
- LLM call latency target: ≤ 500ms (use Qwen / Gemini Flash / GPT-4.1-mini, NOT GPT-4).
- Batch every 5s → 12 calls/minute. Budget 1440 calls for a 2-hour session at worst case.
- Cache identical 60s windows (only changes if new segments arrive).
- Fall back to local Llama 3.1 8B via Ollama on the same machine if API unavailable.

### 6.8 Provider interface
The analyzer must implement `LLMProvider` interface so the LLM is swappable:

```python
class LLMProvider(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> dict: ...
```

Implementations: `OpenAICompatibleProvider`, `OllamaProvider`. No production dependency on a single vendor.

---

## 7. `speaking_ratio` — (Disabled)

### 7.1 Status
**Disabled by default** (`weight: 0.00`). Folded into `speaking_pattern` and `transcript_role`. Kept in the schema so `tune.py` may re-enable it as a tiebreaker.

### 7.2 What it would compute if enabled
- Per-participant speaking time / total speaking time over the session.
- Score curve: `score = clamp((ratio - 0.40) / (0.65 - 0.40), 0.0, 1.0)` (0.40 typical interviewer, 0.65 typical candidate).

### 7.3 Why disabled
Highly correlated with `speaking_pattern` (both come from transcript). Enabling both double-counts a single underlying signal. Keep only the stronger one.

---

## 8. `face_consistency` — Continuous-face detection (NOT recognition)

### 8.1 Critical distinction
This analyzer does NOT recognize faces. It detects **face swaps** — sudden changes in the person on a given participant's webcam. PDF p4 explicitly warns: "face recognition only" is the wrong solution; face *consistency* is a perfectly legitimate supporting signal.

### 8.2 Inputs
- `VIDEO_FRAME` events (one per participant per ~1s).
- Use MediaPipe Face Detection to find a face in the frame; use InsightFace'sArcFace embedding as a 512-dim signature (NOT for identification, only for distance-within-the-same-participant).

### 8.3 Scoring curve
Per participant, maintain an exponential moving average (EMA) embedding `μ_p`. Score each new frame:

```
distance = cosine_distance(new_embedding, μ_p)
update μ_p = 0.9 * μ_p + 0.1 * new_embedding     # slow update
score_for_frame = clamp(1 - distance / 0.5, 0, 1) # if distance <0.5, score >0
```

Then over the last 60s:

```
score = mean(scores_for_frame in last 60s)
```

If score ≥ 0.85 continuously, the face has been consistent → supportive evidence. If score drops below 0.30 in any window, emit a low-score evidence (anti-evidence). The reason text MUST explicitly call out a possible face swap.

### 8.4 Evidence emission
- `on_tick` every 5s.
- `supersedes = "face_consistency"`.
- `expires_at = ts + 300` (5-min half-life).
- If no face in 60s (webcam off), no evidence (not zero — analyzer is silent).

### 8.5 Edge cases

| Case | Behavior |
|---|---|
| Webcam off | No frames; analyzer silent; no evidence (not score 0). |
| Person briefly ducks out of frame | EMA picks up the previous face again when they return; no false swap. |
| Real face swap at t=134s (deepfake injection) | Sudden cosine distance spike — score drops from 0.95 to 0.10. Reason text: `"Face embedding changed abruptly at t=134s — possible face swap"`. Anti-evidence: weakens confidence on this participant. |
| Two people in frame | MediaPipe will return 1 face box (largest). EMA stays on one; partial confusion but not catastrophic. Future improvement: track all faces. |
| Lighting changes | EMA + cosine-distance-tolerance threshold (0.5) absorbs gradual change. |
| Lookalike replacement (someone hired to look similar) | Limitation — face consistency alone can't catch this. Documented in [EVALUATION.md](./EVALUATION.md) limitations. |

### 8.6 False-positive risk
**LOW** — face swaps are rare in real interviews; a true swap is exactly the case we want to flag. The analyzer never says "this face is candidate X" — only "this face is consistent with the face from earlier".

### 8.7 Calibration data
- ≥20 labeled sessions with face embedding time series.
- Measure the distribution of cosine distances for: (a) same-person same-call, (b) same-person across different calls, (c) different people lookalike.
- Choose threshold (0.5) to keep type-1 error rate <2% (don't false-flag real interviews).

### 8.8 Disabled-by-default rationale
- Risk of false-positives from low-quality streams (webcam compression artifacts).
- Vision pipeline adds latency and dependency surface (MediaPipe + InsightFace).
- The plan is to enable weight 0.00 → 0.05 ONLY after `tune.py` validates accuracy on labeled face-swap data.
- Until then, given that we're a prototype-grade system, vision is a stretch goal.

---

## 9. `screen_share_content` — Shared screen content classification

### 9.1 Inputs
- `SCREEN_SHARE_START` / `STOP` events.
- `SCREEN_FRAME` events (one every ~2s while sharing).

### 9.2 Scoring curve
For each shared screen frame, send to a vision CLIP model with candidate prompts:

```
prompts = [
  "resume document",
  "code editor / IDE",
  "browser",
  "spreadsheet",
  "candidate project",
  "PowerPoint slides",
  "screen with interviewer branding (e.g. company logo / Zoom app)",
  "video game",
  "blank desktop",
]
```

CLIP returns cosine similarity to each prompt; take top-1.

Score mapping:

| Top-1 label | score | reason |
|---|---|---|
| resume document | 0.95 | "Screen-shared resume" |
| code editor / IDE | 0.90 | "Screen-shared IDE" |
| candidate project | 0.90 | "Screen-shared project work" |
| browser | 0.60 | "Screen-shared browser content" |
| spreadsheet / PowerPoint slides | 0.50 | "Screen-shared presentation material" |
| screen with interviewer branding | 0.10 | "Screen-share appears to be interviewer content (likely interviewer driving)" |
| else | 0.20 | "Screen-share content did not match candidate-leaning patterns" |

If two or more frames converge on the same top-1 label within a sharing session, emit a single evidence with mean score.

### 9.3 Evidence emission
- Fires at the END of each `SCREEN_SHARE_START` → `STOP` window (after classification aggregation).
- Or every 30s during a long share, whichever comes first.
- `expires_at = ts + 300`.
- Sticky within a single sharing session; replaced at next sharing session (`supersedes = "screen_share_content"`).

### 9.4 Edge cases

| Case | Behavior |
|---|---|
| Interviewer shares a slide deck (very common in interviews) | CLIP classifies as "PowerPoint slides" + "screen with interviewer branding" → score 0.10. Anti-evidence for the person sharing. |
| Candidate shares their IDE to walk through code | Score 0.90. |
| Candidate shares a resume | Score 0.95. |
| Screen share but no participant attribution (Meet sometimes does this) | Emit evidence for the participant who triggered `SCREEN_SHARE_START`, even if attribution is shaky. Mark the evidence `reason` with "attribution assumed". |
| Prank share (someone shares a movie) | Score 0.20. Low anti-evidence. Don't false-flag — let other signals carry. |

### 9.5 False-positive risk
**MODERATE** — interviewers sharing slides is common. The CLIP classification into "interviewer branding" or "presentation material" limits the damage. Still a secondary signal — weight 0.05.

### 9.6 Calibration data
- ≥20 sessions with screen-share frames labeled "candidate vs. interviewer".
- Validate CLIP top-1 accuracy.

---

## 10. `device_name` — (Disabled)

### 10.1 Status
**Disabled by default** (`weight: 0.00`). The PDF p1 calls this out as a trap ("Candidate joins as MacBook Pro").

### 10.2 What it would compute if enabled
Token-inspect the display name. If it matches a device-name pattern (`iPhone`, `iPad`, `MacBook`, `Pixel`, `Galaxy`, `Laptop`, `PC`, `Desktop`, generic nickname such as `Ashwini's Laptop`), emit anti-evidence:

```
score = 0.05   # very weakly candidate
reason: "Display name appears to be a device name — low candidate likelihood"
```

Not a strong signal — just an anti-signal.

### 10.3 Why disabled
Even emitting weak anti-evidence risks penalizing the rare candidate who DID join as their phone and we cannot distinguish. The safest behavior is to *not emit any evidence* — let other signals handle. The PDF case study "MacBook Pro" is actually handled by `name_similarity` going to 0.0, which is enough.

### 10.4 Calibration data
None — this signal is permanently disabled.

---

## 11. Cross-Analyzer Sequencing

Analyzers SHOULD fire in this order on each tick to keep evidence timestamps close:

1. `metadata_analyzer` (sticky; emits only on join/rename)
2. `join_order_analyzer` (sticky; re-emits once at t=60s)
3. `webcam_analyzer` (every 5s)
4. `screen_share_analyzer` (per session)
5. `speaking_pattern_analyzer` (every 5s)
6. `transcript_role_analyzer` (every 5s, queued; LLM call ≤500ms)
7. `vision_analyzer` (every 5s — slowest, runs in worker pool)

This is not a hard requirement but reduces evidence-store contention.

---

## 12. Future Signals (Out of Scope for v1.0)

Listed for honesty's sake — these are NOT in the v1 plan but listed here for [ROADMAP.md](./ROADMAP.md) and future scope discussions.

- **Background noise consistency**: room acoustic fingerprint to detect "candidate" appearing in a different physical environment across sessions.
- **Punctuation / typing pauses in transcript**: hesitation markers stronger for interviewees than interviewers.
- **Calendar invite role metadata**: if the candidate is in the invite with role=candidate (currently rare across platforms).
- **Voice embedding across sessions**: this crosses into "voice recognition" territory PDF warns against — kept disabled by default.

---

## 13. Change Log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-07-09 | Initial per-signal specs, all 10 signals defined. |

---

> **Next:** Read [ARCHITECTURE.md](./ARCHITECTURE.md) for the system shape and dataflow; then [PLATFORM_INTEGRATION.md](./PLATFORM_INTEGRATION.md) for real Zoom + Meet capture contracts.
