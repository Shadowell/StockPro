import React, { useEffect, useMemo, useState, useCallback } from "react";
import { getMarketCalendar, refreshMarketCalendar } from "@/api/client";
import { MarketCalendarEvent } from "@/types";
import { 
  RefreshCw, 
  CalendarDays, 
  Grid3X3, 
  List, 
  ChevronLeft, 
  ChevronRight,
  Calendar,
  Bell,
  TrendingUp,
  AlertCircle,
  Clock,
  Search,
  X
} from "lucide-react";
import { useStore } from "../stores/useStore";

type FilterPreset = "all" | "near" | "month" | "upcoming";
type ViewMode = "calendar" | "list" | "timeline";

// 事件类型配置
const eventTypeConfig: Record<string, { color: string; bgColor: string; borderColor: string; icon: React.ReactNode }> = {
  '交割日': { color: 'text-red-400', bgColor: 'bg-red-500/20', borderColor: 'border-red-500/40', icon: <AlertCircle size={12} /> },
  '结算日': { color: 'text-orange-400', bgColor: 'bg-orange-500/20', borderColor: 'border-orange-500/40', icon: <Clock size={12} /> },
  '期权': { color: 'text-purple-400', bgColor: 'bg-purple-500/20', borderColor: 'border-purple-500/40', icon: <TrendingUp size={12} /> },
  '期货': { color: 'text-yellow-400', bgColor: 'bg-yellow-500/20', borderColor: 'border-yellow-500/40', icon: <TrendingUp size={12} /> },
  'IPO': { color: 'text-green-400', bgColor: 'bg-green-500/20', borderColor: 'border-green-500/40', icon: <Bell size={12} /> },
  '财报': { color: 'text-blue-400', bgColor: 'bg-blue-500/20', borderColor: 'border-blue-500/40', icon: <Calendar size={12} /> },
  '分红': { color: 'text-emerald-400', bgColor: 'bg-emerald-500/20', borderColor: 'border-emerald-500/40', icon: <TrendingUp size={12} /> },
  '默认': { color: 'text-slate-300', bgColor: 'bg-slate-500/20', borderColor: 'border-slate-500/40', icon: <Calendar size={12} /> },
};

// 获取事件类型配置
const getEventConfig = (event: MarketCalendarEvent) => {
  const category = event.category || '';
  const title = event.title || '';
  
  if (category.includes('交割日') || title.includes('交割')) {
    return eventTypeConfig['交割日'];
  }
  if (category.includes('结算日') || title.includes('结算')) {
    return eventTypeConfig['结算日'];
  }
  if (title.includes('期权')) {
    return eventTypeConfig['期权'];
  }
  if (title.includes('期货')) {
    return eventTypeConfig['期货'];
  }
  if (title.includes('IPO') || title.includes('申购')) {
    return eventTypeConfig['IPO'];
  }
  if (title.includes('财报') || title.includes('业绩')) {
    return eventTypeConfig['财报'];
  }
  if (title.includes('分红') || title.includes('派息')) {
    return eventTypeConfig['分红'];
  }
  return eventTypeConfig['默认'];
};

// 日历单元格数据结构
interface CalendarDay {
  date: Date;
  dateStr: string;
  isCurrentMonth: boolean;
  isToday: boolean;
  isWeekend: boolean;
  events: MarketCalendarEvent[];
}

export const TradingCalendar: React.FC = () => {
  const { language } = useStore();
  const [events, setEvents] = useState<MarketCalendarEvent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preset, setPreset] = useState<FilterPreset>("month");
  const [viewMode, setViewMode] = useState<ViewMode>("calendar");
  const [currentDate, setCurrentDate] = useState(new Date());
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [showSearch, setShowSearch] = useState(false);

  const today = useMemo(() => new Date(), []);
  const todayStr = useMemo(() => today.toISOString().split('T')[0], [today]);

  // 获取事件数据
  const fetchEvents = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await getMarketCalendar({ limit: 500 });
      setEvents(res);
    } catch (e) {
      console.error("Failed to fetch market calendar", e);
      setError(language === 'zh' ? '加载失败，请重试' : 'Failed to load');
    } finally {
      setIsLoading(false);
    }
  }, [language]);

  // 刷新数据
  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await refreshMarketCalendar(6);
      await fetchEvents();
    } catch (e) {
      console.error("Failed to refresh market calendar", e);
      setError(language === 'zh' ? '刷新失败，请重试' : 'Refresh failed');
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  // 月份年份显示
  const monthYear = useMemo(() => {
    return currentDate.toLocaleDateString(language === 'zh' ? 'zh-CN' : 'en-US', { 
      year: 'numeric', 
      month: 'long'
    });
  }, [currentDate, language]);

  // 星期标题
  const weekdays = useMemo(() => {
    if (language === 'zh') {
      return ['日', '一', '二', '三', '四', '五', '六'];
    }
    return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  }, [language]);

  // 生成日历数据
  const calendarDays = useMemo((): CalendarDay[] => {
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();
    
    const firstDayOfMonth = new Date(year, month, 1);
    const lastDayOfMonth = new Date(year, month + 1, 0);
    const firstDayOfWeek = firstDayOfMonth.getDay();
    const daysInMonth = lastDayOfMonth.getDate();
    
    const days: CalendarDay[] = [];
    
    // 添加上个月末尾的几天
    const prevMonthLastDay = new Date(year, month, 0).getDate();
    for (let i = firstDayOfWeek - 1; i >= 0; i--) {
      const date = new Date(year, month - 1, prevMonthLastDay - i);
      const dateStr = date.toISOString().split('T')[0];
      const dayOfWeek = date.getDay();
      days.push({
        date,
        dateStr,
        isCurrentMonth: false,
        isToday: dateStr === todayStr,
        isWeekend: dayOfWeek === 0 || dayOfWeek === 6,
        events: events.filter(e => e.event_date === dateStr)
      });
    }
    
    // 添加当月的所有天
    for (let day = 1; day <= daysInMonth; day++) {
      const date = new Date(year, month, day);
      const dateStr = date.toISOString().split('T')[0];
      const dayOfWeek = date.getDay();
      days.push({
        date,
        dateStr,
        isCurrentMonth: true,
        isToday: dateStr === todayStr,
        isWeekend: dayOfWeek === 0 || dayOfWeek === 6,
        events: events.filter(e => e.event_date === dateStr)
      });
    }
    
    // 补齐到6行
    const totalCells = 42;
    const remainingCells = totalCells - days.length;
    for (let day = 1; day <= remainingCells; day++) {
      const date = new Date(year, month + 1, day);
      const dateStr = date.toISOString().split('T')[0];
      const dayOfWeek = date.getDay();
      days.push({
        date,
        dateStr,
        isCurrentMonth: false,
        isToday: dateStr === todayStr,
        isWeekend: dayOfWeek === 0 || dayOfWeek === 6,
        events: events.filter(e => e.event_date === dateStr)
      });
    }
    
    return days;
  }, [currentDate, events, todayStr]);

  // 过滤事件
  const filteredEvents = useMemo(() => {
    let result = events.slice().sort((a, b) => a.event_date.localeCompare(b.event_date));
    
    // 按搜索词过滤
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      result = result.filter(e => 
        e.title.toLowerCase().includes(query) ||
        e.category?.toLowerCase().includes(query) ||
        e.details?.toLowerCase().includes(query)
      );
    }

    // 按预设过滤
    if (preset === "near") {
      const windowDays = 14;
      result = result.filter((e) => {
        const d = new Date(e.event_date);
        const diff = (d.getTime() - today.getTime()) / (1000 * 60 * 60 * 24);
        return diff >= -3 && diff <= windowDays;
      });
    } else if (preset === "month") {
      const year = currentDate.getFullYear();
      const month = currentDate.getMonth();
      result = result.filter((e) => {
        const d = new Date(e.event_date);
        return d.getFullYear() === year && d.getMonth() === month;
      });
    } else if (preset === "upcoming") {
      result = result.filter((e) => {
        const d = new Date(e.event_date);
        return d >= today;
      });
    }

    return result;
  }, [events, preset, today, currentDate, searchQuery]);

  // 按日期分组事件
  const groupedEvents = useMemo(() => {
    const map: Record<string, MarketCalendarEvent[]> = {};
    for (const e of filteredEvents) {
      if (!map[e.event_date]) {
        map[e.event_date] = [];
      }
      map[e.event_date].push(e);
    }
    return Object.entries(map).sort(([d1], [d2]) => d1.localeCompare(d2));
  }, [filteredEvents]);

  // 选中日期的事件
  const selectedDateEvents = useMemo(() => {
    if (!selectedDate) return [];
    return events.filter(e => e.event_date === selectedDate);
  }, [selectedDate, events]);

  // 导航函数
  const goToPreviousMonth = () => {
    setCurrentDate(prev => new Date(prev.getFullYear(), prev.getMonth() - 1, 1));
  };

  const goToNextMonth = () => {
    setCurrentDate(prev => new Date(prev.getFullYear(), prev.getMonth() + 1, 1));
  };

  const goToToday = () => {
    setCurrentDate(new Date());
    setSelectedDate(todayStr);
  };

  // 格式化日期显示
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const dayOfWeek = date.toLocaleDateString(language === 'zh' ? 'zh-CN' : 'en-US', { weekday: 'short' });
    const monthDay = date.toLocaleDateString(language === 'zh' ? 'zh-CN' : 'en-US', { 
      month: 'short', 
      day: 'numeric' 
    });
    return { dayOfWeek, monthDay };
  };

  // 判断日期是否是今天
  const isDateToday = (dateStr: string) => dateStr === todayStr;

  // 判断日期是否已过去
  const isDatePast = (dateStr: string) => new Date(dateStr) < today;

  return (
    <div className="flex flex-col h-full bg-slate-900 overflow-hidden">
      {/* 顶部工具栏 */}
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/95 backdrop-blur-sm">
        <div className="flex items-center justify-between">
          {/* 左侧：标题和月份导航 */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <CalendarDays className="text-blue-400" size={20} />
              <span className="text-base font-semibold text-white">
                {language === 'zh' ? '交易日历' : 'Trading Calendar'}
              </span>
            </div>
            
            {viewMode === 'calendar' && (
              <div className="flex items-center gap-2 ml-4">
                <button
                  onClick={goToPreviousMonth}
                  className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
                >
                  <ChevronLeft size={18} />
                </button>
                <span className="text-sm font-medium text-white min-w-[120px] text-center">
                  {monthYear}
                </span>
                <button
                  onClick={goToNextMonth}
                  className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
                >
                  <ChevronRight size={18} />
                </button>
                <button
                  onClick={goToToday}
                  className="ml-2 px-3 py-1 text-xs rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors"
                >
                  {language === 'zh' ? '今天' : 'Today'}
                </button>
              </div>
            )}
          </div>

          {/* 右侧：视图切换和筛选 */}
          <div className="flex items-center gap-2">
            {/* 搜索 */}
            {showSearch ? (
              <div className="flex items-center gap-2 bg-slate-800 rounded-lg px-3 py-1">
                <Search size={14} className="text-slate-400" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder={language === 'zh' ? '搜索事件...' : 'Search events...'}
                  className="bg-transparent border-none outline-none text-sm text-white placeholder-slate-500 w-40"
                  autoFocus
                />
                <button onClick={() => { setShowSearch(false); setSearchQuery(''); }}>
                  <X size={14} className="text-slate-400 hover:text-white" />
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowSearch(true)}
                className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
              >
                <Search size={16} />
              </button>
            )}

            {/* 视图切换 */}
            <div className="flex items-center bg-slate-800 rounded-lg p-1">
              <button
                onClick={() => setViewMode('calendar')}
                className={`p-1.5 rounded-md transition-colors ${
                  viewMode === 'calendar' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'
                }`}
                title={language === 'zh' ? '日历视图' : 'Calendar View'}
              >
                <Grid3X3 size={16} />
              </button>
              <button
                onClick={() => setViewMode('list')}
                className={`p-1.5 rounded-md transition-colors ${
                  viewMode === 'list' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'
                }`}
                title={language === 'zh' ? '列表视图' : 'List View'}
              >
                <List size={16} />
              </button>
              <button
                onClick={() => setViewMode('timeline')}
                className={`p-1.5 rounded-md transition-colors ${
                  viewMode === 'timeline' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'
                }`}
                title={language === 'zh' ? '时间轴视图' : 'Timeline View'}
              >
                <CalendarDays size={16} />
              </button>
            </div>

            {/* 筛选器 */}
            <div className="flex items-center bg-slate-800 rounded-lg p-1">
              {[
                { key: 'near', label: language === 'zh' ? '近期' : '2 Weeks' },
                { key: 'month', label: language === 'zh' ? '本月' : 'Month' },
                { key: 'upcoming', label: language === 'zh' ? '未来' : 'Upcoming' },
                { key: 'all', label: language === 'zh' ? '全部' : 'All' },
              ].map(({ key, label }) => (
                <button
                  key={key}
                  onClick={() => setPreset(key as FilterPreset)}
                  className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                    preset === key ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            {/* 刷新按钮 */}
            <button
              onClick={handleRefresh}
              disabled={isRefreshing}
              className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white disabled:opacity-50 transition-colors"
              title={language === 'zh' ? '刷新数据' : 'Refresh'}
            >
              <RefreshCw size={16} className={isRefreshing ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>
      </div>

      {/* 主内容区 */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {isLoading && !events.length ? (
          <div className="h-full flex items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <RefreshCw className="animate-spin text-blue-400" size={32} />
              <span className="text-slate-400 text-sm">
                {language === 'zh' ? '加载中...' : 'Loading...'}
              </span>
            </div>
          </div>
        ) : error ? (
          <div className="h-full flex items-center justify-center">
            <div className="flex flex-col items-center gap-3 text-red-400">
              <AlertCircle size={32} />
              <span className="text-sm">{error}</span>
              <button
                onClick={fetchEvents}
                className="px-4 py-2 bg-red-600 hover:bg-red-500 rounded-lg text-white text-sm"
              >
                {language === 'zh' ? '重试' : 'Retry'}
              </button>
            </div>
          </div>
        ) : viewMode === 'calendar' ? (
          /* 日历视图 */
          <div className="h-full flex flex-col">
            {/* 星期标题 */}
            <div className="grid grid-cols-7 bg-slate-800/50 border-b border-slate-700">
              {weekdays.map((day, index) => (
                <div 
                  key={index} 
                  className={`py-2.5 text-center text-xs font-semibold ${
                    index === 0 || index === 6 ? 'text-slate-500' : 'text-slate-400'
                  }`}
                >
                  {day}
                </div>
              ))}
            </div>

            {/* 日历主体 */}
            <div className="flex-1 grid grid-cols-7 grid-rows-6 min-h-0">
              {calendarDays.map((day, index) => (
                <div
                  key={index}
                  onClick={() => setSelectedDate(day.dateStr)}
                  className={`
                    border-r border-b border-slate-800 cursor-pointer
                    transition-colors relative overflow-hidden
                    ${day.isCurrentMonth ? 'bg-slate-900' : 'bg-slate-950'}
                    ${day.isToday ? 'ring-2 ring-blue-500 ring-inset' : ''}
                    ${selectedDate === day.dateStr ? 'bg-blue-900/30' : 'hover:bg-slate-800/50'}
                    ${day.isWeekend && day.isCurrentMonth ? 'bg-slate-900/70' : ''}
                  `}
                >
                  {/* 日期数字 */}
                  <div className="p-1.5 flex justify-end">
                    <span className={`
                      text-xs font-medium w-6 h-6 flex items-center justify-center rounded-full
                      ${day.isToday ? 'bg-blue-500 text-white font-bold' : ''}
                      ${!day.isCurrentMonth ? 'text-slate-600' : day.isWeekend ? 'text-slate-400' : 'text-slate-300'}
                    `}>
                      {day.date.getDate()}
                    </span>
                  </div>
                  
                  {/* 事件列表 */}
                  <div className="px-1 pb-1 space-y-0.5 overflow-hidden" style={{ maxHeight: 'calc(100% - 32px)' }}>
                    {day.events.slice(0, 3).map((event, idx) => {
                      const config = getEventConfig(event);
                      return (
                        <div
                          key={idx}
                          className={`
                            text-[10px] px-1.5 py-0.5 rounded truncate
                            ${config.bgColor} ${config.color} border ${config.borderColor}
                          `}
                          title={`${event.title}${event.category ? ` - ${event.category}` : ''}`}
                        >
                          {event.title.length > 10 ? `${event.title.substring(0, 10)}...` : event.title}
                        </div>
                      );
                    })}
                    {day.events.length > 3 && (
                      <div className="text-[9px] text-slate-500 px-1">
                        +{day.events.length - 3} {language === 'zh' ? '更多' : 'more'}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : viewMode === 'list' ? (
          /* 列表视图 */
          <div className="h-full overflow-auto p-4">
            {groupedEvents.length === 0 ? (
              <div className="h-full flex items-center justify-center text-slate-500">
                <div className="flex flex-col items-center gap-2">
                  <Calendar size={40} className="opacity-50" />
                  <span>{language === 'zh' ? '暂无事件' : 'No events'}</span>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                {groupedEvents.map(([date, items]) => {
                  const { dayOfWeek, monthDay } = formatDate(date);
                  const isPast = isDatePast(date);
                  const isToday = isDateToday(date);
                  
                  return (
                    <div
                      key={date}
                      className={`
                        rounded-xl overflow-hidden border transition-all
                        ${isToday ? 'border-blue-500 bg-blue-500/10' : 'border-slate-800 bg-slate-800/30'}
                        ${isPast && !isToday ? 'opacity-60' : ''}
                      `}
                    >
                      <div className={`
                        px-4 py-3 flex items-center justify-between border-b
                        ${isToday ? 'border-blue-500/30 bg-blue-500/10' : 'border-slate-700 bg-slate-800/50'}
                      `}>
                        <div className="flex items-center gap-3">
                          <div className={`
                            w-12 h-12 rounded-lg flex flex-col items-center justify-center
                            ${isToday ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-300'}
                          `}>
                            <span className="text-[10px] uppercase">{dayOfWeek}</span>
                            <span className="text-lg font-bold">{new Date(date).getDate()}</span>
                          </div>
                          <div>
                            <div className={`text-sm font-medium ${isToday ? 'text-blue-400' : 'text-white'}`}>
                              {monthDay}
                              {isToday && (
                                <span className="ml-2 px-2 py-0.5 bg-blue-600 rounded text-[10px] text-white">
                                  {language === 'zh' ? '今天' : 'TODAY'}
                                </span>
                              )}
                            </div>
                            <div className="text-xs text-slate-500">
                              {items.length} {language === 'zh' ? '个事件' : 'events'}
                            </div>
                          </div>
                        </div>
                      </div>
                      <div className="divide-y divide-slate-800">
                        {items.map((event) => {
                          const config = getEventConfig(event);
                          return (
                            <div key={event.event_key} className="px-4 py-3 hover:bg-slate-800/30 transition-colors">
                              <div className="flex items-start gap-3">
                                <div className={`p-2 rounded-lg ${config.bgColor} ${config.color}`}>
                                  {config.icon}
                                </div>
                                <div className="flex-1 min-w-0">
                                  <div className="text-sm text-white font-medium">{event.title}</div>
                                  <div className="mt-1 flex flex-wrap gap-2 text-xs">
                                    {event.category && (
                                      <span className={`px-2 py-0.5 rounded ${config.bgColor} ${config.color}`}>
                                        {event.category}
                                      </span>
                                    )}
                                    {event.market && (
                                      <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-400">
                                        {event.market}
                                      </span>
                                    )}
                                  </div>
                                  {event.details && (
                                    <div className="mt-2 text-xs text-slate-500">{event.details}</div>
                                  )}
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ) : (
          /* 时间轴视图 */
          <div className="h-full overflow-auto p-4">
            {groupedEvents.length === 0 ? (
              <div className="h-full flex items-center justify-center text-slate-500">
                <div className="flex flex-col items-center gap-2">
                  <Calendar size={40} className="opacity-50" />
                  <span>{language === 'zh' ? '暂无事件' : 'No events'}</span>
                </div>
              </div>
            ) : (
              <div className="relative">
                {/* 时间轴线 */}
                <div className="absolute left-[60px] top-0 bottom-0 w-px bg-slate-700" />
                
                <div className="space-y-6">
                  {groupedEvents.map(([date, items]) => {
                    const { monthDay } = formatDate(date);
                    const isPast = isDatePast(date);
                    const isToday = isDateToday(date);
                    
                    return (
                      <div key={date} className={`relative pl-24 ${isPast && !isToday ? 'opacity-60' : ''}`}>
                        {/* 日期标记 */}
                        <div className="absolute left-0 w-[52px] text-right">
                          <div className={`text-xs ${isToday ? 'text-blue-400 font-bold' : 'text-slate-500'}`}>
                            {monthDay}
                          </div>
                        </div>
                        
                        {/* 时间轴节点 */}
                        <div className={`
                          absolute left-[56px] top-0 w-2.5 h-2.5 rounded-full border-2
                          ${isToday ? 'bg-blue-500 border-blue-400' : 'bg-slate-800 border-slate-600'}
                        `} />
                        
                        {/* 事件卡片 */}
                        <div className="space-y-2">
                          {items.map((event) => {
                            const config = getEventConfig(event);
                            return (
                              <div
                                key={event.event_key}
                                className={`
                                  p-3 rounded-lg border transition-all hover:scale-[1.01]
                                  ${config.bgColor} ${config.borderColor}
                                `}
                              >
                                <div className="flex items-center gap-2">
                                  <span className={config.color}>{config.icon}</span>
                                  <span className={`text-sm font-medium ${config.color}`}>{event.title}</span>
                                </div>
                                {event.category && (
                                  <div className="mt-1 text-xs text-slate-500">{event.category}</div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 选中日期的事件详情弹窗 */}
      {selectedDate && selectedDateEvents.length > 0 && viewMode === 'calendar' && (
        <div className="absolute bottom-4 right-4 w-80 max-h-80 bg-slate-800 border border-slate-700 rounded-xl shadow-2xl overflow-hidden z-10">
          <div className="px-4 py-3 bg-slate-900 border-b border-slate-700 flex items-center justify-between">
            <span className="text-sm font-medium text-white">
              {formatDate(selectedDate).monthDay}
              {isDateToday(selectedDate) && (
                <span className="ml-2 px-2 py-0.5 bg-blue-600 rounded text-[10px]">
                  {language === 'zh' ? '今天' : 'TODAY'}
                </span>
              )}
            </span>
            <button
              onClick={() => setSelectedDate(null)}
              className="p-1 rounded hover:bg-slate-700"
            >
              <X size={14} className="text-slate-400" />
            </button>
          </div>
          <div className="overflow-auto max-h-60 divide-y divide-slate-700">
            {selectedDateEvents.map((event) => {
              const config = getEventConfig(event);
              return (
                <div key={event.event_key} className="px-4 py-3 hover:bg-slate-700/50">
                  <div className="flex items-start gap-2">
                    <span className={config.color}>{config.icon}</span>
                    <div className="flex-1">
                      <div className={`text-sm font-medium ${config.color}`}>{event.title}</div>
                      {event.category && (
                        <div className="text-xs text-slate-500 mt-1">{event.category}</div>
                      )}
                      {event.details && (
                        <div className="text-xs text-slate-400 mt-1">{event.details}</div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 底部统计栏 */}
      <div className="px-4 py-2 border-t border-slate-800 bg-slate-900/95 flex items-center justify-between text-xs text-slate-500">
        <div className="flex items-center gap-4">
          <span>
            {language === 'zh' ? '共' : 'Total'} {filteredEvents.length} {language === 'zh' ? '个事件' : 'events'}
          </span>
          {searchQuery && (
            <span className="text-blue-400">
              {language === 'zh' ? '搜索:' : 'Search:'} "{searchQuery}"
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {/* 图例 */}
          {Object.entries(eventTypeConfig).slice(0, 4).map(([type, config]) => (
            <div key={type} className="flex items-center gap-1">
              <div className={`w-2 h-2 rounded-full ${config.bgColor.replace('/20', '')}`} />
              <span>{type}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
