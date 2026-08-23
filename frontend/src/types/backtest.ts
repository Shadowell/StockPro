export type BacktestRunRecord = {
  id: string
  name: string
  status: string
  run_mode: 'quick' | 'full'
  strategy_name: string
  strategy_version: number
  strategy_version_id: string
  start_date: string
  end_date: string
  initial_cash: string
  promotion_status: string
  promotion_gate_complete?: boolean
  metrics?: Record<string, number | null>
  progress?: number
  error_message?: string | null
  data_purpose?: string
}

export type BacktestJobRecord = {
  job_id: string
  job_type: string
  run_mode: string
  status: string
  progress: number
  phase: string
  message: string
  backtest_run_id?: string | null
  created_at?: string
}

export type BacktestConfiguration = {
  strategy_versions: Array<Record<string, any>>
  dataset_snapshots: Array<Record<string, any>>
  universe_snapshots: Array<Record<string, any>>
  factor_snapshots: Array<Record<string, any>>
  pool_snapshots: Array<Record<string, any>>
  cost_models: Array<Record<string, any>>
  protocols: Array<Record<string, any>>
}
