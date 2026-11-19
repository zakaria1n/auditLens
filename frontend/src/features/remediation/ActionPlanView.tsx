import { useCallback, useEffect, useState } from 'react'

import { API_BASE } from '../../lib/api'

export interface PlanAction {
  id: string
  description: string
  priority: string
  status: 'proposed' | 'accepted' | 'in_progress' | 'ready_to_verify' | 'verified' | 'not_verified'
  owner: string | null
  verification_evidence_ids: string[]
  history: { from: string; to: string; by: string; evidence_ids?: string[] }[]
}

export interface ActionPlan {
  finding_id: string
  actions: PlanAction[]
  note: string
}

const STATUS_STYLE: Record<PlanAction['status'], { cls: string; label: string }> = {
  proposed: { cls: 'bg-slate-100 text-slate-600', label: 'proposée' },
  accepted: { cls: 'bg-indigo-50 text-indigo-700', label: 'acceptée' },
  in_progress: { cls: 'bg-amber-50 text-amber-700', label: 'en cours' },
  ready_to_verify: { cls: 'bg-violet-50 text-violet-700', label: 'prête à vérifier' },
  verified: { cls: 'bg-emerald-50 text-emerald-700', label: 'vérifiée' },
  not_verified: { cls: 'bg-red-50 text-red-700', label: 'non vérifiée' },
}

const TRANSITIONS: Record<PlanAction['status'], PlanAction['status'][]> = {
  proposed: ['accepted'],
  accepted: ['in_progress'],
  in_progress: ['ready_to_verify'],
  ready_to_verify: [],
  verified: [],
  not_verified: ['in_progress'],
}

/**
 * Finding Action Plan (Phase 3/10) : rend le plan RÉEL du backend
 * (GET/POST /api/findings/{id}/action-plan). Transitions humaines tracées ;
 * « verified » jamais posé à la main — seul un run de vérification avec preuve.
 */
export function useActionPlan(findingId: string | null) {
  const [plan, setPlan] = useState<ActionPlan | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    if (!findingId) return
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/findings/${findingId}/action-plan`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setPlan(data.plan as ActionPlan)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'chargement impossible')
    }
  }, [findingId])

  useEffect(() => {
    void reload()
  }, [reload])

  const transition = useCallback(async (actionId: string, status: PlanAction['status']) => {
    const res = await fetch(`${API_BASE}/api/findings/${findingId}/action-plan/transition`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action_id: actionId, status }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`)
    setPlan(data.plan as ActionPlan)
  }, [findingId])

  return { plan, error, reload, transition }
}

export function ActionPlanView({
  findingId,
  missionId,
  onOpenEvidence,
  onVerifyFix,
}: {
  findingId: string
  missionId: string
  onOpenEvidence?: (evidenceId: string, missionId: string) => void
  onVerifyFix?: (findingId: string) => void
}) {
  const { plan, error, transition } = useActionPlan(findingId)
  const [actionErr, setActionErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const doTransition = async (actionId: string, status: PlanAction['status']) => {
    setBusy(true)
    setActionErr(null)
    try {
      await transition(actionId, status)
    } catch (err) {
      setActionErr(err instanceof Error ? err.message : 'échec de la transition')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-2 rounded-xl border border-slate-200/80 bg-slate-50/70 px-3 py-2.5">
      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
        Plan d'action de remédiation
      </p>
      {error && <p className="text-xs text-red-600">{error}</p>}
      {plan?.actions.map((a) => {
        const style = STATUS_STYLE[a.status]
        const nextStatuses = TRANSITIONS[a.status] ?? []
        return (
          <div key={a.id} className="mb-2 rounded-lg bg-white px-2.5 py-2 last:mb-0">
            <p className="flex flex-wrap items-center gap-1.5">
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${style.cls}`}>{style.label}</span>
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">{a.priority}</span>
            </p>
            <p className="mt-1 text-[13px] leading-snug text-slate-700">{a.description}</p>
            {a.verification_evidence_ids.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {a.verification_evidence_ids.map((ref) => (
                  <button
                    key={ref}
                    type="button"
                    onClick={() => onOpenEvidence?.(ref, missionId)}
                    className="rounded bg-violet-50 px-1 py-0.5 font-mono text-[10px] text-violet-700 hover:bg-violet-100"
                  >
                    {ref}
                  </button>
                ))}
              </div>
            )}
            {nextStatuses.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {nextStatuses.map((next) => (
                  <button
                    key={next}
                    type="button"
                    disabled={busy}
                    onClick={() => void doTransition(a.id, next)}
                    className="rounded-md border border-slate-200 px-2 py-0.5 text-[11px] font-medium text-slate-600 hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-40"
                  >
                    → {STATUS_STYLE[next].label}
                  </button>
                ))}
                {a.status === 'ready_to_verify' && onVerifyFix && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onVerifyFix(findingId)}
                    className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-40"
                  >
                    Lancer la vérification
                  </button>
                )}
              </div>
            )}
            {a.history.length > 0 && (
              <p className="mt-1 text-[10px] text-slate-400">
                {a.history.map((h) => `${h.from}→${h.to} (${h.by})`).join(' · ')}
              </p>
            )}
          </div>
        )
      })}
      {actionErr && <p className="mt-1 rounded-md bg-red-50 px-2 py-1 text-[11px] text-red-700">{actionErr}</p>}
      {plan?.note && <p className="mt-1.5 text-[10px] leading-snug text-slate-400">{plan.note}</p>}
    </div>
  )
}
