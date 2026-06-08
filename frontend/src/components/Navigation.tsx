import type { ComponentType } from 'react';
import { NavLink } from 'react-router-dom';
import {
  Activity,
  BarChart3,
  Bell,
  BrainCircuit,
  CalendarDays,
  Code2,
  Database,
  FlaskConical,
  Gauge,
  LineChart,
  Newspaper,
  Radio,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import clsx from 'clsx';
import { useStore } from '../stores/useStore';

interface NavigationProps {
  orientation?: 'horizontal' | 'vertical';
}

type IconType = ComponentType<{ className?: string; size?: number | string }>;

type NavItem = {
  id: string;
  to: string;
  labelZh: string;
  labelEn: string;
  Icon: IconType;
  end?: boolean;
};

type NavGroup = {
  id: string;
  titleZh: string;
  titleEn: string;
  items: NavItem[];
};

export const NAV_GROUPS: NavGroup[] = [
  {
    id: 'dashboard',
    titleZh: '大盘驾驶舱',
    titleEn: 'Dashboard',
    items: [
      { id: 'dashboard', to: '/', labelZh: '大盘驾驶舱', labelEn: 'Dashboard', Icon: Gauge, end: true },
      { id: 'research-overview', to: '/research/overview', labelZh: '市场概览', labelEn: 'Market Overview', Icon: BarChart3 },
    ],
  },
  {
    id: 'market',
    titleZh: '行情',
    titleEn: 'Market',
    items: [
      { id: 'market', to: '/market', labelZh: '行情终端', labelEn: 'Market', Icon: LineChart },
      { id: 'data', to: '/data', labelZh: '数据中心', labelEn: 'Data Center', Icon: Database },
    ],
  },
  {
    id: 'research',
    titleZh: '研究工坊',
    titleEn: 'Research Lab',
    items: [
      { id: 'sentiment', to: '/sentiment', labelZh: '市场情绪', labelEn: 'Sentiment', Icon: Activity },
      { id: 'news', to: '/news', labelZh: '消息中心', labelEn: 'News', Icon: Newspaper },
      { id: 'ai', to: '/ai', labelZh: '智能选股', labelEn: 'AI Screener', Icon: BrainCircuit },
      { id: 'factors', to: '/factors', labelZh: '因子研究', labelEn: 'Factors', Icon: FlaskConical },
      { id: 'calendar', to: '/calendar', labelZh: '交易日历', labelEn: 'Calendar', Icon: CalendarDays },
    ],
  },
  {
    id: 'strategy',
    titleZh: '策略工厂',
    titleEn: 'Strategy Factory',
    items: [
      { id: 'strategy', to: '/strategy', labelZh: '策略开发', labelEn: 'Strategy', Icon: Code2 },
      { id: 'backtest', to: '/backtest', labelZh: '回测复盘', labelEn: 'Backtest', Icon: TrendingUp },
      { id: 'paper', to: '/paper', labelZh: '模拟盘', labelEn: 'Paper', Icon: Radio },
      { id: 'monitor', to: '/monitor', labelZh: '监控', labelEn: 'Monitor', Icon: Bell },
    ],
  },
  {
    id: 'ops',
    titleZh: '数据运维',
    titleEn: 'Operations',
    items: [
      { id: 'data-processing', to: '/data/processing', labelZh: '后台任务', labelEn: 'Ops', Icon: ShieldCheck },
    ],
  },
];

export const Navigation = ({ orientation = 'vertical' }: NavigationProps) => {
  const { language } = useStore();
  const isZh = language === 'zh';
  const vertical = orientation === 'vertical';

  return (
    <nav className={clsx(vertical ? 'space-y-4' : 'flex gap-2 overflow-x-auto pb-2')}>
      {NAV_GROUPS.map((group) => (
        <section
          key={group.id}
          className={clsx(
            vertical
              ? 'space-y-1.5'
              : 'flex min-w-max items-center gap-2 rounded-lg border border-crypto-border bg-crypto-bg/70 px-3 py-2',
          )}
        >
          <div
            className={clsx(
              'flex items-center gap-2 font-bold uppercase tracking-widest text-gray-500',
              vertical ? 'px-3 text-[10px]' : 'mr-1 text-[10px]',
            )}
          >
            <span>{isZh ? group.titleZh : group.titleEn}</span>
            {vertical && <span className="h-px min-w-0 flex-1 bg-crypto-border/70" />}
          </div>
          <div className={clsx(vertical ? 'space-y-1' : 'flex items-center gap-1')}>
            {group.items.map((item) => (
              <NavLink
                key={item.id}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  clsx(
                    'group flex items-center gap-2 rounded-md text-sm font-semibold transition-colors',
                    vertical ? 'px-3 py-2' : 'px-3 py-2',
                    isActive
                      ? 'border border-blue-500/25 bg-blue-500/10 text-blue-200 shadow-[inset_3px_0_0_rgba(59,130,246,0.75)]'
                      : 'border border-transparent text-gray-400 hover:border-crypto-border hover:bg-gray-800/70 hover:text-gray-100',
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <item.Icon className={clsx('h-4 w-4 shrink-0 transition-colors group-hover:text-gray-200', isActive ? 'text-blue-300' : 'text-gray-500')} />
                    <span className="truncate">{isZh ? item.labelZh : item.labelEn}</span>
                  </>
                )}
              </NavLink>
            ))}
          </div>
        </section>
      ))}
    </nav>
  );
};
