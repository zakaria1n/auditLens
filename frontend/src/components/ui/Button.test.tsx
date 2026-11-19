import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Button } from './button'

describe('Button', () => {
  it('rend les variantes avec la classe de variante attendue', () => {
    render(<Button variant="primary">OK</Button>)
    expect(screen.getByRole('button', { name: 'OK' })).toHaveClass('bg-brand-600')
  })

  it('déclenche onClick et respecte disabled', async () => {
    const onClick = vi.fn()
    const { rerender } = render(<Button onClick={onClick}>Envoyer</Button>)
    await userEvent.click(screen.getByRole('button', { name: 'Envoyer' }))
    expect(onClick).toHaveBeenCalledTimes(1)
    rerender(<Button onClick={onClick} disabled>Envoyer</Button>)
    await userEvent.click(screen.getByRole('button', { name: 'Envoyer' }))
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
