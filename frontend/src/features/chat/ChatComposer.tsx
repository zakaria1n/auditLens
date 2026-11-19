import { useEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { uploadFileSource } from '../../lib/api'
import { Link } from 'react-router-dom'
import type { ChatModel } from './useChatModel'

type RecognitionResult = { isFinal: boolean; 0: { transcript: string } }
type RecognitionEvent = Event & { resultIndex: number; results: ArrayLike<RecognitionResult> }
type Recognition = { lang: string; interimResults: boolean; continuous: boolean; onresult: ((event: RecognitionEvent) => void) | null; onerror: ((event: Event & { error: string }) => void) | null; onend: (() => void) | null; start: () => void; stop: () => void; abort: () => void }
type RecognitionConstructor = new () => Recognition

export function ChatComposer({ threadId, running, onSend, onCancel, drafts, setDrafts, chatModel }: { chatModel: ChatModel; threadId: string | null; running: boolean; onSend: (text: string) => Promise<void>; onCancel: () => void; drafts: Record<string, string>; setDrafts: Dispatch<SetStateAction<Record<string, string>>> }) {
  const [files, setFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const uploaded = useRef(new Map<File, { id: string; name: string }>())
  const fileInput = useRef<HTMLInputElement>(null)
  const [language, setLanguage] = useState('fr-FR')
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState('')
  const [error, setError] = useState('')
  const recognition = useRef<Recognition | null>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const key = threadId ?? 'new'
  const currentKey = useRef(key)
  currentKey.current = key
  useEffect(() => { setFiles([]); uploaded.current.clear() }, [threadId])
  const value = drafts[key] ?? ''
  const setValue = (text: string) => setDrafts(previous => ({ ...previous, [key]: text }))
  useEffect(() => { recognition.current?.abort(); recognition.current = null; setListening(false); setInterim('') }, [threadId])
  useEffect(() => () => { recognition.current?.abort() }, [])
  useEffect(() => { if (input.current) { input.current.style.height = 'auto'; input.current.style.height = `${Math.min(input.current.scrollHeight, 176)}px` } }, [value])
  const voice = () => {
    if (listening) { recognition.current?.stop(); return }
    const browser = window as unknown as { SpeechRecognition?: RecognitionConstructor; webkitSpeechRecognition?: RecognitionConstructor }
    const Constructor = browser.SpeechRecognition ?? browser.webkitSpeechRecognition
    if (!Constructor) { setError('La reconnaissance vocale n’est pas disponible dans ce navigateur.'); return }
    const session = new Constructor()
    recognition.current = session
    session.lang = language; session.interimResults = true; session.continuous = true
    session.onresult = event => {
      let partial = ''
      let final = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i]
        if (result.isFinal) final += result[0].transcript
        else partial += result[0].transcript
      }
      if (final) setDrafts(previous => ({ ...previous, [key]: `${previous[key] ?? ''}${previous[key] ? ' ' : ''}${final}` }))
      setInterim(partial)
    }
    session.onerror = event => { setError(event.error === 'not-allowed' || event.error === 'service-not-allowed' ? 'Autorisation du microphone refusée.' : event.error === 'audio-capture' ? 'Microphone indisponible.' : `Reconnaissance vocale : ${event.error}`); setListening(false) }
    session.onend = () => { setListening(false); setInterim(''); recognition.current = null }
    setError('')
    try { session.start(); setListening(true) } catch { setError('Impossible de démarrer la reconnaissance vocale.') }
  }
  const submit = async () => {
    if ((!value.trim() && !files.length) || running || uploading || chatModel.saving) return
    setUploading(true); setError('')
    try {
      const sources = []
      for (const file of files) {
        let source = uploaded.current.get(file)
        if (!source) {
          const result = await uploadFileSource(file.name, '', file)
          source = { id: result.source.id, name: file.name }
          uploaded.current.set(file, source)
        }
        sources.push(source)
      }
      if (currentKey.current !== key) throw new Error('La conversation a changé pendant l’import. Sélectionnez à nouveau les fichiers.')
      const reference = sources.map(source => `- ${source.name} (source ${source.id})`).join('\n')
      const text = [value.trim() || 'Je souhaite examiner les fichiers joints.', reference ? `Fichiers joints importés :\n${reference}` : ''].filter(Boolean).join('\n\n')
      setValue(''); setFiles([]); setUploading(false)
      try { await onSend(text); uploaded.current.clear() }
      catch (err) { setValue(value); setFiles(files); throw err }
    } catch (err) {
      setError(`Envoi impossible : ${err instanceof Error ? err.message : 'erreur inconnue'}`)
    } finally { setUploading(false) }
  }
  return <div className="w-full">
    <div className="composer-shell">
      <textarea ref={input} aria-label="Votre message" rows={1} value={value} onChange={e => setValue(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void submit() } }} placeholder="Décrivez votre objectif d’audit…" />
      {interim && <p className="px-2 text-sm text-slate-400" aria-live="polite">{interim}</p>}
      {files.length > 0 && <ul className="flex flex-wrap gap-2 px-2 py-2">{files.map((file, index) => <li key={`${file.name}-${index}`} className="flex items-center gap-2 rounded-lg bg-brand-50 px-2 py-1 text-xs text-brand-800">{file.name}<button type="button" disabled={uploading} onClick={() => setFiles(previous => previous.filter((_, i) => i !== index))} aria-label={`Retirer ${file.name}`}>×</button></li>)}</ul>}
      <div className="flex items-center gap-2 px-1 pb-1 pt-2">
        <input ref={fileInput} type="file" accept=".csv,.xlsx,.json" multiple className="sr-only" aria-label="Choisir des fichiers" onChange={event => { const selected = Array.from(event.target.files ?? []); if (selected.some(file => file.size > 25 * 1024 * 1024)) { setError('Chaque fichier doit peser au maximum 25 Mo.') } else { setError(''); setFiles(previous => [...previous, ...selected]) } event.target.value = '' }} />
        <button type="button" disabled={running || uploading} onClick={() => fileInput.current?.click()} aria-label="Ajouter des fichiers CSV, XLSX ou JSON" title="Ajouter des fichiers CSV, XLSX ou JSON" className="voice-button text-xl">+</button>
        <span className="hidden flex-1 text-xs text-slate-400 sm:inline">{uploading ? 'Import des fichiers…' : listening ? 'Écoute en cours…' : 'Entrée pour envoyer · Maj + Entrée pour une ligne'}</span>
        <span className="flex-1 sm:hidden" />
        {chatModel.options.length > 1 ? <select aria-label="Modèle actif" title={`Modèle actif pour les prochaines requêtes (${chatModel.provider})`} value={chatModel.model} disabled={running || chatModel.loading || chatModel.saving} onChange={event => void chatModel.changeModel(event.target.value)} className="max-w-[110px] rounded-md bg-transparent py-1 text-xs text-slate-600 sm:max-w-[180px]">{!chatModel.model && <option value="">Modèle</option>}{chatModel.options.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}</select> : <Link to="/settings" title="Configurer le modèle" className="max-w-[100px] truncate rounded-md px-1 py-1 text-xs text-slate-500 sm:max-w-[150px]">{chatModel.loading ? 'Modèle…' : chatModel.model || 'Modèle'}</Link>}
        <select aria-label="Langue de dictée" value={language} disabled={listening} onChange={e => setLanguage(e.target.value)} className="bg-transparent text-xs text-slate-500"><option value="fr-FR">FR</option><option value="en-US">EN</option><option value="ar-MA">العربية</option></select>
        <button type="button" onClick={voice} aria-label={listening ? 'Arrêter la dictée' : 'Démarrer la dictée'} aria-pressed={listening} className={`voice-button ${listening ? 'is-listening' : ''}`}><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3m-3 0h6"/></svg></button>
        {running ? <button type="button" onClick={onCancel} className="send-button bg-ink-900 hover:bg-ink-700" aria-label="Arrêter la génération" title="Arrêter la génération"><svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2.5" /></svg></button> : <button type="button" onClick={() => void submit()} disabled={(!value.trim() && !files.length) || uploading || chatModel.saving} className="send-button" aria-label="Envoyer le message" title="Envoyer (Entrée)"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7" /></svg></button>}
      </div>
    </div>
    <p className="mt-2 text-center text-[11px] text-slate-400">Fichiers : CSV, XLSX, JSON (25 Mo max). La dictée peut être traitée par un service du navigateur.</p>
    {chatModel.error && <p role="alert" className="mt-2 text-sm text-red-700">Modèle : {chatModel.error}</p>}
    {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
  </div>
}
