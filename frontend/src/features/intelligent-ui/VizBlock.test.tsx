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
