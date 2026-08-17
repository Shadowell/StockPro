import { Suspense, useEffect, useRef, useState, type ReactNode } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { LogOut, Settings, X } from 'lucide-react';
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
import { McpAgentManager } from './McpAgentManager';
import { MarketSessionBadge } from './MarketSessionBadge';
import { StockProMark } from './StockProMark';
import { ResearchDeskProvider } from './ResearchDeskContext';

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
    <ResearchDeskProvider>
    <div
      ref={shellRef}
      className="flex h-screen overflow-hidden bg-crypto-bg text-slate-100"
      data-testid="financial-operator-shell"
      data-auth-role={authProfile?.role || 'unknown'}
    >
      <aside className="hidden w-[72px] shrink-0 flex-col overflow-hidden border-r border-crypto-border bg-crypto-bg md:flex">
        <div className="flex flex-col items-center gap-1.5 border-b border-crypto-border px-1 py-2.5">
          <StockProMark size="sm" showGlow={false} quiet />
          <MarketSessionBadge compact />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto py-1.5">
          <Navigation />
        </div>
        <div className="border-t border-crypto-border py-1.5">
          <div className="px-1 pb-1 text-center text-[10px] leading-none text-crypto-muted">
            {authProfile?.role === 'guest' ? '访客' : '管理员'}
          </div>
          {authProfile?.role === 'admin' && (
            <button
              type="button"
              onClick={() => setShowSettings(true)}
              className={clsx(
                'flex h-9 w-full items-center justify-center transition-colors',
                showSettings
                  ? 'bg-crypto-accent/10 text-crypto-accent'
                  : 'text-crypto-muted hover:bg-white/[0.04] hover:text-slate-200',
              )}
              aria-label="设置"
            >
              <Settings className="h-4 w-4" />
            </button>
          )}
          <button
            type="button"
            onClick={logout}
            className="flex h-9 w-full items-center justify-center text-crypto-muted transition-colors hover:bg-white/[0.04] hover:text-slate-200"
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
        <div className="sticky top-0 z-30 border-b border-crypto-border bg-crypto-card/95 px-3 py-2 backdrop-blur md:hidden">
          <div className="flex items-center justify-between gap-3">
            <StockProMark size="sm" />
            <MarketSessionBadge className="shrink-0" />
            <div className="min-w-0 flex-1 overflow-x-auto" data-mobile-nav-viewport>
              <Navigation orientation="horizontal" />
            </div>
            <button
              type="button"
              onClick={logout}
              className="rounded p-2 text-gray-500 transition-colors hover:bg-gray-800 hover:text-gray-200"
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

        <div
          key={location.pathname}
          className="stockpro-page-viewport animate-fade-in-up min-h-full min-w-0 flex-1"
          data-tremor-workspace="true"
        >
          <Suspense fallback={<PageFallback />}>{children || <Outlet />}</Suspense>
        </div>
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
              <McpAgentManager />
            </div>
          </div>
        </div>
      )}
    </div>
    </ResearchDeskProvider>
  );
};

export default MainLayout;
