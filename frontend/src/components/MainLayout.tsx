import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { Activity, BarChart3, CircleDot, Code2, DatabaseZap, FlaskConical, LogOut, Radio, Settings, ShieldCheck, X } from 'lucide-react';
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

  const pipeline = [
    { label: '数据', Icon: DatabaseZap },
    { label: '研究', Icon: BarChart3 },
    { label: '策略', Icon: Code2 },
    { label: '回测', Icon: FlaskConical },
    { label: '执行', Icon: Radio },
  ];

  return (
    <div className="flex h-screen overflow-hidden bg-crypto-bg text-gray-100">
      <aside className="hidden w-[276px] shrink-0 flex-col border-r border-crypto-border bg-crypto-card lg:flex">
        <div className="border-b border-crypto-border px-4 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-blue-500/30 bg-blue-500/15">
              <Activity className="h-5 w-5 text-blue-200" />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-black tracking-wide text-white">StockPro</div>
              <div className="truncate text-[11px] font-semibold text-gray-500">A股量化交易与研究系统</div>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <div className="rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2 py-1.5">
              <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-300">
                <CircleDot className="h-3 w-3" />
                PG
              </div>
              <div className="mt-0.5 text-[10px] text-gray-500">单一数据层</div>
            </div>
            <div className="rounded-md border border-cyan-500/20 bg-cyan-500/10 px-2 py-1.5">
              <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-cyan-300">
                <ShieldCheck className="h-3 w-3" />
                Admin
              </div>
              <div className="mt-0.5 text-[10px] text-gray-500">全站鉴权</div>
            </div>
          </div>
          <div className="mt-3 rounded-md border border-crypto-border bg-crypto-bg/70 px-2 py-2">
            <div className="mb-2 flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-gray-500">
              <span>Quant Pipeline</span>
              <span className="text-blue-300">A-SHARE</span>
            </div>
            <div className="grid grid-cols-5 gap-1">
              {pipeline.map(({ label, Icon }) => (
                <div key={label} className="flex min-w-0 flex-col items-center gap-1 rounded border border-crypto-border bg-crypto-card/70 px-1 py-1.5">
                  <Icon className="h-3.5 w-3.5 text-blue-300" />
                  <span className="text-[10px] font-semibold text-gray-400">{label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
          <Navigation orientation="vertical" />
        </div>

        <div className="border-t border-crypto-border p-2">
          <div className="mb-2 rounded-md border border-crypto-border bg-crypto-bg/70 px-3 py-2">
            <div className="flex items-center justify-between gap-2 text-[10px] font-semibold uppercase tracking-wider text-gray-500">
              <span>Data Source</span>
              <DatabaseZap className="h-3.5 w-3.5 text-blue-300" />
            </div>
            <div className="mt-1 truncate text-xs font-semibold text-gray-300">行情采集 · 因子缓存 · 策略运行</div>
          </div>
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

      <main className="min-w-0 flex-1 overflow-auto bg-crypto-bg">
        <div className="sticky top-0 z-30 border-b border-crypto-border bg-crypto-card/95 px-4 py-3 backdrop-blur lg:hidden">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-md border border-blue-500/30 bg-blue-500/15">
                <Activity className="h-4 w-4 text-blue-200" />
              </div>
              <div>
                <span className="block text-sm font-black text-white">StockPro</span>
                <span className="block text-[10px] font-semibold text-gray-500">量化交易 · PG · Admin</span>
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
