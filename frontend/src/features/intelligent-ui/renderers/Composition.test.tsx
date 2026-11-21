import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'
import { VizBlock } from '../VizBlock'

it('affiche une composition et ouvre les détails localement', async () => {
  render(<VizBlock raw={{ version: 2, type: 'composition', mode: 'conceptual', children: [
    { type: 'heading', text: 'Architecture' },
    { type: 'accordion', title: 'Les outils', children: [{ type: 'paragraph', text: 'Le contrôle vérifie le périmètre.' }] },
  ] }} />)
  expect(screen.getByText('Explication illustrative · données non vérifiées')).toBeInTheDocument()
  const toggle = screen.getByText('Les outils')
  expect(toggle.closest('details')).not.toHaveAttribute('open')
  await userEvent.click(toggle)
  expect(toggle.closest('details')).toHaveAttribute('open')
})
