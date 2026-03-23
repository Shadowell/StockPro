import React from 'react';
import { TradingCalendar } from '../components/TradingCalendar';
import { MainLayout } from '../components/MainLayout';
import { useStore } from '../stores/useStore';

export const TradingCalendarPage: React.FC = () => {
  const { language } = useStore();

  return (
    <MainLayout title={language === 'zh' ? '交易日历' : 'Trading Calendar'}>
      <div className="h-full relative">
        <TradingCalendar />
      </div>
    </MainLayout>
  );
};
