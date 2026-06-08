import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Activity, BarChart3, Bell, Code2, DatabaseZap, FlaskConical, Gauge, LineChart, Newspaper, Radio, RefreshCw, ShieldCheck, TrendingDown, TrendingUp, Zap } from 'lucide-react';
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

const quantPipeline = [
  { id: 'data', label: '行情数据层', metric: 'PG + TuShare', description: 'K线、实时快照、数据新鲜度', Icon: DatabaseZap },
  { id: 'research', label: '研究因子层', metric: 'Alpha Lab', description: '情绪、事件、因子、AI选股', Icon: BarChart3 },
  { id: 'strategy', label: '策略研发层', metric: 'Code + Rules', description: '策略开发、参数、版本管理', Icon: Code2 },
  { id: 'backtest', label: '回测评估层', metric: 'Risk/Return', description: '收益、回撤、交易归因', Icon: FlaskConical },
  { id: 'runtime', label: '模拟执行层', metric: 'Paper Runtime', description: '账户、委托、执行回放', Icon: Radio },
  { id: 'risk', label: '风控监控层', metric: 'Monitor', description: '告警、运行状态、异常处理', Icon: Bell },
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
    <div className="min-h-full bg-crypto-bg p-4 sm:p-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-black text-white">量化交易中枢</h1>
            <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-emerald-300">
              <ShieldCheck className="h-3 w-3" />
              Quant Stack
            </span>
          </div>
          <p className="mt-1 text-xs font-medium text-gray-500">数据采集 → 研究因子 → 策略研发 → 回测评估 → 模拟执行 → 风险监控</p>
        </div>
        <button
          onClick={load}
          className="inline-flex h-9 items-center gap-2 rounded-md border border-crypto-border bg-crypto-card px-3 text-sm font-semibold text-gray-200 transition-colors hover:border-blue-500/60 hover:bg-gray-800/70"
        >
          <RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} />
          刷新
        </button>
      </div>

      <section className="mb-4 rounded-lg border border-crypto-border bg-crypto-card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border bg-crypto-bg/35 px-4 py-3">
          <div>
            <h2 className="text-sm font-black uppercase tracking-widest text-white">量化交易模块链路</h2>
            <p className="mt-1 text-xs text-gray-500">从数据到执行的闭环结构，页面模块按交易生产线组织</p>
          </div>
          <span className="rounded-md border border-blue-500/20 bg-blue-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-blue-200">
            Research To Runtime
          </span>
        </div>
        <div className="grid grid-cols-1 divide-y divide-crypto-border sm:grid-cols-2 sm:divide-x sm:divide-y-0 xl:grid-cols-6">
          {quantPipeline.map(({ id, label, metric, description, Icon }) => (
            <div key={id} className="min-h-[116px] p-3">
              <div className="mb-3 flex items-center justify-between gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-md border border-blue-500/20 bg-blue-500/10">
                  <Icon className="h-4 w-4 text-blue-300" />
                </div>
                <span className="truncate text-[10px] font-semibold uppercase tracking-wider text-gray-500">{metric}</span>
              </div>
              <div className="text-sm font-bold text-gray-100">{label}</div>
              <div className="mt-1 min-h-[32px] text-xs leading-4 text-gray-500">{description}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="mb-4 overflow-hidden rounded-lg border border-crypto-border bg-crypto-card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border bg-crypto-bg/35 px-4 py-3">
          <div>
            <h2 className="text-sm font-black uppercase tracking-widest text-white">实时大盘</h2>
            <p className="mt-1 text-xs text-gray-500">作为量化交易前置状态面板，缓存优先展示，外部源不可用时保持页面可读</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className={clsx('inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-semibold', overview?.is_open ? 'border-crypto-border bg-up text-up' : 'border-crypto-border bg-crypto-card text-gray-300')}>
              <Activity className="h-3.5 w-3.5" />
              {overview?.is_open ? '开市中' : '休市'}
            </div>
            <div className="inline-flex items-center gap-1.5 rounded-md border border-blue-500/20 bg-blue-500/10 px-2.5 py-1.5 text-xs font-semibold text-blue-200">
              <DatabaseZap className="h-3.5 w-3.5" />
              TuShare 优先
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 divide-y divide-crypto-border lg:grid-cols-4 lg:divide-x lg:divide-y-0">
          {(overview?.indices || []).map((index) => (
            <div key={index.name} className="p-4">
              <div className="mb-3 flex items-center justify-between text-xs font-semibold text-gray-500">
                <span>{index.name}</span>
                {(index.change_percent || 0) >= 0 ? <TrendingUp className="h-4 w-4 text-up" /> : <TrendingDown className="h-4 w-4 text-down" />}
              </div>
              <div className="text-xl font-semibold text-white">{formatNumber(index.price)}</div>
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

        <div className="grid grid-cols-1 gap-4 border-t border-crypto-border p-4 lg:grid-cols-3">
          <div>
            <div className="mb-2 flex items-center gap-2 text-sm text-gray-300">
              <BarChart3 className="h-4 w-4 text-blue-400" />
              市场宽度因子
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
              短线强度因子
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
              主线板块因子
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

      <div className="mb-4 flex flex-wrap gap-1 rounded-lg border border-crypto-border bg-crypto-card p-1">
        {dashboardModules.map((item) => (
          <button
            key={item.id}
            onClick={() => openModule(item.id)}
            className={clsx(
              'flex min-w-[180px] flex-1 items-center gap-2 rounded-md border px-3 py-2 text-left transition-colors',
              activeModule === item.id
                ? 'border-blue-500/35 bg-blue-500/15 text-blue-200'
                : 'border-transparent text-gray-400 hover:border-crypto-border hover:bg-gray-800/70 hover:text-gray-100'
            )}
          >
            <item.Icon className="h-4 w-4 shrink-0" />
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
            <h2 className="mb-3 text-base font-bold text-white">市场概览与分析</h2>
            <MarketOverviewContent />
          </div>
        )}

        {activeModule === 'sentiment' && (
          <div className="h-full">
            <h2 className="mb-3 text-base font-bold text-white">市场情绪分析</h2>
            <SentimentAnalysisContent />
          </div>
        )}

        {activeModule === 'news' && (
          <div className="flex min-h-[720px] flex-col">
            <h2 className="mb-3 text-base font-bold text-white">消息流</h2>
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
