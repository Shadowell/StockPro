import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, CheckCircle2, Clock3, Database, RefreshCw, Wrench } from 'lucide-react';
import { getDatabaseTables, executeSqlQuery, getImportStatus, getDataDevTasks, getMADataStats } from '@/api/client';

type HealthLevel = 'good' | 'warning' | 'danger' | 'unknown';

interface CoreMetrics {
  tableCount: number;
  totalRows: number;
  largestTable: string;
  importRunning: boolean;
  importMessage: string;
  dataDevEnabled: number;
  dataDevTotal: number;
  stockHistoryRows: number;
  stockHistoryLatestDate: string;
  stockHistoryDuplicates: number;
  maStockCount: number;
  maRecordCount: number;
}

const defaultMetrics: CoreMetrics = {
  tableCount: 0,
  totalRows: 0,
  largestTable: '-',
  importRunning: false,
  importMessage: '-',
  dataDevEnabled: 0,
  dataDevTotal: 0,
  stockHistoryRows: 0,
  stockHistoryLatestDate: '-',
  stockHistoryDuplicates: 0,
  maStockCount: 0,
  maRecordCount: 0,
};

const toNumber = (value: unknown): number => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const n = Number(value);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
};

const toStringValue = (value: unknown, fallback = '-'): string => {
  if (typeof value === 'string' && value.trim()) return value;
  return fallback;
};

export const DataOverviewPanel: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<CoreMetrics>(defaultMetrics);

  const runScalarQuery = useCallback(async (query: string, column: string): Promise<unknown> => {
    const result = await executeSqlQuery(query);
    if (!result.rows || result.rows.length === 0) return null;
    return result.rows[0][column];
  }, []);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [tables, importStatus, tasks, maStats] = await Promise.all([
        getDatabaseTables(),
        getImportStatus().catch(() => null),
        getDataDevTasks().catch(() => []),
        getMADataStats().catch(() => null),
      ]);

      const totalRows = tables.reduce((sum, item) => sum + toNumber(item.rowCount), 0);
      const largest = tables
        .slice()
        .sort((a, b) => toNumber(b.rowCount) - toNumber(a.rowCount))[0];

      let historyRows = 0;
      let historyLatest = '-';
      let historyDup = 0;

      try {
        historyRows = toNumber(await runScalarQuery('SELECT COUNT(*) AS total FROM stock_history', 'total'));
        historyLatest = toStringValue(await runScalarQuery('SELECT MAX(date) AS latest FROM stock_history', 'latest'));
        historyDup = toNumber(
          await runScalarQuery(
            "SELECT COUNT(*) - COUNT(DISTINCT symbol || '|' || date) AS duplicates FROM stock_history",
            'duplicates'
          )
        );
      } catch {
        // Ignore if stock_history is not available
      }

      setMetrics({
        tableCount: tables.length,
        totalRows,
        largestTable: largest ? `${largest.name} (${toNumber(largest.rowCount).toLocaleString()})` : '-',
        importRunning: Boolean(importStatus?.is_running),
        importMessage: toStringValue(importStatus?.message, '-'),
        dataDevEnabled: tasks.filter((t) => Boolean(t.enabled)).length,
        dataDevTotal: tasks.length,
        stockHistoryRows: historyRows,
        stockHistoryLatestDate: historyLatest,
        stockHistoryDuplicates: historyDup,
        maStockCount: maStats?.success ? toNumber(maStats.stats.stock_count) : 0,
        maRecordCount: maStats?.success ? toNumber(maStats.stats.record_count) : 0,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载总览失败');
    } finally {
      setLoading(false);
    }
  }, [runScalarQuery]);

  useEffect(() => {
    loadOverview();
  }, [loadOverview]);

  const healthLevel = useMemo<HealthLevel>(() => {
    if (metrics.stockHistoryRows === 0) return 'unknown';
    if (metrics.stockHistoryDuplicates > 0) return 'danger';
    if (metrics.importRunning) return 'warning';
    return 'good';
  }, [metrics.importRunning, metrics.stockHistoryDuplicates, metrics.stockHistoryRows]);

  const healthBadge = useMemo(() => {
    if (healthLevel === 'good') {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-1 rounded bg-green-500/20 text-green-400 text-xs font-bold">
          <CheckCircle2 size={12} />
          健康
        </span>
      );
    }
    if (healthLevel === 'warning') {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-1 rounded bg-amber-500/20 text-amber-400 text-xs font-bold">
          <AlertTriangle size={12} />
          处理中
        </span>
      );
    }
    if (healthLevel === 'danger') {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-1 rounded bg-red-500/20 text-red-400 text-xs font-bold">
          <AlertTriangle size={12} />
          异常
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-2 py-1 rounded bg-slate-700 text-slate-300 text-xs font-bold">
        <Clock3 size={12} />
        未知
      </span>
    );
  }, [healthLevel]);

  return (
    <div className="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="text-blue-400" size={18} />
          <span className="text-sm font-semibold text-gray-100">数据总览</span>
          {healthBadge}
        </div>
        <button
          onClick={() => { void loadOverview(); }}
          disabled={loading}
          className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 flex items-center gap-1"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>

      <div className="p-4 overflow-auto flex-1 space-y-4">
        {error && (
          <div className="px-3 py-2 rounded border border-red-500/30 bg-red-500/10 text-red-400 text-sm">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          <div className="rounded-lg border border-slate-800 bg-[#0d121f] p-4">
            <div className="text-xs text-slate-500 mb-1">数据表数量</div>
            <div className="text-2xl font-black text-white">{metrics.tableCount}</div>
            <div className="text-xs text-slate-500 mt-1">总行数 {metrics.totalRows.toLocaleString()}</div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-[#0d121f] p-4">
            <div className="text-xs text-slate-500 mb-1">最大数据表</div>
            <div className="text-sm font-bold text-slate-200">{metrics.largestTable}</div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-[#0d121f] p-4">
            <div className="text-xs text-slate-500 mb-1">导入任务状态</div>
            <div className={`text-sm font-bold ${metrics.importRunning ? 'text-amber-400' : 'text-green-400'}`}>
              {metrics.importRunning ? '运行中' : '空闲'}
            </div>
            <div className="text-xs text-slate-500 mt-1 line-clamp-2">{metrics.importMessage}</div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-[#0d121f] p-4">
            <div className="text-xs text-slate-500 mb-1">数据开发任务</div>
            <div className="text-2xl font-black text-white">{metrics.dataDevEnabled}/{metrics.dataDevTotal}</div>
            <div className="text-xs text-slate-500 mt-1">启用 / 总数</div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded-lg border border-slate-800 bg-[#0d121f] p-4">
            <div className="flex items-center gap-2 mb-3">
              <Database size={14} className="text-blue-400" />
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">行情核心数据</span>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-slate-500">stock_history 行数</span>
                <span className="font-semibold text-slate-200">{metrics.stockHistoryRows.toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">最新交易日</span>
                <span className="font-semibold text-slate-200">{metrics.stockHistoryLatestDate}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">重复主键行</span>
                <span className={`font-semibold ${metrics.stockHistoryDuplicates > 0 ? 'text-red-400' : 'text-green-400'}`}>
                  {metrics.stockHistoryDuplicates}
                </span>
              </div>
            </div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-[#0d121f] p-4">
            <div className="flex items-center gap-2 mb-3">
              <Wrench size={14} className="text-emerald-400" />
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">衍生数据</span>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-slate-500">MA覆盖股票数</span>
                <span className="font-semibold text-slate-200">{metrics.maStockCount.toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">MA记录总数</span>
                <span className="font-semibold text-slate-200">{metrics.maRecordCount.toLocaleString()}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
