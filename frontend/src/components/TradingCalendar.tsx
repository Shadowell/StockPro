import React, { useEffect, useMemo, useState } from "react";
import { getMarketCalendar, refreshMarketCalendar } from "@/api/client";
import { MarketCalendarEvent } from "@/types";
import { RefreshCw, CalendarDays, Grid3X3 } from "lucide-react";
import { CalendarView } from "./CalendarView";
import { getTranslation } from "../lib/i18n";
import { useStore } from "../stores/useStore";

type FilterPreset = "all" | "near" | "month";

export const TradingCalendar: React.FC = () => {
  const { language } = useStore();
  const [events, setEvents] = useState<MarketCalendarEvent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preset, setPreset] = useState<FilterPreset>("near");
  const [viewMode, setViewMode] = useState<'list' | 'calendar'>('calendar');

  const t = (key: any) => getTranslation(language, key);
  const today = useMemo(() => new Date(), []);

  const fetchEvents = async () => {
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
  };

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

  useEffect(() => {
    fetchEvents();
  }, []);

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
          <span className="text-sm font-semibold text-gray-100">
            {language === 'zh' ? '交易日历' : 'Trading Calendar'}
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {/* View mode toggle */}
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
          
          {/* Filter presets */}
          <div className="border-l border-slate-700 pl-2 ml-1 flex gap-1">
            <button
              onClick={() => setPreset("near")}
              className={`px-2 py-1 rounded-md ${
                preset === "near" ? "bg-blue-600 text-white" : "bg-slate-800 text-gray-300 hover:bg-slate-700"
              }`}
            >
              {language === 'zh' ? '近两周' : '2 Weeks'}
            </button>
            <button
              onClick={() => setPreset("month")}
              className={`px-2 py-1 rounded-md ${
                preset === "month" ? "bg-blue-600 text-white" : "bg-slate-800 text-gray-300 hover:bg-slate-700"
              }`}
            >
              {language === 'zh' ? '本月' : 'Month'}
            </button>
            <button
              onClick={() => setPreset("all")}
              className={`px-2 py-1 rounded-md ${
                preset === "all" ? "bg-blue-600 text-white" : "bg-slate-800 text-gray-300 hover:bg-slate-700"
              }`}
            >
              {language === 'zh' ? '全部' : 'All'}
            </button>
          </div>

          {/* Loading indicator */}
          {isRefreshing && (
            <RefreshCw size={14} className="animate-spin text-blue-400 ml-2" />
          )}
        </div>
      </div>

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
                    {items[0]?.market || t('nav.market')} · {items.length} {language === 'zh' ? '个事件' : 'events'}
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
                      </div>
                      <div className="text-[11px] text-gray-500 flex flex-wrap gap-2">
                        {e.category && <span>{language === 'zh' ? '分类' : 'Category'}: {e.category}</span>}
                        {e.details && <span>{language === 'zh' ? '详情' : 'Details'}: {e.details}</span>}
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
