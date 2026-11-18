import { useParams } from 'react-router-dom'
import { runReport } from '../lib/api'
import { errorMessage, useAsync } from '../lib/useAsync'
import { EmptyState } from '../components/EmptyState'
import { MarkdownView } from '../components/MarkdownView'
import { PageHeader } from '../components/PageHeader'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { DownloadIcon } from '../components/icons'

function downloadMarkdown(runId: string, markdown: string) {
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `auditlens-report-${runId}-v.md`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function ReportPage() {
  const { runId = '' } = useParams()
  const reportState = useAsync(() => runReport(runId), [runId])
  const report = reportState.data?.report ?? null

  return (
    <>
      <PageHeader
        title="Rapport d'audit"
        description="Synthèse limitée aux résultats revus, avec annexes des preuves et méthodes. Le markdown source reste téléchargeable tel quel."
        actions={
          report ? (
            <Button variant="outline" onClick={() => downloadMarkdown(runId, report.markdown)}>
              <DownloadIcon className="h-4 w-4" /> Télécharger .md
            </Button>
          ) : null
        }
      />

      {reportState.loading ? (
        <p className="text-sm text-slate-500">Chargement du rapport…</p>
      ) : reportState.error ? (
        <EmptyState
          title="Rapport indisponible"
          description={reportState.error.includes('404')
            ? 'Aucun rapport généré pour ce run. Terminez un audit (et la revue des constats) pour en produire un.'
            : `Erreur : ${errorMessage(reportState.error)}`}
        />
      ) : report ? (
        <>
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle>
                  Rapport v{report.version} — généré {report.created_at}
                </CardTitle>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">{report.provider_id} / {report.model_id}</Badge>
                  <Badge tone="indigo">prompt {report.prompt_version}</Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500">
              <span>évalués : {report.assessed.join(', ') || '—'}</span>
              <span>partiels : {report.partial.join(', ') || '—'}</span>
              <span>non évalués : {report.not_assessed.join(', ') || '—'}</span>
              <span>constats inclus (acceptés) : {report.findings_included.length}</span>
              <span>exclus : {report.findings_excluded.length}</span>
            </CardContent>
          </Card>

          {report.limitations.length > 0 ? (
            <div className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              <p className="font-semibold">Limitations du rapport</p>
              <ul className="mt-1 list-disc pl-4">
                {report.limitations.map((l, i) => (
                  <li key={i}>{l}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle>Contenu</CardTitle>
            </CardHeader>
            <CardContent>
              <MarkdownView markdown={report.markdown} />
            </CardContent>
          </Card>
        </>
      ) : null}
    </>
  )
}
