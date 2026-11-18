import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ConnectionsPage } from './pages/Connections'
import { EvidenceExplorerPage } from './pages/EvidenceExplorer'
import { FindingsReviewPage } from './pages/FindingsReview'
import { HomePage } from './pages/Home'
import { MissionDetailPage } from './pages/MissionDetail'
import { MissionNewPage } from './pages/MissionNew'
import { ReportPage } from './pages/Report'
import { RunIndexPage } from './pages/RunIndex'
import { RunLivePage } from './pages/RunLive'
import { SettingsPage } from './pages/Settings'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/connections" element={<ConnectionsPage />} />
          <Route path="/missions/new" element={<MissionNewPage />} />
          <Route path="/missions/:missionId" element={<MissionDetailPage />} />
          <Route path="/runs" element={<RunIndexPage />} />
          <Route path="/runs/:runId" element={<RunLivePage />} />
          <Route path="/runs/:runId/report" element={<ReportPage />} />
          <Route path="/evidence" element={<EvidenceExplorerPage />} />
          <Route path="/findings" element={<FindingsReviewPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
