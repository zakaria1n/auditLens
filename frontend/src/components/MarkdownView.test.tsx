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
})
