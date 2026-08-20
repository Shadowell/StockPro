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

export type WorkflowCapabilityStatus = 'available' | 'partial' | 'disabled' | 'not_implemented';

export interface WorkflowStageCapability {
  id: 'strategy' | 'backtest' | 'paper' | 'watch' | 'monitor' | 'review';
  label: string;
  route: string;
  status: WorkflowCapabilityStatus;
  requires: string[];
  evidence: string[];
  reason?: string;
}

export interface WorkflowCapabilities {
  contract_version: string;
  behavioral_baseline: 'bitpro';
  execution_scope: 'paper_only';
  checked_at: string;
  auth_modes: Array<{
    id: 'admin' | 'guest' | 'agent';
    status: WorkflowCapabilityStatus;
    write_access: boolean;
    reason?: string;
  }>;
  feature_gates: Record<string, {
    status: WorkflowCapabilityStatus;
    enabled?: boolean;
    reason?: string;
  }>;
  domain_guardrails: string[];
  stages: WorkflowStageCapability[];
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
  source_label?: string | null;
  data_status?: 'fresh' | 'stale' | 'empty' | 'error' | string;
  error?: string | null;
  price_basis?: 'unadjusted' | 'qfq' | 'hfq' | string;
  price_usage?: 'valuation_snapshot' | string;
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

export interface DailyChartData {
  date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
  source_label?: string | null;
  updated_at?: string | null;
  price_basis?: 'unadjusted' | 'qfq' | 'hfq' | string;
  price_usage?: 'research_raw_bar' | string;
}

export interface IntradayChartData {
  time: string;
  price: number;
  volume: number;
  amount?: number;
  pre_close?: number;    // 昨收价（只在第一条数据中）
  trade_date?: string;   // 交易日期（只在第一条数据中）
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
  amount?: number | null;
}

export interface MarketWatchlistEntry {
  id: number;
  symbol: string;
  note: string;
  name?: string | null;
  price?: number | null;
  change_percent?: number | null;
  amount?: number | null;
  turnover?: number | null;
  volume_ratio?: number | null;
  amplitude?: number | null;
  quote_updated_at?: string | null;
  created_at: string;
}

export interface MarketWatchlistResponse {
  items: MarketWatchlistEntry[];
  total: number;
  source_label: string;
  source_updated_at?: string | null;
  data_status: 'available' | 'empty';
}

export interface OrderBookLevel {
  level: number;
  price?: number | null;
  volume?: number | null;
}

export interface OrderBookSnapshot {
  symbol?: string | null;
  code?: string | null;
  name?: string | null;
  price?: number | null;
  pre_close?: number | null;
  bid?: number | null;
  ask?: number | null;
  change_percent?: number | null;
  asks: OrderBookLevel[];
  bids: OrderBookLevel[];
  volume_unit?: string | null;
  trade_date?: string | null;
  trade_time?: string | null;
  source?: string | null;
  source_label?: string | null;
  data_status?: string | null;
  updated_at?: string | null;
  error?: string | null;
  price_basis?: 'unadjusted' | string;
  price_usage?: 'execution_quote' | string;
}

export interface HotConceptItem {
  rank: number;
  name: string;
  change_percent: number;
  inflow: number;
  outflow: number;
  net_inflow: number;
  updated_at?: string | null;
  source_label?: string | null;
}

export interface SectorFundFlowItem {
  rank?: number | null;
  name: string;
  change_percent?: number | null;
  net_inflow_yi: number;
  inflow_yi?: number | null;
  outflow_yi?: number | null;
  updated_at?: string | null;
  source_label?: string | null;
}

export interface SectorFundFlowResponse {
  limit: number;
  unit: string;
  inflows: SectorFundFlowItem[];
  outflows: SectorFundFlowItem[];
  rankings: SectorFundFlowItem[];
  updated_at?: string | null;
  data_status: 'fresh' | 'stale' | 'empty' | string;
  source_label: string;
  methodology: string;
}

export interface LimitBoardStock {
  symbol: string;
  code?: string | null;
  name?: string | null;
  pool_kind: 'up' | 'down' | string;
  price?: number | null;
  change_percent?: number | null;
  limit_times?: number | null;
  first_limit_at?: string | null;
  last_limit_at?: string | null;
  open_times?: number | null;
  seal_amount?: number | null;
  turnover?: number | null;
  industry?: string | null;
  source_label?: string | null;
}

export interface LimitBoardResponse {
  trade_date?: string | null;
  snapshot_id?: number | null;
  captured_at?: string | null;
  data_status: 'fresh' | 'stale' | 'empty' | string;
  source_label: string;
  counts: { up: number; down: number };
  up: LimitBoardStock[];
  down: LimitBoardStock[];
  methodology: string;
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
  source_label?: string | null;
  updated_at?: string | null;
  data_status?: 'fresh' | 'stale' | string;
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
  updated_at?: string | null;
  source_label?: string | null;
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
  source_updated_at?: string | null;
  response_generated_at?: string | null;
  data_status?: {
    stock_snapshot_state?: 'fresh' | 'stale' | 'unavailable' | string;
    stock_snapshot_updated_at?: string | null;
    news_state?: 'available' | 'empty' | string;
    message?: string | null;
  };
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

export interface TradingCalendarTag {
  kind: string;
  label: string;
  tone?: string | null;
  detail?: string | null;
}

export interface TradingCalendarDay {
  date: string;
  is_open: boolean;
  session: string;
  weekday?: number;
  tags: TradingCalendarTag[];
}

export interface TradingCalendarResponse {
  start: string;
  end: string;
  days: TradingCalendarDay[];
  source_label?: string | null;
  sources?: string[];
  errors?: string[];
  updated_at?: string | null;
}

export interface CalendarRefreshResponse {
  written: number;
  error: string | null;
}

export interface MarketIndex {
  name: string;
  code?: string;
  price: number;
  change_amount: number;
  change_percent: number;
}

/** Realtime-cache breadth diagnostics for operator market judgment. */
export interface MarketPulse {
  source_label?: string | null;
  universe_count?: number | null;
  rise_fall_ratio?: number | null;
  median_change_percent?: number | null;
  avg_change_percent?: number | null;
  strong_up_5?: number | null;
  strong_up_7?: number | null;
  weak_down_5?: number | null;
  weak_down_7?: number | null;
  limit_up_est?: number | null;
  limit_down_est?: number | null;
  amount_top10_share?: number | null;
  avg_turnover?: number | null;
  avg_amplitude?: number | null;
  avg_volume_ratio?: number | null;
  volume_ratio_gt2?: number | null;
  active_traded?: number | null;
  advancing?: number | null;
  declining?: number | null;
  unchanged?: number | null;
}

export interface MarketOverview {
  indices: MarketIndex[];
  sentiment?: {
    score: number | null;
    status: string;
    advancing: number | null;
    declining: number | null;
    unchanged: number | null;
  };
  volume?: {
    amount: number | null;
    unit: string;
    ratio: number | null;
    sh_amount?: number | null;  // 上交所成交额
    sz_amount?: number | null;  // 深交所成交额
    bj_amount?: number | null;  // 北交所成交额
  };
  hot_sectors?: Sector[];
  market_breadth?: {
    up: number | null;
    down: number | null;
    flat: number | null;
  };
  /** Derived from all_stocks_realtime; complementary to sealed short-line ecology. */
  market_pulse?: MarketPulse;
  data_status?: {
    stock_snapshot_state?: 'fresh' | 'stale' | 'unavailable' | string;
    stock_snapshot_count?: number;
    stock_snapshot_updated_at?: string | null;
    index_snapshot_state?: 'fresh' | 'stale' | 'unavailable' | string;
    index_snapshot_count?: number;
    index_snapshot_updated_at?: string | null;
    source_label?: string | null;
    message?: string;
  };
  is_open: boolean;
  session_phase?: 'pre_open' | 'auction' | 'open' | 'lunch' | 'closed' | 'weekend' | string;
  session_label?: string;
  session_detail?: string;
  session_local_time?: string;
  last_update?: string;
  response_generated_at?: string;
  updated_at?: string;
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
  data_purpose?: 'user' | 'acceptance' | 'seed';
}

export interface AICapabilities {
  provider: 'qwen';
  model: string | null;
  configured: boolean;
  generation_status: 'available' | 'not_configured';
  reason: string | null;
  strategy_auto_develop_mode: 'deterministic_template';
  strategy_auto_develop_uses_ai: false;
  checked_at: string;
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
  data_purpose?: 'user' | 'acceptance' | 'seed';
}

export type DataScope = 'business' | 'audit';

export interface StrategyValidationReport {
  valid: boolean;
  api_version: string;
  issues: Array<{ code: string; message: string; line?: number | null }>;
  dependencies: string[];
}

export interface StrategyVersion {
  id: string;
  legacy_strategy_id?: number | null;
  name: string;
  version: number;
  description: string;
  script_content: string;
  content_hash: string;
  strategy_api_version: string;
  validation_status: string;
  validation_report: StrategyValidationReport;
  dataset_snapshot_id?: number;
  parameter_schema?: Record<string, unknown>;
  data_dependencies?: string[];
  dependency_manifest?: Record<string, unknown>;
  runtime_limits?: Record<string, unknown>;
  status?: string;
  created_at?: string;
  updated_at?: string;
}

export interface StrategySaveResponse extends Partial<Strategy> {
  success: boolean;
  id?: number;
  message?: string;
  error?: string;
  strategy_version?: StrategyVersion;
  validation?: StrategyValidationReport;
}

export interface StrategyReplayResult {
  run_id: string;
  status: 'success' | 'failed' | 'resource_failed';
  event_count?: number;
  intent_count?: number;
  record_count?: number;
  intent_hash?: string;
  record_hash?: string;
  error_code?: string;
  error_message?: string;
}

export interface StartStrategyRequest {
  interval_seconds?: number;
}

export interface AutoDevelopStrategyRequest {
  objective?: string;
  symbols?: string[];
  risk_level?: 'conservative' | 'balanced' | 'aggressive';
}

export interface AutoDevelopStrategyResult {
  success: boolean;
  id: number;
  strategy: Strategy;
  symbols: string[];
  generated_plan: string;
}

export interface StrategyBacktestRequest {
  symbols?: string[];
  start_date?: string;
  end_date?: string;
  initial_capital?: number;
  position_pct?: number;
  commission?: number;
  stamp_duty?: number;
  slippage?: number;
  min_commission?: number;
}

export interface StrategyBacktestTrade {
  date: string;
  symbol: string;
  name?: string;
  side: 'buy' | 'sell';
  price: number;
  quantity: number;
  amount: number;
  fee: number;
  pnl: number;
  reason?: string;
}

export interface StrategyBacktestResult {
  engine?: string;
  status: string;
  backtest_id?: number;
  strategy_id: number;
  strategy_name: string;
  symbols: string[];
  symbol_names?: Record<string, string>;
  start_date: string;
  end_date: string;
  initial_capital: number;
  final_capital: number;
  total_return: number;
  annual_return?: number;
  max_drawdown: number;
  sharpe?: number;
  profit_factor?: number;
  win_rate: number;
  total_trades: number;
  equity_curve: Array<{ date: string; equity: number }>;
  trades: StrategyBacktestTrade[];
  created_at: string;
}

export interface BacktestMetric {
  metric_code: string;
  metric_value: number | null;
  unit: string;
  calculation_version: string;
  input_frequency: string;
  null_reason?: string | null;
  metric_payload?: Record<string, unknown>;
}

export interface BacktestProtocolEvaluation {
  sample_label: 'train' | 'validation' | 'out_of_sample';
  start_date: string;
  end_date: string;
  metrics: Record<string, number | null>;
  status: 'passed' | 'rejected' | 'not_applicable';
  reason?: string | null;
}

export interface BacktestPromotionCheck {
  check_code: string;
  status: 'passed' | 'failed' | 'pending';
  reason?: string | null;
  evidence?: Record<string, unknown>;
}

export interface ResearchProtocol {
  id: string;
  name: string;
  hypothesis: string;
  status: string;
  benchmark_code: string;
  train_start: string;
  train_end: string;
  validation_start?: string | null;
  validation_end?: string | null;
  out_of_sample_start: string;
  out_of_sample_end: string;
  embargo_days: number;
  capacity_rules: Record<string, number>;
  promotion_thresholds: Record<string, number>;
  content_hash?: string;
}

export interface BacktestRun {
  id: string;
  name: string;
  status: 'running' | 'success' | 'failed';
  run_mode: 'quick' | 'full';
  progress: number;
  promotion_status: string;
  strategy_version_id: string;
  strategy_name?: string;
  strategy_version?: number;
  script_content?: string;
  strategy_content_hash?: string;
  dataset_snapshot_id: number;
  factor_snapshot_id?: number | null;
  pool_snapshot_id?: number | null;
  universe_snapshot_id: number;
  research_protocol_id?: string | null;
  protocol_name?: string | null;
  cost_model_id: string;
  cost_model_name?: string;
  benchmark_code: string;
  start_date: string;
  end_date: string;
  initial_cash: number;
  parameters: Record<string, unknown>;
  universe: { symbols?: string[] };
  metrics?: Record<string, number | null>;
  core_metrics?: BacktestMetric[];
  protocol?: ResearchProtocol | null;
  protocol_evaluations?: BacktestProtocolEvaluation[];
  promotion_checks?: BacktestPromotionCheck[];
  promotion_gate_complete?: boolean;
  capacity_evidence?: { peak_capacity_ratio?: number | null };
  result_manifest?: Record<string, unknown>;
  input_hash?: string;
  error_message?: string | null;
  created_at: string;
  finished_at?: string | null;
  data_purpose?: 'user' | 'acceptance' | 'seed';
}

export type BacktestJobStatus =
  | 'pending'
  | 'running'
  | 'cancelling'
  | 'cancelled'
  | 'success'
  | 'failed'
  | 'interrupted';

export interface BacktestJob {
  job_id: string;
  job_type?: 'single' | 'walk_forward';
  request_payload: BacktestRunRequestV1;
  run_mode: 'quick' | 'full';
  status: BacktestJobStatus;
  progress: number;
  phase: string;
  message?: string | null;
  error_message?: string | null;
  backtest_run_id?: string | null;
  owner_role: 'admin' | 'guest';
  parent_job_id?: string | null;
  attempt: number;
  created_at: string;
  started_at?: string | null;
  updated_at: string;
  finished_at?: string | null;
  cancel_requested_at?: string | null;
  result_payload?: WalkForwardExecutionResult | Record<string, never>;
}

export interface BacktestJobLog {
  id: number;
  job_id: string;
  level: 'debug' | 'info' | 'warning' | 'error';
  phase: string;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface WalkForwardFold {
  index: number;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  train_sessions?: number;
  test_sessions?: number;
}

export interface WalkForwardPreview {
  planning_version?: string;
  dataset_snapshot_id: number;
  dataset_manifest_hash: string;
  start_date?: string;
  end_date?: string;
  date_count: number;
  n_folds: number;
  folds: WalkForwardFold[];
  promotion_eligible: boolean;
  next_step?: string;
}

export interface WalkForwardExecutionFold extends WalkForwardFold {
  best_parameters: Record<string, unknown>;
  is_objective: number;
  oos_objective?: number | null;
  oos_return?: number | null;
  is_run_id: string;
  oos_run_id: string;
  oos_degraded?: boolean | null;
}

export interface WalkForwardExecutionResult {
  execution_version: string;
  objective: string;
  direction: 'max' | 'min';
  dataset_snapshot_id: number;
  dataset_manifest_hash: string;
  n_folds: number;
  n_combinations: number;
  folds: WalkForwardExecutionFold[];
  summary: {
    compounded_oos_return: number;
    avg_is_objective?: number | null;
    avg_oos_objective?: number | null;
    degradation?: number | null;
    consistency: number;
    oos_equity_curve: Array<{ fold: number; date: string; value: number }>;
  };
  promotion_eligible: false;
  promotion_reason: string;
}

export interface BacktestConfiguration {
  strategy_versions: Array<{
    id: string;
    name: string;
    version: number;
    description?: string;
    script_content?: string;
    content_hash: string;
  }>;
  dataset_snapshots: Array<{
    id: number;
    name: string;
    start_date: string;
    end_date: string;
    row_count: number;
    symbol_count: number;
    manifest_hash: string;
    datasets: string[];
  }>;
  universe_snapshots: Array<{
    id: number;
    code: string;
    rule_version: string;
    trade_date: string;
    member_count: number;
    manifest_hash: string;
  }>;
  factor_snapshots: Array<{
    id: number;
    name: string;
    trade_date: string;
    dataset_snapshot_id: number;
    universe_snapshot_id: number;
    manifest_hash: string;
  }>;
  pool_snapshots: StockPoolSnapshot[];
  cost_models: Array<{
    id: string;
    code: string;
    name: string;
    version: number;
    content_hash: string;
  }>;
  protocols: ResearchProtocol[];
}

export interface BacktestDailyPoint {
  trade_date: string;
  strategy_nav: number;
  strategy_return?: number | null;
  benchmark_nav?: number | null;
  benchmark_return?: number | null;
  excess_nav?: number | null;
  excess_return?: number | null;
  equity: number;
  cash: number;
  market_value: number;
  gross_exposure: number;
  position_count: number;
  drawdown: number;
  excess_drawdown?: number | null;
}

export interface BacktestRunRequestV1 {
  strategy_version_id: string;
  dataset_snapshot_id: number;
  universe_snapshot_id: number;
  symbols: string[];
  start_date: string;
  end_date: string;
  initial_cash: number;
  factor_snapshot_id?: number | null;
  pool_snapshot_id?: number | null;
  cost_model_id?: string;
  research_protocol_id?: string | null;
  benchmark_code: string;
  parameters: Record<string, unknown>;
  event_limit?: number;
  name?: string;
}

export interface MarketEvidenceMetric {
  metric_code: string;
  label: string;
  value: number | null;
  unit?: string | null;
  definition: string;
  source_label?: string | null;
  publication_state: 'published' | 'unavailable';
  missing_reason?: string | null;
}

export interface MarketResearchContext {
  publication_state: string;
  reason?: string;
  snapshot: {
    id: number;
    trade_date: string;
    snapshot_type: string;
    session_label?: string;
    freshness?: string;
    source_map: Record<string, string>;
    status: string;
    content_hash: string;
  } | null;
  sentiment?: {
    metrics: MarketEvidenceMetric[];
    market_temperature: {
      value: number | null;
      formula_version: string;
      weights: Record<string, number>;
      missing_components: string[];
      publication_state: string;
    };
  };
  limit_ecosystem?: {
    source_label?: string | null;
    highest_board: number;
    ladder: Array<{ level: string; count: number; members: Array<Record<string, unknown>> }>;
    pools: Record<string, Array<Record<string, unknown>>>;
    promotion_elimination: Array<Record<string, unknown>>;
  };
  sector_evidence?: {
    classification_system: string;
    items: Array<Record<string, unknown>>;
  };
  comparisons?: Array<Record<string, unknown>>;
  evidence_summary?: {
    summary_version: string;
    kind: string;
    facts: Array<{ text: string; evidence_ref: string }>;
    inferences: Array<{ text: string; basis: string }>;
    evidence_snapshot_id: number;
    disclaimer: string;
  };
  heat_rankings?: Array<Record<string, unknown>>;
}

export interface StockPool {
  id: string;
  name: string;
  pool_type: 'screener' | 'factor' | 'sector' | 'event' | 'manual';
  description: string;
  status: string;
  data_purpose?: 'user' | 'acceptance' | 'seed';
  rule_id: string;
  rule_type: string;
  rule_version: number;
  config: Record<string, unknown>;
  rule_hash: string;
  snapshot_count: number;
  current_member_count: number;
  latest_generation_id?: string | null;
  latest_dataset_snapshot_id?: number | null;
  latest_universe_snapshot_id?: number | null;
  latest_factor_snapshot_id?: number | null;
  latest_market_evidence_snapshot_id?: number | null;
  latest_trade_date?: string | null;
  latest_knowledge_cutoff_at?: string | null;
  latest_input_hash?: string | null;
}

export interface StockPoolMember {
  ordinal: number;
  symbol: string;
  name?: string | null;
  score?: number | null;
  reason: string;
  evidence: Record<string, unknown>;
  evidence_hash: string;
  valid_from: string;
  valid_until?: string | null;
  generator_version: string;
}

export interface StockPoolGeneration {
  id: string;
  pool_id: string;
  status: string;
  trade_date: string;
  input_hash: string;
  member_manifest_hash?: string;
  member_count: number;
  members: StockPoolMember[];
  reused?: boolean;
}

export interface StockPoolSnapshot {
  id: number;
  pool_id: string;
  pool_name: string;
  pool_type: string;
  data_purpose?: 'user' | 'acceptance' | 'seed';
  trade_date: string;
  dataset_snapshot_id: number;
  universe_snapshot_id: number;
  factor_snapshot_id?: number | null;
  market_evidence_snapshot_id?: number | null;
  knowledge_cutoff_at: string;
  valid_until?: string | null;
  manifest_hash: string;
  member_count: number;
  status: string;
  members?: StockPoolMember[];
}

export interface PaperRunRequest {
  symbols?: string[];
  initial_capital?: number;
  position_pct?: number;
  commission?: number;
  slippage?: number;
}

export interface PaperOrder {
  account_id?: number;
  strategy_id?: number;
  symbol: string;
  name?: string;
  side: 'buy' | 'sell';
  price: number;
  quantity: number;
  amount: number;
  fee: number;
  status: string;
  reason?: string;
  created_at?: string;
}

export interface PaperPosition {
  account_id?: number;
  strategy_id?: number;
  symbol: string;
  name?: string;
  quantity: number;
  avg_price: number;
  last_price: number;
  market_value: number;
  pnl: number;
  pnl_pct: number;
  updated_at?: string;
}

export interface PaperAccount {
  account_id: number;
  strategy_id: number;
  strategy_name?: string;
  name: string;
  initial_capital: number;
  cash: number;
  equity: number;
  status: string;
  created_at: string;
  updated_at?: string;
  orders?: PaperOrder[];
  positions?: PaperPosition[];
  equity_curve?: Array<{ time?: string; equity: number; cash?: number }>;
  events?: Array<{ level: string; message: string; payload?: unknown; created_at?: string }>;
}

export interface PaperRunResult extends PaperAccount {
  orders: PaperOrder[];
  positions: PaperPosition[];
}

export interface PaperRuntimeCycle {
  id: string;
  cycle_key: string;
  trade_date: string;
  status: 'running' | 'success' | 'blocked' | 'failed';
  signal_count: number;
  order_count: number;
  trade_count: number;
  ledger_difference?: number | string | null;
  error_message?: string | null;
  created_at?: string | null;
  finished_at?: string | null;
}

export interface PaperRuntimeInstance {
  id: string;
  name: string;
  status: 'draft' | 'starting' | 'running' | 'paused' | 'stopping' | 'stopped' | 'failed';
  strategy_version_id: string;
  dataset_snapshot_id: number;
  factor_snapshot_id: number;
  universe_snapshot_id: number;
  pool_snapshot_id: number;
  research_protocol_id: string;
  qualifying_backtest_run_id: string;
  portfolio_id: string;
  parameters: Record<string, unknown>;
  capacity_limits: Record<string, unknown>;
  feed_config: Record<string, unknown>;
  cash_balance: number | string;
  initial_cash: number | string;
  equity?: number | string | null;
  signal_count?: number;
  order_count?: number;
  trade_count?: number;
  last_processed_trade_date?: string | null;
  heartbeat_at?: string | null;
  started_at?: string | null;
  stopped_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  latest_cycle_id?: string | null;
  latest_cycle_status?: PaperRuntimeCycle['status'] | null;
  latest_cycle_trade_date?: string | null;
  latest_cycle_finished_at?: string | null;
  latest_cycle_error?: string | null;
  latest_cycle_ledger_difference?: number | string | null;
  signals?: Array<Record<string, unknown>>;
  orders?: Array<Record<string, unknown>>;
  trades?: Array<Record<string, unknown>>;
  positions?: Array<Record<string, unknown>>;
  cash_ledger?: Array<Record<string, unknown>>;
  equity_snapshots?: Array<Record<string, unknown>>;
  events?: Array<Record<string, unknown>>;
  risk_events?: Array<Record<string, unknown>>;
  alerts?: Array<Record<string, unknown>>;
  cycles?: PaperRuntimeCycle[];
  strategy_version?: StrategyVersion;
  qualifying_backtest?: BacktestRun;
  reused?: boolean;
  data_purpose?: 'user' | 'acceptance' | 'seed';
}

export interface PaperKlineSnapshot {
  items: Array<{
    date: string;
    open: number | string | null;
    high: number | string | null;
    low: number | string | null;
    close: number | string | null;
    volume?: number | string | null;
  }>;
  total: number;
  symbol: string;
  source_label: string;
  dataset_snapshot_id: number;
  knowledge_cutoff_at?: string | null;
  data_status: 'available' | 'empty';
}

export interface RuntimeAlert {
  id: string;
  paper_instance_id?: string | null;
  category: 'signal' | 'pool' | 'data' | 'risk' | 'system';
  severity: 'info' | 'warning' | 'critical';
  title: string;
  message: string;
  source_object_type: string;
  source_object_id: string;
  evidence: Record<string, unknown>;
  status: 'active' | 'acknowledged' | 'resolved';
  triggered_at: string;
}

export type WatchRuleType = 'strategy' | 'indicator' | 'price' | 'abnormal';

export interface WatchRuleCondition {
  field: string;
  operator: 'gt' | 'gte' | 'lt' | 'lte' | 'eq';
  value: number | string;
}

export interface WatchRule {
  id: string;
  code: string;
  name: string;
  rule_type: WatchRuleType;
  rule_version: number;
  severity: 'info' | 'warning' | 'critical';
  enabled: boolean;
  data_purpose: 'user' | 'acceptance' | 'seed';
  config: {
    logic: 'all' | 'any';
    symbols: string[];
    conditions: WatchRuleCondition[];
  };
  last_evaluated_at?: string | null;
  created_at: string;
}

export interface WatchRulePreview {
  rule_id: string;
  rule_version: number;
  source_count: number;
  matched: number;
  items: Array<Record<string, unknown>>;
  writes_performed: boolean;
  alerts_created?: number;
  orders_created?: 0;
}

export interface WatchContext {
  scope: DataScope;
  excluded_counts: Record<string, number>;
  alerts: RuntimeAlert[];
  signals: Array<Record<string, unknown>>;
  orders: Array<Record<string, unknown>>;
  trades: Array<Record<string, unknown>>;
  positions: Array<Record<string, unknown>>;
  risk_events: Array<Record<string, unknown>>;
  runtime_events: Array<Record<string, unknown>>;
  pool_moves: Array<Record<string, unknown>>;
  instances: PaperRuntimeInstance[];
  coverage: Record<string, number>;
  symbol_names?: Record<string, string>;
  data_status: 'fresh' | 'stale' | 'empty';
  source_label: string;
  source_updated_at?: string | null;
  response_generated_at: string;
}

export interface StrategyRuntimeHealth {
  id: string;
  name: string;
  status: PaperRuntimeInstance['status'];
  health_state: 'fresh' | 'stale' | 'exhausted' | 'missing' | 'failed' | 'stopped' | 'draft';
  data_purpose: 'user' | 'acceptance' | 'seed';
  heartbeat_at?: string | null;
  heartbeat_age_seconds?: number | null;
  last_processed_trade_date?: string | null;
  latest_cycle_id?: string | null;
  latest_cycle_status?: string | null;
  latest_cycle_trade_date?: string | null;
  latest_cycle_finished_at?: string | null;
  latest_cycle_error?: string | null;
  latest_cycle_ledger_difference?: number | string | null;
  latest_equity?: number | string | null;
  latest_nav?: number | string | null;
  latest_drawdown?: number | string | null;
  latest_equity_trade_date?: string | null;
  order_count: number;
  trade_count: number;
  risk_event_count: number;
  rejected_count: number;
}

export interface MonitorHealth {
  scope: DataScope;
  excluded_counts: Record<string, number>;
  status: 'healthy' | 'warning' | 'critical' | 'unavailable';
  services: Array<Record<string, unknown>>;
  data: { dataset?: Record<string, unknown> | null; market?: Record<string, unknown> | null };
  strategy_instances: Array<Record<string, unknown>>;
  strategy_health: StrategyRuntimeHealth[];
  risk_alerts: Array<Record<string, unknown>>;
  active_alerts: RuntimeAlert[];
  notifications: Array<Record<string, unknown>>;
  source_label: string;
  source_updated_at?: string | null;
  response_generated_at: string;
}

export interface DailyReviewItem {
  id?: number;
  item_key: string;
  occurred_at: string;
  category: 'market' | 'pool' | 'strategy' | 'risk' | 'order' | 'trade' | 'position' | 'performance' | 'system';
  title: string;
  summary?: string | null;
  source_object_type: string;
  source_object_id: string;
  source_route?: string | null;
  resolution_status: 'resolved' | 'archived' | 'unavailable';
  evidence: Record<string, unknown>;
  evidence_hash: string;
}

export interface DailyReviewMetric {
  metric_code: string;
  metric_value: number | null;
  unit?: string | null;
  comparison_window?: string | null;
  source_object_type: string;
  source_object_id: string;
  calculation_version: string;
}

export interface DailyReviewContext {
  review?: {
    id: string;
    trade_date: string;
    status: 'draft' | 'sealed';
    author_name: string;
    summary?: string | null;
    next_day_plan?: string | null;
    source_manifest_hash?: string | null;
  } | null;
  trade_date: string;
  status: 'live' | 'draft' | 'sealed';
  items: DailyReviewItem[];
  metrics: DailyReviewMetric[];
  source_manifest_hash: string;
  counts: Record<string, number>;
}

export type ResearchDeskStageStatus = 'available' | 'partial' | 'empty';

export interface ResearchDeskStage {
  id: string;
  label: string;
  route: string;
  status: ResearchDeskStageStatus;
  count?: number | null;
  detail: string;
}

export interface ResearchDeskStrategy {
  id: number;
  name: string;
  description: string;
  updated_at?: string | null;
}

export interface ResearchDeskBacktest {
  id: string;
  name?: string | null;
  status: string;
  run_mode?: string | null;
  promotion_status?: string | null;
  strategy_name?: string | null;
  start_date?: string | null;
  end_date?: string | null;
}

export interface ResearchDeskPaper {
  id: string;
  name?: string | null;
  status: string;
}

export interface ResearchDeskNextAction {
  label: string;
  route: string;
  reason: string;
}

export interface ResearchDeskBindings {
  factor_codes: string[];
  factor_ready: number;
  dataset_snapshot_id?: number | null;
  pool_snapshot_id?: number | null;
  pool_trade_date?: string | null;
  strategy_version_id?: string | null;
  strategy_version_status?: string | null;
}

export interface ResearchDesk {
  contract_version: string;
  checked_at: string;
  trade_date?: string | null;
  pipeline: ResearchDeskStage[];
  active_strategy: ResearchDeskStrategy | null;
  latest_backtest: ResearchDeskBacktest | null;
  latest_paper: ResearchDeskPaper | null;
  next_action: ResearchDeskNextAction;
  bindings?: ResearchDeskBindings;
}

// ---------------------------------------------------------------------------
// AI 策略研发（多智能体闭环）
// ---------------------------------------------------------------------------

export interface AgentGoalCriteria {
  min_sharpe: number;
  max_drawdown: number;
  min_win_rate: number;
  min_return: number;
  min_trades: number;
  min_profit_loss_ratio: number;
}

export interface AgentResearchDefaults {
  dataset_snapshot_id: number | null;
  dataset_snapshot_name: string;
  universe_snapshot_id: number | null;
  universe_code: string;
  cost_model_id: string | null;
  benchmark_code: string;
  symbols: string[];
  start_date: string;
  end_date: string;
  event_limit: number;
  initial_cash: number;
}

export interface AgentResearchConfig {
  llm_available: boolean;
  default_model: string;
  defaults: AgentResearchDefaults;
}

export interface AgentTaskSummary {
  id: string;
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'stopped';
  stage: string;
  stage_label: string;
  goal: AgentGoalCriteria;
  user_prompt: string;
  iteration_count: number;
  max_iterations: number;
  best_iteration: number | null;
  best_score: number | null;
  best_metrics: Record<string, number | null> | null;
  llm_model: string;
  promoted_strategy_version_id: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentStrategySpec {
  market_analysis: string;
  strategy_candidates: { name: string; description: string; fit_reason: string }[];
  recommended_approach: string;
  risk_considerations: string;
  iteration_plan: string;
}

export interface AgentTaskDetail extends AgentTaskSummary {
  research_config: AgentResearchDefaults & Record<string, unknown>;
  strategy_spec: AgentStrategySpec | null;
}

export interface AgentEvalScores {
  risk_control: number;
  profitability: number;
  robustness: number;
  strategy_logic: number;
  originality: number;
  total_score: number;
}

export interface AgentIteration {
  id: string;
  task_id: string;
  iteration: number;
  action: 'new' | 'refine' | 'pivot';
  contract: {
    strategy_direction: string;
    key_indicators: string[];
    entry_logic_desc: string;
    exit_logic_desc: string;
    risk_management_desc: string;
    acceptance_criteria: string[];
    action: string;
  } | null;
  strategy_name: string;
  strategy_version_id: string | null;
  strategy_code: string;
  reasoning: string;
  sandbox_report: { valid: boolean; issues?: { code: string; message: string; line: number | null }[] } | null;
  backtest_run_id: string | null;
  backtest_metrics: Record<string, number | null>;
  eval_scores: AgentEvalScores | null;
  score: number;
  meets_goal: boolean;
  analysis: string;
  suggestions: string[];
  error: string;
  next_action: string;
  created_at: string;
}

export interface AgentTaskCreateRequest {
  name: string;
  user_prompt?: string;
  goal?: Partial<AgentGoalCriteria>;
  research_config?: Partial<AgentResearchDefaults>;
  max_iterations?: number;
  llm_model?: string | null;
}

// ---------------------------------------------------------------------------
// A 股实盘工作台
// ---------------------------------------------------------------------------

export interface LiveBrokerAdapter {
  key: string;
  name: string;
  available: boolean;
  configured: boolean;
  note: string;
}

export interface LiveTradingStatus {
  trading_enabled: boolean;
  boundary_note: string;
  adapters: LiveBrokerAdapter[];
  risk_limits: Record<string, number | null>;
}

export interface LivePromotionCandidate {
  kind: 'backtest_run' | 'paper_instance';
  id: string;
  name: string;
  strategy_version_id: string | null;
  promotion_status: string | null;
  metrics: Record<string, number | null>;
  detail: Record<string, unknown>;
}

export interface LivePreflightRequest {
  candidate_kind: 'backtest_run' | 'paper_instance';
  candidate_id: string;
}

export interface LivePreflightCheck {
  check_code: string;
  title: string;
  status: 'passed' | 'failed' | 'warning';
  reason: string | null;
}

export interface LivePreflightResult {
  candidate: LivePromotionCandidate | null;
  checks: LivePreflightCheck[];
  deployable: boolean;
  confirm_token: string | null;
}

export interface LiveDeploymentRequest {
  candidate_kind: 'backtest_run' | 'paper_instance';
  candidate_id: string;
  confirm_token: string;
  confirmed: boolean;
}

export interface LiveDeploymentResult {
  accepted: boolean;
  status: 'deployed' | 'rejected' | 'blocked';
  reason: string;
  event_id: string | null;
}

export interface LiveAuditEvent {
  id: string;
  event_type: string;
  candidate_kind: string;
  candidate_id: string;
  status: string;
  detail: Record<string, unknown>;
  created_at: string;
}
