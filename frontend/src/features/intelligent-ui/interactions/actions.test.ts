import { describe, expect, it, vi } from 'vitest'
import { dispatchAction, isActionName } from './actions'

describe('registre des actions', () => {
  it('exécute uniquement les actions connues avec gestionnaire applicatif', () => {
    const handler = vi.fn()
    expect(dispatchAction('select_node', { select_node: handler })).toBe(true)
    expect(handler).toHaveBeenCalledOnce()
    expect(dispatchAction('fetch:https://evil.test', { select_node: handler })).toBe(false)
    expect(dispatchAction('__proto__', {})).toBe(false)
    expect(isActionName('open_evidence')).toBe(true)
    expect(dispatchAction('open_evidence', {})).toBe(false)
  })
})
