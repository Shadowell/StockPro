import { useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import { DataPanel, StatusBadge } from '@bitpro/ui';
import { OperatorMetricCard } from '../components/OperatorShell';
import type { MetricTone } from '../utils/marketColors';
import {
  AlertCircle,
  BarChart3,
  Calendar,
  CheckCircle,
  ChevronDown,
  Clock,
  Database,
  Download,
  HardDrive,
  Info,
  LayoutDashboard,
  ListChecks,
  Play,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  TrendingUp,
  X,
  Zap,
} from 'lucide-react';
import {
  addDataSymbol,
  deleteDataKlines,
  getDataConfig,
  getDailyReferenceSchedule,
  getDataSchedule,
  getDataStatus,
  getDataTableStats,
  getResearchDatasetSnapshots,
  getResearchDatasets,
  getTushareEndpoints,
  probeTushareEndpoint,
  removeDataSymbol,
  runDailyReferenceSchedule,
  searchStocks,
  startDataSync,
  syncAllMarketHistory,
  triggerDataSync,
  updateDailyReferenceSchedule,
  updateDataSchedule,
  type DataTableStatsResponse,
  type DataSyncConfigResponse,
  type DataSyncScheduleConfig,
  type DailyReferenceSchedule,
  type ResearchDataset,
  type ResearchDatasetSnapshot,
  type TushareEndpoint,
  type TushareEndpointCatalogResponse,
} from '../api/client';
import type { StockCandidate } from '../types';
import { evaluateFreshness } from '../utils/dataFreshness';
import { formatSymbolLabel, resolveSymbolName, toPublicSymbol } from '../utils/symbolDisplay';
import { WorkspaceTabs } from '../components/WorkspaceTabs';

type DataStatus = {
  database?: string;
  status?: string;
  storage?: string;
  sync?: {
    is_running?: boolean;
    message?: string;
    last_started_at?: string | null;
    last_finished_at?: string | null;
  };
  tables?: Array<{ name: string; rows: number }>;
  kline_coverage?: CoverageRow[];
  sync_jobs?: SyncJob[];
};

type CoverageRow = {
  exchange?: string;
  symbol: string;
  name?: string;
  timeframe: string;
  rows: number;
  first_date?: string | null;
  last_date?: string | null;
  status?: string | null;
  last_sync_at?: string | null;
  error_message?: string | null;
  total_records?: number;
};

type SyncJob = {
  id: number;
  job_name?: string;
  source?: string;
  start_date?: string;
  end_date?: string;
  status?: string;
  total_items?: number;
  completed_items?: number;
  failed_items?: number;
  message?: string | null;
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
};

type DataSection = 'overview' | 'datasets' | 'coverage' | 'jobs' | 'providers';

const TIMEFRAME_LABELS: Record<string, string> = {
  '1m': '1M',
  '5m': '5M',
  '15m': '15M',
  '30m': '30M',
  '1h': '1H',
  '4h': '4H',
  '1d': '1D',
};

const TIMEFRAME_BADGE: Record<string, string> = {
  '1m': 'bg-rose-500/20 text-rose-300 border-rose-500/30',
  '5m': 'bg-violet-500/20 text-violet-300 border-violet-500/30',
  '15m': 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  '30m': 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30',
  '1h': 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
  '4h': 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  '1d': 'bg-amber-500/20 text-amber-300 border-amber-500/30',
};

const TIMEFRAME_COLORS: Record<string, string> = {
  '1m': 'from-rose-500/20 to-rose-600/5 border-rose-500/30',
  '5m': 'from-violet-500/20 to-violet-600/5 border-violet-500/30',
  '15m': 'from-blue-500/20 to-blue-600/5 border-blue-500/30',
  '30m': 'from-indigo-500/20 to-indigo-600/5 border-indigo-500/30',
  '1h': 'from-cyan-500/20 to-cyan-600/5 border-cyan-500/30',
  '4h': 'from-emerald-500/20 to-emerald-600/5 border-emerald-500/30',
  '1d': 'from-amber-500/20 to-amber-600/5 border-amber-500/30',
};

const TIMEFRAME_ORDER = ['1m', '5m', '15m', '30m', '1h', '4h', '1d'];

const TUSHARE_MODULE_LABELS: Record<string, string> = {
  reference_calendar: '基础与日历',
  price_valuation: '行情与估值',
  financial_disclosure: '财报与披露',
  index_industry: '指数与行业',
  capital_flow_dragon_tiger: '资金流与龙虎榜',
  limit_up_ecology: '涨跌停生态',
  fund_etf_convertible: '基金、ETF 与可转债',
  macro_context: '宏观环境',
  restricted_extensions: '权限受限扩展',
  independent_extensions: '单独授权扩展',
};

const endpointState = (endpoint: TushareEndpoint) => {
  const state = endpoint.permission_state || (endpoint.enabled ? 'catalogue_eligible' : endpoint.baseline_state);
  if (state === 'available') return { label: '已验证', tone: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200' };
  if (state === 'available_empty') return { label: '已验证（空）', tone: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200' };
  if (state === 'missing_token') return { label: '待配置令牌', tone: 'border-yellow-500/25 bg-yellow-500/10 text-yellow-200' };
  if (state === 'failed') return { label: '探测失败', tone: 'border-red-500/25 bg-red-500/10 text-red-200' };
  if (state === 'independent_authorization') return { label: '需单独授权', tone: 'border-violet-500/25 bg-violet-500/10 text-violet-200' };
  if (state === 'restricted') return { label: '需要更高权限', tone: 'border-gray-600 bg-gray-800 text-gray-400' };
  return { label: '目录支持', tone: 'border-blue-500/25 bg-blue-500/10 text-blue-200' };
};

const format = (value?: number | null) =>
  value === null || value === undefined || Number.isNaN(value) ? '--' : Number(value).toLocaleString('zh-CN');

const dateOffset = (days: number) => {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
};

const statusLabel = (status?: string | null) => {
  if (!status) return '空闲';
  if (status === 'running' || status === 'syncing' || status === 'pending') return '同步中';
  if (status === 'success' || status === 'completed') return '完成';
  if (status === 'partial') return '部分完成';
  if (status === 'failed') return '失败';
  return status;
};

const statusTone = (status?: string | null) => {
  if (status === 'success' || status === 'completed') return 'text-emerald-300 border-emerald-500/25 bg-emerald-500/10';
  if (status === 'failed') return 'text-red-300 border-red-500/25 bg-red-500/10';
  if (status === 'partial') return 'text-yellow-300 border-yellow-500/25 bg-yellow-500/10';
  if (status === 'running' || status === 'syncing' || status === 'pending') return 'text-blue-300 border-blue-500/25 bg-blue-500/10';
  return 'text-gray-400 border-crypto-border bg-crypto-bg';
};

const parseDate = (value?: string | null) => {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
};

const coveragePercent = (item: CoverageRow) => {
  const first = parseDate(item.first_date);
  const last = parseDate(item.last_date);
  if (!first || !last) return item.rows > 0 ? 100 : 0;
  const days = Math.max(1, Math.round((last.getTime() - first.getTime()) / 86400000) + 1);
  const expectedTradingDays = Math.max(1, Math.round(days * 5 / 7));
  return Math.min(100, Math.round((Number(item.rows || 0) / expectedTradingDays) * 100));
};

const compactDate = (value?: string | null) => {
  if (!value) return '--';
  return String(value).replace('T', ' ').slice(0, 19);
};

export function DataCenter() {
  const [activeSection, setActiveSection] = useState<DataSection>('overview');
  const [status, setStatus] = useState<DataStatus | null>(null);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [symbols, setSymbols] = useState('SH_600000,SZ_000001');
  const [startDate, setStartDate] = useState(dateOffset(-90));
  const [endDate, setEndDate] = useState(dateOffset(0));
  const [jobHistoryExpanded, setJobHistoryExpanded] = useState(true);
  const [filterSymbol, setFilterSymbol] = useState('');
  const [filterTf, setFilterTf] = useState('');
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);
  const [showSyncDialog, setShowSyncDialog] = useState(false);
  const [detailStartDate, setDetailStartDate] = useState(dateOffset(-90));
  const [detailEndDate, setDetailEndDate] = useState(dateOffset(0));
  const [dataConfig, setDataConfig] = useState<DataSyncConfigResponse | null>(null);
  const [scheduleConfig, setScheduleConfig] = useState<DataSyncScheduleConfig | null>(null);
  const [showScheduleDialog, setShowScheduleDialog] = useState(false);
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduleIntervalMinutes, setScheduleIntervalMinutes] = useState(1440);
  const [scheduleRunHour, setScheduleRunHour] = useState(17);
  const [scheduleRunMinute, setScheduleRunMinute] = useState(30);
  const [scheduleHistoryDays, setScheduleHistoryDays] = useState(365);
  const [scheduleCatchupDays, setScheduleCatchupDays] = useState(5);
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [runningDailyReference, setRunningDailyReference] = useState(false);
  const [showAddSymbolDialog, setShowAddSymbolDialog] = useState(false);
  const [addSymbolQuery, setAddSymbolQuery] = useState('');
  const [addSymbolResults, setAddSymbolResults] = useState<StockCandidate[]>([]);
  const [selectedAddSymbol, setSelectedAddSymbol] = useState<StockCandidate | null>(null);
  const [searchingSymbol, setSearchingSymbol] = useState(false);
  const [addingSymbol, setAddingSymbol] = useState(false);
  const [syncAddedSymbolHistory, setSyncAddedSymbolHistory] = useState(true);
  const [showRemoveSymbolDialog, setShowRemoveSymbolDialog] = useState(false);
  const [removeSymbolTarget, setRemoveSymbolTarget] = useState<{ symbol: string; name?: string | null } | null>(null);
  const [removingSymbol, setRemovingSymbol] = useState(false);
  const [tableStats, setTableStats] = useState<DataTableStatsResponse | null>(null);
  const [tushareCatalog, setTushareCatalog] = useState<TushareEndpointCatalogResponse | null>(null);
  const [researchDatasets, setResearchDatasets] = useState<ResearchDataset[]>([]);
  const [researchSnapshots, setResearchSnapshots] = useState<ResearchDatasetSnapshot[]>([]);
  const [dailyReferenceSchedule, setDailyReferenceSchedule] = useState<DailyReferenceSchedule | null>(null);
  const [catalogModule, setCatalogModule] = useState('');
  const [probingEndpoint, setProbingEndpoint] = useState(false);
  const [showDeleteDataDialog, setShowDeleteDataDialog] = useState(false);
  const [deleteDataTarget, setDeleteDataTarget] = useState<{ symbol: string; name?: string | null } | null>(null);
  const [deletingData, setDeletingData] = useState(false);
  const [loadIssues, setLoadIssues] = useState<string[]>([]);

  const load = async () => {
    setLoading(true);
    setLoadIssues([]);
    try {
      const issues: string[] = [];
      const safe = async <T,>(label: string, request: Promise<T>): Promise<T | null> => {
        try {
          return await request;
        } catch {
          issues.push(label);
          return null;
        }
      };
      const [nextStatus, nextConfig, nextSchedule, nextTableStats, nextTushareCatalog, nextResearchDatasets, nextResearchSnapshots, nextDailyReferenceSchedule] = await Promise.all([
        safe('数据状态', getDataStatus<DataStatus>()),
        safe('同步配置', getDataConfig()),
        safe('调度配置', getDataSchedule()),
        safe('表统计', getDataTableStats()),
        safe('TuShare 目录', getTushareEndpoints()),
        safe('研究数据集', getResearchDatasets()),
        safe('研究快照', getResearchDatasetSnapshots()),
        safe('日终编排', getDailyReferenceSchedule()),
      ]);
      setStatus(nextStatus);
      setTableStats(nextTableStats);
      setTushareCatalog(nextTushareCatalog);
      setResearchDatasets(nextResearchDatasets?.items || []);
      setResearchSnapshots(nextResearchSnapshots?.items || []);
      setDailyReferenceSchedule(nextDailyReferenceSchedule);
      if (nextConfig) {
        setDataConfig(nextConfig);
        if (nextConfig.defaultSymbols?.length) {
          setSymbols(nextConfig.defaultSymbols.join(','));
        }
      }
      if (nextSchedule) {
        setScheduleConfig(nextSchedule);
        setScheduleEnabled(Boolean(nextSchedule.enabled));
        setScheduleIntervalMinutes(Number(nextSchedule.intervalMinutes || 1440));
        setScheduleRunHour(Number(nextSchedule.runHour ?? 18));
        setScheduleRunMinute(Number(nextSchedule.runMinute ?? 10));
        setScheduleHistoryDays(Number(nextSchedule.historyDays || nextConfig?.defaultHistoryDays || 365));
      }
      setLoadIssues(issues);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const coverage = useMemo(() => status?.kline_coverage || [], [status?.kline_coverage]);
  const symbolNameMap = useMemo(() => {
    const map = new Map<string, string>();
    coverage.forEach((item) => {
      const name = String(item.name || '').trim();
      if (item.symbol && name && name !== item.symbol) map.set(item.symbol, name);
    });
    return map;
  }, [coverage]);
  const jobs = status?.sync_jobs || [];
  const tables = status?.tables || [];
  const defaultTimeframes = dataConfig?.defaultTimeframes?.length ? dataConfig.defaultTimeframes : ['1d'];
  const defaultHistoryDays = dataConfig?.defaultHistoryDays || 365;
  const coverageSampleRows = coverage.reduce((sum, item) => sum + Number(item.rows || 0), 0);
  const dailyTable = tables.find((item) => ['kline_1d', 'kline_history'].includes(item.name));
  const dailyTableRows = dailyTable ? Number(dailyTable.rows || 0) : null;
  const totalRows = dailyTableRows ?? (coverage.length > 0 ? coverageSampleRows : null);
  const totalRowsLabel = dailyTable ? '日线全表统计' : coverage.length > 0 ? '覆盖统计样本合计' : '尚未读取日线统计';
  const isRunning = Boolean(status?.sync?.is_running || syncing || jobs.some((job) => ['pending', 'running', 'syncing'].includes(String(job.status))));
  const lastRunResult = dailyReferenceSchedule?.lastRun?.result as {
    publication?: { actual_source?: string; fallback_reason?: string | null; response_hash?: string; snapshot?: { id?: number } };
    factorSchedule?: { status?: string; factor_snapshot?: { id?: number }; factor_snapshot_id?: number };
    marketEvidence?: { status?: string; snapshot_id?: number | null };
  } | undefined;
  const lastPublication = lastRunResult?.publication;
  const lastFactorSchedule = lastRunResult?.factorSchedule;

  const groupedCoverage = useMemo(() => {
    const groups = new Map<string, { symbol: string; name?: string; rows: CoverageRow[]; total: number }>();
    coverage.forEach((item) => {
      const key = item.symbol;
      const current = groups.get(key) || { symbol: key, name: item.name, rows: [], total: 0 };
      current.rows.push(item);
      current.total += Number(item.rows || 0);
      if (!current.name && item.name) current.name = item.name;
      groups.set(key, current);
    });
    const query = filterSymbol.trim().toUpperCase();
    return Array.from(groups.values())
      .filter((item) => {
        const label = formatSymbolLabel(item.symbol, item.name).toUpperCase();
        return !query || item.symbol.toUpperCase().includes(query) || String(item.name || '').toUpperCase().includes(query) || label.includes(query);
      })
      .sort((a, b) => b.total - a.total);
  }, [coverage, filterSymbol]);

  const uniqueSymbols = new Set(coverage.map((item) => item.symbol)).size;
  const coverageSymbolCount = coverage.length > 0 ? uniqueSymbols : null;
  const syncedTimeframes = Array.from(new Set(coverage.map((item) => item.timeframe || '1d')));
  const allTimeframes = TIMEFRAME_ORDER;
  const latestJob = jobs[0];
  const failedJobs = jobs.filter((job) => String(job.status) === 'failed').length;
  const databaseReady = status?.database === 'postgresql' || status?.status === 'ready';
  const dailyCoverageSymbols = new Set(coverage.filter((item) => (item.timeframe || '1d') === '1d' && Number(item.rows || 0) > 0).map((item) => item.symbol)).size;
  const healthScore = uniqueSymbols > 0 ? Math.round((dailyCoverageSymbols / uniqueSymbols) * 100) : null;
  const totalJobItems = jobs.reduce((sum, job) => sum + Number(job.total_items || 0), 0);
  const completedJobItems = jobs.reduce((sum, job) => sum + Number(job.completed_items || 0), 0);
  const failedJobItems = jobs.reduce((sum, job) => sum + Number(job.failed_items || 0), 0);
  const successRate = totalJobItems > 0 ? Math.round((completedJobItems / totalJobItems) * 100) : null;
  const coveredTimeframeCells = coverage.filter((item) => Number(item.rows || 0) > 0).length;
  const coverageGap = uniqueSymbols > 0 ? Math.max(0, uniqueSymbols * allTimeframes.length - coveredTimeframeCells) : null;
  const configuredSymbols = useMemo(() => {
    const names = new Map(coverage.map((item) => [item.symbol, item.name]));
    const configured = dataConfig?.defaultSymbols?.length
      ? dataConfig.defaultSymbols
      : symbols.split(',').map((item) => item.trim()).filter(Boolean);
    const source = configured.length ? configured : Array.from(new Set(coverage.map((item) => item.symbol)));
    return Array.from(new Set(source)).map((symbol) => ({ symbol, name: names.get(symbol) }));
  }, [coverage, dataConfig, symbols]);
  const catalogItems = useMemo(() => tushareCatalog?.items || [], [tushareCatalog]);
  const catalogModules = useMemo(() => {
    const groups = new Map<string, TushareEndpoint[]>();
    catalogItems.forEach((item) => {
      const rows = groups.get(item.module_code) || [];
      rows.push(item);
      groups.set(item.module_code, rows);
    });
    return Array.from(groups.entries()).map(([code, items]) => ({
      code,
      label: TUSHARE_MODULE_LABELS[code] || code,
      total: items.length,
      eligible: items.filter((item) => item.enabled).length,
      verified: items.filter((item) => ['available', 'available_empty'].includes(item.permission_state || '')).length,
    }));
  }, [catalogItems]);
  const visibleCatalogItems = useMemo(
    () => catalogItems.filter((item) => !catalogModule || item.module_code === catalogModule),
    [catalogItems, catalogModule],
  );
  const eligibleEndpointCount = catalogItems.filter((item) => item.enabled).length;
  const restrictedEndpointCount = catalogItems.filter((item) => item.baseline_state === 'restricted').length;
  const independentlyAuthorizedCount = catalogItems.filter((item) => item.requires_independent_authorization).length;
  const publishedDatasetCount = researchDatasets.filter((dataset) => dataset.partition_status === 'published').length;
  const blockingDatasetIssues = researchDatasets.reduce((sum, dataset) => sum + Number(dataset.blocking_issues || 0), 0);
  const sealedSnapshotCount = researchSnapshots.filter((snapshot) => snapshot.status === 'sealed').length;
  const latestSealedSnapshot = [...researchSnapshots]
    .filter((snapshot) => snapshot.status === 'sealed')
    .sort((left, right) => new Date(right.sealed_at || right.created_at).getTime() - new Date(left.sealed_at || left.created_at).getTime())[0];
  const researchFreshness = evaluateFreshness(latestSealedSnapshot?.knowledge_cutoff_at, 7 * 24 * 60 * 60 * 1000);
  const dailyBarsDataset = researchDatasets.find((dataset) => dataset.code === 'daily_bars');
  const researchReadiness = !latestSealedSnapshot
    ? { label: '研究快照未封存', tone: 'border-red-500/25 bg-red-500/10 text-red-200' }
    : researchFreshness.state === 'fresh'
      ? { label: '研究快照当前', tone: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200' }
      : { label: '研究快照历史', tone: 'border-yellow-500/25 bg-yellow-500/10 text-yellow-200' };
  const attentionItems = useMemo(() => {
    const items: Array<{ label: string; detail: string; section: DataSection; tone: 'red' | 'amber' }> = [];
    if (loadIssues.length) {
      items.push({ label: `${loadIssues.length} 个模块读取失败`, detail: loadIssues.join('、'), section: 'overview', tone: 'red' });
    }
    if (!databaseReady) {
      items.push({ label: '数据仓库不可用', detail: 'PostgreSQL 状态未就绪', section: 'overview', tone: 'red' });
    }
    if (!latestSealedSnapshot) {
      items.push({ label: '没有可用于研究的封存快照', detail: '因子与回测不应使用普通行情缓存替代', section: 'datasets', tone: 'red' });
    } else if (researchFreshness.state !== 'fresh') {
      items.push({ label: '研究快照已经陈旧', detail: `知识截止 ${compactDate(latestSealedSnapshot.knowledge_cutoff_at)}`, section: 'datasets', tone: 'amber' });
    }
    if (blockingDatasetIssues > 0) {
      items.push({ label: `${blockingDatasetIssues} 个质量问题阻断发布`, detail: '需要先处理数据集质量门禁', section: 'datasets', tone: 'red' });
    }
    if (dailyReferenceSchedule?.enabled && dailyReferenceSchedule.runtimeStatus !== 'running') {
      items.push({ label: '日终调度配置已启用，但运行器未在线', detail: '配置时间不会自动执行', section: 'datasets', tone: 'amber' });
    }
    if (failedJobs > 0 || failedJobItems > 0) {
      items.push({ label: `${failedJobs} 个同步任务失败`, detail: `失败任务项 ${format(failedJobItems)}`, section: 'jobs', tone: 'amber' });
    }
    return items;
  }, [
    blockingDatasetIssues,
    dailyReferenceSchedule,
    databaseReady,
    failedJobItems,
    failedJobs,
    latestSealedSnapshot,
    loadIssues,
    researchFreshness.state,
  ]);
  const primaryState = !databaseReady || !latestSealedSnapshot || blockingDatasetIssues > 0
    ? { label: '不可用于研究', tone: 'red' as const, detail: '先处理阻断项，再运行因子或回测' }
    : researchFreshness.state !== 'fresh'
      ? { label: '可用但已陈旧', tone: 'amber' as const, detail: '使用前建议更新并重新封存快照' }
      : { label: '研究数据可用', tone: 'green' as const, detail: '最近封存的研究数据可追溯' };

  useEffect(() => {
    if (!showAddSymbolDialog) return undefined;
    const query = addSymbolQuery.trim();
    setSelectedAddSymbol(null);
    if (!query) {
      setAddSymbolResults([]);
      setSearchingSymbol(false);
      return undefined;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setSearchingSymbol(true);
      searchStocks({ q: query, limit: 20 })
        .then((results) => {
          if (!cancelled) setAddSymbolResults(results);
        })
        .catch(() => {
          if (!cancelled) setAddSymbolResults([]);
        })
        .finally(() => {
          if (!cancelled) setSearchingSymbol(false);
        });
    }, 180);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [addSymbolQuery, showAddSymbolDialog]);

  const openScheduleDialog = () => {
    const cron = dailyReferenceSchedule?.cron || '30 17 * * 1-5';
    const parts = cron.trim().split(/\s+/);
    const minute = Number(parts[0] ?? 30);
    const hour = Number(parts[1] ?? 17);
    setScheduleEnabled(Boolean(dailyReferenceSchedule?.enabled ?? scheduleConfig?.enabled));
    setScheduleIntervalMinutes(Number(scheduleConfig?.intervalMinutes || 1440));
    setScheduleRunHour(Number.isFinite(hour) ? hour : 17);
    setScheduleRunMinute(Number.isFinite(minute) ? minute : 30);
    setScheduleHistoryDays(Number(scheduleConfig?.historyDays || defaultHistoryDays));
    setScheduleCatchupDays(Number(dailyReferenceSchedule?.catchupDays || 5));
    setShowScheduleDialog(true);
  };

  const openAddSymbolDialog = () => {
    setAddSymbolQuery('');
    setAddSymbolResults([]);
    setSelectedAddSymbol(null);
    setSyncAddedSymbolHistory(true);
    setShowAddSymbolDialog(true);
  };

  const openRemoveSymbolDialog = () => {
    setRemoveSymbolTarget(null);
    setShowRemoveSymbolDialog(true);
  };

  const openDeleteDataDialog = () => {
    setDeleteDataTarget(null);
    setShowDeleteDataDialog(true);
  };

  const saveSchedule = async () => {
    setSavingSchedule(true);
    setMessage('');
    try {
      const cron = `${Math.max(0, Math.min(59, Number(scheduleRunMinute)))} ${Math.max(0, Math.min(23, Number(scheduleRunHour)))} * * 1-5`;
      const saved = await updateDailyReferenceSchedule({
        enabled: scheduleEnabled,
        cron,
        timezone: 'Asia/Shanghai',
        catchupDays: Math.max(1, Math.min(10, Number(scheduleCatchupDays || 5))),
      });
      setDailyReferenceSchedule(saved);
      // Keep legacy JSON schedule aligned for older status cards, but PG schedule is authoritative.
      try {
        const legacy = await updateDataSchedule({
          enabled: scheduleEnabled,
          mode: 'all_ashare_daily',
          syncAllAshare: true,
          runHour: scheduleRunHour,
          runMinute: scheduleRunMinute,
          intervalMinutes: Math.max(5, Number(scheduleIntervalMinutes || 1440)),
          historyDays: Math.max(1, Number(scheduleHistoryDays || defaultHistoryDays)),
          symbols: [],
          timeframes: defaultTimeframes,
        });
        setScheduleConfig(legacy);
      } catch {
        // Legacy schedule is best-effort only.
      }
      setMessage(
        saved.runtimeStatus === 'running'
          ? '盘后日终计划已保存，调度器在线'
          : saved.enabled
            ? '盘后日终计划已保存（若运行器离线，请确认 ENABLE_SCHEDULER=true 并重启后端）'
            : '盘后日终计划已停用',
      );
      setShowScheduleDialog(false);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '定时同步保存失败');
    } finally {
      setSavingSchedule(false);
    }
  };

  const runDailyNow = async () => {
    setRunningDailyReference(true);
    setMessage('');
    try {
      const result = await runDailyReferenceSchedule({ force: true });
      setMessage(result.message || `日终编排已触发：${result.status || 'submitted'}`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '日终编排触发失败');
    } finally {
      setRunningDailyReference(false);
    }
  };

  const runFullMarketDownload = async () => {
    setSyncing(true);
    setMessage('');
    try {
      const result = await syncAllMarketHistory({
        history_days: 365,
        refresh_universe: true,
        include_signals: true,
        job_name: `market-1y-${Date.now()}`,
      });
      setMessage(
        result.message
          || `全市场下载已提交：${result.tradeDateCount || '?'} 个交易日（含信号回补）`,
      );
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '全市场下载提交失败');
    } finally {
      setSyncing(false);
    }
  };

  const addSelectedSymbol = async () => {
    if (!selectedAddSymbol) return;
    setAddingSymbol(true);
    setMessage('');
    try {
      const result = await addDataSymbol(selectedAddSymbol.code);
      const nextSymbols = result.defaultSymbols?.length
        ? result.defaultSymbols
        : Array.from(new Set([...configuredSymbols.map((item) => item.symbol), selectedAddSymbol.code]));
      setDataConfig((current) => ({
        defaultSymbols: nextSymbols,
        defaultTimeframes: current?.defaultTimeframes || defaultTimeframes,
        defaultHistoryDays: current?.defaultHistoryDays || defaultHistoryDays,
      }));
      setSymbols(nextSymbols.join(','));
      if (syncAddedSymbolHistory) {
        await startDataSync({
          symbols: [selectedAddSymbol.code],
          timeframes: defaultTimeframes,
          historyDays: defaultHistoryDays,
          jobName: `kline-add-${selectedAddSymbol.code}-${Date.now()}`,
        });
      }
      setShowAddSymbolDialog(false);
      await load();
      setMessage('股票已添加');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '股票添加失败');
    } finally {
      setAddingSymbol(false);
    }
  };

  const removeSelectedSymbol = async () => {
    if (!removeSymbolTarget) return;
    setRemovingSymbol(true);
    setMessage('');
    try {
      const result = await removeDataSymbol(removeSymbolTarget.symbol);
      const nextSymbols = result.defaultSymbols?.length
        ? result.defaultSymbols
        : configuredSymbols.map((item) => item.symbol).filter((symbol) => symbol !== removeSymbolTarget.symbol);
      setDataConfig((current) => ({
        defaultSymbols: nextSymbols,
        defaultTimeframes: current?.defaultTimeframes || defaultTimeframes,
        defaultHistoryDays: current?.defaultHistoryDays || defaultHistoryDays,
      }));
      setSymbols(nextSymbols.join(','));
      setShowRemoveSymbolDialog(false);
      await load();
      setMessage('股票已从后续同步名单移除');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '股票移除失败');
    } finally {
      setRemovingSymbol(false);
    }
  };

  const deleteSelectedData = async () => {
    if (!deleteDataTarget) return;
    setDeletingData(true);
    setMessage('');
    try {
      const result = await deleteDataKlines({ symbol: deleteDataTarget.symbol, timeframe: '1d' });
      setShowDeleteDataDialog(false);
      await load();
      setMessage(result.deleted > 0 ? '历史数据已删除' : '没有可删除的历史数据');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '历史数据删除失败');
    } finally {
      setDeletingData(false);
    }
  };

  const runSync = async (payload?: { symbols?: string[]; start_date?: string; end_date?: string; job_name?: string }) => {
    setSyncing(true);
    setMessage('');
    try {
      const result = await triggerDataSync({
        symbols: payload?.symbols || symbols.split(',').map((item) => item.trim()).filter(Boolean),
        timeframes: ['1d'],
        start_date: payload?.start_date || startDate,
        end_date: payload?.end_date || endDate,
        job_name: payload?.job_name,
      });
      setMessage(result.message || 'K线历史同步任务已提交');
      setShowSyncDialog(false);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '同步任务提交失败');
    } finally {
      setSyncing(false);
    }
  };

  const syncOne = (symbol: string, start = detailStartDate, end = detailEndDate) => {
    setSymbols(symbol);
    void runSync({ symbols: [symbol], start_date: start, end_date: end, job_name: `kline-sync-${symbol}-${Date.now()}` });
  };

  const probeBasicTushareAccess = async () => {
    setProbingEndpoint(true);
    setMessage('');
    try {
      const result = await probeTushareEndpoint('stock_basic', { fields: 'ts_code,name,market' });
      const refreshed = await getTushareEndpoints();
      setTushareCatalog(refreshed);
      setMessage(result.error_message || `TuShare 基础连接：${result.permission_state}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'TuShare 基础连接探测失败');
    } finally {
      setProbingEndpoint(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-5 overflow-y-auto bg-crypto-bg p-4 sm:p-6" data-operator-page="data">
      <div className="flex shrink-0 flex-col items-stretch gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-blue-600 shadow-lg shadow-blue-500/20">
            <Database className="h-5 w-5 text-white" />
          </div>
          <div className="min-w-0">
            <h1 className="whitespace-nowrap text-xl font-bold text-white">数据管理中心</h1>
            <p className="mt-0.5 text-xs text-gray-500">五个子区：总览 / 研究数据 / 行情覆盖 / 同步任务 / 数据源 · A股 · {format(coverageSymbolCount)} 个覆盖统计样本</p>
            {loading && (
              <div className="mt-1 flex items-center gap-1.5 text-xs text-blue-300">
                <RefreshCw className="h-3 w-3 animate-spin" />
                加载数据管理...
              </div>
            )}
          </div>
        </div>
        <div className="flex w-full items-center gap-2 overflow-x-auto pb-1 lg:w-auto lg:pb-0">
          <div className="group/data-help relative shrink-0">
            <button
              type="button"
              aria-label="查看数据同步说明"
              className="flex h-9 w-9 items-center justify-center rounded-lg border border-crypto-border bg-gray-800 text-blue-300 transition hover:bg-gray-700 hover:text-blue-200"
            >
              <Info className="h-4 w-4" />
            </button>
            <div className="pointer-events-none absolute right-0 top-11 z-30 w-[520px] max-w-[calc(100vw-3rem)] translate-y-1 rounded-xl border border-blue-500/25 bg-[#111827] p-4 text-xs leading-relaxed text-gray-400 opacity-0 shadow-2xl shadow-black/40 transition-all duration-150 group-hover/data-help:translate-y-0 group-hover/data-help:opacity-100 group-focus-within/data-help:translate-y-0 group-focus-within/data-help:opacity-100">
              <div className="space-y-1.5">
                <p><strong className="text-gray-200">全量下载</strong>：按交易日批量拉取全市场近一年日 K，并可回补市场证据信号。</p>
                <p><strong className="text-gray-200">盘后日终</strong>：PostgreSQL 计划 + APScheduler；工作日自动更新 K 线、参考数据与信号。</p>
                <p><strong className="text-gray-200">自定义同步</strong>：指定股票池和日期范围，提交后台任务。</p>
              </div>
            </div>
          </div>
          <button onClick={load} className="flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-crypto-border bg-gray-800 px-3 text-sm text-gray-400 transition hover:bg-gray-700 hover:text-white">
            <RefreshCw className={clsx('h-3.5 w-3.5', loading && 'animate-spin')} />
            刷新
          </button>
          <button
            type="button"
            onClick={openScheduleDialog}
            className={clsx('flex h-9 shrink-0 items-center gap-1.5 rounded-lg border px-4 text-sm font-medium transition-all', dailyReferenceSchedule?.enabled || scheduleConfig?.enabled ? 'border-emerald-500/35 bg-emerald-500/10 text-emerald-200' : isRunning ? 'border-blue-500/35 bg-blue-500/10 text-blue-200' : 'border-crypto-border bg-gray-800 text-gray-300 hover:bg-gray-700 hover:text-white')}
          >
            <span className="relative flex h-2.5 w-2.5 items-center justify-center">
              {(dailyReferenceSchedule?.enabled || scheduleConfig?.enabled || isRunning) && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />}
              <span className={clsx('relative inline-flex h-2 w-2 rounded-full', dailyReferenceSchedule?.runtimeStatus === 'running' ? 'bg-emerald-300' : dailyReferenceSchedule?.enabled || scheduleConfig?.enabled ? 'bg-amber-300' : isRunning ? 'bg-blue-300' : 'bg-gray-500')} />
            </span>
            <Clock className="h-3.5 w-3.5" />
            定时同步
          </button>
          <button
            type="button"
            onClick={() => void runDailyNow()}
            disabled={runningDailyReference || syncing}
            className="flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 text-sm font-semibold text-amber-200 transition hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {runningDailyReference ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
            立即运行日终
          </button>
          <button onClick={() => void runSync({ start_date: dateOffset(-7), end_date: dateOffset(0), job_name: `kline-incremental-${Date.now()}` })} disabled={syncing} className="flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 text-sm font-semibold text-blue-300 transition hover:bg-blue-500/20 disabled:cursor-not-allowed disabled:opacity-50">
            {syncing ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
            增量更新
          </button>
          <button onClick={() => setShowSyncDialog(true)} disabled={syncing} className="flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-purple-400/30 bg-purple-500/10 px-4 text-sm font-semibold text-purple-300 transition hover:bg-purple-500/20 disabled:cursor-not-allowed disabled:opacity-50">
            <Calendar className="h-3.5 w-3.5" />
            自定义同步
          </button>
          <button onClick={() => void runFullMarketDownload()} disabled={syncing} className="flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-4 text-sm font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50">
            <Play className="h-3.5 w-3.5" />
            全量下载
          </button>
        </div>
      </div>

      {message && <div className="shrink-0 rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-sm font-semibold text-blue-300">{message}</div>}
      {loadIssues.length > 0 && <div className="shrink-0 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm font-semibold text-red-200" role="alert">部分数据模块加载失败：{loadIssues.join('、')}</div>}

      <WorkspaceTabs<DataSection>
        ariaLabel="数据管理分区"
        items={[
          { id: 'overview', label: '总览', icon: LayoutDashboard, badge: attentionItems.length || undefined },
          { id: 'datasets', label: '研究数据', icon: Database },
          { id: 'coverage', label: '行情覆盖', icon: BarChart3 },
          { id: 'jobs', label: '同步任务', icon: ListChecks },
          { id: 'providers', label: '数据源', icon: Zap },
        ]}
        value={activeSection}
        onChange={setActiveSection}
      />

      {activeSection === 'overview' && (
        <>
      <DataPanel
        className="shrink-0 border-l-2 border-l-blue-500"
        title="当前数据结论"
        subtitle={primaryState.detail}
        actions={<StatusBadge tone={primaryState.tone}>{primaryState.label}</StatusBadge>}
      >
        {attentionItems.length === 0 ? (
          <div className="flex items-center gap-3 px-4 py-4 text-sm text-emerald-100">
            <CheckCircle className="h-5 w-5 text-emerald-400" />
            当前没有阻断项。数据仓库、研究快照和质量门禁均处于可用状态。
          </div>
        ) : (
          <div className="divide-y divide-crypto-border">
            {attentionItems.slice(0, 4).map((item) => (
              <button
                key={`${item.section}-${item.label}`}
                type="button"
                onClick={() => setActiveSection(item.section)}
                className="flex w-full items-start justify-between gap-4 px-4 py-3 text-left transition hover:bg-white/[0.025]"
              >
                <span className="flex min-w-0 items-start gap-3">
                  <AlertCircle className={clsx('mt-0.5 h-4 w-4 shrink-0', item.tone === 'red' ? 'text-red-400' : 'text-amber-400')} />
                  <span>
                    <span className="block text-sm font-semibold text-gray-100">{item.label}</span>
                    <span className="mt-0.5 block text-xs text-gray-400">{item.detail}</span>
                  </span>
                </span>
                <span className="shrink-0 text-xs font-semibold text-blue-300">查看</span>
              </button>
            ))}
            {attentionItems.length > 4 ? (
              <div className="px-4 py-2 text-xs text-gray-400">另有 {attentionItems.length - 4} 个待处理项</div>
            ) : null}
          </div>
        )}
      </DataPanel>

      <div className="shrink-0 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-white">关键指标</h2>
            <p className="mt-1 text-xs text-gray-400">只展示判断数据是否可用所需的核心信息。</p>
          </div>
          <div className={clsx('inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold', databaseReady ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200' : 'border-red-500/25 bg-red-500/10 text-red-200')}>
            {databaseReady ? <CheckCircle className="h-3.5 w-3.5" /> : <AlertCircle className="h-3.5 w-3.5" />}
            {databaseReady ? '数据仓库就绪' : '数据仓库异常'}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <OperatorMetricCard
            label="研究快照"
            value={latestSealedSnapshot ? '已封存' : '--'}
            icon={<Database className="h-4 w-4" />}
            tone={(latestSealedSnapshot ? (researchFreshness.state === 'fresh' ? 'green' : 'amber') : 'red') as MetricTone}
            detail={latestSealedSnapshot ? `知识截止 ${compactDate(latestSealedSnapshot.knowledge_cutoff_at)}` : '尚未封存，不能用于回测'}
          />
          <OperatorMetricCard
            label="日线数据"
            value={format(totalRows)}
            icon={<HardDrive className="h-4 w-4" />}
            tone="blue"
            detail={totalRowsLabel}
          />
          <OperatorMetricCard
            label="样本覆盖"
            value={healthScore === null ? '--' : `${healthScore}%`}
            icon={<TrendingUp className="h-4 w-4" />}
            tone={(healthScore === null ? 'blue' : healthScore >= 80 ? 'green' : healthScore >= 50 ? 'amber' : 'red') as MetricTone}
            detail={healthScore === null ? '尚无覆盖统计' : `${dailyCoverageSymbols}/${uniqueSymbols} 个统计样本有日线`}
          />
          <OperatorMetricCard
            label="同步任务"
            value={isRunning ? '运行中' : failedJobs > 0 ? `${failedJobs} 失败` : '空闲'}
            icon={<RefreshCw className={clsx('h-4 w-4', isRunning && 'animate-spin')} />}
            tone={(isRunning ? 'blue' : failedJobs > 0 ? 'red' : 'green') as MetricTone}
            detail={latestJob ? `${statusLabel(latestJob.status)} · ${compactDate(latestJob.finished_at || latestJob.created_at)}` : '暂无任务记录'}
          />
        </div>
      </div>

      <section className="shrink-0 rounded-xl border border-crypto-border bg-crypto-card p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-white">缓存同步质量诊断</h2>
            <p className="mt-1 text-xs text-gray-500">同步任务与覆盖样本仅说明缓存链路；回测可用性必须以封存研究快照为准。研究日线截止 {dailyBarsDataset?.end_date || '--'}。</p>
          </div>
          <span className={clsx('rounded-lg border px-3 py-1.5 text-xs font-semibold', researchReadiness.tone)}>
            {researchReadiness.label}
          </span>
        </div>
        <div className="grid gap-3 md:grid-cols-4">
          <div className="rounded-xl border border-crypto-border bg-crypto-bg/50 p-3">
            <div className="text-xs text-gray-500">缓存任务成功率</div>
            <div className={clsx('mt-1 text-xl font-bold tabular-nums', successRate === null ? 'text-gray-500' : successRate >= 95 ? 'text-emerald-300' : successRate >= 70 ? 'text-yellow-300' : 'text-red-300')}>{successRate === null ? '--' : `${successRate}%`}</div>
            <div className="mt-1 text-[10px] text-gray-600">{totalJobItems > 0 ? `${format(completedJobItems)} / ${format(totalJobItems)} 项` : '尚无任务项统计'}</div>
          </div>
          <div className="rounded-xl border border-crypto-border bg-crypto-bg/50 p-3">
            <div className="text-xs text-gray-500">失败项</div>
            <div className={clsx('mt-1 text-xl font-bold tabular-nums', failedJobItems > 0 ? 'text-red-300' : 'text-emerald-300')}>{format(failedJobItems)}</div>
            <div className="mt-1 text-[10px] text-gray-600">任务失败 {format(failedJobs)} 次</div>
          </div>
          <div className="rounded-xl border border-crypto-border bg-crypto-bg/50 p-3">
            <div className="text-xs text-gray-500">覆盖缺口</div>
            <div className={clsx('mt-1 text-xl font-bold tabular-nums', coverageGap === null ? 'text-gray-500' : coverageGap > 0 ? 'text-yellow-300' : 'text-emerald-300')}>{format(coverageGap)}</div>
            <div className="mt-1 text-[10px] text-gray-600">覆盖样本 × 7 周期（非研究快照）</div>
          </div>
          <div className="rounded-xl border border-crypto-border bg-crypto-bg/50 p-3">
            <div className="text-xs text-gray-500">最近任务</div>
            <div className="mt-1 truncate text-sm font-bold text-white">{latestJob?.job_name || '--'}</div>
            <div className="mt-1 text-[10px] text-gray-600">{statusLabel(latestJob?.status)} · {compactDate(latestJob?.finished_at || latestJob?.created_at)}</div>
          </div>
        </div>
      </section>
        </>
      )}

      {activeSection === 'providers' && (
      <section className="shrink-0 overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-crypto-border px-4 py-3">
          <div>
            <div className="text-[11px] font-black uppercase tracking-wider text-cyan-300">TuShare data access</div>
            <h2 className="mt-0.5 text-base font-semibold text-white">TuShare 数据接口</h2>
            <p className="mt-1 text-xs text-gray-500">按 A 股研究模块展示接口支持情况；目录支持不代表当前账户已经完成远端权限验证。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-lg border border-cyan-500/25 bg-cyan-500/10 px-3 py-1.5 text-xs font-semibold text-cyan-200">
              权限配置已加载
            </span>
            <button
              type="button"
              onClick={() => void probeBasicTushareAccess()}
              disabled={probingEndpoint}
              className="flex h-8 items-center gap-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 text-xs font-semibold text-blue-200 transition hover:bg-blue-500/20 disabled:cursor-not-allowed disabled:opacity-50"
              title="仅验证 stock_basic 的当前账户访问权限，不写入业务数据。"
            >
              <Zap className={clsx('h-3.5 w-3.5', probingEndpoint && 'animate-pulse')} />
              {probingEndpoint ? '检测中' : '检测基础连接'}
            </button>
          </div>
        </div>

        {!tushareCatalog ? (
          <div className="px-4 py-6 text-center text-sm text-gray-500">数据目录暂不可用；请检查本地后端和 PostgreSQL 连接。</div>
        ) : (
          <>
            <div className="grid gap-px border-b border-crypto-border bg-crypto-border sm:grid-cols-4">
              <div className="bg-crypto-card px-4 py-3">
                <div className="text-[11px] text-gray-500">目录端点</div>
                <div className="mt-1 text-xl font-bold tabular-nums font-mono text-blue-300">{format(catalogItems.length)}</div>
              </div>
              <div className="bg-crypto-card px-4 py-3">
                <div className="text-[11px] text-gray-500">当前目录支持</div>
                <div className="mt-1 text-xl font-bold tabular-nums text-emerald-300">{format(eligibleEndpointCount)}</div>
              </div>
              <div className="bg-crypto-card px-4 py-3">
                <div className="text-[11px] text-gray-500">权限受限扩展</div>
                <div className="mt-1 text-xl font-bold tabular-nums text-gray-300">{format(restrictedEndpointCount)}</div>
              </div>
              <div className="bg-crypto-card px-4 py-3">
                <div className="text-[11px] text-gray-500">需单独授权</div>
                <div className="mt-1 text-xl font-bold tabular-nums text-violet-300">{format(independentlyAuthorizedCount)}</div>
              </div>
            </div>

            <div className="flex gap-1 overflow-x-auto border-b border-crypto-border px-3 py-2">
              <button
                type="button"
                onClick={() => setCatalogModule('')}
                className={clsx('shrink-0 rounded-md px-2.5 py-1.5 text-xs transition', !catalogModule ? 'bg-blue-500/15 text-blue-200' : 'text-gray-500 hover:bg-white/5 hover:text-gray-300')}
              >
                全部 {catalogItems.length}
              </button>
              {catalogModules.map((module) => (
                <button
                  key={module.code}
                  type="button"
                  onClick={() => setCatalogModule(module.code)}
                  className={clsx('shrink-0 rounded-md px-2.5 py-1.5 text-xs transition', catalogModule === module.code ? 'bg-blue-500/15 text-blue-200' : 'text-gray-500 hover:bg-white/5 hover:text-gray-300')}
                >
                  {module.label} {module.total}
                </button>
              ))}
            </div>

            <div className="max-h-72 overflow-auto">
              <table className="w-full min-w-[900px] text-xs">
                <thead className="sticky top-0 z-10 bg-gray-900/95 text-gray-500 backdrop-blur">
                  <tr>
                    <th className="px-4 py-2 text-left font-medium">接口 / 模块</th>
                    <th className="px-4 py-2 text-left font-medium">调度与落库</th>
                    <th className="px-4 py-2 text-left font-medium">账户状态</th>
                    <th className="px-4 py-2 text-left font-medium">最近探测</th>
                    <th className="px-4 py-2 text-right font-medium">官方文档</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-crypto-border">
                  {visibleCatalogItems.map((endpoint) => {
                    const state = endpointState(endpoint);
                    return (
                      <tr key={endpoint.endpoint_code} className="text-gray-400 hover:bg-white/[0.025]">
                        <td className="px-4 py-2.5">
                          <div className="font-medium text-gray-200">{endpoint.display_name}</div>
                          <div className="mt-0.5 font-mono text-[10px] text-gray-600">{endpoint.endpoint_code} · {TUSHARE_MODULE_LABELS[endpoint.module_code] || endpoint.module_code}</div>
                        </td>
                        <td className="px-4 py-2.5">
                          <div>{endpoint.schedule_kind}</div>
                          <div className="mt-0.5 font-mono text-[10px] text-gray-600">{endpoint.storage_dataset}</div>
                        </td>
                        <td className="px-4 py-2.5">
                          <span className={clsx('inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold', state.tone)}>{state.label}</span>
                        </td>
                        <td className="max-w-[260px] px-4 py-2.5">
                          <div className="truncate text-[11px] text-gray-400" title={endpoint.error_message || undefined}>{endpoint.error_message || (endpoint.checked_at ? compactDate(endpoint.checked_at) : '尚未使用当前令牌探测')}</div>
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          <a href={endpoint.contract_url} target="_blank" rel="noreferrer" className="text-blue-300 transition hover:text-blue-200">查看</a>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
      )}

      {activeSection === 'datasets' && (
      <section className="shrink-0 overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-crypto-border px-4 py-3">
          <div>
            <div className="text-[11px] font-black uppercase tracking-wider text-emerald-300">Point-in-time research data</div>
            <h2 className="mt-0.5 text-base font-semibold text-white">回测数据快照与质量门禁</h2>
            <p className="mt-1 text-xs text-gray-500">只有封存快照可作为后续因子与回测输入；历史缓存尚未重新采集并通过门禁时，不会自动被视作可回测数据。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-3 py-1.5 font-semibold text-emerald-200">已发布数据集 {publishedDatasetCount}/{researchDatasets.length}</span>
            <span className={clsx('rounded-lg border px-3 py-1.5 font-semibold', blockingDatasetIssues ? 'border-red-500/25 bg-red-500/10 text-red-200' : 'border-crypto-border bg-crypto-bg text-gray-400')}>阻断问题 {blockingDatasetIssues}</span>
            <span className="rounded-lg border border-blue-500/25 bg-blue-500/10 px-3 py-1.5 font-semibold text-blue-200">已封存 {sealedSnapshotCount}</span>
          </div>
        </div>
        <div className="grid border-b border-crypto-border lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="max-h-64 overflow-auto border-b border-crypto-border lg:border-b-0 lg:border-r">
            <table className="w-full min-w-[720px] text-xs">
              <thead className="sticky top-0 z-10 bg-gray-900/95 text-gray-500 backdrop-blur">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">研究数据集</th>
                  <th className="px-4 py-2 text-left font-medium">来源优先级</th>
                  <th className="px-4 py-2 text-left font-medium">最新分区</th>
                  <th className="px-4 py-2 text-right font-medium">行 / 标的</th>
                  <th className="px-4 py-2 text-left font-medium">门禁状态</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-crypto-border">
                {researchDatasets.length === 0 ? (
                  <tr><td colSpan={5} className="px-4 py-5 text-center text-gray-500">本地 PG 尚未返回研究数据集注册表</td></tr>
                ) : researchDatasets.map((dataset) => {
                  const published = dataset.partition_status === 'published';
                  const blockers = Number(dataset.blocking_issues || 0);
                  return (
                    <tr key={dataset.code} className="text-gray-400 hover:bg-white/[0.025]">
                      <td className="px-4 py-2.5">
                        <div className="font-medium text-gray-200">{dataset.name}</div>
                        <div className="mt-0.5 font-mono text-[10px] text-gray-600">{dataset.code} · {dataset.schema_version}</div>
                      </td>
                      <td className="px-4 py-2.5"><span className="font-mono text-[11px] text-gray-300">{dataset.primary_source}</span><span className="px-1 text-gray-700">→</span><span className="font-mono text-[11px] text-gray-500">{dataset.fallback_source || '--'}</span><div className="mt-0.5 font-mono text-[10px] text-gray-600">实际 {dataset.actual_source || '--'}{dataset.fallback_reason ? ` · ${dataset.fallback_reason}` : ''}</div></td>
                      <td className="px-4 py-2.5">{dataset.end_date || '--'}<div className="mt-0.5 text-[10px] text-gray-600">{dataset.content_hash ? '内容已校验' : '未发布'}</div></td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-gray-300">{dataset.row_count ? format(dataset.row_count) : '--'} <span className="text-gray-600">/</span> {dataset.symbol_count ? format(dataset.symbol_count) : '--'}</td>
                      <td className="px-4 py-2.5"><span className={clsx('inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold', blockers ? 'border-red-500/25 bg-red-500/10 text-red-200' : published ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200' : 'border-gray-600 bg-gray-800 text-gray-400')}>{blockers ? `阻断 ${blockers}` : published ? '已发布' : '待采集'}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="max-h-64 overflow-auto p-3">
            <div className="mb-3 rounded-lg border border-blue-500/20 bg-blue-500/[0.045] p-2.5">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-blue-100"><Clock className="h-3.5 w-3.5 text-blue-300" />日终发布计划</div>
                <span className={clsx(
                  'rounded border px-1.5 py-0.5 text-[10px] font-semibold',
                  dailyReferenceSchedule?.runtimeStatus === 'running'
                    ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200'
                    : dailyReferenceSchedule
                      ? 'border-amber-500/25 bg-amber-500/10 text-amber-200'
                      : 'border-red-500/25 bg-red-500/10 text-red-200',
                )}>
                  {dailyReferenceSchedule?.runtimeStatus === 'running'
                    ? '运行中'
                    : dailyReferenceSchedule?.enabled
                      ? '配置已启用 · 运行器未启动'
                      : dailyReferenceSchedule?.configured === false
                        ? '未初始化'
                        : dailyReferenceSchedule
                          ? '已停用'
                          : '读取失败'}
                </span>
              </div>
              {dailyReferenceSchedule ? (
                <>
                  <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[10px] text-gray-500">
                    <div>计划 <span className="font-mono text-gray-300">{dailyReferenceSchedule.cron}</span></div>
                    <div>时区 <span className="font-mono text-gray-300">{dailyReferenceSchedule.timezone}</span></div>
                    <div>配置下次 <span className="text-gray-300">{compactDate(dailyReferenceSchedule.configuredNextRunAt ?? dailyReferenceSchedule.nextRunAt)}</span></div>
                    <div>有效下次 <span className="text-gray-300">{compactDate(dailyReferenceSchedule.effectiveNextRunAt)}</span></div>
                    <div>日线水位 <span className="font-mono text-gray-300">{dailyReferenceSchedule.dailyBarsWatermark || '--'}</span></div>
                  </div>
                  {dailyReferenceSchedule.configured === false ? <div className="mt-2 rounded border border-amber-500/15 bg-amber-500/[0.05] px-2 py-1.5 text-[10px] leading-relaxed text-amber-200">日终计划尚未初始化，请由管理员完成初始化后启用。</div> : null}
                  {dailyReferenceSchedule.enabled && dailyReferenceSchedule.runtimeStatus !== 'running' ? <div className="mt-2 rounded border border-amber-500/15 bg-amber-500/[0.05] px-2 py-1.5 text-[10px] leading-relaxed text-amber-200">PostgreSQL 中保存了启用配置，但当前后端进程没有在线调度任务；配置时间不会自动执行。</div> : null}
                  {dailyReferenceSchedule.lastRun && (
                    <div className="mt-2 space-y-1 border-t border-blue-500/15 pt-2 text-[10px] text-gray-500">
                      <div>最近 {dailyReferenceSchedule.lastRun.tradeDate} · <span className={dailyReferenceSchedule.lastRun.status === 'sealed' ? 'text-emerald-300' : dailyReferenceSchedule.lastRun.status === 'not_trading_day' ? 'text-amber-300' : 'text-red-300'}>{dailyReferenceSchedule.lastRun.status}</span> · 第 {dailyReferenceSchedule.lastRun.attemptCount} 次 · 完成 {compactDate(dailyReferenceSchedule.lastRun.finishedAt)}</div>
                      <div>研究数据 <span className="text-gray-300">{dailyReferenceSchedule.lastRun.snapshotId ?? lastPublication?.snapshot?.id ? '已封存' : '未生成'}</span> · 实际来源 <span className="font-mono text-gray-300">{lastPublication?.actual_source || '--'}</span>{lastPublication?.fallback_reason ? <span className="text-amber-300"> · 兜底 {lastPublication.fallback_reason}</span> : null}</div>
                      <div>因子 <span className={lastFactorSchedule?.status === 'sealed' ? 'text-emerald-300' : lastFactorSchedule?.status ? 'text-amber-300' : 'text-gray-600'}>{lastFactorSchedule?.status === 'sealed' ? '已封存' : lastFactorSchedule?.status || '--'}</span> · 市场证据 <span className="text-gray-300">{lastRunResult?.marketEvidence?.status || '--'}</span></div>
                    </div>
                  )}
                </>
              ) : <div className="mt-2 text-[10px] text-gray-600">日终计划状态暂不可用。</div>}
            </div>
            <div className="mb-2 flex items-center justify-between"><span className="text-xs font-semibold text-white">最近封存清单</span></div>
            {researchSnapshots.length === 0 ? (
              <div className="rounded-lg border border-dashed border-crypto-border bg-crypto-bg/40 p-3 text-xs leading-relaxed text-gray-500">尚无可用的数据快照，请先完成日线同步与质量检查。</div>
            ) : (
              <div className="space-y-2">
                {researchSnapshots.slice(0, 6).map((snapshot) => (
                  <div key={snapshot.id} className="rounded-lg border border-crypto-border bg-crypto-bg/50 p-2.5">
                    <div className="flex items-center justify-between gap-2"><span className="truncate text-[11px] text-gray-200">研究数据 · 截止 {compactDate(snapshot.knowledge_cutoff_at)}</span><span className={clsx('rounded border px-1.5 py-0.5 text-[10px]', snapshot.status === 'sealed' ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200' : 'border-gray-600 text-gray-400')}>{snapshot.status === 'sealed' ? '已封存' : snapshot.status}</span></div>
                    <div className="mt-1 text-[10px] text-gray-600">{snapshot.partition_count || 0} 分区 · 截止 {compactDate(snapshot.knowledge_cutoff_at)}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>
      )}

      {activeSection === 'jobs' && (
      <div className="shrink-0 overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
        <div className={clsx('flex items-stretch', jobHistoryExpanded && 'border-b border-crypto-border')}>
          <button
            type="button"
            onClick={() => setJobHistoryExpanded((expanded) => !expanded)}
            className="flex min-w-0 flex-1 items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-white/5"
            aria-expanded={jobHistoryExpanded}
          >
            <div className="flex min-w-0 items-center gap-2">
              <ListChecks className="h-4 w-4 shrink-0 text-emerald-400" />
              <span className="text-sm font-semibold text-white">同步任务明细</span>
              <span className="truncate text-xs text-gray-500">当前任务和最近历史任务 · {jobs.length} 条</span>
            </div>
            <span className="flex h-7 shrink-0 items-center gap-1 rounded-md border border-crypto-border bg-gray-800 px-2.5 text-[11px] text-gray-300">
              <ChevronDown className={clsx('h-3 w-3 transition-transform', jobHistoryExpanded && 'rotate-180')} />
              {jobHistoryExpanded ? '收起' : '展开'}
            </span>
          </button>
          <button onClick={load} className="flex shrink-0 items-center gap-1 border-l border-crypto-border px-4 py-3 text-xs text-gray-500 transition-colors hover:bg-white/5 hover:text-white">
            <RefreshCw className="h-3 w-3" />
            刷新
          </button>
        </div>
        {jobHistoryExpanded && (
          <div className="max-h-80 overflow-auto">
            <table className="w-full min-w-[980px] text-xs">
              <thead className="bg-gray-900/50 text-gray-500">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">操作时间</th>
                  <th className="px-4 py-2 text-left font-medium">状态</th>
                  <th className="px-4 py-2 text-left font-medium">任务</th>
                  <th className="px-4 py-2 text-left font-medium">数据时间段</th>
                  <th className="px-4 py-2 text-left font-medium">进度</th>
                  <th className="px-4 py-2 text-left font-medium">完成时间</th>
                  <th className="px-4 py-2 text-left font-medium">提示</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-crypto-border">
                {jobs.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-5 text-center text-gray-500">暂无同步任务记录</td>
                  </tr>
                ) : jobs.map((job) => {
                  const total = Number(job.total_items || 0);
                  const done = Number(job.completed_items || 0) + Number(job.failed_items || 0);
                  const progress = total ? Math.round((done / total) * 100) : 0;
                  return (
                    <tr key={job.id} className="text-gray-400">
                      <td className="px-4 py-3">{compactDate(job.created_at)}</td>
                      <td className="px-4 py-3">
                        <span className={clsx('inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold', statusTone(job.status))}>{statusLabel(job.status)}</span>
                      </td>
                      <td className="px-4 py-3 text-gray-300">
                        <div>{job.job_name || `任务 ${job.id}`}</div>
                        <div className="mt-0.5 text-[10px] text-gray-600">TuShare 优先 · 实际来源见快照分区</div>
                      </td>
                      <td className="px-4 py-3">{job.start_date || '--'} 至 {job.end_date || '--'}</td>
                      <td className="px-4 py-3">
                        <div className="mb-1 flex justify-between text-[10px] text-gray-500">
                          <span>{format(done)} / {format(total)}</span>
                          <span>{progress}%</span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-crypto-bg">
                          <div className="h-full rounded-full bg-blue-500" style={{ width: `${progress}%` }} />
                        </div>
                      </td>
                      <td className="px-4 py-3">{compactDate(job.finished_at)}</td>
                      <td className="px-4 py-3">{job.message || '--'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      )}

      {activeSection === 'datasets' && (
      <section className="shrink-0 overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-4 py-3">
          <div>
            <h2 className="text-base font-semibold text-white">数据表统计</h2>
            <p className="mt-1 text-xs text-gray-500">按表、标的和周期核对 K 线存储规模。</p>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="rounded-lg border border-blue-500/25 bg-blue-500/10 px-3 py-1.5 font-semibold text-blue-200">
              记录 {format(tableStats?.totalRecords || 0)}
            </span>
            <span className="rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-3 py-1.5 font-semibold text-emerald-200">
              组合 {format(tableStats?.totalPairs || 0)}
            </span>
          </div>
        </div>
        <div className="max-h-64 overflow-auto">
          <table className="w-full min-w-[860px] text-xs">
            <thead className="bg-gray-900/50 text-gray-500">
              <tr>
                <th className="px-4 py-2 text-left font-medium">数据表</th>
                <th className="px-4 py-2 text-left font-medium">标的</th>
                <th className="px-4 py-2 text-left font-medium">周期</th>
                <th className="px-4 py-2 text-right font-medium">记录数</th>
                <th className="px-4 py-2 text-left font-medium">覆盖时间</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-crypto-border">
              {!tableStats?.tables?.length ? (
                <tr>
                  <td colSpan={5} className="px-4 py-5 text-center text-gray-500">暂无表统计数据</td>
                </tr>
              ) : tableStats.tables.slice(0, 12).map((item, index) => (
                <tr key={`${item.tableName}-${item.symbol || index}-${item.timeframe || '1d'}`} className="text-gray-400">
                  <td className="px-4 py-3 font-mono text-gray-200">{item.tableName}</td>
                  <td className="px-4 py-3">
                    {item.symbol ? (
                      <div>
                        <div className="font-medium text-gray-100">
                          {resolveSymbolName(
                            item.symbol,
                            item.name || symbolNameMap.get(item.symbol),
                          ) || '未命名'}
                        </div>
                        <div className="mt-0.5 font-mono text-[10px] text-gray-500">
                          {toPublicSymbol(item.symbol)}
                        </div>
                      </div>
                    ) : (
                      '--'
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={clsx('inline-flex rounded border px-2 py-0.5 text-[10px] font-semibold', TIMEFRAME_BADGE[item.timeframe || '1d'] || TIMEFRAME_BADGE['1d'])}>
                      {TIMEFRAME_LABELS[item.timeframe || '1d'] || item.timeframe || '1D'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-semibold tabular-nums text-blue-300">{format(item.recordCount)}</td>
                  <td className="px-4 py-3 text-gray-500">
                    {item.firstTimestamp ? new Date(item.firstTimestamp).toISOString().slice(0, 10) : '--'}
                    <span className="px-1 text-gray-700">至</span>
                    {item.lastTimestamp ? new Date(item.lastTimestamp).toISOString().slice(0, 10) : '--'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      )}

      {activeSection === 'coverage' && (
      <section className="shrink-0 rounded-2xl border border-crypto-border bg-crypto-card/45 p-3 shadow-inner shadow-black/20" aria-label="A股数据维护面板">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3 px-1">
          <div>
            <div className="text-[11px] font-black uppercase tracking-wider text-blue-300">A股数据维护面板</div>
            <h2 className="text-base font-semibold text-white">同步覆盖矩阵</h2>
            <p className="mt-1 text-xs text-gray-500">按标的聚合历史 K 线，展开后可按周期查看起止日期、覆盖率和同步入口。</p>
          </div>
          <span className="rounded-lg border border-crypto-border bg-crypto-bg px-3 py-1.5 text-xs text-gray-400">历史数据存储：kline_history</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative shrink-0">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
            <input
              type="text"
              placeholder="搜索股票..."
              value={filterSymbol}
              onChange={(event) => setFilterSymbol(event.target.value)}
              className="h-9 w-44 rounded-lg border border-crypto-border bg-gray-800 pl-9 pr-3 text-sm text-white placeholder-gray-600 outline-none transition focus:border-blue-500"
            />
          </div>
          <div className="flex items-center gap-1 rounded-lg border border-crypto-border bg-crypto-card p-1">
            <button
              onClick={() => setFilterTf('')}
              className={clsx('rounded-md px-3 py-1 text-xs font-medium transition', !filterTf ? 'bg-blue-500/20 text-blue-300' : 'text-gray-400 hover:text-white')}
            >
              全部
            </button>
            {allTimeframes.map((timeframe) => (
              <button
                key={timeframe}
                onClick={() => setFilterTf(filterTf === timeframe ? '' : timeframe)}
                className={clsx(
                  'rounded-md px-3 py-1 text-xs font-medium transition',
                  filterTf === timeframe ? 'bg-blue-500/20 text-blue-300' : 'text-gray-400 hover:text-white',
                  !syncedTimeframes.includes(timeframe) && 'opacity-55',
                )}
              >
                {TIMEFRAME_LABELS[timeframe] || timeframe}
              </button>
            ))}
          </div>
          <div className="flex-1" />
          <button
            type="button"
            onClick={openAddSymbolDialog}
            className="flex h-9 items-center gap-1.5 rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-3 text-xs font-semibold text-emerald-200 transition hover:bg-emerald-500/20"
          >
            <Plus className="h-3.5 w-3.5" />
            增加股票
          </button>
          <button
            type="button"
            onClick={openRemoveSymbolDialog}
            className="flex h-9 items-center gap-1.5 rounded-lg border border-red-500/25 bg-red-500/10 px-3 text-xs font-semibold text-red-200 transition hover:bg-red-500/20"
          >
            <Trash2 className="h-3.5 w-3.5" />
            删除股票
          </button>
          <button
            type="button"
            onClick={openDeleteDataDialog}
            className="flex h-9 items-center gap-1.5 rounded-lg border border-orange-500/25 bg-orange-500/10 px-3 text-xs font-semibold text-orange-200 transition hover:bg-orange-500/20"
          >
            <Trash2 className="h-3.5 w-3.5" />
            删除数据
          </button>
          <span className="text-xs text-gray-500">当前显示 A股 · 共 {groupedCoverage.length} 个标的</span>
        </div>

        <div className="mt-3 flex max-h-[52vh] min-h-[320px] flex-col overflow-hidden rounded-xl border border-crypto-border bg-crypto-bg/35">
          <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-2.5 pr-3">
            {groupedCoverage.length === 0 ? (
              <div className="flex h-full min-h-64 items-center justify-center text-sm text-gray-500">暂无匹配的数据标的</div>
            ) : groupedCoverage.map((group) => {
              const isExpanded = expandedSymbol === group.symbol;
              const rowsByTf = new Map(group.rows.map((item) => [item.timeframe || '1d', item]));
              const displayTimeframes = filterTf ? allTimeframes.filter((timeframe) => timeframe === filterTf) : allTimeframes;
              const filledTimeframes = allTimeframes.filter((timeframe) => Number(rowsByTf.get(timeframe)?.rows || 0) > 0).length;
              const groupLabel = formatSymbolLabel(group.symbol, group.name);
              const groupName = resolveSymbolName(group.symbol, group.name);
              return (
                <div key={group.symbol} className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card transition-all hover:border-gray-600">
                  <div className="flex cursor-pointer select-none items-center gap-5 px-5 py-3.5" onClick={() => setExpandedSymbol(isExpanded ? null : group.symbol)}>
                    <div className="flex w-56 shrink-0 items-center gap-3">
                      <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-blue-500/30 bg-blue-500/15 text-xs font-bold text-blue-200">
                        {group.symbol.slice(0, 2)}
                      </div>
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-white" title={groupLabel}>
                          {groupName || '未命名'}
                        </div>
                        <div className="truncate font-mono text-[10px] text-gray-500">
                          {toPublicSymbol(group.symbol)} · A股历史 K 线
                        </div>
                      </div>
                    </div>

                    <div className="flex min-w-0 flex-1 flex-nowrap gap-2.5 overflow-x-auto">
                      {displayTimeframes.map((timeframe) => {
                        const item = rowsByTf.get(timeframe);
                        const itemPercent = item ? coveragePercent(item) : 0;
                        const hasData = Number(item?.rows || 0) > 0;
                        return (
                          <div
                            key={`${group.symbol}-${timeframe}`}
                            className={clsx(
                              'min-w-[120px] flex-1 basis-0 rounded-lg border px-3 py-2 bg-gradient-to-br transition-all',
                              hasData ? TIMEFRAME_COLORS[timeframe] || 'from-blue-500/10 border-blue-500/20' : 'from-transparent to-transparent border-crypto-border opacity-70',
                            )}
                          >
                            <div className="mb-1 flex items-center justify-between">
                              <span className={clsx('text-[10px] font-medium', hasData ? 'text-white/70' : 'text-gray-600')}>{TIMEFRAME_LABELS[timeframe] || timeframe}</span>
                              <span className={clsx('text-[10px]', hasData ? itemPercent >= 80 ? 'text-emerald-300' : itemPercent >= 50 ? 'text-yellow-300' : 'text-red-300' : 'text-gray-700')}>{hasData ? `${itemPercent}%` : '-'}</span>
                            </div>
                            <div className={clsx('text-xs font-bold tabular-nums', hasData ? 'text-blue-300' : 'text-gray-600')}>{hasData ? format(item?.rows) : '-'}</div>
                            <div className="mt-1.5 h-0.5 overflow-hidden rounded-full bg-white/5">
                              <div className={clsx('h-full rounded-full', itemPercent >= 80 ? 'bg-emerald-400' : itemPercent >= 50 ? 'bg-yellow-400' : 'bg-red-400')} style={{ width: `${itemPercent}%` }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>

                    <div className="flex w-44 shrink-0 items-center justify-end gap-3">
                      <div className="text-right">
                        <div className="text-xs text-gray-500">{filledTimeframes}/{allTimeframes.length} 周期</div>
                        <div className="text-sm font-bold tabular-nums text-blue-300">{format(group.total)}</div>
                      </div>
                      <ChevronDown className={clsx('h-4 w-4 text-gray-500 transition-transform', isExpanded && 'rotate-180')} />
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="border-t border-crypto-border bg-crypto-bg/50 px-5 py-4">
                      <div className="mb-4 flex items-center gap-3 border-b border-crypto-border pb-3">
                        <Calendar className="h-3.5 w-3.5 text-gray-500" />
                        <span className="text-xs text-gray-500">同步范围:</span>
                        <input type="date" value={detailStartDate} onChange={(event) => setDetailStartDate(event.target.value)} className="h-7 rounded-md border border-crypto-border bg-gray-800 px-2 text-xs text-white outline-none focus:border-blue-500" />
                        <span className="text-xs text-gray-600">~</span>
                        <input type="date" value={detailEndDate} onChange={(event) => setDetailEndDate(event.target.value)} className="h-7 rounded-md border border-crypto-border bg-gray-800 px-2 text-xs text-white outline-none focus:border-blue-500" />
                        {[['1月', 30], ['3月', 90], ['半年', 180], ['1年', 365]].map(([label, days]) => (
                          <button
                            key={String(days)}
                            onClick={() => {
                              setDetailStartDate(dateOffset(-Number(days)));
                              setDetailEndDate(dateOffset(0));
                            }}
                            className="rounded border border-crypto-border bg-gray-800 px-2 py-0.5 text-[10px] text-gray-500 transition hover:bg-gray-700 hover:text-white"
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                      <div className={clsx('grid gap-3', displayTimeframes.length <= 5 ? 'md:grid-cols-5' : 'md:grid-cols-7')}>
                        {displayTimeframes.map((timeframe) => {
                          const item = rowsByTf.get(timeframe);
                          const itemPercent = item ? coveragePercent(item) : 0;
                          const hasData = Number(item?.rows || 0) > 0;
                          const enabled = timeframe === '1d';
                          return (
                            <div
                              key={`${group.symbol}-${timeframe}-detail`}
                              className={clsx(
                                'rounded-xl border bg-gradient-to-br p-3',
                                hasData ? TIMEFRAME_COLORS[timeframe] || 'from-blue-500/10 border-blue-500/20' : 'from-crypto-card to-transparent border-crypto-border',
                              )}
                            >
                              <div className="mb-2 flex items-center justify-between">
                                <span className={clsx('rounded border px-2 py-0.5 text-[10px] font-medium', TIMEFRAME_BADGE[timeframe])}>{TIMEFRAME_LABELS[timeframe] || timeframe}</span>
                                {!enabled ? <Clock className="h-3.5 w-3.5 text-gray-500" /> : item?.status === 'failed' ? <AlertCircle className="h-3.5 w-3.5 text-red-400" /> : hasData ? <CheckCircle className="h-3.5 w-3.5 text-emerald-400" /> : <Clock className="h-3.5 w-3.5 text-gray-500" />}
                              </div>
                              <div className="space-y-2">
                                <div className={clsx('text-lg font-bold tabular-nums', hasData ? 'text-blue-300' : 'text-gray-600')}>{hasData ? format(item?.rows) : '-'}</div>
                                <div className="space-y-1 text-[10px] text-gray-500">
                                  <div className="flex justify-between"><span>起始</span><span className="text-white/70">{item?.first_date || '--'}</span></div>
                                  <div className="flex justify-between"><span>结束</span><span className="text-white/70">{item?.last_date || '--'}</span></div>
                                  <div className="flex justify-between"><span>同步于</span><span className="text-white/50">{compactDate(item?.last_sync_at)}</span></div>
                                </div>
                                <div>
                                  <div className="mb-0.5 flex items-center justify-between text-[10px]">
                                    <span className="text-gray-500">覆盖率</span>
                                    <span className={clsx('font-mono tabular-nums', itemPercent >= 80 ? 'text-emerald-300' : itemPercent >= 50 ? 'text-amber-300' : 'text-red-300')}>{itemPercent}%</span>
                                  </div>
                                  <div className="h-1 overflow-hidden rounded-full bg-white/5">
                                    <div className={clsx('h-full rounded-full', itemPercent >= 80 ? 'bg-emerald-400' : itemPercent >= 50 ? 'bg-yellow-400' : 'bg-red-400')} style={{ width: `${itemPercent}%` }} />
                                  </div>
                                </div>
                                <div className="flex gap-1">
                                  <button onClick={() => syncOne(group.symbol, dateOffset(-7), dateOffset(0))} disabled={syncing || !enabled} className="flex flex-1 items-center justify-center gap-1 rounded-md border border-crypto-border bg-white/5 py-1 text-[10px] text-gray-400 transition hover:bg-white/10 hover:text-white disabled:opacity-30">
                                    {syncing ? <RefreshCw className="h-3 w-3 animate-spin" /> : null}
                                    增量
                                  </button>
                                  <button onClick={() => syncOne(group.symbol)} disabled={syncing || !enabled} className="flex-1 rounded-md border border-purple-500/20 bg-purple-500/10 py-1 text-[10px] text-purple-300 transition hover:bg-purple-500/20 hover:text-purple-200 disabled:opacity-30">
                                    按日期
                                  </button>
                                </div>
                                {!enabled && <div className="rounded-md border border-crypto-border bg-crypto-bg/60 px-2 py-1 text-[10px] text-gray-600">V1 未启用</div>}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </section>
      )}

      {showScheduleDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <section className="w-full max-w-xl overflow-hidden rounded-2xl border border-emerald-500/30 bg-crypto-card shadow-2xl shadow-black/50">
            <div className="flex items-center justify-between border-b border-emerald-500/20 px-6 py-4">
              <div>
                <h2 className="text-base font-semibold text-white">盘后日终计划</h2>
                <div className="mt-0.5 text-xs text-gray-500">写入 PostgreSQL 日终编排计划，交易日收盘后自动更新全市场 K 线与信号。</div>
              </div>
              <button onClick={() => setShowScheduleDialog(false)} className="rounded-lg border border-crypto-border p-2 text-gray-500 hover:text-white" aria-label="关闭定时同步设置">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-4 p-6">
              <label className="flex items-center justify-between rounded-xl border border-crypto-border bg-crypto-bg/55 px-4 py-3">
                <span>
                  <span className="block text-sm font-semibold text-white">启用盘后自动更新</span>
                  <span className="mt-0.5 block text-xs text-gray-500">工作日按 cron 触发；需 ENABLE_SCHEDULER=true。</span>
                </span>
                <input
                  type="checkbox"
                  checked={scheduleEnabled}
                  onChange={(event) => setScheduleEnabled(event.target.checked)}
                  className="h-5 w-5 rounded border-crypto-border bg-gray-800 text-emerald-500 focus:ring-emerald-500"
                />
              </label>
              <div className="grid gap-4 md:grid-cols-3">
                <label className="block">
                  <span className="mb-2 block text-xs text-gray-400">执行小时</span>
                  <input
                    type="number"
                    min={0}
                    max={23}
                    value={scheduleRunHour}
                    onChange={(event) => setScheduleRunHour(Number(event.target.value))}
                    className="h-11 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none focus:border-emerald-500"
                  />
                </label>
                <label className="block">
                  <span className="mb-2 block text-xs text-gray-400">执行分钟</span>
                  <input
                    type="number"
                    min={0}
                    max={59}
                    value={scheduleRunMinute}
                    onChange={(event) => setScheduleRunMinute(Number(event.target.value))}
                    className="h-11 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none focus:border-emerald-500"
                  />
                </label>
                <label className="block">
                  <span className="mb-2 block text-xs text-gray-400">回补交易日数</span>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={scheduleCatchupDays}
                    onChange={(event) => setScheduleCatchupDays(Number(event.target.value))}
                    className="h-11 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none focus:border-emerald-500"
                  />
                </label>
              </div>
              <div className="rounded-xl border border-crypto-border bg-crypto-bg/45 p-3 text-xs text-gray-500">
                <div className="font-semibold text-gray-300">计划摘要</div>
                <div className="mt-1">cron：<span className="font-mono text-gray-300">{scheduleRunMinute} {scheduleRunHour} * * 1-5</span>（Asia/Shanghai，工作日）</div>
                <div className="mt-1">同步内容：全市场日 K（按交易日批量）+ 参考数据/市场证据/因子日终编排。</div>
                <div className="mt-1">运行器状态：<span className="text-gray-300">{dailyReferenceSchedule?.runtimeStatus || 'unknown'}</span>
                  {dailyReferenceSchedule?.effectiveNextRunAt ? ` · 下次 ${compactDate(dailyReferenceSchedule.effectiveNextRunAt)}` : ''}
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-2 border-t border-crypto-border px-6 py-4">
              <button onClick={() => setShowScheduleDialog(false)} className="rounded-xl border border-crypto-border px-4 py-2 text-sm font-semibold text-gray-400 hover:text-gray-200">取消</button>
              <button onClick={() => void saveSchedule()} disabled={savingSchedule} className="flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50">
                {savingSchedule ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Clock className="h-4 w-4" />}
                保存设置
              </button>
            </div>
          </section>
        </div>
      )}

      {showAddSymbolDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <section className="w-full max-w-2xl overflow-hidden rounded-2xl border border-emerald-500/30 bg-crypto-card shadow-2xl shadow-black/50">
            <div className="flex items-center justify-between border-b border-emerald-500/20 px-6 py-4">
              <div>
                <h2 className="text-base font-semibold text-white">增加股票</h2>
                <div className="mt-0.5 text-xs text-gray-500">搜索 A股代码或名称，加入默认同步股票池。</div>
              </div>
              <button onClick={() => setShowAddSymbolDialog(false)} className="rounded-lg border border-crypto-border p-2 text-gray-500 hover:text-white" aria-label="关闭增加股票">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-4 p-6">
              <label className="block">
                <span className="mb-2 block text-xs text-gray-400">股票搜索</span>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                  <input
                    value={addSymbolQuery}
                    onChange={(event) => setAddSymbolQuery(event.target.value)}
                    placeholder="搜索股票代码或名称..."
                    className="h-11 w-full rounded-lg border border-crypto-border bg-crypto-bg pl-10 pr-3 text-sm text-white placeholder-gray-600 outline-none focus:border-emerald-500"
                  />
                </div>
              </label>
              <div className="max-h-60 overflow-y-auto rounded-xl border border-crypto-border bg-crypto-bg/45 p-2">
                {searchingSymbol ? (
                  <div className="flex items-center gap-2 px-3 py-5 text-sm text-gray-500">
                    <RefreshCw className="h-4 w-4 animate-spin" />
                    搜索中...
                  </div>
                ) : addSymbolResults.length === 0 ? (
                  <div className="px-3 py-5 text-sm text-gray-500">{addSymbolQuery.trim() ? '暂无匹配股票' : '输入关键词开始搜索'}</div>
                ) : addSymbolResults.map((candidate) => {
                  const active = selectedAddSymbol?.code === candidate.code;
                  return (
                    <button
                      key={candidate.code}
                      type="button"
                      onClick={() => setSelectedAddSymbol(candidate)}
                      className={clsx('mb-2 flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left transition last:mb-0', active ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-100' : 'border-crypto-border bg-gray-800/60 text-gray-300 hover:border-gray-600 hover:text-white')}
                    >
                      <span className="text-sm font-semibold">{formatSymbolLabel(candidate.code, candidate.name || undefined)}</span>
                      <span className="text-xs text-gray-500">A股</span>
                    </button>
                  );
                })}
              </div>
              <label className="flex items-center gap-3 rounded-xl border border-crypto-border bg-crypto-bg/45 px-4 py-3 text-sm text-gray-300">
                <input
                  type="checkbox"
                  checked={syncAddedSymbolHistory}
                  onChange={(event) => setSyncAddedSymbolHistory(event.target.checked)}
                  className="h-4 w-4 rounded border-crypto-border bg-gray-800 text-emerald-500 focus:ring-emerald-500"
                />
                添加后同步历史数据
              </label>
            </div>
            <div className="flex justify-end gap-2 border-t border-crypto-border px-6 py-4">
              <button onClick={() => setShowAddSymbolDialog(false)} className="rounded-xl border border-crypto-border px-4 py-2 text-sm font-semibold text-gray-400 hover:text-gray-200">取消</button>
              <button onClick={() => void addSelectedSymbol()} disabled={!selectedAddSymbol || addingSymbol} className="flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50">
                {addingSymbol ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                添加
              </button>
            </div>
          </section>
        </div>
      )}

      {showRemoveSymbolDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <section className="w-full max-w-2xl overflow-hidden rounded-2xl border border-red-500/30 bg-crypto-card shadow-2xl shadow-black/50">
            <div className="flex items-center justify-between border-b border-red-500/20 px-6 py-4">
              <div>
                <h2 className="text-base font-semibold text-white">删除股票</h2>
                <div className="mt-0.5 text-xs text-gray-500">从默认同步股票池移除，不会清空已写入的历史 K 线。</div>
              </div>
              <button onClick={() => setShowRemoveSymbolDialog(false)} className="rounded-lg border border-crypto-border p-2 text-gray-500 hover:text-white" aria-label="关闭删除股票">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-4 p-6">
              <div className="max-h-72 overflow-y-auto rounded-xl border border-crypto-border bg-crypto-bg/45 p-2">
                {configuredSymbols.length === 0 ? (
                  <div className="px-3 py-5 text-sm text-gray-500">暂无可移除股票</div>
                ) : configuredSymbols.map((item) => {
                  const active = removeSymbolTarget?.symbol === item.symbol;
                  return (
                    <button
                      key={item.symbol}
                      type="button"
                      onClick={() => setRemoveSymbolTarget(item)}
                      className={clsx('mb-2 flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left transition last:mb-0', active ? 'border-red-500/40 bg-red-500/15 text-red-100' : 'border-crypto-border bg-gray-800/60 text-gray-300 hover:border-gray-600 hover:text-white')}
                    >
                      <span className="text-sm font-semibold">{formatSymbolLabel(item.symbol, item.name || undefined)}</span>
                      <span className="text-xs text-gray-500">默认同步</span>
                    </button>
                  );
                })}
              </div>
              {removeSymbolTarget && (
                <div className="rounded-xl border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-100">
                  将移除 {formatSymbolLabel(removeSymbolTarget.symbol, removeSymbolTarget.name || undefined)}
                </div>
              )}
            </div>
            <div className="flex justify-end gap-2 border-t border-crypto-border px-6 py-4">
              <button onClick={() => setShowRemoveSymbolDialog(false)} className="rounded-xl border border-crypto-border px-4 py-2 text-sm font-semibold text-gray-400 hover:text-gray-200">取消</button>
              <button onClick={() => void removeSelectedSymbol()} disabled={!removeSymbolTarget || removingSymbol} className="flex items-center gap-2 rounded-xl bg-red-600 px-5 py-2 text-sm font-semibold text-white hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-50">
                {removingSymbol ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                移除
              </button>
            </div>
          </section>
        </div>
      )}

      {showDeleteDataDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <section className="w-full max-w-2xl overflow-hidden rounded-2xl border border-orange-500/30 bg-crypto-card shadow-2xl shadow-black/50">
            <div className="flex items-center justify-between border-b border-orange-500/20 px-6 py-4">
              <div>
                <h2 className="text-base font-semibold text-white">删除历史数据</h2>
                <div className="mt-0.5 text-xs text-gray-500">清空所选标的的 1D K线缓存，股票仍保留在默认同步名单中。</div>
              </div>
              <button onClick={() => setShowDeleteDataDialog(false)} className="rounded-lg border border-crypto-border p-2 text-gray-500 hover:text-white" aria-label="关闭删除历史数据">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-4 p-6">
              <div className="max-h-72 overflow-y-auto rounded-xl border border-crypto-border bg-crypto-bg/45 p-2">
                {groupedCoverage.length === 0 ? (
                  <div className="px-3 py-5 text-sm text-gray-500">暂无可删除数据</div>
                ) : groupedCoverage.map((item) => {
                  const active = deleteDataTarget?.symbol === item.symbol;
                  return (
                    <button
                      key={`delete-${item.symbol}`}
                      type="button"
                      onClick={() => setDeleteDataTarget({ symbol: item.symbol, name: item.name })}
                      className={clsx('mb-2 flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left transition last:mb-0', active ? 'border-orange-500/40 bg-orange-500/15 text-orange-100' : 'border-crypto-border bg-gray-800/60 text-gray-300 hover:border-gray-600 hover:text-white')}
                    >
                      <span>
                        <span className="block text-sm font-semibold">{formatSymbolLabel(item.symbol, item.name)}</span>
                        <span className="mt-0.5 block text-[10px] text-gray-500">已存 {format(item.total)} 条</span>
                      </span>
                      <span className="text-xs text-gray-500">1D</span>
                    </button>
                  );
                })}
              </div>
              {deleteDataTarget && (
                <div className="rounded-xl border border-orange-500/25 bg-orange-500/10 px-4 py-3 text-sm text-orange-100">
                  将删除 {formatSymbolLabel(deleteDataTarget.symbol, deleteDataTarget.name || undefined)} 的历史 K线缓存
                </div>
              )}
            </div>
            <div className="flex justify-end gap-2 border-t border-crypto-border px-6 py-4">
              <button onClick={() => setShowDeleteDataDialog(false)} className="rounded-xl border border-crypto-border px-4 py-2 text-sm font-semibold text-gray-400 hover:text-gray-200">取消</button>
              <button onClick={() => void deleteSelectedData()} disabled={!deleteDataTarget || deletingData} className="flex items-center gap-2 rounded-xl bg-orange-600 px-5 py-2 text-sm font-semibold text-white hover:bg-orange-500 disabled:cursor-not-allowed disabled:opacity-50">
                {deletingData ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                确认删除数据
              </button>
            </div>
          </section>
        </div>
      )}

      {showSyncDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <section className="w-full max-w-3xl overflow-hidden rounded-2xl border border-purple-500/35 bg-crypto-card shadow-2xl shadow-black/50">
            <div className="flex items-center justify-between border-b border-purple-500/25 px-6 py-4">
              <div>
                <div className="text-base font-semibold text-white">同步配置 · 自定义同步</div>
                <div className="mt-0.5 text-xs text-gray-500">设置股票池和历史区间后开始同步。</div>
              </div>
              <button onClick={() => setShowSyncDialog(false)} className="rounded-lg border border-crypto-border p-2 text-gray-500 hover:text-white" aria-label="关闭同步配置">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-4 p-6">
              <label className="block">
                <span className="mb-2 block text-xs text-gray-400">同步标的</span>
                <input value={symbols} onChange={(event) => setSymbols(event.target.value)} className="h-11 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none focus:border-purple-500" />
              </label>
              <div className="grid gap-4 md:grid-cols-2">
                <label className="block">
                  <span className="mb-2 block text-xs text-gray-400">开始日期</span>
                  <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} className="h-11 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none focus:border-purple-500" />
                </label>
                <label className="block">
                  <span className="mb-2 block text-xs text-gray-400">结束日期</span>
                  <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} className="h-11 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none focus:border-purple-500" />
                </label>
              </div>
              <div>
                <div className="mb-2 text-xs text-gray-400">同步粒度</div>
                <span className="inline-flex rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs font-semibold text-blue-300">1D 日线</span>
              </div>
            </div>
            <div className="flex justify-end gap-2 border-t border-crypto-border px-6 py-4">
              <button onClick={() => setShowSyncDialog(false)} className="rounded-xl border border-crypto-border px-4 py-2 text-sm font-semibold text-gray-400 hover:text-gray-200">取消</button>
              <button onClick={() => void runSync({ job_name: `kline-custom-${Date.now()}` })} disabled={syncing} className="flex items-center gap-2 rounded-xl bg-purple-600 px-5 py-2 text-sm font-semibold text-white hover:bg-purple-500 disabled:opacity-50">
                {syncing ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                开始同步
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

export default DataCenter;
