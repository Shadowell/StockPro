import { useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import clsx from "clsx";
import {
  DataPanel,
  LogStream,
  MetricCard,
  StatusBadge,
  type LogStreamItem,
} from "@bitpro/ui";
import {
  Activity,
  ArrowLeft,
  BarChart3,
  BookOpen,
  CandlestickChart,
  ChevronDown,
  CircleDollarSign,
  Clock3,
  Database,
  FlaskConical,
  Gauge,
  ListTree,
  Pause,
  Play,
  RefreshCw,
  ShieldCheck,
  Square,
  Terminal,
  TrendingDown,
  TrendingUp,
  WalletCards,
} from "lucide-react";
import { getPaperInstanceKlines } from "../api/client";
import type {
  BacktestRun,
  PaperKlineSnapshot,
  PaperRuntimeInstance,
} from "../types";
import { SymbolCell } from "./SymbolCell";
import { useSymbolNames } from "../hooks/useSymbolNames";
import { formatSymbolLabel } from "../utils/symbolDisplay";
import { marketAdverseToneClass, marketToneClass, type MetricTone } from "../utils/marketColors";
import { MetricValue } from "./OperatorShell";
import { COLOR_SCHEMES, useSettingsStore } from "../stores/useSettingsStore";

type Row = Record<string, unknown>;
type Action = "start" | "pause" | "resume" | "stop";

const asNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const text = (value: unknown, fallback = "未提供") =>
  value === null || value === undefined || value === "" ? fallback : String(value);
const number = (value: unknown, digits = 2) => {
  const parsed = asNumber(value);
  return parsed === null
    ? "--"
    : parsed.toLocaleString("zh-CN", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
};
const money = (value: unknown) => {
  const parsed = asNumber(value);
  if (parsed === null) return "--";
  return `${parsed > 0 ? "+" : parsed < 0 ? "-" : ""}¥${Math.abs(parsed).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
};
const pct = (value: number | null, digits = 2) =>
  value === null ? "--" : `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
const dateTime = (value: unknown) =>
  value
    ? new Date(String(value)).toLocaleString("zh-CN", { hour12: false })
    : "--";
const statusLabel: Record<string, string> = {
  draft: "草稿",
  starting: "启动中",
  running: "运行中",
  paused: "已暂停",
  stopping: "停止中",
  stopped: "已停止",
  failed: "故障",
  success: "成功",
  blocked: "已阻断",
  critical: "严重",
  error: "错误",
  info: "提示",
  warning: "警告",
  lifecycle: "生命周期",
  runtime: "运行",
  paper_eligible: "已通过模拟盘准入",
  rejected: "未通过准入",
};
const parameterLabel: Record<string, string> = {
  stop_loss: "止损比例",
  long_window: "长期均线",
  initial_cash: "初始资金",
  short_window: "短期均线",
  target_weight: "目标仓位",
  profit_trigger: "止盈触发",
  trailing_drawdown: "浮盈回撤",
};
const percentParameterKeys = new Set([
  "stop_loss",
  "target_weight",
  "profit_trigger",
  "trailing_drawdown",
]);
const ratioText = (value: unknown) => {
  const parsed = asNumber(value);
  return parsed === null ? "--" : `${(parsed * 100).toFixed(1)}%`;
};
const parameterText = (key: string, value: unknown) => {
  if (percentParameterKeys.has(key)) return ratioText(value);
  if (key === "initial_cash") {
    const parsed = asNumber(value);
    return parsed === null ? "--" : `¥${parsed.toLocaleString("zh-CN")}`;
  }
  if (key === "long_window" || key === "short_window") return `${text(value)} 日`;
  return text(value);
};

function Section({
  title,
  subtitle,
  icon,
  children,
  action,
  defaultOpen = true,
}: {
  title: string;
  subtitle?: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  action?: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <DataPanel
      className="shadow-lg shadow-black/20"
      title={<span className="inline-flex items-start gap-2">{icon}<span>{title}</span></span>}
      subtitle={subtitle}
      actions={(
        <>
          {action}
          <button
            type="button"
            aria-label={`${open ? "收起" : "展开"}${title}`}
            aria-expanded={open}
            onClick={() => setOpen((current) => !current)}
            className="rounded-md p-1.5 text-slate-500 transition-colors hover:bg-white/[0.04] hover:text-slate-200"
          >
            <ChevronDown className={clsx("h-4 w-4 transition-transform", open && "rotate-180")} />
          </button>
        </>
      )}
    >
      {open ? <div className="p-5">{children}</div> : null}
    </DataPanel>
  );
}

function Metric({
  label,
  value,
  note,
  tone = "text-blue-300",
  icon,
}: {
  label: string;
  value: string;
  note: string;
  tone?: string;
  icon: React.ReactNode;
}) {
  const color: MetricTone = tone.includes("down") || tone.includes("red")
    ? "down"
    : tone.includes("up") || tone.includes("emerald")
      ? "up"
      : tone.includes("amber") || tone.includes("yellow")
        ? "amber"
        : "blue";
  return (
    <MetricCard
      label={label}
      value={<MetricValue tone={color}>{value}</MetricValue>}
      detail={note}
      icon={icon}
      color={color}
      className="min-h-[104px]"
    />
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-crypto-border bg-crypto-bg/45 px-4 py-10 text-center text-xs leading-5 text-slate-500">
      {children}
    </div>
  );
}

function ParameterGrid({
  title,
  values,
}: {
  title: string;
  values: Array<[string, unknown]>;
}) {
  return (
    <div>
      <h3 className="mb-3 text-xs font-semibold text-slate-300">{title}</h3>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {values.map(([label, value]) => (
          <div
            key={label}
            className="rounded-lg border border-crypto-border bg-crypto-bg/60 px-3 py-2.5"
          >
            <div className="text-[10px] text-slate-600">{label}</div>
            <div className="mt-1 break-all text-xs font-semibold text-slate-300">
              {text(value)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const rowSymbol = (row: Row) => text(row.symbol, "").toUpperCase();
const symbolsFrom = (instance: PaperRuntimeInstance) =>
  [
    ...(instance.positions ?? []),
    ...(instance.trades ?? []),
    ...(instance.orders ?? []),
    ...(instance.signals ?? []),
  ]
    .map(rowSymbol)
    .filter((value, index, items) => Boolean(value) && items.indexOf(value) === index);

const runtimeDuration = (instance: PaperRuntimeInstance) => {
  const start = Date.parse(instance.started_at ?? instance.created_at ?? "");
  const end = Date.parse(
    instance.status === "stopped"
      ? instance.stopped_at ?? instance.updated_at ?? ""
      : instance.heartbeat_at ?? instance.updated_at ?? "",
  );
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "--";
  const minutes = Math.max(0, Math.floor((end - start) / 60000));
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours} 小时 ${minutes % 60} 分` : `${Math.floor(hours / 24)} 天 ${hours % 24} 小时`;
};

export function PaperRuntimeInstanceDetail({
  instance,
  qualifyingRun,
  busy,
  onBack,
  onRefresh,
  onAction,
  onRunCycle,
}: {
  instance: PaperRuntimeInstance;
  qualifyingRun?: BacktestRun | null;
  busy: boolean;
  onBack: () => void;
  onRefresh: () => void | Promise<void>;
  onAction: (action: Action) => void | Promise<void>;
  onRunCycle: (tradeDate: string) => void | Promise<void>;
}) {
  const colorScheme = useSettingsStore((state) => state.colorScheme);
  const { upColor, downColor } = COLOR_SCHEMES[colorScheme];
  const [recordTab, setRecordTab] = useState<"trades" | "events">("trades");
  const [symbol, setSymbol] = useState("");
  const [kline, setKline] = useState<PaperKlineSnapshot | null>(null);
  const [klineError, setKlineError] = useState("");
  const [cycleDate, setCycleDate] = useState(instance.last_processed_trade_date ?? "");

  const positions = instance.positions ?? [];
  const trades = useMemo(() => instance.trades ?? [], [instance.trades]);
  const events = instance.events ?? [];
  const cycles = instance.cycles ?? [];
  const riskEvents = instance.risk_events ?? [];
  const alerts = instance.alerts ?? [];
  const equityRows = useMemo(
    () => instance.equity_snapshots ?? [],
    [instance.equity_snapshots],
  );
  const symbols = useMemo(() => symbolsFrom(instance), [instance]);
  const symbolNames = useSymbolNames(symbols);
  const strategyVersion = instance.strategy_version;
  const feed = instance.feed_config ?? {};
  const capacity = instance.capacity_limits ?? {};
  const parameters = instance.parameters ?? {};
  const readableParameters = Object.entries(parameters).map(
    ([key, value]) => [parameterLabel[key] ?? key, parameterText(key, value)] as [string, unknown],
  );
  const latestEquity = equityRows.at(-1);
  const equity =
    asNumber(latestEquity?.equity ?? instance.equity) ??
    asNumber(instance.cash_balance) ??
    asNumber(instance.initial_cash);
  const initialCash = asNumber(instance.initial_cash);
  const pnl =
    equity !== null && initialCash !== null ? equity - initialCash : null;
  const returnPct =
    pnl !== null && initialCash !== null && initialCash > 0
      ? (pnl / initialCash) * 100
      : null;
  const drawdown = asNumber(latestEquity?.drawdown);
  const tradeCount = instance.trade_count ?? trades.length;
  const closedPnls = trades
    .map((row) => asNumber(row.realized_pnl ?? row.pnl))
    .filter((value): value is number => value !== null);
  const wins = closedPnls.filter((value) => value > 0);
  const losses = closedPnls.filter((value) => value < 0);
  const winRate =
    closedPnls.length > 0 ? (wins.length / closedPnls.length) * 100 : null;
  const grossProfit = wins.reduce((sum, value) => sum + value, 0);
  const grossLoss = Math.abs(losses.reduce((sum, value) => sum + value, 0));
  const profitFactor =
    closedPnls.length > 0 && grossLoss > 0 ? grossProfit / grossLoss : null;
  const activeAlerts = alerts.filter((row) => row.status === "active");
  const actionableAlerts = activeAlerts.filter((row) =>
    ["warning", "critical"].includes(text(row.severity, "").toLowerCase()),
  );
  const isReplay = ["recorded_replay", "historical_replay", "paper_replay"].includes(
    text(feed.mode, "").toLowerCase(),
  );

  useEffect(() => {
    if (!symbols.length) {
      setSymbol("");
      setKline(null);
      return;
    }
    if (!symbols.includes(symbol)) setSymbol(symbols[0]);
  }, [symbol, symbols]);

  useEffect(() => {
    if (!symbol) return;
    let active = true;
    setKline(null);
    setKlineError("");
    getPaperInstanceKlines(instance.id, symbol)
      .then((result) => {
        if (active) setKline(result);
      })
      .catch((reason) => {
        if (active)
          setKlineError(reason instanceof Error ? reason.message : "K 线读取失败");
      });
    return () => {
      active = false;
    };
  }, [instance.id, symbol]);

  const klineOption = useMemo(() => {
    const bars = kline?.items ?? [];
    const symbolTrades = trades.filter((row) => rowSymbol(row) === symbol);
    const markers = symbolTrades
      .map((row) => {
        const tradeDate = text(row.trade_date ?? row.traded_at, "").slice(0, 10);
        const bar = bars.find((item) => item.date === tradeDate);
        const price = asNumber(row.price ?? row.trade_price);
        if (!tradeDate || !bar || price === null) return null;
        const side = text(row.side).toLowerCase();
        return {
          name: side === "buy" ? "B" : "S",
          coord: [tradeDate, price],
          value: side === "buy" ? "B" : "S",
          itemStyle: { color: side === "buy" ? "#22c55e" : "#ef4444" },
        };
      })
      .filter(Boolean);
    return {
      animation: false,
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
      grid: { left: 54, right: 24, top: 24, bottom: 54 },
      dataZoom: [
        { type: "inside", start: Math.max(0, 100 - (80 / Math.max(bars.length, 1)) * 100), end: 100 },
        { type: "slider", height: 18, bottom: 8, borderColor: "#30363d", textStyle: { color: "#64748b" } },
      ],
      xAxis: {
        type: "category",
        data: bars.map((item) => item.date),
        axisLine: { lineStyle: { color: "#30363d" } },
        axisLabel: { color: "#64748b" },
      },
      yAxis: {
        type: "value",
        scale: true,
        splitLine: { lineStyle: { color: "rgba(48,54,61,.55)" } },
        axisLabel: { color: "#64748b" },
      },
      series: [
        {
          name: "日线",
          type: "candlestick",
          data: bars.map((item) => [
            asNumber(item.open),
            asNumber(item.close),
            asNumber(item.low),
            asNumber(item.high),
          ]),
          itemStyle: {
            color: upColor,
            color0: downColor,
            borderColor: upColor,
            borderColor0: downColor,
          },
          markPoint: { symbolSize: 36, data: markers },
        },
      ],
    };
  }, [downColor, kline, symbol, trades, upColor]);

  const equityOption = useMemo(
    () => ({
      animation: false,
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      grid: { left: 62, right: 24, top: 24, bottom: 34 },
      xAxis: {
        type: "category",
        data: equityRows.map((row) => text(row.trade_date)),
        axisLine: { lineStyle: { color: "#30363d" } },
        axisLabel: { color: "#64748b" },
      },
      yAxis: {
        type: "value",
        scale: true,
        splitLine: { lineStyle: { color: "rgba(48,54,61,.55)" } },
        axisLabel: { color: "#64748b" },
      },
      series: [
        {
          name: "账户权益",
          type: "line",
          data: equityRows.map((row) => asNumber(row.equity)),
          showSymbol: true,
          lineStyle: { color: "#58a6ff", width: 2 },
          itemStyle: { color: "#58a6ff" },
          areaStyle: { color: "rgba(88,166,255,.10)" },
        },
      ],
    }),
    [equityRows],
  );

  const logicDescription =
    strategyVersion?.description ||
    "策略版本未提供文字说明；请以已封存脚本、参数和运行证据为准。";
  const selectionLogic =
    text(strategyVersion?.dependency_manifest?.selection_logic, "") ||
    `${logicDescription} 候选范围固定来自创建模拟盘时选定的股票池。`;
  const tradingLogic =
    text(strategyVersion?.dependency_manifest?.trading_logic, "") ||
    `${logicDescription} 信号在收盘周期生成，按 A 股 T+1、100 股整手和容量约束执行。`;
  const diagnosticItems = ([
    ...(cycles as unknown as Row[]).map((row) => ({
      ...row,
      _kind: "cycle",
      _time: row.finished_at ?? row.trade_date,
    })),
    ...events.map((row) => ({
      ...row,
      _kind: "event",
      _time: row.occurred_at,
    })),
  ] as Row[])
    .sort((a, b) => String(b._time ?? "").localeCompare(String(a._time ?? "")))
    .map((row, index): LogStreamItem => {
      const failed =
        row.status === "failed" ||
        row.status === "blocked" ||
        row.level === "error";
      const isCycle = row._kind === "cycle";
      return {
        id: text(row.id, String(index)),
        time: dateTime(row._time),
        label: isCycle
          ? statusLabel[text(row.status)] ?? text(row.status)
          : statusLabel[text(row.category ?? row.level)] ?? text(row.category ?? row.level),
        message: text(
          row.message,
          isCycle
            ? `交易日 ${text(row.trade_date)} · 信号 ${text(row.signal_count, "--")} · 订单 ${text(row.order_count, "--")} · 成交 ${text(row.trade_count, "--")}`
            : "事件未提供说明",
        ),
        tone: failed ? "red" : isCycle ? "blue" : "neutral",
        meta: isCycle
          ? `交易周期 · ${text(row.trade_date)}`
          : `系统事件 · ${statusLabel[text(row.level)] ?? text(row.level)}`,
      };
    });
  const eventLogItems = events.map((row, index): LogStreamItem => ({
    id: text(row.id, String(index)),
    time: dateTime(row.occurred_at),
    label: statusLabel[text(row.category ?? row.level)] ?? text(row.category ?? row.level),
    message: text(row.message, "事件未提供说明"),
    tone: row.level === "error" ? "red" : row.level === "warning" ? "amber" : "neutral",
    meta: `系统事件 · ${statusLabel[text(row.level)] ?? text(row.level)}`,
  }));

  return (
    <div className="space-y-5" data-testid="paper-instance-monitor">
      <header>
        <button
          type="button"
          onClick={onBack}
          className="mb-4 inline-flex items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-3 py-2 text-sm text-slate-300 hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" />
          返回模拟盘控制台
        </button>
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-2xl font-bold text-white">{instance.name}</h1>
              <StatusBadge tone="amber">
                <FlaskConical className="mr-1 inline h-3 w-3" />
                模拟盘
              </StatusBadge>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
              <span className="inline-flex items-center gap-1.5 font-semibold text-slate-200">
                <span
                  className={clsx(
                    "h-2.5 w-2.5 rounded-full",
                    instance.status === "running"
                      ? "animate-pulse bg-emerald-400"
                      : instance.status === "failed"
                        ? "bg-red-400"
                        : "bg-amber-400",
                  )}
                />
                {statusLabel[instance.status] ?? instance.status}
              </span>
              <span>{strategyVersion?.name ?? "策略版本"} · 日线 · A股</span>
              <span>最后交易日 {instance.last_processed_trade_date ?? "--"}</span>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void onRefresh()}
              disabled={busy}
              className="inline-flex h-10 items-center gap-2 rounded-lg border border-blue-500/35 bg-blue-500/10 px-4 text-xs font-semibold text-blue-200 disabled:opacity-50"
            >
              <RefreshCw className={clsx("h-4 w-4", busy && "animate-spin")} />
              刷新
            </button>
            {instance.status === "draft" || instance.status === "stopped" ? (
              <button type="button" onClick={() => void onAction("start")} disabled={busy} className="inline-flex h-10 items-center gap-2 rounded-lg border border-emerald-500/35 bg-emerald-500/10 px-4 text-xs font-semibold text-emerald-200 disabled:opacity-50"><Play className="h-4 w-4" />启动</button>
            ) : null}
            {instance.status === "running" ? (
              <button type="button" onClick={() => void onAction("pause")} disabled={busy} className="inline-flex h-10 items-center gap-2 rounded-lg border border-amber-500/35 bg-amber-500/10 px-4 text-xs font-semibold text-amber-200 disabled:opacity-50"><Pause className="h-4 w-4" />暂停</button>
            ) : null}
            {instance.status === "paused" ? (
              <button type="button" onClick={() => void onAction("resume")} disabled={busy} className="inline-flex h-10 items-center gap-2 rounded-lg border border-emerald-500/35 bg-emerald-500/10 px-4 text-xs font-semibold text-emerald-200 disabled:opacity-50"><Play className="h-4 w-4" />恢复</button>
            ) : null}
            {["running", "paused"].includes(instance.status) ? (
              <button type="button" onClick={() => void onAction("stop")} disabled={busy} className="inline-flex h-10 items-center gap-2 rounded-lg border border-red-500/35 bg-red-500/10 px-4 text-xs font-semibold text-red-200 disabled:opacity-50"><Square className="h-4 w-4" />停止</button>
            ) : null}
          </div>
        </div>
      </header>

      <div className="grid gap-2 rounded-xl border border-blue-500/20 bg-blue-500/[0.055] p-3 text-[11px] text-slate-400 sm:grid-cols-2 xl:grid-cols-3">
        <div><Database className="mr-1 inline h-3.5 w-3.5 text-blue-400" />数据源：{text(feed.provider) === "postgresql" ? "本地数据库" : text(feed.provider)}</div>
        <div>模式：{isReplay ? "封存历史回放" : text(feed.mode)}</div>
        <div>研究数据：已绑定封存版本</div>
        <div>心跳：{dateTime(instance.heartbeat_at)}</div>
        <div>策略：{strategyVersion?.name ?? qualifyingRun?.strategy_name ?? "未提供"} · 版本 {strategyVersion?.version ?? qualifyingRun?.strategy_version ?? "--"}</div>
        <div>回测准入：{statusLabel[qualifyingRun?.promotion_status ?? ""] ?? (qualifyingRun ? "已完成准入检查" : "未提供")}</div>
        <div>最新周期：{statusLabel[instance.latest_cycle_status ?? ""] ?? instance.latest_cycle_status ?? "--"} · {instance.latest_cycle_trade_date ?? "--"}</div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-9">
        <Metric label="账户总额" value={equity === null ? "--" : `¥${number(equity)}`} note={equity === null ? "尚无权益快照" : `快照 ${latestEquity?.trade_date ?? "--"}`} tone="text-blue-300" icon={<CircleDollarSign className="h-4 w-4" />} />
        <Metric label="总盈亏" value={money(pnl)} note={pnl === null ? "缺少初始资金或权益" : "权益 - 初始资金"} tone={marketToneClass(pnl)} icon={<TrendingUp className="h-4 w-4" />} />
        <Metric label="收益率" value={pct(returnPct)} note={returnPct === null ? "当前不可计算" : "模拟账户收益"} tone={marketToneClass(returnPct)} icon={<BarChart3 className="h-4 w-4" />} />
        <Metric label="Sharpe" value="--" note="Paper API 尚无日收益序列统计" icon={<Gauge className="h-4 w-4" />} />
        <Metric label="胜率" value={pct(winRate, 1)} note={winRate === null ? "尚无可识别的已平仓盈亏" : `${closedPnls.length} 笔已平仓样本`} icon={<Activity className="h-4 w-4" />} />
        <Metric label="盈亏因子" value={profitFactor === null ? "--" : number(profitFactor)} note={profitFactor === null ? "尚无完整盈利/亏损样本" : "毛利 / 毛损"} icon={<TrendingUp className="h-4 w-4" />} />
        <Metric label="成交数" value={String(tradeCount)} note="PG 模拟成交记录" tone="text-blue-300" icon={<ListTree className="h-4 w-4" />} />
        <Metric label="最大回撤" value={drawdown === null ? "--" : pct(drawdown * 100)} note={drawdown === null ? "尚无回撤快照" : "Paper 权益快照"} tone={marketAdverseToneClass(drawdown)} icon={<TrendingDown className="h-4 w-4" />} />
        <Metric label="运行时长" value={runtimeDuration(instance)} note="实例开始至最后心跳" icon={<Clock3 className="h-4 w-4" />} />
      </div>

      <Section title="核心选股与交易逻辑" icon={<BookOpen className="mt-0.5 h-5 w-5 text-blue-400" />}>
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="border-l-2 border-blue-500/50 pl-4">
            <div className="text-xs font-semibold text-blue-300">核心选股</div>
            <p className="mt-2 text-sm leading-6 text-slate-300">{selectionLogic}</p>
          </div>
          <div className="border-l-2 border-emerald-500/50 pl-4">
            <div className="text-xs font-semibold text-emerald-300">交易与风控逻辑</div>
            <p className="mt-2 text-sm leading-6 text-slate-300">{tradingLogic}</p>
          </div>
        </div>
      </Section>

      <Section title="策略参数" subtitle="来自实例固定参数、运行容量边界和行情配置；详情页只读。" icon={<Gauge className="mt-0.5 h-5 w-5 text-cyan-400" />} defaultOpen={false}>
        <div className="space-y-5">
          <ParameterGrid title="交易逻辑参数" values={readableParameters.length ? readableParameters : [["参数", "本实例未覆盖策略默认参数"]]} />
          <ParameterGrid title="风险参数" values={[
            ["现金底线", ratioText(capacity.cash_floor_ratio)],
            ["单票权重上限", ratioText(capacity.max_single_symbol_weight)],
            ["参与率上限", ratioText(capacity.max_participation_ratio)],
            ["最大回撤阈值", ratioText(capacity.max_drawdown)],
            ["日换手上限", ratioText(capacity.max_daily_turnover)],
            ["A股 T+1", "启用"],
            ["整手规则", "100 股"],
          ]} />
        </div>
      </Section>

      <Section title="策略运行诊断日志" subtitle="来自 PostgreSQL 运行周期与实例事件，不依赖临时前端日志。" icon={<Terminal className="mt-0.5 h-5 w-5 text-cyan-400" />} action={<StatusBadge tone={diagnosticItems.length ? "blue" : "neutral"}>{diagnosticItems.length} 条证据</StatusBadge>}>
        <LogStream items={diagnosticItems} emptyText="尚无诊断记录；实例启动并处理周期后生成。" />
      </Section>

      <div className="grid gap-5 2xl:grid-cols-[1.05fr_1fr]">
        <Section title="当前持仓" subtitle="A股数量、可用数量、成本、最新估值与浮动盈亏。" icon={<WalletCards className="mt-0.5 h-5 w-5 text-amber-400" />} action={<span className="rounded-full border border-crypto-border bg-crypto-bg px-2 py-1 text-[10px] text-slate-500">{positions.length} 个持仓</span>}>
          {positions.length === 0 ? <Empty>当前无持仓。手动平仓未开放；退出必须由策略信号并遵守 T+1。</Empty> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[880px] text-xs">
                <thead><tr className="border-b border-crypto-border text-left text-slate-500"><th className="py-2">股票</th><th className="py-2 text-right">数量</th><th className="py-2 text-right">可用</th><th className="py-2 text-right">成本</th><th className="py-2 text-right">最新价</th><th className="py-2 text-right">市值</th><th className="py-2 text-right">浮动盈亏</th></tr></thead>
                <tbody>{positions.map((row, index) => {
                  const unrealized = asNumber(row.unrealized_pnl ?? row.pnl);
                  return <tr key={text(row.id, `${row.symbol}-${index}`)} className="border-b border-white/[0.04] text-slate-300"><td className="py-2.5"><SymbolCell symbol={text(row.symbol, "")} name={text(row.name, "")} names={symbolNames} compact /></td><td className="py-2.5 text-right">{number(row.quantity, 0)}</td><td className="py-2.5 text-right">{number(row.available_quantity ?? row.sellable_quantity, 0)}</td><td className="py-2.5 text-right">{number(row.avg_price ?? row.cost_price)}</td><td className="py-2.5 text-right">{number(row.last_price)}</td><td className="py-2.5 text-right">{number(row.market_value)}</td><td className={clsx("py-2.5 text-right font-semibold", marketToneClass(unrealized))}>{money(unrealized)}</td></tr>;
                })}</tbody>
              </table>
            </div>
          )}
        </Section>

        <Section title="成交与事件" icon={<ListTree className="mt-0.5 h-5 w-5 text-blue-400" />} action={<span className="flex gap-1" onClick={(event) => event.stopPropagation()}>{(["trades", "events"] as const).map((key) => <button key={key} type="button" onClick={() => setRecordTab(key)} className={clsx("rounded-md px-2.5 py-1 text-[10px] font-semibold", recordTab === key ? "bg-blue-500/20 text-blue-300" : "text-slate-500")}>{key === "trades" ? `成交 ${trades.length}` : `事件 ${events.length}`}</button>)}</span>}>
          {recordTab === "trades" ? (
            trades.length === 0 ? <Empty>暂无模拟成交。信号、订单与成交不会相互冒充。</Empty> : <div className="max-h-[360px] overflow-auto"><table className="w-full min-w-[780px] text-xs"><thead><tr className="border-b border-crypto-border text-left text-slate-500"><th className="py-2">时间</th><th>方向</th><th>股票</th><th className="text-right">价格</th><th className="text-right">数量</th><th className="text-right">金额</th><th className="text-right">费用</th></tr></thead><tbody>{trades.map((row, index) => <tr key={text(row.id, String(index))} className="border-b border-white/[0.04] text-slate-300"><td className="py-2.5 text-[10px]">{dateTime(row.traded_at)}</td><td className={text(row.side).toLowerCase() === "buy" ? "text-emerald-300" : "text-red-300"}>{text(row.side).toLowerCase() === "buy" ? "买入" : "卖出"}</td><td className="py-2.5"><SymbolCell symbol={text(row.symbol, "")} name={text(row.name, "")} names={symbolNames} compact /></td><td className="text-right">{number(row.price)}</td><td className="text-right">{number(row.quantity, 0)}</td><td className="text-right">{number(row.amount)}</td><td className="text-right">{number(row.fee, 4)}</td></tr>)}</tbody></table></div>
          ) : <LogStream items={eventLogItems} emptyText="暂无系统事件。" />}
        </Section>
      </div>

      <Section title="买卖点 K线复盘" subtitle="K 线直接读取本实例绑定的 PostgreSQL 封存数据快照；只有真实模拟成交才绘制 B/S 标记。" icon={<CandlestickChart className="mt-0.5 h-5 w-5 text-blue-400" />} action={symbols.length ? <select value={symbol} onChange={(event) => setSymbol(event.target.value)} onClick={(event) => event.stopPropagation()} className="h-8 max-w-[220px] rounded-md border border-crypto-border bg-crypto-bg px-2 text-xs text-slate-300">{symbols.map((item) => <option key={item} value={item}>{formatSymbolLabel(item, symbolNames[item])}</option>)}</select> : undefined}>
        {!symbols.length ? <Empty>当前没有持仓、订单、成交或信号证券，无法确定 K 线标的。</Empty> : klineError ? <Empty>K 线接口失败：{klineError}</Empty> : !kline ? <div className="py-16 text-center text-xs text-slate-500">正在读取封存研究数据…</div> : kline.data_status === "empty" ? <Empty>封存研究数据中没有 {formatSymbolLabel(symbol, symbolNames[symbol])} 的日线数据。</Empty> : <>
          <div className="mb-3 flex flex-wrap justify-between gap-2 text-[10px] text-slate-500"><span>{kline.source_label} · 封存研究数据</span><span>数据截止 {dateTime(kline.knowledge_cutoff_at)} · {kline.total} 根</span></div>
          <ReactECharts option={klineOption} style={{ height: 430 }} />
        </>}
      </Section>

      <Section title="账户曲线" subtitle="来自 Paper 权益快照，不使用准入回测曲线替代实时模拟盘表现。" icon={<TrendingUp className="mt-0.5 h-5 w-5 text-blue-400" />}>
        {equityRows.length === 0 ? <Empty>尚无 Paper 权益快照，无法绘制账户曲线。</Empty> : <ReactECharts option={equityOption} style={{ height: 380 }} />}
      </Section>

      <Section title="风控状态" subtitle="运行保护、回撤、仓位边界、T+1、告警和审计证据。" icon={<ShieldCheck className="mt-0.5 h-5 w-5 text-emerald-400" />}>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[
            ["运行保护", instance.latest_cycle_status === "failed" || instance.latest_cycle_status === "blocked" ? "异常" : "正常", instance.latest_cycle_status === "failed" || instance.latest_cycle_status === "blocked"],
            ["回撤监控", drawdown === null ? "未计算" : pct(drawdown * 100), drawdown !== null && asNumber(capacity.max_drawdown) !== null && drawdown > Number(capacity.max_drawdown)],
            ["仓位边界", `${positions.length} 个持仓`, false],
            ["风险告警", `${actionableAlerts.length} 条`, actionableAlerts.length > 0],
            ["T+1 约束", "启用", false],
            ["100股整手", "启用", false],
            ["账本差额", instance.latest_cycle_ledger_difference === null || instance.latest_cycle_ledger_difference === undefined ? "未提供" : number(instance.latest_cycle_ledger_difference, 4), asNumber(instance.latest_cycle_ledger_difference) !== null && Math.abs(Number(instance.latest_cycle_ledger_difference)) > 0.01],
            ["风险事件", `${riskEvents.length} 条`, riskEvents.some((row) => row.decision === "rejected")],
          ].map(([label, value, danger]) => <div key={String(label)} className="rounded-lg border border-crypto-border bg-crypto-bg/60 p-3"><div className="text-[10px] text-slate-600">{label}</div><div className={clsx("mt-1 text-sm font-semibold", danger ? "text-red-300" : value === "未计算" || value === "未提供" ? "text-amber-300" : "text-emerald-300")}>{String(value)}</div></div>)}
        </div>
        <div className="mt-4 flex flex-wrap items-end gap-3 rounded-lg border border-crypto-border bg-crypto-bg/45 p-3">
          <label className="text-[10px] text-slate-500">封存回放交易日<input type="date" value={cycleDate} onChange={(event) => setCycleDate(event.target.value)} className="mt-1 block h-9 rounded-md border border-crypto-border bg-crypto-bg px-2 text-xs text-slate-200" /></label>
          <button type="button" disabled={busy || instance.status !== "running" || !cycleDate} onClick={() => void onRunCycle(cycleDate)} className="h-9 rounded-md bg-blue-600 px-3 text-xs font-semibold text-white disabled:opacity-40">处理收盘周期</button>
          <span className="text-[10px] text-slate-600">仅处理本实例固定快照，不触发外部 provider 或真实券商。</span>
        </div>
      </Section>
    </div>
  );
}
