import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { AuditLensLogo } from './AuditLensLogo'

describe('AuditLensLogo', () => {
  it('rend un span décoratif aria-hidden avec la taille demandée', () => {
    const { container } = render(<AuditLensLogo size={48} />)
    const el = container.querySelector('span[aria-hidden="true"]') as HTMLElement
    expect(el).toBeInTheDocument()
    expect(el.style.width).toBe('48px')
    expect(el.querySelector('svg')).toBeInTheDocument()
  })

  it('applique la classe supplémentaire fournie', () => {
    const { container } = render(<AuditLensLogo className="!rounded-[22px]" />)
    expect(container.querySelector('span[aria-hidden="true"]')).toHaveClass('!rounded-[22px]')
  })
})
