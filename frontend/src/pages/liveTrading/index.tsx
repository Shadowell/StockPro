import { lazy, Suspense, useState, useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { FlaskConical, Radio } from 'lucide-react';
import clsx from 'clsx';
import { liveApi, monitorApi, paperApi, tradingApi } from '../../api/client';
import { useStore } from '../../stores/useStore';
import { useAuth } from '../../auth/AuthProvider';
import ThemeDialog from '../../components/ThemeDialog';
import type {
  Balance,
  AssetClassFilter,
  ConfirmTone,
  CreateStep,
  DashboardData,
  InstanceListView,
  InstanceSortMode,
  PageView,
  PromotionCandidate,
  StrategyInfo,
  TradeMode,
  TradingInstance,
} from './types';
import { ENGINE_SESSION_ID, paperInstanceKey, toLiveApiInstanceId } from './types';
import {
  DEFAULT_LIVE_CONFIG,
  DEFAULT_PAPER_INITIAL_EQUITY,
  DEFAULT_PAPER_TIMEFRAME,
  formatStrategySymbolScope,
  isAiAutonomousStrategy,
  isSuperPnLUniverseStrategy,
  loadLivePrefs,
  LIVE_PREFS_KEY,
  paperQuickVerifyDaysBack,
  type LivePrefsStored,
} from './constants';
import InstanceDashboard from './InstanceDashboard';
import CreateWizard from './CreateWizard';
import LiveExecutionCenter from './LiveExecutionCenter';
import PromotionPipelineDialog, {
  type PromotionPipelineAccount,
  type PromotionPipelineCheck,
  type PromotionPipelineState,
} from './PromotionPipelineDialog';
import type { PaperPositionCloseRequest } from './InstanceMonitor';
import { togglePreferredStrategy } from './preferredStrategy';

let instanceMonitorPromise: Promise<typeof import('./InstanceMonitor')> | null = null;
let watchKlineChartPromise: Promise<typeof import('../../components/WatchKlineChart')> | null = null;

const preloadWatchKlineChart = () => {
  if (!watchKlineChartPromise) {
    watchKlineChartPromise = import('../../components/WatchKlineChart');
  }
  return watchKlineChartPromise;
};

const loadInstanceMonitor = () => {
  if (!instanceMonitorPromise) {
    instanceMonitorPromise = import('./InstanceMonitor');
    void preloadWatchKlineChart();
  }
  return instanceMonitorPromise;
};

const InstanceMonitor = lazy(loadInstanceMonitor);

const ACTIVE_INSTANCE_STATUSES = new Set(['running', 'paused']);
const DASHBOARD_LIST_REFRESH_INTERVAL_MS = 60_000;
const INSTANCE_FAVORITES_STORAGE_KEY = 'bitpro_live_instance_favorites_v1';
const AUTO_PREFERRED_DISMISSED_STORAGE_KEY =
  'bitpro_live_auto_preferred_dismissed_v1';
const AUTO_PREFERRED_RETURN_THRESHOLD_PCT = 5;
type ConcreteAssetClass = Exclude<AssetClassFilter, 'all'>;
type MetricRefreshTarget = Pick<
  TradingInstance,
  | 'id'
  | 'dryRun'
  | 'totalPnl'
  | 'totalReturnPct'
  | 'winRate'
  | 'profitFactor'
  | 'sharpeRatio'
  | 'maxDrawdownPct'
>;

function normalizeInstanceStatus(source: any): string {
  const raw = String(source?.status ?? source?.state ?? '').toLowerCase();
  return raw || 'stopped';
}

function loadFavoriteInstanceIds(): Set<string> {
  if (typeof window === 'undefined') return new Set();
  try {
    const raw = window.localStorage.getItem(INSTANCE_FAVORITES_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return new Set(
      Array.isArray(parsed)
        ? parsed.map((value) => String(value)).filter(Boolean)
        : [],
    );
  } catch {
    return new Set();
  }
}

function saveFavoriteInstanceIds(ids: Set<string>) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(INSTANCE_FAVORITES_STORAGE_KEY, JSON.stringify([...ids]));
  } catch {
    /* 浏览器禁用本地存储时仍保留当前会话状态。 */
  }
}

function loadDismissedAutoPreferredInstanceIds(): Set<string> {
  if (typeof window === 'undefined') return new Set();
  try {
    const raw = window.localStorage.getItem(AUTO_PREFERRED_DISMISSED_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return new Set(
      Array.isArray(parsed)
        ? parsed.map((value) => String(value)).filter(Boolean)
        : [],
    );
  } catch {
    return new Set();
  }
}

function saveDismissedAutoPreferredInstanceIds(ids: Set<string>) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(
      AUTO_PREFERRED_DISMISSED_STORAGE_KEY,
      JSON.stringify([...ids]),
    );
  } catch {
    /* 浏览器禁用本地存储时仍保留当前会话状态。 */
  }
}

function strategySymbol(strategy: StrategyInfo, cfg: Record<string, unknown>): string {
  return formatStrategySymbolScope({ ...strategy, config: cfg });
}

function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  if (typeof value === 'string' && value.trim()) {
    try {
      const parsed = JSON.parse(value);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : {};
    } catch {
      return {};
    }
  }
  return {};
}

function optionalText(value: unknown): string | null {
  if (value == null) return null;
  const text = String(value).trim();
  return text || null;
}

function timestampMs(value?: string | null): number {
  if (!value) return 0;
  const ts = Date.parse(value);
  return Number.isFinite(ts) ? ts : 0;
}

function numericInstanceRank(inst: TradingInstance): number {
  const strategyId = Number(inst.strategyId);
  if (Number.isFinite(strategyId)) return strategyId;
  const match = inst.id.match(/(\d+)$/);
  return match ? Number(match[1]) : 0;
}

function compareNewestInstanceFirst(a: TradingInstance, b: TradingInstance): number {
  const createdDiff = timestampMs(b.createdAt) - timestampMs(a.createdAt);
  if (createdDiff) return createdDiff;
  const rankDiff = numericInstanceRank(b) - numericInstanceRank(a);
  if (rankDiff) return rankDiff;
  return a.name.localeCompare(b.name, 'zh-Hans-CN');
}

function compareOldestInstanceFirst(a: TradingInstance, b: TradingInstance): number {
  const createdDiff = timestampMs(a.createdAt) - timestampMs(b.createdAt);
  if (createdDiff) return createdDiff;
  const rankDiff = numericInstanceRank(a) - numericInstanceRank(b);
  if (rankDiff) return rankDiff;
  return a.name.localeCompare(b.name, 'zh-Hans-CN');
}

function compareReturnRate(a: TradingInstance, b: TradingInstance, direction: 'asc' | 'desc'): number {
  const aHasReturn = Number.isFinite(a.totalReturnPct);
  const bHasReturn = Number.isFinite(b.totalReturnPct);
  if (aHasReturn !== bHasReturn) return aHasReturn ? -1 : 1;
  if (aHasReturn && bHasReturn) {
    const diff =
      direction === 'asc'
        ? Number(a.totalReturnPct) - Number(b.totalReturnPct)
        : Number(b.totalReturnPct) - Number(a.totalReturnPct);
    if (diff) return diff;
  }
  return compareNewestInstanceFirst(a, b);
}

function compareInstanceMetric(
  a: TradingInstance,
  b: TradingInstance,
  key: 'sharpeRatio' | 'winRate' | 'profitFactor',
  direction: 'asc' | 'desc',
): number {
  const aValue = a[key];
  const bValue = b[key];
  const aHasValue = Number.isFinite(aValue);
  const bHasValue = Number.isFinite(bValue);
  if (aHasValue !== bHasValue) return aHasValue ? -1 : 1;
  if (aHasValue && bHasValue) {
    const diff =
      direction === 'asc'
        ? Number(aValue) - Number(bValue)
        : Number(bValue) - Number(aValue);
    if (diff) return diff;
  }
  return compareNewestInstanceFirst(a, b);
}

function compareInstancesBySortMode(sortMode: InstanceSortMode) {
  return (a: TradingInstance, b: TradingInstance) => {
    if (sortMode === 'created_asc') return compareOldestInstanceFirst(a, b);
    if (sortMode === 'return_desc') return compareReturnRate(a, b, 'desc');
    if (sortMode === 'return_asc') return compareReturnRate(a, b, 'asc');
    if (sortMode === 'sharpe_desc') return compareInstanceMetric(a, b, 'sharpeRatio', 'desc');
    if (sortMode === 'sharpe_asc') return compareInstanceMetric(a, b, 'sharpeRatio', 'asc');
    if (sortMode === 'win_rate_desc') return compareInstanceMetric(a, b, 'winRate', 'desc');
    if (sortMode === 'win_rate_asc') return compareInstanceMetric(a, b, 'winRate', 'asc');
    if (sortMode === 'profit_factor_desc')
      return compareInstanceMetric(a, b, 'profitFactor', 'desc');
    if (sortMode === 'profit_factor_asc')
      return compareInstanceMetric(a, b, 'profitFactor', 'asc');
    return compareNewestInstanceFirst(a, b);
  };
}

function inferAssetClass(source: {
  name?: unknown;
  symbol?: unknown;
  symbols?: unknown;
  config?: unknown;
  marketType?: unknown;
  market_type?: unknown;
  instType?: unknown;
  inst_type?: unknown;
}): ConcreteAssetClass {
  const cfg = asRecord(source.config);
  return String(cfg.assetClass ?? cfg.asset_class ?? '').toLowerCase() === 'etf' ? 'etf' : 'stock';
}

function resolveInstanceLeverage(cfg: Record<string, unknown>): number | undefined {
  const candidates = [
    cfg.leverage,
    cfg.default_leverage,
    cfg.decision_leverage,
    cfg.default_decision_leverage,
    cfg.max_leverage,
    cfg.maxLeverage,
    cfg.max_leverage_cap,
  ];
  for (const candidate of candidates) {
    const value = finiteNumber(candidate, NaN);
    if (Number.isFinite(value) && value > 0) return value;
  }
  return undefined;
}

function buildTradingInstances(strategies: StrategyInfo[]): TradingInstance[] {
  const out: TradingInstance[] = [];

  // 僵尸 /paper-trading/instances 数据源已移除（恒空，见组件内说明）；
  // 实例卡片全部由 strategies（live:strategy:*）组装。

  for (const s of strategies) {
    const status = normalizeInstanceStatus(s);
    if (!ACTIVE_INSTANCE_STATUSES.has(status)) continue;
    const sid = Number(s.id);
    const cfg = asRecord(s.config);
    const dryRun = (cfg as { is_paper_trading?: boolean }).is_paper_trading !== false;
    out.push({
      id: `live:strategy:${sid}`,
      kind: 'live',
      dryRun,
      strategyId: sid,
      assetClass: inferAssetClass({
        name: s.name,
        symbol: s.symbol,
        symbols: s.symbols,
        config: cfg,
      }),
      name: s.name || `策略 #${sid}`,
      symbol: strategySymbol(s, cfg),
      timeframe: String(cfg.timeframe ?? s.timeframe ?? '—'),
      status,
      createdAt: optionalText(s.createdAt ?? s.created_at),
      strategyType: optionalText(cfg.strategy_type ?? cfg.strategyType),
      strategyKey: optionalText(cfg.strategy_key ?? cfg.strategyKey),
      isAiAutonomous: isAiAutonomousStrategy({ name: s.name, config: cfg }),
      capitalVersion: finiteNumber(cfg.initial_capital ?? s.initialCapital ?? s.initial_capital, NaN),
      leverage: resolveInstanceLeverage(cfg),
      totalPnl: undefined,
      totalReturnPct: undefined,
      sharpeRatio: undefined,
      maxDrawdownPct: undefined,
      stopKind: 'strategy',
    });
  }

  return out;
}

function finiteNumber(value: unknown, fallback = 0): number {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function normalizeStrategyTradesResponse(payload: unknown): any[] {
  if (Array.isArray(payload)) return payload;
  const record = asRecord(payload);
  const candidates = [record.data, record.trades, record.items, record.results];
  for (const candidate of candidates) {
    if (Array.isArray(candidate)) return candidate;
    const nested = asRecord(candidate);
    for (const nestedCandidate of [nested.data, nested.trades, nested.items, nested.results]) {
      if (Array.isArray(nestedCandidate)) return nestedCandidate;
    }
  }
  return [];
}

function dashboardHasRecordedTrades(dashboard: unknown): boolean {
  const dash = asRecord(dashboard);
  const performance = asRecord(dash.performance);
  return finiteNumber(performance.totalTrades ?? performance.total_trades, 0) > 0;
}

function strategyRuntimeDefaults(strategy?: StrategyInfo | null): {
  timeframe?: string;
  initialEquity?: number;
  loopInterval?: number;
} {
  if (!strategy) return {};
  const cfg = asRecord(strategy.config);
  const timeframe = String(cfg.timeframe ?? strategy.timeframe ?? '').trim();
  const initialEquity = finiteNumber(
    cfg.initial_capital ?? cfg.initialCapital ?? strategy.initialCapital ?? strategy.initial_capital,
    NaN,
  );
  const loopInterval = finiteNumber(cfg.loop_interval_sec ?? cfg.loopInterval, NaN);
  return {
    timeframe: timeframe || undefined,
    initialEquity: Number.isFinite(initialEquity) && initialEquity > 0 ? initialEquity : undefined,
    loopInterval: Number.isFinite(loopInterval) ? loopInterval : undefined,
  };
}

function normalizePipelineChecks(raw: unknown): PromotionPipelineCheck[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item: any) => ({
    item: String(item?.item || '检查项'),
    passed: Boolean(item?.passed),
    detail: item?.detail == null ? null : String(item.detail),
    account: normalizePipelineAccount(item?.account),
  }));
}

function normalizePipelineAccount(raw: unknown): PromotionPipelineAccount | null {
  if (!raw || typeof raw !== 'object') return null;
  const item = raw as Record<string, unknown>;
  const freeUsdt = finiteNumber(item.freeUsdt ?? item.free_usdt, NaN);
  const totalUsdt = finiteNumber(item.totalUsdt ?? item.total_usdt, NaN);
  const usedUsdt = finiteNumber(item.usedUsdt ?? item.used_usdt, NaN);
  return {
    freeUsdt: Number.isFinite(freeUsdt) ? freeUsdt : null,
    totalUsdt: Number.isFinite(totalUsdt) ? totalUsdt : null,
    usedUsdt: Number.isFinite(usedUsdt) ? usedUsdt : null,
    exchange: item.exchange == null ? undefined : String(item.exchange),
    currency: item.currency == null ? undefined : String(item.currency),
  };
}

function dashboardMetrics(dash: DashboardData | null | undefined): Partial<TradingInstance> {
  if (!dash) return {};
  const equityChangePct = finiteNumber(dash.equity?.changePct, 0);
  const pnlPct = finiteNumber(dash.performance?.totalPnlPct, equityChangePct);
  const dashSymbols = Array.isArray(dash.system?.symbols) ? dash.system.symbols : [];
  const symbolLabel =
    dashSymbols.length > 0
      ? formatStrategySymbolScope({
          id: dash.system?.strategyId ?? '',
          name: dash.system?.strategy || '',
          description: '',
          symbols: dashSymbols,
          config: {},
        })
      : dash.system?.symbol || undefined;
  const metrics: Partial<TradingInstance> = {
    totalPnl: finiteNumber(dash.performance?.totalPnl, finiteNumber(dash.equity?.change, 0)),
    totalReturnPct: pnlPct,
    winRate: finiteNumber(dash.performance?.winRate, 0),
    profitFactor: finiteNumber(dash.performance?.profitFactor, 0),
    sharpeRatio: finiteNumber(dash.performance?.sharpeRatio, 0),
    maxDrawdownPct: finiteNumber(
      dash.performance?.maxDrawdown,
      finiteNumber(dash.risk?.currentDrawdown, 0),
    ),
    totalTrades: finiteNumber(dash.performance?.totalTrades, 0),
  };
  const timeframe = String(dash.system?.timeframe ?? '').trim();
  const status = String(dash.system?.state ?? '').trim();
  if (symbolLabel) metrics.symbol = symbolLabel;
  if (timeframe) metrics.timeframe = timeframe;
  if (status) metrics.status = status;
  return metrics;
}

function metricsFromRunningStrategyStatus(status: any): Partial<TradingInstance> {
  const symbols = Array.isArray(status?.symbols) ? status.symbols.map((item: unknown) => String(item || '')).filter(Boolean) : [];
  const symbolLabel =
    symbols.length > 0
      ? formatStrategySymbolScope({
          id: status?.strategyId ?? status?.strategy_id ?? '',
          name: status?.name || '',
          description: '',
          symbols,
          config: {},
        })
      : undefined;
  return {
    symbol: symbolLabel,
    status: normalizeInstanceStatus(status),
    totalPnl: finiteNumber(status?.pnl ?? status?.totalPnl ?? status?.total_pnl, 0),
    totalReturnPct: finiteNumber(status?.returnPct ?? status?.return_pct, 0),
    winRate: finiteNumber(status?.winRate ?? status?.win_rate, 0),
    profitFactor: finiteNumber(status?.profitFactor ?? status?.profit_factor, 0),
    sharpeRatio: finiteNumber(status?.sharpeRatio ?? status?.sharpe_ratio, 0),
    totalTrades: finiteNumber(status?.totalTrades ?? status?.total_trades, 0),
  };
}

function strategyIdFromInstanceId(activeInstanceId: string | null): number | null {
  if (!activeInstanceId?.startsWith('live:strategy:')) return null;
  const n = Number(activeInstanceId.replace('live:strategy:', ''));
  return Number.isFinite(n) && n > 0 ? n : null;
}

function strategyIdFromSearchParams(searchParams: URLSearchParams): number | null {
  const sidRaw =
    searchParams.get('strategyId') ??
    searchParams.get('strategy_id') ??
    searchParams.get('instance_id') ??
    searchParams.get('instanceId');
  if (!sidRaw) return null;
  const sid = Number(sidRaw);
  return Number.isFinite(sid) && sid > 0 ? sid : null;
}

function deleteStrategyIdSearchParams(searchParams: URLSearchParams) {
  searchParams.delete('mode');
  searchParams.delete('strategyId');
  searchParams.delete('strategy_id');
  searchParams.delete('instance_id');
  searchParams.delete('instanceId');
}

async function loadAllStrategies() {
  const result = await liveApi.getPaperInstances();
  return Array.isArray(result?.items) ? result.items : [];
}

function dashboardMatchesInstance(
  dash: DashboardData | null | undefined,
  activeInstanceId: string | null,
): dash is DashboardData {
  if (!dash || !activeInstanceId) return false;
  const sid = strategyIdFromInstanceId(activeInstanceId);
  if (sid != null) return Number(dash.system?.strategyId) === sid;
  if (activeInstanceId === ENGINE_SESSION_ID) return true;
  return false;
}

function LiveTradingWorkspace({ modeScope }: { modeScope?: TradeMode }) {
  const [initialPrefs] = useState<LivePrefsStored | null>(() => loadLivePrefs());
  const { isAdmin } = useAuth();
  const readOnly = !isAdmin;
  const { selectedExchange, setSelectedExchange } = useStore();

  useLayoutEffect(() => {
    const ex = initialPrefs?.exchange;
    if (ex && typeof ex === 'string') setSelectedExchange(ex);
  }, [initialPrefs, setSelectedExchange]);

  const [view, setView] = useState<PageView>(() => initialPrefs?.view ?? 'dashboard');
  const [createStep, setCreateStep] = useState<CreateStep>(
    () => initialPrefs?.createStep ?? 'select',
  );
  const [activeInstanceId, setActiveInstanceId] = useState<string | null>(
    () => initialPrefs?.activeInstanceId ?? null,
  );

  useEffect(() => {
    void loadInstanceMonitor();
  }, []);

  useEffect(() => {
    if (readOnly && view === 'create') {
      setView('dashboard');
      setCreateStep('select');
    }
  }, [readOnly, view]);

  const [tradeModeState, setTradeModeState] = useState<TradeMode>(() =>
    modeScope ?? (initialPrefs?.tradeMode === 'live' ? 'live' : 'paper'),
  );
  const tradeMode = modeScope ?? tradeModeState;

  const [searchParams, setSearchParams] = useSearchParams();

  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<string | number>(
    () => initialPrefs?.selectedStrategy ?? '',
  );
  const [assetClassFilter, setAssetClassFilter] = useState<AssetClassFilter>(
    () => initialPrefs?.assetClassFilter ?? 'all',
  );
  const [instanceSortMode, setInstanceSortMode] = useState<InstanceSortMode>('return_desc');
  const [instanceListView, setInstanceListView] = useState<InstanceListView>('all');
  const [favoriteInstanceIds, setFavoriteInstanceIds] = useState<Set<string>>(
    loadFavoriteInstanceIds,
  );
  const [dismissedAutoPreferredInstanceIds, setDismissedAutoPreferredInstanceIds] =
    useState<Set<string>>(loadDismissedAutoPreferredInstanceIds);
  const [loading, setLoading] = useState(false);
  const [paperAdvanceBusy, setPaperAdvanceBusy] = useState(false);

  const [config, setConfig] = useState(() => {
    const mode: TradeMode =
      modeScope ?? (initialPrefs?.tradeMode === 'live' ? 'live' : 'paper');
    const defaultTf =
      mode === 'paper' ? DEFAULT_PAPER_TIMEFRAME : DEFAULT_LIVE_CONFIG.timeframe;
    const defaultInitialEquity =
      mode === 'paper' ? DEFAULT_PAPER_INITIAL_EQUITY : DEFAULT_LIVE_CONFIG.initialEquity;
    const saved =
      !modeScope && initialPrefs?.config && typeof initialPrefs.config === 'object'
        ? initialPrefs.config
        : {};
    return {
      ...DEFAULT_LIVE_CONFIG,
      timeframe: defaultTf,
      initialEquity: defaultInitialEquity,
      ...saved,
    };
  });

  const [balances, setBalances] = useState<Balance[]>([]);
  const [balanceLoading, setBalanceLoading] = useState(false);

  const [preflightResult, setPreflightResult] = useState<any>(null);
  const [preflightLoading, setPreflightLoading] = useState(false);

  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [engineSnapshot, setEngineSnapshot] = useState<DashboardData | null>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [trades, setTrades] = useState<any[]>([]);
  const [equityCurve, setEquityCurve] = useState<any[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [isPaused, setIsPaused] = useState(false);

  const [paperResult, setPaperResult] = useState<any>(null);
  const [paperLoading, setPaperLoading] = useState(false);
  const [paperCandidates, setPaperCandidates] = useState<StrategyInfo[]>([]);
  // /paper-trading/instances 僵尸 API 已移除（生产 review 2026-08-24）：该端点基于
  // 永远为空的内存列表，重启后恒为空且 getInstance 全部 404。模拟盘实例列表真实
  // 来源是 strategies（live:strategy:*）。props 链暂保留空数组以维持子组件编译，
  // UI 死分支留待后续清理切片拆除。
  const paperInstances: any[] = [];
  const paperDetail: any | null = null;
  const [instanceMetrics, setInstanceMetrics] = useState<Record<string, Partial<TradingInstance>>>({});
  const [promotionPipeline, setPromotionPipeline] = useState<PromotionPipelineState | null>(null);
  const [promotionPreflightId, setPromotionPreflightId] = useState<number | null>(null);
  const [promotionConfirmingId, setPromotionConfirmingId] = useState<number | null>(null);
  const [promotionBusyId, setPromotionBusyId] = useState<number | null>(null);

  /** 进入某实例详情后，首次成功拉取仪表盘时与顶部「模拟/实盘」对齐 */
  const detailTradeModeSyncedForRef = useRef<string | null>(null);
  const syncedStrategyDefaultsRef = useRef<string | null>(null);
  const dashboardListRefreshInFlightRef = useRef(false);

  const [showLiveConfirm, setShowLiveConfirm] = useState(false);
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean;
    title: string;
    content: string;
    confirmText?: string;
    tone?: ConfirmTone;
    isAlert?: boolean;
    onConfirm?: () => void | Promise<void>;
  }>({
    open: false,
    title: '',
    content: '',
    confirmText: '确定',
    tone: 'default',
    isAlert: false,
  });
  const [stopDialogOpen, setStopDialogOpen] = useState(false);

  const isDryRun = tradeMode === 'paper';
  const canSwitchMode = !modeScope;
  const creatableStrategies = useMemo(
    () => isDryRun ? paperCandidates : strategies,
    [isDryRun, paperCandidates, strategies],
  );
  const selectedStrategyInfo = useMemo(
    () => creatableStrategies.find((s) => String(s.id) === String(selectedStrategy)),
    [creatableStrategies, selectedStrategy],
  );
  const selectedStrategyRuntime = useMemo(
    () => strategyRuntimeDefaults(selectedStrategyInfo),
    [selectedStrategyInfo],
  );
  const selectedStrategyTimeframe = selectedStrategyRuntime.timeframe || DEFAULT_PAPER_TIMEFRAME;

  const rawInstances = useMemo(
    () => buildTradingInstances(strategies),
    [strategies],
  );
  const metricRefreshTargets = useMemo<MetricRefreshTarget[]>(
    () =>
      rawInstances.map((inst) => ({
        id: inst.id,
        dryRun: inst.dryRun,
        totalPnl: inst.totalPnl,
        totalReturnPct: inst.totalReturnPct,
        winRate: inst.winRate,
        sharpeRatio: inst.sharpeRatio,
        maxDrawdownPct: inst.maxDrawdownPct,
      })),
    [rawInstances],
  );
  const metricRefreshSignature = useMemo(
    () => metricRefreshTargets.map((inst) => inst.id).join('|'),
    [metricRefreshTargets],
  );
  const metricRefreshTargetsRef = useRef<MetricRefreshTarget[]>([]);
  useEffect(() => {
    metricRefreshTargetsRef.current = metricRefreshTargets;
  }, [metricRefreshTargets]);
  const enrichedInstances = useMemo(
    () =>
      rawInstances.map((inst) => ({
        ...inst,
        ...(instanceMetrics[inst.id] || {}),
      })),
    [instanceMetrics, rawInstances],
  );
  /** 模拟：独立模拟实例 + 引擎里 is_paper_trading 的策略；实盘：仅真实下单的引擎策略 */
  const modeInstances = useMemo(
    () =>
      enrichedInstances.filter((i) => {
        const paperish = i.kind === 'paper' || i.dryRun !== false;
        return tradeMode === 'paper' ? paperish : i.kind === 'live' && i.dryRun === false;
      }),
    [enrichedInstances, tradeMode],
  );
  const automaticPreferredInstanceIds = useMemo(
    () =>
      new Set(
        modeInstances
          .filter(
            (instance) =>
              instance.totalReturnPct != null &&
              Number.isFinite(instance.totalReturnPct) &&
              instance.totalReturnPct > AUTO_PREFERRED_RETURN_THRESHOLD_PCT,
          )
          .map((instance) => instance.id),
      ),
    [modeInstances],
  );
  const autoPreferredInstanceIds = useMemo(
    () =>
      new Set(
        [...automaticPreferredInstanceIds].filter(
          (instanceId) => !dismissedAutoPreferredInstanceIds.has(instanceId),
        ),
      ),
    [automaticPreferredInstanceIds, dismissedAutoPreferredInstanceIds],
  );
  const preferredInstanceIds = useMemo(
    () => new Set([...favoriteInstanceIds, ...autoPreferredInstanceIds]),
    [autoPreferredInstanceIds, favoriteInstanceIds],
  );
  const favoriteInstancesCount = useMemo(
    () => modeInstances.filter((instance) => preferredInstanceIds.has(instance.id)).length,
    [modeInstances, preferredInstanceIds],
  );
  const viewModeInstances = useMemo(
    () =>
      instanceListView === 'favorites'
        ? modeInstances.filter((instance) => preferredInstanceIds.has(instance.id))
        : modeInstances,
    [instanceListView, modeInstances, preferredInstanceIds],
  );
  const assetClassCounts = useMemo(
    () => ({
      all: viewModeInstances.length,
      stock: viewModeInstances.filter((i) => i.assetClass === 'stock').length,
      etf: viewModeInstances.filter((i) => i.assetClass === 'etf').length,
    }),
    [viewModeInstances],
  );
  const instances = useMemo(
    () =>
      viewModeInstances
        .filter((i) => assetClassFilter === 'all' || i.assetClass === assetClassFilter)
        .slice()
        .sort(compareInstancesBySortMode(instanceSortMode)),
    [assetClassFilter, instanceSortMode, viewModeInstances],
  );
  const handleToggleFavoriteInstance = (instance: TradingInstance) => {
    const next = togglePreferredStrategy({
      instanceId: instance.id,
      automaticIds: automaticPreferredInstanceIds,
      dismissedAutomaticIds: dismissedAutoPreferredInstanceIds,
      favoriteIds: favoriteInstanceIds,
    });
    setFavoriteInstanceIds(next.favoriteIds);
    setDismissedAutoPreferredInstanceIds(next.dismissedAutomaticIds);
    saveFavoriteInstanceIds(next.favoriteIds);
    saveDismissedAutoPreferredInstanceIds(next.dismissedAutomaticIds);
  };

  const promotionCandidates: PromotionCandidate[] = useMemo(() => {
    return strategies
      .filter((strategy) => {
        const cfg =
          strategy.config && typeof strategy.config === 'object'
            ? (strategy.config as Record<string, unknown>)
            : {};
        const status = normalizeInstanceStatus(strategy);
        return (
          ACTIVE_INSTANCE_STATUSES.has(status) &&
          cfg.is_paper_trading !== false &&
          cfg.isPaperTrading !== false
        );
      })
      .map((strategy) => {
        const metrics = instanceMetrics[`live:strategy:${Number(strategy.id)}`] || {};
        const cfg =
          strategy.config && typeof strategy.config === 'object'
            ? (strategy.config as Record<string, unknown>)
            : {};
        return {
          strategy,
          status: normalizeInstanceStatus(strategy),
          returnPct: finiteNumber(metrics.totalReturnPct ?? strategy.backtest?.totalReturn, 0),
          sharpeRatio: finiteNumber(metrics.sharpeRatio ?? strategy.backtest?.sharpeRatio, 0),
          maxDrawdownPct: finiteNumber(
            metrics.maxDrawdownPct ?? strategy.backtest?.maxDrawdown,
            0,
          ),
          totalTrades: Number(
            cfg.total_trades ?? cfg.totalTrades ?? strategy.backtest?.totalTrades ?? 0,
          ),
        };
      })
      .sort((a, b) => {
        const activeScore = (status: string) => (ACTIVE_INSTANCE_STATUSES.has(status) ? 1 : 0);
        return activeScore(b.status) - activeScore(a.status) || (b.returnPct ?? 0) - (a.returnPct ?? 0);
      });
  }, [instanceMetrics, strategies]);

  useEffect(() => {
    if (modeScope && tradeModeState !== modeScope) {
      setTradeModeState(modeScope);
    }
  }, [modeScope, tradeModeState]);

  useEffect(() => {
    if (view !== 'create') return;
    if (creatableStrategies.length === 0) {
      if (selectedStrategy) setSelectedStrategy('');
      return;
    }
    const selectedStillCreatable = creatableStrategies.some(
      (strategy) => String(strategy.id) === String(selectedStrategy),
    );
    if (!selectedStillCreatable) {
      setSelectedStrategy(creatableStrategies[0].id);
    }
  }, [creatableStrategies, selectedStrategy, view]);

  useEffect(() => {
    if (view !== 'detail' || !activeInstanceId) return;
    if (modeInstances.some((i) => i.id === activeInstanceId)) return;
    const sid = strategyIdFromInstanceId(activeInstanceId);
    if (sid != null) {
      const strategy = strategies.find((s) => Number(s.id) === sid);
      if (strategy) {
        const cfg = asRecord(strategy.config);
        const targetMode =
          cfg.is_paper_trading === false || cfg.isPaperTrading === false ? 'live' : 'paper';
        if (!modeScope && tradeMode !== targetMode) {
          setTradeModeState(targetMode);
          return;
        }
      }
    }
    if (
      activeInstanceId === ENGINE_SESSION_ID &&
      tradeMode === 'live' &&
      !modeScope &&
      !engineSnapshot
    ) {
      return;
    }
    if (activeInstanceId.startsWith('live:strategy:') && strategies.length === 0) return;
    if (activeInstanceId.startsWith('paper:') && paperInstances.length === 0) {
      return;
    }
    setActiveInstanceId(null);
    setView('dashboard');
    setDashboard(null);
    setEquityCurve([]);
    setEvents([]);
    setTrades([]);
    setIsRunning(false);
    setIsPaused(false);
  }, [
    activeInstanceId,
    engineSnapshot,
    modeInstances,
    modeScope,
    paperInstances.length,
    strategies,
    strategies.length,
    tradeMode,
    view,
  ]);

  const detailHeadline = useMemo(() => {
    if (!activeInstanceId) return '';
    const inst = rawInstances.find((i) => i.id === activeInstanceId);
    if (inst?.name) return inst.name;
    if (activeInstanceId === ENGINE_SESSION_ID) return '引擎会话';
    return '策略监控';
  }, [activeInstanceId, rawInstances]);

  const liveDetailDashboard = useMemo(
    () => (dashboardMatchesInstance(dashboard, activeInstanceId) ? dashboard : null),
    [activeInstanceId, dashboard],
  );

  const selectedRuntimeStrategy = useMemo(() => {
    const activeStrategyId = strategyIdFromInstanceId(activeInstanceId);
    const dashboardStrategyId = Number(liveDetailDashboard?.system?.strategyId);
    const sid =
      activeStrategyId ??
      (Number.isFinite(dashboardStrategyId) && dashboardStrategyId > 0
        ? dashboardStrategyId
        : null);
    if (sid == null) return null;
    return strategies.find((strategy) => Number(strategy.id) === sid) ?? null;
  }, [activeInstanceId, liveDetailDashboard?.system?.strategyId, strategies]);

  const openConfirmDialog = (opts: {
    title: string;
    content: string;
    confirmText?: string;
    tone?: ConfirmTone;
    onConfirm?: () => void | Promise<void>;
  }) => {
    setConfirmDialog({
      open: true,
      title: opts.title,
      content: opts.content,
      confirmText: opts.confirmText || '确定',
      tone: opts.tone || 'default',
      isAlert: false,
      onConfirm: opts.onConfirm,
    });
  };

  const openAlertDialog = (opts: {
    title: string;
    content: string;
    tone?: ConfirmTone;
  }) => {
    setConfirmDialog({
      open: true,
      title: opts.title,
      content: opts.content,
      confirmText: '我知道了',
      tone: opts.tone ?? 'danger',
      isAlert: true,
      onConfirm: () => {},
    });
  };

  const closeConfirmDialog = () => {
    setPromotionPreflightId(null);
    setPromotionConfirmingId(null);
    setConfirmDialog({
      open: false,
      title: '',
      content: '',
      confirmText: '确定',
      tone: 'default',
      isAlert: false,
    });
  };

  const closePromotionPipeline = () => {
    setPromotionPipeline(null);
    setPromotionPreflightId(null);
    setPromotionConfirmingId(null);
    setPromotionBusyId(null);
  };

  useEffect(() => {
    try {
      const payload: LivePrefsStored = {
        v: 2,
        tradeMode,
        view,
        createStep,
        selectedStrategy,
        assetClassFilter,
        config: { ...config },
        exchange: selectedExchange,
        activeInstanceId,
      };
      localStorage.setItem(LIVE_PREFS_KEY, JSON.stringify(payload));
    } catch {
      /* ignore */
    }
  }, [
    tradeMode,
    view,
    createStep,
    selectedStrategy,
    assetClassFilter,
    config,
    selectedExchange,
    activeInstanceId,
  ]);

  useEffect(() => {
    const key = String(selectedStrategy || '');
    if (!key || syncedStrategyDefaultsRef.current === key) return;
    const strategy = strategies.find((s) => String(s.id) === key);
    if (!strategy) return;

    const defaults = strategyRuntimeDefaults(strategy);
    setConfig((prev) => {
      const next = { ...prev };
      let changed = false;
      if (defaults.loopInterval != null && next.loopInterval !== defaults.loopInterval) {
        next.loopInterval = defaults.loopInterval;
        changed = true;
      }
      if (defaults.initialEquity != null && next.initialEquity !== defaults.initialEquity) {
        next.initialEquity = defaults.initialEquity;
        changed = true;
      }
      return changed ? next : prev;
    });
    syncedStrategyDefaultsRef.current = key;
    setPaperResult(null);
    setPreflightResult(null);
  }, [selectedStrategy, strategies]);

  /** 从策略中心等处跳转：/live?mode=paper&strategyId=123 → 打开该策略实例监控（兼容 instance_id 旧入口） */
  useEffect(() => {
    const sid = strategyIdFromSearchParams(searchParams);
    if (sid == null) return;

    void loadInstanceMonitor();
    const requestedMode = searchParams.get('mode');
    if (!modeScope && (requestedMode === 'paper' || requestedMode === 'live')) {
      setTradeModeState(requestedMode);
    }
    setSelectedStrategy(sid);
    setActiveInstanceId(`live:strategy:${sid}`);
    setView('detail');
    setDashboard(null);
    setEquityCurve([]);
    setEvents([]);
    setTrades([]);
  }, [modeScope, searchParams]);

  const loadStrategies = async () => {
    try {
      const [raw, candidates] = await Promise.all([loadAllStrategies(), liveApi.getPaperCandidates()]);
      const list: StrategyInfo[] = raw.map((s: any) => ({
        ...s,
        id: s.id ?? s.strategyId,
        name: s.name || `策略 #${s.id}`,
        description: s.description || '',
        riskLevel: s.riskLevel || s.risk_level,
        status: s.status || 'stopped',
        config: s.config,
        symbol: s.symbol,
        symbols: s.symbols,
        createdAt: s.createdAt ?? s.created_at ?? null,
      }));
      setStrategies(list);
      setPaperCandidates((Array.isArray(candidates) ? candidates : []).map((candidate: any) => ({
        id: candidate.strategyId,
        name: candidate.strategyName || `策略 #${candidate.strategyId}`,
        description: candidate.description || '已通过完整回测与 Paper 晋级门禁',
        status: 'not_started',
        timeframe: '1d',
        initialCapital: Number(candidate.initialCash || 1_000_000),
        config: {
          asset_class: 'stock',
          timeframe: '1d',
          initial_capital: Number(candidate.initialCash || 1_000_000),
          qualifying_backtest_run_id: candidate.qualifyingBacktestRunId,
          return_pct: candidate.returnPct,
          max_drawdown_pct: candidate.maxDrawdownPct,
          sharpe_ratio: candidate.sharpeRatio,
        },
      })));
    } catch (err) {
      console.error('加载策略列表失败:', err);
    }
  };

  const fetchBalance = async () => {
    setBalanceLoading(true);
    try {
      const payload = await tradingApi.getBalance(selectedExchange);
      setBalances(payload.balance || []);
    } catch (err) {
      console.error('获取余额失败:', err);
    } finally {
      setBalanceLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const refreshDashboardLists = async () => {
      if (cancelled || dashboardListRefreshInFlightRef.current) return;
      dashboardListRefreshInFlightRef.current = true;
      try {
        await Promise.all([loadStrategies()]);
      } finally {
        dashboardListRefreshInFlightRef.current = false;
      }
    };
    void refreshDashboardLists();
    const interval = setInterval(refreshDashboardLists, DASHBOARD_LIST_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (view !== 'dashboard') return;
    let cancelled = false;
    const refreshInstanceMetrics = async () => {
      const active = metricRefreshTargetsRef.current;
      if (active.length === 0) {
        if (!cancelled) setInstanceMetrics({});
        return;
      }
      const livePaperTargets = active.filter(
        (inst) => inst.id.startsWith('live:strategy:') && inst.dryRun !== false,
      );
      const runningStatusMetricsById = new Map<string, Partial<TradingInstance>>();
      if (livePaperTargets.length > 0) {
        try {
          const statuses = await monitorApi.getActiveStrategies();
          for (const status of statuses || []) {
            const strategyId = Number(status?.strategyId ?? status?.strategy_id);
            if (!Number.isFinite(strategyId) || strategyId <= 0) continue;
            runningStatusMetricsById.set(
              `live:strategy:${strategyId}`,
              metricsFromRunningStrategyStatus(status),
            );
          }
        } catch {
          // 批量指标失败时保留上一轮卡片指标，避免回退到空值。
        }
      }
      const entries = await Promise.all(
        active.map(async (inst) => {
          try {
            if (inst.id.startsWith('live:strategy:') && inst.dryRun !== false) {
              return [inst.id, runningStatusMetricsById.get(inst.id) || null] as const;
            }
            if (inst.id.startsWith('live:strategy:')) {
              const qid = toLiveApiInstanceId(inst.id);
              const dash = await liveApi.getDashboard(qid);
              return [inst.id, dashboardMetrics(dash)] as const;
            }
          } catch {
            // 卡片指标刷新失败时保留上一轮实时值，避免刷新时回落到 0 或空指标。
          }
          return [inst.id, null] as const;
        }),
      );
      if (cancelled) return;
      setInstanceMetrics((prev) => {
        const activeIds = new Set(active.map((inst) => inst.id));
        const next: Record<string, Partial<TradingInstance>> = {};
        for (const [id, metrics] of Object.entries(prev)) {
          if (activeIds.has(id)) next[id] = metrics;
        }
        for (const [id, metrics] of entries) {
          if (metrics) next[id] = { ...(next[id] || {}), ...metrics };
        }
        return next;
      });
    };

    refreshInstanceMetrics();
    const timer = setInterval(refreshInstanceMetrics, 10000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [metricRefreshSignature, view]);

  useEffect(() => {
    let cancel = false;
    const tick = async () => {
      try {
        const d = await liveApi.getDashboard();
        if (cancel) return;
        setEngineSnapshot(d);
      } catch {
        if (!cancel) {
          setEngineSnapshot(null);
        }
      }
    };
    tick();
    const t = setInterval(tick, 8000);
    return () => {
      cancel = true;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    if (tradeMode === 'live') fetchBalance();
  }, [tradeMode, selectedExchange]);

  useEffect(() => {
    detailTradeModeSyncedForRef.current = null;
  }, [activeInstanceId]);

  useEffect(() => {
    if (view !== 'detail' || !activeInstanceId) return;
    // paper:* 详情视图不可达（僵尸 API 已移除，实例列表只产生 live:strategy:*），
    // 原基于 /paper-trading/instances/{id} 的 10s 轮询分支一并移除。
    if (paperInstanceKey(activeInstanceId)) {
      if (detailTradeModeSyncedForRef.current !== activeInstanceId) {
        detailTradeModeSyncedForRef.current = activeInstanceId;
        if (!modeScope) setTradeModeState('paper');
      }
      setTrades([]);
      return;
    }

    const qid = toLiveApiInstanceId(activeInstanceId);
    setDashboard(null);
    setEvents([]);
    setTrades([]);
    setEquityCurve([]);
    setIsRunning(false);
    setIsPaused(false);
    let cancelled = false;
    const fetchLive = async () => {
      let dash: any = null;
      try {
        dash = await liveApi.getDashboard(qid);
        if (cancelled) return;
        setDashboard(dash);
        setInstanceMetrics((prev) => ({
          ...prev,
          [activeInstanceId]: dashboardMetrics(dash),
        }));
        if (detailTradeModeSyncedForRef.current !== activeInstanceId && dash?.system) {
          detailTradeModeSyncedForRef.current = activeInstanceId;
          const isPaper =
            dash.system.mode === 'paper' ||
            (dash.system.mode !== 'live' && dash.system.dryRun === true);
          if (!modeScope) setTradeModeState(isPaper ? 'paper' : 'live');
        }
        setIsRunning(dash?.system?.state === 'running');
        setIsPaused(dash?.system?.state === 'paused');
      } catch (err) {
        if (!cancelled) console.error('刷新仪表盘失败:', err);
        return;
      }

      try {
        const evts = await liveApi.getEvents(30, undefined, qid);
        if (cancelled) return;
        setEvents(Array.isArray(evts) ? evts : evts?.events || []);
      } catch (err) {
        if (!cancelled) {
          console.error('刷新策略事件失败:', err);
          setEvents([]);
        }
      }

      let sidTrades: number | undefined;
      if (activeInstanceId.startsWith('live:strategy:')) {
        const n = Number(activeInstanceId.replace('live:strategy:', ''));
        if (Number.isFinite(n)) sidTrades = n;
      }
      const sysSid = dash?.system?.strategyId;
      if (sidTrades == null && sysSid != null && Number.isFinite(Number(sysSid))) {
        sidTrades = Number(sysSid);
      }
      if (sidTrades != null) {
        try {
          const tr = await liveApi.getStrategyTrades(sidTrades, 100);
          if (cancelled) return;
          const normalizedTrades = normalizeStrategyTradesResponse(tr);
          setTrades((prev) =>
            normalizedTrades.length > 0 || !dashboardHasRecordedTrades(dash)
              ? normalizedTrades
              : prev,
          );
        } catch (err) {
          if (!cancelled && !dashboardHasRecordedTrades(dash)) setTrades([]);
          if (!cancelled) console.error('刷新策略成交失败:', err);
        }
      } else {
        if (!cancelled) setTrades([]);
      }

      try {
        const curve = await liveApi.getEquityCurve(qid);
        if (cancelled) return;
        if (Array.isArray(curve) && curve.length > 0) setEquityCurve(curve);
      } catch {
        /* ignore */
      }
    };
    fetchLive();
    const timer = setInterval(fetchLive, 10000);
    return () => {
      cancelled = true;
      clearInterval(timer);
      setTrades([]);
    };
  }, [view, activeInstanceId]);

  const handleModeChange = (mode: TradeMode) => {
    if (!canSwitchMode) return;
    setTradeModeState(mode);
    setPreflightResult(null);
    setPaperResult(null);
    if (view === 'detail') {
      setActiveInstanceId(null);
      setView('dashboard');
      setDashboard(null);
      setEquityCurve([]);
      setEvents([]);
      setTrades([]);
      setIsRunning(false);
      setIsPaused(false);
    }
  };

  const handleRunPaper = async () => {
    setPaperLoading(true);
    setPaperResult(null);
    try {
      const strategy = strategies.find((s) => String(s.id) === String(selectedStrategy));
      if (isSuperPnLUniverseStrategy(strategy)) {
        setPaperResult({
          error:
            '该策略依赖 Top20 实时币池批量预测，当前快捷验证是单币同步回测，不适合此策略；请进入飞行检查后启动模拟盘。',
        });
        return;
      }
      const res = await paperApi.run({
        strategy: String(selectedStrategy),
        exchange: selectedExchange,
        timeframe: selectedStrategyTimeframe,
        initial_capital: config.initialEquity,
        stop_loss: 0.05,
        days_back: paperQuickVerifyDaysBack(selectedStrategyTimeframe),
      });
      setPaperResult(res);
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      setPaperResult({ error: e?.response?.data?.detail || e?.message || '模拟盘失败' });
    } finally {
      setPaperLoading(false);
    }
  };

  const runPreFlight = async () => {
    setPreflightLoading(true);
    setPreflightResult(null);
    try {
      const res = await liveApi.preFlight({
        strategy: String(selectedStrategy),
        exchange: selectedExchange,
        dry_run: isDryRun,
        capital_pct: 0.1,
        total_capital: config.initialEquity,
      });
      setPreflightResult(res);
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      setPreflightResult({
        allPassed: false,
        all_passed: false,
        checks: [
          {
            item: '飞行检查执行失败',
            passed: false,
            detail: e?.response?.data?.detail || e?.message,
          },
        ],
      });
    } finally {
      setPreflightLoading(false);
    }
  };

  const handleLaunch = async () => {
    if (!isDryRun && !showLiveConfirm) {
      setShowLiveConfirm(true);
      return;
    }
    setShowLiveConfirm(false);
    setLoading(true);
    try {
      if (isDryRun) {
        const candidate = selectedStrategyInfo;
        const qualifyingBacktestRunId = String(asRecord(candidate?.config).qualifying_backtest_run_id || '');
        if (!candidate || !qualifyingBacktestRunId) {
          throw new Error('请选择已通过 Paper 晋级门禁的 A 股策略');
        }
        await liveApi.createPaperInstance({
          name: `${candidate.name} / Paper`,
          qualifyingBacktestRunId,
          initialCash: config.initialEquity,
          start: true,
        });
        setView('dashboard');
        setCreateStep('select');
        setPreflightResult(null);
        await loadStrategies();
        return;
      }
      await liveApi.configure({
        exchange: selectedExchange,
        strategy_type: String(selectedStrategy),
        initial_equity: config.initialEquity,
        dry_run: isDryRun,
        loop_interval: config.loopInterval,
        risk_config: {
          risk_per_trade_pct: config.riskPerTrade,
          max_daily_loss_pct: config.maxDailyLoss,
          max_total_loss_pct: config.maxTotalLoss,
        },
      });
      await liveApi.start();
      setIsRunning(true);
      setView('dashboard');
      setCreateStep('select');
      setPreflightResult(null);
      loadStrategies();
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      openAlertDialog({
        title: '启动失败',
        content: String(e?.response?.data?.detail || e?.message),
        tone: 'danger',
      });
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmPromotionDeployment = async () => {
    if (!promotionPipeline) return;
    const { sourceId, exchange, loopInterval, riskConfig } = promotionPipeline;

    setPromotionConfirmingId(null);
    setPromotionBusyId(sourceId);
    setPromotionPipeline((prev) => (prev ? { ...prev, phase: 'deploying', error: undefined } : prev));
    setLoading(true);
    try {
      const res = await liveApi.promoteToLive({
        sourceStrategyId: sourceId,
        exchange,
        loopInterval,
        startImmediately: true,
        confirmPaperReviewed: true,
        confirmLiveRisk: true,
        riskConfig,
      });
      if (!res.promoted) {
        const checks = normalizePipelineChecks(res.preflight?.checks);
        setPromotionPipeline((prev) =>
          prev
            ? {
                ...prev,
                phase: 'error',
                failedAt: 'deploy',
                checks,
                error: '实盘部署复检未通过，未创建或启动实盘策略。',
              }
            : prev,
        );
        return;
      }
      const liveId = Number(res.liveStrategyId);
      await loadStrategies();
      setTradeModeState('live');
      void loadInstanceMonitor();
      setActiveInstanceId(`live:strategy:${liveId}`);
      setView('detail');
      setDashboard(null);
      setEquityCurve([]);
      setEvents([]);
      setTrades([]);
      setPromotionPipeline((prev) => {
        const returnedInitial = finiteNumber(res.trial?.initialEquity, NaN);
        return prev
          ? {
              ...prev,
              phase: 'success',
              liveStrategyId: liveId,
              checks: normalizePipelineChecks(res.preflight?.checks),
              trialEquity: Number.isFinite(returnedInitial) ? returnedInitial : prev.trialEquity,
              account:
                normalizePipelineAccount(res.trial?.account ?? res.preflight?.account) ??
                prev.account,
              error: undefined,
            }
          : prev;
      });
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      setPromotionPipeline((prev) =>
        prev
          ? {
              ...prev,
              phase: 'error',
              failedAt: 'deploy',
              error: String(e?.response?.data?.detail || e?.message),
            }
          : prev,
      );
    } finally {
      setPromotionBusyId(null);
      setLoading(false);
    }
  };

  const handlePromoteToLive = async (candidate: PromotionCandidate) => {
    const sourceId = Number(candidate.strategy.id);
    if (!Number.isFinite(sourceId) || sourceId <= 0) {
      openAlertDialog({
        title: '无法部署实盘',
        content: '来源模拟策略 ID 无效，请刷新页面后重试。',
        tone: 'danger',
      });
      return;
    }
    const riskConfig = {
      riskPerTradePct: 0.005,
      maxDailyLossPct: 0.01,
      maxTotalLossPct: 0.03,
    };
    setPromotionPipeline({
      phase: 'preflight',
      sourceId,
      strategyName: candidate.strategy.name || `策略 #${sourceId}`,
      exchange: selectedExchange,
      trialEquity: null,
      account: null,
      loopInterval: config.loopInterval,
      riskConfig,
      checks: [],
    });
    setPromotionPreflightId(sourceId);
    setLoading(true);
    try {
      const preflight = await liveApi.promoteToLivePreflight({
        sourceStrategyId: sourceId,
        exchange: selectedExchange,
        loopInterval: config.loopInterval,
        startImmediately: true,
        riskConfig,
      });
      const checks = normalizePipelineChecks(preflight.checks);
      const account =
        normalizePipelineAccount(preflight.account ?? preflight.plan?.account) ??
        checks.find((check) => check.account)?.account ??
        null;
      const detectedEquity = finiteNumber(preflight.plan?.initialEquity, account?.freeUsdt ?? NaN);
      if (!(preflight.allPassed ?? preflight.all_passed)) {
        setPromotionPipeline((prev) =>
          prev
            ? {
                ...prev,
                phase: 'error',
                failedAt: 'preflight',
                checks,
                trialEquity: Number.isFinite(detectedEquity) ? detectedEquity : prev.trialEquity,
                account: account ?? prev.account,
                error: '策略暂不满足实盘部署条件，未创建实盘策略。',
              }
            : prev,
        );
        return;
      }
      setPromotionConfirmingId(sourceId);
      setPromotionPipeline((prev) =>
        prev
          ? {
              ...prev,
              phase: 'awaiting_confirmation',
              checks,
              trialEquity: Number.isFinite(detectedEquity) ? detectedEquity : prev.trialEquity,
              account: account ?? prev.account,
              error: undefined,
            }
          : prev,
      );
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      setPromotionPipeline((prev) =>
        prev
          ? {
              ...prev,
              phase: 'error',
              failedAt: 'preflight',
              error: String(e?.response?.data?.detail || e?.message),
            }
          : prev,
      );
    } finally {
      setPromotionPreflightId(null);
      setLoading(false);
    }
  };

  // 僵尸 API 已移除：paper:* 卡片不可达，以下 handler 仅保留签名兼容既有
  // props 链；后端端点与前端 client 方法已删除。
  const handleDeletePaper = async (_instanceId: string) => {
    if (readOnly) return;
    if (activeInstanceId === `paper:${_instanceId}`) {
      setActiveInstanceId(null);
      setView('dashboard');
    }
  };

  const handleClearAllPaper = async () => {
    if (readOnly) return;
  };

  const handleCardPausePaperTrading = (inst: TradingInstance) => {
    if (readOnly) return;
    const instanceId = toLiveApiInstanceId(inst.id);
    if (instanceId == null) {
      openAlertDialog({
        title: '操作失败',
        content: '当前模拟实例不支持暂停或继续交易。',
        tone: 'warning',
      });
      return;
    }
    const paused = inst.status === 'paused';
    openConfirmDialog({
      title: paused ? '继续模拟交易' : '暂停模拟交易',
      content: paused
        ? `确定要继续「${inst.name}」的模拟交易吗？`
        : `确定要暂停「${inst.name}」的模拟交易吗？暂停后保留收益曲线和历史指标。`,
      tone: paused ? 'default' : 'warning',
      confirmText: paused ? '继续交易' : '暂停交易',
      onConfirm: async () => {
        try {
          if (paused) {
            await liveApi.resume(instanceId);
          } else {
            await liveApi.pause(instanceId);
          }
          const nextStatus = paused ? 'running' : 'paused';
          setInstanceMetrics((prev) => ({
            ...prev,
            [inst.id]: { ...(prev[inst.id] || {}), status: nextStatus },
          }));
          if (activeInstanceId === inst.id) {
            setIsPaused(nextStatus === 'paused');
            setIsRunning(nextStatus === 'running');
          }
          loadStrategies();
        } catch (err: unknown) {
          const e = err as { response?: { data?: { detail?: string } }; message?: string };
          openAlertDialog({
            title: '操作失败',
            content: String(e?.response?.data?.detail || e?.message),
            tone: 'danger',
          });
        }
      },
    });
  };

  const handleCardStopPaperTrading = (inst: TradingInstance) => {
    if (readOnly) return;
    const instanceId = toLiveApiInstanceId(inst.id);
    if (instanceId == null) {
      openAlertDialog({
        title: '操作失败',
        content: '当前模拟实例不支持关闭交易。',
        tone: 'warning',
      });
      return;
    }
    openConfirmDialog({
      title: '关闭模拟交易',
      content: `确定要关闭「${inst.name}」的模拟交易吗？历史收益、成交和收益曲线会保留。`,
      tone: 'danger',
      confirmText: '关闭交易',
      onConfirm: async () => {
        try {
          await liveApi.stop(instanceId, false);
          setInstanceMetrics((prev) => {
            const next = { ...prev };
            delete next[inst.id];
            return next;
          });
          if (activeInstanceId === inst.id) {
            setView('dashboard');
            setActiveInstanceId(null);
            setIsRunning(false);
            setIsPaused(false);
          }
          loadStrategies();
        } catch (err: unknown) {
          const e = err as { response?: { data?: { detail?: string } }; message?: string };
          openAlertDialog({
            title: '关闭失败',
            content: String(e?.response?.data?.detail || e?.message),
            tone: 'danger',
          });
        }
      },
    });
  };

  const executeStop = async (clearMetrics: boolean) => {
    if (readOnly) return;
    try {
      if (!activeInstanceId) return;
      const stoppedId = activeInstanceId;
      await liveApi.stop(toLiveApiInstanceId(stoppedId), clearMetrics);
      setView('dashboard');
      setActiveInstanceId(null);
      setIsRunning(false);
      setIsPaused(false);
      if (clearMetrics) {
        setTrades([]);
        setEvents([]);
        setEquityCurve([]);
        setInstanceMetrics((prev) => {
          const next = { ...prev };
          delete next[stoppedId];
          return next;
        });
      }
      loadStrategies();
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      openAlertDialog({
        title: '停止失败',
        content: String(e?.response?.data?.detail || e?.message),
        tone: 'danger',
      });
    }
  };

  const handleMonitorStop = () => {
    if (readOnly) return;
    const pk = paperInstanceKey(activeInstanceId);
    if (pk) {
      openConfirmDialog({
        title: '删除模拟实例',
        content: '确定要从列表中移除此模拟实例吗？',
        tone: 'warning',
        confirmText: '删除',
        onConfirm: async () => {
          await handleDeletePaper(pk);
          setView('dashboard');
          setActiveInstanceId(null);
        },
      });
      return;
    }
    setStopDialogOpen(true);
  };

  const handlePauseResume = async () => {
    if (readOnly) return;
    const qid = activeInstanceId ? toLiveApiInstanceId(activeInstanceId) : undefined;
    try {
      const nextState = isPaused ? 'running' : 'paused';
      if (isPaused) {
        await liveApi.resume(qid);
      } else {
        await liveApi.pause(qid);
      }
      setIsPaused(nextState === 'paused');
      setIsRunning(nextState === 'running');
      setDashboard((prev) => {
        const base = prev ?? liveDetailDashboard;
        if (!base) return prev;
        return {
          ...base,
          system: {
            ...base.system,
            state: nextState,
          },
        };
      });
      if (activeInstanceId) {
        setInstanceMetrics((prev) => ({
          ...prev,
          [activeInstanceId]: { status: nextState },
        }));
      }
      loadStrategies();
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      openAlertDialog({
        title: '操作失败',
        content: String(e?.response?.data?.detail || e?.message),
        tone: 'danger',
      });
    }
  };

  const handleAdvancePaper = async () => {
    if (readOnly || !activeInstanceId || paperAdvanceBusy) return;
    const qid = toLiveApiInstanceId(activeInstanceId);
    if (qid == null) return;
    setPaperAdvanceBusy(true);
    try {
      const result = await liveApi.advance(qid, 1);
      const [dash, evts, curve, tradePayload] = await Promise.all([
        liveApi.getDashboard(qid),
        liveApi.getEvents(30, undefined, qid),
        liveApi.getEquityCurve(qid),
        liveApi.getStrategyTrades(Number(qid), 100),
      ]);
      setDashboard(dash);
      setEvents(Array.isArray(evts) ? evts : evts?.events || []);
      setEquityCurve(Array.isArray(curve) ? curve : []);
      setTrades(normalizeStrategyTradesResponse(tradePayload));
      await loadStrategies();
      openAlertDialog({
        title: result.processedDates?.length ? '周期推进完成' : '当前已到 sealed 快照末端',
        content: result.processedDates?.length
          ? `已处理 ${result.processedDates.join('、')}；信号 ${result.signalCount || 0}，订单 ${result.orderCount || 0}，成交 ${result.tradeCount || 0}。`
          : '没有新的 sealed 交易日，实例和全部历史保持不变。',
        tone: 'default',
      });
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      openAlertDialog({ title: '周期推进失败', content: String(e?.response?.data?.detail || e?.message), tone: 'danger' });
    } finally {
      setPaperAdvanceBusy(false);
    }
  };

  const handleClosePaperPosition = async (position: PaperPositionCloseRequest) => {
    if (readOnly) return;
    if (!activeInstanceId) {
      throw new Error('缺少模拟实例 ID');
    }
    const qid = toLiveApiInstanceId(activeInstanceId);
    if (qid == null) {
      throw new Error('当前实例不支持持仓平仓');
    }

    await liveApi.closePaperPosition({
      instanceId: qid,
      symbol: position.symbol,
      side: position.side,
      marketType: position.marketType,
    });

    const dash = await liveApi.getDashboard(qid);
    setDashboard(dash);
    setInstanceMetrics((prev) => ({
      ...prev,
      [activeInstanceId]: dashboardMetrics(dash),
    }));
    setIsRunning(dash?.system?.state === 'running');
    setIsPaused(dash?.system?.state === 'paused');

    const evts = await liveApi.getEvents(30, undefined, qid);
    setEvents(Array.isArray(evts) ? evts : evts?.events || []);

    const dashboardStrategyId = Number(dash?.system?.strategyId);
    const sid =
      strategyIdFromInstanceId(activeInstanceId) ??
      (Number.isFinite(dashboardStrategyId) && dashboardStrategyId > 0
        ? dashboardStrategyId
        : null);
    if (sid != null) {
      const latestTradesRaw = await liveApi.getStrategyTrades(sid, 100);
      const latestTrades = normalizeStrategyTradesResponse(latestTradesRaw);
      setTrades((prev) =>
        latestTrades.length > 0 || !dashboardHasRecordedTrades(dash)
          ? latestTrades
          : prev,
      );
    }

    try {
      const curve = await liveApi.getEquityCurve(qid);
      if (Array.isArray(curve) && curve.length > 0) {
        setEquityCurve(curve);
      }
    } catch {
      /* 平仓成功后权益曲线刷新失败不影响持仓状态 */
    }
  };

  const detailHydrating =
    view === 'detail' &&
    !!activeInstanceId &&
    (paperInstanceKey(activeInstanceId)
      ? paperDetail == null
      : liveDetailDashboard == null);

  return (
    <div className="p-6 h-full flex flex-col">
      <div className="flex items-start justify-between gap-4 mb-6">
        <div className="flex flex-col gap-1.5 min-w-0">
          {modeScope ? (
            <div
              className={clsx(
                'flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-semibold w-fit',
                tradeMode === 'live'
                  ? 'border-red-500/30 bg-red-500/10 text-red-300'
                  : 'border-yellow-500/30 bg-yellow-500/10 text-yellow-300',
              )}
            >
              {tradeMode === 'live' ? <Radio className="w-4 h-4" /> : <FlaskConical className="w-4 h-4" />}
              {tradeMode === 'live' ? '实盘部署' : '模拟盘'}
            </div>
          ) : (
            <div className="flex items-center bg-crypto-card border border-crypto-border rounded-xl p-1 w-fit">
              <button
                type="button"
                onClick={() => handleModeChange('paper')}
                className={clsx(
                  'flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all',
                  tradeMode === 'paper'
                    ? 'bg-yellow-500/20 text-yellow-400 shadow-sm'
                    : canSwitchMode
                      ? 'text-gray-500 hover:text-gray-300'
                      : 'text-gray-600 cursor-not-allowed',
                )}
                disabled={!canSwitchMode && tradeMode !== 'paper'}
              >
                <FlaskConical className="w-4 h-4" />
                模拟盘
              </button>
              <button
                type="button"
                onClick={() => handleModeChange('live')}
                className={clsx(
                  'flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all',
                  tradeMode === 'live'
                    ? 'bg-red-500/20 text-red-400 shadow-sm'
                    : canSwitchMode
                      ? 'text-gray-500 hover:text-gray-300'
                      : 'text-gray-600 cursor-not-allowed',
                )}
                disabled={!canSwitchMode && tradeMode !== 'live'}
              >
                <Radio className="w-4 h-4" />
                实盘
              </button>
            </div>
          )}
          <p className="text-[11px] text-gray-500 leading-snug max-w-lg">
            {tradeMode === 'paper'
              ? '模拟：只做 PaperBroker / 模拟成交，不触碰真实资金。'
              : '实盘：只展示真实下单策略；推荐从模拟盘克隆独立小资金实盘试运行。'}
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-500 shrink-0 pt-1">
          {view !== 'dashboard' && (
            <span className="px-2 py-1 bg-crypto-bg border border-crypto-border rounded-lg text-gray-400">
              {view === 'create' ? '创建向导' : '实例监控'}
            </span>
          )}
        </div>
      </div>

      {view === 'dashboard' && (
        <InstanceDashboard
          tradeMode={tradeMode}
          exchange={selectedExchange}
          balances={balances}
          balanceLoading={balanceLoading}
          instances={instances}
          instanceListView={instanceListView}
          totalInstancesCount={modeInstances.length}
          favoriteInstancesCount={favoriteInstancesCount}
          preferredInstanceIds={preferredInstanceIds}
          autoPreferredInstanceIds={autoPreferredInstanceIds}
          automaticPreferredInstanceIds={automaticPreferredInstanceIds}
          assetClassFilter={assetClassFilter}
          assetClassCounts={assetClassCounts}
          instanceSortMode={instanceSortMode}
          paperInstancesCount={paperInstances.length}
          promotionCandidates={tradeMode === 'live' ? promotionCandidates : []}
          promotionPreflightId={promotionPreflightId}
          promotionConfirmingId={promotionConfirmingId}
          promotionBusyId={promotionBusyId}
          readOnly={readOnly}
          onCreateClick={() => {
            if (readOnly) return;
            setView('create');
            setCreateStep('select');
          }}
          onAssetClassFilterChange={setAssetClassFilter}
          onInstanceListViewChange={setInstanceListView}
          onToggleFavoriteInstance={handleToggleFavoriteInstance}
          onInstanceSortModeChange={setInstanceSortMode}
          onOpenDetail={(inst) => {
            void loadInstanceMonitor();
            if (!modeScope) {
              setTradeModeState(
                inst.kind === 'paper' || inst.dryRun !== false ? 'paper' : 'live',
              );
            }
            setActiveInstanceId(inst.id);
            setView('detail');
            setDashboard(null);
            setEquityCurve([]);
            setEvents([]);
            setTrades([]);
          }}
          onPausePaperTrading={handleCardPausePaperTrading}
          onStopPaperTrading={handleCardStopPaperTrading}
          onDeletePaper={handleDeletePaper}
          onClearAllPaper={handleClearAllPaper}
          onPromoteToLive={handlePromoteToLive}
          openConfirmDialog={openConfirmDialog}
        />
      )}

      {view === 'create' && !readOnly && (
        <CreateWizard
          createStep={createStep}
          setCreateStep={setCreateStep}
          tradeMode={tradeMode}
          selectedExchange={selectedExchange}
          strategies={creatableStrategies}
          selectedStrategy={selectedStrategy}
          setSelectedStrategy={setSelectedStrategy}
          definedTimeframe={selectedStrategyTimeframe}
          config={config}
          setConfig={setConfig}
          balances={balances}
          balanceLoading={balanceLoading}
          paperInstances={paperInstances}
          onDeletePaper={handleDeletePaper}
          onClearAllPaper={() =>
            openConfirmDialog({
              title: '清空全部模拟实例',
              content: '确定要清空列表中的全部模拟盘实例吗？',
              tone: 'warning',
              confirmText: '清空',
              onConfirm: handleClearAllPaper,
            })
          }
          paperResult={paperResult}
          setPaperResult={setPaperResult}
          paperLoading={paperLoading}
          onRunPaper={handleRunPaper}
          preflightResult={preflightResult}
          preflightLoading={preflightLoading}
          onRunPreFlight={runPreFlight}
          showLiveConfirm={showLiveConfirm}
          setShowLiveConfirm={setShowLiveConfirm}
          launchLoading={loading}
          onLaunch={handleLaunch}
          onCancel={() => {
            setView('dashboard');
            setCreateStep('select');
            setPreflightResult(null);
            setShowLiveConfirm(false);
          }}
        />
      )}

      {detailHydrating && (
        <div className="min-h-[420px] rounded-2xl border border-crypto-border bg-crypto-card/60 flex items-center justify-center">
          <div className="text-center space-y-3">
            <div className="mx-auto h-8 w-8 rounded-full border-2 border-blue-500/30 border-t-blue-400 animate-spin" />
            <div className="text-sm font-medium text-gray-300">正在加载实例控制台</div>
            <div className="text-xs text-gray-600 font-mono">
              {activeInstanceId}
            </div>
          </div>
        </div>
      )}

      {view === 'detail' && activeInstanceId && !detailHydrating && (
        <Suspense
          fallback={
            <div className="min-h-[420px] rounded-2xl border border-crypto-border bg-crypto-card/60 flex items-center justify-center">
              <div className="text-center space-y-3">
                <div className="mx-auto h-8 w-8 rounded-full border-2 border-blue-500/30 border-t-blue-400 animate-spin" />
                <div className="text-sm font-medium text-gray-300">正在加载实例监控</div>
                <div className="text-xs text-gray-600 font-mono">{activeInstanceId}</div>
              </div>
            </div>
          }
        >
          <InstanceMonitor
            activeInstanceId={activeInstanceId}
            headlineTitle={detailHeadline}
            trades={trades}
            initialConfig={config}
            dashboard={liveDetailDashboard}
            strategyInfo={selectedRuntimeStrategy}
            events={events}
            equityCurve={equityCurve}
            isRunning={isRunning}
            isPaused={isPaused}
            paperDetail={paperDetail}
            readOnly={readOnly}
            wsExchange={selectedExchange}
            onBack={() => {
              const next = new URLSearchParams(searchParams);
              deleteStrategyIdSearchParams(next);
              setSearchParams(next, { replace: true });
              setView('dashboard');
              setActiveInstanceId(null);
              setTrades([]);
            }}
            onPauseResume={handlePauseResume}
            onStop={handleMonitorStop}
            onAdvance={handleAdvancePaper}
            advanceBusy={paperAdvanceBusy}
            onClosePosition={handleClosePaperPosition}
            onDeletePaper={
              paperInstanceKey(activeInstanceId)
                ? () =>
                    handleDeletePaper(paperInstanceKey(activeInstanceId)!).then(() => {
                      setView('dashboard');
                      setActiveInstanceId(null);
                    })
                : undefined
            }
          />
        </Suspense>
      )}

      {stopDialogOpen && (
        <ThemeDialog
          open
          variant="confirm"
          title="关闭交易"
          tone="warning"
          confirmText="关闭"
          cancelText="取消"
          onCancel={() => setStopDialogOpen(false)}
          onConfirm={async () => {
            setStopDialogOpen(false);
            await executeStop(false);
          }}
        >
          <div className="space-y-4 text-sm text-gray-300">
            <p>
              关闭会取消当前策略任务，不再产生新的交易。已有持仓不会因为关闭按钮自动卖出。
            </p>
            <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 p-3 text-xs leading-relaxed text-emerald-100">
              关闭只停止后续周期；当前现金、持仓、订单、成交、收益曲线、事件、运行游标和诊断历史全部保留。
            </div>
          </div>
        </ThemeDialog>
      )}

      {promotionPipeline && (
        <PromotionPipelineDialog
          state={promotionPipeline}
          onCancel={closePromotionPipeline}
          onConfirm={handleConfirmPromotionDeployment}
          onClose={closePromotionPipeline}
        />
      )}

      {confirmDialog.open &&
        (confirmDialog.isAlert ? (
          <ThemeDialog
            open
            variant="alert"
            title={confirmDialog.title}
            content={confirmDialog.content}
            tone={confirmDialog.tone}
            confirmText={confirmDialog.confirmText}
            onClose={closeConfirmDialog}
          />
        ) : (
          <ThemeDialog
            open
            variant="confirm"
            title={confirmDialog.title}
            content={confirmDialog.content}
            tone={confirmDialog.tone}
            confirmText={confirmDialog.confirmText}
            cancelText="取消"
            onCancel={closeConfirmDialog}
            onConfirm={async () => {
              const fn = confirmDialog.onConfirm;
              closeConfirmDialog();
              if (fn) await fn();
            }}
          />
        ))}
    </div>
  );
}

export default function LiveTrading({ modeScope }: { modeScope?: TradeMode }) {
  if (modeScope === 'live') {
    return <LiveExecutionCenter />;
  }
  return <LiveTradingWorkspace modeScope={modeScope} />;
}
