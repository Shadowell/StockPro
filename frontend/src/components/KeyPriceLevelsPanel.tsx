import { useEffect, useMemo, useState } from 'react';
import { Crosshair, RefreshCw } from 'lucide-react';
import clsx from 'clsx';
import { marketApi, type KeyLevelsPayload, type KeyPriceLevelPoint } from '../api/client';

/** 默认展开的价位分组：压力支撑 / 枢轴点 / 前高前低 */
const DEFAULT_ACTIVE_GROUPS = ['sr', 'pivot', 'extreme'];

const SIDE_COLORS: Record<string, string> = {
  resistance: '#f59e0b',
  support: '#38bdf8',
  neutral: '#94a3b8',
};

function formatSignedPrice(value: number): string {
  return value.toFixed(2);
}

interface KeyPriceLevelsPanelProps {
  symbol: string;
  exchange: string;
  /** 分组或数据变化时回调当前应叠加到 K 线的价位点 */
  onChange?: (levels: Array<{ value: number; label: string; side: string }>) => void;
}

export default function KeyPriceLevelsPanel({ symbol, exchange, onChange }: KeyPriceLevelsPanelProps) {
  const [payload, setPayload] = useState<KeyLevelsPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeGroups, setActiveGroups] = useState<Set<string>>(() => new Set(DEFAULT_ACTIVE_GROUPS));

  useEffect(() => {
    if (!symbol) {
      setPayload(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    marketApi.getKeyLevels(exchange, symbol, 500)
      .then((data) => {
        if (!cancelled) setPayload(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : '关键价位读取失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [exchange, symbol]);

  const groups = useMemo(() => payload?.groups || {}, [payload]);
  const levelTypes = useMemo(() => payload?.levelTypes || {}, [payload]);
  const close = payload?.close ?? null;

  const visibleLevels = useMemo(() => {
    const points: KeyPriceLevelPoint[] = [];
    activeGroups.forEach((group) => {
      (groups[group] || []).forEach((point) => {
        if (Number.isFinite(Number(point.value)) && Number(point.value) > 0) {
          points.push(point);
        }
      });
    });
    return points;
  }, [activeGroups, groups]);

  /** 序列化作为依赖，避免父组件 setState 新数组引用引发渲染循环 */
  const visibleLevelsKey = JSON.stringify(visibleLevels);

  useEffect(() => {
    const points = JSON.parse(visibleLevelsKey) as KeyPriceLevelPoint[];
    onChange?.(points.map((point) => ({
      value: Number(point.value),
      label: point.label,
      side: point.side || 'neutral',
    })));
  }, [onChange, visibleLevelsKey]);

  const nearestLevels = useMemo(() => {
    if (!close) return [];
    const all: KeyPriceLevelPoint[] = [];
    Object.entries(groups).forEach(([group, points]) => {
      (points || []).forEach((point) => all.push({ ...point, type: point.type || group }));
    });
    return all
      .sort((a, b) => Math.abs(a.value - close) - Math.abs(b.value - close))
      .slice(0, 10);
  }, [close, groups]);

  const toggleGroup = (group: string) => {
    setActiveGroups((prev) => {
      const next = new Set(prev);
      if (next.has(group)) {
        next.delete(group);
      } else {
        next.add(group);
      }
      return next;
    });
  };

  if (!symbol) return null;

  return (
    <section
      className="mt-2 shrink-0 rounded-lg border border-crypto-border/70 bg-slate-950/25 px-3 py-2"
      aria-label="个股关键价位"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-200">
          <Crosshair className="h-3.5 w-3.5 text-cyan-300" />
          关键价位
        </div>
        {loading ? (
          <span className="flex items-center gap-1 text-[11px] text-gray-500">
            <RefreshCw className="h-3 w-3 animate-spin" /> 计算中…
          </span>
        ) : error ? (
          <span className="text-[11px] text-amber-300">{error}</span>
        ) : payload && payload.dataStatus !== 'ok' ? (
          <span className="text-[11px] text-amber-300">
            {payload.unavailableReason || `数据状态 ${payload.dataStatus}`}
          </span>
        ) : payload ? (
          <span className="text-[11px] text-gray-500">
            现价 <span className="font-mono text-gray-300">{formatSignedPrice(Number(close))}</span>
            · 截至 {payload.asOfTradeDate || '—'} · {payload.rowsUsed} 根日线
          </span>
        ) : null}
        <div className="ml-auto flex flex-wrap items-center gap-1">
          {Object.entries(levelTypes).map(([group, label]) => {
            const count = (groups[group] || []).length;
            const active = activeGroups.has(group);
            return (
              <button
                key={group}
                type="button"
                onClick={() => toggleGroup(group)}
                disabled={!count}
                title={`${label}（${count} 个点位）`}
                className={clsx(
                  'rounded border px-2 py-0.5 text-[10px] font-medium transition-colors',
                  active && count
                    ? 'border-cyan-500/40 bg-cyan-500/[0.12] text-cyan-200'
                    : 'border-crypto-border bg-white/[0.02] text-gray-500 hover:text-gray-300',
                  !count && 'cursor-not-allowed opacity-40',
                )}
              >
                {label} {count || ''}
              </button>
            );
          })}
        </div>
      </div>

      {!loading && !error && nearestLevels.length > 0 && (
        <div className="mt-1.5 flex items-center gap-1.5 overflow-x-auto pb-0.5">
          {nearestLevels.map((point) => (
            <span
              key={`${point.type}-${point.label}-${point.value}`}
              className="shrink-0 rounded border border-white/[0.07] bg-white/[0.03] px-1.5 py-0.5 font-mono text-[10px] tabular-nums"
              style={{ color: SIDE_COLORS[point.side] || SIDE_COLORS.neutral }}
              title={`${levelTypes[point.type] || point.type} · ${point.side === 'resistance' ? '压力' : point.side === 'support' ? '支撑' : '中性'}`}
            >
              {point.label} {formatSignedPrice(point.value)}
            </span>
          ))}
        </div>
      )}

      {!loading && !error && payload?.summary && (
        <p className="mt-1 truncate text-[10px] leading-4 text-gray-600" title={payload.summary}>
          {payload.summary}
          {payload.turnoverSource !== 'row_field' ? ' · 筹码分布未含换手率衰减（无历史换手数据）' : ''}
        </p>
      )}
    </section>
  );
}
