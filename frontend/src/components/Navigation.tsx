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
  { id: 'paper', to: '/paper', label: '模拟', Icon: Activity },
  { id: 'watch', to: '/watch', label: '盯盘', Icon: ScanLine },
  { id: 'monitor', to: '/monitor', label: '监控', Icon: Eye },
  { id: 'review', to: '/review', label: '复盘', Icon: ClipboardList },
  { id: 'data', to: '/data', label: '数据', Icon: Database },
  { id: 'ai-lab', to: '/ai-lab', label: 'AI研发', Icon: Bot },
];

export const Navigation = ({ orientation = 'vertical' }: NavigationProps) => {
  const vertical = orientation === 'vertical';

  return (
    <nav
      aria-label="主菜单"
      className={clsx(
        vertical ? 'flex flex-1 flex-col gap-0.5' : 'flex min-w-max items-center gap-1',
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
              'group relative flex shrink-0 items-center justify-center overflow-hidden text-xs transition-all duration-200',
              vertical
                ? 'h-14 w-16 flex-col'
                : 'h-9 min-w-[58px] gap-1.5 rounded-md px-2.5',
              isActive
                ? 'bg-blue-500/15 font-bold text-blue-400 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]'
                : 'text-gray-400 hover:bg-gray-800/80 hover:text-gray-200',
            )
          }
        >
          {({ isActive }) => (
            <>
              {/* Tremor Active Indicator Bar */}
              {isActive && (
                <span
                  className={clsx(
                    'absolute bg-blue-400 shadow-[0_0_8px_rgba(56,189,248,0.7)] transition-all',
                    vertical
                      ? 'left-0 top-2.5 bottom-2.5 w-1 rounded-r-full'
                      : 'bottom-0 left-2 right-2 h-0.5 rounded-t-full'
                  )}
                />
              )}

              <item.Icon
                className={clsx(
                  'transition-all duration-200 group-hover:scale-110',
                  vertical ? 'mb-1 h-5 w-5' : 'h-[18px] w-[18px]',
                  isActive ? 'text-blue-400' : 'text-gray-400 group-hover:text-gray-200'
                )}
              />
              <span className={clsx(vertical ? 'text-[10px]' : 'text-[11px]')}>
                {item.label}
              </span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
};

export default Navigation;
