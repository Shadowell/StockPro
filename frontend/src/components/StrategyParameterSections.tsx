import { useState } from 'react';
import { ChevronDown, Settings2, ShieldCheck } from 'lucide-react';
import clsx from 'clsx';
import type { StrategyParameterItem, StrategyParameterSections as StrategyParameterSectionsData } from '../utils/strategyConfigDisplay';

interface ParameterPanelProps {
  title: string;
  subtitle: string;
  items: StrategyParameterItem[];
  tone: 'logic' | 'risk';
}

function joinParameterSummary(items: StrategyParameterItem[]): string {
  if (items.length === 0) return '暂无核心参数。';
  return `${items.map((item) => `${item.label}：${item.value}`).join('；')}。`;
}

function ParameterPanel({ title, subtitle, items, tone }: ParameterPanelProps) {
  const logicTone = tone === 'logic';
  const Icon = logicTone ? Settings2 : ShieldCheck;
  return (
    <div className={clsx('min-w-0 pl-4', logicTone ? 'border-l border-blue-500/40' : 'border-l border-emerald-500/40')}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className={clsx('flex items-center gap-2 text-sm font-semibold', logicTone ? 'text-blue-300' : 'text-emerald-300')}>
          <Icon className="h-4 w-4 shrink-0" />
          {title}
        </div>
        <span className="shrink-0 text-xs font-semibold text-gray-500">{items.length} 项</span>
      </div>
      <p className="text-sm leading-7 text-gray-300" aria-label={`${title}参数摘要`}>
        {joinParameterSummary(items)}
      </p>
      <p className="mt-1 text-xs leading-relaxed text-gray-500">{subtitle}</p>
    </div>
  );
}

export default function StrategyParameterSections({
  sections,
  className,
}: {
  sections: StrategyParameterSectionsData;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const tradingCount = sections.trading.length;
  const riskCount = sections.risk.length;

  return (
    <section className={clsx('rounded-xl border border-crypto-border bg-crypto-card/80', className)}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors hover:bg-white/[0.03]"
      >
        <span className="flex min-w-0 items-center gap-2">
          <Settings2 className="h-4 w-4 shrink-0 text-cyan-300" />
          <span className="truncate text-base font-semibold text-white">策略参数配置</span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[11px] font-semibold text-blue-200">
            交易逻辑 {tradingCount}
          </span>
          <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-200">
            风控 {riskCount}
          </span>
          <ChevronDown
            className={clsx('h-4 w-4 text-gray-500 transition-transform', open && 'rotate-180 text-gray-300')}
          />
        </span>
      </button>

      {open && (
        <div className="border-t border-crypto-border px-4 pb-4 pt-4">
          <div className="grid gap-5 lg:grid-cols-2">
            <ParameterPanel
              title="交易逻辑参数配置"
              subtitle="仅展示影响信号、交易池与触发条件的核心配置"
              items={sections.trading}
              tone="logic"
            />
            <ParameterPanel
              title="风控参数配置"
              subtitle="仅展示影响资金、杠杆、仓位与止盈止损的核心配置"
              items={sections.risk}
              tone="risk"
            />
          </div>
        </div>
      )}
    </section>
  );
}
