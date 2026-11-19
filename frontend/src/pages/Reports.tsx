import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { listReports } from '../lib/api'
import type { ReportListItem } from '../lib/chatReports'
import { useChatWorkspaceCtx } from '../lib/chatWorkspaceContext'

/**
 * Bibliothèque centralisée des rapports (ADR-17 §4) : toutes conversations et
 * missions confondues, recherche, lien vers le rapport versionné et vers la
 * conversation d'origine (ouverte dans la sidebar chat — état conservé).
 */
export function ReportsPage() {
  const ws = useChatWorkspaceCtx()
  const navigate = useNavigate()
  const [reports, setReports] = useState<ReportListItem[] | null>(null)
  const [query, setQuery] = useState('')
  const [error, setError] = useState<string | null>(null)

  const load = (q: string) => {
    listReports(q || undefined)
      .then((data) => setReports(data.reports))
      .catch((err) => setError((err as Error).message))
  }

  useEffect(() => {
    load('')
  }, [])

  const openInConversation = (threadId: string) => {
    void ws.selectThread(threadId)
    navigate('/chat')
  }

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-2">
        <h1 className="text-xl font-semibold text-slate-900">Rapports d'audit</h1>
        <p className="text-sm text-slate-500">
          Archive centralisée des rapports générés par les investigations — versionnés par run,
          liés à leur conversation d'origine. La revue humaine reste obligatoire avant publication.
        </p>
      </header>

      <div className="flex items-center gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') load(query)
          }}
          placeholder="Rechercher (mission, modèle, id)…"
          className="w-72 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 placeholder:text-slate-400 focus:border-brand-300 focus:outline-none"
        />
        <button
          type="button"
          onClick={() => load(query)}
          className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
        >
          Chercher
        </button>
        {query && (
          <button
            type="button"
            onClick={() => {
              setQuery('')
              load('')
            }}
            className="text-xs text-slate-400 hover:text-slate-700"
          >
            ✕ réinitialiser
          </button>
        )}
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {reports == null ? (
        <p className="text-sm text-slate-400">Chargement…</p>
      ) : reports.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="text-sm font-medium text-slate-600">Aucun rapport</p>
          <p className="mt-1 text-xs text-slate-400">
            Lancez un audit depuis une conversation : le rapport versionné apparaîtra ici une fois
            l'investigation terminée.
          </p>
        </div>
      ) : (
        <ul className="flex flex-col gap-2">
          {reports.map((r) => (
            <li
              key={`${r.id}-${r.version}`}
              className="flex flex-col gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm md:flex-row md:items-center md:justify-between"
            >
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-semibold text-slate-800">{r.mission_title}</span>
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-500">
                    v{r.version}
                  </span>
                  {r.findings_included > 0 && (
                    <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700">
                      {r.findings_included} constat(s) accepté(s)
                    </span>
                  )}
                </p>
                <p className="mt-0.5 truncate font-mono text-[11px] text-slate-400">
                  {r.created_at} · {r.provider_id}/{r.model_id} · run {r.run_id}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {r.thread_id && (
                  <button
                    type="button"
                    onClick={() => openInConversation(r.thread_id as string)}
                    className="rounded-lg border border-brand-200 bg-brand-50 px-2.5 py-1.5 text-xs font-medium text-brand-700 hover:bg-brand-100"
                  >
                    Ouvrir la conversation
                  </button>
                )}
                <Link
                  to={`/runs/${r.run_id}/report`}
                  className="rounded-lg bg-brand-600 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-brand-700"
                >
                  Voir le rapport
                </Link>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
