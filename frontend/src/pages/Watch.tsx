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
import { acknowledgeRuntimeAlert, getWatchContext } from "../api/client";
import type { RuntimeAlert, WatchContext } from "../types";
import { orderTypeLabel, sideLabel, sourceLabel, statusLabel } from "../utils/presentation";

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
  const [dataScope, setDataScope] = useState<"business" | "test">("business");
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
  const inScope = (row: Record<string, unknown>) =>
    dataScope === "business"
      ? !row.data_purpose || row.data_purpose === "user"
      : Boolean(row.data_purpose && row.data_purpose !== "user");
  const scoped = {
    alerts: (context?.alerts ?? []).filter((row) =>
      inScope(row as unknown as Record<string, unknown>),
    ),
    signals: (context?.signals ?? []).filter(inScope),
    orders: (context?.orders ?? []).filter(inScope),
    trades: (context?.trades ?? []).filter(inScope),
    positions: (context?.positions ?? []).filter(inScope),
    risk_events: (context?.risk_events ?? []).filter(inScope),
    runtime_events: (context?.runtime_events ?? []).filter(inScope),
    pool_moves: (context?.pool_moves ?? []).filter(inScope),
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
    >
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <Eye className="h-7 w-7 text-violet-400" />
            <h1 className="text-2xl font-black text-white">盯盘</h1>
          </div>
          <p className="mt-2 text-sm text-slate-500">
            集中查看策略信号、订单成交、股票池变化和待确认风险。
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-400"
        >
          <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
          刷新
        </button>
      </header>
      <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-crypto-border bg-crypto-card px-4 py-3 text-xs text-slate-500">
        <span>
          数据{" "}
          <strong className="font-medium text-slate-300">
            模拟交易 / 告警 / 股票池
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
                  : context
                    ? context.data_status === "fresh"
                      ? "text-emerald-300"
                      : "text-amber-300"
                    : "text-amber-300"
            }
          >
            {error
              ? "加载失败"
              : busy
                ? "读取中"
                : context
                  ? context.data_status === "stale"
                    ? "记录已陈旧"
                    : context.data_status === "empty"
                      ? "无审计记录"
                      : "已读取"
                  : "未加载"}
          </strong>
        </span>
        <span>
          最新观察{" "}
          <strong className="tabular-nums text-slate-300">
            {context?.source_updated_at ??
              (latestObservedAt === "--" ? "--" : latestObservedAt)}
          </strong>
        </span>
        <span>
          来源 <strong className="font-medium text-slate-300">{sourceLabel(context?.source_label)}</strong>
        </span>
      </div>
      <nav className="mb-5 flex overflow-x-auto rounded-xl border border-crypto-border bg-crypto-card p-1">
        {TABS.map(([key, label]) => (
          <button
            data-testid={`watch-tab-${key}`}
            type="button"
            key={key}
            onClick={() => setParams({ tab: key })}
            className={`min-w-max flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold ${tab === key ? "bg-violet-600 text-white" : "text-slate-500 hover:bg-slate-800/60 hover:text-white"}`}
          >
            {label}
          </button>
        ))}
      </nav>
      <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-crypto-border bg-crypto-card px-4 py-3 text-xs text-slate-500">
        <div className="flex rounded-md border border-crypto-border bg-crypto-bg p-1">
          <button
            type="button"
            data-testid="watch-scope-business"
            onClick={() => setDataScope("business")}
            className={`rounded px-2.5 py-1 font-semibold ${dataScope === "business" ? "bg-violet-600 text-white" : "text-slate-500"}`}
          >
            业务观察
          </button>
          <button
            type="button"
            data-testid="watch-scope-test"
            onClick={() => setDataScope("test")}
            className={`rounded px-2.5 py-1 font-semibold ${dataScope === "test" ? "bg-amber-500/15 text-amber-200" : "text-slate-500"}`}
          >
            测试与验收
          </button>
        </div>
        <span>{dataScope === "business" ? "默认不混入测试运行证据" : "当前仅查看测试运行证据"}</span>
      </div>
      {error ? (
        <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">
          {error}
        </div>
      ) : null}
      {tab === "signals" ? (
        <section className={`${panel} overflow-hidden`}>
          <div className="border-b border-crypto-border px-5 py-4">
            <h2 className="font-semibold text-white">最新策略信号</h2>
            <p className="mt-1 text-xs text-slate-500">
              每个信号回链固定 Paper 实例，不提供绕过风险规则的下单入口。
            </p>
          </div>
          <div className="divide-y divide-white/[0.04]">
            {scoped.signals.map((row, index) => (
              <div
                key={text(row.id ?? index)}
                className="grid gap-3 px-5 py-4 sm:grid-cols-[150px_100px_1fr_180px]"
              >
                <span className="font-mono text-xs text-slate-500">
                  {text(row.signal_time)}
                </span>
                <span className="font-semibold text-slate-200">
                  {text(row.symbol)}
                </span>
                <div>
                  <span className="text-sm text-slate-300">
                    {text(row.signal_type)} · {text(row.reason)}
                  </span>
                  <div className="mt-1 text-[10px] text-slate-500">策略信号已写入运行证据</div>
                </div>
                <Link
                  to={`/paper?tab=signals&instance=${text(row.paper_instance_id)}`}
                  className="text-xs text-blue-300 hover:text-blue-200"
                >
                  {instanceById.get(text(row.paper_instance_id))?.name ??
                    text(row.paper_instance_id)}
                </Link>
              </div>
            ))}
            {!scoped.signals.length ? (
              <div className="p-12 text-center text-sm text-slate-600">
                {emptyState("当前没有策略信号")}
              </div>
            ) : null}
          </div>
        </section>
      ) : null}
      {tab === "execution" ? (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              ["订单", scoped.orders.length],
              ["成交", scoped.trades.length],
              ["持仓", scoped.positions.length],
              ["风险决策", scoped.risk_events.length],
            ].map(([label, value]) => (
              <div key={String(label)} className={`${panel} p-4`}>
                <div className="text-xs text-slate-500">{String(label)}</div>
                <div className="mt-2 text-2xl font-black text-white">
                  {value === undefined ? "--" : String(value)}
                </div>
              </div>
            ))}
          </div>
          <section className={`${panel} overflow-hidden`}>
            <div className="border-b border-crypto-border px-5 py-4">
              <div className="flex items-center gap-2">
                <ClipboardList className="h-5 w-5 text-blue-400" />
                <h2 className="font-semibold text-white">模拟订单</h2>
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
                      <td className="px-4 py-3 font-mono text-xs text-slate-500">{text(row.created_at)}</td>
                      <td className="px-4 py-3 font-semibold">{text(row.symbol)}</td>
                      <td className="px-4 py-3">{sideLabel(row.side)}</td>
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
              <h2 className="font-semibold text-white">模拟成交</h2>
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
                      <td className="px-4 py-3 font-mono text-xs text-slate-500">{text(row.traded_at)}</td>
                      <td className="px-4 py-3 font-semibold">{text(row.symbol)}</td>
                      <td className="px-4 py-3">{sideLabel(row.side)}</td>
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
              <h2 className="font-semibold text-white">当前持仓证据</h2>
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
                      <td className="px-4 py-3 font-mono text-xs text-slate-500">{text(row.updated_at)}</td>
                      <td className="px-4 py-3 font-semibold">{text(row.symbol)}</td>
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
                <h2 className="font-semibold text-white">风险决策</h2>
              </div>
            </div>
            <div className="divide-y divide-white/[0.04]">
              {scoped.risk_events.map((row) => (
                <div key={text(row.id)} className="grid gap-2 px-5 py-4 md:grid-cols-[160px_180px_100px_1fr_180px]">
                  <span className="font-mono text-xs text-slate-500">{text(row.created_at)}</span>
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
              <h2 className="font-semibold text-white">对象联动</h2>
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
            <h2 className="font-semibold text-white">联动边界</h2>
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
                      触发时间 {text(alert.triggered_at)}
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
