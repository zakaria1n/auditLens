import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createMission, listControls, listSources } from '../lib/api'
import type { Control } from '../lib/types'
import { errorMessage, useAsync } from '../lib/useAsync'
import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Field, Input } from '../components/ui/input'

function ControlCheckbox({
  control,
  checked,
  onToggle,
}: {
  control: Control
  checked: boolean
  onToggle: () => void
}) {
  return (
    <label
      className={`flex cursor-pointer flex-col gap-1.5 rounded-lg border px-4 py-3 transition-colors duration-150 ${
        checked ? 'border-brand-300 bg-brand-50' : 'border-slate-200 bg-white hover:bg-slate-50'
      }`}
    >
      <span className="flex items-center gap-2.5">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-200"
        />
        <span className="text-sm font-semibold text-slate-900">{control.id}</span>
        <span className="text-sm text-slate-600">{control.title}</span>
        <span className="ml-auto text-xs text-slate-400">v{control.version}</span>
      </span>
      <span className="pl-6.5 text-xs text-slate-500">
        Critère : {control.criterion}
      </span>
      <span className="pl-6.5 text-xs text-slate-400">
        Types de sources : {control.source_types.join(', ')} · preuves attendues :{' '}
        {control.expected_evidence.join(', ')}
      </span>
    </label>
  )
}

export function MissionNewPage() {
  const navigate = useNavigate()
  const sourcesState = useAsync(listSources, [])
  const controlsState = useAsync(listControls, [])

  const [title, setTitle] = useState('')
  const [objective, setObjective] = useState('')
  const [sourceIds, setSourceIds] = useState<string[]>([])
  const [controlIds, setControlIds] = useState<string[]>([])
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [maxToolCalls, setMaxToolCalls] = useState(12)
  const [maxSeconds, setMaxSeconds] = useState(180)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const sources = sourcesState.data?.sources ?? []
  const controls = controlsState.data?.controls ?? []

  function toggle(list: string[], setList: (v: string[]) => void, id: string) {
    setList(list.includes(id) ? list.filter((x) => x !== id) : [...list, id])
  }

  async function submit() {
    setError(null)
    if (!title.trim() || !objective.trim()) {
      setError('Titre et objectif sont requis.')
      return
    }
    if (sourceIds.length === 0) {
      setError('Sélectionnez au moins une source.')
      return
    }
    if (controlIds.length === 0) {
      setError('Sélectionnez au moins un contrôle du catalogue.')
      return
    }
    setBusy(true)
    try {
      const res = await createMission({
        title: title.trim(),
        objective: objective.trim(),
        source_ids: sourceIds,
        control_ids: controlIds,
        time_range: { from: fromDate || null, to: toDate || null },
        limits: { max_tool_calls: maxToolCalls, max_seconds: maxSeconds },
      })
      navigate(`/missions/${res.mission.id}`)
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Nouvelle mission"
        description="Définissez l'objectif d'audit, le périmètre de sources, les contrôles du catalogue et les limites d'exécution."
        actions={<Button onClick={submit} disabled={busy}>{busy ? 'Création…' : 'Créer la mission'}</Button>}
      />

      <div className="grid items-start gap-6 lg:grid-cols-[1fr_1.2fr]">
        <Card>
          <CardHeader>
            <CardTitle>Objectif</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <Field label="Titre de la mission" required htmlFor="m-title">
              <Input
                id="m-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="ex. Audit de la facturation"
              />
            </Field>
            <Field label="Objectif d'audit" required htmlFor="m-objective" hint="Question d'audit précise : ce que la mission doit établir ou infirmer.">
              <Input
                id="m-objective"
                value={objective}
                onChange={(e) => setObjective(e.target.value)}
                placeholder="ex. Vérifier que chaque facture émise a une commande associée"
              />
            </Field>

            <Field label="Période (optionnelle)">
              <div className="grid grid-cols-2 gap-2">
                <Input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} aria-label="Début de période" />
                <Input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} aria-label="Fin de période" />
              </div>
            </Field>

            <Field label="Limites d'exécution" hint="Arrêt explicite quand une limite est atteinte (docs/04).">
              <div className="grid grid-cols-2 gap-2">
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-slate-500">max_tool_calls</span>
                  <Input
                    type="number"
                    min={1}
                    max={100}
                    value={maxToolCalls}
                    onChange={(e) => setMaxToolCalls(Number(e.target.value))}
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-slate-500">max_seconds</span>
                  <Input
                    type="number"
                    min={10}
                    max={3600}
                    value={maxSeconds}
                    onChange={(e) => setMaxSeconds(Number(e.target.value))}
                  />
                </label>
              </div>
            </Field>
          </CardContent>
        </Card>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Sources ({sourceIds.length} sélectionnée(s))</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {sourcesState.loading ? (
                <p className="text-sm text-slate-500">Chargement…</p>
              ) : sources.length === 0 ? (
                <p className="text-sm text-slate-500">
                  Aucune source — <span className="text-brand-600">créez-en une dans Connections</span> d'abord.
                </p>
              ) : (
                sources.map((source) => {
                  const checked = sourceIds.includes(source.id)
                  return (
                    <label
                      key={source.id}
                      className={`flex cursor-pointer items-center gap-2.5 rounded-lg border px-3.5 py-2.5 transition-colors duration-150 ${
                        checked ? 'border-brand-300 bg-brand-50' : 'border-slate-200 hover:bg-slate-50'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(sourceIds, setSourceIds, source.id)}
                        className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-200"
                      />
                      <span className="text-sm font-medium text-slate-900">{source.name}</span>
                      <span className="ml-auto text-xs text-slate-400">
                        {source.type} · {source.status}
                      </span>
                    </label>
                  )
                })
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Contrôles du catalogue ({controlIds.length} sélectionné(s))</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {controlsState.loading ? (
                <p className="text-sm text-slate-500">Chargement du catalogue…</p>
              ) : controlsState.error ? (
                <p className="text-sm text-red-600">Catalogue indisponible : {controlsState.error}</p>
              ) : (
                controls.map((control) => (
                  <ControlCheckbox
                    key={control.id}
                    control={control}
                    checked={controlIds.includes(control.id)}
                    onToggle={() => toggle(controlIds, setControlIds, control.id)}
                  />
                ))
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {error ? (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      ) : null}
    </>
  )
}
