/** Application-owned actions: generated specifications cannot add endpoints or commands. */
export const ACTIONS = {
  select_node: 'local', select_edge: 'local', select_row: 'local', select_chart: 'local', clear_selection: 'local',
  toggle_accordion: 'local', switch_tab: 'local', filter_table: 'local', sort_table: 'local',
  explain_selection: 'conversation', open_evidence: 'backend',
} as const

export type ActionName = keyof typeof ACTIONS
export function isActionName(value: unknown): value is ActionName {
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(ACTIONS, value)
}

/** A specification cannot supply a callback; only application-owned handlers execute. */
export function dispatchAction(name: unknown, handlers: Partial<Record<ActionName, () => void>>): boolean {
  if (!isActionName(name)) return false
  const handler = handlers[name]
  if (typeof handler !== 'function') return false
  handler()
  return true
}
