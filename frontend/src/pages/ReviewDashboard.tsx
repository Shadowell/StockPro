import { Fragment, useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Clock3,
  ClipboardList,
  Flame,
  Layers3,
  ListChecks,
  Loader2,
  RefreshCw,
  Target,
  TimerReset,
} from 'lucide-react';
import clsx from 'clsx';
import { SELECTED_SEGMENT_CLASS } from '../utils/selectionStyles';
import {
  marketApi,
  reviewApi,
  type MarketPhase,
  type ReviewBucket,
  type ReviewGroupRow,
  type ReviewHeatmapBucket,
  type ReviewHeatmapRow,
  type ReviewLeaderboardItem,
  type ReviewSummary,
  type ReviewTag,
  type ReviewWindow,
  type SymbolAbnormality,
} from '../api/client';
import { useSettingsStore } from '../stores/useSettingsStore';

const REVIEW_AUTO_REFRESH_MS = 60 * 60 * 1000;
const REVIEW_WINDOWS: Array<{ key: ReviewWindow; label: string }> = [
  { key: '24h', label: '24H' },
  { key: '7d', label: '7D' },
  { key: '30d', label: '30D' },
];
const REVIEW_BUCKET: ReviewBucket = '1h';

function finiteNumber(value: unknown, fallback = 0): number {
  const n = Number(value ?? fallback);
  return Number.isFinite(n) ? n : fallback;
}

function formatSignedPercent(value: unknown, digits = 2): string {
  const n = finiteNumber(value);
  return `${n > 0 ? '+' : ''}${n.toFixed(digits)}%`;
}

function formatOptionalSignedPercent(value: unknown, digits = 2): string {
  if (value == null || !Number.isFinite(Number(value))) return '不可判定';
  return formatSignedPercent(value, digits);
}

function formatOptionalPercent(value: unknown, digits = 1): string {
  if (value == null || !Number.isFinite(Number(value))) return '不可判定';
  return formatPercent(value, digits);
}

function formatPercent(value: unknown, digits = 1): string {
  return `${finiteNumber(value).toFixed(digits)}%`;
}

function formatRatio(value: unknown): string {
  const n = finiteNumber(value, NaN);
  return Number.isFinite(n) && n > 0 ? n.toFixed(2) : '--';
}

function metricTone(value: unknown): 'up' | 'down' | 'blue' {
  const n = finiteNumber(value);
  if (n > 0) return 'up';
  if (n < 0) return 'down';
  return 'blue';
}

function scoreTone(score: number | null): string {
  if (score == null) return 'bg-amber-400';
  if (score >= 75) return 'bg-emerald-400';
  if (score >= 55) return 'bg-yellow-400';
  return 'bg-rose-400';
}

function hexToRgba(hex: string, alpha: number): string {
  const normalized = hex.replace('#', '');
  if (normalized.length !== 6) return hex;
  const r = parseInt(normalized.slice(0, 2), 16);
  const g = parseInt(normalized.slice(2, 4), 16);
  const b = parseInt(normalized.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function heatToneStyle(bucket: ReviewHeatmapBucket, upColor: string, downColor: string): CSSProperties {
  const strength = Math.max(0.24, Math.min(1, Math.abs(finiteNumber(bucket.returnPct)) / 2.5));
  if (bucket.tone === 'positive') return { backgroundColor: hexToRgba(upColor, strength), borderColor: hexToRgba(upColor, 0.54) };
  if (bucket.tone === 'negative') return { backgroundColor: hexToRgba(downColor, strength), borderColor: hexToRgba(downColor, 0.54) };
  return { backgroundColor: '#475569' };
}

function updatedAtText(value?: string | null): string {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function KpiCard({
  label,
  value,
  sub,
  tone = 'blue',
}: {
  label: string;
  value: string;
  sub: string;
  tone?: 'up' | 'down' | 'yellow' | 'blue' | 'cyan';
}) {
  const toneStyles = {
    up: {
      text: 'text-up',
      border: 'border-crypto-border',
      bg: 'bg-up',
    },
    down: {
      text: 'text-down',
      border: 'border-crypto-border',
      bg: 'bg-down',
    },
    yellow: {
      text: 'text-yellow-300',
      border: 'border-yellow-500/25',
      bg: 'bg-yellow-500/[0.06]',
    },
    blue: {
      text: 'text-blue-300',
      border: 'border-blue-500/25',
      bg: 'bg-blue-500/[0.06]',
    },
    cyan: {
      text: 'text-cyan-300',
      border: 'border-cyan-500/25',
      bg: 'bg-cyan-500/[0.06]',
    },
  }[tone];

  return (
    <section data-metric-card className={clsx('rounded-xl border p-4 shadow-inner shadow-black/10', toneStyles.border, toneStyles.bg)}>
      <div className="mb-3 text-xs font-semibold text-gray-400">{label}</div>
      <div className={clsx('text-[clamp(1.25rem,1.55vw,1.75rem)] font-bold leading-tight tabular-nums', toneStyles.text)}>{value}</div>
      <div className="mt-2 text-[11px] leading-snug text-gray-500">{sub}</div>
    </section>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-crypto-border bg-crypto-bg/40 p-6 text-center text-sm text-gray-500">
      {text}
    </div>
  );
}

function SectionTitle({
  icon,
  title,
  meta,
}: {
  icon: React.ReactNode;
  title: string;
  meta?: string;
}) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-blue-500/20 bg-blue-500/10 text-blue-300">
          {icon}
        </span>
        <h2 className="truncate text-sm font-semibold text-white">{title}</h2>
      </div>
      {meta && (
        <span className="shrink-0 rounded-md border border-crypto-border bg-crypto-bg px-2 py-1 text-[10px] font-medium text-gray-500">
          {meta}
        </span>
      )}
    </div>
  );
}

function GroupMatrix({ groups }: { groups: ReviewGroupRow[] }) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  const toggleGroup = (groupKey: string) => {
    setExpandedGroups((current) => {
      const next = new Set(current);
      if (next.has(groupKey)) {
        next.delete(groupKey);
      } else {
        next.add(groupKey);
      }
      return next;
    });
  };

  return (
    <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
      <SectionTitle icon={<Layers3 className="h-4 w-4" />} title="策略分层评分矩阵" meta={`${groups.length} 组`} />
      {groups.length === 0 ? (
        <EmptyState text="暂无可复盘的运行中模拟策略样本。" />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-crypto-border bg-crypto-bg/40">
          <table className="min-w-full text-left text-xs">
            <thead className="bg-crypto-bg text-[10px] uppercase text-gray-500">
              <tr className="border-b border-crypto-border">
                <th className="whitespace-nowrap px-3 py-2 font-semibold">策略组</th>
                <th className="whitespace-nowrap px-3 py-2 font-semibold">数</th>
                <th className="whitespace-nowrap px-3 py-2 font-semibold">权益变化</th>
                <th className="whitespace-nowrap px-3 py-2 font-semibold">回撤</th>
                <th className="whitespace-nowrap px-3 py-2 font-semibold">胜率</th>
                <th className="whitespace-nowrap px-3 py-2 font-semibold">盈亏比</th>
                <th className="whitespace-nowrap px-3 py-2 font-semibold">评分</th>
                <th className="whitespace-nowrap px-3 py-2 font-semibold">判断</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => {
                const expanded = expandedGroups.has(group.groupKey);
                const strategies = group.strategies ?? [];
                return (
                  <Fragment key={group.groupKey}>
                    <tr
                      role="button"
                      tabIndex={0}
                      aria-expanded={expanded}
                      aria-label={`${expanded ? '收起' : '展开'}${group.groupKey}策略列表`}
                      onClick={() => toggleGroup(group.groupKey)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          toggleGroup(group.groupKey);
                        }
                      }}
                      className="cursor-pointer border-b border-crypto-border/70 transition-colors last:border-0 hover:bg-white/[0.025] focus-visible:bg-white/[0.035] focus-visible:outline-none"
                    >
                      <td className="min-w-[300px] px-3 py-3 font-semibold text-gray-100">
                        <div className="flex min-w-0 items-center gap-2">
                          <ChevronRight className={clsx('h-3.5 w-3.5 shrink-0 text-blue-300 transition-transform', expanded && 'rotate-90')} />
                          <span className="truncate">{group.groupKey}</span>
                        </div>
                      </td>
                      <td className="px-3 py-3 tabular-nums text-gray-400">{group.strategyCount}</td>
                      <td className={clsx('px-3 py-3 font-semibold tabular-nums', metricTone(group.returnPct) === 'up' ? 'text-up' : metricTone(group.returnPct) === 'down' ? 'text-down' : 'text-blue-400')}>
                        {formatOptionalSignedPercent(group.returnPct)}
                      </td>
                      <td className="px-3 py-3 tabular-nums text-gray-400">{group.maxDrawdownPct == null ? '不可判定' : `${Math.abs(group.maxDrawdownPct).toFixed(1)}%`}</td>
                      <td className="px-3 py-3 tabular-nums text-gray-400">{formatOptionalPercent(group.winRate, 0)}</td>
                      <td className="px-3 py-3 tabular-nums text-gray-400">{formatRatio(group.profitFactor)}</td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-16 rounded-full bg-crypto-bg">
                            <div className={clsx('h-2 rounded-full', scoreTone(group.score))} style={{ width: `${group.score == null ? 4 : Math.max(4, Math.min(100, group.score))}%` }} />
                          </div>
                          <span className="min-w-7 text-right tabular-nums text-gray-400">{group.score ?? '--'}</span>
                        </div>
                      </td>
                      <td className={clsx('whitespace-nowrap px-3 py-3 font-semibold', group.score == null ? 'text-amber-200' : group.score >= 75 ? 'text-emerald-400' : group.score >= 55 ? 'text-yellow-300' : 'text-rose-400')}>
                        {group.verdict}
                      </td>
                    </tr>
                    {expanded && (
                      <tr className="border-b border-crypto-border/70 bg-crypto-bg/35">
                        <td colSpan={8} className="px-3 py-3">
                          <div className="overflow-x-auto rounded-lg border border-crypto-border bg-crypto-card/70">
                            <div className="grid min-w-[880px] grid-cols-[minmax(320px,1fr)_90px_90px_80px_80px_80px_90px_100px] border-b border-crypto-border bg-crypto-bg px-3 py-2 text-[10px] font-semibold uppercase text-gray-500">
                              <div>策略</div>
                              <div>权益变化</div>
                              <div>回撤</div>
                              <div>胜率</div>
                              <div>盈亏比</div>
                              <div>成交/闭合</div>
                              <div>评分</div>
                              <div>判断</div>
                            </div>
                            {strategies.length === 0 ? (
                              <div className="px-3 py-4 text-center text-xs text-gray-500">暂无组内策略明细</div>
                            ) : (
                              strategies.map((strategy) => (
                                <div
                                  key={`${group.groupKey}-${strategy.strategyId}`}
                                  className="grid min-w-[880px] grid-cols-[minmax(320px,1fr)_90px_90px_80px_80px_80px_90px_100px] items-center border-b border-crypto-border/60 px-3 py-2.5 text-[11px] last:border-0"
                                >
                                  <div className="min-w-0">
                                    <div className="truncate font-medium text-gray-100" title={strategy.name}>{strategy.name}</div>
                                    <div className="mt-1 text-[10px] text-gray-600">覆盖 {strategy.coverageStart || '--'} 至 {strategy.coverageEnd || '--'} · 权益点 {strategy.sampleCount}</div>
                                    <div className="mt-1 flex flex-wrap gap-1">
                                      {strategy.tags.slice(0, 3).map((tag) => (
                                        <span key={`${strategy.strategyId}-${tag}`} className="rounded border border-crypto-border bg-crypto-bg px-1.5 py-0.5 text-[10px] text-gray-500">{tag}</span>
                                      ))}
                                    </div>
                                  </div>
                                  <div className={clsx('font-semibold tabular-nums', metricTone(strategy.returnPct) === 'up' ? 'text-up' : metricTone(strategy.returnPct) === 'down' ? 'text-down' : 'text-blue-400')}>
                                    {formatOptionalSignedPercent(strategy.returnPct)}
                                  </div>
                                  <div className="tabular-nums text-gray-400">{strategy.maxDrawdownPct == null ? '--' : `${Math.abs(strategy.maxDrawdownPct).toFixed(1)}%`}</div>
                                  <div className="tabular-nums text-gray-400">{strategy.winRate == null ? '--' : formatPercent(strategy.winRate, 0)}</div>
                                  <div className="tabular-nums text-gray-400">{formatRatio(strategy.profitFactor)}</div>
                                  <div className="tabular-nums text-gray-400">{strategy.tradeCount}/{strategy.closedTradeCount}</div>
                                  <div className="tabular-nums text-gray-300">{strategy.score ?? '--'}</div>
                                  <div className={clsx('font-semibold', strategy.score == null ? 'text-amber-200' : strategy.score >= 75 ? 'text-emerald-400' : strategy.score >= 55 ? 'text-yellow-300' : 'text-rose-400')}>
                                    {strategy.verdict}
                                  </div>
                                </div>
                              ))
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function LeaderColumn({
  title,
  items,
  tone,
}: {
  title: string;
  items: ReviewLeaderboardItem[];
  tone: 'green' | 'red' | 'amber';
}) {
  const isPositiveList = tone === 'green';
  const isInsufficientList = tone === 'amber';
  return (
    <div className="rounded-xl border border-crypto-border bg-crypto-bg/40 p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className={clsx('inline-flex items-center gap-1.5 text-xs font-semibold', isPositiveList ? 'text-emerald-400' : isInsufficientList ? 'text-amber-200' : 'text-rose-400')}>
          {isPositiveList ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
          {title}
        </h3>
        <span className="rounded-md border border-crypto-border bg-crypto-card px-2 py-0.5 text-[10px] text-gray-500">{items.length}</span>
      </div>
      <div className="space-y-2">
        {items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-crypto-border p-4 text-center text-xs text-gray-500">暂无策略</div>
        ) : (
          items.map((item) => (
            <div
              key={`${title}-${item.strategyId}`}
              className={clsx(
                'min-w-0 rounded-lg border p-3 transition-colors',
                isPositiveList
                  ? 'border-emerald-500/15 bg-emerald-500/[0.035] hover:border-emerald-500/25'
                  : isInsufficientList
                    ? 'border-amber-500/20 bg-amber-500/[0.04] hover:border-amber-500/30'
                    : 'border-rose-500/15 bg-rose-500/[0.035] hover:border-rose-500/25',
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="line-clamp-2 text-xs font-semibold leading-5 text-gray-100">{item.name}</div>
                  <div className="mt-1 truncate text-[10px] text-gray-500">{item.groupKey}</div>
                </div>
                <div className={clsx('inline-flex h-7 min-w-8 shrink-0 items-center justify-center rounded-md border px-1.5 text-xs font-bold tabular-nums', isPositiveList ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300' : isInsufficientList ? 'border-amber-500/25 bg-amber-500/10 text-amber-200' : 'border-rose-500/25 bg-rose-500/10 text-rose-300')}>{item.score ?? '--'}</div>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-[10px]">
                <div>
                  <span className="block text-gray-500">权益变化</span>
                  <strong className={clsx('tabular-nums', item.returnPct == null ? 'text-amber-200' : item.returnPct >= 0 ? 'text-up' : 'text-down')}>{formatOptionalSignedPercent(item.returnPct)}</strong>
                </div>
                <div>
                  <span className="block text-gray-500">回撤</span>
                  <strong className="tabular-nums text-gray-300">{item.maxDrawdownPct == null ? '--' : `${Math.abs(item.maxDrawdownPct).toFixed(1)}%`}</strong>
                </div>
                <div>
                  <span className="block text-gray-500">成交/闭合</span>
                  <strong className="tabular-nums text-gray-300">{item.tradeCount}/{item.closedTradeCount}</strong>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {item.tags.slice(0, 3).map((tag) => (
                  <span key={tag} className="rounded border border-crypto-border bg-crypto-card px-1.5 py-0.5 text-[10px] text-gray-400">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function Leaderboard({ summary }: { summary: ReviewSummary }) {
  return (
    <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
      <SectionTitle icon={<Flame className="h-4 w-4" />} title="策略质量分组" meta="仅充足样本参与评分" />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <LeaderColumn title="值得继续观察" items={summary.leaderboard.observe} tone="green" />
        <LeaderColumn title="需要复查/等待" items={summary.leaderboard.review} tone="red" />
        <LeaderColumn title="样本不足/不可判定" items={summary.leaderboard.insufficient ?? []} tone="amber" />
      </div>
    </section>
  );
}

function Heatmap({ rows }: { rows: ReviewHeatmapRow[] }) {
  const { upColor, downColor } = useSettingsStore((s) => s.getColors());
  const maxBucketCount = Math.max(0, ...rows.map((row) => row.buckets.length));
  const headerBuckets = rows.find((row) => row.buckets.length === maxBucketCount)?.buckets || [];

  return (
    <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
      <SectionTitle icon={<Clock3 className="h-4 w-4" />} title="小时权益变化热力图" meta={`${rows.length} 组`} />
      {rows.length === 0 ? (
        <EmptyState text="暂无小时权益变化桶。" />
      ) : (
        <div className="overflow-x-auto">
          <div className="min-w-[760px]">
            <div className="grid items-center gap-2" style={{ gridTemplateColumns: `150px repeat(${Math.max(1, headerBuckets.length)}, 24px)` }}>
              <div />
              {headerBuckets.map((bucket, index) => (
                <div key={`${bucket.hour}-${index}`} className="text-center text-[10px] text-gray-500">{bucket.hour}</div>
              ))}
            </div>
            <div className="mt-3 space-y-3">
              {rows.map((row) => (
                <div key={row.groupKey} className="grid items-center gap-2" style={{ gridTemplateColumns: `150px repeat(${Math.max(1, headerBuckets.length)}, 24px)` }}>
                  <div className="truncate text-xs font-medium text-gray-400" title={row.groupKey}>{row.label}</div>
                  {row.buckets.map((bucket, index) => (
                    <div
                      key={`${row.groupKey}-${bucket.hour}-${index}`}
                      className="h-6 w-6 rounded-[5px] border shadow-inner shadow-black/30 transition-transform hover:scale-110"
                      style={heatToneStyle(bucket, upColor, downColor)}
                      title={`${row.groupKey} · ${bucket.hour} · ${formatSignedPercent(bucket.returnPct)}`}
                    />
                  ))}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function TagPanel({ tags, nextActions }: { tags: ReviewTag[]; nextActions: string[] }) {
  const tagClass = (label: string) => {
    if (label.includes('稳健')) return 'border-emerald-500/60 bg-emerald-500/10 text-emerald-300';
    if (label.includes('失血') || label.includes('马丁')) return 'border-rose-500/60 bg-rose-500/10 text-rose-300';
    if (label.includes('回撤')) return 'border-yellow-500/60 bg-yellow-500/10 text-yellow-200';
    if (label.includes('转强')) return 'border-blue-500/60 bg-blue-500/10 text-blue-300';
    return 'border-crypto-border bg-crypto-bg text-gray-300';
  };

  return (
    <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
      <SectionTitle icon={<ListChecks className="h-4 w-4" />} title="复盘结论标签" meta={`${tags.length} 类`} />
      <div className="flex flex-wrap gap-3">
        {tags.length === 0 ? (
          <span className="text-xs text-gray-500">暂无标签。</span>
        ) : (
          tags.map((tag) => (
            <span key={tag.label} className={clsx('rounded-lg border px-3 py-2 text-xs font-semibold', tagClass(tag.label))}>
              {tag.label} {tag.count}
            </span>
          ))
        )}
      </div>
      <div className="mt-6 border-t border-crypto-border pt-4">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-white">
          <Target className="h-3.5 w-3.5 text-blue-300" />
          下一步建议
        </div>
        <div className="space-y-2 text-xs leading-relaxed text-gray-400">
          {nextActions.map((action, index) => (
            <div key={action} className="flex gap-2 rounded-lg border border-crypto-border bg-crypto-bg/50 px-3 py-2">
              <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded bg-blue-500/10 text-[10px] font-bold text-blue-300">
                {index + 1}
              </span>
              <span>{action}</span>
              <ChevronRight className="ml-auto mt-0.5 h-3.5 w-3.5 shrink-0 text-gray-600" />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function ReviewDashboard() {
  const [windowKey, setWindowKey] = useState<ReviewWindow>('24h');
  const [summary, setSummary] = useState<ReviewSummary | null>(null);
  const [marketPhase, setMarketPhase] = useState<MarketPhase | null>(null);
  const [marketMovers, setMarketMovers] = useState<SymbolAbnormality[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSummary = useCallback(async (quiet = false) => {
    if (quiet) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    try {
      const [data, phase, movers] = await Promise.all([
        reviewApi.getSummary({ window: windowKey, bucket: REVIEW_BUCKET }),
        marketApi.getPhase().catch(() => null),
        marketApi.getMovers(undefined, 8).catch(() => []),
      ]);
      setSummary(data);
      setMarketPhase(phase);
      setMarketMovers(movers);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || '读取复盘数据失败');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [windowKey]);

  useEffect(() => {
    void fetchSummary();
  }, [fetchSummary]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void fetchSummary(true);
    }, REVIEW_AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [fetchSummary]);

  const overview = summary?.overview;
  const denominator = overview?.healthDenominator;
  const coverageLabel = overview?.coverageStart && overview?.coverageEnd
    ? `${overview.coverageStart} 至 ${overview.coverageEnd}`
    : '暂无覆盖';
  const kpis = useMemo(() => [
    {
      label: '组合权益变化',
      value: formatOptionalSignedPercent(overview?.overallReturnPct),
      sub: `${overview?.strategyCount ?? 0} 策略 · ${overview?.sampleStrategyCount ?? 0} 可判定`,
      tone: metricTone(overview?.overallReturnPct ?? 0),
    },
    {
      label: '中位权益变化',
      value: formatOptionalSignedPercent(overview?.medianReturnPct),
      sub: `${windowKey.toUpperCase()} · 覆盖 ${coverageLabel}`,
      tone: metricTone(overview?.medianReturnPct ?? 0),
    },
    {
      label: '最大回撤',
      value: overview?.maxDrawdownPct == null ? '不可判定' : `${Math.abs(overview.maxDrawdownPct).toFixed(1)}%`,
      sub: `权益采样点 ${overview?.equitySampleCount ?? 0}`,
      tone: 'down' as const,
    },
    {
      label: '可继续观察',
      value: String(overview?.observeCount ?? 0),
      sub: '评分 ≥ 75 且样本较健康',
      tone: 'blue' as const,
    },
    {
      label: '样本不足',
      value: String(overview?.insufficientStrategyCount ?? 0),
      sub: `成交 ${overview?.fillCount ?? 0} · 闭合 ${overview?.closedTradeCount ?? 0}`,
      tone: 'yellow' as const,
    },
    {
      label: '样本健康度',
      value: overview?.sampleHealthStatus === 'insufficient_sample' ? '样本不足' : formatPercent(overview?.sampleHealthPct ?? 0, 0),
      sub: `健康度 ${formatPercent(overview?.sampleHealthPct ?? 0, 0)} · 每策略门槛：日 ≥ ${denominator?.minTradingDays ?? 0} · 权益 ≥ ${denominator?.minEquityPoints ?? 0} · 闭合 ≥ ${denominator?.minClosedTrades ?? 0} · 水位完整`,
      tone: 'cyan' as const,
    },
  ], [coverageLabel, denominator, overview, windowKey]);

  return (
    <div className="p-6 h-full min-h-0 overflow-y-auto">
      <div className="mb-5 rounded-xl border border-crypto-border bg-crypto-card px-4 py-3 shadow-inner shadow-black/10">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-blue-500/25 bg-blue-500/10 text-blue-300 shadow-inner shadow-blue-950/20">
                <ClipboardList className="h-4 w-4" />
              </span>
              <h1 className="truncate text-xl font-bold leading-tight text-white">复盘中心</h1>
              <span className="rounded-md border border-blue-500/20 bg-blue-500/10 px-2 py-1 text-[11px] font-medium text-blue-300">
                运行中模拟策略
              </span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
              <span className="inline-flex h-7 items-center gap-1.5 rounded-md border border-crypto-border bg-crypto-bg/80 px-2.5">
                <TimerReset className="h-3 w-3 text-blue-300" />
                <span>刷新</span>
                <span className="font-semibold text-gray-200">1H</span>
              </span>
              <span className="inline-flex h-7 items-center gap-1.5 rounded-md border border-crypto-border bg-crypto-bg/80 px-2.5">
                <Clock3 className="h-3 w-3 text-blue-300" />
                <span>最新</span>
                <span className="font-semibold text-gray-200">{updatedAtText(overview?.updatedAt)}</span>
              </span>
              <span className="inline-flex h-7 items-center gap-1.5 rounded-md border border-blue-500/20 bg-blue-500/10 px-2.5 text-blue-300">
                <CheckCircle2 className="h-3 w-3" />
                <span>口径</span>
                <span className="font-semibold text-blue-200">仅模拟盘</span>
              </span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 xl:justify-end">
            <div className="flex h-9 rounded-lg border border-crypto-border bg-crypto-bg p-1">
              {REVIEW_WINDOWS.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  aria-pressed={windowKey === item.key}
                  onClick={() => setWindowKey(item.key)}
                  className={clsx(
                    'h-7 rounded-md px-4 text-xs font-semibold transition-colors',
                    windowKey === item.key ? SELECTED_SEGMENT_CLASS : 'text-gray-500 hover:bg-white/[0.03] hover:text-gray-200',
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => void fetchSummary(true)}
              disabled={refreshing}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-600/15 px-3 text-xs font-medium text-blue-300 shadow-inner shadow-blue-950/20 transition-colors hover:border-blue-400/50 hover:bg-blue-600/25 disabled:cursor-wait disabled:opacity-60"
            >
              <RefreshCw className={clsx('h-3.5 w-3.5', refreshing && 'animate-spin')} />
              刷新
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      {loading && !summary ? (
        <div className="flex min-h-[360px] items-center justify-center rounded-xl border border-crypto-border bg-crypto-card">
          <div className="flex items-center gap-3 text-sm text-gray-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在加载复盘数据
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          {(overview?.strategyCount ?? 0) === 0 && (
            <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-white">当日市场复盘</h2>
                  <p className="mt-1 text-[11px] text-gray-500">
                    尚无已完成回测样本，先用本地行情阶段与异动对照。交易日 {marketPhase?.tradeDate || '—'} · 阶段 {marketPhase?.phase || '待计算'}
                  </p>
                </div>
                <span className="rounded-md border border-cyan-500/25 bg-cyan-500/10 px-2 py-1 text-[11px] font-semibold text-cyan-200">
                  置信度 {marketPhase?.confidence == null ? '—' : `${Math.round(marketPhase.confidence * 100)}%`}
                </span>
              </div>
              <div className="divide-y divide-crypto-border/40">
                {marketMovers.slice(0, 8).map((row) => (
                  <div key={row.symbol} className="grid grid-cols-[minmax(0,1fr)_88px_88px] items-center gap-2 py-2 text-xs">
                    <span className="truncate text-gray-200">{row.name || row.symbol}</span>
                    <span className="truncate text-right text-gray-500">{row.symbol}</span>
                    <span className={clsx('text-right tabular-nums', (row.return3d || 0) >= 0 ? 'text-up' : 'text-down')}>
                      {row.return3d == null ? '—' : `${row.return3d >= 0 ? '+' : ''}${row.return3d.toFixed(2)}%`}
                    </span>
                  </div>
                ))}
                {!marketMovers.length && (
                  <div className="py-6 text-center text-xs text-gray-500">当日异动尚未生成</div>
                )}
              </div>
            </section>
          )}
          {(summary?.diagnostics?.length ?? 0) > 0 && (
            <section className="rounded-xl border border-amber-500/30 bg-amber-500/[0.07] p-4">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-200" />
                <div className="min-w-0">
                  <h2 className="text-sm font-semibold text-amber-100">样本诊断</h2>
                  <ul className="mt-2 space-y-1 text-xs leading-relaxed text-amber-100/75">
                    {summary?.diagnostics.map((item) => <li key={item}>· {item}</li>)}
                  </ul>
                </div>
              </div>
            </section>
          )}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-6">
            {kpis.map((item) => (
              <KpiCard key={item.label} {...item} />
            ))}
          </div>

          <div className="grid grid-cols-1 gap-6 2xl:grid-cols-[minmax(0,1.7fr)_minmax(420px,1fr)]">
            <GroupMatrix groups={summary?.groups ?? []} />
            {summary ? <Leaderboard summary={summary} /> : <EmptyState text="暂无复盘榜单。" />}
          </div>

          <div className="grid grid-cols-1 gap-6 2xl:grid-cols-[minmax(0,1.7fr)_minmax(420px,1fr)]">
            <Heatmap rows={summary?.heatmap ?? []} />
            <TagPanel tags={summary?.tags ?? []} nextActions={summary?.nextActions ?? []} />
          </div>

          <div className="rounded-xl border border-crypto-border bg-crypto-card p-4">
            <div className="flex items-start gap-3">
              <Target className="mt-0.5 h-4 w-4 text-blue-400" />
              <div>
                <div className="text-sm font-semibold text-white">复盘口径</div>
                <div className="mt-1 text-xs leading-relaxed text-gray-500">
                  本页只读取已完成 A 股回测的权益采样、委托与成交证据。只有满足当前窗口最低交易日、权益点、闭合交易和数据水位四项门槛的策略才参与评分与好坏分组；样本不足时不以业务零替代缺失指标。
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
