import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';
import {
  Activity,
  AlertTriangle,
  ArrowDown,
  ArrowDownUp,
  ArrowUp,
  Briefcase,
  ChevronDown,
  CircleDollarSign,
  KeyRound,
  Landmark,
  Link2,
  Loader2,
  Pause,
  Play,
  Plus,
  Rocket,
  Search,
  ShieldCheck,
  Square,
  Trash2,
  Wallet,
  X,
} from 'lucide-react';
import clsx from 'clsx';
import CryptoSelect from '../../components/CryptoSelect';
import ThemeDialog from '../../components/ThemeDialog';
import {
  liveExecutionApi,
  marketApi,
  type LiveExecutionAccount,
  type LiveExecutionAccountReturnRates,
  type LiveExecutionOrder,
  type LiveExecutionPosition,
  type LiveExecutionPreflight,
  type LiveExecutionStrategy,
} from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';

const strategyFilters = [
  { key: 'all', label: '全部' },
  { key: 'deployable', label: '可部署' },
  { key: 'deployed', label: '已部署' },
] as const;

const livePanelStatusFilters = [
  { key: 'running', label: '运行中' },
  { key: 'paused', label: '暂停' },
  { key: 'all', label: '全部' },
] as const;

const LIVE_PANEL_REFRESH_INTERVAL_MS = 5_000;
const LIVE_ASSET_REFRESH_INTERVAL_MS = 60_000;
const LIVE_ASSET_CACHE_TTL_MS = 5 * 60_000;
const LIVE_ASSET_CACHE_PREFIX = 'bitpro:live-real:asset-snapshot:v1';

type StrategyFilter = (typeof strategyFilters)[number]['key'];
type LivePanelStatusFilter = (typeof livePanelStatusFilters)[number]['key'];
type SortMode = 'created_desc' | 'return_desc' | 'return_asc';
type SortDirection = 'asc' | 'desc';

type AccountBalanceRow = {
  currency?: string;
  free?: number;
  used?: number;
  total?: number;
};

type LiveAssetSnapshot = {
  balances: AccountBalanceRow[];
  balanceDetail: {
    trading: AccountBalanceRow[];
    funding: AccountBalanceRow[];
  };
  returnRates: LiveExecutionAccountReturnRates | null;
};

const EMPTY_LIVE_ASSET_SNAPSHOT: LiveAssetSnapshot = {
  balances: [],
  balanceDetail: { trading: [], funding: [] },
  returnRates: null,
};

const stableCoins = new Set(['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD']);

type ConfirmState = {
  title: string;
  content: string;
  confirmText: string;
  tone: 'danger' | 'warning' | 'default';
  onConfirm: () => Promise<void> | void;
} | null;

type AccountFormState = {
  name: string;
  exchange: 'okx' | 'binanceusdm';
  apiKey: string;
  apiSecret: string;
  passphrase: string;
  testnet: boolean;
};

const emptyAccountForm: AccountFormState = {
  name: '',
  exchange: 'okx',
  apiKey: '',
  apiSecret: '',
  passphrase: '',
  testnet: false,
};

function finiteNumber(value: unknown): number | null {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function liveAssetCacheKey(accountId: string): string {
  return `${LIVE_ASSET_CACHE_PREFIX}:${accountId || 'default'}`;
}

function readCachedLiveAssetSnapshot(accountId: string): LiveAssetSnapshot | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(liveAssetCacheKey(accountId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as (LiveAssetSnapshot & { cachedAt?: number }) | null;
    if (!parsed || typeof parsed !== 'object') return null;
    const cachedAt = finiteNumber(parsed.cachedAt) || 0;
    if (!cachedAt || Date.now() - cachedAt > LIVE_ASSET_CACHE_TTL_MS) return null;
    return {
      balances: Array.isArray(parsed.balances) ? parsed.balances : [],
      balanceDetail: {
        trading: Array.isArray(parsed.balanceDetail?.trading) ? parsed.balanceDetail.trading : [],
        funding: Array.isArray(parsed.balanceDetail?.funding) ? parsed.balanceDetail.funding : [],
      },
      returnRates: parsed.returnRates || null,
    };
  } catch {
    return null;
  }
}

function hasRenderableLiveAssetSnapshot(snapshot: LiveAssetSnapshot): boolean {
  return [
    ...snapshot.balances,
    ...snapshot.balanceDetail.trading,
    ...snapshot.balanceDetail.funding,
  ].some((row) => (finiteNumber(row.total) || 0) > 0);
}

function writeCachedLiveAssetSnapshot(accountId: string, snapshot: LiveAssetSnapshot): void {
  if (typeof window === 'undefined') return;
  try {
    const payload = { ...snapshot, cachedAt: Date.now() };
    window.sessionStorage.setItem(liveAssetCacheKey(accountId), JSON.stringify(payload));
  } catch {
    // sessionStorage may be unavailable in private/restricted contexts; asset data still renders from memory.
  }
}

function formatUsd(value: unknown): string {
  const num = finiteNumber(value);
  if (num == null) return '--';
  return `$${num.toFixed(2)}`;
}

function formatSignedUsd(value: unknown): string {
  const num = finiteNumber(value);
  if (num == null) return '--';
  const sign = num > 0 ? '+' : num < 0 ? '-' : '';
  return `${sign}$${Math.abs(num).toFixed(2)}`;
}

function formatSignedPct(value: unknown): string {
  const num = finiteNumber(value);
  if (num == null) return '--';
  const sign = num > 0 ? '+' : '';
  return `${sign}${num.toFixed(2)}%`;
}

function formatReturnRate(value: unknown): string {
  return formatSignedPct(value);
}

function signedMetricColor(value: unknown): string {
  const num = finiteNumber(value);
  if (num == null || num === 0) return 'text-gray-300';
  return num > 0 ? 'text-up' : 'text-down';
}

function summarizeSymbols(symbols?: string[], tradeSymbols?: string[]): string {
  const list = tradeSymbols && tradeSymbols.length > 0 ? tradeSymbols : symbols || [];
  if (list.length === 0) return '未定义';
  const shown = list.slice(0, 3).join(', ');
  return list.length > 3 ? `${shown} 等 ${list.length} 个` : shown;
}

function compactName(name: string, fallback: string): string {
  return String(name || fallback).replace(/^\[(现货|合约)\]\s*/, '');
}

function strategyMatchesSearch(strategy: LiveExecutionStrategy, keyword: string): boolean {
  if (!keyword) return true;
  const haystack = [
    strategy.strategyName,
    String(strategy.strategyId),
    strategy.status,
    ...(strategy.symbols || []),
    ...(strategy.tradeSymbols || []),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return haystack.includes(keyword);
}

function isRunningStrategy(strategy: LiveExecutionStrategy): boolean {
  return String(strategy.status || '').toLowerCase() === 'running';
}

function isRunningDeployableStrategy(strategy: LiveExecutionStrategy): boolean {
  return (
    !strategy.deployed
    && Boolean(strategy.deployable)
    && isRunningStrategy(strategy)
  );
}

function strategyMatchesFilter(strategy: LiveExecutionStrategy, filter: StrategyFilter): boolean {
  // 候选池只保留源模拟策略仍在运行中的条目；未运行/已停止策略不进入列表。
  if (!isRunningStrategy(strategy)) return false;
  if (filter === 'deployable') return isRunningDeployableStrategy(strategy);
  if (filter === 'deployed') return Boolean(strategy.deployed);
  return true;
}

function liveDeploymentMatchesFilter(status: string, filter: LivePanelStatusFilter): boolean {
  if (filter === 'all') return true;
  return status === filter;
}

function timestampMs(value?: string | null): number {
  if (!value) return 0;
  const ts = Date.parse(value);
  return Number.isFinite(ts) ? ts : 0;
}

function sortDirectionFor(sortMode: SortMode, field: 'created' | 'return'): SortDirection | null {
  if (field === 'created') return sortMode === 'created_desc' ? 'desc' : null;
  if (sortMode === 'return_asc') return 'asc';
  if (sortMode === 'return_desc') return 'desc';
  return null;
}

function nextSortMode(sortMode: SortMode, field: 'created' | 'return'): SortMode {
  if (field === 'created') return 'created_desc';
  return sortDirectionFor(sortMode, field) === 'desc' ? 'return_asc' : 'return_desc';
}

function SortArrow({ direction }: { direction: SortDirection | null }) {
  if (direction === 'asc') return <ArrowUp className="h-3.5 w-3.5" />;
  if (direction === 'desc') return <ArrowDown className="h-3.5 w-3.5" />;
  return <ArrowDownUp className="h-3.5 w-3.5 opacity-60" />;
}

function preflightLogTone(passed: boolean): string {
  return passed ? 'text-green-300' : 'text-red-300';
}

function preflightResultButtonTone(preflight?: LiveExecutionPreflight): string {
  if (!preflight) return 'border-crypto-border text-gray-500';
  return preflight.allPassed
    ? 'border-green-500/40 text-green-300 hover:bg-green-500/10'
    : 'border-red-500/40 text-red-300 hover:bg-red-500/10';
}

const livePanelActionButtonBase =
  'inline-flex h-8 min-w-0 items-center justify-center gap-1.5 rounded-lg border px-2.5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:border-crypto-border disabled:bg-white/[0.03] disabled:text-gray-500';
const liveActionButtonWarning = 'border-yellow-500/40 text-yellow-300 hover:bg-yellow-500/10';
const liveActionButtonSuccess = 'border-green-500/40 text-green-300 hover:bg-green-500/10';
const liveActionButtonDanger = 'border-red-500/40 text-red-300 hover:bg-red-500/10';

function deploymentStatusLabel(status: string): string {
  if (status === 'running') return '运行中';
  if (status === 'paused') return '已暂停';
  if (status === 'stopped') return '已停止';
  if (status === 'error') return '异常';
  return '状态未知';
}

function deploymentStatusLightClass(status: string): string {
  if (status === 'running') {
    return 'animate-pulse bg-green-400 shadow-[0_0_0_4px_rgba(74,222,128,0.14),0_0_14px_rgba(74,222,128,0.7)]';
  }
  if (status === 'paused') {
    return 'animate-pulse bg-yellow-300 shadow-[0_0_0_4px_rgba(253,224,71,0.12),0_0_14px_rgba(253,224,71,0.55)]';
  }
  if (status === 'error') {
    return 'animate-pulse bg-red-400 shadow-[0_0_0_4px_rgba(248,113,113,0.12),0_0_14px_rgba(248,113,113,0.55)]';
  }
  if (status === 'stopped') {
    return 'bg-gray-500 shadow-[0_0_0_4px_rgba(107,114,128,0.12)]';
  }
  return 'bg-gray-500 shadow-[0_0_0_4px_rgba(107,114,128,0.12)]';
}

function liveWorkspaceRemoveBlockReason(strategy: LiveExecutionStrategy): string | null {
  const statuses = new Set<string>();
  (strategy.accountBindings || []).forEach((binding) => {
    const status = String(binding.deploymentStatus || '').toLowerCase();
    if (status) statuses.add(status);
  });
  const topLevelStatus = String(strategy.deploymentStatus || '').toLowerCase();
  if (topLevelStatus) statuses.add(topLevelStatus);
  if (statuses.has('running') || statuses.has('active') || statuses.has('deployed')) {
    return '仍有正在运行的实盘订阅。请先在右侧订阅面板点击「停止」，确认订阅停止后再移出实盘列表。';
  }
  if (statuses.has('paused')) {
    return '已暂停的实盘订阅需要先停止后才能移出。请先在右侧订阅面板点击「停止」，确认订阅停止后再移出实盘列表。';
  }
  return null;
}

function livePanelStatusFilterButtonClass(filter: LivePanelStatusFilter, active: boolean): string {
  if (!active) {
    if (filter === 'running') return 'text-gray-500 hover:bg-green-400/[0.08] hover:text-green-200';
    if (filter === 'paused') return 'text-gray-500 hover:bg-yellow-300/[0.08] hover:text-yellow-200';
    return 'text-gray-500 hover:bg-white/[0.04] hover:text-gray-200';
  }
  if (filter === 'running') {
    return 'bg-green-400/[0.12] text-green-100 shadow-[inset_0_0_0_1px_rgba(74,222,128,0.34)]';
  }
  if (filter === 'paused') {
    return 'bg-yellow-300/[0.12] text-yellow-100 shadow-[inset_0_0_0_1px_rgba(253,224,71,0.34)]';
  }
  return 'bg-white/[0.06] text-gray-100 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.28)]';
}

function livePanelStatusFilterCountClass(filter: LivePanelStatusFilter, active: boolean): string {
  if (!active) return 'bg-white/[0.04] text-gray-500';
  if (filter === 'running') return 'bg-green-400/[0.16] text-green-100';
  if (filter === 'paused') return 'bg-yellow-300/[0.16] text-yellow-100';
  return 'bg-white/[0.08] text-gray-100';
}

function isSpotPosition(position: LiveExecutionPosition): boolean {
  return [position.assetType, position.posSide, position.side]
    .map((value) => String(value || '').toLowerCase())
    .includes('spot');
}

function normalizeLiveInstrumentKey(value: unknown): string {
  const raw = String(value || '').trim().toUpperCase();
  if (!raw) return '';
  return raw.split(':')[0];
}

function extractRiskConfigSymbols(strategy: LiveExecutionStrategy): string[] {
  const config = strategy.riskConfig || {};
  const candidates = [
    config.allowedLiveSymbols,
    config.allowed_live_symbols,
    config.symbols,
    config.tradeSymbols,
    config.trade_symbols,
  ];
  return candidates.flatMap((value) => (Array.isArray(value) ? value.map(String) : []));
}

function liveStopPositionKeys(strategy: LiveExecutionStrategy): Set<string> {
  return new Set([
    ...(strategy.tradeSymbols || []),
    ...(strategy.symbols || []),
    ...extractRiskConfigSymbols(strategy),
  ].map(normalizeLiveInstrumentKey).filter(Boolean));
}

function hasOpenContractPosition(position: LiveExecutionPosition): boolean {
  if (isSpotPosition(position)) return false;
  return [
    position.contracts,
    position.amount,
    position.baseAmount,
    position.notional,
    position.notionalUsdt,
  ].some((value) => {
    const num = finiteNumber(value);
    return num != null && Math.abs(num) > 0;
  });
}

function liveStopRelatedContractPositions(
  strategy: LiveExecutionStrategy,
  positions: LiveExecutionPosition[],
): LiveExecutionPosition[] {
  const keys = liveStopPositionKeys(strategy);
  return positions.filter((position) => {
    if (!hasOpenContractPosition(position)) return false;
    if (keys.size === 0) return false;
    return keys.has(normalizeLiveInstrumentKey(position.symbol));
  });
}

function formatAssetAmount(value: unknown, currency?: string): string {
  const num = finiteNumber(value);
  if (num == null) return '--';
  if (Math.abs(num) > 0 && Math.abs(num) < 0.0001) return num.toExponential(2);
  const ccy = String(currency || '').toUpperCase();
  if (ccy === 'USDT' || stableCoins.has(ccy)) return num.toFixed(2);
  return num.toFixed(Math.abs(num) >= 100 ? 2 : 6);
}

function assetUsdValue(row: AccountBalanceRow, priceMap: Record<string, number>): number {
  const total = finiteNumber(row.total) || 0;
  const currency = String(row.currency || '').toUpperCase();
  if (!currency || total <= 0) return 0;
  if (stableCoins.has(currency)) return total;
  const price = finiteNumber(priceMap[currency]) || 0;
  return price > 0 ? total * price : 0;
}

function assetBadgeClass(currency?: string): string {
  const ccy = String(currency || '').toUpperCase();
  if (ccy === 'USDT') return 'bg-green-500/20 text-green-300';
  if (ccy === 'BTC') return 'bg-orange-500/20 text-orange-300';
  if (ccy === 'ETH') return 'bg-blue-500/20 text-blue-300';
  return 'bg-gray-500/20 text-gray-300';
}

function stringifyErrorDetail(value: unknown): string | null {
  if (value == null) return null;
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function errorMessage(error: unknown): string {
  const responseData = (error as { response?: { data?: unknown } } | null)?.response?.data;
  if (responseData && typeof responseData === 'object') {
    const record = responseData as Record<string, unknown>;
    const direct = stringifyErrorDetail(record.detail ?? record.message);
    if (direct) return direct;
    const nested = record.error;
    if (nested && typeof nested === 'object') {
      const nestedRecord = nested as Record<string, unknown>;
      const nestedMessage = stringifyErrorDetail(nestedRecord.message ?? nestedRecord.detail ?? nestedRecord.details);
      if (nestedMessage) return nestedMessage;
    }
    const fallback = stringifyErrorDetail(record.error ?? record.details);
    if (fallback) return fallback;
  }
  if (typeof responseData === 'string') return responseData;
  if (error instanceof Error) return error.message;
  return String(error || '请求失败');
}

function preflightKey(strategyId: number, accountId: string): string {
  return `${strategyId}:${accountId || 'default'}`;
}

function failedPreflight(item: string, detail: string): LiveExecutionPreflight {
  return {
    allPassed: false,
    checks: [{ item, passed: false, detail }],
  };
}

function boundAccountIds(strategy: LiveExecutionStrategy): string[] {
  const ids = Array.isArray(strategy.accountIds)
    ? strategy.accountIds
    : strategy.accountId
      ? [strategy.accountId]
      : [];
  return Array.from(new Set(ids.map((id) => String(id || 'default'))));
}

function accountBindingFor(strategy: LiveExecutionStrategy | null, accountId: string) {
  if (!strategy) return undefined;
  const normalized = accountId || 'default';
  return (strategy.accountBindings || []).find((binding) => binding.accountId === normalized);
}

function accountLabel(accounts: LiveExecutionAccount[], accountId: string): string {
  return accounts.find((account) => account.accountId === accountId)?.name || accountId || 'default';
}

function accountExchangeLabel(account?: LiveExecutionAccount | null): string {
  const exchange = String(account?.exchange || '').toLowerCase();
  if (exchange === 'binanceusdm') return 'Binance USD-M';
  if (exchange === 'okx') return 'OKX';
  return exchange.toUpperCase() || 'OKX';
}

function LiveAccountTabs({
  accounts,
  value,
  onChange,
  className,
  ariaLabel = '实盘账户切换',
}: {
  accounts: LiveExecutionAccount[];
  value: string;
  onChange: (accountId: string) => void;
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      data-account-management-control
      className={clsx('grid min-h-8 grid-cols-2 rounded-lg border border-white/10 bg-[#0b1220]/95 p-1', className)}
    >
      {accounts.map((account) => {
        const selected = account.accountId === value;
        return (
          <button
            key={account.accountId}
            type="button"
            role="tab"
            aria-selected={selected}
            title={account.name}
            onClick={() => onChange(account.accountId)}
            className={clsx(
              'min-w-0 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors',
              selected
                ? 'bg-blue-600 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.18)]'
                : 'text-gray-400 hover:bg-white/[0.05] hover:text-gray-100',
            )}
          >
            {accountExchangeLabel(account)}
          </button>
        );
      })}
      {accounts.length === 0 && (
        <span className="col-span-2 inline-flex items-center justify-center px-3 py-1.5 text-xs text-gray-500">
          暂无实盘账户
        </span>
      )}
    </div>
  );
}

function canUseAccountForLiveDeployment(account?: LiveExecutionAccount | null): boolean {
  return Boolean(account && ['okx', 'binanceusdm'].includes(account.exchange) && !account.displayOnly);
}

function liveSubscriptionIdForAccount(strategy: LiveExecutionStrategy, accountId: string): number | null {
  const normalized = accountId || 'default';
  const binding = accountBindingFor(strategy, normalized);
  const raw = binding?.liveSubscriptionId ?? (
    strategy.accountId === normalized ? strategy.liveSubscriptionId : null
  );
  const id = Number(raw);
  return Number.isFinite(id) && id > 0 ? id : null;
}

function deploymentStatusForAccount(strategy: LiveExecutionStrategy, accountId: string): string {
  const normalized = accountId || 'default';
  const binding = accountBindingFor(strategy, normalized);
  const raw = binding?.deploymentStatus ?? (
    strategy.accountId === normalized ? strategy.deploymentStatus : null
  );
  return String(raw || '').toLowerCase();
}

export default function LiveExecutionCenter() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { isGuest } = useAuth();
  const readOnly = isGuest;
  const [strategies, setStrategies] = useState<LiveExecutionStrategy[]>([]);
  const [selectedStrategyId, setSelectedStrategyId] = useState<number | null>(() => {
    const raw = Number(searchParams.get('strategy_id') || searchParams.get('strategyId'));
    return Number.isFinite(raw) && raw > 0 ? raw : null;
  });
  const [candidateStrategyId, setCandidateStrategyId] = useState<number | null>(selectedStrategyId);
  const [selectedStrategyIds, setSelectedStrategyIds] = useState<number[]>(() =>
    selectedStrategyId ? [selectedStrategyId] : [],
  );
  const [filter, setFilter] = useState<StrategyFilter>('all');
  const [livePanelStatusFilter, setLivePanelStatusFilter] = useState<LivePanelStatusFilter>('running');
  const [sortMode, setSortMode] = useState<SortMode>('return_desc');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [actioningId, setActioningId] = useState<number | null>(null);
  const [, setError] = useState('');
  const [preflights, setPreflights] = useState<Record<string, LiveExecutionPreflight>>({});
  const [openPreflightResultKey, setOpenPreflightResultKey] = useState<string | null>(null);
  const [closedPreflightResultKey, setClosedPreflightResultKey] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<LiveExecutionAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState('default');
  const [accountManagementOpen, setAccountManagementOpen] = useState(false);
  const [accountFormOpen, setAccountFormOpen] = useState(false);
  const [accountSaving, setAccountSaving] = useState(false);
  const [accountForm, setAccountForm] = useState<AccountFormState>(emptyAccountForm);
  const [accountBindingAction, setAccountBindingAction] = useState<string | null>(null);
  const [balances, setBalances] = useState<AccountBalanceRow[]>([]);
  const [balanceDetail, setBalanceDetail] = useState<{ trading: AccountBalanceRow[]; funding: AccountBalanceRow[] }>({
    trading: [],
    funding: [],
  });
  const [accountReturnRates, setAccountReturnRates] = useState<LiveExecutionAccountReturnRates | null>(null);
  const [priceMap, setPriceMap] = useState<Record<string, number>>({});
  const [positions, setPositions] = useState<LiveExecutionPosition[]>([]);
  const [historyOrders, setHistoryOrders] = useState<LiveExecutionOrder[]>([]);
  const [accountLoading, setAccountLoading] = useState(false);
  const [accountError, setAccountError] = useState('');
  const [accountFormError, setAccountFormError] = useState('');
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const assetSnapshotRequestSeqRef = useRef(0);
  const executionSnapshotRequestSeqRef = useRef(0);

  const selectedStrategy = useMemo(
    () => strategies.find((strategy) => strategy.strategyId === selectedStrategyId) || null,
    [selectedStrategyId, strategies],
  );

  const selectedStrategies = useMemo(
    () =>
      selectedStrategyIds
        .map((strategyId) => strategies.find((strategy) => strategy.strategyId === strategyId))
        .filter((strategy): strategy is LiveExecutionStrategy => Boolean(strategy)),
    [selectedStrategyIds, strategies],
  );

  const selectedAccount = useMemo(
    () => accounts.find((account) => account.accountId === selectedAccountId) || accounts[0] || null,
    [accounts, selectedAccountId],
  );

  const selectedExchangeAlias = selectedAccount?.exchangeAlias || 'okx';
  const isBinanceUsdmAccount = selectedAccount?.exchange === 'binanceusdm';
  const selectedAccountExchangeLabel = accountExchangeLabel(selectedAccount);
  const currentAccountDeployments = useMemo(
    () =>
      strategies
        .map((strategy) => {
          const liveSubscriptionId = liveSubscriptionIdForAccount(strategy, selectedAccountId);
          const binding = accountBindingFor(strategy, selectedAccountId);
          if (!liveSubscriptionId && !binding?.deployed) return null;
          return {
            strategy,
            liveSubscriptionId,
            deploymentStatus: deploymentStatusForAccount(strategy, selectedAccountId),
          };
        })
        .filter((item): item is {
          strategy: LiveExecutionStrategy;
          liveSubscriptionId: number | null;
          deploymentStatus: string;
        } => Boolean(item))
        .sort((left, right) => {
          if (left.strategy.strategyId === selectedStrategyId) return -1;
          if (right.strategy.strategyId === selectedStrategyId) return 1;
          return timestampMs(right.strategy.updatedAt || right.strategy.createdAt)
            - timestampMs(left.strategy.updatedAt || left.strategy.createdAt)
            || right.strategy.strategyId - left.strategy.strategyId;
        }),
    [selectedAccountId, selectedStrategyId, strategies],
  );

  const livePanelStatusCounts = useMemo(() => {
    return {
      all: currentAccountDeployments.length,
      running: currentAccountDeployments.filter((item) => item.deploymentStatus === 'running').length,
      paused: currentAccountDeployments.filter((item) => item.deploymentStatus === 'paused').length,
    } satisfies Record<LivePanelStatusFilter, number>;
  }, [currentAccountDeployments]);

  const filteredAccountDeployments = useMemo(
    () =>
      currentAccountDeployments.filter((item) =>
        liveDeploymentMatchesFilter(item.deploymentStatus, livePanelStatusFilter),
      ),
    [currentAccountDeployments, livePanelStatusFilter],
  );

  const strategyFilterCounts = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    const searchableStrategies = strategies.filter(
      (strategy) => isRunningStrategy(strategy) && strategyMatchesSearch(strategy, keyword),
    );
    return {
      all: searchableStrategies.length,
      deployable: searchableStrategies.filter(isRunningDeployableStrategy).length,
      deployed: searchableStrategies.filter((strategy) => Boolean(strategy.deployed)).length,
    } satisfies Record<StrategyFilter, number>;
  }, [search, strategies]);

  const filteredStrategies = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    const out = strategies.filter((strategy) => {
      return strategyMatchesFilter(strategy, filter) && strategyMatchesSearch(strategy, keyword);
    });
    return [...out].sort((left, right) => {
      if (sortMode === 'created_desc') {
        return timestampMs(right.updatedAt || right.createdAt) - timestampMs(left.updatedAt || left.createdAt);
      }
      const leftReturn = finiteNumber(left.returnPct);
      const rightReturn = finiteNumber(right.returnPct);
      if (leftReturn == null && rightReturn == null) return right.strategyId - left.strategyId;
      if (leftReturn == null) return 1;
      if (rightReturn == null) return -1;
      return sortMode === 'return_desc'
        ? rightReturn - leftReturn || right.strategyId - left.strategyId
        : leftReturn - rightReturn || right.strategyId - left.strategyId;
    });
  }, [filter, search, sortMode, strategies]);

  const contractPositions = useMemo(
    () => positions.filter((position) => !isSpotPosition(position)),
    [positions],
  );

  const spotPositions = useMemo(
    () => positions.filter((position) => isSpotPosition(position)),
    [positions],
  );

  const totalAssetUsd = useMemo(
    () => balances.reduce((sum, row) => sum + assetUsdValue(row, priceMap), 0),
    [balances, priceMap],
  );

  const fundingAssetCount = useMemo(
    () => balanceDetail.funding.filter((row) => (finiteNumber(row.total) || 0) > 0).length,
    [balanceDetail.funding],
  );

  const tradingAssetCount = useMemo(
    () => balanceDetail.trading.filter((row) => (finiteNumber(row.total) || 0) > 0).length,
    [balanceDetail.trading],
  );

  useEffect(() => {
    const currencies = Array.from(
      new Set(
        balances
          .map((row) => String(row.currency || '').toUpperCase())
          .filter((currency) => currency && !stableCoins.has(currency)),
      ),
    );
    if (currencies.length === 0) {
      setPriceMap({});
      return;
    }

    let cancelled = false;
    void Promise.all(
      currencies.map(async (currency) => {
        try {
          const ticker = await marketApi.getTicker('okx', `${currency}/USDT`);
          return [currency, finiteNumber(ticker.last) || 0] as const;
        } catch {
          return [currency, 0] as const;
        }
      }),
    ).then((items) => {
      if (cancelled) return;
      const next: Record<string, number> = {};
      items.forEach(([currency, price]) => {
        if (price > 0) next[currency] = price;
      });
      setPriceMap(next);
    });

    return () => {
      cancelled = true;
    };
  }, [balances]);

  const syncStrategyParam = useCallback(
    (strategyId: number | null) => {
      const next = new URLSearchParams(searchParams);
      if (strategyId) next.set('strategy_id', String(strategyId));
      else next.delete('strategy_id');
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const loadStrategies = useCallback(async (options: { silent?: boolean } = {}) => {
    const silent = Boolean(options.silent);
    if (!silent) {
      setLoading(true);
      setError('');
    }
    try {
      const res = await liveExecutionApi.listStrategies();
      const nextStrategies = res.strategies || [];
      setStrategies(nextStrategies);
      const addedIds = nextStrategies
        .filter((strategy) => strategy.added || strategy.deployed)
        .map((strategy) => strategy.strategyId);
      setSelectedStrategyIds(addedIds);
      setSelectedStrategyId((prev) => {
        const available = new Set(nextStrategies.map((strategy) => strategy.strategyId));
        if (prev && available.has(prev)) return prev;
        const restored = addedIds[0] || nextStrategies[0]?.strategyId || null;
        syncStrategyParam(restored);
        return restored;
      });
      setCandidateStrategyId((prev) => {
        const available = new Set(nextStrategies.map((strategy) => strategy.strategyId));
        if (prev && available.has(prev)) return prev;
        return addedIds[0] || nextStrategies[0]?.strategyId || null;
      });
    } catch (err) {
      if (!silent) setError(errorMessage(err));
    } finally {
      if (!silent) setLoading(false);
    }
  }, [syncStrategyParam]);

  const loadAccounts = useCallback(async () => {
    try {
      const res = await liveExecutionApi.listAccounts();
      const nextAccounts = res.accounts || [];
      setAccounts(nextAccounts);
      setSelectedAccountId((prev) => {
        if (nextAccounts.some((account) => account.accountId === prev)) return prev;
        return nextAccounts[0]?.accountId || 'default';
      });
    } catch (err) {
      setAccountError(errorMessage(err));
    }
  }, []);

  const applyLiveAssetSnapshot = useCallback((snapshot: LiveAssetSnapshot) => {
    setBalances(snapshot.balances || []);
    setBalanceDetail({
      trading: snapshot.balanceDetail?.trading || [],
      funding: snapshot.balanceDetail?.funding || [],
    });
    setAccountReturnRates(snapshot.returnRates || null);
  }, []);

  const loadAssetSnapshot = useCallback(async (options: { silent?: boolean; preferCache?: boolean } = {}) => {
    const accountId = selectedAccountId;
    const requestSeq = ++assetSnapshotRequestSeqRef.current;
    const cachedSnapshot = options.preferCache ? readCachedLiveAssetSnapshot(accountId) : null;
    const canRenderCachedSnapshot = Boolean(cachedSnapshot && hasRenderableLiveAssetSnapshot(cachedSnapshot));
    if (cachedSnapshot && canRenderCachedSnapshot) {
      applyLiveAssetSnapshot(cachedSnapshot);
      setAccountLoading(false);
    }
    const silent = Boolean(options.silent) || canRenderCachedSnapshot;
    const showLoading = !silent && !canRenderCachedSnapshot;
    if (!silent) {
      setAccountError('');
    }
    if (showLoading) setAccountLoading(true);
    if (selectedAccount && !canUseAccountForLiveDeployment(selectedAccount)) {
      const detail = selectedAccount.displayOnly
        ? '该 Binance 账户只配置了 API Key，缺少 Secret Key，不能读取私有资产、持仓或订单。'
        : '当前账户未通过实盘私有读取条件。';
      if (assetSnapshotRequestSeqRef.current !== requestSeq) return;
      applyLiveAssetSnapshot({
        balances: [],
        balanceDetail: { trading: [], funding: [] },
        returnRates: {
          source: selectedAccount.exchange,
          error: detail,
        },
      });
      if (!silent) setAccountError(detail);
      if (showLoading) setAccountLoading(false);
      return;
    }
    try {
      const [balanceRes, balanceDetailRes] = await Promise.all([
        liveExecutionApi.getAccountBalance(accountId),
        liveExecutionApi.getAccountBalanceDetail(accountId),
      ]);
      if (assetSnapshotRequestSeqRef.current !== requestSeq) return;
      const nextSnapshot: LiveAssetSnapshot = {
        balances: balanceRes.balance || [],
        balanceDetail: {
          trading: balanceDetailRes.trading || [],
          funding: balanceDetailRes.funding || [],
        },
        returnRates: balanceDetailRes.returnRates || null,
      };
      applyLiveAssetSnapshot(nextSnapshot);
      if (assetSnapshotRequestSeqRef.current === requestSeq) setAccountError('');
      writeCachedLiveAssetSnapshot(accountId, nextSnapshot);
    } catch (err) {
      if (!silent && assetSnapshotRequestSeqRef.current === requestSeq) setAccountError(errorMessage(err));
    } finally {
      if (showLoading && assetSnapshotRequestSeqRef.current === requestSeq) setAccountLoading(false);
    }
  }, [applyLiveAssetSnapshot, selectedAccount, selectedAccountId]);

  const loadExecutionSnapshot = useCallback(async (options: { silent?: boolean } = {}) => {
    const accountId = selectedAccountId;
    const requestSeq = ++executionSnapshotRequestSeqRef.current;
    const silent = Boolean(options.silent);
    if (selectedAccount && !canUseAccountForLiveDeployment(selectedAccount)) {
      if (executionSnapshotRequestSeqRef.current !== requestSeq) return;
      setPositions([]);
      setHistoryOrders([]);
      return;
    }
    try {
      const [positionsRes, historyRes] = await Promise.all([
        liveExecutionApi.listPositions(accountId),
        liveExecutionApi.listOrderHistory(accountId, undefined, 30),
      ]);
      if (executionSnapshotRequestSeqRef.current !== requestSeq) return;
      setPositions(positionsRes.positions || []);
      setHistoryOrders(historyRes.orders || []);
    } catch (err) {
      if (!silent && executionSnapshotRequestSeqRef.current === requestSeq) setAccountError(errorMessage(err));
    }
  }, [selectedAccount, selectedAccountId]);

  const loadAccountSnapshot = useCallback(async (options: { silent?: boolean; preferCache?: boolean } = {}) => {
    await Promise.all([
      loadAssetSnapshot(options),
      loadExecutionSnapshot({ silent: true }),
    ]);
  }, [loadAssetSnapshot, loadExecutionSnapshot]);

  const refreshLivePanelData = useCallback(async () => {
    await Promise.all([
      loadStrategies({ silent: true }),
      loadExecutionSnapshot({ silent: true }),
    ]);
  }, [loadExecutionSnapshot, loadStrategies]);

  useEffect(() => {
    void loadStrategies();
    void loadAccounts();
  }, [loadAccounts, loadStrategies]);

  useEffect(() => {
    let cancelled = false;
    let refreshing = false;
    const runRefresh = () => {
      if (cancelled || refreshing) return;
      refreshing = true;
      void refreshLivePanelData().finally(() => {
        refreshing = false;
      });
    };
    const timer = window.setInterval(runRefresh, LIVE_PANEL_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refreshLivePanelData]);

  useEffect(() => {
    let cancelled = false;
    let refreshing = false;
    const runAssetRefresh = () => {
      if (cancelled || refreshing) return;
      refreshing = true;
      void loadAssetSnapshot({ silent: true }).finally(() => {
        refreshing = false;
      });
    };
    const timer = window.setInterval(runAssetRefresh, LIVE_ASSET_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [loadAssetSnapshot]);

  useEffect(() => {
    applyLiveAssetSnapshot(EMPTY_LIVE_ASSET_SNAPSHOT);
    setAccountError('');
    setAccountLoading(false);
  }, [applyLiveAssetSnapshot, selectedAccountId]);

  useEffect(() => {
    void loadAccountSnapshot({ preferCache: true });
  }, [loadAccountSnapshot]);

  useEffect(() => {
    setOpenPreflightResultKey(null);
    setClosedPreflightResultKey(null);
  }, [selectedAccountId, selectedStrategyId]);

  const selectStrategy = (strategyId: number) => {
    setSelectedStrategyId(strategyId);
    setCandidateStrategyId(strategyId);
    const strategy = strategies.find((item) => item.strategyId === strategyId);
    const ids = strategy ? boundAccountIds(strategy) : [];
    if (ids.length > 0 && !ids.includes(selectedAccountId)) {
      setSelectedAccountId(ids[0]);
    }
    syncStrategyParam(strategyId);
  };

  const createLiveAccount = async () => {
    if (readOnly) return;
    setAccountSaving(true);
    setError('');
    setAccountError('');
    setAccountFormError('');
    try {
      const res = await liveExecutionApi.createAccount({
        name: accountForm.name,
        exchange: accountForm.exchange,
        apiKey: accountForm.apiKey,
        apiSecret: accountForm.apiSecret,
        passphrase: accountForm.exchange === 'okx' ? accountForm.passphrase : undefined,
        testnet: accountForm.testnet,
      });
      await loadAccounts();
      setSelectedAccountId(res.account.accountId);
      setAccountForm(emptyAccountForm);
      setAccountFormOpen(false);
    } catch (err) {
      setAccountFormError(errorMessage(err));
    } finally {
      setAccountSaving(false);
    }
  };

  const addStrategy = async (strategy: LiveExecutionStrategy) => {
    if (readOnly) return;
    if (!canUseAccountForLiveDeployment(selectedAccount)) {
      setError('请先选择已配置 Secret Key 且通过权限测试的 OKX 或 Binance USD-M 账户。');
      return;
    }
    setActioningId(strategy.strategyId);
    setError('');
    try {
      const res = await liveExecutionApi.updateStrategy(strategy.strategyId, {
        added: true,
        accountId: selectedAccountId,
        bindAccount: false,
      });
      setStrategies((prev) =>
        prev.map((item) => (item.strategyId === strategy.strategyId ? res.strategy : item)),
      );
      setSelectedStrategyIds((prev) =>
        prev.includes(strategy.strategyId) ? prev : [...prev, strategy.strategyId],
      );
      selectStrategy(strategy.strategyId);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setActioningId(null);
    }
  };

  const removeStrategyFromWorkspace = (strategy: LiveExecutionStrategy) => {
    if (readOnly) return;
    const blockReason = liveWorkspaceRemoveBlockReason(strategy);
    if (blockReason) {
      setConfirmState({
        title: '无法移出实盘策略',
        content: `${blockReason}\n策略：${strategy.strategyName}`,
        confirmText: '知道了',
        tone: 'warning',
        onConfirm: () => {
          setConfirmState(null);
        },
      });
      return;
    }

    setConfirmState({
      title: '移出实盘列表',
      content: `将把该策略从实盘策略列表移出，并解除当前工作台绑定记录；历史实盘执行审计记录会保留。\n策略：${strategy.strategyName}`,
      confirmText: '移出',
      tone: 'warning',
      onConfirm: async () => {
        setConfirmState(null);
        setActioningId(strategy.strategyId);
        setError('');
        try {
          const res = await liveExecutionApi.updateStrategy(strategy.strategyId, { added: false });
          setStrategies((prev) =>
            prev.map((item) => (item.strategyId === strategy.strategyId ? res.strategy : item)),
          );
          setSelectedStrategyIds((prev) => prev.filter((strategyId) => strategyId !== strategy.strategyId));
          if (selectedStrategyId === strategy.strategyId) {
            setSelectedStrategyId(null);
            syncStrategyParam(null);
          }
          await loadStrategies({ silent: true });
        } catch (err) {
          setError(errorMessage(err));
        } finally {
          setActioningId(null);
        }
      },
    });
  };

  const preflightStrategyAccount = async (strategy: LiveExecutionStrategy, accountId: string) => {
    if (readOnly || !accountId) return;
    const actionKey = `${strategy.strategyId}:${accountId}`;
    const key = preflightKey(strategy.strategyId, accountId);
    setAccountBindingAction(actionKey);
    setSelectedAccountId(accountId);
    setError('');
    try {
      const account = accounts.find((item) => item.accountId === accountId);
      const res = await liveExecutionApi.preflightStrategy(strategy.strategyId, {
        accountId,
        exchange: account?.exchangeAlias || selectedExchangeAlias,
        loopInterval: 60,
      });
      setPreflights((prev) => ({ ...prev, [key]: res.preflight }));
      setClosedPreflightResultKey(null);
      setOpenPreflightResultKey(key);
      setSelectedStrategyId(strategy.strategyId);
      syncStrategyParam(strategy.strategyId);
    } catch (err) {
      setPreflights((prev) => ({
        ...prev,
        [key]: failedPreflight('账户预检失败', errorMessage(err)),
      }));
      setClosedPreflightResultKey(null);
      setOpenPreflightResultKey(key);
    } finally {
      setAccountBindingAction(null);
    }
  };

  const enableStrategyAccount = async (strategy: LiveExecutionStrategy, accountId: string) => {
    if (readOnly) return;
    if (!accountId) return;
    const actionKey = `${strategy.strategyId}:${accountId}`;
    setAccountBindingAction(actionKey);
    setSelectedAccountId(accountId);
    setError('');
    const key = preflightKey(strategy.strategyId, accountId);
    try {
      const account = accounts.find((item) => item.accountId === accountId);
      const res = await liveExecutionApi.enableStrategyAccount(strategy.strategyId, {
        accountId,
        exchange: account?.exchangeAlias || selectedExchangeAlias,
        loopInterval: 60,
        confirmPaperReviewed: true,
        confirmLiveRisk: true,
      });
      setPreflights((prev) => ({ ...prev, [key]: res.preflight }));
      setClosedPreflightResultKey(null);
      setOpenPreflightResultKey(key);
      setStrategies((prev) =>
        prev.map((item) => (item.strategyId === strategy.strategyId ? res.strategy : item)),
      );
      setSelectedStrategyIds((prev) =>
        prev.includes(strategy.strategyId) ? prev : [...prev, strategy.strategyId],
      );
      setSelectedAccountId(accountId);
      setSelectedStrategyId(strategy.strategyId);
      syncStrategyParam(strategy.strategyId);
      await loadStrategies({ silent: true });
      await loadAccountSnapshot();
    } catch (err) {
      setPreflights((prev) => ({
        ...prev,
        [key]: failedPreflight('绑定并启用下单失败', errorMessage(err)),
      }));
      setClosedPreflightResultKey(null);
      setOpenPreflightResultKey(key);
    } finally {
      setAccountBindingAction(null);
    }
  };

  const openEnableAccountConfirm = (strategy: LiveExecutionStrategy, accountId: string) => {
    if (readOnly) return;
    const account = accounts.find((item) => item.accountId === accountId);
    const alreadyBound = boundAccountIds(strategy).includes(accountId);
    setConfirmState({
      title: alreadyBound ? '确认启用下单' : '确认绑定并启用下单',
      content: `系统会先执行账户权限、策略止盈止损、源模拟仓位对齐和交易规则预检；全部通过后，${account?.name || accountId} 将立即订阅该策略后续信号并进行真实下单。\n策略：${strategy.strategyName}`,
      confirmText: alreadyBound ? '启用下单' : '绑定并启用下单',
      tone: 'danger',
      onConfirm: async () => {
        setConfirmState(null);
        await enableStrategyAccount(strategy, accountId);
      },
    });
  };

  const unbindAccountFromStrategy = async (strategy: LiveExecutionStrategy, accountId: string) => {
    if (readOnly) return;
    const actionKey = `${strategy.strategyId}:${accountId}`;
    setAccountBindingAction(actionKey);
    setError('');
    try {
      const res = await liveExecutionApi.updateStrategy(strategy.strategyId, {
        accountId,
        bindAccount: false,
      });
      setStrategies((prev) =>
        prev.map((item) => (item.strategyId === strategy.strategyId ? res.strategy : item)),
      );
      const ids = boundAccountIds(res.strategy);
      setSelectedStrategyIds((prev) =>
        prev.includes(strategy.strategyId) ? prev : [...prev, strategy.strategyId],
      );
      if (ids.length > 0 && selectedStrategyId === strategy.strategyId && accountId === selectedAccountId) {
        setSelectedAccountId(ids[0]);
      }
      setSelectedStrategyId(strategy.strategyId);
      syncStrategyParam(strategy.strategyId);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setAccountBindingAction(null);
    }
  };

  const pauseDeployment = async (strategy: LiveExecutionStrategy) => {
    if (readOnly) return;
    setActioningId(strategy.strategyId);
    try {
      const res = await liveExecutionApi.pauseStrategy(strategy.strategyId, { accountId: selectedAccountId });
      setStrategies((prev) =>
        prev.map((item) => (item.strategyId === strategy.strategyId ? res.strategy : item)),
      );
      await loadStrategies({ silent: true });
      await loadAccountSnapshot();
    } finally {
      setActioningId(null);
    }
  };

  const resumeDeployment = async (strategy: LiveExecutionStrategy) => {
    if (readOnly) return;
    setActioningId(strategy.strategyId);
    try {
      const res = await liveExecutionApi.resumeStrategy(strategy.strategyId, { accountId: selectedAccountId });
      setStrategies((prev) =>
        prev.map((item) => (item.strategyId === strategy.strategyId ? res.strategy : item)),
      );
      await loadStrategies({ silent: true });
      await loadAccountSnapshot();
    } finally {
      setActioningId(null);
    }
  };

  const stopDeployment = async (strategy: LiveExecutionStrategy) => {
    if (readOnly) return;
    setActioningId(strategy.strategyId);
    try {
      const res = await liveExecutionApi.stopStrategy(strategy.strategyId, { accountId: selectedAccountId });
      setStrategies((prev) =>
        prev.map((item) => (item.strategyId === strategy.strategyId ? res.strategy : item)),
      );
      await loadStrategies({ silent: true });
      await loadAccountSnapshot();
    } finally {
      setActioningId(null);
    }
  };

  const closeStrategyPositionsThenStop = async (
    strategy: LiveExecutionStrategy,
    positionsToClose: LiveExecutionPosition[],
  ) => {
    if (readOnly) return;
    setActioningId(strategy.strategyId);
    try {
      const closeSymbols = Array.from(
        new Set(positionsToClose.map((position) => String(position.symbol || '').trim()).filter(Boolean)),
      );
      for (const symbol of closeSymbols) {
        await liveExecutionApi.closePosition(selectedAccountId, {
          symbol,
          closeAll: true,
          confirmLiveRisk: true,
        });
      }
      const res = await liveExecutionApi.stopStrategy(strategy.strategyId, { accountId: selectedAccountId });
      setStrategies((prev) =>
        prev.map((item) => (item.strategyId === strategy.strategyId ? res.strategy : item)),
      );
      await loadStrategies({ silent: true });
      await loadAccountSnapshot();
    } finally {
      setActioningId(null);
    }
  };

  const openStopConfirm = (
    strategy: LiveExecutionStrategy,
  ) => {
    if (readOnly) return;
    const relatedPositions = liveStopRelatedContractPositions(strategy, contractPositions);
    if (relatedPositions.length > 0) {
      const symbols = relatedPositions
        .map((position) => position.symbol || position.currency || '--')
        .join(' / ');
      setConfirmState({
        title: '确认平仓并停止策略',
        content: `检测到当前账户仍有该实盘策略相关合约持仓：${symbols}。\n确认后会先对这些持仓逐个市价全平，全部完成后自动停止实盘订阅；取消则不执行任何操作。\n策略：${strategy.deploymentStrategyName || strategy.strategyName}`,
        confirmText: '确认平仓并停止',
        tone: 'danger',
        onConfirm: async () => {
          setConfirmState(null);
          await closeStrategyPositionsThenStop(strategy, relatedPositions);
        },
      });
      return;
    }

    setConfirmState({
      title: '确认停止实盘策略',
      content: `将停止实盘策略运行，但不会自动平仓。\n策略：${strategy.deploymentStrategyName || strategy.strategyName}`,
      confirmText: '停止实盘',
      tone: 'warning',
      onConfirm: async () => {
        setConfirmState(null);
        await stopDeployment(strategy);
      },
    });
  };

  const activePreflight = selectedStrategy ? preflights[preflightKey(selectedStrategy.strategyId, selectedAccountId)] : undefined;
  const renderEnableCheckResult = () => {
    if (!selectedStrategy || !activePreflight) return null;
    const currentPreflightKey = preflightKey(selectedStrategy.strategyId, selectedAccountId);
    const preflightResultId = `preflight-result-${selectedStrategy.strategyId}-${selectedAccountId}`;
    const visiblePreflight = activePreflight;
    const resultPanelPinned = openPreflightResultKey === currentPreflightKey;
    const resultPanelDismissed = closedPreflightResultKey === currentPreflightKey && !resultPanelPinned;
    return (
      <div className="group relative z-20 inline-flex min-w-0">
        <button
          type="button"
          onClick={() => {
            const nextPinned = !resultPanelPinned;
            setClosedPreflightResultKey(nextPinned ? null : currentPreflightKey);
            setOpenPreflightResultKey(nextPinned ? currentPreflightKey : null);
          }}
          aria-describedby={preflightResultId}
          aria-controls={preflightResultId}
          aria-expanded={resultPanelPinned}
          className={clsx(
            'inline-flex h-7 items-center justify-center gap-1.5 rounded-md border px-2.5 text-[11px] font-semibold transition-colors',
            preflightResultButtonTone(activePreflight),
          )}
        >
          {activePreflight.allPassed ? (
            <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          )}
          <span className="truncate">查看最近启用检查</span>
        </button>
        <div
          id={preflightResultId}
          role="dialog"
          aria-label="启用检查结果"
          className={clsx(
            'pointer-events-none fixed left-1/2 top-[clamp(5rem,16vh,8rem)] z-[80] w-[min(760px,calc(100vw-2rem))] max-h-[calc(100vh-7rem)] -translate-x-1/2 translate-y-1 overflow-hidden rounded-xl border border-crypto-border bg-[#070d13] p-3 opacity-0 shadow-2xl shadow-black/60 transition duration-150',
            !resultPanelDismissed && 'group-hover:pointer-events-auto group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:translate-y-0 group-focus-within:opacity-100',
            resultPanelPinned && 'pointer-events-auto translate-y-0 opacity-100',
          )}
        >
          <div className="mb-2 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-gray-100">启用检查结果</div>
              <div className="mt-0.5 truncate text-[11px] text-gray-500">
                {accountLabel(accounts, selectedAccountId)} · {compactName(selectedStrategy.strategyName, `策略 #${selectedStrategy.strategyId}`)}
              </div>
            </div>
            <span
              className={clsx(
                'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold',
                visiblePreflight.allPassed
                  ? 'bg-green-500/15 text-green-300'
                  : 'bg-red-500/15 text-red-300',
              )}
            >
              {visiblePreflight.allPassed ? '通过' : '失败'}
            </span>
          <button
            type="button"
            aria-label="关闭启用检查结果"
            onClick={(event) => {
              event.stopPropagation();
              setOpenPreflightResultKey(null);
              setClosedPreflightResultKey(currentPreflightKey);
            }}
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-crypto-border bg-crypto-bg text-gray-400 transition hover:border-gray-500 hover:text-gray-100"
          >
            <X className="h-3.5 w-3.5" />
          </button>
          </div>
          <div className="max-h-[min(28rem,calc(100vh-13rem))] overscroll-contain overflow-y-auto rounded-lg border border-crypto-border bg-black/20 px-3 py-2 font-mono text-[11px] leading-5 text-gray-300">
            {visiblePreflight.checks.map((check, index) => (
              <div key={`${check.item}-${index}`} className="grid grid-cols-[112px_minmax(0,1fr)] gap-2 py-0.5">
                <span className={clsx('font-semibold', preflightLogTone(check.passed))}>
                  [{check.passed ? 'PASS' : 'FAIL'}] #{String(index + 1).padStart(2, '0')}
                </span>
                <span className="min-w-0 break-words">
                  <span className="text-gray-100">{check.item}</span>
                  {check.detail && <span className="text-gray-500"> - {check.detail}</span>}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  };

  const renderBalancePanel = (
    title: string,
    subtitle: string,
    icon: 'funding' | 'trading',
    rows: AccountBalanceRow[],
  ) => {
    const visibleRows = rows
      .filter((row) => (finiteNumber(row.total) || 0) > 0)
      .sort((left, right) => assetUsdValue(right, priceMap) - assetUsdValue(left, priceMap));
    const Icon = icon === 'funding' ? Landmark : Briefcase;
    const accent = icon === 'funding' ? 'text-blue-300' : 'text-emerald-300';
    return (
      <div className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-bg">
        <div className="flex items-center gap-2 border-b border-crypto-border px-3 py-2.5">
          <Icon className={clsx('h-4 w-4', accent)} />
          <span className="text-sm font-semibold text-gray-100">{title}</span>
          <span className="ml-auto text-[10px] text-gray-500">{subtitle}</span>
        </div>
        <div className="p-3">
          {visibleRows.length === 0 ? (
            <div className="py-6 text-center text-xs text-gray-600">暂无资产</div>
          ) : (
            <div className="space-y-1">
              <div className="grid grid-cols-4 border-b border-crypto-border/60 pb-2 text-[10px] font-semibold text-gray-500">
                <span>币种</span>
                <span className="text-right">总计</span>
                <span className="text-right">可用</span>
                <span className="text-right">估值</span>
              </div>
              {visibleRows.map((row) => {
                const currency = String(row.currency || '--').toUpperCase();
                const usdValue = assetUsdValue(row, priceMap);
                return (
                  <div
                    key={`${title}-${currency}`}
                    className="grid grid-cols-4 items-center gap-2 rounded-md px-1 py-1.5 text-xs transition-colors hover:bg-white/[0.03]"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <span className={clsx('flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold', assetBadgeClass(currency))}>
                        {currency.slice(0, 1)}
                      </span>
                      <span className="truncate font-semibold text-gray-100">{currency}</span>
                    </div>
                    <span className="text-right font-mono text-gray-100">{formatAssetAmount(row.total, currency)}</span>
                    <span className={clsx('text-right font-mono', icon === 'funding' ? 'text-blue-300' : 'text-emerald-300')}>
                      {formatAssetAmount(row.free, currency)}
                    </span>
                    <span className="text-right font-mono text-gray-400">
                      {usdValue > 0 ? formatUsd(usdValue) : '--'}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderTotalAssetPanel = () => {
    const displayedTotalAssetUsd = finiteNumber(accountReturnRates?.valuationUsd) ?? totalAssetUsd;
    const returnItems = [
      { label: '1日收益率', value: accountReturnRates?.oneDay },
      { label: '7日收益率', value: accountReturnRates?.sevenDay },
      { label: '30日收益率', value: accountReturnRates?.thirtyDay },
    ];
    const assetSummaryItems = isBinanceUsdmAccount
      ? [
          { value: tradingAssetCount, tone: 'text-emerald-300', label: '合约钱包币种' },
          { value: contractPositions.length, tone: 'text-amber-300', label: '合约持仓' },
          { value: historyOrders.length, tone: 'text-blue-300', label: '订单审计' },
        ]
      : [
          { value: fundingAssetCount, tone: 'text-blue-300', label: '资金账户币种' },
          { value: tradingAssetCount, tone: 'text-emerald-300', label: '交易账户币种' },
          { value: contractPositions.length, tone: 'text-amber-300', label: '合约持仓' },
          { value: spotPositions.length, tone: 'text-gray-100', label: '现货资产' },
        ];
    return (
      <div className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-bg">
        <div className="flex items-center gap-2 border-b border-crypto-border px-3 py-2.5">
          <Wallet className="h-4 w-4 text-blue-300" />
          <span className="text-sm font-semibold text-gray-100">总资产（估算）</span>
          <span className="ml-auto text-[10px] text-gray-500">{selectedAccountExchangeLabel}</span>
        </div>
        <div className="p-3">
          <div className="rounded-lg bg-crypto-card px-3 py-3">
            <div className="text-[10px] font-semibold text-gray-500">估算资产</div>
            <div className="mt-1 text-2xl font-bold text-white">{formatUsd(displayedTotalAssetUsd)}</div>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 border-b border-crypto-border/60 pb-3 text-xs">
            {returnItems.map((item) => (
              <div key={item.label} className="rounded-md bg-white/[0.02] px-2 py-2">
                <div className={clsx('font-mono text-sm font-semibold', signedMetricColor(item.value))}>
                  {formatReturnRate(item.value)}
                </div>
                <div className="mt-0.5 text-[10px] text-gray-500">{item.label}</div>
              </div>
            ))}
          </div>
          <div className={clsx('mt-3 grid gap-2 text-xs', isBinanceUsdmAccount ? 'grid-cols-3' : 'grid-cols-2')}>
            {assetSummaryItems.map((item) => (
              <div key={item.label} className="rounded-md px-1 py-1.5">
                <div className={clsx('font-mono text-sm font-semibold', item.tone)}>{item.value}</div>
                <div className="mt-0.5 text-[10px] text-gray-500">{item.label}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="flex h-full flex-col gap-5 p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-normal text-white">
            <Rocket className="h-6 w-6 text-red-300" />
            实盘交易
          </h1>
          <div className="mt-1 text-xs text-gray-500">OKX 与 Binance USD-M 私有账户 · 策略加入式部署</div>
        </div>
        <button
          type="button"
          onClick={() => {
            void loadStrategies();
            void loadAccounts();
            void loadAccountSnapshot();
          }}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-3 text-sm font-semibold text-gray-200 hover:border-blue-500/50 hover:text-blue-200"
        >
          {loading || accountLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Activity className="h-4 w-4" />}
          刷新
        </button>
      </header>

      <section className="min-w-0 rounded-xl border border-crypto-border bg-crypto-card p-4">
          <div
            onClick={(event) => {
              if (event.target instanceof Element && event.target.closest('[data-account-management-control]')) return;
              setAccountManagementOpen((open) => !open);
            }}
            className={clsx(
              'flex cursor-pointer flex-wrap items-stretch justify-between gap-3',
              accountManagementOpen && 'mb-3 border-b border-crypto-border pb-3',
            )}
          >
            <button
              type="button"
              aria-expanded={accountManagementOpen}
              aria-controls="live-account-management-panel"
              title={accountManagementOpen ? '收起实盘账户管理' : '展开实盘账户管理'}
              className="liveAccountManagementToggle group flex min-w-[240px] flex-1 items-center gap-2 rounded-lg px-1 py-1 text-left outline-none transition-colors hover:bg-white/[0.03] hover:text-white focus-visible:ring-2 focus-visible:ring-blue-500/50"
            >
              <KeyRound className="h-5 w-5 text-red-300" />
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-white">实盘账户管理</div>
                <div className="text-[11px] text-gray-500">选择账户 / 新增 OKX 或 Binance USD-M API Key</div>
              </div>
              <ChevronDown
                className={clsx(
                  'ml-auto h-4 w-4 shrink-0 text-gray-500 transition-transform group-hover:text-gray-300',
                  accountManagementOpen ? 'rotate-180' : '-rotate-90',
                )}
              />
            </button>
            {accountManagementOpen && (
              <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-2 sm:flex-nowrap">
                <LiveAccountTabs
                  accounts={accounts}
                  value={selectedAccountId}
                  onChange={setSelectedAccountId}
                  className="min-w-[252px] flex-1 sm:w-[360px] sm:flex-none"
                />
                {!readOnly && (
                  <button
                    type="button"
                    data-account-management-control
                    onClick={() => setAccountFormOpen((open) => !open)}
                    className="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-blue-400/35 bg-blue-500/15 px-3 text-xs font-semibold text-blue-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_10px_24px_rgba(37,99,235,0.14)] hover:border-blue-300/55 hover:bg-blue-500/25 hover:text-white"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    增加账户
                  </button>
                )}
              </div>
            )}
          </div>

          {accountManagementOpen && (
            <div id="live-account-management-panel" className="min-w-0">
              {!readOnly && accountFormOpen && (
                <div className="mb-3 rounded-xl border border-red-500/25 bg-crypto-bg/70 p-3">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-100">
                <KeyRound className="h-4 w-4 text-red-300" />
                新增实盘账户
              </div>
              <div className="mb-3 rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                <div className="flex items-center gap-1.5 font-semibold">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  交易权限测试
                </div>
                <div className="mt-1 text-amber-100/75">
                  保存前会验证读取权限和 Trade 权限；未通过不会保存账户。
                </div>
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                <CryptoSelect
                  value={accountForm.exchange}
                  onChange={(event) => setAccountForm((prev) => ({
                    ...prev,
                    exchange: event.target.value === 'binanceusdm' ? 'binanceusdm' : 'okx',
                    passphrase: event.target.value === 'binanceusdm' ? '' : prev.passphrase,
                  }))}
                  controlSize="sm"
                  wrapperClassName="min-w-0"
                >
                  <option value="okx">OKX USDT 永续</option>
                  <option value="binanceusdm">Binance USD-M 永续</option>
                </CryptoSelect>
                <input
                  value={accountForm.name}
                  onChange={(event) => setAccountForm((prev) => ({ ...prev, name: event.target.value }))}
                  placeholder="账户名称"
                  className="h-9 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-xs text-gray-100 outline-none placeholder:text-gray-600 focus:border-red-500/60"
                />
                <input
                  value={accountForm.apiKey}
                  onChange={(event) => setAccountForm((prev) => ({ ...prev, apiKey: event.target.value }))}
                  placeholder="API Key"
                  autoComplete="off"
                  className="h-9 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-xs text-gray-100 outline-none placeholder:text-gray-600 focus:border-red-500/60"
                />
                <input
                  value={accountForm.apiSecret}
                  onChange={(event) => setAccountForm((prev) => ({ ...prev, apiSecret: event.target.value }))}
                  placeholder="Secret Key"
                  type="password"
                  autoComplete="new-password"
                  className="h-9 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-xs text-gray-100 outline-none placeholder:text-gray-600 focus:border-red-500/60"
                />
                {accountForm.exchange === 'okx' && (
                  <input
                    value={accountForm.passphrase}
                    onChange={(event) => setAccountForm((prev) => ({ ...prev, passphrase: event.target.value }))}
                    placeholder="Passphrase（仅 OKX）"
                    type="password"
                    autoComplete="new-password"
                    className="h-9 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-xs text-gray-100 outline-none placeholder:text-gray-600 focus:border-red-500/60"
                  />
                )}
              </div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                <label className="inline-flex items-center gap-2 text-xs font-semibold text-gray-400">
                  <input
                    type="checkbox"
                    checked={accountForm.testnet}
                    onChange={(event) => setAccountForm((prev) => ({ ...prev, testnet: event.target.checked }))}
                    className="h-3.5 w-3.5 rounded border-crypto-border bg-crypto-bg accent-red-500"
                  />
                  Testnet
                </label>
                {accountFormError && (
                  <div className="min-w-[220px] flex-1 rounded-lg border border-red-500/35 bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-200">
                    {accountFormError}
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setAccountForm(emptyAccountForm);
                      setAccountFormError('');
                      setAccountFormOpen(false);
                    }}
                    className="h-8 rounded-lg border border-crypto-border px-3 text-xs font-semibold text-gray-400 hover:text-gray-200"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    disabled={accountSaving || !accountForm.name.trim() || !accountForm.apiKey.trim() || !accountForm.apiSecret.trim()}
                    onClick={() => void createLiveAccount()}
                    className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-red-500/45 bg-crypto-bg px-3 text-xs font-semibold text-red-100 hover:bg-white/[0.03] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {accountSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <KeyRound className="h-3.5 w-3.5" />}
                    {accountSaving ? '测试中' : '测试并保存账户'}
                  </button>
                </div>
              </div>
                </div>
              )}

              <div className="min-w-0">
                {accountLoading ? (
                  <div className="rounded-xl border border-crypto-border bg-crypto-bg px-3 py-8 text-center text-sm text-gray-500">
                    <Loader2 className="mx-auto mb-2 h-4 w-4 animate-spin" />
                    读取资产
                  </div>
                ) : accountError ? (
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                    {accountError}
                  </div>
                ) : (
                  <div className={clsx('grid grid-cols-1 gap-3', isBinanceUsdmAccount ? 'xl:grid-cols-2' : 'xl:grid-cols-3')}>
                    {renderTotalAssetPanel()}
                    {isBinanceUsdmAccount
                      ? renderBalancePanel('USD-M 合约账户', 'Futures Wallet', 'trading', balanceDetail.trading)
                      : <>
                          {renderBalancePanel('资金账户', 'Funding', 'funding', balanceDetail.funding)}
                          {renderBalancePanel('交易账户', 'Trading', 'trading', balanceDetail.trading)}
                        </>}
                  </div>
                )}
              </div>
            </div>
          )}
      </section>

      <div className="grid min-h-0 gap-5 xl:grid-cols-[minmax(320px,360px)_minmax(390px,0.9fr)_minmax(440px,1fr)]">
        <aside className="min-w-0">
          <section className="flex h-[700px] min-h-0 flex-col rounded-xl border border-crypto-border bg-crypto-card p-4">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-gray-100">策略选择</h2>
              <span className="rounded-full border border-blue-500/25 bg-blue-500/10 px-2.5 py-1 text-xs font-semibold text-blue-200">
                {filteredStrategies.length}/{strategies.length}
              </span>
            </div>
            <div className="relative mb-3">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-600" />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索策略名称 / ID / 交易对"
                className="h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg py-2 pl-9 pr-3 text-sm text-gray-100 outline-none placeholder:text-gray-600 focus:border-red-500/70"
              />
            </div>
            <div className="mb-3 grid grid-cols-3 gap-1 rounded-lg border border-crypto-border bg-crypto-bg p-1">
              {strategyFilters.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => setFilter(item.key)}
                  className={clsx(
                    'inline-flex min-w-0 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-semibold transition-colors',
                    filter === item.key
                      ? 'bg-red-500/15 text-red-200'
                      : 'text-gray-500 hover:bg-white/[0.03] hover:text-gray-300',
                  )}
                >
                  <span className="truncate">{item.label}</span>
                  <span
                    className={clsx(
                      'shrink-0 tabular-nums',
                      filter === item.key ? 'text-red-100' : 'text-gray-600',
                    )}
                  >
                    {strategyFilterCounts[item.key]}
                  </span>
                </button>
              ))}
            </div>
            <div className="mb-3 inline-flex h-11 w-full items-center gap-1 rounded-xl border border-crypto-border bg-crypto-bg p-1">
              {[
                { field: 'return' as const, label: '收益率' },
                { field: 'created' as const, label: '更新时间' },
              ].map((control) => {
                const direction = sortDirectionFor(sortMode, control.field);
                return (
                  <button
                    key={control.field}
                    type="button"
                    onClick={() => setSortMode(nextSortMode(sortMode, control.field))}
                    className={clsx(
                      'inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg px-3 text-xs font-semibold transition-colors',
                      direction
                        ? 'bg-purple-500/20 text-purple-200 ring-1 ring-purple-400/20'
                        : 'text-gray-500 hover:bg-white/[0.03] hover:text-gray-300',
                    )}
                  >
                    <span>{control.label}</span>
                    <SortArrow direction={direction} />
                  </button>
                );
              })}
            </div>
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
              {filteredStrategies.length === 0 ? (
                <div className="rounded-lg border border-dashed border-crypto-border py-8 text-center text-sm text-gray-500">
                  没有匹配的策略
                </div>
              ) : (
                filteredStrategies.map((strategy) => {
                  const candidate = strategy.strategyId === candidateStrategyId;
                  const added = selectedStrategyIds.includes(strategy.strategyId);
                  const canAddStrategy = isRunningDeployableStrategy(strategy);
                  return (
                    <article
                      key={strategy.strategyId}
                      className={clsx(
                        'rounded-lg border p-3 transition-colors',
                        candidate
                          ? 'border-blue-500/55 bg-blue-500/10'
                          : added
                            ? 'border-amber-500/35 bg-amber-500/10'
                            : 'border-crypto-border bg-crypto-bg',
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <button
                          type="button"
                          onClick={() => setCandidateStrategyId(strategy.strategyId)}
                          className="min-w-0 flex-1 text-left"
                        >
                          <div className="truncate text-sm font-semibold text-gray-100">
                            {compactName(strategy.strategyName, `策略 #${strategy.strategyId}`)}
                          </div>
                          <div className="mt-1 text-xs text-gray-500">
                            #{strategy.strategyId} · {strategy.status || 'unknown'} · {summarizeSymbols(strategy.symbols, strategy.tradeSymbols)}
                          </div>
                        </button>
                        {added ? (
                          <span className="shrink-0 rounded-full bg-amber-500/15 px-2 py-1 text-[11px] font-semibold text-amber-200">
                            已加入
                          </span>
                        ) : !readOnly && (
                          <button
                            type="button"
                            disabled={actioningId === strategy.strategyId || !canAddStrategy}
                            title={!canAddStrategy ? '只有运行中的模拟策略可加入实盘' : undefined}
                            onClick={() => void addStrategy(strategy)}
                            className="inline-flex h-7 shrink-0 items-center justify-center gap-1 rounded-md border border-red-500/50 bg-crypto-bg px-2 text-[11px] font-semibold text-red-200 hover:bg-white/[0.03] disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            <Rocket size={12} />
                            {actioningId === strategy.strategyId ? '加入中' : canAddStrategy ? '加入实盘' : '未运行'}
                          </button>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => setCandidateStrategyId(strategy.strategyId)}
                        className="mt-3 block w-full text-left"
                      >
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <div className={clsx('truncate text-sm font-bold tabular-nums', signedMetricColor(strategy.totalPnl))}>
                              {formatSignedUsd(strategy.totalPnl)}
                            </div>
                            <div className="mt-0.5 text-[10px] text-gray-500">收益金额</div>
                          </div>
                          <div className="text-right">
                            <div className={clsx('truncate text-sm font-bold tabular-nums', signedMetricColor(strategy.returnPct))}>
                              {formatSignedPct(strategy.returnPct)}
                            </div>
                            <div className="mt-0.5 text-[10px] text-gray-500">收益率</div>
                          </div>
                        </div>
                      </button>
                    </article>
                  );
                })
              )}
            </div>
          </section>
        </aside>

        <main className="min-w-0">
          <section className="flex h-[700px] min-h-0 flex-col rounded-xl border border-crypto-border bg-crypto-card p-4">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-100">
                <ShieldCheck size={18} className="text-red-300" />
                实盘策略列表
              </h2>
              <span className="rounded-full border border-red-500/25 bg-crypto-bg px-2.5 py-1 text-xs font-semibold text-red-200">
                已添加策略 {selectedStrategies.length}
              </span>
            </div>
            {selectedStrategies.length === 0 ? (
              <div className="flex min-h-0 flex-1 items-center justify-center rounded-lg border border-dashed border-crypto-border text-center text-sm text-gray-500">
                {readOnly ? '暂无已加入实盘策略' : '从左侧选择策略并点击加入实盘'}
              </div>
            ) : (
              <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
                {selectedStrategies.map((strategy) => {
                  const active = strategy.strategyId === selectedStrategyId;
                  const strategyAccountIds = boundAccountIds(strategy);
                  const currentBinding = accountBindingFor(strategy, selectedAccountId);
                  const currentDeploymentActive = Boolean(currentBinding?.deployed || liveSubscriptionIdForAccount(strategy, selectedAccountId));
                  return (
                    <article
                      key={strategy.strategyId}
                      className={clsx(
                        'rounded-lg border p-3 transition-colors',
                        active
                          ? 'border-blue-500/55 bg-blue-500/10'
                          : 'border-crypto-border bg-crypto-bg/70 hover:border-blue-500/35',
                      )}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <button
                          type="button"
                          onClick={() => selectStrategy(strategy.strategyId)}
                          className="min-w-0 flex-1 text-left"
                        >
                          <div className="truncate text-sm font-semibold text-gray-100">
                            {compactName(strategy.strategyName, `策略 #${strategy.strategyId}`)}
                          </div>
                          <div className="mt-1 text-xs text-gray-500">
                            #{strategy.strategyId} · {summarizeSymbols(strategy.symbols, strategy.tradeSymbols)}
                          </div>
                        </button>
                        <div className="flex shrink-0 items-center gap-2">
                          <RouterLink
                            to={`/live?mode=paper&strategyId=${strategy.strategyId}`}
                            className="inline-flex h-7 items-center justify-center gap-1 rounded-md border border-blue-500/35 bg-blue-500/10 px-2 text-[11px] font-semibold text-blue-200 hover:bg-blue-500/20"
                            title="打开对应模拟盘实例"
                          >
                            <Activity size={12} />
                            模拟盘实例
                          </RouterLink>
                          {!readOnly && (
                            <button
                              type="button"
                              onClick={() => removeStrategyFromWorkspace(strategy)}
                              disabled={actioningId === strategy.strategyId}
                              className="inline-flex h-7 items-center justify-center gap-1 rounded-md border border-crypto-border bg-crypto-bg px-2 text-[11px] font-semibold text-gray-300 hover:border-red-500/45 hover:text-red-200 disabled:cursor-not-allowed disabled:opacity-60"
                              title={liveWorkspaceRemoveBlockReason(strategy) || '移出实盘列表'}
                            >
                              <Trash2 size={12} />
                              移出
                            </button>
                          )}
                        </div>
                      </div>
                      {active && (
                        <div className="mt-3 space-y-3 border-t border-crypto-border pt-3">
                          <div className="grid grid-cols-3 gap-2 text-center">
                            <div className="rounded-md bg-crypto-bg px-2 py-2">
                              <div className={clsx('text-xs font-bold', signedMetricColor(strategy.returnPct))}>
                                {formatSignedPct(strategy.returnPct)}
                              </div>
                              <div className="mt-0.5 text-[9px] text-gray-600">模拟收益</div>
                            </div>
                            <div className="rounded-md bg-crypto-bg px-2 py-2">
                              <div className="text-xs font-bold text-white">{currentDeploymentActive ? '已部署' : '待部署'}</div>
                              <div className="mt-0.5 text-[9px] text-gray-600">当前账户</div>
                            </div>
                            <div className="rounded-md bg-crypto-bg px-2 py-2">
                              <div className="text-xs font-bold text-blue-300">{strategyAccountIds.length}</div>
                              <div className="mt-0.5 text-[9px] text-gray-600">绑定账户</div>
                            </div>
                          </div>

                          <div className="space-y-2">
                            <div className="flex items-center justify-between gap-2 text-xs">
                              <div className="flex items-center gap-2 font-semibold text-gray-300">
                                <Wallet size={14} className="text-red-300" />
                                使用的实盘账户
                              </div>
                              <span className="text-gray-500">
                                已绑定 {strategyAccountIds.length}/{accounts.length}
                              </span>
                            </div>

                            <div className="grid gap-1.5">
                              {accounts.map((account) => {
                                const binding = accountBindingFor(strategy, account.accountId);
                                const bound = strategyAccountIds.includes(account.accountId);
                                const selected = selectedAccountId === account.accountId;
                                const accountSubscriptionId = liveSubscriptionIdForAccount(strategy, account.accountId);
                                const accountDeployed = Boolean(binding?.deployed || accountSubscriptionId);
                                const busy = accountBindingAction === `${strategy.strategyId}:${account.accountId}`;
                                const deployableAccount = canUseAccountForLiveDeployment(account);
                                const accountPreflight = preflights[preflightKey(strategy.strategyId, account.accountId)];
                                const preflightPassed = Boolean(accountPreflight?.allPassed);
                                return (
                                  <div
                                    key={account.accountId}
                                    className={clsx(
                                      'flex items-center gap-2 rounded-md border px-2.5 py-2 text-xs transition-colors',
                                      selected
                                        ? 'border-crypto-border bg-crypto-bg/80 text-gray-100'
                                        : bound
                                          ? 'border-crypto-border bg-crypto-bg/70 text-gray-300'
                                          : 'border-crypto-border/80 bg-crypto-bg/40 text-gray-500',
                                    )}
                                  >
                                    <button
                                      type="button"
                                      onClick={() => setSelectedAccountId(account.accountId)}
                                      className="flex min-w-0 flex-1 items-center gap-2 text-left"
                                      aria-pressed={selected}
                                      aria-label={`${account.name} ${bound ? '已绑定' : '未绑定'}`}
                                    >
                                      <span
                                        className={clsx(
                                          'h-2.5 w-2.5 shrink-0 rounded-full',
                                          accountDeployed
                                            ? 'animate-pulse bg-green-400 shadow-[0_0_0_4px_rgba(74,222,128,0.14),0_0_14px_rgba(74,222,128,0.7)]'
                                            : bound
                                              ? 'bg-yellow-400 shadow-[0_0_0_4px_rgba(250,204,21,0.12),0_0_12px_rgba(250,204,21,0.4)]'
                                              : 'bg-red-400 shadow-[0_0_0_4px_rgba(248,113,113,0.12),0_0_12px_rgba(248,113,113,0.45)]',
                                        )}
                                      />
                                      <span className="min-w-0 flex-1 truncate font-semibold">
                                        {account.name}
                                      </span>
                                      <span
                                        className={clsx(
                                          'hidden shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold sm:inline-flex',
                                          account.exchange === 'binanceusdm'
                                            ? 'bg-yellow-500/15 text-yellow-200'
                                            : 'bg-blue-500/15 text-blue-200',
                                        )}
                                      >
                                        {accountExchangeLabel(account)}
                                      </span>
                                      <span className="hidden truncate text-[11px] text-gray-500 sm:inline">
                                        {account.maskedApiKey || account.accountId}
                                      </span>
                                    </button>
                                    <span
                                      className={clsx(
                                        'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold',
                                        accountDeployed
                                          ? 'bg-green-500/15 text-green-300'
                                          : preflightPassed
                                            ? 'bg-blue-500/15 text-blue-300'
                                          : bound
                                            ? 'bg-yellow-500/15 text-yellow-300'
                                            : 'bg-gray-500/15 text-gray-400',
                                      )}
                                    >
                                      {accountDeployed ? '已启用' : preflightPassed ? '预检通过' : bound ? '已绑定待启用' : '未绑定'}
                                    </span>
                                    {!readOnly && (
                                      <button
                                        type="button"
                                        disabled={busy || accountDeployed || !deployableAccount}
                                        title={!deployableAccount ? '账户缺少 Secret Key 或尚未通过权限测试' : accountDeployed ? '账户已启用下单' : preflightPassed ? '预检已通过，可以绑定并启用' : '先对该账户执行独立预检'}
                                        onClick={() => {
                                          if (preflightPassed) openEnableAccountConfirm(strategy, account.accountId);
                                          else void preflightStrategyAccount(strategy, account.accountId);
                                        }}
                                        className="inline-flex h-7 shrink-0 items-center justify-center gap-1 rounded-md border border-crypto-border bg-crypto-card px-2 text-[11px] font-semibold text-gray-200 hover:border-blue-500/35 hover:text-blue-200 disabled:cursor-not-allowed disabled:opacity-60"
                                      >
                                        {preflightPassed ? <Link2 size={12} /> : <ShieldCheck size={12} />}
                                        {accountDeployed ? '已启用' : busy ? '预检中' : preflightPassed ? (bound ? '启用下单' : '绑定并启用') : '预检'}
                                      </button>
                                    )}
                                    {!readOnly && bound && !accountDeployed && (
                                      <button
                                        type="button"
                                        disabled={busy}
                                        title="解除账户绑定"
                                        onClick={() => void unbindAccountFromStrategy(strategy, account.accountId)}
                                        className="inline-flex h-7 shrink-0 items-center justify-center rounded-md px-1.5 text-[11px] font-semibold text-gray-500 hover:text-gray-200 disabled:cursor-not-allowed disabled:opacity-60"
                                      >
                                        解绑
                                      </button>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                            {renderEnableCheckResult()}
                          </div>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        </main>

        <aside className="min-w-0">
          <section className="flex h-[700px] min-h-0 flex-col rounded-xl border border-crypto-border bg-crypto-card p-4">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-lg font-semibold text-gray-100">
                <CircleDollarSign size={18} className="text-red-300" />
                实盘面板
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <RouterLink
                  to="/watch"
                  className="inline-flex h-8 items-center justify-center rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 text-xs font-semibold text-blue-200 hover:border-blue-400 hover:bg-blue-500/15 hover:text-blue-100"
                >
                  打开盯盘
                </RouterLink>
                {currentAccountDeployments.length === 0 ? (
                  <span className="rounded-full border border-crypto-border bg-crypto-bg px-2.5 py-1 text-xs font-semibold text-gray-500">
                    未部署
                  </span>
                ) : null}
              </div>
            </div>
            <LiveAccountTabs
              accounts={accounts}
              value={selectedAccountId}
              onChange={setSelectedAccountId}
              ariaLabel="实盘面板账户切换"
              className="mb-3 w-full"
            />
            <div
              aria-label="实盘策略状态筛选"
              className="mb-3 flex items-center gap-1 rounded-xl border border-crypto-border bg-crypto-bg/80 p-1"
            >
              {livePanelStatusFilters.map((item) => {
                const active = livePanelStatusFilter === item.key;
                return (
                  <button
                    key={item.key}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setLivePanelStatusFilter(item.key)}
                    className={clsx(
                      'inline-flex h-8 flex-1 items-center justify-center gap-1.5 rounded-lg px-2 text-xs font-semibold transition-colors',
                      livePanelStatusFilterButtonClass(item.key, active),
                    )}
                  >
                    <span>{item.label}</span>
                    <span
                      className={clsx(
                        'min-w-5 rounded-full px-1.5 py-0.5 text-[10px] tabular-nums',
                        livePanelStatusFilterCountClass(item.key, active),
                      )}
                    >
                      {livePanelStatusCounts[item.key]}
                    </span>
                  </button>
                );
              })}
            </div>
            <div className="mb-4 grid grid-cols-4 gap-2 text-center">
              <div className="rounded-lg bg-crypto-bg px-3 py-2">
                <div className="text-sm font-bold text-white">{selectedStrategies.length}</div>
                <div className="mt-0.5 text-[10px] text-gray-500">已加入</div>
              </div>
              <div className="rounded-lg bg-crypto-bg px-3 py-2">
                <div className="text-sm font-bold text-red-300">
                  {currentAccountDeployments.length}
                </div>
                <div className="mt-0.5 text-[10px] text-gray-500">已部署</div>
              </div>
              <div className="rounded-lg bg-crypto-bg px-3 py-2">
                <div className="text-sm font-bold text-amber-300">{contractPositions.length}</div>
                <div className="mt-0.5 text-[10px] text-gray-500">合约持仓</div>
              </div>
              <div className="rounded-lg bg-crypto-bg px-3 py-2">
                <div className="text-sm font-bold text-blue-300">{historyOrders.length}</div>
                <div className="mt-0.5 text-[10px] text-gray-500">订单明细</div>
              </div>
            </div>
            {selectedStrategies.length === 0 && currentAccountDeployments.length === 0 ? (
              <div className="flex min-h-0 flex-1 items-center justify-center rounded-xl border border-dashed border-crypto-border text-center text-sm text-gray-500">
                将模拟策略加入实盘列表并完成部署后，这里会展示当前账户的实盘策略。
              </div>
            ) : (
              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
                {currentAccountDeployments.length > 0 ? (
                  <div className="space-y-2">
                    {filteredAccountDeployments.length > 0 ? (
                      filteredAccountDeployments.map(({ strategy, liveSubscriptionId, deploymentStatus }) => {
                        const strategyBusy = actioningId === strategy.strategyId;
                        const canResumeDeployment = deploymentStatus === 'paused';
                        const canPauseDeployment = deploymentStatus === 'running';
                        const canToggleDeployment = canResumeDeployment || canPauseDeployment;
                        const canStopCurrentDeployment = Boolean(
                          liveSubscriptionId && deploymentStatus !== 'stopped' && deploymentStatus !== '',
                        );
                        return (
                          <div
                            key={`${strategy.strategyId}-${liveSubscriptionId || selectedAccountId}`}
                            className={clsx(
                              'rounded-xl border bg-crypto-bg/70 p-3',
                              strategy.strategyId === selectedStrategyId ? 'border-blue-500/35' : 'border-red-500/25',
                            )}
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="flex min-w-0 items-center gap-2">
                                  <span
                                    className={clsx(
                                      'h-2.5 w-2.5 shrink-0 rounded-full',
                                      deploymentStatusLightClass(deploymentStatus),
                                    )}
                                    title={deploymentStatusLabel(deploymentStatus)}
                                    aria-label={deploymentStatusLabel(deploymentStatus)}
                                  />
                                  <div className="truncate text-sm font-semibold text-white">
                                    {strategy.deploymentStrategyName || strategy.strategyName || '当前账户实盘策略'}
                                  </div>
                                </div>
                                <div className="mt-1 text-xs text-gray-500">
                                  {accountLabel(accounts, selectedAccountId)} · 来源模拟策略 #{strategy.strategyId}
                                </div>
                              </div>
                              {!readOnly && (
                                <div className="flex shrink-0 items-center gap-2">
                                  <button
                                    type="button"
                                    disabled={!canToggleDeployment || strategyBusy}
                                    aria-label={canResumeDeployment ? '继续实盘信号' : '暂停实盘信号'}
                                    title={canResumeDeployment ? '恢复当前账户的实盘信号执行' : '仅暂停当前账户实盘信号执行，源模拟策略继续运行并继续产生模拟盘信号'}
                                    onClick={() =>
                                      canResumeDeployment
                                        ? void resumeDeployment(strategy)
                                        : void pauseDeployment(strategy)
                                    }
                                    className={clsx(
                                      livePanelActionButtonBase,
                                      canResumeDeployment ? liveActionButtonSuccess : liveActionButtonWarning,
                                    )}
                                  >
                                    {canResumeDeployment ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
                                    {canResumeDeployment ? '继续实盘信号' : '暂停实盘信号'}
                                  </button>
                                  <button
                                    type="button"
                                    disabled={!canStopCurrentDeployment || strategyBusy}
                                    onClick={() => openStopConfirm(strategy)}
                                    className={clsx(livePanelActionButtonBase, liveActionButtonDanger)}
                                  >
                                    <Square className="h-3.5 w-3.5" />
                                    停止
                                  </button>
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <div className="rounded-xl border border-dashed border-crypto-border bg-crypto-bg/70 px-3 py-5 text-center">
                        <div className="text-sm font-semibold text-gray-300">当前筛选下暂无实盘策略</div>
                        <div className="mt-1 text-xs text-gray-500">
                          可切换到其他状态筛选查看当前账户的实盘订阅。
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed border-crypto-border bg-crypto-bg p-3">
                    <div className="mb-3 flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-gray-200">当前账户实盘策略</div>
                        <div className="mt-1 text-xs text-gray-500">
                          {accountLabel(accounts, selectedAccountId)} · 尚未部署实盘策略
                        </div>
                      </div>
                      <span className="shrink-0 rounded-full bg-gray-500/15 px-2 py-1 text-[11px] font-semibold text-gray-400">
                        待部署
                      </span>
                    </div>
                    <div className="rounded-lg border border-dashed border-crypto-border px-3 py-4 text-center text-sm font-semibold text-gray-200">
                      当前账户尚未部署实盘策略
                    </div>
                    <div className="mt-2 text-xs text-gray-500">
                      完成订阅部署后，这里会展示当前账户跟随源模拟策略信号的实盘执行订阅。
                    </div>
                  </div>
                )}

              </div>
            )}
          </section>
        </aside>
      </div>

      {confirmState && (
        <ThemeDialog
          open
          variant="confirm"
          title={confirmState.title}
          content={confirmState.content}
          confirmText={confirmState.confirmText}
          cancelText="取消"
          tone={confirmState.tone}
          onCancel={() => setConfirmState(null)}
          onConfirm={() => {
            void confirmState.onConfirm();
          }}
        />
      )}

    </div>
  );
}
