import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

export type WorkspaceTabItem<T extends string> = {
  id: T;
  label: string;
  icon?: LucideIcon;
  badge?: ReactNode;
  testId?: string;
};

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
      className={`flex items-center gap-6 overflow-x-auto border-b border-crypto-border px-1 ${className}`}
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
            className={`-mb-px inline-flex h-11 shrink-0 items-center gap-2 border-b-2 px-1 text-sm font-medium transition-colors ${
              active
                ? 'border-blue-400 text-white'
                : 'border-transparent text-slate-500 hover:border-slate-700 hover:text-slate-200'
            }`}
          >
            {Icon ? <Icon className={`h-4 w-4 ${active ? 'text-blue-300' : 'text-slate-600'}`} /> : null}
            <span>{item.label}</span>
            {item.badge !== undefined ? (
              <span className={`rounded-md px-1.5 py-0.5 text-[10px] tabular-nums ${
                active ? 'bg-blue-500/15 text-blue-200' : 'bg-slate-800 text-slate-500'
              }`}>
                {item.badge}
              </span>
            ) : null}
          </button>
        );
      })}
    </nav>
  );
}
