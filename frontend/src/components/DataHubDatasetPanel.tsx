import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Database, RefreshCw, Link2, KeyRound, Clock3, AlertTriangle, CheckCircle2, Play } from 'lucide-react';
import { DataHubDataset, DataHubDatasetFreshness, createDataHubJob, getDataHubDatasets, getDataHubDatasetFreshness } from '@/api/client';

const statusBadgeClass = (status: string): string => {
  if (status === 'green') return 'bg-green-500/20 text-green-400 border-green-500/30';
  if (status === 'yellow') return 'bg-amber-500/20 text-amber-400 border-amber-500/30';
  return 'bg-red-500/20 text-red-400 border-red-500/30';
};

const statusLabel = (status: string): string => {
  if (status === 'green') return '健康';
  if (status === 'yellow') return '预警';
  return '风险';
};

export const DataHubDatasetPanel: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [datasets, setDatasets] = useState<DataHubDataset[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [freshness, setFreshness] = useState<DataHubDatasetFreshness | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [recovering, setRecovering] = useState(false);
  const [recoverDate, setRecoverDate] = useState<string>(() => new Date().toISOString().split('T')[0]);
  const [backfillDays, setBackfillDays] = useState<number>(30);

  interface RecoveryAction {
    id: string;
    label: string;
    action: string;
    scope: string;
    params: Record<string, unknown>;
  }

  const sortedDatasets = useMemo(
    () => datasets.slice().sort((a, b) => a.id.localeCompare(b.id)),
    [datasets]
  );

  const loadDatasets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await getDataHubDatasets();
      setDatasets(items);
      if (!selectedId && items.length > 0) {
        setSelectedId(items[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载数据集失败');
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  const loadFreshness = async (datasetId: string) => {
    try {
      const detail = await getDataHubDatasetFreshness(datasetId);
      setFreshness(detail);
    } catch (err) {
      setFreshness(null);
      setError(err instanceof Error ? err.message : '加载数据新鲜度失败');
    }
  };

  useEffect(() => {
    void loadDatasets();
  }, [loadDatasets]);

  useEffect(() => {
    if (selectedId) {
      void loadFreshness(selectedId);
    }
  }, [selectedId]);

  const recoveryActions = useMemo<RecoveryAction[]>(() => {
    const datasetId = freshness?.dataset.id;
    if (!datasetId) return [];
    if (datasetId === 'stock_history') {
      return [
        {
          id: 'recover-history',
          label: '重跑行情',
          action: 'import_daily_data',
          scope: 'stock_history',
          params: { date: recoverDate, task_type: 'history', datasets: ['stock_history'] },
        },
        {
          id: 'recover-history-fund',
          label: '重跑行情+基本面',
          action: 'import_daily_data',
          scope: 'stock_history',
          params: { date: recoverDate, task_type: 'all', datasets: ['stock_history', 'stock_fundamentals'] },
        },
      ];
    }
    if (datasetId === 'stock_fundamentals') {
      return [
        {
          id: 'recover-fundamentals',
          label: '重跑基本面',
          action: 'import_daily_data',
          scope: 'stock_fundamentals',
          params: { date: recoverDate, task_type: 'fundamentals', datasets: ['stock_fundamentals'] },
        },
      ];
    }
    if (datasetId === 'daily_concept_sectors') {
      return [
        {
          id: 'recover-concepts-today',
          label: '同步今日板块',
          action: 'sync_today_concepts',
          scope: 'daily_concept_sectors',
          params: {},
        },
        {
          id: 'recover-concepts-backfill',
          label: `回补${backfillDays}天`,
          action: 'backfill_concept_history',
          scope: 'daily_concept_sectors',
          params: { days: backfillDays },
        },
      ];
    }
    if (datasetId === 'factor_data') {
      return [
        {
          id: 'recover-factor-spot',
          label: '同步实时因子',
          action: 'sync_factor_spot',
          scope: 'factor_data',
          params: { date: recoverDate },
        },
        {
          id: 'recover-factor-all',
          label: '同步全部因子',
          action: 'sync_factor_all',
          scope: 'factor_data',
          params: { date: recoverDate },
        },
      ];
    }
    return [];
  }, [freshness?.dataset.id, recoverDate, backfillDays]);

  const handleRunRecovery = async (item: RecoveryAction) => {
    setRecovering(true);
    setError(null);
    setMessage(null);
    try {
      const job = await createDataHubJob({
        action: item.action,
        scope: item.scope,
        params: item.params,
      });
      setMessage(`已提交恢复任务：${job.job_key}`);
      await loadDatasets();
      if (selectedId) {
        await loadFreshness(selectedId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交恢复任务失败');
    } finally {
      setRecovering(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Database className="text-blue-400" size={18} />
          <span className="text-sm font-semibold text-gray-100">数据资产注册表</span>
        </div>
        <button
          onClick={() => {
            void loadDatasets();
            if (selectedId) void loadFreshness(selectedId);
          }}
          className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 flex items-center gap-1"
          disabled={loading}
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[420px_1fr] h-full min-h-0">
        <div className="border-r border-slate-800 overflow-auto">
          {(error || message) && (
            <div
              className={`m-3 px-3 py-2 rounded border text-xs ${
                error
                  ? 'border-red-500/30 bg-red-500/10 text-red-400'
                  : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
              }`}
            >
              {error || message}
            </div>
          )}
          <div className="p-3 space-y-3">
            {sortedDatasets.map((ds) => (
              <button
                key={ds.id}
                onClick={() => setSelectedId(ds.id)}
                className={`w-full text-left p-3 rounded border transition ${
                  selectedId === ds.id
                    ? 'border-blue-500/40 bg-blue-500/10'
                    : 'border-slate-800 bg-[#0d121f] hover:border-slate-700'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <div className="text-sm font-semibold text-slate-100">{ds.name}</div>
                    <div className="text-xs text-slate-500 mt-0.5">{ds.id}</div>
                  </div>
                  <span className={`px-2 py-0.5 rounded border text-[11px] font-bold ${statusBadgeClass(ds.freshness_status)}`}>
                    {statusLabel(ds.freshness_status)}
                  </span>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div className="bg-slate-900/60 rounded px-2 py-1">
                    <div className="text-slate-500">行数</div>
                    <div className="text-slate-200 font-semibold">{ds.row_count.toLocaleString()}</div>
                  </div>
                  <div className="bg-slate-900/60 rounded px-2 py-1">
                    <div className="text-slate-500">主键</div>
                    <div className="text-slate-200 font-semibold">{ds.primary_keys.length}</div>
                  </div>
                  <div className="bg-slate-900/60 rounded px-2 py-1">
                    <div className="text-slate-500">频率</div>
                    <div className="text-slate-200 font-semibold">{ds.refresh_frequency}</div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-auto p-4 space-y-4">
          {freshness ? (
            <>
              <div className="rounded border border-slate-800 bg-[#0d121f] p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-sm font-semibold text-slate-100">{freshness.dataset.name}</div>
                  <span className={`px-2 py-0.5 rounded border text-[11px] font-bold ${statusBadgeClass(freshness.dataset.freshness_status)}`}>
                    {statusLabel(freshness.dataset.freshness_status)}
                  </span>
                </div>
                <div className="text-xs text-slate-500 mb-3">表名：{freshness.dataset.table}</div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                  <div className="rounded border border-slate-800 bg-slate-900/60 p-3">
                    <div className="text-xs text-slate-500 mb-1 flex items-center gap-1">
                      <Clock3 size={12} />
                      最新快照
                    </div>
                    <div className="text-slate-200 font-semibold">{freshness.dataset.latest_snapshot || '-'}</div>
                  </div>
                  <div className="rounded border border-slate-800 bg-slate-900/60 p-3">
                    <div className="text-xs text-slate-500 mb-1 flex items-center gap-1">
                      <KeyRound size={12} />
                      主键定义
                    </div>
                    <div className="text-slate-200 font-semibold">{freshness.dataset.primary_keys.join(', ') || '-'}</div>
                  </div>
                </div>

                <div className="mt-4">
                  <div className="text-xs text-slate-500 mb-2 flex items-center gap-1">
                    <Link2 size={12} />
                    依赖关系
                  </div>
                  {freshness.dataset.dependencies.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {freshness.dataset.dependencies.map((dep) => (
                        <span key={dep} className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-xs border border-slate-700">
                          {dep}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <div className="text-xs text-slate-500">无依赖</div>
                  )}
                </div>

                <div className="mt-4">
                  <div className="text-xs text-slate-500 mb-2">可恢复动作</div>
                  {freshness.dataset.id !== 'daily_concept_sectors' && (
                    <div className="mb-3">
                      <label className="text-xs text-slate-500 block mb-1">目标日期</label>
                      <input
                        type="date"
                        value={recoverDate}
                        onChange={(e) => setRecoverDate(e.target.value)}
                        className="w-full md:w-64 px-3 py-2 rounded bg-slate-800 border border-slate-700 text-xs text-slate-200"
                      />
                    </div>
                  )}
                  {freshness.dataset.id === 'daily_concept_sectors' && (
                    <div className="mb-3">
                      <label className="text-xs text-slate-500 block mb-1">回补天数</label>
                      <input
                        type="number"
                        min={1}
                        max={365}
                        value={backfillDays}
                        onChange={(e) => setBackfillDays(Math.max(1, Number(e.target.value) || 30))}
                        className="w-full md:w-40 px-3 py-2 rounded bg-slate-800 border border-slate-700 text-xs text-slate-200"
                      />
                    </div>
                  )}
                  {recoveryActions.length === 0 ? (
                    <div className="text-xs text-slate-500">当前数据集暂无内置恢复动作</div>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {recoveryActions.map((item) => (
                        <button
                          key={item.id}
                          disabled={recovering}
                          onClick={() => void handleRunRecovery(item)}
                          className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 text-xs text-white flex items-center gap-1"
                        >
                          <Play size={12} />
                          {item.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="rounded border border-slate-800 bg-[#0d121f] p-4">
                <div className="text-sm font-semibold text-slate-100 mb-3">最近任务</div>
                {freshness.recent_jobs.length === 0 ? (
                  <div className="text-xs text-slate-500 flex items-center gap-2">
                    <AlertTriangle size={12} />
                    暂无关联任务记录
                  </div>
                ) : (
                  <div className="space-y-2">
                    {freshness.recent_jobs.map((job) => (
                      <div key={job.job_key} className="rounded border border-slate-800 bg-slate-900/60 px-3 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-xs text-slate-400">{job.job_key}</div>
                          <span className={`px-2 py-0.5 rounded border text-[11px] font-bold ${statusBadgeClass(job.status.includes('success') ? 'green' : job.status.includes('fail') ? 'red' : 'yellow')}`}>
                            {job.status}
                          </span>
                        </div>
                        <div className="text-xs text-slate-300 mt-1">{job.message || '-'}</div>
                        <div className="text-[11px] text-slate-500 mt-1">
                          progress: {Math.round(job.progress || 0)}% · created: {job.created_at || '-'}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="h-full flex items-center justify-center text-slate-500 text-sm">
              <CheckCircle2 size={16} className="mr-2 text-slate-600" />
              选择左侧数据集查看详情
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
