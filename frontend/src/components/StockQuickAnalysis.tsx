import { useCallback, useEffect, useState } from 'react';
import { LineChart, Search } from 'lucide-react';
import clsx from 'clsx';
import { useNavigate } from 'react-router-dom';
import { marketApi, parseApiError, type KeyLevelsPayload, type MarketInstrument } from '../api/client';
import { useStore } from '../stores/useStore';
import SymbolSearch from './SymbolSearch';
import { AnalysisSection, formatSignedPercent } from './analysisShared';

const SIDE_COLORS: Record<string, string> = {
  resistance: '#f59e0b',
  support: '#38bdf8',
  neutral: '#94a3b8',
};

export default function StockQuickAnalysis() {
  const navigate = useNavigate();
  const [allSymbols, setAllSymbols] = useState<string[]>([]);
  const [instruments, setInstruments] = useState<MarketInstrument[]>([]);
  const [symbol, setSymbol] = useState('');
  const [levels, setLevels] = useState<KeyLevelsPayload | null>(null);
  const [levelsLoading, setLevelsLoading] = useState(false);
  const [quote, setQuote] = useState<{ close: number; changePercent: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    marketApi.getSymbols('SSE', 'CNY', 'stock')
      .then((res) => {
        if (cancelled) return;
        const symbols = res.symbols || [];
        setAllSymbols(symbols);
        setInstruments(res.instruments || []);
        if (symbols.length && !symbols.includes(symbol)) setSymbol(symbols.includes('600519.SH') ? '600519.SH' : symbols[0]);
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    setLevelsLoading(true);
    setError(null);
    Promise.all([
      marketApi.getKeyLevels('SSE', symbol, 500),
      marketApi.getKlines('SSE', symbol, '1d', 2),
    ])
      .then(([levelsData, klinesData]) => {
        if (cancelled) return;
        setLevels(levelsData);
        const items = (klinesData as { items?: Array<{ close?: number }> }).items || [];
        const last = items[items.length - 1];
        const prev = items[items.length - 2];
        if (last?.close) {
          const changePercent = prev?.close ? (last.close / prev.close - 1) * 100 : 0;
          setQuote({ close: last.close, changePercent });
        } else {
          setQuote(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(parseApiError(err, '个股读取失败'));
      })
      .finally(() => {
        if (!cancelled) setLevelsLoading(false);
      });
    return () => { cancelled = true; };
  }, [symbol]);

  const openInMarket = useCallback(() => {
    if (!symbol) return;
    useStore.getState().setSelectedSymbol(symbol);
    navigate('/market');
  }, [navigate, symbol]);

  const nearest = (levels?.groups ? Object.values(levels.groups).flat() : [])
    .filter((p) => Number.isFinite(Number(p.value)) && Number(p.value) > 0 && levels?.close)
    .sort((a, b) => Math.abs(a.value - (levels?.close || 0)) - Math.abs(b.value - (levels?.close || 0)))
    .slice(0, 12);

  return (
    <AnalysisSection
      icon={<LineChart className="h-4 w-4 text-cyan-300" />}
      title="个股分析"
      subtitle="证券速查 + 关键价位摘要 · 完整 K 线见行情页"
      status={levels?.dataStatus}
      dateLabel={levels?.asOfTradeDate ? `截至 ${levels.asOfTradeDate}` : undefined}
      loading={levelsLoading}
      error={error}
      hasContent={Boolean(levels && levels.close)}
      emptyReason={levels?.unavailableReason || '搜索并选择一只 A 股查看关键价位'}
      footer={`关键价位基于未复权日线实时计算（${levels?.rowsUsed ?? 0} 根） · 筹码分布${levels?.turnoverSource === 'row_field' ? '含换手率衰减' : '未含换手率衰减（无历史换手数据）'} · 跳转行情页查看 K 线叠加`}
    >
      <div className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="w-full max-w-[320px]">
            <SymbolSearch
              value={symbol}
              onChange={setSymbol}
              allSymbols={allSymbols}
              instruments={instruments}
              marketType="stock"
            />
          </div>
          {quote ? (
            <div className="flex items-baseline gap-3">
              <span className="text-xl font-bold tabular-nums text-white">¥{quote.close.toFixed(2)}</span>
              <span className={clsx('text-sm font-medium tabular-nums', quote.changePercent >= 0 ? 'text-up' : 'text-down')}>
                {formatSignedPercent(quote.changePercent)}
              </span>
            </div>
          ) : null}
          <button
            type="button"
            onClick={openInMarket}
            disabled={!symbol}
            className="ml-auto inline-flex h-9 items-center gap-1.5 rounded-lg border border-cyan-500/25 bg-cyan-500/[0.08] px-3 text-xs font-medium text-cyan-200 transition hover:bg-cyan-500/[0.14] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Search className="h-3.5 w-3.5" /> 行情页打开 K 线叠加
          </button>
        </div>

        {nearest.length ? (
          <div className="flex flex-wrap gap-1.5">
            {nearest.map((point) => (
              <span
                key={`${point.type}-${point.label}-${point.value}`}
                className="rounded border border-white/[0.07] bg-white/[0.03] px-2 py-1 font-mono text-[10px] tabular-nums"
                style={{ color: SIDE_COLORS[point.side] || SIDE_COLORS.neutral }}
                title={point.label}
              >
                {point.label} {Number(point.value).toFixed(2)}
              </span>
            ))}
          </div>
        ) : null}

        {levels?.summary ? (
          <p className="text-[11px] leading-5 text-gray-500" title={levels.summary}>{levels.summary}</p>
        ) : null}
      </div>
    </AnalysisSection>
  );
}
