import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { Activity, DatabaseZap, LogOut, Settings, X } from 'lucide-react';
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
        selected ? 'border-blue-500 bg-blue-500/10 shadow-[0_0_0_1px_rgba(59,130,246,0.18)]' : 'border-crypto-border bg-crypto-bg hover:border-gray-500',
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
      <aside className="hidden w-[292px] shrink-0 flex-col border-r border-crypto-border bg-crypto-bg p-3 lg:flex">
        <div className="rounded-lg border border-crypto-border bg-crypto-card">
          <div className="p-3">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-md border border-blue-500/25 bg-blue-500/10">
                <Activity className="h-4 w-4 text-blue-200" />
              </div>
              <div className="min-w-0">
                <div className="text-sm font-black tracking-wide text-white">StockPro</div>
                <div className="truncate text-[11px] font-semibold text-gray-500">A股量化交易与研究系统</div>
              </div>
            </div>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto py-3">
          <Navigation orientation="vertical" />
        </div>

        <div className="rounded-lg border border-crypto-border bg-crypto-card p-2">
          <div className="border-b border-crypto-border px-2 pb-2">
            <div className="flex items-center justify-between gap-2 text-[10px] font-semibold uppercase tracking-wider text-gray-500">
              <span>Data Source</span>
              <span className="flex h-6 w-6 items-center justify-center rounded-md border border-blue-500/20 bg-blue-500/10">
                <DatabaseZap className="h-3.5 w-3.5 text-blue-300" />
              </span>
            </div>
            <div className="mt-1 truncate text-xs font-semibold text-gray-300">行情采集 · 因子缓存 · 策略运行</div>
          </div>
          <button
            type="button"
            onClick={() => setShowSettings(true)}
            className="mt-2 flex w-full items-center gap-2 rounded-md border border-transparent px-2 py-2 text-sm font-semibold text-gray-400 transition-colors hover:border-crypto-border hover:bg-crypto-bg hover:text-gray-100"
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-md border border-crypto-border bg-crypto-bg">
              <Settings className="h-3.5 w-3.5 text-gray-400" />
            </span>
            设置
          </button>
          <button
            type="button"
            onClick={logout}
            className="mt-1 flex w-full items-center gap-2 rounded-md border border-transparent px-2 py-2 text-sm font-semibold text-gray-400 transition-colors hover:border-crypto-border hover:bg-crypto-bg hover:text-gray-100"
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-md border border-crypto-border bg-crypto-bg">
              <LogOut className="h-3.5 w-3.5 text-gray-400" />
            </span>
            退出登录
          </button>
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-auto bg-crypto-bg">
        <div className="sticky top-0 z-30 border-b border-crypto-border bg-crypto-card/95 px-4 py-3 backdrop-blur lg:hidden">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-md border border-blue-500/25 bg-blue-500/10">
                <Activity className="h-4 w-4 text-blue-200" />
              </div>
              <div>
                <span className="block text-sm font-black text-white">StockPro</span>
                <span className="block text-[10px] font-semibold text-gray-500">A股量化交易与研究系统</span>
              </div>
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
          <div className="border-b border-crypto-border bg-crypto-card/95 px-6 py-4">
            <h1 className="text-lg font-bold text-white">{title}</h1>
          </div>
        ) : null}

        {children || <Outlet />}
      </main>

      {showSettings && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
          <div ref={settingsRef} className="w-full max-w-sm rounded-lg border border-crypto-border bg-crypto-card shadow-2xl shadow-black/40">
            <div className="flex items-center justify-between border-b border-crypto-border p-4">
              <div>
                <h3 className="text-sm font-bold text-white">工作台设置</h3>
                <p className="mt-0.5 text-[11px] text-gray-500">跟随 BitPro 的涨跌色语义</p>
              </div>
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
