/**
 * Abonnement au flux SSE réel du backend (GET /api/runs/{id}/events).
 * Les animations de l'UI sont déclenchées uniquement par ces événements —
 * jamais par des timers factices (docs/02, docs/19).
 */

import { runEventsUrl } from './api'
import type { RunEvent } from './types'

export interface RunEventsSubscription {
  close: () => void
}

export function subscribeRunEvents(
  runId: string,
  handlers: {
    onEvent: (ev: RunEvent) => void
    onEnd: () => void
    onOpen?: () => void
    onError?: () => void
  },
): RunEventsSubscription {
  const es = new EventSource(runEventsUrl(runId))

  es.onopen = () => handlers.onOpen?.()
  es.onmessage = (message: MessageEvent<string>) => {
    try {
      const ev = JSON.parse(message.data) as RunEvent
      handlers.onEvent(ev)
    } catch {
      // trame SSE non JSON : ignorée (le backend n'en émet pas en pratique)
    }
  }
  es.addEventListener('end', () => {
    es.close()
    handlers.onEnd()
  })
  es.onerror = () => {
    handlers.onError?.()
    // EventSource retente automatiquement ; on ne ferme pas ici pour
    // ne pas perdre des événements en cas de coupure réseau brève.
  }

  return {
    close: () => es.close(),
  }
}
