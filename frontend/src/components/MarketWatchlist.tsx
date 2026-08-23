import { Plus, Trash2 } from 'lucide-react'
import type { InstrumentContract, MarketWatchlistEntry } from '../types/research'


type MarketWatchlistProps = {
  items: MarketWatchlistEntry[]
  selected: InstrumentContract | null
  loading?: boolean
  onAdd: () => void
  onDelete: (entryId: number) => void
  onSelect: (symbol: string) => void
}


export default function MarketWatchlist({
  items,
  selected,
  loading = false,
  onAdd,
  onDelete,
  onSelect,
}: MarketWatchlistProps) {
  return (
    <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-gray-100">自选</h2>
          <p className="mt-0.5 text-[11px] text-gray-600">仅持久化证券代码与备注，价格来自当前缓存。</p>
        </div>
        <button
          type="button"
          onClick={onAdd}
          disabled={!selected || selected.asset_class === 'index' || loading}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-blue-500/35 bg-blue-500/10 px-2.5 text-[11px] text-blue-200 disabled:cursor-not-allowed disabled:border-crypto-border disabled:bg-transparent disabled:text-gray-600"
        >
          <Plus className="h-3.5 w-3.5" />
          加入当前证券
        </button>
      </div>
      {loading ? (
        <div className="py-6 text-center text-xs text-gray-500">读取自选…</div>
      ) : items.length ? (
        <div className="divide-y divide-crypto-border/70 overflow-hidden rounded-lg border border-crypto-border">
          {items.map((item) => (
            <div key={item.id} className="grid grid-cols-[minmax(0,1fr)_90px_32px] items-center gap-2 bg-crypto-bg/40 px-3 py-2">
              <button type="button" onClick={() => onSelect(item.symbol)} className="min-w-0 text-left">
                <span className="block truncate text-xs font-semibold text-gray-200">{item.name || item.symbol}</span>
                <span className="mt-0.5 block font-mono text-[10px] text-gray-600">{item.symbol}{item.note ? ` · ${item.note}` : ''}</span>
              </button>
              <span className="text-right font-mono text-xs text-gray-300">{item.price == null ? '—' : Number(item.price).toLocaleString('zh-CN')}</span>
              <button type="button" aria-label={`删除自选 ${item.symbol}`} onClick={() => onDelete(item.id)} className="rounded p-1.5 text-gray-600 hover:bg-red-500/10 hover:text-red-300">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-crypto-border py-6 text-center text-xs text-gray-500">自选为空</div>
      )}
    </section>
  )
}
