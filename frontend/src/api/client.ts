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
import type {
  DailyBarsResponse,
  InstrumentContract,
  InstrumentDetailView,
  MarketOverviewView,
  MarketWatchlistEntry,
  OrderBookView,
  StockPoolMember,
  StockPoolRecord,
  StockPoolSnapshot,
  FactorLibraryRecord,
  FactorMetricRecord,
} from '../types/research';
import type { StrategyValidationResult, StrategyVersionRecord } from '../types/strategy';
import type { BacktestConfiguration, BacktestJobRecord, BacktestRunRecord } from '../types/backtest';
import type { PaperInstanceDetail, PaperInstanceList } from '../types/paper';
import type { DailyReviewView, MonitorSummary, OperationAlert, OperationSignal, WatchContext, WatchRule } from '../types/operations';
import type { DataJob, DataStatus, DatasetRecord, ExtensionImport, SnapshotRecord } from '../types/data';
import type { AIConfig, AITask } from '../types/ai';

const API_BASE = '/api';

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

export const apiClient = axios.create({
  baseURL: API_BASE,
  timeout: DEFAULT_TIMEOUT_MS,
  withCredentials: true,
});

const api = apiClient;

export const researchApi = {
  marketOverview: async (): Promise<MarketOverviewView> =>
    apiClient.get<MarketOverviewView, MarketOverviewView>('/market/overview'),
  searchInstruments: async (
    query: string,
    assetClass: 'stock' | 'etf' | 'index' | null,
    limit = 30,
  ): Promise<{ items: InstrumentContract[]; query: string; asset_class: string | null }> =>
    apiClient.get('/market/instruments', { params: { q: query, asset_class: assetClass || undefined, limit } }),
  instrumentDetail: async (symbol: string): Promise<InstrumentDetailView> =>
    apiClient.get(`/market/instruments/${encodeURIComponent(symbol)}`),
  dailyBars: async (symbol: string, limit = 500): Promise<DailyBarsResponse> =>
    apiClient.get(`/market/instruments/${encodeURIComponent(symbol)}/daily`, { params: { limit } }),
  orderBook: async (symbol: string): Promise<OrderBookView> =>
    apiClient.get(`/market/instruments/${encodeURIComponent(symbol)}/order-book`),
  watchlist: async (): Promise<{ items: MarketWatchlistEntry[] }> =>
    apiClient.get('/market/watchlist'),
  addWatchlist: async (symbol: string, note = ''): Promise<MarketWatchlistEntry> =>
    apiClient.post('/market/watchlist', { symbol, note }),
  deleteWatchlist: async (entryId: number): Promise<{ deleted: boolean; id: number }> =>
    apiClient.delete(`/market/watchlist/${entryId}`),
  pools: async (): Promise<{ items: StockPoolRecord[] }> =>
    apiClient.get('/pools'),
  pool: async (poolId: string): Promise<StockPoolRecord> =>
    apiClient.get(`/pools/${encodeURIComponent(poolId)}`),
  poolMembers: async (poolId: string, generationId?: string): Promise<{ items: StockPoolMember[] }> =>
    apiClient.get(`/pools/${encodeURIComponent(poolId)}/members`, { params: { generation_id: generationId } }),
  poolSnapshots: async (poolId: string): Promise<{ items: StockPoolSnapshot[] }> =>
    apiClient.get(`/pools/${encodeURIComponent(poolId)}/snapshots`),
  createPool: async (payload: Record<string, unknown>): Promise<StockPoolRecord> =>
    apiClient.post('/pools', payload),
  generatePool: async (poolId: string, payload: Record<string, unknown>): Promise<Record<string, unknown>> =>
    apiClient.post(`/pools/${encodeURIComponent(poolId)}/generate`, payload),
  sealPoolSnapshot: async (poolId: string, generationId: string): Promise<StockPoolSnapshot> =>
    apiClient.post(`/pools/${encodeURIComponent(poolId)}/snapshots`, { generation_id: generationId }),
  factors: async (): Promise<{ items: FactorLibraryRecord[] }> =>
    apiClient.get('/factors'),
  factorMetrics: async (factorCode: string): Promise<{ factor: FactorLibraryRecord; items: FactorMetricRecord[] }> =>
    apiClient.get(`/factors/${encodeURIComponent(factorCode)}/metrics`),
  factorValues: async (factorCode: string, limit = 500, offset = 0): Promise<{ items: Record<string, unknown>[] }> =>
    apiClient.get(`/factors/${encodeURIComponent(factorCode)}/values`, { params: { limit, offset } }),
  factorRuns: async (limit = 100): Promise<{ items: Record<string, any>[] }> =>
    apiClient.get('/factor-runs', { params: { limit } }),
  factorCorrelations: async (limit = 500): Promise<{ items: Record<string, any>[] }> =>
    apiClient.get('/factor-correlations', { params: { limit } }),
  factorSnapshots: async (limit = 50): Promise<{ items: Record<string, any>[] }> =>
    apiClient.get('/factor-snapshots', { params: { limit } }),
  computeFactor: async (versionId: number, payload: { trade_date: string; dataset_snapshot_id: number; universe_snapshot_id: number }): Promise<Record<string, unknown>> =>
    apiClient.post(`/factor-versions/${versionId}/compute`, payload),
};

export const strategyCurrentApi = {
  list: async (): Promise<{ items: StrategyVersionRecord[] }> => apiClient.get('/strategies'),
  detail: async (versionId: string): Promise<StrategyVersionRecord> => apiClient.get(`/strategies/${encodeURIComponent(versionId)}`),
  create: async (payload: { name: string; description: string; script_content: string }): Promise<{ strategy_version: StrategyVersionRecord; validation: StrategyValidationResult }> => apiClient.post('/strategies', payload),
  createVersion: async (parentId: string, payload: { description?: string; script_content: string }): Promise<{ strategy_version: StrategyVersionRecord; validation: StrategyValidationResult }> => apiClient.post(`/strategies/${encodeURIComponent(parentId)}/versions`, payload),
  validate: async (scriptContent: string): Promise<StrategyValidationResult> => apiClient.post('/strategies/validate', { script_content: scriptContent }),
  quickRun: async (versionId: string, payload: Record<string, unknown>): Promise<Record<string, unknown>> => apiClient.post(`/strategies/${encodeURIComponent(versionId)}/quick-run`, payload),
};

export const backtestCurrentApi = {
  configuration: async (): Promise<BacktestConfiguration> => apiClient.get('/backtest/configuration'),
  runs: async (limit = 200): Promise<{ items: BacktestRunRecord[] }> => apiClient.get('/backtest/runs', { params: { limit } }),
  run: async (runId: string): Promise<Record<string, any>> => apiClient.get(`/backtest/runs/${encodeURIComponent(runId)}`),
  metrics: async (runId: string): Promise<{ items: Record<string, any>[] }> => apiClient.get(`/backtest/runs/${encodeURIComponent(runId)}/metrics`),
  series: async (runId: string): Promise<Record<string, any>> => apiClient.get(`/backtest/runs/${encodeURIComponent(runId)}/series`),
  detailRows: async (runId: string, kind: 'orders' | 'trades' | 'positions' | 'logs'): Promise<{ items: Record<string, any>[] }> => apiClient.get(`/backtest/runs/${encodeURIComponent(runId)}/${kind}`),
  jobs: async (limit = 200): Promise<{ items: BacktestJobRecord[] }> => apiClient.get('/backtest/jobs', { params: { limit } }),
  createJob: async (payload: Record<string, unknown>): Promise<BacktestJobRecord> => apiClient.post('/backtest/jobs', payload),
  cancelJob: async (jobId: string): Promise<BacktestJobRecord> => apiClient.post(`/backtest/jobs/${encodeURIComponent(jobId)}/cancel`),
  retryJob: async (jobId: string): Promise<BacktestJobRecord> => apiClient.post(`/backtest/jobs/${encodeURIComponent(jobId)}/retry`),
  matrix: async (payload: Record<string, unknown>): Promise<Record<string, unknown>> => apiClient.post('/backtest/matrix', payload),
  walkForward: async (payload: Record<string, unknown>): Promise<Record<string, unknown>> => apiClient.post('/backtest/walk-forward', payload),
};

export const paperCurrentApi = {
  list: async (scope: 'business' | 'audit' = 'audit'): Promise<PaperInstanceList> =>
    apiClient.get('/paper/instances', { params: { scope } }),
  detail: async (instanceId: string): Promise<PaperInstanceDetail> =>
    apiClient.get(`/paper/instances/${encodeURIComponent(instanceId)}`),
  create: async (payload: Record<string, unknown>): Promise<PaperInstanceDetail> =>
    apiClient.post('/paper/instances', payload),
  transition: async (instanceId: string, action: 'start' | 'pause' | 'resume' | 'stop'): Promise<PaperInstanceDetail> =>
    apiClient.post(`/paper/instances/${encodeURIComponent(instanceId)}/${action}`),
  advance: async (instanceId: string, maxDates = 1): Promise<Record<string, unknown>> =>
    apiClient.post(`/paper/instances/${encodeURIComponent(instanceId)}/advance`, { max_dates: maxDates }),
};

export const operationsCurrentApi = {
  signals: async (scope: 'business' | 'audit' = 'business'): Promise<{ items: OperationSignal[]; total: number; scope: string }> => apiClient.get('/signals', { params: { scope } }),
  signal: async (signalId: string): Promise<OperationSignal> => apiClient.get(`/signals/${encodeURIComponent(signalId)}`),
  acknowledgeSignal: async (signalId: string): Promise<OperationSignal> => apiClient.post(`/signals/${encodeURIComponent(signalId)}/acknowledge`),
  context: async (scope: 'business' | 'audit' = 'business'): Promise<WatchContext> => apiClient.get('/watch/context', { params: { scope } }),
  alerts: async (status?: string): Promise<{ items: OperationAlert[]; total: number }> => apiClient.get('/watch/alerts', { params: { status } }),
  acknowledgeAlert: async (alertId: string): Promise<OperationAlert> => apiClient.post(`/watch/alerts/${encodeURIComponent(alertId)}/acknowledge`),
  rules: async (scope: 'business' | 'audit' = 'business'): Promise<{ items: WatchRule[]; total: number; scope: string }> => apiClient.get('/watch/rules', { params: { scope } }),
  previewRule: async (ruleId: string): Promise<Record<string, any>> => apiClient.post(`/watch/rules/${encodeURIComponent(ruleId)}/preview`),
  evaluateRule: async (ruleId: string): Promise<Record<string, any>> => apiClient.post(`/watch/rules/${encodeURIComponent(ruleId)}/evaluate`),
  scheduler: async (): Promise<{ running: boolean; timezone: string; jobs: Array<{ id: string; name: string; next_run_at: string | null; trigger: string }>; schedule?: { enabled: boolean; cron: string; dailyBarsWatermark?: string | null }; last_results?: Record<string, unknown> }> => apiClient.get('/operations/scheduler'),
  updateDailyReferenceSchedule: async (payload: Record<string, unknown>): Promise<Record<string, any>> => apiClient.put('/operations/scheduler/daily-reference', payload),
  runDailyReference: async (tradeDate?: string | null, force = false): Promise<Record<string, any>> => apiClient.post('/operations/scheduler/daily-reference/run', { trade_date: tradeDate ?? null, force }),
  advanceAllPaper: async (maxDates = 260): Promise<Record<string, any>> => apiClient.post('/operations/paper/advance', { max_dates: maxDates }),
};

export const monitorCurrentApi = {
  summary: async (scope: 'business' | 'audit' = 'business'): Promise<MonitorSummary> => apiClient.get('/monitor/summary', { params: { scope }, timeout: 60_000 }),
};

export const reviewCurrentApi = {
  dates: async (limit = 120): Promise<{ items: string[]; total: number }> => apiClient.get('/review/dates', { params: { limit } }),
  list: async (limit = 100): Promise<{ items: Array<Record<string, any>>; total: number }> => apiClient.get('/review', { params: { limit } }),
  get: async (tradeDate: string): Promise<DailyReviewView> => apiClient.get(`/review/${encodeURIComponent(tradeDate)}`),
  assemble: async (tradeDate: string): Promise<DailyReviewView> => apiClient.post(`/review/${encodeURIComponent(tradeDate)}/assemble`),
  save: async (tradeDate: string, payload: { summary: string; next_day_plan: string }): Promise<DailyReviewView> => apiClient.put(`/review/${encodeURIComponent(tradeDate)}`, payload),
  seal: async (tradeDate: string): Promise<DailyReviewView> => apiClient.post(`/review/${encodeURIComponent(tradeDate)}/seal`),
};

export const dataCurrentApi = {
  status: async ():Promise<DataStatus>=>apiClient.get('/data/status'),
  datasets: async ():Promise<{items:DatasetRecord[];total:number}>=>apiClient.get('/data/datasets'),
  snapshots: async ():Promise<{items:SnapshotRecord[];total:number}>=>apiClient.get('/data/snapshots'),
  providers: async ():Promise<{items:Array<Record<string,any>>;total:number;provider_calls_performed:number}>=>apiClient.get('/data/providers'),
  schedules: async ():Promise<{items:Array<Record<string,any>>;total:number}>=>apiClient.get('/data/schedules'),
  jobs: async ():Promise<{items:DataJob[];total:number}>=>apiClient.get('/data/jobs'),
  quality: async ():Promise<{items:Array<Record<string,any>>;total:number}>=>apiClient.get('/data/quality'),
  imports: async ():Promise<{items:ExtensionImport[];total:number}>=>apiClient.get('/data/exchange/imports'),
  createJob: async (payload:Record<string,unknown>):Promise<DataJob>=>apiClient.post('/data/sync',payload),
  createQualityJob: async (payload:Record<string,unknown>):Promise<DataJob>=>apiClient.post('/data/quality/run',payload),
  stageImport: async (payload:Record<string,unknown>):Promise<ExtensionImport>=>apiClient.post('/data/exchange/imports',payload),
  qlibStatus: async ():Promise<Record<string,any>>=>apiClient.get('/data/qlib/status'),
  qlibExport: async (force=false):Promise<Record<string,any>>=>apiClient.post(`/data/qlib/export?force=${force?'true':'false'}`),
};

export interface OkxNativeSyncScheduleConfig {
  enabled: boolean;
  rubikIntervalMinutes: number;
  oiIntervalMinutes: number;
  ccys: string[];
  rubikRowCount: number;
  oiSnapshotCount: number;
  oiSymbolCount: number;
  lastRubikRunAt?: string | null;
  lastRubikFinishedAt?: string | null;
  lastRubikError?: string | null;
  lastOiRunAt?: string | null;
  lastOiFinishedAt?: string | null;
  lastOiError?: string | null;
}

export const okxNativeSyncApi = {
  getSchedule: (): Promise<OkxNativeSyncScheduleConfig> => Promise.reject(new Error('StockPro 不注册 OKX 原生同步')),
  updateSchedule: (_data: Partial<OkxNativeSyncScheduleConfig>): Promise<OkxNativeSyncScheduleConfig> => Promise.reject(new Error('StockPro 不注册 OKX 原生同步')),
  run: (_kind: 'rubik' | 'oi' | 'all'): Promise<Record<string, unknown>> => Promise.reject(new Error('StockPro 不注册 OKX 原生同步')),
};

export const aiCurrentApi={
  config:async():Promise<AIConfig>=>apiClient.get('/ai/config'),
  tasks:async():Promise<{items:AITask[];total:number}>=>apiClient.get('/ai/tasks'),
  task:async(id:string):Promise<AITask>=>apiClient.get(`/ai/tasks/${encodeURIComponent(id)}`),
  create:async(payload:Record<string,unknown>):Promise<AITask>=>apiClient.post('/ai/tasks',payload),
  start:async(id:string):Promise<AITask>=>apiClient.post(`/ai/tasks/${encodeURIComponent(id)}/start`),
  stop:async(id:string):Promise<AITask>=>apiClient.post(`/ai/tasks/${encodeURIComponent(id)}/stop`),
  promote:async(iterationId:string):Promise<Record<string,unknown>>=>apiClient.post(`/ai/iterations/${encodeURIComponent(iterationId)}/promote-candidate`),
};

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

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
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

export const factorLabApi = {
  getSummary: (): Promise<FactorLabSummary> =>
    getReq('/factorlab/summary'),
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

export const marketApi = {
  getTicker: (exchange: string, symbol: string): Promise<Ticker> =>
    getReq('/market/ticker', { params: { exchange, symbol } }),

  getTickers: (exchange: string, symbols?: string[]): Promise<Ticker[]> =>
    getReq('/market/tickers', {
      params: { exchange, symbols: symbols?.join(','), offset: 0, limit: 500 },
    }),

  getAllTickers: async (
    exchange: string,
    scope: { quote: string; marketType: 'spot' | 'swap' | 'future' | 'all' },
  ): Promise<Ticker[]> => {
    const items: Ticker[] = [];
    const limit = 500;
    let offset = 0;
    let total = 0;

    do {
      const page = await getPagedReq<Ticker[]>('/market/tickers', {
        params: { exchange, quote: scope.quote, marketType: scope.marketType, offset, limit },
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
    getReq('/market/klines', {
      params: { exchange, symbol, timeframe, limit, start, end },
    }),

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

  getSymbols: (exchange: string, quote = 'USDT', marketType = 'spot'): Promise<{ symbols: string[] }> =>
    getReq('/market/symbols', { params: { exchange, quote, market_type: marketType } }),
};

// ============================================
// 资金费率 API
// ============================================

export const fundingApi = {
  getRates: (exchange: string, symbols?: string[]): Promise<FundingRate[]> =>
    getReq('/funding/rates', {
      params: { exchange, symbols: symbols?.join(',') },
    }),

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

const strategyVersionIdByLegacyId = new Map<number, string>();
const backtestRunIdByLegacyId = new Map<number, string>();

function stableLegacyId(value: unknown): number {
  const text = String(value ?? '');
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return Math.max(1, hash >>> 0);
}

function bridgeStrategy(item: Strategy & Record<string, any>): Strategy {
  const versionId = String(item.id ?? '');
  const explicitLegacyId = Number(item.legacyStrategyId ?? item.legacy_strategy_id);
  const legacyId = Number.isFinite(explicitLegacyId) && explicitLegacyId > 0
    ? explicitLegacyId
    : stableLegacyId(versionId);
  strategyVersionIdByLegacyId.set(legacyId, versionId);
  return {
    ...item,
    id: legacyId,
    exchange: 'cn',
    scriptContent: item.scriptContent ?? item.script_content ?? '',
    config: {
      ...(item.config || {}),
      strategyVersionId: versionId,
      assetClass: item.config?.assetClass ?? 'stock',
    },
    symbols: Array.isArray(item.symbols) ? item.symbols : [],
    status: item.status || 'stopped',
    createdAt: item.createdAt ?? item.created_at ?? '',
    updatedAt: item.updatedAt ?? item.updated_at ?? item.createdAt ?? item.created_at ?? '',
  };
}

function strategyVersionIdForLegacyId(value: unknown): string {
  const legacyId = Number(value);
  return strategyVersionIdByLegacyId.get(legacyId) || String(value ?? '');
}

function registerBacktestRunId(value: unknown): number {
  const runId = String(value ?? '');
  const legacyId = stableLegacyId(runId);
  backtestRunIdByLegacyId.set(legacyId, runId);
  return legacyId;
}

function backtestRunIdForLegacyId(value: unknown): string {
  const legacyId = Number(value);
  return backtestRunIdByLegacyId.get(legacyId) || String(value ?? '');
}

export const strategyApi = {
  getPage: async (params: {
    page: number;
    perPage: number;
    search?: string;
    status?: string;
    assetClass?: string;
    strategyType?: string;
    timeframe?: string;
    capital?: string;
  }): Promise<StrategyPageResponse> => {
    const response = await getReq<Partial<StrategyPageResponse> & { items?: Strategy[] }>('/strategies');
    const allItems = (Array.isArray(response.items) ? response.items : []).map((item) =>
      bridgeStrategy(item as Strategy & Record<string, any>),
    );
    const search = (params.search || '').trim().toLowerCase();
    const filtered = allItems.filter((item) => {
      if (search && !`${item.name || ''} ${item.description || ''}`.toLowerCase().includes(search)) return false;
      if (params.status && params.status !== 'all') {
        const normalized = item.status || 'not_started';
        if (normalized !== params.status) return false;
      }
      return true;
    });
    const page = Math.max(1, params.page);
    const perPage = Math.max(1, params.perPage);
    const total = filtered.length;
    const pages = Math.max(1, Math.ceil(total / perPage));
    const items = filtered.slice((page - 1) * perPage, page * perPage);
    const statusCounts = allItems.reduce<Record<string, number>>((counts, item) => {
      const key = item.status || 'not_started';
      counts[key] = (counts[key] || 0) + 1;
      return counts;
    }, { all: allItems.length });
    const stockCount = allItems.filter((item) => !item.symbols?.some((symbol) => /^(15|16|51|56|58)/.test(symbol))).length;
    return {
      items,
      total,
      page,
      perPage,
      pages,
      statusCounts,
      assetCounts: { all: allItems.length, stock: stockCount, etf: allItems.length - stockCount },
      typeCounts: response.typeCounts || { all: allItems.length },
      timeframeCounts: response.timeframeCounts || { all: allItems.length },
      capitalCounts: response.capitalCounts || { all: allItems.length },
    };
  },

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

// BitPro live workspace compatibility surface. The UI is copied from BitPro,
// while every data call stays on StockPro's A-share Paper/broker contracts.
export const tradingApi = {
  getBalance: (accountId = 'default'): Promise<{ exchange: string; balance: any[] }> =>
    liveExecutionApi.getAccountBalance(accountId),
};

export const liveApi = {
  getStrategies: (params?: { page?: number; perPage?: number }): Promise<StrategyPageResponse> =>
    strategyApi.getPage({
      page: params?.page ?? 1,
      perPage: params?.perPage ?? 60,
    }),

  getStrategyTrades: (id: number, limit = 50): Promise<any> =>
    getReq(`/strategies/${id}/trades`, { params: { limit } }),

  configure: (config: Record<string, unknown>): Promise<any> =>
    paperCurrentApi.create(config),

  start: (instanceId?: string | number): Promise<any> => {
    if (instanceId == null) return Promise.reject(new Error('启动 A 股模拟实例需要明确 instance_id'));
    return paperCurrentApi.transition(String(instanceId), 'start');
  },

  stop: (instanceId?: string | number, _clearMetrics = false): Promise<any> => {
    if (instanceId == null) return Promise.reject(new Error('停止 A 股模拟实例需要明确 instance_id'));
    return paperCurrentApi.transition(String(instanceId), 'stop');
  },

  pause: (instanceId?: string | number): Promise<any> => {
    if (instanceId == null) return Promise.reject(new Error('暂停 A 股模拟实例需要明确 instance_id'));
    return paperCurrentApi.transition(String(instanceId), 'pause');
  },

  resume: (instanceId?: string | number): Promise<any> => {
    if (instanceId == null) return Promise.reject(new Error('恢复 A 股模拟实例需要明确 instance_id'));
    return paperCurrentApi.transition(String(instanceId), 'resume');
  },

  closePaperPosition: (payload: {
    instanceId?: string | number;
    symbol: string;
    side?: string | null;
    marketType?: string | null;
  }): Promise<any> => {
    if (payload.instanceId == null) return Promise.reject(new Error('平仓需要明确 A 股模拟实例'));
    return postReq(`/paper/instances/${encodeURIComponent(String(payload.instanceId))}/positions/close`, payload);
  },

  getDashboard: (instanceId?: string | number): Promise<any> =>
    instanceId == null
      ? paperCurrentApi.list('audit')
      : paperCurrentApi.detail(String(instanceId)),

  getEvents: async (
    limit = 50,
    _eventType?: string,
    instanceId?: string | number,
  ): Promise<any> => {
    if (instanceId == null) return [];
    const detail = await paperCurrentApi.detail(String(instanceId));
    return detail.events.slice(0, limit);
  },

  getEquityCurve: async (instanceId?: string | number): Promise<any> => {
    if (instanceId == null) return [];
    const detail = await paperCurrentApi.detail(String(instanceId));
    return detail.equity_snapshots;
  },

  preFlight: (config: Record<string, unknown>): Promise<any> =>
    postReq('/paper/preflight', config),

  promoteToLive: (config: {
    sourceStrategyId: string | number;
    accountId?: string;
    exchange?: string;
    initialEquity?: number;
    loopInterval?: number;
    startImmediately?: boolean;
    confirmPaperReviewed?: boolean;
    confirmLiveRisk?: boolean;
    riskConfig?: Record<string, unknown>;
  }): Promise<any> => liveExecutionApi.deployStrategy(Number(config.sourceStrategyId), {
    accountId: config.accountId,
    exchange: config.exchange,
    initialEquity: config.initialEquity,
    loopInterval: config.loopInterval,
    startImmediately: config.startImmediately,
    confirmPaperReviewed: config.confirmPaperReviewed === true,
    confirmLiveRisk: config.confirmLiveRisk === true,
    riskConfig: config.riskConfig,
  }),

  promoteToLivePreflight: (config: {
    sourceStrategyId: string | number;
    accountId?: string;
    exchange?: string;
    initialEquity?: number;
    loopInterval?: number;
    startImmediately?: boolean;
    riskConfig?: Record<string, unknown>;
  }): Promise<any> => liveExecutionApi.preflightStrategy(Number(config.sourceStrategyId), {
    accountId: config.accountId,
    exchange: config.exchange,
    initialEquity: config.initialEquity,
    loopInterval: config.loopInterval,
    startImmediately: config.startImmediately,
    riskConfig: config.riskConfig,
  }),
};

// ============================================
// 监控 API
// ============================================

export const monitorApi = {
  getAlerts: (): Promise<any[]> => getReq('/monitor/alerts'),

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

  getInstances: (): Promise<any> => getReq('/paper-trading/instances'),

  getInstance: (instanceId: string): Promise<any> => getReq(`/paper-trading/instances/${instanceId}`),

  deleteInstance: (instanceId: string): Promise<any> => deleteReq(`/paper-trading/instances/${instanceId}`),

  clearInstances: (): Promise<any> => deleteReq('/paper-trading/instances'),

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
    exchange: string | null;
    status: string | null;
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
}

export interface LLMProviderInput {
  providerKey: string;
  name: string;
  apiKeyEnv: string;
  baseUrl: string;
  defaultModel: string;
  models: string[];
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
  getLLMModel: (): Promise<LLMModelSettings> =>
    getReq('/settings/llm-model'),
  setLLMModel: (model: string): Promise<LLMModelSettings> =>
    putReq('/settings/llm-model', { model }),
  addLLMModel: (model: string): Promise<LLMModelSettings> =>
    postReq('/settings/llm-models', { model }),
  deleteLLMModel: (model: string): Promise<LLMModelSettings> =>
    deleteReq('/settings/llm-models', { data: { model } }),
  addLLMProvider: (data: LLMProviderInput): Promise<LLMModelSettings> =>
    postReq('/settings/llm-providers', data),
  setLLMProvider: (providerKey: string): Promise<LLMModelSettings> =>
    putReq('/settings/llm-provider', { providerKey }),
  testLLMModel: (): Promise<{ ok: boolean; model: string; baseUrl: string; reply: string }> =>
    postReq('/settings/llm-model/test'),
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

function currentBacktestRunToBitPro(run: Record<string, any>): Record<string, any> {
  const metrics = run.metrics || {};
  const initialCapital = Number(run.initialCash ?? run.initial_cash ?? 0);
  const strategyReturn = Number(metrics.strategyReturn ?? metrics.strategy_return);
  const maximumDrawdown = Number(metrics.maximumDrawdown ?? metrics.maximum_drawdown);
  const winRate = Number(metrics.winRate ?? metrics.win_rate);
  const runId = registerBacktestRunId(run.id);
  const versionId = String(run.strategyVersionId ?? run.strategy_version_id ?? '');
  const strategyEntry = [...strategyVersionIdByLegacyId.entries()].find(([, value]) => value === versionId);
  return {
    id: runId,
    strategyId: strategyEntry?.[0] ?? stableLegacyId(versionId),
    strategyName: run.strategyName ?? run.strategy_name ?? 'A股策略',
    startDate: run.startDate ?? run.start_date,
    endDate: run.endDate ?? run.end_date,
    initialCapital,
    finalCapital: Number.isFinite(strategyReturn) ? initialCapital * (1 + strategyReturn) : null,
    totalReturn: Number.isFinite(strategyReturn) ? strategyReturn * 100 : null,
    annualReturn: Number.isFinite(Number(metrics.annualizedReturn ?? metrics.annualized_return))
      ? Number(metrics.annualizedReturn ?? metrics.annualized_return) * 100
      : null,
    maxDrawdown: Number.isFinite(maximumDrawdown) ? maximumDrawdown * 100 : null,
    sharpeRatio: metrics.sharpe ?? null,
    sortinoRatio: metrics.sortino ?? null,
    beta: metrics.beta ?? null,
    alpha: Number.isFinite(Number(metrics.alpha)) ? Number(metrics.alpha) * 100 : null,
    benchmarkReturn: Number.isFinite(Number(metrics.benchmarkReturn ?? metrics.benchmark_return))
      ? Number(metrics.benchmarkReturn ?? metrics.benchmark_return) * 100
      : null,
    winRate: Number.isFinite(winRate) ? winRate * 100 : null,
    profitFactor: metrics.profitLossRatio ?? metrics.profit_loss_ratio ?? null,
    totalTrades: metrics.completedTrades ?? metrics.completed_trades ?? metrics.totalOrders ?? metrics.total_orders ?? null,
    winningTrades: metrics.profitableTrades ?? metrics.profitable_trades ?? null,
    losingTrades: metrics.losingTrades ?? metrics.losing_trades ?? null,
    totalFees: metrics.totalCost ?? metrics.total_cost ?? null,
    avgHoldingBars: metrics.averageHoldingDays ?? metrics.average_holding_days ?? null,
    annualizedVolatility: Number.isFinite(Number(metrics.annualizedVolatility ?? metrics.annualized_volatility))
      ? Number(metrics.annualizedVolatility ?? metrics.annualized_volatility) * 100
      : null,
    timeframe: run.parameters?.timeframe ?? '1d',
    timeframeMode: 'strategy',
    status: run.status === 'success' ? 'completed' : run.status,
    dataQualityStatus: Number(metrics.dataQualityWarnings ?? metrics.data_quality_warnings ?? 0) > 0 ? 'warning' : 'passed',
    dataQualityMessage: run.errorMessage ?? run.error_message ?? null,
    createdAt: run.createdAt ?? run.created_at,
    promotionStatus: run.promotionStatus ?? run.promotion_status,
    inputHash: run.inputHash ?? run.input_hash,
    runMode: run.runMode ?? run.run_mode,
  };
}

function currentBacktestJobToBitPro(job: Record<string, any>): Record<string, any> {
  const progress = Number(job.progress ?? 0);
  return {
    jobId: String(job.jobId ?? job.job_id),
    strategyId: Number(job.legacyStrategyId ?? job.legacy_strategy_id ?? 0),
    status: job.status === 'success' ? 'completed' : job.status,
    currentBar: Number(job.currentBar ?? job.current_bar ?? 0),
    totalBars: Number(job.totalBars ?? job.total_bars ?? 0),
    percent: Number.isFinite(progress) ? progress : null,
    request: job.request ?? job.requestPayload ?? job.request_payload ?? null,
    message: job.message ?? job.phase ?? null,
    result: job.result ?? null,
    errorMessage: job.errorMessage ?? job.error_message ?? null,
    updatedAt: job.updatedAt ?? job.updated_at ?? null,
    resumable: job.status === 'interrupted' || job.status === 'failed',
  };
}

async function createCurrentBacktestJob(data: Record<string, unknown>): Promise<Record<string, any>> {
  const configuration = await backtestCurrentApi.configuration();
  const strategyVersionId = strategyVersionIdForLegacyId(data.strategy_id ?? data.strategyId);
  const payload = {
    mode: String(data.mode || 'quick'),
    name: String(data.name || 'A股回测实例'),
    strategy_version_id: strategyVersionId,
    dataset_snapshot_id: data.dataset_snapshot_id ?? configuration.dataset_snapshots[0]?.id,
    universe_snapshot_id: data.universe_snapshot_id ?? configuration.universe_snapshots[0]?.id,
    factor_snapshot_id: data.factor_snapshot_id ?? null,
    pool_snapshot_id: data.pool_snapshot_id ?? null,
    cost_model_id: data.cost_model_id ?? configuration.cost_models[0]?.id,
    research_protocol_id: data.research_protocol_id ?? configuration.protocols[0]?.id ?? null,
    start_date: data.start_date ?? data.startDate,
    end_date: data.end_date ?? data.endDate,
    initial_cash: data.initial_cash ?? data.initialCapital ?? 1_000_000,
    parameters: data.parameters ?? {
      timeframe: data.timeframe ?? '1d',
      lot_size: 100,
      long_only: true,
    },
    symbols: data.symbols ?? [],
  };
  return backtestCurrentApi.createJob(payload);
}

export const backtestApi = {
  runSync: (data: Record<string, unknown>): Promise<any> =>
    postReq('/backtest/run_sync', data, { timeout: BACKTEST_RUN_SYNC_TIMEOUT_MS }),

  /** 异步回测：立即返回 jobId，进度见 getJob（SQLite 持久化，刷新页面或服务重启后可继续轮询） */
  runJob: async (data: Record<string, unknown>): Promise<{ jobId: string }> => {
    const job = await createCurrentBacktestJob(data);
    return { jobId: String(job.jobId ?? job.job_id) };
  },

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
  }> => {
    const end = new Date();
    const start = new Date(end);
    start.setFullYear(end.getFullYear() - 1);
    const toDate = (value: Date) => value.toISOString().slice(0, 10);
    const defaults = {
      startDate: toDate(start),
      endDate: toDate(end),
      initialCapital: 1_000_000,
      timeframeMode: 'strategy',
    };
    return paperCurrentApi.list('audit').then(async (paper) => {
      const running = paper.items.filter((item) => item.lifecycle_status === 'running');
      const attempts = await Promise.all(running.map(async (item) => {
        const detail = await paperCurrentApi.detail(item.id);
        const strategyVersionId = String(detail.strategy_version?.id ?? detail.strategy_version_id ?? '');
        if (!strategyVersionId) throw new Error('Paper 实例缺少策略版本');
        const job = await createCurrentBacktestJob({
          ...(data || {}),
          strategy_id: strategyVersionId,
          name: `${item.name} / 批量回测`,
          start_date: defaults.startDate,
          end_date: defaults.endDate,
          initial_capital: defaults.initialCapital,
          timeframe_mode: defaults.timeframeMode,
        });
        return {
          jobId: String(job.jobId ?? job.job_id),
          strategyId: stableLegacyId(strategyVersionId),
          strategyName: detail.strategy_version?.name ?? item.name,
          status: String(job.status ?? 'pending'),
          request: job.request ?? null,
        };
      }));
      return {
        count: attempts.length,
        skippedCount: paper.items.length - running.length,
        defaults,
        jobs: attempts,
        skipped: paper.items
          .filter((item) => item.lifecycle_status !== 'running')
          .map((item) => ({ strategyName: item.name, status: item.lifecycle_status, reason: '仅运行中的 Paper 实例参与批量回测' })),
      };
    });
  },

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
  }> => apiClient.get(`/backtest/jobs/${encodeURIComponent(jobId)}`).then((item) => currentBacktestJobToBitPro(item) as any),

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
  }> => backtestCurrentApi.cancelJob(jobId).then((item) => currentBacktestJobToBitPro(item) as any),

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
  }> => backtestCurrentApi.retryJob(jobId).then((item) => currentBacktestJobToBitPro(item) as any),

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
  }>> => {
    void params?.strategyId;
    void params?.status;
    void params?.includeResult;
    return backtestCurrentApi.jobs(params?.limit ?? 50).then((response) =>
      response.items.map((item) => currentBacktestJobToBitPro(item) as any),
    );
  },

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
  ): Promise<any[]> => {
    void params?.strategyId;
    void params?.sortBy;
    void params?.sortDir;
    void params?.includeMatrixSummary;
    const offset = Math.max(0, params?.offset ?? 0);
    const limit = Math.max(1, params?.limit ?? 20);
    return backtestCurrentApi.runs(Math.min(200, offset + limit)).then((response) => {
      const query = (params?.query || '').trim().toLowerCase();
      return response.items
        .map((item) => currentBacktestRunToBitPro(item))
        .filter((item) => !query || `${item.strategyName} ${item.id}`.toLowerCase().includes(query))
        .slice(offset, offset + limit);
    });
  },

  getResult: async (id: number): Promise<any> => {
    const runId = backtestRunIdForLegacyId(id);
    const run = await backtestCurrentApi.run(runId);
    return currentBacktestRunToBitPro(run);
  },

  getResultEvidence: async (id: number): Promise<any> => {
    const runId = backtestRunIdForLegacyId(id);
    const series = await backtestCurrentApi.series(runId);
    const trades = await backtestCurrentApi.detailRows(runId, 'trades');
    const orders = await backtestCurrentApi.detailRows(runId, 'orders');
    const positions = await backtestCurrentApi.detailRows(runId, 'positions');
    const logs = await backtestCurrentApi.detailRows(runId, 'logs');
    return {
      trades: trades.items,
      orders: orders.items,
      positions: positions.items,
      logs: logs.items,
      equityCurve: series.equityCurve ?? series.equity_curve ?? series,
    };
  },

  deleteResult: (id: number): Promise<{ deleted: boolean; id: number }> =>
    Promise.reject(new Error(`回测证据不可删除：${id}`)),

  getStrategies: (): Promise<Record<string, unknown>> =>
    getReq('/backtest/strategies'),
};

export default api;
