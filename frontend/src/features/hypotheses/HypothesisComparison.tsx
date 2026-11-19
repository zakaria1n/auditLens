import { useMemo, useState } from 'react'

import type { RunEvent } from '../../lib/types'

export interface HypothesisView {
  id: string
  statement: string
  status: string
  evidenceRefs: string[]
  alternatives: { id: string; statement: string; evidence_refs: string[] }[]
  contradicted_by: string[]
  revisions: { turn: number; status: string; statement: string; note: string }[]
}

/** Reconstruit les hypothèses depuis les événements backend réels du run. */
export function useHypotheses(events: RunEvent[]): HypothesisView[] {
  return useMemo(() => {
    const map = new Map<string, HypothesisView>()
    for (const ev of events) {
      const data = ev.data as Record<string, unknown>
      if (ev.type === 'hypothesis_created' || ev.type === 'hypothesis_updated') {
        map.set(String(data.id ?? '?'), {
          id: String(data.id ?? '?'),
          statement: String(data.statement ?? ''),
          status: String(data.status ?? 'open'),
          evidenceRefs: Array.isArray(data.evidence_refs) ? (data.evidence_refs as string[]) : [],
          alternatives: Array.isArray(data.alternatives)
            ? (data.alternatives as { id: string; statement: string; evidence_refs: string[] }[])
            : [],
          contradicted_by: Array.isArray(data.contradicted_by) ? (data.contradicted_by as string[]) : [],
          revisions: Array.isArray(data.revisions)
            ? (data.revisions as { turn: number; status: string; statement: string; note: string }[])
            : [],
        })
      } else if (ev.type === 'hypothesis_rejected') {
        for (const h of map.values()) h.status = 'partiellement rejetée'
      }
    }
    return Array.from(map.values())
  }, [events])
}

const STATUS_TONE: Record<string, string> = {
  supported: 'text-emerald-600',
  rejected: 'text-red-600',
  inconclusive: 'text-amber-600',
  open: 'text-slate-500',
}

/**
 * Hypothesis Comparison View (Phase 4/10) : hypothèse principale vs alternatives,
 * preuves support/contradiction, historique de révisions, vérifications manquantes.
 * « Investiguer » poursuit la conversation avec l'explication alternative choisie.
 */
export function HypothesisComparison({
  hypotheses,
  onOpenEvidence,
  onInvestigateAlternative,
  missionId,
}: {
  hypotheses: HypothesisView[]
  onOpenEvidence: (evidenceId: string, missionId: string) => void
  onInvestigateAlternative: (hypothesisId: string, altId: string, statement: string) => void
  missionId: string
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null)

  if (hypotheses.length === 0) {
    return <p className="text-xs text-slate-400">Aucune hypothèse consignée.</p>
  }
  const main = hypotheses.find((h) => h.id === selectedId) ?? hypotheses[0]

  return (
    <div className="space-y-2">
      {hypotheses.length > 1 && (
        <div className="flex flex-wrap gap-1">
          {hypotheses.map((h) => (
            <button
              key={h.id}
              type="button"
              onClick={() => setSelectedId(h.id)}
              className={`rounded-lg px-2 py-1 text-[11px] font-medium transition-colors ${
                h.id === main.id ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              {h.id}
            </button>
          ))}
        </div>
      )}

      <div className="rounded-xl bg-slate-50 px-3 py-2.5">
        <p className="flex items-center justify-between text-[11px]">
          <span className="font-mono text-slate-400">{main.id}</span>
          <span className={`font-medium ${STATUS_TONE[main.status] ?? 'text-amber-600'}`}>{main.status}</span>
        </p>
        <p className="mt-1 text-[13px] leading-relaxed text-slate-700">{main.statement}</p>
        {main.evidenceRefs.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            <span className="text-[10px] uppercase tracking-wide text-emerald-600">support :</span>
            {main.evidenceRefs.map((ref) => (
              <button key={ref} type="button" onClick={() => onOpenEvidence(ref, missionId)}
                className="rounded bg-emerald-50 px-1 py-0.5 font-mono text-[10px] text-emerald-700 hover:bg-emerald-100">
                {ref}
              </button>
            ))}
          </div>
        )}
        {main.contradicted_by.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            <span className="text-[10px] uppercase tracking-wide text-red-500">contradiction :</span>
            {main.contradicted_by.map((ref) => (
              <button key={ref} type="button" onClick={() => onOpenEvidence(ref, missionId)}
                className="rounded bg-red-50 px-1 py-0.5 font-mono text-[10px] text-red-700 hover:bg-red-100">
                {ref}
              </button>
            ))}
          </div>
        )}
      </div>

      {main.alternatives.length > 0 && (
        <div>
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Explications alternatives (challenger)
          </p>
          <div className="space-y-1.5">
            {main.alternatives.map((alt) => (
              <div key={alt.id} className="rounded-xl border border-slate-200/80 bg-white px-3 py-2">
                <p className="flex items-center justify-between text-[11px]">
                  <span className="font-mono text-slate-400">{alt.id}</span>
                  {alt.statement && (
                    <button
                      type="button"
                      onClick={() => onInvestigateAlternative(main.id, alt.id, alt.statement)}
                      className="font-medium text-brand-600 hover:underline"
                    >
                      Investiguer cette explication
                    </button>
                  )}
                </p>
                <p className="mt-0.5 text-[13px] leading-snug text-slate-600">{alt.statement}</p>
                {alt.evidence_refs.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {alt.evidence_refs.map((ref) => (
                      <button key={ref} type="button" onClick={() => onOpenEvidence(ref, missionId)}
                        className="rounded bg-brand-50 px-1 py-0.5 font-mono text-[10px] text-brand-700 hover:bg-brand-100">
                        {ref}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {main.revisions.length > 0 && (
        <div>
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Historique de révisions
          </p>
          <ul className="space-y-1">
            {main.revisions.slice().reverse().map((rev, i) => (
              <li key={i} className="rounded-xl bg-slate-50 px-3 py-1.5 text-[11px] text-slate-600">
                <span className="font-mono text-slate-400">tour {rev.turn}</span> → {rev.status}
                {rev.note ? <span className="text-slate-400"> — {rev.note}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}

      {main.status === 'inconclusive' && main.contradicted_by.length === 0 && main.alternatives.length === 0 && (
        <p className="rounded-xl bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
          Vérification manquante : aucune alternative explorée ni contradiction cherchée —
          demandez à l'agent de challenger cette hypothèse avant conclusion.
        </p>
      )}
    </div>
  )
}
