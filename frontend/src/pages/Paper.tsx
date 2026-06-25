import { useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import {
  Activity,
  ArrowDown,
  ArrowDownUp,
  ArrowUp,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FlaskConical,
  Plus,
  RefreshCw,
  Rocket,
  ShieldCheck,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import {
  getStrategies,
  listPaperAccounts,
  refreshPaperAccount,
  runPaperTrading,
  stopPaperAccount,
} from '../api/client';
import { AshareGuardrailStrip } from '../components/AshareGuardrailStrip';
import { PaperInstanceDetailPanel } from '../components/BitProDetailPanels';
import { formatSymbolLabel, normalizeSymbolCode } from '../utils/symbolDisplay';
import type { PaperAccount, Strategy } from '../types';

type AssetFilter = 'all' | 'ashare';
type SortField = 'created' | 'return';
type SortDirection = 'asc' | 'desc';
type SortMode =
  | 'created_desc'
  | 'created_asc'
  | 'return_desc'
  | 'return_asc';

const wizardSteps = [
  { title: '选择策略', subtitle: '策略可独立运行' },
  { title: '运行参数', subtitle: '资金与启动' },
  { title: '飞行检查', subtitle: '注册与预检' },
  { title: '运行监控', subtitle: '启动后可查看' },
];

const compactNumber = (value?: number | null, digits = 0) =>
  value == null || !Number.isFinite(value)
    ? '--'
    : Number(value).toLocaleString('zh-CN', {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
      });

const formatSignedCny = (value?: number | null) => {
  if (value == null || !Number.isFinite(value)) return '--';
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  return `${sign}¥${Math.abs(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
};

const formatSignedPercent = (value?: number | null) => {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${value.toFixed(2)}%`;
};

const formatRatio = (value?: number | null) =>
  value != null && Number.isFinite(value) && value >= 0 ? value.toFixed(2) : '--';

const mergePaperAccount = (base: PaperAccount | null | undefined, update: PaperAccount): PaperAccount => ({
  ...(base || {}),
  ...update,
  account_id: update.account_id ?? base?.account_id ?? 0,
  strategy_id: update.strategy_id ?? base?.strategy_id ?? 0,
  strategy_name: update.strategy_name ?? base?.strategy_name,
  name: update.name ?? base?.name ?? 'A股模拟盘',
  initial_capital: update.initial_capital ?? base?.initial_capital ?? 100000,
  cash: update.cash ?? base?.cash ?? 0,
  equity: update.equity ?? base?.equity ?? 0,
  status: update.status ?? base?.status ?? 'unknown',
  created_at: update.created_at ?? base?.created_at ?? '',
  updated_at: update.updated_at ?? base?.updated_at,
  orders: update.orders ?? base?.orders,
  positions: update.positions ?? base?.positions,
  equity_curve: update.equity_curve ?? base?.equity_curve,
  events: update.events ?? base?.events,
});

const accountPnl = (account: PaperAccount) => account.equity - account.initial_capital;

const accountReturnPct = (account: PaperAccount) =>
  account.initial_capital > 0 ? (accountPnl(account) / account.initial_capital) * 100 : null;

const accountWinRate = (account: PaperAccount) => {
  const positions = account.positions || [];
  if (positions.length === 0) return null;
  return (positions.filter((item) => item.pnl >= 0).length / positions.length) * 100;
};

const accountProfitFactor = (account: PaperAccount) => {
  const positions = account.positions || [];
  if (positions.length === 0) return null;
  const grossProfit = positions.reduce((sum, item) => sum + Math.max(item.pnl, 0), 0);
  const grossLoss = positions.reduce((sum, item) => sum + Math.abs(Math.min(item.pnl, 0)), 0);
  if (grossProfit <= 0) return null;
  if (grossLoss === 0) return grossProfit > 0 ? grossProfit / 1000 : null;
  return grossProfit / grossLoss;
};

const accountTradeCount = (account: PaperAccount) => account.orders?.length ?? 0;

const accountSymbols = (account: PaperAccount) => {
  const names = new Map<string, string>();
  const symbolSet = new Set<string>();
  for (const item of account.positions || []) {
    const code = normalizeSymbolCode(item.symbol);
    if (code) symbolSet.add(code);
    if (code && item.name) names.set(code, item.name);
  }
  for (const item of account.orders || []) {
    const code = normalizeSymbolCode(item.symbol);
    if (code) symbolSet.add(code);
    if (code && item.name && !names.has(code)) names.set(code, item.name);
  }
  const symbols = [...symbolSet];
  return symbols.length > 0 ? symbols.map((symbol) => formatSymbolLabel(symbol, names.get(symbol))).join(' / ') : 'A股多股组合';
};

const sortDirectionFor = (sortMode: SortMode, field: SortField): SortDirection | null => {
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
  return null;
};

const nextSortMode = (sortMode: SortMode, field: SortField): SortMode => {
  const currentDirection = sortDirectionFor(sortMode, field);
  if (field === 'created') return currentDirection === 'desc' ? 'created_asc' : 'created_desc';
  return currentDirection === 'desc' ? 'return_asc' : 'return_desc';
};

function SortArrow({ direction }: { direction: SortDirection | null }) {
  if (direction === 'asc') return <ArrowUp className="h-3.5 w-3.5" />;
  if (direction === 'desc') return <ArrowDown className="h-3.5 w-3.5" />;
  return <ArrowDownUp className="h-3.5 w-3.5 opacity-60" />;
}

function statusLabel(status: string) {
  const normalized = status.toLowerCase();
  if (normalized === 'running') return '运行中';
  if (normalized === 'stopped') return '已停止';
  return status || '--';
}

function statusClass(status: string) {
  const normalized = status.toLowerCase();
  if (normalized === 'running') return 'bg-emerald-500/20 text-emerald-300';
  if (normalized === 'stopped') return 'bg-gray-700/50 text-gray-400';
  return 'bg-yellow-500/20 text-yellow-300';
}

export function Paper() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [strategyId, setStrategyId] = useState<number | ''>('');
  const [accounts, setAccounts] = useState<PaperAccount[]>([]);
  const [selected, setSelected] = useState<PaperAccount | null>(null);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [assetFilter, setAssetFilter] = useState<AssetFilter>('all');
  const [sortMode, setSortMode] = useState<SortMode>('return_desc');
  const [view, setView] = useState<'console' | 'detail'>('console');
  const [showCreateWizard, setShowCreateWizard] = useState(false);
  const [wizardStep, setWizardStep] = useState(0);
  const [draftInitialCapital, setDraftInitialCapital] = useState(100000);
  const [draftPositionPct, setDraftPositionPct] = useState(0.3);

  const load = async () => {
    const [strategyData, accountData] = await Promise.all([getStrategies(), listPaperAccounts()]);
    setStrategies(strategyData);
    setAccounts(accountData.accounts);
    setStrategyId((current) => current || strategyData[0]?.id || '');
    setSelected((current) => current || accountData.accounts[0] || null);
  };

  useEffect(() => {
    void load();
  }, []);

  const mergedAccounts = useMemo(() => {
    const byId = new Map<number, PaperAccount>();
    for (const account of accounts) {
      byId.set(account.account_id, account);
    }
    if (selected) {
      byId.set(selected.account_id, mergePaperAccount(byId.get(selected.account_id), selected));
    }
    return Array.from(byId.values());
  }, [accounts, selected]);

  const visibleAccounts = useMemo(() => {
    const filtered = mergedAccounts.filter(() => assetFilter === 'all' || assetFilter === 'ashare');

    return [...filtered].sort((a, b) => {
      if (sortMode.startsWith('return')) {
        const diff = (accountReturnPct(b) ?? -Infinity) - (accountReturnPct(a) ?? -Infinity);
        return sortMode === 'return_asc' ? -diff : diff;
      }
      const diff = Date.parse(b.created_at || '') - Date.parse(a.created_at || '');
      return sortMode === 'created_asc' ? -diff : diff;
    });
  }, [assetFilter, mergedAccounts, sortMode]);

  const overview = useMemo(() => {
    const totalEquity = mergedAccounts.reduce((sum, account) => sum + Number(account.equity || 0), 0);
    const totalPnl = mergedAccounts.reduce((sum, account) => sum + accountPnl(account), 0);
    const runningCount = mergedAccounts.filter((account) => account.status.toLowerCase() === 'running').length;
    const totalTrades = mergedAccounts.reduce((sum, account) => sum + accountTradeCount(account), 0);
    const latestTimestamp = mergedAccounts
      .map((account) => Date.parse(account.updated_at || account.created_at || ''))
      .filter((time) => Number.isFinite(time))
      .sort((a, b) => b - a)[0];

    return {
      totalEquity,
      totalPnl,
      runningCount,
      totalTrades,
      latestUpdatedAt: latestTimestamp ? new Date(latestTimestamp).toLocaleString('zh-CN', { hour12: false }) : '--',
    };
  }, [mergedAccounts]);

  const assetCounts: Record<AssetFilter, number> = {
    all: mergedAccounts.length,
    ashare: mergedAccounts.length,
  };

  const selectedStrategy = useMemo(
    () => strategies.find((strategy) => strategy.id === Number(strategyId)) || strategies[0],
    [strategies, strategyId],
  );

  const updateAccount = (account: PaperAccount) => {
    setAccounts((prev) => {
      const current = prev.find((item) => item.account_id === account.account_id);
      const merged = mergePaperAccount(current, account);
      return [merged, ...prev.filter((item) => item.account_id !== account.account_id)];
    });
    setSelected((current) => mergePaperAccount(current?.account_id === account.account_id ? current : null, account));
  };

  const openCreateWizard = () => {
    setStrategyId((current) => current || strategies[0]?.id || '');
    setWizardStep(0);
    setShowCreateWizard(true);
  };

  const closeCreateWizard = () => {
    if (loading) return;
    setShowCreateWizard(false);
    setWizardStep(0);
  };

  const start = async () => {
    const nextStrategyId = strategyId || strategies[0]?.id;
    if (!nextStrategyId) return;
    setLoading(true);
    setMessage('');
    try {
      const account = await runPaperTrading(Number(nextStrategyId), {
        symbols: ['SH_600000', 'SZ_000001'],
        initial_capital: draftInitialCapital,
        position_pct: draftPositionPct,
      });
      updateAccount(account);
      setMessage('模拟盘已启动');
      setShowCreateWizard(false);
      setWizardStep(0);
    } finally {
      setLoading(false);
    }
  };

  const refresh = async (account: PaperAccount) => {
    const refreshed = await refreshPaperAccount(account.account_id);
    const merged = mergePaperAccount(account, refreshed);
    updateAccount(merged);
    setMessage(merged.events?.at(-1)?.message || '手动刷新完成');
  };

  const stop = async (account: PaperAccount) => {
    const stopped = await stopPaperAccount(account.account_id);
    const merged = mergePaperAccount(account, stopped);
    updateAccount(merged);
    setMessage(merged.events?.at(-1)?.message || '模拟盘已停止');
  };

  const sortControls: Array<{ field: SortField; label: string }> = [
    { field: 'return', label: '收益率' },
    { field: 'created', label: '创建时间' },
  ];

  const finalWizardStep = wizardSteps.length - 1;
  const nextWizardLabel =
    wizardStep === 0 ? '下一步 · 运行参数' : wizardStep === 1 ? '下一步 · 飞行检查' : '下一步 · 运行监控';

  if (view === 'detail' && selected) {
    return (
      <div className="min-h-full bg-crypto-bg p-6">
        <PaperInstanceDetailPanel
          account={selected}
          onBack={() => setView('console')}
          onRefresh={(account) => refresh(account)}
          onStop={(account) => stop(account)}
        />
      </div>
    );
  }

  return (
    <div className="min-h-full bg-crypto-bg p-6">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="flex w-fit items-center gap-2 rounded-xl border border-yellow-500/30 bg-yellow-500/10 px-4 py-2.5 text-sm font-semibold text-yellow-300">
            <FlaskConical className="h-4 w-4" />
            模拟盘
          </div>
          <p className="max-w-lg text-[11px] leading-snug text-gray-500">
            模拟：只做 PaperBroker / 模拟成交，不触碰真实资金。
          </p>
        </div>
      </div>

      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-bold text-white">
              <Activity className="h-6 w-6 text-blue-400" />
              策略实例控制台
            </h1>
            <p className="mt-1 text-sm text-gray-500">
              管理多路模拟实例；通过模拟盘验证后可在「实盘」入口晋级。
            </p>
          </div>
          <button
            type="button"
            onClick={openCreateWizard}
            disabled={loading || (!strategyId && strategies.length === 0)}
            className="inline-flex w-auto shrink-0 items-center justify-center gap-2 rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-blue-900/20 transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Plus className="h-4 w-4" />
            创建新模拟实例
          </button>
        </div>

        {message && (
          <div className="rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-sm font-semibold text-blue-300">
            {message}
          </div>
        )}

        <AshareGuardrailStrip
          title="实盘前置约束"
          description="模拟盘是实盘前的最后验收层，所有成交和风控都按 A 股制度做预检查。"
          items={[
            { label: 'T+1 / 100股', detail: '卖出、买入数量和持仓可用量必须先过交易制度校验。' },
            { label: '涨跌停风险', detail: '接近涨跌停、停牌和异常波动标的进入高风险提示。' },
            { label: 'PaperBroker隔离', detail: '当前只写模拟账户，不触碰真实资金或券商接口。' },
          ]}
        />

        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex h-11 items-center rounded-xl border border-crypto-border bg-crypto-card p-1">
            {[
              { value: 'all' as const, label: '全部' },
              { value: 'ashare' as const, label: 'A股' },
            ].map((option) => {
              const active = assetFilter === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setAssetFilter(option.value)}
                  className={clsx(
                    'inline-flex h-9 min-w-20 items-center justify-center gap-2 rounded-lg px-3 text-xs font-semibold transition-colors',
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
                    {assetCounts[option.value]}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="inline-flex h-11 items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card/80 p-1">
            {sortControls.map((control) => {
              const direction = sortDirectionFor(sortMode, control.field);
              const active = direction !== null;
              return (
                <button
                  key={control.field}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setSortMode(nextSortMode(sortMode, control.field))}
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
        </div>

        <section className="grid gap-3 rounded-xl border border-crypto-border bg-crypto-card/70 p-4 shadow-sm shadow-black/20 lg:grid-cols-[1.2fr_repeat(4,minmax(0,1fr))]">
          <div className="flex min-w-0 flex-col justify-center">
            <div className="flex items-center gap-2 text-sm font-bold text-white">
              <ShieldCheck className="h-4 w-4 text-yellow-300" />
              模拟账户概览
            </div>
            <p className="mt-1 text-xs leading-5 text-gray-500">
              汇总当前 PaperBroker 实例的状态、资金和最近刷新时间。
            </p>
          </div>
          {[
            ['运行中账户', `${overview.runningCount}/${mergedAccounts.length}`, 'text-emerald-300', '当前仍在接收刷新指令的账户'],
            ['账户总权益', `¥${compactNumber(overview.totalEquity, 2)}`, 'text-blue-300', '全部模拟账户权益合计'],
            ['总盈亏', formatSignedCny(overview.totalPnl), overview.totalPnl >= 0 ? 'text-up' : 'text-down', '按初始资金口径汇总'],
            ['总交易数', String(overview.totalTrades), 'text-purple-200', `最近更新 ${overview.latestUpdatedAt}`],
          ].map(([label, value, tone, caption]) => (
            <div key={label} className="min-h-20 rounded-lg border border-crypto-border bg-crypto-bg/65 px-3 py-3">
              <div className="text-[10px] font-semibold text-gray-500">{label}</div>
              <div className={clsx('mt-2 truncate text-lg font-bold tabular-nums', tone)}>{value}</div>
              <div className="mt-1 truncate text-[10px] text-gray-600">{caption}</div>
            </div>
          ))}
        </section>

        <div data-testid="paper-instance-grid" className="grid grid-cols-1 gap-3 lg:grid-cols-4">
          {visibleAccounts.length === 0 && (
            <div className="col-span-full flex flex-col items-center justify-center rounded-xl border border-dashed border-crypto-border py-16 text-sm text-gray-500">
              <Rocket className="mb-3 h-10 w-10 opacity-40" />
              暂无模拟实例。点击「创建新模拟实例」启动策略。
            </div>
          )}

          {visibleAccounts.map((account) => {
            const pnl = accountPnl(account);
            const returnPct = accountReturnPct(account);
            const winRate = accountWinRate(account);
            const profitFactor = accountProfitFactor(account);
            const tradeCount = accountTradeCount(account);
            return (
              <div
                key={account.account_id}
                data-testid="paper-instance-card"
                data-account-id={account.account_id}
                className="flex flex-col gap-3 rounded-xl border border-crypto-border bg-crypto-card p-3 transition-colors hover:border-gray-600"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div
                      title={account.name}
                      aria-label={`策略名称：${account.name}`}
                      className="min-w-0 truncate text-sm font-semibold text-[#FFAB73]"
                    >
                      {account.name}
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <span className="inline-flex h-5 items-center rounded-full border border-blue-500/30 bg-blue-500/10 px-2 text-[10px] font-bold uppercase tracking-normal text-blue-300">
                        1D
                      </span>
                      <span className="inline-flex h-5 items-center rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 text-[10px] font-bold uppercase tracking-normal text-emerald-300">
                        {compactNumber(account.initial_capital / 10000, 0)}万
                      </span>
                    </div>
                    <div className="mt-0.5 text-[11px] text-gray-500">{accountSymbols(account)}</div>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    <span
                      className={clsx(
                        'inline-flex min-w-12 justify-center rounded-full px-2 py-0.5 text-[10px] font-bold',
                        statusClass(account.status),
                      )}
                    >
                      {statusLabel(account.status)}
                    </span>
                    <button
                      type="button"
                      data-testid="paper-card-primary-action"
                      onClick={() => {
                        setSelected(account);
                        setView('detail');
                      }}
                      className="inline-flex h-6 min-w-14 items-center justify-center rounded-full bg-blue-500/20 px-3 text-[10px] font-bold text-blue-200 transition-colors hover:bg-blue-500/30"
                    >
                      详情
                    </button>
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="grid min-w-0 grid-cols-2 items-end gap-2">
                    <div className="flex min-w-0 flex-col gap-1">
                      <span className="text-[10px] font-semibold text-gray-400">收益金额</span>
                      <div
                        className={clsx(
                          'whitespace-nowrap text-[clamp(0.8125rem,0.72vw,1rem)] font-bold tabular-nums leading-tight',
                          pnl >= 0 ? 'text-up' : 'text-down',
                        )}
                      >
                        {formatSignedCny(pnl)}
                      </div>
                    </div>
                    <div className="flex min-w-0 flex-col items-end gap-1 text-right">
                      <span className="text-[10px] font-semibold text-gray-400">收益率</span>
                      <div
                        className={clsx(
                          'whitespace-nowrap text-[clamp(0.8125rem,0.72vw,1rem)] font-bold tabular-nums leading-tight',
                          returnPct == null ? 'text-gray-500' : returnPct >= 0 ? 'text-up' : 'text-down',
                        )}
                      >
                        {formatSignedPercent(returnPct)}
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-2 text-center">
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
                      <div className="whitespace-nowrap text-xs font-bold tabular-nums text-blue-300">
                        {tradeCount}
                      </div>
                      <div className="mt-1 text-[10px] font-semibold text-gray-400">交易次数</div>
                    </div>
                  </div>
                </div>

                <div className="mt-auto" />
              </div>
            );
          })}
        </div>
      </div>

      {showCreateWizard && (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-6 backdrop-blur-sm">
          <section
            data-testid="paper-create-wizard"
            className="w-full max-w-7xl overflow-hidden rounded-xl border border-crypto-border bg-crypto-card shadow-2xl shadow-black/50"
          >
            <div className="flex items-start justify-between gap-4 border-b border-crypto-border px-5 py-4">
              <div>
                <div className="flex items-center gap-2 text-xs font-semibold text-gray-500">
                  <FlaskConical className="h-4 w-4 text-yellow-300" />
                  创建向导
                </div>
                <h2 className="mt-1 text-lg font-bold text-white">创建新模拟实例</h2>
              </div>
              <button
                type="button"
                onClick={closeCreateWizard}
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-crypto-border text-gray-500 transition-colors hover:text-white"
                aria-label="关闭创建向导"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="border-b border-crypto-border px-5 py-4">
              <div className="rounded-xl border border-crypto-border bg-crypto-bg px-6 py-4">
                <div className="grid grid-cols-[minmax(0,1fr)_88px_minmax(0,1fr)_88px_minmax(0,1fr)_88px_minmax(0,1fr)] items-center gap-3">
                  {wizardSteps.map((step, index) => {
                    const active = wizardStep === index;
                    const done = wizardStep > index;
                    return (
                      <div key={step.title} className="contents">
                        <div className="flex min-w-0 flex-col items-center text-center">
                          <div
                            className={clsx(
                              'flex h-10 w-10 items-center justify-center rounded-full border text-sm font-bold transition-colors',
                              active
                                ? 'border-blue-400 bg-blue-500/20 text-blue-100 shadow-[0_0_18px_rgba(59,130,246,0.35)]'
                                : done
                                  ? 'border-emerald-400/45 bg-emerald-500/15 text-emerald-200'
                                  : 'border-crypto-border bg-crypto-card text-gray-500',
                            )}
                          >
                            {done ? <CheckCircle2 className="h-5 w-5" /> : index + 1}
                          </div>
                          <div
                            data-testid={`paper-wizard-step-${index + 1}`}
                            className={clsx('mt-2 truncate text-xs font-semibold', active ? 'text-white' : 'text-gray-500')}
                          >
                            {step.title}
                          </div>
                          <div className="mt-0.5 truncate text-[10px] text-gray-600">{step.subtitle}</div>
                        </div>
                        {index < wizardSteps.length - 1 && <div className="h-px bg-crypto-border" />}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="min-h-[420px] px-5 py-5">
              {wizardStep === 0 && (
                <div>
                  <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
                    <div>
                      <h3 className="flex items-center gap-2 text-lg font-bold text-white">
                        <Rocket className="h-5 w-5 text-blue-400" />
                        选择交易策略
                      </h3>
                      <p className="mt-1 text-xs text-gray-500">仅显示可用于模拟的 A 股策略；运行中的策略不会重复创建同名模拟实例。</p>
                    </div>
                    <span className="rounded-full border border-blue-500/25 bg-blue-500/10 px-3 py-1 text-xs font-semibold text-blue-200">
                      {strategies.length} 个策略
                    </span>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {strategies.map((strategy) => {
                      const selectedStrategy = Number(strategyId) === strategy.id;
                      return (
                        <button
                          key={strategy.id}
                          type="button"
                          onClick={() => setStrategyId(strategy.id)}
                          className={clsx(
                            'min-h-24 rounded-xl border p-4 text-left transition-colors',
                            selectedStrategy
                              ? 'border-blue-500 bg-blue-500/10 shadow-[0_0_0_1px_rgba(59,130,246,0.22)]'
                              : 'border-crypto-border bg-crypto-bg hover:border-gray-600',
                          )}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className={clsx('truncate text-sm font-bold', selectedStrategy ? 'text-[#FFAB73]' : 'text-gray-100')}>
                                {strategy.name}
                              </div>
                              <p className="mt-2 line-clamp-2 text-xs leading-5 text-gray-500">{strategy.description || '暂无策略描述'}</p>
                            </div>
                            {selectedStrategy && <CheckCircle2 className="h-4 w-4 shrink-0 text-blue-300" />}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {wizardStep === 1 && (
                <div>
                  <div className="mb-4">
                    <h3 className="flex items-center gap-2 text-lg font-bold text-white">
                      <SlidersHorizontal className="h-5 w-5 text-purple-300" />
                      运行参数确认
                    </h3>
                    <p className="mt-1 text-xs text-gray-500">V1 复用 Backtrader 和 PaperBroker 资金口径，日线优先。</p>
                  </div>
                  <div className="grid gap-4 lg:grid-cols-3">
                    <label className="rounded-xl border border-crypto-border bg-crypto-bg p-4">
                      <span className="text-xs font-semibold text-gray-500">初始资金</span>
                      <input
                        type="number"
                        min={10000}
                        step={10000}
                        value={draftInitialCapital}
                        onChange={(event) => setDraftInitialCapital(Number(event.target.value) || 100000)}
                        className="mt-3 h-11 w-full rounded-lg border border-crypto-border bg-crypto-card px-3 text-sm font-bold text-white outline-none focus:border-blue-500"
                      />
                    </label>
                    <label className="rounded-xl border border-crypto-border bg-crypto-bg p-4">
                      <span className="text-xs font-semibold text-gray-500">单次仓位</span>
                      <input
                        type="number"
                        min={0.05}
                        max={1}
                        step={0.05}
                        value={draftPositionPct}
                        onChange={(event) => setDraftPositionPct(Number(event.target.value) || 0.3)}
                        className="mt-3 h-11 w-full rounded-lg border border-crypto-border bg-crypto-card px-3 text-sm font-bold text-white outline-none focus:border-blue-500"
                      />
                    </label>
                    <div className="rounded-xl border border-crypto-border bg-crypto-bg p-4">
                      <span className="text-xs font-semibold text-gray-500">标的池</span>
                      <div className="mt-3 flex h-11 items-center rounded-lg border border-blue-500/25 bg-blue-500/10 px-3 text-sm font-bold text-blue-200">
                        SH_600000 / SZ_000001
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {wizardStep === 2 && (
                <div>
                  <div className="mb-4">
                    <h3 className="flex items-center gap-2 text-lg font-bold text-white">
                      <ShieldCheck className="h-5 w-5 text-emerald-300" />
                      飞行检查
                    </h3>
                    <p className="mt-1 text-xs text-gray-500">模拟盘只写入 PaperBroker 账户，不触碰真实资金。</p>
                  </div>
                  <div className="grid gap-3 md:grid-cols-3">
                    {[
                      ['PaperBroker', '模拟成交账户已就绪'],
                      ['A股约束', '只做多 / 100 股一手 / T+1'],
                      ['PG 数据缓存', 'K线与策略结果写入 PostgreSQL'],
                    ].map(([title, subtitle]) => (
                      <div key={title} className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 p-4">
                        <div className="flex items-center gap-2 text-sm font-bold text-emerald-200">
                          <CheckCircle2 className="h-4 w-4" />
                          {title}
                        </div>
                        <div className="mt-2 text-xs text-emerald-100/70">{subtitle}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {wizardStep === 3 && (
                <div>
                  <div className="mb-4">
                    <h3 className="flex items-center gap-2 text-lg font-bold text-white">
                      <Activity className="h-5 w-5 text-blue-300" />
                      运行监控预览
                    </h3>
                    <p className="mt-1 text-xs text-gray-500">启动后进入实例详情页，查看权益曲线、成交事件和风控状态。</p>
                  </div>
                  <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
                    <div className="rounded-xl border border-blue-500/25 bg-blue-500/10 p-4">
                      <div className="text-xs font-semibold text-blue-200">即将启动</div>
                      <div className="mt-2 truncate text-lg font-bold text-white">{selectedStrategy?.name || 'A股模拟盘'}</div>
                      <div className="mt-3 grid gap-2 text-xs text-gray-300 sm:grid-cols-3">
                        <div className="rounded-lg bg-crypto-bg/70 p-3">
                          <div className="text-gray-500">初始资金</div>
                          <div className="mt-1 font-bold text-blue-200">¥{compactNumber(draftInitialCapital, 0)}</div>
                        </div>
                        <div className="rounded-lg bg-crypto-bg/70 p-3">
                          <div className="text-gray-500">单次仓位</div>
                          <div className="mt-1 font-bold text-purple-200">{Math.round(draftPositionPct * 100)}%</div>
                        </div>
                        <div className="rounded-lg bg-crypto-bg/70 p-3">
                          <div className="text-gray-500">周期</div>
                          <div className="mt-1 font-bold text-emerald-200">1D</div>
                        </div>
                      </div>
                    </div>
                    <div className="rounded-xl border border-crypto-border bg-crypto-bg p-4">
                      <div className="flex items-center gap-2 text-sm font-bold text-white">
                        <RefreshCw className="h-4 w-4 text-blue-300" />
                        启动后监控项
                      </div>
                      <div className="mt-3 space-y-2 text-xs text-gray-400">
                        {['账户权益和现金变化', '成交明细与系统事件', '买卖点 K 线复盘', '熔断、仓位和资金约束'].map((item) => (
                          <div key={item} className="flex items-center gap-2 rounded-lg bg-crypto-card/70 px-3 py-2">
                            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />
                            {item}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-crypto-border px-5 py-4">
              <button
                type="button"
                onClick={closeCreateWizard}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-crypto-border px-4 text-sm font-semibold text-gray-400 transition-colors hover:text-gray-200"
              >
                返回控制台
              </button>
              <div className="flex items-center gap-2">
                {wizardStep > 0 && (
                  <button
                    type="button"
                    onClick={() => setWizardStep((step) => Math.max(0, step - 1))}
                    className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-crypto-border px-4 text-sm font-semibold text-gray-300 transition-colors hover:text-white"
                  >
                    <ChevronLeft className="h-4 w-4" />
                    上一步
                  </button>
                )}
                {wizardStep < finalWizardStep ? (
                  <button
                    type="button"
                    onClick={() => setWizardStep((step) => Math.min(finalWizardStep, step + 1))}
                    disabled={!strategyId}
                    className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-blue-600 px-5 text-sm font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {nextWizardLabel}
                    <ChevronRight className="h-4 w-4" />
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={start}
                    disabled={loading || !strategyId}
                    className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-blue-600 px-5 text-sm font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {loading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
                    启动模拟实例
                  </button>
                )}
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

export default Paper;
