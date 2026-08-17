import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, LayoutDashboard, PieChart, Radar, TrendingUp, Zap } from 'lucide-react';
import clsx from 'clsx';
import { StatusBadge } from '@bitpro/ui';
import { getMarketOverview, getShortLineIndices, getThsHot } from '../api/client';
import { OperatorMetricCard, OperatorPageHeader, MetricValue } from '../components/OperatorShell';
import { MarketSessionBadge } from '../components/MarketSessionBadge';
import { SectorFundFlowPanel } from '../components/SectorFundFlowPanel';
import { LimitBoardPanel } from '../components/LimitBoardPanel';
import type { MarketOverview, MarketPulse, ThsHotItem } from '../types';
import { evaluateFreshness, formatFreshnessTime, latestTimestamp } from '../utils/dataFreshness';
import { marketMetricColor, marketToneClass, type MetricTone } from '../utils/marketColors';

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

type DashboardModule = 'overview' | 'shortLine' | 'thsHot';
type DashboardErrors = Partial<Record<DashboardModule, string>>;

const CACHE_FRESHNESS_MS = 36 * 60 * 60 * 1000;

const MARKET_INDEX_ORDER = ['上证指数', '深证成指', '创业板指', '科创50'];

const formatNumber = (value?: number | null, digits = 2) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits });
};

const Pct = ({ value }: { value?: number | null }) => (
  <span className={marketToneClass(value, 'text-gray-500')}>
    {value === null || value === undefined ? '' : value >= 0 ? '+' : ''}
    {value === null || value === undefined ? '--' : formatNumber(value, 2)}{value === null || value === undefined ? '' : '%'}
  </span>
);

const metricText = (value?: number | null, digits = 0) => (
  value === null || value === undefined || Number.isNaN(value) ? '--' : formatNumber(value, digits)
);

const shortLineUnit = (unit?: string | null) => {
  if (unit === 'stocks') return '';
  if (unit === 'boards') return '板';
  if (unit === 'percent') return '%';
  if (unit === 'ratio') return '';
  return '';
};

const shortLineTone = (code: string) => {
  if (['limit_up_count', 'rise_count', 'ZT', 'LIMIT_UP', 'red_ratio'].includes(code)) return 'border-up bg-up';
  if (['limit_down_count', 'fall_count', 'LIMIT_DOWN'].includes(code)) return 'border-down bg-down';
  if (['broken_board_count', 'highest_board'].includes(code)) return 'border-amber-500/30 bg-amber-500/[0.045]';
  if (code === 'seal_rate') return 'border-blue-500/25 bg-blue-500/[0.035]';
  return 'border-blue-500/25 bg-blue-500/[0.035]';
};

/** Value color must follow metric semantics — never blanket-amber. */
const shortLineValueTone = (code: string, value?: number | null): MetricTone => {
  if (['limit_up_count', 'rise_count', 'ZT', 'LIMIT_UP', 'red_ratio'].includes(code)) return 'up';
  if (['limit_down_count', 'fall_count', 'LIMIT_DOWN'].includes(code)) return 'down';
  if (code === 'broken_board_count' || code === 'broken_board') return 'amber';
  if (code === 'highest_board' || code === 'board_height') return 'amber';
  if (code === 'seal_rate') return 'blue';
  if (code === 'rise_fall_ratio') {
    if (value !== null && value !== undefined && Number.isFinite(Number(value))) {
      return Number(value) >= 1 ? 'up' : 'down';
    }
    return 'neutral';
  }
  if (code.includes('up') || code.includes('rise') || code.includes('red')) return 'up';
  if (code.includes('down') || code.includes('fall')) return 'down';
  return 'blue';
};

/** Breadth metrics live in 大盘诊断; keep short-line for limit ecology only. */
const SHORT_LINE_ECOLOGY = new Set([
  'limit_up_count',
  'limit_down_count',
  'broken_board_count',
  'highest_board',
  'seal_rate',
  'ZT',
  'LIMIT_UP',
  'LIMIT_DOWN',
]);

const shortLineGroup = (code: string) => {
  if (['limit_up_count', 'limit_down_count', 'broken_board_count', 'highest_board', 'ZT', 'LIMIT_UP', 'LIMIT_DOWN'].includes(code)) {
    return '涨停生态';
  }
  if (code === 'seal_rate') return '封板质量';
  return '短线强度';
};

const shortLineSource = (source?: string | null) => {
  if (source === 'tushare_limit_list_derived') return 'TuShare 涨跌停证据';
  if (source === 'tushare_daily') return 'TuShare 日线广度';
  if (source === 'akshare_zt_pool') return 'AkShare 涨停池';
  return source || '';
};

const pulseTone = (value?: number | null, invert = false): MetricTone => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'neutral';
  const positive = invert ? Number(value) < 0 : Number(value) > 0;
  const negative = invert ? Number(value) > 0 : Number(value) < 0;
  if (positive) return 'up';
  if (negative) return 'down';
  return 'neutral';
};

type PulseCard = {
  key: string;
  label: string;
  value: string;
  detail: string;
  tone: MetricTone;
};

const buildPulseCards = (pulse?: MarketPulse | null): PulseCard[] => {
  if (!pulse) return [];
  const ratio = pulse.rise_fall_ratio;
  const ratioTone: MetricTone =
    ratio === null || ratio === undefined ? 'neutral' : Number(ratio) >= 1 ? 'up' : 'down';
  return [
    {
      key: 'breadth',
      label: '涨跌家数',
      value: `${metricText(pulse.advancing)} / ${metricText(pulse.declining)}`,
      detail: `平盘 ${metricText(pulse.unchanged)} · 样本 ${metricText(pulse.universe_count)}`,
      tone: ratioTone,
    },
    {
      key: 'ratio',
      label: '涨跌比',
      value: ratio === null || ratio === undefined ? '--' : `${formatNumber(ratio, 2)}`,
      detail: '上涨家数 ÷ 下跌家数',
      tone: ratioTone,
    },
    {
      key: 'median',
      label: '中位涨跌幅',
      value: pulse.median_change_percent === null || pulse.median_change_percent === undefined
        ? '--'
        : `${pulse.median_change_percent >= 0 ? '+' : ''}${formatNumber(pulse.median_change_percent, 2)}%`,
      detail: `均值 ${pulse.avg_change_percent === null || pulse.avg_change_percent === undefined
        ? '--'
        : `${pulse.avg_change_percent >= 0 ? '+' : ''}${formatNumber(pulse.avg_change_percent, 2)}%`}`,
      tone: pulseTone(pulse.median_change_percent),
    },
    {
      key: 'strong',
      label: '强势带 (≥5% / ≥7%)',
      value: `${metricText(pulse.strong_up_5)} / ${metricText(pulse.strong_up_7)}`,
      detail: '短线攻击力 · 家数',
      tone: 'up',
    },
    {
      key: 'weak',
      label: '弱势带 (≤-5% / ≤-7%)',
      value: `${metricText(pulse.weak_down_5)} / ${metricText(pulse.weak_down_7)}`,
      detail: '抛压深度 · 家数',
      tone: 'down',
    },
    {
      key: 'limits',
      label: '涨停估 / 跌停估',
      value: `${metricText(pulse.limit_up_est)} / ${metricText(pulse.limit_down_est)}`,
      detail: '按板块阈值估算 · 非交易所确认',
      tone: (pulse.limit_up_est ?? 0) >= (pulse.limit_down_est ?? 0) ? 'up' : 'down',
    },
    {
      key: 'concentration',
      label: 'Top10 成交额占比',
      value: pulse.amount_top10_share === null || pulse.amount_top10_share === undefined
        ? '--'
        : `${formatNumber(pulse.amount_top10_share, 1)}%`,
      detail: '资金集中度越高越抱团',
      tone: 'amber',
    },
    {
      key: 'turnover',
      label: '平均换手 / 振幅',
      value: `${pulse.avg_turnover == null ? '--' : `${formatNumber(pulse.avg_turnover, 2)}%`} / ${pulse.avg_amplitude == null ? '--' : `${formatNumber(pulse.avg_amplitude, 2)}%`}`,
      detail: '全市场活跃度',
      tone: 'blue',
    },
    {
      key: 'volume_ratio',
      label: '平均量比',
      value: pulse.avg_volume_ratio == null ? '--' : formatNumber(pulse.avg_volume_ratio, 2),
      detail: `量比≥2 · ${metricText(pulse.volume_ratio_gt2)} 家`,
      tone: pulse.avg_volume_ratio != null && pulse.avg_volume_ratio >= 1 ? 'up' : 'blue',
    },
    {
      key: 'active',
      label: '有成交家数',
      value: metricText(pulse.active_traded),
      detail: `覆盖 ${metricText(pulse.universe_count)} 只实时样本`,
      tone: 'blue',
    },
  ];
};

function RealtimeMarketModule({
  overview,
  shortLine,
  thsHot,
  errors,
  loading,
  onViewAll,
}: {
  overview: MarketOverview | null;
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
  const pulse = overview?.market_pulse;
  const hasPulseData = Boolean(
    pulse &&
      (pulse.universe_count != null
        || pulse.rise_fall_ratio != null
        || pulse.median_change_percent != null
        || pulse.advancing != null),
  );
  const pulseCards = hasPulseData ? buildPulseCards(pulse) : [];
  const snapshotState = overview?.data_status?.stock_snapshot_state ?? (loading ? 'loading' : 'unavailable');
  const snapshotMessage = overview?.data_status?.message
    ?? (loading ? '正在读取缓存' : '全市场实时快照未同步');
  const thsHotFreshness = evaluateFreshness(latestTimestamp(thsHot), CACHE_FRESHNESS_MS);
  const shortLineFreshness = evaluateFreshness(latestTimestamp(shortLine), CACHE_FRESHNESS_MS);
  const shortLineSnapshot = shortLine.find((item) => item.data_state === 'sealed_snapshot');
  const shortLineTradeDate = shortLineSnapshot?.trade_date ?? null;
  const ecologyShortLine = shortLine.filter((item) => SHORT_LINE_ECOLOGY.has(item.code) || item.name.includes('涨停') || item.name.includes('跌停') || item.name.includes('炸板') || item.name.includes('连板') || item.name.includes('封板'));
  const displayShortLine = ecologyShortLine.length > 0 ? ecologyShortLine.slice(0, 8) : shortLine.filter((item) => !['rise_count', 'fall_count', 'rise_fall_ratio'].includes(item.code)).slice(0, 8);
  // 热榜缓存陈旧时不得把陈旧个股当作当前强势股信号展示。
  const topGainer = thsHotFreshness.state === 'fresh' ? thsHot[0] : undefined;
  const totalAmount = volume?.amount ?? null;
  const amountUnit = volume?.unit || '亿';
  const upCount = pulse?.advancing ?? breadth?.up ?? sentiment?.advancing ?? null;
  const downCount = pulse?.declining ?? breadth?.down ?? sentiment?.declining ?? null;
  const riseFallRatio = pulse?.rise_fall_ratio ?? null;
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
          {indices.map((index) => {
            const tone = marketMetricColor(index.change_percent);
            return (
            <OperatorMetricCard
              key={index.name}
              label={index.name}
              tone={tone === 'neutral' ? 'blue' : tone}
              value={formatNumber(index.price)}
              detail={<div className="flex flex-wrap items-center gap-2 text-xs font-semibold tabular-nums">
                <Pct value={index.change_percent} />
                <span className={marketToneClass(index.change_amount)}>
                  {(index.change_amount || 0) > 0 ? '+' : ''}
                  {formatNumber(index.change_amount)}
                </span>
              </div>}
            />
            );
          })}

          {indices.length === 0 && (
            <div className="rounded-lg border border-crypto-border bg-crypto-bg/45 p-4 text-sm text-gray-500 md:col-span-2 xl:col-span-4">
              {loading ? '正在读取指数缓存' : '暂无指数缓存'}
            </div>
          )}

          <div className="min-h-[156px] rounded-lg border border-crypto-border bg-crypto-bg/45 p-4">
            <div className="mb-4 flex items-center justify-between gap-2">
              <span className="text-sm font-bold text-gray-400">强势股</span>
              <TrendingUp className="h-4 w-4 text-up" />
            </div>
            <div className="text-2xl font-bold text-blue-300">{topGainer?.name || '--'}</div>
            {topGainer ? (
              <div className="mt-3 flex items-center gap-2 text-sm font-semibold">
                <span className="text-gray-500">{topGainer.code}</span>
                <Pct value={topGainer.change_percent} />
              </div>
            ) : (
              <div className="mt-3 text-sm font-semibold text-amber-300">
                {errors.thsHot ? '热榜加载失败' : loading ? '正在读取热榜' : thsHotFreshness.state === 'stale' ? '热榜缓存已陈旧' : '暂无当前热榜'}
              </div>
            )}
            <div className="mt-3 text-[10px] text-gray-600">{topGainer?.source_label || '来源未记录'} · {formatFreshnessTime(thsHotFreshness.timestamp)}</div>
          </div>

          <div className="min-h-[156px] rounded-lg border border-crypto-border bg-crypto-bg/45 p-4">
            <div className="mb-4 flex items-center justify-between gap-2">
              <span className="text-sm font-bold text-gray-400">市场情绪</span>
              <Activity className="h-4 w-4 text-amber-400" />
            </div>
            <div className="text-2xl font-bold text-amber-300">{sentiment?.status || (loading ? '读取中' : '未同步')}</div>
            <div className="mt-3 text-sm font-bold text-amber-300">情绪分 {metricText(sentiment?.score, 0)}</div>
            <div className="mt-4 text-xs text-gray-500">
              涨跌 {metricText(upCount)} / {metricText(downCount)}
              {riseFallRatio != null ? (
                <span className={clsx('ml-2 font-semibold', Number(riseFallRatio) >= 1 ? 'text-up' : 'text-down')}>
                  比 {formatNumber(riseFallRatio, 2)}
                </span>
              ) : null}
            </div>
            {snapshotState !== 'fresh' ? <div className="mt-3 text-[11px] font-semibold text-amber-300">{snapshotMessage}</div> : null}
          </div>

          <div className="min-h-[156px] rounded-lg border border-crypto-border bg-crypto-bg/45 p-4">
            <div className="mb-4 flex items-center justify-between gap-2">
              <span className="text-sm font-bold text-gray-400">成交额</span>
              <PieChart className="h-4 w-4 text-blue-400" />
            </div>
            <MetricValue tone="blue" size="xl">
              {totalAmount === null ? '--' : `${formatNumber(totalAmount, 0)}${amountUnit}`}
            </MetricValue>
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
              <span className="text-sm font-bold text-gray-400">资金集中度</span>
              <Radar className="h-4 w-4 text-amber-400" />
            </div>
            <MetricValue tone="amber" size="xl">
              {pulse?.amount_top10_share == null ? '--' : `${formatNumber(pulse.amount_top10_share, 1)}%`}
            </MetricValue>
            <div className="mt-3 text-sm text-gray-500">Top10 成交额占比</div>
            <div className="mt-2 text-xs text-gray-600">
              量比均值 {pulse?.avg_volume_ratio == null ? '--' : formatNumber(pulse.avg_volume_ratio, 2)}
              · 换手 {pulse?.avg_turnover == null ? '--' : `${formatNumber(pulse.avg_turnover, 2)}%`}
            </div>
          </div>
        </div>
      </section>

      <section className="overflow-hidden rounded-lg border border-crypto-border bg-crypto-card">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-crypto-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Radar className="h-4 w-4 text-blue-400" />
            <div>
              <h2 className="text-base font-black text-white">大盘诊断</h2>
              <p className="mt-1 text-xs text-gray-500">
                由全市场实时快照推算（AkShare/东财类字段缓存）· 用于判断广度、强弱带与资金抱团
              </p>
            </div>
          </div>
          <StatusBadge tone={snapshotState === 'fresh' ? 'green' : 'amber'}>
            {errors.overview ? '加载失败' : snapshotState === 'fresh' ? '实时样本可用' : snapshotMessage}
          </StatusBadge>
        </div>
        <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {pulseCards.length > 0 ? (
            pulseCards.map((card) => (
              <OperatorMetricCard
                key={card.key}
                label={card.label}
                value={card.value}
                tone={card.tone === 'neutral' ? 'blue' : card.tone}
                detail={<span className="text-[11px] text-gray-500">{card.detail}</span>}
                className="min-h-[112px]"
              />
            ))
          ) : (
            <div className="flex min-h-[88px] items-center justify-center text-sm font-semibold text-gray-500 sm:col-span-2 lg:col-span-3 xl:col-span-5">
              {loading ? '正在读取全市场快照' : '全市场实时快照未同步，暂无大盘诊断指标'}
            </div>
          )}
        </div>
      </section>

      <section className="overflow-hidden rounded-lg border border-crypto-border bg-crypto-card">
        <div className="flex items-center justify-between gap-3 border-b border-crypto-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-yellow-400" />
            <div>
              <h2 className="text-base font-black text-white">涨停生态</h2>
              <p className="mt-1 text-xs text-gray-500">
                TuShare/AkShare 涨跌停计数 + 封存名单；点开个股看近 30 日 K 与当日分时
              </p>
            </div>
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
          {displayShortLine.length > 0 ? (
            displayShortLine.map((item, index) => (
              <div key={item.code} className={clsx('rounded-lg border p-3', shortLineTone(item.code), index < 4 && 'min-h-[118px]')}>
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs font-semibold text-gray-400">{item.name}</div>
                  {index < 4 ? <span className="text-[9px] font-semibold tracking-wide text-gray-600">{shortLineGroup(item.code)}</span> : null}
                </div>
                <MetricValue tone={shortLineValueTone(item.code, item.price)} size={index < 4 ? 'xl' : 'lg'} className="mt-3 block">
                  {formatNumber(item.price, ['percent', 'ratio'].includes(item.unit || '') ? 2 : 0)}
                  <span className="ml-1 text-xs font-semibold text-gray-500">{shortLineUnit(item.unit)}</span>
                </MetricValue>
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
        <LimitBoardPanel />
      </section>

      <SectorFundFlowPanel onViewAll={onViewAll} />
    </div>
  );
}

export function Dashboard() {
  const navigate = useNavigate();
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [shortLine, setShortLine] = useState<ShortLineIndex[]>([]);
  const [thsHot, setThsHot] = useState<ThsHotItem[]>([]);
  const [errors, setErrors] = useState<DashboardErrors>({});
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    const [overviewResult, shortResult, thsHotResult] = await Promise.allSettled([
        getMarketOverview(),
        getShortLineIndices(),
        getThsHot(8),
    ]);
    const nextErrors: DashboardErrors = {};
    if (overviewResult.status === 'fulfilled') setOverview(overviewResult.value);
    else { setOverview(null); nextErrors.overview = '大盘快照'; }
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

  const evidenceDate = shortLine.find((item) => item.data_state === 'sealed_snapshot')?.trade_date
    ?? shortLine.find((item) => item.trade_date)?.trade_date
    ?? null;
  const cacheDate = overview?.data_status?.stock_snapshot_updated_at
    ? String(overview.data_status.stock_snapshot_updated_at).slice(0, 10)
    : null;

  return (
    <div className="min-h-full bg-crypto-bg p-4 sm:p-6" data-operator-page="dashboard">
      <OperatorPageHeader
        icon={LayoutDashboard}
        title="市场大盘"
        subtitle="指数、广度、涨停生态与板块资金。首页读缓存，不是盘中推送。"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {evidenceDate ? (
              <StatusBadge tone="green">证据日 {evidenceDate}</StatusBadge>
            ) : null}
            {cacheDate ? (
              <StatusBadge tone={overview?.data_status?.stock_snapshot_state === 'fresh' ? 'green' : 'amber'}>
                行情缓存 {cacheDate}
              </StatusBadge>
            ) : (
              <StatusBadge tone="amber">行情缓存未同步</StatusBadge>
            )}
            <MarketSessionBadge prominent overview={overview} />
          </div>
        }
      />
      <section className="min-h-[720px]">
        <RealtimeMarketModule
          overview={overview}
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
