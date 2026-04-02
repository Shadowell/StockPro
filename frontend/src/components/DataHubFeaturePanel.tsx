import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, RefreshCw, Search, FlaskConical, Database } from 'lucide-react';
import { getDataHubFactorFeatures, getDataHubScreenerFeatures } from '@/api/client';

export const DataHubFeaturePanel: React.FC = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [screener, setScreener] = useState<{ count: number; snapshot: string | null } | null>(null);
  const [factors, setFactors] = useState<{
    factor_count: number;
    data_count: number;
    latest_date: string | null;
    snapshot: string | null;
  } | null>(null);

  const loadSummary = async () => {
    setLoading(true);
    setError(null);
    try {
      const [screenerResp, factorResp] = await Promise.all([
        getDataHubScreenerFeatures({ limit: 20 }),
        getDataHubFactorFeatures(),
      ]);
      setScreener({
        count: screenerResp.total_found || 0,
        snapshot: screenerResp.snapshot?.as_of || null,
      });
      setFactors({
        factor_count: factorResp.stats?.factor_count || 0,
        data_count: factorResp.stats?.data_count || 0,
        latest_date: factorResp.stats?.latest_date || null,
        snapshot: factorResp.snapshot?.as_of || null,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载特征服务摘要失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSummary();
  }, []);

  return (
    <div className="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Database className="text-cyan-400" size={18} />
          <span className="text-sm font-semibold text-gray-100">特征服务</span>
        </div>
        <button
          onClick={() => void loadSummary()}
          disabled={loading}
          className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 flex items-center gap-1"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>

      <div className="p-4 overflow-auto space-y-4">
        {error && (
          <div className="px-3 py-2 rounded border border-red-500/30 bg-red-500/10 text-red-400 text-sm">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded border border-slate-800 bg-[#0d121f] p-4">
            <div className="flex items-center gap-2 mb-2">
              <Search size={14} className="text-blue-400" />
              <span className="text-sm font-semibold text-slate-100">选股特征输出</span>
            </div>
            <div className="text-xs text-slate-500">快照日期</div>
            <div className="text-lg font-bold text-white">{screener?.snapshot || '-'}</div>
            <div className="text-xs text-slate-500 mt-2">当前命中候选</div>
            <div className="text-lg font-bold text-cyan-400">{screener?.count ?? 0}</div>
            <button
              onClick={() => navigate('/screener')}
              className="mt-4 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-xs text-white flex items-center gap-1"
            >
              打开智能选股
              <ArrowRight size={12} />
            </button>
          </div>

          <div className="rounded border border-slate-800 bg-[#0d121f] p-4">
            <div className="flex items-center gap-2 mb-2">
              <FlaskConical size={14} className="text-purple-400" />
              <span className="text-sm font-semibold text-slate-100">因子特征输出</span>
            </div>
            <div className="text-xs text-slate-500">快照日期</div>
            <div className="text-lg font-bold text-white">{factors?.snapshot || factors?.latest_date || '-'}</div>
            <div className="grid grid-cols-2 gap-2 mt-3">
              <div className="rounded bg-slate-900/60 p-2 border border-slate-800">
                <div className="text-xs text-slate-500">因子数量</div>
                <div className="text-sm font-semibold text-slate-200">{factors?.factor_count ?? 0}</div>
              </div>
              <div className="rounded bg-slate-900/60 p-2 border border-slate-800">
                <div className="text-xs text-slate-500">数据记录</div>
                <div className="text-sm font-semibold text-slate-200">{(factors?.data_count ?? 0).toLocaleString()}</div>
              </div>
            </div>
            <button
              onClick={() => navigate('/factors')}
              className="mt-4 px-3 py-1.5 rounded bg-purple-600 hover:bg-purple-500 text-xs text-white flex items-center gap-1"
            >
              打开因子库
              <ArrowRight size={12} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
