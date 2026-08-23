import type { Dispatch, SetStateAction } from 'react';
import {
  CheckCircle2, History, PauseCircle, Play, Radio,
  RefreshCw, Send, ShieldCheck, WalletCards,
} from 'lucide-react';
import {
  MetricCard, finiteNumber, fmtNumber, fmtPct, fmtSignedPct, fmtSignedUsd, formatDateTime,
  type OrbitAutoPostConfig, type OrbitCandidate, type OrbitLoginStatus, type OrbitPostRecord,
} from './aiLabSupport';

interface OrbitPostPanelProps {
  autonomousModelOptions: string[];
  handlePublishOrbitCandidate: (candidate: OrbitCandidate) => void;
  handleRunOrbitAutoPost: () => void;
  handleSaveOrbitConfig: (updates: Partial<OrbitAutoPostConfig>) => void;
  orbitCandidates: OrbitCandidate[];
  orbitConfig: OrbitAutoPostConfig;
  orbitEligibleCount: number;
  orbitHistory: OrbitPostRecord[];
  orbitLoading: boolean;
  orbitLoginStatus: OrbitLoginStatus | null;
  orbitPublishingId: string;
  orbitRunning: boolean;
  orbitSaving: boolean;
  orbitStatus: string;
  refreshOrbitAutoPost: () => void;
  selectedOrbitModel: string;
  setOrbitConfig: Dispatch<SetStateAction<OrbitAutoPostConfig>>;
}

export default function OrbitPostPanel({
  autonomousModelOptions,
  handlePublishOrbitCandidate,
  handleRunOrbitAutoPost,
  handleSaveOrbitConfig,
  orbitCandidates,
  orbitConfig,
  orbitEligibleCount,
  orbitHistory,
  orbitLoading,
  orbitLoginStatus,
  orbitPublishingId,
  orbitRunning,
  orbitSaving,
  orbitStatus,
  refreshOrbitAutoPost,
  selectedOrbitModel,
  setOrbitConfig,
}: OrbitPostPanelProps) {
  return (
        <div className="space-y-4">
          <div className="rounded-2xl border border-cyan-500/20 bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.15),transparent_34%),linear-gradient(180deg,rgba(255,255,255,0.045),rgba(255,255,255,0.014))] p-4">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
              <div className="min-w-0">
                <div className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-500/10 px-2.5 py-1 text-[11px] font-semibold text-cyan-200">
                  <Radio size={13} />
                  OKX Orbit · 单账号自动发帖
                </div>
                <h2 className="mt-3 text-2xl font-semibold text-gray-50">真实合约单星球发布台</h2>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-400">
                  只读取已绑定 OKX 实盘账户的当前合约持仓，收益超过阈值后生成 AI 文案并提交星球；同一合约单按冷却时间去重，文案保留真实收益和风险提示。
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleSaveOrbitConfig({ enabled: !orbitConfig.enabled, llmModel: selectedOrbitModel })}
                  disabled={orbitSaving}
                  className={`inline-flex h-9 items-center justify-center gap-2 rounded-md px-4 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-60 ${
                    orbitConfig.enabled
                      ? 'border border-emerald-500/40 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/20'
                      : 'border border-crypto-border bg-crypto-bg text-gray-300 hover:border-cyan-500/50'
                  }`}
                >
                  {orbitConfig.enabled ? <PauseCircle size={15} /> : <Play size={15} />}
                  {orbitConfig.enabled ? '自动发帖 ON' : '自动发帖 OFF'}
                </button>
                <button
                  type="button"
                  onClick={handleRunOrbitAutoPost}
                  disabled={orbitRunning}
                  className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-cyan-500/45 bg-cyan-500/15 px-4 text-xs font-semibold text-cyan-200 transition hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {orbitRunning ? <RefreshCw size={15} className="animate-spin" /> : <Send size={15} />}
                  立即扫描并发帖
                </button>
                <button
                  type="button"
                  onClick={refreshOrbitAutoPost}
                  disabled={orbitLoading}
                  className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-crypto-border bg-crypto-bg px-4 text-xs font-semibold text-gray-300 transition hover:border-cyan-500/50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <RefreshCw size={14} className={orbitLoading ? 'animate-spin' : ''} />
                  刷新
                </button>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
              <MetricCard label="符合条件" value={`${orbitEligibleCount}/${orbitCandidates.length}`} tone="info" />
              <MetricCard label="收益阈值" value={`≥ ${fmtPct(orbitConfig.minMarginRoiPct, 1)}`} tone="good" />
              <MetricCard label="扫描间隔" value={`${orbitConfig.intervalMinutes} 分钟`} />
              <MetricCard label="单轮上限" value={`${orbitConfig.maxPostsPerRun} 条`} />
              <MetricCard label="Orbit 登录" value={orbitLoginStatus?.logged_in ? '已登录' : '未登录'} tone={orbitLoginStatus?.logged_in ? 'good' : 'bad'} />
            </div>

            {(orbitStatus || orbitConfig.lastError || orbitLoginStatus?.error) && (
              <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${
                (orbitStatus || orbitConfig.lastError || orbitLoginStatus?.error || '').includes('失败') || orbitConfig.lastError || orbitLoginStatus?.error
                  ? 'border-red-500/30 bg-red-500/10 text-red-300'
                  : 'border-cyan-500/30 bg-cyan-500/10 text-cyan-200'
              }`}>
                {orbitStatus || orbitConfig.lastError || orbitLoginStatus?.error}
              </div>
            )}
          </div>

          <div className="grid gap-4 xl:grid-cols-[420px_1fr]">
            <div className="rounded-2xl border border-crypto-border bg-crypto-card p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h3 className="flex items-center gap-2 text-base font-semibold text-gray-100">
                    <ShieldCheck size={18} className="text-cyan-300" />
                    发布配置
                  </h3>
                  <p className="mt-1 text-xs text-gray-500">保存后调度器每分钟检查，到点才扫描。</p>
                </div>
                <button
                  type="button"
                  onClick={() => handleSaveOrbitConfig({ llmModel: selectedOrbitModel })}
                  disabled={orbitSaving}
                  className="inline-flex h-8 items-center justify-center gap-2 rounded-md bg-blue-600 px-3 text-xs font-semibold text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {orbitSaving ? <RefreshCw size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
                  保存
                </button>
              </div>
              <div className="mt-4 space-y-3">
                <label className="block">
                  <span className="text-xs text-gray-400">实盘账户</span>
                  <input
                    value={orbitConfig.accountId}
                    onChange={(e) => setOrbitConfig((prev) => ({ ...prev, accountId: e.target.value }))}
                    className="mt-1 h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-gray-100 outline-none focus:border-cyan-500"
                  />
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <label className="block">
                    <span className="text-xs text-gray-400">收益超过</span>
                    <input
                      type="number"
                      min={0.1}
                      step={0.1}
                      value={orbitConfig.minMarginRoiPct}
                      onChange={(e) => setOrbitConfig((prev) => ({ ...prev, minMarginRoiPct: Number(e.target.value) }))}
                      className="mt-1 h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-gray-100 outline-none focus:border-cyan-500"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs text-gray-400">扫描分钟</span>
                    <input
                      type="number"
                      min={1}
                      value={orbitConfig.intervalMinutes}
                      onChange={(e) => setOrbitConfig((prev) => ({ ...prev, intervalMinutes: Number(e.target.value) }))}
                      className="mt-1 h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-gray-100 outline-none focus:border-cyan-500"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs text-gray-400">冷却小时</span>
                    <input
                      type="number"
                      min={0}
                      value={orbitConfig.cooldownHours}
                      onChange={(e) => setOrbitConfig((prev) => ({ ...prev, cooldownHours: Number(e.target.value) }))}
                      className="mt-1 h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-gray-100 outline-none focus:border-cyan-500"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs text-gray-400">单轮条数</span>
                    <input
                      type="number"
                      min={1}
                      max={5}
                      value={orbitConfig.maxPostsPerRun}
                      onChange={(e) => setOrbitConfig((prev) => ({ ...prev, maxPostsPerRun: Number(e.target.value) }))}
                      className="mt-1 h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-gray-100 outline-none focus:border-cyan-500"
                    />
                  </label>
                </div>
                <label className="block">
                  <span className="text-xs text-gray-400">AI 文案模型</span>
                  <select
                    value={orbitConfig.llmModel || selectedOrbitModel}
                    onChange={(e) => setOrbitConfig((prev) => ({ ...prev, llmModel: e.target.value }))}
                    className="mt-1 h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-gray-100 outline-none focus:border-cyan-500"
                  >
                    {autonomousModelOptions.length > 0 ? (
                      autonomousModelOptions.map((model) => (
                        <option key={model} value={model}>{model}</option>
                      ))
                    ) : (
                      <option value="">全局默认</option>
                    )}
                  </select>
                </label>
                <label className="block">
                  <span className="text-xs text-gray-400">文案风格</span>
                  <textarea
                    value={orbitConfig.copyStyle}
                    onChange={(e) => setOrbitConfig((prev) => ({ ...prev, copyStyle: e.target.value }))}
                    rows={4}
                    className="mt-1 w-full resize-none rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 text-sm text-gray-100 outline-none focus:border-cyan-500"
                  />
                </label>
              </div>
            </div>

            <div className="space-y-4">
              <div className="rounded-2xl border border-crypto-border bg-crypto-card">
                <div className="flex items-center justify-between border-b border-crypto-border px-4 py-3">
                  <h3 className="flex items-center gap-2 text-base font-semibold text-gray-100">
                    <WalletCards size={18} className="text-cyan-300" />
                    候选合约单
                  </h3>
                  <span className="text-xs text-gray-500">按保证金收益率排序</span>
                </div>
                <div className="max-h-[420px] space-y-3 overflow-y-auto p-4">
                  {orbitCandidates.length > 0 ? (
                    orbitCandidates.map((candidate) => {
                      const eligible = Boolean(candidate.eligible);
                      return (
                        <div key={candidate.id} className={`rounded-xl border p-3 ${eligible ? 'border-cyan-500/30 bg-cyan-500/5' : 'border-crypto-border bg-crypto-bg/60'}`}>
                          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="text-lg font-semibold text-gray-50">{candidate.symbol}</span>
                                <span className={`rounded-md px-2 py-0.5 text-xs font-semibold ${candidate.side === 'short' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-red-500/15 text-red-300'}`}>
                                  {candidate.side_label || (candidate.side === 'short' ? '做空' : '做多')}
                                </span>
                                <span className="rounded-md bg-crypto-border/60 px-2 py-0.5 text-xs font-semibold text-gray-300">{fmtNumber(candidate.leverage, 0)}x</span>
                                {!eligible && (
                                  <span className="rounded-md border border-gray-600 px-2 py-0.5 text-xs text-gray-400">{candidate.blocked_reason || '未达标'}</span>
                                )}
                              </div>
                              <div className="mt-2 grid grid-cols-2 gap-3 text-xs text-gray-400 md:grid-cols-5">
                                <div><span className="block text-gray-600">保证金收益率</span><strong className={finiteNumber(candidate.margin_roi_pct)! >= 0 ? 'text-red-400' : 'text-green-400'}>{fmtSignedPct(candidate.margin_roi_pct)}</strong></div>
                                <div><span className="block text-gray-600">浮盈</span><strong className={finiteNumber(candidate.unrealized_pnl)! >= 0 ? 'text-red-400' : 'text-green-400'}>{fmtSignedUsd(candidate.unrealized_pnl)}</strong></div>
                                <div><span className="block text-gray-600">保证金</span><strong className="text-gray-200">${fmtNumber(candidate.margin, 2)}</strong></div>
                                <div><span className="block text-gray-600">入场</span><strong className="text-gray-200">{fmtNumber(candidate.entry_price, 6)}</strong></div>
                                <div><span className="block text-gray-600">当前</span><strong className="text-gray-200">{fmtNumber(candidate.mark_price, 6)}</strong></div>
                              </div>
                            </div>
                            <button
                              type="button"
                              onClick={() => handlePublishOrbitCandidate(candidate)}
                              disabled={!eligible || orbitPublishingId === candidate.id}
                              className="inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded-md border border-cyan-500/45 bg-cyan-500/15 px-3 text-xs font-semibold text-cyan-200 transition hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              {orbitPublishingId === candidate.id ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
                              手动发帖
                            </button>
                          </div>
                        </div>
                      );
                    })
                  ) : (
                    <div className="rounded-xl border border-dashed border-crypto-border bg-crypto-bg/40 p-6 text-center text-sm text-gray-500">
                      暂无符合扫描范围的实盘合约持仓
                    </div>
                  )}
                </div>
              </div>

              <div className="rounded-2xl border border-crypto-border bg-crypto-card">
                <div className="flex items-center justify-between border-b border-crypto-border px-4 py-3">
                  <h3 className="flex items-center gap-2 text-base font-semibold text-gray-100">
                    <History size={18} className="text-cyan-300" />
                    发布记录
                  </h3>
                  <span className="text-xs text-gray-500">{orbitHistory.length} 条</span>
                </div>
                <div className="max-h-[300px] space-y-3 overflow-y-auto p-4">
                  {orbitHistory.length > 0 ? (
                    orbitHistory.map((record) => (
                      <div key={record.id} className="rounded-xl border border-crypto-border bg-crypto-bg/60 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-semibold text-gray-100">{record.candidate?.symbol || '--'} · {record.status || '--'}</div>
                            <div className="mt-1 text-[11px] text-gray-500">{record.created_at ? formatDateTime(record.created_at) : '--'}</div>
                          </div>
                          {record.url && (
                            <a href={record.url} target="_blank" rel="noreferrer" className="text-xs font-semibold text-cyan-300 hover:text-cyan-200">打开</a>
                          )}
                        </div>
                        <p className="mt-2 line-clamp-3 text-xs leading-5 text-gray-400">{record.content || record.error || '--'}</p>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-xl border border-dashed border-crypto-border bg-crypto-bg/40 p-5 text-center text-sm text-gray-500">
                      还没有星球发布记录
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
  );
}
