import { useState } from 'react'
import {
  createSource,
  listRuleSets,
  listSources,
  testSource,
  uploadFileSource,
} from '../lib/api'
import type { SourceConnection, SourceType } from '../lib/types'
import { errorMessage, useAsync } from '../lib/useAsync'
import { EmptyState } from '../components/EmptyState'
import { ApiIcon, DatabaseIcon, FileIcon, GlobeIcon, PlusIcon } from '../components/icons'
import { PageHeader } from '../components/PageHeader'
import { SourceCard } from '../components/SourceCard'
import { Button } from '../components/ui/button'
import { Dialog } from '../components/ui/dialog'
import { Field, Input, Select } from '../components/ui/input'

const WIZARD_TYPES: { type: SourceType; label: string; description: string; icon: typeof DatabaseIcon }[] = [
  { type: 'file', label: 'Fichier', description: 'CSV, XLSX ou JSON (≤ 25 Mo) avec un contrat de données', icon: FileIcon },
  { type: 'odoo', label: 'Odoo', description: 'Instance locale : URL, base, utilisateur, mot de passe', icon: DatabaseIcon },
  { type: 'api', label: 'API', description: 'base_url + endpoints déclarés, OpenAPI optionnel', icon: ApiIcon },
  { type: 'web', label: 'Web', description: 'Parcours de contrôle pas-à-pas sur un site', icon: GlobeIcon },
]

type WebStepAction = 'goto' | 'click' | 'fill' | 'expect_text' | 'expect_selector' | 'wait'

interface WebStepDraft {
  action: WebStepAction
  url: string
  selector: string
  text: string
  ms: string
  expect_status: string
}

interface EndpointDraft {
  id: string
  method: string
  path: string
}

const EMPTY_STEP: WebStepDraft = {
  action: 'goto',
  url: '',
  selector: '',
  text: '',
  ms: '1000',
  expect_status: '',
}

function buildWebStep(step: WebStepDraft): Record<string, unknown> {
  const out: Record<string, unknown> = { action: step.action }
  if (step.action === 'goto') {
    if (step.url) out.url = step.url
    if (step.expect_status.trim()) out.expect_status = Number(step.expect_status)
  } else if (step.action === 'click' || step.action === 'fill' || step.action === 'expect_selector') {
    if (step.selector) out.selector = step.selector
    if (step.action === 'fill' && step.text) out.text = step.text
  } else if (step.action === 'expect_text') {
    if (step.text) out.text = step.text
  } else if (step.action === 'wait') {
    out.ms = Number(step.ms || 1000)
  }
  return out
}

function SourceWizard({ onClose, onCreated }: { onClose: () => void; onCreated: (msg: string) => void }) {
  const [wizardType, setWizardType] = useState<SourceType | null>(null)

  // Champs communs
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Fichier
  const [file, setFile] = useState<File | null>(null)
  const ruleSetsState = useAsync(listRuleSets, [])
  const [ruleSetId, setRuleSetId] = useState('')

  // Odoo
  const [odooUrl, setOdooUrl] = useState('')
  const [odooDb, setOdooDb] = useState('')
  const [odooUser, setOdooUser] = useState('')
  const [odooPassword, setOdooPassword] = useState('')

  // API
  const [apiBaseUrl, setApiBaseUrl] = useState('')
  const [apiOpenApiUrl, setApiOpenApiUrl] = useState('')
  const [apiToken, setApiToken] = useState('')
  const [endpoints, setEndpoints] = useState<EndpointDraft[]>([{ id: 'list', method: 'GET', path: '/' }])

  // Web
  const [webBaseUrl, setWebBaseUrl] = useState('')
  const [journeyName, setJourneyName] = useState('Parcours de contrôle')
  const [steps, setSteps] = useState<WebStepDraft[]>([{ ...EMPTY_STEP }])

  // Service local explicite (docs/08 : loopback interdit sauf configuration explicite)
  const [allowPrivate, setAllowPrivate] = useState(false)

  const ruleSets = ruleSetsState.data?.rule_sets ?? []

  function resetForm() {
    setError(null)
  }

  async function submit() {
    resetForm()
    if (!name.trim()) {
      setError('Le nom est requis.')
      return
    }
    setBusy(true)
    try {
      let created: SourceConnection
      if (wizardType === 'file') {
        if (!file) {
          setError('Sélectionnez un fichier CSV, XLSX ou JSON.')
          setBusy(false)
          return
        }
        const res = await uploadFileSource(name.trim(), ruleSetId, file)
        created = res.source
      } else if (wizardType === 'odoo') {
        if (!odooUrl.trim()) {
          setError('config.url est requis pour Odoo.')
          setBusy(false)
          return
        }
        const res = await createSource({
          name: name.trim(),
          type: 'odoo',
          config: { url: odooUrl.trim(), db: odooDb.trim(), username: odooUser.trim() },
          secrets: odooPassword ? { password: odooPassword } : undefined,
        })
        created = res.source
      } else if (wizardType === 'api') {
        if (!apiBaseUrl.trim()) {
          setError('config.base_url est requis pour une API.')
          setBusy(false)
          return
        }
        const cleaned = endpoints
          .filter((e) => e.id.trim() && e.path.trim())
          .map((e) => ({ id: e.id.trim(), method: e.method, path: e.path.trim() }))
        if (cleaned.length === 0) {
          setError('Déclarez au moins un endpoint {id, method, path}.')
          setBusy(false)
          return
        }
        const config: Record<string, unknown> = { base_url: apiBaseUrl.trim(), endpoints: cleaned }
        if (apiOpenApiUrl.trim()) config.openapi_url = apiOpenApiUrl.trim()
        if (allowPrivate) config.allow_private_host = true
        const res = await createSource({
          name: name.trim(),
          type: 'api',
          config,
          secrets: apiToken ? { auth: { type: 'bearer', token: apiToken } } : undefined,
        })
        created = res.source
      } else if (wizardType === 'web') {
        if (!webBaseUrl.trim()) {
          setError('config.base_url est requis pour une source Web.')
          setBusy(false)
          return
        }
        const builtSteps = steps
          .map(buildWebStep)
          .filter((s) => Object.keys(s).length > 1 || s.action === 'wait')
        if (builtSteps.length === 0) {
          setError('Le parcours doit contenir au moins une étape complète.')
          setBusy(false)
          return
        }
        const res = await createSource({
          name: name.trim(),
          type: 'web',
          config: {
            base_url: webBaseUrl.trim(),
            journeys: [{ id: 'journey_1', name: journeyName.trim() || 'Parcours', steps: builtSteps }],
            ...(allowPrivate ? { allow_private_host: true } : {}),
          },
        })
        created = res.source
      } else {
        return
      }

      // Le parcours nominal teste la connexion juste après la création (docs/02 étape 2).
      const test = await testSource(created.id)
      onCreated(
        test.ok
          ? `Source « ${created.name} » créée — connexion OK : ${test.message ?? 'ok'}`
          : `Source « ${created.name} » créée — test : ${test.error ?? test.message ?? 'échec'}`,
      )
      onClose()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      wide
      title="Ajouter une source"
      description="Les secrets ne sont jamais réaffichés ni stockés côté navigateur (docs/13)."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Annuler
          </Button>
          <Button onClick={submit} disabled={busy || wizardType === null}>
            {busy ? 'Création + test…' : 'Créer et tester'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {wizardType === null ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {WIZARD_TYPES.map((t) => (
              <button
                key={t.type}
                type="button"
                onClick={() => setWizardType(t.type)}
                className="flex items-start gap-3 rounded-xl border border-slate-200 p-4 text-left transition-colors duration-150 hover:border-indigo-300 hover:bg-indigo-50"
              >
                <t.icon className="mt-0.5 h-5 w-5 shrink-0 text-indigo-600" />
                <span>
                  <span className="block text-sm font-semibold text-slate-900">{t.label}</span>
                  <span className="block text-xs text-slate-500">{t.description}</span>
                </span>
              </button>
            ))}
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <Field label="Nom de la source" required htmlFor="src-name">
              <Input
                id="src-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="ex. ERP démo, API facturation…"
              />
            </Field>

            {wizardType === 'file' ? (
              <>
                <Field label="Fichier (CSV / XLSX / JSON, ≤ 25 Mo)" required htmlFor="src-file">
                  <Input
                    id="src-file"
                    type="file"
                    accept=".csv,.xlsx,.json"
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  />
                </Field>
                <Field
                  label="Contrat de données (rule_set)"
                  required
                  htmlFor="src-ruleset"
                  hint={ruleSets.find((r) => r.id === ruleSetId)?.contract_note}
                >
                  <Select id="src-ruleset" value={ruleSetId} onChange={(e) => setRuleSetId(e.target.value)}>
                    <option value="">— Choisir un rule_set —</option>
                    {ruleSets.map((rs) => (
                      <option key={rs.id} value={rs.id}>
                        {rs.name} ({rs.id})
                      </option>
                    ))}
                  </Select>
                </Field>
              </>
            ) : null}

            {wizardType === 'odoo' ? (
              <>
                <Field label="URL Odoo" required htmlFor="odoo-url">
                  <Input id="odoo-url" value={odooUrl} onChange={(e) => setOdooUrl(e.target.value)} placeholder="http://localhost:8069" />
                </Field>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Base de données" htmlFor="odoo-db">
                    <Input id="odoo-db" value={odooDb} onChange={(e) => setOdooDb(e.target.value)} />
                  </Field>
                  <Field label="Utilisateur" htmlFor="odoo-user">
                    <Input id="odoo-user" value={odooUser} onChange={(e) => setOdooUser(e.target.value)} autoComplete="off" />
                  </Field>
                </div>
                <Field label="Mot de passe" hint="Envoyé au backend une seule fois, jamais conservé par le frontend." htmlFor="odoo-pass">
                  <Input
                    id="odoo-pass"
                    type="password"
                    value={odooPassword}
                    onChange={(e) => setOdooPassword(e.target.value)}
                    autoComplete="new-password"
                  />
                </Field>
              </>
            ) : null}

            {wizardType === 'api' ? (
              <>
                <Field label="base_url" required htmlFor="api-url">
                  <Input id="api-url" value={apiBaseUrl} onChange={(e) => setApiBaseUrl(e.target.value)} placeholder="https://api.exemple.test" />
                </Field>
                <Field label="openapi_url (optionnel)" htmlFor="api-openapi">
                  <Input id="api-openapi" value={apiOpenApiUrl} onChange={(e) => setApiOpenApiUrl(e.target.value)} placeholder="https://…/openapi.json" />
                </Field>
                <Field label="Token Bearer (optionnel)" hint="Envoyé une seule fois au backend, jamais réaffiché." htmlFor="api-token">
                  <Input
                    id="api-token"
                    type="password"
                    value={apiToken}
                    onChange={(e) => setApiToken(e.target.value)}
                    autoComplete="new-password"
                  />
                </Field>

                <div className="flex flex-col gap-2">
                  <p className="text-xs font-medium text-slate-700">Endpoints déclarés</p>
                  {endpoints.map((ep, i) => (
                    <div key={i} className="grid grid-cols-[1fr_90px_1fr_auto] items-center gap-2">
                      <Input
                        value={ep.id}
                        onChange={(e) => setEndpoints((prev) => prev.map((p, j) => (j === i ? { ...p, id: e.target.value } : p)))}
                        placeholder="id"
                        aria-label={`Endpoint ${i + 1} — id`}
                      />
                      <Select
                        value={ep.method}
                        onChange={(e) => setEndpoints((prev) => prev.map((p, j) => (j === i ? { ...p, method: e.target.value } : p)))}
                        aria-label={`Endpoint ${i + 1} — méthode`}
                      >
                        {['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((m) => (
                          <option key={m}>{m}</option>
                        ))}
                      </Select>
                      <Input
                        value={ep.path}
                        onChange={(e) => setEndpoints((prev) => prev.map((p, j) => (j === i ? { ...p, path: e.target.value } : p)))}
                        placeholder="/orders"
                        aria-label={`Endpoint ${i + 1} — chemin`}
                      />
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setEndpoints((prev) => prev.filter((_, j) => j !== i))}
                        aria-label={`Supprimer l'endpoint ${i + 1}`}
                      >
                        ✕
                      </Button>
                    </div>
                  ))}
                  <div>
                    <Button size="sm" variant="outline" onClick={() => setEndpoints((prev) => [...prev, { id: '', method: 'GET', path: '' }])}>
                      <PlusIcon className="h-3.5 w-3.5" /> Ajouter un endpoint
                    </Button>
                  </div>
                  <label className="flex items-start gap-2 text-xs text-slate-600">
                    <input
                      type="checkbox"
                      checked={allowPrivate}
                      onChange={(e) => setAllowPrivate(e.target.checked)}
                      className="mt-0.5"
                    />
                    <span>
                      Service local : autoriser loopback / réseau privé (loopback est refusé par le garde SSRF
                      sauf configuration explicite — docs/08).
                    </span>
                  </label>
                </div>
              </>
            ) : null}

            {wizardType === 'web' ? (
              <>
                <Field label="base_url du site" required htmlFor="web-url">
                  <Input id="web-url" value={webBaseUrl} onChange={(e) => setWebBaseUrl(e.target.value)} placeholder="http://localhost:3000" />
                </Field>
                <Field label="Nom du parcours" htmlFor="web-journey">
                  <Input id="web-journey" value={journeyName} onChange={(e) => setJourneyName(e.target.value)} />
                </Field>

                <div className="flex flex-col gap-2">
                  <p className="text-xs font-medium text-slate-700">Étapes du parcours (pas-à-pas)</p>
                  {steps.map((step, i) => (
                    <div key={i} className="rounded-lg border border-slate-200 p-3">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-slate-600">Étape {i + 1}</span>
                        <div className="flex items-center gap-2">
                          <Select
                            value={step.action}
                            onChange={(e) =>
                              setSteps((prev) =>
                                prev.map((p, j) => (j === i ? { ...p, action: e.target.value as WebStepAction } : p)),
                              )
                            }
                            aria-label={`Étape ${i + 1} — action`}
                            className="w-auto"
                          >
                            <option value="goto">goto (aller à l'URL)</option>
                            <option value="click">click (cliquer)</option>
                            <option value="fill">fill (remplir)</option>
                            <option value="expect_text">expect_text (texte attendu)</option>
                            <option value="expect_selector">expect_selector (sélecteur attendu)</option>
                            <option value="wait">wait (attendre)</option>
                          </Select>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setSteps((prev) => prev.filter((_, j) => j !== i))}
                            aria-label={`Supprimer l'étape ${i + 1}`}
                          >
                            ✕
                          </Button>
                        </div>
                      </div>
                      <div className="grid gap-2 sm:grid-cols-2">
                        {step.action === 'goto' ? (
                          <>
                            <Field label="URL">
                              <Input
                                value={step.url}
                                onChange={(e) => setSteps((prev) => prev.map((p, j) => (j === i ? { ...p, url: e.target.value } : p)))}
                                placeholder="/ ou https://…"
                              />
                            </Field>
                            <Field label="Statut HTTP attendu (optionnel)">
                              <Input
                                value={step.expect_status}
                                onChange={(e) => setSteps((prev) => prev.map((p, j) => (j === i ? { ...p, expect_status: e.target.value } : p)))}
                                placeholder="200"
                                inputMode="numeric"
                              />
                            </Field>
                          </>
                        ) : null}
                        {step.action === 'click' || step.action === 'fill' || step.action === 'expect_selector' ? (
                          <Field label="Sélecteur CSS">
                            <Input
                              value={step.selector}
                              onChange={(e) => setSteps((prev) => prev.map((p, j) => (j === i ? { ...p, selector: e.target.value } : p)))}
                              placeholder="#login"
                            />
                          </Field>
                        ) : null}
                        {step.action === 'fill' || step.action === 'expect_text' ? (
                          <Field label="Texte">
                            <Input
                              value={step.text}
                              onChange={(e) => setSteps((prev) => prev.map((p, j) => (j === i ? { ...p, text: e.target.value } : p)))}
                            />
                          </Field>
                        ) : null}
                        {step.action === 'wait' ? (
                          <Field label="Durée (ms)">
                            <Input
                              value={step.ms}
                              onChange={(e) => setSteps((prev) => prev.map((p, j) => (j === i ? { ...p, ms: e.target.value } : p)))}
                              inputMode="numeric"
                            />
                          </Field>
                        ) : null}
                      </div>
                    </div>
                  ))}
                  <div>
                    <Button size="sm" variant="outline" onClick={() => setSteps((prev) => [...prev, { ...EMPTY_STEP }])}>
                      <PlusIcon className="h-3.5 w-3.5" /> Ajouter une étape
                    </Button>
                  </div>
                  <label className="flex items-start gap-2 text-xs text-slate-600">
                    <input
                      type="checkbox"
                      checked={allowPrivate}
                      onChange={(e) => setAllowPrivate(e.target.checked)}
                      className="mt-0.5"
                    />
                    <span>
                      Service local : autoriser loopback / réseau privé (requis pour une app de test sur
                      localhost — garde SSRF docs/08).
                    </span>
                  </label>
                </div>
              </>
            ) : null}

            <div>
              <Button size="sm" variant="ghost" onClick={() => { setWizardType(null); resetForm() }}>
                ← Changer de type
              </Button>
            </div>
          </div>
        )}

        {ruleSetsState.error ? (
          <p className="text-xs text-amber-700">Catalogue rule_sets indisponible : {ruleSetsState.error}</p>
        ) : null}
        {error ? <p className="text-xs text-red-600">{error}</p> : null}
      </div>
    </Dialog>
  )
}

export function ConnectionsPage() {
  const sourcesState = useAsync(listSources, [])
  const [wizardOpen, setWizardOpen] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const sources = sourcesState.data?.sources ?? []

  return (
    <>
      <PageHeader
        title="Connections"
        description="Sources disponibles pour les missions. Le statut reflète le dernier test réel effectué par le backend."
        actions={
          <Button onClick={() => setWizardOpen(true)}>
            <PlusIcon className="h-4 w-4" /> Ajouter une source
          </Button>
        }
      />

      {notice ? (
        <div className="rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-800">
          {notice}
        </div>
      ) : null}

      {sourcesState.error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">
          Erreur : {sourcesState.error}
        </div>
      ) : null}

      {sourcesState.loading ? (
        <p className="text-sm text-slate-500">Chargement…</p>
      ) : sources.length === 0 ? (
        <EmptyState
          title="Aucune source"
          description="Ajoutez votre première source : Odoo, API, site web ou fichier CSV/XLSX/JSON."
          action={<Button onClick={() => setWizardOpen(true)}>Ajouter une source</Button>}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {sources.map((source) => (
            <SourceCard
              key={source.id}
              source={source}
              onChanged={() => sourcesState.reload()}
            />
          ))}
        </div>
      )}

      {wizardOpen ? (
        <SourceWizard
          onClose={() => setWizardOpen(false)}
          onCreated={(msg) => {
            setNotice(msg)
            sourcesState.reload()
          }}
        />
      ) : null}
    </>
  )
}
