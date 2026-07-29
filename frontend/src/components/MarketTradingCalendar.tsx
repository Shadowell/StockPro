import { useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import { ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react';
import { getTradingCalendar } from '../api/client';
import type { TradingCalendarDay, TradingCalendarResponse, TradingCalendarTag } from '../types';

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];

const toneClass = (tone?: string | null) => {
  switch (tone) {
    case 'open':
      return 'border-emerald-500/30 bg-emerald-500/15 text-emerald-200';
    case 'closed':
      return 'border-slate-500/30 bg-slate-500/15 text-slate-300';
    case 'holiday':
      return 'border-rose-500/30 bg-rose-500/15 text-rose-200';
    case 'danger':
      return 'border-red-500/35 bg-red-500/15 text-red-200';
    case 'warn':
      return 'border-amber-500/35 bg-amber-500/15 text-amber-200';
    case 'accent':
      return 'border-sky-500/35 bg-sky-500/15 text-sky-200';
    case 'info':
      return 'border-blue-500/30 bg-blue-500/15 text-blue-200';
    case 'macro':
      return 'border-cyan-500/30 bg-cyan-500/15 text-cyan-200';
    default:
      return 'border-white/10 bg-white/[0.04] text-slate-400';
  }
};

function monthBounds(anchor: Date) {
  const start = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const end = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  return { start: iso(start), end: iso(end), label: `${start.getFullYear()}年${start.getMonth() + 1}月` };
}

function buildCells(anchor: Date, byDate: Map<string, TradingCalendarDay>) {
  const year = anchor.getFullYear();
  const month = anchor.getMonth();
  const first = new Date(year, month, 1);
  const startPad = (first.getDay() + 6) % 7; // Monday-first
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: Array<{ dateStr: string; inMonth: boolean; day: TradingCalendarDay | null }> = [];
  for (let i = 0; i < startPad; i += 1) {
    cells.push({ dateStr: '', inMonth: false, day: null });
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    cells.push({ dateStr, inMonth: true, day: byDate.get(dateStr) || null });
  }
  while (cells.length % 7 !== 0) {
    cells.push({ dateStr: '', inMonth: false, day: null });
  }
  return cells;
}

function Capsule({ tag }: { tag: TradingCalendarTag }) {
  return (
    <span
      title={tag.detail || tag.label}
      className={clsx(
        'inline-flex max-w-full truncate rounded-full border px-1.5 py-0.5 text-[10px] font-medium leading-none',
        toneClass(tag.tone),
      )}
    >
      {tag.label}
    </span>
  );
}

export function MarketTradingCalendar() {
  const [anchor, setAnchor] = useState(() => new Date());
  const [payload, setPayload] = useState<TradingCalendarResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const bounds = useMemo(() => monthBounds(anchor), [anchor]);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await getTradingCalendar({ start: bounds.start, end: bounds.end });
      setPayload(data);
      if (!selected || selected < bounds.start || selected > bounds.end) {
        const today = new Date();
        const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
        setSelected(todayStr >= bounds.start && todayStr <= bounds.end ? todayStr : bounds.start);
      }
    } catch (reason) {
      setPayload(null);
      setError(reason instanceof Error ? reason.message : '交易日历加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bounds.start, bounds.end]);

  const byDate = useMemo(() => {
    const map = new Map<string, TradingCalendarDay>();
    for (const day of payload?.days || []) map.set(day.date, day);
    return map;
  }, [payload]);

  const cells = useMemo(() => buildCells(anchor, byDate), [anchor, byDate]);
  const selectedDay = selected ? byDate.get(selected) : null;
  const todayStr = useMemo(() => {
    const today = new Date();
    return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  }, []);

  return (
    <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card" data-testid="market-trading-calendar">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-5 py-4">
        <div>
          <h2 className="font-semibold text-white">交易日历</h2>
          <p className="mt-1 text-xs text-slate-500">
            每日标注开盘/休市、股指与商品交割、期权窗口与重大事项
            {payload?.source_label ? ` · ${payload.source_label}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-label="上一月"
            onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1))}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-crypto-border text-slate-400 hover:text-white"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <div className="min-w-[7.5rem] text-center text-sm font-semibold text-slate-200">{bounds.label}</div>
          <button
            type="button"
            aria-label="下一月"
            onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1))}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-crypto-border text-slate-400 hover:text-white"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border px-3 text-xs text-slate-400 hover:text-white"
          >
            <RefreshCw className={clsx('h-3.5 w-3.5', loading && 'animate-spin')} />
            刷新
          </button>
        </div>
      </div>

      {error ? <div className="border-b border-red-500/20 bg-red-500/10 px-5 py-3 text-sm text-red-200">{error}</div> : null}

      <div className="grid gap-4 p-4 xl:grid-cols-[1fr_280px]">
        <div>
          <div className="mb-2 grid grid-cols-7 gap-1 px-1">
            {WEEKDAYS.map((label) => (
              <div key={label} className="text-center text-[11px] font-medium text-slate-500">
                {label}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-1">
            {cells.map((cell, index) => {
              if (!cell.inMonth) {
                return <div key={`pad-${index}`} className="min-h-[108px] rounded-lg bg-transparent" />;
              }
              const active = selected === cell.dateStr;
              const isToday = cell.dateStr === todayStr;
              const closed = cell.day?.session === 'closed' || cell.day?.session === 'weekend';
              const tags = (cell.day?.tags || []).slice(0, 4);
              return (
                <button
                  key={cell.dateStr}
                  type="button"
                  onClick={() => setSelected(cell.dateStr)}
                  className={clsx(
                    'flex min-h-[108px] flex-col gap-1 rounded-lg border p-2 text-left transition-colors',
                    active ? 'border-blue-500/50 bg-blue-500/10' : 'border-white/[0.05] bg-crypto-bg/40 hover:border-white/10',
                    closed && !active && 'opacity-80',
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span
                      className={clsx(
                        'text-sm font-semibold tabular-nums',
                        isToday ? 'text-blue-300' : closed ? 'text-slate-500' : 'text-slate-200',
                      )}
                    >
                      {Number(cell.dateStr.slice(-2))}
                    </span>
                    {isToday ? <span className="text-[10px] text-blue-400">今</span> : null}
                  </div>
                  <div className="flex flex-col gap-1">
                    {tags.map((tag) => (
                      <Capsule key={`${cell.dateStr}-${tag.kind}-${tag.label}`} tag={tag} />
                    ))}
                    {(cell.day?.tags.length || 0) > 4 ? (
                      <span className="text-[10px] text-slate-600">+{(cell.day?.tags.length || 0) - 4}</span>
                    ) : null}
                  </div>
                </button>
              );
            })}
          </div>
          <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-slate-500">
            {[
              ['开盘', 'open'],
              ['休市', 'closed'],
              ['股指交割', 'danger'],
              ['商品交割', 'warn'],
              ['期权交割', 'accent'],
              ['重大事项', 'macro'],
            ].map(([label, tone]) => (
              <span key={label} className={clsx('rounded-full border px-2 py-0.5', toneClass(tone))}>
                {label}
              </span>
            ))}
          </div>
        </div>

        <aside className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-4">
          <h3 className="text-sm font-semibold text-white">{selected || '选择日期'}</h3>
          <p className="mt-1 text-[11px] text-slate-500">
            {selectedDay
              ? selectedDay.is_open
                ? '交易日'
                : selectedDay.session === 'weekend'
                  ? '周末休市'
                  : '非交易日'
              : loading
                ? '加载中…'
                : '点击日历格子查看当日明细'}
          </p>
          <div className="mt-4 space-y-2">
            {(selectedDay?.tags || []).length === 0 ? (
              <div className="rounded-lg border border-dashed border-crypto-border px-3 py-8 text-center text-xs text-slate-600">
                当日暂无标注
              </div>
            ) : (
              (selectedDay?.tags || []).map((tag) => (
                <div
                  key={`${selected}-${tag.kind}-${tag.label}`}
                  className="rounded-lg border border-white/[0.06] bg-crypto-card/80 px-3 py-2"
                >
                  <div className="mb-1">
                    <Capsule tag={tag} />
                  </div>
                  <p className="text-[11px] leading-relaxed text-slate-400">{tag.detail || tag.label}</p>
                </div>
              ))
            )}
          </div>
        </aside>
      </div>
    </section>
  );
}

export default MarketTradingCalendar;
