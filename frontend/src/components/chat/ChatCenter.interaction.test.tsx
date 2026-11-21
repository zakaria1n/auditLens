import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeAll, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ ws: { current: {} as Record<string, unknown> }, send: vi.fn().mockResolvedValue(undefined) }))
vi.mock('../../lib/chatWorkspaceContext', () => ({ useChatWorkspaceCtx: () => mocks.ws.current }))
vi.mock('../../features/chat/useChatModel', () => ({ useChatModel: () => ({ options: [], loading: false, model: 'mock', provider: 'mock' }) }))

import { ChatCenter } from './ChatCenter'

beforeAll(() => { Element.prototype.scrollIntoView = vi.fn() })

it('envoie depuis le chat le contexte précis de la composition et invalide une sélection après changement de branche', async () => {
  const spec = { version: 2, type: 'composition', mode: 'conceptual', children: [{ type: 'visualization', spec: {
    version: 1, type: 'process_diagram', title: 'Cycle', steps: [{ id: 'a', label: 'Agent' }, { id: 'b', label: 'Outil', detail: 'Vérification' }],
  } }] }
  const message = { id: 'msg-assistant', role: 'assistant', parent_id: 'msg-user', status: 'complete', parts: [{ type: 'text', text: `\`\`\`viz\n${JSON.stringify(spec)}\n\`\`\`` }] }
  mocks.ws.current = { activeId: 'conversation-a', headId: 'branch-1', thread: { title: 'Test', mission_ids: [], run_ids: [] }, messages: [message], branches: [], loading: false, isRunning: false, send: mocks.send, notice: null }
  const view = render(<MemoryRouter><ChatCenter onOpenSidebar={() => {}} onToggleInvestigation={() => {}} /></MemoryRouter>)
  await userEvent.click(screen.getByRole('button', { name: /Outil/ }))
  expect(screen.getByText(/Illustration sélectionnée/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Expliquer cette étape' }))
  await waitFor(() => expect(mocks.send).toHaveBeenCalledOnce())
  const [sent, , explanationOnly] = mocks.send.mock.calls[0]
  expect(sent).toContain('conversation_id: conversation-a')
  expect(sent).toContain('branche_id: branch-1')
  expect(sent).toContain('message_id: msg-assistant')
  expect(sent).toContain('composition_id: viz-0')
  expect(sent).toContain('noeud_id: b')
  expect(sent).toContain('illustration conceptuelle non vérifiée')
  expect(explanationOnly).toBe(true)
  await userEvent.click(screen.getByRole('button', { name: /Agent/ }))
  await userEvent.type(screen.getByPlaceholderText('Décrivez votre objectif d’audit…'), 'Explique davantage{Enter}')
  await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(2))
  expect(mocks.send.mock.calls[1][2]).toBe(true)
  expect(mocks.send.mock.calls[1][0]).toContain('Explique davantage')
  await userEvent.click(screen.getByRole('button', { name: /Agent/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Retirer la sélection du prochain message' }))
  expect(screen.getByRole('button', { name: /Agent/ })).toHaveAttribute('aria-pressed', 'false')
  await userEvent.click(screen.getByRole('button', { name: /Agent/ }))
  mocks.ws.current = { ...mocks.ws.current, headId: 'branch-2' }
  view.rerender(<MemoryRouter><ChatCenter onOpenSidebar={() => {}} onToggleInvestigation={() => {}} /></MemoryRouter>)
  expect(screen.queryByText(/Illustration sélectionnée/)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Agent/ })).toHaveAttribute('aria-pressed', 'false')
})
