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

/**
 * Tremor-style L2 / L3 views use an underline tab rail.  A workspace switch
 * changes the page context, so it must not look like a filter or a row of
 * primary-action buttons.
 */
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
        'mb-5 flex min-w-0 items-end gap-5 overflow-x-auto border-b border-crypto-border px-1',
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
              '-mb-px inline-flex h-10 shrink-0 items-center gap-2 border-b-2 px-1 text-xs font-semibold transition-colors sm:text-sm',
              active
                ? 'border-blue-400 text-slate-100'
                : 'border-transparent text-gray-500 hover:border-slate-600 hover:text-slate-200',
            )}
          >
            {Icon ? <Icon className={clsx('h-3.5 w-3.5', active ? 'text-blue-300' : 'text-gray-500')} /> : null}
            <span>{item.label}</span>
            {item.badge !== undefined ? (
              <span
                className={clsx(
                  'rounded-md px-1.5 py-0.5 text-[10px] font-semibold tabular-nums',
                  active ? 'bg-blue-500/15 text-blue-200' : 'bg-crypto-card text-slate-500',
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
