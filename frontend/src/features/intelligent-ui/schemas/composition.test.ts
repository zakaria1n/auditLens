import { describe, expect, it } from 'vitest'
import { validateComposition } from './composition'

const root = { version: 2, type: 'composition', mode: 'conceptual' }
const graph = { version: 1, type: 'relationship_graph', title: 'Flux', nodes: [{ id: 'a', label: 'Agent' }, { id: 'b', label: 'Outils' }], edges: [{ source: 'a', target: 'b' }] }

describe('composition déclarative', () => {
  it('compose texte, disposition, graphe v1 et détails', () => {
    expect(validateComposition({ ...root, children: [
      { type: 'heading', text: 'Fonctionnement' },
      { type: 'row', children: [{ type: 'paragraph', text: 'Le processus' }, { type: 'visualization', spec: graph }] },
      { type: 'accordion', title: 'Détails', children: [{ type: 'paragraph', text: 'Vérification' }] },
    ] }).ok).toBe(true)
  })
  it('refuse les actions, le code HTML, les ressources et les preuves non vérifiées', () => {
    for (const child of [
      { type: 'paragraph', text: 'texte', onclick: 'alert(1)' },
      { type: 'paragraph', text: '<script>alert(1)</script>' },
      { type: 'paragraph', text: 'https://exemple.test/x' },
      { type: 'visualization', spec: { ...graph, evidence_refs: ['ev_abcd1234'] } },
      { type: 'button', action: 'delete' },
    ]) expect(validateComposition({ ...root, children: [child] }).ok).toBe(false)
    expect(validateComposition({ ...root, mode: 'evidence', children: [{ type: 'heading', text: 'Résultat' }] }).ok).toBe(false)
  })
  it('borne la profondeur et refuse les propriétés inconnues', () => {
    let node: object = { type: 'heading', text: 'Fin' }
    for (let i = 0; i < 7; i++) node = { type: 'stack', children: [node] }
    expect(validateComposition({ ...root, children: [node] }).ok).toBe(false)
    expect(validateComposition({ ...root, style: 'position:fixed', children: [{ type: 'heading', text: 'X' }] }).ok).toBe(false)
  })
})
