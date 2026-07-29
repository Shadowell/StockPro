import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import clsx from 'clsx';
import { ChevronDown, Flame, RefreshCw, Search, TrendingUp, X } from 'lucide-react';
import {
  getDailyChart,
  getHotConceptIntradayKline,
  getHotConceptLeaders,
  getHotConcepts,
  getOrderBook,
  getStockFundamentals,
  getThsHot,
  searchStocks,
} from '../api/client';
import type {
  ConceptIntradayKlineItem,
  ConceptLeaderStock,
  DailyChartData,
  HotConceptItem,
  OrderBookSnapshot,
  StockFundamentals,
  ThsHotItem,
} from '../types';
import { COLOR_SCHEMES, useSettingsStore } from '../stores/useSettingsStore';
import { marketToneClass } from '../utils/marketColors';
import { formatSymbolLabel, resolveSymbolName, toPublicSymbol } from '../utils/symbolDisplay';

const MIN_KLINES_TO_RENDER = 1;

type MarketScope = 'a-share' | 'theme';

const pctClass = (value?: number | null) => marketToneClass(value, 'text-gray-500');
const format = (value?: number | null, digits = 2) =>
  value === null || value === undefined || Number.isNaN(value)
    ? '--'
    : Number(value).toLocaleString('zh-CN', {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
      });

const signedPct = (value?: number | null) =>
  value === null || value === undefined || Number.isNaN(value)
    ? '--'
    : `${value > 0 ? '+' : ''}${format(value)}%`;

const ema = (rows: DailyChartData[], period: number) => {
  if (!rows || rows.length < period) {
    return rows.map(() => null);
  }
  const k = 2 / (period + 1);
  let current = 0;
  return rows.map((row, index) => {
    if (index < period - 1) {
      return null;
    }
    if (index === period - 1) {
      const initialSum = rows.slice(0, period).reduce((acc, item) => acc + item.close, 0);
      current = initialSum / period;
      return Number(current.toFixed(4));
    }
    current = row.close * k + current * (1 - k);
    return Number(current.toFixed(4));
  });
};

type MarketRow = {
  code: string;
  name: string;
  price?: number | null;
  change_percent?: number | null;
  amount?: number | null;
  turnover?: number | null;
  rank?: number;
};

type MarketProps = {
  asOfDate?: string;
};

export function Market({ asOfDate }: MarketProps = {}) {
  const colorScheme = useSettingsStore((state) => state.colorScheme);
  const { upColor, downColor } = COLOR_SCHEMES[colorScheme];
  const [marketScope, setMarketScope] = useState<MarketScope>('a-share');
  const [thsHot, setThsHot] = useState<ThsHotItem[]>([]);
  const [concepts, setConcepts] = useState<HotConceptItem[]>([]);
  const [selectedConcept, setSelectedConcept] = useState('');
  const [leaders, setLeaders] = useState<ConceptLeaderStock[]>([]);
  const [conceptIntraday, setConceptIntraday] = useState<ConceptIntradayKlineItem[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState('SH_600000');
  const [daily, setDaily] = useState<DailyChartData[]>([]);
  const [fundamentals, setFundamentals] = useState<StockFundamentals | null>(null);
  const [searchHits, setSearchHits] = useState<MarketRow[]>([]);
  const [listHits, setListHits] = useState<MarketRow[]>([]);
  const [universeRows, setUniverseRows] = useState<MarketRow[]>([]);
  const [universeTotalHint, setUniverseTotalHint] = useState<number | null>(null);
  const [orderBook, setOrderBook] = useState<OrderBookSnapshot | null>(null);
  const [orderBookLoading, setOrderBookLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [listFilter, setListFilter] = useState('');
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const toRows = (items: Array<{ code: string; name?: string | null; price?: number | null; change_percent?: number | null; amount?: number | null }>): MarketRow[] =>
    items.map((item, index) => ({
      code: item.code,
      name: item.name || item.code,
      price: item.price,
      change_percent: item.change_percent,
      amount: item.amount,
      rank: index + 1,
    }));

  const loadUniverse = useCallback(async (query = '', limit = 200) => {
    const items = await searchStocks({ q: query, limit });
    return toRows(items);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [conceptResult, thsResult, universeResult] = await Promise.allSettled([
        getHotConcepts(40, asOfDate),
        getThsHot(40, asOfDate),
        loadUniverse('', 200),
      ]);
      setThsHot(thsResult.status === 'fulfilled' ? thsResult.value : []);
      if (conceptResult.status === 'fulfilled') {
        setConcepts(conceptResult.value);
        if (conceptResult.value[0]?.name) {
          setSelectedConcept((current) => current || conceptResult.value[0].name);
        }
      } else {
        setConcepts([]);
      }
      if (universeResult.status === 'fulfilled') {
        setUniverseRows(universeResult.value);
        setUniverseTotalHint(universeResult.value.length >= 200 ? 200 : universeResult.value.length);
      }
    } finally {
      setLoading(false);
    }
  }, [asOfDate, loadUniverse]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const handleMouseDown = (event: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(event.target as Node)) {
        setIsSearchOpen(false);
      }
    };
    document.addEventListener('mousedown', handleMouseDown);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, []);

  useEffect(() => {
    if (isSearchOpen) searchInputRef.current?.focus();
  }, [isSearchOpen]);

  useEffect(() => {
    if (!selectedConcept) return;
    let active = true;
    getHotConceptLeaders({ name: selectedConcept, limit: 20, date: asOfDate })
      .then((items) => {
        if (!active) return;
        setLeaders(items);
        if (marketScope === 'theme' && items[0]?.code) {
          setSelectedSymbol(items[0].code);
        }
      })
      .catch(() => {
        if (active) setLeaders([]);
      });
    return () => {
      active = false;
    };
  }, [asOfDate, marketScope, selectedConcept]);

  useEffect(() => {
    if (marketScope !== 'theme' || !selectedConcept) {
      setConceptIntraday([]);
      return;
    }
    let active = true;
    getHotConceptIntradayKline({ name: selectedConcept, period: '1', date: asOfDate })
      .then((rows) => {
        if (active) setConceptIntraday(rows);
      })
      .catch(() => {
        if (active) setConceptIntraday([]);
      });
    return () => {
      active = false;
    };
  }, [asOfDate, marketScope, selectedConcept]);

  useEffect(() => {
    if (marketScope !== 'a-share') return;
    let active = true;
    Promise.allSettled([getDailyChart(selectedSymbol), getStockFundamentals(selectedSymbol)]).then(
      ([dailyResult, fundamentalsResult]) => {
        if (!active) return;
        setDaily(dailyResult.status === 'fulfilled' ? dailyResult.value : []);
        setFundamentals(fundamentalsResult.status === 'fulfilled' ? fundamentalsResult.value : null);
      },
    );
    return () => {
      active = false;
    };
  }, [marketScope, selectedSymbol]);

  useEffect(() => {
    if (marketScope !== 'a-share' || !selectedSymbol) {
      setOrderBook(null);
      return;
    }
    let active = true;
    let first = true;
    const loadBook = () => {
      if (first) setOrderBookLoading(true);
      void getOrderBook(selectedSymbol)
        .then((book) => {
          if (active) setOrderBook(book);
        })
        .catch(() => {
          if (active) {
            setOrderBook({
              asks: [],
              bids: [],
              data_status: 'empty',
              error: 'fetch_failed',
              source_label: '实时盘口请求失败',
            });
          }
        })
        .finally(() => {
          if (active && first) {
            setOrderBookLoading(false);
            first = false;
          }
        });
    };
    loadBook();
    const timer = window.setInterval(loadBook, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [marketScope, selectedSymbol]);

  useEffect(() => {
    if (marketScope !== 'a-share') {
      setSearchHits([]);
      return;
    }
    const query = searchQuery.trim();
    let active = true;
    const timer = window.setTimeout(() => {
      void loadUniverse(query, query ? 120 : 200)
        .then((rows) => {
          if (!active) return;
          if (query) setSearchHits(rows);
          else {
            setSearchHits([]);
            setUniverseRows(rows);
            setUniverseTotalHint(rows.length >= 200 ? 200 : rows.length);
          }
        })
        .catch(() => {
          if (active && query) setSearchHits([]);
        });
    }, query ? 180 : 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [loadUniverse, marketScope, searchQuery]);

  useEffect(() => {
    if (marketScope !== 'a-share') {
      setListHits([]);
      return;
    }
    const query = listFilter.trim();
    if (!query) {
      setListHits([]);
      return;
    }
    let active = true;
    const timer = window.setTimeout(() => {
      void loadUniverse(query, 200)
        .then((rows) => {
          if (active) setListHits(rows);
        })
        .catch(() => {
          if (active) setListHits([]);
        });
    }, 180);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [listFilter, loadUniverse, marketScope]);

  const visibleDaily = useMemo(
    () => (asOfDate ? daily.filter((item) => item.date <= asOfDate) : daily),
    [asOfDate, daily],
  );
  const latestDaily = visibleDaily.at(-1);
  const previousDaily = visibleDaily.at(-2);
  const dailyChangePct =
    latestDaily && previousDaily?.close
      ? ((latestDaily.close - previousDaily.close) / previousDaily.close) * 100
      : undefined;
  const fallbackPrice = asOfDate ? latestDaily?.close : fundamentals?.current_price ?? latestDaily?.close;
  const fallbackChangePct = asOfDate ? dailyChangePct : fundamentals?.change_percent ?? dailyChangePct;
  const fallbackAmount =
    latestDaily?.volume && fallbackPrice ? latestDaily.volume * fallbackPrice : undefined;

  const conceptRows: MarketRow[] = useMemo(
    () =>
      concepts.map((item) => ({
        code: item.name,
        name: item.name,
        price: null,
        change_percent: item.change_percent,
        amount: item.net_inflow,
        rank: item.rank,
      })),
    [concepts],
  );

  const marketRows: MarketRow[] = useMemo(() => {
    if (marketScope === 'theme') return conceptRows;
    if (searchQuery.trim() && searchHits.length > 0) return searchHits;
    if (universeRows.length > 0) return universeRows;
    if (thsHot.length > 0) {
      return thsHot.slice(0, 40).map((item) => ({
        code: item.code,
        name: item.name,
        price: item.price,
        change_percent: item.change_percent,
        amount: undefined,
        turnover: undefined,
        rank: item.rank,
      }));
    }
    if (fallbackPrice != null || visibleDaily.length > 0 || (!asOfDate && fundamentals)) {
      return [
        {
          code: selectedSymbol,
          name: fundamentals?.name || toPublicSymbol(selectedSymbol),
          price: fallbackPrice,
          change_percent: fallbackChangePct,
          amount: fallbackAmount,
          turnover: undefined,
          rank: 1,
        },
      ];
    }
    return [];
  }, [
    asOfDate,
    conceptRows,
    fallbackAmount,
    fallbackChangePct,
    fallbackPrice,
    fundamentals,
    marketScope,
    searchHits,
    searchQuery,
    selectedSymbol,
    thsHot,
    universeRows,
    visibleDaily.length,
  ]);

  const listRows: MarketRow[] = useMemo(() => {
    if (marketScope === 'theme') return [];
    if (listFilter.trim()) return listHits;
    return universeRows.length > 0 ? universeRows : marketRows;
  }, [listFilter, listHits, marketRows, marketScope, universeRows]);

  const filteredMarketRows = useMemo(() => {
    if (marketScope === 'theme') {
      const query = searchQuery.trim().toLowerCase();
      if (!query) return marketRows;
      return marketRows.filter((item) => [item.code, item.name].join(' ').toLowerCase().includes(query));
    }
    if (searchQuery.trim() && searchHits.length > 0) return searchHits;
    return marketRows;
  }, [marketRows, marketScope, searchHits, searchQuery]);

  const selectedLeader = leaders.find((item) => item.code === selectedSymbol);
  const selectedConceptMeta = concepts.find((item) => item.name === selectedConcept);
  const selectedPrice =
    marketScope === 'theme'
      ? selectedLeader?.price ?? null
      : asOfDate
        ? latestDaily?.close ?? selectedLeader?.price
        : fundamentals?.current_price ?? selectedLeader?.price ?? latestDaily?.close;
  const selectedChangePct =
    marketScope === 'theme'
      ? selectedConceptMeta?.change_percent ?? selectedLeader?.change_percent ?? null
      : asOfDate
        ? dailyChangePct ?? selectedLeader?.change_percent
        : fundamentals?.change_percent ?? selectedLeader?.change_percent ?? dailyChangePct;
  const selectedName =
    marketScope === 'theme'
      ? selectedConcept || '选择板块'
      : resolveSymbolName(selectedSymbol, fundamentals?.name || selectedLeader?.name) ||
        toPublicSymbol(selectedSymbol);

  const stockChartOption = useMemo(() => {
    const dates = visibleDaily.map((item) => item.date);
    const candleRows = visibleDaily.map((item) => [item.open, item.close, item.low, item.high]);
    const volumeRows = visibleDaily.map((item, index) => ({
      value: item.volume,
      itemStyle: {
        color:
          item.close > item.open ? `${upColor}66` : item.close < item.open ? `${downColor}66` : '#94a3b866',
      },
      date: dates[index],
    }));
    const ema5 = ema(visibleDaily, 5);
    const ema10 = ema(visibleDaily, 10);
    const ema20 = ema(visibleDaily, 20);
    const ema30 = ema(visibleDaily, 30);
    return {
      backgroundColor: 'transparent',
      legend: {
        show: true,
        top: 8,
        right: 16,
        textStyle: { color: '#8B949E', fontSize: 11 },
      },
      grid: [
        { left: 56, right: 20, top: 52, height: '58%' },
        { left: 56, right: 20, top: '74%', height: '14%' },
      ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 1],
          start: visibleDaily.length > 60 ? Math.max(0, Math.floor((1 - 60 / visibleDaily.length) * 100)) : 0,
          end: 100,
        },
        {
          type: 'slider',
          xAxisIndex: [0, 1],
          bottom: 8,
          height: 18,
          start: visibleDaily.length > 60 ? Math.max(0, Math.floor((1 - 60 / visibleDaily.length) * 100)) : 0,
          end: 100,
          borderColor: '#30363D',
          fillerColor: 'rgba(88,166,255,0.16)',
          textStyle: { color: '#8B949E' },
        },
      ],
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      xAxis: [
        {
          type: 'category',
          data: dates,
          axisLine: { lineStyle: { color: '#30363D' } },
          axisLabel: { color: '#8B949E' },
        },
        {
          type: 'category',
          gridIndex: 1,
          data: dates,
          axisLine: { lineStyle: { color: '#30363D' } },
          axisLabel: { color: '#8B949E' },
        },
      ],
      yAxis: [
        {
          type: 'value',
          scale: true,
          axisLine: { lineStyle: { color: '#30363D' } },
          splitLine: { lineStyle: { color: '#21262D' } },
          axisLabel: { color: '#8B949E' },
        },
        {
          type: 'value',
          gridIndex: 1,
          splitNumber: 2,
          axisLine: { lineStyle: { color: '#30363D' } },
          splitLine: { lineStyle: { color: '#21262D' } },
          axisLabel: { color: '#8B949E' },
        },
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: candleRows,
          barMaxWidth: 16,
          barMinWidth: 2,
          itemStyle: {
            color: upColor,
            color0: downColor,
            borderColor: upColor,
            borderColor0: downColor,
          },
        },
        { name: 'EMA5', type: 'line', data: ema5, smooth: true, symbol: 'none', lineStyle: { color: '#FFE600', width: 1.2 } },
        { name: 'EMA10', type: 'line', data: ema10, smooth: true, symbol: 'none', lineStyle: { color: '#00B8FF', width: 1.2 } },
        { name: 'EMA20', type: 'line', data: ema20, smooth: true, symbol: 'none', lineStyle: { color: '#E85AAD', width: 1.2 } },
        { name: 'EMA30', type: 'line', data: ema30, smooth: true, symbol: 'none', lineStyle: { color: '#00C853', width: 1.2 } },
        { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumeRows, barMaxWidth: 16 },
      ],
    };
  }, [downColor, upColor, visibleDaily]);

  const themeChartOption = useMemo(() => {
    const times = conceptIntraday.map((item) => item.time);
    const closes = conceptIntraday.map((item) => item.close);
    const volumes = conceptIntraday.map((item) => item.volume);
    return {
      backgroundColor: 'transparent',
      legend: { show: false },
      grid: [
        { left: 56, right: 20, top: 36, height: '58%' },
        { left: 56, right: 20, top: '74%', height: '14%' },
      ],
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      xAxis: [
        {
          type: 'category',
          data: times,
          axisLine: { lineStyle: { color: '#30363D' } },
          axisLabel: { color: '#8B949E', interval: Math.max(0, Math.floor(times.length / 6) - 1) },
        },
        {
          type: 'category',
          gridIndex: 1,
          data: times,
          axisLine: { lineStyle: { color: '#30363D' } },
          axisLabel: { show: false },
        },
      ],
      yAxis: [
        {
          type: 'value',
          scale: true,
          axisLine: { lineStyle: { color: '#30363D' } },
          splitLine: { lineStyle: { color: '#21262D' } },
          axisLabel: { color: '#8B949E' },
        },
        {
          type: 'value',
          gridIndex: 1,
          splitNumber: 2,
          axisLine: { lineStyle: { color: '#30363D' } },
          splitLine: { lineStyle: { color: '#21262D' } },
          axisLabel: { color: '#8B949E' },
        },
      ],
      series: [
        {
          name: '板块分时',
          type: 'line',
          data: closes,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#58A6FF', width: 1.6 },
          areaStyle: { color: 'rgba(88,166,255,0.12)' },
        },
        {
          name: '成交量',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes,
          barWidth: '60%',
          itemStyle: { color: 'rgba(88,166,255,0.35)' },
        },
      ],
    };
  }, [conceptIntraday]);

  const chartOption = marketScope === 'theme' ? themeChartOption : stockChartOption;
  const hasChart =
    marketScope === 'theme' ? conceptIntraday.length > 0 : visibleDaily.length >= MIN_KLINES_TO_RENDER;
  const lastClose = latestDaily?.close ?? selectedPrice ?? null;
  const lastUpdateLabel =
    marketScope === 'theme'
      ? selectedConceptMeta?.updated_at?.slice(0, 16) || asOfDate || '板块缓存'
      : latestDaily?.date || (!asOfDate ? fundamentals?.updated_at?.slice(0, 10) : null) || '待同步';
  const currentPrice = selectedPrice ?? lastClose;
  const priceChange = selectedChangePct ?? null;
  const displayRows =
    marketScope === 'theme'
      ? filteredMarketRows.slice(0, 40)
      : filteredMarketRows.slice(0, 120);
  const quickSymbols = (universeRows.length > 0 ? universeRows : marketRows).slice(0, 8);

  const selectMarketRow = (item: MarketRow) => {
    if (marketScope === 'theme') {
      setSelectedConcept(item.name || item.code);
    } else {
      setSelectedSymbol(item.code);
    }
    setSearchQuery('');
    setListFilter('');
    setIsSearchOpen(false);
  };

  const handleSearchKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter') return;
    const first = filteredMarketRows[0];
    if (first) selectMarketRow(first);
  };

  const switchScope = (next: MarketScope) => {
    setMarketScope(next);
    setSearchQuery('');
    setListFilter('');
    setIsSearchOpen(false);
    if (next === 'theme' && !selectedConcept && concepts[0]?.name) {
      setSelectedConcept(concepts[0].name);
    }
  };

  return (
    <div className="h-full overflow-y-auto bg-crypto-bg p-6" data-testid="market-terminal">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <TrendingUp className="h-6 w-6 text-blue-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">行情终端</h1>
            <p className="mt-1 text-xs text-slate-500">个股分析 · 板块龙头 · K线图表</p>
          </div>
        </div>
        <div className="market-action-strip flex flex-wrap items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card/80 p-1 shadow-sm shadow-black/10">
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className={clsx(
              'flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium text-gray-400 transition-all duration-200 hover:bg-gray-800/70 hover:text-gray-300',
              loading && 'cursor-not-allowed opacity-50',
            )}
            title="刷新行情"
          >
            <RefreshCw className={clsx('h-4 w-4 shrink-0', loading && 'animate-spin')} />
            刷新
          </button>
          <span className="market-connection-pill flex h-9 items-center gap-2 rounded-lg bg-amber-500/10 px-3 text-xs font-medium text-amber-200">
            {asOfDate ? `研究截止 ${asOfDate} · K线至 ${lastUpdateLabel}` : `PostgreSQL 历史缓存 · ${lastUpdateLabel}`}
          </span>
        </div>
      </div>

      {loading && !hasChart && marketRows.length === 0 ? (
        <div className="flex min-h-[560px] items-center justify-center text-gray-400">加载中...</div>
      ) : (
        <div className="grid min-h-[560px] grid-cols-1 gap-4 lg:grid-cols-4">
          <section className="flex h-full min-h-0 flex-col rounded-lg border border-crypto-border bg-crypto-card p-4 lg:col-span-3">
            <div className="mb-2 flex flex-wrap items-center gap-3">
              <div className="market-detail-controls flex min-w-0 flex-wrap items-center gap-3">
                <div
                  className="market-type-toggle flex overflow-hidden rounded-lg border border-crypto-border bg-crypto-card"
                  data-active-market={marketScope}
                  data-testid="market-scope-toggle"
                  role="tablist"
                  aria-label="行情范围"
                >
                  {(
                    [
                      ['a-share', 'A股'],
                      ['theme', '板块'],
                    ] as const
                  ).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      role="tab"
                      aria-selected={marketScope === value}
                      onClick={() => switchScope(value)}
                      className={clsx(
                        'h-9 px-3 text-xs font-semibold transition-colors',
                        marketScope === value
                          ? 'bg-blue-500/20 text-blue-300'
                          : 'text-gray-500 hover:bg-gray-800/60 hover:text-gray-300',
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                <div ref={searchRef} className="relative w-full min-w-[210px] sm:w-[270px]">
                  <button
                    type="button"
                    onClick={() => {
                      setSearchQuery('');
                      setIsSearchOpen((value) => !value);
                    }}
                    className="flex h-9 min-w-[180px] items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-3 text-left transition-colors hover:border-gray-500"
                    aria-label={marketScope === 'theme' ? '选择板块' : '选择股票'}
                    title={selectedName}
                  >
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[10px] font-bold text-white">
                      {(selectedName || selectedSymbol).slice(0, 1)}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-white">
                      {marketScope === 'theme'
                        ? selectedName
                        : formatSymbolLabel(selectedSymbol, selectedName)}
                    </span>
                    <ChevronDown
                      className={clsx(
                        'h-4 w-4 shrink-0 text-gray-400 transition-transform',
                        isSearchOpen && 'rotate-180',
                      )}
                    />
                  </button>

                  {isSearchOpen && (
                    <div className="absolute left-0 top-full z-50 mt-1 w-[320px] max-w-[calc(100vw-7rem)] overflow-hidden rounded-lg border border-crypto-border bg-crypto-card shadow-lg shadow-black/40">
                      <div className="border-b border-crypto-border p-2">
                        <div className="relative">
                          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                          <input
                            ref={searchInputRef}
                            value={searchQuery}
                            onChange={(event) => setSearchQuery(event.target.value)}
                            onKeyDown={handleSearchKeyDown}
                            placeholder={marketScope === 'theme' ? '搜索板块名称' : '搜索股票 / 代码'}
                            className="w-full rounded-lg border border-crypto-border bg-crypto-bg py-2 pl-8 pr-8 text-sm text-white outline-none transition-colors placeholder:text-gray-600 focus:border-blue-500"
                          />
                          {searchQuery && (
                            <button
                              type="button"
                              onClick={() => {
                                setSearchQuery('');
                                setIsSearchOpen(true);
                              }}
                              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                              aria-label="清空搜索"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </div>
                      </div>

                      {!searchQuery && (
                        <div className="border-b border-crypto-border/50 px-3 py-2">
                          <div className="mb-1.5 flex items-center gap-1">
                            <Flame className="h-3 w-3 text-orange-400" />
                            <span className="text-[10px] uppercase tracking-wider text-gray-500">
                              {marketScope === 'theme' ? '热门板块' : '成交额前列'}
                            </span>
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {quickSymbols.map((item) => (
                              <button
                                key={`hot-${item.code}`}
                                type="button"
                                onClick={() => selectMarketRow(item)}
                                className={clsx(
                                  'rounded px-2 py-0.5 text-xs transition-colors',
                                  (marketScope === 'theme'
                                    ? selectedConcept === item.name
                                    : selectedSymbol === item.code)
                                    ? 'bg-blue-500/20 text-blue-300'
                                    : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white',
                                )}
                              >
                                {item.name || item.code}
                              </button>
                            ))}
                          </div>
                          {marketScope === 'a-share' ? (
                            <p className="mt-2 text-[10px] leading-relaxed text-gray-600">
                              输入代码或名称可筛选全市场缓存标的
                            </p>
                          ) : null}
                        </div>
                      )}

                      <div className="max-h-[360px] overflow-y-auto">
                        {displayRows.length === 0 ? (
                          <div className="px-3 py-8 text-center text-sm text-gray-500">
                            {marketScope === 'theme' ? '未找到匹配板块' : '未找到匹配标的'}
                          </div>
                        ) : (
                          displayRows.map((item, index) => {
                            const active =
                              marketScope === 'theme'
                                ? selectedConcept === item.name || selectedConcept === item.code
                                : selectedSymbol === item.code;
                            return (
                              <button
                                key={item.code}
                                type="button"
                                onClick={() => selectMarketRow(item)}
                                className={clsx(
                                  'flex w-full items-center border-l-2 px-3 py-2.5 text-left transition-colors',
                                  active
                                    ? 'border-blue-500 bg-blue-600/20'
                                    : 'border-transparent hover:bg-gray-800/60',
                                )}
                              >
                                <span className="mr-2 w-7 text-center text-[10px] text-gray-600">
                                  {item.rank || index + 1}
                                </span>
                                <span className="mr-2.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[10px] font-bold text-white">
                                  {(item.name || item.code).slice(0, 1)}
                                </span>
                                <span className="min-w-0 flex-1">
                                  <span className="block truncate text-sm font-medium text-white">
                                    {item.name || item.code}
                                  </span>
                                  <span className="block truncate text-xs text-gray-500">
                                    {marketScope === 'theme'
                                      ? `净流入 ${format(item.amount, 2)}`
                                      : toPublicSymbol(item.code)}
                                  </span>
                                </span>
                                <span
                                  className={clsx(
                                    'ml-2 shrink-0 text-xs font-semibold tabular-nums',
                                    pctClass(item.change_percent),
                                  )}
                                >
                                  {signedPct(item.change_percent)}
                                </span>
                              </button>
                            );
                          })
                        )}
                      </div>

                      <div className="border-t border-crypto-border/50 px-3 py-2 text-center text-[10px] text-gray-600">
                        共 {displayRows.length} 个{marketScope === 'theme' ? '板块' : '标的'}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className="flex min-w-[13rem] flex-1 flex-wrap items-baseline gap-x-3 gap-y-1">
                {marketScope === 'theme' ? (
                  <>
                    <div
                      className={clsx(
                        'inline-flex rounded px-2 py-0.5 text-2xl font-bold leading-none tabular-nums transition-all duration-500',
                        marketToneClass(priceChange, 'text-blue-300'),
                      )}
                    >
                      {signedPct(priceChange)}
                    </div>
                    <span className="text-sm font-medium text-gray-500">板块涨跌</span>
                  </>
                ) : (
                  <>
                    <div
                      className={clsx(
                        'inline-flex rounded px-2 py-0.5 text-2xl font-bold leading-none tabular-nums transition-all duration-500',
                        marketToneClass(priceChange, 'text-blue-300'),
                      )}
                    >
                      ¥{format(currentPrice)}
                    </div>
                    <span className={clsx('text-sm font-medium tabular-nums', pctClass(priceChange))}>
                      {signedPct(priceChange)}
                    </span>
                  </>
                )}
                <span className="text-[10px] tabular-nums text-gray-600">{lastUpdateLabel}</span>
              </div>

              <div className="market-detail-timeframe-controls ml-auto flex flex-wrap items-center justify-end gap-3">
                <span className="rounded-lg border border-crypto-border bg-crypto-bg/60 px-3 py-1.5 text-xs font-medium text-gray-400">
                  {marketScope === 'theme' ? '分时' : '日线'}
                </span>
              </div>

              <div className="flex basis-full flex-wrap items-center justify-between gap-2 text-xs text-gray-400">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span>
                    {marketScope === 'theme'
                      ? `共 ${conceptIntraday.length} 根分时`
                      : `共 ${visibleDaily.length} 根K线`}
                  </span>
                  <span className="text-gray-600">·</span>
                  <span className="truncate text-gray-500">
                    {marketScope === 'theme'
                      ? selectedConcept || '未选板块'
                      : selectedName || toPublicSymbol(selectedSymbol)}
                  </span>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  {quickSymbols.map((item) => (
                    <button
                      key={item.code}
                      type="button"
                      onClick={() => selectMarketRow(item)}
                      className={clsx(
                        'rounded-md border px-2 py-1 text-[11px] font-semibold transition-colors',
                        (marketScope === 'theme'
                          ? selectedConcept === item.name
                          : selectedSymbol === item.code)
                          ? 'border-blue-500/60 bg-blue-500/15 text-blue-200'
                          : 'border-crypto-border bg-crypto-bg/60 text-gray-500 hover:border-gray-600 hover:text-gray-300',
                      )}
                    >
                      {item.name || toPublicSymbol(item.code)}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex min-h-0 flex-1 flex-col gap-2">
              <h2 className="sr-only">{marketScope === 'theme' ? '板块分时' : 'K线图表'}</h2>
              <div className="h-[610px] min-h-[460px] min-w-0">
                {hasChart ? (
                  <ReactECharts option={chartOption} notMerge={true} lazyUpdate={true} style={{ height: '100%', width: '100%' }} />
                ) : (
                  <div className="flex h-full items-center justify-center px-6 text-center text-gray-400">
                    {marketScope === 'theme'
                      ? selectedConcept
                        ? `暂无「${selectedConcept}」分时缓存`
                        : '请选择板块'
                      : asOfDate
                        ? `${asOfDate} 及以前暂无该标的日线数据`
                        : '本地 PostgreSQL 暂无该标的日线数据'}
                  </div>
                )}
              </div>
            </div>
          </section>

          <aside className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-crypto-border bg-crypto-card p-4 lg:min-h-0">
            {marketScope === 'theme' ? (
              <>
                <h2 className="mb-3 text-lg font-semibold text-white">板块龙头</h2>
                <div className="min-h-0 flex-1 overflow-y-auto">
                  {leaders.length === 0 ? (
                    <div className="grid h-40 place-items-center text-center text-xs text-gray-500">
                      {selectedConcept ? '该板块暂无龙头缓存' : '先选择一个板块'}
                    </div>
                  ) : (
                    leaders.map((item, index) => (
                      <button
                        key={item.code}
                        type="button"
                        onClick={() => setSelectedSymbol(item.code)}
                        className={clsx(
                          'flex w-full items-center gap-2 border-b border-white/[0.04] px-1 py-2.5 text-left transition-colors hover:bg-white/[0.03]',
                          selectedSymbol === item.code && 'bg-blue-500/[0.08]',
                        )}
                      >
                        <span className="w-5 text-[10px] text-gray-600">{index + 1}</span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm text-slate-100">{item.name}</span>
                          <span className="block truncate text-[10px] text-gray-500">
                            {toPublicSymbol(item.code)}
                          </span>
                        </span>
                        <span className={clsx('text-xs font-semibold tabular-nums', pctClass(item.change_percent))}>
                          {signedPct(item.change_percent)}
                        </span>
                      </button>
                    ))
                  )}
                </div>
                {selectedSymbol && leaders.some((item) => item.code === selectedSymbol) ? (
                  <button
                    type="button"
                    onClick={() => switchScope('a-share')}
                    className="mt-3 h-9 rounded-lg border border-blue-500/30 bg-blue-500/10 text-xs font-semibold text-blue-200 hover:bg-blue-500/20"
                  >
                    查看龙头日线 · {formatSymbolLabel(selectedSymbol, selectedLeader?.name)}
                  </button>
                ) : null}
              </>
            ) : (
              <>
                <div className="mb-3 shrink-0 rounded-lg border border-crypto-border/80 bg-crypto-bg/50 p-3" data-testid="market-order-book">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <div>
                      <h2 className="text-sm font-semibold text-white">五档盘口</h2>
                      <p className="mt-0.5 text-[10px] text-gray-500">
                        {orderBook?.source_label || (orderBookLoading ? '拉取中…' : '等待报价')}
                        {orderBook?.trade_time ? ` · ${orderBook.trade_time}` : ''}
                      </p>
                    </div>
                    <span className="text-[10px] text-gray-600">{orderBook?.volume_unit || '手'}</span>
                  </div>
                  {orderBookLoading && !orderBook?.asks?.length && !orderBook?.bids?.length ? (
                    <div className="grid h-28 place-items-center text-[11px] text-gray-500">加载盘口…</div>
                  ) : !orderBook?.asks?.length && !orderBook?.bids?.length ? (
                    <div className="grid h-28 place-items-center px-2 text-center text-[11px] text-gray-500">
                      {orderBook?.error || orderBook?.source_label || '暂无五档快照'}
                    </div>
                  ) : (
                    <div className="space-y-0.5 font-mono text-[11px] tabular-nums">
                      {(orderBook?.asks || []).map((level) => (
                        <div key={`ask-${level.level}`} className="grid grid-cols-[28px_1fr_1fr] gap-1">
                          <span className="text-gray-600">卖{level.level}</span>
                          <span className={clsx('text-right', pctClass(1))}>{format(level.price)}</span>
                          <span className="text-right text-gray-400">{format(level.volume, 0)}</span>
                        </div>
                      ))}
                      <div className="my-1 flex items-center justify-between border-y border-white/[0.06] py-1.5">
                        <span className={clsx('text-sm font-semibold', pctClass(orderBook?.change_percent))}>
                          {format(orderBook?.price ?? orderBook?.bid)}
                        </span>
                        <span className={clsx('text-[10px]', pctClass(orderBook?.change_percent))}>
                          {signedPct(orderBook?.change_percent)}
                        </span>
                      </div>
                      {(orderBook?.bids || []).map((level) => (
                        <div key={`bid-${level.level}`} className="grid grid-cols-[28px_1fr_1fr] gap-1">
                          <span className="text-gray-600">买{level.level}</span>
                          <span className={clsx('text-right', pctClass(-1))}>{format(level.price)}</span>
                          <span className="text-right text-gray-400">{format(level.volume, 0)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="mb-2 flex items-start justify-between gap-2">
                  <div>
                    <h2 className="text-sm font-semibold text-white">全市场标的</h2>
                    <p className="mt-0.5 text-[10px] text-gray-500">
                      {listFilter.trim()
                        ? `筛选命中 ${listRows.length} 只`
                        : `默认成交额前列 ${universeTotalHint ?? listRows.length} 只 · 可搜全市场`}
                    </p>
                  </div>
                </div>
                <div className="relative mb-2">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-500" />
                  <input
                    value={listFilter}
                    onChange={(event) => setListFilter(event.target.value)}
                    placeholder="筛选代码 / 名称"
                    className="h-9 w-full rounded-lg border border-crypto-border bg-crypto-bg py-2 pl-8 pr-8 text-xs text-white outline-none placeholder:text-gray-600 focus:border-blue-500"
                    data-testid="market-universe-filter"
                  />
                  {listFilter ? (
                    <button
                      type="button"
                      onClick={() => setListFilter('')}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                      aria-label="清空筛选"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  ) : null}
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto" data-testid="market-universe-list">
                  {listRows.length === 0 ? (
                    <div className="grid h-40 place-items-center px-3 text-center text-xs text-gray-500">
                      {listFilter.trim() ? '未找到匹配标的，换个代码或名称试试' : '暂无全市场缓存'}
                    </div>
                  ) : (
                    listRows.map((item, index) => (
                      <button
                        key={item.code}
                        type="button"
                        onClick={() => {
                          setSelectedSymbol(item.code);
                          setListFilter('');
                          setSearchQuery('');
                        }}
                        className={clsx(
                          'flex w-full items-center gap-2 border-b border-white/[0.04] px-1 py-2.5 text-left transition-colors hover:bg-white/[0.03]',
                          selectedSymbol === item.code && 'bg-blue-500/[0.08]',
                        )}
                      >
                        <span className="w-5 text-[10px] text-gray-600">{item.rank || index + 1}</span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm text-slate-100">{item.name}</span>
                          <span className="block truncate text-[10px] text-gray-500">
                            {toPublicSymbol(item.code)}
                          </span>
                        </span>
                        <span className={clsx('text-xs font-semibold tabular-nums', pctClass(item.change_percent))}>
                          {signedPct(item.change_percent)}
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

export default Market;
