import { useState } from 'react'
import type { ReactNode } from 'react'

import type {
  BarChartSpec, ComparisonSpec, DataTableSpec, KpiSummarySpec, LineChartSpec,
  ProcessDiagramSpec, RelationshipGraphSpec, TimelineSpec, VizSpec,
} from '../schemas/viz'
import { specToText } from '../schemas/viz'

/** Interactions fournies par le chat (Phase 4 : handoff structuré vers l'agent). */
export interface VizCallbacks {
  onOpenEvidence?: (evidenceId: string) => void
  onInvestigateRecord?: (record: Record<string, unknown>, rowId?: string, sourceTitle?: string) => void
  onInvestigateLabel?: (label: string, sourceTitle?: string) => void
}

function EvidenceChips({ refs, onOpenEvidence }: { refs?: string[]; onOpenEvidence?: (id: string) => void }) {
  if (!refs?.length) return null
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      {refs.map((ref) => (
        <button
          key={ref}
          type="button"
          onClick={() => onOpenEvidence?.(ref)}
          className="rounded-md border border-brand-200 bg-brand-50 px-1.5 py-0.5 font-mono text-[10px] text-brand-700 transition-colors hover:bg-brand-100"
          title="Ouvrir la preuve source"
        >
          {ref}
        </button>
      ))}
    </div>
  )
}

/** Cadre commun : titre, note, preuves, alternative textuelle pour lecteurs d'écran. */
export function VizFrame({ spec, children, onOpenEvidence }: { spec: VizSpec; children: ReactNode; onOpenEvidence?: (id: string) => void }) {
  return (
    <figure className="my-2 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-card">
      <figcaption className="flex items-center justify-between gap-3 border-b border-slate-100 px-3.5 py-2.5">
        <span className="min-w-0 truncate text-[13px] font-semibold text-ink-700">{spec.title}</span>
        <span className="shrink-0 rounded-md bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-ink-400">
          {spec.type.replace('_', ' ')}
        </span>
      </figcaption>
      <div className="px-3.5 py-3">{children}</div>
      {(spec.note || spec.evidence_refs?.length) && (
        <div className="border-t border-slate-100 px-3.5 py-2">
          {spec.note && <p className="text-[11px] leading-snug text-ink-400">{spec.note}</p>}
          <EvidenceChips refs={spec.evidence_refs} onOpenEvidence={onOpenEvidence} />
        </div>
      )}
      {/* alternative textuelle complète pour lecteurs d'écran */}
      <span className="sr-only">{specToText(spec)}</span>
    </figure>
  )
}

function fmt(n: number, unit?: string): string {
  const s = Number.isInteger(n) ? String(n) : n.toFixed(2)
  return unit ? `${s} ${unit}` : s
}

// ---------------------------------------------------------------- data_table

export function DataTableViz({ spec, callbacks }: { spec: DataTableSpec; callbacks?: VizCallbacks }) {
  const [selected, setSelected] = useState<number | null>(null)
  return (
    <VizFrame spec={spec} onOpenEvidence={callbacks?.onOpenEvidence}>
      <div className="max-h-72 overflow-auto rounded-lg border border-slate-200">
        <table className="w-full border-collapse text-left text-xs">
          <thead className="sticky top-0 bg-surface-2">
            <tr>
              {spec.columns.map((c) => (
                <th key={c} scope="col" className="whitespace-nowrap border-b border-slate-200 px-2.5 py-2 font-semibold text-ink-600">
                  {c}
                </th>
              ))}
              <th className="border-b border-slate-200 px-2 py-2">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {spec.rows.map((row, i) => (
              <tr
                key={i}
                className={selected === i ? 'bg-brand-50/70' : 'hover:bg-surface-1'}
                aria-selected={selected === i}
              >
                {spec.columns.map((c) => (
                  <td key={c} className="max-w-[220px] truncate border-b border-slate-100 px-2.5 py-1.5 text-ink-700">
                    {row[c] === null || row[c] === undefined ? <span className="text-ink-300">—</span> : String(row[c])}
                  </td>
                ))}
                <td className="whitespace-nowrap border-b border-slate-100 px-1 py-1.5 text-right">
                  <button
                    type="button"
                    onClick={() => setSelected(selected === i ? null : i)}
                    aria-expanded={selected === i}
                    className="rounded-md px-1.5 py-0.5 text-[10px] font-medium text-brand-600 hover:bg-brand-50"
                  >
                    Détail
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected !== null && (
        <div className="al-event-in mt-2 rounded-lg border border-brand-200 bg-brand-50/60 p-2.5">
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-brand-700">
            Enregistrement {spec.row_ids?.[selected] ?? `#${selected + 1}`}
          </p>
          <dl className="grid grid-cols-[minmax(0,140px)_1fr] gap-x-3 gap-y-1 text-[11px]">
            {spec.columns.map((c) => (
              <div key={c} className="contents">
                <dt className="truncate text-ink-400">{c}</dt>
                <dd className="min-w-0 break-words text-ink-700">{spec.rows[selected][c] ?? '—'}</dd>
              </div>
            ))}
          </dl>
          {callbacks?.onInvestigateRecord && (
            <button
              type="button"
              onClick={() => callbacks.onInvestigateRecord?.(spec.rows[selected], spec.row_ids?.[selected], spec.title)}
              className="mt-2 rounded-lg bg-brand-600 px-2.5 py-1 text-[11px] font-semibold text-white transition-colors hover:bg-brand-700"
            >
              Investiguer cet enregistrement
            </button>
          )}
        </div>
      )}
    </VizFrame>
  )
}

// ----------------------------------------------------------------- bar_chart

export function BarChartViz({ spec, callbacks }: { spec: BarChartSpec; callbacks?: VizCallbacks }) {
  const max = Math.max(...spec.bars.map((b) => Math.abs(b.value)), 1e-9)
  return (
    <VizFrame spec={spec} onOpenEvidence={callbacks?.onOpenEvidence}>
      <ul className="flex flex-col gap-1.5">
        {spec.bars.map((bar) => (
          <li key={bar.label} className="flex items-center gap-2.5">
            <span className="w-[130px] shrink-0 truncate text-right text-[11px] text-ink-500" title={bar.label}>
              {bar.label}
            </span>
            <span className="relative h-5 flex-1 overflow-hidden rounded-md bg-surface-2">
              <button
                type="button"
                aria-label={`${bar.label} : ${fmt(bar.value, spec.unit)}. Investiguer`}
                onClick={() => callbacks?.onInvestigateLabel?.(bar.label, spec.title)}
                className="absolute inset-y-0 left-0 rounded-md bg-brand-500/90 transition-colors hover:bg-brand-600"
                style={{ width: `${Math.max((Math.abs(bar.value) / max) * 100, 2)}%` }}
              />
            </span>
            <span className="w-20 shrink-0 font-mono text-[11px] text-ink-600">{fmt(bar.value, spec.unit)}</span>
          </li>
        ))}
      </ul>
    </VizFrame>
  )
}

// ---------------------------------------------------------------- line_chart

export function LineChartViz({ spec, callbacks }: { spec: LineChartSpec; callbacks?: VizCallbacks }) {
  const W = 560
  const H = 200
  const PAD = 34
  const all = spec.series.flatMap((s) => s.points)
  const xs = all.map((p) => p.x)
  const ys = all.map((p) => p.y)
  const xNums = xs.filter((x): x is number => typeof x === 'number')
  const yMin = Math.min(...ys, 0)
  const yMax = Math.max(...ys)
  const colors = ['#5046c9', '#0d9488', '#d97706', '#be4a5a', '#5b6478', '#7c3aed']
  const xScale = (p: { x: number | string }, idx: number, len: number): number => {
    if (typeof p.x === 'number' && xNums.length === all.length) {
      const xMin = Math.min(...xNums)
      const xMax = Math.max(...xNums)
      return xMax === xMin ? PAD : PAD + ((p.x - xMin) / (xMax - xMin)) * (W - 2 * PAD)
    }
    return len <= 1 ? W / 2 : PAD + (idx / (len - 1)) * (W - 2 * PAD)
  }
  const yScale = (y: number): number =>
    yMax === yMin ? H / 2 : H - PAD - ((y - yMin) / (yMax - yMin)) * (H - 2 * PAD)

  return (
    <VizFrame spec={spec} onOpenEvidence={callbacks?.onOpenEvidence}>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={specToText(spec)}>
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="#e2e8f0" />
        <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="#e2e8f0" />
        {spec.series.map((s, si) => (
          <g key={s.name}>
            <polyline
              fill="none"
              stroke={colors[si % colors.length]}
              strokeWidth="2"
              points={s.points.map((p, i) => `${xScale(p, i, s.points.length)},${yScale(p.y)}`).join(' ')}
            />
            {s.points.map((p, i) => (
              <circle key={i} cx={xScale(p, i, s.points.length)} cy={yScale(p.y)} r="3" fill={colors[si % colors.length]}>
                <title>{`${s.name} · ${String(p.x)} : ${p.y}`}</title>
              </circle>
            ))}
          </g>
        ))}
        {spec.x_label && <text x={W / 2} y={H - 6} textAnchor="middle" fontSize="10" fill="#8a93a6">{spec.x_label}</text>}
        {spec.y_label && <text x={8} y={14} fontSize="10" fill="#8a93a6">{spec.y_label}</text>}
      </svg>
      <ul className="mt-1 flex flex-wrap gap-3">
        {spec.series.map((s, si) => (
          <li key={s.name} className="flex items-center gap-1.5 text-[11px] text-ink-500">
            <span className="h-2 w-2 rounded-full" style={{ background: colors[si % colors.length] }} aria-hidden="true" />
            {s.name}
          </li>
        ))}
      </ul>
    </VizFrame>
  )
}

// ---------------------------------------------------------------- comparison

export function ComparisonViz({ spec, callbacks }: { spec: ComparisonSpec; callbacks?: VizCallbacks }) {
  const max = Math.max(...spec.items.flatMap((i) => [Math.abs(i.left), Math.abs(i.right)]), 1e-9)
  return (
    <VizFrame spec={spec} onOpenEvidence={callbacks?.onOpenEvidence}>
      <div className="mb-1.5 flex gap-2 pl-[140px] text-[10px] font-medium text-ink-400">
        <span className="flex-1 text-left">{spec.left_label}</span>
        <span className="flex-1 text-right">{spec.right_label}</span>
      </div>
      <ul className="flex flex-col gap-2">
        {spec.items.map((item) => (
          <li key={item.label}>
            <button
              type="button"
              onClick={() => callbacks?.onInvestigateLabel?.(item.label, spec.title)}
              className="group grid w-full grid-cols-[130px_1fr] items-center gap-2 rounded-lg text-left hover:bg-surface-1"
              title={`Comparer ${item.label}`}
            >
              <span className="truncate text-[11px] text-ink-600">{item.label}</span>
              <span className="grid grid-cols-2 gap-2">
                <span className="relative h-5 overflow-hidden rounded-md bg-surface-2">
                  <span
                    className="absolute inset-y-0 right-0 rounded-md bg-brand-500/85 group-hover:bg-brand-600"
                    style={{ width: `${Math.max((Math.abs(item.left) / max) * 100, 2)}%` }}
                  />
                  <span className="absolute inset-y-0 right-1.5 flex items-center font-mono text-[10px] text-ink-700">{fmt(item.left)}</span>
                </span>
                <span className="relative h-5 overflow-hidden rounded-md bg-surface-2">
                  <span
                    className="absolute inset-y-0 left-0 rounded-md bg-teal-600/80 group-hover:bg-teal-700"
                    style={{ width: `${Math.max((Math.abs(item.right) / max) * 100, 2)}%` }}
                  />
                  <span className="absolute inset-y-0 left-1.5 flex items-center font-mono text-[10px] text-white">{fmt(item.right, spec.unit)}</span>
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </VizFrame>
  )
}

// -------------------------------------------------------- relationship_graph

const EDGE_STYLES: Record<string, { stroke: string; dash?: string }> = {
  ok: { stroke: '#5046c9' },
  missing: { stroke: '#d97706', dash: '5 4' },
  conflict: { stroke: '#be4a5a' },
}

export function RelationshipGraphViz({ spec, callbacks }: { spec: RelationshipGraphSpec; callbacks?: VizCallbacks }) {
  const W = 560
  const H = 240
  const positions = new Map<string, { x: number; y: number }>()
  const cols = Math.ceil(Math.sqrt(spec.nodes.length))
  spec.nodes.forEach((node, i) => {
    const col = i % cols
    const row = Math.floor(i / cols)
    const rows = Math.ceil(spec.nodes.length / cols)
    positions.set(node.id, {
      x: cols === 1 ? W / 2 : 70 + (col / (cols - 1)) * (W - 140),
      y: rows === 1 ? H / 2 : 50 + (row / (rows - 1)) * (H - 100),
    })
  })
  return (
    <VizFrame spec={spec} onOpenEvidence={callbacks?.onOpenEvidence}>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={specToText(spec)}>
        {spec.edges.map((edge, i) => {
          const a = positions.get(edge.source)
          const b = positions.get(edge.target)
          if (!a || !b) return null
          const style = EDGE_STYLES[edge.status ?? 'ok']
          return (
            <g key={i}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={style.stroke} strokeWidth="1.6" strokeDasharray={style.dash}>
                <title>{`${edge.source} → ${edge.target}${edge.label ? ` · ${edge.label}` : ''}${edge.status && edge.status !== 'ok' ? ` (${edge.status})` : ''}`}</title>
              </line>
              {edge.label && (
                <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 4} textAnchor="middle" fontSize="9" fill="#8a93a6">
                  {edge.label}
                </text>
              )}
            </g>
          )
        })}
        {spec.nodes.map((node) => {
          const pos = positions.get(node.id)
          if (!pos) return null
          return (
            <g key={node.id}>
              <circle cx={pos.x} cy={pos.y} r="17" fill="#f4f3ff" stroke="#5046c9" strokeWidth="1.4" />
              <text x={pos.x} y={pos.y + 3.5} textAnchor="middle" fontSize="9.5" fontWeight="600" fill="#2c3449">
                {node.label.length > 9 ? `${node.label.slice(0, 8)}…` : node.label}
              </text>
              <title>{node.label}{node.kind ? ` (${node.kind})` : ''}</title>
            </g>
          )
        })}
      </svg>
      <ul className="mt-1 flex flex-wrap gap-3 text-[10px] text-ink-400">
        <li className="flex items-center gap-1"><span className="h-0.5 w-4 bg-brand-600" aria-hidden="true" /> lien vérifié</li>
        <li className="flex items-center gap-1"><span className="h-0.5 w-4 border-t border-dashed border-amber-600" aria-hidden="true" /> lien manquant</li>
        <li className="flex items-center gap-1"><span className="h-0.5 w-4 bg-red-400" aria-hidden="true" /> contradiction</li>
      </ul>
    </VizFrame>
  )
}

// ----------------------------------------------------------- process_diagram

export function ProcessDiagramViz({ spec, callbacks }: { spec: ProcessDiagramSpec; callbacks?: VizCallbacks }) {
  const vertical = spec.direction === 'vertical'
  return (
    <VizFrame spec={spec} onOpenEvidence={callbacks?.onOpenEvidence}>
      <ol className={`flex ${vertical ? 'flex-col' : 'flex-row overflow-x-auto'} items-stretch gap-0`}>
        {spec.steps.map((step, i) => (
          <li key={step.id} className={`flex ${vertical ? 'flex-col' : 'flex-row'} items-center`}>
            <div className="min-w-[130px] max-w-[190px] rounded-xl border border-brand-200 bg-brand-50/60 px-3 py-2">
              <p className="text-[12px] font-semibold text-ink-700">{step.label}</p>
              {step.detail && <p className="mt-0.5 text-[10.5px] leading-snug text-ink-400">{step.detail}</p>}
            </div>
            {i < spec.steps.length - 1 && (
              <span className={`mx-1.5 text-brand-400 ${vertical ? 'rotate-90' : ''}`} aria-hidden="true">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14m-6-6 6 6-6 6" /></svg>
              </span>
            )}
          </li>
        ))}
      </ol>
    </VizFrame>
  )
}

// ------------------------------------------------------------------ timeline

const KIND_DOT: Record<string, string> = {
  tool: 'bg-brand-500',
  evidence: 'bg-emerald-500',
  hypothesis: 'bg-amber-500',
  decision: 'bg-red-400',
  run: 'bg-teal-600',
  other: 'bg-ink-300',
}

export function TimelineViz({ spec, callbacks }: { spec: TimelineSpec; callbacks?: VizCallbacks }) {
  return (
    <VizFrame spec={spec} onOpenEvidence={callbacks?.onOpenEvidence}>
      <ol className="relative flex flex-col gap-2.5 border-l border-slate-200 pl-4">
        {spec.events.map((event, i) => (
          <li key={i} className="relative">
            <span className={`absolute -left-[21.5px] top-1 h-2.5 w-2.5 rounded-full ring-2 ring-white ${KIND_DOT[event.kind ?? 'other']}`} aria-hidden="true" />
            <p className="text-[12px] font-medium text-ink-700">
              {event.label}
              {event.at && <span className="ml-2 font-mono text-[10px] text-ink-400">{event.at}</span>}
            </p>
            {event.detail && <p className="text-[11px] leading-snug text-ink-400">{event.detail}</p>}
            {event.evidence_ref && (
              <button
                type="button"
                onClick={() => callbacks?.onOpenEvidence?.(event.evidence_ref as string)}
                className="mt-0.5 rounded-md border border-brand-200 bg-brand-50 px-1.5 py-0.5 font-mono text-[10px] text-brand-700 hover:bg-brand-100"
              >
                {event.evidence_ref}
              </button>
            )}
          </li>
        ))}
      </ol>
    </VizFrame>
  )
}

// --------------------------------------------------------------- kpi_summary

export function KpiSummaryViz({ spec, callbacks }: { spec: KpiSummarySpec; callbacks?: VizCallbacks }) {
  return (
    <VizFrame spec={spec} onOpenEvidence={callbacks?.onOpenEvidence}>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {spec.metrics.map((metric) => (
          <div key={metric.label} className="rounded-xl border border-slate-200 bg-surface-1 px-3 py-2.5">
            <dt className="truncate text-[10px] font-semibold uppercase tracking-wide text-ink-400" title={metric.label}>
              {metric.label}
            </dt>
            <dd className="mt-0.5 text-lg font-semibold tracking-tight text-ink-900">
              {typeof metric.value === 'number' ? fmt(metric.value, metric.unit) : metric.value}
              {typeof metric.value === 'string' && metric.unit ? <span className="ml-1 text-xs text-ink-400">{metric.unit}</span> : null}
            </dd>
            {metric.hint && <p className="mt-0.5 text-[10px] leading-snug text-ink-400">{metric.hint}</p>}
            {metric.evidence_ref && (
              <button
                type="button"
                onClick={() => callbacks?.onOpenEvidence?.(metric.evidence_ref as string)}
                className="mt-1 rounded-md border border-brand-200 bg-brand-50 px-1.5 py-0.5 font-mono text-[9.5px] text-brand-700 hover:bg-brand-100"
              >
                {metric.evidence_ref}
              </button>
            )}
          </div>
        ))}
      </dl>
    </VizFrame>
  )
}
