import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Archive,
  ArrowRight,
  CheckCircle2,
  Filter,
  Layers3,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Tag,
} from "lucide-react";
import {
  createPoolBacktestDraft,
  createStockPool,
  generateStockPool,
  getBacktestConfiguration,
  getMarketResearchContext,
  getStockPoolMembers,
  listStockPools,
  listStockPoolSnapshots,
  sealStockPoolSnapshot,
} from "../api/client";
import { WorkspaceTabs } from "../components/WorkspaceTabs";
import { DiagnosticDetails } from "../components/DiagnosticDetails";
import {
  EvidenceStrip,
  FilterChipGroup,
  MetricValue,
  OperatorFilterBar,
  OperatorPageHeader,
} from "../components/OperatorShell";
import { SymbolCell } from "../components/SymbolCell";
import {
  TremorBarList,
  TremorCallout,
  TremorCard,
  TremorDeltaBadge,
} from "../components/TremorUI";
import type {
  BacktestConfiguration,
  MarketResearchContext,
  StockPool,
  StockPoolMember,
  StockPoolSnapshot,
} from "../types";

const TABS = [
  ["mine", "我的股票池"],
  ["screener", "基础筛选与建池"],
  ["snapshots", "快照与回测"],
] as const;

type TabKey = (typeof TABS)[number][0];
type PoolTypeFilter = "all" | StockPool["pool_type"];
type CreationType = Extract<
  StockPool["pool_type"],
  "sector" | "event" | "screener" | "factor"
>;

const panel = "rounded-xl border border-crypto-border bg-crypto-card";
const input =
  "h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-slate-200 outline-none focus:border-blue-500/60";

const poolTypeLabel = (type: string) =>
  ({ screener: "条件", factor: "因子", sector: "板块", event: "事件", manual: "手工" })[
    type
  ] ?? type;

const TYPE_GUIDES: Record<
  CreationType,
  { title: string; blurb: string; tip: string; color: "blue" | "emerald" | "amber" }
> = {
  sector: {
    title: "板块选股",
    blurb: "按行业/概念板块、热点轮动及涨停梯队筛选候选标的，自动绑定同交易日市场证据。",
    tip: "推荐优先使用：结合每日封存市场证据，快速捕获强势板块与连板领头羊。",
    color: "blue",
  },
  event: {
    title: "事件选股",
    blurb: "根据市场催化、重大事项、重组/政策等主题关键字抽取关联成分股。",
    tip: "推荐优先使用：支持实时/历史快讯与热点榜单联动，适合主题跟踪与消息驱动策略。",
    color: "emerald",
  },
  screener: {
    title: "基础条件选股",
    blurb: "设定价格区间、最小成交额、上市天数限制以及创业板/科创板/ST/停牌剔除规则。",
    tip: "适合构建基础全市场流动性池或观察名册，可作为策略的基础标的宇宙。",
    color: "amber",
  },
  factor: {
    title: "因子选股",
    blurb: "引用已封存的量化因子快照，按因子得分与分位数截取 Top N 股票。",
    tip: "因子计算由因子实验室管理，此处仅引用已冻结的结果，保证研究绝对可复现。",
    color: "blue",
  },
};

const memberIsExpired = (member: StockPoolMember) =>
  Boolean(member.valid_until && member.valid_until < new Date().toISOString().slice(0, 10));

function PoolTypeBadge({ type }: { type: string }) {
  const deltaType =
    type === "sector"
      ? "increase"
      : type === "event"
        ? "moderate-increase"
        : type === "screener"
          ? "neutral"
          : "moderate-decrease";
  return (
    <TremorDeltaBadge
      type={deltaType}
      value={poolTypeLabel(type)}
      className="text-[11px]"
    />
  );
}

function WorkflowStep({
  step,
  label,
  active,
  done,
}: {
  step: number;
  label: string;
  active?: boolean;
  done?: boolean;
}) {
  return (
    <div
      className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs transition-all ${
        active
          ? "border-blue-500/40 bg-blue-500/10 text-blue-200 shadow-sm"
          : done
            ? "border-emerald-500/25 bg-emerald-500/[0.07] text-emerald-300"
            : "border-crypto-border bg-crypto-bg/50 text-slate-500"
      }`}
    >
      {done ? (
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
      ) : (
        <span
          className={`grid h-4 w-4 place-items-center rounded-full text-[10px] font-bold ${
            active ? "bg-blue-500 text-white" : "bg-crypto-card text-slate-500"
          }`}
        >
          {step}
        </span>
      )}
      <span className="font-medium">{label}</span>
    </div>
  );
}

export function StockPools() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const rawTab = params.get("tab") || "mine";

  // Standardized tab mapping (normalizes legacy tabs factor/sector/event to screener)
  const tab: TabKey =
    rawTab === "mine" || rawTab === "snapshots" ? rawTab : "screener";

  const [creationType, setCreationType] = useState<CreationType>(
    rawTab === "factor" || rawTab === "sector" || rawTab === "event"
      ? rawTab
      : "sector"
  );

  const [pools, setPools] = useState<StockPool[]>([]);
  const [snapshots, setSnapshots] = useState<StockPoolSnapshot[]>([]);
  const [members, setMembers] = useState<StockPoolMember[]>([]);
  const [selectedPoolId, setSelectedPoolId] = useState("");
  const [config, setConfig] = useState<BacktestConfiguration | null>(null);
  const [market, setMarket] = useState<MarketResearchContext | null>(null);
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);
  const [membersLoading, setMembersLoading] = useState(false);
  const [error, setError] = useState("");
  const [membersError, setMembersError] = useState("");
  const [partialWarnings, setPartialWarnings] = useState<string[]>([]);
  const [message, setMessage] = useState("");

  // Form states for pool creation
  const [name, setName] = useState("");
  const [topN, setTopN] = useState(20);
  const [factorCode, setFactorCode] = useState("momentum_20d");
  const [sector, setSector] = useState("商业百货");
  const [keyword, setKeyword] = useState("");
  const [symbols, setSymbols] = useState("600519.SH,000333.SZ");
  const [minPrice, setMinPrice] = useState(0);
  const [minTurnover, setMinTurnover] = useState(0);
  const [lastGenerationId, setLastGenerationId] = useState("");

  const [poolTypeFilter, setPoolTypeFilter] = useState<PoolTypeFilter>("all");
  const [poolQuery, setPoolQuery] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    setPartialWarnings([]);
    const [poolResult, snapshotResult, configResult, marketResult] =
      await Promise.allSettled([
        listStockPools(),
        listStockPoolSnapshots(),
        getBacktestConfiguration(),
        getMarketResearchContext(),
      ]);
    const warnings: string[] = [];
    if (poolResult.status === "fulfilled") {
      setPools(poolResult.value.items);
    } else {
      setError(
        poolResult.reason instanceof Error
          ? poolResult.reason.message
          : "股票池规则读取失败"
      );
    }
    if (snapshotResult.status === "fulfilled")
      setSnapshots(snapshotResult.value.items);
    else warnings.push("快照仓库暂不可用");
    if (configResult.status === "fulfilled") setConfig(configResult.value);
    else warnings.push("生成输入配置暂不可用");
    if (marketResult.status === "fulfilled") setMarket(marketResult.value);
    else warnings.push("市场证据暂不可用，板块/事件池不能生成");
    setPartialWarnings(warnings);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selectedPoolId) {
      setMembers([]);
      setMembersError("");
      return;
    }
    let active = true;
    setMembersLoading(true);
    setMembersError("");
    getStockPoolMembers(selectedPoolId)
      .then((items) => {
        if (active) setMembers(items);
      })
      .catch((reason) => {
        if (!active) return;
        setMembers([]);
        setMembersError(
          reason instanceof Error ? reason.message : "成员证据读取失败"
        );
      })
      .finally(() => {
        if (active) setMembersLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedPoolId]);

  const businessPools = useMemo(
    () =>
      pools.filter(
        (item) => !item.data_purpose || item.data_purpose === "user"
      ),
    [pools]
  );

  const visiblePools = useMemo(() => {
    const normalizedQuery = poolQuery.trim().toLowerCase();
    return businessPools
      .filter(
        (item) =>
          poolTypeFilter === "all" || item.pool_type === poolTypeFilter
      )
      .filter((item) => {
        if (!normalizedQuery) return true;
        return [item.name, item.description, item.pool_type, item.rule_type]
          .filter(Boolean)
          .some((value) =>
            String(value).toLowerCase().includes(normalizedQuery)
          );
      })
      .sort((left, right) => {
        const dateOrder = String(right.latest_trade_date ?? "").localeCompare(
          String(left.latest_trade_date ?? "")
        );
        return dateOrder || left.name.localeCompare(right.name, "zh-CN");
      });
  }, [businessPools, poolQuery, poolTypeFilter]);

  const selectedPool = pools.find((item) => item.id === selectedPoolId);

  useEffect(() => {
    if (tab !== "mine") return;
    if (visiblePools.some((item) => item.id === selectedPoolId)) return;
    setSelectedPoolId(visiblePools[0]?.id ?? "");
  }, [selectedPoolId, tab, visiblePools]);

  const binding = useMemo(() => {
    if (!selectedPool || !config)
      return { ready: false, reason: "请选择股票池并等待输入配置" };
    const needsFactor = selectedPool.pool_type === "factor";
    const needsMarket =
      selectedPool.pool_type === "sector" ||
      selectedPool.pool_type === "event";
    const factorSnapshot = needsFactor ? config.factor_snapshots[0] : undefined;
    const tradeDate =
      factorSnapshot?.trade_date ??
      (needsMarket ? market?.snapshot?.trade_date : undefined) ??
      config.universe_snapshots[0]?.trade_date;
    const universeSnapshot = factorSnapshot
      ? config.universe_snapshots.find(
          (item) => item.id === factorSnapshot.universe_snapshot_id
        )
      : config.universe_snapshots.find((item) => item.trade_date === tradeDate) ??
        config.universe_snapshots[0];
    const datasetSnapshot = factorSnapshot
      ? config.dataset_snapshots.find(
          (item) => item.id === factorSnapshot.dataset_snapshot_id
        )
      : config.dataset_snapshots.find(
          (item) =>
            Boolean(tradeDate) &&
            item.start_date <= tradeDate! &&
            item.end_date >= tradeDate!
        ) ?? config.dataset_snapshots[0];
    const marketSnapshot =
      needsMarket && market?.snapshot?.trade_date === tradeDate
        ? market.snapshot
        : null;
    let reason = "";
    if (!datasetSnapshot || !universeSnapshot || !tradeDate)
      reason = "缺少兼容的数据或股票范围快照";
    else if (needsFactor && !factorSnapshot) reason = "缺少已封存因子快照";
    else if (needsMarket && !marketSnapshot) reason = "缺少同交易日市场证据快照";
    return {
      ready: !reason,
      reason,
      datasetSnapshot,
      universeSnapshot,
      factorSnapshot,
      marketSnapshot,
      tradeDate,
    };
  }, [config, market, selectedPool]);

  const currentEvidence = useMemo(() => {
    if (!selectedPool?.latest_generation_id) {
      return { bound: false, reason: "当前规则尚无成功生成记录" };
    }
    if (
      selectedPool.pool_type === "factor" &&
      !selectedPool.latest_factor_snapshot_id
    ) {
      return { bound: false, reason: "当前成员未绑定因子快照" };
    }
    if (
      ["sector", "event"].includes(selectedPool.pool_type) &&
      !selectedPool.latest_market_evidence_snapshot_id
    ) {
      return { bound: false, reason: "当前成员未绑定市场证据快照" };
    }
    return { bound: true, reason: "" };
  }, [selectedPool]);

  const sealedSnapshots = snapshots.length;
  const poolsWithMembers = businessPools.filter(
    (item) => item.current_member_count > 0
  ).length;

  const nextAction = useMemo(() => {
    if (!selectedPool) {
      return {
        title: "还没选中股票池",
        detail: "从左侧目录点一条规则，或在「基础筛选与建池」新建筛选规则。",
        step: 1 as const,
      };
    }
    if (!selectedPool.latest_generation_id || members.length === 0) {
      return {
        title: "下一步：生成成员",
        detail: binding.ready
          ? `将用 ${binding.tradeDate} 的封存输入跑一遍规则，得到带理由与有效期的候选名单。`
          : binding.reason,
        step: 2 as const,
      };
    }
    if (selectedPool.snapshot_count === 0) {
      return {
        title: "下一步：封存快照",
        detail:
          "把当前成员名单冻成不可变快照，之后回测只认这份名单，后续调优池子不影响历史回测存根。",
        step: 3 as const,
      };
    }
    return {
      title: "下一步：送去回测",
      detail: "切换到「快照与回测」标签选择已封存快照，一键生成策略回测草稿。",
      step: 4 as const,
    };
  }, [
    binding.ready,
    binding.reason,
    binding.tradeDate,
    members.length,
    selectedPool,
  ]);

  // Compute BarList visualization data for pool member reason / score metrics
  const barListData = useMemo(() => {
    if (!members.length) return [];
    const counts: Record<string, number> = {};
    members.forEach((m) => {
      // Group by reason keyword or score range
      const key = m.reason.split("，")[0] || m.reason.slice(0, 12);
      counts[key] = (counts[key] || 0) + 1;
    });
    return Object.entries(counts)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 5);
  }, [members]);

  const create = async () => {
    setBusy("create");
    setError("");
    setMessage("");
    try {
      const poolConfig: Record<string, unknown> = {
        top_n: topN,
        exclude_st: true,
        exclude_suspended: true,
        min_listing_days: 120,
        validity_days: 5,
      };
      if (creationType === "factor")
        Object.assign(poolConfig, {
          factor_code: factorCode,
          direction: "desc",
        });
      if (creationType === "sector")
        Object.assign(poolConfig, {
          sectors: sector
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean),
        });
      if (creationType === "event") Object.assign(poolConfig, { keyword });
      if (creationType === "screener")
        Object.assign(poolConfig, {
          symbols: symbols
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean),
          min_price: minPrice,
          min_turnover: minTurnover,
        });
      const created = await createStockPool({
        name:
          name ||
          `${TYPE_GUIDES[creationType].title} ${new Date().toLocaleDateString()}`,
        pool_type: creationType,
        description: TYPE_GUIDES[creationType].blurb,
        config: poolConfig,
      });
      await load();
      setSelectedPoolId(created.id);
      setMessage(`已成功创建规则 v${created.rule_version}，下一步点「生成成员」`);
      setParams({ tab: "mine" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setBusy("");
    }
  };

  const generate = async () => {
    if (
      !selectedPool ||
      !binding.ready ||
      !binding.datasetSnapshot ||
      !binding.universeSnapshot ||
      !binding.tradeDate
    ) {
      setError(binding.reason || "缺少兼容的封存输入");
      return;
    }
    setBusy("generate");
    setError("");
    setMessage("");
    try {
      const payload = {
        dataset_snapshot_id: binding.datasetSnapshot.id,
        universe_snapshot_id: binding.universeSnapshot.id,
        trade_date: binding.tradeDate,
        ...(selectedPool.pool_type === "factor" && binding.factorSnapshot
          ? { factor_snapshot_id: binding.factorSnapshot.id }
          : {}),
        ...(["sector", "event"].includes(selectedPool.pool_type) &&
        binding.marketSnapshot
          ? { market_evidence_snapshot_id: binding.marketSnapshot.id }
          : {}),
      };
      const generation = await generateStockPool(selectedPool.id, payload);
      setLastGenerationId(generation.id);
      setMembers(generation.members);
      await load();
      setMessage(
        `${generation.reused ? "复用已有结果" : "已完成筛选"}，入选 ${generation.member_count} 只标的`
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "生成失败");
    } finally {
      setBusy("");
    }
  };

  const seal = async () => {
    if (!selectedPool) return;
    setBusy("seal");
    setError("");
    try {
      const snapshot = await sealStockPoolSnapshot(
        selectedPool.id,
        lastGenerationId || undefined
      );
      await load();
      setMessage(`股票池快照已成功封存，包含 ${snapshot.member_count} 只标的`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "封存失败");
    } finally {
      setBusy("");
    }
  };

  const toBacktest = async (snapshot: StockPoolSnapshot) => {
    if (!config?.strategy_versions[0]) return;
    setBusy(`backtest-${snapshot.id}`);
    setError("");
    try {
      const data = await createPoolBacktestDraft(snapshot.id, {
        strategy_version_id: config.strategy_versions[0].id,
        start_date:
          config.dataset_snapshots.find(
            (item) => item.id === snapshot.dataset_snapshot_id
          )?.start_date ?? "2024-01-02",
        end_date: snapshot.trade_date,
        initial_cash: 1_000_000,
        benchmark_code: "000300.SH",
        parameters: {},
      });
      const experimentId = String(data.experiment.id ?? "");
      navigate(
        `/backtest?poolSnapshotId=${snapshot.id}&experimentId=${experimentId}`
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "回测草稿创建失败");
    } finally {
      setBusy("");
    }
  };

  const activeGuide = TYPE_GUIDES[creationType];

  return (
    <div
      className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8"
      data-testid="stock-pool-workbench"
      data-operator-page="pools"
    >
      <OperatorPageHeader
        icon={Layers3}
        title="股票池工作台"
        subtitle="将行情、板块轮动、事件催化与因子规则转化为可复现、带审计理由的候选标的池，并封存为不可变快照供量化策略回测使用。"
        actions={
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-3.5 text-xs text-slate-300 transition-colors hover:bg-white/[0.05] hover:text-white"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            刷新状态
          </button>
        }
      />

      {/* Top Standard Workflow Stepper */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <WorkflowStep
          step={1}
          label="1. 设定规则"
          active={tab === "screener"}
          done={businessPools.length > 0}
        />
        <ArrowRight className="hidden h-3.5 w-3.5 text-slate-600 sm:block" />
        <WorkflowStep
          step={2}
          label="2. 筛选成员"
          active={tab === "mine" && nextAction.step === 2}
          done={poolsWithMembers > 0}
        />
        <ArrowRight className="hidden h-3.5 w-3.5 text-slate-600 sm:block" />
        <WorkflowStep
          step={3}
          label="3. 封存快照"
          active={tab === "mine" && nextAction.step === 3}
          done={sealedSnapshots > 0}
        />
        <ArrowRight className="hidden h-3.5 w-3.5 text-slate-600 sm:block" />
        <WorkflowStep
          step={4}
          label="4. 送去回测"
          active={tab === "snapshots"}
          done={false}
        />
      </div>

      {/* Top Tremor KPI Cards */}
      <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <TremorCard decorationColor="blue">
          <div className="text-[11px] font-medium text-slate-400">已建规则总数</div>
          <div className="mt-1 flex items-baseline justify-between">
            <MetricValue tone="blue" size="md">
              {businessPools.length}
            </MetricValue>
            <span className="text-[11px] text-slate-500">套选股规则</span>
          </div>
        </TremorCard>

        <TremorCard decorationColor="emerald">
          <div className="text-[11px] font-medium text-slate-400">已生成成员规则</div>
          <div className="mt-1 flex items-baseline justify-between">
            <MetricValue tone="up" size="md">
              {poolsWithMembers}
            </MetricValue>
            <span className="text-[11px] text-slate-500">含选股结果</span>
          </div>
        </TremorCard>

        <TremorCard decorationColor="amber">
          <div className="text-[11px] font-medium text-slate-400">已封存快照存根</div>
          <div className="mt-1 flex items-baseline justify-between">
            <MetricValue tone="amber" size="md">
              {sealedSnapshots}
            </MetricValue>
            <span className="text-[11px] text-slate-500">份不可变证据</span>
          </div>
        </TremorCard>

        <TremorCard decorationColor="blue">
          <div className="text-[11px] font-medium text-slate-400">当前选中股票池</div>
          <div className="mt-1 flex items-center justify-between">
            <span className="truncate font-semibold text-amber-200">
              {selectedPool ? selectedPool.name : "尚未选择"}
            </span>
            {selectedPool && <PoolTypeBadge type={selectedPool.pool_type} />}
          </div>
        </TremorCard>
      </div>

      {/* Primary L2 Workspace Tabs */}
      <WorkspaceTabs
        ariaLabel="股票池主功能导航"
        items={TABS.map(([id, label]) => ({
          id,
          label,
          testId: `pool-tab-${id}`,
        }))}
        value={tab}
        onChange={(id) => setParams({ tab: id })}
      />

      {/* System Banners & Warnings */}
      {error ? (
        <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">
          {error}
        </div>
      ) : null}
      {message ? (
        <div className="mb-5 rounded-lg border border-emerald-500/25 bg-emerald-500/10 p-4 text-sm text-emerald-200">
          {message}
        </div>
      ) : null}
      {partialWarnings.length ? (
        <div
          className="mb-5 rounded-lg border border-amber-500/25 bg-amber-500/[0.07] px-4 py-3 text-xs text-amber-200/80"
          role="status"
        >
          <span className="font-semibold text-amber-300">部分数据降级：</span>
          <span className="ml-1">{partialWarnings.join("；")}</span>
        </div>
      ) : null}

      {loading && pools.length === 0 ? (
        <div className={`${panel} mb-5 grid min-h-48 place-items-center text-sm text-slate-500`}>
          正在加载股票池规则与封存快照…
        </div>
      ) : null}

      {/* Main Tab 1: 我的股票池 (mine) */}
      {tab === "mine" ? (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(360px,0.75fr)]">
          {/* Left: Stock Pool List */}
          <section className={`${panel} overflow-hidden`}>
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-5 py-4">
              <div>
                <h2 className="font-semibold text-white">股票池规则目录</h2>
                <p className="mt-1 text-xs text-slate-500">
                  选择一条选股规则进行成员生成、证据校验与快照封存。
                </p>
              </div>
              <button
                type="button"
                onClick={() => setParams({ tab: "screener" })}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-blue-600 px-3 text-xs font-semibold text-white hover:bg-blue-500"
              >
                <Plus className="h-3.5 w-3.5" />
                新建规则
              </button>
            </div>

            <div className="space-y-3 border-b border-crypto-border bg-crypto-bg/35 p-4">
              <OperatorFilterBar>
                <label className="relative min-w-[220px] flex-1">
                  <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-600" />
                  <input
                    value={poolQuery}
                    onChange={(event) => setPoolQuery(event.target.value)}
                    className={`${input} pl-9`}
                    placeholder="搜索规则名称、说明或类型…"
                    aria-label="搜索股票池"
                  />
                </label>
              </OperatorFilterBar>
              <FilterChipGroup<PoolTypeFilter>
                aria-label="类型筛选"
                value={poolTypeFilter}
                onChange={(value) => setPoolTypeFilter(value)}
                options={[
                  { value: "all", label: "全部" },
                  { value: "sector", label: "板块选股" },
                  { value: "event", label: "事件选股" },
                  { value: "screener", label: "基础条件" },
                  { value: "factor", label: "因子选股" },
                  { value: "manual", label: "手工选股" },
                ]}
              />
            </div>

            <div className="divide-y divide-white/[0.05]">
              {visiblePools.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSelectedPoolId(item.id)}
                  className={`grid w-full gap-3 px-5 py-4 text-left transition-colors sm:grid-cols-[minmax(0,1fr)_90px_92px_92px_100px] sm:items-center ${
                    selectedPoolId === item.id
                      ? "bg-blue-500/[0.08]"
                      : "hover:bg-white/[0.025]"
                  }`}
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-semibold text-slate-100">
                        {item.name}
                      </span>
                    </div>
                    <div className="mt-1 truncate text-[11px] text-slate-500">
                      {item.description || "未填写说明"}
                    </div>
                  </div>
                  <PoolTypeBadge type={item.pool_type} />
                  <div>
                    <div className="text-[10px] text-slate-500">成员 / 快照</div>
                    <div className="mt-1 font-mono text-xs text-slate-300">
                      {item.current_member_count} / {item.snapshot_count}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-slate-500">最新交易日</div>
                    <div className="mt-1 font-mono text-xs text-slate-300">
                      {item.latest_trade_date ?? "--"}
                    </div>
                  </div>
                  <div className="sm:text-right">
                    <div className="font-mono text-[10px] text-slate-500">
                      v{item.rule_version}
                    </div>
                    <div className="mt-1 text-[11px] font-semibold text-blue-400">
                      查看明细 →
                    </div>
                  </div>
                </button>
              ))}

              {!loading && visiblePools.length === 0 ? (
                <div className="grid min-h-56 place-items-center px-6 py-10 text-center">
                  <div>
                    <Layers3 className="mx-auto h-8 w-8 text-slate-700" />
                    <div className="mt-3 text-sm font-semibold text-slate-300">
                      暂无对应选股规则
                    </div>
                    <p className="mt-2 text-xs text-slate-500">
                      选择常用基础筛选方法创建第一条股票池规则。
                    </p>
                    <div className="mt-4 flex flex-wrap justify-center gap-2">
                      {(
                        [
                          ["sector", "板块选股"],
                          ["event", "事件选股"],
                          ["screener", "基础条件"],
                          ["factor", "因子选股"],
                        ] as Array<[CreationType, string]>
                      ).map(([key, label]) => (
                        <button
                          key={key}
                          type="button"
                          onClick={() => {
                            setCreationType(key);
                            setParams({ tab: "screener" });
                          }}
                          className="rounded-md border border-crypto-border bg-crypto-bg px-3 py-1.5 text-xs text-slate-300 hover:border-blue-500/45 hover:text-blue-200"
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="flex flex-wrap gap-3 border-t border-crypto-border px-5 py-4">
              <button
                data-testid="generate-pool"
                onClick={() => void generate()}
                disabled={Boolean(busy) || !selectedPool || !binding.ready}
                title={!binding.ready ? binding.reason : undefined}
                className="inline-flex h-9 items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 text-xs font-semibold text-blue-300 hover:bg-blue-500/20 disabled:opacity-40"
              >
                <Filter className="h-3.5 w-3.5" />
                生成最新成员
              </button>
              <button
                data-testid="seal-pool"
                onClick={() => void seal()}
                disabled={
                  Boolean(busy) || !selectedPool || members.length === 0
                }
                className="inline-flex h-9 items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-40"
              >
                <ShieldCheck className="h-3.5 w-3.5" />
                封存快照存根
              </button>
              {selectedPool && selectedPool.snapshot_count > 0 ? (
                <button
                  type="button"
                  onClick={() => setParams({ tab: "snapshots" })}
                  className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border px-4 text-xs text-slate-300 hover:text-white"
                >
                  <Archive className="h-3.5 w-3.5" />
                  去快照回测
                </button>
              ) : null}
            </div>
          </section>

          {/* Right: Next Step Guide & Evidence Overview */}
          <div className="space-y-5">
            <TremorCallout
              title={nextAction.title}
              color={
                nextAction.step === 1
                  ? "amber"
                  : nextAction.step === 2
                    ? "blue"
                    : "emerald"
              }
            >
              <p className="text-xs">{nextAction.detail}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {nextAction.step === 1 ? (
                  <button
                    type="button"
                    onClick={() => setParams({ tab: "screener" })}
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-blue-600 px-3 text-xs font-semibold text-white"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    去创建规则
                  </button>
                ) : null}
                {nextAction.step === 2 ? (
                  <button
                    type="button"
                    onClick={() => void generate()}
                    disabled={Boolean(busy) || !binding.ready}
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 text-xs font-semibold text-blue-300 disabled:opacity-40"
                  >
                    <Filter className="h-3.5 w-3.5" />
                    生成成员
                  </button>
                ) : null}
                {nextAction.step === 3 ? (
                  <button
                    type="button"
                    onClick={() => void seal()}
                    disabled={Boolean(busy) || members.length === 0}
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 text-xs font-semibold text-emerald-300 disabled:opacity-40"
                  >
                    <ShieldCheck className="h-3.5 w-3.5" />
                    封存不可变快照
                  </button>
                ) : null}
                {nextAction.step === 4 ? (
                  <button
                    type="button"
                    onClick={() => setParams({ tab: "snapshots" })}
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 text-xs font-semibold text-blue-300"
                  >
                    <Play className="h-3.5 w-3.5" />
                    查看已封存快照
                  </button>
                ) : null}
              </div>
            </TremorCallout>

            {/* Evidence & Input Binding Panel */}
            <section className={`${panel} p-5`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold text-white">输入绑定与证据状态</h3>
                  <p className="mt-1 text-xs text-slate-500">
                    {selectedPool?.name ?? "未选择规则"}
                  </p>
                </div>
                <span
                  className={`rounded-md border px-2 py-0.5 text-[10px] font-semibold ${
                    currentEvidence.bound
                      ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300"
                      : "border-amber-500/25 bg-amber-500/10 text-amber-300"
                  }`}
                >
                  {currentEvidence.bound ? "证据已绑定" : "证据未绑定"}
                </span>
              </div>

              <div className="mt-4 space-y-2.5 text-xs">
                {[
                  [
                    "规则版本",
                    selectedPool ? `v${selectedPool.rule_version}` : "--",
                  ],
                  ["最新交易日", selectedPool?.latest_trade_date ?? "--"],
                  [
                    "数据/股票范围",
                    selectedPool?.latest_dataset_snapshot_id &&
                    selectedPool.latest_universe_snapshot_id
                      ? "研究数据快照已绑定 · 历史股票范围已绑定"
                      : "--",
                  ],
                  [
                    selectedPool?.pool_type === "factor"
                      ? "因子快照"
                      : ["sector", "event"].includes(
                          selectedPool?.pool_type ?? ""
                        )
                        ? "市场证据"
                        : "候选来源",
                    selectedPool?.pool_type === "factor"
                      ? selectedPool.latest_factor_snapshot_id
                        ? "因子快照已绑定"
                        : "未绑定"
                      : ["sector", "event"].includes(
                          selectedPool?.pool_type ?? ""
                        )
                        ? selectedPool?.latest_market_evidence_snapshot_id
                          ? "盘后市场证据已绑定"
                          : "未绑定"
                        : "全市场/定义范围",
                  ],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="flex items-center justify-between rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2"
                  >
                    <span className="text-slate-500">{label}</span>
                    <span className="font-mono text-slate-300">{value}</span>
                  </div>
                ))}
              </div>

              {selectedPool ? (
                <DiagnosticDetails
                  ariaLabel="输入绑定诊断原值"
                  fields={[
                    ["dataset_snapshot_id", selectedPool.latest_dataset_snapshot_id == null ? null : `Dataset #${selectedPool.latest_dataset_snapshot_id}`],
                    ["universe_snapshot_id", selectedPool.latest_universe_snapshot_id == null ? null : `Universe #${selectedPool.latest_universe_snapshot_id}`],
                    ["factor_snapshot_id", selectedPool.latest_factor_snapshot_id == null ? null : `Factor #${selectedPool.latest_factor_snapshot_id}`],
                    ["market_evidence_snapshot_id", selectedPool.latest_market_evidence_snapshot_id == null ? null : `Market #${selectedPool.latest_market_evidence_snapshot_id}`],
                  ]}
                />
              ) : null}

              {barListData.length > 0 && (
                <div className="mt-4 pt-4 border-t border-crypto-border/60">
                  <div className="mb-2 text-[11px] font-semibold text-slate-400">
                    入选理由分布 Top 5
                  </div>
                  <TremorBarList data={barListData} color="blue" />
                </div>
              )}
            </section>
          </div>

          {/* Bottom Full Member Table */}
          <section className={`${panel} overflow-hidden xl:col-span-2`}>
            <div className="border-b border-crypto-border px-5 py-4">
              <h2 className="font-semibold text-white">当前入选成员明细与存根理由</h2>
              <p className="mt-1 text-xs text-slate-500">
                {membersLoading
                  ? "正在读取入选成员…"
                  : membersError
                    ? "成员读取失败"
                    : `共 ${members.length} 只标的。包含入选顺序、权重得分、具体理由及生效期限。`}
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-sm">
                <thead>
                  <tr className="border-b border-crypto-border text-left text-xs text-slate-500">
                    <th className="px-5 py-3">序号</th>
                    <th className="px-4 py-3">证券标的</th>
                    <th className="px-4 py-3 text-right">得分/排名</th>
                    <th className="px-4 py-3">入选理由与证据</th>
                    <th className="px-4 py-3">有效期</th>
                    <th className="px-5 py-3 text-right">证据状态</th>
                  </tr>
                </thead>
                <tbody>
                  {members.map((item) => (
                    <tr
                      key={item.symbol}
                      className="border-b border-white/[0.04] transition-colors hover:bg-white/[0.02]"
                    >
                      <td className="px-5 py-2.5 font-mono text-xs text-slate-500">
                        {item.ordinal}
                      </td>
                      <td className="px-4 py-2.5">
                        <SymbolCell
                          symbol={item.symbol}
                          name={item.name}
                          compact
                        />
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs tabular-nums text-slate-300">
                        {item.score !== null && item.score !== undefined
                          ? item.score.toFixed(4)
                          : "--"}
                      </td>
                      <td className="max-w-md px-4 py-2.5 text-xs text-slate-400">
                        {item.reason}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-slate-500">
                        <div>
                          {item.valid_from} → {item.valid_until ?? "--"}
                        </div>
                        {memberIsExpired(item) ? (
                          <span className="mt-0.5 inline-block rounded border border-amber-500/20 bg-amber-500/[0.07] px-1.5 py-0.5 text-[10px] text-amber-300">
                            已过期
                          </span>
                        ) : null}
                      </td>
                      <td className="px-5 py-2.5 text-right text-xs">
                        {item.evidence_hash ? (
                          <span className="inline-flex items-center gap-1 text-emerald-400">
                            <CheckCircle2 className="h-3 w-3" /> 已校验
                          </span>
                        ) : (
                          <span className="text-slate-500">待校验</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {!membersLoading && membersError ? (
                <div className="grid min-h-36 place-items-center px-6 text-center text-xs text-red-300">
                  {membersError}
                </div>
              ) : null}

              {!membersLoading && !membersError && members.length === 0 ? (
                <div className="grid min-h-36 place-items-center px-6 text-center text-xs text-slate-600">
                  当前规则尚无筛选成员。请选择规则后点击「生成最新成员」。
                </div>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}

      {/* Main Tab 2: 基础筛选与建池 (screener) */}
      {tab === "screener" ? (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(360px,0.8fr)]">
          {/* Left Form: Unified Multi-Mode Screener Builder */}
          <section className={`${panel} overflow-hidden`}>
            <div className="border-b border-crypto-border px-5 py-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="font-semibold text-white">基础筛选规则生成器</h2>
                  <p className="mt-1 text-xs text-slate-500">
                    选择筛选模式，填写筛选门槛与行业/主题条件，生成可持久化的选股规则。
                  </p>
                </div>
                <div className="flex items-center gap-1 rounded-lg border border-crypto-border bg-crypto-bg p-1 text-xs">
                  {(
                    [
                      ["sector", "板块选股"],
                      ["event", "事件选股"],
                      ["screener", "基础条件"],
                      ["factor", "因子选股"],
                    ] as Array<[CreationType, string]>
                  ).map(([type, label]) => (
                    <button
                      key={type}
                      type="button"
                      onClick={() => setCreationType(type)}
                      className={`rounded-md px-3 py-1 font-semibold transition-all ${
                        creationType === type
                          ? "bg-blue-600 text-white shadow-sm"
                          : "text-slate-400 hover:text-white"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Mode Guide Callout */}
            <div className="px-5 pt-4">
              <TremorCallout
                title={activeGuide.title}
                color={activeGuide.color}
              >
                <p className="text-xs leading-relaxed">{activeGuide.blurb}</p>
                <div className="mt-1 text-[11px] font-medium text-slate-400">
                  提示：{activeGuide.tip}
                </div>
              </TremorCallout>
            </div>

            {/* Config Form Inputs */}
            <div className="grid gap-4 p-5 md:grid-cols-2">
              <label className="text-xs text-slate-400 md:col-span-2">
                <span className="font-semibold text-slate-200">规则名称</span>
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  className={`${input} mt-1.5`}
                  placeholder={`例如：${activeGuide.title} - ${new Date().toLocaleDateString()}`}
                />
              </label>

              <label className="text-xs text-slate-400">
                <span className="font-semibold text-slate-200">最大候选数量 (Top N)</span>
                <input
                  type="number"
                  value={topN}
                  onChange={(event) => setTopN(Number(event.target.value))}
                  className={`${input} mt-1.5`}
                  min={1}
                  max={500}
                />
              </label>

              {/* Mode-specific Fields */}
              {creationType === "sector" && (
                <label className="text-xs text-slate-400 md:col-span-2">
                  <span className="font-semibold text-slate-200">目标板块 / 行业名称 (多行业用逗号分隔)</span>
                  <input
                    value={sector}
                    onChange={(event) => setSector(event.target.value)}
                    className={`${input} mt-1.5`}
                    placeholder="例如：商业百货, 半导体, 光模块"
                  />
                  <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px]">
                    <span className="text-slate-500">快捷预设：</span>
                    {["商业百货", "半导体", "汽车零部件", "软件开发", "医药商业"].map(
                      (s) => (
                        <button
                          key={s}
                          type="button"
                          onClick={() => setSector(s)}
                          className="rounded border border-crypto-border bg-crypto-bg/60 px-2 py-0.5 text-blue-300 hover:border-blue-500/50"
                        >
                          {s}
                        </button>
                      )
                    )}
                  </div>
                </label>
              )}

              {creationType === "event" && (
                <label className="text-xs text-slate-400 md:col-span-2">
                  <span className="font-semibold text-slate-200">事件主题关键字</span>
                  <input
                    value={keyword}
                    onChange={(event) => setKeyword(event.target.value)}
                    className={`${input} mt-1.5`}
                    placeholder="例如：重组, 增持, 连板, 机器人"
                  />
                  <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px]">
                    <span className="text-slate-500">推荐热词：</span>
                    {["重组", "增持", "首板", "高送转", "人工智能"].map((kw) => (
                      <button
                        key={kw}
                        type="button"
                        onClick={() => setKeyword(kw)}
                        className="rounded border border-crypto-border bg-crypto-bg/60 px-2 py-0.5 text-emerald-300 hover:border-emerald-500/50"
                      >
                        {kw}
                      </button>
                    ))}
                  </div>
                </label>
              )}

              {creationType === "screener" && (
                <>
                  <label className="text-xs text-slate-400 md:col-span-2">
                    <span className="font-semibold text-slate-200">基础股票名单 (留空则默认全市场标的)</span>
                    <input
                      value={symbols}
                      onChange={(event) => setSymbols(event.target.value)}
                      className={`${input} mt-1.5`}
                      placeholder="600519.SH, 000333.SZ"
                    />
                  </label>

                  <label className="text-xs text-slate-400">
                    <span className="font-semibold text-slate-200">最低收盘价 (元)</span>
                    <input
                      type="number"
                      value={minPrice}
                      onChange={(event) => setMinPrice(Number(event.target.value))}
                      className={`${input} mt-1.5`}
                      placeholder="0 表示不限制"
                    />
                  </label>

                  <label className="text-xs text-slate-400">
                    <span className="font-semibold text-slate-200">最低日成交额 (元)</span>
                    <input
                      type="number"
                      value={minTurnover}
                      onChange={(event) => setMinTurnover(Number(event.target.value))}
                      className={`${input} mt-1.5`}
                      placeholder="0 表示不限制"
                    />
                  </label>
                </>
              )}

              {creationType === "factor" && (
                <label className="text-xs text-slate-400 md:col-span-2">
                  <span className="font-semibold text-slate-200">引用因子代码</span>
                  <input
                    value={factorCode}
                    onChange={(event) => setFactorCode(event.target.value)}
                    className={`${input} mt-1.5`}
                    placeholder="momentum_20d"
                  />
                  <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px]">
                    <span className="text-slate-500">标准因子：</span>
                    {["momentum_20d", "reversal_5d", "volatility_20d", "turnover_20d"].map(
                      (fc) => (
                        <button
                          key={fc}
                          type="button"
                          onClick={() => setFactorCode(fc)}
                          className="rounded border border-crypto-border bg-crypto-bg/60 px-2 py-0.5 text-blue-300 hover:border-blue-500/50"
                        >
                          {fc}
                        </button>
                      )
                    )}
                  </div>
                </label>
              )}
            </div>

            {/* Action Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-crypto-border px-5 py-4">
              <div className="text-xs text-slate-500">
                创建规则后将自动进入「我的股票池」并可立即生成候选成员。
              </div>
              <button
                data-testid="create-pool"
                onClick={() => void create()}
                disabled={Boolean(busy)}
                className="inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-5 text-xs font-semibold text-white shadow-sm hover:bg-blue-500 disabled:opacity-50"
              >
                <Plus className="h-4 w-4" />
                创建筛选规则
              </button>
            </div>
          </section>

          {/* Right: Quick Instructions & Strategy Tips */}
          <div className="space-y-5">
            <TremorCard decorationColor="blue">
              <h3 className="flex items-center gap-2 font-semibold text-white">
                <Sparkles className="h-4 w-4 text-blue-400" />
                筛选规则运行原理
              </h3>
              <ul className="mt-3 space-y-2 text-xs leading-relaxed text-slate-400">
                <li className="flex items-start gap-2">
                  <Tag className="mt-0.5 h-3.5 w-3.5 shrink-0 text-blue-400" />
                  <span>
                    <strong>可复现性保证：</strong> 规则并不直接保存硬编码的股票列表，而是保存版本化的筛选参数逻辑。
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <Tag className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                  <span>
                    <strong>自动剔除机制：</strong> 筛选时会自动过滤 ST 股票、已停牌股票及上市不足 120 天的新股。
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <Tag className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
                  <span>
                    <strong>快照隔离：</strong> 点击“封存快照”后，系统会将当时筛选出的股票名单永久冻结，策略回测将严格读取该快照。
                  </span>
                </li>
              </ul>
            </TremorCard>

            <TremorCard decorationColor="emerald">
              <h3 className="font-semibold text-white">已存在规则选择</h3>
              <p className="mt-1 text-xs text-slate-500">
                可快速选择已有相同类型的规则重新触发筛选。
              </p>
              <div className="mt-3">
                <select
                  aria-label="选择股票池"
                  value={selectedPoolId}
                  onChange={(event) => setSelectedPoolId(event.target.value)}
                  className={input}
                >
                  <option value="">选择已有同类规则…</option>
                  {pools
                    .filter((item) => item.pool_type === creationType)
                    .map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name} (v{item.rule_version})
                      </option>
                    ))}
                </select>
                {selectedPool && (
                  <button
                    type="button"
                    onClick={() => setParams({ tab: "mine" })}
                    aria-label="在我的股票池中查看选中的规则"
                    className="mt-3 inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 text-xs font-semibold text-blue-300 hover:bg-blue-500/20"
                  >
                    在「我的股票池」中查看 →
                  </button>
                )}
              </div>
            </TremorCard>
          </div>
        </div>
      ) : null}

      {/* Main Tab 3: 快照与回测 (snapshots) */}
      {tab === "snapshots" ? (
        <section className={`${panel} overflow-hidden`}>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-5 py-4">
            <div>
              <h2 className="font-semibold text-white">不可变股票池快照仓库</h2>
              <p className="mt-1 text-xs text-slate-500">
                一份已封存快照对应某个交易日固定的股票名单。回测引擎严格校验快照哈希，不受后期选股池规则修改影响。
              </p>
            </div>
            <Archive className="h-5 w-5 text-emerald-400" />
          </div>

          <EvidenceStrip
            className="mx-5 mt-4"
            items={[
              { label: "已封存快照", value: sealedSnapshots, tone: "blue" },
              {
                label: "回测对接",
                value: "一键创建策略回测草稿",
                tone: "green",
              },
              {
                label: "防未来函数",
                value: "锁定 Dataset & Universe 知识截止日",
                tone: "amber",
              },
            ]}
          />

          <div className="overflow-x-auto">
            <table
              data-testid="pool-snapshot-table"
              className="w-full min-w-[950px] text-sm"
            >
              <thead>
                <tr className="border-b border-crypto-border text-left text-xs text-slate-500">
                  <th className="px-5 py-3">封存状态</th>
                  <th className="px-4 py-3">股票池规则</th>
                  <th className="px-4 py-3">交易日</th>
                  <th className="px-4 py-3 text-right">成员数量</th>
                  <th className="px-4 py-3">数据与证据绑定</th>
                  <th className="px-5 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {snapshots.map((snapshot) => (
                  <tr
                    key={snapshot.id}
                    className="border-b border-white/[0.04] transition-colors hover:bg-white/[0.02]"
                  >
                    <td className="px-5 py-4 text-emerald-400">
                      已封存快照
                    </td>
                    <td className="px-4 py-4">
                      <div className="font-medium text-slate-200">
                        {snapshot.pool_name}
                      </div>
                      <div className="mt-1">
                        <PoolTypeBadge type={snapshot.pool_type} />
                      </div>
                    </td>
                    <td className="px-4 py-4 font-mono text-xs text-slate-300">
                      {snapshot.trade_date}
                    </td>
                    <td className="px-4 py-4 text-right font-mono tabular-nums text-blue-300">
                      {snapshot.member_count} 只
                    </td>
                    <td className="px-4 py-4 text-xs text-slate-400">
                      <div>
                        研究数据快照已绑定 · 历史股票范围已绑定
                      </div>
                      <div className="mt-0.5 text-[11px] text-slate-500">
                        {snapshot.factor_snapshot_id
                          ? "因子快照已绑定"
                          : snapshot.market_evidence_snapshot_id
                            ? "盘后市场证据已绑定"
                            : "基础规则出池"}
                      </div>
                      <DiagnosticDetails
                        ariaLabel="快照诊断原值"
                        fields={[
                          ["snapshot_id", `Pool Snapshot #${snapshot.id}`],
                          ["dataset_snapshot_id", `Dataset #${snapshot.dataset_snapshot_id}`],
                          ["universe_snapshot_id", `Universe #${snapshot.universe_snapshot_id}`],
                          ["factor_snapshot_id", snapshot.factor_snapshot_id == null ? null : `Factor #${snapshot.factor_snapshot_id}`],
                          ["market_evidence_snapshot_id", snapshot.market_evidence_snapshot_id == null ? null : `Market #${snapshot.market_evidence_snapshot_id}`],
                        ]}
                      />
                    </td>
                    <td className="px-5 py-4 text-right">
                      <button
                        data-testid={`pool-backtest-${snapshot.id}`}
                        onClick={() => void toBacktest(snapshot)}
                        disabled={Boolean(busy)}
                        className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 text-xs font-semibold text-blue-300 hover:bg-blue-500/20 disabled:opacity-40"
                      >
                        <Play className="h-3.5 w-3.5" />
                        创建回测草稿
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {!loading && snapshots.length === 0 ? (
              <div className="grid min-h-44 place-items-center px-6 text-center text-xs text-slate-600">
                暂无已封存快照。请先在「我的股票池」生成成员并点击「封存快照存根」。
              </div>
            ) : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}

export default StockPools;
