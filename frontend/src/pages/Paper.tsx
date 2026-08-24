import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  BookOpenCheck,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  Database,
  FileClock,
  Gauge,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Square,
  WalletCards,
  X,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { backtestCurrentApi, paperCurrentApi } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import type { BacktestRunRecord } from '../types/backtest'
import type { PaperInstanceDetail, PaperInstanceView } from '../types/paper'
import { formatAshareSymbol } from '../utils/ashareSymbol'


type Numeric = string | number | null | undefined
type StatusFilter = 'all' | 'running' | 'paused' | 'stopped'

const numberValue = (value: Numeric) => {
  if (value == null || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const money = (value: Numeric) => {
  const parsed = numberValue(value)
  return parsed == null ? '—' : new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 2 }).format(parsed)
}

const percent = (value: Numeric) => {
  const parsed = numberValue(value)
  return parsed == null ? '—' : `${parsed >= 0 ? '+' : ''}${(parsed * 100).toFixed(2)}%`
}

const compactDate = (value: unknown) => {
  if (!value) return '—'
  const date = new Date(String(value))
  return Number.isNaN(date.getTime()) ? String(value).slice(0, 19) : date.toLocaleString('zh-CN', { hour12: false })
}

const displaySymbol = (value: unknown) => formatAshareSymbol(String(value || ''))

const statusLabel: Record<string, string> = {
  draft: '草稿', starting: '启动中', running: '运行中', pausing: '暂停中', paused: '已暂停', stopping: '停止中', stopped: '已停止', failed: '异常',
}

const statusTone = (status: string) => {
  if (status === 'running') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (status === 'paused' || status === 'draft') return 'border-amber-500/30 bg-amber-500/10 text-amber-200'
  if (status === 'failed') return 'border-red-500/30 bg-red-500/10 text-red-300'
  return 'border-slate-600/50 bg-slate-800/60 text-slate-300'
}

function EmptyBlock({ children }: { children: string }) {
  return <div className="rounded-lg border border-dashed border-crypto-border px-4 py-8 text-center text-xs text-gray-500">{children}</div>
}

function Panel({ title, icon: Icon, detail, children }: { title: string; icon: typeof Activity; detail?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2"><Icon className="h-4 w-4 text-blue-300" /><h2 className="text-sm font-semibold text-gray-100">{title}</h2></div>
        {detail && <span className="text-[10px] text-gray-600">{detail}</span>}
      </div>
      {children}
    </section>
  )
}

function EquityChart({ rows }: { rows: Array<Record<string, any>> }) {
  const points = rows.map((row) => numberValue(row.equity)).filter((value): value is number => value != null)
  if (points.length < 2) return <EmptyBlock>暂无可绘制的权益序列</EmptyBlock>
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = Math.max(max - min, 1)
  const polyline = points.map((value, index) => `${(index / (points.length - 1)) * 100},${44 - ((value - min) / span) * 38}`).join(' ')
  return (
    <div className="h-44 rounded-lg border border-crypto-border bg-crypto-bg/55 p-3">
      <svg viewBox="0 0 100 48" preserveAspectRatio="none" className="h-full w-full" role="img" aria-label="模拟盘账户曲线">
        <defs><linearGradient id="paper-equity" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#3b82f6" stopOpacity=".35" /><stop offset="1" stopColor="#3b82f6" stopOpacity="0" /></linearGradient></defs>
        <polygon points={`0,48 ${polyline} 100,48`} fill="url(#paper-equity)" />
        <polyline points={polyline} fill="none" stroke="#60a5fa" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  )
}

function InstanceCard({ item, onOpen }: { item: PaperInstanceView; onOpen: () => void }) {
  const pnl = numberValue(item.total_pnl)
  return (
    <article data-testid="paper-instance-card" className="group rounded-xl border border-crypto-border bg-crypto-card p-4 transition-colors hover:border-blue-500/40">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0"><h2 className="truncate text-sm font-semibold text-gray-100">{item.name}</h2><div className="mt-1 truncate font-mono text-[10px] text-gray-600">{item.id}</div></div>
        <span className={`shrink-0 rounded border px-2 py-0.5 text-[10px] font-semibold ${statusTone(item.lifecycle_status)}`}>{statusLabel[item.lifecycle_status] || item.lifecycle_status}</span>
      </div>
      <div className={`mt-5 font-mono text-2xl font-semibold tabular-nums ${pnl == null ? 'text-gray-500' : pnl >= 0 ? 'text-up' : 'text-down'}`}>{percent(item.return_rate)}</div>
      <div className="mt-1 text-[11px] text-gray-500">总盈亏 <span className="font-mono text-gray-300">{money(item.total_pnl)}</span></div>
      <div className="mt-4 grid grid-cols-3 gap-2 border-y border-crypto-border/70 py-3 text-center">
        <div><div className="text-[10px] text-gray-600">权益</div><div className="mt-1 truncate font-mono text-xs text-gray-200">{money(item.equity)}</div></div>
        <div><div className="text-[10px] text-gray-600">成交</div><div className="mt-1 font-mono text-xs text-gray-200">{item.trade_count}</div></div>
        <div><div className="text-[10px] text-gray-600">持仓</div><div className="mt-1 font-mono text-xs text-gray-200">{item.position_count}</div></div>
      </div>
      <div className="mt-3 flex items-center justify-between gap-2 text-[10px] text-gray-600"><span className="flex items-center gap-1"><Clock3 className="h-3 w-3" />{compactDate(item.heartbeat_at)}</span><button type="button" onClick={onOpen} className="inline-flex items-center gap-1 rounded border border-blue-500/25 px-2 py-1 text-blue-300 hover:bg-blue-500/10">详情<ChevronRight className="h-3 w-3" /></button></div>
    </article>
  )
}

function CreateDialog({ runs, onClose, onCreated }: { runs: BacktestRunRecord[]; onClose: () => void; onCreated: (item: PaperInstanceDetail) => void }) {
  const eligible = runs.filter((run) => run.run_mode === 'full' && run.promotion_status === 'paper_eligible')
  const [runId, setRunId] = useState(eligible[0]?.id || '')
  const [name, setName] = useState('A股策略模拟实例')
  const [cash, setCash] = useState('1000000')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const submit = async () => {
    const run = eligible.find((item) => item.id === runId) as (BacktestRunRecord & Record<string, any>) | undefined
    if (!run) return setError('请选择已通过完整晋级门禁的回测')
    setSubmitting(true); setError('')
    try {
      const created = await paperCurrentApi.create({
        name, initial_cash: Number(cash), qualifying_backtest_run_id: run.id,
        strategy_version_id: run.strategy_version_id, dataset_snapshot_id: run.dataset_snapshot_id,
        factor_snapshot_id: run.factor_snapshot_id, universe_snapshot_id: run.universe_snapshot_id,
        pool_snapshot_id: run.pool_snapshot_id, research_protocol_id: run.research_protocol_id,
      })
      onCreated(created)
    } catch (requestError: any) { setError(requestError?.response?.data?.detail || requestError?.message || '创建失败') }
    finally { setSubmitting(false) }
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-label="创建模拟实例">
      <div className="w-full max-w-lg rounded-xl border border-crypto-border bg-slate-950 p-5 shadow-2xl">
        <div className="flex items-center justify-between"><div><h2 className="text-base font-semibold text-white">创建模拟实例</h2><p className="mt-1 text-xs text-gray-500">只接受完整回测晋级证据，不修改历史实例。</p></div><button type="button" onClick={onClose} aria-label="关闭"><X className="h-5 w-5 text-gray-500" /></button></div>
        <div className="mt-5 space-y-4">
          <label className="block text-xs text-gray-400">实例名称<input value={name} onChange={(event) => setName(event.target.value)} className="mt-1.5 w-full rounded-md border border-crypto-border bg-crypto-bg px-3 py-2 text-sm text-gray-100 outline-none focus:border-blue-500" /></label>
          <label className="block text-xs text-gray-400">晋级回测<select value={runId} onChange={(event) => setRunId(event.target.value)} className="mt-1.5 w-full rounded-md border border-crypto-border bg-crypto-bg px-3 py-2 text-sm text-gray-100"><option value="">请选择</option>{eligible.map((run) => <option key={run.id} value={run.id}>{run.name}</option>)}</select></label>
          <label className="block text-xs text-gray-400">初始资金（CNY）<input type="number" min="1" value={cash} onChange={(event) => setCash(event.target.value)} className="mt-1.5 w-full rounded-md border border-crypto-border bg-crypto-bg px-3 py-2 font-mono text-sm text-gray-100" /></label>
          <div className="grid grid-cols-3 gap-2 text-center text-[10px] text-gray-500">{['T+1', '100股整手', '只做多'].map((item) => <span key={item} className="rounded border border-crypto-border bg-crypto-bg/70 px-2 py-2">{item}</span>)}</div>
          {error && <div className="rounded border border-red-500/25 bg-red-500/10 px-3 py-2 text-xs text-red-200">{error}</div>}
        </div>
        <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onClose} className="rounded border border-crypto-border px-3 py-2 text-xs text-gray-400">取消</button><button type="button" disabled={submitting || !runId || !name.trim()} onClick={() => void submit()} className="rounded bg-blue-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">{submitting ? '创建中…' : '创建草稿'}</button></div>
      </div>
    </div>
  )
}

function DetailView({ detail, readOnly, onBack, onChanged }: { detail: PaperInstanceDetail; readOnly: boolean; onBack: () => void; onChanged: (item: PaperInstanceDetail) => void }) {
  const [busy, setBusy] = useState('')
  const action = async (next: 'start' | 'pause' | 'resume' | 'stop') => {
    if (!window.confirm(`确认对「${detail.name}」执行${next === 'start' ? '启动' : next === 'pause' ? '暂停' : next === 'resume' ? '恢复' : '停止'}？`)) return
    setBusy(next)
    try { onChanged(await paperCurrentApi.transition(detail.id, next)) } finally { setBusy('') }
  }
  const view = detail.view
  const pnl = numberValue(view.total_pnl)
  return (
    <main className="space-y-4 px-4 py-4 pb-8 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3"><button type="button" onClick={onBack} className="mt-0.5 rounded border border-crypto-border p-2 text-gray-400 hover:text-white" aria-label="返回模拟实例列表"><ArrowLeft className="h-4 w-4" /></button><div className="min-w-0"><div className="flex items-center gap-2"><h1 className="truncate text-lg font-bold text-white">{detail.name}</h1><span className={`rounded border px-2 py-0.5 text-[10px] ${statusTone(detail.status)}`}>{statusLabel[detail.status] || detail.status}</span></div><div className="mt-1 truncate font-mono text-[10px] text-gray-600">{detail.id}</div></div></div>
        {!readOnly && <div className="flex flex-wrap gap-2">{['draft', 'stopped'].includes(detail.status) && <button type="button" disabled={!!busy} onClick={() => void action('start')} className="inline-flex items-center gap-1.5 rounded bg-emerald-600 px-3 py-2 text-xs font-semibold text-white"><Play className="h-3.5 w-3.5" />启动</button>}{detail.status === 'running' && <button type="button" disabled={!!busy} onClick={() => void action('pause')} className="inline-flex items-center gap-1.5 rounded border border-amber-500/35 px-3 py-2 text-xs text-amber-200"><Pause className="h-3.5 w-3.5" />暂停</button>}{detail.status === 'paused' && <button type="button" disabled={!!busy} onClick={() => void action('resume')} className="inline-flex items-center gap-1.5 rounded bg-emerald-600 px-3 py-2 text-xs text-white"><Play className="h-3.5 w-3.5" />恢复</button>}{!['stopped', 'draft'].includes(detail.status) && <button type="button" disabled={!!busy} onClick={() => void action('stop')} className="inline-flex items-center gap-1.5 rounded border border-red-500/35 px-3 py-2 text-xs text-red-300"><Square className="h-3.5 w-3.5" />停止</button>}</div>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[
        ['当前权益', money(view.equity), WalletCards], ['累计收益', percent(view.return_rate), BarChart3], ['累计盈亏', money(view.total_pnl), CircleDollarSign], ['成交 / 持仓', `${view.trade_count} / ${view.position_count}`, Activity],
      ].map(([label, value, Icon]) => <div key={String(label)} className="rounded-xl border border-crypto-border bg-crypto-card p-4"><div className="flex items-center justify-between text-[11px] text-gray-500"><span>{label as string}</span><Icon className="h-4 w-4 text-blue-400/70" /></div><div className={`mt-2 truncate font-mono text-xl font-semibold ${label === '累计盈亏' && pnl != null ? pnl >= 0 ? 'text-up' : 'text-down' : 'text-gray-100'}`}>{value as string}</div></div>)}</div>
      <div className="grid gap-4 xl:grid-cols-[1.25fr_0.75fr]"><Panel title="账户曲线" icon={BarChart3} detail={`${detail.equity_snapshots.length} 个净值点`}><EquityChart rows={detail.equity_snapshots} /></Panel><Panel title="风控状态" icon={ShieldCheck} detail={`${detail.risk_events.length} 条风险证据`}><div className="space-y-2">{detail.alerts.slice(0, 4).map((item) => <div key={String(item.id)} className="rounded-lg border border-amber-500/20 bg-amber-500/[0.06] p-3"><div className="text-xs font-medium text-amber-100">{item.title || item.alert_code || '风险告警'}</div><div className="mt-1 text-[10px] text-gray-500">{item.message || item.status}</div></div>)}{detail.alerts.length === 0 && <EmptyBlock>当前没有告警记录</EmptyBlock>}</div></Panel></div>
      <Panel title="当前持仓" icon={WalletCards} detail={`${detail.positions.length} 项`}><div className="overflow-x-auto">{detail.positions.length ? <table className="w-full min-w-[680px] text-left text-xs"><thead className="text-[10px] uppercase text-gray-600"><tr>{['证券', '数量', '可用', '成本价', '市场价值', '更新时间'].map((item) => <th key={item} className="border-b border-crypto-border px-3 py-2 font-medium">{item}</th>)}</tr></thead><tbody>{detail.positions.map((item) => <tr key={String(item.id)} className="border-b border-crypto-border/60 text-gray-300"><td className="px-3 py-2.5"><div>{item.name || '—'}</div><div className="mt-0.5 font-mono text-[10px] text-gray-600">{displaySymbol(item.symbol)}</div></td><td className="px-3 py-2.5 font-mono">{item.quantity ?? '—'}</td><td className="px-3 py-2.5 font-mono">{item.available_quantity ?? '—'}</td><td className="px-3 py-2.5 font-mono">{money(item.avg_cost ?? item.avg_price ?? item.average_price)}</td><td className="px-3 py-2.5 font-mono">{money(item.market_value)}</td><td className="px-3 py-2.5 text-gray-500">{compactDate(item.updated_at)}</td></tr>)}</tbody></table> : <EmptyBlock>当前没有持仓</EmptyBlock>}</div></Panel>
      <div className="grid gap-4 xl:grid-cols-2"><Panel title="成交与事件" icon={BookOpenCheck} detail={`${detail.trades.length} 笔成交 · ${detail.events.length} 个事件`}><div className="max-h-80 space-y-2 overflow-y-auto">{detail.events.slice(0, 12).map((item) => <div key={String(item.id)} className="rounded-lg border border-crypto-border bg-crypto-bg/45 p-3"><div className="flex justify-between gap-3"><span className="text-xs text-gray-300">{item.message || item.event_type}</span><span className="shrink-0 text-[10px] text-gray-600">{compactDate(item.occurred_at)}</span></div><div className="mt-1 font-mono text-[10px] text-blue-300/70">{item.event_type}</div></div>)}{detail.events.length === 0 && <EmptyBlock>暂无运行事件</EmptyBlock>}</div></Panel><Panel title="诊断日志" icon={FileClock} detail={`${detail.cycles.length} 个运行周期`}><div className="max-h-80 space-y-2 overflow-y-auto">{detail.cycles.slice().reverse().slice(0, 12).map((item) => <div key={String(item.id)} className="grid grid-cols-[84px_1fr_auto] items-center gap-2 rounded-lg border border-crypto-border bg-crypto-bg/45 px-3 py-2 text-[11px]"><span className="font-mono text-gray-500">{String(item.trade_date || '').slice(0, 10)}</span><span className="truncate text-gray-300">{item.error_message || item.cycle_key || '账本周期'}</span><span className={item.status === 'success' ? 'text-emerald-300' : item.status === 'failed' ? 'text-red-300' : 'text-amber-200'}>{item.status}</span></div>)}{detail.cycles.length === 0 && <EmptyBlock>暂无周期日志</EmptyBlock>}</div></Panel></div>
      <Panel title="固定输入证据" icon={Database}><div className="grid gap-2 text-[11px] sm:grid-cols-2 xl:grid-cols-4">{[['策略版本', detail.strategy_version_id], ['数据快照', detail.dataset_snapshot_id], ['Universe', detail.universe_snapshot_id], ['因子快照', detail.factor_snapshot_id], ['股票池快照', detail.pool_snapshot_id], ['研究协议', detail.research_protocol_id], ['晋级回测', detail.qualifying_backtest_run_id], ['运行时', detail.runtime_version]].map(([label, value]) => <div key={String(label)} className="rounded border border-crypto-border bg-crypto-bg/50 p-2"><div className="text-gray-600">{label}</div><div className="mt-1 truncate font-mono text-gray-300" title={String(value || '')}>{value == null ? '未绑定' : String(value)}</div></div>)}</div></Panel>
    </main>
  )
}

export default function Paper() {
  const { role } = useAuth()
  const [items, setItems] = useState<PaperInstanceView[]>([])
  const [runs, setRuns] = useState<BacktestRunRecord[]>([])
  const [detail, setDetail] = useState<PaperInstanceDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [showCreate, setShowCreate] = useState(false)
  const load = async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const [instancesResult, backtestsResult] = await Promise.allSettled([paperCurrentApi.list('audit'), backtestCurrentApi.runs(200)])
      if (instancesResult.status === 'rejected') throw instancesResult.reason
      setItems(instancesResult.value.items)
      setRuns(backtestsResult.status === 'fulfilled' ? backtestsResult.value.items : [])
      setError('')
    }
    catch (requestError: any) { if (!silent) setError(requestError?.response?.data?.detail || requestError?.message || '模拟实例读取失败') }
    finally { if (!silent) setLoading(false) }
  }
  useEffect(() => { void load(); const timer = window.setInterval(() => { if (!document.hidden) void load(true) }, 60_000); return () => window.clearInterval(timer) }, [])
  const open = async (id: string) => { setDetailLoading(true); try { setDetail(await paperCurrentApi.detail(id)) } finally { setDetailLoading(false) } }
  const visible = useMemo(() => items.filter((item) => (status === 'all' || item.lifecycle_status === status) && (!query.trim() || `${item.name} ${item.id}`.toLowerCase().includes(query.trim().toLowerCase()))), [items, query, status])
  const counts = useMemo(() => ({ all: items.length, running: items.filter((item) => item.lifecycle_status === 'running').length, paused: items.filter((item) => item.lifecycle_status === 'paused').length, stopped: items.filter((item) => item.lifecycle_status === 'stopped').length }), [items])
  const summaryMetrics: Array<[string, number, LucideIcon]> = [
    ['实例总数', counts.all, Activity],
    ['运行中', counts.running, Play],
    ['累计成交', items.reduce((sum, item) => sum + item.trade_count, 0), BookOpenCheck],
    ['当前持仓', items.reduce((sum, item) => sum + item.position_count, 0), WalletCards],
  ]
  if (detail) return <div className="h-full overflow-y-auto bg-crypto-bg"><DetailView detail={detail} readOnly={role !== 'admin'} onBack={() => setDetail(null)} onChanged={(item) => { setDetail(item); void load(true) }} /></div>
  return (
    <div className="h-full overflow-y-auto bg-crypto-bg">
      <header className="border-b border-crypto-border/70 bg-slate-950/35 px-4 py-4 sm:px-6"><div className="flex flex-wrap items-center justify-between gap-4"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-lg border border-blue-500/25 bg-blue-500/10"><Gauge className="h-5 w-5 text-blue-300" /></div><div><div className="text-[10px] font-semibold uppercase tracking-[.18em] text-blue-300/80">Paper Operations</div><div className="mt-0.5 flex items-center gap-2"><h1 className="text-xl font-bold text-white">模拟盘</h1><span className="rounded border border-blue-500/25 bg-blue-500/10 px-2 py-0.5 text-[10px] font-semibold text-blue-200">仅模拟</span><span className="rounded border border-slate-600/45 bg-slate-900/70 px-2 py-0.5 text-[10px] font-semibold text-slate-300">现金账本</span></div></div></div><div className="flex items-center gap-2"><span className="rounded border border-emerald-500/20 bg-emerald-500/[.07] px-2.5 py-1.5 text-[10px] font-semibold text-emerald-300">POSTGRESQL LEDGER</span>{role === 'admin' && <button type="button" onClick={() => setShowCreate(true)} className="inline-flex items-center gap-1.5 rounded bg-blue-600 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-500"><Plus className="h-3.5 w-3.5" />创建模拟实例</button>}</div></div><div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-l-2 border-blue-500/40 pl-3 text-xs text-gray-500"><span>完整审计视图 · 历史账本只读加载 · 写操作仅作用明确实例</span><button type="button" onClick={() => void load()} disabled={loading} className="inline-flex items-center gap-1.5 rounded border border-crypto-border px-2 py-1.5 text-[11px] text-gray-400"><RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />刷新</button></div></header>
      <main className="space-y-4 px-4 py-4 pb-8 sm:px-6"><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{summaryMetrics.map(([label, value, Icon]) => <div key={label} className="rounded-xl border border-crypto-border bg-crypto-card p-4"><div className="flex items-center justify-between text-[11px] text-gray-500"><span>{label}</span><Icon className="h-4 w-4 text-blue-400/70" /></div><div className="mt-2 font-mono text-2xl font-semibold text-gray-100">{value}</div></div>)}</div>
        <div className="flex flex-col gap-3 rounded-xl border border-crypto-border bg-crypto-card p-3 lg:flex-row lg:items-center lg:justify-between"><div className="flex flex-wrap gap-1">{(['all', 'running', 'paused', 'stopped'] as StatusFilter[]).map((item) => <button key={item} type="button" onClick={() => setStatus(item)} className={`rounded px-3 py-1.5 text-[11px] ${status === item ? 'bg-blue-600 text-white' : 'text-gray-500 hover:bg-slate-800 hover:text-gray-300'}`}>{item === 'all' ? '全部' : statusLabel[item]} <span className="ml-1 font-mono opacity-70">{counts[item]}</span></button>)}</div><label className="relative block w-full lg:w-72"><Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-gray-600" /><input aria-label="搜索模拟实例" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="名称或实例 ID" className="w-full rounded-md border border-crypto-border bg-crypto-bg py-2 pl-9 pr-3 text-xs text-gray-200 outline-none focus:border-blue-500" /></label></div>
        {loading && <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }, (_, index) => <div key={index} className="h-56 animate-pulse rounded-xl border border-crypto-border bg-crypto-card" />)}</div>}
        {!loading && error && <div className="rounded-xl border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200"><div className="flex items-center gap-2 font-semibold"><AlertTriangle className="h-4 w-4" />模拟盘不可用</div><div className="mt-1 text-xs text-red-200/70">{error}</div></div>}
        {!loading && !error && visible.length > 0 && <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{visible.map((item) => <InstanceCard key={item.id} item={item} onOpen={() => void open(item.id)} />)}</div>}
        {!loading && !error && visible.length === 0 && <EmptyBlock>没有符合筛选条件的模拟实例</EmptyBlock>}
        {detailLoading && <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60"><div className="flex items-center gap-2 rounded-lg border border-crypto-border bg-slate-950 px-4 py-3 text-xs text-gray-300"><RefreshCw className="h-4 w-4 animate-spin" />读取实例账本…</div></div>}
      </main>
      {showCreate && <CreateDialog runs={runs} onClose={() => setShowCreate(false)} onCreated={(created) => { setShowCreate(false); setDetail(created); void load(true) }} />}
    </div>
  )
}
