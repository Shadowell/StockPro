import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { MainLayout } from '../components/MainLayout';
import { useStore } from '../stores/useStore';
import { 
  getDailySectorStats, 
  syncTodayConceptSectors,
  backfillConceptHistory,
  DailySectorStats,
  SectorStatItem
} from '../api/client';
import { 
  Target,
  RefreshCw,
  Filter,
  Download,
  ChevronLeft,
  ChevronRight,
  Info,
  Loader2,
  AlertCircle,
  Database,
  History
} from 'lucide-react';
import clsx from 'clsx';

// 预定义的板块颜色 - 确保相同板块显示相同颜色
const SECTOR_COLOR_MAP: Record<string, string> = {};
const COLOR_PALETTE = [
  'bg-blue-600', 'bg-emerald-600', 'bg-purple-600', 'bg-red-600', 
  'bg-orange-600', 'bg-cyan-600', 'bg-pink-600', 'bg-indigo-600',
  'bg-teal-600', 'bg-amber-600', 'bg-rose-600', 'bg-lime-600',
  'bg-sky-600', 'bg-violet-600', 'bg-fuchsia-600', 'bg-yellow-600',
  'bg-blue-500', 'bg-emerald-500', 'bg-purple-500', 'bg-red-500',
  'bg-orange-500', 'bg-cyan-500', 'bg-pink-500', 'bg-indigo-500',
];

// 基于板块名称生成固定颜色（确保相同板块永远是同一颜色）
const getSectorColor = (sectorName: string): string => {
  if (!sectorName) return 'bg-slate-600';
  
  // 如果已经分配过颜色，直接返回
  if (SECTOR_COLOR_MAP[sectorName]) {
    return SECTOR_COLOR_MAP[sectorName];
  }
  
  // 基于字符串hash生成固定颜色
  let hash = 0;
  for (let i = 0; i < sectorName.length; i++) {
    hash = ((hash << 5) - hash) + sectorName.charCodeAt(i);
    hash = hash & hash;
  }
  
  const color = COLOR_PALETTE[Math.abs(hash) % COLOR_PALETTE.length];
  SECTOR_COLOR_MAP[sectorName] = color;
  
  return color;
};

// 格式化日期显示
const formatDate = (dateStr: string): string => {
  if (!dateStr) return '';
  // 格式: YYYY-MM-DD -> MM-DD
  if (dateStr.includes('-')) {
    const parts = dateStr.split('-');
    return `${parts[1]}-${parts[2]}`;
  }
  // 格式: YYYYMMDD -> MM-DD
  if (dateStr.length === 8) {
    return `${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`;
  }
  return dateStr;
};

// 获取星期几
const getWeekday = (dateStr: string): string => {
  if (!dateStr) return '';
  try {
    const date = new Date(dateStr);
    const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
    return weekdays[date.getDay()];
  } catch {
    return '';
  }
};

export const MarketPulse: React.FC = () => {
  const { language } = useStore();
  
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [sectorStats, setSectorStats] = useState<DailySectorStats[]>([]);
  
  // 筛选条件
  const [minChangePct, setMinChangePct] = useState(3.0);
  const [days, setDays] = useState(30);
  const [topN, setTopN] = useState(15);
  const [displayDays, setDisplayDays] = useState(10); // 一次显示的天数
  const [startIndex, setStartIndex] = useState(0);
  
  // 加载数据
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getDailySectorStats(days, minChangePct, topN);
      setSectorStats(data);
      setStartIndex(0);
    } catch (e: any) {
      console.error('加载复盘数据失败:', e);
      setError(e.response?.data?.detail || e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, [days, minChangePct, topN]);

  // 同步今日数据
  const handleSyncToday = async () => {
    setSyncing(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const result = await syncTodayConceptSectors();
      if (result.status === 'success') {
        setSuccessMsg(`今日数据同步成功，共 ${result.count} 个板块`);
        // 同步成功后重新加载数据
        await loadData();
      }
    } catch (e: any) {
      console.error('同步失败:', e);
      setError(e.response?.data?.detail || e.message || '同步失败');
    } finally {
      setSyncing(false);
    }
  };

  // 回填历史数据
  const handleBackfillHistory = async () => {
    if (!confirm(`确定要回填最近 ${days} 天的历史数据吗？\n\n此操作可能需要 5-15 分钟，请耐心等待。`)) {
      return;
    }
    
    setBackfilling(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const result = await backfillConceptHistory(days);
      if (result.status === 'success') {
        setSuccessMsg(`历史数据回填成功！共 ${result.days_filled} 天，耗时 ${result.duration_minutes} 分钟`);
        // 回填成功后重新加载数据
        await loadData();
      } else {
        setError(result.message || '回填失败');
      }
    } catch (e: any) {
      console.error('回填失败:', e);
      setError(e.response?.data?.detail || e.message || '回填失败，可能是请求超时');
    } finally {
      setBackfilling(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  // 计算显示的日期范围
  const visibleDays = useMemo(() => {
    return sectorStats.slice(startIndex, startIndex + displayDays);
  }, [sectorStats, startIndex, displayDays]);

  // 收集所有出现过的板块（用于统计）
  const allSectors = useMemo(() => {
    const sectorCount: Record<string, number> = {};
    for (const day of sectorStats) {
      for (const sector of day.sectors) {
        sectorCount[sector.name] = (sectorCount[sector.name] || 0) + 1;
      }
    }
    return Object.entries(sectorCount)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20);
  }, [sectorStats]);

  // 计算最大行数（显示天数中最多的板块数量）
  const maxRows = useMemo(() => {
    return Math.max(...visibleDays.map(d => d.sectors.length), 1);
  }, [visibleDays]);

  // 翻页
  const canGoPrev = startIndex > 0;
  const canGoNext = startIndex + displayDays < sectorStats.length;
  
  const goPrev = () => {
    if (canGoPrev) setStartIndex(Math.max(0, startIndex - displayDays));
  };
  
  const goNext = () => {
    if (canGoNext) setStartIndex(startIndex + displayDays);
  };

  // 导出数据
  const handleExport = () => {
    if (sectorStats.length === 0) return;
    
    // 构建CSV数据
    let csv = '日期,排名,板块名称,涨幅(%),领涨股\n';
    for (const day of sectorStats) {
      for (const sector of day.sectors) {
        csv += `${day.date},${sector.rank || ''},${sector.name},${sector.change_percent},${sector.leader_stock || ''}\n`;
      }
    }
    
    // 下载
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `板块轮动_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <MainLayout title={language === 'zh' ? '复盘中心' : 'Review Center'}>
      <div className="flex flex-col h-full gap-4">
        {/* 页面标题 */}
        <div className="bg-gradient-to-r from-blue-900/50 to-indigo-900/50 rounded-xl p-4 border border-blue-500/30">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-blue-500/20 rounded-lg">
                <Target className="text-blue-400" size={24} />
              </div>
              <div>
                <h2 className="text-lg font-bold text-white">{language === 'zh' ? '复盘中心' : 'Review Center'}</h2>
                <p className="text-sm text-slate-400">
                  每日热门概念板块轮动 · 相同板块用相同颜色标识
                </p>
              </div>
            </div>
            
            {/* 操作按钮 */}
            <div className="flex items-center gap-2">
              <button
                onClick={handleBackfillHistory}
                disabled={backfilling || syncing}
                className="px-3 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:bg-slate-700 rounded-lg text-sm text-white flex items-center gap-1.5 transition-colors"
                title="回填历史板块数据（需要几分钟）"
              >
                {backfilling ? <Loader2 size={16} className="animate-spin" /> : <History size={16} />}
                {backfilling ? '回填中...' : '回填历史'}
              </button>
              <button
                onClick={handleSyncToday}
                disabled={syncing || backfilling}
                className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 rounded-lg text-sm text-white flex items-center gap-1.5 transition-colors"
                title="同步今日板块数据"
              >
                {syncing ? <Loader2 size={16} className="animate-spin" /> : <Database size={16} />}
                同步今日
              </button>
              <button
                onClick={handleExport}
                disabled={sectorStats.length === 0}
                className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-600 rounded-lg text-sm text-white flex items-center gap-1.5 transition-colors"
              >
                <Download size={16} />
                导出
              </button>
              <button
                onClick={loadData}
                disabled={loading}
                className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 rounded-lg text-sm text-white flex items-center gap-1.5 transition-colors"
              >
                {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
                刷新
              </button>
            </div>
          </div>
        </div>

        {/* 筛选条件 */}
        <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-4">
          <div className="flex items-center gap-6 flex-wrap">
            <div className="flex items-center gap-2">
              <Filter size={16} className="text-slate-400" />
              <span className="text-sm text-slate-400">筛选:</span>
            </div>
            
            <div className="flex items-center gap-2">
              <label className="text-sm text-slate-400">最低涨幅:</label>
              <select
                value={minChangePct}
                onChange={(e) => setMinChangePct(parseFloat(e.target.value))}
                className="px-2 py-1 bg-slate-900 border border-slate-600 rounded text-white text-sm focus:border-blue-500 focus:outline-none"
              >
                {[1, 2, 3, 4, 5, 6, 7, 8].map(n => (
                  <option key={n} value={n}>{n}%以上</option>
                ))}
              </select>
            </div>
            
            <div className="flex items-center gap-2">
              <label className="text-sm text-slate-400">每日显示:</label>
              <select
                value={topN}
                onChange={(e) => setTopN(parseInt(e.target.value))}
                className="px-2 py-1 bg-slate-900 border border-slate-600 rounded text-white text-sm focus:border-blue-500 focus:outline-none"
              >
                {[10, 15, 20, 25, 30].map(n => (
                  <option key={n} value={n}>前{n}个板块</option>
                ))}
              </select>
            </div>
            
            <div className="flex items-center gap-2">
              <label className="text-sm text-slate-400">历史天数:</label>
              <select
                value={days}
                onChange={(e) => setDays(parseInt(e.target.value))}
                className="px-2 py-1 bg-slate-900 border border-slate-600 rounded text-white text-sm focus:border-blue-500 focus:outline-none"
              >
                {[15, 30, 45, 60, 90].map(n => (
                  <option key={n} value={n}>最近{n}天</option>
                ))}
              </select>
            </div>
            
            <button
              onClick={loadData}
              disabled={loading}
              className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 rounded text-sm text-white transition-colors"
            >
              应用筛选
            </button>
            
            {/* 翻页控制 */}
            <div className="flex items-center gap-2 ml-auto">
              <button
                onClick={goPrev}
                disabled={!canGoPrev}
                className="p-1.5 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-600 rounded transition-colors"
              >
                <ChevronLeft size={18} />
              </button>
              <span className="text-sm text-slate-400">
                {startIndex + 1}-{Math.min(startIndex + displayDays, sectorStats.length)} / {sectorStats.length}天
              </span>
              <button
                onClick={goNext}
                disabled={!canGoNext}
                className="p-1.5 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-600 rounded transition-colors"
              >
                <ChevronRight size={18} />
              </button>
            </div>
          </div>
        </div>

        {/* 成功提示 */}
        {successMsg && (
          <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-lg p-4 flex items-center gap-3">
            <Info className="text-emerald-400" size={20} />
            <span className="text-emerald-400">{successMsg}</span>
            <button 
              onClick={() => setSuccessMsg(null)}
              className="ml-auto text-emerald-400 hover:text-emerald-300"
            >
              ✕
            </button>
          </div>
        )}

        {/* 错误提示 */}
        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 flex items-center gap-3">
            <AlertCircle className="text-red-400" size={20} />
            <span className="text-red-400">{error}</span>
            <button 
              onClick={() => setError(null)}
              className="ml-auto text-red-400 hover:text-red-300"
            >
              ✕
            </button>
          </div>
        )}
        
        {/* 回填进度提示 */}
        {backfilling && (
          <div className="bg-purple-500/10 border border-purple-500/30 rounded-lg p-4 flex items-center gap-3">
            <Loader2 className="text-purple-400 animate-spin" size={20} />
            <span className="text-purple-400">
              正在回填历史数据，这可能需要 5-15 分钟，请勿关闭页面...
            </span>
          </div>
        )}

        {/* Excel风格板块轮动表格 */}
        <div className="flex-1 bg-slate-800/50 rounded-xl border border-slate-700 overflow-hidden">
          {loading && sectorStats.length === 0 ? (
            <div className="h-full flex items-center justify-center">
              <Loader2 size={32} className="animate-spin text-blue-400" />
            </div>
          ) : sectorStats.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-slate-500 py-12">
              <Info size={48} className="mb-4 opacity-50" />
              <p className="text-lg mb-2">暂无数据</p>
              <p className="text-sm mb-4">请点击"同步今日"按钮获取当日板块数据</p>
              <button
                onClick={handleSyncToday}
                disabled={syncing}
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-white flex items-center gap-2"
              >
                {syncing ? <Loader2 size={16} className="animate-spin" /> : <Database size={16} />}
                同步今日数据
              </button>
            </div>
          ) : (
            <div className="overflow-auto h-full">
              <table className="w-full text-sm border-collapse">
                {/* 表头 - 日期行 */}
                <thead className="bg-slate-900/80 sticky top-0 z-10">
                  <tr>
                    <th className="px-2 py-2 text-left text-slate-400 font-medium border-r border-slate-700 w-12 sticky left-0 bg-slate-900/80 z-20">
                      #
                    </th>
                    {visibleDays.map(day => (
                      <th 
                        key={day.date}
                        className="px-2 py-2 text-center text-white font-medium border-r border-slate-700 min-w-[110px]"
                      >
                        <div className="flex flex-col">
                          <span className="text-sm">{formatDate(day.date)}</span>
                          <span className="text-xs text-slate-500">{getWeekday(day.date)}</span>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                
                {/* 表体 - 每行对应一个排名位置 */}
                <tbody>
                  {Array.from({ length: maxRows }, (_, rowIndex) => (
                    <tr key={rowIndex} className="border-b border-slate-700/50 hover:bg-slate-700/20">
                      {/* 排名 */}
                      <td className="px-2 py-1 text-center text-slate-500 font-medium border-r border-slate-700 sticky left-0 bg-slate-800/90 z-10">
                        {rowIndex + 1}
                      </td>
                      
                      {/* 每天该位置的板块 */}
                      {visibleDays.map(day => {
                        const sector = day.sectors[rowIndex];
                        if (!sector) {
                          return (
                            <td 
                              key={`${day.date}-${rowIndex}`}
                              className="px-1 py-1 border-r border-slate-700/50"
                            >
                              <div className="text-slate-700 text-center">-</div>
                            </td>
                          );
                        }
                        
                        const bgColor = getSectorColor(sector.name);
                        return (
                          <td 
                            key={`${day.date}-${rowIndex}`}
                            className="px-1 py-1 border-r border-slate-700/50"
                          >
                            <div
                              className={clsx(
                                'px-2 py-1.5 rounded text-white text-xs transition-all hover:opacity-80 cursor-default',
                                bgColor
                              )}
                              title={`${sector.name}\n涨幅: ${sector.change_percent.toFixed(2)}%\n领涨: ${sector.leader_stock || '-'}`}
                            >
                              <div className="font-medium truncate text-center">
                                {sector.name.length > 6 ? sector.name.slice(0, 6) + '..' : sector.name}
                              </div>
                              <div className="text-[10px] opacity-80 text-center mt-0.5">
                                +{sector.change_percent.toFixed(1)}%
                              </div>
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* 底部统计：高频出现的板块 */}
        {allSectors.length > 0 && (
          <div className="bg-slate-800/30 rounded-lg p-3">
            <div className="flex items-start gap-3">
              <Info size={16} className="mt-0.5 text-slate-500 flex-shrink-0" />
              <div className="flex-1">
                <p className="text-xs text-slate-400 mb-2">
                  <strong>高频板块（近{days}天内出现次数最多）:</strong>
                </p>
                <div className="flex flex-wrap gap-2">
                  {allSectors.map(([name, count]) => (
                    <span
                      key={name}
                      className={clsx(
                        'px-2 py-1 rounded text-xs text-white',
                        getSectorColor(name)
                      )}
                    >
                      {name} ({count}次)
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 使用说明 */}
        <div className="bg-slate-800/30 rounded-lg p-3 text-xs text-slate-500">
          <div className="flex items-start gap-2">
            <Info size={14} className="mt-0.5 flex-shrink-0" />
            <div>
              <p>
                <strong className="text-slate-400">使用说明:</strong>
                {' '}每列代表一天，显示当天涨幅排名靠前的概念板块。相同板块用相同颜色标识，方便观察板块轮动规律。
                首次使用请先点击"同步今日"获取当天数据，之后系统会每天15:30自动同步。
              </p>
            </div>
          </div>
        </div>
      </div>
    </MainLayout>
  );
};
