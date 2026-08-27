// 行情相关类型
export interface Ticker {
  exchange: string;
  symbol: string;
  name?: string;
  displayName?: string;
  last: number;
  bid?: number;
  ask?: number;
  high?: number;
  low?: number;
  volume?: number;
  quoteVolume?: number;
  markPrice?: number;
  mark_price?: number;
  change?: number;
  changePercent?: number;
  changePercentToday?: number;
  change_percent?: number;
  change_percent_24h?: number;
  change_percent_today?: number;
  sectorKey?: string;
  sectorName?: string;
  taxonomyVersion?: string;
  sector_key?: string;
  sector_name?: string;
  taxonomy_version?: string;
  open24h?: number;
  sod_utc0?: number;
  sod_utc8?: number;
  timestamp?: number;
  source?: string;
  sourceUpdatedAt?: string | null;
  dataStatus?: string;
  unavailableReason?: string | null;
}

export interface Kline {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  /** 成交额（计价货币），缺省时前端可用 close * volume 估算 */
  quote_volume?: number;
  quoteVolume?: number;
  source?: string;
  dataStatus?: string;
}

export interface TechnicalIndicators {
  exchange: string;
  symbol: string;
  timeframe: string;
  source: string;
  dataSource?: string;
  timestamps: number[];
  series: Record<string, Array<number | null>>;
}

export interface PredictedKline extends Kline {
  confidence: number;
  is_predicted: true;
}

export interface OrderBook {
  exchange: string;
  symbol: string;
  bids: [number, number][];
  asks: [number, number][];
  timestamp?: number;
  dataStatus?: string;
  unavailableReason?: string | null;
  providerSource?: string;
  sourceUpdatedAt?: string | null;
}

// 资金费率相关
export interface FundingRate {
  exchange: string;
  symbol: string;
  currentRate: number;
  predictedRate?: number;
  nextFundingTime?: number;
  markPrice?: number;
  indexPrice?: number;
}

export interface FundingOpportunity {
  symbol: string;
  exchange: string;
  rate: number;
  annualized: number;
  nextFundingTime: number;
}

// 策略相关
export interface StrategyAuditSummary {
  selectionLogic: string;
  entryLogic: string;
  exitLogic: string;
  rebalanceLogic: string;
  riskConstraints: string[];
  universeSymbols: string[];
  latestExecutionReason?: string | null;
}

export interface StrategyLinkedBacktest {
  id: number;
  uuid: string;
  status: string;
  startDate: string;
  endDate: string;
  fillCount: number;
  closedTradeCount: number;
  orderCount: number;
  equityPointCount: number;
  metricStatus: 'eligible' | 'insufficient_sample';
}

export interface StrategyLinkedPaper {
  id: number;
  uuid: string;
  status: string;
  runtimeVersion?: string | null;
  symbols: string[];
  capacityLimits: Record<string, unknown>;
  feedConfig: Record<string, unknown>;
  consolePath: string;
}

export interface Strategy {
  id: number | string;
  name: string;
  description?: string;
  scriptContent: string;
  config?: Record<string, unknown>;
  status: 'running' | 'stopped' | 'error' | 'paused' | 'not_started';
  definitionStatus?: string;
  exchange?: string;
  symbols?: string[];
  versionId?: string;
  version?: number;
  versionParameters?: Record<string, unknown>;
  contentHash?: string | null;
  strategyApiVersion?: string | null;
  validationStatus?: string | null;
  validationReport?: Record<string, unknown>;
  validatedAt?: string | null;
  dataDependencies?: string[];
  outputContract?: Record<string, unknown>;
  isSample?: boolean;
  disclaimer?: string | null;
  auditSummary?: StrategyAuditSummary;
  linkedBacktest?: StrategyLinkedBacktest | null;
  linkedPaper?: StrategyLinkedPaper | null;
  createdAt: string;
  updatedAt: string;
}

export interface StrategyTrade {
  id: number;
  strategyId: number | string;
  exchange: string;
  symbol: string;
  orderId?: string;
  timestamp: number;
  side: 'buy' | 'sell';
  type: string;
  price: number;
  quantity: number;
  fee?: number;
  pnl?: number;
}

// 回测相关
export interface BacktestResult {
  id: number;
  strategyId: number;
  status: 'running' | 'completed' | 'failed';
  totalReturn?: number;
  annualReturn?: number;
  maxDrawdown?: number;
  sharpeRatio?: number;
  winRate?: number;
  profitFactor?: number;
  totalTrades?: number;
  trades?: StrategyTrade[];
  createdAt: string;
}

// 告警相关
export interface Alert {
  id: number;
  name: string;
  type: 'price' | 'funding' | 'position' | 'liquidation';
  symbol?: string;
  condition: Record<string, unknown>;
  notification?: Record<string, unknown>;
  enabled: boolean;
  lastTriggeredAt?: string;
  createdAt: string;
}

// 持仓
export interface Position {
  exchange: string;
  symbol: string;
  side: 'long' | 'short';
  amount: number;
  entryPrice: number;
  markPrice?: number;
  liquidationPrice?: number;
  unrealizedPnl?: number;
  leverage?: number;
  marginMode?: string;
}

// 余额
export interface Balance {
  currency: string;
  free: number;
  used: number;
  total: number;
}
