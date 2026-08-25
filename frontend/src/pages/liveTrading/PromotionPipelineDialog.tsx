import clsx from 'clsx';
import {
  CheckCircle2,
  Circle,
  Clock3,
  Loader2,
  Rocket,
  ShieldAlert,
  XCircle,
} from 'lucide-react';

export type PromotionPipelinePhase =
  | 'preflight'
  | 'awaiting_confirmation'
  | 'deploying'
  | 'success'
  | 'error';

export type PromotionPipelineCheck = {
  item: string;
  passed: boolean;
  detail?: string | null;
  account?: PromotionPipelineAccount | null;
};

export type PromotionPipelineAccount = {
  freeUsdt?: number | null;
  totalUsdt?: number | null;
  usedUsdt?: number | null;
  exchange?: string;
  currency?: string;
};

export type PromotionPipelineState = {
  phase: PromotionPipelinePhase;
  sourceId: number;
  strategyName: string;
  exchange: string;
  trialEquity?: number | null;
  loopInterval: number;
  account?: PromotionPipelineAccount | null;
  riskConfig: {
    riskPerTradePct: number;
    maxDailyLossPct: number;
    maxTotalLossPct: number;
  };
  checks: PromotionPipelineCheck[];
  error?: string;
  failedAt?: 'preflight' | 'deploy';
  liveStrategyId?: number;
};

type StepStatus = 'pending' | 'running' | 'waiting' | 'success' | 'error';

type Step = {
  key: 'match' | 'connectivity' | 'funds' | 'confirm' | 'deploy' | 'monitor';
  label: string;
  detail: string;
  tone: 'blue' | 'yellow' | 'green' | 'purple' | 'orange' | 'cyan';
};

const STEPS: Step[] = [
  {
    key: 'match',
    label: '策略匹配',
    detail: '来源模拟 / 交易范围 / 风控频率',
    tone: 'blue',
  },
  {
    key: 'connectivity',
    label: '实盘连通',
    detail: 'OKX 行情、K 线、交易规则、订单簿',
    tone: 'yellow',
  },
  {
    key: 'funds',
    label: '资金检查',
    detail: '真实 USDT、最小下单、单笔名义',
    tone: 'green',
  },
  {
    key: 'confirm',
    label: '人工确认',
    detail: '确认后才进入真实交易路径',
    tone: 'purple',
  },
  {
    key: 'deploy',
    label: '克隆并启动',
    detail: '复跑预检、写入实盘记录、启动 LiveBroker',
    tone: 'orange',
  },
  {
    key: 'monitor',
    label: '进入监控',
    detail: '切换到独立实盘实例详情',
    tone: 'cyan',
  },
];

function includesAny(value: string, patterns: string[]) {
  return patterns.some((pattern) => value.includes(pattern));
}

function groupStatus(checks: PromotionPipelineCheck[], group: 'match' | 'connectivity' | 'funds'): StepStatus {
  const patterns =
    group === 'match'
      ? [
          '来源策略',
          '真实交易路径',
          '策略交易对',
          '策略运行合约',
          '重复实盘',
          '小资金风控',
          '调度频率',
        ]
      : group === 'connectivity'
        ? ['行情连接', 'K 线拉取', '交易规则', '订单簿', '全局风控熔断', '实盘未成交挂单']
        : ['USDT 余额', '实盘最小下单资金', '订单名义金额'];
  const items = checks.filter((check) => includesAny(check.item, patterns));
  if (items.length === 0) return 'pending';
  return items.every((check) => check.passed) ? 'success' : 'error';
}

function stepStatus(state: PromotionPipelineState, key: Step['key']): StepStatus {
  const { phase, checks, failedAt } = state;
  if (phase === 'error') {
    if (failedAt === 'preflight') {
      if (key === 'match' || key === 'connectivity' || key === 'funds') {
        return groupStatus(checks, key);
      }
      return 'pending';
    }
    if (failedAt === 'deploy') {
      if (key === 'match' || key === 'connectivity' || key === 'funds' || key === 'confirm') {
        return 'success';
      }
      if (key === 'deploy') return 'error';
      return 'pending';
    }
    return key === 'match' ? 'error' : 'pending';
  }
  if (phase === 'preflight') {
    return key === 'match' ? 'running' : 'pending';
  }
  if (phase === 'awaiting_confirmation') {
    if (key === 'match' || key === 'connectivity' || key === 'funds') return 'success';
    return key === 'confirm' ? 'waiting' : 'pending';
  }
  if (phase === 'deploying') {
    if (key === 'match' || key === 'connectivity' || key === 'funds' || key === 'confirm') {
      return 'success';
    }
    return key === 'deploy' ? 'running' : 'pending';
  }
  return 'success';
}

function StepIcon({ status }: { status: StepStatus }) {
  if (status === 'success') return <CheckCircle2 className="h-4 w-4 text-emerald-300" />;
  if (status === 'error') return <XCircle className="h-4 w-4 text-red-300" />;
  if (status === 'running') return <Loader2 className="h-4 w-4 animate-spin text-amber-300" />;
  if (status === 'waiting') return <Clock3 className="h-4 w-4 text-blue-300" />;
  return <Circle className="h-4 w-4 text-slate-600" />;
}

function phaseTitle(phase: PromotionPipelinePhase) {
  if (phase === 'preflight') return '正在执行实盘前检查';
  if (phase === 'awaiting_confirmation') return '实盘前检查通过';
  if (phase === 'deploying') return '正在部署到实盘';
  if (phase === 'success') return '实盘部署已启动';
  return '部署流程已停止';
}

function phaseHint(state: PromotionPipelineState) {
  if (state.phase === 'preflight') return '正在确认策略与真实账户是否匹配；当前不会创建实盘策略。';
  if (state.phase === 'awaiting_confirmation') return '确认后会克隆独立实盘记录，并立即启动真实下单路径。';
  if (state.phase === 'deploying') return '后端正在复跑预检、创建实盘策略记录并启动 LiveBroker。';
  if (state.phase === 'success') return '已切换到实盘实例监控，后续以详情页运行状态为准。';
  return state.error || '检查或部署未通过，未启动真实交易。';
}

function statusPill(status: StepStatus) {
  if (status === 'success') return '已完成';
  if (status === 'running') return '进行中';
  if (status === 'waiting') return '待确认';
  if (status === 'error') return '未通过';
  return '等待';
}

function toneClasses(tone: Step['tone'], status: StepStatus) {
  const active = status === 'success' || status === 'running' || status === 'waiting';
  const tones = {
    blue: active
      ? 'border-blue-500/60 bg-blue-950/35 text-blue-200'
      : 'border-slate-700 bg-slate-950/40 text-slate-500',
    yellow: active
      ? 'border-yellow-500/60 bg-yellow-950/25 text-yellow-200'
      : 'border-slate-700 bg-slate-950/40 text-slate-500',
    green: active
      ? 'border-emerald-500/60 bg-emerald-950/30 text-emerald-200'
      : 'border-slate-700 bg-slate-950/40 text-slate-500',
    purple: active
      ? 'border-purple-500/60 bg-purple-950/30 text-purple-200'
      : 'border-slate-700 bg-slate-950/40 text-slate-500',
    orange: active
      ? 'border-orange-500/60 bg-orange-950/25 text-orange-200'
      : 'border-slate-700 bg-slate-950/40 text-slate-500',
    cyan: active
      ? 'border-cyan-500/60 bg-cyan-950/25 text-cyan-200'
      : 'border-slate-700 bg-slate-950/40 text-slate-500',
  };
  if (status === 'error') return 'border-red-500/70 bg-red-950/30 text-red-200';
  return tones[tone];
}

function formatUsdt(value?: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '检测中';
  return `${value.toFixed(2)} USDT`;
}

export default function PromotionPipelineDialog({
  state,
  onCancel,
  onConfirm,
  onClose,
}: {
  state: PromotionPipelineState;
  onCancel: () => void;
  onConfirm: () => void | Promise<void>;
  onClose: () => void;
}) {
  const busy = state.phase === 'preflight' || state.phase === 'deploying';
  const canConfirm = state.phase === 'awaiting_confirmation';
  const canClose = state.phase === 'success' || state.phase === 'error';
  const account = state.account;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/75 p-4 backdrop-blur-[2px]">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="promotion-pipeline-title"
        className="w-full max-w-5xl overflow-hidden rounded-2xl border border-red-500/30 bg-[#0d1422] shadow-2xl shadow-black/60"
      >
        <div className="border-b border-red-500/25 bg-gradient-to-r from-red-950/60 via-slate-950 to-slate-900 px-6 py-5">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-red-500/15 text-red-300">
              <ShieldAlert className="h-5 w-5" aria-hidden />
            </div>
            <div className="min-w-0">
              <h3 id="promotion-pipeline-title" className="text-lg font-semibold text-white">
                {phaseTitle(state.phase)}
              </h3>
              <p className="mt-1 text-sm leading-relaxed text-slate-300">{phaseHint(state)}</p>
            </div>
          </div>
        </div>

        <div className="space-y-5 px-6 py-5">
          <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
            <div className="rounded-xl border border-slate-700/70 bg-slate-950/45 px-3 py-2">
              <div className="text-slate-500">来源策略</div>
              <div className="mt-1 truncate font-semibold text-slate-100">#{state.sourceId}</div>
            </div>
            <div className="rounded-xl border border-slate-700/70 bg-slate-950/45 px-3 py-2">
              <div className="text-slate-500">交易所</div>
              <div className="mt-1 font-semibold text-slate-100">{state.exchange.toUpperCase()}</div>
            </div>
            <div className="rounded-xl border border-slate-700/70 bg-slate-950/45 px-3 py-2">
              <div className="text-slate-500">实盘可用资金</div>
              <div className="mt-1 font-semibold text-slate-100">
                {formatUsdt(account?.freeUsdt ?? state.trialEquity)}
              </div>
            </div>
            <div className="rounded-xl border border-slate-700/70 bg-slate-950/45 px-3 py-2">
              <div className="text-slate-500">账户总额</div>
              <div className="mt-1 font-semibold text-red-200">{formatUsdt(account?.totalUsdt)}</div>
            </div>
          </div>

          <div className="overflow-x-auto pb-1">
            <div className="grid min-w-[960px] grid-cols-6 gap-3">
              {STEPS.map((step) => {
                const status = stepStatus(state, step.key);
                return (
                  <div
                    key={step.key}
                    className={clsx(
                      'min-h-[118px] rounded-2xl border px-4 py-3 shadow-lg shadow-black/10',
                      toneClasses(step.tone, status),
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div
                        className={clsx(
                          'flex h-9 w-9 items-center justify-center rounded-full border bg-black/20',
                          status === 'success' && 'border-emerald-400/40 bg-emerald-500/10',
                          status === 'error' && 'border-red-400/50 bg-red-500/10',
                          status === 'running' && 'border-amber-400/50 bg-amber-500/10',
                          status === 'waiting' && 'border-blue-400/50 bg-blue-500/10',
                          status === 'pending' && 'border-slate-700 bg-slate-900/70',
                        )}
                      >
                        <StepIcon status={status} />
                      </div>
                      <span
                        className={clsx(
                          'shrink-0 rounded-full bg-black/25 px-2 py-0.5 text-[10px] font-bold',
                          status === 'pending' && 'text-slate-500',
                        )}
                      >
                        {statusPill(status)}
                      </span>
                    </div>
                    <div className="mt-3 text-base font-bold">{step.label}</div>
                    <div className="mt-1 text-xs leading-relaxed opacity-75">{step.detail}</div>
                  </div>
                );
              })}
            </div>
          </div>

          {state.checks.length > 0 && (
            <div className="max-h-48 overflow-auto rounded-xl border border-slate-700/70 bg-slate-950/50 p-3">
              <div className="mb-2 text-xs font-semibold text-slate-400">检查结果</div>
              <div className="space-y-2">
                {state.checks.map((check, index) => (
                  <div key={`${check.item}-${index}`} className="flex items-start gap-2 text-xs">
                    {check.passed ? (
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-300" />
                    ) : (
                      <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-300" />
                    )}
                    <div className="min-w-0">
                      <span className="font-semibold text-slate-200">{check.item}</span>
                      {check.detail && (
                        <span className="ml-1 break-words text-slate-500">{check.detail}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-3 border-t border-slate-800 px-6 pb-5 pt-4">
          {canConfirm && (
            <>
              <button
                type="button"
                onClick={onCancel}
                className="rounded-full border border-slate-600 bg-slate-800 px-5 py-2.5 text-sm font-semibold text-slate-200 transition-colors hover:bg-slate-700"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void onConfirm()}
                className="inline-flex items-center gap-2 rounded-full bg-red-600 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-red-700"
              >
                <Rocket className="h-4 w-4" />
                确认部署实盘
              </button>
            </>
          )}
          {busy && (
            <button
              type="button"
              disabled
              className="inline-flex cursor-not-allowed items-center gap-2 rounded-full bg-slate-800 px-5 py-2.5 text-sm font-semibold text-slate-400"
            >
              <Loader2 className="h-4 w-4 animate-spin" />
              {state.phase === 'preflight' ? '检查中' : '部署中'}
            </button>
          )}
          {canClose && (
            <button
              type="button"
              onClick={onClose}
              className={clsx(
                'rounded-full px-5 py-2.5 text-sm font-semibold text-white transition-colors',
                state.phase === 'success'
                  ? 'bg-blue-600 hover:bg-blue-700'
                  : 'bg-slate-700 hover:bg-slate-600',
              )}
            >
              {state.phase === 'success' ? '进入实盘监控' : '我知道了'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
