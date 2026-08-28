import { useCallback, useEffect, useState } from 'react';
import { Flame } from 'lucide-react';
import clsx from 'clsx';
import { marketApi, parseApiError, type LimitLadderPayload } from '../api/client';
import { AnalysisSection, formatAmountYi, formatSignedPercent } from './analysisShared';

const POOL_TABS = [
  { key: 'up', label: '涨停池' },
  { key: 'broken', label: '炸板池' },
  { key: 'down', label: '跌停池' },
] as const;

type PoolKey = (typeof POOL_TABS)[number]['key'];

interface LimitUpLadderProps {
  onSelectSymbol: (symbol: string) => void;
}

export default function LimitUpLadder({ onSelectSymbol }: LimitUpLadderProps) {
  const [payload, setPayload] = useState<LimitLadderPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [poolTab, setPoolTab] = useState<PoolKey>('up');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPayload(await marketApi.getLimitLadder(30));
    } catch (err) {
      setError(parseApiError(err, '连板梯队读取失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const levels = payload?.levels || [];
  const trend = payload?.trend || [];
  const maxTrendTotal = Math.max(1, ...trend.map((p) => p.total));
  const pools = payload?.pools || { up: [], broken: [], down: [] };
  const activePool = pools[poolTab] || [];
  const maxHeight = levels.length ? levels[0].level : 0;

  return (
    <AnalysisSection
      icon={<Flame className="h-4 w-4 text-orange-300" />}
      title="连板梯队"
      subtitle={`最高 ${maxHeight || '—'} 板 · 共 ${payload?.ladderTotal ?? 0} 只`}
      status={payload?.dataStatus}
      dateLabel={`梯队 ${payload?.ladderDate || '—'} · 池 ${payload?.poolTradeDate || '—'}`}
      loading={loading}
      error={error}
      onRetry={load}
      hasContent={Boolean(payload && (levels.length || trend.length || (pools.up || []).length || (pools.down || []).length))}
      emptyReason={payload?.unavailableReason || '暂无已同步的连板梯队事实'}
      footer={`来源 ${(payload?.sources || []).join(' + ') || '—'} · 梯队与池为异步管道快照，日期可能滞后 · 只读 · writes_performed=false`}
    >
      <div className="space-y-4 p-4">
        {levels.length ? (
          <div className="space-y-2">
            {levels.map((level) => (
              <div key={level.level} className="rounded-lg border border-crypto-border/60 bg-slate-950/30 px-3 py-2.5">
                <div className="mb-2 flex items-center gap-2">
                  <span
                    className={clsx(
                      'rounded-md px-2 py-0.5 text-xs font-bold',
                      level.level >= 5
                        ? 'bg-red-500/15 text-red-300'
                        : level.level >= 3
                          ? 'bg-amber-500/15 text-amber-300'
                          : 'bg-slate-500/15 text-slate-300',
                    )}
                  >
                    {level.level} 板
                  </span>
                  <span className="text-[11px] text-gray-500">{level.members.length} 只</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {level.members.map((member) => (
                    <button
                      key={member.symbol}
                      type="button"
                      onClick={() => onSelectSymbol(member.symbol)}
                      className="rounded-md border border-crypto-border/70 bg-white/[0.03] px-2.5 py-1.5 text-left transition hover:border-cyan-500/30 hover:bg-white/[0.06]"
                      title={member.reason || member.symbol}
                    >
                      <span className="block max-w-[8.5rem] truncate text-xs font-medium text-gray-200">{member.name}</span>
                      <span className="mt-0.5 flex items-center gap-1.5 text-[10px]">
                        <span className="font-mono text-gray-500">{member.symbol}</span>
                        <span className={(member.changePercent ?? 0) >= 0 ? 'text-up' : 'text-down'}>
                          {formatSignedPercent(member.changePercent)}
                        </span>
                        {member.durationDays != null ? (
                          <span className="text-gray-600">{member.durationDays} 天</span>
                        ) : null}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : null}

        <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex overflow-hidden rounded-lg border border-crypto-border">
              {POOL_TABS.map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setPoolTab(tab.key)}
                  className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                    poolTab === tab.key ? 'bg-blue-600 text-white' : 'text-gray-500 hover:bg-gray-800/60 hover:text-gray-300'
                  }`}
                >
                  {tab.label} {pools[tab.key]?.length ?? 0}
                </button>
              ))}
            </div>
            <span className="text-[10px] text-gray-500">封单额为快照口径 · 点击标的进行情页</span>
          </div>
          {activePool.length ? (
            <div className="overflow-x-auto rounded-lg border border-crypto-border/60">
              <div className="min-w-[680px]">
                <div className="grid grid-cols-[minmax(180px,1.4fr)_72px_96px_minmax(110px,1fr)_82px] gap-2 border-b border-crypto-border/50 bg-slate-950/40 px-3 py-2 text-[10px] text-gray-500">
                  <span>标的</span>
                  <span className="text-right">连板数</span>
                  <span className="text-right">封单额</span>
                  <span>行业</span>
                  <span className="text-right">开板</span>
                </div>
                <div className="max-h-72 divide-y divide-crypto-border/35 overflow-y-auto">
                  {activePool.map((member) => (
                    <button
                      key={`${poolTab}-${member.symbol}`}
                      type="button"
                      onClick={() => onSelectSymbol(member.symbol)}
                      className="grid w-full grid-cols-[minmax(180px,1.4fr)_72px_96px_minmax(110px,1fr)_82px] items-center gap-2 px-3 py-2 text-left text-[11px] transition hover:bg-white/[0.03]"
                    >
                      <span className="flex min-w-0 items-center gap-1.5">
                        <span className="truncate font-medium text-gray-200">{member.name}</span>
                        <span className="shrink-0 font-mono text-[10px] text-gray-600">{member.symbol}</span>
                        {member.isSt ? <span className="shrink-0 rounded border border-rose-500/25 bg-rose-500/[0.08] px-1 text-[9px] text-rose-300">ST</span> : null}
                      </span>
                      <span className="text-right font-mono tabular-nums text-amber-300">{member.limitTimes ?? '—'}</span>
                      <span className="text-right font-mono tabular-nums text-gray-300">{formatAmountYi(member.sealAmount)}</span>
                      <span className="truncate text-gray-500">{member.industry || member.board || '—'}</span>
                      <span className="text-right font-mono tabular-nums text-gray-400">{member.openTimes ?? '—'}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex h-24 items-center justify-center rounded-lg border border-crypto-border/50 text-xs text-gray-500">
              {POOL_TABS.find((tab) => tab.key === poolTab)?.label}暂无成员
            </div>
          )}
        </div>

        {trend.length ? (
          <div>
            <div className="mb-2 text-[11px] font-semibold text-gray-400">梯队趋势（近 {payload?.trendDays ?? 30} 个梯队日）</div>
            <div className="overflow-x-auto rounded-lg border border-crypto-border/60">
              <div className="flex min-w-max items-end gap-2 px-3 py-3">
                {trend.map((point) => (
                  <div key={point.date} className="flex w-12 shrink-0 flex-col items-center gap-1" title={`${point.date}：最高 ${point.maxHeight} 板 · ${point.total} 只 · ≥2板 ${point.twoPlus}`}>
                    <span className="text-[9px] tabular-nums text-gray-500">{point.total}</span>
                    <div className="flex h-20 w-6 items-end rounded bg-slate-800/80">
                      <div
                        className="w-full rounded bg-gradient-to-t from-red-500/70 to-amber-400/80"
                        style={{ height: `${Math.max(8, (point.total / maxTrendTotal) * 100)}%` }}
                      />
                    </div>
                    <span className="text-[9px] tabular-nums text-amber-300/90">{point.maxHeight}板</span>
                    <span className="text-[8px] tabular-nums text-gray-600">{point.date.slice(5)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </AnalysisSection>
  );
}
