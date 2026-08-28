import { useCallback, useEffect, useState } from 'react';
import { Gauge } from 'lucide-react';
import clsx from 'clsx';
import {
  marketApi,
  parseApiError,
  type ConceptAnalysisPayload,
  type IndustryAnalysisPayload,
  type LimitLadderPayload,
  type MarketPhase,
  type MarketTimelinePayload,
} from '../api/client';
import { AnalysisSection, formatSignedPercent } from './analysisShared';

export default function MarketEnvironment() {
  const [phase, setPhase] = useState<MarketPhase | null>(null);
  const [timeline, setTimeline] = useState<MarketTimelinePayload | null>(null);
  const [ladder, setLadder] = useState<LimitLadderPayload | null>(null);
  const [industry, setIndustry] = useState<IndustryAnalysisPayload | null>(null);
  const [concept, setConcept] = useState<ConceptAnalysisPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [phaseData, timelineData, ladderData, industryData, conceptData] = await Promise.all([
        marketApi.getPhase(),
        marketApi.getTimeline(30),
        marketApi.getLimitLadder(30),
        marketApi.getIndustryAnalysis().catch(() => null),
        marketApi.getConceptAnalysis(20, 8).catch(() => null),
      ]);
      setPhase(phaseData);
      setTimeline(timelineData);
      setLadder(ladderData);
      setIndustry(industryData);
      setConcept(conceptData);
    } catch (err) {
      setError(parseApiError(err, '市场环境读取失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const trend = [...(ladder?.trend || [])].slice(-14);
  const maxTrendTotal = Math.max(1, ...trend.map((p) => p.total));
  const latest = trend[trend.length - 1];
  const timelineRows = (timeline?.items || []).slice(-14).reverse();
  const leadingIndustries = (industry?.industries || []).slice(0, 3);
  const leadingConcepts = (concept?.sectors || []).slice(0, 3);

  return (
    <AnalysisSection
      icon={<Gauge className="h-4 w-4 text-emerald-300" />}
      title="市场环境"
      subtitle={`六阶段 + 涨停梯队情绪 · 梯队源 ${ladder?.ladderDate || '—'}`}
      status={phase?.status}
      dateLabel={latest ? `梯队 ${latest.date}` : undefined}
      loading={loading}
      error={error}
      onRetry={load}
      hasContent={Boolean(phase || timelineRows.length || trend.length)}
      emptyReason="暂无已物化的市场阶段与梯队事实（需运行盘后同步管道）"
      footer="阶段读 market_phase_results（本地未物化时诚实展示）· 梯队读 lianban_ladder_history · 只读"
    >
      <div className="space-y-4 p-4">
        <div className="grid gap-3 lg:grid-cols-3">
          <div className="rounded-lg border border-crypto-border/60 p-3">
            <div className="text-[10px] text-gray-500">当前阶段</div>
            <div className="mt-1 text-lg font-semibold text-gray-100">{phase?.phase && phase.phase !== 'unknown' ? phase.phase : '待计算'}</div>
            <div className="mt-0.5 text-[10px] text-gray-500">
              置信度 {phase ? `${Math.round((phase.confidence ?? 0) * 100)}%` : '—'}
            </div>
            <div className="mt-2 line-clamp-3 text-[10px] leading-4 text-gray-600">
              {(phase?.reasons?.length ? phase.reasons : phase?.missingInputs || ['暂无已计算结果']).join(' · ')}
            </div>
          </div>
          <div className="rounded-lg border border-crypto-border/60 p-3">
            <div className="text-[10px] text-gray-500">梯队情绪（最新梯队日）</div>
            <div className="mt-1 grid grid-cols-3 gap-2 text-center">
              <div>
                <div className="text-lg font-semibold text-amber-300">{latest?.maxHeight ?? '—'}</div>
                <div className="text-[10px] text-gray-600">最高板</div>
              </div>
              <div>
                <div className="text-lg font-semibold text-gray-100">{latest?.total ?? '—'}</div>
                <div className="text-[10px] text-gray-600">涨停梯队</div>
              </div>
              <div>
                <div className="text-lg font-semibold text-gray-100">{latest?.twoPlus ?? '—'}</div>
                <div className="text-[10px] text-gray-600">≥2板宽度</div>
              </div>
            </div>
            <div className="mt-2 text-[10px] text-gray-600">炸板 {ladder?.pools.broken.length ?? '—'} · 跌停 {ladder?.pools.down.length ?? '—'}</div>
          </div>
          <div className="rounded-lg border border-crypto-border/60 p-3">
            <div className="text-[10px] text-gray-500">梯队高度演变（近 {trend.length} 个梯队日）</div>
            <div className="mt-2 flex h-20 items-end gap-1">
              {trend.map((point) => (
                <div
                  key={point.date}
                  className="flex-1 rounded-t bg-gradient-to-t from-red-500/60 to-amber-400/70"
                  style={{ height: `${Math.max(8, (point.total / maxTrendTotal) * 100)}%` }}
                  title={`${point.date}：${point.total} 只 · 最高 ${point.maxHeight} 板`}
                />
              ))}
              {!trend.length ? <div className="flex h-full w-full items-center justify-center text-[11px] text-gray-600">暂无梯队历史</div> : null}
            </div>
          </div>
        </div>

        <div className="overflow-x-auto rounded-lg border border-crypto-border/60">
          <div className="min-w-[880px]">
            <div className="grid grid-cols-[92px_88px_64px_repeat(3,64px)_72px_72px_84px_minmax(200px,1fr)] gap-2 border-b border-crypto-border/50 bg-slate-950/40 px-3 py-2 text-[10px] text-gray-500">
              <span>交易日</span><span>阶段</span><span>置信度</span><span>涨停</span><span>跌停</span><span>炸板</span><span>封板率</span><span>最高板</span><span>快照</span><span>阶段解释</span>
            </div>
            {timelineRows.map((row) => (
              <div
                key={row.tradeDate}
                className="grid grid-cols-[92px_88px_64px_repeat(3,64px)_72px_72px_84px_minmax(200px,1fr)] items-center gap-2 border-b border-crypto-border/30 px-3 py-2 text-[11px] text-gray-400"
              >
                <span className="font-mono">{row.tradeDate}</span>
                <span className={clsx('font-medium', row.weakMarketVeto ? 'text-rose-300' : 'text-blue-200')}>{row.phase}</span>
                <span className="font-mono">{row.confidence == null ? '—' : `${Math.round(row.confidence * 100)}%`}</span>
                <span className="font-mono text-up">{row.limitUpCount ?? '—'}</span>
                <span className="font-mono text-down">{row.limitDownCount ?? '—'}</span>
                <span className="font-mono text-amber-300">{row.failedLimitCount ?? '—'}</span>
                <span className="font-mono">{row.sealRatePct == null ? '—' : `${row.sealRatePct.toFixed(1)}%`}</span>
                <span className="font-mono">{row.highestStreak == null ? '—' : `${row.highestStreak}板`}</span>
                <span className={clsx('font-mono', row.snapshotConsistent ? 'text-emerald-300' : 'text-amber-300')}>
                  {row.sourceSnapshotId == null ? '不一致' : `#${row.sourceSnapshotId}`}
                </span>
                <span className="truncate" title={(row.reasons || []).join(' · ')}>
                  {(row.reasons || []).join(' · ') || row.phaseMissingInputs.join(' · ') || '—'}
                </span>
              </div>
            ))}
            {!timelineRows.length ? (
              <div className="flex h-24 items-center justify-center text-xs text-gray-500">
                {timeline?.unavailableReason || '暂无已持久化的市场阶段历史'}
              </div>
            ) : null}
          </div>
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <div className="rounded-lg border border-crypto-border/60">
            <div className="border-b border-crypto-border/50 px-3 py-2 text-[11px] font-semibold text-gray-400">领涨行业（等权当日）</div>
            {leadingIndustries.length ? leadingIndustries.map((row) => (
              <div key={row.code} className="grid grid-cols-[minmax(0,1fr)_72px_64px] items-center gap-2 border-t border-crypto-border/30 px-3 py-2 text-[11px]">
                <span className="truncate text-gray-200">{row.name}</span>
                <span className={clsx('text-right font-mono tabular-nums', (row.change1d ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                  {formatSignedPercent(row.change1d)}
                </span>
                <span className="text-right tabular-nums text-gray-600">{row.count}只</span>
              </div>
            )) : (
              <div className="px-3 py-6 text-center text-[11px] text-gray-500">{industry?.unavailableReason || '暂无行业等权事实'}</div>
            )}
          </div>
          <div className="rounded-lg border border-crypto-border/60">
            <div className="border-b border-crypto-border/50 px-3 py-2 text-[11px] font-semibold text-gray-400">领涨概念</div>
            {leadingConcepts.length ? leadingConcepts.map((row) => (
              <div key={row.sectorName} className="grid grid-cols-[minmax(0,1fr)_72px_minmax(0,1fr)] items-center gap-2 border-t border-crypto-border/30 px-3 py-2 text-[11px]">
                <span className="truncate text-gray-200">{row.sectorName}</span>
                <span className={clsx('text-right font-mono tabular-nums', (row.changePercent ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                  {formatSignedPercent(row.changePercent)}
                </span>
                <span className="truncate text-right text-gray-500">{row.leaderStock || '—'}</span>
              </div>
            )) : (
              <div className="px-3 py-6 text-center text-[11px] text-gray-500">{concept?.unavailableReason || '暂无概念快照'}</div>
            )}
          </div>
        </div>

        <div className="text-[11px] text-gray-600">
          本地 RPS / 六阶段物化未运行时对应模块显示空态；梯队情绪由 lianban_ladder_history 直接推导，
          行业/概念领涨与「行业分析」「概念分析」tab 同口径。
        </div>
      </div>
    </AnalysisSection>
  );
}
