import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MarkdownView } from './MarkdownView'

describe('Markdown des réponses', () => {
  it('rend un tableau lisible et garde le texte des cellules', () => {
    render(<MarkdownView markdown={'Résultat\n\n| Source | Valeur |\n| --- | --- |\n| Odoo | **42** |'} />)
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Source' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '42' })).toBeInTheDocument()
  })

  it('présente un bloc de code avec une action de copie', () => {
    render(<MarkdownView markdown={'```json\n{"ok": true}\n```'} />)
    expect(screen.getByRole('button', { name: 'Copier le code' })).toBeInTheDocument()
    expect(screen.getByText('{"ok": true}')).toBeInTheDocument()
  })
  it('attend la fermeture du bloc viz avant de l’activer pendant le streaming', () => {
    const { rerender } = render(<MarkdownView markdown={'Voici le schéma\n\n```viz\n{"version":2'} isStreaming />)
    expect(screen.getByRole('status')).toHaveTextContent('Préparation')
    expect(screen.queryByText(/Présentation non supportée/i)).not.toBeInTheDocument()
    rerender(<MarkdownView markdown={'Voici le schéma\n\n```viz\n{"version":2'} />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.getByText(/La réponse textuelle reste disponible/)).toBeInTheDocument()
  })
  it('affiche une composition entre deux paragraphes', () => {
    render(<MarkdownView markdown={'Introduction\n\n```viz\n{"version":2,"type":"composition","mode":"conceptual","children":[{"type":"heading","text":"Architecture"}]}\n```\n\nConclusion'} />)
    expect(screen.getByText('Introduction')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Architecture' })).toBeInTheDocument()
    expect(screen.getByText('Conclusion')).toBeInTheDocument()
  })
})
