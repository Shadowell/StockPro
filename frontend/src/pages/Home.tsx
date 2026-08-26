import { useCallback, useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import {
  Activity,
  AlertTriangle,
  CircleDot,
  Database,
  Layers3,
  LayoutDashboard,
  RefreshCw,
  TrendingUp,
  WifiOff,
  Zap,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import {
  marketApi,
  type MarketInstrument,
  type MarketPhase,
  type SectorRpsRow,
  type SymbolAbnormality,
} from '../api/client';
import MarketUniversePanel from '../components/MarketUniversePanel';
import NativeDataPanel from '../components/NativeDataPanel';
import { useStore } from '../stores/useStore';

const HOME_INTEL_LIMIT = 8;
const A_SHARE_EXCHANGES = ['SSE', 'SZSE', 'BSE'] as const;

type HomeMarketIntel = {
  phase: MarketPhase | null;
  sectors: SectorRpsRow[];
  movers: SymbolAbnormality[];
  instruments: MarketInstrument[];
};

function formatPercent(value?: number | null, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

function formatRatio(value?: number | null, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return value.toFixed(digits);
}

function statusLabel(status?: string | null): string {
  if (!status) return 'empty';
  if (status === 'ok') return '可用';
  if (status === 'partial') return '部分可用';
  if (status === 'blocked') return '阻塞';
  return status;
}

function displaySymbol(symbol: string, nameMap: Map<string, string>): string {
  const name = nameMap.get(symbol);
  if (!name || name === symbol) return symbol;
  return `${name}（${symbol}）`;
}

function MarketIntelSkeleton() {
  return (
    <section className="rounded-xl border border-crypto-border bg-crypto-card">
      <div className="flex h-40 items-center justify-center gap-2 text-xs text-gray-500">
        <RefreshCw className="h-3.5 w-3.5 animate-spin" />
        正在加载市场指标...
      </div>
    </section>
  );
}

function MarketIntelligencePanel({
  selectedExchange,
  onSelectSymbol,
}: {
  selectedExchange: string;
  onSelectSymbol: (symbol: string) => void;
}) {
  const [data, setData] = useState<HomeMarketIntel | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [lastRefreshAt, setLastRefreshAt] = useState<Date | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    const exchangeScope = Array.from(new Set([selectedExchange, ...A_SHARE_EXCHANGES]));
    const [phase, sectors, movers, ...symbolPages] = await Promise.allSettled([
      marketApi.getPhase(),
      marketApi.getSectorRps('industry', undefined, HOME_INTEL_LIMIT),
      marketApi.getMovers(undefined, HOME_INTEL_LIMIT),
      ...exchangeScope.map((exchange) => marketApi.getSymbols(exchange, 'CNY', 'stock')),
    ]);

    const instruments = symbolPages.flatMap((page) => {
      if (page.status !== 'fulfilled') return [];
      return page.value.instruments || [];
    });

    const nextData: HomeMarketIntel = {
      phase: phase.status === 'fulfilled' ? phase.value : null,
      sectors: sectors.status === 'fulfilled' ? sectors.value : [],
      movers: movers.status === 'fulfilled' ? movers.value : [],
      instruments,
    };

    setData(nextData);
    setFailed([phase, sectors, movers].every((result) => result.status === 'rejected'));
    setLastRefreshAt(new Date());
    setLoading(false);
  }, [selectedExchange]);

  useEffect(() => {
    void load();
  }, [load]);

  const nameMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const instrument of data?.instruments || []) {
      const name = instrument.name || instrument.displayName || instrument.symbol;
      if (instrument.symbol) map.set(instrument.symbol, name);
    }
    return map;
  }, [data?.instruments]);

  if (loading && !data) return <MarketIntelSkeleton />;

  const phase = data?.phase;
  const sectors = data?.sectors || [];
  const movers = data?.movers || [];
  const phaseNotes = phase?.reasons?.length ? phase.reasons : phase?.missingInputs || [];

  return (
    <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border/70 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <Activity className="h-4 w-4 text-blue-300" />
          <div>
            <h2 className="text-sm font-semibold text-white">市场指标看板</h2>
            <p className="mt-0.5 text-[11px] text-gray-500">
              接入市场阶段、行业 RPS、异动标的；全部来自后端真实研究指标。
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {failed ? (
            <span className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/25 bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-300">
              <WifiOff className="h-3.5 w-3.5" />
              指标接口不可用
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/20 bg-emerald-500/[0.07] px-2.5 py-1 text-[11px] text-emerald-300">
              <Database className="h-3.5 w-3.5" />
              {lastRefreshAt ? lastRefreshAt.toLocaleTimeString('zh-CN', { hour12: false }) : '—'}
            </span>
          )}
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-crypto-border bg-gray-800 px-2.5 text-xs text-gray-400 transition hover:bg-gray-700 hover:text-white"
          >
            <RefreshCw className={clsx('h-3.5 w-3.5', loading && 'animate-spin')} />
            刷新
          </button>
        </div>
      </div>

      <div className="grid gap-3 p-4 xl:grid-cols-[1.12fr_1fr_1.08fr]">
        <div className="rounded-lg border border-crypto-border/70 bg-slate-950/35 p-3">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-blue-300" />
              <span className="text-xs font-semibold text-gray-200">市场阶段</span>
            </div>
            <span
              className={clsx(
                'rounded-md border px-2 py-0.5 text-[10px]',
                phase?.status === 'ok'
                  ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
                  : phase?.status === 'partial'
                    ? 'border-amber-500/25 bg-amber-500/10 text-amber-300'
                    : 'border-slate-600/45 bg-slate-900/70 text-slate-400'
              )}
            >
              {statusLabel(phase?.status)}
            </span>
          </div>
          <div className="flex items-end gap-3">
            <div className="text-2xl font-semibold tracking-tight text-white">{phase?.phase || 'unknown'}</div>
            <div className="pb-1 text-xs tabular-nums text-gray-500">
              置信度 {phase ? `${Math.round((phase.confidence || 0) * 100)}%` : '—'}
            </div>
          </div>
          <div className="mt-2 text-xs text-gray-500">
            交易日 <span className="font-mono text-gray-300">{phase?.tradeDate || '—'}</span>
          </div>
          <div className="mt-3 min-h-10 rounded-md border border-crypto-border/50 bg-black/15 px-2.5 py-2 text-xs leading-5 text-gray-400">
            {phaseNotes.length ? phaseNotes.slice(0, 3).join(' · ') : '暂无阶段解释或缺失项。'}
          </div>
        </div>

        <div className="rounded-lg border border-crypto-border/70 bg-slate-950/35">
          <div className="flex items-center justify-between border-b border-crypto-border/60 px-3 py-2.5">
            <div className="flex items-center gap-2">
              <Layers3 className="h-4 w-4 text-cyan-300" />
              <span className="text-xs font-semibold text-gray-200">行业强弱 RPS</span>
            </div>
            <span className="text-[10px] text-gray-500">Top {Math.min(sectors.length, 5) || '—'}</span>
          </div>
          <div className="divide-y divide-crypto-border/45">
            {sectors.length ? (
              sectors.slice(0, 5).map((row) => (
                <div key={`${row.classificationSystem}-${row.sectorCode}`} className="grid grid-cols-[minmax(0,1fr)_58px_54px] items-center gap-2 px-3 py-2.5 text-xs">
                  <span className="truncate font-medium text-gray-200">{row.sectorName || row.sectorCode}</span>
                  <span className="text-right tabular-nums text-blue-200">{formatRatio(row.rpsPercentile)}</span>
                  <span
                    className={clsx(
                      'text-right tabular-nums',
                      (row.rankChange || 0) >= 0 ? 'text-up' : 'text-down'
                    )}
                  >
                    {row.rankChange == null ? '—' : `${row.rankChange >= 0 ? '+' : ''}${row.rankChange}`}
                  </span>
                  {row.leaderSymbol ? (
                    <span className="col-span-3 truncate text-[11px] text-gray-500">
                      龙头 {displaySymbol(row.leaderSymbol, nameMap)}
                    </span>
                  ) : null}
                </div>
              ))
            ) : (
              <div className="flex h-40 items-center justify-center text-xs text-gray-500">
                暂无行业 RPS 结果
              </div>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-crypto-border/70 bg-slate-950/35">
          <div className="flex items-center justify-between border-b border-crypto-border/60 px-3 py-2.5">
            <div className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-amber-300" />
              <span className="text-xs font-semibold text-gray-200">异动标的</span>
            </div>
            <span className="text-[10px] text-gray-500">中文名（代码）</span>
          </div>
          <div className="divide-y divide-crypto-border/45">
            {movers.length ? (
              movers.slice(0, 5).map((row) => (
                <button
                  key={row.symbol}
                  type="button"
                  onClick={() => onSelectSymbol(row.symbol)}
                  className="grid w-full grid-cols-[minmax(0,1fr)_64px_64px] items-center gap-2 px-3 py-2.5 text-left text-xs transition hover:bg-white/[0.03]"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-gray-200">
                      {displaySymbol(row.symbol, nameMap)}
                    </span>
                    <span className="mt-0.5 block truncate text-[11px] text-gray-500">
                      {(row.tags || []).join(' · ') || statusLabel(row.status)}
                    </span>
                  </span>
                  <span className={clsx('text-right tabular-nums', (row.return3d || 0) >= 0 ? 'text-up' : 'text-down')}>
                    {formatPercent(row.return3d)}
                  </span>
                  <span className={clsx('text-right tabular-nums', (row.return10d || 0) >= 0 ? 'text-up' : 'text-down')}>
                    {formatPercent(row.return10d)}
                  </span>
                </button>
              ))
            ) : (
              <div className="flex h-40 items-center justify-center gap-2 text-xs text-gray-500">
                <AlertTriangle className="h-3.5 w-3.5" />
                暂无异动指标
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

export default function Home() {
  const { selectedExchange } = useStore();
  const navigate = useNavigate();

  const handleSelectSymbol = (symbol: string) => {
    useStore.getState().setSelectedSymbol(symbol);
    navigate('/market');
  };

  return (
    <div className="h-full overflow-y-auto bg-crypto-bg">
      <header className="border-b border-crypto-border/70 bg-slate-950/35 px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-blue-500/25 bg-blue-500/10 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
              <LayoutDashboard className="h-5 w-5 text-blue-300" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-300/80">
                <Activity className="h-3 w-3" />
                Market Command
              </div>
              <h1 className="mt-0.5 text-xl font-bold text-white">市场大盘</h1>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-[11px]">
            <span className="flex items-center gap-2 rounded-md border border-emerald-500/20 bg-emerald-500/[0.07] px-3 py-1.5 font-medium text-emerald-300">
              <CircleDot className="h-3.5 w-3.5" />
              POSTGRESQL MARKET DATA
            </span>
            <span className="rounded-md border border-slate-600/45 bg-slate-900/70 px-3 py-1.5 font-medium text-slate-300">
              CN A-SHARE
            </span>
            <span className="rounded-md border border-slate-600/45 bg-slate-900/70 px-3 py-1.5 font-medium text-slate-400">
              DAILY MARKET PULSE
            </span>
          </div>
        </div>
        <p className="mt-3 max-w-3xl border-l-2 border-blue-500/40 pl-3 text-xs leading-5 text-gray-500">
          聚合 PostgreSQL A 股行情的市场广度、成交活跃度和强弱排行；点击榜单标的后进入行情页查看日线详情。
        </p>
      </header>

      <div className="space-y-5 px-6 py-5 pb-7">
        <MarketIntelligencePanel
          selectedExchange={selectedExchange}
          onSelectSymbol={handleSelectSymbol}
        />
        <MarketUniversePanel
          variant="summary"
          selectedExchange={selectedExchange}
          onSelectSymbol={handleSelectSymbol}
        />
        <NativeDataPanel />
      </div>
    </div>
  );
}
