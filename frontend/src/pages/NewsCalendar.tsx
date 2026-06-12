import React from 'react';
import { NewsFeed } from '../components/NewsFeed';
import { MainLayout } from '../components/MainLayout';
import { useStore } from '../stores/useStore';

export const NewsCalendar: React.FC = () => {
  const { language } = useStore();

  return (
    <div className="h-full">
      <div className="bg-crypto-card border border-crypto-border rounded-xl overflow-hidden flex flex-col h-full">
        <div className="px-6 py-4 border-b border-crypto-border bg-crypto-bg">
          <h2 className="text-sm font-black uppercase tracking-widest text-slate-100">
            {language === 'zh' ? '7x24 实时快讯' : '7x24 News Feed'}
          </h2>
        </div>
        <div className="flex-1 overflow-hidden">
          <NewsFeed />
        </div>
      </div>
    </div>
  );
};
