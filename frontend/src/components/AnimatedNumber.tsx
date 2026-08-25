import { useAnimatedValue } from '../hooks/useAnimatedValue';

interface AnimatedNumberProps {
  value: number | null;
  format: (value: number) => string;
  className?: string;
  duration?: number;
}

/** 数字滚动展示：数值变化时平滑滚动到新值（尊重 prefers-reduced-motion）。 */
export default function AnimatedNumber({ value, format, className, duration = 900 }: AnimatedNumberProps) {
  const display = useAnimatedValue(value, duration);
  if (display == null) {
    return <span className={className}>-</span>;
  }
  return <span className={className}>{format(display)}</span>;
}
