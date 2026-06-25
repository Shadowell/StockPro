import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, Filter, Flame, Info, PieChart, TrendingUp, Zap } from 'lucide-react';
import clsx from 'clsx';
import { getHotConcepts, getMarketOverview, getShortLineIndices, getThsHot } from '../api/client';
import type { HotConceptItem, MarketOverview, ThsHotItem } from '../types';

type ShortLineIndex = {
  code: string;
  name: string;
  price: number;
  change_percent: number;
  change_amount: number;
};

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
  <span className={clsx((value || 0) >= 0 ? 'text-up' : 'text-down')}>
    {(value || 0) >= 0 ? '+' : ''}
    {formatNumber(value || 0, 2)}%
  </span>
);

function RealtimeMarketModule({
  overview,
  hotConcepts,
  shortLine,
  thsHot,
  onViewAll,
}: {
  overview: MarketOverview | null;
  hotConcepts: HotConceptItem[];
  shortLine: ShortLineIndex[];
  thsHot: ThsHotItem[];
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
  const topGainer = thsHot[0];
  const limitUp = shortLine.find((item) => item.name.includes('涨停')) || shortLine[0];
  const hotAboveFive = hotConcepts.filter((item) => item.change_percent >= 5).slice(0, 5);
  const visibleHotConcepts = hotAboveFive.length > 0 ? hotAboveFive : hotConcepts.slice(0, 5);
  const hotConceptTitle = hotAboveFive.length > 0 ? '热门板块 (>5%)' : '热门板块 TOP5';
  const hotConceptFilter = hotAboveFive.length > 0 ? '>=5%' : 'TOP5';
  const totalAmount = volume?.amount ?? 0;
  const amountUnit = volume?.unit || '亿';

  return (
    <div className="space-y-4">
      <section className="overflow-hidden rounded-lg border border-crypto-border bg-crypto-card">
        <div className="border-b border-crypto-border px-4 py-3">
          <h2 className="text-base font-black text-white">市场指数</h2>
        </div>

        <div className="grid grid-cols-1 gap-4 p-4 md:grid-cols-2 xl:grid-cols-4">
          {indices.map((index) => (
            <div key={index.name} className="min-h-[116px] rounded-lg border border-crypto-border bg-crypto-bg/45 p-4">
              <div className="text-sm font-bold text-gray-400">{index.name}</div>
              <div className="mt-4 text-2xl font-black leading-none text-white tabular-nums">{formatNumber(index.price)}</div>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-sm font-semibold tabular-nums">
                <Pct value={index.change_percent} />
                <span className={clsx((index.change_amount || 0) >= 0 ? 'text-up' : 'text-down')}>
                  {(index.change_amount || 0) >= 0 ? '+' : ''}
                  {formatNumber(index.change_amount)}
                </span>
              </div>
            </div>
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
              <div className="mt-3 text-sm font-semibold text-gray-600">--</div>
            )}
          </div>

          <div className="min-h-[156px] rounded-lg border border-crypto-border bg-crypto-bg/45 p-4">
            <div className="mb-4 flex items-center justify-between gap-2">
              <span className="text-sm font-bold text-gray-400">市场情绪</span>
              <Activity className="h-4 w-4 text-orange-400" />
            </div>
            <div className="text-2xl font-black text-white">{sentiment?.status || '中性'}</div>
            <div className="mt-3 text-sm font-bold text-orange-400">Index: {formatNumber(sentiment?.score ?? 50, 0)}</div>
            <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
              <div>
                <div className="text-gray-600">上涨</div>
                <div className="mt-1 font-bold text-up">{breadth?.up ?? sentiment?.advancing ?? 0}</div>
              </div>
              <div>
                <div className="text-gray-600">下跌</div>
                <div className="mt-1 font-bold text-down">{breadth?.down ?? sentiment?.declining ?? 0}</div>
              </div>
              <div>
                <div className="text-gray-600">平盘</div>
                <div className="mt-1 font-bold text-gray-300">{breadth?.flat ?? sentiment?.unchanged ?? 0}</div>
              </div>
            </div>
          </div>

          <div className="min-h-[156px] rounded-lg border border-crypto-border bg-crypto-bg/45 p-4">
            <div className="mb-4 flex items-center justify-between gap-2">
              <span className="text-sm font-bold text-gray-400">成交额</span>
              <PieChart className="h-4 w-4 text-blue-400" />
            </div>
            <div className="text-2xl font-black text-white tabular-nums">{formatNumber(totalAmount, 0)}{amountUnit}</div>
            <div className="mt-4 space-y-2 text-sm">
              {[
                ['沪', volume?.sh_amount, 'bg-blue-500'],
                ['深', volume?.sz_amount, 'bg-emerald-500'],
                ['北', volume?.bj_amount, 'bg-orange-500'],
              ].map(([label, value, color]) => (
                <div key={label as string} className="flex items-center gap-2">
                  <span className={clsx('h-2.5 w-2.5 rounded-full', color as string)} />
                  <span className="w-4 text-gray-400">{label}</span>
                  <span className="font-semibold text-blue-300 tabular-nums">{formatNumber(value as number | undefined, 0)}亿</span>
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
              {limitUp ? `${formatNumber(limitUp.price, 0)} ${limitUp.name.replace('家数', '')}` : '0 涨跌停'}
            </div>
            <div className="mt-3 text-sm font-semibold text-gray-600">异动监控</div>
          </div>
        </div>
      </section>

      <section className="overflow-hidden rounded-lg border border-crypto-border bg-crypto-card">
        <div className="flex items-center justify-between gap-3 border-b border-crypto-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-yellow-400" />
            <h2 className="text-base font-black text-white">短线指标</h2>
          </div>
          <span className="text-xs font-semibold text-gray-500">连板梯队 · 短线强度</span>
        </div>
        <div className="grid min-h-[132px] grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          {shortLine.length > 0 ? (
            shortLine.slice(0, 4).map((item) => (
              <div key={item.code} className="rounded-lg border border-crypto-border bg-crypto-bg/45 p-3">
                <div className="text-xs font-semibold text-gray-500">{item.name}</div>
                <div className="mt-3 text-xl font-black text-white tabular-nums">{formatNumber(item.price, item.price > 99 ? 0 : 2)}</div>
                <div className="mt-2 text-xs font-semibold">
                  <Pct value={item.change_percent} />
                </div>
              </div>
            ))
          ) : (
            <div className="flex items-center justify-center text-sm font-semibold text-gray-500 sm:col-span-2 lg:col-span-4">暂无数据</div>
          )}
        </div>
      </section>

      <section className="overflow-hidden rounded-lg border border-crypto-border bg-crypto-card">
        <div className="flex items-center justify-between gap-3 border-b border-crypto-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Flame className="h-4 w-4 text-orange-400" />
            <h2 className="text-base font-black text-white">热门板块</h2>
          </div>
          <button type="button" onClick={onViewAll} className="text-sm font-bold text-blue-400 transition-colors hover:text-blue-300">
            查看全部
          </button>
        </div>
        <div className="min-h-[168px] p-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-xl font-black text-white">{hotConceptTitle}</h3>
            <button type="button" className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border bg-slate-800 px-3 text-sm font-bold text-gray-300">
              <Filter className="h-4 w-4" />
              {hotConceptFilter}
            </button>
          </div>

          {visibleHotConcepts.length > 0 ? (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-5">
              {visibleHotConcepts.map((item) => (
                <div key={item.name} className="rounded-lg border border-crypto-border bg-crypto-bg/45 p-3">
                  <div className="text-sm font-bold text-white">{item.name}</div>
                  <div className="mt-3 text-lg font-black"><Pct value={item.change_percent} /></div>
                  <div className="mt-2 text-xs text-gray-500">净流入 {formatCompact(item.net_inflow)}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex min-h-[88px] items-center justify-center text-sm font-semibold text-gray-500">暂无热门板块数据</div>
          )}
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

  const load = async () => {
    try {
      const [overviewData, hotData, shortData, thsHotData] = await Promise.all([
        getMarketOverview(),
        getHotConcepts(8),
        getShortLineIndices(),
        getThsHot(8),
      ]);
      setOverview(overviewData);
      setHotConcepts(hotData);
      setShortLine(shortData);
      setThsHot(thsHotData);
    } catch {
      // Keep the dashboard shell usable when a market endpoint is temporarily unavailable.
    }
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
          onViewAll={() => navigate('/market')}
        />
      </section>
    </div>
  );
}

export default Dashboard;
