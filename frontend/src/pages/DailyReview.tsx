import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import clsx from "clsx";
import {
  CalendarDays,
  CheckCircle2,
  Clock3,
  FileLock2,
  NotebookPen,
  RefreshCw,
  Save,
  ShieldAlert,
  TrendingUp,
} from "lucide-react";
import {
  assembleDailyReview,
  getDailyReview,
  getDailyReviewDates,
  getLianbanLadder,
  getLimitBoard,
  getMarketOverview,
  getSectorFundFlow,
  getShortLineIndices,
  getThsHot,
  saveDailyReview,
  sealDailyReview,
} from "../api/client";
import { DiagnosticDetails } from "../components/DiagnosticDetails";
import {
  FilterChipGroup,
  MetricValue,
  OperatorMetricCard,
  OperatorPageHeader,
} from "../components/OperatorShell";
import { WorkspacePipelineNote } from "../components/WorkspacePipelineNote";
import { useResearchDesk } from "../components/ResearchDeskContext";
import { formatFreshnessTime, latestTimestamp } from "../utils/dataFreshness";
import { marketToneClass } from "../utils/marketColors";
import type { MetricTone } from "../utils/marketColors";
import { formatSymbolLabel } from "../utils/symbolDisplay";
import type {
  DailyReviewContext,
  DailyReviewItem,
  LianbanLadderResponse,
  LimitBoardResponse,
  MarketOverview,
  SectorFundFlowResponse,
  ThsHotItem,
} from "../types";
import { businessTextLabel, categoryLabel, statusLabel } from "../utils/presentation";

const panel = "rounded-xl border border-crypto-border bg-crypto-card";
const DASH = "—";

/** getShortLineIndices 的本地视图：client.ts 的 ShortLineIndex 未导出，且运行时负载含更多溯源字段。 */
type ShortLineRow = {
  code: string;
  name: string;
  price: number;
  change_percent?: number | null;
  change_amount?: number | null;
  updated_at?: string | null;
  trade_date?: string | null;
  data_state?: string | null;
  source_label?: string | null;
  unit?: string | null;
  definition?: string | null;
};

type Block<T> = { data: T | null; error: string; loading: boolean };

type SnapshotState = {
  overview: Block<MarketOverview>;
  shortLine: Block<ShortLineRow[]>;
  limitBoard: Block<LimitBoardResponse>;
  ladder: Block<LianbanLadderResponse>;
  fundFlow: Block<SectorFundFlowResponse>;
  thsHot: Block<ThsHotItem[]>;
};

const idleBlock = { data: null, error: "", loading: false };

const INDEX_ORDER = ["上证指数", "深证成指", "创业板指", "科创50", "北证50"];

const num = (value: unknown): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const fmt = (value: unknown, digits = 2) => {
  const parsed = num(value);
  if (parsed === null) return DASH;
  return parsed.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
};

const signed = (value: unknown, digits = 2) => {
  const parsed = num(value);
  if (parsed === null) return DASH;
  return `${parsed > 0 ? "+" : ""}${parsed.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
};

const toneText = (value: unknown) => marketToneClass(num(value) ?? undefined, "text-slate-400");

const Pct = ({ value }: { value?: number | null }) => {
  const parsed = num(value);
  if (parsed === null) {
    return <span className="font-mono text-slate-600 tabular-nums">{DASH}</span>;
  }
  return (
    <span className={clsx("font-mono text-xs tabular-nums", toneText(parsed))}>
      {parsed > 0 ? "+" : ""}
      {fmt(parsed, 2)}%
    </span>
  );
};

/** 日期串原样展示（YYYYMMDD 转为带连字符）；时间戳展示为 月/日 时:分。 */
const asOf = (value?: string | null) => {
  if (!value) return null;
  if (/^\d{8}$/.test(value)) {
    return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  }
  if (value.length <= 10) return value;
  return formatFreshnessTime(value);
};

/** TS 类型声明 hot，运行时负载为 hot_value（PG 列名）；两者都读，缺失显示 —。 */
const thsHotValue = (item: ThsHotItem) =>
  num(item.hot) ?? num((item as { hot_value?: number | null }).hot_value);

const reasonText = (reason: unknown, fallback: string) =>
  reason instanceof Error ? reason.message : fallback;

function BlockShell({
  title,
  subtitle,
  meta,
  loading,
  error,
  empty,
  emptyText = "暂无数据",
  children,
  className,
  testId,
}: {
  title: string;
  subtitle?: string;
  meta?: ReactNode;
  loading: boolean;
  error: string;
  empty: boolean;
  emptyText?: string;
  children: ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <section
      className={clsx(panel, "overflow-hidden", className)}
      data-testid={testId}
    >
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-crypto-border px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-bold text-slate-100">{title}</h2>
          {subtitle ? (
            <p className="mt-1 text-[11px] leading-4 text-slate-500">{subtitle}</p>
          ) : null}
        </div>
        {meta ? (
          <div className="shrink-0 text-right text-[10px] leading-4 text-slate-600">
            {meta}
          </div>
        ) : null}
      </header>
      <div className="p-4">
        {loading ? (
          <div className="flex min-h-28 items-center justify-center text-sm text-slate-500">
            正在读取…
          </div>
        ) : error ? (
          <div className="flex min-h-28 items-center justify-center px-4 text-center text-sm text-red-300">
            {error}
          </div>
        ) : empty ? (
          <div className="flex min-h-28 items-center justify-center px-4 text-center text-sm text-slate-600">
            {emptyText}
          </div>
        ) : (
          children
        )}
      </div>
    </section>
  );
}

function StatTile({
  label,
  value,
  tone = "blue",
  sub,
}: {
  label: string;
  value: ReactNode;
  tone?: MetricTone;
  sub?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-crypto-border bg-crypto-bg/45 p-3">
      <div className="text-[11px] text-slate-500">{label}</div>
      <MetricValue tone={tone} size="lg" className="mt-2 block">
        {value}
      </MetricValue>
      {sub ? <div className="mt-1 text-[10px] leading-4 text-slate-600">{sub}</div> : null}
    </div>
  );
}

const categoryTone: Record<string, string> = {
  market: "bg-blue-500",
  pool: "bg-violet-500",
  strategy: "bg-cyan-500",
  risk: "bg-amber-500",
  order: "bg-orange-500",
  trade: "bg-emerald-500",
  performance: "bg-fuchsia-500",
  system: "bg-slate-500",
};

function Timeline({
  items,
  empty,
}: {
  items: DailyReviewItem[];
  empty: string;
}) {
  return (
    <section className={`${panel} overflow-hidden`}>
      <div className="border-b border-crypto-border px-5 py-4">
        <h2 className="font-semibold text-white">交易日时间线</h2>
        <p className="mt-1 text-xs text-slate-500">
          按发生时间汇总市场、股票池、策略、风控与交易记录，逐条指向原对象。
        </p>
      </div>
      <div className="divide-y divide-white/[0.04]">
        {items.map((item) => (
          <article
            key={item.item_key}
            className="grid gap-3 px-5 py-4 sm:grid-cols-[90px_14px_1fr_170px]"
          >
            <time className="font-mono text-xs text-slate-500">
              {new Date(item.occurred_at).toLocaleTimeString("zh-CN", {
                hour12: false,
                hour: "2-digit",
                minute: "2-digit",
              })}
            </time>
            <span
              className={`mt-1.5 h-2.5 w-2.5 rounded-full ${categoryTone[item.category] ?? "bg-slate-500"}`}
            />
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold text-slate-200">
                  {businessTextLabel(item.title)}
                </h3>
                <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-slate-500">
                  {categoryLabel(item.category)}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                {businessTextLabel(item.summary, "无补充摘要")}
              </p>
              <DiagnosticDetails
                ariaLabel="时间线诊断原值"
                fields={[
                  ["title", item.title],
                  ["summary", item.summary],
                  ["source_object_type", item.source_object_type],
                  ["source_object_id", item.source_object_id],
                  ["resolution_status", item.resolution_status],
                ]}
              />
            </div>
            {item.source_route ? (
              <Link
                to={item.source_route}
                className="self-center text-right text-xs text-blue-300 hover:text-blue-200"
              >
                查看关联记录 →
              </Link>
            ) : (
              <span className="self-center text-right text-xs text-amber-400">
                {statusLabel(item.resolution_status, "待处理")}
              </span>
            )}
          </article>
        ))}
        {items.length === 0 ? (
          <div className="p-16 text-center text-sm text-slate-600">{empty}</div>
        ) : null}
      </div>
    </section>
  );
}

const EVIDENCE_FILTERS = [
  ["all", "全部"],
  ["market", "市场"],
  ["pool", "股票池"],
  ["strategy", "策略"],
  ["execution", "交易执行"],
] as const;
type EvidenceFilter = (typeof EVIDENCE_FILTERS)[number][0];

const EXECUTION_CATEGORIES = ["risk", "order", "trade", "position", "performance"];

export function DailyReview() {
  const { desk } = useResearchDesk();
  const [params, setParams] = useSearchParams();
  const [dates, setDates] = useState<string[]>([]);
  const [tradeDate, setTradeDate] = useState(params.get("date") ?? "");
  const [context, setContext] = useState<DailyReviewContext | null>(null);
  const [summary, setSummary] = useState("");
  const [plan, setPlan] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [evidenceFilter, setEvidenceFilter] = useState<EvidenceFilter>("all");
  const [snap, setSnap] = useState<SnapshotState>({
    overview: { ...idleBlock },
    shortLine: { ...idleBlock },
    limitBoard: { ...idleBlock },
    ladder: { ...idleBlock },
    fundFlow: { ...idleBlock },
    thsHot: { ...idleBlock },
  });

  const applyContext = useCallback((next: DailyReviewContext) => {
    setContext(next);
    setSummary(next.review?.summary ?? "");
    setPlan(next.review?.next_day_plan ?? "");
  }, []);

  const load = useCallback(
    async (date?: string) => {
      setBusy(true);
      setError("");
      try {
        const available = await getDailyReviewDates();
        setDates(available.items);
        const requested = date ?? "";
        const target =
          requested ||
          (desk?.trade_date && available.items.includes(desk.trade_date)
            ? desk.trade_date
            : available.items[0]);
        if (!target) {
          setContext(null);
          setError("暂无可复盘交易日；未创建空白日期或伪造 0 指标");
          return;
        }
        if (!requested) {
          setTradeDate(target);
          setParams({ date: target });
        }
        applyContext(await getDailyReview(target));
      } catch (reason) {
        setContext(null);
        setSummary("");
        setPlan("");
        setError(reason instanceof Error ? reason.message : "复盘证据加载失败");
      } finally {
        setBusy(false);
      }
    },
    [applyContext, desk?.trade_date, setParams],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const changeDate = (date: string) => {
    setTradeDate(date);
    setParams({ date });
    void load(date);
  };

  const rebuild = async () => {
    setBusy(true);
    setError("");
    try {
      applyContext(await assembleDailyReview(tradeDate));
    } catch (reason) {
      setError(reasonText(reason, "重建时间线失败"));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    try {
      const next = await saveDailyReview(tradeDate, {
        summary,
        next_day_plan: plan,
      });
      setContext(next);
    } catch (reason) {
      setError(reasonText(reason, "保存失败"));
    } finally {
      setBusy(false);
    }
  };

  const seal = async () => {
    setBusy(true);
    try {
      setContext(await sealDailyReview(tradeDate));
    } catch (reason) {
      setError(reasonText(reason, "封存失败"));
    } finally {
      setBusy(false);
    }
  };

  // 大盘 Snapshot：所有行情块并行读取，块内独立 loading / error / empty。
  useEffect(() => {
    if (!tradeDate) return;
    let live = true;
    setSnap({
      overview: { data: null, error: "", loading: true },
      shortLine: { data: null, error: "", loading: true },
      limitBoard: { data: null, error: "", loading: true },
      ladder: { data: null, error: "", loading: true },
      fundFlow: { data: null, error: "", loading: true },
      thsHot: { data: null, error: "", loading: true },
    });
    const bind = <K extends keyof SnapshotState>(
      key: K,
      promise: Promise<SnapshotState[K]["data"]>,
      fallbackError: string,
    ) => {
      promise.then(
        (data) => {
          if (live) {
            setSnap((prev) => ({ ...prev, [key]: { data, error: "", loading: false } }));
          }
        },
        (reason: unknown) => {
          if (live) {
            setSnap((prev) => ({
              ...prev,
              [key]: { data: null, error: reasonText(reason, fallbackError), loading: false },
            }));
          }
        },
      );
    };
    bind("overview", getMarketOverview(), "大盘快照加载失败");
    bind("shortLine", getShortLineIndices(), "短线情绪指标加载失败");
    bind("limitBoard", getLimitBoard(tradeDate), "涨跌停名单加载失败");
    bind("ladder", getLianbanLadder(tradeDate), "连板天梯加载失败");
    bind("fundFlow", getSectorFundFlow(30), "板块资金流加载失败");
    bind("thsHot", getThsHot(10, tradeDate), "人气榜加载失败");
    return () => {
      live = false;
    };
  }, [tradeDate]);

  const overview = snap.overview.data;
  const shortLine = snap.shortLine.data;
  const limitBoard = snap.limitBoard.data;
  const ladder = snap.ladder.data;
  const fundFlow = snap.fundFlow.data;
  const thsHot = snap.thsHot.data;

  // 指数快照：按常用顺序排列，其余指数追加在尾部。
  const indices = useMemo(() => {
    const rows = overview?.indices ?? [];
    const ordered = INDEX_ORDER.map((name) => rows.find((item) => item.name === name))
      .filter((item) => item !== undefined);
    const extras = rows.filter(
      (item) => !INDEX_ORDER.includes(item.name) && !ordered.includes(item),
    );
    return [...ordered, ...extras];
  }, [overview]);

  const breadth = overview?.market_breadth;
  const sentiment = overview?.sentiment;
  const pulse = overview?.market_pulse;
  const volume = overview?.volume;
  const upCount = pulse?.advancing ?? breadth?.up ?? sentiment?.advancing ?? null;
  const downCount = pulse?.declining ?? breadth?.down ?? sentiment?.declining ?? null;
  const flatCount = pulse?.unchanged ?? breadth?.flat ?? sentiment?.unchanged ?? null;
  const ratioTone: MetricTone =
    num(pulse?.rise_fall_ratio) !== null
      ? (pulse!.rise_fall_ratio! >= 1 ? "up" : "down")
      : num(upCount) !== null && num(downCount) !== null && num(downCount) !== 0
        ? ((num(upCount)! / num(downCount)!) >= 1 ? "up" : "down")
        : "neutral";

  // 情绪指标：短线指标行按返回顺序展示（涨停/封板/涨跌比/创新高低等）。
  const shortLineMeta = useMemo(() => {
    const rows = shortLine ?? [];
    const sealed = rows.find((item) => item.data_state === "sealed_snapshot");
    return {
      asOf: asOf(latestTimestamp(rows) ?? sealed?.trade_date ?? null),
      source: sealed?.source_label ?? rows[0]?.source_label ?? null,
      tradeDate: sealed?.trade_date ?? null,
    };
  }, [shortLine]);

  const shortLineDigits = (unit?: string | null) =>
    unit === "percent" || unit === "ratio" ? 2 : 0;
  const shortLineSuffix = (unit?: string | null) =>
    unit === "boards" ? "板" : unit === "percent" ? "%" : "";

  // 涨停生态：炸板数 / 封板率来自短线指标行（ZB / FBL），存在才展示。
  const brokenRow = shortLine?.find(
    (item) => item.code === "ZB" || item.name.includes("炸板"),
  );
  const sealRateRow = shortLine?.find(
    (item) => item.code === "FBL" || item.name.includes("封板"),
  );

  const lianbanDistribution = useMemo(() => {
    const rows = limitBoard?.up ?? [];
    const buckets = new Map<number, number>();
    rows.forEach((item) => {
      const times = Math.max(1, Math.floor(num(item.limit_times) ?? 1));
      buckets.set(times, (buckets.get(times) ?? 0) + 1);
    });
    return [...buckets.entries()].sort((a, b) => b[0] - a[0]);
  }, [limitBoard]);

  const topBoards = useMemo(
    () =>
      [...(limitBoard?.up ?? [])]
        .sort(
          (a, b) =>
            (num(b.limit_times) ?? 1) - (num(a.limit_times) ?? 1) ||
            (num(b.change_percent) ?? -100) - (num(a.change_percent) ?? -100),
        )
        .slice(0, 6),
    [limitBoard],
  );

  const ladderLevels = useMemo(
    () =>
      [...(ladder?.levels ?? [])]
        .filter((level) => (level.today_items?.length ?? 0) > 0)
        .sort((a, b) => b.today_level - a.today_level),
    [ladder],
  );

  const topFlows = useMemo(() => (fundFlow?.rankings ?? []).slice(0, 8), [fundFlow]);
  const flowMax = useMemo(
    () =>
      Math.max(
        1,
        ...topFlows.map((item) => Math.abs(num(item.net_inflow_yi) ?? 0)),
      ),
    [topFlows],
  );

  const riskItems = useMemo(
    () => (context?.items ?? []).filter((item) => item.category === "risk"),
    [context],
  );

  const executionCount = useMemo(
    () =>
      EXECUTION_CATEGORIES.reduce(
        (total, category) => total + (context?.counts?.[category] ?? 0),
        0,
      ),
    [context],
  );

  const filteredItems = useMemo(() => {
    const items = context?.items ?? [];
    if (evidenceFilter === "all") return items;
    if (evidenceFilter === "execution") {
      return items.filter((item) =>
        EXECUTION_CATEGORIES.includes(item.category),
      );
    }
    return items.filter((item) => item.category === evidenceFilter);
  }, [context, evidenceFilter]);

  const count = (category: string) =>
    context ? (context.counts[category] ?? 0) : 0;
  // 证据未加载成功时计数未知：显示 -- 而不是伪装成 0。
  const evidenceCount = (id: EvidenceFilter): number | string => {
    if (!context) return "--";
    if (id === "all") return context.items.length;
    if (id === "execution") return executionCount;
    return count(id);
  };
  const reviewStatus = error
    ? "加载失败"
    : busy && !context
      ? "读取中"
      : context
        ? statusLabel(context.status, "数据就绪")
        : "未加载";
  const reviewStatusTone = error
    ? "border-red-500/25 bg-red-500/10 text-red-300"
    : context?.status === "sealed"
      ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300"
      : "border-amber-500/25 bg-amber-500/10 text-amber-300";
  const timelineEmpty = (empty: string) =>
    error
      ? "复盘证据加载失败"
      : busy && !context
        ? "正在读取复盘证据…"
        : context
          ? empty
          : "复盘证据尚未加载";

  const overviewMeta = overview ? (
    <>
      <div>
        来源 {overview.data_status?.source_label || "未记录"}
        {overview.session_label ? ` · ${overview.session_label}` : ""}
      </div>
      <div>
        指数缓存 {asOf(overview.data_status?.index_snapshot_updated_at) ?? DASH} · 个股缓存{" "}
        {asOf(overview.data_status?.stock_snapshot_updated_at) ?? DASH}
      </div>
    </>
  ) : null;

  return (
    <div
      className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8"
      data-testid="daily-review-workbench"
      data-operator-page="review"
    >
      <OperatorPageHeader
        icon={NotebookPen}
        title="复盘"
        subtitle="当天大盘 Snapshot：一屏读取指数、市场宽度、短线情绪、涨停生态、板块资金与人气榜，再落到当日结论、风险证据与次日计划。"
        actions={
          <div className="flex flex-wrap items-end gap-2">
            <span
              className={`h-fit self-center rounded-md border px-2 py-1 text-xs font-semibold ${reviewStatusTone}`}
            >
              {reviewStatus}
            </span>
            <label className="text-[11px] text-slate-500">
              交易日
              <select
                value={tradeDate}
                onChange={(event) => changeDate(event.target.value)}
                className="mt-1 block h-10 min-w-36 rounded-lg border border-crypto-border bg-crypto-card px-3 text-sm text-slate-200"
              >
                {dates.includes(tradeDate) ? null : (
                  <option value={tradeDate}>
                    {tradeDate || "暂无可用交易日"}
                  </option>
                )}
                {dates.map((date) => (
                  <option key={date} value={date}>
                    {date}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={() => void rebuild()}
              disabled={busy || !tradeDate}
              className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-400 disabled:cursor-wait disabled:opacity-60"
            >
              <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
              生成复盘
            </button>
          </div>
        }
      />
      <WorkspacePipelineNote stageId="review" />
      {error ? (
        <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">
          {error}
        </div>
      ) : null}

      {/* 大盘 Snapshot：所有块并行读取；未带日期参数的块使用实时缓存，块头标注数据时间。 */}
      <section className="space-y-4" data-testid="market-snapshot">
        <BlockShell
          title="指数快照"
          subtitle="主要指数点位、涨跌幅与涨跌额；实时缓存，未带所选交易日参数。"
          meta={overviewMeta}
          loading={snap.overview.loading}
          error={snap.overview.error}
          empty={indices.length === 0}
          emptyText="暂无指数缓存"
          testId="snapshot-indices"
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {indices.map((indexRow) => {
              const tone = marketToneClass(indexRow.change_percent, "text-slate-300");
              const metricTone: MetricTone =
                num(indexRow.change_percent) !== null
                  ? (indexRow.change_percent > 0 ? "up" : indexRow.change_percent < 0 ? "down" : "blue")
                  : "blue";
              return (
                <OperatorMetricCard
                  key={indexRow.name}
                  label={indexRow.name}
                  tone={metricTone}
                  value={fmt(indexRow.price)}
                  detail={
                    <span className="flex items-center gap-2 text-xs font-semibold tabular-nums">
                      <Pct value={indexRow.change_percent} />
                      <span className={tone}>{signed(indexRow.change_amount)}</span>
                    </span>
                  }
                />
              );
            })}
          </div>
        </BlockShell>

        <div className="grid gap-4 xl:grid-cols-3">
          <BlockShell
            title="市场宽度"
            subtitle="涨跌家数、涨跌比、中位涨跌幅、强弱带、涨停/跌停估算与两市成交额（实时缓存）。"
            meta={overviewMeta}
            className="xl:col-span-2"
            loading={snap.overview.loading}
            error={snap.overview.error}
            empty={
              upCount === null &&
              downCount === null &&
              pulse == null &&
              volume?.amount == null
            }
            emptyText="全市场实时快照未同步，暂无宽度指标"
            testId="snapshot-breadth"
          >
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
              <StatTile
                label="涨跌家数"
                value={`${fmt(upCount, 0)} / ${fmt(downCount, 0)}`}
                tone={ratioTone}
                sub={`平盘 ${fmt(flatCount, 0)}`}
              />
              {pulse?.rise_fall_ratio != null ? (
                <StatTile
                  label="涨跌比"
                  value={fmt(pulse.rise_fall_ratio, 2)}
                  tone={ratioTone}
                  sub="上涨家数 ÷ 下跌家数"
                />
              ) : null}
              {pulse?.median_change_percent != null ? (
                <StatTile
                  label="中位涨跌幅"
                  value={`${signed(pulse.median_change_percent, 2)}%`}
                  tone={num(pulse.median_change_percent)! > 0 ? "up" : num(pulse.median_change_percent)! < 0 ? "down" : "neutral"}
                  sub={`均值 ${signed(pulse.avg_change_percent, 2)}%`}
                />
              ) : null}
              <StatTile
                label="强势带 ≥5% / ≥7%"
                value={`${fmt(pulse?.strong_up_5, 0)} / ${fmt(pulse?.strong_up_7, 0)}`}
                tone="up"
                sub="短线攻击力 · 家数"
              />
              <StatTile
                label="弱势带 ≤-5% / ≤-7%"
                value={`${fmt(pulse?.weak_down_5, 0)} / ${fmt(pulse?.weak_down_7, 0)}`}
                tone="down"
                sub="抛压深度 · 家数"
              />
              <StatTile
                label="涨停估 / 跌停估"
                value={`${fmt(pulse?.limit_up_est, 0)} / ${fmt(pulse?.limit_down_est, 0)}`}
                tone={(num(pulse?.limit_up_est) ?? 0) >= (num(pulse?.limit_down_est) ?? 0) ? "up" : "down"}
                sub="按板块阈值估算 · 非交易所确认"
              />
              <StatTile
                label="两市成交额"
                value={
                  volume?.amount == null ? DASH : `${fmt(volume.amount, 0)}${volume.unit || "亿"}`
                }
                tone="blue"
                sub={`沪 ${fmt(volume?.sh_amount, 0)} · 深 ${fmt(volume?.sz_amount, 0)} · 北 ${fmt(volume?.bj_amount, 0)}（亿）`}
              />
            </div>
          </BlockShell>

          <BlockShell
            title="情绪指标"
            subtitle="短线指标行：涨停家数、封板率、涨跌比、创新高低、连续涨跌等。"
            meta={
              shortLineMeta.source || shortLineMeta.asOf ? (
                <>
                  {shortLineMeta.source ? <div>来源 {shortLineMeta.source}</div> : null}
                  {shortLineMeta.tradeDate ? <div>快照 {shortLineMeta.tradeDate}</div> : null}
                  <div>更新 {shortLineMeta.asOf ?? DASH}</div>
                </>
              ) : null
            }
            loading={snap.shortLine.loading}
            error={snap.shortLine.error}
            empty={(shortLine ?? []).length === 0}
            emptyText="当前既无有效实时短线缓存，也无封存市场证据"
            testId="snapshot-sentiment"
          >
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-1">
              {(shortLine ?? []).map((row) => (
                <div
                  key={`${row.code}-${row.name}`}
                  className="flex items-center justify-between gap-3 rounded-lg border border-crypto-border bg-crypto-bg/45 px-3 py-2"
                >
                  <div className="min-w-0">
                    <div className="truncate text-xs font-semibold text-slate-300">
                      {row.name}
                    </div>
                    {row.source_label ? (
                      <div
                        className="mt-0.5 truncate text-[10px] text-slate-600"
                        title={row.definition ?? row.source_label ?? undefined}
                      >
                        {row.source_label}
                      </div>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-2 font-mono text-sm tabular-nums">
                    <span className={toneText(row.price)}>
                      {fmt(row.price, shortLineDigits(row.unit))}
                      {shortLineSuffix(row.unit)}
                    </span>
                    {num(row.change_percent) !== null ? (
                      <Pct value={row.change_percent} />
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </BlockShell>
        </div>

        <div className="grid gap-4 xl:grid-cols-3">
          <BlockShell
            title="涨停生态"
            subtitle="涨跌停封存名单 + 连板分布与最高连板个股；右侧连板天梯按层级列代表个股。"
            meta={
              limitBoard || ladder ? (
                <>
                  {limitBoard?.trade_date ? (
                    <div>名单交易日 {limitBoard.trade_date}</div>
                  ) : null}
                  {limitBoard?.source_label ? (
                    <div>名单来源 {limitBoard.source_label}</div>
                  ) : null}
                  {limitBoard?.captured_at ? (
                    <div>捕获 {asOf(limitBoard.captured_at) ?? DASH}</div>
                  ) : null}
                  {ladder?.date ? (
                    <div>
                      天梯 {ladder.date}
                      {ladder.prev_date ? ` · 对比 ${ladder.prev_date}` : ""}
                    </div>
                  ) : null}
                </>
              ) : null
            }
            className="xl:col-span-2"
            loading={snap.limitBoard.loading}
            error={snap.limitBoard.error}
            empty={
              (limitBoard?.up?.length ?? 0) === 0 &&
              (limitBoard?.down?.length ?? 0) === 0
            }
            emptyText="当前封存交易日的涨跌停名单为 0 家；未封存时不使用涨跌幅估算替代"
            testId="snapshot-limit-ecology"
          >
            <div className="grid gap-4 lg:grid-cols-2">
              <div>
                <div className="grid grid-cols-2 gap-3">
                  <StatTile
                    label="涨停家数"
                    value={fmt(limitBoard?.counts?.up, 0)}
                    tone="up"
                    sub={`跌停 ${fmt(limitBoard?.counts?.down, 0)} 家`}
                  />
                  {sealRateRow ? (
                    <StatTile
                      label="封板率 / 炸板"
                      value={`${fmt(sealRateRow.price, 1)}% / ${fmt(brokenRow?.price, 0)}`}
                      tone="amber"
                      sub="涨停 ÷（涨停 + 炸板）· 短线指标缓存"
                    />
                  ) : brokenRow ? (
                    <StatTile
                      label="炸板数"
                      value={fmt(brokenRow.price, 0)}
                      tone="amber"
                      sub="短线指标缓存"
                    />
                  ) : null}
                </div>
                {lianbanDistribution.length > 0 ? (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {lianbanDistribution.map(([times, count]) => (
                      <span
                        key={times}
                        className={clsx(
                          "rounded-md border px-2 py-1 text-[11px] font-semibold tabular-nums",
                          times >= 3
                            ? "border-up/40 bg-up/10 text-up"
                            : "border-crypto-border bg-crypto-bg/60 text-slate-400",
                        )}
                      >
                        {times === 1 ? "首板" : `${times}板`} × {count}
                      </span>
                    ))}
                  </div>
                ) : null}
                {topBoards.length > 0 ? (
                  <div className="mt-3 space-y-1.5">
                    {topBoards.map((stock) => (
                      <div
                        key={stock.symbol}
                        className="flex items-center justify-between gap-3 rounded-lg border border-crypto-border bg-crypto-bg/45 px-3 py-1.5 text-xs"
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          <span className="truncate font-semibold text-slate-200">
                            {formatSymbolLabel(stock.symbol || stock.code, stock.name)}
                          </span>
                          {num(stock.limit_times) !== null && stock.limit_times! > 1 ? (
                            <span className="shrink-0 rounded bg-up/15 px-1.5 py-0.5 text-[10px] font-bold text-up tabular-nums">
                              {stock.limit_times}连板
                            </span>
                          ) : null}
                        </span>
                        <span className="flex shrink-0 items-center gap-2 font-mono text-xs tabular-nums">
                          <span className="text-slate-300">{fmt(stock.price)}</span>
                          <Pct value={stock.change_percent} />
                        </span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 className="flex items-center gap-1.5 text-xs font-bold text-slate-300">
                    <TrendingUp className="h-3.5 w-3.5 text-up" />
                    连板天梯
                  </h3>
                  <span className="text-[10px] text-slate-600">
                    {ladderLevels.length > 0 ? `${ladderLevels.length} 个层级` : DASH}
                  </span>
                </div>
                {snap.ladder.error ? (
                  <div className="flex min-h-24 items-center justify-center rounded-lg border border-crypto-border bg-crypto-bg/45 px-3 text-center text-xs text-red-300">
                    {snap.ladder.error}
                  </div>
                ) : snap.ladder.loading ? (
                  <div className="flex min-h-24 items-center justify-center text-xs text-slate-500">
                    正在读取连板天梯…
                  </div>
                ) : ladderLevels.length === 0 ? (
                  <div className="flex min-h-24 items-center justify-center px-3 text-center text-xs text-slate-600">
                    该日无连板天梯数据
                  </div>
                ) : (
                  <div className="max-h-72 overflow-y-auto rounded-lg border border-crypto-border">
                    <table className="w-full text-xs">
                      <thead className="sticky top-0 bg-crypto-card">
                        <tr className="text-left text-[10px] text-slate-600">
                          <th className="px-3 py-2 font-medium">层级</th>
                          <th className="px-2 py-2 font-medium">家数</th>
                          <th className="px-3 py-2 font-medium">代表个股</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/[0.04]">
                        {ladderLevels.map((level) => (
                          <tr key={level.today_level}>
                            <td
                              className={clsx(
                                "whitespace-nowrap px-3 py-2 font-mono font-bold tabular-nums",
                                level.today_level >= 3 ? "text-up" : "text-slate-300",
                              )}
                            >
                              {level.today_level === 1 ? "首板" : `${level.today_level}板`}
                            </td>
                            <td className="px-2 py-2 font-mono text-slate-400 tabular-nums">
                              {level.today_count}
                            </td>
                            <td className="px-3 py-2">
                              <div className="flex flex-wrap gap-x-2 gap-y-1">
                                {level.today_items.slice(0, 4).map((item) => (
                                  <span
                                    key={item.code}
                                    className="whitespace-nowrap text-slate-300"
                                  >
                                    {item.name}
                                    <span
                                      className={clsx(
                                        "ml-1 font-mono text-[10px] tabular-nums",
                                        toneText(item.change_percent),
                                      )}
                                    >
                                      {signed(item.change_percent, 2)}%
                                    </span>
                                  </span>
                                ))}
                                {level.today_items.length > 4 ? (
                                  <span className="text-[10px] text-slate-600">
                                    +{level.today_items.length - 4}
                                  </span>
                                ) : null}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          </BlockShell>

          <BlockShell
            title="人气榜"
            subtitle="同花顺人气榜 Top 10：排名、最新价、涨跌幅与热度。"
            meta={
              <div>
                来源 {(thsHot ?? [])[0]?.source_label || "同花顺人气榜"}
                <div>更新 {asOf(latestTimestamp(thsHot ?? [])) ?? DASH}</div>
              </div>
            }
            loading={snap.thsHot.loading}
            error={snap.thsHot.error}
            empty={(thsHot ?? []).length === 0}
            emptyText="暂无人气榜缓存"
            testId="snapshot-ths-hot"
          >
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-[10px] text-slate-600">
                    <th className="py-1 pr-2 font-medium">排名</th>
                    <th className="py-1 pr-2 font-medium">名称</th>
                    <th className="py-1 pr-2 text-right font-medium">最新价</th>
                    <th className="py-1 pr-2 text-right font-medium">涨跌幅</th>
                    <th className="py-1 pl-2 text-right font-medium">热度</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {(thsHot ?? []).map((item) => (
                    <tr key={`${item.code}-${item.rank}`}>
                      <td className="py-1.5 pr-2 font-mono text-slate-600 tabular-nums">
                        {item.rank}
                      </td>
                      <td className="py-1.5 pr-2">
                        <div className="font-semibold text-slate-200">{item.name}</div>
                        <div className="font-mono text-[10px] text-slate-600">{item.code}</div>
                      </td>
                      <td className="py-1.5 pr-2 text-right font-mono text-slate-300 tabular-nums">
                        {fmt(item.price)}
                      </td>
                      <td className="py-1.5 pr-2 text-right">
                        <Pct value={item.change_percent} />
                      </td>
                      <td className="py-1.5 pl-2 text-right font-mono text-amber-300 tabular-nums">
                        {fmt(thsHotValue(item), 0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </BlockShell>
        </div>

        <BlockShell
          title="板块资金"
          subtitle={`行业/概念主力净流入 TOP${topFlows.length || 8}：红为净流入、绿为净流出，条长为相对规模。`}
          meta={
            fundFlow ? (
              <>
                <div>来源 {fundFlow.source_label || "未记录"}</div>
                <div>
                  单位 {fundFlow.unit || "亿"} · 更新 {asOf(fundFlow.updated_at) ?? DASH}
                </div>
              </>
            ) : null
          }
          loading={snap.fundFlow.loading}
          error={snap.fundFlow.error}
          empty={topFlows.length === 0}
          emptyText="暂无板块资金流缓存"
          testId="snapshot-sector-flow"
        >
          <div className="grid gap-2 lg:grid-cols-2">
            {topFlows.map((item, index) => {
              const netYi = num(item.net_inflow_yi);
              const width = netYi === null ? 0 : Math.round((Math.abs(netYi) / flowMax) * 100);
              return (
                <div
                  key={item.name}
                  className="rounded-lg border border-crypto-border bg-crypto-bg/45 px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="font-mono text-[10px] text-slate-600 tabular-nums">
                        {index + 1}
                      </span>
                      <span className="truncate text-xs font-semibold text-slate-200">
                        {item.name}
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      <Pct value={item.change_percent} />
                      <span
                        className={clsx(
                          "font-mono text-[11px] tabular-nums",
                          toneText(netYi),
                        )}
                      >
                        {netYi === null
                          ? DASH
                          : `${signed(netYi, 2)}${fundFlow?.unit || "亿"}`}
                      </span>
                    </span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                    <div
                      className={clsx(
                        "h-full rounded-full",
                        netYi !== null && netYi > 0 ? "bg-up" : "bg-down",
                      )}
                      style={{ width: `${width}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </BlockShell>
      </section>

      {/* 复盘结论：保存/封存逻辑保持不变，位于 Snapshot 下方。 */}
      <div className="mt-6 grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <section className={`${panel} p-5`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="flex items-center gap-2 font-semibold text-white">
              <NotebookPen className="h-5 w-5 text-fuchsia-400" />
              复盘结论
            </h2>
            <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${reviewStatusTone}`}>
              {reviewStatus}
            </span>
          </div>
          <label className="mt-5 block text-xs text-slate-500">
            当日结论
            <textarea
              disabled={!context || context.status === "sealed"}
              value={summary}
              onChange={(event) => setSummary(event.target.value)}
              className="mt-2 min-h-28 w-full rounded-lg border border-crypto-border bg-crypto-bg p-3 text-sm text-slate-200 disabled:opacity-60"
            />
          </label>
          <label className="mt-4 block text-xs text-slate-500">
            次日计划
            <textarea
              disabled={!context || context.status === "sealed"}
              value={plan}
              onChange={(event) => setPlan(event.target.value)}
              className="mt-2 min-h-24 w-full rounded-lg border border-crypto-border bg-crypto-bg p-3 text-sm text-slate-200 disabled:opacity-60"
            />
          </label>
          {context && context.status !== "sealed" ? (
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                onClick={() => void save()}
                disabled={busy}
                className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-lg border border-crypto-border text-sm text-slate-300 disabled:cursor-wait disabled:opacity-60"
              >
                <Save className="h-4 w-4" />
                保存草稿
              </button>
              <button
                type="button"
                onClick={() => void seal()}
                disabled={busy}
                className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-lg bg-fuchsia-600 text-sm font-semibold text-white disabled:cursor-wait disabled:opacity-60"
              >
                <FileLock2 className="h-4 w-4" />
                封存复盘
              </button>
            </div>
          ) : context?.status === "sealed" ? (
            <div className="mt-4 flex items-center gap-2 text-sm text-emerald-300">
              <CheckCircle2 className="h-4 w-4" />
              复盘已封存，不可修改
            </div>
          ) : (
            <div className="mt-4 text-sm text-amber-300">
              复盘证据加载后才可保存或封存
            </div>
          )}
        </section>

        <div className="space-y-4">
          <section className={`${panel} p-5`}>
            <div className="flex items-center gap-2">
              <CalendarDays className="h-5 w-5 text-blue-400" />
              <h2 className="font-semibold text-white">复盘记录</h2>
            </div>
            <dl className="mt-4 space-y-3 text-xs">
              <div>
                <dt className="text-slate-600">交易日</dt>
                <dd className="mt-1 text-slate-400">
                  {context?.review?.trade_date ?? tradeDate}
                </dd>
              </div>
              <div>
                <dt className="text-slate-600">状态</dt>
                <dd className="mt-1 text-slate-400">{context?.status ?? DASH}</dd>
              </div>
              <div>
                <dt className="text-slate-600">时间线</dt>
                <dd className="mt-1 flex items-center gap-2 text-slate-400">
                  <Clock3 className="h-3.5 w-3.5" />
                  {context ? context.items.length : DASH} 条记录
                </dd>
              </div>
            </dl>
          </section>

          <section className={`${panel} p-5`}>
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5 text-amber-400" />
              <h2 className="font-semibold text-white">风险提示</h2>
            </div>
            <p className="mt-2 text-[11px] text-slate-600">
              当日风险类证据只读汇总；复盘接口未提供独立的风险文本字段。
            </p>
            {riskItems.length > 0 ? (
              <ul className="mt-3 space-y-2">
                {riskItems.map((item) => (
                  <li
                    key={item.item_key}
                    className="rounded-lg border border-amber-500/20 bg-amber-500/[0.04] px-3 py-2"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-xs font-semibold text-amber-200">
                        {businessTextLabel(item.title)}
                      </span>
                      {item.source_route ? (
                        <Link
                          to={item.source_route}
                          className="shrink-0 text-[10px] text-blue-300 hover:text-blue-200"
                        >
                          查看 →
                        </Link>
                      ) : null}
                    </div>
                    {item.summary ? (
                      <p className="mt-1 text-[11px] leading-4 text-slate-500">
                        {businessTextLabel(item.summary)}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-xs text-slate-600">
                {context ? "当日无风险类证据记录" : "复盘证据尚未加载"}
              </p>
            )}
          </section>
        </div>
      </div>

      {/* 证据对象列表：原五个子页签的证据合并为一个可筛选时间线。 */}
      <div className="mt-4 space-y-4">
        <FilterChipGroup<EvidenceFilter>
          aria-label="复盘证据类别筛选"
          options={EVIDENCE_FILTERS.map(([id, label]) => ({
            value: id,
            label,
            count: evidenceCount(id),
          }))}
          value={evidenceFilter}
          onChange={setEvidenceFilter}
        />
        <Timeline
          items={filteredItems}
          empty={timelineEmpty("该筛选下没有复盘证据")}
        />
      </div>
    </div>
  );
}

export default DailyReview;
