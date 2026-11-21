import type { ReactNode } from 'react'
import type { CompositionNode, CompositionSpec } from '../schemas/composition'
import type { VizSpec } from '../schemas/viz'

interface Props {
  spec: CompositionSpec
  renderVisualization: (spec: VizSpec) => ReactNode
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
      case 'visualization': return <div key={key} className="min-w-0">{renderVisualization(node.spec)}</div>
      case 'accordion': return <details key={key} className="rounded-xl border border-slate-200 bg-white p-3"><summary className="cursor-pointer text-sm font-medium text-ink-700">{node.title}</summary><div className="mt-3 flex flex-col gap-3">{node.children.map((child, i) => render(child, `${key}-${i}`))}</div></details>
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
