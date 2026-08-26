import type { AssetClassFilter, TradeMode, CreateStep, PageView, StrategyInfo } from './types';

export const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'];
export const SYMBOLS = [
  'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'DOGE/USDT',
  'ADA/USDT', 'AVAX/USDT', 'DOT/USDT', 'LINK/USDT', 'UNI/USDT', 'NEAR/USDT',
];

export const SUPERPNL_STRATEGY_KEY = 'superpnl_15m_low_turnover';
export const KAIROS_SUPERPNL_COST_AWARE_STRATEGY_KEY = 'kairos_superpnl_cost_aware';
export const AI_AUTONOMOUS_STRATEGY_KEY = 'ai_autonomous_trader';

function stringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || '').trim()).filter(Boolean);
  }
  if (typeof value === 'string' && value.trim()) {
    return value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

export function isSuperPnLUniverseStrategy(strategy?: StrategyInfo | null): boolean {
  const cfg = strategy?.config && typeof strategy.config === 'object' ? strategy.config : {};
  const key = String(cfg.strategy_key || cfg.strategyKey || '').trim();
  return (
    key === SUPERPNL_STRATEGY_KEY ||
    key === KAIROS_SUPERPNL_COST_AWARE_STRATEGY_KEY ||
    Boolean(strategy?.name?.includes('SuperPnL'))
  );
}

export function isAiAutonomousStrategy(strategy?: Pick<StrategyInfo, 'name' | 'config'> | null): boolean {
  const cfg = strategy?.config && typeof strategy.config === 'object' ? strategy.config : {};
  const key = String(cfg.strategy_key || cfg.strategyKey || '').trim();
  return (
    key === AI_AUTONOMOUS_STRATEGY_KEY ||
    Boolean(cfg.ai_autonomous_trader || cfg.aiAutonomousTrader) ||
    Boolean(strategy?.name?.includes('AI自主交易'))
  );
}

export function getStrategySymbols(strategy?: StrategyInfo | null): string[] {
  if (!strategy) return [];
  const cfg = strategy.config && typeof strategy.config === 'object' ? strategy.config : {};
  const rowSymbols = stringList(strategy.symbols);
  if (rowSymbols.length > 0) return rowSymbols;
  return stringList(cfg.symbols);
}

export function getStrategyTradeSymbols(strategy?: StrategyInfo | null): string[] {
  if (!strategy) return [];
  const cfg = strategy.config && typeof strategy.config === 'object' ? strategy.config : {};
  const camel = stringList(cfg.tradeSymbols);
  return camel.length > 0 ? camel : stringList(cfg.trade_symbols);
}

export function formatSymbolList(symbols: string[], max = 5): string {
  if (symbols.length === 0) return '策略未定义';
  const shown = symbols.slice(0, max).join(', ');
  return symbols.length > max ? `${shown} 等 ${symbols.length} 个` : shown;
}

export function formatStrategySymbolScope(strategy?: StrategyInfo | null): string {
  const tradeSymbols = getStrategyTradeSymbols(strategy);
  if (tradeSymbols.length > 0) {
    return `交易子池: ${formatSymbolList(tradeSymbols)}`;
  }
  const symbols = getStrategySymbols(strategy);
  if (isSuperPnLUniverseStrategy(strategy) && symbols.length > 1) {
    return `模型币池: ${formatSymbolList(symbols)}`;
  }
  return formatSymbolList(symbols);
}

export function primaryStrategySymbol(strategy?: StrategyInfo | null): string {
  return getStrategySymbols(strategy)[0] || 'BTC/USDT';
}

/**
 * 模拟盘「快速验证」历史窗口（日历天）：细周期少取、粗周期多取，控制 K 线总根数。
 */
const PAPER_QUICK_VERIFY_DAYS: Readonly<Record<string, number>> = {
  '1m': 1,
  '5m': 3,
  '15m': 7,
  '1h': 30,
  '4h': 60,
  '1d': 120,
};

export function paperQuickVerifyDaysBack(timeframe: string): number {
  const tf = String(timeframe || '1h').trim();
  return PAPER_QUICK_VERIFY_DAYS[tf] ?? 30;
}

export const LIVE_PREFS_KEY = 'bitpro_live_trading_prefs_v2';

/** 模拟盘创建向导：未保存偏好时的默认周期（实盘仍用 DEFAULT_LIVE_CONFIG.timeframe） */
export const DEFAULT_PAPER_TIMEFRAME = '1d';
export const DEFAULT_PAPER_INITIAL_EQUITY = 1_000_000;

export const DEFAULT_LIVE_CONFIG = {
  symbol: '600519.SH',
  timeframe: '1d',
  initialEquity: 1_000_000,
  loopInterval: 60,
  riskPerTrade: 0.03,
  maxDailyLoss: 0.05,
  maxTotalLoss: 0.15,
};

export type LivePrefsStored = {
  v: 2;
  tradeMode?: TradeMode;
  view?: PageView;
  createStep?: CreateStep;
  selectedStrategy?: string | number;
  assetClassFilter?: AssetClassFilter;
  config?: Partial<typeof DEFAULT_LIVE_CONFIG>;
  exchange?: string;
  activeInstanceId?: string | null;
};

/** 读取 v2；若仅有 v1 则迁移为控制台视图（丢弃锁定 step） */
export function loadLivePrefs(): LivePrefsStored | null {
  try {
    const raw = localStorage.getItem(LIVE_PREFS_KEY);
    if (raw) {
      const p = JSON.parse(raw);
      if (p && p.v === 2) return p as LivePrefsStored;
    }
    const legacyRaw = localStorage.getItem('bitpro_live_trading_prefs_v1');
    if (!legacyRaw) return null;
    const legacy = JSON.parse(legacyRaw);
    if (!legacy || legacy.v !== 1) return null;
    const migrated: LivePrefsStored = {
      v: 2,
      tradeMode: legacy.tradeMode === 'live' ? 'live' : 'paper',
      view: 'dashboard',
      createStep: 'select',
      selectedStrategy: legacy.selectedStrategy ?? '',
      assetClassFilter: 'all',
      config:
        legacy.config && typeof legacy.config === 'object'
          ? { ...legacy.config }
          : undefined,
      exchange: typeof legacy.exchange === 'string' ? legacy.exchange : undefined,
    };
    return migrated;
  } catch {
    return null;
  }
}
