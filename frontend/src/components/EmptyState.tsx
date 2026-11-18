import type { ReactNode } from 'react'
import { SearchIcon } from './icons'

export interface EmptyStateProps {
  title: string
  description?: string
  action?: ReactNode
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
      <div className="rounded-full bg-slate-100 p-3 text-slate-400">
        <SearchIcon className="h-6 w-6" />
      </div>
      <div>
        <p className="text-sm font-medium text-slate-900">{title}</p>
        {description ? <p className="mt-1 max-w-sm text-xs text-slate-500">{description}</p> : null}
      </div>
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  )
}
