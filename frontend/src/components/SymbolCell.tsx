import { formatSymbolLabel, normalizeSymbolCode, resolveSymbolName } from '../utils/symbolDisplay';
import { useSymbolNames } from '../hooks/useSymbolNames';

type SymbolCellProps = {
  symbol?: string | null;
  name?: string | null;
  names?: Record<string, string>;
  compact?: boolean;
  className?: string;
};

export function SymbolCell({ symbol, name, names, compact = false, className }: SymbolCellProps) {
  const code = normalizeSymbolCode(symbol) || '--';
  const fetchedNames = useSymbolNames(name ? [] : [symbol]);
  const resolved = resolveSymbolName(symbol, name) || names?.[code] || names?.[String(symbol || '')] || fetchedNames[code] || '';
  return (
    <div className={className} title={formatSymbolLabel(code, resolved)}>
      <div className={compact ? 'truncate text-xs font-semibold text-gray-100' : 'truncate text-sm font-semibold text-white'}>
        {resolved || '名称待同步'}
      </div>
      <div className={compact ? 'mt-0.5 truncate font-mono text-[10px] text-gray-500' : 'mt-0.5 truncate font-mono text-xs text-gray-500'}>
        {code}
      </div>
    </div>
  );
}

export default SymbolCell;
