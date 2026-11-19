import { useEffect, useRef, useState } from 'react'

interface CopyButtonProps {
  text: string
  label?: string
  className?: string
}

/** Copie au presse-papiers avec retour visuel bref (« Copié ») — aucune assertion. */
export function CopyButton({ text, label = 'Copier', className = '' }: CopyButtonProps) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | null>(null)

  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current)
  }, [])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      if (timer.current) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setCopied(false), 1800)
    } catch {
      // presse-papiers indisponible (permission refusée) : silencieux, l'action reste anodine
    }
  }

  return (
    <button
      type="button"
      onClick={() => void copy()}
      aria-label={copied ? 'Copié' : label}
      className={`text-[11px] font-medium text-slate-400 transition-colors hover:text-brand-600 ${className}`}
    >
      {copied ? 'Copié ✓' : label}
    </button>
  )
}
