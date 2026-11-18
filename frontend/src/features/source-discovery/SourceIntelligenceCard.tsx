import { useState } from 'react'

export interface SourceIntelligence {
  source_id: string
  name: string
  type: string
  connection_state: 'connected' | 'error' | 'unknown'
  status?: string
  domains: string[]
  capabilities: {
    rows?: number | null
    truncated?: boolean
    columns?: string[]
    endpoints?: { id?: string; path?: string }[]
    journeys?: { id?: string; name?: string }[]
    models_available?: string[]
    models_unavailable?: string[]
  }
  supported_operations: { tool: string; label: string; scope?: string }[]
  missing_permissions: { tool: string; label: string; reason: string }[]
  unsupported_operations: string[]
  prerequisites: string[]
  discover_error?: string
}

const TYPE_LABELS: Record<string, string> = {
  file: 'Fichier',
  api: 'API',
  odoo: 'ERP Odoo',
  web: 'Application web',
}

function StateChip({ state }: { state: string }) {
  const map: Record<string, { cls: string; label: string }> = {
    connected: { cls: 'bg-emerald-50 text-emerald-700', label: 'connectée' },
    error: { cls: 'bg-red-50 text-red-700', label: 'en échec' },
    unknown: { cls: 'bg-slate-100 text-slate-600', label: 'état inconnu' },
  }
  const info = map[state] ?? map.unknown
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${info.cls}`}>{info.label}</span>
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">{title}</p>
      {children}
    </div>
  )
}

function Pill({ children, tone = 'slate' }: { children: React.ReactNode; tone?: 'slate' | 'indigo' | 'violet' | 'amber' }) {
  const tones: Record<string, string> = {
    slate: 'bg-slate-100 text-slate-600',
    indigo: 'bg-indigo-50 text-indigo-700',
    violet: 'bg-violet-50 text-violet-700',
    amber: 'bg-amber-50 text-amber-700',
  }
  return <span className={`rounded-md px-1.5 py-0.5 text-[11px] ${tones[tone]}`}>{children}</span>
}

/**
 * Carte Source Intelligence (Phase 1/10) : ce qu'une source autorisée expose RÉELLEMENT —
 * état, domaines, opérations supportées / non supportées, permissions manquantes.
 * Rendue depuis le résultat du tool chat `inspect_source` (données backend, rien d'inventé).
 */
export function SourceIntelligenceCard({ intel }: { intel: SourceIntelligence }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="al-event-in my-2 overflow-hidden rounded-xl border border-slate-200/80 bg-white">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-50"
        aria-expanded={expanded}
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-500">
          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
            <ellipse cx="12" cy="5.5" rx="8" ry="2.8" />
            <path d="M4 5.5v6c0 1.55 3.58 2.8 8 2.8s8-1.25 8-2.8v-6M4 11.5v6c0 1.55 3.58 2.8 8 2.8s8-1.25 8-2.8v-6" />
          </svg>
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-slate-800">{intel.name}</span>
          <span className="mt-0.5 flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-slate-400">{TYPE_LABELS[intel.type] ?? intel.type}</span>
            {intel.domains.slice(0, 3).map((d) => (
              <Pill key={d}>{d}</Pill>
            ))}
            {intel.domains.length > 3 && <span className="text-[11px] text-slate-400">+{intel.domains.length - 3}</span>}
            {intel.missing_permissions.length > 0 && (
              <Pill tone="amber">{intel.missing_permissions.length} permission(s) manquante(s)</Pill>
            )}
          </span>
        </span>
        <StateChip state={intel.connection_state} />
        <svg className={`h-4 w-4 shrink-0 text-slate-300 transition-transform ${expanded ? 'rotate-180' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {expanded && (
        <div className="space-y-3 border-t border-slate-100 bg-slate-50/60 px-4 py-3 text-[13px]">
          {intel.discover_error && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">Découverte en échec : {intel.discover_error}</p>
          )}

          {intel.prerequisites.length > 0 && (
            <Section title="Prérequis / limites">
              <ul className="space-y-0.5">
                {intel.prerequisites.map((p) => (
                  <li key={p} className="text-slate-600">• {p}</li>
                ))}
              </ul>
            </Section>
          )}

          <Section title="Opérations supportées">
            <div className="flex flex-wrap gap-1.5">
              {intel.supported_operations.map((op) => (
                <Pill key={op.tool} tone="indigo">
                  {op.label ?? op.tool}
                  {op.scope ? <span className="text-indigo-400"> · {op.scope}</span> : null}
                </Pill>
              ))}
              {intel.supported_operations.length === 0 && <span className="text-xs text-slate-400">aucune</span>}
            </div>
          </Section>

          {intel.missing_permissions.length > 0 && (
            <Section title="Permissions manquantes (approbation humaine requise)">
              <ul className="space-y-1">
                {intel.missing_permissions.map((m) => (
                  <li key={m.tool} className="text-slate-600">
                    <code className="rounded bg-violet-50 px-1 py-0.5 font-mono text-[11px] text-violet-700">{m.tool}</code>{' '}
                    {m.label} — <span className="text-slate-400">{m.reason}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-[11px] text-slate-400">
                Approuvez ces actions sur la page de la mission avant tout audit les nécessitant.
              </p>
            </Section>
          )}

          <Section title="Non supporté par cette source">
            <ul className="space-y-0.5">
              {intel.unsupported_operations.map((u) => (
                <li key={u} className="text-slate-500">• {u}</li>
              ))}
            </ul>
          </Section>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {intel.capabilities.rows != null && (
              <Section title="Lignes">
                <p className="text-slate-700">
                  {intel.capabilities.rows}
                  {intel.capabilities.truncated ? <span className="text-amber-600"> (tronqué)</span> : null}
                </p>
              </Section>
            )}
            {intel.capabilities.columns && intel.capabilities.columns.length > 0 && (
              <Section title="Colonnes">
                <p className="text-slate-700">{intel.capabilities.columns.length}</p>
              </Section>
            )}
            {intel.capabilities.endpoints && intel.capabilities.endpoints.length > 0 && (
              <Section title="Endpoints">
                <p className="text-slate-700">{intel.capabilities.endpoints.length}</p>
              </Section>
            )}
            {intel.capabilities.models_available && intel.capabilities.models_available.length > 0 && (
              <Section title="Modèles ERP">
                <p className="text-slate-700">{intel.capabilities.models_available.length}</p>
              </Section>
            )}
          </div>

          <a
            href={`/connections`}
            className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:underline"
          >
            Configurer ou tester la connexion →
          </a>
        </div>
      )}
    </div>
  )
}
