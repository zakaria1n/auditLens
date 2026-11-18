import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import type { ThreadMeta } from '../../lib/chatApi'
import { Dialog } from '../ui/dialog'
import { ThreadRow } from './ThreadRow'

interface Props {
  threads: ThreadMeta[]
  activeId: string | null
  isRunning: boolean
  onSelect: (id: string | null) => void
  onNew: () => void
  onArchive: (id: string) => void
  onRestore: (id: string) => void
  onDelete: (id: string) => void
  onUpdate: (id: string, changes: { title?: string; pinned?: boolean }) => Promise<void>
  /** ferme le tiroir mobile après une navigation du menu (ADR-17) */
  onNavigate?: () => void
}

const MENU_ITEMS = [
  {
    to: '/connections',
    label: 'Connections',
    description: 'Sources ERP, API, Web et fichiers autorisées',
    icon: (
      <path d="M12 3v3m0 12v3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1M3 12h3m12 0h3M5.6 18.4l2.1-2.1m8.6-8.6 2.1-2.1" />
    ),
  },
  {
    to: '/reports',
    label: 'Rapports',
    description: 'Archive des rapports générés par les audits',
    icon: <path d="M8 3h8l4 4v14H4V3h4zm0 6h8M8 13h8M8 17h5" />,
  },
  {
    to: '/settings',
    label: 'Réglages IA',
    description: 'Providers, modèles, clés BYOK, budgets',
    icon: (
      <>
        <circle cx="12" cy="12" r="3.2" />
        <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 9 19.36a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.64 9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34H9a1.7 1.7 0 0 0 1.03-1.56V3a2 2 0 1 1 4 0v.09c0 .68.4 1.29 1.03 1.56a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87V9c.27.62.88 1.03 1.56 1.03H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51.97z" />
      </>
    ),
  },
] as const

/** Menu AuditLens en bas de sidebar (style ChatGPT, SANS profil fictif — ADR-17 §2). */
function AuditLensMenu({ onNavigate }: { onNavigate?: () => void }) {
  const [open, setOpen] = useState(false)
  const [aboutOpen, setAboutOpen] = useState(false)
  const [backendVersion, setBackendVersion] = useState<string | null>(null)
  const navigate = useNavigate()
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    const escape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', escape)
    }
  }, [open])

  const go = (to: string) => {
    setOpen(false)
    onNavigate?.()
    navigate(to)
  }

  return (
    <div ref={rootRef} className="relative border-t border-slate-200 p-2">
      {open && (
        <div className="absolute bottom-full left-2 right-2 z-30 mb-2 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
          {MENU_ITEMS.map((item) => (
            <button
              key={item.to}
              type="button"
              onClick={() => go(item.to)}
              className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-slate-50"
            >
              <svg className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                {item.icon}
              </svg>
              <span>
                <span className="block text-sm font-medium text-slate-800">{item.label}</span>
                <span className="block text-[11px] leading-snug text-slate-400">{item.description}</span>
              </span>
            </button>
          ))}
          <div className="border-t border-slate-100">
            <button
              type="button"
              onClick={() => {
                setAboutOpen((v) => !v)
                if (backendVersion == null) {
                  fetch('/api/health')
                    .then((r) => r.json())
                    .then((d: { version?: string }) => setBackendVersion(d.version ?? '?'))
                    .catch(() => setBackendVersion('?'))
                }
              }}
              className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-slate-50"
            >
              <svg className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
                <circle cx="12" cy="12" r="9" />
                <path d="M12 8.2v.2M12 11v5" />
              </svg>
              <span>
                <span className="block text-sm font-medium text-slate-800">À propos</span>
                <span className="block text-[11px] leading-snug text-slate-400">AuditLens V1 — principes et version</span>
              </span>
            </button>
            {aboutOpen && (
              <div className="border-t border-slate-100 bg-slate-50 px-3 py-2.5 text-[11px] leading-relaxed text-slate-500">
                <p>
                  <span className="font-semibold text-slate-700">AuditLens V1</span> — agent d'audit IT
                  assisté LLM. Preuves immuables (SHA-256), lecture seule par défaut, revue humaine
                  obligatoire avant toute conclusion publiée.
                </p>
                <p className="mt-1">
                  Version backend : <code className="font-mono">{backendVersion ?? '…'}</code>
                </p>
              </div>
            )}
          </div>
        </div>
      )}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-slate-100"
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-sm">
          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 3v3m0 12v3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1M3 12h3m12 0h3M5.6 18.4l2.1-2.1m8.6-8.6 2.1-2.1" />
            <circle cx="12" cy="12" r="3.5" />
          </svg>
        </span>
        <span className="flex-1">
          <span className="block text-sm font-semibold text-slate-800">Menu AuditLens</span>
          <span className="block text-[11px] text-slate-400">Connections · Rapports · Réglages IA</span>
        </span>
        <svg className={`h-4 w-4 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="m18 15-6-6-6 6" />
        </svg>
      </button>
    </div>
  )
}

interface SidebarProps extends Props {
  /** tiroir mobile ouvert (ADR-17 : une seule sidebar persistante, overlay en mobile) */
  mobileOpen?: boolean
  onCloseMobile?: () => void
}

export function ThreadSidebar({
  threads,
  activeId,
  isRunning,
  onSelect,
  onNew,
  onArchive,
  onRestore,
  onDelete,
  onUpdate,
  mobileOpen = false,
  onCloseMobile,
}: SidebarProps) {
  const [deleteTarget, setDeleteTarget] = useState<ThreadMeta | null>(null)
  const [filter, setFilter] = useState('')
  const [showArchived, setShowArchived] = useState(false)

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase()
    return threads.filter(
      (t) =>
        (showArchived ? t.status === 'archived' : t.status === 'active') &&
        (q === '' || t.title.toLowerCase().includes(q)),
    )
  }, [threads, filter, showArchived])

  const closeMobile = () => onCloseMobile?.()

  return (
    <>
      {/* backdrop du tiroir mobile */}
      {mobileOpen && (
        <button
          type="button"
          aria-label="Fermer la liste des conversations"
          onClick={closeMobile}
          className="fixed inset-0 z-30 bg-slate-900/40 md:hidden"
        />
      )}
      <Dialog open={deleteTarget !== null} onClose={() => setDeleteTarget(null)} title="Supprimer la conversation ?" description={deleteTarget?.title} footer={<><button type="button" onClick={() => setDeleteTarget(null)} className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">Annuler</button><button type="button" onClick={() => { if (deleteTarget) onDelete(deleteTarget.id); setDeleteTarget(null) }} className="rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white hover:bg-red-800">Supprimer</button></>}><p className="text-sm text-slate-600">La conversation sera masquée. Les messages, les audits et les preuves restent conservés pour la traçabilité.</p></Dialog>
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[260px] shrink-0 flex-col border-r border-slate-200 bg-slate-50/95 backdrop-blur transition-transform duration-200 md:static md:z-auto md:translate-x-0 md:bg-slate-50/70 ${
          mobileOpen ? 'visible translate-x-0' : 'invisible -translate-x-full md:visible'
        }`}
        aria-label="Conversations"
      >
        <div className="flex items-center gap-2 px-4 pt-4 md:hidden">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-600 text-white">
            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M12 3v3m0 12v3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1M3 12h3m12 0h3M5.6 18.4l2.1-2.1m8.6-8.6 2.1-2.1" />
              <circle cx="12" cy="12" r="3.5" />
            </svg>
          </div>
          <p className="text-sm font-semibold text-slate-900">AuditLens</p>
        </div>

        <div className="p-3">
          <button
            type="button"
            onClick={() => {
              onNew()
              closeMobile()
            }}
            disabled={isRunning}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-3 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-indigo-700 disabled:opacity-50"
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M12 5v14M5 12h14" />
            </svg>
            Nouvelle conversation
          </button>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Rechercher…"
            className="mt-2.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 placeholder:text-slate-400 focus:border-indigo-300 focus:outline-none"
          />
          <label className="mt-2 flex items-center gap-1.5 text-xs text-slate-500">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-slate-300"
            />
            Afficher les archivées
          </label>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 pb-3" aria-label="Liste des conversations">
          {visible.length === 0 && (
            <p className="px-3 py-6 text-center text-xs text-slate-400">Aucune conversation</p>
          )}
          {([true, false] as const).map(pinned => {
            const section = visible.filter(t => Boolean(t.pinned) === pinned)
            if (!section.length) return null
            return <section key={String(pinned)} className="mb-3"><h2 className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">{pinned ? 'Épinglées' : 'Conversations'}</h2><ul className="flex flex-col gap-0.5">{section.map(t => <ThreadRow key={t.id} thread={t} active={activeId === t.id} disabled={isRunning} onSelect={() => { onSelect(t.id); closeMobile() }} onUpdate={changes => onUpdate(t.id, changes)} onArchive={() => onArchive(t.id)} onRestore={() => onRestore(t.id)} onDelete={() => setDeleteTarget(t)} />)}</ul></section>
          })}
        </nav>

        <AuditLensMenu onNavigate={closeMobile} />

      </aside>
    </>
  )
}
