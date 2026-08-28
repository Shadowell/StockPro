import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { Boxes, X } from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';
import { marketApi, type SectorHeatmapPayload, type SectorHeatmapSector } from '../api/client';
import { useSettingsStore } from '../stores/useSettingsStore';

const WINDOW_OPTIONS = [
  { value: '1d', label: '当日' },
  { value: '5d', label: '5日' },
  { value: '20d', label: '20日' },
] as const;

type HeatmapWindow = (typeof WINDOW_OPTIONS)[number]['value'];

const BOARD_BADGE: Record<string, string> = {
  '主板': 'border-slate-500/25 bg-slate-500/[0.08] text-slate-300',
  '创业板': 'border-amber-500/25 bg-amber-500/[0.08] text-amber-300',
  '科创板': 'border-cyan-500/25 bg-cyan-500/[0.08] text-cyan-300',
  '北交所': 'border-violet-500/25 bg-violet-500/[0.08] text-violet-300',
};

function formatSignedPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function formatPrice(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value)) || Number(value) <= 0) return '—';
  return `¥${Number(value).toFixed(2)}`;
}

function formatAmountCny(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value)) || Number(value) <= 0) return '—';
  const abs = Math.abs(Number(value));
  if (abs >= 1e12) return `${(value / 1e12).toFixed(2)}万亿`;
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(value / 1e4).toFixed(1)}万`;
  return value.toFixed(0);
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

interface AshareSectorHeatmapProps {
  onSelectSymbol?: (symbol: string) => void;
}

export default function AshareSectorHeatmap({ onSelectSymbol }: AshareSectorHeatmapProps) {
  const [heatmapWindow, setHeatmapWindow] = useState<HeatmapWindow>('1d');
  const [payload, setPayload] = useState<SectorHeatmapPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSectorCode, setSelectedSectorCode] = useState<string | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);
  const prefersReducedMotion = useReducedMotion();
  const { upColor, downColor } = useSettingsStore((state) => state.getColors());

  const fetchPayload = useCallback(async (target: HeatmapWindow) => {
    setLoading(true);
    setError(null);
    try {
      const data = await marketApi.getSectorHeatmap(target);
      setPayload(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '板块热力图读取失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPayload(heatmapWindow);
  }, [fetchPayload, heatmapWindow]);

  const sectors = useMemo(() => payload?.sectors || [], [payload]);
  const selectedSector = useMemo(
    () => sectors.find((sector) => sector.code === selectedSectorCode) || null,
    [sectors, selectedSectorCode],
  );
  const strongestSector = useMemo(
    () => [...sectors].sort((a, b) => b.averageChange - a.averageChange)[0],
    [sectors],
  );
  const weakestSector = useMemo(
    () => [...sectors].sort((a, b) => a.averageChange - b.averageChange)[0],
    [sectors],
  );
  const topMovingSectors = useMemo(
    () => [...sectors]
      .sort((a, b) => Math.abs(b.averageChange) - Math.abs(a.averageChange))
      .slice(0, 6),
    [sectors],
  );

  const option = useMemo<echarts.EChartsOption>(() => ({
    backgroundColor: 'transparent',
    animation: !prefersReducedMotion,
    animationDuration: 360,
    animationDurationUpdate: 480,
    animationEasing: 'cubicOut',
    animationThreshold: 300,
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: 'rgba(15, 23, 42, 0.98)',
      borderColor: '#334155',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: (params: any) => {
        const sector = params.data as SectorHeatmapSector;
        const leaders = (sector.members || []).slice(0, 8)
          .map((item) => `${escapeHtml(item.name)} ${formatSignedPercent(item.changePercent)}`)
          .join(' · ');
        return [
          `<strong>${escapeHtml(sector.name)}</strong>`,
          `${sector.count} 个标的 · 等权 ${formatSignedPercent(sector.averageChange)}`,
          `上涨 ${sector.gainers} · 下跌 ${sector.losers} · 平盘 ${sector.flat}`,
          leaders ? `<span style="color:#94a3b8">${leaders}</span>` : '',
        ].filter(Boolean).join('<br/>');
      },
    },
    series: [{
      id: 'ashare-sector-treemap',
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
          const sector = params.data as SectorHeatmapSector;
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
        id: sector.code,
        name: sector.name,
        value: sector.count,
        itemStyle: {
          color: mixHex('#1e293b', sector.averageChange >= 0 ? upColor : downColor,
            0.28 + Math.min(Math.abs(sector.averageChange) / 6, 1) * 0.62),
          borderColor: selectedSectorCode === sector.code ? '#67e8f9' : '#0f172a',
          borderWidth: selectedSectorCode === sector.code ? 4 : 3,
        },
      })),
    }],
  }), [downColor, prefersReducedMotion, sectors, selectedSectorCode, upColor]);

  useEffect(() => {
    if (!chartRef.current || sectors.length === 0) return undefined;
    const chart = echarts.init(chartRef.current);
    chartInstance.current = chart;
    const handleResize = () => chart.resize();
    const handleSectorClick = (params: any) => {
      const sector = params.data as SectorHeatmapSector | undefined;
      if (sector?.code) setSelectedSectorCode(sector.code);
    };
    window.addEventListener('resize', handleResize);
    chart.on('click', handleSectorClick);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.off('click', handleSectorClick);
      chart.dispose();
      chartInstance.current = null;
    };
  }, [sectors.length]);

  useEffect(() => {
    chartInstance.current?.setOption(option, { notMerge: false, lazyUpdate: true });
  }, [option]);

  const statusLabel = payload?.dataStatus === 'ok'
    ? 'ok'
    : (payload?.dataStatus || (loading ? 'loading' : 'empty'));

  return (
    <motion.section
      className="mb-4 overflow-hidden rounded-xl border border-cyan-500/15 bg-crypto-card shadow-[0_18px_48px_rgba(2,8,23,0.18)]"
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
            <span
              className={payload?.dataStatus === 'ok'
                ? 'rounded border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-300'
                : 'rounded border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-300'}
            >
              {statusLabel}
            </span>
          </div>
          <p className="mt-1 text-xs text-gray-500">面积 = 标的数 · 颜色 = 窗口等权涨跌 · 点击板块查看全部标的行情</p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <div className="flex overflow-hidden rounded-lg border border-crypto-border">
            {WINDOW_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setHeatmapWindow(option.value)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  heatmapWindow === option.value
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-500 hover:bg-gray-800/60 hover:text-gray-300'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="text-right text-[11px] leading-4 text-gray-500">
            <div>覆盖 {payload?.coveredSymbols ?? 0} / {payload?.totalSymbols ?? 0} 个标的</div>
            <div>交易日 {payload?.tradeDate || '—'}</div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_300px]">
        {loading ? (
          <div className="flex h-[420px] items-center justify-center text-sm text-gray-500">正在聚合板块行情…</div>
        ) : error ? (
          <div className="flex h-[420px] flex-col items-center justify-center gap-1 px-6 text-center text-sm text-amber-300">
            <span>{error}</span>
            <button
              type="button"
              onClick={() => fetchPayload(heatmapWindow)}
              className="rounded-md border border-crypto-border px-3 py-1 text-xs text-gray-400 hover:bg-white/[0.05] hover:text-gray-200"
            >
              重试
            </button>
          </div>
        ) : sectors.length === 0 ? (
          <div className="flex h-[420px] flex-col items-center justify-center gap-1 px-6 text-center text-sm text-gray-500">
            <span>{payload?.unavailableReason || '暂无可用板块行情'}</span>
            <span className="text-[11px] text-gray-600">需先在数据中心完成 A 股每日同步（行业 + 实时/日线）</span>
          </div>
        ) : (
          <div className="relative border-b border-crypto-border/60 bg-slate-950/15 xl:border-b-0 xl:border-r">
            <div
              ref={chartRef}
              className="h-[420px] w-full sm:h-[460px]"
              role="img"
              aria-label={`板块热度图，共 ${sectors.length} 个板块、${payload?.coveredSymbols ?? 0} 个标的`}
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
            <span className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[10px] text-slate-400">
              {WINDOW_OPTIONS.find((option) => option.value === heatmapWindow)?.label || heatmapWindow}
            </span>
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
                <div key={sector.code} className="rounded-md border border-white/[0.06] bg-white/[0.025] px-3 py-2">
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
            {!topMovingSectors.length && !loading ? (
              <div className="py-6 text-center text-xs text-gray-500">暂无板块动量数据</div>
            ) : null}
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
                  等权 {formatSignedPercent(selectedSector.averageChange)} · 上涨 {selectedSector.gainers} · 下跌 {selectedSector.losers} · 平盘 {selectedSector.flat}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setSelectedSectorCode(null)}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-white/10 bg-white/[0.03] text-slate-500 transition-colors hover:border-white/20 hover:bg-white/[0.06] hover:text-slate-200"
              aria-label="关闭板块行情"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="max-h-[360px] overflow-auto">
            <div className="min-w-[860px]">
              <div className="sticky top-0 z-10 grid grid-cols-[minmax(220px,1.5fr)_110px_110px_120px_110px_110px] items-center gap-x-3 border-b border-slate-500/25 bg-slate-900/95 px-4 py-2.5 text-[11px] font-semibold tracking-[0.04em] text-slate-300 backdrop-blur">
                <span>标的</span>
                <span>最新价</span>
                <span className="text-right">{heatmapWindow === '1d' ? '当日涨跌' : heatmapWindow === '5d' ? '5日涨跌' : '20日涨跌'}</span>
                <span className="text-right">成交额</span>
                <span className="text-right">最高</span>
                <span className="text-right">最低</span>
              </div>
              <div className="divide-y divide-crypto-border/40">
                {selectedSector.members.map((member) => (
                  <button
                    key={member.symbol}
                    type="button"
                    onClick={() => onSelectSymbol?.(member.symbol)}
                    className="grid w-full grid-cols-[minmax(220px,1.5fr)_110px_110px_120px_110px_110px] items-center gap-x-3 px-4 py-3 text-left transition-colors hover:bg-white/[0.035] focus-visible:bg-white/[0.05] focus-visible:outline-none"
                  >
                    <span className="flex min-w-0 items-center gap-3">
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold text-gray-100">{member.name}</span>
                        <span className="mt-0.5 block truncate text-[10px] text-slate-500" title={member.symbol}>{member.symbol}</span>
                      </span>
                      {member.board ? (
                        <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-medium ${BOARD_BADGE[member.board] || BOARD_BADGE['主板']}`}>
                          {member.board}
                        </span>
                      ) : null}
                    </span>
                    <span className="font-mono text-xs tabular-nums text-slate-200">{formatPrice(member.last)}</span>
                    <span className={`text-right font-mono text-xs font-semibold tabular-nums ${member.changePercent >= 0 ? 'text-up' : 'text-down'}`}>
                      {formatSignedPercent(member.changePercent)}
                    </span>
                    <span className="text-right font-mono text-xs tabular-nums text-slate-400">{formatAmountCny(member.amount)}</span>
                    <span className="text-right font-mono text-xs tabular-nums text-slate-400">{formatPrice(member.high)}</span>
                    <span className="text-right font-mono text-xs tabular-nums text-slate-400">{formatPrice(member.low)}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="border-t border-crypto-border/50 px-4 py-2 text-[10px] text-gray-600">
        行业主源 instrument_definitions.industry · 实时源 {payload?.realtimeSource || '日线回退'} · 只读聚合 · writes_performed=false
      </div>
    </motion.section>
  );
}
