import { useEffect, useState } from 'react';
import { Activity, RefreshCw } from 'lucide-react';
import { getMarketOverview } from '../api/client';
import type { MarketOverview } from '../types';
import { marketToneClass } from '../utils/marketColors';
import { formatOperatorTime } from '../utils/presentation';

export function MarketIndicesPanel() {
  const [data, setData] = useState<MarketOverview | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const load = async () => {
    setBusy(true); setError('');
    try { setData(await getMarketOverview()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '指数缓存加载失败'); }
    finally { setBusy(false); }
  };
  useEffect(() => { void load(); }, []);
  const updatedAt = data?.data_status?.index_snapshot_updated_at ?? data?.last_update;
  return <div className="space-y-5" data-testid="market-indices-panel">
    <section className="rounded-xl border border-crypto-border bg-crypto-card p-5"><div className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex items-center gap-2"><Activity className="h-5 w-5 text-blue-300" /><h2 className="font-semibold text-white">主要指数</h2></div><p className="mt-1 text-xs text-slate-500">复用 PostgreSQL 指数行情缓存；这里是行情深挖入口，不复制首页状态。</p></div><button type="button" onClick={() => void load()} className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border px-3 text-xs text-slate-300"><RefreshCw className={`h-3.5 w-3.5 ${busy ? 'animate-spin' : ''}`} />刷新</button></div>{error ? <div className="mt-4 rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-200">{error}</div> : null}<div className="mt-4 text-xs text-slate-500">来源：PostgreSQL 指数缓存 · 更新时间 {formatOperatorTime(updatedAt)} · 状态 {data?.data_status?.index_snapshot_state ?? '--'}</div></section>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{(data?.indices ?? []).map((item) => <article key={item.name} className="rounded-xl border border-crypto-border bg-crypto-card p-5" data-testid="market-index-card"><div className="text-sm font-semibold text-white">{item.name}</div><div className="mt-3 font-mono text-2xl font-bold text-slate-100">{item.price == null ? '--' : Number(item.price).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}</div><div className={`mt-2 font-mono text-sm ${marketToneClass(item.change_percent)}`}>{item.change_percent == null ? '--' : `${Number(item.change_percent) >= 0 ? '+' : ''}${Number(item.change_percent).toFixed(2)}%`}</div></article>)}</div>
    {!busy && !error && !data?.indices.length ? <div className="rounded-xl border border-dashed border-crypto-border p-14 text-center text-sm text-slate-600">当前没有指数行情缓存</div> : null}
  </div>;
}
