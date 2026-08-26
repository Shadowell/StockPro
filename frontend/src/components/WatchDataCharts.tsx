import { useEffect, useMemo, useRef } from 'react';
import * as echarts from 'echarts';
import type { WatchDerivativePoint, WatchDerivativesData } from '../api/client';

interface WatchDataChartsProps {
  data: WatchDerivativesData | null;
  compact?: boolean;
}

interface ChartCardProps {
  title: string;
  description: string;
  points?: WatchDerivativePoint[] | null;
  mode: 'bar-line' | 'line' | 'ratio' | 'dual-volume' | 'basis';
  compact?: boolean;
}

function fmtTime(ts: number): string {
  return new Date(ts).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function num(value: unknown): number | null {
  const next = Number(value);
  return Number.isFinite(next) ? next : null;
}

function pct(value: unknown): string {
  const next = num(value);
  if (next == null) return '--';
  return `${(next * 100).toFixed(4)}%`;
}

function ChartCard({ title, description, points, mode, compact = false }: ChartCardProps) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const usable = (points || []).filter((point) => Number.isFinite(Number(point.timestamp)));

  const option = useMemo(() => {
    const x = usable.map((point) => fmtTime(Number(point.timestamp)));
    const values = usable.map((point) => num(point.value));
    const buy = usable.map((point) => num(point.buy));
    const sell = usable.map((point) => num(point.sell));
    const longRatio = usable.map((point) => num(point.longAccountRatio ?? point.long_account_ratio));
    const shortRatio = usable.map((point) => num(point.shortAccountRatio ?? point.short_account_ratio));
    const basisRate = usable.map((point) => num(point.basisRate ?? point.basis_rate));

    const base = {
      backgroundColor: 'transparent',
      animation: false,
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(15,23,42,0.95)',
        borderColor: '#334155',
        textStyle: { color: '#e5e7eb' },
      },
      legend: { bottom: 0, itemWidth: compact ? 10 : 14, itemHeight: compact ? 6 : 8, textStyle: { color: '#8b949e', fontSize: compact ? 10 : 12 } },
      grid: { left: compact ? 32 : 42, right: compact ? 34 : 44, top: compact ? 24 : 28, bottom: compact ? 34 : 42 },
      xAxis: {
        type: 'category',
        data: x,
        axisLabel: { color: '#8b949e', hideOverlap: true, fontSize: compact ? 10 : 12 },
        axisLine: { lineStyle: { color: '#1f2937' } },
      },
      yAxis: [
        {
          type: 'value',
          scale: true,
          axisLabel: { color: '#8b949e', fontSize: compact ? 10 : 12 },
          splitLine: { lineStyle: { color: '#18212f' } },
        },
        {
          type: 'value',
          scale: true,
          axisLabel: { color: '#8b949e', fontSize: compact ? 10 : 12 },
          splitLine: { show: false },
        },
      ],
      series: [] as any[],
    };

    if (mode === 'bar-line') {
      base.series = [
        { name: '持仓量', type: 'bar', data: values, itemStyle: { color: '#f59e0b' }, barWidth: '54%' },
        { name: '均值', type: 'line', data: values, smooth: true, showSymbol: false, lineStyle: { color: '#e5e7eb', width: 1.4 } },
      ];
    } else if (mode === 'line') {
      base.series = [
        { name: '资金费率', type: 'line', data: values, smooth: true, showSymbol: false, lineStyle: { color: '#ec4899', width: 1.6 } },
      ];
      base.yAxis[0].axisLabel = { color: '#8b949e', formatter: (value: number) => pct(value) } as any;
    } else if (mode === 'ratio') {
      base.series = [
        { name: '多头账户比例', type: 'bar', stack: 'ratio', data: longRatio, itemStyle: { color: '#16a34a' }, barWidth: '62%' },
        { name: '空头账户比例', type: 'bar', stack: 'ratio', data: shortRatio, itemStyle: { color: '#db2777' }, barWidth: '62%' },
        { name: '多空比', type: 'line', yAxisIndex: 1, data: values, smooth: true, showSymbol: false, lineStyle: { color: '#e5e7eb', width: 1.4 } },
      ];
    } else if (mode === 'dual-volume') {
      base.series = [
        { name: '主动买入量', type: 'line', data: buy, smooth: true, showSymbol: false, lineStyle: { color: '#db2777', width: 1.5 } },
        { name: '主动卖出量', type: 'line', data: sell, smooth: true, showSymbol: false, lineStyle: { color: '#16a34a', width: 1.5 } },
      ];
    } else {
      base.series = [
        { name: '合约价格 - 指数价格', type: 'line', data: values, smooth: true, showSymbol: false, lineStyle: { color: '#6366f1', width: 1.5 } },
        { name: '价差率', type: 'line', yAxisIndex: 1, data: basisRate, smooth: true, showSymbol: false, lineStyle: { color: '#f59e0b', width: 1.5 } },
      ];
      base.yAxis[1].axisLabel = { color: '#8b949e', formatter: (value: number) => pct(value) } as any;
    }

    return base;
  }, [compact, mode, usable]);

  useEffect(() => {
    if (!ref.current) return undefined;
    chart.current = echarts.init(ref.current, 'dark');
    const resize = () => chart.current?.resize();
    window.addEventListener('resize', resize);
    return () => {
      window.removeEventListener('resize', resize);
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    if (usable.length > 0) chart.current?.setOption(option, true);
  }, [option, usable.length]);

  return (
    <section className={`rounded-xl border border-crypto-border bg-crypto-card/80 ${compact ? 'p-3' : 'p-4'}`}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-gray-100">{title}</div>
          {!compact && <div className="mt-1 text-xs text-gray-500">{description}</div>}
        </div>
        <div className="text-xs text-gray-500">{usable.length ? `${usable.length} 点` : 'OKX 暂无数据'}</div>
      </div>
      {usable.length ? (
        <div ref={ref} className={compact ? 'h-[250px]' : 'h-[310px]'} />
      ) : (
        <div className={`${compact ? 'h-[250px]' : 'h-[310px]'} flex items-center justify-center rounded-lg border border-dashed border-crypto-border text-sm text-gray-500`}>
          暂无 OKX 数据
        </div>
      )}
    </section>
  );
}

export default function WatchDataCharts({ data, compact = false }: WatchDataChartsProps) {
  return (
    <div className={compact ? 'grid grid-cols-1 gap-3' : 'grid grid-cols-1 gap-4 xl:grid-cols-2'}>
      <ChartCard
        title="持仓量"
        description="OKX 合约持仓量历史，柱线组合展示"
        points={data?.openInterest.points}
        mode="bar-line"
        compact={compact}
      />
      <ChartCard
        title="资金费率"
        description="真实资金费率历史；缺失时不生成模拟值"
        points={data?.fundingRate.points}
        mode="line"
        compact={compact}
      />
      <ChartCard
        title="合约多空账户比例"
        description="多头账户比例、空头账户比例与多空比"
        points={data?.longShortRatio.points}
        mode="ratio"
        compact={compact}
      />
      <ChartCard
        title="主动买卖量"
        description="主动买入量与主动卖出量"
        points={data?.takerVolume.points}
        mode="dual-volume"
        compact={compact}
      />
      <div className={compact ? '' : 'xl:col-span-2'}>
        <ChartCard
          title="合约基差"
          description="优先 OKX basis；不可用时由真实标记价/指数价链路计算"
          points={data?.basis.points}
          mode="basis"
          compact={compact}
        />
      </div>
    </div>
  );
}
