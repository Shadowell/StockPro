import { useEffect, useMemo, useState } from 'react'
import { Activity, BellRing, CheckCircle2, Clock3, FileJson2, Filter, RefreshCw, Search, Signal, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { operationsCurrentApi } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import type { OperationAlert, OperationSignal } from '../types/operations'


const displaySymbol = (value: string) => { const match = value.match(/^(SH|SZ|BJ)_(\d{6})$/); return match ? `${match[2]}.${match[1]}` : value }
const dateText = (value: unknown) => value ? new Date(String(value)).toLocaleString('zh-CN', { hour12: false }) : '—'

export default function SignalCenter() {
  const { role } = useAuth()
  const [signals, setSignals] = useState<OperationSignal[]>([])
  const [alerts, setAlerts] = useState<OperationAlert[]>([])
  const [selected, setSelected] = useState<OperationSignal | null>(null)
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const load = async () => {
    setLoading(true)
    try { const [signalResult, alertResult] = await Promise.all([operationsCurrentApi.signals('audit'), operationsCurrentApi.alerts('')]); setSignals(signalResult.items); setAlerts(alertResult.items); setError('') }
    catch (requestError: any) { setError(requestError?.response?.data?.detail || requestError?.message || '信号证据读取失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])
  const visible = useMemo(() => signals.filter((item) => (status === 'all' || item.status === status) && (!query.trim() || `${item.symbol} ${item.signal_type} ${item.paper_instance_id}`.toLowerCase().includes(query.trim().toLowerCase()))), [query, signals, status])
  const acknowledge = async () => { if (!selected) return; const next = await operationsCurrentApi.acknowledgeSignal(selected.id); setSelected(next); setSignals((items) => items.map((item) => item.id === next.id ? next : item)) }
  const summary: Array<[string, number, LucideIcon]> = [['信号总数', signals.length, Activity], ['待确认', signals.filter((item) => item.status === 'new').length, Clock3], ['投递记录', alerts.length, BellRing]]
  return (
    <div className="h-full overflow-y-auto bg-crypto-bg px-4 py-4 text-gray-100 sm:px-6">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-lg border border-blue-500/25 bg-blue-500/10"><Signal className="h-5 w-5 text-blue-300" /></div><div><div className="text-[10px] font-semibold uppercase tracking-[.18em] text-blue-300/80">Signal Audit</div><h1 className="text-xl font-bold text-white">信号中心</h1></div></div><button type="button" onClick={() => void load()} className="inline-flex items-center gap-1.5 rounded border border-crypto-border px-3 py-2 text-xs text-gray-400"><RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />刷新</button></header>
      <div className="grid gap-3 sm:grid-cols-3">{summary.map(([label, value, Icon]) => <div key={label} className="rounded-xl border border-crypto-border bg-crypto-card p-4"><div className="flex items-center justify-between text-[11px] text-gray-500"><span>{label}</span><Icon className="h-4 w-4 text-blue-400/70" /></div><div className="mt-2 font-mono text-2xl font-semibold">{value}</div></div>)}</div>
      <section className="mt-4 rounded-xl border border-crypto-border bg-crypto-card p-4"><div className="mb-3 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between"><div className="flex items-center gap-2"><Filter className="h-4 w-4 text-blue-300" /><h2 className="text-sm font-semibold">信号审计</h2></div><div className="flex gap-2"><select aria-label="信号状态" value={status} onChange={(event) => setStatus(event.target.value)} className="rounded border border-crypto-border bg-crypto-bg px-2 text-xs"><option value="all">全部状态</option><option value="new">待确认</option><option value="confirmed">已确认</option><option value="ordered">已下达</option><option value="closed">已关闭</option></select><label className="relative"><Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-gray-600" /><input aria-label="搜索信号" value={query} onChange={(event) => setQuery(event.target.value)} className="w-56 rounded border border-crypto-border bg-crypto-bg py-2 pl-8 pr-2 text-xs" placeholder="证券 / 类型 / Paper ID" /></label></div></div>
        {error ? <div className="rounded border border-red-500/25 bg-red-500/10 p-3 text-xs text-red-200">{error}</div> : <div className="overflow-x-auto"><table className="w-full min-w-[900px] text-left text-xs"><thead className="text-[10px] text-gray-600"><tr>{['证券','信号','状态','策略版本','Paper 实例','时间'].map((item) => <th key={item} className="border-b border-crypto-border px-3 py-2 font-medium">{item}</th>)}</tr></thead><tbody>{visible.map((item) => <tr data-testid="signal-row" data-paper-instance-id={item.paper_instance_id} key={item.id} onClick={() => setSelected(item)} className="cursor-pointer border-b border-crypto-border/60 hover:bg-white/[.03]"><td className="px-3 py-2.5 font-mono">{displaySymbol(item.symbol)}</td><td className="px-3 py-2.5 text-blue-200">{item.signal_type}</td><td className="px-3 py-2.5">{item.status}</td><td className="max-w-40 truncate px-3 py-2.5 font-mono text-gray-500">{item.strategy_version_id}</td><td className="max-w-40 truncate px-3 py-2.5 font-mono text-gray-500">{item.paper_instance_id}</td><td className="px-3 py-2.5 text-gray-500">{dateText(item.signal_time)}</td></tr>)}</tbody></table></div>}
      </section>
      <section className="mt-4 rounded-xl border border-crypto-border bg-crypto-card p-4"><div className="mb-3 flex items-center gap-2"><BellRing className="h-4 w-4 text-blue-300" /><h2 className="text-sm font-semibold">投递记录</h2></div>{alerts.length ? <div className="grid gap-2 md:grid-cols-2">{alerts.slice(0, 12).map((item) => <div key={item.id} className="rounded border border-crypto-border bg-crypto-bg/50 p-3"><div className="flex justify-between gap-2"><span className="text-xs text-gray-200">{item.title}</span><span className="text-[10px] text-gray-600">{item.status}</span></div><div className="mt-1 text-[10px] text-gray-500">{item.category} · {dateText(item.triggered_at)}</div></div>)}</div> : <div className="text-xs text-gray-500">暂无投递证据</div>}</section>
      {selected && <div className="fixed inset-0 z-50 flex justify-end bg-black/65"><aside className="h-full w-full max-w-xl overflow-y-auto border-l border-crypto-border bg-slate-950 p-5"><div className="flex items-start justify-between"><div><h2 className="text-lg font-semibold">信号详情</h2><p className="mt-1 font-mono text-[10px] text-gray-600">{selected.id}</p></div><button type="button" aria-label="关闭信号详情" onClick={() => setSelected(null)}><X className="h-4 w-4" /></button></div><div className="mt-4 space-y-2 text-xs">{[['证券',displaySymbol(selected.symbol)],['信号',selected.signal_type],['状态',selected.status],['Paper 实例',selected.paper_instance_id],['策略版本',selected.strategy_version_id],['证据时间',dateText(selected.signal_time)]].map(([label,value]) => <div key={label} className="rounded border border-crypto-border bg-crypto-bg/50 p-3"><div className="text-[10px] text-gray-600">{label}</div><div className="mt-1 break-all font-mono text-gray-300">{value}</div></div>)}</div><div className="mt-4"><div className="mb-2 flex items-center gap-2 text-sm font-semibold"><FileJson2 className="h-4 w-4 text-blue-300" />Payload evidence</div><pre className="max-h-96 overflow-auto rounded border border-crypto-border bg-crypto-bg p-3 text-[11px] text-gray-400">{JSON.stringify(selected.evidence, null, 2)}</pre></div>{role === 'admin' && selected.status === 'new' && <button type="button" onClick={() => void acknowledge()} className="mt-4 inline-flex items-center gap-1.5 rounded bg-blue-600 px-3 py-2 text-xs font-semibold"><CheckCircle2 className="h-3.5 w-3.5" />确认信号</button>}</aside></div>}
    </div>
  )
}
