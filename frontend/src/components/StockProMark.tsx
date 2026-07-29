import clsx from 'clsx';

type StockProMarkProps = {
  size?: 'sm' | 'md' | 'lg' | 'xl';
  className?: string;
  title?: string;
};

const SIZE = {
  sm: { shell: 'h-8 w-8 rounded-lg p-1.5', icon: 18 },
  md: { shell: 'h-10 w-10 rounded-xl p-2', icon: 22 },
  lg: { shell: 'h-12 w-12 rounded-xl p-2.5', icon: 26 },
  xl: { shell: 'h-16 w-16 rounded-2xl p-3.5', icon: 34 },
} as const;

/**
 * StockPro Redesigned High-End Quant Brand Mark
 * 包含：晶格金属底框、立体柱形资产基石、高精度策略脉冲线与量化突破触点。
 */
export function StockProMark({
  size = 'md',
  className,
  title = 'StockPro 量化交易终端',
}: StockProMarkProps) {
  const dim = SIZE[size];

  return (
    <div
      role="img"
      aria-label={title}
      title={title}
      className={clsx(
        'relative inline-flex shrink-0 items-center justify-center overflow-hidden',
        'border border-sky-400/30 bg-gradient-to-br from-[#151d2a] via-[#0e1420] to-[#090d15]',
        'shadow-[inset_0_1px_0_rgba(255,255,255,0.1),0_4px_12px_rgba(0,0,0,0.5)]',
        'transition-all duration-200 hover:border-sky-400/60 hover:shadow-[0_0_16px_rgba(56,189,248,0.25)]',
        dim.shell,
        className,
      )}
    >
      {/* Background ambient glow effect */}
      <div className="absolute -top-1/2 -right-1/2 h-full w-full rounded-full bg-sky-500/10 blur-md pointer-events-none" />

      {/* SVG Icon */}
      <svg
        width={dim.icon}
        height={dim.icon}
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="relative z-10"
        aria-hidden
      >
        <defs>
          {/* Main Stroke Gradient: Sky Blue -> Indigo */}
          <linearGradient id="stockProStrokeGrad" x1="2" y1="24" x2="30" y2="8" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#38BDF8" />
            <stop offset="60%" stopColor="#60A5FA" />
            <stop offset="100%" stopColor="#818CF8" />
          </linearGradient>

          {/* Bar Fill Gradient: Dark Teal -> Emerald */}
          <linearGradient id="stockProBarGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#38BDF8" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#38BDF8" stopOpacity="0.05" />
          </linearGradient>
        </defs>

        {/* Quant Bar Pillars (Background asset bars) */}
        <rect x="5" y="18" width="3.5" height="9" rx="1.2" fill="url(#stockProBarGrad)" />
        <rect x="11.5" y="13" width="3.5" height="14" rx="1.2" fill="url(#stockProBarGrad)" />
        <rect x="18" y="15" width="3.5" height="12" rx="1.2" fill="url(#stockProBarGrad)" />
        <rect x="24.5" y="8" width="3.5" height="19" rx="1.2" fill="url(#stockProBarGrad)" />

        {/* Dynamic Quant Wave Line */}
        <path
          d="M3 21.5L8.5 16L13.5 19.5L21.5 10.5L29 6"
          stroke="url(#stockProStrokeGrad)"
          strokeWidth="2.75"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Signal Trigger Spark Point */}
        <circle cx="29" cy="6" r="2.5" fill="#34D399" />
        <circle cx="29" cy="6" r="4.5" stroke="#34D399" strokeWidth="0.8" strokeOpacity="0.6" />
      </svg>
    </div>
  );
}

export default StockProMark;
