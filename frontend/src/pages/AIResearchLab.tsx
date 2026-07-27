import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  Beaker,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  Cpu,
  FlaskConical,
  Play,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import { getAICapabilities, getStrategies, listBacktestRuns } from "../api/client";
import { WorkspaceTabs } from "../components/WorkspaceTabs";
import type { AICapabilities, BacktestRun, Strategy } from "../types";

const TABS = [
  ["autonomous", "AI自主交易", "模拟实例与硬风控"],
  ["research", "新策略研发", "提议、回测与准入"],
  ["optimize", "现有策略优化", "诊断与候选版本"],
] as const;
type Tab = (typeof TABS)[number][0];
type DataScope = "business" | "test";
const panel = "rounded-xl border border-crypto-border bg-crypto-card";

const dateTime = (value: string | null | undefined) =>
  value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "暂无记录";

const purposeMatches = (
  item: { data_purpose?: string | null },
  scope: DataScope,
) =>
  scope === "business"
    ? !item.data_purpose || item.data_purpose === "user"
    : Boolean(item.data_purpose && item.data_purpose !== "user");

export function AIResearchLab() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") as Tab | null;
  const tab: Tab = TABS.some(([key]) => key === requested)
    ? requested!
    : "autonomous";
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [capabilities, setCapabilities] = useState<AICapabilities | null>(null);
  const [capabilityError, setCapabilityError] = useState("");
  const [dataScope, setDataScope] = useState<DataScope>("business");

  const scopedStrategies = useMemo(
    () => strategies.filter((item) => purposeMatches(item, dataScope)),
    [strategies, dataScope],
  );
  const scopedRuns = useMemo(
    () => runs.filter((item) => purposeMatches(item, dataScope)),
    [runs, dataScope],
  );
  const fullRuns = scopedRuns.filter((run) => run.run_mode === "full");
  const eligibleRuns = fullRuns.filter(
    (run) => run.promotion_status === "paper_eligible",
  );
  const latestEvidence =
    scopedRuns[0]?.finished_at ??
    scopedRuns[0]?.created_at ??
    scopedStrategies[0]?.updated_at;

  const load = async () => {
    setBusy(true);
    setError("");
    try {
      const [strategyResult, runResult, capabilityResult] =
        await Promise.allSettled([
          getStrategies(),
          listBacktestRuns(100),
          getAICapabilities(),
        ]);
      setStrategies(
        strategyResult.status === "fulfilled" ? strategyResult.value : [],
      );
      setRuns(
        runResult.status === "fulfilled" ? runResult.value.items : [],
      );
      if (capabilityResult.status === "fulfilled") {
        setCapabilities(capabilityResult.value);
        setCapabilityError("");
      } else {
        setCapabilities(null);
        setCapabilityError("AI 能力状态接口读取失败");
      }
      const failures = [
        strategyResult.status === "rejected" ? "策略版本" : "",
        runResult.status === "rejected" ? "回测记录" : "",
      ].filter(Boolean);
      setError(failures.length ? `${failures.join("、")}加载失败` : "");
    } catch {
      setError("AI 研发证据加载失败");
    } finally {
      setBusy(false);
      setLoaded(true);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <div
      className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8"
      data-testid="ai-research-lab"
    >
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <BrainCircuit className="h-7 w-7 text-cyan-400" />
            <h1 className="text-2xl font-black text-white">AI研发</h1>
            <span className="rounded-md border border-cyan-500/25 bg-cyan-500/10 px-2 py-1 text-[10px] font-semibold text-cyan-200">
              仅限研究
            </span>
          </div>
          <p className="mt-2 text-sm text-slate-500">
            智能交易代理、受控策略研发和既有策略优化统一入口；所有结果先经过回测与模拟准入。
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-300"
        >
          <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
          刷新
        </button>
      </header>

      <section className="mb-5 grid gap-px overflow-hidden rounded-xl border border-crypto-border bg-crypto-border md:grid-cols-4">
        {[
          ["AI连接", capabilities?.configured ? "可用" : "不可用", capabilities?.configured ? capabilities.model || "服务已连接" : capabilityError || "服务尚未配置"],
          ["策略版本", loaded ? String(scopedStrategies.length) : "读取中", "策略版本库记录"],
          ["完整回测", loaded ? String(fullRuns.length) : "读取中", "仅统计完整模式"],
          ["最新证据", dateTime(latestEvidence), latestEvidence ? "策略或回测更新时间" : "当前范围暂无记录"],
        ].map(([label, value, note], index) => (
          <div key={label} className="bg-crypto-card px-4 py-3">
            <div className="text-[10px] text-slate-600">{label}</div>
            <div
              className={`mt-1 truncate text-sm font-semibold ${
                index === 0
                  ? capabilities?.configured
                    ? "text-emerald-300"
                    : "text-amber-300"
                  : "text-slate-200"
              }`}
              title={value}
            >
              {value}
            </div>
            <div className="mt-1 truncate text-[10px] text-slate-600" title={note}>
              {note}
            </div>
          </div>
        ))}
      </section>

      {error ? (
        <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">
          <strong>证据加载失败：</strong>
          {error}。受影响指标保持不可用，不回退为 0。
        </div>
      ) : null}

      <WorkspaceTabs
        className="mb-5"
        ariaLabel="AI研发工作台"
        items={TABS.map(([id, label]) => ({ id, label }))}
        value={tab}
        onChange={(id) => setParams({ tab: id })}
      />

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex rounded-lg border border-crypto-border bg-crypto-card p-1 text-xs">
          <button
            type="button"
            data-testid="ai-scope-business"
            onClick={() => setDataScope("business")}
            className={`rounded-md px-3 py-1.5 font-semibold ${
              dataScope === "business"
                ? "bg-cyan-600 text-white"
                : "text-slate-500"
            }`}
          >
            我的研发
          </button>
          <button
            type="button"
            data-testid="ai-scope-test"
            onClick={() => setDataScope("test")}
            className={`rounded-md px-3 py-1.5 font-semibold ${
              dataScope === "test"
                ? "bg-amber-500/15 text-amber-200"
                : "text-slate-500"
            }`}
          >
            测试与验收
          </button>
        </div>
        <span className="text-xs text-slate-600">
          当前范围 {scopedStrategies.length} 个策略版本 · {scopedRuns.length} 条回测
        </span>
      </div>

      {dataScope === "test" ? (
        <div className="mb-5 rounded-lg border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-xs text-amber-100">
          当前仅查看测试与验收证据，不代表可投入业务运行。
        </div>
      ) : null}

      {tab === "autonomous" ? (
        <div className="grid gap-5 xl:grid-cols-[1fr_0.72fr]">
          <section className={`${panel} p-5`}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <Bot className="h-5 w-5 text-cyan-400" />
                  <h2 className="font-semibold text-white">AI自主交易控制台</h2>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  仅允许在模拟资金和人工硬风控信封内产生决策。
                </p>
              </div>
              <span className="rounded-md border border-amber-500/25 bg-amber-500/10 px-2 py-1 text-[10px] text-amber-200">
                仅限模拟
              </span>
            </div>
            <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {[
                [Cpu, "AI提供方", capabilities?.configured ? `Qwen · ${capabilities.model || "默认模型"}` : "未配置"],
                [ShieldCheck, "风险信封", "人工约束 · 不可绕过"],
                [Activity, "运行实例", "未接入实例接口"],
                [Clock3, "最近决策", "暂无运行记录"],
              ].map(([Icon, label, value]) => {
                const MetricIcon = Icon as typeof Cpu;
                return (
                  <div key={String(label)} className="rounded-lg border border-crypto-border bg-crypto-bg p-3">
                    <MetricIcon className="h-4 w-4 text-slate-500" />
                    <div className="mt-3 text-[10px] text-slate-600">{String(label)}</div>
                    <div className="mt-1 text-xs font-semibold text-slate-300">{String(value)}</div>
                  </div>
                );
              })}
            </div>
            <div className="mt-5 rounded-xl border border-dashed border-crypto-border bg-crypto-bg p-10 text-center">
              <Bot className="mx-auto h-8 w-8 text-slate-700" />
              <div className="mt-3 text-sm font-semibold text-slate-300">
                暂无 AI 自主交易实例
              </div>
              <p className="mx-auto mt-2 max-w-xl text-xs leading-5 text-slate-600">
                StockPro 当前没有持久化的 AI 决策实例与运行日志接口，因此这里不展示模拟实例、收益或“运行中”占位数据。
              </p>
              <button
                type="button"
                disabled
                title="需要先接入 AI 实例、决策日志与硬风控接口"
                className="mt-5 inline-flex h-10 items-center gap-2 rounded-lg bg-cyan-600 px-4 text-sm font-semibold text-white opacity-40"
              >
                <Play className="h-4 w-4" />
                启动 AI 模拟实例
              </button>
            </div>
          </section>
          <section className={`${panel} p-5`}>
            <SlidersHorizontal className="h-5 w-5 text-amber-400" />
            <h2 className="mt-3 font-semibold text-white">硬风控边界</h2>
            <div className="mt-4 space-y-3 text-xs">
              {[
                ["账户", "模拟资金，不连接券商"],
                ["交易制度", "A 股 T+1 / 100 股整数手"],
                ["数据", "仅使用已封存研究快照"],
                ["自动晋级", "禁止，必须人工复核"],
              ].map(([label, value]) => (
                <div key={label} className="flex items-center justify-between gap-4 border-b border-white/[0.05] pb-3">
                  <span className="text-slate-600">{label}</span>
                  <span className="text-right text-slate-300">{value}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      ) : null}

      {tab === "research" ? (
        <div className="space-y-5">
          <section className={`${panel} p-5`}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <Sparkles className="h-5 w-5 text-cyan-400" />
                  <h2 className="font-semibold text-white">新策略研发流水线</h2>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  提议方向 → 研究回测 → 结果审阅 → 模拟盘决策。
                </p>
              </div>
              <Link
                to="/strategy?view=create"
                className="inline-flex h-10 items-center gap-2 rounded-lg bg-cyan-600 px-4 text-sm font-semibold text-white"
              >
                提交研究提议
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
            <div className="mt-6 grid gap-3 lg:grid-cols-4">
              {[
                ["01", "提议方向", scopedStrategies.length, "策略草案与不可变版本"],
                ["02", "研究回测", fullRuns.length, "完整回测与固定快照"],
                ["03", "回测结果", eligibleRuns.length, "通过模拟准入门槛"],
                ["04", "模拟盘决策", null, "需在模拟盘人工创建"],
              ].map(([step, label, count, note], index) => (
                <div key={String(step)} className="relative rounded-xl border border-crypto-border bg-crypto-bg p-4">
                  <div className="text-[10px] font-bold text-cyan-400">{String(step)}</div>
                  <div className="mt-2 flex items-center justify-between">
                    <strong className="text-sm text-slate-200">{String(label)}</strong>
                    {count === null ? (
                      <span className="text-xs text-slate-600">未接入</span>
                    ) : (
                      <span className="font-mono text-lg font-bold text-white">{String(count)}</span>
                    )}
                  </div>
                  <p className="mt-2 text-[10px] text-slate-600">{String(note)}</p>
                  {index < 3 ? (
                    <ArrowRight className="absolute -right-3 top-1/2 z-10 hidden h-4 w-4 -translate-y-1/2 text-slate-700 lg:block" />
                  ) : null}
                </div>
              ))}
            </div>
          </section>

          <section className={`${panel} overflow-hidden`}>
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-5 py-4">
              <div>
                <h2 className="font-semibold text-white">候选与验证证据</h2>
                <p className="mt-1 text-xs text-slate-500">
                  只显示策略版本库中已有的策略和回测记录，不生成演示候选。
                </p>
              </div>
              <span className="text-xs text-slate-600">{eligibleRuns.length} 个可进入模拟评审</span>
            </div>
            <div className="divide-y divide-white/[0.04]">
              {fullRuns.slice(0, 12).map((run) => (
                <div key={run.id} className="grid gap-3 px-5 py-4 text-xs md:grid-cols-[minmax(0,1fr)_140px_140px_100px] md:items-center">
                  <div className="min-w-0">
                    <div className="truncate font-semibold text-slate-200">{run.name}</div>
                    <div className="mt-1 truncate text-[10px] text-slate-500">完整回测 · 证据已持久化</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-slate-600">研究窗口</div>
                    <div className="mt-1 text-slate-400">{run.start_date} → {run.end_date}</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-slate-600">准入结论</div>
                    <div className={`mt-1 font-semibold ${run.promotion_status === "paper_eligible" ? "text-emerald-300" : "text-amber-300"}`}>
                      {run.promotion_status === "paper_eligible" ? "符合模拟准入" : run.promotion_status ? "待人工评审" : "未记录"}
                    </div>
                  </div>
                  <Link to={`/backtest/${run.id}`} className="inline-flex items-center justify-end gap-1 text-blue-300">
                    查看证据
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </div>
              ))}
              {loaded && !error && fullRuns.length === 0 ? (
                <div className="p-12 text-center text-sm text-slate-600">
                  当前范围暂无完整回测候选；先提交研究提议并完成回测。
                </div>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}

      {tab === "optimize" ? (
        <div className="space-y-5">
          <section className={`${panel} p-5`}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <Beaker className="h-5 w-5 text-violet-400" />
                  <h2 className="font-semibold text-white">现有策略优化</h2>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  从完整回测证据识别待复核策略；不会自动改写版本或启动模拟盘。
                </p>
              </div>
              <span className="rounded-md border border-violet-500/25 bg-violet-500/10 px-2 py-1 text-[10px] text-violet-200">
                HUMAN REVIEW
              </span>
            </div>
            <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {fullRuns.slice(0, 12).map((run) => (
                <article key={run.id} className="rounded-xl border border-crypto-border bg-crypto-bg p-4">
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="line-clamp-2 text-sm font-semibold text-slate-100">{run.name}</h3>
                    {run.promotion_status === "paper_eligible" ? (
                      <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                    ) : (
                      <FlaskConical className="h-4 w-4 shrink-0 text-amber-400" />
                    )}
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-[10px]">
                    <div className="rounded-lg border border-crypto-border p-2">
                      <div className="text-slate-600">数据快照</div>
                      <div className="mt-1 truncate text-slate-300">{run.dataset_snapshot_id ? "已绑定封存数据" : "未绑定"}</div>
                    </div>
                    <div className="rounded-lg border border-crypto-border p-2">
                      <div className="text-slate-600">策略版本</div>
                      <div className="mt-1 truncate text-slate-300">{run.strategy_version_id ? "已绑定不可变版本" : "未绑定"}</div>
                    </div>
                  </div>
                  <div className="mt-4 flex items-center justify-between">
                    <span className="text-[10px] text-slate-600">{dateTime(run.finished_at ?? run.created_at)}</span>
                    <Link to={`/backtest/${run.id}`} className="text-xs font-semibold text-blue-300">诊断证据 →</Link>
                  </div>
                </article>
              ))}
              {loaded && !error && fullRuns.length === 0 ? (
                <div className="rounded-xl border border-dashed border-crypto-border p-12 text-center text-sm text-slate-600 md:col-span-2 xl:col-span-3">
                  暂无可诊断的完整回测记录。
                </div>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

export default AIResearchLab;
