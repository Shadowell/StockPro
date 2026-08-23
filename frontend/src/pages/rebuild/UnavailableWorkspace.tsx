import { Database, ShieldCheck } from 'lucide-react'


export type WorkspaceState = {
  title: string
  description: string
  ownerRoute: string
  status: 'adapting'
}


export default function UnavailableWorkspace({ state }: { state: WorkspaceState }) {
  return (
    <section className="min-h-full bg-crypto-bg p-4 text-gray-100 sm:p-6">
      <div className="mx-auto max-w-6xl rounded-xl border border-crypto-border bg-crypto-card p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-blue-500/30 bg-blue-500/10 text-blue-300">
              <ShieldCheck className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <h1 className="text-base font-semibold text-white">{state.title}</h1>
              <p className="mt-1 text-xs leading-5 text-gray-400">{state.description}</p>
            </div>
          </div>
          <span className="shrink-0 rounded-md border border-amber-500/25 bg-amber-500/10 px-2 py-1 text-[11px] font-medium text-amber-200">
            A股适配未完成
          </span>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-crypto-border bg-crypto-bg/55 p-3">
            <div className="text-[11px] text-gray-500">Owner route</div>
            <div className="mt-1 font-mono text-sm text-gray-200">{state.ownerRoute}</div>
          </div>
          <div className="rounded-lg border border-crypto-border bg-crypto-bg/55 p-3">
            <div className="text-[11px] text-gray-500">运行状态</div>
            <div className="mt-1 text-sm font-medium text-gray-200">未注册业务服务</div>
          </div>
          <div className="rounded-lg border border-crypto-border bg-crypto-bg/55 p-3">
            <div className="flex items-center gap-1.5 text-[11px] text-gray-500">
              <Database className="h-3.5 w-3.5" />
              数据边界
            </div>
            <div className="mt-1 text-sm font-medium text-gray-200">PostgreSQL 接入待验收</div>
          </div>
        </div>

        <div className="mt-4 rounded-lg border border-cyan-500/20 bg-cyan-500/5 px-3 py-2 text-xs leading-5 text-cyan-100">
          正在接入 A股 PostgreSQL 数据。当前页面不发起业务请求，不展示 mock 行情，也不会启动 Provider、策略或 Paper recovery。
        </div>
      </div>
    </section>
  )
}
