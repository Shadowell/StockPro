import { useEffect, useRef, useState } from 'react';

/**
 * 数值滚动动画：目标值变化时从旧值缓动到新值。
 * 尊重系统 prefers-reduced-motion 设置（直接跳到目标值）。
 */
export function useAnimatedValue(target: number | null, duration = 900): number | null {
  const [display, setDisplay] = useState<number | null>(target);
  const latestRef = useRef<number | null>(target);

  useEffect(() => {
    latestRef.current = target;
    if (target == null) {
      setDisplay(null);
      return;
    }
    const reduced =
      typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) {
      setDisplay(target);
      return;
    }

    let raf = 0;
    let cancelled = false;
    setDisplay((prev) => {
      const from = prev == null ? target : prev;
      if (from === target) return target;
      const start = performance.now();
      const tick = (now: number) => {
        if (cancelled) return;
        if (latestRef.current !== target) return; // 目标已变化，交给下一个 effect
        const t = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - t, 3);
        setDisplay(from + (target - from) * eased);
        if (t < 1) raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
      return from;
    });
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
    };
  }, [target, duration]);

  return display;
}
