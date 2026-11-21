/** Normalize only presentation aliases; never invent values or evidence. */
export function normalizeComposition(value: unknown, depth = 0): unknown {
  if (depth > 7 || value === null || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.map(child => normalizeComposition(child, depth + 1))
  const source = value as Record<string, unknown>
  const node: Record<string, unknown> = { ...source }
  const aliases: Record<string, string> = { column: 'stack', text: 'paragraph' }
  if (typeof node.type === 'string' && aliases[node.type]) node.type = aliases[node.type]
  if (['heading', 'paragraph', 'caption', 'code'].includes(String(node.type)) && node.text === undefined && typeof node.content === 'string') {
    node.text = node.content
    delete node.content
  }
  if (['stack', 'row', 'grid', 'section', 'accordion'].includes(String(node.type)) && node.children === undefined && Array.isArray(node.items)) {
    node.children = node.items
    delete node.items
  }
  // Some providers emit positional rows. Map them only when the correspondence
  // to unique columns is complete; never pad, drop, or infer a value.
  if (node.type === 'visualization' && node.spec && typeof node.spec === 'object' && !Array.isArray(node.spec)) {
    const spec = node.spec as Record<string, unknown>
    const columns = spec.columns
    const rows = spec.rows
    if (spec.type === 'data_table' && Array.isArray(columns) && columns.length > 0 &&
        columns.every(column => typeof column === 'string' && column.length > 0) &&
        new Set(columns).size === columns.length && Array.isArray(rows) && rows.length <= 200 &&
        rows.every(row => Array.isArray(row) && row.length === columns.length)) {
      node.spec = { ...spec, rows: rows.map(row => Object.fromEntries(columns.map((column, index) => [column, (row as unknown[])[index]]))) }
    }
  }
  if (Array.isArray(node.children) && node.children.length <= 24) node.children = node.children.map(child => normalizeComposition(child, depth + 1))
  return node
}
