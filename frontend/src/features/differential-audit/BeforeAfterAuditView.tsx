import { useCallback, useEffect, useState } from 'react'

import { API_BASE } from '../../lib/api'

export interface DiffEntry {
  key: string
  status: 'persistent' | 'resolved' | 'new' | 'unknown'
  control_id: string
  base: { id: string; title: string; severity: string; status: string } | null
  target: { id: string; title: string; severity: string; status: string } | null
  explanation: string
}

export interface DiffResult {
  base_run_id: string
  target_run_id: string
  entries: DiffEntry[]
  summary: { base_total: number; target_total: number; persistent: number; resolved: number; new: number; unknown: number }
  note: string
}

const STATUS_STYLE: Record<DiffEntry['status'], { cls: string; label: string }> = {
  persistent: { cls: 'bg-red-50 text-red-700', label: 'persistant' },
  resolved: { cls: 'bg-emerald-50 text-emerald-700', label: 'résolu (ré-inspecté)' },
  new: { cls: 'bg-brand-50 text-brand-700', label: 'nouveau' },
  unknown: { cls: 'bg-slate-100 text-slate-600', label: 'incomparable' },
}

export function useRunDiff(missionId: string | null, baseRunId: string | null, targetRunId: string | null) {
  const [diff, setDiff] = useState<DiffResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    if (!missionId || !baseRunId || !targetRunId || baseRunId === targetRunId) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(
        `${API_BASE}/api/runs/${targetRunId}/diff?base=${encodeURIComponent(baseRunId)}`,
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setDiff((await res.json()) as DiffResult)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'chargement impossible')
    } finally {
      setLoading(false)
    }
  }, [missionId, baseRunId, targetRunId])

  useEffect(() => {
    void load()
  }, [load])

  return { diff, error, loading, reload: load }
}

/** Before / After Audit View (Phase 6/10) : statuts honnêtes, jamais « résolu » non prouvé. */
export function BeforeAfterAuditView({
  diff,
  onVerifyFix,
}: {
  diff: DiffResult
  onVerifyFix?: (controlId: string, findingTitle: string) => void
}) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5 text-[11px]">
        <span className="rounded-md bg-red-50 px-2 py-0.5 text-red-700">{diff.summary.persistent} persistant(s)</span>
        <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-emerald-700">{diff.summary.resolved} résolu(s)</span>
        <span className="rounded-md bg-brand-50 px-2 py-0.5 text-brand-700">{diff.summary.new} nouveau(x)</span>
        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-slate-600">{diff.summary.unknown} incomparable(s)</span>
      </div>

      {diff.entries.map((e) => {
        const style = STATUS_STYLE[e.status]
        return (
          <div key={`${e.status}-${e.key}`} className="rounded-xl bg-slate-50 px-3 py-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${style.cls}`}>{style.label}</span>
              <span className="font-mono text-[11px] text-slate-400">{e.control_id}</span>
            </div>
            <p className="mt-1 text-[13px] text-slate-700">
              {e.base ? e.base.title : e.target?.title}
            </p>
            <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
              {e.base ? <span>avant : {e.base.severity} / {e.base.status}</span> : null}
              {e.target ? <span>→ actuel : {e.target.severity} / {e.target.status}</span> : null}
            </p>
            <p className="mt-1 text-[11px] leading-snug text-slate-400">{e.explanation}</p>
            {e.status === 'persistent' && onVerifyFix && (
              <button
                type="button"
                onClick={() => onVerifyFix(e.control_id, e.base?.title ?? '')}
                className="mt-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700 hover:bg-emerald-100"
              >
                Vérifier la correction (re-audit ciblé)
              </button>
            )}
          </div>
        )
      })}

      <p className="text-[10px] leading-relaxed text-slate-400">{diff.note}</p>
    </div>
  )
}
