import { useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { useChatWorkspaceCtx } from '../lib/chatWorkspaceContext'
import { ChatCenter } from './chat/ChatCenter'
import { InvestigationPanel } from './chat/InvestigationPanel'
import { ThreadSidebar } from './chat/ThreadSidebar'

const CHAT_ROUTES = new Set(['/', '/chat'])

/**
 * Shell unique (ADR-17) : sidebar conversations à gauche, conversation centrale
 * (TOUJOURS montée — l'état chat survit à l'ouverture d'une page du menu),
 * panneau Investigation repliable à droite (overlay sous `lg`).
 * Les anciennes pages restent accessibles par routes profondes dans la zone centrale.
 */
export function AppShell() {
  const ws = useChatWorkspaceCtx()
  const location = useLocation()
  const navigate = useNavigate()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [investigationOpen, setInvestigationOpen] = useState(false)

  const isChatRoute = CHAT_ROUTES.has(location.pathname)
  const subPageTitle = isChatRoute
    ? ''
    : {
        '/connections': 'Connections',
        '/reports': 'Rapports',
        '/settings': 'Réglages IA',
      }[location.pathname] ?? 'Vue détaillée'

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <ThreadSidebar
        threads={ws.threads}
        activeId={ws.activeId}
        isRunning={ws.isRunning}
        onSelect={(id) => {
          void ws.selectThread(id)
          if (!isChatRoute) navigate('/chat')
        }}
        onNew={() => void ws.newThread()}
        onArchive={(id) => void ws.archive(id)}
        onRestore={(id) => void ws.restore(id)}
        onDelete={(id) => void ws.remove(id)}
        mobileOpen={sidebarOpen}
        onCloseMobile={() => setSidebarOpen(false)}
      />

      <main className="relative min-w-0 flex-1">
        {/* conversation : toujours montée, invisibilisée sous une sous-page (état + scroll préservés) */}
        <div
          className={`absolute inset-0 flex overflow-hidden ${
            isChatRoute ? 'visible' : 'invisible pointer-events-none'
          }`}
          aria-hidden={!isChatRoute}
        >
          <ChatCenter
            onOpenSidebar={() => setSidebarOpen(true)}
            onToggleInvestigation={() => setInvestigationOpen((v) => !v)}
          />
          <InvestigationPanel
            missionIds={ws.thread?.mission_ids ?? []}
            runIds={ws.thread?.run_ids ?? []}
            mobileOpen={investigationOpen}
            onCloseMobile={() => setInvestigationOpen(false)}
          />
        </div>

        {/* sous-pages du menu + deep links historiques */}
        {!isChatRoute && (
          <div className="absolute inset-0 z-10 flex flex-col overflow-hidden bg-white">
            <div className="flex items-center gap-3 border-b border-slate-200 px-4 py-2.5">
              <button
                type="button"
                onClick={() => navigate('/chat')}
                className="rounded-lg px-2.5 py-1.5 text-xs font-semibold text-indigo-600 hover:bg-indigo-50"
              >
                ← Conversation
              </button>
              <p className="text-sm font-semibold text-slate-700">{subPageTitle}</p>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-6xl px-4 py-6 md:px-8">
                <Outlet />
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
