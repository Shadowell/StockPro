import { useState, useEffect, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Bell, Activity, Plus, Minus, Trash2, ToggleLeft, ToggleRight, X,
  BarChart3, ChevronRight,
  RefreshCw, Zap, DollarSign, Eye, Clock, Send, Database, HeartPulse, ServerCog, ShieldAlert,
} from 'lucide-react';
import clsx from 'clsx';
import CryptoSelect from '../components/CryptoSelect';
import ThemeDialog from '../components/ThemeDialog';
import { SELECTED_SEGMENT_CLASS, SELECTED_SEGMENT_COUNT_CLASS } from '../utils/selectionStyles';
import { liveExecutionApi, marketApi, monitorApi, monitorCurrentApi, settingsApi } from '../api/client';
import type { MonitorSummary } from '../types/operations';
import SchedulerPanel from './operations/SchedulerPanel';
import type {
  LiveExecutionAccount,
  LiveExecutionAccountBinding,
  LiveExecutionOrder,
  LiveExecutionPosition,
  LiveExecutionStrategy,
} from '../api/client';

interface Alert {
  id: number;
  name: string;
  type: string;
  exchange: string;
  symbol?: string;
  condition: {
    threshold?: number;
    strategyId?: number;
    strategyName?: string;
    cooldownSec?: number;
    metric?: string;
  };
  enabled: boolean;
  last_triggered_at?: string;
}

interface RunningStrategy {
  strategyId?: number | string | null;
  name?: string | null;
  status?: string | null;
  exchange?: string | null;
  strategyKey?: string;
  isAiAutonomous?: boolean;
  symbols?: string[];
  pnl?: number | string | null;
  totalTrades?: number | string | null;
  equity?: number | string | null;
  initialCapital?: number | string | null;
  balance?: number | string | null;
  unrealizedPnl?: number | string | null;
  returnPct?: number | string | null;
  winRate?: number;
  profitFactor?: number;
  grossProfit?: number;
  grossLoss?: number;
  closingTrades?: number;
  winningTrades?: number;
  positions: Record<string, {
    size: number;
    entryPrice: number;
    side: string;
    unrealizedPnl: number;
    markPrice: number;
    mark_price?: number;
    notionalUsdt?: number;
    notional_usdt?: number;
    notional?: number;
    value?: number;
    baseQty?: number;
    base_qty?: number;
    contracts?: number;
    entry_price?: number;
  }>;
  startedAt?: string;
  errorMessage?: string;
}

type RunningStrategyAssetClass = 'spot' | 'contract';
type RunningStrategyAssetFilter = 'all' | RunningStrategyAssetClass;
const liveMonitorStatusFilters = [
  { key: 'running', label: '运行中' },
  { key: 'paused', label: '暂停' },
  { key: 'all', label: '全部' },
] as const;
type LiveMonitorStatusFilter = (typeof liveMonitorStatusFilters)[number]['key'];

interface StrategyProfitPushSettings {
  enabled: boolean;
  intervalMinutes: number;
  running: boolean;
  lastSentAt?: string | null;
  lastFinishedAt?: string | null;
  lastError?: string | null;
  lastSkipReason?: string | null;
  notifyReady: boolean;
  notifyEnabled: boolean;
  webhookConfigured: boolean;
  profitReportImageReady?: boolean;
  profitReportImageConfigured?: boolean;
  profitReportImageCjkFontAvailable?: boolean;
  profitReportImageReason?: string | null;
  lastDeliveryType?: string | null;
  lastDeliveryError?: string | null;
}

interface MarketSentiment {
  longShortRatio: number | null;
  openInterest: number | null;
  openInterestBtc: number | null;
  openInterestChange: number | null;
  fundingRate: number | null;
  fearGreedIndex: number | null;
}

function formatUsd(value: unknown, digits = 2): string {
  const n = Number(value ?? 0);
  return `$${Number.isFinite(n) ? n.toFixed(digits) : '0.00'}`;
}

function finiteNumber(value: unknown, fallback = 0): number {
  const n = Number(value ?? fallback);
  return Number.isFinite(n) ? n : fallback;
}

function formatSignedUsd(value: unknown): string {
  const n = finiteNumber(value);
  const sign = n > 0 ? '+' : n < 0 ? '-' : '';
  return `${sign}$${Math.abs(n).toFixed(2)}`;
}

function formatSignedPercent(value: unknown, digits = 2): string {
  const n = finiteNumber(value);
  return `${n > 0 ? '+' : ''}${n.toFixed(digits)}%`;
}

function formatPercent(value: unknown, digits = 1): string {
  return `${finiteNumber(value).toFixed(digits)}%`;
}

function formatRatio(value: unknown, digits = 2): string {
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? n.toFixed(digits) : '--';
}

function activeAlertCount(alerts: Alert[]): number {
  return alerts.filter(alert => alert.enabled).length;
}

function positionNotionalUsdt(position: RunningStrategy['positions'][string]): number {
  const explicit = finiteNumber(
    position.notionalUsdt ?? position.notional_usdt ?? position.notional ?? position.value,
    NaN,
  );
  if (Number.isFinite(explicit) && explicit > 0) return Math.abs(explicit);

  const px = finiteNumber(position.markPrice ?? position.mark_price ?? position.entryPrice ?? position.entry_price);
  if (px <= 0) return 0;

  const baseQty = finiteNumber(position.baseQty ?? position.base_qty, NaN);
  if (Number.isFinite(baseQty) && baseQty > 0) return Math.abs(baseQty) * px;

  return Math.abs(finiteNumber(position.size)) * px;
}

function livePositionNotionalUsdt(position: LiveExecutionPosition): number {
  const explicit = finiteNumber(position.notionalUsdt ?? position.notional, NaN);
  if (Number.isFinite(explicit) && explicit > 0) return Math.abs(explicit);

  const px = finiteNumber(position.markPrice ?? position.entryPrice);
  if (px <= 0) return 0;

  const baseAmount = finiteNumber(position.baseAmount, NaN);
  if (Number.isFinite(baseAmount) && baseAmount > 0) return Math.abs(baseAmount) * px;

  return Math.abs(finiteNumber(position.contracts ?? position.amount)) * px;
}

function livePositionSize(position: LiveExecutionPosition): number {
  return finiteNumber(position.contracts ?? position.amount ?? position.baseAmount);
}

function accountExchangeLabel(account?: LiveExecutionAccount | null): string {
  return account?.exchange === 'binanceusdm' ? 'Binance USD-M' : 'OKX';
}

function LiveMonitorAccountTabs({
  ariaLabel,
  accounts,
  value,
  onChange,
  className,
}: {
  ariaLabel: string;
  accounts: LiveExecutionAccount[];
  value: string;
  onChange: (accountId: string) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={clsx('grid min-h-8 grid-cols-2 rounded-lg border border-crypto-border bg-crypto-bg/70 p-1', className)}
    >
      {accounts.map(account => {
        const active = account.accountId === value;
        return (
          <button
            key={account.accountId}
            role="tab"
            type="button"
            aria-selected={active}
            title={account.name}
            onClick={() => onChange(account.accountId)}
            className={clsx(
              'min-w-0 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors',
              active
                ? SELECTED_SEGMENT_CLASS
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

function livePositionLiquidationDistancePct(position: LiveExecutionPosition): number | null {
  const mark = finiteNumber(position.markPrice, NaN);
  const liquidation = finiteNumber(position.liquidationPrice, NaN);
  if (!Number.isFinite(mark) || !Number.isFinite(liquidation) || mark <= 0 || liquidation <= 0) return null;
  return (Math.abs(mark - liquidation) / mark) * 100;
}

function isSameLocalDay(value?: string | number | null): boolean {
  if (value == null) return false;
  const date = typeof value === 'number' ? new Date(value) : new Date(value);
  if (Number.isNaN(date.getTime())) return false;
  const now = new Date();
  return (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  );
}

function liveOrderTimestamp(order: LiveExecutionOrder): string | number | null {
  return order.fillTimestamp ?? order.updatedTimestamp ?? order.createdTimestamp ??
    order.fillDatetime ?? order.updatedDatetime ?? order.createdDatetime ?? order.datetime ?? order.timestamp ?? null;
}

function liveOrderIsToday(order: LiveExecutionOrder): boolean {
  return isSameLocalDay(liveOrderTimestamp(order));
}

function finiteMetricValue(value: unknown): number | null {
  if (typeof value === 'boolean' || value == null) return null;
  const normalized = typeof value === 'string' ? value.trim().replace(/,/g, '') : value;
  if (normalized === '') return null;
  const number = Number(normalized);
  return Number.isFinite(number) ? number : null;
}

function firstFiniteMetric(values: unknown[], fallback = 0, preferNonZero = false): number {
  let first: number | null = null;
  for (const value of values) {
    const number = finiteMetricValue(value);
    if (number == null) continue;
    if (first == null) first = number;
    if (!preferNonZero || Math.abs(number) > 1e-12) return number;
  }
  return first ?? fallback;
}

function liveOrderRealizedPnl(order: LiveExecutionOrder): number {
  return firstFiniteMetric([
    order.pnl,
    order.realizedPnl,
    order.realized_pnl,
    order.fillPnl,
    order.fill_pnl,
    order.info?.pnl,
    order.info?.realizedPnl,
    order.info?.realized_pnl,
    order.info?.fillPnl,
    order.info?.fill_pnl,
  ], 0, true);
}

function liveOrderFee(order: LiveExecutionOrder): number {
  const rawFee = order.fee;
  const feeObject = rawFee && typeof rawFee === 'object' && !Array.isArray(rawFee)
    ? rawFee as Record<string, unknown>
    : null;
  const infoFee = order.info?.fee;
  const infoFeeObject = infoFee && typeof infoFee === 'object' && !Array.isArray(infoFee)
    ? infoFee as Record<string, unknown>
    : null;
  return firstFiniteMetric([
    feeObject ? null : rawFee,
    order.feeCost,
    order.fee_cost,
    feeObject?.cost,
    feeObject?.fee,
    infoFeeObject ? null : order.info?.fee,
    infoFeeObject?.cost,
    infoFeeObject?.fee,
    order.info?.feeCost,
    order.info?.fee_cost,
    order.info?.fillFee,
    order.info?.fill_fee,
  ]);
}

function isOpenContractLivePosition(position: LiveExecutionPosition): boolean {
  const symbol = String(position.symbol || '').trim();
  const fields = [position.assetType, position.posSide, position.side]
    .map(value => String(value || '').toLowerCase());
  if (fields.includes('spot')) return false;

  const isContract =
    isContractRunningSymbol(symbol) ||
    fields.some(value => ['swap', 'futures', 'future', 'contract', 'perpetual'].includes(value)) ||
    fields.some(value => ['long', 'short', 'net'].includes(value)) ||
    position.contracts != null ||
    position.margin != null ||
    position.initialMargin != null ||
    position.liquidationPrice != null;
  if (!isContract) return false;

  const size = Math.abs(livePositionSize(position));
  const notional = livePositionNotionalUsdt(position);
  return size > 1e-12 || notional > 1e-8;
}

function liveStrategyIsDeployed(strategy: LiveExecutionStrategy): boolean {
  return Boolean(
    strategy.deployed ||
      strategy.deploymentStatus === 'running' ||
      strategy.status === 'running' ||
      (strategy.accountBindings || []).some(binding => binding.deployed || binding.status === 'running'),
  );
}

function liveAccountBindingFor(
  strategy: LiveExecutionStrategy,
  accountId: string,
): LiveExecutionAccountBinding | null {
  const normalized = accountId || 'default';
  return (strategy.accountBindings || []).find(binding => binding.accountId === normalized) || null;
}

function liveSubscriptionIdForAccount(strategy: LiveExecutionStrategy, accountId: string): number | null {
  const normalized = accountId || 'default';
  const binding = liveAccountBindingFor(strategy, normalized);
  const raw = binding?.liveSubscriptionId ?? (
    strategy.accountId === normalized ? strategy.liveSubscriptionId : null
  );
  const id = Number(raw);
  return Number.isFinite(id) && id > 0 ? id : null;
}

function liveDeploymentStatusForAccount(strategy: LiveExecutionStrategy, accountId: string): string {
  const normalized = accountId || 'default';
  const binding = liveAccountBindingFor(strategy, normalized);
  const raw = binding?.deploymentStatus ?? binding?.status ?? (
    strategy.accountId === normalized ? strategy.deploymentStatus || strategy.status : null
  );
  return String(raw || '').toLowerCase();
}

function liveStrategyHasPanelDeploymentForAccount(strategy: LiveExecutionStrategy, accountId: string): boolean {
  const binding = liveAccountBindingFor(strategy, accountId);
  return Boolean(liveSubscriptionIdForAccount(strategy, accountId) || binding?.deployed);
}

function liveStrategyForMonitorAccount(
  strategy: LiveExecutionStrategy,
  accountId: string,
): LiveExecutionStrategy {
  const binding = liveAccountBindingFor(strategy, accountId);
  const liveSubscriptionId = liveSubscriptionIdForAccount(strategy, accountId);
  const deploymentStatus = liveDeploymentStatusForAccount(strategy, accountId);
  return {
    ...strategy,
    accountId,
    accountIds: [accountId],
    accountBindings: binding ? [binding] : [],
    deployed: liveStrategyHasPanelDeploymentForAccount(strategy, accountId),
    liveSubscriptionId,
    deploymentStatus,
    status: deploymentStatus || strategy.status,
  };
}

function liveStrategyStatusLabel(strategy: LiveExecutionStrategy): string {
  const status = liveDeploymentStatusForMonitor(strategy);
  if (status === 'running') return '运行中';
  if (status === 'paused') return '已暂停';
  if (status === 'stopped') return '已停止';
  if (liveStrategyIsDeployed(strategy)) return '已部署';
  return '待部署';
}

function liveDeploymentStatusForMonitor(strategy: LiveExecutionStrategy): string {
  return String(strategy.deploymentStatus || strategy.status || strategy.workspaceStatus || '').toLowerCase();
}

function liveDeploymentMatchesMonitorFilter(status: string, filter: LiveMonitorStatusFilter): boolean {
  if (filter === 'all') return true;
  return status === filter;
}

function liveMonitorStatusFilterButtonClass(filter: LiveMonitorStatusFilter, active: boolean): string {
  if (!active) {
    if (filter === 'running') return 'text-gray-500 hover:bg-green-400/[0.08] hover:text-green-200';
    if (filter === 'paused') return 'text-gray-500 hover:bg-yellow-300/[0.08] hover:text-yellow-200';
    return 'text-gray-500 hover:bg-white/[0.04] hover:text-gray-200';
  }
  return SELECTED_SEGMENT_CLASS;
}

function liveMonitorStatusFilterCountClass(_filter: LiveMonitorStatusFilter, active: boolean): string {
  if (!active) return 'bg-white/[0.04] text-gray-500';
  return SELECTED_SEGMENT_COUNT_CLASS;
}

function signedMetricColor(value: number): 'green' | 'red' | 'gray' {
  if (value > 0) return 'red';
  if (value < 0) return 'green';
  return 'gray';
}

function isContractRunningSymbol(symbol: string): boolean {
  const normalized = symbol.trim().toUpperCase();
  return normalized.includes(':') || normalized.endsWith('-USDT-SWAP') || normalized.endsWith('-SWAP');
}

function inferRunningStrategyAssetClass(strategy: RunningStrategy): RunningStrategyAssetClass {
  const strategyName = String(strategy.name || '').trim();
  if (strategyName.startsWith('[合约]')) return 'contract';
  if (strategyName.startsWith('[现货]')) return 'spot';
  if ((strategy.symbols || []).some(isContractRunningSymbol)) return 'contract';
  if (Object.keys(strategy.positions || {}).some(isContractRunningSymbol)) return 'contract';
  return 'spot';
}

function inferLiveStrategyAssetClass(strategy: LiveExecutionStrategy): RunningStrategyAssetClass {
  const strategyName = strategy.strategyName.trim();
  if (strategyName.startsWith('[合约]')) return 'contract';
  if (strategyName.startsWith('[现货]')) return 'spot';

  const marketType = String(strategy.marketType || '').toLowerCase();
  if (['swap', 'futures', 'future', 'contract', 'perpetual'].some(type => marketType.includes(type))) {
    return 'contract';
  }
  if (marketType.includes('spot')) return 'spot';

  const symbols = [...(strategy.tradeSymbols || []), ...(strategy.symbols || [])];
  if (symbols.some(isContractRunningSymbol)) return 'contract';
  return 'spot';
}

function compareRunningStrategiesByProfitDesc(a: RunningStrategy, b: RunningStrategy): number {
  const pnlDiff = finiteNumber(b.pnl) - finiteNumber(a.pnl);
  if (pnlDiff !== 0) return pnlDiff;

  const returnDiff = finiteNumber(b.returnPct) - finiteNumber(a.returnPct);
  if (returnDiff !== 0) return returnDiff;

  return finiteNumber(a.strategyId) - finiteNumber(b.strategyId);
}

function compareLiveStrategiesByReturnDesc(
  a: LiveExecutionStrategy,
  b: LiveExecutionStrategy,
): number {
  const returnDiff = finiteNumber(b.returnPct) - finiteNumber(a.returnPct);
  return returnDiff || b.strategyId - a.strategyId;
}

function isAiAutonomousRunningStrategy(strategy: RunningStrategy): boolean {
  return (
    Boolean(strategy.isAiAutonomous) ||
    strategy.strategyKey === 'ai_autonomous_trader' ||
    String(strategy.name || '').includes('AI自主交易')
  );
}

function formatLocalTime(value?: string | null): string {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return date.toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function timestampMs(value?: string | null): number | null {
  if (!value) return null;
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? null : ms;
}

function hasFreshProfitPushError(settings: StrategyProfitPushSettings): boolean {
  if (!settings.lastError) return false;
  if (!settings.enabled || !settings.webhookConfigured || !settings.notifyReady) return false;

  const sentAt = timestampMs(settings.lastSentAt);
  const finishedAt = timestampMs(settings.lastFinishedAt);
  if (sentAt != null && finishedAt != null && sentAt >= finishedAt) return false;
  return true;
}

function profitPushImageReasonText(reason?: string | null): string {
  switch (reason) {
    case 'feishu_app_credentials_missing':
      return '飞书 App 未配置';
    case 'cjk_font_missing':
      return '中文字体未安装';
    case 'pillow_missing':
      return '图片依赖未安装';
    case 'httpx_missing':
      return 'HTTP 客户端不可用';
    case 'image_disabled':
      return '图片推送已关闭';
    case 'image_upload_failed':
      return '图片上传失败';
    default:
      return reason || '图片链路未就绪';
  }
}

function getApiErrorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === 'object') {
    const maybe = error as { response?: { data?: { detail?: unknown } }; message?: unknown };
    const detail = maybe.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (typeof maybe.message === 'string' && maybe.message.trim()) return maybe.message;
  }
  return fallback;
}

function isStrategyScopedAlertType(type: string): boolean {
  return type === 'strategy_return_below' || type === 'strategy_liquidation_risk';
}

interface AlertTemplate {
  id: string;
  label: string;
  desc: string;
  type: string;
  name: string;
  defaultThreshold: number;
  symbol?: string;
  cooldownMinutes?: number;
  className: string;
}

const ALERT_TEMPLATES: AlertTemplate[] = [
  {
    id: 'strategy-return-drawdown',
    label: '策略收益回撤',
    desc: '运行收益率低于自定义百分比',
    type: 'strategy_return_below',
    name: '策略收益低于自定义阈值',
    defaultThreshold: -5,
    cooldownMinutes: 60,
    className: 'border-orange-500/35 bg-orange-500/10 text-orange-300 hover:border-orange-400/70',
  },
  {
    id: 'strategy-liquidation-risk',
    label: '爆仓距离预警',
    desc: '合约持仓接近强平价',
    type: 'strategy_liquidation_risk',
    name: '策略爆仓距离低于自定义阈值',
    defaultThreshold: 10,
    cooldownMinutes: 60,
    className: 'border-rose-500/35 bg-rose-500/10 text-rose-300 hover:border-rose-400/70',
  },
  {
    id: 'price-breakout',
    label: '价格突破',
    desc: '交易对价格高于自定义价位',
    type: 'price_above',
    name: '价格突破自定义阈值',
    symbol: 'BTC/USDT',
    defaultThreshold: 100000,
    className: 'border-blue-500/30 bg-blue-500/10 text-blue-300 hover:border-blue-400/70',
  },
  {
    id: 'price-breakdown',
    label: '价格跌破',
    desc: '交易对价格低于自定义价位',
    type: 'price_below',
    name: '价格跌破自定义阈值',
    symbol: 'BTC/USDT',
    defaultThreshold: 90000,
    className: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300 hover:border-cyan-400/70',
  },
  {
    id: 'funding-above-custom',
    label: '资金费率偏高',
    desc: '永续资金费率高于自定义阈值',
    type: 'funding_above',
    name: '资金费率高于自定义阈值',
    symbol: 'BTC/USDT:USDT',
    defaultThreshold: 0.0005,
    className: 'border-purple-500/30 bg-purple-500/10 text-purple-300 hover:border-purple-400/70',
  },
  {
    id: 'funding-below-custom',
    label: '资金费率偏低',
    desc: '永续资金费率低于自定义阈值',
    type: 'funding_below',
    name: '资金费率低于自定义阈值',
    symbol: 'BTC/USDT:USDT',
    defaultThreshold: -0.0005,
    className: 'border-indigo-500/30 bg-indigo-500/10 text-indigo-300 hover:border-indigo-400/70',
  },
];

export function BitProMonitorSource() {
  const navigate = useNavigate();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [runningStrategies, setRunningStrategies] = useState<RunningStrategy[]>([]);
  const [runningStrategyAssetFilter, setRunningStrategyAssetFilter] =
    useState<RunningStrategyAssetFilter>('all');
  const [liveStrategyAssetFilter, setLiveStrategyAssetFilter] =
    useState<RunningStrategyAssetFilter>('all');
  const [liveMonitorStatusFilter, setLiveMonitorStatusFilter] = useState<LiveMonitorStatusFilter>('running');
  const [liveAccounts, setLiveAccounts] = useState<LiveExecutionAccount[]>([]);
  const [liveStrategies, setLiveStrategies] = useState<LiveExecutionStrategy[]>([]);
  const [livePositions, setLivePositions] = useState<LiveExecutionPosition[]>([]);
  const [liveOrders, setLiveOrders] = useState<LiveExecutionOrder[]>([]);
  const [liveMonitorError, setLiveMonitorError] = useState('');
  const [selectedLiveMonitorAccountId, setSelectedLiveMonitorAccountId] = useState('');
  const selectedLiveMonitorAccountIdRef = useRef('');
  const liveMonitorRequestIdRef = useRef(0);
  const liveMonitorInFlightRef = useRef(false);
  const pendingLiveMonitorAccountIdRef = useRef<string | null>(null);
  const [showCreateAlert, setShowCreateAlert] = useState(false);
  const [sentiment, setSentiment] = useState<MarketSentiment>({
    longShortRatio: null,
    openInterest: null,
    openInterestBtc: null,
    openInterestChange: null,
    fundingRate: null,
    fearGreedIndex: null,
  });
  const [sentimentLoading, setSentimentLoading] = useState(false);
  const [alertToDelete, setAlertToDelete] = useState<{ id: number; name: string } | null>(null);

  const [profitPush, setProfitPush] = useState<StrategyProfitPushSettings | null>(null);
  const [profitPushInterval, setProfitPushInterval] = useState('60');
  const [profitPushSaving, setProfitPushSaving] = useState(false);
  const [profitPushSending, setProfitPushSending] = useState(false);
  const [liveProfitPush, setLiveProfitPush] = useState<StrategyProfitPushSettings | null>(null);
  const [liveProfitPushInterval, setLiveProfitPushInterval] = useState('60');
  const [liveProfitPushSaving, setLiveProfitPushSaving] = useState(false);
  const [liveProfitPushSending, setLiveProfitPushSending] = useState(false);
  const [monitorConfigOpen, setMonitorConfigOpen] = useState(false);

  useEffect(() => {
    selectedLiveMonitorAccountIdRef.current = selectedLiveMonitorAccountId;
  }, [selectedLiveMonitorAccountId]);

  const monitorSummary = useMemo(() => {
    let totalPnl = 0;
    let totalUnrealizedPnl = 0;
    let totalInitialCapital = 0;
    let totalTrades = 0;
    let closingTrades = 0;
    let winningTrades = 0;
    let grossProfit = 0;
    let grossLoss = 0;
    let fallbackWinRateWeight = 0;
    let fallbackWeightedWinRate = 0;
    let fallbackProfitFactorWeight = 0;
    let fallbackWeightedProfitFactor = 0;
    let positionStrategyCount = 0;

    for (const strategy of runningStrategies) {
      const pnl = finiteNumber(strategy.pnl);
      const initial = finiteNumber(strategy.initialCapital);
      const trades = finiteNumber(strategy.totalTrades);
      const closes = finiteNumber(strategy.closingTrades);
      const wins = finiteNumber(strategy.winningTrades);
      const winRate = finiteNumber(strategy.winRate);
      const strategyGrossProfit = finiteNumber(strategy.grossProfit);
      const strategyGrossLoss = finiteNumber(strategy.grossLoss);
      const profitFactor = finiteNumber(strategy.profitFactor, NaN);
      const hasGrossPnl = strategyGrossProfit > 0 || strategyGrossLoss > 0;

      totalPnl += pnl;
      totalUnrealizedPnl += finiteNumber(strategy.unrealizedPnl);
      totalInitialCapital += initial;
      totalTrades += trades;

      if (closes > 0) {
        closingTrades += closes;
        winningTrades += wins;
      } else if (trades > 0 && winRate > 0) {
        fallbackWinRateWeight += trades;
        fallbackWeightedWinRate += winRate * trades;
      }
      if (hasGrossPnl) {
        grossProfit += strategyGrossProfit;
        grossLoss += strategyGrossLoss;
      } else if (Number.isFinite(profitFactor) && profitFactor > 0 && trades > 0) {
        fallbackProfitFactorWeight += trades;
        fallbackWeightedProfitFactor += profitFactor * trades;
      }

      if (Object.keys(strategy.positions || {}).length > 0) {
        positionStrategyCount += 1;
      }
    }

    const returnPct = totalInitialCapital > 0 ? (totalPnl / totalInitialCapital) * 100 : 0;
    const winRate =
      closingTrades > 0
        ? (winningTrades / closingTrades) * 100
        : fallbackWinRateWeight > 0
          ? fallbackWeightedWinRate / fallbackWinRateWeight
          : 0;
    const profitFactor =
      grossLoss > 0
        ? grossProfit / grossLoss
        : fallbackProfitFactorWeight > 0
          ? fallbackWeightedProfitFactor / fallbackProfitFactorWeight
          : 0;

    return {
      totalPnl,
      totalUnrealizedPnl,
      returnPct,
      winRate,
      profitFactor,
      grossProfit,
      grossLoss,
      totalTrades,
      closingTrades,
      winningTrades,
      positionStrategyCount,
    };
  }, [runningStrategies]);

  const runningStrategyAssetCounts = useMemo(() => {
    return runningStrategies.reduce(
      (counts, strategy) => {
        counts[inferRunningStrategyAssetClass(strategy)] += 1;
        counts.total += 1;
        return counts;
      },
      { spot: 0, contract: 0, total: 0 },
    );
  }, [runningStrategies]);

  const visibleRunningStrategies = useMemo(() => {
    const filtered =
      runningStrategyAssetFilter === 'all'
        ? runningStrategies
        : runningStrategies.filter(
            strategy => inferRunningStrategyAssetClass(strategy) === runningStrategyAssetFilter,
          );
    return [...filtered].sort(compareRunningStrategiesByProfitDesc);
  }, [runningStrategies, runningStrategyAssetFilter]);

  const runningStrategyFilterLabel =
    runningStrategyAssetFilter === 'spot'
      ? '现货'
      : runningStrategyAssetFilter === 'contract'
        ? '合约'
        : '全部';

  const liveMonitorAccount = useMemo(() => {
    return (
      liveAccounts.find(account => account.accountId === selectedLiveMonitorAccountId && account.enabled && account.configured) ||
      liveAccounts.find(account => account.enabled && account.configured && account.isDefault) ||
      liveAccounts.find(account => account.enabled && account.configured) ||
      liveAccounts[0] ||
      null
    );
  }, [liveAccounts, selectedLiveMonitorAccountId]);

  const configuredLiveMonitorAccounts = useMemo(
    () => liveAccounts.filter(account => account.enabled && account.configured),
    [liveAccounts],
  );

  const livePanelStrategies = useMemo(() => {
    if (!liveMonitorAccount) return [];
    return liveStrategies
      .filter(strategy =>
        liveStrategyHasPanelDeploymentForAccount(strategy, liveMonitorAccount.accountId),
      )
      .map(strategy => liveStrategyForMonitorAccount(strategy, liveMonitorAccount.accountId));
  }, [liveMonitorAccount, liveStrategies]);

  const liveMonitorStatusCounts = useMemo(() => {
    return {
      all: livePanelStrategies.length,
      running: livePanelStrategies.filter(strategy => liveDeploymentStatusForMonitor(strategy) === 'running').length,
      paused: livePanelStrategies.filter(strategy => liveDeploymentStatusForMonitor(strategy) === 'paused').length,
    } satisfies Record<LiveMonitorStatusFilter, number>;
  }, [livePanelStrategies]);

  const liveStatusFilteredStrategies = useMemo(() => {
    return livePanelStrategies.filter(strategy =>
      liveDeploymentMatchesMonitorFilter(liveDeploymentStatusForMonitor(strategy), liveMonitorStatusFilter),
    );
  }, [liveMonitorStatusFilter, livePanelStrategies]);

  const liveStrategyAssetCounts = useMemo(() => {
    return liveStatusFilteredStrategies.reduce(
      (counts, strategy) => {
        counts[inferLiveStrategyAssetClass(strategy)] += 1;
        counts.total += 1;
        return counts;
      },
      { spot: 0, contract: 0, total: 0 },
    );
  }, [liveStatusFilteredStrategies]);

  const visibleLiveStrategies = useMemo(() => {
    const filtered = liveStrategyAssetFilter === 'all'
      ? liveStatusFilteredStrategies
      : liveStatusFilteredStrategies.filter(
          strategy => inferLiveStrategyAssetClass(strategy) === liveStrategyAssetFilter,
        );
    return [...filtered].sort(compareLiveStrategiesByReturnDesc);
  }, [liveStatusFilteredStrategies, liveStrategyAssetFilter]);

  const liveStrategyFilterLabel =
    liveStrategyAssetFilter === 'spot'
      ? '现货'
      : liveStrategyAssetFilter === 'contract'
        ? '合约'
        : '全部';

  const liveMonitorStatusFilterLabel =
    liveMonitorStatusFilter === 'running'
      ? '运行中'
      : liveMonitorStatusFilter === 'paused'
        ? '暂停'
        : '全部';
  const liveMonitorEmptyFilterLabel =
    liveStrategyAssetFilter === 'all'
      ? liveMonitorStatusFilterLabel
      : `${liveMonitorStatusFilterLabel}${liveStrategyFilterLabel}`;

  const liveContractPositions = useMemo(
    () => livePositions.filter(isOpenContractLivePosition),
    [livePositions],
  );

  const liveMonitorSummary = useMemo(() => {
    const totalNotional = liveContractPositions.reduce((sum, position) => sum + livePositionNotionalUsdt(position), 0);
    const totalUnrealizedPnl = liveContractPositions.reduce(
      (sum, position) => sum + finiteNumber(position.unrealizedPnl),
      0,
    );
    const todayOrders = liveOrders.filter(liveOrderIsToday);
    const filledOrders = liveOrders.filter(order => {
      const status = String(order.status || order.rawStatus || '').toLowerCase();
      return ['filled', 'closed', '成交', '已成交'].some(item => status.includes(item));
    }).length;
    const todayFilledOrders = todayOrders.filter(order => {
      const status = String(order.status || order.rawStatus || '').toLowerCase();
      return ['filled', 'closed', '成交', '已成交'].some(item => status.includes(item));
    }).length;
    const todayRealizedPnl = todayOrders.reduce((sum, order) => sum + liveOrderRealizedPnl(order), 0);
    const todayFees = todayOrders.reduce((sum, order) => sum + Math.abs(liveOrderFee(order)), 0);
    const riskPositionCount = liveContractPositions.filter(position => {
      const marginRatio = finiteNumber(position.marginRatio, NaN);
      const liquidationDistance = livePositionLiquidationDistancePct(position);
      return (
        (Number.isFinite(marginRatio) && marginRatio >= 0.8) ||
        (liquidationDistance != null && liquidationDistance <= 10)
      );
    }).length;

    return {
      accountCount: liveAccounts.filter(account => account.enabled && account.configured).length,
      liveSubscriptionCount: livePanelStrategies.length,
      runningSubscriptionCount: livePanelStrategies.filter(
        strategy => liveDeploymentStatusForMonitor(strategy) === 'running',
      ).length,
      positionCount: liveContractPositions.length,
      totalNotional,
      totalUnrealizedPnl,
      orderCount: liveOrders.length,
      filledOrders,
      todayOrderCount: todayOrders.length,
      todayFilledOrders,
      todayRealizedPnl,
      todayFees,
      riskPositionCount,
    };
  }, [liveAccounts, liveContractPositions, liveOrders, livePanelStrategies]);

  const strategyNotionalUsdt = useMemo(() => {
    return runningStrategies.reduce((sum, s) => {
      for (const p of Object.values(s.positions || {})) {
        sum += positionNotionalUsdt(p);
      }
      return sum;
    }, 0);
  }, [runningStrategies]);

  const { positionCardValue, positionCardSub } = useMemo(() => {
    const oi = sentiment.openInterest;
    const oiBtc = sentiment.openInterestBtc;
    const hasStrat = strategyNotionalUsdt > 1e-6;
    const hasOi = oi != null && oi > 0;

    if (hasStrat) {
      const main = `$${strategyNotionalUsdt.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
      let sub: string;
      if (hasOi) {
        sub = `全市场 OI ${Number(oi).toLocaleString()} 张`;
        if (oiBtc != null && oiBtc > 0) {
          sub += ` (≈${oiBtc.toFixed(2)} BTC)`;
        }
      } else {
        sub = '按各策略标记价估算持仓金额';
      }
      return { positionCardValue: main, positionCardSub: sub };
    }
    if (hasOi) {
      const main =
        oiBtc != null && oiBtc > 0
          ? `≈ ${oiBtc.toFixed(3)} BTC`
          : `${Number(oi).toLocaleString()} 张`;
      const sub =
        oiBtc != null && oiBtc > 0
          ? `${Number(oi).toLocaleString()} 张合约`
          : '全市场未平仓（OKX BTC-SWAP）';
      return { positionCardValue: main, positionCardSub: sub };
    }
    return { positionCardValue: '--', positionCardSub: '暂无策略持仓与市场 OI' };
  }, [strategyNotionalUsdt, sentiment.openInterest, sentiment.openInterestBtc]);

  const profitPushStatusText = useMemo(() => {
    if (!profitPush) return '加载中';
    if (!profitPush.webhookConfigured) {
      return profitPush.enabled ? 'Webhook 未配置' : '已关闭 · Webhook 未配置';
    }
    if (!profitPush.notifyReady) {
      return profitPush.enabled ? '飞书推送未就绪' : '已关闭 · Webhook 已配置';
    }
    if (!profitPush.enabled) return '已关闭 · Webhook 已配置';
    if (hasFreshProfitPushError(profitPush)) return `上次发送失败：${profitPush.lastError}`;
    if (profitPush.lastSkipReason === 'no_running_strategies') return '上次跳过：无运行策略';
    if (profitPush.lastSentAt) {
      const mode = profitPush.lastDeliveryType === 'image' ? '图片' : profitPush.lastDeliveryType === 'card' ? '卡片' : '收益卡片';
      if (profitPush.lastDeliveryType === 'card' && !profitPush.profitReportImageReady) {
        return `上次发卡片 · ${profitPushImageReasonText(profitPush.lastDeliveryError || profitPush.profitReportImageReason)}`;
      }
      return `上次${mode} ${formatLocalTime(profitPush.lastSentAt)}`;
    }
    if (profitPush.profitReportImageReady) return '图片推送就绪，等待首次推送';
    return `当前会发卡片 · ${profitPushImageReasonText(profitPush.profitReportImageReason)}`;
  }, [profitPush]);

  const liveProfitPushStatusText = useMemo(() => {
    if (!liveProfitPush) return '加载中';
    if (!liveProfitPush.webhookConfigured) {
      return liveProfitPush.enabled ? 'Webhook 未配置' : '已关闭 · Webhook 未配置';
    }
    if (!liveProfitPush.notifyReady) {
      return liveProfitPush.enabled ? '飞书推送未就绪' : '已关闭 · Webhook 已配置';
    }
    if (!liveProfitPush.enabled) return '已关闭 · Webhook 已配置';
    if (hasFreshProfitPushError(liveProfitPush)) return `上次发送失败：${liveProfitPush.lastError}`;
    if (liveProfitPush.lastSkipReason === 'no_live_positions') return '上次跳过：无实盘持仓';
    if (liveProfitPush.lastSentAt) {
      const mode = liveProfitPush.lastDeliveryType === 'image' ? '图片' : liveProfitPush.lastDeliveryType === 'card' ? '卡片' : '收益卡片';
      if (liveProfitPush.lastDeliveryType === 'card' && !liveProfitPush.profitReportImageReady) {
        return `上次发卡片 · ${profitPushImageReasonText(liveProfitPush.lastDeliveryError || liveProfitPush.profitReportImageReason)}`;
      }
      return `上次${mode} ${formatLocalTime(liveProfitPush.lastSentAt)}`;
    }
    if (liveProfitPush.profitReportImageReady) return '图片推送就绪，等待首次推送';
    return `当前会发卡片 · ${profitPushImageReasonText(liveProfitPush.profitReportImageReason)}`;
  }, [liveProfitPush]);

  const profitPushActionTitle = useMemo(() => {
    if (!profitPush) return '正在加载收益卡片推送配置';
    if (profitPushSending) return '正在推送收益卡片';
    if (!profitPush.webhookConfigured) return 'Webhook 未配置，无法立即推送';
    if (!profitPush.notifyReady) return '飞书推送未就绪，无法立即推送';
    return '立即推送收益卡片';
  }, [profitPush, profitPushSending]);
  const profitPushSendDisabled = profitPushSending || !profitPush?.notifyReady;

  const liveProfitPushActionTitle = useMemo(() => {
    if (!liveProfitPush) return '正在加载实盘收益卡片推送配置';
    if (liveProfitPushSending) return '正在推送实盘收益卡片';
    if (!liveProfitPush.webhookConfigured) return 'Webhook 未配置，无法立即推送';
    if (!liveProfitPush.notifyReady) return '飞书推送未就绪，无法立即推送';
    return '立即推送实盘收益卡片';
  }, [liveProfitPush, liveProfitPushSending]);
  const liveProfitPushSendDisabled = liveProfitPushSending || !liveProfitPush?.notifyReady;

  const [alertForm, setAlertForm] = useState({
    name: '', type: 'price_above', exchange: 'okx', symbol: 'BTC/USDT',
    threshold: 100000, strategyId: 0, cooldownMinutes: 60,
  });
  const selectedAlertStrategyId = finiteNumber(alertForm.strategyId || runningStrategies[0]?.strategyId, 0);

  const applyAlertTemplate = (template: AlertTemplate) => {
    const isStrategyAlert = isStrategyScopedAlertType(template.type);
    setAlertForm({
      ...alertForm,
      name: template.name,
      type: template.type,
      symbol: template.symbol || alertForm.symbol,
      threshold: template.defaultThreshold,
      strategyId: isStrategyAlert ? selectedAlertStrategyId : alertForm.strategyId,
      cooldownMinutes: template.cooldownMinutes || alertForm.cooldownMinutes || 60,
    });
  };

  useEffect(() => {
    fetchAlerts();
    fetchRunningStrategies();
    fetchLiveMonitor();
    fetchMarketSentiment();
    fetchProfitPushSettings();
    fetchLiveProfitPushSettings();
    const fastInterval = setInterval(() => {
      fetchRunningStrategies();
    }, 5000);
    const liveMonitorInterval = setInterval(() => {
      fetchLiveMonitor();
    }, 15000);
    const slowInterval = setInterval(() => {
      fetchAlerts();
      fetchMarketSentiment();
      fetchProfitPushSettings();
      fetchLiveProfitPushSettings();
    }, 30000);
    return () => {
      clearInterval(fastInterval);
      clearInterval(liveMonitorInterval);
      clearInterval(slowInterval);
    };
  }, []);

  const fetchProfitPushSettings = async () => {
    try {
      const res = await settingsApi.getStrategyProfitPush();
      setProfitPush(res);
      setProfitPushInterval(String(res.intervalMinutes || 60));
    } catch {}
  };

  const fetchLiveProfitPushSettings = async () => {
    try {
      const res = await settingsApi.getLiveProfitPush();
      setLiveProfitPush(res);
      setLiveProfitPushInterval(String(res.intervalMinutes || 60));
    } catch {}
  };

  const parsedProfitPushInterval = () => {
    const raw = Number.parseInt(profitPushInterval, 10);
    if (!Number.isFinite(raw)) return profitPush?.intervalMinutes || 60;
    return Math.max(1, Math.min(raw, 1440));
  };

  const parsedLiveProfitPushInterval = () => {
    const raw = Number.parseInt(liveProfitPushInterval, 10);
    if (!Number.isFinite(raw)) return liveProfitPush?.intervalMinutes || 60;
    return Math.max(1, Math.min(raw, 1440));
  };

  const adjustProfitPushInterval = (delta: number) => {
    const next = Math.max(1, Math.min(parsedProfitPushInterval() + delta, 1440));
    setProfitPushInterval(String(next));
    if (!profitPush || next !== profitPush.intervalMinutes) {
      void updateProfitPushSettings({ intervalMinutes: next });
    }
  };

  const adjustLiveProfitPushInterval = (delta: number) => {
    const next = Math.max(1, Math.min(parsedLiveProfitPushInterval() + delta, 1440));
    setLiveProfitPushInterval(String(next));
    if (!liveProfitPush || next !== liveProfitPush.intervalMinutes) {
      void updateLiveProfitPushSettings({ intervalMinutes: next });
    }
  };

  const updateProfitPushSettings = async (patch: Partial<StrategyProfitPushSettings>) => {
    setProfitPushSaving(true);
    try {
      const intervalMinutes =
        patch.intervalMinutes != null ? patch.intervalMinutes : parsedProfitPushInterval();
      const res = await settingsApi.setStrategyProfitPush({
        enabled: patch.enabled,
        intervalMinutes,
      });
      setProfitPush(res);
      setProfitPushInterval(String(res.intervalMinutes || intervalMinutes));
    } catch {}
    setProfitPushSaving(false);
  };

  const updateLiveProfitPushSettings = async (patch: Partial<StrategyProfitPushSettings>) => {
    setLiveProfitPushSaving(true);
    try {
      const intervalMinutes =
        patch.intervalMinutes != null ? patch.intervalMinutes : parsedLiveProfitPushInterval();
      const res = await settingsApi.setLiveProfitPush({
        enabled: patch.enabled,
        intervalMinutes,
      });
      setLiveProfitPush(res);
      setLiveProfitPushInterval(String(res.intervalMinutes || intervalMinutes));
    } catch {}
    setLiveProfitPushSaving(false);
  };

  const sendProfitPushNow = async () => {
    if (profitPushSendDisabled) return;
    setProfitPushSending(true);
    try {
      const res = await settingsApi.sendStrategyProfitPushNow();
      setProfitPush(res);
      setProfitPushInterval(String(res.intervalMinutes || parsedProfitPushInterval()));
    } catch (error) {
      const message = getApiErrorMessage(error, '立即推送收益卡片失败');
      setProfitPush(prev => prev ? { ...prev, lastError: message } : prev);
    } finally {
      setProfitPushSending(false);
    }
  };

  const sendLiveProfitPushNow = async () => {
    if (liveProfitPushSendDisabled) return;
    setLiveProfitPushSending(true);
    try {
      const res = await settingsApi.sendLiveProfitPushNow();
      setLiveProfitPush(res);
      setLiveProfitPushInterval(String(res.intervalMinutes || parsedLiveProfitPushInterval()));
    } catch (error) {
      const message = getApiErrorMessage(error, '立即推送实盘收益卡片失败');
      setLiveProfitPush(prev => prev ? { ...prev, lastError: message } : prev);
    } finally {
      setLiveProfitPushSending(false);
    }
  };

  const saveProfitPushInterval = () => {
    const next = parsedProfitPushInterval();
    setProfitPushInterval(String(next));
    if (!profitPush || next !== profitPush.intervalMinutes) {
      void updateProfitPushSettings({ intervalMinutes: next });
    }
  };

  const saveLiveProfitPushInterval = () => {
    const next = parsedLiveProfitPushInterval();
    setLiveProfitPushInterval(String(next));
    if (!liveProfitPush || next !== liveProfitPush.intervalMinutes) {
      void updateLiveProfitPushSettings({ intervalMinutes: next });
    }
  };

  const fetchAlerts = async () => {
    try {
      const data = await monitorApi.getAlerts();
      setAlerts(data);
    } catch {}
  };

  const fetchRunningStrategies = async () => {
    try {
      const data = await monitorApi.getActiveStrategies();
      setRunningStrategies(Array.isArray(data) ? data : []);
    } catch {}
  };

  const fetchLiveMonitor = async (
    requestedAccountId = selectedLiveMonitorAccountIdRef.current,
    queueIfBusy = false,
  ) => {
    if (liveMonitorInFlightRef.current) {
      if (queueIfBusy) pendingLiveMonitorAccountIdRef.current = requestedAccountId;
      return;
    }
    liveMonitorInFlightRef.current = true;
    const requestId = ++liveMonitorRequestIdRef.current;
    try {
      const [accountsRes, strategiesRes] = await Promise.all([
        liveExecutionApi.listAccounts(),
        liveExecutionApi.listStrategies(),
      ]);
      const accounts = accountsRes.accounts || [];
      const strategies = strategiesRes.strategies || [];
      const monitorAccount =
        accounts.find(account => account.accountId === requestedAccountId && account.enabled && account.configured) ||
        accounts.find(account => account.enabled && account.configured && account.isDefault) ||
        accounts.find(account => account.enabled && account.configured);

      if (requestId !== liveMonitorRequestIdRef.current) return;
      setLiveAccounts(accounts);
      setLiveStrategies(strategies);
      setLiveMonitorError('');

      if (!monitorAccount) {
        setSelectedLiveMonitorAccountId('');
        setLivePositions([]);
        setLiveOrders([]);
        return;
      }

      setSelectedLiveMonitorAccountId(current => current === monitorAccount.accountId ? current : monitorAccount.accountId);

      const [positionsRes, ordersRes] = await Promise.all([
        liveExecutionApi.listPositions(monitorAccount.accountId),
        liveExecutionApi.listOrderHistory(monitorAccount.accountId, undefined, 50),
      ]);
      if (requestId !== liveMonitorRequestIdRef.current) return;
      setLivePositions(positionsRes.positions || []);
      setLiveOrders(ordersRes.orders || []);
    } catch (error) {
      if (requestId !== liveMonitorRequestIdRef.current) return;
      setLiveMonitorError(getApiErrorMessage(error, '读取实盘监控失败'));
    } finally {
      liveMonitorInFlightRef.current = false;
      const pendingAccountId = pendingLiveMonitorAccountIdRef.current;
      pendingLiveMonitorAccountIdRef.current = null;
      if (pendingAccountId !== null) void fetchLiveMonitor(pendingAccountId);
    }
  };

  const selectLiveMonitorAccount = (nextAccountId: string) => {
    setSelectedLiveMonitorAccountId(nextAccountId);
    setLivePositions([]);
    setLiveOrders([]);
    setLiveMonitorError('');
    void fetchLiveMonitor(nextAccountId, true);
  };

  const fetchMarketSentiment = async () => {
    setSentimentLoading(true);
    try {
      // 并行请求多个数据源
      const [lsRes, oiRes, _frRes] = await Promise.allSettled([
        monitorApi.getLongShortRatio('okx', 'BTC/USDT:USDT'),
        monitorApi.getOpenInterest('okx', 'BTC/USDT:USDT'),
        marketApi.getTicker('okx', 'BTC/USDT'),
      ]);

      const longShortValue =
        lsRes.status === 'fulfilled' ? (lsRes.value.ratio ?? lsRes.value.longShortRatio ?? null) : null;

      setSentiment({
        longShortRatio: longShortValue != null ? Number(longShortValue) : null,
        openInterest: oiRes.status === 'fulfilled' ? (oiRes.value.openInterest ?? null) : null,
        openInterestBtc: oiRes.status === 'fulfilled' ? (oiRes.value.openInterestBtc ?? null) : null,
        openInterestChange: oiRes.status === 'fulfilled' ? (oiRes.value.change ?? oiRes.value.changePct ?? null) : null,
        fundingRate: null, // 后续可扩展
        fearGreedIndex: null,
      });
    } catch {
      // 保持默认
    } finally {
      setSentimentLoading(false);
    }
  };

  const createAlert = async () => {
    try {
      const isStrategyAlert = isStrategyScopedAlertType(alertForm.type);
      await monitorApi.createAlert({
        name: alertForm.name,
        type: alertForm.type,
        exchange: alertForm.exchange,
        symbol: isStrategyAlert ? undefined : alertForm.symbol,
        threshold: alertForm.threshold,
        strategyId: isStrategyAlert ? selectedAlertStrategyId : undefined,
        cooldownSec: isStrategyAlert ? Math.max(1, alertForm.cooldownMinutes) * 60 : undefined,
      });
      setShowCreateAlert(false); fetchAlerts();
      setAlertForm({
        name: '',
        type: 'price_above',
        exchange: 'okx',
        symbol: 'BTC/USDT',
        threshold: 100000,
        strategyId: 0,
        cooldownMinutes: 60,
      });
    } catch {}
  };

  const toggleAlert = async (id: number, enabled: boolean) => {
    try {
      await monitorApi.toggleAlert(id, !enabled);
      fetchAlerts();
    } catch {}
  };

  const runDeleteAlert = async () => {
    if (!alertToDelete) return;
    const id = alertToDelete.id;
    setAlertToDelete(null);
    try {
      await monitorApi.deleteAlert(id);
      fetchAlerts();
    } catch {}
  };

  const alertTypeLabels: Record<string, string> = {
    price_above: '价格高于', price_below: '价格低于', price_change: '价格变动%',
    funding_above: '费率高于', funding_below: '费率低于', strategy_return_below: '策略收益低于',
    strategy_liquidation_risk: '爆仓前告警',
  };

  const alertDescription = (alert: Alert) => {
    if (alert.type === 'strategy_return_below') {
      const name = alert.condition?.strategyName || `策略 #${alert.condition?.strategyId ?? '--'}`;
      const threshold = Number(alert.condition?.threshold ?? -5);
      return `${name} · 收益率低于 ${threshold}%`;
    }
    if (alert.type === 'strategy_liquidation_risk') {
      const name = alert.condition?.strategyName || `策略 #${alert.condition?.strategyId ?? '--'}`;
      const threshold = Number(alert.condition?.threshold ?? 10);
      return `${name} · 爆仓距离低于 ${threshold}%`;
    }
    return `${alert.symbol || '--'} · ${alertTypeLabels[alert.type] || alert.type} ${alert.condition?.threshold}`;
  };

  const isStrategyAlertForm = isStrategyScopedAlertType(alertForm.type);
  const strategyThresholdLabel =
    alertForm.type === 'strategy_liquidation_risk' ? '爆仓距离低于 (%)' : '收益率低于 (%)';
  const strategyThresholdPlaceholder =
    alertForm.type === 'strategy_liquidation_risk' ? '输入强平距离百分比' : '输入收益率百分比';
  const strategyThresholdHint =
    alertForm.type === 'strategy_liquidation_risk'
      ? '使用正数；数值越小越接近强平价。'
      : '亏损阈值使用负数；达到或低于该收益率时记录告警。';

  return (
    <div className="p-6 h-full flex flex-col">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Eye className="w-6 h-6 text-blue-400" />
          <h1 className="text-2xl font-bold text-white">监控中心</h1>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={fetchMarketSentiment} disabled={sentimentLoading}
            className="flex items-center gap-1.5 px-3 py-2 text-xs text-gray-400 hover:text-white bg-crypto-card border border-crypto-border rounded-xl transition-colors">
            <RefreshCw className={clsx('w-3.5 h-3.5', sentimentLoading && 'animate-spin')} />刷新数据
          </button>
        </div>
      </div>

      <div className="monitorOverviewGrid mb-6 grid grid-cols-1 gap-4 2xl:grid-cols-2">
        <section className="monitor-overview-panel rounded-xl border border-blue-500/15 bg-crypto-card p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
                <Activity className="h-4 w-4 text-green-400" />
                模拟盘总览
              </h2>
              <p className="mt-1 text-[11px] text-gray-500">纸面账户、运行策略和模拟成交表现</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <SentimentCard
              label="持仓总金额"
              value={positionCardValue}
              icon={<DollarSign className="w-4 h-4" />}
              color="blue"
              sub={positionCardSub}
            />
            <SentimentCard
              label="总盈亏"
              value={formatSignedUsd(monitorSummary.totalPnl)}
              icon={<DollarSign className="w-4 h-4" />}
              color={signedMetricColor(monitorSummary.totalPnl)}
              sub={`共 ${monitorSummary.totalTrades} 笔交易`}
            />
            <SentimentCard
              label="浮动盈亏"
              value={formatSignedUsd(monitorSummary.totalUnrealizedPnl)}
              icon={<Activity className="w-4 h-4" />}
              color={signedMetricColor(monitorSummary.totalUnrealizedPnl)}
              sub={monitorSummary.positionStrategyCount > 0 ? `${monitorSummary.positionStrategyCount} 个策略有持仓` : '暂无持仓浮盈'}
            />
            <SentimentCard
              label="收益率"
              value={formatSignedPercent(monitorSummary.returnPct)}
              icon={<BarChart3 className="w-4 h-4" />}
              color={signedMetricColor(monitorSummary.returnPct)}
              sub={runningStrategies.length > 0 ? '按初始资金加权' : '暂无运行策略'}
            />
            <SentimentCard
              label="胜率"
              value={formatPercent(monitorSummary.winRate)}
              icon={<Zap className="w-4 h-4" />}
              color="blue"
              sub={
                monitorSummary.closingTrades > 0
                  ? `${monitorSummary.winningTrades}/${monitorSummary.closingTrades} 笔平仓盈利`
                  : '暂无平仓样本'
              }
            />
            <SentimentCard
              label="盈亏比"
              value={formatRatio(monitorSummary.profitFactor)}
              icon={<BarChart3 className="w-4 h-4" />}
              color="blue"
              sub={monitorSummary.grossLoss > 0 ? '总盈利 / 总亏损' : '暂无亏损样本'}
            />
            <SentimentCard
              label="多空比"
              value={sentiment.longShortRatio != null ? sentiment.longShortRatio.toFixed(2) : '--'}
              icon={<BarChart3 className="w-4 h-4" />}
              color={sentiment.longShortRatio != null ? (sentiment.longShortRatio > 1 ? 'green' : sentiment.longShortRatio < 1 ? 'red' : 'gray') : 'gray'}
              sub={sentiment.longShortRatio != null ? (sentiment.longShortRatio > 1 ? '多头占优' : sentiment.longShortRatio < 1 ? '空头占优' : '多空均衡') : '获取中...'}
            />
            <SentimentCard
              label="策略/告警"
              value={`${runningStrategies.length}/${activeAlertCount(alerts)}`}
              icon={<Bell className="w-4 h-4" />}
              color={activeAlertCount(alerts) > 0 ? 'yellow' : runningStrategies.length > 0 ? 'green' : 'gray'}
              sub={`运行中 / 活跃告警，共 ${alerts.length} 条规则`}
            />
          </div>
        </section>

        <section className="monitor-overview-panel rounded-xl border border-blue-500/15 bg-crypto-card p-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
                <Activity className="h-4 w-4 text-blue-400" />
                实盘总览
              </h2>
              <p className="mt-1 text-[11px] text-gray-500">真实账户只读持仓、订单和风险状态</p>
            </div>
            <LiveMonitorAccountTabs
              ariaLabel="实盘总览账户切换"
              accounts={configuredLiveMonitorAccounts}
              value={liveMonitorAccount?.accountId || ''}
              onChange={selectLiveMonitorAccount}
              className="min-w-[252px]"
            />
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <SentimentCard
              label="实盘账户"
              value={String(liveMonitorSummary.accountCount)}
              icon={<Eye className="w-4 h-4" />}
              color={liveMonitorSummary.accountCount > 0 ? 'blue' : 'gray'}
              sub={liveMonitorAccount
                ? `当前：${liveMonitorAccount.name} · ${accountExchangeLabel(liveMonitorAccount)}`
                : '暂无可用账户'}
            />
            <SentimentCard
              label="运行中策略"
              value={String(liveMonitorSummary.runningSubscriptionCount)}
              icon={<Activity className="w-4 h-4" />}
              color={liveMonitorSummary.runningSubscriptionCount > 0 ? 'green' : 'gray'}
              sub={`共 ${liveMonitorSummary.liveSubscriptionCount} 个实盘订阅 / ${liveMonitorStatusCounts.paused} 暂停`}
            />
            <SentimentCard
              label="合约持仓"
              value={String(liveMonitorSummary.positionCount)}
              icon={<BarChart3 className="w-4 h-4" />}
              color={liveMonitorSummary.positionCount > 0 ? 'blue' : 'gray'}
              sub="非零 USDT 永续仓位"
            />
            <SentimentCard
              label="持仓名义"
              value={formatUsd(liveMonitorSummary.totalNotional, 0)}
              icon={<DollarSign className="w-4 h-4" />}
              color="blue"
              sub="按当前标记价估算"
            />
            <SentimentCard
              label="浮动盈亏"
              value={formatSignedUsd(liveMonitorSummary.totalUnrealizedPnl)}
              icon={<Activity className="w-4 h-4" />}
              color={signedMetricColor(liveMonitorSummary.totalUnrealizedPnl)}
              sub={liveMonitorSummary.positionCount > 0 ? `${liveMonitorSummary.positionCount} 个合约仓位` : '暂无实盘持仓'}
            />
            <SentimentCard
              label="今日已实现"
              value={formatSignedUsd(liveMonitorSummary.todayRealizedPnl)}
              icon={<DollarSign className="w-4 h-4" />}
              color={signedMetricColor(liveMonitorSummary.todayRealizedPnl)}
              sub={`${liveMonitorSummary.todayFilledOrders} 笔今日成交`}
            />
            <SentimentCard
              label="今日手续费"
              value={formatUsd(liveMonitorSummary.todayFees)}
              icon={<DollarSign className="w-4 h-4" />}
              color={liveMonitorSummary.todayFees > 0 ? 'yellow' : 'gray'}
              sub={`${liveMonitorSummary.todayOrderCount} 条今日订单`}
            />
            <SentimentCard
              label="风险提示"
              value={String(liveMonitorSummary.riskPositionCount)}
              icon={<Bell className="w-4 h-4" />}
              color={liveMonitorSummary.riskPositionCount > 0 ? 'red' : 'green'}
              sub={liveMonitorSummary.riskPositionCount > 0 ? '保证金率或强平距离需关注' : '暂无接近强平仓位'}
            />
          </div>
        </section>
      </div>

      <div className="monitorConfigPanel mb-6 rounded-xl border border-crypto-border bg-crypto-card">
        <button
          type="button"
          onClick={() => setMonitorConfigOpen(open => !open)}
          aria-expanded={monitorConfigOpen}
          className="flex w-full items-center justify-between gap-3 border-b border-crypto-border p-4 text-left transition-colors hover:bg-white/[0.02]"
        >
          <div className="flex min-w-0 items-center gap-2">
            <Bell className="h-4 w-4 text-blue-400" />
            <h2 className="text-sm font-semibold text-white">监控配置</h2>
            <span className="truncate text-xs text-gray-500">推送、告警规则和触发阈值统一在这里维护</span>
          </div>
          <div className="flex shrink-0 items-center gap-2 text-[10px] text-gray-500">
            <span>模拟推送 {profitPush ? (profitPush.enabled ? 'ON' : 'OFF') : '--'}</span>
            <span>实盘推送 {liveProfitPush ? (liveProfitPush.enabled ? 'ON' : 'OFF') : '--'}</span>
            <span>告警 {activeAlertCount(alerts)}</span>
            <ChevronRight className={clsx('h-4 w-4 transition-transform', monitorConfigOpen && 'rotate-90')} />
          </div>
        </button>
        {monitorConfigOpen && (
          <div className="grid grid-cols-1 gap-4 p-4 xl:grid-cols-[minmax(520px,720px)_minmax(0,1fr)]">
          <div className="monitor-profit-push-stack grid grid-cols-1 gap-3">
            <div className="monitor-profit-push-card rounded-xl border border-crypto-border bg-crypto-bg/70 p-4">
              <div className="mb-4 flex items-center gap-2">
                <Clock className="h-4 w-4 text-blue-400" />
                <div className="min-w-0">
                  <div className="text-xs font-medium text-white">模拟盘收益卡片推送</div>
                  <div className="truncate text-[10px] text-gray-500" title={profitPushStatusText}>
                    {profitPushStatusText}
                  </div>
                </div>
              </div>
              <div className="monitor-profit-push-controls flex w-full flex-wrap items-center gap-2">
                <div className="monitor-profit-push-toggle-row flex w-[104px] shrink-0">
                  <button
                    type="button"
                    onClick={() => void updateProfitPushSettings({ enabled: !profitPush?.enabled })}
                    disabled={profitPushSaving}
                    className={clsx(
                      'inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-lg border px-2 text-[11px] transition-colors',
                      profitPush?.enabled
                        ? 'border-green-500/30 bg-green-500/10 text-green-400'
                        : 'border-crypto-border bg-transparent text-gray-500 hover:text-gray-300',
                    )}
                  >
                    {profitPush?.enabled ? <ToggleRight className="h-4 w-4" /> : <ToggleLeft className="h-4 w-4" />}
                    {profitPush?.enabled ? 'ON' : 'OFF'}
                  </button>
                </div>
                <div className="monitor-profit-push-interval-row inline-flex h-8 w-[176px] shrink-0 items-stretch overflow-hidden rounded-lg border border-crypto-border bg-crypto-bg text-[11px] text-gray-400 transition-colors focus-within:border-blue-500/50 focus-within:bg-blue-500/5">
                  <span className="flex w-8 items-center justify-center border-r border-crypto-border text-gray-500">每</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    value={profitPushInterval}
                    onChange={e => setProfitPushInterval(e.target.value.replace(/[^\d]/g, ''))}
                    onBlur={saveProfitPushInterval}
                    onKeyDown={e => {
                      if (e.key === 'Enter') e.currentTarget.blur();
                    }}
                    aria-label="收益卡片推送间隔分钟数"
                    className="h-full w-9 bg-transparent px-1 text-center text-sm font-semibold tabular-nums text-white outline-none"
                  />
                  <span className="flex flex-1 items-center justify-center text-gray-400">分钟</span>
                  <div className="flex border-l border-crypto-border">
                    <button
                      type="button"
                      aria-label="减少推送间隔"
                      onMouseDown={e => e.preventDefault()}
                      onClick={() => adjustProfitPushInterval(-1)}
                      disabled={profitPushSaving}
                      className="flex w-6 items-center justify-center text-gray-500 transition-colors hover:bg-gray-800 hover:text-gray-200 disabled:cursor-not-allowed disabled:text-gray-700"
                    >
                      <Minus className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      aria-label="增加推送间隔"
                      onMouseDown={e => e.preventDefault()}
                      onClick={() => adjustProfitPushInterval(1)}
                      disabled={profitPushSaving}
                      className="flex w-6 items-center justify-center border-l border-crypto-border text-gray-500 transition-colors hover:bg-gray-800 hover:text-gray-200 disabled:cursor-not-allowed disabled:text-gray-700"
                    >
                      <Plus className="h-3 w-3" />
                    </button>
                  </div>
                </div>
                <div className="monitor-profit-push-send-row flex w-[136px] shrink-0" title={profitPushActionTitle}>
                  <button
                    type="button"
                    aria-label={profitPushActionTitle}
                    onClick={() => void sendProfitPushNow()}
                    disabled={profitPushSendDisabled}
                    className={clsx(
                      'inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-lg border px-2 text-[11px] transition-colors',
                      profitPushSendDisabled
                        ? 'cursor-not-allowed border-crypto-border bg-crypto-bg text-gray-500'
                        : 'border-blue-500/30 bg-blue-600/15 text-blue-400 hover:bg-blue-600/25',
                    )}
                  >
                    {profitPushSending ? (
                      <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Send className="h-3.5 w-3.5" />
                    )}
                    {profitPushSending ? '发送中' : '立即推送'}
                  </button>
                </div>
              </div>
            </div>

            <div className="monitor-profit-push-card rounded-xl border border-crypto-border bg-crypto-bg/70 p-4">
              <div className="mb-4 flex items-center gap-2">
                <Clock className="h-4 w-4 text-green-400" />
                <div className="min-w-0">
                  <div className="text-xs font-medium text-white">实盘收益卡片推送</div>
                  <div className="truncate text-[10px] text-gray-500" title={liveProfitPushStatusText}>
                    {liveProfitPushStatusText}
                  </div>
                </div>
              </div>
              <div className="monitor-profit-push-controls flex w-full flex-wrap items-center gap-2">
                <div className="monitor-profit-push-toggle-row flex w-[104px] shrink-0">
                  <button
                    type="button"
                    onClick={() => void updateLiveProfitPushSettings({ enabled: !liveProfitPush?.enabled })}
                    disabled={liveProfitPushSaving}
                    className={clsx(
                      'inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-lg border px-2 text-[11px] transition-colors',
                      liveProfitPush?.enabled
                        ? 'border-green-500/30 bg-green-500/10 text-green-400'
                        : 'border-crypto-border bg-transparent text-gray-500 hover:text-gray-300',
                    )}
                  >
                    {liveProfitPush?.enabled ? <ToggleRight className="h-4 w-4" /> : <ToggleLeft className="h-4 w-4" />}
                    {liveProfitPush?.enabled ? 'ON' : 'OFF'}
                  </button>
                </div>
                <div className="monitor-profit-push-interval-row inline-flex h-8 w-[176px] shrink-0 items-stretch overflow-hidden rounded-lg border border-crypto-border bg-crypto-bg text-[11px] text-gray-400 transition-colors focus-within:border-blue-500/50 focus-within:bg-blue-500/5">
                  <span className="flex w-8 items-center justify-center border-r border-crypto-border text-gray-500">每</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    value={liveProfitPushInterval}
                    onChange={e => setLiveProfitPushInterval(e.target.value.replace(/[^\d]/g, ''))}
                    onBlur={saveLiveProfitPushInterval}
                    onKeyDown={e => {
                      if (e.key === 'Enter') e.currentTarget.blur();
                    }}
                    aria-label="实盘收益卡片推送间隔分钟数"
                    className="h-full w-9 bg-transparent px-1 text-center text-sm font-semibold tabular-nums text-white outline-none"
                  />
                  <span className="flex flex-1 items-center justify-center text-gray-400">分钟</span>
                  <div className="flex border-l border-crypto-border">
                    <button
                      type="button"
                      aria-label="减少实盘推送间隔"
                      onMouseDown={e => e.preventDefault()}
                      onClick={() => adjustLiveProfitPushInterval(-1)}
                      disabled={liveProfitPushSaving}
                      className="flex w-6 items-center justify-center text-gray-500 transition-colors hover:bg-gray-800 hover:text-gray-200 disabled:cursor-not-allowed disabled:text-gray-700"
                    >
                      <Minus className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      aria-label="增加实盘推送间隔"
                      onMouseDown={e => e.preventDefault()}
                      onClick={() => adjustLiveProfitPushInterval(1)}
                      disabled={liveProfitPushSaving}
                      className="flex w-6 items-center justify-center border-l border-crypto-border text-gray-500 transition-colors hover:bg-gray-800 hover:text-gray-200 disabled:cursor-not-allowed disabled:text-gray-700"
                    >
                      <Plus className="h-3 w-3" />
                    </button>
                  </div>
                </div>
                <div className="monitor-profit-push-send-row flex w-[136px] shrink-0" title={liveProfitPushActionTitle}>
                  <button
                    type="button"
                    aria-label={liveProfitPushActionTitle}
                    onClick={() => void sendLiveProfitPushNow()}
                    disabled={liveProfitPushSendDisabled}
                    className={clsx(
                      'inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-lg border px-2 text-[11px] transition-colors',
                      liveProfitPushSendDisabled
                        ? 'cursor-not-allowed border-crypto-border bg-crypto-bg text-gray-500'
                        : 'border-blue-500/30 bg-blue-600/15 text-blue-400 hover:bg-blue-600/25',
                    )}
                  >
                    {liveProfitPushSending ? (
                      <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Send className="h-3.5 w-3.5" />
                    )}
                    {liveProfitPushSending ? '发送中' : '立即推送'}
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-crypto-border bg-crypto-bg/70">
            <div className="border-b border-crypto-border p-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Bell className="w-4 h-4 text-yellow-400" />
                <h3 className="text-sm font-semibold text-white">告警配置</h3>
              </div>
              <button onClick={() => setShowCreateAlert(true)}
                className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded-lg transition-colors">
                <Plus className="w-3 h-3" />添加
              </button>
            </div>
            <div className="max-h-[260px] overflow-y-auto p-4">
              {alerts.length > 0 ? (
                <div className="space-y-2">
                  {alerts.map(alert => (
                    <div key={alert.id} className="flex items-center justify-between py-3 px-3 bg-crypto-card rounded-xl">
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-white font-medium truncate">{alert.name}</div>
                        <div className="text-[11px] text-gray-500 mt-0.5">
                          {alertDescription(alert)}
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0 ml-3">
                        <button onClick={() => toggleAlert(alert.id, alert.enabled)}
                          className={clsx('p-1 rounded transition-colors', alert.enabled ? 'text-green-400 hover:bg-green-500/10' : 'text-gray-500 hover:bg-gray-500/10')}>
                          {alert.enabled ? <ToggleRight className="w-5 h-5" /> : <ToggleLeft className="w-5 h-5" />}
                        </button>
                        <button onClick={() => setAlertToDelete({ id: alert.id, name: alert.name })} className="p-1 text-red-400 hover:bg-red-500/10 rounded transition-colors">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-8">
                  <Bell className="w-10 h-10 text-gray-700 mx-auto mb-3" />
                  <p className="text-gray-500 text-sm">暂无告警配置</p>
                  <p className="text-gray-600 text-xs mt-1">支持价格、资金费率、策略收益和爆仓前告警</p>
                </div>
              )}
            </div>
          </div>
          </div>
        )}
      </div>

      <div className="monitorRuntimeGrid grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* ====== 运行中的策略 ====== */}
        <div className="bg-crypto-card border border-crypto-border rounded-xl">
          <div className="p-4 border-b border-crypto-border flex items-center gap-2">
            <Activity className="w-4 h-4 text-green-400" />
            <h2 className="text-sm font-semibold text-white">模拟盘监控</h2>
            <div className="ml-auto flex shrink-0 items-center gap-2">
              <div className="flex items-center gap-1.5 text-[10px]">
                <button
                  type="button"
                  onClick={() => setRunningStrategyAssetFilter('all')}
                  aria-pressed={runningStrategyAssetFilter === 'all'}
                  className={clsx(
                    'rounded-md border px-2 py-1 font-medium transition-colors',
                    runningStrategyAssetFilter === 'all'
                      ? SELECTED_SEGMENT_CLASS
                      : 'border-crypto-border bg-transparent text-gray-500 hover:border-gray-500/60 hover:text-gray-300',
                  )}
                >
                  全部 {runningStrategyAssetCounts.total}
                </button>
                <button
                  type="button"
                  onClick={() => setRunningStrategyAssetFilter('spot')}
                  aria-pressed={runningStrategyAssetFilter === 'spot'}
                  className={clsx(
                    'rounded-md border px-2 py-1 font-medium transition-colors',
                    runningStrategyAssetFilter === 'spot'
                      ? SELECTED_SEGMENT_CLASS
                      : 'border-emerald-500/20 bg-emerald-500/5 text-emerald-400/70 hover:bg-emerald-500/10 hover:text-emerald-300',
                  )}
                >
                  现货 {runningStrategyAssetCounts.spot}
                </button>
                <button
                  type="button"
                  onClick={() => setRunningStrategyAssetFilter('contract')}
                  aria-pressed={runningStrategyAssetFilter === 'contract'}
                  className={clsx(
                    'rounded-md border px-2 py-1 font-medium transition-colors',
                    runningStrategyAssetFilter === 'contract'
                      ? SELECTED_SEGMENT_CLASS
                      : 'border-blue-500/20 bg-blue-500/5 text-blue-400/70 hover:bg-blue-500/10 hover:text-blue-300',
                  )}
                >
                  合约 {runningStrategyAssetCounts.contract}
                </button>
              </div>
              <button
                type="button"
                onClick={() => navigate('/live')}
                className="inline-flex items-center gap-1 rounded-lg border border-blue-500/30 bg-blue-600/15 px-3 py-1.5 text-xs text-blue-300 transition-colors hover:bg-blue-600/25"
              >
                模拟工作台
                <ChevronRight className="h-3 w-3" />
              </button>
            </div>
          </div>
          <div className="p-4">
            {visibleRunningStrategies.length > 0 ? (
              <div className="space-y-3">
                {visibleRunningStrategies.map((s, index) => {
                  const symbols = s.symbols || [];
                  const visibleSymbols = symbols.slice(0, 4);
                  const hiddenSymbolCount = Math.max(0, symbols.length - visibleSymbols.length);
                  const isAiAutonomous = isAiAutonomousRunningStrategy(s);
                  const strategyId = s.strategyId ?? `missing-${index}`;
                  const strategyName = s.name || `策略 ${strategyId}`;
                  const returnPct = finiteNumber(s.returnPct);
                  const pnl = finiteNumber(s.pnl);
                  return (
                  <div key={strategyId} className="relative bg-crypto-bg rounded-xl p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                        <span className="min-w-0 truncate text-sm text-white font-medium">{strategyName}</span>
                        {isAiAutonomous && (
                          <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-yellow-500/30 bg-yellow-500/15 px-2 py-0.5 text-[10px] font-bold text-yellow-300">
                            <Zap className="h-3 w-3" />
                            AI自主
                          </span>
                        )}
                        <span className={clsx('text-[10px] px-1.5 py-0.5 rounded',
                          returnPct >= 0 ? 'bg-up text-up' : 'bg-down text-down'
                        )}>
                          {formatSignedPercent(returnPct)}
                        </span>
                      </div>
                      <span className={clsx('shrink-0 text-sm font-bold', pnl >= 0 ? 'text-up' : 'text-down')}>
                        {formatSignedUsd(pnl)}
                      </span>
                    </div>
                    <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                      <div>
                        <span className="text-gray-500">账户总额</span>
                        <div className="text-white font-medium">{formatUsd(s.equity)}</div>
                      </div>
                      <div>
                        <span className="text-gray-500">可用余额</span>
                        <div className="text-white font-medium">{formatUsd(s.balance)}</div>
                      </div>
                      <div>
                        <span className="text-gray-500">浮动盈亏</span>
                        <div className={clsx('font-medium', finiteNumber(s.unrealizedPnl) >= 0 ? 'text-up' : 'text-down')}>
                          {formatSignedUsd(s.unrealizedPnl)}
                        </div>
                      </div>
                    </div>
                    {s.positions && Object.keys(s.positions).length > 0 && (
                      <div className="mt-2 border-t border-crypto-border pt-2">
                        {Object.entries(s.positions).map(([sym, pos]) => (
                          <div key={sym} className="flex items-center justify-between text-[11px] py-0.5">
                            <span className="text-gray-400">{sym}</span>
                            <span className="text-gray-300">
                              {finiteNumber(pos.size).toFixed(6)} @ {finiteNumber(pos.entryPrice).toFixed(2)}
                            </span>
                            <span className={clsx('font-medium', finiteNumber(pos.unrealizedPnl) >= 0 ? 'text-up' : 'text-down')}>
                              {formatSignedUsd(pos.unrealizedPnl)}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                    <div
                      className="mt-2 flex min-w-0 items-center gap-1.5 text-[10px] text-gray-500"
                      title={symbols.join(', ')}
                    >
                      <div className="min-w-0 flex flex-1 items-center gap-1.5 overflow-hidden">
                        {visibleSymbols.map(sym => (
                          <span
                            key={sym}
                            className="max-w-[74px] truncate rounded border border-crypto-border px-1.5 py-0.5"
                          >
                            {sym}
                          </span>
                        ))}
                        {hiddenSymbolCount > 0 && (
                          <span className="shrink-0 rounded border border-crypto-border px-1.5 py-0.5">
                            +{hiddenSymbolCount}
                          </span>
                        )}
                      </div>
                      <span className="shrink-0">{finiteNumber(s.totalTrades)} 笔交易</span>
                      <button
                        type="button"
                        aria-label="进入策略监控详情"
                        title="进入策略监控详情"
                        onClick={() => navigate(`/live?strategyId=${encodeURIComponent(String(strategyId))}`)}
                        className="ml-1 inline-flex h-6 shrink-0 items-center gap-0.5 rounded-md border border-blue-500/30 bg-blue-600/15 px-2 text-[10px] font-medium text-blue-300 shadow-inner shadow-blue-950/20 transition-colors hover:border-blue-400/50 hover:bg-blue-600/25 hover:text-blue-200"
                      >
                        详情
                        <ChevronRight className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                  );
                })}
              </div>
            ) : (
              <div className="text-center py-12">
                <Activity className="w-12 h-12 text-gray-700 mx-auto mb-3" />
                <p className="text-gray-500 text-sm">
                  {runningStrategies.length > 0
                    ? `暂无${runningStrategyFilterLabel}运行策略`
                    : '暂无运行中的策略'}
                </p>
                <p className="text-gray-600 text-xs mt-1">
                  {runningStrategies.length > 0
                    ? '可切换上方筛选查看其他资产类型'
                    : '前往"模拟/实盘"页面启动策略'}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* ====== 实盘监控 ====== */}
        <div className="bg-crypto-card border border-crypto-border rounded-xl">
          <div className="p-4 border-b border-crypto-border flex items-center gap-2">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-blue-400" />
              <h2 className="text-sm font-semibold text-white">实盘监控</h2>
            </div>
            <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
              <LiveMonitorAccountTabs
                ariaLabel="实盘监控账户切换"
                accounts={configuredLiveMonitorAccounts}
                value={liveMonitorAccount?.accountId || ''}
                onChange={selectLiveMonitorAccount}
                className="min-w-[252px]"
              />
              <div
                aria-label="实盘监控策略状态筛选"
                className="flex items-center rounded-lg border border-crypto-border bg-crypto-bg/70 p-0.5 text-[10px]"
              >
                {liveMonitorStatusFilters.map(item => {
                  const active = liveMonitorStatusFilter === item.key;
                  return (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => setLiveMonitorStatusFilter(item.key)}
                      aria-pressed={active}
                      className={clsx(
                        'inline-flex h-7 items-center gap-1.5 rounded-md px-2 font-semibold transition-colors',
                        liveMonitorStatusFilterButtonClass(item.key, active),
                      )}
                    >
                      {item.label}
                      <span
                        className={clsx(
                          'inline-flex min-w-[18px] items-center justify-center rounded-full px-1.5 py-0.5 leading-none',
                          liveMonitorStatusFilterCountClass(item.key, active),
                        )}
                      >
                        {liveMonitorStatusCounts[item.key]}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className="flex items-center gap-1.5 text-[10px]">
                <button
                  type="button"
                  onClick={() => setLiveStrategyAssetFilter('all')}
                  aria-pressed={liveStrategyAssetFilter === 'all'}
                  className={clsx(
                    'rounded-md border px-2 py-1 font-medium transition-colors',
                    liveStrategyAssetFilter === 'all'
                      ? SELECTED_SEGMENT_CLASS
                      : 'border-crypto-border bg-transparent text-gray-500 hover:border-gray-500/60 hover:text-gray-300',
                  )}
                >
                  全部 {liveStrategyAssetCounts.total}
                </button>
                <button
                  type="button"
                  onClick={() => setLiveStrategyAssetFilter('spot')}
                  aria-pressed={liveStrategyAssetFilter === 'spot'}
                  className={clsx(
                    'rounded-md border px-2 py-1 font-medium transition-colors',
                    liveStrategyAssetFilter === 'spot'
                      ? SELECTED_SEGMENT_CLASS
                      : 'border-emerald-500/20 bg-emerald-500/5 text-emerald-400/70 hover:bg-emerald-500/10 hover:text-emerald-300',
                  )}
                >
                  现货 {liveStrategyAssetCounts.spot}
                </button>
                <button
                  type="button"
                  onClick={() => setLiveStrategyAssetFilter('contract')}
                  aria-pressed={liveStrategyAssetFilter === 'contract'}
                  className={clsx(
                    'rounded-md border px-2 py-1 font-medium transition-colors',
                    liveStrategyAssetFilter === 'contract'
                      ? SELECTED_SEGMENT_CLASS
                      : 'border-blue-500/20 bg-blue-500/5 text-blue-400/70 hover:bg-blue-500/10 hover:text-blue-300',
                  )}
                >
                  合约 {liveStrategyAssetCounts.contract}
                </button>
              </div>
              <button
                type="button"
                onClick={() => navigate('/live-real')}
                className="inline-flex items-center gap-1 rounded-lg border border-blue-500/30 bg-blue-600/15 px-3 py-1.5 text-xs text-blue-300 transition-colors hover:bg-blue-600/25"
              >
                实盘工作台
                <ChevronRight className="h-3 w-3" />
              </button>
            </div>
          </div>
          <div className="p-4">
            {liveMonitorError && (
              <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                {liveMonitorError}
              </div>
            )}
            {visibleLiveStrategies.length > 0 ? (
              <div className="space-y-2">
                {visibleLiveStrategies.map(strategy => (
                  <LiveStrategyMonitorCard
                    key={strategy.strategyId}
                    strategy={strategy}
                    orders={liveOrders}
                    positions={liveContractPositions}
                    onOpen={() => navigate(`/live-real?strategy_id=${encodeURIComponent(String(strategy.strategyId))}`)}
                  />
                ))}
              </div>
            ) : (
              <div className="text-center py-12">
                <Activity className="w-12 h-12 text-gray-700 mx-auto mb-3" />
                <p className="text-gray-500 text-sm">
                  {livePanelStrategies.length > 0
                    ? `暂无${liveMonitorEmptyFilterLabel}实盘策略`
                    : '暂无实盘部署策略'}
                </p>
                <p className="text-gray-600 text-xs mt-1">
                  {livePanelStrategies.length > 0
                    ? '可切换上方状态或资产类型筛选查看其他实盘策略'
                    : '实盘面板出现当前账户部署订阅后会在这里显示账户、持仓和订单状态'}
                </p>
              </div>
            )}
          </div>
        </div>

      </div>

      {/* 创建告警对话框 */}
      {showCreateAlert && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-crypto-card border border-crypto-border rounded-xl w-full max-w-2xl">
            <div className="p-4 border-b border-crypto-border flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">新建告警</h3>
              <button onClick={() => setShowCreateAlert(false)} className="text-gray-400 hover:text-white"><X className="w-4 h-4" /></button>
            </div>
            <div className="p-4 space-y-3">
              <div className="rounded-xl border border-crypto-border bg-crypto-bg/40 p-3">
                <div className="mb-3 flex items-end justify-between gap-3">
                  <div>
                    <label className="block text-xs text-gray-400">告警模板</label>
                    <div className="mt-1 text-[10px] text-gray-500">只选择告警场景，阈值在下方自定义</div>
                  </div>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {ALERT_TEMPLATES.map(template => {
                    const active =
                      alertForm.type === template.type &&
                      (isStrategyScopedAlertType(template.type) || alertForm.symbol === template.symbol);
                    return (
                      <button
                        key={template.id}
                        type="button"
                        onClick={() => applyAlertTemplate(template)}
                        className={clsx(
                          'min-h-[68px] rounded-lg border px-3 py-2.5 text-left transition-colors',
                          template.className,
                          active && 'ring-1 ring-white/40 bg-opacity-20',
                        )}
                      >
                        <div className="text-xs font-semibold">{template.label}</div>
                        <div className="mt-1.5 text-[10px] leading-relaxed text-gray-400">{template.desc}</div>
                      </button>
                    );
                  })}
                </div>
              </div>
              <div><label className="block text-xs text-gray-400 mb-1">告警名称</label>
                <input type="text" value={alertForm.name} onChange={e => setAlertForm({ ...alertForm, name: e.target.value })} placeholder="输入易识别的告警名称"
                  className="w-full bg-crypto-bg border border-crypto-border rounded-lg px-3 py-2 text-sm text-white" /></div>
              <div><label className="block text-xs text-gray-400 mb-1">告警类型</label>
                <CryptoSelect value={alertForm.type} onChange={e => {
                  const nextType = e.target.value;
                  if (nextType === 'strategy_return_below') {
                    setAlertForm({
                      ...alertForm,
                      type: nextType,
                      threshold: -5,
                      strategyId: selectedAlertStrategyId,
                      cooldownMinutes: alertForm.cooldownMinutes || 60,
                      name: alertForm.name || '策略收益低于阈值',
                    });
                  } else if (nextType === 'strategy_liquidation_risk') {
                    setAlertForm({
                      ...alertForm,
                      type: nextType,
                      threshold: 10,
                      strategyId: selectedAlertStrategyId,
                      cooldownMinutes: alertForm.cooldownMinutes || 60,
                      name: alertForm.name || '策略爆仓前告警',
                    });
                  } else {
                    setAlertForm({
                      ...alertForm,
                      type: nextType,
                      threshold: nextType.startsWith('funding') ? 0.0001 : 100000,
                      name: ['策略收益低于阈值', '策略爆仓前告警'].includes(alertForm.name) ? '' : alertForm.name,
                    });
                  }
                }}>
                  <option value="price_above">价格高于</option><option value="price_below">价格低于</option>
                  <option value="price_change">价格变动%</option><option value="funding_above">费率高于</option>
                  <option value="funding_below">费率低于</option>
                  <option value="strategy_return_below">策略收益低于</option>
                  <option value="strategy_liquidation_risk">爆仓前告警</option>
                </CryptoSelect></div>
              {isStrategyAlertForm ? (
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">策略</label>
                    <CryptoSelect
                      value={selectedAlertStrategyId}
                      onChange={e => setAlertForm({ ...alertForm, strategyId: Number(e.target.value) })}
                    >
                      {runningStrategies.length === 0 && <option value={0}>暂无运行中策略</option>}
                      {runningStrategies.map((strategy, index) => {
                        const strategyId = finiteNumber(strategy.strategyId, index + 1);
                        return (
                        <option key={strategyId} value={strategyId}>
                          #{strategyId} {strategy.name || `策略 ${strategyId}`}
                        </option>
                        );
                      })}
                    </CryptoSelect>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs text-gray-400 mb-1">{strategyThresholdLabel}</label>
                      <input
                        type="number"
                        step={0.1}
                        min={alertForm.type === 'strategy_liquidation_risk' ? 0 : undefined}
                        value={alertForm.threshold}
                        onChange={e => setAlertForm({ ...alertForm, threshold: Number(e.target.value) })}
                        placeholder={strategyThresholdPlaceholder}
                        className="w-full bg-crypto-bg border border-crypto-border rounded-lg px-3 py-2 text-sm text-white"
                      />
                      <div className="mt-1 text-[10px] text-gray-500">{strategyThresholdHint}</div>
                    </div>
                    <div>
                      <label className="block text-xs text-gray-400 mb-1">冷却时间 (分钟)</label>
                      <input
                        type="number"
                        min={1}
                        value={alertForm.cooldownMinutes}
                        onChange={e => setAlertForm({ ...alertForm, cooldownMinutes: Number(e.target.value) })}
                        className="w-full bg-crypto-bg border border-crypto-border rounded-lg px-3 py-2 text-sm text-white"
                      />
                    </div>
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-2">
                  <div><label className="block text-xs text-gray-400 mb-1">交易对</label>
                    <input type="text" value={alertForm.symbol} onChange={e => setAlertForm({ ...alertForm, symbol: e.target.value })}
                      className="w-full bg-crypto-bg border border-crypto-border rounded-lg px-3 py-2 text-sm text-white" /></div>
                  <div><label className="block text-xs text-gray-400 mb-1">阈值</label>
                    <input type="number" value={alertForm.threshold} onChange={e => setAlertForm({ ...alertForm, threshold: Number(e.target.value) })}
                      className="w-full bg-crypto-bg border border-crypto-border rounded-lg px-3 py-2 text-sm text-white" /></div>
                </div>
              )}
            </div>
            <div className="p-4 border-t border-crypto-border flex justify-end gap-2">
              <button onClick={() => setShowCreateAlert(false)} className="px-4 py-2 text-sm text-gray-400 hover:text-white">取消</button>
              <button
                onClick={createAlert}
                disabled={isStrategyAlertForm && selectedAlertStrategyId <= 0}
                className="px-5 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:text-gray-400 text-white text-sm rounded-lg"
              >
                创建
              </button>
            </div>
          </div>
        </div>
      )}

      <ThemeDialog
        open={alertToDelete !== null}
        variant="confirm"
        title="删除告警"
        content={
          alertToDelete
            ? `确定删除告警「${alertToDelete.name}」吗？此操作不可恢复。`
            : ''
        }
        tone="warning"
        confirmText="删除"
        onCancel={() => setAlertToDelete(null)}
        onConfirm={() => void runDeleteAlert()}
      />
    </div>
  );
}

// ============================================
// 实盘策略监控卡
// ============================================
function LiveStrategyMonitorCard({
  strategy,
  positions,
  orders,
  onOpen,
}: {
  strategy: LiveExecutionStrategy;
  positions: LiveExecutionPosition[];
  orders: LiveExecutionOrder[];
  onOpen: () => void;
}) {
  const symbols = strategy.tradeSymbols?.length ? strategy.tradeSymbols : strategy.symbols || [];
  const visibleSymbols = symbols.slice(0, 4);
  const hiddenSymbolCount = Math.max(0, symbols.length - visibleSymbols.length);
  const strategyOrders = orders.filter(order => order.sourceStrategyId === strategy.strategyId);
  const displayOrders = strategyOrders.length > 0 ? strategyOrders : orders.slice(0, 3);
  const pnl = finiteNumber(strategy.totalPnl, 0);
  const returnPct = finiteNumber(strategy.returnPct, 0);
  const status = liveStrategyStatusLabel(strategy);
  const accountCount = new Set([
    ...(strategy.accountIds || []),
    ...(strategy.accountBindings || []).map(binding => binding.accountId),
    strategy.accountId,
  ].filter(Boolean)).size;
  const relatedPositions = positions.filter(position => {
    const symbol = String(position.symbol || '').toUpperCase();
    return symbols.some(item => symbol === item.toUpperCase() || symbol.includes(item.split('/')[0]?.toUpperCase() || ''));
  });
  const displayPositions = relatedPositions;

  return (
    <div className="relative rounded-xl bg-crypto-bg p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <span className={clsx('h-2 w-2 shrink-0 rounded-full', status === '运行中' ? 'animate-pulse bg-green-400' : 'bg-gray-500')} />
            <span className="min-w-0 truncate text-sm font-medium text-white">{strategy.strategyName}</span>
          </div>
          <div className="mt-1 text-[10px] text-gray-500">
            {accountCount > 0 ? `${accountCount} 个账户` : '未绑定账户'} · {strategy.marketType || 'live'} · {strategy.exchange || 'okx'}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className={clsx('text-sm font-bold', pnl >= 0 ? 'text-up' : 'text-down')}>{formatSignedUsd(pnl)}</div>
          <div className={clsx('text-[10px]', returnPct >= 0 ? 'text-up' : 'text-down')}>{formatSignedPercent(returnPct)}</div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
        <div>
          <span className="text-gray-500">持仓数</span>
          <div className="text-white font-medium">{displayPositions.length}</div>
        </div>
        <div>
          <span className="text-gray-500">订单数</span>
          <div className="text-white font-medium">{strategyOrders.length || displayOrders.length}</div>
        </div>
        <div>
          <span className="text-gray-500">持仓名义</span>
          <div className="text-white font-medium">
            {formatUsd(displayPositions.reduce((sum, position) => sum + livePositionNotionalUsdt(position), 0), 0)}
          </div>
        </div>
      </div>

      {displayPositions.length > 0 && (
        <div className="mt-2 border-t border-crypto-border pt-2">
          {displayPositions.slice(0, 2).map((position, index) => (
            <div key={`${position.symbol || position.currency || 'position'}-${index}`} className="flex items-center justify-between gap-2 py-0.5 text-[11px]">
              <span className="min-w-0 truncate text-gray-400">{position.symbol || position.currency || '--'}</span>
              <span className="shrink-0 text-gray-300">{livePositionSize(position).toFixed(4)} @ {finiteNumber(position.entryPrice).toFixed(2)}</span>
              <span className={clsx('shrink-0 font-medium', finiteNumber(position.unrealizedPnl) >= 0 ? 'text-up' : 'text-down')}>
                {formatSignedUsd(position.unrealizedPnl)}
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="mt-2 flex min-w-0 items-center gap-1.5 text-[10px] text-gray-500" title={symbols.join(', ')}>
        <div className="min-w-0 flex flex-1 items-center gap-1.5 overflow-hidden">
          {visibleSymbols.map(symbol => (
            <span key={symbol} className="max-w-[74px] truncate rounded border border-crypto-border px-1.5 py-0.5">
              {symbol}
            </span>
          ))}
          {hiddenSymbolCount > 0 && (
            <span className="shrink-0 rounded border border-crypto-border px-1.5 py-0.5">+{hiddenSymbolCount}</span>
          )}
        </div>
        <button
          type="button"
          aria-label="进入实盘监控详情"
          onClick={onOpen}
          className="ml-1 inline-flex h-6 shrink-0 items-center gap-0.5 rounded-md border border-blue-500/30 bg-blue-600/15 px-2 text-[10px] font-medium text-blue-300 shadow-inner shadow-blue-950/20 transition-colors hover:border-blue-400/50 hover:bg-blue-600/25 hover:text-blue-200"
        >
          详情
          <ChevronRight className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
}

// ============================================
// 情绪指标卡片
// ============================================
function SentimentCard({ label, value, icon, color, sub }: {
  label: string; value: string; icon: React.ReactNode; color: 'green' | 'red' | 'blue' | 'yellow' | 'gray'; sub: string;
}) {
  const colorMap = {
    green: { bg: 'bg-green-500/10', border: 'border-green-500/20', text: 'text-green-400', glow: 'shadow-green-950/20' },
    red: { bg: 'bg-red-500/10', border: 'border-red-500/20', text: 'text-red-400', glow: 'shadow-red-950/20' },
    blue: { bg: 'bg-blue-500/10', border: 'border-blue-500/20', text: 'text-blue-400', glow: 'shadow-blue-950/20' },
    yellow: { bg: 'bg-yellow-500/10', border: 'border-yellow-500/20', text: 'text-yellow-400', glow: 'shadow-yellow-950/20' },
    gray: { bg: 'bg-gray-500/10', border: 'border-gray-500/20', text: 'text-gray-400', glow: 'shadow-gray-950/20' },
  };
  const c = colorMap[color];
  return (
    <div className={clsx('rounded-xl border p-4 shadow-inner', c.bg, c.border, c.glow)}>
      <div className="mb-2 flex min-w-0 items-center gap-1.5">
        <span className={clsx('shrink-0', c.text)}>{icon}</span>
        <span className="min-w-0 truncate text-[11px] font-semibold text-gray-300/90">{label}</span>
      </div>
      <div className={clsx('min-w-0 truncate font-mono text-xl font-bold leading-tight tabular-nums', c.text)}>{value}</div>
      <div className="mt-2 border-t border-white/5 pt-2 text-[11px] font-medium leading-snug text-gray-300/75">{sub}</div>
    </div>
  );
}

function evidenceTime(value: unknown): string {
  if (!value) return '--';
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value).slice(0, 19) : date.toLocaleString('zh-CN', { hour12: false });
}

function evidenceTone(value: unknown): 'green' | 'red' | 'blue' | 'yellow' | 'gray' {
  const normalized = String(value || '').toLowerCase();
  if (['healthy', 'fresh', 'sealed', 'delivered', 'success'].includes(normalized)) return 'green';
  if (['critical', 'failed', 'error', 'missing'].includes(normalized)) return 'red';
  if (['warning', 'stale', 'partial', 'pending'].includes(normalized)) return 'yellow';
  return 'gray';
}

export default function Monitor() {
  const [summary, setSummary] = useState<MonitorSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [configOpen, setConfigOpen] = useState(false);
  const loadInFlight = useRef(false);

  const load = async () => {
    if (loadInFlight.current) return;
    loadInFlight.current = true;
    setLoading(true);
    try {
      setSummary(await monitorCurrentApi.summary('audit'));
      setError('');
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError?.message || '监控证据读取失败');
    } finally {
      loadInFlight.current = false;
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const running = summary?.strategy_health.filter((item) => item.lifecycle_status === 'running').length ?? 0;
  const unhealthy = summary?.strategy_health.filter((item) => ['stale', 'missing', 'failed', 'error'].includes(item.health_state)).length ?? 0;
  const delivered = summary?.notifications.reduce((total, item) => total + (String(item.status) === 'delivered' ? Number(item.count || 0) : 0), 0) ?? 0;
  const datasetStatus = summary?.data?.dataset?.status || 'missing';
  const marketStatus = summary?.data?.market?.status || 'missing';

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-crypto-bg p-6">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Eye className="h-6 w-6 text-blue-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">监控中心</h1>
            <p className="mt-1 text-xs text-gray-500">Paper 生命周期、运行健康、数据证据、风险与通知</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-xl border border-crypto-border bg-crypto-card px-3 py-2 text-xs text-gray-400 transition-colors hover:text-white disabled:opacity-50"
        >
          <RefreshCw className={clsx('h-3.5 w-3.5', loading && 'animate-spin')} />刷新证据
        </button>
      </div>

      {error && <div className="mb-4 rounded-xl border border-red-500/25 bg-red-500/10 p-3 text-xs text-red-200">{error}</div>}

      <div className="monitorOverviewGrid mb-6 grid grid-cols-1 gap-4 2xl:grid-cols-2">
        <section className="monitor-overview-panel rounded-xl border border-blue-500/15 bg-crypto-card p-4">
          <div className="mb-4">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
              <Activity className="h-4 w-4 text-green-400" />模拟盘总览
            </h2>
            <p className="mt-1 text-[11px] text-gray-500">生命周期与健康分离；运行状态不代表账本健康</p>
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <SentimentCard label="Paper 实例" value={String(summary?.strategy_health.length ?? 0)} icon={<Activity className="h-4 w-4" />} color="blue" sub="PostgreSQL 审计范围" />
            <SentimentCard label="运行中" value={String(running)} icon={<HeartPulse className="h-4 w-4" />} color={running > 0 ? 'green' : 'gray'} sub="仅生命周期 running" />
            <SentimentCard label="健康异常" value={String(unhealthy)} icon={<ShieldAlert className="h-4 w-4" />} color={unhealthy > 0 ? 'yellow' : 'green'} sub="stale / missing / failed" />
            <SentimentCard label="活动告警" value={String(summary?.active_alerts.length ?? 0)} icon={<Bell className="h-4 w-4" />} color={(summary?.active_alerts.length ?? 0) > 0 ? 'yellow' : 'green'} sub="告警只记录，不创建订单" />
          </div>
        </section>

        <section className="monitor-overview-panel rounded-xl border border-blue-500/15 bg-crypto-card p-4">
          <div className="mb-4">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
              <ServerCog className="h-4 w-4 text-blue-400" />运行证据总览
            </h2>
            <p className="mt-1 text-[11px] text-gray-500">服务、封存数据和通知投递来自同一监控快照</p>
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <SentimentCard label="整体状态" value={summary?.overall_status || '--'} icon={<HeartPulse className="h-4 w-4" />} color={evidenceTone(summary?.overall_status)} sub="当前监控聚合结论" />
            <SentimentCard label="服务证据" value={String(summary?.services.length ?? 0)} icon={<ServerCog className="h-4 w-4" />} color="blue" sub="进程与依赖健康" />
            <SentimentCard label="Dataset" value={String(datasetStatus)} icon={<Database className="h-4 w-4" />} color={evidenceTone(datasetStatus)} sub="封存研究输入" />
            <SentimentCard label="已投递通知" value={String(delivered)} icon={<Send className="h-4 w-4" />} color={delivered > 0 ? 'green' : 'gray'} sub="按真实 delivery 状态统计" />
          </div>
        </section>
      </div>

      <div className="monitorConfigPanel mb-6 rounded-xl border border-crypto-border bg-crypto-card">
        <button
          type="button"
          onClick={() => setConfigOpen((open) => !open)}
          aria-expanded={configOpen}
          className="flex w-full items-center justify-between gap-3 p-4 text-left transition-colors hover:bg-white/[0.02]"
        >
          <div className="flex min-w-0 items-center gap-2">
            <Bell className="h-4 w-4 text-blue-400" />
            <h2 className="text-sm font-semibold text-white">监控配置</h2>
            <span className="truncate text-xs text-gray-500">当前只读展示告警与通知证据，不自动修改运行时</span>
          </div>
          <ChevronRight className={clsx('h-4 w-4 text-gray-500 transition-transform', configOpen && 'rotate-90')} />
        </button>
        {configOpen && (
          <div className="grid gap-4 border-t border-crypto-border p-4 xl:grid-cols-2">
            <section className="rounded-xl border border-crypto-border bg-crypto-bg/60 p-4">
              <h3 className="mb-3 text-sm font-semibold text-white">风险告警</h3>
              <div className="max-h-64 space-y-2 overflow-y-auto">
                {(summary?.active_alerts || []).map((item) => (
                  <div key={item.id} className="rounded-lg border border-crypto-border bg-crypto-card p-3">
                    <div className="flex justify-between gap-3 text-xs"><span className="text-gray-200">{item.title}</span><span className="text-amber-300">{item.severity}</span></div>
                    <div className="mt-1 text-[10px] text-gray-500">{item.message || item.status}</div>
                  </div>
                ))}
                {!summary?.active_alerts.length && <div className="py-6 text-center text-xs text-gray-500">当前没有活动告警</div>}
              </div>
            </section>
            <section className="rounded-xl border border-crypto-border bg-crypto-bg/60 p-4">
              <h3 className="mb-3 text-sm font-semibold text-white">通知投递</h3>
              <div className="space-y-2">
                {(summary?.notifications || []).map((item, index) => (
                  <div key={`${item.status}-${index}`} className="flex items-center justify-between rounded-lg border border-crypto-border bg-crypto-card px-3 py-2 text-xs">
                    <span className="text-gray-300">{item.status}</span><span className="font-mono text-gray-400">{item.count ?? 0}</span>
                  </div>
                ))}
                {!summary?.notifications.length && <div className="py-6 text-center text-xs text-gray-500">通知证据为空</div>}
              </div>
            </section>
          </div>
        )}
      </div>

      <div className="monitorRuntimeGrid grid grid-cols-1 gap-6 xl:grid-cols-[1.35fr_.65fr]">
        <section className="rounded-xl border border-crypto-border bg-crypto-card">
          <div className="flex items-center justify-between border-b border-crypto-border p-4">
            <div className="flex items-center gap-2"><Activity className="h-4 w-4 text-green-400" /><h2 className="text-sm font-semibold text-white">模拟盘监控</h2></div>
            <span className="text-[10px] text-gray-500">生命周期与健康分离</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-xs">
              <thead className="border-b border-crypto-border text-[10px] text-gray-500"><tr>{['实例','生命周期','健康','心跳年龄','最近周期','权益日期','账本差异'].map((label) => <th key={label} className="px-3 py-2 font-medium">{label}</th>)}</tr></thead>
              <tbody className="divide-y divide-crypto-border/60">
                {(summary?.strategy_health || []).map((item) => (
                  <tr key={item.id} data-paper-instance-id={item.id}>
                    <td className="px-3 py-2.5"><div className="max-w-64 truncate text-gray-200">{item.name}</div><div className="font-mono text-[10px] text-gray-600">{item.id}</div></td>
                    <td className="px-3 py-2.5 text-gray-300">{item.lifecycle_status}</td>
                    <td className={clsx('px-3 py-2.5', evidenceTone(item.health_state) === 'green' ? 'text-green-300' : evidenceTone(item.health_state) === 'red' ? 'text-red-300' : 'text-amber-300')}>{item.health_state}</td>
                    <td className="px-3 py-2.5 font-mono text-gray-500">{item.heartbeat_age_seconds ?? '--'}</td>
                    <td className="px-3 py-2.5 text-gray-500">{evidenceTime(item.latest_cycle_finished_at)}</td>
                    <td className="px-3 py-2.5 text-gray-500">{String(item.latest_equity_trade_date || '--').slice(0, 10)}</td>
                    <td className="px-3 py-2.5 font-mono text-gray-400">{item.latest_cycle_ledger_difference ?? '--'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rounded-xl border border-crypto-border bg-crypto-card">
          <div className="flex items-center gap-2 border-b border-crypto-border p-4"><ServerCog className="h-4 w-4 text-blue-400" /><h2 className="text-sm font-semibold text-white">服务与数据健康</h2></div>
          <div className="space-y-2 p-4">
            {(summary?.services || []).map((service) => (
              <div key={String(service.service_code)} className="rounded-lg border border-crypto-border bg-crypto-bg/60 p-3">
                <div className="flex justify-between gap-3 text-xs"><span className="text-gray-200">{service.service_code}</span><span className={evidenceTone(service.status) === 'green' ? 'text-green-300' : 'text-amber-300'}>{service.status} · {service.freshness}</span></div>
                <div className="mt-1 text-[10px] text-gray-600">{evidenceTime(service.observed_at)} · {service.latency_ms ?? '--'}ms</div>
              </div>
            ))}
            <div className="grid grid-cols-2 gap-2">
              {[['Dataset', datasetStatus], ['市场证据', marketStatus]].map(([label, status]) => (
                <div key={label} className="rounded-lg border border-crypto-border bg-crypto-bg/60 p-3"><div className="text-[10px] text-gray-500">{label}</div><div className="mt-1 text-xs text-gray-200">{status}</div></div>
              ))}
            </div>
          </div>
        </section>
      </div>

      <div className="mt-6"><SchedulerPanel /></div>
      <div className="mt-4 text-[10px] text-gray-600">{summary?.source_label || 'PostgreSQL runtime evidence'} · 证据更新时间 {evidenceTime(summary?.source_updated_at)}</div>
    </div>
  );
}
