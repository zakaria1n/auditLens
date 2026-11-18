import { useEffect, useState } from 'react'
import { getEvidence } from '../lib/api'
import type { EvidenceMeta } from '../lib/types'
import { errorMessage } from '../lib/useAsync'
import { EmptyState } from './EmptyState'
import { Spinner } from './icons'
import { Badge } from './ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'

export interface EvidenceDetailPanelProps {
  evidenceId: string | null
  missionId: string | null
}

export function EvidenceDetailPanel({ evidenceId, missionId }: EvidenceDetailPanelProps) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [meta, setMeta] = useState<EvidenceMeta | null>(null)
  const [integrityVerified, setIntegrityVerified] = useState<boolean | null>(null)
  const [payload, setPayload] = useState<unknown>(null)

  useEffect(() => {
    if (!evidenceId || !missionId) return
    let cancelled = false
    setLoading(true)
    setError(null)
    getEvidence(evidenceId, missionId)
      .then((res) => {
        if (cancelled) return
        setMeta(res.evidence)
        setIntegrityVerified(res.evidence.integrity_verified)
        setPayload(res.payload)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorMessage(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [evidenceId, missionId])

  if (!evidenceId || !missionId) {
    return (
      <EmptyState
        title="Sélectionnez une preuve"
        description="Cliquez sur une preuve à gauche pour afficher son payload, son checksum et sa vérification d'intégrité."
      />
    )
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-5 py-10 text-sm text-slate-500">
        <Spinner className="h-4 w-4" /> Chargement de la preuve…
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">
        Erreur : {error}
      </div>
    )
  }

  if (!meta) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>{meta.title}</CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <Badge>{meta.type}</Badge>
          {integrityVerified != null ? (
            <Badge tone={integrityVerified ? 'green' : 'red'}>
              integrity_verified : {String(integrityVerified)}
            </Badge>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
          <dt className="font-medium text-slate-500">ID</dt>
          <dd className="font-mono text-slate-800 break-all">{meta.id}</dd>
          <dt className="font-medium text-slate-500">Checksum</dt>
          <dd className="font-mono break-all text-slate-800">{meta.checksum}</dd>
          <dt className="font-medium text-slate-500">Observée à</dt>
          <dd className="text-slate-800">{meta.observed_at}</dd>
          {meta.record_count != null ? (
            <>
              <dt className="font-medium text-slate-500">Enregistrements</dt>
              <dd className="text-slate-800">{meta.record_count}</dd>
            </>
          ) : null}
          {meta.source_id ? (
            <>
              <dt className="font-medium text-slate-500">Source</dt>
              <dd className="font-mono text-slate-800">{meta.source_id}</dd>
            </>
          ) : null}
        </dl>

        {meta.provenance && Object.keys(meta.provenance).length > 0 ? (
          <div>
            <p className="mb-1 text-xs font-semibold text-slate-600">Provenance</p>
            <pre className="overflow-x-auto rounded-lg bg-slate-50 p-3 font-mono text-xs text-slate-700">
              {JSON.stringify(meta.provenance, null, 2)}
            </pre>
          </div>
        ) : null}

        {meta.summary && Object.keys(meta.summary).length > 0 ? (
          <div>
            <p className="mb-1 text-xs font-semibold text-slate-600">Résumé (version minimisée)</p>
            <pre className="overflow-x-auto rounded-lg bg-slate-50 p-3 font-mono text-xs text-slate-700">
              {JSON.stringify(meta.summary, null, 2)}
            </pre>
          </div>
        ) : null}

        <div>
          <p className="mb-1 text-xs font-semibold text-slate-600">Payload</p>
          <pre className="max-h-96 overflow-auto rounded-lg bg-slate-900 p-4 font-mono text-xs leading-relaxed text-slate-100">
            {payload == null ? '∅ (payload vide)' : JSON.stringify(payload, null, 2)}
          </pre>
        </div>
      </CardContent>
    </Card>
  )
}
