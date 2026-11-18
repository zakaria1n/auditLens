import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { approvePlan, getMission, listControls, listRuns, listSources, proposePlan, startRun } from '../lib/api'
import type { AuditPlan } from '../lib/types'
import { errorMessage, useAsync } from '../lib/useAsync'
import { toolLabel } from '../lib/tools'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { PlanSteps } from '../components/PlanSteps'
import { StatusBadge } from '../components/StatusBadge'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Dialog } from '../components/ui/dialog'
import { Field, Select, Textarea } from '../components/ui/input'
import { PlayIcon, PulseIcon } from '../components/icons'

const PROVIDERS = ['mock', 'openai', 'gemini', 'anthropic', 'deepseek', 'compatible']

export function MissionDetailPage() {
  const { missionId } = useParams()
  const navigate = useNavigate()
  const missionState = useAsync(() => getMission(missionId ?? ''), [missionId])
  const sourcesState = useAsync(listSources, [])
  const controlsState = useAsync(listControls, [])
  const runsState = useAsync(() => listRuns(missionId), [missionId])

  const [proposedPlan, setProposedPlan] = useState<AuditPlan | null>(null)
  const [planError, setPlanError] = useState<string | null>(null)
  const [planBusy, setPlanBusy] = useState(false)

  const [approveOpen, setApproveOpen] = useState(false)
  const [approveNote, setApproveNote] = useState('')
  const [approveBusy, setApproveBusy] = useState(false)

  const [provider, setProvider] = useState('mock')
  const [runBusy, setRunBusy] = useState(false)

  const mission = missionState.data?.mission ?? null
  const sources = (sourcesState.data?.sources ?? []).filter((s) => mission?.source_ids.includes(s.id))
  const controls = (controlsState.data?.controls ?? []).filter((c) => mission?.control_ids.includes(c.id))
  const runs = runsState.data?.runs ?? []

  const approvedPlan = mission?.approved_plan ?? null
  const planApproved = approvedPlan != null

  async function handleProposePlan() {
    setPlanBusy(true)
    setPlanError(null)
    try {
      const res = await proposePlan(missionId ?? '')
      setProposedPlan(res.plan)
    } catch (err) {
      setPlanError(errorMessage(err))
    } finally {
      setPlanBusy(false)
    }
  }

  async function handleApprove() {
    if (!proposedPlan) return
    setApproveBusy(true)
    try {
      await approvePlan(
        missionId ?? '',
        proposedPlan as unknown as Record<string, unknown>,
        approveNote.trim(),
      )
      setApproveOpen(false)
      missionState.reload()
      runsState.reload()
    } catch (err) {
      setPlanError(errorMessage(err))
    } finally {
      setApproveBusy(false)
    }
  }

  async function handleRun() {
    setRunBusy(true)
    try {
      const res = await startRun(missionId ?? '', { provider })
      navigate(`/runs/${res.run_id}`)
    } catch (err) {
      setPlanError(errorMessage(err))
      setRunBusy(false)
    }
  }

  if (missionState.loading) {
    return <p className="text-sm text-slate-500">Chargement de la mission…</p>
  }

  if (missionState.error || !mission) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">
        Erreur : {missionState.error ?? 'mission inconnue'}
      </div>
    )
  }

  const needsApproval =
    proposedPlan != null && !planApproved && proposedPlan.steps.some((s) => s.requires_approval)

  return (
    <>
      <PageHeader
        title={mission.title}
        description={mission.objective}
        actions={
          <>
            <Button variant="outline" onClick={handleProposePlan} disabled={planBusy}>
              {planBusy ? 'Proposition…' : 'Proposer le plan IA'}
            </Button>
            {proposedPlan && !planApproved ? (
              <Button variant="secondary" onClick={() => setApproveOpen(true)}>
                Approuver le plan
              </Button>
            ) : null}
            <Button onClick={handleRun} disabled={runBusy}>
              <PlayIcon className="h-4 w-4" /> {runBusy ? 'Lancement…' : "Lancer l'audit"}
            </Button>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <StatusBadge value={mission.status} />
        <span>créée {mission.created_at}</span>
        <span>·</span>
        <span>
          limites : max_tool_calls={mission.limits.max_tool_calls}, max_seconds={mission.limits.max_seconds}
        </span>
        {mission.time_range.from || mission.time_range.to ? (
          <>
            <span>·</span>
            <span>
              période : {mission.time_range.from ?? '—'} → {mission.time_range.to ?? '—'}
            </span>
          </>
        ) : null}
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[1fr_1.6fr]">
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Sources ({sources.length})</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-1.5">
              {sources.length === 0 ? (
                <p className="text-xs text-slate-400">Aucune source rattachée.</p>
              ) : (
                sources.map((s) => (
                  <div key={s.id} className="flex items-center justify-between gap-2 text-sm">
                    <span className="truncate font-medium text-slate-800">{s.name}</span>
                    <StatusBadge value={s.status} />
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Contrôles ({controls.length})</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2.5">
              {controls.length === 0 ? (
                <p className="text-xs text-slate-400">Aucun contrôle sélectionné.</p>
              ) : (
                controls.map((c) => (
                  <div key={c.id} className="rounded-lg border border-slate-200 px-3.5 py-2.5">
                    <p className="text-sm font-semibold text-slate-900">
                      {c.id} <span className="font-normal text-slate-600">— {c.title}</span>
                    </p>
                    <p className="mt-1 text-xs text-slate-500">Critère : {c.criterion}</p>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Runs de la mission</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-1.5">
              {runs.length === 0 ? (
                <p className="text-xs text-slate-400">Aucun run pour le moment.</p>
              ) : (
                runs.map((r) => (
                  <Link
                    key={r.id}
                    to={`/runs/${r.id}`}
                    className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 px-3.5 py-2 transition-colors duration-150 hover:bg-slate-50"
                  >
                    <span className="font-mono text-xs text-slate-700">{r.id}</span>
                    <span className="flex items-center gap-2">
                      <StatusBadge value={r.status} pulsing={r.status === 'running'} />
                      <PulseIcon className="h-3.5 w-3.5 text-slate-400" />
                    </span>
                  </Link>
                ))
              )}
            </CardContent>
          </Card>
        </div>

        <div className="flex flex-col gap-4">
          {needsApproval ? (
            <div className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              Des étapes de ce plan nécessitent votre approbation (tests impliquant des requêtes
              potentiellement mutantes : api_inspect_contract, web_run_journey). Sans approbation,
              ces tools seront bloqués pendant le run.
            </div>
          ) : null}
          {planApproved ? (
            <div className="rounded-xl border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
              Plan approuvé le {approvedPlan?.approved_at ?? ''}. Les tools « approved-tests »
              sont autorisés pour cette mission.
            </div>
          ) : null}
          {planError ? (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {planError}
            </div>
          ) : null}

          {proposedPlan ? (
            <PlanSteps plan={proposedPlan} approved={planApproved} />
          ) : approvedPlan ? (
            <Card>
              <CardHeader>
                <CardTitle>Plan approuvé (actions autorisées)</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {(approvedPlan.approved_actions ?? []).map((a, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <span className="text-slate-700">{toolLabel(a.tool ?? '')}</span>
                    <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">
                      {a.tool ?? ''}
                    </code>
                    {a.source_id ? (
                      <span className="text-xs text-slate-400">source: {a.source_id}</span>
                    ) : null}
                  </div>
                ))}
                {approvedPlan.note ? (
                  <p className="text-xs text-slate-500">Note d'approbation : {approvedPlan.note}</p>
                ) : null}
                <p className="text-xs text-slate-400">
                  Rechargez « Proposer le plan IA » pour afficher le plan détaillé avant un nouveau run.
                </p>
              </CardContent>
            </Card>
          ) : (
            <EmptyState
              title="Pas encore de plan"
              description="« Proposer le plan IA » génère les étapes, leur rationale et les risques. Vous gardez la main : approbation obligatoire pour les tools sensibles."
            />
          )}

          <Card>
            <CardHeader>
              <CardTitle>Lancer un run</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap items-end gap-3">
              <Field label="Provider LLM" hint="mock par défaut : exécution scriptée sans clé API.">
                <Select value={provider} onChange={(e) => setProvider(e.target.value)} className="w-52">
                  {PROVIDERS.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </Select>
              </Field>
              <Button onClick={handleRun} disabled={runBusy}>
                <PlayIcon className="h-4 w-4" /> {runBusy ? 'Lancement…' : "Lancer l'audit"}
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>

      <Dialog
        open={approveOpen}
        onClose={() => setApproveOpen(false)}
        title="Approuver le plan"
        description="Sans approbation explicite, les tools approved-tests (api_inspect_contract, web_run_journey) resteront bloqués pendant l'exécution."
        footer={
          <>
            <Button variant="ghost" onClick={() => setApproveOpen(false)}>
              Annuler
            </Button>
            <Button variant="secondary" onClick={handleApprove} disabled={approveBusy}>
              {approveBusy ? 'Approbation…' : "Approuver le plan"}
            </Button>
          </>
        }
      >
        <Field label="Note d'approbation (optionnelle)" htmlFor="approve-note">
          <Textarea
            id="approve-note"
            value={approveNote}
            onChange={(e) => setApproveNote(e.target.value)}
            rows={3}
            placeholder="Contexte de la décision d'approbation…"
          />
        </Field>
      </Dialog>
    </>
  )
}
