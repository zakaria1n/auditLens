import { Component, memo } from 'react'
import type { ReactNode } from 'react'

import { validateVizSpec, type VizSpec } from './schemas/viz'
import { validateComposition } from './schemas/composition'
import { Composition } from './renderers/Composition'
import type { VizCallbacks } from './renderers'
import {
  BarChartViz, ComparisonViz, DataTableViz, KpiSummaryViz, LineChartViz,
  ProcessDiagramViz, RelationshipGraphViz, TimelineViz,
} from './renderers'

/**
 * Registre FINI des présentations approuvées (Phase 3). Une spécification ne
 * peut instancier QUE ces composants — jamais de code généré. Ajouter une
 * nouvelle visualisation = nouveau renderer + entrée ici + validateur dans
 * schemas/viz.ts (voir docs frontend).
 */
export function renderViz(spec: VizSpec, callbacks?: VizCallbacks): ReactNode {
  switch (spec.type) {
    case 'data_table':
      return <DataTableViz spec={spec} callbacks={callbacks} />
    case 'bar_chart':
      return <BarChartViz spec={spec} callbacks={callbacks} />
    case 'line_chart':
      return <LineChartViz spec={spec} callbacks={callbacks} />
    case 'comparison':
      return <ComparisonViz spec={spec} callbacks={callbacks} />
    case 'relationship_graph':
      return <RelationshipGraphViz spec={spec} callbacks={callbacks} />
    case 'process_diagram':
      return <ProcessDiagramViz spec={spec} callbacks={callbacks} />
    case 'timeline':
      return <TimelineViz spec={spec} callbacks={callbacks} />
    case 'kpi_summary':
      return <KpiSummaryViz spec={spec} callbacks={callbacks} />
  }
}

class VizErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    if (this.state.failed) {
      return (
        <div className="my-2 rounded-xl border border-amber-200 bg-amber-50/70 px-3.5 py-2.5">
          <p className="text-[11px] text-amber-800">
            Rendu de la visualisation indisponible — la réponse textuelle reste la source de référence.
          </p>
        </div>
      )
    }
    return this.props.children
  }
}

/**
 * Point d'entrée Generative UI : une spécification brute (JSON du modèle ou
 * dérivation déterministe d'un résultat d'outil) est VALIDÉE puis rendue par
 * le registre. Invalide → repli lisible avec la raison (jamais un échec silencieux,
 * jamais d'exécution de contenu non approuvé).
 */
function VizBlockInner({ raw, callbacks }: { raw: unknown; callbacks?: VizCallbacks }) {
  if (typeof raw === 'object' && raw !== null && 'version' in raw && raw.version === 2) {
    const result = validateComposition(raw)
    if (!result.ok) return <div className="my-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">Cette présentation ne peut pas être affichée. La réponse textuelle reste disponible.<details><summary>Détails techniques</summary>{result.reason}</details></div>
    return <VizErrorBoundary><Composition spec={result.spec} renderVisualization={spec => renderViz(spec, callbacks)} /></VizErrorBoundary>
  }
  const result = validateVizSpec(raw)
  if (!result.ok) {
    return (
      <div className="my-2 rounded-xl border border-amber-200 bg-amber-50/70 px-3.5 py-2.5">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700">
          Présentation non supportée — repli texte
        </p>
        <p className="mt-0.5 text-[11px] leading-snug text-amber-800">
          {result.reason}. La réponse textuelle ci-dessus reste la source de référence.
        </p>
      </div>
    )
  }
  const spec = result.spec
  // filet de sécurité runtime : tout défaut de rendu → message lisible, jamais un crash du chat
  return (
    <VizErrorBoundary>
      {renderViz(spec, callbacks)}
    </VizErrorBoundary>
  )
}

/**
 * Mémoïsé : pendant le streaming, les messages re-rendent souvent — la
 * validation (déterministe) et le rendu ne refont que si la spéc change.
 */
export const VizBlock = memo(VizBlockInner)
