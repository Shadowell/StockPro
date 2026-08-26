import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import * as echarts from 'echarts';
import {
  Activity,
  AlertTriangle,
  ArrowUpDown,
  Banknote,
  BarChart3,
  Blocks,
  Bookmark,
  CheckCircle2,
  CircleDollarSign,
  DatabaseZap,
  Filter,
  Gauge,
  Info,
  Layers3,
  Loader2,
  Network,
  RefreshCw,
  Search,
  ShieldAlert,
  Star,
  StarOff,
  TrendingUp,
  Wallet,
} from 'lucide-react';
import clsx from 'clsx';
import { onchainApi, type OnchainSummary } from '../api/client';
import AnimatedNumber from '../components/AnimatedNumber';
import { SELECTED_SEGMENT_BORDER_CLASS } from '../utils/selectionStyles';

type TabId = 'overview' | 'protocols' | 'yields';
type ProtocolSort = 'tvl' | 'change7d' | 'feeEfficiency';
type YieldSort = 'apy' | 'tvl' | 'risk';
type WatchKind = 'chain' | 'protocol' | 'yield';
type DataRow = Record<string, unknown>;

const ONCHAIN_AUTO_REFRESH_SECONDS = 300;

const tabs: Array<{ id: TabId; label: string; icon: typeof Network }> = [
  { id: 'overview', label: '综合总览', icon: Network },
  { id: 'protocols', label: '协议研究', icon: Layers3 },
  { id: 'yields', label: '收益机会', icon: Wallet },
];

const protocolSortOptions: Array<{ value: ProtocolSort; label: string }> = [
  { value: 'tvl', label: '按锁仓量' },
  { value: 'feeEfficiency', label: '按费用/TVL' },
  { value: 'change7d', label: '按7日变化' },
];

const yieldSortOptions: Array<{ value: YieldSort; label: string }> = [
  { value: 'apy', label: '按年化收益' },
  { value: 'tvl', label: '按池锁仓量' },
  { value: 'risk', label: '按风险优先' },
];

function numberFrom(record: DataRow, key: string): number | null {
  const raw = record[key];
  if (raw === null || raw === undefined || raw === '') return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function textFrom(record: DataRow, key: string, fallback = '--'): string {
  const raw = record[key];
  if (raw === null || raw === undefined || raw === '') return fallback;
  return String(raw);
}

function listFrom(record: DataRow, key: string): string[] {
  const raw = record[key];
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => String(item)).filter(Boolean);
}

function money(value?: number | null): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return '0 美元';
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000_000) return `${(n / 1_000_000_000_000).toFixed(2)} 万亿美元`;
  if (abs >= 100_000_000) return `${(n / 100_000_000).toFixed(2)} 亿美元`;
  if (abs >= 10_000) return `${(n / 10_000).toFixed(2)} 万美元`;
  return `${n.toFixed(2)} 美元`;
}

function pct(value?: number | null, digits = 2): string {
  const n = Number(value ?? Number.NaN);
  if (!Number.isFinite(n)) return '--';
  const prefix = n > 0 ? '+' : '';
  return `${prefix}${n.toFixed(digits)}%`;
}

function dateTime(value?: string): string {
  if (!value) return '--';
  const time = new Date(value);
  if (Number.isNaN(time.getTime())) return value;
  return time.toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function ratio(value: number | null, max: number): number {
  if (!value || value <= 0 || max <= 0) return 0;
  return Math.max(4, Math.min(100, (value / max) * 100));
}

function statusTone(status: string): string {
  if (status === 'ready') return 'border-emerald-500/35 bg-emerald-500/10 text-emerald-200';
  if (status === 'partial') return 'border-amber-500/35 bg-amber-500/10 text-amber-200';
  if (status === 'error') return 'border-red-500/35 bg-red-500/10 text-red-200';
  return 'border-gray-700 bg-gray-900/70 text-gray-400';
}

function statusLabel(status: string): string {
  if (status === 'ready') return '正常';
  if (status === 'partial') return '部分可用';
  if (status === 'waiting_for_data') return '等待数据';
  if (status === 'loading') return '加载中';
  if (status === 'error') return '异常';
  if (status === 'empty') return '空数据';
  return status || '--';
}

function sourceLabel(name: string): string {
  const labels: Record<string, string> = {
    chains: '链锁仓量',
    protocols: '协议锁仓量',
    fees: '协议费用',
    stablecoins: '稳定币供给',
    stablecoin_chains: '稳定币链分布',
    yield_pools: '稳定币收益池',
    stablecoinChains: '稳定币链分布',
    yieldPools: '稳定币收益池',
  };
  return labels[name] || name;
}

function localizeWarning(warning: string): string {
  return warning
    .replace('DeFiLlama yield_pools ', 'DeFiLlama 稳定币收益池 ')
    .replace('DeFiLlama stablecoin_chains ', 'DeFiLlama 稳定币链分布 ')
    .replace(/DeFiLlama (chains|protocols|fees|stablecoins) /g, (_, name: string) => `DeFiLlama ${sourceLabel(name)} `);
}

function changeTone(value: number | null): string {
  if (value === null) return 'text-gray-500';
  if (value > 0) return 'text-up';
  if (value < 0) return 'text-down';
  return 'text-gray-400';
}

function protocolIdentity(row: DataRow): string {
  return textFrom(row, 'slug', textFrom(row, 'name')).toLowerCase();
}

function chainText(row: DataRow): string {
  const chains = listFrom(row, 'chains');
  return chains.length ? chains.join(' / ') : textFrom(row, 'chain');
}

function pegRisk(row: DataRow): { label: string; tone: string } {
  const price = numberFrom(row, 'price');
  if (price === null) return { label: '无价格', tone: 'text-gray-500' };
  if (price < 0.995 || price > 1.005) return { label: '锚定偏离', tone: 'text-amber-200' };
  return { label: '锚定稳定', tone: 'text-emerald-200' };
}

function yieldRisk(row: DataRow): { label: string; tone: string; score: number } {
  const apy = numberFrom(row, 'apy') || 0;
  const mean30d = numberFrom(row, 'apyMean30d');
  const tvl = numberFrom(row, 'tvlUsd') || 0;
  const ilRisk = textFrom(row, 'ilRisk', '').toLowerCase();
  if (ilRisk && ilRisk !== 'no' && ilRisk !== 'none') {
    return { label: '无常损失风险', tone: 'text-red-200', score: 3 };
  }
  if (apy >= 20 || (mean30d !== null && apy - mean30d >= 8)) {
    return { label: '年化异常偏高', tone: 'text-amber-200', score: 2 };
  }
  if (tvl > 0 && tvl < 5_000_000) {
    return { label: '池规模偏小', tone: 'text-amber-200', score: 1 };
  }
  return { label: '稳定币收益线索', tone: 'text-emerald-200', score: 0 };
}

function watchId(kind: WatchKind, row: DataRow): string {
  if (kind === 'chain') return `chain:${textFrom(row, 'name')}`;
  if (kind === 'yield') return `yield:${textFrom(row, 'pool', `${textFrom(row, 'project')}:${textFrom(row, 'chain')}:${textFrom(row, 'symbol')}`)}`;
  return `protocol:${protocolIdentity(row)}`;
}

function EmptyPanel({ text }: { text: string }) {
  return (
    <div className="flex min-h-[116px] items-center justify-center rounded-lg border border-dashed border-crypto-border bg-crypto-bg/45 px-4 text-center text-sm text-gray-500">
      {text}
    </div>
  );
}

const CHART_AXIS_COLOR = '#8b949e';
const CHART_SPLIT_COLOR = '#21262d';

function compactUsd(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000_000) return `$${(value / 1_000_000_000_000).toFixed(2)}T`;
  if (abs >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  return `$${value.toFixed(0)}`;
}

function ChainTvlBarChart({ rows, height = 300 }: { rows: DataRow[]; height?: number }) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  const topRows = useMemo(() => {
    return [...rows]
      .map((row) => ({ name: textFrom(row, 'name'), tvl: numberFrom(row, 'tvlUsd') || 0 }))
      .filter((row) => row.name && row.tvl > 0)
      .sort((a, b) => b.tvl - a.tvl)
      .slice(0, 10)
      .reverse();
  }, [rows]);

  const option = useMemo(
    () => ({
      backgroundColor: 'transparent',
      animation: true,
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(13, 17, 23, 0.96)',
        borderColor: '#30363D',
        textStyle: { color: '#e6edf3' },
        formatter: (params: any) =>
          `${params.name}<br/>锁仓量：<span style="color:#67e8f9">${money(Number(params.value))}</span>`,
      },
      grid: { left: 8, right: 72, top: 8, bottom: 8, containLabel: true },
      xAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: CHART_SPLIT_COLOR } },
        axisLabel: { color: CHART_AXIS_COLOR, fontSize: 10, formatter: (value: number) => compactUsd(value) },
      },
      yAxis: {
        type: 'category',
        inverse: false,
        data: topRows.map((row) => row.name),
        axisLine: { lineStyle: { color: '#30363D' } },
        axisTick: { show: false },
        axisLabel: { color: '#e6edf3', fontSize: 11 },
      },
      series: [
        {
          type: 'bar',
          data: topRows.map((row) => row.tvl),
          barMaxWidth: 16,
          itemStyle: {
            borderRadius: [0, 4, 4, 0],
            color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
              { offset: 0, color: 'rgba(34, 211, 238, 0.25)' },
              { offset: 1, color: 'rgba(34, 211, 238, 0.85)' },
            ]),
          },
          label: {
            show: true,
            position: 'right',
            color: CHART_AXIS_COLOR,
            fontSize: 10,
            formatter: (params: any) => compactUsd(Number(params.value)),
          },
        },
      ],
    }),
    [topRows],
  );

  useEffect(() => {
    if (!chartRef.current) return;
    chartInstance.current = echarts.init(chartRef.current);
    const observer = new ResizeObserver(() => chartInstance.current?.resize());
    observer.observe(chartRef.current);
    return () => {
      observer.disconnect();
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chartInstance.current) return;
    chartInstance.current.setOption(option, { notMerge: true });
  }, [option]);

  if (!topRows.length) {
    return <EmptyPanel text="等待 DeFiLlama 返回真实链上数据" />;
  }

  return <div ref={chartRef} style={{ width: '100%', height }} />;
}

function Panel({
  title,
  description,
  icon,
  action,
  children,
  className,
}: {
  title: string;
  description?: string;
  icon: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={clsx('min-w-0 overflow-hidden rounded-xl border border-crypto-border bg-crypto-card/80 p-4', className)}>
      <div className="mb-3 flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            {icon}
            <span className="truncate">{title}</span>
          </div>
          {description && <div className="mt-0.5 text-xs leading-5 text-gray-500">{description}</div>}
        </div>
        {action && <div className="shrink-0 pt-0.5">{action}</div>}
      </div>
      {children}
    </section>
  );
}

type MetricTone = 'liquidity' | 'stable' | 'fee' | 'yield' | 'chain' | 'protocol';

const metricToneStyles: Record<MetricTone, { sub: string; bar: string }> = {
  liquidity: {
    sub: 'text-cyan-100/65',
    bar: 'bg-cyan-400/70',
  },
  stable: {
    sub: 'text-emerald-100/65',
    bar: 'bg-emerald-400/70',
  },
  fee: {
    sub: 'text-amber-100/65',
    bar: 'bg-amber-400/75',
  },
  yield: {
    sub: 'text-lime-100/65',
    bar: 'bg-lime-400/70',
  },
  chain: {
    sub: 'text-sky-100/65',
    bar: 'bg-sky-400/70',
  },
  protocol: {
    sub: 'text-indigo-100/65',
    bar: 'bg-indigo-400/70',
  },
};

function MetricCard({
  label,
  value,
  countValue,
  countFormat,
  sub,
  tone = 'liquidity',
}: {
  label: string;
  value: string;
  countValue?: number | null;
  countFormat?: (value: number) => string;
  sub?: string;
  tone?: MetricTone;
}) {
  const styles = metricToneStyles[tone];
  return (
    <div className="relative min-h-[112px] overflow-hidden rounded-xl border border-crypto-border bg-crypto-card p-4">
      <div className={clsx('absolute inset-x-0 bottom-0 h-0.5', styles.bar)} />
      <div className="min-w-0">
        <div className="text-xs font-medium text-gray-500">{label}</div>
        <div className="mt-2 truncate text-xl font-bold leading-7 tracking-normal tabular-nums text-white">
          {countValue != null && countFormat ? (
            <AnimatedNumber value={countValue} format={countFormat} />
          ) : (
            value
          )}
        </div>
      </div>
      {sub && <div className={clsx('mt-3 truncate text-xs', styles.sub)}>{sub}</div>}
    </div>
  );
}

function GlossaryChip({
  label,
  text,
  tone = 'cyan',
}: {
  label: string;
  text: string;
  tone?: 'cyan' | 'emerald' | 'amber' | 'red';
}) {
  const tones = {
    cyan: 'border-cyan-400/30 bg-cyan-500/10 text-cyan-100',
    emerald: 'border-emerald-400/30 bg-emerald-500/10 text-emerald-100',
    amber: 'border-amber-400/30 bg-amber-500/10 text-amber-100',
    red: 'border-red-400/30 bg-red-500/10 text-red-100',
  };
  return (
    <span
      title={text}
      className={clsx('inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-semibold', tones[tone])}
    >
      <Info className="h-3.5 w-3.5" />
      {label}
    </span>
  );
}

function ScaleBar({ value, max, tone = 'bg-cyan-400/70' }: { value: number | null; max: number; tone?: string }) {
  return (
    <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-crypto-bg">
      <div className={clsx('h-full rounded-full', tone)} style={{ width: `${ratio(value, max)}%` }} />
    </div>
  );
}

function WatchButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      className={clsx(
        'inline-flex h-8 w-8 items-center justify-center rounded-lg border transition-colors',
        active
          ? SELECTED_SEGMENT_BORDER_CLASS
          : 'border-crypto-border bg-crypto-bg/70 text-gray-500 hover:border-cyan-400/45 hover:text-cyan-100'
      )}
    >
      {active ? <Star className="h-4 w-4" /> : <StarOff className="h-4 w-4" />}
    </button>
  );
}

function SelectControl<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <label className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-bg/70 px-2 text-xs text-gray-500">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
        className="h-7 rounded-md border border-crypto-border bg-crypto-card px-2 text-xs font-medium text-gray-200 outline-none"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function SearchBox({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <label className="relative flex h-9 min-w-[220px] flex-1 items-center">
      <Search className="pointer-events-none absolute left-2.5 h-4 w-4 text-gray-600" />
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="h-9 w-full rounded-lg border border-crypto-border bg-crypto-bg/70 pl-8 pr-3 text-sm text-gray-100 outline-none placeholder:text-gray-600 focus:border-cyan-500/60"
      />
    </label>
  );
}

function CapitalFlowPipeline({
  chains,
  protocols,
  height = 380,
}: {
  chains: DataRow[];
  protocols: DataRow[];
  height?: number;
}) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  const graph = useMemo(() => {
    const chainRows = [...chains]
      .map((row) => ({ name: textFrom(row, 'name'), tvl: numberFrom(row, 'tvlUsd') || 0 }))
      .filter((row) => row.name && row.tvl > 0)
      .sort((a, b) => b.tvl - a.tvl);
    const topChains = chainRows.slice(0, 8);
    if (!topChains.length) return null;
    const totalTvl = chainRows.reduce((sum, row) => sum + row.tvl, 0);

    const protocolByChain = new Map<string, Array<{ name: string; tvl: number }>>();
    for (const row of protocols) {
      const primary = listFrom(row, 'chains')[0] || textFrom(row, 'chain', '');
      const tvl = numberFrom(row, 'tvlUsd') || 0;
      if (!primary || tvl <= 0) continue;
      const arr = protocolByChain.get(primary) || [];
      arr.push({ name: textFrom(row, 'name'), tvl });
      protocolByChain.set(primary, arr);
    }

    const rootNode = '全链 TVL';
    const nodes: Array<{ name: string }> = [{ name: rootNode }];
    const links: Array<{ source: string; target: string; value: number }> = [];
    const usedNames = new Set<string>([rootNode]);
    for (const chain of topChains) {
      nodes.push({ name: chain.name });
      usedNames.add(chain.name);
      links.push({ source: rootNode, target: chain.name, value: chain.tvl });
      const topProtocols = (protocolByChain.get(chain.name) || [])
        .sort((a, b) => b.tvl - a.tvl)
        .slice(0, 3);
      for (const proto of topProtocols) {
        let nodeName = proto.name;
        if (usedNames.has(nodeName)) nodeName = `${proto.name} · ${chain.name}`;
        usedNames.add(nodeName);
        nodes.push({ name: nodeName });
        links.push({ source: chain.name, target: nodeName, value: proto.tvl });
      }
    }
    return { rootNode, totalTvl, nodes, links };
  }, [chains, protocols]);

  const option = useMemo(() => {
    if (!graph) return null;
    return {
      backgroundColor: 'transparent',
      animation: true,
      animationDuration: 1200,
      animationEasing: 'cubicOut' as const,
      tooltip: {
        backgroundColor: 'rgba(13, 17, 23, 0.96)',
        borderColor: '#30363D',
        textStyle: { color: '#e6edf3', fontSize: 12 },
        formatter: (params: any) => {
          if (params.dataType === 'edge') {
            return `${params.data.source} → ${params.data.target}<br/>锁仓量：<span style="color:#67e8f9">${money(Number(params.data.value))}</span>`;
          }
          const value = Number(params.value);
          return `${params.name}<br/>锁仓量：<span style="color:#67e8f9">${money(value)}</span>`;
        },
      },
      series: [
        {
          type: 'sankey',
          left: 10,
          right: 130,
          top: 12,
          bottom: 12,
          nodeWidth: 14,
          nodeGap: 12,
          data: graph.nodes,
          links: graph.links,
          emphasis: { focus: 'adjacency' },
          nodeAlign: 'justify',
          itemStyle: { borderRadius: 3, color: '#22d3ee' },
          lineStyle: { color: 'gradient', opacity: 0.28, curveness: 0.5 },
          label: { color: '#e6edf3', fontSize: 11, width: 120, overflow: 'truncate' },
        },
      ],
    };
  }, [graph]);

  useEffect(() => {
    if (!chartRef.current) return;
    chartInstance.current = echarts.init(chartRef.current);
    const observer = new ResizeObserver(() => chartInstance.current?.resize());
    observer.observe(chartRef.current);
    return () => {
      observer.disconnect();
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chartInstance.current || !option) return;
    chartInstance.current.setOption(option, { notMerge: true });
  }, [option]);

  if (!graph || graph.links.length === 0) {
    return <EmptyPanel text="等待 DeFiLlama 返回真实链上数据" />;
  }

  return (
    <div>
      <div className="mb-2 text-[11px] text-gray-500">
        全链锁仓 {money(graph.totalTvl)} · 覆盖锁仓量前 {Math.min(8, graph.nodes.length - 1)} 条公链与其头部协议，连线越粗代表资金越大
      </div>
      <div ref={chartRef} style={{ width: '100%', height }} />
    </div>
  );
}

export default function OnchainResearch() {
  const [summary, setSummary] = useState<OnchainSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [protocolQuery, setProtocolQuery] = useState('');
  const [protocolChain, setProtocolChain] = useState('all');
  const [protocolCategory, setProtocolCategory] = useState('all');
  const [protocolSort, setProtocolSort] = useState<ProtocolSort>('tvl');
  const [yieldChain, setYieldChain] = useState('all');
  const [yieldRiskFilter, setYieldRiskFilter] = useState('all');
  const [yieldSort, setYieldSort] = useState<YieldSort>('apy');
  const [watchIds, setWatchIds] = useState<Set<string>>(() => new Set());
  const [refreshCountdown, setRefreshCountdown] = useState(ONCHAIN_AUTO_REFRESH_SECONDS);

  const loadSummary = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setSummary(await onchainApi.getSummary());
      setRefreshCountdown(ONCHAIN_AUTO_REFRESH_SECONDS);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || '链上数据加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      setRefreshCountdown((prev) => {
        if (prev <= 1) {
          void loadSummary();
          return ONCHAIN_AUTO_REFRESH_SECONDS;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [loadSummary]);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  const kpis = summary?.kpis;
  const endpointStatus = useMemo(() => {
    if (!summary) return [];
    return Object.entries(summary.sourceStatus || {});
  }, [summary]);
  const emptyText = summary?.emptyReason || '等待 A 股资金流、股东与基本面封存快照';

  const maxChainTvl = useMemo(
    () => Math.max(0, ...(summary?.chains || []).map((row) => numberFrom(row, 'tvlUsd') || 0)),
    [summary?.chains]
  );
  const maxStableSupply = useMemo(
    () => Math.max(0, ...(summary?.stablecoins || []).map((row) => numberFrom(row, 'supplyUsd') || 0)),
    [summary?.stablecoins]
  );
  const maxProtocolTvl = useMemo(
    () => Math.max(0, ...(summary?.protocols || []).map((row) => numberFrom(row, 'tvlUsd') || 0)),
    [summary?.protocols]
  );
  const maxYieldTvl = useMemo(
    () => Math.max(0, ...(summary?.yieldPools || []).map((row) => numberFrom(row, 'tvlUsd') || 0)),
    [summary?.yieldPools]
  );

  const feesByProtocol = useMemo(() => {
    const out = new Map<string, number>();
    for (const row of summary?.fees || []) {
      const value = numberFrom(row, 'total24hUsd') || 0;
      const slug = textFrom(row, 'slug', '').toLowerCase();
      const name = textFrom(row, 'name', '').toLowerCase();
      if (slug) out.set(slug, value);
      if (name) out.set(name, value);
    }
    return out;
  }, [summary?.fees]);

  const protocolCategories = useMemo(() => {
    const values = new Set<string>();
    for (const row of summary?.protocols || []) {
      const value = textFrom(row, 'category', '');
      if (value) values.add(value);
    }
    return [{ value: 'all', label: '全部类别' }, ...Array.from(values).slice(0, 12).map((value) => ({ value, label: value }))];
  }, [summary?.protocols]);

  const protocolChains = useMemo(() => {
    const values = new Set<string>();
    for (const row of summary?.protocols || []) {
      for (const value of listFrom(row, 'chains')) values.add(value);
      const chain = textFrom(row, 'chain', '');
      if (chain) values.add(chain);
    }
    return [{ value: 'all', label: '全部链' }, ...Array.from(values).slice(0, 12).map((value) => ({ value, label: value }))];
  }, [summary?.protocols]);

  const yieldChains = useMemo(() => {
    const values = new Set<string>();
    for (const row of summary?.yieldPools || []) {
      const chain = textFrom(row, 'chain', '');
      if (chain) values.add(chain);
    }
    return [{ value: 'all', label: '全部链' }, ...Array.from(values).slice(0, 12).map((value) => ({ value, label: value }))];
  }, [summary?.yieldPools]);

  const protocolRows = useMemo(() => {
    const query = protocolQuery.trim().toLowerCase();
    return [...(summary?.protocols || [])]
      .filter((row) => {
        const category = textFrom(row, 'category', '');
        const chains = chainText(row);
        const haystack = `${textFrom(row, 'name')} ${category} ${chains}`.toLowerCase();
        if (query && !haystack.includes(query)) return false;
        if (protocolCategory !== 'all' && category !== protocolCategory) return false;
        if (protocolChain !== 'all' && !chains.split(' / ').includes(protocolChain)) return false;
        return true;
      })
      .sort((a, b) => {
        if (protocolSort === 'change7d') return (numberFrom(b, 'change7d') || -999) - (numberFrom(a, 'change7d') || -999);
        if (protocolSort === 'feeEfficiency') return protocolFeeEfficiency(b) - protocolFeeEfficiency(a);
        return (numberFrom(b, 'tvlUsd') || 0) - (numberFrom(a, 'tvlUsd') || 0);
      });
  }, [protocolCategory, protocolChain, protocolQuery, protocolSort, summary?.protocols, feesByProtocol]);

  const yieldRows = useMemo(() => {
    return [...(summary?.yieldPools || [])]
      .filter((row) => {
        if (yieldChain !== 'all' && textFrom(row, 'chain') !== yieldChain) return false;
        const risk = yieldRisk(row);
        if (yieldRiskFilter === 'attention' && risk.score === 0) return false;
        if (yieldRiskFilter === 'stable' && risk.score > 0) return false;
        return true;
      })
      .sort((a, b) => {
        if (yieldSort === 'tvl') return (numberFrom(b, 'tvlUsd') || 0) - (numberFrom(a, 'tvlUsd') || 0);
        if (yieldSort === 'risk') return yieldRisk(b).score - yieldRisk(a).score;
        return (numberFrom(b, 'apy') || 0) - (numberFrom(a, 'apy') || 0);
      });
  }, [summary?.yieldPools, yieldChain, yieldRiskFilter, yieldSort]);

  const riskItems = useMemo(() => {
    const items: Array<{ label: string; value: string; tone: string }> = [];
    const failingSources = endpointStatus.filter(([, status]) => status !== 'ready').length;
    if (failingSources > 0) {
      items.push({ label: '数据源', value: `${failingSources} 组数据源暂时不可用，页面数据可能不完整`, tone: 'text-amber-200' });
    }
    const pegRisks = (summary?.stablecoins || []).filter((row) => pegRisk(row).label === '锚定偏离');
    if (pegRisks.length) {
      items.push({ label: '稳定币', value: `${pegRisks.length} 个稳定币价格偏离 1 美元，注意脱锚风险`, tone: 'text-amber-200' });
    }
    const highYield = (summary?.yieldPools || []).filter((row) => yieldRisk(row).score >= 2);
    if (highYield.length) {
      items.push({ label: '收益池', value: `${highYield.length} 个收益池年化异常偏高，可能是高风险信号`, tone: 'text-red-200' });
    }
    const fallingProtocols = (summary?.protocols || []).filter((row) => (numberFrom(row, 'change7d') || 0) <= -10);
    if (fallingProtocols.length) {
      items.push({ label: '协议', value: `${fallingProtocols.length} 个协议一周内资金流出超过 10%`, tone: 'text-down' });
    }
    if (!items.length) {
      items.push({ label: '风险提示', value: '暂无高优先级风险', tone: 'text-emerald-200' });
    }
    return items.slice(0, 4);
  }, [endpointStatus, summary?.protocols, summary?.stablecoins, summary?.yieldPools]);
  const hasRiskAlert = useMemo(() => riskItems.some((item) => item.label !== '风险提示'), [riskItems]);

  const watchItems = useMemo(() => {
    const items: Array<{ id: string; label: string; sub: string; kind: WatchKind }> = [];
    for (const row of summary?.chains || []) {
      const id = watchId('chain', row);
      if (watchIds.has(id)) items.push({ id, label: textFrom(row, 'name'), sub: money(numberFrom(row, 'tvlUsd')), kind: 'chain' });
    }
    for (const row of summary?.protocols || []) {
      const id = watchId('protocol', row);
      if (watchIds.has(id)) items.push({ id, label: textFrom(row, 'name'), sub: `${textFrom(row, 'category')} · ${money(numberFrom(row, 'tvlUsd'))}`, kind: 'protocol' });
    }
    for (const row of summary?.yieldPools || []) {
      const id = watchId('yield', row);
      if (watchIds.has(id)) items.push({ id, label: textFrom(row, 'project'), sub: `${textFrom(row, 'chain')} · ${pct(numberFrom(row, 'apy'))}`, kind: 'yield' });
    }
    return items;
  }, [summary?.chains, summary?.protocols, summary?.yieldPools, watchIds]);

  function protocolFeeEfficiency(row: DataRow): number {
    const tvl = numberFrom(row, 'tvlUsd') || 0;
    if (tvl <= 0) return 0;
    const fee = feesByProtocol.get(protocolIdentity(row)) || feesByProtocol.get(textFrom(row, 'name', '').toLowerCase()) || 0;
    return (fee / tvl) * 365 * 100;
  }

  function toggleWatch(kind: WatchKind, row: DataRow) {
    const id = watchId(kind, row);
    setWatchIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  if (summary?.status === 'partial') {
    return (
      <div className="h-full w-full min-w-0 overflow-auto p-6">
        <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-normal text-white"><Network className="h-6 w-6 text-cyan-300" />A 股基本面与资金流</h1>
            <div className="mt-1 text-xs text-gray-500">研究页数据域已切换为 A 股 PostgreSQL 只读数据</div>
          </div>
          <button type="button" onClick={() => void loadSummary()} className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-crypto-border bg-crypto-card px-3 text-sm font-semibold text-gray-200 hover:border-cyan-400/45 hover:text-cyan-100">{loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}刷新</button>
        </header>
        <div className="rounded-xl border border-amber-500/25 bg-crypto-card p-8">
          <div className="text-base font-semibold text-amber-200">A 股基本面明细适配中</div>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-400">当前 PostgreSQL 已登记股东、资金流和基本面数据域，但尚未形成可验证的冻结快照。明细适配完成前保持诚实空态，不用模拟数据填充。</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full w-full min-w-0 overflow-auto p-6">
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-normal text-white">
            <Network className="h-6 w-6 text-cyan-300" />
            A 股基本面与资金流
          </h1>
          <div className="mt-1 text-xs text-gray-500">PostgreSQL 股东、资金流和基本面数据 · 只读研究看板</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex h-10 items-center gap-2 rounded-xl border border-crypto-border bg-crypto-card/85 px-3 text-xs font-semibold text-gray-300">
            <Network className="h-4 w-4 text-cyan-300" />
            A 股全市场
          </span>
          <span className={clsx('inline-flex h-10 items-center gap-2 rounded-xl border px-3 text-xs font-semibold', statusTone(summary?.status || 'loading'))}>
            <span className="live-dot h-2 w-2 rounded-full bg-current" />
            A股数据 {statusLabel(summary?.status || 'loading')}
          </span>
          <span className="inline-flex h-10 items-center rounded-xl border border-crypto-border bg-crypto-card/85 px-3 text-xs tabular-nums text-gray-500" title="页面每 5 分钟自动刷新一次链上数据">
            更新于 {dateTime(summary?.asOf)} · 自动刷新 {Math.floor(refreshCountdown / 60)}:{String(refreshCountdown % 60).padStart(2, '0')}
          </span>
          <button
            type="button"
            onClick={() => void loadSummary()}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-crypto-border bg-crypto-card px-3 text-sm font-semibold text-gray-200 hover:border-cyan-400/45 hover:text-cyan-100"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            刷新
          </button>
        </div>
      </header>

      {error && (
        <div className="mb-4 rounded-lg border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {!summary && loading ? (
        <div className="flex min-h-[420px] items-center justify-center rounded-xl border border-crypto-border bg-crypto-card/70 text-sm text-gray-500">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          读取链上研究数据…
        </div>
      ) : summary ? (
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="总锁仓量" value={money(kpis?.totalTvlUsd)} countValue={kpis?.totalTvlUsd ?? null} countFormat={money} sub={`覆盖 ${kpis?.chainCount || 0} 条公链的锁仓资金`} tone="liquidity" />
            <MetricCard label="稳定币供给" value={money(kpis?.totalStablecoinsUsd)} countValue={kpis?.totalStablecoinsUsd ?? null} countFormat={money} sub={`${summary.stablecoins.length} 种链上美元稳定币`} tone="stable" />
            <MetricCard label="24H 协议费用" value={money(kpis?.fee24hUsd)} countValue={kpis?.fee24hUsd ?? null} countFormat={money} sub={`${summary.fees.length} 个协议一天收取的费用`} tone="fee" />
            <MetricCard label="稳定币收益池" value={String(kpis?.stableYieldPoolCount || 0)} countValue={kpis?.stableYieldPoolCount ?? null} countFormat={(value) => String(Math.round(value))} sub="可研究的稳定币理财池" tone="yield" />
            <MetricCard label="最大公链" value={kpis?.topChain?.name || '--'} sub={money(kpis?.topChain?.tvlUsd)} tone="chain" />
            <MetricCard label="最大协议" value={kpis?.topProtocol?.name || '--'} sub={money(kpis?.topProtocol?.tvlUsd)} tone="protocol" />
          </div>

          <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
            <div className="min-w-0 space-y-4">
              <div className="rounded-xl border border-crypto-border bg-crypto-card/85 px-3 py-2">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex flex-wrap gap-2">
                    {tabs.map((tab) => {
                      const Icon = tab.icon;
                      return (
                        <button
                          key={tab.id}
                          type="button"
                          aria-pressed={activeTab === tab.id}
                          onClick={() => setActiveTab(tab.id)}
                          className={clsx(
                            'inline-flex h-9 items-center gap-2 rounded-lg border px-3 text-sm font-medium transition-colors',
                            activeTab === tab.id
                              ? SELECTED_SEGMENT_BORDER_CLASS
                              : 'border-crypto-border bg-crypto-bg/70 text-gray-400 hover:border-gray-600 hover:text-gray-200'
                          )}
                        >
                          <Icon className="h-4 w-4" />
                          {tab.label}
                        </button>
                      );
                    })}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-crypto-border bg-crypto-bg/70 px-2.5 text-xs font-semibold text-gray-300">
                      <Info className="h-3.5 w-3.5 text-cyan-300" />
                      链上术语
                    </span>
                    <GlossaryChip label="TVL" tone="cyan" text="Total Value Locked，总锁仓量，表示资金仍在链上合约或协议中的美元价值。" />
                    <GlossaryChip label="APY" tone="emerald" text="年化收益率，只是历史或当前收益口径，不等于承诺收益。" />
                    <GlossaryChip label="无常损失" tone="red" text="做市或流动性池中，两种资产价格相对变化造成的潜在损失。" />
                    <GlossaryChip label="费用/TVL" tone="amber" text="用协议费用除以锁仓量，粗略观察资金使用效率。" />
                  </div>
                </div>
              </div>

              {activeTab === 'overview' && (
                <>
                  <Panel
                    title="资金流水线 · 链 → 协议"
                    description="锁仓资金从公链流向头部协议的分布管线，悬停可看具体金额，连线越粗代表资金越大"
                    icon={<Activity className="h-4 w-4 text-cyan-300" />}
                    className="border-cyan-400/15"
                    action={<span className="text-[11px] font-medium text-gray-500">按锁仓量取前 8 条链</span>}
                  >
                    <CapitalFlowPipeline chains={summary.chains} protocols={summary.protocols} height={360} />
                  </Panel>
                  <Panel
                    title="链锁仓量 Top 10"
                    description="当前锁仓量最大的十条公链，条越长代表锁定资金越多"
                    icon={<BarChart3 className="h-4 w-4 text-cyan-300" />}
                    className="border-cyan-400/15"
                    action={<span className="text-[11px] font-medium text-gray-500">按当前 TVL 排序</span>}
                  >
                    <ChainTvlBarChart rows={summary.chains} height={300} />
                  </Panel>
                  <div className="grid grid-cols-1 gap-5 2xl:grid-cols-2">
                  <Panel
                    title="综合总览 · 链锁仓量"
                    description="资金存在哪条链上，锁仓量越大代表这条链的生态越活跃"
                    icon={<Network className="h-4 w-4 text-cyan-300" />}
                    className="border-cyan-400/15"
                  >
                    {summary.chains.length ? (
                      <div className="max-h-[430px] overflow-auto">
                        <table className="w-full min-w-[540px] text-left text-sm">
                          <thead className="sticky top-0 bg-crypto-card text-xs text-gray-500">
                            <tr>
                              <th className="py-2 pr-3 font-medium">链</th>
                              <th className="py-2 pr-3 text-right font-medium" title="该链上所有协议锁定的资产总价值（美元）">锁仓量</th>
                              <th className="py-2 pr-3 font-medium">代币</th>
                              <th className="py-2 text-right font-medium">观察</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-crypto-border/70">
                            {summary.chains.map((row, rowIndex) => {
                              const id = watchId('chain', row);
                              const tvl = numberFrom(row, 'tvlUsd');
                              return (
                                <tr key={textFrom(row, 'name')} className="row-enter text-gray-300" style={{ animationDelay: `${Math.min(rowIndex * 30, 300)}ms` }}>
                                  <td className="py-2 pr-3 font-medium text-gray-100">{textFrom(row, 'name')}</td>
                                  <td className="py-2 pr-3 text-right">
                                    <div className="font-semibold tabular-nums text-cyan-200">{money(tvl)}</div>
                                    <ScaleBar value={tvl} max={maxChainTvl} />
                                  </td>
                                  <td className="py-2 pr-3">{textFrom(row, 'tokenSymbol')}</td>
                                  <td className="py-2 text-right">
                                    <WatchButton active={watchIds.has(id)} onClick={() => toggleWatch('chain', row)} label="加入观察清单" />
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <EmptyPanel text={emptyText} />
                    )}
                  </Panel>

                  <Panel
                    title="稳定币供给"
                    description="链上流通的美元稳定币规模，锚定状态提醒哪些币价格偏离了 1 美元"
                    icon={<CircleDollarSign className="h-4 w-4 text-emerald-300" />}
                    className="border-emerald-400/15"
                  >
                    {summary.stablecoins.length ? (
                      <div className="max-h-[430px] overflow-auto">
                        <table className="w-full min-w-[560px] text-left text-sm">
                          <thead className="sticky top-0 bg-crypto-card text-xs text-gray-500">
                            <tr>
                              <th className="py-2 pr-3 font-medium">稳定币</th>
                              <th className="py-2 pr-3 text-right font-medium">供给</th>
                              <th className="py-2 pr-3 font-medium" title="稳定币价格是否贴近 1 美元：偏离可能是脱锚风险信号">锚定状态</th>
                              <th className="py-2 text-right font-medium">覆盖链数</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-crypto-border/70">
                            {summary.stablecoins.map((row) => {
                              const supply = numberFrom(row, 'supplyUsd');
                              const risk = pegRisk(row);
                              return (
                                <tr key={textFrom(row, 'symbol')} className="text-gray-300">
                                  <td className="py-2 pr-3">
                                    <div className="font-medium text-gray-100">{textFrom(row, 'symbol')}</div>
                                    <div className="text-xs text-gray-500">{textFrom(row, 'name')}</div>
                                  </td>
                                  <td className="py-2 pr-3 text-right">
                                    <div className="font-semibold tabular-nums text-emerald-200">{money(supply)}</div>
                                    <ScaleBar value={supply} max={maxStableSupply} tone="bg-emerald-400/70" />
                                  </td>
                                  <td className={clsx('py-2 pr-3 font-medium', risk.tone)}>{risk.label}</td>
                                  <td className="py-2 text-right tabular-nums">{textFrom(row, 'chainCount')}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <EmptyPanel text={emptyText} />
                    )}
                  </Panel>
                  </div>
                </>
              )}

              {activeTab === 'protocols' && (
                <div className="grid grid-cols-1 gap-5 2xl:grid-cols-[1.2fr_0.8fr]">
              <Panel
                title="协议研究 · 协议锁仓量"
                description="每个协议锁定了多少资金、最近资金是在流入还是流出"
                icon={<Layers3 className="h-4 w-4 text-cyan-300" />}
                className="border-cyan-400/15"
                action={
                  <div className="hidden items-center gap-1 text-xs text-gray-500 md:flex">
                    <Filter className="h-4 w-4" />
                    {protocolRows.length} / {summary.protocols.length}
                  </div>
                }
              >
                <div className="mb-3 flex flex-wrap gap-2">
                  <SearchBox value={protocolQuery} onChange={setProtocolQuery} placeholder="筛选协议、类别或链" />
                  <SelectControl value={protocolCategory} options={protocolCategories} onChange={setProtocolCategory} label="类别" />
                  <SelectControl value={protocolChain} options={protocolChains} onChange={setProtocolChain} label="链" />
                  <SelectControl value={protocolSort} options={protocolSortOptions} onChange={setProtocolSort} label="排序" />
                </div>
                {protocolRows.length ? (
                  <div className="max-h-[520px] overflow-auto">
                    <table className="w-full min-w-[820px] text-left text-sm">
                      <thead className="sticky top-0 bg-crypto-card text-xs text-gray-500">
                        <tr>
                          <th className="py-2 pr-3 font-medium">协议</th>
                          <th className="py-2 pr-3 font-medium">类别</th>
                          <th className="py-2 pr-3 font-medium">链</th>
                          <th className="py-2 pr-3 text-right font-medium" title="该协议当前锁定的资产总价值">锁仓量</th>
                          <th className="py-2 pr-3 text-right font-medium" title="相对昨天的锁仓量变化">1日变化</th>
                          <th className="py-2 pr-3 text-right font-medium" title="相对一周前的锁仓量变化">7日变化</th>
                          <th className="py-2 pr-3 text-right font-medium" title="协议年化费用 ÷ 锁仓量，粗略衡量资金的赚钱效率">费用/TVL</th>
                          <th className="py-2 text-right font-medium">观察</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-crypto-border/70">
                        {protocolRows.map((row, rowIndex) => {
                          const id = watchId('protocol', row);
                          const tvl = numberFrom(row, 'tvlUsd');
                          const change1d = numberFrom(row, 'change1d');
                          const change7d = numberFrom(row, 'change7d');
                          return (
                            <tr key={protocolIdentity(row)} className="row-enter text-gray-300" style={{ animationDelay: `${Math.min(rowIndex * 25, 300)}ms` }}>
                              <td className="py-2 pr-3">
                                <div className="font-medium text-gray-100">{textFrom(row, 'name')}</div>
                                <div className="text-xs text-gray-500">{textFrom(row, 'slug')}</div>
                              </td>
                              <td className="py-2 pr-3">{textFrom(row, 'category')}</td>
                              <td className="max-w-[170px] truncate py-2 pr-3 text-gray-400">{chainText(row)}</td>
                              <td className="py-2 pr-3 text-right">
                                <div className="font-semibold tabular-nums text-cyan-200">{money(tvl)}</div>
                                <ScaleBar value={tvl} max={maxProtocolTvl} />
                              </td>
                              <td className={clsx('py-2 pr-3 text-right font-medium tabular-nums', changeTone(change1d))}>{pct(change1d)}</td>
                              <td className={clsx('py-2 pr-3 text-right font-medium tabular-nums', changeTone(change7d))}>{pct(change7d)}</td>
                              <td className="py-2 pr-3 text-right tabular-nums text-amber-200">{pct(protocolFeeEfficiency(row))}</td>
                              <td className="py-2 text-right">
                                <WatchButton active={watchIds.has(id)} onClick={() => toggleWatch('protocol', row)} label="加入观察清单" />
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyPanel text="当前筛选条件下没有协议行" />
                )}
              </Panel>

              <Panel
                title="协议费用排行"
                description="协议过去 24 小时向用户收取的费用，反映真实使用量"
                icon={<Banknote className="h-4 w-4 text-amber-300" />}
                className="border-amber-400/15"
              >
                {summary.fees.length ? (
                  <div className="max-h-[610px] overflow-auto">
                    <table className="w-full min-w-[500px] text-left text-sm">
                      <thead className="sticky top-0 bg-crypto-card text-xs text-gray-500">
                        <tr>
                          <th className="py-2 pr-3 font-medium">协议</th>
                          <th className="py-2 pr-3 text-right font-medium">24H 费用</th>
                          <th className="py-2 pr-3 text-right font-medium">7日费用</th>
                          <th className="py-2 text-right font-medium">1日变化</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-crypto-border/70">
                        {summary.fees.map((row) => {
                          const change1d = numberFrom(row, 'change1d');
                          return (
                            <tr key={textFrom(row, 'slug', textFrom(row, 'name'))} className="text-gray-300">
                              <td className="py-2 pr-3">
                                <div className="font-medium text-gray-100">{textFrom(row, 'name')}</div>
                                <div className="text-xs text-gray-500">{textFrom(row, 'category')}</div>
                              </td>
                              <td className="py-2 pr-3 text-right tabular-nums text-amber-200">{money(numberFrom(row, 'total24hUsd'))}</td>
                              <td className="py-2 pr-3 text-right tabular-nums">{money(numberFrom(row, 'total7dUsd'))}</td>
                              <td className={clsx('py-2 text-right font-medium tabular-nums', changeTone(change1d))}>{pct(change1d)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyPanel text={emptyText} />
                )}
              </Panel>
                </div>
              )}

              {activeTab === 'yields' && (
                <div className="grid grid-cols-1 gap-5 2xl:grid-cols-[1.15fr_0.85fr]">
              <Panel
                title="收益机会 · 稳定币收益"
                description="稳定币理财池的年化收益与风险线索，收益异常偏高的池子要格外小心"
                icon={<TrendingUp className="h-4 w-4 text-emerald-300" />}
                className="border-emerald-400/15"
                action={
                  <div className="hidden items-center gap-1 text-xs text-gray-500 md:flex">
                    <ArrowUpDown className="h-4 w-4" />
                    {yieldRows.length} / {summary.yieldPools.length}
                  </div>
                }
              >
                <div className="mb-3 flex flex-wrap gap-2">
                  <SelectControl value={yieldChain} options={yieldChains} onChange={setYieldChain} label="链" />
                  <SelectControl
                    value={yieldRiskFilter}
                    options={[
                      { value: 'all', label: '全部风险' },
                      { value: 'attention', label: '优先关注' },
                      { value: 'stable', label: '低风险线索' },
                    ]}
                    onChange={setYieldRiskFilter}
                    label="风险"
                  />
                  <SelectControl value={yieldSort} options={yieldSortOptions} onChange={setYieldSort} label="排序" />
                </div>
                {yieldRows.length ? (
                  <div className="max-h-[520px] overflow-auto">
                    <table className="w-full min-w-[760px] text-left text-sm">
                      <thead className="sticky top-0 bg-crypto-card text-xs text-gray-500">
                        <tr>
                          <th className="py-2 pr-3 font-medium">收益池</th>
                          <th className="py-2 pr-3 font-medium">链</th>
                          <th className="py-2 pr-3 text-right font-medium" title="当前年化收益率，只是历史口径，不等于承诺收益">年化收益</th>
                          <th className="py-2 pr-3 text-right font-medium" title="过去 30 天的平均年化，用来判断当前收益是否异常">30日均值</th>
                          <th className="py-2 pr-3 text-right font-medium">池锁仓量</th>
                          <th className="py-2 pr-3 font-medium" title="由年化偏离、池子规模和无常损失自动判别的风险提示">风险状态</th>
                          <th className="py-2 text-right font-medium">观察</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-crypto-border/70">
                        {yieldRows.map((row, rowIndex) => {
                          const id = watchId('yield', row);
                          const tvl = numberFrom(row, 'tvlUsd');
                          const risk = yieldRisk(row);
                          return (
                            <tr key={textFrom(row, 'pool')} className="row-enter text-gray-300" style={{ animationDelay: `${Math.min(rowIndex * 25, 300)}ms` }}>
                              <td className="py-2 pr-3">
                                <div className="font-medium text-gray-100">{textFrom(row, 'project')}</div>
                                <div className="text-xs tabular-nums text-gray-500">{textFrom(row, 'symbol')}</div>
                              </td>
                              <td className="py-2 pr-3">{textFrom(row, 'chain')}</td>
                              <td className="py-2 pr-3 text-right font-semibold tabular-nums text-emerald-200">{pct(numberFrom(row, 'apy'))}</td>
                              <td className="py-2 pr-3 text-right tabular-nums">{pct(numberFrom(row, 'apyMean30d'))}</td>
                              <td className="py-2 pr-3 text-right">
                                <div className="tabular-nums">{money(tvl)}</div>
                                <ScaleBar value={tvl} max={maxYieldTvl} tone="bg-emerald-400/70" />
                              </td>
                              <td className={clsx('py-2 pr-3 font-medium', risk.tone)}>{risk.label}</td>
                              <td className="py-2 text-right">
                                <WatchButton active={watchIds.has(id)} onClick={() => toggleWatch('yield', row)} label="加入观察清单" />
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyPanel text="当前筛选条件下没有收益池" />
                )}
              </Panel>

              <Panel
                title="稳定币链分布"
                description="各条链上沉淀了多少稳定币，观察美元资金停在哪些生态"
                icon={<Blocks className="h-4 w-4 text-teal-300" />}
                className="border-teal-400/15"
              >
                {summary.stablecoinChains.length ? (
                  <div className="max-h-[610px] overflow-auto">
                    <table className="w-full min-w-[420px] text-left text-sm">
                      <thead className="sticky top-0 bg-crypto-card text-xs text-gray-500">
                        <tr>
                          <th className="py-2 pr-3 font-medium">链</th>
                          <th className="py-2 text-right font-medium">供给</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-crypto-border/70">
                        {summary.stablecoinChains.map((row) => {
                          const supply = numberFrom(row, 'supplyUsd');
                          return (
                            <tr key={textFrom(row, 'name')} className="text-gray-300">
                              <td className="py-2 pr-3 font-medium text-gray-100">{textFrom(row, 'name')}</td>
                              <td className="py-2 text-right tabular-nums text-emerald-200">
                                <div>{money(supply)}</div>
                                <ScaleBar value={supply} max={maxStableSupply} tone="bg-emerald-400/70" />
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyPanel text={emptyText} />
                )}
              </Panel>
                </div>
              )}
            </div>

            <aside className="space-y-4 xl:sticky xl:top-6">
              <Panel
                title="数据源健康"
                description="DeFiLlama 各数据集的可用状态，异常时页面数据可能不完整"
                icon={<DatabaseZap className="h-4 w-4 text-cyan-300" />}
                className="border-cyan-400/15"
                action={
                  <span className={clsx('rounded-md border px-2 py-0.5 text-[11px] font-semibold', statusTone(summary.status || 'loading'))}>
                    {summary.warnings.length ? `${summary.warnings.length} 条提醒` : '全部正常'}
                  </span>
                }
              >
                <div className="space-y-2">
                  {endpointStatus.map(([name, status]) => (
                    <div key={name} className="flex items-center justify-between gap-3 rounded-lg border border-crypto-border/70 bg-crypto-bg/55 px-2.5 py-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <span
                          className={clsx(
                            'h-2 w-2 shrink-0 rounded-full',
                            status === 'ready' ? 'bg-emerald-400' : status === 'error' ? 'bg-red-400' : 'bg-amber-400'
                          )}
                        />
                        <span className="truncate text-sm text-gray-300">{sourceLabel(name)}</span>
                      </div>
                      <span className={clsx('shrink-0 rounded-md border px-2 py-0.5 text-[11px] font-semibold', statusTone(status))}>
                        {statusLabel(status)}
                      </span>
                    </div>
                  ))}
                </div>
                {summary.warnings.length ? (
                  <div className="mt-3 space-y-1 rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-100/80">
                    {summary.warnings.map((warning) => (
                      <div key={warning}>{localizeWarning(warning)}</div>
                    ))}
                  </div>
                ) : (
                  <div className="mt-3 flex items-center gap-2 text-xs text-emerald-200">
                    <CheckCircle2 className="h-4 w-4" />
                    全部正常
                  </div>
                )}
              </Panel>

              <Panel
                title="风险提示"
                description="从当前数据里自动识别的异常信号，只作研究提醒"
                icon={<ShieldAlert className={clsx('h-4 w-4', hasRiskAlert ? 'text-red-300' : 'text-emerald-300')} />}
                className={hasRiskAlert ? 'border-red-500/35 bg-red-500/5' : 'border-emerald-500/20'}
                action={
                  <span
                    className={clsx(
                      'rounded-md border px-2 py-0.5 text-[11px] font-semibold',
                      hasRiskAlert ? 'border-red-500/30 bg-red-500/10 text-red-200' : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
                    )}
                  >
                    {hasRiskAlert ? `${riskItems.length} 项` : '平稳'}
                  </span>
                }
              >
                <div className="space-y-2">
                  {riskItems.map((item) => (
                    <div
                      key={`${item.label}-${item.value}`}
                      className={clsx(
                        'rounded-lg border px-3 py-2',
                        item.tone.includes('red') || item.tone.includes('down')
                          ? 'border-red-500/25 bg-red-500/10'
                          : item.tone.includes('amber')
                            ? 'border-amber-500/25 bg-amber-500/10'
                            : 'border-emerald-500/20 bg-emerald-500/10'
                      )}
                    >
                      <div className="text-[11px] text-gray-500">{item.label}</div>
                      <div className={clsx('mt-1 text-sm font-semibold', item.tone)}>{item.value}</div>
                    </div>
                  ))}
                </div>
              </Panel>

              <Panel
                title="观察清单"
                description="你星标关注的链、协议与收益池，方便下次直接回来查看"
                icon={<Bookmark className="h-4 w-4 text-amber-300" />}
                className="border-amber-400/15"
                action={<span className="text-[11px] font-medium text-gray-500">{watchItems.length} 项</span>}
              >
                {watchItems.length ? (
                  <div className="max-h-[360px] space-y-2 overflow-auto">
                    {watchItems.map((item) => (
                      <div key={item.id} className="flex items-center justify-between gap-3 rounded-lg border border-crypto-border bg-crypto-bg/70 px-3 py-2">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-semibold text-gray-100">{item.label}</div>
                          <div className="truncate text-xs text-gray-500">{item.sub}</div>
                        </div>
                        <button
                          type="button"
                          onClick={() => setWatchIds((prev) => {
                            const next = new Set(prev);
                            next.delete(item.id);
                            return next;
                          })}
                          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-crypto-border bg-crypto-card text-gray-500 hover:border-red-400/45 hover:text-red-200"
                          title="移出观察清单"
                        >
                          <StarOff className="h-4 w-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyPanel text="从链、协议或收益池右侧星标加入观察清单" />
                )}
              </Panel>
            </aside>
          </div>

          <Panel title="链上研究边界" icon={<AlertTriangle className="h-4 w-4 text-amber-300" />}>
            <div className="grid grid-cols-1 gap-3 text-xs text-gray-500 md:grid-cols-3">
              <div className="rounded-lg border border-crypto-border bg-crypto-bg/60 px-3 py-2">
                <div className="mb-1 flex items-center gap-1.5 font-semibold text-gray-300">
                  <Activity className="h-3.5 w-3.5 text-cyan-300" />
                  只读研究
                </div>
                不创建策略、不启动同步任务、不连接真实账户。
              </div>
              <div className="rounded-lg border border-crypto-border bg-crypto-bg/60 px-3 py-2">
                <div className="mb-1 flex items-center gap-1.5 font-semibold text-gray-300">
                  <Gauge className="h-3.5 w-3.5 text-emerald-300" />
                  真实数据
                </div>
                所有表格只使用 DeFiLlama 返回行或明确空态。
              </div>
              <div className="rounded-lg border border-crypto-border bg-crypto-bg/60 px-3 py-2">
                <div className="mb-1 flex items-center gap-1.5 font-semibold text-gray-300">
                  <ShieldAlert className="h-3.5 w-3.5 text-amber-300" />
                  非建议
                </div>
                收益池和协议排行只是研究线索，不是交易建议。
              </div>
            </div>
          </Panel>
        </div>
      ) : (
        <EmptyPanel text={emptyText} />
      )}
    </div>
  );
}
