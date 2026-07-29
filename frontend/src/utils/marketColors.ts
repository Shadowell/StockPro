export type MetricTone = "up" | "down" | "neutral" | "blue" | "green" | "red" | "amber";

export const marketToneClass = (
  value: number | null | undefined,
  neutralClass = "text-slate-400",
) => {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return neutralClass;
  }
  if (Number(value) > 0) return "text-up";
  if (Number(value) < 0) return "text-down";
  return neutralClass;
};

export const marketMetricColor = (
  value: number | null | undefined,
): MetricTone => {
  if (value !== null && value !== undefined && Number(value) > 0) return "up";
  if (value !== null && value !== undefined && Number(value) < 0) return "down";
  return "neutral";
};

/** BitPro-style: higher-is-better metrics like Sharpe / profit factor. */
export const thresholdToneClass = (
  value: number | null | undefined,
  threshold = 1,
  neutralClass = "text-slate-400",
) => {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return neutralClass;
  }
  return Number(value) >= threshold ? "text-up" : "text-down";
};

export const thresholdMetricColor = (
  value: number | null | undefined,
  threshold = 1,
): MetricTone => {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return "neutral";
  }
  return Number(value) >= threshold ? "up" : "down";
};

/** Operational counts / inventory sizes — BitPro uses blue accent, never flat white. */
export const countToneClass = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return "text-slate-400";
  }
  if (Number(value) === 0) return "text-slate-400";
  return "text-blue-300";
};

export const countMetricColor = (
  value: number | null | undefined,
): MetricTone => {
  if (value === null || value === undefined || !Number.isFinite(Number(value)) || Number(value) === 0) {
    return "neutral";
  }
  return "blue";
};

export const marketAdverseToneClass = (
  value: number | null | undefined,
  neutralClass = "text-slate-400",
) => {
  if (value === null || value === undefined || !Number.isFinite(Number(value)) || Number(value) === 0) {
    return neutralClass;
  }
  return "text-down";
};

export const marketAdverseMetricColor = (
  value: number | null | undefined,
): Extract<MetricTone, "down" | "neutral"> => (
  value === null || value === undefined || !Number.isFinite(Number(value)) || Number(value) === 0
    ? "neutral"
    : "down"
);

export const marketHexColor = (
  value: number | null | undefined,
  colors: { upColor: string; downColor: string },
  neutralColor = "#8b949e",
) => {
  if (value !== null && value !== undefined && Number(value) > 0) return colors.upColor;
  if (value !== null && value !== undefined && Number(value) < 0) return colors.downColor;
  return neutralColor;
};

export const metricToneClass = (tone: MetricTone) => {
  switch (tone) {
    case "up":
      return "text-up";
    case "down":
      return "text-down";
    case "blue":
      return "text-blue-300";
    case "green":
      return "text-emerald-300";
    case "red":
      return "text-red-300";
    case "amber":
      return "text-amber-300";
    default:
      return "text-slate-300";
  }
};
