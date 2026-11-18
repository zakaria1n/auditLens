import { NavLink, Outlet } from 'react-router-dom'
import {
  DocIcon,
  FlagIcon,
  GearIcon,
  HomeIcon,
  PlugIcon,
  PulseIcon,
  SearchIcon,
  TargetIcon,
} from './icons'

const NAV_ITEMS = [
  { to: '/', label: 'Workspace', icon: HomeIcon, end: true },
  { to: '/connections', label: 'Connections', icon: PlugIcon, end: false },
  { to: '/missions/new', label: 'Nouvelle mission', icon: TargetIcon, end: true },
  { to: '/runs', label: 'Live Audit', icon: PulseIcon, end: false },
  { to: '/evidence', label: 'Evidence', icon: SearchIcon, end: false },
  { to: '/findings', label: 'Findings', icon: FlagIcon, end: false },
  { to: '/settings', label: 'Settings LLM', icon: GearIcon, end: true },
]

export function Layout() {
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-sm">
            <svg className="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 3v3m0 12v3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1M3 12h3m12 0h3M5.6 18.4l2.1-2.1m8.6-8.6 2.1-2.1" />
              <circle cx="12" cy="12" r="3.5" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-900">AuditLens</p>
            <p className="text-xs text-slate-400">Audit LLM + preuves</p>
          </div>
        </div>

        <nav className="flex flex-1 flex-col gap-0.5 px-3 py-2" aria-label="Navigation principale">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-150 ${
                  isActive
                    ? 'bg-indigo-50 text-indigo-700'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                }`
              }
            >
              <item.icon className="h-4.5 w-4.5 shrink-0" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-slate-100 px-5 py-4">
          <p className="flex items-center gap-1.5 text-xs text-slate-400">
            <DocIcon className="h-3.5 w-3.5" />
            Aucune assertion sans preuve
          </p>
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
