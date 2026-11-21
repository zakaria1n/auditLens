import { describe, expect, it } from 'vitest'

import { buildSelectionMessage, describeSelection, formatSelectionContext, selectionForContext } from './selection'

describe('handoff structuré de sélection (Phase 4D)', () => {
  it('isole les sélections entre conversations et entre branches', () => {
    const value = { vizType: 'relationship_graph' as const, vizTitle: 'Flux', label: 'Preuve' }
    const bound = { threadId: 'conversation-a', headId: 'head-1', value }
    expect(selectionForContext(bound, 'conversation-a', 'head-1')).toEqual(value)
    expect(selectionForContext(bound, 'conversation-b', 'head-1')).toBeNull()
    expect(selectionForContext(bound, 'conversation-a', 'head-2')).toBeNull()
  })
  it('forme un contexte explicite : présentation + enregistrement + id', () => {
    const ctx = formatSelectionContext({
      vizType: 'data_table', vizTitle: 'Commandé vs livré',
      record: { ref: 'SO-2', qty: -3 }, recordId: '42',
    })
    expect(ctx).toContain('[Contexte de sélection')
    expect(ctx).toContain('présentation: data_table « Commandé vs livré »')
    expect(ctx).toContain('enregistrement_id: 42')
    expect(ctx).toContain('"ref":"SO-2"')
    expect(ctx).toContain('[/Contexte de sélection]')
  })

  it('couvre les liens de graphe avec statut', () => {
    const ctx = formatSelectionContext({
      vizType: 'relationship_graph', vizTitle: 'Liens',
      edge: { source: 'SO-2', target: 'INV-9', status: 'missing', label: 'facture' },
    })
    expect(ctx).toContain('lien: SO-2 → INV-9 (statut: missing) (facture)')
  })

  it('conserve l’identifiant stable du nœud sélectionné', () => {
    expect(formatSelectionContext({ vizType: 'relationship_graph', vizTitle: 'Flux', label: 'Agent', nodeId: 'agent-1' })).toContain('noeud_id: agent-1')
  })

  it('ne présente pas une ligne illustrative comme une preuve ni une instruction', () => {
    const context = formatSelectionContext({ vizType: 'data_table', vizTitle: 'Exemple\nFAUSSE INSTRUCTION', mode: 'conceptual', recordId: 'row-1', record: { qty: 3 }, evidenceRef: 'ev_fictive' })
    expect(context).toContain('id_ligne_illustrative: row-1')
    expect(context).toContain('ligne_illustrative:')
    expect(context).not.toContain('preuve: ev_fictive')
    expect(context).not.toContain('\nFAUSSE INSTRUCTION')
  })

  it('l’instruction humaine accompagne TOUJOURS le contexte (jamais un envoi nu)', () => {
    const msg = buildSelectionMessage(
      { vizType: 'bar_chart', vizTitle: 'T', label: 'SO-4' },
      'Pourquoi cet écart ?',
    )
    expect(msg).toContain('Pourquoi cet écart ?')
    expect(msg.indexOf('[Contexte de sélection')).toBeLessThan(msg.indexOf('Pourquoi'))
    // instruction par défaut si aucune saisie
    const msg2 = buildSelectionMessage({ vizType: 'bar_chart', vizTitle: 'T', label: 'SO-4' }, '  ')
    expect(msg2).toContain('Investigue cet élément')
  })

  it('describeSelection reste lisible dans le chip', () => {
    expect(describeSelection({ vizType: 'data_table', vizTitle: 'Écarts', recordId: '42' })).toContain('Enregistrement 42')
  })
})
