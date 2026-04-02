import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { MainLayout } from '../components/MainLayout';
import { useStore } from '../stores/useStore';
import { 
  getDailySectorStats, 
  getLianbanHistory,
  getDataHubDatasets,
  syncTodayConceptSectors,
  backfillConceptHistory,
  listReplayNotes,
  getReplayNote,
  saveReplayNote,
  DailySectorStats,
  LianbanHistoryDay,
  DataHubDataset,
  ReplayNote
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
  History,
  Flame
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

type PulseTemplate = {
  id: string;
  label: string;
  mode: 'sector' | 'lianban';
  params: {
    days: number;
    minChangePct?: number;
    topN?: number;
    minLianbanLevel?: number;
  };
};

const PULSE_TEMPLATES: PulseTemplate[] = [
  { id: 'sector_core', label: '板块主线', mode: 'sector', params: { days: 20, minChangePct: 3, topN: 12 } },
  { id: 'sector_wide', label: '板块扩散', mode: 'sector', params: { days: 45, minChangePct: 2, topN: 20 } },
  { id: 'lianban_core', label: '连板核心', mode: 'lianban', params: { days: 20, minLianbanLevel: 3 } },
  { id: 'lianban_dragon', label: '龙头接力', mode: 'lianban', params: { days: 45, minLianbanLevel: 4 } },
];

export const MarketPulse: React.FC = () => {
  const { language } = useStore();
  const [viewMode, setViewMode] = useState<'sector' | 'lianban'>('sector');
  
  const [loading, setLoading] = useState(false);
  const [lianbanLoading, setLianbanLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [sectorStats, setSectorStats] = useState<DailySectorStats[]>([]);
  const [lianbanHistory, setLianbanHistory] = useState<LianbanHistoryDay[]>([]);
  const [freshnessItems, setFreshnessItems] = useState<DataHubDataset[]>([]);
  const [selectedSector, setSelectedSector] = useState<string | null>(null);
  const [selectedLianbanStock, setSelectedLianbanStock] = useState<string | null>(null);
  const [activeTemplateId, setActiveTemplateId] = useState<string | null>(null);
  const [replayNoteDate, setReplayNoteDate] = useState('');
  const [replayNotes, setReplayNotes] = useState<ReplayNote[]>([]);
  const [replayNotesLoading, setReplayNotesLoading] = useState(false);
  const [replaySaving, setReplaySaving] = useState(false);
  const [replayDraft, setReplayDraft] = useState({
    headline: '',
    mainLine: '',
    coreTargets: '',
    riskAlert: '',
    actionPlan: '',
  });
  
  // 筛选条件
  const [minChangePct, setMinChangePct] = useState(3.0);
  const [minLianbanLevel, setMinLianbanLevel] = useState(2);
  const [days, setDays] = useState(30);
  const [topN, setTopN] = useState(15);
  const [displayDays] = useState(10); // 一次显示的天数
  const [startIndex, setStartIndex] = useState(0);
  
  // 加载数据
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getDailySectorStats(days, minChangePct, topN);
      setSectorStats(data);
      setStartIndex(0);
      if (selectedSector && !data.some((d) => d.sectors.some((s) => s.name === selectedSector))) {
        setSelectedSector(null);
      }
    } catch (e: unknown) {
      console.error('加载复盘数据失败:', e);
      setError(getErrorMessage(e, '加载失败'));
    } finally {
      setLoading(false);
    }
  }, [days, minChangePct, topN, selectedSector]);

  const loadLianban = useCallback(async () => {
    setLianbanLoading(true);
    setError(null);
    try {
      const data = await getLianbanHistory(days, minLianbanLevel);
      setLianbanHistory(data);
      setStartIndex(0);
      if (selectedLianbanStock && !data.some((d) => d.stocks.some((s) => s.code === selectedLianbanStock))) {
        setSelectedLianbanStock(null);
      }
    } catch (e: unknown) {
      console.error('加载连板历史失败:', e);
      setError(getErrorMessage(e, '加载连板历史失败'));
    } finally {
      setLianbanLoading(false);
    }
  }, [days, minLianbanLevel, selectedLianbanStock]);

  const loadFreshness = useCallback(async () => {
    try {
      const datasets = await getDataHubDatasets();
      const ids = new Set(['daily_concept_sectors', 'lianban_ladder_history']);
      setFreshnessItems(datasets.filter((item) => ids.has(item.id)));
    } catch {
      setFreshnessItems([]);
    }
  }, []);

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
    } catch (e: unknown) {
      console.error('同步失败:', e);
      setError(getErrorMessage(e, '同步失败'));
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
    } catch (e: unknown) {
      console.error('回填失败:', e);
      setError(getErrorMessage(e, '回填失败，可能是请求超时'));
    } finally {
      setBackfilling(false);
    }
  };

  useEffect(() => {
    if (viewMode === 'sector') {
      void loadData();
    } else {
      void loadLianban();
    }
  }, [viewMode, loadData, loadLianban]);

  useEffect(() => {
    void loadFreshness();
  }, [loadFreshness]);

  // 计算显示的日期范围
  const visibleDays = useMemo(() => {
    return sectorStats.slice(startIndex, startIndex + displayDays);
  }, [sectorStats, startIndex, displayDays]);

  const visibleLianbanDays = useMemo(() => {
    return lianbanHistory.slice(startIndex, startIndex + displayDays);
  }, [lianbanHistory, startIndex, displayDays]);

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

  const allLianbanStocks = useMemo(() => {
    const stockCount: Record<string, { name: string; count: number; maxLevel: number }> = {};
    for (const day of lianbanHistory) {
      for (const stock of day.stocks) {
        const key = stock.code || stock.name;
        if (!key) continue;
        const current = stockCount[key] || { name: stock.name || stock.code, count: 0, maxLevel: 0 };
        current.count += 1;
        current.maxLevel = Math.max(current.maxLevel, stock.level || 0);
        stockCount[key] = current;
      }
    }
    return Object.entries(stockCount)
      .sort((a, b) => b[1].count - a[1].count || b[1].maxLevel - a[1].maxLevel)
      .slice(0, 20);
  }, [lianbanHistory]);

  const selectedSectorSummary = useMemo(() => {
    if (!selectedSector) return null;
    const points: Array<{ date: string; change: number; rank?: number }> = [];
    sectorStats.forEach((day) => {
      const hit = day.sectors.find((s) => s.name === selectedSector);
      if (hit) {
        points.push({ date: day.date, change: hit.change_percent, rank: hit.rank });
      }
    });
    if (points.length === 0) return null;
    const avg = points.reduce((sum, p) => sum + p.change, 0) / points.length;
    const max = points.reduce((m, p) => Math.max(m, p.change), -Infinity);
    const latest = points[0];
    return {
      count: points.length,
      avgChange: avg,
      maxChange: max,
      latestDate: latest.date,
      latestChange: latest.change,
      bestRank: points.reduce((m, p) => Math.min(m, p.rank ?? 999), 999),
    };
  }, [selectedSector, sectorStats]);

  const selectedSectorTimeline = useMemo(() => {
    if (!selectedSector) return [];
    return sectorStats
      .map((day) => {
        const hit = day.sectors.find((s) => s.name === selectedSector);
        if (!hit) return null;
        return {
          date: day.date,
          change: hit.change_percent,
          rank: hit.rank ?? null,
          leader: hit.leader_stock || '-',
        };
      })
      .filter((item): item is { date: string; change: number; rank: number | null; leader: string } => item !== null);
  }, [selectedSector, sectorStats]);

  const selectedSectorLatestStreak = useMemo(() => {
    if (!selectedSector) return 0;
    let streak = 0;
    for (const day of sectorStats) {
      const has = day.sectors.some((s) => s.name === selectedSector);
      if (!has) break;
      streak += 1;
    }
    return streak;
  }, [selectedSector, sectorStats]);

  const selectedLianbanSummary = useMemo(() => {
    if (!selectedLianbanStock) return null;
    const points: Array<{ date: string; level: number; change: number }> = [];
    lianbanHistory.forEach((day) => {
      const hit = day.stocks.find((s) => s.code === selectedLianbanStock);
      if (hit) {
        points.push({ date: day.date, level: hit.level, change: hit.change_percent });
      }
    });
    if (points.length === 0) return null;
    return {
      count: points.length,
      maxLevel: points.reduce((m, p) => Math.max(m, p.level), 0),
      avgChange: points.reduce((sum, p) => sum + p.change, 0) / points.length,
      latestDate: points[0].date,
      latestLevel: points[0].level,
      latestChange: points[0].change,
    };
  }, [selectedLianbanStock, lianbanHistory]);

  const selectedLianbanTimeline = useMemo(() => {
    if (!selectedLianbanStock) return [];
    return lianbanHistory
      .map((day) => {
        const hit = day.stocks.find((s) => s.code === selectedLianbanStock);
        if (!hit) return null;
        return {
          date: day.date,
          name: hit.name,
          level: hit.level,
          change: hit.change_percent,
          price: hit.price,
          durationDays: hit.duration_days ?? null,
          reason: hit.reason || '-',
        };
      })
      .filter(
        (item): item is {
          date: string;
          name: string;
          level: number;
          change: number;
          price: number;
          durationDays: number | null;
          reason: string;
        } => item !== null
      );
  }, [selectedLianbanStock, lianbanHistory]);

  const selectedLianbanLatestStreak = useMemo(() => {
    if (!selectedLianbanStock) return 0;
    let streak = 0;
    for (const day of lianbanHistory) {
      const has = day.stocks.some((s) => s.code === selectedLianbanStock);
      if (!has) break;
      streak += 1;
    }
    return streak;
  }, [selectedLianbanStock, lianbanHistory]);

  const selectedLianbanDisplayName = useMemo(() => {
    if (!selectedLianbanStock) return null;
    const hit = lianbanHistory
      .flatMap((day) => day.stocks)
      .find((stock) => stock.code === selectedLianbanStock);
    return hit?.name || null;
  }, [selectedLianbanStock, lianbanHistory]);

  const replayConclusion = useMemo(() => {
    const freshnessRisk = freshnessItems.find((item) => item.freshness_status !== 'green');
    if (viewMode === 'sector') {
      const topSectors = allSectors.slice(0, 3);
      const latestDay = sectorStats[0];
      const leader = latestDay?.sectors[0];
      return {
        title: '今日复盘结论',
        bullets: [
          topSectors.length
            ? `主线方向: ${topSectors.map(([name, count]) => `${name}(${count}次)`).join(' / ')}`
            : '主线方向: 暂无足够历史样本',
          leader
            ? `当日强度: ${latestDay.date} 领涨板块为 ${leader.name}（${leader.change_percent.toFixed(2)}%）`
            : '当日强度: 当天板块数据为空',
          freshnessRisk
            ? `风险提示: ${freshnessRisk.name} 数据新鲜度为 ${freshnessRisk.freshness_status.toUpperCase()}，请先处理数据任务`
            : '风险提示: 数据新鲜度正常，建议结合成交额与涨停结构复核',
        ],
      };
    }

    const topStocks = allLianbanStocks.slice(0, 3);
    const latestDay = lianbanHistory[0];
    const highest = latestDay?.stocks[0];
    return {
      title: '今日复盘结论',
      bullets: [
        topStocks.length
          ? `核心标的: ${topStocks.map(([, item]) => `${item.name}(最高${item.maxLevel}板)`).join(' / ')}`
          : '核心标的: 暂无足够历史样本',
        highest
          ? `连板高度: ${latestDay.date} 最高为 ${highest.name} ${highest.level}板（${highest.change_percent.toFixed(2)}%）`
          : '连板高度: 当天连板数据为空',
        freshnessRisk
          ? `风险提示: ${freshnessRisk.name} 数据新鲜度为 ${freshnessRisk.freshness_status.toUpperCase()}，结论可能滞后`
          : '风险提示: 数据新鲜度正常，建议关注断板率与次日承接',
      ],
    };
  }, [viewMode, freshnessItems, allSectors, sectorStats, allLianbanStocks, lianbanHistory]);

  const availableReplayDates = useMemo(() => {
    if (viewMode === 'sector') return sectorStats.map((item) => item.date);
    return lianbanHistory.map((item) => item.date);
  }, [viewMode, sectorStats, lianbanHistory]);

  const draftFromConclusion = useMemo(() => {
    const line1 = replayConclusion.bullets[0] || '';
    const line2 = replayConclusion.bullets[1] || '';
    const line3 = replayConclusion.bullets[2] || '';
    return {
      headline: viewMode === 'sector' ? '板块轮动复盘' : '连板情绪复盘',
      mainLine: line1.replace(/^[^:：]+[:：]\s*/, ''),
      coreTargets: line2.replace(/^[^:：]+[:：]\s*/, ''),
      riskAlert: line3.replace(/^[^:：]+[:：]\s*/, ''),
      actionPlan: viewMode === 'sector' ? '聚焦主线板块龙头分歧转一致机会' : '聚焦高标断板反馈与低位补涨节奏',
    };
  }, [replayConclusion.bullets, viewMode]);

  const loadReplayNoteList = useCallback(async () => {
    setReplayNotesLoading(true);
    try {
      const items = await listReplayNotes(120);
      setReplayNotes(items);
    } catch {
      setReplayNotes([]);
    } finally {
      setReplayNotesLoading(false);
    }
  }, []);

  const loadReplayNoteForDate = useCallback(
    async (date: string) => {
      if (!date) return;
      try {
        const item = await getReplayNote(date);
        if (item) {
          setReplayDraft({
            headline: item.headline || '',
            mainLine: item.main_line || '',
            coreTargets: item.core_targets || '',
            riskAlert: item.risk_alert || '',
            actionPlan: item.action_plan || '',
          });
          if (item.template_id) setActiveTemplateId(item.template_id);
          return;
        }
      } catch {
        // ignore and fallback
      }
      setReplayDraft(draftFromConclusion);
    },
    [draftFromConclusion]
  );

  // 计算最大行数（显示天数中最多的板块数量）
  const maxRows = useMemo(() => {
    return Math.max(...visibleDays.map(d => d.sectors.length), 1);
  }, [visibleDays]);

  const maxLianbanRows = useMemo(() => {
    return Math.max(...visibleLianbanDays.map(d => d.stocks.length), 1);
  }, [visibleLianbanDays]);

  // 翻页
  const totalDays = viewMode === 'sector' ? sectorStats.length : lianbanHistory.length;
  const canGoPrev = startIndex > 0;
  const canGoNext = startIndex + displayDays < totalDays;
  
  const goPrev = () => {
    if (canGoPrev) setStartIndex(Math.max(0, startIndex - displayDays));
  };
  
  const goNext = () => {
    if (canGoNext) setStartIndex(startIndex + displayDays);
  };

  const handleApplyTemplate = (template: PulseTemplate) => {
    setActiveTemplateId(template.id);
    setViewMode(template.mode);
    setDays(template.params.days);
    if (template.mode === 'sector') {
      setMinChangePct(template.params.minChangePct ?? 3);
      setTopN(template.params.topN ?? 15);
    } else {
      setMinLianbanLevel(template.params.minLianbanLevel ?? 2);
    }
    setStartIndex(0);
  };

  const handleSaveReplayNote = async () => {
    if (!replayNoteDate) {
      setError('请选择复盘日期后再保存');
      return;
    }
    setReplaySaving(true);
    setError(null);
    try {
      await saveReplayNote({
        note_date: replayNoteDate,
        view_mode: viewMode,
        template_id: activeTemplateId,
        headline: replayDraft.headline.trim(),
        main_line: replayDraft.mainLine.trim(),
        core_targets: replayDraft.coreTargets.trim(),
        risk_alert: replayDraft.riskAlert.trim(),
        action_plan: replayDraft.actionPlan.trim(),
        extra: { generated_at: new Date().toISOString() },
      });
      setSuccessMsg(`复盘日志已保存: ${replayNoteDate}`);
      await loadReplayNoteList();
    } catch (e: unknown) {
      setError(getErrorMessage(e, '保存复盘日志失败'));
    } finally {
      setReplaySaving(false);
    }
  };

  // 导出数据
  const handleExport = () => {
    if (viewMode === 'sector') {
      if (sectorStats.length === 0) return;
      let csv = '日期,排名,板块名称,涨幅(%),领涨股\n';
      for (const day of sectorStats) {
        for (const sector of day.sectors) {
          csv += `${day.date},${sector.rank || ''},${sector.name},${sector.change_percent},${sector.leader_stock || ''}\n`;
        }
      }
      const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `板块轮动_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      return;
    }

    if (lianbanHistory.length === 0) return;
    let csv = '日期,代码,名称,连板数,涨幅(%),价格,持续天数,题材\n';
    for (const day of lianbanHistory) {
      for (const stock of day.stocks) {
        csv += `${day.date},${stock.code},${stock.name},${stock.level},${stock.change_percent},${stock.price},${stock.duration_days ?? ''},${stock.reason || ''}\n`;
      }
    }
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `连板历史_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  useEffect(() => {
    if (!availableReplayDates.length) return;
    if (!replayNoteDate || !availableReplayDates.includes(replayNoteDate)) {
      setReplayNoteDate(availableReplayDates[0]);
    }
  }, [availableReplayDates, replayNoteDate]);

  useEffect(() => {
    if (!replayNoteDate) return;
    void loadReplayNoteForDate(replayNoteDate);
  }, [replayNoteDate, loadReplayNoteForDate]);

  useEffect(() => {
    void loadReplayNoteList();
  }, [loadReplayNoteList]);

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
                  板块轮动 + 连板历史联合复盘
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
                disabled={viewMode === 'sector' ? sectorStats.length === 0 : lianbanHistory.length === 0}
                className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-600 rounded-lg text-sm text-white flex items-center gap-1.5 transition-colors"
              >
                <Download size={16} />
                导出当前视图
              </button>
              <button
                onClick={() => {
                  if (viewMode === 'sector') {
                    void loadData();
                  } else {
                    void loadLianban();
                  }
                  void loadFreshness();
                }}
                disabled={loading || lianbanLoading}
                className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 rounded-lg text-sm text-white flex items-center gap-1.5 transition-colors"
              >
                {(loading || lianbanLoading) ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
                刷新
              </button>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              onClick={() => {
                setViewMode('sector');
                setStartIndex(0);
              }}
              className={clsx(
                'px-3 py-1.5 rounded text-xs font-bold transition-colors',
                viewMode === 'sector' ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
              )}
            >
              板块轮动
            </button>
            <button
              onClick={() => {
                setViewMode('lianban');
                setStartIndex(0);
              }}
              className={clsx(
                'px-3 py-1.5 rounded text-xs font-bold transition-colors flex items-center gap-1',
                viewMode === 'lianban' ? 'bg-orange-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
              )}
            >
              <Flame size={12} />
              连板历史
            </button>

            {freshnessItems.map((item) => (
              <span
                key={item.id}
                className={clsx(
                  'px-2 py-1 rounded text-[11px] border',
                  item.freshness_status === 'green' && 'bg-green-500/15 text-green-300 border-green-500/30',
                  item.freshness_status === 'yellow' && 'bg-amber-500/15 text-amber-300 border-amber-500/30',
                  item.freshness_status === 'red' && 'bg-red-500/15 text-red-300 border-red-500/30'
                )}
                title={`${item.name} 最新快照: ${item.latest_snapshot || '-'}`}
              >
                {item.name}: {item.latest_snapshot || '-'}
              </span>
            ))}
          </div>
        </div>

        {/* 筛选条件 */}
        <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-4">
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <span className="text-xs text-slate-400">复盘模板:</span>
            {PULSE_TEMPLATES.map((tpl) => (
              <button
                key={tpl.id}
                onClick={() => handleApplyTemplate(tpl)}
                className={clsx(
                  'px-2.5 py-1 rounded text-xs transition-colors border',
                  viewMode === tpl.mode
                    ? 'bg-slate-700 border-slate-500 text-white hover:bg-slate-600'
                    : 'bg-slate-900 border-slate-700 text-slate-300 hover:bg-slate-800'
                )}
                title={`切换到${tpl.label}模板`}
              >
                {tpl.label}
              </button>
            ))}
          </div>

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
                disabled={viewMode !== 'sector'}
                className="px-2 py-1 bg-slate-900 border border-slate-600 rounded text-white text-sm focus:border-blue-500 focus:outline-none"
              >
                {[1, 2, 3, 4, 5, 6, 7, 8].map(n => (
                  <option key={n} value={n}>{n}%以上</option>
                ))}
              </select>
            </div>

            <div className="flex items-center gap-2">
              <label className="text-sm text-slate-400">最低连板:</label>
              <select
                value={minLianbanLevel}
                onChange={(e) => setMinLianbanLevel(parseInt(e.target.value))}
                disabled={viewMode !== 'lianban'}
                className="px-2 py-1 bg-slate-900 border border-slate-600 rounded text-white text-sm focus:border-blue-500 focus:outline-none"
              >
                {[2, 3, 4, 5, 6, 7].map(n => (
                  <option key={n} value={n}>{n}板以上</option>
                ))}
              </select>
            </div>
            
            <div className="flex items-center gap-2">
              <label className="text-sm text-slate-400">每日显示:</label>
              <select
                value={topN}
                onChange={(e) => setTopN(parseInt(e.target.value))}
                disabled={viewMode !== 'sector'}
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
              onClick={() => {
                if (viewMode === 'sector') {
                  void loadData();
                } else {
                  void loadLianban();
                }
              }}
              disabled={loading || lianbanLoading}
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
                {startIndex + 1}-{Math.min(startIndex + displayDays, totalDays)} / {totalDays}天
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
          {(viewMode === 'sector' ? loading && sectorStats.length === 0 : lianbanLoading && lianbanHistory.length === 0) ? (
            <div className="h-full flex items-center justify-center">
              <Loader2 size={32} className="animate-spin text-blue-400" />
            </div>
          ) : (viewMode === 'sector' ? sectorStats.length === 0 : lianbanHistory.length === 0) ? (
            <div className="h-full flex flex-col items-center justify-center text-slate-500 py-12">
              <Info size={48} className="mb-4 opacity-50" />
              <p className="text-lg mb-2">暂无数据</p>
              <p className="text-sm mb-4">
                {viewMode === 'sector' ? '请点击"同步今日"按钮获取当日板块数据' : '请先同步数据或降低连板筛选条件'}
              </p>
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
              {viewMode === 'sector' ? (
                <table className="w-full text-sm border-collapse">
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

                  <tbody>
                    {Array.from({ length: maxRows }, (_, rowIndex) => (
                      <tr key={rowIndex} className="border-b border-slate-700/50 hover:bg-slate-700/20">
                        <td className="px-2 py-1 text-center text-slate-500 font-medium border-r border-slate-700 sticky left-0 bg-slate-800/90 z-10">
                          {rowIndex + 1}
                        </td>

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
                          const isSelected = selectedSector === sector.name;
                          const hasSelected = Boolean(selectedSector);
                          return (
                            <td
                              key={`${day.date}-${rowIndex}`}
                              className="px-1 py-1 border-r border-slate-700/50"
                            >
                              <button
                                onClick={() => setSelectedSector((prev) => (prev === sector.name ? null : sector.name))}
                                className={clsx(
                                  'w-full px-2 py-1.5 rounded text-white text-xs transition-all hover:opacity-90',
                                  bgColor,
                                  isSelected && 'ring-2 ring-white/80 scale-[1.02]',
                                  hasSelected && !isSelected && 'opacity-45'
                                )}
                                title={`${sector.name}\n涨幅: ${sector.change_percent.toFixed(2)}%\n领涨: ${sector.leader_stock || '-'}`}
                              >
                                <div className="font-medium truncate text-center">
                                  {sector.name.length > 6 ? `${sector.name.slice(0, 6)}..` : sector.name}
                                </div>
                                <div className="text-[10px] opacity-80 text-center mt-0.5">
                                  +{sector.change_percent.toFixed(1)}%
                                </div>
                              </button>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <table className="w-full text-sm border-collapse">
                  <thead className="bg-slate-900/80 sticky top-0 z-10">
                    <tr>
                      <th className="px-2 py-2 text-left text-slate-400 font-medium border-r border-slate-700 w-12 sticky left-0 bg-slate-900/80 z-20">
                        #
                      </th>
                      {visibleLianbanDays.map(day => (
                        <th
                          key={day.date}
                          className="px-2 py-2 text-center text-white font-medium border-r border-slate-700 min-w-[130px]"
                        >
                          <div className="flex flex-col">
                            <span className="text-sm">{formatDate(day.date)}</span>
                            <span className="text-xs text-slate-500">{getWeekday(day.date)}</span>
                          </div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Array.from({ length: maxLianbanRows }, (_, rowIndex) => (
                      <tr key={rowIndex} className="border-b border-slate-700/50 hover:bg-slate-700/20">
                        <td className="px-2 py-1 text-center text-slate-500 font-medium border-r border-slate-700 sticky left-0 bg-slate-800/90 z-10">
                          {rowIndex + 1}
                        </td>
                        {visibleLianbanDays.map((day) => {
                          const stock = day.stocks[rowIndex];
                          if (!stock) {
                            return (
                              <td key={`${day.date}-${rowIndex}`} className="px-1 py-1 border-r border-slate-700/50">
                                <div className="text-slate-700 text-center">-</div>
                              </td>
                            );
                          }
                          const isSelected = selectedLianbanStock === stock.code;
                          const hasSelected = Boolean(selectedLianbanStock);
                          return (
                            <td key={`${day.date}-${rowIndex}`} className="px-1 py-1 border-r border-slate-700/50">
                              <button
                                onClick={() => setSelectedLianbanStock((prev) => (prev === stock.code ? null : stock.code))}
                                className={clsx(
                                  'w-full px-2 py-1.5 rounded text-xs transition-all border',
                                  stock.level >= 5 ? 'bg-red-600/80 border-red-400/40 text-white' : 'bg-orange-600/70 border-orange-400/40 text-white',
                                  isSelected && 'ring-2 ring-white/80 scale-[1.02]',
                                  hasSelected && !isSelected && 'opacity-45'
                                )}
                                title={`${stock.name}(${stock.code})\n连板: ${stock.level}\n涨幅: ${stock.change_percent?.toFixed(2)}%`}
                              >
                                <div className="font-semibold truncate text-center">{stock.name}</div>
                                <div className="text-[10px] opacity-90 mt-0.5 text-center">
                                  {stock.level}板 · {stock.change_percent >= 0 ? '+' : ''}{stock.change_percent.toFixed(1)}%
                                </div>
                              </button>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>

        {/* 底部统计 */}
        {viewMode === 'sector' && allSectors.length > 0 && (
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

        {viewMode === 'lianban' && allLianbanStocks.length > 0 && (
          <div className="bg-slate-800/30 rounded-lg p-3">
            <div className="flex items-start gap-3">
              <Info size={16} className="mt-0.5 text-slate-500 flex-shrink-0" />
              <div className="flex-1">
                <p className="text-xs text-slate-400 mb-2">
                  <strong>高频连板股（近{days}天）:</strong>
                </p>
                <div className="flex flex-wrap gap-2">
                  {allLianbanStocks.map(([key, item]) => (
                    <span
                      key={key}
                      className={clsx(
                        'px-2 py-1 rounded text-xs text-white border',
                        item.maxLevel >= 5 ? 'bg-red-600/70 border-red-400/40' : 'bg-orange-600/70 border-orange-400/40'
                      )}
                    >
                      {item.name}({item.count}次, 最高{item.maxLevel}板)
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {viewMode === 'sector' && selectedSectorSummary && selectedSector && (
          <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 text-xs text-blue-200">
            已选板块 <strong>{selectedSector}</strong>：
            {' '}出现 {selectedSectorSummary.count} 天，
            连续上榜 {selectedSectorLatestStreak} 天，
            平均涨幅 {selectedSectorSummary.avgChange.toFixed(2)}%，
            最高涨幅 {selectedSectorSummary.maxChange.toFixed(2)}%，
            最近 {selectedSectorSummary.latestDate} 涨幅 {selectedSectorSummary.latestChange.toFixed(2)}%，
            最好名次 #{selectedSectorSummary.bestRank}
          </div>
        )}

        {viewMode === 'lianban' && selectedLianbanSummary && selectedLianbanStock && (
          <div className="bg-orange-500/10 border border-orange-500/30 rounded-lg p-3 text-xs text-orange-200">
            已选个股 <strong>{selectedLianbanDisplayName || selectedLianbanStock}</strong>（{selectedLianbanStock}）：
            {' '}上榜 {selectedLianbanSummary.count} 天，
            连续上榜 {selectedLianbanLatestStreak} 天，
            最高连板 {selectedLianbanSummary.maxLevel}，
            平均涨幅 {selectedLianbanSummary.avgChange.toFixed(2)}%，
            最近 {selectedLianbanSummary.latestDate} 为 {selectedLianbanSummary.latestLevel} 板，
            涨幅 {selectedLianbanSummary.latestChange.toFixed(2)}%
          </div>
        )}

        {viewMode === 'sector' && selectedSector && selectedSectorTimeline.length > 0 && (
          <div className="bg-slate-800/40 border border-slate-700 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-slate-200">板块明细走势: {selectedSector}</h3>
              <span className="text-xs text-slate-400">最近 {selectedSectorTimeline.length} 次上榜记录</span>
            </div>
            <div className="overflow-auto">
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="text-slate-400 border-b border-slate-700">
                    <th className="py-1 text-left">日期</th>
                    <th className="py-1 text-left">涨幅</th>
                    <th className="py-1 text-left">排名</th>
                    <th className="py-1 text-left">领涨股</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedSectorTimeline.slice(0, 12).map((point) => (
                    <tr key={point.date} className="border-b border-slate-700/40 text-slate-200">
                      <td className="py-1">{point.date}</td>
                      <td className={clsx('py-1 font-semibold', point.change >= 0 ? 'text-emerald-300' : 'text-red-300')}>
                        {point.change >= 0 ? '+' : ''}{point.change.toFixed(2)}%
                      </td>
                      <td className="py-1">{point.rank ? `#${point.rank}` : '-'}</td>
                      <td className="py-1 text-slate-300">{point.leader}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {viewMode === 'lianban' && selectedLianbanStock && selectedLianbanTimeline.length > 0 && (
          <div className="bg-slate-800/40 border border-slate-700 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-slate-200">
                连板明细走势: {selectedLianbanDisplayName || selectedLianbanStock}
              </h3>
              <span className="text-xs text-slate-400">最近 {selectedLianbanTimeline.length} 次上榜记录</span>
            </div>
            <div className="overflow-auto">
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="text-slate-400 border-b border-slate-700">
                    <th className="py-1 text-left">日期</th>
                    <th className="py-1 text-left">连板</th>
                    <th className="py-1 text-left">涨幅</th>
                    <th className="py-1 text-left">价格</th>
                    <th className="py-1 text-left">持续天数</th>
                    <th className="py-1 text-left">题材</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedLianbanTimeline.slice(0, 12).map((point) => (
                    <tr key={point.date} className="border-b border-slate-700/40 text-slate-200">
                      <td className="py-1">{point.date}</td>
                      <td className="py-1 text-orange-300 font-semibold">{point.level}板</td>
                      <td className={clsx('py-1 font-semibold', point.change >= 0 ? 'text-emerald-300' : 'text-red-300')}>
                        {point.change >= 0 ? '+' : ''}{point.change.toFixed(2)}%
                      </td>
                      <td className="py-1">{point.price.toFixed(2)}</td>
                      <td className="py-1">{point.durationDays ?? '-'}</td>
                      <td className="py-1 text-slate-300 truncate max-w-[320px]" title={point.reason}>{point.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div className="bg-slate-800/40 border border-slate-700 rounded-lg p-3">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
            <h3 className="text-sm font-semibold text-slate-200">{replayConclusion.title}</h3>
            <div className="flex items-center gap-2">
              <label className="text-xs text-slate-400">日期</label>
              <select
                value={replayNoteDate}
                onChange={(e) => setReplayNoteDate(e.target.value)}
                className="px-2 py-1 bg-slate-900 border border-slate-600 rounded text-white text-xs focus:border-blue-500 focus:outline-none"
              >
                {availableReplayDates.map((date) => (
                  <option key={date} value={date}>{date}</option>
                ))}
              </select>
              <button
                onClick={() => setReplayDraft(draftFromConclusion)}
                className="px-2.5 py-1 rounded text-xs text-slate-200 bg-slate-700 hover:bg-slate-600 transition-colors"
              >
                用系统结论填充
              </button>
              <button
                onClick={() => void handleSaveReplayNote()}
                disabled={replaySaving}
                className="px-2.5 py-1 rounded text-xs text-white bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 transition-colors flex items-center gap-1"
              >
                {replaySaving ? <Loader2 size={12} className="animate-spin" /> : null}
                保存复盘日志
              </button>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
            <input
              value={replayDraft.headline}
              onChange={(e) => setReplayDraft((prev) => ({ ...prev, headline: e.target.value }))}
              className="px-2 py-1.5 bg-slate-900 border border-slate-700 rounded text-slate-200 focus:border-blue-500 focus:outline-none"
              placeholder="标题，如：2026-04-02 主线复盘"
            />
            <input
              value={replayDraft.mainLine}
              onChange={(e) => setReplayDraft((prev) => ({ ...prev, mainLine: e.target.value }))}
              className="px-2 py-1.5 bg-slate-900 border border-slate-700 rounded text-slate-200 focus:border-blue-500 focus:outline-none"
              placeholder="主线方向"
            />
            <input
              value={replayDraft.coreTargets}
              onChange={(e) => setReplayDraft((prev) => ({ ...prev, coreTargets: e.target.value }))}
              className="px-2 py-1.5 bg-slate-900 border border-slate-700 rounded text-slate-200 focus:border-blue-500 focus:outline-none"
              placeholder="核心标的/强度描述"
            />
            <input
              value={replayDraft.riskAlert}
              onChange={(e) => setReplayDraft((prev) => ({ ...prev, riskAlert: e.target.value }))}
              className="px-2 py-1.5 bg-slate-900 border border-slate-700 rounded text-slate-200 focus:border-blue-500 focus:outline-none"
              placeholder="风险提示"
            />
            <input
              value={replayDraft.actionPlan}
              onChange={(e) => setReplayDraft((prev) => ({ ...prev, actionPlan: e.target.value }))}
              className="md:col-span-2 px-2 py-1.5 bg-slate-900 border border-slate-700 rounded text-slate-200 focus:border-blue-500 focus:outline-none"
              placeholder="次日计划"
            />
          </div>
          <div className="mt-3 space-y-1.5 text-xs text-slate-300">
            {replayConclusion.bullets.map((line) => (
              <p key={line}>• {line}</p>
            ))}
          </div>
          <div className="mt-3">
            <p className="text-[11px] text-slate-500 mb-1">历史复盘日志</p>
            {replayNotesLoading ? (
              <div className="text-xs text-slate-500">加载中...</div>
            ) : replayNotes.length === 0 ? (
              <div className="text-xs text-slate-500">暂无已保存复盘日志</div>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {replayNotes.slice(0, 16).map((note) => (
                  <button
                    key={note.note_date}
                    onClick={() => {
                      setViewMode(note.view_mode === 'lianban' ? 'lianban' : 'sector');
                      setReplayNoteDate(note.note_date);
                    }}
                    className={clsx(
                      'px-2 py-1 rounded text-[11px] border transition-colors',
                      replayNoteDate === note.note_date
                        ? 'bg-blue-600/20 border-blue-500/40 text-blue-200'
                        : 'bg-slate-900 border-slate-700 text-slate-400 hover:bg-slate-800'
                    )}
                    title={note.headline || note.main_line || note.note_date}
                  >
                    {note.note_date} · {note.view_mode === 'lianban' ? '连板' : '板块'}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* 使用说明 */}
        <div className="bg-slate-800/30 rounded-lg p-3 text-xs text-slate-500">
          <div className="flex items-start gap-2">
            <Info size={14} className="mt-0.5 flex-shrink-0" />
            <div>
              <p>
                <strong className="text-slate-400">使用说明:</strong>
                {' '}支持“板块轮动”和“连板历史”双视图。点击格子可高亮同一板块/个股并查看趋势摘要。
                首次使用请先点击"同步今日"获取当天数据，之后系统会每天15:30自动同步。
              </p>
            </div>
          </div>
        </div>
      </div>
    </MainLayout>
  );
};
