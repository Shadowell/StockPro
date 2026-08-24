import { useEffect, useState } from 'react'
import {
  Activity,
  CalendarDays,
  Database,
  Flame,
  LayoutDashboard,
  Layers3,
  RefreshCw,
  TrendingUp,
  Workflow,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { researchApi } from '../api/client'
import type { MarketOverviewView } from '../types/research'
import { formatAshareSymbol } from '../utils/ashareSymbol'


type NumericValue = number | string | null | undefined

const numericValue = (value: NumericValue) => {
  if (value == null || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const formatNumber = (value: NumericValue, maximumFractionDigits = 2) => {
  const parsed = numericValue(value)
  return parsed == null
    ? '—'
    : new Intl.NumberFormat('zh-CN', { maximumFractionDigits }).format(parsed)
}

const formatPct = (value: NumericValue) => {
  const parsed = numericValue(value)
  return parsed == null ? '—' : `${parsed >= 0 ? '+' : ''}${parsed.toFixed(2)}%`
}

const formatTurnover = (amount: NumericValue) => {
  const parsed = numericValue(amount)
  return parsed == null ? '—' : `${formatNumber(parsed / 100_000_000, 2)} 亿`
}

const valueTone = (value: NumericValue) => {
  const parsed = numericValue(value)
  return parsed == null ? 'text-gray-500' : parsed >= 0 ? 'text-up' : 'text-down'
}


function PanelTitle({ icon: Icon, title, detail }: { icon: typeof TrendingUp; title: string; detail?: string }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-blue-300" />
        <h2 className="text-sm font-semibold text-gray-100">{title}</h2>
      </div>
      {detail && <span className="text-[11px] text-gray-600">{detail}</span>}
    </div>
  )
}


function LoadingState() {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="首页加载中">
      {Array.from({ length: 8 }, (_, index) => (
        <div key={index} className="h-28 animate-pulse rounded-xl border border-crypto-border bg-crypto-card" />
      ))}
    </div>
  )
}


export default function Home() {
  const navigate = useNavigate()
  const [overview, setOverview] = useState<MarketOverviewView | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      setOverview(await researchApi.marketOverview())
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError?.message || '市场总览读取失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  return (
    <div className="h-full overflow-y-auto bg-crypto-bg">
      <header className="border-b border-crypto-border/70 bg-slate-950/35 px-4 py-4 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-blue-500/25 bg-blue-500/10">
              <LayoutDashboard className="h-5 w-5 text-blue-300" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-300/80">
                <Activity className="h-3 w-3" />
                Market Command
              </div>
              <h1 className="mt-0.5 text-xl font-bold text-white">A股市场总览</h1>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-[11px]">
            <span className="flex items-center gap-1.5 rounded-md border border-emerald-500/20 bg-emerald-500/[0.07] px-3 py-1.5 font-medium text-emerald-300">
              <Database className="h-3.5 w-3.5" />
              POSTGRESQL EVIDENCE
            </span>
            <span className="rounded-md border border-slate-600/45 bg-slate-900/70 px-3 py-1.5 font-medium text-slate-300">
              CN A-SHARE
            </span>
            <span className="rounded-md border border-slate-600/45 bg-slate-900/70 px-3 py-1.5 font-medium text-slate-400">
              {overview?.data_status?.toUpperCase() || 'LOADING'}
            </span>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-l-2 border-blue-500/40 pl-3 text-xs text-gray-500">
          <p>封存市场证据与 PostgreSQL 行情缓存的只读操作台；缺失字段保持不可用。</p>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-md border border-crypto-border px-2.5 py-1.5 text-[11px] text-gray-400 hover:text-gray-200 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            重新读取
          </button>
        </div>
      </header>

      <main className="space-y-4 px-4 py-4 pb-7 sm:px-6">
        {loading && <LoadingState />}
        {!loading && error && (
          <div className="rounded-xl border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">
            <div className="font-semibold">市场总览不可用</div>
            <div className="mt-1 text-xs leading-5 text-red-200/75">{error}</div>
          </div>
        )}

        {!loading && !error && overview && (
          <>
            <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
              <PanelTitle icon={TrendingUp} title="主要指数" detail={`${overview.indices.length} 个缓存指数`} />
              {overview.indices.length ? (
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {overview.indices.map((index) => (
                    <button
                      type="button"
                      key={index.symbol}
                      onClick={() => navigate(`/market?symbol=${encodeURIComponent(index.symbol)}`)}
                      className="rounded-lg border border-crypto-border bg-crypto-bg/55 p-3 text-left transition-colors hover:border-blue-500/40"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <div className="text-xs font-semibold text-gray-200">{index.name}</div>
                          <div className="mt-1 font-mono text-[10px] text-gray-600">{formatAshareSymbol(index.symbol)}</div>
                        </div>
                        <span className={`font-mono text-xs font-semibold ${valueTone(index.change_pct)}`}>
                          {formatPct(index.change_pct)}
                        </span>
                      </div>
                      <div className="mt-3 font-mono text-xl font-semibold tabular-nums text-white">
                        {formatNumber(index.value)}
                      </div>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="rounded-lg border border-dashed border-crypto-border p-5 text-center text-xs text-gray-500">指数缓存为空</div>
              )}
            </section>

            <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
              <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
                <PanelTitle icon={Activity} title="市场宽度" detail="封存交易日口径" />
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    ['上涨', overview.breadth?.rise_count, 'text-up'],
                    ['平盘', overview.breadth?.flat_count, 'text-gray-300'],
                    ['下跌', overview.breadth?.fall_count, 'text-down'],
                    ['成交额', overview.turnover?.amount, 'text-blue-200'],
                  ].map(([label, value, tone]) => (
                    <div key={String(label)} className="rounded-lg border border-crypto-border bg-crypto-bg/55 p-3">
                      <div className="text-[11px] text-gray-500">{label}</div>
                      <div className={`mt-2 font-mono text-lg font-semibold tabular-nums ${tone}`}>
                        {label === '成交额' ? formatTurnover(value) : formatNumber(value, 0)}
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
                <PanelTitle icon={Flame} title="涨停生态" detail="涨跌停与连板证据" />
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-2">
                  {[
                    ['涨停', overview.limit_ecology?.limit_up_count, 'text-up'],
                    ['跌停', overview.limit_ecology?.limit_down_count, 'text-down'],
                    ['最高板', overview.limit_ecology?.max_streak, 'text-blue-200'],
                    ['炸板率', overview.limit_ecology?.broken_board_rate, 'text-amber-200'],
                  ].map(([label, value, tone]) => (
                    <div key={String(label)} className="rounded-lg border border-crypto-border bg-crypto-bg/55 p-3">
                      <div className="text-[11px] text-gray-500">{label}</div>
                      <div className={`mt-2 font-mono text-lg font-semibold ${tone}`}>
                        {label === '炸板率' ? formatPct(value).replace('+', '') : formatNumber(value, 0)}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            </div>

            <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
              <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
                <PanelTitle icon={Layers3} title="板块资金" detail="同一封存快照" />
                {overview.sector_flows.length ? (
                  <div className="divide-y divide-crypto-border/70 overflow-hidden rounded-lg border border-crypto-border">
                    {overview.sector_flows.slice(0, 8).map((sector) => (
                      <div key={sector.sector_code} className="grid grid-cols-[minmax(0,1fr)_110px_90px] items-center gap-3 bg-crypto-bg/40 px-3 py-2 text-xs">
                        <span className="truncate text-gray-200">{sector.sector_name}</span>
                        <span className="text-right font-mono text-gray-300">{formatTurnover(sector.net_inflow)}</span>
                        <span className={`text-right font-mono ${valueTone(sector.change_pct)}`}>{formatPct(sector.change_pct)}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed border-crypto-border p-5 text-center text-xs leading-5 text-gray-500">
                    当前封存快照没有板块净流入证据，本模块保持不可用。
                  </div>
                )}
              </section>

              <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
                <PanelTitle icon={Workflow} title="主线状态" detail="策略 → 回测 → 模拟" />
                <div className="space-y-2">
                  {[
                    ['策略', '/strategy', '不可变版本、验证与研究证据'],
                    ['回测', '/backtest', 'A股撮合、参数矩阵与晋级门禁'],
                    ['模拟', '/paper', 'PostgreSQL 现金账本与实例监控'],
                  ].map(([label, route, detail]) => (
                    <button
                      type="button"
                      key={route}
                      onClick={() => navigate(route)}
                      className="flex w-full items-center justify-between gap-3 rounded-lg border border-crypto-border bg-crypto-bg/45 px-3 py-2.5 text-left hover:border-blue-500/35"
                    >
                      <span>
                        <span className="block text-xs font-semibold text-gray-200">{label}</span>
                        <span className="mt-0.5 block text-[11px] text-gray-600">{detail}</span>
                      </span>
                      <span className="shrink-0 text-[10px] text-emerald-300">已接入</span>
                    </button>
                  ))}
                </div>
              </section>
            </div>

            <footer className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-crypto-border bg-crypto-card/60 px-3 py-2 text-[11px] text-gray-500">
              <span className="flex items-center gap-1.5"><Database className="h-3.5 w-3.5" />{overview.source_label}</span>
              <span className="flex items-center gap-1.5"><CalendarDays className="h-3.5 w-3.5" />交易日 {overview.trade_date || '—'} · 更新 {overview.source_updated_at ? new Date(overview.source_updated_at).toLocaleString('zh-CN') : '—'}</span>
            </footer>
          </>
        )}
      </main>
    </div>
  )
}
