import { describe, expect, it } from 'vitest'

import { buildSelectionMessage, describeSelection, formatSelectionContext } from './selection'

describe('handoff structuré de sélection (Phase 4D)', () => {
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
