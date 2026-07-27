import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Activity, ArrowDownRight, ArrowUpRight, CalendarDays, Database, Flame, Layers3, Newspaper, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { MetricCard } from '@bitpro/ui';
import { getMarketCalendar, getMarketResearchContext, getMessageStream } from '../api/client';
import type { MarketCalendarEvent, MarketResearchContext, MessageStreamResponse } from '../types';
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

const HEADLINE_METRICS = [
  { code: 'rise_count', color: 'up', icon: ArrowUpRight, detail: '收盘上涨证券', cardClass: 'border-red-500/35 bg-red-500/[0.06]' },
  { code: 'fall_count', color: 'down', icon: ArrowDownRight, detail: '收盘下跌证券', cardClass: 'border-emerald-500/35 bg-emerald-500/[0.06]' },
  { code: 'limit_up_count', color: 'red', icon: ArrowUpRight, detail: '收盘封板证券', cardClass: 'border-red-500/25 bg-red-500/[0.035]' },
  { code: 'limit_down_count', color: 'green', icon: ArrowDownRight, detail: '收盘跌停证券', cardClass: 'border-emerald-500/25 bg-emerald-500/[0.035]' },
  { code: 'highest_board', color: 'amber', icon: Flame, detail: '连续涨停最高高度', cardClass: 'border-amber-500/30 bg-amber-500/[0.045]' },
  { code: 'seal_rate', color: 'blue', icon: ShieldCheck, detail: '涨停家数 / 涨停 + 炸板', cardClass: 'border-blue-500/30 bg-blue-500/[0.05]' },
] as const;

function headlineValue(code: string, value: unknown) {
  const display = format(value, code === 'seal_rate' ? 2 : 0);
  return <span className="font-sans text-[28px] font-bold leading-none tracking-[-0.04em] tabular-nums">{display}{code === 'seal_rate' && display !== '--' ? <span className="ml-0.5 text-base font-semibold tracking-normal">%</span> : null}</span>;
}

function StatePill({ state }: { state?: string }) {
  const available = state === 'published' || state === 'fresh';
  return <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${available ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/25 bg-amber-500/10 text-amber-300'}`}>{state || 'unknown'}</span>;
}

function Structure({ context }: { context: MarketResearchContext }) {
  const snapshot = context.snapshot;
  const metrics = context.sentiment?.metrics ?? [];
  return <div className="space-y-5">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
      {HEADLINE_METRICS.map((metric) => {
        const item = metrics.find((candidate) => candidate.metric_code === metric.code);
        const Icon = metric.icon;
        return <div key={metric.code} data-testid={`market-headline-${metric.code}`}><MetricCard label={item?.label ?? metric.code} value={headlineValue(metric.code, item?.value)} icon={<Icon className="h-3.5 w-3.5" />} color={metric.color} detail={item?.definition ?? metric.detail} className={metric.cardClass} /></div>;
      })}
    </div>
    <section className={`${panel} p-5`}><div className="flex flex-wrap items-start justify-between gap-4"><div><h2 className="font-semibold text-white">市场数据快照</h2><p className="mt-1 text-xs text-slate-500">按交易日查看市场结构、来源与数据状态。</p></div><StatePill state={snapshot?.freshness ?? context.publication_state} /></div><dl className="mt-5 grid gap-4 text-sm sm:grid-cols-3">{[['快照', snapshot ? `#${snapshot.id}` : '--'], ['交易日', snapshot?.trade_date ?? '--'], ['会话', snapshot?.session_label ?? snapshot?.snapshot_type ?? '--']].map(([label, value]) => <div key={label} className="rounded-lg border border-crypto-border bg-crypto-bg p-3"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 font-mono text-slate-300">{value}</dd></div>)}</dl><div className="mt-4 flex flex-wrap gap-2">{Object.entries(snapshot?.source_map ?? {}).map(([kind, source]) => <span key={kind} className="rounded-md border border-blue-500/20 bg-blue-500/10 px-2.5 py-1 text-xs text-blue-200">{kind}: {source}</span>)}</div></section>
    <div className="grid gap-5 xl:grid-cols-[1.2fr_1fr]"><section className={`${panel} p-5`}><h2 className="font-semibold text-white">市场广度比较</h2><div className="mt-4 grid gap-3 sm:grid-cols-2">{(context.comparisons ?? []).map((item, index) => <div key={index} className="rounded-lg border border-crypto-border bg-crypto-bg p-3"><div className="flex items-center justify-between"><span className="text-xs font-semibold text-slate-300">{String(item.label ?? '--')}</span><StatePill state={String(item.publication_state ?? '')} /></div><div className="mt-2 text-[11px] text-slate-600">{item.reason ? String(item.reason) : `已发布 ${Object.keys((item.deltas as Record<string, unknown>) ?? {}).length} 个差值`}</div></div>)}</div></section><section className={`${panel} p-5`}><h2 className="font-semibold text-white">AI 证据摘要</h2><p className="mt-1 text-xs text-slate-500">事实与推断分栏，引用封存对象。</p><div className="mt-4 space-y-3">{context.evidence_summary?.facts.map((fact) => <div key={fact.evidence_ref} className="rounded-lg border border-emerald-500/15 bg-emerald-500/5 p-3"><div className="text-sm text-slate-200">事实 · {fact.text}</div><div className="mt-1 font-mono text-[10px] text-emerald-400/70">{fact.evidence_ref}</div></div>)}{context.evidence_summary?.inferences.map((item, index) => <div key={index} className="rounded-lg border border-amber-500/15 bg-amber-500/5 p-3"><div className="text-sm text-amber-100">推断 · {item.text}</div><div className="mt-1 text-[10px] text-amber-500/60">{item.basis}</div></div>)}</div></section></div>
  </div>;
}

function Sectors({ context }: { context: MarketResearchContext }) {
  const rows = context.sector_evidence?.items ?? [];
  if (rows.length === 0) {
    return <section className={`${panel} p-12 text-center text-sm text-slate-600`}>当前快照没有板块证据；未将缺失排名显示为 0。</section>;
  }
  return <section className={`${panel} overflow-hidden`}><div className="border-b border-crypto-border px-5 py-4"><h2 className="font-semibold text-white">板块证据榜</h2><p className="mt-1 text-xs text-slate-500">分类体系 {context.sector_evidence?.classification_system ?? '--'}；缺失收益/资金流时保持空值。</p></div><div className="overflow-x-auto"><table className="w-full min-w-[1100px] text-sm"><thead><tr className="border-b border-crypto-border text-left text-xs text-slate-500"><th className="px-5 py-3">板块</th><th className="px-4 py-3 text-right">涨停数</th><th className="px-4 py-3 text-right">连板参与</th><th className="px-4 py-3">龙头</th><th className="px-4 py-3 text-right">1 / 5 / 20日</th><th className="px-4 py-3 text-right">成分广度</th><th className="px-4 py-3 text-right">持续性</th><th className="px-4 py-3 text-right">资金流</th><th className="px-5 py-3">来源</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${String(row.sector_name)}-${index}`} className="border-b border-white/[0.04]"><td className="px-5 py-4 font-semibold text-slate-200">{String(row.sector_name ?? '--')}</td><td className="px-4 py-4 text-right font-mono text-red-300">{format(row.limit_up_count, 0)}</td><td className="px-4 py-4 text-right font-mono text-slate-300">{format(row.ladder_participation, 0)}</td><td className="px-4 py-4 font-mono text-blue-300">{String(row.leader_symbol ?? '--')}</td><td className="px-4 py-4 text-right text-slate-500">{format(row.return_1d)} / {format(row.return_5d)} / {format(row.return_20d)}</td><td className="px-4 py-4 text-right text-slate-500">{format(row.breadth)}</td><td className="px-4 py-4 text-right text-slate-500">{format(row.persistence)}</td><td className="px-4 py-4 text-right text-slate-500">{format(row.net_flow)}</td><td className="px-5 py-4 text-xs text-slate-500">{String(row.source_label ?? '--')}</td></tr>)}</tbody></table></div></section>;
}

function Sentiment({ context }: { context: MarketResearchContext }) {
  const sentiment = context.sentiment;
  const temperature = sentiment?.market_temperature;
  const ecology = context.limit_ecosystem;
  return <div className="space-y-5">
    {!sentiment || !ecology ? <div className="rounded-lg border border-amber-500/25 bg-amber-500/10 p-4 text-sm text-amber-200">情绪或涨跌停生态证据未发布；下方缺失指标保持 “--”。</div> : null}
    <div className="grid gap-5 xl:grid-cols-[320px_1fr]">
      <section className={`${panel} p-5`}><div className="flex items-center gap-2"><Activity className="h-5 w-5 text-amber-300" /><h2 className="font-semibold text-white">市场温度</h2></div><div className="mt-6 text-5xl font-black tabular-nums text-amber-300">{temperature?.value === null || temperature?.value === undefined ? '--' : format(temperature.value, 1)}</div><div className="mt-3"><StatePill state={temperature?.publication_state} /></div><p className="mt-4 text-xs leading-5 text-slate-500">{temperature?.value === null ? `不发布：缺少 ${temperature.missing_components.join('、')}` : `公式 ${temperature?.formula_version}`}</p></section>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{(sentiment?.metrics ?? []).map((item) => <div key={item.metric_code} className={`${panel} p-4`} title={item.definition}><div className="flex items-center justify-between"><span className="text-xs text-slate-500">{item.label}</span><StatePill state={item.publication_state} /></div><div className="mt-2 text-xl font-bold tabular-nums text-slate-100">{format(item.value)}{item.unit ?? ''}</div><div className="mt-2 truncate text-[10px] text-slate-600">{item.source_label ?? item.missing_reason}</div></div>)}</div>
    </div>
    <section className={`${panel} p-5`}><div className="flex items-center justify-between"><div><h2 className="font-semibold text-white">连板天梯</h2><p className="mt-1 text-xs text-slate-500">最高 {format(ecology?.highest_board, 0)} 板 · {ecology?.source_label ?? '--'}</p></div><Flame className="h-5 w-5 text-red-400" /></div><div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">{(ecology?.ladder ?? []).map((item) => <div key={item.level} className="rounded-lg border border-crypto-border bg-crypto-bg p-4"><div className="flex items-end justify-between"><span className="font-bold text-slate-200">{item.level}</span><strong className="text-2xl text-red-300">{item.count}</strong></div><div className="mt-3 space-y-1.5">{item.members.slice(0, 6).map((member, index) => <div key={`${String(member.symbol)}-${index}`} className="flex justify-between text-xs"><span className="truncate text-slate-400">{String(member.name ?? member.symbol)}</span><span className="ml-2 font-mono text-slate-600">{String(member.symbol)}</span></div>)}</div></div>)}</div></section>
    <section className={`${panel} p-5`}><h2 className="font-semibold text-white">涨停 / 跌停 / 炸板明细</h2><div className="mt-4 grid gap-3 lg:grid-cols-3">{([['up', '涨停池'], ['down', '跌停池'], ['broken', '炸板池']] as const).map(([key, label]) => <div key={key} className="rounded-lg border border-crypto-border bg-crypto-bg p-4"><div className="flex justify-between"><span className="font-semibold text-slate-300">{label}</span><strong className="font-mono text-white">{ecology ? ecology.pools[key]?.length ?? '--' : '--'}</strong></div><div className="mt-3 space-y-1">{(ecology?.pools[key] ?? []).slice(0, 8).map((row, index) => <div key={index} className="flex justify-between text-xs text-slate-500"><span>{String(row.name ?? row.symbol ?? '--')}</span><span className="font-mono">{String(row.symbol ?? '--')}</span></div>)}</div></div>)}</div></section>
    <section className={`${panel} p-5`}><h2 className="font-semibold text-white">晋级 / 淘汰队列</h2><div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{(ecology?.promotion_elimination ?? []).map((row, index) => <div key={index} className="rounded-lg border border-crypto-border bg-crypto-bg p-3 text-xs"><div className="font-semibold text-slate-300">{format(row.from_level, 0)}板队列</div><div className="mt-2 text-slate-500">样本 {format(row.cohort_size, 0)} · 晋级 {format(row.promoted_count, 0)} · 淘汰 {format(row.eliminated_count, 0)}</div></div>)}</div></section>
  </div>;
}

function Events({ messages, context }: { messages: MessageStreamResponse | null; context: MarketResearchContext }) {
  const items = messages ? [...messages.mergers, ...messages.good_news, ...messages.bad_news, ...messages.cailian_news, ...messages.xueqiu_news, ...messages.eastmoney_news] : [];
  const rankings = context.heat_rankings ?? [];
  const newsState = messages?.data_status?.news_state ?? '状态未知';
  return <div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]"><section className={`${panel} overflow-hidden`}><div className="border-b border-crypto-border px-5 py-4"><h2 className="font-semibold text-white">资讯流</h2><p className="mt-1 text-xs text-slate-500">PostgreSQL 缓存 · {newsState} · 内容时间 {messages?.source_updated_at ?? messages?.updated_at ?? '--'}</p></div><div className="divide-y divide-white/[0.04]">{items.slice(0, 30).map((item, index) => <article key={index} className="p-4"><div className="flex items-center gap-2 text-[11px] text-slate-600"><span>{String((item as unknown as Record<string, unknown>).source ?? '--')}</span><span>{String((item as unknown as Record<string, unknown>).published_at ?? (item as unknown as Record<string, unknown>).time ?? '--')}</span></div><h3 className="mt-1 text-sm font-medium text-slate-200">{String((item as unknown as Record<string, unknown>).title ?? (item as unknown as Record<string, unknown>).content ?? '--')}</h3></article>)}{items.length === 0 ? <div className="p-12 text-center text-sm text-slate-600">当前 PostgreSQL 资讯缓存为空；未以空白或 0 条“正常数据”替代。</div> : null}</div></section><section className={`${panel} p-5`}><h2 className="font-semibold text-white">热度榜证据</h2><div className="mt-4 space-y-2">{rankings.slice(0, 30).map((row, index) => <div key={index} className="flex items-center gap-3 rounded-lg border border-crypto-border bg-crypto-bg p-3"><span className="w-6 text-center font-mono text-amber-300">{String(row.rank ?? index + 1)}</span><div className="min-w-0 flex-1"><div className="truncate text-sm text-slate-200">{String(row.name ?? row.symbol ?? '--')}</div><div className="mt-0.5 text-[10px] text-slate-600">{String(row.source_label ?? row.ranking_provider ?? '--')}</div></div></div>)}{rankings.length === 0 ? <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-6 text-center text-sm text-amber-200">当前快照未绑定热度榜证据。</div> : null}</div></section></div>;
}

function Calendar({ items }: { items: MarketCalendarEvent[] }) {
  return <section className={`${panel} overflow-hidden`}><div className="border-b border-crypto-border px-5 py-4"><h2 className="font-semibold text-white">交易事件日历</h2><p className="mt-1 text-xs text-slate-500">PostgreSQL 事件缓存；无记录不代表当日无事件。</p></div><div className="divide-y divide-white/[0.04]">{items.slice(0, 80).map((item, index) => { const row = item as unknown as Record<string, unknown>; return <div key={index} className="grid gap-2 px-5 py-4 sm:grid-cols-[130px_120px_1fr]"><span className="font-mono text-sm text-blue-300">{String(row.event_date ?? row.date ?? '--')}</span><span className="text-xs text-slate-500">{String(row.event_type ?? row.type ?? '市场事件')}</span><span className="text-sm text-slate-200">{String(row.title ?? row.name ?? row.content ?? '--')}</span></div>; })}{items.length === 0 ? <div className="p-12 text-center text-sm text-slate-600">事件缓存为空或尚未同步；不能据此判断“无事件”。</div> : null}</div></section>;
}

export function MarketResearch() {
  const [params, setParams] = useSearchParams();
  const requested = params.get('tab') as TabKey | null;
  const tab: TabKey = TABS.some(([key]) => key === requested) ? requested! : 'structure';
  const [context, setContext] = useState<MarketResearchContext | null>(null);
  const [messages, setMessages] = useState<MessageStreamResponse | null>(null);
  const [calendar, setCalendar] = useState<MarketCalendarEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [resourceErrors, setResourceErrors] = useState<{ messages?: string; calendar?: string }>({});
  const [tradeDate, setTradeDate] = useState('');
  const [scope, setScope] = useState('all_a');

  const load = async () => {
    setLoading(true); setError(''); setResourceErrors({});
    try {
      const [research, news, dates] = await Promise.allSettled([getMarketResearchContext({ trade_date: tradeDate || undefined, market_scope: scope }), getMessageStream(60), getMarketCalendar({ limit: 200 })]);
      if (research.status === 'fulfilled') {
        setContext(research.value);
        if (!tradeDate && research.value.snapshot?.trade_date) setTradeDate(research.value.snapshot.trade_date);
      } else {
        setContext(null);
        setError(research.reason instanceof Error ? research.reason.message : '市场研究快照加载失败');
      }
      if (news.status === 'fulfilled') setMessages(news.value);
      else {
        setMessages(null);
        setResourceErrors((current) => ({ ...current, messages: '资讯缓存接口失败' }));
      }
      if (dates.status === 'fulfilled') setCalendar(dates.value);
      else {
        setCalendar([]);
        setResourceErrors((current) => ({ ...current, calendar: '事件日历接口失败' }));
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : '市场研究上下文加载失败'); }
    finally { setLoading(false); }
  };
  // Initial discovery intentionally uses the default scope; date/scope edits are applied by “加载快照”.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void load(); }, []);
  const title = useMemo(() => TABS.find(([key]) => key === tab)?.[1], [tab]);

  return <div className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8" data-testid="market-research-workbench">
    <header className="mb-5 flex flex-wrap items-start justify-between gap-4"><div><div className="flex items-center gap-3"><Search className="h-7 w-7 text-blue-400" /><h1 className="text-2xl font-black text-white">行情</h1><span className="rounded-md border border-blue-500/25 bg-blue-500/10 px-2 py-1 text-xs text-blue-300">{title}</span></div><p className="mt-2 text-sm text-slate-500">查看市场结构、板块、情绪、事件、日历和个股证据。</p></div><div className="flex flex-wrap items-end gap-2"><label className="text-[11px] text-slate-500">交易日<input aria-label="市场交易日" type="date" value={tradeDate} onChange={(event) => setTradeDate(event.target.value)} className="mt-1 block h-10 rounded-lg border border-crypto-border bg-crypto-card px-3 text-sm text-slate-300" /></label><label className="text-[11px] text-slate-500">市场范围<select aria-label="市场范围" value={scope} onChange={(event) => setScope(event.target.value)} className="mt-1 block h-10 rounded-lg border border-crypto-border bg-crypto-card px-3 text-sm text-slate-300"><option value="all_a">全A</option><option value="main_board">主板</option><option value="chinext">创业板</option><option value="star">科创板</option><option value="beijing">北交所</option><option value="exclude_st">非ST</option></select></label><button type="button" onClick={() => void load()} className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-400 hover:text-white"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />加载快照</button></div></header>
    <nav className="mb-5 flex overflow-x-auto rounded-xl border border-crypto-border bg-crypto-card p-1" aria-label="市场研究二级导航">{TABS.map(([key, label]) => <button key={key} data-testid={`market-tab-${key}`} type="button" onClick={() => setParams({ tab: key })} className={`min-w-max flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors ${tab === key ? 'bg-blue-600 text-white shadow-lg shadow-blue-950/30' : 'text-slate-500 hover:bg-slate-800/60 hover:text-slate-200'}`}>{label}</button>)}</nav>
    {error ? <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">{error}</div> : null}
    {tab === 'events' && resourceErrors.messages ? <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">{resourceErrors.messages}；未把失败响应显示为空资讯。</div> : null}
    {tab === 'calendar' && resourceErrors.calendar ? <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">{resourceErrors.calendar}；未把接口失败解释为“无事件”。</div> : null}
    {!context && loading ? <div className={`${panel} flex h-72 items-center justify-center text-slate-500`}><RefreshCw className="mr-2 h-5 w-5 animate-spin" />读取市场快照…</div> : null}
    {context && tab === 'structure' ? <Structure context={context} /> : null}
    {context && tab === 'sectors' ? <Sectors context={context} /> : null}
    {context && tab === 'sentiment' ? <Sentiment context={context} /> : null}
    {context && tab === 'events' ? <Events messages={messages} context={context} /> : null}
    {context && tab === 'calendar' ? <Calendar items={calendar} /> : null}
    {tab === 'stock' ? <div className="-mx-5 -mb-6 -mt-2 2xl:-mx-8"><StockTerminal asOfDate={tradeDate || context?.snapshot?.trade_date} /></div> : null}
    {context?.snapshot ? <footer className="mt-5 flex flex-wrap items-center gap-4 text-[11px] text-slate-600"><Database className="h-3.5 w-3.5" />证据快照 #{context.snapshot.id}<Layers3 className="h-3.5 w-3.5" />{context.snapshot.content_hash.slice(0, 16)}<Newspaper className="h-3.5 w-3.5" />资讯仅展示缓存<CalendarDays className="h-3.5 w-3.5" />交易日 {context.snapshot.trade_date}</footer> : null}
  </div>;
}

export default MarketResearch;
