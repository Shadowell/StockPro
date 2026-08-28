import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  ArrowLeftRight,
  BarChart3,
  Briefcase,
  Calculator,
  Gauge,
  Loader2,
  RefreshCw,
  Rows3,
  TrendingUp,
} from 'lucide-react';
import clsx from 'clsx';
import { SELECTED_SEGMENT_BORDER_CLASS } from '../utils/selectionStyles';
import { arbitrageApi, marketApi, type ArbitrageSummary, type ConceptAnalysisPayload, type IndustryAnalysisPayload } from '../api/client';

type LiquidityMode = 'maker' | 'taker';

type CalculatorState = {
  okxBid: string;
  okxAsk: string;
  binanceBid: string;
  binanceAsk: string;
  okxFundingBps: string;
  binanceFundingBps: string;
  okxMakerFeeBps: string;
  okxTakerFeeBps: string;
  binanceMakerFeeBps: string;
  binanceTakerFeeBps: string;
  okxLiquidity: LiquidityMode;
  binanceLiquidity: LiquidityMode;
  slippageBps: string;
  notionalUsdt: string;
};

type CalculatorField = Exclude<keyof CalculatorState, 'okxLiquidity' | 'binanceLiquidity'>;

type CalculatorDirection = {
  id: 'longBinanceShortOkx' | 'longOkxShortBinance';
  label: string;
  basisEdgeBps: number;
  fundingEdgeBps: number;
  grossEdgeBps: number;
  netEdgeBps: number;
  estimatedPnlUsdt: number;
};

const CALCULATOR_DEFAULTS: CalculatorState = {
  okxBid: '390.84',
  okxAsk: '390.90',
  binanceBid: '390.33',
  binanceAsk: '390.39',
  okxFundingBps: '0',
  binanceFundingBps: '0',
  okxMakerFeeBps: '2',
  okxTakerFeeBps: '5',
  binanceMakerFeeBps: '1.8',
  binanceTakerFeeBps: '4.5',
  okxLiquidity: 'taker',
  binanceLiquidity: 'taker',
  slippageBps: '4',
  notionalUsdt: '100',
};

function money(value?: number | null): string {
  const n = Number(value ?? 0);
  return `$${n.toFixed(2)}`;
}

function numberFrom(record: Record<string, unknown>, key: string): number | null {
  const raw = record[key];
  if (raw === null || raw === undefined || raw === '') return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

function textFrom(record: Record<string, unknown>, key: string, fallback = '--'): string {
  const raw = record[key];
  if (raw === null || raw === undefined || raw === '') return fallback;
  return String(raw);
}

function bps(value?: number | null): string {
  const n = Number(value ?? 0);
  return `${n.toFixed(2)} bps`;
}

function signedBps(value?: number | null): string {
  const n = Number(value ?? 0);
  const prefix = n > 0 ? '+' : '';
  return `${prefix}${n.toFixed(2)} bps`;
}

function ratePct(value?: number | null): string {
  const n = Number(value ?? 0) * 100;
  return `${n.toFixed(4)}%`;
}

function signedMoney(value?: number | null): string {
  const n = Number(value ?? 0);
  const prefix = n > 0 ? '+' : '';
  return `${prefix}$${n.toFixed(2)}`;
}


function metricClass(value?: number | null): string {
  const n = Number(value ?? 0);
  if (n > 0) return 'text-green-300';
  if (n < 0) return 'text-red-300';
  return 'text-gray-300';
}

function parseCalculatorNumber(value: string): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function positiveAverage(values: number[]): number {
  const positive = values.filter((value) => Number.isFinite(value) && value > 0);
  if (!positive.length) return 0;
  return positive.reduce((sum, value) => sum + value, 0) / positive.length;
}


function EmptyPanel({ text }: { text: string }) {
  return (
    <div className="flex min-h-[120px] items-center justify-center rounded-lg border border-dashed border-crypto-border bg-crypto-bg/50 px-4 text-center text-sm text-gray-500">
      {text}
    </div>
  );
}


export default function ArbitrageCenter() {
  const [summary, setSummary] = useState<ArbitrageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [calculator, setCalculator] = useState<CalculatorState>(CALCULATOR_DEFAULTS);
  const [industry, setIndustry] = useState<IndustryAnalysisPayload | null>(null);
  const [concept, setConcept] = useState<ConceptAnalysisPayload | null>(null);

  const loadSummary = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [nextSummary, nextIndustry, nextConcept] = await Promise.all([
        arbitrageApi.getSummary(),
        marketApi.getIndustryAnalysis().catch(() => null),
        marketApi.getConceptAnalysis().catch(() => null),
      ]);
      setSummary(nextSummary);
      setIndustry(nextIndustry);
      setConcept(nextConcept);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || '套利中心加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  const exchanges = summary?.configuredExchanges || [];
  const pnl = summary?.pnl || {};
  const emptyText = summary?.emptyReason || '等待真实 ETF/LOF/可转债价差数据';
  const kpis = useMemo(() => [
    { label: '净敞口', value: money(summary?.netExposure?.totalUsdt), tone: metricClass(summary?.netExposure?.totalUsdt), icon: Gauge },
    { label: '预估收益', value: money(pnl.estimatedUsdt), tone: metricClass(pnl.estimatedUsdt), icon: TrendingUp },
    { label: '实际收益', value: money(pnl.actualUsdt), tone: metricClass(pnl.actualUsdt), icon: Activity },
  ], [pnl.actualUsdt, pnl.estimatedUsdt, summary?.netExposure?.totalUsdt]);

  const updateCalculatorField = useCallback((field: CalculatorField, value: string) => {
    setCalculator((prev) => ({ ...prev, [field]: value }));
  }, []);

  const updateCalculatorLiquidity = useCallback((field: 'okxLiquidity' | 'binanceLiquidity', value: LiquidityMode) => {
    setCalculator((prev) => ({ ...prev, [field]: value }));
  }, []);

  const calculatorResult = useMemo(() => {
    const okxBid = parseCalculatorNumber(calculator.okxBid);
    const okxAsk = parseCalculatorNumber(calculator.okxAsk);
    const binanceBid = parseCalculatorNumber(calculator.binanceBid);
    const binanceAsk = parseCalculatorNumber(calculator.binanceAsk);
    const okxFunding = parseCalculatorNumber(calculator.okxFundingBps);
    const binanceFunding = parseCalculatorNumber(calculator.binanceFundingBps);
    const okxFee = calculator.okxLiquidity === 'maker'
      ? parseCalculatorNumber(calculator.okxMakerFeeBps)
      : parseCalculatorNumber(calculator.okxTakerFeeBps);
    const binanceFee = calculator.binanceLiquidity === 'maker'
      ? parseCalculatorNumber(calculator.binanceMakerFeeBps)
      : parseCalculatorNumber(calculator.binanceTakerFeeBps);
    const entryFeeBps = Math.max(0, okxFee) + Math.max(0, binanceFee);
    const roundTripFeeBps = entryFeeBps * 2;
    const slippageBps = Math.max(0, parseCalculatorNumber(calculator.slippageBps));
    const notionalUsdt = Math.max(0, parseCalculatorNumber(calculator.notionalUsdt));
    const mid = positiveAverage([okxBid, okxAsk, binanceBid, binanceAsk]);

    const buildDirection = (
      id: CalculatorDirection['id'],
      label: string,
      shortBid: number,
      longAsk: number,
      fundingEdgeBps: number,
    ): CalculatorDirection => {
      const basisEdgeBps = mid > 0 ? ((shortBid - longAsk) / mid) * 10_000 : 0;
      const grossEdgeBps = basisEdgeBps + fundingEdgeBps;
      const netEdgeBps = grossEdgeBps - roundTripFeeBps - slippageBps;
      return {
        id,
        label,
        basisEdgeBps,
        fundingEdgeBps,
        grossEdgeBps,
        netEdgeBps,
        estimatedPnlUsdt: (notionalUsdt * netEdgeBps) / 10_000,
      };
    };

    const longBinanceShortOkx = buildDirection(
      'longBinanceShortOkx',
      'Binance 多 / OKX 空',
      okxBid,
      binanceAsk,
      okxFunding - binanceFunding,
    );
    const longOkxShortBinance = buildDirection(
      'longOkxShortBinance',
      'OKX 多 / Binance 空',
      binanceBid,
      okxAsk,
      binanceFunding - okxFunding,
    );
    const directions = [longBinanceShortOkx, longOkxShortBinance].sort((a, b) => b.netEdgeBps - a.netEdgeBps);
    const best = directions[0];
    const recommendedDirection = best.netEdgeBps > 0 ? best.label : '不开仓';
    return {
      directions,
      best,
      recommendedDirection,
      entryFeeBps,
      roundTripFeeBps,
      slippageBps,
      notionalUsdt,
    };
  }, [calculator]);

  if (summary?.status === 'unavailable') {
    return (
      <div className="h-full w-full min-w-0 p-6">
        <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-normal text-white"><ArrowLeftRight className="h-6 w-6 text-cyan-300" />A 股价差研究</h1>
            <div className="mt-1 text-xs text-gray-500">ETF / LOF / 可转债 · 价差证据 · 模拟组合审计</div>
          </div>
          <button type="button" onClick={() => void loadSummary()} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-3 text-sm font-semibold text-gray-200 hover:border-cyan-400/45 hover:text-cyan-100">{loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}刷新</button>
        </header>
        <div className="grid gap-4 xl:grid-cols-2">
          <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
            <div className="border-b border-crypto-border px-4 py-3">
              <h2 className="text-sm font-semibold text-white">行业相对强弱</h2>
              <p className="mt-1 text-[11px] text-gray-500">用等权 1日/20日涨跌代替尚未接通的 ETF 折溢价，交易日 {industry?.tradeDate || '—'}</p>
            </div>
            <div className="divide-y divide-crypto-border/40">
              {(industry?.industries || []).slice(0, 8).map((row) => (
                <div key={row.code} className="grid grid-cols-[minmax(0,1fr)_72px_72px_72px] items-center gap-2 px-4 py-2.5 text-xs">
                  <span className="truncate text-gray-200">{row.name}</span>
                  <span className={clsx('text-right tabular-nums', (row.change1d || 0) >= 0 ? 'text-up' : 'text-down')}>{row.change1d == null ? '—' : `${row.change1d >= 0 ? '+' : ''}${row.change1d.toFixed(2)}%`}</span>
                  <span className={clsx('text-right tabular-nums', (row.change20d || 0) >= 0 ? 'text-up' : 'text-down')}>{row.change20d == null ? '—' : `${row.change20d >= 0 ? '+' : ''}${row.change20d.toFixed(2)}%`}</span>
                  <span className="truncate text-right text-gray-500">{row.topMember?.name || '—'}</span>
                </div>
              ))}
              {!(industry?.industries || []).length && <div className="px-4 py-8 text-center text-xs text-gray-500">行业涨跌尚未同步</div>}
            </div>
          </section>
          <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
            <div className="border-b border-crypto-border px-4 py-3">
              <h2 className="text-sm font-semibold text-white">概念相对强弱</h2>
              <p className="mt-1 text-[11px] text-gray-500">概念日涨跌与热门资金流，交易日 {concept?.tradeDate || '—'}</p>
            </div>
            <div className="divide-y divide-crypto-border/40">
              {(concept?.sectors || []).slice(0, 8).map((row) => (
                <div key={row.sectorCode || row.sectorName} className="grid grid-cols-[minmax(0,1fr)_80px_minmax(0,1fr)] items-center gap-2 px-4 py-2.5 text-xs">
                  <span className="truncate text-gray-200">{row.sectorName}</span>
                  <span className={clsx('text-right tabular-nums', (row.changePercent || 0) >= 0 ? 'text-up' : 'text-down')}>{row.changePercent == null ? '—' : `${row.changePercent >= 0 ? '+' : ''}${row.changePercent.toFixed(2)}%`}</span>
                  <span className="truncate text-right text-gray-500">{row.leaderStock || '—'}</span>
                </div>
              ))}
              {!(concept?.sectors || []).length && <div className="px-4 py-8 text-center text-xs text-gray-500">概念涨跌尚未同步</div>}
            </div>
          </section>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full w-full min-w-0 p-6">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-normal text-white">
            <ArrowLeftRight className="h-6 w-6 text-cyan-300" />
            A 股价差研究
          </h1>
          <div className="mt-1 text-xs text-gray-500">ETF / LOF / 可转债 · 价差证据 · 模拟组合审计</div>
        </div>
        <button
          type="button"
          onClick={() => void loadSummary()}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-3 text-sm font-semibold text-gray-200 hover:border-cyan-400/45 hover:text-cyan-100"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          刷新
        </button>
      </header>

      {error && (
        <div className="mb-4 rounded-lg border border-red-500/35 bg-red-500/10 px-3 py-2 text-sm font-semibold text-red-200">
          {error}
        </div>
      )}

      <section className="mb-5 grid gap-3 lg:grid-cols-3">
        {kpis.map((item) => {
          const Icon = item.icon;
          return (
            <div key={item.label} className="rounded-xl border border-crypto-border bg-crypto-card p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-semibold text-gray-400">{item.label}</div>
                <Icon className="h-4 w-4 text-cyan-300" />
              </div>
              <div className={clsx('mt-3 font-mono text-2xl font-bold tabular-nums', item.tone)}>{item.value}</div>
            </div>
          );
        })}
      </section>

      <section className="mb-5 rounded-xl border border-crypto-border bg-crypto-card p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
          <Rows3 className="h-4 w-4 text-cyan-300" />
          交易所接入状态
        </div>
        <div className="grid gap-2 md:grid-cols-2">
          {exchanges.map((item) => {
            const exchange = String(item.exchange || '');
            const ready = item.readiness === 'configured';
            return (
              <div key={exchange} className="rounded-lg border border-crypto-border bg-crypto-bg/70 px-3 py-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="font-semibold text-gray-100">{String(item.label || exchange)}</div>
                  <span className={clsx('rounded-full px-2 py-0.5 text-[11px] font-semibold', ready ? 'bg-green-500/15 text-green-300' : 'bg-amber-500/15 text-amber-200')}>
                    {ready ? '已配置' : item.readiness === 'display_only' ? '仅展示' : '公共行情'}
                  </span>
                </div>
                <div className="mt-1 text-xs text-gray-500">{exchange}</div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="mb-5 rounded-xl border border-cyan-500/25 bg-crypto-card p-4">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Calculator className="h-4 w-4 text-cyan-300" />
            净优势计算器
          </div>
          <div className="rounded-full border border-crypto-border bg-crypto-bg px-3 py-1 text-xs font-semibold text-gray-400">
            市价单默认 Taker
          </div>
        </div>

        <div className="grid gap-3 lg:grid-cols-4">
          {([
            ['okxBid', 'OKX Bid'],
            ['okxAsk', 'OKX Ask'],
            ['binanceBid', 'Binance Bid'],
            ['binanceAsk', 'Binance Ask'],
            ['okxFundingBps', 'OKX Funding'],
            ['binanceFundingBps', 'Binance Funding'],
            ['notionalUsdt', '名义金额'],
            ['slippageBps', '滑点'],
          ] as [CalculatorField, string][]).map(([field, label]) => (
            <label key={field} className="block">
              <span className="mb-1 block text-xs font-semibold text-gray-500">{label}</span>
              <input
                type="number"
                value={calculator[field]}
                onChange={(event) => updateCalculatorField(field, event.target.value)}
                className="h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 font-mono text-sm text-gray-100 outline-none transition focus:border-cyan-400/60"
              />
            </label>
          ))}
        </div>

        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          {([
            ['okxLiquidity', 'OKX费率', calculator.okxLiquidity, calculator.okxMakerFeeBps, calculator.okxTakerFeeBps],
            ['binanceLiquidity', 'Binance费率', calculator.binanceLiquidity, calculator.binanceMakerFeeBps, calculator.binanceTakerFeeBps],
          ] as ['okxLiquidity' | 'binanceLiquidity', string, LiquidityMode, string, string][]).map(([field, label, active, makerFee, takerFee]) => (
            <div key={field} className="rounded-lg border border-crypto-border bg-crypto-bg/70 p-3">
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="text-xs font-semibold text-gray-500">{label}</div>
                <div className="font-mono text-xs text-gray-500">M {makerFee} / T {takerFee} bps</div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {(['taker', 'maker'] as LiquidityMode[]).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    aria-pressed={active === mode}
                    onClick={() => updateCalculatorLiquidity(field, mode)}
                    className={clsx(
                      'h-9 rounded-lg border px-3 text-sm font-semibold transition',
                      active === mode
                        ? SELECTED_SEGMENT_BORDER_CLASS
                        : 'border-crypto-border bg-crypto-card text-gray-400 hover:border-cyan-400/35 hover:text-gray-200',
                    )}
                  >
                    {mode === 'taker' ? 'Taker' : 'Maker'}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[0.85fr_1.15fr]">
          <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/10 p-4">
            <div className="text-xs font-semibold text-gray-400">建议方向</div>
            <div className="mt-2 text-xl font-bold text-white">{calculatorResult.recommendedDirection}</div>
            <div className={clsx('mt-3 font-mono text-2xl font-bold tabular-nums', metricClass(calculatorResult.best.netEdgeBps))}>
              {signedBps(calculatorResult.best.netEdgeBps)}
            </div>
            <div className={clsx('mt-1 font-mono text-sm tabular-nums', metricClass(calculatorResult.best.estimatedPnlUsdt))}>
              预估收益 {signedMoney(calculatorResult.best.estimatedPnlUsdt)}
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {[
              { label: '价差优势', value: signedBps(calculatorResult.best.basisEdgeBps), tone: metricClass(calculatorResult.best.basisEdgeBps) },
              { label: '资金费优势', value: signedBps(calculatorResult.best.fundingEdgeBps), tone: metricClass(calculatorResult.best.fundingEdgeBps) },
              { label: '总成本', value: bps(calculatorResult.roundTripFeeBps + calculatorResult.slippageBps), tone: 'text-red-300' },
              { label: '预估收益', value: signedMoney(calculatorResult.best.estimatedPnlUsdt), tone: metricClass(calculatorResult.best.estimatedPnlUsdt) },
            ].map((item) => (
              <div key={item.label} className="rounded-lg border border-crypto-border bg-crypto-bg/70 p-3">
                <div className="text-xs font-semibold text-gray-500">{item.label}</div>
                <div className={clsx('mt-2 font-mono text-lg font-bold tabular-nums', item.tone)}>{item.value}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-gray-500">
              <tr>
                <th className="py-2">方向</th>
                <th>价差</th>
                <th>资金费</th>
                <th>毛优势</th>
                <th>净优势</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-crypto-border text-gray-200">
              {calculatorResult.directions.map((item) => (
                <tr key={item.id}>
                  <td className="py-2">{item.label}</td>
                  <td className={metricClass(item.basisEdgeBps)}>{signedBps(item.basisEdgeBps)}</td>
                  <td className={metricClass(item.fundingEdgeBps)}>{signedBps(item.fundingEdgeBps)}</td>
                  <td className={metricClass(item.grossEdgeBps)}>{signedBps(item.grossEdgeBps)}</td>
                  <td className={metricClass(item.netEdgeBps)}>{signedBps(item.netEdgeBps)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
        <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
            <TrendingUp className="h-4 w-4 text-cyan-300" />
            机会列表
          </div>
          {summary?.opportunities?.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-gray-500">
                  <tr>
                    <th className="py-2">标的</th>
                    <th>方向</th>
                    <th>净优势</th>
                    <th>深度</th>
                    <th>原因</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-crypto-border text-gray-200">
                  {summary.opportunities.map((item) => (
                    <tr key={`${item.symbol}-${item.strategyType}`}>
                      <td className="py-2 font-mono">{item.symbol}</td>
                      <td>{item.longLeg?.exchange} 多 / {item.shortLeg?.exchange} 空</td>
                      <td className={metricClass(item.netEdgeBps)}>{item.netEdgeBps?.toFixed(2)} bps</td>
                      <td>{money(item.depthUsdt)}</td>
                      <td className="text-gray-400">{item.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyPanel text={emptyText} />}
        </section>

        <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
            <BarChart3 className="h-4 w-4 text-cyan-300" />
            A 股价差排行
          </div>
          {summary?.fundingRankings?.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-gray-500">
                  <tr>
                    <th className="py-2">标的</th>
                    <th>OKX</th>
                    <th>Binance</th>
                    <th>差值</th>
                    <th>年化</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-crypto-border text-gray-200">
                  {summary.fundingRankings.map((item) => {
                    const symbol = textFrom(item, 'symbol');
                    const spread = numberFrom(item, 'spreadBps');
                    return (
                      <tr key={symbol}>
                        <td className="py-2 font-mono">{symbol}</td>
                        <td>{ratePct(numberFrom(item, 'okxFundingRate'))}</td>
                        <td>{ratePct(numberFrom(item, 'binanceFundingRate'))}</td>
                        <td className={metricClass(spread)}>{bps(spread)}</td>
                        <td className={metricClass(numberFrom(item, 'annualizedSpreadPct'))}>
                          {(numberFrom(item, 'annualizedSpreadPct') ?? 0).toFixed(2)}%
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : <EmptyPanel text="等待双交易所真实 funding history" />}
        </section>

        <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
            <Rows3 className="h-4 w-4 text-cyan-300" />
            价差矩阵
          </div>
          {summary?.spreadMatrix?.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-gray-500">
                  <tr>
                    <th className="py-2">标的</th>
                    <th>OKX 标记</th>
                    <th>Binance 标记</th>
                    <th>基差</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-crypto-border text-gray-200">
                  {summary.spreadMatrix.map((item) => {
                    const symbol = textFrom(item, 'symbol');
                    const basis = numberFrom(item, 'basisBps');
                    return (
                      <tr key={symbol}>
                        <td className="py-2 font-mono">{symbol}</td>
                        <td className="font-mono">{money(numberFrom(item, 'okxMarkPrice'))}</td>
                        <td className="font-mono">{money(numberFrom(item, 'binanceMarkPrice'))}</td>
                        <td className={metricClass(basis)}>{bps(basis)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : <EmptyPanel text="等待 OKX 与 Binance USD-M 同步后的价差矩阵" />}
        </section>

        <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
            <Briefcase className="h-4 w-4 text-cyan-300" />
            组合持仓
          </div>
          {summary?.portfolioPositions?.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-gray-500">
                  <tr>
                    <th className="py-2">标的</th>
                    <th>多腿</th>
                    <th>空腿</th>
                    <th>净敞口</th>
                    <th>浮盈</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-crypto-border text-gray-200">
                  {summary.portfolioPositions.map((item, index) => {
                    const symbol = textFrom(item, 'symbol', `position-${index + 1}`);
                    return (
                      <tr key={`${symbol}-${index}`}>
                        <td className="py-2 font-mono">{symbol}</td>
                        <td>{textFrom(item, 'longExchange')}</td>
                        <td>{textFrom(item, 'shortExchange')}</td>
                        <td className={metricClass(numberFrom(item, 'netExposureUsdt'))}>
                          {money(numberFrom(item, 'netExposureUsdt'))}
                        </td>
                        <td className={metricClass(numberFrom(item, 'unrealizedPnlUsdt'))}>
                          {signedMoney(numberFrom(item, 'unrealizedPnlUsdt'))}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : <EmptyPanel text="暂无跨所模拟组合持仓" />}
        </section>

        <section className="rounded-xl border border-crypto-border bg-crypto-card p-4 xl:col-span-2">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
            <Activity className="h-4 w-4 text-cyan-300" />
            腿状态
          </div>
          {summary?.legStatus?.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-gray-500">
                  <tr>
                    <th className="py-2">标的</th>
                    <th>交易所</th>
                    <th>方向</th>
                    <th>状态</th>
                    <th>名义</th>
                    <th>价格</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-crypto-border text-gray-200">
                  {summary.legStatus.map((item, index) => {
                    const symbol = textFrom(item, 'symbol', `leg-${index + 1}`);
                    return (
                      <tr key={`${symbol}-${textFrom(item, 'exchange')}-${index}`}>
                        <td className="py-2 font-mono">{symbol}</td>
                        <td>{textFrom(item, 'exchange')}</td>
                        <td>{textFrom(item, 'side')}</td>
                        <td>{textFrom(item, 'status')}</td>
                        <td>{money(numberFrom(item, 'notionalUsdt'))}</td>
                        <td className="font-mono">{money(numberFrom(item, 'price'))}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : <EmptyPanel text="暂无组合腿执行状态；模拟盘启动后展示每条腿的成交、修复与平仓事件" />}
        </section>
      </div>
    </div>
  );
}
