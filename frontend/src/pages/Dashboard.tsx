import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, Filter, Flame, Info, PieChart, TrendingUp, Zap } from 'lucide-react';
import clsx from 'clsx';
import { MetricCard, StatusBadge } from '@bitpro/ui';
import { getHotConcepts, getMarketOverview, getShortLineIndices, getThsHot } from '../api/client';
import type { HotConceptItem, MarketOverview, ThsHotItem } from '../types';
import { evaluateFreshness, formatFreshnessTime, latestTimestamp } from '../utils/dataFreshness';

type ShortLineIndex = {
  code: string;
  name: string;
  price: number;
  change_percent?: number | null;
  change_amount?: number | null;
  updated_at?: string | null;
  trade_date?: string | null;
  snapshot_id?: number | null;
  data_state?: 'sealed_snapshot' | string | null;
  source_label?: string | null;
  unit?: string | null;
  definition?: string | null;
  comparison_state?: string | null;
};

type DashboardModule = 'overview' | 'hotConcepts' | 'shortLine' | 'thsHot';
type DashboardErrors = Partial<Record<DashboardModule, string>>;

const CACHE_FRESHNESS_MS = 36 * 60 * 60 * 1000;

const MARKET_INDEX_ORDER = ['上证指数', '深证成指', '创业板指', '科创50'];

const formatNumber = (value?: number | null, digits = 2) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits });
};

const formatCompact = (value?: number | null) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  if (Math.abs(value) >= 100000000) return `${formatNumber(value / 100000000, 2)}亿`;
  if (Math.abs(value) >= 10000) return `${formatNumber(value / 10000, 2)}万`;
  return formatNumber(value, 0);
};

const Pct = ({ value }: { value?: number | null }) => (
  <span className={clsx(value === null || value === undefined ? 'text-gray-500' : value >= 0 ? 'text-up' : 'text-down')}>
    {value === null || value === undefined ? '' : value >= 0 ? '+' : ''}
    {value === null || value === undefined ? '--' : formatNumber(value, 2)}{value === null || value === undefined ? '' : '%'}
  </span>
);

const metricText = (value?: number | null, digits = 0) => (
  value === null || value === undefined || Number.isNaN(value) ? '--' : formatNumber(value, digits)
);

const shortLineUnit = (unit?: string | null) => {
  if (unit === 'stocks') return '家';
  if (unit === 'boards') return '板';
  if (unit === 'percent') return '%';
  if (unit === 'ratio') return '倍';
  return '';
};

const shortLineTone = (code: string) => {
  if (['limit_up_count', 'rise_count', 'ZT', 'LIMIT_UP'].includes(code)) return 'border-red-500/30 bg-red-500/[0.045]';
  if (['limit_down_count', 'fall_count', 'LIMIT_DOWN'].includes(code)) return 'border-emerald-500/30 bg-emerald-500/[0.045]';
  if (['broken_board_count', 'highest_board'].includes(code)) return 'border-amber-500/30 bg-amber-500/[0.045]';
  return 'border-blue-500/25 bg-blue-500/[0.035]';
};

const shortLineGroup = (code: string) => {
  if (['limit_up_count', 'limit_down_count', 'broken_board_count', 'highest_board'].includes(code)) return '涨停生态';
  if (['rise_count', 'fall_count', 'rise_fall_ratio'].includes(code)) return '市场广度';
  if (code === 'seal_rate') return '封板质量';
  return '短线强度';
};

const shortLineSource = (source?: string | null) => {
  if (source === 'tushare_limit_list_derived') return 'TuShare 涨跌停证据';
  if (source === 'tushare_daily') return 'TuShare 日线广度';
  return source || '';
};

function RealtimeMarketModule({
  overview,
  hotConcepts,
  shortLine,
  thsHot,
  errors,
  loading,
  onViewAll,
}: {
  overview: MarketOverview | null;
  hotConcepts: HotConceptItem[];
  shortLine: ShortLineIndex[];
  thsHot: ThsHotItem[];
  errors: DashboardErrors;
  loading: boolean;
  onViewAll: () => void;
}) {
  const sourceIndices = overview?.indices || [];
  const orderedIndices = MARKET_INDEX_ORDER
    .map((name) => sourceIndices.find((item) => item.name === name))
    .filter((item): item is NonNullable<MarketOverview['indices']>[number] => Boolean(item));
  const indices = orderedIndices.length >= 4
    ? orderedIndices
    : [...orderedIndices, ...sourceIndices.filter((item) => !MARKET_INDEX_ORDER.includes(item.name))].slice(0, 4);
  const sentiment = overview?.sentiment;
  const breadth = overview?.market_breadth;
  const volume = overview?.volume;
  const snapshotState = overview?.data_status?.stock_snapshot_state ?? 'unavailable';
  const snapshotMessage = overview?.data_status?.message ?? '全市场实时快照未同步';
  const hotConceptFreshness = evaluateFreshness(latestTimestamp(hotConcepts), CACHE_FRESHNESS_MS);
  const thsHotFreshness = evaluateFreshness(latestTimestamp(thsHot), CACHE_FRESHNESS_MS);
  const shortLineFreshness = evaluateFreshness(latestTimestamp(shortLine), CACHE_FRESHNESS_MS);
  const shortLineSnapshot = shortLine.find((item) => item.data_state === 'sealed_snapshot');
  const shortLineTradeDate = shortLineSnapshot?.trade_date ?? null;
  const topGainer = thsHotFreshness.state === 'fresh' ? thsHot[0] : undefined;
  const limitUp = shortLine.find((item) => item.name.includes('涨停')) || shortLine[0];
  const hasStrongConcept = hotConcepts.some((item) => Math.abs(item.change_percent ?? 0) >= 5);
  const visibleHotConcepts = hotConcepts.slice(0, hasStrongConcept ? 30 : 5);
  const hotConceptLimit = hasStrongConcept ? 30 : 5;
  const totalAmount = volume?.amount ?? null;
  const amountUnit = volume?.unit || '亿';
  const upCount = breadth?.up ?? sentiment?.advancing ?? null;
  const downCount = breadth?.down ?? sentiment?.declining ?? null;
  const flatCount = breadth?.flat ?? sentiment?.unchanged ?? null;
  const errorMessages = Object.values(errors).filter(Boolean);
  const freshnessLabel = (state: 'fresh' | 'stale' | 'unavailable', timestamp: string | null) => {
    if (state === 'fresh') return `当前缓存 · ${formatFreshnessTime(timestamp)}`;
    if (state === 'stale') return `陈旧缓存 · ${formatFreshnessTime(timestamp)}`;
    return loading ? '正在读取缓存' : '缓存时间未提供';
  };

  return (
    <div className="space-y-4">
      {errorMessages.length > 0 ? (
        <div className="rounded-lg border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-200" role="alert">
          部分行情模块加载失败：{errorMessages.join('；')}
        </div>
      ) : null}
      <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-crypto-border px-4 py-3">
          <div>
            <h2 className="text-base font-black text-white">市场指数</h2>
            <p className="mt-1 text-xs text-gray-500">A 股主要指数与全市场交易快照</p>
          </div>
          <StatusBadge tone={snapshotState === 'fresh' ? 'green' : 'amber'}>{snapshotState === 'fresh' ? '快照可用' : snapshotMessage}</StatusBadge>
        </div>
        <div className="grid grid-cols-1 gap-4 p-4 md:grid-cols-2 xl:grid-cols-4">
          {indices.map((index) => (
            <MetricCard
              key={index.name}
              label={index.name}
              color={(index.change_percent ?? 0) >= 0 ? 'up' : 'down'}
              value={formatNumber(index.price)}
              detail={<div className="flex flex-wrap items-center gap-2 text-xs font-semibold tabular-nums">
                <Pct value={index.change_percent} />
                <span className={clsx((index.change_amount || 0) >= 0 ? 'text-up' : 'text-down')}>
                  {(index.change_amount || 0) >= 0 ? '+' : ''}
                  {formatNumber(index.change_amount)}
                </span>
              </div>}
            />
          ))}

          {indices.length === 0 && (
            <div className="rounded-lg border border-crypto-border bg-crypto-bg/45 p-4 text-sm text-gray-500 md:col-span-2 xl:col-span-4">
              暂无指数缓存
            </div>
          )}

          <div className="min-h-[156px] rounded-lg border border-crypto-border bg-crypto-bg/45 p-4">
            <div className="mb-4 flex items-center justify-between gap-2">
              <span className="text-sm font-bold text-gray-400">强势股</span>
              <TrendingUp className="h-4 w-4 text-up" />
            </div>
            <div className="text-2xl font-black text-white">{topGainer?.name || '--'}</div>
            {topGainer ? (
              <div className="mt-3 flex items-center gap-2 text-sm font-semibold">
                <span className="text-gray-500">{topGainer.code}</span>
                <Pct value={topGainer.change_percent} />
              </div>
            ) : (
              <div className="mt-3 text-sm font-semibold text-amber-300">
                {errors.thsHot ? '热榜加载失败' : thsHotFreshness.state === 'stale' ? '热榜缓存已陈旧' : '暂无当前热榜'}
              </div>
            )}
            <div className="mt-3 text-[10px] text-gray-600">{topGainer?.source_label || '来源未记录'} · {formatFreshnessTime(thsHotFreshness.timestamp)}</div>
          </div>

          <div className="min-h-[156px] rounded-lg border border-crypto-border bg-crypto-bg/45 p-4">
            <div className="mb-4 flex items-center justify-between gap-2">
              <span className="text-sm font-bold text-gray-400">市场情绪</span>
              <Activity className="h-4 w-4 text-orange-400" />
            </div>
            <div className="text-2xl font-black text-white">{sentiment?.status || '未同步'}</div>
            <div className="mt-3 text-sm font-bold text-orange-400">Index: {metricText(sentiment?.score, 0)}</div>
            <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
              <div>
                <div className="text-gray-600">上涨</div>
                <div className="mt-1 font-bold text-up">{metricText(upCount)}</div>
              </div>
              <div>
                <div className="text-gray-600">下跌</div>
                <div className="mt-1 font-bold text-down">{metricText(downCount)}</div>
              </div>
              <div>
                <div className="text-gray-600">平盘</div>
                <div className="mt-1 font-bold text-gray-300">{metricText(flatCount)}</div>
              </div>
            </div>
            {snapshotState !== 'fresh' ? <div className="mt-3 text-[11px] font-semibold text-amber-300">{snapshotMessage}</div> : null}
          </div>

          <div className="min-h-[156px] rounded-lg border border-crypto-border bg-crypto-bg/45 p-4">
            <div className="mb-4 flex items-center justify-between gap-2">
              <span className="text-sm font-bold text-gray-400">成交额</span>
              <PieChart className="h-4 w-4 text-blue-400" />
            </div>
            <div className="text-2xl font-black text-white tabular-nums">
              {totalAmount === null ? '--' : `${formatNumber(totalAmount, 0)}${amountUnit}`}
            </div>
            <div className="mt-4 space-y-2 text-sm">
              {[
                ['沪', volume?.sh_amount, 'bg-blue-500'],
                ['深', volume?.sz_amount, 'bg-emerald-500'],
                ['北', volume?.bj_amount, 'bg-orange-500'],
              ].map(([label, value, color]) => (
                <div key={label as string} className="flex items-center gap-2">
                  <span className={clsx('h-2.5 w-2.5 rounded-full', color as string)} />
                  <span className="w-4 text-gray-400">{label}</span>
                  <span className="font-semibold text-blue-300 tabular-nums">
                    {value === null || value === undefined ? '--' : `${formatNumber(value as number, 0)}亿`}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="min-h-[156px] rounded-lg border border-crypto-border bg-crypto-bg/45 p-4">
            <div className="mb-4 flex items-center justify-between gap-2">
              <span className="text-sm font-bold text-gray-400">短线指标</span>
              <Info className="h-4 w-4 text-gray-400" />
            </div>
            <div className="text-2xl font-black text-white">
              {limitUp ? `${formatNumber(limitUp.price, 0)} ${limitUp.name.replace('家数', '')}` : '--'}
            </div>
            <div className="mt-3 text-sm font-semibold text-gray-600">
              {shortLineSnapshot ? `历史收盘证据 · ${shortLineTradeDate || '--'}` : shortLine.length ? '异动监控' : '短线快照未同步'}
            </div>
          </div>
        </div>
      </section>

      <section className="overflow-hidden rounded-lg border border-crypto-border bg-crypto-card">
        <div className="flex items-center justify-between gap-3 border-b border-crypto-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-yellow-400" />
            <h2 className="text-base font-black text-white">短线指标</h2>
          </div>
          <StatusBadge tone={shortLineFreshness.state === 'fresh' ? 'green' : 'amber'}>
            {errors.shortLine
              ? '加载失败'
              : shortLineSnapshot
                ? `历史快照 · ${shortLineTradeDate || '--'}`
                : freshnessLabel(shortLineFreshness.state, shortLineFreshness.timestamp)}
          </StatusBadge>
        </div>
        <div className="grid min-h-[132px] grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          {shortLine.length > 0 ? (
            shortLine.slice(0, 8).map((item, index) => (
              <div key={item.code} className={clsx('rounded-lg border p-3', shortLineTone(item.code), index < 4 && 'min-h-[118px]')}>
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs font-semibold text-gray-400">{item.name}</div>
                  {index < 4 ? <span className="text-[9px] font-semibold tracking-wide text-gray-600">{shortLineGroup(item.code)}</span> : null}
                </div>
                <div className={clsx('mt-3 font-black text-white tabular-nums', index < 4 ? 'text-2xl' : 'text-xl')}>
                  {formatNumber(item.price, ['percent', 'ratio'].includes(item.unit || '') ? 2 : 0)}
                  <span className="ml-1 text-xs font-semibold text-gray-500">{shortLineUnit(item.unit)}</span>
                </div>
                <div className="mt-2 line-clamp-2 text-[11px] leading-4 text-gray-500">
                  {item.definition || '当前接口未提供历史可比值'}
                </div>
                {item.source_label ? <div className="mt-2 truncate text-[9px] text-gray-600">{shortLineSource(item.source_label)}</div> : null}
              </div>
            ))
          ) : (
            <div className="flex items-center justify-center text-sm font-semibold text-gray-500 sm:col-span-2 lg:col-span-4">
              当前既无有效实时短线缓存，也无封存市场证据
            </div>
          )}
        </div>
      </section>

      <section className="overflow-hidden rounded-lg border border-crypto-border bg-crypto-card">
        <div className="flex items-center justify-between gap-3 border-b border-crypto-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Flame className="h-4 w-4 text-orange-400" />
            <h2 className="text-base font-black text-white">热门板块</h2>
          </div>
          <div className="flex items-center gap-3">
            <StatusBadge tone={hotConceptFreshness.state === 'fresh' ? 'green' : 'amber'}>
              {errors.hotConcepts ? '加载失败' : freshnessLabel(hotConceptFreshness.state, hotConceptFreshness.timestamp)}
            </StatusBadge>
            <button type="button" onClick={onViewAll} className="text-sm font-bold text-blue-400 transition-colors hover:text-blue-300">查看全部</button>
          </div>
        </div>
        <div className="min-h-[168px] p-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-xl font-black text-white">热门板块 TOP{hotConceptLimit}</h3>
            <button type="button" className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border bg-slate-800 px-3 text-sm font-bold text-gray-300">
              <Filter className="h-4 w-4" />
              TOP{hotConceptLimit}
            </button>
          </div>

          {visibleHotConcepts.length > 0 ? (
            <div className={clsx('grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-5', hotConceptFreshness.state === 'stale' && 'opacity-70')}>
              {visibleHotConcepts.map((item) => (
                <div key={item.name} className="rounded-lg border border-crypto-border bg-crypto-bg/45 p-3">
                  <div className="text-sm font-bold text-white">{item.name}</div>
                  <div className="mt-3 text-lg font-black"><Pct value={item.change_percent} /></div>
                  <div className="mt-2 text-xs text-gray-500">资金净额 {formatCompact(item.net_inflow)} <span className="text-gray-700">· 单位未记录</span></div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex min-h-[88px] items-center justify-center text-sm font-semibold text-gray-500">暂无热门板块数据</div>
          )}
          <div className="mt-3 text-[10px] text-gray-600">{hotConcepts[0]?.source_label || '来源未记录'} · 更新时间 {formatFreshnessTime(hotConceptFreshness.timestamp)}</div>
        </div>
      </section>
    </div>
  );
}

export function Dashboard() {
  const navigate = useNavigate();
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [hotConcepts, setHotConcepts] = useState<HotConceptItem[]>([]);
  const [shortLine, setShortLine] = useState<ShortLineIndex[]>([]);
  const [thsHot, setThsHot] = useState<ThsHotItem[]>([]);
  const [errors, setErrors] = useState<DashboardErrors>({});
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    const [overviewResult, hotResult, shortResult, thsHotResult] = await Promise.allSettled([
        getMarketOverview(),
        getHotConcepts(30),
        getShortLineIndices(),
        getThsHot(8),
    ]);
    const nextErrors: DashboardErrors = {};
    if (overviewResult.status === 'fulfilled') setOverview(overviewResult.value);
    else { setOverview(null); nextErrors.overview = '大盘快照'; }
    if (hotResult.status === 'fulfilled') setHotConcepts(hotResult.value);
    else { setHotConcepts([]); nextErrors.hotConcepts = '热门板块'; }
    if (shortResult.status === 'fulfilled') setShortLine(shortResult.value);
    else { setShortLine([]); nextErrors.shortLine = '短线指标'; }
    if (thsHotResult.status === 'fulfilled') setThsHot(thsHotResult.value);
    else { setThsHot([]); nextErrors.thsHot = '热榜'; }
    setErrors(nextErrors);
    setLoading(false);
  };

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="min-h-full bg-crypto-bg p-4 sm:p-6">
      <section className="min-h-[720px]">
        <RealtimeMarketModule
          overview={overview}
          hotConcepts={hotConcepts}
          shortLine={shortLine}
          thsHot={thsHot}
          errors={errors}
          loading={loading}
          onViewAll={() => navigate('/market')}
        />
      </section>
    </div>
  );
}

export default Dashboard;
