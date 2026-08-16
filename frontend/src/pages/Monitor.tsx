import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Activity, Bell, Database, HeartPulse, RefreshCw, ShieldAlert } from 'lucide-react';
import { getMonitorHealth } from '../api/client';
import { WorkspaceTabs } from '../components/WorkspaceTabs';
import { DiagnosticDetails } from '../components/DiagnosticDetails';
import { DataScopeControl } from '../components/DataScopeControl';
import { EvidenceStrip, MetricValue, OperatorPageHeader } from '../components/OperatorShell';
import { WorkspacePipelineNote } from '../components/WorkspacePipelineNote';
import type { DataScope, MonitorHealth } from '../types';
import { categoryLabel, sourceLabel, statusLabel } from '../utils/presentation';
import { countMetricColor, type MetricTone } from '../utils/marketColors';

const TABS = [['overview', '总览'], ['strategy', '策略健康'], ['data', '数据健康'], ['risk', '风险'], ['notifications', '通知']] as const;
type Tab = (typeof TABS)[number][0];
const panel = 'rounded-xl border border-crypto-border bg-crypto-card';
const text = (value: unknown) => value === null || value === undefined || value === '' ? '--' : String(value);
const tone = (status: string) => status === 'healthy' || status === 'running' ? 'text-emerald-300' : status === 'critical' || status === 'failed' ? 'text-red-300' : 'text-amber-300';
const serviceLabels: Record<string, string> = {
  paper_feed: '模拟行情服务',
  paper_runtime: '模拟运行服务',
};
const snapshotLabels: Record<string, string> = {
  status: '封存状态',
  knowledge_cutoff_at: '知识截止',
  trade_date: '交易日',
  available_at: '可用时间',
  manifest_hash: '清单校验',
  content_hash: '内容校验',
};

function SnapshotPanel({
  title,
  toneClass,
  snapshot,
}: {
  title: string;
  toneClass: string;
  snapshot?: Record<string, unknown> | null;
}) {
  const entries = Object.entries(snapshot ?? {})
    .filter(([key]) => key !== 'id')
    .map(([key, value]) => [
      snapshotLabels[key] ?? key,
      key.endsWith('_hash') ? (value ? '已校验' : '未校验') : key === 'status' ? statusLabel(value) : text(value),
    ]);
  return <section className={`${panel} p-5`}>
    <div className="flex items-center gap-2"><Database className={`h-5 w-5 ${toneClass}`} /><h2 className="font-semibold text-white">{title}</h2></div>
    {entries.length ? <dl className="mt-4 space-y-2">{entries.map(([label, value]) => <div key={String(label)} className="flex items-center justify-between gap-4 rounded-lg border border-crypto-border bg-crypto-bg px-4 py-3 text-xs"><dt className="text-slate-500">{String(label)}</dt><dd className="text-right font-medium text-slate-300">{String(value)}</dd></div>)}</dl> : <div className="mt-4 rounded-lg border border-dashed border-crypto-border px-4 py-10 text-center text-sm text-slate-600">暂无可用快照</div>}
  </section>;
}

function Rows({ rows, keys, diagnosticsLabel }: { rows: Array<Record<string, unknown>>; keys: Array<[string, string]>; diagnosticsLabel?: string }) {
  const displayValue = (key: string, current: unknown) => {
    if (current === null || current === undefined || current === '') return '--';
    if (key === 'service_code') return serviceLabels[String(current)] ?? String(current);
    if (key === 'status' || key === 'severity' || key === 'freshness') return statusLabel(current);
    if (key === 'category') return categoryLabel(current);
    return typeof current === 'object' ? JSON.stringify(current) : text(current);
  };
  return <div className={`${panel} overflow-hidden`}><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm"><thead><tr className="border-b border-crypto-border text-left text-xs text-slate-500">{keys.map(([key, label]) => <th key={key} className="px-4 py-3">{label}</th>)}{diagnosticsLabel ? <th className="px-4 py-3">诊断</th> : null}</tr></thead><tbody>{rows.map((row, index) => <tr key={text(row.id ?? `${row.status}-${index}`)} className="border-b border-white/[0.04]">{keys.map(([key]) => <td key={key} className={`px-4 py-3 ${key === 'status' || key === 'freshness' ? tone(text(row[key])) : 'text-slate-300'}`}>{displayValue(key, row[key])}</td>)}{diagnosticsLabel ? <td className="px-4 py-3"><DiagnosticDetails ariaLabel={diagnosticsLabel} fields={keys.map(([key]) => [key, row[key]])} /></td> : null}</tr>)}</tbody></table></div>{rows.length === 0 ? <div className="p-12 text-center text-sm text-slate-600">暂无健康记录</div> : null}</div>;
}

export function Monitor() {
  const [params, setParams] = useSearchParams();
  const requested = params.get('tab') as Tab | null;
  const tab: Tab = TABS.some(([key]) => key === requested) ? requested! : 'overview';
  const [health, setHealth] = useState<MonitorHealth | null>(null);
  const [scope, setScope] = useState<DataScope>('business');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const load = useCallback(async () => { setBusy(true); setError(''); try { setHealth(await getMonitorHealth(scope)); } catch (reason) { setError(reason instanceof Error ? reason.message : '监控上下文加载失败'); } finally { setBusy(false); } }, [scope]);
  useEffect(() => { void load(); }, [load]);
  const scopedStrategyHealth = health?.strategy_health ?? [];
  const excludedCount = Object.values(health?.excluded_counts ?? {}).reduce((sum, count) => sum + Number(count || 0), 0);
  const activeStrategies = health ? scopedStrategyHealth.length : '--';
  const activeRisks = health ? health.risk_alerts.reduce((sum, item) => sum + Number(item.count ?? 0), 0) : '--';
  const delivered = health ? health.notifications.reduce((sum, item) => sum + Number(item.count ?? 0), 0) : '--';
  return <div className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8" data-testid="monitor-workbench" data-operator-page="monitor">
    <OperatorPageHeader
      icon={HeartPulse}
      title="监控中心"
      subtitle="同一策略实例的运行风控：总览 / 策略健康 / 数据健康 / 风险 / 通知。"
      actions={
        <button type="button" onClick={() => void load()} className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-400">
          <RefreshCw className={`h-4 w-4 ${busy ? 'animate-spin' : ''}`} />刷新健康快照
        </button>
      }
    />
    <WorkspacePipelineNote stageId="monitor" />
    <EvidenceStrip
      items={[
        { label: '状态', value: statusLabel(health?.status), tone: health?.status === 'healthy' ? 'green' : health?.status === 'critical' ? 'red' : 'amber' },
        { label: '来源', value: sourceLabel(health?.source_label, '本地运行证据') },
        { label: '最新证据', value: health?.source_updated_at ?? '--' },
        { label: '响应生成', value: health?.response_generated_at ?? '--' },
      ]}
    />
    <DataScopeControl value={scope} onChange={setScope} excludedCount={excludedCount} />
    <WorkspaceTabs ariaLabel="监控中心二级导航" items={TABS.map(([id, label]) => ({ id, label, testId: `monitor-tab-${id}` }))} value={tab} onChange={(id) => setParams({ tab: id })} />
    {error ? <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">{error}</div> : null}
    {tab === 'overview' ? <div className="space-y-5"><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[[Activity, '服务状态', health ? statusLabel(health.status) : '--', (health?.status === 'healthy' ? 'green' : health?.status === 'critical' ? 'red' : 'amber') as MetricTone], [HeartPulse, '策略实例', activeStrategies, countMetricColor(typeof activeStrategies === 'number' ? activeStrategies : Number(activeStrategies))], [ShieldAlert, '活动风险告警', activeRisks, (Number(activeRisks) > 0 ? 'red' : 'neutral') as MetricTone], [Bell, '通知投递', delivered, countMetricColor(typeof delivered === 'number' ? delivered : Number(delivered))]].map(([Icon, label, current, tone]) => { const Component = Icon as typeof Activity; return <div key={String(label)} className={`${panel} p-4`}><Component className={`h-5 w-5 ${tone === 'green' ? 'text-emerald-400' : tone === 'red' ? 'text-red-400' : tone === 'amber' ? 'text-amber-400' : 'text-blue-400'}`} /><div className="mt-3 text-xs text-slate-500">{String(label)}</div><div className="mt-2"><MetricValue tone={tone as MetricTone} size="xl">{String(current)}</MetricValue></div></div>; })}</div><section className={`${panel} p-5`}><h2 className="font-semibold text-white">健康边界</h2><div className="mt-4 grid gap-3 md:grid-cols-3"><div className="rounded-lg border border-crypto-border bg-crypto-bg p-4 text-sm text-slate-400">数据陈旧 ≠ 策略失败</div><div className="rounded-lg border border-crypto-border bg-crypto-bg p-4 text-sm text-slate-400">风险拒单保留规则版本</div><div className="rounded-lg border border-crypto-border bg-crypto-bg p-4 text-sm text-slate-400">通知确认不删除原始告警</div></div><p className="mt-4 text-xs text-slate-600">涨跌停风险、停牌、T+1 与参与率均在执行证据链中保留。</p></section></div> : null}
    {tab === 'strategy' ? <div className="space-y-4">
      {scopedStrategyHealth.map((item) => <article key={item.id} className={`${panel} p-5`}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div><div className="flex flex-wrap items-center gap-2"><h2 className="font-semibold text-white">{item.name}</h2><span className={`rounded border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] ${tone(item.health_state)}`}>{statusLabel(item.health_state)}</span></div><div className="mt-2 text-[10px] text-slate-500">最近交易日 {text(item.last_processed_trade_date)}</div></div>
          <Link to={`/paper?instance=${item.id}`} className="rounded-lg border border-crypto-border px-3 py-2 text-xs text-blue-300">Paper 证据链</Link>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[['运行状态', item.status], ['最后心跳', item.heartbeat_at], ['最后交易日', item.last_processed_trade_date], ['最后周期', item.latest_cycle_status], ['周期完成', item.latest_cycle_finished_at], ['最新权益', item.latest_equity], ['最新回撤', item.latest_drawdown], ['账本差额', item.latest_cycle_ledger_difference]].map(([label, current]) => { const isLifecycle = String(label) === '运行状态'; const isState = isLifecycle || String(label) === '最后周期'; const stateTone = isLifecycle && item.health_state !== 'fresh' ? item.health_state : text(current); return <div key={String(label)} className="rounded-lg border border-crypto-border bg-crypto-bg p-3"><div className="text-[10px] text-slate-600">{String(label)}</div><div className={`mt-1 break-all text-xs ${isState ? tone(stateTone) : 'text-slate-300'}`}>{isLifecycle ? `${statusLabel(current)}（生命周期）` : isState ? statusLabel(current) : text(current)}</div></div>; })}
        </div>
        <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-500"><span>订单 <strong className="text-slate-300">{item.order_count}</strong></span><span>成交 <strong className="text-slate-300">{item.trade_count}</strong></span><span>风险决策 <strong className="text-slate-300">{item.risk_event_count}</strong></span><span>拒绝 <strong className={item.rejected_count ? 'text-red-300' : 'text-slate-300'}>{item.rejected_count}</strong></span></div>
        {item.latest_cycle_error ? <div className="mt-3 rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-xs text-red-200">{item.latest_cycle_error}</div> : null}
      </article>)}
      {!scopedStrategyHealth.length ? <div className={`${panel} p-12 text-center text-sm text-slate-600`}>{busy ? '正在读取实例健康…' : '没有 Paper 实例健康证据'}</div> : null}
    </div> : null}
    {tab === 'data' ? <div className="grid gap-5 xl:grid-cols-2"><SnapshotPanel title="研究数据快照" toneClass="text-blue-400" snapshot={health?.data.dataset} /><SnapshotPanel title="市场证据快照" toneClass="text-violet-400" snapshot={health?.data.market} /><div className="xl:col-span-2"><Rows rows={health?.services ?? []} keys={[["service_code","服务"],["status","最近周期结果"],["freshness","当前新鲜度"],["last_success_at","最近成功"],["error_code","错误码"],["message","消息"],["observed_at","观察时间"]]} diagnosticsLabel="服务诊断原值" /></div></div> : null}
    {tab === 'risk' ? <div className="space-y-4"><Rows rows={health?.risk_alerts ?? []} keys={[["severity","级别"],["count","活动告警"]]} /><Rows rows={(health?.active_alerts ?? []) as unknown as Array<Record<string, unknown>>} keys={[["triggered_at","触发时间"],["severity","级别"],["category","类别"],["title","告警"],["instance_name","关联策略"]]} /><div className={`${panel} flex items-center justify-between p-5`}><div><h2 className="font-semibold text-white">风险告警证据</h2><p className="mt-1 text-xs text-slate-500">在观察台确认告警，在模拟盘查看对应实例、订单与规则链。</p></div><Link to="/watch?tab=alerts" className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white">打开观察台</Link></div></div> : null}
    {tab === 'notifications' ? <Rows rows={health?.notifications ?? []} keys={[["status","投递状态"],["count","数量"]]} /> : null}
  </div>;
}

export default Monitor;
