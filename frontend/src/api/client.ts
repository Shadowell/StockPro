import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { Stock, Sector, StockFilterResponse, AIAnalysis, DailyChartData, IntradayChartData, MarketSector, MarketStock, TaskStatus, HotConceptItem, ThsHotItem, LianbanLadderResponse, RunSentimentResponse, SentimentItem, AIStockAnalyzeResponse, ConceptIntradayKlineItem, ConceptLeaderStock, StockCandidate, StockFundamentals, MessageStreamResponse, MarketCalendarEvent, CalendarRefreshResponse, MarketOverview, Strategy, StrategyResult, StrategyExecutionResult, SaveStrategyRequest, StartStrategyRequest } from '../types';

const API_URL = import.meta.env.VITE_API_URL || '/api/v1';

// Retry configuration
const retryConfig = {
  maxRetries: 3,
  baseDelay: 1000,
  retryableStatus: [408, 429, 500, 502, 503, 504],
};

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

export const generateMarketCalendarWithAI = async (params: { start_date: string; end_date: string }): Promise<any> => {
  const response = await apiClient.post<any>('/market/calendar/generate-with-ai', null, { params });
  return response.data;
};

// Preset Tasks API
export const getPresetTasks = async (): Promise<any[]> => {
  const response = await apiClient.get<any[]>('/preset-tasks');
  return response.data;
};

export const executePresetTask = async (request: any): Promise<any> => {
  const response = await apiClient.post<any>('/preset-tasks/execute', request);
  return response.data;
};

export const getPresetTaskStatus = async (): Promise<any> => {
  const response = await apiClient.get<any>('/preset-tasks/status');
  return response.data;
};

export const cancelPresetTask = async (): Promise<any> => {
  const response = await apiClient.post<any>('/preset-tasks/cancel');
  return response.data;
};

// Batch Import API
export const importHistoricalData = async (request: any): Promise<any> => {
  const response = await apiClient.post<any>('/batch-import/historical-data', request);
  return response.data;
};

export const getImportStatus = async (): Promise<any> => {
  const response = await apiClient.get<any>('/batch-import/status');
  return response.data;
};

export const cancelImportTask = async (): Promise<any> => {
  const response = await apiClient.post<any>('/batch-import/cancel');
  return response.data;
};

// MA Data Import API
export const importMAData = async (mainBoardOnly: boolean = true): Promise<any> => {
  const response = await apiClient.post<any>('/batch-import/ma-data', { main_board_only: mainBoardOnly });
  return response.data;
};

export const getMADataStats = async (): Promise<any> => {
  const response = await apiClient.get<any>('/batch-import/ma-data/stats');
  return response.data;
};

// Data Development API
export const getDataDevTasks = async (): Promise<any[]> => {
  const response = await apiClient.get<any[]>('/data-dev/tasks');
  return response.data;
};

export const createDataDevTask = async (task: any): Promise<any> => {
  const response = await apiClient.post<any>('/data-dev/tasks', task);
  return response.data;
};

export const updateDataDevTask = async (taskId: number, task: any): Promise<any> => {
  const response = await apiClient.put<any>(`/data-dev/tasks/${taskId}`, task);
  return response.data;
};

export const deleteDataDevTask = async (taskId: number): Promise<any> => {
  const response = await apiClient.delete<any>(`/data-dev/tasks/${taskId}`);
  return response.data;
};

export const runDataDevTask = async (taskId: number): Promise<any> => {
  const response = await apiClient.post<any>(`/data-dev/tasks/${taskId}/run`);
  return response.data;
};

export const getTaskLogs = async (taskId: number, limit = 50): Promise<any> => {
  const response = await apiClient.get<any>(`/data-dev/tasks/${taskId}/logs?limit=${limit}`);
  return response.data;
};

// Database Management API
export const getDatabaseTables = async (): Promise<any[]> => {
  const response = await apiClient.get<any[]>('/database/tables');
  return response.data;
};

export const executeSqlQuery = async (query: string): Promise<any> => {
  const response = await apiClient.post<any>('/database/query', { query });
  return response.data;
};

export const getTableData = async (tableName: string, limit: number = 100): Promise<any> => {
  const response = await apiClient.get<any>(`/database/table/${tableName}?limit=${limit}`);
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
