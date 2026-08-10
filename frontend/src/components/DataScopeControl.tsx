import { ShieldCheck } from 'lucide-react';
import clsx from 'clsx';

import type { DataScope } from '../types';

export function DataScopeControl({
  value,
  onChange,
  excludedCount = 0,
}: {
  value: DataScope;
  onChange: (value: DataScope) => void;
  excludedCount?: number;
}) {
  return (
    <div
      className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-crypto-border bg-crypto-card px-4 py-3"
      data-testid="data-scope-control"
    >
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <ShieldCheck className="h-4 w-4 text-blue-400" />
        <span>
          {value === 'business'
            ? `业务视图已隔离验收证据${excludedCount ? `（排除 ${excludedCount} 条）` : ''}`
            : '审计视图包含业务、验收与种子证据，不改变原始记录'}
        </span>
      </div>
      <div className="inline-flex rounded-lg border border-crypto-border bg-crypto-bg p-1" role="group" aria-label="数据范围">
        {([
          ['business', '业务视图'],
          ['audit', '审计视图'],
        ] as const).map(([scope, label]) => (
          <button
            key={scope}
            type="button"
            aria-pressed={value === scope}
            onClick={() => onChange(scope)}
            className={clsx(
              'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
              value === scope
                ? 'bg-blue-600 text-white'
                : 'text-slate-500 hover:text-slate-300',
            )}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
