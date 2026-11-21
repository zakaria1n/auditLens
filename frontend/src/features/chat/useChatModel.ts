import { useCallback, useEffect, useState } from 'react'
import { getLLMConfig, listOpencodeFreeModels, listProviderModels, selectLLMModel } from '../../lib/api'

type ModelOption = { id: string; label: string }

export function useChatModel(route: string) {
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [options, setOptions] = useState<ModelOption[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    async function load() {
      setLoading(true); setError('')
      try {
        const config = await getLLMConfig()
        if (!active) return
        setProvider(config.provider); setModel(config.model)
        let models: ModelOption[] = config.model ? [{ id: config.model, label: `${config.model} (actif · non vérifié)` }] : []
        if (config.provider === 'opencode' || config.provider === 'opencode-cli') {
          const catalogue = await listOpencodeFreeModels(config.provider === 'opencode-cli' ? 'free' : 'api')
          if (!active) return
          if (!catalogue.ok) throw new Error(catalogue.error || 'Catalogue indisponible')
          models = catalogue.models.map(item => ({ id: item.id, label: item.name }))
          if (config.model && !models.some(item => item.id === config.model)) models.unshift({ id: config.model, label: `${config.model} (actif · non vérifié)` })
        } else if (['openai', 'anthropic', 'deepseek', 'gemini'].includes(config.provider)) {
          // suggestions vérifiées (statiques) — le choix reste libre côté Réglages IA
          const curated = await listProviderModels(config.provider)
          if (!active) return
          if (curated.ok && curated.models.length > 0) {
            models = curated.models.map(item => ({ id: item.id, label: item.name }))
            if (config.model && !models.some(item => item.id === config.model)) {
              models.unshift({ id: config.model, label: `${config.model} (actif · non vérifié)` })
            }
          }
        }
        if (active) setOptions(models)
      } catch (err) {
        if (active) { setOptions([]); setError(err instanceof Error ? err.message : 'Chargement impossible') }
      } finally { if (active) setLoading(false) }
    }
    void load()
    return () => { active = false }
  }, [route])

  const changeModel = useCallback(async (next: string) => {
    if (!next || next === model || saving) return
    setSaving(true); setError('')
    try {
      const confirmed = await selectLLMModel(provider, next)
      setModel(confirmed.model)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Modification impossible')
    } finally { setSaving(false) }
  }, [model, provider, saving])

  return { provider, model, options, loading, saving, error, changeModel }
}
export type ChatModel = ReturnType<typeof useChatModel>
