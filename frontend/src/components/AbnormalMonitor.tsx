import { useCallback, useEffect, useState } from 'react';
import { BellRing } from 'lucide-react';
import clsx from 'clsx';
import { marketApi, monitorApi, parseApiError, type MarketEvent, type SymbolAbnormality } from '../api/client';
import { AnalysisSection, formatSignedPercent } from './analysisShared';

interface AbnormalMonitorProps {
  onSelectSymbol: (symbol: string) => void;
}

function windowText(row: SymbolAbnormality, key: '3d' | '10d' | '30d'): string {
  const window = row.windows?.[key];
  if (!window || window.closeness == null) return '—';
  const value = window.valuePct == null ? '—' : formatSignedPercent(window.valuePct, 1);
  const threshold = window.thresholdPct == null ? '—' : `${window.thresholdPct.toFixed(0)}%`;
  return `${value} / ${threshold} · ${(window.closeness * 100).toFixed(0)}%`;
}

function eventTime(value?: string | null): string {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export default function AbnormalMonitor({ onSelectSymbol }: AbnormalMonitorProps) {
  const [movers, setMovers] = useState<SymbolAbnormality[]>([]);
  const [events, setEvents] = useState<MarketEvent[]>([]);
  const [moversStatus, setMoversStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [moversData, eventsData] = await Promise.all([
        marketApi.getMovers(undefined, 50),
        monitorApi.getEvents(20).catch(() => ({ events: [] as MarketEvent[], dataStatus: 'empty' })),
      ]);
      setMovers(moversData || []);
      setMoversStatus((moversData as unknown as { dataStatus?: string }).dataStatus || null);
      setEvents(eventsData.events || []);
    } catch (err) {
      setError(parseApiError(err, '异动监控读取失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <AnalysisSection
      icon={<BellRing className="h-4 w-4 text-amber-300" />}
      title="异动监控"
      subtitle="交易所口径 3/10/30 日偏离接近度"
      status={moversStatus || (movers.length ? 'ok' : 'empty')}
      loading={loading}
      error={error}
      onRetry={load}
      hasContent={movers.length > 0 || events.length > 0}
      emptyReason="暂无已物化的个股异动指标（symbol_abnormal_metrics 为空，需运行盘后异动物化）"
      footer="偏离 / 阈值 / 接近度读已封存 symbol_abnormal_metrics，不在 GET 中重算 · 事件流只读 · writes_performed=false"
    >
      <div className="grid gap-3 p-4 xl:grid-cols-[1.5fr_1fr]">
        <div className="overflow-x-auto rounded-lg border border-crypto-border/60">
          <div className="min-w-[760px]">
            <div className="grid grid-cols-[minmax(180px,1.3fr)_repeat(3,minmax(130px,1fr))_84px_minmax(120px,1fr)] gap-2 border-b border-crypto-border/50 bg-slate-950/40 px-3 py-2 text-[10px] text-gray-500">
              <span>标的</span>
              <span className="text-right">3日 偏离/阈值/接近度</span>
              <span className="text-right">10日</span>
              <span className="text-right">30日</span>
              <span className="text-right">状态</span>
              <span className="text-right">标签</span>
            </div>
            <div className="max-h-[460px] divide-y divide-crypto-border/35 overflow-y-auto">
              {movers.map((row) => (
                <button
                  key={row.symbol}
                  type="button"
                  onClick={() => onSelectSymbol(row.symbol)}
                  className="grid w-full grid-cols-[minmax(180px,1.3fr)_repeat(3,minmax(130px,1fr))_84px_minmax(120px,1fr)] items-center gap-2 px-3 py-2 text-left text-[11px] transition hover:bg-white/[0.03]"
                >
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="truncate font-medium text-gray-200">{row.name || row.symbol}</span>
                    <span className="shrink-0 font-mono text-[10px] text-gray-600">{row.symbol}</span>
                  </span>
                  <span className="text-right font-mono tabular-nums text-gray-300">{windowText(row, '3d')}</span>
                  <span className="text-right font-mono tabular-nums text-gray-300">{windowText(row, '10d')}</span>
                  <span className="text-right font-mono tabular-nums text-gray-300">{windowText(row, '30d')}</span>
                  <span
                    className={clsx(
                      'text-right font-medium',
                      row.abnormalStatus === 'triggered' ? 'text-red-300' : row.abnormalStatus === 'edge' ? 'text-amber-300' : 'text-gray-400',
                    )}
                  >
                    {row.abnormalStatus === 'triggered' ? '已触发' : row.abnormalStatus === 'edge' ? '接近' : '观察'}
                  </span>
                  <span className="truncate text-right text-[10px] text-gray-500">
                    {(row.tags || []).join(' · ') || row.status || '—'}
                  </span>
                </button>
              ))}
              {!movers.length ? (
                <div className="flex h-32 items-center justify-center text-xs text-gray-500">暂无异动指标（本地未物化）</div>
              ) : null}
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-crypto-border/60">
          <div className="border-b border-crypto-border/50 px-3 py-2 text-[11px] font-semibold text-gray-400">异动相关告警事件</div>
          <div className="max-h-[460px] divide-y divide-crypto-border/35 overflow-y-auto">
            {events.map((event) => (
              <div key={event.eventId} className="px-3 py-2.5 text-[11px]">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-gray-500">{eventTime(event.triggeredAt)}</span>
                  <span
                    className={clsx(
                      'rounded border px-1.5 py-0.5 text-[10px]',
                      event.severity === 'critical'
                        ? 'border-red-500/25 bg-red-500/10 text-red-300'
                        : event.severity === 'warning'
                          ? 'border-amber-500/25 bg-amber-500/10 text-amber-300'
                          : 'border-slate-600/45 bg-slate-900/70 text-slate-400',
                    )}
                  >
                    {event.source} · {event.severity}
                  </span>
                </div>
                <div className="mt-1 line-clamp-2 text-gray-400">{event.message}</div>
              </div>
            ))}
            {!events.length ? (
              <div className="flex h-32 items-center justify-center px-4 text-center text-xs text-gray-500">
                暂无异动告警事件
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </AnalysisSection>
  );
}
