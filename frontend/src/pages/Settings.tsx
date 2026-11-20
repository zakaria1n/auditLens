import { useEffect, useState } from 'react'
import { getLLMConfig, listOpencodeFreeModels, listProviderModels, setLLMConfig, testLLMConfig } from '../lib/api'
import type { OpencodeFreeModel, ProviderModel } from '../lib/api'
import { errorMessage, useAsync } from '../lib/useAsync'
import { PageHeader } from '../components/PageHeader'
import { AlertIcon, ShieldIcon } from '../components/icons'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Field, Input, Select } from '../components/ui/input'

export function SettingsPage() {
  const configState = useAsync(getLLMConfig, [])
  const serverConfig = configState.data

  const [provider, setProvider] = useState('mock')
  const [model, setModel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [saveMsg, setSaveMsg] = useState<string | null>(null)
  const [saveErr, setSaveErr] = useState<string | null>(null)
  const [testMsg, setTestMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState<'save' | 'test' | null>(null)
  const [ocModels, setOcModels] = useState<OpencodeFreeModel[] | null>(null)
  const [ocError, setOcError] = useState<string | null>(null)
  const [curated, setCurated] = useState<ProviderModel[] | null>(null)
  const [curatedNote, setCuratedNote] = useState<string>('')
  const [modelSource, setModelSource] = useState<'live' | 'curated' | 'none' | null>(null)
  const [modelWarning, setModelWarning] = useState<string | null>(null)
  const [forceCustom, setForceCustom] = useState(false)

  // Pré-remplissage depuis la config réelle du backend (jamais la clé).
  useEffect(() => {
    if (!serverConfig) return
    setProvider(serverConfig.provider)
    setModel(serverConfig.model ?? '')
    setBaseUrl(serverConfig.base_url ?? '')
    setApiKey('') // la clé n'est jamais réaffichée — champ vide par défaut
  }, [serverConfig])

  // provider opencode-cli : catalogue LIVE des modèles free (aucune clé requise)
  useEffect(() => {
    if (provider !== 'opencode-cli' && provider !== 'opencode') return
    setOcModels(null)
    setOcError(null)
    let cancelled = false
    listOpencodeFreeModels()
      .then((res) => {
        if (cancelled) return
        if (res.ok && res.models.length > 0) {
          setOcModels(res.models)
          // si le modèle courant n'existe pas dans le catalogue : bascule sur le modèle validé
          setModel((cur) => res.models.some((m) => m.id === cur) ? cur : '')
        } else {
          setOcError(res.error ?? 'catalogue vide')
        }
      })
      .catch((err) => {
        if (!cancelled) setOcError(errorMessage(err))
      })
    return () => {
      cancelled = true
    }
  }, [provider])

  // base_url est propre à « compatible » : NE JAMAIS la transmettre à un autre
  // provider (fuite de l'URL saisie précédemment -> endpoint faux -> 404, bug vu en test réel)
  useEffect(() => {
    setBaseUrl('')
    setApiKey('')
  }, [provider])

  // catalogue des modèles : LIVE (clé saisie ou runtime) sinon suggestions
  // statiques vérifiées — recharge avec 600 ms de debounce quand la clé change
  useEffect(() => {
    setCurated(null)
    setCuratedNote('')
    setModelSource(null)
    setModelWarning(null)
    setForceCustom(false)
    if (!['openai', 'anthropic', 'deepseek', 'gemini'].includes(provider)) return
    let cancelled = false
    const timer = window.setTimeout(() => {
      listProviderModels(provider, apiKey.trim() || undefined, baseUrl.trim() || undefined)
        .then((res) => {
          if (cancelled) return
          setCurated(res.models)
          setCuratedNote(res.note)
          setModelSource(res.source as 'live' | 'curated' | 'none')
          setModelWarning(res.warning ?? null)
        })
        .catch(() => {
          if (!cancelled) setCurated([])
        })
    }, apiKey ? 600 : 0)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [provider, apiKey, baseUrl])

  const keyConfigured = provider === serverConfig?.provider && (serverConfig?.key_configured ?? false)
  const providers = serverConfig?.providers_available ?? ['mock', 'opencode', 'opencode-cli', 'openai', 'gemini', 'anthropic', 'deepseek', 'compatible']
  const isOpencodeCli = provider === 'opencode-cli'
  const isOpencode = provider === 'opencode' || isOpencodeCli
  // mode saisie manuelle : choix explicite, ou modèle courant absent des suggestions
  const curatedLoaded = curated != null && curated.length > 0
  const isCustomModel = curatedLoaded && (forceCustom || (model !== '' && !curated!.some((m) => m.id === model)))

  async function handleSave() {
    setBusy('save')
    setSaveMsg(null)
    setSaveErr(null)
    try {
      const res = await setLLMConfig({
        provider,
        model: model.trim(),
        base_url: provider === 'opencode' ? null : baseUrl.trim() || null,
        api_key: apiKey || undefined, // non envoyé si vide : la clé mémorisée reste en place
      })
      setSaveMsg(`Configuration enregistrée en mémoire backend : ${res.provider} / ${res.model || '—'}`)
      configState.reload()
    } catch (err) {
      setSaveErr(errorMessage(err))
    } finally {
      setApiKey('') // on ne conserve jamais la saisie côté navigateur après usage
      setBusy(null)
    }
  }

  async function handleTest() {
    setBusy('test')
    setTestMsg(null)
    try {
      const body = { provider, model: model.trim(), base_url: provider === 'opencode' ? null : baseUrl.trim() || null, api_key: apiKey || undefined }
      const res = await testLLMConfig(body)
      setTestMsg({
        ok: res.ok,
        text: res.ok ? (res.message ?? 'connexion réussie') : (res.error ?? 'échec du test'),
      })
    } catch (err) {
      setTestMsg({ ok: false, text: errorMessage(err) })
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <PageHeader
        title="Settings LLM (BYOK)"
        description="Bring Your Own Key : la clé reste en mémoire backend, jamais persistée, jamais loggée ni renvoyée au frontend."
      />

      <div className="flex items-start gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <AlertIcon className="mt-0.5 h-5 w-5 shrink-0" />
        <div>
          <p className="font-semibold">Vie privée</p>
          <p>
            Les contenus audités (extraits de données, échantillons) transitent par le provider
            choisi. N'utilisez une clé réelle que pour des données que vous êtes autorisé à
            envoyer à ce fournisseur. Le provider <strong>mock</strong> n'envoie rien vers
            l'extérieur.
          </p>
        </div>
      </div>

      {configState.error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">
          Erreur : {configState.error}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldIcon className="h-4 w-4 text-brand-600" />
            Configuration active {serverConfig ? `— source : ${serverConfig.source}` : ''}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Provider" required htmlFor="llm-provider">
              <Select id="llm-provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
                {providers.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              label="Modèle"
              htmlFor="llm-model"
              hint={
                isOpencode
                  ? 'Catalogue OpenCode : modèles gratuits et Big Pickle ; disponibilité selon le fournisseur.'
                  : 'ex. gpt-4o-mini, gemini-2.0-flash, claude-sonnet-4-5, deepseek-chat…'
              }
            >
              {isOpencode ? (
                ocError ? (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                    Catalogue indisponible : {ocError}. Vérifiez la connexion réseau puis réessayez.
                  </div>
                ) : ocModels == null ? (
                  <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-400">
                    Chargement du catalogue des modèles free…
                  </div>
                ) : (
                  <Select id="llm-model" value={model} onChange={(e) => setModel(e.target.value)}>
                    <option value="">— Choisir un modèle —</option>
                    {ocModels.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name} — {m.id}
                      </option>
                    ))}
                  </Select>
                )
              ) : curated && curated.length > 0 ? (
                <div className="flex flex-col gap-1.5">
                  <Select
                    id="llm-model"
                    value={isCustomModel ? '__custom__' : model}
                    onChange={(e) => {
                      if (e.target.value === '__custom__') {
                        setForceCustom(true)
                        setModel('')
                      } else {
                        setForceCustom(false)
                        setModel(e.target.value)
                      }
                    }}
                  >
                    {isCustomModel && model && <option value={model}>{model} (actif)</option>}
                    {curated!.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                    <option value="__custom__">Autre modèle (saisie manuelle)…</option>
                  </Select>
                  {isCustomModel ? (
                    <Input
                      id="llm-model-custom"
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      placeholder="Identifiant exact du modèle (supportant les tool calls)…"
                      aria-label="Identifiant du modèle personnalisé"
                    />
                  ) : null}
                  <p className="text-[11px] leading-snug text-slate-400">
                    <span className={`mr-1.5 rounded px-1.5 py-0.5 font-medium ${modelSource === 'live' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                      {modelSource === 'live' ? 'liste live (votre clé)' : modelSource === 'curated' ? 'suggestions' : '—'}
                    </span>
                    {modelWarning ? modelWarning : curatedNote}
                  </p>
                </div>
              ) : provider === 'compatible' ? (
                <div className="flex flex-col gap-1.5">
                  <Input id="llm-model" value={model} onChange={(e) => setModel(e.target.value)} placeholder="ex. glm-5.3-flash, llama3.1, mon-modele…" />
                  <p className="text-[11px] leading-snug text-slate-400">
                    Endpoint générique : la liste dépend du serveur (base_url) — saisissez l'identifiant exact supportant les tool calls.
                  </p>
                </div>
              ) : (
                <Input id="llm-model" value={model} onChange={(e) => setModel(e.target.value)} />
              )}
            </Field>
            {provider === 'opencode' && <p className="sm:col-span-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">L’API OpenCode Console hors OpenCode ne donne pas accès aux modèles chat gratuits. Utilisez un modèle autorisé avec une clé valide ; les modèles gratuits restent disponibles dans OpenCode selon le catalogue et les conditions du fournisseur.</p>}
            {!isOpencodeCli && (
              <>
                {provider === 'compatible' && <Field label="base_url" htmlFor="llm-base">
                  <Input id="llm-base" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://…/v1" />
                </Field>}
                <Field
                  label="Clé API"
                  htmlFor="llm-key"
                  hint={
                    keyConfigured
                      ? 'Une clé est déjà configurée en mémoire backend. Le champ reste vide : la clé n\'est jamais réaffichée.'
                      : 'Aucune clé configurée. Obligatoire pour tous les providers hors mock et opencode-cli.'
                  }
                >
                  <Input
                    id="llm-key"
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    autoComplete="new-password"
                    placeholder="••••••••••••"
                  />
                </Field>
              </>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={handleSave} disabled={busy !== null || (isOpencode && (!model || ocModels == null))}>
              {busy === 'save' ? 'Enregistrement…' : 'Enregistrer (mémoire backend)'}
            </Button>
            <Button variant="outline" onClick={handleTest} disabled={busy !== null || (isOpencode && (!model || ocModels == null))}>
              {busy === 'test' ? 'Test en cours…' : apiKey ? 'Tester avec cette clé' : 'Tester le modèle sélectionné'}
            </Button>
          </div>

          {saveMsg ? <p className="text-xs text-emerald-700">{saveMsg}</p> : null}
          {saveErr ? <p className="text-xs text-red-600">{saveErr}</p> : null}
          {testMsg ? (
            <div
              className={`rounded-lg border px-3.5 py-2.5 text-xs ${
                testMsg.ok ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-red-200 bg-red-50 text-red-700'
              }`}
            >
              Test : {testMsg.ok ? 'OK' : 'ÉCHEC'} — {testMsg.text}
            </div>
          ) : null}

          <p className="text-xs text-slate-400">{serverConfig?.note}</p>
        </CardContent>
      </Card>
    </>
  )
}
