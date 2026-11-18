import { useState } from 'react'
import { Link } from 'react-router-dom'
import { reviewFinding } from '../lib/api'
import type { Finding } from '../lib/types'
import { errorMessage } from '../lib/useAsync'
import { AlertIcon, CheckIcon, XMarkIcon } from './icons'
import { severityTone } from './StatusBadge'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'
import { Dialog } from './ui/dialog'
import { Field, Textarea } from './ui/input'

type Decision = 'accepted' | 'rejected' | 'needs_more_evidence'

const DECISION_LABEL: Record<Decision, string> = {
  accepted: 'Accepter',
  rejected: 'Rejeter',
  needs_more_evidence: 'Needs More Evidence',
}

const STATUS_LABEL: Record<string, string> = {
  needs_review: 'En attente de revue',
  accepted: 'Accepté',
  rejected: 'Rejeté',
  needs_more_evidence: 'Preuve supplémentaire demandée',
}

export interface FindingCardProps {
  finding: Finding
  onReviewed?: (updated: Finding) => void
  showReviewActions?: boolean
}

function BulletList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <div>
      <p className="mb-1 text-xs font-semibold text-slate-600">{title}</p>
      <ul className="list-disc space-y-1 pl-4">
        {items.map((item, i) => (
          <li key={i} className="text-xs text-slate-600">
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function FindingCard({ finding, onReviewed, showReviewActions = true }: FindingCardProps) {
  const [whyOpen, setWhyOpen] = useState(false)
  const [dialogDecision, setDialogDecision] = useState<Decision | null>(null)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const nonActionable =
    finding.status === 'rejected' || finding.status === 'accepted' || !showReviewActions

  async function submitDecision() {
    if (!dialogDecision) return
    if (!reason.trim()) return // justification obligatoire
    setBusy(true)
    setError(null)
    try {
      const res = await reviewFinding(finding.id, dialogDecision, reason.trim())
      setDialogDecision(null)
      setReason('')
      onReviewed?.(res.finding)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={severityTone(finding.severity_proposed)}>
            severity: {finding.severity_proposed}
          </Badge>
          {finding.control_id ? (
            <Badge tone="indigo">{finding.control_id}</Badge>
          ) : null}
          <Badge tone={finding.status === 'accepted' ? 'green' : finding.status === 'rejected' ? 'red' : 'neutral'}>
            {STATUS_LABEL[finding.status] ?? finding.status}
          </Badge>
        </div>
        <CardTitle className="text-sm leading-snug">{finding.title}</CardTitle>
      </CardHeader>

      <CardContent className="flex flex-col gap-3">
        {finding.rejection_reason ? (
          <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2">
            <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
            <div>
              <p className="text-xs font-semibold text-red-700">Rejeté par le validateur structurel</p>
              <p className="mt-0.5 text-xs text-red-700">{finding.rejection_reason}</p>
            </div>
          </div>
        ) : null}

        <p className="text-sm text-slate-700">{finding.statement}</p>

        {finding.evidence_refs.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-slate-500">Preuves :</span>
            {finding.evidence_refs.map((evId) => (
              <Link
                key={evId}
                to={`/evidence?run_id=${finding.run_id}&focus=${evId}`}
                className="rounded-md border border-indigo-200 bg-indigo-50 px-2 py-0.5 font-mono text-xs text-indigo-700 transition-colors duration-150 hover:bg-indigo-100"
                title="Voir la preuve dans l'Evidence Explorer"
              >
                {evId}
              </Link>
            ))}
          </div>
        ) : (
          <p className="text-xs text-amber-700">
            Aucune preuve rattachée — ce constat ne peut pas être confirmé en l'état.
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {finding.evidence_refs.length > 0 ? (
            <Link
              to={`/evidence?run_id=${finding.run_id}&focus=${finding.evidence_refs[0]}`}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 transition-colors duration-150 hover:bg-slate-100"
            >
              Voir la preuve
            </Link>
          ) : null}
          <Button size="sm" variant="ghost" onClick={() => setWhyOpen((v) => !v)}>
            Pourquoi ?
          </Button>
        </div>

        {whyOpen ? (
          <div className="al-event-in flex flex-col gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
            <BulletList title="Observations" items={finding.observations} />
            <BulletList title="Incertitudes" items={finding.uncertainties} />
            <BulletList title="Limitations" items={finding.limitations} />
            <BulletList title="Recommandations" items={finding.recommendations} />
            {finding.method ? (
              <p className="text-xs text-slate-500">Méthode : {finding.method}</p>
            ) : null}
          </div>
        ) : null}

        {finding.review ? (
          <p className="text-xs text-slate-500">
            Revue ({finding.review.decision}) : {finding.review.reason || 'sans justification'} —{' '}
            {finding.review.timestamp}
          </p>
        ) : null}

        {showReviewActions && finding.status === 'needs_review' ? (
          <div className="mt-1 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
            <Button
              size="sm"
              variant="success"
              onClick={() => setDialogDecision('accepted')}
            >
              <CheckIcon className="h-3.5 w-3.5" /> Accepter
            </Button>
            <Button size="sm" variant="danger" onClick={() => setDialogDecision('rejected')}>
              <XMarkIcon className="h-3.5 w-3.5" /> Rejeter
            </Button>
            <Button size="sm" variant="outline" onClick={() => setDialogDecision('needs_more_evidence')}>
              Needs More Evidence
            </Button>
          </div>
        ) : null}

        {nonActionable && finding.status !== 'needs_review' ? (
          <p className="text-xs text-slate-400">Décision enregistrée — constat non modifiable.</p>
        ) : null}
      </CardContent>

      <Dialog
        open={dialogDecision !== null}
        onClose={() => {
          setDialogDecision(null)
          setError(null)
        }}
        title={dialogDecision ? `${DECISION_LABEL[dialogDecision]} — justification` : ''}
        description="Une justification écrite est obligatoire pour toute décision de revue (docs/02)."
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => {
                setDialogDecision(null)
                setError(null)
              }}
            >
              Annuler
            </Button>
            <Button
              variant={dialogDecision === 'rejected' ? 'danger' : 'primary'}
              onClick={submitDecision}
              disabled={busy || !reason.trim()}
            >
              Confirmer
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Field label="Justification" required hint="Conservée avec la décision et reflétée dans le rapport.">
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={4}
              placeholder="Expliquez la décision (ex. : preuve contradictoire, règle métier, besoin d'un contrôle complémentaire…)"
            />
          </Field>
          {error ? <p className="text-xs text-red-600">{error}</p> : null}
        </div>
      </Dialog>
    </Card>
  )
}
