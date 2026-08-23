export type StrategyVersionRecord = {
  id: string
  legacy_strategy_id?: number | null
  name: string
  version: number
  description: string
  script_content: string
  content_hash: string
  parameter_schema: Record<string, unknown>
  data_dependencies: string[]
  dependency_manifest: Record<string, unknown>
  runtime_limits: Record<string, unknown>
  status: string
  validation_status: 'pending' | 'valid' | 'invalid'
  validation_report?: Record<string, unknown> | null
  parent_version_id?: string | null
  created_at?: string
  updated_at?: string
}

export type StrategyValidationResult = {
  valid: boolean
  issues: Array<{ code: string; message: string; line?: number | null }>
  dependencies: string[]
}
