import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  History,
  Landmark,
  ListChecks,
  Lock,
  RefreshCw,
  ShieldCheck,
  X,
  XCircle,
} from 'lucide-react';
import clsx from 'clsx';
import {
  getLivePromotionCandidates,
  getLiveTradingStatus,
  getStoredAuthProfile,
  listLiveEvents,
  requestLiveDeployment,
  runLivePreflight,
} from '../api/client';
import { OperatorPageHeader, OperatorStatePanel } from '../components/OperatorShell';
import type {
  LiveAuditEvent,
  LiveDeploymentResult,
  LivePreflightResult,
  LivePromotionCandidate,
  LiveTradingStatus,
} from '../types';
import { marketAdverseToneClass, marketToneClass, thresholdToneClass } from '../utils/marketColors';

/** 审计事件轮询：每 30 秒刷新一次，页面隐藏时跳过。 */
const EVENTS_POLL_MS = 30_000;

const panel = 'rounded-xl border border-crypto-border bg-crypto-card';
const MISSING = '—';

const ratioText = (value: number | null | undefined) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? MISSING
    : `${(Number(value) * 100).toFixed(2)}%`;

const numberText = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? MISSING
    : Number(value).toFixed(digits);

const moneyText = (value: number | null | undefined) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? MISSING
    : `¥${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`;

const metricNumber = (metrics: Record<string, number | null>, code: string): number | null => {
  const value = metrics[code];
  return value === null || value === undefined || !Number.isFinite(value) ? null : Number(value);
};

const RISK_LIMITS: Array<{ key: string; label: string; format: (value: number | null) => string }> = [
  { key: 'max_single_order_value', label: '单笔上限', format: moneyText },
  { key: 'max_position_weight', label: '单票仓位上限', format: ratioText },
  { key: 'max_daily_loss_ratio', label: '日内亏损上限', format: ratioText },
];

const candidateKindLabel: Record<LivePromotionCandidate['kind'], string> = {
  backtest_run: '完整回测',
  paper_instance: 'Paper实例',
};

const eventTypeLabels: Record<string, string> = {
  preflight: '预检',
  enable_requested: '部署请求',
  deployment_blocked: '部署拦截',
};

const eventStatusTone = (status: string) => {
  if (status === 'deployed' || status === 'passed' || status === 'accepted') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300';
  if (status === 'rejected' || status === 'failed') return 'border-red-500/30 bg-red-500/10 text-red-300';
  if (status === 'blocked' || status === 'warning') return 'border-amber-500/30 bg-amber-500/10 text-amber-300';
  if (status === 'pending_broker_binding') return 'border-blue-500/30 bg-blue-500/10 text-blue-300';
  return 'border-white/10 bg-white/5 text-slate-300';
};

const eventStatusLabels: Record<string, string> = {
  deployed: '已部署',
  rejected: '已拒绝',
  blocked: '已拦截',
  passed: '通过',
  failed: '未通过',
  warning: '警告',
  pending_broker_binding: '待券商绑定',
  recorded: '已留痕',
};

const formatEventTime = (value: string) => {
  if (!value) return MISSING;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false });
};

const eventDetailSummary = (detail: Record<string, unknown>) => {
  const entries = Object.entries(detail ?? {}).filter(([, value]) => value !== null && value !== undefined && value !== '');
  if (!entries.length) return '—';
  return entries
    .slice(0, 4)
    .map(([key, value]) => `${key}=${typeof value === 'object' ? JSON.stringify(value) : String(value)}`)
    .join(' · ')
    .concat(entries.length > 4 ? ` …+${entries.length - 4}` : '');
};

const gateInfo = (candidate: LivePromotionCandidate) => {
  const passed = Number((candidate.detail as Record<string, unknown> | null)?.passed_gate_count ?? NaN);
  const total = Number((candidate.detail as Record<string, unknown> | null)?.gate_total ?? NaN);
  if (!Number.isFinite(passed) || !Number.isFinite(total) || total <= 0) return null;
  return { passed, total, complete: passed >= total };
};

const PreflightDialog = ({
  candidate,
  preflight,
  busy,
  error,
  confirmed,
  deploying,
  deployResult,
  isAdmin,
  onToggleConfirm,
  onConfirmDeploy,
  onClose,
}: {
  candidate: LivePromotionCandidate;
  preflight: LivePreflightResult | null;
  busy: boolean;
  error: string;
  confirmed: boolean;
  deploying: boolean;
  deployResult: LiveDeploymentResult | null;
  isAdmin: boolean;
  onToggleConfirm: (checked: boolean) => void;
  onConfirmDeploy: () => void;
  onClose: () => void;
}) => {
  const deployable = preflight?.deployable === true && Boolean(preflight.confirm_token);
  const resultStatus = deployResult ? (String(deployResult.status) as LiveDeploymentResult['status'] | 'pending_broker_binding') : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onMouseDown={onClose}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="live-preflight-title"
        className="flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-crypto-border bg-crypto-card shadow-2xl"
        onMouseDown={(event) => event.stopPropagation()}
        data-testid="live-preflight-dialog"
      >
        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-crypto-border px-5 py-4">
          <div className="min-w-0">
            <h2 id="live-preflight-title" className="text-base font-bold text-white">
              实盘预检与部署
            </h2>
            <p className="mt-1 truncate text-xs text-slate-500">
              <span className="mr-2 rounded border border-blue-500/30 bg-blue-500/10 px-1.5 py-0.5 text-[10px] text-blue-300">
                {candidateKindLabel[candidate.kind]}
              </span>
              {candidate.name}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 hover:bg-white/5 hover:text-white"
            aria-label="关闭预检对话框"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
          {busy ? (
            <div className="flex flex-col items-center justify-center py-12 text-sm text-slate-500" data-testid="live-preflight-loading">
              <RefreshCw className="mb-3 h-5 w-5 animate-spin text-blue-400" />
              正在执行实盘预检…
            </div>
          ) : null}

          {!busy && error ? (
            <div className="rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">
              <strong>预检失败：</strong>
              {error}
            </div>
          ) : null}

          {!busy && !error && preflight ? (
            <>
              <ul className="space-y-2">
                {preflight.checks.map((check) => {
                  const passed = check.status === 'passed';
                  const failed = check.status === 'failed';
                  return (
                    <li
                      key={check.check_code}
                      className={clsx(
                        'flex items-start gap-3 rounded-lg border px-3 py-2.5 text-xs',
                        passed
                          ? 'border-emerald-500/20 bg-emerald-500/[0.05]'
                          : failed
                            ? 'border-red-500/20 bg-red-500/[0.05]'
                            : 'border-amber-500/20 bg-amber-500/[0.05]',
                      )}
                      data-testid={`live-check-${check.check_code}`}
                    >
                      {passed ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                      ) : failed ? (
                        <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
                      ) : (
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
                      )}
                      <div className="min-w-0">
                        <div className={clsx('font-semibold', passed ? 'text-emerald-200' : failed ? 'text-red-200' : 'text-amber-200')}>
                          {check.title}
                        </div>
                        {check.reason ? <p className="mt-1 leading-5 text-slate-500">{check.reason}</p> : null}
                      </div>
                    </li>
                  );
                })}
                {!preflight.checks.length ? (
                  <li className="rounded-lg border border-dashed border-crypto-border px-3 py-6 text-center text-xs text-slate-600">
                    预检未返回任何检查项
                  </li>
                ) : null}
              </ul>

              {!deployable ? (
                <div className="rounded-lg border border-amber-500/25 bg-amber-500/10 p-3 text-xs leading-5 text-amber-200">
                  预检未全部通过，当前候选不可部署到实盘；请先补齐晋级证据或通道配置。
                </div>
              ) : (
                <div className="rounded-lg border border-crypto-border bg-crypto-bg p-3">
                  <div className="text-[10px] text-slate-600">确认令牌（confirm_token）</div>
                  <code className="mt-1 block break-all font-mono text-xs text-blue-200">{preflight.confirm_token}</code>
                </div>
              )}
            </>
          ) : null}

          {!busy && !error && preflight && deployable && !deployResult ? (
            <div className="space-y-3">
              <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] p-3 text-xs leading-5 text-amber-200/90">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => onToggleConfirm(event.target.checked)}
                  disabled={!isAdmin || deploying}
                  className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-red-500"
                  data-testid="live-deploy-ack"
                />
                我已核对预检结果，理解实盘风险
              </label>
              <button
                type="button"
                onClick={onConfirmDeploy}
                disabled={!confirmed || !isAdmin || deploying}
                title={!isAdmin ? '访客只读' : undefined}
                className="h-11 w-full rounded-lg bg-red-600 text-sm font-bold text-white transition-colors hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-40"
                data-testid="live-deploy-confirm"
              >
                {deploying ? '正在提交部署请求…' : '确认部署实盘'}
              </button>
              {!isAdmin ? <p className="text-center text-[10px] text-slate-600">访客只读：实盘部署仅管理员可执行</p> : null}
            </div>
          ) : null}

          {deployResult ? (
            <div
              role="status"
              data-testid="live-deploy-result"
              className={clsx(
                'rounded-lg border p-4 text-sm',
                resultStatus === 'rejected'
                  ? 'border-red-500/30 bg-red-500/10 text-red-200'
                  : resultStatus === 'blocked'
                    ? 'border-amber-500/30 bg-amber-500/10 text-amber-200'
                    : resultStatus === 'pending_broker_binding'
                      ? 'border-blue-500/30 bg-blue-500/10 text-blue-200'
                      : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200',
              )}
            >
              <div className="font-semibold">
                {resultStatus === 'rejected'
                  ? '部署已拒绝'
                  : resultStatus === 'blocked'
                    ? '部署被风控拦截'
                    : resultStatus === 'pending_broker_binding'
                      ? '已受理，待券商通道绑定'
                      : '实盘部署已受理'}
              </div>
              {deployResult.reason ? <p className="mt-2 text-xs leading-5 opacity-90">{deployResult.reason}</p> : null}
              {deployResult.event_id ? (
                <p className="mt-2 font-mono text-[10px] opacity-80">事件 {deployResult.event_id}</p>
              ) : null}
            </div>
          ) : null}
        </div>

        <div className="flex shrink-0 items-center justify-between gap-3 border-t border-crypto-border px-5 py-3">
          <p className="text-[10px] text-slate-600">部署请求全量留痕，可在审计事件中复核。</p>
          <button
            type="button"
            onClick={onClose}
            className="h-9 rounded-lg border border-crypto-border bg-crypto-bg px-4 text-xs font-semibold text-slate-300 hover:text-white"
          >
            关闭
          </button>
        </div>
      </section>
    </div>
  );
};

export function LiveTrading() {
  const [isAdmin] = useState(() => getStoredAuthProfile()?.role === 'admin');
  const [status, setStatus] = useState<LiveTradingStatus | null>(null);
  const [statusLoaded, setStatusLoaded] = useState(false);
  const [statusBusy, setStatusBusy] = useState(false);
  const [statusError, setStatusError] = useState('');
  const [candidates, setCandidates] = useState<LivePromotionCandidate[]>([]);
  const [candidatesLoaded, setCandidatesLoaded] = useState(false);
  const [candidatesError, setCandidatesError] = useState('');
  const [events, setEvents] = useState<LiveAuditEvent[]>([]);
  const [eventsBusy, setEventsBusy] = useState(false);
  const [eventsLoaded, setEventsLoaded] = useState(false);
  const [eventsError, setEventsError] = useState('');

  const [dialogCandidate, setDialogCandidate] = useState<LivePromotionCandidate | null>(null);
  const [preflight, setPreflight] = useState<LivePreflightResult | null>(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [preflightError, setPreflightError] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState<LiveDeploymentResult | null>(null);

  const loadStatusAndCandidates = useCallback(async (opts?: { silent?: boolean }) => {
    const silent = opts?.silent === true;
    if (!silent) {
      setStatusBusy(true);
      setStatusError('');
      setCandidatesError('');
    }
    try {
      const [nextStatus, nextCandidates] = await Promise.all([
        getLiveTradingStatus(),
        getLivePromotionCandidates(),
      ]);
      setStatus(nextStatus);
      setCandidates(nextCandidates.candidates ?? []);
    } catch (reason) {
      if (!silent) {
        setStatusError(reason instanceof Error ? reason.message : '实盘状态加载失败');
      }
    } finally {
      if (!silent) setStatusBusy(false);
      setStatusLoaded(true);
      setCandidatesLoaded(true);
    }
  }, []);

  const loadEvents = useCallback(async (opts?: { silent?: boolean }) => {
    const silent = opts?.silent === true;
    if (!silent) {
      setEventsBusy(true);
      setEventsError('');
    }
    try {
      const next = await listLiveEvents(50);
      setEvents(next.events ?? []);
    } catch (reason) {
      if (!silent) setEventsError(reason instanceof Error ? reason.message : '审计事件加载失败');
    } finally {
      if (!silent) setEventsBusy(false);
      setEventsLoaded(true);
    }
  }, []);

  useEffect(() => {
    void loadStatusAndCandidates();
    void loadEvents();
  }, [loadStatusAndCandidates, loadEvents]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      void loadEvents({ silent: true });
    }, EVENTS_POLL_MS);
    return () => window.clearInterval(timer);
  }, [loadEvents]);

  const openPreflight = async (candidate: LivePromotionCandidate) => {
    if (!isAdmin) return;
    setDialogCandidate(candidate);
    setPreflight(null);
    setPreflightError('');
    setConfirmed(false);
    setDeployResult(null);
    setPreflightBusy(true);
    try {
      const result = await runLivePreflight({
        candidate_kind: candidate.kind,
        candidate_id: candidate.id,
      });
      setPreflight(result);
    } catch (reason) {
      setPreflightError(reason instanceof Error ? reason.message : '实盘预检请求失败');
    } finally {
      setPreflightBusy(false);
    }
  };

  const confirmDeploy = async () => {
    if (!dialogCandidate || !preflight?.confirm_token || !confirmed) return;
    setDeploying(true);
    try {
      const result = await requestLiveDeployment({
        candidate_kind: dialogCandidate.kind,
        candidate_id: dialogCandidate.id,
        confirm_token: preflight.confirm_token,
        confirmed: true,
      });
      setDeployResult(result);
      void loadEvents({ silent: true });
      void loadStatusAndCandidates({ silent: true });
    } catch (reason) {
      setPreflightError(reason instanceof Error ? reason.message : '部署请求失败');
    } finally {
      setDeploying(false);
    }
  };

  const closeDialog = () => {
    setDialogCandidate(null);
    setPreflight(null);
    setPreflightError('');
    setConfirmed(false);
    setDeployResult(null);
    setPreflightBusy(false);
    setDeploying(false);
  };

  const tradingEnabled = status?.trading_enabled === true;

  return (
    <div
      className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8"
      data-testid="live-trading-workbench"
      data-operator-page="live"
    >
      <OperatorPageHeader
        icon={ShieldCheck}
        title="实盘工作台"
        subtitle="A 股实盘晋级流水线：券商通道状态 → 晋级候选预检 → 双人留痕的部署确认 → 审计事件复核。"
        actions={
          <button
            type="button"
            onClick={() => {
              void loadStatusAndCandidates();
              void loadEvents();
            }}
            className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-400"
          >
            <RefreshCw className={clsx('h-4 w-4', (statusBusy || eventsBusy) && 'animate-spin')} />
            刷新全部
          </button>
        }
      />

      <div
        className={clsx(
          'mb-5 rounded-xl border border-amber-500/25 bg-amber-500/[0.07] p-4 text-xs leading-5 text-amber-200/90',
        )}
        role="note"
        data-testid="live-boundary-note"
      >
        <div className="flex items-start gap-2.5">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
          <div className="min-w-0">
            <strong className="font-semibold text-amber-200">实盘边界：</strong>
            {status?.boundary_note || '正在读取实盘交易边界说明…'}
          </div>
        </div>
        {!tradingEnabled && statusLoaded ? (
          <div
            className="mt-3 flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs font-semibold text-amber-200"
            role="status"
            data-testid="live-locked-notice"
          >
            <Lock className="h-3.5 w-3.5 shrink-0" />
            实盘通道未开启 — 所有请求仅预检与留痕
          </div>
        ) : null}
      </div>

      {statusError ? (
        <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-4 text-sm text-red-200">
          <strong>状态加载失败：</strong>
          {statusError}；缺失数据未显示为 0。
        </div>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        {/* 券商通道 */}
        <section className={panel} data-testid="live-adapters-panel" aria-label="券商通道">
          <header className="flex items-center gap-2 border-b border-crypto-border px-4 py-3">
            <Landmark className="h-4 w-4 text-blue-400" />
            <h2 className="text-sm font-semibold text-white">券商通道</h2>
            {status ? (
              <span
                className={clsx(
                  'ml-auto rounded border px-2 py-0.5 text-[10px] font-semibold',
                  tradingEnabled
                    ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                    : 'border-amber-500/30 bg-amber-500/10 text-amber-300',
                )}
              >
                {tradingEnabled ? '通道开启' : '通道关闭'}
              </span>
            ) : null}
          </header>
          {!statusLoaded && !statusError ? (
            <OperatorStatePanel kind="loading" title="正在读取通道状态…" />
          ) : null}
          {statusLoaded ? (
            <div className="space-y-2 p-4">
              {(status?.adapters ?? []).map((adapter) => {
                const state = adapter.configured
                  ? { label: '已配置', cls: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' }
                  : adapter.available
                    ? { label: '已安装未配置', cls: 'border-amber-500/30 bg-amber-500/10 text-amber-300' }
                    : { label: '未安装', cls: 'border-white/10 bg-white/5 text-slate-400' };
                return (
                  <div key={adapter.key} className="rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2.5">
                    <div className="flex items-center justify-between gap-3">
                      <span className="min-w-0 truncate text-sm font-medium text-slate-200">{adapter.name}</span>
                      <span className={clsx('shrink-0 rounded border px-2 py-0.5 text-[10px] font-semibold', state.cls)}>
                        {state.label}
                      </span>
                    </div>
                    {adapter.note ? <p className="mt-1.5 text-[11px] leading-4 text-slate-500">{adapter.note}</p> : null}
                  </div>
                );
              })}
              {!status?.adapters?.length ? (
                <div className="rounded-lg border border-dashed border-crypto-border px-3 py-8 text-center text-xs text-slate-600">
                  暂无已注册的券商适配器
                </div>
              ) : null}
              <div className="rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2.5">
                <div className="text-[10px] font-semibold tracking-wider text-slate-600">风控限额</div>
                <div className="mt-2 grid grid-cols-3 gap-2">
                  {RISK_LIMITS.map(({ key, label, format }) => (
                    <div key={key} className="min-w-0">
                      <div className="truncate text-[10px] text-slate-500">{label}</div>
                      <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums text-slate-200">
                        {format(status?.risk_limits?.[key] ?? null)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </section>

        {/* 晋级候选 */}
        <section className={panel} data-testid="live-candidates-panel" aria-label="晋级候选">
          <header className="flex items-center gap-2 border-b border-crypto-border px-4 py-3">
            <ListChecks className="h-4 w-4 text-blue-400" />
            <h2 className="text-sm font-semibold text-white">晋级候选</h2>
            <span className="ml-auto rounded border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] tabular-nums text-slate-400">
              {candidates.length}
            </span>
          </header>
          {!candidatesLoaded && !candidatesError ? (
            <OperatorStatePanel kind="loading" title="正在读取晋级候选…" />
          ) : null}
          {candidatesError ? (
            <div className="p-4 text-sm text-red-300">候选加载失败：{candidatesError}</div>
          ) : null}
          {candidatesLoaded && !candidatesError ? (
            <div className="space-y-2 p-4">
              {candidates.map((candidate) => {
                const gate = gateInfo(candidate);
                const detail = (candidate.detail ?? {}) as Record<string, unknown>;
                const instanceStatus = candidate.kind === 'paper_instance' ? String(detail.status ?? '') : '';
                const strategyReturn = metricNumber(candidate.metrics, 'strategy_return');
                const sharpe = metricNumber(candidate.metrics, 'sharpe');
                const drawdown = metricNumber(candidate.metrics, 'maximum_drawdown');
                const winRate = metricNumber(candidate.metrics, 'win_rate');
                return (
                  <article
                    key={`${candidate.kind}-${candidate.id}`}
                    className="rounded-lg border border-crypto-border bg-crypto-bg p-3"
                    data-testid="live-candidate-row"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className={clsx(
                              'rounded border px-1.5 py-0.5 text-[10px] font-semibold',
                              candidate.kind === 'backtest_run'
                                ? 'border-blue-500/30 bg-blue-500/10 text-blue-300'
                                : 'border-violet-500/30 bg-violet-500/10 text-violet-300',
                            )}
                          >
                            {candidateKindLabel[candidate.kind]}
                          </span>
                          <h3 className="min-w-0 truncate text-sm font-semibold text-slate-100">{candidate.name}</h3>
                          {gate ? (
                            <span
                              className={clsx(
                                'rounded border px-1.5 py-0.5 font-mono text-[10px] tabular-nums',
                                gate.complete
                                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                                  : 'border-amber-500/30 bg-amber-500/10 text-amber-300',
                              )}
                              title={`研究晋级门控 ${gate.passed}/${gate.total}`}
                            >
                              门控 {gate.passed}/{gate.total}
                            </span>
                          ) : null}
                          {instanceStatus ? (
                            <span
                              className={clsx(
                                'rounded border px-1.5 py-0.5 text-[10px]',
                                instanceStatus === 'running'
                                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                                  : 'border-amber-500/30 bg-amber-500/10 text-amber-300',
                              )}
                            >
                              {instanceStatus === 'running' ? '运行中' : instanceStatus === 'paused' ? '已暂停' : instanceStatus}
                            </span>
                          ) : null}
                        </div>
                        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs tabular-nums text-slate-500">
                          <span>
                            收益{' '}
                            <strong className={clsx('font-semibold', marketToneClass(strategyReturn, 'text-slate-400'))}>
                              {ratioText(strategyReturn)}
                            </strong>
                          </span>
                          <span>
                            夏普{' '}
                            <strong className={clsx('font-semibold', thresholdToneClass(sharpe, 1, 'text-slate-400'))}>
                              {numberText(sharpe)}
                            </strong>
                          </span>
                          <span>
                            回撤{' '}
                            <strong className={clsx('font-semibold', marketAdverseToneClass(drawdown, 'text-slate-400'))}>
                              {ratioText(drawdown)}
                            </strong>
                          </span>
                          <span>
                            胜率{' '}
                            <strong className="font-semibold text-slate-300">{ratioText(winRate)}</strong>
                          </span>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => void openPreflight(candidate)}
                        disabled={!isAdmin || preflightBusy}
                        title={!isAdmin ? '访客只读' : undefined}
                        className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-blue-500/35 bg-blue-500/10 px-3 text-xs font-semibold text-blue-300 transition-colors hover:bg-blue-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                        data-testid="live-preflight-button"
                      >
                        <ShieldCheck className="h-3.5 w-3.5" />
                        预检
                      </button>
                    </div>
                  </article>
                );
              })}
              {!candidates.length ? (
                <div className="rounded-lg border border-dashed border-crypto-border px-3 py-10 text-center text-xs leading-5 text-slate-600">
                  暂无晋级候选
                  <p className="mt-1 text-slate-700">完整回测通过 11 项晋级门控，或 Paper 实例进入运行/暂停状态后，才会出现在这里。</p>
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      </div>

      {/* 审计事件 */}
      <section className={clsx(panel, 'mt-5')} data-testid="live-events-panel" aria-label="审计事件">
        <header className="flex items-center gap-2 border-b border-crypto-border px-4 py-3">
          <History className="h-4 w-4 text-blue-400" />
          <h2 className="text-sm font-semibold text-white">审计事件</h2>
          <span className="text-[10px] text-slate-600">每 30 秒自动刷新</span>
          <button
            type="button"
            onClick={() => void loadEvents()}
            disabled={eventsBusy}
            className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-xs text-slate-400 hover:text-white disabled:opacity-40"
          >
            <RefreshCw className={clsx('h-3.5 w-3.5', eventsBusy && 'animate-spin')} />
            刷新
          </button>
        </header>
        {eventsError ? <div className="p-4 text-sm text-red-300">审计事件加载失败：{eventsError}</div> : null}
        {!eventsLoaded && !eventsError ? <OperatorStatePanel kind="loading" title="正在读取审计事件…" /> : null}
        {eventsLoaded && !eventsError ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-xs">
              <thead>
                <tr className="border-b border-crypto-border text-left text-[10px] tracking-wider text-slate-600">
                  <th className="px-4 py-2.5 font-medium">时间</th>
                  <th className="px-4 py-2.5 font-medium">类型</th>
                  <th className="px-4 py-2.5 font-medium">候选</th>
                  <th className="px-4 py-2.5 font-medium">状态</th>
                  <th className="px-4 py-2.5 font-medium">详情摘要</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id} className="border-b border-white/[0.04]">
                    <td className="whitespace-nowrap px-4 py-2.5 font-mono tabular-nums text-slate-400">
                      {formatEventTime(event.created_at)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-slate-300">
                      {eventTypeLabels[event.event_type] ?? event.event_type}
                    </td>
                    <td className="max-w-[240px] truncate px-4 py-2.5 text-slate-300" title={`${candidateKindLabel[event.candidate_kind as LivePromotionCandidate['kind']] ?? event.candidate_kind} · ${event.candidate_id}`}>
                      <span className="mr-1.5 rounded border border-white/10 bg-white/5 px-1 py-0.5 text-[10px] text-slate-400">
                        {candidateKindLabel[event.candidate_kind as LivePromotionCandidate['kind']] ?? event.candidate_kind}
                      </span>
                      {event.candidate_id}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5">
                      <span className={clsx('rounded border px-2 py-0.5 text-[10px] font-semibold', eventStatusTone(event.status))}>
                        {eventStatusLabels[event.status] ?? event.status}
                      </span>
                    </td>
                    <td
                      className="max-w-[360px] truncate px-4 py-2.5 font-mono text-[11px] text-slate-500"
                      title={JSON.stringify(event.detail ?? {})}
                    >
                      {eventDetailSummary(event.detail ?? {})}
                    </td>
                  </tr>
                ))}
                {!events.length ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-10 text-center text-xs text-slate-600">
                      暂无实盘审计事件；每次预检与部署请求都会在此留痕。
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      {dialogCandidate ? (
        <PreflightDialog
          candidate={dialogCandidate}
          preflight={preflight}
          busy={preflightBusy}
          error={preflightError}
          confirmed={confirmed}
          deploying={deploying}
          deployResult={deployResult}
          isAdmin={isAdmin}
          onToggleConfirm={setConfirmed}
          onConfirmDeploy={() => void confirmDeploy()}
          onClose={closeDialog}
        />
      ) : null}
    </div>
  );
}

export default LiveTrading;
