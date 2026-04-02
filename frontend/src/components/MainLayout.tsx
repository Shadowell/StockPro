import React from 'react';
import { Navigation } from './Navigation';
import { Activity, Languages } from 'lucide-react';
import { useStore } from '../stores/useStore';
import { getTranslation, TranslationKey } from '../lib/i18n';
import clsx from 'clsx';

interface MainLayoutProps {
  children: React.ReactNode;
  title?: string;
}

export const MainLayout: React.FC<MainLayoutProps> = ({ children, title }) => {
  const { 
    fetchMarketOverview,
    marketOverview,
    language, 
    setLanguage 
  } = useStore();

  const t = (key: TranslationKey) => getTranslation(language, key);

  // 10秒刷新一次市场指数
  React.useEffect(() => {
    // Initial fetch
    fetchMarketOverview();
    
    // Set up 10-second interval for market indices refresh
    const interval = setInterval(() => {
      fetchMarketOverview();
    }, 10000); // 10 seconds

    return () => clearInterval(interval);
  }, [fetchMarketOverview]);

  return (
    <div className="flex h-screen bg-[#0b0f19] text-slate-200 overflow-hidden font-sans">
      {/* Sidebar */}
      <aside className="w-64 bg-[#111827] border-r border-slate-800 flex flex-col">
        <div className="p-6 flex items-center gap-3">
          <div className="bg-blue-600 p-2 rounded-lg shadow-lg shadow-blue-900/20">
            <Activity className="text-white" size={24} />
          </div>
          <h1 className="text-xl font-bold tracking-tight bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">
            StockPro AI
          </h1>
        </div>
        
        <div className="flex-1 overflow-y-auto py-4 px-3">
          <Navigation orientation="vertical" />
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top Header - 简化版，只保留标题和市场指数 */}
        <header className="h-14 bg-[#111827]/80 backdrop-blur-md border-b border-slate-800 flex items-center justify-between px-6 z-10">
          <h2 className="text-lg font-semibold text-slate-100">
            {title || t('home.title')}
          </h2>

          {/* Market Tickers */}
          <div className="flex items-center gap-4 text-xs font-medium">
            {marketOverview?.indices.map((idx, i) => (
              <div key={i} className="flex flex-col">
                <span className="text-slate-500">{idx.name}</span>
                <span className={clsx(
                  "font-bold",
                  idx.change_amount >= 0 ? "text-red-500" : "text-green-500"
                )}>
                  {idx.price.toLocaleString()} ({idx.change_percent >= 0 ? '+' : ''}{idx.change_percent}%)
                </span>
              </div>
            ))}
            {marketOverview && (
              <div className="flex items-center gap-1.5 ml-2 px-2 py-1 rounded-full border border-slate-700">
                <span className={clsx(
                  "w-2 h-2 rounded-full",
                  marketOverview.is_open ? "bg-green-500 animate-pulse" : "bg-red-500"
                )}></span>
                <span className={clsx(
                  "text-[10px] font-bold",
                  marketOverview.is_open ? "text-green-400" : "text-red-400"
                )}>
                  {marketOverview.is_open ? (language === 'zh' ? '开市中' : 'Open') : (language === 'zh' ? '已休市' : 'Closed')}
                </span>
              </div>
            )}
            {/* 语言切换按钮 - 放在开市/休市状态后面 */}
            <button
              onClick={() => setLanguage(language === 'zh' ? 'en' : 'zh')}
              className="flex items-center gap-1 ml-2 px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 rounded text-[10px] font-bold uppercase tracking-tight transition-all border border-slate-700"
              title={language === 'zh' ? 'Switch to English' : '切换至中文'}
            >
              <Languages size={12} />
              <span>{language === 'zh' ? 'EN' : '中'}</span>
            </button>
            {!marketOverview && (
              <div className="text-slate-500 text-[10px]">{t('layout.loading_market')}</div>
            )}
          </div>
        </header>

        {/* Content Area */}
        <main className="flex-1 overflow-auto p-6 scrollbar-thin scrollbar-thumb-slate-800">
          {children}
        </main>
      </div>
    </div>
  );
};
