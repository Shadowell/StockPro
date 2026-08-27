import { useCallback, useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import {
  Activity,
  AlertTriangle,
  Bell,
  CircleDot,
  Database,
  Layers3,
  LayoutDashboard,
  TrendingUp,
  WifiOff,
  Zap,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import {
  marketApi,
  parseApiError,
  type MarketHomeDashboard,
  type SectorRpsPayload,
  type SymbolAbnormality,
} from '../api/client';
import HomeMarketOverview from '../components/HomeMarketOverview';
import { useStore } from '../stores/useStore';

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

function eventSourceLabel(source?: string | null): string {
  return {
    strategy: '策略',
    signal: '个股信号',
    price: '价格',
    abnormal: '异动',
    sector: '板块',
  }[String(source || '')] || '事件';
}

function eventSeverityLabel(severity?: string | null): string {
  return { info: '提示', warning: '警告', critical: '严重' }[String(severity || '')] || '提示';
}

function formatEventTime(value?: string | null): string {
  if (!value) return '时间未知';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function abnormalWindowText(row: SymbolAbnormality, key: '3d' | '10d' | '30d'): string {
  const window = row.windows?.[key];
  if (!window || window.closeness == null) return '—';
  const value = window.valuePct == null ? '—' : formatPercent(window.valuePct, 1);
  const threshold = window.thresholdPct == null ? '—' : `${window.thresholdPct.toFixed(0)}%`;
  return `${value} / ${threshold} · ${(window.closeness * 100).toFixed(0)}%`;
}

function SectorRpsCard({
  title,
  payload,
  nameMap,
  onSelectSymbol,
  onSelectSector,
}: {
  title: string;
  payload: SectorRpsPayload;
  nameMap: Map<string, string>;
  onSelectSymbol: (symbol: string) => void;
  onSelectSector: (classificationSystem: 'industry' | 'concept', sectorCode: string) => void;
}) {
  const rows = payload.items || [];
  const ranked = rows.filter((row) => row.rank != null);
  const displayRows = [
    ...ranked.slice(0, 5).map((row) => ({ row, direction: '领涨' })),
    ...ranked.slice(-5).reverse().map((row) => ({ row, direction: '领跌' })),
  ];
  return (
    <div className="rounded-lg border border-crypto-border/70 bg-slate-950/35">
      <div className="flex items-center justify-between border-b border-crypto-border/60 px-3 py-2.5">
        <div className="flex items-center gap-2">
          <Layers3 className="h-4 w-4 text-cyan-300" />
          <span className="text-xs font-semibold text-gray-200">{title}</span>
        </div>
        <span className="text-[10px] text-gray-500">{statusLabel(payload.dataStatus)} · 领涨/领跌各 5</span>
      </div>
      <div className="divide-y divide-crypto-border/45">
        {displayRows.length ? displayRows.map(({ row, direction }) => (
          <div key={`${direction}-${row.classificationSystem}-${row.sectorCode}`} className="px-3 py-2.5 text-xs">
            <div className="grid grid-cols-[minmax(0,1fr)_58px_50px] items-center gap-2">
              <button
                type="button"
                onClick={() => onSelectSector(row.classificationSystem, row.sectorCode)}
                className="truncate text-left font-medium text-gray-200 hover:text-white"
              >
                <span className={clsx('mr-1 text-[10px]', direction === '领涨' ? 'text-up' : 'text-down')}>{direction}</span>
                {row.sectorName || row.sectorCode}
              </button>
              <span className="text-right font-mono tabular-nums text-blue-200">{formatRatio(row.rpsPercentile)}</span>
              <span className={clsx('text-right font-mono tabular-nums', (row.rankChange || 0) >= 0 ? 'text-up' : 'text-down')}>
                {row.rankChange == null ? '—' : `${row.rankChange >= 0 ? '+' : ''}${row.rankChange}`}
              </span>
            </div>
            <div className="mt-1 grid grid-cols-2 gap-2 text-[10px] text-gray-500 sm:grid-cols-4">
              <span>20日 {formatPercent(row.return20d, 1)}</span>
              <span>成员 {row.memberCount ?? '—'} 只</span>
              <span>覆盖 {row.memberCoverage == null ? '—' : `${(row.memberCoverage * 100).toFixed(0)}%`}</span>
              <span>连续强势 {row.strongDays ?? '—'} 日</span>
            </div>
            <div className="mt-1 flex min-w-0 items-center justify-between gap-2 text-[10px] text-gray-600">
              {row.leaderSymbol ? (
                <button type="button" onClick={() => onSelectSymbol(row.leaderSymbol || '')} className="min-w-0 truncate text-left hover:text-gray-300">
                  龙头 {displaySymbol(row.leaderSymbol, nameMap)} · 贡献 {row.leaderContributionPct == null ? '—' : `${row.leaderContributionPct.toFixed(1)}%`}
                </button>
              ) : <span>龙头证据 —</span>}
              <span className="shrink-0">{row.tradeDate || '—'} · #{row.sourceSnapshotId ?? '—'}</span>
            </div>
          </div>
        )) : (
          <div className="flex min-h-40 items-center justify-center px-4 text-center text-xs leading-5 text-gray-500">
            {payload.unavailableReason || `${title}暂无可用结果`}
          </div>
        )}
      </div>
    </div>
  );
}

function MarketIntelligencePanel({
  dashboard,
  onSelectSymbol,
  onSelectSector,
  onOpenMonitor,
}: {
  dashboard: MarketHomeDashboard;
  onSelectSymbol: (symbol: string) => void;
  onSelectSector: (classificationSystem: 'industry' | 'concept', sectorCode: string) => void;
  onOpenMonitor: () => void;
}) {
  const nameMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const mover of dashboard.movers.items || []) {
      if (mover.symbol && mover.name) map.set(mover.symbol, mover.name);
    }
    for (const event of dashboard.events.events || []) {
      if (event.symbol && event.name) map.set(event.symbol, event.name);
    }
    return map;
  }, [dashboard.events.events, dashboard.movers.items]);

  const phase = dashboard.phase;
  const sentiment = dashboard.sentiment;
  const movers = dashboard.movers.items || [];
  const events = dashboard.events.events || [];
  const phaseNotes = phase?.reasons?.length ? phase.reasons : phase?.missingInputs || [];

  return (
    <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border/70 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <Activity className="h-4 w-4 text-blue-300" />
          <div>
            <h2 className="text-sm font-semibold text-white">情绪 · 主线 · 异动</h2>
            <p className="mt-0.5 text-[11px] text-gray-500">
              与上方市场基础层共用一次只读 Dashboard 请求，不触发上游或重算。
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {(dashboard.evidence.consistencyWarnings || []).length ? (
            <span className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/25 bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-300">
              <WifiOff className="h-3.5 w-3.5" />
              {dashboard.evidence.consistencyWarnings?.[0]}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/20 bg-emerald-500/[0.07] px-2.5 py-1 text-[11px] text-emerald-300">
              <Database className="h-3.5 w-3.5" />
              Provider 调用 {dashboard.providerCalls} · 只读
            </span>
          )}
        </div>
      </div>

      <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
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
            {' · '}快照 <span className="font-mono text-gray-300">{phase?.sourceSnapshotId ?? '—'}</span>
          </div>
          <div className="mt-3 min-h-10 rounded-md border border-crypto-border/50 bg-black/15 px-2.5 py-2 text-xs leading-5 text-gray-400">
            {phaseNotes.length ? phaseNotes.slice(0, 3).join(' · ') : '暂无阶段解释或缺失项。'}
          </div>
        </div>

        <div className="rounded-lg border border-crypto-border/70 bg-slate-950/35 p-3">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-rose-300" />
              <span className="text-xs font-semibold text-gray-200">涨跌停情绪</span>
            </div>
            <span className={clsx(
              'rounded-md border px-2 py-0.5 text-[10px]',
              sentiment.status === 'ok'
                ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
                : 'border-amber-500/25 bg-amber-500/10 text-amber-300',
            )}>
              {statusLabel(sentiment.status)}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {[
              ['涨停', sentiment.limitUpCount],
              ['跌停', sentiment.limitDownCount],
              ['炸板', sentiment.failedLimitCount],
              ['封板率', sentiment.sealRatePct == null ? null : `${sentiment.sealRatePct.toFixed(1)}%`],
              ['一字板', sentiment.oneWordLimitCount],
              ['最高板', sentiment.highestStreak == null ? null : `${sentiment.highestStreak} 板`],
            ].map(([label, value]) => (
              <div key={String(label)} className="rounded-md border border-crypto-border/50 bg-black/15 px-2 py-2">
                <div className="text-[10px] text-gray-500">{label}</div>
                <div className="mt-1 font-mono text-sm font-semibold tabular-nums text-gray-100">
                  {sentiment.status === 'ok' && value != null ? value : '—'}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 space-y-1.5">
            {(sentiment.ladder || []).slice(0, 3).map((level) => (
              <button
                key={level.height}
                type="button"
                onClick={() => level.leaderSymbol && onSelectSymbol(level.leaderSymbol)}
                disabled={!level.leaderSymbol}
                className="grid w-full grid-cols-[50px_44px_minmax(0,1fr)] gap-2 rounded-md border border-crypto-border/45 px-2 py-1.5 text-left text-[11px] disabled:cursor-default"
              >
                <span className="font-mono text-rose-300">{level.height} 板</span>
                <span className="text-gray-500">{level.count} 家</span>
                <span className="truncate text-gray-300">{level.leaderSymbol ? displaySymbol(level.leaderSymbol, nameMap) : '—'}</span>
              </button>
            ))}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-[10px] text-gray-500 sm:grid-cols-4">
            <span>高度 <strong className="font-mono text-gray-300">{sentiment.highestStreak ?? '—'}</strong></span>
            <span>二板宽度 <strong className="font-mono text-gray-300">{sentiment.ladderWidth ?? '—'}</strong></span>
            <span>晋级率 <strong className="font-mono text-gray-300">{sentiment.promotionRatePct == null ? '—' : `${sentiment.promotionRatePct.toFixed(1)}%`}</strong></span>
            <span>完整度 <strong className="font-mono text-gray-300">{sentiment.ladderCompletenessPct == null ? '—' : `${sentiment.ladderCompletenessPct.toFixed(1)}%`}</strong></span>
          </div>
          {sentiment.weakMarketVeto ? (
            <div className="mt-2 rounded-md border border-rose-500/25 bg-rose-500/[0.07] px-2 py-1.5 text-[11px] text-rose-300">弱市否决生效：阶段不得解释为主升或高潮</div>
          ) : null}
          <div className="mt-2 text-[10px] text-gray-600">
            {sentiment.tradeDate || '—'} · 快照 {sentiment.sourceSnapshotId ?? '—'} · 覆盖 {sentiment.priceLimitCoverage == null ? '—' : `${(sentiment.priceLimitCoverage * 100).toFixed(1)}%`}
          </div>
          {sentiment.status !== 'ok' ? (
            <div className="mt-2 text-[11px] leading-4 text-amber-300/80">{sentiment.missingInputs.join(' · ') || '涨跌停证据不足'}</div>
          ) : null}
        </div>

        <SectorRpsCard title="行业主线 RPS" payload={dashboard.industryRps} nameMap={nameMap} onSelectSymbol={onSelectSymbol} onSelectSector={onSelectSector} />
        <SectorRpsCard title="概念主线 RPS" payload={dashboard.conceptRps} nameMap={nameMap} onSelectSymbol={onSelectSymbol} onSelectSector={onSelectSector} />

        <div className="rounded-lg border border-crypto-border/70 bg-slate-950/35">
          <div className="flex items-center justify-between border-b border-crypto-border/60 px-3 py-2.5">
            <div className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-amber-300" />
              <span className="text-xs font-semibold text-gray-200">异动边缘</span>
            </div>
            <span className="text-[10px] text-gray-500">偏离 / 阈值 / 接近度</span>
          </div>
          <div className="divide-y divide-crypto-border/45">
            {movers.length ? (
              movers.slice(0, 5).map((row) => (
                <button
                  key={row.symbol}
                  type="button"
                  onClick={() => onSelectSymbol(row.symbol)}
                  className="grid w-full grid-cols-[minmax(0,1fr)_82px_82px] items-center gap-2 px-3 py-2.5 text-left text-xs transition hover:bg-white/[0.03]"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-gray-200">
                      {displaySymbol(row.symbol, nameMap)}
                      <span className="ml-1 text-[10px] text-slate-500">
                        {row.board || '板块未知'}{row.st ? ' · ST' : ''}
                      </span>
                    </span>
                    <span className="mt-0.5 block truncate text-[11px] text-gray-500">
                      {row.abnormalStatus === 'triggered' ? '已触发' : row.abnormalStatus === 'edge' ? '接近' : '观察'}
                      {' · '}{(row.tags || []).join(' · ') || statusLabel(row.status)}
                    </span>
                  </span>
                  <span className="text-right text-[10px] tabular-nums text-gray-300">
                    3日 {abnormalWindowText(row, '3d')}
                  </span>
                  <span className="text-right text-[10px] tabular-nums text-gray-300">
                    10日 {abnormalWindowText(row, '10d')}
                  </span>
                </button>
              ))
            ) : (
              <div className="flex h-40 items-center justify-center gap-2 text-xs text-gray-500">
                <AlertTriangle className="h-3.5 w-3.5" />
                暂无完整 3/10/30 日异动指标
              </div>
            )}
          </div>
        </div>
      </div>

      <div className={clsx('grid items-start gap-3 px-4 pb-4', movers.length && 'xl:grid-cols-[1.12fr_1fr]')}>
        {movers.length ? <div className="min-w-0 rounded-lg border border-crypto-border/70 bg-slate-950/35">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-crypto-border/60 px-3 py-2.5">
            <div className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-amber-300" />
              <span className="text-xs font-semibold text-gray-200">异动边缘明细</span>
            </div>
            <span className="text-[10px] text-gray-500">窗口：偏离 / 阈值 / 接近度</span>
          </div>
          <div className="overflow-x-auto">
            <div className="min-w-[620px] divide-y divide-crypto-border/45">
              {movers.slice(0, 10).map((row) => (
                <button
                  key={`detail-${row.symbol}`}
                  type="button"
                  onClick={() => onSelectSymbol(row.symbol)}
                  className="grid w-full grid-cols-[minmax(170px,1.2fr)_repeat(3,minmax(120px,1fr))_72px] items-center gap-2 px-3 py-2 text-left text-[11px] transition hover:bg-white/[0.03]"
                >
                  <span className="min-w-0 truncate font-medium text-gray-200">{displaySymbol(row.symbol, nameMap)}</span>
                  <span className="text-right tabular-nums text-gray-300">3日 {abnormalWindowText(row, '3d')}</span>
                  <span className="text-right tabular-nums text-gray-300">10日 {abnormalWindowText(row, '10d')}</span>
                  <span className="text-right tabular-nums text-gray-300">30日 {abnormalWindowText(row, '30d')}</span>
                  <span className={clsx(
                    'text-right font-medium',
                    row.abnormalStatus === 'triggered' ? 'text-red-300' : row.abnormalStatus === 'edge' ? 'text-amber-300' : 'text-gray-400',
                  )}>
                    {row.abnormalStatus === 'triggered' ? '已触发' : row.abnormalStatus === 'edge' ? '接近' : '观察'}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div> : null}

        <div className="min-w-0 rounded-lg border border-crypto-border/70 bg-slate-950/35">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-crypto-border/60 px-3 py-2.5">
            <div className="flex items-center gap-2">
              <Bell className="h-4 w-4 text-blue-300" />
              <span className="text-xs font-semibold text-gray-200">告警事件流</span>
            </div>
            <button
              type="button"
              onClick={onOpenMonitor}
              className="rounded-md border border-crypto-border bg-gray-900/70 px-2 py-1 text-[10px] text-gray-400 transition hover:text-white"
            >
              监控中心
            </button>
          </div>
          <div className="divide-y divide-crypto-border/45">
            {events.length ? events.slice(0, 10).map((event) => (
              <div key={event.eventId} className="grid grid-cols-[86px_minmax(0,1fr)_54px] gap-2 px-3 py-2.5 text-[11px]">
                <span className="tabular-nums text-gray-500">{formatEventTime(event.triggeredAt)}</span>
                <span className="min-w-0">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="rounded border border-blue-500/20 bg-blue-500/[0.07] px-1.5 py-0.5 text-[10px] text-blue-200">
                      {eventSourceLabel(event.source)}
                    </span>
                    <span className={clsx(
                      'rounded border px-1.5 py-0.5 text-[10px]',
                      event.severity === 'critical' ? 'border-red-500/25 bg-red-500/10 text-red-300' : event.severity === 'warning' ? 'border-amber-500/25 bg-amber-500/10 text-amber-300' : 'border-slate-600/45 bg-slate-900/70 text-slate-400',
                    )}>
                      {eventSeverityLabel(event.severity)}
                    </span>
                    {event.symbol ? (
                      <button type="button" onClick={() => onSelectSymbol(event.symbol || '')} className="min-w-0 truncate font-medium text-gray-200 hover:text-white">
                        {displaySymbol(event.symbol, nameMap)}
                      </button>
                    ) : null}
                  </span>
                  <span className="mt-1 block truncate text-gray-400" title={event.message}>{event.message}</span>
                  <span className="mt-0.5 block truncate text-[10px] text-gray-600">
                    {event.price == null ? '' : `价格 ¥${event.price.toFixed(2)} · `}
                    {event.changePercent == null ? '' : `涨跌 ${formatPercent(event.changePercent, 1)} · `}
                    规则 {event.ruleId || '—'} · orders_created=0
                  </span>
                </span>
                <span className="text-right text-[10px] text-gray-500">{eventSeverityLabel(event.severity)}</span>
              </div>
            )) : (
              <div className="flex h-32 items-center justify-center px-4 text-center text-xs text-gray-500">
                暂无已持久化的策略、信号、价格、异动或板块告警。
              </div>
            )}
          </div>
          <div className="border-t border-crypto-border/50 px-3 py-2 text-[10px] text-gray-600">
            只读事件流 · 可按来源/严重度追溯 · 不下单、不改变 Paper
          </div>
        </div>
      </div>
    </section>
  );
}

export default function Home() {
  const navigate = useNavigate();
  const [dashboard, setDashboard] = useState<MarketHomeDashboard | null>(null);
  const [dashboardLoading, setDashboardLoading] = useState(true);
  const [dashboardError, setDashboardError] = useState<string | null>(null);
  const [dashboardRefreshing, setDashboardRefreshing] = useState(false);

  const loadDashboard = useCallback(async (refresh = false) => {
    if (refresh) setDashboardRefreshing(true);
    else setDashboardLoading(true);
    setDashboardError(null);
    try {
      setDashboard(await marketApi.getDashboard());
    } catch (error) {
      setDashboardError(parseApiError(error, '市场驾驶舱暂时不可用'));
    } finally {
      if (refresh) setDashboardRefreshing(false);
      else setDashboardLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard]);

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
              {dashboard?.evidence.dataMode || 'POSTGRESQL MARKET DATA'}
            </span>
            <span className="rounded-md border border-slate-600/45 bg-slate-900/70 px-3 py-1.5 font-medium text-slate-300">
              {dashboard?.evidence.tradeDate || 'CN A-SHARE'}
            </span>
            <span className="rounded-md border border-slate-600/45 bg-slate-900/70 px-3 py-1.5 font-medium text-slate-400">
              {statusLabel(dashboard?.dataStatus)}
            </span>
          </div>
        </div>
        <p className="mt-3 max-w-3xl border-l-2 border-blue-500/40 pl-3 text-xs leading-5 text-gray-500">
          聚合 PostgreSQL A 股行情的市场广度、成交活跃度和强弱排行；点击榜单标的后进入行情页查看日线详情。
        </p>
      </header>

      <div className="space-y-5 px-6 py-5 pb-7">
        <HomeMarketOverview
          data={dashboard ? {
            ...dashboard.overview,
            status: dashboard.evidence.status,
            dataStatus: dashboard.evidence.dataStatus,
            evidence: { ...dashboard.overview.evidence, ...dashboard.evidence },
          } : null}
          loading={dashboardLoading}
          error={dashboardError}
          refreshing={dashboardRefreshing}
          onRefresh={() => void loadDashboard(true)}
          onSelectSymbol={handleSelectSymbol}
        />
        {dashboard ? (
          <MarketIntelligencePanel
            dashboard={dashboard}
            onSelectSymbol={handleSelectSymbol}
            onSelectSector={(classificationSystem, sectorCode) => navigate(`/market?classification=${classificationSystem}&sector=${encodeURIComponent(sectorCode)}`)}
            onOpenMonitor={() => navigate('/monitor')}
          />
        ) : null}
      </div>
    </div>
  );
}
