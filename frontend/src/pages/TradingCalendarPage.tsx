import React from 'react';
import { TradingCalendar } from '../components/TradingCalendar';
import { MainLayout } from '../components/MainLayout';
import { useStore } from '../stores/useStore';
import { getTranslation } from '../lib/i18n';

export const TradingCalendarPage: React.FC = () => {
  const { language } = useStore();
  const t = (key: any) => getTranslation(language, key);

  return (
    <MainLayout title={language === 'zh' ? '交易日历' : 'Trading Calendar'}>
      <div className="h-full">
        <div className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden shadow-2xl flex flex-col h-full">
          <div className="flex-1 overflow-hidden">
            <TradingCalendar />
          </div>
        </div>
      </div>
    </MainLayout>
  );
};
