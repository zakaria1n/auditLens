import { useCallback, useEffect, useState } from 'react'

import { API_BASE } from '../../lib/api'

export interface CoverageControl {
  control_id: string
  title: string
  status: string
  criterion_version: string | null
  assessment: { result: string; criterion_version: string; evidence_refs: string[] } | null
  findings_count: number
  findings_pending_review: number
  blocked: boolean
  evidence_refs: string[]
  notes: string[]
}

export interface Coverage {
  mission_id: string
  controls: CoverageControl[]
  summary: { total: number; assessed: number; findings_related: number; blocked: number; not_tested: number }
}

const STATUS_STYLE: Record<string, { cls: string; label: string }> = {
  assessed_pass: { cls: 'bg-emerald-50 text-emerald-700', label: 'évalué — conforme' },
  assessed_fail: { cls: 'bg-red-50 text-red-700', label: 'évalué — non conforme' },
  assessed_insufficient: { cls: 'bg-amber-50 text-amber-700', label: 'preuves insuffisantes' },
  findings_without_assessment: { cls: 'bg-amber-50 text-amber-700', label: 'constats sans assessment' },
  not_applicable: { cls: 'bg-slate-100 text-slate-500', label: 'non applicable' },
  needs_review: { cls: 'bg-indigo-50 text-indigo-700', label: 'revue requise' },
  not_tested: { cls: 'bg-slate-100 text-slate-500', label: 'non testé' },
}

/** Audit Coverage Map (Phase 5/10) : couverture RÉELLE depuis le backend. */
export function useCoverage(missionId: string | null) {
  const [coverage, setCoverage] = useState<Coverage | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    if (!missionId) return
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/missions/${missionId}/coverage`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setCoverage((await res.json()) as Coverage)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'chargement impossible')
    }
  }, [missionId])

  useEffect(() => {
    void reload()
  }, [reload])

  return { coverage, error, reload }
}

export function CoverageMap({
  coverage,
  onOpenEvidence,
  missionId,
}: {
  coverage: Coverage
  onOpenEvidence?: (evidenceId: string, missionId: string) => void
  missionId: string
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-1.5 text-[11px]">
        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-slate-600">{coverage.summary.total} contrôles</span>
        <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-emerald-700">{coverage.summary.assessed} évalué(s)</span>
        {coverage.summary.findings_related > 0 && (
          <span className="rounded-md bg-amber-50 px-2 py-0.5 text-amber-700">{coverage.summary.findings_related} avec constats</span>
        )}
        {coverage.summary.blocked > 0 && (
          <span className="rounded-md bg-red-50 px-2 py-0.5 text-red-700">{coverage.summary.blocked} bloqué(s)</span>
        )}
        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-slate-500">{coverage.summary.not_tested} non testé(s)</span>
      </div>
      {coverage.controls.map((c) => {
        const style = STATUS_STYLE[c.status] ?? STATUS_STYLE.not_tested
        return (
          <div key={c.control_id} className="rounded-xl bg-slate-50 px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <p className="truncate text-[13px] font-medium text-slate-700">
                {c.control_id} — {c.title}
              </p>
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${style.cls}`}>{style.label}</span>
            </div>
            {c.notes.length > 0 && (
              <ul className="mt-1 space-y-0.5">
                {c.notes.map((n) => (
                  <li key={n} className="text-[11px] leading-snug text-slate-500">{n}</li>
                ))}
              </ul>
            )}
            {c.evidence_refs.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {c.evidence_refs.map((ref) => (
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
          </div>
        )
      })}
      <p className="text-[10px] leading-relaxed text-slate-400">
        « non testé » signifie aucun test exécuté — jamais un pass. Aucun score global n'est
        produit : chaque contrôle est lu individuellement.
      </p>
    </div>
  )
}
