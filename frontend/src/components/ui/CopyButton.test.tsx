import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { CopyButton } from './CopyButton'

describe('CopyButton', () => {
  it('copie le texte puis affiche « Copié ✓ » brièvement', async () => {
    const write = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText: write } })
    render(<CopyButton text="preuve ev_123" />)
    await userEvent.click(screen.getByRole('button', { name: 'Copier' }))
    expect(write).toHaveBeenCalledWith('preuve ev_123')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Copié' })).toBeInTheDocument())
  })
})
