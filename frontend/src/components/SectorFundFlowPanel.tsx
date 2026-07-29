import { useEffect, useMemo, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import clsx from 'clsx';
import { StatusBadge } from '@bitpro/ui';
import { Flame, Layers3 } from 'lucide-react';
import { getHotConceptLeaders, getSectorFundFlow } from '../api/client';
import type { ConceptLeaderStock, SectorFundFlowItem, SectorFundFlowResponse } from '../types';
import { formatFreshnessTime } from '../utils/dataFreshness';
import { marketToneClass } from '../utils/marketColors';
import { formatSymbolLabel } from '../utils/symbolDisplay';

const formatYi = (value?: number | null) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
  const amount = Number(value);
  const abs = Math.abs(amount);
  const digits = abs >= 10 ? 2 : abs >= 1 ? 2 : 2;
  return `${amount.toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: 2,
  })}亿`;
};

const Pct = ({ value }: { value?: number | null }) => (
  <span className={clsx('tabular-nums', marketToneClass(value, 'text-gray-500'))}>
    {value === null || value === undefined
      ? '--'
      : `${value >= 0 ? '+' : ''}${Number(value).toFixed(2)}%`}
  </span>
);

function buildSankeyOption(flow: SectorFundFlowResponse | null) {
  if (!flow) return null;
  const outflows = flow.outflows.slice(0, 12);
  const inflows = flow.inflows.slice(0, 12);
  if (!outflows.length && !inflows.length) return null;

  const amountByNode = new Map<string, number>();
  outflows.forEach((item) => amountByNode.set(`出·${item.name}`, item.net_inflow_yi));
  inflows.forEach((item) => amountByNode.set(`入·${item.name}`, item.net_inflow_yi));

  const nodes = [
    ...outflows.map((item) => ({
      name: `出·${item.name}`,
      value: Math.abs(item.net_inflow_yi),
      itemStyle: { color: '#00C853' },
      label: { color: '#86efac' },
    })),
    ...inflows.map((item) => ({
      name: `入·${item.name}`,
      value: Math.abs(item.net_inflow_yi),
      itemStyle: { color: '#FF1744' },
      label: { color: '#fca5a5' },
    })),
  ];

  const inflowTotal = inflows.reduce((sum, item) => sum + Math.max(item.net_inflow_yi, 0), 0) || 1;
  const links: Array<{ source: string; target: string; value: number }> = [];
  outflows.forEach((out) => {
    const magnitude = Math.abs(out.net_inflow_yi);
    inflows.forEach((inn) => {
      const share = Math.max(inn.net_inflow_yi, 0) / inflowTotal;
      const value = Number((magnitude * share).toFixed(3));
      if (value <= 0) return;
      links.push({
        source: `出·${out.name}`,
        target: `入·${inn.name}`,
        value,
      });
    });
  });

  const nodeLabel = (name?: string) => {
    const raw = String(name || '');
    const sector = raw.replace(/^[出入]·/, '');
    const amount = amountByNode.get(raw);
    if (amount === undefined || amount === null || Number.isNaN(Number(amount))) return sector;
    // Match reference board: outflow shows amount then name; inflow shows name then amount.
    if (raw.startsWith('出·')) return `${formatYi(Math.abs(amount))} ${sector}`;
    return `${sector} ${formatYi(Math.abs(amount))}`;
  };

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: '#0f172a',
      borderColor: '#334155',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: (params: { dataType?: string; name?: string; value?: number; data?: { source?: string; target?: string; value?: number } }) => {
        if (params.dataType === 'edge' && params.data) {
          return `${String(params.data.source || '').replace(/^出·/, '')} → ${String(params.data.target || '').replace(/^入·/, '')}<br/>分摊连线 ${params.data.value} 亿<br/><span style="color:#94a3b8">连线为按流入权重分摊，非真实板块迁移</span>`;
        }
        const raw = String(params.name || '');
        const amount = amountByNode.get(raw);
        const side = raw.startsWith('出·') ? '净流出' : '净流入';
        return `${raw.replace(/^[出入]·/, '')}<br/>${side} ${formatYi(amount == null ? null : Math.abs(amount))}`;
      },
    },
    series: [
      {
        type: 'sankey',
        orient: 'horizontal',
        nodeAlign: 'justify',
        nodeGap: 10,
        nodeWidth: 14,
        layoutIterations: 0,
        emphasis: { focus: 'adjacency' },
        lineStyle: {
          color: 'gradient',
          opacity: 0.28,
          curveness: 0.5,
        },
        label: {
          fontSize: 11,
          formatter: (params: { name?: string }) => nodeLabel(params.name),
        },
        data: nodes,
        links,
      },
    ],
  };
}

export function SectorFundFlowPanel({
  onViewAll,
}: {
  onViewAll: () => void;
}) {
  const [flow, setFlow] = useState<SectorFundFlowResponse | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string>('');
  const [leaders, setLeaders] = useState<ConceptLeaderStock[]>([]);
  const [leadersBusy, setLeadersBusy] = useState(false);
  const [leadersError, setLeadersError] = useState('');

  useEffect(() => {
    let live = true;
    setLoading(true);
    getSectorFundFlow(30)
      .then((payload) => {
        if (!live) return;
        setFlow(payload);
        setError('');
        const first = payload.rankings[0]?.name || payload.inflows[0]?.name || payload.outflows[0]?.name || '';
        setSelected((current) => current || first);
      })
      .catch((reason: unknown) => {
        if (!live) return;
        setFlow(null);
        setError(reason instanceof Error ? reason.message : '板块资金流加载失败');
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!selected) {
      setLeaders([]);
      return;
    }
    let live = true;
    setLeadersBusy(true);
    setLeadersError('');
    getHotConceptLeaders({ name: selected, limit: 12 })
      .then((rows) => {
        if (!live) return;
        setLeaders(rows);
      })
      .catch((reason: unknown) => {
        if (!live) return;
        setLeaders([]);
        setLeadersError(reason instanceof Error ? reason.message : '龙头股加载失败');
      })
      .finally(() => {
        if (live) setLeadersBusy(false);
      });
    return () => {
      live = false;
    };
  }, [selected]);

  const sankeyOption = useMemo(() => buildSankeyOption(flow), [flow]);
  const rankings = flow?.rankings ?? [];

  const selectSector = (item: SectorFundFlowItem) => setSelected(item.name);

  return (
    <section className="overflow-hidden rounded-lg border border-crypto-border bg-crypto-card" data-testid="sector-fund-flow">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-4 py-3">
        <div className="flex items-center gap-2">
          <Flame className="h-4 w-4 text-orange-400" />
          <div>
            <h2 className="text-base font-black text-white">板块资金流向</h2>
            <p className="mt-0.5 text-[11px] text-gray-500">
              左流出 / 右流入 · TOP30 列表点选看龙头 · TuShare `moneyflow_ind_dc` 可作同步上游
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge
            tone={
              error
                ? 'red'
                : flow?.data_status === 'fresh'
                  ? 'green'
                  : flow?.data_status === 'empty'
                    ? 'amber'
                    : 'amber'
            }
          >
            {error
              ? '加载失败'
              : loading
                ? '读取中'
                : flow?.data_status === 'fresh'
                  ? '缓存可用'
                  : flow?.data_status === 'empty'
                    ? '暂无资金流'
                    : '缓存陈旧'}
          </StatusBadge>
          <button
            type="button"
            onClick={onViewAll}
            className="text-sm font-bold text-blue-400 transition-colors hover:text-blue-300"
          >
            查看全部
          </button>
        </div>
      </div>

      <div className="grid gap-4 p-4 xl:grid-cols-[1.35fr_0.9fr_0.95fr]">
        <div className="min-h-[360px] rounded-lg border border-crypto-border bg-crypto-bg/40 p-3">
          <div className="mb-2 flex items-center justify-between gap-2 text-[11px]">
            <span className="font-semibold text-down">资金流出板块</span>
            <span className="font-semibold text-up">资金流入方向</span>
          </div>
          {sankeyOption ? (
            <ReactECharts option={sankeyOption} style={{ height: 320, width: '100%' }} opts={{ renderer: 'canvas' }} />
          ) : (
            <div className="flex h-[320px] items-center justify-center text-sm text-gray-500">
              {loading ? '正在读取板块资金流…' : error || '当前没有可用的流入/流出板块缓存'}
            </div>
          )}
          <div className="mt-2 text-[10px] leading-4 text-gray-600">
            {flow?.methodology || '连线为按流入权重分摊的可视化，不是板块间真实迁移矩阵。'}
          </div>
        </div>

        <div className="min-h-[360px] overflow-hidden rounded-lg border border-crypto-border bg-crypto-bg/40">
          <div className="flex items-center justify-between border-b border-crypto-border px-3 py-2">
            <h3 className="text-sm font-bold text-gray-100">热门板块 TOP30</h3>
            <span className="text-[10px] text-gray-500">{rankings.length} / 30</span>
          </div>
          <div className="max-h-[330px] overflow-y-auto">
            {rankings.length ? (
              rankings.map((item, index) => {
                const active = item.name === selected;
                return (
                  <button
                    key={item.name}
                    type="button"
                    onClick={() => selectSector(item)}
                    className={clsx(
                      'flex w-full items-center gap-2 border-b border-white/[0.04] px-3 py-2 text-left transition-colors',
                      active ? 'bg-blue-500/10' : 'hover:bg-white/[0.03]',
                    )}
                  >
                    <span className="w-5 shrink-0 font-mono text-[10px] text-gray-600">{index + 1}</span>
                    <span className={clsx('min-w-0 flex-1 truncate text-sm font-semibold', active ? 'text-blue-200' : 'text-gray-200')}>
                      {item.name}
                    </span>
                    <Pct value={item.change_percent} />
                    <span className={clsx('w-[72px] shrink-0 text-right font-mono text-[11px] tabular-nums', marketToneClass(item.net_inflow_yi))}>
                      {formatYi(item.net_inflow_yi)}
                    </span>
                  </button>
                );
              })
            ) : (
              <div className="flex h-[300px] items-center justify-center text-sm text-gray-500">
                {loading ? '读取板块排行…' : '暂无热门板块数据'}
              </div>
            )}
          </div>
        </div>

        <div className="min-h-[360px] overflow-hidden rounded-lg border border-crypto-border bg-crypto-bg/40">
          <div className="border-b border-crypto-border px-3 py-2">
            <div className="flex items-center gap-2">
              <Layers3 className="h-4 w-4 text-blue-400" />
              <h3 className="text-sm font-bold text-gray-100">
                {selected ? `${selected} · 核心龙头` : '核心龙头股'}
              </h3>
            </div>
            <p className="mt-1 text-[10px] text-gray-500">点击左侧板块后展示成分股涨幅靠前标的</p>
          </div>
          <div className="max-h-[330px] overflow-y-auto">
            {leadersBusy ? (
              <div className="flex h-[280px] items-center justify-center text-sm text-gray-500">正在读取龙头缓存…</div>
            ) : leadersError ? (
              <div className="flex h-[280px] items-center justify-center px-4 text-center text-sm text-red-300">{leadersError}</div>
            ) : leaders.length ? (
              leaders.map((item, index) => (
                <div
                  key={`${item.code}-${index}`}
                  className="flex items-center gap-2 border-b border-white/[0.04] px-3 py-2"
                >
                  <span className="w-5 shrink-0 font-mono text-[10px] text-gray-600">{index + 1}</span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-gray-100">
                      {formatSymbolLabel(item.code, item.name)}
                    </div>
                    <div className="mt-0.5 font-mono text-[10px] text-gray-500">
                      {Number(item.price || 0).toFixed(2)} · 成交额 {formatYi((item.amount || 0) / 1e8)}
                    </div>
                  </div>
                  <Pct value={item.change_percent} />
                </div>
              ))
            ) : (
              <div className="flex h-[280px] items-center justify-center px-4 text-center text-sm text-gray-500">
                {selected
                  ? '该板块暂无龙头缓存；等同步任务写入 concept_leaders_cache 后可见'
                  : '先选择一个板块'}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="border-t border-crypto-border px-4 py-2 text-[10px] text-gray-600">
        {flow?.source_label || '来源未记录'} · 更新时间 {formatFreshnessTime(flow?.updated_at ?? null)}
      </div>
    </section>
  );
}

export default SectorFundFlowPanel;
