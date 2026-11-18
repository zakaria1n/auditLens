import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getRun, missionEvidence, runEvidence } from '../lib/api'
import type { EvidenceMeta } from '../lib/types'
import { errorMessage, useAsync } from '../lib/useAsync'
import { EvidenceDetailPanel } from '../components/EvidenceDetailPanel'
import { EvidenceList } from '../components/EvidenceList'
import { PageHeader } from '../components/PageHeader'
import { ScopeSelector } from '../components/ScopeSelector'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Field, Select } from '../components/ui/input'

export function EvidenceExplorerPage() {
  const [searchParams] = useSearchParams()
  const missionIdParam = searchParams.get('mission_id')
  const runIdParam = searchParams.get('run_id')
  const focusParam = searchParams.get('focus')

  const [missionId, setMissionId] = useState<string | null>(missionIdParam)
  const [selectedId, setSelectedId] = useState<string | null>(focusParam)
  const [typeFilter, setTypeFilter] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')

  // run_id → mission_id (nécessaire pour GET /api/evidence/{id} scopé mission)
  const runState = useAsync(runIdParam ? () => getRun(runIdParam) : () => Promise.resolve(null), [runIdParam])

  useEffect(() => {
    if (missionIdParam) setMissionId(missionIdParam)
    else if (runIdParam && runState.data?.run) setMissionId(runState.data.run.mission_id)
    if (focusParam) setSelectedId(focusParam)
  }, [missionIdParam, runIdParam, runState.data, focusParam])

  const evidenceState = useAsync(
    runIdParam && runState.data
      ? () => runEvidence(runIdParam)
      : missionId
        ? () => missionEvidence(missionId)
        : () => Promise.resolve({ evidence: [] as EvidenceMeta[] }),
    [runIdParam, missionId, runState.data],
  )

  const allEvidence: EvidenceMeta[] = evidenceState.data?.evidence ?? []
  const types = useMemo(() => [...new Set(allEvidence.map((e) => e.type))].sort(), [allEvidence])
  const sourceIds = useMemo(
    () => [...new Set(allEvidence.map((e) => e.source_id).filter((s): s is string => s != null))].sort(),
    [allEvidence],
  )

  const filtered = allEvidence.filter(
    (e) =>
      (typeFilter === '' || e.type === typeFilter) &&
      (sourceFilter === '' || e.source_id === sourceFilter),
  )

  if (!missionIdParam && !runIdParam) {
    return (
      <>
        <PageHeader
          title="Evidence Explorer"
          description="Toute assertion d'audit repose sur une preuve vérifiable : payload, checksum sha256, provenance et horodatage."
        />
        <ScopeSelector target="evidence" />
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Evidence Explorer"
        description={
          runIdParam
            ? `Preuves du run ${runIdParam}${missionId ? ` (mission ${missionId})` : ''}`
            : `Preuves de la mission ${missionId ?? ''}`
        }
      />

      {runState.error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">
          Erreur : {errorMessage(runState.error)}
        </div>
      ) : null}
      {evidenceState.error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">
          Erreur : {errorMessage(evidenceState.error)}
        </div>
      ) : null}

      {evidenceState.loading || (runIdParam && !runState.data) ? (
        <p className="text-sm text-slate-500">Chargement des preuves…</p>
      ) : (
        <div className="flex flex-col gap-4">
          <Card>
            <CardContent className="grid gap-4 py-4 sm:grid-cols-2">
              <Field label="Filtrer par type">
                <Select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                  <option value="">Tous les types</option>
                  {types.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Filtrer par source">
                <Select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
                  <option value="">Toutes les sources</option>
                  {sourceIds.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </Select>
              </Field>
            </CardContent>
          </Card>

          <div className="grid items-start gap-6 lg:grid-cols-[1fr_1.4fr]">
            <Card>
              <CardHeader>
                <CardTitle>Preuves ({filtered.length}/{allEvidence.length})</CardTitle>
              </CardHeader>
              <CardContent>
                <EvidenceList
                  evidence={filtered}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                />
              </CardContent>
            </Card>
            <EvidenceDetailPanel evidenceId={selectedId} missionId={missionId} />
          </div>
        </div>
      )}
    </>
  )
}
