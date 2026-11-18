import { useEffect, useRef, useState } from 'react'

import type { BranchNode, ChatMsg } from '../../lib/chatApi'
import { MarkdownView } from '../MarkdownView'
import { ExplorationTable } from '../../features/data-exploration/ExplorationTable'
import type { ExplorationResult } from '../../features/data-exploration/ExplorationTable'
import { SourceIntelligenceCard } from '../../features/source-discovery/SourceIntelligenceCard'
import type { SourceIntelligence } from '../../features/source-discovery/SourceIntelligenceCard'
import { ToolCallCard } from './ToolCallCard'

interface MessagesProps {
  messages: ChatMsg[]
  branches: BranchNode[]
  headId: string | null
  isRunning: boolean
  onRegenerate: (assistantId: string) => void
  onEdit: (userMessageId: string, content: string) => void
  onSwitchBranch: (messageId: string) => void
  onInvestigate?: (record: Record<string, unknown>) => void
}

function siblingsOf(branches: BranchNode[], message: ChatMsg): BranchNode[] {
  return branches.filter((n) => n.parent_id === message.parent_id && n.role === message.role)
}

function MessageStatusBadge({ status }: { status: string }) {
  if (status === 'complete') return null
  const map: Record<string, { cls: string; label: string }> = {
    running: { cls: 'bg-blue-50 text-blue-700', label: 'génération en cours…' },
    incomplete: { cls: 'bg-amber-50 text-amber-700', label: 'interrompu (annulé)' },
    error: { cls: 'bg-red-50 text-red-700', label: 'erreur provider' },
  }
  const info = map[status]
  if (!info) return null
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${info.cls}`}>{info.label}</span>
  )
}

function BranchPicker({
  message,
  branches,
  onSwitchBranch,
}: {
  message: ChatMsg
  branches: BranchNode[]
  headId: string | null
  onSwitchBranch: (messageId: string) => void
}) {
  const siblings = siblingsOf(branches, message)
  if (siblings.length <= 1) return null
  const idx = siblings.findIndex((s) => s.id === message.id)
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-1.5 py-0.5 text-[11px] text-slate-500">
      <button
        type="button"
        aria-label="Version précédente"
        disabled={idx <= 0}
        onClick={() => onSwitchBranch(siblings[idx - 1]?.id ?? message.id)}
        className="px-0.5 disabled:opacity-30 hover:text-slate-900"
      >
        ‹
      </button>
      <span className="font-mono">
        {idx + 1}/{siblings.length}
      </span>
      <button
        type="button"
        aria-label="Version suivante"
        disabled={idx >= siblings.length - 1}
        onClick={() => onSwitchBranch(siblings[idx + 1]?.id ?? message.id)}
        className="px-0.5 disabled:opacity-30 hover:text-slate-900"
      >
        ›
      </button>
    </span>
  )
}

function EditComposer({
  initial,
  onCancel,
  onSave,
  busy,
}: {
  initial: string
  onCancel: () => void
  onSave: (content: string) => void
  busy: boolean
}) {
  const [value, setValue] = useState(initial)
  return (
    <div className="mt-2 rounded-xl border border-indigo-200 bg-white p-2">
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        rows={2}
        autoFocus
        className="w-full resize-none rounded-lg border-0 text-sm text-slate-800 focus:outline-none"
        placeholder="Modifier la demande (crée une branche — l'historique est conservé)"
      />
      <div className="mt-1.5 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100"
        >
          Annuler
        </button>
        <button
          type="button"
          disabled={busy || !value.trim()}
          onClick={() => onSave(value)}
          className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40"
        >
          Envoyer (nouvelle branche)
        </button>
      </div>
    </div>
  )
}

function UserMessage({
  message,
  branches,
  headId,
  onEdit,
  onSwitchBranch,
  busy,
}: {
  message: ChatMsg
  branches: BranchNode[]
  headId: string | null
  onEdit: (id: string, content: string) => void
  onSwitchBranch: (id: string) => void
  busy: boolean
}) {
  const [editing, setEditing] = useState(false)
  const text = message.parts.filter((p) => p.type === 'text').map((p) => p.text).join('\n')
  return (
    <div className="flex flex-col items-end">
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2.5 text-[15px] leading-relaxed text-white">
        <p className="whitespace-pre-wrap">{text}</p>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <MessageStatusBadge status={message.status} />
        <button type="button" onClick={() => void navigator.clipboard.writeText(text)} className="text-[11px] font-medium text-slate-400 hover:text-indigo-600">Copier</button>
        <BranchPicker message={message} branches={branches} headId={headId} onSwitchBranch={onSwitchBranch} />
        <button
          type="button"
          onClick={() => setEditing((v) => !v)}
          disabled={busy}
          className="text-[11px] font-medium text-slate-400 hover:text-indigo-600 disabled:opacity-40"
        >
          Modifier ↺
        </button>
      </div>
      {editing && (
        <div className="w-full max-w-[85%]">
          <EditComposer
            initial={text}
            busy={busy}
            onCancel={() => setEditing(false)}
            onSave={(content) => {
              setEditing(false)
              onEdit(message.id, content)
            }}
          />
        </div>
      )}
    </div>
  )
}

function AssistantMessage({
  message,
  branches,
  headId,
  isRunning,
  onRegenerate,
  onSwitchBranch,
  onInvestigate,
}: {
  message: ChatMsg
  branches: BranchNode[]
  headId: string | null
  isRunning: boolean
  onRegenerate: (id: string) => void
  onSwitchBranch: (id: string) => void
  onInvestigate?: (record: Record<string, unknown>) => void
}) {
  const text = message.parts.filter((p) => p.type === 'text').map((p) => p.text).join('\n')
  const toolParts = message.parts.filter((p): p is Extract<ChatMsg['parts'][number], { type: 'tool_call' }> => p.type === 'tool_call')
  return (
    <div className="flex flex-col items-start">
      <div className="w-full rounded-2xl rounded-bl-md bg-slate-100/80 px-4 py-3">
        {toolParts.map((p) => {
          if (p.tool === 'inspect_source' && p.result && !p.result.status) {
            return <SourceIntelligenceCard key={p.id} intel={p.result as unknown as SourceIntelligence} />
          }
          if (p.tool === 'data_explore' && p.result && !p.result.status && (p.result as { table?: unknown }).table) {
            return (
              <ExplorationTable
                key={p.id}
                result={p.result as unknown as ExplorationResult}
                onInvestigate={onInvestigate}
              />
            )
          }
          return <ToolCallCard key={p.id} part={p} />
        })}
        {text && (
          <div className="text-[15px] leading-relaxed text-slate-800 [&_p]:my-1.5 [&_li]:my-0.5">
            <MarkdownView markdown={text} />
          </div>
        )}
        {message.status === 'running' && toolParts.length === 0 && !text && (
          <p className="flex items-center gap-2 text-sm text-slate-400">
            <span className="al-pulse-dot inline-block h-2 w-2 rounded-full bg-indigo-500" />
            L'assistant travaille…
          </p>
        )}
        {message.status === 'error' && <MessageStatusBadge status={message.status} />}
      </div>
      <div className="mt-1 flex items-center gap-2">
        <MessageStatusBadge status={message.status === 'error' ? '' : message.status} />
        {text && <button type="button" onClick={() => void navigator.clipboard.writeText(text)} className="text-[11px] font-medium text-slate-400 hover:text-indigo-600">Copier</button>}
        <BranchPicker message={message} branches={branches} headId={headId} onSwitchBranch={onSwitchBranch} />
        <button
          type="button"
          disabled={isRunning}
          onClick={() => onRegenerate(message.id)}
          className="text-[11px] font-medium text-slate-400 hover:text-indigo-600 disabled:opacity-40"
        >
          Régénérer ↻
        </button>

      </div>
    </div>
  )
}

/** Liste des messages — rendu 100 % issu des messages persistés backend. */
export function ChatMessages({
  messages,
  branches,
  headId,
  isRunning,
  onRegenerate,
  onEdit,
  onSwitchBranch,
  onInvestigate,
}: MessagesProps) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const followRef = useRef(true)
  useEffect(() => {
    const viewport = bottomRef.current?.closest('.overflow-y-auto')
    if (!viewport) return
    const onScroll = () => { followRef.current = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 100 }
    viewport.addEventListener('scroll', onScroll, { passive: true })
    return () => viewport.removeEventListener('scroll', onScroll)
  }, [])
  useEffect(() => {
    if (followRef.current) bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  return (
    <div className="flex flex-col gap-5 px-1 py-4">
      {messages.map((m) =>
        m.role === 'user' ? (
          <UserMessage key={m.id} message={m} branches={branches} headId={headId} onEdit={onEdit} onSwitchBranch={onSwitchBranch} busy={isRunning} />
        ) : (
          <AssistantMessage
            key={m.id}
            message={m}
            branches={branches}
            headId={headId}
            isRunning={isRunning}
            onRegenerate={onRegenerate}
            onSwitchBranch={onSwitchBranch}
            onInvestigate={onInvestigate}
          />
        ),
      )}
      <div ref={bottomRef} />
    </div>
  )
}
