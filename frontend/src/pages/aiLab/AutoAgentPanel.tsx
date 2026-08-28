import type { Dispatch, SetStateAction } from 'react';
import { Play, RefreshCw, Settings } from 'lucide-react';
import { fmtNumber, type AutoAgentSchedulerConfig } from './aiLabSupport';

interface AutoAgentPanelProps {
  autoAgentBacktestLabel: string;
  autoAgentCandidates: Array<Record<string, any>>;
  autoAgentClosedLoop: Record<string, any> | null;
  autoAgentDecision: string;
  autoAgentHermes: Record<string, any>;
  autoAgentHermesSummary: string;
  autoAgentLoading: boolean;
  autoAgentMarketScan: Record<string, any>;
  autoAgentRejected: Array<Record<string, any>>;
  autoAgentResult: Record<string, any> | null;
  autoAgentRunId: string;
  autoAgentSchedulerConfig: AutoAgentSchedulerConfig;
  autoAgentSchedulerLastRun: string;
  autoAgentSchedulerNextRun: string;
  autoAgentSchedulerOpen: boolean;
  autoAgentSchedulerSaving: boolean;
  autoAgentSchedulerStatus: string;
  autoAgentSchedulerSymbolsText: string;
  autoAgentSource: Record<string, any>;
  autoAgentStatus: string;
  handleRunAutoAgentLocalCycle: () => void;
  pollAutoAgentRun: (runId: string) => void;
  refreshAutoAgentScheduler: () => void;
  runAutoAgentScheduledNow: () => void;
  saveAutoAgentScheduler: (enabled: boolean) => void;
  setAutoAgentScheduler: Dispatch<SetStateAction<AutoAgentSchedulerConfig | null>>;
  setAutoAgentSchedulerOpen: Dispatch<SetStateAction<boolean>>;
}

export default function AutoAgentPanel({
  autoAgentBacktestLabel,
  autoAgentCandidates,
  autoAgentClosedLoop,
  autoAgentDecision,
  autoAgentHermes,
  autoAgentHermesSummary,
  autoAgentLoading,
  autoAgentMarketScan,
  autoAgentRejected,
  autoAgentResult,
  autoAgentRunId,
  autoAgentSchedulerConfig,
  autoAgentSchedulerLastRun,
  autoAgentSchedulerNextRun,
  autoAgentSchedulerOpen,
  autoAgentSchedulerSaving,
  autoAgentSchedulerStatus,
  autoAgentSchedulerSymbolsText,
  autoAgentSource,
  autoAgentStatus,
  handleRunAutoAgentLocalCycle,
  pollAutoAgentRun,
  refreshAutoAgentScheduler,
  runAutoAgentScheduledNow,
  saveAutoAgentScheduler,
  setAutoAgentScheduler,
  setAutoAgentSchedulerOpen,
}: AutoAgentPanelProps) {
  return (
        <div className="space-y-4">
          <div className="overflow-hidden rounded-2xl border border-white/[0.08] bg-[radial-gradient(circle_at_top_left,rgba(113,112,255,0.18),transparent_32%),linear-gradient(180deg,rgba(255,255,255,0.055),rgba(255,255,255,0.018))] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
            <div className="grid gap-4 xl:grid-cols-[1.45fr_1fr]">
              <div className="min-w-0">
                <div className="inline-flex items-center gap-2 rounded-full border border-white/[0.08] bg-white/[0.03] px-2.5 py-1 text-[11px] font-medium text-gray-300">
                  <span className="h-1.5 w-1.5 rounded-full bg-purple-400 shadow-[0_0_12px_rgba(168,85,247,0.8)]" />
                  Linear Console · research/backtest/paper-simulation only
                </div>
                <h2 className="mt-4 max-w-3xl text-3xl font-semibold leading-none tracking-[-0.04em] text-gray-50 md:text-4xl">
                  自动交易 Agent 决策驾驶舱
                </h2>
                <p className="mt-3 max-w-3xl text-sm leading-6 text-gray-400">
                  自动采集 A 股公开行情，完成五 Agent 研究闭环，并把结论、操作和证据压缩到首屏；只参与研究深化，不自动实盘下单。
                </p>
                <div className="mt-5 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={handleRunAutoAgentLocalCycle}
                    disabled={autoAgentLoading}
                    className="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-[#5e6ad2] px-4 text-xs font-semibold text-white shadow-[0_0_0_1px_rgba(255,255,255,0.08)] hover:bg-[#7170ff] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {autoAgentLoading ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
                    立即开始研发
                  </button>
                  <button
                    type="button"
                    onClick={() => autoAgentRunId && void pollAutoAgentRun(autoAgentRunId)}
                    disabled={!autoAgentRunId || autoAgentLoading}
                    className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-white/[0.08] bg-white/[0.03] px-3 text-xs font-semibold text-gray-300 hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    <RefreshCw size={14} />
                    查看最近结果
                  </button>
                  <button
                    type="button"
                    onClick={() => setAutoAgentSchedulerOpen((open) => !open)}
                    className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-purple-400/30 bg-purple-500/10 px-3 text-xs font-semibold text-purple-100 hover:bg-purple-500/15"
                  >
                    <Settings size={14} />
                    定时执行
                  </button>
                </div>
              </div>

              <div className="grid gap-2 sm:grid-cols-2">
                {[
                  ['本轮结论', autoAgentDecision, autoAgentResult ? 'text-purple-100' : 'text-gray-300'],
                  ['真实行情快照', `${Number(autoAgentSource.snapshots_count || 0)} 个`, 'text-gray-100'],
                  ['Hermes 状态', autoAgentHermes.called ? (autoAgentHermes.status || 'called') : '未调用', autoAgentHermes.called ? 'text-emerald-300' : 'text-gray-300'],
                  ['实盘边界', 'live disabled', 'text-red-300'],
                  ['回测状态', autoAgentBacktestLabel, 'text-gray-100'],
                  ['Run ID', autoAgentRunId || '--', 'text-gray-300'],
                ].map(([label, value, valueClass]) => (
                  <div key={label} className="rounded-xl border border-white/[0.08] bg-black/20 p-3 shadow-[inset_0_0_12px_rgba(0,0,0,0.22)]">
                    <div className="text-[10px] uppercase tracking-[0.18em] text-gray-600">{label}</div>
                    <div className={`mt-1 truncate text-sm font-semibold ${valueClass}`}>{value}</div>
                  </div>
                ))}
              </div>
            </div>
            {autoAgentStatus && (
              <div className="mt-4 rounded-xl border border-purple-400/20 bg-purple-950/20 px-3 py-2 text-xs leading-5 text-purple-100/80">
                {autoAgentStatus}
              </div>
            )}
            {autoAgentSchedulerOpen && (
              <div className="mt-4 rounded-2xl border border-purple-400/20 bg-black/25 p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <div className="inline-flex items-center gap-2 rounded-full bg-purple-500/10 px-2.5 py-1 text-[11px] font-semibold text-purple-100">
                      定时执行配置 · 每分钟检查，到点后自动创建 paper-only 研发任务
                    </div>
                    <h3 className="mt-3 text-lg font-semibold text-gray-50">自动交易Agent定时执行</h3>
                    <p className="mt-1 max-w-2xl text-sm leading-6 text-gray-300">
                      开启后，系统按固定间隔自动采集 A 股公开行情、调用 Hermes 研究、运行安全回测矩阵；仍然不会连接券商实盘，也不会自动下单。
                    </p>
                  </div>
                  <span className={`w-fit rounded-full px-2.5 py-1 text-[11px] font-semibold ${autoAgentSchedulerConfig.enabled ? 'bg-emerald-500/15 text-emerald-300' : 'bg-gray-500/15 text-gray-300'}`}>
                    {autoAgentSchedulerConfig.enabled ? '定时已开启' : '定时未开启'}
                  </span>
                </div>

                <div className="mt-4 grid gap-3 md:grid-cols-3">
                  <label className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-3 text-xs text-gray-300">
                    <span className="font-semibold text-gray-100">执行间隔（分钟）</span>
                    <input
                      type="number"
                      min={15}
                      max={1440}
                      value={autoAgentSchedulerConfig.interval_minutes}
                      onChange={(e) => setAutoAgentScheduler({ ...autoAgentSchedulerConfig, interval_minutes: Number(e.target.value || 60) })}
                      className="mt-2 h-9 w-full rounded-lg border border-white/[0.08] bg-black/30 px-3 text-sm font-semibold text-white outline-none focus:border-purple-400/50"
                    />
                    <span className="mt-1 block text-[11px] text-gray-400">范围 15-1440 分钟，默认 60 分钟。</span>
                  </label>
                  <label className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-3 text-xs text-gray-300">
                    <span className="font-semibold text-gray-100">候选数量上限</span>
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={autoAgentSchedulerConfig.max_candidates}
                      onChange={(e) => setAutoAgentScheduler({ ...autoAgentSchedulerConfig, max_candidates: Number(e.target.value || 5) })}
                      className="mt-2 h-9 w-full rounded-lg border border-white/[0.08] bg-black/30 px-3 text-sm font-semibold text-white outline-none focus:border-purple-400/50"
                    />
                    <span className="mt-1 block text-[11px] text-gray-400">用于 Market Agent 过滤后的候选池。</span>
                  </label>
                  <label className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-3 text-xs text-gray-300">
                    <span className="font-semibold text-gray-100">Hermes 研究深化</span>
                    <select
                      value={autoAgentSchedulerConfig.use_hermes_agent ? 'true' : 'false'}
                      onChange={(e) => setAutoAgentScheduler({ ...autoAgentSchedulerConfig, use_hermes_agent: e.target.value === 'true' })}
                      className="mt-2 h-9 w-full rounded-lg border border-white/[0.08] bg-black/30 px-3 text-sm font-semibold text-white outline-none focus:border-purple-400/50"
                    >
                      <option value="true">启用 Hermes Bridge</option>
                      <option value="false">仅本地五 Agent 评分</option>
                    </select>
                    <span className="mt-1 block text-[11px] text-gray-400">推荐开启；失败也不会触发实盘。</span>
                  </label>
                </div>

                <label className="mt-3 block rounded-xl border border-white/[0.08] bg-white/[0.03] p-3 text-xs text-gray-300">
                  <span className="font-semibold text-gray-100">扫描股票池</span>
                  <textarea
                    value={autoAgentSchedulerSymbolsText}
                    onChange={(e) => setAutoAgentScheduler({
                      ...autoAgentSchedulerConfig,
                      symbols: e.target.value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean),
                    })}
                    rows={2}
                    className="mt-2 w-full rounded-lg border border-white/[0.08] bg-black/30 px-3 py-2 text-sm font-semibold text-white outline-none focus:border-purple-400/50"
                  />
                  <span className="mt-1 block text-[11px] text-gray-400">逗号或换行分隔；默认沪深主板与创业板流动性较好的样本股。</span>
                </label>

                <div className="mt-4 grid gap-3 md:grid-cols-3">
                  <div className="rounded-xl border border-white/[0.08] bg-black/20 p-3 text-xs text-gray-300">
                    <div className="font-semibold text-gray-100">上次执行</div>
                    <div className="mt-1">{autoAgentSchedulerLastRun}</div>
                  </div>
                  <div className="rounded-xl border border-white/[0.08] bg-black/20 p-3 text-xs text-gray-300">
                    <div className="font-semibold text-gray-100">预计下次</div>
                    <div className="mt-1">{autoAgentSchedulerNextRun}</div>
                  </div>
                  <div className="rounded-xl border border-white/[0.08] bg-black/20 p-3 text-xs text-gray-300">
                    <div className="font-semibold text-gray-100">最近 Run</div>
                    <div className="mt-1 truncate">{autoAgentSchedulerConfig.last_run_id || '--'}</div>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void saveAutoAgentScheduler(true)}
                    disabled={autoAgentSchedulerSaving}
                    className="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-emerald-600 px-4 text-xs font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <Settings size={14} />
                    保存并开启定时
                  </button>
                  <button
                    type="button"
                    onClick={() => void saveAutoAgentScheduler(false)}
                    disabled={autoAgentSchedulerSaving}
                    className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-white/[0.08] bg-white/[0.03] px-3 text-xs font-semibold text-gray-200 hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    关闭定时
                  </button>
                  <button
                    type="button"
                    onClick={runAutoAgentScheduledNow}
                    disabled={autoAgentSchedulerSaving}
                    className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-purple-400/30 bg-purple-500/10 px-3 text-xs font-semibold text-purple-100 hover:bg-purple-500/15 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    立即按定时配置执行一次
                  </button>
                  <button
                    type="button"
                    onClick={refreshAutoAgentScheduler}
                    disabled={autoAgentSchedulerSaving}
                    className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-white/[0.08] bg-transparent px-3 text-xs font-semibold text-gray-300 hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    刷新配置
                  </button>
                </div>
                {autoAgentSchedulerStatus && (
                  <div className="mt-3 rounded-xl border border-white/[0.08] bg-black/20 px-3 py-2 text-xs leading-5 text-gray-200">{autoAgentSchedulerStatus}</div>
                )}
              </div>
            )}
          </div>

          <div className="grid gap-3 lg:grid-cols-5">
            {[
              ['01', 'Market Agent', '流动性、深度、价差、ADX、EMA gap 与波动率先过滤噪音。'],
              ['02', 'Strategy Agent', '把机会转成可回测策略模板，不让 AI 临场自由下单。'],
              ['03', 'Risk Agent', '统一仓位、杠杆、日亏损、频率、冷却期和人工审批边界。'],
              ['04', 'Execution Agent', '只输出 paper/simulation trade_intent，实盘另走 /live-real。'],
              ['05', 'Review Agent', '定义回测矩阵、模拟观察、晋级和复盘指标。'],
            ].map(([step, name, desc]) => (
              <div key={name} className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.035)]">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs font-semibold text-gray-100">{name}</div>
                  <div className="font-mono text-[10px] text-purple-300/70">{step}</div>
                </div>
                <p className="mt-2 text-[11px] leading-5 text-gray-500">{desc}</p>
              </div>
            ))}
          </div>

          <div className="rounded-2xl border border-white/[0.08] bg-white/[0.025] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.035)]">
            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div>
                <h3 className="text-sm font-semibold text-gray-100">本地闭环产物</h3>
                <p className="mt-1 text-xs text-gray-500">结论优先，其次给操作建议和可审计证据；原始 JSON 仅作为调试折叠项。</p>
              </div>
              <span className="w-fit rounded-full border border-white/[0.08] bg-white/[0.03] px-2.5 py-1 text-[11px] text-gray-400">
                候选 {autoAgentCandidates.length} · 拒绝 {autoAgentRejected.length} · 回测 {autoAgentClosedLoop?.summary?.completed_count || 0}/{autoAgentClosedLoop?.summary?.scenario_count || 0}
              </span>
            </div>

            {autoAgentResult ? (
              <div className="mt-4 space-y-4">
                <div className="grid gap-4 xl:grid-cols-[1.25fr_0.75fr]">
                  <div className="rounded-2xl border border-purple-400/20 bg-purple-950/15 p-4">
                    <div className="text-[10px] uppercase tracking-[0.18em] text-purple-300/60">本轮结论</div>
                    <div className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-purple-50">{autoAgentDecision}</div>
                    {autoAgentClosedLoop?.candidate_strategy ? (
                      <div className="mt-4 space-y-2 text-sm leading-6 text-gray-300">
                        <div><span className="text-gray-500">候选策略：</span><span className="font-semibold text-white">{autoAgentClosedLoop.candidate_strategy.name}</span></div>
                        <div><span className="text-gray-500">策略逻辑：</span>{autoAgentClosedLoop.candidate_strategy.logic}</div>
                        <div><span className="text-gray-500">下一步：</span>{autoAgentClosedLoop.candidate_strategy.recommended_next_step}</div>
                      </div>
                    ) : (
                      <div className="mt-4 rounded-xl border border-white/[0.08] bg-black/20 p-3 text-sm leading-6 text-gray-400">
                        无通过候选，未进入回测矩阵。这是风控结果，不是错误；系统不会为了让页面“有结果”而编造交易机会。
                      </div>
                    )}
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                    <div className="rounded-xl border border-white/[0.08] bg-black/20 p-3">
                      <div className="text-[11px] text-gray-500">回测 / 闭环状态</div>
                      <div className="mt-1 text-sm font-semibold text-gray-100">{autoAgentBacktestLabel}</div>
                    </div>
                    <div className="rounded-xl border border-white/[0.08] bg-black/20 p-3">
                      <div className="text-[11px] text-gray-500">执行边界</div>
                      <div className="mt-1 text-sm font-semibold text-red-300">paper only · 实盘需人工审批</div>
                    </div>
                    <div className="rounded-xl border border-white/[0.08] bg-black/20 p-3">
                      <div className="text-[11px] text-gray-500">下一步操作</div>
                      <div className="mt-1 text-sm text-gray-300">{autoAgentClosedLoop?.candidate_strategy ? '复核候选策略后进入模拟盘观察' : '等待更高质量行情结构或调整市场池后重跑'}</div>
                    </div>
                  </div>
                </div>

                {autoAgentRejected.length > 0 && (
                  <div className="rounded-2xl border border-white/[0.08] bg-black/20 p-3 text-xs">
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <div className="font-semibold text-gray-100">候选拒绝原因</div>
                      <div className="text-[11px] text-gray-600">Top {Math.min(autoAgentRejected.length, 8)} / {autoAgentRejected.length}</div>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="min-w-full text-left text-[11px]">
                        <thead className="text-gray-600">
                          <tr className="border-b border-white/[0.06]">
                            <th className="py-2 pr-3 font-medium">Symbol</th>
                            <th className="py-2 pr-3 font-medium">机会分</th>
                            <th className="py-2 pr-3 font-medium">ADX</th>
                            <th className="py-2 pr-3 font-medium">EMA gap</th>
                            <th className="py-2 pr-3 font-medium">拒绝原因</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-white/[0.05]">
                          {autoAgentRejected.slice(0, 8).map((item: any) => (
                            <tr key={item.symbol} className="text-gray-400">
                              <td className="py-2 pr-3 font-semibold text-gray-100">{item.symbol}</td>
                              <td className="py-2 pr-3 font-mono">{fmtNumber(item.opportunity_score, 1)} / {fmtNumber(autoAgentMarketScan.threshold, 0)}</td>
                              <td className="py-2 pr-3 font-mono">{fmtNumber(item.inputs?.adx, 1)}</td>
                              <td className="py-2 pr-3 font-mono">{fmtNumber(item.inputs?.ema_gap_bps, 1)}bps</td>
                              <td className="py-2 pr-3">{(item.reject_reasons || []).join('；') || '未给出拒绝原因'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                <div className="grid gap-4 xl:grid-cols-2">
                  <div className="rounded-2xl border border-white/[0.08] bg-black/20 p-3 text-xs">
                    <div className="mb-2 font-semibold text-gray-100">Hermes 研究摘要</div>
                    {autoAgentHermesSummary ? (
                      <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-xl border border-white/[0.06] bg-black/25 p-3 text-[11px] leading-5 text-gray-400">{autoAgentHermesSummary.slice(0, 2500)}</pre>
                    ) : (
                      <div className="rounded-xl border border-white/[0.06] bg-black/25 p-3 text-gray-500">Hermes 未调用或暂无 stdout；请查看顶部 Hermes 状态确认是否已启用服务器 Bridge。</div>
                    )}
                  </div>
                  <div className="rounded-2xl border border-white/[0.08] bg-black/20 p-3 text-xs">
                    <div className="mb-2 font-semibold text-gray-100">回测 / 晋级门槛</div>
                    <div className="space-y-2 text-gray-400">
                      <div className="rounded-xl border border-white/[0.06] bg-black/25 p-3">状态：<span className="text-gray-100">{autoAgentBacktestLabel}</span></div>
                      <div className="rounded-xl border border-white/[0.06] bg-black/25 p-3">完成：{autoAgentClosedLoop?.summary?.completed_count || 0} / {autoAgentClosedLoop?.summary?.scenario_count || 0}</div>
                      <div className="rounded-xl border border-white/[0.06] bg-black/25 p-3">晋级：正收益、盈亏比 ≥ 1.05、最大回撤 ≤ 8%、非零交易，且必须人工复核。</div>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-4 rounded-2xl border border-dashed border-white/[0.08] bg-black/20 p-8 text-center text-sm text-gray-500">
                暂无运行结果。点击“立即开始研发”后，这里会先展示本轮结论，再展开拒绝原因、Hermes 摘要和回测状态。
              </div>
            )}

            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <div className="rounded-xl border border-white/[0.08] bg-black/20 p-3 text-xs text-gray-400">
                <div className="font-semibold text-gray-200">当前执行模式</div>
                <div className="mt-1">paper/simulation only；不允许自动升级实盘。</div>
              </div>
              <div className="rounded-xl border border-white/[0.08] bg-black/20 p-3 text-xs text-gray-400">
                <div className="font-semibold text-gray-200">下一步数据输入</div>
                <div className="mt-1">后端采集 A 股日线快照与本地实时行情，Market Agent 才会生成候选。</div>
              </div>
              <div className="rounded-xl border border-white/[0.08] bg-black/20 p-3 text-xs text-gray-400">
                <div className="font-semibold text-gray-200">实盘边界</div>
                <div className="mt-1">任何 live 订单都必须经过 /live-real 账户绑定、预检和人工确认。</div>
              </div>
            </div>

            {autoAgentResult && (
              <details className="mt-4 rounded-xl border border-white/[0.08] bg-black/20 p-3 text-xs text-gray-400">
                <summary className="cursor-pointer select-none font-semibold text-gray-300">原始结果（调试用）</summary>
                <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-white/[0.06] bg-black/30 p-3 text-[11px] leading-5 text-gray-500">
                  {JSON.stringify(autoAgentResult, null, 2)}
                </pre>
              </details>
            )}
          </div>
        </div>
  );
}
