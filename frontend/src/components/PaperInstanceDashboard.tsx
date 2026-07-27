import { useMemo, useState } from "react";
import {
  Activity,
  ArrowDownUp,
  Eye,
  PauseCircle,
  PlayCircle,
  Plus,
  Search,
  Square,
  Star,
} from "lucide-react";
import clsx from "clsx";
import type { PaperRuntimeInstance } from "../types";
import { marketToneClass } from "../utils/marketColors";

type DataScope = "business" | "test";
type ListView = "preferred" | "all";
type StatusFilter = "all" | PaperRuntimeInstance["status"] | "stale";
type MarketFilter = "all" | "main" | "chinext" | "star" | "beijing";
type StrategyFilter = "all" | "factor" | "event" | "trend" | "portfolio";
type CapitalFilter = "all" | "small" | "medium" | "large";
type SortMode = "return" | "equity" | "trades" | "heartbeat";

const FAVORITES_KEY = "stockpro_paper_instance_favorites_v1";
const HEARTBEAT_SLA_MS = 15 * 60 * 1000;

const numberValue = (value: unknown) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const money = (value: unknown) => {
  const parsed = numberValue(value);
  return parsed === null
    ? "--"
    : `¥${parsed.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
};

const signedMoney = (value: number | null) => {
  if (value === null) return "--";
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}¥${Math.abs(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
};

const signedPercent = (value: number | null) =>
  value === null ? "--" : `${value > 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;

const timestamp = (value: string | null | undefined) =>
  value
    ? new Date(value).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "未记录";

const heartbeatState = (instance: PaperRuntimeInstance) => {
  if (instance.status !== "running") return instance.status;
  const heartbeat = instance.heartbeat_at
    ? new Date(instance.heartbeat_at).getTime()
    : Number.NaN;
  return !Number.isFinite(heartbeat) || Date.now() - heartbeat > HEARTBEAT_SLA_MS
    ? "stale"
    : "running";
};

const symbolsFor = (instance: PaperRuntimeInstance) => {
  const fromPositions = (instance.positions ?? [])
    .map((item) => String(item.symbol ?? "").trim())
    .filter(Boolean);
  const configured = instance.feed_config?.symbols;
  const fromConfig = Array.isArray(configured)
    ? configured.map(String).filter(Boolean)
    : [];
  return [...new Set([...fromPositions, ...fromConfig])];
};

const marketForSymbol = (symbol: string): Exclude<MarketFilter, "all"> | null => {
  const code = symbol.replace(/\D/g, "").slice(-6);
  if (/^(8|4)/.test(code)) return "beijing";
  if (/^68/.test(code)) return "star";
  if (/^30/.test(code)) return "chinext";
  if (/^(60|00)/.test(code)) return "main";
  return null;
};

const strategyType = (name: string): Exclude<StrategyFilter, "all"> | "other" => {
  const normalized = name.toLowerCase();
  if (/因子|factor/.test(normalized)) return "factor";
  if (/事件|涨停|event/.test(normalized)) return "event";
  if (/趋势|突破|动量|均线|trend|momentum/.test(normalized)) return "trend";
  if (/组合|轮动|portfolio|rotation/.test(normalized)) return "portfolio";
  return "other";
};

const capitalType = (instance: PaperRuntimeInstance): Exclude<CapitalFilter, "all"> => {
  const initial = numberValue(instance.initial_cash) ?? 0;
  if (initial <= 200_000) return "small";
  if (initial <= 1_000_000) return "medium";
  return "large";
};

const timeframe = (instance: PaperRuntimeInstance) =>
  String(
    instance.feed_config?.timeframe ??
      instance.feed_config?.bar_frequency ??
      instance.feed_config?.frequency ??
      "",
  )
    .trim()
    .toUpperCase();

const loadFavorites = () => {
  try {
    const parsed = JSON.parse(localStorage.getItem(FAVORITES_KEY) || "[]");
    return new Set<string>(Array.isArray(parsed) ? parsed.map(String) : []);
  } catch {
    return new Set<string>();
  }
};

const statusLabel: Record<string, string> = {
  running: "运行中",
  stale: "心跳陈旧",
  paused: "已暂停",
  stopped: "已停止",
  draft: "草稿",
  failed: "失败",
  starting: "启动中",
  stopping: "停止中",
};

interface PaperInstanceDashboardProps {
  instances: PaperRuntimeInstance[];
  allInstances: PaperRuntimeInstance[];
  dataScope: DataScope;
  loaded: boolean;
  busy: boolean;
  onScopeChange: (scope: DataScope) => void;
  onCreate: () => void;
  onOpenDetail: (instance: PaperRuntimeInstance) => void;
  onAction: (
    instance: PaperRuntimeInstance,
    action: "start" | "pause" | "resume" | "stop",
  ) => void;
}

export function PaperInstanceDashboard({
  instances,
  allInstances,
  dataScope,
  loaded,
  busy,
  onScopeChange,
  onCreate,
  onOpenDetail,
  onAction,
}: PaperInstanceDashboardProps) {
  const [listView, setListView] = useState<ListView>("all");
  const [favorites, setFavorites] = useState(loadFavorites);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [market, setMarket] = useState<MarketFilter>("all");
  const [strategy, setStrategy] = useState<StrategyFilter>("all");
  const [capital, setCapital] = useState<CapitalFilter>("all");
  const [sort, setSort] = useState<SortMode>("return");

  const metrics = (instance: PaperRuntimeInstance) => {
    const equity = numberValue(instance.equity);
    const initial = numberValue(instance.initial_cash);
    const pnl = equity !== null && initial !== null ? equity - initial : null;
    const returnRate = pnl !== null && initial !== null && initial > 0 ? pnl / initial : null;
    return { equity, pnl, returnRate };
  };

  const preferredIds = useMemo(() => {
    const next = new Set(favorites);
    instances.forEach((instance) => {
      const { returnRate } = metrics(instance);
      if (
        ["running", "paused"].includes(instance.status) &&
        returnRate !== null &&
        returnRate > 0.05
      ) {
        next.add(instance.id);
      }
    });
    return next;
  }, [favorites, instances]);

  const visible = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return [...instances]
      .filter((instance) => listView === "all" || preferredIds.has(instance.id))
      .filter((instance) => {
        const runtime = heartbeatState(instance);
        return status === "all" || status === runtime || status === instance.status;
      })
      .filter((instance) => {
        if (market === "all") return true;
        return symbolsFor(instance).some((symbol) => marketForSymbol(symbol) === market);
      })
      .filter(
        (instance) =>
          strategy === "all" || strategyType(instance.name) === strategy,
      )
      .filter(
        (instance) => capital === "all" || capitalType(instance) === capital,
      )
      .filter((instance) => {
        if (!normalized) return true;
        return [
          instance.name,
          statusLabel[heartbeatState(instance)],
          symbolsFor(instance).join(" "),
          timeframe(instance),
        ]
          .join(" ")
          .toLowerCase()
          .includes(normalized);
      })
      .sort((left, right) => {
        const leftMetrics = metrics(left);
        const rightMetrics = metrics(right);
        if (sort === "equity")
          return (rightMetrics.equity ?? -Infinity) - (leftMetrics.equity ?? -Infinity);
        if (sort === "trades")
          return Number(right.trade_count ?? 0) - Number(left.trade_count ?? 0);
        if (sort === "heartbeat")
          return (
            new Date(right.heartbeat_at ?? 0).getTime() -
            new Date(left.heartbeat_at ?? 0).getTime()
          );
        return (
          (rightMetrics.returnRate ?? -Infinity) -
          (leftMetrics.returnRate ?? -Infinity)
        );
      });
  }, [capital, instances, listView, market, preferredIds, query, sort, status, strategy]);

  const toggleFavorite = (instance: PaperRuntimeInstance) => {
    const next = new Set(favorites);
    if (next.has(instance.id)) next.delete(instance.id);
    else next.add(instance.id);
    setFavorites(next);
    localStorage.setItem(FAVORITES_KEY, JSON.stringify([...next]));
  };

  const control =
    "h-9 rounded-lg border border-crypto-border bg-crypto-card px-3 text-xs text-slate-300 outline-none focus:border-blue-500/60";

  return (
    <div className="space-y-5" data-testid="paper-instance-dashboard">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold text-white">
            <Activity className="h-6 w-6 text-blue-400" />
            策略实例控制台
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            管理多路 A 股模拟实例；仅使用 PostgreSQL 快照和模拟成交，不连接真实券商。
          </p>
        </div>
        <button
          type="button"
          onClick={onCreate}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-blue-600 px-5 text-sm font-semibold text-white hover:bg-blue-500"
        >
          <Plus className="h-4 w-4" />
          创建新模拟实例
        </button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          role="tablist"
          aria-label="模拟策略视图"
          className="inline-flex h-11 rounded-xl border border-crypto-border bg-crypto-card p-1"
        >
          {([
            ["preferred", "优选策略", preferredIds.size],
            ["all", "全部策略", instances.length],
          ] as const).map(([key, label, count]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={listView === key}
              onClick={() => setListView(key)}
              className={clsx(
                "inline-flex h-9 items-center gap-2 rounded-lg px-4 text-xs font-semibold",
                listView === key
                  ? key === "preferred"
                    ? "bg-yellow-500/15 text-yellow-200 ring-1 ring-yellow-400/20"
                    : "bg-blue-500/20 text-blue-200"
                  : "text-slate-500 hover:bg-white/5 hover:text-slate-200",
              )}
            >
              {key === "preferred" ? <Star className="h-3.5 w-3.5" /> : null}
              {label}
              <span className="rounded bg-crypto-bg px-1.5 py-0.5 text-[10px]">
                {count}
              </span>
            </button>
          ))}
        </div>
        <div className="inline-flex rounded-lg border border-crypto-border bg-crypto-card p-1 text-xs">
          <button
            type="button"
            data-testid="paper-scope-business"
            onClick={() => onScopeChange("business")}
            className={clsx(
              "rounded-md px-3 py-1.5 font-semibold",
              dataScope === "business" ? "bg-blue-600 text-white" : "text-slate-500",
            )}
          >
            业务实例{" "}
            {
              allInstances.filter(
                (item) => !item.data_purpose || item.data_purpose === "user",
              ).length
            }
          </button>
          <button
            type="button"
            data-testid="paper-scope-test"
            onClick={() => onScopeChange("test")}
            className={clsx(
              "rounded-md px-3 py-1.5 font-semibold",
              dataScope === "test"
                ? "bg-amber-500/15 text-amber-200"
                : "text-slate-500",
            )}
          >
            测试与验收{" "}
            {
              allInstances.filter(
                (item) => item.data_purpose && item.data_purpose !== "user",
              ).length
            }
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-crypto-border bg-crypto-card p-3">
        <select
          aria-label="市场范围"
          value={market}
          onChange={(event) => setMarket(event.target.value as MarketFilter)}
          className={control}
        >
          <option value="all">全部市场</option>
          <option value="main">主板</option>
          <option value="chinext">创业板</option>
          <option value="star">科创板</option>
          <option value="beijing">北交所</option>
        </select>
        <select
          aria-label="策略类型"
          value={strategy}
          onChange={(event) => setStrategy(event.target.value as StrategyFilter)}
          className={control}
        >
          <option value="all">全部策略</option>
          <option value="factor">因子</option>
          <option value="event">事件</option>
          <option value="trend">趋势</option>
          <option value="portfolio">组合</option>
        </select>
        <select
          aria-label="资金版本"
          value={capital}
          onChange={(event) => setCapital(event.target.value as CapitalFilter)}
          className={control}
        >
          <option value="all">全部资金</option>
          <option value="small">≤ 20万</option>
          <option value="medium">20万–100万</option>
          <option value="large">&gt; 100万</option>
        </select>
        <select
          aria-label="实例状态"
          value={status}
          onChange={(event) => setStatus(event.target.value as StatusFilter)}
          className={control}
        >
          <option value="all">全部状态</option>
          <option value="running">运行中</option>
          <option value="stale">心跳陈旧</option>
          <option value="paused">暂停</option>
          <option value="stopped">停止</option>
          <option value="draft">草稿</option>
          <option value="failed">失败</option>
        </select>
        <label className="relative min-w-[210px] flex-1">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-600" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索策略、证券或周期"
            className={`${control} w-full pl-9`}
          />
        </label>
        <label className="relative">
          <ArrowDownUp className="absolute left-3 top-2.5 h-4 w-4 text-slate-600" />
          <select
            aria-label="实例排序"
            value={sort}
            onChange={(event) => setSort(event.target.value as SortMode)}
            className={`${control} pl-9`}
          >
            <option value="return">收益率 ↓</option>
            <option value="equity">账户权益 ↓</option>
            <option value="trades">成交数 ↓</option>
            <option value="heartbeat">最近心跳 ↓</option>
          </select>
        </label>
      </div>

      {dataScope === "test" ? (
        <div className="rounded-lg border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-xs text-amber-100">
          当前只查看测试与验收实例，其盈亏和运行状态不代表业务模拟盘。
        </div>
      ) : null}

      {!loaded ? (
        <div className="min-h-64 rounded-xl border border-crypto-border bg-crypto-card p-12 text-center text-sm text-slate-500">
          正在读取模拟实例…
        </div>
      ) : visible.length ? (
        <div
          data-testid="paper-instance-grid"
          className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"
        >
          {visible.map((instance) => {
            const runtime = heartbeatState(instance);
            const running = instance.status === "running";
            const heartbeatStale = runtime === "stale";
            const { pnl, returnRate } = metrics(instance);
            const symbols = symbolsFor(instance);
            const autoPreferred = returnRate !== null && returnRate > 0.05;
            const favorite = favorites.has(instance.id);
            return (
              <article
                key={instance.id}
                data-testid="paper-instance-card"
                className="flex min-h-[292px] flex-col rounded-xl border border-crypto-border bg-crypto-card p-4 hover:border-slate-600"
              >
                <div className="flex items-start justify-between gap-3">
                  <button
                    type="button"
                    onClick={() => onOpenDetail(instance)}
                    className="min-w-0 text-left"
                  >
                    <h2 className="line-clamp-2 text-sm font-semibold text-yellow-200">
                      {instance.name}
                    </h2>
                    <div className="mt-1 text-[10px] text-slate-500">A股模拟策略</div>
                  </button>
                  <div className="flex shrink-0 items-start gap-2">
                    <button
                      type="button"
                      aria-label={favorite ? "取消优选" : "加入优选"}
                      title={
                        autoPreferred
                          ? "收益率 > 5%，已自动进入优选"
                          : favorite
                            ? "取消手动优选"
                            : "加入优选"
                      }
                      disabled={autoPreferred}
                      onClick={() => toggleFavorite(instance)}
                      className={clsx(
                        "rounded-lg p-1.5",
                        autoPreferred || favorite
                          ? "text-yellow-300"
                          : "text-slate-600 hover:bg-white/5 hover:text-yellow-200",
                      )}
                    >
                      <Star
                        className={clsx(
                          "h-4 w-4",
                          (autoPreferred || favorite) && "fill-current",
                        )}
                      />
                    </button>
                    {running ? (
                      <span
                        className="relative mt-1 flex h-4 w-4 items-center justify-center"
                        title="运行中"
                        aria-label="运行中"
                      >
                        <span className="absolute h-4 w-4 animate-ping rounded-full bg-emerald-400/40" />
                        <span className="relative h-2.5 w-2.5 rounded-full bg-emerald-400 shadow-[0_0_14px_rgba(52,211,153,0.85)]" />
                      </span>
                    ) : (
                      <span className={clsx(
                        "inline-flex min-w-12 justify-center rounded-full px-2 py-0.5 text-[10px] font-bold",
                        instance.status === "paused"
                          ? "bg-yellow-500/20 text-yellow-300"
                          : instance.status === "failed"
                            ? "bg-red-500/20 text-red-300"
                            : "bg-gray-700/50 text-gray-400",
                      )}>
                        {statusLabel[instance.status] ?? instance.status}
                      </span>
                    )}
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap gap-1.5 text-[10px]">
                  <span className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-1 text-slate-400">
                    {timeframe(instance) || "周期未记录"}
                  </span>
                  <span className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-1 text-slate-400">
                    {money(instance.initial_cash)}
                  </span>
                  {heartbeatStale ? (
                    <span className="rounded-md border border-amber-500/25 bg-amber-500/10 px-2 py-1 text-amber-300">
                      心跳待更新
                    </span>
                  ) : null}
                </div>

                <div
                  className="mt-3 truncate text-xs text-slate-500"
                  title={symbols.join(", ")}
                >
                  {symbols.length
                    ? `证券范围 ${symbols.slice(0, 3).join(" / ")}${symbols.length > 3 ? ` 等 ${symbols.length} 只` : ""}`
                    : "证券范围未记录"}
                </div>
                <div className="mt-1 text-[10px] text-slate-600">
                  最后心跳 {timestamp(instance.heartbeat_at)}
                </div>

                <div className="mt-4 grid grid-cols-2 gap-3 border-y border-white/[0.05] py-3">
                  <div>
                    <div className="text-[10px] text-slate-600">总盈亏</div>
                    <div
                      className={clsx(
                        "mt-1 font-mono text-lg font-bold",
                        marketToneClass(pnl, "text-slate-500"),
                      )}
                    >
                      {signedMoney(pnl)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-slate-600">收益率</div>
                    <div
                      className={clsx(
                        "mt-1 font-mono text-lg font-bold",
                        marketToneClass(returnRate, "text-slate-500"),
                      )}
                    >
                      {signedPercent(returnRate)}
                    </div>
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-4 gap-2 text-center">
                  {[
                    ["夏普", "未计算", "当前 Paper API 未返回夏普指标"],
                    ["胜率", "未计算", "当前 Paper API 未返回已实现胜率"],
                    ["盈亏比", "未计算", "当前 Paper API 未返回盈亏比"],
                    ["成交", String(instance.trade_count ?? 0), "PostgreSQL 模拟成交计数"],
                  ].map(([label, metric, title]) => (
                    <div key={label} title={title}>
                      <div className="truncate text-xs font-semibold text-slate-300">
                        {metric}
                      </div>
                      <div className="mt-1 text-[9px] text-slate-600">{label}</div>
                    </div>
                  ))}
                </div>

                <div className="mt-auto grid grid-cols-3 gap-2 pt-4">
                  {instance.status === "running" ? (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onAction(instance, "pause")}
                      className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-amber-500/25 text-xs text-amber-200 disabled:opacity-40"
                    >
                      <PauseCircle className="h-3.5 w-3.5" />
                      暂停交易
                    </button>
                  ) : instance.status === "paused" ? (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onAction(instance, "resume")}
                      className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-emerald-500/25 text-xs text-emerald-200 disabled:opacity-40"
                    >
                      <PlayCircle className="h-3.5 w-3.5" />
                      继续交易
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onAction(instance, "start")}
                      className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-emerald-500/25 text-xs text-emerald-200 disabled:opacity-40"
                    >
                      <PlayCircle className="h-3.5 w-3.5" />
                      启动交易
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={
                      busy || !["running", "paused", "failed"].includes(instance.status)
                    }
                    onClick={() => onAction(instance, "stop")}
                    className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-red-500/25 text-xs text-red-200 disabled:opacity-35"
                  >
                    <Square className="h-3.5 w-3.5" />
                    关闭交易
                  </button>
                  <button
                    type="button"
                    onClick={() => onOpenDetail(instance)}
                    className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg bg-blue-600 text-xs font-semibold text-white"
                  >
                    <Eye className="h-3.5 w-3.5" />
                    详情
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="min-h-64 rounded-xl border border-dashed border-crypto-border bg-crypto-card p-12 text-center text-sm text-slate-500">
          {listView === "preferred"
            ? "还没有优选策略。收益率超过 5% 的实例会自动进入，也可使用卡片星标手动加入。"
            : instances.length
              ? "未找到匹配的模拟实例。"
              : "暂无运行实例。点击“创建新模拟实例”进入创建向导。"}
        </div>
      )}

      <div className="text-[10px] text-slate-600">
        当前卡片仅展示已持久化权益和成交证据；夏普、胜率和盈亏比在 API 未提供时明确显示“未计算”，不会伪装为 0。
      </div>
    </div>
  );
}
