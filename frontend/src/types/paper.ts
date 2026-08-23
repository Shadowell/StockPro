export type PaperInstanceView = {
  id: string
  name: string
  lifecycle_status: string
  health_state: 'healthy' | 'warning' | 'error' | 'unavailable'
  initial_cash: string | number | null
  equity: string | number | null
  total_pnl: string | number | null
  return_rate: string | number | null
  trade_count: number
  position_count: number
  heartbeat_at: string | null
}

export type PaperInstanceList = {
  items: PaperInstanceView[]
  total: number
  scope: 'business' | 'audit'
}

export type PaperInstanceDetail = Record<string, any> & {
  id: string
  name: string
  status: string
  view: PaperInstanceView
  positions: Array<Record<string, any>>
  trades: Array<Record<string, any>>
  events: Array<Record<string, any>>
  risk_events: Array<Record<string, any>>
  alerts: Array<Record<string, any>>
  cycles: Array<Record<string, any>>
  equity_snapshots: Array<Record<string, any>>
  strategy_version?: Record<string, any> | null
  qualifying_backtest?: Record<string, any> | null
}
