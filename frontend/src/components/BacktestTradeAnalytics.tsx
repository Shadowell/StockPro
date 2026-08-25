import { useEffect, useMemo, useRef } from 'react';
import * as echarts from 'echarts';
import { useSettingsStore } from '../stores/useSettingsStore';

interface TradeLike {
  timestamp: number;
  pnl: number;
  reason?: string;
}

interface BacktestTradeAnalyticsProps {
  trades: TradeLike[];
  height?: number;
}

const AXIS_COLOR = '#8b949e';
const SPLIT_COLOR = '#21262d';
const STRATEGY_COLOR = '#58a6ff';

function compactMoney(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(2)}`;
}

/**
 * 交易分析：累计盈亏阶梯、单笔盈亏分布直方图、交易原因分布。
 * 只消费结果已落库的真实成交记录，成交为空时整体不渲染。
 */
export default function BacktestTradeAnalytics({ trades, height = 460 }: BacktestTradeAnalyticsProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);
  const { upColor, downColor } = useSettingsStore((s) => s.getColors());

  const model = useMemo(() => {
    const rows = [...(trades || [])]
      .filter((trade) => Number.isFinite(trade?.timestamp))
      .sort((a, b) => a.timestamp - b.timestamp);
    if (rows.length === 0) return null;

    // 1) 累计盈亏阶梯
    let cum = 0;
    const cumPoints: Array<[number, number]> = [];
    for (const trade of rows) {
      cum += trade.pnl || 0;
      cumPoints.push([trade.timestamp, Number(cum.toFixed(4))]);
    }

    // 2) 单笔盈亏分布直方图（排除 0 盈亏成交，如开仓腿）
    const pnls = rows.map((trade) => trade.pnl || 0).filter((pnl) => pnl !== 0);
    let bins: Array<{ left: number; right: number; count: number; positive: boolean }> = [];
    if (pnls.length >= 3) {
      const min = Math.min(...pnls);
      const max = Math.max(...pnls);
      const span = max - min || 1;
      const binCount = Math.min(24, Math.max(8, Math.ceil(Math.sqrt(pnls.length))));
      const width = span / binCount;
      const counts = new Array<number>(binCount).fill(0);
      for (const pnl of pnls) {
        const idx = Math.min(binCount - 1, Math.max(0, Math.floor((pnl - min) / width)));
        counts[idx] += 1;
      }
      bins = counts.map((count, idx) => {
        const left = min + idx * width;
        const right = left + width;
        return { left, right, count, positive: (left + right) / 2 >= 0 };
      });
    }

    // 3) 交易原因分布（按笔数，附累计盈亏）
    const reasonMap = new Map<string, { count: number; pnl: number }>();
    for (const trade of rows) {
      const reason = (trade.reason || '').trim() || '未注明';
      const entry = reasonMap.get(reason) || { count: 0, pnl: 0 };
      entry.count += 1;
      entry.pnl += trade.pnl || 0;
      reasonMap.set(reason, entry);
    }
    const reasons = Array.from(reasonMap.entries())
      .sort((a, b) => b[1].count - a[1].count)
      .slice(0, 8)
      .map(([name, stat]) => ({ name, ...stat }))
      .reverse();

    return { rows, cumPoints, bins, reasons };
  }, [trades]);

  const option = useMemo(() => {
    if (!model) return null;
    const { cumPoints, bins, reasons } = model;

    return {
      backgroundColor: 'transparent',
      animation: true,
      animationDuration: 900,
      animationEasing: 'cubicOut' as const,
      tooltip: {
        backgroundColor: 'rgba(13, 17, 23, 0.96)',
        borderColor: '#30363D',
        textStyle: { color: '#e6edf3', fontSize: 12 },
      },
      grid: [
        { left: 64, right: 24, top: 12, height: '34%' },
        { left: 64, right: '52%', top: '56%', height: '32%' },
        { left: '54%', right: 24, top: '56%', height: '32%', containLabel: true },
      ],
      xAxis: [
        {
          type: 'time',
          gridIndex: 0,
          axisLine: { lineStyle: { color: '#30363D' } },
          axisLabel: { color: AXIS_COLOR, fontSize: 10, hideOverlap: true },
          axisTick: { show: false },
          splitLine: { show: false },
        },
        {
          type: 'value',
          gridIndex: 1,
          axisLine: { lineStyle: { color: '#30363D' } },
          axisLabel: {
            color: AXIS_COLOR,
            fontSize: 10,
            formatter: (value: number) => compactMoney(value),
          },
          splitLine: { lineStyle: { color: SPLIT_COLOR } },
        },
        {
          type: 'value',
          gridIndex: 2,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { show: false },
          splitLine: { show: false },
        },
      ],
      yAxis: [
        {
          type: 'value',
          gridIndex: 0,
          splitLine: { lineStyle: { color: SPLIT_COLOR } },
          axisLabel: { color: AXIS_COLOR, fontSize: 10, formatter: (value: number) => compactMoney(value) },
        },
        {
          type: 'value',
          gridIndex: 1,
          splitLine: { show: false },
          axisLabel: { color: AXIS_COLOR, fontSize: 10 },
        },
        {
          type: 'category',
          gridIndex: 2,
          data: reasons.map((row) => row.name),
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { color: '#e6edf3', fontSize: 10, width: 96, overflow: 'truncate' },
        },
      ],
      series: [
        {
          name: '累计盈亏',
          type: 'line',
          data: cumPoints,
          xAxisIndex: 0,
          yAxisIndex: 0,
          symbol: 'none',
          sampling: 'lttb',
          step: 'end',
          lineStyle: { color: STRATEGY_COLOR, width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(88, 166, 255, 0.2)' },
              { offset: 1, color: 'rgba(88, 166, 255, 0.02)' },
            ]),
          },
          tooltip: {
            valueFormatter: (value: number) => compactMoney(value),
          },
        },
        ...(bins.length
          ? [
              {
                name: '单笔盈亏分布',
                type: 'bar',
                data: bins.map((bin) => ({
                  value: bin.count,
                  itemStyle: { color: bin.positive ? upColor : downColor, opacity: 0.82, borderRadius: [3, 3, 0, 0] },
                })),
                xAxisIndex: 1,
                yAxisIndex: 1,
                barCategoryGap: '18%',
                tooltip: {
                  formatter: (params: any) => {
                    const bin = bins[params.dataIndex];
                    return `单笔盈亏 ${compactMoney(bin.left)} ~ ${compactMoney(bin.right)}<br/>笔数：<b>${bin.count}</b>`;
                  },
                },
              },
            ]
          : []),
        {
          name: '交易原因',
          type: 'bar',
          data: reasons.map((row) => ({
            value: row.count,
            itemStyle: {
              color: row.pnl >= 0 ? 'rgba(88, 166, 255, 0.85)' : 'rgba(139, 148, 158, 0.75)',
              borderRadius: [0, 4, 4, 0],
            },
          })),
          xAxisIndex: 2,
          yAxisIndex: 2,
          barMaxWidth: 14,
          tooltip: {
            formatter: (params: any) => {
              const row = reasons[params.dataIndex];
              return `${row.name}<br/>笔数：<b>${row.count}</b><br/>累计盈亏：<span style="color:${row.pnl >= 0 ? upColor : downColor}">${compactMoney(row.pnl)}</span>`;
            },
          },
        },
      ],
    };
  }, [model, upColor, downColor]);

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
    if (!chartInstance.current || !option) return;
    chartInstance.current.setOption(option, { notMerge: true });
  }, [option]);

  if (!model) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center rounded-lg border border-dashed border-crypto-border bg-crypto-bg/40 text-sm text-gray-500"
      >
        暂无成交记录，无法生成交易分析
      </div>
    );
  }

  return <div ref={chartRef} style={{ width: '100%', height }} />;
}
