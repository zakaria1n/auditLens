import type { AuditPlan } from '../lib/types'
import { toolLabel } from '../lib/tools'
import { AlertIcon, CheckIcon } from './icons'
import { Badge } from './ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'

export interface PlanStepsProps {
  plan: AuditPlan
  approved: boolean
}

/**
 * Étapes du plan IA proposé, avec mise en évidence explicite des étapes
 * nécessitant l'approbation humaine avant exécution (docs/02 étape 4).
 */
export function PlanSteps({ plan, approved }: PlanStepsProps) {
  const approvalNeeded = plan.steps.some((s) => s.requires_approval)
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle>Plan proposé — {plan.steps.length} étapes</CardTitle>
            <div className="flex items-center gap-2">
              {approvalNeeded ? (
                <Badge tone={approved ? 'green' : 'amber'}>
                  {approved ? <CheckIcon className="h-3 w-3" /> : null}
                  {approved ? 'Plan approuvé' : 'Approbation humaine requise'}
                </Badge>
              ) : (
                <Badge tone="green">Aucune étape sensible</Badge>
              )}
              <Badge tone="neutral">
                {plan.provider_id} / {plan.model_id}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-2.5">
          {plan.steps.map((step, i) => (
            <div
              key={step.id}
              className="flex flex-col gap-1 rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-600 text-xs font-semibold text-white">
                  {i + 1}
                </span>
                <span className="text-sm font-medium text-slate-900">{toolLabel(step.tool)}</span>
                <code className="rounded bg-white px-1.5 py-0.5 font-mono text-xs text-slate-500">
                  {step.tool}
                </code>
                {step.source_id ? (
                  <Badge tone="neutral">source: {step.source_id}</Badge>
                ) : null}
                {step.requires_approval ? (
                  <Badge tone={approved ? 'green' : 'amber'} pulsing={!approved}>
                    {approved ? 'Approuvé' : 'Approbation requise'}
                  </Badge>
                ) : null}
              </div>
              {step.rationale ? (
                <p className="pl-7 text-xs text-slate-600">Rationale : {step.rationale}</p>
              ) : null}
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        {plan.risks.length > 0 ? (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-1.5">
                <AlertIcon className="h-4 w-4 text-amber-600" /> Risques identifiés
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="list-disc space-y-1 pl-4">
                {plan.risks.map((risk, i) => (
                  <li key={i} className="text-xs text-slate-600">
                    {risk}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        ) : null}
        {plan.evidence_expected.length > 0 ? (
          <Card>
            <CardHeader>
              <CardTitle>Preuves attendues</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-1.5">
              {plan.evidence_expected.map((ev, i) => (
                <Badge key={i} tone="indigo">
                  {ev}
                </Badge>
              ))}
            </CardContent>
          </Card>
        ) : null}
      </div>
    </div>
  )
}
