import React from 'react';
import { NewsFeed } from '../components/NewsFeed';
import { MainLayout } from '../components/MainLayout';
import { useStore } from '../stores/useStore';

export const NewsCalendar: React.FC = () => {
  const { language } = useStore();

  return (
    <MainLayout title={language === 'zh' ? '消息流' : 'News Feed'}>
      <div className="h-full">
        <div className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden shadow-2xl flex flex-col h-full">
          <div className="px-6 py-4 border-b border-slate-800 bg-[#0d121f]">
            <h2 className="text-sm font-black uppercase tracking-widest text-slate-100">
              {language === 'zh' ? '7x24 实时快讯' : '7x24 News Feed'}
            </h2>
          </div>
          <div className="flex-1 overflow-hidden">
            <NewsFeed />
          </div>
        </div>
      </div>
    </MainLayout>
  );
};
