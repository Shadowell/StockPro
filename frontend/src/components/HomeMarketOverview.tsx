import { useState, type ReactNode } from 'react';
import clsx from 'clsx';
import {
  Activity,
  BarChart3,
  Database,
  Gauge,
  RefreshCw,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import type {
  MarketOverview,
  MarketOverviewEvidence,
  MarketOverviewRankingItem,
} from '../api/client';

export interface HomeMarketOverviewProps {
  data: MarketOverview | null;
  loading: boolean;
  error?: string | null;
  refreshing?: boolean;
  onRefresh: () => void;
  onSelectSymbol: (symbol: string) => void;
}

type RankingKey = 'topGainers' | 'topLosers' | 'turnoverLeaders' | 'activeLeaders';

const STATUS_LABELS: Record<string, string> = {
  ready: '已就绪',
  partial: '部分可用',
  blocked: '等待历史数据',
  stale: '过期快照',
  empty: '暂无数据',
  error: '读取失败',
};

const RANKINGS: Array<{ key: RankingKey; label: string; description: string }> = [
  { key: 'topGainers', label: '涨幅榜', description: '当日涨跌幅降序' },
  { key: 'topLosers', label: '跌幅榜', description: '当日涨跌幅升序' },
  { key: 'turnoverLeaders', label: '成交额榜', description: '当日成交额降序' },
  { key: 'activeLeaders', label: '活跃换手榜', description: '换手率降序' },
];

function statusLabel(status?: string | null): string {
  return STATUS_LABELS[status || ''] || status || '未知状态';
}

function formatNumber(value?: number | null, digits = 2): string {
  return value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatPercent(value?: number | null, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

function formatAmount(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${(value / 1e12).toFixed(2)} 万亿 CNY`;
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)} 亿 CNY`;
  if (abs >= 1e4) return `${(value / 1e4).toFixed(2)} 万 CNY`;
  return `${value.toFixed(2)} CNY`;
}

function formatTimestamp(value?: string | null): string {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatAge(seconds?: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—';
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`;
  return `${(seconds / 3600).toFixed(1)} 小时`;
}

function StatusBadge({ status }: { status?: string | null }) {
  const tone = status === 'ready'
    ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
    : status === 'error'
      ? 'border-rose-500/25 bg-rose-500/10 text-rose-300'
      : status === 'blocked' || status === 'partial' || status === 'stale'
        ? 'border-amber-500/25 bg-amber-500/10 text-amber-300'
        : 'border-slate-600/50 bg-slate-900/70 text-slate-400';
  return (
    <span className={clsx('rounded-md border px-2 py-0.5 text-[10px] font-medium', tone)}>
      {statusLabel(status)}
    </span>
  );
}

function EvidenceStrip({ evidence }: { evidence: MarketOverviewEvidence }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-crypto-border/70 bg-slate-950/35 px-4 py-2 text-[11px] text-gray-500">
      <span>交易日 <strong className="font-mono font-medium text-gray-300">{evidence.tradeDate || '—'}</strong></span>
      <span>模式 <strong className="font-medium text-gray-300">{evidence.dataMode || '盘后快照'}</strong></span>
      <span>来源 <strong className="font-medium text-gray-300">{evidence.provider || '—'}</strong></span>
      <span>快照 <strong className="font-mono font-medium text-gray-300">{evidence.sourceSnapshotId ?? '—'}</strong></span>
      <span>最近成功 <strong className="font-mono font-medium text-gray-300">{formatTimestamp(evidence.lastSuccessAt)}</strong></span>
      <span>数据年龄 <strong className="font-mono font-medium text-gray-300">{formatAge(evidence.dataAgeSeconds)}</strong></span>
      <StatusBadge status={evidence.status} />
      {evidence.missingInputs.length > 0 ? (
        <span className="min-w-0 flex-1 truncate text-amber-300/80" title={evidence.missingInputs.join(' · ')}>
          缺失：{evidence.missingInputs.slice(0, 2).join(' · ')}
        </span>
      ) : null}
    </div>
  );
}

function ModuleShell({
  title,
  icon,
  status,
  children,
  className,
}: {
  title: string;
  icon: ReactNode;
  status?: string | null;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={clsx('overflow-hidden rounded-xl border border-crypto-border bg-crypto-card/95', className)}>
      <div className="flex items-center justify-between gap-3 border-b border-crypto-border/70 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2 text-sm font-semibold text-gray-100">
          {icon}
          <h2>{title}</h2>
        </div>
        <StatusBadge status={status} />
      </div>
      {children}
    </section>
  );
}

function IndexStrip({ overview, onSelectSymbol }: { overview: MarketOverview; onSelectSymbol: (symbol: string) => void }) {
  const { indices } = overview;
  return (
    <ModuleShell title="指数行情" icon={<TrendingUp className="h-4 w-4 text-blue-300" />} status={indices.status}>
      <div className="grid grid-cols-1 gap-2 p-3 sm:grid-cols-2 xl:grid-cols-4">
        {indices.items.length ? indices.items.map((item) => (
          <button
            key={item.symbol}
            type="button"
            onClick={() => onSelectSymbol(item.symbol)}
            data-metric-card
            className="group min-w-0 rounded-xl border border-crypto-border/70 bg-crypto-card px-4 py-3 text-left transition-colors hover:bg-slate-800/75"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-xs font-semibold text-gray-200">{item.name}</span>
              <span className="font-mono text-[10px] text-gray-600">{item.symbol}</span>
            </div>
            <div className="mt-2 flex items-baseline justify-between gap-2">
              <span className="font-mono text-xl font-semibold tabular-nums text-gray-100">{formatNumber(item.price, 2)}</span>
              <span className={clsx('font-mono text-sm font-semibold tabular-nums', (item.changePercent ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                {formatPercent(item.changePercent)}
              </span>
            </div>
            <div className="mt-1 truncate text-[10px] text-gray-600 group-hover:text-gray-500">
              {item.source || '—'} · {item.tradeDate || overview.tradeDate || '—'}
            </div>
          </button>
        )) : (
          <div className="col-span-full flex min-h-24 items-center justify-center px-4 text-xs text-gray-500">
            指数数据不可用；未使用股票行情替代指数。
          </div>
        )}
      </div>
    </ModuleShell>
  );
}

function Value({ value, suffix = '', digits = 2 }: { value?: number | null; suffix?: string; digits?: number }) {
  return <span className="font-mono tabular-nums text-gray-100">{formatNumber(value, digits)}{value == null ? '' : suffix}</span>;
}

function BreadthAndDistribution({ overview }: { overview: MarketOverview }) {
  const { breadth, distribution } = overview;
  const showNumbers = breadth.status === 'ready' || breadth.status === 'partial';
  const breadthPercent = showNumbers && breadth.advanceRatioPct != null ? Math.max(0, Math.min(100, breadth.advanceRatioPct)) : 0;
  return (
    <ModuleShell title="市场宽度 · 涨跌分布" icon={<BarChart3 className="h-4 w-4 text-cyan-300" />} status={breadth.status}>
      <div className="grid gap-4 p-4 xl:grid-cols-[0.9fr_1.35fr]">
        <div>
          <div className="grid grid-cols-3 gap-2">
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/[0.06] p-3">
              <div className="text-[11px] text-emerald-300">上涨</div>
              <div className="mt-1"><Value value={showNumbers ? breadth.gainers : null} digits={0} /></div>
            </div>
            <div className="rounded-lg border border-slate-500/20 bg-slate-500/[0.05] p-3">
              <div className="text-[11px] text-slate-300">平盘</div>
              <div className="mt-1"><Value value={showNumbers ? breadth.flat : null} digits={0} /></div>
            </div>
            <div className="rounded-lg border border-rose-500/20 bg-rose-500/[0.06] p-3">
              <div className="text-[11px] text-rose-300">下跌</div>
              <div className="mt-1"><Value value={showNumbers ? breadth.losers : null} digits={0} /></div>
            </div>
          </div>
          <div className="mt-4 flex items-center justify-between text-xs text-gray-500">
            <span>上涨占比</span>
            <span className="font-mono tabular-nums text-gray-300">{showNumbers ? formatPercent(breadth.advanceRatioPct, 1) : '—'}</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-800">
            <div className="h-full rounded-full bg-blue-400/80" style={{ width: `${breadthPercent}%` }} />
          </div>
          <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-gray-500">
            <span>强势 ≥ {formatNumber(breadth.strongMoveThresholdPct, 0)}%</span>
            <Value value={showNumbers ? breadth.strongCount : null} suffix=" 家" digits={0} />
            <span>弱势 ≤ -{formatNumber(breadth.strongMoveThresholdPct, 0)}%</span>
            <Value value={showNumbers ? breadth.weakCount : null} suffix=" 家" digits={0} />
            <span>平均涨跌</span>
            <span className={clsx((breadth.meanChangePct ?? 0) >= 0 ? 'text-up' : 'text-down')}>
              {showNumbers ? formatPercent(breadth.meanChangePct) : '—'}
            </span>
            <span>中位涨跌</span>
            <span className={clsx((breadth.medianChangePct ?? 0) >= 0 ? 'text-up' : 'text-down')}>
              {showNumbers ? formatPercent(breadth.medianChangePct) : '—'}
            </span>
          </div>
        </div>
        <div>
          <div className="mb-2 flex items-center justify-between text-[11px] text-gray-500">
            <span>分布区间</span>
            <span>分母：{distribution.denominator}</span>
          </div>
          <div className="space-y-2">
            {distribution.buckets.map((bucket) => {
              const width = bucket.percentage == null ? 0 : Math.max(0, Math.min(100, bucket.percentage));
              return (
                <div key={bucket.key} className="grid grid-cols-[72px_minmax(0,1fr)_70px] items-center gap-2 text-[11px]">
                  <span className="font-mono text-gray-500">{bucket.label}</span>
                  <div className="h-1.5 overflow-hidden rounded-full bg-slate-800">
                    <div className="h-full rounded-full bg-slate-500/80" style={{ width: `${width}%` }} />
                  </div>
                  <span className="text-right font-mono tabular-nums text-gray-400">
                    {bucket.count == null ? '—' : `${bucket.count} · ${bucket.percentage?.toFixed(1)}%`}
                  </span>
                </div>
              );
            })}
          </div>
          <p className="mt-3 text-[10px] leading-4 text-gray-600">{distribution.boundaryDefinition}</p>
        </div>
      </div>
    </ModuleShell>
  );
}

function TrendStrength({ overview }: { overview: MarketOverview }) {
  const { trend } = overview;
  const unavailableMetric = { count: null, percentage: null };
  const metrics: Array<[string, { count?: number | null; percentage?: number | null }]> = [
    ['站上 MA5', trend.aboveMa5 || unavailableMetric],
    ['站上 MA20', trend.aboveMa20 || unavailableMetric],
    ['站上 MA60', trend.aboveMa60 || unavailableMetric],
    ['60 日新高', trend.newHigh60d || trend.newHigh_60d || unavailableMetric],
    ['60 日新低', trend.newLow60d || trend.newLow_60d || unavailableMetric],
  ];
  return (
    <ModuleShell title="趋势强度" icon={<Gauge className="h-4 w-4 text-violet-300" />} status={trend.status}>
      <div className="p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-gray-500">
          <span>历史门槛：至少 {trend.requiredHistoryDays} 个确认交易日</span>
          <span>覆盖 {trend.coveredSymbols || 0} / {trend.totalSymbols || 0} 个标的</span>
        </div>
        {trend.status === 'blocked' || trend.status === 'empty' ? (
          <div className="mb-3 rounded-lg border border-amber-500/20 bg-amber-500/[0.05] px-3 py-2 text-xs leading-5 text-amber-200/80">
            {trend.missingInputs.join(' · ') || '历史数据不足，趋势指标保持不可用。'}
          </div>
        ) : null}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {metrics.map(([label, metric]) => (
            <div key={label} className="rounded-lg border border-crypto-border/70 bg-slate-950/35 px-3 py-3">
              <div className="truncate text-[11px] text-gray-500">{label}</div>
              <div className="mt-2 font-mono text-lg font-semibold tabular-nums text-gray-100">{metric.count == null ? '—' : metric.count}</div>
              <div className="mt-1 font-mono text-[10px] tabular-nums text-gray-600">{metric.percentage == null ? '—' : `${metric.percentage.toFixed(1)}%`}</div>
            </div>
          ))}
        </div>
        <div className="mt-3 text-[10px] text-gray-600">分母：{trend.denominator} · 新高/新低比 {trend.newHighLowRatio == null ? '—' : formatNumber(trend.newHighLowRatio)}</div>
      </div>
    </ModuleShell>
  );
}

function ActivitySummary({ overview }: { overview: MarketOverview }) {
  const { activity } = overview;
  return (
    <ModuleShell title="成交与换手" icon={<Activity className="h-4 w-4 text-amber-300" />} status={activity.status}>
      <div className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-3 xl:grid-cols-6">
        {[
          ['全市场成交额', formatAmount(activity.totalAmountCny)],
          ['个股平均成交额', formatAmount(activity.averageAmountCny)],
          ['平均换手率', activity.averageTurnoverRatePct == null ? '—' : `${formatNumber(activity.averageTurnoverRatePct)}%`],
          ['平均量比', activity.averageVolumeRatio == null ? '—' : `${formatNumber(activity.averageVolumeRatio)} 倍`],
          ['高换手', activity.highTurnoverCount == null ? '—' : `${activity.highTurnoverCount} 家`],
          ['放量股票', activity.volumeExpansionCount == null ? '—' : `${activity.volumeExpansionCount} 家`],
        ].map(([label, value]) => (
          <div key={label} data-metric-card className="min-w-0 rounded-xl border border-crypto-border/70 bg-crypto-card px-3 py-3">
            <div className="truncate text-[11px] text-gray-500">{label}</div>
            <div className="mt-2 truncate font-mono text-sm font-semibold tabular-nums text-gray-100">{value}</div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 px-4 py-2 text-[10px] text-gray-600">
        <span>换手阈值 ≥ {formatNumber(activity.highTurnoverThresholdPct, 0)}%</span>
        <span>放量阈值 ≥ {formatNumber(activity.volumeRatioThreshold)} 倍</span>
        <span>{activity.amountDenominator}</span>
      </div>
    </ModuleShell>
  );
}

function rankingMetric(key: RankingKey, item: MarketOverviewRankingItem): string {
  if (key === 'turnoverLeaders') return formatAmount(item.amountCny);
  if (key === 'activeLeaders') return item.turnoverRatePct == null ? '—' : `${formatNumber(item.turnoverRatePct)}%`;
  return formatPercent(item.changePercent);
}

function Rankings({ overview, onSelectSymbol }: { overview: MarketOverview; onSelectSymbol: (symbol: string) => void }) {
  const [activeKey, setActiveKey] = useState<RankingKey>('topGainers');
  const activeRanking = RANKINGS.find((item) => item.key === activeKey) || RANKINGS[0];
  const items = overview.rankings[activeKey] || [];
  return (
    <ModuleShell title="排行榜" icon={<TrendingDown className="h-4 w-4 text-sky-300" />} status={overview.rankings.status}>
      <div className="flex gap-2 overflow-x-auto border-b border-crypto-border/60 px-4 py-3">
        {RANKINGS.map((ranking) => (
          <button
            key={ranking.key}
            type="button"
            aria-pressed={activeKey === ranking.key}
            onClick={() => setActiveKey(ranking.key)}
            className={clsx(
              'shrink-0 rounded-md border px-3 py-1.5 text-xs transition-colors',
              activeKey === ranking.key
                ? 'border-blue-400/40 bg-blue-500/15 text-blue-200'
                : 'border-crypto-border bg-slate-950/25 text-gray-500 hover:text-gray-200',
            )}
          >
            {ranking.label}
          </button>
        ))}
      </div>
      <div className="flex items-center justify-between gap-3 px-4 py-2 text-[11px] text-gray-500">
        <span>{activeRanking.description}</span>
        <span>Top {overview.rankings.limit} · 点击进入行情</span>
      </div>
      <div className="overflow-x-auto">
        <div className="min-w-[620px]">
          <div className="grid grid-cols-[44px_minmax(220px,1fr)_130px_110px_110px] gap-3 border-y border-crypto-border/50 bg-slate-950/30 px-4 py-2 text-[11px] text-gray-500">
            <span>排名</span><span>标的</span><span>最新价</span><span>指标</span><span>成交额</span>
          </div>
          {items.length ? items.map((item, index) => (
            <button
              key={`${activeKey}-${item.symbol}`}
              type="button"
              onClick={() => onSelectSymbol(item.symbol)}
              className="grid w-full grid-cols-[44px_minmax(220px,1fr)_130px_110px_110px] items-center gap-3 border-b border-crypto-border/40 px-4 py-2.5 text-left transition-colors hover:bg-white/[0.03]"
            >
              <span className="font-mono text-xs text-gray-500">{String(index + 1).padStart(2, '0')}</span>
              <span className="min-w-0">
                <span className="block truncate text-xs font-semibold text-gray-200">{item.name}（{item.symbol}）</span>
                <span className="mt-0.5 block truncate text-[10px] text-gray-600">{item.exchange} · {item.tradeDate || overview.tradeDate || '—'}</span>
              </span>
              <span className="font-mono text-xs tabular-nums text-gray-300">{formatNumber(item.price)}</span>
              <span className={clsx('font-mono text-xs font-semibold tabular-nums', (item.changePercent ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                {rankingMetric(activeKey, item)}
              </span>
              <span className="font-mono text-xs tabular-nums text-gray-500">{formatAmount(item.amountCny)}</span>
            </button>
          )) : (
            <div className="flex h-36 items-center justify-center px-4 text-center text-xs text-gray-500">
              排行榜暂无可用数据；停牌、无价格和无效行情不会进入榜单。
            </div>
          )}
        </div>
      </div>
    </ModuleShell>
  );
}

function Skeleton() {
  return (
    <div aria-busy="true" aria-label="正在加载首页市场指标" className="space-y-3">
      <div className="h-24 animate-pulse rounded-xl border border-crypto-border bg-crypto-card/80" />
      <div className="h-64 animate-pulse rounded-xl border border-crypto-border bg-crypto-card/80" />
      <div className="h-56 animate-pulse rounded-xl border border-crypto-border bg-crypto-card/80" />
    </div>
  );
}

export default function HomeMarketOverview({
  data,
  loading,
  error,
  refreshing = false,
  onRefresh,
  onSelectSymbol,
}: HomeMarketOverviewProps) {
  if (loading && !data) return <Skeleton />;
  if (error && !data) {
    return (
      <section role="alert" className="rounded-xl border border-rose-500/25 bg-rose-500/[0.06] px-4 py-6 text-center">
        <div className="text-sm font-semibold text-rose-200">首页市场指标读取失败</div>
        <div className="mt-1 text-xs text-rose-200/70">{error}</div>
        <button type="button" onClick={onRefresh} className="mt-4 inline-flex h-8 items-center gap-2 rounded-md border border-rose-400/30 px-3 text-xs text-rose-200 hover:bg-rose-500/10">
          <RefreshCw className="h-3.5 w-3.5" /> 重试
        </button>
      </section>
    );
  }
  if (!data) return null;

  return (
    <section data-testid="home-market-overview" className="space-y-3">
      <div className="overflow-hidden rounded-xl border border-blue-500/20 bg-crypto-card/95 shadow-[0_18px_48px_rgba(2,8,23,0.18)]">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex min-w-0 items-center gap-2">
            <Database className="h-4 w-4 text-blue-300" />
            <div>
              <h2 className="text-sm font-semibold text-gray-100">A 股市场基础层</h2>
              <p className="mt-0.5 text-[11px] text-gray-500">指数、宽度、趋势、成交活跃度与真实榜单共用同一份市场事实。</p>
            </div>
          </div>
          <button type="button" onClick={onRefresh} disabled={refreshing} className="inline-flex h-7 items-center gap-1.5 rounded-md border border-crypto-border bg-slate-900 px-2.5 text-xs text-gray-400 transition hover:bg-slate-800 hover:text-white disabled:cursor-wait disabled:opacity-60">
            <RefreshCw className={clsx('h-3.5 w-3.5', refreshing && 'animate-spin')} /> 刷新
          </button>
        </div>
        <EvidenceStrip evidence={data.evidence} />
      </div>
      <IndexStrip overview={data} onSelectSymbol={onSelectSymbol} />
      <BreadthAndDistribution overview={data} />
      <div className="grid gap-3 xl:grid-cols-2">
        <TrendStrength overview={data} />
        <ActivitySummary overview={data} />
      </div>
      <Rankings overview={data} onSelectSymbol={onSelectSymbol} />
    </section>
  );
}
