import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listFindings } from '../lib/api'
import type { Finding } from '../lib/types'
import { errorMessage } from '../lib/useAsync'
import { EmptyState } from '../components/EmptyState'
import { FindingCard } from '../components/FindingCard'
import { PageHeader } from '../components/PageHeader'
import { ScopeSelector } from '../components/ScopeSelector'
import { Tabs } from '../components/ui/tabs'

const STATUS_TABS = [
  { id: 'all', label: 'Tous' },
  { id: 'needs_review', label: 'À revoir' },
  { id: 'accepted', label: 'Acceptés' },
  { id: 'rejected', label: 'Rejetés' },
  { id: 'needs_more_evidence', label: 'Preuve demandée' },
]

export function FindingsReviewPage() {
  const [searchParams] = useSearchParams()
  const runIdParam = searchParams.get('run_id')
  const missionIdParam = searchParams.get('mission_id')

  const [findings, setFindings] = useState<Finding[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState('all')

  useEffect(() => {
    if (!runIdParam && !missionIdParam) return
    let cancelled = false
    setLoading(true)
    setError(null)

    const load = runIdParam
      ? listFindings({ run_id: runIdParam })
      : listFindings({ mission_id: missionIdParam ?? '' })

    load
      .then((res) => {
        if (cancelled) return
        setFindings(res.findings)
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
  }, [runIdParam, missionIdParam])

  if (!runIdParam && !missionIdParam) {
    return (
      <>
        <PageHeader
          title="Findings Review"
          description="Décision humaine explicite sur chaque constat : Accept, Reject ou Needs More Evidence, avec justification obligatoire."
        />
        <ScopeSelector target="findings" />
      </>
    )
  }

  const filtered = tab === 'all' ? findings : findings.filter((f) => f.status === tab)
  const countBy = (id: string) => (id === 'all' ? findings.length : findings.filter((f) => f.status === id).length)

  return (
    <>
      <PageHeader
        title="Findings Review"
        description={
          runIdParam
            ? `Constats du run ${runIdParam}`
            : `Constats de la mission ${missionIdParam ?? ''}`
        }
      />

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">
          Erreur : {error}
        </div>
      ) : null}

      {loading ? (
        <p className="text-sm text-slate-500">Chargement des constats…</p>
      ) : findings.length === 0 ? (
        <EmptyState
          title="Aucun constat"
          description="Ce périmètre n'a produit aucun finding. Lancez ou terminez un audit pour en générer."
        />
      ) : (
        <div className="flex flex-col gap-4">
          <Tabs tabs={STATUS_TABS.map((t) => ({ ...t, count: countBy(t.id) }))} value={tab} onChange={setTab} />
          <div className="flex flex-col gap-4">
            {filtered.map((f) => (
              <FindingCard key={f.id} finding={f} onReviewed={(updated) => {
                setFindings((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
              }} />
            ))}
          </div>
        </div>
      )}
    </>
  )
}
