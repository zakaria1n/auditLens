/**
 * Hook workspace chat (ADR-16) — état local synchronisé au backend.
 * Chaque événement SSE est appliqué au rendu ; après le tour, l'état est
 * re-synchronisé depuis le backend (source de vérité) pour éviter toute dérive.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import type { BranchNode, ChatMsg, ChatStreamEvent, ThreadMeta, TurnBody } from './chatApi'
import {
  archiveThread,
  cancelTurn,
  createThread,
  deleteThread,
  getBranches,
  getThread,
  listThreads,
  restoreThread,
  setHead,
  streamTurn,
  updateThread,
} from './chatApi'

export interface Notice {
  kind: 'info' | 'error'
  text: string
}

function nowIso(): string {
  return new Date().toISOString()
}

export function useChatWorkspace() {
  const [threads, setThreads] = useState<ThreadMeta[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [thread, setThread] = useState<ThreadMeta | null>(null)
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [branches, setBranches] = useState<BranchNode[]>([])
  const [headId, setHeadId] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const refreshThreads = useCallback(async () => {
    const data = await listThreads()
    setThreads(data.threads)
    return data.threads
  }, [])

  const loadThread = useCallback(async (id: string) => {
    setLoading(true)
    try {
      const [detail, br] = await Promise.all([getThread(id), getBranches(id)])
      setThread(detail.thread)
      setMessages(detail.messages)
      setHeadId(detail.thread.head_message_id)
      setBranches(br.nodes)
      return detail
    } finally {
      setLoading(false)
    }
  }, [])

  const selectThread = useCallback(
    async (id: string | null) => {
      if (isRunning) return
      setActiveId(id)
      setNotice(null)
      if (id == null) {
        setThread(null)
        setMessages([])
        setBranches([])
        setHeadId(null)
        return
      }
      await loadThread(id)
    },
    [isRunning, loadThread],
  )

  useEffect(() => {
    refreshThreads().catch(() => setNotice({ kind: 'error', text: 'Chargement des conversations impossible' }))
  }, [refreshThreads])

  const newThread = useCallback(async (title?: string) => {
    const { thread: t } = await createThread(title)
    setThreads(previous => [t, ...previous.filter(item => item.id !== t.id)])
    await selectThread(t.id)
    return t
  }, [selectThread])

  /** Cœur du tour : applique les événements SSE au rendu puis re-synchronise. */
  const runTurn = useCallback(
    async (threadId: string, body: TurnBody, truncateBefore?: number) => {
      setIsRunning(true)
      setNotice(null)
      const controller = new AbortController()
      abortRef.current = controller
      let pendingId: string | null = null

      if (truncateBefore != null) {
        setMessages((prev) => prev.slice(0, truncateBefore))
      }

      const ensurePending = () => {
        if (pendingId == null) {
          pendingId = `pending-${Date.now()}`
          const createdId = pendingId
          setMessages((prev) => [
            ...prev,
            {
              id: createdId,
              thread_id: threadId,
              parent_id: null,
              role: 'assistant',
              parts: [],
              status: 'running',
              created_at: nowIso(),
            },
          ])
        }
        return pendingId
      }

      const updatePart = (toolId: string, patch: Partial<ChatMsg['parts'][number]> & { status?: string; result?: Record<string, unknown> }) => {
        const currentPendingId = pendingId
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== currentPendingId) return m
            return {
              ...m,
              parts: m.parts.map((p) =>
                p.type === 'tool_call' && p.id === toolId
                  ? ({ ...p, ...patch } as ChatMsg['parts'][number])
                  : p,
              ),
            }
          }),
        )
      }

      const onEvent = (ev: ChatStreamEvent) => {
        if (ev.type === 'message') {
          if (ev.message.role === 'user') {
            setMessages((prev) => [...prev, ev.message])
          } else {
            const finalId = pendingId
            setMessages((prev) => [...prev.filter((m) => m.id !== finalId), ev.message])
            pendingId = null
          }
        } else if (ev.type === 'assistant_start') {
          ensurePending()
        } else if (ev.type === 'text_delta') {
          const pid = ensurePending()
          setMessages(previous => previous.map(message => {
            if (message.id !== pid) return message
            const parts = [...message.parts]
            const last = parts[parts.length - 1]
            if (last?.type === 'text') parts[parts.length - 1] = { ...last, text: last.text + ev.text }
            else parts.push({ type: 'text', text: ev.text })
            return { ...message, parts }
          }))
        } else if (ev.type === 'tool_call') {
          const pid = ensurePending()
          setMessages((prev) =>
            prev.map((m) =>
              m.id === pid
                ? {
                    ...m,
                    parts: [
                      ...m.parts,
                      { type: 'tool_call', id: ev.id, tool: ev.tool, args: ev.args ?? {}, status: 'running' },
                    ],
                  }
                : m,
            ),
          )
        } else if (ev.type === 'tool_result') {
          updatePart(ev.id, {
            status: ev.status === 'error' ? 'error' : 'complete',
            result: ev.result ?? {},
          } as Partial<ChatMsg['parts'][number]>)
        } else if (ev.type === 'thread') {
          // pont live create_audit : le panel Investigation suit le run pendant le tour
          setThread(ev.thread)
          setThreads(previous => previous.map(item => item.id === ev.thread.id ? { ...item, ...ev.thread } : item))
        } else if (ev.type === 'compaction') {
          if (ev.status === 'compacted') {
            setNotice({
              kind: 'info',
              text: `Contexte compacté : ${ev.summarized_messages ?? 0} message(s) résumés — historique complet conservé (recherche disponible).`,
            })
          } else if (ev.reason) {
            setNotice({ kind: 'info', text: `Compaction non déclenchée : ${ev.reason}` })
          }
        } else if (ev.type === 'error') {
          setNotice({ kind: 'error', text: ev.message })
        }
      }

      try {
        await streamTurn(threadId, body, onEvent, controller.signal)
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          setNotice({ kind: 'error', text: `Erreur de streaming : ${(err as Error).message}` })
        }
      } finally {
        abortRef.current = null
        setIsRunning(false)
        try {
          const detail = await getThread(threadId)
          setThread(detail.thread)
          setMessages(detail.messages)
          setHeadId(detail.thread.head_message_id)
          const br = await getBranches(threadId)
          setBranches(br.nodes)
          await refreshThreads()
        } catch {
          // re-synchronisation best-effort : les événements déjà appliqués restent affichés
        }
      }
    },
    [refreshThreads],
  )

  const send = useCallback(
    async (content: string, threadId?: string) => {
      const targetId = threadId ?? activeId
      if (!targetId || isRunning || !content.trim()) return
      await runTurn(targetId, { content: content.trim(), mode: 'new' })
    },
    [activeId, isRunning, runTurn],
  )

  const editMessage = useCallback(
    async (messageId: string, content: string) => {
      if (!activeId || isRunning || !content.trim()) return
      const idx = messages.findIndex((m) => m.id === messageId)
      if (idx === -1) return
      await runTurn(activeId, { content: content.trim(), mode: 'edit', target_message_id: messageId }, idx)
    },
    [activeId, isRunning, messages, runTurn],
  )

  const regenerate = useCallback(
    async (assistantId: string) => {
      if (!activeId || isRunning) return
      const idx = messages.findIndex((m) => m.id === assistantId)
      if (idx === -1) return
      await runTurn(activeId, { mode: 'regenerate', target_message_id: assistantId }, idx)
    },
    [activeId, isRunning, messages, runTurn],
  )

  const cancel = useCallback(async () => {
    if (!activeId) return
    try {
      // Garder le flux ouvert pour recevoir le message partiel persisté par le backend.
      await cancelTurn(activeId)
    } catch {
      abortRef.current?.abort()
      setNotice({ kind: 'error', text: 'Annulation non confirmée par le serveur : connexion interrompue.' })
    }
  }, [activeId])

  const switchBranch = useCallback(
    async (messageId: string) => {
      if (!activeId || isRunning) return
      await setHead(activeId, messageId)
      // descendre jusqu'à la feuille de la branche (dernier enfant à chaque niveau)
      // pour afficher l'échange complet, pas seulement le message cible
      const nodes = await getBranches(activeId)
      const children = new Map<string | null, typeof nodes.nodes>()
      for (const nd of nodes.nodes) {
        const arr = children.get(nd.parent_id) ?? []
        arr.push(nd)
        children.set(nd.parent_id, arr)
      }
      let cur = messageId
      for (;;) {
        const kids = (children.get(cur) ?? []).sort((a, b) => a.created_at.localeCompare(b.created_at))
        if (kids.length === 0) break
        cur = kids[kids.length - 1].id
      }
      if (cur !== messageId) await setHead(activeId, cur)
      await loadThread(activeId)
    },
    [activeId, isRunning, loadThread],
  )

  const updateMetadata = useCallback(async (id: string, changes: { title?: string; pinned?: boolean }) => {
    const { thread: updated } = await updateThread(id, changes)
    setThreads(previous => previous.map(item => item.id === id ? { ...item, ...updated } : item))
    setThread(previous => previous?.id === id ? { ...previous, ...updated } : previous)
  }, [])

  const archive = useCallback(
    async (id: string) => {
      await archiveThread(id)
      await refreshThreads()
      if (activeId === id) await selectThread(null)
    },
    [activeId, refreshThreads, selectThread],
  )

  const restore = useCallback(
    async (id: string) => {
      await restoreThread(id)
      await refreshThreads()
    },
    [refreshThreads],
  )

  const remove = useCallback(
    async (id: string) => {
      await deleteThread(id)
      await refreshThreads()
      if (activeId === id) await selectThread(null)
    },
    [activeId, refreshThreads, selectThread],
  )

  return {
    threads,
    activeId,
    thread,
    messages,
    branches,
    headId,
    isRunning,
    notice,
    loading,
    setNotice,
    newThread,
    selectThread,
    send,
    editMessage,
    regenerate,
    cancel,
    switchBranch,
    updateMetadata,
    archive,
    restore,
    remove,
  }
}

export type ChatWorkspace = ReturnType<typeof useChatWorkspace>
