import type { HTMLAttributes } from 'react'

export type BadgeTone =
  | 'neutral'
  | 'green'
  | 'red'
  | 'amber'
  | 'blue'
  | 'indigo'
  | 'violet'

const toneClasses: Record<BadgeTone, string> = {
  neutral: 'bg-slate-100 text-slate-700 border-slate-200',
  green: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  red: 'bg-red-50 text-red-700 border-red-200',
  amber: 'bg-amber-50 text-amber-800 border-amber-200',
  blue: 'bg-blue-50 text-blue-700 border-blue-200',
  indigo: 'bg-brand-50 text-brand-700 border-brand-200',
  violet: 'bg-brand-50 text-brand-700 border-brand-200',
}

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone
  pulsing?: boolean
}

export function Badge({
  tone = 'neutral',
  pulsing = false,
  className = '',
  children,
  ...props
}: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${toneClasses[tone]} ${className}`}
      {...props}
    >
      {pulsing ? (
        <span className="al-pulse-dot h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      ) : (
        <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden="true" />
      )}
      {children}
    </span>
  )
}
