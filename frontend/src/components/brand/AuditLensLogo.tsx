interface AuditLensLogoProps {
  /** Taille du carré (px). La marque reste lisible jusqu'à 20px. */
  size?: number
  className?: string
}

/**
 * Marque AuditLens : un objectif (lentille) traversé par un faisceau qui converge
 * en un point — la « mise au point » sur la preuve. Purement décorative (aria-hidden) :
 * le nom est toujours porté par le texte adjacent.
 */
export function AuditLensLogo({ size = 32, className = '' }: AuditLensLogoProps) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center rounded-[30%] bg-brand-600 text-white shadow-card ${className}`}
      style={{ width: size, height: size }}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.9"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ width: size * 0.56, height: size * 0.56 }}
      >
        {/* rayons convergents */}
        <path d="M4 4c2.2 2.4 4.4 4 6.2 5.2M20 4c-2.2 2.4-4.4 4-6.2 5.2M12 2.6v3.2" />
        {/* lentille */}
        <circle cx="12" cy="13.4" r="5.1" />
        {/* point de convergence */}
        <circle cx="12" cy="13.4" r="1.15" fill="currentColor" stroke="none" />
      </svg>
    </span>
  )
}
