import { useMemo, useState } from "react";
import clsx from "clsx";
import {
  Eye,
  FastForward,
  FlaskConical,
  PauseCircle,
  PlayCircle,
  Plus,
  Search,
  Square,
} from "lucide-react";
import type { PaperRuntimeInstance } from "../types";
import { marketToneClass } from "../utils/marketColors";
import {
  OperatorPageHeader,
  OperatorSearchField,
  SegmentedControl,
} from "./OperatorShell";
import { ConfirmDialog } from "./ConfirmDialog";

type StatusFilter = "all" | "running" | "paused" | "stopped";
type SortMode = "created" | "return";
type LifecycleAction = "start" | "pause" | "resume" | "stop";

const HEARTBEAT_SLA_MS = 15 * 60 * 1000;

const numberValue = (value: unknown) => {
  // Number(null) === 0 in JS — treat missing values as unknown, never as zero equity.
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const compactMoney = (value: unknown) => {
  const parsed = numberValue(value);
  if (parsed === null) return "--";
  const abs = Math.abs(parsed);
  const trim = (input: number) =>
    Number.isInteger(input) ? String(input) : input.toFixed(1);
  if (abs >= 1e8) return `¥${trim(parsed / 1e8)}亿`;
  if (abs >= 1e4) return `¥${trim(parsed / 1e4)}万`;
  return `¥${parsed.toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`;
};

const signedMoney = (value: number | null) => {
  if (value === null) return "--";
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}¥${Math.abs(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
};

const signedPercent = (value: number | null) =>
  value === null ? "--" : `${value > 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;

const createdDate = (value: string | null | undefined) =>
  value ? String(value).slice(0, 10) : "未记录";

const heartbeatState = (instance: PaperRuntimeInstance) => {
  if (instance.status !== "running") return instance.status;
  const heartbeat = instance.heartbeat_at
    ? new Date(instance.heartbeat_at).getTime()
    : Number.NaN;
  return !Number.isFinite(heartbeat) || Date.now() - heartbeat > HEARTBEAT_SLA_MS
    ? "stale"
    : "running";
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

const resolveEquity = (instance: PaperRuntimeInstance) => {
  // Prefer sealed equity snapshots; before the first valuation cycle, cash_balance
  // is the truthful account equity (cash-only book with no fills).
  return (
    numberValue(instance.equity) ??
    numberValue(instance.cash_balance) ??
    numberValue(instance.initial_cash)
  );
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

const metricsOf = (instance: PaperRuntimeInstance) => {
  const equity = resolveEquity(instance);
  const initial = numberValue(instance.initial_cash);
  const pnl = equity !== null && initial !== null ? equity - initial : null;
  const returnRate =
    pnl !== null && initial !== null && initial > 0 ? pnl / initial : null;
  return { pnl, returnRate };
};

function InstanceStatusPill({ instance }: { instance: PaperRuntimeInstance }) {
  const runtime = heartbeatState(instance);
  if (runtime === "running") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
        <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.8)]" />
        运行中
      </span>
    );
  }
  if (runtime === "stale") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-300">
        <span className="h-2 w-2 rounded-full bg-amber-400" />
        心跳陈旧
      </span>
    );
  }
  const dot =
    runtime === "failed" || runtime === "stopped"
      ? "bg-red-400"
      : "bg-slate-500";
  const tone =
    runtime === "failed" || runtime === "stopped"
      ? "border-red-500/25 bg-red-500/10 text-red-300"
      : "border-crypto-border bg-crypto-bg text-slate-400";
  return (
    <span
      className={clsx(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-semibold",
        tone,
      )}
    >
      <span className={clsx("h-2 w-2 rounded-full", dot)} />
      {statusLabel[runtime] ?? runtime}
    </span>
  );
}

interface PaperInstanceDashboardProps {
  instances: PaperRuntimeInstance[];
  loaded: boolean;
  busy: boolean;
  onCreate: () => void;
  onOpenDetail: (instance: PaperRuntimeInstance) => void;
  onAction: (
    instance: PaperRuntimeInstance,
    action: LifecycleAction,
  ) => void;
  onAdvanceAll?: () => void;
  advancing?: boolean;
}

export function PaperInstanceDashboard({
  instances,
  loaded,
  busy,
  onCreate,
  onOpenDetail,
  onAction,
  onAdvanceAll,
  advancing = false,
}: PaperInstanceDashboardProps) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [sort, setSort] = useState<SortMode>("created");
  const [pending, setPending] = useState<{
    instance: PaperRuntimeInstance;
    action: LifecycleAction;
  } | null>(null);

  const counts = useMemo(
    () => ({
      all: instances.length,
      running: instances.filter((item) => item.status === "running").length,
      paused: instances.filter((item) => item.status === "paused").length,
      stopped: instances.filter((item) => item.status === "stopped").length,
    }),
    [instances],
  );

  const visible = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return [...instances]
      .filter((instance) => status === "all" || instance.status === status)
      .filter((instance) =>
        normalized
          ? instance.name.toLowerCase().includes(normalized)
          : true,
      )
      .sort((left, right) => {
        if (sort === "return") {
          const leftReturn = metricsOf(left).returnRate;
          const rightReturn = metricsOf(right).returnRate;
          return (
            (rightReturn ?? -Infinity) - (leftReturn ?? -Infinity)
          );
        }
        return (
          new Date(right.created_at ?? 0).getTime() -
          new Date(left.created_at ?? 0).getTime()
        );
      });
  }, [instances, query, sort, status]);

  const confirmCopy = (
    instance: PaperRuntimeInstance,
    action: LifecycleAction,
  ): { title: string; message: string; confirmLabel: string; tone: "blue" | "danger" } => {
    if (action === "pause")
      return {
        title: "暂停实例",
        message: `确认暂停「${instance.name}」？暂停后实例不再处理收盘周期，指标停留在最后快照；可随时继续。`,
        confirmLabel: "暂停",
        tone: "blue",
      };
    if (action === "resume")
      return {
        title: "继续实例",
        message: `确认继续「${instance.name}」？实例将恢复处理收盘周期并更新权益快照。`,
        confirmLabel: "继续",
        tone: "blue",
      };
    if (action === "start")
      return {
        title: "启动实例",
        message: `确认启动「${instance.name}」？实例进入运行状态，按封存数据回放处理交易周期。`,
        confirmLabel: "启动",
        tone: "blue",
      };
    return {
      title: "关闭实例",
      message: `确认关闭「${instance.name}」？关闭后实例停止产生新信号与成交，已持久化的信号、订单、成交与权益记录会保留，之后可重新启动。`,
      confirmLabel: "关闭",
      tone: "danger",
    };
  };

  const requestAction = (instance: PaperRuntimeInstance, action: LifecycleAction) => {
    setPending({ instance, action });
  };
  const pendingCopy = pending ? confirmCopy(pending.instance, pending.action) : null;

  return (
    <div className="space-y-4" data-testid="paper-instance-dashboard" data-operator-page="paper-dashboard">
      <OperatorPageHeader
        icon={FlaskConical}
        title="模拟盘"
        subtitle="已晋级策略版本的模拟实例监控；信号、订单、成交与权益全部来自 PostgreSQL 持久化记录，不触碰真实资金。"
        actions={
          <div className="flex items-center gap-2">
            {onAdvanceAll ? (
              <button
                type="button"
                onClick={onAdvanceAll}
                disabled={advancing || busy}
                title="按封存快照逐日补齐运行中实例的待处理周期；幂等，可重复执行"
                className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-crypto-border bg-crypto-card px-4 text-sm font-semibold text-slate-300 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                <FastForward className={clsx("h-4 w-4", advancing && "animate-pulse")} />
                {advancing ? "推进中…" : "批量推进周期"}
              </button>
            ) : null}
            <button
              type="button"
              onClick={onCreate}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-blue-600 px-5 text-sm font-semibold text-white hover:bg-blue-500"
            >
              <Plus className="h-4 w-4" />
              创建 Paper 实例
            </button>
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <SegmentedControl<StatusFilter>
          aria-label="实例状态筛选"
          value={status}
          onChange={setStatus}
          options={[
            { value: "all", label: "全部", count: counts.all },
            { value: "running", label: "运行中", count: counts.running, tone: "emerald" },
            { value: "paused", label: "暂停", count: counts.paused, tone: "amber" },
            { value: "stopped", label: "已停止", count: counts.stopped },
          ]}
        />
        <OperatorSearchField
          value={query}
          onChange={setQuery}
          placeholder="搜索实例名称"
          icon={<Search className="h-4 w-4" />}
        />
        <SegmentedControl<SortMode>
          aria-label="实例排序"
          size="sm"
          value={sort}
          onChange={setSort}
          options={[
            { value: "created", label: "创建时间↓" },
            { value: "return", label: "收益率↓" },
          ]}
        />
      </div>

      {!loaded ? (
        <div className="min-h-64 rounded-xl border border-crypto-border bg-crypto-card p-12 text-center text-sm text-slate-500">
          正在读取模拟实例…
        </div>
      ) : visible.length ? (
        <div
          data-testid="paper-instance-grid"
          className="grid gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
        >
          {visible.map((instance) => {
            const { pnl, returnRate } = metricsOf(instance);
            const cycle = timeframe(instance);
            return (
              <article
                key={instance.id}
                data-testid="paper-instance-card"
                className="flex flex-col rounded-xl border border-crypto-border bg-crypto-card p-3 hover:border-slate-600"
              >
                <div className="flex items-start justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => onOpenDetail(instance)}
                    title={instance.name}
                    className="min-w-0 text-left"
                  >
                    <h3 className="truncate text-sm font-semibold text-slate-100">
                      {instance.name}
                    </h3>
                    <div className="mt-0.5 truncate text-[10px] text-slate-500">
                      A股模拟策略
                    </div>
                  </button>
                  <InstanceStatusPill instance={instance} />
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-1 text-[10px] text-slate-500">
                  <span className="rounded border border-crypto-border bg-crypto-bg px-1.5 py-0.5 tabular-nums text-slate-400">
                    {compactMoney(instance.initial_cash)}
                  </span>
                  <span className="rounded border border-crypto-border bg-crypto-bg px-1.5 py-0.5 text-slate-400">
                    {cycle || "周期未记录"}
                  </span>
                  <span className="tabular-nums">
                    创建 {createdDate(instance.created_at)}
                  </span>
                </div>

                <div className="mt-3 flex items-end justify-between gap-3 border-y border-white/[0.05] py-2.5">
                  <div className="min-w-0">
                    <div className="text-[10px] text-slate-600">收益率</div>
                    <div
                      className={clsx(
                        "font-mono text-2xl font-bold leading-7 tabular-nums",
                        marketToneClass(returnRate, "text-slate-500"),
                      )}
                    >
                      {signedPercent(returnRate)}
                    </div>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="text-[10px] text-slate-600">总盈亏</div>
                    <div
                      className={clsx(
                        "font-mono text-sm font-bold tabular-nums",
                        marketToneClass(pnl, "text-slate-500"),
                      )}
                    >
                      {signedMoney(pnl)}
                    </div>
                  </div>
                </div>

                <div className="mt-2 grid grid-cols-4 gap-1 text-center">
                  {(
                    [
                      ["夏普", null, "当前 Paper 实例列表未返回夏普指标"],
                      ["胜率", null, "当前 Paper 实例列表未返回已实现胜率"],
                      ["盈亏比", null, "当前 Paper 实例列表未返回盈亏比"],
                      [
                        "交易次数",
                        instance.trade_count === null ||
                          instance.trade_count === undefined
                          ? null
                          : String(instance.trade_count),
                        "PostgreSQL 模拟成交计数",
                      ],
                    ] as Array<[string, string | null, string]>
                  ).map(([label, metric, title]) => (
                    <div key={label} title={title} className="rounded-md bg-crypto-bg/50 px-1 py-1">
                      <div className="truncate font-mono text-[11px] font-semibold tabular-nums text-slate-300">
                        {metric ?? "—"}
                      </div>
                      <div className="mt-0.5 text-[9px] text-slate-600">{label}</div>
                    </div>
                  ))}
                </div>

                <div className="mt-2 grid grid-cols-3 gap-1.5">
                  {instance.status === "running" ? (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => requestAction(instance, "pause")}
                      className="inline-flex h-8 items-center justify-center gap-1 rounded-lg border border-amber-500/25 text-[11px] text-amber-200 disabled:opacity-40"
                    >
                      <PauseCircle className="h-3.5 w-3.5" />
                      暂停
                    </button>
                  ) : instance.status === "paused" ? (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => requestAction(instance, "resume")}
                      className="inline-flex h-8 items-center justify-center gap-1 rounded-lg border border-emerald-500/25 text-[11px] text-emerald-200 disabled:opacity-40"
                    >
                      <PlayCircle className="h-3.5 w-3.5" />
                      继续
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => requestAction(instance, "start")}
                      className="inline-flex h-8 items-center justify-center gap-1 rounded-lg border border-emerald-500/25 text-[11px] text-emerald-200 disabled:opacity-40"
                    >
                      <PlayCircle className="h-3.5 w-3.5" />
                      启动
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={
                      busy ||
                      !["running", "paused", "failed"].includes(instance.status)
                    }
                    onClick={() => requestAction(instance, "stop")}
                    className="inline-flex h-8 items-center justify-center gap-1 rounded-lg border border-red-500/25 text-[11px] text-red-200 disabled:opacity-35"
                  >
                    <Square className="h-3.5 w-3.5" />
                    关闭
                  </button>
                  <button
                    type="button"
                    onClick={() => onOpenDetail(instance)}
                    className="inline-flex h-8 items-center justify-center gap-1 rounded-lg bg-blue-600 text-[11px] font-semibold text-white"
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
          {instances.length
            ? "未找到匹配的模拟实例。"
            : "暂无运行实例。点击“创建 Paper 实例”进入创建向导。"}
        </div>
      )}

      <div className="text-[10px] text-slate-600">
        卡片指标随实例列表每 10 秒批量刷新、每 60 秒全量刷新；夏普、胜率和盈亏比在
        API 未提供时显示“—”，不会伪装为 0。
      </div>

      <ConfirmDialog
        open={pending !== null && pendingCopy !== null}
        title={pendingCopy?.title ?? ""}
        message={pendingCopy?.message ?? ""}
        confirmLabel={pendingCopy?.confirmLabel ?? "确认"}
        tone={pendingCopy?.tone ?? "blue"}
        busy={busy}
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (!pending) return;
          const { instance, action } = pending;
          setPending(null);
          onAction(instance, action);
        }}
      />
    </div>
  );
}
