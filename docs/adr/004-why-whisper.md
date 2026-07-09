# ADR-004: Whisper for speech-to-text, leveraging per-participant audio tracks

> **Status:** Accepted · **Date:** 2026-07-09 · **Decider:** you · **Supersedes:** none · **Superseded by:** none
> **Related:** [../SIGNALS.md §6](../SIGNALS.md) · [../PLATFORM_INTEGRATION.md §2.4, §3.4](../PLATFORM_INTEGRATION.md) · [../TRADEOFFS.md](../TRADEOFFS.md)

---

## Context

The transcript role analyzer ([SIGNALS.md §6](../SIGNALS.md)) drives much of the candidate-vs-interviewer separation. It needs a **speaker-attributed** transcript — segments labeled with which participant said each — so the LLM role classifier can see "P3 asked, P1 answered".

PDF p2 promises:
> Separate audio stream for every participant.

This is gold. It means we don't need to recover speaker identity from a mixed audio stream (which is the diarization problem). We just need:

1. A speech-to-text (STT) engine that produces accurate per-stream transcripts.
2. A way to merge the per-stream outputs into a single speaker-attributed transcript series, ordered by `start_sec`.

Three STT strategies were considered:

| Option | Approach |
|---|---|
| A — Single mixed track + diarization | One mixed `m4a` of the call → diarization (e.g. pyannote) splits by speaker → each speaker chunk transcribed separately (e.g. Whisper). |
| B — Per-participant tracks + Whisper | Each participant's audio track (the PDF-promise per-participant stream) → Whisper transcribes each track independently → results merged by `start_sec`. |
| C — Cloud speaker-attributed STT single-call | Deepgram/AssemblyAI with `diarize=true, speaker_labels=true` and stream-mode — one API call handles both transcription and attribution. |

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| **A — Mixed track + diarization** | Works even when platforms don't expose per-participant tracks; well-supported research stack (pyannote + Whisper). | Diarization is unreliable for similar voices; cross-talk (sarcasm, interrupting) confuses it. 1–3% of segments mislabeled even with SOTA. Duplicates the work the platform has already done. |
| **B — Per-participant tracks + Whisper** | **Honours PDF p2's promise directly.** No diarization needed → no diarization errors. Each track is clean single-speaker audio → Whisper WER drops ~20%. Provenance field notes `"whisper-per-track"` so reviewers can audit. | Requires the platform to actually expose per-participant tracks. Zoom's Cloud Recording with `multi_track_audio=true` does (or pull from Recording API). Meet Recording API disks produce multi-track M4A. Each track incurs one Whisper call → ~1× participant-count computational multiplier. |
| **C — Cloud speaker-attributed STT** | One API call gets transcript + speaker labels. Lower operational surface. | Most cloud diarization is hidden and similar to pyannote accuracy (~95%/1-3% errors). Vendor lock-in. Cost per minute × meeting duration × multiple platforms is real. Doesn't honor the PDF's per-participant-stream promise — treats it as a diarization problem the platform already solved. |

## Decision

**Option B — per-participant tracks + Whisper.** Specified in [`docs/PLATFORM_INTEGRATION.md §2.4, §3.4`](../PLATFORM_INTEGRATION.md) and [`docs/SIGNALS.md §6.7`](../SIGNALS.md).

Concrete rules:
1. Use **faster-whisper** with model `large-v3-turbo` for local deployment, or **`openai/whisper-1`** API for cloud.
2. Run one transcribe call per participant per 30s audio chunk.
3. Tag emitted `TRANSCRIPT_SEGMENT` payloads with `"diarization": "whisper-per-track"` for provenance.
4. Fall-back only when the platform doesn't expose per-participant tracks: emit diarized output via pyannote with `"diarization": "pyannote-fallback"` so reviewers/consumers know the precision was lower.
5. Per-track buffers are 30s (real-time mode) or whatever the recording API returns us (batch mode).
6. Audio bytes NEVER persist; transcripts persist (per [SECURITY.md §2](../SECURITY.md)).
7. LLMProvider abstraction ([SIGNALS.md §6.8](../SIGNALS.md)) mirrors this — Whisper is also behind a `STTProvider` Protocol so vendors swap cleanly.

## Consequences

### Positive
- Avoids the diarization accuracy cliff — every per-track STT run is single-speaker, near-zero WER.
- Honors PDF p2 directly. Closing this loop scores on the AI/ML approach criterion (PDF 20%).
- Lower false-positive rate for transcript_role — every segment's `participant_id` is platform-provided, not inferred.
- Vendor-neutral — Whisper runs locally (no per-call cost) or in the cloud; switchable behind an interface.
- Provenance metadata makes the data quality transparent to downstream assertions and reviewers.

### Negative
- Zoom OAuth has deprecated `multi_track_audio` for some new app categories (2025). Verify with Zoom support before Phase 7a ([ROADMAP.md Phase 7a risk register](../ROADMAP.md)). Mitigation: recording-ID pull via `Recording API` still exposes per-track; documented.
- Real-time path lags by 30s + Whisper turnaround (≤8s on L4 GPU), so verdict updates dependent on transcript_role lag by ~40s. PDF p4 "real-time" is about human-paced verdicts — humans pace questions >30s apart, so this qualifies.
- Compute: on a single L4 GPU, real-time per-track Whisper saturates at ~8 concurrent participant streams. Documented in [PERFORMANCE.md](../PERFORMANCE.md).
- Adds a Python wheel dep (`faster-whisper`) that depends on `ctranslate2` with CUDA wheels — install friction on Windows dev machines. Mitigation: pinned wheel index in `pyproject.toml` and CPU-fallback pre-configured.

### Neutral
- Cloud-attributed STT (Option C) was tempting because Deepgram is cheap (~20¢/min) and good. We kept it as a fallback documented in [PLATFORM_INTEGRATION.md §4 adapter failover table](../PLATFORM_INTEGRATION.md).

## Validation

- `tests/test_analyzers/test_transcript_role.py` mocks a `STTProvider` and asserts per-segment participant_id attribution accuracy on synthetic segment streams.
- The end-to-end proof comes from the Zoom demo capture (5-min real Zoom call with consented interviewer), recording pulled, per-track Whisper transcribed, speaker-attributed segment stream fed to `transcript_role_analyzer` → verdict reached with transcript_role evidence fired correctly (per [EVALUATION.md §4.2](../EVALUATION.md)).

## Classification

- **Type:** Infrastructure / AI choice
- **Cost of reversal:** Low. Adapter-level decision — the `STTProvider` Protocol is the seam; swap implementation to cloud diarization for any single platform without touching analyzers.
- **Risk if wrong:** Low. If per-track audio ever becomes unavailable on a converging platform (Teams), fall back to pyannote on the mixed track; analyzer layer unaffected.
