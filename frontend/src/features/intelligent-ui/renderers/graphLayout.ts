/** Deterministic layout: keep labels readable instead of shrinking a fixed canvas. */
export function wrapNodeLabel(label: string, width = 21): string[] {
  const words = label.trim().split(/\s+/).flatMap(word => {
    const parts: string[] = []
    for (let i = 0; i < word.length; i += width) parts.push(word.slice(i, i + width))
    return parts
  })
  const lines: string[] = []
  for (const word of words) {
    const last = lines.length - 1
    if (last >= 0 && lines[last].length + word.length + 1 <= width) lines[last] += ` ${word}`
    else lines.push(word)
  }
  return lines.length ? lines : ['']
}

export function layoutGraph(nodes: Array<{ id: string; label: string }>) {
  const columns = Math.max(1, Math.ceil(Math.sqrt(nodes.length)))
  const rows = Math.ceil(nodes.length / columns)
  const labels = nodes.map(node => wrapNodeLabel(node.label))
  const nodeHeight = Math.max(54, ...labels.map(lines => lines.length * 19 + 22))
  const width = columns * 236 + 32
  const height = rows * (nodeHeight + 74) + 24
  const positions = new Map(nodes.map((node, i) => [node.id, {
    x: 134 + (i % columns) * 236,
    y: 20 + nodeHeight / 2 + Math.floor(i / columns) * (nodeHeight + 74),
    lines: labels[i],
  }]))
  return { width, height, nodeHeight, positions }
}
