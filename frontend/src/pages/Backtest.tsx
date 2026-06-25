import { useEffect, useMemo, useState, type ReactNode } from 'react';
import clsx from 'clsx';
import {
  ArrowDown,
  ArrowDownUp,
  ArrowUp,
  CheckCircle2,
  Eye,
  FlaskConical,
  History,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from 'lucide-react';
import { getStrategies, listBacktestResults, runStrategyBacktest } from '../api/client';
import { AshareGuardrailStrip } from '../components/AshareGuardrailStrip';
import { BacktestDetailPanel } from '../components/BitProDetailPanels';
import { formatSymbolLabels } from '../utils/symbolDisplay';
import type { Strategy, StrategyBacktestResult } from '../types';

const format = (value?: number | null, digits = 2) =>
  value === null || value === undefined || Number.isNaN(value)
    ? '--'
    : Number(value).toLocaleString('zh-CN', {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
      });

const signedPct = (value?: number | null) =>
  value == null || !Number.isFinite(value) ? '--' : `${value >= 0 ? '+' : ''}${format(value)}%`;

const displayDateTime = (value?: string | null) => {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
};

type BacktestScopeFilter = 'all' | 'current';
type BacktestAssetFilter = 'all' | 'stock' | 'index';
type BacktestSortField = 'created' | 'return' | 'drawdown' | 'win_rate';
type BacktestSortDirection = 'asc' | 'desc';
type BacktestSortMode =
  | 'created_desc'
  | 'created_asc'
  | 'return_desc'
  | 'return_asc'
  | 'drawdown_desc'
  | 'drawdown_asc'
  | 'win_rate_desc'
  | 'win_rate_asc';

const backtestSymbolLabels = (result: StrategyBacktestResult) =>
  formatSymbolLabels(result.symbols || [], result.symbol_names || {});

function FilterPill({
  active,
  label,
  count,
  tone = 'blue',
  onClick,
}: {
  active?: boolean;
  label: string;
  count?: number;
  tone?: 'blue' | 'purple' | 'red';
  onClick?: () => void;
}) {
  const activeClass = {
    blue: 'border-blue-500/45 bg-blue-500/20 text-blue-300',
    purple: 'border-purple-500/45 bg-purple-500/20 text-purple-200',
    red: 'border-red-500/45 bg-red-500/15 text-red-300',
  }[tone];

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={clsx(
        'inline-flex h-10 min-w-20 items-center justify-center gap-2 rounded-lg border px-4 text-sm font-semibold transition-colors',
        active ? activeClass : 'border-transparent text-gray-500 hover:bg-white/[0.03] hover:text-gray-300',
      )}
    >
      {label}
      {count !== undefined ? <span className="rounded-md bg-crypto-bg px-1.5 py-0.5 text-xs">{count}</span> : null}
    </button>
  );
}

function sortDirectionFor(sortMode: BacktestSortMode, field: BacktestSortField): BacktestSortDirection | null {
  if (!sortMode.startsWith(field)) return null;
  return sortMode.endsWith('_asc') ? 'asc' : 'desc';
}

function nextSortMode(current: BacktestSortMode, field: BacktestSortField): BacktestSortMode {
  const direction = sortDirectionFor(current, field);
  return `${field}_${direction === 'desc' ? 'asc' : 'desc'}` as BacktestSortMode;
}

function SortArrow({ direction }: { direction: BacktestSortDirection | null }) {
  if (direction === 'asc') return <ArrowUp className="h-3.5 w-3.5" />;
  if (direction === 'desc') return <ArrowDown className="h-3.5 w-3.5" />;
  return <ArrowDownUp className="h-3.5 w-3.5 opacity-45" />;
}

function ModalField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-3 block text-sm font-medium text-gray-400">{label}</span>
      {children}
    </label>
  );
}

function WizardStep({
  active,
  done,
  index,
  title,
  desc,
}: {
  active?: boolean;
  done?: boolean;
  index: number;
  title: string;
  desc: string;
}) {
  return (
    <div className="relative z-10 flex flex-col items-center text-center">
      <div
        className={clsx(
          'flex h-16 w-16 items-center justify-center rounded-full border-[5px] text-xl font-bold transition-colors',
          active
            ? 'border-purple-500 bg-purple-500/20 text-white shadow-[0_0_28px_rgba(168,85,247,0.35)]'
            : done
              ? 'border-emerald-500/70 bg-emerald-500/15 text-emerald-200'
              : 'border-gray-700 bg-crypto-bg text-gray-600',
        )}
      >
        {done ? <CheckCircle2 className="h-6 w-6" /> : index}
      </div>
      <div className={clsx('mt-4 text-base font-bold', active ? 'text-white' : done ? 'text-emerald-200' : 'text-gray-500')}>
        {title}
      </div>
      <div className="mt-1.5 text-sm text-gray-500">{desc}</div>
    </div>
  );
}

export function Backtest() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [strategyId, setStrategyId] = useState<number | ''>('');
  const [symbols, setSymbols] = useState('SH_600000,SZ_000001');
  const [startDate, setStartDate] = useState('2026-01-01');
  const [endDate, setEndDate] = useState('2026-01-08');
  const [capital, setCapital] = useState(100000);
  const [commission, setCommission] = useState(0.0003);
  const [stampDuty, setStampDuty] = useState(0.001);
  const [slippage, setSlippage] = useState(0.0002);
  const [minCommission, setMinCommission] = useState(5);
  const [result, setResult] = useState<StrategyBacktestResult | null>(null);
  const [results, setResults] = useState<StrategyBacktestResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<'console' | 'detail'>('console');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createStep, setCreateStep] = useState<1 | 2 | 3>(1);
  const [scopeFilter, setScopeFilter] = useState<BacktestScopeFilter>('all');
  const [assetFilter, setAssetFilter] = useState<BacktestAssetFilter>('all');
  const [sortMode, setSortMode] = useState<BacktestSortMode>('created_desc');

  const load = async () => {
    const [data, history] = await Promise.all([
      getStrategies(),
      listBacktestResults().catch(() => ({ items: [], total: 0 })),
    ]);
    setStrategies(data);
    if (!strategyId && data[0]) setStrategyId(data[0].id);
    setResults(history.items || []);
    setResult((current) => current || history.items?.[0] || null);
  };

  useEffect(() => {
    void load();
  }, []);

  const run = async () => {
    if (!strategyId) return;
    setLoading(true);
    try {
      const data = await runStrategyBacktest(Number(strategyId), {
        symbols: symbols.split(',').map((item) => item.trim()).filter(Boolean),
        start_date: startDate,
        end_date: endDate,
        initial_capital: capital,
        position_pct: 0.9,
        commission,
        stamp_duty: stampDuty,
        slippage,
        min_commission: minCommission,
      });
      setResult(data);
      setResults((prev) => [data, ...prev.filter((item) => item.backtest_id !== data.backtest_id)]);
      setView('console');
      setShowCreateModal(false);
      setCreateStep(1);
    } finally {
      setLoading(false);
    }
  };

  const instances = useMemo(() => {
    if (!result) return results;
    const exists = results.some((item) => item.backtest_id === result.backtest_id && item.backtest_id != null);
    if (exists) {
      return results.map((item) => (item.backtest_id === result.backtest_id ? result : item));
    }
    return [result, ...results];
  }, [result, results]);

  const counts = useMemo(() => ({
    all: instances.length,
    current: strategyId ? instances.filter((item) => Number(item.strategy_id) === Number(strategyId)).length : 0,
    stock: instances.length,
    index: 0,
  }), [instances, strategyId]);

  const filteredInstances = useMemo(() => (
    instances
      .filter((item) => {
        if (scopeFilter === 'current' && Number(item.strategy_id) !== Number(strategyId)) return false;
        if (assetFilter === 'index') return false;
        return true;
      })
      .sort((a, b) => {
        const numeric = (field: BacktestSortField, item: StrategyBacktestResult) => {
          if (field === 'return') return Number(item.total_return ?? -Infinity);
          if (field === 'drawdown') return Number(item.max_drawdown ?? Infinity);
          if (field === 'win_rate') return Number(item.win_rate ?? -Infinity);
          return new Date(item.created_at || `${item.end_date}T00:00:00`).getTime();
        };
        const field = sortMode.split('_')[0] as BacktestSortField;
        const direction = sortMode.endsWith('_asc') ? 1 : -1;
        return (numeric(field, a) - numeric(field, b)) * direction;
      })
  ), [assetFilter, instances, scopeFilter, sortMode, strategyId]);

  if (view === 'detail' && result) {
    return (
      <div className="min-h-full bg-crypto-bg px-6 py-8">
        <BacktestDetailPanel result={result} onBack={() => setView('console')} />
      </div>
    );
  }

  return (
    <div className="min-h-full bg-crypto-bg px-6 py-8">
      <div className="mb-14 flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <div className="flex items-center gap-4">
            <FlaskConical className="h-8 w-8 text-purple-400" />
            <h1 className="text-[32px] font-bold leading-tight text-white">回测实例控制台</h1>
          </div>
          <p className="mt-3 text-lg text-gray-500">管理多个异步回测实例；创建任务后在历史中跟踪状态，打开详情查看绩效和成交。</p>
        </div>
        <button
          type="button"
          onClick={() => {
            setShowCreateModal(true);
            setCreateStep(1);
          }}
          disabled={loading || !strategyId}
          className="inline-flex h-16 items-center justify-center gap-4 rounded-2xl bg-purple-600 px-8 text-xl font-bold text-white shadow-[0_18px_40px_rgba(88,28,135,0.35)] transition-colors hover:bg-purple-500 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Plus className="h-6 w-6" />
          创建回测实例
        </button>
      </div>

      <div className="mb-6">
        <AshareGuardrailStrip
          title="A股回测约束"
          description="回测实例默认按 A 股日频交易规则解释信号，保证收益、回撤和成交明细可复盘。"
          items={[
            { label: '涨跌停 / 停牌', detail: '不可成交日期不应产生虚假买卖点。' },
            { label: '100股整数手', detail: '成交数量按一手取整，现金余量保留。' },
            { label: '佣金 / 印花税 / 滑点', detail: '成本项在创建向导中显式配置并写入实例。' },
          ]}
        />
      </div>

      <section className="overflow-hidden rounded-2xl border border-crypto-border bg-crypto-card">
        <div className="flex flex-wrap items-center justify-between gap-4 px-8 py-7">
          <div>
            <div className="flex items-center gap-3">
              <History className="h-6 w-6 text-blue-400" />
              <h2 className="text-2xl font-bold text-white">回测历史</h2>
              <span className="text-lg text-gray-500">{filteredInstances.length} / {instances.length} 条</span>
            </div>
            <p className="mt-3 text-base text-gray-500">查看已落库的回测摘要和成交记录</p>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <div className="inline-flex rounded-xl bg-crypto-bg p-1.5">
              <FilterPill active={scopeFilter === 'all'} label="全部" onClick={() => setScopeFilter('all')} />
              <FilterPill active={scopeFilter === 'current'} label="当前策略" onClick={() => setScopeFilter('current')} />
            </div>
            <div className="inline-flex rounded-xl bg-crypto-bg p-1.5">
              <FilterPill active={assetFilter === 'all'} label="全部" count={counts.all} onClick={() => setAssetFilter('all')} />
              <FilterPill active={assetFilter === 'stock'} label="A股" count={counts.stock} onClick={() => setAssetFilter('stock')} />
              <FilterPill active={assetFilter === 'index'} label="指数" count={counts.index} onClick={() => setAssetFilter('index')} />
            </div>
            <button
              type="button"
              className="inline-flex h-12 items-center gap-2 rounded-xl border border-red-500/35 bg-red-500/10 px-4 text-sm font-semibold text-red-300 opacity-70"
            >
              <Trash2 className="h-4 w-4" />
              批量删除
            </button>
            <button
              type="button"
              onClick={load}
              className="inline-flex h-12 items-center gap-2 rounded-xl border border-crypto-border bg-crypto-bg px-5 text-sm font-semibold text-gray-300 transition-colors hover:border-blue-500/50 hover:text-blue-300"
            >
              <RefreshCw className="h-4 w-4" />
              刷新
            </button>
          </div>
        </div>

        <div className="px-8 pb-8">
          <div className="overflow-x-auto">
            <table data-testid="backtest-history-table" className="w-full min-w-[980px] border-collapse text-sm 2xl:text-base">
              <thead>
                <tr className="border-b border-crypto-border text-sm text-gray-500">
                  <th className="w-12 py-5 text-left">
                    <input type="checkbox" className="h-5 w-5 rounded border-crypto-border bg-crypto-bg accent-blue-500" aria-label="选择全部回测" />
                  </th>
                  <th className="py-5 text-left font-semibold">策略</th>
                  <th className="py-5 text-left font-semibold">区间</th>
                  {([
                    ['return', '收益'],
                    ['drawdown', '回撤'],
                    ['win_rate', '胜率'],
                  ] as Array<[BacktestSortField, string]>).map(([field, label]) => (
                    <th key={field} className="py-5 text-right font-semibold">
                      <button
                        type="button"
                        onClick={() => setSortMode(nextSortMode(sortMode, field))}
                        className="ml-auto inline-flex items-center gap-1.5 text-gray-500 transition-colors hover:text-gray-300"
                      >
                        {label}
                        <SortArrow direction={sortDirectionFor(sortMode, field)} />
                      </button>
                    </th>
                  ))}
                  <th className="py-5 text-right font-semibold">交易</th>
                  <th className="py-5 text-left font-semibold">
                    <button
                      type="button"
                      onClick={() => setSortMode(nextSortMode(sortMode, 'created'))}
                      className="inline-flex items-center gap-1.5 text-blue-300"
                    >
                      回测时间
                      <SortArrow direction={sortDirectionFor(sortMode, 'created')} />
                    </button>
                  </th>
                  <th className="py-5 text-right font-semibold">操作</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={9} className="py-16 text-center text-gray-500">
                      <span className="inline-flex items-center gap-2">
                        <RefreshCw className="h-4 w-4 animate-spin text-purple-400" />
                        回测进行中，正在加载行情与初始化 Backtrader...
                      </span>
                    </td>
                  </tr>
                ) : null}
                {!loading && filteredInstances.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="py-16 text-center text-gray-500">暂无回测历史</td>
                  </tr>
                ) : null}
                {!loading && filteredInstances.map((instance) => {
                  const labels = backtestSymbolLabels(instance);
                  const firstLabel = labels[0] || instance.symbols?.[0] || '--';
                  const moreCount = Math.max(0, (instance.symbols || []).length - 1);
                  return (
                    <tr key={instance.backtest_id || `${instance.strategy_id}-${instance.created_at}`} className="border-b border-crypto-border/60 transition-colors hover:bg-white/[0.025]">
                      <td className="py-5">
                        <input type="checkbox" className="h-5 w-5 rounded border-crypto-border bg-crypto-bg accent-blue-500" aria-label={`选择 ${instance.strategy_name}`} />
                      </td>
                      <td className="py-5">
                        <div className="flex min-w-0 items-center gap-3">
                          <span className="rounded-md border border-purple-500/45 bg-purple-500/15 px-2.5 py-1 text-sm font-semibold text-purple-200">A股</span>
                          <div className="min-w-0">
                            <div className="truncate text-base font-bold text-[#FFAB73]">{instance.strategy_name}</div>
                            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                              <span>{firstLabel}</span>
                              {moreCount > 0 ? <span>+{moreCount}</span> : null}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="whitespace-nowrap py-5 text-gray-400">{instance.start_date} 至 {instance.end_date}</td>
                      <td className={clsx('py-5 text-right font-bold tabular-nums', instance.total_return >= 0 ? 'text-up' : 'text-down')}>
                        {signedPct(instance.total_return)}
                      </td>
                      <td className="py-5 text-right font-bold tabular-nums text-down">{format(instance.max_drawdown)}%</td>
                      <td className="py-5 text-right tabular-nums text-gray-300">{format(instance.win_rate)}%</td>
                      <td className="py-5 text-right font-semibold tabular-nums text-blue-300">{instance.total_trades}</td>
                      <td className="whitespace-nowrap py-5 text-gray-500">{displayDateTime(instance.created_at)}</td>
                      <td className="py-5">
                        <div className="flex justify-end gap-3">
                          <button
                            type="button"
                            onClick={() => {
                              setResult(instance);
                              setView('detail');
                            }}
                            className="inline-flex h-10 items-center gap-2 rounded-xl border border-blue-500/45 bg-blue-500/10 px-3 text-sm font-semibold text-blue-300 transition-colors hover:bg-blue-500/20"
                          >
                            <Eye className="h-4 w-4" />
                            查看
                          </button>
                          <button
                            type="button"
                            className="inline-flex h-10 items-center gap-2 rounded-xl border border-red-500/45 bg-red-500/10 px-3 text-sm font-semibold text-red-300 opacity-70"
                          >
                            <Trash2 className="h-4 w-4" />
                            删除历史
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/75 p-6 backdrop-blur-[7px]">
          <section className="mb-2 max-h-[82vh] w-full max-w-[1120px] overflow-hidden rounded-[22px] border border-crypto-border bg-crypto-card shadow-2xl shadow-black/70">
            <div className="flex items-start justify-between gap-4 border-b border-crypto-border px-8 py-5">
              <div>
                <h2 className="flex items-center gap-3 text-2xl font-bold text-white">
                  <FlaskConical className="h-7 w-7 text-purple-400" />
                  创建回测实例
                </h2>
                <p className="mt-3 text-base text-gray-500">选择策略、设置区间和成本，提交后生成独立回测实例并异步运行。</p>
              </div>
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="inline-flex h-12 w-12 items-center justify-center rounded-xl border border-crypto-border text-gray-500 transition-colors hover:text-gray-300"
                aria-label="关闭回测创建"
              >
                <X className="h-6 w-6" />
              </button>
            </div>

            <div className="relative mx-8 my-5 rounded-2xl border border-crypto-border px-10 py-6">
              <div className="absolute left-[18%] right-[18%] top-[3.95rem] h-px bg-crypto-border" />
              <div className="grid grid-cols-3 gap-8">
                <WizardStep index={1} title="选择策略" desc="策略与资金模式" active={createStep === 1} done={createStep > 1} />
                <WizardStep index={2} title="配置参数" desc="区间、资金与成本" active={createStep === 2} done={createStep > 2} />
                <WizardStep index={3} title="执行回测" desc="确认并启动回测" active={createStep === 3} />
              </div>
            </div>

            <div className="max-h-[calc(82vh-300px)] overflow-y-auto border-t border-crypto-border px-8 py-5">
              {createStep === 1 && (
                <div className="space-y-5">
                  <ModalField label="选择策略">
                    <select value={strategyId} onChange={(event) => setStrategyId(Number(event.target.value))} className="h-16 w-full rounded-xl border border-crypto-border bg-crypto-bg px-5 text-xl text-white outline-none focus:border-purple-500">
                      {strategies.map((item) => (
                        <option key={item.id} value={item.id}>{item.name}</option>
                      ))}
                    </select>
                  </ModalField>
                  <div className="text-sm leading-6 text-gray-500">
                    {strategies.find((item) => Number(item.id) === Number(strategyId))?.description || '请选择可回测策略'}
                  </div>
                </div>
              )}

              {createStep === 2 && (
                <div className="space-y-6">
                  <div className="grid gap-5 md:grid-cols-2">
                    <ModalField label="股票池">
                      <input value={symbols} onChange={(event) => setSymbols(event.target.value)} className="h-14 w-full rounded-xl border border-crypto-border bg-crypto-bg px-4 text-base text-white outline-none focus:border-purple-500" />
                    </ModalField>
                    <ModalField label="初始资金">
                      <input type="number" value={capital} onChange={(event) => setCapital(Number(event.target.value))} className="h-14 w-full rounded-xl border border-crypto-border bg-crypto-bg px-4 text-base text-white outline-none focus:border-purple-500" />
                    </ModalField>
                    <ModalField label="开始日期">
                      <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} className="h-14 w-full rounded-xl border border-crypto-border bg-crypto-bg px-4 text-base text-white outline-none focus:border-purple-500" />
                    </ModalField>
                    <ModalField label="结束日期">
                      <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} className="h-14 w-full rounded-xl border border-crypto-border bg-crypto-bg px-4 text-base text-white outline-none focus:border-purple-500" />
                    </ModalField>
                  </div>
                  <div className="grid gap-5 md:grid-cols-4">
                    <ModalField label="佣金">
                      <input type="number" step="0.0001" value={commission} onChange={(event) => setCommission(Number(event.target.value))} className="h-12 w-full rounded-xl border border-crypto-border bg-crypto-bg px-4 text-base text-white outline-none focus:border-purple-500" />
                    </ModalField>
                    <ModalField label="印花税">
                      <input type="number" step="0.0001" value={stampDuty} onChange={(event) => setStampDuty(Number(event.target.value))} className="h-12 w-full rounded-xl border border-crypto-border bg-crypto-bg px-4 text-base text-white outline-none focus:border-purple-500" />
                    </ModalField>
                    <ModalField label="滑点">
                      <input type="number" step="0.0001" value={slippage} onChange={(event) => setSlippage(Number(event.target.value))} className="h-12 w-full rounded-xl border border-crypto-border bg-crypto-bg px-4 text-base text-white outline-none focus:border-purple-500" />
                    </ModalField>
                    <ModalField label="最低佣金">
                      <input type="number" value={minCommission} onChange={(event) => setMinCommission(Number(event.target.value))} className="h-12 w-full rounded-xl border border-crypto-border bg-crypto-bg px-4 text-base text-white outline-none focus:border-purple-500" />
                    </ModalField>
                  </div>
                </div>
              )}

              {createStep === 3 && (
                <div className="grid gap-3 text-sm md:grid-cols-2">
                  <div className="flex justify-between gap-4 rounded-lg bg-crypto-bg px-4 py-3"><span className="text-gray-500">策略</span><span className="truncate text-[#FFAB73]">{strategies.find((item) => Number(item.id) === Number(strategyId))?.name || '--'}</span></div>
                  <div className="flex justify-between gap-4 rounded-lg bg-crypto-bg px-4 py-3"><span className="text-gray-500">股票池</span><span className="text-gray-200">{symbols}</span></div>
                  <div className="flex justify-between gap-4 rounded-lg bg-crypto-bg px-4 py-3"><span className="text-gray-500">区间</span><span className="text-gray-200">{startDate} 至 {endDate}</span></div>
                  <div className="flex justify-between gap-4 rounded-lg bg-crypto-bg px-4 py-3"><span className="text-gray-500">初始资金</span><span className="text-gray-200">¥{format(capital, 0)}</span></div>
                  <div className="flex justify-between gap-4 rounded-lg bg-crypto-bg px-4 py-3"><span className="text-gray-500">成本</span><span className="text-gray-200">佣金 {commission} · 印花税 {stampDuty}</span></div>
                  <div className="flex justify-between gap-4 rounded-lg bg-crypto-bg px-4 py-3"><span className="text-gray-500">执行约束</span><span className="text-gray-200">只做多 · 100股一手 · T+1</span></div>
                </div>
              )}
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-crypto-border px-8 py-4">
              <button type="button" onClick={() => setShowCreateModal(false)} className="h-12 rounded-xl border border-crypto-border px-6 text-lg font-bold text-gray-400 hover:text-gray-200">取消</button>
              <div className="flex gap-3">
                {createStep > 1 && (
                  <button type="button" onClick={() => setCreateStep((step) => Math.max(1, step - 1) as 1 | 2 | 3)} className="rounded-xl border border-crypto-border px-6 py-3 text-lg font-bold text-gray-300 hover:text-white">上一步</button>
                )}
                {createStep < 3 ? (
                  <button type="button" onClick={() => setCreateStep((step) => Math.min(3, step + 1) as 1 | 2 | 3)} className="rounded-xl bg-purple-600 px-8 py-3 text-lg font-bold text-white hover:bg-purple-500">下一步</button>
                ) : (
                  <button
                    type="button"
                    onClick={run}
                    disabled={loading || !strategyId}
                    className="inline-flex items-center gap-2 rounded-xl bg-purple-600 px-8 py-3 text-lg font-bold text-white hover:bg-purple-500 disabled:cursor-not-allowed disabled:bg-gray-700 disabled:text-gray-500"
                  >
                    <Play className="h-5 w-5" />
                    开始回测
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

export default Backtest;
