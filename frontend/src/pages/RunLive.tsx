import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  extendBudget,
  getMission,
  getRun,
  pauseRun,
  resumeRun,
  runAssessments,
  runFindings,
  stopRun,
} from '../lib/api'
import { subscribeRunEvents } from '../lib/sse'
import { toolLabel } from '../lib/tools'
import type { Assessment, AuditMission, AuditRun, Finding, RunEvent } from '../lib/types'
import { errorMessage } from '../lib/useAsync'
import { AssessmentCard } from '../components/AssessmentCard'
import { EmptyState } from '../components/EmptyState'
import { FindingCard } from '../components/FindingCard'
import { PageHeader } from '../components/PageHeader'
import { Timeline } from '../components/Timeline'
import type { TimelineItem } from '../components/Timeline'
import {
  AlertIcon,
  CheckIcon,
  DocIcon,
  FlagIcon,
  PlayIcon,
  SearchIcon,
  ShieldIcon,
  Spinner,
  TargetIcon,
  XMarkIcon,
} from '../components/icons'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { severityTone, StatusBadge } from '../components/StatusBadge'

const ICONS = {
  run: <PlayIcon className="h-3 w-3" />,
  phase: <TargetIcon className="h-3 w-3" />,
  plan: <DocIcon className="h-3 w-3" />,
  tool: <SearchIcon className="h-3 w-3" />,
  evidence: <ShieldIcon className="h-3 w-3" />,
  finding: <FlagIcon className="h-3 w-3" />,
  warning: <AlertIcon className="h-3 w-3" />,
  ok: <CheckIcon className="h-3 w-3" />,
  ko: <XMarkIcon className="h-3 w-3" />,
}

interface PendingTool {
  itemIndex: number
  tool: string
}

/** Convertit les événements SSE bruts en items de timeline, en fusionnant chaque paire tool_started → tool_completed. */
function buildTimeline(events: RunEvent[], runId: string): TimelineItem[] {
  const items: TimelineItem[] = []
  const pending: PendingTool[] = []

  for (const ev of events) {
    const data = ev.data ?? {}
    switch (ev.type) {
      case 'run_started':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'blue',
          icon: ICONS.run,
          title: 'Run démarré',
          time: ev.at,
          body: (
            <p className="text-xs text-slate-500">
              provider : {String(data.provider_id ?? '—')} · model : {String(data.model_id ?? '—')}
            </p>
          ),
        })
        break

      case 'phase':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'indigo',
          icon: ICONS.phase,
          title: `Phase : ${String(data.phase ?? ev.at)}`,
          time: ev.at,
        })
        break

      case 'plan': {
        const steps = Array.isArray(data.steps) ? (data.steps as unknown[]) : []
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'violet',
          icon: ICONS.plan,
          title: `Plan généré — ${steps.length} étape(s)`,
          time: ev.at,
          body: (
            <p className="text-xs text-slate-500">
              {steps
                .map((s) => toolLabel(String((s as Record<string, unknown>)?.tool ?? '')))
                .join(' → ') || '—'}
            </p>
          ),
        })
        break
      }

      case 'tool_started': {
        const tool = String(data.tool ?? 'tool')
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'blue',
          icon: ICONS.tool,
          title: `${toolLabel(tool)} — en cours`,
          time: ev.at,
          running: true,
          body: (
            <div className="flex flex-col gap-1">
              {data.rationale ? <p className="text-xs text-slate-500">{String(data.rationale)}</p> : null}
              <p className="text-xs text-slate-400">
                <Spinner className="mr-1 inline h-3 w-3" /> outil : <code className="font-mono">{tool}</code>
              </p>
              {data.args != null && Object.keys(data.args as Record<string, unknown>).length > 0 ? (
                <details className="text-xs text-slate-400">
                  <summary className="cursor-pointer select-none hover:text-slate-600">détails techniques</summary>
                  <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2 font-mono text-[11px] text-slate-600">
                    {JSON.stringify(data.args, null, 2)}
                  </pre>
                </details>
              ) : null}
            </div>
          ),
        })
        pending.push({ itemIndex: items.length - 1, tool })
        break
      }

      case 'tool_completed': {
        const tool = String(data.tool ?? 'tool')
        const idx = [...pending].reverse().find((p) => p.tool === tool)
        const status = String(data.status ?? 'error')
        const body = (
          <div className="flex flex-col gap-1.5">
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <Badge tone={status === 'success' ? 'green' : status === 'partial' ? 'amber' : 'red'}>
                {status}
              </Badge>
              {data.latency_ms != null ? <span>latence : {String(data.latency_ms)} ms</span> : null}
              {data.record_count != null ? <span>{String(data.record_count)} enregistrement(s)</span> : null}
              <span>
                outil : <code className="font-mono">{tool}</code>
              </span>
            </div>
            {Array.isArray(data.evidence_ids) && (data.evidence_ids as string[]).length > 0 ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-slate-500">preuves :</span>
                {(data.evidence_ids as string[]).map((evId) => (
                  <Link
                    key={evId}
                    to={`/evidence?run_id=${runId}&focus=${evId}`}
                    className="rounded-md border border-indigo-200 bg-indigo-50 px-2 py-0.5 font-mono text-xs text-indigo-700 transition-colors duration-150 hover:bg-indigo-100"
                  >
                    {evId}
                  </Link>
                ))}
              </div>
            ) : null}
            {Array.isArray(data.warnings) && (data.warnings as string[]).length > 0 ? (
              <ul className="list-disc pl-4">
                {(data.warnings as string[]).map((w, i) => (
                  <li key={i} className="text-xs text-amber-700">
                    {w}
                  </li>
                ))}
              </ul>
            ) : null}
            {data.error ? <p className="text-xs text-red-600">Erreur : {String(data.error)}</p> : null}
          </div>
        )
        if (idx != null) {
          const item = items[idx.itemIndex]
          item.title = `${toolLabel(tool)} — terminé`
          item.running = false
          item.tone = status === 'success' ? 'green' : status === 'partial' ? 'amber' : 'red'
          item.icon = status === 'success' ? ICONS.ok : ICONS.ko
          item.body = body
          const p = pending.indexOf(idx)
          if (p >= 0) pending.splice(p, 1)
        } else {
          items.push({
            id: `ev-${ev.seq}`,
            tone: status === 'success' ? 'green' : 'red',
            icon: status === 'success' ? ICONS.ok : ICONS.ko,
            title: `${toolLabel(tool)} — terminé`,
            time: ev.at,
            body,
          })
        }
        break
      }

      case 'evidence':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'indigo',
          icon: ICONS.evidence,
          title: `Preuve collectée : ${String(data.title ?? data.id ?? '')}`,
          time: ev.at,
          body: (
            <p className="text-xs text-slate-500">
              type : {String(data.type ?? '—')}
              {data.record_count != null ? ` · ${String(data.record_count)} enregistrement(s)` : ''}
              {data.id ? (
                <>
                  {' · '}
                  <Link to={`/evidence?run_id=${runId}&focus=${String(data.id)}`} className="font-mono text-indigo-600 hover:underline">
                    {String(data.id)}
                  </Link>
                </>
              ) : null}
            </p>
          ),
        })
        break

      case 'finding':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'amber',
          icon: ICONS.finding,
          title: `Constat proposé : ${String(data.title ?? '')}`,
          time: ev.at,
          body: (
            <p className="text-xs text-slate-500">
              <Badge tone={severityTone(String(data.severity_proposed ?? 'info'))}>
                severity: {String(data.severity_proposed ?? 'info')}
              </Badge>{' '}
              {data.statement ? String(data.statement) : null}
            </p>
          ),
        })
        break

      case 'finding_rejected':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'red',
          icon: ICONS.ko,
          title: 'Constat rejeté par le validateur structurel',
          time: ev.at,
          body: <p className="text-xs text-red-600">{String(data.reason ?? '')}</p>,
        })
        break

      case 'assessment':
        items.push({
          id: `ev-${ev.seq}`,
          tone: String(data.result) === 'pass' ? 'green' : String(data.result) === 'fail' ? 'red' : 'amber',
          icon: String(data.result) === 'pass' ? ICONS.ok : String(data.result) === 'fail' ? ICONS.ko : ICONS.warning,
          title: `Assessment : ${String(data.control_id ?? '')}`,
          time: ev.at,
          body: (
            <p className="text-xs text-slate-500">
              résultat : <strong className="text-slate-700">{String(data.result ?? '—')}</strong>
              {Array.isArray(data.observations) && (data.observations as string[]).length > 0
                ? ` · ${String((data.observations as string[])[0])}`
                : null}
            </p>
          ),
        })
        break

      case 'warning':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'amber',
          icon: ICONS.warning,
          title: 'Avertissement',
          time: ev.at,
          body: <p className="text-xs text-amber-700">{String(data.message ?? JSON.stringify(data))}</p>,
        })
        break

      case 'run_completed':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'green',
          icon: ICONS.ok,
          title: `Run terminé — statut : ${String(data.status ?? 'completed')}`,
          time: ev.at,
          body: (
            <p className="text-xs text-slate-500">
              stop_reason : {String(data.stop_reason ?? '—')} · tool_calls : {String(data.tool_calls ?? '—')} ·
              findings : {String(data.findings ?? '—')}
            </p>
          ),
        })
        break

      case 'run_failed':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'red',
          icon: ICONS.ko,
          title: 'Run en échec',
          time: ev.at,
          body: <p className="text-xs text-red-600">{String(data.error ?? '')}</p>,
        })
        break

      case 'investigation_decision': {
        const kind = String(data.decision ?? '—')
        const label: Record<string, string> = {
          call_tool: 'outil',
          update_hypotheses: 'hypothèses',
          request_human_input: 'demande à l’auditeur',
          stop: 'arrêt',
        }
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'violet',
          icon: ICONS.plan,
          title: `Décision d'investigation (tour ${String(data.turn ?? '—')}${data.max_turns != null ? `/${String(data.max_turns)}` : ''}) : ${label[kind] ?? kind}`,
          time: ev.at,
          body: (
            <p className="text-xs text-slate-500">
              {data.tool ? <>outil : <code className="font-mono">{String(data.tool)}</code> · </> : null}
              {String(data.rationale ?? '')}
            </p>
          ),
        })
        break
      }

      case 'hypothesis_created':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'blue',
          icon: ICONS.plan,
          title: `Hypothèse créée : ${String(data.id ?? '')}`,
          time: ev.at,
          body: (
            <p className="text-xs text-slate-500">
              {String(data.statement ?? '')} <span className="text-slate-400">· statut : {String(data.status ?? 'open')}</span>
            </p>
          ),
        })
        break

      case 'hypothesis_updated':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'indigo',
          icon: ICONS.plan,
          title: `Hypothèse révisée : ${String(data.id ?? '')} → ${String(data.status ?? '')}`,
          time: ev.at,
          body: (
            <p className="text-xs text-slate-500">
              {String(data.statement ?? '')}
              {Array.isArray(data.evidence_refs) && (data.evidence_refs as string[]).length > 0
                ? <> · preuves : {(data.evidence_refs as string[]).join(', ')}</>
                : null}
            </p>
          ),
        })
        break

      case 'hypothesis_rejected':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'amber',
          icon: ICONS.warning,
          title: 'Hypothèse partiellement rejetée (preuves invalides)',
          time: ev.at,
          body: <p className="text-xs text-amber-700">{String(data.reason ?? '')}</p>,
        })
        break

      case 'info_request':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'amber',
          icon: ICONS.warning,
          title: "Demande d'information à l'auditeur",
          time: ev.at,
          body: <p className="text-xs text-slate-500">{String(data.message ?? '')}</p>,
        })
        break

      case 'investigation_stop':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'neutral',
          icon: ICONS.ok,
          title: 'Investigation arrêtée',
          time: ev.at,
          body: <p className="text-xs text-slate-500">{String(data.reason ?? '')}</p>,
        })
        break

      case 'investigation_paused':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'amber',
          icon: ICONS.warning,
          title: 'Investigation en pause — travail préservé (checkpoint)',
          time: ev.at,
          body: (
            <p className="text-xs text-slate-500">
              {String(data.reason ?? '')} · tour {String(data.turn ?? '—')} ·{' '}
              hypothèses : {String(data.hypotheses ?? 0)}
            </p>
          ),
        })
        break

      case 'budget_warning':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'amber',
          icon: ICONS.warning,
          title: 'Budget presque épuisé',
          time: ev.at,
          body: (
            <p className="text-xs text-amber-700">
              {Array.isArray(data.resources) ? (data.resources as string[]).join(' · ') : ''}
            </p>
          ),
        })
        break

      case 'pause_requested':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'amber',
          icon: ICONS.warning,
          title: "Demande de pause envoyée (prise en compte entre deux tours de l'agent)",
          time: ev.at,
        })
        break

      case 'stop_requested':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'amber',
          icon: ICONS.warning,
          title: "Demande d'annulation envoyée (prise en compte entre deux tours de l'agent)",
          time: ev.at,
        })
        break

      case 'run_paused':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'amber',
          icon: ICONS.warning,
          title: 'Run en pause — preuves et hypothèses conservées, reprise possible',
          time: ev.at,
          body: <p className="text-xs text-slate-500">stop_reason : {String(data.stop_reason ?? '—')}</p>,
        })
        break

      case 'run_resumed':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'indigo',
          icon: ICONS.run,
          title: `Run repris depuis le checkpoint (run d'origine : ${String(data.from_run ?? '—')})`,
          time: ev.at,
          body: <p className="text-xs text-slate-500">checkpoint : {String(data.checkpoint_id ?? '—')} · raison : {String(data.checkpoint_reason ?? '—')}</p>,
        })
        break

      case 'run_cancelled':
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'neutral',
          icon: ICONS.ko,
          title: 'Run annulé proprement (checkpoint conservé)',
          time: ev.at,
          body: <p className="text-xs text-slate-500">{String(data.reason ?? '')}</p>,
        })
        break

      default:
        items.push({
          id: `ev-${ev.seq}`,
          tone: 'neutral',
          icon: ICONS.phase,
          title: `Événement : ${ev.type}`,
          time: ev.at,
        })
    }
  }
  return items
}

export function RunLivePage() {
  const { runId = '' } = useParams()
  const [run, setRun] = useState<AuditRun | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [assessments, setAssessments] = useState<Assessment[]>([])
  const [findings, setFindings] = useState<Finding[]>([])
  const endRef = useRef<HTMLDivElement | null>(null)

  // état initial du run, puis flux SSE réel (historique + temps réel).
  useEffect(() => {
    let cancelled = false
    getRun(runId)
      .then((res) => {
        if (!cancelled) setRun(res.run)
      })
      .catch((err: unknown) => {
        if (!cancelled) setRunError(errorMessage(err))
      })
    return () => {
      cancelled = true
    }
  }, [runId])

  const refreshResults = () => {
    getRun(runId)
      .then((res) => setRun(res.run))
      .catch(() => undefined)
    runAssessments(runId)
      .then((res) => setAssessments(res.assessments))
      .catch(() => setAssessments([]))
    runFindings(runId)
      .then((res) => setFindings(res.findings))
      .catch(() => setFindings([]))
  }

  useEffect(() => {
    if (!runId) return
    const sub = subscribeRunEvents(runId, {
      onOpen: () => setConnected(true),
      onEvent: (ev) => {
        setEvents((prev) => {
          if (prev.some((e) => e.seq === ev.seq)) return prev
          return [...prev, ev].sort((a, b) => a.seq - b.seq)
        })
        if (ev.type === 'run_completed' || ev.type === 'run_failed') {
          refreshResults()
        }
      },
      onEnd: () => {
        setConnected(false)
        refreshResults()
      },
      onError: () => setConnected(false),
    })
    return () => sub.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  // Le scroll suit uniquement l'arrivée réelle d'événements.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'nearest', behavior: 'auto' })
  }, [events.length])

  const items = useMemo(() => buildTimeline(events, runId), [events, runId])
  const toolCompleted = events.filter((e) => e.type === 'tool_completed').length
  const decisionsUsed = events.filter((e) => e.type === 'investigation_decision').length
  const isLive = run?.status === 'running'
  const isPaused = run?.status === 'paused'
  const [mission, setMission] = useState<AuditMission | null>(null)
  const [controlError, setControlError] = useState<string | null>(null)

  useEffect(() => {
    if (!run?.mission_id) return
    getMission(run.mission_id)
      .then((res) => setMission(res.mission))
      .catch(() => undefined)
  }, [run?.mission_id])

  // Dernier instantané de budget réellement publié par le backend (événements ADR-15).
  const budget = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      const ev = events[i]
      const b = (ev.data ?? {}) as Record<string, unknown>
      if (ev.type === 'investigation_decision' && b.budget) return b.budget as Record<string, number>
      if (ev.type === 'investigation_paused' && b.budget) return b.budget as Record<string, number>
      if (ev.type === 'run_paused' && b.budget) return b.budget as Record<string, number>
    }
    return null
  }, [events])

  // Hypothèses courantes reconstruites depuis les événements réels (dernier état par id).
  const hypotheses = useMemo(() => {
    const byId = new Map<string, { id: string; statement: string; status: string; evidence_refs: string[]; at: string }>()
    for (const ev of events) {
      if (ev.type !== 'hypothesis_created' && ev.type !== 'hypothesis_updated') continue
      const d = ev.data as Record<string, unknown>
      byId.set(String(d.id ?? '?'), {
        id: String(d.id ?? '?'),
        statement: String(d.statement ?? ''),
        status: String(d.status ?? 'open'),
        evidence_refs: Array.isArray(d.evidence_refs) ? (d.evidence_refs as string[]) : [],
        at: ev.at,
      })
    }
    return [...byId.values()]
  }, [events])

  const [controlNotice, setControlNotice] = useState<string | null>(null)

  const doAction = async (action: 'pause' | 'stop' | 'resume' | 'extend') => {
    if (!run) return
    setControlError(null)
    setControlNotice(null)
    try {
      if (action === 'pause') {
        await pauseRun(runId)
        setControlNotice('Pause demandée — prise en compte entre deux tours de l’agent.')
      } else if (action === 'stop') {
        await stopRun(runId)
        setControlNotice('Arrêt demandé — prise en compte entre deux tours de l’agent.')
      } else if (action === 'resume') {
        const res = await resumeRun(runId)
        // La reprise crée un NOUVEAU run : l'auditeur le suit directement (sinon aucun feedback visible).
        window.location.href = `/runs/${res.run_id}`
        return
      } else if (action === 'extend' && run.mission_id) {
        await extendBudget(run.mission_id, 12, 120)
        setControlNotice('Budget étendu : +12 tools, +120 s. Vous pouvez reprendre l’investigation.')
        // Rafraîchit les limites affichées (sinon l'UI montre l'ancien budget).
        getMission(run.mission_id)
          .then((res) => setMission(res.mission))
          .catch(() => undefined)
      }
      getRun(runId)
        .then((res) => setRun(res.run))
        .catch(() => undefined)
    } catch (err: unknown) {
      setControlError(errorMessage(err))
    }
  }

  if (runError) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">
        Erreur : {runError}
      </div>
    )
  }

  return (
    <>
      <PageHeader
        title="Live Audit"
        description="Timeline alimentée exclusivement par les événements SSE du backend — aucun progrès simulé."
        actions={
          <>
            <Link to={`/evidence?run_id=${runId}`}>
              <Button variant="outline" size="sm">Evidence</Button>
            </Link>
            <Link to={`/findings?run_id=${runId}`}>
              <Button variant="outline" size="sm">Findings</Button>
            </Link>
            <Link to={`/runs/${runId}/report`}>
              <Button variant="outline" size="sm">Rapport</Button>
            </Link>
          </>
        }
      />

      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-5 gap-y-2 py-4 text-sm">
          {run ? (
            <>
              <StatusBadge value={run.status} pulsing={run.status === 'running'} />
              <span className="text-xs text-slate-500">
                provider : <strong className="text-slate-700">{run.provider_id}</strong> · model :{' '}
                <strong className="text-slate-700">{run.model_id}</strong>
              </span>
              <span className="text-xs text-slate-500">
                tool_calls : <strong className="text-slate-700">{toolCompleted}</strong>
                {run.tool_calls_used > 0 ? ` (${run.tool_calls_used} déclarés)` : ''}
              </span>
              {budget ? (
                <span className="text-xs text-slate-500">
                  budget outils :{' '}
                  <strong className="text-slate-700">
                    {String(budget.tool_calls_used ?? '—')}/{String(budget.max_tool_calls ?? '—')}
                  </strong>
                  {Number(budget.tokens_used ?? 0) > 0 ? (
                    <> · tokens : <strong className="text-slate-700">{String(budget.tokens_used)}</strong></>
                  ) : null}
                  {decisionsUsed > 0 ? (
                    <> · décisions : <strong className="text-slate-700">{decisionsUsed}</strong></>
                  ) : null}
                </span>
              ) : null}
              {mission ? (
                <span className="text-xs text-slate-500">
                  limites mission : {mission.limits.max_tool_calls} tools / {mission.limits.max_seconds}s
                </span>
              ) : null}
              {run.stop_reason ? (
                <span className="text-xs text-slate-500">stop_reason : {run.stop_reason}</span>
              ) : null}
              <span className={`text-xs ${connected ? 'text-emerald-600' : 'text-slate-400'}`}>
                {connected ? 'SSE connecté' : 'SSE déconnecté'}
              </span>
              {run.error ? <span className="text-xs text-red-600">erreur : {run.error}</span> : null}
              <div className="ml-auto flex gap-2">
                {isLive ? (
                  <>
                    <Button variant="outline" size="sm" onClick={() => doAction('pause')}>Pause</Button>
                    <Button variant="outline" size="sm" onClick={() => doAction('stop')}>Arrêter</Button>
                  </>
                ) : null}
                {isPaused ? (
                  <>
                    <Button variant="outline" size="sm" onClick={() => doAction('extend')}>
                      +12 tools / +120s
                    </Button>
                    <Button size="sm" onClick={() => doAction('resume')}>Reprendre</Button>
                  </>
                ) : null}
              </div>
              {controlError ? <span className="text-xs text-red-600">{controlError}</span> : null}
              {controlNotice ? <span className="text-xs text-emerald-700">{controlNotice}</span> : null}
            </>
          ) : (
            <span className="text-xs text-slate-500">Chargement du run…</span>
          )}
        </CardContent>
      </Card>

      {hypotheses.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Hypothèses d'investigation ({hypotheses.length})</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {hypotheses.map((h) => (
              <div key={h.id} className="rounded-lg border border-slate-200 px-3 py-2">
                <div className="flex flex-wrap items-baseline gap-2">
                  <Badge tone={h.status === 'supported' ? 'green' : h.status === 'rejected' ? 'red' : h.status === 'inconclusive' ? 'amber' : 'blue'}>
                    {h.status}
                  </Badge>
                  <span className="font-mono text-xs text-slate-400">{h.id}</span>
                  <span className="text-xs text-slate-400">{h.at}</span>
                </div>
                <p className="mt-1 text-sm text-slate-700">{h.statement}</p>
                {h.evidence_refs.length > 0 ? (
                  <p className="mt-1 text-xs text-slate-500">
                    preuves :{' '}
                    {h.evidence_refs.map((ref, i) => (
                      <span key={ref}>
                        {i > 0 ? ', ' : ''}
                        <Link to={`/evidence?run_id=${runId}&focus=${ref}`} className="font-mono text-indigo-600 hover:underline">
                          {ref}
                        </Link>
                      </span>
                    ))}
                  </p>
                ) : null}
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Timeline des événements
            {isLive ? <Badge tone="blue" pulsing>running</Badge> : null}
            <span className="ml-auto text-xs font-normal text-slate-400">{events.length} événement(s) reçu(s)</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {items.length === 0 ? (
            <EmptyState
              title="Aucun événement pour l'instant"
              description="La timeline se remplit dès que le backend émet un événement (run_started, tool_started…)."
            />
          ) : (
            <>
              <Timeline items={items} />
              <div ref={endRef} />
            </>
          )}
        </CardContent>
      </Card>

      {assessments.length > 0 ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-slate-900">Assessments ({assessments.length})</h2>
          <div className="flex flex-col gap-3">
            {assessments.map((a) => (
              <AssessmentCard key={a.id} assessment={a} />
            ))}
          </div>
        </section>
      ) : null}

      {findings.length > 0 ? (
        <section className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-900">Findings ({findings.length})</h2>
            <Link to={`/findings?run_id=${runId}`} className="text-xs font-medium text-indigo-600 hover:underline">
              Ouvrir la revue complète →
            </Link>
          </div>
          <div className="flex flex-col gap-3">
            {findings.map((f) => (
              <FindingCard key={f.id} finding={f} onReviewed={() => refreshResults()} />
            ))}
          </div>
        </section>
      ) : null}
    </>
  )
}
