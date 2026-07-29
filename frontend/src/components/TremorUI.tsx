import React from 'react';
import {
  ArrowUpRight,
  ArrowDownRight,
  AlertTriangle,
  CheckCircle2,
  Info,
  ShieldAlert,
} from 'lucide-react';
import clsx from 'clsx';

/**
 * Shared Tremor Design System Components
 */

export type TremorDeltaType =
  | 'increase'
  | 'moderate-increase'
  | 'decrease'
  | 'moderate-decrease'
  | 'unchanged'
  | 'neutral';

export interface TremorDeltaBadgeProps {
  type: TremorDeltaType;
  value: string | number;
  className?: string;
}

export function TremorDeltaBadge({ type, value, className }: TremorDeltaBadgeProps) {
  const getStyle = () => {
    switch (type) {
      case 'increase':
      case 'moderate-increase':
        return {
          bg: 'bg-up border-up text-up',
          icon: <ArrowUpRight className="h-3.5 w-3.5 mr-0.5" />,
        };
      case 'decrease':
      case 'moderate-decrease':
        return {
          bg: 'bg-down border-down text-down',
          icon: <ArrowDownRight className="h-3.5 w-3.5 mr-0.5" />,
        };
      case 'unchanged':
      case 'neutral':
      default:
        return {
          bg: 'bg-blue-500/10 border-blue-500/20 text-blue-400',
          icon: null,
        };
    }
  };

  const style = getStyle();

  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium tabular-nums',
        style.bg,
        className
      )}
    >
      {style.icon}
      {value}
    </span>
  );
}

export interface TremorTrackerItem {
  color: 'emerald' | 'amber' | 'rose' | 'gray' | 'blue';
  tooltip: string;
}

export interface TremorTrackerProps {
  data: TremorTrackerItem[];
  className?: string;
}

export function TremorTracker({ data, className }: TremorTrackerProps) {
  const getColorClass = (color: TremorTrackerItem['color']) => {
    switch (color) {
      case 'emerald':
        return 'bg-emerald-500 hover:bg-emerald-400';
      case 'amber':
        return 'bg-amber-500 hover:bg-amber-400';
      case 'rose':
        return 'bg-rose-500 hover:bg-rose-400';
      case 'blue':
        return 'bg-blue-500 hover:bg-blue-400';
      case 'gray':
      default:
        return 'bg-gray-700 hover:bg-gray-600';
    }
  };

  return (
    <div
      className={clsx(
        'flex h-7 w-full items-center gap-1 overflow-hidden rounded-md bg-crypto-bg/60 p-1 border border-crypto-border/50',
        className
      )}
    >
      {data.map((item, index) => (
        <div
          key={index}
          className={clsx(
            'h-full flex-1 rounded-sm transition-all cursor-pointer',
            getColorClass(item.color)
          )}
          title={item.tooltip}
        />
      ))}
    </div>
  );
}

export interface TremorBarListItem {
  name: string;
  value: number;
  icon?: React.ReactNode;
  subtitle?: string;
}

export interface TremorBarListProps {
  data: TremorBarListItem[];
  valueFormatter?: (value: number) => string;
  color?: 'emerald' | 'rose' | 'blue' | 'amber';
  className?: string;
}

export function TremorBarList({
  data,
  valueFormatter = (v) => v.toString(),
  color = 'blue',
  className,
}: TremorBarListProps) {
  const maxValue = Math.max(...data.map((d) => d.value), 1);

  const getBgClass = () => {
    switch (color) {
      case 'emerald':
        return 'bg-emerald-500/15 border-l-2 border-emerald-500';
      case 'rose':
        return 'bg-rose-500/15 border-l-2 border-rose-500';
      case 'amber':
        return 'bg-amber-500/15 border-l-2 border-amber-500';
      case 'blue':
      default:
        return 'bg-blue-500/15 border-l-2 border-blue-500';
    }
  };

  return (
    <div className={clsx('space-y-1.5 text-xs', className)}>
      {data.map((item, idx) => {
        const widthPercent = Math.min(100, Math.max(4, (item.value / maxValue) * 100));
        return (
          <div
            key={idx}
            className="group relative flex items-center justify-between py-1.5 px-2 rounded hover:bg-crypto-bg/40 transition-colors"
          >
            <div
              className={clsx(
                'absolute left-0 top-0 bottom-0 rounded transition-all duration-300',
                getBgClass()
              )}
              style={{ width: `${widthPercent}%` }}
            />
            <div className="relative z-10 flex items-center gap-2 truncate pr-2 font-medium text-gray-200">
              {item.icon}
              <span className="truncate">{item.name}</span>
              {item.subtitle && <span className="text-[10px] text-gray-500">{item.subtitle}</span>}
            </div>
            <div className="relative z-10 font-bold tabular-nums text-gray-300">
              {valueFormatter(item.value)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export interface TremorCalloutProps {
  title: string;
  children: React.ReactNode;
  icon?: React.ReactNode;
  color?: 'emerald' | 'amber' | 'rose' | 'blue';
  className?: string;
}

export function TremorCallout({
  title,
  children,
  icon,
  color = 'blue',
  className,
}: TremorCalloutProps) {
  const getStyle = () => {
    switch (color) {
      case 'emerald':
        return {
          border: 'border-l-4 border-l-emerald-500 border-emerald-500/20',
          bg: 'bg-emerald-500/5',
          text: 'text-emerald-300',
          defaultIcon: <CheckCircle2 className="h-4 w-4 text-emerald-400" />,
        };
      case 'amber':
        return {
          border: 'border-l-4 border-l-amber-500 border-amber-500/20',
          bg: 'bg-amber-500/5',
          text: 'text-amber-300',
          defaultIcon: <AlertTriangle className="h-4 w-4 text-amber-400" />,
        };
      case 'rose':
        return {
          border: 'border-l-4 border-l-rose-500 border-rose-500/20',
          bg: 'bg-rose-500/5',
          text: 'text-rose-300',
          defaultIcon: <ShieldAlert className="h-4 w-4 text-rose-400" />,
        };
      case 'blue':
      default:
        return {
          border: 'border-l-4 border-l-blue-500 border-blue-500/20',
          bg: 'bg-blue-500/5',
          text: 'text-blue-300',
          defaultIcon: <Info className="h-4 w-4 text-blue-400" />,
        };
    }
  };

  const style = getStyle();

  return (
    <div className={clsx('rounded-r-lg border p-3.5 text-xs', style.border, style.bg, className)}>
      <div className="flex items-center gap-2 font-bold mb-1">
        {icon || style.defaultIcon}
        <span className={style.text}>{title}</span>
      </div>
      <div className="text-gray-400 leading-relaxed pl-6">{children}</div>
    </div>
  );
}

export interface TremorCardProps {
  children: React.ReactNode;
  className?: string;
  decorationColor?: 'emerald' | 'amber' | 'rose' | 'blue';
}

export function TremorCard({ children, className, decorationColor }: TremorCardProps) {
  const getDecorationStyle = () => {
    if (!decorationColor) return '';
    switch (decorationColor) {
      case 'emerald':
        return 'border-t-2 border-t-emerald-500';
      case 'amber':
        return 'border-t-2 border-t-amber-500';
      case 'rose':
        return 'border-t-2 border-t-rose-500';
      case 'blue':
      default:
        return 'border-t-2 border-t-blue-500';
    }
  };

  return (
    <div
      className={clsx(
        'rounded-xl border border-crypto-border bg-crypto-card p-4 transition-all hover:border-crypto-border/80',
        getDecorationStyle(),
        className
      )}
    >
      {children}
    </div>
  );
}
