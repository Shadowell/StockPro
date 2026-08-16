import { useNavigate } from 'react-router-dom';
import { ArrowRight, FlaskConical, GitBranch, Layers3, Play } from 'lucide-react';
import { StatusBadge } from '@bitpro/ui';
import clsx from 'clsx';

import type { ResearchDeskStage } from '../types';
import { MetricValue } from './OperatorShell';
import { useResearchDesk } from './ResearchDeskContext';

const statusTone = (status: ResearchDeskStage['status']) => {
  if (status === 'available') return 'border-emerald-500/25 bg-emerald-500/[0.06] text-emerald-200';
  if (status === 'partial') return 'border-amber-500/25 bg-amber-500/[0.06] text-amber-200';
  return 'border-crypto-border bg-crypto-bg/60 text-slate-400';
};

const statusLabel = (status: ResearchDeskStage['status']) => {
  if (status === 'available') return '就绪';
  if (status === 'partial') return '部分';
  return '待补';
};

export function ResearchDeskPanel() {
  const navigate = useNavigate();
  const { desk, error } = useResearchDesk();

  const strategy = desk?.active_strategy;
  const backtest = desk?.latest_backtest;
  const paper = desk?.latest_paper;
  const bindings = desk?.bindings;
  const pipelinePaper = Boolean(
    paper && (
      String(paper.name || '').includes('多因子')
      || Boolean(strategy?.name && String(paper.name || '').includes(strategy.name))
    ),
  );
  const promotionLabel = (() => {
    const status = backtest?.promotion_status;
    if (status === 'paper_eligible') return '可晋级 Paper';
    if (status === 'not_eligible_quick') return '快速预检不可晋级';
    if (status === 'rejected') return '晋级未通过';
    if (backtest?.run_mode === 'quick') return '快速预检';
    if (backtest?.status === 'success') return '成功，待评估';
    return backtest?.status || '未跑';
  })();

  return (
    <section
      className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card"
      data-testid="research-desk"
      aria-label="量化研究台"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-crypto-border px-4 py-3">
        <div>
          <h2 className="text-base font-black text-white">量化研究台</h2>
          <p className="mt-1 text-xs text-gray-500">
            同一条多因子风险预算链路：数据 → 因子 → 股票池 → 策略 → 回测 → 模拟 → 盯盘 / 复盘
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone={desk?.trade_date ? 'green' : 'amber'}>
            {desk?.trade_date ? `证据日 ${desk.trade_date}` : '证据日未封存'}
          </StatusBadge>
          {desk?.next_action ? (
            <button
              type="button"
              onClick={() => navigate(desk.next_action.route)}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-blue-600 px-3 text-xs font-semibold text-white hover:bg-blue-500"
            >
              {desk.next_action.label}
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </div>
      </div>

      {error ? (
        <div className="px-4 py-3 text-sm text-amber-200">{error}</div>
      ) : null}

      <div className="grid gap-3 p-4 lg:grid-cols-[1.4fr_1fr]">
        <div className="min-w-0">
          <div className="mb-2 text-[11px] font-semibold text-slate-500">研究链路状态</div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {(desk?.pipeline ?? []).map((stage) => (
              <button
                key={stage.id}
                type="button"
                onClick={() => navigate(stage.route)}
                className={clsx('rounded-lg border px-2.5 py-2 text-left transition hover:border-blue-500/40', statusTone(stage.status))}
                title={stage.detail}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-bold">{stage.label}</span>
                  <span className="text-[9px]">{statusLabel(stage.status)}</span>
                </div>
                <div className="mt-1 truncate text-[10px] text-slate-500">{stage.detail}</div>
              </button>
            ))}
            {!desk ? (
              <div className="col-span-full rounded-lg border border-crypto-border px-3 py-6 text-center text-xs text-slate-500">
                正在读取研究台计数…
              </div>
            ) : null}
          </div>
          {desk?.next_action ? (
            <p className="mt-3 text-[11px] leading-5 text-slate-500">{desk.next_action.reason}</p>
          ) : null}
        </div>

        <div className="grid gap-2">
          <div className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3">
            <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold text-slate-500">
              <GitBranch className="h-3.5 w-3.5 text-blue-300" />
              当前策略
            </div>
            <div className="truncate text-sm font-semibold text-slate-100">{strategy?.name || '尚未保存策略版本'}</div>
            <div className="mt-1 line-clamp-2 text-[11px] text-slate-500">
              {strategy?.description || '从策略广场打开「多因子风险预算」即可进入同一条研究链路。'}
            </div>
            <button
              type="button"
              onClick={() => navigate(strategy ? `/strategy?strategy=${strategy.id}&view=detail` : '/strategy?tab=plaza')}
              className="mt-3 inline-flex items-center gap-1 text-[11px] font-semibold text-blue-300 hover:text-blue-200"
            >
              打开策略
              <ArrowRight className="h-3 w-3" />
            </button>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3">
              <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold text-slate-500">
                <FlaskConical className="h-3.5 w-3.5 text-blue-300" />
                最新回测
              </div>
              <MetricValue tone={backtest?.promotion_status === 'paper_eligible' ? 'up' : backtest?.status === 'success' ? 'amber' : 'neutral'} size="sm">
                {promotionLabel}
              </MetricValue>
              <div className="mt-1 truncate text-[10px] text-slate-500">
                {backtest?.strategy_name || backtest?.name || '还没有回测证据'}
              </div>
              <button
                type="button"
                onClick={() => navigate(backtest?.id ? `/backtest/${backtest.id}` : '/backtest')}
                className="mt-2 text-[11px] font-semibold text-blue-300"
              >
                回测台
              </button>
            </div>
            <div className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3">
              <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold text-slate-500">
                <Play className="h-3.5 w-3.5 text-emerald-300" />
                Paper
              </div>
              <MetricValue tone={pipelinePaper ? 'blue' : 'neutral'} size="sm">
                {pipelinePaper ? paper?.status : '未创建'}
              </MetricValue>
              <div className="mt-1 truncate text-[10px] text-slate-500">
                {pipelinePaper ? paper?.name : paper ? '现有实例属于其他策略，本策略尚未晋级' : '等待晋级回测'}
              </div>
              <button
                type="button"
                onClick={() => navigate('/paper')}
                className="mt-2 text-[11px] font-semibold text-blue-300"
              >
                模拟盘
              </button>
            </div>
          </div>
          <div className="rounded-lg border border-crypto-border bg-crypto-bg/50 px-3 py-2 text-[11px] text-slate-500">
            <Layers3 className="mr-1 inline h-3.5 w-3.5 text-slate-400" />
            证据截止：市场 {desk?.trade_date || '--'}
            {bindings?.pool_trade_date ? ` · 股票池 ${String(bindings.pool_trade_date).slice(0, 10)}` : ''}
            {bindings?.dataset_snapshot_id ? ` · 数据快照 #${bindings.dataset_snapshot_id}` : ''}
            。首页行情是缓存，不是盘中推送。
          </div>
        </div>
      </div>
    </section>
  );
}
