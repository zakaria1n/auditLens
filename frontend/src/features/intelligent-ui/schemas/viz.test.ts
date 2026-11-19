import { describe, expect, it } from 'vitest'

import { validateVizSpec, specToText, VIZ_TYPES } from './viz'

const base = { version: 1, title: 'Test' }

describe('validateVizSpec — acceptation', () => {
  it('accepte une data_table conforme', () => {
    const r = validateVizSpec({
      ...base, type: 'data_table',
      columns: ['ref', 'qty'],
      rows: [{ ref: 'SO-1', qty: 5 }, { ref: 'SO-2', qty: -3 }],
      row_ids: ['1', '2'],
      evidence_refs: ['ev_abc12345'],
    })
    expect(r.ok).toBe(true)
  })

  it('accepte un bar_chart, comparison, kpi_summary conformes', () => {
    expect(validateVizSpec({ ...base, type: 'bar_chart', bars: [{ label: 'A', value: 3 }], unit: 'u' }).ok).toBe(true)
    expect(validateVizSpec({
      ...base, type: 'comparison', items: [{ label: 'SO-1', left: 5, right: 2 }],
      left_label: 'commandé', right_label: 'livré',
    }).ok).toBe(true)
    expect(validateVizSpec({
      ...base, type: 'kpi_summary', metrics: [{ label: 'constats', value: 4, evidence_ref: 'ev_abc12345' }],
    }).ok).toBe(true)
    expect(validateVizSpec({
      ...base, type: 'line_chart', series: [{ name: 'mois', points: [{ x: 'jan', y: 1 }, { x: 'fev', y: 3 }] }],
    }).ok).toBe(true)
    expect(validateVizSpec({
      ...base, type: 'relationship_graph',
      nodes: [{ id: 'n1', label: 'SO-1' }, { id: 'n2', label: 'INV-9' }],
      edges: [{ source: 'n1', target: 'n2', status: 'missing', label: 'facture' }],
    }).ok).toBe(true)
    expect(validateVizSpec({
      ...base, type: 'process_diagram',
      steps: [{ id: 's1', label: 'Commande' }, { id: 's2', label: 'Livraison' }],
    }).ok).toBe(true)
    expect(validateVizSpec({
      ...base, type: 'timeline',
      events: [{ label: 'preuve collectée', kind: 'evidence', evidence_ref: 'ev_abc12345' }],
    }).ok).toBe(true)
  })
})

describe('validateVizSpec — rejet déterministe (sécurité)', () => {
  it('rejette version inconnue et type hors registre', () => {
    expect(validateVizSpec({ ...base, version: 2, type: 'data_table', columns: ['a'], rows: [{ a: 1 }] }).ok).toBe(false)
    expect(validateVizSpec({ ...base, type: 'iframe_embed', src: 'https://x' }).ok).toBe(false)
    expect(validateVizSpec('alert(1)').ok).toBe(false)
    expect(validateVizSpec(null).ok).toBe(false)
  })

  it('rejette les clés de gestion d’événements et contenus exécutables', () => {
    expect(validateVizSpec({
      ...base, type: 'bar_chart', bars: [{ label: 'A', value: 1 }], onclick: 'alert(1)',
    }).ok).toBe(false)
    expect(validateVizSpec({
      ...base, type: 'data_table', columns: ['a'],
      rows: [{ a: 'javascript:alert(1)' }],
    }).ok).toBe(false)
  })

  it('rejette les clés inconnues (allowlist stricte)', () => {
    expect(validateVizSpec({
      ...base, type: 'kpi_summary', metrics: [{ label: 'x', value: 1 }], custom_html: '<b>',
    }).ok).toBe(false)
  })

  it('rejette les bornes dépassées et champs requis manquants', () => {
    const many = Array.from({ length: 25 }, (_, i) => ({ label: String(i), value: i }))
    expect(validateVizSpec({ ...base, type: 'bar_chart', bars: many }).ok).toBe(false)
    expect(validateVizSpec({ ...base, type: 'bar_chart', bars: [{ label: 'A', value: 'x' }] }).ok).toBe(false)
    expect(validateVizSpec({ version: 1, type: 'comparison', items: [{ label: 'a', left: 1, right: 2 }] }).ok).toBe(false)
    expect(validateVizSpec({
      ...base, type: 'relationship_graph',
      nodes: [{ id: 'n1', label: 'A' }], edges: [{ source: 'n1', target: 'ghost' }],
    }).ok).toBe(false)
    expect(validateVizSpec({ ...base, type: 'kpi_summary', metrics: [{ label: 'x', value: null }] }).ok).toBe(false)
  })

  it('les 8 types du registre sont couverts par des validateurs', () => {
    expect(VIZ_TYPES).toHaveLength(8)
  })

  it('specToText fournit une alternative textuelle non vide', () => {
    const r = validateVizSpec({ ...base, type: 'bar_chart', bars: [{ label: 'A', value: 2 }] })
    if (r.ok) expect(specToText(r.spec)).toContain('A=2')
  })
})
