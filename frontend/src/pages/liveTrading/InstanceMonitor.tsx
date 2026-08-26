import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent, MouseEvent as ReactMouseEvent } from 'react';
import {
  Activity,
  ArrowLeft,
  BookOpen,
  ChevronDown,
  DollarSign,
  List,
  Pause,
  Play,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Square,
  Terminal,
  TrendingDown,
  TrendingUp,
  Wallet,
  XCircle,
  Zap,
} from 'lucide-react';
import clsx from 'clsx';
import type { DashboardData, StrategyInfo } from './types';
import { ENGINE_SESSION_ID, paperInstanceKey, toLiveApiInstanceId } from './types';
import { DEFAULT_LIVE_CONFIG } from './constants';
import { MetricCard } from './MetricCard';
import DynamicPoolPanel from './DynamicPoolPanel';
import CryptoSelect from '../../components/CryptoSelect';
import { SELECTED_SEGMENT_CLASS } from '../../utils/selectionStyles';
import SymbolIcon from '../../components/SymbolIcon';
import StrategyParameterSections from '../../components/StrategyParameterSections';
import ThemeDialog from '../../components/ThemeDialog';
import { marketApi, settingsApi, type WatchTradeMarker } from '../../api/client';
import { useWebSocket } from '../../hooks/useWebSocket';
import type { WSMessage } from '../../services/websocketManager';
import type { Kline } from '../../types';
import { formatTimeframeLabel } from '../../utils/timeframe';
import {
  getPositionContractUnitSize,
  getPositionNotionalUsdt,
  getRealizedTradePnl,
  getTradeContractUnitSize,
  getTradeLeverage,
  getTradeMarginUsdt,
  getTradeNotionalUsdt,
  isContractPosition,
  isContractTradeSide,
} from '../../utils/tradeMetrics';
import { getPositionSideDisplay, getTradeSideDisplay } from '../../utils/tradeSide';
import { getStrategyParameterSections } from '../../utils/strategyConfigDisplay';

const POSITION_SIZE_DISPLAY_EPSILON = 0.0000005;
const POSITION_PREVIEW_TIMEFRAME = '15m';
const POSITION_PREVIEW_TIMEFRAME_LABEL = formatTimeframeLabel(POSITION_PREVIEW_TIMEFRAME);
const POSITION_PREVIEW_LIMIT = 72;
const SIMULATION_REVIEW_KLINE_LIMIT = 360;
const SIMULATION_REVIEW_CONTEXT_BARS = 60;
const ACTIVITY_PANEL_MAX_HEIGHT_CLASS = 'max-h-[372px]';
const WatchKlineChart = lazy(() => import('../../components/WatchKlineChart'));
type EChartsModule = typeof import('echarts');
type EChartsInstance = import('echarts').ECharts;
type EquityRange = '1H' | '4H' | '1D' | '7D' | '30D' | 'ALL';
type EquityMetric = 'returnPct' | 'totalPnl' | 'winRate' | 'profitFactor';
type PositionPreviewState = {
  rows: Kline[];
  loading: boolean;
  error: string | null;
};
type PositionPreviewAnchor = {
  symbol: string;
  left: number;
  top: number;
  pinned: boolean;
};
type EquitySampleRow = {
  timestamp: number;
  equity: number;
  totalPnl?: number;
  returnPct?: number;
  winRate?: number;
  profitFactor?: number;
};
export type PaperPositionCloseRequest = {
  symbol: string;
  side?: string | null;
  marketType?: 'spot' | 'swap' | string | null;
};

const EQUITY_RANGE_OPTIONS: Array<{ value: EquityRange; label: string; durationMs: number | null }> = [
  { value: '1H', label: '1H', durationMs: 60 * 60 * 1000 },
  { value: '4H', label: '4H', durationMs: 4 * 60 * 60 * 1000 },
  { value: '1D', label: '1D', durationMs: 24 * 60 * 60 * 1000 },
  { value: '7D', label: '7D', durationMs: 7 * 24 * 60 * 60 * 1000 },
  { value: '30D', label: '30D', durationMs: 30 * 24 * 60 * 60 * 1000 },
  { value: 'ALL', label: '全部', durationMs: null },
];

const EQUITY_METRIC_OPTIONS: Array<{
  value: EquityMetric;
  label: string;
  axisName: string;
  unit: string;
  color: string;
  fillColor: string;
}> = [
  { value: 'returnPct', label: '收益率', axisName: '%', unit: '%', color: '#FF1744', fillColor: 'rgba(255,23,68,0.16)' },
  { value: 'totalPnl', label: '收益', axisName: 'CNY', unit: ' CNY', color: '#60a5fa', fillColor: 'rgba(96,165,250,0.18)' },
  { value: 'winRate', label: '胜率', axisName: '%', unit: '%', color: '#f59e0b', fillColor: 'rgba(245,158,11,0.14)' },
  { value: 'profitFactor', label: '盈亏比', axisName: '', unit: '', color: '#a78bfa', fillColor: 'rgba(167,139,250,0.14)' },
];

export interface InstanceMonitorProps {
  activeInstanceId: string;
  /** 实例名称（控制台卡片标题），用于运行中页眉 */
  headlineTitle?: string;
  initialConfig: typeof DEFAULT_LIVE_CONFIG;
  /** live：轮询结果；paper：可为 null，用 paperDetail 补 */
  dashboard: DashboardData | null;
  /** 当前运行实例对应的策略定义，用于展示只读策略说明 */
  strategyInfo?: StrategyInfo | null;
  events: any[];
  /** 来自 /strategies/:id/trades 的成交记录 */
  trades: any[];
  equityCurve: any[];
  isRunning: boolean;
  isPaused: boolean;
  paperDetail: any | null;
  readOnly?: boolean;
  onBack: () => void;
  onPauseResume: () => void;
  onStop: () => void;
  onAdvance?: () => void;
  advanceBusy?: boolean;
  onClosePosition?: (position: PaperPositionCloseRequest) => Promise<void> | void;
  onDeletePaper?: () => void;
  /** 策略 WS 诊断：交易所 slug，默认 okx */
  wsExchange?: string;
}

function formatDiagNumber(value: unknown, digits = 4): string | null {
  if (value == null || value === '') return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return n.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
}

function formatDiagField(label: string, value: unknown, suffix = '', digits = 4) {
  const formatted = formatDiagNumber(value, digits);
  if (!formatted) return null;
  return { label, value: `${formatted}${suffix}` };
}

function formatSignedUsd(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  return `${sign}¥${Math.abs(value).toFixed(2)}`;
}

function formatUsd(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '--';
  return `¥${n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatRatio(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? n.toFixed(2) : '--';
}

function formatSharpe(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(2) : '--';
}

function formatLeverage(value: number | null): string {
  if (value == null || !Number.isFinite(value) || value <= 0) return '—';
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}x`;
}

const MISSING_SELECTION_LOGIC = '该策略尚未补充核心标的说明。';
const MISSING_TRADING_LOGIC = '该策略尚未补充交易逻辑说明。';

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function stringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || '').trim()).filter(Boolean);
  }
  if (typeof value === 'string' && value.trim()) {
    return value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

function readTextField(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
  }
  return '';
}

function strategyKlineTimeframe(
  strategy: StrategyInfo | null | undefined,
  dashboard: DashboardData | null,
  fallback: string,
): string {
  const config = isRecord(strategy?.config) ? strategy.config : {};
  const raw =
    config.timeframe ??
    config.klineTimeframe ??
    config.kline_timeframe ??
    strategy?.timeframe ??
    dashboard?.system?.timeframe ??
    fallback;
  return String(raw || '15m').trim() || '15m';
}

function compactKlineTimeframeLabel(timeframe: string): string {
  const normalized = String(timeframe || '').trim();
  const match = normalized.match(/^(\d+)([mhdw])$/i);
  if (match) {
    return `${match[1]}${match[2].toUpperCase()}`;
  }
  return normalized.toUpperCase();
}

function collectSimulationReviewSymbols(
  strategy: StrategyInfo | null | undefined,
  dashboard: DashboardData | null,
  trades: any[],
): string[] {
  const runtimeSymbols = new Set<string>();
  dashboard?.positions?.forEach((position) => {
    const symbol = String(position?.symbol || '').trim();
    if (symbol) runtimeSymbols.add(symbol);
  });
  trades.forEach((trade) => {
    const symbol = String(trade?.symbol || '').trim();
    if (symbol) runtimeSymbols.add(symbol);
  });
  if (runtimeSymbols.size > 0) return Array.from(runtimeSymbols);

  const fallbackSymbols = new Set<string>();
  const config = isRecord(strategy?.config) ? strategy.config : {};
  [
    dashboard?.system?.symbol,
    ...(Array.isArray(dashboard?.system?.symbols) ? dashboard?.system?.symbols || [] : []),
    strategy?.symbol,
    ...(Array.isArray(strategy?.symbols) ? strategy?.symbols || [] : []),
    ...stringList(config.tradeSymbols),
    ...stringList(config.trade_symbols),
    ...stringList(config.symbols),
  ].forEach((symbol) => {
    const text = String(symbol || '').trim();
    if (text) fallbackSymbols.add(text);
  });
  return Array.from(fallbackSymbols);
}

function getStrategyLogicSummary(strategy: StrategyInfo | null | undefined): {
  selectionLogic: string;
  tradingLogic: string;
} {
  const config = isRecord(strategy?.config) ? strategy.config : {};
  const nested = isRecord(config.logicSummary) ? config.logicSummary : {};

  return {
    selectionLogic:
      readTextField(config, ['selectionLogic', 'selection_logic']) ||
      readTextField(nested, ['selection', 'selectionLogic', 'selection_logic']) ||
      MISSING_SELECTION_LOGIC,
    tradingLogic:
      readTextField(config, ['tradingLogic', 'trading_logic']) ||
      readTextField(nested, ['trading', 'tradingLogic', 'trading_logic']) ||
      MISSING_TRADING_LOGIC,
  };
}

function normalizeSimulationTradeTimestamp(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return value < 1_000_000_000_000 ? value * 1000 : value;
  }
  if (typeof value === 'string' && value.trim()) {
    const parsedNumber = Number(value);
    if (Number.isFinite(parsedNumber) && parsedNumber > 0) {
      return parsedNumber < 1_000_000_000_000 ? parsedNumber * 1000 : parsedNumber;
    }
    const parsedDate = Date.parse(value);
    if (Number.isFinite(parsedDate)) return parsedDate;
  }
  return 0;
}

function simulationTradeMarkerLabel(side: unknown): 'B' | 'S' {
  const normalized = String(side || '').toLowerCase();
  if (
    normalized.includes('close_short') ||
    normalized.includes('buy') ||
    normalized.includes('open_long') ||
    (normalized.includes('long') && !normalized.includes('close_long'))
  ) {
    return 'B';
  }
  if (
    normalized.includes('close_long') ||
    normalized.includes('sell') ||
    normalized.includes('open_short') ||
    normalized.includes('short') ||
    normalized === 's'
  ) {
    return 'S';
  }
  return 'B';
}

function normalizeSimulationKline(value: any): Kline | null {
  const timestamp = Number(value?.timestamp);
  const open = Number(value?.open);
  const high = Number(value?.high);
  const low = Number(value?.low);
  const close = Number(value?.close);
  const volume = Number(value?.volume ?? 0);
  if (![timestamp, open, high, low, close].every(Number.isFinite)) return null;
  return { timestamp, open, high, low, close, volume: Number.isFinite(volume) ? volume : 0 };
}

function timeframeMs(timeframe: string): number {
  const normalized = String(timeframe || '').trim().toLowerCase();
  const amount = Number.parseInt(normalized, 10) || 1;
  if (normalized.endsWith('m')) return amount * 60_000;
  if (normalized.endsWith('h')) return amount * 60 * 60_000;
  if (normalized.endsWith('d')) return amount * 24 * 60 * 60_000;
  return 60 * 60_000;
}

function buildSimulationTradeMarkers(
  trades: any[],
  symbol: string,
  strategyId: number,
  strategyName: string,
): WatchTradeMarker[] {
  return trades
    .map((trade) => {
      const timestamp = normalizeSimulationTradeTimestamp(trade?.timestamp ?? trade?.time ?? trade?.createdAt ?? trade?.created_at);
      return {
        raw: trade,
        timestamp,
        price: Number(trade?.price),
        quantity: Number(trade?.quantity ?? trade?.amount ?? trade?.size ?? 0),
        symbol: String(trade?.symbol || ''),
        side: String(trade?.side || trade?.action || ''),
      };
    })
    .filter((trade) =>
      trade.symbol === symbol &&
      Number.isFinite(trade.timestamp) &&
      trade.timestamp > 0 &&
      Number.isFinite(trade.price),
    )
    .sort((a, b) => a.timestamp - b.timestamp)
    .map((trade, index) => ({
      id: index + 1,
      label: simulationTradeMarkerLabel(trade.side),
      side: trade.side,
      action: trade.side,
      symbol,
      price: trade.price,
      quantity: Number.isFinite(trade.quantity) ? trade.quantity : null,
      timestamp: trade.timestamp,
      datetime: new Date(trade.timestamp).toLocaleString('zh-CN', { hour12: false }),
      sourceStrategyId: strategyId,
      sourceStrategyName: strategyName,
      subscriptionId: 0,
      liveOrderId: null,
      clientOrderId: null,
    }));
}

function normalizedDecimalPlaces(value: number): number {
  if (!Number.isFinite(value)) return 0;
  const normalized = Math.abs(value).toFixed(8).replace(/0+$/, '').replace(/\.$/, '');
  const decimalIndex = normalized.indexOf('.');
  return decimalIndex >= 0 ? normalized.length - decimalIndex - 1 : 0;
}

function defaultPriceDigits(value: number): number {
  const absValue = Math.abs(value);
  if (absValue >= 1) return 2;
  if (absValue >= 0.01) return 4;
  if (absValue >= 0.000001) return 6;
  return 8;
}

function getPositionPriceDigits(...rawValues: unknown[]): number {
  const values = rawValues
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
  if (values.length === 0) return 2;
  const requiredDigits = values.reduce(
    (digits, value) => Math.max(digits, defaultPriceDigits(value), normalizedDecimalPlaces(value)),
    0,
  );
  return Math.min(Math.max(requiredDigits, 2), 8);
}

function formatPositionPrice(value: unknown, digits: number): string {
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) return '—';
  return numberValue.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatContractUnitSize(value: number | null): string {
  if (value == null || !Number.isFinite(value) || value <= 0) return '—';
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8,
  });
}

function positionPreviewKey(exchange: string, symbol: string): string {
  return `${exchange}:${symbol}`;
}

function normalizePreviewKlines(rows: Kline[]): Kline[] {
  return rows
    .filter((row) => Number.isFinite(Number(row.timestamp)) && Number.isFinite(Number(row.close)))
    .sort((a, b) => Number(a.timestamp) - Number(b.timestamp));
}

function formatPreviewPrice(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  const digits = defaultPriceDigits(n);
  return n.toLocaleString(undefined, {
    minimumFractionDigits: Math.min(digits, 4),
    maximumFractionDigits: digits,
  });
}

function formatPreviewTime(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return new Date(n).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function buildMiniKlineCandles(rows: Kline[], width: number, height: number): {
  candles: Array<{
    key: string;
    x: number;
    bodyWidth: number;
    openY: number;
    closeY: number;
    highY: number;
    lowY: number;
    up: boolean;
  }>;
  up: boolean;
} | null {
  if (rows.length < 2) return null;
  const visibleRows = rows.slice(-48);
  const prices = visibleRows
    .flatMap((row) => [row.open, row.high, row.low, row.close].map(Number))
    .filter(Number.isFinite);
  if (prices.length < 2) return null;
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const pad = Math.max((max - min) * 0.08, Math.abs(max || 1) * 0.001);
  const floor = min - pad;
  const ceil = max + pad;
  const span = Math.max(ceil - floor, 1e-12);
  const slot = width / Math.max(visibleRows.length, 1);
  const bodyWidth = Math.max(2, Math.min(7, slot * 0.58));
  const yFor = (value: unknown) => height - ((Number(value) - floor) / span) * height;
  const candles = visibleRows.map((row, index) => {
    const close = Number(row.close);
    const open = Number.isFinite(Number(row.open)) ? Number(row.open) : close;
    const high = Number.isFinite(Number(row.high)) ? Number(row.high) : Math.max(open, close);
    const low = Number.isFinite(Number(row.low)) ? Number(row.low) : Math.min(open, close);
    const x = index * slot + slot / 2;
    const openY = yFor(open);
    const closeY = yFor(close);
    return {
      key: `${row.timestamp}-${index}`,
      x,
      bodyWidth,
      openY,
      closeY,
      highY: yFor(high),
      lowY: yFor(low),
      up: close >= open,
    };
  });
  return {
    candles,
    up: Number(visibleRows[visibleRows.length - 1]?.close) >= Number(visibleRows[0]?.close),
  };
}

function PositionMarketPreview({
  symbol,
  state,
  pinned = false,
  onClose,
}: {
  symbol: string;
  state?: PositionPreviewState;
  pinned?: boolean;
  onClose?: () => void;
}) {
  const rows = normalizePreviewKlines(state?.rows || []);
  const latest = rows[rows.length - 1];
  const first = rows[0];
  const changePct =
    first && latest && Number(first.close) !== 0
      ? ((Number(latest.close) - Number(first.close)) / Number(first.close)) * 100
      : 0;
  const miniKline = buildMiniKlineCandles(rows, 360, 136);
  const up = miniKline ? miniKline.up : changePct >= 0;

  return (
    <div className="rounded-xl border border-slate-600/70 bg-[#0b111d]/98 p-3 shadow-2xl shadow-black/50 ring-1 ring-white/5 backdrop-blur">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate font-mono text-[12px] font-semibold text-gray-100">{symbol}</div>
          <div className="text-[10px] text-gray-500">{POSITION_PREVIEW_TIMEFRAME_LABEL} K线 · 最近 {POSITION_PREVIEW_LIMIT} 根</div>
        </div>
        <div className="flex items-start gap-2">
          {latest && (
            <div className="text-right">
              <div className="font-mono text-[12px] font-semibold text-gray-100">
                {formatPreviewPrice(latest.close)}
              </div>
              <div className={clsx('text-[10px] font-semibold', up ? 'text-up' : 'text-down')}>
                {changePct >= 0 ? '+' : ''}
                {changePct.toFixed(2)}%
              </div>
            </div>
          )}
          {pinned && onClose && (
            <button
              type="button"
              aria-label="关闭行情预览"
              onClick={onClose}
              className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-crypto-border bg-crypto-bg text-sm leading-none text-gray-400 transition-colors hover:border-gray-500 hover:text-white"
            >
              ×
            </button>
          )}
        </div>
      </div>

      {state?.error ? (
        <div className="flex h-[136px] items-center justify-center rounded-lg border border-red-500/20 bg-red-950/20 text-[11px] text-red-300">
          {state.error}
        </div>
      ) : state?.loading || !state ? (
        <div className="h-[136px] animate-pulse rounded-lg border border-crypto-border bg-slate-800/35" />
      ) : miniKline ? (
        <svg viewBox="0 0 360 136" className="h-[136px] w-full overflow-visible rounded-lg border border-crypto-border bg-crypto-bg/35">
          {[34, 68, 102].map((y) => (
            <line key={y} x1="0" y1={y} x2="360" y2={y} stroke="rgba(148, 163, 184, 0.12)" />
          ))}
          {miniKline.candles.map((candle) => {
            const color = candle.up ? '#22c55e' : '#f43f5e';
            const bodyY = Math.min(candle.openY, candle.closeY);
            const bodyHeight = Math.max(Math.abs(candle.closeY - candle.openY), 1.5);
            return (
              <g key={candle.key}>
                <line
                  x1={candle.x}
                  x2={candle.x}
                  y1={candle.highY}
                  y2={candle.lowY}
                  stroke={color}
                  strokeWidth="1"
                />
                <rect
                  x={candle.x - candle.bodyWidth / 2}
                  y={bodyY}
                  width={candle.bodyWidth}
                  height={bodyHeight}
                  rx="1"
                  fill={color}
                />
              </g>
            );
          })}
          <line x1="0" y1="135.5" x2="360" y2="135.5" stroke="rgba(148, 163, 184, 0.16)" />
        </svg>
      ) : (
        <div className="flex h-[136px] items-center justify-center rounded-lg border border-crypto-border bg-slate-800/25 text-[11px] text-gray-500">
          暂无足够 K 线
        </div>
      )}

      {latest && (
        <div className="mt-2 grid grid-cols-4 gap-2 text-[10px]">
          <div>
            <div className="text-gray-600">开</div>
            <div className="font-mono text-gray-300">{formatPreviewPrice(latest.open)}</div>
          </div>
          <div>
            <div className="text-gray-600">高</div>
            <div className="font-mono text-gray-300">{formatPreviewPrice(latest.high)}</div>
          </div>
          <div>
            <div className="text-gray-600">低</div>
            <div className="font-mono text-gray-300">{formatPreviewPrice(latest.low)}</div>
          </div>
          <div>
            <div className="text-gray-600">时间</div>
            <div className="font-mono text-gray-300">{formatPreviewTime(latest.timestamp)}</div>
          </div>
        </div>
      )}
    </div>
  );
}

function hasDisplayablePositionSize(sizeValue: unknown): boolean {
  const size = Number(sizeValue);
  if (!Number.isFinite(size)) return true;
  return Math.abs(size) >= POSITION_SIZE_DISPLAY_EPSILON;
}

function formatLogTime(value: unknown): string {
  const n = typeof value === 'number' ? value : Number(value);
  const d = Number.isFinite(n) ? new Date(n) : new Date(String(value || ''));
  if (Number.isNaN(d.getTime())) return String(value || '');
  const pad = (x: number, len = 2) => String(x).padStart(len, '0');
  return [
    d.getFullYear(),
    '-',
    pad(d.getMonth() + 1),
    '-',
    pad(d.getDate()),
    ' ',
    pad(d.getHours()),
    ':',
    pad(d.getMinutes()),
    ':',
    pad(d.getSeconds()),
    '.',
    String(Math.floor(d.getMilliseconds() / 100)),
  ].join('');
}

function stableDiagLogId(raw: any, fallbackTs: number): string {
  const ts = raw?.bar_ts_ms ?? raw?.signal_ts_ms ?? raw?.timestamp ?? fallbackTs;
  return [
    'diag',
    raw?.decision ?? '',
    raw?.symbol ?? '',
    ts,
    raw?.summary ?? '',
  ].join('|');
}

function parseEquityTimestamp(value: unknown): number {
  if (value == null || value === '') return Date.now();
  const n = typeof value === 'number' ? value : Number(value);
  if (Number.isFinite(n)) return n < 1_000_000_000_000 ? n * 1000 : n;
  const parsed = Date.parse(String(value));
  return Number.isFinite(parsed) ? parsed : Date.now();
}

function finiteOptionalNumber(value: unknown): number | undefined {
  if (value == null || value === '') return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
}

function normalizeEquityRows(equityCurve: any[]): EquitySampleRow[] {
  return equityCurve
    .map((p: any) => {
      const value = Number(p.equity ?? p.value);
      return {
        timestamp: parseEquityTimestamp(p.timestamp ?? p.time),
        equity: Number.isFinite(value) ? value : 0,
        totalPnl: finiteOptionalNumber(p.totalPnl ?? p.total_pnl),
        returnPct: finiteOptionalNumber(p.returnPct ?? p.return_pct),
        winRate: finiteOptionalNumber(p.winRate ?? p.win_rate),
        profitFactor: finiteOptionalNumber(p.profitFactor ?? p.profit_factor),
      };
    })
    .filter((p) => p.equity > 0)
    .sort((a, b) => a.timestamp - b.timestamp);
}

function metricValueForEquityRow(
  row: EquitySampleRow,
  metric: EquityMetric,
  initialEquity: number,
): number | null {
  if (metric === 'returnPct') {
    return row.returnPct ?? (initialEquity > 0 ? ((row.equity - initialEquity) / initialEquity) * 100 : null);
  }
  if (metric === 'totalPnl') {
    return row.totalPnl ?? (initialEquity > 0 ? row.equity - initialEquity : null);
  }
  if (metric === 'winRate') return row.winRate ?? null;
  return row.profitFactor ?? null;
}

function resolveInitialEquity(value: unknown, fallback: unknown, rows: Array<{ equity: number }>): number {
  const initial = Number(value);
  if (Number.isFinite(initial) && initial > 0) return initial;
  const fallbackValue = Number(fallback);
  if (Number.isFinite(fallbackValue) && fallbackValue > 0) return fallbackValue;
  return rows[0]?.equity || 1;
}

function sameLocalDay(a: number, b: number): boolean {
  const da = new Date(a);
  const db = new Date(b);
  return (
    da.getFullYear() === db.getFullYear() &&
    da.getMonth() === db.getMonth() &&
    da.getDate() === db.getDate()
  );
}

function calculateRiskFromEquityRows(
  rows: Array<{ timestamp: number; equity: number }>,
  initialEquity: number,
  currentEquity: number,
) {
  const metricRows = rows.length > 0 ? [...rows] : [];
  if (currentEquity > 0) {
    const last = metricRows[metricRows.length - 1];
    if (!last || Math.abs(last.equity - currentEquity) > 0.000001) {
      metricRows.push({ timestamp: Date.now(), equity: currentEquity });
    }
  }
  const latestTimestamp = metricRows.reduce(
    (latest, row) => Math.max(latest, row.timestamp),
    0,
  );
  const rollingCutoff = latestTimestamp - 30 * 24 * 60 * 60 * 1000;
  const rollingRows = metricRows.filter((row) => row.timestamp >= rollingCutoff);
  const latest = rollingRows[rollingRows.length - 1]?.equity || currentEquity || initialEquity;
  let peak = rollingRows[0]?.equity || latest;
  let maxDrawdownPct = 0;
  for (const row of rollingRows) {
    peak = Math.max(peak, row.equity);
    if (peak > 0) {
      maxDrawdownPct = Math.max(maxDrawdownPct, ((peak - row.equity) / peak) * 100);
    }
  }
  const currentDrawdownPct = peak > 0 ? Math.max(0, ((peak - latest) / peak) * 100) : 0;
  const now = Date.now();
  const todayRows = metricRows.filter((row) => sameLocalDay(row.timestamp, now));
  const firstTodayEquity = todayRows[0]?.equity;
  const dailyBaseline =
    firstTodayEquity != null
      ? Math.max(initialEquity || 0, firstTodayEquity)
      : initialEquity || latest;
  const dailyLossPct =
    dailyBaseline > 0 ? Math.max(0, ((dailyBaseline - latest) / dailyBaseline) * 100) : 0;
  return {
    latest,
    maxDrawdownPct,
    currentDrawdownPct,
    dailyLossPct,
  };
}

export default function InstanceMonitor({
  activeInstanceId,
  headlineTitle,
  initialConfig,
  dashboard,
  strategyInfo,
  events,
  trades,
  equityCurve,
  isRunning,
  isPaused,
  paperDetail,
  readOnly = false,
  onBack,
  onPauseResume,
  onStop,
  onAdvance,
  advanceBusy = false,
  onClosePosition,
  onDeletePaper,
  wsExchange = 'okx',
}: InstanceMonitorProps) {
  const [logTab, setLogTab] = useState<'trades' | 'events'>('trades');
  const [positionsSectionOpen, setPositionsSectionOpen] = useState(true);
  const [activitySectionOpen, setActivitySectionOpen] = useState(true);
  const [simulationReviewSectionOpen, setSimulationReviewSectionOpen] = useState(true);
  const [equitySectionOpen, setEquitySectionOpen] = useState(true);
  const [riskSectionOpen, setRiskSectionOpen] = useState(true);
  const [feishuEnabled, setFeishuEnabled] = useState(false);
  const [feishuToggling, setFeishuToggling] = useState(false);
  const [echartsLib, setEchartsLib] = useState<EChartsModule | null>(null);
  const [equityRange, setEquityRange] = useState<EquityRange>('1D');
  const [equityMetric, setEquityMetric] = useState<EquityMetric>('returnPct');
  const [selectedSimulationReviewSymbol, setSelectedSimulationReviewSymbol] = useState('');
  const [simulationReviewKlines, setSimulationReviewKlines] = useState<Kline[]>([]);
  const [simulationReviewLoading, setSimulationReviewLoading] = useState(false);
  const [simulationReviewError, setSimulationReviewError] = useState('');
  const [positionPreviewCache, setPositionPreviewCache] = useState<Record<string, PositionPreviewState>>({});
  const [positionPreviewAnchor, setPositionPreviewAnchor] = useState<PositionPreviewAnchor | null>(null);
  const positionPreviewInFlightRef = useRef<Set<string>>(new Set());
  const [closePositionTarget, setClosePositionTarget] = useState<PaperPositionCloseRequest | null>(null);
  const [closePositionBusy, setClosePositionBusy] = useState(false);
  const [closePositionError, setClosePositionError] = useState<string | null>(null);
  const equityChartRef = useRef<HTMLDivElement>(null);
  const equityChartInstance = useRef<EChartsInstance | null>(null);

  const paperKey = paperInstanceKey(activeInstanceId);
  const liveQueryId = toLiveApiInstanceId(activeInstanceId);
  const isPaperView = Boolean(paperKey);
  const isEngineCard = activeInstanceId === ENGINE_SESSION_ID;

  const MAX_STRATEGY_WS = 400;
  const [logicSummaryOpen, setLogicSummaryOpen] = useState(false);
  const [strategyDiagOpen, setStrategyDiagOpen] = useState(false);

  const toggleActivitySection = useCallback(() => {
    setActivitySectionOpen((value) => !value);
  }, []);

  const handleActivitySectionKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      toggleActivitySection();
    },
    [toggleActivitySection],
  );
  const [strategyWsLogs, setStrategyWsLogs] = useState<
    Array<
      | { id: string; ts: number; kind: 'log'; level: string; text: string }
      | { id: string; ts: number; kind: 'diag'; raw: Record<string, unknown> }
    >
  >([]);

  useEffect(() => {
    setLogicSummaryOpen(false);
    setPositionsSectionOpen(true);
    setActivitySectionOpen(true);
    setSimulationReviewSectionOpen(true);
    setEquitySectionOpen(true);
    setRiskSectionOpen(true);
  }, [activeInstanceId]);

  const strategyWsId = useMemo(() => {
    if (isPaperView) return null;
    if (activeInstanceId.startsWith('live:strategy:')) {
      const n = Number(activeInstanceId.replace('live:strategy:', ''));
      return Number.isFinite(n) && n > 0 ? n : null;
    }
    if (activeInstanceId === ENGINE_SESSION_ID) {
      const sid = dashboard?.system?.strategyId;
      if (sid != null && Number.isFinite(Number(sid))) return Number(sid);
      return null;
    }
    return null;
  }, [activeInstanceId, dashboard?.system?.strategyId, isPaperView]);

  const latestStrategyLog = useMemo(() => {
    const latest = strategyWsLogs[0];
    if (!latest) return null;
    if (latest.kind === 'log') {
      return {
        time: formatLogTime(latest.ts),
        text: latest.text || latest.level,
      };
    }
    const raw = latest.raw;
    return {
      time: formatLogTime(raw.bar_ts_ms ?? raw.timestamp ?? latest.ts),
      text: String(raw.summary || raw.decision_label || raw.decision || raw.type || ''),
    };
  }, [strategyWsLogs]);

  const strategyWsIdRef = useRef<number | null>(null);
  strategyWsIdRef.current = strategyWsId;

  const exchangeForStrategyWs = (dashboard?.system?.exchange || wsExchange || 'okx').toLowerCase();

  const onStrategyWsMessage = useCallback((msg: WSMessage) => {
    if (msg.channel !== 'strategy') return;
    const sid = strategyWsIdRef.current;
    if (sid == null || String(msg.symbol) !== String(sid)) return;
    const data = msg.data as Record<string, unknown> | undefined;
    if (!data || typeof data !== 'object') return;
    const ts = typeof msg.timestamp === 'number' ? msg.timestamp : Date.now();
    const id = `${ts}-${Math.random().toString(36).slice(2, 9)}`;
    if (data.type === 'log') {
      setStrategyWsLogs((prev) =>
        [
          {
            id,
            ts,
            kind: 'log' as const,
            level: String(data.level ?? 'info'),
            text: String(data.message ?? ''),
          },
          ...prev,
        ].slice(0, MAX_STRATEGY_WS),
      );
      return;
    }
    if (data.type === 'bar_diag') {
      const row = {
        id: stableDiagLogId(data, ts),
        ts,
        kind: 'diag' as const,
        raw: { ...data },
      };
      setStrategyWsLogs((prev) =>
        [row, ...prev.filter((item) => item.id !== row.id)].slice(0, MAX_STRATEGY_WS),
      );
    }
  }, []);

  const { isConnected, subscribe, unsubscribe } = useWebSocket({
    enabled: false,
    onMessage: onStrategyWsMessage,
  });

  useEffect(() => {
    if (!events.length) return;
    const rows = events
      .filter((evt) => evt?.type === 'log' || evt?.type === 'bar_diag')
      .map((evt, idx) => {
        const ts = Number(evt.bar_ts_ms ?? evt.timestamp ?? Date.now());
        if (evt.type === 'bar_diag') {
          return {
            id: stableDiagLogId(evt, ts),
            ts,
            kind: 'diag' as const,
            raw: { ...evt },
          };
        }
        return {
          id: evt.event_id ? `event-log-${String(evt.event_id)}` : `event-log-${ts}-${idx}`,
          ts,
          kind: 'log' as const,
          level: String(evt.level ?? 'info'),
          text: String(evt.message ?? evt.summary ?? ''),
        };
      });
    if (!rows.length) return;
    setStrategyWsLogs((prev) => {
      const byId = new Map<string, (typeof rows)[number] | (typeof prev)[number]>();
      [...rows, ...prev].forEach((item) => byId.set(item.id, item));
      return Array.from(byId.values())
        .sort((a, b) => b.ts - a.ts)
        .slice(0, MAX_STRATEGY_WS);
    });
  }, [events]);

  useEffect(() => {
    if (isPaperView || strategyWsId == null || !isConnected) return;
    const ex = exchangeForStrategyWs;
    subscribe('strategy', ex, String(strategyWsId));
    return () => unsubscribe('strategy', ex, String(strategyWsId));
  }, [isPaperView, strategyWsId, isConnected, exchangeForStrategyWs, subscribe, unsubscribe]);

  const simulationReviewTimeframe = useMemo(
    () => strategyKlineTimeframe(strategyInfo, dashboard, initialConfig.timeframe),
    [dashboard?.system?.timeframe, initialConfig.timeframe, strategyInfo],
  );
  const simulationReviewTimeframeLabel = useMemo(
    () => compactKlineTimeframeLabel(simulationReviewTimeframe),
    [simulationReviewTimeframe],
  );
  const simulationReviewSymbols = useMemo(
    () => collectSimulationReviewSymbols(strategyInfo, dashboard, trades),
    [dashboard, strategyInfo, trades],
  );
  const simulationReviewStrategyId = Number(strategyInfo?.id ?? dashboard?.system?.strategyId ?? 0) || 0;
  const simulationReviewStrategyName =
    strategyInfo?.name || dashboard?.system?.strategy || headlineTitle || '模拟策略';
  const simulationReviewExchange = (dashboard?.system?.exchange || wsExchange || 'okx').toLowerCase();
  const simulationReviewEnabled =
    !isPaperView &&
    (dashboard?.system?.mode === 'paper' ||
      (dashboard?.system?.mode !== 'live' && dashboard?.system?.dryRun === true));
  const simulationReviewMarkers = useMemo(
    () => buildSimulationTradeMarkers(
      trades,
      selectedSimulationReviewSymbol,
      simulationReviewStrategyId,
      simulationReviewStrategyName,
    ),
    [selectedSimulationReviewSymbol, simulationReviewStrategyId, simulationReviewStrategyName, trades],
  );
  const simulationReviewMarkerTimestampKey = useMemo(
    () =>
      simulationReviewMarkers
        .map((marker) => Number(marker.timestamp))
        .filter((value) => Number.isFinite(value) && value > 0)
        .join(','),
    [simulationReviewMarkers],
  );

  useEffect(() => {
    if (simulationReviewSymbols.length === 0) {
      setSelectedSimulationReviewSymbol('');
      return;
    }
    if (
      !selectedSimulationReviewSymbol ||
      !simulationReviewSymbols.includes(selectedSimulationReviewSymbol)
    ) {
      setSelectedSimulationReviewSymbol(simulationReviewSymbols[0]);
    }
  }, [selectedSimulationReviewSymbol, simulationReviewSymbols]);

  useEffect(() => {
    if (!simulationReviewEnabled || !selectedSimulationReviewSymbol) {
      setSimulationReviewKlines([]);
      setSimulationReviewError('');
      return;
    }

    const timestamps = simulationReviewMarkerTimestampKey
      .split(',')
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value) && value > 0);
    const barMs = timeframeMs(simulationReviewTimeframe);
    const start = timestamps.length > 0
      ? Math.max(0, Math.min(...timestamps) - barMs * SIMULATION_REVIEW_CONTEXT_BARS)
      : undefined;
    const end = timestamps.length > 0
      ? Math.max(Date.now(), Math.max(...timestamps) + barMs * SIMULATION_REVIEW_CONTEXT_BARS)
      : undefined;
    let cancelled = false;

    setSimulationReviewLoading(true);
    setSimulationReviewError('');
    marketApi.getKlines(
      simulationReviewExchange,
      selectedSimulationReviewSymbol,
      simulationReviewTimeframe,
      SIMULATION_REVIEW_KLINE_LIMIT,
      start,
      end,
    )
      .then((rows) => {
        if (cancelled) return;
        setSimulationReviewKlines(
          (rows || []).map(normalizeSimulationKline).filter(Boolean) as Kline[],
        );
      })
      .catch((error: any) => {
        if (cancelled) return;
        setSimulationReviewKlines([]);
        setSimulationReviewError(error?.response?.data?.detail || error?.message || '读取模拟盘 K 线失败');
      })
      .finally(() => {
        if (!cancelled) setSimulationReviewLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    selectedSimulationReviewSymbol,
    simulationReviewEnabled,
    simulationReviewExchange,
    simulationReviewMarkerTimestampKey,
    simulationReviewTimeframe,
  ]);

  useEffect(() => {
    if (!equitySectionOpen || equityCurve.length === 0 || echartsLib) return;
    let cancelled = false;
    import('echarts')
      .then((mod) => {
        if (!cancelled) setEchartsLib(mod);
      })
      .catch((err) => {
        if (!cancelled) console.error('加载收益曲线图表失败:', err);
      });
    return () => {
      cancelled = true;
    };
  }, [echartsLib, equityCurve.length, equitySectionOpen]);

  useEffect(() => {
    if (!equitySectionOpen) {
      equityChartInstance.current?.dispose();
      equityChartInstance.current = null;
      return;
    }
    if (!echartsLib || !equityChartRef.current || equityCurve.length === 0) return;
    if (!equityChartInstance.current) equityChartInstance.current = echartsLib.init(equityChartRef.current);
    const chart = equityChartInstance.current;
    const allRows = normalizeEquityRows(equityCurve);
    const selectedRange = EQUITY_RANGE_OPTIONS.find((item) => item.value === equityRange);
    if (allRows.length === 0) {
      chart.clear();
      chart.setOption({
        backgroundColor: 'transparent',
        title: {
          text: '当前暂无有效收益曲线数据',
          left: 'center',
          top: 'middle',
          textStyle: { color: '#6b7280', fontSize: 13, fontWeight: 500 },
        },
      });
      return;
    }
    const latestTimestamp = allRows[allRows.length - 1].timestamp;
    const rangeWindow =
      selectedRange?.durationMs == null
        ? null
        : {
            start: latestTimestamp - selectedRange.durationMs,
            end: latestTimestamp,
          };
    const rows =
      rangeWindow == null
        ? allRows
        : allRows.filter((row) => row.timestamp >= rangeWindow.start && row.timestamp <= rangeWindow.end);
    const rangeAxisWindow =
      rangeWindow == null
        ? {}
        : {
            min: rangeWindow.start,
            max: rangeWindow.end,
          };
    if (rows.length === 0) {
      chart.clear();
      chart.setOption({
        backgroundColor: 'transparent',
        title: {
          text: '当前时间范围暂无收益曲线数据',
          left: 'center',
          top: 'middle',
          textStyle: { color: '#6b7280', fontSize: 13, fontWeight: 500 },
        },
      });
      return;
    }
    const initial = resolveInitialEquity(
      dashboard?.equity?.initial,
      initialConfig.initialEquity,
      allRows,
    );
    const selectedMetric = EQUITY_METRIC_OPTIONS.find((item) => item.value === equityMetric) ?? EQUITY_METRIC_OPTIONS[0];
    const primaryData = rows
      .map((row) => {
        const value = metricValueForEquityRow(row, equityMetric, initial);
        return value == null || !Number.isFinite(value) ? null : [row.timestamp, value];
      })
      .filter(Boolean) as Array<[number, number]>;
    if (primaryData.length === 0) {
      chart.clear();
      chart.setOption({
        backgroundColor: 'transparent',
        title: {
          text: `当前时间范围暂无${selectedMetric.label}采样数据`,
          left: 'center',
          top: 'middle',
          textStyle: { color: '#6b7280', fontSize: 13, fontWeight: 500 },
        },
      });
      return;
    }
    const primaryFormatter = selectedMetric.unit === '%' ? '{value}%' : selectedMetric.unit ? '${value}' : '{value}';
    const chartGrids = [{ top: 18, right: 56, bottom: 34, left: 72 }];
    const chartXAxes = [
      {
        ...rangeAxisWindow,
        type: 'time',
        gridIndex: 0,
        axisLine: { lineStyle: { color: '#333' } },
        axisLabel: { color: '#888', fontSize: 10 },
      },
    ];
    const chartYAxes = [
      {
        type: 'value',
        name: selectedMetric.axisName,
        gridIndex: 0,
        scale: true,
        axisLine: { lineStyle: { color: '#333' } },
        axisLabel: { color: '#888', fontSize: 10, formatter: primaryFormatter },
        splitLine: { lineStyle: { color: '#222' } },
      },
    ];
    const primarySeries = {
      name: selectedMetric.label,
      type: 'line',
      xAxisIndex: 0,
      yAxisIndex: 0,
      data: primaryData,
      smooth: false,
      lineStyle: { color: selectedMetric.color, width: 2.2 },
      areaStyle: {
        color: new echartsLib.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: selectedMetric.fillColor },
          { offset: 1, color: 'rgba(15,23,42,0)' },
        ]),
      },
      showSymbol: false,
    };
    const chartSeries = [primarySeries];
    chart.resize();
    chart.setOption({
      backgroundColor: 'transparent',
      animation: false,
      grid: chartGrids,
      xAxis: chartXAxes,
      yAxis: chartYAxes,
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#1a1a2e',
        borderColor: '#333',
        textStyle: { color: '#fff', fontSize: 12 },
        formatter: (params: any) => {
          const items = Array.isArray(params) ? params : [params];
          const ts = Number(items[0]?.value?.[0] ?? items[0]?.axisValue);
          const time = Number.isFinite(ts)
            ? new Date(ts).toLocaleString('zh-CN', {
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false,
              })
            : '';
          const lines = items
            .map((item: any) => {
              const value = Number(item.value?.[1]);
              if (!Number.isFinite(value)) return '';
              return `${item.marker}${item.seriesName} <b>${value.toFixed(2)}${selectedMetric.unit}</b>`;
            })
            .filter(Boolean);
          return [time, ...lines].join('<br/>');
        },
      },
      series: chartSeries,
    }, { notMerge: true });
  }, [
    dashboard?.equity?.initial,
    echartsLib,
    equityCurve,
    equityMetric,
    equityRange,
    equitySectionOpen,
    initialConfig.initialEquity,
  ]);

  useEffect(() => {
    const onResize = () => equityChartInstance.current?.resize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    return () => {
      equityChartInstance.current?.dispose();
      equityChartInstance.current = null;
    };
  }, []);

  useEffect(() => {
    const f = dashboard?.feishu;
    if (f) setFeishuEnabled(f.enabled);
  }, [dashboard?.feishu?.enabled]);

  const getEventIcon = (type: string) => {
    switch (type) {
      case 'bar_diag':
      case 'log':
        return <Activity className="w-3.5 h-3.5 text-cyan-400" />;
      case 'signal':
        return <Zap className="w-3.5 h-3.5 text-blue-400" />;
      case 'order':
        return <DollarSign className="w-3.5 h-3.5 text-green-400" />;
      case 'close':
        return <TrendingDown className="w-3.5 h-3.5 text-yellow-400" />;
      case 'error':
        return <XCircle className="w-3.5 h-3.5 text-red-400" />;
      case 'system':
        return <Settings2 className="w-3.5 h-3.5 text-gray-400" />;
      default:
        return <Activity className="w-3.5 h-3.5 text-gray-500" />;
    }
  };

  const formatEventTime = (evt: any) => {
    const rawTs = evt?.bar_ts_ms ?? evt?.timestamp;
    if (rawTs != null) return formatLogTime(rawTs);
    if (evt?.time) return formatLogTime(evt.time);
    return '';
  };

  const eventTitle = (evt: any) => {
    const details = evt?.details || {};
    const title =
      evt?.message ||
      evt?.summary ||
      details.message ||
      details.action ||
      evt?.decision_label ||
      evt?.decision ||
      evt?.type;
    return String(title || '系统事件');
  };

  const eventReason = (evt: any) => {
    const details = evt?.details || {};
    return String(evt?.detail || details.reason || evt?.broker_reason || evt?.broker_error || '');
  };

  const previewExchange = (dashboard?.system?.exchange || wsExchange || 'okx').toLowerCase();
  const loadPositionPreview = useCallback(
    async (symbol: string) => {
      const key = positionPreviewKey(previewExchange, symbol);
      const existing = positionPreviewCache[key];
      if (existing?.loading || existing?.rows?.length || positionPreviewInFlightRef.current.has(key)) {
        return;
      }

      positionPreviewInFlightRef.current.add(key);
      setPositionPreviewCache((prev) => {
        return {
          ...prev,
          [key]: {
            rows: prev[key]?.rows || [],
            loading: true,
            error: null,
          },
        };
      });
      try {
        const rows = await marketApi.getKlines(
          previewExchange,
          symbol,
          POSITION_PREVIEW_TIMEFRAME,
          POSITION_PREVIEW_LIMIT,
        );
        setPositionPreviewCache((prev) => ({
          ...prev,
          [key]: {
            rows,
            loading: false,
            error: null,
          },
        }));
      } catch {
        setPositionPreviewCache((prev) => ({
          ...prev,
          [key]: {
            rows: [],
            loading: false,
            error: '行情加载失败',
          },
        }));
      } finally {
        positionPreviewInFlightRef.current.delete(key);
      }
    },
    [positionPreviewCache, previewExchange],
  );
  const openPositionPreview = useCallback(
    (symbol: string, element: HTMLElement, pinned = false) => {
      const rect = element.getBoundingClientRect();
      const width = 420;
      const height = 286;
      const left = Math.min(Math.max(rect.left, 12), Math.max(12, window.innerWidth - width - 12));
      const top = Math.min(rect.bottom + 8, Math.max(12, window.innerHeight - height - 12));
      setPositionPreviewAnchor((prev) => {
        if (prev?.pinned && !pinned) return prev;
        return { symbol, left, top, pinned };
      });
      void loadPositionPreview(symbol);
    },
    [loadPositionPreview],
  );
  const togglePinnedPositionPreview = useCallback(
    (symbol: string, element: HTMLElement, event: ReactMouseEvent<HTMLButtonElement>) => {
      event.preventDefault();
      event.stopPropagation();
      const rect = element.getBoundingClientRect();
      const width = 420;
      const height = 286;
      const left = Math.min(Math.max(rect.left, 12), Math.max(12, window.innerWidth - width - 12));
      const top = Math.min(rect.bottom + 8, Math.max(12, window.innerHeight - height - 12));
      setPositionPreviewAnchor((prev) => (
        prev?.pinned && prev.symbol === symbol
          ? null
          : { symbol, left, top, pinned: true }
      ));
      void loadPositionPreview(symbol);
    },
    [loadPositionPreview],
  );
  const closePositionPreview = useCallback((force = false) => {
    setPositionPreviewAnchor((prev) => {
      if (prev?.pinned && !force) return prev;
      return null;
    });
  }, []);
  const closeTemporaryPositionPreview = useCallback(() => {
    closePositionPreview(false);
  }, [closePositionPreview]);
  const closePinnedPositionPreview = useCallback(() => {
    closePositionPreview(true);
  }, [closePositionPreview]);

  if (isPaperView) {
    const p = paperDetail || {};
    return (
      <div className="space-y-5">
        <div className="space-y-3">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-crypto-border text-sm text-gray-300 hover:text-white hover:border-gray-500"
          >
            <ArrowLeft className="w-4 h-4" />
            返回控制台
          </button>
          <div>
            <h2 className="text-xl md:text-2xl font-bold text-white truncate">
              {headlineTitle || '模拟实例详情'}
            </h2>
            <span className="text-xs text-gray-500 font-mono">{paperKey}</span>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MetricCard
            label="收益率"
            value={`${(p.totalReturnPct ?? p.total_return_pct ?? 0).toFixed(1)}%`}
            icon={<TrendingUp className="w-4 h-4" />}
            color={(p.totalReturnPct ?? p.total_return_pct ?? 0) >= 0 ? 'up' : 'down'}
          />
          <MetricCard
            label="夏普"
            value={(p.sharpeRatio ?? p.sharpe_ratio ?? 0).toFixed(2)}
            icon={<Activity className="w-4 h-4" />}
            color="blue"
          />
          <MetricCard
            label="30日最大回撤"
            value={`${(p.maxDrawdownPct ?? p.max_drawdown_pct ?? 0).toFixed(1)}%`}
            icon={<TrendingDown className="w-4 h-4" />}
            color="red"
          />
          <MetricCard
            label="交易对"
            value={String(p.symbol || '—')}
            icon={<DollarSign className="w-4 h-4" />}
            color="gray"
          />
        </div>
        <p className="text-sm text-gray-500">
          模拟实例权益曲线与事件流依赖后端会话存储；当前占位展示元数据。引擎级监控请使用实盘/模拟运行会话。
        </p>
        {onDeletePaper && !readOnly && (
          <button
            type="button"
            onClick={onDeletePaper}
            className="px-4 py-2 rounded-lg bg-red-500/15 text-red-400 border border-red-500/30 text-sm"
          >
            删除此模拟实例
          </button>
        )}
      </div>
    );
  }

  const sys = dashboard?.system;
  const equity = dashboard?.equity;
  const perf = dashboard?.performance;
  const risk = dashboard?.risk;
  const basePositions = dashboard?.positions ?? [];
  const positions = basePositions
    .filter((row) => hasDisplayablePositionSize(row.size))
    .map((row) => {
      const markPrice = row.markPrice;
      const size = Number(row.size);
      const entryPrice = Number(row.entryPrice);
      const mark = Number(markPrice);
      const explicitUnrealizedPnl = Number(row.unrealizedPnl);
      const canEstimateSpotPnl =
        Number.isFinite(size) && Number.isFinite(entryPrice) && Number.isFinite(mark);
      const unrealizedPnl =
        Number.isFinite(explicitUnrealizedPnl)
          ? explicitUnrealizedPnl
          : canEstimateSpotPnl
            ? (mark - entryPrice) * size
            : row.unrealizedPnl;
      return {
        ...row,
        markPrice,
        unrealizedPnl,
      };
    });
  const unrealizedRaw = dashboard?.account?.unrealizedPnl;
  const realtimeUnrealizedTotal = positions.reduce((sum, row) => sum + Number(row.unrealizedPnl ?? 0), 0);
  const unrealizedTotal =
    positions.length > 0
      ? realtimeUnrealizedTotal
      : typeof unrealizedRaw === 'number' && Number.isFinite(unrealizedRaw)
        ? unrealizedRaw
        : Number(unrealizedRaw) || 0;
  const hasContractPositions = positions.some(isContractPosition);
  const hasContractTrades = trades.some((trade) => (
    isContractTradeSide(trade.side) || String(trade.symbol ?? '').includes(':')
  ));
  const equityRowsForMetrics = normalizeEquityRows(equityCurve);
  const initialEquityForMetrics = resolveInitialEquity(
    equity?.initial,
    initialConfig.initialEquity,
    equityRowsForMetrics,
  );
  const currentEquityForMetrics = Number(equity?.current);
  const calculatedRiskMetrics = calculateRiskFromEquityRows(
    equityRowsForMetrics,
    initialEquityForMetrics,
    Number.isFinite(currentEquityForMetrics)
      ? currentEquityForMetrics
      : equityRowsForMetrics[equityRowsForMetrics.length - 1]?.equity || initialEquityForMetrics,
  );
  const backendRollingDrawdown = Number(perf?.maxDrawdown);
  const displayRiskMetrics = {
    ...calculatedRiskMetrics,
    maxDrawdownPct: Number.isFinite(backendRollingDrawdown)
      ? backendRollingDrawdown
      : calculatedRiskMetrics.maxDrawdownPct,
  };

  const formatTradeTime = (ts: unknown) => {
    if (ts == null) return '—';
    const n = typeof ts === 'number' ? ts : Number(ts);
    if (!Number.isFinite(n)) return '—';
    return new Date(n).toLocaleString();
  };

  const totalPnlAmountRaw = equity?.change ?? 0;
  const totalPnlAmount =
    typeof totalPnlAmountRaw === 'number' && Number.isFinite(totalPnlAmountRaw)
      ? totalPnlAmountRaw
      : Number(totalPnlAmountRaw) || 0;
  const returnPctRaw = perf?.totalPnlPct ?? equity?.changePct ?? 0;
  const returnPct =
    typeof returnPctRaw === 'number' && Number.isFinite(returnPctRaw)
      ? returnPctRaw
      : Number(returnPctRaw) || 0;
  const currentEquityAmount = Number(equity?.current);
  const displayEquityAmount = Number.isFinite(currentEquityAmount)
    ? currentEquityAmount
    : initialConfig.initialEquity;
  const state = sys?.state || 'idle';
  // 以后端 system.mode / dryRun 为准（与 DB is_paper_trading 一致）；避免仅依赖 dryRun 缺省误判
  const runningDryRun =
    sys == null
      ? isPaperView
      : sys.mode === 'live'
        ? false
        : sys.mode === 'paper'
          ? true
          : sys.dryRun === true;
  const positionQuantityLabel = runningDryRun ? '持仓数量（股）' : '张数/数量';
  const tradeQuantityLabel = runningDryRun ? '成交数量（股）' : '张数/数量';
  const feishu = dashboard?.feishu;
  const logicSummary = getStrategyLogicSummary(strategyInfo);
  const parameterSections = getStrategyParameterSections(isRecord(strategyInfo?.config) ? strategyInfo.config : {});
  const feishuStatusText = !feishu?.webhookConfigured
    ? 'Webhook 未配置'
    : feishuEnabled
      ? `已启用，已发送 ${feishu?.messagesSent ?? 0} 条`
      : '未启用';
  const riskDescriptionItems = risk
    ? [
        {
          title: '熔断保护',
          status: risk.circuitBreaker ? '已触发' : '正常',
          statusClass: risk.circuitBreaker
            ? 'border-red-500/40 bg-red-500/10 text-red-300'
            : 'border-green-500/30 bg-green-500/10 text-green-300',
          description: risk.circuitBreaker
            ? '系统已触发熔断保护，策略不应继续新增风险敞口，需人工复核后再恢复运行。'
            : '当前未触发熔断，策略仍按自身交易逻辑、启动风控和账户约束继续运行。',
        },
        {
          title: '回撤与亏损监控',
          status: `30日最大回撤 ${displayRiskMetrics.maxDrawdownPct.toFixed(2)}%`,
          statusClass: 'border-amber-500/30 bg-amber-500/10 text-amber-200',
          description: `本区与顶部指标均按当前时点向前滚动 30 个自然日计算最大回撤，同时跟踪日内亏损 ${displayRiskMetrics.dailyLossPct.toFixed(2)}%。出现连续亏损或回撤扩大时，应先查看成交、持仓和诊断事件。`,
        },
        {
          title: '仓位边界',
          status: positions.length > 0 ? `${positions.length} 个持仓` : '当前无持仓',
          statusClass: positions.length > 0
            ? 'border-blue-500/30 bg-blue-500/10 text-blue-200'
            : 'border-crypto-border bg-white/[0.03] text-gray-300',
          description: hasContractPositions
            ? 'A 股持仓会持续暴露市场与流动性风险，新增信号仍需通过 T+1、涨跌停、整手和仓位上限风控。'
            : '当前没有 A 股持仓；下一次交易信号仍会受现金、T+1、涨跌停和仓位上限约束。',
        },
      ]
    : [];

  const handleFeishuToggle = async () => {
    if (feishuToggling) return;
    setFeishuToggling(true);
    try {
      const res = await settingsApi.setNotify(!feishuEnabled);
      setFeishuEnabled(res.enabled);
    } catch {
      /* 轮询仪表盘后会与后端一致 */
    } finally {
      setFeishuToggling(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-crypto-border text-sm text-gray-300 hover:text-white hover:border-gray-500"
        >
          <ArrowLeft className="w-4 h-4" />
          返回控制台
        </button>
        <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
          <div className="min-w-0 space-y-2 flex-1">
            {(headlineTitle || sys?.strategy) && (
              <h1 className="text-2xl sm:text-3xl font-bold text-white tracking-tight truncate">
                {headlineTitle || sys?.strategy || '策略监控'}
              </h1>
            )}
            <div className="flex items-center gap-3 flex-wrap">
              <div
                className={clsx(
                  'w-3 h-3 rounded-full shrink-0 animate-pulse',
                  state === 'running'
                    ? 'bg-green-400'
                    : state === 'paused'
                      ? 'bg-yellow-400'
                      : state === 'circuit_breaker'
                        ? 'bg-red-400'
                        : 'bg-gray-500',
                )}
              />
              <span className="text-base font-bold text-white">
                {state === 'running'
                  ? '运行中'
                  : state === 'paused'
                    ? '已暂停'
                    : state === 'circuit_breaker'
                      ? '风控熔断'
                      : state === 'stopped'
                        ? '已停止'
                        : '空闲'}
              </span>
              {!runningDryRun && (
                <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-red-500/20 text-red-400">
                  实盘
                </span>
              )}
              {liveQueryId != null && (
                <span className="text-[10px] text-gray-500 font-mono">
                  instance_id={String(liveQueryId)}
                </span>
              )}
              {isEngineCard && (
                <span className="text-[10px] text-gray-500 font-mono">engine_session</span>
              )}
              {sys && (
                <span className="text-xs text-gray-500">
                  {sys.strategy} · {sys.symbol} · {formatTimeframeLabel(sys.timeframe)}
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
          {runningDryRun && isRunning && !readOnly && onAdvance && (
            <button
              type="button"
              onClick={onAdvance}
              disabled={advanceBusy}
              className="flex items-center gap-1.5 rounded-lg border border-blue-500/30 bg-blue-600/20 px-4 py-2 text-sm text-blue-300 transition-colors hover:bg-blue-600/30 disabled:cursor-wait disabled:opacity-60"
            >
              <RefreshCw className={clsx('h-4 w-4', advanceBusy && 'animate-spin')} />
              {advanceBusy ? '推进中…' : '推进下一交易日'}
            </button>
          )}
          {(isRunning || isPaused) && !readOnly && (
            <button
              type="button"
              onClick={onPauseResume}
              className={clsx(
                'flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm transition-colors',
                isPaused
                  ? 'bg-green-600/20 text-green-400 border border-green-500/30 hover:bg-green-600/30'
                  : 'bg-yellow-600/20 text-yellow-400 border border-yellow-500/30 hover:bg-yellow-600/30',
              )}
            >
              {isPaused ? (
                <>
                  <Play className="w-4 h-4" />
                  恢复交易
                </>
              ) : (
                <>
                  <Pause className="w-4 h-4" />
                  暂停交易
                </>
              )}
            </button>
          )}
          {(isRunning || isPaused) && !readOnly && (
            <button
              type="button"
              onClick={onStop}
              className="flex items-center gap-1.5 px-4 py-2 bg-red-600/20 text-red-400 border border-red-500/30 rounded-lg text-sm hover:bg-red-600/30 transition-colors"
            >
              <Square className="w-4 h-4" />
              关闭交易
            </button>
          )}
        </div>
      </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-9 gap-3">
        <MetricCard
          label="账户总额"
          value={formatUsd(displayEquityAmount)}
          icon={<DollarSign className="w-4 h-4" />}
          color="blue"
        />
        <MetricCard
          label="总盈亏"
          value={formatSignedUsd(totalPnlAmount)}
          icon={totalPnlAmount >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
          color={totalPnlAmount >= 0 ? 'up' : 'down'}
        />
        <MetricCard
          label="收益率"
          value={`${returnPct >= 0 ? '+' : ''}${returnPct.toFixed(2)}%`}
          icon={returnPct >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
          color={returnPct >= 0 ? 'up' : 'down'}
        />
        <MetricCard
          label="夏普"
          value={formatSharpe(perf?.sharpeRatio)}
          icon={<Activity className="w-4 h-4" />}
          color="blue"
        />
        <MetricCard
          label="胜率"
          value={`${(perf?.winRate ?? 0).toFixed(1)}%`}
          icon={<Activity className="w-4 h-4" />}
          color="blue"
        />
        <MetricCard
          label="盈亏比"
          value={formatRatio(perf?.profitFactor)}
          icon={<Zap className="w-4 h-4" />}
          color="blue"
        />
        <MetricCard
          label="交易次数"
          value={String(perf?.totalTrades ?? 0)}
          icon={<Activity className="w-4 h-4" />}
          color="blue"
        />
        <MetricCard
          label="30日最大回撤"
          value={`${displayRiskMetrics.maxDrawdownPct.toFixed(1)}%`}
          icon={<TrendingDown className="w-4 h-4" />}
          color="red"
        />
        <MetricCard
          label="运行时间"
          value={sys?.uptime || '-'}
          icon={<Activity className="w-4 h-4" />}
          color="gray"
        />
      </div>

      <section className="rounded-xl border border-crypto-border bg-crypto-card/80">
        <button
          type="button"
          aria-expanded={logicSummaryOpen}
          onClick={() => setLogicSummaryOpen((value) => !value)}
          className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors hover:bg-white/[0.03]"
        >
          <span className="flex min-w-0 items-center gap-2">
            <BookOpen className="h-4 w-4 shrink-0 text-blue-400" />
            <h2 className="truncate text-base font-semibold text-white">核心标的与交易逻辑</h2>
          </span>
          <ChevronDown
            className={clsx('h-4 w-4 shrink-0 text-gray-500 transition-transform', logicSummaryOpen && 'rotate-180 text-gray-300')}
          />
        </button>
        {logicSummaryOpen && (
          <div className="grid gap-4 border-t border-crypto-border px-4 py-4 lg:grid-cols-2">
            <div className="border-l border-blue-500/40 pl-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-blue-300">
                <List className="h-4 w-4" />
                核心标的
              </div>
              <p className="text-sm leading-6 text-gray-300">{logicSummary.selectionLogic}</p>
            </div>
            <div className="border-l border-emerald-500/40 pl-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-emerald-300">
                <ShieldCheck className="h-4 w-4" />
                交易逻辑
              </div>
              <p className="text-sm leading-6 text-gray-300">{logicSummary.tradingLogic}</p>
            </div>
          </div>
        )}
      </section>

      <StrategyParameterSections sections={parameterSections} />

      {!isPaperView && (
        <div className="bg-crypto-card border border-crypto-border rounded-xl overflow-hidden">
          <div className="flex items-stretch border-b border-crypto-border">
            <button
              type="button"
              onClick={() => setStrategyDiagOpen((o) => !o)}
              className="flex-1 min-w-0 flex items-center gap-2 px-4 py-3 text-left text-base font-semibold text-white hover:bg-white/5 transition-colors"
            >
              <Terminal className="w-4 h-4 text-cyan-400 shrink-0" />
              策略运行诊断日志
              <span className="text-xs font-normal text-gray-500 ml-1 flex flex-wrap items-center gap-x-2">
                <span>
                  {exchangeForStrategyWs} · #{strategyWsId ?? '—'}
                </span>
                {isConnected ? (
                  <span className="text-emerald-500">WS 已连接</span>
                ) : (
                  <span className="text-amber-500">WS 未连接</span>
                )}
              </span>
              {!strategyDiagOpen && latestStrategyLog && (
                <span className="ml-3 min-w-0 flex-1 flex items-center gap-2 text-left text-xs font-normal">
                  <span className="shrink-0 text-gray-500">{latestStrategyLog.time}</span>
                  <span className="truncate text-purple-400">{latestStrategyLog.text}</span>
                </span>
              )}
              <ChevronDown
                className={clsx(
                  'ml-auto h-4 w-4 shrink-0 text-gray-500 transition-transform',
                  strategyDiagOpen && 'rotate-180 text-gray-300',
                )}
              />
            </button>
            <button
              type="button"
              onClick={() => setStrategyWsLogs([])}
              className="shrink-0 px-4 py-3 text-xs text-gray-500 hover:text-red-400 hover:bg-red-500/10 border-l border-crypto-border transition-colors"
            >
              清空
            </button>
          </div>
          {strategyDiagOpen && (
            <div className="max-h-[min(420px,50vh)] overflow-y-auto px-3 py-2 space-y-2 bg-crypto-bg/40 font-mono text-[11px]">
              {strategyWsId == null ? (
                <p className="text-gray-500 py-4 text-center text-xs">
                  等待 strategyId（引擎会话需仪表盘返回 strategyId 后再订阅）。
                </p>
              ) : strategyWsLogs.length === 0 ? (
                <p className="text-gray-500 py-4 text-center text-xs leading-relaxed">
                  暂无推送。策略运行后每根 K 线会推送 bar_diag（可关 config.strategy_diagnostic_ws）。
                  <br />
                  亦会显示引擎 _broadcast_log 的文本行。
                </p>
              ) : (
                strategyWsLogs.map((entry) => (
                  <div
                    key={entry.id}
                    className="rounded-lg border border-crypto-border/60 bg-crypto-bg/80 p-2"
                  >
                    {entry.kind === 'log' ? (
                      <div className="overflow-x-auto">
                        <div className="flex min-w-max items-center gap-2 whitespace-nowrap">
                          <span className="shrink-0 text-gray-600 tabular-nums">
                            {formatLogTime(entry.ts)}
                          </span>
                          <span
                            className={clsx(
                              'shrink-0 text-[10px] uppercase',
                              entry.level === 'error' ? 'text-red-400' : 'text-gray-500',
                            )}
                          >
                            {entry.level}
                          </span>
                          <span className="text-gray-200">{entry.text}</span>
                        </div>
                      </div>
                    ) : (
                      <div className="overflow-x-auto">
                        <div className="flex min-w-max items-center gap-2 whitespace-nowrap text-gray-400">
                          <span className="shrink-0 text-gray-600 tabular-nums">
                            {formatLogTime(entry.raw.bar_ts_ms ?? entry.raw.timestamp ?? entry.ts)}
                          </span>
                          <span className="text-cyan-400 font-semibold">
                            {String(entry.raw.decision_label ?? entry.raw.decision ?? '—')}
                          </span>
                          <span>bar #{String(entry.raw.bar_index ?? '')}</span>
                          {entry.raw.summary != null && entry.raw.summary !== '' && (
                            <span className="text-gray-200">
                              {String(entry.raw.summary)}
                            </span>
                          )}
                          <span className="flex items-center gap-1.5 text-[10px]">
                            {[
                              { label: '交易对', value: entry.raw.symbol ? String(entry.raw.symbol) : '' },
                              formatDiagField('价格', entry.raw.close, '', 2),
                              entry.raw.confidence != null && entry.raw.confidence_min != null
                                ? {
                                    label: '置信度',
                                    value: `${formatDiagNumber(entry.raw.confidence, 3)}/${formatDiagNumber(entry.raw.confidence_min, 3)}`,
                                  }
                                : null,
                              formatDiagField('预测涨跌', entry.raw.predicted_change_pct, '%', 4),
                              formatDiagField('预测价', entry.raw.predicted_close, '', 2),
                              formatDiagField('买入金额', entry.raw.quote_usdt, ' USDT', 2),
                              formatDiagField('买入数量', entry.raw.qty_btc, ' BTC', 8),
                              formatDiagField('持仓批次', entry.raw.open_lots, '', 0),
                              entry.raw.broker_reason
                                ? { label: '原因', value: String(entry.raw.broker_reason) }
                                : null,
                              entry.raw.broker_error
                                ? { label: '错误', value: String(entry.raw.broker_error) }
                                : null,
                              entry.raw.need_1m_bars
                                ? { label: '需要K线', value: `${String(entry.raw.need_1m_bars)} 根` }
                                : null,
                              entry.raw.bars_since_last_entry != null
                                ? { label: '距上次', value: `${String(entry.raw.bars_since_last_entry)} 根` }
                                : null,
                            ]
                              .filter(Boolean)
                              .map((item) => {
                                const field = item as { label: string; value: string };
                                if (!field.value) return null;
                                return (
                                  <span
                                    key={`${field.label}-${field.value}`}
                                    className="rounded-md border border-crypto-border bg-crypto-card px-2 py-1 text-gray-400"
                                  >
                                    <span className="text-gray-600">{field.label}</span>{' '}
                                    <span className="text-gray-300">{field.value}</span>
                                  </span>
                                );
                              })}
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-5">
        <DynamicPoolPanel pool={dashboard?.dynamicPool ?? null} />
        <section className="min-h-0 overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
          <button
            type="button"
            aria-expanded={positionsSectionOpen}
            onClick={() => setPositionsSectionOpen((value) => !value)}
            className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors hover:bg-white/[0.03]"
          >
            <span className="flex min-w-0 items-center gap-2">
              <Wallet className="h-4 w-4 shrink-0 text-amber-400" />
              <h3 className="truncate text-base font-semibold text-white">当前持仓</h3>
            </span>
            <span className="flex shrink-0 items-center gap-3">
              <span className="rounded-full border border-crypto-border bg-crypto-bg px-2.5 py-1 text-[11px] font-semibold text-gray-400">
                {positions.length} 个持仓
              </span>
              <ChevronDown
                className={clsx(
                  'h-4 w-4 text-gray-500 transition-transform',
                  positionsSectionOpen && 'rotate-180 text-gray-300',
                )}
              />
            </span>
          </button>
          {positionsSectionOpen && (
            <div className="border-t border-crypto-border px-4 py-4">
              <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-xs text-gray-500">未实现盈亏（汇总）</span>
                <span
                  className={clsx(
                    'text-sm font-bold tabular-nums',
                    unrealizedTotal >= 0 ? 'text-up' : 'text-down',
                  )}
                >
                  {unrealizedTotal >= 0 ? '+' : ''}
                  {typeof unrealizedTotal === 'number' ? unrealizedTotal.toFixed(2) : String(unrealizedTotal)} CNY
                </span>
              </div>
              {positions.length === 0 ? (
                <div className="text-center text-gray-500 text-xs py-10 border border-dashed border-crypto-border rounded-lg bg-crypto-bg/50">
                  当前无持仓
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[880px] text-xs text-left">
              <thead>
                <tr className="text-gray-500 border-b border-crypto-border">
                  <th className="py-2 pr-2 font-medium text-left">{runningDryRun ? 'A 股标的' : '交易对'}</th>
                  <th className="py-2 pr-2 font-medium text-center">方向</th>
                  <th className="py-2 pr-2 font-medium text-right">{positionQuantityLabel}</th>
                  {hasContractPositions && (
                    <th className="py-2 pr-2 font-medium text-right">每张数量</th>
                  )}
                  <th className="py-2 pr-2 font-medium text-right">
                    {hasContractPositions ? '持仓名义' : runningDryRun ? '持仓市值（CNY）' : '持仓金额'}
                  </th>
                  <th className="py-2 pr-2 font-medium text-right">持仓均价</th>
                  <th className="py-2 pr-2 font-medium text-right">{runningDryRun ? '最新价' : '标记价'}</th>
                  <th className="py-2 pr-2 font-medium text-right">浮动盈亏</th>
                  {!runningDryRun && <th className="py-2 font-medium text-right">操作</th>}
                </tr>
              </thead>
              <tbody>
                {positions.map((row, idx) => {
                  const positionPriceDigits = getPositionPriceDigits(row.entryPrice, row.markPrice);
                  const positionNotional = getPositionNotionalUsdt(row);
                  const positionContractUnitSize = getPositionContractUnitSize(row);
                  const sideDisplay = getPositionSideDisplay(row.side);
                  const closeSide = String((row as Record<string, unknown>).posSide ?? row.side ?? '').trim().toLowerCase() || null;
                  return (
                    <tr key={`${row.symbol}-${idx}`} className="border-b border-crypto-border/60 text-gray-200">
                      <td className="py-2 pr-2 font-mono">
                        <div className="inline-flex items-center gap-2">
                          <button
                            type="button"
                            aria-label={`查看 ${row.symbol} ${POSITION_PREVIEW_TIMEFRAME_LABEL} 行情`}
                            onMouseEnter={(event) => openPositionPreview(row.symbol, event.currentTarget)}
                            onMouseLeave={closeTemporaryPositionPreview}
                            onClick={(event) => togglePinnedPositionPreview(row.symbol, event.currentTarget, event)}
                            onFocus={(event) => openPositionPreview(row.symbol, event.currentTarget)}
                            onBlur={closeTemporaryPositionPreview}
                            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-blue-500/35 bg-blue-500/10 text-blue-300 transition-colors hover:border-blue-400/70 hover:bg-blue-500/20 hover:text-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
                          >
                            <TrendingUp className="h-3.5 w-3.5" />
                          </button>
                          <SymbolIcon symbol={row.symbol} size="xs" />
                          <span>{row.symbol}</span>
                        </div>
                      </td>
                      <td className={clsx('py-2 pr-2 text-center font-semibold', sideDisplay.className)}>{sideDisplay.label}</td>
                      <td className="py-2 pr-2 text-right tabular-nums">{row.size?.toFixed?.(6) ?? row.size}</td>
                      {hasContractPositions && (
                        <td className="py-2 pr-2 text-right tabular-nums text-gray-300">
                          {formatContractUnitSize(positionContractUnitSize)}
                        </td>
                      )}
                      <td className="py-2 pr-2 text-right tabular-nums">
                        {positionNotional != null ? positionNotional.toFixed(2) : '—'}
                      </td>
                      <td className="py-2 pr-2 text-right tabular-nums">
                        {formatPositionPrice(row.entryPrice, positionPriceDigits)}
                      </td>
                      <td className="py-2 pr-2 text-right tabular-nums">
                        {formatPositionPrice(row.markPrice, positionPriceDigits)}
                      </td>
                      <td
                        className={clsx(
                          'py-2 pr-2 text-right font-medium tabular-nums',
                          (row.unrealizedPnl ?? 0) >= 0 ? 'text-up' : 'text-down',
                        )}
                      >
                        {(row.unrealizedPnl ?? 0) >= 0 ? '+' : ''}
                        {Number(row.unrealizedPnl ?? 0).toFixed(2)}
                      </td>
                      {!runningDryRun && <td className="py-2 text-right">
                        <button
                          type="button"
                          aria-label={`平仓 ${row.symbol}`}
                          disabled={readOnly || !onClosePosition || closePositionBusy}
                          onClick={() => {
                            setClosePositionError(null);
                            setClosePositionTarget({
                              symbol: String(row.symbol),
                              side: closeSide,
                              marketType: isContractPosition(row) ? 'swap' : 'spot',
                            });
                          }}
                          className="inline-flex h-7 items-center gap-1.5 rounded-md border border-cyan-500/35 bg-cyan-500/10 px-2.5 text-[11px] font-semibold text-cyan-200 transition-colors hover:border-cyan-400/70 hover:bg-cyan-500/20 hover:text-cyan-50 disabled:cursor-not-allowed disabled:opacity-45"
                        >
                          <XCircle className="h-3.5 w-3.5" />
                          平仓
                        </button>
                      </td>}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
              )}
            </div>
          )}
        </section>

        {positionPreviewAnchor && (
          <div
            className={clsx(
              'fixed z-[80] w-[420px] max-w-[calc(100vw-24px)]',
              positionPreviewAnchor.pinned ? 'pointer-events-auto' : 'pointer-events-none',
            )}
            style={{ left: positionPreviewAnchor.left, top: positionPreviewAnchor.top }}
          >
            <PositionMarketPreview
              symbol={positionPreviewAnchor.symbol}
              pinned={positionPreviewAnchor.pinned}
              onClose={closePinnedPositionPreview}
              state={
                positionPreviewCache[
                  positionPreviewKey(previewExchange, positionPreviewAnchor.symbol)
                ]
              }
            />
          </div>
        )}

        <section className="min-h-0 overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
          <div
            role="button"
            tabIndex={0}
            aria-expanded={activitySectionOpen}
            onClick={toggleActivitySection}
            onKeyDown={handleActivitySectionKeyDown}
            className="flex cursor-pointer flex-col gap-3 border-b border-crypto-border px-4 py-3 text-left transition-colors hover:bg-white/[0.03] focus:outline-none focus:ring-2 focus:ring-blue-500/30 sm:flex-row sm:items-center"
          >
            <span className="flex min-w-0 items-center gap-2">
              <List className="h-4 w-4 shrink-0 text-blue-400" />
              <span className="truncate text-base font-semibold text-white">成交与事件</span>
              <ChevronDown
                className={clsx(
                  'h-4 w-4 shrink-0 text-gray-500 transition-transform',
                  activitySectionOpen && 'rotate-180 text-gray-300',
                )}
              />
            </span>
            <div
              className="flex flex-wrap gap-2 sm:ml-auto"
              onClick={(event) => event.stopPropagation()}
              onKeyDown={(event) => event.stopPropagation()}
            >
              <button
                type="button"
                aria-pressed={logTab === 'trades'}
                onClick={() => setLogTab('trades')}
                className={clsx(
                  'px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors',
                  logTab === 'trades'
                    ? SELECTED_SEGMENT_CLASS
                    : 'text-gray-400 border border-transparent hover:text-white',
                )}
              >
                成交明细
                <span className="ml-1 font-normal opacity-70">({trades.length})</span>
              </button>
              <button
                type="button"
                aria-pressed={logTab === 'events'}
                onClick={() => setLogTab('events')}
                className={clsx(
                  'px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors',
                  logTab === 'events'
                    ? SELECTED_SEGMENT_CLASS
                    : 'text-gray-400 border border-transparent hover:text-white',
                )}
              >
                系统事件
                <span className="ml-1 font-normal opacity-70">({events.length})</span>
              </button>
            </div>
          </div>

          {activitySectionOpen && (
            <div className="px-4 py-4">
              {logTab === 'trades' ? (
                <div className={clsx('-mr-1 min-h-0 overflow-auto pr-1', ACTIVITY_PANEL_MAX_HEIGHT_CLASS)}>
                  {trades.length === 0 ? (
                    <div className="text-center text-gray-500 text-xs py-12">暂无成交记录</div>
                  ) : (
                    <table className="w-full text-xs text-left min-w-[820px]">
                  <thead className="sticky top-0 bg-crypto-card z-[1] shadow-[0_1px_0_#333]">
                    <tr className="text-gray-500">
                      <th className="py-2 pr-2 font-medium text-left">时间</th>
                      <th className="py-2 pr-2 font-medium text-center">方向</th>
                      <th className="py-2 pr-2 font-medium text-left">{runningDryRun ? 'A 股标的' : '交易对'}</th>
                      <th className="py-2 pr-2 font-medium text-right">价格</th>
                      <th className="py-2 pr-2 font-medium text-right">{tradeQuantityLabel}</th>
                      {hasContractTrades && (
                        <th className="py-2 pr-2 font-medium text-right">每张数量</th>
                      )}
                      {!runningDryRun && <th className="py-2 pr-2 font-medium text-center">杠杆</th>}
                      <th className="py-2 pr-2 font-medium text-right">
                        {hasContractTrades ? '成交名义' : runningDryRun ? '成交金额（CNY）' : '交易金额'}
                      </th>
                      {hasContractTrades && (
                        <th className="py-2 pr-2 font-medium text-right">保证金</th>
                      )}
                      <th className="py-2 pr-2 font-medium text-right">手续费</th>
                      <th className="py-2 font-medium text-right">盈亏</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t: any, i: number) => {
                      const sideDisplay = getTradeSideDisplay(t.side);
                      const tradeNotional = getTradeNotionalUsdt(t);
                      const tradeLeverage = getTradeLeverage(t);
                      const tradeMargin = getTradeMarginUsdt(t);
                      const tradeContractUnitSize = getTradeContractUnitSize(t);
                      const realizedPnl = getRealizedTradePnl(t);
                      return (
                        <tr key={t.id ?? i} className="border-b border-crypto-border/60 text-gray-200">
                          <td className="py-2 pr-2 whitespace-nowrap text-[10px] text-gray-400">
                            {formatTradeTime(t.timestamp)}
                          </td>
                          <td className={clsx('py-2 pr-2 text-center font-semibold', sideDisplay.className)}>{sideDisplay.label}</td>
                          <td className="py-2 pr-2 font-mono">
                            {t.symbol ? (
                              <span className="inline-flex items-center gap-2">
                                <SymbolIcon symbol={String(t.symbol)} size="xs" />
                                <span>{t.symbol}</span>
                              </span>
                            ) : '—'}
                          </td>
                          <td className="py-2 pr-2 text-right tabular-nums">
                            {t.price != null ? Number(t.price).toLocaleString() : '—'}
                          </td>
                          <td className="py-2 pr-2 text-right tabular-nums">
                            {t.quantity != null ? Number(t.quantity).toFixed(runningDryRun ? 0 : 6) : '—'}
                          </td>
                          {hasContractTrades && (
                            <td className="py-2 pr-2 text-right tabular-nums text-gray-300">
                              {formatContractUnitSize(tradeContractUnitSize)}
                            </td>
                          )}
                          {!runningDryRun && <td className="py-2 pr-2 text-center tabular-nums text-gray-300">
                            {formatLeverage(tradeLeverage)}
                          </td>}
                          <td className="py-2 pr-2 text-right tabular-nums">
                            {tradeNotional != null ? tradeNotional.toFixed(2) : '—'}
                          </td>
                          {hasContractTrades && (
                            <td className="py-2 pr-2 text-right tabular-nums">
                              {tradeMargin != null ? tradeMargin.toFixed(2) : '—'}
                            </td>
                          )}
                          <td className="py-2 pr-2 text-right tabular-nums text-gray-400">
                            {t.fee != null ? Number(t.fee).toFixed(4) : '—'}
                          </td>
                          <td
                            className={clsx(
                              'py-2 text-right font-medium tabular-nums',
                              realizedPnl == null || !Number.isFinite(realizedPnl)
                                ? 'text-gray-500'
                                : realizedPnl >= 0
                                  ? 'text-up'
                                  : 'text-down',
                            )}
                          >
                            {realizedPnl == null || !Number.isFinite(realizedPnl)
                              ? '—'
                              : `${realizedPnl >= 0 ? '+' : ''}${realizedPnl.toFixed(2)}`}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                  )}
                </div>
              ) : (
                <div className={clsx('min-h-0 space-y-2 overflow-y-auto pr-1', ACTIVITY_PANEL_MAX_HEIGHT_CLASS)}>
              {events.length === 0 && (
                <div className="text-center text-gray-500 text-xs py-12">暂无系统事件</div>
              )}
              {events.map((evt, i) => {
                const details = evt.details || {};
                const msg = eventTitle(evt);
                const reason = eventReason(evt);
                const price = details.price;
                return (
                  <div key={i} className="flex items-start gap-2 p-2 rounded-lg bg-crypto-bg">
                    {getEventIcon(String(evt.type || ''))}
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-white truncate">
                        {msg}
                        {price ? ` @ $${Number(price).toLocaleString()}` : ''}
                      </div>
                      {reason && (
                        <div className="text-[10px] text-gray-500 truncate mt-0.5">{reason}</div>
                      )}
                      <div className="text-[10px] text-gray-600 mt-0.5">{formatEventTime(evt)}</div>
                    </div>
                  </div>
                );
              })}
                </div>
              )}
            </div>
          )}
        </section>
      </div>

      {simulationReviewEnabled && (
        <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card shadow-lg shadow-black/20">
          <button
            type="button"
            aria-expanded={simulationReviewSectionOpen}
            onClick={() => setSimulationReviewSectionOpen((value) => !value)}
            className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left transition-colors hover:bg-white/[0.03]"
          >
            <span className="flex min-w-0 items-start gap-3">
              <Activity className="mt-0.5 h-5 w-5 shrink-0 text-blue-400" />
              <span className="min-w-0">
                <span className="block truncate text-base font-semibold text-white">买卖点 K线复盘</span>
                <span className="mt-1 block text-xs text-gray-500">
                  使用策略真实成交记录叠加 B/S 成交点，K 线按策略周期读取真实行情。
                </span>
              </span>
            </span>
            <span className="flex shrink-0 items-center gap-3">
              {selectedSimulationReviewSymbol && (
                <span
                  aria-label={`复盘标的 ${selectedSimulationReviewSymbol}`}
                  className="hidden max-w-[220px] truncate rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 text-xs font-semibold text-gray-200 sm:inline-flex"
                >
                  {selectedSimulationReviewSymbol}
                </span>
              )}
              <span
                aria-label={`K线周期 ${simulationReviewTimeframeLabel}`}
                className="flex rounded-xl border border-crypto-border bg-crypto-bg p-1"
              >
                <span className={clsx('inline-flex h-8 items-center justify-center rounded-lg px-3 text-xs font-semibold', SELECTED_SEGMENT_CLASS)}>
                  {simulationReviewTimeframeLabel}
                </span>
              </span>
              <ChevronDown
                className={clsx(
                  'h-4 w-4 text-gray-500 transition-transform',
                  simulationReviewSectionOpen && 'rotate-180 text-gray-300',
                )}
              />
            </span>
          </button>
          {simulationReviewSectionOpen && (
            <div className="border-t border-crypto-border px-5 py-4">
              {simulationReviewSymbols.length > 1 && (
                <div className="mb-3 flex justify-end">
                  <CryptoSelect
                    value={selectedSimulationReviewSymbol}
                    onChange={(event) => setSelectedSimulationReviewSymbol(event.target.value)}
                    controlSize="xs"
                    fullWidth={false}
                    wrapperClassName="min-w-[180px]"
                    aria-label="切换模拟盘复盘标的"
                  >
                    {simulationReviewSymbols.map((symbol) => (
                      <option key={symbol} value={symbol}>
                        {symbol}
                      </option>
                    ))}
                  </CryptoSelect>
                </div>
              )}
              {simulationReviewLoading ? (
                <div className="flex h-[360px] items-center justify-center rounded-xl border border-crypto-border bg-crypto-bg/45 text-sm text-gray-500">
                  <Activity className="mr-2 h-4 w-4 animate-pulse text-blue-400" />
                  正在加载模拟盘 K 线...
                </div>
              ) : simulationReviewError ? (
                <div className="flex h-[220px] items-center justify-center rounded-xl border border-red-500/20 bg-red-500/5 px-4 text-center text-sm text-red-300">
                  {simulationReviewError}
                </div>
              ) : simulationReviewKlines.length > 0 && selectedSimulationReviewSymbol ? (
                <Suspense
                  fallback={
                    <div className="flex h-[360px] items-center justify-center rounded-xl border border-crypto-border bg-crypto-bg/45 text-sm text-gray-500">
                      K 线图加载中...
                    </div>
                  }
                >
                  <WatchKlineChart
                    data={simulationReviewKlines}
                    markers={simulationReviewMarkers}
                    symbol={selectedSimulationReviewSymbol}
                    timeframe={simulationReviewTimeframe}
                    height={420}
                  />
                </Suspense>
              ) : (
                <div className="flex h-[220px] items-center justify-center rounded-xl border border-dashed border-crypto-border bg-crypto-bg/40 px-4 text-center text-sm text-gray-500">
                  暂无 K 线复盘数据，策略产生真实成交后会展示 B/S 成交点
                </div>
              )}
            </div>
          )}
        </section>
      )}

      <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card shadow-lg shadow-black/20">
        <button
          type="button"
          aria-expanded={equitySectionOpen}
          onClick={() => setEquitySectionOpen((value) => !value)}
          className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left transition-colors hover:bg-white/[0.03]"
        >
          <span className="flex min-w-0 items-start gap-3">
            <TrendingUp className="mt-0.5 h-5 w-5 shrink-0 text-blue-400" />
            <span className="min-w-0">
              <span className="block truncate text-base font-semibold text-white">收益曲线</span>
              <span className="mt-1 block text-xs text-gray-500">
                按当前时间范围展示策略收益率、收益、胜率和盈亏比采样。
              </span>
            </span>
          </span>
          <ChevronDown
            className={clsx(
              'h-4 w-4 shrink-0 text-gray-500 transition-transform',
              equitySectionOpen && 'rotate-180 text-gray-300',
            )}
          />
        </button>
        {equitySectionOpen && (
          <div className="border-t border-crypto-border px-5 py-4">
            <div className="mb-4 flex flex-wrap items-center justify-end gap-2">
              <div className="flex rounded-xl border border-crypto-border bg-crypto-bg p-1">
                {EQUITY_RANGE_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={equityRange === option.value}
                    onClick={() => setEquityRange(option.value)}
                    className={clsx(
                      'h-8 rounded-lg px-3 text-xs font-semibold transition-colors',
                      equityRange === option.value
                        ? SELECTED_SEGMENT_CLASS
                        : 'text-gray-500 hover:text-gray-200',
                    )}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <div className="flex rounded-xl border border-crypto-border bg-crypto-bg p-1">
                {EQUITY_METRIC_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={equityMetric === option.value}
                    onClick={() => setEquityMetric(option.value)}
                    className={clsx(
                      'h-8 rounded-lg px-3 text-xs font-semibold transition-colors',
                      equityMetric === option.value
                        ? SELECTED_SEGMENT_CLASS
                        : 'text-gray-500 hover:text-gray-200',
                    )}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
            {equityCurve.length > 0 ? (
              <div
                ref={equityChartRef}
                className="h-[38vh] min-h-[280px] w-full max-h-[520px] sm:h-[42vh]"
              />
            ) : (
              <div className="flex h-[38vh] min-h-[280px] max-h-[520px] items-center justify-center rounded-xl border border-dashed border-crypto-border bg-crypto-bg/40 text-sm text-gray-500 sm:h-[42vh]">
                暂无收益曲线数据，策略运行后将自动显示
              </div>
            )}
          </div>
        )}
      </section>

      {risk && (
        <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
          <button
            type="button"
            aria-expanded={riskSectionOpen}
            onClick={() => setRiskSectionOpen((value) => !value)}
            className="flex w-full items-center justify-between gap-4 px-4 py-4 text-left transition-colors hover:bg-white/[0.03]"
          >
            <span className="flex min-w-0 items-center gap-2">
              <ShieldCheck className="h-4 w-4 shrink-0 text-green-400" />
              <span className="truncate text-base font-semibold text-white">风控状态</span>
            </span>
            <span className="flex shrink-0 items-center gap-3">
              <span
                className={clsx(
                  'rounded-full border px-2 py-0.5 text-[11px] font-semibold',
                  risk.circuitBreaker
                    ? 'border-red-500/40 bg-red-500/10 text-red-300'
                    : 'border-green-500/30 bg-green-500/10 text-green-300',
                )}
              >
                {risk.circuitBreaker ? '已触发' : '正常'}
              </span>
              <ChevronDown
                className={clsx(
                  'h-4 w-4 text-gray-500 transition-transform',
                  riskSectionOpen && 'rotate-180 text-gray-300',
                )}
              />
            </span>
          </button>
          {riskSectionOpen && (
            <div className="border-t border-crypto-border p-4 xl:min-h-[264px]">
              <div aria-label="风控说明块" className="grid content-start gap-3 lg:grid-cols-2">
                {riskDescriptionItems.map((item) => (
                  <div
                    key={item.title}
                    className="rounded-lg border border-crypto-border bg-crypto-bg/55 px-3 py-3"
                  >
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <div className="text-sm font-semibold text-gray-100">{item.title}</div>
                      <span
                        className={clsx(
                          'shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-semibold',
                          item.statusClass,
                        )}
                      >
                        {item.status}
                      </span>
                    </div>
                    <p className="text-xs leading-5 text-gray-400">{item.description}</p>
                  </div>
                ))}
                <div className="rounded-lg border border-crypto-border bg-crypto-bg/55 px-3 py-3 lg:col-span-2">
                  <div className="mb-2 flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-gray-100">通知与审计</div>
                      <div
                        className={clsx(
                          'mt-1 inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold',
                          feishuEnabled && feishu?.webhookConfigured
                            ? 'border-green-500/30 bg-green-500/10 text-green-300'
                            : 'border-crypto-border bg-white/[0.03] text-gray-400',
                        )}
                      >
                        {feishuStatusText}
                      </div>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={feishuEnabled}
                      aria-label="飞书推送"
                      disabled={feishuToggling}
                      onClick={handleFeishuToggle}
                      className={clsx(
                        'relative mt-0.5 shrink-0 w-10 h-5 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 disabled:opacity-50',
                        feishuEnabled ? 'bg-blue-500' : 'bg-gray-600',
                      )}
                    >
                      <span
                        className={clsx(
                          'absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform duration-200',
                          feishuEnabled ? 'translate-x-5' : 'translate-x-0',
                        )}
                      />
                    </button>
                  </div>
                  <p className="text-xs leading-5 text-gray-400">
                    风控状态、交易事件和通知开关共同用于运行审计；飞书只负责提醒，不会改变模拟盘策略、仓位或交易行为。
                  </p>
                </div>
              </div>
            </div>
          )}
        </section>
      )}

      <ThemeDialog
        open={closePositionTarget != null}
        variant="confirm"
        title="平仓当前模拟持仓"
        tone="warning"
        confirmText={closePositionBusy ? '平仓中...' : '平仓'}
        cancelText="取消"
        onCancel={() => {
          if (closePositionBusy) return;
          setClosePositionTarget(null);
        }}
        onConfirm={async () => {
          if (!closePositionTarget || closePositionBusy) return;
          setClosePositionBusy(true);
          setClosePositionError(null);
          try {
            await onClosePosition?.({
              symbol: closePositionTarget.symbol,
              side: closePositionTarget.side,
              marketType: closePositionTarget.marketType,
            });
            setClosePositionTarget(null);
          } catch (err: unknown) {
            const error = err as {
              response?: { data?: { detail?: string; error?: { message?: string } } };
              message?: string;
            };
            const message =
              error.response?.data?.detail ||
              error.response?.data?.error?.message ||
              error.message ||
              String(err);
            setClosePositionError(message || '模拟持仓平仓失败');
          } finally {
            setClosePositionBusy(false);
          }
        }}
      >
        <div className="space-y-3 text-sm text-gray-300">
          <p>
            将按当前模拟盘标记价平掉这条持仓，不会触发真实交易所下单，也不会关闭策略任务。
          </p>
          <div className="rounded-xl border border-crypto-border bg-crypto-bg px-3 py-2 font-mono text-xs text-gray-300">
            <div>{closePositionTarget?.symbol || '—'}</div>
            <div className="mt-1 text-gray-500">
              A 股 · {closePositionTarget?.side || 'long'}
            </div>
          </div>
        </div>
      </ThemeDialog>

      <ThemeDialog
        open={closePositionError != null}
        variant="alert"
        title="平仓失败"
        tone="danger"
        content={closePositionError || ''}
        onClose={() => setClosePositionError(null)}
      />
    </div>
  );
}
