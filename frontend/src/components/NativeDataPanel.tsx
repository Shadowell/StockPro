import { useCallback, useEffect, useState } from 'react';
import { Activity, Database, RefreshCw, WifiOff } from 'lucide-react';
import { nativeSentimentApi, type NativeSentimentResponse } from '../api/client';



const PIPELINE_LABELS: Record<string, string> = {
  rubik_taker_volume: '资金流（OKX 日频）',
  rubik_long_short: '多空账户比（OKX）',
  funding_okx: '资金费率（OKX）',
  oi_okx_forward: 'OI 快照（OKX 积累中）',
  oi_binance_backfill: 'OI 历史（回填）',
};

function fmtCompact(n: number): string {
  if (!Number.isFinite(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toFixed(2);
}

function SignedValue({ value, suffix = '' }: { value: number | null; suffix?: string }) {
  if (value === null || !Number.isFinite(value)) return <span className="text-gray-500">—</span>;
  const up = value >= 0;
  return (
    <span className={up ? 'text-up' : 'text-down'}>
      {up ? '+' : ''}{value.toFixed(2)}{suffix}
    </span>
  );
}

export default function NativeDataPanel({ className = '' }: { className?: string }) {
  const [data, setData] = useState<NativeSentimentResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      setFailed(false);
      const res = await nativeSentimentApi.get();
      setData(res);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section
      data-testid="native-data-panel"
      className={`rounded-lg border border-crypto-border bg-crypto-card ${className}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-4 py-3">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-cyan-400" />
          <h2 className="text-sm font-semibold text-white">加密原生数据</h2>
          <span className="rounded-md border border-slate-600/45 bg-slate-900/70 px-2 py-0.5 text-[10px] font-medium text-slate-400">
            资金流 · 多空比 · 资金费率 · OI
          </span>
        </div>
        <button
          onClick={() => void load()}
          className="flex h-7 items-center gap-1.5 rounded-md border border-crypto-border bg-gray-800 px-2 text-xs text-gray-400 transition hover:text-white hover:bg-gray-700"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} /> 刷新
        </button>
      </div>

      {loading && !data ? (
        <div className="px-4 py-8 text-center text-xs text-gray-500">加载中...</div>
      ) : failed && !data ? (
        <div className="flex items-center justify-center gap-2 px-4 py-8 text-xs text-gray-500">
          <WifiOff className="h-3.5 w-3.5" /> 加载失败，请稍后刷新
        </div>
      ) : !data?.core?.length ? (
        <div className="px-4 py-8 text-center text-xs text-gray-500">暂无数据</div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 px-4 py-4 md:grid-cols-3">
            {data.core.map((item) => (
              <div key={item.ccy} className="rounded-lg border border-crypto-border/70 bg-gray-900/40 px-3 py-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm font-semibold text-white">{item.ccy}</span>
                  <span className="text-[10px] text-gray-500">USDT 永续</span>
                </div>
                <div className="space-y-1.5 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">资金流买入占比</span>
                    {item.taker?.buyRatio != null ? (
                      <SignedValue value={(item.taker.buyRatio - 0.5) * 200} suffix="%" />
                    ) : (
                      <span className="text-gray-500">—</span>
                    )}
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">多空账户比</span>
                    {item.longShortRatio ? (
                      <span className={item.longShortRatio.value >= 1 ? 'text-up' : 'text-down'}>
                        {item.longShortRatio.value.toFixed(2)}
                      </span>
                    ) : (
                      <span className="text-gray-500">—</span>
                    )}
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">资金费率</span>
                    {item.fundingRate ? (
                      <SignedValue value={item.fundingRate.value * 100} suffix="%" />
                    ) : (
                      <span className="text-gray-500">—</span>
                    )}
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">持仓量 24h</span>
                    {item.oi ? (
                      <span className="flex items-center gap-2">
                        <span className="text-gray-300">{fmtCompact(item.oi.openInterestUsd)}</span>
                        <SignedValue value={item.oi.change24hPct} suffix="%" />
                      </span>
                    ) : (
                      <span className="text-gray-500">—</span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="border-t border-crypto-border/60 px-4 py-3">
            <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-gray-500">
              <Activity className="h-3 w-3" /> 数据管道积累
            </div>
            <div className="grid grid-cols-1 gap-1 text-[11px] md:grid-cols-2 xl:grid-cols-5">
              {Object.entries(data.pipeline || {}).map(([key, span]) => (
                <div key={key} className="flex items-center justify-between rounded border border-crypto-border/50 bg-gray-900/30 px-2 py-1">
                  <span className="text-gray-500">{PIPELINE_LABELS[key] || key}</span>
                  <span className="text-gray-300">
                    {span.rows.toLocaleString()} 行
                    {span.from ? <span className="ml-1 text-gray-600">{span.from}~</span> : null}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
