import { CalendarDays, Database, ShieldCheck, SlidersHorizontal } from 'lucide-react'
import type { StrategyParameterSections as LegacyParameterSections } from '../utils/strategyConfigDisplay'


export default function StrategyParameterSections({
  parameterSchema,
  dependencyManifest,
  sections,
}: {
  parameterSchema?: Record<string, unknown>
  dependencyManifest?: Record<string, unknown>
  sections?: LegacyParameterSections
}) {
  if (sections) {
    return (
      <div className="grid gap-3 lg:grid-cols-2">
        {[['交易参数', sections.trading], ['风险参数', sections.risk]].map(([title, items]) => (
          <section key={String(title)} className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3">
            <div className="text-xs font-semibold text-gray-200">{String(title)}</div>
            <div className="mt-3 space-y-2">{(items as LegacyParameterSections['trading']).map((item) => <div key={item.key} className="flex justify-between gap-3 text-[11px]"><span className="text-gray-600">{item.label}</span><span className="font-mono text-gray-300">{item.value}</span></div>)}</div>
          </section>
        ))}
      </div>
    )
  }
  const manifest = dependencyManifest || {}
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <section className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-gray-200"><CalendarDays className="h-4 w-4 text-blue-300" />A股执行语义</div>
        <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
          {[
            ['交易日历', 'CN_A_SHARE'],
            ['可卖规则', 'T+1'],
            ['最小委托', '100股'],
            ['方向', '只做多'],
          ].map(([label, value]) => <div key={label} className="rounded border border-crypto-border p-2"><div className="text-gray-600">{label}</div><div className="mt-1 font-mono text-gray-300">{value}</div></div>)}
        </div>
      </section>
      <section className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-gray-200"><Database className="h-4 w-4 text-cyan-300" />封存输入</div>
        <div className="mt-3 space-y-2 text-[11px]">
          {[
            ['股票池快照', manifest.pool_snapshot_id],
            ['因子快照', manifest.factor_snapshot_id],
            ['数据快照', manifest.dataset_snapshot_id],
            ['成本模型', manifest.cost_model_id],
          ].map(([label, value]) => <div key={String(label)} className="flex items-center justify-between rounded border border-crypto-border px-2.5 py-2"><span className="text-gray-600">{String(label)}</span><span className="font-mono text-gray-300">{value == null ? '未绑定' : String(value)}</span></div>)}
        </div>
      </section>
      <section className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3 lg:col-span-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-gray-200"><SlidersHorizontal className="h-4 w-4 text-purple-300" />参数 Schema</div>
        <pre className="mt-3 max-h-56 overflow-auto rounded border border-crypto-border bg-black/15 p-3 text-[11px] leading-5 text-gray-400">{JSON.stringify(parameterSchema || {}, null, 2)}</pre>
      </section>
      <div className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-[11px] leading-5 text-amber-100 lg:col-span-2"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />目录、代码校验或 quick-run 不产生 Paper 晋级资格；必须进入完整回测协议。</div>
    </div>
  )
}
