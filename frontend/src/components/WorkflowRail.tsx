import { useMemo } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { AlertTriangle, ArrowRight, CheckCircle2, CircleDashed, ShieldCheck } from 'lucide-react';
import { StatusBadge } from '@bitpro/ui';
import clsx from 'clsx';

import { PIPELINE_STRATEGY_NAME } from '../lib/pipeline';
import type { ResearchDeskStage } from '../types';
import { useResearchDesk } from './ResearchDeskContext';

const statusIcon = (status: ResearchDeskStage['status']) => {
  if (status === 'available') return CheckCircle2;
  if (status === 'partial') return CircleDashed;
  return AlertTriangle;
};

export function WorkflowRail() {
  const location = useLocation();
  const navigate = useNavigate();
  const { desk, state } = useResearchDesk();

  const activeStage = useMemo(() => {
    const pipeline = Array.isArray(desk?.pipeline) ? desk.pipeline : [];
    return pipeline.find((stage) =>
      stage.route === '/'
        ? location.pathname === '/'
        : location.pathname === stage.route || location.pathname.startsWith(`${stage.route}/`),
    )?.id;
  }, [desk, location.pathname]);

  return (
    <section
      className="border-b border-crypto-border bg-crypto-panel/95 px-3 py-2 lg:px-4"
      aria-label="量化研究链路"
      data-testid="workflow-rail"
    >
      <div className="flex min-w-0 items-center gap-3">
        <div className="hidden shrink-0 items-center gap-2 xl:flex">
          <ShieldCheck className="h-4 w-4 text-blue-300" />
          <div>
            <div className="text-[11px] font-black text-slate-200">量化研究链路</div>
            <div className="max-w-[220px] truncate font-mono text-[9px] text-slate-600">
              {desk?.active_strategy?.name || PIPELINE_STRATEGY_NAME}
              {desk?.trade_date ? ` · 证据日 ${desk.trade_date}` : ''}
              {desk?.bindings?.pool_trade_date ? ` · 池 ${String(desk.bindings.pool_trade_date).slice(0, 10)}` : ''}
            </div>
          </div>
        </div>

        <div className="min-w-0 flex-1 overflow-x-auto">
          <div className="flex min-w-max items-center gap-1">
            {state === 'ready' && desk
              ? desk.pipeline.map((stage, index) => {
                  const Icon = statusIcon(stage.status);
                  const active = activeStage === stage.id;
                  return (
                    <div key={stage.id} className="flex items-center gap-1">
                      {index > 0 ? <span className="h-px w-3 bg-slate-700" aria-hidden="true" /> : null}
                      <NavLink
                        to={stage.route}
                        title={stage.detail || stage.label}
                        className={clsx(
                          'inline-flex h-7 items-center gap-1.5 rounded-[6px] border px-2.5 text-[11px] font-bold transition-colors',
                          active
                            ? 'border-blue-500/55 bg-blue-500/15 text-blue-100'
                            : 'border-transparent text-slate-500 hover:border-crypto-border hover:bg-slate-800/70 hover:text-slate-200',
                        )}
                      >
                        <Icon
                          className={clsx(
                            'h-3.5 w-3.5',
                            stage.status === 'available'
                              ? 'text-emerald-400'
                              : stage.status === 'partial'
                                ? 'text-amber-400'
                                : 'text-slate-500',
                          )}
                        />
                        {stage.label}
                      </NavLink>
                    </div>
                  );
                })
              : (
                <div className={clsx('px-2 text-[11px]', state === 'error' ? 'text-amber-300' : 'text-slate-500')}>
                  {state === 'error' ? '研究链路不可用' : '正在读取研究链路…'}
                </div>
              )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          {desk?.next_action ? (
            <button
              type="button"
              onClick={() => navigate(desk.next_action.route)}
              title={desk.next_action.reason}
              className="hidden h-7 items-center gap-1 rounded-[6px] border border-blue-500/40 bg-blue-500/10 px-2.5 text-[11px] font-bold text-blue-200 hover:bg-blue-500/20 lg:inline-flex"
            >
              {desk.next_action.label}
              <ArrowRight className="h-3 w-3" />
            </button>
          ) : null}
          <StatusBadge tone="blue">仅模拟盘</StatusBadge>
          <StatusBadge tone="amber">实盘未接入</StatusBadge>
        </div>
      </div>
    </section>
  );
}
