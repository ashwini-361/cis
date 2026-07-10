// Verbatim worked examples from docs/DATA_CONTRACT.md §5.3, used across
// component tests instead of a live WebSocket.
import type { SessionUpdateMessage, Verdict } from "./types";

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
    "Joined first - typical candidate behavior (+0.030)",
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
  candidate_id: "P1",
  candidate_name: "Ashwini",
  confidence: 0.42,
  runner_up_id: "P3",
  runner_up_confidence: 0.38,
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

export const sessionUpdateMessage: SessionUpdateMessage = {
  kind: "session_update",
  session_id: "sess_1",
  verdict: decidableVerdict,
  live_debug: {
    session_id: "sess_1",
    extension_connected: true,
    extension_connections: 1,
    control_messages: 3,
    audio_chunks: 5,
    transcript_segments: 2,
    verdict_count: 1,
    last_control_type: "PARTICIPANT_JOINED",
    last_control_payload: { participant_id: "P1" },
    last_audio: { participant_id: "P1", start_sec: 0, end_sec: 25, size_bytes: 1000 },
    last_transcript: { participant_id: "P1", text: "hello", source: "extension" },
    last_verdict: { candidate_id: "P1", confidence: 0.97, is_decision: true, ts: 300.4 },
    fallback_only_mode: false,
    transcript_source_active: true,
    audio_mapping_coverage: 1,
    transcribing_lag: false,
    per_participant_mode: true,
    transcript_coverage: {
      total_segments: 2,
      caption_active: true,
      transcribing_lag: false,
    },
    role_summary: {
      total_participants: 1,
      roles: [
        {
          participant_id: "P1",
          display_name: "Ashwini",
          role: "candidate",
          confidence: 0.97,
        },
      ],
    },
    recent_events: [],
  },
};
