import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Database,
  RefreshCw,
} from 'lucide-react';
import {
  orderflowApi,
  type OrderflowBar,
  type OrderflowLargeTrade,
  type OrderflowStreamStatus,
} from '../api/client';
import { useSettingsStore } from '../stores/useSettingsStore';

const SYMBOL_OPTIONS = [
  '600519.SH',
  '000001.SZ',
  '300750.SZ',
  '510300.SH',
];

const RANGE_OPTIONS = [
  { label: '近 1 小时', hours: 1 },
  { label: '近 6 小时', hours: 6 },
  { label: '近 24 小时', hours: 24 },
  { label: '近 3 天', hours: 72 },
];

const THRESHOLD_OPTIONS = [
  { label: '≥ 5 万元', value: 50_000 },
  { label: '≥ 10 万元', value: 100_000 },
  { label: '≥ 50 万元', value: 500_000 },
  { label: '≥ 100 万元', value: 1_000_000 },
];

const BAR_OPTIONS = [
  { label: '1 分钟', minutes: 1 },
  { label: '5 分钟', minutes: 5 },
  { label: '15 分钟', minutes: 15 },
  { label: '1 小时', minutes: 60 },
];

function fmtUsdt(v: number | null | undefined): string {
  if (v == null) return '—';
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toFixed(0);
}

function fmtTime(ts: number): string {
  return new Date(ts).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export default function OrderFlow() {
  const { upColor, downColor } = useSettingsStore((s) => s.getColors());
  const [symbol, setSymbol] = useState(SYMBOL_OPTIONS[0]);
  const [hours, setHours] = useState(6);
  const [threshold, setThreshold] = useState(50_000);
  const [barMinutes, setBarMinutes] = useState(5);
  const [sideFilter, setSideFilter] = useState<'all' | 'buy' | 'sell'>('all');

  const [trades, setTrades] = useState<OrderflowLargeTrade[]>([]);
  const [bars, setBars] = useState<OrderflowBar[]>([]);
  const [streamStatus, setStreamStatus] = useState<OrderflowStreamStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const bubbleRef = useRef<HTMLDivElement>(null);
  const deltaRef = useRef<HTMLDivElement>(null);
  const bubbleChart = useRef<echarts.ECharts | null>(null);
  const deltaChart = useRef<echarts.ECharts | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [tradeRes, barRes, status] = await Promise.all([
        orderflowApi.getLargeTrades({
          instId: symbol,
          hours,
          minNotional: threshold,
          side: sideFilter === 'all' ? undefined : sideFilter,
          limit: 3000,
        }),
        orderflowApi.getBars({ instId: symbol, barMinutes, hours }),
        orderflowApi.getStreamStatus(),
      ]);
      setTrades(tradeRes.items ?? []);
      setBars(barRes.items ?? []);
      setStreamStatus(status);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [symbol, hours, threshold, barMinutes, sideFilter]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, [autoRefresh, load]);

  const kpi = useMemo(() => {
    let buy = 0;
    let sell = 0;
    let maxTrade = 0;
    for (const t of trades) {
      if (t.side === 'buy') buy += t.notionalUsdt;
      else sell += t.notionalUsdt;
      if (t.notionalUsdt > maxTrade) maxTrade = t.notionalUsdt;
    }
    return { buy, sell, delta: buy - sell, maxTrade, count: trades.length };
  }, [trades]);

  // 气泡图：x=时间 y=价格 size=名义 红买绿卖
  useEffect(() => {
    if (!bubbleRef.current) return;
    if (!bubbleChart.current) {
      bubbleChart.current = echarts.init(bubbleRef.current);
    }
    const chart = bubbleChart.current;
    const buyPoints = trades
      .filter((t) => t.side === 'buy')
      .map((t) => [t.tradeTs, t.px, t.notionalUsdt]);
    const sellPoints = trades
      .filter((t) => t.side === 'sell')
      .map((t) => [t.tradeTs, t.px, t.notionalUsdt]);

    chart.setOption(
      {
        backgroundColor: 'transparent',
        animation: false,
        grid: { left: 70, right: 20, top: 16, bottom: 40 },
        tooltip: {
          trigger: 'item',
          formatter: (p: { seriesName: string; value: [number, number, number] }) =>
            `${p.seriesName} · ${fmtTime(p.value[0])}<br/>价格 ${p.value[1]} · 成交额 ${fmtUsdt(p.value[2])} 元`,
        },
        xAxis: {
          type: 'time',
          axisLabel: { color: '#9ca3af', fontSize: 10 },
          splitLine: { show: false },
        },
        yAxis: {
          type: 'value',
          scale: true,
          axisLabel: { color: '#9ca3af', fontSize: 10 },
          splitLine: { lineStyle: { color: 'rgba(107,114,128,0.15)' } },
        },
        series: [
          {
            name: '主动买',
            type: 'scatter',
            symbolSize: (val: [number, number, number]) =>
              Math.max(4, Math.min(26, (Math.sqrt(val[2] / threshold) * 26) / 4.5)),
            data: buyPoints,
            itemStyle: { color: upColor, opacity: 0.75 },
          },
          {
            name: '主动卖',
            type: 'scatter',
            symbolSize: (val: [number, number, number]) =>
              Math.max(4, Math.min(26, (Math.sqrt(val[2] / threshold) * 26) / 4.5)),
            data: sellPoints,
            itemStyle: { color: downColor, opacity: 0.75 },
          },
        ],
      },
      true,
    );
  }, [trades, upColor, downColor, threshold]);

  // 副图：bar 级 delta 柱 + 累积 CVD 线
  useEffect(() => {
    if (!deltaRef.current) return;
    if (!deltaChart.current) {
      deltaChart.current = echarts.init(deltaRef.current);
    }
    const chart = deltaChart.current;
    chart.setOption(
      {
        backgroundColor: 'transparent',
        animation: false,
        grid: { left: 70, right: 70, top: 16, bottom: 40 },
        tooltip: { trigger: 'axis' },
        legend: {
          data: ['bar 净流', '累积 CVD'],
          textStyle: { color: '#9ca3af', fontSize: 10 },
          top: 0,
        },
        xAxis: {
          type: 'time',
          axisLabel: { color: '#9ca3af', fontSize: 10 },
          splitLine: { show: false },
        },
        yAxis: [
          {
            type: 'value',
            name: '净流',
            nameTextStyle: { color: '#9ca3af', fontSize: 10 },
            axisLabel: {
              color: '#9ca3af',
              fontSize: 10,
              formatter: (v: number) => fmtUsdt(v),
            },
            splitLine: { lineStyle: { color: 'rgba(107,114,128,0.15)' } },
          },
          {
            type: 'value',
            name: 'CVD',
            nameTextStyle: { color: '#9ca3af', fontSize: 10 },
            axisLabel: {
              color: '#9ca3af',
              fontSize: 10,
              formatter: (v: number) => fmtUsdt(v),
            },
            splitLine: { show: false },
          },
        ],
        series: [
          {
            name: 'bar 净流',
            type: 'bar',
            data: bars.map((b) => [b.barTs, b.delta]),
            itemStyle: {
              color: (p: { value: [number, number] }) =>
                p.value[1] >= 0 ? upColor : downColor,
            },
            barMaxWidth: 12,
          },
          {
            name: '累积 CVD',
            type: 'line',
            yAxisIndex: 1,
            data: bars.map((b) => [b.barTs, b.cumDelta]),
            lineStyle: { color: '#3b82f6', width: 1.5 },
            itemStyle: { color: '#3b82f6' },
            symbol: 'none',
          },
        ],
      },
      true,
    );
  }, [bars, upColor, downColor]);

  useEffect(() => {
    const onResize = () => {
      bubbleChart.current?.resize();
      deltaChart.current?.resize();
    };
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      bubbleChart.current?.dispose();
      deltaChart.current?.dispose();
      bubbleChart.current = null;
      deltaChart.current = null;
    };
  }, []);

  const statusBadge = streamStatus?.connected
    ? { text: '已连接', cls: 'bg-up/10 text-up border-up/30' }
    : streamStatus?.enabled
      ? { text: '重连中', cls: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30' }
      : { text: '未启用', cls: 'bg-gray-500/10 text-gray-400 border-gray-500/30' };

  return (
    <div className="space-y-4 p-4 text-gray-200">
      {/* 页头 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-blue-400" />
          <h1 className="text-lg font-semibold">A 股资金流 · 大单微观结构</h1>
          <span className={`rounded border px-2 py-0.5 text-xs ${statusBadge.cls}`}>
            {statusBadge.text}
          </span>
          {streamStatus && (
            <span className="text-xs text-gray-500">
              采集 {streamStatus.totalIngested.toLocaleString()} 笔 · 阈值 ≥{' '}
              ¥{fmtUsdt(streamStatus.minNotionalUsdt)} · 重连 {streamStatus.reconnects}
              {streamStatus.lastError ? ` · ${streamStatus.lastError}` : ''}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-gray-400">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="accent-blue-500"
            />
            30s 自动刷新
          </label>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1 rounded border border-crypto-border bg-crypto-card px-3 py-1.5 text-xs hover:border-blue-500/50 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </button>
        </div>
      </div>

      {/* 控件行 */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="rounded border border-crypto-border bg-crypto-card px-2 py-1.5"
        >
          {SYMBOL_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          value={hours}
          onChange={(e) => setHours(Number(e.target.value))}
          className="rounded border border-crypto-border bg-crypto-card px-2 py-1.5"
        >
          {RANGE_OPTIONS.map((r) => (
            <option key={r.hours} value={r.hours}>
              {r.label}
            </option>
          ))}
        </select>
        <select
          value={threshold}
          onChange={(e) => setThreshold(Number(e.target.value))}
          className="rounded border border-crypto-border bg-crypto-card px-2 py-1.5"
        >
          {THRESHOLD_OPTIONS.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <select
          value={barMinutes}
          onChange={(e) => setBarMinutes(Number(e.target.value))}
          className="rounded border border-crypto-border bg-crypto-card px-2 py-1.5"
        >
          {BAR_OPTIONS.map((b) => (
            <option key={b.minutes} value={b.minutes}>
              {b.label}
            </option>
          ))}
        </select>
        <div className="flex overflow-hidden rounded border border-crypto-border">
          {(['all', 'buy', 'sell'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSideFilter(s)}
              className={`px-3 py-1.5 ${
                sideFilter === s ? 'bg-blue-500/20 text-blue-300' : 'bg-crypto-card text-gray-400'
              }`}
            >
              {s === 'all' ? '全部' : s === 'buy' ? '主买' : '主卖'}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          <AlertTriangle className="h-4 w-4" />
          {error}
        </div>
      )}

      {/* KPI 行 */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        {[
          { label: '大单笔数', value: kpi.count.toLocaleString(), cls: 'text-gray-200' },
          { label: '主买金额', value: `¥${fmtUsdt(kpi.buy)}`, cls: 'text-up' },
          { label: '主卖金额', value: `¥${fmtUsdt(kpi.sell)}`, cls: 'text-down' },
          {
            label: '净流 Delta',
            value: `${kpi.delta >= 0 ? '+' : ''}¥${fmtUsdt(kpi.delta)}`,
            cls: kpi.delta >= 0 ? 'text-up' : 'text-down',
          },
          { label: '最大单笔', value: `¥${fmtUsdt(kpi.maxTrade)}`, cls: 'text-blue-300' },
        ].map((item) => (
          <div
            key={item.label}
            className="rounded border border-crypto-border bg-crypto-card px-3 py-2"
          >
            <div className="text-xs text-gray-500">{item.label}</div>
            <div className={`mt-1 text-base font-semibold ${item.cls}`}>{item.value}</div>
          </div>
        ))}
      </div>

      {/* 气泡图 */}
      <div className="rounded border border-crypto-border bg-crypto-card p-3">
        <div className="mb-1 text-xs text-gray-500">
          大单时间轴 · 气泡大小 = 单笔成交额（{symbol}）
        </div>
        <div ref={bubbleRef} className="h-72 w-full" />
        {trades.length === 0 && !loading && (
          <div className="flex items-center justify-center gap-2 py-6 text-xs text-gray-500">
            <Database className="h-4 w-4" />
            当前窗口无大单数据——采集服务自部署起实时写入，数据随运行时间累积
          </div>
        )}
      </div>

      {/* Delta 副图 */}
      <div className="rounded border border-crypto-border bg-crypto-card p-3">
        <div className="mb-1 text-xs text-gray-500">
          Bar 级主买/主卖净流与累积 CVD（{BAR_OPTIONS.find((b) => b.minutes === barMinutes)?.label}）
        </div>
        <div ref={deltaRef} className="h-56 w-full" />
      </div>

      {/* 明细表 */}
      <div className="rounded border border-crypto-border bg-crypto-card">
        <div className="border-b border-crypto-border px-3 py-2 text-xs text-gray-500">
          大单明细（最近 {Math.min(trades.length, 200)} / {trades.length} 笔）
        </div>
        <div className="max-h-80 overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-crypto-card text-gray-500">
              <tr>
                <th className="px-3 py-2 text-left font-normal">时间</th>
                <th className="px-3 py-2 text-left font-normal">方向</th>
                <th className="px-3 py-2 text-right font-normal">价格</th>
                <th className="px-3 py-2 text-right font-normal">数量(股)</th>
                <th className="px-3 py-2 text-right font-normal">名义(U)</th>
              </tr>
            </thead>
            <tbody>
              {trades.slice(0, 200).map((t) => (
                <tr key={t.tradeId} className="border-t border-crypto-border/50">
                  <td className="px-3 py-1.5 text-gray-400">{fmtTime(t.tradeTs)}</td>
                  <td className="px-3 py-1.5">
                    <span
                      className={`inline-flex items-center gap-0.5 ${
                        t.side === 'buy' ? 'text-up' : 'text-down'
                      }`}
                    >
                      {t.side === 'buy' ? (
                        <ArrowUpRight className="h-3 w-3" />
                      ) : (
                        <ArrowDownRight className="h-3 w-3" />
                      )}
                      {t.side === 'buy' ? '主买' : '主卖'}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{t.px}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {t.szBase < 1 ? t.szBase.toFixed(4) : t.szBase.toFixed(2)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {fmtUsdt(t.notionalUsdt)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {trades.length === 0 && !loading && (
            <div className="px-3 py-8 text-center text-xs text-gray-500">暂无明细</div>
          )}
        </div>
      </div>
    </div>
  );
}
