import React, { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getHotConceptIntradayKline, getHotConceptLeaders, getHotConcepts, getLianbanLadder, getThsHot, getStockFundamentals } from '../api/client';
import { ConceptIntradayKlineItem, ConceptLeaderStock, HotConceptItem, LianbanLadderResponse, ThsHotItem } from '../types';
import { Navigation } from '../components/Navigation';
import { ChartPanel } from '../components/ChartPanel';
import { DateField } from '../components/DateField';
import { BarChart2, Flame, TrendingUp, Layers, RotateCcw, Filter, ChevronDown } from 'lucide-react';
import clsx from 'clsx';
import ReactECharts from 'echarts-for-react';
import { useStore } from '../stores/useStore';
import { MainLayout } from '../components/MainLayout';
import { getTranslation, TranslationKey } from '../lib/i18n';

// Filter options for concept list
type ConceptFilterOption = 'all' | '1' | '2' | '3' | '5' | '8';

// Helper to get cache TTL based on market phase
const getCacheTTL = (): number => {
  const now = new Date();
  const hours = now.getHours();
  const minutes = now.getMinutes();
  const time = hours * 60 + minutes;
  const dayOfWeek = now.getDay();

  // Weekend: 10 minutes
  if (dayOfWeek === 0 || dayOfWeek === 6) {
    return 10 * 60 * 1000;
  }

  // Auction: 9:15-9:25 - 10 seconds
  if (time >= 9 * 60 + 15 && time < 9 * 60 + 25) {
    return 10 * 1000;
  }

  // Morning session: 9:30-11:30 - 30 seconds
  if (time >= 9 * 60 + 30 && time < 11 * 60 + 30) {
    return 30 * 1000;
  }

  // Afternoon session: 13:00-15:00 - 30 seconds
  if (time >= 13 * 60 && time < 15 * 60) {
    return 30 * 1000;
  }

  // Non-trading hours: 5 minutes
  return 5 * 60 * 1000;
};

export const MarketOverview: React.FC = () => {
  const { selectStock, selectedStock, language } = useStore();
  const t = (key: TranslationKey) => getTranslation(language, key);

  const today = useMemo(() => {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }, []);
  const [activeTab, setActiveTab] = useState<'hot_concepts' | 'ths_hot' | 'lianban'>('hot_concepts');
  const [dateValue, setDateValue] = useState<string>(today);
  const [dateText, setDateText] = useState<string>(today);
  const [hotConcepts, setHotConcepts] = useState<HotConceptItem[]>([]);
  const [thsHot, setThsHot] = useState<ThsHotItem[]>([]);
  const [ladder, setLadder] = useState<LianbanLadderResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [thsCharacterByCode, setThsCharacterByCode] = useState<Record<string, string>>({});

  // New states for UX improvements
  const [conceptFilter, setConceptFilter] = useState<ConceptFilterOption>(() => {
    if (typeof window !== 'undefined') {
      return (localStorage.getItem('market_concept_filter') as ConceptFilterOption) || '2';
    }
    return '2';
  });
  const [showFilterDropdown, setShowFilterDropdown] = useState(false);
  const [userHasInteractedConcept, setUserHasInteractedConcept] = useState(false);
  const [userHasInteractedThs, setUserHasInteractedThs] = useState(false);

  type ConceptTabKey = 'leaders' | 'intraday';
  const moveConceptTab = useCallback((arr: ConceptTabKey[], from: ConceptTabKey, to: ConceptTabKey): ConceptTabKey[] => {
    if (from === to) return arr;
    const next = arr.slice();
    const fromIdx = next.indexOf(from);
    const toIdx = next.indexOf(to);
    if (fromIdx === -1 || toIdx === -1) return arr;
    next.splice(fromIdx, 1);
    const insertIdx = fromIdx < toIdx ? toIdx - 1 : toIdx;
    next.splice(insertIdx, 0, from);
    return next;
  }, []);

  const loadConceptTabOrder = useCallback((): ConceptTabKey[] => {
    if (typeof window === 'undefined') return ['leaders', 'intraday'];
    try {
      const raw = window.localStorage.getItem('market_overview_concept_tab_order');
      if (!raw) return ['leaders', 'intraday'];
      const parsed = JSON.parse(raw) as unknown;
      if (!Array.isArray(parsed)) return ['leaders', 'intraday'];
      const normalized = parsed
        .map((x) => (x === 'leaders' || x === 'intraday' ? x : null))
        .filter((x): x is ConceptTabKey => Boolean(x));
      const uniq = Array.from(new Set(normalized));
      const out: ConceptTabKey[] = [];
      for (const k of uniq) {
        if ((k === 'leaders' || k === 'intraday') && !out.includes(k)) out.push(k);
      }
      for (const k of ['leaders', 'intraday'] as const) {
        if (!out.includes(k)) out.push(k);
      }
      return out;
    } catch {
      return ['leaders', 'intraday'];
    }
  }, []);

  const [selectedConcept, setSelectedConcept] = useState<string>('');
  const [conceptTabOrder, setConceptTabOrder] = useState<ConceptTabKey[]>(() => loadConceptTabOrder());
  const [draggingConceptTab, setDraggingConceptTab] = useState<ConceptTabKey | null>(null);
  const [dragOverConceptTab, setDragOverConceptTab] = useState<ConceptTabKey | null>(null);
  const [conceptTab, setConceptTab] = useState<ConceptTabKey>('leaders');
  const [conceptIntraday, setConceptIntraday] = useState<ConceptIntradayKlineItem[]>([]);
  const [expandedLeader, setExpandedLeader] = useState<string | null>(null);
  const [conceptLeaders, setConceptLeaders] = useState<ConceptLeaderStock[]>([]);
  const [isLoadingConcept, setIsLoadingConcept] = useState(false);
  const [conceptError, setConceptError] = useState<string | null>(null);

  const formatFlowYi = useCallback((value: number) => {
    return `${Number(value || 0).toFixed(2)}${t('common.billion')}`;
  }, [language]); // Added language to dependency to ensure re-render on change

  const fetchActive = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const cleanDate = dateValue.replace(/-/g, '');
      
      // Batch request optimization
      if (activeTab === 'hot_concepts') {
        const res = await getHotConcepts(50, cleanDate);
        setHotConcepts(res);
      } else if (activeTab === 'ths_hot') {
        const res = await getThsHot(100, cleanDate);
        setThsHot(res);
      } else {
        const res = await getLianbanLadder(cleanDate);
        setLadder(res);
      }
    } catch (e: unknown) {
      if (e instanceof Error) setError(e.message);
      else setError(t('common.failed'));
    } finally {
      setIsLoading(false);
    }
  }, [activeTab, dateValue]);

  useEffect(() => {
    const run = async () => {
      try {
        const res = await getThsHot(200);
        const map: Record<string, string> = {};
        for (const it of res) {
          const code = String(it.code || '').replace(/\D/g, '').slice(-6);
          if (!code) continue;
          const raw = String(it.tags || it.reason || '').trim();
          if (!raw) continue;
          const compact = raw.replace(/\s+/g, ' ');
          map[code] = compact;
        }
        setThsCharacterByCode(map);
      } catch {
        setThsCharacterByCode({});
      }
    };
    run();
  }, []);

  useEffect(() => {
    fetchActive();
    
    // Auto-refresh every 2 minutes
    const interval = setInterval(() => {
      fetchActive();
      if (selectedConcept) {
        fetchConceptDetail(selectedConcept, true);
      }
    }, 2 * 60 * 1000); // 2 minutes

    return () => clearInterval(interval);
  }, [fetchActive]);

  // Auto-select first concept only if user hasn't interacted
  useEffect(() => {
    if (activeTab !== 'hot_concepts') return;
    if (userHasInteractedConcept) return; // Don't auto-select if user interacted
    if (selectedConcept) return;
    if (hotConcepts.length === 0) return;
    setSelectedConcept(hotConcepts[0].name);
  }, [activeTab, hotConcepts, selectedConcept, userHasInteractedConcept]);

  // Reset interaction flag when switching tabs
  useEffect(() => {
    setUserHasInteractedConcept(false);
    setUserHasInteractedThs(false);
  }, [activeTab]);

  // Persist filter preference
  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('market_concept_filter', conceptFilter);
    }
  }, [conceptFilter]);

  const conceptCacheRef = useRef<Map<string, { data: any; timestamp: number }>>(new Map());

  const fetchConceptDetail = useCallback(async (name: string, force = false) => {
    if (!name) return;
    setIsLoadingConcept(true);
    setConceptError(null);
    
    // Use dynamic cache TTL based on market phase
    const cacheKey = `${name}-${dateValue}`;
    const cached = conceptCacheRef.current.get(cacheKey);
    const now = Date.now();
    const cacheTTL = getCacheTTL();
    
    if (!force && cached && (now - cached.timestamp) < cacheTTL) {
      console.log(`Using cached data for concept: ${name} (TTL: ${cacheTTL/1000}s)`);
      setConceptIntraday(cached.data.intraday);
      setConceptLeaders(cached.data.leaders);
      // Don't auto-select stock from cache if user has interacted
      if (!userHasInteractedConcept && cached.data.leaders.length > 0 && (!selectedStock || selectedStock.code !== cached.data.leaders[0].code)) {
        selectStock({
          code: cached.data.leaders[0].code,
          name: cached.data.leaders[0].name,
          current_price: Number(cached.data.leaders[0].price || 0),
          change_percent: Number(cached.data.leaders[0].change_percent || 0),
          volume: 0,
          market_cap: 0,
          is_short: false,
        });
      }
      setIsLoadingConcept(false);
      return;
    }

    try {
      const [intraday, leaders] = await Promise.all([
        getHotConceptIntradayKline({ name: name, period: '1', date: dateValue }),
        getHotConceptLeaders({ name: name, limit: 20, date: dateValue }),
      ]);

      // Cache the results
      conceptCacheRef.current.set(cacheKey, {
        data: { intraday, leaders },
        timestamp: now
      });

      setConceptIntraday(intraday);
      setConceptLeaders(leaders);
      // Don't auto-select stock if user has interacted
      if (!userHasInteractedConcept && leaders.length > 0 && (!selectedStock || selectedStock.code !== leaders[0].code)) {
        selectStock({
          code: leaders[0].code,
          name: leaders[0].name,
          current_price: Number(leaders[0].price || 0),
          change_percent: Number(leaders[0].change_percent || 0),
          volume: 0,
          market_cap: 0,
          is_short: false,
        });
      }
    } catch (e: unknown) {
      if (e instanceof Error) setConceptError(e.message);
      else setConceptError(t('common.failed'));
      setConceptIntraday([]);
      setConceptLeaders([]);
    } finally {
      setIsLoadingConcept(false);
    }
  }, [selectStock, selectedStock, dateValue, userHasInteractedConcept]);

  // 修改选择股票的逻辑，不再需要本地的 setSelectedStockFundamentals，直接使用 store 中的数据
  useEffect(() => {
    if (selectedStock?.code) {
      // selectStock in useStore already fetches fundamentals
    }
  }, [selectedStock]);

  useEffect(() => {
    if (activeTab !== 'hot_concepts') return;
    if (!selectedConcept) return;
    fetchConceptDetail(selectedConcept);
  }, [activeTab, fetchConceptDetail, selectedConcept]);

  // Auto-select first stock in THS hot list only if user hasn't interacted
  useEffect(() => {
    if (activeTab !== 'ths_hot') return;
    if (userHasInteractedThs) return; // Don't auto-select if user interacted
    if (thsHot.length === 0) return;
    const first = thsHot[0];
    if (!first?.code) return;
    const nextCode = String(first.code || '').replace(/\D/g, '').slice(-6);
    if (!nextCode) return;
    if (selectedStock?.code === nextCode) return;
    selectStock({
      code: nextCode,
      name: first.name,
      current_price: Number(first.price || 0),
      change_percent: Number(first.change_percent || 0),
      volume: 0,
      market_cap: 0,
      is_short: false,
    });
  }, [activeTab, selectStock, selectedStock?.code, thsHot]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem('market_overview_concept_tab_order', JSON.stringify(conceptTabOrder));
    } catch {
      // ignore
    }
  }, [conceptTabOrder]);

  const conceptIntradayOption = useMemo(() => {
    if (!conceptIntraday || conceptIntraday.length === 0) return null;
    const times = conceptIntraday.map((it) => {
      const t = String(it.time || '');
      const parts = t.split(' ');
      return parts.length > 1 ? parts[1] : t;
    });
    const ohlc = conceptIntraday.map((it) => [Number(it.open || 0), Number(it.close || 0), Number(it.low || 0), Number(it.high || 0)]);
    const volumes = conceptIntraday.map((it, idx) => [idx, Number(it.volume || 0), (Number(it.close || 0) >= Number(it.open || 0)) ? 1 : -1]);

    return {
      title: { text: t('market.intraday'), left: 'center', textStyle: { color: '#eee' } },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      grid: [
        { left: '10%', right: '8%', height: '55%' },
        { left: '10%', right: '8%', top: '70%', height: '18%' },
      ],
      xAxis: [
        { type: 'category', data: times, scale: true, boundaryGap: false, axisLine: { onZero: false }, splitLine: { show: false }, min: 'dataMin', max: 'dataMax', axisLabel: { color: '#ccc' } },
        { type: 'category', gridIndex: 1, data: times, scale: true, boundaryGap: false, axisLine: { onZero: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false }, min: 'dataMin', max: 'dataMax' },
      ],
      yAxis: [
        { scale: true, splitArea: { show: true }, axisLabel: { color: '#ccc' } },
        { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, axisLine: { show: false }, splitLine: { show: false } },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
        { show: true, xAxisIndex: [0, 1], type: 'slider', bottom: 10, start: 0, end: 100, textStyle: { color: '#ccc' } },
      ],
      series: [
        {
          name: 'K',
          type: 'candlestick',
          data: ohlc,
          itemStyle: { color: '#ef232a', color0: '#14b143', borderColor: '#ef232a', borderColor0: '#14b143' },
        },
        {
          name: 'Volume',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes.map((v) => v[1]),
          itemStyle: {
            color: (params: { dataIndex: number }) => {
              const isUp = volumes[params.dataIndex][2] > 0;
              return isUp ? '#ef232a' : '#14b143';
            },
          },
        },
      ],
    };
  }, [conceptIntraday]);

  const ladderMeta = useMemo(() => {
    if (!ladder?.date) return null;
    return `${ladder.prev_date ? `${t('market.yesterday')} ${ladder.prev_date}` : t('market.yesterday')}  → ${t('market.today')} ${ladder.date}`;
  }, [ladder, language]);

  return (
    <MainLayout title={t('market.title')}>
      <div className="flex flex-col gap-6 h-full">
        <div className="flex flex-wrap gap-2 items-center">
          <button
            onClick={() => setActiveTab('hot_concepts')}
            className={clsx(
              "flex items-center gap-2 px-4 py-2 rounded-lg font-bold text-xs uppercase tracking-widest transition-all",
              activeTab === 'hot_concepts' ? "bg-blue-600 text-white shadow-lg shadow-blue-900/20" : "bg-[#111827] text-slate-400 hover:bg-slate-800 border border-slate-800"
            )}
          >
            <TrendingUp size={16} />
            {t('market.hot_concepts')}
          </button>
          <button
            onClick={() => setActiveTab('ths_hot')}
            className={clsx(
              "flex items-center gap-2 px-4 py-2 rounded-lg font-bold text-xs uppercase tracking-widest transition-all",
              activeTab === 'ths_hot' ? "bg-blue-600 text-white shadow-lg shadow-blue-900/20" : "bg-[#111827] text-slate-400 hover:bg-slate-800 border border-slate-800"
            )}
          >
            <Flame size={16} />
            {t('market.ths_hot')}
          </button>
          <button
            onClick={() => setActiveTab('lianban')}
            className={clsx(
              "flex items-center gap-2 px-4 py-2 rounded-lg font-bold text-xs uppercase tracking-widest transition-all",
              activeTab === 'lianban' ? "bg-blue-600 text-white shadow-lg shadow-blue-900/20" : "bg-[#111827] text-slate-400 hover:bg-slate-800 border border-slate-800"
            )}
          >
            <Layers size={16} />
            {t('market.lianban')}
          </button>

          <div className="flex items-center gap-2 ml-auto">
            <div className="flex flex-col">
              <DateField
                value={dateValue}
                text={dateText}
                onTextChange={(val) => {
                  setDateText(val);
                  if (!val) setDateValue('');
                }}
                onDatePick={(val) => {
                  setDateValue(val);
                  setDateText(val);
                }}
                placeholder={t('market.select_date')}
                className="!mt-0 w-40"
              />
            </div>
            {/* Back to Today button - only visible when viewing historical date */}
            {dateValue && dateValue !== today && (
              <button
                onClick={() => {
                  setDateValue(today);
                  setDateText(today);
                }}
                className="flex items-center gap-1 px-3 py-2 text-xs font-bold text-blue-400 hover:text-blue-300 bg-blue-600/10 hover:bg-blue-600/20 rounded-lg border border-blue-500/30 transition-colors"
                title={t('market.realtime')}
              >
                <RotateCcw size={14} />
                {language === 'zh' ? '今天' : 'Today'}
              </button>
            )}
          </div>

          {activeTab === 'lianban' && ladderMeta && (
            <span className="text-[10px] text-slate-500 font-mono ml-4 uppercase tracking-tighter">
              {ladderMeta}
            </span>
          )}
        </div>

        <div className="flex-1 overflow-hidden flex flex-col bg-[#111827] rounded-xl border border-slate-800 shadow-2xl min-h-[600px]">
          {error && (
            <div className="p-4 text-xs text-red-400 bg-red-500/10 border-b border-red-500/20 flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500"></span>
              {error}
            </div>
          )}

          {activeTab === 'hot_concepts' && (
            <div className="flex-1 overflow-hidden grid grid-cols-1 lg:grid-cols-3 divide-x divide-slate-800">
              <div className="lg:col-span-1 overflow-hidden flex flex-col">
                <div className="px-6 py-4 bg-[#0d121f] text-[10px] font-bold uppercase text-slate-500 tracking-wider border-b border-slate-800 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span>{t('market.hot_concepts')}</span>
                    <span className="text-slate-600">
                      ({hotConcepts.filter(c => conceptFilter === 'all' || c.change_percent >= Number(conceptFilter)).length}/{hotConcepts.length})
                    </span>
                  </div>
                  {/* Filter dropdown */}
                  <div className="relative">
                    <button
                      onClick={() => setShowFilterDropdown(!showFilterDropdown)}
                      className="flex items-center gap-1 px-2 py-1 text-[10px] bg-slate-800 hover:bg-slate-700 rounded border border-slate-700 transition-colors"
                    >
                      <Filter size={10} />
                      <span>{conceptFilter === 'all' ? (language === 'zh' ? '全部' : 'All') : `>=${conceptFilter}%`}</span>
                      <ChevronDown size={10} />
                    </button>
                    {showFilterDropdown && (
                      <div className="absolute right-0 mt-1 w-32 bg-[#111827] border border-slate-700 rounded-lg shadow-xl z-20 overflow-hidden">
                        {(['all', '1', '2', '3', '5', '8'] as ConceptFilterOption[]).map((opt) => (
                          <button
                            key={opt}
                            onClick={() => {
                              setConceptFilter(opt);
                              setShowFilterDropdown(false);
                            }}
                            className={clsx(
                              "w-full px-3 py-2 text-left text-xs hover:bg-slate-800 transition-colors",
                              conceptFilter === opt ? "bg-blue-600/20 text-blue-400" : "text-slate-300"
                            )}
                          >
                            {opt === 'all' ? (language === 'zh' ? '显示全部' : 'Show All') : `>= ${opt}%`}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex-1 overflow-auto custom-scrollbar">
                  <table className="w-full text-left text-sm text-slate-300">
                    <thead className="bg-[#0d121f]/50 text-[10px] uppercase text-slate-600 font-bold sticky top-0 backdrop-blur-sm">
                      <tr>
                        <th className="px-4 py-3 min-w-[60px]">{t('market.rank')}</th>
                        <th className="px-4 py-3 min-w-[120px]">{t('market.concept')}</th>
                        <th className="px-4 py-3 text-right min-w-[80px]">{t('market.change')}</th>
                        <th className="px-4 py-3 text-right min-w-[80px]">{t('market.flow')}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/30">
                      {hotConcepts.filter(c => conceptFilter === 'all' || c.change_percent >= Number(conceptFilter)).map((c) => {
                        const isSelected = selectedConcept === c.name;
                        return (
                          <tr
                            key={`${c.rank}-${c.name}`}
                            className={clsx(
                              "hover:bg-[#1f2937]/50 transition-colors cursor-pointer group",
                              isSelected ? "bg-[#1f2937] ring-1 ring-inset ring-blue-500/30" : ""
                            )}
                            onClick={() => {
                              setUserHasInteractedConcept(true); // Mark user interaction
                              const nm = c.name;
                              setSelectedConcept(nm);
                              setConceptTab('leaders');
                              fetchConceptDetail(nm, true);
                            }}
                          >
                            <td className="px-4 py-3 text-slate-500 font-mono text-xs min-w-[60px]">{c.rank}</td>
                            <td className="px-4 py-3 font-bold text-slate-100 group-hover:text-blue-400 transition-colors min-w-[120px]">{c.name}</td>
                            <td className={clsx("px-4 py-3 text-right font-mono font-black min-w-[80px]", c.change_percent >= 0 ? "text-[#ef4444]" : "text-[#10b981]")}>
                              {c.change_percent > 0 ? '+' : ''}{c.change_percent.toFixed(2)}%
                            </td>
                            <td className={clsx("px-4 py-3 text-right font-mono text-xs min-w-[80px]", c.net_inflow >= 0 ? "text-red-400" : "text-green-400")}>
                              {formatFlowYi(c.net_inflow)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="lg:col-span-2 overflow-hidden flex flex-col min-h-0 bg-[#0d121f]/30">
                <div className="px-6 py-4 border-b border-slate-800 bg-[#0d121f] flex flex-wrap items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className="w-2 h-2 rounded-full bg-blue-500 shadow-lg shadow-blue-500/50"></div>
                    <div className="text-sm font-black text-slate-100 uppercase tracking-tight">
                      {selectedConcept ? selectedConcept : t('market.select_concept')}
                    </div>
                  </div>
                  <div className="flex items-center bg-[#111827] p-1 rounded-lg border border-slate-800">
                    {conceptTabOrder.map((k) => (
                      <button
                        key={k}
                        draggable
                        onDragStart={(e) => {
                          setDraggingConceptTab(k);
                          setDragOverConceptTab(k);
                          e.dataTransfer.effectAllowed = 'move';
                          e.dataTransfer.setData('text/plain', k);
                        }}
                        onDragEnd={() => {
                          setDraggingConceptTab(null);
                          setDragOverConceptTab(null);
                        }}
                        onDragOver={(e) => {
                          e.preventDefault();
                          if (dragOverConceptTab !== k) setDragOverConceptTab(k);
                        }}
                        onDragLeave={() => {
                          if (dragOverConceptTab === k) setDragOverConceptTab(null);
                        }}
                        onDrop={(e) => {
                          e.preventDefault();
                          const from = draggingConceptTab || (e.dataTransfer.getData('text/plain') as ConceptTabKey);
                          if (!from) return;
                          if (from === k) return;
                          setConceptTabOrder(moveConceptTab(conceptTabOrder, from, k));
                        }}
                        onClick={() => setConceptTab(k)}
                        className={clsx(
                          "px-4 py-1.5 rounded-md text-[10px] font-black uppercase tracking-widest transition-all",
                          conceptTab === k ? "bg-slate-800 text-blue-400 shadow-sm" : "text-slate-500 hover:text-slate-300",
                          draggingConceptTab === k && 'opacity-60',
                          dragOverConceptTab === k && draggingConceptTab && draggingConceptTab !== k && 'bg-blue-600/20'
                        )}
                      >
                        {k === 'leaders' ? t('market.leaders') : t('market.intraday')}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex-1 overflow-hidden relative">
                  {isLoadingConcept && (
                    <div className="absolute inset-0 flex items-center justify-center bg-[#0d121f]/60 backdrop-blur-sm z-20 transition-all">
                      <div className="flex flex-col items-center gap-3">
                        <div className="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-blue-500"></div>
                        <span className="text-[10px] font-black uppercase tracking-widest text-blue-500 animate-pulse">{t('market.loading_data')}</span>
                      </div>
                    </div>
                  )}

                  {conceptTab === 'intraday' && (
                    <div className="h-full p-6">
                      <div className="bg-[#111827] border border-slate-800 rounded-xl h-full overflow-hidden shadow-inner">
                        {conceptIntradayOption ? (
                          <ReactECharts option={conceptIntradayOption} style={{ height: '100%', width: '100%' }} theme="dark" />
                        ) : (
                          <div className="h-full flex items-center justify-center text-[10px] font-black uppercase tracking-widest text-slate-600">{t('market.no_data')}</div>
                        )}
                      </div>
                    </div>
                  )}

                  {conceptTab === 'leaders' && (
                    <div className="h-full flex flex-col p-6 overflow-auto custom-scrollbar gap-6">
                      <div className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden shadow-xl">
                        <div className="px-6 py-3 text-[10px] font-black uppercase text-slate-500 tracking-widest border-b border-slate-800 bg-[#0d121f]/50">
                          {t('market.constituents')}
                        </div>
                        <div className="overflow-x-auto">
                          {conceptLeaders.length === 0 ? (
                            <div className="flex items-center justify-center py-12 text-slate-500 text-sm">
                              {isLoadingConcept ? t('market.loading_data') : (selectedConcept ? t('market.no_data') : t('market.select_concept'))}
                            </div>
                          ) : (
                          <table className="w-full text-left text-xs text-slate-300">
                            <thead className="bg-[#0d121f] text-[9px] uppercase text-slate-600 font-bold border-b border-slate-800">
                              <tr>
                                <th className="px-4 py-3 min-w-[70px]">{t('market.code')}</th>
                                <th className="px-4 py-3 min-w-[100px]">{t('market.security')}</th>
                                <th className="px-4 py-3 text-right font-mono min-w-[70px]">{t('market.price')}</th>
                                <th className="px-4 py-3 text-right font-mono min-w-[70px]">{t('market.change')}</th>
                                <th className="px-4 py-3 text-right font-mono min-w-[80px]">{t('market.amount')}</th>
                                <th className="px-4 py-3 text-right font-mono min-w-[70px]">{t('market.turnover')}</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-800/30 font-mono">
                              {conceptLeaders.map((s) => {
                                const isSelected = selectedStock?.code === s.code;
                                const character = thsCharacterByCode[String(s.code || '').replace(/\D/g, '').slice(-6)] || '';
                                const isExpanded = expandedLeader === s.code;
                                
                                return (
                                  <React.Fragment key={s.code}>
                                    <tr
                                      className={clsx(
                                        "hover:bg-[#1f2937]/50 transition-all cursor-pointer",
                                        isSelected ? "bg-[#1f2937] ring-1 ring-inset ring-blue-500/30" : ""
                                      )}
                                      onClick={() => {
                                        if (expandedLeader === s.code) setExpandedLeader(null);
                                        else setExpandedLeader(s.code);
                                                                      
                                        selectStock({
                                          code: s.code,
                                          name: s.name,
                                          current_price: Number(s.price || 0),
                                          change_percent: Number(s.change_percent || 0),
                                          volume: 0,
                                          market_cap: 0,
                                          is_short: false,
                                        });
                                      }}
                                    >
                                      <td className="px-4 py-3 text-slate-500 min-w-[70px]">{s.code}</td>
                                      <td className="px-4 py-3 font-sans min-w-[100px]">
                                        <div className="flex items-center gap-2">
                                          <span className="font-black text-slate-100">{s.name}</span>
                                          {character && (
                                            <span className="text-[10px] font-medium text-slate-500 truncate max-w-[150px]" title={character}>
                                              · {character}
                                            </span>
                                          )}
                                        </div>
                                      </td>
                                      <td className="px-4 py-3 text-right font-bold text-slate-200 min-w-[70px]">{Number(s.price || 0).toFixed(2)}</td>
                                      <td className={clsx("px-4 py-3 text-right font-black min-w-[70px]", Number(s.change_percent || 0) >= 0 ? "text-[#ef4444]" : "text-[#10b981]")}>
                                        {Number(s.change_percent || 0) > 0 ? '+' : ''}{Number(s.change_percent || 0).toFixed(2)}%
                                      </td>
                                      <td className="px-4 py-3 text-right text-slate-400 min-w-[80px]">{formatFlowYi(Number(s.amount || 0) / 100000000)}</td>
                                      <td className="px-4 py-3 text-right text-slate-400 min-w-[70px]">{Number(s.turnover || 0).toFixed(2)}%</td>
                                    </tr>
                                    
                                    {isExpanded && (
                                      <tr className="bg-[#0d121f]">
                                        <td colSpan={6} className="px-4 py-4 border-t border-slate-800 shadow-inner">
                                          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 h-[280px]">
                                            <div className="bg-[#111827] rounded-lg border border-slate-800 p-3 shadow-lg">
                                              <ChartPanel mode="intraday" />
                                            </div>
                                            <div className="bg-[#111827] rounded-lg border border-slate-800 p-3 shadow-lg">
                                              <ChartPanel mode="daily" />
                                            </div>
                                          </div>
                                        </td>
                                      </tr>
                                    )}
                                  </React.Fragment>
                                );
                              })}
                            </tbody>
                          </table>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'ths_hot' && (
            <div className="flex-1 overflow-hidden grid grid-cols-1 lg:grid-cols-3 divide-x divide-slate-800">
              <div className="lg:col-span-1 overflow-hidden flex flex-col">
                <div className="px-6 py-4 bg-[#0d121f] text-[10px] font-bold uppercase text-slate-500 tracking-wider border-b border-slate-800">
                  {t('market.ths_hot')}
                </div>
                <div className="flex-1 overflow-auto custom-scrollbar">
                  <table className="w-full text-left text-sm text-slate-300">
                    <thead className="bg-[#0d121f]/50 text-[10px] uppercase text-slate-600 sticky top-0 backdrop-blur-sm">
                      <tr>
                        <th className="px-4 py-3 min-w-[60px]">{t('market.rank')}</th>
                        <th className="px-4 py-3 min-w-[120px]">{t('market.security')}</th>
                        <th className="px-4 py-3 text-right min-w-[60px]">Hot</th>
                        <th className="px-4 py-3 text-right min-w-[80px]">{t('market.change')}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/30">
                      {thsHot.map((s) => {
                        const code = String(s.code || '').replace(/\D/g, '').slice(-6);
                        const isSelected = selectedStock?.code === code;
                        return (
                          <tr
                            key={`${s.rank}-${s.code}`}
                            className={clsx(
                              "hover:bg-[#1f2937]/50 transition-colors cursor-pointer group",
                              isSelected ? "bg-[#1f2937] ring-1 ring-inset ring-blue-500/30" : ""
                            )}
                            onClick={() => {
                              if (!code) return;
                              setUserHasInteractedThs(true); // Mark user interaction
                              selectStock({
                                code,
                                name: s.name,
                                current_price: Number(s.price || 0),
                                change_percent: Number(s.change_percent || 0),
                                volume: 0,
                                market_cap: 0,
                                is_short: false,
                              });
                            }}
                          >
                            <td className="px-4 py-3 text-slate-500 font-mono text-xs min-w-[60px]">{s.rank}</td>
                            <td className="px-4 py-3 font-bold text-slate-100 group-hover:text-blue-400 transition-colors min-w-[120px]">{s.name}</td>
                            <td className="px-4 py-3 text-right font-mono text-xs text-orange-400 min-w-[60px]">{Number(s.hot || 0).toFixed(0)}</td>
                            <td className={clsx("px-4 py-3 text-right font-mono font-black min-w-[80px]", Number(s.change_percent || 0) >= 0 ? "text-[#ef4444]" : "text-[#10b981]")}>
                              {Number(s.change_percent || 0) > 0 ? '+' : ''}{Number(s.change_percent || 0).toFixed(2)}%
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="lg:col-span-2 overflow-hidden flex flex-col bg-[#0d121f]/30">
                <div className="px-6 py-4 border-b border-slate-800 bg-[#0d121f] flex flex-col gap-1">
                  <div className="flex items-center gap-3">
                    <div className="w-2 h-2 rounded-full bg-orange-500 shadow-lg shadow-orange-500/50"></div>
                    <div className="text-sm font-black text-slate-100 uppercase tracking-tight">
                      {selectedStock ? `${selectedStock.name} (${selectedStock.code})` : t('chart.select_stock_hint')}
                    </div>
                  </div>
                  <div className="text-[10px] text-slate-500 font-medium italic mt-1 pl-5">
                    {thsHot.find((it) => String(it.code || '').replace(/\D/g, '').slice(-6) === selectedStock?.code)?.reason ||
                      thsHot.find((it) => String(it.code || '').replace(/\D/g, '').slice(-6) === selectedStock?.code)?.tags ||
                      t('market.no_analysis')}
                  </div>
                </div>
                <div className="flex-1 p-6 overflow-hidden">
                  <div className="bg-[#111827] border border-slate-800 rounded-xl h-full overflow-hidden shadow-2xl p-4">
                    <ChartPanel />
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'lianban' && (
            <div className="flex-1 overflow-auto p-4 sm:p-6 custom-scrollbar bg-[#0d121f]/20">
              {/* 晋级模式横向布局 */}
              <div className="flex gap-4 overflow-x-auto pb-4">
                {ladder?.levels?.filter(lv => lv.today_items.length > 0).sort((a, b) => a.today_level - b.today_level).map((lv) => (
                  <div key={`level-${lv.today_level}`} className="flex-shrink-0 w-72 bg-[#111827] rounded-xl border border-slate-800 shadow-lg overflow-hidden">
                    {/* 板级头部 */}
                    <div className="px-4 py-3 bg-gradient-to-r from-red-900/30 to-slate-900 border-b border-slate-700">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="flex items-center justify-center w-8 h-8 rounded-full bg-red-500/20 border border-red-500/40">
                            <span className="text-lg font-black text-red-400">{lv.today_level}</span>
                          </div>
                          <div>
                            <h3 className="font-black text-white text-sm">
                              {lv.today_level === 1 ? '今日首板' : `今日${lv.today_level}板`}
                            </h3>
                            <p className="text-[10px] text-slate-400">{lv.today_count} 只股票</p>
                          </div>
                        </div>
                        {lv.prev_count > 0 && (
                          <div className="text-right">
                            <div className="text-[10px] text-slate-500">昨日{lv.prev_level}板</div>
                            <div className="text-xs font-bold text-green-400">{lv.prev_count}→{lv.today_count}</div>
                          </div>
                        )}
                      </div>
                    </div>
                    
                    {/* 股票列表 */}
                    <div className="p-3 max-h-[500px] overflow-y-auto custom-scrollbar">
                      <div className="space-y-2">
                        {lv.today_items.map((it, idx) => (
                          <div 
                            key={`t-${lv.today_level}-${it.code}`}
                            className="flex items-center justify-between p-2.5 bg-[#0d121f]/50 rounded-lg border border-slate-800 hover:bg-slate-800/50 hover:border-red-500/30 transition-all cursor-pointer"
                            onClick={() => {
                              selectStock({
                                code: it.code,
                                name: it.name,
                                current_price: Number(it.price || 0),
                                change_percent: Number(it.change_percent || 0),
                                volume: 0,
                                market_cap: 0,
                                is_short: false,
                              });
                            }}
                          >
                            <div className="flex items-center gap-2">
                              <div className="flex items-center justify-center w-5 h-5 rounded bg-slate-700/50">
                                <span className="text-[10px] font-bold text-slate-300">{idx + 1}</span>
                              </div>
                              <div>
                                <div className="font-bold text-white text-sm">{it.name}</div>
                                <div className="text-[10px] text-slate-500">{it.code}</div>
                              </div>
                            </div>
                            <div className="text-right">
                              <div className={clsx(
                                "text-sm font-black",
                                it.change_percent >= 0 ? "text-red-500" : "text-green-500"
                              )}>
                                {it.change_percent > 0 ? '+' : ''}{it.change_percent.toFixed(2)}%
                              </div>
                              <div className="text-[10px] text-slate-400">¥{it.price?.toFixed(2)}</div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                ))}
                
                {(!ladder || ladder.levels.length === 0 || ladder.levels.every(lv => lv.today_items.length === 0)) && (
                  <div className="flex-1 flex flex-col items-center justify-center py-20 text-center">
                    <div className="w-16 h-16 rounded-full bg-slate-800 flex items-center justify-center mb-4">
                      <Layers className="w-8 h-8 text-slate-600" />
                    </div>
                    <h3 className="text-lg font-bold text-slate-400 mb-2">暂无连板股票</h3>
                    <p className="text-slate-600 max-w-md">当前没有连续涨停的股票</p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </MainLayout>
  );
};
