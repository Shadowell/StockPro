export const normalizeSymbolCode = (symbol?: string | null) => {
  const raw = String(symbol || '').trim().toUpperCase();
  if (!raw) return '';
  if (/^\d{6}\.(?:SH|SZ|BJ)$/.test(raw)) return raw;
  const storage = raw.match(/^(SH|SZ|BJ)_(\d{6})$/);
  if (storage) return `${storage[2]}.${storage[1]}`;
  if (/^\d{6}$/.test(raw)) {
    const suffix = raw.startsWith('5') || raw.startsWith('6') || raw.startsWith('9')
      ? 'SH'
      : raw.startsWith('4') || raw.startsWith('8')
        ? 'BJ'
        : 'SZ';
    return `${raw}.${suffix}`;
  }
  return raw;
};

export const resolveSymbolName = (symbol?: string | null, name?: string | null) => {
  const code = normalizeSymbolCode(symbol);
  const candidate = String(name || '').trim();
  return candidate && normalizeSymbolCode(candidate) !== code ? candidate : '';
};

export const formatSymbolLabel = (symbol?: string | null, name?: string | null) => {
  const code = normalizeSymbolCode(symbol) || '--';
  const resolved = resolveSymbolName(symbol, name);
  return resolved ? `${resolved} ${code}` : code;
};
