import React, { useState, useMemo } from 'react';
import { ChevronLeft, ChevronRight, Calendar } from 'lucide-react';
import { MarketCalendarEvent } from '../types';
import { getTranslation, TranslationKey } from '../lib/i18n';
import { useStore } from '../stores/useStore';

interface CalendarViewProps {
  events: MarketCalendarEvent[];
}

interface CalendarDay {
  date: Date;
  isCurrentMonth: boolean;
  isToday: boolean;
  events: MarketCalendarEvent[];
}

export const CalendarView: React.FC<CalendarViewProps> = ({ events }) => {
  const { language } = useStore();
  const [currentDate, setCurrentDate] = useState(new Date());
  
  const t = (key: TranslationKey) => getTranslation(language, key);
  
  // 辅助函数：判断是否为今天
  const isToday = (date: Date): boolean => {
    const today = new Date();
    return date.getDate() === today.getDate() &&
           date.getMonth() === today.getMonth() &&
           date.getFullYear() === today.getFullYear();
  };

  // 辅助函数：获取指定日期的事件
  const getEventsForDate = (date: Date, events: MarketCalendarEvent[]): MarketCalendarEvent[] => {
    const dateString = date.toISOString().split('T')[0];
    return events.filter(event => event.event_date === dateString);
  };
  
  const monthYear = useMemo(() => {
    return currentDate.toLocaleDateString(language === 'zh' ? 'zh-CN' : 'en-US', { 
      year: 'numeric', 
      month: language === 'zh' ? 'long' : 'short'
    });
  }, [currentDate, language]);

  const calendarDays = useMemo(() => {
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();
    
    // 获取当月第一天和最后一天
    const firstDayOfMonth = new Date(year, month, 1);
    const lastDayOfMonth = new Date(year, month + 1, 0);
    
    // 获取当月第一天是星期几 (0=周日, 1=周一, ..., 6=周六)
    const firstDayOfWeek = firstDayOfMonth.getDay();
    
    // 获取当月天数
    const daysInMonth = lastDayOfMonth.getDate();
    
    // 构建日历数组
    const days: CalendarDay[] = [];
    
    // 添加上个月末尾的几天
    const prevMonthLastDay = new Date(year, month, 0).getDate();
    for (let i = firstDayOfWeek - 1; i >= 0; i--) {
      const date = new Date(year, month - 1, prevMonthLastDay - i);
      days.push({
        date,
        isCurrentMonth: false,
        isToday: isToday(date),
        events: getEventsForDate(date, events)
      });
    }
    
    // 添加当月的所有天
    for (let day = 1; day <= daysInMonth; day++) {
      const date = new Date(year, month, day);
      days.push({
        date,
        isCurrentMonth: true,
        isToday: isToday(date),
        events: getEventsForDate(date, events)
      });
    }
    
    // 添加下个月开头的几天，直到填满6行（42个格子）
    const totalCells = 42; // 6行 x 7列
    const remainingCells = totalCells - days.length;
    for (let day = 1; day <= remainingCells; day++) {
      const date = new Date(year, month + 1, day);
      days.push({
        date,
        isCurrentMonth: false,
        isToday: isToday(date),
        events: getEventsForDate(date, events)
      });
    }
    
    return days;
  }, [currentDate, events]);

  const goToPreviousMonth = () => {
    setCurrentDate(prev => new Date(prev.getFullYear(), prev.getMonth() - 1, 1));
  };

  const goToNextMonth = () => {
    setCurrentDate(prev => new Date(prev.getFullYear(), prev.getMonth() + 1, 1));
  };

  const goToToday = () => {
    setCurrentDate(new Date());
  };

  // 获取星期几的名称
  const weekdays = useMemo(() => {
    const baseDate = new Date();
    const days = [];
    for (let i = 0; i < 7; i++) {
      const date = new Date(baseDate.getFullYear(), baseDate.getMonth(), baseDate.getDate() - baseDate.getDay() + i);
      days.push(date.toLocaleDateString(language, { weekday: language === 'zh' ? 'narrow' : 'short' }));
    }
    return days;
  }, [language]);

  return (
    <div className="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      {/* 日历头部 - 月份导航 */}
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Calendar className="text-blue-400" size={18} />
          <span className="text-sm font-semibold text-gray-100">{monthYear}</span>
          <button
            onClick={goToToday}
            className="ml-2 px-2 py-1 text-xs rounded bg-blue-600 hover:bg-blue-500 text-white"
          >
            {t('calendar.today')}
          </button>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={goToPreviousMonth}
            className="p-1 rounded hover:bg-slate-800"
          >
            <ChevronLeft size={16} />
          </button>
          <button
            onClick={goToNextMonth}
            className="p-1 rounded hover:bg-slate-800"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {/* 星期标题 */}
      <div className="grid grid-cols-7 bg-slate-800 border-b border-slate-700">
        {weekdays.map((day, index) => (
          <div 
            key={index} 
            className="py-2 text-center text-xs font-semibold text-gray-400"
          >
            {day}
          </div>
        ))}
      </div>

      {/* 日历主体 */}
      <div className="grid grid-cols-7 flex-1 min-h-0">
        {calendarDays.map((day, index) => (
          <div
            key={index}
            className={`
              border-r border-b border-slate-800
              ${day.isCurrentMonth ? 'bg-slate-900' : 'bg-slate-950 text-gray-600'}
              ${day.isToday ? 'ring-2 ring-blue-500' : ''}
              flex flex-col
            `}
          >
            <div className="p-1 flex justify-end">
              <span className={`
                text-xs font-medium w-6 h-6 flex items-center justify-center rounded-full
                ${day.isToday ? 'bg-blue-500 text-white' : ''}
                ${!day.isCurrentMonth ? 'text-gray-500' : 'text-gray-300'}
              `}>
                {day.date.getDate()}
              </span>
            </div>
            <div className="flex-1 overflow-y-auto p-1 space-y-1 max-h-24">
              {day.events.slice(0, 3).map((event, idx) => (
                <div
                  key={idx}
                  className={`
                    text-[10px] px-1 py-0.5 rounded truncate
                    ${event.category?.includes('交割日') || event.category?.includes('结算日') 
                      ? 'bg-red-500/20 text-red-300 border border-red-500/30' 
                      : event.title.includes('期权') || event.title.includes('期货')
                      ? 'bg-orange-500/20 text-orange-300 border border-orange-500/30'
                      : event.title.includes('月末') || event.title.includes('季度')
                      ? 'bg-yellow-500/20 text-yellow-300 border border-yellow-500/30'
                      : 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                    }
                  `}
                  title={`${event.title} - ${event.category || ''}`}
                >
                  {event.title.length > 8 ? `${event.title.substring(0, 8)}...` : event.title}
                </div>
              ))}
              {day.events.length > 3 && (
                <div className="text-[9px] text-gray-500 px-1">
                  +{day.events.length - 3} {t('common.more')}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
