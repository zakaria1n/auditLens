import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { API_BASE, extendBudget, getMission, getRun, pauseRun, resumeRun, runFindings, stopRun } from '../../lib/api'
import type { AuditMission, AuditRun, Finding, RunEvent } from '../../lib/types'
import { subscribeRunEvents } from '../../lib/sse'
import { EvidenceDetailPanel } from '../EvidenceDetailPanel'
import { FindingCard } from '../FindingCard'
import { ActionPlanView } from '../../features/remediation/ActionPlanView'
import { BeforeAfterAuditView, useRunDiff } from '../../features/differential-audit/BeforeAfterAuditView'
import { CoverageMap, useCoverage } from '../../features/audit-coverage/CoverageMap'
import { HypothesisComparison, useHypotheses } from '../../features/hypotheses/HypothesisComparison'

interface PanelProps {
  missionIds: string[]
  runIds: string[]
  mobileOpen?: boolean
  onCloseMobile?: () => void
}

type Tab = 'overview' | 'tools' | 'hypotheses' | 'evidence' | 'findings' | 'coverage'

const TABS: { key: Tab; label: string }[] = [
  { key: 'overview', label: 'Aperçu' },
  { key: 'tools', label: 'Activité' },
  { key: 'hypotheses', label: 'Hypothèses' },
  { key: 'evidence', label: 'Preuves' },
  { key: 'findings', label: 'Constats' },
  { key: 'coverage', label: 'Couverture' },
]



function StatusChip({ status }: { status: string }) {
  const cls =
    status === 'completed' || status === 'review_required'
      ? 'bg-emerald-50 text-emerald-700'
      : status === 'running'
        ? 'bg-indigo-50 text-indigo-600'
        : status === 'paused'
          ? 'bg-amber-50 text-amber-700'
          : 'bg-slate-100 text-slate-600'
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}>{status}</span>
}

function BudgetBar({ run, events }: { run: AuditRun | null; events: RunEvent[] }) {
  let used: number | null = run?.tool_calls_used ?? null
  let max: number | null = null
  for (const ev of events) {
    const data = ev.data as Record<string, unknown>
    const b = data.budget as Record<string, unknown> | undefined
    if (b && typeof b.tool_calls_used === 'number') {
      used = b.tool_calls_used
      max = typeof b.max_tool_calls === 'number' ? b.max_tool_calls : max
    }
  }
  if (used == null) {
    return <p className="text-xs text-slate-400">Budget tools : indisponible</p>
  }
  const pct = max ? Math.min(100, Math.round((used / max) * 100)) : 0
  return (
    <div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-500">Budget tools</span>
        <span className="font-mono text-slate-600">
          {used}
          {max != null ? ` / ${max}` : ''}
        </span>
      </div>
      {max != null && (
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-200">
          <div
            className={`h-full rounded-full transition-[width] duration-300 ${pct >= 80 ? 'bg-amber-500' : 'bg-emerald-500'}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
    </div>
  )
}


function CoverageSection({
  missionId,
  onOpenEvidence,
}: {
  missionId: string
  onOpenEvidence: (evidenceId: string, missionId: string) => void
}) {
  const { coverage, error } = useCoverage(missionId || null)
  if (error) return <p className="text-xs text-red-600">Couverture indisponible : {error}</p>
  if (!coverage) return <p className="text-xs text-slate-400">Chargement de la couverture…</p>
  return <CoverageMap coverage={coverage} onOpenEvidence={onOpenEvidence} missionId={missionId} />
}


function DiffInline({ missionId, targetRunId }: { missionId: string; targetRunId: string }) {
  const runs = useRunIds(missionId)
  const others = runs.filter((r) => r !== targetRunId)
  if (others.length === 0) return null
  const baseRun = others[others.length - 1] // run précédent le plus ancien lié au thread
  const { diff, error, loading } = useRunDiff(missionId, baseRun, targetRunId)
  if (loading) return <p className="text-xs text-slate-400">Comparaison…</p>
  if (error) return <p className="text-xs text-slate-400">Différentiel indisponible : {error}</p>
  if (!diff || diff.entries.length === 0) return null
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2.5">
      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
        Différentiel vs {baseRun}
      </p>
      <BeforeAfterAuditView diff={diff} onVerifyFix={(controlId, title) => console.info('verify-fix', controlId, title)} />
    </div>
  )
}

function useRunIds(missionId: string): string[] {
  const [ids, setIds] = useState<string[]>([])
  useEffect(() => {
    let cancelled = false
    fetch(`${API_BASE}/api/missions/${missionId}/runs`)
      .then((r) => r.json())
      .then((d) => { if (!cancelled) setIds((d.runs ?? []).map((r: { id: string }) => r.id)) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [missionId])
  return ids
}

/** Un run : en-tête permanent (statut, budget, contrôles) + contenu de l'onglet actif. */
function RunSection({
  runId,
  approvedActiveTests,
  tab,
  onOpenEvidence,
  onSteer,
  onVerifyFix,
}: {
  runId: string
  approvedActiveTests: boolean
  tab: Tab
  onOpenEvidence: (evidenceId: string, missionId: string) => void
  onSteer?: (instruction: string) => void
  onVerifyFix?: (findingId: string) => void
}) {
  const [run, setRun] = useState<AuditRun | null>(null)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [findings, setFindings] = useState<Finding[]>([])
  const [notice, setNotice] = useState<string | null>(null)

  const reload = () => {
    getRun(runId)
      .then((data) => setRun(data.run))
      .catch(() => setNotice('Run inaccessible'))
  }
  const reloadFindings = () => {
    runFindings(runId)
      .then((data) => setFindings(data.findings))
      .catch(() => setFindings([]))
  }

  useEffect(() => {
    reload()
    reloadFindings()
    const sub = subscribeRunEvents(runId, {
      onEvent: (ev) => {
        setEvents((prev) => [...prev.slice(-199), ev])
        if (ev.type.startsWith('run_') || ev.type.startsWith('investigation_')) reload()
        if (ev.type === 'finding' || ev.type.startsWith('run_')) reloadFindings()
      },
      onEnd: () => {
        reload()
        reloadFindings()
      },
    })
    return () => sub.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  const act = async (fn: () => Promise<unknown>, label: string) => {
    try {
      await fn()
      setNotice(`${label} — demandé`)
      reload()
    } catch (err) {
      setNotice(`${label} refusé : ${(err as Error).message}`)
    }
  }

  const hypotheses = useHypotheses(events)
  const tools = events.filter((e) => e.type === 'tool_started')
  const evidences = events.filter((e) => e.type === 'evidence')
  const needsInput = events.filter((e) => e.type === 'info_request' || e.type === 'needs_input')
  const steering = events.filter((e) => e.type === 'steering_received' || e.type === 'steering_applied')
  const decisions = events.filter((e) => e.type === 'investigation_decision')
  const privacy = events.filter((e) => e.type === 'privacy_preview')
  const status = run?.status ?? '…'
  const paused = status === 'paused'
  const missionId = run?.mission_id ?? ''

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-slate-100 px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <Link to={`/runs/${runId}`} className="truncate font-mono text-xs font-medium text-indigo-600 hover:underline">
            {runId}
          </Link>
          <StatusChip status={status} />
        </div>
        {run?.stop_reason && <p className="mt-1 text-[11px] text-slate-400">arrêt : {run.stop_reason}</p>}
        {notice && <p className="mt-1 text-[11px] text-amber-700">{notice}</p>}

        <div className="mt-2.5 space-y-2">
          <BudgetBar run={run} events={events} />
        {privacy.length > 0 && (
          <div className="rounded-xl bg-indigo-50/70 px-3 py-2">
            <p className="flex items-center gap-1.5 text-[11px] font-semibold text-indigo-800">
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7l8-4z" />
              </svg>
              Exposition IA (contexte envoyé au provider)
            </p>
            {(() => {
              const last = privacy[privacy.length - 1]
              const data = last.data as Record<string, unknown>
              const cats = (data.categories as { category: string; count: number }[] | undefined) ?? []
              return (
                <div className="mt-1">
                  <p className="text-[11px] text-indigo-700">
                    {String(data.provider)}/{String(data.model)} · phase {String(data.phase)} ·{' '}
                    {String(data.total_redactions)} valeur(s) masquée(s) du contexte LLM
                  </p>
                  {cats.length > 0 && (
                    <p className="mt-0.5 flex flex-wrap gap-1">
                      {cats.slice(0, 5).map((c) => (
                        <span key={c.category} className="rounded bg-white px-1.5 py-0.5 text-[10px] text-indigo-600">
                          {c.category} ×{c.count}
                        </span>
                      ))}
                    </p>
                  )}
                  <p className="mt-0.5 text-[10px] leading-snug text-indigo-400">
                    masquage automatique (aide, pas une garantie) ; preuves immuables intactes
                  </p>
                </div>
              )
            })()}
          </div>
        )}
          {steering.length > 0 && (
          <div className="rounded-xl bg-sky-50 px-3 py-2">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-sky-700">Pilotage auditeur</p>
            {steering.map((e) => (
              <p key={e.seq} className="mt-0.5 text-[11px] leading-snug text-sky-800">
                {e.type === 'steering_applied' ? '✓ appliquée : ' : '⏳ reçue : '}
                {String((e.data as Record<string, unknown>).instruction ?? '')}
              </p>
            ))}
          </div>
        )}
        {needsInput.length > 0 && (
            <div className="rounded-xl bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800">
              {needsInput.map((e) => (
                <p key={e.seq}>❓ {String((e.data as Record<string, unknown>).message ?? 'question à l’auditeur')}</p>
              ))}
            </div>
          )}
          {!approvedActiveTests && (
            <div className="rounded-xl bg-violet-50 px-3 py-2 text-xs leading-relaxed text-violet-700">
              Tests actifs non approuvés —{' '}
              <Link to={`/missions/${missionId}`} className="font-semibold underline">
                approuver sur la page mission
              </Link>
            </div>
          )}
        </div>

        <div className="mt-2.5 flex flex-wrap gap-1.5">
          <button
            type="button"
            disabled={status !== 'running'}
            onClick={() => act(() => pauseRun(runId), 'Pause')}
            className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-amber-50 hover:text-amber-700 disabled:opacity-40"
          >
            Pause
          </button>
          <button
            type="button"
            disabled={status !== 'running'}
            onClick={() => act(() => stopRun(runId), 'Arrêt')}
            className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-red-50 hover:text-red-700 disabled:opacity-40"
          >
            Stop
          </button>
          {paused && (
            <button
              type="button"
              onClick={() => act(() => resumeRun(runId), 'Reprise')}
              className="rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-xs font-medium text-emerald-700 transition-colors hover:bg-emerald-100"
            >
              Reprendre
            </button>
          )}
          {paused && missionId && (
            <button
              type="button"
              onClick={() => act(() => extendBudget(missionId, 12, 180), 'Budget étendu')}
              className="rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1.5 text-xs font-medium text-indigo-700 transition-colors hover:bg-indigo-100"
            >
              + Budget
            </button>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {tab === 'overview' && (
          <div className="space-y-3">
            {decisions.length > 0 && (
              <div className="rounded-xl bg-slate-50 px-3 py-2.5">
                <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">Dernière décision</p>
                {(() => {
                  const last = decisions[decisions.length - 1]
                  const data = last.data as Record<string, unknown>
                  return (
                    <p className="mt-1 text-[13px] leading-relaxed text-slate-600">
                      <span className="font-medium text-slate-700">{String(data.decision ?? '—')}</span>
                      {data.rationale ? ` — ${String(data.rationale)}` : ''}
                    </p>
                  )
                })()}
              </div>
            )}
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="rounded-xl bg-slate-50 px-2 py-2.5">
                <p className="text-base font-semibold text-slate-700">{tools.length}</p>
                <p className="text-[11px] text-slate-400">appels d'outils</p>
              </div>
              <div className="rounded-xl bg-slate-50 px-2 py-2.5">
                <p className="text-base font-semibold text-slate-700">{evidences.length}</p>
                <p className="text-[11px] text-slate-400">preuves</p>
              </div>
              <div className="rounded-xl bg-slate-50 px-2 py-2.5">
                <p className="text-base font-semibold text-slate-700">{findings.length}</p>
                <p className="text-[11px] text-slate-400">constats</p>
              </div>
            </div>
            {missionId && runId && (
              <DiffInline missionId={missionId} targetRunId={runId} />
            )}
            <p className="px-1 text-[11px] leading-relaxed text-slate-400">
              Événements backend réels (SSE). Les autres onglets détaillent l'activité, les
              hypothèses, les preuves et les constats.
            </p>
          </div>
        )}

        {tab === 'tools' && (
          <div className="space-y-1.5">
            {tools.length === 0 ? (
              <p className="text-xs text-slate-400">Aucun outil exécuté pour l'instant.</p>
            ) : (
              tools.map((t) => {
                const data = t.data as Record<string, unknown>
                return (
                  <div key={t.seq} className="rounded-xl bg-slate-50 px-3 py-2">
                    <p className="font-mono text-xs text-slate-700">{String(data.tool ?? data.name ?? '?')}</p>
                    {Array.isArray(data.evidence_ids) && (data.evidence_ids as string[]).length > 0 ? (
                      <p className="mt-0.5 font-mono text-[11px] text-slate-400">
                        {(data.evidence_ids as string[]).join(', ')}
                      </p>
                    ) : null}
                  </div>
                )
              })
            )}
          </div>
        )}

        {tab === 'hypotheses' && (
          <HypothesisComparison
            hypotheses={hypotheses}
            onOpenEvidence={onOpenEvidence}
            missionId={missionId}
            onInvestigateAlternative={(hypId, altId, statement) => onSteer?.(
              `Investigue l'explication alternative ${altId} de l'hypothèse ${hypId} : « ${statement} » — confronte-la aux preuves déjà collectées.`,
            )}
          />
        )}

        {tab === 'evidence' && (
          <div className="space-y-1.5">
            {evidences.length === 0 ? (
              <p className="text-xs text-slate-400">Aucune preuve collectée pour l'instant.</p>
            ) : (
              evidences.map((e) => {
                const data = e.data as Record<string, unknown>
                return (
                  <button
                    key={e.seq}
                    type="button"
                    onClick={() => onOpenEvidence(String(data.id ?? ''), missionId)}
                    className="w-full rounded-xl bg-slate-50 px-3 py-2.5 text-left transition-colors hover:bg-violet-50"
                  >
                    <p className="truncate font-mono text-xs text-violet-700">{String(data.id ?? '')}</p>
                    <p className="mt-0.5 truncate text-[13px] text-slate-600">{String(data.title ?? '')}</p>
                    <p className="mt-0.5 text-[11px] text-slate-400">
                      {String(data.type ?? '?')}
                      {data.record_count != null ? ` · ${String(data.record_count)} enregistrement(s)` : ''}
                    </p>
                  </button>
                )
              })
            )}
          </div>
        )}

        {tab === 'coverage' && <CoverageSection missionId={missionId} onOpenEvidence={onOpenEvidence} />}

        {tab === 'findings' && (
          <div className="space-y-2.5">
            {findings.length === 0 ? (
              <p className="text-xs text-slate-400">
                Aucun constat — il faut des preuves suffisantes pour en produire (« preuves
                insuffisantes » est un résultat valide).
              </p>
            ) : (
              findings.map((f) => (
                <div key={f.id}>
                  <FindingCard finding={f} showReviewActions onReviewed={() => reloadFindings()} />
                  <ActionPlanView findingId={f.id} missionId={missionId} onOpenEvidence={onOpenEvidence} onVerifyFix={onVerifyFix} />
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/** Panneau Investigation (droite) : 360px en desktop large, tiroir overlay sous `xl`. */
export function InvestigationPanel({
  missionIds, runIds, onSteer, onVerifyFix, mobileOpen = false, onCloseMobile,
}: PanelProps & { onSteer?: (instruction: string) => void; onVerifyFix?: (findingId: string) => void }) {
  const [open, setOpen] = useState(true)
  const [missions, setMissions] = useState<AuditMission[]>([])
  const [selectedRun, setSelectedRun] = useState<string | null>(null)
  const [drawer, setDrawer] = useState<{ evidenceId: string; missionId: string } | null>(null)
  const [tab, setTab] = useState<Tab>('overview')

  useEffect(() => {
    let cancelled = false
    Promise.all(
      missionIds.slice(-5).map((mid) =>
        getMission(mid)
          .then((d) => d.mission)
          .catch(() => null),
      ),
    ).then((list) => {
      if (!cancelled) setMissions(list.filter((m): m is AuditMission => m != null))
    })
    return () => {
      cancelled = true
    }
  }, [missionIds])

  useEffect(() => {
    setSelectedRun((prev) => {
      if (prev && runIds.includes(prev)) return prev
      return runIds.length > 0 ? runIds[runIds.length - 1] : null
    })
  }, [runIds])

  const approvedActiveTests =
    missions.length === 0 || missions.every((m) => (m.approved_plan?.approved_actions?.length ?? 0) > 0)

  const content = (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-4 pt-3">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1.5 text-sm font-semibold text-slate-700"
        >
          Investigation
          <span className="text-xs text-slate-400">{open ? '▾' : '▸'}</span>
        </button>
        {onCloseMobile && (
          <button
            type="button"
            onClick={onCloseMobile}
            aria-label="Fermer le panneau investigation"
            className="rounded-lg px-2 py-1 text-xs text-slate-400 transition-colors hover:bg-slate-200 hover:text-slate-600 xl:hidden"
          >
            ✕
          </button>
        )}
      </div>

      {open && (
        <>
          {missions.length > 0 && (
            <div className="mx-3 mt-2 rounded-xl border border-slate-200/80 bg-white px-3.5 py-2.5">
              {missions.slice(-1).map((m) => (
                <div key={m.id}>
                  <Link
                    to={`/missions/${m.id}`}
                    className="block truncate text-sm font-medium text-slate-800 hover:text-indigo-600"
                  >
                    {m.title}
                  </Link>
                  <p className="mt-0.5 line-clamp-2 text-xs leading-snug text-slate-500">{m.objective}</p>
                </div>
              ))}
            </div>
          )}

          {runIds.length > 1 && (
            <label className="mx-3 mt-2 block rounded-xl border border-slate-200/80 bg-white px-3 py-2">
              <span className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-slate-400">
                Run affiché
              </span>
              <select
                value={selectedRun ?? ''}
                onChange={(e) => setSelectedRun(e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 font-mono text-xs text-slate-700 focus:border-indigo-300 focus:outline-none"
              >
                {runIds.map((rid) => (
                  <option key={rid} value={rid}>
                    {rid}
                  </option>
                ))}
              </select>
            </label>
          )}

          {runIds.length === 0 && (
            <p className="mx-3 mt-3 rounded-xl border border-dashed border-slate-200 bg-white p-5 text-center text-xs leading-relaxed text-slate-400">
              Aucun run lié. Demandez un audit à l'assistant pour en lancer un via le moteur existant.
            </p>
          )}

          {selectedRun && (
            <div className="mt-2.5 flex min-h-0 flex-1 flex-col">
              <RunSection
                runId={selectedRun}
                approvedActiveTests={approvedActiveTests}
                tab={tab}
                onOpenEvidence={(evidenceId, mid) => setDrawer({ evidenceId, missionId: mid })}
                onSteer={onSteer}
                onVerifyFix={onVerifyFix}
              />
            </div>
          )}

          {runIds.length > 0 && (
            <div className="mx-3 mb-3 mt-1 grid shrink-0 grid-cols-6 gap-0.5 rounded-xl bg-slate-200/70 p-0.5">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setTab(t.key)}
                  className={`rounded-lg px-1 py-1.5 text-[11px] font-medium transition-colors ${
                    tab === t.key ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          )}
        </>
      )}

      {/* tiroir de détail de preuve — rendu au niveau document, indépendant du panel */}
      {drawer && (
        <div className="fixed inset-0 z-50 flex" role="dialog" aria-label="Détail de preuve">
          <button
            type="button"
            aria-label="Fermer le détail de preuve"
            className="flex-1 bg-slate-900/40"
            onClick={() => setDrawer(null)}
          />
          <div className="al-event-in flex h-full w-full max-w-xl flex-col overflow-y-auto bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
              <p className="text-sm font-semibold text-slate-800">
                Preuve <code className="font-mono text-xs text-indigo-600">{drawer.evidenceId}</code>
              </p>
              <button
                type="button"
                onClick={() => setDrawer(null)}
                className="rounded-lg px-2 py-1 text-sm text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
              >
                ✕
              </button>
            </div>
            <div className="flex-1 p-5">
              <EvidenceDetailPanel evidenceId={drawer.evidenceId} missionId={drawer.missionId} />
            </div>
          </div>
        </div>
      )}
    </div>
  )

  return (
    <>
      {mobileOpen && (
        <button
          type="button"
          aria-label="Fermer le panneau investigation"
          onClick={onCloseMobile}
          className="fixed inset-0 z-30 bg-slate-900/40 xl:hidden"
        />
      )}
      <aside
        className={`fixed inset-y-0 right-0 z-40 w-[360px] shrink-0 border-l border-slate-200 bg-white transition-transform duration-200 xl:static xl:z-auto xl:translate-x-0 xl:bg-slate-50/60 ${
          mobileOpen ? 'translate-x-0' : 'translate-x-full xl:translate-x-0'
        } ${mobileOpen ? 'block' : 'hidden xl:block'}`}
        aria-label="Panneau investigation"
      >
        {content}
      </aside>
    </>
  )
}
