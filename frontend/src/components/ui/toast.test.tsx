import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ToastProvider, useToast } from './toast'

function Probe() {
  const { toast } = useToast()
  return (
    <>
      <button type="button" onClick={() => toast('success', 'Conversation renommée.')}>succès</button>
      <button type="button" onClick={() => toast('error', 'Suppression impossible.')}>échec</button>
    </>
  )
}

describe('ToastProvider', () => {
  it('affiche un toast confirmé et permet la fermeture manuelle', async () => {
    render(<ToastProvider><Probe /></ToastProvider>)
    await userEvent.click(screen.getByText('succès'))
    expect(screen.getByRole('status')).toHaveTextContent('Conversation renommée.')
    await userEvent.click(screen.getByRole('button', { name: 'Fermer la notification' }))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('les erreurs utilisent role=alert', async () => {
    render(<ToastProvider><Probe /></ToastProvider>)
    await userEvent.click(screen.getByText('échec'))
    expect(screen.getByRole('alert')).toHaveTextContent('Suppression impossible.')
  })

  it('auto-dismiss après le délai (errores plus longs)', async () => {
    vi.useFakeTimers()
    render(<ToastProvider><Probe /></ToastProvider>)
    act(() => { screen.getByText('succès').click() })
    expect(screen.getByRole('status')).toBeInTheDocument()
    act(() => { vi.advanceTimersByTime(3600) })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    vi.useRealTimers()
  })
})
