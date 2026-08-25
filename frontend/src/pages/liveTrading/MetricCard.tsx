import clsx from 'clsx';
import type { ReactNode } from 'react';

export function MetricCard({
  label,
  value,
  icon,
  color,
}: {
  label: string;
  value: string;
  icon: ReactNode;
  color: 'blue' | 'green' | 'red' | 'yellow' | 'gray' | 'up' | 'down';
}) {
  const colorMap: Record<string, string> = {
    blue: 'text-blue-400',
    green: 'text-green-400',
    red: 'text-red-400',
    yellow: 'text-yellow-400',
    gray: 'text-gray-400',
    up: 'text-up',
    down: 'text-down',
  };
  return (
    <div className="bg-crypto-card border border-crypto-border rounded-xl p-3">
      <div className="flex items-center gap-1.5 mb-1">
        <span className={colorMap[color]}>{icon}</span>
        <span className="text-[10px] text-gray-500">{label}</span>
      </div>
      <div className={clsx('text-lg font-bold', colorMap[color])}>{value}</div>
    </div>
  );
}
