import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Archive,
  Filter,
  Layers3,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  TestTube2,
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
import type {
  BacktestConfiguration,
  MarketResearchContext,
  StockPool,
  StockPoolMember,
  StockPoolSnapshot,
} from "../types";

const TABS = [
  ["mine", "我的股票池"],
  ["screener", "条件选股"],
  ["factor", "因子股票池"],
  ["sector", "板块股票池"],
  ["event", "事件股票池"],
  ["snapshots", "快照仓库"],
] as const;
type TabKey = (typeof TABS)[number][0];
type CatalogueScope = "business" | "test";
type PoolTypeFilter = "all" | StockPool["pool_type"];
const panel = "rounded-xl border border-crypto-border bg-crypto-card";
const input =
  "h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-slate-200 outline-none focus:border-blue-500/60";
const publicSymbol = (value: string) => {
  const match = value.toUpperCase().match(/^(SH|SZ|BJ)_([T]?\d{6})$/);
  return match ? `${match[2]}.${match[1]}` : value;
};
const poolTypeLabel = (type: string) =>
  ({ screener: "条件", factor: "因子", sector: "板块", event: "事件", manual: "手工" })[type] ?? type;
const memberIsExpired = (member: StockPoolMember) =>
  Boolean(member.valid_until && member.valid_until < new Date().toISOString().slice(0, 10));

function PoolTypeBadge({ type }: { type: string }) {
  return (
    <span className="rounded-md border border-purple-500/25 bg-purple-500/10 px-2 py-1 text-[11px] font-semibold text-purple-200">
      {poolTypeLabel(type)}
    </span>
  );
}

export function StockPools() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") as TabKey | null;
  const tab: TabKey = TABS.some(([key]) => key === requested)
    ? requested!
    : "mine";
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
  const [name, setName] = useState("");
  const [topN, setTopN] = useState(20);
  const [factorCode, setFactorCode] = useState("momentum_20d");
  const [sector, setSector] = useState("商业百货");
  const [keyword, setKeyword] = useState("");
  const [symbols, setSymbols] = useState("600519.SH,000333.SZ");
  const [minPrice, setMinPrice] = useState(0);
  const [minTurnover, setMinTurnover] = useState(0);
  const [lastGenerationId, setLastGenerationId] = useState("");
  const [catalogueScope, setCatalogueScope] =
    useState<CatalogueScope>("business");
  const [poolTypeFilter, setPoolTypeFilter] =
    useState<PoolTypeFilter>("all");
  const [poolQuery, setPoolQuery] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    setPartialWarnings([]);
    const [poolResult, snapshotResult, configResult, marketResult] = await Promise.allSettled([
      listStockPools(),
      listStockPoolSnapshots(),
      getBacktestConfiguration(),
      getMarketResearchContext(),
    ]);
    const warnings: string[] = [];
    if (poolResult.status === "fulfilled") {
      setPools(poolResult.value.items);
    } else {
      setError(poolResult.reason instanceof Error ? poolResult.reason.message : "股票池规则读取失败");
    }
    if (snapshotResult.status === "fulfilled") setSnapshots(snapshotResult.value.items);
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
        setMembersError(reason instanceof Error ? reason.message : "成员证据读取失败");
      })
      .finally(() => {
        if (active) setMembersLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedPoolId]);

  const businessPools = useMemo(
    () => pools.filter((item) => !item.data_purpose || item.data_purpose === "user"),
    [pools],
  );
  const testPools = useMemo(
    () => pools.filter((item) => item.data_purpose && item.data_purpose !== "user"),
    [pools],
  );
  const visiblePools = useMemo(() => {
    const source = catalogueScope === "business" ? businessPools : testPools;
    const normalizedQuery = poolQuery.trim().toLowerCase();
    return source
      .filter((item) => poolTypeFilter === "all" || item.pool_type === poolTypeFilter)
      .filter((item) => {
        if (!normalizedQuery) return true;
        return [item.name, item.description, item.pool_type, item.rule_type]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(normalizedQuery));
      })
      .sort((left, right) => {
        const dateOrder = String(right.latest_trade_date ?? "").localeCompare(
          String(left.latest_trade_date ?? ""),
        );
        return dateOrder || left.name.localeCompare(right.name, "zh-CN");
      });
  }, [businessPools, catalogueScope, poolQuery, poolTypeFilter, testPools]);
  const selectedPool = pools.find((item) => item.id === selectedPoolId);
  useEffect(() => {
    if (tab !== "mine") return;
    if (visiblePools.some((item) => item.id === selectedPoolId)) return;
    setSelectedPoolId(visiblePools[0]?.id ?? "");
  }, [selectedPoolId, tab, visiblePools]);
  const creationType: StockPool["pool_type"] =
    tab === "factor" || tab === "sector" || tab === "event" ? tab : "screener";
  useEffect(() => {
    if (tab === "mine" || tab === "snapshots") return;
    const current = pools.find((item) => item.id === selectedPoolId);
    const selectablePools =
      catalogueScope === "test" ? testPools : businessPools;
    if (
      current?.pool_type === creationType &&
      selectablePools.some((item) => item.id === current.id)
    )
      return;
    setSelectedPoolId(
      selectablePools.find((item) => item.pool_type === creationType)?.id ?? "",
    );
  }, [
    businessPools,
    catalogueScope,
    creationType,
    pools,
    selectedPoolId,
    tab,
    testPools,
  ]);
  const binding = useMemo(() => {
    if (!selectedPool || !config) return { ready: false, reason: "请选择股票池并等待输入配置" };
    const needsFactor = selectedPool.pool_type === "factor";
    const needsMarket = selectedPool.pool_type === "sector" || selectedPool.pool_type === "event";
    const factorSnapshot = needsFactor ? config.factor_snapshots[0] : undefined;
    const tradeDate = factorSnapshot?.trade_date
      ?? (needsMarket ? market?.snapshot?.trade_date : undefined)
      ?? config.universe_snapshots[0]?.trade_date;
    const universeSnapshot = factorSnapshot
      ? config.universe_snapshots.find((item) => item.id === factorSnapshot.universe_snapshot_id)
      : config.universe_snapshots.find((item) => item.trade_date === tradeDate) ?? config.universe_snapshots[0];
    const datasetSnapshot = factorSnapshot
      ? config.dataset_snapshots.find((item) => item.id === factorSnapshot.dataset_snapshot_id)
      : config.dataset_snapshots.find((item) => Boolean(tradeDate) && item.start_date <= tradeDate! && item.end_date >= tradeDate!)
        ?? config.dataset_snapshots[0];
    const marketSnapshot = needsMarket && market?.snapshot?.trade_date === tradeDate ? market.snapshot : null;
    let reason = "";
    if (!datasetSnapshot || !universeSnapshot || !tradeDate) reason = "缺少兼容的数据或股票范围快照";
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
    if (selectedPool.pool_type === "factor" && !selectedPool.latest_factor_snapshot_id) {
      return { bound: false, reason: "当前成员未绑定因子快照" };
    }
    if (["sector", "event"].includes(selectedPool.pool_type) && !selectedPool.latest_market_evidence_snapshot_id) {
      return { bound: false, reason: "当前成员未绑定市场证据快照" };
    }
    return { bound: true, reason: "" };
  }, [selectedPool]);

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
          `${TABS.find(([key]) => key === tab)?.[1]} ${new Date().toLocaleDateString()}`,
        pool_type: creationType,
        description: "基于研究数据的版本化股票池",
        config: poolConfig,
      });
      await load();
      setCatalogueScope("business");
      setSelectedPoolId(created.id);
      setMessage(`已创建规则 v${created.rule_version}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setBusy("");
    }
  };

  const generate = async () => {
    if (!selectedPool || !binding.ready || !binding.datasetSnapshot || !binding.universeSnapshot || !binding.tradeDate) {
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
        ...(["sector", "event"].includes(selectedPool.pool_type) && binding.marketSnapshot
          ? { market_evidence_snapshot_id: binding.marketSnapshot.id }
          : {}),
      };
      const generation = await generateStockPool(selectedPool.id, payload);
      setLastGenerationId(generation.id);
      setMembers(generation.members);
      await load();
      setMessage(
        `${generation.reused ? "复用已有结果" : "已生成"} ${generation.member_count} 只`,
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
        lastGenerationId || undefined,
      );
      await load();
      setMessage(`${snapshot.pool_name} 已封存，共 ${snapshot.member_count} 只`);
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
            (item) => item.id === snapshot.dataset_snapshot_id,
          )?.start_date ?? "2024-01-02",
        end_date: snapshot.trade_date,
        initial_cash: 1_000_000,
        benchmark_code: "000300.SH",
        parameters: {},
      });
      const experimentId = String(data.experiment.id ?? "");
      navigate(
        `/backtest?poolSnapshotId=${snapshot.id}&experimentId=${experimentId}`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "回测草稿创建失败");
    } finally {
      setBusy("");
    }
  };

  return (
    <div
      className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8"
      data-testid="stock-pool-workbench"
    >
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <Layers3 className="h-7 w-7 text-purple-400" />
            <h1 className="text-2xl font-black text-white">股票池</h1>
          </div>
          <p className="mt-2 text-sm text-slate-500">
            管理选股规则、成员、版本和回测引用；业务对象与测试数据分区展示。
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-400 hover:text-white"
        >
          <RefreshCw className="h-4 w-4" />
          刷新
        </button>
      </header>
      <WorkspaceTabs
        className="mb-5"
        ariaLabel="股票池二级导航"
        items={TABS.map(([id, label]) => ({ id, label, testId: `pool-tab-${id}` }))}
        value={tab}
        onChange={(id) => setParams({ tab: id })}
      />
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
        <div className="mb-5 rounded-lg border border-amber-500/25 bg-amber-500/[0.07] px-4 py-3 text-xs text-amber-200/80" role="status">
          <span className="font-semibold text-amber-300">部分数据降级</span>
          <span className="ml-2">{partialWarnings.join("；")}。已加载的股票池仍可查看。</span>
        </div>
      ) : null}
      {loading && pools.length === 0 ? (
        <div className={`${panel} mb-5 grid min-h-48 place-items-center text-sm text-slate-500`}>
          正在读取股票池与封存证据…
        </div>
      ) : null}

      {tab !== "snapshots" ? (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(360px,0.75fr)]">
          {tab === "mine" ? (
            <section className={`${panel} overflow-hidden`}>
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-5 py-4">
                <div>
                  <h2 className="font-semibold text-white">股票池目录</h2>
                  <p className="mt-1 text-xs text-slate-500">
                    业务股票池与测试对象分区管理；选择一条规则查看版本和成员证据。
                  </p>
                </div>
                <span className="text-xs text-slate-500">
                  {visiblePools.length} / {catalogueScope === "business" ? businessPools.length : testPools.length} 条
                </span>
              </div>
              <div className="space-y-3 border-b border-crypto-border bg-crypto-bg/35 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex rounded-lg border border-crypto-border bg-crypto-bg p-1">
                    <button
                      type="button"
                      data-testid="pool-scope-business"
                      onClick={() => setCatalogueScope("business")}
                      className={`rounded-md px-3 py-1.5 text-xs font-semibold ${catalogueScope === "business" ? "bg-blue-600 text-white" : "text-slate-500 hover:text-slate-200"}`}
                    >
                      我的股票池 {businessPools.length}
                    </button>
                    <button
                      type="button"
                      data-testid="pool-scope-test"
                      onClick={() => setCatalogueScope("test")}
                      className={`rounded-md px-3 py-1.5 text-xs font-semibold ${catalogueScope === "test" ? "bg-amber-500/20 text-amber-200" : "text-slate-500 hover:text-slate-200"}`}
                    >
                      测试与验收 {testPools.length}
                    </button>
                  </div>
                  <div className="relative min-w-[220px] flex-1">
                    <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-600" />
                    <input
                      value={poolQuery}
                      onChange={(event) => setPoolQuery(event.target.value)}
                      className={`${input} pl-9`}
                      placeholder="搜索股票池名称、说明或类型…"
                      aria-label="搜索股票池"
                    />
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {([
                    ["all", "全部"],
                    ["screener", "条件"],
                    ["factor", "因子"],
                    ["sector", "板块"],
                    ["event", "事件"],
                    ["manual", "手工"],
                  ] as const).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setPoolTypeFilter(value)}
                      className={`rounded-md border px-2.5 py-1 text-[11px] ${poolTypeFilter === value ? "border-blue-500/45 bg-blue-500/10 text-blue-200" : "border-crypto-border text-slate-500 hover:text-slate-300"}`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                {catalogueScope === "test" ? (
                  <div
                    className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] px-3 py-2 text-[11px] leading-5 text-amber-200/80"
                    role="status"
                  >
                    <TestTube2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    这里仅保留自动化验收和种子对象，不参与默认业务目录、策略晋级或 Paper 运行。
                  </div>
                ) : null}
              </div>
              <div className="divide-y divide-white/[0.05]">
                {visiblePools.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedPoolId(item.id)}
                    className={`grid w-full gap-3 px-5 py-4 text-left transition-colors sm:grid-cols-[minmax(0,1fr)_80px_92px_92px_120px] sm:items-center ${selectedPoolId === item.id ? "bg-blue-500/[0.08]" : "hover:bg-white/[0.025]"}`}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-semibold text-slate-100">{item.name}</span>
                        {item.data_purpose !== "user" && item.data_purpose ? (
                          <span className="shrink-0 rounded border border-amber-500/20 bg-amber-500/[0.07] px-1.5 py-0.5 text-[9px] text-amber-300">
                            {item.data_purpose === "acceptance" ? "验收数据" : "种子数据"}
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-1 truncate text-[11px] text-slate-600">
                        {item.description || "未填写说明"}
                      </div>
                    </div>
                    <PoolTypeBadge type={item.pool_type} />
                    <div>
                      <div className="text-[10px] text-slate-600">成员 / 快照</div>
                      <div className="mt-1 font-mono text-xs text-slate-300">
                        {item.current_member_count} / {item.snapshot_count}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-slate-600">交易日</div>
                      <div className="mt-1 font-mono text-xs text-slate-300">
                        {item.latest_trade_date ?? "--"}
                      </div>
                    </div>
                    <div className="sm:text-right">
                      <div className="font-mono text-[10px] text-slate-600">
                        v{item.rule_version} · {item.rule_hash ? "规则已校验" : "规则待校验"}
                      </div>
                      <div className="mt-1 text-[11px] font-semibold text-blue-300">
                        查看证据 →
                      </div>
                    </div>
                  </button>
                ))}
                {!loading && visiblePools.length === 0 ? (
                  <div className="grid min-h-56 place-items-center px-6 py-10 text-center">
                    <div>
                      <Layers3 className="mx-auto h-8 w-8 text-slate-700" />
                      <div className="mt-3 text-sm font-semibold text-slate-300">
                        {catalogueScope === "business"
                          ? "还没有业务股票池"
                          : "当前筛选下没有测试对象"}
                      </div>
                      <p className="mt-2 text-xs text-slate-600">
                        {catalogueScope === "business"
                          ? "从条件、因子、板块或事件研究创建第一条可运行规则。"
                          : "调整类型或搜索条件后再试。"}
                      </p>
                      {catalogueScope === "business" ? (
                        <div className="mt-4 flex flex-wrap justify-center gap-2">
                          {TABS.filter(([key]) =>
                            ["screener", "factor", "sector", "event"].includes(key),
                          ).map(([key, label]) => (
                            <button
                              key={key}
                              type="button"
                              onClick={() => setParams({ tab: key })}
                              className="rounded-md border border-crypto-border bg-crypto-bg px-3 py-2 text-xs text-slate-300 hover:border-blue-500/45 hover:text-blue-200"
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      ) : null}
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
                  className="inline-flex h-10 items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 text-sm font-semibold text-blue-300 disabled:opacity-40"
                >
                  <Filter className="h-4 w-4" />生成最新成员
                </button>
                <button
                  data-testid="seal-pool"
                  onClick={() => void seal()}
                  disabled={Boolean(busy) || !selectedPool || members.length === 0}
                  className="inline-flex h-10 items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 text-sm font-semibold text-emerald-300 disabled:opacity-40"
                >
                  <ShieldCheck className="h-4 w-4" />封存当前批次
                </button>
              </div>
            </section>
          ) : (
          <section className={`${panel} overflow-hidden`}>
            <div className="flex items-center justify-between border-b border-crypto-border px-5 py-4">
              <div>
                <h2 className="font-semibold text-white">股票池定义</h2>
                <p className="mt-1 text-xs text-slate-500">
                  选择规则类型并生成候选成员。
                </p>
              </div>
              <PoolTypeBadge type={creationType} />
            </div>
            <div className="grid gap-4 p-5 md:grid-cols-2">
              <label className="text-xs text-slate-500">
                规则名称
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  className={`${input} mt-1.5`}
                  placeholder="例如：动量 Top20"
                />
              </label>
              <label className="text-xs text-slate-500">
                最大成员数
                <input
                  type="number"
                  value={topN}
                  onChange={(event) => setTopN(Number(event.target.value))}
                  className={`${input} mt-1.5`}
                />
              </label>
              {creationType === "factor" ? (
                <label className="text-xs text-slate-500">
                  因子代码
                  <input
                    value={factorCode}
                    onChange={(event) => setFactorCode(event.target.value)}
                    className={`${input} mt-1.5`}
                  />
                </label>
              ) : null}
              {creationType === "sector" ? (
                <label className="text-xs text-slate-500">
                  板块（逗号分隔）
                  <input
                    value={sector}
                    onChange={(event) => setSector(event.target.value)}
                    className={`${input} mt-1.5`}
                  />
                </label>
              ) : null}
              {creationType === "event" ? (
                <label className="text-xs text-slate-500">
                  事件主题关键字
                  <input
                    value={keyword}
                    onChange={(event) => setKeyword(event.target.value)}
                    className={`${input} mt-1.5`}
                  />
                </label>
              ) : null}
              {creationType === "screener" ? (
                <>
                  <label className="text-xs text-slate-500 md:col-span-2">
                    基础候选证券（留空则扫描历史股票范围）
                    <input
                      value={symbols}
                      onChange={(event) => setSymbols(event.target.value)}
                      className={`${input} mt-1.5`}
                    />
                  </label>
                  <label className="text-xs text-slate-500">
                    最低收盘价
                    <input
                      type="number"
                      value={minPrice}
                      onChange={(event) =>
                        setMinPrice(Number(event.target.value))
                      }
                      className={`${input} mt-1.5`}
                    />
                  </label>
                  <label className="text-xs text-slate-500">
                    最低成交额
                    <input
                      type="number"
                      value={minTurnover}
                      onChange={(event) =>
                        setMinTurnover(Number(event.target.value))
                      }
                      className={`${input} mt-1.5`}
                    />
                  </label>
                </>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-3 border-t border-crypto-border px-5 py-4">
              <button
                data-testid="create-pool"
                onClick={() => void create()}
                disabled={Boolean(busy)}
                className="inline-flex h-10 items-center gap-2 rounded-lg bg-purple-600 px-4 text-sm font-semibold text-white disabled:opacity-50"
              >
                <Plus className="h-4 w-4" />
                创建版本规则
              </button>
              <select
                aria-label="选择股票池"
                value={selectedPoolId}
                onChange={(event) => setSelectedPoolId(event.target.value)}
                className={`${input} max-w-sm`}
              >
                <option value="">选择股票池</option>
                {pools.filter((item) => item.pool_type === creationType).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {poolTypeLabel(item.pool_type)}
                  </option>
                ))}
              </select>
              <button
                data-testid="generate-pool"
                onClick={() => void generate()}
                disabled={Boolean(busy) || !selectedPool || !binding.ready}
                title={!binding.ready ? binding.reason : undefined}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 text-sm font-semibold text-blue-300 disabled:opacity-40"
              >
                <Filter className="h-4 w-4" />
                生成成员
              </button>
              <button
                data-testid="seal-pool"
                onClick={() => void seal()}
                disabled={
                  Boolean(busy) || !selectedPool || members.length === 0
                }
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 text-sm font-semibold text-emerald-300 disabled:opacity-40"
              >
                <ShieldCheck className="h-4 w-4" />
                封存快照
              </button>
            </div>
          </section>
          )}
          <section className={`${panel} p-5`}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold text-white">当前成员证据</h2>
                <p className="mt-1 text-xs text-slate-500">{selectedPool?.name ?? "尚未选择规则"}</p>
              </div>
              <span className={`rounded-md border px-2 py-1 text-[10px] font-semibold ${currentEvidence.bound ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300" : "border-amber-500/25 bg-amber-500/10 text-amber-300"}`}>
                {currentEvidence.bound ? "证据已绑定" : "证据未绑定"}
              </span>
            </div>
            <div className="mt-4 space-y-3 text-xs">
              {[
                [
                  "规则版本",
                  selectedPool ? `v${selectedPool.rule_version}` : "--",
                ],
                [
                  "研究交易日",
                  selectedPool?.latest_trade_date ?? "--",
                ],
                [
                  "数据 / 股票范围",
                  selectedPool?.latest_dataset_snapshot_id && selectedPool.latest_universe_snapshot_id
                    ? "研究数据与股票范围已封存"
                    : "--",
                ],
                [
                  selectedPool?.pool_type === "factor" ? "因子快照" : ["sector", "event"].includes(selectedPool?.pool_type ?? "") ? "市场证据" : "候选来源",
                  selectedPool?.pool_type === "factor"
                    ? selectedPool.latest_factor_snapshot_id ? "因子证据已绑定" : "未绑定"
                    : ["sector", "event"].includes(selectedPool?.pool_type ?? "")
                      ? selectedPool?.latest_market_evidence_snapshot_id ? "市场证据已绑定" : "未绑定"
                      : "规则候选 / 历史股票范围",
                ],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="flex items-center justify-between rounded-lg border border-crypto-border bg-crypto-bg p-3"
                >
                  <span className="text-slate-500">{label}</span>
                  <span className="font-mono text-slate-300">{value}</span>
                </div>
              ))}
            </div>
            {!currentEvidence.bound ? <p className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] p-3 text-[11px] leading-5 text-amber-200/70">{currentEvidence.reason}</p> : null}
            <p className="mt-3 text-[10px] leading-5 text-slate-600">
              下次生成：{binding.ready ? `将使用 ${binding.tradeDate} 的兼容输入` : binding.reason}
            </p>
          </section>
          <section className={`${panel} overflow-hidden xl:col-span-2`}>
            <div className="border-b border-crypto-border px-5 py-4">
              <h2 className="font-semibold text-white">当前成员与入选证据</h2>
              <p className="mt-1 text-xs text-slate-500">
                {membersLoading ? "正在读取成员…" : membersError ? "成员读取失败" : `${members.length} 只；排序、原因、有效期、生成器版本可审计。`}
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1000px] text-sm">
                <thead>
                  <tr className="border-b border-crypto-border text-left text-xs text-slate-500">
                    <th className="px-5 py-3">#</th>
                    <th className="px-4 py-3">证券</th>
                    <th className="px-4 py-3 text-right">分数</th>
                    <th className="px-4 py-3">入选理由</th>
                    <th className="px-4 py-3">有效期</th>
                    <th className="px-5 py-3">证据哈希</th>
                  </tr>
                </thead>
                <tbody>
                  {members.map((item) => (
                    <tr
                      key={item.symbol}
                      className="border-b border-white/[0.04]"
                    >
                      <td className="px-5 py-4 font-mono text-slate-600">
                        {item.ordinal}
                      </td>
                      <td className="px-4 py-4 font-mono font-semibold text-blue-300">
                        {publicSymbol(item.symbol)}
                      </td>
                      <td className="px-4 py-4 text-right font-mono text-slate-300">
                        {item.score?.toFixed(4) ?? "--"}
                      </td>
                      <td className="max-w-lg px-4 py-4 text-xs text-slate-400">
                        {item.reason}
                      </td>
                      <td className="px-4 py-4 text-xs text-slate-500">
                        <div>{item.valid_from} → {item.valid_until ?? "--"}</div>
                        {memberIsExpired(item) ? <span className="mt-1 inline-block rounded border border-amber-500/20 bg-amber-500/[0.07] px-1.5 py-0.5 text-[10px] text-amber-300">当前已过期</span> : null}
                      </td>
                      <td className="px-5 py-4 text-xs text-slate-500">
                        {item.evidence_hash ? "证据已校验" : "证据待校验"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!membersLoading && membersError ? <div className="grid min-h-36 place-items-center px-6 text-center text-xs text-red-300">{membersError}</div> : null}
              {!membersLoading && !membersError && members.length === 0 ? <div className="grid min-h-36 place-items-center px-6 text-center text-xs text-slate-600">所选规则尚无成功生成的成员批次</div> : null}
            </div>
          </section>
        </div>
      ) : null}

      {tab === "snapshots" ? (
        <section className={`${panel} overflow-hidden`}>
          <div className="flex items-center justify-between border-b border-crypto-border px-5 py-4">
            <div>
              <h2 className="font-semibold text-white">股票池快照</h2>
              <p className="mt-1 text-xs text-slate-500">
                选择固定交易日的成员集合创建回测。
              </p>
            </div>
            <Archive className="h-5 w-5 text-emerald-400" />
          </div>
          <div className="overflow-x-auto">
            <table
              data-testid="pool-snapshot-table"
              className="w-full min-w-[950px] text-sm"
            >
              <thead>
                <tr className="border-b border-crypto-border text-left text-xs text-slate-500">
                  <th className="px-5 py-3">快照</th>
                  <th className="px-4 py-3">股票池</th>
                  <th className="px-4 py-3">交易日</th>
                  <th className="px-4 py-3 text-right">成员</th>
                  <th className="px-4 py-3">输入绑定</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody>
                {snapshots.map((snapshot) => (
                  <tr
                    key={snapshot.id}
                    className="border-b border-white/[0.04]"
                  >
                    <td className="px-5 py-4 font-mono text-emerald-300">
                      已封存
                    </td>
                    <td className="px-4 py-4">
                      <div className="font-medium text-slate-200">
                        {snapshot.pool_name}
                      </div>
                      <PoolTypeBadge type={snapshot.pool_type} />
                    </td>
                    <td className="px-4 py-4 text-slate-400">
                      {snapshot.trade_date}
                    </td>
                    <td className="px-4 py-4 text-right font-mono text-slate-200">
                      {snapshot.member_count}
                    </td>
                    <td className="px-4 py-4 text-xs text-slate-500">
                      研究数据与股票范围已绑定
                      <br />
                      {snapshot.factor_snapshot_id
                        ? "因子证据已绑定"
                        : snapshot.market_evidence_snapshot_id
                          ? "市场证据已绑定"
                          : "附加证据未绑定"}
                    </td>
                    <td className="px-5 py-4 text-right">
                      <button
                        data-testid={`pool-backtest-${snapshot.id}`}
                        onClick={() => void toBacktest(snapshot)}
                        disabled={Boolean(busy)}
                        className="inline-flex h-9 items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 text-xs font-semibold text-blue-300 disabled:opacity-40"
                      >
                        <Play className="h-3.5 w-3.5" />
                        创建回测草稿
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!loading && snapshots.length === 0 ? <div className="grid min-h-44 place-items-center px-6 text-center text-xs text-slate-600">暂无已封存股票池快照</div> : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}

export default StockPools;
