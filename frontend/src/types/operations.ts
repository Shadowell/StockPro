export type OperationSignal = {
  id: string
  paper_instance_id: string
  strategy_version_id: string
  symbol: string
  signal_type: string
  status: string
  signal_time: string | null
  evidence: Record<string, unknown>
  acknowledged_by?: string
}

export type OperationAlert = Record<string, any> & {
  id: string
  paper_instance_id?: string | null
  severity: string
  category: string
  title: string
  message: string
  status: string
  triggered_at: string
}

export type WatchContext = {
  scope: 'business' | 'audit'
  data_status: 'empty' | 'stale' | 'fresh'
  source_label: string
  source_updated_at: string | null
  instances: Array<Record<string, any>>
  signals: OperationSignal[]
  orders: Array<Record<string, any>>
  trades: Array<Record<string, any>>
  positions: Array<Record<string, any>>
  risk_events: Array<Record<string, any>>
  runtime_events: Array<Record<string, any>>
  alerts: OperationAlert[]
  pool_moves: Array<Record<string, any>>
  coverage: Record<string, number>
  symbol_names: Record<string, string>
}

export type WatchRule = Record<string, any> & {
  id: string
  name: string
  rule_type: string
  rule_version: number
  severity: string
  enabled: boolean
  config: Record<string, any>
}
