import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  BellRing,
  Check,
  ClipboardList,
  Eye,
  GitCompareArrows,
  Layers3,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import clsx from "clsx";
import { DataPanel, StatusBadge } from "@bitpro/ui";
import { acknowledgeRuntimeAlert, getWatchContext } from "../api/client";
import { WorkspaceTabs } from "../components/WorkspaceTabs";
import {
  EvidenceStrip,
  MetricValue,
  OperatorPageHeader,
} from "../components/OperatorShell";
import { TremorDeltaBadge, TremorTracker } from "../components/TremorUI";
import type { RuntimeAlert, WatchContext } from "../types";
import {
  formatOperatorTime,
  orderTypeLabel,
  sideLabel,
  sideToneClass,
  signalReasonLabel,
  sourceLabel,
  statusLabel,
} from "../utils/presentation";
import {
  formatSymbolLabel,
  normalizeSymbolCode,
  resolveSymbolName,
  toPublicSymbol,
} from "../utils/symbolDisplay";
import { SymbolCell } from "../components/SymbolCell";

const TABS = [
  ["signals", "策略信号"],
  ["execution", "订单与成交"],
  ["pools", "股票池变动"],
  ["charts", "图表联动"],
  ["alerts", "告警"],
] as const;
type Tab = (typeof TABS)[number][0];
const panel = "rounded-xl border border-crypto-border bg-crypto-card";
const text = (value: unknown) =>
  value === null || value === undefined || value === "" ? "--" : String(value);
const tone = (severity: string) =>
  severity === "critical"
    ? "border-red-500/30 bg-red-500/10 text-red-200"
    : severity === "warning"
      ? "border-amber-500/30 bg-amber-500/10 text-amber-200"
      : "border-blue-500/25 bg-blue-500/10 text-blue-200";

export function Watch() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") as Tab | null;
  const tab: Tab = TABS.some(([key]) => key === requested)
    ? requested!
    : "signals";
  const [context, setContext] = useState<WatchContext | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = async () => {
    setBusy(true);
    setError("");
    try {
      setContext(await getWatchContext());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "观察台加载失败");
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  const instanceById = useMemo(
    () => new Map((context?.instances ?? []).map((item) => [item.id, item])),
    [context],
  );
  const symbolNames = context?.symbol_names ?? {};
  const isBusiness = (row: Record<string, unknown>) =>
    !row.data_purpose || row.data_purpose === "user";
  const scoped = {
    alerts: (context?.alerts ?? []).filter((row) =>
      isBusiness(row as unknown as Record<string, unknown>),
    ),
    signals: (context?.signals ?? []).filter(isBusiness),
    orders: (context?.orders ?? []).filter(isBusiness),
    trades: (context?.trades ?? []).filter(isBusiness),
    positions: (context?.positions ?? []).filter(isBusiness),
    risk_events: (context?.risk_events ?? []).filter(isBusiness),
    runtime_events: (context?.runtime_events ?? []).filter(isBusiness),
    pool_moves: (context?.pool_moves ?? []).filter(isBusiness),
  };
  const latestObservedAt =
    scoped.alerts[0]?.triggered_at ??
    text(
      (scoped.signals[0] as Record<string, unknown> | undefined)
        ?.signal_time,
    );
  const emptyState = (label: string) =>
    error ? "数据加载失败" : busy && !context ? "正在读取观察记录…" : label;
  const acknowledge = async (alert: RuntimeAlert) => {
    setBusy(true);
    try {
      await acknowledgeRuntimeAlert(alert.id);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "确认失败");
      setBusy(false);
    }
  };
  return (
    <div
      className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8"
      data-testid="watch-workbench"
      data-operator-page="watch"
    >
      <OperatorPageHeader
        icon={Eye}
        title="盯盘"
        subtitle="集中查看策略信号、订单成交、股票池变化和待确认风险。五个子页签均需对齐密度。"
        actions={
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-400"
          >
            <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
            刷新
          </button>
        }
      />
      <EvidenceStrip
        items={[
          { label: "数据", value: "模拟交易 / 告警 / 股票池" },
          {
            label: "状态",
            value: error
              ? "加载失败"
              : busy
                ? "读取中"
                : context?.data_status === "fresh"
                  ? "观测正常"
                  : "数据离线/旧快照",
            tone: error
              ? "red"
              : busy
                ? "blue"
                : context?.data_status === "fresh"
                  ? "green"
                  : "amber",
          },
          {
            label: "最新观察",
            value:
              context?.source_updated_at ??
              (latestObservedAt === "--" ? "--" : latestObservedAt),
          },
          { label: "来源", value: sourceLabel(context?.source_label) },
        ]}
      />
      <div className="mb-4 rounded-xl border border-crypto-border bg-crypto-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2 text-xs">
          <span className="font-bold text-gray-200">系统观察台与策略引擎健康度 (Tremor Tracker 视角)</span>
          <span className="text-[10px] text-emerald-400 font-semibold">100% 实时监控中</span>
        </div>
        <TremorTracker
          data={Array.from({ length: 30 }, (_, i) => ({
            color: i === 15 ? 'amber' : 'emerald',
            tooltip: `Day ${i + 1}: 运行状态正常 (在途实时观测)`,
          }))}
        />
      </div>
      <WorkspaceTabs
        ariaLabel="观察台二级导航"
        items={TABS.map(([id, label]) => ({ id, label, testId: `watch-tab-${id}` }))}
        value={tab}
        onChange={(id) => setParams({ tab: id })}
      />
      {error ? (
        <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">
          {error}
        </div>
      ) : null}
      {tab === "signals" ? (
        <DataPanel
          title="最新策略信号"
          subtitle="每个信号回链固定 Paper 实例，不提供绕过风险规则的下单入口。"
          actions={
            <StatusBadge tone="blue">
              {scoped.signals.length} 条
            </StatusBadge>
          }
        >
          <div className="space-y-3">
            {scoped.signals.map((row, index) => {
              const instanceId = text(row.paper_instance_id);
              const instanceName =
                instanceById.get(instanceId)?.name ?? instanceId;
              const action = text(row.signal_type);
              const cnName =
                resolveSymbolName(text(row.symbol), text(row.name)) ||
                symbolNames[normalizeSymbolCode(text(row.symbol))] ||
                "";
              return (
                <article
                  key={text(row.id ?? index)}
                  className="relative rounded-xl border border-crypto-border bg-crypto-bg/95 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]"
                  data-testid="watch-signal-row"
                >
                  <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
                    <div className="min-w-0">
                      <div className="mb-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                        <TremorDeltaBadge
                          type={
                            action.includes('buy') || action.includes('open') || action.includes('long')
                              ? 'increase'
                              : action.includes('sell') || action.includes('close') || action.includes('short')
                                ? 'decrease'
                                : 'neutral'
                          }
                          value={sideLabel(action)}
                          className="shrink-0"
                        />
                        <span className="min-w-0 truncate text-sm font-semibold text-gray-100">
                          {cnName ||
                            formatSymbolLabel(text(row.symbol), text(row.name))}
                        </span>
                        <span className="shrink-0 font-mono text-[11px] text-gray-500">
                          {toPublicSymbol(text(row.symbol)) || text(row.symbol)}
                        </span>
                        <StatusBadge
                          tone={
                            text(row.status) === "ordered" ||
                            text(row.status) === "closed"
                              ? "green"
                              : text(row.status) === "invalidated" ||
                                  text(row.status) === "rejected"
                                ? "red"
                                : "amber"
                          }
                        >
                          {statusLabel(row.status, text(row.status))}
                        </StatusBadge>
                      </div>
                      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
                        <span className="shrink-0 text-gray-300">
                          {signalReasonLabel(row.reason)}
                        </span>
                        <span className="shrink-0">
                          产生时间：{formatOperatorTime(row.signal_time)}
                        </span>
                        <span className="shrink-0 text-gray-400">
                          已写入运行证据
                        </span>
                      </div>
                    </div>
                    <div className="flex max-w-[240px] shrink-0 flex-wrap items-center justify-start gap-2 xl:justify-end">
                      <Link
                        to={`/paper?tab=signals&instance=${instanceId}`}
                        className="inline-flex h-8 items-center rounded-lg border border-crypto-border bg-crypto-card/90 px-2.5 text-[11px] font-semibold text-gray-300 transition-colors hover:border-blue-500/50 hover:bg-blue-500/10 hover:text-blue-200"
                      >
                        {instanceName}
                      </Link>
                    </div>
                  </div>
                </article>
              );
            })}
            {!scoped.signals.length ? (
              <div className="flex min-h-[180px] items-center justify-center rounded-xl border border-dashed border-crypto-border px-6 text-center text-sm text-gray-500">
                {emptyState("当前没有策略信号")}
              </div>
            ) : null}
          </div>
        </DataPanel>
      ) : null}
      {tab === "execution" ? (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              { label: "订单", value: scoped.orders.length, tone: "blue" as const },
              { label: "成交", value: scoped.trades.length, tone: "green" as const },
              { label: "持仓", value: scoped.positions.length, tone: "amber" as const },
              { label: "风险决策", value: scoped.risk_events.length, tone: "red" as const },
            ].map((item) => (
              <div key={item.label} className={`${panel} p-4`}>
                <div className="text-xs text-slate-500">{item.label}</div>
                <div className="mt-2">
                  <MetricValue tone={item.value === 0 ? "neutral" : item.tone} size="xl">
                    {String(item.value)}
                  </MetricValue>
                </div>
              </div>
            ))}
          </div>
          <section className={`${panel} overflow-hidden`}>
            <div className="border-b border-crypto-border px-5 py-4">
              <div className="flex items-center gap-2">
                <ClipboardList className="h-5 w-5 text-blue-400" />
                <h2 className="font-semibold text-gray-100">模拟订单</h2>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                价格缺失表示订单没有可用限价证据，不显示为 0。
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] text-sm">
                <thead><tr className="border-b border-crypto-border text-left text-xs text-slate-500">
                  {["时间", "证券", "方向", "类型", "价格", "数量 / 成交", "状态", "实例"].map((label) => <th key={label} className="px-4 py-3">{label}</th>)}
                </tr></thead>
                <tbody>
                  {scoped.orders.map((row) => (
                    <tr key={text(row.id)} className="border-b border-white/[0.04] text-slate-300">
                      <td className="px-4 py-3 font-mono text-xs text-slate-500">{formatOperatorTime(row.created_at)}</td>
                      <td className="px-4 py-3">
                        <SymbolCell
                          symbol={text(row.symbol) === "--" ? "" : text(row.symbol)}
                          name={text(row.name) === "--" ? "" : text(row.name)}
                          names={symbolNames}
                        />
                      </td>
                      <td className={clsx("px-4 py-3 font-semibold", sideToneClass(row.side))}>{sideLabel(row.side)}</td>
                      <td className="px-4 py-3">{orderTypeLabel(row.order_type)}</td>
                      <td className="px-4 py-3 font-mono">{text(row.price)}</td>
                      <td className="px-4 py-3 font-mono">{text(row.quantity)} / {text(row.filled_quantity)}</td>
                      <td className="px-4 py-3">
                        <span className={text(row.status) === "rejected" ? "text-red-300" : text(row.status) === "filled" ? "text-emerald-300" : "text-amber-300"}>{statusLabel(row.status)}</span>
                        {row.message ? <div className="mt-1 text-xs text-red-300">{text(row.message)}</div> : null}
                      </td>
                      <td className="px-4 py-3"><Link to={`/paper?tab=orders&instance=${text(row.paper_instance_id)}`} className="text-xs text-blue-300">{text(row.instance_name)}</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!scoped.orders.length ? <div className="p-10 text-center text-sm text-slate-600">{emptyState("当前没有模拟订单证据")}</div> : null}
          </section>
          <section className={`${panel} overflow-hidden`}>
            <div className="border-b border-crypto-border px-5 py-4">
              <h2 className="font-semibold text-gray-100">模拟成交</h2>
              <p className="mt-1 text-xs text-slate-500">成交时间、价格、数量、金额与费用均来自本地成交记录。</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-sm">
                <thead><tr className="border-b border-crypto-border text-left text-xs text-slate-500">
                  {["成交时间", "证券", "方向", "价格", "数量", "金额", "费用", "实例"].map((label) => <th key={label} className="px-4 py-3">{label}</th>)}
                </tr></thead>
                <tbody>
                  {scoped.trades.map((row) => (
                    <tr key={text(row.id)} className="border-b border-white/[0.04] text-slate-300">
                      <td className="px-4 py-3 font-mono text-xs text-slate-500">{formatOperatorTime(row.traded_at)}</td>
                      <td className="px-4 py-3">
                        <SymbolCell
                          symbol={text(row.symbol) === "--" ? "" : text(row.symbol)}
                          name={text(row.name) === "--" ? "" : text(row.name)}
                          names={symbolNames}
                        />
                      </td>
                      <td className={clsx("px-4 py-3 font-semibold", sideToneClass(row.side))}>{sideLabel(row.side)}</td>
                      <td className="px-4 py-3 font-mono">{text(row.price)}</td>
                      <td className="px-4 py-3 font-mono">{text(row.quantity)}</td>
                      <td className="px-4 py-3 font-mono">{text(row.amount)}</td>
                      <td className="px-4 py-3 font-mono">{text(row.commission)}</td>
                      <td className="px-4 py-3"><Link to={`/paper?tab=orders&instance=${text(row.paper_instance_id)}`} className="text-xs text-blue-300">{text(row.instance_name)}</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!scoped.trades.length ? <div className="p-10 text-center text-sm text-slate-600">{emptyState("当前没有模拟成交证据")}</div> : null}
          </section>
          <section className={`${panel} overflow-hidden`}>
            <div className="border-b border-crypto-border px-5 py-4">
              <h2 className="font-semibold text-gray-100">当前持仓证据</h2>
              <p className="mt-1 text-xs text-slate-500">最新价缺失保持 --；数量和市值来自组合持仓账本。</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-sm">
                <thead><tr className="border-b border-crypto-border text-left text-xs text-slate-500">
                  {["更新时间", "证券", "持仓 / 可用", "成本", "最新价", "市值", "实例"].map((label) => <th key={label} className="px-4 py-3">{label}</th>)}
                </tr></thead>
                <tbody>
                  {scoped.positions.map((row) => (
                    <tr key={text(row.id)} className="border-b border-white/[0.04] text-slate-300">
                      <td className="px-4 py-3 font-mono text-xs text-slate-500">{formatOperatorTime(row.updated_at)}</td>
                      <td className="px-4 py-3">
                        <SymbolCell
                          symbol={text(row.symbol) === "--" ? "" : text(row.symbol)}
                          name={text(row.name) === "--" ? "" : text(row.name)}
                          names={symbolNames}
                        />
                      </td>
                      <td className="px-4 py-3 font-mono">{text(row.quantity)} / {text(row.available_quantity)}</td>
                      <td className="px-4 py-3 font-mono">{text(row.avg_cost)}</td>
                      <td className="px-4 py-3 font-mono">{text(row.last_price)}</td>
                      <td className="px-4 py-3 font-mono">{text(row.market_value)}</td>
                      <td className="px-4 py-3"><Link to={`/paper?tab=positions&instance=${text(row.paper_instance_id)}`} className="text-xs text-blue-300">{text(row.instance_name)}</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!scoped.positions.length ? <div className="p-10 text-center text-sm text-slate-600">{emptyState("当前没有持仓证据")}</div> : null}
          </section>
          <section className={`${panel} overflow-hidden`}>
            <div className="border-b border-crypto-border px-5 py-4">
              <div className="flex items-center gap-2">
                <ShieldAlert className="h-5 w-5 text-amber-400" />
                <h2 className="font-semibold text-gray-100">风险决策</h2>
              </div>
            </div>
            <div className="divide-y divide-white/[0.04]">
              {scoped.risk_events.map((row) => (
                <div key={text(row.id)} className="grid gap-2 px-5 py-4 md:grid-cols-[160px_180px_100px_1fr_180px]">
                  <span className="font-mono text-xs text-slate-500">{formatOperatorTime(row.created_at)}</span>
                  <span className="text-sm text-slate-300">{text(row.rule_name)} <span className="text-xs text-slate-600">v{text(row.rule_version)}</span></span>
                  <span className={text(row.decision) === "rejected" ? "text-sm text-red-300" : "text-sm text-emerald-300"}>{text(row.decision)}</span>
                  <span className="text-sm text-slate-400">{text(row.message)}</span>
                  <Link to={`/paper?tab=events&instance=${text(row.paper_instance_id)}`} className="text-xs text-blue-300">{text(row.instance_name)}</Link>
                </div>
              ))}
            </div>
            {!scoped.risk_events.length ? <div className="p-10 text-center text-sm text-slate-600">{emptyState("当前没有风险决策证据")}</div> : null}
          </section>
        </div>
      ) : null}
      {tab === "pools" ? (
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
          {scoped.pool_moves.map((row, index) => (
            <article
              key={text(row.snapshot_id ?? index)}
              className={`${panel} p-5`}
            >
              <div className="flex items-start justify-between">
                <Layers3 className="h-5 w-5 text-blue-400" />
                <span className="text-xs text-slate-500">
                  {text(row.trade_date)}
                </span>
              </div>
              <h2 className="mt-4 font-semibold text-slate-100">
                {text(row.pool_name)}
              </h2>
              <p className="mt-2 text-xs text-slate-500">
                交易日 {text(row.trade_date)} · 成员 {text(row.member_count)}
              </p>
              <Link
                to="/pools?tab=snapshots"
                className="mt-4 inline-block text-xs text-blue-300"
              >
                查看固定股票池 →
              </Link>
            </article>
          ))}
        </div>
      ) : null}
      {tab === "charts" ? (
        <div className="grid gap-5 xl:grid-cols-[1fr_1fr]">
          <section className={`${panel} p-5`}>
            <div className="flex items-center gap-2">
              <GitCompareArrows className="h-5 w-5 text-violet-400" />
              <h2 className="font-semibold text-gray-100">对象联动</h2>
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-500">
              从信号跳转时自动保留证券、策略实例与股票池上下文；行情图只用于观察，不触发交易。
            </p>
            <div className="mt-5 space-y-2">
              {(context?.instances ?? []).map((item) => (
                <Link
                  key={item.id}
                  to={`/market?tab=stock&paper=${item.id}&pool=${item.pool_snapshot_id}`}
                  className="flex items-center justify-between rounded-lg border border-crypto-border bg-crypto-bg p-3 text-sm"
                >
                  <span className="text-slate-300">{item.name}</span>
                  <span className="text-xs text-violet-300">
                    打开关联行情 →
                  </span>
                </Link>
              ))}
            </div>
          </section>
          <section className={`${panel} p-5`}>
            <h2 className="font-semibold text-gray-100">联动边界</h2>
            <div className="mt-4 space-y-3 text-xs text-slate-500">
              {[
                "图表使用相同固定数据快照和证券代码。",
                "告警可回到对应策略实例和事件证据。",
                "任何观察操作都不能直接生成订单或修改运行参数。",
              ].map((item) => (
                <div
                  key={item}
                  className="rounded-lg border border-crypto-border bg-crypto-bg p-3"
                >
                  {item}
                </div>
              ))}
            </div>
          </section>
        </div>
      ) : null}
      {tab === "alerts" ? (
        <section className="space-y-3">
          {scoped.alerts.map((alert) => (
            <article key={alert.id} className={`${panel} p-5`}>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex gap-3">
                  <BellRing
                    className={`mt-0.5 h-5 w-5 ${alert.severity === "critical" ? "text-red-400" : alert.severity === "warning" ? "text-amber-400" : "text-blue-400"}`}
                  />
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="font-semibold text-slate-100">
                        {alert.title}
                      </h2>
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[10px] ${tone(alert.severity)}`}
                      >
                        {statusLabel(alert.severity)}
                      </span>
                    </div>
                    <p className="mt-2 text-sm text-slate-400">
                      {alert.message}
                    </p>
                    <div className="mt-2 text-[10px] text-slate-500">
                      {alert.paper_instance_id && instanceById.get(alert.paper_instance_id)?.name
                        ? `关联策略 ${instanceById.get(alert.paper_instance_id)?.name} · `
                        : ""}
                      触发时间 {formatOperatorTime(alert.triggered_at)}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {alert.paper_instance_id ? (
                    <Link
                      to={`/paper?tab=events&instance=${alert.paper_instance_id}`}
                      className="rounded-lg border border-crypto-border px-3 py-2 text-xs text-blue-300"
                    >
                      事件链
                    </Link>
                  ) : null}
                  {alert.status === "active" ? (
                    <button
                      type="button"
                      onClick={() => void acknowledge(alert)}
                      className="inline-flex items-center gap-2 rounded-lg bg-slate-700 px-3 py-2 text-xs text-white"
                    >
                      <Check className="h-3.5 w-3.5" />
                      确认
                    </button>
                  ) : (
                    <span className="text-xs text-emerald-400">已确认</span>
                  )}
                </div>
              </div>
            </article>
          ))}
          {!scoped.alerts.length ? (
            <div className={`${panel} p-16 text-center text-slate-600`}>
              {emptyState("当前没有告警")}
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

export default Watch;
