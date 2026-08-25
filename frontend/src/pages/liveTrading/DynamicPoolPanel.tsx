import { useMemo, useState } from 'react';
import NumberFlow from '@number-flow/react';
import { AnimatePresence, motion, useReducedMotion, type MotionProps } from 'motion/react';
import clsx from 'clsx';
import {
  Activity,
  ChevronDown,
  Clock,
  Layers,
  Radar,
  Snowflake,
  Waves,
} from 'lucide-react';
import SymbolIcon from '../../components/SymbolIcon';
import type {
  DynamicPoolBadge,
  DynamicPoolDisplayEvent,
  DynamicPoolDisplayMetric,
  DynamicPoolDisplayPosition,
  DynamicPoolDisplayRow,
  DynamicPoolTone,
  DynamicPoolView,
} from './types';

const TONE_TEXT_CLASS: Record<DynamicPoolTone, string> = {
  neutral: 'text-gray-400',
  info: 'text-blue-300',
  success: 'text-emerald-300',
  warning: 'text-orange-300',
  danger: 'text-red-300',
  up: 'text-up',
  down: 'text-down',
};

const TONE_BADGE_CLASS: Record<DynamicPoolTone, string> = {
  neutral: 'border-gray-500/35 bg-gray-500/10 text-gray-400',
  info: 'border-blue-500/35 bg-blue-500/10 text-blue-300',
  success: 'border-emerald-500/35 bg-emerald-500/10 text-emerald-300',
  warning: 'border-orange-500/35 bg-orange-500/10 text-orange-300',
  danger: 'border-red-500/35 bg-red-500/10 text-red-300',
  up: 'border-up/35 bg-up/10 text-up',
  down: 'border-down/35 bg-down/10 text-down',
};

function normalizedTone(tone?: DynamicPoolTone): DynamicPoolTone {
  return tone ?? 'neutral';
}

function shortSymbol(symbol: string): string {
  return symbol.split('/')[0] || symbol;
}

function formatClock(ms?: number | null): string {
  if (!ms) return '—';
  const date = new Date(Number(ms));
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatEventTimestamp(ms?: number | null): string {
  if (!ms) return '—';
  const date = new Date(Number(ms));
  if (Number.isNaN(date.getTime())) return '—';
  const pad = (value: number, length = 2) => String(value).padStart(length, '0');
  return [
    date.getFullYear(),
    '-',
    pad(date.getMonth() + 1),
    '-',
    pad(date.getDate()),
    ' ',
    pad(date.getHours()),
    ':',
    pad(date.getMinutes()),
    ':',
    pad(date.getSeconds()),
    '.',
    String(Math.floor(date.getMilliseconds() / 100)),
  ].join('');
}

function MetricDisplay({ metric }: { metric: DynamicPoolDisplayMetric }) {
  const value = metric.value;
  if (typeof value !== 'number' || !Number.isFinite(value)) return <>{metric.display}</>;
  const numberMatch = metric.display.match(/[+-]?\d+(?:\.\d+)?/);
  if (!numberMatch || numberMatch.index == null) return <>{metric.display}</>;
  const token = numberMatch[0];
  const decimalPlaces = token.includes('.') ? token.split('.')[1].length : 0;
  const prefix = metric.display.slice(0, numberMatch.index);
  const suffix = metric.display.slice(numberMatch.index + token.length);
  return (
    <>
      {prefix}
      <NumberFlow
        value={value}
        format={{
          minimumFractionDigits: decimalPlaces,
          maximumFractionDigits: decimalPlaces,
          signDisplay: token.startsWith('+') ? 'always' : 'auto',
        }}
      />
      {suffix}
    </>
  );
}

function MetricValue({ metric, strong = false }: { metric: DynamicPoolDisplayMetric; strong?: boolean }) {
  return (
    <span
      className={clsx(
        'tabular-nums',
        strong ? 'text-xs font-bold' : 'text-[10px]',
        TONE_TEXT_CLASS[normalizedTone(metric.tone)],
      )}
    >
      {strong && <span className="mr-1 font-medium text-gray-500">{metric.label}</span>}
      <MetricDisplay metric={metric} />
    </span>
  );
}

function BadgeList({ badges }: { badges: DynamicPoolBadge[] }) {
  if (badges.length === 0) return null;
  return (
    <span className="flex flex-wrap items-center gap-1">
      {badges.map((badge, index) => (
        <span
          key={`${badge.label}-${index}`}
          className={clsx(
            'rounded border px-1 py-0.5 text-[10px] font-semibold',
            TONE_BADGE_CLASS[normalizedTone(badge.tone)],
          )}
        >
          {badge.label}
        </span>
      ))}
    </span>
  );
}

function MetricList({ metrics }: { metrics: DynamicPoolDisplayMetric[] }) {
  if (metrics.length === 0) return null;
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
      {metrics.map((metric, index) => (
        <span key={`${metric.label}-${index}`} className="text-[10px] text-gray-500 tabular-nums">
          {metric.label}{' '}
          <span className={TONE_TEXT_CLASS[normalizedTone(metric.tone)]}>
            <MetricDisplay metric={metric} />
          </span>
        </span>
      ))}
    </span>
  );
}

interface DisplayRowCardProps {
  row: DynamicPoolDisplayRow;
  cardMotion: MotionProps;
  highlightOpenable?: boolean;
}

function DisplayRowCard({ row, cardMotion, highlightOpenable = false }: DisplayRowCardProps) {
  return (
    <motion.li
      {...cardMotion}
      className={clsx(
        'rounded-md border px-2.5 py-1.5',
        highlightOpenable && row.openable
          ? 'border-emerald-500/30 bg-emerald-500/[0.06]'
          : 'border-crypto-border/70 bg-crypto-card',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1.5 text-xs text-gray-100">
          <SymbolIcon symbol={row.symbol} size="xs" />
          <span className="truncate font-mono">{shortSymbol(row.symbol)}</span>
          <BadgeList badges={row.badges} />
        </span>
        <span className="shrink-0">
          <MetricValue metric={row.primaryMetric} strong />
        </span>
      </div>
      {(row.metrics.length > 0 || row.reason) && (
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5">
          <MetricList metrics={row.metrics} />
          {row.reason && (
            <span className={clsx('text-[10px]', row.openable ? 'text-gray-500' : 'text-orange-400/80')}>
              {row.reason}
            </span>
          )}
        </div>
      )}
    </motion.li>
  );
}

function PositionCard({ position, cardMotion }: { position: DynamicPoolDisplayPosition; cardMotion: MotionProps }) {
  return (
    <motion.li
      {...cardMotion}
      className="rounded-md border border-purple-500/25 bg-purple-500/[0.05] px-2.5 py-1.5"
    >
      <div className="flex items-center gap-1.5 text-xs text-gray-100">
        <SymbolIcon symbol={position.symbol} size="xs" />
        <span className="truncate font-mono">{shortSymbol(position.symbol)}</span>
        <BadgeList badges={position.badges} />
      </div>
      {position.metrics.length > 0 && (
        <div className="mt-1">
          <MetricList metrics={position.metrics} />
        </div>
      )}
    </motion.li>
  );
}

function eventToneClass(event: DynamicPoolDisplayEvent): string {
  return TONE_BADGE_CLASS[normalizedTone(event.tone)];
}

interface DynamicPoolPanelProps {
  pool: DynamicPoolView | null;
}

export default function DynamicPoolPanel({ pool }: DynamicPoolPanelProps) {
  const hasPool = pool != null;
  const warming = pool?.status === 'warming';
  const [open, setOpen] = useState(hasPool);
  const [eventsOpen, setEventsOpen] = useState(true);
  const reduceMotion = useReducedMotion();

  const candidates = pool?.candidates ?? [];
  const members = pool?.members ?? [];
  const positions = pool?.positions ?? [];
  const counts = pool?.counts ?? { candidates: 0, eligible: 0, members: 0, positions: 0 };
  const timestamps = pool?.timestamps ?? {};
  const events = useMemo(
    () => [...(pool?.events ?? [])].sort((a, b) => (b.ts ?? 0) - (a.ts ?? 0)),
    [pool?.events],
  );
  const latestEvent = events[0];

  const cardMotion: MotionProps = reduceMotion
    ? {}
    : {
        layout: true,
        initial: { opacity: 0, y: 8, scale: 0.97 },
        animate: { opacity: 1, y: 0, scale: 1 },
        exit: { opacity: 0, scale: 0.95, transition: { duration: 0.18 } },
        transition: { type: 'spring', stiffness: 320, damping: 28 },
      };

  return (
    <section className="min-h-0 overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors hover:bg-white/[0.03]"
      >
        <span className="flex min-w-0 items-center gap-2">
          <Radar className="h-4 w-4 shrink-0 text-emerald-400" />
          <h3 className="truncate text-base font-semibold text-white">动态标的池</h3>
          {hasPool && (
            <span className="hidden truncate text-[11px] text-gray-500 sm:inline">{pool.summary}</span>
          )}
        </span>
        <span className="flex shrink-0 items-center gap-3">
          <span className="rounded-full border border-crypto-border bg-crypto-bg px-2.5 py-1 text-[11px] font-semibold text-gray-400">
            {hasPool
              ? warming
                ? `预热中 · 有效 ${counts.eligible}`
                : `候选 ${counts.candidates} · 池内 ${counts.members}`
              : '未启用'}
          </span>
          <ChevronDown
            className={clsx('h-4 w-4 text-gray-500 transition-transform', open && 'rotate-180 text-gray-300')}
          />
        </span>
      </button>

      {open && !hasPool && (
        <div className="border-t border-crypto-border px-4 py-8 text-center text-xs text-gray-500">
          该策略未启用动态标的池（仅动态池类策略会输出候选与池状态）。
        </div>
      )}

      {open && hasPool && (
        <div className="border-t border-crypto-border px-4 py-4">
          <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-gray-500">
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" />
              上次更新 {formatClock(timestamps.lastEvaluatedAtMs)}
            </span>
            <span>下次更新 {formatClock(timestamps.nextEvaluationAtMs)}</span>
            <span>快照更新 {formatClock(timestamps.updatedAtMs)}</span>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-gray-300">
                  <Waves className="h-3.5 w-3.5 text-blue-400" />
                  候选标的
                </span>
                <span className="text-[10px] text-gray-500">{candidates.length} 个</span>
              </div>
              {candidates.length === 0 ? (
                <div className="rounded-md border border-dashed border-crypto-border py-6 text-center text-[11px] text-gray-500">
                  {warming ? '动态池数据预热中' : '暂无接近门槛的候选'}
                </div>
              ) : (
                <ul className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
                  <AnimatePresence initial={false} mode="popLayout">
                    {candidates.map((candidate) => (
                      <DisplayRowCard key={candidate.id} row={candidate} cardMotion={cardMotion} />
                    ))}
                  </AnimatePresence>
                </ul>
              )}
            </div>

            <div className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-gray-300">
                  <Activity className="h-3.5 w-3.5 text-emerald-400" />
                  池内成员
                </span>
                <span className="text-[10px] text-gray-500">{members.length} 个</span>
              </div>
              {members.length === 0 ? (
                <div className="rounded-md border border-dashed border-crypto-border py-6 text-center text-[11px] text-gray-500">
                  {warming ? '动态池数据预热完成后开始评估' : '当前没有标的通过准入门控'}
                </div>
              ) : (
                <ul className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
                  <AnimatePresence initial={false} mode="popLayout">
                    {members.map((member) => (
                      <DisplayRowCard
                        key={member.id}
                        row={member}
                        cardMotion={cardMotion}
                        highlightOpenable
                      />
                    ))}
                  </AnimatePresence>
                </ul>
              )}
            </div>

            <div className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-gray-300">
                  <Layers className="h-3.5 w-3.5 text-purple-400" />
                  池内持仓
                </span>
                <span className="text-[10px] text-gray-500">{positions.length} 个</span>
              </div>
              {positions.length === 0 ? (
                <div className="rounded-md border border-dashed border-crypto-border py-6 text-center text-[11px] text-gray-500">
                  暂无持仓
                </div>
              ) : (
                <ul className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
                  <AnimatePresence initial={false} mode="popLayout">
                    {positions.map((position) => (
                      <PositionCard key={position.id} position={position} cardMotion={cardMotion} />
                    ))}
                  </AnimatePresence>
                </ul>
              )}
            </div>
          </div>

          <div className="mt-4 overflow-hidden rounded-lg border border-crypto-border bg-crypto-bg/40">
            <button
              type="button"
              aria-expanded={eventsOpen}
              onClick={() => setEventsOpen((value) => !value)}
              className="flex w-full items-center justify-between px-3 py-2.5 text-left hover:bg-white/[0.02]"
            >
              <span className="inline-flex items-center gap-2 text-xs font-semibold text-gray-300">
                <Snowflake className="h-3.5 w-3.5 text-cyan-400" />
                池事件流
                <span className="rounded-full border border-crypto-border px-1.5 py-0.5 text-[10px] text-gray-500">
                  {events.length} 条
                </span>
              </span>
              <span className="flex items-center gap-2">
                {latestEvent && <span className="hidden text-[10px] text-gray-500 sm:inline">最新：{latestEvent.label}</span>}
                <ChevronDown
                  className={clsx(
                    'h-3.5 w-3.5 text-gray-500 transition-transform',
                    eventsOpen && 'rotate-180 text-gray-300',
                  )}
                />
              </span>
            </button>
            {eventsOpen &&
              (events.length === 0 ? (
                <div className="border-t border-crypto-border py-6 text-center text-[11px] text-gray-500">
                  暂无入池 / 踢出 / 加仓事件
                </div>
              ) : (
                <ul className="max-h-[288px] space-y-1 overflow-auto border-t border-crypto-border p-2">
                  <AnimatePresence initial={false}>
                    {events.map((event) => (
                      <motion.li
                        key={event.eventId}
                        initial={reduceMotion ? false : { opacity: 0, x: -6 }}
                        animate={{ opacity: 1, x: 0 }}
                        className="flex min-w-max items-center gap-2 whitespace-nowrap rounded-md px-2 py-1.5 text-[11px] hover:bg-white/[0.02]"
                      >
                        <span className="shrink-0 font-mono text-[10px] tabular-nums text-gray-600">
                          {formatEventTimestamp(event.ts)}
                        </span>
                        <span
                          className={clsx(
                            'shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-bold',
                            eventToneClass(event),
                          )}
                        >
                          {event.label}
                        </span>
                        <span className="text-gray-300">{event.message}</span>
                      </motion.li>
                    ))}
                  </AnimatePresence>
                </ul>
              ))}
          </div>
        </div>
      )}
    </section>
  );
}
