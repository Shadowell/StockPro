import { Fragment, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  CheckCircle2,
  ChevronRight,
  Clock,
  Eye,
  Info,
  Loader2,
  Lock,
  Plus,
  Rocket,
  Search,
  Settings2,
  ShieldCheck,
  Wallet,
  XCircle,
  Zap,
} from 'lucide-react';
import clsx from 'clsx';
import ThemeDialog from '../../components/ThemeDialog';
import { formatTimeframeLabel } from '../../utils/timeframe';
import { SELECTED_SEGMENT_BORDER_CLASS } from '../../utils/selectionStyles';
import type { Balance, CreateStep, StrategyInfo, TradeMode } from './types';
import {
  DEFAULT_LIVE_CONFIG,
  formatStrategySymbolScope,
  getStrategySymbols,
  getStrategyTradeSymbols,
  isAiAutonomousStrategy,
  isSuperPnLUniverseStrategy,
  paperQuickVerifyDaysBack,
} from './constants';

const STRATEGY_PARAM_LABELS: Record<string, string> = {
  market_type: '市场类型',
  trade_symbols: '交易子池',
  contract_trade_symbols: '合约子池',
  entry_interval_bars: '开仓间隔',
  hold_bars: '持仓周期',
  max_hold_bars: '最长持仓',
  predict_steps: '预测步数',
  window_size: '模型窗口',
  warmup_bars: '预热K线',
  quote_per_order: '单次名义',
  trade_notional_usdt: '单次名义',
  entry_balance_pct: '余额比例',
  position_pct: '单仓比例',
  max_position_pct: '单仓上限',
  max_total_position: '总仓上限',
  max_total_position_pct: '总仓上限',
  max_total_notional_pct: '总名义上限',
  confidence_threshold: '置信阈值',
  min_predicted_change: '最小预测涨幅',
  threshold_bps: '信号阈值',
  profit_floor_bps: '保本线',
  profit_floor_start_bps: '浮盈保护启动',
  stop_loss_bps: '止损',
  take_profit_bps: '止盈',
  trailing_start_bps: '移动止盈启动',
  trailing_pullback_bps: '移动回撤',
  top_k: 'Top-K',
  max_active_symbols: '最大活跃标的',
  rebalance_interval_bars: '再平衡间隔',
  cooldown_bars: '冷却周期',
  poll_interval_seconds: '扫描间隔',
  min_annualized_rate: '最低年化费率',
  close_annualized_rate: '平仓年化费率',
  leverage: '杠杆',
  max_leverage: '最大杠杆',
  grid_low: '网格下沿',
  grid_high: '网格上沿',
  grid_levels: '网格层数',
  risk_per_trade_pct: '单笔风险',
  max_daily_loss_pct: '日亏损上限',
  max_total_loss_pct: '总亏损上限',
};

const STRATEGY_PARAM_KEYS = Object.keys(STRATEGY_PARAM_LABELS);

function strategyConfig(strategy?: StrategyInfo | null): Record<string, unknown> {
  return strategy?.config && typeof strategy.config === 'object' ? strategy.config : {};
}

function formatParamValue(key: string, value: unknown): string {
  if (Array.isArray(value)) {
    const list = value.map((item) => String(item || '').trim()).filter(Boolean);
    if (list.length === 0) return '—';
    return list.length > 4 ? `${list.slice(0, 4).join(' / ')} 等 ${list.length} 个` : list.join(' / ');
  }
  if (typeof value === 'boolean') return value ? '开启' : '关闭';
  if (typeof value === 'number') {
    if (key.endsWith('_bps') || key.includes('bps')) return `${Number(value.toFixed(2))} bps`;
    if (
      key.endsWith('_pct') ||
      key.endsWith('_position') ||
      key === 'entry_balance_pct' ||
      key === 'position_pct' ||
      key === 'min_annualized_rate' ||
      key === 'close_annualized_rate'
    ) {
      const pct = Math.abs(value) <= 1 ? value * 100 : value;
      return `${Number(pct.toFixed(2))}%`;
    }
    if (key.includes('notional') || key.includes('quote')) return `${Number(value.toFixed(4))} USDT`;
    if (key.includes('leverage')) return `${Number(value.toFixed(2))}x`;
    return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)));
  }
  if (value == null || value === '') return '—';
  return String(value);
}

function strategyParamRows(strategy?: StrategyInfo | null): Array<{
  key: string;
  label: string;
  value: string;
}> {
  const cfg = strategyConfig(strategy);
  return STRATEGY_PARAM_KEYS
    .filter((key) => cfg[key] != null && cfg[key] !== '')
    .map((key) => ({
      key,
      label: STRATEGY_PARAM_LABELS[key],
      value: formatParamValue(key, cfg[key]),
    }))
    .slice(0, 12);
}

function normalizeStrategySearchText(value: unknown): string {
  return String(value ?? '')
    .toLowerCase()
    .replace(/[\s\-_/：:·.,，。()[\]【】]+/g, '');
}

function collectStrategyConfigSearchValues(value: unknown, depth = 0): string[] {
  if (value == null || depth > 2) return [];
  if (Array.isArray(value)) {
    return value.flatMap((item) => collectStrategyConfigSearchValues(item, depth + 1));
  }
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).flatMap(([key, item]) => [
      key,
      ...collectStrategyConfigSearchValues(item, depth + 1),
    ]);
  }
  return [String(value)];
}

function strategySearchHaystack(strategy: StrategyInfo): string {
  const cfg = strategyConfig(strategy);
  const name = strategy.name || '';
  const normalizedName = normalizeStrategySearchText(name);
  const marketType = String(cfg.market_type || cfg.marketType || '').toLowerCase();
  const strategyKey = String(cfg.strategy_key || cfg.strategyKey || '').toLowerCase();
  const assetLabel =
    normalizedName.includes('合约') || marketType === 'swap' || marketType === 'contract'
      ? '合约 contract swap futures perpetual'
      : normalizedName.includes('现货') || marketType === 'spot'
        ? '现货 spot'
        : '';
  const typeLabel = [
    normalizedName.includes('cta') || normalizedName.includes('趋势跟踪') ? 'CTA 趋势 趋势跟踪' : '',
    normalizedName.includes('马丁') || normalizedName.includes('martin') ? '马丁 martingale' : '',
    normalizedName.includes('套利') || strategyKey.includes('arbitrage') ? '套利 arbitrage' : '',
    normalizedName.includes('ai') || strategyKey.includes('ai') ? 'AI 自主' : '',
  ].join(' ');
  const symbols = [
    strategy.symbol,
    ...(strategy.symbols || []),
    ...getStrategySymbols(strategy),
    ...getStrategyTradeSymbols(strategy),
  ];
  const capital = strategy.initialCapital ?? strategy.initial_capital ?? cfg.initial_capital;

  return normalizeStrategySearchText(
    [
      strategy.id,
      name,
      strategy.description,
      strategy.timeframe,
      strategy.suitableFor,
      strategy.status,
      strategy.riskLevel,
      strategy.risk_level,
      assetLabel,
      typeLabel,
      symbols.join(' '),
      capital ? `${capital}U ${capital} USDT` : '',
      ...collectStrategyConfigSearchValues(cfg),
    ].join(' '),
  );
}

function strategyMatchesSearch(strategy: StrategyInfo, query: string): boolean {
  const tokens = query
    .split(/\s+/)
    .map(normalizeStrategySearchText)
    .filter(Boolean);
  if (tokens.length === 0) return true;
  const haystack = strategySearchHaystack(strategy);
  return tokens.every((token) => haystack.includes(token));
}

export interface CreateWizardProps {
  createStep: CreateStep;
  setCreateStep: (s: CreateStep) => void;
  tradeMode: TradeMode;
  selectedExchange: string;
  strategies: StrategyInfo[];
  selectedStrategy: string | number;
  setSelectedStrategy: (id: string | number) => void;
  definedTimeframe: string;
  config: typeof DEFAULT_LIVE_CONFIG;
  setConfig: React.Dispatch<React.SetStateAction<typeof DEFAULT_LIVE_CONFIG>>;
  balances: Balance[];
  balanceLoading: boolean;
  paperInstances: any[];
  onDeletePaper: (id: string) => void;
  onClearAllPaper: () => void;
  paperResult: any;
  setPaperResult: (v: any) => void;
  paperLoading: boolean;
  onRunPaper: () => void;
  preflightResult: any;
  preflightLoading: boolean;
  onRunPreFlight: () => void;
  showLiveConfirm: boolean;
  setShowLiveConfirm: (v: boolean) => void;
  launchLoading: boolean;
  onLaunch: () => void;
  onCancel: () => void;
}

export default function CreateWizard({
  createStep,
  setCreateStep,
  tradeMode,
  selectedExchange,
  strategies,
  selectedStrategy,
  setSelectedStrategy,
  definedTimeframe,
  config,
  setConfig,
  balances,
  balanceLoading,
  paperInstances,
  onDeletePaper,
  onClearAllPaper,
  paperResult,
  setPaperResult,
  paperLoading,
  onRunPaper,
  preflightResult,
  preflightLoading,
  onRunPreFlight,
  showLiveConfirm,
  setShowLiveConfirm,
  launchLoading,
  onLaunch,
  onCancel,
}: CreateWizardProps) {
  const [strategySearchQuery, setStrategySearchQuery] = useState('');
  const isDryRun = tradeMode === 'paper';
  const usdtBalance = balances.find((b) => b.currency === 'USDT');
  const selectedStrategyInfo = strategies.find((s) => String(s.id) === String(selectedStrategy));
  const selectedStrategyName =
    selectedStrategyInfo?.name || String(selectedStrategy);
  const isSuperPnLStrategy = isSuperPnLUniverseStrategy(selectedStrategyInfo);
  const feedSymbols = getStrategySymbols(selectedStrategyInfo);
  const tradeSymbols = getStrategyTradeSymbols(selectedStrategyInfo);
  const symbolScopeLabel = formatStrategySymbolScope(selectedStrategyInfo);
  const symbolScopeTitle = (tradeSymbols.length > 0 ? tradeSymbols : feedSymbols).join(', ');
  const paramRows = strategyParamRows(selectedStrategyInfo);
  const definedTimeframeLabel = formatTimeframeLabel(definedTimeframe);
  const wizardSteps = [
    { id: 'select' as const, label: '选择策略', desc: '策略与资金模式' },
    { id: 'configure' as const, label: '运行参数', desc: '资金与启动' },
    { id: 'preflight' as const, label: '飞行检查', desc: '连通与预检' },
    { id: 'monitor' as const, label: '运行监控', desc: '启动后可查看' },
  ];
  const activeWizardIdx = Math.max(0, wizardSteps.findIndex((s) => s.id === createStep));
  const canContinueFromSelect = Boolean(selectedStrategy && selectedStrategyInfo);
  const visibleStrategies = useMemo(
    () => strategies.filter((strategy) => strategyMatchesSearch(strategy, strategySearchQuery)),
    [strategies, strategySearchQuery],
  );
  const hasStrategySearch = strategySearchQuery.trim().length > 0;

  const renderSelect = () => (
    <div className="space-y-6">
      <div className="sticky top-0 z-10 -mx-1 bg-crypto-bg/95 px-1 pb-3 backdrop-blur">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <Rocket className="w-6 h-6 text-blue-400" />
            <div>
              <h2 className="text-xl font-bold text-white">选择交易策略</h2>
              <p className="mt-1 text-xs text-gray-500">
                {isDryRun ? '仅显示停止中的策略，运行中的策略不能重复创建模拟实例' : '选择要启动的策略'}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onCancel}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg border border-crypto-border bg-crypto-card text-sm text-gray-300 hover:text-white hover:border-gray-500 transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              返回控制台
            </button>
            <button
              type="button"
              disabled={!canContinueFromSelect}
              onClick={() => setCreateStep('configure')}
              className={clsx(
                'flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium transition-colors',
                canContinueFromSelect
                  ? 'bg-blue-600 text-white hover:bg-blue-700'
                  : 'bg-gray-700 text-gray-500 cursor-not-allowed',
              )}
            >
              下一步: 运行参数
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {tradeMode === 'live' && (
        <div className="bg-gradient-to-r from-orange-600/10 to-red-600/10 border border-orange-500/30 rounded-xl p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Wallet className="w-5 h-5 text-orange-400" />
              <div>
                <div className="text-sm font-semibold text-white">
                  实盘账户 · {selectedExchange.toUpperCase()}
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

      {isDryRun && paperInstances.length > 0 && (
        <div className="bg-crypto-card border border-crypto-border rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <Settings2 className="w-4 h-4 text-purple-400" />
              已有模拟实例 ({paperInstances.length})
            </h3>
            {paperInstances.length > 1 && (
              <button
                type="button"
                onClick={onClearAllPaper}
                className="text-[10px] text-gray-500 hover:text-red-400 transition-colors"
              >
                全部清空
              </button>
            )}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {paperInstances.map((inst: any) => (
              <div
                key={inst.instanceId || inst.instance_id || inst.id}
                className="bg-crypto-bg rounded-lg p-3 border border-crypto-border"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-white truncate pr-2">
                    {inst.strategyName || inst.strategy_name}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      onDeletePaper(String(inst.instanceId || inst.instance_id || inst.id))
                    }
                    className="text-gray-600 hover:text-red-400 transition-colors flex-shrink-0"
                  >
                    <XCircle className="w-3.5 h-3.5" />
                  </button>
                </div>
                <div className="text-[10px] text-gray-500 mb-2">
                  {inst.symbol} · {formatTimeframeLabel(inst.timeframe)} · {inst.daysBack || inst.days_back}天
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {strategies.length > 0 && (
        <div className="flex flex-col gap-3 rounded-xl border border-crypto-border bg-crypto-card/70 p-3 sm:flex-row sm:items-center sm:justify-between">
          <label className="relative flex h-11 w-full items-center rounded-xl border border-crypto-border bg-crypto-bg px-3 text-sm text-gray-400 focus-within:border-blue-500/50 focus-within:ring-1 focus-within:ring-blue-500/20 sm:max-w-xl">
            <Search className="mr-2 h-4 w-4 shrink-0 text-gray-500" />
            <span className="sr-only">搜索可创建策略</span>
            <input
              type="search"
              value={strategySearchQuery}
              onChange={(event) => setStrategySearchQuery(event.target.value)}
              placeholder="搜索策略、标的、周期、类型、资金版本..."
              className="min-w-0 flex-1 bg-transparent text-sm font-semibold text-gray-200 placeholder:text-gray-600 focus:outline-none"
            />
            {hasStrategySearch && (
              <button
                type="button"
                onClick={() => setStrategySearchQuery('')}
                aria-label="清空策略搜索"
                className="ml-2 rounded-full p-1 text-gray-600 transition-colors hover:bg-white/5 hover:text-gray-300"
              >
                <XCircle className="h-4 w-4" />
              </button>
            )}
          </label>
          <div className="shrink-0 text-xs font-medium text-gray-500">
            {hasStrategySearch
              ? `匹配 ${visibleStrategies.length} / ${strategies.length} 个可创建策略`
              : `可创建策略 ${strategies.length} 个`}
          </div>
        </div>
      )}

      {strategies.length === 0 ? (
        <div className="rounded-xl border border-crypto-border bg-crypto-card px-5 py-10 text-center">
          <Rocket className="mx-auto mb-3 h-7 w-7 text-gray-600" />
          <div className="text-sm font-semibold text-gray-300">暂无可创建的停止策略</div>
          <p className="mt-2 text-xs text-gray-500">
            运行中的策略已经有模拟实例，需先停止后才能重新创建。
          </p>
        </div>
      ) : visibleStrategies.length === 0 ? (
        <div className="rounded-xl border border-dashed border-crypto-border bg-crypto-card px-5 py-10 text-center">
          <Search className="mx-auto mb-3 h-7 w-7 text-gray-600" />
          <div className="text-sm font-semibold text-gray-300">未找到匹配的可创建策略</div>
          <p className="mt-2 text-xs text-gray-500">换一个策略名称、标的、周期或资金版本试试。</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {visibleStrategies.map((s) => {
            const sid = s.id;
            const isSelected = String(selectedStrategy) === String(sid);
            const bt = s.backtest;
            const riskLevel = s.riskLevel || s.risk_level;
            const isAiAutonomous = isAiAutonomousStrategy(s);
            const riskColor =
              riskLevel === '低'
                ? 'text-green-400'
                : riskLevel === '中'
                  ? 'text-yellow-400'
                  : riskLevel === '中低'
                    ? 'text-green-300'
                    : riskLevel === '中高'
                      ? 'text-orange-400'
                      : 'text-gray-400';
            const isStrategyRunning = s.status === 'running';

            return (
              <button
                key={String(sid)}
                type="button"
                onClick={() => setSelectedStrategy(sid)}
                className={clsx(
                  'relative p-5 rounded-xl border text-left transition-all',
                  isSelected
                    ? SELECTED_SEGMENT_BORDER_CLASS
                    : isStrategyRunning
                      ? 'border-green-500/50 bg-green-500/5 hover:border-green-500/70'
                      : 'border-crypto-border bg-crypto-card hover:border-gray-600',
                )}
              >
              <div className="absolute top-3 right-3 flex items-center gap-1.5">
                {isStrategyRunning && (
                  <span className="flex items-center gap-1 px-2 py-0.5 text-[10px] font-bold bg-green-500/20 text-green-400 rounded-full">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                    运行中
                  </span>
                )}
                {s.recommended && (
                  <span className="px-2 py-0.5 text-[10px] font-bold bg-green-500/20 text-green-400 rounded-full">
                    推荐
                  </span>
                )}
                {isAiAutonomous && (
                  <span className="flex items-center gap-1 px-2 py-0.5 text-[10px] font-bold bg-yellow-500/15 text-yellow-300 rounded-full border border-yellow-500/30">
                    <Zap className="w-3 h-3" />
                    AI自主
                  </span>
                )}
                {riskLevel && (
                  <span
                    className={clsx(
                      'px-2 py-0.5 text-[10px] font-bold rounded-full bg-gray-700/50',
                      riskColor,
                    )}
                  >
                    {riskLevel}风险
                  </span>
                )}
              </div>
              <h3 className="text-sm font-semibold text-white mb-1.5 pr-24">{s.name || sid}</h3>
              <p className="text-xs text-gray-400 leading-relaxed">{s.description}</p>
              <div className="mt-2.5 flex items-center gap-3 text-[10px] text-gray-500">
                {s.timeframe && (
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {formatTimeframeLabel(s.timeframe)}
                  </span>
                )}
                {s.suitableFor && (
                  <span className="flex items-center gap-1">
                    <Zap className="w-3 h-3" />
                    {s.suitableFor}
                  </span>
                )}
              </div>
              {bt && (
                <div className="mt-3 pt-3 border-t border-crypto-border">
                  <div className="text-[10px] text-gray-500 mb-2 flex items-center gap-1">
                    <BarChart3 className="w-3 h-3" />
                    回测绩效
                  </div>
                  <div className="grid grid-cols-5 gap-2">
                    <div className="text-center">
                      <div
                        className={clsx(
                          'text-xs font-bold',
                          (bt.totalReturn ?? 0) >= 0 ? 'text-up' : 'text-down',
                        )}
                      >
                        {bt.totalReturn != null
                          ? `${bt.totalReturn >= 0 ? '+' : ''}${bt.totalReturn.toFixed(1)}%`
                          : '-'}
                      </div>
                      <div className="text-[9px] text-gray-600">总收益</div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs font-bold text-white">
                        {bt.sharpeRatio != null ? bt.sharpeRatio.toFixed(2) : '-'}
                      </div>
                      <div className="text-[9px] text-gray-600">夏普</div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs font-bold text-white">
                        {bt.winRate != null ? `${bt.winRate.toFixed(1)}%` : '-'}
                      </div>
                      <div className="text-[9px] text-gray-600">胜率</div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs font-bold text-white">
                        {bt.profitFactor != null ? bt.profitFactor.toFixed(2) : '-'}
                      </div>
                      <div className="text-[9px] text-gray-600">盈亏比</div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs font-bold text-red-300">
                        {bt.maxDrawdown != null ? `${bt.maxDrawdown.toFixed(1)}%` : '-'}
                      </div>
                      <div className="text-[9px] text-gray-600">最大回撤</div>
                    </div>
                  </div>
                </div>
              )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );

  const renderConfigure = () => (
    <div className="space-y-6">
      <div className="sticky top-0 z-10 -mx-1 bg-crypto-bg/95 px-1 pb-3 backdrop-blur">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            <Settings2 className="w-6 h-6 text-blue-400" />
            <h2 className="text-xl font-bold text-white">运行参数</h2>
            <span className="max-w-full truncate px-3 py-1 text-xs bg-blue-500/20 text-blue-400 rounded-full">
              {selectedStrategyName}
            </span>
            <span
              className={clsx(
                'px-3 py-1 text-xs rounded-full',
                isDryRun ? 'bg-yellow-500/20 text-yellow-400' : 'bg-red-500/20 text-red-400',
              )}
            >
              {isDryRun ? '模拟盘' : '实盘'}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setCreateStep('select')}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg border border-crypto-border bg-crypto-card text-sm text-gray-300 hover:text-white hover:border-gray-500 transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              返回
            </button>
            <button
              type="button"
              onClick={() => setCreateStep('preflight')}
              className="flex items-center gap-2 px-6 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
            >
              下一步: 飞行检查
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-crypto-card border border-crypto-border rounded-xl p-5 space-y-4">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-blue-400" />
            策略定义
          </h3>
          <div className="space-y-3">
            <div>
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="text-xs text-gray-400">交易范围</span>
                <span className="inline-flex items-center gap-1 rounded-full bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium text-blue-300">
                  <Lock className="h-3 w-3" />
                  来自策略
                </span>
              </div>
              <div
                className="w-full min-h-[42px] bg-crypto-bg border border-crypto-border rounded-lg px-3 py-2 text-sm text-white leading-relaxed"
                title={symbolScopeTitle}
              >
                {symbolScopeLabel}
              </div>
            </div>
            <div className="rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-gray-500">驱动方式</span>
                <Info className="h-3.5 w-3.5 text-gray-500" />
              </div>
              <div className="mt-1 text-sm font-semibold text-white">按K线收盘</div>
            </div>
            <div>
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="text-xs text-gray-400">策略内置参数</span>
                <span className="text-[10px] text-gray-600">启动时随策略配置加载</span>
              </div>
              {paramRows.length > 0 ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {paramRows.map((item) => (
                    <div
                      key={item.key}
                      className="rounded-lg border border-crypto-border/80 bg-crypto-bg/80 px-3 py-2"
                    >
                      <div className="text-[10px] text-gray-500">{item.label}</div>
                      <div className="mt-0.5 truncate text-sm font-semibold text-gray-100" title={item.value}>
                        {item.value}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-lg border border-crypto-border bg-crypto-bg px-3 py-3 text-sm text-gray-400">
                  未声明可展示的策略参数
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="bg-crypto-card border border-crypto-border rounded-xl p-5 space-y-4">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2">
            <Wallet className="w-4 h-4 text-yellow-400" />
            启动参数
          </h3>
          <div className="space-y-3">
            <label className="block">
              <span className="text-xs text-gray-400 mb-1 block">
                {isDryRun ? '模拟初始资金 (USDT)' : '投入资金 (USDT)'}
              </span>
              <input
                type="number"
                value={config.initialEquity}
                onChange={(e) =>
                  setConfig({ ...config, initialEquity: Number(e.target.value) })
                }
                className="w-full bg-crypto-bg border border-crypto-border rounded-lg px-3 py-2 text-sm text-white"
              />
              {!isDryRun && usdtBalance && (
                <div className="mt-1.5 flex items-center justify-between text-xs">
                  <span className="text-gray-500">
                    账户可用:{' '}
                    <span className="text-green-400">${usdtBalance.free.toFixed(2)}</span>
                  </span>
                  <div className="flex gap-2">
                    {[25, 50, 75, 100].map((pct) => (
                      <button
                        key={pct}
                        type="button"
                        onClick={() =>
                          setConfig({
                            ...config,
                            initialEquity: Math.floor((usdtBalance.free * pct) / 100),
                          })
                        }
                        className="px-2 py-0.5 bg-gray-800 text-gray-400 rounded hover:bg-gray-700 hover:text-white text-[10px]"
                      >
                        {pct}%
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </label>
            <div className="flex items-center justify-between py-2 px-3 bg-crypto-bg rounded-lg border border-crypto-border">
              <div>
                <span className="text-xs text-gray-400 block">运行模式</span>
                <span
                  className={clsx(
                    'text-sm font-medium',
                    isDryRun ? 'text-yellow-400' : 'text-red-400',
                  )}
                >
                  {isDryRun ? '模拟模式 (不实际下单)' : '实盘模式 (真实下单)'}
                </span>
              </div>
              <div
                className={clsx('w-3 h-3 rounded-full', isDryRun ? 'bg-yellow-400' : 'bg-red-400')}
              />
            </div>
          </div>
          <div className="border-t border-crypto-border pt-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-green-400" />
                通用启动风控
              </h3>
              <span className="rounded-full border border-crypto-border bg-crypto-bg px-2 py-0.5 text-[10px] font-medium text-gray-500">
                默认启动参数
              </span>
            </div>
            <div className="space-y-3">
              <label className="block">
                <span className="text-xs text-gray-400 mb-1 block">单笔风险比例</span>
                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min="0.01"
                    max="0.1"
                    step="0.01"
                    value={config.riskPerTrade}
                    onChange={(e) =>
                      setConfig({ ...config, riskPerTrade: Number(e.target.value) })
                    }
                    className="flex-1"
                  />
                  <span className="text-sm text-white w-12 text-right">
                    {(config.riskPerTrade * 100).toFixed(0)}%
                  </span>
                </div>
              </label>
              <label className="block">
                <span className="text-xs text-gray-400 mb-1 block">单日最大亏损</span>
                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min="0.02"
                    max="0.2"
                    step="0.01"
                    value={config.maxDailyLoss}
                    onChange={(e) =>
                      setConfig({ ...config, maxDailyLoss: Number(e.target.value) })
                    }
                    className="flex-1"
                  />
                  <span className="text-sm text-white w-12 text-right">
                    {(config.maxDailyLoss * 100).toFixed(0)}%
                  </span>
                </div>
              </label>
              <label className="block">
                <span className="text-xs text-gray-400 mb-1 block">总最大亏损 (熔断线)</span>
                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min="0.05"
                    max="0.5"
                    step="0.01"
                    value={config.maxTotalLoss}
                    onChange={(e) =>
                      setConfig({ ...config, maxTotalLoss: Number(e.target.value) })
                    }
                    className="flex-1"
                  />
                  <span className="text-sm text-white w-12 text-right">
                    {(config.maxTotalLoss * 100).toFixed(0)}%
                  </span>
                </div>
              </label>
            </div>
          </div>

          <div className="mt-4 pt-4 border-t border-crypto-border">
            <h4 className="text-xs text-gray-400 mb-3">
              快速验证 (策略周期 {definedTimeframeLabel} · 最近{' '}
              {paperQuickVerifyDaysBack(definedTimeframe)} 天数据)
            </h4>
            {isSuperPnLStrategy ? (
              <div className="rounded-lg border border-purple-500/30 bg-purple-500/10 px-3 py-2 text-xs leading-relaxed text-purple-200">
                该策略依赖 Top20 实时币池批量预测和 Kairos 二次确认，当前快捷验证是单币同步回测，不适合此策略；请直接进入飞行检查后启动模拟盘。
              </div>
            ) : (
              <button
                type="button"
                onClick={onRunPaper}
                disabled={paperLoading}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-purple-600/20 text-purple-400 border border-purple-500/30 rounded-lg text-sm hover:bg-purple-600/30 transition-colors disabled:opacity-50"
              >
                {paperLoading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    运行模拟盘中…
                  </>
                ) : (
                  <>
                    <Eye className="w-4 h-4" />
                    运行模拟盘验证
                  </>
                )}
              </button>
            )}
            {paperResult && !paperResult.error && (
              <div className="mt-3 space-y-3">
                <div className="grid grid-cols-5 gap-2 text-center">
                  <div className="bg-crypto-bg rounded-lg p-2">
                    <div
                      className={clsx(
                        'text-sm font-bold',
                        (paperResult.totalReturnPct ??
                          paperResult.totalReturn ??
                          paperResult.total_return_pct ??
                          paperResult.total_return ??
                          0) >= 0
                          ? 'text-up'
                          : 'text-down',
                      )}
                    >
                      {(
                        paperResult.totalReturnPct ??
                        paperResult.totalReturn ??
                        paperResult.total_return_pct ??
                        paperResult.total_return ??
                        0
                      ).toFixed(1)}
                      %
                    </div>
                    <div className="text-[10px] text-gray-500">收益率</div>
                  </div>
                  <div className="bg-crypto-bg rounded-lg p-2">
                    <div className="text-sm font-bold text-white">
                      {(paperResult.sharpeRatio ?? paperResult.sharpe_ratio ?? 0).toFixed(2)}
                    </div>
                    <div className="text-[10px] text-gray-500">夏普比率</div>
                  </div>
                  <div className="bg-crypto-bg rounded-lg p-2">
                    <div className="text-sm font-bold text-white">
                      {(paperResult.winRate ?? paperResult.win_rate ?? 0).toFixed(1)}
                      %
                    </div>
                    <div className="text-[10px] text-gray-500">胜率</div>
                  </div>
                  <div className="bg-crypto-bg rounded-lg p-2">
                    <div className="text-sm font-bold text-white">
                      {(paperResult.profitFactor ?? paperResult.profit_factor ?? 0).toFixed(2)}
                    </div>
                    <div className="text-[10px] text-gray-500">盈亏比</div>
                  </div>
                  <div className="bg-crypto-bg rounded-lg p-2">
                    <div className="text-sm font-bold text-red-400">
                      {(
                        paperResult.maxDrawdownPct ??
                        paperResult.maxDrawdown ??
                        paperResult.max_drawdown_pct ??
                        paperResult.max_drawdown ??
                        0
                      ).toFixed(1)}
                      %
                    </div>
                    <div className="text-[10px] text-gray-500">最大回撤</div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setPaperResult(null)}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600/20 text-blue-400 border border-blue-500/30 rounded-lg text-xs hover:bg-blue-600/30 transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" />
                  清除结果并重新验证
                </button>
              </div>
            )}
            {paperResult?.error && (
              <div className="mt-3 p-2 bg-red-500/10 border border-red-500/30 rounded-lg text-xs text-red-400">
                {paperResult.error}
              </div>
            )}
          </div>
        </div>
      </div>

    </div>
  );

  const renderPreflight = () => (
    <div className="space-y-6">
      <div className="sticky top-0 z-10 -mx-1 bg-crypto-bg/95 px-1 pb-3 backdrop-blur">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <ShieldCheck className="w-6 h-6 text-green-400" />
            <h2 className="text-xl font-bold text-white">飞行检查</h2>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setCreateStep('configure')}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg border border-crypto-border bg-crypto-card text-sm text-gray-300 hover:text-white hover:border-gray-500 transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              返回
            </button>
            <button
              type="button"
              onClick={onLaunch}
              disabled={launchLoading}
              className={clsx(
                'flex items-center gap-2 px-8 py-2.5 rounded-lg text-sm font-medium transition-colors',
                isDryRun
                  ? 'bg-yellow-600 text-white hover:bg-yellow-700'
                  : 'bg-red-600 text-white hover:bg-red-700',
              )}
            >
              {launchLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  启动中…
                </>
              ) : (
                <>
                  <Rocket className="w-4 h-4" />
                  {isDryRun ? '启动模拟运行' : '启动实盘交易'}
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      <div className="bg-crypto-card border border-crypto-border rounded-xl p-5">
        <h3 className="text-sm font-semibold text-white mb-3">配置摘要</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <span className="text-[10px] text-gray-500 block">策略</span>
            <span className="text-sm text-white">{selectedStrategyName}</span>
          </div>
          <div>
            <span className="text-[10px] text-gray-500 block">交易范围</span>
            <span className="text-sm text-white" title={symbolScopeTitle}>{symbolScopeLabel}</span>
          </div>
          <div>
            <span className="text-[10px] text-gray-500 block">策略周期</span>
            <span className="text-sm text-white">{definedTimeframeLabel}</span>
          </div>
          <div>
            <span className="text-[10px] text-gray-500 block">模式</span>
            <span
              className={clsx('text-sm font-medium', isDryRun ? 'text-yellow-400' : 'text-red-400')}
            >
              {isDryRun ? '模拟盘' : '实盘'}
            </span>
          </div>
          <div>
            <span className="text-[10px] text-gray-500 block">
              {isDryRun ? '模拟资金' : '投入资金'}
            </span>
            <span className="text-sm text-white">${config.initialEquity}</span>
          </div>
          <div>
            <span className="text-[10px] text-gray-500 block">单笔风险</span>
            <span className="text-sm text-white">{(config.riskPerTrade * 100).toFixed(0)}%</span>
          </div>
          <div>
            <span className="text-[10px] text-gray-500 block">日损限额</span>
            <span className="text-sm text-white">{(config.maxDailyLoss * 100).toFixed(0)}%</span>
          </div>
          <div>
            <span className="text-[10px] text-gray-500 block">熔断线</span>
            <span className="text-sm text-white">{(config.maxTotalLoss * 100).toFixed(0)}%</span>
          </div>
        </div>
      </div>

      {!isDryRun && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-red-400 mt-0.5 shrink-0" />
          <div>
            <div className="text-sm font-semibold text-red-400">实盘交易风险警告</div>
            <div className="text-xs text-red-300/70 mt-1 leading-relaxed">
              即将使用您在 {selectedExchange.toUpperCase()} 的真实资金进行交易。策略将自动下单，可能造成本金亏损。
            </div>
          </div>
        </div>
      )}

      {!preflightResult && !preflightLoading && (
        <div className="text-center py-8">
          <button
            type="button"
            onClick={onRunPreFlight}
            className="inline-flex items-center gap-2 px-8 py-3 bg-green-600/20 text-green-400 border border-green-500/30 rounded-xl text-sm font-medium hover:bg-green-600/30 transition-colors"
          >
            <ShieldCheck className="w-5 h-5" />
            运行飞行检查
          </button>
          <p className="text-xs text-gray-500 mt-3">在正式上线前验证系统环境、数据、连接状态</p>
        </div>
      )}

      {preflightLoading && (
        <div className="text-center py-8">
          <Loader2 className="w-8 h-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-sm text-gray-400">正在进行飞行检查…</p>
        </div>
      )}

      {preflightResult && (
        <div className="bg-crypto-card border border-crypto-border rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2 mb-4">
            {preflightResult.allPassed ?? preflightResult.all_passed ? (
              <>
                <CheckCircle2 className="w-5 h-5 text-green-400" />
                <span className="text-green-400 font-semibold text-sm">全部通过</span>
              </>
            ) : (
              <>
                <AlertTriangle className="w-5 h-5 text-yellow-400" />
                <span className="text-yellow-400 font-semibold text-sm">存在未通过项</span>
              </>
            )}
          </div>
          {(preflightResult.checks || []).map((check: any, i: number) => (
            <div
              key={i}
              className={clsx(
                'flex items-start gap-3 p-3 rounded-lg',
                check.passed ? 'bg-green-500/5' : 'bg-red-500/5',
              )}
            >
              {check.passed ? (
                <CheckCircle2 className="w-4 h-4 text-green-400 mt-0.5 shrink-0" />
              ) : (
                <XCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
              )}
              <div>
                <div className="text-sm text-white">{check.item}</div>
                {check.detail && (
                  <div className="text-xs text-gray-500 mt-0.5">{check.detail}</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <ThemeDialog
        open={showLiveConfirm}
        variant="confirm"
        title="确认启动实盘交易"
        tone="danger"
        confirmText="确认启动实盘"
        cancelText="取消"
        onCancel={() => setShowLiveConfirm(false)}
        onConfirm={() => void onLaunch()}
      >
        <div className="space-y-2 text-sm text-gray-300">
          <p>
            您即将启动<span className="text-red-400 font-bold">实盘交易</span>，系统将使用您在{' '}
            <span className="text-white font-medium">{selectedExchange.toUpperCase()}</span>{' '}
            的真实资金。
          </p>
          <div className="bg-crypto-bg rounded-lg p-3 space-y-1 border border-crypto-border">
            <div className="flex justify-between">
              <span className="text-gray-500">策略</span>
              <span className="text-white">{selectedStrategyName}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">交易范围</span>
              <span className="text-white text-right" title={symbolScopeTitle}>{symbolScopeLabel}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">投入资金</span>
              <span className="text-white">${config.initialEquity}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">熔断线</span>
              <span className="text-red-400">
                {(config.maxTotalLoss * 100).toFixed(0)}% (亏损 $
                {(config.initialEquity * config.maxTotalLoss).toFixed(0)})
              </span>
            </div>
          </div>
          <p className="text-red-300/80 text-xs">策略交易存在风险，过去的回测表现不代表未来收益。</p>
        </div>
      </ThemeDialog>
    </div>
  );

  return (
    <div className="space-y-2">
      <div className="mb-8 rounded-xl border border-crypto-border bg-crypto-card/80 px-3 py-4 sm:px-6">
        <div className="flex w-full max-w-4xl mx-auto items-start">
          {wizardSteps.map((step, i) => {
            const isPast = i < activeWizardIdx;
            const isActive = i === activeWizardIdx;
            const isFuture = i > activeWizardIdx;

            return (
              <Fragment key={step.id}>
                <div className="flex flex-col items-center shrink-0 w-[21%] sm:w-36 min-w-0">
                  <div
                    className={clsx(
                      'flex h-9 w-9 sm:h-10 sm:w-10 shrink-0 items-center justify-center rounded-full border-2 text-xs sm:text-sm font-bold transition-colors',
                      isActive &&
                        'border-blue-400 bg-blue-500/25 text-blue-200 shadow-[0_0_0_4px_rgba(59,130,246,0.15)]',
                      isPast && !isActive && 'border-emerald-500/60 bg-emerald-500/10 text-emerald-300',
                      isFuture &&
                        !isActive &&
                        'border-crypto-border bg-crypto-bg text-gray-500',
                    )}
                  >
                    {isPast && !isActive ? (
                      <CheckCircle2 className="w-4 h-4 sm:w-5 sm:h-5" />
                    ) : (
                      <span>{i + 1}</span>
                    )}
                  </div>
                  <div className="mt-2 text-center px-0.5 w-full">
                    <div
                      className={clsx(
                        'text-[11px] sm:text-xs font-semibold leading-tight',
                        isActive && 'text-white',
                        isPast && !isActive && 'text-emerald-200/90',
                        isFuture && !isActive && 'text-gray-500',
                      )}
                    >
                      {step.label}
                    </div>
                    <div className="text-[10px] text-gray-600 mt-0.5 leading-tight hidden sm:block">
                      {step.desc}
                    </div>
                  </div>
                </div>
                {i < wizardSteps.length - 1 && (
                  <div
                    className={clsx(
                      'h-0.5 flex-1 min-w-[6px] mt-[1.125rem] sm:mt-5 rounded-full transition-colors shrink',
                      i < activeWizardIdx ? 'bg-emerald-500/45' : 'bg-crypto-border',
                    )}
                    aria-hidden
                  />
                )}
              </Fragment>
            );
          })}
        </div>
      </div>
      {createStep === 'select' && renderSelect()}
      {createStep === 'configure' && renderConfigure()}
      {createStep === 'preflight' && renderPreflight()}
    </div>
  );
}
