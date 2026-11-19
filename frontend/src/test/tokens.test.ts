import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync('src/index.css', 'utf-8')

describe('design tokens (Phase 1)', () => {
  it('définit l’échelle brand AuditLens avec l’ancre identitaire #5046c9', () => {
    expect(css).toContain('--color-brand-600: #5046c9')
  })

  it('définit les encres, surfaces et élévations sémantiques', () => {
    for (const token of ['--color-ink-900', '--color-surface-2', '--shadow-card', '--shadow-pop', '--ease-out-soft']) {
      expect(css).toContain(token)
    }
  })

  it('respecte prefers-reduced-motion', () => {
    expect(css).toContain('prefers-reduced-motion')
  })
})
