import { useMemo, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import clsx from 'clsx';
import { DataPanel, StatusBadge } from '@bitpro/ui';
import {
  Activity,
  ArrowLeft,
  BarChart3,
  BookOpen,
  CandlestickChart,
  ChevronDown,
  DollarSign,
  Edit3,
  FlaskConical,
  Info,
  Layers,
  List,
  PauseCircle,
  RefreshCw,
  ShieldCheck,
  Square,
  Terminal,
  TrendingDown,
  TrendingUp,
  Wallet,
  Zap,
  Braces,
  Database,
  Play,
} from 'lucide-react';
import { formatSymbolLabel } from '../utils/symbolDisplay';
import { useSymbolNames } from '../hooks/useSymbolNames';
import { marketAdverseMetricColor, marketMetricColor, marketToneClass } from '../utils/marketColors';
import { EvidenceStrip } from './OperatorShell';
import type { PaperAccount, Strategy, StrategyBacktestResult, StrategyValidationReport, StrategyVersion } from '../types';

const formatNumber = (value?: number | null, digits = 2) =>
  value == null || !Number.isFinite(value)
    ? '--'
    : Number(value).toLocaleString('zh-CN', {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
      });

const signedMoney = (value?: number | null) => {
  if (value == null || !Number.isFinite(value)) return '--';
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  return `${sign}¥${Math.abs(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
};

const signedPercent = (value?: number | null, digits = 2) =>
  value == null || !Number.isFinite(value) ? '--' : `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;

const parseSymbols = (strategy?: Strategy | null) => {
  const text = `${strategy?.description || ''}\n${strategy?.script_content || ''}`;
  const matches = text.match(/(?:SH|SZ|BJ)_?\d{6}/gi) || [];
  return [...new Set(matches.map((item) => item.toUpperCase().replace(/^(SH|SZ|BJ)(\d)/, '$1_$2')))];
};

const paperTargetLabels = (account: PaperAccount) => {
  const labels = [
    ...(account.positions || []).map((item) => formatSymbolLabel(item.symbol, item.name)),
    ...(account.orders || []).map((item) => formatSymbolLabel(item.symbol, item.name)),
  ];
  return [...new Set(labels)].filter(Boolean);
};

function BackButton({ label = '返回控制台', onBack }: { label?: string; onBack: () => void }) {
  return (
    <button
      type="button"
      onClick={onBack}
      className="inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-lg border border-crypto-border px-3 py-2 text-sm text-gray-300 transition-colors hover:border-gray-500 hover:text-white"
    >
      <ArrowLeft className="h-4 w-4" />
      {label}
    </button>
  );
}

function MetricCard({
  label,
  value,
  icon,
  color,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  color: 'blue' | 'green' | 'red' | 'yellow' | 'amber' | 'gray' | 'neutral' | 'up' | 'down';
}) {
  const colorMap: Record<string, string> = {
    blue: 'text-blue-300',
    green: 'text-emerald-300',
    red: 'text-red-300',
    yellow: 'text-amber-300',
    amber: 'text-amber-300',
    gray: 'text-slate-400',
    neutral: 'text-slate-300',
    up: 'text-up',
    down: 'text-down',
  };
  return (
    <div className="rounded-xl border border-crypto-border bg-crypto-card p-3">
      <div className="mb-1 flex items-center gap-1.5">
        <span className={colorMap[color]}>{icon}</span>
        <span className="text-[10px] text-gray-500">{label}</span>
      </div>
      <div className={clsx('font-mono text-lg font-bold tabular-nums tracking-tight', colorMap[color])}>{value}</div>
    </div>
  );
}

function LogicSummarySection({
  selection,
  trading,
  icon = <BookOpen className="h-4 w-4 shrink-0 text-blue-400" />,
}: {
  selection: string;
  trading: string;
  icon?: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <section className="rounded-xl border border-crypto-border bg-crypto-card/80">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors hover:bg-white/[0.03]"
      >
        <span className="flex min-w-0 items-center gap-2">
          {icon}
          <h2 className="truncate text-base font-semibold text-white">核心选股与交易逻辑</h2>
        </span>
        <ChevronDown className={clsx('h-4 w-4 shrink-0 text-gray-500 transition-transform', open && 'rotate-180 text-gray-300')} />
      </button>
      {open && (
        <div className="grid gap-5 border-t border-crypto-border px-4 py-4 lg:grid-cols-2">
          <div className="border-l border-blue-500/40 pl-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-blue-300">
              <Layers className="h-4 w-4" />
              核心选股
            </div>
            <p className="text-sm leading-6 text-gray-300">{selection}</p>
          </div>
          <div className="border-l border-emerald-500/40 pl-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-emerald-300">
              <BarChart3 className="h-4 w-4" />
              交易逻辑
            </div>
            <p className="text-sm leading-6 text-gray-300">{trading}</p>
          </div>
        </div>
      )}
    </section>
  );
}

function CollapsibleSection({
  title,
  subtitle,
  icon,
  children,
  defaultOpen = true,
  action,
}: {
  title: string;
  subtitle?: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
  action?: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card shadow-lg shadow-black/20">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left transition-colors hover:bg-white/[0.03]"
      >
        <span className="flex min-w-0 items-start gap-3">
          {icon}
          <span className="min-w-0">
            <span className="block truncate text-base font-semibold text-white">{title}</span>
            {subtitle ? <span className="mt-1 block text-xs text-gray-500">{subtitle}</span> : null}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-3">
          {action}
          <ChevronDown className={clsx('h-4 w-4 text-gray-500 transition-transform', open && 'rotate-180 text-gray-300')} />
        </span>
      </button>
      {open && <div className="border-t border-crypto-border px-5 py-4">{children}</div>}
    </section>
  );
}

const evidenceValue = (value: unknown) =>
  value === null || value === undefined || value === '' ? '未提供' : String(value);

const strategyStatusLabel = (value?: string | null) => {
  const labels: Record<string, string> = {
    active: '已启用',
    draft: '草稿',
    failed: '失败',
    published: '已发布',
    sealed: '已封存',
    valid: '校验通过',
  };
  return value ? labels[value] ?? value : '未提供';
};

const evidenceEntries = (value?: Record<string, unknown> | null) =>
  Object.entries(value ?? {}).filter(([, item]) => item !== undefined);

export function StrategyDetailPanel({
  strategy,
  version,
  validation,
  onBack,
  onEdit,
  onBacktest,
  onPaper,
}: {
  strategy: Strategy;
  version?: StrategyVersion | null;
  validation?: StrategyValidationReport | null;
  onBack: () => void;
  onEdit?: () => void;
  onBacktest?: () => void;
  onPaper?: () => void;
}) {
  const symbols = parseSymbols(strategy);
  const symbolNames = useSymbolNames(symbols);
  const parameters = evidenceEntries(version?.parameter_schema);
  const runtimeLimits = evidenceEntries(version?.runtime_limits);
  const dependencies = version?.data_dependencies ?? validation?.dependencies ?? [];
  const isValid = validation?.valid ?? version?.validation_status === 'valid';
  return (
    <div className="space-y-4" data-testid="strategy-detail-workspace">
      <header className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <BackButton label="返回" onBack={onBack} />
          <div className="min-w-0">
            <div className="mb-1.5 flex flex-wrap items-center gap-2">
              <StatusBadge tone="amber">A股</StatusBadge>
              <StatusBadge tone="blue">1D</StatusBadge>
              <StatusBadge tone={strategy.is_running ? 'green' : 'neutral'}>
                {strategy.is_running ? '运行中' : '未启动'}
              </StatusBadge>
            </div>
            <h1 className="text-xl font-bold leading-tight text-white sm:text-2xl">{strategy.name}</h1>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
              <span>当前版本 {version ? `v${version.version}` : '未绑定'}</span>
              <span>更新于 {strategy.updated_at ? new Date(strategy.updated_at).toLocaleString('zh-CN', { hour12: false }) : '未提供'}</span>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 xl:justify-end">
          {onBacktest ? (
            <button type="button" onClick={onBacktest} className="inline-flex h-10 items-center gap-2 rounded-lg border border-purple-500/35 bg-purple-500/10 px-4 text-xs font-semibold text-purple-200 hover:bg-purple-500/15">
              <FlaskConical className="h-4 w-4" />进入回测
            </button>
          ) : null}
          {onPaper ? (
            <button type="button" onClick={onPaper} className="inline-flex h-10 items-center gap-2 rounded-lg border border-emerald-500/35 bg-emerald-500/10 px-4 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/15">
              <Play className="h-4 w-4" />进入模拟盘
            </button>
          ) : null}
          {onEdit ? (
            <button type="button" onClick={onEdit} className="inline-flex h-10 items-center gap-2 rounded-lg bg-blue-600 px-4 text-xs font-semibold text-white transition-colors hover:bg-blue-700">
              <Edit3 className="h-4 w-4" />编辑策略
            </button>
          ) : null}
        </div>
      </header>

      <EvidenceStrip
        items={[
          { label: '版本', value: version ? `v${version.version}` : '未绑定' },
          {
            label: '校验',
            value: isValid ? '通过' : validation ? '未通过' : '未校验',
            tone: isValid ? 'green' : validation ? 'amber' : 'neutral',
          },
          { label: '依赖', value: `${dependencies.length} 项` },
          { label: '标的', value: symbols.length ? `${symbols.length} 只` : '未声明' },
        ]}
      />

      <DataPanel
        title={<span className="inline-flex items-center gap-2"><BookOpen className="h-4 w-4 text-blue-400" />核心选股与交易逻辑</span>}
        subtitle="策略定义中的可解释逻辑；进入回测或模拟前先核对信号、交易与风控边界。"
      >
        <div className="grid gap-5 p-4 lg:grid-cols-2">
          <div className="border-l-2 border-blue-500/45 pl-4">
            <div className="text-xs font-semibold text-blue-300">核心选股</div>
            <p className="mt-2 text-sm leading-6 text-slate-300">
              {evidenceValue(version?.dependency_manifest?.selection_logic ?? '基于全 A 股票池、指数环境、板块热度与日线数据生成候选标的，并支持 ST、行业、概念和指数成分过滤。')}
            </p>
          </div>
          <div className="border-l-2 border-emerald-500/45 pl-4">
            <div className="text-xs font-semibold text-emerald-300">交易与风控逻辑</div>
            <p className="mt-2 text-sm leading-6 text-slate-300">
              {evidenceValue(version?.dependency_manifest?.trading_logic ?? '以策略运行时为执行核心，统一遵循 A 股只做多、100 股一手、T+1、佣金、印花税、滑点和最低佣金约束。')}
            </p>
          </div>
        </div>
      </DataPanel>

      <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <DataPanel title="策略描述" subtitle="来自策略注册表，不使用自动生成的营销文案。">
          <p className="p-4 text-sm leading-6 text-slate-300">{strategy.description || '暂无描述'}</p>
        </DataPanel>
        <DataPanel title="交易范围" subtitle="运行时仍以绑定股票池或快照为准。">
          <div className="p-4">
          {symbols.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {symbols.map((symbol) => (
                <span key={symbol} className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-1 text-xs text-gray-300">
                  {formatSymbolLabel(symbol, symbolNames[symbol])}
                </span>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500">多股组合 / 全 A 可扩展股票池</p>
          )}
          </div>
        </DataPanel>
      </div>

      <DataPanel
        title={<span className="inline-flex items-center gap-2"><Database className="h-4 w-4 text-cyan-400" />版本状态</span>}
        subtitle="展示使用者需要核对的版本、兼容性、校验和数据绑定状态。"
        actions={<StatusBadge tone={!version ? 'amber' : isValid ? 'green' : 'red'}>{!version ? '未绑定版本' : isValid ? '校验通过' : '校验未通过'}</StatusBadge>}
      >
        <dl className="grid gap-px bg-crypto-border sm:grid-cols-2 xl:grid-cols-4">
          {[
            ['版本', version ? `v${version.version}` : '未提供'],
            ['策略 API', version?.strategy_api_version ?? validation?.api_version ?? '未提供'],
            ['状态', strategyStatusLabel(version?.status ?? version?.validation_status)],
            ['研究数据', version?.dataset_snapshot_id ? '已绑定封存版本' : '未绑定'],
          ].map(([label, value]) => (
            <div key={label} className="min-w-0 bg-crypto-card px-4 py-3">
              <dt className="text-[10px] text-slate-500">{label}</dt>
              <dd className="mt-1 truncate text-xs font-semibold tabular-nums text-slate-200" title={value}>{value}</dd>
            </div>
          ))}
        </dl>
        {validation?.issues?.length ? (
          <div className="border-t border-crypto-border bg-red-500/[0.045] px-4 py-3 text-xs text-red-200">
            {validation.issues.map((issue) => `${issue.code}: ${issue.message}`).join('；')}
          </div>
        ) : null}
      </DataPanel>

      <div className="grid gap-4 xl:grid-cols-2">
        <DataPanel title={<span className="inline-flex items-center gap-2"><Braces className="h-4 w-4 text-purple-400" />参数与运行边界</span>} subtitle="只展示当前版本已持久化的参数模式与运行限制。">
          <div className="grid gap-px bg-crypto-border sm:grid-cols-2">
            {[...parameters, ...runtimeLimits].length ? [...parameters, ...runtimeLimits].map(([label, value]) => (
              <div key={label} className="min-w-0 bg-crypto-card px-4 py-3">
                <div className="text-[10px] text-slate-500">{label}</div>
                <div className="mt-1 break-all text-xs font-semibold text-slate-300">{typeof value === 'object' ? JSON.stringify(value) : evidenceValue(value)}</div>
              </div>
            )) : <div className="col-span-full bg-crypto-card px-4 py-10 text-center text-xs text-slate-500">当前版本未提供结构化参数；不能将缺失参数显示为默认值。</div>}
          </div>
        </DataPanel>
        <DataPanel title="数据依赖" subtitle="策略执行前需要满足的数据与运行时依赖。">
          <div className="p-4">
            {dependencies.length ? <div className="flex flex-wrap gap-2">{dependencies.map((item) => <StatusBadge key={item} tone="blue">{item}</StatusBadge>)}</div> : <div className="py-6 text-center text-xs text-slate-500">当前版本未声明数据依赖。</div>}
          </div>
        </DataPanel>
      </div>

      <DataPanel title={<span className="inline-flex items-center gap-2"><Terminal className="h-4 w-4 text-cyan-400" />策略源码</span>} subtitle="当前注册策略源码，只读展示；修改需进入编辑策略并生成新版本。">
        <pre className="max-h-[420px] overflow-auto bg-[#090d12] p-4 text-[11px] leading-5 text-slate-300"><code>{strategy.script_content || '当前策略没有可展示源码。'}</code></pre>
      </DataPanel>
    </div>
  );
}

export function BacktestDetailPanel({ result, onBack }: { result: StrategyBacktestResult; onBack: () => void }) {
  const [resultTab, setResultTab] = useState<'overview' | 'performance' | 'trades'>('overview');
  const totalFees = result.trades.reduce((sum, trade) => sum + (trade.fee || 0), 0);
  const profitFactor = result.profit_factor ?? null;
  const valueTone = (value?: number | null) => (value == null || !Number.isFinite(value) ? 'muted' : value >= 0 ? 'up' : 'down');
  const metricTiles = [
    { label: '累计收益', value: signedPercent(result.total_return), tone: marketMetricColor(result.total_return) },
    { label: '年化收益率', value: result.annual_return == null ? '-' : `${formatNumber(result.annual_return)}%`, tone: valueTone(result.annual_return) },
    { label: '基准收益率', value: '-', tone: 'muted' },
    { label: '阿尔法', value: '-', tone: 'muted' },
    { label: '贝塔', value: '-', tone: 'muted' },
    { label: '夏普比率', value: formatNumber(result.sharpe), tone: valueTone(result.sharpe) },
    { label: '胜率', value: `${formatNumber(result.win_rate)}%`, tone: result.win_rate >= 50 ? 'up' : 'down' },
    { label: '盈亏比', value: profitFactor == null ? '-' : formatNumber(profitFactor), tone: profitFactor == null ? 'muted' : profitFactor >= 1 ? 'up' : 'down' },
    { label: '索提诺比率', value: '-', tone: 'muted' },
    { label: '最大回撤', value: `${formatNumber(result.max_drawdown)}%`, tone: 'down' },
  ];

  const equityOption = useMemo(
    () => ({
      backgroundColor: 'transparent',
      grid: { left: 52, right: 20, top: 24, bottom: 36 },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: result.equity_curve.map((item) => item.date),
        axisLine: { lineStyle: { color: '#30363D' } },
        axisLabel: { color: '#8B949E' },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLine: { lineStyle: { color: '#30363D' } },
        splitLine: { lineStyle: { color: '#21262D' } },
        axisLabel: { color: '#8B949E' },
      },
      series: [
        {
          type: 'line',
          data: result.equity_curve.map((item) => item.equity),
          smooth: true,
          lineStyle: { color: '#00C853', width: 2 },
          areaStyle: { color: 'rgba(0,200,83,0.12)' },
        },
      ],
    }),
    [result.equity_curve],
  );

  const tradeRows = result.trades.slice().reverse();

  return (
    <div className="space-y-9">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex h-16 items-center gap-3 rounded-2xl border border-crypto-border bg-crypto-card px-8 text-xl font-bold text-gray-200 transition-colors hover:border-blue-500/50 hover:text-blue-300"
      >
        <ArrowLeft className="h-5 w-5" />
        返回控制台
      </button>

      <div>
        <h1 className="text-[32px] font-bold leading-tight text-[#FFAB73]">{result.strategy_name}</h1>
        <div className="mt-6 flex flex-wrap items-center gap-4">
          <span className="rounded-lg border border-purple-500/45 bg-purple-500/15 px-4 py-2 text-lg font-bold text-purple-200">A股</span>
          <span className="rounded-full border border-green-500/45 bg-green-500/15 px-5 py-2 text-lg font-bold text-green-300">历史记录</span>
          <span className="text-xl text-gray-500">{result.start_date} 至 {result.end_date}</span>
        </div>
      </div>

      <section className="overflow-hidden rounded-2xl border border-crypto-border bg-crypto-card">
        <div className="flex flex-wrap items-center justify-between gap-5 px-8 py-7">
          <div className="flex flex-wrap items-center gap-4">
            <h2 className="text-[28px] font-bold text-[#FFAB73]">{result.strategy_name}</h2>
            <span className="rounded-lg bg-blue-500/20 px-4 py-2 text-base font-bold text-blue-300">历史记录</span>
            <span className="rounded-lg bg-crypto-bg px-4 py-2 text-base text-gray-500">{result.start_date} 至 {result.end_date}</span>
          </div>
          <div className="flex items-center gap-1 rounded-xl bg-crypto-bg p-1.5">
            {([
              ['overview', '概要'],
              ['performance', '绩效'],
              ['trades', '交易记录'],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setResultTab(key)}
                className={clsx(
                  'rounded-lg px-6 py-3 text-lg font-bold transition-colors',
                  resultTab === key ? 'bg-purple-500/35 text-purple-200' : 'text-gray-500 hover:text-gray-300',
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div data-testid="backtest-detail-metrics" className="mx-8 mb-8 grid overflow-hidden rounded-2xl border border-crypto-border md:grid-cols-5 xl:grid-cols-10">
          {metricTiles.map((metric) => (
            <div key={metric.label} className="min-h-[112px] border-b border-r border-crypto-border px-2 py-6 text-center last:border-r-0 md:[&:nth-child(n+6)]:border-b-0 xl:border-b-0">
              <div
                className={clsx(
                  'text-[26px] font-bold leading-tight tabular-nums',
                  metric.tone === 'up' && 'text-up',
                  metric.tone === 'down' && 'text-down',
                  (metric.tone === 'muted' || metric.tone === 'neutral') && 'text-gray-400',
                )}
              >
                {metric.value}
              </div>
              <div className="mt-4 flex items-center justify-center gap-1 text-xs text-gray-500">
                <span className="whitespace-nowrap">{metric.label}</span>
                <Info className="h-3.5 w-3.5" />
              </div>
            </div>
          ))}
        </div>
      </section>

      {resultTab === 'overview' && (
        <section className="overflow-hidden rounded-2xl border border-crypto-border bg-crypto-card">
          <div className="flex flex-wrap items-center justify-between gap-4 px-8 py-6">
            <div className="flex flex-wrap items-center gap-8">
              <span className="text-lg text-gray-500">缩放时间</span>
              {['1月', '3月', '6月', '1年', '全部'].map((item) => (
                <button
                  key={item}
                  type="button"
                  className={clsx(
                    'rounded-lg px-4 py-2 text-lg font-bold',
                    item === '全部' ? 'bg-purple-500/35 text-purple-200' : 'text-gray-500 hover:text-gray-300',
                  )}
                >
                  {item}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-8 text-lg">
              <span className="text-gray-500">区间收益 <strong className={marketToneClass(result.total_return)}>{signedPercent(result.total_return)}</strong></span>
              <span className="text-gray-500">区间最大回撤 <strong className="text-down">{formatNumber(result.max_drawdown)}%</strong></span>
            </div>
          </div>
          <div className="border-t border-crypto-border px-8 py-6">
            <div className="mb-4 text-lg font-semibold text-white">资金曲线</div>
            <div className="h-[520px]">
              {result.equity_curve.length > 0 ? (
                <ReactECharts option={equityOption} style={{ height: '100%', width: '100%' }} />
              ) : (
                <div className="flex h-full items-center justify-center text-lg text-gray-500">暂无资金曲线数据</div>
              )}
            </div>
          </div>
        </section>
      )}

      {resultTab === 'performance' && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="rounded-2xl border border-crypto-border bg-crypto-card p-6">
            <h3 className="mb-4 flex items-center gap-2 text-lg font-semibold text-white">
              <Activity className="h-4 w-4 text-purple-400" />
              交易统计
            </h3>
            <div className="space-y-3 text-base">
              {[
                ['总交易次数', String(result.total_trades), 'text-gray-200'],
                ['胜率', `${formatNumber(result.win_rate)}%`, result.win_rate >= 50 ? 'text-up' : 'text-down'],
                ['盈亏比', profitFactor == null ? '--' : formatNumber(profitFactor), 'text-gray-200'],
                ['股票数量', String(result.symbols.length), 'text-blue-300'],
              ].map(([label, value, color]) => (
                <div key={label} className="flex justify-between border-b border-crypto-border/50 pb-2">
                  <span className="text-gray-500">{label}</span>
                  <span className={clsx('font-semibold tabular-nums', color)}>{value}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-2xl border border-crypto-border bg-crypto-card p-6">
            <h3 className="mb-4 flex items-center gap-2 text-lg font-semibold text-white">
              <DollarSign className="h-4 w-4 text-green-400" />
              资金统计
            </h3>
            <div className="space-y-3 text-base">
              {[
                ['初始资金', `¥${formatNumber(result.initial_capital)}`, 'text-gray-200'],
                ['最终资金', `¥${formatNumber(result.final_capital)}`, marketToneClass(result.final_capital - result.initial_capital)],
                ['总手续费', `¥${formatNumber(totalFees)}`, 'text-gray-200'],
                ['最大回撤', `${formatNumber(result.max_drawdown)}%`, 'text-down'],
              ].map(([label, value, color]) => (
                <div key={label} className="flex justify-between border-b border-crypto-border/50 pb-2">
                  <span className="text-gray-500">{label}</span>
                  <span className={clsx('font-semibold tabular-nums', color)}>{value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {resultTab === 'trades' && (
        <div className="rounded-2xl border border-crypto-border bg-crypto-card p-6">
          <h3 className="mb-4 flex items-center gap-2 text-lg font-semibold text-white">
            <List className="h-4 w-4 text-blue-400" />
            交易记录
            <span className="ml-auto text-xs text-gray-500">{result.trades.length} 笔</span>
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead>
                <tr className="border-b border-crypto-border text-xs text-gray-500">
                  <th className="py-3 text-left font-medium">时间</th>
                  <th className="py-3 text-left font-medium">股票</th>
                  <th className="py-3 text-left font-medium">方向</th>
                  <th className="py-3 text-right font-medium">成交价</th>
                  <th className="py-3 text-right font-medium">数量</th>
                  <th className="py-3 text-right font-medium">成交金额</th>
                  <th className="py-3 text-right font-medium">手续费</th>
                  <th className="py-3 text-right font-medium">盈亏</th>
                </tr>
              </thead>
              <tbody>
                {tradeRows.map((trade, index) => (
                  <tr key={`${trade.date}-${trade.symbol}-${index}`} className="border-b border-crypto-border/20 transition-colors hover:bg-white/[0.02]">
                    <td className="py-3 text-sm text-gray-400">{trade.date}</td>
                    <td className="py-3 text-sm font-medium text-gray-200">{formatSymbolLabel(trade.symbol, trade.name || result.symbol_names?.[trade.symbol])}</td>
                    <td className={clsx('py-3 text-sm font-semibold', trade.side === 'buy' ? 'text-up' : 'text-down')}>
                      {trade.side === 'buy' ? '买入' : '卖出'}
                    </td>
                    <td className="py-3 text-right text-sm font-mono tabular-nums text-blue-300">{formatNumber(trade.price)}</td>
                    <td className="py-3 text-right text-sm font-mono tabular-nums text-blue-300">{trade.quantity}</td>
                    <td className="py-3 text-right text-sm text-gray-300">¥{formatNumber(trade.amount)}</td>
                    <td className="py-3 text-right text-sm text-gray-300">¥{formatNumber(trade.fee)}</td>
                    <td className={clsx('py-3 text-right text-sm font-semibold', marketToneClass(trade.pnl))}>
                      {trade.pnl > 0 ? '+' : ''}{formatNumber(trade.pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {tradeRows.length === 0 && <div className="py-12 text-center text-sm text-gray-500">暂无交易记录</div>}
          </div>
        </div>
      )}
    </div>
  );
}

const paperWinRate = (account: PaperAccount) => {
  const positions = account.positions || [];
  if (positions.length === 0) return 0;
  return (positions.filter((item) => item.pnl >= 0).length / positions.length) * 100;
};

const paperProfitFactor = (account: PaperAccount) => {
  const positions = account.positions || [];
  const profit = positions.reduce((sum, item) => sum + Math.max(item.pnl, 0), 0);
  const loss = positions.reduce((sum, item) => sum + Math.abs(Math.min(item.pnl, 0)), 0);
  if (profit <= 0) return 0;
  return loss === 0 ? profit / 1000 : profit / loss;
};

const paperMaxDrawdown = (account: PaperAccount) => {
  const rows = account.equity_curve || [];
  if (rows.length < 2) return 0;
  let peak = rows[0].equity;
  let maxDrawdown = 0;
  for (const row of rows) {
    peak = Math.max(peak, row.equity);
    if (peak > 0) maxDrawdown = Math.max(maxDrawdown, ((peak - row.equity) / peak) * 100);
  }
  return maxDrawdown;
};

const paperRuntime = (account: PaperAccount) => {
  const start = Date.parse(account.created_at || '');
  if (!Number.isFinite(start)) return '-';
  const diff = Math.max(0, Date.now() - start);
  const hours = Math.floor(diff / 3600000);
  const minutes = Math.floor((diff % 3600000) / 60000);
  if (hours <= 0) return `${minutes}m`;
  return `${hours}h ${minutes}m`;
};

export function PaperInstanceDetailPanel({
  account,
  onBack,
  onRefresh,
  onStop,
}: {
  account: PaperAccount;
  onBack: () => void;
  onRefresh?: (account: PaperAccount) => void | Promise<void>;
  onStop?: (account: PaperAccount) => void | Promise<void>;
}) {
  const [logTab, setLogTab] = useState<'trades' | 'events'>('trades');
  const pnl = account.equity - account.initial_capital;
  const returnPct = account.initial_capital ? (pnl / account.initial_capital) * 100 : 0;
  const curveRows = account.equity_curve?.length
    ? account.equity_curve
    : [{ time: account.updated_at || account.created_at, equity: account.equity, cash: account.cash }];
  const orders = account.orders || [];
  const positions = account.positions || [];
  const events = account.events || [];
  const winRate = paperWinRate(account);
  const profitFactor = paperProfitFactor(account);
  const maxDrawdown = paperMaxDrawdown(account);
  const running = account.status.toLowerCase() === 'running';
  const targetLabels = paperTargetLabels(account);
  const reviewOrders = orders.slice(0, 8);

  const equityOption = useMemo(
    () => ({
      backgroundColor: 'transparent',
      grid: { left: 52, right: 20, top: 20, bottom: 36 },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: curveRows.map((item) => item.time || '--'),
        axisLine: { lineStyle: { color: '#30363D' } },
        axisLabel: { color: '#8B949E' },
      },
      yAxis: {
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { color: '#21262D' } },
        axisLabel: { color: '#8B949E' },
      },
      series: [
        {
          type: 'line',
          data: curveRows.map((item) => item.equity),
          smooth: true,
          lineStyle: { color: '#58A6FF', width: 2 },
          areaStyle: { color: 'rgba(88,166,255,0.14)' },
        },
      ],
    }),
    [curveRows],
  );

  return (
    <div className="space-y-6">
      <div className="space-y-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="inline-flex h-12 items-center gap-2 rounded-xl border border-yellow-500/40 bg-yellow-500/10 px-4 text-sm font-bold text-yellow-300 shadow-[0_0_0_1px_rgba(234,179,8,0.08)]">
              <FlaskConical className="h-4 w-4" />
              模拟盘
            </div>
            <p className="mt-3 text-xs text-gray-500">模拟 · 只做 PaperBroker / 模拟成交，不触碰真实资金。</p>
          </div>
          <span className="rounded-lg border border-crypto-border bg-crypto-bg px-3 py-1.5 text-xs font-semibold text-gray-400">实例监控</span>
        </div>
        <BackButton onBack={onBack} />
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0 flex-1 space-y-2">
            <h1 className="truncate text-2xl font-bold tracking-tight text-white sm:text-3xl">{account.name}</h1>
            <div className="flex flex-wrap items-center gap-3">
              <div className={clsx('h-3 w-3 shrink-0 rounded-full', running ? 'animate-pulse bg-green-400' : 'bg-gray-500')} />
              <span className="text-base font-bold text-white">{running ? '运行中' : account.status === 'stopped' ? '已停止' : account.status}</span>
              <span className="rounded-full bg-yellow-500/20 px-2 py-0.5 text-[10px] font-bold text-yellow-400">模拟盘</span>
              <span className="text-[10px] font-mono text-gray-500">account_id={account.account_id}</span>
              <span className="text-xs text-gray-500">
                {account.strategy_name || 'A股策略'} · {targetLabels.slice(0, 2).join(' / ') || '多股组合'} · 1D
              </span>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => void onRefresh?.(account)}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-blue-500/35 bg-blue-500/10 px-4 text-xs font-semibold text-blue-200 transition-colors hover:bg-blue-500/20"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              刷新
            </button>
            <button
              type="button"
              disabled={!running}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-yellow-500/35 bg-yellow-500/10 px-4 text-xs font-semibold text-yellow-200 transition-colors hover:bg-yellow-500/20 disabled:cursor-not-allowed disabled:opacity-45"
            >
              <PauseCircle className="h-3.5 w-3.5" />
              暂停交易
            </button>
            <button
              type="button"
              onClick={() => void onStop?.(account)}
              disabled={!running}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-4 text-xs font-semibold text-red-200 transition-colors hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-45"
            >
              <Square className="h-3.5 w-3.5" />
              关闭交易
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-8">
        <MetricCard label="账户总额" value={`¥${formatNumber(account.equity)}`} icon={<DollarSign className="h-4 w-4" />} color="blue" />
        <MetricCard label="总盈亏" value={signedMoney(pnl)} icon={pnl >= 0 ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />} color={marketMetricColor(pnl)} />
        <MetricCard label="收益率" value={signedPercent(returnPct)} icon={returnPct >= 0 ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />} color={marketMetricColor(returnPct)} />
        <MetricCard label="胜率" value={`${winRate.toFixed(1)}%`} icon={<Activity className="h-4 w-4" />} color="blue" />
        <MetricCard label="盈亏比" value={formatNumber(profitFactor)} icon={<Zap className="h-4 w-4" />} color="blue" />
        <MetricCard label="总交易" value={String(orders.length)} icon={<Activity className="h-4 w-4" />} color="blue" />
        <MetricCard label="最大回撤" value={`${maxDrawdown.toFixed(1)}%`} icon={<TrendingDown className="h-4 w-4" />} color={marketAdverseMetricColor(maxDrawdown)} />
        <MetricCard label="运行时间" value={paperRuntime(account)} icon={<Activity className="h-4 w-4" />} color="gray" />
      </div>

      <LogicSummarySection
        selection="使用策略输出的 A 股候选股票池、最新行情和模拟持仓生成下一轮候选信号。"
        trading="复用回测成本、仓位和风控口径；模拟成交只写入 PaperBroker 账户、订单、持仓、权益曲线和事件流。"
        icon={<BookOpen className="h-4 w-4 shrink-0 text-blue-400" />}
      />

      <section className="flex min-h-14 items-center overflow-hidden rounded-xl border border-crypto-border bg-crypto-card shadow-lg shadow-black/20">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-white/[0.03]"
        >
          <ChevronDown className="-rotate-90 h-4 w-4 shrink-0 text-gray-500" />
          <Terminal className="h-4 w-4 shrink-0 text-cyan-400" />
          <span className="min-w-0 truncate text-sm font-semibold text-white">策略运行诊断日志</span>
          <span className="shrink-0 text-xs text-gray-500">模拟账户 · 运行诊断</span>
          <span className="hidden truncate text-xs text-gray-500 md:inline">{account.updated_at || '--'}</span>
          <span className={clsx('hidden shrink-0 text-xs font-semibold lg:inline', running ? 'text-emerald-400' : 'text-purple-400')}>
            {running ? '运行态连接' : '已停止 · 状态缓存'}
          </span>
        </button>
        <button type="button" className="h-14 border-l border-crypto-border px-5 text-xs font-semibold text-gray-500 hover:text-gray-300">
          清空
        </button>
      </section>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.05fr_1fr]">
        <CollapsibleSection
          title="当前持仓"
          icon={<Wallet className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" />}
          action={<span className="rounded-full border border-crypto-border bg-crypto-bg px-2.5 py-1 text-[11px] font-semibold text-gray-400">{positions.length} 个持仓</span>}
        >
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-xs text-gray-500">未实现盈亏（汇总）</span>
            <span className={clsx('text-sm font-bold tabular-nums', marketToneClass(pnl))}>{signedMoney(pnl)}</span>
          </div>
          {positions.length === 0 ? (
            <div className="rounded-lg border border-dashed border-crypto-border bg-crypto-bg/50 py-10 text-center text-xs text-gray-500">当前无持仓</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left text-xs">
                <thead>
                  <tr className="border-b border-crypto-border text-gray-500">
                    <th className="py-2 pr-2 font-medium text-left">股票</th>
                    <th className="py-2 pr-2 font-medium text-right">数量</th>
                    <th className="py-2 pr-2 font-medium text-right">持仓市值</th>
                    <th className="py-2 pr-2 font-medium text-right">持仓均价</th>
                    <th className="py-2 pr-2 font-medium text-right">最新价</th>
                    <th className="py-2 pr-2 font-medium text-right">浮动盈亏</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((position) => (
                    <tr key={position.symbol} className="border-b border-crypto-border/60 text-gray-200">
                      <td className="py-2 pr-2 font-mono">{formatSymbolLabel(position.symbol, position.name)}</td>
                      <td className="py-2 pr-2 text-right tabular-nums">{position.quantity}</td>
                      <td className="py-2 pr-2 text-right tabular-nums">{formatNumber(position.market_value)}</td>
                      <td className="py-2 pr-2 text-right tabular-nums">{formatNumber(position.avg_price)}</td>
                      <td className="py-2 pr-2 text-right tabular-nums">{formatNumber(position.last_price)}</td>
                      <td className={clsx('py-2 pr-2 text-right font-medium tabular-nums', marketToneClass(position.pnl))}>{signedMoney(position.pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CollapsibleSection>

        <CollapsibleSection
          title="成交与事件"
          icon={<List className="mt-0.5 h-5 w-5 shrink-0 text-blue-400" />}
          action={
            <div className="flex flex-wrap gap-2" onClick={(event) => event.stopPropagation()}>
              {([
                ['trades', `成交明细 (${orders.length})`],
                ['events', `系统事件 (${events.length})`],
              ] as const).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setLogTab(key)}
                  className={clsx(
                    'rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors',
                    logTab === key ? 'border border-blue-500/40 bg-blue-500/20 text-blue-300' : 'border border-transparent text-gray-400 hover:text-white',
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          }
        >
          {logTab === 'trades' ? (
            orders.length === 0 ? (
              <div className="py-12 text-center text-xs text-gray-500">暂无成交记录</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-left text-xs">
                  <thead className="sticky top-0 z-[1] bg-crypto-card shadow-[0_1px_0_#333]">
                    <tr className="text-gray-500">
                      <th className="py-2 pr-2 font-medium text-left">时间</th>
                      <th className="py-2 pr-2 font-medium text-center">方向</th>
                      <th className="py-2 pr-2 font-medium text-left">股票</th>
                      <th className="py-2 pr-2 font-medium text-right">价格</th>
                      <th className="py-2 pr-2 font-medium text-right">数量</th>
                      <th className="py-2 pr-2 font-medium text-right">交易金额</th>
                      <th className="py-2 font-medium text-right">手续费</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orders.map((order, index) => (
                      <tr key={`${order.symbol}-${index}`} className="border-b border-crypto-border/60 text-gray-200">
                        <td className="py-2 pr-2 whitespace-nowrap text-[10px] text-gray-400">{order.created_at || '--'}</td>
                        <td className={clsx('py-2 pr-2 text-center font-semibold', order.side === 'buy' ? 'text-up' : 'text-down')}>{order.side === 'buy' ? '买入' : '卖出'}</td>
                        <td className="py-2 pr-2 font-mono">{formatSymbolLabel(order.symbol, order.name)}</td>
                        <td className="py-2 pr-2 text-right tabular-nums">{formatNumber(order.price)}</td>
                        <td className="py-2 pr-2 text-right tabular-nums">{order.quantity}</td>
                        <td className="py-2 pr-2 text-right tabular-nums">{formatNumber(order.amount)}</td>
                        <td className="py-2 text-right tabular-nums text-gray-400">{formatNumber(order.fee, 4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          ) : (
            <div className="space-y-2">
              {events.length === 0 && <div className="py-12 text-center text-xs text-gray-500">暂无系统事件</div>}
              {events.map((event, index) => (
                <div key={`${event.message}-${index}`} className="flex items-start gap-2 rounded-lg bg-crypto-bg p-2">
                  <ShieldCheck className="mt-0.5 h-3.5 w-3.5 text-blue-400" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs text-white">{event.message}</div>
                    <div className="mt-0.5 text-[10px] text-gray-600">{event.created_at || event.level}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CollapsibleSection>
      </div>

      <CollapsibleSection
        title="买卖点 K线复盘"
        subtitle="使用模拟盘真实成交记录叠加 B/S 成交点，K 线按策略周期读取真实行情。"
        icon={<CandlestickChart className="mt-0.5 h-5 w-5 shrink-0 text-blue-400" />}
        action={<span className="rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 text-xs font-semibold text-gray-200">1D</span>}
      >
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-semibold text-white">成交点时间线</div>
              <p className="mt-1 text-xs text-gray-500">按最近成交顺序展示买卖点。</p>
            </div>
            <span className="rounded-full border border-crypto-border bg-crypto-bg px-2.5 py-1 text-[11px] font-semibold text-gray-400">
              {reviewOrders.length} 个成交点
            </span>
          </div>

          {reviewOrders.length === 0 ? (
            <div className="flex h-[220px] items-center justify-center rounded-xl border border-dashed border-crypto-border bg-crypto-bg/40 px-4 text-center text-sm text-gray-500">暂无 K 线复盘数据，策略产生真实成交后会展示 B/S 成交点</div>
          ) : (
            <>
              <div className="relative min-h-[150px] overflow-hidden rounded-xl border border-crypto-border bg-crypto-bg px-4 py-5">
                <div className="absolute left-8 right-8 top-1/2 h-px bg-gradient-to-r from-blue-500/25 via-gray-500/40 to-purple-500/25" />
                <div className="relative grid h-full min-h-[110px]" style={{ gridTemplateColumns: `repeat(${reviewOrders.length}, minmax(0, 1fr))` }}>
                  {reviewOrders.map((order, index) => {
                    const isBuy = order.side === 'buy';
                    return (
                      <div key={`${order.symbol}-marker-${index}`} className="flex min-w-0 flex-col items-center justify-center gap-2 px-1">
                        <div
                          className={clsx(
                            'flex h-10 w-10 items-center justify-center rounded-full border text-xs font-black shadow-lg',
                            isBuy
                              ? 'border-emerald-400/50 bg-emerald-500/20 text-emerald-200 shadow-emerald-950/20'
                              : 'border-red-400/50 bg-red-500/20 text-red-200 shadow-red-950/20',
                          )}
                        >
                          {isBuy ? 'B' : 'S'}
                        </div>
                        <div className="max-w-full truncate text-center text-[11px] font-semibold text-gray-300">
                          {formatSymbolLabel(order.symbol, order.name)}
                        </div>
                        <div className={clsx('text-xs font-bold tabular-nums', isBuy ? 'text-up' : 'text-down')}>
                          {isBuy ? 'B' : 'S'} · {formatNumber(order.price)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                {reviewOrders.map((order, index) => {
                  const isBuy = order.side === 'buy';
                  return (
                    <div key={`${order.symbol}-review-${index}`} className="rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 text-sm">
                      <div className="flex items-center justify-between gap-2">
                        <span className="min-w-0 truncate text-gray-300">{formatSymbolLabel(order.symbol, order.name)}</span>
                        <span className={clsx('shrink-0 font-bold', isBuy ? 'text-up' : 'text-down')}>
                          {isBuy ? 'B' : 'S'} · {formatNumber(order.price)}
                        </span>
                      </div>
                      <div className="mt-1 flex items-center justify-between gap-2 text-[10px] text-gray-600">
                        <span className="truncate">{order.created_at || '模拟成交'}</span>
                        <span className="shrink-0 tabular-nums">{order.quantity} 股</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title="账户曲线"
        subtitle="按当前时间范围展示策略权益、现金和收益采样。"
        icon={<TrendingUp className="mt-0.5 h-5 w-5 shrink-0 text-blue-400" />}
      >
        <div className="h-[38vh] min-h-[280px] max-h-[520px] w-full">
          <ReactECharts option={equityOption} style={{ height: '100%', width: '100%' }} />
        </div>
      </CollapsibleSection>

      <div className="rounded-xl border border-crypto-border bg-crypto-card p-4">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
          <ShieldCheck className="h-4 w-4 text-green-400" />
          风控状态
        </h3>
        <div className="grid gap-3 md:grid-cols-3">
          {[
            ['熔断保护', returnPct <= -5 ? '预警' : '正常', returnPct <= -5 ? 'text-red-300 border-red-500/40 bg-red-500/10' : 'text-green-300 border-green-500/30 bg-green-500/10'],
            ['仓位边界', `${positions.length} 个持仓`, 'text-blue-200 border-blue-500/30 bg-blue-500/10'],
            ['资金约束', `现金 ¥${formatNumber(account.cash)}`, 'text-gray-300 border-crypto-border bg-white/[0.03]'],
          ].map(([title, status, className]) => (
            <div key={title} className="rounded-lg border border-crypto-border bg-crypto-bg/45 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold text-white">{title}</span>
                <span className={clsx('rounded-full border px-2 py-0.5 text-[10px] font-semibold', className)}>{status}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function MarketDetailHeader({
  selectedSymbol,
  selectedName,
  price,
  changePercent,
  activeRange = '1D',
  onRangeChange,
}: {
  selectedSymbol: string;
  selectedName?: string | null;
  price?: number | null;
  changePercent?: number | null;
  activeRange?: string;
  onRangeChange?: (range: string) => void;
}) {
  return (
    <div className="flex flex-col gap-4 border-b border-crypto-border px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-xl border border-crypto-border bg-crypto-bg p-1">
          <span className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white">A股</span>
          <span className="px-3 py-1.5 text-xs font-semibold text-gray-500">板块</span>
        </div>
        <div className="inline-flex min-w-[190px] items-center gap-2 rounded-xl border border-crypto-border bg-crypto-bg px-3 py-2">
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-amber-500 text-[10px] font-bold text-black">A</span>
          <span className="truncate text-sm font-semibold text-white">{selectedName || selectedSymbol}</span>
          <span className="text-xs text-gray-500">{selectedSymbol}</span>
        </div>
        <div className="flex items-baseline gap-3">
          <span className={clsx('text-3xl font-bold tabular-nums', marketToneClass(changePercent, 'text-blue-300'))}>¥{formatNumber(price)}</span>
          <span className={clsx('text-sm font-semibold', marketToneClass(changePercent))}>
            {signedPercent(changePercent)}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {['分时', '1D', '5D', '1M', '3M', '1Y'].map((item) => (
          <button
            type="button"
            key={item}
            onClick={() => onRangeChange?.(item)}
            className={clsx(
              'rounded-lg px-3 py-1.5 text-xs font-semibold',
              activeRange === item ? 'bg-blue-600 text-white' : 'text-gray-500 hover:bg-white/5',
            )}
          >
            {item}
          </button>
        ))}
      </div>
    </div>
  );
}
