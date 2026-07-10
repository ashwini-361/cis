// Mirrors app/schema.py's Verdict/RejectedHypothesis (docs/DATA_CONTRACT.md §5).
// Kept as a hand-written mirror rather than a generated type since the
// backend has no OpenAPI/schema-export step yet.

export interface RejectedHypothesis {
  participant_id: string;
  display_name: string;
  confidence: number;
  top_negative_reasons: string[];
}

export interface Verdict {
  session_id: string;
  ts: number;
  platform: string;
  candidate_id: string | null;
  candidate_name: string | null;
  confidence: number | null;
  runner_up_id: string | null;
  runner_up_confidence: number | null;
  margin: number | null;
  reasons: string[];
  rejected_hypotheses: RejectedHypothesis[];
  is_decision: boolean;
  not_deciding_reason: string | null;
  analyzer_count: number;
  total_evidence: number;
  engine_version: string;
}

export interface LiveDebugEvent {
  ts: number;
  kind: string;
  message: string;
  payload: Record<string, unknown>;
}

export interface RoleSummaryEntry {
  participant_id: string;
  display_name: string;
  role: string;
  confidence: number;
}

export interface LiveDebugSnapshot {
  session_id: string;
  extension_connected: boolean;
  extension_connections: number;
  control_messages: number;
  audio_chunks: number;
  transcript_segments: number;
  verdict_count: number;
  last_control_type: string | null;
  last_control_payload: Record<string, unknown> | null;
  last_audio: Record<string, unknown> | null;
  last_transcript: Record<string, unknown> | null;
  last_verdict: Record<string, unknown> | null;
  fallback_only_mode: boolean;
  transcript_source_active: boolean;
  audio_mapping_coverage: number;
  transcribing_lag: boolean;
  per_participant_mode?: boolean;
  transcript_coverage?: {
    total_segments: number;
    caption_active: boolean;
    transcribing_lag: boolean;
  };
  role_summary?: {
    total_participants: number;
    roles: RoleSummaryEntry[];
  };
  recent_events: LiveDebugEvent[];
}

export interface SessionUpdateMessage {
  kind: "session_update";
  session_id: string;
  verdict: Verdict | null;
  live_debug: LiveDebugSnapshot | null;
}
