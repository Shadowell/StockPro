import { useCallback, useEffect, useMemo, useState } from 'react';
import { Building } from 'lucide-react';
import clsx from 'clsx';
import { marketApi, parseApiError, type IndustryAnalysisPayload } from '../api/client';
import { AnalysisSection, formatSignedPercent } from './analysisShared';

const WINDOW_OPTIONS = [
  { key: 'change1d', label: '当日' },
  { key: 'change5d', label: '5日' },
  { key: 'change20d', label: '20日' },
] as const;

type WindowKey = (typeof WINDOW_OPTIONS)[number]['key'];

interface IndustryAnalysisProps {
  onSelectSymbol: (symbol: string) => void;
}

export default function IndustryAnalysis({ onSelectSymbol }: IndustryAnalysisProps) {
  const [payload, setPayload] = useState<IndustryAnalysisPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [windowKey, setWindowKey] = useState<WindowKey>('change1d');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPayload(await marketApi.getIndustryAnalysis());
    } catch (err) {
      setError(parseApiError(err, '行业分析读取失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const industries = useMemo(() => {
    const rows = [...(payload?.industries || [])];
    rows.sort((a, b) => {
      const av = a[windowKey];
      const bv = b[windowKey];
      const an = av == null || !Number.isFinite(Number(av)) ? -999 : Number(av);
      const bn = bv == null || !Number.isFinite(Number(bv)) ? -999 : Number(bv);
      return bn - an;
    });
    return rows;
  }, [payload, windowKey]);

  const top = industries.slice(0, 8);
  const bottom = industries.slice(-5).reverse();

  return (
    <AnalysisSection
      icon={<Building className="h-4 w-4 text-sky-300" />}
      title="行业分析"
      subtitle={`${payload?.industryCount ?? 0} 个行业 · 等权涨跌（与热力图同口径）`}
      status={payload?.dataStatus}
      dateLabel={`交易日 ${payload?.tradeDate || '—'}`}
      loading={loading}
      error={error}
      onRetry={load}
      hasContent={industries.length > 0}
      emptyReason={payload?.unavailableReason || '暂无可用行业事实（确认已跑每日同步）'}
      footer={`来源 ${(payload?.sources || []).join(' + ') || '—'} · 实时源 ${payload?.realtimeSource || '日线回退'} · 1d 优先实时、5d/20d 为日线收盘比 · 只读`}
    >
      <div className="space-y-4 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex overflow-hidden rounded-lg border border-crypto-border">
            {WINDOW_OPTIONS.map((option) => (
              <button
                key={option.key}
                type="button"
                onClick={() => setWindowKey(option.key)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  windowKey === option.key ? 'bg-blue-600 text-white' : 'text-gray-500 hover:bg-gray-800/60 hover:text-gray-300'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <span className="text-[10px] text-gray-500">按当前窗口等权涨跌排序</span>
        </div>

        <div className="grid gap-3 lg:grid-cols-[1fr_1.6fr]">
          <div className="space-y-2">
            <div className="rounded-lg border border-up/20 bg-up/[0.05] p-3">
              <div className="text-[10px] text-gray-500">领涨行业</div>
              <div className="mt-1 truncate text-sm font-semibold text-gray-100">{top[0]?.name || '—'}</div>
              <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-up">
                {formatSignedPercent(top[0]?.[windowKey])}
              </div>
            </div>
            <div className="rounded-lg border border-down/20 bg-down/[0.05] p-3">
              <div className="text-[10px] text-gray-500">领跌行业</div>
              <div className="mt-1 truncate text-sm font-semibold text-gray-100">{bottom[0]?.name || '—'}</div>
              <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-down">
                {formatSignedPercent(bottom[0]?.[windowKey])}
              </div>
            </div>
            <div className="rounded-lg border border-crypto-border/60">
              <div className="border-b border-crypto-border/50 px-3 py-2 text-[11px] font-semibold text-gray-400">领跌 Bottom 5</div>
              <div className="divide-y divide-crypto-border/35">
                {bottom.map((row) => (
                  <div key={row.code} className="grid grid-cols-[minmax(0,1.5fr)_64px_58px] items-center gap-2 px-3 py-2 text-[11px]">
                    <span className="truncate text-gray-200">{row.name}</span>
                    <span className={clsx('text-right font-mono tabular-nums', (row[windowKey] ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                      {formatSignedPercent(row[windowKey])}
                    </span>
                    <span className="text-right tabular-nums text-gray-600">{row.count}只</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="overflow-x-auto rounded-lg border border-crypto-border/60">
            <div className="min-w-[720px]">
              <div className="grid grid-cols-[44px_minmax(0,1.3fr)_58px_repeat(3,80px)_96px_minmax(150px,1.1fr)] gap-2 border-b border-crypto-border/50 bg-slate-950/40 px-3 py-2 text-[10px] text-gray-500">
                <span>#</span>
                <span>行业</span>
                <span className="text-right">标的数</span>
                <span className="text-right">当日</span>
                <span className="text-right">5日</span>
                <span className="text-right">20日</span>
                <span className="text-right">涨/跌家数</span>
                <span className="text-right">领涨成员</span>
              </div>
              <div className="max-h-[430px] divide-y divide-crypto-border/35 overflow-y-auto">
                {industries.map((row, index) => (
                  <div
                    key={row.code}
                    className="grid grid-cols-[44px_minmax(0,1.3fr)_58px_repeat(3,80px)_96px_minmax(150px,1.1fr)] items-center gap-2 px-3 py-2 text-[11px]"
                  >
                    <span className="font-mono text-gray-600">{String(index + 1).padStart(2, '0')}</span>
                    <span className="truncate font-medium text-gray-200">{row.name}</span>
                    <span className="text-right tabular-nums text-gray-500">{row.count}</span>
                    <span className={clsx('text-right font-mono tabular-nums', (row.change1d ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                      {formatSignedPercent(row.change1d)}
                    </span>
                    <span className={clsx('text-right font-mono tabular-nums', (row.change5d ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                      {formatSignedPercent(row.change5d)}
                    </span>
                    <span className={clsx('text-right font-mono tabular-nums', (row.change20d ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                      {formatSignedPercent(row.change20d)}
                    </span>
                    <span className="text-right tabular-nums text-gray-400">
                      <span className="text-up">{row.gainers1d ?? '—'}</span> / <span className="text-down">{row.losers1d ?? '—'}</span>
                    </span>
                    <span className="text-right">
                      {row.topMember ? (
                        <button
                          type="button"
                          onClick={() => onSelectSymbol(row.topMember!.symbol)}
                          className="max-w-full truncate text-gray-300 transition hover:text-white"
                          title={`${row.topMember.name} ${row.topMember.symbol}`}
                        >
                          {row.topMember.name} <span className={row.topMember.changePercent >= 0 ? 'text-up' : 'text-down'}>{formatSignedPercent(row.topMember.changePercent)}</span>
                        </button>
                      ) : '—'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </AnalysisSection>
  );
}
