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

/** Operator-trunk cut. Empty this set to restore hidden workspaces. Routes stay registered. */
const HIDDEN_NAV_IDS = new Set<string>([
  'pools',
  'factors',
  'monitor',
  'review',
  'live',
]);

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
      { id: 'ai-lab', to: '/ai-lab', label: 'AI研发', Icon: Bot },
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
    ],
  },
];

function visibleNavGroups(groups: NavGroup[]): NavGroup[] {
  return groups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => !HIDDEN_NAV_IDS.has(item.id)),
    }))
    .filter((group) => group.items.length > 0);
}

function navItemClass(vertical: boolean, isActive: boolean): string {
  if (vertical) {
    return clsx(
      'group relative flex h-11 w-full flex-col items-center justify-center gap-1 text-[11px] leading-none transition-colors',
      isActive
        ? 'bg-crypto-accent/10 font-medium text-crypto-accent'
        : 'text-crypto-muted hover:bg-white/[0.04] hover:text-slate-200',
    );
  }
  return clsx(
    'group relative flex h-9 min-w-[52px] shrink-0 items-center justify-center gap-1.5 border-b border-transparent px-2 text-[11px] leading-none transition-colors',
    isActive
      ? 'border-crypto-accent font-medium text-crypto-accent'
      : 'text-crypto-muted hover:border-crypto-border hover:text-slate-200',
  );
}

function NavItemLink({ item, vertical }: { item: NavItem; vertical: boolean }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      title={item.label}
      className={({ isActive }) => navItemClass(vertical, isActive)}
    >
      {({ isActive }) => (
        <>
          {vertical && isActive ? (
            <span className="absolute inset-y-1.5 left-0 w-0.5 bg-crypto-accent" aria-hidden="true" />
          ) : null}
          <item.Icon
            className={clsx(
              'h-4 w-4',
              isActive ? 'text-crypto-accent' : 'text-crypto-muted group-hover:text-slate-200',
            )}
          />
          <span>{item.label}</span>
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
      {visibleNavGroups(NAV_GROUPS).map((group, index) => (
        <div
          key={group.id}
          role="group"
          aria-label={group.label}
          className={clsx(vertical ? 'flex flex-col' : 'flex items-center gap-1')}
        >
          {index > 0 ? (
            <div
              className={clsx(
                'bg-crypto-border',
                vertical ? 'mx-3.5 my-1.5 h-px' : 'mx-1 h-4 w-px',
              )}
              aria-hidden="true"
            />
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
