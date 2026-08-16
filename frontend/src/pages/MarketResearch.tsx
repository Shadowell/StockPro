import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Activity, ArrowDownRight, ArrowUpRight, CalendarDays, Database, Flame, Layers3, Newspaper, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { MetricCard } from '@bitpro/ui';
import { getMarketResearchContext, getMessageStream } from '../api/client';
import { WorkspaceTabs } from '../components/WorkspaceTabs';
import { MetricValue, OperatorPageHeader } from '../components/OperatorShell';
import { WorkspacePipelineNote } from '../components/WorkspacePipelineNote';
import { MarketTradingCalendar } from '../components/MarketTradingCalendar';
import type { MarketResearchContext, MessageStreamResponse } from '../types';
import { snapshotTypeLabel, sourceKindLabel, sourceLabel, statusLabel } from '../utils/presentation';
import { metricToneClass, type MetricTone } from '../utils/marketColors';
import { formatSymbolLabel, toPublicSymbol } from '../utils/symbolDisplay';
import { SymbolCell } from '../components/SymbolCell';
import { useSymbolNames } from '../hooks/useSymbolNames';
import { Market as StockTerminal } from './Market';

const TABS = [
  ['structure', '市场结构'],
  ['sectors', '板块轮动'],
  ['sentiment', '情绪 / 涨停'],
  ['events', '事件'],
  ['calendar', '交易日历'],
  ['stock', '个股研究'],
] as const;

type TabKey = (typeof TABS)[number][0];

const panel = 'rounded-xl border border-crypto-border bg-crypto-card';
const format = (value: unknown, digits = 2) => {
  if (value === null || value === undefined || value === '') return '--';
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toLocaleString('zh-CN', { maximumFractionDigits: digits }) : String(value);
};

/** Never render English unit tokens like `stocks` / `percent` next to values. */
function sentimentDisplay(item: { metric_code?: string; value?: unknown; unit?: string | null }) {
  const code = String(item.metric_code || '');
  const unit = String(item.unit || '').toLowerCase();
  const ratioLike = unit === 'percent' || unit === 'ratio' || code.includes('rate') || code.includes('ratio');
  const boardLike = unit === 'boards' || code === 'highest_board' || code === 'board_height';
  const display = format(item.value, ratioLike ? 2 : 0);
  let suffix = '';
  if (display !== '--') {
    if (ratioLike && (unit === 'percent' || code.includes('rate') || code === 'red_market_ratio')) suffix = '%';
    else if (boardLike) suffix = '板';
  }
  return { display, suffix };
}

const EVIDENCE_FIELD_LABELS: Record<string, string> = {
  limit_pool_members: '涨停池成员',
  limit_up_count: '涨停数',
};
const evidenceReferenceLabel = (reference: string) => {
  const parts = reference.split(':');
  const field = parts.at(-1) ?? '';
  return `封存快照 · ${EVIDENCE_FIELD_LABELS[field] ?? '市场证据'}`;
};

const HEADLINE_METRICS = [
  { code: 'rise_count', color: 'up', icon: ArrowUpRight, detail: '收盘上涨证券', cardClass: 'border-up bg-up' },
  { code: 'fall_count', color: 'down', icon: ArrowDownRight, detail: '收盘下跌证券', cardClass: 'border-down bg-down' },
  { code: 'limit_up_count', color: 'up', icon: ArrowUpRight, detail: '收盘封板证券', cardClass: 'border-up bg-up' },
  { code: 'limit_down_count', color: 'down', icon: ArrowDownRight, detail: '收盘跌停证券', cardClass: 'border-down bg-down' },
  { code: 'highest_board', color: 'amber', icon: Flame, detail: '连续涨停最高高度', cardClass: 'border-amber-500/30 bg-amber-500/[0.045]' },
  { code: 'seal_rate', color: 'blue', icon: ShieldCheck, detail: '涨停家数 / 涨停 + 炸板', cardClass: 'border-blue-500/30 bg-blue-500/[0.05]' },
] as const;

function headlineTone(code: string): MetricTone {
  if (code === 'rise_count' || code === 'limit_up_count') return 'up';
  if (code === 'fall_count' || code === 'limit_down_count') return 'down';
  if (code === 'highest_board') return 'amber';
  if (code === 'seal_rate') return 'blue';
  return 'neutral';
}

function headlineValue(code: string, value: unknown) {
  const display = format(value, code === 'seal_rate' ? 2 : 0);
  return (
    <span className={`font-sans text-[28px] font-bold leading-none tracking-[-0.04em] tabular-nums ${metricToneClass(headlineTone(code))}`}>
      {display}
      {code === 'seal_rate' && display !== '--' ? <span className="ml-0.5 text-base font-semibold tracking-normal">%</span> : null}
    </span>
  );
}

function sentimentMetricTone(code: string, value: unknown): MetricTone {
  if (code === 'limit_up_count' || code === 'rise_count' || code === 'red_ratio') return 'up';
  if (code === 'limit_down_count' || code === 'fall_count') return 'down';
  if (code === 'broken_board_count' || code === 'broken_board') return 'amber';
  if (code === 'highest_board' || code === 'board_height') return 'amber';
  if (code === 'seal_rate') return 'blue';
  if (code === 'rise_fall_ratio') {
    const n = Number(value);
    if (Number.isFinite(n)) return n >= 1 ? 'up' : 'down';
    return 'neutral';
  }
  if (code.includes('up') || code.includes('rise') || code.includes('red')) return 'up';
  if (code.includes('down') || code.includes('fall')) return 'down';
  return 'blue';
}

function sentimentMetricSurface(tone: MetricTone): string {
  if (tone === 'up') return 'border-up/25 bg-up/[0.06]';
  if (tone === 'down') return 'border-down/25 bg-down/[0.06]';
  if (tone === 'amber') return 'border-amber-400/25 bg-amber-400/[0.06]';
  if (tone === 'blue') return 'border-blue-400/25 bg-blue-400/[0.06]';
  return 'border-slate-700/80 bg-slate-950/40';
}

function StatePill({ state }: { state?: string }) {
  const available = state === 'published' || state === 'fresh';
  return <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${available ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/25 bg-amber-500/10 text-amber-300'}`}>{statusLabel(state)}</span>;
}

function Structure({ context }: { context: MarketResearchContext }) {
  const snapshot = context.snapshot;
  const metrics = context.sentiment?.metrics ?? [];
  return <div className="space-y-5">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
      {HEADLINE_METRICS.map((metric) => {
        const item = metrics.find((candidate) => candidate.metric_code === metric.code);
        const Icon = metric.icon;
        return <div key={metric.code} data-testid={`market-headline-${metric.code}`}><MetricCard label={item?.label ?? metric.detail} value={headlineValue(metric.code, item?.value)} icon={<Icon className="h-3.5 w-3.5" />} color={metric.color} detail={item?.definition ?? metric.detail} className={metric.cardClass} /></div>;
      })}
    </div>
    <section className={`${panel} p-5`}><div className="flex flex-wrap items-start justify-between gap-4"><div><h2 className="font-semibold text-white">市场数据快照</h2><p className="mt-1 text-xs text-slate-500">按交易日查看市场结构、来源与数据状态。</p></div><StatePill state={snapshot?.freshness ?? context.publication_state} /></div><dl className="mt-5 grid gap-4 text-sm sm:grid-cols-3">{[['快照状态', snapshot ? '已封存校验' : '未绑定'], ['交易日', snapshot?.trade_date ?? '--'], ['时段', snapshot?.session_label ?? snapshotTypeLabel(snapshot?.snapshot_type)]].map(([label, value]) => <div key={label} className="rounded-lg border border-crypto-border bg-crypto-bg p-3"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 tabular-nums text-slate-300">{value}</dd></div>)}</dl><div className="mt-4 flex flex-wrap gap-2">{Object.entries(snapshot?.source_map ?? {}).map(([kind, source]) => <span key={kind} className="rounded-md border border-blue-500/20 bg-blue-500/10 px-2.5 py-1 text-xs text-blue-200">{sourceKindLabel(kind)} · {sourceLabel(source)}</span>)}</div></section>
    <div className="grid gap-5 xl:grid-cols-[1.2fr_1fr]"><section className={`${panel} p-5`}><h2 className="font-semibold text-white">市场广度比较</h2><div className="mt-4 grid gap-3 sm:grid-cols-2">{(context.comparisons ?? []).map((item, index) => <div key={index} className="rounded-lg border border-crypto-border bg-crypto-bg p-3"><div className="flex items-center justify-between"><span className="text-xs font-semibold text-slate-300">{String(item.label ?? '--')}</span><StatePill state={String(item.publication_state ?? '')} /></div><div className="mt-2 text-[11px] text-slate-600">{item.reason ? String(item.reason) : `已发布 ${Object.keys((item.deltas as Record<string, unknown>) ?? {}).length} 个差值`}</div></div>)}</div></section><section className={`${panel} p-5`}><h2 className="font-semibold text-white">智能证据摘要</h2><p className="mt-1 text-xs text-slate-500">事实与推断分栏，引用封存对象。</p><div className="mt-4 space-y-3">{context.evidence_summary?.facts.map((fact) => <div key={fact.evidence_ref} className="rounded-lg border border-emerald-500/15 bg-emerald-500/5 p-3"><div className="text-sm text-slate-200">事实 · {fact.text}</div><div className="mt-1 text-[10px] text-emerald-400/70">{evidenceReferenceLabel(fact.evidence_ref)}</div></div>)}{context.evidence_summary?.inferences.map((item, index) => <div key={index} className="rounded-lg border border-amber-500/15 bg-amber-500/5 p-3"><div className="text-sm text-amber-100">推断 · {item.text}</div><div className="mt-1 text-[10px] text-amber-500/60">{item.basis}</div></div>)}</div></section></div>
  </div>;
}

function Sectors({ context }: { context: MarketResearchContext }) {
  const rows = useMemo(() => context.sector_evidence?.items ?? [], [context.sector_evidence?.items]);
  const leaderSymbols = useMemo(
    () => rows.map((row) => String(row.leader_symbol ?? '')),
    [rows],
  );
  const symbolNames = useSymbolNames(leaderSymbols);
  if (rows.length === 0) {
    return <section className={`${panel} p-12 text-center text-sm text-slate-600`}>当前快照没有板块证据；未将缺失排名显示为 0。</section>;
  }
  return (
    <section className={`${panel} overflow-hidden`}>
      <div className="border-b border-crypto-border px-5 py-4">
        <h2 className="font-semibold text-white">板块证据榜</h2>
        <p className="mt-1 text-xs text-slate-500">
          分类依据：{sourceLabel(context.sector_evidence?.classification_system)}；缺失收益或资金流时保持空值。
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1100px] text-sm">
          <thead>
            <tr className="border-b border-crypto-border text-left text-xs text-slate-500">
              <th className="px-5 py-3">板块</th>
              <th className="px-4 py-3 text-right">涨停数</th>
              <th className="px-4 py-3 text-right">连板参与</th>
              <th className="px-4 py-3">龙头</th>
              <th className="px-4 py-3 text-right">1 / 5 / 20日</th>
              <th className="px-4 py-3 text-right">成分广度</th>
              <th className="px-4 py-3 text-right">持续性</th>
              <th className="px-4 py-3 text-right">资金流</th>
              <th className="px-5 py-3">来源</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${String(row.sector_name)}-${index}`} className="border-b border-white/[0.04]">
                <td className="px-5 py-4 font-semibold text-slate-200">{String(row.sector_name ?? '--')}</td>
                <td className="px-4 py-4 text-right tabular-nums text-up">{format(row.limit_up_count, 0)}</td>
                <td className="px-4 py-4 text-right tabular-nums text-slate-300">{format(row.ladder_participation, 0)}</td>
                <td className="px-4 py-4">
                  <SymbolCell
                    symbol={String(row.leader_symbol ?? '')}
                    name={String((row as { leader_name?: string }).leader_name ?? '')}
                    names={symbolNames}
                    compact
                  />
                </td>
                <td className="px-4 py-4 text-right text-slate-500">{format(row.return_1d)} / {format(row.return_5d)} / {format(row.return_20d)}</td>
                <td className="px-4 py-4 text-right text-slate-500">{format(row.breadth)}</td>
                <td className="px-4 py-4 text-right text-slate-500">{format(row.persistence)}</td>
                <td className="px-4 py-4 text-right text-slate-500">{format(row.net_flow)}</td>
                <td className="px-5 py-4 text-xs text-slate-500">{sourceLabel(row.source_label)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PoolMemberRow({ row }: { row: Record<string, unknown> }) {
  const symbol = String(row.symbol ?? '');
  const name = String(row.name ?? formatSymbolLabel(symbol) ?? '--');
  return (
    <div className="flex items-center justify-between gap-2 border-b border-white/[0.03] px-2.5 py-1.5 text-xs last:border-0">
      <span className="min-w-0 truncate font-medium text-slate-100">{name}</span>
      <span className="shrink-0 font-mono text-[10px] tabular-nums text-slate-500">{toPublicSymbol(symbol) || '--'}</span>
    </div>
  );
}

function Sentiment({ context }: { context: MarketResearchContext }) {
  const sentiment = context.sentiment;
  const temperature = sentiment?.market_temperature;
  const ecology = context.limit_ecosystem;
  const ladder = ecology?.ladder ?? [];
  const ladderTotal = ladder.reduce((sum, item) => sum + Number(item.count || 0), 0);
  const pools = [
    { key: 'up' as const, label: '涨停池', tone: 'up' as MetricTone },
    { key: 'down' as const, label: '跌停池', tone: 'down' as MetricTone },
    { key: 'broken' as const, label: '炸板池', tone: 'amber' as MetricTone },
  ];

  return (
    <div className="space-y-4" data-testid="market-sentiment-ths">
      {!sentiment || !ecology ? (
        <div className="rounded-lg border border-amber-500/25 bg-amber-500/10 p-4 text-sm text-amber-200">
          情绪或涨跌停生态证据未发布；下方缺失指标保持 “--”。
        </div>
      ) : null}

      {/* 紧凑指标条：数值不带 stocks/percent 英文后缀 */}
      <section className={`${panel} p-3`}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 px-1">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-amber-300" />
            <h2 className="text-sm font-semibold text-white">市场情绪</h2>
            {temperature?.value != null ? (
              <span className="rounded border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold tabular-nums text-amber-200">
                温度 {format(temperature.value, 1)}
              </span>
            ) : null}
          </div>
          <StatePill state={temperature?.publication_state ?? (ecology ? 'published' : undefined)} />
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
          {(sentiment?.metrics ?? []).map((item) => {
            const tone = sentimentMetricTone(item.metric_code, item.value);
            const { display, suffix } = sentimentDisplay(item);
            return (
              <div
                key={item.metric_code}
                data-testid={`sentiment-metric-${item.metric_code}`}
                className={`rounded-lg border px-3 py-2.5 ${sentimentMetricSurface(tone)}`}
                title={item.definition}
              >
                <div className="truncate text-[11px] text-slate-500">{item.label}</div>
                <MetricValue tone={tone} size="lg" className="mt-1 block">
                  {display}
                  {suffix ? <span className="ml-0.5 text-sm font-semibold opacity-80">{suffix}</span> : null}
                </MetricValue>
              </div>
            );
          })}
        </div>
      </section>

      {/* 同花顺风格：连板天梯 */}
      <section className={`${panel} overflow-hidden`} data-testid="lianban-ladder">
        <div className="flex items-center justify-between border-b border-crypto-border px-4 py-2.5">
          <div className="flex items-center gap-2">
            <Flame className="h-4 w-4 text-up" />
            <h2 className="text-sm font-semibold text-white">连板天梯</h2>
            <span className="text-[11px] text-slate-500">总数: {format(ladderTotal, 0)}</span>
            {ecology?.highest_board ? (
              <span className="text-[11px] text-amber-300/80">最高 {format(ecology.highest_board, 0)} 板</span>
            ) : null}
          </div>
          <span className="text-[10px] text-slate-600">{sourceLabel(ecology?.source_label)}</span>
        </div>
        <div className="grid grid-cols-2 gap-px bg-crypto-border sm:grid-cols-3 xl:grid-cols-5">
          {ladder.map((item) => (
            <div key={item.level} className="flex min-h-[220px] flex-col bg-crypto-card">
              <div className="flex items-center justify-between border-b border-crypto-border/80 px-3 py-2">
                <span className="text-sm font-bold text-slate-200">{item.level}</span>
                <strong className={`text-xl font-black tabular-nums ${metricToneClass('up')}`}>{item.count}</strong>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto custom-scrollbar">
                {item.members.length === 0 ? (
                  <div className="grid h-24 place-items-center text-[11px] text-slate-600">暂无</div>
                ) : (
                  item.members.map((member, index) => (
                    <PoolMemberRow key={`${item.level}-${String(member.symbol)}-${index}`} row={member} />
                  ))
                )}
              </div>
            </div>
          ))}
          {ladder.length === 0 ? (
            <div className="col-span-full grid h-40 place-items-center bg-crypto-card text-sm text-slate-600">
              当前快照无连板成员
            </div>
          ) : null}
        </div>
      </section>

      {/* 涨停 / 跌停 / 炸板 */}
      <section className="grid gap-3 lg:grid-cols-3">
        {pools.map(({ key, label, tone }) => {
          const rows = ecology?.pools?.[key] ?? [];
          return (
            <div key={key} className={`${panel} overflow-hidden`} data-testid={`limit-pool-${key}`}>
              <div className="flex items-center justify-between border-b border-crypto-border px-3 py-2.5">
                <h3 className="text-sm font-semibold text-slate-200">{label}</h3>
                <MetricValue tone={tone} size="md">{ecology ? format(rows.length, 0) : '--'}</MetricValue>
              </div>
              <div className="max-h-72 overflow-y-auto custom-scrollbar">
                {rows.length === 0 ? (
                  <div className="grid h-24 place-items-center text-[11px] text-slate-600">名单为空</div>
                ) : (
                  rows.map((row, index) => <PoolMemberRow key={`${key}-${index}`} row={row} />)
                )}
              </div>
            </div>
          );
        })}
      </section>

      {/* 晋级 / 淘汰 */}
      <section className={`${panel} p-3`}>
        <h2 className="mb-3 px-1 text-sm font-semibold text-white">晋级 / 淘汰队列</h2>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {(ecology?.promotion_elimination ?? []).map((row, index) => (
            <div key={index} className="rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2.5">
              <div className="text-xs font-semibold text-slate-300">{format(row.from_level, 0)}级队列</div>
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500">
                <span>样本 <span className="tabular-nums text-slate-300">{format(row.cohort_size, 0)}</span></span>
                <span>晋级 <span className={`tabular-nums ${metricToneClass('up')}`}>{format(row.promoted_count, 0)}</span></span>
                <span>淘汰 <span className={`tabular-nums ${metricToneClass('down')}`}>{format(row.eliminated_count, 0)}</span></span>
              </div>
            </div>
          ))}
          {(ecology?.promotion_elimination ?? []).length === 0 ? (
            <div className="col-span-full rounded-lg border border-dashed border-crypto-border px-3 py-6 text-center text-[11px] text-slate-600">
              无上一交易日对照队列
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function Events({ messages, context }: { messages: MessageStreamResponse | null; context: MarketResearchContext }) {
  const items = messages ? [...messages.mergers, ...messages.good_news, ...messages.bad_news, ...messages.cailian_news, ...messages.xueqiu_news, ...messages.eastmoney_news] : [];
  const rankings = context.heat_rankings ?? [];
  const newsState = messages?.data_status?.news_state ?? '状态未知';
  return <div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]"><section className={`${panel} overflow-hidden`}><div className="border-b border-crypto-border px-5 py-4"><h2 className="font-semibold text-white">资讯流</h2><p className="mt-1 text-xs text-slate-500">本地缓存 · {statusLabel(newsState)} · 内容时间 {messages?.source_updated_at ?? messages?.updated_at ?? '--'}</p></div><div className="divide-y divide-white/[0.04]">{items.slice(0, 30).map((item, index) => <article key={index} className="p-4"><div className="flex items-center gap-2 text-[11px] text-slate-600"><span>{sourceLabel((item as unknown as Record<string, unknown>).source, '资讯来源')}</span><span>{String((item as unknown as Record<string, unknown>).published_at ?? (item as unknown as Record<string, unknown>).time ?? '--')}</span></div><h3 className="mt-1 text-sm font-medium text-slate-200">{String((item as unknown as Record<string, unknown>).title ?? (item as unknown as Record<string, unknown>).content ?? '--')}</h3></article>)}{items.length === 0 ? <div className="p-12 text-center text-sm text-slate-600">当前资讯缓存为空；未以空白或 0 条“正常数据”替代。</div> : null}</div></section><section className={`${panel} p-5`}><h2 className="font-semibold text-white">热度榜证据</h2><div className="mt-4 space-y-2">{rankings.slice(0, 30).map((row, index) => <div key={index} className="flex items-center gap-3 rounded-lg border border-crypto-border bg-crypto-bg p-3"><span className="w-6 text-center tabular-nums text-amber-300">{String(row.rank ?? index + 1)}</span><div className="min-w-0 flex-1"><div className="truncate text-sm text-slate-200">{String(row.name ?? row.symbol ?? '--')}</div><div className="mt-0.5 text-[10px] text-slate-600">{sourceLabel(row.source_label ?? row.ranking_provider)}</div></div></div>)}{rankings.length === 0 ? <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-6 text-center text-sm text-amber-200">当前快照未绑定热度榜证据。</div> : null}</div></section></div>;
}

export function MarketResearch() {
  const [params, setParams] = useSearchParams();
  const requested = params.get('tab') as TabKey | null;
  const tab: TabKey = TABS.some(([key]) => key === requested) ? requested! : 'structure';
  const [context, setContext] = useState<MarketResearchContext | null>(null);
  const [messages, setMessages] = useState<MessageStreamResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [resourceErrors, setResourceErrors] = useState<{ messages?: string }>({});
  const [tradeDate, setTradeDate] = useState('');
  const [scope, setScope] = useState('all_a');

  const load = async () => {
    setLoading(true); setError(''); setResourceErrors({});
    try {
      const [research, news] = await Promise.allSettled([
        getMarketResearchContext({ trade_date: tradeDate || undefined, market_scope: scope }),
        getMessageStream(60),
      ]);
      if (research.status === 'fulfilled') {
        setContext(research.value);
        if (research.value?.snapshot?.trade_date && (!tradeDate || tradeDate === '')) {
          setTradeDate(research.value.snapshot.trade_date);
        }
      } else {
        setContext(null);
        setError(research.reason instanceof Error ? research.reason.message : '市场研究快照加载失败');
      }
      if (news.status === 'fulfilled') setMessages(news.value);
      else {
        setMessages(null);
        setResourceErrors((current) => ({ ...current, messages: '资讯缓存接口失败' }));
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : '市场研究上下文加载失败'); }
    finally { setLoading(false); }
  };
  // Initial discovery intentionally uses the default scope; date/scope edits are applied by “加载快照”.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void load(); }, []);
  const title = useMemo(() => TABS.find(([key]) => key === tab)?.[1], [tab]);

  const evidenceDate = context?.snapshot?.trade_date || '';
  const lagDays = useMemo(() => {
    if (!evidenceDate) return null;
    const asOf = new Date(`${evidenceDate}T00:00:00`);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const diff = Math.round((today.getTime() - asOf.getTime()) / 86_400_000);
    return Number.isFinite(diff) ? diff : null;
  }, [evidenceDate]);
  const evidenceStale = lagDays != null && lagDays >= 1;

  return <div className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8" data-testid="market-research-workbench" data-operator-page="market">
    <OperatorPageHeader
      icon={Search}
      title={
        <span className="inline-flex flex-wrap items-center gap-3">
          行情
          <span className="rounded-md border border-blue-500/25 bg-blue-500/10 px-2 py-1 text-xs font-semibold text-blue-300">{title}</span>
          {evidenceDate ? (
            <span
              className={`rounded-md border px-2 py-1 text-xs font-semibold tabular-nums ${
                evidenceStale
                  ? 'border-amber-500/30 bg-amber-500/10 text-amber-200'
                  : 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
              }`}
              title="当前页面展示的是已封存盘后证据，不是实时推送"
            >
              证据截止 {evidenceDate}
              {evidenceStale && lagDays != null ? ` · 滞后 ${lagDays} 天` : ''}
            </span>
          ) : null}
        </span>
      }
      subtitle="多因子链路的市场输入：结构 / 板块 / 情绪涨停 / 事件 / 日历 / 个股。情绪页读封存盘后快照，不是盘中实时。"
      actions={
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-[11px] text-slate-500">
            交易日
            <input
              aria-label="市场交易日"
              type="date"
              value={tradeDate}
              onChange={(event) => setTradeDate(event.target.value)}
              placeholder="最新封存"
              className="mt-1 block h-10 rounded-lg border border-crypto-border bg-crypto-card px-3 text-sm text-slate-300"
            />
          </label>
          <button
            type="button"
            onClick={() => {
              setTradeDate('');
              void getMarketResearchContext({ market_scope: scope }).then((res) => {
                setContext(res);
                if (res?.snapshot?.trade_date) {
                  setTradeDate(res.snapshot.trade_date);
                }
              });
            }}
            className="h-10 rounded-lg border border-crypto-border px-3 text-xs text-slate-400 hover:bg-crypto-card hover:text-slate-200"
            title="加载最新封存证据日期"
          >
            最新
          </button>
          <label className="text-[11px] text-slate-500">市场范围<select aria-label="市场范围" value={scope} onChange={(event) => setScope(event.target.value)} className="mt-1 block h-10 rounded-lg border border-crypto-border bg-crypto-card px-3 text-sm text-slate-300"><option value="all_a">全A</option><option value="main_board">主板</option><option value="chinext">创业板</option><option value="star">科创板</option><option value="beijing">北交所</option><option value="exclude_st">非ST</option></select></label>
          <button type="button" onClick={() => void load()} className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-400 hover:text-white"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />加载快照</button>
        </div>
      }
    />
    <WorkspacePipelineNote stageId="market" />
    {evidenceStale && evidenceDate ? (
      <div className="mb-4 rounded-lg border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-100" data-testid="market-evidence-stale-banner">
        当前展示的是 <span className="font-semibold tabular-nums">{evidenceDate}</span> 盘后封存证据
        {lagDays != null ? `（距今 ${lagDays} 天）` : ''}。
        本地已有更新的日线缓存时，需跑日终市场证据同步才会出现在本页；这不是实时行情页。
      </div>
    ) : null}
    <WorkspaceTabs ariaLabel="市场研究二级导航" items={TABS.map(([id, label]) => ({ id, label, testId: `market-tab-${id}` }))} value={tab} onChange={(id) => setParams({ tab: id })} />
    {error ? <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">{error}</div> : null}
    {tab === 'events' && resourceErrors.messages ? <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">{resourceErrors.messages}；未把失败响应显示为空资讯。</div> : null}
    {!context && loading && tab !== 'calendar' && tab !== 'stock' ? <div className={`${panel} flex h-72 items-center justify-center text-slate-500`}><RefreshCw className="mr-2 h-5 w-5 animate-spin" />读取市场快照…</div> : null}
    {context && tab === 'structure' ? <Structure context={context} /> : null}
    {context && tab === 'sectors' ? <Sectors context={context} /> : null}
    {context && tab === 'sentiment' ? <Sentiment context={context} /> : null}
    {context && tab === 'events' ? <Events messages={messages} context={context} /> : null}
    {tab === 'calendar' ? <MarketTradingCalendar /> : null}
    {tab === 'stock' ? <div className="-mx-5 -mb-6 -mt-2 2xl:-mx-8"><StockTerminal asOfDate={tradeDate || context?.snapshot?.trade_date} /></div> : null}
    {context?.snapshot ? <footer className="mt-5 flex flex-wrap items-center gap-4 text-[11px] text-slate-600"><Database className="h-3.5 w-3.5" />市场证据已绑定<Layers3 className="h-3.5 w-3.5" />已封存校验 · {context.snapshot.trade_date}<Newspaper className="h-3.5 w-3.5" />资讯仅展示缓存<CalendarDays className="h-3.5 w-3.5" />交易日 {context.snapshot.trade_date}</footer> : null}
  </div>;
}

export default MarketResearch;
