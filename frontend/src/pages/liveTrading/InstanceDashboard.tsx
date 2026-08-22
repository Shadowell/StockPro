import {
  Activity,
  ArrowDown,
  ArrowDownUp,
  ArrowUp,
  Eye,
  Loader2,
  PauseCircle,
  PlayCircle,
  Plus,
  Power,
  Rocket,
  Search,
  ShieldCheck,
  Star,
  Wallet,
  XCircle,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import clsx from 'clsx';
import SymbolIcon from '../../components/SymbolIcon';
import { formatTimeframeLabel } from '../../utils/timeframe';
import { formatStrategySymbolScope } from './constants';
import type {
  AssetClassFilter,
  Balance,
  InstanceListView,
  InstanceSortMode,
  PromotionCandidate,
  TradeMode,
  TradingInstance,
} from './types';

export interface InstanceDashboardProps {
  tradeMode: TradeMode;
  exchange: string;
  balances: Balance[];
  balanceLoading: boolean;
  instances: TradingInstance[];
  instanceListView: InstanceListView;
  totalInstancesCount: number;
  favoriteInstancesCount: number;
  preferredInstanceIds: ReadonlySet<string>;
  autoPreferredInstanceIds: ReadonlySet<string>;
  automaticPreferredInstanceIds: ReadonlySet<string>;
  assetClassFilter: AssetClassFilter;
  assetClassCounts: Record<AssetClassFilter, number>;
  instanceSortMode: InstanceSortMode;
  paperInstancesCount: number;
  promotionCandidates?: PromotionCandidate[];
  promotionPreflightId?: number | null;
  promotionConfirmingId?: number | null;
  promotionBusyId?: number | null;
  readOnly?: boolean;
  onCreateClick: () => void;
  onInstanceListViewChange: (view: InstanceListView) => void;
  onToggleFavoriteInstance: (inst: TradingInstance) => void;
  onAssetClassFilterChange: (filter: AssetClassFilter) => void;
  onInstanceSortModeChange: (mode: InstanceSortMode) => void;
  onOpenDetail: (inst: TradingInstance) => void;
  onPausePaperTrading: (inst: TradingInstance) => void;
  onStopPaperTrading: (inst: TradingInstance) => void;
  onPromoteToLive?: (candidate: PromotionCandidate) => void;
  onDeletePaper: (paperId: string) => void;
  onClearAllPaper: () => void;
  openConfirmDialog: (opts: {
    title: string;
    content: string;
    confirmText?: string;
    tone?: 'danger' | 'warning' | 'default';
    onConfirm?: () => void | Promise<void>;
  }) => void;
}

function formatSignedUsd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '--';
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

function formatSignedPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${value.toFixed(2)}%`;
}

function formatRatio(value: number | null | undefined): string {
  return value != null && Number.isFinite(value) && value >= 0 ? value.toFixed(2) : '--';
}

function formatSharpe(value: number | null | undefined): string {
  return value != null && Number.isFinite(value) ? value.toFixed(2) : '--';
}

function strategyNameColorClass(assetClass: TradingInstance['assetClass']): string {
  return assetClass === 'contract' ? 'text-[#FFAB73]' : 'text-yellow-300';
}

function normalizeInstanceSearchText(value: unknown): string {
  return String(value ?? '')
    .toLowerCase()
    .replace(/[\s\-_/：:·.,，。]+/g, '');
}

function instanceMatchesSearch(inst: TradingInstance, query: string): boolean {
  const tokens = query
    .split(/\s+/)
    .map(normalizeInstanceSearchText)
    .filter(Boolean);
  if (tokens.length === 0) return true;

  const assetClassLabel = inst.assetClass === 'contract' ? '合约' : '现货';
  const statusLabel =
    inst.status === 'running' ? '运行中' : inst.status === 'paused' ? '暂停' : inst.status;
  const haystack = normalizeInstanceSearchText(
    [
      inst.id,
      inst.name,
      inst.symbol,
      inst.strategyType,
      inst.strategyKey,
      inst.timeframe,
      inst.leverage ? `${inst.leverage}x` : '',
      inst.status,
      statusLabel,
      inst.assetClass,
      assetClassLabel,
    ].join(' '),
  );

  return tokens.every((token) => haystack.includes(token));
}

type StrategyTypeFilter = 'all' | 'cta' | 'martin' | 'ai' | 'market_making';
type KlineTimeframeFilter = 'all' | '1m' | '5m' | '15m' | '30m' | '1h' | '4h' | '12h' | '1d';
type CapitalVersionFilter = 'all' | '100u' | '1000u';
type LeverageFilter = 'all' | '1x' | '2x' | '3x' | '5x' | '10x' | '20x' | '50x';

function inferInstanceStrategyType(inst: TradingInstance): StrategyTypeFilter | 'other' {
  const normalized = normalizeInstanceSearchText(
    [inst.name, inst.symbol, inst.strategyType, inst.strategyKey].join(' '),
  );
  if (
    normalized.includes('做市') ||
    normalized.includes('marketmaking') ||
    normalized.includes('marketmaker')
  ) {
    return 'market_making';
  }
  if (inst.isAiAutonomous) return 'ai';
  if (normalized.includes('[ai]')) return 'ai';
  if (
    normalized.includes('马丁') ||
    normalized.includes('martin') ||
    normalized.includes('martingale')
  ) {
    return 'martin';
  }
  if (normalized.includes('cta') || normalized.includes('趋势跟踪')) {
    return 'cta';
  }
  return 'other';
}

function normalizeInstanceTimeframe(value: unknown): KlineTimeframeFilter | 'other' {
  const normalized = String(value ?? '').trim().toLowerCase().replace(/\s+/g, '');
  if (
    normalized === '1m' ||
    normalized === '5m' ||
    normalized === '15m' ||
    normalized === '30m' ||
    normalized === '1h' ||
    normalized === '4h' ||
    normalized === '12h' ||
    normalized === '1d'
  ) {
    return normalized;
  }
  return 'other';
}

function normalizeInstanceCapitalVersion(inst: TradingInstance): CapitalVersionFilter | 'other' {
  const capital = inst.capitalVersion;
  if (typeof capital === 'number' && Number.isFinite(capital)) {
    const rounded = Math.round(capital);
    if (rounded === 100) return '100u';
    if (rounded === 1000) return '1000u';
  }
  const match = String(inst.name || '').match(/(?:^|[·\s])(\d+(?:\.\d+)?)U(?:$|\s|[·#])/i);
  if (!match) return 'other';
  const parsed = Number(match[1]);
  if (!Number.isFinite(parsed)) return 'other';
  const rounded = Math.round(parsed);
  if (rounded === 100) return '100u';
  if (rounded === 1000) return '1000u';
  return 'other';
}

function normalizeInstanceLeverage(inst: TradingInstance): LeverageFilter | 'other' {
  if (inst.assetClass !== 'contract') return 'other';
  const leverage = inst.leverage;
  if (typeof leverage !== 'number' || !Number.isFinite(leverage) || leverage <= 0) {
    return 'other';
  }
  const rounded = Math.round(leverage);
  if (Math.abs(leverage - rounded) > 0.01) return 'other';
  if (rounded === 1) return '1x';
  if (rounded === 2) return '2x';
  if (rounded === 3) return '3x';
  if (rounded === 5) return '5x';
  if (rounded === 10) return '10x';
  if (rounded === 20) return '20x';
  if (rounded === 50) return '50x';
  return 'other';
}

function formatInstanceTimeframePill(value: unknown): string {
  const normalized = String(value ?? '').trim();
  if (!normalized) return '周期 --';
  const timeframe = normalizeInstanceTimeframe(normalized);
  return formatTimeframeLabel(timeframe === 'other' ? normalized : timeframe);
}

function formatInstanceCapitalVersionPill(inst: TradingInstance): string | null {
  const capital = inst.capitalVersion;
  if (typeof capital === 'number' && Number.isFinite(capital) && capital > 0) {
    return `${Math.round(capital)}U`;
  }
  const match = String(inst.name || '').match(/(?:^|[·\s])(\d+(?:\.\d+)?)U(?:$|\s|[·#])/i);
  if (!match) return null;
  const parsed = Number(match[1]);
  return Number.isFinite(parsed) && parsed > 0 ? `${Math.round(parsed)}U` : null;
}

function formatInstanceLeveragePill(inst: TradingInstance): string | null {
  if (inst.assetClass !== 'contract') return null;
  const leverage = inst.leverage;
  if (typeof leverage !== 'number' || !Number.isFinite(leverage) || leverage <= 0) return null;
  const rounded = Math.round(leverage);
  const display = Math.abs(leverage - rounded) < 0.01 ? String(rounded) : leverage.toFixed(2);
  const normalized = display.includes('.') ? display.replace(/\.?0+$/, '') : display;
  return `${normalized}X`;
}

type SortField = 'created' | 'return' | 'sharpe' | 'win_rate' | 'profit_factor';
type SortDirection = 'asc' | 'desc';

function sortDirectionFor(sortMode: InstanceSortMode, field: SortField): SortDirection | null {
  if (field === 'created') {
    if (sortMode === 'created_asc') return 'asc';
    if (sortMode === 'created_desc') return 'desc';
    return null;
  }
  if (field === 'return') {
    if (sortMode === 'return_asc') return 'asc';
    if (sortMode === 'return_desc') return 'desc';
    return null;
  }
  if (field === 'sharpe') {
    if (sortMode === 'sharpe_asc') return 'asc';
    if (sortMode === 'sharpe_desc') return 'desc';
    return null;
  }
  if (field === 'win_rate') {
    if (sortMode === 'win_rate_asc') return 'asc';
    if (sortMode === 'win_rate_desc') return 'desc';
    return null;
  }
  if (field === 'profit_factor') {
    if (sortMode === 'profit_factor_asc') return 'asc';
    if (sortMode === 'profit_factor_desc') return 'desc';
    return null;
  }
  return null;
}

function nextInstanceSortMode(sortMode: InstanceSortMode, field: SortField): InstanceSortMode {
  const currentDirection = sortDirectionFor(sortMode, field);
  if (field === 'created') {
    return currentDirection === 'desc' ? 'created_asc' : 'created_desc';
  }
  if (field === 'win_rate') {
    return currentDirection === 'desc' ? 'win_rate_asc' : 'win_rate_desc';
  }
  if (field === 'sharpe') {
    return currentDirection === 'desc' ? 'sharpe_asc' : 'sharpe_desc';
  }
  if (field === 'profit_factor') {
    return currentDirection === 'desc' ? 'profit_factor_asc' : 'profit_factor_desc';
  }
  return currentDirection === 'desc' ? 'return_asc' : 'return_desc';
}

function SortArrow({ direction }: { direction: SortDirection | null }) {
  if (direction === 'asc') return <ArrowUp className="h-3.5 w-3.5" />;
  if (direction === 'desc') return <ArrowDown className="h-3.5 w-3.5" />;
  return <ArrowDownUp className="h-3.5 w-3.5 opacity-60" />;
}

export default function InstanceDashboard({
  tradeMode,
  exchange,
  balances,
  balanceLoading,
  instances,
  instanceListView,
  totalInstancesCount,
  favoriteInstancesCount,
  preferredInstanceIds,
  autoPreferredInstanceIds,
  automaticPreferredInstanceIds,
  assetClassFilter,
  assetClassCounts,
  instanceSortMode,
  paperInstancesCount,
  promotionCandidates = [],
  promotionPreflightId,
  promotionConfirmingId,
  promotionBusyId,
  readOnly = false,
  onCreateClick,
  onInstanceListViewChange,
  onToggleFavoriteInstance,
  onAssetClassFilterChange,
  onInstanceSortModeChange,
  onOpenDetail,
  onPausePaperTrading,
  onStopPaperTrading,
  onPromoteToLive,
  onDeletePaper,
  onClearAllPaper,
  openConfirmDialog,
}: InstanceDashboardProps) {
  const usdtBalance = balances.find((b) => b.currency === 'USDT');
  const isDryRun = tradeMode === 'paper';
  const [instanceSearchQuery, setInstanceSearchQuery] = useState('');
  const [strategyTypeFilter, setStrategyTypeFilter] = useState<StrategyTypeFilter>('all');
  const [klineTimeframeFilter, setKlineTimeframeFilter] = useState<KlineTimeframeFilter>('all');
  const [capitalVersionFilter, setCapitalVersionFilter] = useState<CapitalVersionFilter>('all');
  const [leverageFilter, setLeverageFilter] = useState<LeverageFilter>('all');
  const assetClassOptions: Array<{ value: AssetClassFilter; label: string }> = [
    { value: 'all', label: '全部' },
    { value: 'spot', label: '现货' },
    { value: 'contract', label: '合约' },
  ];
  const strategyTypeOptions: Array<{ value: StrategyTypeFilter; label: string }> = [
    { value: 'all', label: '全部' },
    { value: 'cta', label: 'CTA' },
    { value: 'martin', label: '马丁' },
    { value: 'ai', label: 'AI' },
    { value: 'market_making', label: '做市' },
  ];
  const timeframeOptions: Array<{ value: KlineTimeframeFilter; label: string }> = [
    { value: 'all', label: '全部' },
    { value: '1m', label: '1M' },
    { value: '5m', label: '5M' },
    { value: '15m', label: '15M' },
    { value: '30m', label: '30M' },
    { value: '1h', label: '1H' },
    { value: '4h', label: '4H' },
    { value: '12h', label: '12H' },
    { value: '1d', label: '1D' },
  ];
  const capitalVersionOptions: Array<{ value: CapitalVersionFilter; label: string }> = [
    { value: 'all', label: '全部' },
    { value: '100u', label: '100U' },
    { value: '1000u', label: '1000U' },
  ];
  const leverageOptions: Array<{ value: LeverageFilter; label: string }> = [
    { value: 'all', label: '全部' },
    { value: '1x', label: '1X' },
    { value: '2x', label: '2X' },
    { value: '3x', label: '3X' },
    { value: '5x', label: '5X' },
    { value: '10x', label: '10X' },
    { value: '20x', label: '20X' },
    { value: '50x', label: '50X' },
  ];
  const sortControls: Array<{ field: SortField; label: string }> = [
    { field: 'return', label: '收益率' },
    { field: 'sharpe', label: '夏普' },
    { field: 'win_rate', label: '胜率' },
    { field: 'profit_factor', label: '盈亏比' },
    { field: 'created', label: '创建时间' },
  ];
  const handleStrategyTypeFilterChange = (nextFilter: StrategyTypeFilter) => {
    setStrategyTypeFilter(nextFilter);
    setKlineTimeframeFilter('all');
    setCapitalVersionFilter('all');
    setLeverageFilter('all');
  };
  const handleTimeframeFilterChange = (nextFilter: KlineTimeframeFilter) => {
    setKlineTimeframeFilter(nextFilter);
    setCapitalVersionFilter('all');
    setLeverageFilter('all');
  };
  const handleCapitalVersionFilterChange = (nextFilter: CapitalVersionFilter) => {
    setCapitalVersionFilter(nextFilter);
    setLeverageFilter('all');
  };
  const strategyTypeCounts = useMemo(() => {
    const counts: Record<StrategyTypeFilter, number> = {
      all: instances.length,
      cta: 0,
      martin: 0,
      ai: 0,
      market_making: 0,
    };
    for (const inst of instances) {
      const type = inferInstanceStrategyType(inst);
      if (type === 'cta' || type === 'martin' || type === 'ai' || type === 'market_making') {
        counts[type] += 1;
      }
    }
    return counts;
  }, [instances]);
  const strategyTypeFilteredInstances = useMemo(
    () =>
      instances.filter(
        (inst) => strategyTypeFilter === 'all' || inferInstanceStrategyType(inst) === strategyTypeFilter,
      ),
    [instances, strategyTypeFilter],
  );
  const timeframeCounts = useMemo(() => {
    const counts: Record<KlineTimeframeFilter, number> = {
      all: strategyTypeFilteredInstances.length,
      '1m': 0,
      '5m': 0,
      '15m': 0,
      '30m': 0,
      '1h': 0,
      '4h': 0,
      '12h': 0,
      '1d': 0,
    };
    for (const inst of strategyTypeFilteredInstances) {
      const timeframe = normalizeInstanceTimeframe(inst.timeframe);
      if (timeframe !== 'other' && timeframe !== 'all') counts[timeframe] += 1;
    }
    return counts;
  }, [strategyTypeFilteredInstances]);
  const timeframeFilteredInstances = useMemo(
    () =>
      strategyTypeFilteredInstances.filter(
        (inst) =>
          klineTimeframeFilter === 'all' ||
          normalizeInstanceTimeframe(inst.timeframe) === klineTimeframeFilter,
      ),
    [klineTimeframeFilter, strategyTypeFilteredInstances],
  );
  const capitalVersionCounts = useMemo(() => {
    const counts: Record<CapitalVersionFilter, number> = {
      all: timeframeFilteredInstances.length,
      '100u': 0,
      '1000u': 0,
    };
    for (const inst of timeframeFilteredInstances) {
      const capitalVersion = normalizeInstanceCapitalVersion(inst);
      if (capitalVersion !== 'other' && capitalVersion !== 'all') counts[capitalVersion] += 1;
    }
    return counts;
  }, [timeframeFilteredInstances]);
  const capitalVersionFilteredInstances = useMemo(
    () =>
      timeframeFilteredInstances.filter(
        (inst) =>
          capitalVersionFilter === 'all' ||
          normalizeInstanceCapitalVersion(inst) === capitalVersionFilter,
      ),
    [capitalVersionFilter, timeframeFilteredInstances],
  );
  const leverageCounts = useMemo(() => {
    const counts: Record<LeverageFilter, number> = {
      all: capitalVersionFilteredInstances.length,
      '1x': 0,
      '2x': 0,
      '3x': 0,
      '5x': 0,
      '10x': 0,
      '20x': 0,
      '50x': 0,
    };
    for (const inst of capitalVersionFilteredInstances) {
      const leverage = normalizeInstanceLeverage(inst);
      if (leverage !== 'other' && leverage !== 'all') counts[leverage] += 1;
    }
    return counts;
  }, [capitalVersionFilteredInstances]);
  const leverageFilteredInstances = useMemo(
    () =>
      capitalVersionFilteredInstances.filter(
        (inst) =>
          leverageFilter === 'all' ||
          normalizeInstanceLeverage(inst) === leverageFilter,
      ),
    [capitalVersionFilteredInstances, leverageFilter],
  );
  const visibleInstances = useMemo(
    () =>
      leverageFilteredInstances.filter((inst) => instanceMatchesSearch(inst, instanceSearchQuery)),
    [leverageFilteredInstances, instanceSearchQuery],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Activity className="w-6 h-6 text-blue-400" />
            策略实例控制台
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {tradeMode === 'live'
              ? '实盘只展示真实下单实例；推荐从已验证模拟盘生成独立小资金实盘试运行。'
              : '管理多路模拟实例；通过模拟盘验证后可在「实盘」入口晋级。'}
          </p>
        </div>
        {!readOnly && (
          <button
            type="button"
            onClick={onCreateClick}
            className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold shadow-lg shadow-blue-900/20 transition-colors"
          >
            <Plus className="w-4 h-4" />
            {tradeMode === 'live' ? '手动创建实盘实例' : '创建新模拟实例'}
          </button>
        )}
      </div>

      {isDryRun && (
        <div
          role="tablist"
          aria-label="模拟策略视图"
          className="inline-flex h-11 w-fit max-w-full items-center rounded-xl border border-crypto-border bg-crypto-card p-1"
        >
          {([
            { value: 'favorites', label: '优选策略', count: favoriteInstancesCount },
            { value: 'all', label: '全部策略', count: totalInstancesCount },
          ] as const).map((option) => {
            const active = instanceListView === option.value;
            return (
              <button
                key={option.value}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => onInstanceListViewChange(option.value)}
                className={clsx(
                  'inline-flex h-9 items-center justify-center gap-2 rounded-lg px-4 text-xs font-semibold transition-colors',
                  active
                    ? 'bg-yellow-500/15 text-yellow-200 ring-1 ring-yellow-400/20'
                    : 'text-gray-500 hover:bg-white/5 hover:text-gray-300',
                )}
              >
                {option.value === 'favorites' && (
                  <Star className={clsx('h-3.5 w-3.5', active && 'fill-current')} />
                )}
                <span>{option.label}</span>
                <span
                  className={clsx(
                    'rounded-md px-1.5 py-0.5 text-[10px]',
                    active ? 'bg-yellow-400/10 text-yellow-100' : 'bg-crypto-bg text-gray-500',
                  )}
                >
                  {option.count}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {tradeMode === 'live' && (
        <div className="bg-gradient-to-r from-orange-600/10 to-red-600/10 border border-orange-500/30 rounded-xl p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Wallet className="w-5 h-5 text-orange-400" />
              <div>
                <div className="text-sm font-semibold text-white">
                  实盘账户 · {exchange.toUpperCase()}
                </div>
                <div className="text-xs text-gray-400 mt-0.5">将使用您的真实资金进行交易</div>
              </div>
            </div>
            <div className="text-right">
              {balanceLoading ? (
                <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
              ) : usdtBalance ? (
                <>
                  <div className="text-lg font-bold text-white">${usdtBalance.total.toFixed(2)}</div>
                  <div className="text-[10px] text-gray-500">
                    可用: ${usdtBalance.free.toFixed(2)} · 冻结: ${usdtBalance.used.toFixed(2)}
                  </div>
                </>
              ) : (
                <div className="text-sm text-gray-500">无余额数据</div>
              )}
            </div>
          </div>
        </div>
      )}

      {tradeMode === 'live' && (
        <div className="bg-crypto-card border border-red-500/25 rounded-xl p-4 space-y-4">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
            <div>
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <ShieldCheck className="w-5 h-5 text-red-400" />
                模拟转实盘
              </h2>
              <p className="text-xs text-gray-500 mt-1">
                从模拟策略克隆独立实盘记录，自动写入小资金风控、晋级元数据、实盘预检和二次确认。
              </p>
            </div>
          </div>

          {promotionCandidates.length === 0 ? (
            <div className="rounded-lg border border-dashed border-crypto-border py-8 text-center text-sm text-gray-500">
              暂无可晋级的模拟策略。先在模拟盘跑出稳定样本，再从这里晋级小资金实盘试运行。
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {promotionCandidates.slice(0, 6).map((candidate) => {
                const strategy = candidate.strategy;
                const strategyId = Number(strategy.id);
                const returnPct = candidate.returnPct;
                const isPreflighting = promotionPreflightId === strategyId;
                const isConfirming = promotionConfirmingId === strategyId;
                const isBusy = promotionBusyId === strategyId;
                return (
                  <div
                    key={String(strategy.id)}
                    className="rounded-xl border border-crypto-border bg-crypto-bg/50 p-3 flex flex-col gap-3"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-white truncate">
                          {strategy.name}
                        </div>
                        <div className="text-[11px] text-gray-500 mt-0.5 truncate">
                          #{strategy.id} · {formatStrategySymbolScope(strategy)}
                        </div>
                      </div>
                      <span className="shrink-0 rounded-full bg-yellow-500/15 px-2 py-0.5 text-[10px] font-bold text-yellow-300">
                        模拟
                      </span>
                    </div>
                    <div className="grid grid-cols-4 gap-2 text-center">
                      <div>
                        <div
                          className={clsx(
                            'text-xs font-bold',
                            returnPct == null
                              ? 'text-gray-500'
                              : returnPct >= 0
                                ? 'text-up'
                                : 'text-down',
                          )}
                        >
                          {returnPct == null ? '--' : `${returnPct.toFixed(2)}%`}
                        </div>
                        <div className="text-[9px] text-gray-600">收益</div>
                      </div>
                      <div>
                        <div className="text-xs font-bold text-white">
                          {candidate.sharpeRatio == null ? '--' : candidate.sharpeRatio.toFixed(2)}
                        </div>
                        <div className="text-[9px] text-gray-600">夏普</div>
                      </div>
                      <div>
                        <div className="text-xs font-bold text-red-300">
                          {candidate.maxDrawdownPct == null
                            ? '--'
                            : `${candidate.maxDrawdownPct.toFixed(1)}%`}
                        </div>
                        <div className="text-[9px] text-gray-600">回撤</div>
                      </div>
                      <div>
                        <div className="text-xs font-bold text-blue-300">
                          {candidate.totalTrades == null ? '--' : candidate.totalTrades}
                        </div>
                        <div className="text-[9px] text-gray-600">交易</div>
                      </div>
                    </div>
                    <button
                      type="button"
                      disabled={isPreflighting || isBusy}
                      onClick={() => onPromoteToLive?.(candidate)}
                      className={clsx(
                        'inline-flex items-center justify-center gap-2 rounded-lg border border-red-500/40 bg-red-600/15 px-3 py-2 text-xs font-semibold text-red-300 hover:bg-red-600/25',
                        (isPreflighting || isBusy) && 'cursor-not-allowed opacity-70',
                      )}
                    >
                      {isPreflighting || isBusy ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Rocket className="w-3.5 h-3.5" />
                      )}
                      {isBusy
                        ? '正在部署实盘...'
                        : isPreflighting
                          ? '正在实盘前检查...'
                          : isConfirming
                            ? '等待确认实盘...'
                            : '部署到实盘'}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex h-11 items-center rounded-xl border border-crypto-border bg-crypto-card p-1">
          {assetClassOptions.map((option) => {
            const active = assetClassFilter === option.value;
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={active}
                onClick={() => onAssetClassFilterChange(option.value)}
                className={clsx(
                  'inline-flex h-9 items-center min-w-20 justify-center gap-2 rounded-lg px-3 text-xs font-semibold transition-colors',
                  active
                    ? 'bg-blue-500/20 text-blue-300'
                    : 'text-gray-500 hover:bg-white/5 hover:text-gray-300',
                )}
              >
                <span>{option.label}</span>
                <span
                  className={clsx(
                    'rounded-md px-1.5 py-0.5 text-[10px]',
                    active ? 'bg-blue-400/15 text-blue-200' : 'bg-crypto-bg text-gray-500',
                  )}
                >
                  {assetClassCounts[option.value] ?? 0}
                </span>
              </button>
            );
          })}
        </div>
        <div className="inline-flex min-h-11 items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card/80 p-1">
          {strategyTypeOptions.map((option) => {
            const active = strategyTypeFilter === option.value;
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={active}
                onClick={() => handleStrategyTypeFilterChange(option.value)}
                className={clsx(
                  'inline-flex h-9 items-center justify-center gap-2 rounded-lg px-3 text-xs font-semibold transition-colors',
                  active
                    ? 'bg-blue-500/20 text-blue-300'
                    : 'text-gray-500 hover:bg-white/5 hover:text-gray-300',
                )}
              >
                <span>{option.label}</span>
                <span
                  className={clsx(
                    'rounded-md px-1.5 py-0.5 text-[10px]',
                    active ? 'bg-blue-400/15 text-blue-200' : 'bg-crypto-bg text-gray-500',
                  )}
                >
                  {strategyTypeCounts[option.value] ?? 0}
                </span>
              </button>
            );
          })}
        </div>
        <div className="inline-flex min-h-11 max-w-full flex-wrap items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card/80 p-1">
          {timeframeOptions.map((option) => {
            const active = klineTimeframeFilter === option.value;
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={active}
                onClick={() => handleTimeframeFilterChange(option.value)}
                className={clsx(
                  'inline-flex h-9 items-center justify-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold transition-colors',
                  active
                    ? 'bg-blue-500/20 text-blue-300'
                    : 'text-gray-500 hover:bg-white/5 hover:text-gray-300',
                )}
              >
                <span>{option.label}</span>
                <span
                  className={clsx(
                    'rounded-md px-1.5 py-0.5 text-[10px]',
                    active ? 'bg-blue-400/15 text-blue-200' : 'bg-crypto-bg text-gray-500',
                  )}
                >
                  {timeframeCounts[option.value] ?? 0}
                </span>
              </button>
            );
          })}
        </div>
        <div className="inline-flex min-h-11 items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card/80 p-1">
          {capitalVersionOptions.map((option) => {
            const active = capitalVersionFilter === option.value;
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={active}
                onClick={() => handleCapitalVersionFilterChange(option.value)}
                className={clsx(
                  'inline-flex h-9 items-center justify-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold transition-colors',
                  active
                    ? 'bg-blue-500/20 text-blue-300'
                    : 'text-gray-500 hover:bg-white/5 hover:text-gray-300',
                )}
              >
                <span>{option.label}</span>
                <span
                  className={clsx(
                    'rounded-md px-1.5 py-0.5 text-[10px]',
                    active ? 'bg-blue-400/15 text-blue-200' : 'bg-crypto-bg text-gray-500',
                  )}
                >
                  {capitalVersionCounts[option.value] ?? 0}
                </span>
              </button>
            );
          })}
        </div>
        <div className="inline-flex min-h-11 max-w-full flex-wrap items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card/80 p-1">
          {leverageOptions.map((option) => {
            const active = leverageFilter === option.value;
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={active}
                onClick={() => setLeverageFilter(option.value)}
                className={clsx(
                  'inline-flex h-9 items-center justify-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold transition-colors',
                  active
                    ? 'bg-amber-500/20 text-amber-200 ring-1 ring-amber-400/20'
                    : 'text-gray-500 hover:bg-white/5 hover:text-gray-300',
                )}
              >
                <span>{option.label}</span>
                <span
                  className={clsx(
                    'rounded-md px-1.5 py-0.5 text-[10px]',
                    active ? 'bg-amber-400/15 text-amber-100' : 'bg-crypto-bg text-gray-500',
                  )}
                >
                  {leverageCounts[option.value] ?? 0}
                </span>
              </button>
            );
          })}
        </div>
        <div className="inline-flex h-11 items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card/80 p-1">
          {sortControls.map((control) => {
            const direction = sortDirectionFor(instanceSortMode, control.field);
            const active = direction !== null;
            return (
              <button
                key={control.field}
                type="button"
                aria-pressed={active}
                onClick={() =>
                  onInstanceSortModeChange(nextInstanceSortMode(instanceSortMode, control.field))
                }
                className={clsx(
                  'inline-flex h-9 items-center justify-center gap-1.5 rounded-lg px-3 text-xs font-semibold transition-colors',
                  active
                    ? 'bg-purple-500/20 text-purple-200 ring-1 ring-purple-400/20'
                    : 'text-gray-500 hover:bg-white/5 hover:text-gray-300',
                )}
              >
                <span>{control.label}</span>
                <SortArrow direction={direction} />
              </button>
            );
          })}
        </div>
        <label className="relative flex h-11 w-full min-w-[260px] max-w-md items-center rounded-xl border border-crypto-border bg-crypto-card px-3 text-sm text-gray-400 focus-within:border-blue-500/50 focus-within:ring-1 focus-within:ring-blue-500/20 sm:w-[360px]">
          <Search className="mr-2 h-4 w-4 shrink-0 text-gray-500" />
          <span className="sr-only">搜索模拟实例</span>
          <input
            type="search"
            value={instanceSearchQuery}
            onChange={(event) => setInstanceSearchQuery(event.target.value)}
            placeholder="搜索策略、标的、周期、杠杆..."
            className="min-w-0 flex-1 bg-transparent text-sm font-semibold text-gray-200 placeholder:text-gray-600 focus:outline-none"
          />
        </label>
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-4">
        {visibleInstances.length === 0 && (
          <div className="col-span-full flex flex-col items-center justify-center py-16 border border-dashed border-crypto-border rounded-xl text-gray-500 text-sm">
            <Rocket className="w-10 h-10 mb-3 opacity-40" />
            {instanceListView === 'favorites' && favoriteInstancesCount === 0
              ? '还没有优选策略。收益率超过 5% 的策略会自动进入，也可点击卡片右上角星标手动加入。'
              : instanceSearchQuery.trim()
              ? '未找到匹配的模拟实例。'
              : assetClassCounts.all > 0
              ? '当前筛选下暂无实例。'
              : '暂无运行中实例。点击「创建新策略实例」启动策略。'}
          </div>
        )}

        {visibleInstances.map((inst) => {
          const running = inst.status === 'running';
          const paused = inst.status === 'paused';
          const paperId = inst.id.startsWith('paper:') ? inst.id.slice('paper:'.length) : null;
          const hasTradingControls = inst.id.startsWith('live:strategy:') && inst.dryRun !== false;
          const totalPnl = inst.totalPnl;
          const totalReturnPct = inst.totalReturnPct;
          const sharpeRatio = inst.sharpeRatio;
          const winRate = inst.winRate;
          const profitFactor = inst.profitFactor;
          const timeframePill = formatInstanceTimeframePill(inst.timeframe);
          const capitalVersionPill = formatInstanceCapitalVersionPill(inst);
          const leveragePill = formatInstanceLeveragePill(inst);
          const preferred = preferredInstanceIds.has(inst.id);
          const autoPreferred = autoPreferredInstanceIds.has(inst.id);
          const automaticPreferred = automaticPreferredInstanceIds.has(inst.id);
          const returnToneClass =
            totalReturnPct == null
              ? 'text-gray-500'
              : totalReturnPct >= 0
                ? 'text-up'
                : 'text-down';

          return (
            <div
              key={inst.id}
              className="bg-crypto-card border border-crypto-border rounded-xl p-3 flex flex-col gap-3 hover:border-gray-600 transition-colors"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div
                    title={inst.name}
                    aria-label={`策略名称：${inst.name}`}
                    className={clsx(
                      'min-w-0 truncate text-sm font-semibold',
                      strategyNameColorClass(inst.assetClass),
                    )}
                  >
                    {inst.name}
                  </div>
                  {inst.isAiAutonomous && (
                    <span className="mt-1 inline-flex w-fit items-center gap-1 rounded-full border border-yellow-500/30 bg-yellow-500/15 px-2 py-0.5 text-[10px] font-bold text-yellow-300">
                      <Activity className="h-3 w-3" />
                      AI自主
                    </span>
                  )}
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <span className="inline-flex h-5 items-center rounded-full border border-blue-500/30 bg-blue-500/10 px-2 text-[10px] font-bold uppercase tracking-normal text-blue-300">
                      {timeframePill}
                    </span>
                    {capitalVersionPill && (
                      <span className="inline-flex h-5 items-center rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 text-[10px] font-bold uppercase tracking-normal text-emerald-300">
                        {capitalVersionPill}
                      </span>
                    )}
                    {leveragePill && (
                      <span className="inline-flex h-5 items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-2 text-[10px] font-bold uppercase tracking-normal text-amber-300">
                        {leveragePill}
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[11px] text-gray-500">
                    <SymbolIcon symbol={inst.symbol} size="xs" />
                    <span className="truncate">{inst.symbol}</span>
                  </div>
                </div>
                <div className="flex shrink-0 items-start justify-end gap-2">
                  {isDryRun && (
                    <button
                      type="button"
                      aria-pressed={preferred}
                      aria-label={
                        autoPreferred
                          ? `取消自动优选 ${inst.name}`
                          : automaticPreferred
                            ? `恢复自动优选 ${inst.name}`
                          : preferred
                            ? `取消收藏 ${inst.name}`
                            : `收藏 ${inst.name}`
                      }
                      title={
                        autoPreferred
                          ? '收益率 > 5%，点击取消自动优选'
                          : automaticPreferred
                            ? '恢复自动优选'
                          : preferred
                            ? '从优选移除'
                            : '加入优选'
                      }
                      onClick={(event) => {
                        event.stopPropagation();
                        onToggleFavoriteInstance(inst);
                      }}
                      className={clsx(
                        'inline-flex h-8 w-8 items-center justify-center rounded-lg border transition-colors',
                        preferred
                          ? 'border-yellow-400/40 bg-yellow-500/15 text-yellow-300'
                          : 'border-crypto-border text-gray-600 hover:border-yellow-500/35 hover:bg-yellow-500/10 hover:text-yellow-300',
                      )}
                    >
                      <Star className={clsx('h-4 w-4', preferred && 'fill-current')} />
                    </button>
                  )}
                  {running ? (
                    <span
                      className="relative mt-1 flex h-4 w-4 items-center justify-center"
                      title="运行中"
                      aria-label="运行中"
                    >
                      <span className="absolute h-4 w-4 rounded-full bg-emerald-400/40 animate-ping" />
                      <span className="relative h-2.5 w-2.5 rounded-full bg-emerald-400 shadow-[0_0_14px_rgba(52,211,153,0.85)]" />
                    </span>
                  ) : (
                    <span
                      className={clsx(
                        'inline-flex min-w-12 justify-center rounded-full px-2 py-0.5 text-[10px] font-bold',
                        paused && 'bg-yellow-500/20 text-yellow-400',
                        !paused && 'bg-gray-700/50 text-gray-400',
                      )}
                    >
                      {paused ? '暂停' : inst.status}
                    </span>
                  )}
                </div>
              </div>

              <div className="space-y-3">
                <div className="grid min-w-0 grid-cols-2 items-end gap-2">
                  <div className="flex min-w-0 flex-col gap-1">
                    <span className="text-[10px] font-semibold text-gray-400">
                      收益金额
                    </span>
                    <div
                      className={clsx(
                        'whitespace-nowrap text-[clamp(0.8125rem,0.72vw,1rem)] font-bold tabular-nums leading-tight',
                        totalPnl == null
                          ? 'text-gray-500'
                          : totalPnl >= 0
                            ? 'text-up'
                            : 'text-down',
                      )}
                    >
                      {formatSignedUsd(totalPnl)}
                    </div>
                  </div>
                  <div className="flex min-w-0 flex-col items-end gap-1 text-right">
                    <span className="text-[10px] font-semibold text-gray-400">
                      收益率
                    </span>
                    <div
                      className={clsx(
                        'whitespace-nowrap text-[clamp(0.8125rem,0.72vw,1rem)] font-bold tabular-nums leading-tight',
                        returnToneClass,
                      )}
                    >
                      {formatSignedPercent(totalReturnPct)}
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-4 gap-2 text-center">
                  <div className="min-w-0">
                    <div
                      className={clsx(
                        'whitespace-nowrap text-xs font-bold tabular-nums',
                        sharpeRatio == null
                          ? 'text-gray-500'
                          : sharpeRatio > 0
                            ? 'text-up'
                            : sharpeRatio < 0
                              ? 'text-down'
                              : 'text-white',
                      )}
                    >
                      {formatSharpe(sharpeRatio)}
                    </div>
                    <div className="mt-1 text-[10px] font-semibold text-gray-400">夏普</div>
                  </div>
                  <div className="min-w-0">
                    <div
                      className={clsx(
                        'whitespace-nowrap text-xs font-bold tabular-nums',
                        winRate == null ? 'text-gray-500' : 'text-white',
                      )}
                    >
                      {winRate == null ? '--' : `${winRate.toFixed(1)}%`}
                    </div>
                    <div className="mt-1 text-[10px] font-semibold text-gray-400">胜率</div>
                  </div>
                  <div className="min-w-0">
                    <div
                      className={clsx(
                        'whitespace-nowrap text-xs font-bold tabular-nums',
                        profitFactor == null ? 'text-gray-500' : 'text-white',
                      )}
                    >
                      {formatRatio(profitFactor)}
                    </div>
                    <div className="mt-1 text-[10px] font-semibold text-gray-400">盈亏比</div>
                  </div>
                  <div className="min-w-0">
                    <div
                      className="whitespace-nowrap text-xs font-bold tabular-nums text-blue-300"
                    >
                      {inst.totalTrades == null ? '--' : Math.trunc(inst.totalTrades)}
                    </div>
                    <div className="mt-1 text-[10px] font-semibold text-gray-400">交易次数</div>
                  </div>
                </div>
              </div>

              <div className="mt-auto flex items-center justify-center gap-2">
                {hasTradingControls && !readOnly && (
                  <div className="grid w-full grid-cols-1 items-center gap-2 sm:grid-cols-3">
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        onPausePaperTrading(inst);
                      }}
                      className={clsx(
                        'inline-flex h-8 min-w-0 w-full items-center justify-center gap-1 rounded-lg border px-1.5 text-[10px] font-bold transition-colors',
                        paused
                          ? 'border-green-500/40 bg-green-500/10 text-green-300 hover:bg-green-500/20'
                          : 'border-yellow-500/40 bg-yellow-500/10 text-yellow-300 hover:bg-yellow-500/20',
                      )}
                    >
                      {paused ? (
                        <PlayCircle className="h-3.5 w-3.5" />
                      ) : (
                        <PauseCircle className="h-3.5 w-3.5" />
                      )}
                      {paused ? '继续交易' : '暂停交易'}
                    </button>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        onStopPaperTrading(inst);
                      }}
                      className="inline-flex h-8 min-w-0 w-full items-center justify-center gap-1 rounded-lg border border-red-500/40 bg-red-500/10 px-1.5 text-[10px] font-bold text-red-300 transition-colors hover:bg-red-500/20"
                    >
                      <Power className="h-3.5 w-3.5" />
                      关闭交易
                    </button>
                    <button
                      type="button"
                      onClick={() => onOpenDetail(inst)}
                      className="inline-flex h-8 min-w-0 w-full items-center justify-center gap-1 rounded-lg border border-blue-500/40 bg-blue-500/10 px-1.5 text-[10px] font-bold text-blue-300 transition-colors hover:bg-blue-500/20"
                    >
                      <Eye className="h-3.5 w-3.5" />
                      详情
                    </button>
                  </div>
                )}
                {paperId && !readOnly && (
                  <button
                    type="button"
                    onClick={() => onDeletePaper(paperId)}
                    className="flex h-8 w-8 items-center justify-center rounded-lg border border-crypto-border text-gray-500 hover:border-red-500/40 hover:text-red-400"
                    title="删除模拟实例"
                  >
                    <XCircle className="w-4 h-4" />
                  </button>
                )}
                {!hasTradingControls && (
                  <button
                    type="button"
                    onClick={() => onOpenDetail(inst)}
                    className="inline-flex h-8 min-w-0 w-full items-center justify-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 text-[11px] font-bold text-blue-300 transition-colors hover:bg-blue-500/20 sm:max-w-[8rem]"
                  >
                    <Eye className="h-3.5 w-3.5" />
                    详情
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {isDryRun && !readOnly && paperInstancesCount > 1 && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() =>
              openConfirmDialog({
                title: '清空全部模拟实例',
                content: '确定要清空列表中的全部模拟盘实例吗？',
                tone: 'warning',
                confirmText: '清空',
                onConfirm: onClearAllPaper,
              })
            }
            className="text-xs text-gray-500 hover:text-red-400"
          >
            清空全部模拟实例
          </button>
        </div>
      )}
    </div>
  );
}
