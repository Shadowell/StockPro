type BitProLogoProps = {
  className?: string;
  title?: string;
};

export function BitProLogo({ className = 'h-10 w-10', title = 'StockPro' }: BitProLogoProps) {
  return (
    <svg
      className={className}
      viewBox="0 0 64 64"
      role="img"
      aria-label={title}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id="bitpro-logo-bg" x1="8" y1="6" x2="56" y2="58" gradientUnits="userSpaceOnUse">
          <stop stopColor="#102A56" />
          <stop offset="0.48" stopColor="#08111E" />
          <stop offset="1" stopColor="#020617" />
        </linearGradient>
        <radialGradient id="bitpro-logo-glow" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(44 17) rotate(127) scale(42 35)">
          <stop stopColor="#22D3EE" stopOpacity="0.28" />
          <stop offset="1" stopColor="#22D3EE" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect x="4" y="4" width="56" height="56" rx="16" fill="url(#bitpro-logo-bg)" />
      <rect x="5.5" y="5.5" width="53" height="53" rx="14.5" fill="none" stroke="#2563EB" strokeOpacity="0.95" strokeWidth="3" />
      <rect x="9" y="9" width="46" height="46" rx="12.5" fill="none" stroke="#22D3EE" strokeOpacity="0.16" strokeWidth="1.5" />
      <rect x="10" y="10" width="44" height="44" rx="12" fill="url(#bitpro-logo-glow)" />
      <path d="M13.6 45.2C19.1 51.1 30 52.5 40.2 48C48.4 44.4 53.4 37.1 53.3 29" fill="none" stroke="#2563EB" strokeOpacity="0.38" strokeWidth="3" strokeLinecap="round" />
      <text
        x="32"
        y="44.2"
        textAnchor="middle"
        fontFamily="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
        fontSize="35"
        fontWeight="900"
        fill="#EAF2FF"
        stroke="#06111E"
        strokeWidth="2.4"
        paintOrder="stroke"
      >
        S
      </text>
    </svg>
  );
}
