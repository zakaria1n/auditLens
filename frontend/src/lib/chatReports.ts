export interface ReportListItem {
  id: string
  run_id: string
  mission_id: string
  mission_title: string
  version: number
  created_at: string
  model_id: string
  provider_id: string
  findings_included: number
  thread_id: string | null
}
