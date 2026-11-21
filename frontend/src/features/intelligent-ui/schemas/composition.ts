import { validateVizSpec, type VizSpec } from './viz'

export type CompositionNode =
  | { type: 'heading' | 'paragraph' | 'caption' | 'code'; text: string }
  | { type: 'divider' }
  | { type: 'stack' | 'row' | 'grid' | 'section'; title?: string; children: CompositionNode[] }
  | { type: 'accordion'; title: string; children: CompositionNode[] }
  | { type: 'visualization'; spec: VizSpec }

export type CompositionSpec = { version: 2; type: 'composition'; mode: 'conceptual'; children: CompositionNode[] }
export type CompositionValidation = { ok: true; spec: CompositionSpec } | { ok: false; reason: string }

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
  if (!isObject(raw) || raw.version !== 2 || raw.type !== 'composition' || raw.mode !== 'conceptual' || !hasOnly(raw, ['version', 'type', 'mode', 'children'])) {
    return { ok: false, reason: 'Composition conceptuelle v2 attendue' }
  }
  let total = 0
  function parse(node: unknown, depth: number): CompositionNode | null {
    if (++total > 80 || depth > 5 || !isObject(node) || typeof node.type !== 'string') return null
    if (textTypes.has(node.type)) {
      if (!hasOnly(node, ['type', 'text']) || !validText(node.text, node.type === 'code' ? 3000 : 1200)) return null
      return { type: node.type as 'heading' | 'paragraph' | 'caption' | 'code', text: node.text }
    }
    if (node.type === 'divider') return hasOnly(node, ['type']) ? { type: 'divider' } : null
    if (layoutTypes.has(node.type)) {
      if (!hasOnly(node, ['type', 'title', 'children']) || !Array.isArray(node.children) || !node.children.length || node.children.length > 24) return null
      if (node.title !== undefined && !validText(node.title, 140)) return null
      if (node.type === 'accordion' && !validText(node.title, 140)) return null
      const children = node.children.map(child => parse(child, depth + 1))
      if (children.some(child => child === null)) return null
      const type = node.type as 'stack' | 'row' | 'grid' | 'section' | 'accordion'
      if (type === 'accordion') return { type, title: node.title as string, children: children as CompositionNode[] }
      return { type, ...(node.title ? { title: node.title as string } : {}), children: children as CompositionNode[] }
    }
    if (node.type === 'visualization' && hasOnly(node, ['type', 'spec'])) {
      if (hasEvidenceBinding(node.spec)) return null
      const result = validateVizSpec(node.spec)
      // v1 data visuals lack verified bindings; v2 is explicitly illustrative.
      return result.ok ? { type: 'visualization', spec: result.spec } : null
    }
    return null
  }
  if (!Array.isArray(raw.children) || !raw.children.length || raw.children.length > 24) return { ok: false, reason: 'Contenu de composition invalide' }
  const children = raw.children.map(child => parse(child, 1))
  if (children.some(child => child === null)) return { ok: false, reason: 'Élément invalide ou limites de composition dépassées' }
  return { ok: true, spec: { version: 2, type: 'composition', mode: 'conceptual', children: children as CompositionNode[] } }
}
