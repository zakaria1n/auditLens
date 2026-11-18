import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { ChatWorkspaceProvider } from './lib/chatWorkspaceContext'
import { ConnectionsPage } from './pages/Connections'
import { EvidenceExplorerPage } from './pages/EvidenceExplorer'
import { FindingsReviewPage } from './pages/FindingsReview'
import { MissionDetailPage } from './pages/MissionDetail'
import { MissionNewPage } from './pages/MissionNew'
import { ReportPage } from './pages/Report'
import { ReportsPage } from './pages/Reports'
import { RunIndexPage } from './pages/RunIndex'
import { RunLivePage } from './pages/RunLive'
import { SettingsPage } from './pages/Settings'

/**
 * Shell unique chat-first (ADR-17) : la conversation est la surface principale.
 * Anciennes pages conservées par routes profondes (compatibilité des liens) ;
 * le tableau de bord Workspace est remplacé par la liste des conversations.
 */
export default function App() {
  return (
    <BrowserRouter>
      <ChatWorkspaceProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={null} />
            <Route path="/connections" element={<ConnectionsPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/missions/new" element={<MissionNewPage />} />
            <Route path="/missions/:missionId" element={<MissionDetailPage />} />
            <Route path="/runs" element={<RunIndexPage />} />
            <Route path="/runs/:runId" element={<RunLivePage />} />
            <Route path="/runs/:runId/report" element={<ReportPage />} />
            <Route path="/evidence" element={<EvidenceExplorerPage />} />
            <Route path="/findings" element={<FindingsReviewPage />} />
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Route>
        </Routes>
      </ChatWorkspaceProvider>
    </BrowserRouter>
  )
}
