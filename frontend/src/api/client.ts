import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { Stock, Sector, StockFilterResponse, AIAnalysis, DailyChartData, IntradayChartData, MarketSector, MarketStock, TaskStatus, HotConceptItem, ThsHotItem, LianbanLadderResponse, RunSentimentResponse, SentimentItem, AIStockAnalyzeResponse, ConceptIntradayKlineItem, ConceptLeaderStock, StockCandidate, StockFundamentals, MessageStreamResponse, MarketCalendarEvent, CalendarRefreshResponse, MarketOverview, Strategy, StrategyResult, StrategyExecutionResult, SaveStrategyRequest, StartStrategyRequest } from '../types';

const API_URL = import.meta.env.VITE_API_URL || '/api/v1';

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

export interface DataHubScreenerResponse {
  status: string;
  snapshot: DataHubScreenerSnapshot;
  data: MAConvergenceStock[];
  count: number;
  total_found: number;
  params: MAConvergenceParams;
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

// Extend axios config type to include retry count
interface RetryableRequestConfig extends InternalAxiosRequestConfig {
  __retryCount?: number;
}

export const apiClient = axios.create({
  baseURL: API_URL,
  timeout: 60000, // 60 seconds timeout
  headers: {
    'Content-Type': 'application/json',
  },
});

// Response interceptor for automatic retry with exponential backoff
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetryableRequestConfig | undefined;
    if (!config) {
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

export const getMarketOverview = async (): Promise<MarketOverview> => {
  const response = await apiClient.get<MarketOverview>('/market/overview');
  return response.data;
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

export const getFilteredStocks = async (): Promise<StockFilterResponse> => {
  const response = await apiClient.get<StockFilterResponse>('/stocks/filter');
  return response.data;
};

export const getHotSectors = async (): Promise<Sector[]> => {
  const response = await apiClient.get<Sector[]>('/sectors/hot');
  return response.data;
};

export const analyzeStocks = async (stocks: Stock[]): Promise<AIAnalysis[]> => {
  const response = await apiClient.post<AIAnalysis[]>('/ai/analyze', { stocks });
  return response.data;
};

export const getDailyChart = async (symbol: string): Promise<DailyChartData[]> => {
  const response = await apiClient.get<DailyChartData[]>(`/charts/daily/${symbol}`);
  return response.data;
};

export const getIntradayChart = async (symbol: string): Promise<IntradayChartData[]> => {
  const response = await apiClient.get<IntradayChartData[]>(`/charts/intraday/${symbol}`);
  return response.data;
};

export const getStockFundamentals = async (symbol: string): Promise<StockFundamentals> => {
  const response = await apiClient.get<StockFundamentals>(`/market/fundamentals/${symbol}`);
  return response.data;
};

export const getMarketSectors = async (): Promise<MarketSector[]> => {
  const response = await apiClient.get<MarketSector[]>('/market/sectors');
  return response.data;
};

export const getMarketStocks = async (): Promise<MarketStock[]> => {
  const response = await apiClient.get<MarketStock[]>('/market/stocks');
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

export const searchStocks = async (params: { q: string; limit?: number }): Promise<StockCandidate[]> => {
  const response = await apiClient.get<StockCandidate[]>('/stocks/search', { params });
  return response.data;
};

export const getHotConcepts = async (limit = 50, date?: string): Promise<HotConceptItem[]> => {
  const response = await apiClient.get<HotConceptItem[]>('/market/hot-concepts', { params: { limit, date } });
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
  params?: MAConvergenceParams
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

export const getStrategies = async (): Promise<Strategy[]> => {
  const response = await apiClient.get<Strategy[]>('/strategy/list');
  return response.data;
};

export const getStrategy = async (strategyId: number): Promise<Strategy> => {
  const response = await apiClient.get<Strategy>(`/strategy/${strategyId}`);
  return response.data;
};

export const saveStrategy = async (data: SaveStrategyRequest): Promise<{ success: boolean; id?: number; message?: string; error?: string }> => {
  const response = await apiClient.post<{ success: boolean; id?: number; message?: string; error?: string }>('/strategy/save', data);
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

// ========== 选股器 API ==========

export interface MAConvergenceStock {
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

export interface MAConvergenceParams {
  days?: number;
  max_range_pct?: number;
  main_board_only?: boolean;
  min_price?: number;
  max_price?: number;
  limit?: number;
}

export interface MAConvergenceResponse {
  status: string;
  data: MAConvergenceStock[];
  count: number;
  total_found: number;
  params: MAConvergenceParams;
  description: string;
}

export const scanMAConvergenceStocks = async (params?: MAConvergenceParams): Promise<MAConvergenceResponse> => {
  const response = await apiClient.get<MAConvergenceResponse>('/screener/ma-convergence', { params });
  return response.data;
};

export const getStockMADetail = async (symbol: string, days?: number): Promise<Record<string, unknown>> => {
  const response = await apiClient.get<Record<string, unknown>>(`/screener/ma-convergence/${symbol}`, { params: { days } });
  return response.data;
};

export const checkStockMAConvergence = async (symbol: string, days?: number, max_range_pct?: number): Promise<Record<string, unknown>> => {
  const response = await apiClient.get<Record<string, unknown>>(`/screener/ma-convergence/check/${symbol}`, { params: { days, max_range_pct } });
  return response.data;
};

// ============ 复盘中心 API ============

export interface LianbanHistoryStock {
  code: string;
  name: string;
  level: number;
  change_percent: number;
  price: number;
  duration_days?: number;
  reason?: string;
}

export interface LianbanHistoryDay {
  date: string;
  stocks: LianbanHistoryStock[];
}

export interface SectorStatItem {
  name: string;
  code?: string;
  change_percent: number;
  leader_stock?: string;
  rank?: number;
}

export interface DailySectorStats {
  date: string;
  sectors: SectorStatItem[];
}

export const getLianbanHistory = async (days: number = 30, minLevel: number = 2): Promise<LianbanHistoryDay[]> => {
  const response = await apiClient.get<LianbanHistoryDay[]>('/market/pulse/lianban-history', { 
    params: { days, min_level: minLevel } 
  });
  return response.data;
};

export const getDailySectorStats = async (
  days: number = 30, 
  minChangePct: number = 3.0,
  topN: number = 15
): Promise<DailySectorStats[]> => {
  const response = await apiClient.get<DailySectorStats[]>('/market/pulse/daily-stats', { 
    params: { days, min_change_pct: minChangePct, top_n: topN } 
  });
  return response.data;
};

export const syncTodayConceptSectors = async (): Promise<{status: string; count: number; date?: string}> => {
  const response = await apiClient.post('/market/pulse/sync-today');
  return response.data;
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
    timeout: 600000  // 10分钟超时
  });
  return response.data;
};

export interface ReplayNote {
  note_date: string;
  view_mode: 'sector' | 'lianban' | string;
  template_id?: string | null;
  headline?: string | null;
  main_line?: string | null;
  core_targets?: string | null;
  risk_alert?: string | null;
  action_plan?: string | null;
  extra?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export const listReplayNotes = async (limit: number = 60): Promise<ReplayNote[]> => {
  const response = await apiClient.get<{ status: string; data: ReplayNote[] }>('/market/pulse/replay-notes', { params: { limit } });
  return response.data.data || [];
};

export const getReplayNote = async (noteDate: string): Promise<ReplayNote | null> => {
  const response = await apiClient.get<{ status: string; data: ReplayNote | null }>(`/market/pulse/replay-notes/${noteDate}`);
  return response.data.data;
};

export const saveReplayNote = async (payload: Partial<ReplayNote> & { note_date: string }): Promise<ReplayNote> => {
  const response = await apiClient.post<{ status: string; data: ReplayNote }>('/market/pulse/replay-notes', payload);
  return response.data.data;
};
