import { useState, useEffect, useMemo, useRef } from 'react';
import {
  Cpu, Play, Square, AlertCircle, ChevronRight, ChevronDown, Download,
  RefreshCw, Sparkles, Target, FileText, GitBranch, RotateCcw,
  ArrowRight, Zap, History, Trash2,
  Activity, Wrench, PauseCircle, Terminal, Settings,
  Send,
} from 'lucide-react';
import axios from 'axios';
import clsx from 'clsx';
import { useSearchParams } from 'react-router-dom';
import CryptoSelect from '../components/CryptoSelect';
import ThemeDialog from '../components/ThemeDialog';
import ThemeAlertDialog, { type ThemeAlertTone } from '../components/ThemeAlertDialog';
import { SELECTED_SEGMENT_BORDER_CLASS } from '../utils/selectionStyles';
import ResearchWorkbench from './aiLab/ResearchWorkbench';
import AutoAgentPanel from './aiLab/AutoAgentPanel';
import OrbitPostPanel from './aiLab/OrbitPostPanel';
import { GoalCriteria, Iteration, TaskInfo, StrategyOptimizerConfig, StrategyOptimizationRun, AutoAgentSchedulerConfig, AutonomousTraderConfig, AutonomousTraderInstance, LLMModelConfig, OrbitAutoPostConfig, OrbitCandidate, OrbitPostRecord, OrbitLoginStatus, AutonomousNumericConfigKey, AssistantTab, MarketType, HUNTER_GOAL, AI_RESEARCH_MARKETS, AI_RESEARCH_DEFAULT_TIMEFRAME, AUTONOMOUS_HERMES_MODEL, AUTONOMOUS_HERMES_PROVIDER_LABEL, AUTONOMOUS_TRADER_DEFAULT_CONFIG, AUTO_AGENT_RUN_STORAGE_KEY, AUTO_AGENT_DEFAULT_SYMBOLS, AUTO_AGENT_DEFAULT_SCHEDULER, ORBIT_AUTO_POST_DEFAULT_CONFIG, getTaskId, isActiveResearchTask, readRememberedTaskId, rememberTaskId, forgetRememberedTaskId, normalizeTaskInfo, getResearchTaskTitle, researchMarketForTask, apiSymbolScopeForMarket, autonomousSymbolsFromText, autonomousStatusText, autonomousStatusClass, formatAutonomousLogTime, autonomousLogLevelClass, autonomousLogTitle, autonomousLogSummary, autonomousLogChips, normalizeAutonomousNumericInput, autonomousInstanceConfigItems, autonomousConfigFromInstance, autonomousParameterCardClass, autonomousRiskParameterCardClass, HUNTER_PROMPT, ACTION_LABELS, formatDateTime, DEFAULT_BACKTEST_DATE_RANGE, DatePickerField, finiteNumber, fmtNumber, fmtPct, unwrapApiData, normalizeOrbitAutoPostConfig, orbitConfigPayload, signedMarketTone, targetTone, riskTone, metricToneTextClass, getCandidateQuality, ResearchPipeline, StrategyOptimizerPipeline, optimizerStatusText, getOptimizerRunTitle, canDeleteOptimizerRun, RadarChart, MetricCard } from './aiLab/aiLabSupport';
import { useSymbolNames } from '../hooks/useSymbolNames';
import { formatSymbolLabel } from '../utils/symbolDisplay';

const api = axios.create({ baseURL: '/api/v2', timeout: 120000 });
api.interceptors.response.use((r) => r.data, (e) => Promise.reject(e));

/* ---------- types ---------- */

export default function AILab() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const activeTab = (tabParam === 'research' || tabParam === 'optimizer' ? tabParam : 'research') as AssistantTab;
  const [startDate, setStartDate] = useState(DEFAULT_BACKTEST_DATE_RANGE.start);
  const [endDate, setEndDate] = useState(DEFAULT_BACKTEST_DATE_RANGE.end);
  const [maxIter, setMaxIter] = useState(3);
  const [marketType, setMarketType] = useState<MarketType>('spot');
  const [manualPrompt, setManualPrompt] = useState('');
  const [userPrompt, setUserPrompt] = useState(HUNTER_PROMPT);
  const [goal, setGoal] = useState<GoalCriteria>({ ...HUNTER_GOAL });

  const [task, setTask] = useState<TaskInfo | null>(null);
  const [taskHistory, setTaskHistory] = useState<TaskInfo[]>([]);
  const [iterations, setIterations] = useState<Iteration[]>([]);
  const [selectedIter, setSelectedIter] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [promptOptimizing, setPromptOptimizing] = useState(false);
  const [promptOptimizeSummary, setPromptOptimizeSummary] = useState('');
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState('');
  const [showSpec, setShowSpec] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<TaskInfo | null>(null);
  const [deletingTaskId, setDeletingTaskId] = useState('');
  const [forceSaveTarget, setForceSaveTarget] = useState<Iteration | null>(null);
  const [savingIteration, setSavingIteration] = useState<number | null>(null);
  const [optimizerConfig, setOptimizerConfig] = useState<StrategyOptimizerConfig | null>(null);
  const [optimizerRuns, setOptimizerRuns] = useState<StrategyOptimizationRun[]>([]);
  const [optimizerLoading, setOptimizerLoading] = useState(false);
  const [optimizerSaving, setOptimizerSaving] = useState(false);
  const [optimizerRunningNow, setOptimizerRunningNow] = useState(false);
  const [optimizerStopping, setOptimizerStopping] = useState(false);
  const [optimizerStatus, setOptimizerStatus] = useState('');
  const [optimizerDeleteTarget, setOptimizerDeleteTarget] = useState<StrategyOptimizationRun | null>(null);
  const [deletingOptimizerRunId, setDeletingOptimizerRunId] = useState('');
  const [researchModel, setResearchModel] = useState('');
  const [optimizerModel, setOptimizerModel] = useState('');
  const [autonomousConfig, setAutonomousConfig] = useState<AutonomousTraderConfig>({ ...AUTONOMOUS_TRADER_DEFAULT_CONFIG });
  const [autonomousModelConfig, setAutonomousModelConfig] = useState<LLMModelConfig | null>(null);
  const [autonomousInstances, setAutonomousInstances] = useState<AutonomousTraderInstance[]>([]);
  const [autonomousLoading, setAutonomousLoading] = useState(false);
  const [autonomousStarting, setAutonomousStarting] = useState(false);
  const [autonomousStatus, setAutonomousStatus] = useState('');
  const [autonomousLifecycleActionId, setAutonomousLifecycleActionId] = useState<number | null>(null);
  const [autonomousDeleteTarget, setAutonomousDeleteTarget] = useState<AutonomousTraderInstance | null>(null);
  const [deletingAutonomousId, setDeletingAutonomousId] = useState<number | null>(null);
  const [autonomousEditTarget, setAutonomousEditTarget] = useState<AutonomousTraderInstance | null>(null);
  const [autonomousEditConfig, setAutonomousEditConfig] = useState<AutonomousTraderConfig | null>(null);
  const [autonomousEditDrafts, setAutonomousEditDrafts] = useState<Partial<Record<AutonomousNumericConfigKey, string>>>({});
  const [savingAutonomousConfig, setSavingAutonomousConfig] = useState(false);
  const [selectedAutonomousId, setSelectedAutonomousId] = useState<number | null>(null);
  const [autonomousLogsOpen, setAutonomousLogsOpen] = useState(true);
  const [autonomousNumberDrafts, setAutonomousNumberDrafts] = useState<Partial<Record<AutonomousNumericConfigKey, string>>>({});
  const [autoAgentLoading, setAutoAgentLoading] = useState(false);
  const [autoAgentStatus, setAutoAgentStatus] = useState('');
  const [autoAgentResult, setAutoAgentResult] = useState<Record<string, any> | null>(null);
  const [autoAgentRunId, setAutoAgentRunId] = useState('');
  const [autoAgentScheduler, setAutoAgentScheduler] = useState<AutoAgentSchedulerConfig | null>(null);
  const [autoAgentSchedulerOpen, setAutoAgentSchedulerOpen] = useState(false);
  const [autoAgentSchedulerSaving, setAutoAgentSchedulerSaving] = useState(false);
  const [autoAgentSchedulerStatus, setAutoAgentSchedulerStatus] = useState('');
  const [orbitConfig, setOrbitConfig] = useState<OrbitAutoPostConfig>({ ...ORBIT_AUTO_POST_DEFAULT_CONFIG });
  const [orbitCandidates, setOrbitCandidates] = useState<OrbitCandidate[]>([]);
  const [orbitHistory, setOrbitHistory] = useState<OrbitPostRecord[]>([]);
  const [orbitLoginStatus, setOrbitLoginStatus] = useState<OrbitLoginStatus | null>(null);
  const [orbitLoading, setOrbitLoading] = useState(false);
  const [orbitSaving, setOrbitSaving] = useState(false);
  const [orbitRunning, setOrbitRunning] = useState(false);
  const [orbitPublishingId, setOrbitPublishingId] = useState('');
  const [orbitStatus, setOrbitStatus] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const restoredTaskRef = useRef(false);

  const [themeAlert, setThemeAlert] = useState<{
    open: boolean;
    title: string;
    content: string;
    tone?: ThemeAlertTone;
  }>({ open: false, title: '', content: '' });

  const showThemeAlert = (title: string, content: string, tone?: ThemeAlertTone) => {
    setThemeAlert({ open: true, title, content, tone: tone ?? 'danger' });
  };

  const isRunning = task?.status === 'running' || task?.status === 'pending';
  const selectedMarket = AI_RESEARCH_MARKETS[marketType];
  const stageText = task?.stage_label || (isRunning ? '正在准备任务...' : '启动任务后将在此显示迭代进度');
  const canResume = Boolean(
    task
    && ['interrupted', 'stopped', 'failed'].includes(task.status)
    && task.iterations_count < task.max_iterations
  );

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const refreshTaskHistory = async () => {
    setHistoryLoading(true);
    try {
      const items = await api.get('/agent/tasks') as any[];
      const normalized = items.map(normalizeTaskInfo);
      setTaskHistory(normalized.slice(0, 12));

      if (!restoredTaskRef.current) {
        restoredTaskRef.current = true;
        const rememberedTaskId = readRememberedTaskId();
        const activeTask = normalized.find(isActiveResearchTask);
        const rememberedTask = rememberedTaskId
          ? normalized.find((item) => getTaskId(item) === rememberedTaskId)
          : null;
        const restoreTask = activeTask || rememberedTask;
        const restoreTaskId = getTaskId(restoreTask);

        if (restoreTaskId) {
          void loadTask(restoreTaskId, isActiveResearchTask(restoreTask)).catch(() => {
            if (rememberedTaskId === restoreTaskId) forgetRememberedTaskId(restoreTaskId);
          });
        }
      }
    } catch {
      /* history is optional */
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    refreshTaskHistory();
  }, []);

  const refreshOptimizer = async () => {
    setOptimizerLoading(true);
    try {
      const [cfg, runs] = await Promise.all([
        api.get('/agent/strategy-optimizer/config'),
        api.get('/agent/strategy-optimizer/runs?limit=20'),
      ]);
      const nextConfig = cfg as unknown as StrategyOptimizerConfig;
      setOptimizerConfig(nextConfig);
      const configuredModel = String(nextConfig.llm_model || '').trim();
      if (configuredModel) {
        setOptimizerModel((prev) => prev || configuredModel);
      }
      setOptimizerRuns(runs as unknown as StrategyOptimizationRun[]);
    } catch (e: any) {
      setOptimizerStatus(e?.response?.data?.detail || e.message || '自动优化状态读取失败');
    } finally {
      setOptimizerLoading(false);
    }
  };

  useEffect(() => {
    refreshOptimizer();
    const timer = setInterval(refreshOptimizer, 15000);
    return () => clearInterval(timer);
  }, []);

  const refreshAutonomousModelConfig = async () => {
    try {
      const cfg = await api.get('/settings/llm-model') as LLMModelConfig;
      setAutonomousModelConfig(cfg);
      const currentModel = String(cfg.model || cfg.default_model || '').trim();
      if (currentModel) {
        setResearchModel((prev) => prev || currentModel);
        setOptimizerModel((prev) => prev || currentModel);
        setAutonomousConfig((prev) => (prev.llmModel ? prev : { ...prev, llmModel: currentModel }));
      }
    } catch (e: any) {
      setAutonomousStatus(e?.response?.data?.detail || e.message || 'AI模型配置读取失败');
    }
  };

  useEffect(() => {
    refreshAutonomousModelConfig();
  }, []);

  const refreshAutonomousTrader = async () => {
    setAutonomousLoading(true);
    try {
      const items = await api.get('/agent/autonomous-trader/instances?limit=20') as AutonomousTraderInstance[];
      setAutonomousInstances(items || []);
    } catch (e: any) {
      setAutonomousStatus(e?.response?.data?.detail || e.message || 'AI自主交易状态读取失败');
    } finally {
      setAutonomousLoading(false);
    }
  };

  useEffect(() => {
    refreshAutonomousTrader();
    const timer = setInterval(refreshAutonomousTrader, 15000);
    return () => clearInterval(timer);
  }, []);

  const refreshOrbitAutoPost = async () => {
    setOrbitLoading(true);
    try {
      const [cfg, payload, login] = await Promise.all([
        api.get('/agent/orbit-auto-post/config'),
        api.get('/agent/orbit-auto-post/candidates'),
        api.get('/agent/orbit-auto-post/login-status'),
      ]);
      setOrbitConfig(normalizeOrbitAutoPostConfig(unwrapApiData(cfg)));
      const data = unwrapApiData<{ candidates?: OrbitCandidate[]; history?: OrbitPostRecord[]; config?: any }>(payload);
      if (data.config) {
        setOrbitConfig(normalizeOrbitAutoPostConfig(data.config));
      }
      setOrbitCandidates(data.candidates || []);
      setOrbitHistory(data.history || []);
      setOrbitLoginStatus(unwrapApiData<OrbitLoginStatus>(login));
    } catch (e: any) {
      setOrbitStatus(e?.response?.data?.detail || e.message || '星球发帖状态读取失败');
    } finally {
      setOrbitLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab !== 'orbit-post') return;
    refreshOrbitAutoPost();
  }, [activeTab]);

  const handleSaveOrbitConfig = async (updates: Partial<OrbitAutoPostConfig> = {}) => {
    setOrbitSaving(true);
    setOrbitStatus('');
    try {
      const nextConfig = { ...orbitConfig, ...updates };
      const saved = await api.put('/agent/orbit-auto-post/config', orbitConfigPayload(nextConfig));
      setOrbitConfig(normalizeOrbitAutoPostConfig(unwrapApiData(saved)));
      setOrbitStatus('星球发帖配置已保存');
      await refreshOrbitAutoPost();
    } catch (e: any) {
      setOrbitStatus(e?.response?.data?.detail || e.message || '星球发帖配置保存失败');
    } finally {
      setOrbitSaving(false);
    }
  };

  const handleRunOrbitAutoPost = async () => {
    setOrbitRunning(true);
    setOrbitStatus('');
    try {
      const res = unwrapApiData<{ posted_count?: number; skipped?: string; posted?: OrbitPostRecord[] }>(
        await api.post('/agent/orbit-auto-post/run-now')
      );
      setOrbitStatus(res.posted_count ? `已发布 ${res.posted_count} 条星球动态` : `未发布：${res.skipped || '暂无符合条件的合约单'}`);
      await refreshOrbitAutoPost();
    } catch (e: any) {
      setOrbitStatus(e?.response?.data?.detail || e.message || '立即发帖失败');
    } finally {
      setOrbitRunning(false);
    }
  };

  const handlePublishOrbitCandidate = async (candidate: OrbitCandidate) => {
    setOrbitPublishingId(candidate.id);
    setOrbitStatus('');
    try {
      const res = unwrapApiData<OrbitPostRecord>(await api.post('/agent/orbit-auto-post/publish', { candidate }));
      setOrbitStatus(res.status === 'submitted' || res.status === 'published' ? '已提交研究纪要' : `发布状态：${res.status && res.status !== 'unknown' ? res.status : '待处理'}${res.error ? `，${res.error}` : ''}`);
      await refreshOrbitAutoPost();
    } catch (e: any) {
      setOrbitStatus(e?.response?.data?.detail || e.message || '候选发布失败');
    } finally {
      setOrbitPublishingId('');
    }
  };

  const startPolling = (taskId: string) => {
    rememberTaskId(taskId);
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const [t, iters] = await Promise.all([
          api.get(`/agent/tasks/${taskId}`),
          api.get(`/agent/tasks/${taskId}/iterations`),
        ]);
        const nextTask = normalizeTaskInfo(t);
        setTask(nextTask);
        setIterations(iters as any);
        if (nextTask.status !== 'running' && nextTask.status !== 'pending') {
          if (pollRef.current) clearInterval(pollRef.current);
          refreshTaskHistory();
        }
      } catch { /* ignore */ }
    }, 3000);
  };

  const loadTask = async (taskId: string, poll = false) => {
    rememberTaskId(taskId);
    const [t, iters] = await Promise.all([
      api.get(`/agent/tasks/${taskId}`),
      api.get(`/agent/tasks/${taskId}/iterations`),
    ]);
    const nextTask = normalizeTaskInfo(t);
    setTask(nextTask);
    setIterations(iters as any);
    setSelectedIter(null);
    setShowSpec(Boolean(nextTask.strategy_spec));
    if (nextTask.backtest_start) setStartDate(nextTask.backtest_start);
    if (nextTask.backtest_end) setEndDate(nextTask.backtest_end);
    if (nextTask.max_iterations) setMaxIter(nextTask.max_iterations);
    setMarketType(researchMarketForTask(nextTask));
    if (nextTask.goal) setGoal(nextTask.goal);
    if (nextTask.llm_model) setResearchModel(String(nextTask.llm_model));
    if (nextTask.user_prompt) {
      setUserPrompt(nextTask.user_prompt);
      setPromptOptimizeSummary('已载入该任务使用的最终提示词');
    }
    if (poll || nextTask.status === 'running' || nextTask.status === 'pending') {
      startPolling(taskId);
    }
    return {
      task: nextTask as unknown as Record<string, any>,
      iterations: iters as unknown as Record<string, any>[],
    };
  };

  const handleOptimizePrompt = async () => {
    const sourcePrompt = manualPrompt.trim() || userPrompt.trim();
    if (!sourcePrompt) {
      setError('请先输入人工提示词');
      return;
    }
    if (!selectedResearchModel) {
      setError('请先选择 AI 模型');
      return;
    }
    setError('');
    setPromptOptimizeSummary('');
    setPromptOptimizing(true);
    try {
      const res = await api.post('/agent/prompt/optimize', {
        manual_prompt: manualPrompt,
        current_prompt: userPrompt,
        market_type: marketType,
        llm_model: selectedResearchModel,
        goal,
      }) as { optimized_prompt?: string; summary?: string };
      const optimized = String(res.optimized_prompt || '').trim();
      if (!optimized) {
        throw new Error('模型未返回最终提示词');
      }
      setUserPrompt(optimized);
      setPromptOptimizeSummary(res.summary || '已生成最终策略提示词，启动研发时会使用这段内容。');
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || '提示词生成失败');
    } finally {
      setPromptOptimizing(false);
    }
  };

  const handleStart = async () => {
    setError('');
    setLoading(true);
    try {
      if (!selectedResearchModel) {
        throw new Error('请先选择 AI 模型');
      }
      const res: any = await api.post('/agent/tasks', {
        market_type: marketType,
        symbol: apiSymbolScopeForMarket(marketType),
        timeframe: AI_RESEARCH_DEFAULT_TIMEFRAME,
        backtest_start: startDate,
        backtest_end: endDate,
        max_iterations: maxIter,
        user_prompt: userPrompt,
        llm_model: selectedResearchModel,
        goal,
      });
      const taskId = res.task_id;
      const t: any = await api.get(`/agent/tasks/${taskId}`);
      rememberTaskId(taskId);
      setTask(normalizeTaskInfo(t));
      setIterations([]);
      setSelectedIter(null);
      setShowSpec(false);
      refreshTaskHistory();
      startPolling(taskId);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || '启动失败');
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    if (!task) return;
    const taskId = getTaskId(task);
    if (!taskId) {
      setError('任务ID缺失，无法停止');
      return;
    }
    setError('');
    try {
      await api.post(`/agent/tasks/${taskId}/stop`);
      setTask({ ...task, status: 'stopped', stage: 'stopped', stage_label: '任务已停止' });
      if (pollRef.current) clearInterval(pollRef.current);
      refreshTaskHistory();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || '停止失败');
    }
  };

  const handleResume = async () => {
    if (!task) return;
    const taskId = getTaskId(task);
    if (!taskId) {
      setError('任务ID缺失，无法继续');
      return;
    }
    setError('');
    setLoading(true);
    try {
      await api.post(`/agent/tasks/${taskId}/resume`);
      await loadTask(taskId, true);
      refreshTaskHistory();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || '继续研发失败');
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteRecord = async () => {
    if (!deleteTarget) return;
    const taskId = getTaskId(deleteTarget);
    if (!taskId) return;

    setError('');
    setDeletingTaskId(taskId);
    try {
      await api.delete(`/agent/tasks/${taskId}`);
      setTaskHistory((items) => items.filter((item) => getTaskId(item) !== taskId));
      if (task && getTaskId(task) === taskId) {
        setTask(null);
        setIterations([]);
        setSelectedIter(null);
        setShowSpec(false);
        forgetRememberedTaskId(taskId);
        if (pollRef.current) clearInterval(pollRef.current);
      }
      setDeleteTarget(null);
      refreshTaskHistory();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || '删除记录失败');
    } finally {
      setDeletingTaskId('');
    }
  };

  const handleToggleOptimizer = async () => {
    if (!optimizerConfig) return;
    setOptimizerSaving(true);
    setOptimizerStatus('');
    try {
      if (!selectedOptimizerModel) {
        throw new Error('请先选择 AI 模型');
      }
      const cfg = await api.put('/agent/strategy-optimizer/config', {
        enabled: !optimizerConfig.enabled,
        interval_hours: optimizerConfig.interval_hours || 4,
        low_return_pct: optimizerConfig.low_return_pct ?? 0,
        trial_hours: optimizerConfig.trial_hours || 4,
        trial_success_return_pct: optimizerConfig.trial_success_return_pct ?? 0,
        llm_model: selectedOptimizerModel,
      }) as StrategyOptimizerConfig;
      setOptimizerConfig(cfg);
      setOptimizerStatus(cfg.enabled ? '自动优化已开启' : '自动优化已关闭');
    } catch (e: any) {
      setOptimizerStatus(e?.response?.data?.detail || e.message || '自动优化配置保存失败');
    } finally {
      setOptimizerSaving(false);
    }
  };

  const handleRunOptimizerNow = async () => {
    setOptimizerRunningNow(true);
    setOptimizerStatus('');
    try {
      if (!selectedOptimizerModel) {
        throw new Error('请先选择 AI 模型');
      }
      const res = await api.post('/agent/strategy-optimizer/run-now', {
        llm_model: selectedOptimizerModel,
      }) as { message?: string };
      setOptimizerStatus(res.message || '已触发自动优化扫描');
      setTimeout(refreshOptimizer, 1500);
    } catch (e: any) {
      setOptimizerStatus(e?.response?.data?.detail || e.message || '触发自动优化失败');
    } finally {
      setOptimizerRunningNow(false);
    }
  };

  const handleCancelOptimizerRun = async (runId: string) => {
    setOptimizerStatus('');
    try {
      await api.post(`/agent/strategy-optimizer/runs/${runId}/cancel`);
      setOptimizerStatus('优化任务已取消');
      refreshOptimizer();
    } catch (e: any) {
      setOptimizerStatus(e?.response?.data?.detail || e.message || '取消优化任务失败');
    }
  };

  const handleDeleteOptimizerRun = async () => {
    if (!optimizerDeleteTarget) return;
    const runId = optimizerDeleteTarget.id;
    setOptimizerStatus('');
    setDeletingOptimizerRunId(runId);
    try {
      await api.delete(`/agent/strategy-optimizer/runs/${runId}`);
      setOptimizerRuns((items) => items.filter((run) => run.id !== runId));
      setOptimizerDeleteTarget(null);
      setOptimizerStatus('优化记录已删除');
      refreshOptimizer();
    } catch (e: any) {
      setOptimizerStatus(e?.response?.data?.detail || e.message || '删除优化记录失败');
    } finally {
      setDeletingOptimizerRunId('');
    }
  };

  const handleStopOptimizer = async () => {
    setOptimizerStopping(true);
    setOptimizerStatus('');
    try {
      const res = await api.post('/agent/strategy-optimizer/stop') as { message?: string; cancelled_runs?: string[] };
      const cancelledCount = res.cancelled_runs?.length || 0;
      setOptimizerStatus(cancelledCount > 0 ? `已停止优化，取消 ${cancelledCount} 个任务` : (res.message || '已请求停止优化'));
      refreshOptimizer();
    } catch (e: any) {
      setOptimizerStatus(e?.response?.data?.detail || e.message || '停止优化失败');
    } finally {
      setOptimizerStopping(false);
    }
  };

  const updateAutonomousConfig = (key: keyof AutonomousTraderConfig, value: string | number | boolean) => {
    if (key === 'symbolsText') {
      setAutonomousConfig((prev) => ({ ...prev, symbolsText: String(value) }));
      return;
    }
    if (key === 'promptText') {
      setAutonomousConfig((prev) => ({ ...prev, promptText: String(value) }));
      return;
    }
    if (key === 'restrictSymbols') {
      setAutonomousConfig((prev) => ({ ...prev, restrictSymbols: Boolean(value) }));
      return;
    }
    if (key === 'llmModel') {
      setAutonomousConfig((prev) => ({ ...prev, llmModel: String(value).trim() }));
      return;
    }
    if (key === 'llmProvider') {
      setAutonomousConfig((prev) => {
        const provider = String(value).trim();
        return {
          ...prev,
          llmProvider: provider,
          llmModel: provider === 'hermes' ? AUTONOMOUS_HERMES_MODEL : (autonomousModelConfig?.model || prev.llmModel),
        };
      });
      return;
    }
    if (key === 'tradeDirection') {
      setAutonomousConfig((prev) => ({ ...prev, tradeDirection: String(value).trim() }));
      return;
    }
    const normalized = normalizeAutonomousNumericInput(String(value));
    setAutonomousNumberDrafts((prev) => ({ ...prev, [key]: normalized }));
    if (!normalized) return;
    const numericValue = Number(normalized);
    if (Number.isFinite(numericValue)) {
      setAutonomousConfig((prev) => ({
        ...prev,
        [key]: numericValue,
      }));
    }
  };

  const commitAutonomousNumericConfig = (
    key: AutonomousNumericConfigKey,
    min: number,
    max: number,
  ) => {
    const draft = autonomousNumberDrafts[key];
    const fallback = AUTONOMOUS_TRADER_DEFAULT_CONFIG[key];
    const rawValue = draft === undefined || draft === '' ? autonomousConfig[key] : Number(draft);
    const numericValue = Number.isFinite(Number(rawValue)) ? Number(rawValue) : Number(fallback);
    const clamped = Math.min(max, Math.max(min, numericValue));
    setAutonomousConfig((prev) => ({ ...prev, [key]: clamped }));
    setAutonomousNumberDrafts((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const openAutonomousConfigEditor = (item: AutonomousTraderInstance) => {
    const config = autonomousConfigFromInstance(item, selectedAutonomousModel);
    setAutonomousEditTarget(item);
    setAutonomousEditConfig(config);
    setAutonomousEditDrafts({});
  };

  const updateAutonomousEditConfig = (key: keyof AutonomousTraderConfig, value: string | number | boolean) => {
    if (!autonomousEditConfig) return;
    if (key === 'symbolsText') {
      setAutonomousEditConfig((prev) => (prev ? { ...prev, symbolsText: String(value) } : prev));
      return;
    }
    if (key === 'promptText') {
      setAutonomousEditConfig((prev) => (prev ? { ...prev, promptText: String(value) } : prev));
      return;
    }
    if (key === 'restrictSymbols') {
      setAutonomousEditConfig((prev) => (prev ? { ...prev, restrictSymbols: Boolean(value) } : prev));
      return;
    }
    if (key === 'llmModel') {
      setAutonomousEditConfig((prev) => (prev ? { ...prev, llmModel: String(value).trim() } : prev));
      return;
    }
    if (key === 'llmProvider') {
      setAutonomousEditConfig((prev) => {
        if (!prev) return prev;
        const provider = String(value).trim();
        return {
          ...prev,
          llmProvider: provider,
          llmModel: provider === 'hermes' ? AUTONOMOUS_HERMES_MODEL : (autonomousModelConfig?.model || prev.llmModel),
        };
      });
      return;
    }
    if (key === 'tradeDirection') {
      setAutonomousEditConfig((prev) => (prev ? { ...prev, tradeDirection: String(value).trim() } : prev));
      return;
    }
    const normalized = normalizeAutonomousNumericInput(String(value));
    setAutonomousEditDrafts((prev) => ({ ...prev, [key]: normalized }));
    if (!normalized) return;
    const numericValue = Number(normalized);
    if (Number.isFinite(numericValue)) {
      setAutonomousEditConfig((prev) => (prev ? { ...prev, [key]: numericValue } : prev));
    }
  };

  const commitAutonomousEditNumericConfig = (
    key: AutonomousNumericConfigKey,
    min: number,
    max: number,
  ) => {
    if (!autonomousEditConfig) return;
    const draft = autonomousEditDrafts[key];
    const fallback = AUTONOMOUS_TRADER_DEFAULT_CONFIG[key];
    const rawValue = draft === undefined || draft === '' ? autonomousEditConfig[key] : Number(draft);
    const numericValue = Number.isFinite(Number(rawValue)) ? Number(rawValue) : Number(fallback);
    const clamped = Math.min(max, Math.max(min, numericValue));
    setAutonomousEditConfig((prev) => (prev ? { ...prev, [key]: clamped } : prev));
    setAutonomousEditDrafts((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const handleSaveAutonomousConfig = async () => {
    if (!autonomousEditTarget || !autonomousEditConfig) return;
    setSavingAutonomousConfig(true);
    setAutonomousStatus('');
    try {
      if (!autonomousEditConfig.llmModel) {
        throw new Error('请先选择 AI 模型');
      }
      const strategyId = autonomousEditTarget.strategy_id;
      const editRuntimeStatus = String(autonomousEditTarget.status || '').toLowerCase();
      const payload: Record<string, any> = {
        llm_provider: autonomousEditConfig.llmProvider,
        llm_model: autonomousEditConfig.llmModel,
        trade_direction: autonomousEditConfig.tradeDirection,
        operator_prompt: autonomousEditConfig.promptText.trim(),
        restrict_symbols: autonomousEditConfig.restrictSymbols,
        max_leverage_cap: autonomousEditConfig.maxLeverageCap,
        max_single_position_pct: autonomousEditConfig.maxSinglePositionPct,
        max_total_exposure_pct: autonomousEditConfig.maxTotalExposurePct,
        max_positions: autonomousEditConfig.maxPositions,
        min_decision_interval_sec: autonomousEditConfig.minDecisionIntervalSec,
        max_decision_interval_sec: autonomousEditConfig.maxDecisionIntervalSec,
        max_trades_per_hour: autonomousEditConfig.maxTradesPerHour,
        probe_size_pct: autonomousEditConfig.probeSizePct,
      };
      if (!['pending', 'running', 'paused'].includes(editRuntimeStatus)) {
        payload.initial_capital = autonomousEditConfig.initialCapital;
      }
      const res = await api.put(`/agent/autonomous-trader/${strategyId}/config`, payload) as { message?: string; runtime_applied?: boolean };
      setAutonomousStatus(
        res.runtime_applied
          ? 'AI自主交易配置已更新，运行中实例将在下一次 AI 决策使用新配置'
          : (res.message || 'AI自主交易配置已更新'),
      );
      setAutonomousEditTarget(null);
      setAutonomousEditConfig(null);
      setAutonomousEditDrafts({});
      refreshAutonomousTrader();
    } catch (e: any) {
      setAutonomousStatus(e?.response?.data?.detail || e.message || '保存 AI自主交易配置失败');
    } finally {
      setSavingAutonomousConfig(false);
    }
  };

  const handleStartAutonomousTrader = async () => {
    setAutonomousStarting(true);
    setAutonomousStatus('');
    try {
      const symbols = autonomousSymbolsFromText(autonomousConfig.symbolsText);
      if (autonomousConfig.restrictSymbols && !symbols.length) {
        throw new Error('请至少配置一个合约标的');
      }
      if (!selectedAutonomousModel) {
        throw new Error('请先选择 AI 模型');
      }
      const res = await api.post('/agent/autonomous-trader/start', {
        symbols: autonomousConfig.restrictSymbols ? symbols : [],
        restrict_symbols: autonomousConfig.restrictSymbols,
        operator_prompt: autonomousConfig.promptText.trim(),
        llm_provider: autonomousConfig.llmProvider,
        llm_model: selectedAutonomousModel,
        trade_direction: autonomousConfig.tradeDirection,
        max_leverage_cap: autonomousConfig.maxLeverageCap,
        max_single_position_pct: autonomousConfig.maxSinglePositionPct,
        max_total_exposure_pct: autonomousConfig.maxTotalExposurePct,
        max_positions: autonomousConfig.maxPositions,
        min_decision_interval_sec: autonomousConfig.minDecisionIntervalSec,
        max_decision_interval_sec: autonomousConfig.maxDecisionIntervalSec,
        max_trades_per_hour: autonomousConfig.maxTradesPerHour,
        probe_size_pct: autonomousConfig.probeSizePct,
        initial_capital: autonomousConfig.initialCapital,
      }) as { message?: string };
      setAutonomousStatus(res.message || 'AI自主交易模拟盘已启动');
      setTimeout(refreshAutonomousTrader, 1200);
    } catch (e: any) {
      setAutonomousStatus(e?.response?.data?.detail || e.message || 'AI自主交易启动失败');
    } finally {
      setAutonomousStarting(false);
    }
  };

  const handlePauseAutonomousTrader = async (strategyId: number) => {
    setAutonomousLifecycleActionId(strategyId);
    setAutonomousStatus('');
    try {
      const res = await api.post(`/agent/autonomous-trader/${strategyId}/pause`) as { message?: string };
      setAutonomousStatus(res.message || 'AI自主交易模拟盘已暂停，指标已保留，可继续运行');
      refreshAutonomousTrader();
    } catch (e: any) {
      setAutonomousStatus(e?.response?.data?.detail || e.message || '暂停 AI自主交易失败');
    } finally {
      setAutonomousLifecycleActionId(null);
    }
  };

  const handleResumeAutonomousTrader = async (strategyId: number) => {
    setAutonomousLifecycleActionId(strategyId);
    setAutonomousStatus('');
    try {
      const res = await api.post(`/agent/autonomous-trader/${strategyId}/resume`) as { message?: string };
      setAutonomousStatus(res.message || 'AI自主交易模拟盘已继续运行');
      refreshAutonomousTrader();
    } catch (e: any) {
      setAutonomousStatus(e?.response?.data?.detail || e.message || '继续 AI自主交易失败');
    } finally {
      setAutonomousLifecycleActionId(null);
    }
  };

  const handleDeleteAutonomousTrader = async () => {
    if (!autonomousDeleteTarget) return;
    const strategyId = autonomousDeleteTarget.strategy_id;
    setDeletingAutonomousId(strategyId);
    setAutonomousStatus('');
    try {
      const res = await api.delete(`/agent/autonomous-trader/${strategyId}`) as { message?: string };
      setAutonomousInstances((items) => items.filter((item) => item.strategy_id !== strategyId));
      if (selectedAutonomousId === strategyId) setSelectedAutonomousId(null);
      setAutonomousDeleteTarget(null);
      setAutonomousStatus(res.message || 'AI自主交易模拟盘实例已删除');
      refreshAutonomousTrader();
    } catch (e: any) {
      setAutonomousStatus(e?.response?.data?.detail || e.message || '删除 AI自主交易实例失败');
    } finally {
      setDeletingAutonomousId(null);
    }
  };

  const handleAccept = async () => {
    if (!task) return;
    const taskId = getTaskId(task);
    if (!taskId) {
      showThemeAlert('保存失败', '任务ID缺失，无法保存策略', 'danger');
      return;
    }
    try {
      const res: any = await api.post(`/agent/tasks/${taskId}/accept`);
      showThemeAlert(
        '保存成功',
        `策略已保存。\nID: ${res.strategy_id}\n名称: ${res.strategy_name}`,
        'default',
      );
      refreshTaskHistory();
    } catch (e: any) {
      showThemeAlert('保存失败', String(e?.response?.data?.detail || e.message || '保存失败'), 'danger');
    }
  };

  const saveIterationCandidate = async (record: Iteration, allowLowQuality = false) => {
    if (!task) return;
    const taskId = getTaskId(task);
    if (!taskId) {
      showThemeAlert('保存失败', '任务ID缺失，无法保存候选策略', 'danger');
      return;
    }
    setSavingIteration(record.iteration);
    try {
      const res: any = await api.post(
        `/agent/tasks/${taskId}/iterations/${record.iteration}/accept`,
        undefined,
        { params: { allow_low_quality: allowLowQuality } },
      );
      showThemeAlert(
        allowLowQuality ? '候选策略已保存（人工保留）' : '候选策略已保存',
        `策略已保存到策略库。\nID: ${res.strategy_id}\n名称: ${res.strategy_name}`,
        allowLowQuality ? 'warning' : 'default',
      );
      setForceSaveTarget(null);
      refreshTaskHistory();
    } catch (e: any) {
      showThemeAlert('保存失败', String(e?.response?.data?.detail || e.message || '保存失败'), 'danger');
    } finally {
      setSavingIteration(null);
    }
  };

  const handleAcceptSelected = async () => {
    if (!sel) return;
    const quality = getCandidateQuality(sel, goal);
    if (!quality.ok) {
      setForceSaveTarget(sel);
      return;
    }
    await saveIterationCandidate(sel, false);
  };

  const sel = selectedIter !== null ? iterations.find(i => i.iteration === selectedIter) : null;
  const selMetrics = sel?.backtest_metrics ?? {};
  const selectedQuality = getCandidateQuality(sel, goal);
  const bestIteration = task?.best_iteration !== null && task?.best_iteration !== undefined
    ? iterations.find((it) => it.iteration === task.best_iteration)
    : null;
  const canSaveBest = Boolean(task && bestIteration && getCandidateQuality(bestIteration, goal).ok);
  const candidates = useMemo(() => (
    iterations
      .filter((it) => !it.error && it.strategy_code && it.backtest_metrics)
      .filter((it) => getCandidateQuality(it, goal).ok)
      .map((it) => {
        const m = it.backtest_metrics || {};
        const totalReturn = Number(m.total_return_pct ?? 0);
        const sharpe = Number(m.sharpe_ratio ?? 0);
        const drawdown = Number(m.max_drawdown_pct ?? 100);
        const trades = Number(m.total_trades ?? 0);
        const profitFactor = Number(m.profit_factor ?? 0);
        const robustnessPenalty = trades < goal.min_total_trades ? 12 : 0;
        const hunterScore =
          Number(it.score ?? 0) * 0.45
          + Math.max(-20, Math.min(30, totalReturn)) * 0.7
          + Math.max(0, Math.min(3, sharpe)) * 10
          + Math.max(0, 25 - drawdown) * 0.8
          + Math.max(0, Math.min(3, profitFactor)) * 6
          - robustnessPenalty;
        return { iteration: it.iteration, record: it, hunterScore };
      })
      .sort((a, b) => b.hunterScore - a.hunterScore)
      .slice(0, 5)
  ), [goal, iterations]);
  const latestOptimizerRun = optimizerRuns[0] || null;
  const activeOptimizerRuns = optimizerRuns.filter((run) => run.status === 'running' || run.status === 'trial_running');
  const optimizerHasActiveRun = activeOptimizerRuns.length > 0 || Boolean(optimizerConfig?.running);
  const latestOptimizerRunDeletable = Boolean(latestOptimizerRun && canDeleteOptimizerRun(latestOptimizerRun));
  const latestAutonomousInstance = autonomousInstances[0] || null;
  const activeAutonomousInstances = autonomousInstances.filter((item) => item.status === 'running');
  const selectedAutonomousInstance = autonomousInstances.find((item) => item.strategy_id === selectedAutonomousId) || latestAutonomousInstance;
  const selectedAutonomousLogs = useMemo(
    () => (selectedAutonomousInstance?.events || []).slice(0, 8),
    [selectedAutonomousInstance?.events],
  );
  const latestAutonomousLog = selectedAutonomousLogs[0] || null;
  const autonomousConfiguredSymbols = autonomousSymbolsFromText(autonomousConfig.symbolsText);
  const aiDisplayedSymbols = useMemo(() => Array.from(new Set([
    ...autonomousConfiguredSymbols,
    ...autonomousInstances.flatMap((item) => item.symbols || []),
    ...autonomousSymbolsFromText(autonomousEditConfig?.symbolsText || ''),
  ])), [autonomousConfiguredSymbols.join(','), autonomousEditConfig?.symbolsText, autonomousInstances]);
  const aiSymbolNames = useSymbolNames(aiDisplayedSymbols);
  const autonomousModelOptions = Array.from(new Set([
    AUTONOMOUS_HERMES_MODEL,
    ...(autonomousModelConfig?.models?.length ? autonomousModelConfig.models : []),
    ...(autonomousModelConfig?.free_tier_models?.length ? autonomousModelConfig.free_tier_models : []),
    autonomousModelConfig?.model,
    autonomousModelConfig?.default_model,
    researchModel,
    optimizerModel,
    optimizerConfig?.llm_model || undefined,
    autonomousConfig.llmModel,
  ].filter((model): model is string => Boolean(model))));
  const autonomousEditModelOptions = Array.from(new Set([
    ...autonomousModelOptions,
    autonomousEditConfig?.llmModel,
  ].filter((model): model is string => Boolean(model))));
  const selectedAutonomousModel = autonomousConfig.llmModel || autonomousModelConfig?.model || autonomousModelOptions[0] || '';
  const selectedResearchModel = researchModel || task?.llm_model || autonomousModelConfig?.model || autonomousModelOptions[0] || '';
  const selectedOptimizerModel = optimizerModel || optimizerConfig?.llm_model || autonomousModelConfig?.model || autonomousModelOptions[0] || '';
  const selectedOrbitModel = orbitConfig.llmModel || autonomousModelConfig?.model || autonomousModelOptions[0] || '';
  const orbitEligibleCount = orbitCandidates.filter((item) => item.eligible).length;
  const autoAgentMarketScan = (autoAgentResult?.market_scan || {}) as Record<string, any>;
  const autoAgentRejected = Array.isArray(autoAgentMarketScan.rejected) ? autoAgentMarketScan.rejected : [];
  const autoAgentCandidates = Array.isArray(autoAgentMarketScan.candidates) ? autoAgentMarketScan.candidates : [];
  const autoAgentClosedLoop = (autoAgentResult?.closed_loop || null) as Record<string, any> | null;
  const autoAgentHermes = (autoAgentResult?.hermes_agent || {}) as Record<string, any>;
  const autoAgentSource = (autoAgentResult?.market_data_source || {}) as Record<string, any>;
  const autoAgentHasTradeIntent = Boolean(autoAgentResult?.trade_intent);
  const autoAgentDecision = autoAgentResult
    ? (autoAgentClosedLoop?.candidate_strategy
      ? '候选策略已生成'
      : autoAgentHasTradeIntent
        ? '已生成 paper 执行意图'
        : '不交易 / 等待数据')
    : '等待启动';
  const autoAgentBacktestLabel = autoAgentClosedLoop
    ? (autoAgentClosedLoop.status || '未进入回测矩阵')
    : (autoAgentResult?.selected_opportunity ? '回测矩阵结果缺失' : '无通过候选，未进入回测矩阵');
  const autoAgentHermesSummary = String(autoAgentHermes.stdout || '').trim();
  const autoAgentSchedulerConfig = autoAgentScheduler || AUTO_AGENT_DEFAULT_SCHEDULER;
  const autoAgentSchedulerSymbolsText = (autoAgentSchedulerConfig.symbols?.length ? autoAgentSchedulerConfig.symbols : AUTO_AGENT_DEFAULT_SYMBOLS).join(', ');
  const autoAgentSchedulerLastRun = autoAgentSchedulerConfig.last_run_at ? formatDateTime(autoAgentSchedulerConfig.last_run_at) : '尚未执行';
  const autoAgentSchedulerNextRun = autoAgentSchedulerConfig.enabled && autoAgentSchedulerConfig.last_run_at
    ? formatDateTime(new Date(new Date(autoAgentSchedulerConfig.last_run_at).getTime() + autoAgentSchedulerConfig.interval_minutes * 60_000).toISOString())
    : (autoAgentSchedulerConfig.enabled ? '等待调度器下一分钟检查' : '未开启');

  const refreshAutoAgentScheduler = async () => {
    try {
      const res = await api.get('/agent/strategy-assistant/scheduler') as { success?: boolean; data?: AutoAgentSchedulerConfig };
      setAutoAgentScheduler({ ...AUTO_AGENT_DEFAULT_SCHEDULER, ...((res?.data || res) as AutoAgentSchedulerConfig) });
    } catch (e: any) {
      setAutoAgentSchedulerStatus(e?.response?.data?.detail || e.message || '定时配置读取失败');
    }
  };

  const saveAutoAgentScheduler = async (enabled: boolean) => {
    const current = autoAgentSchedulerConfig;
    setAutoAgentSchedulerSaving(true);
    setAutoAgentSchedulerStatus(enabled ? '正在开启定时执行...' : '正在关闭定时执行...');
    try {
      const payload = {
        enabled,
        interval_minutes: Math.max(15, Math.min(Number(current.interval_minutes || 60), 1440)),
        symbols: current.symbols?.length ? current.symbols : AUTO_AGENT_DEFAULT_SYMBOLS,
        use_hermes_agent: current.use_hermes_agent !== false,
        max_candidates: Math.max(1, Math.min(Number(current.max_candidates || 5), 20)),
        preferred_direction: 'auto',
      };
      const res = await api.put('/agent/strategy-assistant/scheduler', payload) as { success?: boolean; data?: AutoAgentSchedulerConfig };
      const next = { ...AUTO_AGENT_DEFAULT_SCHEDULER, ...((res?.data || res) as AutoAgentSchedulerConfig) };
      setAutoAgentScheduler(next);
      setAutoAgentSchedulerStatus(next.enabled ? `定时执行已开启：每 ${next.interval_minutes} 分钟自动研发一次。` : '定时执行已关闭。');
    } catch (e: any) {
      setAutoAgentSchedulerStatus(e?.response?.data?.detail || e.message || '定时配置保存失败');
    } finally {
      setAutoAgentSchedulerSaving(false);
    }
  };

  const runAutoAgentScheduledNow = async () => {
    setAutoAgentSchedulerSaving(true);
    setAutoAgentSchedulerStatus('正在按定时配置立即触发一次研发...');
    try {
      const res = await api.post('/agent/strategy-assistant/scheduler/run-now') as { success?: boolean; data?: Record<string, any> };
      const data = (res?.data || res) as Record<string, any>;
      const runId = String(data.run_id || data.config?.last_run_id || '');
      if (data.config) setAutoAgentScheduler({ ...AUTO_AGENT_DEFAULT_SCHEDULER, ...(data.config as AutoAgentSchedulerConfig) });
      if (runId) {
        setAutoAgentRunId(runId);
        try { window.localStorage.setItem(AUTO_AGENT_RUN_STORAGE_KEY, runId); } catch { /* ignore */ }
        setAutoAgentSchedulerStatus(`已按定时配置触发一次研发：${runId}`);
        void pollAutoAgentRun(runId);
      } else {
        setAutoAgentSchedulerStatus(String(data.skipped || '已提交定时触发请求'));
      }
    } catch (e: any) {
      setAutoAgentSchedulerStatus(e?.response?.data?.detail || e.message || '立即触发定时研发失败');
    } finally {
      setAutoAgentSchedulerSaving(false);
    }
  };

  const updateAutoAgentRunState = (run: Record<string, any>) => {
    const result = run.result as Record<string, any> | null;
    if (result) setAutoAgentResult(result);
    const status = String(run.status || '');
    const stageLabel = String(run.stage_label || '');
    if (status === 'completed' && result) {
      const source = result.market_data_source || {};
      const hermes = result.hermes_agent || {};
      const closedLoop = result.closed_loop || {};
      const candidate = closedLoop.candidate_strategy;
      const count = Number(source.snapshots_count || 0);
      if (count <= 0) {
        setAutoAgentStatus('自动研发已完成，但服务器未采集到真实 A 股行情快照；系统不会编造机会，请先在数据页完成同步。');
      } else if (candidate?.name) {
        setAutoAgentStatus(`闭环完成：已采集 ${count} 个真实行情快照，完成 ${closedLoop.summary?.completed_count || 0} 组回测，产出候选策略「${candidate.name}」。仍然只允许 paper/simulation，实盘需人工审批。`);
      } else if (hermes.called) {
        const rejectedCount = Array.isArray(result.market_scan?.rejected) ? result.market_scan.rejected.length : 0;
        const matrixStatus = closedLoop.status || (result.selected_opportunity ? '回测矩阵结果缺失' : '无通过候选，未进入回测矩阵');
        setAutoAgentStatus(`自动研发已完成：已采集 ${count} 个真实行情快照，并已调用服务器 Hermes（${hermes.status || 'unknown'}）；${matrixStatus}；拒绝 ${rejectedCount} 个候选。`);
      } else {
        const matrixStatus = closedLoop.status || (result.selected_opportunity ? '回测矩阵结果缺失' : '无通过候选，未进入回测矩阵');
        setAutoAgentStatus(`已采集 ${count} 个真实行情快照并完成本地五 Agent 评分；Hermes 未调用（${hermes.status || 'not_called'}），${matrixStatus}。`);
      }
      setAutoAgentLoading(false);
      return;
    }
    if (status === 'failed') {
      setAutoAgentStatus(String(run.error || stageLabel || '自动研发失败'));
      setAutoAgentLoading(false);
      return;
    }
    setAutoAgentStatus(stageLabel || '自动研发正在运行；即使服务重启也会从持久化记录自动续跑');
    setAutoAgentLoading(true);
  };

  const pollAutoAgentRun = async (runId: string) => {
    if (!runId) return;
    try {
      const res = await api.get(`/agent/strategy-assistant/research-runs/${runId}`) as { success?: boolean; data?: Record<string, any> };
      const run = (res?.data || res) as Record<string, any>;
      updateAutoAgentRunState(run);
      if (run.status === 'completed' || run.status === 'failed') {
        return;
      }
      setTimeout(() => { void pollAutoAgentRun(runId); }, 3000);
    } catch (e: any) {
      setAutoAgentStatus(e?.response?.data?.detail || e.message || '自动研发状态读取失败');
      setAutoAgentLoading(false);
    }
  };

  const handleRunAutoAgentLocalCycle = async () => {
    setAutoAgentLoading(true);
    setAutoAgentStatus('正在创建可恢复的自动研发任务；服务重启后会自动续跑');
    try {
      const res = await api.post('/agent/strategy-assistant/research-runs', {
        objective: '自动判断 A 股高流动性标的的做多研发机会，调用服务器继续策略研究，但只允许 research/backtest/paper-simulation，不允许实盘下单。',
        snapshots: [],
        auto_collect_market: true,
        use_hermes_agent: true,
        preferred_direction: 'auto',
        symbols: AUTO_AGENT_DEFAULT_SYMBOLS,
      }) as { success?: boolean; data?: Record<string, any> };
      const run = (res?.data || res) as Record<string, any>;
      const runId = String(run.run_id || '');
      setAutoAgentRunId(runId);
      try { window.localStorage.setItem(AUTO_AGENT_RUN_STORAGE_KEY, runId); } catch { /* ignore */ }
      updateAutoAgentRunState(run);
      void pollAutoAgentRun(runId);
    } catch (e: any) {
      setAutoAgentStatus(e?.response?.data?.detail || e.message || '自动交易Agent自动研发启动失败');
      setAutoAgentLoading(false);
    }
  };
  useEffect(() => {
    void refreshAutoAgentScheduler();
    try {
      const rememberedRunId = window.localStorage.getItem(AUTO_AGENT_RUN_STORAGE_KEY) || '';
      if (rememberedRunId) {
        setAutoAgentRunId(rememberedRunId);
        void pollAutoAgentRun(rememberedRunId);
      }
    } catch {
      /* localStorage may be unavailable */
    }
  }, []);

  const switchTab = (next: AssistantTab) => {
    const params = new URLSearchParams(searchParams);
    params.set('tab', next);
    setSearchParams(params, { replace: true });
  };
  // 旧版 JSX 暂作迁移保留，实际 research Tab 只渲染独立的 ResearchWorkbench。
  const legacyResearchPanelDeprecated = false;

  return (
    <div className="p-4 h-full overflow-auto">
      {/* Header */}
      <div className="mb-4 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <Sparkles className="text-yellow-400" size={28} />
            AI策略助手
          </h1>
          <p className="mt-1 text-xs text-gray-500">A 股新策略研发与现有策略优化统一入口；执行类能力保持关闭</p>
        </div>
        <div className="flex items-center gap-3">
          {task && (
            <span className={`px-3 py-1 rounded-full text-xs font-bold ${
              task.status === 'running' ? 'bg-blue-500/20 text-blue-400 animate-pulse' :
              task.status === 'completed' ? 'bg-green-500/20 text-green-400' :
              task.status === 'failed' ? 'bg-red-500/20 text-red-400' :
              task.status === 'interrupted' ? 'bg-orange-500/20 text-orange-400' :
              task.status === 'stopped' ? 'bg-yellow-500/20 text-yellow-400' :
              'bg-gray-500/20 text-gray-400'
            }`}>
              {task.status === 'running' ? `运行中 (${task.current_iteration + 1}/${task.max_iterations})` :
               task.status === 'completed' ? '已完成' :
               task.status === 'failed' ? '失败' :
               task.status === 'interrupted' ? '服务重启已中断' :
               task.status === 'stopped' ? '已停止' : task.status}
            </span>
          )}
        </div>
      </div>

      <div className="mb-4 grid grid-cols-1 gap-2 rounded-xl border border-crypto-border bg-crypto-card p-1 lg:grid-cols-2">
        <button
          type="button"
          onClick={() => switchTab('auto-agent')}
          className={`hidden min-h-[62px] items-center gap-3 rounded-lg border px-4 py-3 text-left transition ${
            activeTab === 'auto-agent'
              ? SELECTED_SEGMENT_BORDER_CLASS
              : 'border-purple-500/30 bg-purple-950/45 text-purple-100/80 hover:border-purple-400/55 hover:bg-purple-900/45'
          }`}
        >
          <GitBranch size={18} className={activeTab === 'auto-agent' ? 'text-purple-300' : 'text-purple-500/70'} />
          <span className="min-w-0">
            <span className="block text-sm font-semibold">自动交易Agent</span>
            <span className="block truncate text-[11px] text-current/60">五 Agent 闭环、paper/simulation only</span>
          </span>
        </button>
        <button
          type="button"
          onClick={() => switchTab('autonomous')}
          className={`hidden min-h-[62px] items-center gap-3 rounded-lg border px-4 py-3 text-left transition ${
            activeTab === 'autonomous'
              ? SELECTED_SEGMENT_BORDER_CLASS
              : 'border-yellow-500/30 bg-yellow-950/45 text-yellow-100/80 hover:border-yellow-400/55 hover:bg-yellow-900/45'
          }`}
        >
          <Activity size={18} className={activeTab === 'autonomous' ? 'text-yellow-300' : 'text-yellow-500/70'} />
          <span className="min-w-0">
            <span className="block text-sm font-semibold">AI自主交易</span>
            <span className="block truncate text-[11px] text-current/60">模拟盘限定、硬性风控、监控追踪</span>
          </span>
        </button>
        <button
          type="button"
          onClick={() => switchTab('research')}
          className={`flex min-h-[62px] items-center gap-3 rounded-lg border px-4 py-3 text-left transition ${
            activeTab === 'research'
              ? SELECTED_SEGMENT_BORDER_CLASS
              : 'border-blue-500/30 bg-blue-950/45 text-blue-100/80 hover:border-blue-400/55 hover:bg-blue-900/45'
          }`}
        >
          <Sparkles size={18} className={activeTab === 'research' ? 'text-blue-300' : 'text-blue-500/70'} />
          <span className="min-w-0">
            <span className="block text-sm font-semibold">新策略研发</span>
            <span className="block truncate text-[11px] text-current/60">AI 策略猎手、迭代流水线、候选策略池</span>
          </span>
        </button>
        <button
          type="button"
          onClick={() => switchTab('optimizer')}
          className={`flex min-h-[62px] items-center gap-3 rounded-lg border px-4 py-3 text-left transition ${
            activeTab === 'optimizer'
              ? SELECTED_SEGMENT_BORDER_CLASS
              : 'border-emerald-500/30 bg-emerald-950/45 text-emerald-100/80 hover:border-emerald-400/55 hover:bg-emerald-900/45'
          }`}
        >
          <Wrench size={18} className={activeTab === 'optimizer' ? 'text-green-300' : 'text-emerald-500/70'} />
          <span className="min-w-0">
            <span className="block text-sm font-semibold">现有策略优化</span>
            <span className="block truncate text-[11px] text-current/60">日线扫描、AI 诊断、候选试运行</span>
          </span>
        </button>
        <button
          type="button"
          onClick={() => switchTab('orbit-post')}
          className={`hidden min-h-[62px] items-center gap-3 rounded-lg border px-4 py-3 text-left transition ${
            activeTab === 'orbit-post'
              ? SELECTED_SEGMENT_BORDER_CLASS
              : 'border-cyan-500/30 bg-cyan-950/45 text-cyan-100/80 hover:border-cyan-400/55 hover:bg-cyan-900/45'
          }`}
        >
          <Send size={18} className={activeTab === 'orbit-post' ? 'text-cyan-300' : 'text-cyan-500/70'} />
          <span className="min-w-0">
            <span className="block text-sm font-semibold">星球发帖</span>
            <span className="block truncate text-[11px] text-current/60">单账号自动发帖、真实合约单</span>
          </span>
        </button>
      </div>

      {error && <div className="bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-2 rounded mb-4">{error}</div>}

      {activeTab === 'orbit-post' && (
        <OrbitPostPanel {...{
          autonomousModelOptions, handlePublishOrbitCandidate, handleRunOrbitAutoPost,
          handleSaveOrbitConfig, orbitCandidates, orbitConfig, orbitEligibleCount, orbitHistory,
          orbitLoading, orbitLoginStatus, orbitPublishingId, orbitRunning, orbitSaving, orbitStatus,
          refreshOrbitAutoPost, selectedOrbitModel, setOrbitConfig,
        }} />
      )}

      {activeTab === 'auto-agent' && (
        <AutoAgentPanel {...{
          autoAgentBacktestLabel, autoAgentCandidates, autoAgentClosedLoop, autoAgentDecision,
          autoAgentHermes, autoAgentHermesSummary, autoAgentLoading, autoAgentMarketScan,
          autoAgentRejected, autoAgentResult, autoAgentRunId, autoAgentSchedulerConfig,
          autoAgentSchedulerLastRun, autoAgentSchedulerNextRun, autoAgentSchedulerOpen,
          autoAgentSchedulerSaving, autoAgentSchedulerStatus, autoAgentSchedulerSymbolsText,
          autoAgentSource, autoAgentStatus, handleRunAutoAgentLocalCycle, pollAutoAgentRun,
          refreshAutoAgentScheduler, runAutoAgentScheduledNow, saveAutoAgentScheduler,
          setAutoAgentScheduler, setAutoAgentSchedulerOpen,
        }} />
      )}

      {activeTab === 'optimizer' && (
      <div className="bg-crypto-card border border-crypto-border rounded-xl p-4 mb-4">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
                <Wrench size={16} className="text-green-400" />
                现有策略优化
              </h2>
              <span className={`rounded-full px-2 py-0.5 text-[11px] ${
                optimizerConfig?.enabled ? 'bg-green-500/15 text-green-400' : 'bg-gray-500/15 text-gray-400'
              }`}>
                {optimizerConfig?.enabled ? '自动优化开启' : '自动优化关闭'}
              </span>
              {optimizerConfig?.running && (
                <span className="rounded-full bg-blue-500/15 px-2 py-0.5 text-[11px] text-blue-300">扫描中</span>
              )}
            </div>
            <p className="mt-1 text-xs text-gray-500">
              每 4 小时扫描运行中的模拟盘；运行满 4h 且收益率低于 0% 时，AI 生成优化候选并先独立试运行。
            </p>
          </div>

          <div className="flex flex-wrap items-end gap-2">
            <label className="flex min-w-[220px] flex-col gap-1 text-[11px] text-gray-500">
              <span>AI模型</span>
              <CryptoSelect
                value={selectedOptimizerModel}
                onChange={(e) => setOptimizerModel(e.target.value)}
                disabled={optimizerLoading || optimizerConfig?.running}
                controlSize="sm"
              >
                {autonomousModelOptions.length > 0 ? (
                  autonomousModelOptions.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))
                ) : (
                  <option value="">暂无可用模型</option>
                )}
              </CryptoSelect>
            </label>
            <button
              type="button"
              onClick={handleToggleOptimizer}
              disabled={optimizerSaving || optimizerLoading || !optimizerConfig}
              className={`inline-flex h-9 items-center gap-2 rounded-lg px-4 text-sm font-semibold transition disabled:opacity-50 ${
                optimizerConfig?.enabled
                  ? 'border border-green-500/40 bg-green-500/10 text-green-300 hover:border-green-400'
                  : 'border border-crypto-border text-gray-300 hover:border-blue-500 hover:text-blue-300'
              }`}
            >
              {optimizerConfig?.enabled ? <PauseCircle size={15} /> : <Play size={15} />}
              {optimizerSaving ? '保存中...' : optimizerConfig?.enabled ? '关闭自动优化' : '开启自动优化'}
            </button>
            <button
              type="button"
              onClick={handleRunOptimizerNow}
              disabled={optimizerRunningNow || optimizerConfig?.running}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-50"
            >
              <RefreshCw size={15} className={optimizerRunningNow || optimizerConfig?.running ? 'animate-spin' : ''} />
              立即执行一次
            </button>
            {optimizerHasActiveRun && (
              <button
                type="button"
                onClick={handleStopOptimizer}
                disabled={optimizerStopping}
                className="inline-flex h-9 items-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-4 text-sm font-semibold text-red-300 hover:bg-red-500/15 disabled:opacity-50"
              >
                <Square size={14} />
                {optimizerStopping ? '停止中...' : '停止优化'}
              </button>
            )}
            <button
              type="button"
              onClick={refreshOptimizer}
              disabled={optimizerLoading}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border px-3 text-sm font-semibold text-gray-300 hover:border-blue-500 hover:text-blue-300 disabled:opacity-50"
            >
              <RefreshCw size={14} className={optimizerLoading ? 'animate-spin' : ''} />
              刷新
            </button>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 xl:grid-cols-4">
          <div className="rounded-lg border border-crypto-border bg-crypto-bg p-3">
            <div className="text-[11px] text-gray-500">下次自动扫描</div>
            <div className="mt-1 truncate text-sm font-semibold text-gray-200">{optimizerConfig?.next_run_at || '--'}</div>
          </div>
          <div className="rounded-lg border border-crypto-border bg-crypto-bg p-3">
            <div className="text-[11px] text-gray-500">低收益阈值</div>
            <div className="mt-1 text-sm font-semibold text-gray-200">&lt; {fmtPct(optimizerConfig?.low_return_pct ?? 0)}</div>
          </div>
          <div className="rounded-lg border border-crypto-border bg-crypto-bg p-3">
            <div className="text-[11px] text-gray-500">活跃优化</div>
            <div className="mt-1 text-sm font-semibold text-gray-200">{activeOptimizerRuns.length} 个</div>
          </div>
          <div className="rounded-lg border border-crypto-border bg-crypto-bg p-3">
            <div className="text-[11px] text-gray-500">最近结果</div>
            <div className="mt-1 truncate text-sm font-semibold text-gray-200">{optimizerStatusText(latestOptimizerRun)}</div>
          </div>
        </div>

        <div className="mt-4">
          <StrategyOptimizerPipeline run={latestOptimizerRun} />
        </div>

        {optimizerStatus && (
          <div className={`mt-3 text-xs ${optimizerStatus.includes('失败') ? 'text-red-400' : 'text-blue-300'}`}>
            {optimizerStatus}
          </div>
        )}

        <div className="mt-4 flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-gray-300">{optimizerHasActiveRun ? '当前优化' : '最近优化结果'}</h3>
          <span className="text-[11px] text-gray-600">{optimizerRuns.length} 条记录</span>
        </div>

        {latestOptimizerRun ? (
          <div className="mt-4 rounded-lg border border-crypto-border bg-crypto-bg p-3">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="min-w-0 truncate text-sm font-semibold text-white">
                    {latestOptimizerRun.source_strategy_name || `策略 #${latestOptimizerRun.source_strategy_id}`}
                  </div>
                  <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${
                    latestOptimizerRun.status === 'replaced' ? 'bg-green-500/15 text-green-400' :
                    latestOptimizerRun.status === 'failed' ? 'bg-red-500/15 text-red-400' :
                    latestOptimizerRun.status === 'trial_running' ? 'bg-orange-500/15 text-orange-300' :
                    latestOptimizerRun.status === 'cancelled' ? 'bg-blue-500/15 text-blue-300' :
                    'bg-blue-500/15 text-blue-300'
                  }`}>
                    {optimizerStatusText(latestOptimizerRun)}
                  </span>
                </div>
                <div className="mt-1 text-[11px] text-gray-500">
                  源策略 #{latestOptimizerRun.source_strategy_id}
                  {latestOptimizerRun.candidate_strategy_id ? ` · 候选 #${latestOptimizerRun.candidate_strategy_id}` : ''}
                  {latestOptimizerRun.source_return_pct != null ? ` · 源收益 ${fmtPct(latestOptimizerRun.source_return_pct)}` : ''}
                  {latestOptimizerRun.candidate_return_pct != null ? ` · 候选收益 ${fmtPct(latestOptimizerRun.candidate_return_pct)}` : ''}
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-2">
                {(latestOptimizerRun.status === 'running' || latestOptimizerRun.status === 'trial_running') && (
                  <button
                    type="button"
                    onClick={() => handleCancelOptimizerRun(latestOptimizerRun.id)}
                    className="inline-flex h-8 items-center justify-center rounded-lg border border-red-500/40 px-3 text-xs font-semibold text-red-300 hover:bg-red-500/10"
                  >
                    停止
                  </button>
                )}
                {latestOptimizerRunDeletable && (
                  <button
                    type="button"
                    disabled={deletingOptimizerRunId === latestOptimizerRun.id}
                    onClick={() => setOptimizerDeleteTarget(latestOptimizerRun)}
                    className="inline-flex h-8 items-center justify-center gap-1 rounded-lg border border-red-500/30 bg-red-500/5 px-3 text-xs font-semibold text-red-300 hover:border-red-400/70 hover:bg-red-500/10 hover:text-red-200 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Trash2 size={13} />
                    删除
                  </button>
                )}
              </div>
            </div>
            {latestOptimizerRun.error_message && (
              <div className="mt-2 rounded border border-red-500/25 bg-red-500/10 px-2 py-1 text-xs text-red-300">
                {latestOptimizerRun.error_message}
              </div>
            )}
          </div>
        ) : (
          <div className="mt-4 rounded-lg border border-dashed border-crypto-border bg-crypto-bg px-3 py-5 text-center text-xs text-gray-500">
            暂无优化记录
          </div>
        )}

        {optimizerRuns.length > 1 && (
          <>
          <h3 className="mt-4 text-sm font-semibold text-gray-300">优化历史</h3>
          <div className="mt-3 grid grid-cols-1 gap-2 xl:grid-cols-4">
            {optimizerRuns.slice(1, 9).map((run) => {
              const deletable = canDeleteOptimizerRun(run);
              return (
                <div key={run.id} className="rounded-lg border border-crypto-border bg-crypto-bg p-3">
                  <div className="flex items-start justify-between gap-2">
                    <span className="min-w-0 truncate text-xs font-semibold text-gray-200">
                      {getOptimizerRunTitle(run)}
                    </span>
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${
                      run.status === 'replaced' ? 'bg-green-500/15 text-green-400' :
                      run.status === 'failed' ? 'bg-red-500/15 text-red-400' :
                      run.status === 'trial_running' ? 'bg-orange-500/15 text-orange-300' :
                      'bg-blue-500/15 text-blue-300'
                    }`}>
                      {optimizerStatusText(run)}
                    </span>
                  </div>
                  <div className="mt-2 text-[11px] text-gray-500">
                    源 #{run.source_strategy_id}
                    {run.candidate_strategy_id ? ` · 候选 #${run.candidate_strategy_id}` : ''}
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    {(run.status === 'running' || run.status === 'trial_running') && (
                      <button
                        type="button"
                        onClick={() => handleCancelOptimizerRun(run.id)}
                        className="inline-flex h-7 items-center justify-center rounded-md border border-red-500/40 px-2 text-[11px] font-semibold text-red-300 hover:bg-red-500/10"
                      >
                        停止
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={!deletable || deletingOptimizerRunId === run.id}
                      title={deletable ? '删除优化记录' : '运行中的优化需先停止'}
                      onClick={() => setOptimizerDeleteTarget(run)}
                      className="inline-flex h-7 items-center justify-center gap-1 rounded-md border border-red-500/30 bg-red-500/5 px-2 text-[11px] font-semibold text-red-300 hover:border-red-400/70 hover:bg-red-500/10 hover:text-red-200 disabled:cursor-not-allowed disabled:border-gray-700 disabled:bg-transparent disabled:text-gray-600"
                    >
                      <Trash2 size={12} />
                      删除
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
          </>
        )}
      </div>
      )}

      {activeTab === 'autonomous' && (
      <div className="space-y-4">
        <div className="rounded-xl border border-yellow-500/25 bg-crypto-card p-4">
          <div className="flex flex-col gap-4 2xl:flex-row 2xl:items-center 2xl:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="flex items-center gap-2 text-base font-semibold text-gray-100">
                  <Activity size={18} className="text-yellow-300" />
                  AI自主交易控制台
                </h2>
                <span className="rounded-full bg-yellow-500/15 px-2 py-0.5 text-[11px] font-semibold text-yellow-300">仅模拟盘</span>
                <span className="rounded-full bg-blue-500/15 px-2 py-0.5 text-[11px] font-semibold text-blue-300">A 股模拟盘</span>
              </div>
              <p className="mt-1 max-w-3xl text-xs leading-relaxed text-gray-500">
                AI 只在人工风控信封内做模拟盘决策；首页负责启动、风控和实例操作，逐笔决策与成交明细进入监控页查看。
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={refreshAutonomousTrader}
                disabled={autonomousLoading}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-crypto-border px-3 text-sm font-semibold text-gray-300 hover:border-yellow-500 hover:text-yellow-300 disabled:opacity-50"
              >
                <RefreshCw size={14} className={autonomousLoading ? 'animate-spin' : ''} />
                刷新
              </button>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-8">
            <MetricCard label="运行中" value={`${activeAutonomousInstances.length}/${autonomousInstances.length}`} tone="info" />
            <MetricCard label="当前查看" value={selectedAutonomousInstance ? `#${selectedAutonomousInstance.strategy_id}` : '--'} />
            <MetricCard label="权益" value={fmtNumber(selectedAutonomousInstance?.dashboard?.equity, 2)} />
            <MetricCard label="收益率" value={fmtPct(selectedAutonomousInstance?.dashboard?.return_pct)} tone={signedMarketTone(selectedAutonomousInstance?.dashboard?.return_pct)} />
            <MetricCard label="胜率" value={fmtPct(selectedAutonomousInstance?.dashboard?.win_rate)} />
            <MetricCard label="盈亏比" value={fmtNumber(selectedAutonomousInstance?.dashboard?.profit_factor)} />
            <MetricCard label="交易数" value={selectedAutonomousInstance?.dashboard?.total_trades ?? '--'} tone="info" />
            <MetricCard label="未实现盈亏" value={fmtNumber(selectedAutonomousInstance?.dashboard?.unrealized_pnl, 2)} tone={signedMarketTone(selectedAutonomousInstance?.dashboard?.unrealized_pnl)} />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
            <span className="rounded-md border border-cyan-500/25 bg-cyan-500/10 px-2 py-1 text-cyan-200">
              提供方 {autonomousConfig.llmProvider === 'hermes' ? AUTONOMOUS_HERMES_PROVIDER_LABEL : 'DashScope / Qwen'}
            </span>
            <span className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-1">模型 {selectedAutonomousModel || '--'}</span>
            <span className="rounded-md border border-red-500/25 bg-red-500/10 px-2 py-1 text-red-200">
              方向 {autonomousConfig.tradeDirection === 'short_only' ? '只做空' : '多空双向'}
            </span>
            <span className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-1">
              标的 {autonomousConfig.restrictSymbols ? autonomousConfiguredSymbols.length : '不限制'}
            </span>
            <span className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-1">仓位上限 ≤ {autonomousConfig.maxSinglePositionPct}%</span>
            <span className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-1">单笔 ≤ {autonomousConfig.maxSinglePositionPct}%</span>
            <span className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-1">总敞口 ≤ {autonomousConfig.maxTotalExposurePct}%</span>
            <span className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-1">间隔 ≥ {autonomousConfig.minDecisionIntervalSec}s</span>
            <span className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-1">每小时 ≤ {autonomousConfig.maxTradesPerHour} 笔</span>
          </div>

          {autonomousStatus && (
            <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${
              autonomousStatus.includes('失败')
                ? 'border-red-500/30 bg-red-500/10 text-red-300'
                : 'border-blue-500/30 bg-blue-500/10 text-blue-300'
            }`}>
              {autonomousStatus}
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
          <div className="space-y-3 xl:col-span-4">
            <div className="rounded-xl border border-crypto-border bg-crypto-card p-4">
              <div className="mb-3 flex items-center justify-between gap-2">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-200">
                  <Target size={15} className="text-yellow-300" />
                  启动参数
                </h3>
                <div className="flex items-center gap-2">
                  <span className="rounded-full bg-crypto-bg px-2 py-0.5 text-[10px] text-gray-500">新实例生效</span>
                  <button
                    type="button"
                    onClick={handleStartAutonomousTrader}
                    disabled={autonomousStarting}
                    className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg bg-yellow-600 px-3 text-xs font-semibold text-white hover:bg-yellow-500 disabled:opacity-50"
                  >
                    <Play size={13} />
                    {autonomousStarting ? '启动中...' : '启动新实例'}
                  </button>
                </div>
              </div>
              <div className="space-y-3">
              <div className={autonomousParameterCardClass}>
                <label className="text-xs text-gray-400">AI提供方</label>
                <CryptoSelect
                  value={autonomousConfig.llmProvider}
                  onChange={(e) => updateAutonomousConfig('llmProvider', e.target.value)}
                  wrapperClassName="mt-1"
                >
                  <option value="hermes">{AUTONOMOUS_HERMES_PROVIDER_LABEL}</option>
                  <option value="dashscope">DashScope / Qwen</option>
                </CryptoSelect>
                <div className="mt-1 text-[11px] text-gray-600">
                  Hermes / Codex 走服务器本地 Hermes 配置，仍然只执行模拟盘。
                </div>
              </div>
              <div className={autonomousParameterCardClass}>
                <label className="text-xs text-gray-400">AI模型</label>
                <CryptoSelect
                  value={selectedAutonomousModel}
                  onChange={(e) => updateAutonomousConfig('llmModel', e.target.value)}
                  wrapperClassName="mt-1"
                >
                  {autonomousModelOptions.length > 0 ? (
                    autonomousModelOptions.map((model) => (
                      <option key={model} value={model}>
                        {model}
                      </option>
                    ))
                  ) : (
                    <option value="">暂无可用模型</option>
                  )}
                </CryptoSelect>
                <div className="mt-1 text-[11px] text-gray-600">
                  候选模型来自全局配置；百炼免费额度耗尽时会自动尝试下一个免费候选。
                </div>
              </div>
              <div className={autonomousParameterCardClass}>
                <label className="text-xs text-gray-400">交易方向</label>
                <CryptoSelect
                  value={autonomousConfig.tradeDirection}
                  onChange={(e) => updateAutonomousConfig('tradeDirection', e.target.value)}
                  wrapperClassName="mt-1"
                >
                  <option value="short_only">只做空</option>
                  <option value="long_short">多空双向</option>
                </CryptoSelect>
                <div className="mt-1 text-[11px] text-gray-600">
                  只做空模式会在后端硬拦截 open_long 决策。
                </div>
              </div>
              <div className={autonomousParameterCardClass}>
                <label className="text-xs text-gray-400">提示词</label>
                <textarea
                  value={autonomousConfig.promptText}
                  onChange={(e) => updateAutonomousConfig('promptText', e.target.value)}
                  rows={3}
                  maxLength={4000}
                  className="mt-1 w-full resize-y rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 text-sm leading-relaxed text-gray-100 focus:border-yellow-500 focus:outline-none"
                  placeholder="例如：偏向趋势突破，避免高频交易；只有波动扩张或强弱分化明显时试单。"
                />
                <div className="mt-1 text-[11px] text-gray-600">
                  作为本实例的人工偏好传给 AI；硬性风控仍以数值上限为准。
                </div>
              </div>
              <div className={autonomousParameterCardClass}>
                <div className="flex items-center justify-between gap-3">
                  <label className="text-xs text-gray-400">合约标的池</label>
                  <label className="inline-flex cursor-pointer items-center gap-2 text-[11px] text-gray-400">
                    <span>{autonomousConfig.restrictSymbols ? '限制标的' : '不限制标的'}</span>
                    <input
                      type="checkbox"
                      checked={autonomousConfig.restrictSymbols}
                      onChange={(e) => updateAutonomousConfig('restrictSymbols', e.target.checked)}
                      className="peer sr-only"
                    />
                    <span className={clsx(
                      'relative h-5 w-9 rounded-full border transition',
                      autonomousConfig.restrictSymbols
                        ? 'border-yellow-500/60 bg-yellow-500/25'
                        : 'border-crypto-border bg-crypto-bg',
                    )}>
                      <span className={clsx(
                        'absolute top-0.5 h-3.5 w-3.5 rounded-full transition',
                        autonomousConfig.restrictSymbols ? 'left-4 bg-yellow-300' : 'left-0.5 bg-gray-500',
                      )} />
                    </span>
                  </label>
                </div>
                <textarea
                  value={autonomousConfig.symbolsText}
                  onChange={(e) => updateAutonomousConfig('symbolsText', e.target.value)}
                  disabled={!autonomousConfig.restrictSymbols}
                  rows={4}
                  className="mt-1 w-full resize-y rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 text-sm leading-relaxed text-gray-100 focus:border-yellow-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-45"
                  placeholder={autonomousConfig.restrictSymbols ? '600519.SH, 000001.SZ, 300750.SZ' : '关闭时使用系统全量 A 股候选池'}
                />
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {autonomousConfig.restrictSymbols ? (
                    <>
                      {autonomousConfiguredSymbols.slice(0, 8).map((symbol) => (
                        <span key={symbol} className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-0.5 text-[10px] text-gray-400">
                          {formatSymbolLabel(symbol, aiSymbolNames[symbol])}
                        </span>
                      ))}
                      {autonomousConfiguredSymbols.length > 8 && (
                        <span className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-0.5 text-[10px] text-gray-500">
                          +{autonomousConfiguredSymbols.length - 8}
                        </span>
                      )}
                    </>
                  ) : (
                    <span className="rounded-md border border-yellow-500/20 bg-yellow-500/10 px-2 py-0.5 text-[10px] text-yellow-300">
                      不限制：使用系统默认高流动性 A 股候选池
                    </span>
                  )}
                </div>
              </div>
              </div>

              <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                {([
                  ['maxLeverageCap', '单票上限', '≤ x', 1, 20, 0.5],
                  ['maxSinglePositionPct', '单笔仓位', '≤ %', 1, 100, 1],
                  ['maxTotalExposurePct', '总风险敞口', '≤ %', 1, 500, 1],
                  ['maxPositions', '最多持仓', '≤ 个', 1, 20, 1],
                  ['minDecisionIntervalSec', '决策间隔', '≥ 秒', 30, 3600, 10],
                  ['maxDecisionIntervalSec', '最长等待', '≤ 秒', 30, 3600, 10],
                  ['probeSizePct', '试单仓位', '%', 0.1, 100, 0.5],
                  ['maxTradesPerHour', '每小时交易', '≤ 笔', 1, 120, 1],
                  ['initialCapital', '初始资金', 'CNY', 100, 1000000, 100],
                ] as [AutonomousNumericConfigKey, string, string, number, number, number][]).map(([key, label, suffix, min, max, step]) => (
                  <label key={key} className={autonomousRiskParameterCardClass}>
                    <span className="block text-[11px] text-gray-500">{label}</span>
                    <div className="mt-1 flex items-center gap-2">
                      <input
                        type="text"
                        inputMode="decimal"
                        min={min}
                        max={max}
                        step={step}
                        value={autonomousNumberDrafts[key] ?? String(autonomousConfig[key])}
                        onChange={(e) => updateAutonomousConfig(key, e.target.value)}
                        onBlur={() => commitAutonomousNumericConfig(key, min, max)}
                        className="h-9 min-w-0 flex-1 rounded-md border border-crypto-border bg-black/20 px-2 text-center text-sm font-semibold text-gray-100 focus:border-yellow-500 focus:outline-none"
                      />
                      <span className="shrink-0 text-[11px] text-gray-500">{suffix}</span>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-yellow-500/25 bg-yellow-500/5 p-4">
              <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-yellow-200">
                <AlertCircle size={15} />
                系统硬边界
              </h3>
              <div className="grid gap-2 text-xs leading-relaxed text-gray-400">
                <div className="rounded-lg border border-yellow-500/15 bg-black/10 px-3 py-2">只创建 A 股模拟盘，遵守 T+1 / 100 股 / 只做多。</div>
                <div className="rounded-lg border border-yellow-500/15 bg-black/10 px-3 py-2">AI 超过任一上限时只记录风控拦截。</div>
                <div className="rounded-lg border border-yellow-500/15 bg-black/10 px-3 py-2">完整指标、AI 决策和成交明细统一进入模拟盘监控。</div>
              </div>
            </div>
          </div>

          <div className="space-y-3 xl:col-span-8">
            <div className="rounded-xl border border-crypto-border bg-crypto-card p-4">
              <div className="mb-3 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-gray-200">实例操作台</h3>
                  <p className="mt-0.5 text-[11px] text-gray-500">点击实例卡片切换顶部摘要；打开监控查看完整 AI 决策、成交和指标。</p>
                </div>
                <span className="text-[11px] text-gray-600">{autonomousInstances.length} 条记录</span>
              </div>

              {autonomousInstances.length > 0 ? (
                <div className="space-y-3">
                  {autonomousInstances.slice(0, 8).map((item) => {
                    const selected = selectedAutonomousInstance?.strategy_id === item.strategy_id;
                    const configItems = autonomousInstanceConfigItems(item.config);
                    const itemStatus = String(item.status || '').toLowerCase();
                    return (
                      <div
                        key={item.strategy_id}
                        onClick={() => setSelectedAutonomousId(item.strategy_id)}
                        className={`cursor-pointer rounded-xl border bg-crypto-bg p-3 transition ${
                          selected ? 'border-yellow-400/60 shadow-[0_0_0_1px_rgba(250,204,21,0.12)]' : 'border-crypto-border hover:border-blue-500/40'
                        }`}
                      >
                        <div className="flex flex-col gap-3 2xl:flex-row 2xl:items-start 2xl:justify-between">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="truncate text-sm font-semibold text-white">{item.name}</span>
                              <span className={`rounded-full px-2 py-0.5 text-[10px] ${autonomousStatusClass(item.status)}`}>
                                {autonomousStatusText(item.status)}
                              </span>
                              {selected && <span className="rounded-full bg-yellow-500/15 px-2 py-0.5 text-[10px] text-yellow-300">当前查看</span>}
                            </div>
                            <div className="mt-1 text-[11px] text-gray-500">#{item.strategy_id}</div>
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {(item.symbols || []).slice(0, 6).map((symbol) => (
                                <span key={symbol} className="rounded-md border border-crypto-border bg-crypto-card px-2 py-0.5 text-[10px] text-gray-400">
                                  {formatSymbolLabel(symbol, aiSymbolNames[symbol])}
                                </span>
                              ))}
                              {(item.symbols || []).length > 6 && (
                                <span className="rounded-md border border-crypto-border bg-crypto-card px-2 py-0.5 text-[10px] text-gray-500">
                                  +{(item.symbols || []).length - 6}
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="flex flex-wrap items-center gap-2" onClick={(e) => e.stopPropagation()}>
                            <button
                              type="button"
                              onClick={() => openAutonomousConfigEditor(item)}
                              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-yellow-500/40 px-3 text-xs font-semibold text-yellow-200 hover:bg-yellow-500/10"
                            >
                              <Settings size={13} />
                              编辑配置
                            </button>
                            <a
                              href={`/live?strategyId=${item.strategy_id}`}
                              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-blue-500/40 px-3 text-xs font-semibold text-blue-300 hover:bg-blue-500/10"
                            >
                              <Activity size={13} />
                              打开监控
                            </a>
                            {itemStatus === 'running' && (
                              <button
                                type="button"
                                onClick={() => handlePauseAutonomousTrader(item.strategy_id)}
                                disabled={autonomousLifecycleActionId === item.strategy_id}
                                className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-red-500/40 px-3 text-xs font-semibold text-red-300 hover:bg-red-500/10 disabled:opacity-50"
                              >
                                <PauseCircle size={13} />
                                {autonomousLifecycleActionId === item.strategy_id ? '暂停中...' : '暂停'}
                              </button>
                            )}
                            {['paused', 'stopped'].includes(itemStatus) && (
                              <button
                                type="button"
                                onClick={() => handleResumeAutonomousTrader(item.strategy_id)}
                                disabled={autonomousLifecycleActionId === item.strategy_id}
                                className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-green-500/40 px-3 text-xs font-semibold text-green-300 hover:bg-green-500/10 disabled:opacity-50"
                              >
                                <Play size={13} />
                                {autonomousLifecycleActionId === item.strategy_id ? '继续中...' : '继续'}
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => setAutonomousDeleteTarget(item)}
                              disabled={deletingAutonomousId === item.strategy_id || autonomousLifecycleActionId === item.strategy_id}
                              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-red-500/40 px-3 text-xs font-semibold text-red-300 hover:bg-red-500/10 disabled:opacity-50"
                              title="删除实例"
                            >
                              <Trash2 size={13} />
                              {deletingAutonomousId === item.strategy_id ? '删除中...' : '删除'}
                            </button>
                          </div>
                        </div>
                        <div className="mt-3 grid grid-cols-2 gap-2 xl:grid-cols-6">
                          <MetricCard label="权益" value={fmtNumber(item.dashboard?.equity, 2)} />
                          <MetricCard label="收益率" value={fmtPct(item.dashboard?.return_pct)} tone={signedMarketTone(item.dashboard?.return_pct)} />
                          <MetricCard label="胜率" value={fmtPct(item.dashboard?.win_rate)} />
                          <MetricCard label="盈亏比" value={fmtNumber(item.dashboard?.profit_factor)} />
                          <MetricCard label="交易数" value={item.dashboard?.total_trades ?? '--'} tone="info" />
                          <MetricCard label="未实现盈亏" value={fmtNumber(item.dashboard?.unrealized_pnl, 2)} tone={signedMarketTone(item.dashboard?.unrealized_pnl)} />
                        </div>
                        {selected && (
                          <>
                            <div className="mt-3 rounded-lg border border-crypto-border bg-crypto-card/45 p-3">
                              <div className="mb-2 text-[11px] font-semibold text-gray-400">配置参数</div>
                              <div className="grid grid-cols-2 gap-2 md:grid-cols-3 2xl:grid-cols-6">
                                {configItems.map((configItem) => (
                                  <div key={configItem.label} className="rounded-md border border-crypto-border bg-black/15 px-2.5 py-2">
                                    <div className="text-[10px] text-gray-500">{configItem.label}</div>
                                    <div className="mt-0.5 truncate text-xs font-semibold text-gray-200">{configItem.value}</div>
                                  </div>
                                ))}
                              </div>
                            </div>

                            <div className="mt-3 overflow-hidden rounded-lg border border-crypto-border bg-black/10">
                              <div className={`flex flex-col gap-2 px-3 py-2 lg:flex-row lg:items-center lg:justify-between ${autonomousLogsOpen ? 'border-b border-crypto-border' : ''}`}>
                                <button
                                  type="button"
                                  aria-expanded={autonomousLogsOpen}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setAutonomousLogsOpen((open) => !open);
                                  }}
                                  className="flex min-w-0 flex-1 items-center gap-2 rounded-md text-left transition hover:text-cyan-200"
                                >
                                  {autonomousLogsOpen ? (
                                    <ChevronDown size={15} className="shrink-0 text-gray-400" />
                                  ) : (
                                    <ChevronRight size={15} className="shrink-0 text-gray-400" />
                                  )}
                                  <Terminal size={15} className="shrink-0 text-cyan-400" />
                                  <span className="shrink-0 text-sm font-semibold text-gray-200">最新日志</span>
                                  <span className="shrink-0 text-[11px] text-gray-500">#{item.strategy_id}</span>
                                  {!autonomousLogsOpen && latestAutonomousLog && (
                                    <span className="min-w-0 flex-1 truncate text-[11px] font-normal text-cyan-300">
                                      {formatAutonomousLogTime(latestAutonomousLog.timestamp ?? latestAutonomousLog.ts ?? latestAutonomousLog.time)}
                                      {' · '}
                                      {autonomousLogTitle(latestAutonomousLog)}
                                      {' · '}
                                      {autonomousLogSummary(latestAutonomousLog)}
                                    </span>
                                  )}
                                </button>
                                <a
                                  href={`/live?strategyId=${item.strategy_id}`}
                                  onClick={(e) => e.stopPropagation()}
                                  className="text-[11px] font-semibold text-blue-300 hover:text-blue-200"
                                >
                                  查看完整监控
                                </a>
                              </div>
                              {autonomousLogsOpen && (
                                <div className="max-h-[280px] overflow-y-auto px-3 py-2 font-mono text-[11px]">
                                  {selectedAutonomousLogs.length === 0 ? (
                                    <div className="rounded-lg border border-dashed border-crypto-border bg-crypto-bg px-3 py-8 text-center text-xs font-sans text-gray-500">
                                      暂无策略日志，实例运行后会显示 AI 决策、风控拦截和执行结果。
                                    </div>
                                  ) : (
                                    <div className="space-y-2">
                                      {selectedAutonomousLogs.map((evt, index) => {
                                        const level = String(evt.level || 'info');
                                        const time = formatAutonomousLogTime(evt.timestamp ?? evt.ts ?? evt.time);
                                        const chips = autonomousLogChips(evt);
                                        return (
                                          <div
                                            key={`${evt.timestamp || evt.time || index}-${evt.decision || evt.type || level}`}
                                            className="rounded-lg border border-crypto-border/60 bg-crypto-bg/80 p-2"
                                          >
                                            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                                              <span className={`text-[10px] font-semibold uppercase ${autonomousLogLevelClass(level)}`}>
                                                {level}
                                              </span>
                                              {time && <span className="text-gray-600">{time}</span>}
                                              <span className="font-semibold text-cyan-300">
                                                {autonomousLogTitle(evt)}
                                              </span>
                                            </div>
                                            <div className="mt-1 whitespace-pre-wrap break-words text-gray-200">
                                              {autonomousLogSummary(evt)}
                                            </div>
                                            {chips.length > 0 && (
                                              <div className="mt-2 flex flex-wrap gap-1.5 text-[10px]">
                                                {chips.map((chip) => (
                                                  <span key={`${chip.label}-${chip.value}`} className="rounded border border-crypto-border bg-black/20 px-1.5 py-0.5 text-gray-400">
                                                    {chip.label}: <span className="text-gray-300">{chip.value}</span>
                                                  </span>
                                                ))}
                                              </div>
                                            )}
                                          </div>
                                        );
                                      })}
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-crypto-border bg-crypto-bg px-3 py-10 text-center">
                  <div className="text-sm font-semibold text-gray-300">暂无 AI自主交易模拟盘实例</div>
                  <div className="mt-1 text-xs text-gray-500">配置左侧风控后启动一个新实例。</div>
                </div>
              )}

            </div>
          </div>
        </div>
      </div>
      )}

      {activeTab === 'research' && (
        <ResearchWorkbench />
      )}

      {activeTab === 'research' && legacyResearchPanelDeprecated && (
      <div className="space-y-4">
      <div className="rounded-xl border border-crypto-border bg-crypto-card p-4">
        <div className="flex flex-col gap-4 2xl:flex-row 2xl:items-center 2xl:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
                <Sparkles size={16} className="text-blue-400" />
                研发控制台
              </h2>
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${
                isRunning ? 'bg-blue-500/15 text-blue-300' :
                task?.status === 'completed' ? 'bg-green-500/15 text-green-400' :
                task?.status === 'interrupted' ? 'bg-orange-500/15 text-orange-400' :
                task?.status === 'failed' ? 'bg-red-500/15 text-red-400' :
                'bg-gray-500/15 text-gray-400'
              }`}>
                {isRunning
                  ? `第 ${(task?.current_iteration ?? 0) + 1}/${task?.max_iterations || maxIter} 轮`
                  : task?.status === 'completed'
                    ? '已完成'
                    : task?.status === 'interrupted'
                      ? '可继续'
                      : task?.status === 'failed'
                        ? '失败'
                        : '待启动'}
              </span>
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${
                marketType === 'swap' ? 'bg-orange-500/15 text-orange-300' : 'bg-blue-500/15 text-blue-300'
              }`}>
                {selectedMarket.badge} {selectedMarket.shortLabel}
              </span>
            </div>
            <div className="mt-1 max-w-2xl truncate text-xs text-gray-500">
              {task ? getResearchTaskTitle(task) : '配置任务参数后启动 AI 策略猎手'}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2 text-xs sm:flex sm:min-w-[360px] sm:justify-end">
            <div className="rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 sm:min-w-[96px]">
              <div className="text-[10px] text-gray-600">迭代</div>
              <div className="mt-0.5 font-semibold text-gray-200">{iterations.length}/{task?.max_iterations || maxIter}</div>
            </div>
            <div className="rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 sm:min-w-[96px]">
              <div className="text-[10px] text-gray-600">候选</div>
              <div className="mt-0.5 font-semibold text-gray-200">{candidates.length}</div>
            </div>
            <div className="rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 sm:min-w-[96px]">
              <div className="text-[10px] text-gray-600">最佳分</div>
              <div className="mt-0.5 font-semibold text-gray-200">
                {task?.best_score !== null && task?.best_score !== undefined ? Number(task.best_score).toFixed(0) : '--'}
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-end">
            {!isRunning ? (
              <>
                <button
                  type="button"
                  onClick={handleStart}
                  disabled={loading || promptOptimizing}
                  className="inline-flex h-10 min-w-[150px] items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-50"
                >
                  <Sparkles size={15} />
                  {loading ? '启动中...' : '启动策略猎手'}
                </button>
                {canResume && (
                  <button
                    type="button"
                    onClick={handleResume}
                    disabled={loading}
                    className="inline-flex h-10 min-w-[118px] items-center justify-center gap-2 rounded-lg bg-orange-600 px-4 text-sm font-semibold text-white hover:bg-orange-500 disabled:opacity-50"
                  >
                    <RotateCcw size={15} />
                    继续研发
                  </button>
                )}
              </>
            ) : (
              <button
                type="button"
                onClick={handleStop}
                className="inline-flex h-10 min-w-[118px] items-center justify-center gap-2 rounded-lg bg-red-600 px-4 text-sm font-semibold text-white hover:bg-red-500"
              >
                <Square size={15} />
                停止任务
              </button>
            )}
            {canSaveBest && (
              <button
                type="button"
                onClick={handleAccept}
                className="inline-flex h-10 min-w-[118px] items-center justify-center gap-2 rounded-lg bg-green-600 px-4 text-sm font-semibold text-white hover:bg-green-500"
              >
                <Download size={15} />
                保存最佳
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        {/* Left: Config Panel */}
        <div className="space-y-3 xl:col-span-3">
          <div className="bg-crypto-card border border-crypto-border rounded-lg p-4 space-y-3">
            <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-1">
              <Target size={14} /> 任务配置
            </h3>

            <div>
              <label className="text-xs text-gray-400">研发市场</label>
              <div className="mt-1 grid grid-cols-2 gap-2">
                {(['spot', 'swap'] as MarketType[]).map((type) => {
                  const item = AI_RESEARCH_MARKETS[type];
                  const active = marketType === type;
                  return (
                    <button
                      key={type}
                      type="button"
                      disabled={isRunning}
                      onClick={() => setMarketType(type)}
                      className={`flex min-h-[54px] items-center justify-center rounded-lg border px-3 py-2 text-center transition disabled:cursor-not-allowed disabled:opacity-70 ${
                        active
                          ? type === 'swap'
                            ? 'border-orange-400/70 bg-orange-500/15 text-orange-100'
                            : 'border-blue-400/70 bg-blue-500/15 text-blue-100'
                          : 'border-crypto-border bg-crypto-bg text-gray-400 hover:border-gray-600'
                      }`}
                    >
                      <div className="text-sm font-semibold">{item.shortLabel}</div>
                    </button>
                  );
                })}
              </div>
            </div>

            <div>
              <label className="text-xs text-gray-400">AI模型</label>
              <CryptoSelect
                value={selectedResearchModel}
                onChange={(e) => setResearchModel(e.target.value)}
                disabled={isRunning}
                wrapperClassName="mt-1"
              >
                {autonomousModelOptions.length > 0 ? (
                  autonomousModelOptions.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))
                ) : (
                  <option value="">暂无可用模型</option>
                )}
              </CryptoSelect>
              <div className="mt-1 text-[11px] leading-relaxed text-gray-600">
                Planner、策略生成、合约审查和评估都会使用该模型。
              </div>
            </div>

            <div>
              <label className="text-xs text-gray-400">研发范围</label>
              <div className="mt-1 rounded border border-crypto-border bg-crypto-bg px-3 py-2">
                <div className="text-sm font-medium text-gray-100">{selectedMarket.label}</div>
                <div className="mt-1 text-[11px] leading-relaxed text-gray-500">
                  {selectedMarket.symbols.join(' / ')}
                </div>
                <div className="mt-2 border-t border-crypto-border pt-2 text-[11px] leading-relaxed text-gray-500">
                  {selectedMarket.scope}
                </div>
                <div className="mt-1 text-[11px] leading-relaxed text-gray-600">{selectedMarket.note}</div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <DatePickerField
                label="开始日期"
                value={startDate}
                onChange={setStartDate}
                disabled={isRunning}
                max={endDate}
              />
              <DatePickerField
                label="结束日期"
                value={endDate}
                onChange={setEndDate}
                disabled={isRunning}
                min={startDate}
              />
            </div>

            <div>
              <label className="text-xs text-gray-400">最大迭代轮数</label>
              <CryptoSelect value={maxIter} onChange={e => setMaxIter(+e.target.value)} disabled={isRunning} controlSize="sm" wrapperClassName="mt-1">
                {[3, 5, 8, 12].map(v => <option key={v} value={v}>{v} 轮</option>)}
              </CryptoSelect>
            </div>

            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <label className="text-xs text-gray-400">人工提示词</label>
                <button
                  type="button"
                  onClick={handleOptimizePrompt}
                  disabled={isRunning || promptOptimizing || (!manualPrompt.trim() && !userPrompt.trim())}
                  className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-blue-500/45 bg-blue-500/10 px-3 text-xs font-semibold text-blue-200 hover:border-blue-400 hover:bg-blue-500/15 disabled:cursor-not-allowed disabled:border-gray-700 disabled:bg-transparent disabled:text-gray-600"
                >
                  <Sparkles size={13} />
                  {promptOptimizing ? '生成中...' : 'AI生成最终提示词'}
                </button>
              </div>
              <textarea
                value={manualPrompt}
                onChange={e => setManualPrompt(e.target.value)}
                disabled={isRunning}
                rows={5}
                placeholder="输入你的原始想法，例如：做合约多空、少交易、控制回撤、优先趋势突破和波动率过滤。"
                className="min-h-[120px] w-full bg-crypto-bg border border-crypto-border rounded px-3 py-2 text-sm resize-y"
              />
              <div>
                <div className="flex items-center justify-between gap-2">
                  <label className="text-xs text-gray-400">最终策略提示词（启动研发时使用）</label>
                  <button
                    type="button"
                    disabled={isRunning || !manualPrompt.trim()}
                    onClick={() => {
                      setUserPrompt(manualPrompt);
                      setPromptOptimizeSummary('已直接使用人工提示词作为最终提示词');
                    }}
                    className="text-[11px] font-medium text-gray-400 hover:text-gray-200 disabled:cursor-not-allowed disabled:text-gray-700"
                  >
                    直接使用人工提示词
                  </button>
                </div>
                <textarea
                  value={userPrompt}
                  onChange={e => setUserPrompt(e.target.value)}
                  disabled={isRunning}
                  rows={9}
                  placeholder="AI 生成后的最终提示词会出现在这里，也可以人工微调。"
                  className="mt-1 min-h-[220px] w-full bg-crypto-bg border border-crypto-border rounded px-3 py-2 text-sm resize-y"
                />
              </div>
              {promptOptimizeSummary && (
                <div className="rounded-md border border-blue-500/20 bg-blue-500/5 px-3 py-2 text-[11px] leading-relaxed text-blue-200">
                  {promptOptimizeSummary}
                </div>
              )}
            </div>

          </div>

          <div className="bg-crypto-card border border-crypto-border rounded-lg p-4 space-y-2">
            <h3 className="text-sm font-semibold text-gray-300">绩效目标</h3>
            {([
              ['min_sharpe_ratio', '夏普比率 ≥', 0.1],
              ['max_drawdown_pct', '最大回撤 ≤ %', 1],
              ['min_win_rate_pct', '胜率 ≥ %', 1],
              ['min_total_return_pct', '总收益率 ≥ %', 1],
              ['min_profit_factor', '盈亏比 ≥', 0.1],
              ['min_total_trades', '交易次数 ≥', 1],
            ] as [keyof GoalCriteria, string, number][]).map(([key, label, step]) => (
              <div key={key} className="flex items-center justify-between">
                <label className="text-xs text-gray-400 w-28">{label}</label>
                <input type="number" step={step} value={goal[key]} disabled={isRunning}
                  onChange={e => setGoal({ ...goal, [key]: +e.target.value })}
                  className="w-20 bg-crypto-bg border border-crypto-border rounded px-2 py-1 text-sm text-right" />
              </div>
            ))}
          </div>

          {/* Architecture diagram */}
          <div className="bg-crypto-card border border-crypto-border rounded-lg p-3">
            <h4 className="text-[10px] font-semibold text-gray-500 mb-2">研发流程</h4>
            <div className="flex flex-col items-center gap-1 text-[10px]">
              <div className="flex items-center gap-1 text-blue-400">
                <FileText size={10} /> 规划 <span className="text-gray-600">(规格书)</span>
              </div>
              <ArrowRight size={10} className="text-gray-600 rotate-90" />
              <div className="flex items-center gap-1 text-yellow-400">
                <GitBranch size={10} /> 合约准备 <span className="text-gray-600">(首轮快速)</span>
              </div>
              <ArrowRight size={10} className="text-gray-600 rotate-90" />
              <div className="flex items-center gap-1 text-green-400">
                <Zap size={10} /> 策略生成 <span className="text-gray-600">(代码)</span>
              </div>
              <ArrowRight size={10} className="text-gray-600 rotate-90" />
              <div className="flex items-center gap-1 text-purple-400">
                <Cpu size={10} /> 回测 <span className="text-gray-600">(验证候选)</span>
              </div>
              <ArrowRight size={10} className="text-gray-600 rotate-90" />
              <div className="flex items-center gap-1 text-orange-400">
                <Target size={10} /> 评估 <span className="text-gray-600">(独立评分)</span>
              </div>
              <RotateCcw size={10} className="text-gray-600 mt-1" />
            </div>
          </div>
        </div>

        {/* Middle: Research Records + Iteration Timeline */}
        <div className="space-y-3 xl:col-span-4">
          <div className="bg-crypto-card border border-crypto-border rounded-lg p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
                <History size={15} className="text-blue-400" />
                研发记录
                <span className="rounded-full bg-crypto-bg px-2 py-0.5 text-[10px] font-normal text-gray-500">
                  最近 {Math.min(taskHistory.length, 5)} / {taskHistory.length}
                </span>
              </h3>
              <button
                type="button"
                onClick={refreshTaskHistory}
                disabled={historyLoading}
                className="inline-flex h-8 items-center gap-2 rounded-lg border border-crypto-border px-3 text-xs font-semibold text-gray-300 hover:border-blue-500 hover:text-blue-300 disabled:opacity-50"
              >
                <RefreshCw size={13} className={historyLoading ? 'animate-spin' : ''} />
                刷新
              </button>
            </div>
            {taskHistory.length > 0 ? (
              <div className="space-y-2 xl:max-h-[430px] xl:overflow-y-auto xl:pr-1">
                {taskHistory.slice(0, 5).map((item) => {
                  const itemId = getTaskId(item);
                  const displayTitle = getResearchTaskTitle(item);
                  const active = task && getTaskId(task) === itemId;
                  const canDeleteRecord = item.status !== 'running' && item.status !== 'pending';
                  return (
                    <div
                      key={itemId}
                      className={`rounded-lg border p-3 transition-colors ${
                        active
                          ? SELECTED_SEGMENT_BORDER_CLASS
                          : 'border-crypto-border bg-crypto-bg hover:border-gray-600'
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        <button
                          type="button"
                          onClick={() => loadTask(itemId)}
                          className="min-w-0 flex-1 text-left"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="flex min-w-0 items-center gap-1.5">
                              <span className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] ${
                                item.market_type === 'swap' ? 'bg-orange-500/15 text-orange-300' : 'bg-blue-500/15 text-blue-300'
                              }`}>
                                {AI_RESEARCH_MARKETS[item.market_type].shortLabel}
                              </span>
                              <span className="truncate text-xs font-semibold text-white">{displayTitle}</span>
                            </span>
                            <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${
                              item.status === 'completed' ? 'bg-green-500/15 text-green-400' :
                              item.status === 'running' || item.status === 'pending' ? 'bg-blue-500/15 text-blue-400' :
                              item.status === 'interrupted' ? 'bg-orange-500/15 text-orange-400' :
                              item.status === 'failed' ? 'bg-red-500/15 text-red-400' :
                              'bg-gray-500/15 text-gray-400'
                            }`}>
                              {item.status === 'interrupted' ? '中断' : item.status}
                            </span>
                          </div>
                          <div className="mt-2 text-[11px] text-gray-400">
                            {item.iterations_count}/{item.max_iterations} 轮
                            {item.best_score !== null ? ` · 最佳 ${Number(item.best_score).toFixed(0)}分` : ''}
                          </div>
                          <div className="mt-1 truncate text-[11px] text-gray-500">
                            {item.stage_label || item.updated_at || '已持久化'}
                          </div>
                        </button>
                        <button
                          type="button"
                          disabled={!canDeleteRecord || deletingTaskId === itemId}
                          title={canDeleteRecord ? '删除研发记录' : '运行中的任务需先停止'}
                          onClick={() => setDeleteTarget(item)}
                          className="mt-0.5 inline-flex h-7 shrink-0 items-center justify-center gap-1 rounded-md border border-red-500/30 bg-red-500/5 px-2.5 text-[11px] font-medium text-red-300 hover:border-red-400/70 hover:bg-red-500/10 hover:text-red-200 disabled:cursor-not-allowed disabled:border-gray-700 disabled:bg-transparent disabled:text-gray-600"
                        >
                          <Trash2 size={13} />
                          删除
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-crypto-border bg-crypto-bg px-3 py-4 text-center text-xs text-gray-500">
                暂无持久化研发记录
              </div>
            )}
          </div>
          <div className="bg-crypto-card border border-crypto-border rounded-lg p-4 h-full overflow-auto">
            <h3 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-1">
              <RefreshCw size={14} className={isRunning ? 'animate-spin' : ''} /> 迭代时间线
              {isRunning && task?.stage_label && (
                <span className="ml-auto min-w-0 truncate text-[10px] font-normal text-blue-300">
                  {task.stage_label}
                </span>
              )}
            </h3>
            <ResearchPipeline
              task={task}
              iterations={iterations}
              stageText={stageText}
              specOpen={showSpec}
              onToggleSpec={() => setShowSpec((open) => !open)}
            />

            {showSpec && task?.strategy_spec && (
              <div className="mt-3 rounded-lg border border-blue-500/30 bg-crypto-bg p-4">
                <h3 className="text-sm font-semibold text-blue-400 mb-3 flex items-center gap-1">
                  <FileText size={14} /> 策略规格书
                </h3>
                <div className="space-y-3 text-xs text-gray-400">
                  <div>
                    <h4 className="text-gray-300 font-medium mb-1">市场分析</h4>
                    <p className="whitespace-pre-wrap leading-relaxed">{task.strategy_spec.market_analysis}</p>
                  </div>
                  <div>
                    <h4 className="text-gray-300 font-medium mb-1">推荐方向</h4>
                    <p className="whitespace-pre-wrap leading-relaxed">{task.strategy_spec.recommended_approach}</p>
                  </div>
                  {task.strategy_spec.strategy_candidates?.length > 0 && (
                    <div>
                      <h4 className="text-gray-300 font-medium mb-2">候选策略方向</h4>
                      <div className="grid grid-cols-1 gap-2 2xl:grid-cols-2">
                        {task.strategy_spec.strategy_candidates.map((c, i) => (
                          <div key={i} className="bg-crypto-card rounded p-2 border border-crypto-border">
                            <div className="font-medium text-gray-300 mb-1">{c.name}</div>
                            <p className="text-[10px] leading-relaxed">{c.description}</p>
                            <div className="flex gap-2 mt-1">
                              <span className="text-green-400 text-[10px]">+{c.pros}</span>
                              <span className="text-red-400 text-[10px]">-{c.cons}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  <div>
                    <h4 className="text-gray-300 font-medium mb-1">风险提示</h4>
                    <p className="whitespace-pre-wrap leading-relaxed">{task.strategy_spec.risk_considerations}</p>
                  </div>
                  <div>
                    <h4 className="text-gray-300 font-medium mb-1">迭代计划</h4>
                    <p className="whitespace-pre-wrap leading-relaxed">{task.strategy_spec.iteration_plan}</p>
                  </div>
                </div>
              </div>
            )}

            {iterations.length > 0 && (
              <div className="mt-4 mb-2 flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold text-gray-500">迭代记录</span>
                <span className="text-[10px] text-gray-600">{iterations.length}/{task?.max_iterations || maxIter} 轮</span>
              </div>
            )}
            <div className="space-y-2">
              {iterations.map((it) => {
                const isBest = task?.best_iteration === it.iteration;
                const m = it.backtest_metrics;
                const act = ACTION_LABELS[it.action] || ACTION_LABELS['new'];
                return (
                  <button key={it.iteration}
                    onClick={() => setSelectedIter(it.iteration)}
                    className={`w-full text-left p-3 rounded-lg border transition-all ${
                      selectedIter === it.iteration
                        ? SELECTED_SEGMENT_BORDER_CLASS
                        : 'border-crypto-border bg-crypto-bg hover:border-gray-600'
                    }`}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-medium text-gray-300 flex items-center gap-1">
                        {isBest && <span className="text-yellow-400">★</span>}
                        第 {it.iteration + 1} 轮
                        <span className={`text-[10px] ${act.color}`}>[{act.label}]</span>
                      </span>
                      <span className={`text-xs px-1.5 py-0.5 rounded ${
                        it.meets_goal ? 'bg-green-500/20 text-green-400' :
                        it.error ? 'bg-red-500/20 text-red-400' :
                        'bg-gray-500/20 text-gray-400'
                      }`}>
                        {it.meets_goal ? '达标' : it.error ? '错误' : `${it.score.toFixed(0)}分`}
                      </span>
                    </div>
                    <p className="text-xs text-gray-400 truncate">{it.strategy_name || '生成中...'}</p>
                    {m && finiteNumber(m.total_return_pct) !== null && (
                      <div className="flex gap-2 mt-1 text-[10px]">
                        <span className={metricToneTextClass(signedMarketTone(m.total_return_pct))}>
                          收益 {fmtPct(m.total_return_pct)}
                        </span>
                        <span className={metricToneTextClass(signedMarketTone(m.sharpe_ratio))}>
                          夏普 {fmtNumber(m.sharpe_ratio)}
                        </span>
                        <span className="text-gray-500">回撤 {fmtPct(m.max_drawdown_pct)}</span>
                      </div>
                    )}
                    {/* Mini score bar */}
                    {it.eval_scores && !it.error && (
                      <div className="mt-1.5 flex gap-0.5">
                        {(['risk_control','profitability','robustness','strategy_logic','originality'] as const).map(k => {
                          const v = it.eval_scores![k];
                          const color = v >= 70 ? 'bg-green-500' : v >= 50 ? 'bg-yellow-500' : 'bg-red-500';
                          return (
                            <div key={k} className="flex-1 h-1 bg-gray-700 rounded-full overflow-hidden" title={`${k}: ${v}`}>
                              <div className={`h-full ${color} rounded-full`} style={{ width: `${v}%` }} />
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Right: Detail Panel */}
        <div className="xl:sticky xl:top-4 xl:col-span-5 xl:max-h-[calc(100vh-120px)] xl:self-start xl:overflow-y-auto xl:pr-1">
          {iterations.length > 0 && candidates.length === 0 && (
            <div className="bg-crypto-card border border-yellow-500/25 rounded-lg p-4 mb-3">
              <h3 className="text-sm font-semibold text-yellow-300 mb-1 flex items-center gap-2">
                <AlertCircle size={15} /> 暂无合格候选
              </h3>
              <p className="text-xs leading-relaxed text-gray-500">
                当前完成的迭代没有通过基本候选门槛；亏损、负夏普、盈亏比低于 1、交易数不足或回撤明显超标的策略不会进入候选池，保存时需要人工确认并记录风险。
              </p>
            </div>
          )}

          {candidates.length > 0 && (
            <div className="bg-crypto-card border border-blue-500/25 rounded-lg p-4 mb-3">
              <h3 className="text-sm font-semibold text-blue-300 mb-3 flex items-center gap-2">
                <Sparkles size={15} /> 候选策略池
              </h3>
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2 2xl:grid-cols-5">
                {candidates.map((item, idx) => {
                  const it = item.record;
                  const m = it.backtest_metrics || {};
                  return (
                    <button
                      key={it.iteration}
                      type="button"
                      onClick={() => setSelectedIter(it.iteration)}
                      className={`text-left rounded-lg border p-3 transition-colors ${
                        selectedIter === it.iteration
                          ? SELECTED_SEGMENT_BORDER_CLASS
                          : 'border-crypto-border bg-crypto-bg hover:border-gray-600'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="text-xs font-bold text-white">#{idx + 1} 第 {it.iteration + 1} 轮</span>
                        <span className="text-[10px] text-blue-300">{item.hunterScore.toFixed(0)}</span>
                      </div>
                      <div className="text-[11px] text-gray-400 truncate mb-2">{it.strategy_name}</div>
                      <div className="grid grid-cols-2 gap-x-2 gap-y-1 text-[10px] text-gray-500">
                        <span className={metricToneTextClass(signedMarketTone(m.total_return_pct))}>
                          收益 {Number(m.total_return_pct ?? 0).toFixed(1)}%
                        </span>
                        <span className={metricToneTextClass(signedMarketTone(m.sharpe_ratio))}>
                          夏普 {Number(m.sharpe_ratio ?? 0).toFixed(2)}
                        </span>
                        <span>回撤 {Number(m.max_drawdown_pct ?? 0).toFixed(1)}%</span>
                        <span>交易 {Number(m.total_trades ?? 0)}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {sel ? (
            <div className="space-y-3">
              <div className="bg-crypto-card border border-crypto-border rounded-lg p-4 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-white truncate">
                    <span className={`mr-2 rounded px-1.5 py-0.5 text-[10px] ${
                      marketType === 'swap' ? 'bg-orange-500/15 text-orange-300' : 'bg-blue-500/15 text-blue-300'
                    }`}>
                      {selectedMarket.badge}
                    </span>
                    第 {sel.iteration + 1} 轮 · {sel.strategy_name || '未命名策略'}
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    {selectedQuality.ok
                      ? '已完成的合格候选可随时保存到策略库；保存不会中断当前研发，也不会直接进入实盘。'
                      : `未通过保存门槛，点击保存需人工确认：${selectedQuality.issues.join('、')}`}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={handleAcceptSelected}
                  disabled={!sel.strategy_code || savingIteration === sel.iteration}
                  title={
                    !sel.strategy_code
                      ? '该轮尚未生成策略代码'
                      : selectedQuality.ok
                        ? '保存已完成候选，不会中断当前研发任务'
                        : `未通过保存门槛，保存前会要求人工确认：${selectedQuality.issues.join('、')}`
                  }
                  className={`shrink-0 inline-flex items-center gap-2 px-4 py-2 rounded-lg text-white text-sm font-semibold disabled:opacity-50 ${
                    selectedQuality.ok ? 'bg-green-600 hover:bg-green-500' : 'bg-amber-600 hover:bg-amber-500'
                  }`}
                >
                  <Download size={14} />
                  {savingIteration === sel.iteration ? '保存中...' : '保存此候选'}
                </button>
              </div>

              {/* Eval Scores Radar + Metrics */}
              <div className="grid grid-cols-1 gap-3 2xl:grid-cols-3">
                {sel.eval_scores && (
                  <div className="bg-crypto-card border border-crypto-border rounded-lg p-3">
                    <h4 className="text-xs font-semibold text-gray-400 mb-1 text-center">多维度评分</h4>
                    <RadarChart scores={sel.eval_scores} />
                    <div className="text-center mt-1">
                      <span className="text-lg font-bold text-blue-400">{sel.score.toFixed(0)}</span>
                      <span className="text-xs text-gray-500">/100</span>
                    </div>
                  </div>
                )}
                <div className={sel.eval_scores ? '2xl:col-span-2' : '2xl:col-span-3'}>
                  <div className="grid grid-cols-2 gap-2 2xl:grid-cols-4">
                    <MetricCard label="总收益率" value={fmtPct(selMetrics.total_return_pct)}
                      tone={signedMarketTone(selMetrics.total_return_pct)} />
                    <MetricCard label="夏普比率" value={fmtNumber(selMetrics.sharpe_ratio)}
                      tone={signedMarketTone(selMetrics.sharpe_ratio)} />
                    <MetricCard label="最大回撤" value={fmtPct(selMetrics.max_drawdown_pct)}
                      tone={riskTone((finiteNumber(selMetrics.max_drawdown_pct) ?? Infinity) <= goal.max_drawdown_pct)} />
                    <MetricCard label="胜率" value={fmtPct(selMetrics.win_rate_pct)}
                      tone={targetTone((finiteNumber(selMetrics.win_rate_pct) ?? -Infinity) >= goal.min_win_rate_pct)} />
                    <MetricCard label="盈亏比" value={fmtNumber(selMetrics.profit_factor)}
                      tone={targetTone((finiteNumber(selMetrics.profit_factor) ?? -Infinity) >= goal.min_profit_factor)} />
                    <MetricCard label="总交易数" value={fmtNumber(selMetrics.total_trades, 0)}
                      tone={targetTone((finiteNumber(selMetrics.total_trades) ?? -Infinity) >= goal.min_total_trades)} />
                    <MetricCard label="年化收益" value={fmtPct(selMetrics.annual_return_pct)}
                      tone={signedMarketTone(selMetrics.annual_return_pct)} />
                    <MetricCard label="评分" value={`${fmtNumber(sel.score, 0)}/100`}
                      tone={targetTone(sel.meets_goal)} />
                  </div>
                </div>
              </div>

              {/* Sprint Contract */}
              {sel.contract && (
                <div className="bg-crypto-card border border-yellow-500/20 rounded-lg p-4">
                  <h4 className="text-sm font-semibold text-yellow-400 mb-2 flex items-center gap-1">
                    <GitBranch size={14} /> Sprint 合约
                    <span className={`text-xs ml-2 ${ACTION_LABELS[sel.action]?.color || ''}`}>
                      [{ACTION_LABELS[sel.action]?.label || sel.action}]
                    </span>
                  </h4>
                  <div className="grid grid-cols-2 gap-3 text-xs text-gray-400">
                    <div>
                      <span className="text-gray-500">策略方向:</span> {sel.contract.strategy_direction}
                    </div>
                    <div>
                      <span className="text-gray-500">核心指标:</span> {sel.contract.key_indicators?.join(', ')}
                    </div>
                    <div><span className="text-gray-500">进场:</span> {sel.contract.entry_logic_desc}</div>
                    <div><span className="text-gray-500">出场:</span> {sel.contract.exit_logic_desc}</div>
                    <div className="col-span-2"><span className="text-gray-500">风控:</span> {sel.contract.risk_management_desc}</div>
                    {sel.contract.acceptance_criteria?.length > 0 && (
                      <div className="col-span-2">
                        <span className="text-gray-500">验收标准:</span>
                        <ul className="mt-1 space-y-0.5">
                          {sel.contract.acceptance_criteria.map((c, i) => (
                            <li key={i} className="flex items-start gap-1">
                              <ChevronRight size={10} className="text-yellow-400 mt-0.5 shrink-0" /> {c}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Analysis */}
              {sel.analysis && (
                <div className="bg-crypto-card border border-crypto-border rounded-lg p-4">
                  <h4 className="text-sm font-semibold text-gray-300 mb-2 flex items-center gap-1">
                    <AlertCircle size={14} /> 评估分析报告
                  </h4>
                  <p className="text-xs text-gray-400 leading-relaxed whitespace-pre-wrap">{sel.analysis}</p>
                  {sel.suggestions.length > 0 && (
                    <div className="mt-3">
                      <h5 className="text-xs font-semibold text-yellow-400 mb-1">优化建议:</h5>
                      <ul className="space-y-1">
                        {sel.suggestions.map((s, i) => (
                          <li key={i} className="text-xs text-gray-400 flex items-start gap-1">
                            <ChevronRight size={12} className="text-yellow-400 mt-0.5 shrink-0" />
                            {s}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* Reasoning */}
              {sel.reasoning && (
                <div className="bg-crypto-card border border-crypto-border rounded-lg p-4">
                  <h4 className="text-sm font-semibold text-gray-300 mb-2">设计思路</h4>
                  <p className="text-xs text-gray-400 leading-relaxed whitespace-pre-wrap">{sel.reasoning}</p>
                </div>
              )}

              {/* Strategy Code */}
              {sel.strategy_code && (
                <div className="bg-crypto-card border border-crypto-border rounded-lg p-4">
                  <h4 className="text-sm font-semibold text-gray-300 mb-2 flex items-center gap-1">
                    <Cpu size={14} /> 策略代码
                  </h4>
                  <pre className="bg-crypto-bg rounded p-3 text-xs text-green-300 overflow-auto max-h-80 font-mono leading-relaxed">
                    {sel.strategy_code}
                  </pre>
                </div>
              )}

              {/* Error */}
              {sel.error && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
                  <h4 className="text-sm font-semibold text-red-400 mb-1">错误</h4>
                  <p className="text-xs text-red-300">{sel.error}</p>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-crypto-card border border-crypto-border rounded-lg p-8 flex flex-col items-center justify-center h-full text-gray-500">
              <Sparkles size={48} className="mb-4 opacity-30" />
              <p className="text-sm">在左侧选择迭代轮次查看详情</p>
              <p className="text-xs mt-2 text-gray-600 max-w-md text-center">
                策略规格书 → 合约准备 → 策略生成 → 回测验证 → 独立评估，循环迭代
              </p>
            </div>
          )}
        </div>
      </div>
      </div>
      )}

      <ThemeDialog
        open={autonomousEditTarget !== null && autonomousEditConfig !== null}
        variant="confirm"
        title="编辑 AI自主交易配置"
        tone="warning"
        confirmText={savingAutonomousConfig ? '保存中...' : '保存配置'}
        cancelText="取消"
        onCancel={() => {
          setAutonomousEditTarget(null);
          setAutonomousEditConfig(null);
          setAutonomousEditDrafts({});
        }}
        onConfirm={() => {
          if (savingAutonomousConfig) return;
          void handleSaveAutonomousConfig();
        }}
      >
        {autonomousEditConfig && autonomousEditTarget && (
          <div className="max-h-[68vh] space-y-4 overflow-y-auto pr-1">
            <div className="rounded-lg border border-yellow-500/20 bg-yellow-500/5 px-3 py-2 text-xs leading-relaxed text-yellow-100/80">
              模型、仓位、决策间隔和交易频率保存后会写入实例配置；运行中实例会在下一次 AI 决策使用新模型和风控上限。初始资金只能在实例停止后修改。
            </div>

            <div>
              <div className="text-[11px] text-gray-500">实例</div>
              <div className="mt-1 truncate text-sm font-semibold text-gray-100">{autonomousEditTarget.name}</div>
              <div className="mt-1 text-[11px] text-gray-500">#{autonomousEditTarget.strategy_id} · {autonomousStatusText(autonomousEditTarget.status)}</div>
            </div>

            <label className="block">
              <span className="text-xs text-gray-400">AI提供方</span>
              <CryptoSelect
                value={autonomousEditConfig.llmProvider}
                onChange={(e) => updateAutonomousEditConfig('llmProvider', e.target.value)}
                wrapperClassName="mt-1"
              >
                <option value="hermes">{AUTONOMOUS_HERMES_PROVIDER_LABEL}</option>
                <option value="dashscope">DashScope / Qwen</option>
              </CryptoSelect>
            </label>

            <label className="block">
              <span className="text-xs text-gray-400">AI模型</span>
              <CryptoSelect
                value={autonomousEditConfig.llmModel}
                onChange={(e) => updateAutonomousEditConfig('llmModel', e.target.value)}
                wrapperClassName="mt-1"
              >
                {autonomousEditModelOptions.length > 0 ? (
                  autonomousEditModelOptions.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))
                ) : (
                  <option value="">暂无可用模型</option>
                )}
              </CryptoSelect>
            </label>

            <label className="block">
              <span className="text-xs text-gray-400">交易方向</span>
              <CryptoSelect
                value={autonomousEditConfig.tradeDirection}
                onChange={(e) => updateAutonomousEditConfig('tradeDirection', e.target.value)}
                wrapperClassName="mt-1"
              >
                <option value="short_only">只做空</option>
                <option value="long_short">多空双向</option>
              </CryptoSelect>
            </label>

            <div>
              <div className="text-xs text-gray-400">A 股标的池</div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {autonomousSymbolsFromText(autonomousEditConfig.symbolsText).map((symbol) => (
                  <span key={symbol} className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-0.5 text-[10px] text-gray-400">
                    {formatSymbolLabel(symbol, aiSymbolNames[symbol])}
                  </span>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {([
                ['maxLeverageCap', '单票上限', '≤ x', 1, 20, 0.5, false],
                ['maxSinglePositionPct', '单笔仓位', '≤ %', 1, 100, 1, false],
                ['maxTotalExposurePct', '总风险敞口', '≤ %', 1, 500, 1, false],
                ['maxPositions', '最多持仓', '≤ 个', 1, 20, 1, false],
                ['minDecisionIntervalSec', '决策间隔', '≥ 秒', 30, 3600, 10, false],
                ['maxDecisionIntervalSec', '最长等待', '≤ 秒', 30, 3600, 10, false],
                ['probeSizePct', '试单仓位', '%', 0.1, 100, 0.5, false],
                ['maxTradesPerHour', '每小时交易', '≤ 笔', 1, 120, 1, false],
                ['initialCapital', '初始资金', 'CNY', 100, 1000000, 100, ['pending', 'running', 'paused'].includes(String(autonomousEditTarget.status || '').toLowerCase())],
              ] as [AutonomousNumericConfigKey, string, string, number, number, number, boolean][]).map(([key, label, suffix, min, max, step, disabled]) => (
                <label key={key} className={`rounded-lg border border-crypto-border bg-crypto-bg p-3 ${disabled ? 'opacity-60' : ''}`}>
                  <span className="block text-[11px] text-gray-500">{label}</span>
                  <div className="mt-1 flex items-center gap-2">
                    <input
                      type="text"
                      inputMode="decimal"
                      min={min}
                      max={max}
                      step={step}
                      disabled={disabled}
                      value={autonomousEditDrafts[key] ?? String(autonomousEditConfig[key])}
                      onChange={(e) => updateAutonomousEditConfig(key, e.target.value)}
                      onBlur={() => commitAutonomousEditNumericConfig(key, min, max)}
                      className="h-9 min-w-0 flex-1 rounded-md border border-crypto-border bg-black/20 px-2 text-center text-sm font-semibold text-gray-100 focus:border-yellow-500 focus:outline-none disabled:cursor-not-allowed"
                    />
                    <span className="shrink-0 text-[11px] text-gray-500">{suffix}</span>
                  </div>
                </label>
              ))}
            </div>
          </div>
        )}
      </ThemeDialog>

      <ThemeAlertDialog
        open={themeAlert.open}
        title={themeAlert.title}
        content={themeAlert.content}
        tone={themeAlert.tone}
        onClose={() => setThemeAlert((a) => ({ ...a, open: false }))}
      />
      <ThemeDialog
        open={forceSaveTarget !== null}
        variant="confirm"
        title="保存未达标候选"
        content={
          forceSaveTarget
            ? `第 ${forceSaveTarget.iteration + 1} 轮未通过保存门槛：\n${getCandidateQuality(forceSaveTarget, goal).issues.join('\n')}\n\n仍然保存会写入策略库，并记录为人工保留的实验样本；不会自动进入实盘。`
            : ''
        }
        tone="warning"
        confirmText={savingIteration !== null ? '保存中...' : '仍然保存'}
        cancelText="取消"
        onCancel={() => setForceSaveTarget(null)}
        onConfirm={() => {
          if (!forceSaveTarget || savingIteration !== null) return;
          void saveIterationCandidate(forceSaveTarget, true);
        }}
      />
      <ThemeDialog
        open={deleteTarget !== null}
        variant="confirm"
        title="删除研发记录"
        content={
          deleteTarget
            ? `确定要删除研发记录「${getResearchTaskTitle(deleteTarget)}」吗？该任务的迭代记录也会一起删除，此操作不可恢复。`
            : ''
        }
        tone="danger"
        confirmText={deletingTaskId ? '删除中...' : '删除'}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => void handleDeleteRecord()}
      />
      <ThemeDialog
        open={optimizerDeleteTarget !== null}
        variant="confirm"
        title="删除优化记录"
        content={
          optimizerDeleteTarget
            ? `确定要删除优化记录「${getOptimizerRunTitle(optimizerDeleteTarget)}」吗？该记录的阶段日志也会一起删除，不会删除源策略或候选策略。`
            : ''
        }
        tone="danger"
        confirmText={deletingOptimizerRunId ? '删除中...' : '删除'}
        onCancel={() => setOptimizerDeleteTarget(null)}
        onConfirm={() => void handleDeleteOptimizerRun()}
      />
      <ThemeDialog
        open={autonomousDeleteTarget !== null}
        variant="confirm"
        title="删除 AI自主交易实例"
        content={
          autonomousDeleteTarget
            ? `确定要删除实例「${autonomousDeleteTarget.name}」吗？运行中或暂停中的实例会先停止；策略记录、成交记录和最近 AI 决策记录会一起删除，此操作不可恢复。`
            : ''
        }
        tone="danger"
        confirmText={deletingAutonomousId ? '删除中...' : '删除'}
        onCancel={() => setAutonomousDeleteTarget(null)}
        onConfirm={() => void handleDeleteAutonomousTrader()}
      />
    </div>
  );
}
