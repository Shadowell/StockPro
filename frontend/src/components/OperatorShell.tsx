import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import clsx from 'clsx';
import { MetricCard, StatusBadge } from '@bitpro/ui';
import { AlertCircle, Inbox, Lock, RefreshCw } from 'lucide-react';
import {
  metricToneClass,
  type MetricTone,
} from '../utils/marketColors';

/** Shared StockPro operator-shell primitives aligned to BitPro density. */

/** BitPro MetricCard value rhythm: mono + tabular + semantic tone (never flat white). */
export function MetricValue({
  children,
  tone = 'blue',
  size = 'lg',
  className,
  title,
}: {
  children: ReactNode;
  tone?: MetricTone;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  className?: string;
  title?: string;
}) {
  const sizeClass =
    size === 'sm'
      ? 'text-sm'
      : size === 'md'
        ? 'text-base'
        : size === 'xl'
          ? 'text-2xl'
          : 'text-xl';
  return (
    <span
      title={title}
      className={clsx(
        'font-mono font-bold tabular-nums tracking-tight',
        sizeClass,
        metricToneClass(tone),
        className,
      )}
    >
      {children}
    </span>
  );
}

export function OperatorMetricCard({
  label,
  value,
  detail,
  icon,
  tone = 'blue',
  className,
}: {
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
  icon?: ReactNode;
  tone?: MetricTone;
  className?: string;
}) {
  const cardTone: MetricTone = tone === 'neutral' ? 'blue' : tone;
  const renderedValue =
    typeof value === 'string' || typeof value === 'number' ? (
      <MetricValue tone={cardTone}>{value}</MetricValue>
    ) : (
      value
    );
  return (
    <MetricCard
      label={label}
      value={renderedValue}
      detail={detail}
      icon={icon}
      color={cardTone}
      className={className}
    />
  );
}

export function OperatorPageHeader({
  icon: Icon,
  title,
  subtitle,
  actions,
  className,
}: {
  icon?: LucideIcon;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx('mb-5 flex flex-wrap items-start justify-between gap-4', className)}>
      <div className="min-w-0">
        <div className="flex items-center gap-3">
          {Icon ? <Icon className="h-6 w-6 shrink-0 text-blue-400" /> : null}
          <h1 className="text-2xl font-bold text-white">{title}</h1>
        </div>
        {subtitle ? <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-500">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export type SegmentedOption<T extends string> = {
  value: T;
  label: ReactNode;
  icon?: LucideIcon;
  count?: number | string;
  tone?: 'blue' | 'purple' | 'emerald' | 'amber';
  testId?: string;
};

const toneActive: Record<NonNullable<SegmentedOption<string>['tone']>, string> = {
  blue: 'bg-blue-500/20 text-blue-300',
  purple: 'bg-purple-500/20 text-purple-300',
  emerald: 'bg-emerald-500/20 text-emerald-300',
  amber: 'bg-amber-500/20 text-amber-300',
};

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  size = 'md',
  className,
  'aria-label': ariaLabel,
}: {
  options: ReadonlyArray<SegmentedOption<T>>;
  value: T;
  onChange: (value: T) => void;
  size?: 'sm' | 'md';
  className?: string;
  'aria-label'?: string;
}) {
  const height = size === 'sm' ? 'h-9' : 'h-10';
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={clsx(
        'inline-flex w-fit max-w-full flex-wrap items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card p-1',
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        const Icon = option.icon;
        const tone = option.tone ?? 'blue';
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={active}
            data-testid={option.testId}
            onClick={() => onChange(option.value)}
            className={clsx(
              'inline-flex items-center gap-2 rounded-lg px-3 text-xs font-semibold transition-all duration-150 active:scale-95 sm:px-4 sm:text-sm',
              height,
              active ? toneActive[tone] + ' shadow-sm shadow-blue-950/50' : 'text-gray-400 hover:text-gray-200 hover:bg-slate-800/60',
            )}
          >
            {Icon ? <Icon className="h-4 w-4" /> : null}
            <span>{option.label}</span>
            {option.count !== undefined ? (
              <span
                className={clsx(
                  'rounded-md px-1.5 py-0.5 text-[10px] tabular-nums',
                  active ? 'bg-white/10 text-inherit' : 'bg-crypto-bg text-gray-500',
                )}
              >
                {option.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export function FilterChipGroup<T extends string>({
  options,
  value,
  onChange,
  className,
  'aria-label': ariaLabel,
}: {
  options: ReadonlyArray<SegmentedOption<T>>;
  value: T;
  onChange: (value: T) => void;
  className?: string;
  'aria-label'?: string;
}) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={clsx(
        'inline-flex h-11 max-w-full flex-wrap items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card/80 p-1',
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            data-testid={option.testId}
            onClick={() => onChange(option.value)}
            className={clsx(
              'inline-flex h-9 min-w-[3.5rem] items-center justify-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold transition-colors',
              active ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:bg-white/5 hover:text-gray-300',
            )}
          >
            <span>{option.label}</span>
            {option.count !== undefined ? (
              <span
                className={clsx(
                  'rounded-md px-1.5 py-0.5 text-[10px] tabular-nums',
                  active ? 'bg-blue-400/15 text-blue-200' : 'bg-crypto-bg text-gray-500',
                )}
              >
                {option.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export function OperatorFilterBar({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx('mb-4 flex flex-wrap items-center gap-2', className)}>
      {children}
    </div>
  );
}

export function OperatorSearchField({
  value,
  onChange,
  placeholder,
  className,
  icon,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  icon?: ReactNode;
}) {
  return (
    <label
      className={clsx(
        'relative flex h-11 w-full min-w-[220px] max-w-md items-center gap-2 rounded-xl border border-crypto-border bg-crypto-card px-3 text-sm text-gray-400 focus-within:border-blue-500/50 focus-within:ring-1 focus-within:ring-blue-500/20 sm:w-[360px]',
        className,
      )}
    >
      {icon ? <span className="shrink-0 text-gray-500">{icon}</span> : null}
      <span className="sr-only">搜索</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder ?? '搜索…'}
        className="min-w-0 flex-1 bg-transparent text-sm font-semibold text-slate-200 outline-none placeholder:text-slate-600"
      />
    </label>
  );
}

export type EvidenceItem = {
  label: string;
  value: ReactNode;
  tone?: 'neutral' | 'blue' | 'green' | 'red' | 'amber';
};

export function EvidenceStrip({
  items,
  className,
}: {
  items: ReadonlyArray<EvidenceItem>;
  className?: string;
}) {
  return (
    <div
      className={clsx(
        'mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-crypto-border bg-crypto-card/60 px-4 py-2.5 text-[11px] text-slate-500',
        className,
      )}
    >
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-1.5">
          <span className="text-slate-600">{item.label}</span>
          {item.tone && item.tone !== 'neutral' ? (
            <StatusBadge tone={item.tone === 'green' ? 'green' : item.tone === 'red' ? 'red' : item.tone === 'amber' ? 'amber' : 'blue'}>
              {item.value}
            </StatusBadge>
          ) : (
            <strong className="font-medium tabular-nums text-slate-300">{item.value}</strong>
          )}
        </span>
      ))}
    </div>
  );
}

export type OperatorStateKind = 'loading' | 'empty' | 'stale' | 'error' | 'permission';

export function OperatorStatePanel({
  kind,
  title,
  description,
  action,
  className,
}: {
  kind: OperatorStateKind;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const Icon =
    kind === 'loading'
      ? RefreshCw
      : kind === 'permission'
        ? Lock
        : kind === 'empty'
          ? Inbox
          : AlertCircle;
  const iconClass =
    kind === 'loading'
      ? 'animate-spin text-blue-400'
      : kind === 'error'
        ? 'text-red-400'
        : kind === 'stale'
          ? 'text-amber-400'
          : kind === 'permission'
            ? 'text-amber-300'
            : 'text-slate-500';

  return (
    <div
      className={clsx(
        'rounded-xl border border-crypto-border bg-crypto-card px-6 py-16 text-center',
        className,
      )}
      data-operator-state={kind}
    >
      <Icon className={clsx('mx-auto mb-3 h-5 w-5', iconClass)} />
      <div className="text-sm font-semibold text-slate-200">{title}</div>
      {description ? <p className="mx-auto mt-2 max-w-md text-xs leading-5 text-slate-500">{description}</p> : null}
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}

export function CatalogueCard({
  children,
  active,
  onClick,
  className,
  testId,
}: {
  children: ReactNode;
  active?: boolean;
  onClick?: () => void;
  className?: string;
  testId?: string;
}) {
  return (
    <article
      data-testid={testId}
      onClick={onClick}
      onKeyDown={
        onClick
          ? (event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      className={clsx(
        'group w-full self-start overflow-hidden rounded-xl border bg-crypto-card text-left transition-all duration-200',
        onClick ? 'cursor-pointer' : null,
        active
          ? 'border-blue-500/50 shadow-md shadow-blue-950/40'
          : 'border-crypto-border hover:border-blue-500/40 hover:-translate-y-[1px] hover:shadow-lg hover:shadow-blue-500/5',
        className,
      )}
    >
      {children}
    </article>
  );
}
