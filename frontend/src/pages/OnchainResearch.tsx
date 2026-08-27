import { useCallback, useEffect, useMemo, useState } from 'react';
import { Building2, Database, RefreshCw, Search, ShieldCheck, Users } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import {
  marketApi,
  onchainApi,
  parseApiError,
  type FundamentalFact,
  type FundamentalSummary,
  type MarketInstrument,
} from '../api/client';
import { useAuth } from '../auth/AuthProvider';
import SymbolSearch from '../components/SymbolSearch';


const PANEL = 'overflow-hidden rounded-xl border border-crypto-border bg-crypto-card/95';

function number(value?: number | null, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function money(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (Math.abs(value) >= 1e12) return `¥${(value / 1e12).toFixed(2)}万亿`;
  if (Math.abs(value) >= 1e8) return `¥${(value / 1e8).toFixed(2)}亿`;
  if (Math.abs(value) >= 1e4) return `¥${(value / 1e4).toFixed(2)}万`;
  return `¥${value.toFixed(2)}`;
}

function factValue(fact?: FundamentalFact): string {
  if (!fact || fact.value == null) return '—';
  if (fact.unit === '%') return `${number(fact.value)}%`;
  if (fact.unit === '户') return `${Math.round(fact.value).toLocaleString('zh-CN')} 户`;
  if (fact.unit === 'CNY/股') return `¥${number(fact.value, 4)}/股`;
  return number(fact.value, 4);
}

function EvidenceMetric({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-crypto-border/70 bg-slate-950/35 px-3 py-3">
      <div className="truncate text-[11px] text-gray-500">{label}</div>
      <div className="mt-2 truncate font-mono text-lg font-semibold tabular-nums text-gray-100">{value}</div>
      <div className="mt-1 truncate text-[10px] text-gray-600" title={note}>{note}</div>
    </div>
  );
}

export default function OnchainResearch() {
  const { isAdmin } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [symbol, setSymbol] = useState(searchParams.get('symbol') || '600519.SH');
  const [symbols, setSymbols] = useState<string[]>([]);
  const [instruments, setInstruments] = useState<MarketInstrument[]>([]);
  const [summary, setSummary] = useState<FundamentalSummary | null>(null);
  const [reportPeriod, setReportPeriod] = useState('');
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const payload = await onchainApi.getSummary(symbol);
      setSummary(payload);
      const periods = Array.from(new Set(payload.items.map((item) => item.reportPeriod))).sort().reverse();
      setReportPeriod((current) => current && periods.includes(current) ? current : periods[0] || '');
    } catch (caught) { setError(parseApiError(caught, '基本面证据读取失败')); }
    finally { setLoading(false); }
  }, [symbol]);

  useEffect(() => {
    void marketApi.getSymbols('SSE', 'CNY', 'stock').then((payload) => {
      setSymbols(payload.symbols || []); setInstruments(payload.instruments || []);
    }).catch(() => undefined);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const selectSymbol = (next: string) => {
    setSymbol(next);
    const params = new URLSearchParams(searchParams); params.set('symbol', next); setSearchParams(params, { replace: true });
  };
  const sync = async () => {
    if (!isAdmin || syncing) return;
    setSyncing(true); setError('');
    try { await onchainApi.sync(symbol, 3); await load(); }
    catch (caught) { setError(parseApiError(caught, '基本面同步失败')); }
    finally { setSyncing(false); }
  };

  const periods = useMemo(() => Array.from(new Set((summary?.items || []).map((item) => item.reportPeriod))).sort().reverse(), [summary?.items]);
  const selectedFacts = useMemo(() => {
    if (!summary) return {} as Record<string, FundamentalFact>;
    if (!reportPeriod) return summary.latestFactors;
    return Object.fromEntries(summary.items.filter((item) => item.reportPeriod === reportPeriod).map((item) => [item.factorCode, item]));
  }, [reportPeriod, summary]);
  const valuation = summary?.valuation;
  const profitability = [
    ['ROE', 'fundamental.roe_ttm_pit'], ['ROA', 'fundamental.roa_ttm_pit'],
    ['毛利率', 'fundamental.gross_margin_pit'], ['净利率', 'fundamental.net_margin_pit'],
  ] as const;
  const structure = [
    ['营收同比', 'fundamental.revenue_growth_yoy_pit'], ['净利润同比', 'fundamental.net_profit_growth_yoy_pit'],
    ['经营现金流/营收', 'fundamental.ocf_quality_pit'], ['资产负债率', 'fundamental.debt_asset_ratio_pit'],
  ] as const;

  return (
    <div className="h-full overflow-y-auto bg-crypto-bg p-4 sm:p-6">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-crypto-border/70 pb-4">
        <div className="flex min-w-0 items-start gap-3">
          <div className="rounded-lg border border-cyan-500/25 bg-cyan-500/10 p-2"><Building2 className="h-5 w-5 text-cyan-300" /></div>
          <div><h1 className="text-xl font-semibold text-white">A 股基本面与资金流</h1><p className="mt-1 text-xs text-gray-500">公告时点财务、估值、股东与分红证据</p></div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SymbolSearch value={symbol} onChange={selectSymbol} allSymbols={symbols} instruments={instruments} marketType="stock" />
          <button type="button" onClick={() => void load()} disabled={loading} className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-crypto-border text-gray-400 hover:text-white disabled:opacity-50" title="刷新基本面"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /></button>
          <button type="button" onClick={() => void sync()} disabled={!isAdmin || syncing} className="inline-flex h-10 items-center gap-2 rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 text-xs text-cyan-200 disabled:cursor-not-allowed disabled:opacity-40"><Database className="h-4 w-4" />{syncing ? '同步中' : '同步财务事实'}</button>
        </div>
      </header>

      {error ? <div role="alert" className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">{error}</div> : null}
      {loading && !summary ? <div className="mt-4 flex h-40 items-center justify-center rounded-xl border border-crypto-border text-sm text-gray-500">正在读取基本面证据...</div> : null}
      {summary ? <>
        <section className="mt-4 overflow-hidden rounded-xl border border-blue-500/20 bg-crypto-card/95">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-[11px] text-gray-500">
            <span className="font-medium text-gray-200">{summary.name}（{summary.symbol}）</span>
            <span>{summary.board || '板块未知'} · {summary.industry || '行业未知'}</span>
            <span>状态 {summary.status}</span>
            <span>估值快照 #{valuation?.sourceSnapshotId ?? '—'} · {valuation?.tradeDate || '—'}</span>
            <span>知识截止 {valuation?.knowledgeCutoffAt || summary.asOf}</span>
            <span>Provider 调用 {summary.providerCalls} · writes {String(summary.writesPerformed)}</span>
          </div>
          {summary.missingInputs.length ? <div className="border-t border-amber-500/20 bg-amber-500/[0.05] px-4 py-2 text-xs text-amber-200/80">{summary.missingInputs.join(' · ')}</div> : null}
        </section>

        <section className="mt-4">
          <div className="mb-2 flex items-center gap-2"><Search className="h-4 w-4 text-blue-300" /><h2 className="text-sm font-semibold text-gray-100">估值与市场规模</h2></div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
            <EvidenceMetric label="PE TTM" value={number(valuation?.peTtm)} note={valuation?.source || 'daily_basic 缺失'} />
            <EvidenceMetric label="PB" value={number(valuation?.pb)} note={valuation?.tradeDate || '—'} />
            <EvidenceMetric label="PS TTM" value={number(valuation?.psTtm)} note={valuation?.tradeDate || '—'} />
            <EvidenceMetric label="总市值" value={money(valuation?.totalMarketCapCny)} note="CNY" />
            <EvidenceMetric label="流通市值" value={money(valuation?.floatMarketCapCny)} note="CNY" />
            <EvidenceMetric label="股息率 TTM" value={valuation?.dividendYieldTtm == null ? '—' : `${number(valuation.dividendYieldTtm)}%`} note={valuation?.availableAt || '—'} />
          </div>
        </section>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-cyan-300" /><h2 className="text-sm font-semibold text-gray-100">报告期指标</h2></div>
          <select value={reportPeriod} onChange={(event) => setReportPeriod(event.target.value)} className="h-9 rounded-lg border border-crypto-border bg-crypto-card px-3 text-xs text-gray-200"><option value="">最新已知</option>{periods.map((period) => <option key={period} value={period}>{period}</option>)}</select>
        </div>
        <div className="mt-2 grid gap-3 xl:grid-cols-2">
          <section className={PANEL}><div className="border-b border-crypto-border px-4 py-3 text-sm font-semibold text-gray-100">盈利与质量</div><div className="grid grid-cols-2 gap-px bg-crypto-border/50">{profitability.map(([label, code]) => <div key={code} className="bg-crypto-card p-4"><div className="text-xs text-gray-500">{label}</div><div className="mt-2 font-mono text-xl text-gray-100">{factValue(selectedFacts[code])}</div><div className="mt-1 text-[10px] text-gray-600">{selectedFacts[code]?.reportPeriod || '—'} · 公告 {selectedFacts[code]?.annDate || '—'}</div></div>)}</div></section>
          <section className={PANEL}><div className="border-b border-crypto-border px-4 py-3 text-sm font-semibold text-gray-100">成长与资本结构</div><div className="grid grid-cols-2 gap-px bg-crypto-border/50">{structure.map(([label, code]) => <div key={code} className="bg-crypto-card p-4"><div className="text-xs text-gray-500">{label}</div><div className="mt-2 font-mono text-xl text-gray-100">{factValue(selectedFacts[code])}</div><div className="mt-1 text-[10px] text-gray-600">{selectedFacts[code]?.reportPeriod || '—'} · 可用 {selectedFacts[code]?.availableAt || '—'}</div></div>)}</div></section>
        </div>

        <section className={`mt-4 ${PANEL}`}>
          <div className="flex items-center gap-2 border-b border-crypto-border px-4 py-3"><Users className="h-4 w-4 text-blue-300" /><h2 className="text-sm font-semibold text-gray-100">股东与分红</h2></div>
          <div className="grid grid-cols-2 gap-px bg-crypto-border/50"><div className="bg-crypto-card p-4"><div className="text-xs text-gray-500">股东户数</div><div className="mt-2 font-mono text-xl text-gray-100">{factValue(selectedFacts['shareholder.holder_count'])}</div></div><div className="bg-crypto-card p-4"><div className="text-xs text-gray-500">每股现金分红</div><div className="mt-2 font-mono text-xl text-gray-100">{factValue(selectedFacts['dividend.cash_per_share'])}</div></div></div>
        </section>

        <section className={`mt-4 ${PANEL}`}>
          <div className="border-b border-crypto-border px-4 py-3"><h2 className="text-sm font-semibold text-gray-100">公告时点证据</h2></div>
          <div className="overflow-x-auto"><table className="w-full min-w-[920px] text-left text-xs"><thead className="bg-slate-950/45 text-gray-500"><tr><th className="px-4 py-2">指标</th><th className="px-4 py-2">值</th><th className="px-4 py-2">报告期</th><th className="px-4 py-2">公告日</th><th className="px-4 py-2">可用时间</th><th className="px-4 py-2">来源</th><th className="px-4 py-2">版本</th></tr></thead><tbody className="divide-y divide-crypto-border">{summary.items.length ? summary.items.map((item, index) => <tr key={`${item.factorCode}-${item.reportPeriod}-${index}`}><td className="px-4 py-2 text-gray-200">{item.label}</td><td className="px-4 py-2 font-mono text-gray-300">{factValue(item)}</td><td className="px-4 py-2 text-gray-400">{item.reportPeriod}</td><td className="px-4 py-2 text-gray-400">{item.annDate || '—'}</td><td className="px-4 py-2 text-gray-400">{item.availableAt}</td><td className="px-4 py-2 text-gray-400">{item.source || '—'}</td><td className="px-4 py-2 font-mono text-gray-600">{item.definitionVersion}</td></tr>) : <tr><td colSpan={7} className="px-4 py-10 text-center text-gray-500">尚无公告时点事实；管理员可显式同步当前证券。</td></tr>}</tbody></table></div>
        </section>
      </> : null}
    </div>
  );
}
