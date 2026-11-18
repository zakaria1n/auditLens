/**
 * Client conversations chat-first (ADR-16) — le backend est la source de vérité ;
 * le frontend n'invente aucun message. Streaming SSE via fetch (POST + lecture).
 */

import { API_BASE, ApiError } from './api'

export type ChatRole = 'user' | 'assistant' | 'system'

export interface TextPart {
  type: 'text'
  text: string
}

export interface ToolCallPart {
  type: 'tool_call'
  id: string
  tool: string
  args?: Record<string, unknown>
  status: 'complete' | 'error' | 'running'
  result?: Record<string, unknown>
  error?: string | null
  duration_ms?: number
}

export type ChatPart = TextPart | ToolCallPart

export interface ChatMsg {
  id: string
  thread_id: string
  parent_id: string | null
  role: ChatRole
  parts: ChatPart[]
  status: 'complete' | 'running' | 'incomplete' | 'error'
  run_id?: string | null
  provider_id?: string | null
  model_id?: string | null
  created_at: string
}

export interface ThreadMeta {
  id: string
  title: string
  status: 'active' | 'archived' | 'deleted'
  head_message_id: string | null
  mission_ids: string[]
  run_ids: string[]
  context_summary?: string | null
  summary_upto_message_id?: string | null
  compacted_message_count?: number
  updated_at: string
}

export interface BranchNode {
  id: string
  parent_id: string | null
  role: ChatRole
  status: string
  created_at: string
  preview: string
}

export type ChatStreamEvent =
  | { type: 'message'; message: ChatMsg }
  | { type: 'head'; head_message_id: string }
  | { type: 'tool_call'; id: string; tool: string; args?: Record<string, unknown> }
  | { type: 'tool_result'; id: string; tool: string; status: string; result?: Record<string, unknown> }
  | { type: 'thread'; thread: ThreadMeta }
  | { type: 'compaction'; status?: string; reason?: string; summarized_messages?: number }
  | { type: 'error'; message: string }
  | { type: 'done'; status: string; rounds?: number }

export function listThreads() {
  return request<{ threads: ThreadMeta[] }>('/api/conversations')
}

export function createThread(title?: string) {
  return request<{ thread: ThreadMeta }>('/api/conversations', {
    method: 'POST',
    body: JSON.stringify({ title: title ?? null }),
  })
}

export function getThread(id: string) {
  return request<{ thread: ThreadMeta; messages: ChatMsg[] }>(`/api/conversations/${id}`)
}

export function getBranches(id: string) {
  return request<{ head_message_id: string | null; nodes: BranchNode[] }>(
    `/api/conversations/${id}/branches`,
  )
}

export function setHead(id: string, messageId: string) {
  return request<{ thread: ThreadMeta }>(`/api/conversations/${id}/head`, {
    method: 'POST',
    body: JSON.stringify({ message_id: messageId }),
  })
}

export function cancelTurn(id: string) {
  return request<{ ok: boolean }>(`/api/conversations/${id}/cancel`, { method: 'POST' })
}

export function archiveThread(id: string) {
  return request<{ thread: ThreadMeta }>(`/api/conversations/${id}/archive`, { method: 'POST' })
}

export function restoreThread(id: string) {
  return request<{ thread: ThreadMeta }>(`/api/conversations/${id}/restore`, { method: 'POST' })
}

export function deleteThread(id: string) {
  return request<{ ok: boolean }>(`/api/conversations/${id}`, { method: 'DELETE' })
}

export function searchThread(id: string, q: string) {
  return request<{
    query: string
    head_message_id: string | null
    results: { id: string; role: ChatRole; created_at: string; status: string; snippet: string }[]
  }>(`/api/conversations/${id}/search?q=${encodeURIComponent(q)}`)
}

export interface TurnBody {
  content?: string | null
  mode?: 'new' | 'edit' | 'regenerate'
  target_message_id?: string | null
}

/** Tour de conversation en SSE : chaque événement backend est transmis à onEvent. */
export async function streamTurn(
  threadId: string,
  body: TurnBody,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/conversations/${threadId}/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    let detail = `HTTP ${res.status}`
    try {
      const data = (await res.json()) as { detail?: unknown }
      if (typeof data.detail === 'string') detail = data.detail
    } catch {
      // corps non JSON
    }
    throw new ApiError(res.status, detail)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      for (const line of raw.split('\n')) {
        if (line.startsWith('data: ')) {
          try {
            onEvent(JSON.parse(line.slice(6)) as ChatStreamEvent)
          } catch {
            // chunk JSON invalide : ignoré (le backend garantit un JSON par événement)
          }
        }
      }
    }
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {}
  if (init?.body != null) headers['Content-Type'] = 'application/json'
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const data = (await res.json()) as { detail?: unknown }
      if (typeof data.detail === 'string') detail = data.detail
    } catch {
      // corps non JSON
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}
