export type Origin = "document" | "user";

export interface Traced {
  id: string;
  origin: Origin;
  source_line: number | null;
  uncertain: boolean;
}
export interface Bullet extends Traced {
  text: string;
}
export interface Contact {
  name: string;
  email: string;
  phone: string;
  location: string;
  links: string[];
}
export interface SkillGroup extends Traced {
  category: string;
  items: string[];
}
export interface Experience extends Traced {
  employer: string;
  title: string;
  location: string;
  dates: string;
  bullets: Bullet[];
}
export interface Project extends Traced {
  name: string;
  tech: string;
  dates: string;
  link: string;
  bullets: Bullet[];
}
export interface Education extends Traced {
  institution: string;
  degree: string;
  location: string;
  dates: string;
  details: Bullet[];
}
export interface Certification extends Traced {
  name: string;
  issuer: string;
  date: string;
}
export interface OtherSection extends Traced {
  title: string;
  items: Bullet[];
}
export interface Profile {
  contact: Contact;
  summary: string;
  summary_origin: Origin;
  skills: SkillGroup[];
  experience: Experience[];
  projects: Project[];
  education: Education[];
  certifications: Certification[];
  other: OtherSection[];
}

export interface ResumeSummary {
  id: string;
  name: string;
  source_filename: string;
  source_kind: "tex" | "pdf" | "manual";
  version: number;
  verified: boolean;
  created_at: string;
  updated_at: string;
}
export interface Resume extends ResumeSummary {
  extracted_text: string;
  warnings: string[];
  issues: string[];
  profile: Profile;
}

export type ReqCategory =
  | "required_skill"
  | "preferred_skill"
  | "responsibility"
  | "experience"
  | "qualification"
  | "technology"
  | "terminology";
export type Importance = "must" | "important" | "nice";
export interface Requirement {
  id: string;
  text: string;
  category: ReqCategory;
  importance: Importance;
  keywords: string[];
  origin: "extracted" | "user";
}
export type MatchStatus = "supported" | "needs_confirmation" | "indirect" | "unsupported" | "unclear";
export interface MatchEvidence {
  evidence_id: string;
  excerpt: string;
  context: string;
  matched_terms: string[];
  strength: "demonstrated" | "claimed" | "related";
}
export interface RequirementMatch {
  requirement_id: string;
  status: MatchStatus;
  evidence: MatchEvidence[];
  matched_terms: string[];
  missing_terms: string[];
  note: string;
}
export interface MatchReport {
  matches: RequirementMatch[];
  score: { value: number; label: string; explanation: string; counts: Record<MatchStatus, number> };
}
export interface Flag {
  code: string;
  severity: "info" | "warning" | "blocker";
  message: string;
  terms: string[];
}
export type SuggestionStatus = "pending" | "accepted" | "modified" | "rejected" | "invalid";
export interface Suggestion {
  id: string;
  target_id: string;
  target_kind: "summary" | "bullet" | "skills";
  target_label: string;
  original_text: string;
  proposed_text: string;
  final_text: string | null;
  reason: string;
  requirement_ids: string[];
  evidence_ids: string[];
  confidence: "high" | "medium" | "low";
  flags: Flag[];
  requires_confirmation: boolean;
  confirmed: boolean;
  status: SuggestionStatus;
  invalid_reason: string;
  history: string[];
}
export interface ResumeConfig {
  target_role: string;
  section_order: string[];
  include_summary: boolean;
  include_projects: boolean;
  include_certifications: boolean;
  include_other: boolean;
  prioritized_skills: string[];
  max_pages: number;
  paper: "a4" | "letter";
  font_size: 10 | 11 | 12;
}
export interface Check {
  id: string;
  category: string;
  label: string;
  status: "pass" | "warn" | "fail" | "info";
  detail: string;
  items: string[];
}
export interface Validation {
  formatting: {
    checks: Check[];
    extracted_text: string;
    pages: number;
    ok: boolean;
    engine: string | null;
    disclaimer: string;
    tex_sha256: string;
    summary?: Record<string, number>;
  };
  qualification: {
    score: MatchReport["score"] | null;
    required_total: number;
    required_supported: number;
    gaps: { id: string; text: string; importance: Importance; missing_terms: string[] }[];
    needs_confirmation: { id: string; text: string; note: string }[];
    terminology: { present: string[]; documented_but_not_in_this_draft: string[]; not_documented: string[] };
    user_confirmed_claims: { id: string; target: string; text: string; flags: Flag[] }[];
    note: string;
  };
}
export interface EvidenceItem {
  id: string;
  kind: string;
  text: string;
  context: string;
  origin: Origin;
}
export interface Session {
  id: string;
  resume_id: string | null;
  job_title: string;
  employer: string;
  status: string;
  created_at: string;
  updated_at: string;
  resume_name: string;
  resume_version: number;
  profile: Profile;
  draft: Profile;
  evidence: EvidenceItem[];
  jd_text: string;
  analysis: { job_title: string; employer: string; requirements: Requirement[]; notes: string[] } | null;
  match: MatchReport | null;
  suggestions: Suggestion[];
  suggestion_counts: Record<SuggestionStatus, number>;
  ai_meta: Record<string, unknown>;
  config: ResumeConfig;
  generated: { tex_sha256: string; generated_at: string; stale: boolean } | null;
  compile: {
    ok: boolean;
    engine: string | null;
    seconds: number;
    error: string;
    log_excerpt: string;
    tex_sha256: string;
    compiled_at: string;
  } | null;
  validation: Validation | null;
  tex: string | null;
  has_pdf: boolean;
  status_labels: Record<MatchStatus, string>;
}
export interface SessionSummary {
  id: string;
  resume_id: string | null;
  job_title: string;
  employer: string;
  status: string;
  created_at: string;
  updated_at: string;
  resume_name: string;
  resume_version: number;
  match_score: number | null;
}
export interface SystemInfo {
  version: string;
  ai: {
    provider: string;
    model: string;
    configured: boolean;
    structured_output: string;
    setup_hint: string;
    consent: boolean;
    consent_at: string | null;
    privacy_notice: string;
  };
  toolchain: {
    engine: string | null;
    engine_version: string;
    available_engines: string[];
    pdftotext: boolean;
    can_compile: boolean;
    missing: { name: string; purpose: string; install: Record<string, string> }[];
    notes: string[];
  };
  limits: { max_upload_mb: number; compile_timeout_seconds: number };
  server: { host: string; port: number; local_only: boolean; access_token_required: boolean; data_dir: string };
  retention_days: number;
  counts: { resumes: number; sessions: number; generated_drafts: number };
}
