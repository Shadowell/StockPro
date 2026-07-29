import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import clsx from 'clsx';

export type WorkspaceTabItem<T extends string> = {
  id: T;
  label: string;
  icon?: LucideIcon;
  badge?: ReactNode;
  testId?: string;
};

/** Tremor-styled L2 / L3 workspace tabs — capsule chips with smooth micro-animations. */
export function WorkspaceTabs<T extends string>({
  items,
  value,
  onChange,
  ariaLabel,
  className = '',
}: {
  items: ReadonlyArray<WorkspaceTabItem<T>>;
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
  className?: string;
}) {
  return (
    <nav
      role="tablist"
      aria-label={ariaLabel}
      data-operator-workspace-tabs="true"
      className={clsx(
        'mb-4 flex items-center gap-1.5 overflow-x-auto rounded-xl border border-crypto-border bg-crypto-card/90 p-1.5 backdrop-blur-sm',
        className,
      )}
    >
      {items.map((item) => {
        const active = item.id === value;
        const Icon = item.icon;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={active}
            data-testid={item.testId}
            onClick={() => onChange(item.id)}
            className={clsx(
              'inline-flex h-9 shrink-0 items-center gap-2 rounded-lg px-3.5 text-xs font-bold transition-all duration-150 active:scale-95',
              active
                ? 'bg-blue-600 text-white shadow-md shadow-blue-950/60 border border-blue-400/30'
                : 'border border-transparent bg-crypto-bg/60 text-gray-400 hover:border-crypto-border hover:bg-slate-800/70 hover:text-gray-200',
            )}
          >
            {Icon ? <Icon className={clsx('h-3.5 w-3.5 transition-transform group-hover:scale-110', active ? 'text-white' : 'text-gray-500')} /> : null}
            <span>{item.label}</span>
            {item.badge !== undefined ? (
              <span
                className={clsx(
                  'rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums',
                  active ? 'bg-white/20 text-white' : 'bg-slate-800 text-slate-400',
                )}
              >
                {item.badge}
              </span>
            ) : null}
          </button>
        );
      })}
    </nav>
  );
}

export default WorkspaceTabs;
