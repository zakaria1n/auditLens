import { useMemo, useState } from 'react'

export interface CorrelationResult {
  left: { evidence_id: string; label: string; key: string; rows: number }
  right: { evidence_id: string; label: string; key: string; rows: number }
  links: {
    key: string
    status: 'matched' | 'uncertain'
    ambiguous?: boolean
    left: { evidence_id: string; label: string; row_index: number; record: Record<string, unknown> }
    right: { evidence_id: string; label: string; row_index: number; record: Record<string, unknown> }
    field_comparisons: {
      left_field: string; right_field: string
      left_value?: string; right_value?: string
      difference?: string; status: string
    }[]
  }[]
  unmatched_left: { evidence_id: string; label: string; row_index: number; key_value: string; record: Record<string, unknown> }[]
  unmatched_right: { evidence_id: string; label: string; row_index: number; key_value: string; record: Record<string, unknown> }[]
  conflicts: {
    key: string
    left: { evidence_id: string; label: string; row_index: number; field: string; value: string }
    right: { evidence_id: string; label: string; row_index: number; field: string; value: string }
    difference: string
  }[]
  stats: {
    matched: number; uncertain: number
    unmatched_left: number; unmatched_right: number
    conflicts: number; ambiguous_keys: number
  }
  mission_id: string
}

const NODE_H = 34
const GAP = 10

/**
 * Graphe de relations de preuves (Phase 3/10) : rend le résultat RÉEL du tool
 * `correlate_records`. SVG inline sans dépendance — nœuds gauche/droite, liens
 * solides (matched), pointillés (uncertain via normalisation), rouges (conflit).
 * Sélection d'un nœud => détails + preuves liées. Relations ambiguës signalées.
 */
export function CorrelationGraph({ result }: { result: CorrelationResult }) {
  const [selected, setSelected] = useState<{
    side: 'left' | 'right'
    row_index: number
    record: Record<string, unknown>
    evidence_id: string
    label: string
  } | null>(null)

  const { leftNodes, rightNodes, edges, height } = useMemo(() => {
    const leftKeys = Array.from(new Set(result.links.map((l) => l.key)))
    const leftNodes = leftKeys.map((key, i) => ({
      key, y: 30 + i * (NODE_H + GAP),
      links: result.links.filter((l) => l.key === key),
    }))
    const rightKeys = Array.from(new Set(result.links.map((l) => l.right.row_index)))
    const rightNodes = rightKeys.map((rowIndex, i) => ({
      row_index: rowIndex, y: 30 + i * (NODE_H + GAP),
      links: result.links.filter((l) => l.right.row_index === rowIndex),
    }))
    const maxRows = Math.max(leftNodes.length + result.unmatched_left.length,
                             rightNodes.length + result.unmatched_right.length, 1)
    const height = 30 + maxRows * (NODE_H + GAP) + 20
    const edges = result.links.map((l) => {
      const ln = leftNodes.find((n) => n.key === l.key)
      const rn = rightNodes.find((n) => n.row_index === l.right.row_index)
      const conflict = l.field_comparisons.some((c) => c.status === 'conflict')
      return {
        l, x1: 210, y1: ln ? ln.y + NODE_H / 2 : 30,
        x2: 390, y2: rn ? rn.y + NODE_H / 2 : 30,
        conflict, uncertain: l.status === 'uncertain',
      }
    })
    return { leftNodes, rightNodes, edges, height }
  }, [result])

  const label = (record: Record<string, unknown>): string => {
    const key = Object.keys(record).find((k) => k.endsWith('_id') || k === 'id') ?? Object.keys(record)[0]
    return String(record[key] ?? key)
  }

  return (
    <div className="al-event-in my-2 overflow-hidden rounded-xl border border-slate-200/80 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-3.5 py-2.5">
        <p className="text-xs font-medium text-slate-600">
          {result.stats.matched + result.stats.uncertain} lien(s) ·{' '}
          {result.stats.conflicts} conflit(s) ·{' '}
          {result.stats.unmatched_left + result.stats.unmatched_right} non-correspondance(s)
          {result.stats.ambiguous_keys > 0 && (
            <span className="text-amber-600"> · {result.stats.ambiguous_keys} clé(s) ambiguë(s)</span>
          )}
        </p>
        <a
          href={`/evidence?focus=${result.left.evidence_id}`}
          className="rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-[11px] text-brand-700 hover:bg-brand-100"
          title="Preuve de corrélation"
        >
          corrélation
        </a>
      </div>

      <div className="overflow-x-auto bg-slate-50/50 px-2 py-1">
        <svg width="620" height={height} className="min-w-[620px]">
          {edges.map((e, i) => (
            <line
              key={i}
              x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}
              stroke={e.conflict ? '#dc2626' : e.uncertain ? '#f59e0b' : '#059669'}
              strokeWidth={e.conflict ? 2 : 1.5}
              strokeDasharray={e.uncertain ? '5,4' : undefined}
              opacity={0.75}
            >
              <title>{`${e.l.key} : ${e.conflict ? 'CONFLIT de valeurs' : e.uncertain ? 'lien normalisé (incertain)' : 'lien vérifié'}`}</title>
            </line>
          ))}
          {leftNodes.map((n) => {
            const conflict = n.links.some((l) => l.field_comparisons.some((c) => c.status === 'conflict'))
            return (
              <g key={n.key} className="cursor-pointer" onClick={() => {
                const link = n.links[0]
                if (link) setSelected({ side: 'left', row_index: link.left.row_index, record: link.left.record, evidence_id: link.left.evidence_id, label: link.left.label })
              }}>
                <rect x={10} y={n.y} width={200} height={NODE_H} rx={8}
                      fill={conflict ? '#fef2f2' : 'white'} stroke={conflict ? '#dc2626' : '#cbd5e1'} />
                <text x={20} y={n.y + 21} className="fill-slate-700" fontSize={12}>{n.key.slice(0, 26)}</text>
              </g>
            )
          })}
          {rightNodes.map((n) => {
            const link = n.links[0]
            const record = link?.right.record ?? {}
            const conflict = n.links.some((l) => l.field_comparisons.some((c) => c.status === 'conflict'))
            return (
              <g key={n.row_index} className="cursor-pointer" onClick={() => {
                if (link) setSelected({ side: 'right', row_index: n.row_index, record, evidence_id: link.right.evidence_id, label: link.right.label })
              }}>
                <rect x={390} y={n.y} width={200} height={NODE_H} rx={8}
                      fill={conflict ? '#fef2f2' : 'white'} stroke={conflict ? '#dc2626' : '#cbd5e1'} />
                <text x={400} y={n.y + 21} className="fill-slate-700" fontSize={12}>{label(record).slice(0, 26)}</text>
              </g>
            )
          })}
          <text x={10} y={18} className="fill-slate-400" fontSize={11}>{result.left.label} ({result.left.key})</text>
          <text x={390} y={18} className="fill-slate-400" fontSize={11}>{result.right.label} ({result.right.key})</text>
          {/* non-correspondances listées sous le graphe comme nœuds grisés */}
          {result.unmatched_left.length > 0 && (
            <text x={10} y={height - 4} className="fill-slate-400" fontSize={11}>
              sans contrepartie droite : {result.unmatched_left.map((u) => u.key_value).join(', ').slice(0, 34)}
            </text>
          )}
          {result.unmatched_right.length > 0 && (
            <text x={390} y={height - 4} className="fill-slate-400" fontSize={11}>
              sans contrepartie gauche : {result.unmatched_right.map((u) => u.key_value).join(', ').slice(0, 34)}
            </text>
          )}
        </svg>
      </div>

      {selected && (
        <div className="border-t border-slate-100 bg-slate-50/70 px-3.5 py-3">
          <div className="mb-1.5 flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-700">
              {selected.label} · {selected.evidence_id} · ligne {selected.row_index}
            </p>
            <div className="flex items-center gap-2">
              <a
                href={`/evidence?focus=${selected.evidence_id}`}
                className="rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-[11px] text-brand-700 hover:bg-brand-100"
              >
                preuve {selected.evidence_id}
              </a>
              <button type="button" onClick={() => setSelected(null)} className="text-[11px] text-slate-400 hover:text-slate-700">✕</button>
            </div>
          </div>
          <pre className="max-h-40 overflow-auto rounded-lg bg-white p-2 font-mono text-[11px] text-slate-600">
            {JSON.stringify(selected.record, null, 2)}
          </pre>
        </div>
      )}

      {result.conflicts.length > 0 && (
        <div className="border-t border-slate-100 bg-red-50/60 px-3.5 py-2 text-[11px] text-red-800">
          <p className="mb-1 font-semibold">Conflits de valeurs (liens rouges)</p>
          {result.conflicts.slice(0, 5).map((c, i) => (
            <p key={i}>
              {c.key} : {c.left.field}={c.left.value} ≠ {c.right.field}={c.right.value} (écart {c.difference})
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
