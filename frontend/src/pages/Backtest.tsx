import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import ReactECharts from 'echarts-for-react';
import {
  ArrowLeft,
  BarChart3,
  Beaker,
  CalendarRange,
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
  RotateCcw,
  Search,
  ShieldCheck,
  Square,
  Terminal,
  X,
  Zap,
} from 'lucide-react';
import {
  compareBacktestRuns,
  cancelBacktestJob,
  createBacktestJob,
  createBacktestExperiment,
  createWalkForwardJob,
  getBacktestConfiguration,
  getBacktestEvidence,
  getBacktestMetrics,
  getBacktestJobLogs,
  getBacktestRun,
  getBacktestSeries,
  listBacktestRuns,
  listBacktestJobs,
  retryBacktestJob,
  runBacktestMatrix,
  previewWalkForward,
} from '../api/client';
import type {
  BacktestConfiguration,
  BacktestDailyPoint,
  BacktestMetric,
  BacktestJob,
  BacktestJobLog,
  BacktestRun,
  BacktestRunRequestV1,
  WalkForwardExecutionResult,
  WalkForwardPreview,
} from '../types';
import { orderTypeLabel, sideLabel, statusLabel } from '../utils/presentation';
import {
  countToneClass,
  marketAdverseToneClass,
  marketToneClass,
  thresholdToneClass,
} from '../utils/marketColors';
import {
  FilterChipGroup,
  OperatorFilterBar,
  OperatorMetricCard,
  OperatorPageHeader,
  OperatorStatePanel,
  SegmentedControl,
} from '../components/OperatorShell';
import { WorkspacePipelineNote } from '../components/WorkspacePipelineNote';
import { WorkspaceTabs } from '../components/WorkspaceTabs';
import { SymbolCell } from '../components/SymbolCell';
import { useSymbolNames } from '../hooks/useSymbolNames';

const panel = 'rounded-2xl border border-crypto-border bg-crypto-card';
const input = 'h-11 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-gray-200 outline-none transition focus:border-blue-500/70';
const isBusinessPurpose = (item: { data_purpose?: string | null }) =>
  !item.data_purpose || item.data_purpose === 'user';

const metricLabels: Record<string, string> = {
  strategy_return: '策略收益', annualized_return: '年化收益', benchmark_return: '基准收益', excess_return: '超额收益',
  maximum_drawdown: '最大回撤', sharpe: '夏普比率', sortino: '索提诺比率', alpha: 'Alpha', beta: 'Beta',
  information_ratio: '信息比率', annualized_volatility: '年化波动', downside_volatility: '下行波动',
  benchmark_volatility: '基准波动', tracking_error: '跟踪误差', calmar: '卡玛比率',
  win_rate: '交易胜率', profit_loss_ratio: '盈亏比', daily_win_rate: '日胜率', fill_rate: '成交率', rejection_rate: '拒单率',
  turnover: '换手率', total_cost: '总成本', total_commission: '佣金', total_tax: '印花税', total_transfer_fee: '过户费',
  total_slippage_cost: '滑点成本', average_holding_days: '平均持有天数', average_exposure: '平均敞口',
  peak_single_symbol_weight: '单票最高权重', capacity_warnings: '容量警告', data_quality_warnings: '数据质量警告',
  completed_trades: '成交笔数', total_orders: '总订单数', total_trades: '总成交数', excess_maximum_drawdown: '超额最大回撤',
};

const promotionCheckLabels: Record<string, string> = {
  FULL_SEALED_RUN: '完整回测已封存',
  SEALED_PROTOCOL: '研究协议已封存',
  TRAIN_PASS: '训练区间通过',
  VALIDATION_PASS: '验证区间通过',
  OUT_OF_SAMPLE_PASS: '样本外区间通过',
  COST_MODEL_PASS: '成本模型证据完整',
  CAPACITY_RULES_DEFINED: '容量规则已定义',
  CAPACITY_PASS: '容量实测通过',
  PROMOTION_THRESHOLDS_DEFINED: '晋级阈值已定义',
  BENCHMARK_PASS: '基准证据完整',
  DATA_QUALITY_PASS: '数据质量通过',
};

const unitLabels: Record<string, string> = {
  ratio: '比率 / %',
  ratio_per_year: '年化比率',
  number: '数值',
  count: '次数',
  days: '天',
  CNY: '人民币',
  percent: '%',
};

const frequencyLabels: Record<string, string> = {
  '1d': '日频',
  daily: '日频',
  '1h': '小时',
  intraday: '日内',
};

const sampleLabels: Record<string, string> = {
  train: '训练', validation: '验证', out_of_sample: '样本外',
};

function formatValue(value: number | null | undefined, unit = 'number') {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--';
  if (unit === 'ratio' || unit === 'ratio_per_year') return `${(Number(value) * 100).toFixed(2)}%`;
  if (unit === 'CNY') return `¥${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
  if (unit === 'count') return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 });
  if (unit === 'days') return `${Number(value).toFixed(1)} 天`;
  return Number(value).toFixed(3);
}

/** Compact console formatting: ratio -> %, count -> int, number -> 2dp, null -> muted dash. */
function formatConsoleValue(value: number | null | undefined, unit = 'number') {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  if (unit === 'ratio' || unit === 'ratio_per_year') return `${(Number(value) * 100).toFixed(2)}%`;
  if (unit === 'CNY') return `¥${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
  if (unit === 'count') return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 });
  if (unit === 'days') return `${Number(value).toFixed(1)} 天`;
  return Number(value).toFixed(2);
}

const NULL_TONE = 'text-slate-600';
const isNil = (value: number | null | undefined) =>
  value === null || value === undefined || !Number.isFinite(Number(value));

function metricValueTone(code: string, value: number | null | undefined, unit?: string) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return 'text-slate-500';
  if (code === 'maximum_drawdown' || code.includes('drawdown') || code.includes('cost') || code.includes('tax') || code.includes('slippage') || code.includes('rejection')) {
    return marketAdverseToneClass(value, 'text-slate-200');
  }
  if (code === 'sharpe' || code === 'sortino' || code === 'calmar' || code === 'information_ratio' || code === 'profit_loss_ratio') {
    return thresholdToneClass(value, code === 'profit_loss_ratio' ? 1 : 1, 'text-slate-200');
  }
  if (
    unit === 'ratio' ||
    unit === 'ratio_per_year' ||
    code.includes('return') ||
    code.includes('excess') ||
    code.includes('alpha') ||
    code.includes('win_rate')
  ) {
    return marketToneClass(value, 'text-slate-200');
  }
  return 'text-slate-100';
}

const runStatusMeta: Record<string, { label: string; chip: string }> = {
  running: { label: '进行中', chip: 'border-blue-500/30 bg-blue-500/10 text-blue-300' },
  success: { label: '成功', chip: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' },
  failed: { label: '失败', chip: 'border-red-500/30 bg-red-500/10 text-red-300' },
  cancelled: { label: '已取消', chip: 'border-white/10 bg-white/[0.04] text-slate-400' },
};

function RunStatusChip({ status }: { status: string }) {
  const meta = runStatusMeta[status] ?? { label: statusLabel(status), chip: runStatusMeta.cancelled.chip };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${meta.chip}`}>
      {status === 'success' ? <CheckCircle2 className="h-3.5 w-3.5" /> : null}
      {status === 'running' ? <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400" /> : null}
      {meta.label}
    </span>
  );
}

function RunModeChip({ mode }: { mode: BacktestRun['run_mode'] }) {
  const quick = mode === 'quick';
  return (
    <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${quick ? 'border-amber-500/25 bg-amber-500/[0.08] text-amber-300' : 'border-blue-500/25 bg-blue-500/10 text-blue-300'}`}>
      {quick ? '快速' : '完整'}
    </span>
  );
}

const promotionStatusMeta: Record<string, { label: string; chip: string }> = {
  paper_eligible: { label: '晋级 Paper', chip: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' },
  rejected: { label: '晋级驳回', chip: 'border-red-500/30 bg-red-500/10 text-red-300' },
  not_evaluated: { label: '未评估晋级', chip: 'border-white/10 bg-white/[0.04] text-slate-400' },
  not_eligible_quick: { label: '快速预检不可晋级', chip: 'border-white/10 bg-white/[0.04] text-slate-400' },
};

function PromotionStatusChip({ status }: { status: string }) {
  const meta = promotionStatusMeta[status] ?? { label: status || '未评估晋级', chip: promotionStatusMeta.not_evaluated.chip };
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${meta.chip}`}>{meta.label}</span>
  );
}

/** Dashboard comparison KPIs: 收益 / 回撤 / 夏普 / 交易数, nulls render muted dash. */
function runKpis(run: BacktestRun): Array<{ label: string; text: string; tone: string }> {
  const ret = run.metrics?.strategy_return ?? null;
  const drawdown = run.metrics?.maximum_drawdown ?? null;
  const sharpe = run.metrics?.sharpe ?? null;
  const trades = run.metrics?.completed_trades ?? run.metrics?.total_trades ?? null;
  return [
    { label: '收益', text: formatConsoleValue(ret, 'ratio'), tone: marketToneClass(ret, NULL_TONE) },
    { label: '回撤', text: formatConsoleValue(drawdown, 'ratio'), tone: marketAdverseToneClass(drawdown, NULL_TONE) },
    { label: '夏普', text: formatConsoleValue(sharpe), tone: isNil(sharpe) ? NULL_TONE : thresholdToneClass(sharpe, 1, 'text-slate-200') },
    { label: '交易', text: formatConsoleValue(trades, 'count'), tone: isNil(trades) ? NULL_TONE : countToneClass(trades) },
  ];
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return <label className="block"><span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-gray-500">{label}</span>{children}{hint ? <span className="mt-1.5 block text-xs text-gray-600">{hint}</span> : null}</label>;
}

const NUMERIC_KEYS = new Set([
  'metric_value', 'quantity', 'available_quantity', 'avg_cost', 'close_price', 'market_value', 'weight',
  'price', 'amount', 'commission', 'tax', 'realized_pnl', 'filled_quantity', 'contribution',
  'return', 'drawdown', 'sharpe',
]);
const DATETIME_KEYS = new Set([
  'trade_date', 'signal_at', 'earliest_fill_at', 'filled_at', 'simulated_at', 'created_at', 'period',
]);
const META_KEYS = new Set([
  'calculation_version', 'input_frequency', 'null_reason', 'rejection_code', 'source', 'payload',
  'attribution_type', 'attribution_key',
]);

function GenericTable({
  rows,
  columns,
  symbolNames = {},
}: {
  rows: Array<Record<string, unknown>>;
  columns: Array<[string, string]>;
  symbolNames?: Record<string, string>;
}) {
  if (!rows.length) {
    return <div className="flex min-h-48 items-center justify-center text-sm text-gray-600">暂无记录</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-left">
        <thead>
          <tr className="border-b border-crypto-border">
            {columns.map(([key, label]) => (
              <th
                key={key}
                className={`px-4 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-gray-600 ${NUMERIC_KEYS.has(key) ? 'text-right' : 'text-left'}`}
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={String(row.id ?? `${index}`)}
              className="border-b border-white/[0.04] hover:bg-white/[0.015]"
            >
              {columns.map(([key]) => {
                const current = row[key];
                if (key === 'symbol') {
                  return (
                    <td key={key} className="max-w-[280px] px-4 py-3">
                      <SymbolCell
                        symbol={String(current ?? '')}
                        name={String(row.name ?? '')}
                        names={symbolNames}
                        compact
                      />
                    </td>
                  );
                }
                if (key === 'metric_code') {
                  const code = String(current ?? '');
                  return (
                    <td key={key} className="px-4 py-3">
                      <div className="text-sm font-medium text-slate-200">
                        {metricLabels[code] ?? code}
                      </div>
                      <div className="mt-0.5 font-mono text-[10px] text-gray-600">{code}</div>
                    </td>
                  );
                }
                if (key === 'metric_value') {
                  const code = String(row.metric_code ?? '');
                  const unit = String(row.unit ?? 'number');
                  const numeric =
                    current === null || current === undefined || current === ''
                      ? null
                      : Number(current);
                  return (
                    <td key={key} className="px-4 py-3 text-right">
                      <span className={`font-mono text-sm font-bold tabular-nums tracking-tight ${metricValueTone(code, numeric, unit)}`}>
                        {formatValue(numeric, unit)}
                      </span>
                    </td>
                  );
                }
                if (key === 'unit') {
                  const raw = String(current ?? '');
                  return (
                    <td key={key} className="px-4 py-3">
                      <span className="inline-flex rounded border border-crypto-border bg-crypto-bg px-1.5 py-0.5 text-[10px] font-medium text-gray-500">
                        {unitLabels[raw] ?? (raw || '--')}
                      </span>
                    </td>
                  );
                }
                if (key === 'input_frequency') {
                  const raw = String(current ?? '');
                  return (
                    <td key={key} className="px-4 py-3 text-[11px] text-gray-500">
                      {frequencyLabels[raw] ?? (raw || '--')}
                    </td>
                  );
                }
                if (key === 'status' || key === 'level') {
                  return (
                    <td key={key} className="px-4 py-3">
                      <span className="inline-flex rounded border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] font-semibold text-slate-300">
                        {statusLabel(current)}
                      </span>
                    </td>
                  );
                }
                if (key === 'side') {
                  const label = sideLabel(current);
                  const buy = String(current).toLowerCase().includes('buy') || label.includes('买');
                  return (
                    <td key={key} className="px-4 py-3">
                      <span className={`text-sm font-semibold ${buy ? 'text-up' : 'text-down'}`}>{label}</span>
                    </td>
                  );
                }
                if (key === 'order_type' || key === 'intent_type') {
                  return (
                    <td key={key} className="px-4 py-3 text-xs font-medium text-slate-300">
                      {orderTypeLabel(current)}
                    </td>
                  );
                }
                if (DATETIME_KEYS.has(key)) {
                  return (
                    <td key={key} className="whitespace-nowrap px-4 py-3 font-mono text-[11px] tabular-nums text-gray-500">
                      {String(current ?? '--')}
                    </td>
                  );
                }
                if (NUMERIC_KEYS.has(key)) {
                  const numeric =
                    current === null || current === undefined || current === ''
                      ? null
                      : Number(current);
                  const pnlLike = key.includes('pnl') || key === 'return' || key === 'contribution';
                  return (
                    <td key={key} className="px-4 py-3 text-right">
                      <span
                        className={`font-mono text-sm tabular-nums tracking-tight ${
                          pnlLike ? marketToneClass(numeric, 'text-slate-200') : 'font-semibold text-slate-100'
                        }`}
                      >
                        {numeric === null || !Number.isFinite(numeric)
                          ? '--'
                          : key === 'weight' || key === 'return' || key === 'drawdown'
                            ? formatValue(numeric, 'ratio')
                            : Number.isInteger(numeric)
                              ? numeric.toLocaleString('zh-CN')
                              : numeric.toLocaleString('zh-CN', { maximumFractionDigits: 4 })}
                      </span>
                    </td>
                  );
                }
                if (META_KEYS.has(key) || typeof current === 'object') {
                  const text =
                    typeof current === 'object' ? JSON.stringify(current) : String(current ?? '--');
                  const empty = !current || text === '--' || text === 'null';
                  return (
                    <td key={key} className="max-w-[320px] px-4 py-3">
                      <span
                        className={`line-clamp-2 font-mono text-[10px] leading-4 ${
                          key === 'null_reason' && !empty ? 'text-amber-300/90' : 'text-gray-600'
                        }`}
                      >
                        {empty ? '--' : text}
                      </span>
                    </td>
                  );
                }
                return (
                  <td key={key} className="max-w-[360px] px-4 py-3">
                    <span className="line-clamp-2 text-sm text-slate-300">{String(current ?? '--')}</span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
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

const detailTabs = ['持仓', '交易', '订单', '日志', '归因', '代码与参数'] as const;

/** 绩效明细: 3 compact label:value columns over whatever metric codes the backend sealed. */
const metricGroups: Array<{ title: string; codes: string[] }> = [
  {
    title: '收益类',
    codes: ['annualized_return', 'benchmark_return', 'excess_return', 'alpha', 'beta', 'information_ratio', 'calmar'],
  },
  {
    title: '风险类',
    codes: ['sharpe', 'annualized_volatility', 'downside_volatility', 'benchmark_volatility', 'tracking_error', 'sortino', 'maximum_drawdown', 'excess_maximum_drawdown'],
  },
  {
    title: '交易类',
    codes: ['win_rate', 'daily_win_rate', 'profit_loss_ratio', 'completed_trades', 'total_orders', 'total_trades', 'fill_rate', 'rejection_rate', 'turnover', 'total_cost', 'total_commission', 'total_tax', 'total_transfer_fee', 'total_slippage_cost', 'average_holding_days', 'average_exposure', 'peak_single_symbol_weight'],
  },
];

const verdictCodes = [
  { code: 'strategy_return', label: '净收益' },
  { code: 'excess_return', label: '超额收益' },
  { code: 'maximum_drawdown', label: '最大回撤' },
  { code: 'sharpe', label: '夏普' },
] as const;

function MetricRow({ code, item }: { code: string; item?: BacktestMetric }) {
  const value = item?.metric_value;
  const tone = isNil(value) ? NULL_TONE : metricValueTone(code, value, item?.unit);
  return (
    <div className="flex items-center justify-between gap-3 border-b border-white/[0.03] py-1.5">
      <span className="min-w-0 truncate text-xs text-slate-500" title={code}>
        {metricLabels[code] ?? code}
      </span>
      <span
        className={`shrink-0 font-mono text-xs tabular-nums ${tone}`}
        title={item?.metric_value == null ? (item?.null_reason ?? '未定义') : item?.calculation_version}
      >
        {formatConsoleValue(value, item?.unit ?? 'number')}
      </span>
    </div>
  );
}

function BacktestDetail({ runId }: { runId: string }) {
  const navigate = useNavigate();
  const [data, setData] = useState<DetailData | null>(null);
  const [tab, setTab] = useState<(typeof detailTabs)[number]>('持仓');
  const [error, setError] = useState('');
  const [evidenceStatus, setEvidenceStatus] = useState<Record<string, 'loading' | 'loaded' | 'failed'>>({});
  const [seriesStatus, setSeriesStatus] = useState<'loading' | 'loaded' | 'failed'>('loading');

  useEffect(() => {
    let live = true;
    Promise.all([
      getBacktestRun(runId), getBacktestMetrics(runId),
    ]).then(([run, metrics]) => {
      if (live) setData({ run, metrics, daily: [], monthly: [], custom: [], positions: [], orders: [], trades: [], logs: [], attribution: [] });
    }).catch((reason: unknown) => live && setError(reason instanceof Error ? reason.message : '回测证据加载失败'));
    return () => { live = false; };
  }, [runId]);

  useEffect(() => {
    if (!data || seriesStatus !== 'loading') return;
    void getBacktestSeries(runId).then((series) => {
      setData((current) => current ? { ...current, daily: series.daily, monthly: series.monthly_returns, custom: series.custom_records } : current);
      setSeriesStatus('loaded');
    }).catch(() => setSeriesStatus('failed'));
  }, [data, runId, seriesStatus]);

  useEffect(() => {
    const kindByTab: Partial<Record<(typeof detailTabs)[number], 'positions' | 'orders' | 'trades' | 'logs' | 'attribution'>> = {
      持仓: 'positions',
      交易: 'trades',
      订单: 'orders',
      日志: 'logs',
      归因: 'attribution',
    };
    const kind = kindByTab[tab];
    if (!data || !kind || evidenceStatus[kind]) return;
    setEvidenceStatus((current) => ({ ...current, [kind]: 'loading' }));
    void getBacktestEvidence(runId, kind).then((items) => {
      setData((current) => current ? { ...current, [kind]: items } : current);
      setEvidenceStatus((current) => ({ ...current, [kind]: 'loaded' }));
    }).catch(() => {
      setEvidenceStatus((current) => ({ ...current, [kind]: 'failed' }));
    });
  }, [data, evidenceStatus, runId, tab]);

  const metricMap = useMemo(() => Object.fromEntries((data?.metrics ?? []).map((item) => [item.metric_code, item])), [data]);
  const evidenceSymbols = useMemo(() => {
    if (!data) return [] as string[];
    return [
      ...data.positions.map((row) => String(row.symbol ?? '')),
      ...data.trades.map((row) => String(row.symbol ?? '')),
      ...data.orders.map((row) => String(row.symbol ?? '')),
    ];
  }, [data]);
  const symbolNames = useSymbolNames(evidenceSymbols);
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
  const gateChecks = data.run.promotion_checks ?? [];
  const dataQualityCheck = gateChecks.find((check) => check.check_code === 'DATA_QUALITY_PASS');
  const protocolEvaluations = data.run.protocol_evaluations ?? [];

  return (
    <div className="min-h-full bg-crypto-bg p-6 2xl:px-8" data-operator-page="backtest-detail">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <button type="button" onClick={() => navigate('/backtest')} className="mb-4 inline-flex items-center gap-2 text-sm text-gray-500 hover:text-blue-300"><ArrowLeft className="h-4 w-4" />返回回测台</button>
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-2xl font-bold text-white">{data.run.strategy_name ?? data.run.name}</h1>
            <RunModeChip mode={data.run.run_mode} />
            <RunStatusChip status={data.run.status} />
            <PromotionStatusChip status={data.run.promotion_status} />
            {dataQualityCheck ? (
              <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${dataQualityCheck.status === 'passed' ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : dataQualityCheck.status === 'failed' ? 'border-red-500/30 bg-red-500/10 text-red-300' : 'border-amber-500/30 bg-amber-500/10 text-amber-300'}`}>
                {dataQualityCheck.status === 'passed' ? <CheckCircle2 className="h-3.5 w-3.5" /> : <CircleAlert className="h-3.5 w-3.5" />}
                数据可信度 · {dataQualityCheck.status === 'passed' ? '通过' : dataQualityCheck.status === 'failed' ? '未通过' : '待定'}
              </span>
            ) : null}
          </div>
          <p className="mt-2 font-mono text-xs tabular-nums text-gray-500">回测区间 {data.run.start_date} — {data.run.end_date}</p>
          <p className="mt-1 truncate text-xs text-gray-600">
            {data.run.name} · v{data.run.strategy_version} · 基准 {data.run.benchmark_code} · 成本模型 {data.run.cost_model_name ?? '未绑定'} · 研究协议 {data.run.protocol_name ?? '未绑定'} · 数据快照 {data.run.dataset_snapshot_id ? '已封存' : '未绑定'}
          </p>
        </div>
      </div>

      {/* 判决带 verdict strip */}
      <div data-testid="backtest-verdict-strip" className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {verdictCodes.map(({ code, label }) => {
          const item = metricMap[code];
          const value = item?.metric_value;
          const toneClass = code === 'maximum_drawdown'
            ? marketAdverseToneClass(value)
            : code === 'sharpe'
              ? thresholdToneClass(value, 1)
              : marketToneClass(value);
          const tone = toneClass.includes('up') ? 'up' : toneClass.includes('down') ? 'down' : 'neutral';
          return (
            <div key={code} title={value == null ? (item?.null_reason ?? '未定义') : undefined}>
              <OperatorMetricCard
                label={label}
                tone={tone}
                value={value == null ? '—' : formatConsoleValue(value, item?.unit ?? (code === 'sharpe' ? 'number' : 'ratio'))}
                detail={value == null ? (item?.null_reason ?? '未定义') : item?.calculation_version}
              />
            </div>
          );
        })}
      </div>

      {/* 绩效明细 */}
      <section className={`${panel} mb-5 overflow-hidden`}>
        <div className="flex items-center justify-between gap-3 border-b border-crypto-border px-5 py-3">
          <h2 className="text-sm font-semibold text-white">绩效明细</h2>
          <span className="font-mono text-[10px] tabular-nums text-gray-600">{data.metrics.length} 项封存指标 · 空值显示未定义原因</span>
        </div>
        <div className="grid gap-x-8 p-5 md:grid-cols-3">
          {metricGroups.map((group) => (
            <div key={group.title} className="min-w-0">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">{group.title}</h3>
              {group.codes.filter((code) => metricMap[code]).map((code) => (
                <MetricRow key={code} code={code} item={metricMap[code]} />
              ))}
              {group.codes.every((code) => !metricMap[code]) ? <p className="text-xs text-gray-600">暂无封存指标</p> : null}
            </div>
          ))}
        </div>
      </section>

      {/* 晋级检查：快速预检也要渲染，向操作者显式声明“不产生晋级证据”。 */}
      {data.run.run_mode === 'quick' || gateChecks.length ? (
        <section className={`${panel} mb-5 overflow-hidden`}>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-5 py-3">
            <div>
              <h2 className="text-sm font-semibold text-white">晋级检查</h2>
              <p className="mt-0.5 text-[11px] text-gray-600">评估证据封存后只读；门禁必须全部通过才可进入 Paper 候选。</p>
            </div>
            {data.run.run_mode === 'full' ? (
              <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${data.run.promotion_gate_complete ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : data.run.promotion_status === 'rejected' ? 'border-red-500/30 bg-red-500/10 text-red-300' : 'border-amber-500/30 bg-amber-500/10 text-amber-300'}`}>
                {data.run.promotion_gate_complete ? '门禁全部通过' : data.run.promotion_status === 'rejected' ? '未通过晋级' : '门禁未完成'}
              </span>
            ) : null}
          </div>
          {data.run.run_mode === 'quick' ? (
            <div className="flex items-start gap-3 p-5">
              <Zap className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" />
              <p className="text-sm leading-6 text-amber-200/70">快速预检不产生晋级证据：只用于检查策略能否运行及早期诊断，不会进入模拟盘候选。</p>
            </div>
          ) : (
            <div className="grid gap-2 p-5 md:grid-cols-2">
              {gateChecks.map((check) => (
                <div key={check.check_code} className={`flex items-start gap-2.5 rounded-lg border px-3 py-2 ${check.status === 'passed' ? 'border-emerald-500/20 bg-emerald-500/[0.05]' : check.status === 'failed' ? 'border-red-500/20 bg-red-500/[0.05]' : 'border-amber-500/20 bg-amber-500/[0.05]'}`}>
                  {check.status === 'passed'
                    ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                    : check.status === 'failed'
                      ? <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-400" />
                      : <Clock3 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />}
                  <div className="min-w-0">
                    <div className={`text-xs font-medium ${check.status === 'passed' ? 'text-emerald-300' : check.status === 'failed' ? 'text-red-300' : 'text-amber-300'}`}>
                      {promotionCheckLabels[check.check_code] ?? check.check_code}
                    </div>
                    {check.status !== 'passed' && check.reason ? (
                      <div className="mt-0.5 text-[11px] leading-4 text-gray-500">{check.reason}</div>
                    ) : null}
                  </div>
                </div>
              ))}
              {!gateChecks.length ? <div className="text-xs text-gray-600 md:col-span-2">尚无封存的晋级检查证据。</div> : null}
            </div>
          )}
          {protocolEvaluations.length ? (
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t border-crypto-border px-5 py-3 text-[11px] text-gray-500">
              {protocolEvaluations.map((evaluation) => (
                <span key={evaluation.sample_label} className="inline-flex items-center gap-1.5 font-mono tabular-nums">
                  {evaluation.status === 'passed' ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" /> : <CircleAlert className="h-3.5 w-3.5 text-amber-400" />}
                  {sampleLabels[evaluation.sample_label] ?? evaluation.sample_label} {evaluation.start_date}~{evaluation.end_date}
                </span>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {/* 账户曲线 */}
      <section className={`${panel} mb-5 p-5`}>
        <div className="mb-3 flex items-center gap-2 text-base font-semibold text-white"><BarChart3 className="h-5 w-5 text-blue-400" />账户曲线</div>
        {seriesStatus === 'loaded'
          ? <ReactECharts option={chartOption} style={{ height: 380 }} />
          : <EvidenceLedgerState status={seriesStatus === 'failed' ? 'failed' : 'loading'} />}
        {seriesStatus === 'loaded' && data.monthly.length ? (
          <div className="mt-4 border-t border-white/[0.04] pt-4">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">月度收益</div>
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-6 xl:grid-cols-12">
              {data.monthly.map((item) => (
                <div key={item.month} className="rounded-lg border border-crypto-border bg-crypto-bg p-3 text-center">
                  <div className="text-xs text-gray-500">{item.month}</div>
                  <div className={`mt-1 font-mono text-sm font-bold tabular-nums ${marketToneClass(item.return)}`}>{formatValue(item.return, 'ratio')}</div>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </section>

      {/* 交易流水：按需懒加载 */}
      <WorkspaceTabs<(typeof detailTabs)[number]>
        ariaLabel="回测交易流水"
        items={detailTabs.map((item) => ({ id: item, label: item, testId: `backtest-detail-tab-${item}` }))}
        value={tab}
        onChange={setTab}
      />
      {tab === '持仓' && <section className={panel}>{evidenceStatus.positions === 'loaded' ? <GenericTable rows={data.positions} symbolNames={symbolNames} columns={[["trade_date", "日期"], ["symbol", "证券"], ["quantity", "数量"], ["available_quantity", "可卖"], ["avg_cost", "成本"], ["close_price", "收盘"], ["market_value", "市值"], ["weight", "权重"]]} /> : <EvidenceLedgerState status={evidenceStatus.positions} />}</section>}
      {tab === '交易' && <section className={panel}>{evidenceStatus.trades === 'loaded' ? <GenericTable rows={data.trades} symbolNames={symbolNames} columns={[["trade_date", "日期"], ["symbol", "证券"], ["side", "方向"], ["price", "价格"], ["quantity", "数量"], ["amount", "金额"], ["commission", "佣金"], ["tax", "税费"], ["realized_pnl", "已实现盈亏"]]} /> : <EvidenceLedgerState status={evidenceStatus.trades} />}</section>}
      {tab === '订单' && <section className={panel}>{evidenceStatus.orders === 'loaded' ? <GenericTable rows={data.orders} symbolNames={symbolNames} columns={[["signal_at", "信号时间"], ["earliest_fill_at", "最早成交"], ["filled_at", "成交时间"], ["symbol", "证券"], ["intent_type", "意图"], ["status", "状态"], ["filled_quantity", "成交数量"], ["rejection_code", "拒单代码"]]} /> : <EvidenceLedgerState status={evidenceStatus.orders} />}</section>}
      {tab === '日志' && <section className={panel}>{evidenceStatus.logs === 'loaded' ? <GenericTable rows={data.logs} columns={[["simulated_at", "模拟时间"], ["level", "级别"], ["source", "来源"], ["message", "消息"], ["payload", "上下文"]]} /> : <EvidenceLedgerState status={evidenceStatus.logs} />}</section>}
      {tab === '归因' && <section className={panel}>{evidenceStatus.attribution === 'loaded' ? <GenericTable rows={data.attribution} columns={[["attribution_type", "类型"], ["attribution_key", "归因项"], ["contribution", "贡献"], ["amount", "金额"], ["payload", "证据"]]} /> : <EvidenceLedgerState status={evidenceStatus.attribution} />}</section>}
      {tab === '代码与参数' && <div className="grid gap-5 xl:grid-cols-[2fr_1fr]"><section className={`${panel} overflow-hidden`}><div className="border-b border-crypto-border px-5 py-4 text-sm font-semibold text-white">策略代码 · v{data.run.strategy_version}</div><pre className="max-h-[620px] overflow-auto p-5 text-xs leading-6 text-blue-100"><code>{data.run.script_content}</code></pre></section><section className={`${panel} p-5`}><h2 className="text-sm font-semibold text-white">运行参数</h2><pre className="mt-4 overflow-auto rounded-lg bg-crypto-bg p-4 text-xs leading-6 text-gray-300">{JSON.stringify(data.run.parameters, null, 2)}</pre><h2 className="mt-6 text-sm font-semibold text-white">自定义指标</h2><pre className="mt-4 max-h-72 overflow-auto rounded-lg bg-crypto-bg p-4 text-xs leading-6 text-gray-300">{JSON.stringify(data.custom, null, 2)}</pre></section></div>}
    </div>
  );
}

function EvidenceLedgerState({ status }: { status?: 'loading' | 'loaded' | 'failed' }) {
  if (status === 'failed') return <div className="flex min-h-48 items-center justify-center gap-2 p-6 text-sm text-red-300"><CircleAlert className="h-4 w-4" />证据账读取失败，请刷新页面后重试。</div>;
  return <div className="flex min-h-48 items-center justify-center gap-2 p-6 text-sm text-gray-500"><RefreshCw className="h-4 w-4 animate-spin" />正在按需读取证据账…</div>;
}

type StatusFilter = 'all' | 'running' | 'success' | 'failed' | 'cancelled';
type SortKey = 'created' | 'return' | 'drawdown' | 'win_rate';

export function Backtest() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [config, setConfig] = useState<BacktestConfiguration | null>(null);
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [jobs, setJobs] = useState<BacktestJob[]>([]);
  const [jobLogs, setJobLogs] = useState<Record<string, BacktestJobLog[]>>({});
  const [openJobLog, setOpenJobLog] = useState('');
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
  const [historyStatus, setHistoryStatus] = useState<StatusFilter>('all');
  const [historySort, setHistorySort] = useState<SortKey>('created');
  const [listReady, setListReady] = useState(false);
  const [walkForwardOpen, setWalkForwardOpen] = useState(false);
  const [walkForwardBusy, setWalkForwardBusy] = useState(false);
  const [walkForwardError, setWalkForwardError] = useState('');
  const [walkForwardPreview, setWalkForwardPreview] = useState<WalkForwardPreview | null>(null);
  const [trainSessions, setTrainSessions] = useState(252);
  const [testSessions, setTestSessions] = useState(63);
  const [stepSessions, setStepSessions] = useState(63);
  const [walkForwardGrid, setWalkForwardGrid] = useState('{"lookback":[5,10]}');
  const [walkForwardObjective, setWalkForwardObjective] = useState<'sharpe' | 'sortino' | 'strategy_return' | 'maximum_drawdown'>('sharpe');
  const [selectedWalkForwardResult, setSelectedWalkForwardResult] = useState<WalkForwardExecutionResult | null>(null);

  const load = useCallback(async () => {
    setError('');
    const listPromise = Promise.all([listBacktestRuns(50), listBacktestJobs(50)])
      .then(([history, jobHistory]) => {
        setRuns(history.items);
        setJobs(jobHistory.items);
        setListReady(true);
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : '回测记录加载失败');
        setListReady(true);
      });
    const configPromise = getBacktestConfiguration()
      .then((configuration) => setConfig(configuration))
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : '回测配置加载失败');
      });
    await Promise.allSettled([listPromise, configPromise]);
  }, []);

  useEffect(() => { if (!runId) void load(); }, [load, runId]);
  const hasActiveJobs = jobs.some((job) => ['pending', 'running', 'cancelling'].includes(job.status));
  useEffect(() => {
    if (runId || !hasActiveJobs) return;
    const timer = window.setInterval(() => {
      void Promise.all([listBacktestJobs(), listBacktestRuns()]).then(([jobHistory, history]) => {
        setJobs(jobHistory.items);
        setRuns(history.items);
      }).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [hasActiveJobs, runId]);
  useEffect(() => {
    if (!config) return;
    const requestedVersion = searchParams.get('strategyVersionId');
    const pipelineVersion = config.strategy_versions.find((item) => (item.name || '').includes('多因子'));
    if (!strategyVersionId) {
      setStrategyVersionId(requestedVersion || pipelineVersion?.id || config.strategy_versions[0]?.id || '');
    }
    const requestedPool = Number(searchParams.get('poolSnapshotId') || 0);
    const pipelinePool = config.pool_snapshots.find((item) => item.id === requestedPool)
      || config.pool_snapshots.find((item) => item.factor_snapshot_id && (item.pool_name || '').includes('动量'))
      || config.pool_snapshots.find((item) => item.factor_snapshot_id);
    if (pipelinePool && !poolSnapshotId) {
      setPoolSnapshotId(pipelinePool.id);
      setDatasetSnapshotId(pipelinePool.dataset_snapshot_id);
      setUniverseSnapshotId(pipelinePool.universe_snapshot_id);
      setFactorSnapshotId(pipelinePool.factor_snapshot_id ?? 0);
      setSymbols('');
    } else {
      if (!datasetSnapshotId && config.dataset_snapshots[0]) setDatasetSnapshotId(config.dataset_snapshots[0].id);
      if (!universeSnapshotId) setUniverseSnapshotId(config.universe_snapshots[0]?.id ?? 0);
    }
    if (!costModelId) setCostModelId(config.cost_models[0]?.id ?? '');
    if (!protocolId) {
      const pipelineProtocol = config.protocols.find((item) => (item.name || '').includes('多因子'))
        || config.protocols[0];
      if (pipelineProtocol) {
        setProtocolId(pipelineProtocol.id);
        setStartDate(pipelineProtocol.train_start);
        setEndDate(pipelineProtocol.out_of_sample_end);
      }
    }
  }, [config, costModelId, datasetSnapshotId, poolSnapshotId, protocolId, searchParams, strategyVersionId, universeSnapshotId]);
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

  const scopedRuns = useMemo(
    () => runs.filter((run) => isBusinessPurpose(run)),
    [runs],
  );
  const visibleJobs = useMemo(
    () =>
      jobs.filter((job) => {
        const linkedRun = job.backtest_run_id
          ? runs.find((run) => run.id === job.backtest_run_id)
          : undefined;
        return !linkedRun || isBusinessPurpose(linkedRun);
      }),
    [jobs, runs],
  );
  const visibleRuns = useMemo(() => {
    const query = historyQuery.trim().toLowerCase();
    return scopedRuns.filter((run) => {
      if (historyStatus !== 'all' && run.status !== historyStatus) return false;
      if (!query) return true;
      const haystack = `${run.name} ${run.strategy_name ?? ''} ${run.start_date} ${run.end_date} ${run.created_at} ${statusLabel(run.status)} ${run.run_mode === 'quick' ? '快速 快速预检' : '完整 完整回测'}`.toLowerCase();
      return haystack.includes(query);
    }).sort((a, b) => {
      if (historySort === 'created') return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      const metricOf = (run: BacktestRun, code: string) => Number(run.metrics?.[code] ?? -Infinity);
      if (historySort === 'return') return metricOf(b, 'strategy_return') - metricOf(a, 'strategy_return');
      if (historySort === 'drawdown') return metricOf(b, 'maximum_drawdown') - metricOf(a, 'maximum_drawdown');
      return metricOf(b, 'win_rate') - metricOf(a, 'win_rate');
    });
  }, [historyQuery, historySort, historyStatus, scopedRuns]);
  const statusCounts = useMemo(() => ({
    all: scopedRuns.length,
    running: scopedRuns.filter((run) => run.status === 'running').length,
    success: scopedRuns.filter((run) => run.status === 'success').length,
    failed: scopedRuns.filter((run) => run.status === 'failed').length,
    cancelled: scopedRuns.filter((run) => (run.status as string) === 'cancelled').length,
  }), [scopedRuns]);
  const strategyOptions = useMemo(() => {
    const query = strategyQuery.trim().toLowerCase();
    return (config?.strategy_versions ?? []).filter((item) =>
      !query || `${item.name} ${item.description ?? ''} v${item.version}`.toLowerCase().includes(query));
  }, [config?.strategy_versions, strategyQuery]);

  if (runId) return <BacktestDetail runId={runId} />;

  if (!listReady) return <div className="min-h-full bg-crypto-bg p-6 2xl:px-8"><header className="mb-6 flex flex-wrap items-start justify-between gap-4"><div><div className="flex items-center gap-3"><FlaskConical className="h-7 w-7 text-blue-400" /><h1 className="text-2xl font-bold text-white">回测</h1></div><p className="mt-2 text-sm text-gray-500">A股策略回测 · T+1 撮合 · 成本与风险证据</p></div></header>{error ? <div className="rounded-xl border border-red-500/25 bg-red-500/10 p-5 text-sm text-red-200"><div className="flex items-start gap-3"><CircleAlert className="mt-0.5 h-4 w-4 shrink-0" /><span><strong>记录加载失败：</strong>{error}</span></div><button type="button" onClick={() => void load()} className="mt-4 inline-flex h-9 items-center gap-2 rounded-lg border border-red-400/30 px-3 text-xs font-semibold"><RefreshCw className="h-3.5 w-3.5" />重试</button></div> : <div className={`${panel} flex min-h-[360px] items-center justify-center text-sm text-gray-500`}><RefreshCw className="mr-3 h-5 w-5 animate-spin" />正在读取回测记录…</div>}</div>;

  const request = (): BacktestRunRequestV1 => ({
    strategy_version_id: strategyVersionId, dataset_snapshot_id: datasetSnapshotId, universe_snapshot_id: universeSnapshotId,
    factor_snapshot_id: factorSnapshotId || null, cost_model_id: costModelId, research_protocol_id: protocolId || null,
    pool_snapshot_id: poolSnapshotId || null,
    symbols: poolSnapshotId ? [] : symbols.split(',').map((item) => item.trim().toUpperCase()).filter(Boolean), start_date: startDate, end_date: endDate,
    initial_cash: initialCash, benchmark_code: selectedProtocol?.benchmark_code ?? '000300.SH', parameters: JSON.parse(parameters || '{}') as Record<string, unknown>, event_limit: 30,
  });

  const execute = async (mode: 'quick' | 'full') => {
    setBusy(mode); setError('');
    try {
      const job = await createBacktestJob(request(), mode);
      setJobs((current) => [job, ...current.filter((item) => item.job_id !== job.job_id)]);
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : '回测运行失败'); }
    finally { setBusy(''); }
  };

  const controlJob = async (job: BacktestJob, action: 'cancel' | 'retry') => {
    setBusy(`${action}:${job.job_id}`);
    setError('');
    try {
      const updated = action === 'cancel'
        ? await cancelBacktestJob(job.job_id)
        : await retryBacktestJob(job.job_id);
      setJobs((current) => [
        updated,
        ...current.filter((item) => item.job_id !== updated.job_id),
      ]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '任务控制失败');
    } finally {
      setBusy('');
    }
  };

  const toggleJobLog = async (jobId: string) => {
    if (openJobLog === jobId) {
      setOpenJobLog('');
      return;
    }
    setOpenJobLog(jobId);
    try {
      const logs = await getBacktestJobLogs(jobId);
      setJobLogs((current) => ({ ...current, [jobId]: logs }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '任务日志加载失败');
    }
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
  const selectedDataset = config?.dataset_snapshots.find((item) => item.id === datasetSnapshotId);
  const selectedUniverse = config?.universe_snapshots.find((item) => item.id === universeSnapshotId);
  const selectedCostModel = config?.cost_models.find((item) => item.id === costModelId);
  const selectedProtocol = config?.protocols.find((item) => item.id === protocolId);
  const selectedPool = config?.pool_snapshots.find((item) => item.id === poolSnapshotId);
  const hasWalkForwardSnapshot = Boolean(config?.dataset_snapshots.length && datasetSnapshotId);
  const openCreate = () => {
    if (!config) {
      setError('回测配置尚未就绪，请稍后重试');
      return;
    }
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

  const openWalkForwardPreview = () => {
    if (!config || !datasetSnapshotId) {
      setError('Walk-forward 需要已封存数据快照');
      return;
    }
    setWalkForwardError('');
    setWalkForwardPreview(null);
    setWalkForwardOpen(true);
  };

  const buildWalkForwardPreview = async () => {
    setWalkForwardBusy(true);
    setWalkForwardError('');
    try {
      setWalkForwardPreview(await previewWalkForward({
        dataset_snapshot_id: datasetSnapshotId,
        start_date: startDate,
        end_date: endDate,
        train_sessions: trainSessions,
        test_sessions: testSessions,
        step_sessions: stepSessions,
      }));
    } catch (reason) {
      setWalkForwardPreview(null);
      setWalkForwardError(reason instanceof Error ? reason.message : '折叠计划生成失败');
    } finally {
      setWalkForwardBusy(false);
    }
  };

  const startWalkForwardJob = async () => {
    setWalkForwardBusy(true);
    setWalkForwardError('');
    try {
      const parameterGrid = JSON.parse(walkForwardGrid) as Record<string, unknown[]>;
      const job = await createWalkForwardJob({
        ...request(),
        train_sessions: trainSessions,
        test_sessions: testSessions,
        step_sessions: stepSessions,
        parameter_grid: parameterGrid,
        objective: walkForwardObjective,
        name: `${selectedVersion?.name ?? '策略'} / Walk-forward`,
      });
      setJobs((current) => [job, ...current.filter((item) => item.job_id !== job.job_id)]);
      setWalkForwardOpen(false);
      setWalkForwardPreview(null);
    } catch (reason) {
      setWalkForwardError(reason instanceof Error ? reason.message : 'Walk-forward 任务创建失败');
    } finally {
      setWalkForwardBusy(false);
    }
  };

  return (
    <div className="min-h-full bg-crypto-bg p-6 2xl:px-8" data-operator-page="backtest">
      <OperatorPageHeader
        icon={FlaskConical}
        title="回测"
        subtitle="绑定策略版本、数据快照与股票池后异步回测；任务队列、创建向导、结果详情与对比。"
        actions={
          <>
            <button type="button" onClick={openWalkForwardPreview} disabled={!hasWalkForwardSnapshot} title={hasWalkForwardSnapshot ? '从封存快照生成滚动训练/OOS窗口' : '需要至少一个已封存数据快照'} className="inline-flex h-11 items-center gap-2 rounded-xl border border-purple-500/30 bg-purple-500/10 px-4 text-sm font-semibold text-purple-200 disabled:cursor-not-allowed disabled:opacity-50">
              <CalendarRange className="h-4 w-4" />{hasWalkForwardSnapshot ? 'Walk-forward 预览' : '无封存快照'}
            </button>
            <button type="button" onClick={openCreate} disabled={!config} className="inline-flex h-11 items-center gap-2 rounded-xl bg-blue-600 px-5 text-sm font-semibold text-white shadow-lg shadow-blue-950/30 transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50">
              <Plus className="h-4 w-4" />{config ? '创建回测实例' : '配置读取中…'}
            </button>
          </>
        }
      />
      <WorkspacePipelineNote stageId="backtest" />

      {error ? (
        <OperatorStatePanel
          kind="error"
          title="回测工作台加载失败"
          description={error}
          className="mb-5"
          action={
            <button type="button" onClick={() => void load()} className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 px-3 py-1.5 text-xs font-semibold text-red-100">
              <RefreshCw className="h-3.5 w-3.5" />重试
            </button>
          }
        />
      ) : null}

      <section className={`${panel} mb-5 overflow-hidden`}>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-5 py-3.5">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2"><Layers3 className="h-4 w-4 text-blue-400" /><h2 className="font-semibold text-white">回测实例</h2><span className="text-xs text-gray-600">{visibleRuns.length} / {scopedRuns.length} 个</span></div>
            <label className="relative">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-600" />
              <input value={historyQuery} onChange={(event) => setHistoryQuery(event.target.value)} placeholder="搜索策略 / 运行名称 / 日期 / 状态" className="h-9 w-72 rounded-lg border border-crypto-border bg-crypto-bg pl-9 pr-3 text-xs text-gray-200 outline-none focus:border-blue-500/60" />
            </label>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => void load()} className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border px-3 text-xs text-gray-400 hover:text-white"><RefreshCw className="h-3.5 w-3.5" />刷新记录</button>
            <button type="button" disabled={selected.length < 2 || selected.length > 8 || Boolean(busy)} onClick={() => void compare()} className="inline-flex h-9 items-center gap-2 rounded-lg border border-purple-500/30 bg-purple-500/10 px-3 text-xs font-semibold text-purple-300 disabled:opacity-40"><GitCompareArrows className="h-3.5 w-3.5" />对比 {selected.length} 项</button>
          </div>
        </div>
        <OperatorFilterBar className="border-b border-crypto-border px-5 py-2.5">
          <FilterChipGroup<StatusFilter>
            aria-label="回测状态"
            value={historyStatus}
            onChange={setHistoryStatus}
            options={[
              { value: 'all', label: '全部', count: statusCounts.all },
              { value: 'running', label: '进行中', count: statusCounts.running },
              { value: 'success', label: '成功', count: statusCounts.success },
              { value: 'failed', label: '失败', count: statusCounts.failed },
              { value: 'cancelled', label: '已取消', count: statusCounts.cancelled },
            ]}
          />
          <SegmentedControl<SortKey>
            aria-label="回测排序"
            size="sm"
            value={historySort}
            onChange={setHistorySort}
            options={[
              { value: 'created', label: '创建时间↓' },
              { value: 'return', label: '收益率' },
              { value: 'drawdown', label: '回撤' },
              { value: 'win_rate', label: '胜率' },
            ]}
          />
        </OperatorFilterBar>
        <div data-testid="backtest-history-table">
          {visibleRuns.map((run) => {
            const selectable = run.run_mode === 'full' && run.status === 'success';
            const kpis = runKpis(run);
            return (
              <div key={run.id} className="grid items-center gap-3 px-5 py-2.5 transition hover:bg-white/[0.02] xl:grid-cols-[minmax(240px,2.2fr)_auto_minmax(190px,1fr)_minmax(320px,1.5fr)_auto]">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-100">{run.strategy_name ?? run.name}</div>
                  <div className="mt-0.5 truncate text-[10px] text-gray-600">{run.name}</div>
                </div>
                <div className="flex items-center gap-2">
                  <RunModeChip mode={run.run_mode} />
                  <RunStatusChip status={run.status} />
                </div>
                <div className="font-mono text-[11px] tabular-nums text-slate-500">{run.start_date} ~ {run.end_date}</div>
                <div className="grid grid-cols-4 gap-3 text-right">
                  {kpis.map((kpi) => (
                    <div key={kpi.label} className="min-w-0">
                      <div className={`truncate font-mono text-sm font-semibold tabular-nums ${kpi.tone}`}>{kpi.text}</div>
                      <div className="mt-0.5 text-[10px] text-gray-600">{kpi.label}</div>
                    </div>
                  ))}
                </div>
                <div className="flex items-center justify-end gap-2">
                  {selectable ? <label className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-lg border border-crypto-border px-3 text-xs text-gray-400"><input aria-label={`选择 ${run.name}`} type="checkbox" checked={selected.includes(run.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, run.id] : current.filter((id) => id !== run.id))} className="h-3.5 w-3.5 accent-purple-500" />对比</label> : null}
                  <button type="button" onClick={() => navigate(`/backtest/${run.id}`)} className="inline-flex h-9 items-center gap-2 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 text-xs font-semibold text-blue-300 transition hover:bg-blue-500/20"><Eye className="h-3.5 w-3.5" />详情</button>
                </div>
              </div>
            );
          })}
          {visibleRuns.length === 0 ? <div className="flex min-h-60 flex-col items-center justify-center px-4 py-10 text-center"><FlaskConical className="h-8 w-8 text-gray-700" /><p className="mt-3 text-sm text-gray-500">当前筛选下没有回测实例</p><p className="mt-1 text-xs text-gray-700">创建首个实例，或调整上方筛选条件。</p></div> : null}
        </div>
      </section>

      <section className={`${panel} mb-5 overflow-hidden`} data-testid="backtest-job-console">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-5 py-4">
          <div>
            <div className="flex items-center gap-2">
              <Terminal className="h-4 w-4 text-cyan-400" />
              <h2 className="font-semibold text-white">任务队列</h2>
              <span className="text-xs text-gray-600">{visibleJobs.length} 个持久化任务</span>
            </div>
            <p className="mt-1 text-[11px] text-gray-600">本地持久化状态与增量日志；页面关闭后仍可追踪，后端重启会标记为已中断。</p>
          </div>
          <button type="button" onClick={() => void load()} className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border px-3 text-xs text-gray-400 hover:text-white">
            <RefreshCw className="h-3.5 w-3.5" />刷新任务
          </button>
        </div>
        <div className="space-y-3 p-4">
          {visibleJobs.slice(0, 20).map((job) => {
            const active = ['pending', 'running', 'cancelling'].includes(job.status);
            const retryable = ['failed', 'cancelled', 'interrupted'].includes(job.status);
            const statusTone = job.status === 'success'
              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
              : job.status === 'failed' || job.status === 'interrupted'
                ? 'border-red-500/30 bg-red-500/10 text-red-300'
                : job.status === 'cancelled' || job.status === 'cancelling'
                  ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
                  : 'border-blue-500/30 bg-blue-500/10 text-blue-300';
            const walkForwardResult = job.job_type === 'walk_forward'
              && job.result_payload
              && 'execution_version' in job.result_payload
              ? job.result_payload as WalkForwardExecutionResult
              : null;
            return (
              <article key={job.job_id} className="rounded-xl border border-crypto-border bg-[#0c1119] p-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded-full border px-2 py-1 text-[10px] font-semibold ${statusTone}`}>{statusLabel(job.status)}</span>
                      <span className="text-xs font-semibold text-gray-300">{job.job_type === 'walk_forward' ? 'Walk-forward' : job.run_mode === 'quick' ? '快速预检' : '完整回测'} · 第 {job.attempt} 次</span>
                      <span className="text-[10px] text-gray-600">{job.created_at ? `创建于 ${job.created_at}` : '创建时间未记录'}</span>
                    </div>
                    <p className="mt-2 text-xs text-gray-500">{job.message || job.phase}</p>
                    {job.error_message ? <p className="mt-1 text-xs text-red-300">{job.error_message}</p> : null}
                    <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-gray-800">
                      <div className={`h-full transition-all ${job.status === 'failed' ? 'bg-red-500' : job.status === 'success' ? 'bg-emerald-500' : 'bg-blue-500'}`} style={{ width: `${Math.max(0, Math.min(Number(job.progress), 100))}%` }} />
                    </div>
                    <div className="mt-1 flex justify-between text-[10px] text-gray-700"><span>{job.phase}</span><span>{Number(job.progress).toFixed(0)}%</span></div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button type="button" onClick={() => void toggleJobLog(job.job_id)} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-crypto-border px-2.5 text-[11px] text-gray-400 hover:text-white"><FileText className="h-3.5 w-3.5" />任务日志</button>
                    {active ? <button type="button" onClick={() => void controlJob(job, 'cancel')} disabled={Boolean(busy)} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 text-[11px] text-amber-300 disabled:opacity-40"><Square className="h-3 w-3" />停止任务</button> : null}
                    {retryable ? <button type="button" onClick={() => void controlJob(job, 'retry')} disabled={Boolean(busy)} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 px-2.5 text-[11px] text-blue-300 disabled:opacity-40"><RotateCcw className="h-3.5 w-3.5" />重试任务</button> : null}
                    {walkForwardResult ? <button type="button" onClick={() => setSelectedWalkForwardResult(walkForwardResult)} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-purple-500/30 bg-purple-500/10 px-2.5 text-[11px] font-semibold text-purple-200"><CalendarRange className="h-3.5 w-3.5" />折叠结果</button> : null}
                    {job.backtest_run_id ? <button type="button" onClick={() => navigate(`/backtest/${job.backtest_run_id}`)} className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-emerald-600 px-2.5 text-[11px] font-semibold text-white"><Eye className="h-3.5 w-3.5" />结果证据</button> : null}
                  </div>
                </div>
                {openJobLog === job.job_id ? (
                  <div className="mt-4 max-h-52 overflow-auto rounded-lg border border-crypto-border bg-black/25 p-3 font-mono text-[11px] leading-5">
                    {(jobLogs[job.job_id] || []).map((item) => <div key={item.id} className={item.level === 'error' ? 'text-red-300' : item.level === 'warning' ? 'text-amber-300' : 'text-gray-400'}><span className="text-gray-700">{item.created_at.slice(11, 19)} [{item.phase}]</span> {item.message}</div>)}
                    {(jobLogs[job.job_id] || []).length === 0 ? <div className="text-gray-600">暂无任务日志</div> : null}
                  </div>
                ) : null}
              </article>
            );
          })}
          {visibleJobs.length === 0 ? <div className="flex min-h-28 items-center justify-center text-sm text-gray-600">当前分区暂无持久化回测任务；创建后会在这里显示状态与日志。</div> : null}
        </div>
      </section>

      {walkForwardOpen && config ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm" onMouseDown={() => !walkForwardBusy && setWalkForwardOpen(false)}>
          <section role="dialog" aria-modal="true" aria-labelledby="walk-forward-title" className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-crypto-border bg-[#10161f] shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between border-b border-crypto-border px-6 py-5">
              <div>
                <h2 id="walk-forward-title" className="text-lg font-semibold text-white">滚动样本外计划</h2>
                <p className="mt-1 text-xs text-gray-500">先冻结封存快照与无重叠交易日窗口；本步骤不执行优化、不生成晋级证据。</p>
              </div>
              <button type="button" onClick={() => setWalkForwardOpen(false)} disabled={walkForwardBusy} className="rounded-lg p-2 text-gray-500 hover:bg-white/5 hover:text-white disabled:opacity-40"><X className="h-4 w-4" /></button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-6">
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                <Field label="数据快照"><select className={input} value={datasetSnapshotId} onChange={(event) => { setDatasetSnapshotId(Number(event.target.value)); setWalkForwardPreview(null); }}>{config.dataset_snapshots.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
                <Field label="开始日期"><input type="date" className={input} value={startDate} onChange={(event) => { setStartDate(event.target.value); setWalkForwardPreview(null); }} /></Field>
                <Field label="结束日期"><input type="date" className={input} value={endDate} onChange={(event) => { setEndDate(event.target.value); setWalkForwardPreview(null); }} /></Field>
                <Field label="训练交易日"><input aria-label="训练交易日" type="number" min={1} max={2000} className={input} value={trainSessions} onChange={(event) => { setTrainSessions(Number(event.target.value)); setWalkForwardPreview(null); }} /></Field>
                <Field label="测试交易日"><input aria-label="测试交易日" type="number" min={1} max={500} className={input} value={testSessions} onChange={(event) => { setTestSessions(Number(event.target.value)); setWalkForwardPreview(null); }} /></Field>
                <Field label="步进交易日"><input aria-label="步进交易日" type="number" min={1} max={500} className={input} value={stepSessions} onChange={(event) => { setStepSessions(Number(event.target.value)); setWalkForwardPreview(null); }} /></Field>
                <Field label="优化目标"><select aria-label="Walk-forward 优化目标" className={input} value={walkForwardObjective} onChange={(event) => setWalkForwardObjective(event.target.value as typeof walkForwardObjective)}><option value="sharpe">夏普比率（越高越好）</option><option value="sortino">索提诺比率（越高越好）</option><option value="strategy_return">策略收益（越高越好）</option><option value="maximum_drawdown">最大回撤（越低越好）</option></select></Field>
                <label className="block md:col-span-2"><span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-gray-500">参数矩阵 JSON</span><textarea aria-label="Walk-forward 参数矩阵" className="h-24 w-full rounded-lg border border-crypto-border bg-crypto-bg p-3 font-mono text-xs leading-5 text-gray-300 outline-none focus:border-purple-500/60" value={walkForwardGrid} onChange={(event) => setWalkForwardGrid(event.target.value)} /></label>
              </div>

              {walkForwardError ? <div className="mt-4 rounded-lg border border-red-500/25 bg-red-500/10 p-3 text-xs text-red-200">{walkForwardError}</div> : null}
              {walkForwardPreview ? (
                <section className="mt-5 overflow-hidden rounded-xl border border-crypto-border bg-black/10">
                  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-4 py-3">
                    <div className="text-sm font-semibold text-white">共 {walkForwardPreview.n_folds} 折 · {walkForwardPreview.date_count} 个可用交易日</div>
                    <span className="rounded-full border border-amber-500/25 bg-amber-500/10 px-2.5 py-1 text-[11px] font-semibold text-amber-300">预览不可晋级模拟盘</span>
                  </div>
                  <div className="divide-y divide-white/[0.05]">
                    {walkForwardPreview.folds.map((fold) => (
                      <div key={fold.index} className="grid gap-3 px-4 py-3 text-xs sm:grid-cols-[4rem_1fr_1fr]">
                        <div className="font-semibold text-blue-300">第 {fold.index} 折</div>
                        <div><div className="text-[10px] text-gray-600">训练</div><div className="mt-1 font-mono text-gray-300">{fold.train_start} → {fold.train_end}</div></div>
                        <div><div className="text-[10px] text-gray-600">样本外</div><div className="mt-1 font-mono text-emerald-300">{fold.test_start} → {fold.test_end}</div></div>
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}
            </div>
            <div className="flex items-center justify-between gap-3 border-t border-crypto-border px-6 py-4">
              <span className="text-[11px] text-gray-600">训练结束后的下一可用交易日才进入 OOS，禁止同日重叠。</span>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => void buildWalkForwardPreview()} disabled={walkForwardBusy} className="inline-flex h-10 items-center gap-2 rounded-lg border border-purple-500/30 bg-purple-500/10 px-4 text-sm font-semibold text-purple-200 disabled:opacity-50"><CalendarRange className="h-4 w-4" />{walkForwardBusy ? '生成中…' : '生成折叠计划'}</button>
                {walkForwardPreview ? <button type="button" onClick={() => void startWalkForwardJob()} disabled={walkForwardBusy} className="inline-flex h-10 items-center gap-2 rounded-lg bg-purple-600 px-5 text-sm font-semibold text-white disabled:opacity-50"><Play className="h-4 w-4" />{walkForwardBusy ? '正在入队…' : '启动 Walk-forward 任务'}</button> : null}
              </div>
            </div>
          </section>
        </div>
      ) : null}

      {createOpen && config ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm" onMouseDown={closeCreate}>
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
                {strategyOptions.map((item) => <button key={item.id} type="button" onClick={() => setStrategyVersionId(item.id)} className={`rounded-xl border p-4 text-left transition ${strategyVersionId === item.id ? 'border-purple-500/50 bg-purple-500/10' : 'border-crypto-border bg-black/10 hover:border-slate-600'}`}><div className="flex items-start justify-between gap-3"><div><div className="font-semibold text-gray-100">{item.name}</div><p className="mt-1 line-clamp-2 text-xs leading-5 text-gray-500">{item.description || '未填写策略说明'}</p></div><span className="shrink-0 rounded border border-blue-500/25 bg-blue-500/10 px-2 py-1 text-[10px] text-blue-300">v{item.version}</span></div><p className="mt-3 text-[10px] text-emerald-400/80">{item.content_hash ? '版本内容已校验' : '版本内容待校验'}</p></button>)}
              </div>
            </div> : null}
            {createStep === 2 ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <Field label="数据快照"><select className={input} value={datasetSnapshotId} onChange={(event) => setDatasetSnapshotId(Number(event.target.value))}>{config.dataset_snapshots.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
              <Field label="股票范围"><select className={input} value={universeSnapshotId} onChange={(event) => setUniverseSnapshotId(Number(event.target.value))}>{config.universe_snapshots.map((item) => <option key={item.id} value={item.id}>{item.code} · {item.member_count}只</option>)}</select></Field>
              <Field label="因子快照" hint="可选，且须与数据及股票范围兼容"><select className={input} value={factorSnapshotId} onChange={(event) => setFactorSnapshotId(Number(event.target.value))}><option value={0}>不绑定</option>{config.factor_snapshots.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
              <Field label="股票池快照"><select className={input} value={poolSnapshotId} onChange={(event) => { const id = Number(event.target.value); setPoolSnapshotId(id); const pool = config.pool_snapshots.find((item) => item.id === id); if (pool) { setDatasetSnapshotId(pool.dataset_snapshot_id); setUniverseSnapshotId(pool.universe_snapshot_id); setFactorSnapshotId(pool.factor_snapshot_id ?? 0); setSymbols(''); } }}><option value={0}>不绑定</option>{config.pool_snapshots.map((item) => <option key={item.id} value={item.id}>{item.pool_name} · {item.member_count}只</option>)}</select></Field>
              <Field label="成本模型"><select className={input} value={costModelId} onChange={(event) => setCostModelId(event.target.value)}>{config.cost_models.map((item) => <option key={item.id} value={item.id}>{item.name} · v{item.version}</option>)}</select></Field>
              <Field label="研究协议" hint="不绑定则不能晋级模拟盘"><select className={input} value={protocolId} onChange={(event) => { const id = event.target.value; setProtocolId(id); const protocol = config.protocols.find((item) => item.id === id); if (protocol) { setStartDate(protocol.train_start); setEndDate(protocol.out_of_sample_end); } }}><option value="">不绑定</option>{config.protocols.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
              <Field label="股票代码" hint={poolSnapshotId ? '由股票池快照提供' : '英文逗号分隔，例如 600519.SH'}><input className={input} value={poolSnapshotId ? `${selectedPool?.pool_name ?? '已选股票池'} · ${selectedPool?.member_count ?? '--'}只` : symbols} readOnly={Boolean(poolSnapshotId)} onChange={(event) => setSymbols(event.target.value)} /></Field>
              <Field label="开始日期"><input type="date" className={input} value={startDate} onChange={(event) => setStartDate(event.target.value)} /></Field>
              <Field label="结束日期"><input type="date" className={input} value={endDate} onChange={(event) => setEndDate(event.target.value)} /></Field>
              <Field label="初始资金"><input type="number" min={10000} step={10000} className={input} value={initialCash} onChange={(event) => setInitialCash(Number(event.target.value))} /></Field>
              <Field label="策略参数 JSON"><input className={input} value={parameters} onChange={(event) => setParameters(event.target.value)} /></Field>
              <Field label="基准"><input className={input} value={selectedProtocol?.benchmark_code ?? '000300.SH'} readOnly /></Field>
            </div> : null}
            {createStep === 3 ? <div className="grid gap-5 xl:grid-cols-[1.05fr_.95fr]">
              <div className="space-y-4">
                <section className="rounded-xl border border-crypto-border bg-black/10 p-4"><div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-emerald-400" /><h3 className="text-sm font-semibold text-white">实验配置确认</h3></div><dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">{[
                  ['策略版本', `${selectedVersion?.name ?? '--'} · v${selectedVersion?.version ?? '--'}`],
                  ['回测区间', `${startDate} 至 ${endDate}`],
                  ['初始资金', `¥${initialCash.toLocaleString('zh-CN')}`],
                  ['证券范围', selectedPool ? `${selectedPool.pool_name} · ${selectedPool.member_count}只` : symbols || '--'],
                  ['数据快照', selectedDataset?.name ?? '--'],
                  ['股票范围', selectedUniverse ? `${selectedUniverse.code} · ${selectedUniverse.member_count}只` : '--'],
                  ['成本模型', selectedCostModel ? `${selectedCostModel.name} · v${selectedCostModel.version}` : '--'],
                  ['研究协议', selectedProtocol?.name ?? '未绑定（不可晋级）'],
                ].map(([label, value]) => <div key={label} className="rounded-lg border border-white/[0.05] bg-white/[0.02] p-3"><dt className="text-gray-600">{label}</dt><dd className="mt-1 font-medium text-gray-300">{value}</dd></div>)}</dl></section>
                <section className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4 text-xs leading-6 text-amber-200/80"><strong>执行规则：</strong>A 股日线信号最早于下一可交易日成交；100 股整数手、T+1、停牌与涨跌停约束均进入订单证据。快速预检不可对比或晋级。</section>
              </div>
              <section className="rounded-xl border border-crypto-border bg-black/10 p-4"><div className="flex items-center gap-2"><Beaker className="h-4 w-4 text-purple-400" /><h3 className="text-sm font-semibold text-white">参数矩阵</h3></div><p className="mt-2 text-xs text-gray-600">可选：运行 1–24 个组合检验参数稳定性。</p><textarea value={grid} onChange={(event) => setGrid(event.target.value)} className="mt-4 h-28 w-full rounded-lg border border-crypto-border bg-crypto-bg p-3 font-mono text-xs leading-6 text-gray-300 outline-none focus:border-purple-500/60" /><button type="button" onClick={() => void runMatrix()} disabled={Boolean(busy)} className="mt-3 inline-flex h-9 items-center gap-2 rounded-lg border border-purple-500/30 bg-purple-500/10 px-3 text-xs font-semibold text-purple-300 disabled:opacity-50"><Beaker className="h-3.5 w-3.5" />{busy === 'matrix' ? '矩阵运行中…' : '运行参数矩阵'}</button><div className="mt-5 border-t border-crypto-border pt-4"><div className="text-xs font-semibold text-gray-400">策略代码摘要</div><pre className="mt-3 max-h-44 overflow-auto rounded-lg bg-[#080c12] p-3 text-[10px] leading-5 text-blue-100"><code>{selectedVersion?.content_hash ? `内容哈希 ${selectedVersion.content_hash}` : '请选择策略版本'}</code></pre></div></section>
            </div> : null}
          </div>
          <div className="flex shrink-0 items-center justify-between border-t border-crypto-border px-6 py-4">
            <button type="button" onClick={() => createStep === 1 ? closeCreate() : setCreateStep((createStep - 1) as 1 | 2)} className="h-10 rounded-lg border border-crypto-border px-4 text-sm text-gray-400 hover:text-white">{createStep === 1 ? '取消' : '上一步'}</button>
            {createStep < 3 ? <button type="button" disabled={createStep === 1 && !strategyVersionId} onClick={() => setCreateStep((createStep + 1) as 2 | 3)} className="inline-flex h-10 items-center gap-2 rounded-lg bg-purple-600 px-5 text-sm font-semibold text-white disabled:opacity-40">下一步<ChevronRight className="h-4 w-4" /></button> : <div className="flex items-center gap-2"><button type="button" onClick={() => void executeFromWizard('quick')} disabled={Boolean(busy)} className="inline-flex h-10 items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 text-sm font-semibold text-amber-300 disabled:opacity-50"><Zap className="h-4 w-4" />{busy === 'quick' ? '正在入队…' : '快速预检'}</button><button data-testid="run-full-backtest" type="button" onClick={() => void executeFromWizard('full')} disabled={Boolean(busy)} className="inline-flex h-10 items-center gap-2 rounded-lg bg-purple-600 px-5 text-sm font-semibold text-white disabled:opacity-50"><Play className="h-4 w-4" />{busy === 'full' ? '正在入队…' : '创建回测任务'}</button></div>}
          </div>
        </section>
      </div> : null}

      {compareData ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-5" onMouseDown={() => setCompareData(null)}><section className="max-h-[88vh] w-full max-w-6xl overflow-auto rounded-2xl border border-crypto-border bg-crypto-card shadow-2xl" onMouseDown={(event) => event.stopPropagation()}><div className="sticky top-0 flex items-center justify-between border-b border-crypto-border bg-crypto-card px-6 py-4"><div><h2 className="font-semibold text-white">完整回测对比</h2><p className="mt-1 text-xs text-gray-500">{compareData.runs.length} 个回测结果</p></div><button type="button" onClick={() => setCompareData(null)} className="text-sm text-gray-400">关闭</button></div><div className="p-6"><GenericTable rows={compareData.runs.map((run) => ({ name: run.name, strategy: run.strategy_name, period: `${run.start_date} — ${run.end_date}`, return: formatValue(run.metrics?.strategy_return, 'ratio'), drawdown: formatValue(run.metrics?.maximum_drawdown, 'ratio'), sharpe: formatValue(run.metrics?.sharpe) }))} columns={[["name", "运行"], ["strategy", "策略"], ["period", "区间"], ["return", "收益"], ["drawdown", "回撤"], ["sharpe", "Sharpe"]]} /></div></section></div> : null}

      {selectedWalkForwardResult ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-5" onMouseDown={() => setSelectedWalkForwardResult(null)}>
          <section role="dialog" aria-modal="true" aria-labelledby="walk-forward-result-title" className="max-h-[90vh] w-full max-w-5xl overflow-auto rounded-2xl border border-crypto-border bg-crypto-card shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
            <div className="sticky top-0 z-10 flex items-start justify-between border-b border-crypto-border bg-crypto-card px-6 py-4">
              <div><h2 id="walk-forward-result-title" className="font-semibold text-white">Walk-forward OOS 结果</h2><p className="mt-1 text-xs text-gray-500">{selectedWalkForwardResult.n_folds} 折 · {selectedWalkForwardResult.n_combinations} 组参数 · {selectedWalkForwardResult.objective}</p></div>
              <button type="button" onClick={() => setSelectedWalkForwardResult(null)} className="text-sm text-gray-400">关闭</button>
            </div>
            <div className="space-y-5 p-6">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <OperatorMetricCard label="OOS复利收益" value={formatValue(selectedWalkForwardResult.summary.compounded_oos_return, 'ratio')} tone={selectedWalkForwardResult.summary.compounded_oos_return >= 0 ? 'up' : 'down'} />
                <OperatorMetricCard label="一致性" value={formatValue(selectedWalkForwardResult.summary.consistency, 'ratio')} tone="blue" />
                <OperatorMetricCard label="样本内目标" value={formatValue(selectedWalkForwardResult.summary.avg_is_objective)} tone="blue" />
                <OperatorMetricCard label="样本外目标" value={formatValue(selectedWalkForwardResult.summary.avg_oos_objective)} tone="amber" detail={`退化 ${formatValue(selectedWalkForwardResult.summary.degradation)}`} />
              </div>
              <div className="rounded-xl border border-amber-500/20 bg-amber-500/[0.06] p-4 text-xs leading-6 text-amber-200/80">
                <strong>不可直接晋级模拟盘：</strong>{selectedWalkForwardResult.promotion_reason}
              </div>
              <div className="overflow-hidden rounded-xl border border-crypto-border">
                {selectedWalkForwardResult.folds.map((fold) => (
                  <article key={fold.index} className="grid gap-4 border-b border-white/[0.05] p-4 text-xs last:border-b-0 lg:grid-cols-[4rem_1fr_1fr_1fr]">
                    <div className="font-semibold text-blue-300">第 {fold.index} 折</div>
                    <div><div className="text-[10px] text-gray-600">训练 / IS</div><div className="mt-1 font-mono text-gray-300">{fold.train_start} → {fold.train_end}</div><div className="mt-1 text-gray-500">目标 {formatValue(fold.is_objective)}</div></div>
                    <div><div className="text-[10px] text-gray-600">样本外 / OOS</div><div className="mt-1 font-mono text-emerald-300">{fold.test_start} → {fold.test_end}</div><div className="mt-1 text-gray-500">收益 {formatValue(fold.oos_return, 'ratio')}</div></div>
                    <div><div className="text-[10px] text-gray-600">最优参数</div><div className="mt-1 font-mono text-purple-200">{Object.entries(fold.best_parameters).map(([key, value]) => `${key}=${String(value)}`).join(' · ') || '—'}</div><div className={`mt-1 ${fold.oos_degraded ? 'text-red-300' : 'text-emerald-300'}`}>{fold.oos_degraded ? '样本外退化' : '未检测到退化'}</div></div>
                  </article>
                ))}
              </div>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
