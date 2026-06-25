import type { ComponentType } from 'react';
import { NavLink } from 'react-router-dom';
import {
  Activity,
  BarChart3,
  Bot,
  CalendarDays,
  Code2,
  Grid2X2,
  LineChart,
  Newspaper,
  NotebookPen,
  Shield,
  ShieldCheck,
  Sparkles,
  TestTube2,
  WalletCards,
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
    id: 'research-workshop',
    titleZh: '研究工坊',
    titleEn: 'Research Studio',
    items: [
      { id: 'dashboard', to: '/', labelZh: '总览看板', labelEn: 'Overview', Icon: Grid2X2, end: true },
      { id: 'research-overview', to: '/research/overview', labelZh: '市场概览', labelEn: 'Market Overview', Icon: BarChart3 },
      { id: 'sentiment', to: '/sentiment', labelZh: '市场情绪', labelEn: 'Market Sentiment', Icon: Activity },
      { id: 'news', to: '/news', labelZh: '消息中心', labelEn: 'News Center', Icon: Newspaper },
      { id: 'ai', to: '/ai', labelZh: '智能选股', labelEn: 'AI Screener', Icon: Bot },
      { id: 'factors', to: '/factors', labelZh: '因子研究', labelEn: 'Factor Lab', Icon: TestTube2 },
      { id: 'calendar', to: '/calendar', labelZh: '交易日历', labelEn: 'Calendar', Icon: CalendarDays },
    ],
  },
  {
    id: 'strategy-factory',
    titleZh: '策略工厂',
    titleEn: 'Strategy Factory',
    items: [
      { id: 'strategy', to: '/strategy', labelZh: '策略开发', labelEn: 'Strategy Dev', Icon: Code2 },
      { id: 'execution', to: '/paper?tab=execution', labelZh: '策略执行', labelEn: 'Execution', Icon: Sparkles },
      { id: 'backtest', to: '/backtest', labelZh: '回测中心', labelEn: 'Backtest Center', Icon: LineChart },
      { id: 'review', to: '/review', labelZh: '复盘中心', labelEn: 'Review Center', Icon: NotebookPen },
    ],
  },
  {
    id: 'risk-control',
    titleZh: '执行风控',
    titleEn: 'Risk Control',
    items: [
      { id: 'paper', to: '/paper', labelZh: '模拟/实盘交易', labelEn: 'Paper / Live', Icon: WalletCards },
      { id: 'monitor', to: '/monitor', labelZh: '运行风控', labelEn: 'Runtime Risk', Icon: Shield },
    ],
  },
  {
    id: 'system-admin',
    titleZh: '系统管理',
    titleEn: 'System Admin',
    items: [
      { id: 'admin', to: '/data', labelZh: '管理后台', labelEn: 'Admin Console', Icon: ShieldCheck },
    ],
  },
];

export const Navigation = ({ orientation = 'vertical' }: NavigationProps) => {
  const { language } = useStore();
  const isZh = language === 'zh';
  const vertical = orientation === 'vertical';

  return (
    <nav className={clsx(vertical ? 'space-y-3' : 'flex gap-2 overflow-x-auto pb-2')}>
      {NAV_GROUPS.map((group) => (
        <section
          key={group.id}
          className={clsx(
            vertical
              ? 'overflow-hidden rounded-[10px] border border-crypto-border bg-crypto-card'
              : 'flex min-w-max items-center gap-1 rounded-[10px] border border-crypto-border bg-crypto-card p-1',
          )}
        >
          {vertical ? (
            <div className="border-b border-crypto-border px-3 py-2.5">
              <span className="block truncate text-[12px] font-bold text-slate-500">{isZh ? group.titleZh : group.titleEn}</span>
            </div>
          ) : null}

          <div className={clsx(vertical ? 'space-y-1 p-2' : 'flex items-center gap-1')}>
            {group.items.map((item) => (
              <NavLink
                key={item.id}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  clsx(
                    'group flex min-w-0 items-center gap-2 rounded-[7px] border text-sm font-semibold transition-colors',
                    vertical ? 'h-10 px-2.5' : 'h-10 px-3',
                    isActive
                      ? 'border-blue-500/55 bg-blue-600/18 text-blue-200 shadow-[inset_0_0_0_1px_rgba(96,165,250,0.08)]'
                      : 'border-transparent text-slate-400 hover:border-crypto-border hover:bg-slate-800/65 hover:text-slate-100',
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <span
                      className={clsx(
                        'flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-colors',
                        isActive ? 'text-blue-200' : 'text-slate-500 group-hover:text-slate-300',
                      )}
                    >
                      <item.Icon className="h-4 w-4" />
                    </span>
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
