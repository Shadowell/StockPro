import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import NumberFlow from '@number-flow/react';
import { motion, useReducedMotion } from 'motion/react';
import {
  Activity,
  BarChart3,
  Brain,
  Compass,
  Flame,
  Gauge,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
  Star,
  TrendingDown,
  TrendingUp,
  Zap,
  WifiOff,
} from 'lucide-react';
import { healthApi, marketApi } from '../api/client';
import type { FundingRate } from '../types';
import { TOP50_SYMBOLS } from './SymbolSearch';
import SymbolIcon, { extractSymbolBase } from './SymbolIcon';
import MarketSectorHeatmap from './MarketSectorHeatmap';
import { useSettingsStore } from '../stores/useSettingsStore';
import { useTickersWebSocket, type RealtimeTicker } from '../hooks/useWebSocket';

const COIN_NAMES: Record<string, string> = {
  BTC: 'Bitcoin',
  ETH: 'Ethereum',
  USDT: 'Tether',
  BNB: 'BNB',
  XRP: 'XRP',
  USDC: 'USD Coin',
  SOL: 'Solana',
  DOGE: 'Dogecoin',
  ADA: 'Cardano',
  AVAX: 'Avalanche',
  DOT: 'Polkadot',
  LINK: 'Chainlink',
  LTC: 'Litecoin',
  UNI: 'Uniswap',
  NEAR: 'NEAR Protocol',
  APT: 'Aptos',
  ARB: 'Arbitrum',
  OP: 'Optimism',
  SUI: 'Sui',
  PEPE: 'Pepe',
  FIL: 'Filecoin',
  ATOM: 'Cosmos',
  INJ: 'Injective',
  FET: 'Fetch.ai',
  TIA: 'Celestia',
  BCH: 'Bitcoin Cash',
  XLM: 'Stellar',
  WIF: 'dogwifhat',
  RUNE: 'THORChain',
  AAVE: 'Aave',
  MATIC: 'Polygon',
  STX: 'Stacks',
  IMX: 'Immutable X',
  SEI: 'Sei',
  LAB: 'LAB',
  BILL: 'Billions Network',
  USELESS: 'Useless Coin',
  UB: 'Unibase',
  XAU: 'Gold',
  XAG: 'Silver',
  OPENAI: 'OpenAI Pre-IPO',
  SPACEX: 'SpaceX Pre-IPO',
  ANTHROPIC: 'Anthropic Pre-IPO',
  SNDK: 'SanDisk',
  MU: 'Micron',
  NVDA: 'NVIDIA',
  AMD: 'AMD',
  TSLA: 'Tesla',
  CRCL: 'Circle',
  EWY: 'Korea ETF',
};

const CATEGORIES = [
  { key: 'all', label: '全部' },
  { key: 'top', label: '热门' },
] as const;

type MarketCategoryKey = (typeof CATEGORIES)[number]['key'];
type MarketTabKey = 'favorites' | 'crypto' | 'spot' | 'futures';
type SortKey = 'name' | 'price' | 'change' | 'volume' | 'base_volume';
type SortDir = 'asc' | 'desc';
type SectorTickerSource = RealtimeTicker & {
  sectorKey?: string;
  sectorName?: string;
  taxonomyVersion?: string;
  sector_key?: string;
  sector_name?: string;
  taxonomy_version?: string;
};

const TOP_CATEGORY_LIMIT = 12;
const MARKET_RANKING_LIMIT = 5;
const HOME_RANKING_LIMIT = 10;

function toUsdtSwapSymbol(symbol: string): string {
  const base = symbol.split('/')[0];
  return `${base}/USDT:USDT`;
}

const MARKET_TAB_SYMBOLS: Record<Exclude<MarketTabKey, 'favorites'>, string[]> = {
  crypto: TOP50_SYMBOLS,
  spot: [
    'ETH/BTC', 'SOL/BTC', 'XRP/BTC', 'DOGE/BTC', 'ADA/BTC',
    'LINK/BTC', 'LTC/BTC', 'DOT/BTC', 'AVAX/BTC', 'UNI/BTC',
    'BCH/BTC', 'ATOM/BTC', 'NEAR/BTC', 'FIL/BTC', 'AAVE/BTC',
  ],
  futures: TOP50_SYMBOLS.slice(0, 32).map(toUsdtSwapSymbol),
};

const NEW_LISTING_SYMBOLS = [
  'LAB/USDT:USDT',
  'BILL/USDT:USDT',
  'USELESS/USDT:USDT',
  'UB/USDT:USDT',
  'MUBARAK/USDT:USDT',
  'PUMP/USDT:USDT',
  'LINEA/USDT:USDT',
  'WLFI/USDT:USDT',
  'XPL/USDT:USDT',
  'ZORA/USDT:USDT',
] as const;

const TRADFI_SYMBOLS = [
  'XAU/USDT:USDT',
  'XAG/USDT:USDT',
  'OPENAI/USDT:USDT',
  'SPCX/USDT:USDT',
  'ANTHROPIC/USDT:USDT',
  'NVDA/USDT:USDT',
  'AMD/USDT:USDT',
  'TSLA/USDT:USDT',
  'SNDK/USDT:USDT',
  'MU/USDT:USDT',
  'CRCL/USDT:USDT',
  'EWY/USDT:USDT',
] as const;


type HomeTickerRankingKey = 'hot' | 'new' | 'tradfi' | 'gainers' | 'losers';
type HomeRankingKey = HomeTickerRankingKey | 'funding';

const HOME_RANKING_TABS: { key: HomeRankingKey; label: string; desc: string; icon: ReactNode }[] = [
  { key: 'hot', label: '成交额榜', desc: '当日成交额', icon: <Flame className="h-4 w-4 text-amber-300" /> },
  { key: 'gainers', label: '涨幅榜', desc: '当日涨幅', icon: <TrendingUp className="h-4 w-4 text-emerald-300" /> },
  { key: 'losers', label: '跌幅榜', desc: '当日跌幅', icon: <TrendingDown className="h-4 w-4 text-rose-300" /> },
];
const HOME_TICKER_RANKING_GRID =
  'grid-cols-[minmax(220px,1.45fr)_96px_76px_88px_100px_108px_96px]';
const HOME_TICKER_RANKING_VALUE_CLASS = 'self-start pt-0.5';
const HOME_RANKING_TABLE_HEADER_CLASS =
  'sticky top-0 z-10 grid items-center gap-x-3 border-y border-slate-500/25 bg-slate-800/80 px-4 py-2.5 text-xs font-semibold tracking-[0.04em] text-slate-200 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] backdrop-blur';

const MARKET_TABS: { key: MarketTabKey; label: string }[] = [
  { key: 'futures', label: '股票' },
  { key: 'crypto', label: 'ETF' },
  { key: 'spot', label: '指数' },
  { key: 'favorites', label: '自选' },
];

const MARKET_TAB_META: Record<MarketTabKey, { title: string; desc: string; accent: string }> = {
  favorites: {
    title: '自选观察池',
    desc: '跟踪你收藏的核心标的，适合快速复盘关注列表的涨跌和成交活跃度。',
    accent: 'text-amber-300',
  },
  crypto: {
    title: 'ETF 市场',
    desc: '覆盖高流动性 ETF，用于观察主题资金、成交额和强弱排序。',
    accent: 'text-sky-300',
  },
  spot: {
    title: '指数市场',
    desc: '展示主要指数，用于判断大盘、风格和主题轮动。',
    accent: 'text-violet-300',
  },
  futures: {
    title: '股票市场',
    desc: '聚焦 A 股现货标的的涨跌、成交额和策略候选。',
    accent: 'text-emerald-300',
  },
};

const HOME_SUMMARY_META = {
  title: 'A 股市场榜单',
  desc: '聚合股票、ETF、指数和当日强弱排行，帮助先看市场氛围，再进入行情页查看具体 K 线。',
  accent: 'text-blue-300',
};

interface TickerData {
  symbol: string;
  coin: string;
  quote: string;
  isContract: boolean;
  displayName: string;
  displayDetails: string;
  name: string;
  last: number;
  change_percent: number;
  high: number;
  low: number;
  volume: number;
  quote_volume: number;
  sparkline: number[];
  sector_key: string;
  sector_name: string;
  taxonomy_version: string;
}

interface MarketSentimentMetric {
  key: string;
  label: string;
  score: number | null;
  status: string;
  detail: string;
  meta: string;
  tone: 'blue' | 'emerald' | 'amber' | 'rose' | 'violet';
  icon: ReactNode;
}

interface MarketSentimentModel {
  score: number;
  label: string;
  summary: string;
  components: MarketSentimentMetric[];
}

interface MarketUniversePanelProps {
  selectedExchange: string;
  onSelectSymbol: (symbol: string) => void;
  variant?: 'summary' | 'full';
  className?: string;
}

function isContractSymbol(symbol: string): boolean {
  return symbol.includes(':') || symbol.toUpperCase().includes('-SWAP');
}

function contractInstrumentId(symbol: string): string {
  if (symbol.toUpperCase().includes('-SWAP')) return symbol.toUpperCase();
  const [base, rest = 'USDT'] = symbol.split('/');
  const quote = rest.split(':')[0] || 'USDT';
  return `${base}-${quote}-SWAP`.toUpperCase();
}

function contractDisplayName(symbol: string): string {
  const [base, rest = 'USDT'] = symbol.split('/');
  const quote = rest.split(':')[0] || 'USDT';
  return `${base}${quote} 永续`;
}

function quoteFromSymbol(symbol: string): string {
  const quotePart = symbol.split('/')[1] || 'USDT';
  return quotePart.split(':')[0] || 'USDT';
}

function contractDisplayDetails(symbol: string): string {
  const quote = quoteFromSymbol(symbol);
  return `${symbol} · ${quote} 本位 · 线性永续`;
}

function isUsdQuote(quote: string): boolean {
  return ['USD', 'USDT', 'USDC'].includes(quote.toUpperCase());
}

function formatNum(num: number): string {
  if (num >= 10000) return num.toLocaleString('en-US', { maximumFractionDigits: 0 });
  if (num >= 100) return num.toFixed(2);
  if (num >= 1) return num.toFixed(4);
  if (num >= 0.01) return num.toFixed(5);
  return num.toFixed(6);
}

function formatVolume(vol: number): string {
  if (vol >= 1e9) return `$${(vol / 1e9).toFixed(2)}B`;
  if (vol >= 1e6) return `$${(vol / 1e6).toFixed(1)}M`;
  if (vol >= 1e3) return `$${(vol / 1e3).toFixed(0)}K`;
  return `$${vol.toFixed(0)}`;
}

function formatPrice(num: number, quote: string): string {
  return isUsdQuote(quote) ? `$${formatNum(num)}` : `${formatNum(num)} ${quote}`;
}

function formatQuoteVolume(vol: number, quote: string): string {
  if (vol == null || !Number.isFinite(vol) || vol <= 0) return '—';
  if (isUsdQuote(quote)) return formatVolume(vol);
  if (vol >= 1e9) return `${(vol / 1e9).toFixed(2)}B ${quote}`;
  if (vol >= 1e6) return `${(vol / 1e6).toFixed(2)}M ${quote}`;
  if (vol >= 1e3) return `${(vol / 1e3).toFixed(2)}K ${quote}`;
  if (vol >= 1) return `${vol.toFixed(2)} ${quote}`;
  return `${vol.toFixed(6)} ${quote}`;
}

function formatSignedPercent(value: number): string {
  if (!Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function clampScore(value: number): number {
  if (!Number.isFinite(value)) return 50;
  return Math.max(0, Math.min(100, Math.round(value)));
}

function formatRatio(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${value.toFixed(digits)}%`;
}

function formatFundingRate(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${(value * 100).toFixed(4)}%`;
}

function formatAnnualizedFunding(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${(value * 3 * 365 * 100).toFixed(2)}%`;
}

function formatFundingTime(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const timestamp = value > 10_000_000_000 ? value : value * 1000;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatBaseVolume(vol: number, coin: string): string {
  if (vol == null || !Number.isFinite(vol) || vol <= 0) return '—';
  const unit = ` ${coin}`;
  if (vol >= 1e9) return `${(vol / 1e9).toFixed(2)}B${unit}`;
  if (vol >= 1e6) return `${(vol / 1e6).toFixed(2)}M${unit}`;
  if (vol >= 1e3) return `${(vol / 1e3).toFixed(2)}K${unit}`;
  if (vol >= 1) return `${vol.toFixed(2)}${unit}`;
  return `${vol.toFixed(4)}${unit}`;
}

function generateSparkline(low: number, high: number, last: number, changePct: number): number[] {
  const points = 24;
  const data: number[] = [];
  const range = high - low || 1;
  const open = last / (1 + changePct / 100);

  for (let i = 0; i < points; i++) {
    const progress = i / (points - 1);
    const trend = open + (last - open) * progress;
    const noise = (Math.sin(i * 2.5 + changePct) * 0.3 + Math.cos(i * 1.7) * 0.2) * range * 0.15;
    data.push(Math.max(low, Math.min(high, trend + noise)));
  }

  data[data.length - 1] = last;
  return data;
}

function SparklineChart({ data, isUp }: { data: number[]; isUp: boolean }) {
  const { upColor, downColor } = useSettingsStore((s) => s.getColors());

  if (!data || data.length < 2) return <div className="h-[28px] w-[86px]" />;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const width = 86;
  const height = 28;
  const padding = 2;
  const points = data.map((val, i) => {
    const x = padding + (i / (data.length - 1)) * (width - padding * 2);
    const y = height - padding - ((val - min) / range) * (height - padding * 2);
    return `${x},${y}`;
  }).join(' ');

  return (
    <svg width={width} height={height} className="shrink-0">
      <polyline
        points={points}
        fill="none"
        stroke={isUp ? upColor : downColor}
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function RangeBar({ low, high, current, quote: _quote }: { low: number; high: number; current: number; quote: string }) {
  const range = high - low || 1;
  const pct = Math.max(0, Math.min(100, ((current - low) / range) * 100));

  return (
    <div className="inline-flex h-7 w-[88px] items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.035] px-2 text-[10px] text-gray-500">
      <span className="font-semibold text-gray-400">1D</span>
      <div className="relative h-1 min-w-0 flex-1 rounded-full bg-gray-700">
        <div
          className="absolute top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full bg-white"
          style={{ left: `${pct}%` }}
        />
      </div>
      <span className="w-6 text-right font-mono tabular-nums text-gray-400">{Number.isFinite(pct) ? `${pct.toFixed(0)}` : '—'}</span>
    </div>
  );
}

function MarketRankingPanel({
  title,
  subtitle,
  icon,
  items,
  metric,
  onSelect,
}: {
  title: string;
  subtitle: string;
  icon: ReactNode;
  items: TickerData[];
  metric: (item: TickerData) => ReactNode;
  onSelect: (symbol: string) => void;
}) {
  return (
    <div className="rounded-lg border border-crypto-border bg-crypto-card/90">
      <div className="flex items-center justify-between border-b border-crypto-border/60 px-4 py-3">
        <div className="flex items-center gap-2">
          {icon}
          <div>
            <div className="text-sm font-semibold text-gray-100">{title}</div>
            <div className="mt-0.5 text-[11px] text-gray-500">{subtitle}</div>
          </div>
        </div>
        <span className="rounded border border-white/10 bg-white/[0.04] px-2 py-1 text-[10px] text-gray-500">
          Top {MARKET_RANKING_LIMIT}
        </span>
      </div>
      <div className="divide-y divide-crypto-border/40">
        {items.length === 0 ? (
          <div className="px-4 py-5 text-center text-xs text-gray-500">暂无排行数据</div>
        ) : (
          items.map((item, index) => (
            <button
              key={item.symbol}
              type="button"
              onClick={() => onSelect(item.symbol)}
              className="grid w-full grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-gray-800/45"
            >
              <span className={`flex h-6 w-6 items-center justify-center rounded-md text-xs font-semibold ${
                index < 3 ? 'bg-blue-500/15 text-blue-300' : 'bg-white/[0.04] text-gray-500'
              }`}>
                {index + 1}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold text-gray-100">{item.displayName}</span>
                <span className="mt-0.5 block truncate text-[11px] text-gray-500">{item.displayDetails}</span>
              </span>
              <span className="text-right text-sm font-semibold tabular-nums">
                {metric(item)}
              </span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}

function HomeRankingBoard({
  activeKey,
  onActiveKeyChange,
  items,
  fundingItems,
  onSelect,
}: {
  activeKey: HomeRankingKey;
  onActiveKeyChange: (key: HomeRankingKey) => void;
  items: TickerData[];
  fundingItems: FundingRate[];
  onSelect: (symbol: string) => void;
}) {
  const activeTab = HOME_RANKING_TABS.find((tab) => tab.key === activeKey) || HOME_RANKING_TABS[0];
  const isFundingTab = activeKey === 'funding';
  const activeCount = isFundingTab ? fundingItems.length : items.length;

  return (
    <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-[260px_minmax(0,1fr)]">
      <aside className="overflow-hidden rounded-xl border border-blue-500/15 bg-crypto-card/90 shadow-[0_14px_36px_rgba(2,8,23,0.14)]">
        <div className="border-b border-crypto-border/60 bg-slate-950/30 px-4 py-3">
          <div className="mb-1 text-[9px] font-semibold uppercase tracking-[0.2em] text-blue-300/65">Market Ranking</div>
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-blue-300" />
            <div>
              <div className="text-sm font-semibold text-gray-100">榜单列表</div>
              <div className="mt-0.5 text-[11px] text-gray-500">选择榜单后查看右侧明细</div>
            </div>
          </div>
        </div>

        <div className="divide-y divide-crypto-border/40">
          {HOME_RANKING_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              aria-pressed={activeKey === tab.key}
              onClick={() => onActiveKeyChange(tab.key)}
              className={`flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors ${
                activeKey === tab.key
                  ? 'border-l-2 border-blue-400 bg-blue-600/20 pl-3.5 text-white shadow-[inset_12px_0_24px_rgba(37,99,235,0.08)]'
                  : 'text-gray-500 hover:bg-white/[0.04] hover:text-gray-200'
              }`}
            >
              <span className="flex min-w-0 items-center gap-2">
                {tab.icon}
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold">{tab.label}</span>
                  <span className="mt-0.5 block truncate text-[11px] text-gray-500">{tab.desc}</span>
                </span>
              </span>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                activeKey === tab.key
                  ? 'bg-blue-500 text-white'
                  : 'bg-white/[0.05] text-gray-500'
              }`}>
                Top {HOME_RANKING_LIMIT}
              </span>
            </button>
          ))}
        </div>
      </aside>

      <section className="overflow-hidden rounded-xl border border-blue-500/15 bg-crypto-card/90 shadow-[0_14px_36px_rgba(2,8,23,0.14)]">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border/60 bg-slate-950/25 px-4 py-3">
          <div className="flex items-center gap-2">
            {activeTab.icon}
            <div>
              <div className="text-sm font-semibold text-gray-100">{activeTab.label}明细</div>
              <div className="mt-0.5 text-[11px] text-gray-500">
                {isFundingTab ? 'A股证据' : '本地行情'} · {activeTab.desc}
              </div>
            </div>
          </div>
          <span className="rounded border border-white/10 bg-white/[0.04] px-2 py-1 text-[10px] text-gray-500">
            {activeCount} / {HOME_RANKING_LIMIT} 个标的
          </span>
        </div>

        <div className="h-[560px] overflow-auto">
          {isFundingTab ? (
            <div className="min-w-[820px]">
              <div className={`${HOME_RANKING_TABLE_HEADER_CLASS} grid-cols-[minmax(180px,1.2fr)_132px_132px_156px_150px_120px]`}>
                <span>标的</span>
                <span>当前资金费率</span>
                <span>年化估算</span>
                <span>下次结算</span>
                <span>标记价</span>
                <span>交易所</span>
              </div>

              {fundingItems.length === 0 ? (
                <div className="flex h-[520px] items-center justify-center px-4 text-center text-sm text-gray-500">
                  当前接口暂无 {activeTab.label} 数据
                </div>
              ) : (
                <div className="divide-y divide-crypto-border/40">
                  {fundingItems.map((item, index) => {
                    const isPositive = item.currentRate >= 0;
                    const coin = extractSymbolBase(item.symbol) || item.symbol;
                    return (
                      <button
                        key={`${item.exchange}-${item.symbol}`}
                        type="button"
                        onClick={() => onSelect(item.symbol)}
                        className="grid w-full grid-cols-[minmax(180px,1.2fr)_132px_132px_156px_150px_120px] items-center gap-x-3 px-4 py-3 text-left transition-colors hover:bg-gray-800/45"
                      >
                        <span className="flex min-w-0 items-center gap-3">
                          <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-xs font-semibold ${
                            index < 3 ? 'bg-amber-500/15 text-amber-300' : 'bg-white/[0.04] text-gray-500'
                          }`}>
                            {index + 1}
                          </span>
                          <SymbolIcon symbol={item.symbol} base={coin} size="md" />
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-semibold text-gray-100">{contractDisplayName(item.symbol)}</span>
                            <span className="mt-0.5 block truncate text-[11px] text-gray-500">{item.symbol}</span>
                          </span>
                        </span>
                        <span className={`font-mono text-sm font-semibold tabular-nums ${isPositive ? 'text-up' : 'text-down'}`}>
                          {formatFundingRate(item.currentRate)}
                        </span>
                        <span className={`font-mono text-sm tabular-nums ${isPositive ? 'text-up' : 'text-down'}`}>
                          {formatAnnualizedFunding(item.currentRate)}
                        </span>
                        <span className="font-mono text-sm tabular-nums text-gray-400">
                          {formatFundingTime(item.nextFundingTime)}
                        </span>
                        <span className="font-mono text-sm tabular-nums text-gray-400">
                          {item.markPrice ? formatPrice(item.markPrice, quoteFromSymbol(item.symbol)) : '—'}
                        </span>
                        <span className="text-xs font-semibold uppercase text-gray-500">
                          {item.exchange || 'CN'}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          ) : (
            <div className="min-w-[1180px]">
              <div className={`${HOME_RANKING_TABLE_HEADER_CLASS} ${HOME_TICKER_RANKING_GRID}`}>
                <span>标的</span>
                <span>最新价</span>
                <span>当日涨跌</span>
                <span className="text-center">当日走势</span>
                <span>当日成交量</span>
                <span>当日成交额</span>
                <span>当日区间</span>
              </div>

              {items.length === 0 ? (
              <div className="flex h-[520px] items-center justify-center px-4 text-center text-sm text-gray-500">
                当前接口暂无 {activeTab.label} 数据
              </div>
              ) : (
                <div className="divide-y divide-crypto-border/40">
                  {items.map((item, index) => (
                    <button
                      key={item.symbol}
                      type="button"
                      onClick={() => onSelect(item.symbol)}
                      className={`grid w-full ${HOME_TICKER_RANKING_GRID} items-center gap-x-3 px-4 py-3 text-left transition-colors hover:bg-gray-800/45`}
                    >
                      <span className="flex min-w-0 items-center gap-3">
                        <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-xs font-semibold ${
                          index < 3 ? 'bg-blue-500/15 text-blue-300' : 'bg-white/[0.04] text-gray-500'
                        }`}>
                          {index + 1}
                        </span>
                        <SymbolIcon symbol={item.symbol} base={item.coin} size="md" />
                        <span className="min-w-0 flex-1">
                          <span className="flex min-w-0 items-center gap-2">
                            <span className="min-w-0 flex-1 truncate text-sm font-semibold text-gray-100" title={item.displayName}>
                              {item.displayName}
                            </span>
                            {item.isContract && (
                              <span className="shrink-0 rounded border border-amber-500/25 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium leading-none text-amber-300">
                                SWAP
                              </span>
                            )}
                          </span>
                          <span className="mt-0.5 block truncate text-[11px] text-gray-500">
                            {formatQuoteVolume(item.quote_volume, item.quote)}
                          </span>
                        </span>
                      </span>
                      <span className={`${HOME_TICKER_RANKING_VALUE_CLASS} font-mono text-sm tabular-nums text-gray-100`}>
                        {formatPrice(item.last, item.quote)}
                      </span>
                      <span className={`${HOME_TICKER_RANKING_VALUE_CLASS} font-mono text-sm tabular-nums ${
                        item.change_percent >= 0 ? 'text-up' : 'text-down'
                      }`}>
                        {formatSignedPercent(item.change_percent)}
                      </span>
                      <span className={`${HOME_TICKER_RANKING_VALUE_CLASS} flex justify-center`}>
                        <SparklineChart data={item.sparkline} isUp={item.change_percent >= 0} />
                      </span>
                      <span className={`${HOME_TICKER_RANKING_VALUE_CLASS} truncate font-mono text-sm tabular-nums text-gray-400`} title={`${item.volume} ${item.coin}`}>
                        {formatBaseVolume(item.volume, item.coin)}
                      </span>
                      <span className={`${HOME_TICKER_RANKING_VALUE_CLASS} font-mono text-sm tabular-nums text-gray-400`}>
                        {formatQuoteVolume(item.quote_volume, item.quote)}
                      </span>
                      <div className={HOME_TICKER_RANKING_VALUE_CLASS}>
                        <RangeBar low={item.low} high={item.high} current={item.last} quote={item.quote} />
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

const SENTIMENT_TONE_CLASSES: Record<MarketSentimentMetric['tone'], { border: string; bg: string; text: string; bar: string }> = {
  blue: {
    border: 'border-blue-500/20',
    bg: 'bg-blue-500/[0.07]',
    text: 'text-blue-300',
    bar: 'bg-blue-400',
  },
  emerald: {
    border: 'border-emerald-500/20',
    bg: 'bg-emerald-500/[0.07]',
    text: 'text-emerald-300',
    bar: 'bg-emerald-400',
  },
  amber: {
    border: 'border-amber-500/20',
    bg: 'bg-amber-500/[0.07]',
    text: 'text-amber-300',
    bar: 'bg-amber-400',
  },
  rose: {
    border: 'border-rose-500/20',
    bg: 'bg-rose-500/[0.07]',
    text: 'text-rose-300',
    bar: 'bg-rose-400',
  },
  violet: {
    border: 'border-violet-500/20',
    bg: 'bg-violet-500/[0.07]',
    text: 'text-violet-300',
    bar: 'bg-violet-400',
  },
};

function sentimentLabel(score: number): string {
  if (score >= 72) return '风险偏好强';
  if (score >= 58) return '偏多活跃';
  if (score <= 28) return '避险降温';
  if (score <= 42) return '偏弱谨慎';
  return '中性震荡';
}

function HomeMarketSummaryModule({
  sentiment,
  evidenceStatus,
  overviewCards,
}: {
  sentiment: MarketSentimentModel;
  evidenceStatus: 'loading' | 'ready' | 'error';
  overviewCards: ReactNode;
}) {
  const prefersReducedMotion = useReducedMotion();
  const scoreTone = sentiment.score >= 58 ? 'text-emerald-300' : sentiment.score <= 42 ? 'text-rose-300' : 'text-amber-300';

  return (
    <motion.section
      className="overflow-hidden rounded-xl border border-blue-500/15 bg-crypto-card/95 shadow-[0_18px_48px_rgba(2,8,23,0.2)]"
      initial={prefersReducedMotion ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: 'easeOut' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border/60 bg-slate-950/30 px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-blue-500/25 bg-blue-500/10">
            <Brain className="h-5 w-5 text-blue-300" />
          </div>
          <div>
            <div className="text-[9px] font-semibold uppercase tracking-[0.2em] text-blue-300/65">Market Intelligence</div>
            <h2 className="mt-0.5 text-base font-semibold text-gray-100">A 股市场概览 · 大盘广度指数</h2>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <span className="rounded-lg border border-blue-400/20 bg-blue-500/10 px-3 py-1.5 text-xs text-blue-200">
            全部 A 股
          </span>
          <span className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-gray-400">
            市场证据 {evidenceStatus === 'loading' ? '读取中' : evidenceStatus === 'ready' ? '已接入' : '读取失败'}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-[280px_repeat(5,minmax(0,1fr))]">
        <div className="relative overflow-hidden rounded-xl border border-blue-500/20 bg-slate-950/55 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] 2xl:row-span-2">
          <div className="absolute inset-y-0 left-0 w-1 bg-blue-400/70" />
          <div className="flex items-center justify-between text-xs text-gray-500">
            <span>综合分</span>
            <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-blue-300/60">Sentiment</span>
          </div>
          <div className="mt-3 flex items-end justify-between gap-3">
            <div className={`text-6xl font-black leading-none tabular-nums ${scoreTone}`}>
              <NumberFlow value={sentiment.score} willChange />
            </div>
            <div className="mb-1 flex h-11 w-11 items-center justify-center rounded-full border border-blue-400/25 bg-blue-500/[0.08]">
              <Gauge className="h-5 w-5 text-blue-300" />
            </div>
          </div>
          <div className="mt-2 text-sm font-semibold text-gray-100">{sentiment.label}</div>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-gray-800">
            <div
              className={`h-full rounded-full bg-gradient-to-r from-rose-400 via-amber-300 to-emerald-400 ${
                prefersReducedMotion ? '' : 'transition-[width] duration-500 ease-out'
              }`}
              style={{ width: `${sentiment.score}%` }}
            />
          </div>
          <div className="mt-2 flex justify-between text-[10px] text-gray-600">
            <span>避险</span>
            <span>中性</span>
            <span>活跃</span>
          </div>
          <div className="mt-4 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-[11px] text-gray-500">
            {sentiment.summary}
          </div>
        </div>

        {overviewCards}

        {sentiment.components.map((metric) => {
          const tone = SENTIMENT_TONE_CLASSES[metric.tone];
          return (
            <motion.div
              key={metric.key}
              layout={!prefersReducedMotion}
              initial={prefersReducedMotion ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.24, ease: 'easeOut' }}
              className={`rounded-xl border ${tone.border} ${tone.bg} p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]`}
            >
              <div className="flex items-center justify-between gap-2">
                <div className={`flex items-center gap-2 text-sm font-semibold ${tone.text}`}>
                  {metric.icon}
                  {metric.label}
                </div>
                <span className="text-lg font-bold tabular-nums text-gray-100">
                  {metric.score == null ? '—' : <NumberFlow value={metric.score} willChange />}
                </span>
              </div>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-gray-900/70">
                <div
                  className={`h-full rounded-full ${tone.bar} ${
                    prefersReducedMotion ? '' : 'transition-[width] duration-500 ease-out'
                  }`}
                  style={{ width: `${metric.score ?? 0}%` }}
                />
              </div>
              <div className="mt-3 text-sm font-semibold text-gray-100">{metric.status}</div>
              <div className="mt-1 truncate text-xs text-gray-400">{metric.detail}</div>
            </motion.div>
          );
        })}
      </div>
    </motion.section>
  );
}

export default function MarketUniversePanel({
  selectedExchange,
  onSelectSymbol,
  variant = 'full',
  className = '',
}: MarketUniversePanelProps) {
  const isSummary = variant === 'summary';
  const [tickers, setTickers] = useState<TickerData[]>([]);
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [apiStatus, setApiStatus] = useState<string>('checking');
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState<MarketCategoryKey>('all');
  const [favorites, setFavorites] = useState<Set<string>>(() => {
    const saved = localStorage.getItem('bitpro_favorites');
    return saved ? new Set(JSON.parse(saved)) : new Set(['600519.SH', '000001.SZ', '300750.SZ']);
  });
  const [sortKey, setSortKey] = useState<SortKey>('volume');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [activeTab, setActiveTab] = useState<MarketTabKey>('futures');
  const [homeRankingKey, setHomeRankingKey] = useState<HomeRankingKey>('hot');

  const { tickers: wsTickers, isConnected: wsConnected } = useTickersWebSocket(selectedExchange, false);
  const sparklineCache = useRef<Record<string, number[]>>({});
  const prevPricesRef = useRef<Record<string, number>>({});
  const [priceFlashes, setPriceFlashes] = useState<Record<string, 'up' | 'down'>>({});
  const flashTimersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const toggleFavorite = (symbol: string) => {
    setFavorites((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      localStorage.setItem('bitpro_favorites', JSON.stringify([...next]));
      return next;
    });
  };

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const mapTickerData = useCallback((tickersData: SectorTickerSource[]): TickerData[] => {
    return tickersData.map((t) => {
      const coin = extractSymbolBase(t.symbol);
      const quote = quoteFromSymbol(t.symbol);
      const contract = isContractSymbol(t.symbol);
      const last = t.last ?? 0;
      const high = t.high ?? last;
      const low = t.low ?? last;
      const changePct = t.changePercent ?? t.change_percent ?? 0;
      const rawBase = t.volume ?? t.baseVolume ?? 0;
      const baseVol = typeof rawBase === 'number' ? rawBase : Number(rawBase) || 0;
      let quoteVol = (t.quoteVolume ?? t.quote_volume ?? 0) as number;
      if ((!quoteVol || !Number.isFinite(quoteVol)) && last > 0 && baseVol > 0) {
        quoteVol = baseVol * last;
      }
      const cached = sparklineCache.current[t.symbol];
      const sparkline = cached && cached.length >= 2
        ? [...cached.slice(-23), last]
        : generateSparkline(low, high, last, changePct);
      sparklineCache.current[t.symbol] = sparkline;

      return {
        symbol: t.symbol,
        coin,
        quote,
        isContract: contract,
        displayName: contract ? contractDisplayName(t.symbol) : (t.name || '名称待同步'),
        displayDetails: contract ? contractDisplayDetails(t.symbol) : t.symbol,
        name: contract ? (COIN_NAMES[coin] || coin) : (t.name || ''),
        last,
        change_percent: changePct,
        high,
        low,
        volume: baseVol,
        quote_volume: quoteVol,
        sparkline,
        sector_key: t.sectorKey ?? t.sector_key ?? 'other',
        sector_name: t.sectorName ?? t.sector_name ?? '其他',
        taxonomy_version: t.taxonomyVersion ?? t.taxonomy_version ?? '—',
      };
    });
  }, []);

  const favoritesKey = useMemo(() => (
    activeTab === 'favorites' ? Array.from(favorites).join('|') : ''
  ), [activeTab, favorites]);

  const requestedSymbols = useMemo(() => {
    if (isSummary) return [];
    const symbols = activeTab === 'favorites'
      ? (favoritesKey ? favoritesKey.split('|') : [])
      : MARKET_TAB_SYMBOLS[activeTab];
    return symbols.filter((symbol) => typeof symbol === 'string' && symbol.trim());
  }, [activeTab, favoritesKey, isSummary]);

  const fetchAllTickers = useCallback(async () => {
    try {
      if (!isSummary && requestedSymbols.length === 0) {
        setTickers([]);
        return;
      }
      const tickersData = isSummary
        ? await marketApi.getAllTickers(selectedExchange)
        : await marketApi.getTickers(selectedExchange, requestedSymbols);
      setTickers(mapTickerData(tickersData as RealtimeTicker[]));
    } catch (err) {
      console.error('Failed to fetch tickers:', err);
    }
  }, [isSummary, selectedExchange, requestedSymbols, mapTickerData]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await fetchAllTickers();
    setIsRefreshing(false);
  };

  useEffect(() => {
    setLoading(true);
    healthApi.check()
      .then(() => setApiStatus('connected'))
      .catch(() => setApiStatus('disconnected'));
    fetchAllTickers().finally(() => setLoading(false));
  }, [fetchAllTickers]);

  useEffect(() => {
    if (activeTab === 'crypto' && wsTickers && wsTickers.length > 0) {
      const items = mapTickerData(wsTickers);
      if (items.length > 0) {
        const newFlashes: Record<string, 'up' | 'down'> = {};
        for (const item of items) {
          const prev = prevPricesRef.current[item.symbol];
          if (prev !== undefined && prev !== item.last && item.last > 0) {
            newFlashes[item.symbol] = item.last > prev ? 'up' : 'down';
          }
          prevPricesRef.current[item.symbol] = item.last;
        }

        if (Object.keys(newFlashes).length > 0) {
          setPriceFlashes((old) => ({ ...old, ...newFlashes }));
          for (const sym of Object.keys(newFlashes)) {
            if (flashTimersRef.current[sym]) clearTimeout(flashTimersRef.current[sym]);
            flashTimersRef.current[sym] = setTimeout(() => {
              setPriceFlashes((old) => {
                const next = { ...old };
                delete next[sym];
                return next;
              });
            }, 600);
          }
        }

        setTickers(items);
        setLoading(false);
        if (apiStatus === 'checking') setApiStatus('connected');
      }
    }
  }, [wsTickers, mapTickerData, apiStatus, activeTab]);

  useEffect(() => {
    if (wsConnected) setApiStatus('connected');
  }, [wsConnected]);

  const displayedTickers = useMemo(() => {
    if (isSummary) return [...tickers];
    let list = [...tickers];
    if (searchQuery) {
      const q = searchQuery.toUpperCase();
      list = list.filter((t) => (
        t.coin.includes(q)
        || t.name.toUpperCase().includes(q)
        || t.symbol.toUpperCase().includes(q)
        || t.displayName.toUpperCase().includes(q)
        || t.displayDetails.toUpperCase().includes(q)
        || contractInstrumentId(t.symbol).includes(q)
      ));
    }

    if (activeTab === 'favorites') {
      list = list.filter((t) => favorites.has(t.symbol));
    } else {
      const tabSymbols = new Set(MARKET_TAB_SYMBOLS[activeTab]);
      list = list.filter((t) => tabSymbols.has(t.symbol));
    }

    if (activeCategory === 'top') {
      list = [...list]
        .sort((a, b) => b.quote_volume - a.quote_volume)
        .slice(0, TOP_CATEGORY_LIMIT);
    }

    list.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case 'name': cmp = a.coin.localeCompare(b.coin); break;
        case 'price': cmp = a.last - b.last; break;
        case 'change': cmp = a.change_percent - b.change_percent; break;
        case 'volume': cmp = a.quote_volume - b.quote_volume; break;
        case 'base_volume': cmp = a.volume - b.volume; break;
      }
      return sortDir === 'desc' ? -cmp : cmp;
    });
    return list;
  }, [tickers, searchQuery, activeCategory, activeTab, favorites, sortKey, sortDir, isSummary]);

  const marketOverview = useMemo(() => {
    const source = displayedTickers;
    const total = source.length;
    const gainers = source.filter((t) => t.change_percent > 0).length;
    const losers = source.filter((t) => t.change_percent < 0).length;
    const flat = Math.max(0, total - gainers - losers);
    const totalTurnover = source.reduce((sum, t) => sum + (Number.isFinite(t.quote_volume) ? t.quote_volume : 0), 0);
    const avgChange = total
      ? source.reduce((sum, t) => sum + (Number.isFinite(t.change_percent) ? t.change_percent : 0), 0) / total
      : 0;
    const breadthPct = total ? Math.round((gainers / total) * 100) : 0;
    const topGainer = source.reduce<TickerData | null>(
      (best, item) => (!best || item.change_percent > best.change_percent ? item : best),
      null,
    );
    const topLoser = source.reduce<TickerData | null>(
      (worst, item) => (!worst || item.change_percent < worst.change_percent ? item : worst),
      null,
    );
    const turnoverLeader = source.reduce<TickerData | null>(
      (best, item) => (!best || item.quote_volume > best.quote_volume ? item : best),
      null,
    );
    const hotRanking = [...source]
      .filter((item) => Number.isFinite(item.quote_volume) && item.quote_volume > 0)
      .sort((a, b) => b.quote_volume - a.quote_volume)
      .slice(0, HOME_RANKING_LIMIT);
    const gainerRanking = [...source]
      .filter((item) => Number.isFinite(item.change_percent))
      .sort((a, b) => b.change_percent - a.change_percent)
      .slice(0, HOME_RANKING_LIMIT);
    const loserRanking = [...source]
      .filter((item) => Number.isFinite(item.change_percent))
      .sort((a, b) => a.change_percent - b.change_percent)
      .slice(0, HOME_RANKING_LIMIT);
    const newListingSet = new Set(NEW_LISTING_SYMBOLS);
    const newListingRanking = [...source]
      .filter((item) => newListingSet.has(item.symbol as (typeof NEW_LISTING_SYMBOLS)[number]))
      .sort((a, b) => b.quote_volume - a.quote_volume)
      .slice(0, HOME_RANKING_LIMIT);
    const tradfiSet = new Set(TRADFI_SYMBOLS);
    const tradfiRanking = [...source]
      .filter((item) => tradfiSet.has(item.symbol as (typeof TRADFI_SYMBOLS)[number]))
      .sort((a, b) => b.quote_volume - a.quote_volume)
      .slice(0, HOME_RANKING_LIMIT);
    const topTurnoverConcentration = totalTurnover > 0
      ? hotRanking.slice(0, 5).reduce((sum, item) => sum + item.quote_volume, 0) / totalTurnover
      : 0;
    const newListingTurnover = [...source]
      .filter((item) => newListingSet.has(item.symbol as (typeof NEW_LISTING_SYMBOLS)[number]))
      .reduce((sum, item) => sum + item.quote_volume, 0);
    const newListingTurnoverRatio = totalTurnover > 0 ? newListingTurnover / totalTurnover : 0;
    const topGainerAvg = gainerRanking.length
      ? gainerRanking.slice(0, 5).reduce((sum, item) => sum + item.change_percent, 0) / Math.min(5, gainerRanking.length)
      : 0;
    const topLoserAvg = loserRanking.length
      ? loserRanking.slice(0, 5).reduce((sum, item) => sum + item.change_percent, 0) / Math.min(5, loserRanking.length)
      : 0;
    const strongestLabel = topGainer ? `${topGainer.displayName} ${formatSignedPercent(topGainer.change_percent)}` : '—';
    const weakestLabel = topLoser ? `${topLoser.displayName} ${formatSignedPercent(topLoser.change_percent)}` : '—';

    return {
      total,
      gainers,
      losers,
      flat,
      totalTurnover,
      avgChange,
      breadthPct,
      topTurnoverConcentration,
      newListingTurnoverRatio,
      topGainerAvg,
      topLoserAvg,
      turnoverLeader,
      gainerRanking,
      hotRanking,
      loserRanking,
      newListingRanking,
      tradfiRanking,
      strongestLabel,
      weakestLabel,
    };
  }, [displayedTickers]);

  const marketSentiment = useMemo<MarketSentimentModel>(() => {
    const breadthScore = marketOverview.breadthPct;
    const avgChangeScore = clampScore(50 + marketOverview.avgChange * 5);
    const concentrationScore = clampScore(50 + marketOverview.topTurnoverConcentration * 70);
    const heatScore = clampScore(breadthScore * 0.42 + avgChangeScore * 0.38 + concentrationScore * 0.2);

    const activityScore = clampScore(35 + Math.min(marketOverview.total, 100) * 0.25 + marketOverview.topTurnoverConcentration * 40);
    const breadthBalanceScore = clampScore(50 + (marketOverview.breadthPct - 50) * 0.8 + marketOverview.avgChange * 4);
    const riskPreferenceScore = clampScore(
      50
      + Math.max(0, marketOverview.topGainerAvg) * 2.2
      + Math.min(0, marketOverview.topLoserAvg) * 0.8,
    );
    const macroScore = 50;

    const weightedComponents = [
      { score: heatScore, weight: 0.3 },
      { score: activityScore, weight: 0.2 },
      { score: breadthBalanceScore, weight: 0.22 },
      { score: riskPreferenceScore, weight: 0.18 },
      { score: macroScore, weight: 0.1 },
    ];
    const weightSum = weightedComponents.reduce((sum, item) => sum + item.weight, 0);
    const score = clampScore(weightedComponents.reduce((sum, item) => sum + (item.score ?? 0) * item.weight, 0) / (weightSum || 1));

    const components: MarketSentimentMetric[] = [
      {
        key: 'heat',
        label: '市场热度',
        score: heatScore,
        status: `成交集中 ${formatRatio(marketOverview.topTurnoverConcentration * 100)}`,
        detail: 'Top5 占视图成交额',
        meta: '结合涨跌广度与成交强度',
        tone: 'emerald',
        icon: <Flame className="h-4 w-4" />,
      },
      {
        key: 'activity',
        label: '成交活跃',
        score: activityScore,
        status: marketOverview.totalTurnover > 0 ? `Top5 集中 ${formatRatio(marketOverview.topTurnoverConcentration * 100)}` : '等待成交证据',
        detail: `覆盖 ${marketOverview.total} 个 A 股标的`,
        meta: `活跃标的 ${marketOverview.turnoverLeader?.displayName || '—'}`,
        tone: 'amber',
        icon: <Zap className="h-4 w-4" />,
      },
      {
        key: 'breadth',
        label: '涨跌广度',
        score: breadthBalanceScore,
        status: marketOverview.breadthPct >= 55 ? '上涨家数占优' : marketOverview.breadthPct <= 45 ? '下跌家数占优' : '涨跌均衡',
        detail: `上涨占比 ${formatRatio(marketOverview.breadthPct)}`,
        meta: `上涨 ${marketOverview.gainers} · 下跌 ${marketOverview.losers} · 平盘 ${marketOverview.flat}`,
        tone: 'blue',
        icon: <Compass className="h-4 w-4" />,
      },
      {
        key: 'risk',
        label: '风险偏好',
        score: riskPreferenceScore,
        status: riskPreferenceScore >= 58 ? '进攻偏好' : riskPreferenceScore <= 42 ? '防御偏好' : '风险中性',
        detail: `领涨均值 ${formatSignedPercent(marketOverview.topGainerAvg)}`,
        meta: `Top5 涨幅均值 ${formatSignedPercent(marketOverview.topGainerAvg)}`,
        tone: 'violet',
        icon: <Sparkles className="h-4 w-4" />,
      },
      {
        key: 'macro',
        label: '交易日证据',
        score: macroScore,
        status: apiStatus === 'connected' ? '行情库已连接' : '数据连接异常',
        detail: 'A 股交易日历已由本地行情库维护',
        meta: '事件临近时提醒，不直接纳入短线信号',
        tone: 'rose',
        icon: <ShieldAlert className="h-4 w-4" />,
      },
    ];

    return {
      score,
      label: sentimentLabel(score),
      summary: `热度 ${heatScore} · 活跃 ${activityScore} · 广度 ${breadthBalanceScore} · 风险偏好 ${riskPreferenceScore}`,
      components,
    };
  }, [apiStatus, marketOverview]);

  const homeRankings = useMemo<Record<HomeTickerRankingKey, TickerData[]>>(() => ({
    hot: marketOverview.hotRanking,
    new: marketOverview.newListingRanking,
    tradfi: marketOverview.tradfiRanking,
    gainers: marketOverview.gainerRanking,
    losers: marketOverview.loserRanking,
  }), [marketOverview]);
  const homeFundingRanking: FundingRate[] = [];
  const activeHomeRankingItems = homeRankingKey === 'funding' ? [] : homeRankings[homeRankingKey];

  const activeTabMeta = isSummary ? HOME_SUMMARY_META : MARKET_TAB_META[activeTab];
  const SortIcon = ({ k }: { k: SortKey }) => (
    <span className="ml-1 inline-flex flex-col text-[8px] leading-[6px] text-gray-500">
      <span className={sortKey === k && sortDir === 'asc' ? 'text-white' : ''}>▲</span>
      <span className={sortKey === k && sortDir === 'desc' ? 'text-white' : ''}>▼</span>
    </span>
  );

  const marketOverviewCards = (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-[1.45fr_repeat(4,minmax(0,1fr))]">
      <div className="rounded-lg border border-crypto-border bg-crypto-card/90 px-4 py-3">
        <div className="flex items-center gap-2">
          <Activity className={`h-4 w-4 ${activeTabMeta.accent}`} />
          <span className="text-sm font-semibold text-gray-100">{activeTabMeta.title}</span>
          <span className="rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-[10px] text-gray-400">
            {selectedExchange.toUpperCase()}
          </span>
        </div>
        <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-gray-500">
          {activeTabMeta.desc}
        </p>
        <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-gray-400">
          <span className="rounded bg-white/[0.04] px-2 py-1">
            当前视图 {marketOverview.total} 个标的
          </span>
          <span className="rounded bg-white/[0.04] px-2 py-1">
            排序 成交额↓
          </span>
        </div>
      </div>
      <div className="rounded-lg border border-emerald-500/15 bg-emerald-500/[0.06] px-4 py-3">
        <div className="flex items-center justify-between text-xs text-emerald-300">
          <span>上涨家数</span>
          <TrendingUp className="h-4 w-4" />
        </div>
        <div className="mt-2 text-2xl font-semibold tabular-nums text-gray-100">
          {marketOverview.gainers}
          <span className="ml-1 text-xs font-normal text-gray-500">/ {marketOverview.total}</span>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-800">
          <div className="h-full rounded-full bg-emerald-400" style={{ width: `${marketOverview.breadthPct}%` }} />
        </div>
      </div>
      <div className="rounded-lg border border-rose-500/15 bg-rose-500/[0.05] px-4 py-3">
        <div className="flex items-center justify-between text-xs text-rose-300">
          <span>下跌 / 平盘</span>
          <TrendingDown className="h-4 w-4" />
        </div>
        <div className="mt-2 text-2xl font-semibold tabular-nums text-gray-100">
          {marketOverview.losers}
          <span className="ml-1 text-xs font-normal text-gray-500">/ {marketOverview.flat}</span>
        </div>
        <div className="mt-2 text-xs text-gray-500">
          平均涨跌 <span className={marketOverview.avgChange >= 0 ? 'text-up' : 'text-down'}>
            {formatSignedPercent(marketOverview.avgChange)}
          </span>
        </div>
      </div>
      <div className="rounded-lg border border-sky-500/15 bg-sky-500/[0.05] px-4 py-3">
        <div className="flex items-center justify-between text-xs text-sky-300">
          <span>视图成交额</span>
          <BarChart3 className="h-4 w-4" />
        </div>
        <div className="mt-2 text-2xl font-semibold tabular-nums text-gray-100">
          {formatQuoteVolume(marketOverview.totalTurnover, displayedTickers[0]?.quote || 'CNY')}
        </div>
        <div className="mt-2 truncate text-xs text-gray-500">
          活跃 {marketOverview.turnoverLeader?.displayName || '—'}
        </div>
      </div>
      <div className="rounded-lg border border-amber-500/15 bg-amber-500/[0.06] px-4 py-3">
        <div className="flex items-center justify-between text-xs text-amber-300">
          <span>强弱标的</span>
          <Gauge className="h-4 w-4" />
        </div>
        <div className="mt-2 truncate text-sm font-semibold text-up">{marketOverview.strongestLabel}</div>
        <div className="mt-1 truncate text-sm font-semibold text-down">{marketOverview.weakestLabel}</div>
      </div>
    </div>
  );

  const homeOverviewCards = (
    <>
      <div className="rounded-xl border border-emerald-500/15 bg-emerald-500/[0.06] p-3">
        <div className="flex items-center justify-between text-xs text-emerald-300">
          <span>上涨家数</span>
          <TrendingUp className="h-4 w-4" />
        </div>
        <div className="mt-2 text-2xl font-semibold tabular-nums text-gray-100">
          <NumberFlow value={marketOverview.gainers} willChange />
          <span className="ml-1 text-xs font-normal text-gray-500">
            / <NumberFlow value={marketOverview.total} willChange />
          </span>
        </div>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-gray-900/70">
          <div className="h-full rounded-full bg-emerald-400" style={{ width: `${marketOverview.breadthPct}%` }} />
        </div>
      </div>

      <div className="rounded-xl border border-rose-500/15 bg-rose-500/[0.05] p-3">
        <div className="flex items-center justify-between text-xs text-rose-300">
          <span>下跌 / 平盘</span>
          <TrendingDown className="h-4 w-4" />
        </div>
        <div className="mt-2 text-2xl font-semibold tabular-nums text-gray-100">
          <NumberFlow value={marketOverview.losers} willChange />
          <span className="ml-1 text-xs font-normal text-gray-500">
            / <NumberFlow value={marketOverview.flat} willChange />
          </span>
        </div>
        <div className="mt-3 truncate text-xs text-gray-500">
          平均涨跌 <span className={marketOverview.avgChange >= 0 ? 'text-up' : 'text-down'}>
            {formatSignedPercent(marketOverview.avgChange)}
          </span>
        </div>
      </div>

      <div className="rounded-xl border border-sky-500/15 bg-sky-500/[0.05] p-3">
        <div className="flex items-center justify-between text-xs text-sky-300">
          <span>视图成交额</span>
          <BarChart3 className="h-4 w-4" />
        </div>
        <div className="mt-2 truncate text-2xl font-semibold tabular-nums text-gray-100">
          {formatQuoteVolume(marketOverview.totalTurnover, displayedTickers[0]?.quote || 'CNY')}
        </div>
        <div className="mt-3 truncate text-xs text-gray-500">
          活跃 {marketOverview.turnoverLeader?.displayName || '—'}
        </div>
      </div>

      <div className="rounded-xl border border-amber-500/15 bg-amber-500/[0.06] p-3">
        <div className="flex items-center justify-between text-xs text-amber-300">
          <span>强弱标的</span>
          <Gauge className="h-4 w-4" />
        </div>
        <div className="mt-2 truncate text-sm font-semibold text-up">{marketOverview.strongestLabel}</div>
        <div className="mt-1 truncate text-sm font-semibold text-down">{marketOverview.weakestLabel}</div>
      </div>
    </>
  );

  const overview = (
    <>
      {isSummary ? (
        <>
          <HomeMarketSummaryModule
            sentiment={marketSentiment}
            evidenceStatus={loading ? 'loading' : apiStatus === 'connected' ? 'ready' : 'error'}
            overviewCards={homeOverviewCards}
          />
          <MarketSectorHeatmap tickers={displayedTickers}
            loading={loading}
            onSelectSymbol={onSelectSymbol}
          />
          <HomeRankingBoard
            activeKey={homeRankingKey}
            onActiveKeyChange={setHomeRankingKey}
            items={activeHomeRankingItems}
            fundingItems={homeFundingRanking}
            onSelect={onSelectSymbol}
          />
        </>
      ) : (
        <>
          {marketOverviewCards}
          <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-2">
            <MarketRankingPanel
              title="涨幅榜"
              subtitle="本地行情 · 当日涨幅"
              icon={<TrendingUp className="h-4 w-4 text-emerald-300" />}
              items={marketOverview.gainerRanking.slice(0, 5)}
              onSelect={onSelectSymbol}
              metric={(item) => (
                <span className={item.change_percent >= 0 ? 'text-up' : 'text-down'}>
                  {formatSignedPercent(item.change_percent)}
                </span>
              )}
            />
            <MarketRankingPanel
              title="热门榜"
              subtitle="本地行情 · 当日成交额"
              icon={<Flame className="h-4 w-4 text-amber-300" />}
              items={marketOverview.hotRanking.slice(0, 5)}
              onSelect={onSelectSymbol}
              metric={(item) => (
                <span className="text-sky-300">{formatQuoteVolume(item.quote_volume, item.quote)}</span>
              )}
            />
          </div>
        </>
      )}
    </>
  );

  if (variant === 'summary') {
    return <div className={className}>{overview}</div>;
  }

  return (
    <div className={`market-universe-panel flex h-[420px] flex-col rounded-lg border border-crypto-border bg-crypto-card ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-blue-400" />
            <h2 className="text-sm font-semibold text-white">市场列表</h2>
            <div className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
              wsConnected
                ? 'border border-green-500/30 bg-green-500/10 text-green-400'
                : apiStatus === 'disconnected'
                  ? 'border border-red-500/30 bg-red-500/10 text-red-400'
                  : 'border border-yellow-500/30 bg-yellow-500/10 text-yellow-400'
            }`}>
              {wsConnected ? (
                <>
                  <span className="relative flex h-1.5 w-1.5">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
                    <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-green-500" />
                  </span>
                  {selectedExchange.toUpperCase()} · 实时行情
                </>
              ) : apiStatus === 'disconnected' ? (
                <>
                  <WifiOff className="h-3 w-3" />
                  已断开
                </>
              ) : (
                <>
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-yellow-400" />
                  连接中...
                </>
              )}
            </div>
          </div>
          <p className="mt-1 text-xs text-gray-500">股票、ETF、指数和自选标的统一在行情页筛选。</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
            <input
              type="text"
              placeholder="搜索 A 股代码..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-48 rounded-lg border border-crypto-border bg-gray-800 py-1.5 pl-8 pr-3 text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
            />
          </div>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-800 hover:text-white"
            title="刷新市场列表"
          >
            <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      <div className="flex items-center space-x-6 border-b border-crypto-border px-4">
        {MARKET_TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`border-b-2 pb-3 pt-3 text-sm font-medium transition-colors ${
              activeTab === tab.key
                ? 'border-white text-white'
                : 'border-transparent text-gray-500 hover:text-gray-300'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex items-center space-x-2 overflow-x-auto px-4 py-3">
        {CATEGORIES.map((cat) => (
          <button
            key={cat.key}
            type="button"
            onClick={() => setActiveCategory(cat.key)}
            className={`whitespace-nowrap rounded-full px-3 py-1 text-xs transition-colors ${
              activeCategory === cat.key
                ? 'bg-gray-700 text-white'
                : 'bg-gray-800/50 text-gray-500 hover:bg-gray-800 hover:text-gray-300'
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-[40px_1fr_120px_88px_120px_120px_120px_1fr] items-center gap-x-1 border-b border-crypto-border/50 px-4 py-2 text-xs text-gray-500">
        <span />
        <button type="button" onClick={() => handleSort('name')} className="flex items-center text-left hover:text-gray-300">
          {activeTab === 'futures' ? '股票' : '证券'} <SortIcon k="name" />
        </button>
        <button type="button" onClick={() => handleSort('price')} className="flex items-center text-left hover:text-gray-300">
          最新价 <SortIcon k="price" />
        </button>
        <button type="button" onClick={() => handleSort('change')} className="flex items-center text-left hover:text-gray-300">
          当日涨跌 <SortIcon k="change" />
        </button>
        <span className="text-center">当日走势</span>
        <button type="button" onClick={() => handleSort('base_volume')} className="flex items-center text-left hover:text-gray-300">
          当日成交量 <SortIcon k="base_volume" />
        </button>
        <button type="button" onClick={() => handleSort('volume')} className="flex items-center text-left hover:text-gray-300">
          当日成交额 <SortIcon k="volume" />
        </button>
        <span className="text-left">当日区间</span>
      </div>

      <div className="flex-1 overflow-y-auto px-4">
        {loading ? (
          <div className="flex items-center justify-center py-20 text-gray-500">
            <RefreshCw className="mr-2 h-5 w-5 animate-spin" /> 加载中...
          </div>
        ) : displayedTickers.length === 0 ? (
          <div className="flex items-center justify-center py-20 text-gray-500">
            {searchQuery ? `未找到 "${searchQuery}" 相关证券` : '暂无数据'}
          </div>
        ) : (
          displayedTickers.map((t) => (
            <div
              key={t.symbol}
              onClick={() => onSelectSymbol(t.symbol)}
              className="grid cursor-pointer grid-cols-[40px_1fr_120px_88px_120px_120px_120px_1fr] items-center gap-x-1 border-b border-crypto-border/30 py-3.5 transition-colors hover:bg-gray-800/40"
            >
              {/* 收藏星 */}
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  toggleFavorite(t.symbol);
                }}
                className="flex items-center justify-center"
              >
                <Star
                  className={`h-4 w-4 ${
                    favorites.has(t.symbol)
                      ? 'fill-yellow-400 text-yellow-400'
                      : 'text-gray-600 hover:text-gray-400'
                  }`}
                />
              </button>
              <div className="flex items-center space-x-3">
                <SymbolIcon symbol={t.symbol} base={t.coin} size="sm" />
                <div className="min-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-sm font-semibold leading-tight text-white">{t.displayName}</span>
                    {t.isContract && (
                      <span className="rounded border border-amber-500/25 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium leading-none text-amber-300">
                        SWAP
                      </span>
                    )}
                  </div>
                  <div
                    className="mt-0.5 truncate text-xs leading-tight text-gray-500"
                    title={t.isContract ? contractInstrumentId(t.symbol) : t.name}
                  >
                    {t.displayDetails}
                  </div>
                </div>
              </div>
              <div className={`-mx-1 rounded px-1 font-mono text-sm transition-all duration-500 ${
                priceFlashes[t.symbol] === 'up'
                  ? 'bg-green-500/20 text-green-400'
                  : priceFlashes[t.symbol] === 'down'
                    ? 'bg-red-500/20 text-red-400'
                    : 'text-white'
              }`}>
                {formatPrice(t.last, t.quote)}
              </div>
              <div className={`-mx-1 rounded px-1 font-mono text-sm transition-all duration-500 ${
                priceFlashes[t.symbol] === 'up'
                  ? 'bg-green-500/15 text-up'
                  : priceFlashes[t.symbol] === 'down'
                    ? 'bg-red-500/15 text-down'
                    : t.change_percent >= 0 ? 'text-up' : 'text-down'
              }`}>
                {t.change_percent >= 0 ? '+' : ''}{t.change_percent.toFixed(2)}%
              </div>
              <div className="flex justify-center">
                <SparklineChart data={t.sparkline} isUp={t.change_percent >= 0} />
              </div>
              <div className="truncate font-mono text-sm tabular-nums text-gray-400" title={`${t.volume} ${t.coin}`}>
                {formatBaseVolume(t.volume, t.coin)}
              </div>
              <div className="font-mono text-sm tabular-nums text-gray-400">
                {formatQuoteVolume(t.quote_volume, t.quote)}
              </div>
              <RangeBar low={t.low} high={t.high} current={t.last} quote={t.quote} />
            </div>
          ))
        )}
      </div>
    </div>
  );
}
