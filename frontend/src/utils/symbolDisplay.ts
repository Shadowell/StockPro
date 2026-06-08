const FALLBACK_SYMBOL_NAMES: Record<string, string> = {
  SH_600000: '浦发银行',
  SZ_000001: '平安银行',
};

export const normalizeSymbolCode = (symbol?: string | null) => {
  const text = String(symbol || '').trim().toUpperCase().replace('.', '_');
  if (!text) return '';
  if (/^(SH|SZ|BJ)_\d{6}$/.test(text)) return text;
  const digits = text.match(/\d{6}/)?.[0];
  if (!digits) return text;
  if (digits.startsWith('6')) return `SH_${digits}`;
  if (digits.startsWith('8') || digits.startsWith('4')) return `BJ_${digits}`;
  return `SZ_${digits}`;
};

export const formatSymbolLabel = (symbol?: string | null, name?: string | null) => {
  const code = normalizeSymbolCode(symbol);
  const rawName = String(name || '').trim();
  const cleanName =
    rawName && normalizeSymbolCode(rawName) !== code && rawName.toUpperCase() !== code
      ? rawName
      : FALLBACK_SYMBOL_NAMES[code] || '';
  if (!code) return cleanName || '--';
  if (!cleanName) return code;
  return `${cleanName} ${code}`;
};

export const formatSymbolLabels = (symbols: string[] = [], names: Record<string, string> = {}) =>
  symbols.map((symbol) => formatSymbolLabel(symbol, names[normalizeSymbolCode(symbol)] || names[symbol]));
