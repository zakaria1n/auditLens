import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useChatModel } from '../../features/chat/useChatModel'

import { searchThread } from '../../lib/chatApi'
import { useChatWorkspaceCtx } from '../../lib/chatWorkspaceContext'
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
  const chatModel = useChatModel(location.pathname)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null)
  const [searching, setSearching] = useState(false)

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
            hidden={!ws.thread?.run_ids.length}
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
          <div className="hide-scrollbar min-h-0 flex-1 overflow-y-auto px-5 py-6">
            {searchResults.length === 0 ? <p className="text-sm text-slate-400">Aucun résultat.</p> : <ul className="mx-auto max-w-3xl space-y-2">{searchResults.map(r => <li key={r.id} className="rounded-xl border border-slate-200 bg-white p-4 text-sm"><p className="text-xs text-slate-400">{r.role} · {r.created_at}</p><p>{r.snippet}</p></li>)}</ul>}
          </div>
        ) : !ws.loading && ws.messages.length === 0 ? (
          <div className="hide-scrollbar flex min-h-0 flex-1 items-center justify-center overflow-y-auto px-5 py-10">
            <div className="al-event-in w-full max-w-[690px]">
              <div className="mb-8 flex flex-col items-center text-center"><div className="welcome-mark" aria-hidden="true">✳</div><p className="mt-5 text-xs font-semibold uppercase tracking-[.2em] text-indigo-600">AuditLens workspace</p><h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">Que souhaitez-vous examiner ?</h2><p className="mt-3 max-w-md text-sm leading-6 text-slate-500">Explorez vos sources autorisées et construisez une investigation fondée sur des preuves.</p></div>
              <ChatComposer chatModel={chatModel} drafts={drafts} setDrafts={setDrafts} threadId={ws.activeId} running={ws.isRunning} onSend={async text => { if (ws.activeId) await ws.send(text); else { const title = text.split('\n')[0].slice(0, 80); const thread = await ws.newThread(title); await ws.send(text, thread.id) } }} onCancel={() => void ws.cancel()} />
              <div className="mt-6 grid grid-cols-1 gap-2 sm:grid-cols-2">{[
                ['Auditer un ERP', 'Je souhaite auditer un ERP. Aidez-moi à définir le périmètre et les sources autorisées.'],
                ['Inspecter une API', 'Je souhaite inspecter une API autorisée. Quelles informations sont nécessaires ?'],
                ['Analyser une application Web', 'Je souhaite analyser une application Web autorisée. Aidons-nous à définir le périmètre.'],
                ['Explorer des preuves importées', 'Je souhaite explorer les preuves et fichiers importés disponibles.'],
              ].map(([label, text]) => <button key={label} type="button" className="suggestion" onClick={() => setDrafts(previous => ({ ...previous, [ws.activeId ?? 'new']: text }))}><span className="mr-2 text-indigo-500">↗</span>{label}</button>)}</div>
            </div>
          </div>
        ) : (
          <><div className="hide-scrollbar min-h-0 flex-1 overflow-y-auto"><div className="mx-auto w-full max-w-[760px] px-5">{ws.loading ? <p className="py-10 text-center text-sm text-slate-400">Chargement…</p> : <ChatMessages messages={ws.messages} branches={ws.branches} headId={ws.headId} isRunning={ws.isRunning} onRegenerate={id => void ws.regenerate(id)} onEdit={(id, content) => void ws.editMessage(id, content)} onSwitchBranch={id => void ws.switchBranch(id)} onOpenThread={id => { void ws.selectThread(id) }} onInvestigate={record => { const ids = Object.entries(record).filter(([k]) => k.endsWith("_id") || k === "id").map(([k, v]) => k + "=" + String(v)); const label = ids.length > 0 ? ids.join(', ') : JSON.stringify(record).slice(0, 200); const text = "Investigue cet enregistrement (" + label + ") : verifie sa coherence, confronte-le aux autres preuves collectees et documente toute anomalie avec les preuves correspondantes."; if (ws.activeId) { void ws.send(text) } else { void (async () => { const t = await ws.newThread(text.slice(0, 80)); await ws.send(text, t.id) })() } }} />}</div></div>
          <footer className="bg-white px-4 pb-4 pt-2"><div className="mx-auto max-w-[760px]"><ChatComposer chatModel={chatModel} drafts={drafts} setDrafts={setDrafts} threadId={ws.activeId} running={ws.isRunning} onSend={ws.send} onCancel={() => void ws.cancel()} /></div></footer></>
        )}
      </section>
    </>
  )
}
