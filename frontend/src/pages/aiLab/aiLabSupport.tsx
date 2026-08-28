import { useRef } from 'react';
import {
  Activity, AlertCircle, Beaker, Calendar, CheckCircle2, Cpu,
  FileText, GitBranch, RotateCcw, Target, Wrench, Zap,
  type LucideIcon,
} from 'lucide-react';

export interface GoalCriteria {
  min_sharpe_ratio: number;
  max_drawdown_pct: number;
  min_win_rate_pct: number;
  min_total_return_pct: number;
  min_total_trades: number;
  min_profit_factor: number;
}

export interface EvalScores {
  risk_control: number;
  profitability: number;
  robustness: number;
  strategy_logic: number;
  originality: number;
  total_score: number;
}

export interface SprintContract {
  strategy_direction: string;
  key_indicators: string[];
  entry_logic_desc: string;
  exit_logic_desc: string;
  risk_management_desc: string;
  acceptance_criteria: string[];
  action: string;
}

export interface Iteration {
  iteration: number;
  strategy_name: string;
  strategy_code: string;
  reasoning: string;
  backtest_metrics: Record<string, any>;
  eval_scores: EvalScores | null;
  analysis: string;
  suggestions: string[];
  score: number;
  meets_goal: boolean;
  error: string;
  created_at: string;
  contract: SprintContract | null;
  action: string;
}

export interface StrategySpec {
  market_analysis: string;
  strategy_candidates: { name: string; description: string; pros: string; cons: string }[];
  recommended_approach: string;
  risk_considerations: string;
  iteration_plan: string;
}

export interface TaskInfo {
  task_id: string;
  id?: string;
  status: string;
  stage?: string;
  stage_label?: string;
  market_type: MarketType;
  symbol: string;
  timeframe: string;
  backtest_start: string;
  backtest_end: string;
  current_iteration: number;
  max_iterations: number;
  best_iteration: number | null;
  best_score: number | null;
  best_metrics: Record<string, any> | null;
  best_eval_scores: EvalScores | null;
  goal: GoalCriteria;
  user_prompt: string;
  llm_model?: string;
  strategy_spec: StrategySpec | null;
  iterations_count: number;
  created_at: string;
  updated_at: string;
}

export interface StrategyOptimizerConfig {
  enabled: boolean;
  interval_hours: number;
  low_return_pct: number;
  trial_hours: number;
  trial_success_return_pct: number;
  running: boolean;
  llm_model?: string | null;
  next_run_at?: string | null;
  last_started_at?: string | null;
  last_finished_at?: string | null;
  last_error?: string | null;
}

export interface StrategyOptimizationRun {
  id: string;
  source_strategy_id: number;
  source_strategy_name: string;
  candidate_strategy_id?: number | null;
  agent_task_id?: string | null;
  stage: string;
  status: string;
  source_return_pct?: number | null;
  candidate_return_pct?: number | null;
  source_snapshot?: Record<string, any>;
  ai_analysis?: string | null;
  backtest_result?: Record<string, any>;
  trial_started_at?: string | null;
  trial_checked_at?: string | null;
  trial_finished_at?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  events?: { id?: number; ts: string; stage: string; message: string; detail?: Record<string, any> }[];
}

export interface AutoAgentSchedulerConfig {
  enabled: boolean;
  interval_minutes: number;
  symbols: string[];
  use_hermes_agent: boolean;
  max_candidates: number;
  preferred_direction?: string;
  last_run_at?: string | null;
  last_run_id?: string | null;
  last_error?: string | null;
  builtin_objective?: string;
}

export interface AutonomousTraderConfig {
  symbolsText: string;
  promptText: string;
  restrictSymbols: boolean;
  llmProvider: string;
  llmModel: string;
  tradeDirection: string;
  maxLeverageCap: number;
  maxSinglePositionPct: number;
  maxTotalExposurePct: number;
  maxPositions: number;
  minDecisionIntervalSec: number;
  maxDecisionIntervalSec: number;
  maxTradesPerHour: number;
  probeSizePct: number;
  initialCapital: number;
}

export interface AutonomousTraderInstance {
  strategy_id: number;
  name: string;
  status: string;
  config: Record<string, any>;
  symbols: string[];
  dashboard?: Record<string, any>;
  recent_trades?: Record<string, any>[];
  events?: Record<string, any>[];
  created_at?: string;
  updated_at?: string;
}

export interface LLMModelConfig {
  model: string;
  default_model?: string;
  models?: string[];
  free_tier_models?: string[];
  model_fallback_enabled?: boolean;
  api_key_configured?: boolean;
  api_key_source?: string;
}

export interface OrbitAutoPostConfig {
  enabled: boolean;
  accountId: string;
  intervalMinutes: number;
  minMarginRoiPct: number;
  maxPostsPerRun: number;
  cooldownHours: number;
  maxPostsPerDay: number;
  llmModel: string;
  copyStyle: string;
  publishMode: string;
  truthfulOnly: boolean;
  running?: boolean;
  lastStartedAt?: string | null;
  lastFinishedAt?: string | null;
  lastPostedAt?: string | null;
  lastError?: string | null;
  lastSkipReason?: string | null;
}

export interface OrbitCandidate {
  id: string;
  dedupe_key?: string;
  account_id?: string;
  symbol: string;
  base?: string;
  side: 'long' | 'short' | string;
  side_label?: string;
  leverage?: number;
  size?: number;
  entry_price?: number;
  mark_price?: number;
  unrealized_pnl?: number;
  margin?: number;
  notional_usdt?: number;
  margin_roi_pct?: number;
  threshold_pct?: number;
  eligible?: boolean;
  blocked_reason?: string;
  source?: string;
}

export interface OrbitPostRecord {
  id: string;
  candidate?: OrbitCandidate;
  content?: string;
  status?: string;
  url?: string;
  error?: string;
  created_at?: string;
}

export interface OrbitLoginStatus {
  publish_mode?: string;
  available?: boolean;
  logged_in?: boolean;
  status?: string;
  url?: string;
  error?: string;
}

export type AutonomousNumericConfigKey = Exclude<keyof AutonomousTraderConfig, 'symbolsText' | 'promptText' | 'restrictSymbols' | 'llmProvider' | 'llmModel' | 'tradeDirection'>;
export type AssistantTab = 'research' | 'optimizer' | 'autonomous' | 'auto-agent' | 'orbit-post';
export type MarketType = 'spot' | 'swap';

/* ---------- constants ---------- */

export const HUNTER_GOAL: GoalCriteria = {
  min_sharpe_ratio: 1.2,
  max_drawdown_pct: 5.0,
  min_win_rate_pct: 55.0,
  min_total_return_pct: 30.0,
  min_total_trades: 30,
  min_profit_factor: 1.25,
};

export const AI_RESEARCH_MARKETS: Record<MarketType, { label: string; shortLabel: string; badge: string; symbols: string[]; scope: string; note: string }> = {
  spot: {
    label: 'A 股主板 / 创业板股票池',
    shortLabel: '股票',
    badge: '[股票]',
    symbols: [
      '600519.SH', '000001.SZ', '300750.SZ', '601318.SH', '000858.SZ',
      '002594.SZ', '600036.SH', '000333.SZ', '601899.SH', '002475.SZ',
    ],
    scope: '只做多或空仓，适合趋势、反转、成交量和截面强弱因子验证。',
    note: '策略保存后默认进入 A 股模拟盘，不会进入实盘。',
  },
  swap: {
    label: 'A 股 ETF / 宽基指数池',
    shortLabel: 'ETF',
    badge: '[ETF]',
    symbols: [
      '510300.SH', '510500.SH', '159915.SZ', '588000.SH', '512480.SH',
      '512880.SH', '159919.SZ', '510050.SH',
    ],
    scope: '只做多，按人民币名义和 100 股整手执行，当前仅模拟盘。',
    note: 'AI 生成策略必须遵守 T+1 / 100 股，不触发真实券商下单。',
  },
};

export const AI_RESEARCH_SCOPE_LABEL = AI_RESEARCH_MARKETS.spot.label;
export const AI_RESEARCH_DEFAULT_TIMEFRAME = '15m';
export const TOP30_USDT_SWAP_SYMBOLS = [
  '600519.SH', '000001.SZ', '300750.SZ', '601318.SH', '000858.SZ',
  '002594.SZ', '600036.SH', '000333.SZ', '601899.SH', '002475.SZ',
  '600900.SH', '601012.SH', '000725.SZ', '002415.SZ', '600276.SH',
  '601088.SH', '600030.SH', '000568.SZ', '002371.SZ', '600809.SH',
];
export const AUTONOMOUS_HERMES_MODEL = 'gpt-5.5';
export const AUTONOMOUS_HERMES_PROVIDER_LABEL = 'Hermes / Codex';
export const AUTONOMOUS_DEFAULT_OPERATOR_PROMPT = [
  '只做 A 股模拟盘，禁止实盘、禁止真实账户、禁止任何真实下单建议。',
  '目标是在严格 paper 风控内提升模拟盘净收益：只允许做多或空仓，遵守 T+1、100 股整手、涨跌停和人民币资金。',
  '优先从高流动性 A 股中选择强弱分化清晰、成交活跃、能覆盖佣金印花税的标的；避开停牌、ST、一字板无法成交或流动性过差的标的。',
  '无持仓且候选信号有优势时不要长期观望；仓位由信号强度、波动和止损空间决定，并严格遵守单笔上限、总敞口和持仓数量。',
  '做多优先选择相对强势、上行动量、突破后回踩确认的标的；持仓后优势消失或反向信号出现时及时减仓/卖出。',
  '每次决策必须用中文 reason 说明标的选择、方向、观察窗口、风险和下一次检查间隔。',
].join('\n');
export const AUTONOMOUS_TRADER_DEFAULT_CONFIG: AutonomousTraderConfig = {
  symbolsText: TOP30_USDT_SWAP_SYMBOLS.join(', '),
  promptText: AUTONOMOUS_DEFAULT_OPERATOR_PROMPT,
  restrictSymbols: false,
  llmProvider: 'hermes',
  llmModel: AUTONOMOUS_HERMES_MODEL,
  tradeDirection: 'long_short',
  maxLeverageCap: 10,
  maxSinglePositionPct: 60,
  maxTotalExposurePct: 360,
  maxPositions: 6,
  minDecisionIntervalSec: 60,
  maxDecisionIntervalSec: 180,
  maxTradesPerHour: 6,
  probeSizePct: 10,
  initialCapital: 100,
};

export const ACTIVE_TASK_STORAGE_KEY = 'bitpro.aiLab.activeTaskId';
export const AUTO_AGENT_RUN_STORAGE_KEY = 'bitpro.aiLab.autoAgentRunId';
export const AUTO_AGENT_DEFAULT_SYMBOLS = TOP30_USDT_SWAP_SYMBOLS;
export const AUTO_AGENT_DEFAULT_SCHEDULER: AutoAgentSchedulerConfig = {
  enabled: false,
  interval_minutes: 60,
  symbols: AUTO_AGENT_DEFAULT_SYMBOLS,
  use_hermes_agent: true,
  max_candidates: 5,
  preferred_direction: 'auto',
};

export const ORBIT_AUTO_POST_DEFAULT_CONFIG: OrbitAutoPostConfig = {
  enabled: false,
  accountId: 'default',
  intervalMinutes: 10,
  minMarginRoiPct: 5,
  maxPostsPerRun: 1,
  cooldownHours: 24,
  maxPostsPerDay: 12,
  llmModel: '',
  copyStyle: '吸引跟单但不夸大，不承诺收益，突出真实仓位、方向、收益率和风险控制。',
  publishMode: 'orbit_web',
  truthfulOnly: true,
};

export function getTaskId(task: Pick<TaskInfo, 'task_id' | 'id'> | null | undefined): string {
  return task?.task_id || task?.id || '';
}

export function isActiveResearchTask(task: Pick<TaskInfo, 'status'> | null | undefined): boolean {
  return task?.status === 'running' || task?.status === 'pending';
}

export function readRememberedTaskId(): string {
  try {
    return window.localStorage.getItem(ACTIVE_TASK_STORAGE_KEY) || '';
  } catch {
    return '';
  }
}

export function rememberTaskId(taskId: string): void {
  if (!taskId) return;
  try {
    window.localStorage.setItem(ACTIVE_TASK_STORAGE_KEY, taskId);
  } catch {
    /* localStorage may be unavailable in private mode */
  }
}

export function forgetRememberedTaskId(taskId?: string): void {
  try {
    if (!taskId || window.localStorage.getItem(ACTIVE_TASK_STORAGE_KEY) === taskId) {
      window.localStorage.removeItem(ACTIVE_TASK_STORAGE_KEY);
    }
  } catch {
    /* localStorage may be unavailable in private mode */
  }
}

export function normalizeTaskInfo(raw: any): TaskInfo {
  const taskId = String(raw?.task_id || raw?.id || '');
  const marketType: MarketType = raw?.market_type === 'swap' ? 'swap' : 'spot';
  return {
    task_id: taskId,
    id: raw?.id || taskId,
    status: raw?.status || 'unknown',
    stage: raw?.stage,
    stage_label: raw?.stage_label,
    market_type: marketType,
    symbol: raw?.symbol || AI_RESEARCH_SCOPE_LABEL,
    timeframe: raw?.timeframe || AI_RESEARCH_DEFAULT_TIMEFRAME,
    backtest_start: raw?.backtest_start || '',
    backtest_end: raw?.backtest_end || '',
    current_iteration: Number(raw?.current_iteration ?? 0),
    max_iterations: Number(raw?.max_iterations ?? 0),
    best_iteration: raw?.best_iteration ?? null,
    best_score: raw?.best_score ?? null,
    best_metrics: raw?.best_metrics ?? null,
    best_eval_scores: raw?.best_eval_scores ?? null,
    goal: raw?.goal || raw?.goal_criteria || HUNTER_GOAL,
    user_prompt: raw?.user_prompt || '',
    llm_model: raw?.llm_model || '',
    strategy_spec: raw?.strategy_spec || null,
    iterations_count: Number(raw?.iterations_count ?? 0),
    created_at: raw?.created_at || '',
    updated_at: raw?.updated_at || '',
  };
}

export function compactTaskTitle(value?: string | null, maxLength = 30): string {
  const normalized = String(value || '')
    .replace(/[#*`>]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!normalized) return '';
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}...` : normalized;
}

export function getResearchTaskTitle(task: TaskInfo): string {
  const spec = task.strategy_spec;
  const firstCandidate = spec?.strategy_candidates?.find((candidate) => candidate?.name)?.name;
  const title =
    compactTaskTitle(firstCandidate, 28)
    || compactTaskTitle(spec?.recommended_approach, 32)
    || compactTaskTitle(spec?.market_analysis, 32);

  if (title) return title;
  if (task.status === 'running' || task.status === 'pending') return '策略规格书生成中';
  if (task.status === 'interrupted') return '可继续的策略研发任务';
  return `${AI_RESEARCH_MARKETS[task.market_type || 'spot'].shortLabel}高流动性市场策略研发`;
}

export function researchMarketForTask(task: TaskInfo | null | undefined): MarketType {
  return task?.market_type === 'swap' ? 'swap' : 'spot';
}

export function apiSymbolScopeForMarket(marketType: MarketType): string {
  if (marketType === 'swap') {
    return [
      '510300.SH', '510500.SH', '159915.SZ', '588000.SH',
      '512480.SH', '512880.SH', '159919.SZ', '510050.SH',
    ].join(',');
  }
  return [
    '600519.SH', '000001.SZ', '300750.SZ', '601318.SH', '000858.SZ',
    '002594.SZ', '600036.SH', '000333.SZ', '601899.SH', '002475.SZ',
  ].join(',');
}

export function autonomousSymbolsFromText(value: string): string[] {
  return String(value || '')
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function autonomousStatusText(status?: string): string {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'running') return '运行中';
  if (normalized === 'paused') return '已暂停';
  if (normalized === 'stopped') return '已停止';
  if (normalized === 'error') return '错误';
  return status || '--';
}

export function autonomousStatusClass(status?: string): string {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'running') return 'bg-blue-500/15 text-blue-300';
  if (normalized === 'paused') return 'bg-orange-500/15 text-orange-300';
  if (normalized === 'error') return 'bg-red-500/15 text-red-300';
  return 'bg-gray-500/15 text-gray-400';
}

export function formatAutonomousLogTime(value: unknown): string {
  if (value == null || value === '') return '';
  const numberValue = typeof value === 'number' ? value : Number(value);
  const date = Number.isFinite(numberValue)
    ? new Date(numberValue < 1_000_000_000_000 ? numberValue * 1000 : numberValue)
    : new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value || '');
  const pad = (x: number, len = 2) => String(x).padStart(len, '0');
  return [
    date.getFullYear(),
    '-',
    pad(date.getMonth() + 1),
    '-',
    pad(date.getDate()),
    ' ',
    pad(date.getHours()),
    ':',
    pad(date.getMinutes()),
    ':',
    pad(date.getSeconds()),
    '.',
    String(Math.floor(date.getMilliseconds() / 100)),
  ].join('');
}

export function autonomousLogLevelClass(level?: string): string {
  const normalized = String(level || '').toLowerCase();
  if (normalized === 'error') return 'text-red-400';
  if (normalized === 'warning' || normalized === 'warn') return 'text-yellow-400';
  if (normalized === 'success') return 'text-green-400';
  return 'text-cyan-400';
}

export function autonomousLogTitle(evt: Record<string, any>): string {
  return String(
    evt.decision_label
    || evt.decision
    || evt.message
    || evt.summary
    || evt.type
    || '策略日志',
  );
}

export function autonomousLogSummary(evt: Record<string, any>): string {
  const detail = evt.detail || evt.details || {};
  const reasons = Array.isArray(detail.reasons) ? detail.reasons.join('；') : '';
  return String(
    evt.summary
    || evt.message
    || detail.reason
    || detail.message
    || reasons
    || '--',
  );
}

export function autonomousLogChips(evt: Record<string, any>): { label: string; value: string }[] {
  const detail = evt.detail || evt.details || {};
  const decision = detail.decision || {};
  const chips: { label: string; value: string }[] = [];
  if (decision.symbol) chips.push({ label: '标的', value: String(decision.symbol) });
  if (decision.action) chips.push({ label: '动作', value: String(decision.action) });
  if (decision.observation_window || decision.analysis_window) {
    chips.push({ label: '观察', value: String(decision.observation_window || decision.analysis_window) });
  }
  if (decision.leverage != null) chips.push({ label: '杠杆', value: `${decision.leverage}x` });
  if (decision.size_pct != null) {
    const sizePct = Number(decision.size_pct);
    chips.push({ label: '仓位', value: Number.isFinite(sizePct) ? `${(sizePct * 100).toFixed(1)}%` : String(decision.size_pct) });
  }
  if (Array.isArray(detail.reasons) && detail.reasons.length > 0) chips.push({ label: '拦截', value: `${detail.reasons.length} 条` });
  return chips;
}

export function normalizeAutonomousNumericInput(value: string): string {
  const raw = String(value || '').trim().replace(/[^\d.]/g, '');
  if (!raw) return '';
  const [intPart, ...decimalParts] = raw.split('.');
  const integer = intPart.replace(/^0+(?=\d)/, '') || '0';
  if (decimalParts.length === 0) return integer;
  return `${integer}.${decimalParts.join('')}`;
}

export function formatAutonomousCompactNumber(value: unknown, digits = 0): string {
  const n = finiteNumber(value);
  if (n == null) return '--';
  return Number.isInteger(n) ? String(n) : n.toFixed(digits).replace(/\.?0+$/, '');
}

export function formatAutonomousPercentConfig(value: unknown): string {
  const n = finiteNumber(value);
  if (n == null) return '--';
  const pct = Math.abs(n) <= 1 ? n * 100 : n;
  return `${formatAutonomousCompactNumber(pct, 2)}%`;
}

export function formatAutonomousSeconds(value: unknown): string {
  const n = finiteNumber(value);
  if (n == null) return '--';
  return `${formatAutonomousCompactNumber(n, 1)}s`;
}

export function formatAutonomousLeverage(value: unknown): string {
  const formatted = formatAutonomousCompactNumber(value, 1);
  return formatted === '--' ? '--' : `${formatted}x`;
}

export function formatAutonomousUsdt(value: unknown): string {
  const formatted = formatAutonomousCompactNumber(value, 2);
  return formatted === '--' ? '--' : `${formatted} CNY`;
}

export function autonomousInstanceConfigItems(config: Record<string, any> = {}): { label: string; value: string }[] {
  return [
    {
      label: '提供方',
      value: String(config.llm_provider || config.ai_provider || 'dashscope') === 'hermes' ? AUTONOMOUS_HERMES_PROVIDER_LABEL : 'DashScope / Qwen',
    },
    {
      label: 'AI模型',
      value: String(config.llm_model || config.model || '全局默认'),
    },
    {
      label: '方向',
      value: String(config.trade_direction || '') === 'short_only' ? '只做空' : '多空双向',
    },
    {
      label: '观察窗口',
      value: config.market_observation_mode === 'ai_decides' ? 'AI 自选' : '系统默认',
    },
    {
      label: '最大杠杆',
      value: formatAutonomousLeverage(config.max_leverage_cap ?? config.max_leverage),
    },
    {
      label: '单笔仓位',
      value: `≤ ${formatAutonomousPercentConfig(config.max_single_position_pct)}`,
    },
    {
      label: '总风险敞口',
      value: `≤ ${formatAutonomousPercentConfig(config.max_total_exposure_pct)}`,
    },
    {
      label: '最多持仓',
      value: `≤ ${formatAutonomousCompactNumber(config.max_positions)} 个`,
    },
    {
      label: '决策间隔',
      value: `≥ ${formatAutonomousSeconds(config.min_decision_interval_sec)}`,
    },
    {
      label: '最长等待',
      value: `≤ ${formatAutonomousSeconds(config.max_decision_interval_sec)}`,
    },
    {
      label: '试单仓位',
      value: formatAutonomousPercentConfig(config.probe_size_pct),
    },
    {
      label: '每小时交易',
      value: `≤ ${formatAutonomousCompactNumber(config.max_trades_per_hour)} 笔`,
    },
    {
      label: '初始资金',
      value: formatAutonomousUsdt(config.initial_capital),
    },
  ];
}

export function autonomousPercentInputValue(value: unknown, fallback: number): number {
  const n = finiteNumber(value);
  if (n == null) return fallback;
  return Math.abs(n) <= 1 ? n * 100 : n;
}

export function autonomousConfigFromInstance(
  instance: AutonomousTraderInstance,
  fallbackModel = '',
): AutonomousTraderConfig {
  const cfg = instance.config || {};
  const symbols = (
    Array.isArray(cfg.contract_trade_symbols) ? cfg.contract_trade_symbols :
    Array.isArray(cfg.trade_symbols) ? cfg.trade_symbols :
    Array.isArray(cfg.symbols) ? cfg.symbols :
    instance.symbols || []
  );
  return {
    symbolsText: symbols.join(', '),
    promptText: String(cfg.operator_prompt || '').trim(),
    restrictSymbols: Boolean(cfg.restrict_symbols),
    llmProvider: String(cfg.llm_provider || cfg.ai_provider || AUTONOMOUS_TRADER_DEFAULT_CONFIG.llmProvider).trim(),
    llmModel: String(cfg.llm_model || cfg.model || fallbackModel || '').trim(),
    tradeDirection: String(cfg.trade_direction || AUTONOMOUS_TRADER_DEFAULT_CONFIG.tradeDirection).trim(),
    maxLeverageCap: finiteNumber(cfg.max_leverage_cap ?? cfg.max_leverage) ?? AUTONOMOUS_TRADER_DEFAULT_CONFIG.maxLeverageCap,
    maxSinglePositionPct: autonomousPercentInputValue(cfg.max_single_position_pct, AUTONOMOUS_TRADER_DEFAULT_CONFIG.maxSinglePositionPct),
    maxTotalExposurePct: autonomousPercentInputValue(cfg.max_total_exposure_pct, AUTONOMOUS_TRADER_DEFAULT_CONFIG.maxTotalExposurePct),
    maxPositions: finiteNumber(cfg.max_positions) ?? AUTONOMOUS_TRADER_DEFAULT_CONFIG.maxPositions,
    minDecisionIntervalSec: finiteNumber(cfg.min_decision_interval_sec) ?? AUTONOMOUS_TRADER_DEFAULT_CONFIG.minDecisionIntervalSec,
    maxDecisionIntervalSec: finiteNumber(cfg.max_decision_interval_sec) ?? AUTONOMOUS_TRADER_DEFAULT_CONFIG.maxDecisionIntervalSec,
    maxTradesPerHour: finiteNumber(cfg.max_trades_per_hour) ?? AUTONOMOUS_TRADER_DEFAULT_CONFIG.maxTradesPerHour,
    probeSizePct: autonomousPercentInputValue(cfg.probe_size_pct, AUTONOMOUS_TRADER_DEFAULT_CONFIG.probeSizePct),
    initialCapital: finiteNumber(cfg.initial_capital) ?? AUTONOMOUS_TRADER_DEFAULT_CONFIG.initialCapital,
  };
}

export const autonomousParameterCardClass =
  'rounded-xl border border-white/10 bg-slate-900/70 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]';
export const autonomousRiskParameterCardClass =
  'rounded-xl border border-white/10 bg-slate-900/70 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] transition-colors hover:border-yellow-500/35 hover:bg-slate-900/90';

export const HUNTER_PROMPT = `你是 AI 策略猎手。目标不是写一个模板策略，而是主动提出多种可能赚钱的市场假设并迭代验证。

请优先探索这些方向的组合，但不要局限于单一模板：
1. 趋势突破、动量延续、回调再入场。
2. 均值回归、超买超卖反转、波动率收缩后扩张。
3. 多周期过滤、成交量确认、假突破过滤。
4. Kairos 预测、资金费率、多空比、持仓量、盘口等外生因子可用时作为过滤条件；不可用时显式降级为纯 K 线因子，不允许 mock。

每一轮都要和上一轮明显不同：改变交易假设、信号组合、退出规则或风控方式。重点寻找手续费和滑点后仍稳健的策略。避免只靠少数大单盈利、交易次数过少、参数过拟合或未来函数。`;

export const ACTION_LABELS: Record<string, { label: string; color: string }> = {
  new: { label: '全新', color: 'text-blue-400' },
  refine: { label: '优化', color: 'text-green-400' },
  pivot: { label: '转向', color: 'text-orange-400' },
};

export type PipelineStepId = 'planner' | 'contract' | 'strategist' | 'backtester' | 'evaluator';
export type PipelineStepStatus = 'done' | 'active' | 'waiting' | 'paused' | 'failed';

export interface PipelineStep {
  id: PipelineStepId;
  title: string;
  detail: string;
  Icon: LucideIcon;
  textClass: string;
  activeClass: string;
  doneClass: string;
}

export const PIPELINE_STEPS: PipelineStep[] = [
  {
    id: 'planner',
    title: '规划',
    detail: '生成策略规格书',
    Icon: FileText,
    textClass: 'text-blue-300',
    activeClass: 'border-blue-400 bg-blue-500/15 text-blue-200 shadow-[0_0_0_1px_rgba(96,165,250,0.22)]',
    doneClass: 'border-blue-500/40 bg-blue-500/10 text-blue-300',
  },
  {
    id: 'contract',
    title: '合约准备',
    detail: '确定本轮验收标准',
    Icon: GitBranch,
    textClass: 'text-yellow-300',
    activeClass: 'border-yellow-400 bg-yellow-500/15 text-yellow-100 shadow-[0_0_0_1px_rgba(250,204,21,0.22)]',
    doneClass: 'border-yellow-500/40 bg-yellow-500/10 text-yellow-300',
  },
  {
    id: 'strategist',
    title: '策略生成',
    detail: '生成 BaseStrategy 代码',
    Icon: Zap,
    textClass: 'text-green-300',
    activeClass: 'border-green-400 bg-green-500/15 text-green-100 shadow-[0_0_0_1px_rgba(74,222,128,0.22)]',
    doneClass: 'border-green-500/40 bg-green-500/10 text-green-300',
  },
  {
    id: 'backtester',
    title: '回测',
    detail: '执行统一回测',
    Icon: Cpu,
    textClass: 'text-purple-300',
    activeClass: 'border-purple-400 bg-purple-500/15 text-purple-100 shadow-[0_0_0_1px_rgba(192,132,252,0.22)]',
    doneClass: 'border-purple-500/40 bg-purple-500/10 text-purple-300',
  },
  {
    id: 'evaluator',
    title: '评估',
    detail: '独立评分与反馈',
    Icon: Target,
    textClass: 'text-orange-300',
    activeClass: 'border-orange-400 bg-orange-500/15 text-orange-100 shadow-[0_0_0_1px_rgba(251,146,60,0.22)]',
    doneClass: 'border-orange-500/40 bg-orange-500/10 text-orange-300',
  },
];

export const STAGE_STEP_INDEX: Record<string, number> = {
  planner: 0,
  planner_done: 1,
  contract: 1,
  strategist: 2,
  backtester: 3,
  evaluator: 4,
};

export const OPTIMIZER_STEPS: PipelineStep[] = [
  {
    id: 'planner',
    title: '监控',
    detail: '扫描运行中的模拟策略',
    Icon: Activity,
    textClass: 'text-blue-300',
    activeClass: 'border-blue-400 bg-blue-500/15 text-blue-100 shadow-[0_0_0_1px_rgba(96,165,250,0.22)]',
    doneClass: 'border-blue-500/40 bg-blue-500/10 text-blue-300',
  },
  {
    id: 'contract',
    title: '诊断',
    detail: '收集收益、成交和诊断日志',
    Icon: AlertCircle,
    textClass: 'text-yellow-300',
    activeClass: 'border-yellow-400 bg-yellow-500/15 text-yellow-100 shadow-[0_0_0_1px_rgba(250,204,21,0.22)]',
    doneClass: 'border-yellow-500/40 bg-yellow-500/10 text-yellow-300',
  },
  {
    id: 'strategist',
    title: '优化',
    detail: 'AI 调参并生成候选代码',
    Icon: Wrench,
    textClass: 'text-green-300',
    activeClass: 'border-green-400 bg-green-500/15 text-green-100 shadow-[0_0_0_1px_rgba(74,222,128,0.22)]',
    doneClass: 'border-green-500/40 bg-green-500/10 text-green-300',
  },
  {
    id: 'backtester',
    title: '回测',
    detail: '统一回测验证候选',
    Icon: Beaker,
    textClass: 'text-purple-300',
    activeClass: 'border-purple-400 bg-purple-500/15 text-purple-100 shadow-[0_0_0_1px_rgba(192,132,252,0.22)]',
    doneClass: 'border-purple-500/40 bg-purple-500/10 text-purple-300',
  },
  {
    id: 'evaluator',
    title: '试运行',
    detail: '候选模拟盘试运行 4h',
    Icon: Target,
    textClass: 'text-orange-300',
    activeClass: 'border-orange-400 bg-orange-500/15 text-orange-100 shadow-[0_0_0_1px_rgba(251,146,60,0.22)]',
    doneClass: 'border-orange-500/40 bg-orange-500/10 text-orange-300',
  },
];

export const OPTIMIZER_STAGE_INDEX: Record<string, number> = {
  monitor: 0,
  diagnose: 1,
  optimize: 2,
  backtest: 3,
  trial: 4,
  replace: 4,
};

export function formatDateInputValue(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || '--';
  return date.toLocaleString('zh-CN', { hour12: false });
}

export function getRecentOneYearDateRange(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end);
  start.setFullYear(start.getFullYear() - 1);
  return {
    start: formatDateInputValue(start),
    end: formatDateInputValue(end),
  };
}

export const DEFAULT_BACKTEST_DATE_RANGE = getRecentOneYearDateRange();

export interface DatePickerFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  min?: string;
  max?: string;
}

export function DatePickerField({ label, value, onChange, disabled, min, max }: DatePickerFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const displayValue = value ? value.replace(/-/g, '/') : '选择日期';

  const openPicker = () => {
    if (disabled) return;
    const input = inputRef.current as (HTMLInputElement & { showPicker?: () => void }) | null;
    if (!input) return;
    try {
      input.showPicker?.();
    } catch {
      input.focus();
      input.click();
    }
  };

  return (
    <div>
      <label className="text-xs text-gray-400">{label}</label>
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-label={label}
        aria-disabled={disabled}
        onClick={openPicker}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            openPicker();
          }
        }}
        className={`relative mt-1 flex h-9 w-full items-center justify-between rounded-lg border border-crypto-border bg-crypto-bg px-3 text-left text-sm text-white transition focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500/60 ${
          disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:border-blue-500/60'
        }`}
      >
        <span className={value ? 'truncate' : 'truncate text-gray-500'}>{displayValue}</span>
        <Calendar size={16} className="shrink-0 text-gray-400" />
        <input
          ref={inputRef}
          type="date"
          value={value}
          min={min}
          max={max}
          onChange={(e) => onChange(e.target.value)}
          onClick={(e) => {
            try {
              (e.currentTarget as HTMLInputElement & { showPicker?: () => void }).showPicker?.();
            } catch {
              /* native picker fallback */
            }
          }}
          disabled={disabled}
          aria-label={label}
          tabIndex={-1}
          className="pointer-events-none absolute inset-0 opacity-0"
        />
      </div>
    </div>
  );
}

export function finiteNumber(value: unknown): number | null {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function fmtNumber(value: unknown, digits = 2): string {
  const n = finiteNumber(value);
  return n == null ? '--' : n.toFixed(digits);
}

export function fmtPct(value: unknown, digits = 1): string {
  const n = finiteNumber(value);
  return n == null ? '--' : `${n.toFixed(digits)}%`;
}

export function fmtSignedPct(value: unknown, digits = 2): string {
  const n = finiteNumber(value);
  if (n == null) return '--';
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`;
}

export function fmtSignedUsd(value: unknown, digits = 2): string {
  const n = finiteNumber(value);
  if (n == null) return '--';
  return `${n >= 0 ? '+$' : '-$'}${Math.abs(n).toFixed(digits)}`;
}

export function unwrapApiData<T>(raw: any): T {
  if (raw && typeof raw === 'object' && 'success' in raw && 'data' in raw) {
    return raw.data as T;
  }
  return raw as T;
}

export function normalizeOrbitAutoPostConfig(raw: any): OrbitAutoPostConfig {
  return {
    ...ORBIT_AUTO_POST_DEFAULT_CONFIG,
    enabled: Boolean(raw?.enabled),
    accountId: String(raw?.account_id ?? raw?.accountId ?? ORBIT_AUTO_POST_DEFAULT_CONFIG.accountId),
    intervalMinutes: Number(raw?.interval_minutes ?? raw?.intervalMinutes ?? ORBIT_AUTO_POST_DEFAULT_CONFIG.intervalMinutes),
    minMarginRoiPct: Number(raw?.min_margin_roi_pct ?? raw?.minMarginRoiPct ?? ORBIT_AUTO_POST_DEFAULT_CONFIG.minMarginRoiPct),
    maxPostsPerRun: Number(raw?.max_posts_per_run ?? raw?.maxPostsPerRun ?? ORBIT_AUTO_POST_DEFAULT_CONFIG.maxPostsPerRun),
    cooldownHours: Number(raw?.cooldown_hours ?? raw?.cooldownHours ?? ORBIT_AUTO_POST_DEFAULT_CONFIG.cooldownHours),
    maxPostsPerDay: Number(raw?.max_posts_per_day ?? raw?.maxPostsPerDay ?? ORBIT_AUTO_POST_DEFAULT_CONFIG.maxPostsPerDay),
    llmModel: String(raw?.llm_model ?? raw?.llmModel ?? ''),
    copyStyle: String(raw?.copy_style ?? raw?.copyStyle ?? ORBIT_AUTO_POST_DEFAULT_CONFIG.copyStyle),
    publishMode: String(raw?.publish_mode ?? raw?.publishMode ?? 'orbit_web'),
    truthfulOnly: Boolean(raw?.truthful_only ?? raw?.truthfulOnly ?? true),
    running: Boolean(raw?.running),
    lastStartedAt: raw?.last_started_at ?? raw?.lastStartedAt ?? null,
    lastFinishedAt: raw?.last_finished_at ?? raw?.lastFinishedAt ?? null,
    lastPostedAt: raw?.last_posted_at ?? raw?.lastPostedAt ?? null,
    lastError: raw?.last_error ?? raw?.lastError ?? null,
    lastSkipReason: raw?.last_skip_reason ?? raw?.lastSkipReason ?? null,
  };
}

export function orbitConfigPayload(config: OrbitAutoPostConfig): Record<string, unknown> {
  return {
    enabled: config.enabled,
    account_id: config.accountId,
    interval_minutes: config.intervalMinutes,
    min_margin_roi_pct: config.minMarginRoiPct,
    max_posts_per_run: config.maxPostsPerRun,
    cooldown_hours: config.cooldownHours,
    max_posts_per_day: config.maxPostsPerDay,
    llm_model: config.llmModel,
    copy_style: config.copyStyle,
  };
}

export type MetricTone = 'gain' | 'loss' | 'good' | 'bad' | 'info' | 'neutral';

export const MIN_CANDIDATE_SCORE = 50;

export function signedMarketTone(value: unknown): MetricTone {
  const n = finiteNumber(value);
  if (n == null || n === 0) return 'neutral';
  return n > 0 ? 'gain' : 'loss';
}

export function targetTone(passed: boolean): MetricTone {
  return passed ? 'info' : 'neutral';
}

export function riskTone(passed: boolean): MetricTone {
  return passed ? 'info' : 'loss';
}

export function metricToneTextClass(tone: MetricTone): string {
  if (tone === 'gain' || tone === 'good') return 'text-red-400';
  if (tone === 'loss' || tone === 'bad') return 'text-green-400';
  if (tone === 'info') return 'text-blue-400';
  return 'text-gray-300';
}

export function getCandidateQuality(iteration: Iteration | null | undefined, goal: GoalCriteria): { ok: boolean; issues: string[] } {
  if (!iteration) return { ok: false, issues: ['未选择候选'] };
  const issues: string[] = [];
  const metrics = iteration.backtest_metrics || {};
  const totalReturn = finiteNumber(metrics.total_return_pct);
  const sharpe = finiteNumber(metrics.sharpe_ratio);
  const drawdown = finiteNumber(metrics.max_drawdown_pct);
  const trades = finiteNumber(metrics.total_trades);
  const profitFactor = finiteNumber(metrics.profit_factor);
  const score = finiteNumber(iteration.score);
  const drawdownLimit = Math.max(goal.max_drawdown_pct * 3, 15);

  if (iteration.error) issues.push('回测或评估存在错误');
  if (!iteration.strategy_code?.trim()) issues.push('缺少可保存策略代码');
  if (totalReturn == null || totalReturn <= 0) issues.push('收益率未转正');
  if (sharpe == null || sharpe <= 0) issues.push('夏普比率未转正');
  if (profitFactor == null || profitFactor < 1) issues.push('盈亏比低于 1');
  if (trades == null || trades < goal.min_total_trades) issues.push(`交易数少于 ${goal.min_total_trades}`);
  if (drawdown == null || drawdown > drawdownLimit) issues.push(`最大回撤超过 ${drawdownLimit.toFixed(1)}%`);
  if (score == null || score < MIN_CANDIDATE_SCORE) issues.push(`评分低于 ${MIN_CANDIDATE_SCORE}`);

  return { ok: issues.length === 0, issues };
}

export function getPipelineStepStatus(
  task: TaskInfo | null,
  stepIndex: number,
  iterationCount: number,
): PipelineStepStatus {
  if (!task) return 'waiting';
  if (task.status === 'failed') return stepIndex === 0 ? 'failed' : 'paused';
  if (task.status === 'completed') return 'done';

  const activeIndex = STAGE_STEP_INDEX[task.stage || ''] ?? (task.status === 'pending' ? 0 : -1);
  if (task.status === 'running' || task.status === 'pending') {
    if (stepIndex < activeIndex) return 'done';
    if (stepIndex === activeIndex) return 'active';
    return 'waiting';
  }

  const completedUntil = iterationCount > 0 ? PIPELINE_STEPS.length - 1 : task.strategy_spec ? 0 : -1;
  if (stepIndex <= completedUntil) return 'done';
  return 'paused';
}

export function getPipelineRoundLabel(task: TaskInfo | null): string {
  if (!task) return '等待启动';
  if (task.status === 'completed') {
    const doneRounds = Math.max(task.iterations_count, task.current_iteration + 1);
    return `已完成 ${doneRounds || 0} 轮`;
  }
  const max = Math.max(task.max_iterations || 0, 1);
  const current = Math.min(Math.max((task.current_iteration ?? 0) + 1, 1), max);
  return `第 ${current} 轮 / 共 ${max} 轮`;
}

export function getPipelineTone(status: PipelineStepStatus, step: PipelineStep): string {
  if (status === 'active') return step.activeClass;
  if (status === 'done') return step.doneClass;
  if (status === 'failed') return 'border-red-500/50 bg-red-500/10 text-red-300';
  if (status === 'paused') return 'border-gray-700 bg-crypto-card text-gray-500';
  return 'border-gray-800 bg-crypto-card text-gray-600';
}

export function getPipelineStatusLabel(status: PipelineStepStatus): string {
  if (status === 'active') return '进行中';
  if (status === 'done') return '已完成';
  if (status === 'failed') return '失败';
  if (status === 'paused') return '已暂停';
  return '等待';
}

export function ResearchPipeline({
  task,
  iterations,
  stageText,
  specOpen,
  onToggleSpec,
}: {
  task: TaskInfo | null;
  iterations: Iteration[];
  stageText: string;
  specOpen: boolean;
  onToggleSpec: () => void;
}) {
  const isTaskRunning = task?.status === 'running' || task?.status === 'pending';
  const headerTone =
    task?.status === 'failed' ? 'text-red-300' :
    task?.status === 'completed' ? 'text-green-300' :
    isTaskRunning ? 'text-blue-300' :
    'text-gray-400';

  return (
    <div className="rounded-lg border border-crypto-border bg-crypto-bg/60 p-3">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-gray-600">策略研发流水线</p>
          <h4 className="mt-1 text-sm font-semibold text-gray-200">{getPipelineRoundLabel(task)}</h4>
        </div>
        <div className={`min-w-0 rounded-full border border-current/20 px-2.5 py-1 text-right text-[11px] ${headerTone}`}>
          <span className="block max-w-[220px] truncate">{stageText}</span>
        </div>
      </div>

      <div className="space-y-0.5">
        {PIPELINE_STEPS.map((step, index) => {
          const status = getPipelineStepStatus(task, index, iterations.length);
          const StepIcon = status === 'done' ? CheckCircle2 : step.Icon;
          const tone = getPipelineTone(status, step);
          const isActive = status === 'active';
          const showSpecAction = index === 0 && Boolean(task?.strategy_spec) && status === 'done';
          const nextStatus = index < PIPELINE_STEPS.length - 1
            ? getPipelineStepStatus(task, index + 1, iterations.length)
            : 'waiting';
          const connectorClass =
            status === 'done' && nextStatus !== 'waiting'
              ? 'bg-blue-400/35'
              : status === 'active'
                ? 'bg-current/35'
                : 'bg-gray-800';

          return (
            <div key={step.id}>
              <div className={`flex items-center gap-3 rounded-lg border px-3 py-2.5 transition-colors ${tone}`}>
                <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-current/25 ${isActive ? 'animate-pulse' : ''}`}>
                  <StepIcon size={16} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-center justify-between gap-2">
                    <span className={`truncate text-sm font-semibold ${status === 'waiting' || status === 'paused' ? '' : step.textClass}`}>
                      {step.title}
                    </span>
                    <span className="shrink-0 rounded-full bg-black/20 px-2 py-0.5 text-[10px] text-current/75">
                      {getPipelineStatusLabel(status)}
                    </span>
                  </div>
                  <p className="mt-0.5 truncate text-[11px] text-current/55">{step.detail}</p>
                </div>
                {showSpecAction && (
                  <button
                    type="button"
                    onClick={onToggleSpec}
                    className="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-blue-400/35 bg-blue-500/10 px-3 text-[11px] font-semibold text-blue-200 transition hover:border-blue-300 hover:bg-blue-500/15"
                  >
                    <FileText size={12} />
                    {specOpen ? '隐藏规格书' : '查看规格书'}
                  </button>
                )}
              </div>
              {index < PIPELINE_STEPS.length - 1 && (
                <div className="ml-[28px] h-4 w-px">
                  <div className={`h-full w-px ${connectorClass}`} />
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex items-center justify-center gap-2 text-[11px] text-gray-600">
        <RotateCcw size={13} className={isTaskRunning ? 'animate-spin text-blue-400' : ''} />
        <span>每轮完成后将根据评估反馈进入下一轮</span>
      </div>
    </div>
  );
}

export function getOptimizerStepStatus(run: StrategyOptimizationRun | null, index: number): PipelineStepStatus {
  if (!run) return 'waiting';
  if (run.status === 'failed') return index <= (OPTIMIZER_STAGE_INDEX[run.stage] ?? 0) ? 'failed' : 'paused';
  if (run.status === 'cancelled') return index <= (OPTIMIZER_STAGE_INDEX[run.stage] ?? 0) ? 'paused' : 'waiting';
  if (run.status === 'replaced') return 'done';

  const activeIndex = OPTIMIZER_STAGE_INDEX[run.stage] ?? 0;
  if (index < activeIndex) return 'done';
  if (index === activeIndex) return 'active';
  return 'waiting';
}

export function StrategyOptimizerPipeline({ run }: { run: StrategyOptimizationRun | null }) {
  return (
    <div className="grid grid-cols-1 gap-2 lg:grid-cols-5">
      {OPTIMIZER_STEPS.map((step, index) => {
        const status = getOptimizerStepStatus(run, index);
        const StepIcon = status === 'done' ? CheckCircle2 : step.Icon;
        const tone = getPipelineTone(status, step);
        return (
          <div key={step.title} className={`rounded-lg border px-3 py-2.5 ${tone}`}>
            <div className="flex items-center gap-2">
              <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-current/25 ${status === 'active' ? 'animate-pulse' : ''}`}>
                <StepIcon size={15} />
              </div>
              <div className="min-w-0">
                <div className={`truncate text-sm font-semibold ${status === 'waiting' || status === 'paused' ? '' : step.textClass}`}>
                  {step.title}
                </div>
                <div className="truncate text-[11px] text-current/55">{step.detail}</div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function optimizerStatusText(run?: StrategyOptimizationRun | null): string {
  if (!run) return '暂无优化任务';
  if (run.status === 'trial_running') return '候选试运行中';
  if (run.status === 'replaced') return '已替换';
  if (run.status === 'failed') return '失败';
  if (run.status === 'cancelled') return '已取消';
  if (run.status === 'running') return '优化中';
  return run.status || '未知';
}

export function getOptimizerRunTitle(run?: StrategyOptimizationRun | null): string {
  if (!run) return '';
  return run.source_strategy_name || (run.source_strategy_id ? `源策略 #${run.source_strategy_id}` : run.id);
}

export function canDeleteOptimizerRun(run: StrategyOptimizationRun): boolean {
  return run.status !== 'running' && run.status !== 'trial_running';
}

/* ---------- Radar chart (pure CSS/SVG) ---------- */

export function RadarChart({ scores }: { scores: EvalScores }) {
  const dims = [
    { key: 'risk_control', label: '风控' },
    { key: 'profitability', label: '盈利' },
    { key: 'robustness', label: '稳健' },
    { key: 'strategy_logic', label: '逻辑' },
    { key: 'originality', label: '原创' },
  ] as const;
  const n = dims.length;
  const cx = 80, cy = 80, R = 60;

  const angleOf = (i: number) => (Math.PI * 2 * i) / n - Math.PI / 2;
  const ptAt = (i: number, r: number) => {
    const a = angleOf(i);
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  };

  const gridLevels = [0.25, 0.5, 0.75, 1.0];
  const values = dims.map((d) => (scores[d.key as keyof EvalScores] as number) / 100);
  const dataPoints = values.map((v, i) => ptAt(i, R * v));
  const dataPath = dataPoints.map((p, i) => (i === 0 ? `M${p[0]},${p[1]}` : `L${p[0]},${p[1]}`)).join(' ') + 'Z';

  return (
    <svg viewBox="0 0 160 160" className="w-full max-w-[200px] mx-auto">
      {gridLevels.map((lv) => {
        const pts = dims.map((_, i) => ptAt(i, R * lv));
        const d = pts.map((p, i) => (i === 0 ? `M${p[0]},${p[1]}` : `L${p[0]},${p[1]}`)).join(' ') + 'Z';
        return <path key={lv} d={d} fill="none" stroke="#374151" strokeWidth={0.5} />;
      })}
      {dims.map((_, i) => {
        const [ex, ey] = ptAt(i, R);
        return <line key={i} x1={cx} y1={cy} x2={ex} y2={ey} stroke="#374151" strokeWidth={0.5} />;
      })}
      <path d={dataPath} fill="rgba(59,130,246,0.2)" stroke="#3b82f6" strokeWidth={1.5} />
      {dataPoints.map((p, i) => (
        <circle key={i} cx={p[0]} cy={p[1]} r={2.5} fill="#3b82f6" />
      ))}
      {dims.map((d, i) => {
        const [lx, ly] = ptAt(i, R + 16);
        return (
          <text key={d.key} x={lx} y={ly} textAnchor="middle" dominantBaseline="central"
            className="fill-gray-400 text-[9px]">
            {d.label} {Math.round(scores[d.key as keyof EvalScores] as number)}
          </text>
        );
      })}
    </svg>
  );
}

/* ---------- Main component ---------- */


export function metricToneCardClass(tone: MetricTone): string {
  if (tone === 'gain' || tone === 'good') return 'border-red-500/35';
  if (tone === 'loss' || tone === 'bad') return 'border-green-500/35';
  if (tone === 'info') return 'border-blue-500/30';
  return 'border-crypto-border';
}

export function MetricCard({ label, value, tone = 'neutral' }: { label: string; value: any; tone?: MetricTone }) {
  return (
    <div data-metric-card className={`bg-crypto-card border rounded-xl p-3 ${metricToneCardClass(tone)}`}>
      <div className="text-[10px] text-gray-500">{label}</div>
      <div className={`text-sm font-bold mt-0.5 ${metricToneTextClass(tone)}`}>
        {value ?? '--'}
      </div>
    </div>
  );
}
