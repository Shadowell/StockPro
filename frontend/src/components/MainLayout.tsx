import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Activity, Languages, LogOut, Settings, X } from 'lucide-react';
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

const FALLBACK_INDICES: MarketIndex[] = [
  { name: '上证指数', code: '000001', price: 4120.28, change_amount: 9.47, change_percent: 0.23 },
  { name: '深证成指', code: '399001', price: 16344.08, change_amount: 292.76, change_percent: 1.82 },
  { name: '创业板指', code: '399006', price: 4371.99, change_amount: 120.56, change_percent: 2.84 },
  { name: '科创50', code: '000688', price: 2066.33, change_amount: 76.91, change_percent: 3.87 },
];

const TOP_INDEX_ORDER = ['上证指数', '深证成指', '创业板指', '科创50'];

const PAGE_TITLES: Array<[RegExp, string]> = [
  [/^\/$/, '实时大盘'],
  [/^\/market/, '市场概览'],
  [/^\/research\/overview/, '市场概览'],
  [/^\/sentiment/, '市场情绪'],
  [/^\/news/, '消息中心'],
  [/^\/ai/, '智能选股'],
  [/^\/factors/, '因子研究'],
  [/^\/calendar/, '交易日历'],
  [/^\/strategy/, '策略开发'],
  [/^\/backtest/, '回测中心'],
  [/^\/review/, '复盘中心'],
  [/^\/paper/, '模拟/实盘交易'],
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
    <div className="flex items-center gap-3">
      <div className="flex h-11 w-11 items-center justify-center rounded-[9px] bg-blue-600 text-white shadow-[0_10px_28px_rgba(37,99,235,0.32)]">
        <Activity className="h-6 w-6" />
      </div>
      <div className="min-w-0">
        <div className="text-[22px] font-black leading-none tracking-tight text-white">
          StockPro <span className="text-slate-400">AI</span>
        </div>
      </div>
    </div>
  );
}

function TopTicker({ indices }: { indices: MarketIndex[] }) {
  const ordered = TOP_INDEX_ORDER
    .map((name) => indices.find((item) => item.name === name))
    .filter((item): item is MarketIndex => Boolean(item));
  const displayIndices = ordered.length >= 4 ? ordered : [...ordered, ...indices.filter((item) => !TOP_INDEX_ORDER.includes(item.name))];

  return (
    <div className="flex min-w-0 items-center gap-7">
      {displayIndices.slice(0, 4).map((item) => {
        const positive = (item.change_percent || 0) >= 0;
        return (
          <div key={item.name} className="min-w-[112px] text-right">
            <div className="text-[12px] font-bold text-slate-500">{item.name}</div>
            <div className={clsx('mt-0.5 text-[13px] font-black tabular-nums', positive ? 'text-up' : 'text-down')}>
              {formatNumber(item.price)} ({positive ? '+' : ''}{formatNumber(item.change_percent)}%)
            </div>
          </div>
        );
      })}
    </div>
  );
}

export const MainLayout = ({ children, title }: MainLayoutProps) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { language, setLanguage } = useStore();
  const { colorScheme, setColorScheme } = useSettingsStore();
  const [showSettings, setShowSettings] = useState(false);
  const [indices, setIndices] = useState<MarketIndex[]>(FALLBACK_INDICES);
  const settingsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    getMarketOverview()
      .then((overview) => {
        if (!cancelled && overview.indices?.length) {
          setIndices(overview.indices);
        }
      })
      .catch(() => {
        if (!cancelled) setIndices(FALLBACK_INDICES);
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
    <div className="flex h-screen overflow-hidden bg-crypto-bg text-slate-100">
      <aside className="hidden w-[264px] shrink-0 flex-col border-r border-crypto-border bg-crypto-card lg:flex">
        <div className="flex h-[106px] items-center border-b border-crypto-border px-3">
          <StockProLogo />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto py-3 pr-3">
          <Navigation orientation="vertical" />
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-hidden bg-crypto-bg">
        <div className="hidden h-[54px] items-center justify-between border-b border-crypto-border bg-crypto-panel px-6 lg:flex" data-testid="stockpro-ai-topbar">
          <h1 className="shrink-0 text-xl font-black tracking-tight text-white">{pageTitle}</h1>
          <div className="ml-6 flex min-w-0 items-center gap-7">
            <TopTicker indices={indices} />
            <span className="inline-flex h-8 items-center gap-2 rounded-full border border-crypto-border bg-crypto-card px-3 text-xs font-black text-red-300">
              <span className="h-2 w-2 rounded-full bg-red-400" />
              已休市
            </span>
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

        <div className="h-full overflow-auto">{children || <Outlet />}</div>
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
