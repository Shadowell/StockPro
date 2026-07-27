import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  BookOpenCheck,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Database,
  FileLock2,
  Layers3,
  NotebookPen,
  RefreshCw,
  Save,
  ShieldAlert,
} from "lucide-react";
import {
  assembleDailyReview,
  getDailyReview,
  getDailyReviewDates,
  saveDailyReview,
  sealDailyReview,
} from "../api/client";
import type { DailyReviewContext, DailyReviewItem } from "../types";
import { categoryLabel, statusLabel } from "../utils/presentation";

const TABS = [
  ["market", "市场复盘"],
  ["pools", "股票池复盘"],
  ["strategy", "策略复盘"],
  ["trades", "交易复盘"],
  ["logs", "日志"],
] as const;
type Tab = (typeof TABS)[number][0];
const panel = "rounded-xl border border-crypto-border bg-crypto-card";
const format = (value: unknown, digits = 2) =>
  value === null || value === undefined || value === ""
    ? "--"
    : Number.isFinite(Number(value))
      ? Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits })
      : String(value);
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
          按发生时间汇总市场、策略、风控与交易记录。
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
                  {item.title}
                </h3>
                <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-slate-500">
                  {categoryLabel(item.category)}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                {item.summary || "无补充摘要"}
              </p>
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

export function DailyReview() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") as Tab | null;
  const tab: Tab = TABS.some(([key]) => key === requested)
    ? requested!
    : "market";
  const [dates, setDates] = useState<string[]>([]);
  const [tradeDate, setTradeDate] = useState(
    params.get("date") ?? "",
  );
  const [context, setContext] = useState<DailyReviewContext | null>(null);
  const [summary, setSummary] = useState("");
  const [plan, setPlan] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const applyContext = (next: DailyReviewContext) => {
    setContext(next);
    setSummary(next.review?.summary ?? "");
    setPlan(next.review?.next_day_plan ?? "");
  };
  const load = async (date = tradeDate) => {
    setBusy(true);
    setError("");
    try {
      const available = await getDailyReviewDates();
      setDates(available.items);
      const target = date || available.items[0];
      if (!target) {
        setContext(null);
        setError("暂无可复盘交易日；未创建空白日期或伪造 0 指标");
        return;
      }
      if (!date) {
        setTradeDate(target);
        setParams({ tab, date: target });
      }
      const next = await getDailyReview(target);
      applyContext(next);
    } catch (reason) {
      setContext(null);
      setSummary("");
      setPlan("");
      setError(reason instanceof Error ? reason.message : "复盘证据加载失败");
    } finally {
      setBusy(false);
    }
  };
  const rebuild = async () => {
    setBusy(true);
    setError("");
    try {
      applyContext(await assembleDailyReview(tradeDate));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "重建时间线失败");
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  const changeDate = (date: string) => {
    setTradeDate(date);
    setParams({ tab, date });
    void load(date);
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
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };
  const seal = async () => {
    setBusy(true);
    try {
      setContext(await sealDailyReview(tradeDate));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "封存失败");
    } finally {
      setBusy(false);
    }
  };
  const marketItems = useMemo(
    () => (context?.items ?? []).filter((item) => item.category === "market"),
    [context],
  );
  const poolItems = useMemo(
    () => (context?.items ?? []).filter((item) => item.category === "pool"),
    [context],
  );
  const strategyItems = useMemo(
    () => (context?.items ?? []).filter((item) => item.category === "strategy"),
    [context],
  );
  const tradeItems = useMemo(
    () =>
      (context?.items ?? []).filter((item) =>
        ["risk", "order", "trade", "position", "performance"].includes(
          item.category,
        ),
      ),
    [context],
  );
  const metric = (code: string) =>
    context?.metrics.find((item) => item.metric_code === code)?.metric_value;
  const reviewStatus = error
    ? "加载失败"
    : busy && !context
      ? "读取中"
      : context
        ? statusLabel(context.status)
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

  return (
    <div
      className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8"
      data-testid="daily-review-workbench"
    >
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <NotebookPen className="h-7 w-7 text-fuchsia-400" />
            <h1 className="text-2xl font-black text-white">复盘中心</h1>
            <span
              className={`rounded-md border px-2 py-1 text-xs font-semibold ${reviewStatusTone}`}
            >
              {reviewStatus}
            </span>
          </div>
          <p className="mt-2 text-sm text-slate-500">
            汇总市场、股票池、策略、风险、订单、成交与账户表现。
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
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
            disabled={busy}
            className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-400 disabled:cursor-wait disabled:opacity-60"
          >
            <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
            重建时间线
          </button>
        </div>
      </header>
      <nav className="mb-5 flex overflow-x-auto rounded-xl border border-crypto-border bg-crypto-card p-1">
        {TABS.map(([key, label]) => (
          <button
            data-testid={`review-tab-${key}`}
            type="button"
            key={key}
            onClick={() => setParams({ tab: key, date: tradeDate })}
            className={`min-w-max flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold ${tab === key ? "bg-fuchsia-600 text-white" : "text-slate-500 hover:bg-slate-800/60 hover:text-white"}`}
          >
            {label}
          </button>
        ))}
      </nav>
      {error ? (
        <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">
          {error}
        </div>
      ) : null}
      <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        {[
          ["涨停数", metric("limit_up_count")],
          ["跌停数", metric("limit_down_count")],
          ["最高连板", metric("highest_board")],
          ["股票池快照", context ? context.counts.pool : undefined],
          ["策略信号", context ? context.counts.strategy : undefined],
          [
            "风险 / 成交",
            context
              ? `${context.counts.risk} / ${context.counts.trade}`
              : undefined,
          ],
        ].map(([label, current]) => (
          <div
            data-testid={`review-metric-${String(label)}`}
            key={String(label)}
            className={`${panel} p-4`}
          >
            <div className="text-xs text-slate-500">{label}</div>
            <div className="mt-2 text-xl font-black text-white">
              {format(current, 0)}
            </div>
          </div>
        ))}
      </div>
      {tab === "market" ? (
        <div className="space-y-5">
          <div className="grid gap-5 xl:grid-cols-2">
            <section className={`${panel} p-5`}>
              <h2 className="font-semibold text-white">板块轮动</h2>
              <p className="mt-2 text-sm text-slate-500">
                板块结论通过市场快照引用；未发布收益或资金流保持空值。
              </p>
              <div className="mt-4 flex items-center gap-2 text-xs text-blue-300">
                <Database className="h-4 w-4" />
                市场证据 {context ? marketItems.length : "--"} 个
              </div>
            </section>
            <section className={`${panel} p-5`}>
              <h2 className="font-semibold text-white">连板梯队</h2>
              <p className="mt-2 text-sm text-slate-500">
                最高连板 {format(metric("highest_board"), 0)} · 涨停{" "}
                {format(metric("limit_up_count"), 0)} · 跌停{" "}
                {format(metric("limit_down_count"), 0)}
              </p>
              <div className="mt-4 text-xs text-slate-600">
                计算版本与来源保留在复盘指标行。
              </div>
            </section>
          </div>
          <Timeline
            items={marketItems}
            empty={timelineEmpty("该日没有已发布市场证据")}
          />
        </div>
      ) : null}
      {tab === "pools" ? (
        <div className="space-y-5">
          <section className={`${panel} p-5`}>
            <div className="flex items-center gap-2">
              <Layers3 className="h-5 w-5 text-violet-400" />
              <h2 className="font-semibold text-white">固定股票池变动</h2>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              展示成员数量、规则输入与完整性清单；回测和模拟盘只消费已封存快照。
            </p>
          </section>
          <Timeline
            items={poolItems}
            empty={timelineEmpty("该日没有股票池快照")}
          />
        </div>
      ) : null}
      {tab === "strategy" ? (
        <Timeline
          items={strategyItems}
          empty={timelineEmpty("该日没有 Paper 策略信号")}
        />
      ) : null}
      {tab === "trades" ? (
        <div className="space-y-5">
          <section className={`${panel} p-5`}>
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5 text-amber-400" />
              <h2 className="font-semibold text-white">信号到权益核对</h2>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              风险规则版本、订单时点、模拟成交和账本差均指向原对象。
            </p>
          </section>
          <Timeline
            items={tradeItems}
            empty={timelineEmpty("该日没有模拟执行记录")}
          />
        </div>
      ) : null}
      {tab === "logs" ? (
        <div className="grid gap-5 xl:grid-cols-[1.25fr_0.75fr]">
          <Timeline
            items={context?.items ?? []}
            empty={timelineEmpty("该日没有审计日志")}
          />
          <div className="space-y-5">
            <section className={`${panel} p-5`}>
              <div className="flex items-center gap-2">
                <BookOpenCheck className="h-5 w-5 text-fuchsia-400" />
                <h2 className="font-semibold text-white">复盘结论</h2>
              </div>
              <label className="mt-5 block text-xs text-slate-500">
                当日总结
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
                    className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-lg border border-crypto-border text-sm text-slate-300"
                  >
                    <Save className="h-4 w-4" />
                    保存草稿
                  </button>
                  <button
                    type="button"
                    onClick={() => void seal()}
                    className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-lg bg-fuchsia-600 text-sm font-semibold text-white"
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
                  <dd className="mt-1 text-slate-400">
                    {context?.status ?? "--"}
                  </dd>
                </div>
                <div>
                  <dt className="text-slate-600">时间线</dt>
                  <dd className="mt-1 flex items-center gap-2 text-slate-400">
                    <Clock3 className="h-3.5 w-3.5" />
                    {context ? context.items.length : "--"} 条记录
                  </dd>
                </div>
              </dl>
            </section>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default DailyReview;
