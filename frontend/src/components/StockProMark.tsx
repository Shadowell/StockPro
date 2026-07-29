import clsx from 'clsx';

type StockProMarkProps = {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
  /** Soft pulse ring for live market identity. */
  breathe?: boolean;
  title?: string;
};

const SIZE = {
  sm: { shell: 'h-8 w-8 rounded-lg', icon: 16 },
  md: { shell: 'h-11 w-11 rounded-xl', icon: 22 },
  lg: { shell: 'h-14 w-14 rounded-2xl', icon: 28 },
} as const;

/** StockPro brand mark — rounded shell + single A-share heartbeat stroke. */
export function StockProMark({
  size = 'md',
  className,
  breathe = false,
  title = 'StockPro',
}: StockProMarkProps) {
  const dim = SIZE[size];
  return (
    <div
      role="img"
      aria-label={title}
      title={title}
      className={clsx(
        'relative inline-flex shrink-0 items-center justify-center border border-sky-400/45 bg-[#121a24]',
        dim.shell,
        className,
      )}
    >
      {breathe ? (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-[inherit] border border-sky-400/35 market-session-breath"
        />
      ) : null}
      <svg
        width={dim.icon}
        height={dim.icon}
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden
      >
        <path
          d="M3 12.5H7.2L9.1 8.2L12.05 17.6L14.7 6.4L17.1 12.5H21"
          stroke="#7DD3FC"
          strokeWidth="1.85"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

export default StockProMark;
