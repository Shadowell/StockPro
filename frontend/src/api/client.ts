import axios, { type AxiosError, type AxiosRequestConfig } from 'axios';
import type {
  Ticker,
  Kline,
  TechnicalIndicators,
  OrderBook,
  FundingRate,
  FundingOpportunity,
  Strategy,
} from '../types';

const API_BASE = '/api/v2';

/** 默认 REST 超时（秒） */
const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * 批量/自定义数据同步：后端在单次 HTTP 内顺序拉取 K 线（1m + 长区间可达数万～数十万根），
 * 必须显著大于默认 30s，否则会误报「启动失败: timeout」而任务实际仍在跑或刚失败。
 */
const DATA_SYNC_LONG_TIMEOUT_MS = 3_600_000; // 60 分钟

/**
 * POST /backtest/run_sync：Backtrader 整条链路跑完才返回；含 Kairos 时每根 bar 可能触发推理，
 * 1m + 长日期区间极易超过默认 30s。
 */
const BACKTEST_RUN_SYNC_TIMEOUT_MS = 3_600_000; // 60 分钟

const api = axios.create({
  baseURL: API_BASE,
  timeout: DEFAULT_TIMEOUT_MS,
  withCredentials: true,
});

function extractApiErrorDetail(data: unknown): unknown {
  if (!data) return undefined;
  if (typeof data === 'string') return data.slice(0, 500);
  if (typeof data !== 'object') return data;

  const record = data as Record<string, unknown>;
  if (record.detail != null) return record.detail;
  if (record.message != null) return record.message;
  if (record.error && typeof record.error === 'object' && !Array.isArray(record.error)) {
    const error = record.error as Record<string, unknown>;
    return error.detail ?? error.message ?? error.code ?? record.error;
  }
  return record.error ?? data;
}

function describeApiError(error: AxiosError | Error | unknown): Record<string, unknown> {
  if (axios.isAxiosError(error)) {
    const method = String(error.config?.method || 'GET').toUpperCase();
    const baseURL = error.config?.baseURL || '';
    const url = error.config?.url || '';

    return {
      method,
      url: `${baseURL}${url}`,
      status: error.response?.status,
      code: error.code,
      message: error.message,
      detail: extractApiErrorDetail(error.response?.data),
    };
  }

  if (error instanceof Error) {
    return {
      message: error.message,
      name: error.name,
    };
  }

  return {
    message: String(error),
  };
}

/**
 * Convert backend errors into a bounded, display-safe string.
 * Provider endpoints may return either a plain detail string or a structured
 * `{code, error_code, message}` detail object; callers must never put that
 * object directly into React string state.
 */
export function parseApiError(error: unknown, fallback = '请求失败'): string {
  const errorRecord = error && typeof error === 'object' && !Array.isArray(error)
    ? error as Record<string, unknown>
    : undefined;
  const responseRecord = errorRecord?.response && typeof errorRecord.response === 'object' && !Array.isArray(errorRecord.response)
    ? errorRecord.response as Record<string, unknown>
    : undefined;
  const root = (axios.isAxiosError(error) ? error.response?.data : responseRecord?.data) ?? error;
  const rootRecord = root && typeof root === 'object' && !Array.isArray(root)
    ? root as Record<string, unknown>
    : undefined;
  const detail = rootRecord?.detail;
  const detailRecord = detail && typeof detail === 'object' && !Array.isArray(detail)
    ? detail as Record<string, unknown>
    : undefined;
  const structured = detailRecord || rootRecord;
  const codeValue = structured?.error_code ?? structured?.code;
  const messageValue = detailRecord?.message
    ?? (typeof detail === 'string' ? detail : undefined)
    ?? rootRecord?.message
    ?? (error instanceof Error ? error.message : undefined);
  const message = typeof messageValue === 'string' && messageValue.trim() ? messageValue.trim() : fallback;
  const code = typeof codeValue === 'string' && codeValue.trim() ? codeValue.trim() : '';
  const sanitized = `${message}${code ? `（${code}）` : ''}`
    .replace(/(?:sk|xai|api)[-_][A-Za-z0-9_-]{8,}/gi, '[已脱敏]')
    .replace(/([A-Za-z0-9+/]{24,}={0,2})/g, '[已脱敏]')
    .slice(0, 320);
  return sanitized || fallback;
}

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (axios.isCancel(error) || (axios.isAxiosError(error) && error.code === 'ERR_CANCELED')) {
      return Promise.reject(error);
    }
    if (axios.isAxiosError(error) && error.response?.data) {
      const detail = extractApiErrorDetail(error.response.data);
      if (
        detail != null &&
        typeof error.response.data === 'object' &&
        !Array.isArray(error.response.data) &&
        (error.response.data as Record<string, unknown>).detail == null
      ) {
        (error.response.data as Record<string, unknown>).detail = detail;
      }
    }
    console.error('API Error:', describeApiError(error));
    return Promise.reject(error);
  }
);

function snakeToCamel(input: string): string {
  return input.replace(/_([a-z])/g, (_, s: string) => s.toUpperCase());
}

function camelToSnake(input: string): string {
  return input.replace(/[A-Z]/g, (s) => `_${s.toLowerCase()}`);
}

function camelizeDeep<T = any>(value: any): T {
  if (Array.isArray(value)) {
    return value.map((item) => camelizeDeep(item)) as T;
  }
  if (value && typeof value === 'object') {
    return Object.entries(value).reduce((acc, [key, val]) => {
      acc[snakeToCamel(key)] = camelizeDeep(val);
      return acc;
    }, {} as Record<string, any>) as T;
  }
  return value as T;
}

function snakifyDeep<T = any>(value: any): T {
  if (Array.isArray(value)) {
    return value.map((item) => snakifyDeep(item)) as T;
  }
  if (value && typeof value === 'object' && !(value instanceof FormData)) {
    return Object.entries(value).reduce((acc, [key, val]) => {
      acc[camelToSnake(key)] = snakifyDeep(val);
      return acc;
    }, {} as Record<string, any>) as T;
  }
  return value as T;
}

function unwrapEnvelope(raw: any): any {
  if (raw && typeof raw === 'object' && 'success' in raw && 'data' in raw) {
    return raw.data;
  }
  return raw;
}

export type AuthRole = 'admin' | 'guest' | null;

export interface AuthSession {
  authEnabled: boolean;
  authenticated: boolean;
  role: AuthRole;
  permissions: string[];
  expiresAt?: string;
  sessionId?: string;
  guestCodeId?: number;
  maxBacktestsPerDay?: number;
  maxConcurrentBacktests?: number;
  maxBacktestDays?: number;
}

export interface GuestAccessCode {
  id: number;
  note: string;
  expiresAt: string;
  maxBacktestsPerDay: number;
  maxConcurrentBacktests: number;
  maxBacktestDays: number;
  createdBy?: string;
  createdAt?: string;
  lastUsedAt?: string | null;
  revokedAt?: string | null;
}

export interface CreatedGuestAccessCode extends GuestAccessCode {
  code: string;
}

export interface GuestCodeCreateInput {
  note?: string;
  expiresInMinutes?: number;
  maxBacktestsPerDay?: number;
  maxConcurrentBacktests?: number;
  maxBacktestDays?: number;
}

async function getReq<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const normalized = config ? { ...config, params: snakifyDeep(config.params) } : undefined;
  const raw = await api.get(url, normalized);
  return camelizeDeep<T>(unwrapEnvelope(raw));
}

type PageMeta = { total: number; offset: number; limit: number };

async function getPagedReq<T>(url: string, config?: AxiosRequestConfig): Promise<{ data: T; meta?: PageMeta }> {
  const normalized = config ? { ...config, params: snakifyDeep(config.params) } : undefined;
  const raw = await api.get(url, normalized);
  const meta = raw && typeof raw === 'object' ? (raw as { meta?: PageMeta }).meta : undefined;
  return camelizeDeep({ data: unwrapEnvelope(raw), meta });
}

async function postReq<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const normalized = config ? { ...config, params: snakifyDeep(config.params) } : undefined;
  const raw = await api.post(url, snakifyDeep(data), normalized);
  return camelizeDeep<T>(unwrapEnvelope(raw));
}

async function putReq<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const normalized = config ? { ...config, params: snakifyDeep(config.params) } : undefined;
  const raw = await api.put(url, snakifyDeep(data), normalized);
  return camelizeDeep<T>(unwrapEnvelope(raw));
}

async function patchReq<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const normalized = config ? { ...config, params: snakifyDeep(config.params) } : undefined;
  const raw = await api.patch(url, snakifyDeep(data), normalized);
  return camelizeDeep<T>(unwrapEnvelope(raw));
}

async function deleteReq<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const normalized = config ? { ...config, params: snakifyDeep(config.params) } : undefined;
  const raw = await api.delete(url, normalized);
  return camelizeDeep<T>(unwrapEnvelope(raw));
}

export type ArcConsoleConfig = {
  configured: boolean;
  baseUrlSet: boolean;
  tokenSet: boolean;
  signingSecretSet: boolean;
};

export type ArcPipelineBadge = {
  currentStage: string | null;
  currentLabel: string;
  stageIndex: number;
  stageTotal: number;
  percent: number;
  blocked: boolean;
  finished: boolean;
};

export type ArcMissionSummary = {
  missionId: string;
  state: string;
  objective: string;
  symbol: string;
  timeframe: string;
  createdBy?: string;
  createdAt?: string;
  updatedAt?: string;
  progress: { candidatesUsed: number; maxCandidates: number };
  awaitingApproval: boolean;
  survivorCount?: number;
  pipeline?: ArcPipelineBadge;
};

export type ArcStageStatus = 'done' | 'active' | 'blocked' | 'pending';

export type ArcPipelineStage = {
  key: string;
  label: string;
  status: ArcStageStatus;
  detail: string;
  metrics: Record<string, unknown>;
};

export type ArcActivityRow = {
  eventId: string;
  type: string;
  label: string;
  at: string;
  detail: Record<string, string | number | boolean>;
};

export type ArcPipelineView = {
  missionId: string;
  state: string;
  stages: ArcPipelineStage[];
  currentStage: string | null;
  blocked: boolean;
  blockedReason: { reason: string; message: string; missing: string[]; at: string } | null;
  finished: boolean;
  percent: number;
  updatedAt: string;
  secondsSinceUpdate: number;
  eventCount: number;
  activity: ArcActivityRow[];
};

export type ArcRejection = { code: string; text: string };

export type ArcCandidateRow = {
  attemptId: string;
  candidateId: string;
  state: string;
  family: string;
  direction: string;
  oosSharpe: number | null;
  trades: number | null;
  winRate: number | null;
  foldsPassed: number | null;
  foldsTotal: number | null;
  rankingBasis: string | null;
  rejections: ArcRejection[];
  strategyCode?: string;
  strategySpec?: Record<string, unknown>;
  reflexionEvents?: Record<string, unknown>[];
  hypothesis?: string;
};

export type ArcEvidence = {
  mission: ArcMissionSummary;
  candidates: ArcCandidateRow[];
  promotion: {
    bitproStrategyId?: string | null;
    bitproBacktestId?: string | null;
    validationId?: string | null;
    paperInstanceId?: string | null;
    selfTest?: Record<string, unknown> | null;
    paperObservation?: Record<string, unknown>;
  };
  approval: {
    status: string | null;
    unknowns: string[];
    recommendation?: string | null;
    packageHash?: string | null;
  };
};

/** HyperTrade ARC 只经由 BitPro 服务端代理，浏览器不持有令牌或签名密钥。 */
export const arcApi = {
  config: () => getReq<ArcConsoleConfig>('/arc/config'),
  listMissions: (params?: { state?: string; limit?: number }) =>
    getReq<{ missions: ArcMissionSummary[] }>('/arc/missions', { params }),
  createMission: (payload: {
    objective: string;
    symbol: string;
    timeframe: string;
    maxCandidates: number;
  }) => postReq<Record<string, unknown>>('/arc/missions', payload),
  getProgress: (missionId: string) => getReq<ArcPipelineView>(`/arc/missions/${missionId}/progress`),
  getEvidence: (missionId: string) => getReq<ArcEvidence>(`/arc/missions/${missionId}/evidence`),
  getCandidate: (missionId: string, attemptId: string) =>
    getReq<ArcCandidateRow>(`/arc/missions/${missionId}/candidates/${attemptId}`),
  decide: (missionId: string, payload: { decision: 'approve' | 'reject'; reason: string }) =>
    postReq<Record<string, unknown>>(`/arc/missions/${missionId}/decide`, payload),
};

/** HyperTrade 研究机构流程只经由 BitPro 服务端代理，浏览器不持有上游配置或凭据。 */
export const researchWorkbenchApi = {
  summary: () => getReq<Record<string, any>>('/research-workbench/summary'),
  candidates: () => getReq<{ items: Record<string, any>[]; reportErrors?: string[] }>('/research-workbench/candidates'),
  createMandate: (payload: Record<string, any>) => postReq<Record<string, any>>('/research-workbench/mandates', payload),
  pauseMandate: (mandateId: string, payload: Record<string, any>) => postReq<Record<string, any>>(`/research-workbench/mandates/${mandateId}/pause`, payload),
  resumeMandate: (mandateId: string, payload: Record<string, any>) => postReq<Record<string, any>>(`/research-workbench/mandates/${mandateId}/resume`, payload),
  draftStrategySpec: (mandateId: string, payload: Record<string, any>) => postReq<Record<string, any>>(`/research-workbench/mandates/${mandateId}/strategy-specs/draft`, payload),
  createJob: (mandateId: string, payload: Record<string, any>) => postReq<Record<string, any>>(`/research-workbench/mandates/${mandateId}/jobs`, payload),
  runJob: (jobId: string, payload: Record<string, any>) => postReq<Record<string, any>>(`/research-workbench/jobs/${jobId}/run`, payload),
  cancelJob: (jobId: string, payload: Record<string, any>) => postReq<Record<string, any>>(`/research-workbench/jobs/${jobId}/cancel`, payload),
  requestPaperPromotion: (payload: Record<string, any>) => postReq<Record<string, any>>('/research-workbench/paper-promotions', payload),
  approvePaperPromotion: (promotionId: string, payload: Record<string, any>) => postReq<Record<string, any>>(`/research-workbench/paper-promotions/${promotionId}/approve`, payload),
  observePaperPromotion: (promotionId: string, payload: Record<string, any>) => postReq<Record<string, any>>(`/research-workbench/paper-promotions/${promotionId}/observe`, payload),
  samplePaperObservations: (payload: Record<string, any>) => postReq<Record<string, any>>('/research-workbench/paper-observations/sample', payload),
  portfolioReview: () => getReq<Record<string, any>>('/research-workbench/portfolio-review'),
};

// ============================================
// 认证 API
// ============================================

export const authApi = {
  me: (): Promise<AuthSession> => getReq('/auth/me'),

  adminLogin: (username: string, password: string): Promise<AuthSession> =>
    postReq('/auth/admin/login', { username, password }),

  guestLogin: (code: string): Promise<AuthSession> =>
    postReq('/auth/guest/login', { code }),

  logout: (): Promise<{ loggedOut: boolean }> => postReq('/auth/logout'),

  listGuestCodes: (): Promise<{ items: GuestAccessCode[] }> =>
    getReq('/auth/guest-codes'),

  createGuestCode: (data: GuestCodeCreateInput): Promise<CreatedGuestAccessCode> =>
    postReq('/auth/guest-codes', data),

  revokeGuestCode: (codeId: number): Promise<{ id: number; revokedAt: string }> =>
    deleteReq(`/auth/guest-codes/${codeId}`),
};

// ============================================
// 信号中心 API
// ============================================

export interface SignalDelivery {
  id: number;
  signalId: number;
  channelId: number;
  status: 'pending' | 'approved' | 'sent' | 'failed' | 'expired' | 'canceled';
  requestPayload?: Record<string, unknown>;
  responseStatus?: number | null;
  responseBody?: string | null;
  error?: string | null;
  attempts: number;
  approvedAt?: string | null;
  sentAt?: string | null;
  updatedAt: string;
}

export interface StrategySignal {
  id: number;
  signalUid: string;
  strategyId: number;
  strategyName?: string;
  symbol: string;
  okxInstId: string;
  marketType: 'swap';
  action: 'ENTER_LONG' | 'ENTER_SHORT' | 'EXIT_LONG' | 'EXIT_SHORT';
  price: number;
  suggestedInvestmentType: 'margin' | 'percentage_balance' | 'percentage_position';
  suggestedAmount: number;
  reason?: string;
  confidence?: string;
  riskNote?: string;
  status: 'pending_approval' | 'sent' | 'failed' | 'expired' | 'canceled';
  rawContext?: Record<string, unknown>;
  okxPayloadPreview: Record<string, unknown>;
  deliveries?: SignalDelivery[];
  createdAt: string;
  expiresAt: string;
  updatedAt: string;
}

export interface SignalChannel {
  id: number;
  name: string;
  enabled: boolean;
  webhookUrl?: string;
  maskedWebhookUrl: string;
  maskedSignalToken: string;
  allowedStrategyIds: number[];
  allowedSymbols: string[];
  allowedActions: string[];
  maxMarginUsdt?: number | null;
  maxLagSec: number;
  createdAt: string;
  updatedAt: string;
}

export interface SignalStrategySetting {
  strategyId: number;
  strategyName: string;
  signalEnabled: boolean;
  manualApprovalRequired: boolean;
  status?: string;
  exchange?: string;
  symbols?: string[];
  marketType?: string;
  totalPnl?: number | null;
  returnPct?: number | null;
  updatedAt?: string | null;
}

export interface SignalChannelInput {
  name: string;
  webhookUrl: string;
  signalToken: string;
  enabled?: boolean;
  allowedStrategyIds?: number[];
  allowedSymbols?: string[];
  allowedActions?: string[];
  maxMarginUsdt?: number | null;
  maxLagSec?: number;
}

export interface SignalChannelTestInput {
  send?: boolean;
  action?: string;
  instrument?: string;
  investmentType?: string;
  amount?: number;
}

export interface SignalChannelTestResult {
  status: 'dry_run' | 'sent' | 'failed';
  payload?: Record<string, unknown>;
  responseStatus?: number | null;
  responseBody?: string | null;
  channel?: SignalChannel;
}

export const signalCenterApi = {
  listSignals: (params?: {
    status?: string;
    strategyId?: number;
    channelId?: number;
    limit?: number;
  }): Promise<{ signals: StrategySignal[] }> => getReq('/signals', { params }),

  approveSignal: (signalId: number, channelIds: number[]): Promise<StrategySignal> =>
    postReq(`/signals/${signalId}/approve`, { channelIds }),

  cancelSignal: (signalId: number): Promise<StrategySignal> =>
    postReq(`/signals/${signalId}/cancel`),

  retrySignal: (signalId: number): Promise<StrategySignal> =>
    postReq(`/signals/${signalId}/retry`),

  listChannels: (): Promise<{ channels: SignalChannel[] }> => getReq('/signal-channels'),

  listSignalStrategies: (): Promise<{ strategies: SignalStrategySetting[] }> =>
    getReq('/signal-strategies'),

  setStrategySignalEnabled: (
    strategyId: number,
    enabled: boolean
  ): Promise<{ strategy: SignalStrategySetting }> =>
    putReq(`/signal-strategies/${strategyId}`, { enabled }),

  updateSignalStrategySettings: (
    strategyId: number,
    payload: { enabled?: boolean; manualApprovalRequired?: boolean }
  ): Promise<{ strategy: SignalStrategySetting }> =>
    putReq(`/signal-strategies/${strategyId}`, payload),

  createChannel: (payload: SignalChannelInput): Promise<{ channel: SignalChannel }> =>
    postReq('/signal-channels', payload),

  updateChannel: (
    channelId: number,
    payload: Partial<SignalChannelInput>
  ): Promise<{ channel: SignalChannel }> =>
    putReq(`/signal-channels/${channelId}`, payload),

  deleteChannel: (
    channelId: number
  ): Promise<{ deleted: boolean; channelId: number; channelName: string; canceledDeliveries: number }> =>
    deleteReq(`/signal-channels/${channelId}`),

  testChannel: (
    channelId: number,
    payload: SignalChannelTestInput = {}
  ): Promise<SignalChannelTestResult> =>
    postReq(`/signal-channels/${channelId}/test`, { send: false, ...payload }),
};

// ============================================
// 实盘工作台 API
// ============================================

export interface LiveExecutionStrategy {
  strategyId: number;
  strategyName: string;
  added: boolean;
  deployable: boolean;
  deployed: boolean;
  liveSubscriptionId?: number | null;
  deploymentStrategyId?: number | null;
  deploymentStrategyName?: string | null;
  deploymentStatus?: string | null;
  status?: string;
  workspaceStatus?: string;
  exchange?: string;
  accountId?: string;
  accountIds?: string[];
  accountBindings?: LiveExecutionAccountBinding[];
  symbols?: string[];
  tradeSymbols?: string[];
  marketType?: string;
  riskConfig?: Record<string, unknown>;
  totalPnl?: number | null;
  returnPct?: number | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface LiveExecutionAccountBinding {
  accountId: string;
  accountName?: string;
  exchange?: string;
  exchangeAlias?: string;
  maskedApiKey?: string | null;
  testnet?: boolean;
  added: boolean;
  deployed: boolean;
  liveSubscriptionId?: number | null;
  deploymentStrategyId?: number | null;
  deploymentStatus?: string | null;
  status?: string | null;
  riskConfig?: Record<string, unknown>;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface LiveExecutionPreflightCheck {
  item: string;
  passed: boolean;
  detail?: string | null;
  account?: Record<string, unknown> | null;
}

export interface LiveExecutionPreflight {
  allPassed: boolean;
  checks: LiveExecutionPreflightCheck[];
  plan?: Record<string, unknown>;
  account?: Record<string, unknown> | null;
}

export interface LiveExecutionOrder {
  id?: string;
  clientOrderId?: string | null;
  instrumentId?: string | null;
  instrumentType?: string | null;
  symbol?: string;
  side?: string;
  positionSide?: string | null;
  positionDirection?: string | null;
  positionEffect?: string | null;
  reduceOnly?: boolean | null;
  tdMode?: string | null;
  type?: string;
  price?: number | null;
  average?: number | null;
  amount?: number | null;
  filled?: number | null;
  remaining?: number | null;
  fillPrice?: number | null;
  fillSize?: number | null;
  fillTimestamp?: number | null;
  fillDatetime?: string | null;
  tradeId?: string | null;
  createdTimestamp?: number | null;
  createdDatetime?: string | null;
  updatedTimestamp?: number | null;
  updatedDatetime?: string | null;
  status?: string | null;
  rawStatus?: string | null;
  timestamp?: number | null;
  datetime?: string | null;
  fee?: number | string | { cost?: number | string | null; currency?: string | null; fee?: number | string | null } | null;
  feeCurrency?: string | null;
  feeCost?: number | string | null;
  fee_cost?: number | string | null;
  feeCcy?: string | null;
  pnl?: number | string | null;
  realizedPnl?: number | string | null;
  realized_pnl?: number | string | null;
  fillPnl?: number | string | null;
  fill_pnl?: number | string | null;
  rebate?: number | null;
  rebateCurrency?: string | null;
  bitproSource?: 'strategy' | 'external';
  bitproSourceLabel?: string | null;
  sourceStrategyId?: number | null;
  sourceStrategyName?: string | null;
  subscriptionId?: number | null;
  signalEventId?: number | null;
  liveExecutionId?: number | null;
  error?: string | null;
  failureLog?: Record<string, unknown> | null;
  source?: string;
  info?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface LiveExecutionPosition {
  symbol?: string;
  currency?: string;
  assetType?: string;
  side?: string;
  posSide?: string;
  amount?: number;
  free?: number;
  used?: number;
  contracts?: number;
  contractSize?: number | null;
  baseAmount?: number | null;
  notional?: number;
  notionalUsdt?: number;
  margin?: number | null;
  initialMargin?: number | null;
  maintenanceMargin?: number | null;
  marginRatio?: number | null;
  marginMode?: string | null;
  leverage?: number | string | null;
  percentage?: number | null;
  unrealizedPnlPct?: number | null;
  unrealizedPnl?: number;
  markPrice?: number;
  entryPrice?: number;
  liquidationPrice?: number;
  [key: string]: unknown;
}

export interface LivePositionCloseResult {
  accountId: string;
  exchange: string;
  closed: number;
  results: Record<string, unknown>[];
}

export interface LiveExecutionAccount {
  accountId: string;
  name: string;
  exchange: string;
  exchangeAlias: string;
  maskedApiKey?: string | null;
  displayOnly?: boolean;
  canTrade?: boolean | null;
  permissionCheckedAt?: string | null;
  permissionCheckDetail?: string | null;
  isDefault: boolean;
  configured: boolean;
  enabled: boolean;
  testnet: boolean;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface LiveExecutionAccountReturnRates {
  oneDay?: number | null;
  sevenDay?: number | null;
  thirtyDay?: number | null;
  source?: string | null;
  valuationUsd?: number | null;
  method?: string | null;
  error?: string | null;
}

export interface LiveAccountCreateInput {
  name: string;
  exchange?: 'okx' | 'binanceusdm';
  apiKey: string;
  apiSecret: string;
  passphrase?: string;
  testnet?: boolean;
}

export const liveExecutionApi = {
  listAccounts: (): Promise<{ accounts: LiveExecutionAccount[] }> =>
    getReq('/live/accounts'),

  createAccount: (payload: LiveAccountCreateInput): Promise<{ account: LiveExecutionAccount }> =>
    postReq('/live/accounts', payload),

  getAccountBalance: (
    accountId = 'default'
  ): Promise<{ accountId: string; exchange: string; balance: any[] }> =>
    getReq(`/live/accounts/${accountId}/balance`),

  getAccountBalanceDetail: (
    accountId = 'default'
  ): Promise<{
    accountId: string;
    exchange: string;
    trading: any[];
    funding: any[];
    returnRates?: LiveExecutionAccountReturnRates | null;
  }> =>
    getReq(`/live/accounts/${accountId}/balance/detail`),

  listStrategies: (): Promise<{ strategies: LiveExecutionStrategy[] }> =>
    getReq('/live/strategies'),

  updateStrategy: (
    strategyId: number,
    payload: { added?: boolean; accountId?: string; bindAccount?: boolean; riskConfig?: Record<string, unknown> }
  ): Promise<{ strategy: LiveExecutionStrategy }> =>
    api.patch(`/live/strategies/${strategyId}`, snakifyDeep(payload)).then((raw) =>
      camelizeDeep(unwrapEnvelope(raw.data))
    ),

  preflightStrategy: (
    strategyId: number,
    payload: {
      accountId?: string;
      exchange?: string;
      initialEquity?: number;
      loopInterval?: number;
      startImmediately?: boolean;
      riskConfig?: Record<string, unknown>;
    }
  ): Promise<{ strategy: LiveExecutionStrategy; preflight: LiveExecutionPreflight }> =>
    postReq(`/live/strategies/${strategyId}/preflight`, payload),

  deployStrategy: (
    strategyId: number,
    payload: {
      accountId?: string;
      exchange?: string;
      initialEquity?: number;
      loopInterval?: number;
      startImmediately?: boolean;
      confirmPaperReviewed: boolean;
      confirmLiveRisk: boolean;
      riskConfig?: Record<string, unknown>;
    }
  ): Promise<{
    deployed: boolean;
    started: boolean;
    sourceStrategyId: number;
    liveStrategyId?: number | null;
    liveSubscriptionId?: number | null;
    strategy: LiveExecutionStrategy;
    preflight: LiveExecutionPreflight;
  }> =>
    postReq(`/live/strategies/${strategyId}/deploy`, payload),

  enableStrategyAccount: (
    strategyId: number,
    payload: {
      accountId?: string;
      exchange?: string;
      initialEquity?: number;
      loopInterval?: number;
      confirmPaperReviewed: boolean;
      confirmLiveRisk: boolean;
      riskConfig?: Record<string, unknown>;
    }
  ): Promise<{
    deployed: boolean;
    started: boolean;
    sourceStrategyId: number;
    liveStrategyId?: number | null;
    liveSubscriptionId?: number | null;
    strategy: LiveExecutionStrategy;
    preflight: LiveExecutionPreflight;
  }> =>
    postReq(`/live/strategies/${strategyId}/enable-account`, payload),

  pauseStrategy: (
    strategyId: number,
    payload: { accountId?: string } = {}
  ): Promise<{ paused: boolean; sourceStrategyId: number; liveSubscriptionId?: number | null; strategy: LiveExecutionStrategy }> =>
    postReq(`/live/strategies/${strategyId}/pause`, payload),

  resumeStrategy: (
    strategyId: number,
    payload: { accountId?: string } = {}
  ): Promise<{ resumed: boolean; sourceStrategyId: number; liveSubscriptionId?: number | null; strategy: LiveExecutionStrategy }> =>
    postReq(`/live/strategies/${strategyId}/resume`, payload),

  stopStrategy: (
    strategyId: number,
    payload: { accountId?: string } = {}
  ): Promise<{ stopped: boolean; sourceStrategyId: number; liveSubscriptionId?: number | null; strategy: LiveExecutionStrategy }> =>
    postReq(`/live/strategies/${strategyId}/stop`, payload),

  listPositions: (
    accountId = 'default',
    symbol?: string
  ): Promise<{ accountId: string; exchange: string; positions: LiveExecutionPosition[] }> =>
    getReq(`/live/accounts/${accountId}/positions`, { params: { symbol } }),

  closePosition: (
    accountId = 'default',
    payload: { symbol?: string; side?: 'long' | 'short'; closeAll?: boolean; confirmLiveRisk: boolean }
  ): Promise<LivePositionCloseResult> =>
    postReq(`/live/accounts/${accountId}/positions/close`, payload),

  listOpenOrders: (
    accountId = 'default',
    symbol?: string
  ): Promise<{ accountId: string; exchange: string; orders: LiveExecutionOrder[] }> =>
    getReq(`/live/accounts/${accountId}/orders/open`, { params: { symbol } }),

  listOrderHistory: (
    accountId = 'default',
    symbol?: string,
    limit = 50
  ): Promise<{ accountId: string; exchange: string; orders: LiveExecutionOrder[] }> =>
    getReq(`/live/accounts/${accountId}/orders/history`, { params: { symbol, limit } }),
};

// ============================================
// 跨交易所套利 API
// ============================================

export interface ArbitrageLeg {
  exchange: string;
  side?: string;
  price?: number | null;
  fundingRate?: number | null;
}

export interface ArbitrageOpportunity {
  symbol: string;
  strategyType?: string;
  longLeg?: ArbitrageLeg | null;
  shortLeg?: ArbitrageLeg | null;
  grossEdgeBps?: number | null;
  feeBps?: number | null;
  slippageBps?: number | null;
  fundingEdgeBps?: number | null;
  netEdgeBps?: number | null;
  depthUsdt?: number | null;
  estimatedMarginUsdt?: number | null;
  reason?: string | null;
}

export interface ArbitrageSummary {
  status: string;
  asOf?: string;
  configuredExchanges: Array<Record<string, unknown>>;
  opportunities: ArbitrageOpportunity[];
  spreadMatrix: Array<Record<string, unknown>>;
  fundingRankings: Array<Record<string, unknown>>;
  portfolioPositions: Array<Record<string, unknown>>;
  legStatus: Array<Record<string, unknown>>;
  netExposure: { totalUsdt?: number; bySymbol?: Array<Record<string, unknown>> };
  pnl: {
    estimatedUsdt?: number;
    actualUsdt?: number;
    fundingUsdt?: number;
    spreadUsdt?: number;
    feeUsdt?: number;
  };
  emptyReason?: string;
}

export const arbitrageApi = {
  getSummary: (): Promise<ArbitrageSummary> =>
    getReq('/arbitrage/summary'),
};

// ============================================
// 链上研究 API
// ============================================

export interface OnchainKpiTarget {
  name: string;
  tvlUsd?: number;
  total24hUsd?: number;
  category?: string;
  chain?: string;
}

export interface OnchainSummary {
  status: string;
  asOf?: string;
  source: {
    provider: string;
    authRequired: boolean;
    endpoints: Record<string, string>;
  };
  sourceStatus: Record<string, string>;
  kpis: {
    totalTvlUsd: number;
    totalStablecoinsUsd: number;
    protocolCount: number;
    chainCount: number;
    fee24hUsd: number;
    stableYieldPoolCount: number;
    topChain?: OnchainKpiTarget | null;
    topProtocol?: OnchainKpiTarget | null;
    topFeeProtocol?: OnchainKpiTarget | null;
  };
  chains: Array<Record<string, unknown>>;
  protocols: Array<Record<string, unknown>>;
  fees: Array<Record<string, unknown>>;
  stablecoins: Array<Record<string, unknown>>;
  stablecoinChains: Array<Record<string, unknown>>;
  yieldPools: Array<Record<string, unknown>>;
  warnings: string[];
  emptyReason?: string;
}

export const onchainApi = {
  getSummary: (): Promise<OnchainSummary> =>
    getReq('/onchain/summary'),
};

// ============================================
// FactorLab 因子库与机器学习研究 API
// ============================================

export interface FactorLabDefinition {
  definitionId: string;
  definitionVersion: number;
  displayName: string;
  family: string;
  role: string;
  description: string;
  kernelName: string;
  inputs: string[];
  parameterSchema: Record<string, { type: string; default?: number; minimum?: number; maximum?: number }>;
  lookbackBars: number;
  availability: string;
  orientation: string;
  missingPolicy: string;
  validMin?: number | null;
  validMax?: number | null;
  implementationHash: string;
  status: string;
  metadata: Record<string, unknown>;
}

export interface FactorLabInstance {
  instanceId: string;
  definitionId: string;
  definitionVersion: number;
  parametersJson: string;
  parameters: Record<string, number>;
  parameterHash: string;
  requiredBars: number;
  createdAt: string;
  isDefault: boolean;
}

export interface FactorLabLatestValue {
  exchange: string;
  marketType: string;
  symbol: string;
  timeframe: string;
  instanceId: string;
  eventTime: number;
  availableAt: number;
  computedAt: number;
  value?: number | null;
  valueStatus: string;
  datasetRevision: string;
}

export interface FactorLabSummary {
  status: string;
  phase: string;
  statistics: {
    definitionCount: number;
    instanceCount: number;
    latestValueCount: number;
    materializedPartitionCount: number;
    researchTaskCount: number;
    trialCount: number;
  };
  definitions: FactorLabDefinition[];
  instances: FactorLabInstance[];
  latestValues: FactorLabLatestValue[];
  dataPlane: {
    format: string;
    layout: string;
    manifest: string;
  };
  capabilities: {
    apiMode: string;
    materializationStoreReady: boolean;
    researchMetricsAvailable: boolean;
    strategyRuntimeConnected: boolean;
    paperLiveConnected: boolean;
  };
}

export interface MarketPhase {
  tradeDate?: string | null;
  phase: string;
  status: string;
  confidence: number;
  reasons: string[];
  missingInputs: string[];
  definitionVersion: string;
  availableAt?: string | null;
  knowledgeCutoffAt?: string | null;
  sourceSnapshotId?: number | null;
}

export interface SectorRpsRow {
  tradeDate: string;
  classificationSystem: 'industry' | 'concept';
  sectorCode: string;
  sectorName: string;
  strengthScore?: number | null;
  rpsPercentile?: number | null;
  rank?: number | null;
  rankChange?: number | null;
  strongDays?: number | null;
  memberCoverage?: number | null;
  leaderSymbol?: string | null;
  leaderContributionPct?: number | null;
  memberCount?: number | null;
  return5d?: number | null;
  return10d?: number | null;
  return20d?: number | null;
  return60d?: number | null;
  amountChangePct?: number | null;
  upRatio?: number | null;
  limitUpCount?: number | null;
  sourceSnapshotId?: number | null;
  availableAt?: string | null;
  knowledgeCutoffAt?: string | null;
  status: string;
  missingInputs: string[];
}

export interface MarketSentiment {
  tradeDate?: string | null;
  status: string;
  limitUpCount?: number | null;
  limitDownCount?: number | null;
  failedLimitCount?: number | null;
  oneWordLimitCount?: number | null;
  sealRatePct?: number | null;
  highestStreak?: number | null;
  ladderWidth?: number | null;
  promotionRatePct?: number | null;
  ladderCompletenessPct?: number | null;
  weakMarketVeto: boolean;
  ladder: Array<{
    height: number;
    count: number;
    leaderSymbol?: string | null;
    symbols: string[];
    amountCny?: number | null;
  }>;
  priceLimitCoverage?: number | null;
  missingInputs: string[];
  sourceSnapshotId?: number | null;
  definitionVersion?: string;
  availableAt?: string | null;
  knowledgeCutoffAt?: string | null;
  ordersCreated: number;
  paperMutated: boolean;
}

export interface MarketTimelineRow {
  tradeDate: string;
  phase: string;
  phaseStatus: string;
  confidence?: number | null;
  reasons: string[];
  phaseMissingInputs: string[];
  sentimentStatus: string;
  limitUpCount?: number | null;
  limitDownCount?: number | null;
  failedLimitCount?: number | null;
  oneWordLimitCount?: number | null;
  sealRatePct?: number | null;
  highestStreak?: number | null;
  ladderWidth?: number | null;
  promotionRatePct?: number | null;
  ladderCompletenessPct?: number | null;
  weakMarketVeto?: boolean | null;
  priceLimitCoverage?: number | null;
  sourceSnapshotId?: number | null;
  phaseSnapshotId?: number | null;
  sentimentSnapshotId?: number | null;
  snapshotConsistent: boolean;
  availableAt?: string | null;
  knowledgeCutoffAt?: string | null;
}

export interface MarketTimelinePayload {
  items: MarketTimelineRow[];
  dataStatus: string;
  unavailableReason?: string | null;
  limit: number;
  writesPerformed: boolean;
  paperMutated: boolean;
}

export interface SectorRpsPayload {
  items: SectorRpsRow[];
  dataStatus: string;
  unavailableReason?: string | null;
  definitionVersion?: string;
}

export interface SectorMember {
  tradeDate: string;
  classificationSystem: 'industry' | 'concept';
  sectorCode: string;
  sectorName: string;
  symbol: string;
  name?: string | null;
  board?: string | null;
  sourceSnapshotId?: number | null;
  source: string;
  membershipBias: string;
  availableAt?: string | null;
}

export interface SectorMembersPayload {
  items: SectorMember[];
  total: number;
  dataStatus: string;
  unavailableReason?: string | null;
  tradeDate?: string | null;
  sourceSnapshotId?: number | null;
  membershipBias?: string | null;
}

export interface SymbolAbnormality {
  symbol: string;
  name?: string | null;
  board?: string | null;
  st?: boolean;
  tradeDate?: string | null;
  return3d?: number | null;
  return10d?: number | null;
  return30d?: number | null;
  benchmarkDeviation3d?: number | null;
  sectorDeviation3d?: number | null;
  amountRatio5d?: number | null;
  distanceTo60dHighPct?: number | null;
  distanceTo60dLowPct?: number | null;
  tags?: string[];
  status?: string;
  dataStatus?: string;
  abnormalStatus?: 'triggered' | 'edge' | 'watch' | null;
  maxCloseness?: number | null;
  eligible?: boolean;
  thresholds?: Record<string, { up: number; down: number }>;
  windows?: Record<string, {
    value?: number | null;
    valuePct?: number | null;
    threshold?: number | null;
    thresholdPct?: number | null;
    closeness?: number | null;
    direction?: 'up' | 'down' | 'flat' | string;
    status?: 'triggered' | 'edge' | 'watch' | string;
  }>;
  sourceSnapshotId?: number | null;
  benchmarkCode?: string | null;
  sectorCode?: string | null;
  missingInputs?: string[];
  unavailableReason?: string;
}

export interface MarketEvent {
  eventId: string;
  source: 'strategy' | 'signal' | 'price' | 'abnormal' | 'sector' | string;
  severity: 'info' | 'warning' | 'critical' | string;
  symbol?: string | null;
  name?: string | null;
  price?: number | null;
  changePercent?: number | null;
  ruleId?: string | null;
  ruleName?: string | null;
  message: string;
  sourceObjectType: string;
  sourceObjectId: string;
  evidence?: Record<string, unknown>;
  ordersCreated: number;
  paperMutated?: boolean;
  triggeredAt?: string | null;
}

export interface MarketEventsPayload {
  events: MarketEvent[];
  dataStatus: string;
  unavailableReason?: string | null;
  ordersCreated: number;
  paperMutated?: boolean;
  limit?: number;
}

export type MarketOverviewStatus = 'ready' | 'partial' | 'blocked' | 'stale' | 'empty' | 'error';

export interface MarketOverviewEvidence {
  tradeDate?: string | null;
  dataMode?: string | null;
  provider?: string | null;
  sourceSnapshotId?: number | null;
  availableAt?: string | null;
  knowledgeCutoffAt?: string | null;
  lastSuccessAt?: string | null;
  dataAgeSeconds?: number | null;
  status: MarketOverviewStatus | string;
  dataStatus?: MarketOverviewStatus | string;
  missingInputs: string[];
}

export interface MarketOverviewIndex {
  symbol: string;
  code: string;
  name: string;
  assetClass: 'index' | string;
  exchange: string;
  price?: number | null;
  changePercent?: number | null;
  changeAmount?: number | null;
  tradeDate?: string | null;
  source?: string | null;
  sourceSnapshotId?: number | null;
  availableAt?: string | null;
  status: MarketOverviewStatus | string;
}

export interface MarketOverviewModule extends MarketOverviewEvidence {
  definitionVersion?: string;
}

export interface MarketOverviewIndices extends MarketOverviewModule {
  items: MarketOverviewIndex[];
  requiredCount: number;
  availableCount: number;
  denominator: string;
}

export interface MarketOverviewBreadth extends MarketOverviewModule {
  universeCount: number;
  eligibleCount: number;
  excludedCount: number;
  excludedReasons: Record<string, number>;
  gainers: number;
  losers: number;
  flat: number;
  advanceRatioPct?: number | null;
  strongCount: number;
  weakCount: number;
  meanChangePct?: number | null;
  medianChangePct?: number | null;
  strongMoveThresholdPct: number;
  denominator: string;
}

export interface MarketOverviewDistributionBucket {
  key: string;
  label: string;
  count?: number | null;
  percentage?: number | null;
}

export interface MarketOverviewDistribution extends MarketOverviewModule {
  buckets: MarketOverviewDistributionBucket[];
  totalCount?: number | null;
  boundaryDefinition: string;
  denominator: string;
}

export interface MarketOverviewTrendMetric {
  count?: number | null;
  percentage?: number | null;
}

export interface MarketOverviewTrend extends MarketOverviewModule {
  requiredHistoryDays: number;
  availableHistoryDays: number;
  totalSymbols: number;
  coveredSymbols: number;
  denominator: string;
  aboveMa5: MarketOverviewTrendMetric;
  aboveMa20: MarketOverviewTrendMetric;
  aboveMa60: MarketOverviewTrendMetric;
  newHigh60d?: MarketOverviewTrendMetric;
  newLow60d?: MarketOverviewTrendMetric;
  newHigh_60d?: MarketOverviewTrendMetric;
  newLow_60d?: MarketOverviewTrendMetric;
  newHighLowRatio?: number | null;
}

export interface MarketOverviewActivity extends MarketOverviewModule {
  totalAmountCny?: number | null;
  averageAmountCny?: number | null;
  amountUnit: string;
  amountDenominator: string;
  averageTurnoverRatePct?: number | null;
  turnoverUnit: string;
  turnoverDenominator: string;
  highTurnoverCount?: number | null;
  highTurnoverThresholdPct: number;
  averageVolumeRatio?: number | null;
  volumeRatioUnit: string;
  volumeRatioDenominator: string;
  volumeExpansionCount?: number | null;
  volumeRatioThreshold: number;
  amount: {
    totalCny?: number | null;
    averageCny?: number | null;
    unit: string;
    denominator: string;
  };
  turnover: {
    averageRatePct?: number | null;
    highCount?: number | null;
    unit: string;
    thresholdPct: number;
  };
  volumeRatio: {
    average?: number | null;
    expansionCount?: number | null;
    unit: string;
    threshold: number;
    denominator: string;
  };
}

export interface MarketOverviewRankingItem {
  symbol: string;
  name: string;
  exchange: string;
  price?: number | null;
  changePercent?: number | null;
  amountCny?: number | null;
  turnoverRatePct?: number | null;
  volumeRatio?: number | null;
  tradeDate?: string | null;
  source?: string | null;
  sourceUpdatedAt?: string | null;
}

export interface MarketOverviewRankings extends MarketOverviewModule {
  limit: number;
  topGainers: MarketOverviewRankingItem[];
  topLosers: MarketOverviewRankingItem[];
  turnoverLeaders: MarketOverviewRankingItem[];
  activeLeaders: MarketOverviewRankingItem[];
}

export interface MarketOverview extends MarketOverviewEvidence {
  definitionVersion: string;
  evidence: MarketOverviewEvidence;
  indices: MarketOverviewIndices;
  breadth: MarketOverviewBreadth;
  distribution: MarketOverviewDistribution;
  trend: MarketOverviewTrend;
  activity: MarketOverviewActivity;
  amount: {
    status: MarketOverviewStatus | string;
    totalCny?: number | null;
    averageCny?: number | null;
    unit: string;
    denominator: string;
  };
  rankings: MarketOverviewRankings;
  topGainers: MarketOverviewRankingItem[];
  topLosers: MarketOverviewRankingItem[];
  turnoverLeaders: MarketOverviewRankingItem[];
  activeLeaders: MarketOverviewRankingItem[];
}

export interface MarketHomeDashboardEvidence extends MarketOverviewEvidence {
  consistencyWarnings?: string[];
  observedTradeDates?: Record<string, string>;
  observedSnapshotIds?: Record<string, number>;
  providerCalls: number;
  writesPerformed: boolean;
  paperMutated: boolean;
}

export interface MarketHomeDashboard {
  evidence: MarketHomeDashboardEvidence;
  overview: MarketOverview;
  phase: MarketPhase;
  sentiment: MarketSentiment;
  industryRps: SectorRpsPayload;
  conceptRps: SectorRpsPayload;
  movers: { items: SymbolAbnormality[]; dataStatus: string; unavailableReason?: string | null };
  events: MarketEventsPayload;
  dataStatus: string;
  providerCalls: number;
  writesPerformed: boolean;
  paperMutated: boolean;
}

export type FactorResearchMode = 'manual' | 'auto' | 'hybrid';
export type FactorResearchStatus = 'queued' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled';

export interface FactorResearchCombinationInput {
  hypothesis: string;
  expression: Record<string, unknown>;
}

export interface FactorResearchTaskInput {
  exchange: string;
  marketType: 'stock' | 'etf';
  symbols: string[];
  timeframe: string;
  startMs: number;
  endMs: number;
  mode: FactorResearchMode;
  factorInstanceIds: string[];
  manualCombinations: FactorResearchCombinationInput[];
  providerKey?: string;
  model?: string;
  reasoningEffort?: string;
  speedMode?: string;
  horizonBars: number;
  baseCostBps: number;
  stressCostBps: number;
  minCoverage: number;
  nSplits: number;
  maxCandidates: number;
  maxRuntimeSec: number;
  maxNoImprovement: number;
  maxCombinationLeaves: number;
  targetAcceptedCandidates: number;
  randomSeed: number;
}

export interface FactorResearchTask {
  taskId: string;
  status: FactorResearchStatus;
  mode: FactorResearchMode;
  exchange: string;
  marketType: 'stock' | 'etf';
  symbols: string[];
  timeframe: string;
  startMs: number;
  endMs: number;
  factorInstanceIds: string[];
  manualCombinationCount: number;
  providerKey: string;
  model: string;
  reasoningEffort: string;
  speedMode: string;
  horizonBars: number;
  baseCostBps: number;
  stressCostBps: number;
  nSplits: number;
  maxCandidates: number;
  maxRuntimeSec: number;
  maxNoImprovement: number;
  maxCombinationLeaves: number;
  targetAcceptedCandidates: number;
  datasetSnapshotId?: string | null;
  trialCursor: number;
  bestTrialId?: string | null;
  stopReason?: string | null;
  archivedAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface FactorResearchTrial {
  trialId: string;
  taskId: string;
  ordinal: number;
  semanticHash: string;
  modelType: 'equal_weight' | 'ridge' | 'logistic' | string;
  featureIds: string[];
  parameters: {
    hypothesis?: string;
    source?: string;
    combination?: Record<string, unknown>;
  };
  status: 'completed' | 'rejected' | 'failed';
  metrics: {
    coverage?: number;
    foldCount?: number;
    totalReturn?: number;
    stressTotalReturn?: number;
    baselineTotalReturn?: number;
    profitFactor?: number;
    maxDrawdown?: number;
    profitableFoldRatio?: number;
    symbolConcentration?: number;
    directionalAccuracy?: number;
    score?: number;
    accepted?: boolean;
  };
  hardGateFailures: string[];
  createdAt: string;
}

export const factorLabApi = {
  getSummary: (): Promise<FactorLabSummary> =>
    getReq('/factorlab/summary'),
  createResearchTask: (payload: FactorResearchTaskInput): Promise<FactorResearchTask> =>
    postReq('/factorlab/research/tasks', payload),
  listResearchTasks: (): Promise<FactorResearchTask[]> =>
    getReq('/factorlab/research/tasks'),
  getResearchTask: (taskId: string): Promise<FactorResearchTask> =>
    getReq(`/factorlab/research/tasks/${taskId}`),
  listResearchTrials: (taskId: string): Promise<FactorResearchTrial[]> =>
    getReq(`/factorlab/research/tasks/${taskId}/trials`),
  pauseResearchTask: (taskId: string): Promise<FactorResearchTask> =>
    postReq(`/factorlab/research/tasks/${taskId}/pause`),
  resumeResearchTask: (taskId: string): Promise<FactorResearchTask> =>
    postReq(`/factorlab/research/tasks/${taskId}/resume`),
  deleteResearchTask: (taskId: string): Promise<FactorResearchTask> =>
    deleteReq(`/factorlab/research/tasks/${taskId}`),
};

// ============================================
// 复盘中心 API
// ============================================

export type ReviewWindow = '24h' | '7d' | '30d';
export type ReviewBucket = '1h';

export interface ReviewOverview {
  reviewWindow: ReviewWindow;
  bucket: ReviewBucket;
  updatedAt?: string | null;
  strategyCount: number;
  sampleStrategyCount: number;
  overallReturnPct: number;
  medianReturnPct: number;
  maxDrawdownPct: number;
  observeCount: number;
  reviewCount: number;
  sampleHealthPct: number;
}

export interface ReviewGroupRow {
  groupKey: string;
  assetClass: string;
  timeframe: string;
  strategyType: string;
  capitalVersion: string;
  strategyCount: number;
  sampleStrategyCount: number;
  returnPct: number;
  maxDrawdownPct: number;
  winRate: number;
  profitFactor: number;
  tradeCount: number;
  score: number;
  verdict: string;
  strategies: ReviewGroupStrategy[];
}

export interface ReviewGroupStrategy {
  strategyId: number;
  name: string;
  score: number;
  returnPct: number;
  maxDrawdownPct: number;
  winRate: number;
  profitFactor: number;
  tradeCount: number;
  sampleCount: number;
  tags: string[];
  verdict: string;
}

export interface ReviewLeaderboardItem {
  strategyId: number;
  name: string;
  groupKey: string;
  score: number;
  returnPct: number;
  maxDrawdownPct: number;
  winRate: number;
  profitFactor: number;
  tradeCount: number;
  tags: string[];
  verdict: string;
}

export interface ReviewHeatmapBucket {
  hour: string;
  returnPct: number;
  tone: 'positive' | 'negative' | 'flat' | string;
}

export interface ReviewHeatmapRow {
  groupKey: string;
  label: string;
  buckets: ReviewHeatmapBucket[];
}

export interface ReviewTag {
  label: string;
  count: number;
}

export interface ReviewSummary {
  overview: ReviewOverview;
  groups: ReviewGroupRow[];
  leaderboard: {
    observe: ReviewLeaderboardItem[];
    review: ReviewLeaderboardItem[];
  };
  heatmap: ReviewHeatmapRow[];
  tags: ReviewTag[];
  nextActions: string[];
}

export const reviewApi = {
  getSummary: (params?: { window?: ReviewWindow; bucket?: ReviewBucket }): Promise<ReviewSummary> =>
    getReq('/review/summary', {
      params: {
        window: params?.window ?? '24h',
        bucket: params?.bucket ?? '1h',
      },
    }),
};

export interface WatchlistItem {
  symbol: string;
  sourceStrategyId: number;
  sourceStrategyName: string;
  lastSide?: string | null;
  lastAction?: string | null;
  lastPrice?: number | null;
  lastQuantity?: number | null;
  lastNotionalUsdt?: number | null;
  lastExecutionAt?: string | null;
  orderCount: number;
}

export interface WatchTradeMarker {
  id: number;
  label: 'B' | 'S';
  side?: string | null;
  action?: string | null;
  symbol: string;
  price?: number | null;
  quantity?: number | null;
  timestamp: number;
  datetime?: string | null;
  sourceStrategyId: number;
  sourceStrategyName: string;
  subscriptionId: number;
  liveOrderId?: string | null;
  clientOrderId?: string | null;
}

export interface WatchDerivativePoint {
  timestamp: number;
  value?: number | null;
  [key: string]: number | string | null | undefined;
}

export interface WatchDerivativesData {
  accountId: string;
  exchange: string;
  symbol: string;
  timeframe: string;
  openInterest: { points: WatchDerivativePoint[] | null };
  fundingRate: { points: WatchDerivativePoint[] | null };
  longShortRatio: { points: WatchDerivativePoint[] | null };
  takerVolume: { points: WatchDerivativePoint[] | null };
  basis: { points: WatchDerivativePoint[] | null };
}

export interface WatchMarketPayload {
  accountId: string;
  exchange: string;
  symbol: string;
  timeframe: string;
  ticker: Ticker;
  klines: Kline[];
  orderbook: OrderBook;
  recentTrades: Array<Record<string, unknown>>;
  positions: LiveExecutionPosition[];
}

export const liveWatchApi = {
  getWatchlist: (
    accountId = 'default',
    limit = 100
  ): Promise<{ accountId: string; exchange: string; items: WatchlistItem[] }> =>
    getReq('/live/watchlist', { params: { accountId, limit } }),

  getWatchMarket: (
    symbol: string,
    accountId = 'default',
    timeframe = '15m',
    limit = 240
  ): Promise<WatchMarketPayload> =>
    getReq('/live/watchlist/market', { params: { accountId, symbol, timeframe, limit } }),

  getTradeMarkers: (
    symbol: string,
    accountId = 'default',
    params?: { start?: number; end?: number; limit?: number }
  ): Promise<{ accountId: string; exchange: string; symbol: string; markers: WatchTradeMarker[] }> =>
    getReq('/live/watchlist/markers', { params: { accountId, symbol, ...params } }),

  getDerivativesData: (
    symbol: string,
    accountId = 'default',
    timeframe = '15m',
    limit = 120
  ): Promise<WatchDerivativesData> =>
    getReq('/live/watchlist/derivatives-data', { params: { accountId, symbol, timeframe, limit } }),
};

// ============================================
// 行情 API
// ============================================

export interface MarketKlinesMeta {
  exchange?: string;
  symbol?: string;
  timeframe?: string;
  dataStatus?: string;
  unavailableReason?: string | null;
  providerSource?: string;
  externalFetch?: boolean;
  cacheHit?: boolean;
  fallbackSource?: string;
  fallbackError?: string;
  rowCount?: number;
  fromDate?: string | null;
  toDate?: string | null;
  latestTradeDate?: string | null;
  fallbackFrom?: {
    dataStatus?: string;
    unavailableReason?: string | null;
  } | null;
}

export interface MarketKlinesPayload extends MarketKlinesMeta {
  items: Kline[];
}

async function getMarketKlinesPayload(
  exchange: string,
  symbol: string,
  timeframe = '1h',
  limit = 100,
  start?: number,
  end?: number
): Promise<MarketKlinesPayload> {
  const raw = await api.get('/market/klines', {
    params: snakifyDeep({ exchange, symbol, timeframe, limit, start, end }),
  });
  const response = raw as unknown;
  const envelope = response && typeof response === 'object' ? response as Record<string, unknown> : {};
  const items = camelizeDeep<Kline[]>(unwrapEnvelope(raw));
  const meta = camelizeDeep<MarketKlinesMeta>(envelope.meta || {});
  return { ...meta, items: Array.isArray(items) ? items : [] };
}

export const marketApi = {
  getTicker: (exchange: string, symbol: string): Promise<Ticker> =>
    getReq('/market/ticker', { params: { exchange, symbol } }),

  getOverview: (tradeDate?: string): Promise<MarketOverview> =>
    getReq('/market/overview', { params: { tradeDate } }),

  getDashboard: (tradeDate?: string): Promise<MarketHomeDashboard> =>
    getReq('/market/dashboard', { params: { tradeDate } }),

  getTickers: (exchange: string, symbols?: string[]): Promise<Ticker[]> =>
    getReq('/market/tickers', {
      params: { exchange, symbols: symbols?.join(','), offset: 0, limit: 500 },
    }),

  getAllTickers: async (exchange: string): Promise<Ticker[]> => {
    const items: Ticker[] = [];
    const limit = 500;
    let offset = 0;
    let total = 0;

    do {
      const page = await getPagedReq<Ticker[]>('/market/tickers', {
        params: { exchange, offset, limit },
      });
      const rows = Array.isArray(page.data) ? page.data : [];
      items.push(...rows);
      total = page.meta?.total ?? items.length;
      offset += rows.length;
      if (rows.length === 0) break;
    } while (offset < total);

    return items;
  },

  getKlines: (
    exchange: string,
    symbol: string,
    timeframe = '1h',
    limit = 100,
    start?: number,
    end?: number
  ): Promise<Kline[]> =>
    getMarketKlinesPayload(exchange, symbol, timeframe, limit, start, end).then((payload) => payload.items),

  getKlinesPayload: getMarketKlinesPayload,

  getTechnicalIndicators: (
    exchange: string,
    symbol: string,
    timeframe = '1h',
    limit = 100,
    start?: number,
    end?: number,
    emaPeriods: number[] = [5, 10, 20, 30]
  ): Promise<TechnicalIndicators> =>
    getReq('/market/indicators', {
      params: {
        exchange,
        symbol,
        timeframe,
        limit,
        start,
        end,
        emaPeriods: emaPeriods.join(','),
      },
    }),

  getOrderbook: (exchange: string, symbol: string, limit = 20): Promise<OrderBook> =>
    getReq('/market/orderbook', { params: { exchange, symbol, limit } }),

  getTrades: (
    exchange: string,
    symbol: string,
    limit = 30
  ): Promise<Array<{
    id?: string | number;
    timestamp?: number;
    datetime?: string;
    side?: string;
    price?: number;
    amount?: number;
    cost?: number;
  }>> => getReq('/market/trades', { params: { exchange, symbol, limit } }),

  getSymbols: (exchange: string, quote = 'CNY', marketType = 'stock'): Promise<{ symbols: string[]; instruments: MarketInstrument[] }> =>
    getReq('/market/symbols', { params: { exchange, quote, market_type: marketType } }),

  getPhase: (tradeDate?: string): Promise<MarketPhase> =>
    getReq('/market/phase', { params: { tradeDate } }),

  getSentiment: (tradeDate?: string): Promise<MarketSentiment> =>
    getReq('/market/sentiment', { params: { tradeDate } }),

  getTimeline: (limit = 60): Promise<MarketTimelinePayload> =>
    getReq('/market/timeline', { params: { limit } }),

  getSectorRps: (
    classificationSystem: 'industry' | 'concept' = 'industry',
    tradeDate?: string,
    limit = 10
  ): Promise<SectorRpsRow[]> =>
    getReq('/market/sector-rps', { params: { classificationSystem, tradeDate, limit } }),

  getSectorRpsHistory: (
    sectorCode: string,
    classificationSystem: 'industry' | 'concept',
    limit = 60,
  ): Promise<SectorRpsRow[]> =>
    getReq(`/market/sector-rps/${encodeURIComponent(sectorCode)}/history`, { params: { classificationSystem, limit } }),

  getSectorMembers: async (
    sectorCode: string,
    classificationSystem: 'industry' | 'concept',
    tradeDate?: string,
    limit = 2000,
  ): Promise<SectorMembersPayload> => {
    const page = await getPagedReq<SectorMember[]>(`/market/sector-rps/${encodeURIComponent(sectorCode)}/members`, {
      params: { classificationSystem, tradeDate, limit },
    });
    return { items: page.data || [], ...(page.meta || {}) } as SectorMembersPayload;
  },

  getMovers: (tradeDate?: string, limit = 10): Promise<SymbolAbnormality[]> =>
    getReq('/market/movers', { params: { tradeDate, limit } }),

  getSymbolMover: (symbol: string, tradeDate?: string): Promise<SymbolAbnormality> =>
    getReq(`/market/movers/${symbol}`, { params: { tradeDate } }),
};

export interface MarketInstrument {
  symbol: string;
  name: string;
  displayName?: string;
  exchange?: string;
  assetClass?: string;
  industry?: string | null;
  board?: string | null;
  listStatus?: string;
}

export async function lookupSymbolNames(symbols: string[]): Promise<Record<string, string>> {
  const unique = Array.from(new Set(symbols.map((item) => String(item || '').trim()).filter(Boolean)));
  if (!unique.length) return {};
  const chunks = Array.from({ length: Math.ceil(unique.length / 500) }, (_, index) => unique.slice(index * 500, (index + 1) * 500));
  const responses = await Promise.all(chunks.map((chunk) => getReq<{ names: Record<string, string>; total: number }>('/market/symbol-names', { params: { symbols: chunk.join(',') } })));
  return Object.assign({}, ...responses.map((response) => response.names || {}));
}

// ============================================
// 资金费率 API
// ============================================

export const fundingApi = {
  getRates: async (_exchange: string, _symbols?: string[]): Promise<FundingRate[]> => [],

  getRate: (exchange: string, symbol: string): Promise<FundingRate> =>
    getReq(`/funding/rate/${symbol}`, { params: { exchange } }),

  getHistory: (
    exchange: string,
    symbol: string,
    limit = 100
  ): Promise<{ timestamp: number; rate: number }[]> =>
    getReq('/funding/history', { params: { exchange, symbol, limit } }),

  getOpportunities: (
    exchange: string,
    minRate = 0.0001,
    limit = 20
  ): Promise<FundingOpportunity[]> =>
    getReq('/funding/opportunities', { params: { exchange, minRate, limit } }),

  getSummary: (): Promise<{
    exchanges: Record<string, { total: number; avgRate: number }>;
    topOpportunities: FundingOpportunity[];
  }> => getReq('/funding/summary'),
};

// ============================================
// 交易 API
// ============================================

export const tradingApi = {
  getBalance: (exchange: string): Promise<{ exchange: string; balance: any[] }> =>
    getReq('/trading/accounts/balance', { params: { exchange } }),

  getBalanceDetail: (exchange: string): Promise<{ exchange: string; trading: any[]; funding: any[] }> =>
    getReq('/trading/accounts/balance/detail', { params: { exchange } }),

  getOpenOrders: (exchange: string, symbol?: string): Promise<{ exchange: string; orders: any[] }> =>
    getReq('/trading/orders/open', { params: { exchange, symbol } }),

  getOrderHistory: (exchange: string, limit = 50, symbol?: string): Promise<{ exchange: string; orders: any[] }> =>
    getReq('/trading/orders/history', { params: { exchange, limit, symbol } }),

  cancelOrder: (orderId: string, exchange: string, symbol: string): Promise<{ result: any }> =>
    deleteReq(`/trading/order/${orderId}`, { params: { exchange, symbol } }),

  transfer: (data: {
    exchange: string;
    currency: string;
    amount: number;
    fromAccount: string;
    toAccount: string;
  }): Promise<any> =>
    postReq('/trading/transfer', data),

  spotOrder: (data: {
    exchange: string;
    symbol: string;
    side: 'buy' | 'sell';
    type: 'market' | 'limit';
    amount: number;
    price?: number | null;
  }): Promise<{ order: any; warnings?: string[] }> =>
    postReq('/trading/spot/order', data),

  futuresOrder: (data: {
    exchange: string;
    symbol: string;
    side: 'long' | 'short';
    action: 'open' | 'close';
    amount: number;
    leverage: number;
    price?: number | null;
  }): Promise<{ order: any }> =>
    postReq('/trading/futures/order', data),
};

// ============================================
// 策略 API
// ============================================

export interface StrategyPageResponse {
  items: Strategy[];
  total: number;
  page: number;
  perPage: number;
  pages: number;
  statusCounts: Record<string, number>;
  assetCounts: Record<string, number>;
  typeCounts: Record<string, number>;
  timeframeCounts: Record<string, number>;
  capitalCounts: Record<string, number>;
}

export const strategyApi = {
  getPage: (params: {
    page: number;
    perPage: number;
    search?: string;
    status?: string;
    assetClass?: string;
    strategyType?: string;
    timeframe?: string;
    capital?: string;
  }): Promise<StrategyPageResponse> =>
    getReq<StrategyPageResponse>('/strategies', {
      params: {
        page: params.page,
        perPage: params.perPage,
        search: params.search,
        status: params.status,
        assetClass: params.assetClass,
        strategyType: params.strategyType,
        timeframe: params.timeframe,
        capital: params.capital,
      },
    }),

  get: (id: number): Promise<Strategy> => getReq(`/strategies/${id}`),

  create: (data: {
    name: string;
    description?: string;
    scriptContent: string;
    config?: Record<string, unknown>;
    exchange?: string;
    symbols?: string[];
  }): Promise<Strategy> => postReq('/strategies', data),

  update: (id: number, data: Partial<Strategy>): Promise<Strategy> =>
    putReq(`/strategies/${id}`, data),

  delete: (id: number): Promise<void> => deleteReq(`/strategies/${id}`),

  start: (id: number): Promise<{ started: boolean }> => postReq(`/strategies/${id}/start`),

  stop: (id: number): Promise<{ stopped: boolean }> => postReq(`/strategies/${id}/stop`),

  getStatus: (id: number): Promise<{
    strategyId: number;
    name: string;
    status: string;
    pnl: number;
    totalTrades: number;
  }> => getReq(`/strategies/${id}/status`),
};

// ============================================
// 监控 API
// ============================================

export const monitorApi = {
  getAlerts: (): Promise<any[]> => getReq('/monitor/alerts'),

  getEvents: (
    limit = 10,
    source?: 'strategy' | 'signal' | 'price' | 'abnormal' | 'sector',
    severity?: 'info' | 'warning' | 'critical',
  ): Promise<MarketEventsPayload> => getReq('/monitor/events', {
    params: { limit, source, severity },
  }),

  createAlert: (data: {
    name: string;
    type: string;
    exchange: string;
    symbol?: string;
    threshold: number;
    strategyId?: number;
    cooldownSec?: number;
    telegramBotToken?: string;
    telegramChatId?: string;
    webhookUrl?: string;
  }): Promise<{ id: number }> => postReq('/monitor/alerts', data),

  toggleAlert: (id: number, enabled: boolean): Promise<{ id: number; enabled: boolean }> =>
    putReq(`/monitor/alerts/${id}`, null, { params: { enabled } }),

  deleteAlert: (id: number): Promise<{ deleted: boolean }> =>
    deleteReq(`/monitor/alerts/${id}`),

  getRunningStrategies: (): Promise<any[]> =>
    getReq('/monitor/running-strategies'),

  getActiveStrategies: (): Promise<any[]> =>
    getReq('/monitor/active_strategies'),

  getLongShortRatio: (exchange: string, symbol: string): Promise<any> =>
    getReq('/monitor/long-short-ratio', { params: { exchange, symbol } }),

  getOpenInterest: (exchange: string, symbol: string): Promise<any> =>
    getReq('/monitor/open-interest', { params: { exchange, symbol } }),
};

// ============================================
// 策略上线 (自动交易 / 实盘) API
// ============================================

export const liveApi = {
  getPaperInstances: (): Promise<{ items: Strategy[] }> => getReq('/live/instances'),
  getPaperCandidates: (): Promise<any[]> => getReq('/live/candidates'),
  createPaperInstance: (payload: {
    name: string;
    qualifyingBacktestRunId: string;
    initialCash: number;
    start?: boolean;
  }): Promise<any> => postReq('/live/instances', payload),
  getStrategies: (params?: { page?: number; perPage?: number }): Promise<StrategyPageResponse> =>
    getReq<StrategyPageResponse>('/strategies', {
      params: {
        page: params?.page ?? 1,
        perPage: params?.perPage ?? 60,
      },
    }),

  startStrategy: (id: number): Promise<any> => postReq(`/strategies/${id}/start`),

  stopStrategy: (id: number): Promise<any> => postReq(`/strategies/${id}/stop`),

  getStrategyStatus: (id: number): Promise<any> => getReq(`/strategies/${id}/status`),

  getStrategyTrades: (id: number, limit = 50): Promise<any> =>
    getReq('/live/trades', { params: { instanceId: id, limit } }),

  configure: (config: {
    [key: string]: unknown;
    instance_id?: string | number;
  }): Promise<any> => postReq('/live/configure', config),

  start: (instanceId?: string | number): Promise<any> =>
    postReq('/live/start', instanceId != null ? { instance_id: instanceId } : {}),

  stop: (instanceId?: string | number, clearMetrics = false): Promise<any> =>
    postReq('/live/stop', {
      ...(instanceId != null ? { instance_id: instanceId } : {}),
      clear_metrics: clearMetrics,
    }),

  pause: (instanceId?: string | number): Promise<any> =>
    postReq('/live/pause', instanceId != null ? { instance_id: instanceId } : {}),

  resume: (instanceId?: string | number): Promise<any> =>
    postReq('/live/resume', instanceId != null ? { instance_id: instanceId } : {}),

  advance: (instanceId: string | number, maxDates = 1): Promise<any> =>
    postReq('/live/advance', { instance_id: instanceId, max_dates: maxDates }),

  closePaperPosition: (payload: {
    instanceId?: string | number;
    symbol: string;
    side?: string | null;
    marketType?: 'spot' | 'swap' | string | null;
  }): Promise<any> => postReq('/live/positions/close', payload),

  getDashboard: (instanceId?: string | number): Promise<any> =>
    getReq('/live/dashboard', { params: instanceId != null ? { instance_id: instanceId } : {} }),

  getEvents: (limit = 50, eventType?: string, instanceId?: string | number): Promise<any> =>
    getReq('/live/events', {
      params: {
        limit,
        eventType,
        ...(instanceId != null ? { instance_id: instanceId } : {}),
      },
    }),

  getEquityCurve: (instanceId?: string | number): Promise<any> =>
    getReq('/live/equity_curve', { params: instanceId != null ? { instance_id: instanceId } : {} }),

  preFlight: (config: {
    [key: string]: unknown;
  }): Promise<any> => postReq('/live/pre_flight', config),

  promoteToLive: (config: {
    sourceStrategyId: string | number;
    exchange?: string;
    initialEquity?: number;
    loopInterval?: number;
    startImmediately?: boolean;
    confirmPaperReviewed?: boolean;
    confirmLiveRisk?: boolean;
    riskConfig?: Record<string, unknown>;
  }): Promise<any> => postReq('/live/promote', config),

  promoteToLivePreflight: (config: {
    sourceStrategyId: string | number;
    exchange?: string;
    initialEquity?: number;
    loopInterval?: number;
    startImmediately?: boolean;
    riskConfig?: Record<string, unknown>;
  }): Promise<any> => postReq('/live/promote/preflight', config),

  testTelegram: (message: string): Promise<any> =>
    postReq('/live/test_telegram', { message }),
};

// ============================================
// 模拟盘 API
// ============================================

export const paperApi = {
  // 兼容旧“模拟盘验证”入口：底层改为复用回测 run_sync
  run: async (config: {
    [key: string]: unknown;
  }): Promise<any> => {
    const daysBack = Number(config.days_back || 30);
    const end = new Date();
    const start = new Date(end.getTime() - daysBack * 24 * 60 * 60 * 1000);
    const toDate = (d: Date) => d.toISOString().slice(0, 10);

    const payload: Record<string, unknown> = {
      strategy_id: Number(config.strategy),
      exchange: String(config.exchange || 'okx'),
      timeframe: String(config.timeframe || '1h'),
      start_date: toDate(start),
      end_date: toDate(end),
      initial_capital: Number(config.initial_capital || 10000),
      stop_loss: Number(config.stop_loss || 0.05),
    };
    if (typeof config.symbol === 'string' && config.symbol.trim()) {
      payload.symbol = config.symbol.trim();
    }

    // 与 backtestApi.runSync 一致，避免 Kairos 验证误判超时
    return postReq('/backtest/run_sync', payload, { timeout: BACKTEST_RUN_SYNC_TIMEOUT_MS });
  },

  getSignals: (instanceId?: string, strategy?: string, symbol?: string, timeframe?: string, limit?: number): Promise<any> =>
    getReq('/paper-trading/signals', { params: { instanceId: instanceId, strategy, symbol, timeframe, limit } }),
};

// ============================================
// 数据管理 API
// ============================================

export interface DataSyncMeta {
  exchange: string;
  symbol: string;
  timeframe: string;
  dataType: string;
  firstTimestamp: number | null;
  lastTimestamp: number | null;
  totalRecords: number;
  status: string | null;
  lastSyncAt: string | null;
  errorMessage: string | null;
  updatedAt?: string | null;
}

export interface DataSyncProgressItem {
  exchange: string;
  symbol: string;
  timeframe: string;
  status: string;
  totalFetched: number;
  totalInserted: number;
  startedAt: string | null;
  endedAt: string | null;
  elapsedSeconds: number | null;
  checkpointTimestamp?: number | null;
  error: string | null;
}

export interface DataSyncStatusResponse {
  isRunning: boolean;
  currentJob: {
    jobId?: string | null;
    runId?: number | null;
    exchange: string | null;
    status: string | null;
    symbols?: string[];
    timeframes?: string[];
    historyDays?: number;
    syncScope?: string | null;
    startDate?: string | null;
    endDate?: string | null;
    tradeDateCount?: number;
    processedTradeDates?: number;
    instrumentCount?: number;
    dailyCount?: number;
    totalFetched: number;
    totalInserted: number;
    errors: number;
    startedAt?: string | null;
    completedAt?: string | null;
    elapsedSeconds?: number | null;
    totalItems?: number;
    completedItems?: number;
    errorItems?: number;
    processedItems?: number;
    progress: DataSyncProgressItem[];
  } | null;
  summary: {
    totalRecords: number;
    exchanges: string[];
    symbolsCount: number;
    pairs: number;
  };
  details: DataSyncMeta[];
}

export interface DataSyncJobItem {
  id?: number;
  exchange?: string;
  symbol: string;
  timeframe: string;
  status: string;
  totalFetched: number;
  totalInserted: number;
  checkpointTimestamp?: number | null;
  startedAt?: string | null;
  endedAt?: string | null;
  elapsedSeconds?: number | null;
  errorMessage?: string | null;
}

export interface DataSyncJobSummary {
  jobId: string;
  exchange: string;
  status: string;
  symbols: string[];
  timeframes: string[];
  historyDays: number;
  startDate?: string | null;
  endDate?: string | null;
  totalSymbols: number;
  totalTimeframes: number;
  totalItems: number;
  completedItems: number;
  runningItems: number;
  pendingItems: number;
  errorItems: number;
  processedItems?: number;
  progressPercent: number;
  totalFetched: number;
  totalInserted: number;
  errorCount: number;
  errorMessage?: string | null;
  createdAt?: string | null;
  startedAt?: string | null;
  completedAt?: string | null;
  updatedAt?: string | null;
  elapsedSeconds?: number | null;
  items?: DataSyncJobItem[];
}

export interface DataSyncJobsResponse {
  jobs: DataSyncJobSummary[];
}

export interface DataSyncConfigResponse {
  defaultSymbols: string[];
  instruments?: MarketInstrument[];
  symbolsCount?: number;
  defaultTimeframes: string[];
  defaultHistoryDays: number;
}

export interface DataSyncScheduleConfig {
  enabled: boolean;
  intervalMinutes: number;
  historyDays: number;
  symbols: string[];
  timeframes: string[];
  lastRunAt?: string | null;
  lastStartedAt?: string | null;
  lastFinishedAt?: string | null;
  lastJobId?: string | null;
  lastError?: string | null;
  nextRunAt?: string | null;
  updatedAt?: string | null;
}

export interface DataSyncScheduleUpdate {
  enabled?: boolean;
  intervalMinutes?: number;
  historyDays?: number;
  symbols?: string[];
  timeframes?: string[];
}

export interface DataSyncTableStat {
  tableName: string;
  timeframe: string;
  exchange: string;
  symbol: string;
  recordCount: number;
  firstTimestamp: number | null;
  lastTimestamp: number | null;
}

export interface DataSyncMarketStats {
  totalRecords: number;
  totalPairs: number;
  totalSymbols: number;
}

export interface DataSyncTableStatsResponse {
  tables: DataSyncTableStat[];
  totalRecords: number;
  totalPairs: number;
  marketStats: {
    swap: DataSyncMarketStats;
    spot: DataSyncMarketStats;
  };
}

export interface DataSyncQualityIssue {
  type: string;
  exchange?: string;
  symbol?: string;
  timeframe?: string;
  count?: number;
  directionFlips?: number;
  firstTimestamp?: number | null;
  lastTimestamp?: number | null;
  message?: string;
}

export interface DataSyncQualityItem {
  exchange: string;
  symbol: string;
  timeframe: string;
  status: 'ok' | 'missing' | 'error' | string;
  recordCount: number;
  firstTimestamp: number | null;
  lastTimestamp: number | null;
  issues: DataSyncQualityIssue[];
  message: string;
}

export interface DataSyncQualityResponse {
  checkedAt: string;
  summary: {
    checked: number;
    ok: number;
    error: number;
    missing: number;
    issueCount: number;
    truncated: boolean;
    maxItems: number;
  };
  items: DataSyncQualityItem[];
}

export interface DataSyncQualityRequest {
  exchange?: string;
  symbols?: string[];
  timeframes?: string[];
  maxItems?: number;
}

export interface DataSyncStartRequest {
  exchange?: string;
  symbols?: string[];
  timeframes?: string[];
  historyDays?: number;
  startDate?: string;
  endDate?: string;
}

export interface DataSyncStartResponse {
  jobId?: string;
  message?: string;
  exchange?: string;
  symbols?: string[];
  timeframes?: string[];
  historyDays?: number;
  startDate?: string;
  endDate?: string;
}

export interface AshareHistorySyncRequest {
  historyDays?: number;
  startDate?: string;
  endDate?: string;
}

export interface AshareHistorySyncResponse {
  runId?: number;
  status: string;
  syncScope?: string;
  instrumentCount?: number;
  dailyCount?: number;
  startDate?: string;
  endDate?: string;
  tradeDateCount?: number;
  skippedTradeDates?: Array<{ tradeDate: string; reason: string }>;
}

export interface DataSyncSyncOneRequest {
  exchange?: string;
  symbol: string;
  timeframe: string;
  startDate?: string;
  endDate?: string;
  historyDays?: number;
}

export interface DataSyncSyncOneResponse {
  exchange: string;
  symbol: string;
  timeframe: string;
  status: string;
  totalFetched: number;
  totalInserted: number;
  error?: string | null;
  elapsedSeconds?: number | null;
}

export interface DataSyncDeleteRequest {
  exchange?: string;
  symbol?: string;
  timeframe?: string;
}

export interface DataSyncDeleteResponse {
  message: string;
  deleted: number;
}

export interface DataSyncAddSymbolRequest {
  symbol: string;
}

export interface DataSyncAddSymbolResponse {
  symbol: string;
  added: boolean;
  defaultSymbols: string[];
}

export interface DataSyncRemoveSymbolRequest {
  symbol: string;
}

export interface DataSyncRemoveSymbolResponse {
  symbol: string;
  removed: boolean;
  defaultSymbols: string[];
}

// ============================================
// AI 分析 API
// ============================================

export const aiPredictApi = {
  analyze: (data: {
    exchange?: string;
    symbol: string;
    timeframe: string;
    lookback?: number;
  }): Promise<{
    symbol: string;
    timeframe: string;
    analysis: string;
    predictedBars: any[];
  }> => postReq('/ai_predict/analyze', data),
};

// ============================================
// 数据资产 API
// ============================================

export const dataAssetsApi = {
  getAssets: (): Promise<{
    assets: Array<{
      exchange: string;
      symbol: string;
      timeframe: string;
      recordCount: number;
      firstDate: string | null;
      lastDate: string | null;
    }>;
    totalRecords: number;
    totalPairs: number;
    totalItems: number;
  }> => getReq('/sync/assets'),

  quickSync: (data: {
    exchange?: string;
    symbol: string;
    timeframe: string;
    historyDays?: number;
  }): Promise<{ taskId: string; message: string }> =>
    postReq('/sync/quick-sync', data),
};

// ============================================
// 数据同步 API
// ============================================

export const dataSyncApi = {
  getStatus: (): Promise<DataSyncStatusResponse> => getReq('/sync/status'),

  getJobs: (limit = 20): Promise<DataSyncJobsResponse> =>
    getReq('/sync/jobs', { params: { limit, includeItems: false } }),

  getConfig: (): Promise<DataSyncConfigResponse> => getReq('/sync/config'),

  getSchedule: (): Promise<DataSyncScheduleConfig> => getReq('/sync/schedule'),

  updateSchedule: (data: DataSyncScheduleUpdate): Promise<DataSyncScheduleConfig> =>
    putReq('/sync/schedule', data),

  addSymbol: (data: DataSyncAddSymbolRequest): Promise<DataSyncAddSymbolResponse> =>
    postReq('/sync/symbols', data),

  removeSymbol: (data: DataSyncRemoveSymbolRequest): Promise<DataSyncRemoveSymbolResponse> =>
    deleteReq('/sync/symbols', { data }),

  getData: (exchange?: string): Promise<Array<Record<string, unknown>>> =>
    getReq('/sync/data', { params: { exchange } }),

  getTableStats: (): Promise<DataSyncTableStatsResponse> => getReq('/sync/table-stats'),

  getQuality: (params: DataSyncQualityRequest): Promise<DataSyncQualityResponse> =>
    getReq('/sync/quality', {
      params: {
        exchange: params.exchange,
        symbols: params.symbols?.join(','),
        timeframes: params.timeframes?.join(','),
        maxItems: params.maxItems,
      },
      timeout: DATA_SYNC_LONG_TIMEOUT_MS,
    }),

  startSync: (data: DataSyncStartRequest): Promise<DataSyncStartResponse> =>
    postReq('/sync/start', data, { timeout: DATA_SYNC_LONG_TIMEOUT_MS }),

  syncAllAshareHistory: (data: AshareHistorySyncRequest = {}): Promise<AshareHistorySyncResponse> =>
    postReq('/sync/history/sync-all', data, { timeout: DATA_SYNC_LONG_TIMEOUT_MS }),

  syncOne: (data: DataSyncSyncOneRequest): Promise<DataSyncSyncOneResponse> =>
    postReq('/sync/sync-one', data, { timeout: DATA_SYNC_LONG_TIMEOUT_MS }),

  dailyUpdate: (exchange?: string, data?: DataSyncStartRequest): Promise<DataSyncStartResponse> =>
    postReq('/sync/daily-update', data || {}, {
      params: { exchange },
      timeout: DATA_SYNC_LONG_TIMEOUT_MS,
    }),

  deleteData: (data: DataSyncDeleteRequest): Promise<DataSyncDeleteResponse> =>
    postReq('/sync/delete-data', data),
};

// ============================================
// OKX 原生数据同步 API（资金流/多空比/OI 快照）
// ============================================

export interface OkxNativeSyncScheduleConfig {
  enabled: boolean;
  rubikIntervalMinutes: number;
  oiIntervalMinutes: number;
  ccys: string[];
  lastRubikRunAt?: string | null;
  lastRubikFinishedAt?: string | null;
  lastRubikError?: string | null;
  lastOiRunAt?: string | null;
  lastOiFinishedAt?: string | null;
  lastOiError?: string | null;
  rubikRowCount: number;
  oiSnapshotCount: number;
  oiSymbolCount: number;
}

export type OkxNativeSyncScheduleUpdate = Partial<{
  enabled: boolean;
  rubikIntervalMinutes: number;
  oiIntervalMinutes: number;
  ccys: string[];
}>;

export const okxNativeSyncApi = {
  getSchedule: (): Promise<OkxNativeSyncScheduleConfig> => getReq('/sync/okx-native/schedule'),

  updateSchedule: (data: OkxNativeSyncScheduleUpdate): Promise<OkxNativeSyncScheduleConfig> =>
    putReq('/sync/okx-native/schedule', data),

  run: (kind: 'rubik' | 'oi' | 'all'): Promise<Record<string, unknown>> =>
    postReq('/sync/okx-native/run', { kind }, { timeout: DATA_SYNC_LONG_TIMEOUT_MS }),
};

// ============================================
// 首页加密原生数据 API
// ============================================

export interface NativeSentimentSpan {
  rows: number;
  from: string;
  to: string;
}

export interface NativeSentimentCoreItem {
  ccy: string;
  symbol: string;
  taker?: { date: string; sellVol: number; buyVol: number; buyRatio: number | null };
  longShortRatio?: { date: string; value: number };
  fundingRate?: { date: string; value: number };
  oi?: {
    exchange: string; date: string; openInterest: number;
    openInterestUsd: number; change24hPct: number | null;
  };
}

export interface NativeSentimentResponse {
  core: NativeSentimentCoreItem[];
  pipeline: Record<string, NativeSentimentSpan>;
}

export const nativeSentimentApi = {
  get: (): Promise<NativeSentimentResponse> => getReq('/market/native-sentiment'),
};

// ============================================
// 系统设置 API
// ============================================

export interface LLMModelSettings {
  providerKey?: string;
  providerName?: string;
  model: string;
  defaultModel: string;
  models: string[];
  freeTierModels?: string[];
  modelFallbackEnabled?: boolean;
  baseUrl: string;
  enableThinking?: boolean;
  requestTimeout?: number;
  apiKeyConfigured: boolean;
  apiKeySource?: string | null;
  providers?: LLMProviderSettings[];
  providerCapabilities?: LLMProviderCapabilities[];
  providerMigrations?: Record<string, { errorCode?: string; statusDetail?: string }>;
  modelManagementEnabled?: boolean;
  providerManagementEnabled?: boolean;
  connectionTestEnabled?: boolean;
}

export type ProviderTransportType = 'openai_chat' | 'xai_api' | 'codex_cli' | 'cursor_cli';
export type HttpProviderTransportType = 'openai_chat' | 'xai_api';

export interface LLMProviderCapabilities {
  providerKey: string;
  displayName: string;
  transportType: ProviderTransportType;
  models: string[];
  reasoningEfforts: string[];
  speedModes: string[];
  supportsTools: boolean;
  supportsStructuredOutput: boolean;
  supportsResume: boolean;
  configured: boolean;
  healthy: boolean;
  commandAvailable?: boolean;
  loginVerified?: boolean | null;
  statusDetail?: string;
  credentialMode?: 'env' | 'managed_login' | 'none';
  credentialSource?: string;
  configRevision?: string;
  probedAt?: string | null;
  errorCode?: string | null;
  defaultModel?: string;
  enabled?: boolean;
  active?: boolean;
}

export interface LLMProviderSettings {
  providerKey: string;
  name: string;
  apiKeyEnv: string;
  baseUrl: string;
  defaultModel: string;
  models: string[];
  apiKeyConfigured: boolean;
  builtin?: boolean;
  active?: boolean;
  enabled?: boolean;
  transportType?: ProviderTransportType;
  credentialMode?: 'env' | 'managed_login' | 'none';
  credentialSource?: string;
  commandAvailable?: boolean;
  loginVerified?: boolean | null;
  configRevision?: string;
  reasoningEfforts?: string[];
  speedModes?: string[];
  supportsTools?: boolean;
  supportsStructuredOutput?: boolean;
  supportsResume?: boolean;
  statusDetail?: string;
  errorCode?: string | null;
}

export interface LLMProviderInput {
  providerKey: string;
  name: string;
  apiKeyEnv: string;
  baseUrl: string;
  defaultModel: string;
  models: string[];
  transportType?: HttpProviderTransportType;
  credentialMode?: 'env' | 'managed_login' | 'none';
  reasoningEfforts?: string[];
  speedModes?: string[];
  enabled?: boolean;
  localProvider?: boolean;
  supportsTools?: boolean;
  supportsStructuredOutput?: boolean;
  supportsResume?: boolean;
}

export interface McpTokenSettings {
  configured: boolean;
  source: 'none' | 'env' | 'generated' | string;
  maskedToken?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  note?: string | null;
  authHeader: string;
  tokenEnv: string;
  legacyAuthHeader?: string;
  legacyTokenEnv?: string;
  remoteEnabled: boolean;
  remotePath: string;
  requireToken: boolean;
}

export interface GeneratedMcpToken extends McpTokenSettings {
  token: string;
}

export interface McpAgentTokenItem {
  id: number;
  name: string;
  tokenPrefix: string;
  maskedToken: string;
  scopes: string[];
  toolGroups: string[];
  rateLimitPerMin: number;
  expiresAt?: string | null;
  createdAt?: string | null;
  createdBy?: string | null;
  lastUsedAt?: string | null;
  revokedAt?: string | null;
}

export interface McpAgentTokenListResponse {
  items: McpAgentTokenItem[];
  policy: {
    plaintextReturnedOnce: boolean;
    staticTokenEnv: string;
    authHeaderDefault: string;
    tokenManagement?: Record<string, unknown>;
    scopeClasses?: Record<string, unknown>;
    idempotency?: Record<string, unknown>;
  };
  status: {
    configured: boolean;
    envTokenConfigured: boolean;
    activeTokenCount: number;
  };
}

export interface McpAgentTokenCreateInput {
  name?: string;
  expiresInDays?: number;
  rateLimitPerMin?: number;
  toolGroups?: string[];
}

export interface McpAgentTokenCreateResponse {
  token: string;
  item: McpAgentTokenItem;
}

export const settingsApi = {
  getNotify: (): Promise<{ enabled: boolean; webhookConfigured: boolean }> =>
    getReq('/settings/notify'),
  setNotify: (enabled: boolean): Promise<{ enabled: boolean; webhookConfigured: boolean }> =>
    postReq('/settings/notify', { enabled }),
  getFeishuWebhook: (): Promise<{ webhookConfigured: boolean; maskedWebhookUrl?: string | null }> =>
    getReq('/settings/feishu-webhook'),
  setFeishuWebhook: (webhookUrl: string): Promise<{ webhookConfigured: boolean; maskedWebhookUrl?: string | null }> =>
    postReq('/settings/feishu-webhook', { webhookUrl }),
  getMcpToken: (): Promise<McpTokenSettings> =>
    getReq('/settings/mcp-token'),
  generateMcpToken: (note?: string): Promise<GeneratedMcpToken> =>
    postReq('/settings/mcp-token/generate', { note }),
  getLLMModel: (signal?: AbortSignal): Promise<LLMModelSettings> =>
    getReq('/settings/llm-model', { signal }),
  setLLMModel: (model: string): Promise<LLMModelSettings> =>
    putReq('/settings/llm-model', { model }),
  addLLMModel: (model: string): Promise<LLMModelSettings> =>
    postReq('/settings/llm-models', { model }),
  deleteLLMModel: (model: string): Promise<LLMModelSettings> =>
    deleteReq('/settings/llm-models', { data: { model } }),
  addLLMProvider: (data: LLMProviderInput): Promise<LLMModelSettings> =>
    postReq('/settings/llm-providers', data),
  getLLMProviderCapabilities: (providerKey: string, signal?: AbortSignal): Promise<LLMProviderCapabilities> =>
    getReq(`/settings/llm-providers/${encodeURIComponent(providerKey)}/capabilities`, { signal }),
  testLLMProvider: (
    providerKey: string,
    selection: { model: string; reasoningEffort: string; speedMode: string },
    signal?: AbortSignal,
  ): Promise<{ ok: boolean; providerKey: string; model: string; status: string; durationMs?: number }> =>
    postReq(`/settings/llm-providers/${encodeURIComponent(providerKey)}/test`, selection, { signal }),
  updateLLMProvider: (
    providerKey: string,
    changes: {
      enabled?: boolean;
      defaultModel?: string;
      models?: string[];
      reasoningEfforts?: string[];
      speedModes?: string[];
    },
    signal?: AbortSignal,
  ): Promise<LLMProviderCapabilities> =>
    patchReq(`/settings/llm-providers/${encodeURIComponent(providerKey)}`, changes, { signal }),
  setLLMProvider: (providerKey: string): Promise<LLMModelSettings> =>
    putReq('/settings/llm-provider', { providerKey }),
  testLLMModel: (signal?: AbortSignal): Promise<{ ok: boolean; model: string; baseUrl: string; reply: string }> =>
    postReq('/settings/llm-model/test', undefined, { signal }),
  getMcpAgentTokens: (): Promise<McpAgentTokenListResponse> =>
    getReq('/settings/mcp-agent-tokens'),
  createMcpAgentToken: (data: McpAgentTokenCreateInput): Promise<McpAgentTokenCreateResponse> =>
    postReq('/settings/mcp-agent-tokens', data),
  revokeMcpAgentToken: (tokenId: number): Promise<{ id: number; revokedAt: string }> =>
    deleteReq(`/settings/mcp-agent-tokens/${tokenId}`),
  getStrategyProfitPush: (): Promise<{
    enabled: boolean;
    intervalMinutes: number;
    running: boolean;
    lastStartedAt?: string | null;
    lastSentAt?: string | null;
    lastFinishedAt?: string | null;
    lastError?: string | null;
    lastSkipReason?: string | null;
    notifyReady: boolean;
    notifyEnabled: boolean;
    webhookConfigured: boolean;
    profitReportImageReady?: boolean;
    profitReportImageConfigured?: boolean;
    profitReportImageCjkFontAvailable?: boolean;
    profitReportImageReason?: string | null;
    lastDeliveryType?: string | null;
    lastDeliveryError?: string | null;
  }> => getReq('/settings/strategy-profit-push'),
  setStrategyProfitPush: (data: {
    enabled?: boolean;
    intervalMinutes?: number;
  }): Promise<{
    enabled: boolean;
    intervalMinutes: number;
    running: boolean;
    lastStartedAt?: string | null;
    lastSentAt?: string | null;
    lastFinishedAt?: string | null;
    lastError?: string | null;
    lastSkipReason?: string | null;
    notifyReady: boolean;
    notifyEnabled: boolean;
    webhookConfigured: boolean;
    profitReportImageReady?: boolean;
    profitReportImageConfigured?: boolean;
    profitReportImageCjkFontAvailable?: boolean;
    profitReportImageReason?: string | null;
    lastDeliveryType?: string | null;
    lastDeliveryError?: string | null;
  }> => postReq('/settings/strategy-profit-push', data),
  sendStrategyProfitPushNow: (): Promise<{
    enabled: boolean;
    intervalMinutes: number;
    running: boolean;
    lastSentAt?: string | null;
    lastError?: string | null;
    lastSkipReason?: string | null;
    result?: Record<string, unknown>;
    notifyReady: boolean;
    notifyEnabled: boolean;
    webhookConfigured: boolean;
    profitReportImageReady?: boolean;
    profitReportImageConfigured?: boolean;
    profitReportImageCjkFontAvailable?: boolean;
    profitReportImageReason?: string | null;
    lastDeliveryType?: string | null;
    lastDeliveryError?: string | null;
  }> => postReq('/settings/strategy-profit-push/test'),
  getLiveProfitPush: (): Promise<{
    enabled: boolean;
    intervalMinutes: number;
    running: boolean;
    lastStartedAt?: string | null;
    lastSentAt?: string | null;
    lastFinishedAt?: string | null;
    lastError?: string | null;
    lastSkipReason?: string | null;
    notifyReady: boolean;
    notifyEnabled: boolean;
    webhookConfigured: boolean;
    profitReportImageReady?: boolean;
    profitReportImageConfigured?: boolean;
    profitReportImageCjkFontAvailable?: boolean;
    profitReportImageReason?: string | null;
    lastDeliveryType?: string | null;
    lastDeliveryError?: string | null;
  }> => getReq('/settings/live-profit-push'),
  setLiveProfitPush: (data: {
    enabled?: boolean;
    intervalMinutes?: number;
  }): Promise<{
    enabled: boolean;
    intervalMinutes: number;
    running: boolean;
    lastStartedAt?: string | null;
    lastSentAt?: string | null;
    lastFinishedAt?: string | null;
    lastError?: string | null;
    lastSkipReason?: string | null;
    notifyReady: boolean;
    notifyEnabled: boolean;
    webhookConfigured: boolean;
    profitReportImageReady?: boolean;
    profitReportImageConfigured?: boolean;
    profitReportImageCjkFontAvailable?: boolean;
    profitReportImageReason?: string | null;
    lastDeliveryType?: string | null;
    lastDeliveryError?: string | null;
  }> => postReq('/settings/live-profit-push', data),
  sendLiveProfitPushNow: (): Promise<{
    enabled: boolean;
    intervalMinutes: number;
    running: boolean;
    lastSentAt?: string | null;
    lastError?: string | null;
    lastSkipReason?: string | null;
    result?: Record<string, unknown>;
    notifyReady: boolean;
    notifyEnabled: boolean;
    webhookConfigured: boolean;
    profitReportImageReady?: boolean;
    profitReportImageConfigured?: boolean;
    profitReportImageCjkFontAvailable?: boolean;
    profitReportImageReason?: string | null;
    lastDeliveryType?: string | null;
    lastDeliveryError?: string | null;
  }> => postReq('/settings/live-profit-push/test'),
};

// ============================================
// 健康检查 API
// ============================================

export const healthApi = {
  check: (): Promise<{ status: string }> => getReq('/system/health'),
  checkExchanges: (): Promise<{ exchanges: Record<string, string> }> =>
    getReq('/system/exchanges'),
};

// ============================================
// AI Agent API
// ============================================

export const agentApi = {
  createTask: (data: {
    [key: string]: unknown;
  }): Promise<{ taskId: string; status: string; message: string }> =>
    postReq('/agent/tasks', data),

  listTasks: (): Promise<any[]> => getReq('/agent/tasks'),

  getTask: (taskId: string): Promise<any> => getReq(`/agent/tasks/${taskId}`),

  getIterations: (taskId: string): Promise<any[]> =>
    getReq(`/agent/tasks/${taskId}/iterations`),

  stopTask: (taskId: string): Promise<any> =>
    postReq(`/agent/tasks/${taskId}/stop`),

  acceptBest: (taskId: string): Promise<any> =>
    postReq(`/agent/tasks/${taskId}/accept`),

  generateStrategy: (data: {
    prompt: string;
    symbol?: string;
    timeframe?: string;
  }): Promise<{
    strategyId: number;
    className: string;
    fileName: string;
    description: string;
    modulePath: string;
    message: string;
  }> => postReq('/agent/generate_strategy', data),
};

// ============================================
// 回测 API
// ============================================

export const backtestApi = {
  getConfiguration: (): Promise<{
    items: Array<{
      datasetSnapshotId: number;
      datasetSnapshotName: string;
      poolSnapshotId: number;
      poolName: string;
      startDate: string;
      endDate: string;
      memberCount: number;
      knowledgeCutoffAt?: string | null;
    }>;
  }> => getReq('/backtest/configuration'),

  runSync: (data: Record<string, unknown>): Promise<any> =>
    postReq('/backtest/run_sync', data, { timeout: BACKTEST_RUN_SYNC_TIMEOUT_MS }),

  /** 异步回测：立即返回 jobId，进度见 getJob（PostgreSQL 持久化，刷新页面或服务重启后可继续轮询） */
  runJob: (data: Record<string, unknown>): Promise<{ jobId: string }> =>
    postReq('/backtest/run_job', data),

  /** 便捷批量回测：为所有运行中的模拟策略创建普通异步回测任务 */
  runRunningStrategies: (data?: Record<string, unknown>): Promise<{
    count: number;
    skippedCount: number;
    defaults: {
      startDate: string;
      endDate: string;
      initialCapital: number;
      timeframeMode: string;
    };
    jobs: Array<{
      jobId: string;
      strategyId: number;
      strategyName?: string | null;
      status: string;
      request?: Record<string, any> | null;
    }>;
    skipped: Array<{
      strategyId?: number | null;
      strategyName?: string | null;
      status?: string | null;
      reason: string;
    }>;
  }> => postReq('/backtest/run_running_strategies', data ?? {}),

  getJob: (
    jobId: string,
  ): Promise<{
    jobId: string;
    strategyId: number;
    status: string;
    currentBar: number;
    totalBars: number;
    percent: number | null;
    message?: string | null;
    result?: any;
    errorMessage?: string | null;
    updatedAt?: string | null;
    resumable?: boolean;
  }> => getReq(`/backtest/job/${jobId}`),

  cancelJob: (
    jobId: string,
  ): Promise<{
    jobId: string;
    strategyId: number;
    status: string;
    currentBar: number;
    totalBars: number;
    percent: number | null;
    message?: string | null;
    result?: any;
    errorMessage?: string | null;
    updatedAt?: string | null;
    resumable?: boolean;
  }> => postReq(`/backtest/job/${jobId}/cancel`),

  resumeJob: (
    jobId: string,
  ): Promise<{
    jobId: string;
    strategyId: number;
    status: string;
    currentBar: number;
    totalBars: number;
    percent: number | null;
    message?: string | null;
    result?: any;
    errorMessage?: string | null;
    updatedAt?: string | null;
    resumable?: boolean;
  }> => postReq(`/backtest/job/${jobId}/resume`),

  getJobs: (
    params?: { strategyId?: number | null; status?: string; limit?: number; includeResult?: boolean },
  ): Promise<Array<{
    jobId: string;
    strategyId: number;
    status: string;
    currentBar: number;
    totalBars: number;
    percent: number | null;
    request?: Record<string, unknown> | null;
    message?: string | null;
    result?: any;
    errorMessage?: string | null;
    updatedAt?: string | null;
    resumable?: boolean;
  }>> => getReq('/backtest/jobs', {
    params: {
      strategyId: params?.strategyId ?? undefined,
      status: params?.status,
      limit: params?.limit ?? 50,
      include_result: params?.includeResult ?? undefined,
    },
  }),

  getResults: (
    params?: {
      strategyId?: number | null;
      query?: string;
      limit?: number;
      offset?: number;
      sortBy?: 'created' | 'return' | 'drawdown' | 'win_rate';
      sortDir?: 'asc' | 'desc';
      includeMatrixSummary?: boolean;
    },
  ): Promise<any[]> =>
    getReq('/backtest/results', {
      params: {
        strategyId: params?.strategyId ?? undefined,
        q: params?.query || undefined,
        limit: params?.limit ?? 20,
        offset: params?.offset ?? undefined,
        sort_by: params?.sortBy,
        sort_dir: params?.sortDir,
        include_matrix_summary: params?.includeMatrixSummary ?? undefined,
      },
    }),

  getResult: (id: number): Promise<any> =>
    getReq(`/backtest/result/${id}`),

  deleteResult: (id: number): Promise<{ deleted: boolean; id: number }> =>
    deleteReq(`/backtest/result/${id}`),

  getStrategies: (): Promise<Record<string, unknown>> =>
    getReq('/backtest/strategies'),
};

export interface OrderflowLargeTrade {
  instId: string;
  tradeId: string;
  px: number;
  szBase: number;
  notionalUsdt: number;
  side: 'buy' | 'sell';
  tradeTs: number;
}

export interface OrderflowBar {
  barTs: number;
  symbol?: string;
  openPx?: number | null;
  closePx?: number | null;
  volume?: number | null;
  amount?: number | null;
  source?: string;
  dataStatus?: string;
  buyNotional: number;
  sellNotional: number;
  delta: number;
  cumDelta: number;
  tradeCount: number;
  vwap: number | null;
  lowPx: number;
  highPx: number;
}

export interface OrderflowSymbolStat {
  instId: string;
  tradeCount: number;
  totalNotional: number;
  lastTs: number;
}

export interface OrderflowStreamStatus {
  dataStatus?: string;
  providerSource?: string;
  permissionState?: string;
  frequency?: string;
  tables?: string[];
  setupPath?: string;
  enabled: boolean;
  connected: boolean;
  subscribedCount: number;
  totalIngested: number;
  totalFiltered: number;
  bufferSize: number;
  reconnects: number;
  lastMsgAt: number | null;
  lastFlushAt: number | null;
  lastError: string | null;
  lastSuccessAt?: string | null;
  cacheAgeSeconds?: number | null;
  nextRetryAt?: string | null;
  minNotionalUsdt: number;
  instIds: string[];
}

export const orderflowApi = {
  getLargeTrades: (params: {
    instId: string;
    hours?: number;
    minNotional?: number;
    side?: 'buy' | 'sell';
    limit?: number;
  }): Promise<{ items: OrderflowLargeTrade[]; count: number }> =>
    getReq('/orderflow/large-trades', { params }),

  getBars: (params: {
    instId: string;
    barMinutes?: number;
    hours?: number;
  }): Promise<{
    items: OrderflowBar[];
    barMinutes: number;
    count: number;
    dataStatus?: string;
    providerSource?: string;
    permissionState?: string;
    frequency?: string;
    unavailableReason?: string | null;
    lastError?: string | null;
    asOf?: number;
    lastSuccessAt?: string | null;
    cacheAgeSeconds?: number | null;
    nextRetryAt?: string | null;
  }> =>
    getReq('/orderflow/bars', { params }),

  getSymbols: (params: { hours?: number }): Promise<{ items: OrderflowSymbolStat[]; count: number }> =>
    getReq('/orderflow/symbols', { params }),

  getStreamStatus: (): Promise<OrderflowStreamStatus> =>
    getReq('/orderflow/stream-status'),
};

export default api;
