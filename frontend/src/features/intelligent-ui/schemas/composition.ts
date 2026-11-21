import { validateVizSpec, type VizSpec } from './viz'
import { normalizeComposition } from './normalizeComposition'

export type CompositionNode =
  | { type: 'heading' | 'paragraph' | 'caption' | 'code'; text: string }
  | { type: 'divider' }
  | { type: 'stack' | 'row' | 'grid' | 'section'; title?: string; children: CompositionNode[] }
  | { type: 'accordion'; title: string; children: CompositionNode[] }
  | { type: 'visualization'; spec: VizSpec }

export type CompositionSpec = { version: 2; type: 'composition'; mode: 'conceptual'; children: CompositionNode[] }
export type CompositionIssue = { path: string; expected: string; actual: string; suggestion: string; evidenceValid: 'unknown' }
export type CompositionValidation = { ok: true; spec: CompositionSpec } | { ok: false; reason: string; issue: CompositionIssue }

const textTypes = new Set(['heading', 'paragraph', 'caption', 'code'])
const layoutTypes = new Set(['stack', 'row', 'grid', 'section', 'accordion'])
const dangerous = /<\/?[a-z][^>]*>|javascript\s*:|data\s*:|https?:\/\//i
const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const validText = (v: unknown, limit: number): v is string => typeof v === 'string' && !!v.trim() && v.length <= limit && !dangerous.test(v)
const hasOnly = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).every(key => keys.includes(key))
function hasEvidenceBinding(value: unknown, depth = 0): boolean {
  if (depth > 12) return true
  if (Array.isArray(value)) return value.some(item => hasEvidenceBinding(item, depth + 1))
  if (!isObject(value)) return false
  return Object.entries(value).some(([key, child]) => key === 'evidence_ref' || key === 'evidence_refs' || hasEvidenceBinding(child, depth + 1))
}

/** The model never supplies components, styles, URLs, event handlers, or executable code. */
export function validateComposition(raw: unknown): CompositionValidation {
  raw = normalizeComposition(raw)
  let issue: CompositionIssue = { path: '$', expected: 'composition conceptuelle v2', actual: typeof raw, suggestion: 'Vérifiez version, type, mode et children.', evidenceValid: 'unknown' }
  const reject = (path: string, expected: string, actual: unknown, suggestion: string) => {
    issue = { path, expected, actual: Array.isArray(actual) ? 'array' : actual === null ? 'null' : typeof actual, suggestion, evidenceValid: 'unknown' }
    return null
  }
  if (!isObject(raw) || raw.version !== 2 || raw.type !== 'composition' || raw.mode !== 'conceptual' || !hasOnly(raw, ['version', 'type', 'mode', 'children'])) {
    return { ok: false, reason: 'Composition conceptuelle v2 attendue', issue }
  }
  let total = 0
  function parse(node: unknown, depth: number, path: string): CompositionNode | null {
    if (++total > 80 || depth > 5) return reject(path, '80 éléments et profondeur 5 maximum', node, 'Réduisez la taille ou la profondeur.')
    if (!isObject(node) || typeof node.type !== 'string') return reject(path, 'objet avec type', node, 'Fournissez un composant autorisé.')
    if (textTypes.has(node.type)) {
      if (!hasOnly(node, ['type', 'text'])) return reject(path, 'propriétés type et text', node, 'Supprimez les propriétés non prises en charge.')
      if (!validText(node.text, node.type === 'code' ? 3000 : 1200)) return reject(`${path}.text`, 'texte sûr non vide et borné', node.text, 'Corrigez le champ text.')
      return { type: node.type as 'heading' | 'paragraph' | 'caption' | 'code', text: node.text }
    }
    if (node.type === 'divider') return hasOnly(node, ['type']) ? { type: 'divider' } : reject(path, 'divider sans propriétés supplémentaires', node, 'Supprimez les propriétés inconnues.')
    if (layoutTypes.has(node.type)) {
      if (!hasOnly(node, ['type', 'title', 'children']) || !Array.isArray(node.children) || !node.children.length || node.children.length > 24) return reject(path, 'type, title optionnel, 1 à 24 children', node.children, 'Corrigez les propriétés ou la liste children.')
      if (node.title !== undefined && !validText(node.title, 140)) return reject(`${path}.title`, 'titre sûr non vide de 140 caractères maximum', node.title, 'Corrigez le titre.')
      if (node.type === 'accordion' && !validText(node.title, 140)) return reject(`${path}.title`, 'titre obligatoire', node.title, 'Ajoutez un titre à la section repliable.')
      const children: CompositionNode[] = []
      for (const [index, child] of node.children.entries()) {
        const parsed = parse(child, depth + 1, `${path}.children[${index}]`)
        if (!parsed) return null
        children.push(parsed)
      }
      const type = node.type as 'stack' | 'row' | 'grid' | 'section' | 'accordion'
      if (type === 'accordion') return { type, title: node.title as string, children: children as CompositionNode[] }
      return { type, ...(node.title ? { title: node.title as string } : {}), children: children as CompositionNode[] }
    }
    if (node.type === 'visualization' && hasOnly(node, ['type', 'spec'])) {
      if (hasEvidenceBinding(node.spec)) return reject(`${path}.spec`, 'visualisation illustrative sans preuve', node.spec, 'Retirez les références non vérifiées.')
      const result = validateVizSpec(node.spec)
      // v1 data visuals lack verified bindings; v2 is explicitly illustrative.
      return result.ok ? { type: 'visualization', spec: result.spec } : reject(`${path}.spec`, 'visualisation v1 valide', node.spec, result.reason)
    }
    return reject(`${path}.type`, 'type de composant autorisé', node.type, 'Utilisez un type du registre.')
  }
  if (!Array.isArray(raw.children) || !raw.children.length || raw.children.length > 24) {
    reject('$.children', '1 à 24 éléments', raw.children, 'Fournissez une liste non vide.')
    return { ok: false, reason: 'Contenu de composition invalide', issue }
  }
  const children: CompositionNode[] = []
  for (const [index, child] of raw.children.entries()) {
    const parsed = parse(child, 1, `$.children[${index}]`)
    if (!parsed) return { ok: false, reason: 'Élément invalide ou limites de composition dépassées', issue }
    children.push(parsed)
  }
  return { ok: true, spec: { version: 2, type: 'composition', mode: 'conceptual', children } }
}
