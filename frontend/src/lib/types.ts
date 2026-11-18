/**
 * Types TypeScript du contrat API AuditLens (docs/CONTRAT_API_IMPL.md,
 * miroir exact de backend/app/models/schemas.py).
 */

// ---- Sources ----

export type SourceType = 'odoo' | 'api' | 'web' | 'file'
export type SourceStatus = 'untested' | 'connected' | 'failed'

export interface SourceConnection {
  id: string
  workspace_id: string
  name: string
  type: SourceType
  config: Record<string, unknown>
  secrets_ref: string | null
  status: SourceStatus
  last_test_at: string | null
  last_test_message: string | null
  created_at: string
}

// ---- Missions ----

export interface MissionLimits {
  max_tool_calls: number
  max_seconds: number
  max_input_chars: number
  max_page_size: number
}

export type MissionStatus =
  | 'draft'
  | 'planned'
  | 'approved'
  | 'running'
  | 'completed'
  | 'failed'

export interface AuditPlanStep {
  id: string
  tool: string
  source_id: string | null
  args: Record<string, unknown>
  rationale: string
  requires_approval: boolean
}

export interface AuditPlan {
  id: string
  mission_id: string
  provider_id: string
  model_id: string
  steps: AuditPlanStep[]
  evidence_expected: string[]
  risks: string[]
  created_at: string
}

export interface AuditMission {
  id: string
  workspace_id: string
  title: string
  objective: string
  source_ids: string[]
  control_ids: string[]
  time_range: { from?: string | null; to?: string | null }
  limits: MissionLimits
  status: MissionStatus
  approved_plan: {
    plan_id?: string
    approved_actions?: { tool?: string; source_id?: string | null }[]
    note?: string
    approved_at?: string
  } | null
  created_at: string
}

// ---- Runs ----

export type RunStatus =
  | 'not_started'
  | 'awaiting_permission'
  | 'running'
  | 'needs_input'
  | 'paused'
  | 'cancelled'
  | 'partial'
  | 'failed'
  | 'completed'
  | 'review_required'

export interface AuditRun {
  id: string
  mission_id: string
  status: RunStatus
  provider_id: string
  model_id: string
  prompt_version: string
  tool_calls_used: number
  input_chars_used: number
  started_at: string | null
  finished_at: string | null
  stop_reason: string | null
  error: string | null
}

export type ToolCallStatus =
  | 'success'
  | 'error'
  | 'unauthorized'
  | 'partial'
  | 'insufficient_evidence'
  | 'blocked'

export interface ToolCallRecord {
  id: string
  run_id: string
  mission_id: string
  name: string
  source_id: string | null
  args: Record<string, unknown>
  status: ToolCallStatus
  latency_ms: number | null
  observed_at: string
  evidence_ids: string[]
  warnings: string[]
  error: string | null
}

// ---- Événements SSE ----

export type RunEventType =
  | 'run_started'
  | 'phase'
  | 'plan'
  | 'tool_started'
  | 'tool_completed'
  | 'evidence'
  | 'finding'
  | 'finding_rejected'
  | 'assessment'
  | 'warning'
  | 'run_completed'
  | 'run_failed'

export interface RunEvent {
  seq: number
  run_id: string
  type: RunEventType | string
  at: string
  data: Record<string, unknown>
}

// ---- Evidence ----

export interface EvidenceMeta {
  id: string
  mission_id: string
  run_id: string | null
  source_id: string | null
  type: string
  title: string
  observed_at: string
  provenance: Record<string, unknown>
  checksum: string
  storage_ref: string
  record_count: number | null
  summary: Record<string, unknown> | null
  payload: Record<string, unknown> | null
}

export interface EvidenceFull extends EvidenceMeta {
  integrity_verified: boolean
}

// ---- Assessments ----

export type AssessmentResult =
  | 'pass'
  | 'fail'
  | 'insufficient_evidence'
  | 'not_applicable'
  | 'not_tested'
  | 'error'
  | 'needs_review'

export interface Assessment {
  id: string
  run_id: string
  mission_id: string
  control_id: string
  criterion_version: string
  result: AssessmentResult
  evidence_refs: string[]
  observations: string[]
  method: string
  limitations: string[]
}

// ---- Findings ----

export type FindingStatus = 'needs_review' | 'accepted' | 'rejected' | 'needs_more_evidence'
export type Severity = 'info' | 'low' | 'medium' | 'high'

export interface AuditorReview {
  decision: 'accepted' | 'rejected' | 'needs_more_evidence'
  reviewer: string
  reason: string
  timestamp: string
}

export interface Finding {
  id: string
  run_id: string
  mission_id: string
  control_id: string | null
  title: string
  statement: string
  severity_proposed: Severity
  evidence_refs: string[]
  observations: string[]
  method: string
  limitations: string[]
  recommendations: string[]
  uncertainties: string[]
  status: FindingStatus
  review: AuditorReview | null
  rejection_reason: string | null
  created_at: string
}

// ---- Rapport ----

export interface ReportSnapshot {
  id: string
  run_id: string
  mission_id: string
  version: number
  created_at: string
  period: Record<string, string | null>
  sources: string[]
  assessed: string[]
  partial: string[]
  not_assessed: string[]
  findings_included: string[]
  findings_excluded: string[]
  limitations: string[]
  model_id: string
  provider_id: string
  prompt_version: string
  markdown: string
}

// ---- Catalogues ----

export interface Control {
  id: string
  version: string
  title: string
  source_types: string[]
  criterion: string
  expected_evidence: string[]
  method: string
}

export interface RuleSet {
  id: string
  name: string
  description: string
  contract_note: string
  rules: unknown[]
}

// ---- Settings LLM ----

export type LLMProvider = 'mock' | 'openai' | 'gemini' | 'anthropic' | 'deepseek' | 'compatible'

export interface LLMConfigResponse {
  provider: string
  model: string
  base_url: string | null
  key_configured: boolean
  source: string
  providers_available: string[]
  note: string
}

export interface LLMConfigBody {
  provider: string
  model?: string
  base_url?: string | null
  api_key?: string
}
