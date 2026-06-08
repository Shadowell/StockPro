import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { Activity, LogOut, Settings, X } from 'lucide-react';
import clsx from 'clsx';
import { clearAdminToken } from '../api/client';
import { useSettingsStore, type ColorScheme } from '../stores/useSettingsStore';
import { Navigation } from './Navigation';

interface MainLayoutProps {
  children?: ReactNode;
  title?: string;
}

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
      type="button"
      onClick={onSelect}
      className={clsx(
        'w-full rounded-lg border p-3 transition-colors',
        selected ? 'border-blue-500 bg-blue-500/10' : 'border-crypto-border bg-crypto-bg hover:border-gray-500',
      )}
    >
      <div className="mb-2 flex h-10 items-end justify-center gap-1">
        <div className="h-5 w-3 rounded-sm" style={{ backgroundColor: upColor }} />
        <div className="h-4 w-3 rounded-sm" style={{ backgroundColor: downColor }} />
        <div className="h-7 w-3 rounded-sm" style={{ backgroundColor: upColor }} />
      </div>
      <div className="text-xs font-semibold text-gray-300">{label}</div>
      <div className="mt-1 flex items-center justify-center gap-2 text-[10px]">
        <span style={{ color: upColor }}>涨</span>
        <span style={{ color: downColor }}>跌</span>
      </div>
    </button>
  );
}

export const MainLayout = ({ children, title }: MainLayoutProps) => {
  const navigate = useNavigate();
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

  const logout = () => {
    clearAdminToken();
    navigate('/admin-login', { replace: true });
  };

  return (
    <div className="flex h-screen overflow-hidden bg-crypto-bg text-gray-100">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-crypto-border bg-crypto-card lg:flex">
        <div className="flex h-16 items-center gap-3 border-b border-crypto-border px-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600">
            <Activity className="h-5 w-5 text-white" />
          </div>
          <div>
            <div className="text-sm font-black tracking-wide text-white">StockPro</div>
            <div className="text-[11px] font-semibold text-gray-500">A股研究与策略工作台</div>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-4">
          <Navigation orientation="vertical" />
        </div>

        <div className="border-t border-crypto-border p-2">
          <button
            type="button"
            onClick={() => setShowSettings(true)}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm font-semibold text-gray-400 transition-colors hover:bg-gray-800 hover:text-gray-100"
          >
            <Settings className="h-4 w-4" />
            设置
          </button>
          <button
            type="button"
            onClick={logout}
            className="mt-1 flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm font-semibold text-gray-400 transition-colors hover:bg-gray-800 hover:text-gray-100"
          >
            <LogOut className="h-4 w-4" />
            退出登录
          </button>
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-auto">
        <div className="sticky top-0 z-30 border-b border-crypto-border bg-crypto-card/95 px-4 py-3 backdrop-blur lg:hidden">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-md bg-blue-600">
                <Activity className="h-4 w-4 text-white" />
              </div>
              <span className="text-sm font-black text-white">StockPro</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setShowSettings(true)}
                className="rounded-md p-2 text-gray-400 hover:bg-gray-800 hover:text-gray-100"
                aria-label="设置"
              >
                <Settings className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={logout}
                className="rounded-md p-2 text-gray-400 hover:bg-gray-800 hover:text-gray-100"
                aria-label="退出登录"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          </div>
          <Navigation orientation="horizontal" />
        </div>

        {title ? (
          <div className="border-b border-crypto-border bg-crypto-card px-6 py-4">
            <h1 className="text-xl font-bold text-white">{title}</h1>
          </div>
        ) : null}

        {children || <Outlet />}
      </main>

      {showSettings && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 px-4">
          <div ref={settingsRef} className="w-full max-w-sm rounded-lg border border-crypto-border bg-crypto-card shadow-2xl">
            <div className="flex items-center justify-between border-b border-crypto-border p-4">
              <h3 className="text-sm font-bold text-white">设置</h3>
              <button
                type="button"
                onClick={() => setShowSettings(false)}
                className="rounded-md p-1 text-gray-400 hover:bg-gray-700 hover:text-white"
                aria-label="关闭设置"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-4 p-4">
              <div>
                <div className="mb-3 text-xs font-semibold text-gray-400">K线涨跌颜色</div>
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
