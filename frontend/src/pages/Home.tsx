import { Link, useNavigate } from 'react-router-dom'
import { listMissions, listRuns, listSources } from '../lib/api'
import type { AuditMission, AuditRun } from '../lib/types'
import { errorMessage, useAsync } from '../lib/useAsync'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { SourceCard } from '../components/SourceCard'
import { StatusBadge } from '../components/StatusBadge'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader } from '../components/ui/card'
import { PlusIcon, TargetIcon } from '../components/icons'

function lastRunOf(runs: AuditRun[], missionId: string): AuditRun | null {
  let latest: AuditRun | null = null
  for (const run of runs) {
    if (run.mission_id !== missionId) continue
    if (latest === null || (run.started_at ?? '') >= (latest.started_at ?? '')) {
      latest = run
    }
  }
  return latest
}

export function HomePage() {
  const navigate = useNavigate()
  const sourcesState = useAsync(listSources, [])
  const missionsState = useAsync(listMissions, [])
  const runsState = useAsync(() => listRuns(), [])

  const sources = sourcesState.data?.sources ?? []
  const missions = (missionsState.data?.missions ?? []).slice().reverse()
  const runs = runsState.data?.runs ?? []
  const recentMissions = missions.slice(0, 6)

  const loading = sourcesState.loading || missionsState.loading

  return (
    <>
      <PageHeader
        title="Workspace"
        description="Vos sources connectées et vos missions d'audit. Aucun score de conformité n'est affiché : seuls les résultats réels des runs apparaissent."
        actions={
          <>
            <Button variant="outline" onClick={() => navigate('/connections')}>
              <PlusIcon className="h-4 w-4" /> Ajouter une source
            </Button>
            <Button onClick={() => navigate('/missions/new')}>
              <TargetIcon className="h-4 w-4" /> Nouvelle mission
            </Button>
          </>
        }
      />

      {sourcesState.error || missionsState.error || runsState.error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">
          Impossible de joindre le backend : {errorMessage(sourcesState.error) || errorMessage(missionsState.error) || errorMessage(runsState.error)}
        </div>
      ) : null}

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold text-slate-900">Sources</h2>
        {loading ? (
          <p className="text-sm text-slate-500">Chargement…</p>
        ) : sources.length === 0 ? (
          <EmptyState
            title="Aucune source"
            description="Connectez Odoo, une API, un site web ou importez un fichier (CSV/XLSX/JSON) pour commencer."
            action={
              <Button variant="outline" onClick={() => navigate('/connections')}>
                Ajouter une source
              </Button>
            }
          />
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {sources.map((source) => (
              <SourceCard key={source.id} source={source} onChanged={() => sourcesState.reload()} showActions={false} />
            ))}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold text-slate-900">Missions récentes</h2>
        {missionsState.loading ? (
          <p className="text-sm text-slate-500">Chargement…</p>
        ) : recentMissions.length === 0 ? (
          <EmptyState
            title="Aucune mission"
            description="Créez une mission : choisissez les sources, les contrôles du catalogue et les limites d'exécution."
            action={
              <Button onClick={() => navigate('/missions/new')}>Nouvelle mission</Button>
            }
          />
        ) : (
          <div className="flex flex-col gap-2">
            {recentMissions.map((mission: AuditMission) => {
              const lastRun = lastRunOf(runs, mission.id)
              return (
                <Card key={mission.id} className="transition-colors duration-150 hover:bg-slate-50">
                  <CardHeader>
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <Link
                        to={`/missions/${mission.id}`}
                        className="text-sm font-semibold text-slate-900 hover:text-indigo-700"
                      >
                        {mission.title}
                      </Link>
                      <div className="flex items-center gap-2">
                        {lastRun ? (
                          <>
                            <StatusBadge value={lastRun.status} pulsing={lastRun.status === 'running'} />
                            <Link
                              to={`/runs/${lastRun.id}`}
                              className="text-xs font-medium text-indigo-600 hover:underline"
                            >
                              Voir le run →
                            </Link>
                          </>
                        ) : (
                          <span className="text-xs text-slate-400">aucun run</span>
                        )}
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p className="line-clamp-2 text-xs text-slate-500">{mission.objective}</p>
                    <p className="mt-1 text-xs text-slate-400">
                      {mission.source_ids.length} source(s) · {mission.control_ids.length} contrôle(s) ·
                      créée {mission.created_at}
                    </p>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </section>
    </>
  )
}
