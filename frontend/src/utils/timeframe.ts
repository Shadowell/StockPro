const KNOWN_TIMEFRAME_LABELS: Record<string, string> = {
  '1m': '1M',
  '5m': '5M',
  '15m': '15M',
  '30m': '30M',
  '1h': '1H',
  '4h': '4H',
  '12h': '12H',
  '1d': '1D',
};

export function formatTimeframeLabel(value: unknown, fallback = '未定义'): string {
  const raw = String(value ?? '').trim();
  if (!raw) return fallback;
  const normalized = raw.toLowerCase();
  return KNOWN_TIMEFRAME_LABELS[normalized] || raw.toUpperCase();
}
