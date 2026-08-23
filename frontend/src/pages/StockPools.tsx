import { FormEvent, useEffect, useState } from 'react'
import { Archive, Database, Filter, Plus, RefreshCw, ShieldCheck, Users } from 'lucide-react'
import { researchApi } from '../api/client'
import type { StockPoolMember, StockPoolRecord, StockPoolSnapshot } from '../types/research'


export default function StockPools() {
  const [pools, setPools] = useState<StockPoolRecord[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState<StockPoolRecord | null>(null)
  const [members, setMembers] = useState<StockPoolMember[]>([])
  const [snapshots, setSnapshots] = useState<StockPoolSnapshot[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [showGenerate, setShowGenerate] = useState(false)
  const [saving, setSaving] = useState(false)
  const [createForm, setCreateForm] = useState({ name: '', pool_type: 'screener', description: '' })
  const [generateForm, setGenerateForm] = useState({ trade_date: '', dataset_snapshot_id: '', universe_snapshot_id: '', factor_snapshot_id: '', market_evidence_snapshot_id: '' })

  const loadPools = async () => {
    setLoading(true)
    setError('')
    try {
      const response = await researchApi.pools()
      setPools(response.items)
      setSelectedId((current) => current || response.items[0]?.id || '')
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError?.message || '股票池目录读取失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadPools() }, [])

  useEffect(() => {
    if (!selectedId) {
      setDetail(null); setMembers([]); setSnapshots([]); return
    }
    let cancelled = false
    Promise.all([
      researchApi.pool(selectedId),
      researchApi.poolMembers(selectedId),
      researchApi.poolSnapshots(selectedId),
    ]).then(([pool, memberResponse, snapshotResponse]) => {
      if (cancelled) return
      setDetail(pool)
      setMembers(memberResponse.items)
      setSnapshots(snapshotResponse.items)
    }).catch((requestError: any) => {
      if (!cancelled) setError(requestError?.response?.data?.detail || requestError?.message || '股票池详情读取失败')
    })
    return () => { cancelled = true }
  }, [selectedId])

  const createPool = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true)
    try {
      const created = await researchApi.createPool({ ...createForm, config: {} })
      setShowCreate(false); setCreateForm({ name: '', pool_type: 'screener', description: '' })
      await loadPools(); setSelectedId(created.id)
    } finally { setSaving(false) }
  }

  const generate = async (event: FormEvent) => {
    event.preventDefault(); if (!detail) return; setSaving(true)
    const payload = Object.fromEntries(Object.entries(generateForm).filter(([, value]) => value !== '').map(([key, value]) => [key, key.endsWith('_id') ? Number(value) : value]))
    try {
      await researchApi.generatePool(detail.id, payload)
      setShowGenerate(false)
      const [memberResponse, snapshotResponse] = await Promise.all([researchApi.poolMembers(detail.id), researchApi.poolSnapshots(detail.id)])
      setMembers(memberResponse.items); setSnapshots(snapshotResponse.items); await loadPools()
    } finally { setSaving(false) }
  }

  const sealLatest = async () => {
    if (!detail?.latest_generation_id) return
    setSaving(true)
    try {
      await researchApi.sealPoolSnapshot(detail.id, detail.latest_generation_id)
      setSnapshots((await researchApi.poolSnapshots(detail.id)).items); await loadPools()
    } finally { setSaving(false) }
  }

  return (
    <div className="h-full overflow-y-auto bg-crypto-bg p-4 text-gray-100 sm:p-6">
      <header className="mb-4 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-blue-500/25 bg-blue-500/10"><Filter className="h-5 w-5 text-blue-300" /></div>
          <div><div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-300/80">Research Universe</div><h1 className="mt-0.5 text-xl font-bold text-white">股票池</h1></div>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => void loadPools()} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-crypto-border px-3 text-xs text-gray-400 hover:text-gray-200"><RefreshCw className="h-3.5 w-3.5" />刷新</button>
          <button type="button" onClick={() => setShowCreate((value) => !value)} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-blue-500/35 bg-blue-500/10 px-3 text-xs text-blue-200"><Plus className="h-3.5 w-3.5" />新建规则</button>
        </div>
      </header>

      {showCreate && (
        <form onSubmit={createPool} className="mb-4 grid gap-3 rounded-xl border border-blue-500/25 bg-crypto-card p-4 sm:grid-cols-3">
          <input required aria-label="股票池名称" value={createForm.name} onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })} placeholder="股票池名称" className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm outline-none focus:border-blue-500/60" />
          <select aria-label="股票池类型" value={createForm.pool_type} onChange={(e) => setCreateForm({ ...createForm, pool_type: e.target.value })} className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm"><option value="screener">条件筛选</option><option value="factor">因子</option><option value="sector">板块</option><option value="event">事件</option><option value="manual">手工</option></select>
          <button disabled={saving} className="h-10 rounded-lg bg-blue-600 text-sm font-semibold disabled:opacity-50">保存不可变规则 v1</button>
          <input aria-label="股票池描述" value={createForm.description} onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })} placeholder="描述" className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm sm:col-span-3" />
        </form>
      )}

      {error && <div className="mb-4 rounded-xl border border-red-500/25 bg-red-500/10 p-3 text-sm text-red-200">{error}</div>}

      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="rounded-xl border border-crypto-border bg-crypto-card p-3">
          <div className="mb-2 flex items-center justify-between px-1"><span className="text-xs font-semibold text-gray-300">规则目录</span><span className="text-[10px] text-gray-600">{pools.length} 个</span></div>
          {loading ? <div className="py-8 text-center text-xs text-gray-500">读取目录…</div> : pools.length ? (
            <div className="space-y-2">
              {pools.map((pool) => <button type="button" key={pool.id} onClick={() => setSelectedId(pool.id)} className={`w-full rounded-lg border p-3 text-left ${selectedId === pool.id ? 'border-blue-500/40 bg-blue-500/10' : 'border-crypto-border bg-crypto-bg/45 hover:border-gray-600'}`}><div className="flex items-start justify-between gap-2"><span className="text-xs font-semibold text-gray-100">{pool.name}</span><span className="rounded border border-crypto-border px-1.5 py-0.5 text-[9px] uppercase text-gray-500">{pool.pool_type}</span></div><div className="mt-2 grid grid-cols-2 gap-2 text-[10px] text-gray-600"><span>成员 {pool.current_member_count ?? '—'}</span><span>封存 {pool.snapshot_count ?? 0}</span><span className="col-span-2">交易日 {pool.latest_trade_date || '—'}</span></div></button>)}
            </div>
          ) : <div className="rounded-lg border border-dashed border-crypto-border py-8 text-center text-xs text-gray-500">没有股票池规则</div>}
        </aside>

        <section className="min-w-0 space-y-4">
          {detail ? <>
            <div className="rounded-xl border border-crypto-border bg-crypto-card p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div><div className="flex items-center gap-2"><h2 className="text-base font-semibold text-white">{detail.name}</h2><span className="rounded border border-emerald-500/25 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-300">{detail.status}</span></div><p className="mt-1 text-xs text-gray-500">{detail.description || '无描述'}</p></div><div className="flex gap-2"><button type="button" onClick={() => setShowGenerate((value) => !value)} className="rounded-lg border border-blue-500/30 px-3 py-2 text-xs text-blue-200">生成批次</button><button type="button" disabled={!detail.latest_generation_id || saving} onClick={() => void sealLatest()} className="rounded-lg border border-amber-500/30 px-3 py-2 text-xs text-amber-200 disabled:opacity-40">封存最新批次</button></div></div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[['规则版本', detail.rule_version ?? '—'], ['规则哈希', detail.rule_hash || '—'], ['最新批次', detail.latest_generation_id || '—'], ['数据用途', detail.data_purpose || 'user']].map(([label, value]) => <div key={String(label)} className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3"><div className="text-[10px] text-gray-600">{label}</div><div className="mt-1 truncate font-mono text-xs text-gray-300" title={String(value)}>{value}</div></div>)}</div>
              <pre className="mt-3 max-h-48 overflow-auto rounded-lg border border-crypto-border bg-crypto-bg/60 p-3 text-[11px] leading-5 text-gray-400">{JSON.stringify(detail.config || {}, null, 2)}</pre>
            </div>

            {showGenerate && <form onSubmit={generate} className="grid gap-3 rounded-xl border border-blue-500/25 bg-crypto-card p-4 sm:grid-cols-2 xl:grid-cols-5">{[['trade_date','交易日'],['dataset_snapshot_id','数据快照 ID'],['universe_snapshot_id','Universe ID'],['factor_snapshot_id','因子快照 ID'],['market_evidence_snapshot_id','市场证据 ID']].map(([key,label]) => <label key={key} className="text-[11px] text-gray-500">{label}<input required={key === 'trade_date' || key === 'dataset_snapshot_id' || key === 'universe_snapshot_id'} type={key === 'trade_date' ? 'date' : 'number'} value={generateForm[key as keyof typeof generateForm]} onChange={(e) => setGenerateForm({ ...generateForm, [key]: e.target.value })} className="mt-1 h-9 w-full rounded-lg border border-crypto-border bg-crypto-bg px-2 text-xs text-gray-200" /></label>)}<button disabled={saving} className="h-9 rounded-lg bg-blue-600 text-xs font-semibold xl:col-span-5">按封存输入生成</button></form>}

            <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_360px]">
              <div className="rounded-xl border border-crypto-border bg-crypto-card p-4">
                <div className="mb-3 flex items-center justify-between"><div className="flex items-center gap-2"><Users className="h-4 w-4 text-blue-300" /><h2 className="text-sm font-semibold">成员与证据</h2></div><span className="text-[10px] text-gray-600">{members.length} 条</span></div>
                {members.length ? <div className="overflow-x-auto rounded-lg border border-crypto-border"><table className="min-w-full text-left text-xs"><thead className="bg-crypto-bg/80 text-[10px] text-gray-500"><tr><th className="px-3 py-2">#</th><th className="px-3 py-2">证券</th><th className="px-3 py-2">分数</th><th className="px-3 py-2">理由</th><th className="px-3 py-2">Evidence hash</th></tr></thead><tbody className="divide-y divide-crypto-border/70">{members.map((member) => <tr key={member.id}><td className="px-3 py-2 font-mono text-gray-600">{member.ordinal}</td><td className="px-3 py-2"><div className="font-semibold text-gray-200">{member.name || member.symbol}</div><div className="font-mono text-[10px] text-gray-600">{member.symbol}</div></td><td className="px-3 py-2 font-mono text-gray-300">{member.score ?? '—'}</td><td className="px-3 py-2 text-gray-400">{member.reason}</td><td className="max-w-[180px] truncate px-3 py-2 font-mono text-[10px] text-gray-600" title={member.evidence_hash}>{member.evidence_hash}</td></tr>)}</tbody></table></div> : <div className="rounded-lg border border-dashed border-crypto-border py-8 text-center text-xs text-gray-500">还没有成功生成的成员</div>}
              </div>

              <div className="rounded-xl border border-crypto-border bg-crypto-card p-4">
                <div className="mb-3 flex items-center gap-2"><Archive className="h-4 w-4 text-amber-300" /><h2 className="text-sm font-semibold">封存快照</h2></div>
                {snapshots.length ? <div className="space-y-2">{snapshots.map((snapshot) => <div key={snapshot.id} className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3"><div className="flex items-center justify-between"><span className="font-mono text-xs text-gray-300">Snapshot #{snapshot.id}</span><span className="rounded border border-emerald-500/25 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-300">{snapshot.status}</span></div><div className="mt-2 text-[10px] text-gray-600">{snapshot.trade_date} · {snapshot.member_count} members</div><div className="mt-1 truncate font-mono text-[10px] text-gray-600" title={snapshot.manifest_hash}>{snapshot.manifest_hash}</div></div>)}</div> : <div className="rounded-lg border border-dashed border-crypto-border py-8 text-center text-xs text-gray-500">尚无封存快照</div>}
              </div>
            </div>
          </> : <div className="rounded-xl border border-dashed border-crypto-border bg-crypto-card/50 p-12 text-center text-sm text-gray-500"><ShieldCheck className="mx-auto mb-3 h-7 w-7" />选择一个股票池查看规则与证据</div>}
        </section>
      </div>

      <footer className="mt-4 flex items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card/60 px-3 py-2 text-[11px] text-gray-500"><Database className="h-3.5 w-3.5" />PostgreSQL immutable stock-pool evidence · 页面读取不会生成成员或快照</footer>
    </div>
  )
}
