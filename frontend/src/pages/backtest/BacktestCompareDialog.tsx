import { useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { Loader2, X } from 'lucide-react';
import { backtestApi } from '../../api/client';
import type { BacktestResult } from './backtestSupport';
import { historyDetailToBacktestResult, strategyNameById } from './backtestSupport';
import { useSettingsStore } from '../../stores/useSettingsStore';

export interface CompareEntryInput {
  key: string;
  result: BacktestResult | null;
  historyId?: number | null;
  strategyId: number | null;
}

interface CompareSeries {
  label: string;
  timeframe: string;
  points: Array<[number, number]>;
}

interface CompareRow {
  key: string;
  result: BacktestResult;
}

const SERIES_COLORS = ['#58a6ff', '#22d3ee', '#a78bfa', '#34d399'];
const AXIS_COLOR = '#8b949e';
const SPLIT_COLOR = '#21262d';

function fmt(value: number | undefined | null, digits = 2): string {
  return value == null ? '-' : value.toFixed(digits);
}

function fmtPct(value: number | undefined | null): string {
  return value == null ? '-' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

/** 从规范策略名里取「策略名称」段做对比图例短名。 */
function shortLabel(result: BacktestResult): string {
  const name = result.strategyName || '';
  const parts = name.split('·').map((part) => part.trim()).filter(Boolean);
  if (parts.length >= 2) return `${parts[parts.length - 2]} ${result.timeframe || ''}`.trim();
  return `${name.slice(0, 16)} ${result.timeframe || ''}`.trim();
}

interface DiffMetric {
  label: string;
  value: (result: BacktestResult) => number | null;
  format: (value: number) => string;
  best: 'max' | 'min' | null;
}

const DIFF_METRICS: DiffMetric[] = [
  { label: '净收益', value: (r) => r.totalReturn ?? null, format: (v) => fmtPct(v), best: 'max' },
  { label: '年化收益', value: (r) => r.annualReturn ?? null, format: (v) => fmtPct(v), best: 'max' },
  { label: '最大回撤', value: (r) => r.maxDrawdown ?? null, format: (v) => `${fmt(v)}%`, best: 'min' },
  { label: '夏普', value: (r) => r.sharpeRatio ?? null, format: (v) => fmt(v), best: 'max' },
  { label: '胜率', value: (r) => r.winRate ?? null, format: (v) => `${fmt(v)}%`, best: 'max' },
  { label: '盈亏比', value: (r) => r.profitFactor ?? null, format: (v) => fmt(v), best: 'max' },
  { label: '交易数', value: (r) => r.totalTrades ?? null, format: (v) => `${v}`, best: null },
  { label: '手续费', value: (r) => r.totalFees ?? null, format: (v) => `$${fmt(v)}`, best: 'min' },
];

function CompareEquityOverlay({ series }: { series: CompareSeries[] }) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  const option = useMemo(
    () => ({
      backgroundColor: 'transparent',
      animation: true,
      animationDuration: 1000,
      animationEasing: 'cubicOut' as const,
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(13, 17, 23, 0.96)',
        borderColor: '#30363D',
        textStyle: { color: '#e6edf3', fontSize: 12 },
        valueFormatter: (value: number) => `${value >= 0 ? '+' : ''}${Number(value).toFixed(2)}%`,
      },
      legend: {
        top: 0,
        textStyle: { color: AXIS_COLOR, fontSize: 11 },
        itemWidth: 14,
        itemHeight: 2,
        icon: 'rect',
      },
      grid: { left: 60, right: 20, top: 34, bottom: 40 },
      xAxis: {
        type: 'time',
        axisLine: { lineStyle: { color: '#30363D' } },
        axisLabel: { color: AXIS_COLOR, fontSize: 10, hideOverlap: true },
        axisTick: { show: false },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: SPLIT_COLOR } },
        axisLabel: {
          color: AXIS_COLOR,
          fontSize: 10,
          formatter: (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(0)}%`,
        },
      },
      series: series.map((item, index) => ({
        name: item.label,
        type: 'line',
        data: item.points,
        symbol: 'none',
        sampling: 'lttb',
        lineStyle: { color: SERIES_COLORS[index % SERIES_COLORS.length], width: 2 },
        itemStyle: { color: SERIES_COLORS[index % SERIES_COLORS.length] },
        animationDelay: index * 220,
      })),
    }),
    [series],
  );

  useEffect(() => {
    if (!chartRef.current) return;
    chartInstance.current = echarts.init(chartRef.current);
    const observer = new ResizeObserver(() => chartInstance.current?.resize());
    observer.observe(chartRef.current);
    return () => {
      observer.disconnect();
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chartInstance.current) return;
    chartInstance.current.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={chartRef} style={{ width: '100%', height: 320 }} />;
}

/**
 * 回测对比面板：叠加权益曲线 + 指标差异表（最优值高亮）。
 * 本地实例直接用已加载结果，历史记录逐条拉取完整结果。
 */
export default function BacktestCompareDialog({
  open,
  entries,
  strategies,
  onClose,
}: {
  open: boolean;
  entries: CompareEntryInput[];
  strategies: any[];
  onClose: () => void;
}) {
  const [rows, setRows] = useState<CompareRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { upColor } = useSettingsStore((s) => s.getColors());

  useEffect(() => {
    if (!open) {
      setRows([]);
      setError('');
      return;
    }
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const loaded: CompareRow[] = [];
        for (const entry of entries) {
          let result = entry.result;
          if ((!result?.equityCurve || result.equityCurve.length === 0) && entry.historyId != null) {
            const detail = await backtestApi.getResult(entry.historyId);
            const name = strategyNameById(strategies, Number(detail.strategyId), detail.strategyName);
            result = historyDetailToBacktestResult(detail, name);
          }
          if (result) loaded.push({ key: entry.key, result });
        }
        if (!cancelled) setRows(loaded);
      } catch (err: any) {
        if (!cancelled) setError(String(err?.response?.data?.detail || err?.message || '加载对比数据失败'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, entries, strategies]);

  const series = useMemo(
    () =>
      rows
        .filter((row) => row.result.equityCurve && row.result.equityCurve.length >= 2)
        .map((row) => {
          const sorted = [...row.result.equityCurve!].sort((a, b) => a.timestamp - b.timestamp);
          const base = sorted[0].equity > 0 ? sorted[0].equity : row.result.initialCapital || 1;
          return {
            label: shortLabel(row.result),
            timeframe: row.result.timeframe || '',
            points: sorted.map((point) => [point.timestamp, (point.equity / base - 1) * 100] as [number, number]),
          };
        }),
    [rows],
  );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-crypto-border bg-crypto-card shadow-2xl shadow-black/40">
        <div className="flex items-start justify-between gap-4 border-b border-crypto-border px-6 py-4">
          <div>
            <h2 className="text-lg font-bold text-white">回测对比</h2>
            <p className="mt-0.5 text-xs text-gray-500">
              叠加累计收益曲线并排核心指标，最多同时对比 4 条记录。
            </p>
          </div>
          <button
            type="button"
            aria-label="关闭对比"
            onClick={onClose}
            className="rounded-lg border border-crypto-border p-2 text-gray-500 hover:text-gray-300"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {loading ? (
            <div className="flex h-64 items-center justify-center text-sm text-gray-500">
              <Loader2 className="mr-2 h-4 w-4 animate-spin text-blue-400" />
              正在加载对比数据…
            </div>
          ) : error ? (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">{error}</div>
          ) : rows.length === 0 ? (
            <div className="flex h-64 items-center justify-center text-sm text-gray-500">没有可对比的回测结果</div>
          ) : (
            <div className="space-y-5">
              <section className="rounded-xl border border-crypto-border bg-crypto-bg/45 p-4">
                <div className="mb-2 text-xs font-semibold text-gray-400">累计收益对比（%）</div>
                {series.length > 0 ? (
                  <CompareEquityOverlay series={series} />
                ) : (
                  <div className="flex h-40 items-center justify-center text-sm text-gray-500">所选记录缺少权益曲线</div>
                )}
              </section>

              <section className="overflow-x-auto rounded-xl border border-crypto-border">
                <table className="w-full min-w-[560px] text-sm">
                  <thead className="bg-crypto-bg/60 text-xs text-gray-500">
                    <tr>
                      <th className="px-4 py-2.5 text-left font-medium">指标</th>
                      {rows.map((row) => (
                        <th key={row.key} className="px-4 py-2.5 text-right font-medium">
                          <span className="block max-w-[180px] truncate text-gray-300">{shortLabel(row.result)}</span>
                          <span className="block text-[10px] font-normal text-gray-600">
                            {row.result.startDate} ~ {row.result.endDate}
                          </span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-crypto-border/70">
                    {DIFF_METRICS.map((metric) => {
                      const values = rows.map((row) => metric.value(row.result));
                      const finite = values.filter((value): value is number => value != null);
                      const bestValue =
                        metric.best && finite.length >= 2
                          ? metric.best === 'max'
                            ? Math.max(...finite)
                            : Math.min(...finite)
                          : null;
                      return (
                        <tr key={metric.label}>
                          <td className="px-4 py-2 text-xs text-gray-500">{metric.label}</td>
                          {values.map((value, index) => {
                            const isBest =
                              bestValue != null && value != null && Math.abs(value - bestValue) < 1e-9;
                            return (
                              <td
                                key={rows[index].key}
                                className={`px-4 py-2 text-right text-xs font-semibold tabular-nums ${
                                  isBest ? 'rounded bg-yellow-500/15 text-yellow-100' : 'text-gray-200'
                                }`}
                              >
                                {value == null ? '-' : metric.format(value)}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </section>
              <p className="text-[11px] leading-5 text-gray-600">
                对比曲线按各自回测起点归一化为累计收益百分比；黄色高亮为该指标下的最优值（回撤、手续费取最小值）。
                当前主题上涨色 <span style={{ color: upColor }}>■</span> 用于正贡献方向。
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
