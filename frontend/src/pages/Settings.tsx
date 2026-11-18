import { useEffect, useState } from 'react'
import { getLLMConfig, listOpencodeFreeModels, setLLMConfig, testLLMConfig } from '../lib/api'
import type { OpencodeFreeModel } from '../lib/api'
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
    if (provider !== 'opencode-cli') return
    setOcModels(null)
    setOcError(null)
    let cancelled = false
    listOpencodeFreeModels()
      .then((res) => {
        if (cancelled) return
        if (res.ok && res.models.length > 0) {
          setOcModels(res.models)
          // si le modèle courant n'existe pas dans le catalogue : bascule sur le modèle validé
          setModel((cur) =>
            res.models.some((m) => m.id === cur) ? cur : 'deepseek-v4.1-flash-free',
          )
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

  const keyConfigured = serverConfig?.key_configured ?? false
  const providers = serverConfig?.providers_available ?? ['mock', 'opencode', 'opencode-cli', 'openai', 'gemini', 'anthropic', 'deepseek', 'compatible']
  const isOpencodeCli = provider === 'opencode-cli'

  async function handleSave() {
    setBusy('save')
    setSaveMsg(null)
    setSaveErr(null)
    try {
      const res = await setLLMConfig({
        provider,
        model: model.trim(),
        base_url: baseUrl.trim() || null,
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
      // Si aucune nouvelle clé n'est saisie, on teste la configuration en mémoire du backend.
      const body = apiKey ? { provider, model: model.trim(), base_url: baseUrl.trim() || null, api_key: apiKey } : undefined
      const res = await testLLMConfig(body)
      setTestMsg({
        ok: res.ok,
        text: res.ok ? (res.message ?? 'connexion réussie') : (res.error ?? 'échec du test'),
      })
    } catch (err) {
      setTestMsg({ ok: false, text: errorMessage(err) })
    } finally {
      setApiKey('')
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
            <ShieldIcon className="h-4 w-4 text-indigo-600" />
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
                isOpencodeCli
                  ? 'Modèles FREE OpenCode (catalogue live, tool-calls supportés)'
                  : 'ex. gpt-4o-mini, gemini-2.0-flash, claude-sonnet-4-5, deepseek-chat…'
              }
            >
              {isOpencodeCli ? (
                ocError ? (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                    Catalogue indisponible : {ocError}. Le CLI OpenCode doit être installé et
                    l'accès réseau ouvert.
                  </div>
                ) : ocModels == null ? (
                  <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-400">
                    Chargement du catalogue des modèles free…
                  </div>
                ) : (
                  <Select id="llm-model" value={model} onChange={(e) => setModel(e.target.value)}>
                    {ocModels.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name} — {m.id}
                      </option>
                    ))}
                  </Select>
                )
              ) : (
                <Input id="llm-model" value={model} onChange={(e) => setModel(e.target.value)} />
              )}
            </Field>
            {!isOpencodeCli && (
              <>
                <Field label="base_url (compatible uniquement)" htmlFor="llm-base">
                  <Input id="llm-base" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://…/v1" />
                </Field>
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
            <Button onClick={handleSave} disabled={busy !== null}>
              {busy === 'save' ? 'Enregistrement…' : 'Enregistrer (mémoire backend)'}
            </Button>
            <Button variant="outline" onClick={handleTest} disabled={busy !== null}>
              {busy === 'test' ? 'Test en cours…' : apiKey ? 'Tester avec cette clé' : 'Tester la configuration enregistrée'}
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
