import { useNavigate } from 'react-router-dom'
import { listMissions, listRuns } from '../lib/api'
import type { AuditMission, AuditRun } from '../lib/types'
import { errorMessage, useAsync } from '../lib/useAsync'
import { EmptyState } from './EmptyState'
import { StatusBadge } from './StatusBadge'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'

/**
 * Sélecteur de périmètre (mission ou run) pour les pages Evidence et Findings,
 * lorsqu'aucun paramètre d'URL ne précise de mission_id / run_id.
 */
export function ScopeSelector({ target }: { target: 'evidence' | 'findings' }) {
  const navigate = useNavigate()
  const missionsState = useAsync(listMissions, [])
  const runsState = useAsync(() => listRuns(), [])

  if (missionsState.error || runsState.error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">
        Erreur : {errorMessage(missionsState.error) || errorMessage(runsState.error)}
      </div>
    )
  }

  const missions: AuditMission[] = missionsState.data?.missions ?? []
  const runs: AuditRun[] = runsState.data?.runs ?? []

  if (missions.length === 0 && runs.length === 0) {
    return (
      <EmptyState
        title="Aucun périmètre disponible"
        description="Créez d'abord une source et une mission, puis lancez un audit."
      />
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Choisir un périmètre</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <p className="text-xs font-medium text-slate-600">Missions</p>
          {missions.length === 0 ? (
            <p className="text-xs text-slate-400">Aucune mission.</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {missions.slice(0, 8).map((m) => (
                <li key={m.id}>
                  <button
                    type="button"
                    onClick={() => navigate(`/${target}?mission_id=${m.id}`)}
                    className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-left text-sm transition-colors duration-150 hover:bg-slate-50"
                  >
                    <span className="font-medium text-slate-900">{m.title}</span>
                    <span className="ml-2 text-xs text-slate-400">{m.id}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <p className="text-xs font-medium text-slate-600">Runs récents</p>
          {runs.length === 0 ? (
            <p className="text-xs text-slate-400">Aucun run.</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {runs.slice(0, 8).map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => navigate(`/${target}?run_id=${r.id}`)}
                    className="flex w-full items-center justify-between gap-3 rounded-lg border border-slate-200 px-3.5 py-2.5 text-left transition-colors duration-150 hover:bg-slate-50"
                  >
                    <span className="font-mono text-xs text-slate-700">{r.id}</span>
                    <StatusBadge value={r.status} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
