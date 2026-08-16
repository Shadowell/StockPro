import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  CircleDollarSign,
  RefreshCw,
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
import { PaperInstanceDashboard } from "../components/PaperInstanceDashboard";
import { PaperRuntimeInstanceDetail } from "../components/PaperRuntimeInstanceDetail";
import { WorkspacePipelineNote } from "../components/WorkspacePipelineNote";

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
type PageView = "dashboard" | "create" | "detail";

/** 指标轮询：每 10 秒批量刷新一次实例列表（卡片权益 / 计数）。 */
const METRICS_POLL_MS = 10_000;
/** 列表全量刷新：每 60 秒（含晋级回测与选中实例详情）。 */
const LIST_REFRESH_MS = 60_000;

const panel = "rounded-xl border border-crypto-border bg-crypto-card";
const input =
  "h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-slate-200 outline-none focus:border-blue-500/60";
const isBusinessPurpose = (item: { data_purpose?: string | null }) =>
  !item.data_purpose || item.data_purpose === "user";

export function Paper() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") as Tab | null;
  const tab: Tab = TABS.some(([key]) => key === requested)
    ? requested!
    : "instances";
  const requestedView = params.get("view") as PageView | null;
  const pageView: PageView =
    requestedView === "create" || requestedView === "detail"
      ? requestedView
      : "dashboard";
  const [instances, setInstances] = useState<PaperRuntimeInstance[]>([]);
  const [selected, setSelected] = useState<PaperRuntimeInstance | null>(null);
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [runId, setRunId] = useState("");
  const [name, setName] = useState("");
  const [initialCash, setInitialCash] = useState(1_000_000);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  const eligible = useMemo(
    () =>
      runs.filter(
        (item) =>
          isBusinessPurpose(item) &&
          item.status === "success" &&
          item.run_mode === "full" &&
          item.promotion_status === "paper_eligible" &&
          item.promotion_gate_complete === true &&
          item.factor_snapshot_id &&
          item.pool_snapshot_id &&
          item.research_protocol_id,
      ),
    [runs],
  );
  const selectedRun = eligible.find((item) => item.id === runId);
  const scopedInstances = useMemo(
    () => instances.filter((item) => isBusinessPurpose(item)),
    [instances],
  );

  const requestedInstanceId = params.get("instance");
  const load = useCallback(
    async (keepId?: string, opts?: { silent?: boolean }) => {
      const silent = opts?.silent === true;
      if (!silent) {
        setBusy(true);
        setError("");
      }
      try {
        const [paper, backtests] = await Promise.all([
          listPaperInstances(),
          listBacktestRuns(200),
        ]);
        setInstances(paper.items);
        setRuns(backtests.items);
        const scopeInstances = paper.items.filter((item) =>
          isBusinessPurpose(item),
        );
        const id = [
          keepId,
          requestedInstanceId,
          scopeInstances[0]?.id,
        ].find(
          (candidate) =>
            Boolean(candidate) &&
            scopeInstances.some((item) => item.id === candidate),
        ) ?? undefined;
        setSelected(id ? await getPaperInstance(id) : null);
        setRunId((current) =>
          current ||
            backtests.items.find(
              (item) =>
                isBusinessPurpose(item) &&
                item.promotion_status === "paper_eligible" &&
                item.factor_snapshot_id &&
                item.pool_snapshot_id,
            )?.id ||
            "",
        );
      } catch (reason) {
        // 静默轮询失败时保留上一份列表数据，等待下一轮或手动刷新。
        if (!silent) {
          setError(
            reason instanceof Error ? reason.message : "Paper 工作台加载失败",
          );
        }
      } finally {
        if (!silent) setBusy(false);
        setLoaded(true);
      }
    },
    [requestedInstanceId],
  );
  useEffect(() => {
    void load();
  }, [load]);

  const selectedIdRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    selectedIdRef.current = selected?.id;
  }, [selected?.id]);

  useEffect(() => {
    let active = true;
    const timer = window.setInterval(async () => {
      if (document.hidden) return;
      try {
        const paper = await listPaperInstances();
        if (!active) return;
        setInstances(paper.items);
      } catch {
        // 轮询失败保持最后一份已确认数据；缺失数据不显示为 0。
      }
    }, METRICS_POLL_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      void load(selectedIdRef.current, { silent: true });
    }, LIST_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const chooseInstance = async (id: string) => {
    setBusy(true);
    setError("");
    try {
      setSelected(await getPaperInstance(id));
      setParams({ view: "detail", tab: tab === "instances" ? "account" : tab, instance: id });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "实例详情加载失败");
    } finally {
      setBusy(false);
    }
  };
  const openCreate = () => {
    setParams({ view: "create" });
  };
  const backToDashboard = () => {
    setParams({});
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
      setParams({ view: "detail", tab: "account", instance: created.id });
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
  const actionFor = async (
    instance: PaperRuntimeInstance,
    next: "start" | "pause" | "resume" | "stop",
  ) => {
    setSelected(instance);
    setBusy(true);
    setError("");
    try {
      await paperInstanceAction(instance.id, next);
      await load(instance.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "状态操作失败");
      setBusy(false);
    }
  };
  const replay = async (requestedDate: string) => {
    if (!selected || !requestedDate) return setError("请选择回放交易日");
    setBusy(true);
    setError("");
    try {
      await processPaperCycle(selected.id, {
        trade_date: requestedDate,
        data_available_at: `${requestedDate}T15:00:00+08:00`,
        observed_at: `${requestedDate}T15:01:00+08:00`,
      });
      await load(selected.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "周期处理失败");
      setBusy(false);
    }
  };

  if (pageView === "detail" && selected) {
    const qualifyingRun =
      runs.find((item) => item.id === selected.qualifying_backtest_run_id) ??
      selected.qualifying_backtest ??
      null;
    return (
      <div className="min-h-full bg-crypto-bg px-4 py-5 sm:px-5 2xl:px-8">
        <WorkspacePipelineNote stageId="paper" />
        {error ? (
          <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">
            <strong>加载或操作失败：</strong>
            {error}；缺失数据未显示为 0。
          </div>
        ) : null}
        <PaperRuntimeInstanceDetail
          instance={selected}
          qualifyingRun={qualifyingRun}
          busy={busy}
          onBack={backToDashboard}
          onRefresh={() => load(selected.id)}
          onAction={action}
          onRunCycle={replay}
        />
      </div>
    );
  }

  return (
    <div
      className="min-h-full bg-crypto-bg p-6"
      data-testid="paper-runtime-workbench"
      data-operator-page="paper"
    >
      <WorkspacePipelineNote stageId="paper" />

      {pageView === "dashboard" ? (
        <PaperInstanceDashboard
          instances={scopedInstances}
          loaded={loaded}
          busy={busy}
          onCreate={openCreate}
          onOpenDetail={(instance) => void chooseInstance(instance.id)}
          onAction={(instance, next) => void actionFor(instance, next)}
        />
      ) : null}

      {pageView === "create" ? (
        <>
          <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-3">
                <WalletCards className="h-7 w-7 text-blue-400" />
                <h1 className="text-2xl font-black text-white">创建模拟实例</h1>
                <span className="rounded-md border border-amber-500/25 bg-amber-500/10 px-2 py-1 text-xs text-amber-300">
                  无真实券商连接
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-500">
                选择已通过晋级门槛的完整回测，确认固定快照与模拟资金后创建实例。
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={backToDashboard}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-300"
              >
                <ArrowLeft className="h-4 w-4" />
                返回控制台
              </button>
              <button
                type="button"
                onClick={() => void load(selected?.id)}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-400"
              >
                <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
                刷新
              </button>
            </div>
          </header>
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
          {loaded ? (
            <div className="mx-auto max-w-4xl">
              <section data-testid="paper-create-wizard" className={`${panel} p-5`}>
                <h2 className="font-semibold text-white">创建模拟实例</h2>
                <p className="mt-1 text-xs text-slate-500">
                  从已晋级回测创建可审计实例，不连接真实券商账户。
                </p>
                <div className="mt-5 grid grid-cols-4 gap-1 text-center text-[10px]">
                  <span className="rounded bg-blue-500/15 px-2 py-2 text-blue-300">
                    1 选择策略
                  </span>
                  <span className="rounded bg-crypto-bg px-2 py-2 text-slate-500">
                    2 运行参数
                  </span>
                  <span className="rounded bg-crypto-bg px-2 py-2 text-slate-500">
                    3 飞行检查
                  </span>
                  <span className="rounded bg-crypto-bg px-2 py-2 text-slate-500">
                    4 运行监控
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
                        {run.name} · {run.strategy_name ?? "策略回测"}
                      </option>
                    ))}
                  </select>
                </label>
                {selectedRun ? (
                  <dl className="mt-3 grid grid-cols-2 gap-2 rounded-lg border border-crypto-border bg-crypto-bg p-3 text-[10px] text-slate-500">
                    <div>
                      策略
                      <div className="mt-1 truncate text-slate-300">
                        {selectedRun.strategy_name ?? "未提供"} · 版本 {selectedRun.strategy_version ?? "--"}
                      </div>
                    </div>
                    <div>
                      研究区间
                      <div className="mt-1 text-slate-300">
                        {selectedRun.start_date} 至 {selectedRun.end_date}
                      </div>
                    </div>
                    <div>
                      研究数据
                      <div className="mt-1 text-slate-300">
                        {selectedRun.factor_snapshot_id && selectedRun.pool_snapshot_id ? "因子与股票池均已绑定" : "研究数据绑定不完整"}
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
        </>
      ) : null}

      {pageView === "detail" && !selected ? (
        <>
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
          ) : (
            <div className={`${panel} p-16 text-center text-slate-600`}>
              <CircleDollarSign className="mx-auto mb-3 h-8 w-8" />
              请先创建或选择 Paper 实例
              <div className="mt-4">
                <button
                  type="button"
                  onClick={backToDashboard}
                  className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-300"
                >
                  <ArrowLeft className="h-4 w-4" />
                  返回控制台
                </button>
              </div>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}

export default Paper;
