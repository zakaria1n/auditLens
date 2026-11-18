import { createContext, useContext, type ReactNode } from 'react'

import { useChatWorkspace, type ChatWorkspace } from './useChatWorkspace'

/**
 * État du workspace chat partagé par TOUTE l'application (ADR-17) : le shell
 * conserve la conversation montée quand on ouvre Connections/Rapports/Réglages,
 * donc l'historique, la branche active et les runs liés restent intacts.
 */
const ChatWorkspaceContext = createContext<ChatWorkspace | null>(null)

export function ChatWorkspaceProvider({ children }: { children: ReactNode }) {
  const ws = useChatWorkspace()
  return <ChatWorkspaceContext.Provider value={ws}>{children}</ChatWorkspaceContext.Provider>
}

export function useChatWorkspaceCtx(): ChatWorkspace {
  const ctx = useContext(ChatWorkspaceContext)
  if (!ctx) throw new Error('useChatWorkspaceCtx hors ChatWorkspaceProvider')
  return ctx
}
