export type FreshnessState = 'fresh' | 'stale' | 'unavailable';

export type FreshnessResult = {
  state: FreshnessState;
  timestamp: string | null;
  ageMs: number | null;
};

const timestampValue = (value?: string | null) => {
  if (!value) return null;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : null;
};

export const latestTimestamp = <T extends { updated_at?: string | null }>(items: T[]) => {
  let latest: { value: string; timestamp: number } | null = null;
  items.forEach((item) => {
    const timestamp = timestampValue(item.updated_at);
    if (timestamp !== null && (!latest || timestamp > latest.timestamp)) {
      latest = { value: item.updated_at as string, timestamp };
    }
  });
  return latest?.value ?? null;
};

export const evaluateFreshness = (
  timestamp?: string | null,
  maxAgeMs = 36 * 60 * 60 * 1000,
  nowMs = Date.now(),
): FreshnessResult => {
  const parsed = timestampValue(timestamp);
  if (parsed === null) return { state: 'unavailable', timestamp: null, ageMs: null };
  const ageMs = Math.max(0, nowMs - parsed);
  return { state: ageMs <= maxAgeMs ? 'fresh' : 'stale', timestamp: timestamp ?? null, ageMs };
};

export const formatFreshnessTime = (timestamp?: string | null) => {
  if (!timestamp) return '时间未提供';
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return '时间无效';
  return parsed.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
};
