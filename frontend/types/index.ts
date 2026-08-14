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
}
