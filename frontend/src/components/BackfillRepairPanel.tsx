import React, { useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, Loader2, RefreshCw, Wrench } from 'lucide-react';
import {
  backfillConceptHistory,
  cancelImportTask,
  getImportStatus,
  importHistoricalData,
  syncTodayConceptSectors,
} from '@/api/client';

type BackfillRowStatus = 'pending' | 'running' | 'success' | 'failed' | 'cancelled';

interface BackfillRow {
  date: string;
  status: BackfillRowStatus;
  message: string;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

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

const parseDate = (value: string): Date => new Date(`${value}T00:00:00`);

const formatDate = (date: Date): string => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const generateDateList = (fromDate: string, toDate: string, skipWeekend: boolean): string[] => {
  if (!fromDate || !toDate) return [];
  const start = parseDate(fromDate);
  const end = parseDate(toDate);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || start > end) return [];
  const out: string[] = [];
  const cursor = new Date(start);
  while (cursor <= end) {
    const day = cursor.getDay();
    if (!(skipWeekend && (day === 0 || day === 6))) {
      out.push(formatDate(cursor));
    }
    cursor.setDate(cursor.getDate() + 1);
  }
  return out;
};

export const BackfillRepairPanel: React.FC = () => {
  const today = useMemo(() => formatDate(new Date()), []);
  const [fromDate, setFromDate] = useState(today);
  const [toDate, setToDate] = useState(today);
  const [taskType, setTaskType] = useState<'history' | 'fundamentals' | 'all'>('all');
  const [skipWeekend, setSkipWeekend] = useState(true);
  const [dryRunOnly, setDryRunOnly] = useState(false);
  const [rows, setRows] = useState<BackfillRow[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pulseDays, setPulseDays] = useState(30);
  const [pulseRunning, setPulseRunning] = useState(false);
  const [pulseMsg, setPulseMsg] = useState<string | null>(null);
  const stopRef = useRef(false);

  const dateCandidates = useMemo(
    () => generateDateList(fromDate, toDate, skipWeekend),
    [fromDate, toDate, skipWeekend]
  );

  const waitImportFinished = async (): Promise<{ ok: boolean; message: string }> => {
    for (let i = 0; i < 300; i++) {
      if (stopRef.current) {
        return { ok: false, message: '已取消' };
      }
      await sleep(2000);
      const status = await getImportStatus();
      if (!status.is_running) {
        const msg = typeof status.message === 'string' ? status.message : '完成';
        const lower = msg.toLowerCase();
        return { ok: !lower.includes('error'), message: msg };
      }
    }
    return { ok: false, message: '等待任务完成超时' };
  };

  const runBackfill = async () => {
    setError(null);
    const dates = generateDateList(fromDate, toDate, skipWeekend);
    if (!dates.length) {
      setError('日期范围无效或无可执行交易日。');
      return;
    }

    const initialRows = dates.map((date) => ({ date, status: 'pending' as BackfillRowStatus, message: '待执行' }));
    setRows(initialRows);

    if (dryRunOnly) {
      setRows((prev) => prev.map((r) => ({ ...r, message: 'Dry-run：仅预览，不执行任务' })));
      return;
    }

    stopRef.current = false;
    setRunning(true);
    try {
      for (const date of dates) {
        if (stopRef.current) break;
        setRows((prev) =>
          prev.map((r) => (r.date === date ? { ...r, status: 'running', message: '提交任务中...' } : r))
        );
        try {
          await importHistoricalData({ date, task_type: taskType });
          const done = await waitImportFinished();
          setRows((prev) =>
            prev.map((r) =>
              r.date === date
                ? { ...r, status: done.ok ? 'success' : stopRef.current ? 'cancelled' : 'failed', message: done.message }
                : r
            )
          );
        } catch (err) {
          setRows((prev) =>
            prev.map((r) =>
              r.date === date
                ? { ...r, status: 'failed', message: getErrorMessage(err, '执行失败') }
                : r
            )
          );
        }
      }
      if (stopRef.current) {
        setRows((prev) => prev.map((r) => (r.status === 'pending' ? { ...r, status: 'cancelled', message: '已取消' } : r)));
      }
    } finally {
      setRunning(false);
      stopRef.current = false;
    }
  };

  const stopBackfill = async () => {
    stopRef.current = true;
    try {
      await cancelImportTask();
    } catch {
      // ignore
    }
  };

  const handleSyncTodayPulse = async () => {
    setPulseRunning(true);
    setPulseMsg(null);
    setError(null);
    try {
      const res = await syncTodayConceptSectors();
      setPulseMsg(`今日板块同步完成：${res.count ?? 0} 条`);
    } catch (err) {
      setError(getErrorMessage(err, '同步今日板块失败'));
    } finally {
      setPulseRunning(false);
    }
  };

  const handleBackfillPulseHistory = async () => {
    setPulseRunning(true);
    setPulseMsg(null);
    setError(null);
    try {
      const res = await backfillConceptHistory(pulseDays);
      if (res.status === 'success') {
        setPulseMsg(`历史回补完成：${res.days_filled ?? 0} 天，耗时 ${res.duration_minutes ?? 0} 分钟`);
      } else {
        setPulseMsg(res.message || '历史回补已执行');
      }
    } catch (err) {
      setError(getErrorMessage(err, '回补历史板块失败'));
    } finally {
      setPulseRunning(false);
    }
  };

  const countBy = (status: BackfillRowStatus) => rows.filter((r) => r.status === status).length;

  return (
    <div className="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wrench className="text-orange-400" size={18} />
          <span className="text-sm font-semibold text-gray-100">回补修复</span>
        </div>
      </div>

      <div className="p-4 space-y-4 overflow-auto flex-1">
        {error && (
          <div className="px-3 py-2 rounded border border-red-500/30 bg-red-500/10 text-red-400 text-sm flex items-center gap-2">
            <AlertCircle size={14} />
            {error}
          </div>
        )}

        <div className="rounded border border-slate-800 bg-[#0d121f] p-4 space-y-4">
          <div className="text-sm font-bold text-slate-200">行情数据按日回补</div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-3">
            <div>
              <label className="text-xs text-slate-500 block mb-1">开始日期</label>
              <input
                type="date"
                value={fromDate}
                onChange={(e) => setFromDate(e.target.value)}
                className="w-full px-2 py-1.5 rounded bg-slate-800 border border-slate-700 text-sm text-slate-200"
              />
            </div>
            <div>
              <label className="text-xs text-slate-500 block mb-1">结束日期</label>
              <input
                type="date"
                value={toDate}
                onChange={(e) => setToDate(e.target.value)}
                className="w-full px-2 py-1.5 rounded bg-slate-800 border border-slate-700 text-sm text-slate-200"
              />
            </div>
            <div>
              <label className="text-xs text-slate-500 block mb-1">任务类型</label>
              <select
                value={taskType}
                onChange={(e) => setTaskType(e.target.value as 'history' | 'fundamentals' | 'all')}
                className="w-full px-2 py-1.5 rounded bg-slate-800 border border-slate-700 text-sm text-slate-200"
              >
                <option value="all">全部任务</option>
                <option value="history">历史行情</option>
                <option value="fundamentals">基本面</option>
              </select>
            </div>
            <label className="flex items-end gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={skipWeekend}
                onChange={(e) => setSkipWeekend(e.target.checked)}
              />
              跳过周末
            </label>
            <label className="flex items-end gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={dryRunOnly}
                onChange={(e) => setDryRunOnly(e.target.checked)}
              />
              Dry-run 预览
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => { void runBackfill(); }}
              disabled={running}
              className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 text-sm text-white flex items-center gap-1"
            >
              {running ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              开始回补
            </button>
            <button
              onClick={() => { void stopBackfill(); }}
              disabled={!running}
              className="px-3 py-1.5 rounded bg-red-600 hover:bg-red-500 disabled:bg-slate-700 text-sm text-white"
            >
              停止
            </button>
            <span className="text-xs text-slate-500">
              预计执行日期 {dateCandidates.length} 天
            </span>
          </div>

          {rows.length > 0 && (
            <div className="text-xs text-slate-400 flex items-center gap-4">
              <span>成功 {countBy('success')}</span>
              <span>失败 {countBy('failed')}</span>
              <span>运行中 {countBy('running')}</span>
              <span>待执行 {countBy('pending')}</span>
            </div>
          )}
        </div>

        <div className="rounded border border-slate-800 bg-[#0d121f] p-4 space-y-3">
          <div className="text-sm font-bold text-slate-200">板块数据修复（复盘）</div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => { void handleSyncTodayPulse(); }}
              disabled={pulseRunning}
              className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 text-sm text-white"
            >
              同步今日板块
            </button>
            <input
              type="number"
              min={1}
              max={365}
              value={pulseDays}
              onChange={(e) => setPulseDays(Math.max(1, Number(e.target.value) || 30))}
              className="w-24 px-2 py-1.5 rounded bg-slate-800 border border-slate-700 text-sm text-slate-200"
            />
            <button
              onClick={() => { void handleBackfillPulseHistory(); }}
              disabled={pulseRunning}
              className="px-3 py-1.5 rounded bg-purple-600 hover:bg-purple-500 disabled:bg-slate-700 text-sm text-white flex items-center gap-1"
            >
              {pulseRunning ? <Loader2 size={14} className="animate-spin" /> : null}
              回补历史板块
            </button>
          </div>
          {pulseMsg && (
            <div className="text-xs text-green-400 flex items-center gap-1">
              <CheckCircle2 size={12} />
              {pulseMsg}
            </div>
          )}
        </div>

        {rows.length > 0 && (
          <div className="rounded border border-slate-800 bg-[#0d121f] overflow-hidden">
            <div className="px-3 py-2 border-b border-slate-800 text-xs font-bold tracking-wider text-slate-400 uppercase">
              回补执行明细
            </div>
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-xs">
                <thead className="bg-slate-900 sticky top-0 text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-left">日期</th>
                    <th className="px-3 py-2 text-left">状态</th>
                    <th className="px-3 py-2 text-left">消息</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.date} className="border-t border-slate-800/60">
                      <td className="px-3 py-2 text-slate-300">{row.date}</td>
                      <td className="px-3 py-2">
                        <span
                          className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                            row.status === 'success'
                              ? 'bg-green-500/20 text-green-400'
                              : row.status === 'failed'
                              ? 'bg-red-500/20 text-red-400'
                              : row.status === 'running'
                              ? 'bg-blue-500/20 text-blue-400'
                              : row.status === 'cancelled'
                              ? 'bg-slate-700 text-slate-300'
                              : 'bg-slate-800 text-slate-400'
                          }`}
                        >
                          {row.status}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-slate-400">{row.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
