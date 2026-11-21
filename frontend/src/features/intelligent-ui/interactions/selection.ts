import type { VizType } from '../schemas/viz'

/**
 * Sélection structurée (Phase 4) : quand l'auditeur sélectionne un élément
 * d'une visualisation, le contexte EXACT (type de présentation, enregistrement,
 * identifiant, preuve) accompagne la prochaine demande — jamais un « investigue
 * ça » ambigu. Le bloc de contexte est du TEXTE structuré inséré avant la
 * demande : toute exécution d'outil reste soumise au Policy Gate backend.
 */

export interface VizSelection {
  vizType: VizType
  vizTitle: string
  /** ligne de tableau (objet + id de ligne si fourni par la spéc) */
  record?: Record<string, unknown>
  recordId?: string
  /** libellé sélectionné (barre, item de comparaison, nœud de graphe, étape) */
  label?: string
  nodeId?: string
  /** arête de graphe sélectionnée */
  edge?: { source: string; target: string; status?: string; label?: string }
  /** preuve directement ciblée */
  evidenceRef?: string
}

/** Never carry a selection from a different thread or conversation branch. */
export interface BoundVizSelection {
  threadId: string | null
  headId: string | null
  value: VizSelection
}

export function selectionForContext(bound: BoundVizSelection | null, threadId: string | null, headId: string | null): VizSelection | null {
  return bound && bound.threadId === threadId && bound.headId === headId ? bound.value : null
}

export function describeSelection(selection: VizSelection): string {
  if (selection.record !== undefined || selection.recordId !== undefined) {
    const id = selection.recordId ?? 'sans identifiant'
    return `Enregistrement ${id} · ${selection.vizTitle}`
  }
  if (selection.edge) return `Lien ${selection.edge.source} → ${selection.edge.target} · ${selection.vizTitle}`
  if (selection.evidenceRef) return `Preuve ${selection.evidenceRef} · ${selection.vizTitle}`
  if (selection.label) return `${selection.label} · ${selection.vizTitle}`
  return selection.vizTitle
}

/** Bloc de contexte déterministe inséré avant l'instruction utilisateur. */
export function formatSelectionContext(selection: VizSelection): string {
  const lines = [
    '[Contexte de sélection — généré par l’interface AuditLens]',
    `présentation: ${selection.vizType} « ${selection.vizTitle} »`,
  ]
  if (selection.recordId !== undefined) lines.push(`enregistrement_id: ${selection.recordId}`)
  if (selection.record !== undefined) {
    lines.push(`enregistrement: ${JSON.stringify(selection.record)}`)
  }
  if (selection.label !== undefined) lines.push(`élément: ${selection.label}`)
  if (selection.nodeId !== undefined) lines.push(`noeud_id: ${selection.nodeId}`)
  if (selection.edge !== undefined) {
    lines.push(
      `lien: ${selection.edge.source} → ${selection.edge.target}` +
        (selection.edge.status ? ` (statut: ${selection.edge.status})` : '') +
        (selection.edge.label ? ` (${selection.edge.label})` : ''),
    )
  }
  if (selection.evidenceRef !== undefined) lines.push(`preuve: ${selection.evidenceRef}`)
  lines.push('[/Contexte de sélection]')
  return lines.join('\n')
}

/** Message final : contexte structuré + instruction humaine (jamais l'un sans l'autre). */
export function buildSelectionMessage(selection: VizSelection, instruction: string): string {
  const trimmed = instruction.trim()
  return trimmed
    ? `${formatSelectionContext(selection)}\n\n${trimmed}`
    : `${formatSelectionContext(selection)}\n\nInvestigue cet élément : vérifie sa cohérence, confronte-le aux autres preuves collectées et documente toute anomalie avec les preuves correspondantes.`
}
