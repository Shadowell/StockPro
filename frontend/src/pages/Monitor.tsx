import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Activity, Bell, Database, HeartPulse, RefreshCw, ShieldAlert } from 'lucide-react';
import { getMonitorHealth } from '../api/client';
import type { MonitorHealth } from '../types';

const TABS = [['overview', '总览'], ['strategy', '策略健康'], ['data', '数据健康'], ['risk', '风险'], ['notifications', '通知']] as const;
type Tab = (typeof TABS)[number][0];
const panel = 'rounded-xl border border-crypto-border bg-crypto-card';
const text = (value: unknown) => value === null || value === undefined || value === '' ? '--' : String(value);
const tone = (status: string) => status === 'healthy' || status === 'running' ? 'text-emerald-300' : status === 'critical' || status === 'failed' ? 'text-red-300' : 'text-amber-300';
const purposeLabel = (value: string) => value === 'acceptance' ? '验收数据' : value === 'seed' ? '种子数据' : '用户数据';

function Rows({ rows, keys }: { rows: Array<Record<string, unknown>>; keys: Array<[string, string]> }) {
  return <div className={`${panel} overflow-hidden`}><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm"><thead><tr className="border-b border-crypto-border text-left text-xs text-slate-500">{keys.map(([key, label]) => <th key={key} className="px-4 py-3">{label}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={text(row.id ?? `${row.status}-${index}`)} className="border-b border-white/[0.04]">{keys.map(([key]) => <td key={key} className={`px-4 py-3 ${key === 'status' ? tone(text(row[key])) : 'text-slate-300'}`}>{typeof row[key] === 'object' ? JSON.stringify(row[key]) : text(row[key])}</td>)}</tr>)}</tbody></table></div>{rows.length === 0 ? <div className="p-12 text-center text-sm text-slate-600">暂无健康记录</div> : null}</div>;
}

export function Monitor() {
  const [params, setParams] = useSearchParams();
  const requested = params.get('tab') as Tab | null;
  const tab: Tab = TABS.some(([key]) => key === requested) ? requested! : 'overview';
  const [health, setHealth] = useState<MonitorHealth | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const load = async () => { setBusy(true); setError(''); try { setHealth(await getMonitorHealth()); } catch (reason) { setError(reason instanceof Error ? reason.message : '监控上下文加载失败'); } finally { setBusy(false); } };
  useEffect(() => { void load(); }, []);
  const activeStrategies = health ? health.strategy_instances.reduce((sum, item) => sum + Number(item.count ?? 0), 0) : '--';
  const activeRisks = health ? health.risk_alerts.reduce((sum, item) => sum + Number(item.count ?? 0), 0) : '--';
  const delivered = health ? health.notifications.reduce((sum, item) => sum + Number(item.count ?? 0), 0) : '--';
  return <div className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8" data-testid="monitor-workbench">
    <header className="mb-5 flex flex-wrap items-start justify-between gap-4"><div><div className="flex items-center gap-3"><HeartPulse className="h-7 w-7 text-emerald-400" /><h1 className="text-2xl font-black text-white">监控中心</h1><span className={`rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs font-semibold ${tone(health?.status ?? 'unavailable')}`}>{health?.status ?? 'unavailable'}</span></div><p className="mt-2 text-sm text-slate-500">运行风控检查 · 区分策略、数据、风险与通知服务健康，不混入人工交易控制。</p></div><button type="button" onClick={() => void load()} className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-400"><RefreshCw className={`h-4 w-4 ${busy ? 'animate-spin' : ''}`} />刷新健康快照</button></header>
    <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-crypto-border bg-crypto-card px-4 py-3 text-xs text-slate-500"><span>来源 <strong className="font-medium text-slate-300">{health?.source_label ?? 'PostgreSQL 运行证据'}</strong></span><span>状态 <strong className={error ? 'text-red-300' : busy ? 'text-blue-300' : health ? tone(health.status) : 'text-amber-300'}>{error ? '加载失败' : busy ? '读取中' : health?.status ?? '未加载'}</strong></span><span>最新持久化证据 <strong className="font-mono text-slate-300">{health?.source_updated_at ?? '--'}</strong></span><span>响应生成 <strong className="font-mono text-slate-400">{health?.response_generated_at ?? '--'}</strong></span></div>
    <nav className="mb-5 flex overflow-x-auto rounded-xl border border-crypto-border bg-crypto-card p-1">{TABS.map(([key, label]) => <button data-testid={`monitor-tab-${key}`} type="button" key={key} onClick={() => setParams({ tab: key })} className={`min-w-max flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold ${tab === key ? 'bg-emerald-600 text-white' : 'text-slate-500 hover:bg-slate-800/60 hover:text-white'}`}>{label}</button>)}</nav>
    {error ? <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">{error}</div> : null}
    {tab === 'overview' ? <div className="space-y-5"><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[[Activity, '服务状态', health?.status ?? '--'], [HeartPulse, '策略实例', activeStrategies], [ShieldAlert, '活动风险告警', activeRisks], [Bell, '通知投递', delivered]].map(([Icon, label, current]) => { const Component = Icon as typeof Activity; return <div key={String(label)} className={`${panel} p-4`}><Component className="h-5 w-5 text-emerald-400" /><div className="mt-3 text-xs text-slate-500">{String(label)}</div><div className={`mt-2 text-2xl font-black ${String(label) === '服务状态' ? tone(String(current)) : 'text-white'}`}>{String(current)}</div></div>; })}</div><section className={`${panel} p-5`}><h2 className="font-semibold text-white">健康边界</h2><div className="mt-4 grid gap-3 md:grid-cols-3"><div className="rounded-lg border border-crypto-border bg-crypto-bg p-4 text-sm text-slate-400">数据陈旧 ≠ 策略失败</div><div className="rounded-lg border border-crypto-border bg-crypto-bg p-4 text-sm text-slate-400">风险拒单保留规则版本</div><div className="rounded-lg border border-crypto-border bg-crypto-bg p-4 text-sm text-slate-400">通知确认不删除原始告警</div></div><p className="mt-4 text-xs text-slate-600">涨跌停风险、停牌、T+1 与参与率均在执行证据链中保留。</p></section></div> : null}
    {tab === 'strategy' ? <div className="space-y-4">
      {(health?.strategy_health ?? []).map((item) => <article key={item.id} className={`${panel} p-5`}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div><div className="flex flex-wrap items-center gap-2"><h2 className="font-semibold text-white">{item.name}</h2><span className={`rounded border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] ${tone(item.health_state)}`}>{item.health_state}</span><span className="rounded border border-slate-700 px-2 py-0.5 text-[10px] text-slate-400">{purposeLabel(item.data_purpose)}</span></div><div className="mt-2 font-mono text-[10px] text-slate-600">{item.id}</div></div>
          <Link to={`/paper?instance=${item.id}`} className="rounded-lg border border-crypto-border px-3 py-2 text-xs text-blue-300">Paper 证据链</Link>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[['运行状态', item.status], ['最后心跳', item.heartbeat_at], ['最后交易日', item.last_processed_trade_date], ['最后周期', item.latest_cycle_status], ['周期完成', item.latest_cycle_finished_at], ['最新权益', item.latest_equity], ['最新回撤', item.latest_drawdown], ['账本差额', item.latest_cycle_ledger_difference]].map(([label, value]) => <div key={String(label)} className="rounded-lg border border-crypto-border bg-crypto-bg p-3"><div className="text-[10px] text-slate-600">{String(label)}</div><div className={`mt-1 break-all text-xs ${String(label).includes('状态') || String(label) === '最后周期' ? tone(text(value)) : 'text-slate-300'}`}>{text(value)}</div></div>)}
        </div>
        <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-500"><span>订单 <strong className="text-slate-300">{item.order_count}</strong></span><span>成交 <strong className="text-slate-300">{item.trade_count}</strong></span><span>风险决策 <strong className="text-slate-300">{item.risk_event_count}</strong></span><span>拒绝 <strong className={item.rejected_count ? 'text-red-300' : 'text-slate-300'}>{item.rejected_count}</strong></span></div>
        {item.latest_cycle_error ? <div className="mt-3 rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-xs text-red-200">{item.latest_cycle_error}</div> : null}
      </article>)}
      {!health?.strategy_health?.length ? <div className={`${panel} p-12 text-center text-sm text-slate-600`}>{busy ? '正在读取实例健康…' : '没有 Paper 实例健康证据'}</div> : null}
    </div> : null}
    {tab === 'data' ? <div className="grid gap-5 xl:grid-cols-2"><section className={`${panel} p-5`}><div className="flex items-center gap-2"><Database className="h-5 w-5 text-blue-400" /><h2 className="font-semibold text-white">研究数据快照</h2></div><pre className="mt-4 overflow-x-auto rounded-lg border border-crypto-border bg-crypto-bg p-4 text-xs leading-6 text-slate-400">{JSON.stringify(health?.data.dataset ?? null, null, 2)}</pre></section><section className={`${panel} p-5`}><div className="flex items-center gap-2"><Database className="h-5 w-5 text-violet-400" /><h2 className="font-semibold text-white">市场证据快照</h2></div><pre className="mt-4 overflow-x-auto rounded-lg border border-crypto-border bg-crypto-bg p-4 text-xs leading-6 text-slate-400">{JSON.stringify(health?.data.market ?? null, null, 2)}</pre></section><Rows rows={health?.services ?? []} keys={[["service_code","服务"],["status","状态"],["last_success_at","最近成功"],["error_code","错误码"],["message","消息"],["observed_at","观察时间"]]} /></div> : null}
    {tab === 'risk' ? <div className="space-y-4"><Rows rows={health?.risk_alerts ?? []} keys={[["severity","级别"],["count","活动告警"]]} /><Rows rows={(health?.active_alerts ?? []) as unknown as Array<Record<string, unknown>>} keys={[["triggered_at","触发时间"],["severity","级别"],["category","类别"],["title","告警"],["source_object_type","来源类型"],["source_object_id","来源 ID"]]} /><div className={`${panel} flex items-center justify-between p-5`}><div><h2 className="font-semibold text-white">风险告警证据</h2><p className="mt-1 text-xs text-slate-500">在观察台确认告警，在 Paper 查看对应实例、订单与规则链。</p></div><Link to="/watch?tab=alerts" className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white">打开观察台</Link></div></div> : null}
    {tab === 'notifications' ? <Rows rows={health?.notifications ?? []} keys={[["status","投递状态"],["count","数量"]]} /> : null}
  </div>;
}

export default Monitor;
