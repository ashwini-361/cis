// Verbatim worked examples from docs/DATA_CONTRACT.md §5.3, used across
// component tests instead of a live WebSocket.
import type { Verdict } from "./types";

export const decidableVerdict: Verdict = {
  session_id: "sess_1",
  ts: 300.4,
  platform: "zoom",
  candidate_id: "P1",
  candidate_name: "Ashwini",
  confidence: 0.97,
  runner_up_id: "P3",
  runner_up_confidence: 0.45,
  margin: 0.52,
  is_decision: true,
  reasons: [
    "Email matched calendar metadata (+0.300)",
    "Transcript role: answered 8 of 9 interviewer questions (+0.225)",
    "Display name similarity 96% (+0.144)",
    "Speaking pattern matched candidate turn-taking (+0.120)",
    "Webcam active throughout meeting (+0.050)",
    "Screen-shared IDE / resume (+0.045)",
    "Joined first — typical candidate behavior (+0.030)",
  ],
  rejected_hypotheses: [
    {
      participant_id: "P3",
      display_name: "Priya Sharma",
      confidence: 0.45,
      top_negative_reasons: [
        "Transcript role strongly indicates interviewer (+0.225 to interviewer-role signal)",
        "Email not provided by platform",
      ],
    },
    {
      participant_id: "P2",
      display_name: "MacBook Pro",
      confidence: 0.1,
      top_negative_reasons: [
        "Display name similarity 5% (likely device name)",
        "No Q&A participation in transcript",
        "No screen-share activity",
      ],
    },
  ],
  analyzer_count: 6,
  total_evidence: 11,
  engine_version: "v1-weighted",
  not_deciding_reason: null,
};

export const notDecidingVerdict: Verdict = {
  session_id: "sess_1",
  ts: 12.3,
  platform: "zoom",
  candidate_id: null,
  candidate_name: null,
  confidence: null,
  runner_up_id: "P1",
  runner_up_confidence: 0.42,
  margin: null,
  is_decision: false,
  not_deciding_reason: "top confidence 0.42 < threshold 0.55",
  reasons: [
    'Top candidate so far: P1 "Ashwini" (0.42)',
    "Awaiting transcript role evidence (transcript not yet available)",
    "Awaiting more Q&A turns for behavioral signals",
  ],
  rejected_hypotheses: [],
  analyzer_count: 4,
  total_evidence: 5,
  engine_version: "v1-weighted",
};
