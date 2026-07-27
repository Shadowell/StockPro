import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Activity, Languages, LogOut, Settings, X } from 'lucide-react';
import { StatusBadge } from '@bitpro/ui';
import clsx from 'clsx';
import { clearAdminToken, getMarketOverview } from '../api/client';
import { useSettingsStore, type ColorScheme } from '../stores/useSettingsStore';
import { useStore } from '../stores/useStore';
import type { MarketIndex } from '../types';
import { Navigation } from './Navigation';

interface MainLayoutProps {
  children?: ReactNode;
  title?: string;
}

const TOP_INDEX_ORDER = ['上证指数', '深证成指', '创业板指', '科创50'];

const PAGE_TITLES: Array<[RegExp, string]> = [
  [/^\/$/, '实时大盘'],
  [/^\/market/, '市场概览'],
  [/^\/pools/, '股票池研究'],
  [/^\/research\/overview/, '市场概览'],
  [/^\/sentiment/, '市场情绪'],
  [/^\/news/, '消息中心'],
  [/^\/ai-lab/, 'AI 研发'],
  [/^\/ai/, '智能选股'],
  [/^\/factors/, '因子研究'],
  [/^\/calendar/, '交易日历'],
  [/^\/strategy/, '策略开发'],
  [/^\/backtest/, '回测中心'],
  [/^\/review/, '复盘中心'],
  [/^\/paper/, '模拟/实盘交易'],
  [/^\/watch/, '观察台'],
  [/^\/monitor/, '运行风控'],
  [/^\/data\/processing/, '管理后台'],
  [/^\/data/, '管理后台'],
];

const formatNumber = (value?: number | null, digits = 2) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return Number(value).toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
};

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
  const upColor = isRedUp ? '#ff4d57' : '#10b981';
  const downColor = isRedUp ? '#10b981' : '#ff4d57';

  return (
    <button
      type="button"
      onClick={onSelect}
      className={clsx(
        'w-full rounded-[10px] border p-3 transition-colors',
        selected ? 'border-blue-500/65 bg-blue-600/15 shadow-[0_0_0_1px_rgba(96,165,250,0.14)]' : 'border-crypto-border bg-crypto-bg hover:border-slate-500',
      )}
    >
      <div className="mb-2 flex h-10 items-end justify-center gap-1">
        <div className="h-5 w-3 rounded-sm" style={{ backgroundColor: upColor }} />
        <div className="h-4 w-3 rounded-sm" style={{ backgroundColor: downColor }} />
        <div className="h-7 w-3 rounded-sm" style={{ backgroundColor: upColor }} />
      </div>
      <div className="text-xs font-semibold text-slate-200">{label}</div>
      <div className="mt-1 flex items-center justify-center gap-2 text-[10px]">
        <span style={{ color: upColor }}>涨</span>
        <span style={{ color: downColor }}>跌</span>
      </div>
    </button>
  );
}

function StockProLogo() {
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[7px] border border-blue-400/30 bg-blue-500/15 text-blue-300">
        <Activity className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <div className="truncate text-[16px] font-black leading-none tracking-tight text-white">
          StockPro <span className="text-slate-500">AI</span>
        </div>
        <div className="mt-1 text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-600">A-Share Operator</div>
      </div>
    </div>
  );
}

function TopTicker({ indices }: { indices: MarketIndex[] }) {
  const ordered = TOP_INDEX_ORDER
    .map((name) => indices.find((item) => item.name === name))
    .filter((item): item is MarketIndex => Boolean(item));
  const displayIndices = ordered.length >= 4 ? ordered : [...ordered, ...indices.filter((item) => !TOP_INDEX_ORDER.includes(item.name))];
  const slots = TOP_INDEX_ORDER.map((name) => displayIndices.find((item) => item.name === name) ?? null);

  return (
    <div className="flex min-w-0 items-center gap-1" aria-label="A股指数快照">
      {slots.map((item, index) => {
        const positive = (item?.change_percent || 0) >= 0;
        return (
          <div key={TOP_INDEX_ORDER[index]} className="min-w-[118px] border-l border-crypto-border px-3 first:border-l-0">
            <div className="text-[10px] font-bold text-slate-500">{TOP_INDEX_ORDER[index]}</div>
            <div className={clsx('mt-0.5 font-mono text-[12px] font-bold tabular-nums', item ? (positive ? 'text-up' : 'text-down') : 'text-slate-600')}>
              {item ? `${formatNumber(item.price)} ${positive ? '+' : ''}${formatNumber(item.change_percent)}%` : '-- --'}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function PageContentFallback() {
  return (
    <div className="flex min-h-[calc(100vh-48px)] items-center justify-center bg-crypto-bg text-sm text-slate-500">
      正在加载页面…
    </div>
  );
}

export const MainLayout = ({ children, title }: MainLayoutProps) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { language, setLanguage } = useStore();
  const { colorScheme, setColorScheme } = useSettingsStore();
  const [showSettings, setShowSettings] = useState(false);
  const [indices, setIndices] = useState<MarketIndex[]>([]);
  const [marketSnapshotState, setMarketSnapshotState] = useState<'loading' | 'fresh' | 'stale' | 'unavailable'>('loading');
  const [marketSnapshotUpdatedAt, setMarketSnapshotUpdatedAt] = useState<string | null>(null);
  const settingsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    getMarketOverview()
      .then((overview) => {
        if (cancelled) return;
        setIndices(overview.indices || []);
        const stockState = overview.data_status?.stock_snapshot_state;
        const indexState = overview.data_status?.index_snapshot_state;
        const effectiveState = stockState === 'stale' || indexState === 'stale'
          ? 'stale'
          : stockState === 'fresh' && (indexState === 'fresh' || indexState === undefined)
            ? 'fresh'
            : 'unavailable';
        setMarketSnapshotState(effectiveState);
        setMarketSnapshotUpdatedAt(
          overview.data_status?.stock_snapshot_updated_at
          || overview.data_status?.index_snapshot_updated_at
          || overview.last_update
          || null,
        );
      })
      .catch(() => {
        if (!cancelled) {
          setIndices([]);
          setMarketSnapshotState('unavailable');
          setMarketSnapshotUpdatedAt(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

  const pageTitle = useMemo(() => {
    if (title) return title;
    return PAGE_TITLES.find(([pattern]) => pattern.test(location.pathname))?.[1] || 'StockPro AI';
  }, [location.pathname, title]);

  const logout = () => {
    clearAdminToken();
    navigate('/admin-login', { replace: true });
  };

  return (
    <div className="flex h-screen overflow-hidden bg-crypto-bg text-slate-100" data-testid="financial-operator-shell">
      <aside className="hidden w-[232px] shrink-0 flex-col border-r border-crypto-border bg-crypto-card lg:flex">
        <div className="flex h-[58px] items-center border-b border-crypto-border px-3.5">
          <StockProLogo />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto py-2">
          <Navigation orientation="vertical" />
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-hidden bg-crypto-bg">
        <div className="hidden h-[48px] items-center justify-between border-b border-crypto-border bg-crypto-panel px-4 lg:flex" data-testid="stockpro-ai-topbar">
          <h1 className="shrink-0 text-sm font-bold tracking-tight text-slate-100">{pageTitle}</h1>
          <div className="ml-4 flex min-w-0 items-center gap-3">
            <TopTicker indices={indices} />
            <StatusBadge tone={marketSnapshotState === 'fresh' ? 'green' : marketSnapshotState === 'loading' ? 'blue' : 'amber'}>
              {marketSnapshotState === 'fresh'
                ? '行情快照新鲜'
                : marketSnapshotState === 'stale'
                  ? `行情已陈旧${marketSnapshotUpdatedAt ? ` · ${marketSnapshotUpdatedAt.slice(0, 10)}` : ''}`
                  : marketSnapshotState === 'loading'
                    ? '行情加载中'
                    : '行情快照不可用'}
            </StatusBadge>
            <button
              type="button"
              onClick={() => setLanguage(language === 'zh' ? 'en' : 'zh')}
              className="inline-flex h-8 items-center gap-1.5 rounded-[7px] border border-crypto-border bg-slate-800/70 px-3 text-xs font-black text-slate-300 transition-colors hover:border-blue-500/50 hover:text-blue-200"
              aria-label="切换语言"
            >
              <Languages className="h-3.5 w-3.5" />
              {language === 'zh' ? 'EN' : '中'}
            </button>
            <button
              type="button"
              onClick={() => setShowSettings(true)}
              className="inline-flex h-8 w-8 items-center justify-center rounded-[7px] border border-crypto-border bg-slate-800/70 text-slate-400 transition-colors hover:border-blue-500/50 hover:text-blue-200"
              aria-label="设置"
            >
              <Settings className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={logout}
              className="inline-flex h-8 w-8 items-center justify-center rounded-[7px] border border-crypto-border bg-slate-800/70 text-slate-400 transition-colors hover:border-red-500/40 hover:text-red-200"
              aria-label="退出登录"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="sticky top-0 z-30 border-b border-crypto-border bg-crypto-card/95 px-4 py-3 backdrop-blur lg:hidden">
          <div className="mb-3 flex items-center justify-between">
            <StockProLogo />
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setShowSettings(true)}
                className="rounded-md p-2 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
                aria-label="设置"
              >
                <Settings className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={logout}
                className="rounded-md p-2 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
                aria-label="退出登录"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          </div>
          <Navigation orientation="horizontal" />
        </div>

        <div className="stockpro-page-viewport h-full overflow-auto" data-operator-surface="page">
          <Suspense fallback={<PageContentFallback />}>
            {children || <Outlet />}
          </Suspense>
        </div>
      </main>

      {showSettings && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 px-4 backdrop-blur-sm">
          <div ref={settingsRef} className="w-full max-w-sm rounded-[12px] border border-crypto-border bg-crypto-card shadow-2xl shadow-black/40">
            <div className="flex items-center justify-between border-b border-crypto-border p-4">
              <div>
                <h3 className="text-sm font-bold text-white">工作台设置</h3>
                <p className="mt-0.5 text-[11px] text-slate-500">保持服务器版 StockPro AI 的交易语义</p>
              </div>
              <button
                type="button"
                onClick={() => setShowSettings(false)}
                className="rounded-md p-1 text-slate-400 hover:bg-slate-700 hover:text-white"
                aria-label="关闭设置"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-4 p-4">
              <div>
                <div className="mb-3 text-xs font-semibold text-slate-400">K线涨跌颜色</div>
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
