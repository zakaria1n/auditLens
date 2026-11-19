import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

export type ToastKind = 'success' | 'error' | 'info'

export interface ToastItem {
  id: number
  kind: ToastKind
  text: string
}

interface ToastContextValue {
  /** Affiche un toast. À appeler APRÈS confirmation backend (jamais en optimiste). */
  toast: (kind: ToastKind, text: string) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

const DURATION_MS: Record<ToastKind, number> = { success: 3500, info: 4000, error: 6000 }

const KIND_STYLES: Record<ToastKind, string> = {
  success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  error: 'border-red-200 bg-red-50 text-red-800',
  info: 'border-brand-200 bg-brand-50 text-brand-800',
}

const KIND_DOT: Record<ToastKind, string> = {
  success: 'bg-emerald-500',
  error: 'bg-red-500',
  info: 'bg-brand-500',
}

/**
 * File de notifications coin inférieur droit (Phase 2D) : confirmations d'actions
 * conversation (renommer/épingler/archiver/supprimer) et erreurs réseau.
 * Toujours rendu APRÈS confirmation backend ; animation sobre, réduite sous
 * prefers-reduced-motion (CSS global) ; fermeture manuelle et auto-dismiss.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const nextId = useRef(1)

  const dismiss = useCallback((id: number) => {
    setItems((previous) => previous.filter((t) => t.id !== id))
  }, [])

  const toast = useCallback((kind: ToastKind, text: string) => {
    const id = nextId.current++
    setItems((previous) => [...previous.slice(-3), { id, kind, text }])
  }, [])

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-[70] flex w-[320px] max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {items.map((t) => (
          <ToastRow key={t.id} item={t} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

function ToastRow({ item, onDismiss }: { item: ToastItem; onDismiss: (id: number) => void }) {
  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(item.id), DURATION_MS[item.kind])
    return () => window.clearTimeout(timer)
  }, [item.id, item.kind, onDismiss])

  return (
    <div
      role={item.kind === 'error' ? 'alert' : 'status'}
      className={`al-event-in pointer-events-auto flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 shadow-pop ${KIND_STYLES[item.kind]}`}
    >
      <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${KIND_DOT[item.kind]}`} aria-hidden="true" />
      <p className="min-w-0 flex-1 text-[13px] leading-snug">{item.text}</p>
      <button
        type="button"
        onClick={() => onDismiss(item.id)}
        aria-label="Fermer la notification"
        className="shrink-0 rounded-md p-0.5 text-current opacity-60 transition-opacity hover:opacity-100"
      >
        <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>
    </div>
  )
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast doit être utilisé sous ToastProvider')
  return ctx
}
