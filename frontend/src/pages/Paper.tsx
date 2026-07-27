import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import ReactECharts from "echarts-for-react";
import {
  Activity,
  BarChart3,
  CircleDollarSign,
  Database,
  Filter,
  Pause,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Square,
  WalletCards,
} from "lucide-react";
import {
  createPaperInstance,
  getPaperInstance,
  listBacktestRuns,
  listPaperInstances,
  paperInstanceAction,
  processPaperCycle,
} from "../api/client";
import type { BacktestRun, PaperRuntimeInstance } from "../types";

const TABS = [
  ["instances", "实例"],
  ["signals", "信号"],
  ["orders", "订单"],
  ["positions", "持仓"],
  ["trades", "成交"],
  ["account", "账户"],
  ["events", "事件"],
] as const;
type Tab = (typeof TABS)[number][0];
type StatusFilter = "all" | PaperRuntimeInstance["status"] | "stale";
type DataScope = "business" | "test";
const panel = "rounded-xl border border-crypto-border bg-crypto-card";
const input =
  "h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-slate-200 outline-none focus:border-blue-500/60";
const value = (current: unknown, digits = 2) =>
  current === null || current === undefined || current === ""
    ? "--"
    : Number.isFinite(Number(current))
      ? Number(current).toLocaleString("zh-CN", {
          maximumFractionDigits: digits,
        })
      : String(current);
const currency = (current: unknown) =>
  current === null || current === undefined || current === ""
    ? "--"
    : `¥${value(current)}`;
const percent = (current: unknown) =>
  current === null || current === undefined || !Number.isFinite(Number(current))
    ? "--"
    : `${(Number(current) * 100).toFixed(2)}%`;
const time = (current: unknown) =>
  current
    ? new Date(String(current)).toLocaleString("zh-CN", { hour12: false })
    : "--";
const feedSourceLabel = (current: unknown) =>
  current === "sealed_pg_snapshot" ? "历史数据快照" : value(current);
const feedModeLabel = (current: unknown) =>
  current === "recorded_replay" ? "历史回放" : value(current);
const PAPER_HEARTBEAT_SLA_MS = 15 * 60 * 1000;

const runtimePresentation = (
  instance: PaperRuntimeInstance,
  nowMs = Date.now(),
) => {
  if (instance.status !== "running")
    return { state: instance.status, label: instance.status, stale: false };
  const heartbeatMs = instance.heartbeat_at
    ? new Date(instance.heartbeat_at).getTime()
    : Number.NaN;
  const stale =
    !Number.isFinite(heartbeatMs) ||
    nowMs - heartbeatMs > PAPER_HEARTBEAT_SLA_MS;
  if (!stale) return { state: "running", label: "running", stale: false };
  return {
    state: "stale",
    label:
      instance.feed_config?.mode === "recorded_replay"
        ? "回放心跳陈旧"
        : "运行心跳陈旧",
    stale: true,
  };
};

const statusTone = (status: string) =>
  status === "running" || status === "success"
    ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300"
    : status === "failed" || status === "blocked" || status === "stale"
      ? "border-red-500/25 bg-red-500/10 text-red-300"
      : "border-amber-500/25 bg-amber-500/10 text-amber-300";

function Status({ instance }: { instance: PaperRuntimeInstance }) {
  const presentation = runtimePresentation(instance);
  return (
    <div className="min-w-0">
      <span
        className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusTone(presentation.state)}`}
      >
        {presentation.label}
      </span>
      <div
        className={`mt-1 truncate text-[10px] ${presentation.stale ? "text-red-300" : "text-slate-600"}`}
      >
        心跳 {time(instance.heartbeat_at)}
      </div>
    </div>
  );
}

function DataTable({
  rows,
  columns,
  empty,
}: {
  rows: Array<Record<string, unknown>>;
  columns: Array<[string, string]>;
  empty: string;
}) {
  return (
    <div className={`${panel} overflow-hidden`}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[900px] text-sm">
          <thead>
            <tr className="border-b border-crypto-border text-left text-xs text-slate-500">
              {columns.map(([key, label]) => (
                <th key={key} className="px-4 py-3 font-medium">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr
                key={String(row.id ?? index)}
                className="border-b border-white/[0.04] hover:bg-white/[0.02]"
              >
                {columns.map(([key]) => (
                  <td
                    key={key}
                    className="max-w-[320px] truncate px-4 py-3 font-mono text-xs text-slate-300"
                  >
                    {key.includes("_at") || key === "signal_time"
                      ? time(row[key])
                      : typeof row[key] === "object"
                        ? JSON.stringify(row[key])
                        : value(row[key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 ? (
        <div className="p-12 text-center text-sm text-slate-600">{empty}</div>
      ) : null}
    </div>
  );
}

function Metric({
  label,
  current,
  note,
  tone = "text-white",
}: {
  label: string;
  current: string;
  note?: string;
  tone?: string;
}) {
  return (
    <div className={`${panel} p-4`}>
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className={`mt-2 text-xl font-bold ${tone}`}>{current}</div>
      {note ? (
        <div className="mt-1 truncate text-[10px] text-slate-600">{note}</div>
      ) : null}
    </div>
  );
}

export function Paper() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") as Tab | null;
  const tab: Tab = TABS.some(([key]) => key === requested)
    ? requested!
    : "instances";
  const [instances, setInstances] = useState<PaperRuntimeInstance[]>([]);
  const [selected, setSelected] = useState<PaperRuntimeInstance | null>(null);
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [runId, setRunId] = useState("");
  const [name, setName] = useState("");
  const [initialCash, setInitialCash] = useState(1_000_000);
  const [cycleDate, setCycleDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [dataScope, setDataScope] = useState<DataScope>("business");

  const eligible = useMemo(
    () =>
      runs.filter(
        (item) =>
          (dataScope === "business"
            ? !item.data_purpose || item.data_purpose === "user"
            : Boolean(
                item.data_purpose && item.data_purpose !== "user",
              )) &&
          item.status === "success" &&
          item.run_mode === "full" &&
          item.promotion_status === "paper_eligible" &&
          item.factor_snapshot_id &&
          item.pool_snapshot_id &&
          item.research_protocol_id,
      ),
    [dataScope, runs],
  );
  const selectedRun = eligible.find((item) => item.id === runId);
  const scopedInstances = useMemo(
    () =>
      instances.filter((item) =>
        dataScope === "business"
          ? !item.data_purpose || item.data_purpose === "user"
          : Boolean(item.data_purpose && item.data_purpose !== "user"),
      ),
    [dataScope, instances],
  );
  const visibleInstances = useMemo(
    () =>
      scopedInstances.filter((item) => {
        const presentation = runtimePresentation(item);
        if (
          statusFilter !== "all" &&
          statusFilter !== presentation.state &&
          statusFilter !== item.status
        )
          return false;
        return `${item.name} ${item.id}`
          .toLowerCase()
          .includes(query.trim().toLowerCase());
      }),
    [query, scopedInstances, statusFilter],
  );
  const summary = useMemo(() => {
    const validEquity = scopedInstances.filter(
      (item) =>
        item.equity !== null &&
        item.equity !== undefined &&
        item.initial_cash !== null &&
        item.initial_cash !== undefined,
    );
    const totalEquity = validEquity.length
      ? validEquity.reduce((sum, item) => sum + Number(item.equity), 0)
      : null;
    const totalPnl = validEquity.length
      ? validEquity.reduce(
          (sum, item) => sum + Number(item.equity) - Number(item.initial_cash),
          0,
        )
      : null;
    return {
      running: scopedInstances.filter(
        (item) => item.status === "running" && !runtimePresentation(item).stale,
      ).length,
      stale: scopedInstances.filter((item) => runtimePresentation(item).stale).length,
      trades: scopedInstances.reduce((sum, item) => sum + (item.trade_count ?? 0), 0),
      totalEquity,
      totalPnl,
    };
  }, [scopedInstances]);

  const load = async (keepId?: string) => {
    setBusy(true);
    setError("");
    try {
      const [paper, backtests] = await Promise.all([
        listPaperInstances(),
        listBacktestRuns(200),
      ]);
      setInstances(paper.items);
      setRuns(backtests.items);
      const scopeInstances = paper.items.filter((item) =>
        dataScope === "business"
          ? !item.data_purpose || item.data_purpose === "user"
          : Boolean(item.data_purpose && item.data_purpose !== "user"),
      );
      const id =
        [
          keepId,
          selected?.id,
          params.get("instance"),
          scopeInstances[0]?.id,
        ].find(
          (candidate) =>
            Boolean(candidate) &&
            scopeInstances.some((item) => item.id === candidate),
        ) ?? undefined;
      setSelected(id ? await getPaperInstance(id) : null);
      if (!runId)
        setRunId(
          backtests.items.find(
            (item) =>
              (dataScope === "business"
                ? !item.data_purpose || item.data_purpose === "user"
                : Boolean(
                    item.data_purpose && item.data_purpose !== "user",
                  )) &&
              item.promotion_status === "paper_eligible" &&
              item.factor_snapshot_id &&
              item.pool_snapshot_id,
          )?.id ?? "",
        );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Paper 工作台加载失败",
      );
    } finally {
      setBusy(false);
      setLoaded(true);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  useEffect(() => {
    if (!loaded) return;
    let active = true;
    const next = scopedInstances[0];
    setSelected(null);
    setRunId(eligible[0]?.id ?? "");
    if (next) {
      getPaperInstance(next.id)
        .then((instance) => {
          if (active) setSelected(instance);
        })
        .catch((reason) => {
          if (active)
            setError(
              reason instanceof Error ? reason.message : "实例详情加载失败",
            );
        });
    }
    return () => {
      active = false;
    };
  }, [dataScope]);

  const chooseInstance = async (id: string) => {
    setBusy(true);
    setError("");
    try {
      setSelected(await getPaperInstance(id));
      setParams({ tab, instance: id });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "实例详情加载失败");
    } finally {
      setBusy(false);
    }
  };
  const create = async () => {
    const run = eligible.find((item) => item.id === runId);
    if (
      !run ||
      !run.factor_snapshot_id ||
      !run.pool_snapshot_id ||
      !run.research_protocol_id
    )
      return setError("请选择固定因子与股票池的 Paper Eligible 完整回测");
    setBusy(true);
    setError("");
    try {
      const created = await createPaperInstance({
        name: name || `${run.strategy_name ?? run.name} / Paper`,
        strategy_version_id: run.strategy_version_id,
        dataset_snapshot_id: run.dataset_snapshot_id,
        factor_snapshot_id: run.factor_snapshot_id,
        universe_snapshot_id: run.universe_snapshot_id,
        pool_snapshot_id: run.pool_snapshot_id,
        research_protocol_id: run.research_protocol_id,
        qualifying_backtest_run_id: run.id,
        initial_cash: initialCash,
      });
      setName("");
      await load(created.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
      setBusy(false);
    }
  };
  const action = async (next: "start" | "pause" | "resume" | "stop") => {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      await paperInstanceAction(selected.id, next);
      await load(selected.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "状态操作失败");
      setBusy(false);
    }
  };
  const replay = async () => {
    if (!selected || !cycleDate) return setError("请选择回放交易日");
    setBusy(true);
    setError("");
    try {
      await processPaperCycle(selected.id, {
        trade_date: cycleDate,
        data_available_at: `${cycleDate}T15:00:00+08:00`,
        observed_at: `${cycleDate}T15:01:00+08:00`,
      });
      await load(selected.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "周期处理失败");
      setBusy(false);
    }
  };

  const pnl =
    selected?.equity === null || selected?.equity === undefined
      ? null
      : Number(selected.equity) - Number(selected.initial_cash);
  const returnRate =
    pnl === null || Number(selected?.initial_cash) <= 0
      ? null
      : pnl / Number(selected?.initial_cash);
  const latestEquity = selected?.equity_snapshots?.at(-1);
  const equityOption = useMemo(
    () => ({
      backgroundColor: "transparent",
      animation: false,
      tooltip: {
        trigger: "axis",
        backgroundColor: "#111827",
        borderColor: "#334155",
        textStyle: { color: "#e5e7eb" },
      },
      grid: { left: 58, right: 18, top: 24, bottom: 32 },
      xAxis: {
        type: "category",
        data: (selected?.equity_snapshots ?? []).map((item) => item.trade_date),
        axisLabel: { color: "#64748b" },
        axisLine: { lineStyle: { color: "#334155" } },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: "#64748b" },
        splitLine: { lineStyle: { color: "rgba(51,65,85,.4)" } },
      },
      series: [
        {
          name: "账户权益",
          type: "line",
          showSymbol: true,
          data: (selected?.equity_snapshots ?? []).map((item) =>
            Number(item.equity),
          ),
          lineStyle: { color: "#3b82f6", width: 2 },
          itemStyle: { color: "#3b82f6" },
          areaStyle: { color: "rgba(59,130,246,.08)" },
        },
      ],
    }),
    [selected],
  );
  const rows = selected
    ? ((tab === "signals"
        ? selected.signals
        : tab === "orders"
          ? selected.orders
          : tab === "positions"
            ? selected.positions
            : tab === "trades"
              ? selected.trades
              : tab === "events"
                ? selected.events
                : []) ?? [])
    : [];

  return (
    <div
      className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8"
      data-testid="paper-runtime-workbench"
    >
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <WalletCards className="h-7 w-7 text-blue-400" />
            <h1 className="text-2xl font-black text-white">模拟盘</h1>
            <span className="rounded-md border border-amber-500/25 bg-amber-500/10 px-2 py-1 text-xs text-amber-300">
              无真实券商连接
            </span>
          </div>
          <p className="mt-2 text-sm text-slate-500">
            管理模拟策略实例、风险控制、订单成交与账户权益。
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load(selected?.id)}
          className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-400"
        >
          <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
          刷新
        </button>
      </header>

      <section
        className={`${panel} mb-5 flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3 text-xs`}
      >
        <div className="flex rounded-lg border border-crypto-border bg-crypto-bg p-1">
          <button
            type="button"
            data-testid="paper-scope-business"
            onClick={() => setDataScope("business")}
            className={`rounded-md px-3 py-1.5 font-semibold ${dataScope === "business" ? "bg-blue-600 text-white" : "text-slate-500 hover:text-slate-200"}`}
          >
            我的实例 {instances.filter((item) => !item.data_purpose || item.data_purpose === "user").length}
          </button>
          <button
            type="button"
            data-testid="paper-scope-test"
            onClick={() => setDataScope("test")}
            className={`rounded-md px-3 py-1.5 font-semibold ${dataScope === "test" ? "bg-amber-500/15 text-amber-200" : "text-slate-500 hover:text-slate-200"}`}
          >
            测试与验收 {instances.filter((item) => item.data_purpose && item.data_purpose !== "user").length}
          </button>
        </div>
        <span className="font-semibold text-slate-300">当前模式：模拟交易</span>
        <span className="text-slate-500">
          数据源：
          {selected
            ? feedSourceLabel(selected.feed_config?.provider ?? "未声明")
            : "实例未选择"}
        </span>
        <span className="text-slate-500">
          回放模式：
          {selected ? feedModeLabel(selected.feed_config?.mode ?? "未声明") : "--"}
        </span>
        <span className={summary.stale ? "text-red-300" : "text-slate-500"}>
          陈旧实例：{summary.stale}
        </span>
      </section>
      {dataScope === "test" ? (
        <div className="mb-5 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] px-4 py-3 text-xs text-amber-200/80" role="status">
          当前仅查看自动化验收与种子实例；其权益、盈亏、心跳和成交不会计入默认模拟盘统计。
        </div>
      ) : null}

      <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        <Metric
          label="模拟实例"
          current={value(scopedInstances.length, 0)}
          note={loaded ? "运行记录" : "加载中"}
        />
        <Metric
          label="健康运行"
          current={loaded ? value(summary.running, 0) : "--"}
          note="状态 + 心跳 SLA"
          tone="text-emerald-300"
        />
        <Metric
          label="心跳陈旧"
          current={loaded ? value(summary.stale, 0) : "--"}
          note="超过 15 分钟降级"
          tone={summary.stale ? "text-red-300" : "text-white"}
        />
        <Metric
          label="组合权益"
          current={currency(summary.totalEquity)}
          note="仅汇总有权益记录的实例"
        />
        <Metric
          label="累计盈亏"
          current={currency(summary.totalPnl)}
          note="权益 - 初始资金"
          tone={
            summary.totalPnl !== null && summary.totalPnl < 0
              ? "text-red-300"
              : "text-emerald-300"
          }
        />
        <Metric
          label="成交记录"
          current={loaded ? value(summary.trades, 0) : "--"}
          note="模拟成交"
        />
      </div>

      <div className="mb-5 grid gap-3 md:grid-cols-3">
        <div className={`${panel} p-4`}>
          <ShieldCheck className="h-5 w-5 text-emerald-400" />
          <div className="mt-3 text-sm font-semibold text-slate-200">
            实盘前置约束
          </div>
          <p className="mt-1 text-xs text-slate-600">
            样本外、容量、数据和固定快照全部通过才可创建。
          </p>
        </div>
        <div className={`${panel} p-4`}>
          <Database className="h-5 w-5 text-blue-400" />
          <div className="mt-3 text-sm font-semibold text-slate-200">
            T+1 / 100股
          </div>
          <p className="mt-1 text-xs text-slate-600">
            收盘信号最早下一交易日成交，买入当日不可卖。
          </p>
        </div>
        <div className={`${panel} p-4`}>
          <Activity className="h-5 w-5 text-amber-400" />
          <div className="mt-3 text-sm font-semibold text-slate-200">
            逐周期审计
          </div>
          <p className="mt-1 text-xs text-slate-600">
            signal → risk → order → trade → ledger 全链路可追溯。
          </p>
        </div>
      </div>

      <nav
        className="mb-5 flex overflow-x-auto rounded-xl border border-crypto-border bg-crypto-card p-1"
        aria-label="Paper 二级导航"
      >
        {TABS.map(([key, label]) => (
          <button
            data-testid={`paper-tab-${key}`}
            type="button"
            key={key}
            onClick={() =>
              setParams({
                tab: key,
                ...(selected ? { instance: selected.id } : {}),
              })
            }
            className={`min-w-max flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold ${tab === key ? "bg-blue-600 text-white" : "text-slate-500 hover:bg-slate-800/60 hover:text-white"}`}
          >
            {label}
          </button>
        ))}
      </nav>
      {error ? (
        <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">
          <strong>加载或操作失败：</strong>
          {error}；缺失数据未显示为 0。
        </div>
      ) : null}
      {!loaded && !error ? (
        <div className={`${panel} p-16 text-center text-sm text-slate-500`}>
          <RefreshCw className="mx-auto mb-3 h-5 w-5 animate-spin" />
          正在读取 Paper 运行记录…
        </div>
      ) : null}

      {loaded && tab === "instances" ? (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(340px,0.55fr)]">
          <section className={`${panel} overflow-hidden`}>
            <div className="border-b border-crypto-border px-5 py-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold text-white">Paper 实例</h2>
                  <p className="mt-1 text-xs text-slate-500">
                    状态机、游标、现金与审计计数统一展示；running
                    必须同时满足心跳 SLA。
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <label className="relative">
                    <Search className="absolute left-3 top-3 h-4 w-4 text-slate-600" />
                    <input
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="搜索实例"
                      className={`${input} w-48 pl-9`}
                    />
                  </label>
                  <label className="relative">
                    <Filter className="absolute left-3 top-3 h-4 w-4 text-slate-600" />
                    <select
                      value={statusFilter}
                      onChange={(event) =>
                        setStatusFilter(event.target.value as StatusFilter)
                      }
                      className={`${input} pl-9`}
                    >
                      <option value="all">全部状态</option>
                      <option value="running">健康运行</option>
                      <option value="stale">心跳陈旧</option>
                      <option value="draft">草稿</option>
                      <option value="paused">暂停</option>
                      <option value="stopped">已停止</option>
                      <option value="failed">失败</option>
                    </select>
                  </label>
                </div>
              </div>
            </div>
            <div
              data-testid="paper-instance-grid"
              className="divide-y divide-white/[0.04]"
            >
              {visibleInstances.map((item) => (
                <button
                  data-testid="paper-instance-card"
                  type="button"
                  key={item.id}
                  onClick={() => void chooseInstance(item.id)}
                  className={`grid w-full gap-3 p-4 text-left sm:grid-cols-[minmax(0,1fr)_150px_120px_130px_90px] ${selected?.id === item.id ? "bg-blue-500/[0.06]" : "hover:bg-white/[0.02]"}`}
                >
                  <div className="min-w-0">
                    <div className="truncate font-semibold text-slate-200">
                      {item.name}
                    </div>
                    {item.data_purpose !== "user" && item.data_purpose ? (
                      <span className="mt-1 inline-block rounded border border-amber-500/25 bg-amber-500/10 px-1.5 py-0.5 text-[9px] text-amber-300">
                        {item.data_purpose === "acceptance"
                          ? "验收数据"
                          : "种子数据"}
                      </span>
                    ) : null}
                    <div className="mt-1 truncate font-mono text-[10px] text-slate-600">
                      {item.id}
                    </div>
                    <div className="mt-1 text-[10px] text-slate-600">
                      最后交易日 {item.last_processed_trade_date ?? "--"}
                    </div>
                  </div>
                  <Status instance={item} />
                  <div>
                    <div className="text-[10px] text-slate-600">权益</div>
                    <div className="mt-1 font-mono text-slate-300">
                      {currency(item.equity)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-slate-600">
                      信号 / 订单 / 成交
                    </div>
                    <div className="mt-1 font-mono text-slate-300">
                      {value(item.signal_count, 0)} /{" "}
                      {value(item.order_count, 0)} /{" "}
                      {value(item.trade_count, 0)}
                    </div>
                  </div>
                  <div className="text-right text-xs font-semibold text-blue-300">
                    监控详情
                  </div>
                </button>
              ))}
              {visibleInstances.length === 0 ? (
                <div className="p-12 text-center text-sm text-slate-600">
                  {scopedInstances.length
                    ? "当前筛选下无实例"
                    : "尚无 Paper 实例；右侧仅在存在晋级回测时可创建。"}
                </div>
              ) : null}
            </div>
          </section>
          <section data-testid="paper-create-wizard" className={`${panel} p-5`}>
            <h2 className="font-semibold text-white">创建固定实例</h2>
            <p className="mt-1 text-xs text-slate-500">
              仅列出满足数据、风控与样本外要求的完整回测。
            </p>
            <div className="mt-5 grid grid-cols-3 gap-1 text-center text-[10px]">
              <span className="rounded bg-blue-500/15 px-2 py-2 text-blue-300">
                1 晋级回测
              </span>
              <span className="rounded bg-crypto-bg px-2 py-2 text-slate-500">
                2 A股风控
              </span>
              <span className="rounded bg-crypto-bg px-2 py-2 text-slate-500">
                3 Paper 草稿
              </span>
            </div>
            <label className="mt-5 block text-xs text-slate-500">
              晋级回测
              <select
                value={runId}
                onChange={(event) => setRunId(event.target.value)}
                className={`${input} mt-2 w-full`}
              >
                <option value="">请选择</option>
                {eligible.map((run) => (
                  <option key={run.id} value={run.id}>
                    {run.data_purpose !== "user" && run.data_purpose
                      ? `[${run.data_purpose === "acceptance" ? "验收" : "种子"}] `
                      : ""}
                    {run.name} · Pool #{run.pool_snapshot_id}
                  </option>
                ))}
              </select>
            </label>
            {selectedRun ? (
              <dl className="mt-3 grid grid-cols-2 gap-2 rounded-lg border border-crypto-border bg-crypto-bg p-3 text-[10px] text-slate-500">
                <div>
                  策略版本
                  <div className="mt-1 truncate text-slate-300">
                    {selectedRun.strategy_version_id.slice(0, 8)}
                  </div>
                </div>
                <div>
                  数据快照
                  <div className="mt-1 text-slate-300">
                    #{selectedRun.dataset_snapshot_id}
                  </div>
                </div>
                <div>
                  因子 / 股票池
                  <div className="mt-1 text-slate-300">
                    #{selectedRun.factor_snapshot_id} / #
                    {selectedRun.pool_snapshot_id}
                  </div>
                </div>
                <div>
                  成本 / 协议
                  <div className="mt-1 truncate text-slate-300">
                    {selectedRun.cost_model_name ?? selectedRun.cost_model_id}
                  </div>
                </div>
              </dl>
            ) : null}
            <label className="mt-4 block text-xs text-slate-500">
              实例名
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="自动使用策略名"
                className={`${input} mt-2 w-full`}
              />
            </label>
            <label className="mt-4 block text-xs text-slate-500">
              初始资金
              <input
                type="number"
                min={10000}
                step={10000}
                value={initialCash}
                onChange={(event) => setInitialCash(Number(event.target.value))}
                className={`${input} mt-2 w-full`}
              />
            </label>
            <div className="mt-4 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] p-3 text-[11px] leading-5 text-amber-200/70">
              新实例使用历史数据回放，不连接真实账户。
            </div>
            <button
              type="button"
              onClick={() => void create()}
              disabled={busy || !runId}
              className="mt-5 h-11 w-full rounded-lg bg-blue-600 text-sm font-semibold text-white disabled:opacity-40"
            >
              创建 Paper 草稿
            </button>
          </section>
        </div>
      ) : null}

      {selected && tab !== "instances" ? (
        <>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-crypto-border bg-crypto-card p-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <strong className="text-slate-100">{selected.name}</strong>
                <Status instance={selected} />
                <span className="rounded border border-crypto-border px-2 py-0.5 text-[10px] text-slate-500">
                  交易日 {selected.last_processed_trade_date ?? "--"}
                </span>
              </div>
              <div className="mt-1 font-mono text-[10px] text-slate-600">
                {selected.id}
              </div>
            </div>
            <div className="flex gap-2">
              {selected.status === "draft" || selected.status === "stopped" ? (
                <button
                  type="button"
                  onClick={() => void action("start")}
                  className="inline-flex h-9 items-center gap-2 rounded-lg bg-emerald-600 px-3 text-xs font-semibold text-white"
                >
                  <Play className="h-3.5 w-3.5" />
                  启动
                </button>
              ) : null}
              {selected.status === "running" ? (
                <button
                  type="button"
                  onClick={() => void action("pause")}
                  className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border px-3 text-xs text-slate-300"
                >
                  <Pause className="h-3.5 w-3.5" />
                  暂停
                </button>
              ) : null}
              {selected.status === "paused" ? (
                <button
                  type="button"
                  onClick={() => void action("resume")}
                  className="inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-3 text-xs text-white"
                >
                  <Play className="h-3.5 w-3.5" />
                  恢复
                </button>
              ) : null}
              {["running", "paused", "failed"].includes(selected.status) ? (
                <button
                  type="button"
                  onClick={() => void action("stop")}
                  className="inline-flex h-9 items-center gap-2 rounded-lg border border-red-500/30 px-3 text-xs text-red-300"
                >
                  <Square className="h-3.5 w-3.5" />
                  停止
                </button>
              ) : null}
            </div>
          </div>
          <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
            <Metric
              label="账户权益"
              current={currency(selected.equity)}
              note={`快照 ${latestEquity?.trade_date ?? "--"}`}
            />
            <Metric
              label="累计盈亏"
              current={currency(pnl)}
              tone={
                pnl !== null && pnl < 0 ? "text-red-300" : "text-emerald-300"
              }
            />
            <Metric
              label="累计收益"
              current={percent(returnRate)}
              tone={
                returnRate !== null && returnRate < 0
                  ? "text-red-300"
                  : "text-emerald-300"
              }
            />
            <Metric
              label="可用现金"
              current={currency(selected.cash_balance)}
            />
            <Metric
              label="持仓 / 可卖"
              current={`${value(selected.positions?.length ?? 0, 0)} / ${value(selected.positions?.reduce((sum, item) => sum + Number(item.available_quantity ?? 0), 0) ?? 0, 0)}`}
              note="T+1 可卖数量"
            />
            <Metric
              label="信号 / 订单 / 成交"
              current={`${value(selected.signal_count, 0)} / ${value(selected.order_count, 0)} / ${value(selected.trade_count, 0)}`}
            />
          </div>
        </>
      ) : null}

      {selected && tab === "signals" ? (
        <DataTable
          rows={rows}
          empty="尚无策略信号；这不是 0 信号结论，仅表示当前实例无持久化记录。"
          columns={[
            ["signal_time", "信号时间"],
            ["symbol", "证券"],
            ["signal_type", "方向"],
            ["strength", "强度"],
            ["status", "状态"],
            ["reason", "原因"],
          ]}
        />
      ) : null}
      {selected && tab === "orders" ? (
        <DataTable
          rows={rows}
          empty="尚无订单"
          columns={[
            ["created_at", "创建时间"],
            ["symbol", "证券"],
            ["side", "方向"],
            ["quantity", "数量"],
            ["price", "价格"],
            ["status", "状态"],
            ["risk_event_id", "风险证据"],
          ]}
        />
      ) : null}
      {selected && tab === "positions" ? (
        <DataTable
          rows={rows}
          empty="当前无持仓"
          columns={[
            ["symbol", "证券"],
            ["quantity", "数量"],
            ["available_quantity", "可卖"],
            ["avg_cost", "成本"],
            ["last_price", "现价"],
            ["market_value", "市值"],
            ["updated_at", "更新时间"],
          ]}
        />
      ) : null}
      {selected && tab === "trades" ? (
        <DataTable
          rows={rows}
          empty="尚无成交记录"
          columns={[
            ["traded_at", "成交时间"],
            ["symbol", "证券"],
            ["side", "方向"],
            ["quantity", "数量"],
            ["price", "价格"],
            ["amount", "金额"],
            ["commission", "佣金"],
            ["earliest_fill_at", "最早可成交"],
          ]}
        />
      ) : null}
      {selected && tab === "events" ? (
        <DataTable
          rows={rows}
          empty="尚无审计事件"
          columns={[
            ["occurred_at", "时间"],
            ["event_type", "类型"],
            ["level", "级别"],
            ["message", "消息"],
            ["cycle_id", "周期"],
          ]}
        />
      ) : null}
      {selected && tab === "account" ? (
        <div className="space-y-5">
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,0.7fr)]">
            <section className={`${panel} p-5`}>
              <div className="flex items-center gap-2">
                <BarChart3 className="h-5 w-5 text-blue-400" />
                <h2 className="font-semibold text-white">Paper 权益曲线</h2>
              </div>
              {selected.equity_snapshots?.length ? (
                <ReactECharts option={equityOption} style={{ height: 330 }} />
              ) : (
                <div className="flex h-[330px] items-center justify-center text-sm text-slate-600">
                  尚无权益快照，未绘制零值曲线
                </div>
              )}
            </section>
            <section className={`${panel} p-5`}>
              <h2 className="font-semibold text-white">运行证据与风控</h2>
              <dl className="mt-4 space-y-2 text-xs">
                {[
                  ["策略版本", selected.strategy_version_id],
                  [
                    "数据 / Universe",
                    `#${selected.dataset_snapshot_id} / #${selected.universe_snapshot_id}`,
                  ],
                  [
                    "因子 / 股票池",
                    `#${selected.factor_snapshot_id} / #${selected.pool_snapshot_id}`,
                  ],
                  ["晋级回测", selected.qualifying_backtest_run_id],
                  ["研究协议", selected.research_protocol_id],
                  [
                    "数据源",
                    feedSourceLabel(selected.feed_config?.provider ?? "未声明"),
                  ],
                  [
                    "回放模式",
                    feedModeLabel(selected.feed_config?.mode ?? "未声明"),
                  ],
                ].map(([label, current]) => (
                  <div
                    key={label}
                    className="flex justify-between gap-3 border-b border-white/[0.04] py-2"
                  >
                    <dt className="text-slate-500">{label}</dt>
                    <dd className="max-w-[190px] truncate font-mono text-slate-300">
                      {current}
                    </dd>
                  </div>
                ))}
              </dl>
              <div className="mt-4 grid grid-cols-2 gap-2">
                {[
                  [
                    "现金底线",
                    percent(selected.capacity_limits?.cash_floor_ratio),
                  ],
                  [
                    "单票上限",
                    percent(selected.capacity_limits?.max_single_symbol_weight),
                  ],
                  [
                    "参与率上限",
                    percent(selected.capacity_limits?.max_participation_ratio),
                  ],
                  ["回撤上限", percent(selected.capacity_limits?.max_drawdown)],
                  [
                    "日换手上限",
                    percent(selected.capacity_limits?.max_daily_turnover),
                  ],
                ].map(([label, current]) => (
                  <div
                    key={label}
                    className="rounded-lg border border-crypto-border bg-crypto-bg p-2"
                  >
                    <div className="text-[10px] text-slate-600">{label}</div>
                    <div className="mt-1 text-xs font-semibold text-slate-300">
                      {current}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>
          <section className={`${panel} p-5`}>
            <div className="flex flex-wrap items-end gap-3">
              <label className="text-xs text-slate-500">
                记录回放交易日
                <input
                  type="date"
                  value={cycleDate}
                  onChange={(event) => setCycleDate(event.target.value)}
                  className={`${input} mt-2 block`}
                />
              </label>
              <button
                type="button"
                onClick={() => void replay()}
                disabled={selected.status !== "running" || busy}
                className="h-10 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white disabled:opacity-40"
              >
                处理收盘周期
              </button>
              <span className="text-xs text-slate-600">
                按所选交易日处理模拟交易周期
              </span>
            </div>
          </section>
          <DataTable
            rows={
              (selected.cycles ?? []) as unknown as Array<
                Record<string, unknown>
              >
            }
            empty="尚无运行周期"
            columns={[
              ["trade_date", "交易日"],
              ["cycle_key", "周期键"],
              ["status", "状态"],
              ["signal_count", "信号"],
              ["order_count", "订单"],
              ["trade_count", "成交"],
              ["ledger_difference", "账本差"],
            ]}
          />
        </div>
      ) : null}
      {!selected && loaded && tab !== "instances" ? (
        <div className={`${panel} p-16 text-center text-slate-600`}>
          <CircleDollarSign className="mx-auto mb-3 h-8 w-8" />
          请先创建或选择 Paper 实例
        </div>
      ) : null}
    </div>
  );
}

export default Paper;
