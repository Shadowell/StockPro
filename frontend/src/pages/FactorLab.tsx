import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, Boxes, BrainCircuit, CheckCircle2, Cpu, Database, FileStack,
  FlaskConical, Gauge, LibraryBig, Loader2, Pause, Play, RefreshCw, RotateCcw,
  ShieldCheck, Trash2,
} from 'lucide-react';
import clsx from 'clsx';
import { SELECTED_SEGMENT_CLASS } from '../utils/selectionStyles';
import {
  factorLabApi, parseApiError, settingsApi,
  type FactorLabDefinition, type FactorLabSummary, type FactorResearchMode,
  type FactorResearchTask, type FactorResearchTrial, type LLMProviderCapabilities,
} from '../api/client';

const familyLabels: Record<string, string> = {
  trend_direction: '趋势方向', trend_quality: '趋势质量', momentum: '动量',
  volatility_regime: '波动状态', reversal: '反转', volume: '成交量',
};
const roleLabels: Record<string, string> = {
  alpha_direction: '方向 Alpha', alpha_quality: '信号质量', regime: '市场状态', execution: '执行/流动性',
};
const orientationLabels: Record<string, string> = {
  higher_is_stronger: '越高越强', higher_is_more_volatile: '越高波动越大',
  signed_trend_direction: '正负表示方向', signed_momentum: '正负表示动量',
  signed_mean_deviation: '正负表示均值偏离', signed_volume_confirmation: '正负表示量能确认',
  signed_vwap_distance: '正负表示 VWAP 距离', lower_is_less_choppy: '越低越顺畅',
  higher_is_abnormal_volume: '越高表示异常放量', higher_is_buying_pressure: '越高表示买入资金流更强',
  signed_price_volume_confirmation: '正负表示量价确认方向',
};
const statusLabels: Record<string, string> = {
  queued: '排队中', running: '运行中', paused: '已暂停', completed: '已完成', failed: '失败', cancelled: '已取消',
};
const failureLabels: Record<string, string> = {
  coverage: '覆盖率不足', fold_count: 'OOS fold 不足', cost_return_non_positive: '20bps 后收益非正',
  profit_factor: 'Profit Factor 未达标', max_drawdown: '最大回撤超限', profitable_folds: '盈利 fold 比例不足',
  stress_collapse: '40bps 压力崩溃', symbol_concentration: '收益集中于少数标的',
  baseline_not_beaten: '未优于简单基线', catastrophic_loss: '存在灾难性损失',
  score_below_threshold: '综合分不足 70', factor_model_error: '模型训练失败',
};

function shortHash(value: string) { return value ? value.slice(0, 10) : '--'; }
function defaultParameters(definition: FactorLabDefinition) {
  return Object.entries(definition.parameterSchema).map(([name, schema]) => `${name}=${schema.default ?? '--'}`).join(' · ') || '--';
}
function dateInput(daysAgo: number) { return new Date(Date.now() - daysAgo * 86_400_000).toISOString().slice(0, 10); }
function percent(value?: number | null) { return value == null || !Number.isFinite(value) ? '--' : `${(value * 100).toFixed(2)}%`; }

function MetricCard({ label, value, note, tone }: { label: string; value: number; note: string; tone: 'cyan' | 'blue' | 'amber' | 'slate' }) {
  const toneClass = { cyan: 'text-cyan-300 border-cyan-500/30 after:bg-cyan-400', blue: 'text-blue-300 border-blue-500/30 after:bg-blue-400', amber: 'text-amber-300 border-amber-500/30 after:bg-amber-400', slate: 'text-gray-200 border-gray-700 after:bg-gray-500' }[tone];
  return <div className={clsx('relative overflow-hidden border bg-crypto-card px-4 py-3 after:absolute after:inset-x-0 after:bottom-0 after:h-0.5', toneClass)}><div className="text-xs text-gray-500">{label}</div><div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div><div className="mt-1 text-xs text-gray-500">{note}</div></div>;
}
function BoundaryRow({ ok, label, detail }: { ok: boolean; label: string; detail: string }) {
  const Icon = ok ? CheckCircle2 : ShieldCheck;
  return <div className="flex items-start gap-3 border-b border-crypto-border px-4 py-3 last:border-b-0"><Icon className={clsx('mt-0.5 h-4 w-4 shrink-0', ok ? 'text-cyan-300' : 'text-amber-300')} /><div className="min-w-0"><div className="text-sm text-gray-200">{label}</div><div className="mt-0.5 text-xs leading-5 text-gray-500">{detail}</div></div></div>;
}
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="min-w-0 text-[11px] text-gray-500"><span className="mb-1 block">{label}</span>{children}</label>;
}
const inputClass = 'h-9 w-full border border-crypto-border bg-crypto-bg px-2 text-xs text-gray-200 outline-none focus:border-cyan-500/50';

export default function FactorLab() {
  const [summary, setSummary] = useState<FactorLabSummary | null>(null);
  const [tasks, setTasks] = useState<FactorResearchTask[]>([]);
  const [trials, setTrials] = useState<FactorResearchTrial[]>([]);
  const [providers, setProviders] = useState<LLMProviderCapabilities[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState('');
  const [selectedFactors, setSelectedFactors] = useState<string[]>([]);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [mode, setMode] = useState<FactorResearchMode>('auto');
  const [marketType, setMarketType] = useState<'stock' | 'etf'>('stock');
  const [symbols, setSymbols] = useState('600519.SH\n000001.SZ');
  const [timeframe, setTimeframe] = useState('1d');
  const [startDate, setStartDate] = useState(dateInput(365));
  const [endDate, setEndDate] = useState(dateInput(1));
  const [providerKey, setProviderKey] = useState('');
  const [model, setModel] = useState('');
  const [reasoningEffort, setReasoningEffort] = useState('');
  const [speedMode, setSpeedMode] = useState('');
  const [horizonBars, setHorizonBars] = useState(6);
  const [maxCandidates, setMaxCandidates] = useState(200);
  const [maxRuntimeMinutes, setMaxRuntimeMinutes] = useState(120);
  const [maxNoImprovement, setMaxNoImprovement] = useState(50);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [actionTaskId, setActionTaskId] = useState('');
  const [error, setError] = useState('');
  const [providerError, setProviderError] = useState('');

  const loadTasks = useCallback(async () => {
    const nextTasks = await factorLabApi.listResearchTasks();
    setTasks(nextTasks);
    setSelectedTaskId((current) => current || nextTasks[0]?.taskId || '');
  }, []);

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true); else setLoading(true);
    setError('');
    try {
      const [nextSummary, nextTasks] = await Promise.all([factorLabApi.getSummary(), factorLabApi.listResearchTasks()]);
      setSummary(nextSummary); setTasks(nextTasks);
      setSelectedTaskId((current) => current || nextTasks[0]?.taskId || '');
      setSelectedFactors((current) => current.length ? current : nextSummary.instances.map((item) => item.instanceId));
      setWeights((current) => { const next = { ...current }; for (const instance of nextSummary.instances) next[instance.instanceId] ??= 1; return next; });
      try {
        const settings = await settingsApi.getLLMModel();
        const nextProviders = (settings.providerCapabilities || []).filter((item) => item.enabled !== false);
        setProviders(nextProviders);
        const preferred = nextProviders.find((provider) => provider.providerKey === 'codex')
          || nextProviders.find((provider) => provider.providerKey === settings.providerKey)
          || nextProviders[0];
        if (preferred) {
          setProviderKey((current) => current || preferred.providerKey);
          setModel((current) => current || (preferred.models.includes('gpt-5.6-sol') ? 'gpt-5.6-sol' : preferred.defaultModel || preferred.models[0] || ''));
          setReasoningEffort((current) => current || (preferred.reasoningEfforts.includes('medium') ? 'medium' : preferred.reasoningEfforts[0] || 'auto'));
          setSpeedMode((current) => current || (preferred.speedModes.includes('standard') ? 'standard' : preferred.speedModes[0] || 'standard'));
        }
        setProviderError('');
      } catch (caught) { setProviderError(parseApiError(caught, 'Provider 能力不可用')); }
    } catch (caught) { setError(parseApiError(caught, '读取 FactorLab 失败')); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);
  const selectedTask = useMemo(() => tasks.find((task) => task.taskId === selectedTaskId) || null, [selectedTaskId, tasks]);
  const selectedProvider = useMemo(() => providers.find((provider) => provider.providerKey === providerKey) || null, [providerKey, providers]);
  const instancesByDefinition = useMemo(() => { const result = new Map<string, number>(); for (const instance of summary?.instances || []) result.set(instance.definitionId, (result.get(instance.definitionId) || 0) + 1); return result; }, [summary]);

  useEffect(() => {
    if (!selectedTaskId) { setTrials([]); return; }
    void factorLabApi.listResearchTrials(selectedTaskId).then(setTrials).catch((caught) => setError(parseApiError(caught, '读取 trial 失败')));
  }, [selectedTaskId]);
  useEffect(() => {
    if (!tasks.some((task) => task.status === 'queued' || task.status === 'running')) return undefined;
    const timer = window.setInterval(() => { void loadTasks().catch((caught) => setError(parseApiError(caught, '刷新研究任务失败'))); if (selectedTaskId) void factorLabApi.listResearchTrials(selectedTaskId).then(setTrials).catch(() => undefined); }, 3000);
    return () => window.clearInterval(timer);
  }, [loadTasks, selectedTaskId, tasks]);

  const updateProvider = (nextKey: string) => { const next = providers.find((item) => item.providerKey === nextKey); setProviderKey(nextKey); setModel(next?.defaultModel || next?.models[0] || ''); setReasoningEffort(next?.reasoningEfforts[0] || 'auto'); setSpeedMode(next?.speedModes[0] || 'standard'); };
  const toggleFactor = (instanceId: string) => setSelectedFactors((current) => current.includes(instanceId) ? current.filter((item) => item !== instanceId) : [...current, instanceId]);

  const runTaskAction = async (task: FactorResearchTask, action: 'pause' | 'resume') => {
    setActionTaskId(task.taskId); setError('');
    try { const updated = action === 'pause' ? await factorLabApi.pauseResearchTask(task.taskId) : await factorLabApi.resumeResearchTask(task.taskId); setTasks((current) => current.map((item) => item.taskId === updated.taskId ? (action === 'resume' ? { ...updated, status: 'queued' } : updated) : item)); if (action === 'resume') window.setTimeout(() => void loadTasks(), 500); }
    catch (caught) { setError(parseApiError(caught, action === 'pause' ? '暂停失败' : '恢复失败')); }
    finally { setActionTaskId(''); }
  };
  const deleteResearchTask = async (task: FactorResearchTask) => {
    if (task.status === 'queued' || task.status === 'running') { setError('运行中的任务请先暂停，再删除'); return; }
    if (!window.confirm('删除后任务会从当前列表隐藏，但 Trial、数据集和模型证据会保留。确认删除？')) return;
    setActionTaskId(task.taskId); setError('');
    try {
      await factorLabApi.deleteResearchTask(task.taskId);
      const remaining = tasks.filter((item) => item.taskId !== task.taskId);
      setTasks(remaining);
      if (selectedTaskId === task.taskId) { setSelectedTaskId(remaining[0]?.taskId || ''); setTrials([]); }
    } catch (caught) { setError(parseApiError(caught, '删除任务失败')); }
    finally { setActionTaskId(''); }
  };

  const statistics = summary?.statistics;
  const visibleError = error || (mode !== 'manual' ? providerError : '');
  return <div className="h-full overflow-y-auto bg-crypto-bg p-4 sm:p-6">
    <div className="flex flex-wrap items-start justify-between gap-4"><div className="flex items-start gap-3"><div className="border border-cyan-500/25 bg-cyan-500/10 p-2"><LibraryBig className="h-6 w-6 text-cyan-300" /></div><div><div className="flex flex-wrap items-center gap-2"><h1 className="text-xl font-semibold text-white">因子库与实验</h1><span className="border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 text-xs text-cyan-200">机器学习验证</span><span className="border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-xs text-amber-200">研究候选</span></div><p className="mt-1 text-sm text-gray-500">自由组合连续因子，使用真实 K 线进行 walk-forward、20bps / 40bps 成本验证。</p></div></div><button type="button" onClick={() => void load(true)} disabled={loading || refreshing} className="inline-flex h-9 items-center gap-2 border border-crypto-border bg-crypto-card px-3 text-sm text-gray-300 hover:border-cyan-500/40 hover:text-white disabled:opacity-50"><RefreshCw className={clsx('h-4 w-4', refreshing && 'animate-spin')} />刷新</button></div>
    {visibleError && <div role="alert" className="mt-4 flex items-center gap-2 border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"><AlertTriangle className="h-4 w-4 shrink-0" />{visibleError}</div>}
    {loading && !summary ? <div className="mt-6 flex min-h-64 items-center justify-center border border-crypto-border bg-crypto-card text-sm text-gray-500"><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在读取 FactorLab…</div> : <>
      <div className="mt-5 grid grid-cols-2 gap-3 xl:grid-cols-6"><MetricCard label="定义总数" value={statistics?.definitionCount || 0} note="不可变版本" tone="cyan" /><MetricCard label="参数实例" value={statistics?.instanceCount || 0} note="当前注册" tone="blue" /><MetricCard label="研究任务" value={statistics?.researchTaskCount || 0} note="全部状态" tone="amber" /><MetricCard label="Trial" value={statistics?.trialCount || 0} note="失败也保留" tone="slate" /><MetricCard label="最新值" value={statistics?.latestValueCount || 0} note="运行时缓存" tone="amber" /><MetricCard label="物化分区" value={statistics?.materializedPartitionCount || 0} note="Parquet" tone="slate" /></div>
      <section className="mt-4 grid border border-crypto-border bg-crypto-card 2xl:grid-cols-[440px_minmax(0,1fr)]">
        <div className="border-b border-crypto-border p-4 2xl:border-b-0 2xl:border-r"><div className="flex items-center gap-2"><BrainCircuit className="h-4 w-4 text-cyan-300" /><h2 className="text-sm font-medium text-white">因子实验配置</h2></div>
          <div className="mt-3 grid grid-cols-3 border border-crypto-border">{([['manual', '手动组合'], ['auto', '自动组合'], ['hybrid', '混合组合']] as const).map(([value, label]) => <button key={value} type="button" aria-pressed={mode === value} onClick={() => setMode(value)} className={clsx('h-9 border-r border-crypto-border text-xs last:border-r-0', mode === value ? SELECTED_SEGMENT_CLASS : 'text-gray-500 hover:text-gray-300')}>{label}</button>)}</div>
          <div className="mt-3 grid grid-cols-2 gap-2"><Field label="市场"><select className={inputClass} value={marketType} onChange={(event) => setMarketType(event.target.value as 'stock' | 'etf')}><option value="stock">股票</option><option value="etf">ETF</option></select></Field><Field label="K 线周期"><select className={inputClass} value={timeframe} onChange={(event) => setTimeframe(event.target.value)}><option value="1d">1D</option></select></Field><Field label="开始日期"><input className={inputClass} type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></Field><Field label="结束日期"><input className={inputClass} type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></Field></div>
          <Field label="标的池（换行或逗号分隔）"><textarea className="min-h-16 w-full resize-y border border-crypto-border bg-crypto-bg px-2 py-2 font-mono text-xs text-gray-200 outline-none focus:border-cyan-500/50" value={symbols} onChange={(event) => setSymbols(event.target.value)} /></Field>
          {mode !== 'manual' && <div className="mt-3 grid grid-cols-2 gap-2 border border-blue-500/20 bg-blue-500/[0.04] p-3"><Field label="Provider"><select className={inputClass} value={providerKey} onChange={(event) => updateProvider(event.target.value)}><option value="">选择 Provider</option>{providers.map((provider) => <option key={provider.providerKey} value={provider.providerKey} disabled={!provider.configured}>{provider.displayName}{provider.configured ? '' : '（不可用）'}</option>)}</select></Field><Field label="模型"><select className={inputClass} value={model} onChange={(event) => setModel(event.target.value)}>{(selectedProvider?.models || []).map((item) => <option key={item} value={item}>{item}</option>)}</select></Field><Field label="思考深度"><select className={inputClass} value={reasoningEffort} onChange={(event) => setReasoningEffort(event.target.value)}>{(selectedProvider?.reasoningEfforts || ['auto']).map((item) => <option key={item} value={item}>{item}</option>)}</select></Field><Field label="速度"><select className={inputClass} value={speedMode} onChange={(event) => setSpeedMode(event.target.value)}>{(selectedProvider?.speedModes || ['standard']).map((item) => <option key={item} value={item}>{item}</option>)}</select></Field></div>}
          <div className="mt-3 text-[11px] text-gray-500">因子范围与权重</div><div className="mt-1 max-h-52 overflow-y-auto border border-crypto-border">{summary?.instances.map((instance) => { const definition = summary.definitions.find((item) => item.definitionId === instance.definitionId); const selected = selectedFactors.includes(instance.instanceId); return <div key={instance.instanceId} className="grid grid-cols-[20px_minmax(0,1fr)_72px] items-center gap-2 border-b border-crypto-border px-2 py-2 last:border-b-0"><input type="checkbox" checked={selected} onChange={() => toggleFactor(instance.instanceId)} aria-label={`选择 ${definition?.displayName || instance.definitionId}`} /><div className="min-w-0"><div className="truncate text-xs text-gray-300">{definition?.displayName || instance.definitionId}</div><div className="truncate font-mono text-[9px] text-gray-600">{instance.instanceId}</div></div><input type="number" step="0.1" disabled={!selected || mode === 'auto'} className="h-7 border border-crypto-border bg-crypto-bg px-1 text-right text-[11px] text-gray-300 disabled:opacity-30" value={weights[instance.instanceId] ?? 1} onChange={(event) => setWeights((current) => ({ ...current, [instance.instanceId]: Number(event.target.value) }))} aria-label={`${definition?.displayName || instance.definitionId} 权重`} /></div>; })}</div>
          <div className="mt-3 grid grid-cols-3 gap-2"><Field label="Horizon"><input className={inputClass} type="number" min={1} max={168} value={horizonBars} onChange={(event) => setHorizonBars(Number(event.target.value))} /></Field><Field label="候选上限"><input className={inputClass} type="number" min={1} max={1000} value={maxCandidates} onChange={(event) => setMaxCandidates(Number(event.target.value))} /></Field><Field label="无提升停止"><input className={inputClass} type="number" min={1} max={1000} value={maxNoImprovement} onChange={(event) => setMaxNoImprovement(Number(event.target.value))} /></Field><Field label="最长分钟"><input className={inputClass} type="number" min={1} max={1440} value={maxRuntimeMinutes} onChange={(event) => setMaxRuntimeMinutes(Number(event.target.value))} /></Field><div className="col-span-2 border border-crypto-border bg-crypto-bg px-2 py-1.5 text-[10px] leading-5 text-gray-500">固定 5 个 OOS fold · purge/embargo={horizonBars} · 20bps 基线 · 40bps 压力</div></div>
          <button type="button" disabled className="mt-3 inline-flex h-9 w-full items-center justify-center gap-2 border border-cyan-500/35 bg-cyan-500/10 text-sm font-medium text-cyan-100 disabled:opacity-40"><Play className="h-4 w-4" />A 股研究写入待接通</button><div className="mt-2 text-center text-[10px] text-amber-300/80">当前只读真实因子定义和封存快照，不创建任务或 Paper。</div>
        </div>
        <div className="min-w-0 p-4"><div className="flex items-center gap-2"><FlaskConical className="h-4 w-4 text-blue-300" /><h2 className="text-sm font-medium text-white">任务与 Trial</h2></div><div className="mt-3 grid gap-3 lg:grid-cols-[280px_minmax(0,1fr)]"><div className="max-h-[520px] overflow-y-auto border border-crypto-border">{tasks.length ? tasks.map((task) => { const active = task.status === 'queued' || task.status === 'running'; return <div key={task.taskId} className={clsx('grid grid-cols-[minmax(0,1fr)_36px] border-b border-crypto-border last:border-b-0', selectedTaskId === task.taskId ? SELECTED_SEGMENT_CLASS : 'hover:bg-white/[0.02]')}><button type="button" aria-pressed={selectedTaskId === task.taskId} onClick={() => setSelectedTaskId(task.taskId)} className="min-w-0 px-3 py-3 text-left"><div className="flex items-center justify-between gap-2"><span className="font-mono text-[10px] text-gray-500">{task.taskId}</span><span className={clsx('text-[10px]', task.status === 'running' ? 'text-cyan-300' : task.status === 'failed' ? 'text-red-300' : task.status === 'paused' ? 'text-amber-300' : 'text-gray-400')}>{statusLabels[task.status]}</span></div><div className="mt-1 truncate text-xs text-gray-200">{task.mode} · {task.model || '本地验证'}</div><div className="mt-1 text-[10px] text-gray-600">trial {task.trialCursor}/{task.maxCandidates * 3} · {task.timeframe}</div></button><button type="button" onClick={() => void deleteResearchTask(task)} disabled={active || actionTaskId === task.taskId} title={active ? '请先暂停任务再删除' : '删除任务'} aria-label={`删除任务 ${task.taskId}`} className="flex items-center justify-center border-l border-crypto-border text-gray-600 hover:bg-red-500/10 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-25"><Trash2 className="h-3.5 w-3.5" /></button></div>; }) : <div className="px-3 py-12 text-center text-xs text-gray-600">尚无研究任务</div>}</div>
          <div className="min-w-0 border border-crypto-border">{selectedTask ? <><div className="flex flex-wrap items-start justify-between gap-3 border-b border-crypto-border px-3 py-3"><div><div className="text-sm text-white">{statusLabels[selectedTask.status]} · {selectedTask.mode}</div><div className="mt-1 font-mono text-[10px] text-gray-600">{selectedTask.datasetSnapshotId || '等待数据集快照'}</div></div><div className="flex gap-2">{(selectedTask.status === 'queued' || selectedTask.status === 'running') && <button type="button" onClick={() => void runTaskAction(selectedTask, 'pause')} disabled={actionTaskId === selectedTask.taskId} className="inline-flex h-8 items-center gap-1 border border-amber-500/30 px-2 text-xs text-amber-200"><Pause className="h-3.5 w-3.5" />暂停</button>}{selectedTask.status === 'paused' && <button type="button" onClick={() => void runTaskAction(selectedTask, 'resume')} disabled={actionTaskId === selectedTask.taskId} className="inline-flex h-8 items-center gap-1 border border-cyan-500/30 px-2 text-xs text-cyan-200"><RotateCcw className="h-3.5 w-3.5" />恢复</button>}</div></div><div className="grid grid-cols-2 gap-px bg-crypto-border sm:grid-cols-4">{[['Trial', selectedTask.trialCursor], ['Horizon', selectedTask.horizonBars], ['20bps', selectedTask.baseCostBps], ['40bps', selectedTask.stressCostBps]].map(([label, value]) => <div key={label} className="bg-crypto-card px-3 py-2"><div className="text-[10px] text-gray-600">{label}</div><div className="mt-1 text-sm tabular-nums text-gray-200">{value}</div></div>)}</div>{selectedTask.stopReason && <div className="border-t border-crypto-border px-3 py-2 text-xs text-gray-500">停止原因：{selectedTask.stopReason}</div>}<div className="max-h-[380px] overflow-auto border-t border-crypto-border"><table className="w-full min-w-[760px] text-left text-[11px]"><thead className="sticky top-0 bg-gray-950 text-gray-500"><tr><th className="px-3 py-2">模型 / 假设</th><th className="px-3 py-2">Score</th><th className="px-3 py-2">20bps</th><th className="px-3 py-2">40bps</th><th className="px-3 py-2">PF / 回撤</th><th className="px-3 py-2">拒绝原因</th></tr></thead><tbody className="divide-y divide-crypto-border">{trials.length ? trials.map((trial) => <tr key={trial.trialId} className="align-top"><td className="px-3 py-2"><div className="text-gray-200">{trial.modelType}</div><div className="mt-1 max-w-52 truncate text-[10px] text-gray-600">{trial.parameters.hypothesis || trial.featureIds.join(', ')}</div></td><td className="px-3 py-2 tabular-nums text-gray-200">{trial.metrics.score?.toFixed(1) ?? '--'}</td><td className={clsx('px-3 py-2 tabular-nums', (trial.metrics.totalReturn || 0) >= 0 ? 'text-up' : 'text-down')}>{percent(trial.metrics.totalReturn)}</td><td className={clsx('px-3 py-2 tabular-nums', (trial.metrics.stressTotalReturn || 0) >= 0 ? 'text-up' : 'text-down')}>{percent(trial.metrics.stressTotalReturn)}</td><td className="px-3 py-2 text-gray-400">{trial.metrics.profitFactor?.toFixed(2) ?? '--'} / {percent(trial.metrics.maxDrawdown)}</td><td className="px-3 py-2 text-amber-300/80">{trial.hardGateFailures.length ? trial.hardGateFailures.map((item) => failureLabels[item] || item).join(' · ') : '通过硬门槛'}</td></tr>) : <tr><td colSpan={6} className="px-3 py-12 text-center text-gray-600">暂无 Trial 证据</td></tr>}</tbody></table></div></> : <div className="flex min-h-72 items-center justify-center text-xs text-gray-600">选择研究任务查看证据</div>}</div>
        </div></div>
      </section>
      <div className="mt-4 grid gap-4 2xl:grid-cols-[minmax(0,1fr)_340px]"><section className="min-w-0 border border-crypto-border bg-crypto-card"><div className="flex items-center justify-between border-b border-crypto-border px-4 py-3"><div className="flex items-center gap-2"><Boxes className="h-4 w-4 text-cyan-300" /><h2 className="text-sm font-medium text-white">因子定义</h2></div><span className="text-xs text-gray-500">连续值 · 阈值不写入定义</span></div><div className="overflow-x-auto"><table className="w-full min-w-[940px] text-left text-xs"><thead className="bg-gray-950/55 text-gray-500"><tr><th className="px-4 py-2.5">因子 / 版本</th><th className="px-4 py-2.5">家族 / 角色</th><th className="px-4 py-2.5">默认参数</th><th className="px-4 py-2.5">预热</th><th className="px-4 py-2.5">方向语义</th><th className="px-4 py-2.5">实现</th></tr></thead><tbody className="divide-y divide-crypto-border">{summary?.definitions.length ? summary.definitions.map((definition) => <tr key={`${definition.definitionId}@${definition.definitionVersion}`} className="hover:bg-white/[0.02]"><td className="px-4 py-3 align-top"><div className="font-medium text-gray-100">{definition.displayName}</div><div className="mt-1 font-mono text-[11px] text-gray-500">{definition.definitionId}@{definition.definitionVersion}</div><div className="mt-1 max-w-xs text-[11px] leading-4 text-gray-600">{definition.description}</div></td><td className="px-4 py-3 align-top text-gray-300"><div>{familyLabels[definition.family] || definition.family}</div><div className="mt-1 text-gray-500">{roleLabels[definition.role] || definition.role}</div></td><td className="px-4 py-3 align-top font-mono text-[11px] text-blue-200">{defaultParameters(definition)}</td><td className="px-4 py-3 align-top text-gray-300">{definition.lookbackBars} 根<div className="mt-1 text-gray-500">实例 {instancesByDefinition.get(definition.definitionId) || 0}</div></td><td className="px-4 py-3 align-top text-gray-400">{orientationLabels[definition.orientation] || definition.orientation}</td><td className="px-4 py-3 align-top"><div className="font-mono text-[11px] text-gray-300">{definition.kernelName}</div><div className="mt-1 font-mono text-[10px] text-gray-600">{shortHash(definition.implementationHash)}</div></td></tr>) : <tr><td colSpan={6} className="px-4 py-12 text-center text-gray-500">暂无已注册因子定义</td></tr>}</tbody></table></div></section><aside className="border border-crypto-border bg-crypto-card"><div className="flex items-center gap-2 border-b border-crypto-border px-4 py-3"><ShieldCheck className="h-4 w-4 text-amber-300" /><h2 className="text-sm font-medium text-white">数据与运行边界</h2></div><BoundaryRow ok label="16 个连续因子可用" detail="默认内置十六个；目录读取全部已注册。成交量包含 Z-Score、MFI、量价相关性、OBV 与 VWAP；并与 EMA、MACD、KDJ、RSI、ADX、ATR、布林等进入同一 ML 验证合同。" /><BoundaryRow ok={Boolean(summary?.capabilities.materializationStoreReady)} label="真实数据集快照" detail="下一根 open 标签，20bps / 40bps 成本，Parquet 与 manifest 可复查。" /><BoundaryRow ok={Boolean(summary?.capabilities.researchMetricsAvailable)} label="机器学习验证可用" detail="等权、Ridge、Logistic；至少 5 个 OOS fold，分数不能覆盖硬门槛。" /><BoundaryRow ok={false} label="尚未接入策略运行时" detail="研究结果不会改变原策略信号、仓位或退出保护。" /><BoundaryRow ok={false} label="未连接 Paper / Live" detail="不读取账户，不创建模拟盘，不发送订单。" /><div className="m-4 border border-blue-500/20 bg-blue-500/[0.06] p-3 text-xs leading-5 text-blue-200/80">ADX14 ≥ 18、MFI ≥ 80 等条件属于实验组合；因子定义仍保存连续值。</div></aside></div>
      <section className="mt-4 border border-crypto-border bg-crypto-card"><div className="flex flex-wrap items-center justify-between gap-2 border-b border-crypto-border px-4 py-3"><div className="flex items-center gap-2"><FileStack className="h-4 w-4 text-blue-300" /><h2 className="text-sm font-medium text-white">已注册参数实例</h2></div><div className="flex items-center gap-3 text-xs text-gray-500"><span className="inline-flex items-center gap-1"><Database className="h-3.5 w-3.5" /> SQLite 控制面</span><span className="inline-flex items-center gap-1"><Cpu className="h-3.5 w-3.5" /> ML Worker</span><span className="inline-flex items-center gap-1"><Gauge className="h-3.5 w-3.5" /> 严格预热</span></div></div><div className="overflow-x-auto"><table className="w-full min-w-[880px] text-left text-xs"><thead className="bg-gray-950/55 text-gray-500"><tr><th className="px-4 py-2.5">实例 ID</th><th className="px-4 py-2.5">定义</th><th className="px-4 py-2.5">参数</th><th className="px-4 py-2.5">所需 K 线</th><th className="px-4 py-2.5">状态</th></tr></thead><tbody className="divide-y divide-crypto-border">{summary?.instances.length ? summary.instances.map((instance) => <tr key={instance.instanceId} className="hover:bg-white/[0.02]"><td className="px-4 py-3 font-mono text-[11px] text-gray-300">{instance.instanceId}</td><td className="px-4 py-3 text-gray-400">{instance.definitionId}@{instance.definitionVersion}</td><td className="px-4 py-3 font-mono text-[11px] text-blue-200">{instance.parametersJson}</td><td className="px-4 py-3 tabular-nums text-gray-300">{instance.requiredBars} 根</td><td className="px-4 py-3"><span className="border border-cyan-500/25 bg-cyan-500/10 px-2 py-1 text-[11px] text-cyan-200">{instance.isDefault ? '默认实例' : '已注册实例'}</span></td></tr>) : <tr><td colSpan={5} className="px-4 py-12 text-center text-gray-500">暂无参数实例</td></tr>}</tbody></table></div></section>
    </>}
  </div>;
}
