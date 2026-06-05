import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Activity, BarChart3, Gauge, LineChart, Newspaper, RefreshCw, TrendingDown, TrendingUp, Zap } from 'lucide-react';
import clsx from 'clsx';
import { getHotConcepts, getMarketOverview, getShortLineIndices } from '../api/client';
import { NewsFeed } from '../components/NewsFeed';
import { MarketOverviewContent } from './MarketOverview';
import { SentimentAnalysisContent } from './SentimentAnalysis';
import type { HotConceptItem, MarketOverview } from '../types';

type ShortLineIndex = {
  code: string;
  name: string;
  price: number;
  change_percent: number;
  change_amount: number;
};

type DashboardModule = 'overview' | 'sentiment' | 'news';

const dashboardModules: Array<{
  id: DashboardModule;
  label: string;
  description: string;
  Icon: typeof LineChart;
}> = [
  { id: 'overview', label: '市场概览与分析', description: '热门概念、同花顺热榜、连板梯队', Icon: LineChart },
  { id: 'sentiment', label: '市场情绪分析', description: '情绪指数、涨跌统计、资金流向', Icon: Gauge },
  { id: 'news', label: '消息流', description: '异动、利好利空、财联社与雪球', Icon: Newspaper },
];

const normalizeModule = (value: string | null): DashboardModule => {
  if (value === 'sentiment' || value === 'news') return value;
  return 'overview';
};

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

export function Dashboard() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeModule = normalizeModule(searchParams.get('module'));
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [hotConcepts, setHotConcepts] = useState<HotConceptItem[]>([]);
  const [shortLine, setShortLine] = useState<ShortLineIndex[]>([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [overviewData, hotData, shortData] = await Promise.all([
        getMarketOverview(),
        getHotConcepts(8),
        getShortLineIndices(),
      ]);
      setOverview(overviewData);
      setHotConcepts(hotData);
      setShortLine(shortData);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
  }, []);

  const breadth = overview?.market_breadth;
  const upDownRatio = useMemo(() => {
    if (!breadth) return 0;
    return breadth.up / Math.max(breadth.down, 1);
  }, [breadth]);

  const openModule = (moduleId: DashboardModule) => {
    if (moduleId === 'overview') {
      setSearchParams({});
    } else {
      setSearchParams({ module: moduleId });
    }
  };

  return (
    <div className="min-h-full bg-crypto-bg p-6">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">大盘模块</h1>
          <p className="mt-1 text-sm text-gray-400">恢复市场概览、市场情绪和消息流三个看盘入口</p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 rounded border border-crypto-border bg-crypto-card px-4 py-2 text-sm text-gray-200 hover:border-blue-500"
        >
          <RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} />
          刷新
        </button>
      </div>

      <section className="mb-5 rounded-lg border border-crypto-border bg-crypto-card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-white">实时大盘</h2>
            <p className="mt-1 text-xs text-gray-500">A股指数、市场宽度、短线强度与热门板块</p>
          </div>
          <div className={clsx('flex items-center gap-2 text-sm font-semibold', overview?.is_open ? 'text-up' : 'text-gray-300')}>
            <Activity className="h-4 w-4" />
            {overview?.is_open ? '开市中' : '休市'}
          </div>
        </div>

        <div className="grid grid-cols-1 divide-y divide-crypto-border lg:grid-cols-4 lg:divide-x lg:divide-y-0">
          {(overview?.indices || []).map((index) => (
            <div key={index.name} className="p-4">
              <div className="mb-3 flex items-center justify-between text-sm text-gray-400">
                <span>{index.name}</span>
                {(index.change_percent || 0) >= 0 ? <TrendingUp className="h-4 w-4 text-up" /> : <TrendingDown className="h-4 w-4 text-down" />}
              </div>
              <div className="text-2xl font-semibold text-white">{formatNumber(index.price)}</div>
              <div className="mt-2 text-sm">
                <Pct value={index.change_percent} />
                <span className="ml-2 text-gray-500">{formatNumber(index.change_amount)}</span>
              </div>
            </div>
          ))}
          {(!overview?.indices || overview.indices.length === 0) && (
            <div className="p-4 text-sm text-gray-400 lg:col-span-4">
              暂无指数缓存，请在数据中心执行手动同步。
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 gap-4 border-t border-crypto-border p-5 lg:grid-cols-3">
          <div>
            <div className="mb-2 flex items-center gap-2 text-sm text-gray-300">
              <BarChart3 className="h-4 w-4 text-blue-400" />
              市场宽度
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <div className="text-xs text-gray-500">上涨</div>
                <div className="mt-1 text-lg font-semibold text-up">{breadth?.up ?? 0}</div>
              </div>
              <div>
                <div className="text-xs text-gray-500">下跌</div>
                <div className="mt-1 text-lg font-semibold text-down">{breadth?.down ?? 0}</div>
              </div>
              <div>
                <div className="text-xs text-gray-500">平盘</div>
                <div className="mt-1 text-lg font-semibold text-white">{breadth?.flat ?? 0}</div>
              </div>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded bg-gray-800">
              <div className="h-full bg-up" style={{ width: `${Math.min(upDownRatio * 40, 100)}%` }} />
            </div>
          </div>

          <div>
            <div className="mb-2 flex items-center gap-2 text-sm text-gray-300">
              <Zap className="h-4 w-4 text-yellow-400" />
              短线指标
            </div>
            <div className="grid grid-cols-2 gap-2">
              {shortLine.slice(0, 4).map((item) => (
                <div key={item.code} className="rounded border border-crypto-border bg-crypto-bg/50 px-3 py-2">
                  <div className="text-xs text-gray-500">{item.name}</div>
                  <div className="mt-1 text-base font-semibold text-white">{formatNumber(item.price, item.price > 99 ? 0 : 2)}</div>
                </div>
              ))}
              {shortLine.length === 0 && <div className="text-sm text-gray-500">暂无短线指标缓存</div>}
            </div>
          </div>

          <div>
            <div className="mb-2 flex items-center gap-2 text-sm text-gray-300">
              <TrendingUp className="h-4 w-4 text-red-400" />
              热门板块
            </div>
            <div className="space-y-2">
              {hotConcepts.slice(0, 3).map((item) => (
                <div key={item.name} className="flex items-center justify-between rounded border border-crypto-border bg-crypto-bg/50 px-3 py-2">
                  <div>
                    <div className="text-sm font-semibold text-white">{item.name}</div>
                    <div className="text-xs text-gray-500">净流入 {formatCompact(item.net_inflow)}</div>
                  </div>
                  <Pct value={item.change_percent} />
                </div>
              ))}
              {hotConcepts.length === 0 && <div className="text-sm text-gray-500">暂无板块缓存</div>}
            </div>
          </div>
        </div>
      </section>

      <div className="mb-5 flex flex-wrap gap-2">
        {dashboardModules.map((item) => (
          <button
            key={item.id}
            onClick={() => openModule(item.id)}
            className={clsx(
              'flex min-w-[180px] items-center gap-3 rounded-lg border px-4 py-3 text-left transition-colors',
              activeModule === item.id
                ? 'border-blue-500 bg-blue-600/15 text-blue-300'
                : 'border-crypto-border bg-crypto-card text-gray-400 hover:border-gray-600 hover:text-gray-100'
            )}
          >
            <item.Icon className="h-5 w-5 shrink-0" />
            <span>
              <span className="block text-sm font-semibold">{item.label}</span>
              <span className="mt-0.5 block text-xs text-gray-500">{item.description}</span>
            </span>
          </button>
        ))}
      </div>

      <section className="min-h-[720px]">
        {activeModule === 'overview' && (
          <div className="h-full">
            <h2 className="mb-4 text-xl font-bold text-white">市场概览与分析</h2>
            <MarketOverviewContent />
          </div>
        )}

        {activeModule === 'sentiment' && (
          <div className="h-full">
            <h2 className="mb-4 text-xl font-bold text-white">市场情绪分析</h2>
            <SentimentAnalysisContent />
          </div>
        )}

        {activeModule === 'news' && (
          <div className="flex min-h-[720px] flex-col">
            <h2 className="mb-4 text-xl font-bold text-white">消息流</h2>
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-slate-800 bg-[#111827]">
              <div className="border-b border-slate-800 bg-[#0d121f] px-6 py-4">
                <h3 className="text-sm font-black uppercase tracking-widest text-slate-100">7x24 实时快讯</h3>
              </div>
              <div className="min-h-0 flex-1 overflow-hidden">
                <NewsFeed />
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

export default Dashboard;
