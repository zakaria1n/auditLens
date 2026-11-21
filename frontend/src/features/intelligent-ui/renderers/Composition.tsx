import { useId, useState } from 'react'
import type { ReactNode } from 'react'
import type { CompositionNode, CompositionSpec } from '../schemas/composition'
import type { VizSpec } from '../schemas/viz'
import { dispatchAction } from '../interactions/actions'

function Tabs({ items, renderChild }: { items: Array<{ label: string; children: CompositionNode[] }>; renderChild: (node: CompositionNode, key: string) => ReactNode }) {
  const [active, setActive] = useState(0)
  const prefix = useId()
  return <div><div role="tablist" aria-label="Sections de la présentation" className="flex gap-2 border-b border-slate-200">
    {items.map((item, index) => <button key={index} type="button" role="tab" id={`${prefix}-tab-${index}`} aria-selected={active === index} aria-controls={`${prefix}-panel-${index}`} tabIndex={active === index ? 0 : -1} className="px-3 py-2 text-sm aria-selected:border-b-2 aria-selected:border-brand-600" onClick={() => dispatchAction('switch_tab', { switch_tab: () => setActive(index) })} onKeyDown={event => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
      event.preventDefault()
      const next = (index + (event.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length
      dispatchAction('switch_tab', { switch_tab: () => setActive(next) })
      document.getElementById(`${prefix}-tab-${next}`)?.focus()
    }}>{item.label}</button>)}
  </div><div role="tabpanel" id={`${prefix}-panel-${active}`} aria-labelledby={`${prefix}-tab-${active}`} className="flex flex-col gap-3 pt-3">{items[active].children.map((child, i) => renderChild(child, `tab-${active}-${i}`))}</div></div>
}

interface Props {
  spec: CompositionSpec
  renderVisualization: (spec: VizSpec, componentId: string) => ReactNode
}

/** Local-only interaction: no model-supplied actions or network calls. */
export function Composition({ spec, renderVisualization }: Props) {
  function render(node: CompositionNode, key: string): ReactNode {
    switch (node.type) {
      case 'heading': return <h3 key={key} className="text-base font-semibold text-ink-900">{node.text}</h3>
      case 'paragraph': return <p key={key} className="whitespace-pre-wrap text-sm leading-relaxed text-ink-700" dir="auto">{node.text}</p>
      case 'caption': return <p key={key} className="text-xs leading-relaxed text-ink-400">{node.text}</p>
      case 'code': return <pre key={key} className="overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-white"><code>{node.text}</code></pre>
      case 'divider': return <hr key={key} className="border-slate-200" />
      case 'visualization': return <div key={key} className="min-w-0">{renderVisualization(node.spec, key)}</div>
      case 'tabs': return <Tabs key={key} items={node.items} renderChild={(child, childKey) => render(child, `${key}-${childKey}`)} />
      case 'accordion': return <details key={key} data-action="toggle_accordion" className="rounded-xl border border-slate-200 bg-white p-3"><summary className="cursor-pointer text-sm font-medium text-ink-700">{node.title}</summary><div className="mt-3 flex flex-col gap-3">{node.children.map((child, i) => render(child, `${key}-${i}`))}</div></details>
      case 'stack': case 'row': case 'grid': case 'section': {
        const layout = node.type === 'row' || node.type === 'grid' ? 'grid grid-cols-1 gap-3 sm:grid-cols-2' : 'flex flex-col gap-3'
        return <section key={key} className={`min-w-0 ${layout}`} aria-label={node.title}>
          {node.title && <h4 className="col-span-full text-sm font-semibold text-ink-700">{node.title}</h4>}
          {node.children.map((child, i) => render(child, `${key}-${i}`))}
        </section>
      }
    }
  }
  return <div className="my-3 flex min-w-0 flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4">
    <p className="text-xs font-medium text-slate-500">Explication illustrative · données non vérifiées</p>
    {spec.children.map((node, i) => render(node, String(i)))}
  </div>
}
