import type { ComponentType } from 'react';
import { NavLink } from 'react-router-dom';
import {
  Activity,
  Bot,
  ClipboardList,
  Code2,
  Database,
  Eye,
  FlaskConical,
  Layers3,
  LayoutDashboard,
  ScanLine,
  TestTube2,
  TrendingUp,
} from 'lucide-react';
import clsx from 'clsx';

interface NavigationProps {
  orientation?: 'horizontal' | 'vertical';
}

type IconType = ComponentType<{ className?: string }>;

type NavItem = {
  id: string;
  to: string;
  label: string;
  Icon: IconType;
  end?: boolean;
};

const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', to: '/', label: '首页', Icon: LayoutDashboard, end: true },
  { id: 'market', to: '/market', label: '行情', Icon: TrendingUp },
  { id: 'pools', to: '/pools', label: '股票池', Icon: Layers3 },
  { id: 'factors', to: '/factors', label: '因子', Icon: TestTube2 },
  { id: 'strategy', to: '/strategy', label: '策略', Icon: Code2 },
  { id: 'backtest', to: '/backtest', label: '回测', Icon: FlaskConical },
  { id: 'ai-lab', to: '/ai-lab', label: 'AI研发', Icon: Bot },
  { id: 'paper', to: '/paper', label: '模拟', Icon: Activity },
  { id: 'watch', to: '/watch', label: '盯盘', Icon: ScanLine },
  { id: 'monitor', to: '/monitor', label: '监控', Icon: Eye },
  { id: 'review', to: '/review', label: '复盘', Icon: ClipboardList },
  { id: 'data', to: '/data', label: '数据', Icon: Database },
];

export const Navigation = ({ orientation = 'vertical' }: NavigationProps) => {
  const vertical = orientation === 'vertical';

  return (
    <nav
      aria-label="主菜单"
      className={clsx(
        vertical ? 'flex flex-1 flex-col py-2' : 'flex min-w-max items-center gap-1',
      )}
    >
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.id}
          to={item.to}
          end={item.end}
          title={item.label}
          className={({ isActive }) =>
            clsx(
              'group relative flex shrink-0 items-center justify-center text-xs font-semibold transition-colors duration-150',
              vertical
                ? 'h-[52px] w-16 flex-col gap-1 border-l-2'
                : 'h-10 min-w-[58px] gap-1.5 rounded-md px-2',
              isActive
                ? vertical
                  ? 'border-blue-400 bg-blue-600/25 text-blue-100 shadow-[inset_0_0_18px_rgba(37,99,235,0.12)]'
                  : 'border-transparent bg-blue-600/30 text-blue-100'
                : vertical
                  ? 'border-transparent text-slate-300 hover:border-slate-600 hover:bg-slate-800/80 hover:text-white'
                  : 'text-slate-300 hover:bg-slate-800 hover:text-white',
            )
          }
        >
          <item.Icon className="h-[18px] w-[18px] stroke-[2.2]" />
          <span className={clsx(vertical ? 'text-[10px]' : 'text-[11px]')}>
            {item.label}
          </span>
        </NavLink>
      ))}
    </nav>
  );
};
