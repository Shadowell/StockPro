import { useEffect, useMemo, useState, type ReactNode } from 'react';
import clsx from 'clsx';
import {
  Activity,
  BookOpenCheck,
  CalendarDays,
  Flame,
  Layers3,
  Loader2,
  NotebookPen,
  RefreshCw,
  Save,
  ShieldAlert,
  Sparkles,
  TrendingUp,
} from 'lucide-react';
import {
  getHotConcepts,
  getLianbanLadder,
  getMarketOverview,
  getShortLineIndices,
  listReplayNotes,
  saveReplayNote,
  syncTodayConceptSectors,
  type ReplayNote,
} from '../api/client';
import type { HotConceptItem, LianbanLadderResponse, MarketOverview } from '../types';

type ShortLineIndex = {
  code: string;
  name: string;
  price: number;
  change_percent: number;
  change_amount: number;
};

const formatNumber = (value?: number | null, digits = 2) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return Number(value).toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
};

const formatDate = (value = new Date()) => {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const Pct = ({ value }: { value?: number | null }) => (
  <span className={clsx('font-black tabular-nums', (value || 0) >= 0 ? 'text-up' : 'text-down')}>
    {(value || 0) >= 0 ? '+' : ''}
    {formatNumber(value || 0, 2)}%
  </span>
);

function Panel({
  title,
  meta,
  icon,
  children,
}: {
  title: string;
  meta?: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-crypto-border bg-crypto-card">
      <div className="flex items-center justify-between gap-3 border-b border-crypto-border px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-md border border-blue-500/25 bg-blue-500/10 text-blue-300">
            {icon}
          </span>
          <h2 className="text-base font-black text-white">{title}</h2>
        </div>
        {meta ? <span className="text-xs font-semibold text-slate-500">{meta}</span> : null}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function DailyReview() {
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [hotConcepts, setHotConcepts] = useState<HotConceptItem[]>([]);
  const [ladder, setLadder] = useState<LianbanLadderResponse | null>(null);
  const [shortLine, setShortLine] = useState<ShortLineIndex[]>([]);
  const [notes, setNotes] = useState<ReplayNote[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [selectedDate, setSelectedDate] = useState(formatDate());
  const [title, setTitle] = useState(`${formatDate()} 盘面复盘`);
  const [mainTone, setMainTone] = useState('');
  const [risk, setRisk] = useState('');
  const [plan, setPlan] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const [overviewData, conceptData, ladderData, shortLineData, noteData] = await Promise.all([
        getMarketOverview().catch(() => null),
        getHotConcepts(10).catch(() => []),
        getLianbanLadder().catch(() => null),
        getShortLineIndices().catch(() => []),
        listReplayNotes(8).catch(() => []),
      ]);
      setOverview(overviewData);
      setHotConcepts(conceptData);
      setLadder(ladderData);
      setShortLine(shortLineData);
      setNotes(noteData);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const breadth = overview?.market_breadth;
  const sentiment = overview?.sentiment;
  const volume = overview?.volume;
  const topConcepts = hotConcepts.slice(0, 5);
  const topConcept = topConcepts[0];
  const ladderLevels = (ladder?.levels || []).filter((item) => (item.today_count || 0) > 0).slice(0, 4);
  const limitUp = shortLine.find((item) => item.name.includes('涨停'));
  const limitDown = shortLine.find((item) => item.name.includes('跌停'));

  const systemConclusion = useMemo(() => {
    const tone = sentiment?.status || '中性';
    const concept = topConcept ? `${topConcept.name} ${topConcept.change_percent >= 0 ? '领涨' : '调整'}` : '板块轮动暂不突出';
    const up = breadth?.up ?? sentiment?.advancing ?? 0;
    const down = breadth?.down ?? sentiment?.declining ?? 0;
    return {
      mainTone: `${tone}；上涨 ${up} 家、下跌 ${down} 家，${concept}。`,
      risk: limitDown && limitDown.price > 0 ? `跌停家数 ${formatNumber(limitDown.price, 0)}，注意亏钱效应扩散。` : '暂无明显系统性风险信号，关注量能延续。',
      plan: topConcept ? `次日优先观察 ${topConcept.name} 的延续性、分歧承接和龙头反馈。` : '次日先观察指数量能、情绪修复与主线是否重新聚焦。',
    };
  }, [breadth, limitDown, sentiment, topConcept]);

  const fillSystemConclusion = () => {
    setMainTone(systemConclusion.mainTone);
    setRisk(systemConclusion.risk);
    setPlan(systemConclusion.plan);
  };

  const saveNote = async () => {
    setSaving(true);
    try {
      const content = [`主线方向：${mainTone || systemConclusion.mainTone}`, `风险提示：${risk || systemConclusion.risk}`, `次日计划：${plan || systemConclusion.plan}`].join('\n');
      const note = await saveReplayNote({
        note_date: selectedDate,
        title: title || `${selectedDate} 盘面复盘`,
        content,
        payload_json: {
          sentiment,
          breadth,
          top_concepts: topConcepts,
          lianban_date: ladder?.date,
        },
      });
      setNotes((prev) => [note, ...prev.filter((item) => item.note_date !== note.note_date)].slice(0, 8));
    } finally {
      setSaving(false);
    }
  };

  const syncToday = async () => {
    setSyncing(true);
    try {
      await syncTodayConceptSectors();
      await load();
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="min-h-full bg-crypto-bg p-4 sm:p-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-black text-white">今日盘面复盘</h1>
          <p className="mt-1 text-sm font-semibold text-slate-500">盘面强弱、板块轮动、连板梯队与次日计划</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={syncToday}
            disabled={syncing}
            className="inline-flex h-9 items-center gap-2 rounded-md border border-emerald-500/25 bg-emerald-500/10 px-3 text-sm font-bold text-emerald-200 transition-colors hover:border-emerald-400/50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            同步今日
          </button>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="inline-flex h-9 items-center gap-2 rounded-md border border-crypto-border bg-crypto-card px-3 text-sm font-bold text-slate-200 transition-colors hover:border-blue-500/60 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            刷新
          </button>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {[
          { label: '市场温度', value: sentiment?.status || '中性', sub: `Index: ${formatNumber(sentiment?.score ?? 50, 0)}`, Icon: Activity },
          { label: '上涨/下跌', value: `${breadth?.up ?? sentiment?.advancing ?? 0}/${breadth?.down ?? sentiment?.declining ?? 0}`, sub: `平盘 ${breadth?.flat ?? sentiment?.unchanged ?? 0}`, Icon: TrendingUp },
          { label: '成交额', value: `${formatNumber(volume?.amount ?? 0, 0)}${volume?.unit || '亿'}`, sub: `沪 ${formatNumber(volume?.sh_amount ?? 0, 0)} / 深 ${formatNumber(volume?.sz_amount ?? 0, 0)}`, Icon: Layers3 },
          { label: '短线强度', value: limitUp ? `${formatNumber(limitUp.price, 0)} 涨停` : '0 涨停', sub: ladder?.date ? `连板样本 ${ladder.date}` : '连板样本 --', Icon: Flame },
        ].map(({ label, value, sub, Icon }) => (
          <div key={label} className="rounded-lg border border-crypto-border bg-crypto-card p-4">
            <div className="mb-4 flex items-center justify-between">
              <span className="text-sm font-bold text-slate-400">{label}</span>
              <Icon className="h-4 w-4 text-blue-400" />
            </div>
            <div className="text-2xl font-black text-white">{value}</div>
            <div className="mt-3 text-xs font-semibold text-slate-500">{sub}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.25fr_0.75fr]">
        <div className="space-y-4">
          <Panel title="板块轮动" meta="当日涨幅靠前板块" icon={<Sparkles className="h-4 w-4" />}>
            {topConcepts.length > 0 ? (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-5">
                {topConcepts.map((item) => (
                  <div key={item.name} className="min-h-[116px] rounded-lg border border-crypto-border bg-crypto-bg/45 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-black text-white">{item.name}</span>
                      <span className="text-xs font-semibold text-slate-600">#{item.rank}</span>
                    </div>
                    <div className="mt-4 text-xl">
                      <Pct value={item.change_percent} />
                    </div>
                    <div className="mt-3 text-xs font-semibold text-slate-500">净流入 {formatNumber(item.net_inflow, 0)}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex min-h-[120px] items-center justify-center text-sm font-semibold text-slate-500">暂无板块轮动数据</div>
            )}
          </Panel>

          <Panel title="连板梯队" meta="短线情绪高度" icon={<Flame className="h-4 w-4" />}>
            {ladderLevels.length > 0 ? (
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                {ladderLevels.map((level) => (
                  <div key={`${level.today_level}-${level.today_count}`} className="rounded-lg border border-crypto-border bg-crypto-bg/45 p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <div className="text-lg font-black text-white">{level.today_level} 板</div>
                      <div className="text-sm font-bold text-blue-300">{level.today_count} 只</div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {level.today_items.slice(0, 8).map((stock) => (
                        <span key={`${stock.code}-${stock.name}`} className="rounded-md border border-crypto-border bg-slate-900 px-2 py-1 text-xs font-semibold text-slate-300">
                          {stock.name}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex min-h-[120px] items-center justify-center text-sm font-semibold text-slate-500">暂无连板梯队数据</div>
            )}
          </Panel>
        </div>

        <div className="space-y-4">
          <Panel title="今日复盘结论" meta="保存为盘后日志" icon={<NotebookPen className="h-4 w-4" />}>
            <div className="space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-[160px_1fr]">
                <input
                  type="date"
                  value={selectedDate}
                  onChange={(event) => setSelectedDate(event.target.value)}
                  className="h-9 rounded-md border border-crypto-border bg-crypto-bg px-3 text-sm font-semibold text-slate-200 outline-none focus:border-blue-500/60"
                />
                <input
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder="标题，如：2026-06-25 主线复盘"
                  className="h-9 rounded-md border border-crypto-border bg-crypto-bg px-3 text-sm font-semibold text-slate-200 outline-none placeholder:text-slate-600 focus:border-blue-500/60"
                />
              </div>
              <input
                value={mainTone}
                onChange={(event) => setMainTone(event.target.value)}
                placeholder={systemConclusion.mainTone}
                className="h-9 w-full rounded-md border border-crypto-border bg-crypto-bg px-3 text-sm font-semibold text-slate-200 outline-none placeholder:text-slate-600 focus:border-blue-500/60"
              />
              <input
                value={risk}
                onChange={(event) => setRisk(event.target.value)}
                placeholder={systemConclusion.risk}
                className="h-9 w-full rounded-md border border-crypto-border bg-crypto-bg px-3 text-sm font-semibold text-slate-200 outline-none placeholder:text-slate-600 focus:border-blue-500/60"
              />
              <textarea
                value={plan}
                onChange={(event) => setPlan(event.target.value)}
                placeholder={systemConclusion.plan}
                className="min-h-24 w-full resize-none rounded-md border border-crypto-border bg-crypto-bg px-3 py-2 text-sm font-semibold text-slate-200 outline-none placeholder:text-slate-600 focus:border-blue-500/60"
              />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={fillSystemConclusion}
                  className="inline-flex h-9 items-center gap-2 rounded-md border border-crypto-border bg-slate-800 px-3 text-sm font-bold text-slate-300 transition-colors hover:border-blue-500/50"
                >
                  <BookOpenCheck className="h-4 w-4" />
                  用系统结论填充
                </button>
                <button
                  type="button"
                  onClick={saveNote}
                  disabled={saving}
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-3 text-sm font-bold text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  保存复盘日志
                </button>
              </div>
            </div>
          </Panel>

          <Panel title="风险提示" meta="盘后检查项" icon={<ShieldAlert className="h-4 w-4" />}>
            <div className="space-y-3 text-sm font-semibold text-slate-400">
              <div>主线方向：{mainTone || systemConclusion.mainTone}</div>
              <div>风险提示：{risk || systemConclusion.risk}</div>
              <div>次日计划：{plan || systemConclusion.plan}</div>
            </div>
          </Panel>

          <Panel title="历史复盘日志" meta={`${notes.length} 条`} icon={<CalendarDays className="h-4 w-4" />}>
            {notes.length > 0 ? (
              <div className="space-y-2">
                {notes.map((note) => (
                  <div key={note.note_date} className="rounded-lg border border-crypto-border bg-crypto-bg/45 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="truncate text-sm font-black text-white">{note.title}</span>
                      <span className="shrink-0 text-xs font-semibold text-slate-500">{note.note_date}</span>
                    </div>
                    <div className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">{note.content}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-sm font-semibold text-slate-500">暂无已保存复盘日志</div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

export default DailyReview;
