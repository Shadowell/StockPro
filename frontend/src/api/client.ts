import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { AgentIteration, AgentResearchConfig, AgentTaskCreateRequest, AgentTaskDetail, AgentTaskSummary, LiveAuditEvent, LiveDeploymentRequest, LiveDeploymentResult, LivePreflightRequest, LivePreflightResult, LivePromotionCandidate, LiveTradingStatus, DailyChartData, IntradayChartData, TaskStatus, HotConceptItem, SectorFundFlowResponse, LimitBoardResponse, ThsHotItem, LianbanLadderResponse, RunSentimentResponse, SentimentItem, AIStockAnalyzeResponse, ConceptIntradayKlineItem, ConceptLeaderStock, StockCandidate, StockFundamentals, OrderBookSnapshot, MessageStreamResponse, MarketCalendarEvent, TradingCalendarResponse, CalendarRefreshResponse, MarketOverview, Strategy, StrategyResult, StrategyExecutionResult, SaveStrategyRequest, StartStrategyRequest, StrategyBacktestRequest, StrategyBacktestResult, PaperRunRequest, PaperRunResult, PaperAccount, AutoDevelopStrategyRequest, AutoDevelopStrategyResult, StrategySaveResponse, StrategyVersion, StrategyReplayResult, BacktestConfiguration, BacktestRun, BacktestRunRequestV1, BacktestMetric, BacktestDailyPoint, BacktestJob, BacktestJobLog, WalkForwardPreview, MarketResearchContext, StockPool, StockPoolGeneration, StockPoolMember, StockPoolSnapshot, PaperRuntimeInstance, PaperKlineSnapshot, WatchContext, RuntimeAlert, WatchRule, WatchRulePreview, WatchRuleType, MonitorHealth, DailyReviewContext, AICapabilities, WorkflowCapabilities, ResearchDesk } from '../types';

const API_URL = import.meta.env.VITE_API_URL || '/api';
const ADMIN_TOKEN_STORAGE_KEY = 'stockpro_admin_token';
const AUTH_PROFILE_STORAGE_KEY = 'stockpro_auth_profile';
export const ADMIN_AUTH_CHANGED_EVENT = 'stockpro_admin_auth_changed';

// Retry configuration
const retryConfig = {
  maxRetries: 3,
  baseDelay: 1000,
  retryableStatus: [408, 429, 500, 502, 503, 504],
};

export interface GenericApiResponse {
  status?: string;
  success?: boolean;
  message?: string;
  [key: string]: unknown;
}

export interface AdminLoginResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  username: string;
  role: 'admin';
  permissions: string[];
}

export interface AuthProfile {
  role: 'admin' | 'guest';
  username?: string;
  permissions: string[];
  session_id?: string;
  guest_code_id?: number;
  expires_at?: string;
  max_backtests_per_day?: number;
  max_concurrent_backtests?: number;
  max_backtest_days?: number;
}

export interface GuestLoginResponse extends AuthProfile {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
}

export interface GuestAccessCode {
  id: number;
  code?: string;
  note: string;
  expires_at: string;
  max_backtests_per_day: number;
  max_concurrent_backtests: number;
  max_backtest_days: number;
  created_at: string;
  last_used_at?: string | null;
  revoked_at?: string | null;
}

export interface McpAgentToken {
  id: number;
  name: string;
  token?: string;
  token_hint: string;
  scopes: Array<'R' | 'W'>;
  created_by: string;
  created_at: string;
  last_used_at?: string | null;
  revoked_at?: string | null;
}

export const getAdminToken = (): string | null => {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY);
};

export const setAdminToken = (token: string): void => {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, token);
  window.dispatchEvent(new Event(ADMIN_AUTH_CHANGED_EVENT));
};

export const setAuthProfile = (profile: AuthProfile): void => {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(AUTH_PROFILE_STORAGE_KEY, JSON.stringify(profile));
  window.dispatchEvent(new Event(ADMIN_AUTH_CHANGED_EVENT));
};

export const getStoredAuthProfile = (): AuthProfile | null => {
  if (typeof window === 'undefined') return null;
  try {
    const value = window.localStorage.getItem(AUTH_PROFILE_STORAGE_KEY);
    return value ? JSON.parse(value) as AuthProfile : null;
  } catch {
    return null;
  }
};

export const clearAdminToken = (): void => {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
  window.localStorage.removeItem(AUTH_PROFILE_STORAGE_KEY);
  window.dispatchEvent(new Event(ADMIN_AUTH_CHANGED_EVENT));
};

export const hasAdminToken = (): boolean => Boolean(getAdminToken());

export const getWorkflowCapabilities = async (): Promise<WorkflowCapabilities> => {
  const response = await apiClient.get<WorkflowCapabilities>('/workflow/capabilities');
  return response.data;
};

export const getResearchDesk = async (): Promise<ResearchDesk> => {
  const response = await apiClient.get<ResearchDesk>('/workflow/research-desk');
  return response.data;
};

export interface PresetTaskParam {
  name: string;
  type: string;
  description: string;
}

export interface PresetTaskItem {
  id: string;
  name: string;
  description: string;
  params?: PresetTaskParam[];
}

export interface PresetTaskExecuteRequest {
  task_type: string;
  params?: Record<string, unknown>;
}

export interface PresetTaskStatus extends GenericApiResponse {
  is_running: boolean;
  task_type?: string;
  progress?: number;
  current?: number;
  total?: number;
}

export interface ImportHistoricalRequest {
  date: string;
  task_type: string;
}

export interface ImportStatus extends GenericApiResponse {
  task_id?: string | null;
  is_running: boolean;
  current?: number;
  total?: number;
  processed?: number;
  progress?: number;
  current_step?: string;
}

export interface ImportTaskResponse {
  success?: boolean;
  message?: string;
  status?: ImportStatus;
  [key: string]: unknown;
}

export interface MADataStats {
  stock_count: number;
  record_count: number;
  start_date: string | null;
  end_date: string | null;
}

export interface MADataStatsResponse extends GenericApiResponse {
  success: boolean;
  stats: MADataStats;
}

export interface DataDevTask {
  id: number;
  name: string;
  description?: string;
  sql_content?: string;
  cron_expression?: string;
  enabled?: boolean;
  created_at?: string;
  updated_at?: string;
  last_status?: string;
  last_run?: string;
  last_error?: string;
  [key: string]: unknown;
}

export interface DataDevTaskPayload {
  name: string;
  description: string;
  sql_content: string;
  cron_expression: string;
  enabled: boolean;
}

export interface DataDevTaskLog {
  id: number;
  execution_start: string;
  execution_end?: string | null;
  status: string;
  error_message?: string | null;
  affected_rows?: number;
}

export interface DatabaseTableInfo {
  name: string;
  columns: string[];
  rowCount: number;
}

export interface DatabaseQueryResult {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  rowCount: number;
  totalCount?: number;
}

export interface DataHubDataset {
  id: string;
  name: string;
  table: string;
  exists: boolean;
  row_count: number;
  fields: string[];
  primary_keys: string[];
  refresh_frequency: string;
  dependencies: string[];
  latest_snapshot: string | null;
  freshness_status: 'green' | 'yellow' | 'red';
}

export interface DataHubDatasetFreshness {
  dataset: DataHubDataset;
  recent_jobs: DataHubJob[];
}

export interface DataHubJob {
  job_key: string;
  action: string;
  scope?: string | null;
  params?: Record<string, unknown>;
  status: 'queued' | 'running' | 'success' | 'failed' | 'cancelled' | string;
  progress: number;
  current: number;
  total: number;
  message?: string | null;
  error_message?: string | null;
  result?: Record<string, unknown> | null;
  logs?: DataHubJobLog[];
  parent_job_key?: string | null;
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface DataHubJobLog {
  timestamp: string;
  level: string;
  message: string;
  payload?: Record<string, unknown>;
}

export interface DataHubQualityCheck {
  dataset_id: string;
  status: 'green' | 'yellow' | 'red';
  title: string;
  detail: string;
  metrics: Record<string, unknown>;
}

export interface DataHubQualityReport {
  report_key: string;
  scope: string[];
  status: 'green' | 'yellow' | 'red';
  summary: {
    total_checks: number;
    green: number;
    yellow: number;
    red: number;
    status: 'green' | 'yellow' | 'red';
  };
  checks: DataHubQualityCheck[];
  created_at: string;
  rule_templates?: Array<{
    id: string;
    name: string;
    severity: string;
  }>;
}

export interface DataHubScreenerSnapshot {
  dataset_id: string;
  as_of: string | null;
  version: string;
}

export interface ScreenerFeatureStock {
  symbol: string;
  name: string;
  price: number;
  date: string;
  ma5: number;
  ma10: number;
  ma20: number;
  ma30: number;
  ma_range: number;
  ma_range_pct: number;
  avg_range_pct: number;
  avg_std_pct: number;
  convergence_days: number;
}

export interface ScreenerFeatureParams {
  days?: number;
  max_range_pct?: number;
  main_board_only?: boolean;
  min_price?: number;
  max_price?: number;
  limit?: number;
}

export interface DataHubScreenerResponse {
  status: string;
  snapshot: DataHubScreenerSnapshot;
  data: ScreenerFeatureStock[];
  count: number;
  total_found: number;
  params: ScreenerFeatureParams;
}

export interface DataHubFactorFeaturesResponse {
  status: string;
  snapshot: {
    dataset_id: string;
    as_of: string | null;
    version: string;
  };
  factor_definitions: Array<Record<string, unknown>>;
  stats: {
    factor_count: number;
    data_count: number;
    latest_date: string | null;
    stock_count: number;
    category_stats: Record<string, number>;
  };
  selected_factor?: Record<string, unknown> | null;
  ranking: Array<Record<string, unknown>>;
}

export interface ResearchFactor {
  id: number;
  factor_code: string;
  factor_name: string;
  category: string;
  description?: string | null;
  direction: number;
  research_status: string;
  enabled: boolean;
  active_version_id: number;
  version_no: number;
  content_hash: string;
  validation_status: string;
  last_trade_date?: string | null;
  publication_state?: string | null;
  dataset_snapshot_id?: number | null;
  universe_snapshot_id?: number | null;
  knowledge_cutoff_at?: string | null;
  coverage?: number | null;
  rank_ic?: number | null;
  icir?: number | null;
  long_short_return?: number | null;
  turnover?: number | null;
  decay?: number | null;
}

export interface FactorComputeRun {
  id: number;
  factor_version_id: number;
  factor_code: string;
  factor_name: string;
  version_no: number;
  trade_date: string;
  dataset_snapshot_id: number;
  universe_snapshot_id: number;
  knowledge_cutoff_at: string;
  status: string;
  input_count: number;
  output_count: number;
  missing_count: number;
  error_message?: string | null;
  value_hash?: string | null;
}

export interface FactorMetricRow {
  compute_run_id: number;
  trade_date: string;
  dataset_snapshot_id: number;
  universe_snapshot_id: number;
  knowledge_cutoff_at: string;
  factor_version_id: number;
  version_no: number;
  metric_code: string;
  horizon?: number | null;
  metric_value?: number | null;
  metric_payload?: Record<string, unknown>;
  pending_reason?: string | null;
}

export interface FactorValueRow {
  trade_date: string;
  symbol: string;
  name?: string | null;
  raw_value?: number | null;
  processed_value?: number | null;
  rank?: number | null;
  percentile?: number | null;
  quantile?: number | null;
  quality_flags: Record<string, unknown>;
  compute_run_id: number;
  factor_version_id: number;
  dataset_snapshot_id: number;
  universe_snapshot_id: number;
  knowledge_cutoff_at: string;
}

export interface FactorCorrelationRow {
  trade_date: string;
  factor_version_id_a: number;
  factor_code_a: string;
  factor_version_id_b: number;
  factor_code_b: string;
  correlation?: number | null;
  universe_snapshot_id: number;
}

declare module 'axios' {
  interface AxiosRequestConfig {
    skipRetry?: boolean;
  }
}

// Extend axios config type to include retry count
interface RetryableRequestConfig extends InternalAxiosRequestConfig {
  __retryCount?: number;
  skipRetry?: boolean;
}

export const PAGE_READ_TIMEOUT_MS = 8_000;
// The first Data Center read may establish the SSH-tunnel-backed PostgreSQL
// connection. Keep ordinary page reads fast, but do not turn a cold data
// connection into a false "no data" state.
const pageRead = { timeout: PAGE_READ_TIMEOUT_MS, skipRetry: true as const };

export const apiClient = axios.create({
  baseURL: API_URL,
  timeout: 60000, // 60 seconds timeout
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use((config) => {
  const token = getAdminToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  const profile = getStoredAuthProfile();
  const method = (config.method || 'get').toLowerCase();
  const path = config.url || '';
  const guestBacktestPaths = ['/backtest/quick-runs', '/backtest/runs', '/backtest/run'];
  const guestJobPath = /^\/backtest\/jobs(?:\/[0-9a-f-]+\/(?:cancel|retry))?$/;
  if (
    profile?.role === 'guest'
    && !['get', 'head', 'options'].includes(method)
    && !guestBacktestPaths.includes(path)
    && !guestJobPath.test(path)
    && path !== '/auth/guest/login'
  ) {
    return Promise.reject(new Error('访客账号为只读权限，仅允许在配额内运行回测。'));
  }
  return config;
});

// Response interceptor for automatic retry with exponential backoff
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    // Only drop the session on explicit auth rejection. Network blips / 5xx during
    // local uvicorn --reload must not force a login loop.
    if (error.response?.status === 401) {
      const url = String(error.config?.url || '');
      if (!url.includes('/auth/admin/login') && !url.includes('/auth/guest/login')) {
        clearAdminToken();
      }
    }

    const config = error.config as RetryableRequestConfig | undefined;
    if (!config || config.skipRetry) {
      return Promise.reject(error);
    }

    config.__retryCount = config.__retryCount || 0;

    // Determine if error is retryable
    const isNetworkError = !error.response;
    const isRetryableStatus = error.response && retryConfig.retryableStatus.includes(error.response.status);
    const isRetryable = isNetworkError || isRetryableStatus;

    // Don't retry 4xx errors (except those in retryableStatus)
    if (!isRetryable || config.__retryCount >= retryConfig.maxRetries) {
      return Promise.reject(error);
    }

    config.__retryCount++;

    // Exponential backoff with jitter
    const delay = retryConfig.baseDelay * Math.pow(2, config.__retryCount - 1) + Math.random() * 100;
    
    console.log(`[API] Retry ${config.__retryCount}/${retryConfig.maxRetries} for ${config.url} after ${Math.round(delay)}ms`);

    await new Promise((resolve) => setTimeout(resolve, delay));
    return apiClient(config);
  }
);

export const adminLogin = async (username: string, password: string): Promise<AdminLoginResponse> => {
  const response = await apiClient.post<AdminLoginResponse>('/auth/admin/login', { username, password });
  setAdminToken(response.data.access_token);
  setAuthProfile({ role: 'admin', username: response.data.username, permissions: response.data.permissions });
  return response.data;
};

export const guestLogin = async (code: string): Promise<GuestLoginResponse> => {
  const response = await apiClient.post<GuestLoginResponse>('/auth/guest/login', { code });
  setAdminToken(response.data.access_token);
  setAuthProfile({
    role: response.data.role,
    permissions: response.data.permissions,
    session_id: response.data.session_id,
    guest_code_id: response.data.guest_code_id,
    expires_at: response.data.expires_at,
    max_backtests_per_day: response.data.max_backtests_per_day,
    max_concurrent_backtests: response.data.max_concurrent_backtests,
    max_backtest_days: response.data.max_backtest_days,
  });
  return response.data;
};

export const getAuthProfile = async (): Promise<AuthProfile> => {
  const response = await apiClient.get<AuthProfile>('/auth/me');
  setAuthProfile(response.data);
  return response.data;
};

export const getAdminProfile = getAuthProfile;

export const listGuestAccessCodes = async (): Promise<GuestAccessCode[]> =>
  (await apiClient.get<{ items: GuestAccessCode[] }>('/auth/guest-codes')).data.items;

export const createGuestAccessCode = async (request: {
  note: string;
  expires_in_minutes: number;
  max_backtests_per_day: number;
  max_concurrent_backtests: number;
  max_backtest_days: number;
}): Promise<GuestAccessCode> =>
  (await apiClient.post<GuestAccessCode>('/auth/guest-codes', request)).data;

export const revokeGuestAccessCode = async (codeId: number): Promise<void> => {
  await apiClient.delete(`/auth/guest-codes/${codeId}`);
};

export const listMcpAgentTokens = async (): Promise<McpAgentToken[]> =>
  (await apiClient.get<{ items: McpAgentToken[] }>('/auth/mcp-agent-tokens')).data.items;

export const createMcpAgentToken = async (request: {
  name: string;
  scopes: Array<'R' | 'W'>;
}): Promise<McpAgentToken> =>
  (await apiClient.post<McpAgentToken>('/auth/mcp-agent-tokens', request)).data;

export const revokeMcpAgentToken = async (tokenId: number): Promise<void> => {
  await apiClient.delete(`/auth/mcp-agent-tokens/${tokenId}`);
};

export const getMarketOverview = async (): Promise<MarketOverview> => {
  try {
    const response = await apiClient.get<MarketOverview>('/market/overview', pageRead);
    return response.data;
  } catch (error) {
    return rejectPageTimeout('市场概览', error);
  }
};

// 短线指标类型（涨停、连板、多板、涨跌比等短线强度指标）
interface ShortLineIndex {
  code: string;
  name: string;
  price: number;
  change_percent: number;
  change_amount: number;
}

export const getShortLineIndices = async (): Promise<ShortLineIndex[]> => {
  const response = await apiClient.get<ShortLineIndex[]>('/market/short-line-indices');
  return response.data;
};

export const getDailyChart = async (symbol: string): Promise<DailyChartData[]> => {
  const response = await apiClient.get<DailyChartData[]>(`/charts/daily/${symbol}`);
  return Array.isArray(response.data) ? response.data : [];
};

export const getIntradayChart = async (symbol: string): Promise<IntradayChartData[]> => {
  const response = await apiClient.get<{ data?: IntradayChartData[] } | IntradayChartData[]>(`/charts/intraday/${symbol}`);
  const payload = response.data;
  if (Array.isArray(payload)) return payload;
  return Array.isArray(payload?.data) ? payload.data : [];
};

export const getStockFundamentals = async (symbol: string): Promise<StockFundamentals> => {
  const response = await apiClient.get<StockFundamentals>(`/market/fundamentals/${symbol}`);
  return response.data;
};

export const getOrderBook = async (symbol: string): Promise<OrderBookSnapshot> => {
  const response = await apiClient.get<OrderBookSnapshot>(`/market/order-book/${encodeURIComponent(symbol)}`);
  return response.data;
};

export const getTaskStatus = async (): Promise<TaskStatus> => {
  const response = await apiClient.get<TaskStatus>('/admin/task-status');
  return response.data;
};

export const triggerHistoryFetch = async (): Promise<{ message: string }> => {
  const response = await apiClient.post<{ message: string }>('/admin/fetch-history', {});
  return response.data;
};

export const searchStocks = async (params: { q?: string; limit?: number } = {}): Promise<StockCandidate[]> => {
  const response = await apiClient.get<StockCandidate[]>('/stocks/search', {
    params: { q: params.q ?? '', limit: params.limit ?? 80 },
  });
  return response.data;
};

export const getHotConcepts = async (limit = 50, date?: string): Promise<HotConceptItem[]> => {
  const response = await apiClient.get<HotConceptItem[]>('/market/hot-concepts', { params: { limit, date } });
  return response.data;
};

export const getSectorFundFlow = async (limit = 30): Promise<SectorFundFlowResponse> => {
  const response = await apiClient.get<SectorFundFlowResponse>('/market/sector-fund-flow', { params: { limit } });
  return response.data;
};

export const getLimitBoard = async (tradeDate?: string): Promise<LimitBoardResponse> => {
  const response = await apiClient.get<LimitBoardResponse>('/market/limit-board', {
    params: tradeDate ? { trade_date: tradeDate } : undefined,
  });
  return response.data;
};

export const getThsHot = async (limit = 100, date?: string): Promise<ThsHotItem[]> => {
  const response = await apiClient.get<ThsHotItem[]>('/market/ths-hot', { params: { limit, date } });
  return response.data;
};

export const getLianbanLadder = async (date?: string): Promise<LianbanLadderResponse> => {
  const response = await apiClient.get<LianbanLadderResponse>('/market/lianban-ladder', { params: { date } });
  return response.data;
};

export const getHotConceptIntradayKline = async (params: { name: string; period?: string; date?: string }): Promise<ConceptIntradayKlineItem[]> => {
  const response = await apiClient.get<ConceptIntradayKlineItem[]>('/market/hot-concept/intraday', { params });
  return response.data;
};

export const getHotConceptLeaders = async (params: { name: string; limit?: number; date?: string }): Promise<ConceptLeaderStock[]> => {
  const response = await apiClient.get<ConceptLeaderStock[]>('/market/hot-concept/leaders', { params });
  return response.data;
};

export const syncHotConceptLeaders = async (params?: { name?: string; limit?: number }): Promise<{
  synced: string[];
  synced_count: number;
  empty: string[];
  failed: Record<string, string>;
  total_concepts: number;
}> => {
  const response = await apiClient.post('/market/hot-concept/leaders/sync', null, { params });
  return response.data;
};

export const runSentiment = async (params?: { date?: string; universe?: 'all' | 'hot' }): Promise<RunSentimentResponse> => {
  const response = await apiClient.post<RunSentimentResponse>('/analysis/run-sentiment', null, { params });
  return response.data;
};

export const getSentiment = async (params?: { date?: string; limit?: number; order?: 'asc' | 'desc' }): Promise<SentimentItem[]> => {
  const response = await apiClient.get<SentimentItem[]>('/analysis/sentiment', { params });
  return response.data;
};

export const analyzeStockByAI = async (params: { symbol: string; date?: string }): Promise<AIStockAnalyzeResponse> => {
  const response = await apiClient.post<AIStockAnalyzeResponse>('/ai/analyze-stock', params);
  return response.data;
};

export const getMessageStream = async (limit = 50): Promise<MessageStreamResponse> => {
  const response = await apiClient.get<MessageStreamResponse>('/market/message-stream', { params: { limit } });
  return response.data;
};

export const syncNewsStream = async (): Promise<{status: string; count: number}> => {
  const response = await apiClient.post('/market/message-stream/sync');
  return response.data;
};

export const getMarketCalendar = async (params?: { start?: string; end?: string; limit?: number }): Promise<MarketCalendarEvent[]> => {
  const response = await apiClient.get<MarketCalendarEvent[]>('/market/calendar', { params });
  return response.data;
};

export const getTradingCalendar = async (params?: { start?: string; end?: string }): Promise<TradingCalendarResponse> => {
  const response = await apiClient.get<TradingCalendarResponse>('/market/trading-calendar', { params });
  return response.data;
};

export const refreshMarketCalendar = async (months = 6): Promise<CalendarRefreshResponse> => {
  const response = await apiClient.post<CalendarRefreshResponse>('/market/calendar/refresh', null, { params: { months } });
  return response.data;
};

export const refreshMarketCalendarWithFreeData = async (months = 6): Promise<CalendarRefreshResponse> => {
  const response = await apiClient.post<CalendarRefreshResponse>('/market/calendar/refresh-free', null, { params: { months } });
  return response.data;
};

export const generateMarketCalendarWithAI = async (params: { start_date: string; end_date: string }): Promise<GenericApiResponse> => {
  const response = await apiClient.post<GenericApiResponse>('/market/calendar/generate-with-ai', null, { params });
  return response.data;
};

// Preset Tasks API
export const getPresetTasks = async (): Promise<PresetTaskItem[]> => {
  const response = await apiClient.get<PresetTaskItem[]>('/preset-tasks');
  return response.data;
};

export const executePresetTask = async (request: PresetTaskExecuteRequest): Promise<GenericApiResponse> => {
  const response = await apiClient.post<GenericApiResponse>('/preset-tasks/execute', request);
  return response.data;
};

export const getPresetTaskStatus = async (): Promise<PresetTaskStatus> => {
  const response = await apiClient.get<PresetTaskStatus>('/preset-tasks/status');
  return response.data;
};

export const cancelPresetTask = async (): Promise<GenericApiResponse> => {
  const response = await apiClient.post<GenericApiResponse>('/preset-tasks/cancel');
  return response.data;
};

// Batch Import API
export const importHistoricalData = async (request: ImportHistoricalRequest): Promise<ImportTaskResponse> => {
  const response = await apiClient.post<ImportTaskResponse>('/batch-import/historical-data', request);
  return response.data;
};

export const getImportStatus = async (): Promise<ImportStatus> => {
  const response = await apiClient.get<ImportStatus>('/batch-import/status');
  return response.data;
};

export const cancelImportTask = async (): Promise<GenericApiResponse> => {
  const response = await apiClient.post<GenericApiResponse>('/batch-import/cancel');
  return response.data;
};

// MA Data Import API
export const importMAData = async (mainBoardOnly: boolean = true): Promise<ImportTaskResponse> => {
  const response = await apiClient.post<ImportTaskResponse>('/batch-import/ma-data', { main_board_only: mainBoardOnly });
  return response.data;
};

export const getMADataStats = async (): Promise<MADataStatsResponse> => {
  const response = await apiClient.get<MADataStatsResponse>('/batch-import/ma-data/stats');
  return response.data;
};

// Data Development API
export const getDataDevTasks = async (): Promise<DataDevTask[]> => {
  const response = await apiClient.get<DataDevTask[]>('/data-dev/tasks');
  return response.data;
};

export const createDataDevTask = async (task: DataDevTaskPayload): Promise<GenericApiResponse> => {
  const response = await apiClient.post<GenericApiResponse>('/data-dev/tasks', task);
  return response.data;
};

export const updateDataDevTask = async (taskId: number, task: DataDevTaskPayload): Promise<GenericApiResponse> => {
  const response = await apiClient.put<GenericApiResponse>(`/data-dev/tasks/${taskId}`, task);
  return response.data;
};

export const deleteDataDevTask = async (taskId: number): Promise<GenericApiResponse> => {
  const response = await apiClient.delete<GenericApiResponse>(`/data-dev/tasks/${taskId}`);
  return response.data;
};

export const runDataDevTask = async (taskId: number): Promise<GenericApiResponse> => {
  const response = await apiClient.post<GenericApiResponse>(`/data-dev/tasks/${taskId}/run`);
  return response.data;
};

export const getTaskLogs = async (taskId: number, limit = 50): Promise<DataDevTaskLog[]> => {
  const response = await apiClient.get<DataDevTaskLog[]>(`/data-dev/tasks/${taskId}/logs?limit=${limit}`);
  return response.data;
};

// Data Hub API
export const getDataHubDatasets = async (): Promise<DataHubDataset[]> => {
  const response = await apiClient.get<{ status: string; data: DataHubDataset[] }>('/data-hub/datasets');
  return response.data.data || [];
};

export const getDataHubDatasetFreshness = async (datasetId: string): Promise<DataHubDatasetFreshness> => {
  const response = await apiClient.get<{ status: string; data: DataHubDatasetFreshness }>(
    `/data-hub/datasets/${datasetId}/freshness`
  );
  return response.data.data;
};

export const createDataHubJob = async (payload: {
  action: string;
  scope?: string;
  params?: Record<string, unknown>;
}): Promise<DataHubJob> => {
  const response = await apiClient.post<{ status: string; data: DataHubJob }>('/data-hub/jobs', payload);
  return response.data.data;
};

export const getDataHubJobs = async (params?: {
  action?: string;
  status?: string;
  scope?: string;
  parent_job_key?: string;
  limit?: number;
}): Promise<DataHubJob[]> => {
  const response = await apiClient.get<{ status: string; data: DataHubJob[] }>('/data-hub/jobs', { params });
  return response.data.data || [];
};

export const getDataHubJob = async (jobKey: string): Promise<DataHubJob> => {
  const response = await apiClient.get<{ status: string; data: DataHubJob }>(`/data-hub/jobs/${jobKey}`);
  return response.data.data;
};

export const getDataHubJobLogs = async (jobKey: string, limit = 200): Promise<DataHubJobLog[]> => {
  const response = await apiClient.get<{ status: string; data: DataHubJobLog[] }>(`/data-hub/jobs/${jobKey}/logs`, {
    params: { limit },
  });
  return response.data.data || [];
};

export const rerunDataHubJob = async (jobKey: string): Promise<DataHubJob> => {
  const response = await apiClient.post<{ status: string; data: DataHubJob }>(`/data-hub/jobs/${jobKey}/rerun`);
  return response.data.data;
};

export const cancelDataHubJob = async (jobKey: string): Promise<DataHubJob> => {
  const response = await apiClient.post<{ status: string; data: DataHubJob }>(`/data-hub/jobs/${jobKey}/cancel`);
  return response.data.data;
};

export const runDataHubQuality = async (datasets?: string[]): Promise<DataHubQualityReport> => {
  const response = await apiClient.post<{ status: string; data: DataHubQualityReport }>(
    '/data-hub/quality/run',
    { datasets }
  );
  return response.data.data;
};

export const getDataHubQualityReport = async (): Promise<DataHubQualityReport | null> => {
  const response = await apiClient.get<{ status: string; data: DataHubQualityReport | null }>(
    '/data-hub/quality/report'
  );
  return response.data.data;
};

export const getDataHubScreenerFeatures = async (
  params?: ScreenerFeatureParams
): Promise<DataHubScreenerResponse> => {
  const response = await apiClient.get<DataHubScreenerResponse>('/data-hub/features/screener', { params });
  return response.data;
};

export const getDataHubFactorFeatures = async (params?: {
  factor_code?: string;
  date?: string;
  limit?: number;
  ascending?: boolean;
  category?: string;
}): Promise<DataHubFactorFeaturesResponse> => {
  const response = await apiClient.get<DataHubFactorFeaturesResponse>('/data-hub/features/factors', { params });
  return response.data;
};

// Database Management API
export const getDatabaseTables = async (): Promise<DatabaseTableInfo[]> => {
  const response = await apiClient.get<DatabaseTableInfo[]>('/database/tables');
  return response.data;
};

export const executeSqlQuery = async (query: string): Promise<DatabaseQueryResult> => {
  const response = await apiClient.post<DatabaseQueryResult>('/database/query', { query });
  return response.data;
};

export const getTableData = async (tableName: string, limit: number = 100): Promise<DatabaseQueryResult> => {
  const response = await apiClient.get<DatabaseQueryResult>(`/database/table/${tableName}?limit=${limit}`);
  return response.data;
};

// ============ Strategy API ============

// The strategy catalogue reads PostgreSQL through the same SSH tunnel as the
// Data Center. A cold checkout includes connection validation, the SELECT and
// transaction cleanup, so it needs the established cold-read envelope rather
// than the ordinary interactive-page timeout.
export const STRATEGY_LIST_READ_TIMEOUT_MS = 20_000;

export const getStrategies = async (scope: 'business' | 'audit' = 'business'): Promise<Strategy[]> => {
  try {
    const response = await apiClient.get<Strategy[]>('/strategy/list', {
      params: { scope },
      timeout: STRATEGY_LIST_READ_TIMEOUT_MS,
      skipRetry: true,
    });
    return response.data;
  } catch (error) {
    return rejectPageTimeout('策略目录', error);
  }
};

export const getAICapabilities = async (): Promise<AICapabilities> => {
  const response = await apiClient.get<AICapabilities>('/ai/capabilities');
  return response.data;
};

export const getStrategy = async (strategyId: number): Promise<Strategy> => {
  const response = await apiClient.get<Strategy>(`/strategy/${strategyId}`);
  return response.data;
};

export const saveStrategy = async (data: SaveStrategyRequest): Promise<StrategySaveResponse> => {
  const response = await apiClient.post<StrategySaveResponse>('/strategy/save', data);
  return response.data;
};

export const updateStrategy = async (strategyId: number, data: SaveStrategyRequest): Promise<StrategySaveResponse> => {
  const response = await apiClient.put<StrategySaveResponse>(`/strategy/${strategyId}`, data);
  return response.data;
};

export const getLatestStrategyVersion = async (strategyId: number): Promise<StrategyVersion | null> => {
  const response = await apiClient.get<StrategyVersion | null>(`/strategy/${strategyId}/versions/latest`);
  return response.data;
};

export const quickRunStrategyVersion = async (versionId: string, request: { dataset_snapshot_id: number; factor_snapshot_id?: number; event_limit?: number }): Promise<StrategyReplayResult> => {
  const response = await apiClient.post<StrategyReplayResult>(`/strategy/versions/${versionId}/quick-run`, request);
  return response.data;
};

export const getFactorSnapshots = async (): Promise<{ items: Array<{ id: number; dataset_snapshot_id: number; universe_snapshot_id: number; status: string }> }> => {
  const response = await apiClient.get('/factor-snapshots');
  return response.data;
};

export const deleteStrategy = async (strategyId: number): Promise<{ success: boolean; message?: string; error?: string }> => {
  const response = await apiClient.delete<{ success: boolean; message?: string; error?: string }>(`/strategy/${strategyId}`);
  return response.data;
};

export const executeStrategy = async (strategyId: number): Promise<StrategyExecutionResult> => {
  const response = await apiClient.post<StrategyExecutionResult>(`/strategy/${strategyId}/execute`);
  return response.data;
};

export const startStrategy = async (strategyId: number, request?: StartStrategyRequest): Promise<{ success: boolean; message?: string; error?: string }> => {
  const response = await apiClient.post<{ success: boolean; message?: string; error?: string }>(`/strategy/${strategyId}/start`, request || {});
  return response.data;
};

export const stopStrategy = async (strategyId: number): Promise<{ success: boolean; message?: string; error?: string }> => {
  const response = await apiClient.post<{ success: boolean; message?: string; error?: string }>(`/strategy/${strategyId}/stop`);
  return response.data;
};

export const getStrategyResults = async (strategyId: number, limit = 50): Promise<StrategyResult[]> => {
  const response = await apiClient.get<StrategyResult[]>(`/strategy/${strategyId}/results`, { params: { limit } });
  return response.data;
};

export const getLatestStrategyResult = async (strategyId: number): Promise<StrategyResult | { message: string }> => {
  const response = await apiClient.get<StrategyResult | { message: string }>(`/strategy/${strategyId}/latest-result`);
  return response.data;
};

export const getRunningStrategies = async (): Promise<Strategy[]> => {
  const response = await apiClient.get<Strategy[]>('/strategy/running/list');
  return response.data;
};

export const syncTodayConceptSectors = async (): Promise<{status: string; count: number; date?: string}> => {
  const response = await apiClient.post('/market/pulse/sync-today');
  return response.data;
};

export interface PulseDailySectorItem {
  date: string;
  name: string;
  change_percent: number;
  rank?: number | null;
  inflow?: number | null;
  outflow?: number | null;
  net_inflow?: number | null;
}

export interface PulseLianbanHistoryItem {
  date: string;
  stocks?: Array<{
    code: string;
    name: string;
    level?: number;
    today_level?: number;
    change_percent?: number | null;
    price?: number | null;
    reason?: string | null;
  }>;
  [key: string]: unknown;
}

export interface ReplayNote {
  note_date: string;
  title: string;
  content: string;
  payload_json?: Record<string, unknown> | null;
  updated_at?: string | null;
}

export interface ReplayNotePayload {
  note_date: string;
  title: string;
  content: string;
  payload_json?: Record<string, unknown>;
}

export const getPulseDailyStats = async (
  params: { days?: number; min_change_pct?: number; top_n?: number } = {},
): Promise<PulseDailySectorItem[]> => {
  const response = await apiClient.get<PulseDailySectorItem[]>('/market/pulse/daily-stats', { params });
  return response.data;
};

export const getPulseLianbanHistory = async (
  params: { days?: number; min_level?: number } = {},
): Promise<PulseLianbanHistoryItem[]> => {
  const response = await apiClient.get<PulseLianbanHistoryItem[]>('/market/pulse/lianban-history', { params });
  return response.data;
};

export const listReplayNotes = async (limit = 30): Promise<ReplayNote[]> => {
  const response = await apiClient.get<{ status: string; data: ReplayNote[] }>('/market/pulse/replay-notes', { params: { limit } });
  return response.data.data || [];
};

export const saveReplayNote = async (payload: ReplayNotePayload): Promise<ReplayNote> => {
  const response = await apiClient.post<{ status: string; data: ReplayNote }>('/market/pulse/replay-notes', payload);
  return response.data.data;
};

export interface BackfillResult {
  status: string;
  days_filled?: number;
  sectors_processed?: number;
  sectors_failed?: number;
  duration_minutes?: number;
  message?: string;
}

export const backfillConceptHistory = async (days: number = 30): Promise<BackfillResult> => {
  const response = await apiClient.post('/market/pulse/backfill-history', null, {
    params: { days },
    timeout: 600000,
  });
  return response.data;
};

export const autoDevelopStrategy = async (
  request: AutoDevelopStrategyRequest
): Promise<AutoDevelopStrategyResult> => {
  const response = await apiClient.post<AutoDevelopStrategyResult>('/strategy/auto-develop', request);
  return response.data;
};

export const runStrategyBacktest = async (
  strategyId: number,
  request: StrategyBacktestRequest
): Promise<StrategyBacktestResult> => {
  const response = await apiClient.post<StrategyBacktestResult>('/backtest/run', {
    strategy_id: strategyId,
    ...request,
  });
  return response.data;
};

export const listBacktestResults = async (limit = 20): Promise<{ items: StrategyBacktestResult[]; total: number }> => {
  const response = await apiClient.get<{ items: StrategyBacktestResult[]; total: number }>('/backtest/results', { params: { limit } });
  return response.data;
};

export const BACKTEST_CONFIGURATION_READ_TIMEOUT_MS = 30_000;

export const getBacktestConfiguration = async (): Promise<BacktestConfiguration> => {
  try {
    return (await apiClient.get<BacktestConfiguration>('/backtest/configuration', {
      timeout: BACKTEST_CONFIGURATION_READ_TIMEOUT_MS,
      skipRetry: true,
    })).data;
  } catch (error) {
    return rejectPageTimeout('回测配置', error);
  }
};

export const previewWalkForward = async (request: {
  dataset_snapshot_id: number;
  start_date: string;
  end_date: string;
  train_sessions: number;
  test_sessions: number;
  step_sessions: number;
}): Promise<WalkForwardPreview> =>
  (await apiClient.post<WalkForwardPreview>('/backtest/walk-forward/preview', request, { timeout: 120_000 })).data;

export const createWalkForwardJob = async (request: BacktestRunRequestV1 & {
  train_sessions: number;
  test_sessions: number;
  step_sessions: number;
  parameter_grid: Record<string, unknown[]>;
  objective: 'sharpe' | 'sortino' | 'strategy_return' | 'maximum_drawdown';
}): Promise<BacktestJob> =>
  (await apiClient.post<BacktestJob>('/backtest/walk-forward/jobs', request, { timeout: 120_000 })).data;

export const MARKET_RESEARCH_CONTEXT_TIMEOUT_MS = 20_000;

export const getMarketResearchContext = async (params?: { snapshot_id?: number; trade_date?: string; market_scope?: string }): Promise<MarketResearchContext> => {
  try {
    return (await apiClient.get<MarketResearchContext>('/market/research-context', {
      params,
      timeout: MARKET_RESEARCH_CONTEXT_TIMEOUT_MS,
      skipRetry: true,
    })).data;
  } catch (error) {
    if (axios.isAxiosError(error) && (error.code === 'ECONNABORTED' || /timeout/i.test(error.message))) {
      throw new Error('市场研究快照读取超时，已停止等待。请稍后重试。');
    }
    throw error;
  }
};

export const listStockPools = async (): Promise<{ items: StockPool[]; total: number }> =>
  (await apiClient.get<{ items: StockPool[]; total: number }>('/pools')).data;

export const createStockPool = async (request: { name: string; pool_type: StockPool['pool_type']; description?: string; config: Record<string, unknown> }): Promise<StockPool> =>
  (await apiClient.post<StockPool>('/pools', request)).data;

export const generateStockPool = async (poolId: string, request: { dataset_snapshot_id: number; universe_snapshot_id: number; trade_date: string; factor_snapshot_id?: number; market_evidence_snapshot_id?: number }): Promise<StockPoolGeneration> =>
  (await apiClient.post<StockPoolGeneration>(`/pools/${poolId}/generate`, request)).data;

export const getStockPoolMembers = async (poolId: string, generationId?: string): Promise<StockPoolMember[]> =>
  (await apiClient.get<{ items: StockPoolMember[] }>(`/pools/${poolId}/members`, { params: { generation_id: generationId } })).data.items;

export const sealStockPoolSnapshot = async (poolId: string, generationId?: string): Promise<StockPoolSnapshot> =>
  (await apiClient.post<StockPoolSnapshot>(`/pools/${poolId}/snapshots`, { generation_id: generationId })).data;

export const listStockPoolSnapshots = async (poolId?: string): Promise<{ items: StockPoolSnapshot[]; total: number }> =>
  (await apiClient.get<{ items: StockPoolSnapshot[]; total: number }>('/pool-snapshots', { params: { pool_id: poolId } })).data;

export const getStockPoolSnapshot = async (snapshotId: number): Promise<StockPoolSnapshot> =>
  (await apiClient.get<StockPoolSnapshot>(`/pool-snapshots/${snapshotId}`)).data;

export const createPoolBacktestDraft = async (snapshotId: number, request: { strategy_version_id: string; start_date: string; end_date: string; initial_cash: number; benchmark_code?: string; parameters?: Record<string, unknown> }): Promise<{ status: string; experiment: Record<string, unknown>; pool_snapshot: StockPoolSnapshot }> =>
  (await apiClient.post(`/pool-snapshots/${snapshotId}/backtests`, request)).data;

export const BACKTEST_LIST_READ_TIMEOUT_MS = 30_000;

export const listBacktestRuns = async (limit = 50): Promise<{ items: BacktestRun[]; total: number }> => {
  try {
    return (await apiClient.get<{ items: BacktestRun[]; total: number }>('/backtest/runs', {
      params: { limit },
      timeout: BACKTEST_LIST_READ_TIMEOUT_MS,
      skipRetry: true,
    })).data;
  } catch (error) {
    return rejectPageTimeout('回测记录', error);
  }
};

export const runBacktestV1 = async (request: BacktestRunRequestV1, mode: 'quick' | 'full'): Promise<BacktestRun> =>
  (await apiClient.post<BacktestRun>(mode === 'quick' ? '/backtest/quick-runs' : '/backtest/runs', request, { timeout: 120000 })).data;

export const createBacktestJob = async (
  request: BacktestRunRequestV1,
  mode: 'quick' | 'full',
): Promise<BacktestJob> =>
  (await apiClient.post<BacktestJob>('/backtest/jobs', { ...request, run_mode: mode })).data;

export const listBacktestJobs = async (limit = 50): Promise<{ items: BacktestJob[]; total: number }> => {
  try {
    return (await apiClient.get<{ items: BacktestJob[]; total: number }>('/backtest/jobs', {
      params: { limit },
      timeout: BACKTEST_LIST_READ_TIMEOUT_MS,
      skipRetry: true,
    })).data;
  } catch (error) {
    return rejectPageTimeout('回测任务', error);
  }
};

export const getBacktestJob = async (jobId: string): Promise<BacktestJob> =>
  (await apiClient.get<BacktestJob>(`/backtest/jobs/${jobId}`)).data;

export const getBacktestJobLogs = async (jobId: string, afterId = 0): Promise<BacktestJobLog[]> =>
  (await apiClient.get<{ items: BacktestJobLog[] }>(`/backtest/jobs/${jobId}/logs`, { params: { after_id: afterId } })).data.items;

export const cancelBacktestJob = async (jobId: string): Promise<BacktestJob> =>
  (await apiClient.post<BacktestJob>(`/backtest/jobs/${jobId}/cancel`)).data;

export const retryBacktestJob = async (jobId: string): Promise<BacktestJob> =>
  (await apiClient.post<BacktestJob>(`/backtest/jobs/${jobId}/retry`)).data;

export const getBacktestRun = async (runId: string): Promise<BacktestRun> =>
  (await apiClient.get<BacktestRun>(`/backtest/runs/${runId}`)).data;

export const getBacktestMetrics = async (runId: string): Promise<BacktestMetric[]> =>
  (await apiClient.get<{ items: BacktestMetric[] }>(`/backtest/runs/${runId}/metrics`)).data.items;

export const getBacktestSeries = async (runId: string): Promise<{ daily: BacktestDailyPoint[]; custom_records: Array<Record<string, unknown>>; monthly_returns: Array<{ month: string; return: number | null }> }> =>
  (await apiClient.get(`/backtest/runs/${runId}/series`)).data;

export const getBacktestEvidence = async (runId: string, kind: 'positions' | 'orders' | 'trades' | 'logs' | 'attribution'): Promise<Array<Record<string, unknown>>> =>
  (await apiClient.get<{ items: Array<Record<string, unknown>> }>(`/backtest/runs/${runId}/${kind}`)).data.items;

export const compareBacktestRuns = async (runIds: string[]): Promise<{ runs: BacktestRun[]; series: Record<string, BacktestDailyPoint[]> }> =>
  (await apiClient.post('/backtest/compare', { run_ids: runIds })).data;

export const healMissingData = async (request: { days?: number; heal_kline?: boolean; heal_market_evidence?: boolean }): Promise<Record<string, unknown>> => {
  return (await apiClient.post('/data/heal-missing', request)).data;
};

export const createBacktestProtocol = async (request: Record<string, unknown>): Promise<Record<string, unknown>> =>
  (await apiClient.post('/backtest/protocols', request)).data;

export const createBacktestExperiment = async (request: BacktestRunRequestV1 & { hypothesis: string }): Promise<Record<string, unknown>> =>
  (await apiClient.post('/backtest/experiments', request)).data;

export const runBacktestMatrix = async (experimentId: string, request: { parameter_grid: Record<string, unknown[]>; start_date: string; end_date: string; initial_cash: number; symbols: string[]; event_limit: number }): Promise<Record<string, unknown>> =>
  (await apiClient.post(`/backtest/experiments/${experimentId}/matrix`, request, { timeout: 300000 })).data;

export const runPaperTrading = async (
  strategyId: number,
  request: PaperRunRequest
): Promise<PaperRunResult> => {
  const response = await apiClient.post<PaperRunResult>('/paper/run', {
    strategy_id: strategyId,
    ...request,
  });
  return response.data;
};

export const listPaperAccounts = async (): Promise<{ accounts: PaperAccount[]; total: number }> => {
  const response = await apiClient.get<{ accounts: PaperAccount[]; total: number }>('/paper/accounts');
  return response.data;
};

export const getPaperAccount = async (accountId: number): Promise<PaperAccount> => {
  const response = await apiClient.get<PaperAccount>(`/paper/${accountId}`);
  return response.data;
};

export const refreshPaperAccount = async (accountId: number): Promise<PaperRunResult> => {
  const response = await apiClient.post<PaperRunResult>(`/paper/${accountId}/refresh`);
  return response.data;
};

export const stopPaperAccount = async (accountId: number): Promise<PaperRunResult> => {
  const response = await apiClient.post<PaperRunResult>(`/paper/${accountId}/stop`);
  return response.data;
};

export const listPaperInstances = async (): Promise<{ items: PaperRuntimeInstance[]; total: number }> => {
  try {
    return (await apiClient.get<{ items: PaperRuntimeInstance[]; total: number }>('/paper/instances', pageRead)).data;
  } catch (error) {
    return rejectPageTimeout('模拟实例', error);
  }
};

export const getPaperInstance = async (instanceId: string): Promise<PaperRuntimeInstance> =>
  (await apiClient.get<PaperRuntimeInstance>(`/paper/instances/${instanceId}`)).data;

export const getPaperInstanceKlines = async (instanceId: string, symbol: string): Promise<PaperKlineSnapshot> =>
  (await apiClient.get<PaperKlineSnapshot>(`/paper/instances/${instanceId}/klines/${encodeURIComponent(symbol)}`)).data;

export const createPaperInstance = async (request: {
  name?: string;
  strategy_version_id: string;
  dataset_snapshot_id: number;
  factor_snapshot_id: number;
  universe_snapshot_id: number;
  pool_snapshot_id: number;
  research_protocol_id: string;
  qualifying_backtest_run_id: string;
  initial_cash: number;
  parameters?: Record<string, unknown>;
  capacity_limits?: Record<string, unknown>;
  feed_config?: Record<string, unknown>;
}): Promise<PaperRuntimeInstance> =>
  (await apiClient.post<PaperRuntimeInstance>('/paper/instances', request)).data;

export const paperInstanceAction = async (instanceId: string, action: 'start' | 'pause' | 'resume' | 'stop'): Promise<PaperRuntimeInstance> =>
  (await apiClient.post<PaperRuntimeInstance>(`/paper/instances/${instanceId}/${action}`)).data;

export const processPaperCycle = async (instanceId: string, request: { trade_date: string; data_available_at?: string; observed_at?: string; cycle_key?: string }): Promise<Record<string, unknown>> =>
  (await apiClient.post<Record<string, unknown>>(`/paper/instances/${instanceId}/cycles`, request)).data;

export const advancePaperInstances = async (request?: {
  instance_ids?: string[];
  max_dates?: number;
}): Promise<{
  instances_attempted: number;
  dates_processed: number;
  instances: Array<{
    instance_id: string;
    processed_count?: number;
    skipped_dates?: string[];
    failures?: Array<{ trade_date: string; error: string }>;
    pending_remaining?: number;
    last_processed_trade_date?: string | null;
    error?: string;
  }>;
}> => (await apiClient.post('/paper/instances/advance', request ?? {})).data;

export const getWatchContext = async (scope: 'business' | 'audit' = 'business'): Promise<WatchContext> => {
  try {
    return (await apiClient.get<WatchContext>('/watch/context', { params: { scope }, timeout: 30_000, skipRetry: true })).data;
  } catch (error) {
    return rejectPageTimeout('盯盘观察台', error);
  }
};

export const listRuntimeAlerts = async (status?: string): Promise<{ items: RuntimeAlert[]; total: number }> =>
  (await apiClient.get<{ items: RuntimeAlert[]; total: number }>('/watch/alerts', { params: status ? { status } : {} })).data;

export const acknowledgeRuntimeAlert = async (alertId: string): Promise<RuntimeAlert> =>
  (await apiClient.post<RuntimeAlert>(`/watch/alerts/${alertId}/acknowledge`)).data;

export const listWatchRules = async (): Promise<{ items: WatchRule[]; total: number }> =>
  (await apiClient.get<{ items: WatchRule[]; total: number }>('/watch/rules', { timeout: 30_000, skipRetry: true })).data;

export const createWatchRule = async (request: {
  name: string;
  rule_type: WatchRuleType;
  severity: WatchRule['severity'];
  config: WatchRule['config'];
}): Promise<WatchRule> => (await apiClient.post<WatchRule>('/watch/rules', request)).data;

export const previewWatchRule = async (ruleId: string): Promise<WatchRulePreview> =>
  (await apiClient.post<WatchRulePreview>(`/watch/rules/${ruleId}/preview`)).data;

export const evaluateWatchRule = async (ruleId: string): Promise<WatchRulePreview> =>
  (await apiClient.post<WatchRulePreview>(`/watch/rules/${ruleId}/evaluate`)).data;

export const getMonitorHealth = async (scope: 'business' | 'audit' = 'business'): Promise<MonitorHealth> =>
  (await apiClient.get<MonitorHealth>('/monitor/health', { params: { scope } })).data;

export const getDailyReviewDates = async (): Promise<{ items: string[]; total: number }> =>
  (await apiClient.get<{ items: string[]; total: number }>('/review/dates')).data;

export const getDailyReview = async (tradeDate: string): Promise<DailyReviewContext> =>
  (await apiClient.get<DailyReviewContext>(`/review/${tradeDate}`)).data;

export const assembleDailyReview = async (tradeDate: string): Promise<DailyReviewContext> =>
  (await apiClient.post<DailyReviewContext>(`/review/${tradeDate}/assemble`)).data;

export const saveDailyReview = async (tradeDate: string, request: { author_name?: string; summary?: string; next_day_plan?: string }): Promise<DailyReviewContext> =>
  (await apiClient.put<DailyReviewContext>(`/review/${tradeDate}`, request)).data;

export const sealDailyReview = async (tradeDate: string): Promise<DailyReviewContext> =>
  (await apiClient.post<DailyReviewContext>(`/review/${tradeDate}/seal`)).data;

const rejectPageTimeout = (label: string, error: unknown): never => {
  if (axios.isAxiosError(error) && (error.code === 'ECONNABORTED' || /timeout/i.test(String(error.message)))) {
    throw new Error(`${label}读取超时，已停止等待。请稍后重试。`);
  }
  throw error;
};

export const DATA_STATUS_READ_TIMEOUT_MS = 20_000;

export const getDataStatus = async <T = unknown>(): Promise<T> => {
  try {
    const response = await apiClient.get<T>('/data/status', {
      timeout: DATA_STATUS_READ_TIMEOUT_MS,
      skipRetry: true,
    });
    return response.data;
  } catch (error) {
    return rejectPageTimeout('数据状态', error);
  }
};

export const triggerDataSync = async (request?: {
  symbols?: string[];
  timeframes?: string[];
  start_date?: string;
  end_date?: string;
  job_name?: string;
}): Promise<GenericApiResponse> => {
  const response = await apiClient.post<GenericApiResponse>('/data/sync', request || {});
  return response.data;
};

export type DataSyncConfigResponse = {
  defaultSymbols: string[];
  defaultTimeframes: string[];
  defaultHistoryDays: number;
};

export type DataSyncScheduleConfig = {
  enabled: boolean;
  mode?: string;
  syncAllAshare?: boolean;
  runHour?: number;
  runMinute?: number;
  intervalMinutes: number;
  historyDays: number;
  symbols: string[];
  timeframes: string[];
  lastRunAt?: string | null;
  lastStartedAt?: string | null;
  lastFinishedAt?: string | null;
  nextRunAt?: string | null;
  lastJobId?: string | null;
  lastError?: string | null;
};

export type DataTableStatsResponse = {
  totalRecords: number;
  totalPairs: number;
  marketStats?: Record<string, { totalRecords: number; totalPairs: number; totalSymbols: number }>;
  tables: Array<{
    tableName: string;
    exchange?: string;
    symbol?: string;
    name?: string;
    timeframe?: string;
    recordCount: number;
    firstTimestamp?: number | null;
    lastTimestamp?: number | null;
  }>;
};

export type TushareEndpoint = {
  endpoint_code: string;
  module_code: string;
  display_name: string;
  required_credits: number;
  requires_independent_authorization: boolean;
  schedule_kind: string;
  storage_dataset: string;
  contract_url: string;
  baseline_state: string;
  enabled: boolean;
  permission_state?: string | null;
  checked_at?: string | null;
  supported_fields?: string[] | null;
  rate_limit?: string | null;
  error_code?: string | null;
  error_message?: string | null;
};

export type TushareEndpointCatalogResponse = {
  credit_tier: number;
  items: TushareEndpoint[];
  total: number;
};

export type TushareEndpointProbeResponse = {
  endpoint_code: string;
  permission_state: string;
  checked_at?: string | null;
  supported_fields?: string[] | null;
  rate_limit?: string | null;
  error_code?: string | null;
  error_message?: string | null;
};

export type ResearchDataset = {
  code: string;
  name: string;
  primary_source: string;
  fallback_source?: string | null;
  schema_version: string;
  enabled: boolean;
  latest_partition_id?: number | null;
  start_date?: string | null;
  end_date?: string | null;
  row_count?: number | null;
  symbol_count?: number | null;
  partition_status?: string | null;
  content_hash?: string | null;
  available_at?: string | null;
  knowledge_cutoff_at?: string | null;
  requested_source?: string | null;
  actual_source?: string | null;
  fallback_reason?: string | null;
  response_hash?: string | null;
  blocking_issues?: number | null;
};

export type ResearchDatasetSnapshot = {
  id: number;
  name: string;
  status: 'draft' | 'sealed' | 'failed';
  knowledge_cutoff_at: string;
  manifest_hash?: string | null;
  created_at: string;
  sealed_at?: string | null;
  partition_count?: number;
  datasets?: string[] | null;
};

export type DailyReferenceOrchestrationRun = {
  id: number;
  tradeDate: string;
  status: 'queued' | 'running' | 'not_trading_day' | 'skipped' | 'blocked' | 'failed' | 'sealed';
  syncJobId?: number | null;
  snapshotId?: number | null;
  marketEvidenceSnapshotId?: number | null;
  attemptCount: number;
  result?: Record<string, unknown>;
  errorMessage?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  updatedAt?: string | null;
};

export type DailyReferenceSchedule = {
  code: string;
  cron: string;
  timezone: string;
  configured?: boolean;
  enabled: boolean;
  catchupDays: number;
  maxRetries: number;
  updatedAt?: string | null;
  nextRunAt?: string | null;
  configuredNextRunAt?: string | null;
  runtimeEnabled?: boolean;
  runnerOnline?: boolean;
  jobRegistered?: boolean;
  effectiveNextRunAt?: string | null;
  runtimeStatus?: 'running' | 'runner_offline' | 'disabled' | string;
  dailyBarsWatermark?: string | null;
  watermarkUpdatedAt?: string | null;
  lastRun?: DailyReferenceOrchestrationRun | null;
};

export const getDataConfig = async (): Promise<DataSyncConfigResponse> => {
  const response = await apiClient.get<DataSyncConfigResponse>('/data/config');
  return response.data;
};

export const getDataTableStats = async (): Promise<DataTableStatsResponse> => {
  const response = await apiClient.get<DataTableStatsResponse>('/data/table-stats');
  return response.data;
};

export const getTushareEndpoints = async (module?: string): Promise<TushareEndpointCatalogResponse> => {
  const response = await apiClient.get<TushareEndpointCatalogResponse>('/data/tushare/endpoints', {
    params: module ? { module } : undefined,
  });
  return response.data;
};

export const getResearchDatasets = async (): Promise<{ items: ResearchDataset[] }> => {
  const response = await apiClient.get<{ items: ResearchDataset[] }>('/data/datasets');
  return response.data;
};

export const getResearchDatasetSnapshots = async (limit = 10): Promise<{ items: ResearchDatasetSnapshot[] }> => {
  const response = await apiClient.get<{ items: ResearchDatasetSnapshot[] }>('/data/snapshots', { params: { limit } });
  return response.data;
};

export const getDailyReferenceSchedule = async (): Promise<DailyReferenceSchedule> => {
  const response = await apiClient.get<DailyReferenceSchedule>('/data/schedules/daily');
  return response.data;
};

export const updateDailyReferenceSchedule = async (request: {
  enabled?: boolean;
  cron?: string;
  timezone?: string;
  catchupDays?: number;
  maxRetries?: number;
}): Promise<DailyReferenceSchedule> => {
  const response = await apiClient.put<DailyReferenceSchedule>('/data/schedules/daily', request);
  return response.data;
};

export const runDailyReferenceSchedule = async (request?: {
  trade_date?: string;
  symbols?: string[];
  force?: boolean;
}): Promise<GenericApiResponse & { status?: string; tradeDate?: string; message?: string }> => {
  const response = await apiClient.post<GenericApiResponse & { status?: string; tradeDate?: string; message?: string }>(
    '/data/schedules/daily/run',
    request || { force: true },
  );
  return response.data;
};

export const syncAllMarketHistory = async (request?: {
  history_days?: number;
  start_date?: string;
  end_date?: string;
  refresh_universe?: boolean;
  include_signals?: boolean;
  job_name?: string;
}): Promise<GenericApiResponse & {
  jobId?: string;
  job_id?: number;
  tradeDateCount?: number;
  startDate?: string;
  endDate?: string;
  includeSignals?: boolean;
  mode?: string;
}> => {
  const response = await apiClient.post('/data/history/sync-all', request || { history_days: 365, include_signals: true });
  return response.data;
};

export const probeTushareEndpoint = async (
  endpointCode: string,
  request: { params?: Record<string, unknown>; fields?: string } = {},
): Promise<TushareEndpointProbeResponse> => {
  const response = await apiClient.post<TushareEndpointProbeResponse>(`/data/tushare/endpoints/${endpointCode}/probe`, request);
  return response.data;
};

export const getDataSchedule = async (): Promise<DataSyncScheduleConfig> => {
  const response = await apiClient.get<DataSyncScheduleConfig>('/data/schedule');
  return response.data;
};

export const updateDataSchedule = async (request: Partial<DataSyncScheduleConfig>): Promise<DataSyncScheduleConfig> => {
  const response = await apiClient.put<DataSyncScheduleConfig>('/data/schedule', request);
  return response.data;
};

export const startDataSync = async (request?: {
  symbols?: string[];
  timeframes?: string[];
  startDate?: string;
  endDate?: string;
  historyDays?: number;
  jobName?: string;
}): Promise<GenericApiResponse> => {
  const response = await apiClient.post<GenericApiResponse>('/data/start', request || {});
  return response.data;
};

export const addDataSymbol = async (symbol: string): Promise<{ symbol: string; added: boolean; defaultSymbols: string[] }> => {
  const response = await apiClient.post<{ symbol: string; added: boolean; defaultSymbols: string[] }>('/data/symbols', { symbol });
  return response.data;
};

export const lookupSymbolNames = async (
  symbols: string[],
): Promise<Record<string, string>> => {
  const unique = Array.from(new Set(symbols.map((item) => String(item || '').trim()).filter(Boolean)));
  if (!unique.length) return {};
  const response = await apiClient.post<{ names: Record<string, string> }>('/data/symbol-names', {
    symbols: unique,
  });
  return response.data.names || {};
};

export const removeDataSymbol = async (symbol: string): Promise<{ symbol: string; removed: boolean; defaultSymbols: string[] }> => {
  const response = await apiClient.delete<{ symbol: string; removed: boolean; defaultSymbols: string[] }>('/data/symbols', { data: { symbol } });
  return response.data;
};

export const deleteDataKlines = async (request: { symbol: string; timeframe?: string }): Promise<{ message: string; deleted: number }> => {
  const response = await apiClient.post<{ message: string; deleted: number }>('/data/delete-data', request);
  return response.data;
};

export const getResearchFactorLibrary = async (): Promise<{ items: ResearchFactor[] }> => {
  const response = await apiClient.get<{ items: ResearchFactor[] }>('/factors/research/library');
  return response.data;
};

export const getFactorComputeRuns = async (limit = 100): Promise<{ items: FactorComputeRun[] }> => {
  const response = await apiClient.get<{ items: FactorComputeRun[] }>('/factor-compute-runs', { params: { limit } });
  return response.data;
};

export const getResearchFactorMetrics = async (factorId: number): Promise<{ factor: ResearchFactor; metrics: FactorMetricRow[] }> => {
  const response = await apiClient.get<{ factor: ResearchFactor; metrics: FactorMetricRow[] }>(`/factors/${factorId}/metrics`);
  return response.data;
};

export const getResearchFactorValues = async (factorId: number, limit = 500): Promise<{ items: FactorValueRow[] }> => {
  const response = await apiClient.get<{ items: FactorValueRow[] }>(`/factors/${factorId}/values`, { params: { limit } });
  return response.data;
};

export const getFactorCorrelations = async (tradeDate?: string): Promise<{ items: FactorCorrelationRow[] }> => {
  const response = await apiClient.get<{ items: FactorCorrelationRow[] }>('/factor-correlations', { params: tradeDate ? { trade_date: tradeDate } : undefined });
  return response.data;
};

export const runDailyFactorSchedule = async (request: {
  trade_date: string;
  dataset_snapshot_id: number;
  universe_snapshot_id: number;
}): Promise<Record<string, unknown>> => {
  const response = await apiClient.post<Record<string, unknown>>('/factor-schedules/run-daily', request);
  return response.data;
};

export const createResearchFactor = async (request: {
  factor_code: string;
  factor_name: string;
  category: string;
  description?: string;
  python_code: string;
}): Promise<Record<string, unknown>> => {
  const response = await apiClient.post<Record<string, unknown>>('/factors', request);
  return response.data;
};

// ---------------------------------------------------------------------------
// AI 策略研发（BitPro 式多智能体闭环）
// ---------------------------------------------------------------------------

export const getAgentResearchConfig = async (): Promise<AgentResearchConfig> => {
  const response = await apiClient.get<AgentResearchConfig>('/agent/config');
  return response.data;
};

export const listAgentTasks = async (limit = 50): Promise<{ tasks: AgentTaskSummary[] }> => {
  const response = await apiClient.get<{ tasks: AgentTaskSummary[] }>('/agent/tasks', { params: { limit } });
  return response.data;
};

export const createAgentTask = async (request: AgentTaskCreateRequest): Promise<{ task: AgentTaskSummary }> => {
  const response = await apiClient.post<{ task: AgentTaskSummary }>('/agent/tasks', request);
  return response.data;
};

export const getAgentTask = async (taskId: string): Promise<AgentTaskDetail> => {
  const response = await apiClient.get<AgentTaskDetail>(`/agent/tasks/${taskId}`);
  return response.data;
};

export const listAgentIterations = async (taskId: string): Promise<{ iterations: AgentIteration[] }> => {
  const response = await apiClient.get<{ iterations: AgentIteration[] }>(`/agent/tasks/${taskId}/iterations`);
  return response.data;
};

export const startAgentTask = async (taskId: string): Promise<{ task: AgentTaskSummary }> => {
  const response = await apiClient.post<{ task: AgentTaskSummary }>(`/agent/tasks/${taskId}/start`);
  return response.data;
};

export const stopAgentTask = async (taskId: string): Promise<{ task: AgentTaskSummary }> => {
  const response = await apiClient.post<{ task: AgentTaskSummary }>(`/agent/tasks/${taskId}/stop`);
  return response.data;
};

export const deleteAgentTask = async (taskId: string): Promise<{ deleted: boolean }> => {
  const response = await apiClient.delete<{ deleted: boolean }>(`/agent/tasks/${taskId}`);
  return response.data;
};

export const promoteAgentIteration = async (taskId: string, iteration: number): Promise<{ strategy_version: { id: string; name: string; version: number }; iteration: number }> => {
  const response = await apiClient.post<{ strategy_version: { id: string; name: string; version: number }; iteration: number }>(`/agent/tasks/${taskId}/promote`, { iteration });
  return response.data;
};

// ---------------------------------------------------------------------------
// A 股实盘工作台（预检 + 晋级管线 + 审计，真实委托需券商通道配置）
// ---------------------------------------------------------------------------

export const getLiveTradingStatus = async (): Promise<LiveTradingStatus> => {
  const response = await apiClient.get<LiveTradingStatus>('/live/status');
  return response.data;
};

export const getLivePromotionCandidates = async (): Promise<{ candidates: LivePromotionCandidate[] }> => {
  const response = await apiClient.get<{ candidates: LivePromotionCandidate[] }>('/live/promotion-candidates');
  return response.data;
};

export const runLivePreflight = async (request: LivePreflightRequest): Promise<LivePreflightResult> => {
  const response = await apiClient.post<LivePreflightResult>('/live/preflight', request);
  return response.data;
};

export const requestLiveDeployment = async (request: LiveDeploymentRequest): Promise<LiveDeploymentResult> => {
  const response = await apiClient.post<LiveDeploymentResult>('/live/enable', request);
  return response.data;
};

export const listLiveEvents = async (limit = 50): Promise<{ events: LiveAuditEvent[] }> => {
  const response = await apiClient.get<{ events: LiveAuditEvent[] }>('/live/events', { params: { limit } });
  return response.data;
};
