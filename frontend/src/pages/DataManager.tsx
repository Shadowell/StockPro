import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Activity,
  Database,
  RefreshCw,
  Download,
  Trash2,
  Play,
  CheckCircle,
  XCircle,
  Clock,
  Loader2,
  HardDrive,
  BarChart3,
  Search,
  ChevronDown,
  Zap,
  Calendar,
  TrendingUp,
  AlertCircle,
  Info,
  Plus,
  X,
  ListChecks,
} from 'lucide-react';
import { SELECTED_SEGMENT_BORDER_CLASS, SELECTED_SEGMENT_CLASS } from '../utils/selectionStyles';
import {
  dataSyncApi,
  marketApi,
  okxNativeSyncApi,
  type DataSyncConfigResponse,
  type DataSyncJobSummary,
  type DataSyncMarketStats,
  type DataSyncMeta,
  type DataSyncQualityItem,
  type DataSyncQualityResponse,
  type DataSyncScheduleConfig,
  type DataSyncStatusResponse,
  type DataSyncTableStat,
  type OkxNativeSyncScheduleConfig,
} from '../api/client';
import { useStore } from '../stores/useStore';
import ThemeDialog from '../components/ThemeDialog';
import SymbolIcon, { extractSymbolBase } from '../components/SymbolIcon';
import { formatTimeframeLabel } from '../utils/timeframe';

// ============================================
// 常量
// ============================================

const TIMEFRAME_LABELS: Record<string, string> = {
  '1m': '1M',
  '5m': '5M',
  '15m': '15M',
  '30m': '30M',
  '1h': '1H',
  '4h': '4H',
  '12h': '12H',
  '1d': '1D',
};

const TIMEFRAME_COLORS: Record<string, string> = {
  '1m': 'from-rose-500/20 to-rose-600/5 border-rose-500/30',
  '5m': 'from-violet-500/20 to-violet-600/5 border-violet-500/30',
  '15m': 'from-blue-500/20 to-blue-600/5 border-blue-500/30',
  '30m': 'from-indigo-500/20 to-indigo-600/5 border-indigo-500/30',
  '1h': 'from-cyan-500/20 to-cyan-600/5 border-cyan-500/30',
  '4h': 'from-emerald-500/20 to-emerald-600/5 border-emerald-500/30',
  '12h': 'from-teal-500/20 to-teal-600/5 border-teal-500/30',
  '1d': 'from-amber-500/20 to-amber-600/5 border-amber-500/30',
};

const TIMEFRAME_BADGE: Record<string, string> = {
  '1m': 'bg-rose-500/20 text-rose-300 border-rose-500/30',
  '5m': 'bg-violet-500/20 text-violet-300 border-violet-500/30',
  '15m': 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  '30m': 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30',
  '1h': 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
  '4h': 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  '12h': 'bg-teal-500/20 text-teal-300 border-teal-500/30',
  '1d': 'bg-amber-500/20 text-amber-300 border-amber-500/30',
};

const TIMEFRAME_ORDER = ['1m', '5m', '15m', '30m', '1h', '4h', '12h', '1d'];
const SYNC_TIMEFRAME_ORDER = ['15m', '30m', '1h', '4h', '12h', '1d'];
const SYNC_HISTORY_DAYS = 90;

function dataTimeframeLabel(timeframe: string): string {
  return TIMEFRAME_LABELS[timeframe] || formatTimeframeLabel(timeframe);
}

type SyncFeedbackType = 'info' | 'success' | 'error';

type TargetSyncFeedback = {
  message: string;
  type: SyncFeedbackType;
};

type SyncDialogMode = 'daily' | 'custom' | 'full';
type DataMarketType = 'swap' | 'spot';

type AddSymbolGroup = {
  base: string;
  spotSymbol?: string;
  swapSymbol?: string;
};

const EMPTY_MARKET_STATS: Record<DataMarketType, DataSyncMarketStats> = {
  swap: { totalRecords: 0, totalPairs: 0, totalSymbols: 0 },
  spot: { totalRecords: 0, totalPairs: 0, totalSymbols: 0 },
};

const ADD_SYMBOL_HISTORY_RANGE_OPTIONS = [
  { label: '近3月', days: 90 },
];

// ============================================
// 辅助函数
// ============================================

function dateDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function formatTs(ts: number | null): string {
  if (!ts) return '-';
  return new Date(ts).toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '-';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function getCoinBase(symbol: string): string {
  if (/^\d{6}\.(?:SH|SZ|BJ)$/i.test(symbol)) return symbol.split('.')[0];
  return extractSymbolBase(symbol) || symbol;
}

function isUsdtSwapSymbol(symbol: string): boolean {
  return /^[A-Z0-9]{1,30}\/USDT:USDT$/.test(symbol);
}

function dataMarketLabel(marketType: DataMarketType): string {
  return marketType === 'swap' ? '期货预留' : 'A股';
}

function dedupeSymbols(symbols: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const raw of symbols) {
    const symbol = raw?.trim();
    if (!symbol || seen.has(symbol)) continue;
    seen.add(symbol);
    result.push(symbol);
  }
  return result;
}

function sortTimeframes(timeframes: string[]): string[] {
  const known = TIMEFRAME_ORDER.filter((timeframe) => timeframes.includes(timeframe));
  const extra = timeframes.filter((timeframe) => !TIMEFRAME_ORDER.includes(timeframe));
  return [...known, ...extra];
}

function splitMarketSymbolCounts(symbols: string[]): Record<DataMarketType, number> {
  return {
    swap: symbols.filter((symbol) => isUsdtSwapSymbol(symbol)).length,
    spot: symbols.filter((symbol) => !isUsdtSwapSymbol(symbol)).length,
  };
}

function DataMarketSplit({
  swap,
  spot,
  formatter = formatCount,
}: {
  swap: number;
  spot: number;
  formatter?: (value: number) => string;
}) {
  return (
    <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
      <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/10 px-2 py-1.5">
        <div className="text-cyan-300/80">期货预留</div>
        <div className="mt-0.5 font-semibold text-white">{formatter(swap)}</div>
      </div>
      <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-2 py-1.5">
        <div className="text-emerald-300/80">A股</div>
        <div className="mt-0.5 font-semibold text-white">{formatter(spot)}</div>
      </div>
    </div>
  );
}

function formatOkxInstrumentId(symbol: string): string {
  const base = getCoinBase(symbol).toUpperCase();
  return isUsdtSwapSymbol(symbol) ? `${base}-USDT-SWAP` : `${base}-USDT`;
}

function buildAddSymbolGroups(symbols: string[]): AddSymbolGroup[] {
  const groups = new Map<string, AddSymbolGroup>();
  for (const symbol of symbols) {
    const base = getCoinBase(symbol).toUpperCase();
    const group = groups.get(base) || { base };
    if (isUsdtSwapSymbol(symbol)) {
      group.swapSymbol = symbol;
    } else {
      group.spotSymbol = symbol;
    }
    groups.set(base, group);
  }

  return Array.from(groups.values()).sort((a, b) => a.base.localeCompare(b.base));
}

function getSyncTargetKey(symbol: string, timeframe: string): string {
  return `${symbol}_${timeframe}`;
}

function normalizeUsdtCandidate(value: string): string | null {
  const raw = String(value || '').trim().toUpperCase();
  const okxSwapMatch = raw.match(/^([A-Z0-9]{1,30})-USDT-SWAP$/);
  if (okxSwapMatch) return `${okxSwapMatch[1]}/USDT:USDT`;
  if (/^[A-Z0-9]{1,30}\/USDT:USDT$/.test(raw)) return raw;
  if (!/^[A-Z0-9]{1,30}\/USDT$/.test(raw)) return null;
  return raw;
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '-';
  if (seconds < 60) return `${seconds.toFixed(1)}秒`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) return `${minutes}分${rest}秒`;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return `${hours}时${mins}分`;
}

function syncStatusLabel(status: string | null | undefined): string {
  if (status === 'queued' || status === 'pending') return '排队中';
  if (status === 'running' || status === 'syncing') return '同步中';
  if (status === 'completed') return '完成';
  if (status === 'completed_with_errors') return '部分失败';
  if (status === 'error') return '失败';
  return status || '-';
}

function syncStatusTone(status: string | null | undefined): string {
  if (status === 'completed') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300';
  if (status === 'completed_with_errors') return 'border-amber-500/30 bg-amber-500/10 text-amber-300';
  if (status === 'error') return 'border-red-500/30 bg-red-500/10 text-red-300';
  if (status === 'queued' || status === 'pending') return 'border-gray-500/30 bg-gray-500/10 text-gray-300';
  return 'border-blue-500/30 bg-blue-500/10 text-blue-300';
}

function formatJobRange(job: DataSyncJobSummary): string {
  if (job.startDate || job.endDate) return `${job.startDate || '-'} ~ ${job.endDate || '至今'}`;
  return `回溯 ${job.historyDays || SYNC_HISTORY_DAYS} 天`;
}

function formatListScope(values: string[], total: number | undefined, maxVisible: number): string {
  const uniqueValues = Array.from(new Set(values.filter(Boolean)));
  const count = total || uniqueValues.length;
  if (uniqueValues.length === 0) return count > 0 ? `${count} 个` : '-';
  if (uniqueValues.length <= maxVisible) return uniqueValues.join(' / ');
  return `${uniqueValues.slice(0, maxVisible).join(' / ')} 等 ${count} 个`;
}

function formatJobSymbols(job: DataSyncJobSummary): string {
  return formatListScope(job.symbols || [], job.totalSymbols, 4);
}

function formatJobTimeframes(job: DataSyncJobSummary): string {
  const labels = (job.timeframes || []).map(dataTimeframeLabel);
  return formatListScope(labels, job.totalTimeframes, 4);
}

function formatFullList(values: string[], mapper?: (value: string) => string): string {
  const uniqueValues = Array.from(new Set(values.filter(Boolean)));
  if (uniqueValues.length === 0) return '';
  return uniqueValues.map((value) => mapper ? mapper(value) : value).join(' / ');
}

function formatJobOperationTime(job: DataSyncJobSummary): string {
  return job.startedAt || job.createdAt || '-';
}

function getJobCompletedItems(job: DataSyncJobSummary): number {
  const processedItems = (job.completedItems || 0) + (job.errorItems || 0);
  if ((job.status === 'completed' || job.status === 'completed_with_errors') && (job.totalItems || 0) > 0) {
    return job.totalItems || 0;
  }
  return processedItems || job.completedItems || 0;
}

function getJobProgressPercent(job: DataSyncJobSummary): number {
  if (job.status === 'completed' || job.status === 'completed_with_errors') return 100;
  const processedPercent = (((job.completedItems || 0) + (job.errorItems || 0)) / (job.totalItems || 1)) * 100;
  if (processedPercent > 0) {
    return Math.max(job.progressPercent || 0, processedPercent);
  }
  if ((job.progressPercent || 0) > 0) {
    return job.progressPercent || 0;
  }
  if ((job.totalItems || 0) > 0) {
    return (((job.completedItems || 0) + (job.errorItems || 0)) / (job.totalItems || 1)) * 100;
  }
  return 0;
}

function getDataFreshness(lastTs: number | null): { label: string; color: string } {
  if (!lastTs) return { label: '无数据', color: 'text-gray-500' };
  const hoursSince = (Date.now() - lastTs) / 3600000;
  if (hoursSince < 2) return { label: '最新', color: 'text-green-400' };
  if (hoursSince < 24) return { label: `${Math.floor(hoursSince)}小时前`, color: 'text-yellow-400' };
  if (hoursSince < 168) return { label: `${Math.floor(hoursSince / 24)}天前`, color: 'text-orange-400' };
  return { label: `${Math.floor(hoursSince / 24)}天前`, color: 'text-red-400' };
}

// 计算覆盖率条
function getCoveragePercent(firstTs: number | null, lastTs: number | null, targetDays: number): number {
  if (!firstTs || !lastTs) return 0;
  const range = lastTs - firstTs;
  const target = targetDays * 86400000;
  return Math.min(100, Math.round((range / target) * 100));
}

// ============================================
// 数据管理页面
// ============================================

export default function DataManager() {
  const canMutateData = false;
  const { selectedExchange } = useStore();

  const [config, setConfig] = useState<DataSyncConfigResponse | null>(null);
  const [scheduleConfig, setScheduleConfig] = useState<DataSyncScheduleConfig | null>(null);
  const [tableStats, setTableStats] = useState<DataSyncTableStat[]>([]);
  const [qualityItems, setQualityItems] = useState<DataSyncQualityItem[]>([]);
  const [qualitySummary, setQualitySummary] = useState<DataSyncQualityResponse['summary'] | null>(null);
  const [qualityCheckedAt, setQualityCheckedAt] = useState<string | null>(null);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [qualityError, setQualityError] = useState('');
  const [syncMeta, setSyncMeta] = useState<DataSyncMeta[]>([]);
  const [totalRecords, setTotalRecords] = useState(0);
  const [totalPairs, setTotalPairs] = useState(0);
  const [marketStats, setMarketStats] = useState<Record<DataMarketType, DataSyncMarketStats>>(EMPTY_MARKET_STATS);
  const [isRunning, setIsRunning] = useState(false);
  const [syncCurrentJob, setSyncCurrentJob] = useState<DataSyncStatusResponse['currentJob']>(null);
  const [syncJobs, setSyncJobs] = useState<DataSyncJobSummary[]>([]);
  const [jobHistoryExpanded, setJobHistoryExpanded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [syncingMode, setSyncingMode] = useState<SyncDialogMode | null>(null);
  const [syncingTarget, setSyncingTarget] = useState<{ symbol: string; timeframe: string } | null>(null);
  const [targetSyncFeedback, setTargetSyncFeedback] = useState<Record<string, TargetSyncFeedback>>({});
  const [dataMarketType, setDataMarketType] = useState<DataMarketType>('spot');
  const [filterTf, setFilterTf] = useState<string>('');
  const [filterSymbol, setFilterSymbol] = useState('');
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);
  const [syncDialogMode, setSyncDialogMode] = useState<SyncDialogMode | null>(null);
  const [syncDialogError, setSyncDialogError] = useState('');
  const [showAddSymbolDialog, setShowAddSymbolDialog] = useState(false);
  const [addSymbolInput, setAddSymbolInput] = useState('');
  const [addSymbolSearch, setAddSymbolSearch] = useState('');
  const [addSymbolSelections, setAddSymbolSelections] = useState<string[]>([]);
  const [availableSymbols, setAvailableSymbols] = useState<string[]>([]);
  const [loadingAvailableSymbols, setLoadingAvailableSymbols] = useState(false);
  const [addSymbolError, setAddSymbolError] = useState('');
  const [addingSymbol, setAddingSymbol] = useState(false);
  const [syncAddedSymbolHistory, setSyncAddedSymbolHistory] = useState(true);
  const [addSymbolHistoryDays, setAddSymbolHistoryDays] = useState(SYNC_HISTORY_DAYS);
  const [removeSymbolTarget, setRemoveSymbolTarget] = useState<string | null>(null);
  const [showRemoveSymbolDialog, setShowRemoveSymbolDialog] = useState(false);
  const [removeSymbolSearch, setRemoveSymbolSearch] = useState('');
  const [removingSymbol, setRemovingSymbol] = useState(false);
  const [syncDialogStartDate, setSyncDialogStartDate] = useState(() => dateDaysAgo(SYNC_HISTORY_DAYS));
  const [syncDialogEndDate, setSyncDialogEndDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [syncDialogSymbols, setSyncDialogSymbols] = useState<string[]>([]);
  const [syncDialogTimeframes, setSyncDialogTimeframes] = useState<string[]>([]);
  const [showScheduleDialog, setShowScheduleDialog] = useState(false);
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduleIntervalMinutes, setScheduleIntervalMinutes] = useState('240');
  const [scheduleSymbols, setScheduleSymbols] = useState<string[]>([]);
  const [scheduleTimeframes, setScheduleTimeframes] = useState<string[]>([]);
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [scheduleDialogError, setScheduleDialogError] = useState('');
  const [okxNativeConfig, setOkxNativeConfig] = useState<OkxNativeSyncScheduleConfig | null>(null);
  const [okxNativeEnabled, setOkxNativeEnabled] = useState(false);
  const [okxRubikInterval, setOkxRubikInterval] = useState('1440');
  const [okxOiInterval, setOkxOiInterval] = useState('60');
  const [okxNativeBusy] = useState(false);
  const [okxNativeFeedback, setOkxNativeFeedback] = useState('');
  // 展开详情中的单个同步日期
  const [detailStartDate, setDetailStartDate] = useState(() => {
    const d = new Date(); d.setMonth(d.getMonth() - 6);
    return d.toISOString().slice(0, 10);
  });
  const [detailEndDate, setDetailEndDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [deleteTarget, setDeleteTarget] = useState<{
    symbol?: string;
    timeframe?: string;
    label: string;
  } | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const tableStatsLoadingRef = useRef(false);

  // ============================================
  // 数据加载
  // ============================================

  const loadTableStats = useCallback(async () => {
    if (tableStatsLoadingRef.current) return;
    tableStatsLoadingRef.current = true;
    try {
      const statsRes = await dataSyncApi.getTableStats();
      setTableStats(statsRes.tables || []);
      setTotalRecords(statsRes.totalRecords || 0);
      setTotalPairs(statsRes.totalPairs || 0);
      setMarketStats({
        swap: statsRes.marketStats?.swap || EMPTY_MARKET_STATS.swap,
        spot: statsRes.marketStats?.spot || EMPTY_MARKET_STATS.spot,
      });
    } catch (e) {
      console.error('加载数据统计失败', e);
    } finally {
      tableStatsLoadingRef.current = false;
    }
  }, []);

  const loadData = useCallback(async () => {
    void loadTableStats();
    try {
      const [configRes, statusRes] = await Promise.all([
        dataSyncApi.getConfig(),
        dataSyncApi.getStatus(),
      ]);
      setConfig(configRes);
      void dataSyncApi.getSchedule()
        .then((scheduleRes) => setScheduleConfig(scheduleRes))
        .catch((e) => console.error('加载定时同步配置失败', e));
      void okxNativeSyncApi.getSchedule()
        .then((res) => setOkxNativeConfig(res))
        .catch((e) => console.error('加载OKX原生数据同步配置失败', e));
      setIsRunning(statusRes.isRunning || false);
      setSyncCurrentJob(statusRes.currentJob || null);
      setSyncMeta(statusRes.details || []);

      // 如果不在运行中，停止轮询
      const running = statusRes.isRunning || false;
      if (!running && syncing) {
        setSyncing(false);
        setSyncingMode(null);
      }

      void dataSyncApi.getJobs(20)
        .then((jobsRes) => setSyncJobs(jobsRes.jobs || []))
        .catch((e) => {
          console.error('加载同步任务明细失败', e);
        });
    } catch (e) {
      console.error('加载数据管理信息失败', e);
    } finally {
      setLoading(false);
    }
  }, [loadTableStats, syncing]);

  useEffect(() => { loadData(); }, []);

  useEffect(() => {
    if (isRunning || syncing) {
      pollRef.current = setInterval(loadData, 4000);
    } else {
      if (pollRef.current) clearInterval(pollRef.current);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [isRunning, syncing, loadData]);

  const setTargetFeedback = (
    symbol: string,
    timeframe: string,
    message: string,
    type: SyncFeedbackType = 'info',
  ) => {
    const key = getSyncTargetKey(symbol, timeframe);
    setTargetSyncFeedback((prev) => ({ ...prev, [key]: { message, type } }));
    if (type !== 'error') {
      setTimeout(() => {
        setTargetSyncFeedback((prev) => {
          const current = prev[key];
          if (!current || current.message !== message || current.type !== type) return prev;
          const next = { ...prev };
          delete next[key];
          return next;
        });
      }, 8000);
    }
  };

  const getErrorMessage = (error: unknown): string => {
    if (typeof error === 'string') return error;
    if (error && typeof error === 'object') {
      const e = error as {
        message?: string;
        response?: { data?: { error?: { message?: string }; detail?: unknown } };
      };
      const envelopeMessage = e.response?.data?.error?.message;
      if (typeof envelopeMessage === 'string' && envelopeMessage.length > 0) return envelopeMessage;
      const detail = e.response?.data?.detail;
      if (typeof detail === 'string' && detail.length > 0) return detail;
      if (detail && typeof detail === 'object') return JSON.stringify(detail);
      if (typeof e.message === 'string' && e.message.length > 0) return e.message;
    }
    return '请求失败';
  };

  // ============================================
  // 操作
  // ============================================

  const openSyncDialog = (mode: SyncDialogMode) => {
    setSyncDialogMode(mode);
    setSyncDialogError('');
    setSyncDialogStartDate(dateDaysAgo(SYNC_HISTORY_DAYS));
    setSyncDialogEndDate(new Date().toISOString().slice(0, 10));
    setSyncDialogSymbols([]);
    setSyncDialogTimeframes([]);
  };

  const submitSyncDialog = async () => {
    if (!syncDialogMode) return;

    const mode = syncDialogMode;
    const syms = syncDialogSymbols.length > 0 ? syncDialogSymbols : undefined;
    const tfs = syncDialogTimeframes.length > 0 ? syncDialogTimeframes : undefined;
    const historyDays = SYNC_HISTORY_DAYS;
    const modeLabel = mode === 'daily'
      ? '增量更新'
      : mode === 'full'
        ? '全量同步'
        : '自定义同步';

    try {
      setSyncing(true);
      setSyncingMode(mode);
      setSyncDialogError('');
      const payload = {
        exchange: selectedExchange,
        symbols: syms,
        timeframes: tfs,
        startDate: syncDialogStartDate,
        endDate: syncDialogEndDate,
        historyDays,
      };
      if (mode === 'daily') {
        await dataSyncApi.dailyUpdate(selectedExchange, payload);
      } else {
        await dataSyncApi.startSync(payload);
      }
      setSyncDialogMode(null);
      setTimeout(loadData, 1000);
    } catch (e) {
      setSyncDialogError(`${modeLabel}启动失败: ${getErrorMessage(e)}`);
      setSyncing(false);
      setSyncingMode(null);
    }
  };

  const openScheduleDialog = () => {
    const schedule = scheduleConfig;
    setScheduleEnabled(Boolean(schedule?.enabled));
    setScheduleIntervalMinutes(String(schedule?.intervalMinutes || 240));
    setScheduleSymbols(schedule?.symbols || []);
    setScheduleTimeframes(schedule?.timeframes?.length
      ? schedule.timeframes.filter((timeframe) => SYNC_TIMEFRAME_ORDER.includes(timeframe))
      : [...SYNC_TIMEFRAME_ORDER]);
    const okxNative = okxNativeConfig;
    setOkxNativeEnabled(Boolean(okxNative?.enabled));
    setOkxRubikInterval(String(okxNative?.rubikIntervalMinutes || 1440));
    setOkxOiInterval(String(okxNative?.oiIntervalMinutes || 60));
    setOkxNativeFeedback('');
    setScheduleDialogError('');
    setShowScheduleDialog(true);
  };

  const submitScheduleDialog = async () => {
    const interval = Math.max(5, Math.min(24 * 60, Number(scheduleIntervalMinutes) || 240));
    const historyDays = SYNC_HISTORY_DAYS;
    try {
      setSavingSchedule(true);
      setScheduleDialogError('');
      const res = await dataSyncApi.updateSchedule({
        enabled: scheduleEnabled,
        intervalMinutes: interval,
        historyDays,
        symbols: scheduleSymbols,
        timeframes: scheduleTimeframes.length > 0 ? scheduleTimeframes : SYNC_TIMEFRAME_ORDER,
      });
      setScheduleConfig(res);
      setShowScheduleDialog(false);
    } catch (e) {
      setScheduleDialogError(`保存定时同步失败: ${getErrorMessage(e)}`);
    } finally {
      setSavingSchedule(false);
    }
  };

  const handleSyncOne = async (symbol: string, timeframe: string, startDate?: string, endDate?: string) => {
    try {
      setSyncingTarget({ symbol, timeframe });
      const dateHint = startDate ? ` (${startDate} ~ ${endDate || '至今'})` : '';
      setTargetFeedback(symbol, timeframe, `正在启动 ${dataTimeframeLabel(timeframe)}${dateHint} 同步任务...`, 'info');
      const res = await dataSyncApi.startSync({
        exchange: selectedExchange,
        symbols: [symbol],
        timeframes: [timeframe],
        historyDays: SYNC_HISTORY_DAYS,
        startDate: startDate,
        endDate: endDate,
      });
      const jobSuffix = res.jobId ? ` (任务 ${String(res.jobId).slice(0, 8)})` : '';
      setSyncing(true);
      setJobHistoryExpanded(true);
      setTargetFeedback(symbol, timeframe, `同步任务已启动${jobSuffix}，正在刷新任务明细`, 'success');
      void loadData();
      setTimeout(loadData, 1000);
    } catch (e) {
      setTargetFeedback(symbol, timeframe, `启动同步失败: ${getErrorMessage(e)}`, 'error');
      setSyncing(false);
    } finally {
      setSyncingTarget(null);
    }
  };

  const openAddSymbolDialog = async () => {
    setAddSymbolInput('');
    setAddSymbolSearch('');
    setAddSymbolSelections([]);
    setAddSymbolError('');
    setAvailableSymbols([]);
    setSyncAddedSymbolHistory(true);
    setAddSymbolHistoryDays(SYNC_HISTORY_DAYS);
    setShowAddSymbolDialog(true);
    setLoadingAvailableSymbols(true);
    try {
      const swapRes = await marketApi.getSymbols(selectedExchange, 'USDT', 'swap');
      const normalized = Array.from(new Set(
        [...(swapRes.symbols || [])]
          .map((symbol) => normalizeUsdtCandidate(symbol))
          .filter((symbol): symbol is string => typeof symbol === 'string' && isUsdtSwapSymbol(symbol))
      )).sort((a, b) => a.localeCompare(b));
      setAvailableSymbols(normalized);
    } catch (e) {
      setAddSymbolError(`加载交易对失败: ${getErrorMessage(e)}`);
    } finally {
      setLoadingAvailableSymbols(false);
    }
  };

  const handleAddSymbol = async () => {
    if (addingSymbol) return;

    const symbolsToAdd = addSymbolSelections.filter((symbol) => !configuredSymbolSet.has(symbol));
    if (symbolsToAdd.length === 0) {
      setAddSymbolError('请先从列表选择交易对');
      return;
    }
    if (syncAddedSymbolHistory && isBusy) {
      setAddSymbolError('当前已有同步任务在运行，请等待完成后再添加并同步，或取消勾选历史数据同步。');
      return;
    }

    try {
      setAddingSymbol(true);
      setAddSymbolError('');
      let defaultSymbols = config?.defaultSymbols || [];
      let firstAddedSymbol = symbolsToAdd[0];
      for (const symbol of symbolsToAdd) {
        const res = await dataSyncApi.addSymbol({ symbol });
        defaultSymbols = res.defaultSymbols;
        firstAddedSymbol = firstAddedSymbol || res.symbol;
      }
      setConfig((prev) => prev
        ? { ...prev, defaultSymbols }
        : {
            defaultSymbols,
            defaultTimeframes: SYNC_TIMEFRAME_ORDER,
            defaultHistoryDays: SYNC_HISTORY_DAYS,
          });
      const preferredSymbol = symbolsToAdd.find((symbol) => isUsdtSwapSymbol(symbol)) || firstAddedSymbol;
      setFilterSymbol(getCoinBase(preferredSymbol));
      setDataMarketType(isUsdtSwapSymbol(preferredSymbol) ? 'swap' : 'spot');
      setExpandedSymbol(preferredSymbol);
      if (syncAddedSymbolHistory) {
        await dataSyncApi.startSync({
          exchange: selectedExchange,
          symbols: symbolsToAdd,
          timeframes: SYNC_TIMEFRAME_ORDER,
          historyDays: addSymbolHistoryDays,
        });
        setSyncing(true);
        setJobHistoryExpanded(true);
      }
      setShowAddSymbolDialog(false);
      void loadData();
    } catch (e) {
      setAddSymbolError(getErrorMessage(e));
    } finally {
      setAddingSymbol(false);
    }
  };

  const handleRemoveSymbol = async () => {
    if (!removeSymbolTarget || removingSymbol) return;
    const symbol = removeSymbolTarget;

    try {
      setRemovingSymbol(true);
      const res = await dataSyncApi.removeSymbol({ symbol });
      setConfig((prev) => prev
        ? { ...prev, defaultSymbols: res.defaultSymbols }
        : {
            defaultSymbols: res.defaultSymbols,
            defaultTimeframes: SYNC_TIMEFRAME_ORDER,
            defaultHistoryDays: SYNC_HISTORY_DAYS,
          });
      setScheduleSymbols((prev) => prev.filter((item) => item !== symbol));
      setSyncDialogSymbols((prev) => prev.filter((item) => item !== symbol));
      setExpandedSymbol((current) => current === symbol ? null : current);
      setRemoveSymbolTarget(null);
      void loadData();
    } catch (e) {
      console.error(`移除交易对失败: ${getErrorMessage(e)}`);
    } finally {
      setRemovingSymbol(false);
    }
  };

  const runDeleteData = async () => {
    if (!deleteTarget) return;
    const { symbol, timeframe } = deleteTarget;
    setDeleteTarget(null);
    try {
      const res = await dataSyncApi.deleteData({ exchange: selectedExchange, symbol, timeframe });
      console.info(res.message || '删除完成');
      await loadData();
    } catch (e) {
      console.error(`删除失败: ${getErrorMessage(e)}`);
    }
  };

  const requestDeleteData = (symbol?: string, timeframe?: string) => {
    const target = symbol
      ? `${getCoinBase(symbol)}${timeframe ? ` ${dataTimeframeLabel(timeframe)}` : ' 全部周期'}`
      : '所有数据';
    setDeleteTarget({ symbol, timeframe, label: target });
  };

  // ============================================
  // 数据聚合
  // ============================================

  const discoveredTimeframes = sortTimeframes(dedupeSymbols([
    ...(config?.defaultTimeframes || []),
    ...tableStats.map((s) => s.timeframe),
    ...syncMeta.map((m) => m.timeframe),
    ...(syncCurrentJob?.progress || []).map((row) => row.timeframe),
  ]));
  const allTimeframes = discoveredTimeframes.length > 0 ? discoveredTimeframes : TIMEFRAME_ORDER;
  const configuredSymbols: string[] = config?.defaultSymbols || [];
  const syncedSymbols = dedupeSymbols([
    ...tableStats
      .filter((s) => s.exchange === selectedExchange && s.recordCount > 0)
      .map((s) => s.symbol),
    ...syncMeta
      .filter((m) => m.exchange === selectedExchange && m.dataType === 'kline' && (m.totalRecords > 0 || m.status === 'syncing'))
      .map((m) => m.symbol),
    ...(syncCurrentJob?.progress || [])
      .filter((row) => (row.exchange || selectedExchange) === selectedExchange)
      .map((row) => row.symbol),
  ]);
  const allSymbols: string[] = dedupeSymbols([...configuredSymbols, ...syncedSymbols]);
  const displayedMarketSymbolCounts = splitMarketSymbolCounts(allSymbols);
  const configuredMarketSymbolCounts = splitMarketSymbolCounts(configuredSymbols);

  const statMap = new Map<string, DataSyncTableStat>();
  for (const s of tableStats) {
    if (s.exchange !== selectedExchange) continue;
    const key = `${s.symbol}_${s.timeframe}`;
    const existing = statMap.get(key);
    if (!existing || s.tableName !== 'kline_history') {
      statMap.set(key, s);
    }
  }

  const metaMap = new Map<string, DataSyncMeta>();
  for (const m of syncMeta) {
    if (m.exchange !== selectedExchange) continue;
    metaMap.set(`${m.symbol}_${m.timeframe}`, m);
  }

  const qualityMap = new Map<string, DataSyncQualityItem>();
  for (const item of qualityItems) {
    if (item.exchange !== selectedExchange) continue;
    qualityMap.set(`${item.symbol}_${item.timeframe}`, item);
  }

  const visibleMarketSymbols = allSymbols.filter((s) =>
    dataMarketType === 'swap' ? isUsdtSwapSymbol(s) : !isUsdtSwapSymbol(s)
  );
  const configuredVisibleMarketSymbols = configuredSymbols.filter((s) =>
    dataMarketType === 'swap' ? isUsdtSwapSymbol(s) : !isUsdtSwapSymbol(s)
  );
  const filteredSymbols = visibleMarketSymbols.filter((s) =>
    filterSymbol ? s.toLowerCase().includes(filterSymbol.toLowerCase()) : true
  );
  const removeSymbolSearchText = removeSymbolSearch.trim().toLowerCase();
  const removeSymbolCandidates = configuredVisibleMarketSymbols.filter((symbol) => {
    if (!removeSymbolSearchText) return true;
    return symbol.toLowerCase().includes(removeSymbolSearchText)
      || getCoinBase(symbol).toLowerCase().includes(removeSymbolSearchText)
      || formatOkxInstrumentId(symbol).toLowerCase().includes(removeSymbolSearchText);
  });
  const configuredSymbolSet = new Set(configuredSymbols);
  const addSymbolSearchText = addSymbolSearch.trim().toLowerCase();
  const addSymbolCandidates = availableSymbols.filter((symbol) => {
    if (!addSymbolSearchText) return true;
    return symbol.toLowerCase().includes(addSymbolSearchText)
      || getCoinBase(symbol).toLowerCase().includes(addSymbolSearchText)
      || formatOkxInstrumentId(symbol).toLowerCase().includes(addSymbolSearchText);
  });
  const addSymbolGroups = buildAddSymbolGroups(addSymbolCandidates);
  const toggleAddSymbolSelection = (symbol: string) => {
    if (configuredSymbolSet.has(symbol)) return;
    setAddSymbolSelections((prev) =>
      prev.includes(symbol) ? prev.filter((item) => item !== symbol) : [...prev, symbol]
    );
  };
  const selectAddSymbolGroup = (group: AddSymbolGroup) => {
    const choices = [group.swapSymbol]
      .filter((symbol): symbol is string => typeof symbol === 'string' && !configuredSymbolSet.has(symbol));
    setAddSymbolInput(group.base);
    setAddSymbolSelections(choices);
    setAddSymbolError('');
  };

  // 统计每个 symbol 的总数据量
  const symbolTotalRecords = (symbol: string): number => {
    let total = 0;
    for (const tf of allTimeframes) {
      const stat = statMap.get(`${symbol}_${tf}`);
      if (stat) total += stat.recordCount;
    }
    return total;
  };

  // 每个 symbol 有数据的周期数
  const symbolFilledTf = (symbol: string): number => {
    let count = 0;
    for (const tf of allTimeframes) {
      const stat = statMap.get(`${symbol}_${tf}`);
      if (stat && stat.recordCount > 0) count++;
    }
    return count;
  };

  const isSyncingTarget = (symbol: string, timeframe: string) =>
    syncingTarget?.symbol === symbol && syncingTarget?.timeframe === timeframe;

  const isBusy = isRunning || syncing || syncingTarget !== null;
  const runQualityCheck = async () => {
    const symbols = filteredSymbols;
    const timeframes = filterTf ? [filterTf] : allTimeframes;
    if (symbols.length === 0 || timeframes.length === 0) {
      setQualityError('当前列表没有可检测的交易对');
      setQualitySummary(null);
      setQualityItems([]);
      setQualityCheckedAt(null);
      return;
    }

    try {
      setQualityLoading(true);
      setQualityError('');
      const maxItems = 500;
      const maxSymbols = Math.max(1, Math.floor(maxItems / Math.max(1, timeframes.length)));
      const scopedSymbols = symbols.length * timeframes.length > maxItems
        ? symbols.slice(0, maxSymbols)
        : symbols;
      const res = await dataSyncApi.getQuality({
        exchange: selectedExchange,
        symbols: scopedSymbols,
        timeframes,
        maxItems,
      });
      setQualityItems(res.items || []);
      setQualitySummary({
        ...res.summary,
        truncated: Boolean(res.summary?.truncated || scopedSymbols.length < symbols.length),
      });
      setQualityCheckedAt(res.checkedAt || null);
    } catch (e) {
      setQualityError(`检测失败: ${getErrorMessage(e)}`);
    } finally {
      setQualityLoading(false);
    }
  };
  const qualityRiskCount = qualitySummary?.error || 0;
  const qualityMissingCount = qualitySummary?.missing || 0;
  const qualityCheckedCount = qualitySummary?.checked || 0;
  const qualityStatusLabel = qualityError
    ? '检测失败'
    : qualityLoading
      ? '检测中...'
      : !qualitySummary
        ? '未检测'
        : qualityRiskCount > 0
          ? `${qualityRiskCount} 项风险`
          : '通过';
  const qualityStatusTone = qualityError || qualityRiskCount > 0
    ? 'text-red-400'
    : qualitySummary
      ? 'text-emerald-400'
      : 'text-gray-400';
  const qualitySummaryHint = qualityError || (
    qualitySummary
      ? `${qualityCheckedCount} 项 · 缺失 ${qualityMissingCount} · ${qualitySummary.truncated ? '已截断' : formatDateTime(qualityCheckedAt)}`
      : '手动扫描开盘断层和 OHLC 异常'
  );
  const currentJob = syncCurrentJob;
  const progressRows = currentJob ? (currentJob.progress || []) : [];
  const currentJobSymbols = Array.from(new Set(progressRows.map((row) => row.symbol))).filter(Boolean);
  const currentJobTimeframes = Array.from(new Set(progressRows.map((row) => row.timeframe))).filter(Boolean);
  const currentJobTotalItems = currentJob?.totalItems || progressRows.length;
  const currentJobCompletedItems = currentJob?.completedItems ?? progressRows.filter((row) => row.status === 'completed').length;
  const currentJobRunningItems = progressRows.filter((row) => row.status === 'running' || row.status === 'syncing').length;
  const currentJobErrorItems = currentJob?.errorItems ?? progressRows.filter((row) => row.status === 'error' || row.error).length;
  const currentJobProcessedItems = currentJob?.processedItems ?? currentJobCompletedItems + currentJobErrorItems;
  const currentJobFallback: DataSyncJobSummary | null = currentJob?.jobId ? {
    jobId: currentJob.jobId,
    exchange: currentJob.exchange || selectedExchange,
    status: currentJob.status || (isRunning ? 'running' : 'completed'),
    symbols: currentJobSymbols,
    timeframes: currentJobTimeframes,
    historyDays: SYNC_HISTORY_DAYS,
    totalSymbols: currentJobSymbols.length,
    totalTimeframes: currentJobTimeframes.length,
    totalItems: currentJobTotalItems,
    completedItems: currentJobCompletedItems,
    runningItems: currentJobRunningItems,
    pendingItems: Math.max(0, currentJobTotalItems - currentJobCompletedItems - currentJobRunningItems - currentJobErrorItems),
    errorItems: currentJobErrorItems,
    processedItems: currentJobProcessedItems,
    progressPercent: currentJobTotalItems > 0 ? (currentJobProcessedItems / currentJobTotalItems) * 100 : 0,
    totalFetched: currentJob.totalFetched || progressRows.reduce((sum, row) => sum + (row.totalFetched || 0), 0),
    totalInserted: currentJob.totalInserted || progressRows.reduce((sum, row) => sum + (row.totalInserted || 0), 0),
    errorCount: currentJob.errors || currentJobErrorItems,
    errorMessage: null,
    createdAt: currentJob.startedAt || null,
    startedAt: currentJob.startedAt || null,
    completedAt: currentJob.completedAt || null,
    elapsedSeconds: currentJob.elapsedSeconds,
  } : null;
  const filteredSyncJobs = syncJobs.filter((job) => !job.exchange || job.exchange === selectedExchange);
  const currentJobAlreadyInHistory = currentJobFallback
    ? filteredSyncJobs.some((job) => job.jobId === currentJobFallback.jobId)
    : false;
  const syncJobRows = currentJobFallback && !currentJobAlreadyInHistory
    ? [currentJobFallback, ...filteredSyncJobs]
    : filteredSyncJobs;
  const dailyButtonBusy = syncingMode === 'daily';
  const customButtonBusy = syncingMode === 'custom';
  const fullButtonBusy = syncingMode === 'full';
  const schedulePulseOn = Boolean(scheduleConfig?.enabled);
  const scheduleSummary = schedulePulseOn
    ? `${scheduleConfig?.intervalMinutes || 240}分钟 · ${(scheduleConfig?.timeframes || []).map(dataTimeframeLabel).join('/') || '全部周期'}`
    : '未启用';
  const syncDialogTitle = syncDialogMode === 'daily'
    ? '增量更新'
    : syncDialogMode === 'full'
      ? '全量同步'
      : '自定义同步';
  const syncDialogDescription = syncDialogMode === 'daily'
    ? '选择日期范围、币种和周期，按增量口径补齐近期数据'
    : syncDialogMode === 'full'
      ? '选择日期范围、币种和周期，重新补齐整段历史数据'
      : '选择日期范围、币种和周期，精确补充历史数据';

  const handleSyncMissingTimeframes = async (symbol: string) => {
    const missingTimeframes = SYNC_TIMEFRAME_ORDER.filter((tf: string) => {
      const stat = statMap.get(`${symbol}_${tf}`);
      return !stat || stat.recordCount <= 0;
    });

    if (missingTimeframes.length === 0) {
      return;
    }

    try {
      setSyncing(true);
      await dataSyncApi.startSync({
        exchange: selectedExchange,
        symbols: [symbol],
        timeframes: missingTimeframes,
        historyDays: SYNC_HISTORY_DAYS,
      });
      setTimeout(loadData, 2000);
    } catch (e) {
      console.error(`同步缺失周期失败: ${getErrorMessage(e)}`);
      setSyncing(false);
    }
  };

  const renderOperationRow = (job: DataSyncJobSummary) => {
    const active = job.status === 'running' || job.status === 'queued';
    const symbolTitle = formatFullList(job.symbols || []);
    const timeframeTitle = formatFullList(job.timeframes || [], dataTimeframeLabel);
    const notice = job.errorMessage || (job.errorItems > 0 ? `失败 ${job.errorItems} 项` : '-');
    const completedItems = getJobCompletedItems(job);
    const progressPercent = getJobProgressPercent(job);

    return (
      <tr key={job.jobId} className="text-gray-400 hover:bg-white/[0.02] transition">
        <td className="px-4 py-2 align-top whitespace-nowrap">
          <div className="font-medium text-white/80">{formatJobOperationTime(job)}</div>
          <div className="mt-0.5 text-[11px] text-gray-500">任务 {job.jobId.slice(0, 8)}</div>
        </td>
        <td className="px-4 py-2 align-top whitespace-nowrap">
          <span className={`inline-flex min-w-[72px] items-center justify-center gap-1 whitespace-nowrap rounded-md px-2.5 py-1 text-[11px] font-medium leading-none border ${syncStatusTone(job.status)}`}>
            {active && <Loader2 className="w-3 h-3 animate-spin" />}
            {syncStatusLabel(job.status)}
          </span>
        </td>
        <td className="px-4 py-2 align-top max-w-[260px]">
          <div className="truncate text-white/75" title={symbolTitle}>
            {formatJobSymbols(job)}
          </div>
          <div className="mt-0.5 text-[11px] text-gray-500">
            {job.totalSymbols || (job.symbols || []).length || 0} 个标的
          </div>
        </td>
        <td className="px-4 py-2 align-top max-w-[200px]">
          <div className="truncate" title={timeframeTitle}>
            {formatJobTimeframes(job)}
          </div>
          <div className="mt-0.5 text-[11px] text-gray-500">
            {job.totalTimeframes || (job.timeframes || []).length || 0} 个周期
          </div>
        </td>
        <td className="px-4 py-2 align-top whitespace-nowrap">{formatJobRange(job)}</td>
        <td className="px-4 py-2 align-top min-w-40">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-gray-500">{completedItems}/{job.totalItems || 0} 项</span>
            <span className="text-white/70">{Math.round(progressPercent)}%</span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-white/5 overflow-hidden">
            <div
              className={`h-full rounded-full ${job.status === 'error' ? 'bg-red-400' : job.status === 'completed_with_errors' ? 'bg-amber-400' : 'bg-emerald-400'}`}
              style={{ width: `${Math.min(100, Math.max(0, progressPercent))}%` }}
            />
          </div>
        </td>
        <td className="px-4 py-2 align-top text-right whitespace-nowrap">
          <span className="text-white/70">{formatCount(job.totalFetched || 0)}</span>
          <span className="mx-1 text-gray-600">/</span>
          <span className="text-white/70">{formatCount(job.totalInserted || 0)}</span>
        </td>
        <td className="px-4 py-2 align-top whitespace-nowrap">{job.completedAt || '-'}</td>
        <td className="px-4 py-2 align-top whitespace-nowrap">{formatDuration(job.elapsedSeconds)}</td>
        <td className="px-4 py-2 align-top max-w-xs truncate" title={notice === '-' ? '' : notice}>
          {notice}
        </td>
      </tr>
    );
  };

  // ============================================
  // 渲染
  // ============================================

  return (
    <div className="p-6 h-full min-h-0 overflow-y-auto flex flex-col gap-5">
      {/* ========== 顶部标题栏 ========== */}
      <div className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center shadow-lg shadow-blue-500/20">
            <Database className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">数据管理中心</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              {selectedExchange.toUpperCase()} · {allSymbols.length} 个交易对 · {allTimeframes.length} 个周期
            </p>
            {loading && (
              <div className="mt-1 flex items-center gap-1.5 text-xs text-blue-300">
                <Loader2 className="w-3 h-3 animate-spin" />
                加载数据管理...
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="dataHelpTooltip group/data-help relative">
            <button
              type="button"
              aria-label="查看数据同步说明"
              className="h-9 w-9 rounded-lg bg-gray-800 border border-crypto-border text-blue-300 hover:text-blue-200 hover:bg-gray-700 transition flex items-center justify-center"
            >
              <Info className="w-4 h-4" />
            </button>
            <div className="pointer-events-none absolute right-0 top-11 z-30 w-[560px] max-w-[calc(100vw-3rem)] rounded-xl border border-blue-500/25 bg-[#111827] p-4 text-xs leading-relaxed text-gray-400 shadow-2xl shadow-black/40 opacity-0 translate-y-1 transition-all duration-150 group-hover/data-help:opacity-100 group-hover/data-help:translate-y-0 group-focus-within/data-help:opacity-100 group-focus-within/data-help:translate-y-0">
              <div className="space-y-1.5">
                <p><strong className="text-gray-200">全量同步</strong> — 按 A 股交易日历拉取全市场日线，完成质量检查后落入 PostgreSQL 分区</p>
                <p><strong className="text-gray-200">自定义同步</strong> — 选择日期范围、证券代码和数据集，<strong className="text-gray-200">精确指定</strong>研究输入</p>
                <p><strong className="text-gray-200">增量更新</strong> — 从上次交易日水位继续拉取，不在页面 GET 时隐式调用 Provider</p>
                <p><strong className="text-gray-200">展开详情 → 按日期</strong> — 在每个交易对的展开面板中，通过顶部日期选择器指定范围后，点击"按日期"按钮同步</p>
                <p><strong className="text-gray-200">数据覆盖率</strong> — 绿色({'>'}80%) = 完整 / 黄色(50-80%) = 部分 / 红色({'<'}50%) = 缺失较多</p>
                <p><strong className="text-gray-200">分区存储</strong> — 日线、参考数据、因子和快照独立落库，封存后不可变</p>
              </div>
            </div>
          </div>
          <button onClick={loadData}
            className="h-9 px-3 rounded-lg bg-gray-800 border border-crypto-border text-gray-400 hover:text-white hover:bg-gray-700 transition text-sm flex items-center gap-1.5">
            <RefreshCw className="w-3.5 h-3.5" /> 刷新
          </button>
          <button
            onClick={openScheduleDialog}
            disabled={!canMutateData}
            title={`定时同步: ${scheduleSummary}`}
            className={`h-9 px-4 rounded-lg border text-sm font-medium flex items-center gap-1.5 transition-all ${
              schedulePulseOn
                ? 'bg-emerald-500/10 border-emerald-500/35 text-emerald-200 hover:bg-emerald-500/15'
                : 'bg-gray-800 border-crypto-border text-gray-300 hover:text-white hover:bg-gray-700'
            }`}
          >
            <span className="relative flex h-2.5 w-2.5 items-center justify-center">
              {schedulePulseOn && <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75 animate-ping" />}
              <span className={`relative inline-flex h-2 w-2 rounded-full ${schedulePulseOn ? 'bg-emerald-300' : 'bg-gray-500'}`} />
            </span>
            <Clock className="w-3.5 h-3.5" />
            定时同步
          </button>
          <button onClick={() => openSyncDialog('daily')} disabled={!canMutateData || isBusy}
            className="h-9 px-4 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed transition-all">
            {dailyButtonBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
            增量更新
          </button>
          <button onClick={() => openSyncDialog('custom')} disabled={!canMutateData || isBusy}
            className="h-9 px-4 rounded-lg text-sm font-medium flex items-center gap-1.5 transition-all border bg-purple-600/80 hover:bg-purple-500 text-white border-purple-400/30 shadow-sm shadow-purple-500/10 disabled:opacity-50 disabled:cursor-not-allowed">
            {customButtonBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Calendar className="w-3.5 h-3.5" />}
            自定义同步
          </button>
          <button onClick={() => openSyncDialog('full')} disabled={!canMutateData || isBusy}
            className="h-9 px-4 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed transition-all">
            {fullButtonBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            全量同步
          </button>
        </div>
      </div>

      {/* ========== 统计概览 ========== */}
      <div className="grid grid-cols-6 gap-3 shrink-0">
        {/* 总记录数 */}
        <div className="bg-crypto-card border border-crypto-border rounded-xl p-4 relative overflow-hidden">
          <div className="absolute top-3 right-3 opacity-5"><HardDrive className="w-10 h-10" /></div>
          <div className="text-xs text-gray-500 mb-1">总记录数</div>
          <div className="text-2xl font-bold text-white">{formatCount(totalRecords)}</div>
          <DataMarketSplit
            swap={marketStats.swap.totalRecords}
            spot={marketStats.spot.totalRecords}
          />
        </div>
        {/* 数据对数 */}
        <div className="bg-crypto-card border border-crypto-border rounded-xl p-4 relative overflow-hidden">
          <div className="absolute top-3 right-3 opacity-5"><BarChart3 className="w-10 h-10" /></div>
          <div className="text-xs text-gray-500 mb-1">数据对数</div>
          <div className="text-2xl font-bold text-white">{totalPairs}</div>
          <DataMarketSplit
            swap={marketStats.swap.totalPairs}
            spot={marketStats.spot.totalPairs}
            formatter={(value) => value.toLocaleString()}
          />
        </div>
        {/* 同步状态 */}
        <div className="bg-crypto-card border border-crypto-border rounded-xl p-4 relative overflow-hidden">
          <div className="absolute top-3 right-3 opacity-5"><Zap className="w-10 h-10" /></div>
          <div className="text-xs text-gray-500 mb-1">同步状态</div>
          <div className={`text-lg font-bold ${isRunning || syncing ? 'text-yellow-400' : 'text-emerald-400'}`}>
            {isRunning || syncing ? '同步中...' : '空闲'}
          </div>
        </div>
        {/* 数据质量 */}
        <div className="bg-crypto-card border border-crypto-border rounded-xl p-4 relative overflow-hidden">
          <div className="absolute top-3 right-3 opacity-5"><AlertCircle className="w-10 h-10" /></div>
          <div className="text-xs text-gray-500 mb-1">数据质量</div>
          <div className={`text-lg font-bold ${qualityStatusTone}`}>{qualityStatusLabel}</div>
          <div className="mt-1 min-h-[1rem] truncate text-[10px] text-gray-500" title={qualitySummaryHint}>
            {qualitySummaryHint}
          </div>
          <button
            type="button"
            onClick={() => void runQualityCheck()}
            disabled={qualityLoading}
            className="mt-2 h-7 w-full rounded-lg border border-amber-500/25 bg-amber-500/10 text-[11px] font-medium text-amber-200 hover:bg-amber-500/20 transition disabled:cursor-not-allowed disabled:opacity-50 flex items-center justify-center gap-1.5"
          >
            {qualityLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle className="w-3 h-3" />}
            检测当前列表
          </button>
        </div>
        {/* 交易对 */}
        <div className="bg-crypto-card border border-crypto-border rounded-xl p-4 relative overflow-hidden">
          <div className="absolute top-3 right-3 opacity-5"><TrendingUp className="w-10 h-10" /></div>
          <div className="text-xs text-gray-500 mb-1">交易对</div>
          <div className="text-2xl font-bold text-white">{allSymbols.length}</div>
          <DataMarketSplit
            swap={displayedMarketSymbolCounts.swap}
            spot={displayedMarketSymbolCounts.spot}
            formatter={(value) => value.toLocaleString()}
          />
          <div className="mt-2 text-[10px] text-gray-500">
            后续同步名单 {configuredSymbols.length} 个 · 期货预留 {configuredMarketSymbolCounts.swap} / A股 {configuredMarketSymbolCounts.spot}
          </div>
        </div>
        {/* 时间周期 */}
        <div className="bg-crypto-card border border-crypto-border rounded-xl p-4 relative overflow-hidden">
          <div className="absolute top-3 right-3 opacity-5"><Calendar className="w-10 h-10" /></div>
          <div className="text-xs text-gray-500 mb-1">时间周期</div>
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            {allTimeframes.map((tf: string) => (
              <span key={tf} className={`text-[10px] px-1.5 py-0.5 rounded border ${TIMEFRAME_BADGE[tf] || 'bg-gray-500/20 text-gray-300 border-gray-500/30'}`}>
                {dataTimeframeLabel(tf)}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="bg-crypto-card border border-crypto-border rounded-xl overflow-hidden shrink-0">
        <div className={`flex items-stretch ${jobHistoryExpanded ? 'border-b border-crypto-border' : ''}`}>
          <button
            type="button"
            onClick={() => setJobHistoryExpanded((expanded) => !expanded)}
            className="flex-1 min-w-0 flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-white/5 transition-colors"
            aria-expanded={jobHistoryExpanded}
            aria-controls="sync-job-history-table"
          >
            <div className="flex items-center gap-2 min-w-0">
              <ListChecks className="w-4 h-4 text-emerald-400 shrink-0" />
              <span className="text-sm font-semibold text-white">同步任务明细</span>
              <span className="truncate text-xs text-gray-500">
                当前任务和最近历史任务 · {syncJobRows.length} 条
              </span>
            </div>
            <span className="h-7 px-2.5 rounded-md bg-gray-800 border border-crypto-border text-[11px] text-gray-300 flex items-center gap-1 shrink-0">
              <ChevronDown className={`w-3 h-3 transition-transform ${jobHistoryExpanded ? 'rotate-180' : ''}`} />
              {jobHistoryExpanded ? '收起' : '展开'}
            </span>
          </button>
          <button
            onClick={loadData}
            className="shrink-0 px-4 py-3 text-xs text-gray-500 hover:text-white hover:bg-white/5 border-l border-crypto-border transition-colors flex items-center gap-1"
          >
            <RefreshCw className="w-3 h-3" /> 刷新
          </button>
        </div>
        {jobHistoryExpanded && (
          <div id="sync-job-history-table" className="max-h-80 overflow-auto">
            <table className="w-full min-w-[1180px] text-xs">
              <thead className="bg-gray-900/50 text-gray-500">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">操作时间</th>
                  <th className="px-4 py-2 text-left font-medium">状态</th>
                  <th className="px-4 py-2 text-left font-medium">同步标的</th>
                  <th className="px-4 py-2 text-left font-medium">时间周期</th>
                  <th className="px-4 py-2 text-left font-medium">数据时间段</th>
                  <th className="px-4 py-2 text-left font-medium">进度</th>
                  <th className="px-4 py-2 text-right font-medium">拉取 / 新增</th>
                  <th className="px-4 py-2 text-left font-medium">完成时间</th>
                  <th className="px-4 py-2 text-left font-medium">执行时间</th>
                  <th className="px-4 py-2 text-left font-medium">提示</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-crypto-border">
                {syncJobRows.length === 0 ? (
                  <tr>
                    <td colSpan={10} className="px-4 py-5 text-center text-gray-500">
                      暂无同步任务记录
                    </td>
                  </tr>
                ) : syncJobRows.map(renderOperationRow)}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <section
        className="rounded-2xl border border-crypto-border bg-crypto-card/45 p-3 shadow-inner shadow-black/20 shrink-0"
        aria-label="交易对维护面板"
      >
        {/* ========== 过滤和搜索 ========== */}
        <div className="flex items-center gap-3 shrink-0">
          <div className="relative flex-shrink-0">
            <Search className="w-4 h-4 text-gray-500 absolute left-3 top-1/2 -translate-y-1/2" />
            <input type="text" placeholder="搜索币种..."
              value={filterSymbol} onChange={(e) => setFilterSymbol(e.target.value)}
              className="h-9 bg-gray-800 border border-crypto-border rounded-lg pl-9 pr-3 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500 transition w-44" />
          </div>
          <div
            className="data-market-type-toggle flex overflow-hidden rounded-lg border border-crypto-border bg-crypto-card"
            data-active-market={dataMarketType}
            aria-label="切换数据市场类型"
          >
            {([
              { value: 'swap', label: '期货预留' },
              { value: 'spot', label: 'A股' },
            ] as const).map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={dataMarketType === option.value}
                onClick={() => {
                  setDataMarketType(option.value);
                  setExpandedSymbol(null);
                }}
                className={`h-9 px-3 text-xs font-semibold transition-colors ${
                  dataMarketType === option.value
                    ? SELECTED_SEGMENT_CLASS
                    : 'text-gray-500 hover:bg-gray-800/60 hover:text-gray-300'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1 bg-crypto-card rounded-lg p-1 border border-crypto-border">
            <button onClick={() => setFilterTf('')} aria-pressed={!filterTf}
              className={`px-3 py-1 rounded-md text-xs font-medium transition ${!filterTf ? SELECTED_SEGMENT_CLASS : 'text-gray-400 hover:text-white'}`}>
              全部
            </button>
            {allTimeframes.map((tf: string) => (
              <button key={tf} onClick={() => setFilterTf(filterTf === tf ? '' : tf)} aria-pressed={filterTf === tf}
                className={`px-3 py-1 rounded-md text-xs font-medium transition ${filterTf === tf ? SELECTED_SEGMENT_CLASS : 'text-gray-400 hover:text-white'}`}>
                {dataTimeframeLabel(tf)}
              </button>
            ))}
          </div>
          <div className="flex-1" />
          <button onClick={() => void openAddSymbolDialog()}
            className="h-9 px-3 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-xs font-medium flex items-center gap-1.5 transition">
            <Plus className="w-3.5 h-3.5" /> 增加交易对
          </button>
          <button
            type="button"
            onClick={() => {
              setRemoveSymbolSearch('');
              setShowRemoveSymbolDialog(true);
            }}
            disabled={configuredVisibleMarketSymbols.length === 0}
            className="h-9 px-3 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/30 text-xs font-medium flex items-center gap-1.5 transition disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Trash2 className="w-3.5 h-3.5" /> 删除交易对
          </button>
          <span className="text-xs text-gray-500">当前显示 {dataMarketLabel(dataMarketType)} · 共 {filteredSymbols.length} 个交易对</span>
        </div>

        {/* ========== 交易对卡片列表 ========== */}
        <div
          className="mt-3 rounded-xl border border-crypto-border bg-crypto-bg/35 overflow-hidden min-h-[320px] max-h-[52vh] flex flex-col"
          aria-label="交易对数据列表"
        >
          <div className="min-h-0 flex-1 overflow-y-auto p-2.5 pr-3 space-y-2.5">
        {filteredSymbols.length === 0 ? (
          <div className="h-full min-h-64 flex items-center justify-center text-sm text-gray-500">
            暂无匹配的交易对
          </div>
        ) : filteredSymbols.map((symbol) => {
          const coin = getCoinBase(symbol);
          const swapSymbol = isUsdtSwapSymbol(symbol);
          const total = symbolTotalRecords(symbol);
          const filled = symbolFilledTf(symbol);
          const isExpanded = expandedSymbol === symbol;
          const displayTfs = filterTf ? allTimeframes.filter((t: string) => t === filterTf) : allTimeframes;
          const configuredSymbol = configuredSymbolSet.has(symbol);

          return (
            <div key={symbol} className="bg-crypto-card border border-crypto-border rounded-xl overflow-hidden hover:border-gray-600 transition-all">
              {/* 卡片头部 */}
              <div className="flex items-center px-5 py-3.5 cursor-pointer select-none gap-5"
                   onClick={() => setExpandedSymbol(isExpanded ? null : symbol)}>
                {/* 证券标识 */}
                <div className="flex items-center gap-3 w-32 flex-shrink-0">
                  <SymbolIcon symbol={symbol} base={coin} size="md" shape="rounded" />
                  <div>
                    <div className="text-sm font-semibold text-white">{symbol}</div>
                    <div className="text-[10px] text-gray-500">{swapSymbol ? '期货预留' : 'A股日线'}</div>
                  </div>
                </div>

                {/* 周期数据条 — 单行 flex，避免 6 个周期在 grid-cols-5 下折成两行 */}
                <div className="flex flex-nowrap gap-2.5 flex-1 min-w-0 overflow-x-auto">
                  {displayTfs.map((tf: string) => {
                    const stat = statMap.get(`${symbol}_${tf}`);
                    const count = stat?.recordCount || 0;
                    const hasData = count > 0;
                    const freshness = getDataFreshness(stat?.lastTimestamp || null);
                    const coverage = getCoveragePercent(stat?.firstTimestamp || null, stat?.lastTimestamp || null, 365);
                    const qualityItem = qualityMap.get(`${symbol}_${tf}`);
                    const hasQualityRisk = qualityItem?.status === 'error';

                    return (
                      <div
                        key={tf}
                        className={`flex-1 basis-0 min-w-0 rounded-lg border px-2 sm:px-3 py-2 bg-gradient-to-br ${
                          hasData ? TIMEFRAME_COLORS[tf] || 'from-gray-500/10 border-gray-500/20' : 'from-transparent border-crypto-border'
                        } transition-all`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className={`text-[10px] font-medium ${hasData ? 'text-white/70' : 'text-gray-600'}`}>
                            {dataTimeframeLabel(tf)}
                          </span>
                          {hasData && (
                            <span className="flex items-center gap-1">
                              {hasQualityRisk && (
                                <AlertCircle
                                  className="h-3 w-3 text-red-300"
                                  aria-label="质量风险"
                                />
                              )}
                              <span className={`text-[10px] ${freshness.color}`}>
                                {freshness.label}
                              </span>
                            </span>
                          )}
                        </div>
                        {hasData ? (
                          <>
                            <div className="text-xs font-bold text-white">{formatCount(count)}</div>
                            <div className="h-0.5 bg-white/5 rounded-full mt-1.5 overflow-hidden">
                              <div className="h-full bg-white/30 rounded-full transition-all" style={{ width: `${coverage}%` }} />
                            </div>
                          </>
                        ) : (
                          <div className="text-[10px] text-gray-600 py-0.5">-</div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* 右侧汇总 */}
                <div className="flex items-center gap-3 w-48 flex-shrink-0 justify-end">
                  <div className="text-right">
                    <div className="text-xs text-gray-500">
                      {filled}/{allTimeframes.length} 周期
                    </div>
                    <div className="text-sm font-bold text-white">
                      {total > 0 ? formatCount(total) : '-'}
                    </div>
                  </div>
                  {configuredSymbol ? (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setRemoveSymbolTarget(symbol);
                      }}
                      className="h-7 w-7 rounded-lg border border-red-500/25 bg-red-500/10 text-red-300/80 hover:bg-red-500/20 hover:text-red-200 transition flex items-center justify-center"
                      title={`移除 ${coin} 交易对`}
                      aria-label={`移除 ${coin} 交易对`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  ) : (
                    <span
                      className="h-7 w-7 rounded-lg border border-blue-500/20 bg-blue-500/10 text-blue-300/70 flex items-center justify-center"
                      title="已同步数据，不在后续同步名单"
                      aria-label={`${coin} 已同步数据，不在后续同步名单`}
                    >
                      <Info className="h-3.5 w-3.5" />
                    </span>
                  )}
                  <ChevronDown className={`w-4 h-4 text-gray-500 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                </div>
              </div>

              {/* 展开详情 */}
              {isExpanded && (
                <div className="border-t border-crypto-border px-5 py-4 bg-crypto-bg/50">
                  {/* 日期选择器 */}
                  <div className="flex items-center gap-3 mb-4 pb-3 border-b border-crypto-border">
                    <Calendar className="w-3.5 h-3.5 text-gray-500" />
                    <span className="text-xs text-gray-500">同步范围:</span>
                    <input type="date" value={detailStartDate}
                      onChange={(e) => setDetailStartDate(e.target.value)}
                      onClick={(e) => e.stopPropagation()}
                      className="h-7 bg-gray-800 border border-crypto-border rounded-md px-2 text-xs text-white focus:outline-none focus:border-blue-500 transition" />
                    <span className="text-xs text-gray-600">~</span>
                    <input type="date" value={detailEndDate}
                      onChange={(e) => setDetailEndDate(e.target.value)}
                      onClick={(e) => e.stopPropagation()}
                      className="h-7 bg-gray-800 border border-crypto-border rounded-md px-2 text-xs text-white focus:outline-none focus:border-blue-500 transition" />
                    {[
                      { label: '1月', days: 30 },
                      { label: '3月', days: 90 },
                      { label: '半年', days: 180 },
                      { label: '1年', days: 365 },
                    ].map(({ label, days }) => (
                      <button key={days} onClick={(e) => {
                        e.stopPropagation();
                        const end = new Date();
                        const start = new Date(); start.setDate(start.getDate() - days);
                        setDetailStartDate(start.toISOString().slice(0, 10));
                        setDetailEndDate(end.toISOString().slice(0, 10));
                      }}
                        className="px-2 py-0.5 rounded text-[10px] bg-gray-800 border border-crypto-border text-gray-500 hover:text-white hover:bg-gray-700 transition">
                        {label}
                      </button>
                    ))}
                  </div>

                  <div className={`grid gap-3 ${
                    allTimeframes.length <= 5 ? 'grid-cols-5' : 'grid-cols-6'
                  }`}>
                    {allTimeframes.map((tf: string) => {
                      const key = `${symbol}_${tf}`;
                      const stat = statMap.get(key);
                      const meta = metaMap.get(key);
                      const count = stat?.recordCount || 0;
                      const hasData = count > 0;
                      const metaStatus = meta?.status || 'idle';
                      const metaLastSync = meta?.lastSyncAt || null;
                      const metaError = meta?.errorMessage || null;
                      const freshness = getDataFreshness(stat?.lastTimestamp || null);
                      const coverage = getCoveragePercent(stat?.firstTimestamp || null, stat?.lastTimestamp || null, 365);
                      const qualityItem = qualityMap.get(`${symbol}_${tf}`);
                      const hasQualityRisk = qualityItem?.status === 'error';
                      const qualityIssueLabel = qualityItem?.issues?.some((issue) => issue.type === 'repeated_discontinuity')
                        ? '开盘断层'
                        : '质量风险';
                      const qualityMessage = qualityItem?.message || qualityItem?.issues?.[0]?.message || '';
                      const targetSyncing = isSyncingTarget(symbol, tf);
                      const targetFeedback = targetSyncFeedback[getSyncTargetKey(symbol, tf)];
                      const targetFeedbackTone = targetFeedback?.type === 'success'
                        ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300'
                        : targetFeedback?.type === 'error'
                          ? 'bg-red-500/10 border-red-500/20 text-red-300'
                          : 'bg-blue-500/10 border-blue-500/20 text-blue-300';
                      const targetFeedbackNode = targetFeedback ? (
                        <div className={`mt-2 flex items-start gap-1.5 rounded-md border px-2 py-1.5 text-[10px] leading-snug ${targetFeedbackTone}`}>
                          {targetFeedback.type === 'success' ? (
                            <CheckCircle className="mt-0.5 h-3 w-3 flex-shrink-0" />
                          ) : targetFeedback.type === 'error' ? (
                            <AlertCircle className="mt-0.5 h-3 w-3 flex-shrink-0" />
                          ) : targetSyncing ? (
                            <Loader2 className="mt-0.5 h-3 w-3 flex-shrink-0 animate-spin" />
                          ) : (
                            <Info className="mt-0.5 h-3 w-3 flex-shrink-0" />
                          )}
                          <span className="min-w-0 flex-1 break-words">{targetFeedback.message}</span>
                        </div>
                      ) : null;

                      return (
                        <div key={tf} className={`rounded-xl border p-3 bg-gradient-to-br ${
                          hasData ? TIMEFRAME_COLORS[tf] || 'from-gray-500/10 border-gray-500/20' : 'from-crypto-card border-crypto-border'
                        }`}>
                          <div className="flex items-center justify-between mb-2">
                            <span className={`text-[10px] px-2 py-0.5 rounded border font-medium ${TIMEFRAME_BADGE[tf] || 'bg-gray-500/20 text-gray-300 border-gray-500/30'}`}>
                              {dataTimeframeLabel(tf)}
                            </span>
                            {metaStatus === 'syncing' ? (
                              <Loader2 className="w-3.5 h-3.5 text-yellow-400 animate-spin" />
                            ) : metaStatus === 'completed' && hasData ? (
                              <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                            ) : metaStatus === 'error' ? (
                              <XCircle className="w-3.5 h-3.5 text-red-400" />
                            ) : hasQualityRisk ? (
                              <AlertCircle className="w-3.5 h-3.5 text-red-300" />
                            ) : (
                              <Clock className="w-3.5 h-3.5 text-gray-500" />
                            )}
                          </div>

                          {hasData ? (
                            <div className="space-y-2">
                              <div className="text-lg font-bold text-white">{formatCount(count)}</div>
                              <div className="space-y-1 text-[10px] text-gray-500">
                                <div className="flex justify-between">
                                  <span>起始</span>
                                  <span className="text-white/70">{formatTs(stat?.firstTimestamp || null)}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span>结束</span>
                                  <span className={freshness.color}>{formatTs(stat?.lastTimestamp || null)}</span>
                                </div>
                                {metaLastSync && (
                                  <div className="flex justify-between">
                                    <span>同步于</span>
                                    <span className="text-white/50">{metaLastSync}</span>
                                  </div>
                                )}
                                {hasQualityRisk && (
                                  <div className="rounded-md border border-red-500/20 bg-red-500/10 px-2 py-1.5 text-red-200">
                                    <div className="flex items-center gap-1 text-[10px] font-semibold">
                                      <AlertCircle className="h-3 w-3" />
                                      质量风险 · {qualityIssueLabel}
                                    </div>
                                    <div className="mt-1 line-clamp-2 text-[10px] leading-snug text-red-200/80" title={qualityMessage}>
                                      {qualityMessage || '检测到 K 线开盘断层'}
                                    </div>
                                  </div>
                                )}
                              </div>
                              {/* 覆盖率 */}
                              <div>
                                <div className="flex items-center justify-between text-[10px] mb-0.5">
                                  <span className="text-gray-500">覆盖率</span>
                                  <span className="text-white/60">{coverage}%</span>
                                </div>
                                <div className="h-1 bg-white/5 rounded-full overflow-hidden">
                                  <div className={`h-full rounded-full transition-all ${
                                    coverage >= 80 ? 'bg-emerald-400' : coverage >= 50 ? 'bg-yellow-400' : 'bg-red-400'
                                  }`} style={{ width: `${coverage}%` }} />
                                </div>
                              </div>
                              <div className="flex gap-1">
                                <button onClick={(e) => { e.stopPropagation(); handleSyncOne(symbol, tf); }}
                                  disabled={isBusy}
                                  className="flex-1 text-[10px] py-1 rounded-md bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white border border-crypto-border transition disabled:opacity-30 flex items-center justify-center gap-1">
                                  {targetSyncing ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                                  {targetSyncing ? '同步中' : '增量'}
                                </button>
                                <button onClick={(e) => { e.stopPropagation(); handleSyncOne(symbol, tf, detailStartDate, detailEndDate); }}
                                  disabled={isBusy}
                                  className="flex-1 text-[10px] py-1 rounded-md bg-purple-500/10 hover:bg-purple-500/20 text-purple-300 hover:text-purple-200 border border-purple-500/20 transition disabled:opacity-30"
                                  title={`按日期同步 ${detailStartDate} ~ ${detailEndDate}`}>
                                  {targetSyncing ? '同步中' : '按日期'}
                                </button>
                              </div>
                              {targetFeedbackNode}
                            </div>
                          ) : (
                            <div className="space-y-2">
                              <div className="text-sm text-gray-600 py-2">暂无数据</div>
                              {metaError && (
                                <div className="text-[10px] text-red-400 truncate" title={metaError}>
                                  {metaError}
                                </div>
                              )}
                              <button onClick={(e) => { e.stopPropagation(); handleSyncOne(symbol, tf, detailStartDate, detailEndDate); }}
                                disabled={isBusy}
                                className="w-full text-[10px] py-1.5 rounded-md bg-blue-500/20 hover:bg-blue-500/30 text-blue-300 border border-blue-500/20 transition font-medium disabled:opacity-30 flex items-center justify-center gap-1">
                                {targetSyncing ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                                {targetSyncing ? '正在同步' : '开始同步'}
                              </button>
                              {targetFeedbackNode}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                  {/* 底部操作 */}
                  <div className="flex items-center justify-between mt-3 pt-3 border-t border-crypto-border">
                    <button onClick={(e) => { e.stopPropagation(); requestDeleteData(symbol); }}
                      className="text-xs text-red-400/70 hover:text-red-400 flex items-center gap-1 transition">
                      <Trash2 className="w-3 h-3" /> 删除 {coin} 全部数据
                    </button>
                    <button onClick={(e) => { e.stopPropagation();
                      handleSyncMissingTimeframes(symbol); }}
                      disabled={isBusy}
                      className="text-xs text-blue-400/70 hover:text-blue-400 flex items-center gap-1 transition disabled:opacity-30">
                      <Download className="w-3 h-3" /> 同步缺失周期
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
          </div>
        </div>
      </section>

      {/* ========== 说明面板 ========== */}

      {showScheduleDialog && (
        <div className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-[2px] flex items-center justify-center p-4">
          <div className="w-full max-w-5xl max-h-[calc(100vh-3rem)] overflow-y-auto rounded-2xl border border-emerald-500/35 bg-[#0f1624] shadow-2xl shadow-black/50">
            <div className="flex items-center justify-between px-6 py-4 border-b border-emerald-500/25">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-emerald-500/15 text-emerald-300 flex items-center justify-center">
                  <Clock className="w-4 h-4" />
                </div>
                <div>
                  <div className="text-base font-semibold text-white">定时同步设置</div>
                  <div className="text-xs text-gray-500 mt-0.5">设置自动同步间隔、回溯范围、交易对和同步粒度</div>
                </div>
              </div>
              <button
                onClick={() => setShowScheduleDialog(false)}
                className="w-8 h-8 rounded-lg text-gray-500 hover:text-white hover:bg-white/5 transition"
              >
                <X className="w-4 h-4 mx-auto" />
              </button>
            </div>

            <div className="px-6 py-5 space-y-5">
              {scheduleDialogError && (
                <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
                  <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                  <span>{scheduleDialogError}</span>
                </div>
              )}

              <div className="grid grid-cols-4 gap-3">
                <div className="rounded-xl border border-crypto-border bg-gray-900/45 px-4 py-3">
                  <div className="text-[11px] text-gray-500">当前状态</div>
                  <div className={`mt-1 flex items-center gap-2 text-sm font-semibold ${scheduleEnabled ? 'text-emerald-300' : 'text-gray-300'}`}>
                    <span className={`h-2 w-2 rounded-full ${scheduleEnabled ? 'bg-emerald-300' : 'bg-gray-500'}`} />
                    {scheduleEnabled ? '已启用' : '未启用'}
                  </div>
                </div>
                <div className="rounded-xl border border-crypto-border bg-gray-900/45 px-4 py-3">
                  <div className="text-[11px] text-gray-500">下次执行</div>
                  <div className="mt-1 text-sm font-semibold text-white/80">{formatDateTime(scheduleConfig?.nextRunAt)}</div>
                </div>
                <div className="rounded-xl border border-crypto-border bg-gray-900/45 px-4 py-3">
                  <div className="text-[11px] text-gray-500">上次执行</div>
                  <div className="mt-1 text-sm font-semibold text-white/80">{formatDateTime(scheduleConfig?.lastRunAt)}</div>
                </div>
                <div className="rounded-xl border border-crypto-border bg-gray-900/45 px-4 py-3">
                  <div className="text-[11px] text-gray-500">最近任务</div>
                  <div className="mt-1 text-sm font-semibold text-white/80">{scheduleConfig?.lastJobId ? scheduleConfig.lastJobId.slice(0, 8) : '-'}</div>
                </div>
              </div>

              {scheduleConfig?.lastError && (
                <div className="rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                  最近错误: {scheduleConfig.lastError}
                </div>
              )}

              <div className="flex flex-wrap items-center gap-5">
                <label className="flex items-center gap-2 text-sm text-gray-300">
                  <input
                    type="checkbox"
                    checked={scheduleEnabled}
                    onChange={(e) => setScheduleEnabled(e.target.checked)}
                    className="h-4 w-4 rounded border-crypto-border bg-gray-900 text-emerald-500 focus:ring-emerald-500"
                  />
                  启用定时同步
                </label>
                <div className="flex items-center gap-2">
                  <label className="text-xs text-gray-400">同步间隔</label>
                  <input
                    type="number"
                    min={5}
                    max={1440}
                    value={scheduleIntervalMinutes}
                    onChange={(e) => setScheduleIntervalMinutes(e.target.value)}
                    className="h-9 w-28 bg-gray-800 border border-crypto-border rounded-lg px-3 text-sm text-white focus:outline-none focus:border-emerald-500 transition"
                  />
                  <span className="text-xs text-gray-500">分钟</span>
                </div>
                <div className="flex items-center gap-2">
                  <label className="text-xs text-gray-400">回溯天数</label>
                  <input
                    type="number"
                    value={SYNC_HISTORY_DAYS}
                    disabled
                    className="h-9 w-28 cursor-not-allowed bg-gray-900 border border-crypto-border rounded-lg px-3 text-sm text-gray-400"
                  />
                  <span className="text-xs text-gray-500">天</span>
                </div>
              </div>

              <div>
                <div className="flex items-center gap-2 mb-2">
                  <label className="text-xs text-gray-400">同步标的</label>
                </div>
                <div className="rounded-lg border border-cyan-500/25 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-200">
                  自动跟踪全部当前有效的 OKX USDT 永续合约；每次调度前自动纳入新合约并剔除下架合约。
                </div>
              </div>

              <div>
                <div className="flex items-center gap-2 mb-2">
                  <label className="text-xs text-gray-400">同步粒度</label>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {SYNC_TIMEFRAME_ORDER.map((tf: string) => {
                    return (
                      <span
                        key={tf}
                        className={`px-3 py-1.5 rounded-md text-xs font-medium border ${TIMEFRAME_BADGE[tf] || 'bg-gray-500/20 text-gray-300 border-gray-500/30'}`}
                      >
                        {dataTimeframeLabel(tf)}
                      </span>
                    );
                  })}                </div>
              </div>
            </div>

            <div className="px-6 py-4 border-t border-crypto-border flex items-center justify-between">
              <div className="text-xs text-gray-500">
                每 {scheduleIntervalMinutes || 240} 分钟 · 最近 {SYNC_HISTORY_DAYS} 天
                {scheduleSymbols.length > 0 ? ` · ${scheduleSymbols.length} 个币种` : ' · 全部币种'}
                {scheduleTimeframes.length > 0 ? ` · ${scheduleTimeframes.map(dataTimeframeLabel).join('/')}` : ' · 全部周期'}
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => setShowScheduleDialog(false)}
                  className="h-9 px-5 rounded-lg bg-gray-800 border border-crypto-border text-gray-400 hover:text-white text-xs transition">
                  取消
                </button>
                <button onClick={() => void submitScheduleDialog()} disabled={savingSchedule}
                  className="h-9 px-6 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed transition-all">
                  {savingSchedule ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle className="w-3 h-3" />}
                  保存设置
                </button>
              </div>
            </div>

            {/* ========== A 股扩展数据源 ========== */}
            <div className="px-6 py-5 border-t border-crypto-border space-y-4">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-cyan-500/15 text-cyan-300 flex items-center justify-center">
                  <Activity className="w-4 h-4" />
                </div>
                <div className="flex-1">
                  <div className="text-base font-semibold text-white">A 股扩展数据源</div>
                  <div className="text-xs text-gray-500 mt-0.5">
                    独立于日线主数据的资金流、龙虎榜、股东与基本面 Provider 管道；当前只展示能力边界，不自动拉取。
                  </div>
                </div>
                <label className="flex items-center gap-2 text-sm text-gray-300">
                  <input
                    type="checkbox"
                    checked={okxNativeEnabled}
                    onChange={(e) => setOkxNativeEnabled(e.target.checked)}
                    className="h-4 w-4 rounded border-crypto-border bg-gray-900 text-cyan-500 focus:ring-cyan-500"
                  />
                  启用
                </label>
              </div>

              <div className="grid grid-cols-4 gap-3">
                <div className="rounded-xl border border-crypto-border bg-gray-900/45 px-4 py-3">
                  <div className="text-[11px] text-gray-500">资金流记录</div>
                  <div className="mt-1 text-sm font-semibold text-white/80">{okxNativeConfig?.rubikRowCount ?? 0}</div>
                </div>
                <div className="rounded-xl border border-crypto-border bg-gray-900/45 px-4 py-3">
                  <div className="text-[11px] text-gray-500">龙虎榜/机构记录</div>
                  <div className="mt-1 text-sm font-semibold text-white/80">{okxNativeConfig?.oiSnapshotCount ?? 0}</div>
                </div>
                <div className="rounded-xl border border-crypto-border bg-gray-900/45 px-4 py-3">
                  <div className="text-[11px] text-gray-500">上次 Provider 同步</div>
                  <div className="mt-1 text-sm font-semibold text-white/80">{formatDateTime(okxNativeConfig?.lastRubikFinishedAt)}</div>
                </div>
                <div className="rounded-xl border border-crypto-border bg-gray-900/45 px-4 py-3">
                  <div className="text-[11px] text-gray-500">上次封存快照</div>
                  <div className="mt-1 text-sm font-semibold text-white/80">{formatDateTime(okxNativeConfig?.lastOiFinishedAt)}</div>
                </div>
              </div>

              {(okxNativeConfig?.lastRubikError || okxNativeConfig?.lastOiError) && (
                <div className="rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                  最近错误: {okxNativeConfig?.lastRubikError || okxNativeConfig?.lastOiError}
                </div>
              )}

              <div className="flex flex-wrap items-center gap-5">
                <div className="flex items-center gap-2">
                  <label className="text-xs text-gray-400">Provider 同步间隔</label>
                  <input
                    type="number"
                    min={10}
                    max={1440}
                    value={okxRubikInterval}
                    onChange={(e) => setOkxRubikInterval(e.target.value)}
                    className="h-9 w-24 bg-gray-800 border border-crypto-border rounded-lg px-3 text-sm text-white focus:outline-none focus:border-cyan-500 transition"
                  />
                  <span className="text-xs text-gray-500">分钟</span>
                </div>
                <div className="flex items-center gap-2">
                  <label className="text-xs text-gray-400">快照封存间隔</label>
                  <input
                    type="number"
                    min={10}
                    max={1440}
                    value={okxOiInterval}
                    onChange={(e) => setOkxOiInterval(e.target.value)}
                    className="h-9 w-24 bg-gray-800 border border-crypto-border rounded-lg px-3 text-sm text-white focus:outline-none focus:border-cyan-500 transition"
                  />
                  <span className="text-xs text-gray-500">分钟</span>
                </div>
                <button disabled
                  className="h-9 px-4 rounded-lg bg-gray-800 border border-cyan-500/30 text-cyan-200 hover:bg-gray-700 text-xs font-medium flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed transition-all">
                  {okxNativeBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
                  受控同步未启用
                </button>
                <button disabled
                  className="h-9 px-4 rounded-lg bg-gray-800 border border-cyan-500/30 text-cyan-200 hover:bg-gray-700 text-xs font-medium flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed transition-all">
                  {okxNativeBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
                  快照封存未启用
                </button>
              </div>

              {okxNativeFeedback && (
                <div className="rounded-lg border border-cyan-500/25 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-200">
                  {okxNativeFeedback}
                </div>
              )}

              <div className="flex items-center justify-between">
                <div className="text-xs text-gray-500">
                  数据最终必须落入 PostgreSQL 分区并封存快照；页面 GET 不会隐式调用 Provider。
                </div>
                <button disabled
                  className="h-9 px-6 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-medium flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed transition-all">
                  {okxNativeBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle className="w-3 h-3" />}
                  写入门禁未开放
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {syncDialogMode && (
        <div className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-[2px] flex items-center justify-center p-4">
          <div className="w-full max-w-6xl max-h-[calc(100vh-3rem)] overflow-y-auto rounded-2xl border border-purple-500/35 bg-[#0f1624] shadow-2xl shadow-black/50">
            <div className="flex items-center justify-between px-6 py-4 border-b border-purple-500/25">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-purple-500/20 text-purple-300 flex items-center justify-center">
                  <Calendar className="w-4 h-4" />
                </div>
                <div>
                  <div className="text-base font-semibold text-white">同步配置 · {syncDialogTitle}</div>
                  <div className="text-xs text-gray-500 mt-0.5">{syncDialogDescription}</div>
                </div>
              </div>
              <button
                onClick={() => setSyncDialogMode(null)}
                className="w-8 h-8 rounded-lg text-gray-500 hover:text-white hover:bg-white/5 transition"
              >
                <X className="w-4 h-4 mx-auto" />
              </button>
            </div>

            <div className="px-6 py-5 space-y-5">
              {syncDialogError && (
                <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
                  <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                  <span>{syncDialogError}</span>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-4">
                <div className="flex items-center gap-2">
                  <label className="text-xs text-gray-400 w-16">开始日期</label>
                  <input
                    type="date"
                    min={dateDaysAgo(SYNC_HISTORY_DAYS)}
                    value={syncDialogStartDate}
                    onChange={(e) => setSyncDialogStartDate(e.target.value)}
                    className="h-9 bg-gray-800 border border-crypto-border rounded-lg px-3 text-sm text-white focus:outline-none focus:border-purple-500 transition"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <label className="text-xs text-gray-400 w-16">结束日期</label>
                  <input
                    type="date"
                    value={syncDialogEndDate}
                    onChange={(e) => setSyncDialogEndDate(e.target.value)}
                    className="h-9 bg-gray-800 border border-crypto-border rounded-lg px-3 text-sm text-white focus:outline-none focus:border-purple-500 transition"
                  />
                </div>
                <div className="flex items-center gap-1.5">
                  {[
                    { label: '近3月', days: 90 },
                  ].map(({ label, days }) => (
                    <button key={days} onClick={() => {
                      setSyncDialogStartDate(dateDaysAgo(days));
                      setSyncDialogEndDate(new Date().toISOString().slice(0, 10));
                    }}
                      className="px-2.5 py-1 rounded-md text-xs bg-gray-800 border border-crypto-border text-gray-400 hover:text-white hover:bg-gray-700 transition">
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <div className="flex items-center gap-2 mb-2">
                  <label className="text-xs text-gray-400">交易对</label>
                  <button onClick={() => setSyncDialogSymbols(syncDialogSymbols.length === configuredSymbols.length ? [] : [...configuredSymbols])}
                    className="text-[10px] text-purple-400 hover:text-purple-300 transition">
                    {syncDialogSymbols.length === configuredSymbols.length ? '取消全选' : '全选'}
                  </button>
                  {syncDialogSymbols.length === 0 && (
                    <span className="text-[10px] text-gray-600">（不选 = 全部）</span>
                  )}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {configuredSymbols.map((sym) => {
                    const coin = getCoinBase(sym);
                    const selected = syncDialogSymbols.includes(sym);
                    return (
                      <button key={sym} aria-pressed={selected} onClick={() =>
                        setSyncDialogSymbols(selected
                          ? syncDialogSymbols.filter(s => s !== sym)
                          : [...syncDialogSymbols, sym]
                        )}
                        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition border ${
                          selected
                            ? SELECTED_SEGMENT_BORDER_CLASS
                            : 'text-gray-500 border-crypto-border hover:text-gray-300 bg-gray-800/50'
                        }`}>
                        <SymbolIcon symbol={sym} base={coin} size="xs" />
                        <span>{coin}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <div className="flex items-center gap-2 mb-2">
                  <label className="text-xs text-gray-400">时间周期</label>
                  <button onClick={() => setSyncDialogTimeframes(syncDialogTimeframes.length === SYNC_TIMEFRAME_ORDER.length ? [] : [...SYNC_TIMEFRAME_ORDER])}
                    className="text-[10px] text-purple-400 hover:text-purple-300 transition">
                    {syncDialogTimeframes.length === SYNC_TIMEFRAME_ORDER.length ? '取消全选' : '全选'}
                  </button>
                  {syncDialogTimeframes.length === 0 && (
                    <span className="text-[10px] text-gray-600">（不选 = 全部）</span>
                  )}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {SYNC_TIMEFRAME_ORDER.map((tf: string) => {
                    const selected = syncDialogTimeframes.includes(tf);
                    return (
                      <button key={tf} onClick={() =>
                        setSyncDialogTimeframes(selected
                          ? syncDialogTimeframes.filter(t => t !== tf)
                          : [...syncDialogTimeframes, tf]
                        )}
                        className={`px-3 py-1.5 rounded-md text-xs font-medium transition border ${
                          selected
                            ? `${TIMEFRAME_BADGE[tf] || 'bg-gray-500/20 text-gray-300 border-gray-500/30'}`
                            : 'text-gray-500 border-crypto-border hover:text-gray-300 bg-gray-800/50'
                        }`}>
                        {dataTimeframeLabel(tf)}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="px-6 py-4 border-t border-crypto-border flex items-center justify-between">
              <div className="text-xs text-gray-500">
                {syncDialogStartDate} ~ {syncDialogEndDate}
                {syncDialogSymbols.length > 0 ? ` · ${syncDialogSymbols.length} 个币种` : ' · 全部币种'}
                {syncDialogTimeframes.length > 0 ? ` · ${syncDialogTimeframes.join('/')}` : ' · 全部周期'}
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => setSyncDialogMode(null)}
                  className="h-9 px-5 rounded-lg bg-gray-800 border border-crypto-border text-gray-400 hover:text-white text-xs transition">
                  取消
                </button>
                <button onClick={submitSyncDialog} disabled={isBusy}
                  className="h-9 px-6 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-medium flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed transition-all">
                  {syncing && syncingMode === syncDialogMode ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
                  开始同步
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <ThemeDialog
        open={deleteTarget !== null}
        variant="confirm"
        title="删除本地数据"
        content={
          deleteTarget
            ? `确认删除 ${deleteTarget.label} 的数据？此操作不可恢复。`
            : ''
        }
        tone="danger"
        confirmText="删除"
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => void runDeleteData()}
      />

      <ThemeDialog
        open={showAddSymbolDialog}
        variant="confirm"
        title="增加交易对"
        tone="default"
        confirmText={addingSymbol ? '添加中...' : addSymbolSelections.filter((symbol) => !configuredSymbolSet.has(symbol)).length > 1 ? `添加 ${addSymbolSelections.filter((symbol) => !configuredSymbolSet.has(symbol)).length} 个` : '添加'}
        onCancel={() => {
          if (!addingSymbol) setShowAddSymbolDialog(false);
        }}
        onConfirm={() => void handleAddSymbol()}
      >
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-400">搜索交易对</label>
            <div className="relative mt-2">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
              <input
                autoFocus
                type="text"
                value={addSymbolSearch}
                onChange={(e) => {
                  setAddSymbolSearch(e.target.value);
                  setAddSymbolError('');
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    const firstAvailable = addSymbolGroups.find((group) =>
                      [group.spotSymbol, group.swapSymbol].some((symbol) => symbol && !configuredSymbolSet.has(symbol))
                    );
                    if (firstAvailable) selectAddSymbolGroup(firstAvailable);
                  }
                }}
                placeholder="搜索 BTC、OPENAI 或 OPENAI-USDT-SWAP"
                className="h-10 w-full rounded-lg border border-crypto-border bg-gray-900 pl-9 pr-3 text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div className="mt-2 text-[11px] text-gray-500">仅添加 OKX USDT 永续合约；现货不进入后续同步。</div>
          </div>
          <div className="rounded-lg border border-crypto-border bg-gray-900/50">
            <div className="flex items-center justify-between border-b border-crypto-border px-3 py-2 text-xs text-gray-500">
              <span>可添加交易对</span>
              <span>{loadingAvailableSymbols ? '加载中...' : `${addSymbolGroups.length}/${buildAddSymbolGroups(availableSymbols).length}`}</span>
            </div>
            <div className="max-h-64 overflow-y-auto p-2">
              {loadingAvailableSymbols ? (
                <div className="flex items-center justify-center gap-2 py-8 text-xs text-gray-500">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  正在获取交易对...
                </div>
              ) : addSymbolGroups.length === 0 ? (
                <div className="py-8 text-center text-xs text-gray-500">暂无匹配的交易对</div>
              ) : (
                <div className="grid grid-cols-2 gap-2">
                  {addSymbolGroups.slice(0, 120).map((group) => {
                    const groupSymbols = [group.swapSymbol].filter((symbol): symbol is string => Boolean(symbol));
                    const selected = groupSymbols.some((symbol) => addSymbolSelections.includes(symbol));
                    const allAdded = groupSymbols.every((symbol) => configuredSymbolSet.has(symbol));
                    return (
                      <div
                        key={group.base}
                        className={`rounded-lg border text-xs transition ${
                          selected
                            ? SELECTED_SEGMENT_BORDER_CLASS
                            : allAdded
                              ? 'border-crypto-border bg-gray-800/40 text-gray-600'
                              : 'border-crypto-border bg-gray-800/60 text-gray-300 hover:border-emerald-500/50 hover:text-white'
                        }`}
                      >
                        <button
                          type="button"
                          disabled={allAdded}
                          onClick={() => selectAddSymbolGroup(group)}
                          className="w-full px-3 py-2 text-left disabled:cursor-not-allowed"
                        >
                          <span className="flex items-center gap-2 font-semibold">
                            <SymbolIcon symbol={group.swapSymbol || `${group.base}/USDT:USDT`} base={group.base} size="xs" shape="rounded" />
                            <span className="truncate">{group.base}/USDT</span>
                          </span>
                          <span className="mt-0.5 block truncate text-[10px] text-gray-500">
                            {allAdded ? '已在列表中' : '点击默认选择可添加市场'}
                          </span>
                        </button>
                        <div className="grid grid-cols-1 gap-1.5 px-2 pb-2">
                          {([
                            { symbol: group.swapSymbol, label: 'USDT 永续' },
                          ] as const).map((item) => {
                            const symbol = item.symbol;
                            const unavailable = !symbol;
                            const added = Boolean(symbol && configuredSymbolSet.has(symbol));
                            const itemSelected = Boolean(symbol && addSymbolSelections.includes(symbol));
                            return (
                              <button
                                key={item.label}
                                type="button"
                                disabled={unavailable || added}
                                onClick={() => symbol && toggleAddSymbolSelection(symbol)}
                                className={`flex items-center justify-between rounded-md border px-2 py-1.5 text-[10px] transition ${
                                  itemSelected
                                    ? SELECTED_SEGMENT_BORDER_CLASS
                                    : added
                                      ? 'cursor-not-allowed border-crypto-border bg-gray-950/40 text-gray-600'
                                      : unavailable
                                        ? 'cursor-not-allowed border-crypto-border bg-gray-950/20 text-gray-700'
                                        : 'border-crypto-border bg-gray-950/35 text-gray-400 hover:text-white'
                                }`}
                                title={symbol ? formatOkxInstrumentId(symbol) : `${group.base} 暂无${item.label}`}
                              >
                                <span>{item.label}</span>
                                <span>{added ? '已添加' : itemSelected ? '已选' : unavailable ? '-' : '+'}</span>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
          <div className="text-xs text-gray-500">
            当前选择: <span className="font-medium text-white">{addSymbolSelections.length > 0 ? addSymbolSelections.join(' / ') : addSymbolInput || '未选择'}</span>
            <span className="ml-2 text-emerald-300">
              添加 {addSymbolSelections.filter((symbol) => !configuredSymbolSet.has(symbol)).length} 个交易对
            </span>
          </div>
          <div className="rounded-lg border border-crypto-border bg-gray-900/45 p-3">
            <label className="flex items-center gap-2 text-xs font-medium text-gray-300">
              <input
                type="checkbox"
                checked={syncAddedSymbolHistory}
                onChange={(e) => setSyncAddedSymbolHistory(e.target.checked)}
                className="h-4 w-4 rounded border-crypto-border bg-gray-950 text-emerald-500 focus:ring-emerald-500"
              />
              添加后同步历史数据
            </label>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {ADD_SYMBOL_HISTORY_RANGE_OPTIONS.map((option) => (
                <button
                  key={option.days}
                  type="button"
                  disabled={!syncAddedSymbolHistory}
                  onClick={() => setAddSymbolHistoryDays(option.days)}
                  className={`h-7 rounded-md border px-2.5 text-[11px] font-medium transition ${
                    addSymbolHistoryDays === option.days && syncAddedSymbolHistory
                      ? SELECTED_SEGMENT_BORDER_CLASS
                      : 'border-crypto-border bg-gray-950/35 text-gray-500 hover:text-gray-300 disabled:cursor-not-allowed disabled:opacity-40'
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <div className="mt-2 text-[11px] text-gray-500">
              默认同步近1年；同步会提交后台任务，使用当前数据页配置的全部 K线周期。
            </div>
          </div>
          {addSymbolError && (
            <div className="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300">
              {addSymbolError}
            </div>
          )}
        </div>
      </ThemeDialog>

      <ThemeDialog
        open={showRemoveSymbolDialog}
        variant="alert"
        title="删除交易对"
        tone="danger"
        confirmText="关闭"
        onClose={() => setShowRemoveSymbolDialog(false)}
      >
        <div className="space-y-3">
          <div className="text-xs text-gray-400">
            选择要从后续同步名单移除的 {dataMarketLabel(dataMarketType)} 交易对。这里不会删除已同步的历史 K线数据。
          </div>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
            <input
              type="text"
              value={removeSymbolSearch}
              onChange={(event) => setRemoveSymbolSearch(event.target.value)}
              placeholder="搜索要删除的交易对..."
              className="h-10 w-full rounded-lg border border-crypto-border bg-gray-950/50 pl-9 pr-3 text-sm text-white placeholder-gray-600 outline-none transition focus:border-red-400/50"
            />
          </div>
          <div className="max-h-72 overflow-y-auto rounded-xl border border-crypto-border bg-crypto-bg/50 p-1.5">
            {removeSymbolCandidates.length === 0 ? (
              <div className="px-3 py-8 text-center text-sm text-gray-500">
                暂无可删除的交易对
              </div>
            ) : removeSymbolCandidates.map((symbol) => {
              const coin = getCoinBase(symbol);
              return (
                <button
                  key={symbol}
                  type="button"
                  onClick={() => {
                    setShowRemoveSymbolDialog(false);
                    setRemoveSymbolTarget(symbol);
                  }}
                  className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left transition hover:bg-red-500/10"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <SymbolIcon symbol={symbol} base={coin} size="sm" shape="rounded" />
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-semibold text-white">{formatOkxInstrumentId(symbol)}</span>
                      <span className="block truncate text-xs text-gray-500">{coin} · {isUsdtSwapSymbol(symbol) ? 'USDT 永续' : '现货'}</span>
                    </span>
                  </span>
                  <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-red-500/25 bg-red-500/10 text-red-300">
                    <Trash2 className="h-3.5 w-3.5" />
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </ThemeDialog>

      <ThemeDialog
        open={removeSymbolTarget !== null}
        variant="confirm"
        title="移除交易对"
        content={
          removeSymbolTarget
            ? `确认从数据同步名单移除 ${formatOkxInstrumentId(removeSymbolTarget)}？这只会移除后续同步配置，不会删除已同步的历史 K线数据。`
            : ''
        }
        tone="danger"
        confirmText={removingSymbol ? '移除中...' : '移除'}
        onCancel={() => {
          if (!removingSymbol) setRemoveSymbolTarget(null);
        }}
        onConfirm={() => void handleRemoveSymbol()}
      />
    </div>
  );
}
