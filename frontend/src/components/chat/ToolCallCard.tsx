import { useState } from 'react'

import type { ToolCallPart } from '../../lib/chatApi'

const TOOL_META: Record<string, { label: string; hint: string }> = {
  list_sources: { label: 'Vérification des sources connectées', hint: 'list_sources' },
  create_audit: { label: 'Lancement de l’audit', hint: 'create_audit' },
  get_run_status: { label: 'Consultation du statut du run', hint: 'get_run_status' },
  get_findings: { label: 'Lecture des constats', hint: 'get_findings' },
  get_evidence: { label: 'Consultation d’une preuve', hint: 'get_evidence' },
  search_conversation: { label: 'Recherche dans l’historique', hint: 'search_conversation' },
}

function formatDuration(ms?: number): string | null {
  if (ms == null) return null
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
}

function StatusChip({ status }: { status: string }) {
  const map: Record<string, { cls: string; label: string }> = {
    running: { cls: 'bg-brand-50 text-brand-600', label: 'en cours' },
    complete: { cls: 'bg-emerald-50 text-emerald-700', label: 'terminé' },
    error: { cls: 'bg-red-50 text-red-700', label: 'échec' },
  }
  const info = map[status] ?? map.complete
  return (
    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${info.cls}`}>
      {info.label}
    </span>
  )
}

function countEvidence(result: Record<string, unknown> | undefined): number | null {
  if (!result) return null
  const text = JSON.stringify(result)
  const matches = text.match(/ev_[a-f0-9]+/g)
  return matches ? new Set(matches).size : null
}

/**
 * Activité d'outil du backend, présentée comme une ligne d'activité sobre :
 * action lisible + statut + durée ; les détails techniques (id d'outil, arguments,
 * résultat brut) restent disponibles en extension — jamais en premier plan (ADR-18).
 */
export function ToolCallCard({ part }: { part: ToolCallPart }) {
  const [open, setOpen] = useState(false)
  const meta = TOOL_META[part.tool] ?? { label: part.tool, hint: part.tool }
  const duration = formatDuration(part.duration_ms)
  const evCount = countEvidence(part.result)
  const error = part.error || (part.result as { error?: string } | undefined)?.error
  const refs = [
    typeof part.result?.mission_id === 'string' ? part.result.mission_id : null,
    typeof part.result?.run_id === 'string' ? part.result.run_id : null,
  ].filter(Boolean) as string[]

  return (
    <div className="my-2 overflow-hidden rounded-xl border border-slate-200/80 bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left transition-colors hover:bg-slate-50"
        aria-expanded={open}
      >
        <span
          className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
            part.status === 'error' ? 'bg-red-50 text-red-500' : 'bg-brand-50 text-brand-500'
          }`}
        >
          {part.status === 'running' ? (
            <span className="al-pulse-dot block h-2 w-2 rounded-full bg-current" />
          ) : part.status === 'error' ? (
            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M12 8v5M12 16.5v.2" />
              <circle cx="12" cy="12" r="9" />
            </svg>
          ) : (
            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="m5 13 4 4L19 7" />
            </svg>
          )}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm text-slate-700">
          {meta.label}
        </span>
        {evCount != null && evCount > 0 && (
          <span className="hidden shrink-0 text-[11px] text-slate-400 sm:inline">
            {evCount} preuve{evCount > 1 ? 's' : ''}
          </span>
        )}
        {duration && <span className="shrink-0 font-mono text-[11px] text-slate-400">{duration}</span>}
        <StatusChip status={part.status} />
        <svg
          className={`h-4 w-4 shrink-0 text-slate-300 transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      {open && (
        <div className="border-t border-slate-100 bg-slate-50/70 px-4 py-3">
          {error && (
            <p className="mb-2.5 rounded-lg bg-red-50 px-3 py-2 text-xs leading-relaxed text-red-700">{error}</p>
          )}
          {refs.length > 0 && (
            <p className="mb-2.5 flex flex-wrap gap-1.5">
              {refs.map((r) => (
                <code key={r} className="rounded bg-brand-50 px-1.5 py-0.5 font-mono text-[11px] text-brand-700">
                  {r}
                </code>
              ))}
            </p>
          )}
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">
            Détails techniques · <code className="font-mono normal-case">{meta.hint}</code>
          </p>
          <p className="mb-1 text-[11px] text-slate-400">Entrées (sanitizées côté backend)</p>
          <pre className="mb-2.5 max-h-36 overflow-auto rounded-lg bg-white p-2.5 font-mono text-[11px] leading-relaxed text-slate-600">
            {JSON.stringify(part.args ?? {}, null, 2)}
          </pre>
          <p className="mb-1 text-[11px] text-slate-400">Résultat</p>
          <pre className="max-h-48 overflow-auto rounded-lg bg-white p-2.5 font-mono text-[11px] leading-relaxed text-slate-600">
            {JSON.stringify(part.result ?? {}, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
