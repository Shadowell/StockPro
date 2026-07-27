export const marketToneClass = (
  value: number | null | undefined,
  neutralClass = "text-gray-400",
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
): "up" | "down" | "neutral" => {
  if (value !== null && value !== undefined && Number(value) > 0) return "up";
  if (value !== null && value !== undefined && Number(value) < 0) return "down";
  return "neutral";
};

export const marketAdverseToneClass = (
  value: number | null | undefined,
  neutralClass = "text-gray-400",
) => {
  if (value === null || value === undefined || !Number.isFinite(Number(value)) || Number(value) === 0) {
    return neutralClass;
  }
  return "text-down";
};

export const marketAdverseMetricColor = (
  value: number | null | undefined,
): "down" | "neutral" => (
  value === null || value === undefined || !Number.isFinite(Number(value)) || Number(value) === 0
    ? "neutral"
    : "down"
);

export const marketHexColor = (
  value: number | null | undefined,
  colors: { upColor: string; downColor: string },
  neutralColor = "#94a3b8",
) => {
  if (value !== null && value !== undefined && Number(value) > 0) return colors.upColor;
  if (value !== null && value !== undefined && Number(value) < 0) return colors.downColor;
  return neutralColor;
};
