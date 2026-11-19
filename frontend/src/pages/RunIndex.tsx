import { Link } from 'react-router-dom'
import { listRuns } from '../lib/api'
import { errorMessage, useAsync } from '../lib/useAsync'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { Card, CardContent, CardHeader } from '../components/ui/card'

const TERMINAL = new Set(['completed', 'failed', 'review_required', 'partial'])

export function RunIndexPage() {
  const runsState = useAsync(() => listRuns(), [])
  const runs = runsState.data?.runs ?? []

  return (
    <>
      <PageHeader
        title="Live Audit — runs"
        description="Tous les runs. Un run actif s'affiche avec son statut réel ; cliquez pour suivre la timeline des événements backend."
      />
      {runsState.error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">
          Erreur : {errorMessage(runsState.error)}
        </div>
      ) : null}
      {runsState.loading ? (
        <p className="text-sm text-slate-500">Chargement…</p>
      ) : runs.length === 0 ? (
        <EmptyState
          title="Aucun run"
          description="Lancez un audit depuis une mission pour voir apparaître son exécution ici."
        />
      ) : (
        <div className="flex flex-col gap-2">
          {runs
            .slice()
            .reverse()
            .map((run) => (
              <Card key={run.id}>
                <CardHeader>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <Link
                      to={`/runs/${run.id}`}
                      className="font-mono text-sm font-semibold text-slate-900 hover:text-brand-700"
                    >
                      {run.id}
                    </Link>
                    <div className="flex items-center gap-2">
                      <StatusBadge value={run.status} pulsing={run.status === 'running'} />
                      {!TERMINAL.has(run.status) && run.status !== 'not_started' ? (
                        <Link
                          to={`/runs/${run.id}`}
                          className="text-xs font-medium text-brand-600 hover:underline"
                        >
                          Suivre en direct →
                        </Link>
                      ) : null}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                  <span>mission : {run.mission_id}</span>
                  <span>provider : {run.provider_id}</span>
                  <span>model : {run.model_id}</span>
                  <span>tool_calls : {run.tool_calls_used}</span>
                  {run.stop_reason ? <span>stop_reason : {run.stop_reason}</span> : null}
                  {run.error ? <span className="text-red-600">erreur : {run.error}</span> : null}
                </CardContent>
              </Card>
            ))}
        </div>
      )}
    </>
  )
}
