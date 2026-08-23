import { forwardRef, type SelectHTMLAttributes } from 'react';
import { ChevronDown } from 'lucide-react';
import clsx from 'clsx';

type CryptoSelectSize = 'xs' | 'sm' | 'md' | 'lg';

type CryptoSelectProps = SelectHTMLAttributes<HTMLSelectElement> & {
  controlSize?: CryptoSelectSize;
  fullWidth?: boolean;
  wrapperClassName?: string;
};

const sizeClass: Record<CryptoSelectSize, string> = {
  xs: 'h-8 pl-3 pr-8 text-xs',
  sm: 'h-9 pl-3 pr-9 text-xs',
  md: 'h-10 pl-3.5 pr-10 text-sm',
  lg: 'h-12 pl-4 pr-11 text-sm',
};

const iconClass: Record<CryptoSelectSize, string> = {
  xs: 'right-2 h-3.5 w-3.5',
  sm: 'right-2.5 h-3.5 w-3.5',
  md: 'right-3 h-4 w-4',
  lg: 'right-3.5 h-4 w-4',
};

const CryptoSelect = forwardRef<HTMLSelectElement, CryptoSelectProps>(function CryptoSelect(
  {
    children,
    className,
    controlSize = 'md',
    disabled,
    fullWidth = true,
    wrapperClassName,
    ...props
  },
  ref,
) {
  return (
    <span
      className={clsx(
        'group relative inline-flex min-w-0 items-center',
        fullWidth ? 'w-full' : 'w-auto',
        wrapperClassName,
      )}
    >
      <select
        ref={ref}
        disabled={disabled}
        className={clsx(
          'crypto-select-native min-w-0 appearance-none rounded-xl border border-white/10 bg-[#0b1220]/95 font-semibold text-gray-100 outline-none transition duration-150',
          'shadow-[inset_0_1px_0_rgba(255,255,255,0.04),0_10px_28px_rgba(2,6,23,0.28)]',
          'hover:border-blue-400/40 hover:bg-[#101a2b]',
          'focus:border-blue-400/70 focus:ring-2 focus:ring-blue-500/30',
          'disabled:cursor-not-allowed disabled:border-white/5 disabled:bg-white/[0.035] disabled:text-gray-600',
          sizeClass[controlSize],
          fullWidth ? 'w-full' : 'w-auto',
          className,
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        aria-hidden="true"
        className={clsx(
          'pointer-events-none absolute text-gray-400 transition-colors',
          disabled ? 'text-gray-600' : 'group-hover:text-blue-200',
          iconClass[controlSize],
        )}
      />
    </span>
  );
});

export default CryptoSelect;
