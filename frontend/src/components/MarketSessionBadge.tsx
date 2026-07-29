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
  /** Larger homepage corner treatment with stronger breath. */
  prominent?: boolean;
  className?: string;
  /** Optional API snapshot; clock still ticks locally for breathing freshness. */
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
  { dot: string; text: string; border: string; bg: string; breath: string; glow: string }
> = {
  open: {
    dot: 'bg-emerald-400',
    text: 'text-emerald-300',
    border: 'border-emerald-500/35',
    bg: 'bg-emerald-500/10',
    breath: 'market-session-breath',
    glow: 'shadow-[0_0_14px_rgba(52,211,153,0.55)]',
  },
  auction: {
    dot: 'bg-amber-400',
    text: 'text-amber-300',
    border: 'border-amber-500/35',
    bg: 'bg-amber-500/10',
    breath: 'market-session-breath-fast',
    glow: 'shadow-[0_0_12px_rgba(251,191,36,0.45)]',
  },
  pre_open: {
    dot: 'bg-sky-400',
    text: 'text-sky-300',
    border: 'border-sky-500/35',
    bg: 'bg-sky-500/10',
    breath: 'market-session-breath-slow',
    glow: 'shadow-[0_0_10px_rgba(56,189,248,0.4)]',
  },
  lunch: {
    dot: 'bg-amber-300/90',
    text: 'text-amber-200/90',
    border: 'border-amber-500/25',
    bg: 'bg-amber-500/5',
    breath: 'market-session-breath-slow',
    glow: 'shadow-[0_0_8px_rgba(252,211,77,0.3)]',
  },
  closed: {
    dot: 'bg-slate-500',
    text: 'text-slate-400',
    border: 'border-crypto-border',
    bg: 'bg-slate-800/60',
    breath: 'market-session-breath-dim',
    glow: '',
  },
  weekend: {
    dot: 'bg-slate-500',
    text: 'text-slate-400',
    border: 'border-crypto-border',
    bg: 'bg-slate-800/60',
    breath: 'market-session-breath-dim',
    glow: '',
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
        <span className={clsx('relative flex h-3 w-3 items-center justify-center')}>
          <span className={clsx('absolute inset-0 rounded-full', style.dot, style.breath, 'opacity-40')} />
          <span className={clsx('relative h-2 w-2 rounded-full', style.dot, style.glow, style.breath)} />
        </span>
        <span className={clsx('text-[9px] font-semibold leading-none', style.text)}>{session.label}</span>
      </div>
    );
  }

  if (prominent) {
    return (
      <div
        className={clsx(
          'inline-flex h-11 items-center gap-3 rounded-xl border px-4',
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
        <span className="relative flex h-4 w-4 items-center justify-center">
          <span
            className={clsx(
              'absolute inset-0 rounded-full',
              style.dot,
              style.breath,
              'opacity-35',
            )}
          />
          <span
            className={clsx(
              'relative h-2.5 w-2.5 rounded-full',
              style.dot,
              style.glow,
              style.breath,
            )}
          />
        </span>
        <div className="min-w-0 leading-tight">
          <div className={clsx('text-sm font-bold tracking-wide', style.text)}>{session.label}</div>
          <div className="mt-0.5 font-mono text-[10px] tabular-nums text-slate-500">
            上海 {session.localTime}
          </div>
        </div>
      </div>
    );
  }

  return (
    <span
      className={clsx(
        'inline-flex h-8 items-center gap-2 rounded-full border px-3 text-xs font-semibold',
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
      <span className="relative flex h-2.5 w-2.5 items-center justify-center">
        <span className={clsx('absolute inset-0 rounded-full', style.dot, style.breath, 'opacity-40')} />
        <span className={clsx('relative h-2 w-2 rounded-full', style.dot, style.glow, style.breath)} />
      </span>
      <span>{session.label}</span>
      <span className="tabular-nums text-[10px] opacity-70">{session.localTime}</span>
    </span>
  );
}

export default MarketSessionBadge;
