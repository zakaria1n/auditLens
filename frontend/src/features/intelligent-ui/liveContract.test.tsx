/** Optional real-provider artifact check; skipped in ordinary offline tests. */
import { readFileSync, writeFileSync } from 'node:fs'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { validateComposition } from './schemas/composition'
import { VizBlock } from './VizBlock'

const artifact = process.env.AUDITLENS_LIVE_VIZ_PATH

describe.skipIf(!artifact)('real provider composition contract', () => {
  it('validates and renders at least one actual generated v2 specification', () => {
    const input = JSON.parse(readFileSync(artifact!, 'utf8')) as { specs: unknown[] }
    const results = input.specs.map(validateComposition)
    writeFileSync(`${artifact}.validation.json`, JSON.stringify(results.map((result, i) => ({ index: i, ok: result.ok, ...(!result.ok ? { issue: result.issue } : { components: result.spec.children.map(child => child.type) }) })), null, 2))
    console.log('Provider composition validation:', results.map((result, i) => ({ index: i, ok: result.ok, ...(!result.ok ? { issue: result.issue } : {}) })))
    expect(results.some(result => result.ok)).toBe(true)
    for (const [index, result] of results.entries()) {
      if (!result.ok) continue
      render(<VizBlock raw={input.specs[index]} />)
      expect(screen.getByText('Explication illustrative · données non vérifiées')).toBeInTheDocument()
      cleanup()
    }
  })

  it('interacts with a diagram from the persisted real-provider response', async () => {
    const input = JSON.parse(readFileSync(artifact!, 'utf8')) as { persisted: boolean; specs: unknown[] }
    expect(input.persisted).toBe(true)
    const candidate = input.specs.map(validateComposition).find(result => result.ok && result.spec.children.some(child => child.type === 'visualization' && child.spec.type === 'process_diagram'))
    expect(candidate?.ok).toBe(true)
    if (!candidate?.ok) return
    const diagram = candidate.spec.children.find(child => child.type === 'visualization' && child.spec.type === 'process_diagram')
    if (!diagram || diagram.type !== 'visualization' || diagram.spec.type !== 'process_diagram') throw new Error('Process diagram missing')
    const { id: stepId, label: stepLabel } = diagram.spec.steps[0]
    const onSelect = vi.fn(), onExplainSelection = vi.fn()
    render(<VizBlock raw={candidate.spec} messageId="stored-assistant" compositionId="viz-0" callbacks={{ onSelect, onExplainSelection }} />)
    const step = screen.getAllByRole('button').find(button => button.textContent?.includes(stepLabel))
    expect(step).toBeDefined()
    await userEvent.click(step!)
    await userEvent.click(screen.getByRole('button', { name: 'Expliquer cette étape' }))
    expect(onExplainSelection).toHaveBeenCalledWith(expect.objectContaining({ nodeId: stepId, mode: 'conceptual', messageId: 'stored-assistant' }))
  })
})
