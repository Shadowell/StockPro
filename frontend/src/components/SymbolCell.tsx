import {
  formatSymbolLabel,
  normalizeSymbolCode,
  resolveSymbolName,
  toPublicSymbol,
} from '../utils/symbolDisplay';

type SymbolCellProps = {
  symbol?: string | null;
  name?: string | null;
  names?: Record<string, string>;
  /** denser table cells */
  compact?: boolean;
  className?: string;
};

/**
 * Always prefer 中文名 as primary label; public code (600000.SH) as secondary.
 * Numbered A-share codes must never render as code-only when a name is available.
 */
export function SymbolCell({
  symbol,
  name,
  names,
  compact = false,
  className,
}: SymbolCellProps) {
  const code = normalizeSymbolCode(symbol);
  const resolved =
    resolveSymbolName(symbol, name) ||
    names?.[code] ||
    names?.[String(symbol ?? '')] ||
    '';
  const publicCode = toPublicSymbol(code) || code || '--';

  if (!resolved) {
    return (
      <div className={className} title={formatSymbolLabel(symbol, name)}>
        <div
          className={
            compact
              ? 'truncate font-mono text-xs font-semibold text-blue-300'
              : 'truncate text-sm font-semibold text-gray-100'
          }
        >
          {publicCode}
        </div>
      </div>
    );
  }

  return (
    <div className={className} title={formatSymbolLabel(symbol, resolved)}>
      <div
        className={
          compact
            ? 'truncate text-xs font-semibold text-slate-100'
            : 'truncate text-sm font-semibold text-gray-100'
        }
      >
        {resolved}
      </div>
      <div
        className={
          compact
            ? 'mt-0.5 font-mono text-[10px] text-slate-500'
            : 'mt-0.5 font-mono text-[11px] text-gray-500'
        }
      >
        {publicCode}
      </div>
    </div>
  );
}

export default SymbolCell;
