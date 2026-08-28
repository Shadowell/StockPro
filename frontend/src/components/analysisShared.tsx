import type { ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

export function formatSignedPercent(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  const num = Number(value);
  return `${num >= 0 ? '+' : ''}${num.toFixed(digits)}%`;
}

export function formatAmountYi(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value)) || Number(value) <= 0) return '—';
  const abs = Math.abs(Number(value));
  if (abs >= 1e12) return `${(value / 1e12).toFixed(2)}万亿`;
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(value / 1e4).toFixed(1)}万`;
  return value.toFixed(0);
}

export function DataStateBadge({ status }: { status?: string | null }) {
  const normalized = String(status || 'empty');
  const ok = normalized === 'ok';
  return (
    <span
      className={
        ok
          ? 'rounded border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-300'
          : 'rounded border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-300'
      }
    >
      {normalized}
    </span>
  );
}

interface AnalysisSectionProps {
  icon: ReactNode;
  title: string;
  subtitle?: string;
  status?: string | null;
  dateLabel?: string;
  extra?: ReactNode;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  emptyReason?: string | null;
  children: ReactNode;
  hasContent?: boolean;
  footer?: ReactNode;
}

/** 首页分析 tab 通用外壳：Loading / Error / 诚实空态 / 数据状态徽章 / 底部来源说明。 */
export function AnalysisSection({
  icon,
  title,
  subtitle,
  status,
  dateLabel,
  extra,
  loading = false,
  error = null,
  onRetry,
  emptyReason,
  children,
  hasContent = true,
  footer,
}: AnalysisSectionProps) {
  return (
    <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card/95">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border/60 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          {icon}
          <h2 className="truncate text-sm font-semibold text-gray-100">{title}</h2>
          <DataStateBadge status={status} />
          {subtitle ? <span className="truncate text-[11px] text-gray-500">{subtitle}</span> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
          {dateLabel ? <span>{dateLabel}</span> : null}
          {extra}
        </div>
      </header>
      {loading ? (
        <div className="flex h-48 items-center justify-center gap-2 text-sm text-gray-500">
          <RefreshCw className="h-4 w-4 animate-spin" /> 读取中…
        </div>
      ) : error ? (
        <div className="flex h-48 flex-col items-center justify-center gap-2 px-6 text-center text-sm text-amber-300">
          <span>{error}</span>
          {onRetry ? (
            <button
              type="button"
              onClick={onRetry}
              className="rounded-md border border-crypto-border px-3 py-1 text-xs text-gray-400 hover:bg-white/[0.05] hover:text-gray-200"
            >
              重试
            </button>
          ) : null}
        </div>
      ) : !hasContent ? (
        <div className="flex h-48 flex-col items-center justify-center gap-1 px-6 text-center text-sm text-gray-500">
          <AlertTriangle className="h-4 w-4 text-amber-300/80" />
          <span>{emptyReason || '暂无已持久化数据'}</span>
        </div>
      ) : (
        children
      )}
      {footer ? (
        <footer className="border-t border-crypto-border/50 px-4 py-2 text-[10px] text-gray-600">{footer}</footer>
      ) : null}
    </section>
  );
}
