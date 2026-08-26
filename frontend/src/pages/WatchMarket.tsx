import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import {
  Clock3,
  Crosshair,
  RefreshCcw,
  ScanLine,
} from 'lucide-react';
import clsx from 'clsx';
import { SELECTED_SEGMENT_CLASS } from '../utils/selectionStyles';
import {
  contractPositionSide,
  isSpotLivePosition,
  LiveContractPositionsPanel,
  LiveOrderDetailsPanel,
  LiveOrderFailureLogDialog,
  positionActionKey,
} from '../components/live/LiveAccountSummaryPanels';
import ThemeDialog from '../components/ThemeDialog';
import { useKlineWebSocket, useTickerWebSocket, useWebSocket } from '../hooks/useWebSocket';
import {
  liveExecutionApi,
  liveWatchApi,
  type LiveExecutionAccount,
  type LiveExecutionOrder,
  type LiveExecutionPosition,
  type WatchMarketPayload,
  type WatchTradeMarker,
  type WatchlistItem,
} from '../api/client';
import type { Kline, Ticker } from '../types';

const WatchKlineChart = lazy(() => import('../components/WatchKlineChart'));

const DEFAULT_TIMEFRAME = '1d';
const TIMEFRAMES = [
  { value: '1d', label: '1D' },
];

function finite(value: unknown, fallback = 0): number {
  const next = Number(value);
  return Number.isFinite(next) ? next : fallback;
}

function compactNumber(value: unknown, digits = 2): string {
  const next = finite(value, Number.NaN);
  if (!Number.isFinite(next)) return '--';
  const abs = Math.abs(next);
  if (abs >= 1e8) return `${(next / 1e8).toFixed(digits)}亿`;
  if (abs >= 1e4) return `${(next / 1e4).toFixed(digits)}万`;
  return next.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function money(value: unknown, digits = 2): string {
  const next = finite(value, Number.NaN);
  if (!Number.isFinite(next)) return '--';
  return `¥${compactNumber(next, digits)}`;
}

function signedMoney(value: unknown, digits = 2): string {
  const next = finite(value, Number.NaN);
  if (!Number.isFinite(next)) return '--';
  const sign = next > 0 ? '+' : next < 0 ? '-' : '';
  return `${sign}¥${compactNumber(Math.abs(next), digits)}`;
}

function pct(value: unknown): string {
  const next = finite(value, Number.NaN);
  if (!Number.isFinite(next)) return '--';
  return `${next >= 0 ? '+' : ''}${next.toFixed(2)}%`;
}

function fmtTime(value?: string | number | null): string {
  if (!value) return '--';
  const date = typeof value === 'number' ? new Date(value) : new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function symbolBase(symbol: string): string {
  return symbol.split('/', 1)[0] || symbol;
}

function normalizeWatchSymbolKey(symbol?: string | null): string {
  const raw = String(symbol || '').trim().toUpperCase();
  if (!raw) return '';
  if (raw.includes('/')) {
    const [base, rest = ''] = raw.split('/');
    const [quote = 'USDT', settle = quote || 'USDT'] = rest.split(':');
    return `${base}/${quote || 'USDT'}:${settle || quote || 'USDT'}`;
  }
  const okxSwap = raw.match(/^(.+)-([A-Z0-9]+)-SWAP$/);
  if (okxSwap) return `${okxSwap[1]}/${okxSwap[2]}:${okxSwap[2]}`;
  return raw.replace(/-/g, '/');
}

function accountExchangeLabel(account?: LiveExecutionAccount | null): string {
  return account?.exchangeAlias || account?.name || 'A股';
}

function marketExchangeForAccount(account?: LiveExecutionAccount | null): 'okx' | 'binanceusdm' {
  return account?.exchange === 'binanceusdm' ? 'binanceusdm' : 'okx';
}

function normalizeKline(row: any): Kline | null {
  if (Array.isArray(row)) {
    const [timestamp, open, high, low, close, volume] = row;
    if (!Number.isFinite(Number(timestamp))) return null;
    return {
      timestamp: Number(timestamp),
      open: finite(open),
      high: finite(high),
      low: finite(low),
      close: finite(close),
      volume: finite(volume),
    };
  }
  if (!row || !Number.isFinite(Number(row.timestamp))) return null;
  return {
    timestamp: Number(row.timestamp),
    open: finite(row.open),
    high: finite(row.high),
    low: finite(row.low),
    close: finite(row.close),
    volume: finite(row.volume),
    quote_volume: row.quoteVolume ?? row.quote_volume,
  };
}

function tickerLast(ticker?: Ticker | null): number | null {
  if (!ticker) return null;
  const value = (ticker as any).last ?? (ticker as any).close;
  const next = finite(value, Number.NaN);
  return Number.isFinite(next) ? next : null;
}

function tickerMark(ticker?: Ticker | null): number | null {
  if (!ticker) return null;
  const value = (ticker as any).markPrice ?? (ticker as any).mark_price;
  const next = finite(value, Number.NaN);
  return Number.isFinite(next) ? next : null;
}

function tickerPct(ticker?: Ticker | null): number | null {
  if (!ticker) return null;
  const value = (ticker as any).changePercent ?? (ticker as any).percentage ?? (ticker as any).change_percent;
  const next = finite(value, Number.NaN);
  return Number.isFinite(next) ? next : null;
}

function tickerDisplayPct(ticker?: Ticker | null): number | null {
  if (!ticker) return null;
  const value = (ticker as any).changePercentToday ?? (ticker as any).change_percent_today ?? tickerPct(ticker);
  const next = finite(value, Number.NaN);
  return Number.isFinite(next) ? next : null;
}

function positionMarginValue(position: LiveExecutionPosition): number {
  return finite(position.initialMargin ?? position.margin ?? position.used, 0);
}

function WatchHeaderMetric({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: string | number;
  tone?: 'neutral' | 'blue' | 'green' | 'red';
}) {
  return (
    <span
      className={clsx(
        'inline-flex h-6 items-center gap-1 rounded-md border px-2 text-[11px] font-semibold tabular-nums',
        tone === 'blue' && 'border-blue-500/30 bg-blue-500/10 text-blue-200',
        tone === 'green' && 'border-green-500/30 bg-green-500/10 text-green-200',
        tone === 'red' && 'border-red-500/30 bg-red-500/10 text-red-200',
        tone === 'neutral' && 'border-crypto-border bg-white/[0.03] text-gray-300',
      )}
    >
      <span className="font-normal text-gray-500">{label}</span>
      {value}
    </span>
  );
}

function mergeKline(rows: Kline[], update: any): Kline[] {
  const next = normalizeKline(update);
  if (!next) return rows;
  const merged = [...rows];
  const lastIndex = merged.findIndex((row) => row.timestamp === next.timestamp);
  if (lastIndex >= 0) {
    merged[lastIndex] = next;
  } else {
    merged.push(next);
  }
  return merged.sort((a, b) => a.timestamp - b.timestamp).slice(-180);
}

function patchLatestKlineWithPrice(rows: Kline[], price: number | null): Kline[] {
  if (!rows.length || price == null || !Number.isFinite(price)) return rows;
  const latest = rows[rows.length - 1];
  const currentClose = finite(latest.close, Number.NaN);
  const currentHigh = finite(latest.high, price);
  const currentLow = finite(latest.low, price);
  if (currentClose === price && currentHigh >= price && currentLow <= price) return rows;
  const next = [...rows];
  next[next.length - 1] = {
    ...latest,
    close: price,
    high: Math.max(currentHigh, price),
    low: Math.min(currentLow, price),
  };
  return next;
}

function LivePositionCloseConfirm({
  position,
  closeAll,
  submitting,
  accountLabel,
  exchangeLabel,
  onCancel,
  onConfirm,
}: {
  position: LiveExecutionPosition;
  closeAll: boolean;
  submitting: boolean;
  accountLabel: string;
  exchangeLabel: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const symbol = position.symbol || '--';
  const side = contractPositionSide(position);
  const sideLabel = side === 'short' ? '空' : side === 'long' ? '多' : '当前方向';
  return (
    <ThemeDialog
      open
      variant="confirm"
      tone="danger"
      title={closeAll ? '确认市价全平' : '确认平仓'}
      confirmText={submitting ? '提交中...' : closeAll ? '市价全平' : '确认平仓'}
      cancelText="取消"
      onCancel={onCancel}
      onConfirm={onConfirm}
    >
      <div className="space-y-3 text-sm text-gray-300">
        <p>
          将对实盘账户 <span className="font-mono text-gray-100">{accountLabel} · {exchangeLabel}</span> 提交真实市价减仓指令。
        </p>
        <div className="rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 text-xs">
          <div className="flex items-center justify-between gap-3">
            <span className="text-gray-500">合约</span>
            <span className="font-mono font-semibold text-gray-100">{symbol}</span>
          </div>
          <div className="mt-1 flex items-center justify-between gap-3">
            <span className="text-gray-500">范围</span>
            <span className="font-semibold text-red-200">{closeAll ? '该合约全部方向' : `${sideLabel}仓`}</span>
          </div>
        </div>
        <p className="text-xs leading-5 text-red-200">
          这是实盘操作，请确认当前仓位、方向和账户无误后再继续。
        </p>
      </div>
    </ThemeDialog>
  );
}

function WatchSymbolTile({
  item,
  timeframe,
  accountId,
  marketExchange,
  exchangeLabel,
}: {
  item: WatchlistItem;
  timeframe: string;
  accountId: string;
  marketExchange: 'okx' | 'binanceusdm';
  exchangeLabel: string;
}) {
  const symbol = item.symbol;
  const [market, setMarket] = useState<WatchMarketPayload | null>(null);
  const [klines, setKlines] = useState<Kline[]>([]);
  const [markers, setMarkers] = useState<WatchTradeMarker[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [lastLoadedAt, setLastLoadedAt] = useState<Date | null>(null);

  const { ticker: wsTicker, isConnected } = useTickerWebSocket(marketExchange, symbol, false);
  const { kline: wsKline } = useKlineWebSocket(marketExchange, symbol, timeframe, false);

  const loadMarket = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    setError('');
    try {
      const [marketRes, markerRes] = await Promise.all([
        liveWatchApi.getWatchMarket(symbol, accountId, timeframe, 180),
        liveWatchApi.getTradeMarkers(symbol, accountId, { limit: 400 }),
      ]);
      setMarket(marketRes);
      setKlines((marketRes.klines || []).map(normalizeKline).filter(Boolean) as Kline[]);
      setMarkers(markerRes.markers || []);
      setLastLoadedAt(new Date());
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || '读取盯盘行情失败');
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [accountId, symbol, timeframe]);

  useEffect(() => {
    loadMarket().catch(() => undefined);
  }, [loadMarket]);

  useEffect(() => {
    if (wsKline) setKlines((current) => mergeKline(current, wsKline));
  }, [wsKline]);

  const ticker = useMemo(() => {
    if (!market?.ticker) return wsTicker as Ticker | null;
    return wsTicker ? ({ ...market.ticker, ...wsTicker } as Ticker) : market.ticker;
  }, [market?.ticker, wsTicker]);

  const base = symbolBase(symbol);
  const last = tickerLast(ticker);
  const mark = tickerMark(ticker);
  const displayPrice = mark ?? last;
  const change = tickerDisplayPct(ticker);

  useEffect(() => {
    setKlines((current) => patchLatestKlineWithPrice(current, displayPrice));
  }, [displayPrice]);

  return (
    <section className="watchTileCard min-w-0 overflow-hidden rounded-lg border border-crypto-border bg-[#05070b] shadow-[0_8px_22px_rgba(0,0,0,0.24)] ring-1 ring-white/[0.02]">
      <div className="watchTileBody space-y-2.5 p-3">
        {error && (
          <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
            {error}
          </div>
        )}
        <div className="watchTileChartShell">
          <Suspense fallback={<div className="flex h-[460px] items-center justify-center text-sm text-gray-500">K 线图加载中...</div>}>
            <WatchKlineChart
              data={klines}
              markers={markers}
              symbol={symbol}
              timeframe={timeframe}
              livePrice={displayPrice}
              height={460}
              compact
              header={
              <div className="watchTileChartSummary mb-2 rounded-md border border-white/[0.06] bg-black/35 px-2 py-1.5">
                <div className="watchTileTitleRow mb-1.5 flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate text-base font-black leading-5 tracking-normal text-white">{base}USDT</span>
                      <span className="rounded bg-yellow-500/15 px-1.5 py-0.5 text-[10px] font-semibold leading-4 text-yellow-300">永续</span>
                      <span className={clsx('h-1.5 w-1.5 rounded-full', isConnected ? 'bg-green-400' : 'bg-gray-500')} />
                    </div>
                    <div className="mt-0.5 truncate text-[10px] leading-4 text-gray-500">{exchangeLabel} · {symbol} · {timeframe.toUpperCase()}</div>
                  </div>
                  <button
                    onClick={() => {
                      loadMarket(true).catch(() => undefined);
                    }}
                    className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-crypto-border bg-gray-900/80 text-gray-400 hover:border-blue-500/50 hover:text-blue-200"
                    aria-label={`刷新 ${symbol}`}
                  >
                    <RefreshCcw size={13} className={loading ? 'animate-spin' : ''} />
                  </button>
                </div>
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-[11px] leading-4 text-gray-500">{item.sourceStrategyName}</div>
                    <div className="mt-0.5 flex min-w-0 items-baseline gap-2">
                      <span className={clsx('truncate text-[28px] font-black leading-none tabular-nums tracking-normal', (change || 0) >= 0 ? 'text-up' : 'text-down')}>
                        {displayPrice != null ? compactNumber(displayPrice, 5) : '--'}
                      </span>
                      <span className={clsx('shrink-0 text-[11px] font-semibold tabular-nums', (change || 0) >= 0 ? 'text-up' : 'text-down')}>
                        {pct(change)}
                      </span>
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] leading-4">
                      <span className="text-gray-300">标记价 {money(displayPrice, 4)}</span>
                      <span className="text-gray-500">最新成交 {compactNumber(last, 4)}</span>
                    </div>
                  </div>
                  <div className="watchTileChartStats grid w-[96px] gap-1.5 text-right">
                    <div className="rounded-md border border-blue-400/25 bg-blue-500/[0.08] px-2 py-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
                      <div className="font-mono text-lg font-black leading-5 text-blue-200">{item.orderCount}</div>
                      <div className="text-[10px] font-semibold leading-4 text-blue-300/70">订单</div>
                    </div>
                    <div className="rounded-md border border-cyan-400/20 bg-cyan-500/[0.06] px-2 py-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
                      <div className="whitespace-nowrap font-mono text-[13px] font-bold leading-5 text-cyan-100">{fmtTime(item.lastExecutionAt)}</div>
                      <div className="text-[10px] font-semibold leading-4 text-cyan-200/65">最近</div>
                    </div>
                  </div>
                </div>
                <div className="mt-1.5 flex flex-wrap items-center justify-between gap-x-2 gap-y-1 text-[10px] leading-4 text-gray-500">
                  <span>EMA5 / EMA10 / EMA20 · VOL · MACD · {timeframe}</span>
                  <span className="inline-flex items-center gap-2">
                    <span className="inline-flex items-center gap-1">
                      <span className="h-2 w-2 rounded-sm bg-red-500" />
                      买入
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <span className="h-2 w-2 rounded-sm bg-green-500" />
                      卖出
                    </span>
                  </span>
                </div>
                <div className="mt-1 flex items-center justify-between gap-2 text-[10px] leading-4 text-gray-500">
                  <span className="inline-flex min-w-0 items-center gap-1">
                    <Clock3 size={11} />
                    {lastLoadedAt ? fmtTime(lastLoadedAt.getTime()) : '--'}
                  </span>
                  <span className="inline-flex shrink-0 items-center gap-1">
                    <Crosshair size={11} />
                    {markers.length} 个成交点
                  </span>
                </div>
              </div>
              }
            />
          </Suspense>
        </div>
      </div>
    </section>
  );
}

export default function WatchMarket() {
  const [accounts, setAccounts] = useState<LiveExecutionAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState('default');
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [positions, setPositions] = useState<LiveExecutionPosition[]>([]);
  const [historyOrders, setHistoryOrders] = useState<LiveExecutionOrder[]>([]);
  const [orderLog, setOrderLog] = useState<LiveExecutionOrder | null>(null);
  const [timeframe, setTimeframe] = useState(DEFAULT_TIMEFRAME);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [accountPanelError, setAccountPanelError] = useState('');
  const [closeConfirm, setCloseConfirm] = useState<{ position: LiveExecutionPosition; closeAll: boolean } | null>(null);
  const [positionClosingKey, setPositionClosingKey] = useState<string | null>(null);

  const selectedAccount = useMemo(
    () => accounts.find((account) => account.accountId === selectedAccountId) || accounts[0] || null,
    [accounts, selectedAccountId],
  );
  const marketExchange = marketExchangeForAccount(selectedAccount);
  const selectedAccountExchangeLabel = accountExchangeLabel(selectedAccount);
  const selectedAccountLabel = selectedAccount?.name || selectedAccountId;

  const loadAccounts = useCallback(async () => {
    try {
      const result = await liveExecutionApi.listAccounts();
      const nextAccounts = result.accounts || [];
      setAccounts(nextAccounts);
      setSelectedAccountId((current) => (
        nextAccounts.some((account) => account.accountId === current)
          ? current
          : nextAccounts[0]?.accountId || 'default'
      ));
    } catch (err: any) {
      setAccountPanelError(err?.response?.data?.detail || err?.message || '读取实盘账户列表失败');
    }
  }, []);

  const loadWatchlist = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await liveWatchApi.getWatchlist(selectedAccountId);
      setWatchlist(res.items || []);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || '读取盯盘标的失败');
    } finally {
      setLoading(false);
    }
  }, [selectedAccountId]);

  const loadLiveAccountPanels = useCallback(async () => {
    setAccountPanelError('');
    try {
      const [positionsRes, historyRes] = await Promise.all([
        liveExecutionApi.listPositions(selectedAccountId),
        liveExecutionApi.listOrderHistory(selectedAccountId, undefined, 100),
      ]);
      setPositions(positionsRes.positions || []);
      setHistoryOrders(historyRes.orders || []);
    } catch (err: any) {
      setAccountPanelError(err?.response?.data?.detail || err?.message || '读取实盘账户明细失败');
    }
  }, [selectedAccountId]);

  const { isConnected: orderBridgeConnected, subscribe, unsubscribe } = useWebSocket({
    enabled: false,
    onMessage: (message) => {
      if (
        message.channel === 'live_order'
        && message.exchange === marketExchange
        && message.symbol === selectedAccountId
      ) {
        loadWatchlist().catch(() => undefined);
        loadLiveAccountPanels().catch(() => undefined);
      }
    },
  });

  useEffect(() => {
    loadAccounts().catch(() => undefined);
  }, [loadAccounts]);

  useEffect(() => {
    setWatchlist([]);
    setPositions([]);
    setHistoryOrders([]);
    setError('');
    setAccountPanelError('');
  }, [selectedAccountId]);

  useEffect(() => {
    loadWatchlist().catch(() => undefined);
    loadLiveAccountPanels().catch(() => undefined);
    const id = window.setInterval(() => {
      loadWatchlist().catch(() => undefined);
      loadLiveAccountPanels().catch(() => undefined);
    }, 10_000);
    return () => window.clearInterval(id);
  }, [loadLiveAccountPanels, loadWatchlist]);

  useEffect(() => {
    if (!orderBridgeConnected) return undefined;
    subscribe('live_order', marketExchange, selectedAccountId);
    return () => unsubscribe('live_order', marketExchange, selectedAccountId);
  }, [marketExchange, orderBridgeConnected, selectedAccountId, subscribe, unsubscribe]);

  const contractPositions = useMemo(
    () => positions.filter((position) => !isSpotLivePosition(position)),
    [positions],
  );
  const orderedContractPositions = useMemo(() => {
    const watchlistOrder = new Map(
      watchlist.map((item, index) => [normalizeWatchSymbolKey(item.symbol), index])
    );
    return [...contractPositions].sort((left, right) => {
      const leftOrder = watchlistOrder.get(normalizeWatchSymbolKey(left.symbol)) ?? Number.MAX_SAFE_INTEGER;
      const rightOrder = watchlistOrder.get(normalizeWatchSymbolKey(right.symbol)) ?? Number.MAX_SAFE_INTEGER;
      if (leftOrder !== rightOrder) return leftOrder - rightOrder;
      return normalizeWatchSymbolKey(left.symbol).localeCompare(normalizeWatchSymbolKey(right.symbol));
    });
  }, [contractPositions, watchlist]);

  const contractPositionStats = useMemo(() => {
    const margin = orderedContractPositions.reduce((sum, position) => sum + positionMarginValue(position), 0);
    const pnl = orderedContractPositions.reduce((sum, position) => sum + finite(position.unrealizedPnl, 0), 0);
    return { count: orderedContractPositions.length, margin, pnl };
  }, [orderedContractPositions]);

  const watchlistStats = useMemo(() => {
    const orders = watchlist.reduce((sum, item) => sum + finite(item.orderCount, 0), 0);
    const activeTimeframe = TIMEFRAMES.find((tf) => tf.value === timeframe)?.label || timeframe.toUpperCase();
    return { symbols: watchlist.length, orders, activeTimeframe };
  }, [timeframe, watchlist]);

  const openPositionCloseConfirm = useCallback((position: LiveExecutionPosition, closeAll = false) => {
    setCloseConfirm({ position, closeAll });
  }, []);

  const closeContractPosition = useCallback(async () => {
    if (!closeConfirm) return;
    if (positionClosingKey) return;
    const { position, closeAll } = closeConfirm;
    const key = positionActionKey(position, closeAll);
    setPositionClosingKey(key);
    setAccountPanelError('');
    try {
      const side = contractPositionSide(position);
      await liveExecutionApi.closePosition(selectedAccountId, {
        symbol: position.symbol,
        side: closeAll || side === 'unknown' ? undefined : side,
        closeAll,
        confirmLiveRisk: true,
      });
      setCloseConfirm(null);
      await Promise.all([
        loadWatchlist(),
        loadLiveAccountPanels(),
      ]);
    } catch (err: any) {
      setAccountPanelError(err?.response?.data?.detail || err?.message || '平仓提交失败');
    } finally {
      setPositionClosingKey(null);
    }
  }, [closeConfirm, loadLiveAccountPanels, loadWatchlist, positionClosingKey, selectedAccountId]);

  return (
    <div className="flex h-full flex-col overflow-hidden bg-crypto-bg text-gray-100">
      <header className="border-b border-crypto-border px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <ScanLine className="h-6 w-6 text-blue-400" />
              <h1 className="text-2xl font-bold tracking-tight text-white">盯盘</h1>
            </div>
            <p className="mt-1 text-sm text-gray-500">A 股 Paper 持仓、委托、盯盘标的和日线行情统一查看；当前阶段保持只读。</p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <div
              role="tablist"
              aria-label="盯盘账户切换"
              className="grid min-h-10 min-w-[252px] grid-cols-2 rounded-lg border border-crypto-border bg-crypto-card p-1"
            >
              {accounts.map((account) => {
                const active = account.accountId === selectedAccountId;
                return (
                  <button
                    key={account.accountId}
                    role="tab"
                    type="button"
                    aria-selected={account.accountId === selectedAccountId}
                    title={account.name}
                    onClick={() => setSelectedAccountId(account.accountId)}
                    className={clsx(
                      'min-w-0 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors',
                      active
                        ? SELECTED_SEGMENT_CLASS
                        : 'text-gray-400 hover:bg-white/[0.05] hover:text-gray-100',
                    )}
                  >
                    {accountExchangeLabel(account)}
                  </button>
                );
              })}
              {accounts.length === 0 && (
                <span className="col-span-2 inline-flex items-center justify-center px-3 text-xs text-gray-500">
                  暂无 A 股 Paper 账户
                </span>
              )}
            </div>
            <button
              onClick={() => {
                loadWatchlist().catch(() => undefined);
                loadLiveAccountPanels().catch(() => undefined);
              }}
              className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-3 text-sm text-gray-300 hover:border-blue-500/60 hover:text-blue-200"
            >
              <RefreshCcw size={16} className={loading ? 'animate-spin' : ''} />
              刷新
            </button>
          </div>
        </div>

      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-5">
        {error && (
          <div className="mb-4 rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
        )}
        {accountPanelError && (
          <div className="mb-4 rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {accountPanelError}
          </div>
        )}
        <section className="watchWorkspaceLayout flex min-h-0 flex-col gap-4">
          <div className="watchTopPanelGrid grid min-h-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(520px,680px)_minmax(0,1fr)]">
            <LiveContractPositionsPanel
              rows={orderedContractPositions}
              readonly
              title="A 股持仓"
              emptyText="当前 A 股 Paper 账户无持仓"
              headerStats={
                <>
                  <WatchHeaderMetric label="仓位" value={contractPositionStats.count} tone="blue" />
                  <WatchHeaderMetric label="持仓市值" value={money(contractPositionStats.margin)} />
                  <WatchHeaderMetric
                    label="浮盈"
                    value={signedMoney(contractPositionStats.pnl)}
                    tone={contractPositionStats.pnl > 0 ? 'red' : contractPositionStats.pnl < 0 ? 'green' : 'neutral'}
                  />
                </>
              }
              closingKey={positionClosingKey}
              onClosePosition={(position) => openPositionCloseConfirm(position, false)}
              onCloseAll={(position) => openPositionCloseConfirm(position, true)}
            />
            <div className="watchTilesColumn flex h-[min(680px,calc(100vh-180px))] min-h-[560px] min-w-0 flex-col overflow-hidden rounded-xl border border-crypto-border bg-crypto-bg">
              <div className="watchTilesToolbar flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-3 py-2.5">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="text-sm font-semibold text-white">盯盘列表</div>
                    <WatchHeaderMetric label="标的" value={watchlistStats.symbols} tone="blue" />
                    <WatchHeaderMetric label="订单" value={watchlistStats.orders} />
                    <WatchHeaderMetric label="周期" value={watchlistStats.activeTimeframe} />
                  </div>
                  <div className="mt-0.5 text-xs text-gray-500">切换后同步刷新所有可见标的 K 线</div>
                </div>
                <div className="flex bg-crypto-card border border-crypto-border rounded-lg overflow-hidden">
                  {TIMEFRAMES.map((tf) => (
                    <button
                      key={tf.value}
                      type="button"
                      aria-pressed={timeframe === tf.value}
                      onClick={() => setTimeframe(tf.value)}
                      className={clsx(
                        'px-3 py-1.5 text-xs font-medium transition-colors',
                        timeframe === tf.value
                          ? SELECTED_SEGMENT_CLASS
                          : 'text-gray-500 hover:bg-gray-800/60 hover:text-gray-300'
                      )}
                    >
                      {tf.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="watchTilesBody min-h-0 flex-1 overflow-y-auto p-2.5">
                {watchlist.length ? (
                  <div className="watchTilesGrid grid grid-cols-1 gap-3 lg:grid-cols-2">
                    {watchlist.map((item) => (
                      <WatchSymbolTile
                        key={`${selectedAccountId}:${item.symbol}`}
                        item={item}
                        timeframe={timeframe}
                        accountId={selectedAccountId}
                        marketExchange={marketExchange}
                        exchangeLabel={selectedAccountExchangeLabel}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="flex h-full min-h-[360px] items-center justify-center rounded-xl border border-dashed border-crypto-border text-gray-500">
                    当前 A 股 Paper 账户暂无持仓盯盘标的；接通只读持仓适配后将在此沿用 BitPro K 线卡片展示。
                  </div>
                )}
              </div>
            </div>
          </div>
          <div className="watchOrdersWidePanel min-w-0">
            <LiveOrderDetailsPanel orders={historyOrders} maxRows={100} onShowLog={setOrderLog} />
          </div>
        </section>
      </main>
      <LiveOrderFailureLogDialog order={orderLog} onClose={() => setOrderLog(null)} />
      {closeConfirm && (
        <LivePositionCloseConfirm
          position={closeConfirm.position}
          closeAll={closeConfirm.closeAll}
          submitting={positionClosingKey === positionActionKey(closeConfirm.position, closeConfirm.closeAll)}
          accountLabel={selectedAccountLabel}
          exchangeLabel={selectedAccountExchangeLabel}
          onCancel={() => setCloseConfirm(null)}
          onConfirm={closeContractPosition}
        />
      )}
    </div>
  );
}
