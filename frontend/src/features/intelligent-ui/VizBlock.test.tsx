import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { VizBlock } from './VizBlock'

const barSpec = JSON.stringify({
  version: 1, type: 'bar_chart', title: 'Commandé vs livré',
  bars: [{ label: 'SO-1', value: 5 }, { label: 'SO-2', value: 2 }], unit: 'u',
  evidence_refs: ['ev_abc12345'],
})

describe('VizBlock — rendu sûr', () => {
  it('sélectionne une relation au clavier sans appeler le modèle', async () => {
    const onSelect = vi.fn(), onExplainSelection = vi.fn()
    render(<VizBlock raw={{ version: 1, type: 'relationship_graph', title: 'Flux', nodes: [{ id: 'a', label: 'Agent' }, { id: 'b', label: 'Outil' }], edges: [{ source: 'a', target: 'b', label: 'appel' }] }} callbacks={{ onSelect, onExplainSelection }} />)
    const edge = screen.getByRole('button', { name: /Lien a vers b/ })
    edge.focus()
    await userEvent.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ edge: expect.objectContaining({ source: 'a', target: 'b' }) }))
    expect(onExplainSelection).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Expliquer cet élément' }))
    expect(onExplainSelection).toHaveBeenCalledOnce()
  })

  it('compare deux nœuds sélectionnés uniquement après action explicite', async () => {
    const onExplainSelection = vi.fn()
    render(<VizBlock raw={{ version: 1, type: 'relationship_graph', title: 'Flux', nodes: [{ id: 'a', label: 'Agent' }, { id: 'b', label: 'Outil' }], edges: [{ source: 'a', target: 'b' }] }} callbacks={{ onExplainSelection }} />)
    await userEvent.click(screen.getByRole('button', { name: 'Agent' }))
    await userEvent.click(screen.getByRole('button', { name: 'Outil' }))
    expect(onExplainSelection).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Comparer ces éléments' }))
    expect(onExplainSelection).toHaveBeenCalledWith(expect.objectContaining({ nodes: [{ id: 'a', label: 'Agent' }, { id: 'b', label: 'Outil' }] }))
    await userEvent.click(screen.getByRole('button', { name: 'Effacer la sélection' }))
    expect(screen.getByRole('button', { name: 'Agent' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('filtre et trie un tableau localement', async () => {
    const onSelect = vi.fn()
    render(<VizBlock raw={{ version: 1, type: 'data_table', title: 'Table', columns: ['nom', 'quantité'], rows: [{ nom: 'B', quantité: 2 }, { nom: 'A', quantité: 1 }] }} callbacks={{ onSelect }} />)
    await userEvent.click(screen.getByRole('button', { name: 'Trier par nom' }))
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('A')
    await userEvent.type(screen.getByRole('textbox', { name: 'Filtrer les lignes du tableau' }), 'B')
    expect(screen.queryByText('A')).not.toBeInTheDocument()
    expect(screen.getByText('B')).toBeInTheDocument()
    expect(onSelect).not.toHaveBeenCalled()
  })
  it('tente une seule réparation et vérifie la réponse avant rendu', async () => {
    const repair = vi.fn().mockResolvedValue({ version: 2, type: 'composition', mode: 'conceptual', children: [{ type: 'heading', text: 'Architecture' }] })
    render(<VizBlock raw={{ version: 2, type: 'composition', mode: 'conceptual', children: [{ type: 'heading', text: 17 }] }} callbacks={{ onRepairPresentation: repair }} />)
    await userEvent.click(screen.getByRole('button', { name: 'Réessayer la présentation' }))
    expect(await screen.findByRole('heading', { name: 'Architecture' })).toBeInTheDocument()
    expect(repair).toHaveBeenCalledTimes(1)
  })

  it('conserve le repli après une réparation invalide et ne réessaie pas', async () => {
    const repair = vi.fn().mockResolvedValue({ version: 2, type: 'composition', mode: 'conceptual', children: [] })
    render(<VizBlock raw={{ version: 2, type: 'composition', mode: 'conceptual', children: [] }} callbacks={{ onRepairPresentation: repair }} />)
    await userEvent.click(screen.getByRole('button', { name: 'Réessayer la présentation' }))
    expect(await screen.findByText(/La correction n'a pas abouti/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Réessayer la présentation' })).not.toBeInTheDocument()
    expect(repair).toHaveBeenCalledTimes(1)
  })
  it('affiche les libellés complets du graphe et permet la sélection au clavier', async () => {
    const onSelect = vi.fn()
    const label = 'Politique de contrôle des autorisations'
    render(<VizBlock raw={{ version: 1, type: 'relationship_graph', title: 'Architecture',
      nodes: [{ id: 'a', label }, { id: 'b', label: 'Preuves' }], edges: [{ source: 'a', target: 'b' }] }} callbacks={{ onSelect }} />)
    const node = screen.getByRole('button', { name: label })
    expect(node.textContent).toContain('Politique de contrôle')
    expect(node.textContent).toContain('autorisations')
    node.focus()
    await userEvent.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith({ vizType: 'relationship_graph', vizTitle: 'Architecture', label, nodeId: 'a' })
    expect(screen.queryByText('lien vérifié')).not.toBeInTheDocument()
  })
  it.each([['RL', 'flex-row-reverse', 'rotate-180'], ['BT', 'flex-col-reverse', '-rotate-90']])(
    'affiche %s dans le bon sens', (direction, axis, arrow) => {
      const { container } = render(<VizBlock raw={{ version: 1, type: 'process_diagram', title: 'Processus', direction,
        steps: [{ id: 'a', label: 'Début' }, { id: 'b', label: 'Fin' }] }} />)
      expect(container.querySelector('ol')).toHaveClass(axis)
      expect(container.querySelector('li span')).toHaveClass(arrow)
      expect(screen.queryByText(/Présentation non supportée/i)).not.toBeInTheDocument()
    },
  )
  it('rend une spécification valide via le registre approuvé', () => {
    render(<VizBlock raw={JSON.parse(barSpec)} />)
    expect(screen.getByText('Commandé vs livré')).toBeInTheDocument()
    expect(screen.getByText('SO-1')).toBeInTheDocument()
    expect(screen.getByText('bar chart', { exact: false })).toBeInTheDocument()
  })

  it('repli lisible (jamais de crash, jamais d’exécution) pour une spéc invalide', () => {
    render(<VizBlock raw={{ version: 1, type: 'unknown_widget', payload: '<script>alert(1)</script>' }} />)
    expect(screen.getByText(/Présentation non supportée/i)).toBeInTheDocument()
    expect(screen.queryByText('payload')).not.toBeInTheDocument()
  })

  it('repli pour du JSON malformé', () => {
    render(<VizBlock raw="not json at all" />)
    expect(screen.getByText(/Présentation non supportée/i)).toBeInTheDocument()
  })

  it('table interactive : détail + investigation avec la ligne sélectionnée', async () => {
    const onInvestigate = vi.fn()
    render(
      <VizBlock
        raw={{
          version: 1, type: 'data_table', title: 'Écarts',
          columns: ['ref', 'qty'], rows: [{ ref: 'SO-2', qty: -3 }], row_ids: ['42'],
        }}
        callbacks={{ onInvestigateSelection: onInvestigate }}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Détail' }))
    expect(screen.getByText('Enregistrement 42')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Investiguer cet enregistrement/i }))
    expect(onInvestigate).toHaveBeenCalledExactlyOnceWith({ vizType: 'data_table', vizTitle: 'Écarts', record: { ref: 'SO-2', qty: -3 }, recordId: '42' })
  })

  it('les chips de preuve déclenchent onOpenEvidence', async () => {
    const onOpenEvidence = vi.fn()
    render(<VizBlock raw={JSON.parse(barSpec)} callbacks={{ onOpenEvidence }} />)
    await userEvent.click(screen.getByRole('button', { name: 'ev_abc12345' }))
    expect(onOpenEvidence).toHaveBeenCalledWith('ev_abc12345')
  })
})
