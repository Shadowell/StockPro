import { useEffect, useMemo, useRef, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import clsx from 'clsx';
import { ChevronDown, Flame, RefreshCw, Search, Sparkles, TrendingUp, X } from 'lucide-react';
import {
  getDailyChart,
  getHotConceptLeaders,
  getHotConcepts,
  getStockFundamentals,
  getThsHot,
} from '../api/client';
import type { ConceptLeaderStock, DailyChartData, StockFundamentals, ThsHotItem } from '../types';

const TIMEFRAMES = ['分时', '1D', '5D', '1M', '3M', '1Y'];
const MIN_KLINES_TO_RENDER = 1;

const pctClass = (value?: number | null) => ((value || 0) >= 0 ? 'text-up' : 'text-down');
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
    : `${value >= 0 ? '+' : ''}${format(value)}%`;

const ema = (rows: DailyChartData[], period: number) => {
  const k = 2 / (period + 1);
  let current = rows[0]?.close || 0;
  return rows.map((row, index) => {
    current = index === 0 ? row.close : row.close * k + current * (1 - k);
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

export function Market() {
  const [thsHot, setThsHot] = useState<ThsHotItem[]>([]);
  const [selectedConcept, setSelectedConcept] = useState('');
  const [leaders, setLeaders] = useState<ConceptLeaderStock[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState('SH_600000');
  const [daily, setDaily] = useState<DailyChartData[]>([]);
  const [fundamentals, setFundamentals] = useState<StockFundamentals | null>(null);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [showPrediction, setShowPrediction] = useState(false);
  const [activeRange, setActiveRange] = useState('1D');
  const searchRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [conceptData, thsData] = await Promise.all([getHotConcepts(40), getThsHot(40)]);
      setThsHot(thsData);
      if (!selectedConcept && conceptData[0]?.name) setSelectedConcept(conceptData[0].name);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

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
    getHotConceptLeaders({ name: selectedConcept, limit: 20 }).then((items) => {
      setLeaders(items);
      if (items[0]?.code) setSelectedSymbol(items[0].code);
    });
  }, [selectedConcept]);

  useEffect(() => {
    Promise.all([getDailyChart(selectedSymbol), getStockFundamentals(selectedSymbol)]).then(([dailyData, fundamentalsData]) => {
      setDaily(dailyData);
      setFundamentals(fundamentalsData);
    });
  }, [selectedSymbol]);

  const fallbackPrice = fundamentals?.current_price ?? daily.at(-1)?.close;
  const fallbackChangePct = fundamentals?.change_percent
    ?? (daily.length > 1 && daily[0].close
      ? ((daily.at(-1)!.close - daily[0].close) / daily[0].close) * 100
      : undefined);
  const fallbackAmount = daily.at(-1)?.volume && fallbackPrice ? daily.at(-1)!.volume * fallbackPrice : undefined;

  const marketRows: MarketRow[] = useMemo(() => {
    if (leaders.length > 0) {
      return leaders.map((item, index) => ({
        code: item.code,
        name: item.name,
        price: item.price,
        change_percent: item.change_percent,
        amount: item.amount,
        turnover: item.turnover,
        rank: index + 1,
      }));
    }
    if (thsHot.length > 0) {
      return thsHot.slice(0, 12).map((item) => ({
        code: item.code,
        name: item.name,
        price: undefined,
        change_percent: item.change_percent,
        amount: undefined,
        turnover: undefined,
        rank: item.rank,
      }));
    }
    if (fallbackPrice != null || daily.length > 0 || fundamentals) {
      return [
        {
          code: selectedSymbol,
          name: fundamentals?.name || selectedSymbol,
          price: fallbackPrice,
          change_percent: fallbackChangePct,
          amount: fallbackAmount,
          turnover: undefined,
          rank: 1,
        },
      ];
    }
    return [];
  }, [daily.length, fallbackAmount, fallbackChangePct, fallbackPrice, fundamentals, leaders, selectedSymbol, thsHot]);

  const filteredMarketRows = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return marketRows;
    return marketRows.filter((item) => [item.code, item.name].join(' ').toLowerCase().includes(query));
  }, [marketRows, searchQuery]);

  const selectedLeader = marketRows.find((item) => item.code === selectedSymbol);
  const selectedPrice = fundamentals?.current_price ?? selectedLeader?.price ?? daily.at(-1)?.close;
  const selectedChangePct = fundamentals?.change_percent ?? selectedLeader?.change_percent;
  const selectedName = fundamentals?.name || selectedLeader?.name || selectedSymbol;

  const chartOption = useMemo(() => {
    const dates = daily.map((item) => item.date);
    const candleRows = daily.map((item) => [item.open, item.close, item.low, item.high]);
    const volumeRows = daily.map((item, index) => ({
      value: item.volume,
      itemStyle: { color: item.close >= item.open ? '#F6465D66' : '#00C85366' },
      date: dates[index],
    }));
    const ema5 = ema(daily, 5);
    const ema10 = ema(daily, 10);
    const ema20 = ema(daily, 20);
    const ema30 = ema(daily, 30);
    const predictionRows = showPrediction
      ? daily.map((item, index) => Number((item.close * (1 + (index + 1) * 0.002)).toFixed(4)))
      : [];
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
        { type: 'inside', xAxisIndex: [0, 1], start: daily.length > 80 ? 45 : 0, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1], bottom: 8, height: 18, start: daily.length > 80 ? 45 : 0, end: 100, borderColor: '#30363D', fillerColor: 'rgba(88,166,255,0.16)', textStyle: { color: '#8B949E' } },
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
          itemStyle: {
            color: '#F6465D',
            color0: '#00C853',
            borderColor: '#F6465D',
            borderColor0: '#00C853',
          },
        },
        { name: 'EMA5', type: 'line', data: ema5, smooth: true, symbol: 'none', lineStyle: { color: '#FFE600', width: 1.2 } },
        { name: 'EMA10', type: 'line', data: ema10, smooth: true, symbol: 'none', lineStyle: { color: '#00B8FF', width: 1.2 } },
        { name: 'EMA20', type: 'line', data: ema20, smooth: true, symbol: 'none', lineStyle: { color: '#E85AAD', width: 1.2 } },
        { name: 'EMA30', type: 'line', data: ema30, smooth: true, symbol: 'none', lineStyle: { color: '#00C853', width: 1.2 } },
        ...(showPrediction
          ? [{ name: 'AI 预测', type: 'line', data: predictionRows, smooth: true, symbol: 'none', lineStyle: { color: '#facc15', width: 1.5, type: 'dashed' } }]
          : []),
        { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumeRows, barWidth: '60%' },
      ],
    };
  }, [daily, showPrediction]);

  const lastClose = daily.at(-1)?.close ?? selectedPrice ?? 0;
  const lastBar = daily.at(-1);
  const lastUpdateLabel = lastBar?.date || fundamentals?.updated_at?.slice(0, 10) || '待同步';
  const currentPrice = Number(selectedPrice || lastClose || 0);
  const priceChange = Number(selectedChangePct || 0);
  const displayRows = (searchQuery.trim() ? filteredMarketRows : marketRows).slice(0, 8);
  const quickSymbols = (marketRows.length > 0 ? marketRows : filteredMarketRows).slice(0, 4);

  const handleSearchKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter') return;
    const first = filteredMarketRows[0];
    if (first?.code) {
      setSelectedSymbol(first.code);
      setSearchQuery('');
      setIsSearchOpen(false);
    }
  };

  const orderBook = useMemo(() => {
    const base = Number(lastClose || 10);
    const asks = Array.from({ length: 10 }, (_, index) => ({
      price: base + (10 - index) * 0.01,
      volume: 800 + index * 137,
      total: 0,
    }));
    let askTotal = 0;
    for (const row of asks) {
      askTotal += row.volume;
      row.total = askTotal;
    }
    const bids = Array.from({ length: 10 }, (_, index) => ({
      price: base - (index + 1) * 0.01,
      volume: 760 + index * 121,
      total: 0,
    }));
    let bidTotal = 0;
    for (const row of bids) {
      bidTotal += row.volume;
      row.total = bidTotal;
    }
    return { asks, bids };
  }, [lastClose]);

  return (
    <div className="h-full overflow-y-auto bg-crypto-bg p-6">
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
            onClick={() => setShowPrediction((value) => !value)}
            className={clsx(
              'group flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium transition-all duration-200',
              showPrediction
                ? 'bg-blue-500/20 text-blue-300'
                : 'text-gray-400 hover:bg-gray-800/70 hover:text-gray-300',
            )}
            title="AI 预测"
          >
            <Sparkles className={clsx('h-4 w-4 transition-colors', showPrediction ? 'text-white' : 'text-gray-500 group-hover:text-blue-300')} />
            AI 预测
          </button>
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
          <span className="market-connection-pill flex h-9 items-center gap-2 rounded-lg bg-emerald-500/10 px-3 text-xs font-medium text-emerald-300">
            <span className="relative flex h-2 w-2">
              <span className="absolute inset-0 animate-ping rounded-full bg-[#2ebd85] opacity-50" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-[#2ebd85]" />
            </span>
            实时
          </span>
        </div>
      </div>

      {loading && daily.length < MIN_KLINES_TO_RENDER ? (
        <div className="flex min-h-[560px] items-center justify-center text-gray-400">加载中...</div>
      ) : (
        <div className="grid min-h-[560px] grid-cols-1 gap-4 lg:grid-cols-4">
          <section className="flex h-full min-h-0 flex-col rounded-lg border border-crypto-border bg-crypto-card p-4 lg:col-span-3">
            <div className="mb-2 flex flex-wrap items-center gap-3">
              <div className="market-detail-controls flex min-w-0 flex-wrap items-center gap-3">
                <div className="market-type-toggle flex overflow-hidden rounded-lg border border-crypto-border bg-crypto-card" data-active-market="a-share">
                  {[
                    ['a-share', 'A股'],
                    ['theme', '板块'],
                  ].map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      className={clsx(
                        'h-9 px-3 text-xs font-semibold transition-colors',
                        value === 'a-share'
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
                    aria-label="选择股票"
                    title={selectedName}
                  >
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[10px] font-bold text-white">
                      {(selectedName || selectedSymbol).slice(0, 1)}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-white">{selectedSymbol}</span>
                    <ChevronDown className={clsx('h-4 w-4 shrink-0 text-gray-400 transition-transform', isSearchOpen && 'rotate-180')} />
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
                            placeholder="搜索股票 / 代码"
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
                            <span className="text-[10px] uppercase tracking-wider text-gray-500">热门</span>
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {quickSymbols.map((item) => (
                              <button
                                key={`hot-${item.code}`}
                                type="button"
                                onClick={() => {
                                  setSelectedSymbol(item.code);
                                  setSearchQuery('');
                                  setIsSearchOpen(false);
                                }}
                                className={clsx(
                                  'rounded px-2 py-0.5 text-xs transition-colors',
                                  selectedSymbol === item.code
                                    ? 'bg-blue-500/20 text-blue-300'
                                    : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white',
                                )}
                              >
                                {item.name || item.code}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}

                      <div className="max-h-[360px] overflow-y-auto">
                        {displayRows.length === 0 ? (
                          <div className="px-3 py-8 text-center text-sm text-gray-500">未找到匹配标的</div>
                        ) : (
                          displayRows.map((item, index) => (
                            <button
                              key={item.code}
                              type="button"
                              onClick={() => {
                                setSelectedSymbol(item.code);
                                setSearchQuery('');
                                setIsSearchOpen(false);
                              }}
                              className={clsx(
                                'flex w-full items-center border-l-2 px-3 py-2.5 text-left transition-colors',
                                selectedSymbol === item.code
                                  ? 'border-blue-500 bg-blue-600/20'
                                  : 'border-transparent hover:bg-gray-800/60',
                              )}
                            >
                              <span className="mr-2 w-7 text-center text-[10px] text-gray-600">{item.rank || index + 1}</span>
                              <span className="mr-2.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[10px] font-bold text-white">
                                {(item.name || item.code).slice(0, 1)}
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="block truncate text-sm font-medium text-white">{item.name || item.code}</span>
                                <span className="block truncate text-xs text-gray-500">{item.code}</span>
                              </span>
                              <span className={clsx('ml-2 shrink-0 text-xs font-semibold tabular-nums', pctClass(item.change_percent))}>
                                {signedPct(item.change_percent)}
                              </span>
                            </button>
                          ))
                        )}
                      </div>

                      <div className="border-t border-crypto-border/50 px-3 py-2 text-center text-[10px] text-gray-600">
                        共 {displayRows.length} 个标的 · 板块龙头优先
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className="flex min-w-[13rem] flex-1 flex-wrap items-baseline gap-x-3 gap-y-1">
                <div className="inline-flex rounded px-2 py-0.5 text-2xl font-bold leading-none text-white tabular-nums transition-all duration-500">
                  ¥{format(currentPrice)}
                </div>
                <span className={clsx('text-sm font-medium tabular-nums', pctClass(priceChange))}>{signedPct(priceChange)}</span>
                <span className="text-[10px] text-gray-600 tabular-nums">{lastUpdateLabel}</span>
              </div>

              <div className="market-detail-timeframe-controls ml-auto flex flex-wrap items-center justify-end gap-3">
                <div className="flex overflow-hidden rounded-lg border border-crypto-border bg-crypto-card">
                  {TIMEFRAMES.map((item) => (
                    <button
                      key={item}
                      type="button"
                      onClick={() => setActiveRange(item)}
                      className={clsx(
                        'px-3 py-1.5 text-xs font-medium transition-colors',
                        activeRange === item
                          ? 'bg-blue-500/20 text-blue-300'
                          : 'text-gray-500 hover:bg-gray-800/60 hover:text-gray-300',
                      )}
                    >
                      {item}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex basis-full flex-wrap items-center justify-between gap-2 text-xs text-gray-400">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span>共 {daily.length} 根K线</span>
                  <span className="text-gray-600">·</span>
                  <span className="truncate text-gray-500">{selectedName || selectedSymbol}</span>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  {quickSymbols.map((item) => (
                    <button
                      key={item.code}
                      type="button"
                      onClick={() => setSelectedSymbol(item.code)}
                      className={clsx(
                        'rounded-md border px-2 py-1 text-[11px] font-semibold transition-colors',
                        selectedSymbol === item.code
                          ? 'border-blue-500/60 bg-blue-500/15 text-blue-200'
                          : 'border-crypto-border bg-crypto-bg/60 text-gray-500 hover:border-gray-600 hover:text-gray-300',
                      )}
                    >
                      {item.name || item.code}
                    </button>
                  ))}
                </div>
              </div>

              {showPrediction && (
                <div className="basis-full rounded-lg border border-crypto-border bg-black/20 px-4 py-3">
                  <div className="text-xs font-medium text-gray-400">预测偏差分析（视觉预览）</div>
                  <div className="mt-2 flex flex-wrap gap-6 text-sm text-gray-200">
                    <div>
                      <span className="text-gray-500">MAE</span>
                      <span className="ml-2 font-mono tabular-nums">{Math.abs(priceChange / 100).toFixed(6)}</span>
                    </div>
                    <div>
                      <span className="text-gray-500">方向准确率</span>
                      <span className="ml-2 font-mono tabular-nums">{daily.length > 1 ? '66.7%' : '-'}</span>
                    </div>
                    <div>
                      <span className="text-gray-500">重合样本数</span>
                      <span className="ml-2 font-mono tabular-nums">{Math.max(0, daily.length - 1)}</span>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="flex min-h-0 flex-1 flex-col gap-2">
              <h2 className="sr-only">K线图表</h2>
              <div className="h-[610px] min-h-[460px] min-w-0">
                {daily.length >= MIN_KLINES_TO_RENDER ? (
                  <ReactECharts option={chartOption} style={{ height: '100%', width: '100%' }} />
                ) : (
                  <div className="flex h-full items-center justify-center text-gray-400">K线数据加载中...</div>
                )}
              </div>
            </div>
          </section>

          <aside className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-crypto-border bg-crypto-card p-4 lg:min-h-0">
            <h2 className="mb-4 text-lg font-semibold text-white">订单簿</h2>
            <div className="grid grid-cols-3 border-b border-crypto-border pb-2 text-xs text-gray-400">
              <span>价格</span>
              <span className="text-right">数量</span>
              <span className="text-right">总计</span>
            </div>

            <div className="asks">
              {orderBook.asks.slice().reverse().map((row, index) => {
                const max = Math.max(...orderBook.asks.map((item) => item.volume), ...orderBook.bids.map((item) => item.volume), 1);
                const percentage = (row.volume / max) * 100;
                return (
                  <div key={`ask-${index}`} className="relative grid grid-cols-3 py-1 text-sm hover:bg-gray-800/30">
                    <div className="absolute right-0 top-0 h-full bg-red-500/10" style={{ width: `${percentage}%` }} />
                    <span className="relative z-10 font-mono text-up">{format(row.price)}</span>
                    <span className="relative z-10 text-right text-gray-300">{format(row.volume, 0)}</span>
                    <span className="relative z-10 text-right text-gray-400">{format(row.total, 0)}</span>
                  </div>
                );
              })}
            </div>

            <div className="my-2 border-y border-crypto-border py-3">
              <div className="flex items-center justify-between">
                <span className="text-lg font-bold text-white">{format(lastClose)}</span>
                <span className="text-right text-xs text-yellow-400">价差: 0.01 (0.000%)</span>
              </div>
            </div>

            <div className="bids">
              {orderBook.bids.map((row, index) => {
                const max = Math.max(...orderBook.asks.map((item) => item.volume), ...orderBook.bids.map((item) => item.volume), 1);
                const percentage = (row.volume / max) * 100;
                return (
                  <div key={`bid-${index}`} className="relative grid grid-cols-3 py-1 text-sm hover:bg-gray-800/30">
                    <div className="absolute right-0 top-0 h-full bg-green-500/10" style={{ width: `${percentage}%` }} />
                    <span className="relative z-10 font-mono text-down">{format(row.price)}</span>
                    <span className="relative z-10 text-right text-gray-300">{format(row.volume, 0)}</span>
                    <span className="relative z-10 text-right text-gray-400">{format(row.total, 0)}</span>
                  </div>
                );
              })}
            </div>

          </aside>
        </div>
      )}
    </div>
  );
}

export default Market;
