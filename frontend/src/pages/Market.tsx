import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { Activity, BarChart3, BookOpen, Database, Star, TrendingUp } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { researchApi } from '../api/client'
import MarketWatchlist from '../components/MarketWatchlist'
import OrderBookChart from '../components/OrderBookChart'
import SymbolSearch from '../components/SymbolSearch'
import type { Kline, OrderBook } from '../types'
import type {
  DailyBarsResponse,
  InstrumentContract,
  InstrumentDetailView,
  MarketWatchlistEntry,
  OrderBookView,
} from '../types/research'
import { formatAshareSymbol } from '../utils/ashareSymbol'


const KlineChart = lazy(() => import('../components/KlineChart'))
type AssetFilter = 'all' | 'stock' | 'etf' | 'index'
type MarketTab = 'chart' | 'orderbook' | 'watchlist' | 'evidence'


const numberValue = (value: string | number | null | undefined) => {
  const parsed = Number(value)
  return value == null || !Number.isFinite(parsed) ? null : parsed
}

const formatNumber = (value: string | number | null | undefined, digits = 2) => {
  const parsed = numberValue(value)
  return parsed == null ? '—' : parsed.toLocaleString('zh-CN', { maximumFractionDigits: digits })
}

const formatPct = (value: string | number | null | undefined) => {
  const parsed = numberValue(value)
  return parsed == null ? '—' : `${parsed >= 0 ? '+' : ''}${parsed.toFixed(2)}%`
}


export default function Market() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<AssetFilter>('all')
  const [options, setOptions] = useState<InstrumentContract[]>([])
  const [searching, setSearching] = useState(false)
  const [selected, setSelected] = useState<InstrumentDetailView | null>(null)
  const [daily, setDaily] = useState<DailyBarsResponse | null>(null)
  const [orderBook, setOrderBook] = useState<OrderBookView | null>(null)
  const [watchlist, setWatchlist] = useState<MarketWatchlistEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const symbol = searchParams.get('symbol') || ''
  const tab = (searchParams.get('tab') as MarketTab | null) || 'chart'

  useEffect(() => {
    if (!query.trim()) {
      setOptions([])
      return
    }
    const timer = window.setTimeout(() => {
      setSearching(true)
      researchApi.searchInstruments(query, filter === 'all' ? null : filter, 30)
        .then((response) => setOptions(response.items))
        .catch(() => setOptions([]))
        .finally(() => setSearching(false))
    }, 180)
    return () => window.clearTimeout(timer)
  }, [filter, query])

  const loadWatchlist = async () => {
    try {
      setWatchlist((await researchApi.watchlist()).items)
    } catch {
      setWatchlist([])
    }
  }

  useEffect(() => {
    void loadWatchlist()
  }, [])

  useEffect(() => {
    if (!symbol) {
      setSelected(null)
      setDaily(null)
      setOrderBook(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([
      researchApi.instrumentDetail(symbol),
      researchApi.dailyBars(symbol, 500),
      researchApi.orderBook(symbol),
    ])
      .then(([detail, bars, depth]) => {
        if (cancelled) return
        setSelected(detail)
        setDaily(bars)
        setOrderBook(depth)
        setQuery(detail.instrument.name || detail.instrument.symbol)
      })
      .catch((requestError: any) => {
        if (!cancelled) setError(requestError?.response?.data?.detail || requestError?.message || '证券详情读取失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [symbol])

  const klines = useMemo<Kline[]>(() => (daily?.items || []).map((bar) => ({
    timestamp: new Date(`${bar.date}T00:00:00+08:00`).getTime(),
    open: Number(bar.open),
    high: Number(bar.high),
    low: Number(bar.low),
    close: Number(bar.close),
    volume: Number(bar.volume),
    quote_volume: bar.turnover == null ? undefined : Number(bar.turnover),
  })), [daily])

  const depth = useMemo<OrderBook | null>(() => {
    if (!selected || !orderBook || orderBook.data_status === 'empty') return null
    return {
      exchange: selected.instrument.exchange,
      symbol: selected.instrument.symbol,
      bids: orderBook.bids,
      asks: orderBook.asks,
    }
  }, [orderBook, selected])

  const selectInstrument = (instrument: InstrumentContract) => {
    setSearchParams({ symbol: instrument.symbol, tab: 'chart' })
  }

  const changeTab = (next: MarketTab) => {
    const params = new URLSearchParams(searchParams)
    params.set('tab', next)
    setSearchParams(params)
  }

  const selectWatchlistSymbol = (nextSymbol: string) => {
    setSearchParams({ symbol: nextSymbol, tab: 'chart' })
  }

  return (
    <div className="h-full overflow-y-auto bg-crypto-bg text-gray-100">
      <header className="border-b border-crypto-border/70 bg-slate-950/35 px-4 py-4 sm:px-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-blue-500/25 bg-blue-500/10">
              <TrendingUp className="h-5 w-5 text-blue-300" />
            </div>
            <div>
              <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-300/80">
                <Activity className="h-3 w-3" />
                Market Terminal
              </div>
              <h1 className="mt-0.5 text-xl font-bold text-white">A股行情</h1>
            </div>
          </div>

          <div className="flex w-full flex-col gap-2 xl:w-[640px]">
            <div className="flex gap-2">
              {(['all', 'stock', 'etf', 'index'] as const).map((item) => (
                <button key={item} type="button" onClick={() => setFilter(item)} className={`rounded-md border px-2.5 py-1 text-[11px] ${filter === item ? 'border-blue-500/40 bg-blue-500/10 text-blue-200' : 'border-crypto-border text-gray-500'}`}>
                  {{ all: '全部', stock: '股票', etf: 'ETF', index: '指数' }[item]}
                </button>
              ))}
            </div>
            <SymbolSearch query={query} onQueryChange={setQuery} options={options} loading={searching} onSelect={selectInstrument} />
          </div>
        </div>
      </header>

      <main className="space-y-4 px-4 py-4 pb-7 sm:px-6">
        {!symbol && (
          <div className="rounded-xl border border-dashed border-crypto-border bg-crypto-card/60 p-10 text-center">
            <BarChart3 className="mx-auto h-8 w-8 text-gray-600" />
            <div className="mt-3 text-sm font-semibold text-gray-300">选择股票、ETF 或指数</div>
            <div className="mt-1 text-xs text-gray-600">只读取 PostgreSQL 行情缓存，不自动同步 Provider。</div>
          </div>
        )}
        {loading && <div className="h-40 animate-pulse rounded-xl border border-crypto-border bg-crypto-card" />}
        {error && <div className="rounded-xl border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">{error}</div>}

        {!loading && !error && selected && (
          <>
            <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-lg font-semibold text-white">{selected.instrument.name || selected.instrument.symbol}</h2>
                    <span className="rounded border border-crypto-border bg-crypto-bg px-1.5 py-0.5 font-mono text-[10px] text-gray-500">{formatAshareSymbol(selected.instrument.symbol)}</span>
                    <span className="rounded border border-blue-500/25 bg-blue-500/10 px-1.5 py-0.5 text-[10px] text-blue-200">{selected.instrument.asset_class.toUpperCase()}</span>
                    <span className="rounded border border-crypto-border px-1.5 py-0.5 text-[10px] text-gray-400">{selected.instrument.lot_size}股</span>
                  </div>
                  <div className="mt-3 flex items-end gap-3">
                    <span className="font-mono text-2xl font-semibold tabular-nums text-white">{formatNumber(selected.latest_price)}</span>
                    <span className={`font-mono text-sm font-semibold ${numberValue(selected.change_pct) != null && Number(selected.change_pct) >= 0 ? 'text-up' : 'text-down'}`}>{formatPct(selected.change_pct)}</span>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
                  {[
                    ['代码.市场', formatAshareSymbol(selected.instrument.symbol)],
                    ['交易所', selected.instrument.exchange],
                    ['计价货币', selected.instrument.currency],
                    ['交易日历', selected.instrument.session_calendar || '—'],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-lg border border-crypto-border bg-crypto-bg/50 px-3 py-2">
                      <div className="text-gray-600">{label}</div><div className="mt-1 font-mono text-gray-300">{value || '—'}</div>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <div className="flex overflow-x-auto rounded-lg border border-crypto-border bg-crypto-card p-1">
              {([
                ['chart', 'K线', BarChart3],
                ['orderbook', '盘口', BookOpen],
                ['watchlist', '自选', Star],
                ['evidence', '证据', Database],
              ] as const).map(([id, label, Icon]) => (
                <button key={id} type="button" onClick={() => changeTab(id)} className={`inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md px-4 text-xs font-medium ${tab === id ? 'bg-blue-500/15 text-blue-200' : 'text-gray-500 hover:text-gray-200'}`}>
                  <Icon className="h-3.5 w-3.5" />{label}
                </button>
              ))}
            </div>

            {tab === 'chart' && (
              <section className="rounded-xl border border-crypto-border bg-crypto-card p-3">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-gray-500">
                  <span>日线 · 未复权研究价格</span>
                  <span>{daily?.source_label || '—'} · {daily?.data_status || 'empty'}</span>
                </div>
                {klines.length ? (
                  <Suspense fallback={<div className="h-[460px] animate-pulse rounded-lg bg-crypto-bg" />}>
                    <KlineChart data={klines} symbol={selected.instrument.symbol} height={460} showEMA showVolume defaultShowLastBars={120} />
                  </Suspense>
                ) : (
                  <div className="flex h-72 items-center justify-center rounded-lg border border-dashed border-crypto-border text-xs text-gray-500">当前证券没有日线缓存</div>
                )}
              </section>
            )}

            {tab === 'orderbook' && (
              <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
                <OrderBookChart data={depth} unavailableReason={orderBook?.unavailable_reason || '当前证券没有盘口缓存'} />
              </section>
            )}

            {tab === 'watchlist' && (
              <MarketWatchlist
                items={watchlist}
                selected={selected.instrument}
                onAdd={async () => {
                  await researchApi.addWatchlist(selected.instrument.symbol)
                  await loadWatchlist()
                }}
                onDelete={async (entryId) => {
                  await researchApi.deleteWatchlist(entryId)
                  await loadWatchlist()
                }}
                onSelect={selectWatchlistSymbol}
              />
            )}

            {tab === 'evidence' && (
              <section className="grid gap-3 rounded-xl border border-crypto-border bg-crypto-card p-4 sm:grid-cols-2 xl:grid-cols-4">
                {[
                  ['行情来源', 'PostgreSQL realtime cache'],
                  ['更新时间', selected.source_updated_at ? new Date(selected.source_updated_at).toLocaleString('zh-CN') : '—'],
                  ['复权口径', '未复权成交价'],
                  ['交易日历', selected.instrument.session_calendar || '—'],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3"><div className="text-[11px] text-gray-600">{label}</div><div className="mt-1 text-xs text-gray-300">{value}</div></div>
                ))}
              </section>
            )}
          </>
        )}
      </main>
    </div>
  )
}
