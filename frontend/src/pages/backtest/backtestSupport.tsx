import type { ReactNode } from 'react';
import {
  AlertTriangle, ArrowDown, ArrowDownUp, ArrowUp,
  CheckCircle2, HelpCircle, Loader2, XCircle,
} from 'lucide-react';
import clsx from 'clsx';
import type { WatchTradeMarker } from '../../api/client';
import type { Kline } from '../../types';
import { formatTimeframeLabel } from '../../utils/timeframe';

export interface EquityPoint {
  timestamp: number;
  equity: number;
  drawdown?: number;
}

export interface TradeRecord {
  symbol?: string;
  timestamp: number;
  side: string;
  price: number;
  quantity: number;
  notional_usdt?: number;
  leverage?: number;
  margin?: number;
  pnl: number;
  pnl_pct?: number;
  fee?: number;
  reason?: string;
}

export interface BacktestResult {
  id?: number;
  strategyId: number;
  strategyName?: string;
  status: string;
  timeframe?: string;
  timeframeMode?: BacktestTimeframeMode;
  matrixResults?: BacktestResult[];
  startDate?: string;
  endDate?: string;
  initialCapital: number;
  finalCapital?: number;
  totalReturn?: number;
  annualReturn?: number;
  maxDrawdown?: number;
  maxDrawdownDurationDays?: number;
  sharpeRatio?: number;
  sortinoRatio?: number;
  calmarRatio?: number;
  winRate?: number;
  profitFactor?: number;
  totalTrades?: number;
  winningTrades?: number;
  losingTrades?: number;
  avgWinPct?: number;
  avgLossPct?: number;
  maxConsecutiveWins?: number;
  maxConsecutiveLosses?: number;
  expectancy?: number;
  totalFees?: number;
  avgHoldingBars?: number;
  totalBars?: number;
  elapsedSeconds?: number;
  monthlyReturns?: Record<string, number>;
  equityCurve?: EquityPoint[];
  trades?: TradeRecord[];
  errorMessage?: string;
  dataQualityStatus?: string | null;
  dataQualityMessage?: string | null;
  dataQualityCheckedAt?: string | null;
  createdAt?: string;
  isHistorical?: boolean;
}

export interface BacktestHistoryItem {
  id: number;
  strategyId: number;
  strategyName?: string | null;
  startDate: string;
  endDate: string;
  initialCapital: number;
  finalCapital?: number | null;
  totalReturn?: number | null;
  annualReturn?: number | null;
  maxDrawdown?: number | null;
  sharpeRatio?: number | null;
  winRate?: number | null;
  profitFactor?: number | null;
  totalTrades?: number | null;
  timeframe?: string | null;
  timeframeMode?: BacktestTimeframeMode | null;
  matrixResults?: BacktestResult[];
  status: string;
  dataQualityStatus?: string | null;
  dataQualityMessage?: string | null;
  dataQualityCheckedAt?: string | null;
  createdAt?: string;
}

export type BacktestHistoryDeleteTarget = {
  mode: 'single' | 'batch';
  items: BacktestHistoryItem[];
};

export type StrategyAssetClass = 'spot' | 'contract';
export type HistoryAssetFilter = 'all' | StrategyAssetClass;
export type BacktestView = 'dashboard' | 'detail';
export type BacktestStatusFilter = 'all' | 'running' | 'completed' | 'failed' | 'cancelled';
export type BacktestSortMode =
  | 'created_desc'
  | 'created_asc'
  | 'return_desc'
  | 'return_asc'
  | 'drawdown_desc'
  | 'drawdown_asc'
  | 'win_rate_desc'
  | 'win_rate_asc';
export type BacktestSortField = 'created' | 'return' | 'drawdown' | 'win_rate';
export type BacktestSortDirection = 'asc' | 'desc';

export type CryptoBacktestPerformanceMetrics = {
  annualizedVolatility: number | null;
  sortinoRatio: number | null;
  calmarRatio: number | null;
  feeDragPct: number | null;
  payoffRatio: number | null;
  expectancy: number | null;
  expectancyPct: number | null;
  tradeFrequencyPerDay: number | null;
  durationDays: number | null;
};

export type BacktestHistoryDerivedMetrics = {
  equityCurve: EquityPoint[];
  sortinoRatio: number | null;
  calmarRatio: number | null;
  avgWinPct: number | null;
  avgLossPct: number | null;
  expectancy: number | null;
  totalFees: number | null;
};

export const BACKTEST_PREFS_KEY = 'bitpro_backtest_prefs_v1';
export const BACKTEST_INSTANCES_KEY = 'bitpro_backtest_instances_v1';
export const SELECTED_BACKTEST_INSTANCE_KEY = 'bitpro_backtest_selected_instance';
/** @deprecated 旧版单任务恢复 key；新页面使用 BACKTEST_INSTANCES_KEY 保存多个实例。 */
export const ACTIVE_BACKTEST_JOB_KEY = 'bitpro_backtest_active_job';
export const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
export const BACKTEST_BENCHMARK_SYMBOL = 'BTC/USDT';
export const BACKTEST_HISTORY_PAGE_SIZE = 20;
export const BACKTEST_WIZARD_STEPS = [
  { step: 1, title: '选择策略', desc: '策略与资金模式' },
  { step: 2, title: '配置参数', desc: '区间、资金与成本' },
  { step: 3, title: '执行回测', desc: '异步任务并行运行' },
  { step: 4, title: '查看结果', desc: '绩效、交易与历史' },
] as const;
export const HISTORY_ASSET_FILTERS: Array<{ value: HistoryAssetFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'spot', label: '现货' },
  { value: 'contract', label: '合约' },
];
export const BACKTEST_STATUS_FILTERS: Array<{ value: BacktestStatusFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'running', label: '运行中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '已失败' },
  { value: 'cancelled', label: '已停止' },
];
export const BACKTEST_SORT_CONTROLS: Array<{ field: BacktestSortField; label: string }> = [
  { field: 'return', label: '收益率' },
  { field: 'drawdown', label: '回撤' },
  { field: 'win_rate', label: '胜率' },
  { field: 'created', label: '创建时间' },
];
export const BACKTEST_TIMEFRAME_OPTIONS = [
  { value: '1m', label: '1M' },
  { value: '5m', label: '5M' },
  { value: '15m', label: '15M' },
  { value: '30m', label: '30M' },
  { value: '1h', label: '1H' },
  { value: '4h', label: '4H' },
  { value: '1d', label: '1D' },
] as const;
export const BACKTEST_TIMEFRAME_MODES: Array<{ value: BacktestTimeframeMode; label: string; hint: string }> = [
  { value: 'strategy', label: '策略定义', hint: '沿用策略配置周期' },
  { value: 'single', label: '指定周期', hint: '本次回测覆盖一个周期' },
  { value: 'matrix', label: '多周期矩阵', hint: '一次对比多个周期' },
];

export type BacktestPrefsV1 = {
  v: 1;
  selectedStrategy?: number | null;
  /** @deprecated symbol is now derived from the selected strategy definition. */
  symbol?: string;
  startDate?: string;
  initialCapital?: number;
  /** @deprecated execution costs now reset to OKX defaults for each new run. */
  makerFeeBps?: number;
  /** @deprecated execution costs now reset to OKX defaults for each new run. */
  takerFeeBps?: number;
  /** @deprecated execution costs now reset to OKX defaults for each new run. */
  slippageBps?: number;
};

export const OKX_SPOT_BACKTEST_COSTS = { makerFeeBps: 8, takerFeeBps: 10, slippageBps: 1 } as const;
export const OKX_SWAP_BACKTEST_COSTS = { makerFeeBps: 2, takerFeeBps: 5, slippageBps: 1 } as const;

export type JobProgressState = {
  currentBar: number;
  totalBars: number;
  percent: number | null;
};

export type BacktestInstanceStatus = 'idle' | 'running' | 'cancelling' | 'completed' | 'failed' | 'interrupted' | 'cancelled';
export type BacktestTimeframeMode = 'strategy' | 'single' | 'matrix';

export type BacktestInstanceConfig = {
  selectedStrategy: number | null;
  startDate: string;
  endDate: string;
  initialCapital: number;
  timeframeMode: BacktestTimeframeMode;
  timeframe: string | null;
  timeframes: string[];
  makerFeeBps: number | null;
  takerFeeBps: number | null;
  slippageBps: number | null;
};

export interface BacktestInstance {
  id: string;
  name: string;
  status: BacktestInstanceStatus;
  config: BacktestInstanceConfig;
  activeJobId?: string | null;
  resumeJobId?: string | null;
  jobProgress?: JobProgressState | null;
  result?: BacktestResult | null;
  benchmarkKlines?: { timestamp: number; close: number }[];
  errorMessage?: string | null;
  historyId?: number | null;
  isPersistedHistory?: boolean;
  createdAt: string;
  updatedAt: string;
}

export function dateInputValue(date: Date): string {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, '0'),
    String(date.getDate()).padStart(2, '0'),
  ].join('-');
}

export function todayDateInputValue(): string {
  return dateInputValue(new Date());
}

export function clampIsoDateToToday(value: string | undefined, fallback: string): string {
  if (!value || !ISO_DATE.test(value)) return fallback;
  const today = todayDateInputValue();
  return value > today ? today : value;
}

export function defaultBacktestDateRange() {
  const today = new Date();
  const oneYearAgo = new Date(today);
  oneYearAgo.setFullYear(today.getFullYear() - 1);
  return {
    start: dateInputValue(oneYearAgo),
    end: dateInputValue(today),
  };
}

export function defaultBatchBacktestDateRange() {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const oneYearAgo = new Date(today);
  oneYearAgo.setFullYear(today.getFullYear() - 1);
  return {
    start: dateInputValue(oneYearAgo),
    end: dateInputValue(yesterday),
  };
}

export function loadBacktestPrefs(): BacktestPrefsV1 | null {
  try {
    const raw = localStorage.getItem(BACKTEST_PREFS_KEY);
    if (!raw) return null;
    const p = JSON.parse(raw);
    if (!p || p.v !== 1) return null;
    return p;
  } catch {
    return null;
  }
}

export function createBacktestInstance(
  partial: Partial<BacktestInstanceConfig> = {},
  nameIndex = 1,
): BacktestInstance {
  const range = defaultBacktestDateRange();
  const now = new Date().toISOString();
  const id =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `bt_${Date.now()}_${Math.random().toString(16).slice(2)}`;

  return {
    id,
    name: `回测实例 ${nameIndex}`,
    status: 'idle',
    config: {
      selectedStrategy:
        partial.selectedStrategy != null && Number.isFinite(Number(partial.selectedStrategy))
          ? Number(partial.selectedStrategy)
          : null,
      startDate: clampIsoDateToToday(partial.startDate, range.start),
      endDate: clampIsoDateToToday(partial.endDate, range.end),
      initialCapital:
        typeof partial.initialCapital === 'number' && partial.initialCapital > 0
          ? partial.initialCapital
          : 10000,
      timeframeMode: partial.timeframeMode || 'strategy',
      timeframe: partial.timeframe || '15m',
      timeframes: Array.isArray(partial.timeframes) && partial.timeframes.length > 0
        ? partial.timeframes
        : ['5m', '15m', '1h'],
      makerFeeBps:
        typeof partial.makerFeeBps === 'number' && partial.makerFeeBps >= 0
          ? partial.makerFeeBps
          : null,
      takerFeeBps:
        typeof partial.takerFeeBps === 'number' && partial.takerFeeBps >= 0
          ? partial.takerFeeBps
          : null,
      slippageBps:
        typeof partial.slippageBps === 'number' && partial.slippageBps >= 0
          ? partial.slippageBps
          : null,
    },
    activeJobId: null,
    resumeJobId: null,
    jobProgress: null,
    result: null,
    benchmarkKlines: [],
    errorMessage: null,
    createdAt: now,
    updatedAt: now,
  };
}

export function createBacktestDraft(partial: Partial<BacktestInstanceConfig> = {}): BacktestInstanceConfig {
  return createBacktestInstance(partial, 1).config;
}

export function quickDateRange(months: number) {
  const end = new Date();
  const start = new Date(end);
  start.setMonth(start.getMonth() - months);
  return {
    startDate: dateInputValue(start),
    endDate: dateInputValue(end),
  };
}

export function backtestDateValidationMessage(config: BacktestInstanceConfig): string | null {
  if (!ISO_DATE.test(config.startDate) || !ISO_DATE.test(config.endDate)) {
    return '回测日期格式不正确';
  }
  const today = todayDateInputValue();
  if (config.startDate > config.endDate) {
    return '开始日期不能晚于结束日期';
  }
  if (config.endDate > today) {
    return `结束日期不能晚于当前日期 ${today}`;
  }
  return null;
}

export function normalizeBacktestInstance(raw: any, index: number): BacktestInstance | null {
  if (!raw || typeof raw !== 'object') return null;
  const range = defaultBacktestDateRange();
  const cfg = raw.config && typeof raw.config === 'object' ? raw.config : raw;
  const status = String(raw.status || 'idle') as BacktestInstanceStatus;
  const hasErrorMessage = Boolean(raw.errorMessage);
  const normalizedStatus: BacktestInstanceStatus = (
    ['idle', 'running', 'cancelling', 'completed', 'failed', 'interrupted', 'cancelled'] as BacktestInstanceStatus[]
  ).includes(status)
    ? status
    : 'idle';
  const activeJobId = typeof raw.activeJobId === 'string' && raw.activeJobId.trim()
    ? raw.activeJobId.trim()
    : null;
  const resumeJobId = typeof raw.resumeJobId === 'string' && raw.resumeJobId.trim()
    ? raw.resumeJobId.trim()
    : null;

  return {
    id: String(raw.id || `legacy-${index + 1}`),
    name: String(raw.name || `回测实例 ${index + 1}`),
    status: hasErrorMessage ? 'failed' : activeJobId && normalizedStatus === 'idle' ? 'running' : normalizedStatus,
    config: {
      selectedStrategy:
        cfg.selectedStrategy != null && Number.isFinite(Number(cfg.selectedStrategy))
          ? Number(cfg.selectedStrategy)
          : null,
      startDate: clampIsoDateToToday(typeof cfg.startDate === 'string' ? cfg.startDate : undefined, range.start),
      endDate: clampIsoDateToToday(typeof cfg.endDate === 'string' ? cfg.endDate : undefined, range.end),
      initialCapital:
        typeof cfg.initialCapital === 'number' && cfg.initialCapital > 0
          ? cfg.initialCapital
          : Number(cfg.initialCapital) > 0
            ? Number(cfg.initialCapital)
            : 10000,
      timeframeMode: (['strategy', 'single', 'matrix'] as BacktestTimeframeMode[]).includes(cfg.timeframeMode)
        ? cfg.timeframeMode
        : 'strategy',
      timeframe: typeof cfg.timeframe === 'string' && cfg.timeframe ? cfg.timeframe : '15m',
      timeframes: Array.isArray(cfg.timeframes) && cfg.timeframes.length > 0
        ? cfg.timeframes.map((value: unknown) => String(value)).filter(Boolean)
        : ['5m', '15m', '1h'],
      makerFeeBps:
        cfg.makerFeeBps != null && Number(cfg.makerFeeBps) >= 0 ? Number(cfg.makerFeeBps) : null,
      takerFeeBps:
        cfg.takerFeeBps != null && Number(cfg.takerFeeBps) >= 0 ? Number(cfg.takerFeeBps) : null,
      slippageBps:
        cfg.slippageBps != null && Number(cfg.slippageBps) >= 0 ? Number(cfg.slippageBps) : null,
    },
    activeJobId,
    resumeJobId,
    jobProgress: raw.jobProgress || null,
    result: null,
    benchmarkKlines: [],
    errorMessage: raw.errorMessage ? String(raw.errorMessage) : null,
    createdAt: String(raw.createdAt || new Date().toISOString()),
    updatedAt: String(raw.updatedAt || new Date().toISOString()),
  };
}

export function isBacktestPlaceholderInstance(instance: BacktestInstance): boolean {
  return (
    !instance.config.selectedStrategy &&
    instance.status === 'idle' &&
    !instance.activeJobId &&
    !instance.jobProgress &&
    !instance.result &&
    !instance.errorMessage
  );
}

export function isBacktestUnhydratedCompletedInstance(instance: BacktestInstance): boolean {
  return (
    instance.status === 'completed' &&
    !instance.result &&
    !instance.historyId &&
    !instance.isPersistedHistory
  );
}

export function loadBacktestInstances(initialBt: BacktestPrefsV1 | null): BacktestInstance[] {
  try {
    const raw = localStorage.getItem(BACKTEST_INSTANCES_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      const rawInstances: unknown[] = Array.isArray(parsed?.instances) ? parsed.instances : [];
      const instances = rawInstances
        .map((item: unknown, index: number) => normalizeBacktestInstance(item, index))
        .filter((instance): instance is BacktestInstance => Boolean(instance))
        .filter((instance) => !isBacktestPlaceholderInstance(instance))
        .filter((instance) => !isBacktestUnhydratedCompletedInstance(instance));
      if (instances.length > 0) return instances;
    }
  } catch {
    /* ignore */
  }

  let legacyJobId = '';
  try {
    legacyJobId = sessionStorage.getItem(ACTIVE_BACKTEST_JOB_KEY)?.trim() || '';
  } catch {
    /* ignore */
  }

  const legacy = createBacktestInstance(
    {
      selectedStrategy: initialBt?.selectedStrategy ?? null,
      startDate: initialBt?.startDate,
      initialCapital: initialBt?.initialCapital,
    },
    1,
  );

  if (legacyJobId) {
    legacy.status = 'running';
    legacy.activeJobId = legacyJobId;
  }

  return legacy.activeJobId ? [legacy] : [];
}

export function persistableBacktestInstances(instances: BacktestInstance[]) {
  return instances.filter((instance) => !instance.isPersistedHistory).map((instance) => ({
    id: instance.id,
    name: instance.name,
    status: instance.status,
    config: instance.config,
    activeJobId: instance.activeJobId ?? null,
    resumeJobId: instance.resumeJobId ?? null,
    jobProgress: instance.jobProgress ?? null,
    errorMessage: instance.errorMessage ?? null,
    createdAt: instance.createdAt,
    updatedAt: instance.updatedAt,
  }));
}

export function backtestInstanceStatusMeta(status: BacktestInstanceStatus) {
  switch (status) {
    case 'running':
      return { label: '运行中', className: 'bg-blue-500/15 text-blue-300 border-blue-500/30' };
    case 'cancelling':
      return { label: '停止中', className: 'bg-amber-500/15 text-amber-300 border-amber-500/30' };
    case 'completed':
      return { label: '已完成', className: 'bg-green-500/15 text-green-300 border-green-500/30' };
    case 'failed':
      return { label: '失败', className: 'bg-red-500/15 text-red-300 border-red-500/30' };
    case 'interrupted':
      return { label: '已中断', className: 'bg-amber-500/15 text-amber-300 border-amber-500/30' };
    case 'cancelled':
      return { label: '已停止', className: 'bg-gray-500/10 text-gray-300 border-gray-500/30' };
    default:
      return { label: '待配置', className: 'bg-gray-500/10 text-gray-400 border-gray-500/20' };
  }
}

export function backtestDataQualityStatusMeta(status: string | null | undefined) {
  if (status === 'invalidated') {
    return {
      label: '数据失信',
      className: 'border-red-500/40 bg-red-500/10 text-red-200',
      icon: <AlertTriangle className="h-3.5 w-3.5" />,
    };
  }
  if (status === 'checked') {
    return {
      label: '已审计',
      className: 'border-emerald-500/35 bg-emerald-500/10 text-emerald-200',
      icon: <CheckCircle2 className="h-3.5 w-3.5" />,
    };
  }
  return {
    label: '未标记异常',
    className: 'border-blue-500/30 bg-blue-500/10 text-blue-200',
    icon: <HelpCircle className="h-3.5 w-3.5" />,
  };
}

export function backtestInstanceActionStatusLabel(status: BacktestInstanceStatus) {
  switch (status) {
    case 'completed':
      return '成功';
    case 'failed':
      return '失败';
    case 'running':
      return '运行中';
    case 'cancelling':
      return '停止中';
    case 'interrupted':
      return '中断';
    case 'cancelled':
      return '停止';
    default:
      return '待配置';
  }
}

export type BacktestInstanceActionTone = 'blue' | 'success' | 'green' | 'red' | 'amber' | 'neutral';

export const BACKTEST_INSTANCE_ACTION_BUTTON_BASE =
  'backtestInstanceActionButton inline-flex h-9 w-full min-w-[78px] items-center justify-center gap-1.5 rounded-xl border px-2.5 text-xs font-semibold tracking-[0.01em] transition-[background-color,border-color,color,box-shadow,transform] duration-150 hover:-translate-y-px focus-visible:outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0 sm:w-auto sm:min-w-[84px] sm:px-3 md:w-full md:min-w-0 2xl:h-10 2xl:w-auto 2xl:min-w-[92px] 2xl:gap-2 2xl:px-4 2xl:text-sm';

export const BACKTEST_INSTANCE_ACTION_BUTTON_TONES: Record<BacktestInstanceActionTone, string> = {
  blue: 'border-blue-400/45 bg-blue-500/[0.12] text-blue-100 shadow-[0_0_0_1px_rgba(59,130,246,0.08),inset_0_1px_0_rgba(255,255,255,0.08)] hover:border-blue-300/70 hover:bg-blue-500/[0.18] hover:shadow-[0_0_18px_-10px_rgba(59,130,246,0.9),inset_0_1px_0_rgba(255,255,255,0.10)] focus-visible:ring-blue-500/30',
  success: 'border-emerald-300/55 bg-emerald-400/[0.18] text-emerald-50 shadow-[0_0_0_1px_rgba(52,211,153,0.14),0_0_20px_-12px_rgba(52,211,153,0.95),inset_0_1px_0_rgba(255,255,255,0.10)] hover:border-emerald-200/75 hover:bg-emerald-400/[0.24] hover:shadow-[0_0_24px_-10px_rgba(52,211,153,0.95),inset_0_1px_0_rgba(255,255,255,0.12)] focus-visible:ring-emerald-300/35',
  green: 'border-emerald-500/40 bg-emerald-500/[0.10] text-emerald-200 shadow-[0_0_0_1px_rgba(16,185,129,0.06),inset_0_1px_0_rgba(255,255,255,0.06)] hover:border-emerald-400/65 hover:bg-emerald-500/[0.16] focus-visible:ring-emerald-500/30',
  red: 'border-red-400/45 bg-red-500/[0.09] text-red-100 shadow-[0_0_0_1px_rgba(248,113,113,0.08),inset_0_1px_0_rgba(255,255,255,0.06)] hover:border-red-300/70 hover:bg-red-500/[0.15] hover:shadow-[0_0_18px_-11px_rgba(248,113,113,0.9),inset_0_1px_0_rgba(255,255,255,0.08)] focus-visible:ring-red-500/30',
  amber: 'border-amber-400/45 bg-amber-500/[0.10] text-amber-100 shadow-[0_0_0_1px_rgba(245,158,11,0.08),inset_0_1px_0_rgba(255,255,255,0.06)] hover:border-amber-300/70 hover:bg-amber-500/[0.16] focus-visible:ring-amber-500/30',
  neutral: 'border-white/10 bg-white/[0.035] text-gray-200 shadow-[0_0_0_1px_rgba(255,255,255,0.03),inset_0_1px_0_rgba(255,255,255,0.05)] hover:border-gray-400/45 hover:bg-white/[0.07] hover:text-white focus-visible:ring-gray-500/25',
};

export function backtestInstanceActionButtonClass(tone: BacktestInstanceActionTone, extra?: string) {
  return clsx(BACKTEST_INSTANCE_ACTION_BUTTON_BASE, BACKTEST_INSTANCE_ACTION_BUTTON_TONES[tone], extra);
}

export function backtestInstanceActionStatusTone(status: BacktestInstanceStatus): BacktestInstanceActionTone {
  switch (status) {
    case 'completed':
      return 'success';
    case 'failed':
      return 'red';
    case 'running':
      return 'blue';
    case 'cancelling':
    case 'interrupted':
      return 'amber';
    default:
      return 'neutral';
  }
}

export function backtestInstanceActionStatusIcon(status: BacktestInstanceStatus) {
  switch (status) {
    case 'completed':
      return <CheckCircle2 className="h-4 w-4" />;
    case 'failed':
      return <XCircle className="h-4 w-4" />;
    case 'running':
    case 'cancelling':
      return <Loader2 className="h-4 w-4 animate-spin" />;
    case 'interrupted':
      return <AlertTriangle className="h-4 w-4" />;
    default:
      return <HelpCircle className="h-4 w-4" />;
  }
}

export function backtestInstanceStatusBucket(status: BacktestInstanceStatus): BacktestStatusFilter {
  if (status === 'running' || status === 'cancelling') return 'running';
  if (status === 'completed') return 'completed';
  if (status === 'failed' || status === 'interrupted') return 'failed';
  if (status === 'cancelled') return 'cancelled';
  return 'all';
}

export function backtestInstanceReturn(instance: BacktestInstance): number | null {
  const value = instance.result?.totalReturn;
  return value != null && Number.isFinite(value) ? value : null;
}

export function backtestInstanceDrawdown(instance: BacktestInstance): number | null {
  const value = instance.result?.maxDrawdown;
  return value != null && Number.isFinite(value) ? value : null;
}

export function backtestInstanceWinRate(instance: BacktestInstance): number | null {
  const value = instance.result?.winRate;
  return value != null && Number.isFinite(value) ? value : null;
}

export function backtestInstanceCanContinue(instance: BacktestInstance): boolean {
  if (instance.status === 'running' || instance.status === 'cancelling' || instance.status === 'completed') {
    return false;
  }
  return Boolean(
    instance.resumeJobId ||
      (
        (instance.status === 'interrupted' || instance.status === 'failed') &&
        instance.config.selectedStrategy &&
        instance.config.startDate &&
        instance.config.endDate
      ),
  );
}

export function stringList(value: unknown): string[] {
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

export function strategySymbols(strategy: any | null | undefined): string[] {
  if (!strategy) return [];
  const cfg = strategy.config && typeof strategy.config === 'object' ? strategy.config : {};
  return (
    stringList(strategy.symbols).length > 0
      ? stringList(strategy.symbols)
      : stringList((cfg as Record<string, unknown>).symbols)
  );
}

export function strategyBenchmarkSymbol(): string {
  return BACKTEST_BENCHMARK_SYMBOL;
}

export function strategyTradeSymbols(strategy: any | null | undefined): string[] {
  if (!strategy) return [];
  const cfg = strategy.config && typeof strategy.config === 'object' ? strategy.config as Record<string, unknown> : {};
  return (
    stringList(cfg.tradeSymbols).length > 0
      ? stringList(cfg.tradeSymbols)
      : stringList(cfg.trade_symbols)
  );
}

export function strategyTimeframe(strategy: any | null | undefined): string {
  if (!strategy) return '';
  const cfg = strategy.config && typeof strategy.config === 'object' ? strategy.config as Record<string, unknown> : {};
  const raw = cfg.timeframe ?? cfg.klineTimeframe ?? strategy.timeframe;
  return String(raw || '').trim();
}

export function backtestTimeframeLabel(timeframe: string | null | undefined): string {
  const normalized = normalizeBacktestTimeframe(timeframe);
  const option = BACKTEST_TIMEFRAME_OPTIONS.find((item) => item.value === normalized);
  return option?.label || formatTimeframeLabel(timeframe);
}

export function normalizeBacktestTimeframe(timeframe: string | null | undefined): string | null {
  const value = String(timeframe || '').trim().toLowerCase();
  if (!value) return null;
  const option = BACKTEST_TIMEFRAME_OPTIONS.find(
    (item) => item.value === value || item.label.toLowerCase() === value,
  );
  return option?.value || value;
}

export function uniqueBacktestTimeframes(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  values.forEach((value) => {
    const normalized = normalizeBacktestTimeframe(value);
    if (!normalized || seen.has(normalized)) return;
    seen.add(normalized);
    out.push(normalized);
  });
  return out;
}

export function backtestResultTimeframes(result: BacktestResult | null | undefined): string[] {
  if (!result) return [];
  if (Array.isArray(result.matrixResults) && result.matrixResults.length > 0) {
    return uniqueBacktestTimeframes(result.matrixResults.map((item) => item.timeframe));
  }
  return uniqueBacktestTimeframes([result.timeframe]);
}

export function backtestEffectiveTimeframe(config: BacktestInstanceConfig, strategy: any | null | undefined): string {
  if (config.timeframeMode === 'single' && config.timeframe) return config.timeframe;
  if (config.timeframeMode === 'matrix' && config.timeframes.length > 0) return config.timeframes[0];
  return strategyTimeframe(strategy) || config.timeframe || '1h';
}

export function backtestEffectiveTimeframes(config: BacktestInstanceConfig, strategy: any | null | undefined): string[] {
  if (config.timeframeMode === 'matrix') {
    return config.timeframes.length > 0 ? config.timeframes : [backtestEffectiveTimeframe(config, strategy)];
  }
  return [backtestEffectiveTimeframe(config, strategy)];
}

export function backtestInstanceTimeframes(instance: BacktestInstance, strategy: any | null | undefined): string[] {
  const resultTimeframes = backtestResultTimeframes(instance.result);
  if (resultTimeframes.length > 0) return resultTimeframes;
  if (instance.config.timeframeMode === 'matrix') {
    return uniqueBacktestTimeframes(instance.config.timeframes);
  }
  return uniqueBacktestTimeframes([backtestEffectiveTimeframe(instance.config, strategy)]);
}

export function finiteNumber(value: unknown): number | null {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function optionalFiniteNumber(value: unknown): number | undefined {
  return finiteNumber(value) ?? undefined;
}

export function backtestTradeNotional(trade: TradeRecord): number | null {
  const explicit = finiteNumber(trade.notional_usdt);
  if (explicit != null) return explicit;
  const inferred = Math.abs(trade.price * trade.quantity);
  return Number.isFinite(inferred) && inferred > 0 ? inferred : null;
}

export function backtestTradeMargin(trade: TradeRecord): number | null {
  const explicit = finiteNumber(trade.margin);
  if (explicit != null) return explicit;
  const leverage = finiteNumber(trade.leverage);
  const notional = backtestTradeNotional(trade);
  if (leverage != null && leverage > 0 && notional != null) {
    return notional / leverage;
  }
  return null;
}

export function formatBacktestTradeMoney(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return value.toFixed(digits);
}

export function formatBacktestTradeLeverage(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value <= 0) return '-';
  return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(2)}x`;
}

export function backtestRequestMatchesInstance(request: Record<string, unknown> | null | undefined, instance: BacktestInstance): boolean {
  if (!request || !instance.config.selectedStrategy) return false;
  if (Number(request.strategyId ?? request.strategy_id) !== Number(instance.config.selectedStrategy)) return false;
  if (String(request.startDate ?? request.start_date ?? '') !== instance.config.startDate) return false;
  if (String(request.endDate ?? request.end_date ?? '') !== instance.config.endDate) return false;
  const requestCapital = finiteNumber(request.initialCapital ?? request.initial_capital);
  if (requestCapital == null) return true;
  return Math.abs(requestCapital - instance.config.initialCapital) < 1e-9;
}

export function strategyIsContract(strategy: any | null | undefined): boolean {
  if (!strategy) return false;
  const cfg = strategy.config && typeof strategy.config === 'object' ? strategy.config as Record<string, unknown> : {};
  if (String(cfg.marketType ?? cfg.market_type ?? '').toLowerCase() === 'swap') return true;
  if (String(cfg.instType ?? cfg.inst_type ?? '').toUpperCase() === 'SWAP') return true;
  const name = String(strategy.name || '');
  const symbols = [
    ...stringList(strategy.symbols),
    ...stringList(cfg.symbols),
    ...stringList(cfg.tradeSymbols),
    ...stringList(cfg.trade_symbols),
  ];
  return name.startsWith('[合约]') || symbols.some((s) => s.includes(':USDT') || s.endsWith('-SWAP'));
}

export function inferStrategyAssetClassFromName(name: unknown): StrategyAssetClass | null {
  const text = String(name || '').trim();
  if (!text) return null;
  if (text.startsWith('[合约]') || text.includes('/USDT:USDT') || text.includes('-SWAP')) return 'contract';
  if (text.startsWith('[现货]')) return 'spot';
  return null;
}

export function strategyAssetClass(strategy: any | null | undefined): StrategyAssetClass {
  return strategyIsContract(strategy) ? 'contract' : 'spot';
}

export function strategyAssetClassById(strategies: any[], strategyId: number | null | undefined): StrategyAssetClass {
  const strategy = strategies.find((s) => Number(s.id) === Number(strategyId));
  return strategyAssetClass(strategy);
}

export function backtestResultAssetClass(
  strategies: any[],
  result: BacktestResult | null | undefined,
  strategyId: number | null | undefined,
): StrategyAssetClass {
  const strategy = strategies.find((s) => Number(s.id) === Number(result?.strategyId ?? strategyId));
  if (strategy) return strategyAssetClass(strategy);
  return inferStrategyAssetClassFromName(result?.strategyName) || 'spot';
}

export function backtestInstanceAssetClass(strategies: any[], instance: BacktestInstance): StrategyAssetClass {
  const strategy = strategies.find((s) => Number(s.id) === Number(instance.config.selectedStrategy));
  if (strategy) return strategyAssetClass(strategy);
  return (
    inferStrategyAssetClassFromName(instance.result?.strategyName) ||
    inferStrategyAssetClassFromName(instance.name) ||
    'spot'
  );
}

export function strategyNameColorClass(assetClass: StrategyAssetClass): string {
  return assetClass === 'contract' ? 'text-[#FFAB73]' : 'text-yellow-300';
}

export function strategyAssetBadgeClass(assetClass: StrategyAssetClass): string {
  return assetClass === 'contract'
    ? 'border-purple-500/30 bg-purple-500/10 text-purple-300'
    : 'border-yellow-500/30 bg-yellow-500/10 text-yellow-300';
}

export function isExplicitFalse(value: unknown): boolean {
  if (value === false) return true;
  if (typeof value === 'number') return value === 0;
  if (typeof value === 'string') {
    return ['false', '0', 'no', 'live', 'real'].includes(value.trim().toLowerCase());
  }
  return false;
}

export function strategyIsBacktestSelectable(strategy: any | null | undefined): boolean {
  if (!strategy) return false;
  const cfg = strategy.config && typeof strategy.config === 'object' ? strategy.config as Record<string, unknown> : {};
  const name = String(strategy.name || '');
  if (name.includes('[实盘试运行]') || name.includes('[实盘]')) return false;
  if (
    isExplicitFalse(cfg.is_paper_trading) ||
    isExplicitFalse(cfg.isPaperTrading) ||
    isExplicitFalse(cfg.dry_run) ||
    isExplicitFalse(cfg.dryRun)
  ) {
    return false;
  }
  const mode = String(
    cfg.mode ?? cfg.run_mode ?? cfg.runMode ?? cfg.execution_mode ?? cfg.executionMode ?? '',
  ).toLowerCase();
  return !['live', 'real', 'production'].some((token) => mode.includes(token));
}

export function strategyBacktestCostDefaults(strategy: any | null | undefined) {
  const isContract = strategyIsContract(strategy);
  const okxCosts = isContract ? OKX_SWAP_BACKTEST_COSTS : OKX_SPOT_BACKTEST_COSTS;

  return {
    makerFeeBps: okxCosts.makerFeeBps,
    takerFeeBps: okxCosts.takerFeeBps,
    slippageBps: okxCosts.slippageBps,
  };
}

export function symbolSummary(symbols: string[], max = 5): string {
  if (symbols.length === 0) return '策略未定义';
  const shown = symbols.slice(0, max).join(', ');
  return symbols.length > max ? `${shown} 等 ${symbols.length} 个` : shown;
}

export function backtestStrategySearchText(strategy: any): string {
  const cfg = strategy?.config && typeof strategy.config === 'object' ? strategy.config : {};
  const symbols = [...strategySymbols(strategy), ...strategyTradeSymbols(strategy)];
  const assetText = strategyIsContract(strategy) ? '合约 contract swap perpetual futures' : '现货 spot';
  return [
    strategy?.name,
    strategy?.description,
    strategy?.strategy_key,
    strategy?.strategyKey,
    cfg.strategy_key,
    cfg.strategyKey,
    cfg.strategy_type,
    cfg.strategyType,
    cfg.type,
    cfg.name,
    strategyTimeframe(strategy),
    assetText,
    ...symbols,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

export function strategyMatchesBacktestSearch(strategy: any, query: string): boolean {
  const tokens = query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
  if (tokens.length === 0) return true;
  const haystack = backtestStrategySearchText(strategy);
  return tokens.every((token) => haystack.includes(token));
}

export function backtestInstanceSearchText(
  instance: BacktestInstance,
  strategies: any[],
  strategyInfo: any | null | undefined,
): string {
  const timeframes = backtestInstanceTimeframes(instance, strategyInfo).map(backtestTimeframeLabel);
  const assetClass = backtestInstanceAssetClass(strategies, instance);
  const statusMeta = backtestInstanceStatusMeta(instance.status);
  return [
    backtestStrategyDisplayName(strategies, instance.config.selectedStrategy),
    instance.result?.strategyName,
    instance.name,
    instance.config.startDate,
    instance.config.endDate,
    instance.createdAt,
    instance.historyId,
    instance.activeJobId,
    instance.resumeJobId,
    assetClass === 'contract' ? '合约 contract swap perpetual futures' : '现货 spot',
    statusMeta.label,
    instance.status,
    instance.result?.dataQualityStatus,
    instance.result?.dataQualityMessage,
    instance.result?.timeframe,
    instance.config.timeframe,
    ...timeframes,
    ...strategySymbols(strategyInfo),
    ...strategyTradeSymbols(strategyInfo),
  ]
    .filter((item) => item != null && item !== '')
    .join(' ')
    .toLowerCase();
}

export function backtestInstanceMatchesSearch(
  instance: BacktestInstance,
  strategies: any[],
  strategyInfo: any | null | undefined,
  query: string,
): boolean {
  const tokens = query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
  if (tokens.length === 0) return true;
  const haystack = backtestInstanceSearchText(instance, strategies, strategyInfo);
  return tokens.every((token) => haystack.includes(token));
}

export function isPersistedBacktestStrategyName(value: unknown): boolean {
  const name = String(value ?? '').trim();
  if (!name) return false;
  return !['策略已不存在', '策略加载中', '未选择策略'].includes(name);
}

export function strategyNameById(
  strategies: any[],
  strategyId: number,
  fallbackName?: string | null,
): string {
  return backtestStrategyDisplayName(strategies, strategyId, fallbackName);
}

export function backtestStrategyDisplayName(
  strategies: any[],
  strategyId: number | null | undefined,
  fallbackName?: string | null,
): string {
  if (strategyId == null || !Number.isFinite(Number(strategyId))) {
    return isPersistedBacktestStrategyName(fallbackName) ? String(fallbackName).trim() : '未选择策略';
  }
  const match = strategies.find((s) => Number(s.id) === Number(strategyId));
  if (match?.name) return String(match.name);
  if (isPersistedBacktestStrategyName(fallbackName)) return String(fallbackName).trim();
  return strategies.length === 0 ? '策略加载中' : '策略已不存在';
}

export function formatDateTime(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('zh-CN', { hour12: false });
}

export function normalizeTradeTimestamp(value: unknown): number {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return Date.now();
  return n < 1_000_000_000_000 ? n * 1000 : n;
}

export function normalizeHistoryTrades(value: unknown): TradeRecord[] {
  if (!Array.isArray(value)) return [];
  return value.map((trade: any) => ({
    symbol: trade?.symbol,
    timestamp: normalizeTradeTimestamp(trade?.timestamp),
    side: String(trade?.side || ''),
    price: finiteNumber(trade?.price) ?? 0,
    quantity: finiteNumber(trade?.quantity) ?? 0,
    notional_usdt: optionalFiniteNumber(trade?.notional_usdt ?? trade?.notionalUsdt ?? trade?.notional),
    leverage: optionalFiniteNumber(trade?.leverage),
    margin: optionalFiniteNumber(trade?.margin ?? trade?.margin_usdt ?? trade?.marginUsdt),
    pnl: finiteNumber(trade?.pnl) ?? 0,
    pnl_pct: finiteNumber(trade?.pnlPct ?? trade?.pnl_pct) ?? undefined,
    fee: finiteNumber(trade?.fee) ?? undefined,
    reason: trade?.reason ? String(trade.reason) : undefined,
  }));
}

export function normalizeBacktestEquityCurve(value: unknown): EquityPoint[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((point: any) => {
      const timestamp = normalizeTradeTimestamp(point?.timestamp);
      const equity = finiteNumber(point?.equity);
      const drawdown = finiteNumber(point?.drawdown);
      if (equity == null || equity <= 0) return null;
      return {
        timestamp,
        equity,
        drawdown: drawdown ?? undefined,
      } satisfies EquityPoint;
    })
    .filter(Boolean) as EquityPoint[];
}

export function deriveBacktestTradePnlSamples(
  trades: TradeRecord[],
  totalTrades?: number | null,
): Array<{ timestamp: number; pnl: number; fee: number }> {
  const finiteRows = trades
    .map((trade) => ({
      timestamp: normalizeTradeTimestamp(trade.timestamp),
      pnl: finiteNumber(trade.pnl),
      fee: finiteNumber(trade.fee) ?? 0,
      side: String(trade.side || '').toLowerCase(),
      reason: String(trade.reason || '').toLowerCase(),
    }))
    .filter((trade) => trade.pnl != null) as Array<{
      timestamp: number;
      pnl: number;
      fee: number;
      side: string;
      reason: string;
    }>;
  const nonZeroRows = finiteRows.filter((trade) => Math.abs(trade.pnl) > 1e-9);
  if (nonZeroRows.length > 0) return nonZeroRows;
  const closeLikeRows = finiteRows.filter((trade) => (
    trade.reason.includes('close') ||
    trade.side.includes('close') ||
    trade.side.includes('sell') ||
    trade.side.includes('cover')
  ));
  if (closeLikeRows.length > 0) return closeLikeRows;
  const expected = finiteNumber(totalTrades);
  if (expected != null && expected > 0 && finiteRows.length <= expected + 1) return finiteRows;
  return [];
}

export function rebuildEquityCurveFromTradePnl(
  initialCapital: number,
  trades: TradeRecord[],
  totalTrades?: number | null,
): EquityPoint[] {
  if (!Number.isFinite(initialCapital) || initialCapital <= 0) return [];
  const samples = deriveBacktestTradePnlSamples(trades, totalTrades)
    .sort((a, b) => a.timestamp - b.timestamp);
  if (samples.length === 0) return [];
  let equity = initialCapital;
  let peak = initialCapital;
  return samples.map((sample) => {
    equity += sample.pnl;
    peak = Math.max(peak, equity);
    const drawdown = peak > 0 ? ((peak - equity) / peak) * 100 : 0;
    return {
      timestamp: sample.timestamp,
      equity,
      drawdown,
    };
  });
}

export function sortinoRatioFromEquityCurve(equityCurve: EquityPoint[]): number | null {
  if (!equityCurve || equityCurve.length < 2) return null;
  const dailyEquity = new Map<string, number>();
  [...equityCurve]
    .filter((point) => Number.isFinite(point.timestamp) && Number.isFinite(point.equity) && point.equity > 0)
    .sort((a, b) => a.timestamp - b.timestamp)
    .forEach((point) => {
      dailyEquity.set(new Date(point.timestamp).toISOString().slice(0, 10), point.equity);
    });
  const values = [...dailyEquity.values()];
  if (values.length < 3) return null;
  const returns: number[] = [];
  for (let i = 1; i < values.length; i++) {
    if (values[i - 1] > 0) returns.push((values[i] - values[i - 1]) / values[i - 1]);
  }
  const downsideReturns = returns.filter((value) => value < 0);
  if (returns.length < 2 || downsideReturns.length < 2) return null;
  const mean = returns.reduce((sum, value) => sum + value, 0) / returns.length;
  const downsideMean = downsideReturns.reduce((sum, value) => sum + value, 0) / downsideReturns.length;
  const downsideVariance = downsideReturns.reduce((sum, value) => sum + (value - downsideMean) ** 2, 0) / downsideReturns.length;
  const downsideStd = Math.sqrt(downsideVariance);
  return downsideStd > 0 ? (mean / downsideStd) * Math.sqrt(365) : null;
}

export function deriveBacktestHistoryMetrics(detail: any, trades: TradeRecord[]): BacktestHistoryDerivedMetrics {
  const initialCapital = finiteNumber(detail?.initialCapital ?? detail?.initial_capital) ?? 0;
  const totalTrades = finiteNumber(detail?.totalTrades ?? detail?.total_trades);
  const persistedEquityCurve = normalizeBacktestEquityCurve(detail?.equityCurve ?? detail?.equity_curve);
  const equityCurve = persistedEquityCurve.length > 0
    ? persistedEquityCurve
    : rebuildEquityCurveFromTradePnl(initialCapital, trades, totalTrades);
  const pnlSamples = deriveBacktestTradePnlSamples(trades, totalTrades);
  const wins = pnlSamples.filter((sample) => sample.pnl > 0);
  const losses = pnlSamples.filter((sample) => sample.pnl < 0);
  const avgWin = wins.length ? wins.reduce((sum, sample) => sum + sample.pnl, 0) / wins.length : null;
  const avgLoss = losses.length ? Math.abs(losses.reduce((sum, sample) => sum + sample.pnl, 0) / losses.length) : null;
  const expectancy = pnlSamples.length
    ? pnlSamples.reduce((sum, sample) => sum + sample.pnl, 0) / pnlSamples.length
    : null;
  const fees = trades
    .map((trade) => finiteNumber(trade.fee))
    .filter((fee): fee is number => fee != null);
  const totalFees = fees.length ? fees.reduce((sum, fee) => sum + fee, 0) : null;
  const annualReturn = finiteNumber(detail?.annualReturn ?? detail?.annual_return);
  const maxDrawdown = finiteNumber(detail?.maxDrawdown ?? detail?.max_drawdown);
  const calmarRatio = annualReturn != null && maxDrawdown != null && maxDrawdown > 0
    ? annualReturn / maxDrawdown
    : null;

  return {
    equityCurve,
    sortinoRatio: sortinoRatioFromEquityCurve(equityCurve),
    calmarRatio,
    avgWinPct: avgWin,
    avgLossPct: avgLoss,
    expectancy,
    totalFees,
  };
}

export function timeframeMs(timeframe: string): number {
  const normalized = String(timeframe || '').trim().toLowerCase();
  const amount = Number.parseInt(normalized, 10) || 1;
  if (normalized.endsWith('m')) return amount * 60_000;
  if (normalized.endsWith('h')) return amount * 60 * 60_000;
  if (normalized.endsWith('d')) return amount * 24 * 60 * 60_000;
  return 60 * 60_000;
}

export function tradeRecordMarkerLabel(side: string): 'B' | 'S' {
  const normalized = side.toLowerCase();
  if (
    normalized.includes('close_short') ||
    normalized.includes('buy') ||
    (normalized.includes('long') && !normalized.includes('close_long'))
  ) {
    return 'B';
  }
  if (
    normalized.includes('close_long') ||
    normalized.includes('sell') ||
    normalized.includes('short') ||
    normalized === 's'
  ) {
    return 'S';
  }
  return 'B';
}

export function buildBacktestTradeMarkers(
  trades: TradeRecord[],
  symbol: string,
  strategyId: number,
  strategyName: string,
): WatchTradeMarker[] {
  return trades
    .filter((trade) =>
      trade.symbol === symbol &&
      Number.isFinite(trade.timestamp) &&
      Number.isFinite(trade.price),
    )
    .sort((a, b) => a.timestamp - b.timestamp)
    .map((trade, index) => ({
      id: index + 1,
      label: tradeRecordMarkerLabel(trade.side),
      side: trade.side,
      action: trade.side,
      symbol,
      price: trade.price,
      quantity: trade.quantity,
      timestamp: trade.timestamp,
      datetime: new Date(trade.timestamp).toLocaleString('zh-CN', { hour12: false }),
      sourceStrategyId: strategyId,
      sourceStrategyName: strategyName,
      subscriptionId: 0,
      liveOrderId: null,
      clientOrderId: null,
    }));
}

export function normalizeBacktestKline(value: any): Kline | null {
  const timestamp = Number(value?.timestamp);
  const open = Number(value?.open);
  const high = Number(value?.high);
  const low = Number(value?.low);
  const close = Number(value?.close);
  const volume = Number(value?.volume ?? 0);
  if (![timestamp, open, high, low, close].every(Number.isFinite)) return null;
  return { timestamp, open, high, low, close, volume: Number.isFinite(volume) ? volume : 0 };
}

export function historyDetailToBacktestResult(detail: any, strategyName: string): BacktestResult {
  const trades = normalizeHistoryTrades(detail?.trades);
  const derivedMetrics = deriveBacktestHistoryMetrics(detail, trades);
  const winningTrades = trades.filter((trade) => (trade.pnl || 0) > 0).length;
  const losingTrades = trades.filter((trade) => (trade.pnl || 0) < 0).length;
  return {
    id: Number(detail?.id),
    strategyId: Number(detail?.strategyId),
    strategyName,
    status: String(detail?.status || 'completed'),
    timeframe: detail?.timeframe,
    timeframeMode: detail?.timeframeMode,
    matrixResults: Array.isArray(detail?.matrixResults) ? detail.matrixResults : undefined,
    startDate: detail?.startDate,
    endDate: detail?.endDate,
    initialCapital: finiteNumber(detail?.initialCapital) ?? 0,
    finalCapital: finiteNumber(detail?.finalCapital) ?? undefined,
    totalReturn: finiteNumber(detail?.totalReturn) ?? undefined,
    annualReturn: finiteNumber(detail?.annualReturn) ?? undefined,
    maxDrawdown: finiteNumber(detail?.maxDrawdown) ?? undefined,
    sharpeRatio: finiteNumber(detail?.sharpeRatio) ?? undefined,
    sortinoRatio: finiteNumber(detail?.sortinoRatio) ?? derivedMetrics.sortinoRatio ?? undefined,
    calmarRatio: finiteNumber(detail?.calmarRatio) ?? derivedMetrics.calmarRatio ?? undefined,
    winRate: finiteNumber(detail?.winRate) ?? undefined,
    profitFactor: finiteNumber(detail?.profitFactor) ?? undefined,
    totalTrades: finiteNumber(detail?.totalTrades) ?? trades.length,
    winningTrades,
    losingTrades,
    avgWinPct: finiteNumber(detail?.avgWinPct) ?? derivedMetrics.avgWinPct ?? undefined,
    avgLossPct: finiteNumber(detail?.avgLossPct) ?? derivedMetrics.avgLossPct ?? undefined,
    expectancy: finiteNumber(detail?.expectancy) ?? derivedMetrics.expectancy ?? undefined,
    totalFees: finiteNumber(detail?.totalFees) ?? derivedMetrics.totalFees ?? undefined,
    avgHoldingBars: finiteNumber(detail?.avgHoldingBars) ?? undefined,
    equityCurve: derivedMetrics.equityCurve,
    trades,
    dataQualityStatus: detail?.dataQualityStatus ?? null,
    dataQualityMessage: detail?.dataQualityMessage ?? null,
    dataQualityCheckedAt: detail?.dataQualityCheckedAt ?? null,
    createdAt: detail?.createdAt,
    isHistorical: true,
  };
}

export function normalizeBacktestHistoryStatus(status: string): BacktestInstanceStatus {
  const value = String(status || '').toLowerCase();
  if (value === 'failed') return 'failed';
  if (value === 'cancelled' || value === 'canceled') return 'cancelled';
  if (value === 'running' || value === 'pending') return 'running';
  return 'completed';
}

export function nullableMetricIdentity(value: unknown): string {
  const n = finiteNumber(value);
  return n == null ? '-' : n.toFixed(8);
}

export function backtestHistorySignature(item: BacktestHistoryItem): string {
  return [
    Number(item.strategyId || 0),
    item.startDate || '',
    item.endDate || '',
    nullableMetricIdentity(item.initialCapital),
    nullableMetricIdentity(item.totalReturn),
    nullableMetricIdentity(item.totalTrades),
  ].join('|');
}

export function backtestHistoryIdentity(item: BacktestHistoryItem): string {
  return `result:${item.id}`;
}

export function backtestInstanceHistoryIdentities(instance: BacktestInstance): string[] {
  const identities: string[] = [];
  const resultId = finiteNumber(instance.historyId ?? instance.result?.id);
  if (resultId != null) identities.push(`result:${resultId}`);
  if (instance.result) {
    identities.push([
      Number(instance.result.strategyId || instance.config.selectedStrategy || 0),
      instance.result.startDate || instance.config.startDate || '',
      instance.result.endDate || instance.config.endDate || '',
      nullableMetricIdentity(instance.result.initialCapital || instance.config.initialCapital),
      nullableMetricIdentity(instance.result.totalReturn),
      nullableMetricIdentity(instance.result.totalTrades),
    ].join('|'));
  }
  return identities;
}

export function historyItemToBacktestInstance(item: BacktestHistoryItem, strategyName: string): BacktestInstance {
  const createdAt = item.createdAt || new Date(0).toISOString();
  const matrixTimeframes = Array.isArray(item.matrixResults)
    ? uniqueBacktestTimeframes(item.matrixResults.map((result) => result.timeframe))
    : [];
  const itemTimeframe = normalizeBacktestTimeframe(item.timeframe);
  const itemTimeframeMode: BacktestTimeframeMode =
    item.timeframeMode === 'matrix'
      ? 'matrix'
      : item.timeframeMode === 'single'
        ? 'single'
        : 'strategy';
  return {
    id: `history-${item.id}`,
    name: strategyName,
    status: normalizeBacktestHistoryStatus(item.status),
    config: {
      selectedStrategy: Number(item.strategyId),
      startDate: item.startDate,
      endDate: item.endDate,
      initialCapital: item.initialCapital,
      timeframeMode: itemTimeframeMode,
      timeframe: itemTimeframe,
      timeframes: matrixTimeframes.length > 0 ? matrixTimeframes : itemTimeframe ? [itemTimeframe] : [],
      makerFeeBps: null,
      takerFeeBps: null,
      slippageBps: null,
    },
    activeJobId: null,
    resumeJobId: null,
    jobProgress: null,
    result: {
      id: item.id,
      strategyId: Number(item.strategyId),
      strategyName,
      status: item.status || 'completed',
      startDate: item.startDate,
      endDate: item.endDate,
      initialCapital: item.initialCapital,
      finalCapital: item.finalCapital ?? undefined,
      totalReturn: item.totalReturn ?? undefined,
      annualReturn: item.annualReturn ?? undefined,
      maxDrawdown: item.maxDrawdown ?? undefined,
      sharpeRatio: item.sharpeRatio ?? undefined,
      winRate: item.winRate ?? undefined,
      profitFactor: item.profitFactor ?? undefined,
      totalTrades: item.totalTrades ?? undefined,
      timeframe: itemTimeframe ?? undefined,
      timeframeMode: itemTimeframeMode,
      matrixResults: Array.isArray(item.matrixResults) ? item.matrixResults : undefined,
      dataQualityStatus: item.dataQualityStatus ?? null,
      dataQualityMessage: item.dataQualityMessage ?? null,
      dataQualityCheckedAt: item.dataQualityCheckedAt ?? null,
      createdAt,
      isHistorical: true,
    },
    benchmarkKlines: [],
    errorMessage: null,
    historyId: item.id,
    isPersistedHistory: true,
    createdAt,
    updatedAt: createdAt,
  };
}

export function backtestHistoryItemFromInstance(instance: BacktestInstance): BacktestHistoryItem | null {
  const resultId = finiteNumber(instance.historyId ?? instance.result?.id);
  const strategyId = finiteNumber(instance.result?.strategyId ?? instance.config.selectedStrategy);
  if (resultId == null || strategyId == null) return null;
  return {
    id: resultId,
    strategyId,
    strategyName: instance.result?.strategyName || instance.name || null,
    startDate: instance.result?.startDate || instance.config.startDate,
    endDate: instance.result?.endDate || instance.config.endDate,
    initialCapital: instance.result?.initialCapital || instance.config.initialCapital,
    finalCapital: instance.result?.finalCapital ?? null,
    totalReturn: instance.result?.totalReturn ?? null,
    annualReturn: instance.result?.annualReturn ?? null,
    maxDrawdown: instance.result?.maxDrawdown ?? null,
    sharpeRatio: instance.result?.sharpeRatio ?? null,
    winRate: instance.result?.winRate ?? null,
    profitFactor: instance.result?.profitFactor ?? null,
    totalTrades: instance.result?.totalTrades ?? null,
    dataQualityStatus: instance.result?.dataQualityStatus ?? null,
    dataQualityMessage: instance.result?.dataQualityMessage ?? null,
    dataQualityCheckedAt: instance.result?.dataQualityCheckedAt ?? null,
    status: instance.result?.status || instance.status,
    createdAt: instance.result?.createdAt || instance.createdAt,
  };
}

export function backtestInstanceLogs(instance: BacktestInstance): string[] {
  const logs: string[] = [];
  if (instance.errorMessage) logs.push(`[ERROR] ${instance.errorMessage}`);
  if (instance.result?.errorMessage) logs.push(`[ERROR] ${instance.result.errorMessage}`);
  if (instance.status === 'failed' && logs.length === 0) logs.push('[ERROR] 回测失败，后端未返回详细错误。');
  if (instance.status === 'interrupted') logs.push('[WARN] 回测任务已中断，可继续回测。');
  if (instance.status === 'cancelled') logs.push('[INFO] 回测任务已停止。');
  if (instance.status === 'completed') logs.push('[INFO] 回测已完成。');
  if (instance.status === 'running') logs.push('[INFO] 回测正在后台执行。');
  if (instance.activeJobId) logs.push(`[JOB] activeJobId=${instance.activeJobId}`);
  if (instance.resumeJobId) logs.push(`[JOB] resumeJobId=${instance.resumeJobId}`);
  const progress = instance.jobProgress;
  if (progress && progress.totalBars > 0) {
    const percent = progress.percent != null ? `, ${progress.percent.toFixed(1)}%` : '';
    logs.push(`[PROGRESS] ${progress.currentBar}/${progress.totalBars}${percent}`);
  }
  return logs.length > 0 ? logs : ['[INFO] 暂无回测日志。'];
}

export function backtestStatusDialogContent(instance: BacktestInstance): string {
  const meta = backtestInstanceStatusMeta(instance.status);
  const progress = instance.jobProgress && instance.jobProgress.totalBars > 0
    ? `${instance.jobProgress.currentBar} / ${instance.jobProgress.totalBars}` +
      (instance.jobProgress.percent != null ? ` (${instance.jobProgress.percent.toFixed(1)}%)` : '')
    : '无进行中进度';
  return [
    `状态：${meta.label}`,
    `策略：${instance.name}`,
    `区间：${instance.config.startDate} 至 ${instance.config.endDate}`,
    `初始资金：${instance.config.initialCapital}`,
    `当前任务：${instance.activeJobId || '-'}`,
    `可继续任务：${instance.resumeJobId || '-'}`,
    `进度：${progress}`,
    instance.errorMessage ? `错误：${instance.errorMessage}` : '',
  ].filter(Boolean).join('\n');
}

export function dateToStartMs(date: string): number {
  return new Date(`${date}T00:00:00`).getTime();
}

export function dateToEndMs(date: string): number {
  return new Date(`${date}T23:59:59.999`).getTime();
}

export function annualizedVolatilityFromEquityCurve(equityCurve: EquityPoint[]): number | null {
  if (!equityCurve || equityCurve.length < 2) return null;
  const dailyEquity = new Map<string, number>();
  [...equityCurve]
    .filter((point) => Number.isFinite(point.timestamp) && Number.isFinite(point.equity) && point.equity > 0)
    .sort((a, b) => a.timestamp - b.timestamp)
    .forEach((point) => {
      dailyEquity.set(new Date(point.timestamp).toISOString().slice(0, 10), point.equity);
    });
  const values = [...dailyEquity.values()];
  if (values.length < 3) return null;
  const returns: number[] = [];
  for (let i = 1; i < values.length; i++) {
    if (values[i - 1] > 0) returns.push((values[i] - values[i - 1]) / values[i - 1]);
  }
  if (returns.length < 2) return null;
  const mean = returns.reduce((sum, value) => sum + value, 0) / returns.length;
  const variance = returns.reduce((sum, value) => sum + (value - mean) ** 2, 0) / returns.length;
  return Math.sqrt(variance) * Math.sqrt(365) * 100;
}

export function backtestDurationDays(result: BacktestResult): number | null {
  if (!result.startDate || !result.endDate) return null;
  const start = dateToStartMs(result.startDate);
  const end = dateToEndMs(result.endDate);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
  return Math.max(1, (end - start) / 86_400_000);
}

export function buildCryptoBacktestPerformanceMetrics(result: BacktestResult): CryptoBacktestPerformanceMetrics {
  const durationDays = backtestDurationDays(result);
  const annualizedVolatility = annualizedVolatilityFromEquityCurve(result.equityCurve || []);
  const tradePnlSamples = deriveBacktestTradePnlSamples(result.trades || [], result.totalTrades);
  const winningPnlSamples = tradePnlSamples.filter((sample) => sample.pnl > 0);
  const losingPnlSamples = tradePnlSamples.filter((sample) => sample.pnl < 0);
  const avgWinningPnl = winningPnlSamples.length
    ? winningPnlSamples.reduce((sum, sample) => sum + sample.pnl, 0) / winningPnlSamples.length
    : null;
  const avgLosingPnl = losingPnlSamples.length
    ? Math.abs(losingPnlSamples.reduce((sum, sample) => sum + sample.pnl, 0) / losingPnlSamples.length)
    : null;
  const derivedTotalFees = result.trades?.length
    ? result.trades.reduce((sum, trade) => sum + (finiteNumber(trade.fee) ?? 0), 0)
    : null;
  const totalFees = result.totalFees ?? derivedTotalFees;
  const feeDragPct =
    totalFees != null && result.initialCapital > 0
      ? (totalFees / result.initialCapital) * 100
      : null;
  const sortinoRatio = result.sortinoRatio ?? sortinoRatioFromEquityCurve(result.equityCurve || []);
  const calmarRatio =
    result.calmarRatio ??
    (result.annualReturn != null && result.maxDrawdown != null && result.maxDrawdown > 0
      ? result.annualReturn / result.maxDrawdown
      : null);
  const payoffRatio =
    result.avgWinPct != null && result.avgLossPct != null && result.avgLossPct !== 0
      ? Math.abs(result.avgWinPct / result.avgLossPct)
      : avgWinningPnl != null && avgLosingPnl != null && avgLosingPnl > 0
        ? avgWinningPnl / avgLosingPnl
        : null;
  const expectancy =
    result.expectancy != null
      ? result.expectancy
      : tradePnlSamples.length
        ? tradePnlSamples.reduce((sum, sample) => sum + sample.pnl, 0) / tradePnlSamples.length
        : null;
  const expectancyPct =
    expectancy != null && result.initialCapital > 0
      ? (expectancy / result.initialCapital) * 100
      : null;
  const totalTrades = result.totalTrades ?? result.trades?.length ?? null;
  const tradeFrequencyPerDay =
    totalTrades != null && durationDays != null && durationDays > 0
      ? totalTrades / durationDays
      : null;
  return {
    annualizedVolatility,
    sortinoRatio,
    calmarRatio,
    feeDragPct,
    payoffRatio,
    expectancy,
    expectancyPct,
    tradeFrequencyPerDay,
    durationDays,
  };
}

export function backtestSortDirectionFor(
  sortMode: BacktestSortMode,
  field: BacktestSortField,
): BacktestSortDirection | null {
  const activeDirection: BacktestSortDirection = sortMode.endsWith('_asc') ? 'asc' : 'desc';
  const activeField = sortMode.slice(0, activeDirection === 'asc' ? -4 : -5) as BacktestSortField;
  return activeField === field ? activeDirection : null;
}

export function defaultBacktestSortDirection(field: BacktestSortField): BacktestSortDirection {
  return field === 'drawdown' ? 'asc' : 'desc';
}

export function nextBacktestSortMode(sortMode: BacktestSortMode, field: BacktestSortField): BacktestSortMode {
  const currentDirection = backtestSortDirectionFor(sortMode, field);
  const nextDirection = currentDirection
    ? currentDirection === 'desc' ? 'asc' : 'desc'
    : defaultBacktestSortDirection(field);
  return `${field}_${nextDirection}` as BacktestSortMode;
}

export function backtestApiSortBy(sortMode: BacktestSortMode): 'created' | 'return' | 'drawdown' | 'win_rate' {
  return sortMode.endsWith('_asc')
    ? sortMode.slice(0, -4) as 'created' | 'return' | 'drawdown' | 'win_rate'
    : sortMode.slice(0, -5) as 'created' | 'return' | 'drawdown' | 'win_rate';
}

export function backtestApiSortDir(sortMode: BacktestSortMode): 'asc' | 'desc' {
  return sortMode.endsWith('_asc') ? 'asc' : 'desc';
}

export function compareNullableBacktestMetric(
  left: number | null,
  right: number | null,
  direction: BacktestSortDirection,
): number {
  if (left == null && right == null) return 0;
  if (left == null) return 1;
  if (right == null) return -1;
  return direction === 'desc' ? right - left : left - right;
}

export function BacktestSortArrow({ direction }: { direction: BacktestSortDirection | null }) {
  if (direction === 'asc') return <ArrowUp className="h-3.5 w-3.5" />;
  if (direction === 'desc') return <ArrowDown className="h-3.5 w-3.5" />;
  return <ArrowDownUp className="h-3.5 w-3.5 opacity-60" />;
}

// ============================================
// 回测实例向导阶段
// ============================================
export function BacktestWizardStep({ step, title, desc, state, isLast }: {
  step: number;
  title: string;
  desc: string;
  state: 'done' | 'active' | 'pending';
  isLast: boolean;
}) {
  const done = state === 'done';
  const active = state === 'active';

  return (
    <div className="relative flex items-center gap-3 md:flex-col md:items-center md:text-center">
      {!isLast && (
        <div className="pointer-events-none absolute left-7 top-[1.65rem] h-10 w-px bg-crypto-border md:left-[calc(50%+2.75rem)] md:top-7 md:h-px md:w-[calc(100%-5.5rem)]">
          <div
            className={clsx(
              'h-full w-full transition-colors md:h-px',
              done ? 'bg-purple-500/70' : 'bg-crypto-border',
            )}
          />
        </div>
      )}
      <div
        className={clsx(
          'relative z-10 flex h-14 w-14 shrink-0 items-center justify-center rounded-full border-4 text-lg font-bold tabular-nums transition-colors',
          active && 'border-purple-500 bg-purple-500/20 text-purple-100 shadow-[0_0_0_4px_rgba(168,85,247,0.14)]',
          done && 'border-green-500/50 bg-green-500/15 text-green-300',
          state === 'pending' && 'border-crypto-border bg-crypto-bg text-gray-600',
        )}
      >
        {step}
      </div>
      <div className="min-w-0">
        <div
          className={clsx(
            'text-sm font-bold',
            active && 'text-white',
            done && 'text-green-300',
            state === 'pending' && 'text-gray-500',
          )}
        >
          {title}
        </div>
        <div className="mt-1 text-xs text-gray-600">{desc}</div>
      </div>
    </div>
  );
}

// ============================================
// 主组件
// ============================================

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-gray-400 mb-1 block">{label}</span>
      {children}
    </label>
  );
}

// ============================================
// 统计行
// ============================================
export function StatRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex justify-between items-center py-0.5">
      <span className="text-xs text-gray-500">{label}</span>
      <span className={clsx('text-xs font-medium', color || 'text-white')}>{value}</span>
    </div>
  );
}

export function MiniMetric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div className={clsx('text-[11px] font-bold tabular-nums', color || 'text-white')}>
        {value}
      </div>
      <div className="mt-1 text-xs font-medium text-gray-500">{label}</div>
    </div>
  );
}
