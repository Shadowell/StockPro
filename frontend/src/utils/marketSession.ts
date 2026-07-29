/** A-share market session clock helpers (Asia/Shanghai wall clock). */

export type MarketSessionPhase =
  | 'pre_open'
  | 'auction'
  | 'open'
  | 'lunch'
  | 'closed'
  | 'weekend';

export type MarketSessionState = {
  phase: MarketSessionPhase;
  label: string;
  detail: string;
  isOpen: boolean;
  localTime: string;
};

const PHASE_LABEL: Record<MarketSessionPhase, string> = {
  pre_open: '盘前',
  auction: '竞价中',
  open: '开盘中',
  lunch: '午休',
  closed: '已收盘',
  weekend: '休市',
};

const PHASE_DETAIL: Record<MarketSessionPhase, string> = {
  pre_open: '未开盘',
  auction: '集合竞价 / 开盘准备',
  open: '连续竞价',
  lunch: '午间休市',
  closed: '今日已收盘',
  weekend: '周末休市',
};

export function shanghaiNow(date = new Date()): Date {
  return new Date(date.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }));
}

export function resolveMarketSession(date = new Date()): MarketSessionState {
  const local = shanghaiNow(date);
  const weekday = local.getDay(); // 0 Sun … 6 Sat
  const minutes = local.getHours() * 60 + local.getMinutes();
  const localTime = `${String(local.getHours()).padStart(2, '0')}:${String(local.getMinutes()).padStart(2, '0')}`;

  let phase: MarketSessionPhase;
  if (weekday === 0 || weekday === 6) {
    phase = 'weekend';
  } else if (minutes < 9 * 60 + 15) {
    phase = 'pre_open';
  } else if (minutes < 9 * 60 + 30) {
    phase = 'auction';
  } else if (minutes <= 11 * 60 + 30) {
    phase = 'open';
  } else if (minutes < 13 * 60) {
    phase = 'lunch';
  } else if (minutes <= 15 * 60) {
    phase = 'open';
  } else {
    phase = 'closed';
  }

  return {
    phase,
    label: PHASE_LABEL[phase],
    detail: PHASE_DETAIL[phase],
    isOpen: phase === 'open',
    localTime,
  };
}

export function sessionFromOverview(overview?: {
  session_phase?: string | null;
  session_label?: string | null;
  session_detail?: string | null;
  session_local_time?: string | null;
  is_open?: boolean;
} | null): MarketSessionState | null {
  if (!overview?.session_phase) return null;
  const phase = overview.session_phase as MarketSessionPhase;
  if (!PHASE_LABEL[phase]) return null;
  return {
    phase,
    label: overview.session_label || PHASE_LABEL[phase],
    detail: overview.session_detail || PHASE_DETAIL[phase],
    isOpen: Boolean(overview.is_open ?? phase === 'open'),
    localTime: overview.session_local_time || resolveMarketSession().localTime,
  };
}
