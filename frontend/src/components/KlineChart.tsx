import { useEffect, useRef, useMemo } from 'react';
import * as echarts from 'echarts';
import type { CSSProperties } from 'react';
import type { Kline } from '../types';
import { useSettingsStore } from '../stores/useSettingsStore';
import { KLINE_TRACKPAD_DATA_ZOOM } from '../utils/klineDataZoom';
import { bindKlineWheelNavigation } from '../utils/klineWheelNavigation';

const EMA_COLORS = ['#FFD700', '#00BFFF', '#FF69B4', '#00E676'];

function emaSeriesColor(index: number): string {
  return EMA_COLORS[index % EMA_COLORS.length];
}

export interface KlineChartProps {
  data: Kline[];
  predictedData?: Kline[];
  symbol: string;
  /** 支持像素或百分比，便于双图布局 */
  height?: number | string;
  theme?: 'dark' | 'light';
  showVolume?: boolean;
  showEMA?: boolean;
  /** 是否绘制 RSI(14) 副图；序列来自后端 indicatorSeries.RSI14。 */
  showRSI?: boolean;
  /** 是否绘制 MACD 副图；序列来自后端 MACD / MACD_signal / MACD_hist。 */
  showMACD?: boolean;
  emaPeriods?: number[];
  /** 后端行情指标接口返回的指标序列，key 例如 EMA5 / EMA10 / RSI14 / MACD。 */
  indicatorSeries?: Record<string, Array<number | null>>;
  /** 指标序列对应的 K 线时间戳，用于避免独立接口刷新时与图表 K 线错位。 */
  indicatorTimestamps?: number[];
  /**
   * 多图联动：传入同一时间轴（毫秒），保证上下图 category 索引一一对应，
   * 配合 ECharts group + connect 实现 dataZoom 同步。
   */
  sharedTimestamps?: number[];
  /** echarts.connect 分组名 */
  connectGroupId?: string;
  /** 是否绘制真实 K 线（下图可仅画预测） */
  showRealCandles?: boolean;
  /** 是否绘制预测 K 线（上图可仅画真实） */
  showPredCandles?: boolean;
  /**
   * 上图专用：在仅有真实 K 线系列时，Tooltip 仍展示「当时预测的收盘价」及偏差。
   * key = K 线毫秒时间戳。
   */
  historicalPredCloseByTs?: Record<number, number>;
  /**
   * 初始 X 轴视口：只展示最后 N 根类目（配置变化会重置视口；用户手动缩放后保留）。
   * 未设置时默认展示后半轴（start=50, end=100）。
   */
  defaultShowLastBars?: number;
  /**
   * 与 {@link defaultShowLastBars} 二选一优先：按「实盘类目」计数，视口从倒数第 N 根实盘
   * 画到轴末端（含右侧仅预测类目），便于 1m + 未来预测合并轴时仍能铺满约 N 根分钟 K。
   */
  defaultShowLastRealBars?: number;
}

function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function formatTooltipVolume(v: number): string {
  if (!Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e8) return `${(v / 1e8).toFixed(3)} 亿`;
  if (a >= 1e4) return `${(v / 1e4).toFixed(2)} 万`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function formatTooltipQuoteVol(v: number): string {
  if (!Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e8) return `${(v / 1e8).toFixed(2)} 亿`;
  if (a >= 1e4) return `${(v / 1e4).toFixed(2)} 万`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function quoteVolFromBar(bar: Kline | undefined): number | null {
  if (!bar) return null;
  const q = bar.quoteVolume ?? bar.quote_volume;
  if (q != null && Number.isFinite(Number(q))) return Number(q);
  if (Number.isFinite(bar.close) && Number.isFinite(bar.volume)) return bar.close * bar.volume;
  return null;
}

function latestFiniteLineValue(values: Array<number | '-' | null | undefined>): number | null {
  for (let i = values.length - 1; i >= 0; i--) {
    const value = values[i];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

function formatEmaTooltipValue(value: unknown): string {
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) return '—';
  return numberValue.toLocaleString(undefined, {
    minimumFractionDigits: 5,
    maximumFractionDigits: 5,
  });
}

function formatEmaValue(value: number): string {
  return formatEmaTooltipValue(value);
}

function calculateFallbackEma(values: number[], period: number): Array<number | null> {
  const result: Array<number | null> = Array(values.length).fill(null);
  if (period <= 0 || values.length < period) return result;
  const initial = values.slice(0, period);
  if (!initial.every((value) => Number.isFinite(value))) return result;
  const alpha = 2 / (period + 1);
  let previous = initial.reduce((sum, value) => sum + value, 0) / period;
  result[period - 1] = previous;
  for (let i = period; i < values.length; i += 1) {
    const close = values[i];
    if (!Number.isFinite(close)) {
      result[i] = null;
      continue;
    }
    previous = alpha * close + (1 - alpha) * previous;
    result[i] = previous;
  }
  return result;
}

function padBackendIndicatorSeries(
  seriesValues: Array<number | null> | undefined,
  indicatorTimestamps: number[] | undefined,
  allTimestamps: number[],
  realMap: Map<number, Kline>,
): (number | '-')[] {
  const values = seriesValues || [];
  const valueByTs = new Map<number, number | null>();
  if (indicatorTimestamps && indicatorTimestamps.length === values.length) {
    indicatorTimestamps.forEach((ts, idx) => valueByTs.set(Number(ts), values[idx]));
  }
  const padded: (number | '-')[] = [];
  let realIdx = 0;
  for (const ts of allTimestamps) {
    if (!realMap.has(ts)) {
      padded.push('-');
      continue;
    }
    const backendValue = valueByTs.size
      ? valueByTs.get(Number(ts))
      : realIdx < values.length
        ? values[realIdx]
        : null;
    realIdx += 1;
    if (typeof backendValue === 'number' && Number.isFinite(backendValue)) {
      padded.push(backendValue);
    } else {
      padded.push('-');
    }
  }
  return padded;
}

/** ECharts 蜡烛图为 [open, close, low, high]；修正颠倒的 low/high 与非有限数，避免整屏色块。 */
function toCandleTuple(bar: Kline): [number, number, number, number] | null {
  const o = Number(bar.open);
  const c = Number(bar.close);
  const l = Number(bar.low);
  const h = Number(bar.high);
  if (![o, c, l, h].every((n) => Number.isFinite(n))) return null;
  const lo = Math.min(o, c, l, h);
  const hi = Math.max(o, c, l, h);
  return [o, c, lo, hi];
}

/** 从 BTC/USDT 或 BTC/USDT:USDT 解析基础币 / 计价货币 */
function symbolUnits(sym: string): { base: string; quote: string } {
  const i = sym.indexOf('/');
  if (i < 0) return { base: sym.trim() || '—', quote: 'USDT' };
  const base = sym.slice(0, i).trim();
  const tail = sym.slice(i + 1).split(':')[0].trim();
  return { base: base || '—', quote: tail || 'USDT' };
}

export default function KlineChart({
  data,
  predictedData,
  symbol,
  height = 500,
  theme = 'dark',
  showVolume = true,
  showEMA = true,
  showRSI = false,
  showMACD = false,
  emaPeriods = [5, 10, 20, 30],
  indicatorSeries,
  indicatorTimestamps,
  sharedTimestamps: sharedTimestampsProp,
  connectGroupId,
  showRealCandles = true,
  showPredCandles = true,
  historicalPredCloseByTs,
  defaultShowLastBars,
  defaultShowLastRealBars,
}: KlineChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);
  /** 用户拖过缩放/滑块后，更新数据时不再写入 dataZoom.start/end，否则会回到默认视窗 */
  const userAdjustedZoomRef = useRef(false);
  const prevSymbolRef = useRef(symbol);
  const { upColor, downColor } = useSettingsStore((s) => s.getColors());

  const extractOhlc = (source: unknown): [number, number, number, number] | null => {
    if (!Array.isArray(source)) return null;
    const numeric = source.filter((item): item is number => typeof item === 'number' && Number.isFinite(item));
    if (numeric.length < 4) return null;
    const [open, close, low, high] = numeric.slice(-4);
    return [open, close, low, high];
  };

  /**
   * 构建统一时间轴：
   * - 默认合并 data + predictedData；
   * - 若传入 sharedTimestamps，则强制按该轴对齐（双图联动关键）。
   */
  const chartData = useMemo(() => {
    const empty = {
      dates: [] as string[],
      timestamps: [] as number[],
      realValues: [] as any[],
      predValues: [] as any[],
      predCloseLine: [] as (number | null)[],
      volumes: [] as any[],
      realVolumes: [] as (number | null)[],
      predVolumes: [] as (number | null)[],
      realQuoteVols: [] as (number | null)[],
      predQuoteVols: [] as (number | null)[],
      ema: {} as Record<string, (number | '-')[]>,
      rsi: [] as (number | '-')[],
      macd: [] as (number | '-')[],
      macdSignal: [] as (number | '-')[],
      macdHist: [] as (number | '-')[],
      splitIndex: -1,
      hasOverlap: false,
      /** 仅未来段、按时间排序后的第 30 根预测 K 线收盘（API 通常返回 30 根未来柱） */
      thirtiethFuturePredClose: null as number | null,
      /** 上者在合并时间轴上的类目下标，用于 markPoint */
      thirtiethFuturePredDataIndex: null as number | null,
    };

    const formatDate = (ts: number) =>
      new Date(ts).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });

    const realMap = new Map<number, Kline>();
    for (const bar of data) realMap.set(bar.timestamp, bar);

    const hasPredInput = !!(predictedData && predictedData.length > 0);
    const predMap = new Map<number, Kline>();
    if (hasPredInput) {
      for (const bar of predictedData!) predMap.set(bar.timestamp, bar);
    }

    const allTimestamps =
      sharedTimestampsProp && sharedTimestampsProp.length > 0
        ? [...sharedTimestampsProp].sort((a, b) => a - b)
        : Array.from(
            new Set([
              ...data.map((b) => b.timestamp),
              ...(hasPredInput ? predictedData!.map((b) => b.timestamp) : []),
            ])
          ).sort((a, b) => a - b);

    if (allTimestamps.length === 0) {
      return empty;
    }

    const dates: string[] = [];
    const timestamps: number[] = [];
    const realValues: any[] = [];
    const predValues: any[] = [];
    const volumes: any[] = [];
    const realVolumes: (number | null)[] = [];
    const predVolumes: (number | null)[] = [];
    const realQuoteVols: (number | null)[] = [];
    const predQuoteVols: (number | null)[] = [];

    let lastRealIndex = -1;
    let hasOverlap = false;

    for (let i = 0; i < allTimestamps.length; i++) {
      const ts = allTimestamps[i];
      const realBar = realMap.get(ts);
      const predBar = predMap.get(ts);

      timestamps.push(ts);
      dates.push(formatDate(ts));

      if (showRealCandles && realBar) {
        const tup = toCandleTuple(realBar);
        if (tup) {
          realValues.push(tup);
          lastRealIndex = i;
        } else {
          realValues.push('-');
        }
      } else {
        realValues.push('-');
      }

      if (showPredCandles && predBar) {
        const pt = toCandleTuple(predBar);
        if (pt) {
          predValues.push(pt);
          if (realBar) hasOverlap = true;
        } else {
          predValues.push('-');
        }
      } else {
        predValues.push('-');
      }

      const bar = realBar || predBar;
      const isPredOnly = !realBar && !!predBar;
      const isPredVolumeBar = !!predBar && showPredCandles;
      const volUp = bar ? bar.close >= bar.open : true;
      const volColor = volUp ? upColor : downColor;

      volumes.push({
        value: bar ? bar.volume : 0,
        itemStyle: isPredVolumeBar
          ? {
              ...(isPredOnly ? { color: 'transparent' } : { color: volColor }),
              borderColor: volColor,
              borderWidth: 1,
              borderType: [2, 2] as any,
              opacity: 1,
            }
          : {
              color: volColor,
              opacity: 1,
            },
      });
      realVolumes.push(realBar != null ? Number(realBar.volume) : null);
      predVolumes.push(
        predBar != null && predBar.volume != null && Number.isFinite(Number(predBar.volume))
          ? Number(predBar.volume)
          : null
      );
      realQuoteVols.push(quoteVolFromBar(realBar ?? undefined));
      predQuoteVols.push(quoteVolFromBar(predBar ?? undefined));
    }

    const splitIndex = lastRealIndex + 1;

    const ema: Record<string, (number | '-')[]> = {};
    if (showEMA && showRealCandles && data.length > 0) {
      const realCloseValues = allTimestamps
        .filter((ts) => realMap.has(ts))
        .map((ts) => Number(realMap.get(ts)?.close));
      emaPeriods.forEach((period) => {
        const emaValues = indicatorSeries?.[`EMA${period}`] || [];
        const fallbackEmaValues = calculateFallbackEma(realCloseValues, period);
        const valueByTs = new Map<number, number | null>();
        if (indicatorTimestamps && indicatorTimestamps.length === emaValues.length) {
          indicatorTimestamps.forEach((ts, idx) => valueByTs.set(Number(ts), emaValues[idx]));
        }
        const padded: (number | '-')[] = [];
        let realIdx = 0;
        for (let i = 0; i < allTimestamps.length; i++) {
          const ts = allTimestamps[i];
          if (realMap.has(ts)) {
            const backendValue = valueByTs.size
              ? valueByTs.get(Number(ts))
              : realIdx < emaValues.length
                ? emaValues[realIdx]
                : null;
            const value =
              typeof backendValue === 'number' && Number.isFinite(backendValue)
                ? backendValue
                : fallbackEmaValues[realIdx];
            if (typeof value === 'number' && Number.isFinite(value)) {
              padded.push(value);
            } else {
              padded.push('-');
            }
            realIdx++;
          } else {
            padded.push('-');
          }
        }
        ema[`EMA${period}`] = padded;
      });
    }

    const emptyPad = (): (number | '-')[] => allTimestamps.map(() => '-');
    const rsi =
      showRSI && showRealCandles && data.length > 0
        ? padBackendIndicatorSeries(
            indicatorSeries?.RSI14,
            indicatorTimestamps,
            allTimestamps,
            realMap,
          )
        : emptyPad();
    const macd =
      showMACD && showRealCandles && data.length > 0
        ? padBackendIndicatorSeries(
            indicatorSeries?.MACD,
            indicatorTimestamps,
            allTimestamps,
            realMap,
          )
        : emptyPad();
    const macdSignal =
      showMACD && showRealCandles && data.length > 0
        ? padBackendIndicatorSeries(
            indicatorSeries?.MACD_signal,
            indicatorTimestamps,
            allTimestamps,
            realMap,
          )
        : emptyPad();
    const macdHist =
      showMACD && showRealCandles && data.length > 0
        ? padBackendIndicatorSeries(
            indicatorSeries?.MACD_hist,
            indicatorTimestamps,
            allTimestamps,
            realMap,
          )
        : emptyPad();

    /** 仅 Now 之后的未来预测收盘连线；与实盘时间重合的历史预测柱不连线 */
    const predCloseLine: (number | null)[] = predValues.map((v, i) => {
      if (i < splitIndex) return null;
      if (v === '-' || !Array.isArray(v) || v.length < 2) return null;
      const c = v[1];
      return typeof c === 'number' && Number.isFinite(c) ? c : null;
    });

    const realTsOnly = new Set(data.map((b) => b.timestamp));
    const futurePredBars = hasPredInput
      ? predictedData!
          .filter((b) => !realTsOnly.has(b.timestamp))
          .sort((a, b) => a.timestamp - b.timestamp)
      : [];
    const thirtiethFuturePredClose =
      futurePredBars.length >= 30 && Number.isFinite(futurePredBars[29].close)
        ? Number(futurePredBars[29].close)
        : null;
    const thirtiethTs =
      futurePredBars.length >= 30 ? Number(futurePredBars[29].timestamp) : null;
    const thirtiethFuturePredDataIndex =
      thirtiethTs != null
        ? (() => {
            const ii = timestamps.findIndex((t) => Number(t) === thirtiethTs);
            return ii >= 0 ? ii : null;
          })()
        : null;

    return {
      dates,
      timestamps,
      realValues,
      predValues,
      predCloseLine,
      volumes,
      realVolumes,
      predVolumes,
      realQuoteVols,
      predQuoteVols,
      ema,
      rsi,
      macd,
      macdSignal,
      macdHist,
      splitIndex,
      hasOverlap,
      thirtiethFuturePredClose,
      thirtiethFuturePredDataIndex,
    };
  }, [
    data,
    predictedData,
    showEMA,
    showRSI,
    showMACD,
    emaPeriods,
    indicatorSeries,
    indicatorTimestamps,
    upColor,
    downColor,
    sharedTimestampsProp,
    showRealCandles,
    showPredCandles,
  ]);
  const emaValueLabels = useMemo(
    () => (
      showEMA && showRealCandles
        ? emaPeriods
            .map((period, index) => {
              const value = latestFiniteLineValue(chartData.ema[`EMA${period}`] || []);
              if (value == null) return null;
              return {
                period,
                value,
                color: emaSeriesColor(index),
              };
            })
            .filter((item): item is { period: number; value: number; color: string } => item != null)
        : []
    ),
    [chartData.ema, emaPeriods, showEMA, showRealCandles],
  );

  const option = useMemo(() => {
    const hasPrediction = showPredCandles && chartData.predValues.some((v) => v !== '-');
    const hasReal = showRealCandles && chartData.realValues.some((v) => v !== '-');

    /** 主图纵轴：按实盘 OHLC 定标，并纳入预测收盘价（虚线连线），避免未来 30 根预测被裁出视野。 */
    const priceAxisBounds =
      hasReal && hasPrediction
        ? (() => {
            let lo = Infinity;
            let hi = -Infinity;
            for (const v of chartData.realValues) {
              if (v === '-') continue;
              if (!Array.isArray(v) || v.length < 4) continue;
              for (const n of v) {
                if (typeof n === 'number' && Number.isFinite(n)) {
                  lo = Math.min(lo, n);
                  hi = Math.max(hi, n);
                }
              }
            }
            if (hasPrediction) {
              for (const v of chartData.predValues) {
                if (v === '-' || !Array.isArray(v) || v.length < 2) continue;
                const c = v[1];
                if (typeof c === 'number' && Number.isFinite(c)) {
                  lo = Math.min(lo, c);
                  hi = Math.max(hi, c);
                }
              }
            }
            if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;
            const span = hi - lo;
            const pad = span > 0 ? span * 0.02 : (Math.abs(hi) || 1) * 0.001;
            return { min: lo - pad, max: hi + pad };
          })()
        : null;

    const priceAxisLabel = {
      color: '#8b949e',
      formatter: (val: string | number) => {
        const n = typeof val === 'number' ? val : Number(val);
        if (!Number.isFinite(n)) return '';
        return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
      },
    };
    const nCat = chartData.dates.length;
    let dzStart = 50;
    let dzEnd = 100;
    if (defaultShowLastRealBars != null && defaultShowLastRealBars > 0 && nCat > 0) {
      const si = chartData.splitIndex;
      const startIdx = Math.max(0, si - defaultShowLastRealBars);
      dzStart = (startIdx / nCat) * 100;
      dzEnd = 100;
    } else if (defaultShowLastBars != null && defaultShowLastBars > 0 && nCat > 0) {
      const k = Math.min(defaultShowLastBars, nCat);
      dzStart = nCat <= k ? 0 : ((nCat - k) / nCat) * 100;
      dzEnd = 100;
    }
    const categoryAxisLabel = {
      color: '#8b949e',
      fontSize: 10,
      hideOverlap: true,
    };

    const emaSeries = showEMA && showRealCandles
      ? emaPeriods.map((period, index) => {
          const color = emaSeriesColor(index);
          return {
            name: `EMA${period}`,
            type: 'line' as const,
            data: chartData.ema[`EMA${period}`] || [],
            smooth: true,
            lineStyle: { width: 1, color },
            itemStyle: { color },
            symbol: 'none',
            showSymbol: false,
          };
        })
      : [];

    const markLineData =
      hasPrediction && chartData.splitIndex > 0 && chartData.splitIndex < chartData.dates.length
        ? [
            {
              name: 'Now',
              xAxis: chartData.splitIndex - 1,
              lineStyle: { color: '#adb5bd', width: 1.5, type: 'dashed' as const },
              label: {
                show: true,
                formatter: 'Now / AI Prediction →',
                /** 竖线：end 为价格轴上端；横排文字贴在虚线顶端 */
                position: 'end' as const,
                rotate: 0,
                align: 'center',
                distance: 8,
                color: '#adb5bd',
                fontSize: 10,
                fontWeight: 'bold' as const,
                backgroundColor: 'rgba(173, 181, 189, 0.1)',
                padding: [3, 6],
                borderRadius: 3,
              },
            },
          ]
        : [];

    const lastRealClose =
      showRealCandles &&
      data.length > 0 &&
      data[data.length - 1] != null &&
      Number.isFinite(Number(data[data.length - 1].close))
        ? Number(data[data.length - 1].close)
        : null;

    const tMarkIdx = chartData.thirtiethFuturePredDataIndex;
    const tMarkClose = chartData.thirtiethFuturePredClose;
    /** 右侧预留像素：让「第30根预测」说明框显示在最后一根预测 K 线右边 */
    const gridRightPx =
      hasPrediction && tMarkIdx != null && tMarkClose != null ? 190 : 20;
    const thirtiethPredMarkPoint =
      showPredCandles &&
      tMarkIdx != null &&
      tMarkClose != null &&
      tMarkIdx >= 0 &&
      tMarkIdx < chartData.dates.length
        ? (() => {
            const pct =
              lastRealClose != null && lastRealClose !== 0
                ? ((tMarkClose - lastRealClose) / lastRealClose) * 100
                : null;
            const pctColor =
              pct == null ? '#8b949e' : pct >= 0 ? upColor : downColor;
            const pctStr =
              pct != null ? `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%` : '—';
            const priceStr = tMarkClose.toLocaleString(undefined, {
              maximumFractionDigits: 2,
            });
            return {
              z: 50,
              symbol: 'circle',
              symbolSize: 7,
              itemStyle: {
                color: '#facc15',
                borderColor: 'rgba(255,255,255,0.85)',
                borderWidth: 1,
              },
              label: {
                show: true,
                position: 'right',
                distance: 12,
                align: 'left',
                verticalAlign: 'middle',
                /** 全不透明 + 阴影，避免底层虚线叠在文字上（原 z:6 的连线曾盖住标签） */
                backgroundColor: theme === 'dark' ? '#161B22' : '#ffffff',
                borderColor: theme === 'dark' ? '#484f58' : '#d0d7de',
                borderWidth: 1,
                borderRadius: 6,
                padding: [8, 10],
                shadowBlur: 14,
                shadowColor: 'rgba(0,0,0,0.55)',
                shadowOffsetY: 2,
                formatter: `{t|第30根预测收盘}\n{p|${priceStr}}\n{c|较当前收盘 ${pctStr}}`,
                rich: {
                  t: {
                    fontSize: 10,
                    color: '#8b949e',
                    fontWeight: 600,
                    lineHeight: 16,
                  },
                  p: {
                    fontSize: 12,
                    color: '#e6edf3',
                    fontWeight: 600,
                    lineHeight: 18,
                  },
                  c: { fontSize: 10, color: pctColor, lineHeight: 16 },
                },
              },
              data: [
                {
                  name: '第30根预测收盘',
                  coord: [tMarkIdx, tMarkClose] as [number, number],
                  value: tMarkClose,
                },
              ],
            };
          })()
        : undefined;

    const series: any[] = [];

    if (hasReal) {
      series.push({
        name: symbol,
        type: 'candlestick',
        data: chartData.realValues,
        xAxisIndex: 0,
        yAxisIndex: 0,
        itemStyle: {
          color: upColor,
          color0: downColor,
          borderColor: upColor,
          borderColor0: downColor,
        },
        markLine:
          markLineData.length > 0 && showPredCandles
            ? {
                symbol: 'none',
                data: markLineData,
                silent: true,
              }
            : undefined,
      });
    }

    if (hasPrediction) {
      series.push({
        name: 'AI 预测',
        type: 'candlestick',
        data: chartData.predValues,
        xAxisIndex: 0,
        yAxisIndex: 0,
        /** 须高于「预测收盘连线」的 z，否则虚线会盖在 markPoint 标签上 */
        z: 12,
        /** 默认 clip 会裁掉贴近绘图区边缘的 markPoint 文案 */
        clip: false,
        itemStyle: {
          color: 'transparent',
          color0: 'transparent',
          borderColor: upColor,
          borderColor0: downColor,
          borderType: [2, 2],
          borderWidth: 1,
        },
        emphasis: {
          itemStyle: {
            color: hexToRgba(upColor, 0.15),
            color0: hexToRgba(downColor, 0.15),
            borderColor: upColor,
            borderColor0: downColor,
            borderType: [2, 2],
            borderWidth: 1,
          },
        },
        markLine:
          !hasReal && markLineData.length > 0
            ? { symbol: 'none', data: markLineData, silent: true }
            : undefined,
        markPoint: thirtiethPredMarkPoint,
      });

      const predClosePts = chartData.predCloseLine.filter(
        (y): y is number => y != null && Number.isFinite(y)
      );
      if (predClosePts.length >= 2) {
        series.push({
          name: '预测收盘连线',
          type: 'line',
          data: chartData.predCloseLine.map((y) =>
            y != null && Number.isFinite(y) ? y : null
          ),
          xAxisIndex: 0,
          yAxisIndex: 0,
          showSymbol: false,
          connectNulls: false,
          lineStyle: {
            width: 1.5,
            type: 'dashed',
            color: theme === 'dark' ? '#facc15' : '#ca8a04',
          },
          /** 虚线仅作辅助，必须低于 AI 预测系列（含第30根标签），否则会与文案重叠难分 */
          z: 1,
          silent: true,
          showInLegend: false,
        });
      }
    }

    series.push(...emaSeries);

    const volumeAxisIndex = showVolume && hasReal ? 1 : -1;
    let nextAxisIndex = showVolume && hasReal ? 2 : 1;
    const rsiAxisIndex = showRSI && hasReal ? nextAxisIndex++ : -1;
    const macdAxisIndex = showMACD && hasReal ? nextAxisIndex++ : -1;
    const linkedAxisIndexes = [0];
    if (volumeAxisIndex >= 0) linkedAxisIndexes.push(volumeAxisIndex);
    if (rsiAxisIndex >= 0) linkedAxisIndexes.push(rsiAxisIndex);
    if (macdAxisIndex >= 0) linkedAxisIndexes.push(macdAxisIndex);

    if (showVolume && hasReal) {
      series.push({
        name: '成交量',
        type: 'bar',
        data: chartData.volumes,
        xAxisIndex: volumeAxisIndex,
        yAxisIndex: volumeAxisIndex,
      });
    }

    if (showRSI && hasReal && rsiAxisIndex >= 0) {
      series.push({
        name: 'RSI14',
        type: 'line',
        data: chartData.rsi,
        xAxisIndex: rsiAxisIndex,
        yAxisIndex: rsiAxisIndex,
        showSymbol: false,
        symbol: 'none',
        lineStyle: { width: 1.2, color: '#c084fc' },
        itemStyle: { color: '#c084fc' },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [
            { yAxis: 70, lineStyle: { color: '#f87171', type: 'dashed', width: 1 } },
            { yAxis: 30, lineStyle: { color: '#4ade80', type: 'dashed', width: 1 } },
          ],
        },
      });
    }

    if (showMACD && hasReal && macdAxisIndex >= 0) {
      series.push({
        name: 'MACD_hist',
        type: 'bar',
        data: chartData.macdHist.map((value) => {
          if (value === '-' || typeof value !== 'number' || !Number.isFinite(value)) return '-';
          return {
            value,
            itemStyle: { color: value >= 0 ? upColor : downColor },
          };
        }),
        xAxisIndex: macdAxisIndex,
        yAxisIndex: macdAxisIndex,
      });
      series.push({
        name: 'MACD',
        type: 'line',
        data: chartData.macd,
        xAxisIndex: macdAxisIndex,
        yAxisIndex: macdAxisIndex,
        showSymbol: false,
        symbol: 'none',
        lineStyle: { width: 1.2, color: '#58a6ff' },
        itemStyle: { color: '#58a6ff' },
      });
      series.push({
        name: 'MACD_signal',
        type: 'line',
        data: chartData.macdSignal,
        xAxisIndex: macdAxisIndex,
        yAxisIndex: macdAxisIndex,
        showSymbol: false,
        symbol: 'none',
        lineStyle: { width: 1.2, color: '#fbbf24' },
        itemStyle: { color: '#fbbf24' },
      });
    }

    /** 图例项：真实 K 线用默认样式；指标与 AI 预测用 path 短横线，避免圆点/实体块造成误解。 */
    const legendData: echarts.LegendComponentOption['data'] = [];
    if (hasReal) legendData.push(symbol);
    if (hasPrediction) {
      legendData.push({
        name: 'AI 预测',
        icon: 'path://M1,7 L4,7 M5.5,7 L8.5,7 M10,7 L13,7 M14.5,7 L17.5,7',
        itemStyle: {
          color: theme === 'dark' ? '#adb5bd' : '#6c757d',
        },
      });
    }
    if (showEMA && showRealCandles) emaPeriods.forEach((p) => legendData.push({ name: `EMA${p}`, icon: 'path://M1,5 L18,5' }));
    if (showRSI && hasReal) legendData.push({ name: 'RSI14', icon: 'path://M1,5 L18,5' });
    if (showMACD && hasReal) {
      legendData.push({ name: 'MACD', icon: 'path://M1,5 L18,5' });
      legendData.push({ name: 'MACD_signal', icon: 'path://M1,5 L18,5' });
    }

    const subPanelCount = linkedAxisIndexes.length - 1;
    const priceHeight = subPanelCount <= 0 ? undefined : subPanelCount >= 3 ? '42%' : '55%';
    const subPanelHeight = subPanelCount >= 3 ? '10%' : '18%';
    const subPanelTops =
      subPanelCount >= 3
        ? ['54%', '66%', '78%']
        : subPanelCount === 2
          ? ['62%', '78%']
          : ['72%'];

    const grids =
      subPanelCount > 0
        ? [
            { left: 60, right: gridRightPx, top: 60, height: priceHeight },
            ...linkedAxisIndexes.slice(1).map((_, idx) => ({
              left: 60,
              right: gridRightPx,
              top: subPanelTops[idx],
              height: subPanelHeight,
            })),
          ]
        : [{ left: 60, right: gridRightPx, top: 60, bottom: 50 }];

    const categoryAxes =
      subPanelCount > 0
        ? linkedAxisIndexes.map((gridIndex, idx) => ({
            type: 'category' as const,
            data: chartData.dates,
            gridIndex,
            axisLine: { lineStyle: { color: '#30363D' } },
            axisLabel: idx === 0 ? categoryAxisLabel : { show: false },
            axisTick: { show: false },
          }))
        : [
            {
              type: 'category' as const,
              data: chartData.dates,
              axisLine: { lineStyle: { color: '#30363D' } },
              axisLabel: categoryAxisLabel,
            },
          ];

    const valueAxes =
      subPanelCount > 0
        ? linkedAxisIndexes.map((gridIndex) => {
            if (gridIndex === 0) {
              return {
                scale: true,
                ...(priceAxisBounds
                  ? { min: priceAxisBounds.min, max: priceAxisBounds.max }
                  : {}),
                gridIndex,
                splitNumber: 5,
                splitLine: { lineStyle: { color: '#21262d' } },
                axisLine: { lineStyle: { color: '#30363D' } },
                axisLabel: priceAxisLabel,
              };
            }
            if (gridIndex === rsiAxisIndex) {
              return {
                scale: false,
                min: 0,
                max: 100,
                gridIndex,
                splitNumber: 2,
                splitLine: { show: false },
                axisLine: { show: false },
                axisLabel: { show: false },
              };
            }
            return {
              scale: true,
              gridIndex,
              splitNumber: 2,
              splitLine: { show: false },
              axisLine: { show: false },
              axisLabel: { show: false },
            };
          })
        : [
            {
              scale: true,
              ...(priceAxisBounds
                ? { min: priceAxisBounds.min, max: priceAxisBounds.max }
                : {}),
              splitNumber: 5,
              splitLine: { lineStyle: { color: '#21262d' } },
              axisLine: { lineStyle: { color: '#30363D' } },
              axisLabel: priceAxisLabel,
            },
          ];

    return {
      backgroundColor: theme === 'dark' ? '#161B22' : '#fff',
      animation: false,
      legend: {
        data: legendData,
        top: 10,
        left: 'center',
        textStyle: { color: theme === 'dark' ? '#8b949e' : '#333' },
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(22, 27, 34, 0.92)',
        borderColor: '#30363D',
        borderWidth: 1,
        textStyle: { color: '#e6edf3', fontSize: 11 },
        /** 避免竖条过长挡住 K 线；超出可滚动，并尽量贴指针一侧 */
        extraCssText:
          'max-width:min(92vw,300px);max-height:min(48vh,420px);overflow-y:auto;overflow-x:hidden;box-sizing:border-box;padding:6px 8px;',
        confine: true,
        position: (
          point: number[],
          _params: unknown,
          _el: unknown,
          _rect: unknown,
          size: { contentSize: number[]; viewSize: number[] },
        ) => {
          const [mx, my] = point;
          const [tw, th] = size.contentSize;
          const [vw, vh] = size.viewSize;
          const pad = 10;
          let x = mx + 14;
          let y = my - th - pad;
          if (x + tw > vw - pad) x = mx - tw - 14;
          if (x < pad) x = pad;
          if (y < pad) y = my + pad;
          if (y + th > vh - pad) y = vh - th - pad;
          return [x, y];
        },
        formatter: (params: any) => {
          if (!params || params.length === 0) return '';

          const realKline = params.find((p: any) => p.seriesName === symbol);
          const predKline = params.find((p: any) => p.seriesName === 'AI 预测');
          const idx = params[0]?.dataIndex ?? 0;
          const ts = chartData.timestamps[idx];

          /** 单块信息：紧凑 padding；预测类左侧绿虚线 */
          const borderedBlock = (content: string, accent?: 'green-dash') => {
            const acc = accent === 'green-dash' ? 'border-left:2px dashed #4ade80;' : '';
            return `<div style="border:1px solid #30363D;border-radius:4px;padding:4px 7px;background:rgba(13,17,23,0.92);line-height:1.35;${acc}">${content}</div>`;
          };

          const axisLabel = params[0]?.axisValue || '';
          const { base: baseCcy, quote: quoteCcy } = symbolUnits(symbol);
          const th = (s: string) =>
            `<div style="font-weight:600;margin-bottom:3px;line-height:1.25;">${s}</div>`;

          const renderOhlcInner = (label: string, kline: any, isPred: boolean) => {
            const ohlc = extractOhlc(kline.value ?? kline.data);
            if (!ohlc) return '';
            const [open, close, low, high] = ohlc;
            const change = ((close - open) / open * 100).toFixed(2);
            const color = close >= open ? upColor : downColor;
            return `
                <div style="font-weight:600;color:${isPred ? '#adb5bd' : '#e6edf3'};margin-bottom:3px;">${label}</div>
                <div style="line-height:1.35;">开 ${open.toFixed(2)} &nbsp;高 ${high.toFixed(2)} &nbsp;低 ${low.toFixed(2)} &nbsp;收 <span style="color:${color}">${close.toFixed(2)}</span></div>
                <div style="line-height:1.35;">涨跌 <span style="color:${color}">${change}%</span></div>`;
          };

          let html = `<div style="font-size:11px;display:flex;flex-direction:column;gap:4px;">`;

          html += borderedBlock(th(axisLabel));

          if (realKline) {
            let actualInner = renderOhlcInner('实际', realKline, false);
            const rv0 = chartData.realVolumes[idx];
            const rq0 = chartData.realQuoteVols[idx];
            const hasV0 = rv0 != null && Number.isFinite(Number(rv0));
            const hasQ0 = rq0 != null && Number.isFinite(Number(rq0));
            if (hasV0 || hasQ0) {
              const volPart = hasV0
                ? `量 <span style="font-variant-numeric:tabular-nums">${formatTooltipVolume(Number(rv0))}</span> ${baseCcy}`
                : '量 —';
              const quotePart = hasQ0
                ? `额 <span style="font-variant-numeric:tabular-nums">${formatTooltipQuoteVol(Number(rq0))}</span> ${quoteCcy}`
                : '额 —';
              actualInner += `<div style="margin-top:5px;padding-top:5px;border-top:1px solid #30363d;line-height:1.35;">${volPart} &nbsp;·&nbsp; ${quotePart}</div>`;
            }
            if (actualInner) html += borderedBlock(actualInner);
          }

          if (predKline) {
            html += borderedBlock(renderOhlcInner('AI 预测', predKline, true), 'green-dash');
          } else if (realKline && historicalPredCloseByTs && ts != null) {
            const pClose = historicalPredCloseByTs[ts];
            if (pClose != null) {
              const ro = extractOhlc(realKline.value ?? realKline.data);
              if (ro) {
                const realC = ro[1];
                const dev = pClose - realC;
                const devPct = realC !== 0 ? (dev / realC) * 100 : 0;
                const lineColor = Math.abs(devPct) < 0.5 ? '#4ade80' : Math.abs(devPct) < 2 ? '#fbbf24' : '#f87171';
                html += borderedBlock(
                  `<div style="font-weight:600;color:#adb5bd;margin-bottom:3px;">当时预测收盘</div>
                    <div>收 <span style="color:${lineColor}">${pClose.toFixed(2)}</span> &nbsp;价差 ${dev >= 0 ? '+' : ''}${dev.toFixed(4)} &nbsp;偏差% ${devPct >= 0 ? '+' : ''}${devPct.toFixed(3)}%</div>`,
                  'green-dash'
                );
              }
            }
          }

          if (realKline && predKline) {
            const realOhlc = extractOhlc(realKline.value ?? realKline.data);
            const predOhlc = extractOhlc(predKline.value ?? predKline.data);
            if (realOhlc && predOhlc) {
              const dev = predOhlc[1] - realOhlc[1];
              const devPct = realOhlc[1] !== 0 ? (dev / realOhlc[1]) * 100 : 0;
              const devColor =
                Math.abs(devPct) < 0.5 ? '#4ade80' : Math.abs(devPct) < 2 ? '#fbbf24' : '#f87171';
              html += borderedBlock(
                `<div style="font-weight:600;color:#8b949e;margin-bottom:3px;">预测 vs 实盘（收盘）</div>
                <div style="color:${devColor};line-height:1.35;">
                  价差 ${dev >= 0 ? '+' : ''}${dev.toFixed(4)} &nbsp;偏差% ${devPct >= 0 ? '+' : ''}${devPct.toFixed(3)}%
                </div>`
              );
            }
          }

          const rv = chartData.realVolumes[idx];
          const pv = chartData.predVolumes[idx];
          const rq = chartData.realQuoteVols[idx];
          const pq = chartData.predQuoteVols[idx];
          const hasVolActual = rv != null;
          const hasVolPred = pv != null && showPredCandles;
          const hasQuoteActual = rq != null;
          const hasQuotePred = pq != null && showPredCandles;

          /** 与上方「AI 预测」并列：预测量+额 */
          const renderVolumeOhlcStyleInner = (
            label: string,
            isPred: boolean,
            vol: number | null | undefined,
            quote: number | null | undefined,
          ): string => {
            const hv = vol != null && Number.isFinite(Number(vol));
            const hq = quote != null && Number.isFinite(Number(quote));
            if (!hv && !hq) return '';
            const titleColor = isPred ? '#adb5bd' : '#e6edf3';
            const volPart = hv
              ? `量 <span style="font-variant-numeric:tabular-nums">${formatTooltipVolume(Number(vol))}</span> ${baseCcy}`
              : '量 —';
            const quotePart = hq
              ? `额 <span style="font-variant-numeric:tabular-nums">${formatTooltipQuoteVol(Number(quote))}</span> ${quoteCcy}`
              : '额 —';
            return `
                <div style="font-weight:600;color:${titleColor};margin-bottom:3px;">${label}</div>
                <div style="line-height:1.35;">${volPart} &nbsp;·&nbsp; ${quotePart}</div>`;
          };

          const hasTradePred = hasVolPred || hasQuotePred;
          const showVolPredBlock = predKline != null && hasTradePred;

          if (showVolPredBlock) {
            const inner = renderVolumeOhlcStyleInner('AI 预测', true, pv, pq);
            if (inner) html += borderedBlock(inner, 'green-dash');
          }

          const canVolCmp =
            hasVolActual &&
            hasVolPred &&
            rv != null &&
            pv != null &&
            Number.isFinite(rv) &&
            Number.isFinite(pv);
          const canQuoteCmp =
            hasQuoteActual &&
            hasQuotePred &&
            rq != null &&
            pq != null &&
            Number.isFinite(rq) &&
            Number.isFinite(pq);
          if (realKline && predKline && (canVolCmp || canQuoteCmp)) {
            const pctTone = (pct: number) =>
              Math.abs(pct) < 0.5 ? '#4ade80' : Math.abs(pct) < 2 ? '#fbbf24' : '#f87171';
            const cmpLines: string[] = [];
            if (canVolCmp) {
              const volDev = pv! - rv!;
              const volPct = rv! !== 0 ? (volDev / rv!) * 100 : volDev === 0 ? 0 : NaN;
              const vc = Number.isFinite(volPct) ? pctTone(volPct) : '#8b949e';
              const pctStr = Number.isFinite(volPct)
                ? `${volPct >= 0 ? '+' : ''}${volPct.toFixed(3)}%`
                : '—';
              cmpLines.push(
                `<div style="line-height:1.35;color:${vc}">量差 ${volDev >= 0 ? '+' : ''}${formatTooltipVolume(volDev)} ${baseCcy} &nbsp;偏差% ${pctStr}</div>`
              );
            }
            if (canQuoteCmp) {
              const qDev = pq! - rq!;
              const qPct = rq! !== 0 ? (qDev / rq!) * 100 : qDev === 0 ? 0 : NaN;
              const qc = Number.isFinite(qPct) ? pctTone(qPct) : '#8b949e';
              const pctStr = Number.isFinite(qPct)
                ? `${qPct >= 0 ? '+' : ''}${qPct.toFixed(3)}%`
                : '—';
              cmpLines.push(
                `<div style="line-height:1.35;color:${qc}">额差 ${qDev >= 0 ? '+' : ''}${formatTooltipQuoteVol(qDev)} ${quoteCcy} &nbsp;偏差% ${pctStr}</div>`
              );
            }
            if (cmpLines.length > 0) {
              html += borderedBlock(
                `<div style="font-weight:600;color:#8b949e;margin-bottom:3px;">预测 vs 实盘（量·额）</div>${cmpLines.join('')}`
              );
            }
          }

          const emaTooltipRows = params
            .filter((param: any) => /^EMA\d+$/.test(String(param?.seriesName ?? '')))
            .map((param: any) => {
              const value = formatEmaTooltipValue(param.value);
              if (value === '—') return '';
              return `<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;line-height:1.35;">` +
                `<span>${param.marker ?? ''}<span style="color:#c9d1d9;">${param.seriesName}</span></span>` +
                `<span style="font-variant-numeric:tabular-nums;">${value}</span>` +
                `</div>`;
            })
            .filter(Boolean);
          if (emaTooltipRows.length > 0) {
            html += borderedBlock(
              `<div style="font-weight:600;color:#8b949e;margin-bottom:3px;">EMA</div>${emaTooltipRows.join('')}`
            );
          }

          const rsiParam = params.find((param: any) => param.seriesName === 'RSI14');
          if (rsiParam) {
            const rsiValue = formatEmaTooltipValue(rsiParam.value);
            if (rsiValue !== '—') {
              html += borderedBlock(
                `<div style="font-weight:600;color:#8b949e;margin-bottom:3px;">RSI</div>` +
                  `<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;line-height:1.35;">` +
                  `<span>${rsiParam.marker ?? ''}<span style="color:#c9d1d9;">RSI14</span></span>` +
                  `<span style="font-variant-numeric:tabular-nums;">${rsiValue}</span></div>`
              );
            }
          }

          const macdRows = params
            .filter((param: any) => ['MACD', 'MACD_signal', 'MACD_hist'].includes(String(param?.seriesName ?? '')))
            .map((param: any) => {
              const raw = param.value;
              const numeric = typeof raw === 'object' && raw != null && 'value' in raw
                ? Number((raw as { value: unknown }).value)
                : Number(raw);
              if (!Number.isFinite(numeric)) return '';
              return `<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;line-height:1.35;">` +
                `<span>${param.marker ?? ''}<span style="color:#c9d1d9;">${param.seriesName}</span></span>` +
                `<span style="font-variant-numeric:tabular-nums;">${numeric.toFixed(5)}</span></div>`;
            })
            .filter(Boolean);
          if (macdRows.length > 0) {
            html += borderedBlock(
              `<div style="font-weight:600;color:#8b949e;margin-bottom:3px;">MACD</div>${macdRows.join('')}`
            );
          }

          html += '</div>';
          return html;
        },
      },
      axisPointer: {
        link: [{ xAxisIndex: 'all' }],
        label: { backgroundColor: '#30363D' },
      },
      grid: grids,
      xAxis: categoryAxes,
      yAxis: valueAxes,
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: linkedAxisIndexes,
          ...KLINE_TRACKPAD_DATA_ZOOM,
          start: dzStart,
          end: dzEnd,
        },
        {
          show: true,
          xAxisIndex: linkedAxisIndexes,
          type: 'slider',
          bottom: 10,
          start: dzStart,
          end: dzEnd,
          height: 20,
          borderColor: '#30363D',
          backgroundColor: '#161B22',
          fillerColor: 'rgba(88, 166, 255, 0.2)',
          handleStyle: { color: '#58a6ff' },
          textStyle: { color: '#8b949e' },
        },
      ],
      series,
    };
  }, [
    chartData,
    data,
    symbol,
    theme,
    showVolume,
    showEMA,
    showRSI,
    showMACD,
    emaPeriods,
    upColor,
    downColor,
    showRealCandles,
    showPredCandles,
    historicalPredCloseByTs,
    defaultShowLastBars,
    defaultShowLastRealBars,
  ]);

  useEffect(() => {
    if (prevSymbolRef.current !== symbol) {
      prevSymbolRef.current = symbol;
      userAdjustedZoomRef.current = false;
    }
  }, [symbol]);

  useEffect(() => {
    userAdjustedZoomRef.current = false;
  }, [defaultShowLastBars, defaultShowLastRealBars]);

  useEffect(() => {
    if (!chartRef.current) return;
    userAdjustedZoomRef.current = false;
    const inst = echarts.init(chartRef.current, theme);
    chartInstance.current = inst;
    const disposeWheelNavigation = bindKlineWheelNavigation(inst);
    inst.on('datazoom', () => {
      userAdjustedZoomRef.current = true;
    });

    const handleResize = () => inst.resize();
    window.addEventListener('resize', handleResize);

    const el = chartRef.current;
    const ro =
      typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(() => {
            handleResize();
          })
        : null;
    if (el && ro) ro.observe(el);

    return () => {
      window.removeEventListener('resize', handleResize);
      ro?.disconnect();
      disposeWheelNavigation();
      inst.dispose();
      chartInstance.current = null;
    };
  }, [theme]);

  useEffect(() => {
    const inst = chartInstance.current;
    if (inst && connectGroupId) {
      inst.group = connectGroupId;
      echarts.connect(connectGroupId);
    }
  }, [connectGroupId]);

  useEffect(() => {
    const inst = chartInstance.current;
    if (!inst) return;
    const shouldStripZoom =
      userAdjustedZoomRef.current && Array.isArray(option.dataZoom) && option.dataZoom.length > 0;
    const next = shouldStripZoom
      ? {
          ...option,
          dataZoom: option.dataZoom.map((dz: Record<string, unknown>) => {
            const { start: _s, end: _e, ...rest } = dz;
            return rest;
          }),
        }
      : option;
    inst.setOption(next);
  }, [option]);

  const wrapStyle: CSSProperties = {
    width: '100%',
    height: typeof height === 'number' ? `${height}px` : height,
  };

  return (
    <div style={wrapStyle} className="kline-chart relative">
      {emaValueLabels.length > 0 && (
        <div className="kline-ema-value-strip pointer-events-none absolute left-4 top-2 z-10 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-[#161B22]/75 px-2 py-1 text-xs font-semibold shadow-sm shadow-black/20 backdrop-blur-sm">
          {emaValueLabels.map((item) => (
            <span key={item.period} style={{ color: item.color }}>
              EMA{item.period}: {formatEmaValue(item.value)}
            </span>
          ))}
        </div>
      )}
      <div ref={chartRef} className="h-full w-full" />
    </div>
  );
}
