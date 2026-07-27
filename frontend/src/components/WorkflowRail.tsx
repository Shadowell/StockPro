import { useEffect, useMemo, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, CircleDashed, ShieldCheck } from 'lucide-react';
import { StatusBadge } from '@bitpro/ui';
import clsx from 'clsx';

import { getWorkflowCapabilities } from '../api/client';
import type { WorkflowCapabilities, WorkflowStageCapability } from '../types';


const WORKFLOW_ROUTES = ['/strategy', '/backtest', '/ai-lab', '/paper', '/watch', '/monitor', '/review'];

const statusIcon = (status: WorkflowStageCapability['status']) => {
  if (status === 'available') return CheckCircle2;
  if (status === 'partial') return CircleDashed;
  return AlertTriangle;
};

export function WorkflowRail() {
  const location = useLocation();
  const [capabilities, setCapabilities] = useState<WorkflowCapabilities | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const visible = WORKFLOW_ROUTES.some((route) => location.pathname.startsWith(route));

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    setState('loading');
    getWorkflowCapabilities()
      .then((result) => {
        if (cancelled) return;
        setCapabilities(result);
        setState('ready');
      })
      .catch(() => {
        if (!cancelled) {
          setCapabilities(null);
          setState('error');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [visible]);

  const activeStage = useMemo(() => {
    if (location.pathname.startsWith('/ai-lab')) return 'strategy';
    return capabilities?.stages.find((stage) => location.pathname.startsWith(stage.route))?.id;
  }, [capabilities?.stages, location.pathname]);

  if (!visible) return null;

  return (
    <section
      className="border-b border-crypto-border bg-crypto-panel/95 px-3 py-2 lg:px-4"
      aria-label="BitPro 同构策略生命周期"
      data-testid="workflow-rail"
    >
      <div className="flex min-w-0 items-center gap-3">
        <div className="hidden shrink-0 items-center gap-2 xl:flex">
          <ShieldCheck className="h-4 w-4 text-blue-300" />
          <div>
            <div className="text-[11px] font-black text-slate-200">策略生命周期</div>
            <div className="font-mono text-[9px] text-slate-600">
              {capabilities?.contract_version || 'stockpro-workflow-v1'}
            </div>
          </div>
        </div>

        <div className="min-w-0 flex-1 overflow-x-auto">
          <div className="flex min-w-max items-center gap-1">
            {state === 'ready' && capabilities
              ? capabilities.stages.map((stage, index) => {
                  const Icon = statusIcon(stage.status);
                  const active = activeStage === stage.id;
                  return (
                    <div key={stage.id} className="flex items-center gap-1">
                      {index > 0 ? <span className="h-px w-3 bg-slate-700" aria-hidden="true" /> : null}
                      <NavLink
                        to={stage.route}
                        title={stage.reason || `${stage.label}阶段可用`}
                        className={clsx(
                          'inline-flex h-7 items-center gap-1.5 rounded-[6px] border px-2.5 text-[11px] font-bold transition-colors',
                          active
                            ? 'border-blue-500/55 bg-blue-500/15 text-blue-100'
                            : 'border-transparent text-slate-500 hover:border-crypto-border hover:bg-slate-800/70 hover:text-slate-200',
                        )}
                      >
                        <Icon className={clsx('h-3.5 w-3.5', stage.status === 'available' ? 'text-emerald-400' : 'text-amber-400')} />
                        {stage.label}
                      </NavLink>
                    </div>
                  );
                })
              : (
                <div className={clsx('px-2 text-[11px]', state === 'error' ? 'text-amber-300' : 'text-slate-500')}>
                  {state === 'error' ? '流程能力契约不可用，不能确认阶段状态' : '正在读取流程能力…'}
                </div>
              )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          <StatusBadge tone="blue">仅模拟盘</StatusBadge>
          <StatusBadge tone="amber">实盘未接入</StatusBadge>
        </div>
      </div>
    </section>
  );
}
