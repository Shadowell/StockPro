import { useEffect, useState, useRef, useCallback, lazy, Suspense } from 'react';
import { Activity, History, Layers3, RefreshCw, TrendingUp, Users, X, Zap } from 'lucide-react';
import clsx from 'clsx';
import { useSearchParams } from 'react-router-dom';
import { useStore } from '../stores/useStore';
import {
  marketApi,
  type MarketInstrument,
  type MarketKlinesMeta,
  type MarketPhase,
  type SectorMember,
  type SectorMembersPayload,
  type SectorRpsRow,
  type SymbolAbnormality,
} from '../api/client';
import OrderBookChart from '../components/OrderBookChart';
import SymbolSearch from '../components/SymbolSearch';
import type { Kline, OrderBook } from '../types';
import { formatTimeframeLabel } from '../utils/timeframe';

const KlineChart = lazy(() => import('../components/KlineChart'));

const TIMEFRAMES = ['1m', '5m', '15m', '30m', '60m', '1d'];

const REFRESH_INTERVALS: Record<string, number> = {
  '1m': 10_000,
  '5m': 15_000,
  '15m': 30_000,
  '1h': 60_000,
  '4h': 120_000,
  '1d': 300_000,
};

const MIN_KLINES_TO_RENDER = 1;
const MARKET_EMA_PERIODS = [5, 10, 20, 30];
const RECENT_TRADES_LIMIT = 24;

type MarketType = 'stock' | 'etf' | 'index';

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
  klineMeta?: MarketKlinesMeta | null;
  marketIndicators?: Record<string, Array<number | null>>;
  marketIndicatorTimestamps?: number[];
  orderbook?: OrderBook | null;
  trades?: MarketTradeRow[];
  lastUpdateMs?: number;
};

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

function formatTradeTime(timestamp?: number): string {
  if (!timestamp || !Number.isFinite(timestamp)) return '—';
  return new Date(timestamp).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function formatPercent(value?: number | null, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

function formatRatioLabel(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return value.toFixed(1);
}

function klineDataSourceLabel(meta?: MarketKlinesMeta | null, timeframe?: string): string {
  if (meta?.providerSource?.startsWith('akshare.')) {
    return meta.cacheHit ? 'AKShare 分时 · 缓存' : 'AKShare 分时';
  }
  if (timeframe === '1d') return 'PostgreSQL 日线';
  return 'PostgreSQL 分时缓存';
}

function klineStatusLabel(meta?: MarketKlinesMeta | null, hasRows = false): string {
  const status = meta?.dataStatus;
  if (!status) return hasRows ? 'ok' : '暂无数据';
  const labels: Record<string, string> = {
    ok: 'ok',
    stale: 'stale',
    empty: 'empty',
    unavailable: 'unavailable',
    unsupported: 'unsupported',
    provider_error: 'provider error',
  };
  return labels[status] || status;
}

export default function Market() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { selectedExchange, selectedSymbol, setSelectedSymbol } = useStore();
  const [klines, setKlines] = useState<Kline[]>([]);
  const [klineMeta, setKlineMeta] = useState<MarketKlinesMeta | null>(null);
  const [marketIndicators, setMarketIndicators] = useState<Record<string, Array<number | null>>>({});
  const [marketIndicatorTimestamps, setMarketIndicatorTimestamps] = useState<number[]>([]);
  const [orderbook, setOrderbook] = useState<OrderBook | null>(null);
  const [recentTrades, setRecentTrades] = useState<MarketTradeRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [allSymbols, setAllSymbols] = useState<string[]>([]);
  const [allInstruments, setAllInstruments] = useState<MarketInstrument[]>([]);
  const [marketType, setMarketType] = useState<MarketType>('stock');
  const [timeframe, setTimeframe] = useState('1m');
  const [marketPhase, setMarketPhase] = useState<MarketPhase | null>(null);
  const [sectorRps, setSectorRps] = useState<SectorRpsRow[]>([]);
  const [marketMovers, setMarketMovers] = useState<SymbolAbnormality[]>([]);
  const [sectorHistory, setSectorHistory] = useState<SectorRpsRow[]>([]);
  const [sectorMembers, setSectorMembers] = useState<SectorMembersPayload | null>(null);
  const [sectorDetailLoading, setSectorDetailLoading] = useState(false);
  const sectorCode = searchParams.get('sector') || '';
  const sectorClassification = searchParams.get('classification') === 'concept' ? 'concept' : 'industry';
  const selectedSymbolMatchesMarketType = Boolean(selectedSymbol);

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
    marketApi.getSymbols(selectedExchange, 'CNY', marketType)
      .then((res) => {
        if (cancelled) return;
        const symbols = res.symbols || [];
        const nextSymbol = symbols.includes(selectedSymbol) ? selectedSymbol : symbols[0];

        setAllSymbols(symbols);
        setAllInstruments(res.instruments || []);
        if (nextSymbol && nextSymbol !== selectedSymbol) {
          setSelectedSymbol(nextSymbol);
        }
      })
      .catch(console.error);
    return () => { cancelled = true; };
  }, [selectedExchange, selectedSymbol, setSelectedSymbol, marketType]);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([
      marketApi.getPhase(),
      marketApi.getSectorRps('industry', undefined, 5),
      marketApi.getMovers(undefined, 5),
    ]).then(([phase, rps, movers]) => {
      if (cancelled) return;
      setMarketPhase(phase.status === 'fulfilled' ? phase.value : null);
      setSectorRps(rps.status === 'fulfilled' ? rps.value : []);
      setMarketMovers(movers.status === 'fulfilled' ? movers.value : []);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!sectorCode) {
      setSectorHistory([]);
      setSectorMembers(null);
      return;
    }
    let cancelled = false;
    setSectorDetailLoading(true);
    Promise.all([
      marketApi.getSectorRpsHistory(sectorCode, sectorClassification, 60),
      marketApi.getSectorMembers(sectorCode, sectorClassification),
    ]).then(([history, members]) => {
      if (cancelled) return;
      setSectorHistory(history);
      setSectorMembers(members);
    }).catch(() => {
      if (cancelled) return;
      setSectorHistory([]);
      setSectorMembers({ items: [], total: 0, dataStatus: 'unavailable', unavailableReason: '板块详情读取失败' });
    }).finally(() => {
      if (!cancelled) setSectorDetailLoading(false);
    });
    return () => { cancelled = true; };
  }, [sectorClassification, sectorCode]);

  const applyMarketDataCacheEntry = useCallback(function applyMarketDataCacheEntry(entry?: MarketDataCacheEntry | null): boolean {
    if (!entry?.klines?.length) return false;
    setKlines(entry.klines);
    setKlineMeta(entry.klineMeta || null);
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

    const klineLimit = 500;
    const klineRequest = marketApi.getKlinesPayload(selectedExchange, selectedSymbol, timeframe, klineLimit);
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

    klineRequest.then((payload) => {
      if (isStaleMarketDataRequest()) return;
      const klinesData = payload.items || [];
      const lastUpdateMs = Date.now();
      setKlines(klinesData);
      setKlineMeta(payload);
      setLastUpdate(new Date(lastUpdateMs));
      updateMarketDataCache(cacheKey, {
        klines: klinesData,
        klineMeta: payload,
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

  }, [selectedExchange, selectedSymbol, selectedSymbolMatchesMarketType, timeframe, marketType, updateMarketDataCache]);


  // 初始加载 & 参数变化时重新拉取
  useEffect(() => {
    if (!selectedSymbol) return;
    const cacheKey = marketDataCacheKey(selectedExchange, selectedSymbol, timeframe);
    const cachedEntry = marketDataCacheRef.current.get(cacheKey);
    if (!applyMarketDataCacheEntry(cachedEntry)) {
      setKlines([]);
      setKlineMeta(null);
      setMarketIndicators({});
      setMarketIndicatorTimestamps([]);
      setOrderbook(null);
      setRecentTrades([]);
    }
    fetchData(Boolean(cachedEntry?.klines?.length));
  }, [applyMarketDataCacheEntry, fetchData, selectedExchange, selectedSymbol, timeframe]);

  // K 线 / 订单簿自动轮询
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    const base = REFRESH_INTERVALS[timeframe] || 15_000;
    intervalRef.current = setInterval(() => fetchData(true), base);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [fetchData, timeframe]);

  const handleManualRefresh = () => {
    fetchData(false);
    setRefreshSpin(true);
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    refreshTimerRef.current = setTimeout(() => setRefreshSpin(false), 1000);
  };

  const lastKline = klines[klines.length - 1];
  const previousKline = klines[klines.length - 2];
  const currentPrice = lastKline?.close || 0;
  const priceChange = previousKline?.close ? ((currentPrice / previousKline.close) - 1) * 100 : 0;
  const high24h = lastKline?.high;
  const low24h = lastKline?.low;
  const volume24h = lastKline?.volume;
  const quoteVolume24h = lastKline?.quoteVolume ?? lastKline?.quote_volume;
  const hasMarketData = klines.length > 0;
  const klineSourceLabel = klineDataSourceLabel(klineMeta, timeframe);
  const klineStateLabel = klineStatusLabel(klineMeta, hasMarketData);

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
              hasMarketData ? 'bg-emerald-500/10 text-emerald-300' : 'bg-white/[0.03] text-gray-500'
            )}
          >
            <span className="relative flex h-2 w-2">
              {hasMarketData && (
                <span className="absolute inset-0 rounded-full bg-[#2ebd85] animate-ping opacity-50" />
              )}
              <span
                className={clsx(
                  'relative inline-flex h-2 w-2 rounded-full',
                  hasMarketData ? 'bg-[#2ebd85]' : 'bg-gray-500'
                )}
              />
            </span>
            <span>{hasMarketData ? klineSourceLabel : klineStateLabel}</span>
          </div>

        </div>
      </div>

      {sectorCode ? (
        <section className="mb-4 overflow-hidden rounded-xl border border-cyan-500/20 bg-crypto-card/95">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border/60 px-4 py-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Layers3 className="h-4 w-4 text-cyan-300" />
                <h2 className="truncate text-sm font-semibold text-gray-100">
                  {(sectorHistory[sectorHistory.length - 1]?.sectorName || sectorMembers?.items[0]?.sectorName || sectorCode)} · {sectorClassification === 'concept' ? '概念' : '行业'}详情
                </h2>
              </div>
              <div className="mt-1 text-[10px] text-gray-500">
                成员快照 {sectorMembers?.tradeDate || '—'} · #{sectorMembers?.sourceSnapshotId ?? '—'} · {sectorMembers?.membershipBias || '成员偏差待确认'}
              </div>
            </div>
            <button
              type="button"
              title="关闭板块详情"
              onClick={() => {
                const next = new URLSearchParams(searchParams);
                next.delete('sector');
                next.delete('classification');
                setSearchParams(next, { replace: true });
              }}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-crypto-border text-gray-500 hover:bg-slate-800 hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          {sectorDetailLoading ? (
            <div className="flex h-32 items-center justify-center text-xs text-gray-500">板块证据读取中...</div>
          ) : (
            <div className="grid gap-px bg-crypto-border/50 xl:grid-cols-[1.15fr_1fr]">
              <div className="min-w-0 bg-crypto-card p-4">
                <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-gray-300">
                  <History className="h-3.5 w-3.5 text-blue-300" /> RPS 轮动历史
                </div>
                <div className="overflow-x-auto">
                  <div className="min-w-[620px]">
                    <div className="grid grid-cols-[90px_55px_60px_repeat(4,72px)_80px] gap-2 border-b border-crypto-border/50 pb-2 text-[10px] text-gray-600">
                      <span>交易日</span><span>排名</span><span>RPS</span><span>5日</span><span>10日</span><span>20日</span><span>60日</span><span>覆盖</span>
                    </div>
                    {sectorHistory.slice(-10).reverse().map((row) => (
                      <div key={`${row.tradeDate}-${row.sectorCode}`} className="grid grid-cols-[90px_55px_60px_repeat(4,72px)_80px] gap-2 border-b border-crypto-border/35 py-2 text-[11px] text-gray-400">
                        <span className="font-mono">{row.tradeDate}</span>
                        <span className="font-mono">{row.rank ?? '—'}</span>
                        <span className="font-mono text-blue-200">{formatRatioLabel(row.rpsPercentile)}</span>
                        <span>{formatPercent(row.return5d, 1)}</span>
                        <span>{formatPercent(row.return10d, 1)}</span>
                        <span>{formatPercent(row.return20d, 1)}</span>
                        <span>{formatPercent(row.return60d, 1)}</span>
                        <span>{row.memberCoverage == null ? '—' : `${(row.memberCoverage * 100).toFixed(0)}%`}</span>
                      </div>
                    ))}
                    {!sectorHistory.length ? <div className="py-8 text-center text-xs text-gray-500">暂无板块历史结果</div> : null}
                  </div>
                </div>
              </div>
              <div className="min-w-0 bg-crypto-card p-4">
                <div className="mb-3 flex items-center justify-between gap-2 text-xs font-semibold text-gray-300">
                  <span className="flex items-center gap-2"><Users className="h-3.5 w-3.5 text-cyan-300" /> 当前成员快照</span>
                  <span className="font-normal text-gray-600">{sectorMembers?.total ?? sectorMembers?.items.length ?? 0} 只</span>
                </div>
                <div className="grid max-h-80 grid-cols-1 gap-1.5 overflow-y-auto sm:grid-cols-2">
                  {(sectorMembers?.items || []).map((member: SectorMember) => (
                    <button
                      key={member.symbol}
                      type="button"
                      onClick={() => setSelectedSymbol(member.symbol)}
                      className="min-w-0 rounded-md border border-crypto-border/50 px-2.5 py-2 text-left hover:bg-white/[0.03]"
                    >
                      <span className="block truncate text-xs text-gray-300">{member.name || member.symbol}</span>
                      <span className="mt-0.5 block font-mono text-[10px] text-gray-600">{member.symbol} · {member.board || '板块未知'}</span>
                    </button>
                  ))}
                  {!sectorMembers?.items.length ? (
                    <div className="col-span-full py-8 text-center text-xs text-gray-500">{sectorMembers?.unavailableReason || '暂无成员快照'}</div>
                  ) : null}
                </div>
              </div>
            </div>
          )}
        </section>
      ) : null}

      <div className="mb-4 grid gap-3 xl:grid-cols-[1.2fr_1fr_1fr]">
        <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card/90">
          <div className="flex items-center justify-between border-b border-crypto-border/60 px-4 py-3">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-blue-300" />
              <span className="text-sm font-semibold text-gray-100">市场阶段</span>
            </div>
            <span className={clsx('rounded-lg border px-2 py-1 text-[11px]', marketPhase?.status === 'ok' ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/25 bg-amber-500/10 text-amber-300')}>
              {marketPhase?.status || 'empty'}
            </span>
          </div>
          <div className="px-4 py-3">
            <div className="flex items-end gap-3">
              <div className="text-xl font-semibold text-white">{marketPhase?.phase || 'unknown'}</div>
              <div className="pb-0.5 text-xs tabular-nums text-gray-500">
                置信度 {marketPhase ? `${Math.round(marketPhase.confidence * 100)}%` : '—'}
              </div>
            </div>
            <div className="mt-2 line-clamp-2 text-xs leading-5 text-gray-500">
              {(marketPhase?.reasons?.length ? marketPhase.reasons : marketPhase?.missingInputs || ['暂无已计算结果']).join(' · ')}
            </div>
          </div>
        </section>

        <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card/90">
          <div className="flex items-center gap-2 border-b border-crypto-border/60 px-4 py-3">
            <Layers3 className="h-4 w-4 text-cyan-300" />
            <span className="text-sm font-semibold text-gray-100">行业 RPS</span>
          </div>
          <div className="divide-y divide-crypto-border/40">
            {sectorRps.length ? sectorRps.slice(0, 3).map((row) => (
              <div key={row.sectorCode} className="grid grid-cols-[minmax(0,1fr)_64px_54px] items-center gap-2 px-4 py-2.5 text-xs">
                <span className="truncate text-gray-200">{row.sectorName}</span>
                <span className="text-right tabular-nums text-blue-200">{formatRatioLabel(row.rpsPercentile)}</span>
                <span className={clsx('text-right tabular-nums', (row.rankChange || 0) >= 0 ? 'text-up' : 'text-down')}>{row.rankChange == null ? '—' : `${row.rankChange >= 0 ? '+' : ''}${row.rankChange}`}</span>
              </div>
            )) : <div className="px-4 py-8 text-center text-xs text-gray-500">暂无 RPS 结果</div>}
          </div>
        </section>

        <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card/90">
          <div className="flex items-center gap-2 border-b border-crypto-border/60 px-4 py-3">
            <Zap className="h-4 w-4 text-amber-300" />
            <span className="text-sm font-semibold text-gray-100">异动标签</span>
          </div>
          <div className="divide-y divide-crypto-border/40">
            {marketMovers.length ? marketMovers.slice(0, 3).map((row) => (
              <button key={row.symbol} type="button" onClick={() => setSelectedSymbol(row.symbol)} className="grid w-full grid-cols-[minmax(0,1fr)_72px] items-center gap-2 px-4 py-2.5 text-left text-xs hover:bg-white/[0.03]">
                <span className="min-w-0">
                  <span className="block truncate font-mono text-gray-200">{row.symbol}</span>
                  <span className="mt-0.5 block truncate text-[11px] text-gray-500">{(row.tags || []).join(' · ') || row.status || 'partial'}</span>
                </span>
                <span className={clsx('text-right font-semibold tabular-nums', (row.return3d || 0) >= 0 ? 'text-up' : 'text-down')}>{formatPercent(row.return3d)}</span>
              </button>
            )) : <div className="px-4 py-8 text-center text-xs text-gray-500">暂无异动结果</div>}
          </div>
        </section>
      </div>

      <div className="grid min-h-[720px] grid-cols-1 gap-4 lg:grid-cols-4">
          {/* K线图区域：flex 竖向占满格子高度，否则子元素 height:100% 失效，ECharts 主图会被压成一条 */}
          <div className="lg:col-span-3 bg-crypto-card border border-crypto-border rounded-lg p-4 min-h-0 h-full flex flex-col">
            <div className="mb-2 flex flex-wrap items-center gap-3">
              <div className="market-detail-controls flex min-w-0 flex-wrap items-center gap-3">
                {/* 市场类型 */}
                <div
                  className="market-type-toggle flex overflow-hidden rounded-lg border border-crypto-border bg-crypto-card"
                  data-active-market={marketType}
                >
                  {([
                    { value: 'stock', label: '股票' },
                    { value: 'etf', label: 'ETF' },
                    { value: 'index', label: '指数' },
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
                  instruments={allInstruments}
                  marketType={marketType}
                />
              </div>
              <div className="flex min-w-[13rem] flex-1 flex-wrap items-baseline gap-x-3 gap-y-1">
                <div className={clsx(
                  'inline-flex rounded px-2 py-0.5 text-2xl font-bold leading-none tabular-nums transition-all duration-500',
                  priceFlashClass
                )}>
                  ¥{currentPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
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
                <span className="tabular-nums">当日高 <span className="text-gray-200">{formatMarketCompact(high24h, 4)}</span></span>
                <span className="tabular-nums">当日低 <span className="text-gray-200">{formatMarketCompact(low24h, 4)}</span></span>
                <span className="tabular-nums">成交量 <span className="text-gray-200">{formatMarketCompact(volume24h)}</span></span>
                <span className="tabular-nums">成交额 <span className="text-gray-200">{formatMarketCompact(quoteVolume24h)}</span></span>
                <span className="tabular-nums">制度 <span className="text-gray-200">T+1 · 100股整手</span></span>
                <span className="ml-auto tabular-nums">共 {klines.length} 根K线</span>
              </div>
              <div className="flex basis-full flex-wrap items-center gap-x-3 gap-y-1 border-t border-crypto-border/50 pt-2 text-[11px] text-gray-500">
                <span>来源 <span className="text-gray-300">{klineSourceLabel}</span></span>
                <span>状态 <span className="text-gray-300">{klineStateLabel}</span></span>
                {klineMeta?.fallbackFrom?.dataStatus && (
                  <span>缓存 <span className="text-gray-300">{klineMeta.fallbackFrom.dataStatus}</span></span>
                )}
                {klineMeta?.externalFetch && (
                  <span>模式 <span className="text-gray-300">实时拉取</span></span>
                )}
                {klineMeta?.unavailableReason && !hasMarketData && (
                  <span className="text-amber-300">{klineMeta.unavailableReason}</span>
                )}
                {klineMeta?.fallbackError && (
                  <span className="text-amber-300">{klineMeta.fallbackError}</span>
                )}
              </div>
            </div>
            <div className="flex-1 min-h-0 flex flex-col gap-2">
              <div className="flex-1 min-h-[280px] min-w-0">
                {loading && klines.length < MIN_KLINES_TO_RENDER ? (
                  <div className="flex h-full items-center justify-center text-gray-400">
                    加载中...
                  </div>
                ) : klines.length >= MIN_KLINES_TO_RENDER ? (
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
                    />
                  </Suspense>
                ) : (
                  <div className="flex h-full items-center justify-center text-gray-400">
                    暂无 K 线数据
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

    </div>
  );
}
