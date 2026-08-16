import { useEffect, useRef, type ComponentType } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
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
  ShieldCheck,
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

type NavGroup = {
  id: string;
  label: string;
  items: NavItem[];
};

const NAV_GROUPS: NavGroup[] = [
  {
    id: 'discover',
    label: '研究',
    items: [
      { id: 'dashboard', to: '/', label: '首页', Icon: LayoutDashboard, end: true },
      { id: 'market', to: '/market', label: '行情', Icon: TrendingUp },
      { id: 'pools', to: '/pools', label: '股票池', Icon: Layers3 },
    ],
  },
  {
    id: 'build',
    label: '研发',
    items: [
      { id: 'factors', to: '/factors', label: '因子', Icon: TestTube2 },
      { id: 'strategy', to: '/strategy', label: '策略', Icon: Code2 },
      { id: 'backtest', to: '/backtest', label: '回测', Icon: FlaskConical },
    ],
  },
  {
    id: 'verify',
    label: '验证',
    items: [
      { id: 'paper', to: '/paper', label: '模拟', Icon: Activity },
      { id: 'watch', to: '/watch', label: '盯盘', Icon: ScanLine },
      { id: 'monitor', to: '/monitor', label: '监控', Icon: Eye },
      { id: 'live', to: '/live', label: '实盘', Icon: ShieldCheck },
      { id: 'review', to: '/review', label: '复盘', Icon: ClipboardList },
    ],
  },
  {
    id: 'system',
    label: '系统',
    items: [
      { id: 'data', to: '/data', label: '数据', Icon: Database },
      { id: 'ai-lab', to: '/ai-lab', label: 'AI研发', Icon: Bot },
    ],
  },
];

function NavItemLink({ item, vertical }: { item: NavItem; vertical: boolean }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      title={item.label}
      className={({ isActive }) =>
        clsx(
          'group relative flex shrink-0 items-center justify-center overflow-hidden text-xs transition-all duration-200',
          vertical
            ? 'h-12 w-16 flex-col'
            : 'h-10 min-w-[58px] gap-1.5 border-b-2 border-transparent px-2.5',
          isActive
            ? vertical
              ? 'bg-blue-500/15 font-bold text-blue-400 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]'
              : 'border-blue-400 font-bold text-blue-300'
            : vertical
              ? 'text-gray-400 hover:bg-gray-800/80 hover:text-gray-200'
              : 'text-gray-400 hover:border-slate-600 hover:text-gray-200',
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span
              className={clsx(
                'absolute bg-blue-400 shadow-[0_0_8px_rgba(56,189,248,0.7)] transition-all',
                vertical ? 'left-0 top-2 bottom-2 w-1 rounded-r-full' : 'hidden',
              )}
            />
          )}
          <item.Icon
            className={clsx(
              'transition-all duration-200 group-hover:scale-110',
              vertical ? 'mb-0.5 h-[18px] w-[18px]' : 'h-[18px] w-[18px]',
              isActive ? 'text-blue-400' : 'text-gray-400 group-hover:text-gray-200',
            )}
          />
          <span className={clsx(vertical ? 'text-[10px]' : 'text-[11px]')}>{item.label}</span>
        </>
      )}
    </NavLink>
  );
}

export const Navigation = ({ orientation = 'vertical' }: NavigationProps) => {
  const vertical = orientation === 'vertical';
  const location = useLocation();
  const navigationRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (vertical) return;
    const frame = window.requestAnimationFrame(() => {
      navigationRef.current
        ?.querySelector<HTMLElement>('[aria-current="page"]')
        ?.scrollIntoView({ block: 'nearest', inline: 'center' });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [location.pathname, vertical]);

  return (
    <nav
      ref={navigationRef}
      aria-label="主菜单"
      className={clsx(
        vertical ? 'flex flex-1 flex-col gap-0.5' : 'flex min-w-max items-center gap-1',
      )}
    >
      {NAV_GROUPS.map((group, index) => (
        <div
          key={group.id}
          role="group"
          aria-label={group.label}
          className={clsx(vertical ? 'flex flex-col' : 'flex items-center gap-1')}
        >
          {vertical ? (
            <>
              {index > 0 ? <div className="mx-3 my-1 h-px bg-crypto-border" aria-hidden="true" /> : null}
              <div className="px-1 pb-0.5 text-center text-[8px] font-semibold tracking-wider text-slate-600">
                {group.label}
              </div>
            </>
          ) : index > 0 ? (
            <span className="mx-1 h-5 w-px bg-crypto-border" aria-hidden="true" />
          ) : null}
          {group.items.map((item) => (
            <NavItemLink key={item.id} item={item} vertical={vertical} />
          ))}
        </div>
      ))}
    </nav>
  );
};

export default Navigation;
