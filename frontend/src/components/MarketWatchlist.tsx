import { useCallback, useEffect, useState } from 'react';
import { Plus, RefreshCw, Search, Star, Trash2 } from 'lucide-react';
import {
  addMarketWatchlistItem,
  deleteMarketWatchlistItem,
  getMarketWatchlist,
  getStoredAuthProfile,
  searchStocks,
} from '../api/client';
import type { MarketWatchlistResponse, StockCandidate } from '../types';
import { formatOperatorTime } from '../utils/presentation';
import { metricToneClass } from '../utils/marketColors';

const panel = 'rounded-xl border border-crypto-border bg-crypto-card';

export function MarketWatchlist() {
  const [data, setData] = useState<MarketWatchlistResponse | null>(null);
  const [query, setQuery] = useState('');
  const [note, setNote] = useState('');
  const [candidates, setCandidates] = useState<StockCandidate[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const isAdmin = getStoredAuthProfile()?.role === 'admin';
  const load = useCallback(async () => {
    setBusy(true); setError('');
    try { setData(await getMarketWatchlist()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '自选清单加载失败'); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const find = async () => {
    setBusy(true); setError('');
    try { setCandidates(await searchStocks({ q: query, limit: 8 })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '证券搜索失败'); }
    finally { setBusy(false); }
  };
  const add = async (symbol: string) => {
    if (!isAdmin) return;
    setBusy(true); setError('');
    try { await addMarketWatchlistItem({ symbol, note }); setQuery(''); setNote(''); setCandidates([]); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '添加自选失败'); }
    finally { setBusy(false); }
  };
  const remove = async (id: number) => {
    if (!isAdmin) return;
    setBusy(true); setError('');
    try { await deleteMarketWatchlistItem(id); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '删除自选失败'); }
    finally { setBusy(false); }
  };
  return <div className="space-y-5" data-testid="market-watchlist">
    <section className={`${panel} p-5`}>
      <div className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex items-center gap-2"><Star className="h-5 w-5 text-amber-300" /><h2 className="font-semibold text-white">我的自选</h2></div><p className="mt-1 text-xs text-slate-500">清单存 PostgreSQL；行情字段直接读取现有缓存，不复制价格。</p></div><button type="button" onClick={() => void load()} className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border px-3 text-xs text-slate-300"><RefreshCw className={`h-3.5 w-3.5 ${busy ? 'animate-spin' : ''}`} />刷新</button></div>
      {error ? <div className="mt-4 rounded-lg border border-red-500/25 bg-red-500/10 p-3 text-sm text-red-200">{error}</div> : null}
      <div className="mt-5 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <input aria-label="搜索自选证券" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入代码或名称" className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white" />
        <input aria-label="自选备注" value={note} onChange={(event) => setNote(event.target.value)} maxLength={200} placeholder="备注（可选）" className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white" />
        <button type="button" disabled={busy || !query.trim()} onClick={() => void find()} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 text-sm text-blue-200 disabled:opacity-40"><Search className="h-4 w-4" />查找</button>
      </div>
      {candidates.length ? <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">{candidates.map((item) => <button type="button" key={item.code} disabled={!isAdmin || busy} onClick={() => void add(item.code)} className="flex items-center justify-between rounded-lg border border-crypto-border bg-crypto-bg p-3 text-left disabled:opacity-50"><span><span className="block text-sm text-white">{item.name || item.code}</span><span className="font-mono text-[11px] text-slate-500">{item.code}</span></span><Plus className="h-4 w-4 text-blue-300" /></button>)}</div> : null}
      {!isAdmin ? <p className="mt-3 text-xs text-amber-300">访客可查看自选，不能添加或删除。</p> : null}
    </section>
    <section className={`${panel} overflow-hidden`}>
      <div className="overflow-x-auto"><table className="w-full min-w-[880px] text-sm"><thead><tr className="border-b border-crypto-border text-left text-xs text-slate-500">{['证券','最新价','涨跌幅','成交额','换手 / 量比','备注','行情时间','操作'].map((label) => <th key={label} className="px-4 py-3">{label}</th>)}</tr></thead><tbody>{(data?.items ?? []).map((item) => { const change = Number(item.change_percent); return <tr key={item.id} className="border-b border-white/[0.04] text-slate-300"><td className="px-4 py-3"><div className="font-semibold text-white">{item.name || item.symbol}</div><div className="font-mono text-[11px] text-slate-500">{item.symbol}</div></td><td className="px-4 py-3 font-mono">{item.price ?? '--'}</td><td className={`px-4 py-3 font-mono ${metricToneClass(Number.isFinite(change) ? change > 0 ? 'up' : change < 0 ? 'down' : 'neutral' : 'neutral')}`}>{item.change_percent == null ? '--' : `${change.toFixed(2)}%`}</td><td className="px-4 py-3 font-mono">{item.amount ?? '--'}</td><td className="px-4 py-3 font-mono">{item.turnover ?? '--'} / {item.volume_ratio ?? '--'}</td><td className="px-4 py-3 text-slate-400">{item.note || '--'}</td><td className="px-4 py-3 text-xs text-slate-500">{formatOperatorTime(item.quote_updated_at)}</td><td className="px-4 py-3"><button aria-label={`删除自选 ${item.symbol}`} type="button" disabled={!isAdmin || busy} onClick={() => void remove(item.id)} className="rounded-lg border border-red-500/20 p-2 text-red-300 disabled:opacity-30"><Trash2 className="h-3.5 w-3.5" /></button></td></tr>; })}</tbody></table></div>
      {!data?.items.length ? <div className="p-14 text-center text-sm text-slate-600">{busy && !data ? '正在读取自选…' : '尚未添加自选证券'}</div> : null}
    </section>
  </div>;
}
