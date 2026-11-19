import type { EvidenceMeta } from '../lib/types'
import { EmptyState } from './EmptyState'
import { Badge } from './ui/badge'

export interface EvidenceListProps {
  evidence: EvidenceMeta[]
  selectedId: string | null
  onSelect: (id: string) => void
}

export function EvidenceList({ evidence, selectedId, onSelect }: EvidenceListProps) {
  if (evidence.length === 0) {
    return (
      <EmptyState
        title="Aucune preuve"
        description="Aucune preuve n'a été collectée pour ce périmètre. Lancez un audit pour en produire."
      />
    )
  }
  return (
    <ul className="flex flex-col gap-2" aria-label="Liste des preuves">
      {evidence.map((ev) => {
        const selected = ev.id === selectedId
        return (
          <li key={ev.id}>
            <button
              type="button"
              onClick={() => onSelect(ev.id)}
              aria-selected={selected}
              className={`w-full rounded-xl border px-4 py-3 text-left transition-colors duration-150 ${
                selected
                  ? 'border-brand-300 bg-brand-50'
                  : 'border-slate-200 bg-white hover:bg-slate-50'
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <p className="truncate text-sm font-medium text-slate-900">{ev.title}</p>
                <Badge
                  tone={selected ? 'indigo' : 'neutral'}
                  className="shrink-0"
                >
                  {ev.type}
                </Badge>
              </div>
              <p className="mt-1 truncate font-mono text-xs text-slate-400">{ev.id}</p>
              <p className="mt-1 text-xs text-slate-500">
                {ev.record_count != null ? `${ev.record_count} enregistrements · ` : ''}
                observée {ev.observed_at}
              </p>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
