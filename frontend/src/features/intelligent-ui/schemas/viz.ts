/**
 * Schéma de visualisation TYPIÉ et VERSIONNÉ (Phase 3 — Generative UI).
 *
 * Principe (mission P3) : « le LLM propose la présentation, l'application
 * valide et la rend ». Le modèle ne peut choisir qu'un type du registre
 * fini, avec des données bornées et traçables. Toute spécification non
 * conforme est rejetée par validateVizSpec → repli texte/tableau lisible.
 *
 * Sécurité : allowlist stricte des clés par type (aucune clé inconnue), rejet
 * de toute clé de gestion d'événement (on*), de tout contenu exécutable
 * (javascript:, <script), bornes de taille par collection. Aucune exécution
 * de code : le rendu est fait par des composants React approuvés uniquement.
 */

export const VIZ_VERSION = 1

export type VizType =
  | 'data_table'
  | 'bar_chart'
  | 'line_chart'
  | 'comparison'
  | 'relationship_graph'
  | 'process_diagram'
  | 'timeline'
  | 'kpi_summary'

export const VIZ_TYPES: readonly VizType[] = [
  'data_table', 'bar_chart', 'line_chart', 'comparison',
  'relationship_graph', 'process_diagram', 'timeline', 'kpi_summary',
]

/** Bornes de complexité — le rendu reste borné quel que soit le modèle. */
export const VIZ_LIMITS = {
  title: 140,
  note: 400,
  table_rows: 200,
  table_columns: 24,
  bars: 24,
  series: 6,
  points_per_series: 200,
  comparison_items: 24,
  nodes: 60,
  edges: 120,
  steps: 12,
  events: 60,
  metrics: 8,
  evidence_refs: 8,
} as const

export interface VizBase {
  version: typeof VIZ_VERSION
  type: VizType
  title: string
  note?: string
  evidence_refs?: string[]
}

export interface DataTableSpec extends VizBase {
  type: 'data_table'
  columns: string[]
  rows: Array<Record<string, string | number | boolean | null>>
  /** identifiants d'enregistrements sources, alignés sur rows (interactions P4). */
  row_ids?: string[]
}

export interface BarChartSpec extends VizBase {
  type: 'bar_chart'
  bars: Array<{ label: string; value: number }>
  unit?: string
}

export interface LineChartSpec extends VizBase {
  type: 'line_chart'
  series: Array<{ name: string; points: Array<{ x: number | string; y: number }> }>
  x_label?: string
  y_label?: string
}

export interface ComparisonSpec extends VizBase {
  type: 'comparison'
  items: Array<{ label: string; left: number; right: number }>
  left_label: string
  right_label: string
  unit?: string
}

export type GraphEdgeStatus = 'ok' | 'missing' | 'conflict'

export interface RelationshipGraphSpec extends VizBase {
  type: 'relationship_graph'
  nodes: Array<{ id: string; label: string; kind?: string }>
  edges: Array<{ source: id_field; target: id_field; label?: string; status?: GraphEdgeStatus }>
}

type id_field = string

export interface ProcessDiagramSpec extends VizBase {
  type: 'process_diagram'
  steps: Array<{ id: string; label: string; detail?: string }>
  direction?: 'horizontal' | 'vertical' | 'right-to-left' | 'bottom-to-top'
}

export type TimelineEventKind = 'tool' | 'evidence' | 'hypothesis' | 'decision' | 'run' | 'other'

export interface TimelineSpec extends VizBase {
  type: 'timeline'
  events: Array<{ label: string; at?: string; detail?: string; kind?: TimelineEventKind; evidence_ref?: string }>
}

export interface KpiSummarySpec extends VizBase {
  type: 'kpi_summary'
  metrics: Array<{ label: string; value: string | number; unit?: string; hint?: string; evidence_ref?: string }>
}

export type VizSpec =
  | DataTableSpec
  | BarChartSpec
  | LineChartSpec
  | ComparisonSpec
  | RelationshipGraphSpec
  | ProcessDiagramSpec
  | TimelineSpec
  | KpiSummarySpec

export type VizValidation = { ok: true; spec: VizSpec } | { ok: false; reason: string }

// ---------------------------------------------------------------------------
// Validation déterministe
// ---------------------------------------------------------------------------

const EVIDENCE_RE = /^ev_[a-z0-9]{6,40}$/
const ID_RE = /^[A-Za-z0-9_.:@\-\/]{1,120}$/
/** Contenu jamais accepté : gestionnaires d'événements et protocoles exécutables. */
const UNSAFE_KEY_RE = /^on[a-z]+$/i
const UNSAFE_VALUE_RE = /(?:javascript:|<script|data:text\/html)/i

const BASE_KEYS = ['version', 'type', 'title', 'note', 'evidence_refs'] as const

function fail(reason: string): VizValidation {
  return { ok: false, reason }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

function safeString(v: unknown, max: number): string | null {
  if (typeof v !== 'string') return null
  const trimmed = v.trim()
  if (!trimmed || trimmed.length > max) return null
  if (UNSAFE_VALUE_RE.test(trimmed)) return null
  return trimmed
}

function safeFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

function checkBase(raw: Record<string, unknown>, allowedExtra: readonly string[]): string | null {
  for (const key of Object.keys(raw)) {
    if (UNSAFE_KEY_RE.test(key)) return `clé interdite : ${key}`
    if (![...BASE_KEYS, ...allowedExtra].includes(key)) return `clé inconnue « ${key} » (schéma v1)`
  }
  const title = safeString(raw.title, VIZ_LIMITS.title)
  if (!title) return 'titre requis (1..140 caractères sûrs)'
  if (raw.note !== undefined && safeString(raw.note, VIZ_LIMITS.note) === null) return 'note invalide'
  if (raw.evidence_refs !== undefined) {
    if (!Array.isArray(raw.evidence_refs) || raw.evidence_refs.length > VIZ_LIMITS.evidence_refs) {
      return `evidence_refs limité à ${VIZ_LIMITS.evidence_refs}`
    }
    for (const ref of raw.evidence_refs) {
      if (typeof ref !== 'string' || !EVIDENCE_RE.test(ref)) return `référence de preuve invalide : ${String(ref).slice(0, 40)}`
    }
  }
  return null
}

function validateDataTable(raw: Record<string, unknown>): VizValidation {
  const baseErr = checkBase(raw, ['columns', 'rows', 'row_ids'])
  if (baseErr) return fail(baseErr)
  const columns = raw.columns
  if (!Array.isArray(columns) || columns.length === 0 || columns.length > VIZ_LIMITS.table_columns) {
    return fail(`columns requis (1..${VIZ_LIMITS.table_columns})`)
  }
  for (const c of columns) {
    if (typeof c !== 'string' || !c.trim()) return fail('colonnes invalides')
  }
  const rows = raw.rows
  if (!Array.isArray(rows) || rows.length === 0 || rows.length > VIZ_LIMITS.table_rows) {
    return fail(`rows requis (1..${VIZ_LIMITS.table_rows} lignes bornées)`)
  }
  for (const row of rows) {
    if (!isRecord(row)) return fail('chaque ligne doit être un objet')
    for (const key of Object.keys(row)) {
      if (UNSAFE_KEY_RE.test(key)) return fail(`clé de ligne interdite : ${key}`)
      const value = row[key]
      if (value !== null && typeof value !== 'string' && typeof value !== 'number' && typeof value !== 'boolean') {
        return fail('valeurs de ligne limitées à texte/nombre/booléen/null')
      }
      if (typeof value === 'string' && UNSAFE_VALUE_RE.test(value)) return fail('valeur de ligne non sûre')
    }
  }
  if (raw.row_ids !== undefined) {
    if (!Array.isArray(raw.row_ids) || raw.row_ids.length !== rows.length) {
      return fail('row_ids doit aligner rows (même longueur)')
    }
    for (const id of raw.row_ids) {
      if (typeof id !== 'string' || !ID_RE.test(id)) return fail('row_ids invalides')
    }
  }
  return { ok: true, spec: raw as unknown as DataTableSpec }
}

function validateBarChart(raw: Record<string, unknown>): VizValidation {
  const baseErr = checkBase(raw, ['bars', 'unit'])
  if (baseErr) return fail(baseErr)
  const bars = raw.bars
  if (!Array.isArray(bars) || bars.length === 0 || bars.length > VIZ_LIMITS.bars) {
    return fail(`bars requis (1..${VIZ_LIMITS.bars})`)
  }
  for (const bar of bars) {
    if (!isRecord(bar)) return fail('barres invalides')
    if (typeof bar.label !== 'string' || !bar.label.trim()) return fail('libellé de barre requis')
    if (!safeFiniteNumber(bar.value)) return fail('valeur de barre numérique finie requise')
    if (Object.keys(bar).some((k) => !['label', 'value'].includes(k))) return fail('clés de barre inconnues')
  }
  if (raw.unit !== undefined && safeString(raw.unit, 12) === null) return fail('unité invalide')
  return { ok: true, spec: raw as unknown as BarChartSpec }
}

function validateLineChart(raw: Record<string, unknown>): VizValidation {
  const baseErr = checkBase(raw, ['series', 'x_label', 'y_label'])
  if (baseErr) return fail(baseErr)
  const series = raw.series
  if (!Array.isArray(series) || series.length === 0 || series.length > VIZ_LIMITS.series) {
    return fail(`series requis (1..${VIZ_LIMITS.series})`)
  }
  for (const s of series) {
    if (!isRecord(s)) return fail('séries invalides')
    if (typeof s.name !== 'string' || !s.name.trim()) return fail('nom de série requis')
    if (!Array.isArray(s.points) || s.points.length === 0 || s.points.length > VIZ_LIMITS.points_per_series) {
      return fail(`points bornés (1..${VIZ_LIMITS.points_per_series} par série)`)
    }
    for (const p of s.points) {
      if (!isRecord(p) || !safeFiniteNumber(p.y)) return fail('points {x, y:numérique} requis')
      if (typeof p.x !== 'string' && typeof p.x !== 'number') return fail('x texte ou numérique requis')
      if (Object.keys(p).some((k) => !['x', 'y'].includes(k))) return fail('clés de point inconnues')
    }
    if (Object.keys(s).some((k) => !['name', 'points'].includes(k))) return fail('clés de série inconnues')
  }
  return { ok: true, spec: raw as unknown as LineChartSpec }
}

function validateComparison(raw: Record<string, unknown>): VizValidation {
  const baseErr = checkBase(raw, ['items', 'left_label', 'right_label', 'unit'])
  if (baseErr) return fail(baseErr)
  if (typeof raw.left_label !== 'string' || !raw.left_label.trim()) return fail('left_label requis')
  if (typeof raw.right_label !== 'string' || !raw.right_label.trim()) return fail('right_label requis')
  const items = raw.items
  if (!Array.isArray(items) || items.length === 0 || items.length > VIZ_LIMITS.comparison_items) {
    return fail(`items requis (1..${VIZ_LIMITS.comparison_items})`)
  }
  for (const item of items) {
    if (!isRecord(item)) return fail('items invalides')
    if (typeof item.label !== 'string' || !item.label.trim()) return fail('libellé d’item requis')
    if (!safeFiniteNumber(item.left) || !safeFiniteNumber(item.right)) return fail('left/right numériques requis')
    if (Object.keys(item).some((k) => !['label', 'left', 'right'].includes(k))) return fail('clés d’item inconnues')
  }
  return { ok: true, spec: raw as unknown as ComparisonSpec }
}

function validateRelationshipGraph(raw: Record<string, unknown>): VizValidation {
  const baseErr = checkBase(raw, ['nodes', 'edges'])
  if (baseErr) return fail(baseErr)
  const nodes = raw.nodes
  if (!Array.isArray(nodes) || nodes.length === 0 || nodes.length > VIZ_LIMITS.nodes) {
    return fail(`nodes requis (1..${VIZ_LIMITS.nodes})`)
  }
  const ids = new Set<string>()
  for (const node of nodes) {
    if (!isRecord(node)) return fail('nœuds invalides')
    const id = typeof node.id === 'string' && ID_RE.test(node.id) ? node.id : null
    if (!id) return fail('id de nœud requis (format sûr)')
    if (ids.has(id)) return fail('identifiant de nœud en double')
    ids.add(id)
    if (!safeString(node.label, VIZ_LIMITS.note)) return fail('libellé de nœud invalide ou trop long')
    if (node.kind !== undefined && !safeString(node.kind, VIZ_LIMITS.title)) return fail('type de nœud invalide')
    if (Object.keys(node).some((k) => !['id', 'label', 'kind'].includes(k))) return fail('clés de nœud inconnues')
  }
  const edges = raw.edges
  if (!Array.isArray(edges) || edges.length === 0 || edges.length > VIZ_LIMITS.edges) {
    return fail(`edges requis (1..${VIZ_LIMITS.edges})`)
  }
  for (const edge of edges) {
    if (!isRecord(edge)) return fail('arêtes invalides')
    if (typeof edge.source !== 'string' || !ids.has(edge.source)) return fail(`source inconnue : ${String(edge.source).slice(0, 40)}`)
    if (typeof edge.target !== 'string' || !ids.has(edge.target)) return fail(`target inconnue : ${String(edge.target).slice(0, 40)}`)
    if (edge.label !== undefined && !safeString(edge.label, VIZ_LIMITS.title)) return fail('libellé de lien invalide')
    if (edge.status !== undefined && !['ok', 'missing', 'conflict'].includes(edge.status as string)) {
      return fail('status limité à ok|missing|conflict')
    }
    if (Object.keys(edge).some((k) => !['source', 'target', 'label', 'status'].includes(k))) return fail('clés d’arête inconnues')
  }
  return { ok: true, spec: raw as unknown as RelationshipGraphSpec }
}

function validateProcessDiagram(raw: Record<string, unknown>): VizValidation {
  const baseErr = checkBase(raw, ['steps', 'direction'])
  if (baseErr) return fail(baseErr)
  const steps = raw.steps
  if (!Array.isArray(steps) || steps.length < 2 || steps.length > VIZ_LIMITS.steps) {
    return fail(`steps requis (2..${VIZ_LIMITS.steps})`)
  }
  for (const step of steps) {
    if (!isRecord(step)) return fail('étapes invalides')
    if (typeof step.id !== 'string' || !ID_RE.test(step.id)) return fail('id d’étape requis')
    if (typeof step.label !== 'string' || !step.label.trim()) return fail('libellé d’étape requis')
    if (Object.keys(step).some((k) => !['id', 'label', 'detail'].includes(k))) return fail('clés d’étape inconnues')
  }
  const aliases: Record<string, ProcessDiagramSpec['direction']> = {
    lr: 'horizontal', 'left-to-right': 'horizontal', horizontal: 'horizontal',
    tb: 'vertical', td: 'vertical', 'top-to-bottom': 'vertical', vertical: 'vertical',
    rl: 'right-to-left', 'right-to-left': 'right-to-left',
    bt: 'bottom-to-top', 'bottom-to-top': 'bottom-to-top',
  }
  const direction = raw.direction === undefined ? 'horizontal'
    : typeof raw.direction === 'string' ? aliases[raw.direction.trim().toLowerCase()] : undefined
  if (!direction) return fail('direction attendue : LR, TB, TD, RL ou BT')
  return { ok: true, spec: { ...raw, direction } as unknown as ProcessDiagramSpec }
}

const TIMELINE_KINDS: readonly string[] = ['tool', 'evidence', 'hypothesis', 'decision', 'run', 'other']

function validateTimeline(raw: Record<string, unknown>): VizValidation {
  const baseErr = checkBase(raw, ['events'])
  if (baseErr) return fail(baseErr)
  const events = raw.events
  if (!Array.isArray(events) || events.length === 0 || events.length > VIZ_LIMITS.events) {
    return fail(`events requis (1..${VIZ_LIMITS.events})`)
  }
  for (const event of events) {
    if (!isRecord(event)) return fail('événements invalides')
    if (typeof event.label !== 'string' || !event.label.trim()) return fail('libellé d’événement requis')
    if (event.kind !== undefined && !TIMELINE_KINDS.includes(event.kind as string)) {
      return fail(`kind limité à ${TIMELINE_KINDS.join('|')}`)
    }
    if (event.evidence_ref !== undefined && (typeof event.evidence_ref !== 'string' || !EVIDENCE_RE.test(event.evidence_ref))) {
      return fail('evidence_ref invalide')
    }
    if (Object.keys(event).some((k) => !['label', 'at', 'detail', 'kind', 'evidence_ref'].includes(k))) {
      return fail('clés d’événement inconnues')
    }
  }
  return { ok: true, spec: raw as unknown as TimelineSpec }
}

function validateKpiSummary(raw: Record<string, unknown>): VizValidation {
  const baseErr = checkBase(raw, ['metrics'])
  if (baseErr) return fail(baseErr)
  const metrics = raw.metrics
  if (!Array.isArray(metrics) || metrics.length === 0 || metrics.length > VIZ_LIMITS.metrics) {
    return fail(`metrics requis (1..${VIZ_LIMITS.metrics}) — aucune métrique fabriquée`)
  }
  for (const metric of metrics) {
    if (!isRecord(metric)) return fail('métriques invalides')
    if (typeof metric.label !== 'string' || !metric.label.trim()) return fail('libellé de métrique requis')
    if (typeof metric.value !== 'string' && !safeFiniteNumber(metric.value)) {
      return fail('valeur texte ou numérique requise (jamais null/fabrication)')
    }
    if (metric.evidence_ref !== undefined && (typeof metric.evidence_ref !== 'string' || !EVIDENCE_RE.test(metric.evidence_ref))) {
      return fail('evidence_ref invalide')
    }
    if (Object.keys(metric).some((k) => !['label', 'value', 'unit', 'hint', 'evidence_ref'].includes(k))) {
      return fail('clés de métrique inconnues')
    }
  }
  return { ok: true, spec: raw as unknown as KpiSummarySpec }
}

const VALIDATORS: Record<VizType, (raw: Record<string, unknown>) => VizValidation> = {
  data_table: validateDataTable,
  bar_chart: validateBarChart,
  line_chart: validateLineChart,
  comparison: validateComparison,
  relationship_graph: validateRelationshipGraph,
  process_diagram: validateProcessDiagram,
  timeline: validateTimeline,
  kpi_summary: validateKpiSummary,
}

/** Valide une spécification inconnue (JSON du modèle). Ne lève jamais : résultat discriminé. */
export function validateVizSpec(raw: unknown): VizValidation {
  if (!isRecord(raw)) return fail('spécification non-objet')
  if (raw.version !== VIZ_VERSION) return fail(`version non supportée : ${String(raw.version)} (v1 attendue)`)
  const type = raw.type
  if (typeof type !== 'string' || !VIZ_TYPES.includes(type as VizType)) {
    return fail(`type inconnu : ${String(type).slice(0, 40)} — registre : ${VIZ_TYPES.join(', ')}`)
  }
  return VALIDATORS[type as VizType](raw)
}

/** Alternative textuelle (accessibilité + repli) — jamais vide. */
export function specToText(spec: VizSpec): string {
  const parts: string[] = [`${spec.title} (${spec.type})`]
  if (spec.type === 'data_table') {
    parts.push(`${spec.rows.length} ligne(s), colonnes : ${spec.columns.join(', ')}`)
  } else if (spec.type === 'bar_chart') {
    parts.push(spec.bars.map((b) => `${b.label}=${b.value}`).join('; '))
  } else if (spec.type === 'line_chart') {
    parts.push(spec.series.map((s) => `${s.name} (${s.points.length} points)`).join('; '))
  } else if (spec.type === 'comparison') {
    parts.push(`${spec.left_label} vs ${spec.right_label} : ${spec.items.map((i) => i.label).join(', ')}`)
  } else if (spec.type === 'relationship_graph') {
    parts.push(`${spec.nodes.length} nœud(s), ${spec.edges.length} lien(s)`)
  } else if (spec.type === 'process_diagram') {
    parts.push(spec.steps.map((s) => s.label).join(' → '))
  } else if (spec.type === 'timeline') {
    parts.push(`${spec.events.length} événement(s)`)
  } else if (spec.type === 'kpi_summary') {
    parts.push(spec.metrics.map((m) => `${m.label}=${m.value}`).join('; '))
  }
  return parts.join(' — ')
}
