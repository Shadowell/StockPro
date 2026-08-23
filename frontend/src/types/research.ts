export type DataStatus = 'empty' | 'partial' | 'fresh' | 'stale' | 'error'

export type InstrumentContract = {
  symbol: string
  name: string | null
  asset_class: 'stock' | 'etf' | 'index' | 'future'
  market: 'CN' | 'US'
  exchange: string
  currency: string
  tick_size: string
  lot_size: number
  contract_multiplier: string | null
  margin_rate: string | null
  expiry_date: string | null
  last_trade_date: string | null
  settlement_type: string | null
  session_calendar: string | null
  shortable: boolean
}

export type IndexView = {
  symbol: string
  name: string
  value: string | null
  change_pct: string | null
  source_updated_at: string | null
}

export type MarketBreadthView = {
  rise_count: number | null
  flat_count: number | null
  fall_count: number | null
}

export type TurnoverView = {
  amount: string | null
  unit: string
}

export type LimitEcologyView = {
  limit_up_count: number | null
  limit_down_count: number | null
  max_streak: number | null
  broken_board_rate: string | null
}

export type SectorFlowView = {
  sector_code: string
  sector_name: string
  net_inflow: string | null
  change_pct: string | null
}

export type MarketOverviewView = {
  indices: IndexView[]
  breadth: MarketBreadthView | null
  turnover: TurnoverView | null
  limit_ecology: LimitEcologyView | null
  sector_flows: SectorFlowView[]
  source_label: string
  source_updated_at: string | null
  trade_date: string | null
  data_status: DataStatus
}

export type InstrumentDetailView = {
  instrument: InstrumentContract
  latest_price: string | null
  change_pct: string | null
  turnover: string | null
  source_updated_at: string | null
  trade_date: string | null
  data_status: DataStatus
}

export type StockPoolView = {
  pool_id: string
  name: string
  status: string
  latest_snapshot_id: number | null
  latest_snapshot_status: string | null
  member_count: number | null
}

export type FactorView = {
  factor_code: string
  name: string
  category: string
  latest_version: number | null
  latest_snapshot_id: number | null
  validation_status: string
}

export type DailyBarView = {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  turnover: number | null
}

export type DailyBarsResponse = {
  items: DailyBarView[]
  adjustment: 'unadjusted'
  source_label: string
  data_status: DataStatus
}

export type OrderBookView = {
  bids: Array<[number, number]>
  asks: Array<[number, number]>
  source_label: string | null
  source_updated_at: string | null
  data_status: DataStatus
  unavailable_reason: string | null
}

export type MarketWatchlistEntry = {
  id: number
  owner: string
  symbol: string
  note: string
  name?: string | null
  price?: number | null
  change_percent?: number | null
  quote_updated_at?: string | null
}

export type StockPoolRecord = {
  id: string
  name: string
  pool_type: 'screener' | 'factor' | 'sector' | 'event' | 'manual'
  description?: string
  status: string
  data_purpose?: string
  rule_type?: string
  rule_version?: number
  rule_hash?: string
  config?: Record<string, unknown>
  snapshot_count?: number
  current_member_count?: number | null
  latest_generation_id?: string | null
  latest_trade_date?: string | null
}

export type StockPoolMember = {
  id: number
  ordinal: number
  symbol: string
  name?: string
  score: number | null
  reason: string
  evidence?: Record<string, unknown>
  evidence_hash: string
  valid_from: string
  valid_until?: string | null
}

export type StockPoolSnapshot = {
  id: number
  pool_id?: string
  generation_id?: string
  status: string
  manifest_hash: string
  member_count: number
  trade_date: string
  sealed_at?: string | null
}
