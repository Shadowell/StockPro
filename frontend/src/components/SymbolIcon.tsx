import { useEffect, useMemo, useState, type CSSProperties } from 'react';

type SymbolIconSize = 'xs' | 'sm' | 'md' | 'lg';
type SymbolIconShape = 'circle' | 'rounded';

type SymbolIconProps = {
  symbol: string;
  base?: string;
  size?: SymbolIconSize;
  shape?: SymbolIconShape;
  className?: string;
};

const ICON_BASE_URL = 'https://cdn.jsdelivr.net/gh/spothq/cryptocurrency-icons@master/svg/color/';

const SIZE_CLASS: Record<SymbolIconSize, string> = {
  xs: 'h-5 w-5 text-[9px]',
  sm: 'h-6 w-6 text-[10px]',
  md: 'h-8 w-8 text-xs',
  lg: 'h-10 w-10 text-sm',
};

const SHAPE_CLASS: Record<SymbolIconShape, string> = {
  circle: 'rounded-full',
  rounded: 'rounded-lg',
};

const LOGO_SLUG_ALIASES: Record<string, string> = {
  RENDER: 'rndr',
  WBTC: 'btc',
};

const LOCAL_FALLBACK_ONLY = new Set([
  'XAU',
  'XAG',
  'OPENAI',
  'SPCX',
  'SPACEX',
  'ANTHROPIC',
  'NVDA',
  'AMD',
  'TSLA',
  'SNDK',
  'MU',
  'CRCL',
  'EWY',
]);

export function extractSymbolBase(symbol: string | null | undefined): string {
  let text = String(symbol ?? '').trim().toUpperCase();
  if (!text) return '';
  text = text.split(':')[0];
  text = text.replace(/-(USDT|USD|USDC)-SWAP$/i, '');
  if (text.includes('/')) return text.split('/')[0].replace(/[^A-Z0-9]/g, '');
  if (text.includes('-')) return text.split('-')[0].replace(/[^A-Z0-9]/g, '');
  if (text.includes('_')) return text.split('_')[0].replace(/[^A-Z0-9]/g, '');
  return text.replace(/[^A-Z0-9]/g, '');
}

export function getSymbolLogoUrl(symbol: string, base?: string): string | null {
  const source = String(symbol || base || '').trim().toUpperCase();
  const isAShareSymbol =
    /(?:^|[^A-Z0-9])\d{6}\.(?:SH|SZ|BJ)(?:$|[^A-Z0-9])/.test(source) ||
    /(?:^|[^A-Z0-9])(?:SH|SZ|BJ)_\d{6}(?:$|[^A-Z0-9])/.test(source);
  if (isAShareSymbol) return null;
  const resolvedBase = extractSymbolBase(base || symbol);
  if (!resolvedBase || LOCAL_FALLBACK_ONLY.has(resolvedBase)) return null;
  const slug = LOGO_SLUG_ALIASES[resolvedBase] || resolvedBase.toLowerCase();
  return `${ICON_BASE_URL}${slug}.svg`;
}

function fallbackLetters(base: string): string {
  if (!base) return '?';
  return base.length <= 2 ? base : base.slice(0, 2);
}

function symbolHue(base: string): number {
  let hash = 0;
  for (const char of base) {
    hash = (hash * 31 + char.charCodeAt(0)) % 360;
  }
  return (hash + 210) % 360;
}

function fallbackStyle(base: string): CSSProperties {
  const hue = symbolHue(base || 'USDT');
  return {
    backgroundColor: `hsl(${hue} 54% 20%)`,
    borderColor: `hsl(${hue} 70% 42%)`,
    color: `hsl(${hue} 80% 88%)`,
  };
}

export default function SymbolIcon({
  symbol,
  base,
  size = 'sm',
  shape = 'circle',
  className = '',
}: SymbolIconProps) {
  const resolvedBase = extractSymbolBase(base || symbol);
  const logoUrl = useMemo(() => getSymbolLogoUrl(symbol, resolvedBase), [symbol, resolvedBase]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [logoUrl]);

  const showLogo = Boolean(logoUrl && !failed);

  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center overflow-hidden border border-white/10 bg-gray-900/70 align-middle font-bold leading-none tracking-normal ${SIZE_CLASS[size]} ${SHAPE_CLASS[shape]} ${className}`}
      style={!showLogo ? fallbackStyle(resolvedBase) : undefined}
      title={resolvedBase || symbol}
      aria-label={`${resolvedBase || symbol} 图标`}
    >
      {showLogo ? (
        <img
          src={logoUrl || undefined}
          alt={`${resolvedBase} logo`}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          className="h-full w-full object-contain"
          onError={() => setFailed(true)}
        />
      ) : (
        fallbackLetters(resolvedBase)
      )}
    </span>
  );
}
