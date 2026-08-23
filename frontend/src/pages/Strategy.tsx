import { FormEvent, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, ChevronLeft, ChevronRight, Code2, FlaskConical, Plus, RefreshCw, Search, ShieldCheck, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { strategyCurrentApi } from '../api/client'
import StrategyParameterSections from '../components/StrategyParameterSections'
import type { StrategyValidationResult, StrategyVersionRecord } from '../types/strategy'


const PAGE_SIZE = 12
const DEFAULT_CODE = `def initialize(context):
    context.parameters["lookback"] = 20

def handle_data(context, data):
    pass
`


export default function Strategy() {
  const navigate = useNavigate()
  const [items, setItems] = useState<StrategyVersionRecord[]>([])
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<StrategyVersionRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [editingVersion, setEditingVersion] = useState(false)
  const [saving, setSaving] = useState(false)
  const [validation, setValidation] = useState<StrategyValidationResult | null>(null)
  const [form, setForm] = useState({ name: '', description: '', script_content: DEFAULT_CODE })

  const load = async () => {
    setLoading(true); setError('')
    try { setItems((await strategyCurrentApi.list()).items) }
    catch (requestError: any) { setError(requestError?.response?.data?.detail || requestError?.message || '策略目录读取失败') }
    finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [])

  const filtered = useMemo(() => items.filter((item) => {
    const needle = query.trim().toLowerCase()
    const matchesText = !needle || item.name.toLowerCase().includes(needle) || item.description?.toLowerCase().includes(needle)
    const matchesStatus = status === 'all' || item.validation_status === status || item.status === status
    return matchesText && matchesStatus
  }), [items, query, status])
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const visible = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  useEffect(() => setPage(1), [query, status])

  const openDetail = async (versionId: string) => {
    setError('')
    try { setSelected(await strategyCurrentApi.detail(versionId)); setEditingVersion(false); setValidation(null) }
    catch (requestError: any) { setError(requestError?.response?.data?.detail || requestError?.message || '策略详情读取失败') }
  }

  const validateCode = async (script = selected?.script_content || form.script_content) => {
    setValidation(await strategyCurrentApi.validate(script))
  }

  const create = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true)
    try { const result = await strategyCurrentApi.create(form); setShowCreate(false); await load(); await openDetail(result.strategy_version.id) }
    finally { setSaving(false) }
  }

  const createVersion = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!selected) return
    const data = new FormData(event.currentTarget); setSaving(true)
    try { const result = await strategyCurrentApi.createVersion(selected.id, { description: String(data.get('description') || selected.description), script_content: String(data.get('script_content') || '') }); await load(); await openDetail(result.strategy_version.id) }
    finally { setSaving(false) }
  }

  return (
    <div className="h-full overflow-y-auto bg-crypto-bg p-4 text-gray-100 sm:p-6">
      <header className="mb-4 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-lg border border-blue-500/25 bg-blue-500/10"><Code2 className="h-5 w-5 text-blue-300" /></div><div><div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-300/80">Strategy Catalogue</div><h1 className="mt-0.5 text-xl font-bold text-white">策略中心</h1></div></div>
        <div className="flex gap-2"><button type="button" onClick={() => void load()} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-crypto-border px-3 text-xs text-gray-400"><RefreshCw className="h-3.5 w-3.5" />刷新</button><button type="button" onClick={() => setShowCreate((value) => !value)} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-blue-500/35 bg-blue-500/10 px-3 text-xs text-blue-200"><Plus className="h-3.5 w-3.5" />创建策略</button></div>
      </header>

      {showCreate && <form onSubmit={create} className="mb-4 grid gap-3 rounded-xl border border-blue-500/25 bg-crypto-card p-4 lg:grid-cols-2"><input required aria-label="策略名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="策略名称" className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm" /><input aria-label="策略描述" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="描述" className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm" /><textarea aria-label="策略代码" value={form.script_content} onChange={(e) => setForm({ ...form, script_content: e.target.value })} className="min-h-56 rounded-lg border border-crypto-border bg-crypto-bg p-3 font-mono text-xs leading-5 lg:col-span-2" /><div className="flex gap-2 lg:col-span-2"><button type="button" onClick={() => void validateCode(form.script_content)} className="rounded-lg border border-crypto-border px-3 py-2 text-xs">验证代码</button><button disabled={saving} className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold">保存不可变 v1</button></div>{validation && <ValidationPanel result={validation} />}</form>}

      <section className="mb-4 grid gap-3 rounded-xl border border-crypto-border bg-crypto-card p-3 md:grid-cols-[minmax(0,1fr)_180px]">
        <label className="relative"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-600" /><input aria-label="搜索策略" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索名称或描述" className="h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg pl-9 pr-3 text-sm outline-none focus:border-blue-500/60" /></label>
        <select aria-label="策略状态" value={status} onChange={(e) => setStatus(e.target.value)} className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm"><option value="all">全部状态</option><option value="valid">代码有效</option><option value="invalid">代码无效</option><option value="pending">待验证</option><option value="draft">草稿</option></select>
      </section>

      {error && <div className="mb-4 rounded-xl border border-red-500/25 bg-red-500/10 p-3 text-sm text-red-200">{error}</div>}
      {loading ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }, (_, index) => <div key={index} className="h-48 animate-pulse rounded-xl border border-crypto-border bg-crypto-card" />)}</div> : visible.length ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{visible.map((item) => <article key={item.id} data-testid="strategy-card" className="flex min-h-52 flex-col rounded-xl border border-crypto-border bg-crypto-card p-4"><div className="flex items-start justify-between gap-3"><div><h2 className="text-sm font-semibold text-gray-100">{item.name}</h2><div className="mt-1 font-mono text-[10px] text-gray-600">v{item.version} · {item.id.slice(0, 8)}</div></div><span className={`rounded border px-1.5 py-0.5 text-[10px] ${item.validation_status === 'valid' ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300' : item.validation_status === 'invalid' ? 'border-red-500/25 bg-red-500/10 text-red-300' : 'border-amber-500/25 bg-amber-500/10 text-amber-200'}`}>{item.validation_status === 'valid' ? '代码有效' : item.validation_status === 'invalid' ? '代码无效' : '待验证'}</span></div><p className="mt-3 line-clamp-3 text-xs leading-5 text-gray-500">{item.description || '无描述'}</p><div className="mt-3 grid grid-cols-2 gap-2 text-[10px]"><div className="rounded border border-crypto-border bg-crypto-bg/50 p-2"><div className="text-gray-600">数据依赖</div><div className="mt-1 truncate text-gray-300">{item.data_dependencies?.join(', ') || '—'}</div></div><div className="rounded border border-crypto-border bg-crypto-bg/50 p-2"><div className="text-gray-600">内容哈希</div><div className="mt-1 truncate font-mono text-gray-300">{item.content_hash}</div></div></div><div className="mt-auto flex gap-2 pt-4"><button type="button" onClick={() => void openDetail(item.id)} className="flex-1 rounded-lg border border-crypto-border py-2 text-xs text-gray-300 hover:border-blue-500/35">详情</button><button type="button" onClick={() => navigate(`/backtest?strategy_version_id=${encodeURIComponent(item.id)}`)} className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 py-2 text-xs text-blue-200"><FlaskConical className="h-3.5 w-3.5" />回测</button></div></article>)}</div>
      ) : <div className="rounded-xl border border-dashed border-crypto-border bg-crypto-card/50 py-12 text-center text-sm text-gray-500">没有匹配策略</div>}

      <div className="mt-4 flex items-center justify-between text-xs text-gray-500"><span>{filtered.length} 个策略 · 第 {page}/{pageCount} 页</span><div className="flex gap-1"><button type="button" aria-label="上一页" disabled={page <= 1} onClick={() => setPage((value) => value - 1)} className="rounded border border-crypto-border p-2 disabled:opacity-30"><ChevronLeft className="h-4 w-4" /></button><button type="button" aria-label="下一页" disabled={page >= pageCount} onClick={() => setPage((value) => value + 1)} className="rounded border border-crypto-border p-2 disabled:opacity-30"><ChevronRight className="h-4 w-4" /></button></div></div>

      {selected && <div className="fixed inset-0 z-50 flex justify-end bg-black/65"><div className="h-full w-full max-w-4xl overflow-y-auto border-l border-crypto-border bg-crypto-card p-5"><div className="flex items-start justify-between gap-3"><div><div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold text-white">{selected.name}</h2><span className="rounded border border-crypto-border px-1.5 py-0.5 font-mono text-[10px] text-gray-500">v{selected.version}</span></div><p className="mt-1 text-xs text-gray-500">{selected.description || '无描述'}</p></div><button type="button" aria-label="关闭策略详情" onClick={() => setSelected(null)} className="rounded p-2 text-gray-500 hover:bg-white/5"><X className="h-4 w-4" /></button></div><div className="mt-5 flex flex-wrap gap-2"><span className="rounded border border-blue-500/25 bg-blue-500/10 px-2 py-1 text-[10px] text-blue-200">不可变版本</span><span className="rounded border border-crypto-border px-2 py-1 font-mono text-[10px] text-gray-500">{selected.content_hash}</span></div><div className="mt-5"><h3 className="mb-3 text-sm font-semibold">封存输入</h3><StrategyParameterSections parameterSchema={selected.parameter_schema || {}} dependencyManifest={selected.dependency_manifest || {}} /></div><div className="mt-5 rounded-xl border border-crypto-border p-4"><div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-semibold">策略代码</h3><div className="flex gap-2"><button type="button" onClick={() => void validateCode()} className="inline-flex items-center gap-1.5 rounded-lg border border-crypto-border px-3 py-2 text-xs"><CheckCircle2 className="h-3.5 w-3.5" />验证</button><button type="button" onClick={() => setEditingVersion((value) => !value)} className="rounded-lg border border-blue-500/30 px-3 py-2 text-xs text-blue-200">创建子版本</button></div></div>{editingVersion ? <form onSubmit={createVersion}><input name="description" defaultValue={selected.description} className="mb-2 h-9 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-xs" /><textarea required name="script_content" defaultValue={selected.script_content} className="min-h-72 w-full rounded-lg border border-crypto-border bg-crypto-bg p-3 font-mono text-xs leading-5" /><button disabled={saving} className="mt-2 rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold">保存新版本</button></form> : <pre className="max-h-[480px] overflow-auto rounded-lg bg-crypto-bg p-3 text-xs leading-5 text-gray-400">{selected.script_content}</pre>}{validation && <ValidationPanel result={validation} />}</div><div className="mt-5 flex items-start gap-2 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3 text-xs leading-5 text-amber-100"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />快速预检不可晋级；只有绑定封存输入并通过完整研究协议的回测可以申请模拟。</div></div></div>}
    </div>
  )
}


function ValidationPanel({ result }: { result: StrategyValidationResult }) {
  return <div className={`mt-3 rounded-lg border p-3 text-xs lg:col-span-2 ${result.valid ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200' : 'border-red-500/25 bg-red-500/10 text-red-200'}`}><div className="font-semibold">{result.valid ? '代码验证通过' : '代码验证失败'}</div>{result.issues.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-4">{result.issues.map((issue, index) => <li key={`${issue.code}-${index}`}>{issue.line ? `L${issue.line} ` : ''}{issue.message}</li>)}</ul>}</div>
}
