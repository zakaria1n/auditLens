import { useState } from 'react'
import { deleteSource, testSource } from '../lib/api'
import type { SourceConnection, SourceType } from '../lib/types'
import { ApiIcon, DatabaseIcon, FileIcon, GlobeIcon, TrashIcon } from './icons'
import { StatusBadge } from './StatusBadge'
import { Button } from './ui/button'
import { Card } from './ui/card'

const TYPE_META: Record<SourceType, { label: string; icon: typeof DatabaseIcon }> = {
  odoo: { label: 'Odoo', icon: DatabaseIcon },
  api: { label: 'API', icon: ApiIcon },
  web: { label: 'Web', icon: GlobeIcon },
  file: { label: 'Fichier', icon: FileIcon },
}

function sourceSubtitle(source: SourceConnection): string {
  const config = source.config ?? {}
  switch (source.type) {
    case 'odoo':
      return String(config.url ?? '')
    case 'api':
      return String(config.base_url ?? '')
    case 'web':
      return String(config.base_url ?? '')
    case 'file':
      return String(config.original_name ?? config.path ?? '')
    default:
      return ''
  }
}

export interface SourceCardProps {
  source: SourceConnection
  onChanged: () => void
  showActions?: boolean
}

export function SourceCard({ source, onChanged, showActions = true }: SourceCardProps) {
  const meta = TYPE_META[source.type] ?? { label: source.type, icon: DatabaseIcon }
  const [busy, setBusy] = useState<'test' | 'delete' | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function handleTest() {
    setBusy('test')
    setMessage(null)
    try {
      const res = await testSource(source.id)
      setMessage(res.ok ? (res.message ?? 'connexion réussie') : (res.error ?? res.message ?? 'échec'))
      onChanged()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(null)
    }
  }

  async function handleDelete() {
    setBusy('delete')
    try {
      await deleteSource(source.id)
      onChanged()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
      setBusy(null)
    }
  }

  const Icon = meta.icon

  return (
    <Card className="flex flex-col gap-3 p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-900">{source.name}</p>
            <p className="truncate text-xs text-slate-500">{meta.label} · {sourceSubtitle(source)}</p>
          </div>
        </div>
        <StatusBadge value={source.status} />
      </div>

      {source.last_test_message ? (
        <p className="truncate text-xs text-slate-400" title={source.last_test_message}>
          Dernier test : {source.last_test_message}
        </p>
      ) : null}

      {message ? <p className="text-xs text-slate-600">{message}</p> : null}

      {showActions ? (
        <div className="mt-auto flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={handleTest} disabled={busy !== null}>
            Tester la connexion
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={handleDelete}
            disabled={busy !== null}
            aria-label={`Supprimer ${source.name}`}
            title="Supprimer la source"
          >
            <TrashIcon className="h-4 w-4" />
          </Button>
        </div>
      ) : null}
    </Card>
  )
}
