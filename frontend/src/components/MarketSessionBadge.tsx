import { useEffect, useState } from 'react';
import clsx from 'clsx';
import {
  resolveMarketSession,
  sessionFromOverview,
  type MarketSessionPhase,
  type MarketSessionState,
} from '../utils/marketSession';

type MarketSessionBadgeProps = {
  /** Compact for sidebar; default is inline pill. */
  compact?: boolean;
  /** Larger homepage corner treatment. */
  prominent?: boolean;
  className?: string;
  /** Optional API snapshot. */
  overview?: {
    session_phase?: string | null;
    session_label?: string | null;
    session_detail?: string | null;
    session_local_time?: string | null;
    is_open?: boolean;
  } | null;
};

const PHASE_STYLE: Record<
  MarketSessionPhase,
  { dot: string; text: string; border: string; bg: string }
> = {
  open: {
    dot: 'bg-emerald-400',
    text: 'text-emerald-300',
    border: 'border-emerald-500/30',
    bg: 'bg-emerald-500/10',
  },
  auction: {
    dot: 'bg-amber-400',
    text: 'text-amber-300',
    border: 'border-amber-500/30',
    bg: 'bg-amber-500/10',
  },
  pre_open: {
    dot: 'bg-sky-400',
    text: 'text-sky-300',
    border: 'border-sky-500/30',
    bg: 'bg-sky-500/10',
  },
  lunch: {
    dot: 'bg-amber-400',
    text: 'text-amber-300',
    border: 'border-amber-500/30',
    bg: 'bg-amber-500/10',
  },
  closed: {
    dot: 'bg-slate-400',
    text: 'text-slate-400',
    border: 'border-crypto-border',
    bg: 'bg-slate-800/60',
  },
  weekend: {
    dot: 'bg-slate-400',
    text: 'text-slate-400',
    border: 'border-crypto-border',
    bg: 'bg-slate-800/60',
  },
};

export function MarketSessionBadge({
  compact = false,
  prominent = false,
  className,
  overview,
}: MarketSessionBadgeProps) {
  const [session, setSession] = useState<MarketSessionState>(() => resolveMarketSession());

  useEffect(() => {
    const tick = () => {
      const fromApi = sessionFromOverview(overview);
      setSession(fromApi ?? resolveMarketSession());
    };
    tick();
    const id = window.setInterval(tick, 15_000);
    return () => window.clearInterval(id);
  }, [overview]);

  const style = PHASE_STYLE[session.phase] ?? PHASE_STYLE.closed;
  const title = `A股 · ${session.detail} · ${session.localTime}（上海）`;

  if (compact) {
    return (
      <div
        className={clsx('flex flex-col items-center gap-1 px-1 py-1', className)}
        title={title}
        role="status"
        aria-live="polite"
        data-testid="market-session-badge"
        data-session-phase={session.phase}
      >
        <span className={clsx('h-2 w-2 rounded-full shrink-0', style.dot)} />
        <span className={clsx('text-[10px] font-semibold leading-none', style.text)}>
          {session.label}
        </span>
      </div>
    );
  }

  if (prominent) {
    return (
      <div
        className={clsx(
          'inline-flex h-10 items-center gap-2.5 rounded-lg border px-3.5',
          style.border,
          style.bg,
          className,
        )}
        title={title}
        role="status"
        aria-live="polite"
        data-testid="market-session-badge"
        data-session-phase={session.phase}
      >
        <span className={clsx('h-2 w-2 rounded-full shrink-0', style.dot)} />
        <div className="min-w-0 leading-tight">
          <div className={clsx('text-xs font-bold tracking-wide', style.text)}>
            {session.label}
          </div>
          <div className="mt-0.5 font-mono text-[10px] tabular-nums text-slate-400">
            上海 {session.localTime}
          </div>
        </div>
      </div>
    );
  }

  return (
    <span
      className={clsx(
        'inline-flex h-7 items-center gap-2 rounded-md border px-2.5 text-xs font-semibold',
        style.border,
        style.bg,
        style.text,
        className,
      )}
      title={title}
      role="status"
      aria-live="polite"
      data-testid="market-session-badge"
      data-session-phase={session.phase}
    >
      <span className={clsx('h-2 w-2 rounded-full shrink-0', style.dot)} />
      <span>{session.label}</span>
      <span className="tabular-nums text-[10px] opacity-80 font-mono">{session.localTime}</span>
    </span>
  );
}

export default MarketSessionBadge;
