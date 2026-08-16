import { useNavigate } from 'react-router-dom';
import { ArrowRight, GitBranch } from 'lucide-react';
import { StatusBadge } from '@bitpro/ui';
import clsx from 'clsx';

import { PIPELINE_STAGE_ROLE, PIPELINE_STRATEGY_NAME } from '../lib/pipeline';
import { useResearchDesk } from './ResearchDeskContext';

const statusTone = (status?: string) => {
  if (status === 'available') return 'green' as const;
  if (status === 'partial') return 'amber' as const;
  return 'neutral' as const;
};

const statusLabel = (status?: string) => {
  if (status === 'available') return '本页就绪';
  if (status === 'partial') return '本页部分';
  if (status === 'empty') return '本页待补';
  return '读取中';
};

export function WorkspacePipelineNote({ stageId }: { stageId: string }) {
  const navigate = useNavigate();
  const { desk, state } = useResearchDesk();
  const stage = desk?.pipeline.find((item) => item.id === stageId);
  const strategyName = desk?.active_strategy?.name || PIPELINE_STRATEGY_NAME;
  const bindings = desk?.bindings;

  const bindingText = (() => {
    if (stageId === 'factors' && bindings?.factor_codes?.length) {
      return `链路因子 ${bindings.factor_ready ?? 0}/${bindings.factor_codes.length}`;
    }
    if (stageId === 'pools' && bindings?.pool_snapshot_id) {
      return `快照 #${bindings.pool_snapshot_id}${bindings.pool_trade_date ? ` · ${String(bindings.pool_trade_date).slice(0, 10)}` : ''}`;
    }
    if (stageId === 'data' && bindings?.dataset_snapshot_id) {
      return `数据快照 #${bindings.dataset_snapshot_id}`;
    }
    if (stageId === 'strategy' && bindings?.strategy_version_id) {
      return `版本 ${String(bindings.strategy_version_id).slice(0, 8)} · ${bindings.strategy_version_status || 'draft'}`;
    }
    if (stageId === 'backtest' && desk?.latest_backtest) {
      return `${desk.latest_backtest.strategy_name || desk.latest_backtest.name || '最近一次'} · ${desk.latest_backtest.status}`;
    }
    if ((stageId === 'paper' || stageId === 'watch' || stageId === 'monitor') && desk?.latest_paper) {
      const paperName = String(desk.latest_paper.name || '');
      if (paperName.includes('多因子') || paperName.includes(strategyName)) {
        return `${paperName || 'Paper'} · ${desk.latest_paper.status}`;
      }
      return '本策略尚未晋级 Paper；现有实例属于其他策略';
    }
    return stage?.detail || '等待研究台计数';
  })();

  return (
    <div
      className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-crypto-border bg-crypto-card/80 px-3 py-2"
      data-testid="workspace-pipeline-note"
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <GitBranch className="h-3.5 w-3.5 text-blue-300" />
          <span className="text-[11px] font-semibold text-slate-200">{strategyName}</span>
          <StatusBadge tone={statusTone(stage?.status)}>{statusLabel(state === 'ready' ? stage?.status : undefined)}</StatusBadge>
          <span className="truncate font-mono text-[10px] text-slate-500">{bindingText}</span>
        </div>
        <p className="mt-1 max-w-3xl text-[11px] leading-5 text-slate-500">
          {PIPELINE_STAGE_ROLE[stageId] || '同一条多因子风险预算链路中的工作台。'}
        </p>
      </div>
      {desk?.next_action && desk.next_action.route !== (stage?.route || `/${stageId}`) ? (
        <button
          type="button"
          onClick={() => navigate(desk.next_action.route)}
          className={clsx(
            'inline-flex h-7 shrink-0 items-center gap-1 rounded-md border border-blue-500/35 bg-blue-500/10 px-2.5 text-[11px] font-semibold text-blue-200 hover:bg-blue-500/20',
          )}
        >
          {desk.next_action.label}
          <ArrowRight className="h-3 w-3" />
        </button>
      ) : null}
    </div>
  );
}
