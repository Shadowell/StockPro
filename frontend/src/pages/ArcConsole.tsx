import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Ban,
  Bot,
  CheckCircle2,
  Clock3,
  FlaskConical,
  LineChart,
  Lightbulb,
  Loader2,
  Play,
  RefreshCw,
  Rocket,
  ScrollText,
  ShieldCheck,
  Swords,
  Target,
  XCircle,
} from 'lucide-react';
import clsx from 'clsx';
import { SELECTED_SEGMENT_BORDER_CLASS } from '../utils/selectionStyles';
import {
  arcApi,
  type ArcActivityRow,
  type ArcCandidateRow,
  type ArcConsoleConfig,
  type ArcEvidence,
  type ArcMissionSummary,
  type ArcPipelineStage,
  type ArcPipelineView,
  type ArcStageStatus,
} from '../api/client';
import SymbolCell from '../components/SymbolCell';

const MISSION_POLL_MS = 5000;
const PROGRESS_POLL_MS = 3000;

const STAGE_ICONS: Record<string, typeof Target> = {
  goal: Target,
  explore: Lightbulb,
  red_team: Swords,
  validate: FlaskConical,
  paper: LineChart,
  approval: ShieldCheck,
  live: Rocket,
};

const STATE_LABELS: Record<string, string> = {
  created: '已创建',
  compiling_goal: '编译目标',
  exploring_candidates: '探索候选',
  mutating: '变异候选',
  red_team_testing: '红队对抗',
  validating: '验证中',
  paper_authorizing: '模拟盘授权',
  paper_observing: '模拟盘观察',
  live_approval_ready: '待实盘审批',
  approved_pending_effect: '已批准待生效',
  live_canary: '实盘灰度',
  needs_operator: '需要人工',
  completed: '已完成',
  failed: '已失败',
};

const BLOCK_REASONS: Record<string, string> = {
  evidence_window_unavailable: '缺少可用的历史行情窗口，研究无法开始',
  no_out_of_sample_evidence: '存活候选没有样本外证据，不予采信',
  no_validated_candidate: '预算内没有候选通过红队与门禁',
  bitpro_self_test_incomplete: 'StockPro 自测没有回传完整引用',
  paper_preauthorization_missing: '缺少模拟盘预授权',
  paper_provision_failed: 'StockPro 模拟盘启动失败',
  paper_instance_missing: '模拟盘实例丢失',
  paper_sample_insufficient: '观察窗结束时样本仍然不足',
  live_promote_unhealthy: 'StockPro 实盘上线未返回健康结果',
};

const UNKNOWN_LABELS: Record<string, string> = {
  missing_candidate: '缺少候选',
  missing_backtest_ref: '缺少 StockPro 回测引用',
  missing_validation_id: '缺少校验 ID',
  missing_bitpro_strategy_id: '缺少 StockPro 策略 ID',
  missing_paper_instance: '缺少模拟盘实例',
  missing_paper_observation: '缺少模拟盘观察',
  paper_instance_unconfirmed: '模拟盘实例未确认',
};

const STAGE_TONES: Record<ArcStageStatus, { shell: string; bar: string; text: string }> = {
  done: {
    shell: 'border-emerald-500/25 bg-emerald-500/[0.06]',
    bar: 'bg-emerald-400',
    text: 'text-emerald-300',
  },
  active: {
    shell: 'border-blue-500/30 bg-blue-500/[0.08] shadow-inner shadow-blue-950/20',
    bar: 'bg-blue-400',
    text: 'text-blue-300',
  },
  blocked: {
    shell: 'border-yellow-500/30 bg-yellow-500/[0.07]',
    bar: 'bg-yellow-400',
    text: 'text-yellow-300',
  },
  pending: {
    shell: 'border-crypto-border bg-crypto-bg/40',
    bar: 'bg-gray-700',
    text: 'text-gray-500',
  },
};

function unknownLabel(code: string): string {
  if (UNKNOWN_LABELS[code]) return UNKNOWN_LABELS[code];
  if (code.startsWith('bitpro_unhealthy:')) {
    return `StockPro 不健康：${code.slice('bitpro_unhealthy:'.length)}`;
  }
  return code;
}

function stateLabel(state: string): string {
  return STATE_LABELS[state] || state;
}

function formatNumber(value: unknown, digits = 2): string {
  if (value == null || Number.isNaN(Number(value))) return '--';
  return Number(value).toFixed(digits);
}

/** The mission projection stamps events in naive UTC, which JS would read as local. */
function parseUtc(value: string): Date {
  const normalized = /[Z+]|-\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
  return new Date(normalized);
}

function clockTime(value: string): string {
  const parsed = parseUtc(value);
  if (Number.isNaN(parsed.getTime())) return '--';
  return parsed.toLocaleTimeString('zh-CN', { hour12: false });
}

function elapsedLabel(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '--';
  if (seconds < 60) return `${Math.floor(seconds)} 秒前`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function isRunning(mission: ArcMissionSummary): boolean {
  const badge = mission.pipeline;
  if (badge) return !badge.finished && !badge.blocked;
  return !['needs_operator', 'failed', 'completed', 'live_canary'].includes(mission.state);
}

function stageRatio(stage: ArcPipelineStage): number {
  const raw = stage.metrics?.ratio;
  return typeof raw === 'number' ? Math.min(1, Math.max(0, raw)) : 0;
}

function MetaChip({
  icon,
  label,
  value,
  tone = 'default',
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone?: 'default' | 'blue';
}) {
  return (
    <span
      className={clsx(
        'inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5',
        tone === 'blue'
          ? 'border-blue-500/20 bg-blue-500/10 text-blue-300'
          : 'border-crypto-border bg-crypto-bg/80',
      )}
    >
      {icon}
      <span>{label}</span>
      <span className={clsx('font-semibold', tone === 'blue' ? 'text-blue-200' : 'text-gray-200')}>
        {value}
      </span>
    </span>
  );
}

function KpiCard({
  label,
  value,
  sub,
  tone = 'blue',
}: {
  label: string;
  value: string;
  sub: string;
  tone?: 'blue' | 'emerald' | 'yellow' | 'slate';
}) {
  const toneStyles = {
    blue: { text: 'text-blue-300', border: 'border-blue-500/25', bg: 'bg-blue-500/[0.06]' },
    emerald: {
      text: 'text-emerald-300',
      border: 'border-emerald-500/25',
      bg: 'bg-emerald-500/[0.06]',
    },
    yellow: { text: 'text-yellow-300', border: 'border-yellow-500/25', bg: 'bg-yellow-500/[0.06]' },
    slate: { text: 'text-gray-200', border: 'border-crypto-border', bg: 'bg-crypto-card' },
  }[tone];
  return (
    <section
      className={clsx('rounded-xl border p-4 shadow-inner shadow-black/10', toneStyles.border, toneStyles.bg)}
    >
      <div className="mb-3 text-xs font-semibold text-gray-400">{label}</div>
      <div
        className={clsx(
          'truncate text-[clamp(1.25rem,1.55vw,1.75rem)] font-bold leading-tight tabular-nums',
          toneStyles.text,
        )}
      >
        {value}
      </div>
      <div className="mt-2 truncate text-[11px] leading-snug text-gray-500">{sub}</div>
    </section>
  );
}

function SectionTitle({
  icon,
  title,
  meta,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  meta?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-blue-500/20 bg-blue-500/10 text-blue-300">
          {icon}
        </span>
        <h2 className="truncate text-sm font-semibold text-white">{title}</h2>
      </div>
      {children ??
        (meta && (
          <span className="shrink-0 rounded-md border border-crypto-border bg-crypto-bg px-2 py-1 text-[10px] font-medium text-gray-500">
            {meta}
          </span>
        ))}
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-crypto-border bg-crypto-bg/40 p-6 text-center text-sm text-gray-500">
      {text}
    </div>
  );
}

function StageCard({ stage }: { stage: ArcPipelineStage }) {
  const Icon = STAGE_ICONS[stage.key] || Activity;
  const tone = STAGE_TONES[stage.status];
  const ratio = stage.status === 'active' ? stageRatio(stage) : stage.status === 'done' ? 1 : 0;
  return (
    <div className={clsx('flex min-h-[112px] flex-col rounded-xl border p-3', tone.shell)}>
      <div className="flex items-center gap-1.5">
        <Icon className={clsx('h-3.5 w-3.5 shrink-0', tone.text)} />
        <span className={clsx('truncate text-xs font-semibold', tone.text)}>{stage.label}</span>
        {stage.status === 'active' && (
          <span className="ml-auto h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-blue-400" />
        )}
        {stage.status === 'blocked' && <Ban className="ml-auto h-3 w-3 shrink-0 text-yellow-300" />}
        {stage.status === 'done' && (
          <CheckCircle2 className="ml-auto h-3 w-3 shrink-0 text-emerald-400" />
        )}
      </div>
      <p className="mt-2 line-clamp-3 flex-1 break-words text-[11px] leading-snug text-gray-500">
        {stage.detail || '--'}
      </p>
      <div className="mt-2.5 h-1.5 w-full rounded-full bg-crypto-bg">
        <div
          className={clsx('h-1.5 rounded-full transition-all duration-500', tone.bar)}
          style={{ width: `${Math.round(ratio * 100)}%` }}
        />
      </div>
    </div>
  );
}

function PipelinePanel({
  progress,
  freshSeconds,
  polling,
}: {
  progress: ArcPipelineView;
  freshSeconds: number;
  polling: boolean;
}) {
  const reason = progress.blockedReason;
  const barTone = progress.blocked
    ? 'bg-yellow-400'
    : progress.finished
      ? 'bg-emerald-400'
      : 'bg-blue-400';
  return (
    <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
      <SectionTitle icon={<Activity className="h-4 w-4" />} title="流水线进度">
        <div className="flex shrink-0 items-center gap-2 text-[10px] text-gray-500">
          <span className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-1 font-medium tabular-nums">
            {progress.eventCount} 事件
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-md border border-crypto-border bg-crypto-bg px-2 py-1 font-medium">
            <span
              className={clsx(
                'h-1.5 w-1.5 rounded-full',
                polling ? 'animate-pulse bg-blue-400' : 'bg-gray-600',
              )}
            />
            {polling ? '实时轮询' : '已停止'}
          </span>
        </div>
      </SectionTitle>

      <div className="rounded-xl border border-crypto-border bg-crypto-bg/40 p-3">
        <div className="flex items-baseline justify-between gap-3">
          <span className="truncate text-xs text-gray-500">
            {progress.finished ? '全部阶段完成' : `当前阶段 · ${stateLabel(progress.state)}`}
          </span>
          <span className="shrink-0 text-lg font-bold tabular-nums text-white">
            {progress.percent.toFixed(1)}%
          </span>
        </div>
        <div className="mt-2 h-2 w-full rounded-full bg-crypto-bg">
          <div
            className={clsx('h-2 rounded-full transition-all duration-500', barTone)}
            style={{ width: `${Math.min(100, Math.max(0, progress.percent))}%` }}
          />
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4 xl:grid-cols-7">
        {progress.stages.map((stage) => (
          <StageCard key={stage.key} stage={stage} />
        ))}
      </div>

      {progress.blocked && reason && (
        <div className="mt-3 flex items-start gap-2 rounded-xl border border-yellow-500/25 bg-yellow-500/[0.07] p-3 text-xs text-yellow-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0">
            <div className="font-semibold">{BLOCK_REASONS[reason.reason] || reason.reason}</div>
            {reason.message && (
              <div className="mt-1 break-words text-yellow-200/70">{reason.message}</div>
            )}
            {reason.missing.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {reason.missing.map((item) => (
                  <span
                    key={item}
                    className="rounded border border-yellow-500/25 bg-yellow-500/10 px-1.5 py-0.5 text-[10px]"
                  >
                    {item}
                  </span>
                ))}
              </div>
            )}
            <div className="mt-1.5 text-[10px] text-yellow-200/50">
              {clockTime(reason.at)} · 更新于 {elapsedLabel(freshSeconds)}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function ActivityFeed({ rows }: { rows: ArcActivityRow[] }) {
  return (
    <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
      <SectionTitle
        icon={<ScrollText className="h-4 w-4" />}
        title="活动流"
        meta={`最近 ${rows.length} 条`}
      />
      {rows.length === 0 ? (
        <EmptyState text="该任务还没有记录事件。" />
      ) : (
        <ol className="max-h-80 overflow-y-auto rounded-xl border border-crypto-border bg-crypto-bg/40">
          {rows.map((row) => (
            <li
              key={row.eventId}
              className="flex items-start gap-2 border-b border-crypto-border/60 px-3 py-2 last:border-0"
            >
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-400/70" />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-[11px] font-medium text-gray-200">{row.label}</span>
                  <span className="shrink-0 text-[10px] tabular-nums text-gray-600">
                    {clockTime(row.at)}
                  </span>
                </div>
                {Object.keys(row.detail).length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {Object.entries(row.detail).map(([key, value]) => (
                      <span
                        key={key}
                        className="max-w-full truncate rounded border border-crypto-border bg-crypto-bg px-1.5 py-0.5 text-[10px] text-gray-500"
                      >
                        {key}=<span className="text-gray-400">{String(value)}</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function MissionRow({
  mission,
  selected,
  onSelect,
}: {
  mission: ArcMissionSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  const badge = mission.pipeline;
  const percent = badge?.percent ?? 0;
  const barTone = badge?.blocked
    ? 'bg-yellow-400'
    : badge?.finished
      ? 'bg-emerald-400'
      : 'bg-blue-400';
  return (
    <button
      type="button"
      onClick={onSelect}
      className={clsx(
        'w-full rounded-lg border p-3 text-left transition-colors',
        selected
          ? SELECTED_SEGMENT_BORDER_CLASS
          : 'border-crypto-border bg-crypto-bg/40 hover:border-blue-500/20 hover:bg-white/[0.025]',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="line-clamp-2 flex-1 text-[11px] font-medium leading-snug text-gray-100">
          {mission.objective || mission.missionId}
        </span>
        {mission.awaitingApproval && (
          <span className="shrink-0 rounded-md border border-yellow-500/25 bg-yellow-500/10 px-1.5 py-0.5 text-[10px] font-medium text-yellow-300">
            待审批
          </span>
        )}
      </div>
      <div className="mt-1.5 flex min-w-0 items-center gap-2 text-[10px] text-gray-500">
        <SymbolCell symbol={mission.symbol} compact className="min-w-0" />
        <span className="shrink-0">· {mission.timeframe} · {stateLabel(mission.state)}</span>
      </div>
      <div className="mt-2 h-1.5 w-full rounded-full bg-crypto-bg">
        <div
          className={clsx('h-1.5 rounded-full transition-all duration-500', barTone)}
          style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
        />
      </div>
      <div className="mt-1.5 flex items-center justify-between text-[10px] text-gray-600">
        <span className="truncate">{badge?.currentLabel || '--'}</span>
        <span className="shrink-0 tabular-nums">
          {badge ? `${badge.stageIndex}/${badge.stageTotal}` : ''} · {percent.toFixed(0)}%
        </span>
      </div>
    </button>
  );
}

export default function ArcConsole() {
  const [config, setConfig] = useState<ArcConsoleConfig | null>(null);
  const [missions, setMissions] = useState<ArcMissionSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [progress, setProgress] = useState<ArcPipelineView | null>(null);
  const [progressAt, setProgressAt] = useState<number>(() => Date.now());
  const [tick, setTick] = useState(0);
  const [evidence, setEvidence] = useState<ArcEvidence | null>(null);
  const [detail, setDetail] = useState<ArcCandidateRow | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [objective, setObjective] = useState('在真实历史上寻找可过样本外门禁的趋势策略');
  const [symbol, setSymbol] = useState('ETH-USDT-SWAP');
  const [timeframe, setTimeframe] = useState('1H');
  const [maxCandidates, setMaxCandidates] = useState(12);
  const [reason, setReason] = useState('');
  const eventCountRef = useRef<number>(-1);

  const configured = Boolean(config?.configured);
  const unknowns = evidence?.approval.unknowns ?? [];
  const approveBlocked = unknowns.length > 0;
  const selected = missions.find((item) => item.missionId === selectedId) || null;

  const loadMissions = useCallback(async () => {
    const payload = await arcApi.listMissions({ limit: 50 });
    const rows = payload.missions || [];
    setMissions(rows);
    return rows;
  }, []);

  const loadEvidence = useCallback(async (missionId: string) => {
    setEvidence(await arcApi.getEvidence(missionId));
  }, []);

  /** Evidence is only re-read when the mission actually recorded something new. */
  const loadProgress = useCallback(
    async (missionId: string) => {
      const next = await arcApi.getProgress(missionId);
      setProgress(next);
      setProgressAt(Date.now());
      if (next.eventCount !== eventCountRef.current) {
        eventCountRef.current = next.eventCount;
        await loadEvidence(missionId);
      }
    },
    [loadEvidence],
  );

  const selectMission = useCallback(
    async (missionId: string) => {
      setSelectedId(missionId);
      setDetail(null);
      setProgress(null);
      setEvidence(null);
      setError('');
      eventCountRef.current = -1;
      try {
        await loadProgress(missionId);
      } catch (err) {
        setError(err instanceof Error ? err.message : '无法读取任务进度');
      }
    },
    [loadProgress],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const next = await arcApi.config();
        if (cancelled) return;
        setConfig(next);
        if (!next.configured) return;
        const rows = await loadMissions();
        // Landing on an empty detail pane hides the thing this page exists to show.
        if (!cancelled && rows.length > 0) await selectMission(rows[0].missionId);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : '无法读取 ARC 配置');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadMissions, selectMission]);

  const anyRunning = useMemo(() => missions.some(isRunning), [missions]);
  const selectionRunning = Boolean(progress && !progress.finished);
  const polling = configured && selectionRunning;

  useEffect(() => {
    if (!configured || !anyRunning) return undefined;
    const timer = window.setInterval(() => {
      void loadMissions().catch(() => undefined);
    }, MISSION_POLL_MS);
    return () => window.clearInterval(timer);
  }, [configured, anyRunning, loadMissions]);

  useEffect(() => {
    if (!configured || !selectedId || !selectionRunning) return undefined;
    const timer = window.setInterval(() => {
      void loadProgress(selectedId).catch(() => undefined);
    }, PROGRESS_POLL_MS);
    return () => window.clearInterval(timer);
  }, [configured, selectedId, selectionRunning, loadProgress]);

  // Keeps "更新于 N 秒前" moving between polls without re-reading the server.
  useEffect(() => {
    if (!progress) return undefined;
    const timer = window.setInterval(() => setTick((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [progress]);

  const freshSeconds = useMemo(() => {
    if (!progress) return 0;
    void tick;
    return progress.secondsSinceUpdate + (Date.now() - progressAt) / 1000;
  }, [progress, progressAt, tick]);

  async function refreshAll() {
    setRefreshing(true);
    setError('');
    try {
      await loadMissions();
      if (selectedId) await loadProgress(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : '刷新失败');
    } finally {
      setRefreshing(false);
    }
  }

  async function startMission() {
    setBusy(true);
    setError('');
    try {
      const created = await arcApi.createMission({ objective, symbol, timeframe, maxCandidates });
      const missionId = String(created.missionId || created.mission_id || '');
      await loadMissions();
      if (missionId) await selectMission(missionId);
    } catch (err) {
      setError(err instanceof Error ? err.message : '启动失败');
    } finally {
      setBusy(false);
    }
  }

  async function openCandidate(attemptId: string) {
    if (!selectedId) return;
    try {
      setDetail(await arcApi.getCandidate(selectedId, attemptId));
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法读取候选');
    }
  }

  async function decide(decision: 'approve' | 'reject') {
    if (!selectedId || (decision === 'approve' && approveBlocked)) return;
    setBusy(true);
    setError('');
    try {
      await arcApi.decide(selectedId, {
        decision,
        reason: reason || (decision === 'reject' ? '否决' : '批准接入实盘'),
      });
      await loadMissions();
      eventCountRef.current = -1;
      await loadProgress(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : '审批失败');
    } finally {
      setBusy(false);
    }
  }

  const survivors = selected?.survivorCount ?? 0;
  const candidateProgress = selected
    ? `${selected.progress.candidatesUsed}/${selected.progress.maxCandidates}`
    : '--';
  const paperStage = progress?.stages.find((item) => item.key === 'paper');
  // A KPI value has one line to say one thing, so the window's two legs are split
  // across value and sub rather than truncated into "13.4 / 2…" on a narrow screen.
  const paper = (paperStage?.metrics ?? {}) as {
    elapsedHours?: number;
    minHours?: number;
    trades?: number;
    minTrades?: number;
    instanceId?: string | null;
  };
  const paperRunning = Boolean(paper.instanceId);
  const activeIndex = progress?.stages.findIndex(
    (item) => item.status === 'active' || item.status === 'blocked',
  );

  return (
    <div className="h-full min-h-0 overflow-y-auto p-6">
      <div className="mb-5 rounded-xl border border-crypto-border bg-crypto-card px-4 py-3 shadow-inner shadow-black/10">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-blue-500/25 bg-blue-500/10 text-blue-300 shadow-inner shadow-blue-950/20">
                <Bot className="h-4 w-4" />
              </span>
              <h1 className="truncate text-xl font-bold leading-tight text-white">自主研究</h1>
              <span className="rounded-md border border-blue-500/20 bg-blue-500/10 px-2 py-1 text-[11px] font-medium text-blue-300">
                A股 ARC
              </span>
              <span className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-1 text-[11px] font-medium text-gray-500">
                仅管理员
              </span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
              <MetaChip
                icon={<Activity className="h-3 w-3 text-blue-300" />}
                label="任务"
                value={String(missions.length)}
              />
              <MetaChip
                icon={<Clock3 className="h-3 w-3 text-blue-300" />}
                label="更新"
                value={progress ? elapsedLabel(freshSeconds) : '--'}
              />
              <MetaChip
                icon={<ShieldCheck className="h-3 w-3" />}
                label="边界"
                value="Paper 晋级需人工审批"
                tone="blue"
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 xl:justify-end">
            <button
              type="button"
              onClick={() => void refreshAll()}
              disabled={!configured || refreshing}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-600/15 px-3 text-xs font-medium text-blue-300 shadow-inner shadow-blue-950/20 transition-colors hover:border-blue-400/50 hover:bg-blue-600/25 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <RefreshCw className={clsx('h-3.5 w-3.5', refreshing && 'animate-spin')} />
              刷新
            </button>
          </div>
        </div>
      </div>

      {!configured && config && (
        <div className="mb-4 flex items-start gap-2 rounded-xl border border-yellow-500/25 bg-yellow-500/[0.07] px-4 py-3 text-sm text-yellow-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            A 股 ARC 自主研究写入链路尚未配置。当前不会创建任务、回测或 Paper。
          </div>
        </div>
      )}

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <section className="mb-4 rounded-xl border border-crypto-border bg-crypto-card p-4">
        <SectionTitle icon={<Play className="h-4 w-4" />} title="启动研究" meta="A 股候选生成与门禁待接通" />
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_170px_110px_120px_140px]">
          <label className="min-w-0">
            <span className="mb-1.5 block text-[11px] font-medium text-gray-500">研究目标</span>
            <input
              className="h-9 w-full rounded-md border border-crypto-border bg-crypto-bg px-2.5 text-sm text-gray-200 transition-colors focus:border-blue-500/40 focus:outline-none disabled:opacity-50"
              value={objective}
              onChange={(event) => setObjective(event.target.value)}
              disabled={!configured}
            />
          </label>
          <label className="min-w-0">
            <span className="mb-1.5 block text-[11px] font-medium text-gray-500">标的</span>
            <input
              className="h-9 w-full rounded-md border border-crypto-border bg-crypto-bg px-2.5 text-sm text-gray-200 transition-colors focus:border-blue-500/40 focus:outline-none disabled:opacity-50"
              value={symbol}
              onChange={(event) => setSymbol(event.target.value)}
              disabled={!configured}
            />
          </label>
          <label className="min-w-0">
            <span className="mb-1.5 block text-[11px] font-medium text-gray-500">周期</span>
            <input
              className="h-9 w-full rounded-md border border-crypto-border bg-crypto-bg px-2.5 text-sm text-gray-200 transition-colors focus:border-blue-500/40 focus:outline-none disabled:opacity-50"
              value={timeframe}
              onChange={(event) => setTimeframe(event.target.value)}
              disabled={!configured}
            />
          </label>
          <label className="min-w-0">
            <span className="mb-1.5 block text-[11px] font-medium text-gray-500">候选预算</span>
            <input
              type="number"
              min={1}
              max={200}
              className="h-9 w-full rounded-md border border-crypto-border bg-crypto-bg px-2.5 text-sm tabular-nums text-gray-200 transition-colors focus:border-blue-500/40 focus:outline-none disabled:opacity-50"
              value={maxCandidates}
              onChange={(event) => setMaxCandidates(Number(event.target.value) || 1)}
              disabled={!configured}
            />
          </label>
          <div className="flex items-end">
            <button
              type="button"
              className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg border border-blue-500/30 bg-blue-600/15 px-3 text-xs font-medium text-blue-300 shadow-inner shadow-blue-950/20 transition-colors hover:border-blue-400/50 hover:bg-blue-600/25 disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => void startMission()}
              disabled={!configured || busy}
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              启动研究
            </button>
          </div>
        </div>
      </section>

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="当前阶段"
          value={progress ? (progress.finished ? '已上线' : stateLabel(progress.state)) : '--'}
          sub={
            progress
              ? progress.finished
                ? '七个阶段全部完成'
                : `第 ${(activeIndex ?? 0) + 1} / ${progress.stages.length} 阶段`
              : '未选择任务'
          }
          tone={progress?.blocked ? 'yellow' : progress?.finished ? 'emerald' : 'blue'}
        />
        <KpiCard
          label="总进度"
          value={progress ? `${progress.percent.toFixed(1)}%` : '--'}
          sub={progress ? `${progress.eventCount} 个事件 · 更新于 ${elapsedLabel(freshSeconds)}` : '未选择任务'}
          tone="blue"
        />
        <KpiCard
          label="候选 / 存活"
          value={selected ? `${candidateProgress} · ${survivors}` : '--'}
          sub={selected ? '已用候选预算与红队存活数' : '未选择任务'}
          tone={survivors > 0 ? 'emerald' : 'slate'}
        />
        <KpiCard
          label="模拟盘观察"
          value={
            !progress
              ? '--'
              : paperRunning
                ? `${(paper.elapsedHours ?? 0).toFixed(1)} / ${paper.minHours ?? 0} 小时`
                : '未启动'
          }
          sub={
            paperRunning
              ? `${paper.trades ?? 0} / ${paper.minTrades ?? 0} 笔成交`
              : '观察窗尚未开始'
          }
          tone={selected?.awaitingApproval ? 'yellow' : paperRunning ? 'blue' : 'slate'}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
        <section className="min-w-0 rounded-xl border border-crypto-border bg-crypto-card p-4">
          <SectionTitle
            icon={<Activity className="h-4 w-4" />}
            title="任务"
            meta={`${missions.length} 个`}
          />
          {missions.length === 0 ? (
            <EmptyState text={configured ? '还没有任务，先启动一次研究。' : '未配置上游，无法读取任务。'} />
          ) : (
            <div className="max-h-[560px] space-y-2 overflow-y-auto pr-0.5">
              {missions.map((mission) => (
                <MissionRow
                  key={mission.missionId}
                  mission={mission}
                  selected={mission.missionId === selectedId}
                  onSelect={() => void selectMission(mission.missionId)}
                />
              ))}
            </div>
          )}
        </section>

        <div className="min-w-0 space-y-4">
          {!selectedId ? (
            <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
              <EmptyState text="选择左侧任务查看流水线进度。" />
            </section>
          ) : !progress ? (
            <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
              <div className="flex min-h-48 items-center justify-center rounded-xl border border-dashed border-crypto-border bg-crypto-bg/40 text-sm text-gray-500">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                正在读取任务进度…
              </div>
            </section>
          ) : (
            <>
              <PipelinePanel progress={progress} freshSeconds={freshSeconds} polling={polling} />

              <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_360px]">
                <section className="min-w-0 rounded-xl border border-crypto-border bg-crypto-card p-4">
                  <SectionTitle
                    icon={<FlaskConical className="h-4 w-4" />}
                    title="候选证据"
                    meta={`${evidence?.candidates.length ?? 0} 个 · 点击看源码`}
                  />
                  {(evidence?.candidates.length ?? 0) === 0 ? (
                    <EmptyState text="该任务还没有产生候选。" />
                  ) : (
                    <div className="overflow-x-auto rounded-xl border border-crypto-border bg-crypto-bg/40">
                      <table className="min-w-full text-left text-xs">
                        <thead className="bg-crypto-bg text-[10px] uppercase text-gray-500">
                          <tr className="border-b border-crypto-border">
                            <th className="whitespace-nowrap px-3 py-2 font-semibold">族 / 方向</th>
                            <th className="whitespace-nowrap px-3 py-2 text-right font-semibold">
                              OOS Sharpe
                            </th>
                            <th className="whitespace-nowrap px-3 py-2 text-right font-semibold">
                              成交
                            </th>
                            <th className="whitespace-nowrap px-3 py-2 text-right font-semibold">
                              分折
                            </th>
                            <th className="whitespace-nowrap px-3 py-2 font-semibold">拒绝原因</th>
                          </tr>
                        </thead>
                        <tbody>
                          {evidence?.candidates.map((row) => (
                            <tr
                              key={row.attemptId}
                              onClick={() => void openCandidate(row.attemptId)}
                              className={clsx(
                                'cursor-pointer border-b border-crypto-border/70 transition-colors last:border-0 hover:bg-white/[0.025]',
                                detail?.attemptId === row.attemptId && 'bg-blue-500/[0.06]',
                              )}
                            >
                              <td className="px-3 py-2.5 font-medium text-gray-100">
                                {row.family || '--'} / {row.direction || '--'}
                              </td>
                              <td
                                className={clsx(
                                  'px-3 py-2.5 text-right font-semibold tabular-nums',
                                  (row.oosSharpe ?? 0) > 0 ? 'text-emerald-400' : 'text-gray-400',
                                )}
                              >
                                {formatNumber(row.oosSharpe)}
                              </td>
                              <td className="px-3 py-2.5 text-right tabular-nums text-gray-400">
                                {row.trades ?? '--'}
                              </td>
                              <td className="px-3 py-2.5 text-right tabular-nums text-gray-400">
                                {row.foldsPassed ?? '--'}/{row.foldsTotal ?? '--'}
                              </td>
                              <td className="max-w-[220px] truncate px-3 py-2.5 text-yellow-300/80">
                                {row.rejections.map((item) => item.code).join(', ') || '--'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {detail && (
                    <div className="mt-3 rounded-xl border border-crypto-border bg-crypto-bg/40">
                      <div className="flex items-center justify-between gap-2 px-3 py-2 text-[11px] text-gray-500">
                        <span className="truncate">
                          {detail.family} / {detail.direction} · {detail.attemptId}
                        </span>
                        <button
                          type="button"
                          className="shrink-0 rounded-md border border-crypto-border bg-crypto-bg px-2 py-1 text-[10px] font-medium text-gray-500 transition-colors hover:text-gray-200"
                          onClick={() => setDetail(null)}
                        >
                          收起
                        </button>
                      </div>
                      <pre className="max-h-72 overflow-auto border-t border-crypto-border px-3 py-2.5 text-[11px] leading-5 text-gray-400">
                        {detail.strategyCode}
                      </pre>
                    </div>
                  )}
                </section>

                <div className="min-w-0 space-y-4">
                  <ActivityFeed rows={progress.activity} />

                  <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
                    <SectionTitle icon={<ShieldCheck className="h-4 w-4" />} title="实盘审批" />
                    <dl className="grid grid-cols-2 gap-2">
                      {[
                        ['状态', evidence?.approval.status],
                        ['建议', evidence?.approval.recommendation],
                        ['策略', evidence?.promotion.bitproStrategyId],
                        ['回测', evidence?.promotion.bitproBacktestId],
                        ['校验', evidence?.promotion.validationId],
                        ['模拟盘', evidence?.promotion.paperInstanceId],
                      ].map(([label, value]) => (
                        <div
                          key={String(label)}
                          className="min-w-0 rounded-lg border border-crypto-border bg-crypto-bg/40 px-2.5 py-2"
                        >
                          <dt className="text-[10px] text-gray-600">{label}</dt>
                          <dd className="mt-0.5 truncate text-[11px] font-medium text-gray-300">
                            {value || '--'}
                          </dd>
                        </div>
                      ))}
                    </dl>
                    {unknowns.length > 0 && (
                      <ul className="mt-3 space-y-1 rounded-xl border border-yellow-500/25 bg-yellow-500/[0.07] p-2.5 text-[11px] leading-snug text-yellow-200">
                        {unknowns.map((item) => (
                          <li key={item} className="flex items-start gap-1.5">
                            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                            {unknownLabel(item)}
                          </li>
                        ))}
                      </ul>
                    )}
                    <textarea
                      className="mt-3 w-full resize-none rounded-md border border-crypto-border bg-crypto-bg px-2.5 py-2 text-xs text-gray-200 transition-colors focus:border-blue-500/40 focus:outline-none"
                      rows={2}
                      placeholder="审批理由（写入审计记录）"
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                    />
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      <button
                        type="button"
                        className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-600/15 text-xs font-medium text-emerald-300 shadow-inner shadow-emerald-950/20 transition-colors hover:border-emerald-400/50 hover:bg-emerald-600/25 disabled:cursor-not-allowed disabled:opacity-40"
                        disabled={approveBlocked || busy || !evidence}
                        title={approveBlocked ? '证据仍有缺口，不能批准' : undefined}
                        onClick={() => void decide('approve')}
                      >
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        批准实盘
                      </button>
                      <button
                        type="button"
                        className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-rose-500/30 bg-rose-600/15 text-xs font-medium text-rose-300 shadow-inner shadow-rose-950/20 transition-colors hover:border-rose-400/50 hover:bg-rose-600/25 disabled:cursor-not-allowed disabled:opacity-40"
                        disabled={busy || !evidence}
                        onClick={() => void decide('reject')}
                      >
                        <XCircle className="h-3.5 w-3.5" />
                        否决
                      </button>
                    </div>
                    <p className="mt-2 text-[10px] leading-snug text-gray-600">
                      审批由已验证的管理员会话签名，操作人取自会话而不是页面输入。
                      {selected?.createdBy ? ` 任务由 ${selected.createdBy} 创建。` : ''}
                    </p>
                  </section>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
