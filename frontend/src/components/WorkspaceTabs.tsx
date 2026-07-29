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

/** BitPro-dense L2 workspace tabs — shared by every primary page with subviews. */
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
        'mb-4 flex items-center gap-5 overflow-x-auto border-b border-crypto-border px-1',
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
              '-mb-px inline-flex h-10 shrink-0 items-center gap-2 border-b-2 px-0.5 text-sm font-medium transition-colors',
              active
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-300',
            )}
          >
            {Icon ? <Icon className={clsx('h-4 w-4', active ? 'text-blue-500' : 'text-gray-600')} /> : null}
            <span>{item.label}</span>
            {item.badge !== undefined ? (
              <span
                className={clsx(
                  'rounded-md px-1.5 py-0.5 text-[10px] tabular-nums',
                  active ? 'bg-blue-500/15 text-blue-200' : 'bg-slate-800 text-slate-500',
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
