import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import ReactECharts from 'echarts-for-react';
import {
  ArrowLeft,
  BarChart3,
  Beaker,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  Eye,
  FileText,
  FlaskConical,
  GitCompareArrows,
  Layers3,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  X,
  Zap,
} from 'lucide-react';
import {
  compareBacktestRuns,
  createBacktestExperiment,
  getBacktestConfiguration,
  getBacktestEvidence,
  getBacktestMetrics,
  getBacktestRun,
  getBacktestSeries,
  listBacktestRuns,
  runBacktestMatrix,
  runBacktestV1,
} from '../api/client';
import type {
  BacktestConfiguration,
  BacktestDailyPoint,
  BacktestMetric,
  BacktestRun,
  BacktestRunRequestV1,
} from '../types';

const panel = 'rounded-2xl border border-crypto-border bg-crypto-card';
const input = 'h-11 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-gray-200 outline-none transition focus:border-blue-500/70';

const metricLabels: Record<string, string> = {
  strategy_return: '策略收益', annualized_return: '年化收益', benchmark_return: '基准收益', excess_return: '超额收益',
  maximum_drawdown: '最大回撤', sharpe: '夏普比率', sortino: '索提诺比率', alpha: 'Alpha', beta: 'Beta',
  information_ratio: '信息比率', annualized_volatility: '年化波动', downside_volatility: '下行波动',
  win_rate: '交易胜率', profit_loss_ratio: '盈亏比', daily_win_rate: '日胜率', fill_rate: '成交率', rejection_rate: '拒单率',
  turnover: '换手率', total_cost: '总成本', total_commission: '佣金', total_tax: '印花税', total_transfer_fee: '过户费',
  total_slippage_cost: '滑点成本', average_holding_days: '平均持有天数', average_exposure: '平均敞口',
  peak_single_symbol_weight: '单票最高权重', capacity_warnings: '容量警告', data_quality_warnings: '数据质量警告',
};

function formatValue(value: number | null | undefined, unit = 'number') {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--';
  if (unit === 'ratio' || unit === 'ratio_per_year') return `${(Number(value) * 100).toFixed(2)}%`;
  if (unit === 'CNY') return `¥${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
  if (unit === 'count') return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 });
  if (unit === 'days') return `${Number(value).toFixed(1)} 天`;
  return Number(value).toFixed(3);
}

function StatusBadge({ run }: { run: BacktestRun }) {
  const success = run.status === 'success';
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${success ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : run.status === 'failed' ? 'border-red-500/30 bg-red-500/10 text-red-300' : 'border-amber-500/30 bg-amber-500/10 text-amber-300'}`}>
      {success ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Clock3 className="h-3.5 w-3.5" />}
      {run.run_mode === 'quick' ? '快速预检' : '完整回测'} · {run.status}
      {run.data_purpose !== 'user' && run.data_purpose
        ? ` · ${run.data_purpose === 'acceptance' ? '验收数据' : '种子数据'}`
        : ''}
    </span>
  );
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return <label className="block"><span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-gray-500">{label}</span>{children}{hint ? <span className="mt-1.5 block text-xs text-gray-600">{hint}</span> : null}</label>;
}

function GenericTable({ rows, columns }: { rows: Array<Record<string, unknown>>; columns: Array<[string, string]> }) {
  if (!rows.length) return <div className="flex min-h-48 items-center justify-center text-sm text-gray-600">暂无记录</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-left text-sm">
        <thead><tr className="border-b border-crypto-border text-xs uppercase tracking-wider text-gray-500">{columns.map(([key, label]) => <th key={key} className="px-4 py-3 font-semibold">{label}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={String(row.id ?? `${index}`)} className="border-b border-white/[0.04] text-gray-300 hover:bg-white/[0.02]">{columns.map(([key]) => <td key={key} className="max-w-[360px] px-4 py-3 font-mono text-xs"><span className="line-clamp-2">{typeof row[key] === 'object' ? JSON.stringify(row[key]) : String(row[key] ?? '--')}</span></td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

type DetailData = {
  run: BacktestRun;
  metrics: BacktestMetric[];
  daily: BacktestDailyPoint[];
  monthly: Array<{ month: string; return: number | null }>;
  custom: Array<Record<string, unknown>>;
  positions: Array<Record<string, unknown>>;
  orders: Array<Record<string, unknown>>;
  trades: Array<Record<string, unknown>>;
  logs: Array<Record<string, unknown>>;
  attribution: Array<Record<string, unknown>>;
};

const detailTabs = ['总览', '收益分析', '持仓', '交易', '订单', '日志', '代码与参数', '归因'] as const;

function BacktestDetail({ runId }: { runId: string }) {
  const navigate = useNavigate();
  const [data, setData] = useState<DetailData | null>(null);
  const [tab, setTab] = useState<(typeof detailTabs)[number]>('总览');
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    Promise.all([
      getBacktestRun(runId), getBacktestMetrics(runId), getBacktestSeries(runId),
      getBacktestEvidence(runId, 'positions'), getBacktestEvidence(runId, 'orders'), getBacktestEvidence(runId, 'trades'),
      getBacktestEvidence(runId, 'logs'), getBacktestEvidence(runId, 'attribution'),
    ]).then(([run, metrics, series, positions, orders, trades, logs, attribution]) => {
      if (live) setData({ run, metrics, daily: series.daily, monthly: series.monthly_returns, custom: series.custom_records, positions, orders, trades, logs, attribution });
    }).catch((reason: unknown) => live && setError(reason instanceof Error ? reason.message : '回测证据加载失败'));
    return () => { live = false; };
  }, [runId]);

  const metricMap = useMemo(() => Object.fromEntries((data?.metrics ?? []).map((item) => [item.metric_code, item])), [data]);
  const chartOption = useMemo(() => ({
    backgroundColor: 'transparent',
    animation: false,
    tooltip: { trigger: 'axis', backgroundColor: '#111827', borderColor: '#334155', textStyle: { color: '#e5e7eb' } },
    legend: { top: 4, textStyle: { color: '#94a3b8' }, data: ['策略净值', '基准净值', '超额净值'] },
    grid: { left: 50, right: 24, top: 48, bottom: 34 },
    xAxis: { type: 'category', data: (data?.daily ?? []).map((item) => item.trade_date), axisLabel: { color: '#64748b' }, axisLine: { lineStyle: { color: '#334155' } } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: 'rgba(51,65,85,.45)' } } },
    series: [
      { name: '策略净值', type: 'line', showSymbol: false, data: (data?.daily ?? []).map((item) => item.strategy_nav), lineStyle: { width: 2, color: '#3b82f6' } },
      { name: '基准净值', type: 'line', showSymbol: false, data: (data?.daily ?? []).map((item) => item.benchmark_nav), lineStyle: { width: 1.5, color: '#94a3b8' } },
      { name: '超额净值', type: 'line', showSymbol: false, data: (data?.daily ?? []).map((item) => item.excess_nav), lineStyle: { width: 1.5, color: '#a855f7' } },
    ],
  }), [data]);

  if (error) return <div className="p-8 text-red-300">{error}</div>;
  if (!data) return <div className="flex min-h-[60vh] items-center justify-center text-gray-500"><RefreshCw className="mr-3 h-5 w-5 animate-spin" />正在读取封存结果…</div>;
  const core = ['strategy_return', 'annualized_return', 'benchmark_return', 'excess_return', 'maximum_drawdown', 'sharpe'];

  return (
    <div className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <button type="button" onClick={() => navigate('/backtest')} className="mb-4 inline-flex items-center gap-2 text-sm text-gray-500 hover:text-blue-300"><ArrowLeft className="h-4 w-4" />返回回测工作台</button>
          <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-bold text-white">{data.run.name}</h1><StatusBadge run={data.run} /></div>
          <p className="mt-2 text-sm text-gray-500">{data.run.start_date} — {data.run.end_date} · {data.run.strategy_name} v{data.run.strategy_version} · ID {data.run.id}</p>
        </div>
      </div>

      <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        {core.map((code) => { const item = metricMap[code]; return <div key={code} className={`${panel} p-4`}><div className="text-xs text-gray-500">{metricLabels[code]}</div><div className={`mt-2 text-xl font-bold ${code === 'maximum_drawdown' ? 'text-red-300' : 'text-white'}`}>{formatValue(item?.metric_value, item?.unit)}</div>{item?.metric_value == null ? <div className="mt-2 text-[11px] text-amber-500/80">{item?.null_reason ?? '未定义'}</div> : <div className="mt-2 text-[11px] text-gray-600">{item.calculation_version}</div>}</div>; })}
      </div>

      <div className={`${panel} mb-5 flex overflow-x-auto px-2`} role="tablist">
        {detailTabs.map((item) => <button key={item} type="button" role="tab" aria-selected={tab === item} onClick={() => setTab(item)} className={`whitespace-nowrap border-b-2 px-5 py-4 text-sm font-semibold ${tab === item ? 'border-blue-500 text-blue-300' : 'border-transparent text-gray-500 hover:text-gray-300'}`}>{item}</button>)}
      </div>

      {tab === '总览' && <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <section className={`${panel} p-5`}><div className="mb-3 flex items-center gap-2 text-base font-semibold text-white"><BarChart3 className="h-5 w-5 text-blue-400" />净值与基准</div><ReactECharts option={chartOption} style={{ height: 420 }} /></section>
        <section className={`${panel} p-5`}><h2 className="text-base font-semibold text-white">可复现实验凭证</h2><dl className="mt-5 space-y-4 text-sm">{[
          ['数据快照', `#${data.run.dataset_snapshot_id}`], ['Universe', `#${data.run.universe_snapshot_id}`], ['因子快照', data.run.factor_snapshot_id ? `#${data.run.factor_snapshot_id}` : '未绑定'], ['成本模型', data.run.cost_model_name ?? data.run.cost_model_id], ['研究协议', data.run.protocol_name ?? '未绑定'], ['基准', data.run.benchmark_code], ['频率', '1d / A股收盘信号次日成交'],
        ].map(([label, value]) => <div key={label} className="flex items-start justify-between gap-4 border-b border-white/[0.04] pb-3"><dt className="text-gray-500">{label}</dt><dd className="text-right font-medium text-gray-300">{value}</dd></div>)}</dl></section>
        <section className={`${panel} p-5 xl:col-span-2`}><h2 className="mb-4 text-base font-semibold text-white">月度收益</h2><div className="grid grid-cols-3 gap-2 sm:grid-cols-6 xl:grid-cols-12">{data.monthly.map((item) => <div key={item.month} className="rounded-lg border border-crypto-border bg-crypto-bg p-3 text-center"><div className="text-xs text-gray-500">{item.month}</div><div className={`mt-1 text-sm font-semibold ${item.return === null || item.return === undefined ? 'text-gray-500' : item.return >= 0 ? 'text-emerald-300' : 'text-red-300'}`}>{formatValue(item.return, 'ratio')}</div></div>)}</div></section>
      </div>}

      {tab === '收益分析' && <section className={`${panel} overflow-hidden`}><GenericTable rows={data.metrics as unknown as Array<Record<string, unknown>>} columns={[["metric_code", "指标"], ["metric_value", "数值"], ["unit", "单位"], ["calculation_version", "计算版本"], ["input_frequency", "频率"], ["null_reason", "未定义原因"]]} /></section>}
      {tab === '持仓' && <section className={panel}><GenericTable rows={data.positions} columns={[["trade_date", "日期"], ["symbol", "证券"], ["quantity", "数量"], ["available_quantity", "可卖"], ["avg_cost", "成本"], ["close_price", "收盘"], ["market_value", "市值"], ["weight", "权重"]]} /></section>}
      {tab === '交易' && <section className={panel}><GenericTable rows={data.trades} columns={[["trade_date", "日期"], ["symbol", "证券"], ["side", "方向"], ["price", "价格"], ["quantity", "数量"], ["amount", "金额"], ["commission", "佣金"], ["tax", "税费"], ["realized_pnl", "已实现盈亏"]]} /></section>}
      {tab === '订单' && <section className={panel}><GenericTable rows={data.orders} columns={[["signal_at", "信号时间"], ["earliest_fill_at", "最早成交"], ["filled_at", "成交时间"], ["symbol", "证券"], ["intent_type", "意图"], ["status", "状态"], ["filled_quantity", "成交数量"], ["rejection_code", "拒单代码"]]} /></section>}
      {tab === '日志' && <section className={panel}><GenericTable rows={data.logs} columns={[["simulated_at", "模拟时间"], ["level", "级别"], ["source", "来源"], ["message", "消息"], ["payload", "上下文"]]} /></section>}
      {tab === '代码与参数' && <div className="grid gap-5 xl:grid-cols-[2fr_1fr]"><section className={`${panel} overflow-hidden`}><div className="border-b border-crypto-border px-5 py-4 text-sm font-semibold text-white">策略代码 · v{data.run.strategy_version}</div><pre className="max-h-[620px] overflow-auto p-5 text-xs leading-6 text-blue-100"><code>{data.run.script_content}</code></pre></section><section className={`${panel} p-5`}><h2 className="text-sm font-semibold text-white">运行参数</h2><pre className="mt-4 overflow-auto rounded-lg bg-crypto-bg p-4 text-xs leading-6 text-gray-300">{JSON.stringify(data.run.parameters, null, 2)}</pre><h2 className="mt-6 text-sm font-semibold text-white">自定义指标</h2><pre className="mt-4 max-h-72 overflow-auto rounded-lg bg-crypto-bg p-4 text-xs leading-6 text-gray-300">{JSON.stringify(data.custom, null, 2)}</pre></section></div>}
      {tab === '归因' && <section className={panel}><GenericTable rows={data.attribution} columns={[["attribution_type", "类型"], ["attribution_key", "归因项"], ["contribution", "贡献"], ["amount", "金额"], ["payload", "证据"]]} /></section>}
    </div>
  );
}

export function Backtest() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [config, setConfig] = useState<BacktestConfiguration | null>(null);
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [createStep, setCreateStep] = useState<1 | 2 | 3>(1);
  const [strategyQuery, setStrategyQuery] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [compareData, setCompareData] = useState<{ runs: BacktestRun[]; series: Record<string, BacktestDailyPoint[]> } | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [strategyVersionId, setStrategyVersionId] = useState('');
  const [datasetSnapshotId, setDatasetSnapshotId] = useState(0);
  const [universeSnapshotId, setUniverseSnapshotId] = useState(0);
  const [factorSnapshotId, setFactorSnapshotId] = useState(0);
  const [poolSnapshotId, setPoolSnapshotId] = useState(0);
  const [costModelId, setCostModelId] = useState('');
  const [protocolId, setProtocolId] = useState('');
  const [symbols, setSymbols] = useState('SH_600519');
  const [startDate, setStartDate] = useState('2024-01-02');
  const [endDate, setEndDate] = useState('2025-01-02');
  const [initialCash, setInitialCash] = useState(1_000_000);
  const [parameters, setParameters] = useState('{}');
  const [grid, setGrid] = useState('{"lookback":[5,10,20],"target":[0.3,0.6]}');
  const [historyQuery, setHistoryQuery] = useState('');
  const [historyStatus, setHistoryStatus] = useState<'all' | BacktestRun['status']>('all');
  const [historyMode, setHistoryMode] = useState<'all' | BacktestRun['run_mode']>('all');
  const [historySort, setHistorySort] = useState<'created' | 'return' | 'drawdown' | 'sharpe'>('created');

  const load = useCallback(async () => {
    setError('');
    try {
      const [configuration, history] = await Promise.all([getBacktestConfiguration(), listBacktestRuns()]);
      setConfig(configuration); setRuns(history.items);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '回测配置加载失败'); }
  }, []);

  useEffect(() => { if (!runId) void load(); }, [load, runId]);
  useEffect(() => {
    if (!config) return;
    if (!strategyVersionId) setStrategyVersionId(config.strategy_versions[0]?.id ?? '');
    if (!datasetSnapshotId && config.dataset_snapshots[0]) setDatasetSnapshotId(config.dataset_snapshots[0].id);
    if (!universeSnapshotId) setUniverseSnapshotId(config.universe_snapshots[0]?.id ?? 0);
    if (!costModelId) setCostModelId(config.cost_models[0]?.id ?? '');
  }, [config, costModelId, datasetSnapshotId, strategyVersionId, universeSnapshotId]);
  useEffect(() => {
    if (!config) return;
    const match = config.factor_snapshots.find((item) => item.dataset_snapshot_id === datasetSnapshotId && item.universe_snapshot_id === universeSnapshotId);
    setFactorSnapshotId(match?.id ?? 0);
    const snapshot = config.dataset_snapshots.find((item) => item.id === datasetSnapshotId);
    if (snapshot) { setStartDate(snapshot.start_date); setEndDate(snapshot.end_date); }
  }, [config, datasetSnapshotId, universeSnapshotId]);
  useEffect(() => {
    if (!config) return;
    const requested = Number(searchParams.get('poolSnapshotId') || 0);
    if (!requested) return;
    const pool = config.pool_snapshots.find((item) => item.id === requested);
    if (!pool) return;
    setPoolSnapshotId(pool.id); setDatasetSnapshotId(pool.dataset_snapshot_id); setUniverseSnapshotId(pool.universe_snapshot_id);
    setFactorSnapshotId(pool.factor_snapshot_id ?? 0); setSymbols('');
  }, [config, searchParams]);

  const visibleRuns = useMemo(() => {
    const query = historyQuery.trim().toLowerCase();
    const metric = (run: BacktestRun, code: string) => run.metrics?.[code];
    return runs.filter((run) => {
      if (historyStatus !== 'all' && run.status !== historyStatus) return false;
      if (historyMode !== 'all' && run.run_mode !== historyMode) return false;
      return !query || `${run.name} ${run.strategy_name ?? ''} ${run.id}`.toLowerCase().includes(query);
    }).sort((a, b) => {
      if (historySort === 'created') return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      if (historySort === 'return') return Number(metric(b, 'strategy_return') ?? -Infinity) - Number(metric(a, 'strategy_return') ?? -Infinity);
      if (historySort === 'drawdown') return Number(metric(b, 'maximum_drawdown') ?? -Infinity) - Number(metric(a, 'maximum_drawdown') ?? -Infinity);
      return Number(metric(b, 'sharpe') ?? -Infinity) - Number(metric(a, 'sharpe') ?? -Infinity);
    });
  }, [historyMode, historyQuery, historySort, historyStatus, runs]);
  const statusCounts = useMemo(() => ({
    all: runs.length,
    success: runs.filter((run) => run.status === 'success').length,
    running: runs.filter((run) => run.status === 'running').length,
    failed: runs.filter((run) => run.status === 'failed').length,
  }), [runs]);
  const modeCounts = useMemo(() => ({
    all: runs.length,
    full: runs.filter((run) => run.run_mode === 'full').length,
    quick: runs.filter((run) => run.run_mode === 'quick').length,
  }), [runs]);
  const strategyOptions = useMemo(() => {
    const query = strategyQuery.trim().toLowerCase();
    return (config?.strategy_versions ?? []).filter((item) =>
      !query || `${item.name} ${item.description ?? ''} v${item.version}`.toLowerCase().includes(query));
  }, [config?.strategy_versions, strategyQuery]);

  if (runId) return <BacktestDetail runId={runId} />;

  if (!config) return <div className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8"><header className="mb-6 flex flex-wrap items-start justify-between gap-4"><div><div className="flex items-center gap-3"><FlaskConical className="h-7 w-7 text-blue-400" /><h1 className="text-2xl font-bold text-white">研究回测工作台</h1></div><p className="mt-2 text-sm text-gray-500">A股策略回测 · T+1 撮合 · 成本与风险证据</p></div></header>{error ? <div className="rounded-xl border border-red-500/25 bg-red-500/10 p-5 text-sm text-red-200"><div className="flex items-start gap-3"><CircleAlert className="mt-0.5 h-4 w-4 shrink-0" /><span><strong>配置加载失败：</strong>{error}</span></div><button type="button" onClick={() => void load()} className="mt-4 inline-flex h-9 items-center gap-2 rounded-lg border border-red-400/30 px-3 text-xs font-semibold"><RefreshCw className="h-3.5 w-3.5" />重试</button></div> : <div className={`${panel} flex min-h-[360px] items-center justify-center text-sm text-gray-500`}><RefreshCw className="mr-3 h-5 w-5 animate-spin" />正在读取策略版本、数据快照与回测记录…</div>}</div>;

  const request = (): BacktestRunRequestV1 => ({
    strategy_version_id: strategyVersionId, dataset_snapshot_id: datasetSnapshotId, universe_snapshot_id: universeSnapshotId,
    factor_snapshot_id: factorSnapshotId || null, cost_model_id: costModelId, research_protocol_id: protocolId || null,
    pool_snapshot_id: poolSnapshotId || null,
    symbols: poolSnapshotId ? [] : symbols.split(',').map((item) => item.trim().toUpperCase()).filter(Boolean), start_date: startDate, end_date: endDate,
    initial_cash: initialCash, benchmark_code: '000300.SH', parameters: JSON.parse(parameters || '{}') as Record<string, unknown>, event_limit: 30,
  });

  const execute = async (mode: 'quick' | 'full') => {
    setBusy(mode); setError('');
    try { const result = await runBacktestV1(request(), mode); await load(); navigate(`/backtest/${result.id}`); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '回测运行失败'); }
    finally { setBusy(''); }
  };

  const compare = async () => {
    setBusy('compare'); setError('');
    try { setCompareData(await compareBacktestRuns(selected)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '对比失败'); }
    finally { setBusy(''); }
  };

  const runMatrix = async () => {
    setBusy('matrix'); setError('');
    try {
      const base = request();
      const experiment = await createBacktestExperiment({ ...base, hypothesis: '参数稳定性与容量敏感性检验' });
      await runBacktestMatrix(String(experiment.id), { parameter_grid: JSON.parse(grid) as Record<string, unknown[]>, start_date: base.start_date, end_date: base.end_date, initial_cash: base.initial_cash, symbols: base.symbols, event_limit: 30 });
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '参数矩阵运行失败'); }
    finally { setBusy(''); }
  };

  const selectedVersion = config?.strategy_versions.find((item) => item.id === strategyVersionId);
  const runMetric = (run: BacktestRun, code: string) => run.metrics?.[code] ?? null;
  const selectedDataset = config?.dataset_snapshots.find((item) => item.id === datasetSnapshotId);
  const selectedUniverse = config?.universe_snapshots.find((item) => item.id === universeSnapshotId);
  const selectedCostModel = config?.cost_models.find((item) => item.id === costModelId);
  const selectedProtocol = config?.protocols.find((item) => item.id === protocolId);
  const selectedPool = config?.pool_snapshots.find((item) => item.id === poolSnapshotId);
  const tradeCount = (run: BacktestRun) =>
    runMetric(run, 'completed_trades') ?? runMetric(run, 'total_trades');
  const openCreate = () => {
    setCreateStep(1);
    setStrategyQuery('');
    setError('');
    setCreateOpen(true);
  };
  const closeCreate = () => {
    if (!busy) setCreateOpen(false);
  };
  const executeFromWizard = async (mode: 'quick' | 'full') => {
    await execute(mode);
    setCreateOpen(false);
  };

  return (
    <div className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <FlaskConical className="h-7 w-7 text-purple-400" />
            <h1 className="text-2xl font-bold text-white">回测实例控制台</h1>
          </div>
          <p className="mt-2 text-sm text-gray-500">管理多个 A 股回测实例，创建任务后跟踪状态，打开详情查看绩效与成交证据。</p>
        </div>
        <button type="button" onClick={openCreate} className="inline-flex h-11 items-center gap-2 rounded-xl bg-purple-600 px-5 text-sm font-semibold text-white shadow-lg shadow-purple-950/30 transition hover:bg-purple-500">
          <Plus className="h-4 w-4" />创建回测实例
        </button>
      </header>

      {error ? <div className="mb-5 flex items-start gap-3 rounded-xl border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200"><CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />{error}</div> : null}

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="flex rounded-xl border border-crypto-border bg-crypto-card p-1">
          {([
            ['all', '全部', modeCounts.all],
            ['full', '完整回测', modeCounts.full],
            ['quick', '快速预检', modeCounts.quick],
          ] as const).map(([value, label, count]) => (
            <button key={value} type="button" onClick={() => setHistoryMode(value)} className={`flex h-9 items-center gap-2 rounded-lg px-3 text-xs font-semibold transition ${historyMode === value ? 'bg-blue-500/20 text-blue-200' : 'text-gray-500 hover:text-gray-300'}`}>
              {label}<span className="rounded bg-black/25 px-1.5 py-0.5 text-[10px]">{count}</span>
            </button>
          ))}
        </div>
        <div className="flex rounded-xl border border-crypto-border bg-crypto-card p-1">
          {([
            ['all', '全部状态', statusCounts.all],
            ['running', '运行中', statusCounts.running],
            ['success', '已完成', statusCounts.success],
            ['failed', '已失败', statusCounts.failed],
          ] as const).map(([value, label, count]) => (
            <button key={value} type="button" onClick={() => setHistoryStatus(value)} className={`flex h-9 items-center gap-2 rounded-lg px-3 text-xs font-semibold transition ${historyStatus === value ? 'bg-purple-500/20 text-purple-200' : 'text-gray-500 hover:text-gray-300'}`}>
              {label}<span className="rounded bg-black/25 px-1.5 py-0.5 text-[10px]">{count}</span>
            </button>
          ))}
        </div>
        <label className="flex h-11 items-center gap-2 rounded-xl border border-crypto-border bg-crypto-card px-3 text-xs text-gray-500">
          <SlidersHorizontal className="h-4 w-4" />
          <select aria-label="回测排序" value={historySort} onChange={(event) => setHistorySort(event.target.value as typeof historySort)} className="bg-transparent text-gray-300 outline-none">
            <option value="created">创建时间 ↓</option><option value="return">收益率 ↓</option><option value="drawdown">回撤 ↓</option><option value="sharpe">Sharpe ↓</option>
          </select>
        </label>
      </div>

      <section className={`${panel} overflow-hidden`}>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-5 py-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2"><Layers3 className="h-4 w-4 text-purple-400" /><h2 className="font-semibold text-white">回测实例</h2><span className="text-xs text-gray-600">{visibleRuns.length} / {runs.length} 个</span></div>
            <label className="relative">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-600" />
              <input value={historyQuery} onChange={(event) => setHistoryQuery(event.target.value)} placeholder="搜索策略、运行或 ID" className="h-9 w-64 rounded-lg border border-crypto-border bg-crypto-bg pl-9 pr-3 text-xs text-gray-200 outline-none focus:border-blue-500/60" />
            </label>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => void load()} className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border px-3 text-xs text-gray-400 hover:text-white"><RefreshCw className="h-3.5 w-3.5" />刷新记录</button>
            <button type="button" disabled={selected.length < 2 || selected.length > 8 || Boolean(busy)} onClick={() => void compare()} className="inline-flex h-9 items-center gap-2 rounded-lg border border-purple-500/30 bg-purple-500/10 px-3 text-xs font-semibold text-purple-300 disabled:opacity-40"><GitCompareArrows className="h-3.5 w-3.5" />对比 {selected.length} 项</button>
          </div>
        </div>
        <div data-testid="backtest-history-table" className="space-y-3 p-4">
          {visibleRuns.map((run) => {
            const selectable = run.run_mode === 'full' && run.status === 'success';
            return (
              <article key={run.id} className="rounded-xl border border-crypto-border bg-[#0c1119] p-4 transition hover:border-slate-600/70">
                <div className="grid items-center gap-4 xl:grid-cols-[minmax(260px,3fr)_minmax(360px,2fr)_auto]">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="truncate text-sm font-semibold text-amber-300">{run.strategy_name ?? run.name}</h3>
                      <span className="rounded border border-blue-500/25 bg-blue-500/10 px-1.5 py-0.5 text-[10px] text-blue-300">A股</span>
                      <StatusBadge run={run} />
                    </div>
                    <p className="mt-2 text-xs text-gray-600">{run.start_date} 至 {run.end_date} · 数据快照 #{run.dataset_snapshot_id} · Universe #{run.universe_snapshot_id}</p>
                    <p className="mt-1 truncate text-[10px] text-gray-700">{run.name} · {run.id}</p>
                  </div>
                  <div className="grid grid-cols-5 gap-2">
                    {[
                      ['收益', formatValue(runMetric(run, 'strategy_return'), 'ratio'), 'text-emerald-300'],
                      ['夏普', formatValue(runMetric(run, 'sharpe')), 'text-gray-200'],
                      ['回撤', formatValue(runMetric(run, 'maximum_drawdown'), 'ratio'), 'text-red-300'],
                      ['胜率', formatValue(runMetric(run, 'win_rate'), 'ratio'), 'text-gray-200'],
                      ['交易', formatValue(tradeCount(run), 'count'), 'text-blue-300'],
                    ].map(([label, value, tone]) => <div key={label} className="min-w-0 text-center"><div className={`truncate font-mono text-sm font-semibold ${tone}`}>{value}</div><div className="mt-1 text-[10px] text-gray-600">{label}</div></div>)}
                  </div>
                  <div className="flex flex-wrap justify-end gap-2">
                    {selectable ? <label className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-lg border border-crypto-border px-3 text-xs text-gray-400"><input aria-label={`选择 ${run.name}`} type="checkbox" checked={selected.includes(run.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, run.id] : current.filter((id) => id !== run.id))} className="h-3.5 w-3.5 accent-purple-500" />对比</label> : null}
                    <button type="button" onClick={() => navigate(`/backtest/${run.id}`)} className="inline-flex h-9 items-center gap-2 rounded-lg border border-blue-500/35 bg-blue-500/10 px-3 text-xs font-semibold text-blue-300"><Eye className="h-3.5 w-3.5" />详情</button>
                    <button type="button" onClick={() => navigate(`/backtest/${run.id}`)} className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border px-3 text-xs text-gray-300"><FileText className="h-3.5 w-3.5" />日志</button>
                  </div>
                </div>
              </article>
            );
          })}
          {visibleRuns.length === 0 ? <div className="flex min-h-60 flex-col items-center justify-center text-center"><FlaskConical className="h-8 w-8 text-gray-700" /><p className="mt-3 text-sm text-gray-500">当前筛选下没有回测实例</p><p className="mt-1 text-xs text-gray-700">创建首个实例，或调整上方筛选条件。</p></div> : null}
        </div>
      </section>

      {createOpen ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm" onMouseDown={closeCreate}>
        <section role="dialog" aria-modal="true" aria-labelledby="create-backtest-title" className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-crypto-border bg-[#10161f] shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
          <div className="flex shrink-0 items-start justify-between border-b border-crypto-border px-6 py-5">
            <div><h2 id="create-backtest-title" className="text-lg font-semibold text-white">创建回测实例</h2><p className="mt-1 text-xs text-gray-500">策略选择 → 参数配置 → 证据确认</p></div>
            <button type="button" onClick={closeCreate} className="rounded-lg p-2 text-gray-500 hover:bg-white/5 hover:text-white"><X className="h-4 w-4" /></button>
          </div>
          <div className="shrink-0 border-b border-crypto-border px-6 py-4">
            <div className="grid grid-cols-3 gap-3">
              {([['选择策略', '选择不可变策略版本'], ['配置参数', '设置区间与研究输入'], ['确认运行', '核对证据并启动']] as const).map(([title, desc], index) => {
                const step = (index + 1) as 1 | 2 | 3;
                return <div key={title} className={`rounded-xl border p-3 ${createStep === step ? 'border-purple-500/40 bg-purple-500/10' : createStep > step ? 'border-emerald-500/25 bg-emerald-500/5' : 'border-crypto-border bg-black/10'}`}><div className="flex items-center gap-2"><span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${createStep >= step ? 'bg-purple-500 text-white' : 'bg-gray-800 text-gray-500'}`}>{createStep > step ? '✓' : step}</span><span className="text-xs font-semibold text-gray-200 sm:text-sm">{title}</span></div><p className="mt-1 hidden pl-8 text-[10px] text-gray-600 sm:block">{desc}</p></div>;
              })}
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-6">
            {createStep === 1 ? <div>
              <label className="relative block"><Search className="absolute left-3 top-3.5 h-4 w-4 text-gray-600" /><input autoFocus value={strategyQuery} onChange={(event) => setStrategyQuery(event.target.value)} placeholder="搜索策略名称、说明或版本" className={`${input} pl-10`} /></label>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                {strategyOptions.map((item) => <button key={item.id} type="button" onClick={() => setStrategyVersionId(item.id)} className={`rounded-xl border p-4 text-left transition ${strategyVersionId === item.id ? 'border-purple-500/50 bg-purple-500/10' : 'border-crypto-border bg-black/10 hover:border-slate-600'}`}><div className="flex items-start justify-between gap-3"><div><div className="font-semibold text-gray-100">{item.name}</div><p className="mt-1 line-clamp-2 text-xs leading-5 text-gray-500">{item.description || '未填写策略说明'}</p></div><span className="shrink-0 rounded border border-blue-500/25 bg-blue-500/10 px-2 py-1 text-[10px] text-blue-300">v{item.version}</span></div><p className="mt-3 font-mono text-[10px] text-gray-700">{item.content_hash.slice(0, 16)}</p></button>)}
              </div>
            </div> : null}
            {createStep === 2 ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <Field label="数据快照"><select className={input} value={datasetSnapshotId} onChange={(event) => setDatasetSnapshotId(Number(event.target.value))}>{config.dataset_snapshots.map((item) => <option key={item.id} value={item.id}>#{item.id} {item.name}</option>)}</select></Field>
              <Field label="Universe"><select className={input} value={universeSnapshotId} onChange={(event) => setUniverseSnapshotId(Number(event.target.value))}>{config.universe_snapshots.map((item) => <option key={item.id} value={item.id}>#{item.id} {item.code} · {item.member_count}只</option>)}</select></Field>
              <Field label="因子快照" hint="可选，且须与数据及 Universe 兼容"><select className={input} value={factorSnapshotId} onChange={(event) => setFactorSnapshotId(Number(event.target.value))}><option value={0}>不绑定</option>{config.factor_snapshots.map((item) => <option key={item.id} value={item.id}>#{item.id} {item.name}</option>)}</select></Field>
              <Field label="股票池快照"><select className={input} value={poolSnapshotId} onChange={(event) => { const id = Number(event.target.value); setPoolSnapshotId(id); const pool = config.pool_snapshots.find((item) => item.id === id); if (pool) { setDatasetSnapshotId(pool.dataset_snapshot_id); setUniverseSnapshotId(pool.universe_snapshot_id); setFactorSnapshotId(pool.factor_snapshot_id ?? 0); setSymbols(''); } }}><option value={0}>不绑定</option>{config.pool_snapshots.map((item) => <option key={item.id} value={item.id}>#{item.id} {item.pool_name} · {item.member_count}只</option>)}</select></Field>
              <Field label="成本模型"><select className={input} value={costModelId} onChange={(event) => setCostModelId(event.target.value)}>{config.cost_models.map((item) => <option key={item.id} value={item.id}>{item.name} · v{item.version}</option>)}</select></Field>
              <Field label="研究协议" hint="不绑定则不能晋级模拟盘"><select className={input} value={protocolId} onChange={(event) => setProtocolId(event.target.value)}><option value="">不绑定</option>{config.protocols.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
              <Field label="股票代码" hint={poolSnapshotId ? '由股票池快照提供' : '英文逗号分隔，例如 600519.SH'}><input className={input} value={poolSnapshotId ? `股票池快照 #${poolSnapshotId}` : symbols} readOnly={Boolean(poolSnapshotId)} onChange={(event) => setSymbols(event.target.value)} /></Field>
              <Field label="开始日期"><input type="date" className={input} value={startDate} onChange={(event) => setStartDate(event.target.value)} /></Field>
              <Field label="结束日期"><input type="date" className={input} value={endDate} onChange={(event) => setEndDate(event.target.value)} /></Field>
              <Field label="初始资金"><input type="number" min={10000} step={10000} className={input} value={initialCash} onChange={(event) => setInitialCash(Number(event.target.value))} /></Field>
              <Field label="策略参数 JSON"><input className={input} value={parameters} onChange={(event) => setParameters(event.target.value)} /></Field>
              <Field label="基准"><input className={input} value="000300.SH 沪深300" readOnly /></Field>
            </div> : null}
            {createStep === 3 ? <div className="grid gap-5 xl:grid-cols-[1.05fr_.95fr]">
              <div className="space-y-4">
                <section className="rounded-xl border border-crypto-border bg-black/10 p-4"><div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-emerald-400" /><h3 className="text-sm font-semibold text-white">实验配置确认</h3></div><dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">{[
                  ['策略版本', `${selectedVersion?.name ?? '--'} · v${selectedVersion?.version ?? '--'}`],
                  ['回测区间', `${startDate} 至 ${endDate}`],
                  ['初始资金', `¥${initialCash.toLocaleString('zh-CN')}`],
                  ['证券范围', selectedPool ? `${selectedPool.pool_name} · ${selectedPool.member_count}只` : symbols || '--'],
                  ['数据快照', selectedDataset ? `#${selectedDataset.id} ${selectedDataset.name}` : '--'],
                  ['Universe', selectedUniverse ? `#${selectedUniverse.id} ${selectedUniverse.code}` : '--'],
                  ['成本模型', selectedCostModel ? `${selectedCostModel.name} · v${selectedCostModel.version}` : '--'],
                  ['研究协议', selectedProtocol?.name ?? '未绑定（不可晋级）'],
                ].map(([label, value]) => <div key={label} className="rounded-lg border border-white/[0.05] bg-white/[0.02] p-3"><dt className="text-gray-600">{label}</dt><dd className="mt-1 font-medium text-gray-300">{value}</dd></div>)}</dl></section>
                <section className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4 text-xs leading-6 text-amber-200/80"><strong>执行规则：</strong>A 股日线信号最早于下一可交易日成交；100 股整数手、T+1、停牌与涨跌停约束均进入订单证据。快速预检不可对比或晋级。</section>
              </div>
              <section className="rounded-xl border border-crypto-border bg-black/10 p-4"><div className="flex items-center gap-2"><Beaker className="h-4 w-4 text-purple-400" /><h3 className="text-sm font-semibold text-white">参数矩阵</h3></div><p className="mt-2 text-xs text-gray-600">可选：运行 1–24 个组合检验参数稳定性。</p><textarea value={grid} onChange={(event) => setGrid(event.target.value)} className="mt-4 h-28 w-full rounded-lg border border-crypto-border bg-crypto-bg p-3 font-mono text-xs leading-6 text-gray-300 outline-none focus:border-purple-500/60" /><button type="button" onClick={() => void runMatrix()} disabled={Boolean(busy)} className="mt-3 inline-flex h-9 items-center gap-2 rounded-lg border border-purple-500/30 bg-purple-500/10 px-3 text-xs font-semibold text-purple-300 disabled:opacity-50"><Beaker className="h-3.5 w-3.5" />{busy === 'matrix' ? '矩阵运行中…' : '运行参数矩阵'}</button><div className="mt-5 border-t border-crypto-border pt-4"><div className="text-xs font-semibold text-gray-400">策略代码摘要</div><pre className="mt-3 max-h-44 overflow-auto rounded-lg bg-[#080c12] p-3 text-[10px] leading-5 text-blue-100"><code>{selectedVersion?.script_content ?? '请选择策略版本'}</code></pre></div></section>
            </div> : null}
          </div>
          <div className="flex shrink-0 items-center justify-between border-t border-crypto-border px-6 py-4">
            <button type="button" onClick={() => createStep === 1 ? closeCreate() : setCreateStep((createStep - 1) as 1 | 2)} className="h-10 rounded-lg border border-crypto-border px-4 text-sm text-gray-400 hover:text-white">{createStep === 1 ? '取消' : '上一步'}</button>
            {createStep < 3 ? <button type="button" disabled={createStep === 1 && !strategyVersionId} onClick={() => setCreateStep((createStep + 1) as 2 | 3)} className="inline-flex h-10 items-center gap-2 rounded-lg bg-purple-600 px-5 text-sm font-semibold text-white disabled:opacity-40">下一步<ChevronRight className="h-4 w-4" /></button> : <div className="flex items-center gap-2"><button type="button" onClick={() => void executeFromWizard('quick')} disabled={Boolean(busy)} className="inline-flex h-10 items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 text-sm font-semibold text-amber-300 disabled:opacity-50"><Zap className="h-4 w-4" />{busy === 'quick' ? '预检中…' : '快速预检'}</button><button data-testid="run-full-backtest" type="button" onClick={() => void executeFromWizard('full')} disabled={Boolean(busy)} className="inline-flex h-10 items-center gap-2 rounded-lg bg-purple-600 px-5 text-sm font-semibold text-white disabled:opacity-50"><Play className="h-4 w-4" />{busy === 'full' ? '回测运行中…' : '创建并运行'}</button></div>}
          </div>
        </section>
      </div> : null}

      {compareData ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-5" onMouseDown={() => setCompareData(null)}><section className="max-h-[88vh] w-full max-w-6xl overflow-auto rounded-2xl border border-crypto-border bg-crypto-card shadow-2xl" onMouseDown={(event) => event.stopPropagation()}><div className="sticky top-0 flex items-center justify-between border-b border-crypto-border bg-crypto-card px-6 py-4"><div><h2 className="font-semibold text-white">完整回测对比</h2><p className="mt-1 text-xs text-gray-500">{compareData.runs.length} 个回测结果</p></div><button type="button" onClick={() => setCompareData(null)} className="text-sm text-gray-400">关闭</button></div><div className="p-6"><GenericTable rows={compareData.runs.map((run) => ({ name: run.name, strategy: run.strategy_name, period: `${run.start_date} — ${run.end_date}`, return: formatValue(run.metrics?.strategy_return, 'ratio'), drawdown: formatValue(run.metrics?.maximum_drawdown, 'ratio'), sharpe: formatValue(run.metrics?.sharpe), snapshot: run.dataset_snapshot_id }))} columns={[["name", "运行"], ["strategy", "策略"], ["period", "区间"], ["return", "收益"], ["drawdown", "回撤"], ["sharpe", "Sharpe"], ["snapshot", "快照"]]} /></div></section></div> : null}
    </div>
  );
}
