import { useEffect, useMemo, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { getDailyChart, getIntradayChart } from '../api/client';
import type { DailyChartData, IntradayChartData } from '../types';
import { COLOR_SCHEMES, useSettingsStore } from '../stores/useSettingsStore';

type Props = {
  symbol: string;
  dailyDays?: number;
};

export function StockMiniCharts({ symbol, dailyDays = 30 }: Props) {
  const colorScheme = useSettingsStore((state) => state.colorScheme);
  const { upColor, downColor } = COLOR_SCHEMES[colorScheme];
  const [daily, setDaily] = useState<DailyChartData[]>([]);
  const [intraday, setIntraday] = useState<IntradayChartData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError('');
    Promise.all([
      getDailyChart(symbol).catch(() => [] as DailyChartData[]),
      getIntradayChart(symbol).catch(() => [] as IntradayChartData[]),
    ])
      .then(([dailyRows, intradayRows]) => {
        if (!live) return;
        setDaily(dailyRows.slice(-dailyDays));
        setIntraday(intradayRows);
        if (!dailyRows.length && !intradayRows.length) {
          setError('本地 K 线/分时缓存为空');
        }
      })
      .catch((reason: unknown) => {
        if (!live) return;
        setError(reason instanceof Error ? reason.message : '图表加载失败');
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [dailyDays, symbol]);

  const dailyOption = useMemo(() => {
    if (!daily.length) return null;
    const dates = daily.map((item) => item.date);
    const candles = daily.map((item) => [item.open, item.close, item.low, item.high]);
    return {
      animation: false,
      backgroundColor: 'transparent',
      grid: { left: 48, right: 12, top: 18, bottom: 24 },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: '#0f172a',
        borderColor: '#334155',
        textStyle: { color: '#e2e8f0', fontSize: 11 },
      },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: { color: '#64748b', fontSize: 10 },
        axisLine: { lineStyle: { color: '#334155' } },
      },
      yAxis: {
        scale: true,
        splitLine: { lineStyle: { color: '#1e293b' } },
        axisLabel: { color: '#64748b', fontSize: 10 },
      },
      series: [
        {
          type: 'candlestick',
          data: candles,
          itemStyle: {
            color: upColor,
            color0: downColor,
            borderColor: upColor,
            borderColor0: downColor,
          },
        },
      ],
    };
  }, [daily, downColor, upColor]);

  const intradayOption = useMemo(() => {
    if (!intraday.length) return null;
    const times = intraday.map((item) => {
      const text = String(item.time || '');
      const parts = text.split(' ');
      return parts.length > 1 ? parts[1].slice(0, 5) : text.slice(0, 5);
    });
    const prices = intraday.map((item) => item.price);
    const preClose = intraday[0]?.pre_close ?? prices[0];
    const last = prices[prices.length - 1] ?? preClose;
    const tone = Number(last) >= Number(preClose) ? upColor : downColor;
    return {
      animation: false,
      backgroundColor: 'transparent',
      grid: { left: 48, right: 12, top: 18, bottom: 24 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#0f172a',
        borderColor: '#334155',
        textStyle: { color: '#e2e8f0', fontSize: 11 },
      },
      xAxis: {
        type: 'category',
        data: times,
        boundaryGap: false,
        axisLabel: { color: '#64748b', fontSize: 10, interval: Math.max(1, Math.floor(times.length / 6)) },
        axisLine: { lineStyle: { color: '#334155' } },
      },
      yAxis: {
        scale: true,
        splitLine: { lineStyle: { color: '#1e293b' } },
        axisLabel: { color: '#64748b', fontSize: 10 },
      },
      series: [
        {
          type: 'line',
          data: prices,
          smooth: true,
          showSymbol: false,
          lineStyle: { color: tone, width: 1.5 },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: `${tone}55` },
                { offset: 1, color: `${tone}00` },
              ],
            },
          },
          markLine: preClose
            ? {
                silent: true,
                symbol: 'none',
                lineStyle: { color: '#64748b', type: 'dashed', width: 1 },
                data: [{ yAxis: preClose }],
                label: { formatter: '昨收', color: '#94a3b8', fontSize: 10 },
              }
            : undefined,
        },
      ],
    };
  }, [downColor, intraday, upColor]);

  if (loading) {
    return <div className="flex h-[220px] items-center justify-center text-sm text-gray-500">读取日 K / 分时缓存…</div>;
  }
  if (error && !dailyOption && !intradayOption) {
    return <div className="flex h-[220px] items-center justify-center px-4 text-center text-sm text-amber-300">{error}</div>;
  }

  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-2">
        <div className="mb-1 px-1 text-[11px] font-semibold text-gray-400">近 {dailyDays} 日 K</div>
        {dailyOption ? (
          <ReactECharts option={dailyOption} style={{ height: 200, width: '100%' }} opts={{ renderer: 'canvas' }} />
        ) : (
          <div className="flex h-[200px] items-center justify-center text-xs text-gray-500">无日 K 缓存</div>
        )}
      </div>
      <div className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-2">
        <div className="mb-1 px-1 text-[11px] font-semibold text-gray-400">当日分时</div>
        {intradayOption ? (
          <ReactECharts option={intradayOption} style={{ height: 200, width: '100%' }} opts={{ renderer: 'canvas' }} />
        ) : (
          <div className="flex h-[200px] items-center justify-center text-xs text-gray-500">无分时缓存</div>
        )}
      </div>
    </div>
  );
}

export default StockMiniCharts;
