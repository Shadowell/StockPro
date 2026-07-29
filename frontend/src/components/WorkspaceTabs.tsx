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

/** BitPro-dense L2 workspace tabs — capsule chips with filled active state. */
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
        'mb-4 flex items-center gap-1.5 overflow-x-auto rounded-xl border border-crypto-border bg-crypto-card p-1.5',
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
              'inline-flex h-9 shrink-0 items-center gap-2 rounded-full px-3.5 text-sm font-semibold transition-colors',
              active
                ? 'bg-blue-600 text-white shadow-sm shadow-blue-900/40'
                : 'bg-crypto-bg/80 text-gray-400 hover:bg-slate-800 hover:text-gray-200',
            )}
          >
            {Icon ? <Icon className={clsx('h-4 w-4', active ? 'text-white' : 'text-gray-500')} /> : null}
            <span>{item.label}</span>
            {item.badge !== undefined ? (
              <span
                className={clsx(
                  'rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums',
                  active ? 'bg-white/20 text-white' : 'bg-slate-800 text-slate-500',
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
