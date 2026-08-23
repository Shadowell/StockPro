import { FormEvent, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Activity, BarChart3, FlaskConical, Grid3X3, ListChecks, Plus, RefreshCw, RotateCcw, ShieldCheck, Square, X } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { backtestCurrentApi } from '../api/client'
import type { BacktestConfiguration, BacktestJobRecord, BacktestRunRecord } from '../types/backtest'


const metric = (run: BacktestRunRecord, code: string) => run.metrics?.[code]
const percent = (value: number | null | undefined) => value == null ? '—' : `${(Number(value) * 100).toFixed(2)}%`


export default function Backtest() {
  const [searchParams] = useSearchParams()
  const [runs, setRuns] = useState<BacktestRunRecord[]>([])
  const [jobs, setJobs] = useState<BacktestJobRecord[]>([])
  const [configuration, setConfiguration] = useState<BacktestConfiguration | null>(null)
  const [status, setStatus] = useState('all')
  const [showWizard, setShowWizard] = useState(false)
  const [showMatrix, setShowMatrix] = useState(false)
  const [showWalk, setShowWalk] = useState(false)
  const [selectedRun, setSelectedRun] = useState<Record<string, any> | null>(null)
  const [detailTab, setDetailTab] = useState('metrics')
  const [detailRows, setDetailRows] = useState<Record<string, any>[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [form, setForm] = useState({ mode: 'quick', name: '', strategy_version_id: searchParams.get('strategy_version_id') || '', dataset_snapshot_id: '', universe_snapshot_id: '', factor_snapshot_id: '', pool_snapshot_id: '', cost_model_id: '', research_protocol_id: '', start_date: '', end_date: '', initial_cash: '1000000' })

  const load = async () => {
    setLoading(true); setError('')
    try {
      const [runResponse, jobResponse, config] = await Promise.all([backtestCurrentApi.runs(200), backtestCurrentApi.jobs(200), backtestCurrentApi.configuration()])
      setRuns(runResponse.items); setJobs(jobResponse.items); setConfiguration(config)
      setForm((current) => ({ ...current, strategy_version_id: current.strategy_version_id || String(config.strategy_versions[0]?.id || ''), dataset_snapshot_id: current.dataset_snapshot_id || String(config.dataset_snapshots[0]?.id || ''), universe_snapshot_id: current.universe_snapshot_id || String(config.universe_snapshots[0]?.id || ''), cost_model_id: current.cost_model_id || String(config.cost_models[0]?.id || ''), research_protocol_id: current.research_protocol_id || String(config.protocols[0]?.id || '') }))
    } catch (requestError: any) { setError(requestError?.response?.data?.detail || requestError?.message || '回测控制台读取失败') }
    finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [])

  const filtered = useMemo(() => runs.filter((run) => status === 'all' || run.status === status || run.run_mode === status), [runs, status])
  const successCount = runs.filter((run) => run.status === 'success').length
  const fullCount = runs.filter((run) => run.run_mode === 'full').length

  const openRun = async (runId: string) => {
    setSelectedRun(await backtestCurrentApi.run(runId)); setDetailTab('metrics'); setDetailRows((await backtestCurrentApi.metrics(runId)).items)
  }

  const changeDetailTab = async (tab: string) => {
    if (!selectedRun) return; setDetailTab(tab)
    if (tab === 'metrics') setDetailRows((await backtestCurrentApi.metrics(String(selectedRun.id))).items)
    else if (['orders','trades','positions','logs'].includes(tab)) setDetailRows((await backtestCurrentApi.detailRows(String(selectedRun.id), tab as 'orders' | 'trades' | 'positions' | 'logs')).items)
    else setDetailRows([])
  }

  const createJob = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true)
    const payload = Object.fromEntries(Object.entries(form).filter(([, value]) => value !== '').map(([key, value]) => [key, key.endsWith('_snapshot_id') || key === 'initial_cash' ? Number(value) : value]))
    try { await backtestCurrentApi.createJob({ ...payload, symbols: [], parameters: {} }); setShowWizard(false); await load() }
    finally { setSaving(false) }
  }

  return (
    <div className="h-full overflow-y-auto bg-crypto-bg p-4 text-gray-100 sm:p-6">
      <header className="mb-4 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-lg border border-blue-500/25 bg-blue-500/10"><FlaskConical className="h-5 w-5 text-blue-300" /></div><div><div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-300/80">Evidence Workbench</div><h1 className="mt-0.5 text-xl font-bold text-white">回测控制台</h1></div></div><div className="flex flex-wrap gap-2"><button type="button" onClick={() => void load()} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-crypto-border px-3 text-xs text-gray-400"><RefreshCw className="h-3.5 w-3.5" />刷新</button><button type="button" onClick={() => setShowMatrix((value) => !value)} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-crypto-border px-3 text-xs text-gray-300"><Grid3X3 className="h-3.5 w-3.5" />参数矩阵</button><button type="button" onClick={() => setShowWalk((value) => !value)} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-crypto-border px-3 text-xs text-gray-300"><RotateCcw className="h-3.5 w-3.5" />Walk-forward</button><button type="button" onClick={() => setShowWizard(true)} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-blue-500/35 bg-blue-500/10 px-3 text-xs text-blue-200"><Plus className="h-3.5 w-3.5" />创建回测实例</button></div></header>

      <div className="mb-4 grid grid-cols-2 gap-3 xl:grid-cols-4">{[['历史 Runs', runs.length], ['成功', successCount], ['完整协议', fullCount], ['Jobs', jobs.length]].map(([label,value]) => <div key={String(label)} className="rounded-xl border border-crypto-border bg-crypto-card p-3"><div className="text-[10px] text-gray-600">{label}</div><div className="mt-1 font-mono text-xl font-semibold text-gray-100">{value}</div></div>)}</div>
      {showMatrix && <ModeNotice title="参数矩阵" detail="1-24 个组合；所有 cell 仅用于诊断，promotion_status 固定 not_evaluated。" />}
      {showWalk && <ModeNotice title="Walk-forward" detail="训练/样本外折叠用于稳健性诊断，fold promotion_eligible 固定 false。" />}
      {error && <div className="mb-4 rounded-xl border border-red-500/25 bg-red-500/10 p-3 text-sm text-red-200">{error}</div>}

      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_380px]">
        <section className="min-w-0 rounded-xl border border-crypto-border bg-crypto-card p-4"><div className="mb-3 flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><BarChart3 className="h-4 w-4 text-blue-300" /><h2 className="text-sm font-semibold">回测历史</h2></div><select aria-label="回测筛选" value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 rounded-lg border border-crypto-border bg-crypto-bg px-2 text-xs"><option value="all">全部</option><option value="success">成功</option><option value="failed">失败</option><option value="quick">快速</option><option value="full">完整</option></select></div>{loading ? <div className="h-64 animate-pulse rounded-lg bg-crypto-bg" /> : <div data-testid="backtest-history-table" className="overflow-x-auto rounded-lg border border-crypto-border"><table className="min-w-[980px] w-full text-left text-xs"><thead className="bg-crypto-bg/80 text-[10px] text-gray-500"><tr><th className="px-3 py-2">名称/策略</th><th className="px-3 py-2">区间</th><th className="px-3 py-2">模式</th><th className="px-3 py-2">收益</th><th className="px-3 py-2">Sharpe</th><th className="px-3 py-2">回撤</th><th className="px-3 py-2">晋级</th><th className="px-3 py-2">状态</th></tr></thead><tbody className="divide-y divide-crypto-border/70">{filtered.map((run) => <tr key={run.id} onClick={() => void openRun(run.id)} className="cursor-pointer hover:bg-white/[0.03]"><td className="px-3 py-2"><div className="font-semibold text-gray-200">{run.name}</div><div className="text-[10px] text-gray-600">{run.strategy_name} v{run.strategy_version}</div></td><td className="px-3 py-2 font-mono text-[10px] text-gray-500">{run.start_date}<br />{run.end_date}</td><td className="px-3 py-2"><span className="rounded border border-crypto-border px-1.5 py-0.5 text-[10px]">{run.run_mode}</span></td><td className="px-3 py-2 font-mono text-gray-300">{percent(metric(run,'strategy_return'))}</td><td className="px-3 py-2 font-mono text-gray-300">{metric(run,'sharpe')?.toFixed?.(2) ?? '—'}</td><td className="px-3 py-2 font-mono text-down">{percent(metric(run,'maximum_drawdown'))}</td><td className="px-3 py-2 text-[10px] text-amber-200">{run.promotion_status}</td><td className="px-3 py-2 text-[10px] text-gray-400">{run.status}</td></tr>)}</tbody></table></div>}</section>

        <aside className="rounded-xl border border-crypto-border bg-crypto-card p-4"><div className="mb-3 flex items-center gap-2"><ListChecks className="h-4 w-4 text-cyan-300" /><h2 className="text-sm font-semibold">任务队列</h2></div>{jobs.length ? <div className="space-y-2">{jobs.slice(0,20).map((job) => <div key={job.job_id} className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3"><div className="flex items-center justify-between"><span className="font-mono text-[10px] text-gray-500">{job.job_id.slice(0,8)}</span><span className="text-[10px] text-gray-300">{job.status}</span></div><div className="mt-2 h-1.5 overflow-hidden rounded bg-gray-800"><div className="h-full bg-blue-500" style={{ width: `${Math.max(0,Math.min(100,job.progress || 0))}%` }} /></div><div className="mt-2 text-[11px] text-gray-500">{job.message || job.phase}</div>{['running','pending','cancelling'].includes(job.status) && <button type="button" onClick={() => void backtestCurrentApi.cancelJob(job.job_id).then(load)} className="mt-2 inline-flex items-center gap-1 text-[10px] text-red-300"><Square className="h-3 w-3" />停止</button>}</div>)}</div> : <div className="rounded-lg border border-dashed border-crypto-border py-8 text-center text-xs text-gray-500">当前没有任务</div>}</aside>
      </div>

      {showWizard && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-4"><form onSubmit={createJob} className="max-h-[92vh] w-full max-w-4xl overflow-y-auto rounded-2xl border border-crypto-border bg-crypto-card p-5"><div className="flex items-start justify-between"><div><h2 className="text-lg font-semibold">创建回测实例</h2><p className="mt-1 text-xs text-gray-500">所有输入绑定不可变 ID 与 hash。</p></div><button type="button" aria-label="关闭回测向导" onClick={() => setShowWizard(false)}><X className="h-4 w-4" /></button></div><div className="mt-4 grid grid-cols-3 gap-2">{['选择策略','配置参数','确认运行'].map((step,index) => <div key={step} className="rounded-lg border border-blue-500/25 bg-blue-500/5 p-3"><div className="text-[10px] text-blue-400">STEP {index+1}</div><div className="mt-1 text-xs font-semibold">{step}</div></div>)}</div><div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3"><Field label="实例名称"><input required value={form.name} onChange={(e) => setForm({...form,name:e.target.value})} className="mt-1 h-9 w-full rounded-lg border border-crypto-border bg-crypto-bg px-2 text-xs text-gray-200" /></Field><SelectField label="策略版本" value={form.strategy_version_id} onChange={(value) => setForm({...form,strategy_version_id:value})} items={configuration?.strategy_versions || []} /><SelectField label="Dataset snapshot" value={form.dataset_snapshot_id} onChange={(value) => setForm({...form,dataset_snapshot_id:value})} items={configuration?.dataset_snapshots || []} /><SelectField label="Universe snapshot" value={form.universe_snapshot_id} onChange={(value) => setForm({...form,universe_snapshot_id:value})} items={configuration?.universe_snapshots || []} /><SelectField label="Pool snapshot" value={form.pool_snapshot_id} onChange={(value) => setForm({...form,pool_snapshot_id:value})} items={configuration?.pool_snapshots || []} optional /><SelectField label="Factor snapshot" value={form.factor_snapshot_id} onChange={(value) => setForm({...form,factor_snapshot_id:value})} items={configuration?.factor_snapshots || []} optional /><SelectField label="成本模型" value={form.cost_model_id} onChange={(value) => setForm({...form,cost_model_id:value})} items={configuration?.cost_models || []} /><SelectField label="研究协议" value={form.research_protocol_id} onChange={(value) => setForm({...form,research_protocol_id:value})} items={configuration?.protocols || []} optional /><Field label="初始资金 CNY"><input type="number" value={form.initial_cash} onChange={(e) => setForm({...form,initial_cash:e.target.value})} className="mt-1 h-9 w-full rounded-lg border border-crypto-border bg-crypto-bg px-2 text-xs text-gray-200" /></Field><Field label="开始日期"><input required type="date" value={form.start_date} onChange={(e) => setForm({...form,start_date:e.target.value})} className="mt-1 h-9 w-full rounded-lg border border-crypto-border bg-crypto-bg px-2 text-xs text-gray-200" /></Field><Field label="结束日期"><input required type="date" value={form.end_date} onChange={(e) => setForm({...form,end_date:e.target.value})} className="mt-1 h-9 w-full rounded-lg border border-crypto-border bg-crypto-bg px-2 text-xs text-gray-200" /></Field><Field label="运行模式"><select value={form.mode} onChange={(e) => setForm({...form,mode:e.target.value})} className="mt-1 h-9 w-full rounded-lg border border-crypto-border bg-crypto-bg px-2 text-xs text-gray-200"><option value="quick">快速预检</option><option value="full">完整协议</option></select></Field></div><div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">{[['交易规则','T+1'],['最小委托','100股'],['方向','只做多'],['诊断晋级','不可晋级']].map(([label,value]) => <div key={label} className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3"><div className="text-[10px] text-gray-600">{label}</div><div className="mt-1 font-mono text-xs text-gray-200">{value}</div></div>)}</div><div className="mt-4 flex items-start gap-2 rounded-lg border border-amber-500/25 bg-amber-500/5 p-3 text-xs text-amber-100"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />快速预检不可晋级；完整模式仍须逐项通过研究协议、成本、容量、样本外和数据质量。</div><button disabled={saving} className="mt-4 w-full rounded-lg bg-blue-600 py-3 text-sm font-semibold disabled:opacity-50">确认创建任务</button></form></div>}

      {selectedRun && <div className="fixed inset-0 z-50 flex justify-end bg-black/65"><div className="h-full w-full max-w-5xl overflow-y-auto border-l border-crypto-border bg-crypto-card p-5"><div className="flex items-start justify-between"><div><h2 className="text-lg font-semibold">{selectedRun.name}</h2><p className="mt-1 text-xs text-gray-500">{selectedRun.strategy_name} · {selectedRun.start_date} → {selectedRun.end_date}</p></div><button aria-label="关闭回测详情" onClick={() => setSelectedRun(null)}><X className="h-4 w-4" /></button></div><div className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-4">{[['状态',selectedRun.status],['模式',selectedRun.run_mode],['晋级',selectedRun.promotion_status],['Input hash',selectedRun.input_hash]].map(([label,value]) => <div key={String(label)} className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3"><div className="text-[10px] text-gray-600">{label}</div><div className="mt-1 truncate font-mono text-xs">{String(value ?? '—')}</div></div>)}</div><div className="mt-4 flex overflow-x-auto rounded-lg border border-crypto-border p-1">{['metrics','series','orders','trades','positions','logs'].map((item) => <button key={item} onClick={() => void changeDetailTab(item)} className={`rounded-md px-3 py-2 text-xs ${detailTab===item?'bg-blue-500/15 text-blue-200':'text-gray-500'}`}>{item}</button>)}</div><div className="mt-4 rounded-xl border border-crypto-border p-4"><h3 className="mb-3 text-sm font-semibold">{detailTab}</h3>{detailTab==='series'?<div className="text-xs text-gray-500">权益曲线按需读取；当前切换到 series 时显示。</div>:<pre className="max-h-[620px] overflow-auto rounded-lg bg-crypto-bg p-3 text-[11px] leading-5 text-gray-400">{JSON.stringify(detailRows,null,2)}</pre>}</div></div></div>}
    </div>
  )
}

function ModeNotice({ title, detail }: { title: string; detail: string }) { return <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-100"><Activity className="mt-0.5 h-4 w-4 shrink-0" /><span><strong>{title}：</strong>{detail}</span></div> }
function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="text-[11px] text-gray-500">{label}{children}</label> }
function SelectField({ label, value, onChange, items, optional=false }: { label: string; value: string; onChange: (value:string)=>void; items: Record<string,any>[]; optional?: boolean }) { return <Field label={label}><select required={!optional} value={value} onChange={(e)=>onChange(e.target.value)} className="mt-1 h-9 w-full rounded-lg border border-crypto-border bg-crypto-bg px-2 text-xs text-gray-200"><option value="">{optional?'不绑定':'请选择'}</option>{items.map((item)=><option key={String(item.id)} value={String(item.id)}>{String(item.name || item.code || item.id)}</option>)}</select></Field> }
