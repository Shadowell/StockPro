import { useEffect, useMemo, useRef, type ReactNode } from 'react';
import * as echarts from 'echarts';
import type { Kline } from '../types';
import type { WatchTradeMarker } from '../api/client';
import { useSettingsStore } from '../stores/useSettingsStore';
import { KLINE_TRACKPAD_DATA_ZOOM } from '../utils/klineDataZoom';
import { bindKlineWheelNavigation } from '../utils/klineWheelNavigation';

const APP_DEFAULT_VISIBLE_CANDLES = 36;
const DESKTOP_DEFAULT_VISIBLE_CANDLES = 80;
const TRADE_MARKER_WIDTH = 12;
const TRADE_MARKER_SIZE: [number, number] = [TRADE_MARKER_WIDTH, 16];
const WATCH_LINE_LEGEND_ICON = 'path://M1,5 L18,5';
const BUY_MARKER_COLOR = '#ef4444';
const SELL_MARKER_COLOR = '#22c55e';
const TRADE_MARKER_ACTION_LABELS = new Set(['open_long', 'close_long', 'open_short', 'close_short']);
type TradeMarkerLayout = {
  marker: WatchTradeMarker;
  index: number;
  isBuy: boolean;
  markerPrice: number;
  labelPrice: number;
  actionText: string;
  markerCount: number;
};
const WATCH_EMA_COLORS = {
  EMA5: '#f59e0b',
  EMA10: '#ec4899',
  EMA20: '#22d3ee',
} as const;
const WATCH_DIF_COLOR = '#f59e0b';
const WATCH_DEA_COLOR = '#ec4899';

interface WatchKlineChartProps {
  data: Kline[];
  markers: WatchTradeMarker[];
  symbol: string;
  timeframe: string;
  livePrice?: number | null;
  height?: number;
  compact?: boolean;
  header?: ReactNode;
  showHeader?: boolean;
}

function fmtTime(ts: number): string {
  return new Date(ts).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function finite(value: unknown, fallback = 0): number {
  const next = Number(value);
  return Number.isFinite(next) ? next : fallback;
}

function ema(values: number[], period: number): Array<number | null> {
  const k = 2 / (period + 1);
  let prev: number | null = null;
  return values.map((value, index) => {
    if (!Number.isFinite(value)) return null;
    if (index < period - 1) return null;
    if (prev == null) {
      const seed = values.slice(index - period + 1, index + 1).reduce((sum, item) => sum + item, 0) / period;
      prev = seed;
      return seed;
    }
    prev = value * k + prev * (1 - k);
    return prev;
  });
}

function nearestIndex(timestamps: number[], target: number): number {
  if (!timestamps.length) return 0;
  let best = 0;
  let bestDiff = Math.abs(timestamps[0] - target);
  timestamps.forEach((ts, index) => {
    const diff = Math.abs(ts - target);
    if (diff < bestDiff) {
      best = index;
      bestDiff = diff;
    }
  });
  return best;
}

function formatPrice(value: number): string {
  const abs = Math.abs(value);
  const maximumFractionDigits = abs >= 1000 ? 1 : abs >= 1 ? 4 : 8;
  return value.toLocaleString(undefined, { maximumFractionDigits });
}

function formatEmaTooltipValue(value: unknown): string {
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) return '—';
  return numberValue.toLocaleString(undefined, {
    minimumFractionDigits: 5,
    maximumFractionDigits: 5,
  });
}

function formatTooltipNumber(value: unknown): string {
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) return '—';
  return numberValue.toLocaleString(undefined, { maximumFractionDigits: 5 });
}

function formatCandleTooltipValue(value: unknown): string {
  if (!Array.isArray(value)) return '—';
  const [open, close, low, high] = value.map((item) => Number(item));
  if (![open, close, low, high].every((item) => Number.isFinite(item))) return '—';
  return `开 ${formatPrice(open)} 高 ${formatPrice(high)} 低 ${formatPrice(low)} 收 ${formatPrice(close)}`;
}

function markerActionText(marker: WatchTradeMarker): string {
  const rawAction = String(marker.action || marker.side || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
  if (TRADE_MARKER_ACTION_LABELS.has(rawAction)) return rawAction;
  if (rawAction === 'long') return 'open_long';
  if (rawAction === 'short') return 'open_short';
  if (rawAction === 'buy' || rawAction === 'spot_buy') return 'open_long';
  if (rawAction === 'sell' || rawAction === 'spot_sell') return 'close_long';
  return '';
}

function markerLabelFormatter(params: any): string {
  const markerLabel = params?.data?.value === 'S' ? 'S' : 'B';
  return `{main|${markerLabel}}`;
}

function createEmaSeries(
  name: keyof typeof WATCH_EMA_COLORS,
  data: Array<number | null>,
) {
  const color = WATCH_EMA_COLORS[name];
  return {
    name,
    type: 'line' as const,
    data,
    smooth: true,
    showSymbol: false,
    lineStyle: { color, width: 1.4 },
    itemStyle: { color },
  };
}

function timeframeToMs(value: string): number {
  const normalized = value.toLowerCase();
  const amount = Number.parseInt(normalized, 10) || 1;
  if (normalized.endsWith('m')) return amount * 60_000;
  if (normalized.endsWith('h')) return amount * 60 * 60_000;
  if (normalized.endsWith('d')) return amount * 24 * 60 * 60_000;
  return 60_000;
}

function formatCountdown(ms: number): string {
  const totalSeconds = Math.max(0, Math.ceil(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function currentCandleCountdown(timeframe: string): string {
  const period = timeframeToMs(timeframe);
  const remaining = period - (Date.now() % period);
  return formatCountdown(remaining);
}

export default function WatchKlineChart({
  data,
  markers,
  symbol,
  timeframe,
  livePrice,
  height = 620,
  compact = false,
  header,
  showHeader = true,
}: WatchKlineChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);
  const { upColor, downColor } = useSettingsStore((s) => s.getColors());

  const option = useMemo(() => {
    const rows = data
      .filter((bar) => Number.isFinite(Number(bar.timestamp)))
      .sort((a, b) => Number(a.timestamp) - Number(b.timestamp));
    const timestamps = rows.map((bar) => Number(bar.timestamp));
    const categories = timestamps.map(fmtTime);
    const candleData = rows.map((bar) => [
      finite(bar.open),
      finite(bar.close),
      finite(bar.low),
      finite(bar.high),
    ]);
    const closes = rows.map((bar) => finite(bar.close));
    const volumes = rows.map((bar) => finite(bar.volume));
    const ema5 = ema(closes, 5);
    const ema10 = ema(closes, 10);
    const ema20 = ema(closes, 20);
    const ema12 = ema(closes, 12);
    const ema26 = ema(closes, 26);
    const dif = closes.map((_, i) => (ema12[i] != null && ema26[i] != null ? Number(ema12[i]) - Number(ema26[i]) : null));
    const dea = ema(dif.map((v) => finite(v)), 9);
    const macd = dif.map((v, i) => (v != null && dea[i] != null ? (v - Number(dea[i])) * 2 : null));
    const visibleCandles = compact ? APP_DEFAULT_VISIBLE_CANDLES : DESKTOP_DEFAULT_VISIBLE_CANDLES;
    const rawLivePrice = Number(livePrice);
    const currentPrice = Number.isFinite(rawLivePrice) ? rawLivePrice : (closes.length ? closes[closes.length - 1] : null);
    const basePriceValues = rows.flatMap((bar) => [finite(bar.low), finite(bar.high)]).filter(Number.isFinite);
    const minPrice = basePriceValues.length ? Math.min(...basePriceValues) : 0;
    const maxPrice = basePriceValues.length ? Math.max(...basePriceValues) : 1;
    const markerLineOffset = Math.max((maxPrice - minPrice) * 0.12, Math.abs(maxPrice || 1) * 0.0015);
    const candleIntervalMs = timeframeToMs(timeframe);
    const firstTimestamp = timestamps[0] ?? 0;
    const lastTimestamp = timestamps[timestamps.length - 1] ?? 0;
    const markerLayoutMap = new Map<string, TradeMarkerLayout>();
    markers
      .filter((marker) => Number.isFinite(Number(marker.timestamp)) && Number.isFinite(Number(marker.price)))
      .forEach((marker) => {
        const markerTimestamp = Number(marker.timestamp);
        if (firstTimestamp && lastTimestamp && (markerTimestamp < firstTimestamp || markerTimestamp >= lastTimestamp + candleIntervalMs)) {
          return;
        }
        const index = nearestIndex(timestamps, markerTimestamp);
        const isBuy = marker.label === 'B';
        const markerPrice = finite(marker.price);
        const bar = rows[index];
        const candleLow = finite(bar?.low, markerPrice);
        const candleHigh = finite(bar?.high, markerPrice);
        const labelPrice = isBuy
          ? Math.min(candleLow, markerPrice) - markerLineOffset
          : Math.max(candleHigh, markerPrice) + markerLineOffset;
        const actionText = markerActionText(marker);
        const key = `${index}:${marker.label}:${actionText || marker.action || marker.side || ''}`;
        const existing = markerLayoutMap.get(key);
        if (existing) {
          existing.marker = marker;
          existing.markerPrice = markerPrice;
          existing.labelPrice = labelPrice;
          existing.markerCount += 1;
          return;
        }
        markerLayoutMap.set(key, {
          marker,
          index,
          isBuy,
          markerPrice,
          labelPrice,
          actionText,
          markerCount: 1,
        });
      });
    const markerLayouts = Array.from(markerLayoutMap.values());
    const markerAxisPrices = markerLayouts.flatMap((layout) => [layout.markerPrice, layout.labelPrice]);
    const priceValues = [
      ...basePriceValues,
      ...markerAxisPrices,
      ...(currentPrice != null ? [currentPrice] : []),
    ].filter(Number.isFinite);
    const chartMinPrice = priceValues.length ? Math.min(...priceValues) : minPrice;
    const chartMaxPrice = priceValues.length ? Math.max(...priceValues) : maxPrice;
    const pricePaddingRatio = compact ? 0.04 : 0.025;
    const pricePadding = Math.max((chartMaxPrice - chartMinPrice) * pricePaddingRatio, Math.abs(chartMaxPrice || 1) * 0.0005);
    const gridLeft = compact ? 40 : 56;
    const gridRight = compact ? 76 : 68;

    const markPointData = markerLayouts
      .map(({ marker, index, isBuy, labelPrice, markerCount }) => {
        return {
          name: marker.label,
          value: marker.label,
          markerCount,
          coord: [index, labelPrice],
          symbol: 'rect',
          symbolSize: TRADE_MARKER_SIZE,
          itemStyle: {
            color: isBuy ? BUY_MARKER_COLOR : SELL_MARKER_COLOR,
            borderColor: 'rgba(248, 250, 252, 0.72)',
            borderWidth: 1,
            shadowBlur: 6,
            shadowColor: 'rgba(0,0,0,0.35)',
          },
          label: {
            color: '#fff',
            formatter: markerLabelFormatter,
            rich: {
              main: {
                align: 'center',
                fontSize: 10,
                lineHeight: 12,
                fontWeight: 900,
              },
            },
          },
          marker,
        };
      });
    const markerGuideLines = markerLayouts
      .map(({ index, isBuy, markerPrice, labelPrice }) => {
        const color = isBuy ? BUY_MARKER_COLOR : SELL_MARKER_COLOR;
        return [
          {
            coord: [index, labelPrice],
            lineStyle: { color },
          },
          {
            coord: [index, markerPrice],
            lineStyle: { color },
          },
        ];
      });
    const currentPriceLine = currentPrice != null ? {
      symbol: ['none', 'none'],
      silent: true,
      animation: false,
      label: {
        show: true,
        position: 'end',
        formatter: () => `${formatPrice(currentPrice)}\n${currentCandleCountdown(timeframe)}`,
        color: '#f8fafc',
        fontSize: compact ? 10 : 11,
        lineHeight: compact ? 14 : 16,
        backgroundColor: 'rgba(3, 7, 18, 0.9)',
        borderColor: '#64748b',
        borderWidth: 1,
        borderRadius: 4,
        padding: compact ? [2, 4] : [3, 5],
        distance: 4,
      },
      lineStyle: {
        color: '#d1d5db',
        type: 'dashed',
        width: 1,
        opacity: 0.85,
      },
      data: [{ yAxis: currentPrice }],
    } : undefined;

    return {
      backgroundColor: 'transparent',
      animation: false,
      legend: {
        top: 0,
        left: 0,
        itemWidth: compact ? 10 : 14,
        itemHeight: compact ? 6 : 8,
        textStyle: { color: '#9ca3af', fontSize: compact ? 10 : 12 },
        data: [
          'K线',
          { name: 'EMA5', icon: WATCH_LINE_LEGEND_ICON },
          { name: 'EMA10', icon: WATCH_LINE_LEGEND_ICON },
          { name: 'EMA20', icon: WATCH_LINE_LEGEND_ICON },
          'VOL',
          { name: 'DIF', icon: WATCH_LINE_LEGEND_ICON },
          { name: 'DEA', icon: WATCH_LINE_LEGEND_ICON },
          'MACD',
        ],
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(15, 23, 42, 0.94)',
        borderColor: '#334155',
        textStyle: { color: '#e5e7eb' },
        formatter: (params: any) => {
          const items = Array.isArray(params) ? params : [params];
          if (items.length === 0) return '';
          const axisLabel = items[0]?.axisValueLabel || items[0]?.axisValue || '';
          const rowsHtml = items
            .map((param: any) => {
              const seriesName = String(param?.seriesName ?? '');
              let value = '—';
              if (seriesName === 'K线') {
                value = formatCandleTooltipValue(param.data ?? param.value);
              } else if (/^EMA\d+$/.test(seriesName)) {
                value = formatEmaTooltipValue(param.value);
              } else {
                value = formatTooltipNumber(param.value);
              }
              if (value === '—') return '';
              return `<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;line-height:1.45;">` +
                `<span>${param.marker ?? ''}<span style="color:#cbd5e1;">${seriesName}</span></span>` +
                `<span style="font-variant-numeric:tabular-nums;color:#f8fafc;">${value}</span>` +
                `</div>`;
            })
            .filter(Boolean)
            .join('');
          return `<div style="min-width:180px;font-size:11px;">` +
            `<div style="margin-bottom:6px;color:#94a3b8;font-weight:600;">${axisLabel}</div>` +
            rowsHtml +
            `</div>`;
        },
      },
      axisPointer: {
        link: [{ xAxisIndex: [0, 1, 2] }],
      },
      grid: compact
        ? [
            { left: gridLeft, right: gridRight, top: 28, height: '60%' },
            { left: gridLeft, right: gridRight, top: '70%', height: '10%' },
            { left: gridLeft, right: gridRight, top: '84%', height: '9%' },
          ]
        : [
            { left: gridLeft, right: gridRight, top: 42, height: '52%' },
            { left: gridLeft, right: gridRight, top: '62%', height: '14%' },
            { left: gridLeft, right: gridRight, top: '80%', height: '14%' },
          ],
      xAxis: [0, 1, 2].map((gridIndex) => ({
        type: 'category',
        gridIndex,
        data: categories,
        boundaryGap: true,
        axisLine: { lineStyle: { color: '#1f2937' } },
        axisLabel: { color: gridIndex === 2 ? '#8b949e' : 'transparent', fontSize: compact ? 10 : 12 },
        splitLine: { show: true, lineStyle: { color: '#111827' } },
      })),
      yAxis: [
        {
          scale: true,
          position: 'right',
          gridIndex: 0,
          min: chartMinPrice - pricePadding,
          max: chartMaxPrice + pricePadding,
          axisLabel: { color: '#9ca3af', fontSize: compact ? 10 : 12 },
          splitLine: { lineStyle: { color: '#18212f' } },
        },
        {
          scale: true,
          position: 'right',
          gridIndex: 1,
          axisLabel: { color: '#9ca3af', fontSize: compact ? 10 : 12 },
          splitLine: { show: false },
        },
        {
          scale: true,
          position: 'right',
          gridIndex: 2,
          axisLabel: { color: '#9ca3af', fontSize: compact ? 10 : 12 },
          splitLine: { lineStyle: { color: '#18212f' } },
        },
      ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 1, 2],
          ...KLINE_TRACKPAD_DATA_ZOOM,
          start: Math.max(0, 100 - (visibleCandles / Math.max(1, rows.length)) * 100),
          end: 100,
        },
        { type: 'slider', xAxisIndex: [0, 1, 2], bottom: 0, height: compact ? 14 : 18, borderColor: '#1f2937', textStyle: { color: '#6b7280', fontSize: compact ? 9 : 11 } },
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: candleData,
          itemStyle: {
            color: upColor,
            color0: downColor,
            borderColor: upColor,
            borderColor0: downColor,
          },
          barWidth: TRADE_MARKER_WIDTH,
          markPoint: {
            symbolKeepAspect: false,
            data: markPointData,
            tooltip: {
              formatter: (params: any) => {
                const marker = params?.data?.marker as WatchTradeMarker | undefined;
                if (!marker) return '';
                const actionText = markerActionText(marker);
                const markerCount = Number(params?.data?.markerCount || 1);
                const countText = markerCount > 1 ? `<br/>同K线合并: ${markerCount} 笔` : '';
                return `${marker.label}${actionText ? ` · ${actionText}` : ''} ${marker.sourceStrategyName}<br/>价格: ${marker.price ?? '--'}<br/>数量: ${marker.quantity ?? '--'}<br/>时间: ${marker.datetime ?? '--'}${countText}`;
              },
            },
          },
          markLine: {
            symbol: ['none', 'circle'],
            symbolSize: [0, 4],
            silent: true,
            animation: false,
            label: { show: false },
            lineStyle: {
              width: 1,
              opacity: 0.9,
            },
            emphasis: { disabled: true },
            data: markerGuideLines,
          },
        },
        ...(currentPriceLine ? [{
          name: '当前价',
          type: 'line',
          data: [],
          showSymbol: false,
          lineStyle: { opacity: 0 },
          tooltip: { show: false },
          markLine: currentPriceLine,
        }] : []),
        createEmaSeries('EMA5', ema5),
        createEmaSeries('EMA10', ema10),
        createEmaSeries('EMA20', ema20),
        {
          name: 'VOL',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes,
          itemStyle: {
            color: (params: any) => {
              const bar = rows[params.dataIndex];
              return finite(bar?.close) >= finite(bar?.open) ? 'rgba(34,197,94,0.48)' : 'rgba(239,68,68,0.48)';
            },
          },
        },
        { name: 'DIF', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: dif, showSymbol: false, lineStyle: { color: WATCH_DIF_COLOR, width: 1.2 }, itemStyle: { color: WATCH_DIF_COLOR } },
        { name: 'DEA', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: dea, showSymbol: false, lineStyle: { color: WATCH_DEA_COLOR, width: 1.2 }, itemStyle: { color: WATCH_DEA_COLOR } },
        {
          name: 'MACD',
          type: 'bar',
          xAxisIndex: 2,
          yAxisIndex: 2,
          data: macd,
          itemStyle: { color: (params: any) => (finite(params.value) >= 0 ? 'rgba(34,197,94,0.55)' : 'rgba(239,68,68,0.55)') },
        },
      ],
    };
  }, [compact, data, markers, timeframe, livePrice, upColor, downColor]);

  useEffect(() => {
    if (!chartRef.current) return undefined;
    const inst = echarts.init(chartRef.current, 'dark');
    chartInstance.current = inst;
    const disposeWheelNavigation = bindKlineWheelNavigation(inst);
    const resize = () => inst.resize();
    window.addEventListener('resize', resize);
    return () => {
      window.removeEventListener('resize', resize);
      disposeWheelNavigation();
      inst.dispose();
      chartInstance.current = null;
    };
  }, []);

  useEffect(() => {
    chartInstance.current?.setOption(option, true);
  }, [option]);

  return (
    <section className={`${compact ? 'rounded-lg p-2' : 'rounded-xl p-4'} border border-crypto-border bg-crypto-card/80`}>
      {header ?? (showHeader ? (
        <div className={`${compact ? 'mb-1.5 gap-2' : 'mb-3'} flex items-center justify-between`}>
          <div>
            <div className={`${compact ? 'text-[11px]' : 'text-sm'} font-semibold leading-4 text-gray-100`}>{symbol}</div>
            <div className={`${compact ? 'text-[11px]' : 'text-xs'} leading-4 text-gray-500`}>EMA5 / EMA10 / EMA20 · VOL · MACD · {timeframe}</div>
          </div>
          <div className={`flex items-center gap-2 text-[10px] text-gray-400 ${compact ? 'flex-col items-end gap-1' : ''}`}>
            <span className="inline-flex items-center gap-1">
              <span className={compact ? 'h-2 w-2 rounded-sm bg-red-500' : 'h-2.5 w-2.5 rounded-sm bg-red-500'} />
              买入
            </span>
            <span className="inline-flex items-center gap-1">
              <span className={compact ? 'h-2 w-2 rounded-sm bg-green-500' : 'h-2.5 w-2.5 rounded-sm bg-green-500'} />
              卖出
            </span>
          </div>
        </div>
      ) : null)}
      <div ref={chartRef} style={{ height }} />
    </section>
  );
}
