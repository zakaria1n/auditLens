import { useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { steerRun } from '../lib/api'
import { useChatWorkspaceCtx } from '../lib/chatWorkspaceContext'
import { useToast } from './ui/toast'
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
  const { toast } = useToast()

  const isChatRoute = CHAT_ROUTES.has(location.pathname)
  const subPageTitle = isChatRoute
    ? ''
    : {
        '/connections': 'Connections',
        '/reports': 'Rapports',
        '/settings': 'Réglages IA',
      }[location.pathname] ?? 'Vue détaillée'

  return (
    <div className="flex h-screen overflow-hidden bg-surface-2">
      <ThreadSidebar
        threads={ws.threads}
        activeId={ws.activeId}
        isRunning={ws.isRunning}
        onSelect={(id) => {
          void ws.selectThread(id)
          if (!isChatRoute) navigate('/chat')
        }}
        onNew={() => {
          void ws.newThread()
            .then(() => { navigate('/chat'); toast('success', 'Nouvelle conversation créée.') })
            .catch(() => toast('error', 'Création impossible — vérifiez la connexion au serveur.'))
        }}
        onUpdate={(id, changes) => {
          return ws.updateMetadata(id, changes)
            .then(() => toast('success', changes.title ? 'Conversation renommée.' : 'Épinglage mis à jour.'))
            .catch(() => toast('error', 'Mise à jour impossible.'))
        }}
        onArchive={(id) => {
          void ws.archive(id)
            .then(() => toast('success', 'Conversation archivée — les messages et preuves restent conservés.'))
            .catch(() => toast('error', 'Archivage impossible.'))
        }}
        onRestore={(id) => {
          void ws.restore(id)
            .then(() => toast('success', 'Conversation restaurée.'))
            .catch(() => toast('error', 'Restauration impossible.'))
        }}
        onDelete={(id) => {
          void ws.remove(id)
            .then(() => toast('success', 'Conversation masquée — messages, preuves et runs restent conservés.'))
            .catch(() => toast('error', 'Suppression impossible.'))
        }}
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
          {!!ws.thread?.run_ids.length && <InvestigationPanel
            missionIds={ws.thread?.mission_ids ?? []}
            runIds={ws.thread?.run_ids ?? []}
            onSteer={async (instruction) => {
              const runIds = ws.thread?.run_ids ?? []
              const runId = runIds[runIds.length - 1]
              if (runId) {
                try {
                  await steerRun(runId, instruction)
                  return // routé vers la file du run ; statuts visibles via events panel
                } catch {
                  // run non pilotable (terminé/inconnu) => fallback conversation
                }
              }
              const text = `Pilotage : ${instruction} — intègre cette consigne dans l'investigation en cours.`
              if (ws.activeId) await ws.send(text)
            }}
            onVerifyFix={(findingId) => {
              const text = `Vérification de remédiation : lance un audit ciblé du contrôle lié au constat ${findingId} pour vérifier si les corrections ont été effectives. Documente le résultat avec des preuves.`
              if (ws.activeId) void ws.send(text)
            }}
            mobileOpen={investigationOpen}
            onCloseMobile={() => setInvestigationOpen(false)}
          />}
        </div>

        {/* sous-pages du menu + deep links historiques */}
        {!isChatRoute && (
          <div className="absolute inset-0 z-10 flex flex-col overflow-hidden bg-white">
            <div className="flex items-center gap-3 border-b border-slate-200 px-4 py-2.5">
              <button
                type="button"
                onClick={() => navigate('/chat')}
                className="rounded-lg px-2.5 py-1.5 text-xs font-semibold text-brand-600 hover:bg-brand-50"
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
