import { Link } from 'react-router-dom'
import type { Assessment } from '../lib/types'
import { StatusBadge } from './StatusBadge'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'

export interface AssessmentCardProps {
  assessment: Assessment
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

/**
 * Résultat d'assessment : statut exact affiché en toutes lettres.
 * `insufficient_evidence` est explicite et visible — jamais converti en PASS.
 */
export function AssessmentCard({ assessment }: AssessmentCardProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>
            {assessment.control_id}
            <span className="ml-2 font-normal text-slate-400">
              critère v{assessment.criterion_version}
            </span>
          </CardTitle>
          <StatusBadge value={assessment.result} />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {assessment.method ? (
          <p className="text-xs text-slate-500">Méthode : {assessment.method}</p>
        ) : null}
        <BulletList title="Observations" items={assessment.observations} />
        <BulletList title="Limitations" items={assessment.limitations} />
        {assessment.evidence_refs.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-slate-500">Preuves :</span>
            {assessment.evidence_refs.map((evId) => (
              <Link
                key={evId}
                to={`/evidence?run_id=${assessment.run_id}&focus=${evId}`}
                className="rounded-md border border-indigo-200 bg-indigo-50 px-2 py-0.5 font-mono text-xs text-indigo-700 transition-colors duration-150 hover:bg-indigo-100"
              >
                {evId}
              </Link>
            ))}
          </div>
        ) : (
          <p className="text-xs text-amber-700">
            Aucune preuve rattachée — le statut reflète cette absence.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
