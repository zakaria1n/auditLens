import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useChatModel } from '../../features/chat/useChatModel'

import { repairPresentation, searchThread } from '../../lib/chatApi'
import { useChatWorkspaceCtx } from '../../lib/chatWorkspaceContext'
import { WelcomeScreen } from '../../features/chat/components/WelcomeScreen'
import { buildSelectionMessage, selectionForContext, type BoundVizSelection, type VizSelection } from '../../features/intelligent-ui/interactions/selection'
import { SelectionChip } from '../../features/intelligent-ui/interactions/SelectionChip'
import { ChatMessages } from './ChatMessages'
import { ChatComposer } from '../../features/chat/ChatComposer'

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
  const location = useLocation()
  const navigate = useNavigate()
  const chatModel = useChatModel(location.pathname)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [boundSelection, setBoundSelection] = useState<BoundVizSelection | null>(null)
  const [selectionResetKey, setSelectionResetKey] = useState(0)
  const selection = selectionForContext(boundSelection, ws.activeId, ws.headId)
  const setSelection = (value: VizSelection | null) => setBoundSelection(value ? { threadId: ws.activeId, headId: ws.headId, value } : null)
  const clearSelection = () => { setSelection(null); setSelectionResetKey(value => value + 1) }

  const sendWithSelection = async (text: string, withSelection: VizSelection | null, explanationOnly = false) => {
    const final = withSelection ? buildSelectionMessage({ ...withSelection, threadId: ws.activeId ?? undefined, branchId: ws.headId ?? undefined }, text) : text
    clearSelection()
    if (ws.activeId) await ws.send(final, undefined, explanationOnly)
    else {
      const title = final.split('\n')[0].slice(0, 80)
      const thread = await ws.newThread(title)
      await ws.send(final, thread.id, explanationOnly)
    }
  }

  // investigation immédiate d'une sélection (villes filtres locaux restent sans LLM)
  const investigateSelection = (sel: VizSelection) => {
    void sendWithSelection('', sel).catch(() => ws.notice)
  }

  // anciennes tables d'exploration (data_explore) : même handoff structuré
  const investigateLegacyRecord = (record: Record<string, unknown>) => {
    investigateSelection({ vizType: 'data_table', vizTitle: 'Exploration de données', record })
  }

  const vizCallbacks = {
    onSelect: (sel: VizSelection) => setSelection(sel),
    onClearSelection: clearSelection,
    selectionResetKey: `${ws.activeId}:${ws.headId}:${selectionResetKey}`,
    onExplainSelection: ws.isRunning ? undefined : (sel: VizSelection) => { void sendWithSelection(sel.nodes && sel.nodes.length > 1 ? 'Compare les éléments sélectionnés de cette illustration, sans lancer de mission.' : 'Explique cet élément de la présentation conceptuelle, sans lancer de mission.', sel, true) },
    onInvestigateSelection: (sel: VizSelection) => investigateSelection(sel),
    onRepairPresentation: async (raw: Record<string, unknown>, issue: Record<string, unknown>) => {
      if (!ws.activeId) throw new Error('Conversation indisponible')
      return (await repairPresentation(ws.activeId, raw, issue)).specification
    },
    onOpenEvidence: (evidenceId: string) => {
      const runId = ws.thread?.run_ids?.[ws.thread.run_ids.length - 1]
      navigate(runId ? '/evidence?run_id=' + runId + '&focus=' + evidenceId : '/evidence')
    },
  }

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
    <>
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
              {ws.thread?.mission_ids.length ? `${ws.thread.mission_ids.length} mission(s) liée(s)` : 'Votre espace d’audit'}
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
              className="w-56 rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-700 placeholder:text-slate-400 focus:border-brand-300 focus:outline-none lg:w-64"
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
            className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 xl:hidden"
            hidden={!ws.thread?.run_ids.length}
          >
            Investigation
          </button>
        </header>

        {ws.notice && (
          <div
            className={`mx-4 mt-3 rounded-lg px-3 py-2 text-xs ${
              ws.notice.kind === 'error' ? 'bg-red-50 text-red-700' : 'bg-brand-50 text-brand-700'
            }`}
          >
            {ws.notice.text}
          </div>
        )}

        {searchResults != null ? (
          <div className="hide-scrollbar min-h-0 flex-1 overflow-y-auto px-5 py-6">
            {searchResults.length === 0 ? <p className="text-sm text-slate-400">Aucun résultat.</p> : <ul className="mx-auto max-w-3xl space-y-2">{searchResults.map(r => <li key={r.id} className="rounded-xl border border-slate-200 bg-white p-4 text-sm"><p className="text-xs text-slate-400">{r.role} · {r.created_at}</p><p>{r.snippet}</p></li>)}</ul>}
          </div>
        ) : !ws.loading && ws.messages.length === 0 ? (
          <div className="hide-scrollbar flex min-h-0 flex-1 items-center justify-center overflow-y-auto px-5 py-10">
            {selection && <div className="w-full"><SelectionChip selection={selection} onClear={clearSelection} onInvestigate={selection.mode === 'conceptual' ? undefined : () => investigateSelection(selection)} /></div>}
            <WelcomeScreen
              composer={
                <ChatComposer chatModel={chatModel} drafts={drafts} setDrafts={setDrafts} threadId={ws.activeId} running={ws.isRunning} onSend={async text => { if (ws.activeId) await ws.send(text); else { const title = text.split('\n')[0].slice(0, 80); const thread = await ws.newThread(title); await ws.send(text, thread.id) } }} onCancel={() => void ws.cancel()} />
              }
              onSuggestion={prompt => setDrafts(previous => ({ ...previous, [ws.activeId ?? 'new']: prompt }))}
            />
          </div>
        ) : (
          <><div className="hide-scrollbar min-h-0 flex-1 overflow-y-auto"><div className="mx-auto w-full max-w-[760px] px-5">{ws.loading ? <p className="py-10 text-center text-sm text-slate-400">Chargement…</p> : <ChatMessages key={ws.activeId} messages={ws.messages} branches={ws.branches} headId={ws.headId} isRunning={ws.isRunning} onRegenerate={id => void ws.regenerate(id)} onEdit={(id, content) => void ws.editMessage(id, content)} onSwitchBranch={id => { clearSelection(); void ws.switchBranch(id) }} onOpenThread={id => { void ws.selectThread(id) }} onOpenEvidence={vizCallbacks.onOpenEvidence}
onInvestigate={investigateLegacyRecord} vizCallbacks={vizCallbacks} />}</div></div>
          <footer className="bg-white px-4 pb-4 pt-2"><div className="mx-auto max-w-[760px]">
            {selection && <SelectionChip selection={selection} onClear={clearSelection} onInvestigate={selection.mode === 'conceptual' ? undefined : () => investigateSelection(selection)} />}
            <ChatComposer chatModel={chatModel} drafts={drafts} setDrafts={setDrafts} threadId={ws.activeId} running={ws.isRunning} onSend={text => sendWithSelection(text, selection, selection?.mode === 'conceptual')} onCancel={() => void ws.cancel()} />
          </div></footer></>
        )}
      </section>
    </>
  )
}
