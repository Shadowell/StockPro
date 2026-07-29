import clsx from 'clsx';

type StockProMarkProps = {
  size?: 'sm' | 'md' | 'lg' | 'xl' | '2xl';
  className?: string;
  title?: string;
  showGlow?: boolean;
};

const SIZE = {
  sm: { shell: 'h-8 w-8 rounded-lg p-1.5', icon: 20 },
  md: { shell: 'h-10 w-10 rounded-xl p-2', icon: 24 },
  lg: { shell: 'h-12 w-12 rounded-xl p-2.5', icon: 28 },
  xl: { shell: 'h-16 w-16 rounded-2xl p-3', icon: 38 },
  '2xl': { shell: 'h-24 w-24 rounded-3xl p-4.5', icon: 58 },
} as const;

/**
 * StockPro Professional Financial Operator Brand Mark
 * 包含：精细盾型/晶格立体铠甲底座、S/P 几何交融力量箭羽、量化多维柱形图层与 AI 信号脉冲环。
 */
export function StockProMark({
  size = 'md',
  className,
  title = 'StockPro 智能投研与量化交易终端',
  showGlow = true,
}: StockProMarkProps) {
  const dim = SIZE[size];

  return (
    <div
      role="img"
      aria-label={title}
      title={title}
      className={clsx(
        'relative inline-flex shrink-0 items-center justify-center overflow-hidden',
        'border border-sky-400/35 bg-gradient-to-b from-[#182335] via-[#0f172a] to-[#080d1a]',
        'shadow-[inset_0_1px_1px_rgba(255,255,255,0.18),0_4px_16px_rgba(0,0,0,0.6)]',
        'transition-all duration-300 hover:border-sky-400/70 hover:shadow-[inset_0_1px_2px_rgba(255,255,255,0.25),0_0_24px_rgba(14,165,233,0.35)]',
        'group',
        dim.shell,
        className,
      )}
    >
      {/* Background ambient glow effect */}
      {showGlow && (
        <div className="absolute -top-1/2 -right-1/2 h-full w-full rounded-full bg-gradient-to-br from-sky-400/20 via-blue-600/10 to-transparent blur-md pointer-events-none transition-opacity duration-300 group-hover:opacity-100" />
      )}

      {/* SVG Icon */}
      <svg
        width={dim.icon}
        height={dim.icon}
        viewBox="0 0 48 48"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="relative z-10 drop-shadow-[0_2px_6px_rgba(0,0,0,0.5)]"
        aria-hidden
      >
        <defs>
          {/* Main Shield Rim Gradient */}
          <linearGradient id="spRimGrad" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#38BDF8" />
            <stop offset="50%" stopColor="#2563EB" />
            <stop offset="100%" stopColor="#4F46E5" />
          </linearGradient>

          {/* Primary Trend Arrow Gradient (Power Surge) */}
          <linearGradient id="spTrendGrad" x1="6" y1="38" x2="42" y2="8" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#38BDF8" />
            <stop offset="45%" stopColor="#60A5FA" />
            <stop offset="85%" stopColor="#3B82F6" />
            <stop offset="100%" stopColor="#10B981" />
          </linearGradient>

          {/* Bar Pillar Gradient (Asset Depth) */}
          <linearGradient id="spBarGrad1" x1="0" y1="18" x2="0" y2="38" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#0EA5E9" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#0284C7" stopOpacity="0.2" />
          </linearGradient>
          <linearGradient id="spBarGrad2" x1="0" y1="12" x2="0" y2="38" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#38BDF8" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#1E40AF" stopOpacity="0.2" />
          </linearGradient>
          <linearGradient id="spBarGrad3" x1="0" y1="6" x2="0" y2="38" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#34D399" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#059669" stopOpacity="0.2" />
          </linearGradient>

          {/* Glowing Node Gradient */}
          <radialGradient id="spGlowRadial" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#34D399" />
            <stop offset="60%" stopColor="#10B981" />
            <stop offset="100%" stopColor="#059669" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Quant Matrix Grid Lines (Subtle background texture) */}
        <line x1="10" y1="38" x2="38" y2="38" stroke="#1E293B" strokeWidth="1" strokeDasharray="2 2" />
        <line x1="10" y1="28" x2="38" y2="28" stroke="#1E293B" strokeWidth="1" strokeDasharray="2 2" />
        <line x1="10" y1="18" x2="38" y2="18" stroke="#1E293B" strokeWidth="1" strokeDasharray="2 2" />

        {/* Financial Candlestick & Volume Pillars (Power base) */}
        <rect x="10" y="26" width="4.5" height="12" rx="1.5" fill="url(#spBarGrad1)" />
        <rect x="18" y="20" width="4.5" height="18" rx="1.5" fill="url(#spBarGrad2)" />
        <rect x="26" y="14" width="4.5" height="24" rx="1.5" fill="url(#spBarGrad2)" />
        <rect x="34" y="8" width="4.5" height="30" rx="1.5" fill="url(#spBarGrad3)" />

        {/* Abstract "S" & "P" High-Power Intertwined Vector Line */}
        {/* Shadow Path for 3D depth */}
        <path
          d="M7 33L16 24L23 29L34 14L41 7"
          stroke="#030712"
          strokeWidth="4.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity="0.6"
        />

        {/* Main Ascending Surge Line */}
        <path
          d="M7 33L16 24L23 29L34 14L41 7"
          stroke="url(#spTrendGrad)"
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Arrow Tip / Breakthrough Peak */}
        <path
          d="M34 7H41V14"
          stroke="url(#spTrendGrad)"
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Signal Trigger Node & Target Radar Rings */}
        <circle cx="41" cy="7" r="4.5" fill="url(#spGlowRadial)" opacity="0.4" />
        <circle cx="41" cy="7" r="2.5" fill="#34D399" />
        <circle cx="41" cy="7" r="1" fill="#FFFFFF" />

        {/* Precision Quant Micro-ticks */}
        <circle cx="16" cy="24" r="1.5" fill="#38BDF8" />
        <circle cx="23" cy="29" r="1.5" fill="#60A5FA" />
        <circle cx="34" cy="14" r="1.5" fill="#818CF8" />
      </svg>
    </div>
  );
}
export default StockProMark;
