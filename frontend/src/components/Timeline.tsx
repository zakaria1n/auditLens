import type { ReactNode } from 'react'

export interface TimelineItem {
  id: string
  tone: 'blue' | 'green' | 'red' | 'amber' | 'neutral' | 'indigo' | 'violet'
  icon: ReactNode
  title: string
  time?: string
  body?: ReactNode
  running?: boolean
}

const dotTones: Record<TimelineItem['tone'], string> = {
  blue: 'bg-blue-500 text-white',
  green: 'bg-emerald-500 text-white',
  red: 'bg-red-500 text-white',
  amber: 'bg-amber-500 text-white',
  neutral: 'bg-slate-300 text-slate-600',
  indigo: 'bg-brand-500 text-white',
  violet: 'bg-brand-500 text-white',
}

/**
 * Timeline verticale alimentée exclusivement par les événements SSE du run.
 * Un élément n'apparaît que lorsqu'un événement backend correspondant est reçu.
 */
export function Timeline({ items }: { items: TimelineItem[] }) {
  return (
    <ol className="relative flex flex-col gap-4 before:absolute before:top-2 before:bottom-2 before:left-[11px] before:w-px before:bg-slate-200">
      {items.map((item) => (
        <li key={item.id} className="al-event-in relative flex gap-4 pl-0">
          <div
            className={`relative z-10 mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
              dotTones[item.tone]
            } ${item.running ? 'al-pulse-dot' : ''}`}
            aria-hidden="true"
          >
            {item.icon}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <p className="text-sm font-medium text-slate-900">{item.title}</p>
              {item.time ? (
                <time className="font-mono text-xs text-slate-400">{item.time}</time>
              ) : null}
            </div>
            {item.body ? <div className="mt-1.5">{item.body}</div> : null}
          </div>
        </li>
      ))}
    </ol>
  )
}
