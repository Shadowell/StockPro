import type { ComponentType } from 'react';
import { NavLink } from 'react-router-dom';
import {
  BarChart3,
  Code2,
  Eye,
  Grid2X2,
  LineChart,
  Layers3,
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
      { id: 'market', to: '/market', labelZh: '市场研究', labelEn: 'Market Research', Icon: BarChart3 },
      { id: 'pools', to: '/pools', labelZh: '股票池', labelEn: 'Stock Pools', Icon: Layers3 },
      { id: 'factors', to: '/factors', labelZh: '因子研究', labelEn: 'Factor Lab', Icon: TestTube2 },
    ],
  },
  {
    id: 'strategy-factory',
    titleZh: '策略工厂',
    titleEn: 'Strategy Factory',
    items: [
      { id: 'strategy', to: '/strategy', labelZh: '策略开发', labelEn: 'Strategy Dev', Icon: Code2 },
      { id: 'backtest', to: '/backtest', labelZh: '回测中心', labelEn: 'Backtest Center', Icon: LineChart },
      { id: 'ai-lab', to: '/ai-lab', labelZh: 'AI 研发', labelEn: 'AI Lab', Icon: Sparkles },
    ],
  },
  {
    id: 'risk-control',
    titleZh: '执行风控',
    titleEn: 'Risk Control',
    items: [
      { id: 'paper', to: '/paper', labelZh: '模拟/实盘交易', labelEn: 'Paper / Live', Icon: WalletCards },
      { id: 'watch', to: '/watch', labelZh: '观察台', labelEn: 'Watch', Icon: Eye },
      { id: 'monitor', to: '/monitor', labelZh: '运行风控', labelEn: 'Runtime Risk', Icon: Shield },
      { id: 'review', to: '/review', labelZh: '复盘中心', labelEn: 'Review Center', Icon: NotebookPen },
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
    <nav aria-label="主工作流" className={clsx(vertical ? 'space-y-3 px-2' : 'flex gap-2 overflow-x-auto pb-1')}>
      {NAV_GROUPS.map((group) => (
        <section
          key={group.id}
          className={clsx(
            vertical
              ? 'overflow-hidden border-b border-crypto-border pb-2 last:border-b-0'
              : 'flex min-w-max items-center gap-1 rounded-[10px] border border-crypto-border bg-crypto-card p-1',
          )}
        >
          {vertical ? (
            <div className="px-2 py-2">
              <span className="block truncate text-[10px] font-bold uppercase tracking-[0.12em] text-slate-600">{isZh ? group.titleZh : group.titleEn}</span>
            </div>
          ) : null}

          <div className={clsx(vertical ? 'space-y-0.5' : 'flex items-center gap-1')}>
            {group.items.map((item) => (
              <NavLink
                key={item.id}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  clsx(
                    'group flex min-w-0 items-center gap-2 rounded-[6px] border text-xs font-semibold transition-colors',
                    vertical ? 'h-8 px-2' : 'h-9 px-3',
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
