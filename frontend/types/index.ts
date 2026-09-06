export interface SourceLocation {
  sheet_name?: string;
  column_letter?: string;
  row?: number;
  source?: string;
}

export interface RuleFlag {
  violation_type: string;
  reason: string;
}

export interface EarsPattern {
  pattern: string;
  confidence?: number;
  reason?: string;
}

export interface FailedRule {
  id: string;
  title: string;
  reasons: string[];
}

export interface Candidate {
  index: number;
  rewritten_text: string;
  score: number;
  has_invented_number: boolean;
  failed_rules?: FailedRule[];
}

export interface VagueTermSuggestion {
  term: string;
  suggestion: string;
}

// A row's lifecycle: "analyzed" right after upload (deterministic only,
// no LLM yet) -> a human clicks Generate ("generating" while the LLM call
// is in flight, then "generated", or "failed" if the call errored) or
// types a replacement themselves ("edited", no LLM involved). Never moves
// backwards automatically -- see src/storage/db.py's REQUIREMENT_STATUSES.
export type RequirementStatus = "analyzed" | "generating" | "generated" | "edited" | "failed";

// "not_computed" until a human clicks "Check Accurate Score" for this row
// (see src/rules/incose_ai_scorer.py); "computing" while that one LLM call
// is in flight, then "done"/"failed" -- same lifecycle shape as
// RequirementStatus's generating -> generated/failed, just for this
// separate, opt-in 42-rule score rather than the default 28-rule one.
export type AccurateScoreStatus = "not_computed" | "computing" | "done" | "failed";

export interface Requirement {
  id?: number | string;
  sequence_in_run: number;
  original_text: string;
  source_location?: SourceLocation;
  ears_pattern: EarsPattern;
  rule_flags: RuleFlag[];
  candidates: Candidate[];
  recommended_index: number;
  recommended_score: number;
  recommended_text?: string;
  needs_human_review: boolean;
  compliance_threshold?: number;
  vague_term_suggestions: VagueTermSuggestion[];
  status: RequirementStatus;
  violations: FailedRule[];
  error_message?: string | null;
  // On-demand 42-rule score: recommended_score/violations above only ever
  // cover the 28 automatable INCOSE rules -- these fields stay
  // "not_computed"/null/[] until a human explicitly asks for the more
  // expensive, LLM-assisted 42-rule check.
  accurate_score_status: AccurateScoreStatus;
  accurate_score?: number | null;
  accurate_violations?: FailedRule[];
  accurate_score_error_message?: string | null;
}

export interface Run {
  id: number;
  file_name: string;
  file_path: string;
  file_size_bytes?: number;
  sha256?: string;
  uploaded_at: string;
  requirement_count: number;
  total_requirements: number;
  status: "pending" | "processing" | "completed" | "failed";
  error_message?: string | null;
}

export interface HealthResponse {
  status: string;
  model: string;
}

export interface UploadResponse {
  run_id: number;
  status: string;
}

export interface RequirementDetail {
  id: number;
  sequence_in_run: number;
  recommended_text: string;
  original_text: string;
  display_id?: number;
}

export interface RequirementRelationship {
  id: number;
  run_id: number;
  req_id_1: number;
  req_id_2: number;
  relationship_type: "duplicate" | "similar" | "contradiction" | "independent";
  similarity_score: number;
  confidence: number;
  reason: string | null;
  created_at: string;
  req_1?: RequirementDetail;
  req_2?: RequirementDetail;
}

export interface ConsistencySummary {
  duplicate: number;
  similar: number;
  contradiction: number;
  independent: number;
}

export interface ConsistencyResponse {
  run_id: number;
  total_requirements: number;
  summary: ConsistencySummary;
  relationships: RequirementRelationship[];
  // Both null => consistency analysis has never run for this run (an
  // empty relationships list alone can't tell that apart from "ran and
  // found nothing"). consistency_analyzed_at set + consistency_last_error
  // set => the last analysis attempt crashed; do not read the summary
  // above as a real 100%-consistent result in that case.
  consistency_analyzed_at: string | null;
  consistency_last_error: string | null;
}

export interface StageEvent {
  seq: number;
  ts: string;
  requirement_index: number;
  stage: string;
  message: string;
  status: "running" | "done" | "failed";
}

export interface RunProgress {
  current_requirement_index: number | null;
  current_stage: string | null;
  events: StageEvent[];
}

export interface EmbeddingPair {
  req_id_1: number;
  req_id_2: number;
  req_1_number: number;
  req_2_number: number;
  similarity: number;
  distance: number;
  angle_degrees: number;
}

export interface EmbeddingMatrixResponse {
  pairs: EmbeddingPair[];
  method: "sentence-transformers" | "tfidf";
  total_requirements: number;
}
