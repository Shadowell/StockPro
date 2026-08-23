export interface StrategyParameterItem {
  key: string;
  label: string;
  value: string;
}

export interface StrategyParameterSections {
  trading: StrategyParameterItem[];
  risk: StrategyParameterItem[];
}

const HIDDEN_CONFIG_KEYS = new Set([
  'selection_logic',
  'selectionLogic',
  'trading_logic',
  'tradingLogic',
  'logicSummary',
  'module_path',
  'modulePath',
  'class_name',
  'className',
  'strategy_diagnostic_ws',
  'strategyDiagnosticWs',
  'strategy_diagnostic_every_n_bars',
  'strategyDiagnosticEveryNBars',
]);

const CONFIG_LABELS: Record<string, string> = {
  strategy_key: '策略引擎',
  timeframe: 'K线周期',
  symbols: '行情池',
  trade_symbols: '执行交易对',
  contract_trade_symbols: '合约执行对',
  target_symbol: '目标标的',
  spot_symbol: '现货腿',
  contract_symbol: '合约腿',
  market_type: '市场类型',
  inst_type: '产品类型',
  td_mode: '保证金模式',
  position_mode: '持仓模式',
  settle_ccy: '结算币种',
  is_paper_trading: '模拟盘模式',
  initial_capital: '模拟初始资金',
  loop_interval_sec: '轮询间隔',
  window_size: '模型窗口',
  warmup_bars: '预热K线',
  hold_bars: '持有K线',
  min_holding_bars: '最短持有',
  max_holding_bars: '最长持有',
  entry_interval_bars: '开仓间隔',
  rebalance_interval_bars: '再平衡间隔',
  cooldown_bars: '冷却K线',
  confidence_threshold: '置信度阈值',
  threshold_bps: '信号阈值',
  min_predicted_change: '最小预测涨幅',
  min_net_edge_bps: '最小净优势',
  min_expected_edge_bps: '最小预期优势',
  predict_steps: '预测步数',
  horizon: '预测视界',
  top_k: 'Top-K',
  top_k_per_side: '每边Top-K',
  max_pairs: '最大配对数',
  ema_fast: 'EMA快线',
  ema_slow: 'EMA慢线',
  ema_fast_window: 'EMA快线窗口',
  ema_slow_window: 'EMA慢线窗口',
  fast_window: '快线窗口',
  slow_window: '慢线窗口',
  atr_window: 'ATR窗口',
  atr_stop_mult: 'ATR止损倍数',
  rsi_window: 'RSI窗口',
  rsi_oversold: 'RSI超卖',
  rsi_overbought: 'RSI超买',
  donchian_window: 'Donchian窗口',
  bb_window: '布林窗口',
  bb_std: '布林标准差',
  macd_signal_window: 'MACD信号窗口',
  volume_window: '成交量窗口',
  min_volume_ratio: '最小量能比',
  trend_filter: '趋势过滤',
  market_regime_threshold: '市场状态阈值',
  min_atr_ratio: '最小ATR波动',
  allow_short: '允许做空',
  reversal_exit: '反向信号退出',
  max_leverage: '最高杠杆',
  leverage: '默认杠杆',
  risk_per_trade_pct: '单笔风险',
  max_position_pct: '单标的仓位上限',
  max_total_notional_pct: '总名义敞口上限',
  max_total_position_pct: '总仓位上限',
  max_position_per_symbol: '单币仓位上限',
  max_total_position: '总仓位上限',
  max_positions: '最大持仓数',
  max_concurrent_positions: '最大并发持仓',
  max_active_positions: '最大活跃持仓',
  max_active_symbols: '最大活跃标的',
  quote_per_order: '每笔名义金额',
  entry_quote_usdt: '入场名义金额',
  order_notional_usdt: '委托名义金额',
  trade_notional_usdt: '交易名义金额',
  min_order_notional_usdt: '最小下单名义',
  entry_balance_pct: '入场资金比例',
  entry_equity_pct: '入场权益比例',
  position_pct: '仓位比例',
  trade_notional_pct: '交易名义比例',
  stop_loss_bps: '止损',
  take_profit_bps: '止盈',
  trailing_start_bps: '移动止盈启动',
  trailing_pullback_bps: '移动止盈回撤',
  profit_floor_start_bps: '浮盈保护启动',
  profit_floor_bps: '浮盈保护底线',
  break_even_at_r: '保本R倍数',
  profit_trailing_start_r: '浮盈跟踪R倍数',
  profit_atr_trailing_start_r: 'ATR锁利启动R倍数',
  profit_peak_pullback_pct: '峰值回撤',
  profit_tighten_at_r: '收紧回撤R倍数',
  profit_tight_pullback_pct: '收紧后峰值回撤',
  profit_atr_stop_mult: '锁利ATR倍数',
  max_profit_hold_bars: '盈利持仓上限',
  hard_stop_loss_pct: '保证金兜底止损',
  hard_take_profit_pct: '保证金兜底止盈',
  break_even_buffer_bps: '保本缓冲',
  fee_bps: '默认手续费',
  maker_fee_bps: 'Maker手续费',
  taker_fee_bps: 'Taker手续费',
  slippage_bps: '滑点',
  commission_rate: '佣金率',
  maintenance_margin_rate: '维持保证金率',
  max_basket_loss_equity_pct: '篮子亏损上限',
  max_pool_loss_equity_pct: '资金池亏损上限',
  max_pool_notional_pct: '资金池名义上限',
  max_active_baskets: '最大活跃篮子',
  max_total_layers: '最大网格层数',
};

const CONFIG_VALUE_LABELS: Record<string, string> = {
  cross: '全仓',
  isolated: '逐仓',
  swap: '永续合约',
  spot: '现货',
  margin: '杠杆交易',
  long_short_mode: '双向持仓',
  net_mode: '单向持仓',
  ema_state: 'EMA状态过滤',
  ema_cross: 'EMA交叉',
  okx: 'OKX',
};

const MAX_IMPORTANT_PARAMS_PER_SECTION = 8;

const CORE_TRADING_CONFIG_KEYS = new Set([
  'timeframe',
  'trade_symbols',
  'contract_trade_symbols',
  'target_symbol',
  'spot_symbol',
  'contract_symbol',
  'market_type',
  'top_k',
  'top_k_per_side',
  'max_pairs',
  'window_size',
  'horizon',
  'predict_steps',
  'confidence_threshold',
  'threshold_bps',
  'min_net_edge_bps',
  'min_expected_edge_bps',
  'ema_fast',
  'ema_slow',
  'ema_fast_window',
  'ema_slow_window',
  'fast_window',
  'slow_window',
  'atr_window',
  'donchian_window',
  'rsi_window',
  'rsi_oversold',
  'rsi_overbought',
  'bb_window',
  'bb_std',
  'macd_signal_window',
  'volume_window',
  'min_volume_ratio',
  'trend_filter',
  'market_regime_threshold',
  'min_atr_ratio',
  'entry_interval_bars',
  'rebalance_interval_bars',
  'allow_short',
  'reversal_exit',
]);

const CORE_RISK_CONFIG_KEYS = new Set([
  'initial_capital',
  'quote_per_order',
  'entry_quote_usdt',
  'order_notional_usdt',
  'trade_notional_usdt',
  'min_order_notional_usdt',
  'entry_balance_pct',
  'entry_equity_pct',
  'position_pct',
  'trade_notional_pct',
  'risk_per_trade_pct',
  'max_position_pct',
  'max_total_notional_pct',
  'max_total_position_pct',
  'max_position_per_symbol',
  'max_total_position',
  'max_positions',
  'max_concurrent_positions',
  'max_active_positions',
  'max_active_symbols',
  'max_leverage',
  'leverage',
  'td_mode',
  'position_mode',
  'stop_loss_bps',
  'take_profit_bps',
  'trailing_start_bps',
  'trailing_pullback_bps',
  'profit_floor_start_bps',
  'profit_floor_bps',
  'atr_stop_mult',
  'break_even_at_r',
  'profit_trailing_start_r',
  'profit_atr_trailing_start_r',
  'profit_peak_pullback_pct',
  'profit_tighten_at_r',
  'profit_tight_pullback_pct',
  'profit_atr_stop_mult',
  'max_profit_hold_bars',
  'hard_stop_loss_pct',
  'hard_take_profit_pct',
  'maintenance_margin_rate',
  'fee_bps',
  'maker_fee_bps',
  'taker_fee_bps',
  'slippage_bps',
  'cooldown_bars',
  'max_basket_loss_equity_pct',
  'max_pool_loss_equity_pct',
  'max_pool_notional_pct',
]);

const RISK_KEY_PATTERNS = [
  /risk/,
  /capital/,
  /balance/,
  /cash/,
  /notional/,
  /quote/,
  /order_notional/,
  /min_order/,
  /position/,
  /exposure/,
  /leverage/,
  /margin/,
  /fee/,
  /commission/,
  /slippage/,
  /cost/,
  /loss/,
  /drawdown/,
  /stop/,
  /take_profit/,
  /trailing/,
  /profit_floor/,
  /break_even/,
  /pullback/,
  /blacklist/,
  /cooldown/,
  /hedge/,
  /buffer/,
  /dca/,
  /martingale/,
  /basket/,
  /pool/,
  /funding/,
];

function normalizeConfigKey(key: string): string {
  return key.replace(/[A-Z]/g, (char) => `_${char.toLowerCase()}`);
}

function labelForKey(key: string): string {
  const normalized = normalizeConfigKey(key);
  return CONFIG_LABELS[key] || CONFIG_LABELS[normalized] || '';
}

function isBlankValue(value: unknown): boolean {
  if (value == null) return true;
  if (typeof value === 'string') return value.trim().length === 0;
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

function formatNumber(value: number, maximumFractionDigits = 6): string {
  return value.toLocaleString(undefined, {
    maximumFractionDigits,
    minimumFractionDigits: 0,
  });
}

function formatPercent(value: number): string {
  const pct = Math.abs(value) <= 1 ? value * 100 : value;
  return `${formatNumber(pct, 4)}%`;
}

function formatConfigValue(key: string, value: unknown): string {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join('、');
  }
  if (typeof value === 'boolean') {
    return value ? '是' : '否';
  }
  if (typeof value === 'string') {
    return CONFIG_VALUE_LABELS[value] || value;
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    const normalized = normalizeConfigKey(key);
    if (normalized.includes('bps')) return `${formatNumber(value, 4)} bps`;
    if (normalized.includes('leverage')) return `${formatNumber(value, 2)}x`;
    if (normalized.includes('ms')) return `${formatNumber(value, 0)} ms`;
    if (normalized.includes('sec') || normalized.includes('seconds')) return `${formatNumber(value, 0)} 秒`;
    if (normalized.includes('minutes') || normalized === 'model_tf_min') return `${formatNumber(value, 0)} 分钟`;
    if (
      normalized.includes('bars') ||
      normalized.endsWith('_window') ||
      normalized.endsWith('_period') ||
      normalized.includes('horizon') ||
      normalized.includes('predict_steps') ||
      normalized.includes('lookback')
    ) {
      return `${formatNumber(value, 0)} 根`;
    }
    if (
      normalized.includes('pct') ||
      normalized.includes('ratio') ||
      normalized.includes('rate') ||
      normalized.includes('threshold') ||
      normalized.includes('predicted_change')
    ) {
      return formatPercent(value);
    }
    if (
      normalized.includes('usdt') ||
      normalized.includes('capital') ||
      normalized.includes('notional') ||
      normalized.includes('quote') ||
      normalized.includes('balance')
    ) {
      return `${formatNumber(value, 4)} USDT`;
    }
    return formatNumber(value);
  }
  if (typeof value === 'object' && value) {
    return JSON.stringify(value);
  }
  return String(value);
}

function isRiskConfigKey(key: string): boolean {
  const normalized = normalizeConfigKey(key);
  return RISK_KEY_PATTERNS.some((pattern) => pattern.test(normalized));
}

function itemPriority(item: StrategyParameterItem): number {
  const normalized = normalizeConfigKey(item.key);
  const priority = [
    'strategy_key',
    'timeframe',
    'trade_symbols',
    'contract_trade_symbols',
    'target_symbol',
    'market_type',
    'trend_filter',
    'fast_window',
    'slow_window',
    'ema_fast',
    'ema_slow',
    'atr_window',
    'min_atr_ratio',
    'market_regime_threshold',
    'initial_capital',
    'quote_per_order',
    'entry_quote_usdt',
    'risk_per_trade_pct',
    'max_position_pct',
    'max_total_notional_pct',
    'max_total_position_pct',
    'max_leverage',
    'leverage',
    'stop_loss_bps',
    'hard_stop_loss_pct',
    'take_profit_bps',
    'hard_take_profit_pct',
    'trailing_start_bps',
  ].indexOf(normalized);
  return priority >= 0 ? priority : 1000;
}

function sortParameterItems(items: StrategyParameterItem[]): StrategyParameterItem[] {
  return [...items].sort((left, right) => {
    const priorityDelta = itemPriority(left) - itemPriority(right);
    if (priorityDelta !== 0) return priorityDelta;
    return left.label.localeCompare(right.label, 'zh-CN');
  });
}

export function getStrategyParameterSections(config: Record<string, unknown> | null | undefined): StrategyParameterSections {
  const trading: StrategyParameterItem[] = [];
  const risk: StrategyParameterItem[] = [];
  if (!config) return { trading, risk };

  Object.entries(config).forEach(([key, value]) => {
    if (HIDDEN_CONFIG_KEYS.has(key) || isBlankValue(value)) return;
    const normalized = normalizeConfigKey(key);
    const importantTrading = CORE_TRADING_CONFIG_KEYS.has(normalized);
    const importantRisk = CORE_RISK_CONFIG_KEYS.has(normalized);
    if (!importantTrading && !importantRisk) return;
    const label = labelForKey(key);
    if (!label) return;
    const item: StrategyParameterItem = {
      key,
      label,
      value: formatConfigValue(key, value),
    };
    if (importantRisk || (isRiskConfigKey(key) && !importantTrading)) risk.push(item);
    else trading.push(item);
  });

  return {
    trading: sortParameterItems(trading).slice(0, MAX_IMPORTANT_PARAMS_PER_SECTION),
    risk: sortParameterItems(risk).slice(0, MAX_IMPORTANT_PARAMS_PER_SECTION),
  };
}
