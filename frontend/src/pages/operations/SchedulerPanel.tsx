import { useEffect, useState } from 'react'
import { CalendarClock, PlayCircle } from 'lucide-react'
import { operationsCurrentApi } from '../../api/client'
import { useAuth } from '../../auth/AuthProvider'

type SchedulerStatus = {
  running: boolean
  timezone: string
  jobs: Array<{ id: string; name: string; next_run_at: string | null; trigger: string }>
  schedule?: { enabled: boolean; cron: string; dailyBarsWatermark?: string | null }
  last_results?: Record<string, unknown>
}

const dt = (value: unknown) => (value ? String(value).replace('T', ' ').slice(0, 19) : '—')

/** 日终调度面板：调度器状态、盘后链计划与手动触发（管理员）。 */
export default function SchedulerPanel() {
  const { role } = useAuth()
  const [state, setState] = useState<SchedulerStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const admin = role === 'admin'

  const load = async () => {
    try {
      setState(await operationsCurrentApi.scheduler())
      setMessage('')
    } catch (error: any) {
      setMessage(error?.response?.data?.detail || error?.message || '调度器状态读取失败')
    }
  }
  useEffect(() => { void load() }, [])

  const runNow = async () => {
    if (!window.confirm('手动执行最近交易日的盘后日终链？已封存日期会自动跳过。')) return
    setBusy(true)
    try {
      const result = await operationsCurrentApi.runDailyReference()
      setMessage(`日终链执行完成：${result.status}${result.run?.tradeDate ? ` · ${result.run.tradeDate}` : ''}`)
      await load()
    } catch (error: any) {
      setMessage(error?.response?.data?.detail || error?.message || '日终链执行失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <CalendarClock className="h-4 w-4 text-blue-300" />
          <h2 className="text-sm font-semibold">日终调度</h2>
          <span className={`text-[10px] ${state?.running ? 'text-emerald-300' : 'text-gray-500'}`}>
            {state === null ? '' : state.running ? '运行中' : '未启用'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void load()}
            className="rounded border border-crypto-border px-2.5 py-1.5 text-[11px] text-gray-400"
          >
            刷新
          </button>
          <button
            type="button"
            disabled={!admin || busy}
            title={admin ? '立即执行盘后日终链' : '仅管理员可操作'}
            onClick={() => void runNow()}
            className="inline-flex items-center gap-1 rounded border border-blue-500/40 bg-blue-500/10 px-2.5 py-1.5 text-[11px] text-blue-200 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <PlayCircle className={`h-3.5 w-3.5 ${busy ? 'animate-pulse' : ''}`} />
            立即执行日终链
          </button>
        </div>
      </div>
      {message && (
        <div className="mb-3 rounded border border-blue-500/25 bg-blue-500/10 p-2.5 text-[11px] text-blue-200" role="status">
          {message}
        </div>
      )}
      {!state ? (
        <div className="text-xs text-gray-500">读取中…</div>
      ) : (
        <>
          <div className="mb-2 grid gap-2 text-[11px] sm:grid-cols-3">
            <div className="rounded border border-crypto-border bg-crypto-bg/50 p-2.5">
              <div className="text-[10px] text-gray-600">时区</div>
              <div className="mt-0.5 font-mono">{state.timezone}</div>
            </div>
            <div className="rounded border border-crypto-border bg-crypto-bg/50 p-2.5">
              <div className="text-[10px] text-gray-600">盘后链 Cron</div>
              <div className="mt-0.5 font-mono">{state.schedule?.enabled ? state.schedule.cron : `${state.schedule?.cron ?? '—'}（停用）`}</div>
            </div>
            <div className="rounded border border-crypto-border bg-crypto-bg/50 p-2.5">
              <div className="text-[10px] text-gray-600">日线水位</div>
              <div className="mt-0.5 font-mono">{String(state.schedule?.dailyBarsWatermark || '—')}</div>
            </div>
          </div>
          <div className="space-y-1.5">
            {(state.jobs || []).map((job) => (
              <div key={job.id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-crypto-border bg-crypto-bg/50 px-3 py-2 text-xs">
                <span>{job.name}</span>
                <span className="font-mono text-[10px] text-gray-600">{job.trigger}</span>
                <span className="font-mono text-[10px] text-blue-200/80">下次 {dt(job.next_run_at)}</span>
              </div>
            ))}
            {!state.jobs?.length && <div className="rounded border border-crypto-border p-3 text-xs text-gray-500">ENABLE_SCHEDULER 未开启时无注册任务；仍可手动执行日终链。</div>}
          </div>
        </>
      )}
    </section>
  )
}
