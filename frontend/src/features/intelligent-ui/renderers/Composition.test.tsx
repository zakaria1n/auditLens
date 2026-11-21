import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { VizBlock } from '../VizBlock'
import { MarkdownView } from '../../../components/MarkdownView'

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

it('sélectionne un nœud conceptuel et transmet le contexte exact pour l’explication', async () => {
  const onSelect = vi.fn(), onExplainSelection = vi.fn(), onInvestigateSelection = vi.fn()
  const spec = { version: 2, type: 'composition', mode: 'conceptual', children: [{ type: 'visualization', spec: {
    version: 1, type: 'process_diagram', title: 'Cycle', steps: [{ id: 'agent', label: 'Agent' }, { id: 'tool', label: 'Exécution', detail: 'Contrôles' }],
  } }] }
  render(<MarkdownView messageId="assistant-1" markdown={`\`\`\`viz\n${JSON.stringify(spec)}\n\`\`\``} vizCallbacks={{ onSelect, onExplainSelection, onInvestigateSelection }} />)
  await userEvent.click(screen.getByRole('button', { name: /Exécution/ }))
  expect(screen.getByRole('button', { name: /Exécution/ })).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'Expliquer cette étape' }))
  expect(onExplainSelection).toHaveBeenCalledWith(expect.objectContaining({ mode: 'conceptual', messageId: 'assistant-1', compositionId: 'viz-0', componentId: '0', nodeId: 'tool', description: 'Contrôles' }))
  expect(onInvestigateSelection).not.toHaveBeenCalled()
})

it('change les onglets localement et prend en charge le clavier', async () => {
  const callback = vi.fn()
  render(<VizBlock callbacks={{ onExplainSelection: callback }} raw={{ version: 2, type: 'composition', mode: 'conceptual', children: [{ type: 'tabs', items: [
    { label: 'Première', children: [{ type: 'paragraph', text: 'Contenu A' }] },
    { label: 'Deuxième', children: [{ type: 'paragraph', text: 'Contenu B' }] },
  ] }] }} />)
  const first = screen.getByRole('tab', { name: 'Première' })
  first.focus()
  await userEvent.keyboard('{ArrowRight}')
  expect(screen.getByRole('tab', { name: 'Deuxième' })).toHaveFocus()
  expect(screen.getByRole('tabpanel')).toHaveTextContent('Contenu B')
  expect(callback).not.toHaveBeenCalled()
})

it('sélectionne une ligne illustrative sans proposer d’investigation non vérifiée', async () => {
  const onExplainSelection = vi.fn(), onInvestigateSelection = vi.fn()
  render(<VizBlock messageId="msg" compositionId="viz-1" callbacks={{ onExplainSelection, onInvestigateSelection }} raw={{ version: 2, type: 'composition', mode: 'conceptual', children: [{ type: 'visualization', spec: {
    version: 1, type: 'data_table', title: 'Exemple', columns: ['nom'], rows: [{ nom: 'A' }],
  } }] }} />)
  await userEvent.click(screen.getByRole('button', { name: 'Détail' }))
  expect(screen.getByText(/Ligne illustrative/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Investiguer/ })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Expliquer cette ligne illustrative' }))
  expect(onExplainSelection).toHaveBeenCalledWith(expect.objectContaining({ rowId: 'row-0', mode: 'conceptual', messageId: 'msg', compositionId: 'viz-1', componentId: '0' }))
  expect(onInvestigateSelection).not.toHaveBeenCalled()
})

it('distingue les compositions et les messages dans le contexte sélectionné', async () => {
  const onSelect = vi.fn()
  const composition = (label: string) => ({ version: 2, type: 'composition', mode: 'conceptual', children: [{ type: 'visualization', spec: { version: 1, type: 'process_diagram', title: 'Cycle', steps: [{ id: 'a', label }, { id: 'b', label: 'Fin' }] } }] })
  const first = composition('Premier'), second = composition('Second')
  render(<><MarkdownView messageId="message-a" markdown={`\`\`\`viz\n${JSON.stringify(first)}\n\`\`\`\n\n\`\`\`viz\n${JSON.stringify(second)}\n\`\`\``} vizCallbacks={{ onSelect }} />
    <MarkdownView messageId="message-b" markdown={`\`\`\`viz\n${JSON.stringify(composition('Troisième'))}\n\`\`\``} vizCallbacks={{ onSelect }} /></>)
  await userEvent.click(screen.getByRole('button', { name: 'Premier' }))
  expect(onSelect).toHaveBeenLastCalledWith(expect.objectContaining({ messageId: 'message-a', compositionId: 'viz-0' }))
  await userEvent.click(screen.getByRole('button', { name: 'Second' }))
  expect(onSelect).toHaveBeenLastCalledWith(expect.objectContaining({ messageId: 'message-a', compositionId: 'viz-1' }))
  await userEvent.click(screen.getByRole('button', { name: 'Troisième' }))
  expect(onSelect).toHaveBeenLastCalledWith(expect.objectContaining({ messageId: 'message-b', compositionId: 'viz-0' }))
})
