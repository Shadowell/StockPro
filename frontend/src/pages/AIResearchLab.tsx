import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Beaker,
  Bot,
  BrainCircuit,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { getAICapabilities, getStrategies, listBacktestRuns } from "../api/client";
import type { AICapabilities, BacktestRun, Strategy } from "../types";

const TABS = [
  ["assistant", "策略助手"],
  ["new", "新策略研发"],
  ["optimize", "策略优化"],
  ["candidates", "候选版本"],
] as const;
type Tab = (typeof TABS)[number][0];
const panel = "rounded-xl border border-crypto-border bg-crypto-card";

export function AIResearchLab() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") as Tab | null;
  const tab: Tab = TABS.some(([key]) => key === requested)
    ? requested!
    : "assistant";
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [capabilities, setCapabilities] = useState<AICapabilities | null>(null);
  const [capabilityError, setCapabilityError] = useState("");
  const [dataScope, setDataScope] = useState<"business" | "test">("business");
  const scopedStrategies = strategies.filter((item) =>
    dataScope === "business"
      ? !item.data_purpose || item.data_purpose === "user"
      : Boolean(item.data_purpose && item.data_purpose !== "user"),
  );
  const scopedRuns = runs.filter((item) =>
    dataScope === "business"
      ? !item.data_purpose || item.data_purpose === "user"
      : Boolean(item.data_purpose && item.data_purpose !== "user"),
  );
  const load = async () => {
    setBusy(true);
    setError("");
    try {
      const [strategyResult, runResult, capabilityResult] = await Promise.allSettled([
        getStrategies(),
        listBacktestRuns(100),
        getAICapabilities(),
      ]);
      setStrategies(strategyResult.status === "fulfilled" ? strategyResult.value : []);
      setRuns(runResult.status === "fulfilled" ? runResult.value.items : []);
      if (capabilityResult.status === "fulfilled") {
        setCapabilities(capabilityResult.value);
        setCapabilityError("");
      } else {
        setCapabilities(null);
        setCapabilityError("AI 能力状态读取失败");
      }
      const evidenceFailures = [
        strategyResult.status === "rejected" ? "策略版本" : "",
        runResult.status === "rejected" ? "回测记录" : "",
      ].filter(Boolean);
      setError(evidenceFailures.length ? `${evidenceFailures.join("、")}加载失败` : "");
    } catch {
      setError("AI 研发证据加载失败");
    } finally {
      setBusy(false);
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
          </div>
          <p className="mt-2 text-sm text-slate-500">
            用 AI 提出研究假设、解释证据并生成候选策略；候选仍需完成验证、回测和模拟盘准入。
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-400"
        >
          <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
          刷新候选
        </button>
      </header>
      <div
        className={`mb-5 rounded-lg border p-4 text-sm ${
          capabilities?.configured
            ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-200"
            : "border-amber-500/25 bg-amber-500/10 text-amber-100"
        }`}
      >
        <strong>
          {capabilities?.configured
            ? `AI 可用 · Qwen ${capabilities.model || ""}`
            : "AI 生成不可用"}
        </strong>
        <span className="ml-2 text-xs opacity-80">
          {capabilities?.configured
            ? `能力检查 ${capabilities.checked_at}`
            : capabilityError || capabilities?.reason || "能力状态读取中"}
        </span>
        <div className="mt-1 text-xs opacity-75">
          策略与回测证据仍可只读浏览；“自动开发”当前是确定性模板，不属于 AI 生成。
        </div>
      </div>
      <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-crypto-border bg-crypto-card px-4 py-3 text-xs text-slate-500">
        <span>
          数据{" "}
          <strong className="font-medium text-slate-300">
            策略版本 / 回测记录
          </strong>
        </span>
        <span>
          状态{" "}
          <strong
            className={
              error
                ? "text-red-300"
                : busy
                  ? "text-blue-300"
                  : "text-emerald-300"
            }
          >
            {error ? "加载失败" : busy ? "读取中" : "已读取"}
          </strong>
        </span>
        <span>
          最新更新{" "}
          <strong className="font-mono text-slate-300">
            {runs[0]?.finished_at ??
              runs[0]?.created_at ??
              strategies[0]?.updated_at ??
              "--"}
          </strong>
        </span>
      </div>
      {error ? (
        <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">
          {error}
        </div>
      ) : null}
      <nav className="mb-5 flex overflow-x-auto rounded-xl border border-crypto-border bg-crypto-card p-1">
        {TABS.map(([key, label]) => (
          <button
            type="button"
            key={key}
            onClick={() => setParams({ tab: key })}
            className={`min-w-max flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold ${tab === key ? "bg-cyan-600 text-white" : "text-slate-500 hover:bg-slate-800/60 hover:text-white"}`}
          >
            {label}
          </button>
        ))}
      </nav>
      <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-crypto-border bg-crypto-card px-4 py-3 text-xs text-slate-500">
        <div className="flex rounded-md border border-crypto-border bg-crypto-bg p-1">
          <button
            type="button"
            data-testid="ai-scope-business"
            onClick={() => setDataScope("business")}
            className={`rounded px-2.5 py-1 font-semibold ${dataScope === "business" ? "bg-cyan-600 text-white" : "text-slate-500"}`}
          >
            我的研发
          </button>
          <button
            type="button"
            data-testid="ai-scope-test"
            onClick={() => setDataScope("test")}
            className={`rounded px-2.5 py-1 font-semibold ${dataScope === "test" ? "bg-amber-500/15 text-amber-200" : "text-slate-500"}`}
          >
            测试与验收
          </button>
        </div>
        <span>
          当前范围
          <strong className="ml-1 font-medium text-slate-300">
            {scopedStrategies.length} 个策略版本 · {scopedRuns.length} 条回测
          </strong>
        </span>
      </div>
      {dataScope === "test" ? (
        <div className="mb-5 rounded-lg border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-xs text-amber-100">
          当前仅查看测试与验收证据，不代表可投入业务运行。
        </div>
      ) : null}
      {tab === "assistant" ? (
        <div className="grid gap-5 xl:grid-cols-[1fr_0.8fr]">
          <section className={`${panel} p-5`}>
            <div className="flex items-center gap-2">
              <Bot className="h-5 w-5 text-cyan-400" />
              <h2 className="font-semibold text-white">研究问题模板</h2>
            </div>
            <div className="mt-5 space-y-3">
              {[
                "这个因子的收益是否只来自某个行业暴露？",
                "策略在样本外和不同成本假设下是否稳定？",
                "当前股票池成员变化由哪些封存证据驱动？",
                "Paper 拒单来自容量、现金还是数据陈旧？",
              ].map((item) => (
                <div
                  key={item}
                  className="rounded-lg border border-crypto-border bg-crypto-bg p-4 text-sm text-slate-300"
                >
                  {item}
                </div>
              ))}
            </div>
          </section>
          <section className={`${panel} p-5`}>
            <ShieldCheck className="h-5 w-5 text-emerald-400" />
            <h2 className="mt-3 font-semibold text-white">受控边界</h2>
            <ul className="mt-4 space-y-3 text-xs leading-5 text-slate-500">
              <li>只使用已确认的研究数据，并明确标记缺失状态。</li>
              <li>生成代码必须先通过策略校验。</li>
              <li>AI 候选不会自动进入模拟交易。</li>
            </ul>
          </section>
        </div>
      ) : null}
      {tab === "new" ? (
        <section className={`${panel} p-5`}>
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-cyan-400" />
            <h2 className="font-semibold text-white">普通 Python 策略起点</h2>
          </div>
          <pre className="mt-5 overflow-x-auto rounded-lg border border-crypto-border bg-crypto-bg p-5 text-sm leading-6 text-slate-300">{`def initialize(context):\n    context.security = context.universe[0]\n\ndef handle_data(context, data):\n    # 在这里编写研究与交易逻辑\n    pass`}</pre>
          <Link
            to="/strategy?tab=code"
            className="mt-4 inline-block rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white"
          >
            进入策略编辑器
          </Link>
        </section>
      ) : null}
      {tab === "optimize" ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {scopedRuns
            .filter((run) => run.run_mode === "full")
            .slice(0, 12)
            .map((run) => (
              <article key={run.id} className={`${panel} p-5`}>
                <Beaker className="h-5 w-5 text-violet-400" />
                <h2 className="mt-3 truncate font-semibold text-slate-100">
                  {run.name}
                </h2>
                {run.data_purpose !== "user" && run.data_purpose ? (
                  <span className="mt-2 inline-block rounded border border-amber-500/25 bg-amber-500/10 px-1.5 py-0.5 text-[9px] text-amber-300">
                    {run.data_purpose === "acceptance" ? "验收数据" : "种子数据"}
                  </span>
                ) : null}
                <p className="mt-2 text-xs text-slate-500">
                  {run.start_date} → {run.end_date}
                </p>
                <div className="mt-4 flex items-center justify-between text-xs">
                  <span
                    className={
                      run.promotion_status === "paper_eligible"
                        ? "text-emerald-300"
                        : "text-amber-300"
                    }
                  >
                    {run.promotion_status}
                  </span>
                  <Link to={`/backtest/${run.id}`} className="text-blue-300">
                    查看证据 →
                  </Link>
                </div>
              </article>
            ))}
          {!busy &&
          !error &&
          scopedRuns.filter((run) => run.run_mode === "full").length === 0 ? (
            <div
              className={`${panel} p-12 text-center text-sm text-slate-600 md:col-span-2 xl:col-span-3`}
            >
              暂无完整回测候选
            </div>
          ) : null}
        </div>
      ) : null}
      {tab === "candidates" ? (
        <section className={`${panel} overflow-hidden`}>
          <div className="border-b border-crypto-border px-5 py-4">
            <h2 className="font-semibold text-white">候选策略版本</h2>
            <p className="mt-1 text-xs text-slate-500">
              仅展示已有版本；候选状态不代表投资适用性。
            </p>
          </div>
          <div className="divide-y divide-white/[0.04]">
            {scopedStrategies.slice(0, 30).map((strategy) => (
              <div
                key={strategy.id}
                className="flex items-center justify-between gap-4 px-5 py-4"
              >
                <div>
                  <div className="font-semibold text-slate-200">
                    {strategy.name}
                  </div>
                  {strategy.data_purpose !== "user" && strategy.data_purpose ? (
                    <div className="mt-1 text-[10px] text-amber-300">
                      {strategy.data_purpose === "acceptance" ? "验收数据" : "种子数据"}
                    </div>
                  ) : null}
                  <div className="mt-1 text-xs text-slate-600">
                    Strategy #{strategy.id}
                  </div>
                </div>
                <Link to="/strategy" className="text-xs text-blue-300">
                  研究版本 →
                </Link>
              </div>
            ))}
            {!busy && !error && scopedStrategies.length === 0 ? (
              <div className="p-12 text-center text-sm text-slate-600">
                暂无候选策略版本
              </div>
            ) : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}

export default AIResearchLab;
