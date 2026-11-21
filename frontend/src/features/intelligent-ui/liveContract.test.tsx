/** Optional real-provider artifact check; skipped in ordinary offline tests. */
import { readFileSync, writeFileSync } from 'node:fs'
import { cleanup, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
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
})
