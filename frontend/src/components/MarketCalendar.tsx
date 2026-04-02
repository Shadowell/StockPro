import React, { useCallback, useEffect, useMemo, useState } from "react";
import { getMarketCalendar, refreshMarketCalendar, generateMarketCalendarWithAI, refreshMarketCalendarWithFreeData } from "@/api/client";
import { MarketCalendarEvent } from "@/types";
import { RefreshCw, CalendarDays, Sparkles, Grid3X3 } from "lucide-react";
import { CalendarView } from "./CalendarView";
import { getTranslation, TranslationKey } from "../lib/i18n";
import { useStore } from "../stores/useStore";

type FilterPreset = "all" | "near" | "month";

export const MarketCalendar: React.FC = () => {
  const { language } = useStore();
  const [events, setEvents] = useState<MarketCalendarEvent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isRefreshingWithFreeData, setIsRefreshingWithFreeData] = useState(false);
  const [isGeneratingWithAI, setIsGeneratingWithAI] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preset, setPreset] = useState<FilterPreset>("near");
  const [showAIPanel, setShowAIPanel] = useState(false);
  const [aiStartDate, setAiStartDate] = useState<string>('');
  const [aiEndDate, setAiEndDate] = useState<string>('');
  const [viewMode, setViewMode] = useState<'list' | 'calendar'>('calendar'); // 默认显示日历视图

  const t = useCallback((key: TranslationKey) => getTranslation(language, key), [language]);

  const today = useMemo(() => new Date(), []);

  const fetchEvents = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await getMarketCalendar();
      setEvents(res);
    } catch (e) {
      console.error("Failed to fetch market calendar", e);
      setError(t('calendar.load_failed'));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await refreshMarketCalendar(6);
      await fetchEvents();
    } catch (e) {
      console.error("Failed to refresh market calendar", e);
      setError(t('calendar.refresh_failed'));
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleRefreshWithFreeData = async () => {
    setIsRefreshingWithFreeData(true);
    try {
      await refreshMarketCalendarWithFreeData(6);
      await fetchEvents();
      alert(t('calendar.refresh_success'));
    } catch (e) {
      console.error("Failed to refresh market calendar with free data", e);
      setError(t('calendar.refresh_failed'));
    } finally {
      setIsRefreshingWithFreeData(false);
    }
  };

  const handleGenerateWithAI = async () => {
    if (!aiStartDate || !aiEndDate) {
      setError(t('calendar.enter_dates'));
      return;
    }

    setIsGeneratingWithAI(true);
    setError(null);
    try {
      const result = await generateMarketCalendarWithAI({
        start_date: aiStartDate,
        end_date: aiEndDate,
      });
      
      if (result.status === 'success') {
        // 成功生成后重新获取事件
        await fetchEvents();
        setShowAIPanel(false); // 关闭面板
        alert(`${t('calendar.ai_generation_success')} ${result.count} ${t('calendar.events_count')}`);
      } else {
        setError(result.message || t('calendar.ai_generation_failed'));
      }
    } catch (e) {
      console.error("Failed to generate calendar with AI", e);
      setError(t('calendar.ai_generation_failed'));
    } finally {
      setIsGeneratingWithAI(false);
    }
  };

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  const filteredEvents = useMemo(() => {
    if (events.length === 0) return [];
    const base = events.slice().sort((a, b) => a.event_date.localeCompare(b.event_date));

    if (preset === "all") return base;

    if (preset === "near") {
      const now = today;
      const windowDays = 14;
      return base.filter((e) => {
        const d = new Date(e.event_date);
        const diff = (d.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);
        return diff >= -3 && diff <= windowDays;
      });
    }

    if (preset === "month") {
      const year = today.getFullYear();
      const month = today.getMonth();
      return base.filter((e) => {
        const d = new Date(e.event_date);
        return d.getFullYear() === year && d.getMonth() === month;
      });
    }

    return base;
  }, [events, preset, today]);

  const groupedByDate = useMemo(() => {
    const map: Record<string, MarketCalendarEvent[]> = {};
    for (const e of filteredEvents) {
      if (!map[e.event_date]) {
        map[e.event_date] = [];
      }
      map[e.event_date].push(e);
    }
    return Object.entries(map).sort(([d1], [d2]) => d1.localeCompare(d2));
  }, [filteredEvents]);

  return (
    <div className="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <CalendarDays className="text-blue-400" size={18} />
          <span className="text-sm font-semibold text-gray-100">{t('nav.news')}</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <button
            onClick={() => setViewMode('calendar')}
            className={`px-2 py-1 rounded-md ${
              viewMode === 'calendar' ? "bg-blue-600 text-white" : "bg-slate-800 text-gray-300 hover:bg-slate-700"
            }`}
            title={t('calendar.calendar_view')}
          >
            <Grid3X3 size={14} />
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`px-2 py-1 rounded-md ${
              viewMode === 'list' ? "bg-blue-600 text-white" : "bg-slate-800 text-gray-300 hover:bg-slate-700"
            }`}
            title={t('calendar.list_view')}
          >
            <CalendarDays size={14} />
          </button>
          <button
            onClick={() => setPreset("near")}
            className={`px-2 py-1 rounded-md ${
              preset === "near" ? "bg-blue-600 text-white" : "bg-slate-800 text-gray-300 hover:bg-slate-700"
            }`}
          >
            {t('calendar.near_two_weeks')}
          </button>
          <button
            onClick={() => setPreset("month")}
            className={`px-2 py-1 rounded-md ${
              preset === "month" ? "bg-blue-600 text-white" : "bg-slate-800 text-gray-300 hover:bg-slate-700"
            }`}
          >
            {t('calendar.this_month')}
          </button>
          <button
            onClick={() => setPreset("all")}
            className={`px-2 py-1 rounded-md ${
              preset === "all" ? "bg-blue-600 text-white" : "bg-slate-800 text-gray-300 hover:bg-slate-700"
            }`}
          >
            {t('calendar.all_events')}
          </button>
          <button
            onClick={handleRefresh}
            disabled={isRefreshing || isRefreshingWithFreeData}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-blue-700 hover:bg-blue-600 disabled:bg-slate-700 text-gray-100"
            title={t('common.refresh')}
          >
            <RefreshCw size={14} className={isRefreshing ? "animate-spin" : ""} />
            <span>{language === 'zh' ? '刷新' : 'Refresh'}</span>
          </button>
          <button
            onClick={handleRefreshWithFreeData}
            disabled={isRefreshing || isRefreshingWithFreeData}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-emerald-700 hover:bg-emerald-600 disabled:bg-slate-700 text-gray-100"
            title={language === 'zh' ? '免费源刷新' : 'Refresh with free source'}
          >
            <RefreshCw size={14} className={isRefreshingWithFreeData ? "animate-spin" : ""} />
            <span>{language === 'zh' ? '免费源' : 'Free source'}</span>
          </button>
          {/* Loading indicator */}
          {(isRefreshing || isRefreshingWithFreeData) && (
            <RefreshCw size={14} className="animate-spin text-blue-400 ml-2" />
          )}
          <button
            onClick={() => setShowAIPanel(!showAIPanel)}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-purple-800 hover:bg-purple-700 text-gray-300"
          >
            <Sparkles size={14} />
            <span>{t('calendar.ai_generate')}</span>
          </button>
        </div>
      </div>

      {showAIPanel && (
        <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/60">
          <div className="flex items-center gap-2 text-xs">
            <input
              type="date"
              value={aiStartDate}
              onChange={(e) => setAiStartDate(e.target.value)}
              className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-xs text-gray-200"
            />
            <span className="text-gray-400">-</span>
            <input
              type="date"
              value={aiEndDate}
              onChange={(e) => setAiEndDate(e.target.value)}
              className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-xs text-gray-200"
            />
            <button
              onClick={handleGenerateWithAI}
              disabled={isGeneratingWithAI}
              className="px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isGeneratingWithAI ? t('calendar.generating') : t('calendar.generate')}
            </button>
            <button
              onClick={() => setShowAIPanel(false)}
              className="px-2 py-1 rounded bg-gray-600 hover:bg-gray-500 text-white text-xs"
            >
  {t('calendar.cancel')}
            </button>
          </div>
        </div>
      )}

      <div className="flex-1 min-h-0">
        {isLoading && !events.length ? (
          <div className="h-full flex items-center justify-center text-gray-400 text-sm">
            {t('calendar.loading')}
          </div>
        ) : error ? (
          <div className="h-full flex items-center justify-center text-red-400 text-sm">
            {error}
          </div>
        ) : viewMode === 'calendar' ? (
          <CalendarView events={filteredEvents} />
        ) : groupedByDate.length === 0 ? (
          <div className="h-full flex items-center justify-center text-gray-500 text-sm">
            {t('calendar.no_events')}
          </div>
        ) : (
          <div className="h-full overflow-auto p-3 space-y-3">
            {groupedByDate.map(([date, items]) => (
              <div
                key={date}
                className="border border-slate-800 rounded-lg overflow-hidden bg-slate-900/60"
              >
                <div className="px-3 py-2 flex items-center justify-between border-b border-slate-800 bg-slate-900/80">
                  <span className="text-xs font-semibold text-gray-100">
                    {date}
                  </span>
                  <span className="text-[11px] text-gray-500">
                    {items[0]?.market || t('nav.market')} · {items.length} {t('calendar.events_count')}
                  </span>
                </div>
                <div className="divide-y divide-slate-800">
                  {items.map((e) => (
                    <div key={e.event_key} className="px-3 py-2 text-xs">
                      <div className="text-gray-200 mb-1 flex items-center gap-2">
                        {e.title}
                        {e.category && (e.category.includes('交割日') || e.category.includes('结算日')) && (
                          <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-red-500 text-white text-[10px] font-bold">
                            {e.category.includes('交割日') ? 'J' : 'S'}
                          </span>
                        )}
                        {(e.title.includes('期权') || e.title.includes('期货')) && (
                          <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-orange-500 text-white text-[10px] font-bold">
                            衍
                          </span>
                        )}
                        {(e.title.includes('月末') || e.title.includes('季度')) && (
                          <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-yellow-500 text-black text-[10px] font-bold">
                            结
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-gray-500 flex flex-wrap gap-2">
                        {e.category && <span>{t('calendar.category')}: {e.category}</span>}
                        {e.source && <span>{t('calendar.source')}: {e.source}</span>}
                        {e.details && <span>{t('calendar.details')}: {e.details}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
