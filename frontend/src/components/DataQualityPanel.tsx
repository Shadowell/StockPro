import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw, ShieldAlert, ShieldCheck } from 'lucide-react';
import { DataHubQualityReport, getDataHubQualityReport, runDataHubQuality } from '@/api/client';

type CheckStatus = 'green' | 'yellow' | 'red';

interface CheckItem {
  id: string;
  title: string;
  status: CheckStatus;
  detail: string;
}

export const DataQualityPanel: React.FC = () => {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<DataHubQualityReport | null>(null);

  const loadLatestReport = useCallback(async () => {
    try {
      const latest = await getDataHubQualityReport();
      setReport(latest);
    } catch {
      // ignore initial load errors
    }
  }, []);

  useEffect(() => {
    void loadLatestReport();
  }, [loadLatestReport]);

  const runChecks = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const next = await runDataHubQuality(['stock_history', 'stock_fundamentals', 'daily_concept_sectors']);
      setReport(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : '执行质量检查失败');
    } finally {
      setRunning(false);
    }
  }, []);

  const checks: CheckItem[] = useMemo(
    () =>
      (report?.checks || []).map((item) => ({
        id: item.dataset_id,
        title: item.title,
        status: item.status,
        detail: item.detail,
      })),
    [report]
  );

  const summary = useMemo(() => {
    const green = checks.filter((c) => c.status === 'green').length;
    const yellow = checks.filter((c) => c.status === 'yellow').length;
    const red = checks.filter((c) => c.status === 'red').length;
    return { green, yellow, red, total: checks.length };
  }, [checks]);

  const statusStyle = (status: CheckStatus): string => {
    if (status === 'green') return 'bg-green-500/15 text-green-400 border-green-500/20';
    if (status === 'yellow') return 'bg-amber-500/15 text-amber-400 border-amber-500/20';
    return 'bg-red-500/15 text-red-400 border-red-500/20';
  };

  const statusLabel = (status: CheckStatus): string => {
    if (status === 'green') return '绿色';
    if (status === 'yellow') return '黄色';
    return '红色';
  };

  return (
    <div className="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck className="text-emerald-400" size={18} />
          <span className="text-sm font-semibold text-gray-100">质量治理报告</span>
          {report?.report_key && (
            <span className="text-[11px] px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
              {report.report_key}
            </span>
          )}
        </div>
        <button
          onClick={() => {
            void runChecks();
          }}
          disabled={running}
          className="px-3 py-1.5 rounded bg-emerald-700 hover:bg-emerald-600 text-xs text-white flex items-center gap-1"
        >
          <RefreshCw size={12} className={running ? 'animate-spin' : ''} />
          运行检查
        </button>
      </div>

      <div className="p-4 space-y-4 overflow-auto">
        {error && (
          <div className="px-3 py-2 rounded border border-red-500/30 bg-red-500/10 text-red-400 text-sm">
            {error}
          </div>
        )}

        {report?.created_at && (
          <div className="text-xs text-slate-500">报告生成时间：{report.created_at}</div>
        )}

        {checks.length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="rounded border border-slate-800 bg-[#0d121f] p-3">
              <div className="text-xs text-slate-500">总项</div>
              <div className="text-xl font-black text-white">{summary.total}</div>
            </div>
            <div className="rounded border border-slate-800 bg-[#0d121f] p-3">
              <div className="text-xs text-slate-500">绿色</div>
              <div className="text-xl font-black text-green-400">{summary.green}</div>
            </div>
            <div className="rounded border border-slate-800 bg-[#0d121f] p-3">
              <div className="text-xs text-slate-500">黄色</div>
              <div className="text-xl font-black text-amber-400">{summary.yellow}</div>
            </div>
            <div className="rounded border border-slate-800 bg-[#0d121f] p-3">
              <div className="text-xs text-slate-500">红色</div>
              <div className="text-xl font-black text-red-400">{summary.red}</div>
            </div>
          </div>
        )}

        {report?.rule_templates && report.rule_templates.length > 0 && (
          <div className="rounded border border-slate-800 bg-[#0d121f] p-4">
            <div className="text-sm font-semibold text-slate-100 mb-2">规则模板</div>
            <div className="flex flex-wrap gap-2">
              {report.rule_templates.map((rule) => (
                <span key={rule.id} className="px-2 py-1 rounded bg-slate-900/60 border border-slate-800 text-xs text-slate-300">
                  {rule.name} · {rule.severity}
                </span>
              ))}
            </div>
          </div>
        )}

        {checks.length === 0 ? (
          <div className="rounded border border-slate-800 bg-[#0d121f] p-6 text-center text-slate-500">
            点击“运行检查”生成质量治理报告
          </div>
        ) : (
          <div className="space-y-3">
            {checks.map((item) => (
              <div key={item.id} className="rounded border border-slate-800 bg-[#0d121f] p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2">
                    {item.status === 'red' ? (
                      <ShieldAlert size={14} className="text-red-400" />
                    ) : item.status === 'yellow' ? (
                      <AlertTriangle size={14} className="text-amber-400" />
                    ) : (
                      <CheckCircle2 size={14} className="text-green-400" />
                    )}
                    <span className="text-sm font-semibold text-slate-100">{item.title}</span>
                  </div>
                  <span className={`px-2 py-0.5 rounded border text-xs font-bold ${statusStyle(item.status)}`}>
                    {statusLabel(item.status)}
                  </span>
                </div>
                <div className="mt-2 text-xs text-slate-400">{item.detail}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
