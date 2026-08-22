import { useEffect, useMemo, useState } from 'react';
import {
  BadgeCheck,
  Check,
  ChevronRight,
  CircleUserRound,
  Copy,
  FileSearch,
  FlaskConical,
  Lightbulb,
  RefreshCw,
  Search,
  Sparkles,
  XCircle,
  type LucideIcon,
} from 'lucide-react';
import clsx from 'clsx';
import CryptoSelect from '../../components/CryptoSelect';
import ThemeDialog from '../../components/ThemeDialog';
import { marketApi, researchWorkbenchApi } from '../../api/client';

type StageId = 'proposal' | 'research' | 'results' | 'paper';
type StageTone = 'idle' | 'active' | 'passed' | 'blocked' | 'human' | 'failed';
type Row = Record<string, any>;

type PendingAction = {
  title: string;
  description: string;
  tone?: 'default' | 'warning';
  execute: (reason: string, idempotencyKey: string) => Promise<unknown>;
};

const STAGES: Array<{ id: StageId; label: string; empty: string; icon: LucideIcon }> = [
  { id: 'proposal', label: '提议方向', empty: '写下要研究的市场、策略方向或假设；提交后 HT 会自动开始研究。', icon: Lightbulb },
  { id: 'research', label: 'HT 研究回测', empty: '提交提议后，HT 会自动生成规格、校验数据与代码并完成回测，不需要逐阶段操作。', icon: FlaskConical },
  { id: 'results', label: '回测结果', empty: 'HT 完成研究后，这里会展示真实回测指标、成本假设、验证结论和未通过原因。', icon: BadgeCheck },
  { id: 'paper', label: '模拟盘决策', empty: '只有验证通过并记录证据的结果才能申请模拟盘；申请不会直接启动模拟盘。', icon: CircleUserRound },
];

const DEFAULT_MANDATE_SYMBOLS = ['BTC/USDT:USDT', 'ETH/USDT:USDT'];
const REVIEW_ACTIONS = ['request_paper_review', 'request_pause_review', 'retire_candidate_review'] as const;

function rows(value: unknown): Row[] {
  return Array.isArray(value) ? value.filter((item): item is Row => Boolean(item) && typeof item === 'object') : [];
}

function field(row: Row | null | undefined, ...keys: string[]): any {
  for (const key of keys) {
    if (row && row[key] !== undefined && row[key] !== null) return row[key];
  }
  return undefined;
}

function list(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function short(value: unknown): string {
  const text = String(value ?? '').trim();
  return text || '--';
}

function formatNumber(value: unknown, digits = 2): string {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : '--';
}

function formatPct(value: unknown): string {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)}%` : '--';
}

function formatTime(value: unknown): string {
  if (!value) return '--';
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false });
}

function idempotencyKey(prefix: string): string {
  const suffix = typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${suffix}`.slice(0, 160);
}

function errorText(error: any): string {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') return String(detail.message || detail.code || '上游请求失败');
  return String(error?.message || '请求失败');
}

function statusLabel(status: unknown): string {
  const labels: Record<string, string> = {
    active: '已启用',
    created: '待启动',
    draft: '草案',
    queued: '排队中',
    planning: '生成方案',
    running: '研究回测中',
    validating: '验证中',
    completed: '研究完成',
    evidence_recorded: '验证通过',
    rejected: '未通过',
    failed: '研究失败',
    canceled: '已取消',
    pending_paper_approval: '待人工审批',
    paper_observing: '模拟盘观察中',
    paper_degraded: '需要复核',
    paper_review_required: '待人工复核',
  };
  const raw = String(status || '');
  return labels[raw] || short(raw);
}

function statusTone(status: unknown): string {
  const raw = String(status || '');
  if (['evidence_recorded', 'paper_observing', 'active', 'completed'].includes(raw)) return 'border-emerald-500/35 bg-emerald-500/10 text-emerald-200';
  if (['pending_paper_approval', 'paper_review_required'].includes(raw)) return 'border-orange-400/40 bg-orange-400/10 text-orange-200';
  if (['rejected', 'failed', 'canceled'].includes(raw)) return 'border-red-500/35 bg-red-500/10 text-red-200';
  if (['paper_degraded'].includes(raw)) return 'border-amber-400/40 bg-amber-400/10 text-amber-100';
  if (['queued', 'planning', 'running', 'validating'].includes(raw)) return 'border-cyan-400/40 bg-cyan-400/10 text-cyan-100';
  return 'border-crypto-border bg-crypto-bg text-gray-400';
}

function stageClass(tone: StageTone, selected: boolean): string {
  const styles: Record<StageTone, string> = {
    idle: 'border-crypto-border bg-crypto-bg text-gray-500',
    active: 'border-cyan-400/65 bg-cyan-500/10 text-cyan-100',
    passed: 'border-emerald-500/65 bg-emerald-500/10 text-emerald-100',
    blocked: 'border-amber-400/65 bg-amber-400/10 text-amber-100',
    human: 'border-orange-400/70 bg-orange-400/10 text-orange-100',
    failed: 'border-red-500/65 bg-red-500/10 text-red-100',
  };
  return clsx(styles[tone], selected && 'ring-1 ring-blue-400/80 shadow-[0_0_0_3px_rgba(59,130,246,0.10)]');
}

function StageBadge({ tone, count }: { tone: StageTone; count: number }) {
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-semibold tabular-nums">
      {tone === 'passed' && <Check size={12} className="text-emerald-300" aria-label="已通过" />}
      {tone === 'failed' && <XCircle size={12} className="text-red-300" aria-label="已拒绝" />}
      {tone === 'active' && <span className="h-2 w-2 rounded-full bg-cyan-300 animate-pulse" aria-label="进行中" />}
      <span>{count}</span>
    </span>
  );
}

function metricValueText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '--';
  if (typeof value === 'string' || typeof value === 'number') return short(value);
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (Array.isArray(value)) {
    const values = value.map(metricValueText).filter((item) => item !== '--');
    return values.length ? values.join(' / ') : '--';
  }
  if (typeof value === 'object') {
    const record = value as Row;
    for (const key of ['label', 'summary', 'status', 'level', 'value', 'score']) {
      const candidate = record[key];
      if (typeof candidate === 'string' || typeof candidate === 'number' || typeof candidate === 'boolean') return metricValueText(candidate);
    }
  }
  return '已记录';
}

function Metric({ label, value, tone = 'text-gray-100' }: { label: string; value: unknown; tone?: string }) {
  const display = metricValueText(value);
  return (
    <div className="min-w-0 rounded-lg border border-crypto-border bg-slate-800/65 px-3 py-2.5 shadow-[0_8px_20px_rgba(0,0,0,0.22)] ring-1 ring-white/[0.025]">
      <div className="truncate text-[11px] text-gray-500">{label}</div>
      <div className={clsx('mt-1 truncate text-lg font-semibold tabular-nums', tone)} title={display}>{display}</div>
    </div>
  );
}

function EmptyStage({ children }: { children: string }) {
  return (
    <div className="flex min-h-[250px] items-center justify-center rounded-lg border border-dashed border-crypto-border bg-crypto-bg px-5 text-center text-xs leading-relaxed text-gray-500">
      {children}
    </div>
  );
}

function CopyValue({ label, value }: { label: string; value: unknown }) {
  const display = short(value);
  return (
    <div className="min-w-0">
      <div className="text-[10px] text-gray-600">{label}</div>
      <div className="flex min-w-0 items-center gap-1">
        <span className="min-w-0 flex-1 truncate text-xs text-gray-300" title={display}>{display}</span>
        {display !== '--' && (
          <button type="button" className="shrink-0 text-gray-500 hover:text-blue-300" aria-label={`复制${label}`} onClick={() => void navigator.clipboard?.writeText(display)}>
            <Copy size={12} />
          </button>
        )}
      </div>
    </div>
  );
}

function CandidateCard({ candidate, onRequestPaper, onView }: { candidate: Row; onRequestPaper: (candidate: Row) => void; onView: (candidate: Row) => void }) {
  const metrics = field(candidate, 'metrics') || {};
  const windows = field(candidate, 'windows') || {};
  const gates = field(candidate, 'gateResults', 'gate_results') || {};
  const references = field(candidate, 'backtestReferences', 'backtest_references', 'resultRefs', 'result_refs') || {};
  const gaps = list(field(candidate, 'dataGaps', 'data_gaps'));
  const rejectionReasons = list(field(candidate, 'rejectionReasons', 'rejection_reasons'));
  const status = String(field(candidate, 'status') || '');
  const isPassing = status === 'evidence_recorded' && Object.keys(gates).length > 0 && Object.values(gates).every(Boolean);
  const strategyName = short(field(candidate, 'strategyKey', 'strategy_key'));
  return (
    <article className="rounded-lg border border-crypto-border bg-crypto-bg p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-gray-100" title={strategyName}>{strategyName}</div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-gray-500">
            <span>BitPro #{short(field(candidate, 'bitproStrategyId', 'bitpro_strategy_id'))}</span>
            <span>版本 {short(field(candidate, 'variantId', 'variant_id'))}</span>
            <span>配置 {short(field(field(candidate, 'parameters'), 'configVersion', 'config_version', 'version'))}</span>
          </div>
        </div>
        <span className={clsx('shrink-0 rounded border px-2 py-0.5 text-[10px]', statusTone(status))}>{statusLabel(status)}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-3">
        <CopyValue label="数据窗口" value={field(windows, 'full', 'dataWindow', 'data_window')} />
        <CopyValue label="样本内 / 验证" value={`${short(field(windows, 'inSample', 'in_sample'))} / ${short(field(windows, 'validation'))}`} />
        <CopyValue label="锁定样本外" value={field(windows, 'lockedOutOfSample', 'locked_out_of_sample', 'outOfSample', 'out_of_sample')} />
        <CopyValue label="收益 / 回撤" value={`${formatPct(field(metrics, 'totalReturnPct', 'total_return_pct'))} / ${formatPct(field(metrics, 'maxDrawdownPct', 'max_drawdown_pct'))}`} />
        <CopyValue label="Sharpe / 交易" value={`${formatNumber(field(metrics, 'sharpe', 'sharpeRatio', 'sharpe_ratio'))} / ${formatNumber(field(metrics, 'totalTrades', 'total_trades'), 0)}`} />
        <CopyValue label="成本假设" value={field(metrics, 'costAssumptions', 'cost_assumptions', 'feesAndSlippage') || field(references, 'costAssumptions', 'cost_assumptions')} />
      </div>
      {(gaps.length > 0 || rejectionReasons.length > 0 || status === 'rejected' || status === 'failed') && (
        <div className="mt-3 space-y-1 rounded-md border border-amber-400/25 bg-amber-400/5 px-2 py-1.5 text-[11px] text-amber-100/85">
          {gaps.length > 0 && <div className="break-words">数据缺口：{gaps.join('；')}</div>}
          {rejectionReasons.length > 0 && <div className="break-words">未通过原因：{rejectionReasons.join('；')}</div>}
          {rejectionReasons.length === 0 && ['rejected', 'failed'].includes(status) && <div>当前摘要未返回具体未通过原因，请打开证据详情查看 HT 完整报告。</div>}
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => onView(candidate)} className="inline-flex h-7 items-center gap-1 rounded border border-crypto-border px-2 text-[11px] text-gray-300 hover:border-blue-400 hover:text-blue-200"><FileSearch size={12} />查看回测证据</button>
        {isPassing && <button type="button" onClick={() => onRequestPaper(candidate)} className="inline-flex h-7 items-center gap-1 rounded border border-orange-400/45 bg-orange-400/10 px-2 text-[11px] font-semibold text-orange-100 hover:bg-orange-400/20"><CircleUserRound size={12} />申请模拟盘</button>}
        <span className="ml-auto max-w-full truncate text-[10px] text-gray-600" title={short(field(references, 'backtestResultId', 'backtest_result_id', 'id'))}>回测引用 {short(field(references, 'backtestResultId', 'backtest_result_id', 'id'))}</span>
      </div>
    </article>
  );
}

export default function ResearchWorkbench() {
  const [summary, setSummary] = useState<Row | null>(null);
  const [candidates, setCandidates] = useState<Row[]>([]);
  const [candidateErrors, setCandidateErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState('');
  const [selectedStage, setSelectedStage] = useState<StageId>('proposal');
  const [detail, setDetail] = useState<Row | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [actionReason, setActionReason] = useState('');
  const [actionIdempotencyKey, setActionIdempotencyKey] = useState('');
  const [writeBusy, setWriteBusy] = useState(false);
  const [proposalOpen, setProposalOpen] = useState(false);
  const [mandateSymbols, setMandateSymbols] = useState<string[]>(DEFAULT_MANDATE_SYMBOLS);
  const [mandateSymbolOptions, setMandateSymbolOptions] = useState<string[]>(DEFAULT_MANDATE_SYMBOLS);
  const [mandateSymbolSearch, setMandateSymbolSearch] = useState('');
  const [customMandateSymbol, setCustomMandateSymbol] = useState('');
  const [mandateSymbolsLoading, setMandateSymbolsLoading] = useState(false);
  const [mandateSymbolsError, setMandateSymbolsError] = useState('');
  const [mandateTimeframe, setMandateTimeframe] = useState('4h');
  const [mandateCategory, setMandateCategory] = useState('cta');
  const [proposalDirection, setProposalDirection] = useState('');
  const [proposalFormError, setProposalFormError] = useState('');

  const refresh = async () => {
    setLoading(true);
    setStatus('');
    try {
      const [nextSummary, nextCandidates] = await Promise.all([
        researchWorkbenchApi.summary(),
        researchWorkbenchApi.candidates().catch((error) => ({ items: [], reportErrors: [errorText(error)] })),
      ]);
      setSummary(nextSummary);
      setCandidates(rows(nextCandidates.items));
      setCandidateErrors(list(nextCandidates.reportErrors));
    } catch (error) {
      setSummary(null);
      setCandidates([]);
      setCandidateErrors([]);
      setStatus(errorText(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void refresh(); }, []);

  const jobs = rows(field(summary, 'jobs'));
  const promotions = rows(field(summary, 'paperPromotions', 'paper_promotions'));
  const reviews = rows(field(summary, 'paperReviewRequests', 'paper_review_requests'));
  const metrics = field(summary, 'metrics') || {};
  const connection = field(summary, 'connection') || {};
  const activeJobs = jobs.filter((job) => ['queued', 'planning', 'running', 'validating'].includes(String(field(job, 'status'))));
  const failedJobs = jobs.filter((job) => ['rejected', 'failed', 'canceled'].includes(String(field(job, 'status'))));
  const passingCandidates = candidates.filter((candidate) => {
    const gates = field(candidate, 'gateResults', 'gate_results') || {};
    return field(candidate, 'status') === 'evidence_recorded' && Object.keys(gates).length > 0 && Object.values(gates).every(Boolean);
  });
  const dataGaps = candidates.filter((candidate) => list(field(candidate, 'dataGaps', 'data_gaps')).length > 0);
  const pendingApprovals = promotions.filter((promotion) => field(promotion, 'status') === 'pending_paper_approval');
  const observingPromotions = promotions.filter((promotion) => ['paper_observing', 'paper_degraded', 'paper_review_required'].includes(String(field(promotion, 'status'))));
  const visibleMandateSymbols = useMemo(() => {
    const query = mandateSymbolSearch.trim().toUpperCase();
    return Array.from(new Set([...mandateSymbolOptions, ...mandateSymbols]))
      .filter((symbol) => !query || symbol.toUpperCase().includes(query))
      .sort((left, right) => left.localeCompare(right))
      .slice(0, 120);
  }, [mandateSymbolOptions, mandateSymbolSearch, mandateSymbols]);

  const stageStates = useMemo<Record<StageId, { tone: StageTone; count: number }>>(() => {
    const connectionFailed = field(connection, 'status') === 'unavailable';
    const failedCandidates = candidates.filter((candidate) => ['rejected', 'failed'].includes(String(field(candidate, 'status')))).length;
    return {
      proposal: { count: jobs.length, tone: connectionFailed ? 'failed' : jobs.length > 0 ? 'passed' : 'active' },
      research: { count: activeJobs.length, tone: connectionFailed ? 'failed' : activeJobs.length > 0 ? 'active' : failedJobs.length > 0 && candidates.length === 0 ? 'failed' : jobs.length > 0 ? 'passed' : 'idle' },
      results: { count: candidates.length, tone: connectionFailed ? 'failed' : dataGaps.length > 0 ? 'blocked' : passingCandidates.length > 0 ? 'passed' : failedCandidates > 0 ? 'failed' : 'idle' },
      paper: { count: pendingApprovals.length + observingPromotions.length + reviews.length, tone: connectionFailed ? 'failed' : pendingApprovals.length > 0 || reviews.length > 0 ? 'human' : observingPromotions.length > 0 ? 'passed' : passingCandidates.length > 0 ? 'active' : 'idle' },
    };
  }, [activeJobs.length, candidates, connection, dataGaps.length, failedJobs.length, jobs.length, observingPromotions.length, passingCandidates.length, pendingApprovals.length, reviews.length]);

  const openAction = (action: PendingAction, prefix: string) => {
    setActionReason('');
    setActionIdempotencyKey(idempotencyKey(prefix));
    setPendingAction(action);
  };

  const completeAction = async () => {
    if (!pendingAction || !actionReason.trim() || !actionIdempotencyKey.trim()) return;
    setWriteBusy(true);
    try {
      await pendingAction.execute(actionReason.trim(), actionIdempotencyKey.trim());
      setStatus(`${pendingAction.title}已提交；等待 HyperTrade 返回真实状态。`);
      setPendingAction(null);
      await refresh();
    } catch (error) {
      setStatus(errorText(error));
    } finally {
      setWriteBusy(false);
    }
  };

  const loadMandateSymbols = async () => {
    setMandateSymbolsLoading(true);
    setMandateSymbolsError('');
    try {
      const response = await marketApi.getSymbols('okx', 'USDT', 'swap');
      const received = Array.isArray(response.symbols)
        ? response.symbols.map((symbol) => String(symbol).trim()).filter(Boolean)
        : [];
      if (!received.length) {
        setMandateSymbolsError('BitPro 市场接口未返回可选 USDT 永续标的。');
        return;
      }
      setMandateSymbolOptions(Array.from(new Set([...DEFAULT_MANDATE_SYMBOLS, ...received])).sort((left, right) => left.localeCompare(right)));
    } catch (error) {
      setMandateSymbolsError(`加载真实 USDT 永续标的失败：${errorText(error)}`);
    } finally {
      setMandateSymbolsLoading(false);
    }
  };

  const openProposalDialog = () => {
    setProposalFormError('');
    setProposalOpen(true);
    void loadMandateSymbols();
  };

  const closeProposalDialog = () => {
    setProposalFormError('');
    setProposalOpen(false);
  };

  const resetProposalForm = () => {
    setMandateSymbols(DEFAULT_MANDATE_SYMBOLS);
    setMandateSymbolSearch('');
    setCustomMandateSymbol('');
    setMandateSymbolsError('');
    setMandateTimeframe('4h');
    setMandateCategory('cta');
    setProposalDirection('');
    setProposalFormError('');
  };

  const toggleMandateSymbol = (symbol: string) => {
    setMandateSymbols((current) => current.includes(symbol)
      ? current.filter((item) => item !== symbol)
      : [...current, symbol]);
    setProposalFormError('');
  };

  const addCustomMandateSymbol = () => {
    const symbol = customMandateSymbol.trim().toUpperCase();
    if (!symbol) return;
    if (!symbol.includes('/')) {
      setProposalFormError('自定义标的请使用完整统一格式，例如 BTC/USDT:USDT。');
      return;
    }
    setMandateSymbols((current) => current.includes(symbol) ? current : [...current, symbol]);
    setCustomMandateSymbol('');
    setProposalFormError('');
  };

  const submitProposal = async () => {
    if (mandateSymbols.length === 0 || !proposalDirection.trim()) {
      setProposalFormError('请选择至少一个标的并填写提议方向。');
      return;
    }
    setProposalFormError('');
    setWriteBusy(true);
    try {
      const scope = mandateSymbols.map((symbol) => symbol.split('/')[0]).join('/');
      const category = mandateCategory === 'mean_reversion' ? '均值回归' : mandateCategory === 'grid' ? '网格' : 'CTA';
      const createdMandate = await researchWorkbenchApi.createMandate({
        name: `${scope} ${mandateTimeframe.toUpperCase()} ${category} 研究提议`.slice(0, 160),
        marketType: 'swap',
        symbols: mandateSymbols,
        timeframes: [mandateTimeframe],
        strategyCategories: [mandateCategory],
        budget: {},
        validation: {},
        paperPromotionMode: 'manual_approval',
        liveMode: 'disabled',
        reason: '提交研究提议并建立内部研究范围',
        idempotencyKey: idempotencyKey('proposal-scope'),
      });
      const mandateId = String(field(createdMandate, 'id', 'mandateId', 'mandate_id') || '');
      if (!mandateId) throw new Error('内部研究范围已创建，但未返回可用 ID，未创建 HT 研究任务。');
      const createdJob = await researchWorkbenchApi.createJob(mandateId, {
        prompt: proposalDirection.trim(),
        sourceRunId: '',
        reason: '根据操作者提议创建 HT 研究任务',
        idempotencyKey: idempotencyKey('proposal-job'),
      });
      const job = field(createdJob, 'job') || createdJob;
      const jobId = String(field(job, 'id', 'jobId', 'job_id') || '');
      if (!jobId) throw new Error('HT 研究任务已创建，但未返回可用 ID，无法自动启动研究回测。');
      await researchWorkbenchApi.runJob(jobId, {
        reason: '提交提议后自动运行 HT 研究与回测',
        idempotencyKey: idempotencyKey('proposal-run'),
      });
      setProposalOpen(false);
      resetProposalForm();
      setSelectedStage('research');
      setStatus('提议已提交，HT 正在自动完成研究、校验和回测。');
      await refresh();
    } catch (error) {
      setProposalFormError(errorText(error));
    } finally {
      setWriteBusy(false);
    }
  };

  const requestPaper = (candidate: Row) => openAction({
    title: '申请模拟盘',
    description: '仅通过全部验证门禁并已记录证据的结果可申请。申请不会直接配置或启动模拟盘。',
    execute: (reason, key) => researchWorkbenchApi.requestPaperPromotion({
      evidenceId: field(candidate, 'id'),
      jobId: field(field(candidate, 'job'), 'id'),
      reason,
      idempotencyKey: key,
    }),
  }, 'paper-request');

  const renderResearchJobs = () => jobs.length ? (
    <div className="space-y-2">
      {jobs.map((job) => {
        const id = String(field(job, 'id'));
        const spec = field(job, 'strategySpec', 'strategy_spec') || {};
        const jobStatus = String(field(job, 'status') || '');
        const failure = field(job, 'error', 'errorMessage', 'error_message', 'failureReason', 'failure_reason', 'rejectionReason', 'rejection_reason');
        return (
          <article key={id} className="rounded-lg border border-crypto-border bg-crypto-bg p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-gray-100" title={short(field(spec, 'title', 'strategyKey', 'strategy_key'))}>{short(field(spec, 'title', 'strategyKey', 'strategy_key')) === '--' ? 'HT 研究任务' : short(field(spec, 'title', 'strategyKey', 'strategy_key'))}</div>
                <div className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-gray-500" title={short(field(job, 'prompt'))}>{short(field(job, 'prompt'))}</div>
              </div>
              <span className={clsx('shrink-0 rounded border px-2 py-0.5 text-[10px]', statusTone(jobStatus))}>{statusLabel(jobStatus)}</span>
            </div>
            {failure && <div className="mt-2 rounded border border-red-400/25 bg-red-400/5 px-2 py-1.5 text-[11px] leading-relaxed text-red-100">失败原因：{short(failure)}</div>}
            {!failure && ['rejected', 'failed'].includes(jobStatus) && <div className="mt-2 rounded border border-amber-400/25 bg-amber-400/5 px-2 py-1.5 text-[11px] text-amber-100">当前任务摘要未返回具体原因，请查看详情中的 HT 报告。</div>}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button type="button" onClick={() => setDetail(job)} className="inline-flex h-7 items-center gap-1 rounded border border-crypto-border px-2 text-[11px] text-gray-300 hover:border-blue-400"><FileSearch size={12} />查看研究详情</button>
              <span className="ml-auto max-w-full truncate font-mono text-[10px] text-gray-600" title={id}>任务 {id || '--'}</span>
            </div>
          </article>
        );
      })}
    </div>
  ) : <EmptyStage>{STAGES[1].empty}</EmptyStage>;

  const renderPaperDecision = () => {
    const snapshots = promotions
      .filter((promotion) => field(promotion, 'observation'))
      .map((promotion) => ({ promotion, snapshot: field(field(promotion, 'observation'), 'paperSnapshot', 'paper_snapshot') || {} }));
    if (promotions.length === 0 && reviews.length === 0) return <EmptyStage>{STAGES[3].empty}</EmptyStage>;
    return (
      <div className="space-y-3">
        {promotions.map((promotion) => {
          const id = String(field(promotion, 'id'));
          const pending = field(promotion, 'status') === 'pending_paper_approval';
          return (
            <article key={id} className="rounded-lg border border-crypto-border bg-crypto-bg p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0"><div className="truncate text-sm font-semibold text-gray-100">{short(field(promotion, 'strategyKey', 'strategy_key'))}</div><div className="mt-1 text-[11px] text-gray-500">BitPro #{short(field(promotion, 'bitproStrategyId', 'bitpro_strategy_id'))} · 人工审批</div></div>
                <span className={clsx('shrink-0 rounded border px-2 py-0.5 text-[10px]', statusTone(field(promotion, 'status')))}>{statusLabel(field(promotion, 'status'))}</span>
              </div>
              <div className="mt-2 text-[11px] text-gray-500">申请原因：{short(field(promotion, 'requestReason', 'request_reason'))}</div>
              {pending && <button type="button" onClick={() => openAction({ title: '审批模拟盘申请', description: '审批必须填写理由和唯一幂等键。工作台不会直接配置或启动模拟盘。', tone: 'warning', execute: (reason, key) => researchWorkbenchApi.approvePaperPromotion(id, { reason, idempotencyKey: key }) }, 'paper-approve')} className="mt-3 inline-flex h-7 items-center gap-1 rounded border border-orange-400/45 bg-orange-400/10 px-2 text-[11px] font-semibold text-orange-100 hover:bg-orange-400/20"><CircleUserRound size={12} />填写理由并审批</button>}
            </article>
          );
        })}
        {snapshots.map(({ promotion, snapshot }) => (
          <article key={`snapshot-${String(field(promotion, 'id'))}`} className="rounded-lg border border-crypto-border bg-crypto-bg p-3">
            <div className="flex items-start justify-between gap-2"><div className="min-w-0"><div className="truncate text-sm font-semibold text-gray-100">模拟盘只读证据</div><div className="mt-1 truncate text-[11px] text-gray-500">paper_snapshot · 会话 {short(field(snapshot, 'instanceId', 'instance_id'))} · 策略版本 {short(field(snapshot, 'strategyVersion', 'strategy_version'))}</div></div><span className={clsx('shrink-0 rounded border px-2 py-0.5 text-[10px]', statusTone(field(promotion, 'status')))}>{statusLabel(field(promotion, 'status'))}</span></div>
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3"><Metric label="权益" value={formatNumber(field(snapshot, 'equity'))} /><Metric label="PnL" value={formatNumber(field(snapshot, 'pnl'))} /><Metric label="累计收益" value={formatPct(field(snapshot, 'totalReturnPct', 'total_return_pct'))} /><Metric label="回撤" value={formatPct(field(snapshot, 'maxDrawdownPct', 'max_drawdown_pct'))} /><Metric label="Sharpe" value={formatNumber(field(snapshot, 'sharpe'))} /><Metric label="交易 / 错误" value={`${formatNumber(field(snapshot, 'totalTrades', 'total_trades'), 0)} / ${formatNumber(field(snapshot, 'errorCount', 'error_count'), 0)}`} /></div>
            <div className="mt-2 grid grid-cols-2 gap-2"><CopyValue label="数据覆盖" value={field(snapshot, 'dataCoverage', 'data_coverage')} /><CopyValue label="生成时间" value={formatTime(field(snapshot, 'generatedAt', 'generated_at'))} /></div>
            <div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => setDetail({ ...promotion, paperSnapshot: snapshot })} className="inline-flex h-7 items-center gap-1 rounded border border-crypto-border px-2 text-[11px] text-gray-300 hover:border-blue-400"><FileSearch size={12} />查看证据</button><a href={`/live?strategy_id=${encodeURIComponent(String(field(snapshot, 'strategyId', 'strategy_id', field(promotion, 'bitproStrategyId', 'bitpro_strategy_id')) || ''))}`} className="inline-flex h-7 items-center gap-1 rounded border border-crypto-border px-2 text-[11px] text-gray-300 hover:border-blue-400">跳转模拟盘详情<ChevronRight size={12} /></a></div>
          </article>
        ))}
        {reviews.map((review) => {
          const evidence = field(review, 'evidence') || {};
          const recommendation = short(field(evidence, 'recommendedNextAction', 'recommended_next_action'));
          return (
            <article key={short(field(review, 'id'))} className="rounded-lg border border-orange-400/25 bg-crypto-bg p-3">
              <div className="flex items-start justify-between gap-2"><div className="min-w-0"><div className="truncate text-sm font-semibold text-gray-100">人工复核请求</div><div className="mt-1 text-[11px] text-gray-500">{short(field(review, 'reason'))}</div></div><span className="shrink-0 rounded border border-orange-400/40 bg-orange-400/10 px-2 py-0.5 text-[10px] text-orange-200">{statusLabel(field(review, 'status'))}</span></div>
              <div className="mt-2 grid grid-cols-2 gap-2"><CopyValue label="证据引用" value={field(evidence, 'snapshotId', 'snapshot_id', 'traceRef', 'trace_ref')} /><CopyValue label="数据缺口" value={list(field(field(evidence, 'drift'), 'dataGaps', 'data_gaps')).join('；')} /></div>
              <div className="mt-2 text-[11px] text-orange-100/80">建议：{REVIEW_ACTIONS.includes(recommendation as typeof REVIEW_ACTIONS[number]) ? recommendation : 'request_paper_review'}</div>
              <button type="button" onClick={() => setDetail(review)} className="mt-3 inline-flex h-7 items-center gap-1 rounded border border-crypto-border px-2 text-[11px] text-gray-300 hover:border-blue-400"><FileSearch size={12} />查看复核证据</button>
            </article>
          );
        })}
      </div>
    );
  };

  const renderSelectedStage = () => {
    const stage = STAGES.find((item) => item.id === selectedStage)!;
    if (loading) return <EmptyStage>正在读取 BitPro 代理返回的 HyperTrade 真实对象；不会显示演示数据。</EmptyStage>;
    if (field(connection, 'status') === 'unavailable') return <EmptyStage>{short(field(connection, 'error'))}</EmptyStage>;
    if (selectedStage === 'proposal') {
      return (
        <div className="rounded-lg border border-blue-400/20 bg-blue-400/5 p-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0"><div className="text-sm font-semibold text-gray-100">告诉 HT 你想研究什么</div><p className="mt-1 max-w-3xl text-xs leading-relaxed text-gray-400">只需描述方向或假设。BitPro 会在后台建立受控研究范围，HT 自动完成规格、数据/代码校验、回测和验证。</p></div>
            <button type="button" onClick={openProposalDialog} className="inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-xs font-semibold text-white hover:bg-blue-500"><Sparkles size={14} />提交研究提议</button>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-2 text-[11px] text-gray-400 sm:grid-cols-3"><div className="rounded border border-crypto-border bg-crypto-bg px-3 py-2">1. 选择标的并写提议</div><div className="rounded border border-crypto-border bg-crypto-bg px-3 py-2">2. HT 自动研究与回测</div><div className="rounded border border-crypto-border bg-crypto-bg px-3 py-2">3. 你根据结果决定模拟盘</div></div>
        </div>
      );
    }
    if (selectedStage === 'research') return renderResearchJobs();
    if (selectedStage === 'results') return candidates.length ? <div className="space-y-2">{candidates.map((candidate) => <CandidateCard key={short(field(candidate, 'id'))} candidate={candidate} onView={setDetail} onRequestPaper={requestPaper} />)}</div> : <EmptyStage>{stage.empty}</EmptyStage>;
    return renderPaperDecision();
  };

  const connectionUnavailable = field(connection, 'status') === 'unavailable';
  const connectionLabel = connectionUnavailable ? 'HyperTrade 不可用' : field(connection, 'status') === 'connected' ? 'HyperTrade 已连接' : 'HyperTrade 状态未知';
  const realError = status || (connectionUnavailable ? short(field(connection, 'error')) : '');

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><FlaskConical size={18} className="text-cyan-300" /><h2 className="text-base font-semibold text-gray-100">策略研发工作台</h2><span className={clsx('rounded border px-2 py-0.5 text-[10px]', connectionUnavailable ? 'border-red-500/40 bg-red-500/10 text-red-200' : 'border-emerald-500/35 bg-emerald-500/10 text-emerald-200')}>{connectionLabel}</span></div><p className="mt-1 text-xs text-gray-500">写提议，HT 自动研究回测；你只根据真实回测证据决定是否申请模拟盘。</p></div>
          <div className="flex shrink-0 flex-wrap gap-2"><button type="button" onClick={openProposalDialog} className="inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-4 text-xs font-semibold text-white hover:bg-blue-500"><Sparkles size={14} />提交研究提议</button><button type="button" onClick={() => void refresh()} disabled={loading} className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border px-3 text-xs text-gray-300 hover:border-blue-400 disabled:opacity-50"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />同步</button></div>
        </div>
        {realError && <div role="alert" className="mt-3 rounded-lg border border-red-500/35 bg-red-500/10 px-3 py-2 text-xs text-red-100">真实错误：{realError}</div>}
        {candidateErrors.length > 0 && <div className="mt-3 rounded-lg border border-amber-400/30 bg-amber-400/5 px-3 py-2 text-xs text-amber-100">候选证据读取不完整：{candidateErrors.join('；')}</div>}
        <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4"><Metric label="HT 研究中" value={field(metrics, 'runningJobs', 'running_jobs') ?? activeJobs.length} /><Metric label="回测结果" value={candidates.length} /><Metric label="验证通过" value={field(metrics, 'passingCandidates', 'passing_candidates') ?? passingCandidates.length} /><Metric label="模拟盘待处理" value={pendingApprovals.length + reviews.length} /></div>
        <div className="mt-2 text-[10px] text-gray-600">最近同步：{formatTime(field(summary, 'lastSyncedAt', 'last_synced_at'))}</div>
      </section>

      <section className="rounded-xl border border-crypto-border bg-crypto-card p-3">
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4">
          {STAGES.map((stage, index) => {
            const state = stageStates[stage.id];
            const Icon = stage.icon;
            return (
              <div key={stage.id} className="relative min-w-0">
                {index < STAGES.length - 1 && <div className="absolute -right-2 top-1/2 z-0 hidden h-px w-2 bg-crypto-border xl:block" />}
                <button type="button" onClick={() => setSelectedStage(stage.id)} className={clsx('relative z-10 flex min-h-[96px] w-full flex-col rounded-lg border p-3 text-left transition-colors', stageClass(state.tone, selectedStage === stage.id))}>
                  <div className="flex w-full items-start justify-between gap-2"><span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-current/25 bg-black/10"><Icon size={15} /></span><StageBadge tone={state.tone} count={state.count} /></div>
                  <div className="mt-auto truncate text-xs font-semibold" title={stage.label}>{stage.label}</div>
                </button>
              </div>
            );
          })}
        </div>
      </section>

      <section className="min-h-[430px] overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
        <div className="flex items-center justify-between gap-2 border-b border-crypto-border px-4 py-3"><div><div className="text-sm font-semibold text-gray-100">{STAGES.find((stage) => stage.id === selectedStage)?.label}</div><div className="mt-1 text-[11px] text-gray-500">真实对象与证据</div></div><span className="rounded border border-crypto-border bg-crypto-bg px-2 py-0.5 text-[10px] text-gray-400">{stageStates[selectedStage].count} 项</span></div>
        <div className="min-h-[350px] p-3">{renderSelectedStage()}</div>
        <div className="border-t border-crypto-border px-4 py-2 text-[10px] text-gray-600">研究与模拟盘结果仅作为证据，不代表稳定盈利或实盘表现。最近同步：{formatTime(field(summary, 'lastSyncedAt', 'last_synced_at'))}</div>
      </section>

      <ThemeDialog open={proposalOpen} variant="confirm" title="提交研究提议" tone="default" confirmText={writeBusy ? '提交中...' : '提交给 HT'} confirmDisabled={writeBusy || mandateSymbols.length === 0 || !proposalDirection.trim()} onCancel={closeProposalDialog} onConfirm={() => void submitProposal()}>
        <div className="space-y-3">
          <p className="rounded border border-blue-400/25 bg-blue-400/5 px-3 py-2 text-xs leading-relaxed text-blue-100">提交后 HT 自动完成规格、校验和回测；你只需查看结果并决定是否申请模拟盘。</p>
          {proposalFormError && <p role="alert" className="rounded border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs leading-relaxed text-amber-100">{proposalFormError}</p>}
          <section className="min-w-0" aria-labelledby="research-proposal-symbols-label">
            <div className="flex items-center justify-between gap-2 text-xs text-gray-400"><span id="research-proposal-symbols-label">标的范围</span><span className="shrink-0 text-[11px] text-blue-200">已选 {mandateSymbols.length} 个</span></div>
            <div className="mt-1 overflow-hidden rounded-xl border border-crypto-border bg-crypto-bg shadow-[inset_0_1px_0_rgba(255,255,255,0.035)]">
              <div className="flex items-center gap-2 border-b border-crypto-border px-2"><Search size={14} className="shrink-0 text-gray-500" aria-hidden="true" /><input type="search" value={mandateSymbolSearch} onChange={(event) => setMandateSymbolSearch(event.target.value)} className="h-9 min-w-0 flex-1 bg-transparent text-sm text-gray-100 outline-none placeholder:text-gray-600" placeholder="搜索 BTC、ETH 或完整合约标的" aria-label="搜索真实 USDT 永续标的" /></div>
              <div className="max-h-40 min-h-[6rem] overflow-y-auto p-1" aria-live="polite">
                {mandateSymbolsLoading ? <p className="px-2 py-3 text-xs text-gray-500">正在读取 BitPro 市场接口中的真实 USDT 永续标的…</p> : mandateSymbolsError ? <p role="alert" className="px-2 py-3 text-xs leading-relaxed text-amber-100">{mandateSymbolsError}</p> : visibleMandateSymbols.length ? visibleMandateSymbols.map((symbol) => {
                  const selected = mandateSymbols.includes(symbol);
                  return <button key={symbol} type="button" aria-pressed={selected} onClick={() => toggleMandateSymbol(symbol)} className={clsx('flex h-8 w-full items-center gap-2 rounded-lg px-2 text-left text-xs transition-colors', selected ? 'bg-blue-500/15 text-blue-100' : 'text-gray-300 hover:bg-white/[0.045] hover:text-white')}><span className={clsx('inline-flex h-4 w-4 shrink-0 items-center justify-center rounded border', selected ? 'border-blue-400 bg-blue-500 text-white' : 'border-crypto-border')}>{selected && <Check size={11} />}</span><span className="min-w-0 truncate font-mono" title={symbol}>{symbol}</span></button>;
                }) : <p className="px-2 py-3 text-xs text-gray-500">没有匹配的真实标的；请修改搜索词或手动加入完整统一格式。</p>}
              </div>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5" aria-label="已选标的">{mandateSymbols.map((symbol) => <button key={symbol} type="button" onClick={() => toggleMandateSymbol(symbol)} className="inline-flex max-w-full items-center gap-1 rounded border border-blue-400/35 bg-blue-400/10 px-2 py-1 font-mono text-[11px] text-blue-100 hover:border-blue-300"><span className="truncate">{symbol}</span><XCircle size={12} className="shrink-0" aria-label={`移除 ${symbol}`} /></button>)}</div>
            <div className="mt-2 flex min-w-0 gap-2"><input value={customMandateSymbol} onChange={(event) => setCustomMandateSymbol(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addCustomMandateSymbol(); } }} className="h-8 min-w-0 flex-1 rounded border border-crypto-border bg-crypto-card px-2 font-mono text-xs text-gray-100 placeholder:text-gray-600" placeholder="自定义标的（回车加入）" aria-label="手动加入完整统一格式标的" /><button type="button" onClick={addCustomMandateSymbol} disabled={!customMandateSymbol.trim()} className="shrink-0 rounded border border-crypto-border px-2 text-xs text-gray-300 hover:border-blue-400 hover:text-blue-100 disabled:cursor-not-allowed disabled:opacity-45">加入</button></div>
          </section>
          <div className="grid grid-cols-2 gap-3"><label className="block text-xs text-gray-400">周期<CryptoSelect value={mandateTimeframe} onChange={(event) => setMandateTimeframe(event.target.value)} wrapperClassName="mt-1"><option value="15m">15M</option><option value="1h">1H</option><option value="4h">4H</option><option value="1d">1D</option></CryptoSelect></label><label className="block text-xs text-gray-400">研究类型<CryptoSelect value={mandateCategory} onChange={(event) => setMandateCategory(event.target.value)} wrapperClassName="mt-1"><option value="cta">CTA</option><option value="mean_reversion">均值回归</option><option value="grid">网格</option></CryptoSelect></label></div>
          <label className="block text-xs text-gray-400">提议方向<textarea value={proposalDirection} onChange={(event) => { setProposalDirection(event.target.value); setProposalFormError(''); }} className="mt-1 min-h-[120px] w-full rounded border border-crypto-border bg-crypto-bg px-2 py-2 text-sm text-gray-100" placeholder="例如：研究 BTC/ETH 4H 突破策略，重点比较趋势过滤与止损方式，并计入手续费、滑点和资金费。" /></label>
          <p className="text-[11px] leading-relaxed text-gray-500">内部研究范围、StrategySpec、校验和验证门禁由 HT 自动处理；模拟盘仍固定为人工审批，实盘模式固定禁用。</p>
        </div>
      </ThemeDialog>
      <ThemeDialog open={pendingAction !== null} variant="confirm" title={pendingAction?.title || ''} tone={pendingAction?.tone || 'default'} confirmText={writeBusy ? '提交中...' : '确认提交'} confirmDisabled={writeBusy || !actionReason.trim() || !actionIdempotencyKey.trim()} onCancel={() => setPendingAction(null)} onConfirm={() => void completeAction()}><div className="space-y-3"><p className="text-xs leading-relaxed text-gray-400">{pendingAction?.description}</p><label className="block text-xs text-gray-400">理由<textarea value={actionReason} onChange={(event) => setActionReason(event.target.value)} className="mt-1 min-h-[88px] w-full rounded border border-crypto-border bg-crypto-bg px-2 py-2 text-sm text-gray-100" placeholder="填写操作者理由（必填）。" /></label><label className="block text-xs text-gray-400">唯一幂等键<div className="mt-1 flex gap-2"><input value={actionIdempotencyKey} onChange={(event) => setActionIdempotencyKey(event.target.value)} className="h-9 min-w-0 flex-1 rounded border border-crypto-border bg-crypto-bg px-2 font-mono text-xs text-gray-100" /><button type="button" onClick={() => setActionIdempotencyKey(idempotencyKey('research-workbench'))} className="shrink-0 rounded border border-crypto-border px-2 text-xs text-gray-300 hover:border-blue-400">生成</button></div></label></div></ThemeDialog>
      <ThemeDialog open={detail !== null} variant="alert" title="研究证据详情" tone="default" confirmText="关闭" onClose={() => setDetail(null)}><pre className="max-h-[52vh] overflow-auto whitespace-pre-wrap break-words text-xs leading-relaxed text-gray-300">{JSON.stringify(detail, null, 2)}</pre></ThemeDialog>
    </div>
  );
}
