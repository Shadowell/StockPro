import { useEffect, useState, useRef, useCallback, lazy, Suspense } from 'react';
import { RefreshCw, TrendingUp } from 'lucide-react';
import clsx from 'clsx';
import { useStore } from '../stores/useStore';
import { marketApi, fundingApi } from '../api/client';
import {
  useTickerWebSocket,
  useKlineWebSocket,
  useOrderbookWebSocket,
  type RealtimeTicker,
} from '../hooks/useWebSocket';
import OrderBookChart from '../components/OrderBookChart';
import SymbolSearch from '../components/SymbolSearch';
import type { FundingRate, Kline, OrderBook } from '../types';
import { formatTimeframeLabel } from '../utils/timeframe';

const KlineChart = lazy(() => import('../components/KlineChart'));

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'];

const REFRESH_INTERVALS: Record<string, number> = {
  '1m': 10_000,
  '5m': 15_000,
  '15m': 30_000,
  '1h': 60_000,
  '4h': 120_000,
  '1d': 300_000,
};

/** 1m：拉取最近 6h（360 根）；默认视口约 2h 实盘（120 根），可左滑看更早 */
const KLINE_LIMIT_1M = 360;
const VISIBLE_1M_REAL_BARS = 120;
const MIN_KLINES_TO_RENDER = 20;
const MARKET_EMA_PERIODS = [5, 10, 20, 30];
const RECENT_TRADES_LIMIT = 24;

type MarketType = 'swap' | 'spot';

type MarketTradeRow = {
  id?: string | number;
  timestamp?: number;
  datetime?: string;
  side?: string;
  price?: number;
  amount?: number;
  cost?: number;
};

type MarketDataCacheEntry = {
  klines?: Kline[];
  marketIndicators?: Record<string, Array<number | null>>;
  marketIndicatorTimestamps?: number[];
  orderbook?: OrderBook | null;
  trades?: MarketTradeRow[];
  lastUpdateMs?: number;
};

function symbolBase(symbol: string): string {
  return String(symbol || '').split('/')[0].replace(/-USDT-SWAP$/i, '').toUpperCase();
}

function symbolForMarketType(symbol: string, marketType: MarketType): string {
  const base = symbolBase(symbol) || 'BTC';
  return marketType === 'swap' ? `${base}/USDT:USDT` : `${base}/USDT`;
}

function marketDataCacheKey(exchange: string, symbol: string, timeframe: string): string {
  return [exchange, symbol, timeframe].join('|');
}

function formatMarketCompact(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(value / 1e4).toFixed(2)}万`;
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function formatFundingRatePct(rate: number | null | undefined): string {
  if (rate == null || !Number.isFinite(rate)) return '—';
  return `${(rate * 100).toFixed(4)}%`;
}

function formatTradeTime(timestamp?: number): string {
  if (!timestamp || !Number.isFinite(timestamp)) return '—';
  return new Date(timestamp).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export function BitProMarketSource() {
  const { selectedExchange, selectedSymbol, setSelectedSymbol } = useStore();
  const [klines, setKlines] = useState<Kline[]>([]);
  const [marketIndicators, setMarketIndicators] = useState<Record<string, Array<number | null>>>({});
  const [marketIndicatorTimestamps, setMarketIndicatorTimestamps] = useState<number[]>([]);
  const [orderbook, setOrderbook] = useState<OrderBook | null>(null);
  const [recentTrades, setRecentTrades] = useState<MarketTradeRow[]>([]);
  const [fundingRate, setFundingRate] = useState<FundingRate | null>(null);
  const [loading, setLoading] = useState(false);
  const [allSymbols, setAllSymbols] = useState<string[]>([]);
  const [marketType, setMarketType] = useState<MarketType>('swap');
  const [timeframe, setTimeframe] = useState('1m');
  const selectedSymbolMatchesMarketType = marketType === 'swap'
    ? selectedSymbol.includes(':') || /-SWAP$/i.test(selectedSymbol)
    : !selectedSymbol.includes(':') && !/-SWAP$/i.test(selectedSymbol);

  const { ticker, isConnected } = useTickerWebSocket(selectedExchange, selectedSymbol);
  const { kline: wsKline } = useKlineWebSocket(selectedExchange, selectedSymbol, timeframe);
  const { orderbook: wsOrderbook } = useOrderbookWebSocket(selectedExchange, selectedSymbol);

  // 价格闪烁动画状态
  const prevPriceRef = useRef<number>(0);
  const [priceFlash, setPriceFlash] = useState<'up' | 'down' | null>(null);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout>>();

  // 刷新按钮旋转动画（1s）
  const [refreshSpin, setRefreshSpin] = useState(false);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout>>();

  // 自动刷新相关
  const intervalRef = useRef<ReturnType<typeof setInterval>>();
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const marketDataRequestSeqRef = useRef(0);
  const marketLoadingRequestSeqRef = useRef(0);
  const marketDataCacheRef = useRef<Map<string, MarketDataCacheEntry>>(new Map());

  useEffect(() => {
    let cancelled = false;
    marketApi.getSymbols(selectedExchange, 'USDT', marketType)
      .then((res) => {
        if (cancelled) return;
        const symbols = res.symbols || [];
        const normalizedSymbol = symbolForMarketType(selectedSymbol, marketType);
        const fallbackSymbol = symbols.find((symbol) => symbolBase(symbol) === symbolBase(selectedSymbol)) || symbols[0];
        const nextSymbol = symbols.includes(normalizedSymbol)
          ? normalizedSymbol
          : (fallbackSymbol || normalizedSymbol);

        setAllSymbols(symbols);
        if (nextSymbol && nextSymbol !== selectedSymbol) {
          setSelectedSymbol(nextSymbol);
        }
      })
      .catch(console.error);
    return () => { cancelled = true; };
  }, [selectedExchange, selectedSymbol, setSelectedSymbol, marketType]);

  const applyMarketDataCacheEntry = useCallback(function applyMarketDataCacheEntry(entry?: MarketDataCacheEntry | null): boolean {
    if (!entry?.klines?.length) return false;
    setKlines(entry.klines);
    setMarketIndicators(entry.marketIndicators || {});
    setMarketIndicatorTimestamps(entry.marketIndicatorTimestamps || []);
    setOrderbook(entry.orderbook || null);
    setRecentTrades(entry.trades || []);
    if (entry.lastUpdateMs) setLastUpdate(new Date(entry.lastUpdateMs));
    return true;
  }, []);

  const updateMarketDataCache = useCallback((cacheKey: string, patch: MarketDataCacheEntry) => {
    const next = {
      ...(marketDataCacheRef.current.get(cacheKey) || {}),
      ...patch,
    };
    marketDataCacheRef.current.set(cacheKey, next);
  }, []);

  const fetchData = useCallback((quiet = false) => {
    if (!selectedSymbol || !selectedSymbolMatchesMarketType) return;

    const requestSeq = ++marketDataRequestSeqRef.current;
    const isStaleMarketDataRequest = () => requestSeq !== marketDataRequestSeqRef.current;
    const cacheKey = marketDataCacheKey(selectedExchange, selectedSymbol, timeframe);
    if (!quiet) {
      setLoading(true);
      marketLoadingRequestSeqRef.current = requestSeq;
    }

    const klineLimit = timeframe === '1m' ? KLINE_LIMIT_1M : 200;
    const klineRequest = marketApi.getKlines(selectedExchange, selectedSymbol, timeframe, klineLimit);
    const indicatorsRequest = marketApi.getTechnicalIndicators(
      selectedExchange,
      selectedSymbol,
      timeframe,
      klineLimit,
      undefined,
      undefined,
      MARKET_EMA_PERIODS
    );
    const orderbookRequest = marketApi.getOrderbook(selectedExchange, selectedSymbol, 20);
    const tradesRequest = marketApi.getTrades(selectedExchange, selectedSymbol, RECENT_TRADES_LIMIT);
    const fundingRequest = marketType === 'swap'
      ? fundingApi.getRate(selectedExchange, selectedSymbol).catch(() => null)
      : Promise.resolve(null);

    klineRequest.then((klinesData) => {
      if (isStaleMarketDataRequest()) return;
      const lastUpdateMs = Date.now();
      setKlines(klinesData);
      setLastUpdate(new Date(lastUpdateMs));
      updateMarketDataCache(cacheKey, {
        klines: klinesData,
        lastUpdateMs,
      });
    })
      .catch((error) => {
        if (!isStaleMarketDataRequest()) console.error(error);
      })
      .finally(() => {
        if (!quiet && marketLoadingRequestSeqRef.current === requestSeq) setLoading(false);
      });

    indicatorsRequest
      .then((indicatorsData) => {
        if (isStaleMarketDataRequest()) return;
        setMarketIndicators(indicatorsData.series || {});
        setMarketIndicatorTimestamps(indicatorsData.timestamps || []);
        updateMarketDataCache(cacheKey, {
          marketIndicators: indicatorsData.series || {},
          marketIndicatorTimestamps: indicatorsData.timestamps || [],
        });
      })
      .catch((error) => {
        if (!isStaleMarketDataRequest()) console.error(error);
      });

    orderbookRequest
      .then((orderbookData) => {
        if (isStaleMarketDataRequest()) return;
        setOrderbook(orderbookData);
        updateMarketDataCache(cacheKey, { orderbook: orderbookData });
      })
      .catch((error) => {
        if (!isStaleMarketDataRequest()) console.error(error);
      });

    tradesRequest
      .then((tradesData) => {
        if (isStaleMarketDataRequest()) return;
        const rows = Array.isArray(tradesData) ? tradesData : [];
        setRecentTrades(rows);
        updateMarketDataCache(cacheKey, { trades: rows });
      })
      .catch((error) => {
        if (!isStaleMarketDataRequest()) console.error(error);
      });

    fundingRequest
      .then((fundingData) => {
        if (isStaleMarketDataRequest()) return;
        setFundingRate(fundingData);
      })
      .catch(() => {
        if (isStaleMarketDataRequest()) return;
        setFundingRate(null);
      });
  }, [selectedExchange, selectedSymbol, selectedSymbolMatchesMarketType, timeframe, marketType, updateMarketDataCache]);


  // 初始加载 & 参数变化时重新拉取
  useEffect(() => {
    if (!selectedSymbol) return;
    const cacheKey = marketDataCacheKey(selectedExchange, selectedSymbol, timeframe);
    const cachedEntry = marketDataCacheRef.current.get(cacheKey);
    if (!applyMarketDataCacheEntry(cachedEntry)) {
      setKlines([]);
      setMarketIndicators({});
      setMarketIndicatorTimestamps([]);
      setOrderbook(null);
      setRecentTrades([]);
      setFundingRate(null);
    }
    fetchData(Boolean(cachedEntry?.klines?.length));
  }, [applyMarketDataCacheEntry, fetchData, selectedExchange, selectedSymbol, timeframe]);

  // K 线 / 订单簿自动轮询
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    const base = REFRESH_INTERVALS[timeframe] || 15_000;
    const pollMs = isConnected ? Math.max(base, 30_000) : base;
    intervalRef.current = setInterval(() => fetchData(true), pollMs);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [fetchData, timeframe, isConnected]);

  // WebSocket kline 增量更新（主驱动）
  useEffect(() => {
    if (!wsKline || !selectedSymbol) return;
    const bar = wsKline as any;
    if (!bar.timestamp) return;
    setKlines((prev) => {
      if (prev.length === 0) return prev;
      const next = [...prev];
      const last = next[next.length - 1];
      const sameTs = last && Number(last.timestamp) === Number(bar.timestamp);
      if (sameTs) {
        const vol = Number(bar.volume ?? 0);
        const cl = Number(bar.close);
        const qv =
          bar.quote_volume != null && Number.isFinite(Number(bar.quote_volume))
            ? Number(bar.quote_volume)
            : cl * vol;
        next[next.length - 1] = {
          ...last,
          open: Number(bar.open),
          high: Number(bar.high),
          low: Number(bar.low),
          close: cl,
          volume: vol,
          quote_volume: qv,
          timestamp: Number(bar.timestamp),
        } as any;
      } else {
        const vol = Number(bar.volume ?? 0);
        const cl = Number(bar.close);
        const qv =
          bar.quote_volume != null && Number.isFinite(Number(bar.quote_volume))
            ? Number(bar.quote_volume)
            : cl * vol;
        next.push({
          open: Number(bar.open),
          high: Number(bar.high),
          low: Number(bar.low),
          close: cl,
          volume: vol,
          quote_volume: qv,
          timestamp: Number(bar.timestamp),
        } as any);
      }
      return next.slice(-(timeframe === '1m' ? KLINE_LIMIT_1M : 200));
    });
    setLastUpdate(new Date());
  }, [wsKline, selectedSymbol, timeframe]);

  // WebSocket orderbook 增量更新（主驱动）
  useEffect(() => {
    if (!wsOrderbook) return;
    setOrderbook(wsOrderbook as any);
    setLastUpdate(new Date());
  }, [wsOrderbook]);

  const handleManualRefresh = () => {
    fetchData(false);
    setRefreshSpin(true);
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    refreshTimerRef.current = setTimeout(() => setRefreshSpin(false), 1000);
  };

  // 实时价格 & OKX App 口径涨跌幅：优先用后端按 OKX sodUtc0 计算的当日涨跌幅。
  const lastKline = klines[klines.length - 1];
  const liveTicker = ticker as RealtimeTicker | null;
  const currentPrice = liveTicker?.last || lastKline?.close || 0;
  const priceChange = liveTicker?.changePercentToday ?? liveTicker?.change_percent_today ?? liveTicker?.changePercent ?? liveTicker?.change_percent ?? 0;
  const high24h = liveTicker?.high;
  const low24h = liveTicker?.low;
  const volume24h = liveTicker?.baseVolume ?? liveTicker?.volume;
  const quoteVolume24h = liveTicker?.quoteVolume ?? liveTicker?.quote_volume;
  const markPrice = liveTicker?.markPrice ?? liveTicker?.mark_price;
  const fundingRateValue = fundingRate?.currentRate;
  const nextFundingLabel = fundingRate?.nextFundingTime
    ? new Date(fundingRate.nextFundingTime).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })
    : null;

  // 价格变化时触发闪烁
  useEffect(() => {
    if (currentPrice <= 0) return;
    const prev = prevPriceRef.current;
    if (prev > 0 && prev !== currentPrice) {
      const direction = currentPrice > prev ? 'up' : 'down';
      setPriceFlash(direction);
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
      flashTimerRef.current = setTimeout(() => setPriceFlash(null), 600);
    }
    prevPriceRef.current = currentPrice;
    return () => { if (flashTimerRef.current) clearTimeout(flashTimerRef.current); };
  }, [currentPrice]);

  const priceFlashClass = priceFlash === 'up'
    ? 'bg-green-500/20 text-green-400'
    : priceFlash === 'down'
      ? 'bg-red-500/20 text-red-400'
      : 'text-white';

  return (
    <div className="h-full overflow-y-auto p-6">
      {/* 顶部工具栏 */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <TrendingUp className="w-6 h-6 text-blue-400" />
          <h1 className="text-2xl font-bold text-white">行情</h1>
        </div>

        {/* 右侧工具区 — 刷新 · 连接状态 */}
        <div className="market-action-strip flex flex-wrap items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card/80 p-1 shadow-sm shadow-black/10">
          {/* 刷新按钮 */}
          <button
            type="button"
            onClick={handleManualRefresh}
            disabled={loading}
            className={clsx(
              'flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium transition-all duration-200',
              'text-gray-400 hover:bg-white/[0.06] hover:text-white',
              loading && 'opacity-50 cursor-not-allowed',
            )}
            title="刷新行情"
          >
            <RefreshCw className={clsx('h-4 w-4 shrink-0', refreshSpin && 'animate-spin')} />
            刷新
          </button>

          {/* 连接状态呼吸灯 */}
          <div
            className={clsx(
              'market-connection-pill flex h-9 items-center gap-2 rounded-lg px-3 text-xs font-medium',
              isConnected ? 'bg-emerald-500/10 text-emerald-300' : 'bg-white/[0.03] text-gray-500'
            )}
          >
            <span className="relative flex h-2 w-2">
              {isConnected && (
                <span className="absolute inset-0 rounded-full bg-[#2ebd85] animate-ping opacity-50" />
              )}
              <span
                className={clsx(
                  'relative inline-flex h-2 w-2 rounded-full',
                  isConnected ? 'bg-[#2ebd85]' : 'bg-gray-500'
                )}
              />
            </span>
            <span>{isConnected ? '实时' : '离线'}</span>
          </div>

        </div>
      </div>

      {loading && klines.length < MIN_KLINES_TO_RENDER ? (
        <div className="flex-1 flex items-center justify-center text-gray-400">
          加载中...
        </div>
      ) : (
        <div className="grid min-h-[720px] grid-cols-1 gap-4 lg:grid-cols-4">
          {/* K线图区域：flex 竖向占满格子高度，否则子元素 height:100% 失效，ECharts 主图会被压成一条 */}
          <div className="lg:col-span-3 bg-crypto-card border border-crypto-border rounded-lg p-4 min-h-0 h-full flex flex-col">
            <div className="mb-2 flex flex-wrap items-center gap-3">
              <div className="market-detail-controls flex min-w-0 flex-wrap items-center gap-3">
                {/* 市场类型 */}
                <div
                  className="market-type-toggle flex overflow-hidden rounded-lg border border-crypto-border bg-crypto-card"
                  data-active-market={marketType === 'swap' ? 'swap' : 'spot'}
                >
                  {([
                    { value: 'swap', label: '合约' },
                    { value: 'spot', label: '现货' },
                  ] as const).map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setMarketType(option.value)}
                      className={clsx(
                        'h-9 px-3 text-xs font-semibold transition-colors',
                        marketType === option.value
                          ? 'bg-blue-600 text-white shadow-sm shadow-blue-900/30'
                          : 'text-gray-500 hover:bg-gray-800/60 hover:text-gray-300'
                      )}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>

                {/* 交易对搜索 */}
                <SymbolSearch
                  value={selectedSymbol}
                  onChange={setSelectedSymbol}
                  allSymbols={allSymbols}
                  marketType={marketType}
                />
              </div>
              <div className="flex min-w-[13rem] flex-1 flex-wrap items-baseline gap-x-3 gap-y-1">
                <div className={clsx(
                  'inline-flex rounded px-2 py-0.5 text-2xl font-bold leading-none tabular-nums transition-all duration-500',
                  priceFlashClass
                )}>
                  ${currentPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
                <span className={clsx('text-sm font-medium tabular-nums', priceChange >= 0 ? 'text-up' : 'text-down')}>
                  {priceChange >= 0 ? '+' : ''}{priceChange.toFixed(2)}%
                </span>
                {lastUpdate && (
                  <span className="text-[10px] text-gray-600 tabular-nums">
                    {lastUpdate.toLocaleTimeString()}
                  </span>
                )}
              </div>
              <div className="market-detail-timeframe-controls ml-auto flex flex-wrap items-center justify-end gap-3">
                {/* 时间周期 */}
                <div className="flex bg-crypto-card border border-crypto-border rounded-lg overflow-hidden">
                  {TIMEFRAMES.map((tf) => (
                    <button
                      key={tf}
                      onClick={() => setTimeframe(tf)}
                      className={clsx(
                        'px-3 py-1.5 text-xs font-medium transition-colors',
                        timeframe === tf
                          ? 'bg-blue-600 text-white'
                          : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800/60'
                      )}
                    >
                      {formatTimeframeLabel(tf)}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex basis-full flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-400">
                <span className="tabular-nums">24h 高 <span className="text-gray-200">{formatMarketCompact(high24h, 4)}</span></span>
                <span className="tabular-nums">24h 低 <span className="text-gray-200">{formatMarketCompact(low24h, 4)}</span></span>
                <span className="tabular-nums">24h 量 <span className="text-gray-200">{formatMarketCompact(volume24h)}</span></span>
                <span className="tabular-nums">24h 额 <span className="text-gray-200">{formatMarketCompact(quoteVolume24h)}</span></span>
                {marketType === 'swap' && (
                  <>
                    <span className="tabular-nums">标记价 <span className="text-gray-200">{formatMarketCompact(markPrice, 4)}</span></span>
                    <span className="tabular-nums">资金费率 <span className={clsx(Number(fundingRateValue || 0) >= 0 ? 'text-up' : 'text-down')}>{formatFundingRatePct(fundingRateValue)}</span></span>
                    {nextFundingLabel && (
                      <span className="tabular-nums">下次结算 <span className="text-gray-200">{nextFundingLabel}</span></span>
                    )}
                  </>
                )}
                <span className="ml-auto tabular-nums">共 {klines.length} 根K线</span>
              </div>
            </div>
            <div className="flex-1 min-h-0 flex flex-col gap-2">
              <div className="flex-1 min-h-[280px] min-w-0">
                {klines.length >= MIN_KLINES_TO_RENDER ? (
                  <Suspense
                    fallback={
                      <div className="flex h-full items-center justify-center text-gray-400">
                        图表加载中...
                      </div>
                    }
                  >
                    <KlineChart
                      data={klines}
                      symbol={selectedSymbol}
                      height="100%"
                      showVolume
                      showEMA
                      showRSI={true}
                      showMACD={true}
                      emaPeriods={MARKET_EMA_PERIODS}
                      indicatorSeries={marketIndicators}
                      indicatorTimestamps={marketIndicatorTimestamps}
                      showRealCandles
                      defaultShowLastRealBars={
                        timeframe === '1m' ? VISIBLE_1M_REAL_BARS : undefined
                      }
                    />
                  </Suspense>
                ) : (
                  <div className="flex h-full items-center justify-center text-gray-400">
                    K线数据加载中...
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* 订单簿 + 最近成交 */}
          <div className="bg-crypto-card border border-crypto-border rounded-lg p-4 overflow-hidden min-h-0 h-full flex flex-col gap-4 lg:min-h-0">
            <div className="min-h-0 flex-1 overflow-hidden">
              <h2 className="mb-3 text-lg font-semibold text-white">订单簿</h2>
              <OrderBookChart data={orderbook} maxRows={10} />
            </div>
            <div className="min-h-[220px] flex-1 overflow-hidden border-t border-crypto-border pt-3">
              <h2 className="mb-3 text-lg font-semibold text-white">最近成交</h2>
              <div className="grid grid-cols-3 pb-2 text-xs text-gray-400">
                <span>时间</span>
                <span className="text-right">价格</span>
                <span className="text-right">数量</span>
              </div>
              <div className="max-h-[260px] space-y-0.5 overflow-y-auto pr-1">
                {recentTrades.length === 0 ? (
                  <div className="py-6 text-center text-sm text-gray-500">暂无成交数据</div>
                ) : (
                  recentTrades.map((trade, index) => {
                    const side = String(trade.side || '').toLowerCase();
                    const isBuy = side === 'buy';
                    const isSell = side === 'sell';
                    return (
                      <div
                        key={`${trade.id ?? index}-${trade.timestamp ?? index}`}
                        className="grid grid-cols-3 py-1 text-xs tabular-nums"
                      >
                        <span className="text-gray-500">{formatTradeTime(trade.timestamp)}</span>
                        <span className={clsx('text-right', isBuy ? 'text-up' : isSell ? 'text-down' : 'text-gray-300')}>
                          {formatMarketCompact(trade.price, 4)}
                        </span>
                        <span className="text-right text-gray-300">{formatMarketCompact(trade.amount)}</span>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

export { default } from '../components/AshareMarketWorkspace';
