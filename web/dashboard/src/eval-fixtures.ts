import type { ConfidencePoint } from "./useVerdictStream";
import type { LiveDebugSnapshot, Verdict } from "./types";

export type EvalScenarioId = "happy_path" | "renamed_candidate" | "ambiguous";

interface EvalScenario {
  id: EvalScenarioId;
  label: string;
  description: string;
  verdict: Verdict;
  liveDebug: LiveDebugSnapshot;
  history: ConfidencePoint[];
}

const baseLiveDebug: LiveDebugSnapshot = {
  session_id: "eval-session",
  extension_connected: true,
  extension_connections: 1,
  control_messages: 7,
  audio_chunks: 14,
  transcript_segments: 9,
  verdict_count: 5,
  last_control_type: "PARTICIPANT_RENAMED",
  last_control_payload: { participant_id: "P1" },
  last_audio: { participant_id: "P1", start_sec: 180, end_sec: 205, size_bytes: 6106 },
  last_transcript: {
    participant_id: "P1",
    speaker_name: "Ashwini Kumar",
    text: "I want more end-to-end ownership over the system.",
    start_sec: 188,
    end_sec: 193,
    source: "extension",
  },
  last_verdict: { candidate_id: "P1", confidence: 0.91, is_decision: true, ts: 205 },
  fallback_only_mode: false,
  transcript_source_active: true,
  audio_mapping_coverage: 1,
  transcribing_lag: false,
  per_participant_mode: true,
  transcript_coverage: {
    total_segments: 9,
    caption_active: true,
    transcribing_lag: false,
  },
  role_summary: {
    total_participants: 3,
    roles: [
      { participant_id: "P1", display_name: "Ashwini Kumar", role: "candidate", confidence: 0.91 },
      { participant_id: "P3", display_name: "Priya Sharma", role: "interviewer", confidence: 0.31 },
      { participant_id: "P2", display_name: "MacBook Pro", role: "observer", confidence: 0.1 },
    ],
  },
  recent_events: [
    {
      ts: 181,
      kind: "control",
      message: "PARTICIPANT_RENAMED",
      payload: { participant_id: "P1", old_name: "MacBook", new_name: "Ashwini Kumar" },
    },
  ],
};

const happyPathVerdict: Verdict = {
  session_id: "eval-happy-path",
  ts: 205,
  platform: "mock",
  candidate_id: "P1",
  candidate_name: "Ashwini Kumar",
  confidence: 0.91,
  runner_up_id: "P3",
  runner_up_confidence: 0.31,
  margin: 0.6,
  reasons: [
    "Email matched calendar metadata (+0.300)",
    "Transcript role indicates repeated interviewer-to-candidate Q&A (+0.225)",
    "Speaking pattern matched candidate turn-taking (+0.120)",
    "Screen share activity aligned with candidate workflow (+0.045)",
  ],
  rejected_hypotheses: [
    {
      participant_id: "P3",
      display_name: "Priya Sharma",
      confidence: 0.31,
      top_negative_reasons: [
        "Transcript role indicates interviewer behavior",
        "Asked most of the recent questions",
      ],
    },
    {
      participant_id: "P2",
      display_name: "MacBook Pro",
      confidence: 0.1,
      top_negative_reasons: [
        "Display name looked like a device name",
        "No meaningful speaking activity was observed",
      ],
    },
  ],
  is_decision: true,
  not_deciding_reason: null,
  analyzer_count: 6,
  total_evidence: 12,
  engine_version: "v1-weighted",
};

const renamedCandidateVerdict: Verdict = {
  session_id: "eval-renamed-candidate",
  ts: 205,
  platform: "mock",
  candidate_id: "P1",
  candidate_name: "Ashwini Kumar",
  confidence: 0.79,
  runner_up_id: "P3",
  runner_up_confidence: 0.33,
  margin: 0.46,
  reasons: [
    "Candidate metadata still matches the same participant despite a display-name change",
    "Transcript role remained candidate-leaning after the rename",
    "Speaking pattern stayed consistent with interviewer-to-candidate alternation",
  ],
  rejected_hypotheses: [
    {
      participant_id: "P3",
      display_name: "Priya Sharma",
      confidence: 0.33,
      top_negative_reasons: [
        "Question-leading behavior suggests interviewer role",
        "No candidate email match",
      ],
    },
  ],
  is_decision: true,
  not_deciding_reason: null,
  analyzer_count: 5,
  total_evidence: 10,
  engine_version: "v1-weighted",
};

const ambiguousVerdict: Verdict = {
  session_id: "eval-ambiguous",
  ts: 95,
  platform: "mock",
  candidate_id: "P1",
  candidate_name: "Ashwini Kumar",
  confidence: 0.42,
  runner_up_id: "P2",
  runner_up_confidence: 0.39,
  margin: 0.03,
  reasons: [
    'Top candidate so far: P1 "Ashwini Kumar" (0.42)',
    "Name and email signals are missing for both similar participants",
    "Need more interviewer-to-candidate turns before committing",
  ],
  rejected_hypotheses: [
    {
      participant_id: "P2",
      display_name: "Ashwini Kumar",
      confidence: 0.39,
      top_negative_reasons: [
        "Insufficient transcript separation from P1",
        "No unique metadata available",
      ],
    },
  ],
  is_decision: false,
  not_deciding_reason: "margin 0.03 < required 0.20",
  analyzer_count: 4,
  total_evidence: 6,
  engine_version: "v1-weighted",
};

const scenarios: Record<EvalScenarioId, EvalScenario> = {
  happy_path: {
    id: "happy_path",
    label: "Happy Path",
    description: "All major signals are present and the candidate separates early.",
    verdict: happyPathVerdict,
    liveDebug: {
      ...baseLiveDebug,
      session_id: "eval-happy-path",
      last_verdict: {
        candidate_id: happyPathVerdict.candidate_id,
        confidence: happyPathVerdict.confidence,
        is_decision: true,
        ts: happyPathVerdict.ts,
      },
    },
    history: [
      { ts: 0, P1: 0.05, P3: 0.03, P2: 0.02 },
      { ts: 30, P1: 0.24, P3: 0.12, P2: 0.04 },
      { ts: 60, P1: 0.49, P3: 0.18, P2: 0.06 },
      { ts: 120, P1: 0.73, P3: 0.27, P2: 0.08 },
      { ts: 205, P1: 0.91, P3: 0.31, P2: 0.1 },
    ],
  },
  renamed_candidate: {
    id: "renamed_candidate",
    label: "Incorrect Name",
    description: "The display name changes mid-session, but the system should stay on the same person.",
    verdict: renamedCandidateVerdict,
    liveDebug: {
      ...baseLiveDebug,
      session_id: "eval-renamed-candidate",
      last_verdict: {
        candidate_id: renamedCandidateVerdict.candidate_id,
        confidence: renamedCandidateVerdict.confidence,
        is_decision: true,
        ts: renamedCandidateVerdict.ts,
      },
    },
    history: [
      { ts: 0, P1: 0.08, P3: 0.04 },
      { ts: 60, P1: 0.62, P3: 0.22 },
      { ts: 120, P1: 0.82, P3: 0.28 },
      { ts: 180, P1: 0.57, P3: 0.31 },
      { ts: 205, P1: 0.79, P3: 0.33 },
    ],
  },
  ambiguous: {
    id: "ambiguous",
    label: "Ambiguous",
    description: "Missing metadata and similar participants should keep the system in a non-decision state.",
    verdict: ambiguousVerdict,
    liveDebug: {
      ...baseLiveDebug,
      session_id: "eval-ambiguous",
      last_verdict: {
        candidate_id: ambiguousVerdict.candidate_id,
        confidence: ambiguousVerdict.confidence,
        is_decision: false,
        ts: ambiguousVerdict.ts,
      },
      role_summary: {
        total_participants: 3,
        roles: [
          { participant_id: "P1", display_name: "Ashwini Kumar", role: "unclear", confidence: 0.42 },
          { participant_id: "P2", display_name: "Ashwini Kumar", role: "unclear", confidence: 0.39 },
          { participant_id: "P3", display_name: "Observer", role: "observer", confidence: 0.08 },
        ],
      },
    },
    history: [
      { ts: 0, P1: 0.03, P2: 0.03, P3: 0.02 },
      { ts: 30, P1: 0.18, P2: 0.17, P3: 0.04 },
      { ts: 60, P1: 0.31, P2: 0.28, P3: 0.06 },
      { ts: 95, P1: 0.42, P2: 0.39, P3: 0.08 },
    ],
  },
};

export function getEvalScenario(id: string | null | undefined): EvalScenario {
  if (id === "renamed_candidate" || id === "ambiguous" || id === "happy_path") {
    return scenarios[id];
  }
  return scenarios.happy_path;
}
