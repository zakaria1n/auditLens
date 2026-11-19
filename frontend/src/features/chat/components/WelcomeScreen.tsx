import type { ReactNode } from 'react'

import { AuditLensLogo } from '../../../components/brand/AuditLensLogo'

export interface Suggestion {
  label: string
  description: string
  prompt: string
  /** clé d'icône simple — rendu par WelcomeIcon, aucune donnée arbitraire. */
  icon: 'erp' | 'api' | 'web' | 'file'
}

const DEFAULT_SUGGESTIONS: Suggestion[] = [
  {
    label: 'Auditer mon ERP',
    description: 'Périmètre, sources autorisées et contrôles de réconciliation.',
    prompt:
      'Je souhaite auditer un ERP Odoo. Aidez-moi à définir le périmètre, connecter les sources autorisées et choisir les contrôles de réconciliation.',
    icon: 'erp',
  },
  {
    label: 'Inspecter une API',
    description: 'Contrat OpenAPI, endpoints approuvés, lectures vérifiables.',
    prompt:
      'Je souhaite inspecter une API autorisée : vérifier son contrat OpenAPI et effectuer des lectures bornées sur les endpoints approuvés.',
    icon: 'api',
  },
  {
    label: 'Analyser une application Web',
    description: 'Parcours déclarés, assertions, captures et erreurs JS.',
    prompt:
      'Je souhaite analyser une application Web autorisée via des parcours déclarés : étapes, assertions et captures.',
    icon: 'web',
  },
  {
    label: 'Explorer un fichier de données',
    description: 'CSV, XLSX ou JSON importé : profil, exploration, anomalies.',
    prompt:
      'Je souhaite explorer un fichier de données importé (CSV/XLSX/JSON) : profil des colonnes, exploration bornée et détection d’anomalies avec preuves.',
    icon: 'file',
  },
]

const ICON_PATHS: Record<Suggestion['icon'], ReactNode> = {
  erp: (
    <>
      <path d="M12 3v3m0 12v3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1M3 12h3m12 0h3M5.6 18.4l2.1-2.1m8.6-8.6 2.1-2.1" />
      <circle cx="12" cy="12" r="3.5" />
    </>
  ),
  api: (
    <>
      <path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 5.5l-3 13" />
    </>
  ),
  web: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.8 2.6 4.2 5.6 4.2 9S14.8 18.4 12 21c-2.8-2.6-4.2-5.6-4.2-9S9.2 5.6 12 3z" />
    </>
  ),
  file: (
    <>
      <path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" />
      <path d="M14 3v5h5M9 13h6M9 17h6" />
    </>
  ),
}

function WelcomeIcon({ icon }: { icon: Suggestion['icon'] }) {
  return (
    <svg
      className="h-4 w-4"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {ICON_PATHS[icon]}
    </svg>
  )
}

interface WelcomeScreenProps {
  /** Slot du compositeur : la version active réutilise exactement le même composant. */
  composer: ReactNode
  suggestions?: Suggestion[]
  /** Suggestion choisie : le texte est déposé dans le brouillon (jamais envoyé seul). */
  onSuggestion: (prompt: string) => void
}

/**
 * Écran d'accueil d'une conversation vide : marque, promesse, compositeur centré,
 * suggestions réelles (qui remplissent le brouillon — aucun envoi automatique).
 */
export function WelcomeScreen({ composer, suggestions = DEFAULT_SUGGESTIONS, onSuggestion }: WelcomeScreenProps) {
  return (
    <div className="al-fade-up w-full max-w-[690px]">
      <div className="mb-9 flex flex-col items-center text-center">
        <AuditLensLogo size={60} className="!rounded-[22px]" />
        <p className="mt-5 text-xs font-semibold uppercase tracking-[0.2em] text-brand-600">
          AuditLens workspace
        </p>
        <h2 className="mt-2 text-3xl font-semibold tracking-tight text-ink-900">
          Que souhaitez-vous examiner&nbsp;?
        </h2>
        <p className="mt-3 max-w-md text-sm leading-6 text-ink-500">
          Explorez vos sources autorisées et construisez une investigation fondée sur des preuves
          vérifiables — chaque conclusion reste soumise à votre revue.
        </p>
      </div>

      {composer}

      <div className="mt-6 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {suggestions.map((s) => (
          <button key={s.label} type="button" className="suggestion" onClick={() => onSuggestion(s.prompt)}>
            <span className="suggestion-icon">
              <WelcomeIcon icon={s.icon} />
            </span>
            <span className="min-w-0">
              <span className="block text-[13px] font-semibold text-ink-700">{s.label}</span>
              <span className="mt-0.5 block truncate text-xs text-ink-400">{s.description}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
