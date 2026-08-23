import { useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { Boxes, X } from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';
import { useSettingsStore } from '../stores/useSettingsStore';
import SymbolIcon from './SymbolIcon';

export interface MarketSectorTicker {
  symbol: string;
  coin: string;
  last: number;
  change_percent: number;
  high: number;
  low: number;
  quote_volume: number;
  sector_key: string;
  sector_name: string;
  taxonomy_version: string;
}

interface SectorAggregate {
  key: string;
  name: string;
  count: number;
  averageChange: number;
  gainers: number;
  losers: number;
  flat: number;
  members: MarketSectorTicker[];
}

interface MarketSectorHeatmapProps {
  tickers: MarketSectorTicker[];
  loading?: boolean;
  onSelectSymbol?: (symbol: string) => void;
}

function formatSignedPercent(value: number): string {
  if (!Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function formatMarketPrice(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '—';
  if (value >= 10_000) return `$${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
  if (value >= 100) return `$${value.toFixed(2)}`;
  if (value >= 1) return `$${value.toFixed(4)}`;
  if (value >= 0.01) return `$${value.toFixed(5)}`;
  return `$${value.toFixed(6)}`;
}

function formatQuoteVolume(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '—';
  if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  if (value >= 1e3) return `$${(value / 1e3).toFixed(0)}K`;
  return `$${value.toFixed(0)}`;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function mixHex(base: string, tone: string, amount: number): string {
  const parse = (value: string) => {
    const normalized = value.replace('#', '');
    return [0, 2, 4].map((index) => Number.parseInt(normalized.slice(index, index + 2), 16));
  };
  const [baseR, baseG, baseB] = parse(base);
  const [toneR, toneG, toneB] = parse(tone);
  const weight = Math.max(0, Math.min(1, amount));
  const channel = (start: number, end: number) => Math.round(start + (end - start) * weight)
    .toString(16)
    .padStart(2, '0');
  return `#${channel(baseR, toneR)}${channel(baseG, toneG)}${channel(baseB, toneB)}`;
}

function aggregateSectors(tickers: MarketSectorTicker[]): SectorAggregate[] {
  const groups = new Map<string, { name: string; members: MarketSectorTicker[] }>();

  tickers.forEach((ticker) => {
    const key = ticker.sector_key || 'other';
    const current = groups.get(key) || { name: ticker.sector_name || '其他', members: [] };
    current.members.push(ticker);
    groups.set(key, current);
  });

  return Array.from(groups.entries())
    .map(([key, group]) => {
      const finiteMembers = group.members.filter((item) => Number.isFinite(item.change_percent));
      const averageChange = finiteMembers.length
        ? finiteMembers.reduce((sum, item) => sum + item.change_percent, 0) / finiteMembers.length
        : 0;
      return {
        key,
        name: group.name,
        count: group.members.length,
        averageChange,
        gainers: finiteMembers.filter((item) => item.change_percent > 0).length,
        losers: finiteMembers.filter((item) => item.change_percent < 0).length,
        flat: group.members.length
          - finiteMembers.filter((item) => item.change_percent > 0).length
          - finiteMembers.filter((item) => item.change_percent < 0).length,
        members: [...group.members].sort((a, b) => b.change_percent - a.change_percent),
      };
    })
    .sort((a, b) => b.count - a.count || b.averageChange - a.averageChange);
}

export default function MarketSectorHeatmap({
  tickers,
  loading = false,
  onSelectSymbol,
}: MarketSectorHeatmapProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);
  const [selectedSectorKey, setSelectedSectorKey] = useState<string | null>(null);
  const prefersReducedMotion = useReducedMotion();
  const { upColor, downColor } = useSettingsStore((state) => state.getColors());
  const sectors = useMemo(() => aggregateSectors(tickers), [tickers]);
  const hasSectors = sectors.length > 0;
  const taxonomyVersion = tickers.find((ticker) => ticker.taxonomy_version)?.taxonomy_version || '—';
  const topMovingSectors = useMemo(
    () => [...sectors]
      .sort((a, b) => Math.abs(b.averageChange) - Math.abs(a.averageChange))
      .slice(0, 6),
    [sectors],
  );
  const strongestSector = useMemo(
    () => [...sectors].sort((a, b) => b.averageChange - a.averageChange)[0],
    [sectors],
  );
  const weakestSector = useMemo(
    () => [...sectors].sort((a, b) => a.averageChange - b.averageChange)[0],
    [sectors],
  );
  const selectedSector = useMemo(
    () => sectors.find((sector) => sector.key === selectedSectorKey) || null,
    [sectors, selectedSectorKey],
  );

  const option = useMemo<echarts.EChartsOption>(() => ({
    backgroundColor: 'transparent',
    animation: !prefersReducedMotion,
    animationDuration: 360,
    animationDurationUpdate: 480,
    animationEasing: 'cubicOut',
    animationEasingUpdate: 'cubicOut',
    animationThreshold: 300,
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: 'rgba(15, 23, 42, 0.98)',
      borderColor: '#334155',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: (params: any) => {
        const sector = params.data as SectorAggregate;
        const leaders = sector.members.slice(0, 8)
          .map((item) => `${escapeHtml(item.coin)} ${formatSignedPercent(item.change_percent)}`)
          .join(' · ');
        return [
          `<strong>${escapeHtml(sector.name)}</strong>`,
          `${sector.count} 个标的 · 整体 ${formatSignedPercent(sector.averageChange)}`,
          `上涨 ${sector.gainers} · 下跌 ${sector.losers} · 平盘 ${sector.flat}`,
          leaders ? `<span style="color:#94a3b8">${leaders}</span>` : '',
        ].filter(Boolean).join('<br/>');
      },
    },
    series: [{
      id: 'home-sector-treemap',
      type: 'treemap',
      universalTransition: !prefersReducedMotion,
      roam: false,
      nodeClick: false,
      breadcrumb: { show: false },
      squareRatio: 1.15,
      visibleMin: 1,
      sort: 'desc',
      top: 0,
      right: 0,
      bottom: 0,
      left: 0,
      label: {
        show: true,
        color: '#f8fafc',
        fontSize: 12,
        fontWeight: 600,
        lineHeight: 18,
        overflow: 'truncate',
        formatter: (params: any) => {
          const sector = params.data as SectorAggregate;
          return `${sector.name}\n${sector.count} 个标的\n${formatSignedPercent(sector.averageChange)}`;
        },
      },
      upperLabel: { show: false },
      itemStyle: {
        borderColor: '#0f172a',
        borderWidth: 3,
        gapWidth: 2,
      },
      emphasis: {
        focus: 'self',
        itemStyle: {
          borderColor: '#94a3b8',
          borderWidth: 2,
          shadowBlur: 18,
          shadowColor: 'rgba(15, 23, 42, 0.72)',
        },
      },
      data: sectors.map((sector) => ({
        ...sector,
        id: sector.key,
        name: sector.name,
        value: sector.count,
        itemStyle: {
          color: mixHex('#1e293b', sector.averageChange >= 0 ? upColor : downColor,
            0.28 + Math.min(Math.abs(sector.averageChange) / 8, 1) * 0.62),
          borderColor: selectedSectorKey === sector.key ? '#67e8f9' : '#0f172a',
          borderWidth: selectedSectorKey === sector.key ? 4 : 3,
        },
      })),
    }],
  }), [downColor, prefersReducedMotion, sectors, selectedSectorKey, upColor]);

  useEffect(() => {
    if (!chartRef.current || !hasSectors) return undefined;
    const chart = echarts.init(chartRef.current);
    chartInstance.current = chart;
    const handleResize = () => chart.resize();
    const handleSectorClick = (params: any) => {
      const sector = params.data as SectorAggregate | undefined;
      if (sector?.key) setSelectedSectorKey(sector.key);
    };
    window.addEventListener('resize', handleResize);
    chart.on('click', handleSectorClick);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.off('click', handleSectorClick);
      chart.dispose();
      chartInstance.current = null;
    };
  }, [hasSectors]);

  useEffect(() => {
    chartInstance.current?.setOption(option, { notMerge: false, lazyUpdate: true });
  }, [option]);

  return (
    <motion.section
      className="mt-4 overflow-hidden rounded-xl border border-cyan-500/15 bg-crypto-card shadow-[0_18px_48px_rgba(2,8,23,0.18)]"
      initial={prefersReducedMotion ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: 'easeOut', delay: 0.04 }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-crypto-border bg-slate-950/30 px-4 py-3">
        <div>
          <div className="mb-1 text-[9px] font-semibold uppercase tracking-[0.2em] text-cyan-300/70">Market Map</div>
          <div className="flex items-center gap-2">
            <Boxes className="h-4 w-4 text-cyan-300" />
            <h2 className="text-sm font-semibold text-gray-100">板块热度图</h2>
            <span className="rounded border border-cyan-500/20 bg-cyan-500/[0.08] px-2 py-0.5 text-[11px] text-cyan-200">
              {sectors.length} 个板块
            </span>
          </div>
          <p className="mt-1 text-xs text-gray-500">面积 = 标的数 · 颜色 = 24h 等权涨跌 · 点击板块查看全部标的行情</p>
        </div>
        <div className="text-right text-[11px] leading-5 text-gray-500">
          <div>覆盖 {tickers.length} 个标的</div>
          <div>分类版本 {taxonomyVersion}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_300px]">
        {loading ? (
          <div className="flex h-[420px] items-center justify-center text-sm text-gray-500">正在聚合板块行情…</div>
        ) : sectors.length === 0 ? (
          <div className="flex h-[420px] items-center justify-center text-sm text-gray-500">暂无可用板块行情</div>
        ) : (
          <div className="relative border-b border-crypto-border/60 bg-slate-950/15 xl:border-b-0 xl:border-r">
            <div
              ref={chartRef}
              className="h-[420px] w-full sm:h-[460px]"
              role="img"
              aria-label={`板块热度图，共 ${sectors.length} 个板块、${tickers.length} 个标的`}
            />
            <div className="pointer-events-none absolute bottom-3 left-3 flex items-center gap-3 rounded-md border border-white/10 bg-slate-950/85 px-3 py-1.5 text-[10px] text-slate-400 backdrop-blur">
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ backgroundColor: upColor }} />上涨</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ backgroundColor: downColor }} />下跌</span>
              <span>面积代表标的数量</span>
            </div>
          </div>
        )}

        <aside className="bg-slate-950/25 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[9px] font-semibold uppercase tracking-[0.2em] text-slate-500">Sector Momentum</div>
              <h3 className="mt-1 text-sm font-semibold text-gray-100">板块动量</h3>
            </div>
            <span className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[10px] text-slate-400">24H</span>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-up/20 bg-up/[0.06] p-3">
              <div className="text-[10px] text-slate-500">领涨板块</div>
              <div className="mt-1 truncate text-sm font-semibold text-gray-100">{strongestSector?.name || '—'}</div>
              <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-up">
                {strongestSector ? formatSignedPercent(strongestSector.averageChange) : '—'}
              </div>
            </div>
            <div className="rounded-lg border border-down/20 bg-down/[0.06] p-3">
              <div className="text-[10px] text-slate-500">领跌板块</div>
              <div className="mt-1 truncate text-sm font-semibold text-gray-100">{weakestSector?.name || '—'}</div>
              <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-down">
                {weakestSector ? formatSignedPercent(weakestSector.averageChange) : '—'}
              </div>
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
            <span>强弱板块</span>
            <span>涨跌 / 标的数</span>
          </div>
          <div className="mt-2 space-y-1.5">
            {topMovingSectors.map((sector, index) => {
              const isUp = sector.averageChange >= 0;
              const width = Math.max(12, Math.min(100, Math.abs(sector.averageChange) * 10));
              return (
                <div key={sector.key} className="rounded-md border border-white/[0.06] bg-white/[0.025] px-3 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="font-mono text-[10px] text-slate-600">{String(index + 1).padStart(2, '0')}</span>
                      <span className="truncate text-xs font-medium text-slate-200">{sector.name}</span>
                    </div>
                    <div className="shrink-0 font-mono text-[11px] tabular-nums">
                      <span className={isUp ? 'text-up' : 'text-down'}>{formatSignedPercent(sector.averageChange)}</span>
                      <span className="ml-2 text-slate-600">{sector.count}</span>
                    </div>
                  </div>
                  <div className="mt-2 h-1 overflow-hidden rounded-full bg-slate-800">
                    <div
                      className={`h-full rounded-full ${prefersReducedMotion ? '' : 'transition-[width] duration-500 ease-out'}`}
                      style={{ width: `${width}%`, backgroundColor: isUp ? upColor : downColor }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </aside>
      </div>

      {selectedSector && (
        <div className="border-t border-cyan-500/15 bg-slate-950/30" role="region" aria-live="polite" aria-label={`${selectedSector.name}板块行情`}>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border/60 px-4 py-3">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-cyan-500/20 bg-cyan-500/[0.08]">
                <Boxes className="h-4 w-4 text-cyan-300" />
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="truncate text-sm font-semibold text-gray-100">{selectedSector.name} · 板块行情</h3>
                  <span className="rounded border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] text-slate-400">
                    全部 {selectedSector.count} 个标的
                  </span>
                </div>
                <p className="mt-0.5 text-[11px] text-slate-500">
                  整体 {formatSignedPercent(selectedSector.averageChange)} · 上涨 {selectedSector.gainers} · 下跌 {selectedSector.losers} · 平盘 {selectedSector.flat}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setSelectedSectorKey(null)}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-white/10 bg-white/[0.03] text-slate-500 transition-colors hover:border-white/20 hover:bg-white/[0.06] hover:text-slate-200"
              aria-label="关闭板块行情"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="max-h-[360px] overflow-auto">
            <div className="min-w-[820px]">
              <div className="sticky top-0 z-10 grid grid-cols-[minmax(210px,1.4fr)_120px_110px_130px_120px_120px] items-center gap-x-3 border-b border-slate-500/25 bg-slate-900/95 px-4 py-2.5 text-[11px] font-semibold tracking-[0.04em] text-slate-300 backdrop-blur">
                <span>标的</span>
                <span>最新价</span>
                <span>24h 涨跌</span>
                <span>24h 成交额</span>
                <span>24h 最高</span>
                <span>24h 最低</span>
              </div>
              <div className="divide-y divide-crypto-border/40">
                {selectedSector.members.map((member) => (
                  <button
                    key={member.symbol}
                    type="button"
                    onClick={() => onSelectSymbol?.(member.symbol)}
                    className="grid w-full grid-cols-[minmax(210px,1.4fr)_120px_110px_130px_120px_120px] items-center gap-x-3 px-4 py-3 text-left transition-colors hover:bg-white/[0.035] focus-visible:bg-white/[0.05] focus-visible:outline-none"
                  >
                    <span className="flex min-w-0 items-center gap-3">
                      <SymbolIcon symbol={member.symbol} base={member.coin} size="sm" />
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold text-gray-100">{member.coin}</span>
                        <span className="mt-0.5 block truncate text-[10px] text-slate-500" title={member.symbol}>{member.symbol}</span>
                      </span>
                      <span className="shrink-0 rounded border border-amber-500/20 bg-amber-500/[0.08] px-1.5 py-0.5 text-[9px] font-medium text-amber-300">SWAP</span>
                    </span>
                    <span className="font-mono text-xs tabular-nums text-slate-200">{formatMarketPrice(member.last)}</span>
                    <span className={`font-mono text-xs font-semibold tabular-nums ${member.change_percent >= 0 ? 'text-up' : 'text-down'}`}>
                      {formatSignedPercent(member.change_percent)}
                    </span>
                    <span className="font-mono text-xs tabular-nums text-slate-400">{formatQuoteVolume(member.quote_volume)}</span>
                    <span className="font-mono text-xs tabular-nums text-slate-400">{formatMarketPrice(member.high)}</span>
                    <span className="font-mono text-xs tabular-nums text-slate-400">{formatMarketPrice(member.low)}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </motion.section>
  );
}
