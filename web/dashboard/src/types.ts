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
