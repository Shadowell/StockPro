import React, { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  Activity,
  BarChart3,
  Bell,
  Code2,
  Database,
  FlaskConical,
  LineChart,
  Radio,
  Settings,
  X,
} from 'lucide-react';
import clsx from 'clsx';
import { useSettingsStore, type ColorScheme } from '../stores/useSettingsStore';

interface MainLayoutProps {
  children?: React.ReactNode;
  title?: string;
}

const navItems = [
  { path: '/', icon: BarChart3, label: '大盘' },
  { path: '/market', icon: LineChart, label: '行情' },
  { path: '/strategy', icon: Code2, label: '策略' },
  { path: '/backtest', icon: FlaskConical, label: '回测' },
  { path: '/paper', icon: Radio, label: '模拟' },
  { path: '/monitor', icon: Bell, label: '监控' },
  { path: '/data', icon: Database, label: '数据' },
];

function ColorSchemeCard({
  label,
  scheme,
  selected,
  onSelect,
}: {
  label: string;
  scheme: ColorScheme;
  selected: boolean;
  onSelect: () => void;
}) {
  const isRedUp = scheme === 'redUpGreenDown';
  const upColor = isRedUp ? '#FF1744' : '#00C853';
  const downColor = isRedUp ? '#00C853' : '#FF1744';

  return (
    <button
      onClick={onSelect}
      className={clsx(
        'w-full rounded-lg border-2 p-3 transition-all',
        selected ? 'border-blue-500 bg-blue-500/10' : 'border-crypto-border bg-crypto-card hover:border-gray-500'
      )}
    >
      <div className="mb-2 flex h-10 items-end justify-center gap-1">
        <div className="h-5 w-3 rounded-sm" style={{ backgroundColor: upColor }} />
        <div className="h-4 w-3 rounded-sm" style={{ backgroundColor: downColor }} />
        <div className="h-7 w-3 rounded-sm" style={{ backgroundColor: upColor }} />
      </div>
      <div className="text-xs font-medium text-gray-300">{label}</div>
      <div className="mt-1 flex items-center justify-center gap-2 text-[10px]">
        <span style={{ color: upColor }}>涨</span>
        <span style={{ color: downColor }}>跌</span>
      </div>
    </button>
  );
}

export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
  const { colorScheme, setColorScheme } = useSettingsStore();
  const [showSettings, setShowSettings] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showSettings) return;
    const handleClick = (event: MouseEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(event.target as Node)) {
        setShowSettings(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [showSettings]);

  return (
    <div className="flex h-screen overflow-hidden bg-crypto-bg text-gray-100">
      <aside className="flex w-16 shrink-0 flex-col overflow-hidden border-r border-crypto-border bg-crypto-card">
        <div className="flex h-16 items-center justify-center border-b border-crypto-border">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600">
            <Activity className="h-6 w-6 text-white" />
          </div>
        </div>

        <nav className="flex-1 py-3">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) =>
                clsx(
                  'flex h-16 flex-col items-center justify-center px-1 text-[11px] transition-colors',
                  isActive ? 'bg-blue-500/10 text-blue-400' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'
                )
              }
            >
              <item.icon className="mb-1 h-5 w-5" />
              <span className="max-w-full truncate text-center leading-tight">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="space-y-1 border-t border-crypto-border p-1">
          <div className="flex w-full items-center justify-center rounded bg-blue-600 py-1.5 text-[10px] font-semibold text-white">
            A股
          </div>
          <button
            onClick={() => setShowSettings(true)}
            className={clsx(
              'flex h-10 w-full items-center justify-center rounded transition-colors',
              showSettings ? 'bg-blue-500/10 text-blue-400' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'
            )}
            aria-label="设置"
          >
            <Settings className="h-4 w-4" />
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">{children || <Outlet />}</main>

      {showSettings && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div ref={settingsRef} className="max-h-[80vh] w-80 overflow-y-auto rounded-xl border border-crypto-border bg-crypto-card shadow-2xl">
            <div className="flex items-center justify-between border-b border-crypto-border p-4">
              <h3 className="text-sm font-semibold text-white">设置</h3>
              <button onClick={() => setShowSettings(false)} className="rounded p-1 text-gray-400 hover:bg-gray-700 hover:text-white" aria-label="关闭设置">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-4 p-4">
              <div>
                <div className="mb-3 text-xs font-medium text-gray-400">K线涨跌颜色</div>
                <div className="grid grid-cols-2 gap-3">
                  <ColorSchemeCard
                    label="红涨绿跌"
                    scheme="redUpGreenDown"
                    selected={colorScheme === 'redUpGreenDown'}
                    onSelect={() => setColorScheme('redUpGreenDown')}
                  />
                  <ColorSchemeCard
                    label="绿涨红跌"
                    scheme="greenUpRedDown"
                    selected={colorScheme === 'greenUpRedDown'}
                    onSelect={() => setColorScheme('greenUpRedDown')}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default MainLayout;
