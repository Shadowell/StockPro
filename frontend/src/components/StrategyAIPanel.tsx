import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import clsx from 'clsx';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
  Play,
  RefreshCw,
  Sparkles,
  Square,
  Trash2,
} from 'lucide-react';
import {
  createAgentTask,
  deleteAgentTask,
  getAgentResearchConfig,
  getAgentTask,
  listAgentIterations,
  listAgentTasks,
  promoteAgentIteration,
  startAgentTask,
  stopAgentTask,
} from '../api/client';
import { OperatorStatePanel } from './OperatorShell';
import { marketToneClass } from '../utils/marketColors';
import type {
  AgentEvalScores,
  AgentGoalCriteria,
  AgentIteration,
  AgentResearchConfig,
  AgentTaskDetail,
  AgentTaskSummary,
} from '../types';

// ---------------------------------------------------------------------------
// 本地格式化工具（比率统一转百分比展示，全部数字使用 tabular-nums）
// ---------------------------------------------------------------------------

const isNil = (value: number | null | undefined): value is null | undefined =>
  value === null || value === undefined || Number.isNaN(Number(value));

const formatPercent = (value: number | null | undefined, digits = 2): string =>
  isNil(value) ? '--' : `${(Number(value) * 100).toFixed(digits)}%`;

const formatNumber = (value: number | null | undefined, digits = 2): string =>
  isNil(value) ? '--' : Number(value).toFixed(digits);

const formatInteger = (value: number | null | undefined): string =>
  isNil(value) ? '--' : String(Math.round(Number(value)));

const formatDateTime = (value?: string | null): string => {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  return `${date.getMonth() + 1}/${date.getDate()} ${hh}:${mm}`;
};

const getErrorMessage = (error: unknown, fallback: string): string =>
  error instanceof Error ? error.message : fallback;

// ---------------------------------------------------------------------------
// 常量与展示元数据
// ---------------------------------------------------------------------------

const DEFAULT_GOAL: AgentGoalCriteria = {
  min_sharpe: 0.5,
  max_drawdown: 0.15,
  min_win_rate: 0.4,
  min_return: 0.02,
  min_trades: 5,
  min_profit_loss_ratio: 1.0,
};

const goalFields: Array<{
  key: keyof AgentGoalCriteria;
  label: string;
  step: number;
  hint: string;
}> = [
  { key: 'min_sharpe', label: '最小夏普 ≥', step: 0.1, hint: '0.5' },
  { key: 'max_drawdown', label: '最大回撤 ≤', step: 0.01, hint: '0.15 = 15%' },
  { key: 'min_win_rate', label: '最小胜率 ≥', step: 0.05, hint: '0.40 = 40%' },
  { key: 'min_return', label: '最小收益 ≥', step: 0.01, hint: '0.02 = 2%' },
  { key: 'min_trades', label: '最小交易数 ≥', step: 1, hint: '5' },
  { key: 'min_profit_loss_ratio', label: '最小盈亏比 ≥', step: 0.1, hint: '1.0' },
];

const iterationRoundOptions = [3, 6, 9, 12];

type TaskStatus = AgentTaskSummary['status'];

const statusMeta: Record<TaskStatus, { label: string; chip: string; dot: string }> = {
  pending: { label: '待启动', chip: 'border-slate-600/60 bg-slate-500/10 text-slate-300', dot: 'bg-slate-400' },
  running: { label: '运行中', chip: 'border-blue-500/40 bg-blue-500/10 text-blue-300', dot: 'animate-pulse bg-blue-400' },
  completed: { label: '已完成', chip: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300', dot: 'bg-emerald-400' },
  failed: { label: '失败', chip: 'border-red-500/40 bg-red-500/10 text-red-300', dot: 'bg-red-400' },
  stopped: { label: '已停止', chip: 'border-slate-600/60 bg-slate-500/10 text-slate-400', dot: 'bg-slate-500' },
};

const iterationActionMeta: Record<AgentIteration['action'], { label: string; chip: string }> = {
  new: { label: '新策略', chip: 'border-blue-500/30 bg-blue-500/10 text-blue-300' },
  refine: { label: '迭代优化', chip: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' },
  pivot: { label: '方向调整', chip: 'border-amber-500/30 bg-amber-500/10 text-amber-300' },
};

const evalDimensions: Array<{ key: keyof Omit<AgentEvalScores, 'total_score'>; label: string }> = [
  { key: 'risk_control', label: '风控' },
  { key: 'profitability', label: '盈利' },
  { key: 'robustness', label: '稳健' },
  { key: 'strategy_logic', label: '逻辑' },
  { key: 'originality', label: '独创' },
];

/** 评分条按 0-10 刻度截断展示，避免异常值撑破布局。 */
const scoreBarWidth = (value: number | null | undefined): string =>
  `${Math.max(0, Math.min(10, isNil(value) ? 0 : Number(value))) * 10}%`;

// ---------------------------------------------------------------------------
// 小型展示组件
// ---------------------------------------------------------------------------

function TaskStatusChip({ status }: { status: TaskStatus }) {
  const meta = statusMeta[status] ?? statusMeta.pending;
  return (
    <span
      className={clsx('inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-semibold', meta.chip)}
      data-task-status={status}
    >
      <span className={clsx('h-1.5 w-1.5 rounded-full', meta.dot)} />
      {meta.label}
    </span>
  );
}

function DetailBlock({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-crypto-border bg-crypto-bg p-3">
      <dt className="text-[10px] font-semibold text-slate-500">{label}</dt>
      <dd className="mt-1 whitespace-pre-wrap text-[11px] leading-5 text-slate-300">{children}</dd>
    </div>
  );
}

function MetricItem({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <span className="inline-flex items-baseline gap-1">
      <span className="text-[10px] text-slate-500">{label}</span>
      <span className={clsx('font-mono text-[11px] font-semibold tabular-nums', className)}>{value}</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// 主面板
// ---------------------------------------------------------------------------

export function StrategyAIPanel() {
  // 研发配置（LLM 可用性 + 数据环境默认值）
  const [config, setConfig] = useState<AgentResearchConfig | null>(null);
  const [configState, setConfigState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [configError, setConfigError] = useState('');

  // 任务列表
  const [tasks, setTasks] = useState<AgentTaskSummary[]>([]);
  const [tasksState, setTasksState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [tasksError, setTasksError] = useState('');

  // 选中任务详情与迭代
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AgentTaskDetail | null>(null);
  const [iterations, setIterations] = useState<AgentIteration[]>([]);
  const [detailState, setDetailState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [detailError, setDetailError] = useState('');

  // 创建表单
  const [formName, setFormName] = useState('');
  const [formPrompt, setFormPrompt] = useState('');
  const [goal, setGoal] = useState<AgentGoalCriteria>(DEFAULT_GOAL);
  const [maxIterations, setMaxIterations] = useState(6);
  const [creating, setCreating] = useState(false);

  // 操作反馈
  const [actionMessage, setActionMessage] = useState('');
  const [actionError, setActionError] = useState('');
  const [actionBusyId, setActionBusyId] = useState<string | null>(null);
  const [promotingIteration, setPromotingIteration] = useState<number | null>(null);
  const [promotedInfo, setPromotedInfo] = useState<{
    iteration: number;
    versionId: string;
    name: string;
    version: number;
  } | null>(null);
  const [expandedCodeId, setExpandedCodeId] = useState<string | null>(null);

  const llmAvailable = configState === 'ready' && config?.llm_available === true;

  const loadConfig = useCallback(async () => {
    setConfigState('loading');
    setConfigError('');
    try {
      const data = await getAgentResearchConfig();
      setConfig(data);
      setConfigState('ready');
    } catch (error) {
      setConfigState('error');
      setConfigError(getErrorMessage(error, 'AI 研发配置读取失败'));
    }
  }, []);

  const loadTasks = useCallback(async () => {
    setTasksError('');
    try {
      const data = await listAgentTasks(50);
      const list = data.tasks || [];
      setTasks(list);
      setTasksState('ready');
      setSelectedTaskId((current) =>
        current && list.some((item) => item.id === current) ? current : list[0]?.id ?? null,
      );
    } catch (error) {
      setTasksState('error');
      setTasksError(getErrorMessage(error, '研发任务列表读取失败'));
    }
  }, []);

  useEffect(() => {
    void loadConfig();
    void loadTasks();
  }, [loadConfig, loadTasks]);

  const loadDetail = useCallback(async (taskId: string, isFirstLoad: boolean) => {
    if (isFirstLoad) setDetailState('loading');
    try {
      const [taskDetail, iterationData] = await Promise.all([
        getAgentTask(taskId),
        listAgentIterations(taskId),
      ]);
      setDetail(taskDetail);
      setIterations(iterationData.iterations || []);
      setDetailState('ready');
      setDetailError('');
      // 详情比列表新，回写列表行保持一致
      setTasks((prev) => prev.map((item) => (item.id === taskDetail.id ? { ...item, ...taskDetail } : item)));
    } catch (error) {
      if (isFirstLoad) {
        setDetail(null);
        setIterations([]);
      }
      setDetailState('error');
      setDetailError(getErrorMessage(error, '任务详情读取失败'));
    }
  }, []);

  useEffect(() => {
    if (!selectedTaskId) {
      setDetail(null);
      setIterations([]);
      setDetailState('idle');
      return;
    }
    void loadDetail(selectedTaskId, true);
  }, [selectedTaskId, loadDetail]);

  // 选中任务 pending/running 时每 3s 轮询，终态自动停止
  const selectedStatus: TaskStatus | null = detail?.id === selectedTaskId
    ? detail.status
    : tasks.find((item) => item.id === selectedTaskId)?.status ?? null;
  const pollingActive = selectedTaskId !== null && (selectedStatus === 'pending' || selectedStatus === 'running');

  useEffect(() => {
    if (!pollingActive || !selectedTaskId) return;
    const timer = window.setInterval(() => {
      void loadDetail(selectedTaskId, false);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [pollingActive, selectedTaskId, loadDetail]);

  const sortedIterations = useMemo(
    () => [...iterations].sort((a, b) => b.iteration - a.iteration),
    [iterations],
  );

  // -------------------------------------------------------------------------
  // 操作
  // -------------------------------------------------------------------------

  const patchTaskInList = useCallback((taskId: string, patch: Partial<AgentTaskSummary>) => {
    setTasks((prev) => prev.map((item) => (item.id === taskId ? { ...item, ...patch } : item)));
    setDetail((prev) => (prev && prev.id === taskId ? { ...prev, ...patch } : prev));
  }, []);

  const handleCreate = async () => {
    if (!formName.trim()) {
      setActionError('请填写任务名称');
      return;
    }
    setCreating(true);
    setActionError('');
    setActionMessage('');
    setPromotedInfo(null);
    try {
      const result = await createAgentTask({
        name: formName.trim(),
        user_prompt: formPrompt.trim() || undefined,
        goal: { ...goal },
        max_iterations: maxIterations,
        llm_model: config?.default_model ?? null,
      });
      setActionMessage(`任务「${result.task.name}」已创建，点击任务行内的「启动」开始研发。`);
      setFormName('');
      setFormPrompt('');
      setSelectedTaskId(result.task.id);
      await loadTasks();
    } catch (error) {
      setActionError(getErrorMessage(error, '创建研发任务失败'));
    } finally {
      setCreating(false);
    }
  };

  const handleStart = async (task: AgentTaskSummary) => {
    setActionBusyId(task.id);
    setActionError('');
    setActionMessage('');
    try {
      const result = await startAgentTask(task.id);
      patchTaskInList(task.id, result.task);
      setActionMessage(`任务「${task.name}」已启动，研发过程会自动轮询更新。`);
    } catch (error) {
      setActionError(getErrorMessage(error, '启动研发任务失败'));
    } finally {
      setActionBusyId(null);
    }
  };

  const handleStop = async (task: AgentTaskSummary) => {
    if (!window.confirm(`确认停止任务「${task.name}」？当前迭代会被中断。`)) return;
    setActionBusyId(task.id);
    setActionError('');
    setActionMessage('');
    try {
      const result = await stopAgentTask(task.id);
      patchTaskInList(task.id, result.task);
      setActionMessage(`任务「${task.name}」已停止。`);
    } catch (error) {
      setActionError(getErrorMessage(error, '停止研发任务失败'));
    } finally {
      setActionBusyId(null);
    }
  };

  const handleDelete = async (task: AgentTaskSummary) => {
    if (!window.confirm(`确认删除任务「${task.name}」及其迭代记录？该操作不可恢复。`)) return;
    setActionBusyId(task.id);
    setActionError('');
    setActionMessage('');
    try {
      await deleteAgentTask(task.id);
      if (selectedTaskId === task.id) setSelectedTaskId(null);
      await loadTasks();
      setActionMessage(`任务「${task.name}」已删除。`);
    } catch (error) {
      setActionError(getErrorMessage(error, '删除研发任务失败'));
    } finally {
      setActionBusyId(null);
    }
  };

  const handlePromote = async (iteration: AgentIteration) => {
    if (!detail) return;
    setPromotingIteration(iteration.iteration);
    setActionError('');
    try {
      const result = await promoteAgentIteration(detail.id, iteration.iteration);
      setPromotedInfo({
        iteration: result.iteration,
        versionId: result.strategy_version.id,
        name: result.strategy_version.name,
        version: result.strategy_version.version,
      });
      setActionMessage(
        `第 ${result.iteration} 轮已采纳为策略版本：${result.strategy_version.name} v${result.strategy_version.version}`,
      );
      patchTaskInList(detail.id, { promoted_strategy_version_id: result.strategy_version.id });
    } catch (error) {
      setActionError(getErrorMessage(error, '采纳策略版本失败'));
    } finally {
      setPromotingIteration(null);
    }
  };

  // -------------------------------------------------------------------------
  // 渲染
  // -------------------------------------------------------------------------

  const defaults = config?.defaults;

  return (
    <section className="space-y-4" data-testid="strategy-ai-panel">
      {/* 头部：标题 + LLM 可用性 */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-crypto-border bg-crypto-card px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-purple-500/15 text-purple-300">
            <Sparkles className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-white">AI 策略研发</h2>
            <p className="truncate text-[11px] text-slate-500">
              多智能体闭环：规划 → 写码 → 沙箱校验 → 快速回测 → 多维评估 → 迭代
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {configState === 'loading' && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-crypto-border bg-crypto-bg px-2.5 py-1 text-[10px] text-slate-400">
              <Loader2 className="h-3 w-3 animate-spin" />
              AI 能力检测中…
            </span>
          )}
          {configState === 'ready' && (
            <span
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold',
                llmAvailable
                  ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                  : 'border-red-500/40 bg-red-500/10 text-red-300',
              )}
              data-testid="agent-llm-chip"
            >
              <span className={clsx('h-1.5 w-1.5 rounded-full', llmAvailable ? 'bg-emerald-400' : 'bg-red-400')} />
              {llmAvailable ? `LLM 可用 · ${config?.default_model || '默认模型'}` : 'LLM 不可用'}
            </span>
          )}
          <button
            type="button"
            onClick={() => {
              void loadConfig();
              void loadTasks();
            }}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-crypto-border bg-crypto-bg px-2.5 text-[11px] font-semibold text-slate-400 transition-colors hover:text-slate-200"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            刷新
          </button>
        </div>
      </div>

      {/* 提示条 */}
      {configState === 'error' && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-xs text-red-300">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="flex-1">AI 研发配置读取失败：{configError}</span>
          <button
            type="button"
            onClick={() => void loadConfig()}
            className="rounded-lg border border-red-500/40 px-2.5 py-1 text-[11px] font-semibold text-red-100 hover:bg-red-500/20"
          >
            重试
          </button>
        </div>
      )}
      {configState === 'ready' && !llmAvailable && (
        <div
          className="flex items-start gap-2.5 rounded-xl border border-amber-500/30 bg-amber-500/[0.08] px-4 py-3 text-xs leading-5 text-amber-200"
          data-testid="agent-llm-warning"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
          <span>QWEN_API_KEY 未配置，无法发起研发。配置后端 QWEN_API_KEY 并重启服务即可解锁。</span>
        </div>
      )}
      {actionMessage && (
        <div
          className="flex items-start gap-2.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-xs leading-5 text-emerald-300"
          role="status"
        >
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="flex-1">{actionMessage}</span>
          {promotedInfo && (
            <span className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[10px] font-semibold tabular-nums">
              策略版本 {promotedInfo.name} v{promotedInfo.version}（第 {promotedInfo.iteration} 轮）
            </span>
          )}
        </div>
      )}
      {actionError && (
        <div className="flex items-start gap-2.5 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-xs leading-5 text-red-300" role="alert">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="flex-1">{actionError}</span>
        </div>
      )}

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
        {/* 左列：创建表单 + 任务列表 */}
        <div className="space-y-4">
          <div className="rounded-xl border border-crypto-border bg-crypto-card p-4" data-testid="agent-create-form">
            <h3 className="mb-3 text-xs font-semibold text-slate-300">发起研发任务</h3>
            <label className="block">
              <span className="mb-1.5 block text-[11px] font-medium text-slate-500">
                任务名称 <span className="text-red-400">*</span>
              </span>
              <input
                value={formName}
                onChange={(event) => setFormName(event.target.value)}
                placeholder="例如：低波红利防守策略"
                disabled={!llmAvailable}
                className="w-full rounded-lg border border-crypto-border bg-[#0D1117] px-3 py-2 text-xs text-white outline-none focus:border-blue-500 disabled:opacity-50"
              />
            </label>
            <label className="mt-3 block">
              <span className="mb-1.5 block text-[11px] font-medium text-slate-500">研究目标</span>
              <textarea
                value={formPrompt}
                onChange={(event) => setFormPrompt(event.target.value)}
                rows={3}
                placeholder="描述期望的策略方向、持仓风格或风控要求（可选）"
                disabled={!llmAvailable}
                className="w-full resize-none rounded-lg border border-crypto-border bg-[#0D1117] px-3 py-2 text-xs leading-5 text-white outline-none focus:border-blue-500 disabled:opacity-50"
              />
            </label>
            <div className="mt-3">
              <span className="mb-1.5 block text-[11px] font-medium text-slate-500">绩效目标</span>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {goalFields.map((field) => (
                  <label key={field.key} className="block">
                    <span className="mb-1 block text-[10px] text-slate-500">{field.label}</span>
                    <input
                      type="number"
                      step={field.step}
                      value={goal[field.key]}
                      disabled={!llmAvailable}
                      onChange={(event) => {
                        const parsed = Number(event.target.value);
                        setGoal((prev) => ({ ...prev, [field.key]: Number.isNaN(parsed) ? prev[field.key] : parsed }));
                      }}
                      title={field.hint}
                      className="w-full rounded-lg border border-crypto-border bg-[#0D1117] px-2 py-1.5 font-mono text-[11px] tabular-nums text-slate-200 outline-none focus:border-blue-500 disabled:opacity-50"
                    />
                  </label>
                ))}
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-end gap-3">
              <label className="block">
                <span className="mb-1.5 block text-[11px] font-medium text-slate-500">迭代轮数</span>
                <select
                  value={maxIterations}
                  disabled={!llmAvailable}
                  onChange={(event) => setMaxIterations(Number(event.target.value))}
                  className="rounded-lg border border-crypto-border bg-[#0D1117] px-3 py-2 font-mono text-[11px] tabular-nums text-slate-200 outline-none focus:border-blue-500 disabled:opacity-50"
                >
                  {iterationRoundOptions.map((option) => (
                    <option key={option} value={option}>{option} 轮</option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                onClick={() => void handleCreate()}
                disabled={!llmAvailable || creating || !formName.trim()}
                data-testid="agent-create-submit"
                className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-purple-600 px-4 text-xs font-semibold text-white transition-colors hover:bg-purple-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                {creating ? '创建中…' : '创建任务'}
              </button>
            </div>
            {defaults && (
              <p className="mt-3 rounded-lg border border-crypto-border bg-crypto-bg px-2.5 py-2 text-[10px] leading-5 text-slate-500">
                数据环境（服务端默认）：快照 {defaults.dataset_snapshot_name || `#${defaults.dataset_snapshot_id ?? '--'}`} · 股票池{' '}
                {defaults.universe_code || '--'}（{defaults.symbols?.length ?? 0} 只）· 基准 {defaults.benchmark_code || '--'} · 窗口{' '}
                <span className="tabular-nums">{defaults.start_date || '--'} ~ {defaults.end_date || '--'}</span>
              </p>
            )}
          </div>

          {/* 任务列表 */}
          <div className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card" data-testid="agent-task-list">
            <div className="flex items-center justify-between border-b border-crypto-border px-4 py-2.5">
              <h3 className="text-xs font-semibold text-slate-300">
                研发任务 <span className="ml-1 font-mono text-[10px] tabular-nums text-slate-600">{tasks.length}</span>
              </h3>
              <button
                type="button"
                onClick={() => void loadTasks()}
                title="刷新任务列表"
                className="rounded-lg border border-crypto-border bg-crypto-bg p-1.5 text-slate-500 transition-colors hover:text-slate-300"
              >
                <RefreshCw className={clsx('h-3.5 w-3.5', tasksState === 'loading' && 'animate-spin')} />
              </button>
            </div>
            <div className="max-h-[520px] divide-y divide-slate-800 overflow-y-auto">
              {tasksState === 'loading' && (
                <div className="px-4 py-10 text-center text-xs text-slate-500">正在读取研发任务…</div>
              )}
              {tasksState === 'error' && (
                <div className="px-4 py-8 text-center">
                  <p className="text-xs text-red-300">{tasksError}</p>
                  <button
                    type="button"
                    onClick={() => void loadTasks()}
                    className="mt-3 rounded-lg border border-red-500/30 px-3 py-1.5 text-[11px] font-semibold text-red-100 hover:bg-red-500/10"
                  >
                    重试
                  </button>
                </div>
              )}
              {tasksState === 'ready' && tasks.length === 0 && (
                <div className="px-4 py-10 text-center text-xs leading-5 text-slate-500">
                  暂无研发任务
                  <br />
                  在上方填写目标并发起第一个任务。
                </div>
              )}
              {tasks.map((task) => {
                const active = task.id === selectedTaskId;
                const busy = actionBusyId === task.id;
                return (
                  <div
                    key={task.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedTaskId(task.id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        setSelectedTaskId(task.id);
                      }
                    }}
                    data-testid="agent-task-row"
                    className={clsx(
                      'cursor-pointer px-4 py-3 transition-colors',
                      active ? 'bg-blue-500/[0.08]' : 'hover:bg-white/[0.03]',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <TaskStatusChip status={task.status} />
                        <span className="truncate text-xs font-semibold text-slate-200">{task.name}</span>
                      </div>
                      {task.best_score !== null && task.best_score !== undefined && (
                        <span className="shrink-0 font-mono text-[11px] font-bold tabular-nums text-amber-300">
                          {task.best_score.toFixed(1)}
                        </span>
                      )}
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[10px] text-slate-500">
                      <span className="max-w-[150px] truncate">{task.stage_label || task.stage || '待启动'}</span>
                      <span className="font-mono tabular-nums">
                        {task.iteration_count}/{task.max_iterations} 轮
                      </span>
                      <span className="ml-auto font-mono tabular-nums">{formatDateTime(task.updated_at)}</span>
                    </div>
                    <div className="mt-2 flex items-center gap-1.5" onClick={(event) => event.stopPropagation()}>
                      {busy && <Loader2 className="h-3 w-3 animate-spin text-slate-500" />}
                      {task.status === 'running' && (
                        <button
                          type="button"
                          onClick={() => void handleStop(task)}
                          disabled={busy}
                          className="inline-flex items-center gap-1 rounded-md border border-red-500/30 px-2 py-1 text-[10px] font-semibold text-red-300 transition-colors hover:bg-red-500/10 disabled:opacity-50"
                        >
                          <Square className="h-3 w-3" />
                          停止
                        </button>
                      )}
                      {(task.status === 'pending' || task.status === 'stopped') && (
                        <button
                          type="button"
                          onClick={() => void handleStart(task)}
                          disabled={busy || !llmAvailable}
                          className="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 px-2 py-1 text-[10px] font-semibold text-emerald-300 transition-colors hover:bg-emerald-500/10 disabled:opacity-50"
                        >
                          <Play className="h-3 w-3" />
                          启动
                        </button>
                      )}
                      {task.status !== 'running' && (
                        <button
                          type="button"
                          onClick={() => void handleDelete(task)}
                          disabled={busy}
                          className="inline-flex items-center gap-1 rounded-md border border-crypto-border px-2 py-1 text-[10px] font-semibold text-slate-500 transition-colors hover:border-red-500/30 hover:text-red-300 disabled:opacity-50"
                        >
                          <Trash2 className="h-3 w-3" />
                          删除
                        </button>
                      )}
                      {task.promoted_strategy_version_id && (
                        <span className="ml-auto inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-400/80">
                          <CheckCircle2 className="h-3 w-3" />
                          已采纳
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* 右列：任务详情 + 迭代时间线 */}
        <div className="min-w-0 rounded-xl border border-crypto-border bg-crypto-card" data-testid="agent-task-detail">
          {detailState === 'idle' && (
            <OperatorStatePanel
              kind="empty"
              title="选择一个研发任务"
              description="点击左侧任务查看策略规格书与迭代记录；首次使用请先创建任务。"
              className="border-0"
            />
          )}
          {detailState === 'loading' && (
            <OperatorStatePanel kind="loading" title="正在读取任务详情…" description="加载任务规格与迭代记录。" className="border-0" />
          )}
          {detailState === 'error' && (
            <OperatorStatePanel
              kind="error"
              title="任务详情读取失败"
              description={detailError}
              action={
                <button
                  type="button"
                  onClick={() => selectedTaskId && void loadDetail(selectedTaskId, true)}
                  className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 px-3 py-1.5 text-xs font-semibold text-red-100"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  重试
                </button>
              }
              className="border-0"
            />
          )}
          {detailState === 'ready' && detail && (
            <div className="space-y-4 p-4">
              {/* 概要 */}
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="truncate text-sm font-bold text-white">{detail.name}</h3>
                    <TaskStatusChip status={detail.status} />
                    {detail.status === 'running' && (
                      <span className="text-[10px] text-blue-300/80">{detail.stage_label || detail.stage}</span>
                    )}
                  </div>
                  {detail.user_prompt && (
                    <p className="mt-1.5 max-w-2xl text-[11px] leading-5 text-slate-500">目标：{detail.user_prompt}</p>
                  )}
                </div>
                {pollingActive && (
                  <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-blue-500/30 bg-blue-500/10 px-2.5 py-1 text-[10px] text-blue-300">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    每 3 秒自动刷新
                  </span>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2.5 text-[10px] text-slate-500">
                <span>模型 <span className="ml-1 font-mono text-slate-300">{detail.llm_model || '--'}</span></span>
                <span>迭代 <span className="ml-1 font-mono tabular-nums text-slate-300">{detail.iteration_count}/{detail.max_iterations}</span></span>
                <span>
                  最优 <span className="ml-1 font-mono tabular-nums text-amber-300">{detail.best_score !== null ? detail.best_score.toFixed(1) : '--'}</span>
                  {detail.best_iteration !== null && <span className="ml-1 font-mono tabular-nums text-slate-500">（第 {detail.best_iteration} 轮）</span>}
                </span>
                <span>更新 <span className="ml-1 font-mono tabular-nums text-slate-300">{formatDateTime(detail.updated_at)}</span></span>
                {detail.promoted_strategy_version_id && (
                  <span className="inline-flex items-center gap-1 text-emerald-400/90">
                    <CheckCircle2 className="h-3 w-3" />
                    已采纳策略版本 <span className="font-mono">{detail.promoted_strategy_version_id}</span>
                  </span>
                )}
              </div>
              {detail.error_message && (
                <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] leading-5 text-red-300">
                  {detail.error_message}
                </div>
              )}

              {/* 策略规格书 */}
              {detail.strategy_spec ? (
                <div>
                  <h4 className="mb-2 text-xs font-semibold text-slate-300">策略规格书</h4>
                  <dl className="grid grid-cols-1 gap-2 md:grid-cols-2">
                    <DetailBlock label="市场分析">{detail.strategy_spec.market_analysis}</DetailBlock>
                    <DetailBlock label="推荐方向">{detail.strategy_spec.recommended_approach}</DetailBlock>
                    <DetailBlock label="风险要点">{detail.strategy_spec.risk_considerations}</DetailBlock>
                    <DetailBlock label="迭代计划">{detail.strategy_spec.iteration_plan}</DetailBlock>
                  </dl>
                </div>
              ) : (
                <div className="rounded-lg border border-dashed border-crypto-border px-3 py-3 text-center text-[11px] text-slate-600">
                  策略规格书尚未生成{detail.status === 'pending' ? '，启动任务后由规划智能体产出' : ''}
                </div>
              )}

              {/* 迭代时间线（倒序） */}
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <h4 className="text-xs font-semibold text-slate-300">
                    迭代记录 <span className="ml-1 font-mono text-[10px] tabular-nums text-slate-600">{iterations.length}</span>
                  </h4>
                  <span className="text-[10px] text-slate-600">最新一轮在最上方</span>
                </div>
                {sortedIterations.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-crypto-border px-3 py-6 text-center text-[11px] leading-5 text-slate-600">
                    暂无迭代记录
                    {pollingActive ? '，研发进行中…' : ''}
                  </div>
                ) : (
                  <div className="space-y-3">
                    {sortedIterations.map((iteration) => {
                      const actionMeta = iterationActionMeta[iteration.action] ?? iterationActionMeta.new;
                      const metrics = iteration.backtest_metrics || {};
                      const strategyReturn = metrics.strategy_return;
                      const isBest = detail.best_iteration === iteration.iteration;
                      const alreadyPromoted = detail.promoted_strategy_version_id !== null;
                      return (
                        <article
                          key={iteration.id}
                          data-testid="agent-iteration-card"
                          className={clsx(
                            'rounded-xl border bg-crypto-bg/60 p-3.5',
                            isBest ? 'border-amber-500/30' : 'border-crypto-border',
                          )}
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="rounded bg-blue-500/15 px-1.5 py-0.5 font-mono text-[10px] font-semibold tabular-nums text-blue-300">
                              第 {iteration.iteration} 轮
                            </span>
                            <span className={clsx('rounded border px-1.5 py-0.5 text-[10px] font-semibold', actionMeta.chip)}>
                              {actionMeta.label}
                            </span>
                            {isBest && (
                              <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">
                                最优
                              </span>
                            )}
                            <span className="min-w-0 flex-1 truncate text-xs font-semibold text-slate-200">
                              {iteration.strategy_name || '未命名策略'}
                            </span>
                            <span
                              className={clsx(
                                'rounded-full border px-2 py-0.5 text-[10px] font-semibold',
                                iteration.meets_goal
                                  ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                                  : 'border-slate-600/60 bg-slate-500/10 text-slate-400',
                              )}
                            >
                              {iteration.meets_goal ? '达标' : '未达标'}
                            </span>
                            <span className="font-mono text-xs font-bold tabular-nums text-slate-100">
                              {iteration.score.toFixed(1)}
                              <span className="ml-0.5 text-[10px] font-medium text-slate-500">分</span>
                            </span>
                          </div>

                          {/* 回测关键指标 */}
                          <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
                            <MetricItem
                              label="区间收益"
                              value={formatPercent(strategyReturn)}
                              className={marketToneClass(strategyReturn)}
                            />
                            <MetricItem label="夏普" value={formatNumber(metrics.sharpe)} className="text-slate-300" />
                            <MetricItem
                              label="最大回撤"
                              value={formatPercent(metrics.maximum_drawdown)}
                              className="text-red-400"
                            />
                            <MetricItem label="胜率" value={formatPercent(metrics.win_rate, 1)} className="text-slate-300" />
                            <MetricItem
                              label="成交笔数"
                              value={formatInteger(metrics.completed_trades)}
                              className="text-slate-300"
                            />
                          </div>

                          {/* 评估五维条 */}
                          {iteration.eval_scores && (
                            <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
                              {evalDimensions.map((dimension) => (
                                <span key={dimension.key} className="inline-flex items-center gap-1.5">
                                  <span className="w-7 text-[10px] text-slate-500">{dimension.label}</span>
                                  <span className="h-1 w-14 overflow-hidden rounded-full bg-slate-700/60">
                                    <span
                                      className="block h-full rounded-full bg-blue-500"
                                      style={{ width: scoreBarWidth(iteration.eval_scores?.[dimension.key]) }}
                                    />
                                  </span>
                                  <span className="font-mono text-[10px] tabular-nums text-slate-400">
                                    {formatNumber(iteration.eval_scores?.[dimension.key], 1)}
                                  </span>
                                </span>
                              ))}
                            </div>
                          )}

                          {iteration.error && (
                            <div className="mt-2.5 rounded-lg border border-red-500/30 bg-red-500/10 px-2.5 py-2 text-[11px] leading-5 text-red-300">
                              {iteration.error}
                            </div>
                          )}

                          {iteration.suggestions && iteration.suggestions.length > 0 && (
                            <div className="mt-2.5">
                              <span className="text-[10px] font-semibold text-slate-500">改进建议</span>
                              <ul className="mt-1 space-y-0.5">
                                {iteration.suggestions.map((suggestion, index) => (
                                  <li key={index} className="flex gap-1.5 text-[11px] leading-5 text-slate-400">
                                    <span className="text-slate-600">·</span>
                                    <span>{suggestion}</span>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}

                          {iteration.strategy_code && (
                            <div className="mt-2.5">
                              <button
                                type="button"
                                onClick={() =>
                                  setExpandedCodeId((prev) => (prev === iteration.id ? null : iteration.id))
                                }
                                aria-expanded={expandedCodeId === iteration.id}
                                className="inline-flex items-center gap-1 text-[11px] font-semibold text-blue-300 transition-colors hover:text-blue-200"
                              >
                                {expandedCodeId === iteration.id ? (
                                  <ChevronDown className="h-3.5 w-3.5" />
                                ) : (
                                  <ChevronRight className="h-3.5 w-3.5" />
                                )}
                                策略代码
                              </button>
                              {expandedCodeId === iteration.id && (
                                <pre className="mt-2 max-h-80 overflow-auto rounded-lg border border-crypto-border bg-[#0D1117] p-3 font-mono text-[11px] leading-5 text-slate-300">
                                  {iteration.strategy_code}
                                </pre>
                              )}
                            </div>
                          )}

                          {iteration.meets_goal && !iteration.error && (
                            <div className="mt-3 flex items-center gap-2 border-t border-crypto-border pt-2.5">
                              <button
                                type="button"
                                onClick={() => void handlePromote(iteration)}
                                disabled={promotingIteration === iteration.iteration}
                                data-testid="agent-promote-button"
                                className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-[11px] font-semibold text-emerald-300 transition-colors hover:bg-emerald-500/20 disabled:opacity-50"
                              >
                                {promotingIteration === iteration.iteration ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <CheckCircle2 className="h-3.5 w-3.5" />
                                )}
                                采纳为策略版本
                              </button>
                              {alreadyPromoted && promotedInfo?.iteration !== iteration.iteration && (
                                <span className="text-[10px] text-emerald-400/80">该任务已有采纳版本</span>
                              )}
                            </div>
                          )}
                        </article>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

export default StrategyAIPanel;
