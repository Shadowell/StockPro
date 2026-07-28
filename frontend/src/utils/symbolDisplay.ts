const FALLBACK_SYMBOL_NAMES: Record<string, string> = {
  SH_600000: '浦发银行',
  SH_600519: '贵州茅台',
  SZ_000001: '平安银行',
  SZ_000333: '美的集团',
  SZ_000651: '格力电器',
  SZ_002415: '海康威视',
};

export const normalizeSymbolCode = (symbol?: string | null) => {
  const text = String(symbol || '').trim().toUpperCase().replace('.', '_');
  if (!text) return '';
  if (/^(SH|SZ|BJ)_T?\d{6}$/.test(text)) return text;
  const digits = text.match(/\d{6}/)?.[0];
  if (!digits) return text;
  if (digits.startsWith('6')) return `SH_${digits}`;
  if (digits.startsWith('8') || digits.startsWith('4') || digits.startsWith('92')) return `BJ_${digits}`;
  return `SZ_${digits}`;
};

/** Display code as 600000.SH / 000001.SZ / 920992.BJ */
export const toPublicSymbol = (symbol?: string | null) => {
  const code = normalizeSymbolCode(symbol);
  const match = code.match(/^(SH|SZ|BJ)_(T?\d{6})$/);
  return match ? `${match[2]}.${match[1]}` : code || '';
};

export const resolveSymbolName = (symbol?: string | null, name?: string | null) => {
  const code = normalizeSymbolCode(symbol);
  const publicCode = toPublicSymbol(code);
  const rawName = String(name || '').trim();
  if (
    rawName &&
    normalizeSymbolCode(rawName) !== code &&
    rawName.toUpperCase() !== code &&
    rawName.toUpperCase() !== publicCode.toUpperCase()
  ) {
    return rawName;
  }
  return FALLBACK_SYMBOL_NAMES[code] || '';
};

export const formatSymbolLabel = (symbol?: string | null, name?: string | null) => {
  const code = normalizeSymbolCode(symbol);
  const publicCode = toPublicSymbol(code) || code;
  const cleanName = resolveSymbolName(symbol, name);
  if (!code) return cleanName || '--';
  if (!cleanName) return publicCode;
  return `${cleanName} ${publicCode}`;
};

export const formatSymbolLabels = (symbols: string[] = [], names: Record<string, string> = {}) =>
  symbols.map((symbol) => formatSymbolLabel(symbol, names[normalizeSymbolCode(symbol)] || names[symbol]));
