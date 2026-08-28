import { useCallback, useEffect, useState } from 'react';
import clsx from 'clsx';
import { useSettingsStore } from '../stores/useSettingsStore';
import { Layers } from 'lucide-react';
import { marketApi, parseApiError, type ConceptAnalysisPayload } from '../api/client';
import { AnalysisSection, formatSignedPercent } from './analysisShared';

export default function ConceptAnalysis() {
  const [payload, setPayload] = useState<ConceptAnalysisPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { upColor, downColor } = useSettingsStore((state) => state.getColors());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPayload(await marketApi.getConceptAnalysis(20, 20));
    } catch (err) {
      setError(parseApiError(err, '概念分析读取失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const sectors = payload?.sectors || [];
  const top = sectors.slice(0, 10);
  const bottom = sectors.slice(-5).reverse();
  const rotationDates = (payload?.rotationDates || []).slice(-10);
  const rotationRows = (payload?.rotation || []).slice(0, 12);
  const hot = payload?.hot || [];
  const hotStale = payload?.hotUpdatedAt ? payload.hotUpdatedAt.slice(0, 10) : null;

  const cellColor = (value: number | null | undefined) => {
    if (value == null || !Number.isFinite(Number(value))) return { backgroundColor: undefined, color: '#64748b' };
    const num = Number(value);
    const intensity = 0.15 + Math.min(Math.abs(num) / 6, 1) * 0.6;
    return {
      backgroundColor: num >= 0 ? `rgba(${hexToRgb(upColor)}, ${intensity})` : `rgba(${hexToRgb(downColor)}, ${intensity})`,
      color: '#e2e8f0',
    };
  };

  return (
    <AnalysisSection
      icon={<Layers className="h-4 w-4 text-fuchsia-300" />}
      title="概念分析"
      subtitle={`${payload?.sectorCount ?? 0} 个概念 · 轮动矩阵 ${rotationDates.length} 日`}
      status={payload?.dataStatus}
      dateLabel={`交易日 ${payload?.tradeDate || '—'}`}
      loading={loading}
      error={error}
      onRetry={load}
      hasContent={sectors.length > 0}
      emptyReason={payload?.unavailableReason || '暂无已同步的概念每日快照'}
      footer={`来源 ${(payload?.sources || []).join(' + ') || '—'} · 热门资金流截至 ${hotStale || '—'}（旧管道快照） · 只读`}
    >
      <div className="space-y-4 p-4">
        <div className="grid gap-3 lg:grid-cols-[1.2fr_1fr]">
          <div className="rounded-lg border border-crypto-border/60">
            <div className="border-b border-crypto-border/50 px-3 py-2 text-[11px] font-semibold text-gray-400">领涨概念 Top 10</div>
            <div className="divide-y divide-crypto-border/35">
              {top.map((row) => (
                <div key={row.sectorName} className="grid grid-cols-[34px_minmax(0,1.4fr)_74px_minmax(0,1fr)_86px] items-center gap-2 px-3 py-2 text-[11px]">
                  <span className="font-mono text-gray-600">{String(row.rank ?? '—').padStart(2, '0')}</span>
                  <span className="truncate font-medium text-gray-200">{row.sectorName}</span>
                  <span className={clsx('text-right font-mono tabular-nums', (row.changePercent ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                    {formatSignedPercent(row.changePercent)}
                  </span>
                  <span className="truncate text-gray-500">
                    {row.leaderStock ? `${row.leaderStock} ${formatSignedPercent(row.leaderChange)}` : '—'}
                  </span>
                  <span className="text-right text-[10px] tabular-nums text-gray-500">
                    涨 {row.upCount ?? '—'} / 跌 {row.downCount ?? '—'}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-lg border border-crypto-border/60">
            <div className="border-b border-crypto-border/50 px-3 py-2 text-[11px] font-semibold text-gray-400">领跌概念 Bottom 5</div>
            <div className="divide-y divide-crypto-border/35">
              {bottom.map((row) => (
                <div key={row.sectorName} className="grid grid-cols-[minmax(0,1.6fr)_84px_86px] items-center gap-2 px-3 py-2 text-[11px]">
                  <span className="truncate font-medium text-gray-200">{row.sectorName}</span>
                  <span className={clsx('text-right font-mono tabular-nums', (row.changePercent ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                    {formatSignedPercent(row.changePercent)}
                  </span>
                  <span className="text-right text-[10px] tabular-nums text-gray-500">
                    涨 {row.upCount ?? '—'} / 跌 {row.downCount ?? '—'}
                  </span>
                </div>
              ))}
            </div>
            <div className="border-t border-crypto-border/50 px-3 py-2 text-[10px] font-semibold text-gray-400">热门概念资金流（亿）</div>
            <div className="max-h-48 divide-y divide-crypto-border/35 overflow-y-auto">
              {hot.map((row) => (
                <div key={row.name} className="grid grid-cols-[30px_minmax(0,1.4fr)_64px_70px_70px] items-center gap-2 px-3 py-1.5 text-[11px]">
                  <span className="font-mono text-gray-600">{row.rank ?? '—'}</span>
                  <span className="truncate text-gray-200">{row.name}</span>
                  <span className={clsx('text-right font-mono tabular-nums', (row.changePercent ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                    {formatSignedPercent(row.changePercent)}
                  </span>
                  <span className="text-right font-mono tabular-nums text-gray-400">{row.inflow ?? '—'}</span>
                  <span className={clsx('text-right font-mono tabular-nums', (row.netInflow ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                    {row.netInflow ?? '—'}
                  </span>
                </div>
              ))}
              {!hot.length ? <div className="py-6 text-center text-[11px] text-gray-500">暂无热门概念快照</div> : null}
            </div>
          </div>
        </div>

        {rotationRows.length && rotationDates.length ? (
          <div>
            <div className="mb-2 text-[11px] font-semibold text-gray-400">概念涨幅轮动矩阵（Top/Bottom 概念 × 近 {payload?.rotationDays ?? 20} 个快照日）</div>
            <div className="overflow-x-auto rounded-lg border border-crypto-border/60">
              <table className="min-w-max border-collapse text-[11px]">
                <thead>
                  <tr>
                    <th className="sticky left-0 z-10 bg-slate-950/95 px-3 py-2 text-left font-medium text-gray-400 backdrop-blur">概念</th>
                    {rotationDates.map((date) => (
                      <th key={date} className="px-2.5 py-2 text-center font-mono font-normal text-gray-500">{date.slice(5)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rotationRows.map((row) => (
                    <tr key={row.sectorName} className="border-t border-crypto-border/30">
                      <td className="sticky left-0 z-10 bg-slate-950/95 px-3 py-1.5 font-medium text-gray-200 backdrop-blur">{row.sectorName}</td>
                      {rotationDates.map((date) => {
                        const value = row.changes[date];
                        const style = cellColor(value);
                        return (
                          <td key={date} className="px-2.5 py-1.5 text-center font-mono tabular-nums" style={style}>
                            {value == null ? '—' : formatSignedPercent(value, 1)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </div>
    </AnalysisSection>
  );
}

function hexToRgb(hex: string): string {
  const normalized = hex.replace('#', '');
  return [0, 2, 4]
    .map((index) => Number.parseInt(normalized.slice(index, index + 2), 16))
    .join(', ');
}
