import { useEffect, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'
import type { InstrumentContract } from '../types/research'
import { formatAshareSymbol } from '../utils/ashareSymbol'


type SymbolSearchProps = {
  query?: string
  onQueryChange?: (query: string) => void
  options?: InstrumentContract[]
  loading?: boolean
  onSelect?: (instrument: InstrumentContract) => void
  className?: string
  value?: string
  onChange?: (symbol: string) => void
  allSymbols?: string[]
  marketType?: 'spot' | 'swap'
}

export const TOP50_SYMBOLS: string[] = []


const assetLabel = (assetClass: InstrumentContract['asset_class']) => ({
  stock: '股票',
  etf: 'ETF',
  index: '指数',
  future: '期货',
}[assetClass])


export default function SymbolSearch({
  query,
  onQueryChange,
  options,
  loading = false,
  onSelect,
  value,
  onChange,
  allSymbols,
  className = '',
}: SymbolSearchProps) {
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const currentQuery = query ?? value ?? ''
  const currentOptions = options ?? (allSymbols || []).map((symbol) => ({
    symbol,
    name: symbol,
    asset_class: 'stock' as const,
    market: 'CN' as const,
    exchange: '',
    currency: 'CNY',
    tick_size: '0.01',
    lot_size: 100,
    contract_multiplier: null,
    margin_rate: null,
    expiry_date: null,
    last_trade_date: null,
    settlement_type: null,
    session_calendar: null,
    shortable: false,
  }))
  const updateQuery = onQueryChange ?? onChange ?? (() => undefined)
  const selectInstrument = (instrument: InstrumentContract) => {
    onSelect?.(instrument)
    onChange?.(instrument.symbol)
  }

  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [])

  useEffect(() => setActiveIndex(0), [currentOptions])

  return (
    <div ref={rootRef} className={`relative ${className}`}>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
        <input
          aria-label="证券搜索"
          value={currentQuery}
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            updateQuery(event.target.value)
            setOpen(true)
          }}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') {
              event.preventDefault()
              setActiveIndex((index) => Math.min(index + 1, Math.max(0, currentOptions.length - 1)))
            } else if (event.key === 'ArrowUp') {
              event.preventDefault()
              setActiveIndex((index) => Math.max(0, index - 1))
            } else if (event.key === 'Enter' && currentOptions[activeIndex]) {
              event.preventDefault()
              selectInstrument(currentOptions[activeIndex])
              setOpen(false)
            } else if (event.key === 'Escape') {
              setOpen(false)
            }
          }}
          placeholder="搜索代码.市场或名称，例如 600519.SH / 贵州茅台"
          className="h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg pl-9 pr-9 text-sm text-white outline-none placeholder:text-gray-600 focus:border-blue-500/60"
        />
        {currentQuery && (
          <button
            type="button"
            aria-label="清空证券搜索"
            onClick={() => updateQuery('')}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-gray-500 hover:text-gray-200"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {open && currentQuery.trim() && (
        <div
          role="listbox"
          className="absolute left-0 top-full z-50 mt-1 max-h-80 w-full min-w-[320px] overflow-y-auto rounded-lg border border-crypto-border bg-[#151922] p-1 shadow-2xl"
        >
          {loading ? (
            <div className="px-3 py-5 text-center text-xs text-gray-500">正在检索 PostgreSQL 证券缓存…</div>
          ) : currentOptions.length ? (
            currentOptions.map((instrument, index) => (
              <button
                type="button"
                role="option"
                aria-selected={index === activeIndex}
                key={instrument.symbol}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => {
                  selectInstrument(instrument)
                  setOpen(false)
                }}
                className={`flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left ${
                  index === activeIndex ? 'bg-blue-500/15' : 'hover:bg-white/[0.04]'
                }`}
              >
                <span className="min-w-0">
                  <span className="block truncate text-xs font-semibold text-gray-100">{instrument.name || instrument.symbol}</span>
                  <span className="mt-0.5 block font-mono text-[10px] text-gray-500">{formatAshareSymbol(instrument.symbol)} · {instrument.exchange || 'A股'}</span>
                </span>
                <span className="shrink-0 rounded border border-crypto-border bg-crypto-bg px-1.5 py-0.5 text-[10px] text-gray-400">
                  {assetLabel(instrument.asset_class)}
                </span>
              </button>
            ))
          ) : (
            <div className="px-3 py-5 text-center text-xs text-gray-500">没有匹配的股票、ETF 或指数</div>
          )}
        </div>
      )}
    </div>
  )
}
