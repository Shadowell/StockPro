import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Activity, Boxes, Database, FlaskConical, GitCompareArrows, RefreshCw, Sigma, Table2 } from 'lucide-react'
import { researchApi } from '../api/client'
import type { FactorLibraryRecord, FactorMetricRecord } from '../types/research'


type FactorTab = 'metrics' | 'runs' | 'correlations' | 'snapshots' | 'values'

const metricText = (value: number | null | undefined) => value == null ? '—' : Number(value).toFixed(4)


export default function FactorLab() {
  const [library, setLibrary] = useState<FactorLibraryRecord[]>([])
  const [selectedCode, setSelectedCode] = useState('')
  const [metrics, setMetrics] = useState<FactorMetricRecord[]>([])
  const [runs, setRuns] = useState<Record<string, any>[]>([])
  const [correlations, setCorrelations] = useState<Record<string, any>[]>([])
  const [snapshots, setSnapshots] = useState<Record<string, any>[]>([])
  const [values, setValues] = useState<Record<string, unknown>[]>([])
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('all')
  const [tab, setTab] = useState<FactorTab>('metrics')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showCompute, setShowCompute] = useState(false)
  const [computing, setComputing] = useState(false)
  const [computeForm, setComputeForm] = useState({ trade_date: '', dataset_snapshot_id: '', universe_snapshot_id: '' })

  const load = async () => {
    setLoading(true); setError('')
    try {
      const [factors, factorRuns, factorCorrelations, factorSnapshots] = await Promise.all([
        researchApi.factors(), researchApi.factorRuns(100), researchApi.factorCorrelations(500), researchApi.factorSnapshots(50),
      ])
      setLibrary(factors.items); setRuns(factorRuns.items); setCorrelations(factorCorrelations.items); setSnapshots(factorSnapshots.items)
      setSelectedCode((current) => current || factors.items.find((item) => item.last_trade_date)?.factor_code || factors.items[0]?.factor_code || '')
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError?.message || '因子库读取失败')
    } finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [])

  useEffect(() => {
    if (!selectedCode) { setMetrics([]); return }
    researchApi.factorMetrics(selectedCode).then((response) => setMetrics(response.items)).catch(() => setMetrics([]))
  }, [selectedCode])

  useEffect(() => {
    if (tab !== 'values' || !selectedCode) return
    researchApi.factorValues(selectedCode, 500, 0).then((response) => setValues(response.items)).catch(() => setValues([]))
  }, [selectedCode, tab])

  const selected = library.find((item) => item.factor_code === selectedCode) || null
  const categories = useMemo(() => Array.from(new Set(library.map((item) => item.category))).sort(), [library])
  const filtered = useMemo(() => library.filter((item) => {
    const matchesCategory = category === 'all' || item.category === category
    const needle = query.trim().toLowerCase()
    return matchesCategory && (!needle || item.factor_code.toLowerCase().includes(needle) || item.factor_name.toLowerCase().includes(needle))
  }), [category, library, query])

  const latestMetric = (code: string) => [...metrics].reverse().find((item) => item.metric_code === code)

  const compute = async (event: FormEvent) => {
    event.preventDefault(); if (!selected?.active_version_id) return; setComputing(true)
    try {
      await researchApi.computeFactor(selected.active_version_id, { trade_date: computeForm.trade_date, dataset_snapshot_id: Number(computeForm.dataset_snapshot_id), universe_snapshot_id: Number(computeForm.universe_snapshot_id) })
      setShowCompute(false); await load()
    } finally { setComputing(false) }
  }

  return (
    <div className="h-full overflow-y-auto bg-crypto-bg p-4 text-gray-100 sm:p-6">
      <header className="mb-4 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-lg border border-blue-500/25 bg-blue-500/10"><Sigma className="h-5 w-5 text-blue-300" /></div><div><div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-300/80">Factor Research</div><h1 className="mt-0.5 text-xl font-bold text-white">因子库</h1></div></div>
        <button type="button" onClick={() => void load()} className="inline-flex h-9 items-center gap-1.5 self-start rounded-lg border border-crypto-border px-3 text-xs text-gray-400"><RefreshCw className="h-3.5 w-3.5" />刷新只读证据</button>
      </header>

      {error && <div className="mb-4 rounded-xl border border-red-500/25 bg-red-500/10 p-3 text-sm text-red-200">{error}</div>}
      <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
        <aside className="rounded-xl border border-crypto-border bg-crypto-card p-3">
          <input aria-label="搜索因子" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索代码或名称" className="h-9 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-xs outline-none focus:border-blue-500/60" />
          <div className="mt-2 flex gap-1 overflow-x-auto pb-1">{['all', ...categories].map((item) => <button key={item} type="button" onClick={() => setCategory(item)} className={`shrink-0 rounded border px-2 py-1 text-[10px] ${category === item ? 'border-blue-500/35 bg-blue-500/10 text-blue-200' : 'border-crypto-border text-gray-600'}`}>{item === 'all' ? '全部' : item}</button>)}</div>
          <div className="mt-3 max-h-[680px] space-y-2 overflow-y-auto pr-1">{loading ? <div className="py-8 text-center text-xs text-gray-500">读取因子目录…</div> : filtered.map((factor) => <button type="button" key={factor.factor_code} onClick={() => { setSelectedCode(factor.factor_code); setTab('metrics') }} className={`w-full rounded-lg border p-3 text-left ${selectedCode === factor.factor_code ? 'border-blue-500/40 bg-blue-500/10' : 'border-crypto-border bg-crypto-bg/45'}`}><div className="flex items-start justify-between gap-2"><span className="text-xs font-semibold text-gray-100">{factor.factor_name}</span><span className="rounded border border-crypto-border px-1.5 py-0.5 text-[9px] text-gray-500">{factor.category}</span></div><div className="mt-1 font-mono text-[10px] text-gray-600">{factor.factor_code}</div><div className="mt-2 flex justify-between text-[10px] text-gray-600"><span>{factor.research_status}</span><span>{factor.last_trade_date || '未计算'}</span></div></button>)}</div>
        </aside>

        <section className="min-w-0 space-y-4">
          {selected ? <>
            <div className="rounded-xl border border-crypto-border bg-crypto-card p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div><div className="flex flex-wrap items-center gap-2"><h2 className="text-base font-semibold text-white">{selected.factor_name}</h2><span className="rounded border border-crypto-border px-1.5 py-0.5 font-mono text-[10px] text-gray-500">{selected.factor_code}</span><span className="rounded border border-amber-500/25 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-200">{selected.research_status}</span></div><p className="mt-1 text-xs text-gray-500">目录与代码校验不等于经济有效性验证；指标成熟后才可判断。</p></div><button type="button" disabled={!selected.active_version_id} onClick={() => setShowCompute((value) => !value)} className="rounded-lg border border-blue-500/30 px-3 py-2 text-xs text-blue-200 disabled:opacity-40">按封存输入计算</button></div>
              <div className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-4">{[['Coverage', latestMetric('coverage')?.metric_value ?? selected.coverage], ['Rank IC', latestMetric('rank_ic')?.metric_value ?? selected.rank_ic], ['ICIR', latestMetric('icir')?.metric_value ?? selected.icir], ['Long-short', latestMetric('long_short_return')?.metric_value ?? selected.long_short_return]].map(([label,value]) => <div key={String(label)} className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3"><div className="text-[10px] text-gray-600">{label}</div><div className="mt-2 font-mono text-lg font-semibold text-gray-200">{metricText(value as number | null | undefined)}</div></div>)}</div>
            </div>

            {showCompute && <form onSubmit={compute} className="grid gap-3 rounded-xl border border-blue-500/25 bg-crypto-card p-4 sm:grid-cols-3">{[['trade_date','交易日'],['dataset_snapshot_id','Dataset snapshot ID'],['universe_snapshot_id','Universe snapshot ID']].map(([key,label]) => <label key={key} className="text-[11px] text-gray-500">{label}<input required type={key === 'trade_date' ? 'date' : 'number'} value={computeForm[key as keyof typeof computeForm]} onChange={(e) => setComputeForm({ ...computeForm, [key]: e.target.value })} className="mt-1 h-9 w-full rounded-lg border border-crypto-border bg-crypto-bg px-2 text-xs text-gray-200" /></label>)}<button disabled={computing} className="h-9 rounded-lg bg-blue-600 text-xs font-semibold sm:col-span-3">运行封存快照计算</button></form>}

            <div className="flex overflow-x-auto rounded-lg border border-crypto-border bg-crypto-card p-1">{([['metrics','指标诊断',Activity],['runs','运行记录',FlaskConical],['correlations','相关性',GitCompareArrows],['snapshots','封存快照',Database],['values','值浏览',Table2]] as const).map(([id,label,Icon]) => <button key={id} type="button" onClick={() => setTab(id)} className={`inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md px-3 text-xs ${tab === id ? 'bg-blue-500/15 text-blue-200' : 'text-gray-500'}`}><Icon className="h-3.5 w-3.5" />{label}</button>)}</div>

            {tab === 'metrics' && <div className="rounded-xl border border-crypto-border bg-crypto-card p-4"><div className="mb-3 flex items-center gap-2"><Activity className="h-4 w-4 text-blue-300" /><h2 className="text-sm font-semibold">指标诊断</h2></div>{metrics.length ? <div className="overflow-x-auto rounded-lg border border-crypto-border"><table className="min-w-full text-xs"><thead className="bg-crypto-bg/80 text-left text-[10px] text-gray-500"><tr><th className="px-3 py-2">指标</th><th className="px-3 py-2">Horizon</th><th className="px-3 py-2">值</th><th className="px-3 py-2">状态/原因</th></tr></thead><tbody className="divide-y divide-crypto-border/70">{metrics.map((metric,index) => <tr key={`${metric.compute_run_id || 0}-${metric.metric_code}-${metric.horizon || 0}-${index}`}><td className="px-3 py-2 font-mono text-gray-300">{metric.metric_code}</td><td className="px-3 py-2 text-gray-500">{metric.horizon ?? '—'}</td><td className="px-3 py-2 font-mono text-gray-200">{metricText(metric.metric_value)}</td><td className="px-3 py-2 text-gray-500">{metric.metric_value == null ? metric.pending_reason || '不可用' : 'published'}</td></tr>)}</tbody></table></div> : <div className="rounded-lg border border-dashed border-crypto-border py-8 text-center text-xs text-gray-500">当前因子没有 published run 指标</div>}</div>}

            {tab === 'runs' && <DataTable title="运行记录" icon={FlaskConical} items={runs} columns={['factor_code','trade_date','status','dataset_snapshot_id','universe_snapshot_id']} />}
            {tab === 'correlations' && <DataTable title="相关性" icon={GitCompareArrows} items={correlations} columns={['trade_date','factor_code_a','factor_code_b','correlation','window_days']} />}
            {tab === 'snapshots' && <DataTable title="封存快照" icon={Database} items={snapshots} columns={['id','trade_date','status','factor_count','manifest_hash']} />}
            {tab === 'values' && <DataTable title="值浏览" icon={Table2} items={values} columns={['trade_date','symbol','name','processed_value','rank','quantile']} />}
          </> : <div className="rounded-xl border border-dashed border-crypto-border bg-crypto-card/50 p-12 text-center text-sm text-gray-500"><Boxes className="mx-auto mb-3 h-7 w-7" />选择因子查看运行与证据</div>}
        </section>
      </div>
    </div>
  )
}


function DataTable({ title, icon: Icon, items, columns }: { title: string; icon: typeof Database; items: Record<string, any>[]; columns: string[] }) {
  return <div className="rounded-xl border border-crypto-border bg-crypto-card p-4"><div className="mb-3 flex items-center gap-2"><Icon className="h-4 w-4 text-blue-300" /><h2 className="text-sm font-semibold">{title}</h2></div>{items.length ? <div className="overflow-x-auto rounded-lg border border-crypto-border"><table className="min-w-full text-xs"><thead className="bg-crypto-bg/80 text-left text-[10px] text-gray-500"><tr>{columns.map((column) => <th key={column} className="px-3 py-2">{column}</th>)}</tr></thead><tbody className="divide-y divide-crypto-border/70">{items.slice(0,500).map((item,index) => <tr key={String(item.id || item.compute_run_id || index)}>{columns.map((column) => <td key={column} className="max-w-[240px] truncate px-3 py-2 font-mono text-gray-400" title={String(item[column] ?? '')}>{item[column] == null ? '—' : String(item[column])}</td>)}</tr>)}</tbody></table></div> : <div className="rounded-lg border border-dashed border-crypto-border py-8 text-center text-xs text-gray-500">暂无{title}</div>}</div>
}
