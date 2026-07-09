# APPROACH.md — Sherlock Internship Challenge

> **Status:** v1.0 (Polished from initial ChatGPT exploration)
> **Author:** meet project
> **Owner:** you
> **Last updated:** 2026-07-09
> **Cross-refs:** [ARCHITECTURE.md](./ARCHITECTURE.md) · [SIGNALS.md](./SIGNALS.md) · [DATA_CONTRACT.md](./DATA_CONTRACT.md) · [ROADMAP.md](./ROADMAP.md)

---

## 0. TL;DR

The Sherlock assignment is intentionally open-ended. The single biggest signal in the prompt is the bonus line:

> Use multiple weak signals instead of relying on one rule.

That sentence rules out face-recognition-only, voice-recognition-only, name-matching-only, and LLM-only solutions, and it rules in a **real-time probabilistic evidence-fusion system** modeled after autonomous-systems sensor fusion. This document defends that thesis, enumerates the signals we will fuse, names the architecture, traces every design decision back to a graded rubric item from the PDF, and ends with a critical self-review.

The companion implementation plan lives in [ROADMAP.md](./ROADMAP.md). The per-signal deep-dive lives in [SIGNALS.md](./SIGNALS.md). The wire-level contract lives in [DATA_CONTRACT.md](./DATA_CONTRACT.md).

---

## 1. First-Principles Analysis

### 1.1 What is Sherlock actually asking for?

The brief gives six functional requirements (PDF p3):

1. Automatically identify the candidate
2. Continuously update confidence during the interview
3. Handle incorrect names
4. Handle missing information
5. Handle ambiguous situations
6. Explain why it selected a participant

It also relaxes implementation constraints completely: any models, any LLMs, any open-source, any agents, any cloud (PDF p5). The only hard requirement is "practical and demonstrate how Sherlock could identify the correct interview participant reliably in real time."

The closing note on PDF p6 sharpens the success criterion:

> Don't optimize only for the final answer. Show us how your system reaches its conclusion. In production, explainability, confidence estimation, and graceful handling of ambiguity are just as important as raw accuracy.

### 1.2 Why "single-sensor" solutions fail the brief

| Single-sensor solution | Why it fails |
|---|---|
| Face recognition only | Camera off, candidate changes appearance, two similar candidates, deepfake vs. real — all break this. Also misreads the brief: the brief wants *identification under uncertainty*, not identity verification. |
| Voice recognition only | Multiple interviewers, silent observers, candidate with mic off during Q&A-trigger windows — all break this. |
| Name matching only | Candidate joins as "MacBook Pro" (an explicit example from PDF p1), wrong calendar name, candidate changes display name (explicit), nickname vs. legal name. |
| LLM-only reasoning | Latency too high for real-time 5s updates on raw streams; brittle on cold-start when no transcript yet; no principled confidence aggregation; fails "graceful handling of ambiguity" because the LLM hallucinates a winner. |
| Single heuristic | Fails the bonus criterion directly. |

### 1.3 What does work — evidence fusion

Production fraud systems, autonomous vehicles, and recommendation systems all combine uncertain evidence from many sensors into a single confidence-weighted verdict. The pattern is:

```
   Evidence 1
        \
   Evidence 2 ──┐
                \
   Evidence 3 ───┼──→ Fusion Engine ──→ Confidence + Explanation
                /
   Evidence 4 ──┘
        /
   Evidence 5
```

Each sensor is **decoupled** and emits a normalized piece of evidence. A fusion engine combines the evidence. An explainability layer renders the decision back into bullets a human can audit. This is exactly the shape the brief is asking for.

The companion research basis for the acoustic/semantic fusion variant is the ACL 2023 Findings paper on combining speaker-related information for spoken-meeting diarization ([ACL Anthology](https://aclanthology.org/2023.findings-acl.884.pdf)).

---

## 2. Core Thesis (Three Sentences)

**Treat every participant as a candidate hypothesis.** Every few seconds each participant accumulates normalized, weighted evidence from independent sensors (metadata, audio, video, transcript, behavior). The participant whose fused confidence crosses a decidable threshold with enough margin over the runner-up is declared the candidate; otherwise the system explicitly reports it is still deciding.

This thesis directly satisfies every graded criterion in the PDF rubric (problem-solving 25%, engineering quality 20%, AI/ML approach 20%, product thinking 15%, scalability 10%, code quality 5%, creativity 5%) and every bonus point (multiple weak signals, confidence score, explainability, continue learning, real-time, graceful uncertainty handling).

---

## 3. The Ten Signals

A signal is a self-contained module that ingests one data stream and emits `Evidence` records. Each signal is **decoupled** from every other signal: they share only the contract in [DATA_CONTRACT.md](./DATA_CONTRACT.md). Full per-signal specifications live in [SIGNALS.md](./SIGNALS.md); the summary:

| # | Signal | Source | Default weight | Why |
|---|---|---|---|---|
| 1 | **Name similarity** | External metadata × display name | 0.15 | Strong when calendar metadata is accurate; brittle to PDF p1's "wrong candidate name" / "nickname" / "MacBook Pro" cases. |
| 2 | **Email match** | External metadata × participant email (when exposed) | 0.30 | Strongest single signal when available — exact match. |
| 3 | **Join order** | Real-time join events | 0.05 | Weak but cheap; carries signal early before transcript exists. |
| 4 | **Webcam usage** | Real-time webcam on/off events | 0.05 | Candidate usually keeps webcam on; observers don't. |
| 5 | **Speaking pattern (turn-taking)** | Diarized transcript | 0.15 | Candidate ↔ interviewer alternation is a very strong *behavioral* cue that resists wrong-name scenarios. |
| 6 | **Transcript semantic role** | LLM over transcript windows | 0.25 | Often the strongest behavioral signal; "Who is asking vs. answering questions?" pdf p4 explicitly invites LLM use. |
| 7 | **Speaking ratio** | Diarized transcript | — ( folded into #5 ) | Weak alone; coefully captured by turn-taking. |
| 8 | **Face consistency** | Per-participant webcam frames | 0.00 → 0.05 once calibrated | **Consistency**, not recognition — penalizes face swaps, doesn't try to name identities. |
| 9 | **Screen share content** | Real-time screen-share frames | 0.05 | Resume / IDE / project as screen share is a candidate-leaning signal. |
| 10 | **Device name** | Participant display metadata | 0.00 | Don't assume "MacBook Pro" isn't the candidate; PDF p1 explicitly warns against this. Disabled by default. |

Weights are stored in `weights.json` so a `tune.py` script can recalibrate from labeled past sessions — satisfying the "continue learning" bonus point.

### 3.1 Every signal produces the same thing

Each analyzer module returns one or more `Evidence` records of the same shape (full schema in [DATA_CONTRACT.md](./DATA_CONTRACT.md)):

```python
Evidence(
    participant_id="P2",
    feature="name_similarity",
    score=0.12,                          # 0.0 – 1.0
    weight=0.15,                         # default weight from weights.json
    reason="Display name 'MacBook Pro' vs. expected 'Ashwini Kumar'",
    ts=2.3,                              # meeting seconds when the evidence fired
    source="metadata_analyzer",
)
```

Modules **do not know** about each other. They only produce evidence. This is the same decoupling pattern you'd find in an autonomous-driving stack.

---

## 4. Architecture (One-Paragraph Preview)

A meeting SDK adapter (Zoom OAuth + transcript API, Google Meet Recording API + Chrome capture) publishes normalized events onto an in-process async event bus (`asyncio` + `aioredis` pub/sub for cross-process scale). Five independent analyzer families (Metadata, Audio, Transcript, Vision, Behavior) subscribe to the bus, each emitting `Evidence` records into an evidence store. A 5-second real-time ticker calls the fusion engine, which combines all evidence for each participant via a weighted-Bayesian update and writes a `ParticipantState` (confidence + sorted evidence) to Redis. When the leader's confidence crosses a threshold with sufficient margin over the runner-up, fusion emits a `Verdict` (candidate + confidence + reasons). A FastAPI WebSocket pushes each verdict to a dashboard; the explainability generator renders the evidence log as bullet points. Full diagram and sequence flows in [ARCHITECTURE.md](./ARCHITECTURE.md).

```
Meeting SDK  ──►  Event Bus  ──►  ┌─ Metadata Analyzer ─┐
                                  ├─ Audio Analyzer     ─┤
                                  ├─ Transcript Analyzer ─┤  ──►  Evidence Store
                                  ├─ Vision Analyzer    ─┤            │
                                  └─ Behavior Analyzer  ─┘            ▼
                                                                 Fusion Engine
                                                                       │
                                                                       ▼
                                                              ParticipantState  ──►  WebSocket  ──►  Dashboard
                                                                       │
                                                                       ▼
                                                               Verdict + Reasons
```

---

## 5. Real-Time Updating (The Confidence Curve)

A practical interview lasts 30–60 minutes. The system recomputes confidence every **5 seconds** to satisfy PDF p3 "Continuously update confidence during the interview" and PDF p4 bonus "Work in real time." The curve typically evolves as:

| Time | P1 (Ashwini) | P2 (MacBook Pro) | P3 (Interviewer) | State |
|---|---|---|---|---|
| 0s   | 0.00 | 0.00 | 0.00 | Cold-start, no evidence yet |
| 5s   | 0.42 | 0.03 | 0.05 | Email + name matched P1 |
| 30s  | 0.68 | 0.05 | 0.18 | Join-order + webcam favors P1 |
| 2min | 0.83 | 0.08 | 0.42 | Transcript Q&A roles cleaved interviewer/candidate |
| 5min | 0.97 | 0.10 | 0.45 | **Decidable**: gap > 0.20 over runner-up, both above 0.55 threshold |
| 10min| 0.98 | 0.11 | 0.46 | Stable; verdict locked |

Each tick emits a verdict; low-confidence ticks carry `is_decision = false` so the dashboard can show "still deciding" — see §7 below.

---

## 6. Explainability

Every positive contribution becomes a bullet in the verdict reason list. The explainability layer renders the evidence log of the winning participant into human-readable bullets, ordered by descending contribution:

```
Candidate: P1 ("Ashwini")  — confidence 97%

✓ Email matched calendar metadata              contributed +0.30 × 1.00 = +0.300
✓ Transcript role: answered all Q&A turns      contributed +0.25 × 0.92 = +0.230
✓ Display name similarity 96%                  contributed +0.15 × 0.96 = +0.144
✓ Speaking pattern matched candidate turn-taking (+0.15 × 0.80)  = +0.120
✓ Webcam active throughout meeting             contributed +0.05 × 1.00 = +0.050
✓ Screen-shared IDE / resume                   contributed +0.05 × 0.90 = +0.045
✓ Joined first (typical candidate behavior)    contributed +0.05 × 0.60 = +0.030

Reasoning behind rejected hypotheses:
- P2 "MacBook Pro": low on every signal except webcam. Net 0.10.
- P3 (interviewer): strong on interviewer-role transcript, but anti-correlated with candidate role
  — transcript analyzer emits a complementary negative score for P3.

Total weighted evidence: 0.919 (normalized across all 7 active signals)
```

This matches PDF p6 closing note exactly: "Show us how your system reaches its conclusion."

---

## 7. Handling Edge Cases (PDF p3 requirement)

| PDF-stated case | How the fusion approach handles it |
|---|---|
| **Candidate changes display name** (MacBook Pro mid-call) | Name-similarity signal drops to ~0; behavioral signals dominate within ~5 seconds. Fusion recomputes. |
| **Wrong candidate name in calendar** | Name-similarity weight effectively zero (or we pass soft top-k match). Behavioral signals confidently carry the prediction. |
| **Multiple interviewers present** | Transcript analyzer emits `role=interviewer` evidence for each — none of them accumulate candidate-role evidence, so candidate stays on top. |
| **Candidate joins using a nickname** | Same as "wrong name": name signal weak, behavioral signals strong. |
| **Multiple observers join silently** | Observers accrue near-zero evidence on every signal (no speaking, no cam, no Q&A role). Confidences stay near 0. |
| **Candidate joins as MacBook Pro** (device name as display) | Treated identically to nickname. Device-name signal (#10) deliberately weight 0 because it's a trap. |
| **Webcam off** | Vision analyzer scores 0; audio + transcript + metadata analyzers continue working. Verdict delayed but not blocked. |
| **Two similar participants** (Ashwini / Ashwini Laptop) | Initial confidences 0.45 / 0.43 — neither crosses threshold. Transcript Q&A reveals only one is answering interviewer questions. Confidence diverges over 1–2 minutes. |
| **All signals weak / no decidable gap** | The verdict explicitly returns `is_decision = false` with `candidate_id = None` and a `"insufficient evidence"` reason — graceful uncertainty instead of forced guess. |

---

## 8. Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Backend | **FastAPI** + `asyncio` | Native async event pipeline; auto OpenAPI for free; WebSocket built in. |
| Live platform SDKs | **Zoom OAuth + Meeting/Webhook + Recording API**; **Google Meet Recording API / Chrome extension capture** | PDF p1 lists Meet and Zoom as target platforms. Mock streams remain for unit tests. |
| Speech-to-text | **Per-track Whisper** (one stream per participant, no diarization) | PDF p2 promises "Separate audio stream for every participant" — leverage that, skip diarization complexity entirely. |
| LLM | Qwen / GPT-4.1-mini / Gemini Flash behind an interface | Used only for transcript role classifier; switchable. |
| Vision | **MediaPipe + InsightFace** — face **consistency** only, never recognition | Avoids the "face recognition only" trap and privacy minefield. |
| Streaming | WebSockets (FastAPI native) | Pushes `Verdict` to dashboard at 5s cadence. |
| Live state store | **Redis** | Per-participant state with TTL keyed by session; sub-ms reads on the 5s tick. |
| Session history | **PostgreSQL** | Labeled sessions for offline `tune.py`. |
| Dashboard | **React + confidence-timeline chart** | Real-time verdict + reason panel. |
| Packaging | `uv` or `poetry` via `pyproject.toml` | Reproducible installs. |
| Containerization | `docker-compose` (redis + postgres) | Single `docker compose up` for the demo video. |
| Tests | `pytest` + `pytest-asyncio` | Unit per analyzer; integration with mock bus; e2e with recordings. |

---

## 9. Rubric Traceability Matrix

How this approach satisfies the PDF's published grading categories.

| PDF Rubric (weight) | Where it's satisfied |
|---|---|
| Problem-solving ability (25%) | Multi-signal fusion thesis matches PDF's own stated preference for "multiple sources of evidence... rather than relying on a single heuristic" (PDF p5); graceful-uncertainty handling; decisons updated in real time. |
| Engineering quality (20%) | Analyzer-per-sensor decoupling; typed schemas; mock-first ingest; unit/integration/e2e tests; docker-compose parity with prod env. |
| AI/ML approach (20%) | Per-track Whisper for STT; LLM-only where it's strong (semantic role classification); Bayesian fusion once `tune.py` data exists. |
| Product thinking (15%) | Dashboard with verdict + reason panel; explicit "still deciding" UX; threshold + margin gate prevents premature verdicts that would erode user trust. |
| Scalability (10%) | Async event bus; analyzers parallelize across participants; Redis pub/sub lets analyzers run in separate processes; weights file is the only shared tunable. |
| Code quality (5%) | Pydantic schemas; type hints everywhere; one analyzer per file; `tests/` mirrors `app/analyzers/`. |
| Creativity (5%) | Treating device name as a deliberately-weight-zero trap; face *consistency* not recognition; explicit "no decision yet" verdict; rubric traceability matrix in the README. |

### Bonus-point traceability

| PDF bonus point | Where it's satisfied |
|---|---|
| ✅ Use multiple weak signals | 10-signal fusion table. |
| ✅ Produce a confidence score | `Verdict.confidence` on every tick. |
| ✅ Explain why a participant was selected | `explain/generator.py` bullet list. |
| ✅ Continue learning as more data becomes available | `tune.py` updates `weights.json` from labeled past sessions. |
| ✅ Work in real-time | 5s ticker + WebSocket push. |
| ✅ Gracefully handle uncertainty instead of making incorrect assumptions | `is_decision` flag + `candidate_id = None` below threshold/gap; decisions never forced. |

### Requirement traceability (PDF p3)

| PDF requirement | How satisfied |
|---|---|
| Automatically identify the candidate | Fusion engine + Verdict. |
| Continuously update confidence during the interview | 5s ticker; `ParticipantState.confidence` rewritten every tick. |
| Handle incorrect names | Name-similarity weight is moderate (0.15); behavioral signals dominate. |
| Handle missing information | Missing signals contribute 0 weight; threshold waits for sufficient total. |
| Handle ambiguous situations | Margin-over-runner-up requirement + `is_decision = false` below threshold. |
| Explain why it selected a participant | `reasons: list[str]` populated from evidence log; verbatim bullets. |

---

## 10. Critical Self-Review — Where This Plan Is Still Weak

Being honest about the plan's own weak spots before we ship:

1. **No real-meeting capture in the original plan.** Mock streams alone won't satisfy PDF Deliverable #1 (Working Demo) — a reviewer can fairly call that a "prototype-without-demo". We fix this in [PLATFORM_INTEGRATION.md](./PLATFORM_INTEGRATION.md) by integrating Zoom OAuth + transcript API and Google Meet capture.
2. **Architecture diagram and Evaluation writeup were not in the original plan.** PDF Deliverables #4 and #5 were dropped. We fix this with explicit docs: [ARCHITECTURE.md](./ARCHITECTURE.md) + [ARCHITECTURE.svg](./ARCHITECTURE.svg) and [EVALUATION.md](./EVALUATION.md).
3. **No accuracy metric defined.** PDF Evaluation deliverable asks for "Accuracy". We fix this in [ACCURACY_METRICS.md](./ACCURACY_METRICS.md) with precision@1, time-to-decision, stability, latency, and a labeled-data format.
4. **STT choice ambiguous.** Whisper alone doesn't give the speaker-attributed transcript the plan needs. We resolve this by leaning on PDF p2's promise of per-participant audio streams and running Whisper on each track separately — no diarization needed.
5. **No "continue learning" mechanism.** The original plan updates confidence during a session but never across sessions. We fix this with `weights.json` + `tune.py` minimally, leaving deeper online learning as a future-work item.
6. **Time budget was 4–5 days.** With real platform integration, accuracy harness, dashboard, video, and 3 deliverable writeups, plan for **7–9 days** instead. See [ROADMAP.md](./ROADMAP.md) for the corrected schedule.
7. **Forced-guess risk.** The original `Verdict.candidate_id: str` schema forced a guess even under ambiguity. The polished schema uses `candidate_id: str | None` + `is_decision: bool` so the system can honor PDF bonus "gracefully handle uncertainty".
8. **Face = recognition trap.** The original plan walked the edge by saying "not recognition — consistency". The polished approach disables face-consistency analyzer by default (weight 0.00) and only flips to 0.05 after `tune.py` shows it discriminates.

---

## 11. Rough Self-Rating of the Original Plan

For honesty's sake, rating the *original ChatGPT exploration* against the PDF rubric before the polish above:

| PDF category | Original ChatGPT plan rating | Why |
|---|---|---|
| Problem-solving (25%) | 24/25 | Thesis matches PDF's stated preference directly; only loses 1pt for no graceful-uncertainty escape valve. |
| Engineering quality (20%) | 14/20 | Clean analyzer-as-sensor decoupling; no real-platform integration in original plan; no test plan beyond unit tests. |
| AI/ML approach (20%) | 14/20 | Good LLM placement; Whisper-only STT was wrong without per-track separation; weights file present but no learnable update specified. |
| Product thinking (15%) | 11/15 | Confidence timeline is great UX; verdict schema forced a guess — no "still deciding" state in original. |
| Scalability (10%) | 8/10 | Async bus + Redis is the right shape; original never cross-process-scale considerations. |
| Code quality (5%) | 4/5 | Schema + one-analyzer-per-file plan is clean; no mention of lint/format/typecheck. |
| Creativity (5%) | 5/5 | All five points. |

**Original plan raw:** 80/100 → ⭐⭐⭐⭐☆ (4/5)
**After applying this APPROACH.md's polish:** target ≥ 92/100 → ⭐⭐⭐⭐⭐ (5/5)

The polish is implemented across the other 11 docs.

---

## 12. Suggested Build Order

Given we have 12 docs to write, here is the order in which to write them (matches [ROADMAP.md](./ROADMAP.md)):

1. **APPROACH.md** ← you are here
2. **DATA_CONTRACT.md** — locks the wire-level interface analyzers implement
3. **SIGNALS.md** — per-signal deep dive, references DATA_CONTRACT
4. **ARCHITECTURE.md** + **ARCHITECTURE.svg** — system shape and dataflow
5. **PLATFORM_INTEGRATION.md** — real Zoom + Meet contracts
6. **MOCK_DATA_FORMAT.md** — recording JSON schema + 3 scenarios
7. **ROADMAP.md** — phase plan with corrected 7–9 day schedule
8. **ACCURACY_METRICS.md** — metric definitions + labeled data format
9. **EVALUATION.md** — test methodology, edge cases, results template, limitations
10. **README.md** + **AGENTS.md** — entry-point + onboarding

---

## 13. References

- [Sherlock Internship Challenge.pdf](../Sherlock%20Internship%20Challenge.pdf) — the original assignment (6 pages, in the parent folder)
- [ACL 2023 Findings: Speaker-Related Information in Spoken Meetings](https://aclanthology.org/2023.findings-acl.884.pdf) — research basis for acoustic + semantic fusion for diarization
- [OpenAI / Deepgram / AssemblyAI STT comparison](https://platform.openai.com/docs/guides/speech-to-text) — Choose per-track Whisper when platform-native separate tracks are available

---

## 14. Glossary

| Term | Meaning |
|---|---|
| **Signal** | An analyzer module that ingests one data stream and emits `Evidence` records. |
| **Evidence** | A normalized, weighted contribution to a participant's confidence. Have `participant_id`, `feature`, `score`, `weight`, `reason`, `ts`, `source`. |
| **Confidence** | Per-participant normalized weighted sum of recent evidence, recomputed every 5 s. |
| **Verdict** | The output object emitted each tick: `candidate_id` (or `None`), `confidence`, `reasons`, `is_decision`. |
| **Decidable** | Confidence ≥ threshold (default 0.55) AND margin over runner-up ≥ 0.20. |
| **Margin** | Difference between top-1 and top-2 participant confidences. |
| **Analyzer** | Synonym for "signal module"; implements the contract in [DATA_CONTRACT.md](./DATA_CONTRACT.md). |
| **Bayesian update** | Optional upgrade to the weighted-sum fusion where prior beliefs + new evidence combine via Bayes' rule — only switched on after `tune.py` calibrates priors from labeled data. |
| **Threshold / Margin gate** | The two-condition test that prevents premature verdicts. |
| **Mock stream** | JSON replay of recorded meeting events into the event bus, for tests. |

---

> **Next:** Read [DATA_CONTRACT.md](./DATA_CONTRACT.md) for the exact wire-level `Evidence` / `ParticipantState` / `Verdict` schema; then [SIGNALS.md](./SIGNALS.md) for the per-signal deep dive.
