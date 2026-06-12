import React from 'react';
import { TradingCalendar } from '../components/TradingCalendar';
import { MainLayout } from '../components/MainLayout';
import { useStore } from '../stores/useStore';

export const TradingCalendarPage: React.FC = () => {
  const { language } = useStore();

  return (
    <div className="h-full relative">
      <TradingCalendar />
    </div>
  );
};
