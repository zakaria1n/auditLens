import { Badge } from './ui/badge'
import type { BadgeTone } from './ui/badge'

/**
 * Badge de statut centralisé : affiche TOUJOURS le statut exact du backend,
 * en toutes lettres, sans reformulation ni invention (docs/02 : "No evidence"
 * n'apparaît jamais comme PASS).
 */
const TONES: Record<string, { tone: BadgeTone; pulse: boolean }> = {
  // Runs
  not_started: { tone: 'neutral', pulse: false },
  awaiting_permission: { tone: 'amber', pulse: false },
  running: { tone: 'blue', pulse: true },
  needs_input: { tone: 'amber', pulse: false },
  paused: { tone: 'amber', pulse: false },
  cancelled: { tone: 'neutral', pulse: false },
  partial: { tone: 'amber', pulse: false },
  failed: { tone: 'red', pulse: false },
  completed: { tone: 'green', pulse: false },
  review_required: { tone: 'amber', pulse: false },

  // Assessments
  pass: { tone: 'green', pulse: false },
  fail: { tone: 'red', pulse: false },
  insufficient_evidence: { tone: 'amber', pulse: false },
  not_applicable: { tone: 'neutral', pulse: false },
  not_tested: { tone: 'neutral', pulse: false },
  error: { tone: 'red', pulse: false },
  needs_review: { tone: 'amber', pulse: false },

  // Findings
  accepted: { tone: 'green', pulse: false },
  rejected: { tone: 'red', pulse: false },
  needs_more_evidence: { tone: 'amber', pulse: false },

  // Sources
  untested: { tone: 'neutral', pulse: false },
  connected: { tone: 'green', pulse: false },

  // Tool calls
  success: { tone: 'green', pulse: false },
  unauthorized: { tone: 'red', pulse: false },
  blocked: { tone: 'red', pulse: false },
}

export function StatusBadge({
  value,
  pulsing,
  className,
}: {
  value: string
  pulsing?: boolean
  className?: string
}) {
  const known = TONES[value]
  const tone = known?.tone ?? 'neutral'
  const pulse = pulsing ?? known?.pulse ?? false
  return (
    <Badge tone={tone} pulsing={pulse} className={className}>
      {value}
    </Badge>
  )
}

export function severityTone(severity: string): BadgeTone {
  switch (severity) {
    case 'high':
      return 'red'
    case 'medium':
      return 'amber'
    case 'low':
      return 'blue'
    default:
      return 'neutral'
  }
}
