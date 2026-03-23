export interface Stock {
  code: string;
  name: string;
  current_price: number;
  change_percent: number;
  volume: number;
  market_cap: number;
  is_short: boolean;
  updated_at?: string;
}

export interface StockFundamentals {
  code: string;
  name?: string | null;
  current_price?: number | null;
  change_percent?: number | null;
  turnover_rate?: number | null;
  volume_ratio?: number | null;
  pe_dynamic?: number | null;
  pb?: number | null;
  total_market_cap?: number | null;
  float_market_cap?: number | null;
  amplitude?: number | null;
  updated_at?: string | null;
}

export interface Sector {
  id?: string;
  name: string;
  change_percent: number;
  up_count: number;
  down_count: number;
  leader_stock?: string;
  updated_at?: string;
}

export interface StockFilterResponse {
  stocks: Stock[];
  total_count: number;
  filter_time: string;
}

export interface AIAnalysis {
  stock_code: string;
  score: number;
  analysis_text: string;
}

export interface DailyChartData {
  date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
}

export interface IntradayChartData {
  time: string;
  price: number;
  volume: number;
  amount?: number;
  pre_close?: number;    // 昨收价（只在第一条数据中）
  trade_date?: string;   // 交易日期（只在第一条数据中）
}

export interface MarketSector {
  rank: number;
  name: string;
  code: string;
  price: number;
  change_amount: number;
  change_percent: number;
  market_cap: number;
  turnover_rate: number;
  leading_stock: string;
  leading_stock_change: number;
}

export interface MarketStock {
  code: string;
  name: string;
  price: number;
  change_percent: number;
  volume: number;
  amount: number;
  turnover: number;
}

export interface TaskStatus {
  task_id?: string | null;
  is_running: boolean;
  total: number;
  processed: number;
  message: string;
}

export interface StockCandidate {
  code: string;
  name?: string | null;
  price?: number | null;
  change_percent?: number | null;
}

export interface HotConceptItem {
  rank: number;
  name: string;
  change_percent: number;
  inflow: number;
  outflow: number;
  net_inflow: number;
}

export interface ConceptIntradayKlineItem {
  time: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
  amount: number;
}

export interface ConceptLeaderStock {
  code: string;
  name: string;
  price: number;
  change_percent: number;
  amount: number;
  turnover: number;
}

export interface ThsHotItem {
  rank: number;
  code: string;
  name: string;
  hot: number;
  change_percent: number;
  price: number;
  reason: string;
  tags: string;
}

export interface LianbanStockItem {
  code: string;
  name: string;
  change_percent: number;
  price: number;
  duration_days?: number;  // 连板持续天数
  success_rate?: number;   // 涨停成功率
  reason?: string;        // 涨停原因
}

export interface LianbanLadderLevel {
  prev_level: number;
  prev_count: number;
  prev_items: LianbanStockItem[];
  today_level: number;
  today_count: number;
  today_items: LianbanStockItem[];
}

export interface LianbanLadderResponse {
  date: string | null;
  prev_date: string | null;
  levels: LianbanLadderLevel[];
}

export interface SentimentItem {
  rank?: number;
  code: string;
  name?: string;
  date: string;
  score: number;
  level: string;
  components?: Record<string, unknown>;
}

export interface RunSentimentResponse {
  date: string | null;
  written: number;
  message: string;
  error?: string | null;
}

export interface AIStockAnalyzeResponse {
  symbol: string;
  name: string | null;
  model: string;
  result: Record<string, unknown>;
  raw_text: string | null;
}

export interface RelatedStock {
  code: string;
  name?: string | null;
}

export interface MessageStreamItem {
  id: string;
  time?: string | null;
  title: string;
  source?: string | null;
  url?: string | null;
  sentiment?: 'good' | 'bad' | null;
  related_stocks?: RelatedStock[];
}

export interface AbnormalRule {
  id: string;
  exchange: string;
  threshold_pct: number;
  name: string;
}

export interface AbnormalStockItem {
  code: string;
  name: string;
  exchange: string;
  rule_id: string;
  threshold_pct: number;
  change_percent: number;
  direction: 'UP' | 'DOWN';
}

export interface MessageStreamResponse {
  updated_at: string;
  abnormal: {
    rules: AbnormalRule[];
    triggered: AbnormalStockItem[];
    near: AbnormalStockItem[];
  };
  mergers: MessageStreamItem[];
  good_news: MessageStreamItem[];
  bad_news: MessageStreamItem[];
  cailian_news: MessageStreamItem[];  // 添加财联社新闻
  xueqiu_news: MessageStreamItem[];  // 添加雪球新闻
  eastmoney_news: MessageStreamItem[];  // 添加东方财富新闻
}

export interface MarketCalendarEvent {
  event_key: string;
  event_date: string;
  title: string;
  category?: string | null;
  market?: string | null;
  source?: string | null;
  details?: string | null;
  updated_at?: string | null;
}

export interface CalendarRefreshResponse {
  written: number;
  error: string | null;
}

export interface MarketIndex {
  name: string;
  price: number;
  change_amount: number;
  change_percent: number;
}

export interface MarketOverview {
  indices: MarketIndex[];
  sentiment: {
    score: number;
    status: string;
    advancing: number;
    declining: number;
    unchanged: number;
  };
  volume: {
    amount: number;
    unit: string;
    ratio: number;
    sh_amount?: number;  // 上交所成交额
    sz_amount?: number;  // 深交所成交额
    bj_amount?: number;  // 北交所成交额
  };
  is_open: boolean;
  last_update: string;
}

// ============ 策略相关类型 ============

export interface Strategy {
  id: number;
  name: string;
  description: string;
  script_content: string;
  interval_seconds: number;
  enabled: boolean;
  is_running: boolean;
  created_at: string;
  updated_at: string;
}

export interface StrategyResult {
  id: number;
  strategy_id: number;
  execution_time: string;
  status: 'success' | 'failed' | 'running';
  result_data: string | null;
  error_message: string | null;
  execution_duration_ms: number | null;
}

export interface StrategyStock {
  code: string;
  name: string;
  reason?: string;
}

export interface StrategyExecutionResult {
  success: boolean;
  result?: {
    stocks?: StrategyStock[];
    raw_output?: string;
  };
  error?: string;
  execution_time_ms?: number;
}

export interface SaveStrategyRequest {
  name: string;
  script_content: string;
  description?: string;
  interval_seconds?: number;
}

export interface StartStrategyRequest {
  interval_seconds?: number;
}
