export interface MemoryResult {
  memory: boolean
  finding_id: string
  mission_id: string
  mission_title: string
  run_id: string
  control_id: string | null
  title: string
  statement: string
  severity: string
  review_status: string
  created_at: string
  thread_id: string | null
  evidence_refs: string[]
}

/**
 * Related Investigations (Phase 9/10) : rend le résultat RÉEL du tool chat
 * `search_investigations` — mémoire non vérifiée, liens vers preuve/rapport/
 * conversation d'origine. Aucune relation fabriquée.
 */
export function RelatedInvestigations({
  result,
  onOpenThread,
}: {
  result: { query: string; results: MemoryResult[]; warning?: string }
  onOpenThread?: (threadId: string) => void
}) {
  const results = result.results ?? []
  return (
    <div className="al-event-in my-2 overflow-hidden rounded-xl border border-brand-200/70 bg-brand-50/40">
      <div className="border-b border-brand-100 px-3.5 py-2">
        <p className="text-xs font-semibold text-brand-900">
          Mémoire d'audit — « {result.query} » ({results.length} résultat(s))
        </p>
        {result.warning && (
          <p className="mt-0.5 text-[10px] leading-snug text-brand-400">{result.warning}</p>
        )}
      </div>
      <div className="space-y-1.5 px-3 py-2">
        {results.length === 0 && (
          <p className="text-xs text-slate-400">Aucune investigation antérieure correspondante.</p>
        )}
        {results.map((r) => (
          <div key={r.finding_id} className="rounded-xl border border-slate-200/80 bg-white px-3 py-2">
            <p className="flex flex-wrap items-center gap-1.5">
              <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                mémoire non vérifiée
              </span>
              <span className="truncate text-[13px] font-medium text-slate-700">{r.title}</span>
            </p>
            <p className="mt-0.5 text-[11px] leading-snug text-slate-500">{r.statement}</p>
            <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-slate-400">
              <span className="rounded bg-slate-100 px-1.5 py-0.5">{r.mission_title}</span>
              <span className="rounded bg-slate-100 px-1.5 py-0.5">revue : {r.review_status}</span>
              <span>{r.created_at}</span>
            </p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {r.thread_id && onOpenThread && (
                <button
                  type="button"
                  onClick={() => onOpenThread(r.thread_id as string)}
                  className="rounded-lg border border-brand-200 bg-brand-50 px-2 py-0.5 text-[11px] font-medium text-brand-700 hover:bg-brand-100"
                >
                  Ouvrir la conversation
                </button>
              )}
              <a
                href={`/runs/${r.run_id}/report`}
                className="rounded-lg border border-slate-200 px-2 py-0.5 text-[11px] text-slate-600 hover:bg-slate-50"
              >
                Rapport
              </a>
              {r.evidence_refs.map((ref) => (
                <a
                  key={ref}
                  href={`/evidence?focus=${ref}`}
                  className="rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-[10px] text-brand-700 hover:bg-brand-100"
                >
                  {ref}
                </a>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
