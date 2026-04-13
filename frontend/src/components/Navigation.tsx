import React, { useMemo } from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  BarChart2,
  BrainCircuit,
  Newspaper,
  Activity,
  CalendarDays,
  Code,
  Zap,
  FlaskConical,
  Wallet,
  Search,
  ShieldCheck,
  Microscope,
} from 'lucide-react';
import { useStore } from '../stores/useStore';
import clsx from 'clsx';

interface NavigationProps {
  orientation?: 'horizontal' | 'vertical';
}

type NavItem = {
  id: string;
  to: string;
  label: string;
  Icon: React.ComponentType<{ size?: string | number; className?: string }>;
};

type NavGroup = {
  id: string;
  title: string;
  items: NavItem[];
};

export const Navigation: React.FC<NavigationProps> = ({ orientation = 'horizontal' }) => {
  const { language } = useStore();

  const groups: NavGroup[] = useMemo(
    () => [
      {
        id: 'data-hub',
        title: language === 'zh' ? '数据中台' : 'Data Hub',
        items: [
          { id: 'dashboard', to: '/', label: language === 'zh' ? '总览看板' : 'Dashboard', Icon: LayoutDashboard },
        ],
      },
      {
        id: 'research-lab',
        title: language === 'zh' ? '研究工坊' : 'Research Lab',
        items: [
          { id: 'market-overview', to: '/market', label: language === 'zh' ? '市场概览' : 'Market', Icon: BarChart2 },
          { id: 'sentiment-analysis', to: '/sentiment', label: language === 'zh' ? '市场情绪' : 'Sentiment', Icon: Activity },
          { id: 'news-feed', to: '/news', label: language === 'zh' ? '消息中心' : 'News', Icon: Newspaper },
          { id: 'ai-analysis', to: '/ai', label: language === 'zh' ? 'AI 研究' : 'AI Research', Icon: BrainCircuit },
          { id: 'stock-screener', to: '/screener', label: language === 'zh' ? '智能选股' : 'Screener', Icon: Search },
          { id: 'factor-library', to: '/factors', label: language === 'zh' ? '因子研究' : 'Factor Lab', Icon: FlaskConical },
          { id: 'trading-calendar', to: '/calendar', label: language === 'zh' ? '交易日历' : 'Calendar', Icon: CalendarDays },
        ],
      },
      {
        id: 'strategy-factory',
        title: language === 'zh' ? '策略工厂' : 'Strategy Factory',
        items: [
          { id: 'strategy-dev', to: '/strategy-dev', label: language === 'zh' ? '策略开发' : 'Strategy Dev', Icon: Code },
          { id: 'strategy-exec', to: '/strategy-exec', label: language === 'zh' ? '策略执行' : 'Strategy Exec', Icon: Zap },
          { id: 'market-pulse', to: '/pulse', label: language === 'zh' ? '复盘中心' : 'Review Center', Icon: Microscope },
        ],
      },
      {
        id: 'execution-risk',
        title: language === 'zh' ? '执行风控' : 'Execution & Risk',
        items: [{ id: 'live-trading', to: '/trading', label: language === 'zh' ? '实盘交易' : 'Live Trading', Icon: Wallet }],
      },
    ],
    [language]
  );

  const isVertical = orientation === 'vertical';

  return (
    <nav className={clsx('flex gap-3', isVertical ? 'flex-col' : 'flex-row')}>
      {groups.map((group) => (
        <div
          key={group.id}
          className={clsx(
            'min-w-0',
            isVertical ? 'rounded-lg border border-slate-800 bg-slate-900/30' : 'flex items-center gap-2'
          )}
        >
          <div
            className={clsx(
              'text-[11px] uppercase tracking-wider font-bold text-slate-500',
              isVertical ? 'px-3 py-2 border-b border-slate-800 flex items-center gap-1' : 'px-2'
            )}
          >
            {group.id === 'execution-risk' && <ShieldCheck size={11} />}
            {group.title}
          </div>
          <div className={clsx('flex', isVertical ? 'flex-col p-2 gap-1' : 'flex-row gap-2')}>
            {group.items.map((item) => (
              <NavLink
                key={item.id}
                to={item.to}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-2 px-3 py-2 rounded-md transition-colors text-sm',
                    isActive
                      ? 'bg-blue-600/15 text-blue-300 border border-blue-500/30'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                  )
                }
              >
                <item.Icon size={16} />
                <span>{item.label}</span>
              </NavLink>
            ))}
          </div>
        </div>
      ))}
    </nav>
  );
};
