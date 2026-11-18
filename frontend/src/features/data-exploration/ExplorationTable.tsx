import { useMemo, useState } from 'react'

export interface ExplorationResult {
  table: Record<string, unknown>[]
  total_input_rows: number
  explored_rows: number
  input_truncated: boolean
  total_after_filters: number
  returned_rows: number
  limit: number
  groups: { value: string; count: number; sum?: string; avg?: string; error?: string }[] | null
  comparison: {
    left_field: string
    right_field: string
    op: string
    rows_compared: number
    matches: number
    mismatches: { row_index: number; left: string; right: string; difference: string }[]
  } | null
  source_evidence_id: string
  mission_id: string
}

const PAGE_SIZE = 10

/**
 * Table d'investigation interactive (Phase 2/10) : rend le résultat RÉEL du tool
 * `data_explore` (calculs déterministes backend). Tri/filtre/pagination côté client,
 * lignes incohérentes surlignées (comparaison backend), détails dépliables par ligne,
 * lien preuve et action « Investiguer » qui poursuit la conversation avec les
 * identifiants réels de l'enregistrement — jamais décoratif.
 */
export function ExplorationTable({
  result,
  onInvestigate,
}: {
  result: ExplorationResult
  onInvestigate?: (record: Record<string, unknown>) => void
}) {
  const [sortField, setSortField] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [filter, setFilter] = useState('')
  const [page, setPage] = useState(0)
  const [openRow, setOpenRow] = useState<number | null>(null)

  const columns = useMemo(
    () => (result.table.length > 0 ? Object.keys(result.table[0]) : []),
    [result.table],
  )

  const mismatchValues = useMemo(() => {
    const set = new Set<string>()
    for (const m of result.comparison?.mismatches ?? []) {
      set.add(String(m.left))
      set.add(String(m.right))
    }
    return set
  }, [result.comparison])

  const rows = useMemo(() => {
    let out = result.table
    if (filter.trim()) {
      const q = filter.trim().toLowerCase()
      out = out.filter((r) =>
        Object.values(r).some((v) => String(v ?? '').toLowerCase().includes(q)),
      )
    }
    if (sortField) {
      const field = sortField
      out = [...out].sort((a, b) => {
        const av = a[field] as number | string | null
        const bv = b[field] as number | string | null
        const an = Number(av)
        const bn = Number(bv)
        const cmp =
          !Number.isNaN(an) && !Number.isNaN(bn) && av !== '' && bv !== ''
            ? an - bn
            : String(av ?? '').localeCompare(String(bv ?? ''))
        return sortDir === 'asc' ? cmp : -cmp
      })
    }
    return out
  }, [result.table, filter, sortField, sortDir])

  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const safePage = Math.min(page, pageCount - 1)
  const pageRows = rows.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE)

  const toggleSort = (col: string) => {
    if (sortField === col) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(col)
      setSortDir('asc')
    }
  }

  return (
    <div className="al-event-in my-2 overflow-hidden rounded-xl border border-slate-200/80 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-3.5 py-2.5">
        <p className="text-xs font-medium text-slate-600">
          {result.returned_rows} ligne(s) sur {result.total_after_filters} après filtres
          {result.input_truncated ? <span className="text-amber-600"> · entrée tronquée à {result.explored_rows}</span> : null}
        </p>
        <div className="flex items-center gap-2">
          <input
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value)
              setPage(0)
            }}
            placeholder="Filtrer…"
            className="w-36 rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-700 placeholder:text-slate-400 focus:border-indigo-300 focus:outline-none"
          />
          <a
            href={`/evidence?focus=${result.source_evidence_id}`}
            className="rounded-md bg-violet-50 px-1.5 py-0.5 font-mono text-[11px] text-violet-700 hover:bg-violet-100"
            title="Ouvrir la preuve source"
          >
            {result.source_evidence_id}
          </a>
        </div>
      </div>

      {result.comparison && (
        <div className="border-b border-slate-100 bg-amber-50/60 px-3.5 py-2 text-[11px] text-amber-800">
          Comparaison <strong>{result.comparison.left_field}</strong> {result.comparison.op}{' '}
          <strong>{result.comparison.right_field}</strong> : {result.comparison.matches} concordance(s),{' '}
          <strong>{result.comparison.mismatches.length} incohérence(s)</strong> surlignée(s)
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50/80">
              {columns.map((col) => (
                <th key={col} className="px-2.5 py-1.5">
                  <button
                    type="button"
                    onClick={() => toggleSort(col)}
                    className="font-semibold text-slate-500 hover:text-slate-800"
                  >
                    {col}
                    {sortField === col && <span className="ml-0.5">{sortDir === 'asc' ? '↑' : '↓'}</span>}
                  </button>
                </th>
              ))}
              <th className="px-2 py-1.5" />
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row, i) => {
              const globalIdx = safePage * PAGE_SIZE + i
              const suspicious =
                result.comparison &&
                mismatchValues.has(String(row[result.comparison.left_field]))
              return (
                <>
                  <tr
                    key={globalIdx}
                    className={`border-b border-slate-50 transition-colors hover:bg-slate-50 ${
                      suspicious ? 'bg-red-50/60' : ''
                    }`}
                  >
                    {columns.map((col) => (
                      <td key={col} className="max-w-40 truncate px-2.5 py-1.5 text-slate-700">
                        {row[col] == null || row[col] === '' ? (
                          <span className="text-slate-300">—</span>
                        ) : (
                          String(row[col])
                        )}
                      </td>
                    ))}
                    <td className="whitespace-nowrap px-2 py-1.5 text-right">
                      <button
                        type="button"
                        onClick={() => setOpenRow(openRow === globalIdx ? null : globalIdx)}
                        className="mr-1.5 text-[11px] text-slate-400 hover:text-indigo-600"
                      >
                        {openRow === globalIdx ? 'masquer' : 'détails'}
                      </button>
                      {onInvestigate && (
                        <button
                          type="button"
                          onClick={() => onInvestigate(row)}
                          className="text-[11px] font-medium text-indigo-600 hover:underline"
                        >
                          Investiguer
                        </button>
                      )}
                    </td>
                  </tr>
                  {openRow === globalIdx && (
                    <tr key={`${globalIdx}-detail`} className="border-b border-slate-50 bg-slate-50/70">
                      <td colSpan={columns.length + 1} className="px-3 py-2">
                        <pre className="overflow-auto font-mono text-[11px] leading-relaxed text-slate-600">
                          {JSON.stringify(row, null, 2)}
                        </pre>
                      </td>
                    </tr>
                  )}
                </>
              )
            })}
            {pageRows.length === 0 && (
              <tr>
                <td colSpan={columns.length + 1} className="px-3 py-4 text-center text-slate-400">
                  Aucune ligne (filtre trop restrictif ou résultat vide).
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {result.groups && result.groups.length > 0 && (
        <div className="border-t border-slate-100 bg-slate-50/60 px-3.5 py-2">
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Groupes</p>
          <div className="flex flex-wrap gap-1.5">
            {result.groups.map((g) => (
              <span key={g.value} className="rounded-md bg-white px-2 py-1 text-[11px] text-slate-600 shadow-sm">
                {g.value} → {g.count}
                {g.sum != null ? ` · Σ ${g.sum}` : ''}
                {g.avg != null ? ` · Ø ${g.avg}` : ''}
              </span>
            ))}
          </div>
        </div>
      )}

      {pageCount > 1 && (
        <div className="flex items-center justify-between border-t border-slate-100 px-3.5 py-2 text-[11px] text-slate-500">
          <span>
            Page {safePage + 1} / {pageCount}
          </span>
          <span className="flex gap-1.5">
            <button
              type="button"
              disabled={safePage === 0}
              onClick={() => setPage((p) => p - 1)}
              className="rounded-md border border-slate-200 px-2 py-0.5 hover:bg-slate-50 disabled:opacity-40"
            >
              ← Précédent
            </button>
            <button
              type="button"
              disabled={safePage >= pageCount - 1}
              onClick={() => setPage((p) => p + 1)}
              className="rounded-md border border-slate-200 px-2 py-0.5 hover:bg-slate-50 disabled:opacity-40"
            >
              Suivant →
            </button>
          </span>
        </div>
      )}
    </div>
  )
}
