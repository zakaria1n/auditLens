import { describeSelection, type VizSelection } from './selection'

interface SelectionChipProps {
  selection: VizSelection
  onClear: () => void
  /** Investigation immédiate : le message part avec le contexte structuré. */
  onInvestigate?: () => void
}

/**
 * Contexte de sélection joint au prochain message (Phase 4D) : l'auditeur voit
 * EXACTEMENT ce qui sera transmis à l'agent — aucun « investigue ça » ambigu.
 */
export function SelectionChip({ selection, onClear, onInvestigate }: SelectionChipProps) {
  return (
    <div className="al-event-in mb-2 flex items-center gap-2 rounded-xl border border-brand-200 bg-brand-50/70 px-3 py-2">
      <svg className="h-3.5 w-3.5 shrink-0 text-brand-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M4 4h7v7H4zM13 13h7v7h-7zM13 7h7v7h-7z" opacity="0.6" />
        <path d="M13 7h4v4h-4z" />
      </svg>
      <p className="min-w-0 flex-1 truncate text-[12px] text-brand-800" title={describeSelection(selection)}>
        <span className="font-semibold">{selection.mode === 'conceptual' ? 'Illustration sélectionnée (sans outils) :' : 'Sélection jointe au prochain message :'}</span>{' '}
        {describeSelection(selection)}
      </p>
      {onInvestigate && (
        <button
          type="button"
          onClick={onInvestigate}
          className="shrink-0 rounded-lg bg-brand-600 px-2.5 py-1 text-[11px] font-semibold text-white transition-colors hover:bg-brand-700"
        >
          Investiguer maintenant
        </button>
      )}
      <button
        type="button"
        onClick={onClear}
        aria-label="Retirer la sélection du prochain message"
        className="shrink-0 rounded-md p-1 text-brand-500 transition-colors hover:bg-brand-100 hover:text-brand-700"
      >
        <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>
    </div>
  )
}
