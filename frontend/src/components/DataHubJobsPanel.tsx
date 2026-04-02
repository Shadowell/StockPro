import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  createDataHubJob,
  getDataHubJobs,
  getDataHubJob,
  getDataHubJobLogs,
  rerunDataHubJob,
  cancelDataHubJob,
  getDataDevTasks,
  DataHubJob,
  DataDevTask,
} from '@/api/client';
import { Play, RefreshCw, RotateCcw, StopCircle, AlertCircle, CheckCircle2, Clock3, X } from 'lucide-react';

type JobAction =
  | 'import_daily_data'
  | 'run_data_dev_task'
  | 'backfill_concept_history'
  | 'sync_today_concepts'
  | 'init_factor_definitions'
  | 'sync_factor_spot'
  | 'sync_factor_technical'
  | 'sync_factor_all';

const actionLabel: Record<JobAction, string> = {
  import_daily_data: '日频数据生产（行情+基本面）',
  run_data_dev_task: '执行数据开发任务',
  backfill_concept_history: '板块历史回补',
  sync_today_concepts: '同步今日板块',
  init_factor_definitions: '初始化因子定义',
  sync_factor_spot: '同步实时因子',
  sync_factor_technical: '同步技术因子',
  sync_factor_all: '同步全部因子',
};

const badgeClass = (status: string): string => {
  if (status === 'success') return 'bg-green-500/20 text-green-400 border-green-500/30';
  if (status === 'failed') return 'bg-red-500/20 text-red-400 border-red-500/30';
  if (status === 'cancelled') return 'bg-slate-700 text-slate-300 border-slate-600';
  if (status === 'running') return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
  return 'bg-amber-500/20 text-amber-400 border-amber-500/30';
};

const getErrorMessage = (error: unknown, fallback: string): string => {
  if (typeof error === 'object' && error !== null) {
    const maybeError = error as {
      message?: unknown;
      response?: { data?: { detail?: unknown } };
    };
    const detail = maybeError.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (typeof maybeError.message === 'string' && maybeError.message.trim()) return maybeError.message;
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
};

const isDatasetScope = (scope?: string | null): scope is string =>
  Boolean(scope && scope !== 'quality' && scope !== 'data_dev_tasks');

const extractJobDatasets = (job: DataHubJob): string[] => {
  const datasets = new Set<string>();
  if (isDatasetScope(job.scope)) {
    datasets.add(job.scope);
  }
  const params = (job.params || {}) as Record<string, unknown>;
  const paramDatasets = params.datasets;
  if (Array.isArray(paramDatasets)) {
    paramDatasets.forEach((item) => {
      if (typeof item === 'string' && item.trim()) datasets.add(item.trim());
    });
  }
  if (job.action === 'sync_today_concepts' || job.action === 'backfill_concept_history') {
    datasets.add('daily_concept_sectors');
  }
  if (job.action.startsWith('sync_factor_') || job.action === 'init_factor_definitions') {
    datasets.add('factor_data');
  }
  return Array.from(datasets);
};

const parseTimeToMs = (value?: string | null): number => {
  if (!value) return 0;
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : 0;
};

const formatTime = (value?: string | null): string => {
  if (!value) return '-';
  const ms = parseTimeToMs(value);
  if (!ms) return value;
  const d = new Date(ms);
  const y = d.getFullYear();
  const m = `${d.getMonth() + 1}`.padStart(2, '0');
  const day = `${d.getDate()}`.padStart(2, '0');
  const h = `${d.getHours()}`.padStart(2, '0');
  const min = `${d.getMinutes()}`.padStart(2, '0');
  const sec = `${d.getSeconds()}`.padStart(2, '0');
  return `${y}-${m}-${day} ${h}:${min}:${sec}`;
};

const durationText = (job: DataHubJob): string => {
  const start = parseTimeToMs(job.started_at || job.created_at);
  const end = parseTimeToMs(job.finished_at);
  if (!start || !end || end < start) return '-';
  const sec = Math.floor((end - start) / 1000);
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return `${h}h ${m}m`;
};

const timelineNodeClass = (status: string): string => {
  if (status === 'success') return 'border-green-500/40 bg-green-500/10';
  if (status === 'failed') return 'border-red-500/40 bg-red-500/10';
  if (status === 'cancelled') return 'border-amber-500/40 bg-amber-500/10';
  if (status === 'running') return 'border-blue-500/40 bg-blue-500/10';
  return 'border-slate-700 bg-slate-800/60';
};

export const DataHubJobsPanel: React.FC = () => {
  const [action, setAction] = useState<JobAction>('import_daily_data');
  const [date, setDate] = useState<string>(() => new Date().toISOString().split('T')[0]);
  const [taskType, setTaskType] = useState<'history' | 'fundamentals' | 'all'>('all');
  const [dataDevTaskId, setDataDevTaskId] = useState<number>(0);
  const [backfillDays, setBackfillDays] = useState(30);
  const [jobs, setJobs] = useState<DataHubJob[]>([]);
  const [tasks, setTasks] = useState<DataDevTask[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loadingLogsKey, setLoadingLogsKey] = useState<string | null>(null);
  const [actionFilter, setActionFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [datasetFilter, setDatasetFilter] = useState<string>('all');
  const [detailJob, setDetailJob] = useState<DataHubJob | null>(null);
  const [detailParentChain, setDetailParentChain] = useState<DataHubJob[]>([]);
  const [detailChildren, setDetailChildren] = useState<DataHubJob[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);

  const activeJobs = useMemo(() => jobs.filter((j) => j.status === 'running' || j.status === 'queued'), [jobs]);
  const datasetFilterOptions = useMemo(() => {
    const set = new Set<string>();
    jobs.forEach((job) => extractJobDatasets(job).forEach((d) => set.add(d)));
    return Array.from(set).sort();
  }, [jobs]);
  const actionFilterOptions = useMemo(() => Array.from(new Set(jobs.map((j) => j.action))).sort(), [jobs]);
  const filteredJobs = useMemo(() => {
    return jobs.filter((job) => {
      if (actionFilter !== 'all' && job.action !== actionFilter) return false;
      if (statusFilter !== 'all' && job.status !== statusFilter) return false;
      if (datasetFilter !== 'all' && !extractJobDatasets(job).includes(datasetFilter)) return false;
      return true;
    });
  }, [jobs, actionFilter, statusFilter, datasetFilter]);
  const detailTimeline = useMemo(() => {
    if (!detailJob) return [] as Array<{ relation: 'parent' | 'current' | 'child'; job: DataHubJob; sortMs: number }>;
    const nodes: Array<{ relation: 'parent' | 'current' | 'child'; job: DataHubJob; sortMs: number }> = [];
    detailParentChain.forEach((job) => {
      nodes.push({
        relation: 'parent',
        job,
        sortMs: parseTimeToMs(job.started_at || job.created_at || job.finished_at),
      });
    });
    nodes.push({
      relation: 'current',
      job: detailJob,
      sortMs: parseTimeToMs(detailJob.started_at || detailJob.created_at || detailJob.finished_at),
    });
    detailChildren.forEach((job) => {
      nodes.push({
        relation: 'child',
        job,
        sortMs: parseTimeToMs(job.started_at || job.created_at || job.finished_at),
      });
    });

    const dedup = new Map<string, { relation: 'parent' | 'current' | 'child'; job: DataHubJob; sortMs: number }>();
    nodes.forEach((node) => {
      const existed = dedup.get(node.job.job_key);
      if (!existed || node.relation === 'current') dedup.set(node.job.job_key, node);
    });
    return Array.from(dedup.values()).sort((a, b) => a.sortMs - b.sortMs);
  }, [detailJob, detailParentChain, detailChildren]);

  const loadJobs = useCallback(async () => {
    setLoading(true);
    try {
      const list = await getDataHubJobs({ limit: 50 });
      setJobs(list);
    } catch (err) {
      setError(getErrorMessage(err, '加载任务列表失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDataDevTasks = useCallback(async () => {
    try {
      const list = await getDataDevTasks();
      setTasks(list);
      if (list.length > 0) {
        setDataDevTaskId(Number(list[0].id));
      }
    } catch {
      setTasks([]);
    }
  }, []);

  useEffect(() => {
    void loadJobs();
    void loadDataDevTasks();
  }, [loadJobs, loadDataDevTasks]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadJobs();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [loadJobs]);

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      let params: Record<string, unknown> = {};
      let scope = '';
      if (action === 'import_daily_data') {
        params = {
          date,
          task_type: taskType,
          datasets: taskType === 'all' ? ['stock_history', 'stock_fundamentals'] : [taskType === 'fundamentals' ? 'stock_fundamentals' : 'stock_history'],
        };
        scope = taskType === 'fundamentals' ? 'stock_fundamentals' : 'stock_history';
      } else if (action === 'run_data_dev_task') {
        if (!dataDevTaskId) {
          throw new Error('请先选择可执行的数据开发任务');
        }
        params = { task_id: dataDevTaskId };
        scope = 'data_dev_tasks';
      } else if (action === 'backfill_concept_history') {
        params = { days: backfillDays };
        scope = 'daily_concept_sectors';
      } else if (action === 'sync_today_concepts') {
        params = {};
        scope = 'daily_concept_sectors';
      } else if (action === 'init_factor_definitions') {
        params = {};
        scope = 'factor_data';
      } else if (action === 'sync_factor_spot') {
        params = { date };
        scope = 'factor_data';
      } else if (action === 'sync_factor_technical') {
        params = { date };
        scope = 'factor_data';
      } else if (action === 'sync_factor_all') {
        params = { date };
        scope = 'factor_data';
      }
      const job = await createDataHubJob({ action, params, scope });
      setMessage(`任务已创建：${job.job_key}`);
      await loadJobs();
    } catch (err) {
      setError(getErrorMessage(err, '创建任务失败'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleRerun = async (jobKey: string) => {
    setError(null);
    try {
      await rerunDataHubJob(jobKey);
      await loadJobs();
    } catch (err) {
      setError(getErrorMessage(err, '重跑任务失败'));
    }
  };

  const handleCancel = async (jobKey: string) => {
    setError(null);
    try {
      await cancelDataHubJob(jobKey);
      await loadJobs();
    } catch (err) {
      setError(getErrorMessage(err, '取消任务失败'));
    }
  };

  const handleLoadLogs = async (jobKey: string) => {
    setLoadingLogsKey(jobKey);
    setError(null);
    try {
      const logs = await getDataHubJobLogs(jobKey, 120);
      setJobs((prev) =>
        prev.map((job) => (job.job_key === jobKey ? { ...job, logs } : job))
      );
    } catch (err) {
      setError(getErrorMessage(err, '加载任务日志失败'));
    } finally {
      setLoadingLogsKey(null);
    }
  };

  const handleOpenDetail = async (jobKey: string) => {
    setDetailLoading(true);
    setError(null);
    setDetailParentChain([]);
    setDetailChildren([]);
    try {
      const hydrateLogs = async (item: DataHubJob): Promise<DataHubJob> => {
        if (item.logs && item.logs.length > 0) return item;
        const logs = await getDataHubJobLogs(item.job_key, 200);
        return { ...item, logs };
      };

      const baseJob = await hydrateLogs(await getDataHubJob(jobKey));

      const parents: DataHubJob[] = [];
      let parentKey = baseJob.parent_job_key || null;
      while (parentKey) {
        const parent = await hydrateLogs(await getDataHubJob(parentKey));
        parents.unshift(parent);
        parentKey = parent.parent_job_key || null;
      }

      const childrenRaw = await getDataHubJobs({ parent_job_key: baseJob.job_key, limit: 100 });
      const children = await Promise.all(childrenRaw.map((item) => hydrateLogs(item)));

      setDetailJob(baseJob);
      setDetailParentChain(parents);
      setDetailChildren(children);
    } catch (err) {
      setError(getErrorMessage(err, '加载任务详情失败'));
    } finally {
      setDetailLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clock3 className="text-emerald-400" size={18} />
          <span className="text-sm font-semibold text-gray-100">数据生产任务编排</span>
          <span className="px-2 py-0.5 text-[11px] rounded bg-slate-800 text-slate-400 border border-slate-700">
            已统一至 data-hub/jobs
          </span>
        </div>
        <button
          onClick={() => void loadJobs()}
          disabled={loading}
          className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 flex items-center gap-1"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>

      <div className="p-4 space-y-4 overflow-auto">
        {(error || message) && (
          <div
            className={`px-3 py-2 rounded border text-sm ${
              error ? 'border-red-500/30 bg-red-500/10 text-red-400' : 'border-green-500/30 bg-green-500/10 text-green-400'
            }`}
          >
            {error || message}
          </div>
        )}

        <div className="rounded border border-slate-800 bg-[#0d121f] p-4 space-y-3">
          <div className="text-sm font-semibold text-slate-100">发起任务</div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3">
            <div className="xl:col-span-2">
              <label className="text-xs text-slate-500 block mb-1">任务动作</label>
              <select
                value={action}
                onChange={(e) => setAction(e.target.value as JobAction)}
                className="w-full px-3 py-2 rounded bg-slate-800 border border-slate-700 text-sm text-slate-200"
              >
                {(Object.keys(actionLabel) as JobAction[]).map((key) => (
                  <option key={key} value={key}>
                    {actionLabel[key]}
                  </option>
                ))}
              </select>
            </div>

            {action === 'import_daily_data' && (
              <>
                <div>
                  <label className="text-xs text-slate-500 block mb-1">目标日期</label>
                  <input
                    type="date"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                    className="w-full px-3 py-2 rounded bg-slate-800 border border-slate-700 text-sm text-slate-200"
                  />
                </div>
                <div>
                  <label className="text-xs text-slate-500 block mb-1">任务类型</label>
                  <select
                    value={taskType}
                    onChange={(e) => setTaskType(e.target.value as 'history' | 'fundamentals' | 'all')}
                    className="w-full px-3 py-2 rounded bg-slate-800 border border-slate-700 text-sm text-slate-200"
                  >
                    <option value="all">history + fundamentals</option>
                    <option value="history">history</option>
                    <option value="fundamentals">fundamentals</option>
                  </select>
                </div>
              </>
            )}

            {(action === 'sync_factor_spot' || action === 'sync_factor_technical' || action === 'sync_factor_all') && (
              <div>
                <label className="text-xs text-slate-500 block mb-1">同步日期</label>
                <input
                  type="date"
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                  className="w-full px-3 py-2 rounded bg-slate-800 border border-slate-700 text-sm text-slate-200"
                />
              </div>
            )}

            {action === 'run_data_dev_task' && (
              <div className="xl:col-span-2">
                <label className="text-xs text-slate-500 block mb-1">Data Dev 任务</label>
                <select
                  value={dataDevTaskId || ''}
                  onChange={(e) => setDataDevTaskId(Number(e.target.value))}
                  className="w-full px-3 py-2 rounded bg-slate-800 border border-slate-700 text-sm text-slate-200"
                >
                  {tasks.map((task) => (
                    <option key={task.id} value={task.id}>
                      #{task.id} {task.name}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {action === 'backfill_concept_history' && (
              <div>
                <label className="text-xs text-slate-500 block mb-1">回补天数</label>
                <input
                  type="number"
                  min={1}
                  max={365}
                  value={backfillDays}
                  onChange={(e) => setBackfillDays(Math.max(1, Number(e.target.value) || 30))}
                  className="w-full px-3 py-2 rounded bg-slate-800 border border-slate-700 text-sm text-slate-200"
                />
              </div>
            )}
          </div>
          <button
            onClick={() => void handleSubmit()}
            disabled={submitting}
            className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-500 text-sm text-white flex items-center gap-2"
          >
            {submitting ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
            提交任务
          </button>
        </div>

        <div className="rounded border border-slate-800 bg-[#0d121f] p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="text-sm font-semibold text-slate-100">任务执行列表</div>
            <div className="text-xs text-slate-500">
              运行中 {activeJobs.length} 个 · 当前筛选 {filteredJobs.length} 个
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mb-3">
            <select
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
              className="w-full px-2 py-1.5 rounded bg-slate-800 border border-slate-700 text-xs text-slate-200"
            >
              <option value="all">全部动作</option>
              {actionFilterOptions.map((item) => (
                <option key={item} value={item}>
                  {actionLabel[item as JobAction] || item}
                </option>
              ))}
            </select>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-full px-2 py-1.5 rounded bg-slate-800 border border-slate-700 text-xs text-slate-200"
            >
              <option value="all">全部状态</option>
              <option value="queued">queued</option>
              <option value="running">running</option>
              <option value="success">success</option>
              <option value="failed">failed</option>
              <option value="cancelled">cancelled</option>
            </select>
            <select
              value={datasetFilter}
              onChange={(e) => setDatasetFilter(e.target.value)}
              className="w-full px-2 py-1.5 rounded bg-slate-800 border border-slate-700 text-xs text-slate-200"
            >
              <option value="all">全部数据集</option>
              {datasetFilterOptions.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          {filteredJobs.length === 0 ? (
            <div className="text-xs text-slate-500">暂无任务记录</div>
          ) : (
            <div className="space-y-2">
              {filteredJobs.map((job) => (
                <div key={job.job_key} className="rounded border border-slate-800 bg-slate-900/60 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <div className="text-xs text-slate-500">{job.job_key}</div>
                      <div className="text-sm text-slate-200">{actionLabel[job.action as JobAction] || job.action}</div>
                    </div>
                    <span className={`px-2 py-0.5 rounded border text-[11px] font-bold ${badgeClass(job.status)}`}>
                      {job.status}
                    </span>
                  </div>
                  <div className="mt-2 text-xs text-slate-400">
                    progress {Math.round(job.progress || 0)}% · {job.message || '-'}
                  </div>
                  {extractJobDatasets(job).length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {extractJobDatasets(job).map((ds) => (
                        <span key={`${job.job_key}-${ds}`} className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-[10px] text-slate-300">
                          {ds}
                        </span>
                      ))}
                    </div>
                  )}
                  {job.error_message && <div className="mt-1 text-xs text-red-400">error: {job.error_message}</div>}
                  <div className="mt-2 flex items-center gap-2">
                    <button
                      onClick={() => void handleOpenDetail(job.job_key)}
                      className="px-2 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700 text-slate-200"
                    >
                      详情
                    </button>
                    <button
                      onClick={() => void handleLoadLogs(job.job_key)}
                      className="px-2 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700 text-slate-200 flex items-center gap-1"
                    >
                      <RefreshCw size={12} className={loadingLogsKey === job.job_key ? 'animate-spin' : ''} />
                      日志
                    </button>
                    <button
                      onClick={() => void handleRerun(job.job_key)}
                      className="px-2 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700 text-slate-200 flex items-center gap-1"
                    >
                      <RotateCcw size={12} />
                      重跑
                    </button>
                    {(job.status === 'running' || job.status === 'queued') && (
                      <button
                        onClick={() => void handleCancel(job.job_key)}
                        className="px-2 py-1 text-xs rounded bg-red-600 hover:bg-red-500 text-white flex items-center gap-1"
                      >
                        <StopCircle size={12} />
                        取消
                      </button>
                    )}
                    {job.status === 'success' && (
                      <span className="text-[11px] text-green-400 flex items-center gap-1">
                        <CheckCircle2 size={12} />
                        完成
                      </span>
                    )}
                    {job.status === 'failed' && (
                      <span className="text-[11px] text-red-400 flex items-center gap-1">
                        <AlertCircle size={12} />
                        失败
                      </span>
                    )}
                  </div>
                  {job.logs && job.logs.length > 0 && (
                    <div className="mt-3 border border-slate-800 rounded bg-slate-950/50 p-2 space-y-1 max-h-36 overflow-auto">
                      {job.logs.slice(-6).map((line, idx) => (
                        <div key={`${job.job_key}-log-${idx}`} className="text-[11px] text-slate-400">
                          <span className="text-slate-500">{line.timestamp?.replace('T', ' ').slice(0, 19)}</span>
                          {' '}
                          <span className="uppercase text-slate-500">{line.level}</span>
                          {' '}
                          {line.message}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {detailJob && (
        <div className="fixed inset-0 z-50 bg-black/60 flex justify-end">
          <div className="w-full max-w-2xl h-full bg-slate-950 border-l border-slate-800 overflow-auto">
            <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold text-slate-100">任务详情</div>
                <div className="text-xs text-slate-500">{detailJob.job_key}</div>
              </div>
              <button
                onClick={() => {
                  setDetailJob(null);
                  setDetailParentChain([]);
                  setDetailChildren([]);
                }}
                className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200"
              >
                <X size={14} />
              </button>
            </div>
            <div className="p-4 space-y-4 text-xs">
              {detailLoading && <div className="text-slate-500">加载详情中...</div>}
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded border border-slate-800 bg-slate-900/60 p-2">
                  <div className="text-slate-500">动作</div>
                  <div className="text-slate-200">{actionLabel[detailJob.action as JobAction] || detailJob.action}</div>
                </div>
                <div className="rounded border border-slate-800 bg-slate-900/60 p-2">
                  <div className="text-slate-500">状态</div>
                  <div className="text-slate-200">{detailJob.status}</div>
                </div>
                <div className="rounded border border-slate-800 bg-slate-900/60 p-2">
                  <div className="text-slate-500">Scope</div>
                  <div className="text-slate-200">{detailJob.scope || '-'}</div>
                </div>
                <div className="rounded border border-slate-800 bg-slate-900/60 p-2">
                  <div className="text-slate-500">Progress</div>
                  <div className="text-slate-200">{Math.round(detailJob.progress || 0)}%</div>
                </div>
                <div className="rounded border border-slate-800 bg-slate-900/60 p-2">
                  <div className="text-slate-500">Created</div>
                  <div className="text-slate-200">{detailJob.created_at || '-'}</div>
                </div>
                <div className="rounded border border-slate-800 bg-slate-900/60 p-2">
                  <div className="text-slate-500">Finished</div>
                  <div className="text-slate-200">{detailJob.finished_at || '-'}</div>
                </div>
              </div>

              {detailJob.error_message && (
                <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-red-300">
                  {detailJob.error_message}
                </div>
              )}

              <div className="rounded border border-slate-800 bg-slate-900/60 p-3">
                <div className="text-slate-400 mb-2">父子任务链路</div>
                {detailTimeline.length === 0 ? (
                  <div className="text-[11px] text-slate-500">无</div>
                ) : (
                  <div className="space-y-2">
                    {detailTimeline.map((node, idx) => (
                      <div key={`timeline-${node.job.job_key}`} className="flex gap-2">
                        <div className="flex flex-col items-center">
                          <span
                            className={`mt-1 h-2.5 w-2.5 rounded-full ${
                              node.job.status === 'failed'
                                ? 'bg-red-400'
                                : node.job.status === 'cancelled'
                                  ? 'bg-amber-400'
                                  : node.job.status === 'success'
                                    ? 'bg-green-400'
                                    : node.job.status === 'running'
                                      ? 'bg-blue-400'
                                      : 'bg-slate-500'
                            }`}
                          />
                          {idx < detailTimeline.length - 1 && <span className="mt-1 h-8 w-px bg-slate-700" />}
                        </div>
                        <button
                          onClick={() => void handleOpenDetail(node.job.job_key)}
                          className={`flex-1 text-left rounded border p-2 hover:bg-slate-700/50 ${timelineNodeClass(node.job.status)}`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-[11px] text-slate-300 font-semibold">
                              {node.relation === 'parent' ? '父任务' : node.relation === 'child' ? '子任务' : '当前任务'}
                            </span>
                            <span className={`px-1.5 py-0.5 rounded border text-[10px] ${badgeClass(node.job.status)}`}>
                              {node.job.status}
                            </span>
                          </div>
                          <div className="mt-1 text-[11px] text-slate-200">
                            {actionLabel[node.job.action as JobAction] || node.job.action}
                          </div>
                          <div className="mt-1 text-[10px] text-slate-500">{node.job.job_key}</div>
                          <div className="mt-1 text-[10px] text-slate-500">
                            started: {formatTime(node.job.started_at || node.job.created_at)} · finished: {formatTime(node.job.finished_at)}
                          </div>
                          <div className="mt-1 text-[10px] text-slate-500">duration: {durationText(node.job)}</div>
                          {node.job.error_message && (
                            <div className="mt-1 text-[10px] text-red-300 line-clamp-2">{node.job.error_message}</div>
                          )}
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <div className="mt-2 text-[10px] text-slate-500">
                  按 started_at / created_at 时间排序，失败或取消节点已高亮。
                </div>
              </div>

              <div className="rounded border border-slate-800 bg-slate-900/60 p-3">
                <div className="text-slate-400 mb-1">参数</div>
                <pre className="text-[11px] text-slate-200 whitespace-pre-wrap break-words">
                  {JSON.stringify(detailJob.params || {}, null, 2)}
                </pre>
              </div>

              <div className="rounded border border-slate-800 bg-slate-900/60 p-3">
                <div className="text-slate-400 mb-1">结果</div>
                <pre className="text-[11px] text-slate-200 whitespace-pre-wrap break-words">
                  {JSON.stringify(detailJob.result || {}, null, 2)}
                </pre>
              </div>

              <div className="rounded border border-slate-800 bg-slate-900/60 p-3">
                <div className="text-slate-400 mb-1">日志</div>
                {detailJob.logs && detailJob.logs.length > 0 ? (
                  <div className="space-y-1 max-h-72 overflow-auto">
                    {detailJob.logs.map((line, idx) => (
                      <div key={`detail-log-${idx}`} className="text-[11px] text-slate-300">
                        <span className="text-slate-500">{line.timestamp?.replace('T', ' ').slice(0, 19)}</span>
                        {' '}
                        <span className="uppercase text-slate-500">{line.level}</span>
                        {' '}
                        {line.message}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-slate-500">暂无日志</div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
