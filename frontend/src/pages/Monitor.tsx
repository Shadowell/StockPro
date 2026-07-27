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
    <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-crypto-border bg-crypto-card px-4 py-3 text-xs text-slate-500"><span>数据 <strong className="font-medium text-slate-300">服务健康与审计记录</strong></span><span>状态 <strong className={error ? 'text-red-300' : busy ? 'text-blue-300' : health ? tone(health.status) : 'text-amber-300'}>{error ? '加载失败' : busy ? '读取中' : health?.status ?? '未加载'}</strong></span><span>观察时间 <strong className="font-mono text-slate-300">{health?.observed_at ?? '--'}</strong></span></div>
    <nav className="mb-5 flex overflow-x-auto rounded-xl border border-crypto-border bg-crypto-card p-1">{TABS.map(([key, label]) => <button data-testid={`monitor-tab-${key}`} type="button" key={key} onClick={() => setParams({ tab: key })} className={`min-w-max flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold ${tab === key ? 'bg-emerald-600 text-white' : 'text-slate-500 hover:bg-slate-800/60 hover:text-white'}`}>{label}</button>)}</nav>
    {error ? <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">{error}</div> : null}
    {tab === 'overview' ? <div className="space-y-5"><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[[Activity, '服务状态', health?.status ?? '--'], [HeartPulse, '策略实例', activeStrategies], [ShieldAlert, '活动风险告警', activeRisks], [Bell, '通知投递', delivered]].map(([Icon, label, current]) => { const Component = Icon as typeof Activity; return <div key={String(label)} className={`${panel} p-4`}><Component className="h-5 w-5 text-emerald-400" /><div className="mt-3 text-xs text-slate-500">{String(label)}</div><div className={`mt-2 text-2xl font-black ${String(label) === '服务状态' ? tone(String(current)) : 'text-white'}`}>{String(current)}</div></div>; })}</div><section className={`${panel} p-5`}><h2 className="font-semibold text-white">健康边界</h2><div className="mt-4 grid gap-3 md:grid-cols-3"><div className="rounded-lg border border-crypto-border bg-crypto-bg p-4 text-sm text-slate-400">数据陈旧 ≠ 策略失败</div><div className="rounded-lg border border-crypto-border bg-crypto-bg p-4 text-sm text-slate-400">风险拒单保留规则版本</div><div className="rounded-lg border border-crypto-border bg-crypto-bg p-4 text-sm text-slate-400">通知确认不删除原始告警</div></div><p className="mt-4 text-xs text-slate-600">涨跌停风险、停牌、T+1 与参与率均在执行证据链中保留。</p></section></div> : null}
    {tab === 'strategy' ? <Rows rows={health?.strategy_instances ?? []} keys={[["status","实例状态"],["count","数量"]]} /> : null}
    {tab === 'data' ? <div className="grid gap-5 xl:grid-cols-2"><section className={`${panel} p-5`}><div className="flex items-center gap-2"><Database className="h-5 w-5 text-blue-400" /><h2 className="font-semibold text-white">研究数据快照</h2></div><pre className="mt-4 overflow-x-auto rounded-lg border border-crypto-border bg-crypto-bg p-4 text-xs leading-6 text-slate-400">{JSON.stringify(health?.data.dataset ?? null, null, 2)}</pre></section><section className={`${panel} p-5`}><div className="flex items-center gap-2"><Database className="h-5 w-5 text-violet-400" /><h2 className="font-semibold text-white">市场证据快照</h2></div><pre className="mt-4 overflow-x-auto rounded-lg border border-crypto-border bg-crypto-bg p-4 text-xs leading-6 text-slate-400">{JSON.stringify(health?.data.market ?? null, null, 2)}</pre></section><Rows rows={health?.services ?? []} keys={[["service_code","服务"],["status","状态"],["last_success_at","最近成功"],["error_code","错误码"],["message","消息"],["observed_at","观察时间"]]} /></div> : null}
    {tab === 'risk' ? <div className="space-y-4"><Rows rows={health?.risk_alerts ?? []} keys={[["severity","级别"],["count","活动告警"]]} /><div className={`${panel} flex items-center justify-between p-5`}><div><h2 className="font-semibold text-white">风险告警证据</h2><p className="mt-1 text-xs text-slate-500">在观察台确认告警，在 Paper 查看对应实例、订单与规则链。</p></div><Link to="/watch?tab=alerts" className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white">打开观察台</Link></div></div> : null}
    {tab === 'notifications' ? <Rows rows={health?.notifications ?? []} keys={[["status","投递状态"],["count","数量"]]} /> : null}
  </div>;
}

export default Monitor;
