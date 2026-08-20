import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, CircleAlert, ClipboardList, Settings2 } from 'lucide-react';
import { getOnboardingReadiness } from '../api/client';
import type { OnboardingReadiness } from '../types';

export function OnboardingReadinessPanel() {
  const [data, setData] = useState<OnboardingReadiness | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { getOnboardingReadiness().then(setData).catch((reason) => setError(reason instanceof Error ? reason.message : '首次配置状态加载失败')); }, []);
  return <section className="mb-5 rounded-xl border border-crypto-border bg-crypto-card p-5" data-testid="onboarding-readiness">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex items-center gap-2"><Settings2 className="h-5 w-5 text-blue-300" /><h2 className="font-semibold text-white">首次就绪检查</h2></div><p className="mt-1 text-xs text-slate-500">只读检查配置和 PostgreSQL 证据；不会自动同步、迁移、创建策略或启动模拟盘。</p></div><div className="flex gap-2"><Link to="/review" className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border px-3 text-xs text-blue-300"><ClipboardList className="h-3.5 w-3.5" />统一复盘</Link><span className={`inline-flex h-9 items-center rounded-lg border px-3 text-xs font-semibold ${data?.status === 'ready' ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200' : 'border-amber-500/25 bg-amber-500/10 text-amber-200'}`}>{data ? `必需项 ${data.required_ready}/${data.required_total}` : error ? '检查失败' : '检查中'}</span></div></div>
    {error ? <div className="mt-4 rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-200">{error}</div> : null}
    {data ? <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">{data.steps.map((step) => <Link key={step.code} to={step.action_route} className={`rounded-lg border p-3 ${step.status === 'ready' ? 'border-emerald-500/15 bg-emerald-500/[0.04]' : 'border-amber-500/20 bg-amber-500/[0.05]'}`}><div className="flex items-center justify-between gap-2"><span className="text-sm font-semibold text-white">{step.label}</span>{step.status === 'ready' ? <CheckCircle2 className="h-4 w-4 text-emerald-300" /> : <CircleAlert className="h-4 w-4 text-amber-300" />}</div><p className="mt-2 text-xs leading-5 text-slate-500">{step.detail}</p><span className="mt-2 block text-[10px] text-slate-600">{step.required ? '必需' : '后续阶段'} · 查看下一步 →</span></Link>)}</div> : null}
  </section>;
}
