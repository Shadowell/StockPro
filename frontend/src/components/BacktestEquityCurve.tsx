import { useEffect, useMemo, useRef } from 'react';
import * as echarts from 'echarts';
import { useSettingsStore } from '../stores/useSettingsStore';

interface EquityPoint {
  timestamp: number;
  equity: number;
  drawdown?: number;
}

interface BenchmarkPoint {
  timestamp: number;
  close: number;
}

interface BacktestEquityCurveProps {
  equityCurve: EquityPoint[];
  benchmarkKlines: BenchmarkPoint[];
  benchmarkSymbol: string;
  initialCapital: number;
  height?: number;
}

const AXIS_LABEL_COLOR = '#8b949e';
const SPLIT_LINE_COLOR = '#21262d';
const STRATEGY_LINE_COLOR = '#58a6ff';

/**
 * 回测权益曲线：策略累计收益（%）与基准累计收益（%）对比，下方为回撤区间。
 * 只消费已落库的真实权益曲线与真实基准 K 线，不做任何合成或插值外推；
 * 基准按日收盘 forward-fill 对齐到策略权益时间点。
 */
export default function BacktestEquityCurve({
  equityCurve,
  benchmarkKlines,
  benchmarkSymbol,
  initialCapital,
  height = 420,
}: BacktestEquityCurveProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);
  const { upColor, downColor } = useSettingsStore((s) => s.getColors());

  const series = useMemo(() => {
    const sorted = [...(equityCurve || [])]
      .filter((point) => Number.isFinite(point?.timestamp) && Number.isFinite(point?.equity))
      .sort((a, b) => a.timestamp - b.timestamp);
    if (sorted.length < 2) return null;

    const baseEquity = sorted[0].equity > 0 ? sorted[0].equity : initialCapital;
    const timestamps = sorted.map((point) => point.timestamp);
    const strategyReturns = sorted.map((point) =>
      baseEquity > 0 ? (point.equity / baseEquity - 1) * 100 : 0,
    );
    const drawdowns = sorted.map((point) => -(Math.abs(point.drawdown || 0)));

    const bench = [...(benchmarkKlines || [])]
      .filter((row) => Number.isFinite(row?.timestamp) && Number.isFinite(row?.close) && row.close > 0)
      .sort((a, b) => a.timestamp - b.timestamp);

    let benchmarkReturns: number[] | null = null;
    if (bench.length >= 2) {
      // 基线取策略起点当日（或其后第一个交易日）收盘，使基准与策略都从 0% 起步
      let baseIdx = bench.findIndex((row) => row.timestamp >= timestamps[0]);
      if (baseIdx === -1) baseIdx = bench.length - 1;
      const base = bench[baseIdx].close;
      let cursor = baseIdx;
      benchmarkReturns = timestamps.map((ts) => {
        while (cursor + 1 < bench.length && bench[cursor + 1].timestamp <= ts) cursor += 1;
        if (bench[cursor].timestamp > ts) return 0;
        return (bench[cursor].close / base - 1) * 100;
      });
    }

    return { timestamps, strategyReturns, drawdowns, benchmarkReturns };
  }, [equityCurve, benchmarkKlines, initialCapital]);

  const option = useMemo(() => {
    if (!series) return null;
    const { timestamps, strategyReturns, drawdowns, benchmarkReturns } = series;

    const tooltipFormatter = (params: any) => {
      if (!params || params.length === 0) return '';
      const time = params[0]?.axisValueLabel || params[0]?.axisValue || '';
      let html = `<div style="font-size:12px;"><div style="margin-bottom:4px;color:${AXIS_LABEL_COLOR}">${time}</div>`;
      params.forEach((param: any) => {
        const value = Number(param.value);
        if (!Number.isFinite(value)) return;
        if (param.seriesName === '策略累计收益') {
          html += `<div>策略累计：<span style="color:${value >= 0 ? upColor : downColor}">${value >= 0 ? '+' : ''}${value.toFixed(2)}%</span></div>`;
        } else if (param.seriesName === '基准累计收益') {
          html += `<div>${benchmarkSymbol}同期：<span style="color:${value >= 0 ? upColor : downColor}">${value >= 0 ? '+' : ''}${value.toFixed(2)}%</span></div>`;
        } else if (param.seriesName === '回撤') {
          html += `<div>回撤：<span style="color:${downColor}">${Math.abs(value).toFixed(2)}%</span></div>`;
        }
      });
      html += '</div>';
      return html;
    };

    return {
      backgroundColor: 'transparent',
      animation: true,
      animationDuration: 1100,
      animationEasing: 'cubicOut' as const,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross', label: { backgroundColor: '#161B22' } },
        backgroundColor: 'rgba(13, 17, 23, 0.96)',
        borderColor: '#30363D',
        textStyle: { color: '#e6edf3' },
        formatter: tooltipFormatter,
      },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [
        { left: 64, right: 24, top: 24, height: '52%' },
        { left: 64, right: 24, top: '72%', height: '16%' },
      ],
      xAxis: [
        {
          type: 'time',
          gridIndex: 0,
          axisLine: { lineStyle: { color: '#30363D' } },
          axisLabel: { color: AXIS_LABEL_COLOR, fontSize: 10, hideOverlap: true },
          axisTick: { show: false },
          splitLine: { show: false },
        },
        {
          type: 'time',
          gridIndex: 1,
          axisLine: { lineStyle: { color: '#30363D' } },
          axisLabel: { show: false },
          axisTick: { show: false },
          splitLine: { show: false },
        },
      ],
      yAxis: [
        {
          type: 'value',
          gridIndex: 0,
          splitLine: { lineStyle: { color: SPLIT_LINE_COLOR } },
          axisLabel: {
            color: AXIS_LABEL_COLOR,
            fontSize: 10,
            formatter: (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(0)}%`,
          },
        },
        {
          type: 'value',
          gridIndex: 1,
          min: (value: { min: number }) => (value.min < -1 ? Math.floor(value.min) : -1),
          splitNumber: 2,
          splitLine: { show: false },
          axisLine: { show: false },
          axisLabel: {
            color: AXIS_LABEL_COLOR,
            fontSize: 10,
            formatter: (value: number) => `${value.toFixed(0)}%`,
          },
        },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
        {
          show: true,
          xAxisIndex: [0, 1],
          type: 'slider',
          bottom: 6,
          height: 18,
          borderColor: '#30363D',
          backgroundColor: 'rgba(22, 27, 34, 0.9)',
          fillerColor: 'rgba(88, 166, 255, 0.16)',
          handleStyle: { color: '#58a6ff' },
          textStyle: { color: AXIS_LABEL_COLOR, fontSize: 10 },
        },
      ],
      series: [
        {
          name: '策略累计收益',
          type: 'line',
          data: timestamps.map((ts, i) => [ts, strategyReturns[i]]),
          xAxisIndex: 0,
          yAxisIndex: 0,
          symbol: 'none',
          sampling: 'lttb',
          lineStyle: { color: STRATEGY_LINE_COLOR, width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(88, 166, 255, 0.22)' },
              { offset: 1, color: 'rgba(88, 166, 255, 0.02)' },
            ]),
          },
        },
        ...(benchmarkReturns
          ? [
              {
                name: '基准累计收益',
                type: 'line',
                data: timestamps.map((ts, i) => [ts, benchmarkReturns![i]]),
                xAxisIndex: 0,
                yAxisIndex: 0,
                symbol: 'none',
                sampling: 'lttb',
                lineStyle: { color: AXIS_LABEL_COLOR, width: 1.5, type: 'dashed' as const },
              },
            ]
          : []),
        {
          name: '回撤',
          type: 'line',
          data: timestamps.map((ts, i) => [ts, drawdowns[i]]),
          xAxisIndex: 1,
          yAxisIndex: 1,
          symbol: 'none',
          sampling: 'lttb',
          lineStyle: { color: downColor, width: 1 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(0, 0, 0, 0)' },
              { offset: 1, color: `${downColor}26` },
            ]),
          },
        },
      ],
    };
  }, [series, upColor, downColor, benchmarkSymbol]);

  useEffect(() => {
    if (!chartRef.current) return;
    chartInstance.current = echarts.init(chartRef.current);
    const handleResize = () => chartInstance.current?.resize();
    const observer = new ResizeObserver(handleResize);
    observer.observe(chartRef.current);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', handleResize);
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chartInstance.current || !option) return;
    chartInstance.current.setOption(option, { notMerge: true });
  }, [option]);

  if (!series) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center rounded-lg border border-dashed border-crypto-border bg-crypto-bg/40 text-sm text-gray-500"
      >
        暂无权益曲线数据
      </div>
    );
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-gray-500">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-4 rounded-full" style={{ backgroundColor: STRATEGY_LINE_COLOR }} />
          策略累计收益
        </span>
        {series.benchmarkReturns && (
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-4 rounded-full bg-gray-400" style={{ backgroundImage: 'repeating-linear-gradient(90deg, #8b949e 0 4px, transparent 4px 7px)' }} />
            {benchmarkSymbol} 基准
          </span>
        )}
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-3 rounded-sm" style={{ backgroundColor: `${downColor}33` }} />
          回撤区间
        </span>
        <span>基准按日收盘对齐，可框选缩放查看区间</span>
      </div>
      <div ref={chartRef} style={{ width: '100%', height }} />
    </div>
  );
}
