type DataZoomOption = {
  start?: number;
  end?: number;
};

type WheelNavigationChart = {
  getDom: () => HTMLElement;
  getOption: () => unknown;
  dispatchAction: (action: { type: 'dataZoom'; start: number; end: number }) => void;
};

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

const finiteNumber = (value: unknown, fallback: number) =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback;

const readDataZoomRange = (chart: WheelNavigationChart) => {
  const option = chart.getOption() as { dataZoom?: DataZoomOption[] };
  const dataZoom = option.dataZoom ?? [];
  const source = dataZoom.find((item) => Number.isFinite(item.start) && Number.isFinite(item.end)) ?? dataZoom[0];
  const start = clamp(finiteNumber(source?.start, 0), 0, 100);
  const end = clamp(finiteNumber(source?.end, 100), 0, 100);
  return start <= end ? { start, end } : { start: end, end: start };
};

const normalizeRange = (start: number, end: number) => {
  const span = clamp(end - start, 1, 100);
  const nextStart = clamp(start, 0, 100 - span);
  return { start: nextStart, end: nextStart + span };
};

export const bindKlineWheelNavigation = (chart: WheelNavigationChart) => {
  const dom = chart.getDom();

  const dispatchRange = (start: number, end: number) => {
    const next = normalizeRange(start, end);
    chart.dispatchAction({ type: 'dataZoom', start: next.start, end: next.end });
  };

  const onWheel = (event: WheelEvent) => {
    const isPinchZoom = event.ctrlKey || event.metaKey;
    const absDeltaX = Math.abs(event.deltaX);
    const absDeltaY = Math.abs(event.deltaY);
    const horizontalDelta = absDeltaX > 0 ? event.deltaX : event.shiftKey ? event.deltaY : 0;
    const isHorizontalPan = Math.abs(horizontalDelta) > 1 && absDeltaX >= absDeltaY * 0.45;

    if (!isPinchZoom && !isHorizontalPan) return;

    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();

    const rect = dom.getBoundingClientRect();
    const width = Math.max(rect.width, 1);
    const { start, end } = readDataZoomRange(chart);
    const span = Math.max(end - start, 1);

    if (isPinchZoom) {
      const pointerRatio = clamp((event.clientX - rect.left) / width, 0, 1);
      const anchor = start + span * pointerRatio;
      const zoomFactor = event.deltaY > 0 ? 1.12 : 0.88;
      const nextSpan = clamp(span * zoomFactor, 1, 100);
      const nextStart = anchor - nextSpan * pointerRatio;
      dispatchRange(nextStart, nextStart + nextSpan);
      return;
    }

    const shiftPercent = (horizontalDelta / width) * span * 1.35;
    dispatchRange(start + shiftPercent, end + shiftPercent);
  };

  dom.addEventListener('wheel', onWheel, { passive: false, capture: true });

  return () => {
    dom.removeEventListener('wheel', onWheel, { capture: true });
  };
};
