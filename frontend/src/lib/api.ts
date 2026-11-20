/**
 * Client fetch typé vers le backend FastAPI (docs/CONTRAT_API_IMPL.md).
 * Aucun secret n'est stocké côté frontend au-delà de l'envoi immédiat.
 */

import type { ReportListItem } from './chatReports'
import type {
  Assessment,
  AuditMission,
  AuditPlan,
  AuditRun,
  Control,
  EvidenceFull,
  EvidenceMeta,
  Finding,
  LLMConfigBody,
  LLMConfigResponse,
  MissionLimits,
  ReportSnapshot,
  RuleSet,
  RunEvent,
  RunStatus,
  SourceConnection,
  ToolCallRecord,
} from './types'

export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const body = init?.body
  const headers: Record<string, string> = {}
  if (body != null && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const data: unknown = await res.json()
      if (
        data !== null &&
        typeof data === 'object' &&
        'detail' in data &&
        (typeof data.detail === 'string' || data.detail != null)
      ) {
        detail =
          typeof data.detail === 'string'
            ? data.detail
            : JSON.stringify(data.detail)
      }
    } catch {
      // corps non JSON : on garde le message par défaut
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

// ---- Santé & catalogues ----

export function getHealth() {
  return request<{ status: string; service: string; version: string }>('/api/health')
}

export function listControls() {
  return request<{ controls: Control[] }>('/api/missions/catalog/controls')
}

export function listRuleSets() {
  return request<{ rule_sets: RuleSet[] }>('/api/missions/catalog/rulesets')
}

// ---- Sources ----

export interface SourceCreateBody {
  name: string
  type: 'odoo' | 'api' | 'web'
  config: Record<string, unknown>
  secrets?: Record<string, unknown>
}

export function createSource(body: SourceCreateBody) {
  return request<{ source: SourceConnection }>('/api/sources', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function uploadFileSource(name: string, ruleSetId: string, file: File) {
  const qs = new URLSearchParams({ name })
  if (ruleSetId) qs.set('rule_set_id', ruleSetId)
  const fd = new FormData()
  fd.append('file', file)
  return request<{ source: SourceConnection; evidence_id: string | null }>(
    `/api/sources/file?${qs.toString()}`,
    { method: 'POST', body: fd },
  )
}

export function listSources() {
  return request<{ sources: SourceConnection[] }>('/api/sources')
}

export function testSource(id: string) {
  return request<{ ok: boolean; message?: string; error?: string; source?: SourceConnection }>(
    `/api/sources/${id}/test`,
    { method: 'POST' },
  )
}

export function deleteSource(id: string) {
  return request<{ deleted: boolean }>(`/api/sources/${id}`, { method: 'DELETE' })
}

// ---- Missions ----

export interface MissionCreateBody {
  title: string
  objective: string
  source_ids: string[]
  control_ids: string[]
  time_range: { from?: string | null; to?: string | null }
  limits?: Partial<MissionLimits>
}

export function createMission(body: MissionCreateBody) {
  return request<{ mission: AuditMission }>('/api/missions', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function listMissions() {
  return request<{ missions: AuditMission[] }>('/api/missions')
}

export function getMission(id: string) {
  return request<{ mission: AuditMission }>(`/api/missions/${id}`)
}

export function proposePlan(id: string) {
  return request<{ plan: AuditPlan }>(`/api/missions/${id}/plan`, { method: 'POST' })
}

export function approvePlan(id: string, plan: Record<string, unknown>, note: string) {
  return request<{ mission: AuditMission }>(`/api/missions/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ plan, note }),
  })
}

export interface RunBody {
  provider?: string
  model?: string
  scenario?: string
}

export function startRun(id: string, body: RunBody = {}) {
  return request<{ run_id: string; status: RunStatus | string }>(
    `/api/missions/${id}/run`,
    { method: 'POST', body: JSON.stringify(body) },
  )
}

export function missionEvidence(id: string) {
  return request<{ evidence: EvidenceMeta[] }>(`/api/missions/${id}/evidence`)
}

// ---- Runs & résultats ----

export function listRuns(missionId?: string) {
  const qs = missionId ? `?mission_id=${encodeURIComponent(missionId)}` : ''
  return request<{ runs: AuditRun[] }>(`/api/runs${qs}`)
}

export function getRun(id: string) {
  return request<{ run: AuditRun }>(`/api/runs/${id}`)
}

export function listToolCalls(runId: string) {
  return request<{ tool_calls: ToolCallRecord[] }>(`/api/runs/${runId}/tool-calls`)
}

export function runEvidence(runId: string) {
  return request<{ evidence: EvidenceMeta[] }>(`/api/runs/${runId}/evidence`)
}

export function runAssessments(runId: string) {
  return request<{ assessments: Assessment[] }>(`/api/runs/${runId}/assessments`)
}

export function runFindings(runId: string) {
  return request<{ findings: Finding[] }>(`/api/runs/${runId}/findings`)
}

export interface OpencodeFreeModel {
  id: string
  name: string
  context: number | null
  structured_output: boolean
}

export function listOpencodeFreeModels() {
  return request<{ ok: boolean; models: OpencodeFreeModel[]; error?: string }>(
    '/api/settings/llm/opencode/models',
  )
}

export interface ProviderModel {
  id: string
  name: string
}

/** Modèles pour un provider : LIVE depuis l'API du provider quand une clé
 * est disponible (référence absolue), sinon suggestions statiques vérifiées.
 * source: 'live' | 'curated' | 'none' ; warning présent si le live a échoué. */
export function listProviderModels(provider: string, apiKey?: string, baseUrl?: string | null) {
  const params = new URLSearchParams({ provider })
  if (apiKey) params.set('api_key', apiKey)
  if (baseUrl) params.set('base_url', baseUrl)
  return request<{
    ok: boolean; provider: string; source: string
    models: ProviderModel[]; note: string; warning?: string; detail?: string
  }>(`/api/settings/llm/models?${params.toString()}`)
}

export function listReports(q?: string) {
  const suffix = q ? `?q=${encodeURIComponent(q)}` : ''
  return request<{ reports: ReportListItem[] }>(`/api/reports${suffix}`)
}

export function runReport(runId: string) {
  return request<{ report: ReportSnapshot }>(`/api/runs/${runId}/report`)
}

export function runEventsUrl(runId: string, after = 0) {
  return `${API_BASE}/api/runs/${runId}/events?after=${after}`
}

export type { RunEvent }

// ---- Evidence & Findings ----

export function getEvidence(id: string, missionId: string) {
  return request<{ evidence: EvidenceFull; payload: unknown }>(
    `/api/evidence/${id}?mission_id=${encodeURIComponent(missionId)}`,
  )
}

export function listFindings(params: { run_id?: string; mission_id?: string }) {
  const qs = new URLSearchParams()
  if (params.run_id) qs.set('run_id', params.run_id)
  if (params.mission_id) qs.set('mission_id', params.mission_id)
  return request<{ findings: Finding[] }>(`/api/findings?${qs.toString()}`)
}

export function reviewFinding(
  id: string,
  decision: 'accepted' | 'rejected' | 'needs_more_evidence',
  reason: string,
) {
  return request<{ finding: Finding }>(`/api/findings/${id}/review`, {
    method: 'POST',
    body: JSON.stringify({ decision, reason }),
  })
}

// ---- Settings LLM (BYOK) ----

export function getLLMConfig() {
  return request<LLMConfigResponse>('/api/settings/llm')
}

export function selectLLMModel(provider: string, model: string) {
  return request<{ provider: string; model: string }>('/api/settings/llm/model', {
    method: 'PATCH', body: JSON.stringify({ provider, model }),
  })
}

export function setLLMConfig(body: LLMConfigBody) {
  return request<{ ok: boolean; provider: string; model: string }>('/api/settings/llm', {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

export function testLLMConfig(body?: LLMConfigBody) {
  return request<{ ok: boolean; message?: string; error?: string; provider?: string }>(
    '/api/settings/llm/test',
    {
      method: 'POST',
      body: body == null ? JSON.stringify(null) : JSON.stringify(body),
    },
  )
}

// ---- Contrôle d'investigation (ADR-15 : pause / reprise / budget) ----

export function steerRun(runId: string, instruction: string) {
  return request<{ steering: { id: string; status: string } }>(
    `/api/runs/${runId}/steer`,
    { method: 'POST', body: JSON.stringify({ instruction }) },
  )
}

export function pauseRun(id: string) {
  return request<{ ok: boolean }>(`/api/runs/${id}/pause`, { method: 'POST' })
}

export function stopRun(id: string) {
  return request<{ ok: boolean }>(`/api/runs/${id}/stop`, { method: 'POST' })
}

export function resumeRun(id: string) {
  return request<{ run_id: string; resumed_from: string; checkpoint_id: string }>(
    `/api/runs/${id}/resume`,
    { method: 'POST' },
  )
}

export function extendBudget(missionId: string, addToolCalls: number, addSeconds: number) {
  return request<{ mission: AuditMission }>(`/api/missions/${missionId}/extend-budget`, {
    method: 'POST',
    body: JSON.stringify({ add_tool_calls: addToolCalls, add_seconds: addSeconds }),
  })
}

export function getCheckpoint(runId: string) {
  return request<{ checkpoint: Record<string, unknown> | null }>(`/api/runs/${runId}/checkpoint`)
}
