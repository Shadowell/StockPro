import { Suspense, useEffect, useRef, useState, type ReactNode } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Activity, LogOut, Settings, X } from 'lucide-react';
import clsx from 'clsx';
import {
  clearAdminToken,
  getStoredAuthProfile,
  type AuthProfile,
} from '../api/client';
import {
  useSettingsStore,
  type ColorScheme,
} from '../stores/useSettingsStore';
import { Navigation } from './Navigation';
import { GuestCodeManager } from './GuestCodeManager';
import { McpAgentManager } from './McpAgentManager';

interface MainLayoutProps {
  children?: ReactNode;
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
  const redUp = scheme === 'redUpGreenDown';
  const up = redUp ? '#ff1744' : '#00c853';
  const down = redUp ? '#00c853' : '#ff1744';
  return (
    <button
      type="button"
      onClick={onSelect}
      className={clsx(
        'w-full rounded-lg border p-3 transition-colors',
        selected
          ? 'border-blue-500 bg-blue-500/10'
          : 'border-crypto-border bg-crypto-bg hover:border-slate-500',
      )}
    >
      <div className="mb-2 flex h-9 items-end justify-center gap-1">
        <span className="h-5 w-3 rounded-sm" style={{ backgroundColor: up }} />
        <span className="h-4 w-3 rounded-sm" style={{ backgroundColor: down }} />
        <span className="h-7 w-3 rounded-sm" style={{ backgroundColor: up }} />
      </div>
      <div className="text-xs font-semibold text-slate-200">{label}</div>
      <div className="mt-1 flex justify-center gap-2 text-[10px]">
        <span style={{ color: up }}>涨</span>
        <span style={{ color: down }}>跌</span>
      </div>
    </button>
  );
}

function StockProMark() {
  return (
    <div
      aria-label="StockPro"
      className="flex h-11 w-11 items-center justify-center rounded-xl border border-blue-400/30 bg-blue-500/15"
    >
      <Activity className="h-5 w-5 text-blue-300" />
    </div>
  );
}

function PageFallback() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center text-sm text-slate-500">
      页面加载中…
    </div>
  );
}

export const MainLayout = ({ children }: MainLayoutProps) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { colorScheme, setColorScheme } = useSettingsStore();
  const [showSettings, setShowSettings] = useState(false);
  const [authProfile] = useState<AuthProfile | null>(() => getStoredAuthProfile());
  const settingsRef = useRef<HTMLDivElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showSettings) return;
    const close = (event: MouseEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(event.target as Node)) {
        setShowSettings(false);
      }
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [showSettings]);

  useEffect(() => {
    if (authProfile?.role !== 'guest' || !shellRef.current) return;
    const root = shellRef.current;
    const writeAction = /新建|创建|保存|删除|撤销|同步|更新|导入|生成|执行|运行|启动|停止|暂停|恢复|重试|提交|批准|拒绝|晋级|发布|封存|检测.*连接|清空|重置/;
    const allowedBacktest = /启动.*回测|运行.*回测|快速回测|完整回测|停止任务|重试任务/;
    const guard = () => {
      root.querySelectorAll<HTMLButtonElement>('button').forEach((button) => {
        const label = (button.textContent || button.getAttribute('aria-label') || '').trim();
        if (/^查看.*说明$/.test(label)) return;
        const permitted = location.pathname.startsWith('/backtest') && allowedBacktest.test(label);
        if (!permitted && writeAction.test(label) && !button.dataset.guestWriteBlocked) {
          button.disabled = true;
          button.dataset.guestWriteBlocked = 'true';
          button.setAttribute('aria-disabled', 'true');
          button.title = '访客账号为只读权限；仅回测运行可在配额内执行。';
          button.classList.add('cursor-not-allowed', 'opacity-45');
        }
      });
    };
    guard();
    const observer = new MutationObserver(guard);
    observer.observe(root, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      root.querySelectorAll<HTMLButtonElement>('button[data-guest-write-blocked="true"]').forEach((button) => {
        button.disabled = false;
        delete button.dataset.guestWriteBlocked;
        button.removeAttribute('aria-disabled');
        button.removeAttribute('title');
        button.classList.remove('cursor-not-allowed', 'opacity-45');
      });
    };
  }, [authProfile?.role, location.pathname]);

  const logout = () => {
    clearAdminToken();
    navigate('/admin-login', { replace: true });
  };

  return (
    <div
      ref={shellRef}
      className="flex h-screen overflow-hidden bg-crypto-bg text-slate-100"
      data-testid="financial-operator-shell"
      data-auth-role={authProfile?.role || 'unknown'}
    >
      <aside className="hidden w-16 shrink-0 flex-col overflow-hidden border-r border-slate-800 bg-[#090e15] md:flex">
        <div className="flex h-16 items-center justify-center border-b border-slate-800">
          <StockProMark />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <Navigation />
        </div>
        <div className="space-y-1 border-t border-slate-800 p-1">
          <div
            className={clsx(
              'rounded px-1 py-1 text-center text-[9px] font-semibold',
              authProfile?.role === 'guest'
                ? 'bg-cyan-500/10 text-cyan-300'
                : 'bg-emerald-500/10 text-emerald-300',
            )}
          >
            {authProfile?.role === 'guest' ? '访客' : '管理员'}
          </div>
          {authProfile?.role === 'admin' && (
            <button
              type="button"
              onClick={() => setShowSettings(true)}
              className="flex h-9 w-full items-center justify-center rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200"
              aria-label="设置"
            >
              <Settings className="h-4 w-4" />
            </button>
          )}
          <button
            type="button"
            onClick={logout}
            className="flex h-9 w-full items-center justify-center rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200"
            aria-label="退出登录"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </aside>

      <main
        className="min-w-0 flex-1 overflow-auto"
        data-operator-surface="page"
      >
        <div className="sticky top-0 z-30 border-b border-slate-800 bg-[#090e15]/95 px-3 py-2 backdrop-blur md:hidden">
          <div className="flex items-center justify-between gap-3">
            <StockProMark />
            <div className="min-w-0 flex-1 overflow-x-auto">
              <Navigation orientation="horizontal" />
            </div>
            <button
              type="button"
              onClick={logout}
              className="rounded p-2 text-slate-500 hover:bg-slate-800 hover:text-slate-200"
              aria-label="退出登录"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>

        {authProfile?.role === 'guest' && (
          <div
            className="sticky top-0 z-20 border-b border-cyan-500/20 bg-crypto-bg/95 px-4 py-2 text-xs text-cyan-100 backdrop-blur"
            role="status"
            data-testid="guest-access-banner"
          >
            <span className="font-semibold text-cyan-200">访客模式：</span>
            可查看研究证据并在配额内运行回测；策略、数据同步和模拟交易写入不可用。
          </div>
        )}

        <Suspense fallback={<PageFallback />}>{children || <Outlet />}</Suspense>
      </main>

      {showSettings && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 px-4 backdrop-blur-sm">
          <div
            ref={settingsRef}
            className="max-h-[88vh] w-full max-w-2xl overflow-auto rounded-xl border border-crypto-border bg-crypto-card shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-crypto-border p-4">
              <div>
                <h2 className="text-sm font-bold text-white">工作台设置</h2>
                <p className="mt-1 text-xs text-slate-500">权限、Agent 接入与显示偏好</p>
              </div>
              <button
                type="button"
                onClick={() => setShowSettings(false)}
                className="rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-white"
                aria-label="关闭设置"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-5 p-4">
              <section>
                <h3 className="mb-3 text-xs font-semibold text-slate-400">K 线涨跌颜色</h3>
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
              </section>
              <GuestCodeManager />
              <McpAgentManager />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default MainLayout;
