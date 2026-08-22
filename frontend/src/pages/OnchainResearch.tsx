import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Activity,
  AlertTriangle,
  ArrowUpDown,
  Banknote,
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

type TabId = 'overview' | 'protocols' | 'yields';
type ProtocolSort = 'tvl' | 'change7d' | 'feeEfficiency';
type YieldSort = 'apy' | 'tvl' | 'risk';
type WatchKind = 'chain' | 'protocol' | 'yield';
type DataRow = Record<string, unknown>;

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

function Panel({
  title,
  icon,
  action,
  children,
  className,
}: {
  title: string;
  icon: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={clsx('min-w-0 overflow-hidden rounded-lg border border-crypto-border bg-crypto-card/80 p-4', className)}>
      <div className="mb-3 flex min-w-0 items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2 text-sm font-semibold text-gray-100">
          {icon}
          <span className="truncate">{title}</span>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

type MetricTone = 'liquidity' | 'stable' | 'fee' | 'yield' | 'chain' | 'protocol';

const metricToneStyles: Record<MetricTone, { border: string; sub: string; value: string; bar: string }> = {
  liquidity: {
    border: 'border-cyan-400/20',
    sub: 'text-cyan-100/65',
    value: 'text-cyan-100',
    bar: 'bg-cyan-400/70',
  },
  stable: {
    border: 'border-emerald-400/20',
    sub: 'text-emerald-100/65',
    value: 'text-emerald-200',
    bar: 'bg-emerald-400/70',
  },
  fee: {
    border: 'border-amber-400/25',
    sub: 'text-amber-100/65',
    value: 'text-amber-200',
    bar: 'bg-amber-400/75',
  },
  yield: {
    border: 'border-lime-400/20',
    sub: 'text-lime-100/65',
    value: 'text-lime-200',
    bar: 'bg-lime-400/70',
  },
  chain: {
    border: 'border-sky-400/20',
    sub: 'text-sky-100/65',
    value: 'text-sky-200',
    bar: 'bg-sky-400/70',
  },
  protocol: {
    border: 'border-indigo-400/20',
    sub: 'text-indigo-100/65',
    value: 'text-indigo-200',
    bar: 'bg-indigo-400/70',
  },
};

function MetricCard({
  label,
  value,
  sub,
  tone = 'liquidity',
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: MetricTone;
}) {
  const styles = metricToneStyles[tone];
  return (
    <div className={clsx('relative min-h-[112px] overflow-hidden rounded-lg border bg-crypto-card/85 p-4', styles.border)}>
      <div className={clsx('absolute inset-x-0 bottom-0 h-0.5', styles.bar)} />
      <div className="min-w-0">
        <div className="text-xs font-medium text-gray-500">{label}</div>
        <div className={clsx('mt-2 truncate text-xl font-bold leading-7 tracking-normal', styles.value)}>{value}</div>
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
          ? 'border-amber-400/45 bg-amber-500/15 text-amber-100'
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

  const loadSummary = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setSummary(await onchainApi.getSummary());
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || '链上数据加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  const kpis = summary?.kpis;
  const endpointStatus = useMemo(() => {
    if (!summary) return [];
    return Object.entries(summary.sourceStatus || {});
  }, [summary]);
  const emptyText = summary?.emptyReason || '等待 DeFiLlama 返回真实链上数据';

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
      items.push({ label: '数据源', value: `${failingSources} 组非正常`, tone: 'text-amber-200' });
    }
    const pegRisks = (summary?.stablecoins || []).filter((row) => pegRisk(row).label === '锚定偏离');
    if (pegRisks.length) {
      items.push({ label: '稳定币', value: `${pegRisks.length} 个锚定偏离`, tone: 'text-amber-200' });
    }
    const highYield = (summary?.yieldPools || []).filter((row) => yieldRisk(row).score >= 2);
    if (highYield.length) {
      items.push({ label: '收益池', value: `${highYield.length} 个高风险线索`, tone: 'text-red-200' });
    }
    const fallingProtocols = (summary?.protocols || []).filter((row) => (numberFrom(row, 'change7d') || 0) <= -10);
    if (fallingProtocols.length) {
      items.push({ label: '协议', value: `${fallingProtocols.length} 个7日回落超10%`, tone: 'text-down' });
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

  return (
    <div className="h-full w-full min-w-0 overflow-auto p-6">
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-normal text-white">
            <Network className="h-6 w-6 text-cyan-300" />
            链上数据
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card/85 px-3 text-xs font-semibold text-gray-300">
            <Network className="h-4 w-4 text-cyan-300" />
            全链视图
          </span>
          <span className={clsx('inline-flex h-10 items-center gap-2 rounded-lg border px-3 text-xs font-semibold', statusTone(summary?.status || 'loading'))}>
            <span className="h-2 w-2 rounded-full bg-current" />
            DeFiLlama {statusLabel(summary?.status || 'loading')}
          </span>
          <span className="inline-flex h-10 items-center rounded-lg border border-crypto-border bg-crypto-card/85 px-3 text-xs text-gray-500">
            更新于 {dateTime(summary?.asOf)}
          </span>
          <button
            type="button"
            onClick={() => void loadSummary()}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-3 text-sm font-semibold text-gray-200 hover:border-cyan-400/45 hover:text-cyan-100"
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
        <div className="flex min-h-[420px] items-center justify-center rounded-lg border border-crypto-border bg-crypto-card/70 text-sm text-gray-500">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          读取链上研究数据…
        </div>
      ) : summary ? (
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="总锁仓量" value={money(kpis?.totalTvlUsd)} sub={`${kpis?.chainCount || 0} 条链`} tone="liquidity" />
            <MetricCard label="稳定币供给" value={money(kpis?.totalStablecoinsUsd)} sub={`${summary.stablecoins.length} 种稳定币`} tone="stable" />
            <MetricCard label="24H 协议费用" value={money(kpis?.fee24hUsd)} sub={`${summary.fees.length} 个协议`} tone="fee" />
            <MetricCard label="稳定币收益池" value={String(kpis?.stableYieldPoolCount || 0)} sub="DeFiLlama 收益池" tone="yield" />
            <MetricCard label="最大公链" value={kpis?.topChain?.name || '--'} sub={money(kpis?.topChain?.tvlUsd)} tone="chain" />
            <MetricCard label="最大协议" value={kpis?.topProtocol?.name || '--'} sub={money(kpis?.topProtocol?.tvlUsd)} tone="protocol" />
          </div>

          <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
            <div className="min-w-0 space-y-4">
              <div className="rounded-lg border border-cyan-400/15 bg-crypto-card/85 px-3 py-2">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex flex-wrap gap-2">
                    {tabs.map((tab) => {
                      const Icon = tab.icon;
                      return (
                        <button
                          key={tab.id}
                          type="button"
                          onClick={() => setActiveTab(tab.id)}
                          className={clsx(
                            'inline-flex h-9 items-center gap-2 rounded-lg border px-3 text-sm font-medium transition-colors',
                            activeTab === tab.id
                              ? 'border-cyan-400/55 bg-cyan-500/15 text-cyan-100'
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
                <div className="grid grid-cols-1 gap-5 2xl:grid-cols-2">
                  <Panel title="综合总览 · 链锁仓量" icon={<Network className="h-4 w-4 text-cyan-300" />} className="border-cyan-400/15">
                    {summary.chains.length ? (
                      <div className="max-h-[430px] overflow-auto">
                        <table className="w-full min-w-[540px] text-left text-sm">
                          <thead className="sticky top-0 bg-crypto-card text-xs text-gray-500">
                            <tr>
                              <th className="py-2 pr-3 font-medium">链</th>
                              <th className="py-2 pr-3 font-medium">锁仓量</th>
                              <th className="py-2 pr-3 font-medium">代币</th>
                              <th className="py-2 pr-3 font-medium">链编号</th>
                              <th className="py-2 text-right font-medium">观察</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-crypto-border/70">
                            {summary.chains.map((row) => {
                              const id = watchId('chain', row);
                              const tvl = numberFrom(row, 'tvlUsd');
                              return (
                                <tr key={textFrom(row, 'name')} className="text-gray-300">
                                  <td className="py-2 pr-3 font-medium text-gray-100">{textFrom(row, 'name')}</td>
                                  <td className="py-2 pr-3">
                                    <div className="font-semibold text-cyan-200">{money(tvl)}</div>
                                    <ScaleBar value={tvl} max={maxChainTvl} />
                                  </td>
                                  <td className="py-2 pr-3">{textFrom(row, 'tokenSymbol')}</td>
                                  <td className="py-2 pr-3 text-gray-500">{textFrom(row, 'chainId')}</td>
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

                  <Panel title="稳定币供给" icon={<CircleDollarSign className="h-4 w-4 text-emerald-300" />} className="border-emerald-400/15">
                    {summary.stablecoins.length ? (
                      <div className="max-h-[430px] overflow-auto">
                        <table className="w-full min-w-[560px] text-left text-sm">
                          <thead className="sticky top-0 bg-crypto-card text-xs text-gray-500">
                            <tr>
                              <th className="py-2 pr-3 font-medium">稳定币</th>
                              <th className="py-2 pr-3 font-medium">供给</th>
                              <th className="py-2 pr-3 font-medium">锚定状态</th>
                              <th className="py-2 font-medium">覆盖链数</th>
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
                                  <td className="py-2 pr-3">
                                    <div className="font-semibold text-emerald-200">{money(supply)}</div>
                                    <ScaleBar value={supply} max={maxStableSupply} tone="bg-emerald-400/70" />
                                  </td>
                                  <td className={clsx('py-2 pr-3 font-medium', risk.tone)}>{risk.label}</td>
                                  <td className="py-2">{textFrom(row, 'chainCount')}</td>
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

              {activeTab === 'protocols' && (
                <div className="grid grid-cols-1 gap-5 2xl:grid-cols-[1.2fr_0.8fr]">
              <Panel
                title="协议研究 · 协议锁仓量"
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
                          <th className="py-2 pr-3 font-medium">锁仓量</th>
                          <th className="py-2 pr-3 font-medium">1日变化</th>
                          <th className="py-2 pr-3 font-medium">7日变化</th>
                          <th className="py-2 pr-3 font-medium">费用/TVL</th>
                          <th className="py-2 text-right font-medium">观察</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-crypto-border/70">
                        {protocolRows.map((row) => {
                          const id = watchId('protocol', row);
                          const tvl = numberFrom(row, 'tvlUsd');
                          const change1d = numberFrom(row, 'change1d');
                          const change7d = numberFrom(row, 'change7d');
                          return (
                            <tr key={protocolIdentity(row)} className="text-gray-300">
                              <td className="py-2 pr-3">
                                <div className="font-medium text-gray-100">{textFrom(row, 'name')}</div>
                                <div className="text-xs text-gray-500">{textFrom(row, 'slug')}</div>
                              </td>
                              <td className="py-2 pr-3">{textFrom(row, 'category')}</td>
                              <td className="max-w-[170px] truncate py-2 pr-3 text-gray-400">{chainText(row)}</td>
                              <td className="py-2 pr-3">
                                <div className="font-semibold text-cyan-200">{money(tvl)}</div>
                                <ScaleBar value={tvl} max={maxProtocolTvl} />
                              </td>
                              <td className={clsx('py-2 pr-3 font-medium', changeTone(change1d))}>{pct(change1d)}</td>
                              <td className={clsx('py-2 pr-3 font-medium', changeTone(change7d))}>{pct(change7d)}</td>
                              <td className="py-2 pr-3 text-amber-200">{pct(protocolFeeEfficiency(row))}</td>
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

              <Panel title="协议费用排行" icon={<Banknote className="h-4 w-4 text-amber-300" />} className="border-amber-400/15">
                {summary.fees.length ? (
                  <div className="max-h-[610px] overflow-auto">
                    <table className="w-full min-w-[500px] text-left text-sm">
                      <thead className="sticky top-0 bg-crypto-card text-xs text-gray-500">
                        <tr>
                          <th className="py-2 pr-3 font-medium">协议</th>
                          <th className="py-2 pr-3 font-medium">24H 费用</th>
                          <th className="py-2 pr-3 font-medium">7日费用</th>
                          <th className="py-2 font-medium">1日变化</th>
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
                              <td className="py-2 pr-3 text-amber-200">{money(numberFrom(row, 'total24hUsd'))}</td>
                              <td className="py-2 pr-3">{money(numberFrom(row, 'total7dUsd'))}</td>
                              <td className={clsx('py-2 font-medium', changeTone(change1d))}>{pct(change1d)}</td>
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
                          <th className="py-2 pr-3 font-medium">年化收益</th>
                          <th className="py-2 pr-3 font-medium">30日均值</th>
                          <th className="py-2 pr-3 font-medium">池锁仓量</th>
                          <th className="py-2 pr-3 font-medium">风险状态</th>
                          <th className="py-2 text-right font-medium">观察</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-crypto-border/70">
                        {yieldRows.map((row) => {
                          const id = watchId('yield', row);
                          const tvl = numberFrom(row, 'tvlUsd');
                          const risk = yieldRisk(row);
                          return (
                            <tr key={textFrom(row, 'pool')} className="text-gray-300">
                              <td className="py-2 pr-3">
                                <div className="font-medium text-gray-100">{textFrom(row, 'project')}</div>
                                <div className="text-xs text-gray-500">{textFrom(row, 'symbol')}</div>
                              </td>
                              <td className="py-2 pr-3">{textFrom(row, 'chain')}</td>
                              <td className="py-2 pr-3 text-emerald-200">{pct(numberFrom(row, 'apy'))}</td>
                              <td className="py-2 pr-3">{pct(numberFrom(row, 'apyMean30d'))}</td>
                              <td className="py-2 pr-3">
                                <div>{money(tvl)}</div>
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

              <Panel title="稳定币链分布" icon={<Blocks className="h-4 w-4 text-teal-300" />} className="border-teal-400/15">
                {summary.stablecoinChains.length ? (
                  <div className="max-h-[610px] overflow-auto">
                    <table className="w-full min-w-[420px] text-left text-sm">
                      <thead className="sticky top-0 bg-crypto-card text-xs text-gray-500">
                        <tr>
                          <th className="py-2 pr-3 font-medium">链</th>
                          <th className="py-2 font-medium">供给</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-crypto-border/70">
                        {summary.stablecoinChains.map((row) => {
                          const supply = numberFrom(row, 'supplyUsd');
                          return (
                            <tr key={textFrom(row, 'name')} className="text-gray-300">
                              <td className="py-2 pr-3 font-medium text-gray-100">{textFrom(row, 'name')}</td>
                              <td className="py-2 text-emerald-200">
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
