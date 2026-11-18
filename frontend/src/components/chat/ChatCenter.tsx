import { useState } from 'react'

import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  ThreadPrimitive,
  useExternalStoreRuntime,
} from '@assistant-ui/react'
import type { ThreadMessageLike } from '@assistant-ui/react'

import { searchThread } from '../../lib/chatApi'
import type { ChatMsg } from '../../lib/chatApi'
import { useChatWorkspaceCtx } from '../../lib/chatWorkspaceContext'
import { ChatMessages } from './ChatMessages'

type Json = string | number | boolean | null | Json[] | { [key: string]: Json }

/** ChatMsg → ThreadMessageLike (format assistant-ui) : la couche 1 backend reste source de vérité. */
function toThreadMessageLike(m: ChatMsg): ThreadMessageLike {
  const writable: Array<
    | { type: 'text'; text: string }
    | {
        type: 'tool-call'
        toolCallId: string
        toolName: string
        args?: Json
        result?: Json
        isError?: boolean
        isPreliminary?: boolean
      }
  > = []
  for (const p of m.parts) {
    if (p.type === 'text') {
      writable.push({ type: 'text', text: p.text })
    } else if (p.status === 'running') {
      writable.push({
        type: 'tool-call',
        toolCallId: p.id,
        toolName: p.tool,
        args: (p.args ?? {}) as Json,
        isPreliminary: true,
      })
    } else {
      writable.push({
        type: 'tool-call',
        toolCallId: p.id,
        toolName: p.tool,
        args: (p.args ?? {}) as Json,
        result: (p.result ?? {}) as Json,
        isError: p.status === 'error',
      })
    }
  }
  if (writable.length === 0) writable.push({ type: 'text', text: '' })
  // args/result sont des objets JSON produits par le backend (sanitizés) : cast sûr vers le
  // format lecture-seule attendu par assistant-ui (ReadonlyJSONObject).
  const content = writable as unknown as ThreadMessageLike['content']
  return { role: m.role === 'assistant' ? 'assistant' : m.role === 'user' ? 'user' : 'system', content, id: m.id }
}

function extractText(content: readonly unknown[]): string {
  return content
    .filter(
      (part): part is { type: 'text'; text: string } =>
        typeof part === 'object' &&
        part !== null &&
        (part as { type?: unknown }).type === 'text' &&
        typeof (part as { text?: unknown }).text === 'string',
    )
    .map((part) => part.text)
    .join('\n')
}

interface SearchResult {
  id: string
  role: string
  snippet: string
  created_at: string
}

interface Props {
  onOpenSidebar: () => void
  onToggleInvestigation: () => void
}

/** Centre de la conversation : vue toujours montée dans le shell (ADR-17) —
 * l'historique, la branche active et le scroll survivent à l'ouverture d'une
 * page du menu (Connections, Rapports, Réglages). */
export function ChatCenter({ onOpenSidebar, onToggleInvestigation }: Props) {
  const ws = useChatWorkspaceCtx()
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null)
  const [searching, setSearching] = useState(false)

  const runtime = useExternalStoreRuntime({
    isRunning: ws.isRunning,
    messages: ws.messages,
    convertMessage: toThreadMessageLike,
    onNew: async (message) => {
      const text = extractText(message.content as readonly unknown[])
      if (text.trim()) await ws.send(text)
    },
    onCancel: async () => {
      await ws.cancel()
    },
  })

  const doSearch = async () => {
    if (!ws.activeId || !searchQuery.trim()) return
    setSearching(true)
    try {
      const data = await searchThread(ws.activeId, searchQuery.trim())
      setSearchResults(data.results)
    } catch {
      setSearchResults([])
    } finally {
      setSearching(false)
    }
  }

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-slate-200 bg-white px-3 py-2.5 md:px-5">
          <button
            type="button"
            onClick={onOpenSidebar}
            aria-label="Ouvrir la liste des conversations"
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 md:hidden"
          >
            <svg className="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold text-slate-900">
              {ws.thread?.title ?? 'Assistant d’audit AuditLens'}
            </h1>
            <p className="truncate text-[11px] text-slate-400">
              {ws.thread
                ? `conversation ${ws.thread.id}${ws.thread.mission_ids.length ? ` · ${ws.thread.mission_ids.length} mission(s)` : ''}`
                : 'Sélectionnez ou créez une conversation'}
            </p>
          </div>
          <div className="hidden items-center gap-2 sm:flex">
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void doSearch()
              }}
              placeholder="Rechercher dans la conversation (y compris compacté)…"
              className="w-56 rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-700 placeholder:text-slate-400 focus:border-indigo-300 focus:outline-none lg:w-64"
              disabled={!ws.activeId}
            />
            <button
              type="button"
              onClick={() => void doSearch()}
              disabled={!ws.activeId || !searchQuery.trim() || searching}
              className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            >
              {searching ? '…' : 'Chercher'}
            </button>
            {searchResults != null && (
              <button
                type="button"
                onClick={() => setSearchResults(null)}
                className="text-xs text-slate-400 hover:text-slate-700"
              >
                ✕
              </button>
            )}
          </div>
          <button
            type="button"
            onClick={onToggleInvestigation}
            aria-label="Ouvrir le panneau investigation"
            className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 lg:hidden"
          >
            Investigation
          </button>
        </header>

        {ws.notice && (
          <div
            className={`mx-4 mt-3 rounded-lg px-3 py-2 text-xs ${
              ws.notice.kind === 'error' ? 'bg-red-50 text-red-700' : 'bg-violet-50 text-violet-700'
            }`}
          >
            {ws.notice.text}
          </div>
        )}

        {searchResults != null ? (
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
            {searchResults.length === 0 ? (
              <p className="text-sm text-slate-400">Aucun résultat.</p>
            ) : (
              <ul className="mx-auto w-full max-w-[760px] space-y-2">
                {searchResults.map((r) => (
                  <li key={r.id} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm">
                    <p className="mb-0.5 flex items-center gap-2 text-[11px] text-slate-400">
                      <span className="font-mono">{r.id}</span>
                      <span>{r.role}</span>
                      <span>{r.created_at}</span>
                    </p>
                    <p className="text-slate-700">{r.snippet}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-[760px] px-5">
              {!ws.activeId ? (
                <div className="flex h-full flex-col items-center justify-center gap-3 py-24 text-center">
                  <p className="text-2xl font-semibold text-slate-800">Chat-First Audit Workspace</p>
                  <p className="max-w-md text-sm text-slate-500">
                    Discutez avec l'assistant d'audit : lancez des investigations réelles, suivez les
                    outils exécutés, examinez les preuves et les constats — chaque action affichée
                    provient du backend.
                  </p>
                </div>
              ) : ws.loading ? (
                <p className="py-10 text-center text-sm text-slate-400">Chargement…</p>
              ) : (
                <ChatMessages
                  messages={ws.messages}
                  branches={ws.branches}
                  headId={ws.headId}
                  isRunning={ws.isRunning}
                  onRegenerate={(id) => void ws.regenerate(id)}
                  onEdit={(id, content) => void ws.editMessage(id, content)}
                  onSwitchBranch={(id) => void ws.switchBranch(id)}
                />
              )}
            </div>
          </div>
        )}

        {ws.activeId && (
          <footer className="border-t border-slate-200 bg-white px-3 py-3 md:px-4">
            <div className="mx-auto max-w-3xl">
              <ComposerPrimitive.Root className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-white p-2 shadow-sm focus-within:border-indigo-300">
                <ComposerPrimitive.Input
                  rows={1}
                  autoFocus
                  placeholder="Demandez un audit, interrogez un constat, demandez une preuve…"
                  className="max-h-44 min-h-[2.5rem] flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] leading-relaxed text-slate-800 placeholder:text-slate-400 focus:outline-none"
                />
                <ThreadPrimitive.If running={false}>
                  <ComposerPrimitive.Send className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600 text-white transition-colors hover:bg-indigo-700 disabled:opacity-40">
                    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="m22 2-7 20-4-9-9-4Z" />
                      <path d="M22 2 11 13" />
                    </svg>
                  </ComposerPrimitive.Send>
                </ThreadPrimitive.If>
                <ThreadPrimitive.If running>
                  <ComposerPrimitive.Cancel className="flex h-9 items-center rounded-xl border border-red-200 bg-red-50 px-3 text-xs font-semibold text-red-700 hover:bg-red-100">
                    Arrêter
                  </ComposerPrimitive.Cancel>
                </ThreadPrimitive.If>
              </ComposerPrimitive.Root>
              <p className="mt-1.5 px-1 text-[11px] text-slate-400">
                L'assistant n'accède jamais directement aux systèmes : les audits passent par le moteur
                AuditLens (Policy Gate, preuves SHA-256, revue humaine).
              </p>
            </div>
          </footer>
        )}
      </section>
    </AssistantRuntimeProvider>
  )
}
