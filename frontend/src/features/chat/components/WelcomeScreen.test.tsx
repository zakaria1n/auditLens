import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { WelcomeScreen, type Suggestion } from './WelcomeScreen'

const composer = <textarea aria-label="Message" readOnly value="" />

describe('WelcomeScreen', () => {
  it('affiche la marque, le titre et les 4 suggestions réelles', () => {
    render(<WelcomeScreen composer={composer} onSuggestion={vi.fn()} />)
    expect(screen.getByText('Que souhaitez-vous examiner ?')).toBeInTheDocument()
    expect(screen.getByText('Auditer mon ERP')).toBeInTheDocument()
    expect(screen.getByText('Inspecter une API')).toBeInTheDocument()
    expect(screen.getByText('Analyser une application Web')).toBeInTheDocument()
    expect(screen.getByText('Explorer un fichier de données')).toBeInTheDocument()
  })

  it('dépose le prompt de la suggestion dans le brouillon — jamais d’envoi automatique', async () => {
    const onSuggestion = vi.fn()
    render(<WelcomeScreen composer={composer} onSuggestion={onSuggestion} />)
    await userEvent.click(screen.getByText('Auditer mon ERP'))
    expect(onSuggestion).toHaveBeenCalledExactlyOnceWith(
      expect.stringContaining('Je souhaite auditer un ERP Odoo'),
    )
  })

  it('accepte des suggestions personnalisées (extensible sans duplication)', () => {
    const custom: Suggestion[] = [
      { label: 'Test', description: 'desc', prompt: 'p', icon: 'file' },
    ]
    render(<WelcomeScreen composer={composer} suggestions={custom} onSuggestion={vi.fn()} />)
    expect(screen.getByText('Test')).toBeInTheDocument()
    expect(screen.queryByText('Auditer mon ERP')).not.toBeInTheDocument()
  })

  it('le logo est décoratif (aria-hidden) — le nom est porté par le texte', () => {
    const { container } = render(<WelcomeScreen composer={composer} onSuggestion={vi.fn()} />)
    const logo = container.querySelector('span[aria-hidden="true"]')
    expect(logo).toBeInTheDocument()
  })
})
