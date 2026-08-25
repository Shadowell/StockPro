import { lazy, Suspense, useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  FlaskConical, Play, Loader2,
  DollarSign, Activity,
  Calendar, List, RefreshCw, Eye,
  Plus, Trash2, Layers, Square, ListChecks,
  ChevronLeft, X,
  FileText, HelpCircle, CheckCircle2, AlertTriangle, Search,
  BarChart3,
} from 'lucide-react';
import { useStore } from '../stores/useStore';
import { backtestApi, researchApi } from '../api/client';
import clsx from 'clsx';
import ThemeAlertDialog, { type ThemeAlertTone } from '../components/ThemeAlertDialog';
import ThemeDialog from '../components/ThemeDialog';
import AnimatedNumber from '../components/AnimatedNumber';
import { getTradeSideDisplay } from '../utils/tradeSide';
import { SELECTED_SEGMENT_BORDER_CLASS, SELECTED_SEGMENT_CLASS, SELECTED_SEGMENT_COUNT_CLASS } from '../utils/selectionStyles';
import type { Kline } from '../types';
import { BacktestResult, BacktestHistoryItem, BacktestHistoryDeleteTarget, HistoryAssetFilter, BacktestView, BacktestStatusFilter, BacktestSortMode, BACKTEST_PREFS_KEY, BACKTEST_INSTANCES_KEY, SELECTED_BACKTEST_INSTANCE_KEY, ACTIVE_BACKTEST_JOB_KEY, ISO_DATE, BACKTEST_HISTORY_PAGE_SIZE, BACKTEST_WIZARD_STEPS, HISTORY_ASSET_FILTERS, BACKTEST_STATUS_FILTERS, BACKTEST_TIMEFRAME_OPTIONS, BACKTEST_TIMEFRAME_MODES, BacktestPrefsV1, BacktestInstanceStatus, BacktestTimeframeMode, BacktestInstanceConfig, BacktestInstance, todayDateInputValue, clampIsoDateToToday, defaultBacktestDateRange, defaultBatchBacktestDateRange, loadBacktestPrefs, createBacktestInstance, createBacktestDraft, quickDateRange, backtestDateValidationMessage, loadBacktestInstances, persistableBacktestInstances, backtestInstanceStatusMeta, backtestDataQualityStatusMeta, backtestInstanceActionStatusLabel, backtestInstanceActionButtonClass, backtestInstanceActionStatusTone, backtestInstanceActionStatusIcon, backtestInstanceStatusBucket, backtestInstanceReturn, backtestInstanceDrawdown, backtestInstanceWinRate, backtestInstanceCanContinue, strategySymbols, strategyBenchmarkSymbol, strategyTradeSymbols, strategyTimeframe, backtestTimeframeLabel, backtestEffectiveTimeframe, backtestEffectiveTimeframes, backtestInstanceTimeframes, finiteNumber, backtestTradeNotional, backtestTradeMargin, formatBacktestTradeMoney, formatBacktestTradeLeverage, backtestRequestMatchesInstance, strategyAssetClass, strategyAssetClassById, inferStrategyAssetClassFromName, backtestResultAssetClass, backtestInstanceAssetClass, strategyNameColorClass, strategyAssetBadgeClass, strategyIsBacktestSelectable, strategyBacktestCostDefaults, symbolSummary, strategyMatchesBacktestSearch, backtestInstanceMatchesSearch, strategyNameById, backtestStrategyDisplayName, formatDateTime, timeframeMs, buildBacktestTradeMarkers, normalizeBacktestKline, historyDetailToBacktestResult, backtestHistorySignature, backtestHistoryIdentity, backtestInstanceHistoryIdentities, historyItemToBacktestInstance, backtestHistoryItemFromInstance, backtestInstanceLogs, backtestStatusDialogContent, dateToStartMs, dateToEndMs, buildBacktestPerformanceMetrics, backtestSortDirectionFor, nextBacktestSortMode, backtestApiSortBy, backtestApiSortDir, compareNullableBacktestMetric, BacktestSortArrow, BacktestWizardStep, Field, StatRow } from './backtest/backtestSupport';

const WatchKlineChart = lazy(() => import('../components/WatchKlineChart'));
const BacktestEquityCurve = lazy(() => import('../components/BacktestEquityCurve'));
const BacktestTradeAnalytics = lazy(() => import('../components/BacktestTradeAnalytics'));
const BacktestCompareDialog = lazy(() => import('./backtest/BacktestCompareDialog'));

// ============================================
// 类型定义
// ============================================
export default function Backtest() {
  const { strategies, fetchStrategies } = useStore();
  const [searchParams] = useSearchParams();
  const deepLinkStrategyId = Number(searchParams.get('strategy_version_id')) || null;
  const [initialBt] = useState(() => ({
    ...(loadBacktestPrefs() || { v: 1 as const }),
    selectedStrategy: deepLinkStrategyId ?? loadBacktestPrefs()?.selectedStrategy ?? null,
  }));
  const [view, setView] = useState<BacktestView>('dashboard');
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [batchBacktestConfirmOpen, setBatchBacktestConfirmOpen] = useState(false);
  const [isBatchBacktestSubmitting, setIsBatchBacktestSubmitting] = useState(false);
  const [createStep, setCreateStep] = useState<1 | 2 | 3>(1);
  const [createDraft, setCreateDraft] = useState<BacktestInstanceConfig>(() =>
    createBacktestDraft({
      selectedStrategy: initialBt?.selectedStrategy ?? null,
      startDate: initialBt?.startDate,
      initialCapital: initialBt?.initialCapital,
    }),
  );
  const [strategySearchQuery, setStrategySearchQuery] = useState('');
  const [instanceSearchQuery, setInstanceSearchQuery] = useState('');
  const [instanceAssetFilter, setInstanceAssetFilter] = useState<HistoryAssetFilter>('all');
  const [instanceStatusFilter, setInstanceStatusFilter] = useState<BacktestStatusFilter>('all');
  const [instanceSortMode, setInstanceSortMode] = useState<BacktestSortMode>('created_desc');
  const [instanceTimeframeFilter, setInstanceTimeframeFilter] = useState<string>('all');
  const [compareSelection, setCompareSelection] = useState<string[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);
  const [historyDetailResult, setHistoryDetailResult] = useState<BacktestResult | null>(null);
  const [historyBenchmarkKlines, setHistoryBenchmarkKlines] = useState<{ timestamp: number; close: number }[]>([]);
  const [backtestInstances, setBacktestInstances] = useState<BacktestInstance[]>(() =>
    loadBacktestInstances(initialBt),
  );
  const [selectedInstanceId, setSelectedInstanceId] = useState<string>(() => {
    try {
      return localStorage.getItem(SELECTED_BACKTEST_INSTANCE_KEY) || '';
    } catch {
      return '';
    }
  });
  const instancesRef = useRef<BacktestInstance[]>(backtestInstances);
  const selectedInstanceIdRef = useRef<string>(selectedInstanceId);

  const [activeMatrixTimeframe, setActiveMatrixTimeframe] = useState('');
  const [historyItems, setHistoryItems] = useState<BacktestHistoryItem[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [isLoadingMoreHistory, setIsLoadingMoreHistory] = useState(false);
  const [historyHasMore, setHistoryHasMore] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [selectedHistoryId, setSelectedHistoryId] = useState<number | null>(null);
  const [isLoadingDetailEvidence, setIsLoadingDetailEvidence] = useState(false);
  const [deletingHistoryId, setDeletingHistoryId] = useState<number | null>(null);
  const [historyDeleteTarget, setHistoryDeleteTarget] = useState<BacktestHistoryDeleteTarget | null>(null);
  const [isDeletingHistoryBatch, setIsDeletingHistoryBatch] = useState(false);
  const [backtestStatusTarget, setBacktestStatusTarget] = useState<BacktestInstance | null>(null);
  const [backtestLogTarget, setBacktestLogTarget] = useState<BacktestInstance | null>(null);
  const [localBacktestDeleteTarget, setLocalBacktestDeleteTarget] = useState<BacktestInstance | null>(null);
  const [cancelBacktestTarget, setCancelBacktestTarget] = useState<BacktestInstance | null>(null);

  const [themeAlert, setThemeAlert] = useState<{
    open: boolean;
    title: string;
    content: string;
    tone?: ThemeAlertTone;
  }>({ open: false, title: '', content: '' });

  const showThemeAlert = (title: string, content: string, tone?: ThemeAlertTone) => {
    setThemeAlert({ open: true, title, content, tone: tone ?? 'danger' });
  };

  const backtestableStrategies = useMemo(
    () => strategies.filter(strategyIsBacktestSelectable),
    [strategies],
  );
  const filteredBacktestStrategyOptions = useMemo(
    () => backtestableStrategies
      .filter((strategy) => strategyMatchesBacktestSearch(strategy, strategySearchQuery))
      .slice(0, 60),
    [backtestableStrategies, strategySearchQuery],
  );
  const selectedInstance = useMemo(() => {
    return (
      backtestInstances.find((instance) => instance.id === selectedInstanceId) ||
      backtestInstances[0] ||
      null
    );
  }, [backtestInstances, selectedInstanceId]);
  const selectedStrategy = selectedInstance?.config.selectedStrategy ?? null;
  const startDate = selectedInstance?.config.startDate ?? defaultBacktestDateRange().start;
  const endDate = selectedInstance?.config.endDate ?? defaultBacktestDateRange().end;
  const initialCapital = selectedInstance?.config.initialCapital ?? 1_000_000;
  const batchBacktestDefaults = useMemo(defaultBatchBacktestDateRange, []);
  const isCancelling = selectedInstance?.status === 'cancelling';
  const isRunning = selectedInstance?.status === 'running' || isCancelling;
  const jobProgress = selectedInstance?.jobProgress ?? null;
  const baseResult = historyDetailResult ?? selectedInstance?.result ?? null;
  const matrixPeriodResults = useMemo(() => {
    if (!baseResult || !Array.isArray(baseResult.matrixResults) || baseResult.matrixResults.length === 0) {
      return [];
    }
    const seen = new Set<string>();
    return baseResult.matrixResults
      .filter((item) => {
        const key = item.timeframe || item.status || String(seen.size);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .map((item): BacktestResult => ({
        ...baseResult,
        ...item,
        id: baseResult.id,
        strategyId: item.strategyId ?? baseResult.strategyId,
        strategyName: item.strategyName || baseResult.strategyName,
        status: item.status || baseResult.status,
        timeframe: item.timeframe || baseResult.timeframe,
        timeframeMode: baseResult.timeframeMode,
        startDate: item.startDate || baseResult.startDate,
        endDate: item.endDate || baseResult.endDate,
        initialCapital: item.initialCapital ?? baseResult.initialCapital,
        isHistorical: baseResult.isHistorical,
        matrixResults: undefined,
      }));
  }, [baseResult]);
  const activeMatrixResult = useMemo(() => {
    if (matrixPeriodResults.length === 0) return null;
    return (
      matrixPeriodResults.find((item) => item.timeframe === activeMatrixTimeframe) ||
      matrixPeriodResults.find((item) => item.timeframe === baseResult?.timeframe) ||
      matrixPeriodResults[0]
    );
  }, [activeMatrixTimeframe, baseResult?.timeframe, matrixPeriodResults]);
  const result = activeMatrixResult ?? baseResult;
  const benchmarkKlines = historyDetailResult ? historyBenchmarkKlines : selectedInstance?.benchmarkKlines ?? [];
  const todayDate = todayDateInputValue();
  useEffect(() => {
    if (matrixPeriodResults.length === 0) {
      if (activeMatrixTimeframe) setActiveMatrixTimeframe('');
      return;
    }
    const preferred =
      matrixPeriodResults.find((item) => item.timeframe === activeMatrixTimeframe)?.timeframe ||
      matrixPeriodResults.find((item) => item.timeframe === baseResult?.timeframe)?.timeframe ||
      matrixPeriodResults[0]?.timeframe ||
      '';
    if (preferred !== activeMatrixTimeframe) setActiveMatrixTimeframe(preferred);
  }, [activeMatrixTimeframe, baseResult?.timeframe, matrixPeriodResults]);
  const displayedTrades = useMemo(() => {
    const trades = result?.trades;
    if (!trades?.length) return [];
    return [...trades].sort((a, b) => b.timestamp - a.timestamp).slice(0, 100);
  }, [result?.trades]);
  const selectedStrategyInfo = useMemo(
    () => backtestableStrategies.find((s) => Number(s.id) === Number(selectedStrategy)) || null,
    [selectedStrategy, backtestableStrategies],
  );
  const resultStrategyInfo = useMemo(
    () => backtestableStrategies.find((s) => Number(s.id) === Number(result?.strategyId ?? selectedStrategy)) || null,
    [result?.strategyId, selectedStrategy, backtestableStrategies],
  );
  const detailStrategyInfo = resultStrategyInfo || selectedStrategyInfo;
  const feedSymbols = useMemo(() => strategySymbols(detailStrategyInfo), [detailStrategyInfo]);
  const tradeSymbols = useMemo(() => strategyTradeSymbols(detailStrategyInfo), [detailStrategyInfo]);
  const benchmarkSymbol = strategyBenchmarkSymbol();
  const selectedStrategyTimeframe = useMemo(() => strategyTimeframe(selectedStrategyInfo), [selectedStrategyInfo]);
  const resultStrategyTimeframe = useMemo(
    () => result?.timeframe || strategyTimeframe(resultStrategyInfo || selectedStrategyInfo) || '1h',
    [result?.timeframe, resultStrategyInfo, selectedStrategyInfo],
  );
  const selectedStrategyTimeframeLabel = selectedStrategyInfo
    ? backtestTimeframeLabel(selectedStrategyTimeframe)
    : '请选择策略';
  const tradeChartSymbols = useMemo(() => {
    const symbols = new Set<string>();
    (result?.trades || []).forEach((trade) => {
      if (trade.symbol) symbols.add(trade.symbol);
    });
    return Array.from(symbols);
  }, [result?.trades]);
  const [selectedTradeChartSymbol, setSelectedTradeChartSymbol] = useState('');
  const [tradeChartKlines, setTradeChartKlines] = useState<Kline[]>([]);
  const [tradeChartLoading, setTradeChartLoading] = useState(false);
  const [tradeChartError, setTradeChartError] = useState('');
  const tradeChartMarkers = useMemo(
    () => buildBacktestTradeMarkers(
      result?.trades || [],
      selectedTradeChartSymbol,
      Number(result?.strategyId ?? selectedStrategy ?? 0),
      result?.strategyName || '回测策略',
    ),
    [result?.trades, result?.strategyId, result?.strategyName, selectedStrategy, selectedTradeChartSymbol],
  );
  useEffect(() => {
    if (tradeChartSymbols.length === 0) {
      setSelectedTradeChartSymbol('');
      return;
    }
    if (!selectedTradeChartSymbol || !tradeChartSymbols.includes(selectedTradeChartSymbol)) {
      setSelectedTradeChartSymbol(tradeChartSymbols[0]);
    }
  }, [selectedTradeChartSymbol, tradeChartSymbols]);
  useEffect(() => {
    if (!selectedTradeChartSymbol || tradeChartMarkers.length === 0) {
      setTradeChartKlines([]);
      setTradeChartError('');
      return;
    }

    const timestamps = tradeChartMarkers.map((marker) => Number(marker.timestamp)).filter(Number.isFinite);
    if (!timestamps.length) return;

    const barMs = timeframeMs(resultStrategyTimeframe);
    const tradeChartStart = Math.max(0, Math.min(...timestamps) - barMs * 30);
    const tradeChartEnd = Math.max(...timestamps) + barMs * 30;
    let cancelled = false;

    setTradeChartLoading(true);
    setTradeChartError('');
    researchApi.dailyBars(selectedTradeChartSymbol, 1000)
      .then((response) => {
        if (cancelled) return;
        const rows = response.items
          .map((row) => ({ ...row, timestamp: new Date(row.date).getTime() }))
          .filter((row) => row.timestamp >= tradeChartStart && row.timestamp <= tradeChartEnd);
        setTradeChartKlines(rows.map(normalizeBacktestKline).filter(Boolean) as Kline[]);
      })
      .catch((error: any) => {
        if (cancelled) return;
        setTradeChartKlines([]);
        setTradeChartError(error?.response?.data?.detail || error?.message || '读取回测 K 线失败');
      })
      .finally(() => {
        if (!cancelled) setTradeChartLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedTradeChartSymbol, tradeChartMarkers, resultStrategyTimeframe]);
  const symbolScopeLabel =
    tradeSymbols.length > 0
      ? `交易子池: ${symbolSummary(tradeSymbols)}`
      : symbolSummary(feedSymbols);
  const draftStrategyInfo = useMemo(
    () => backtestableStrategies.find((s) => Number(s.id) === Number(createDraft.selectedStrategy)) || null,
    [backtestableStrategies, createDraft.selectedStrategy],
  );
  const draftCostDefaults = useMemo(() => strategyBacktestCostDefaults(draftStrategyInfo), [draftStrategyInfo]);
  const draftEffectiveMakerFeeBps = createDraft.makerFeeBps ?? draftCostDefaults.makerFeeBps;
  const draftEffectiveTakerFeeBps = createDraft.takerFeeBps ?? draftCostDefaults.takerFeeBps;
  const draftEffectiveSlippageBps = createDraft.slippageBps ?? draftCostDefaults.slippageBps;
  const draftAssetClass = strategyAssetClass(draftStrategyInfo);
  const historicalBacktestInstances = useMemo(() => {
    const localIdentities = new Set(backtestInstances.flatMap(backtestInstanceHistoryIdentities));
    return historyItems
      .filter((item) => {
        const identity = backtestHistoryIdentity(item);
        const signature = backtestHistorySignature(item);
        return !localIdentities.has(identity) && !localIdentities.has(signature);
      })
      .map((item) => historyItemToBacktestInstance(item, strategyNameById(strategies, item.strategyId, item.strategyName)));
  }, [backtestInstances, historyItems, strategies]);
  const unifiedBacktestInstances = useMemo(
    () => [...backtestInstances, ...historicalBacktestInstances],
    [backtestInstances, historicalBacktestInstances],
  );
  const shouldRenderBacktestInstances =
    unifiedBacktestInstances.length > 0 || isLoadingHistory || Boolean(historyError);
  const instanceAssetCounts = useMemo(() => {
    const counts: Record<HistoryAssetFilter, number> = { all: unifiedBacktestInstances.length, stock: 0, etf: 0 };
    unifiedBacktestInstances.forEach((instance) => {
      counts[backtestInstanceAssetClass(backtestableStrategies, instance)] += 1;
    });
    return counts;
  }, [unifiedBacktestInstances, backtestableStrategies]);
  const instanceStatusCounts = useMemo(() => {
    const counts: Record<BacktestStatusFilter, number> = {
      all: unifiedBacktestInstances.length,
      running: 0,
      completed: 0,
      failed: 0,
      cancelled: 0,
    };
    unifiedBacktestInstances.forEach((instance) => {
      const bucket = backtestInstanceStatusBucket(instance.status);
      if (bucket !== 'all') counts[bucket] += 1;
    });
    return counts;
  }, [unifiedBacktestInstances]);
  const availableInstanceTimeframes = useMemo(() => {
    const values = new Set<string>();
    unifiedBacktestInstances.forEach((instance) => {
      const strategyInfoForInstance = backtestableStrategies.find((s) => Number(s.id) === Number(instance.config.selectedStrategy));
      backtestInstanceTimeframes(instance, strategyInfoForInstance).forEach((timeframe) => values.add(timeframe));
    });
    return Array.from(values).sort();
  }, [unifiedBacktestInstances, backtestableStrategies]);
  const instanceTimeframeFilterOptions = useMemo(
    () => [
      { value: 'all', label: '全部周期' },
      ...availableInstanceTimeframes.map((timeframe) => ({ value: timeframe, label: backtestTimeframeLabel(timeframe) })),
    ],
    [availableInstanceTimeframes],
  );
  const filteredBacktestInstances = useMemo(() => {
    const filtered = unifiedBacktestInstances.filter((instance) => {
      const strategyInfoForInstance = backtestableStrategies.find((s) => Number(s.id) === Number(instance.config.selectedStrategy));
      const assetMatches =
        instanceAssetFilter === 'all' ||
        backtestInstanceAssetClass(backtestableStrategies, instance) === instanceAssetFilter;
      const statusMatches =
        instanceStatusFilter === 'all' ||
        backtestInstanceStatusBucket(instance.status) === instanceStatusFilter;
      const instanceTimeframes = backtestInstanceTimeframes(instance, strategyInfoForInstance);
      const timeframeMatches =
        instanceTimeframeFilter === 'all' || instanceTimeframes.includes(instanceTimeframeFilter);
      const searchMatches = backtestInstanceMatchesSearch(
        instance,
        backtestableStrategies,
        strategyInfoForInstance,
        instanceSearchQuery,
      );
      return assetMatches && statusMatches && timeframeMatches && searchMatches;
    });
    return [...filtered].sort((a, b) => {
      if (instanceSortMode === 'created_asc' || instanceSortMode === 'created_desc') {
        const left = new Date(a.createdAt).getTime() || 0;
        const right = new Date(b.createdAt).getTime() || 0;
        return instanceSortMode === 'created_desc' ? right - left : left - right;
      }
      const sortBy = backtestApiSortBy(instanceSortMode);
      const sortDir = backtestApiSortDir(instanceSortMode);
      const metricGetter =
        sortBy === 'drawdown'
          ? backtestInstanceDrawdown
          : sortBy === 'win_rate'
            ? backtestInstanceWinRate
            : backtestInstanceReturn;
      const metricOrder = compareNullableBacktestMetric(metricGetter(a), metricGetter(b), sortDir);
      if (metricOrder !== 0) return metricOrder;
      const leftCreated = new Date(a.createdAt).getTime() || 0;
      const rightCreated = new Date(b.createdAt).getTime() || 0;
      return rightCreated - leftCreated;
    });
  }, [
    unifiedBacktestInstances,
    backtestableStrategies,
    instanceSearchQuery,
    instanceAssetFilter,
    instanceStatusFilter,
    instanceTimeframeFilter,
    instanceSortMode,
  ]);

  const toggleCompareSelection = useCallback((id: string) => {
    setCompareSelection((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : prev.length >= 4 ? prev : [...prev, id],
    );
  }, []);
  const compareEntries = useMemo(
    () =>
      compareSelection.map((id) => {
        const instance = unifiedBacktestInstances.find((item) => item.id === id);
        return {
          key: id,
          result: instance?.result ?? null,
          historyId: instance?.historyId ?? null,
          strategyId: instance?.config.selectedStrategy ?? null,
        };
      }),
    [compareSelection, unifiedBacktestInstances],
  );

  const updateInstance = useCallback((
    instanceId: string,
    updater: (instance: BacktestInstance) => BacktestInstance,
  ) => {
    setBacktestInstances((prev) =>
      prev.map((instance) =>
        instance.id === instanceId
          ? { ...updater(instance), updatedAt: new Date().toISOString() }
          : instance,
      ),
    );
  }, []);

  const addBacktestInstance = () => {
    setCreateDraft(createBacktestDraft({
      selectedStrategy,
      startDate,
      initialCapital,
    }));
    setStrategySearchQuery('');
    setCreateStep(1);
    setIsCreateModalOpen(true);
  };

  const createBatchBacktestInstances = async () => {
    if (isBatchBacktestSubmitting) return;
    setIsBatchBacktestSubmitting(true);
    try {
      const response = await backtestApi.runRunningStrategies();
      const createdInstances = (response.jobs || [])
        .map((job, index): BacktestInstance => {
          const instance = createBacktestInstance({
            selectedStrategy: Number(job.strategyId),
            startDate: String(job.request?.startDate ?? job.request?.start_date ?? response.defaults.startDate ?? batchBacktestDefaults.start),
            endDate: String(job.request?.endDate ?? job.request?.end_date ?? response.defaults.endDate ?? batchBacktestDefaults.end),
            initialCapital: Number(job.request?.initialCapital ?? job.request?.initial_capital ?? 1_000_000),
            timeframeMode: String(job.request?.timeframeMode ?? job.request?.timeframe_mode ?? 'strategy') as BacktestTimeframeMode,
            timeframe: String(job.request?.timeframe ?? '') || null,
            timeframes: Array.isArray(job.request?.timeframes) ? job.request.timeframes.map(String) : [],
            makerFeeBps: finiteNumber(job.request?.makerFeeBps ?? job.request?.maker_fee_bps),
            takerFeeBps: finiteNumber(job.request?.takerFeeBps ?? job.request?.taker_fee_bps),
            slippageBps: finiteNumber(job.request?.slippageBps ?? job.request?.slippage_bps),
          }, backtestInstances.length + index + 1);
          const jobId = String(job.jobId || '');
          return {
            ...instance,
            name: job.strategyName || strategyNameById(strategies, Number(job.strategyId)),
            status: 'running',
            activeJobId: jobId || null,
            resumeJobId: null,
            jobProgress: { currentBar: 0, totalBars: 0, percent: null },
            result: null,
            benchmarkKlines: [],
            errorMessage: null,
          };
        })
        .filter((instance) => Boolean(instance.activeJobId));

      setBatchBacktestConfirmOpen(false);
      if (createdInstances.length === 0) {
        showThemeAlert(
          '没有可批量回测的运行中策略',
          '当前没有符合条件的运行中模拟策略；实盘、非模拟或无法解析的运行中策略会被跳过。',
          'warning',
        );
        return;
      }

      setBacktestInstances((prev) => [...createdInstances, ...prev]);
      setSelectedInstanceId(createdInstances[0].id);
      setHistoryDetailResult(null);
      setSelectedHistoryId(null);
      setView('dashboard');
      try {
        sessionStorage.setItem(ACTIVE_BACKTEST_JOB_KEY, createdInstances[0].activeJobId || '');
      } catch {
        /* ignore */
      }

      const skippedCount = Number(response.skippedCount ?? 0);
      const skippedText = skippedCount > 0 ? `，跳过 ${skippedCount} 个运行中策略` : '';
      const responseStartDate = response.defaults?.startDate ?? batchBacktestDefaults.start;
      const responseEndDate = response.defaults?.endDate ?? batchBacktestDefaults.end;
      showThemeAlert(
        '已创建批量回测实例',
        `已为 ${createdInstances.length} 个运行中模拟策略创建回测任务${skippedText}。批量默认使用 100 万元，区间 ${responseStartDate} 至 ${responseEndDate}，周期沿用策略定义。`,
        'default',
      );
    } catch (error: any) {
      showThemeAlert(
        '创建批量回测实例失败',
        String(error?.response?.data?.detail || error?.message || '未知错误'),
        'danger',
      );
    } finally {
      setIsBatchBacktestSubmitting(false);
    }
  };

  const updateCreateDraft = (patch: Partial<BacktestInstanceConfig>) => {
    setCreateDraft((prev) => {
      const strategyChanged =
        Object.prototype.hasOwnProperty.call(patch, 'selectedStrategy') &&
        Number(patch.selectedStrategy ?? 0) !== Number(prev.selectedStrategy ?? 0);
      const next = { ...prev, ...patch };
      if (strategyChanged) {
        next.makerFeeBps = null;
        next.takerFeeBps = null;
        next.slippageBps = null;
      }
      if (patch.startDate != null) {
        next.startDate = clampIsoDateToToday(patch.startDate, prev.startDate);
      }
      if (patch.endDate != null) {
        next.endDate = clampIsoDateToToday(patch.endDate, prev.endDate);
      }
      if (next.startDate > todayDateInputValue()) {
        next.startDate = todayDateInputValue();
      }
      if (next.endDate > todayDateInputValue()) {
        next.endDate = todayDateInputValue();
      }
      return next;
    });
  };

  const applyQuickRange = (months: number) => {
    updateCreateDraft(quickDateRange(months));
  };

  const openInstanceDetail = (instanceId: string) => {
    setSelectedInstanceId(instanceId);
    setHistoryDetailResult(null);
    setView('detail');
  };

  const openBacktestRecordDetail = (instance: BacktestInstance) => {
    if (instance.isPersistedHistory && instance.historyId != null) {
      void loadHistoryDetail(instance.historyId);
      return;
    }
    openInstanceDetail(instance.id);
  };

  const deleteBacktestInstance = (instanceId: string) => {
    const target = backtestInstances.find((instance) => instance.id === instanceId);
    if (!target || target.status === 'running' || target.status === 'cancelling') return;
    setLocalBacktestDeleteTarget(target);
  };

  const confirmDeleteLocalBacktestInstance = () => {
    const target = localBacktestDeleteTarget;
    if (!target || target.status === 'running' || target.status === 'cancelling') {
      setLocalBacktestDeleteTarget(null);
      return;
    }
    const rest = backtestInstances.filter((instance) => instance.id !== target.id);
    const next = rest.map((instance, index) => ({
      ...instance,
      name: instance.name || `回测实例 ${index + 1}`,
    }));
    setBacktestInstances(next);
    if (selectedInstanceId === target.id) {
      setSelectedInstanceId(next[0]?.id || '');
      setHistoryDetailResult(null);
      setView('dashboard');
    }
    try {
      if (target.activeJobId && sessionStorage.getItem(ACTIVE_BACKTEST_JOB_KEY) === target.activeJobId) {
        sessionStorage.removeItem(ACTIVE_BACKTEST_JOB_KEY);
      }
    } catch {
      /* ignore */
    }
    setLocalBacktestDeleteTarget(null);
  };

  const deleteBacktestUnifiedRecord = (instance: BacktestInstance) => {
    if (instance.status === 'running' || instance.status === 'cancelling') return;
    const persistedItem =
      (instance.historyId != null
        ? historyItems.find((item) => Number(item.id) === Number(instance.historyId))
        : null) ||
      backtestHistoryItemFromInstance(instance);
    if (persistedItem) {
      deleteBacktestHistory(persistedItem);
      return;
    }
    deleteBacktestInstance(instance.id);
  };

  const fetchBenchmarkKlinesForResult = useCallback(async (
    backtestResult: BacktestResult,
    fallbackConfig: BacktestInstanceConfig,
  ) => {
    const benchmark = strategyBenchmarkSymbol();
    const benchmarkStartDate = backtestResult.startDate && ISO_DATE.test(backtestResult.startDate)
      ? backtestResult.startDate
      : fallbackConfig.startDate;
    const benchmarkEndDate = backtestResult.endDate && ISO_DATE.test(backtestResult.endDate)
      ? backtestResult.endDate
      : fallbackConfig.endDate;

    try {
      const response = await researchApi.dailyBars(benchmark, 1000);
      const startMs = dateToStartMs(benchmarkStartDate);
      const endMs = dateToEndMs(benchmarkEndDate);
      return response.items
        .map((row) => ({ timestamp: new Date(row.date).getTime(), close: row.close }))
        .filter((row) => row.timestamp >= startMs && row.timestamp <= endMs);
    } catch {
      return [];
    }
  }, []);

  const loadBacktestHistory = useCallback(async (options?: { reset?: boolean; offset?: number }) => {
    const reset = options?.reset ?? true;
    const offset = reset ? 0 : Math.max(0, options?.offset ?? 0);
    if (reset) {
      setIsLoadingHistory(true);
    } else {
      setIsLoadingMoreHistory(true);
    }
    setHistoryError(null);
    try {
      const items = await backtestApi.getResults({
        limit: BACKTEST_HISTORY_PAGE_SIZE + 1,
        offset,
        query: instanceSearchQuery.trim(),
        sortBy: backtestApiSortBy(instanceSortMode),
        sortDir: backtestApiSortDir(instanceSortMode),
        includeMatrixSummary: false,
      });
      const pageItems = (items as BacktestHistoryItem[]).slice(0, BACKTEST_HISTORY_PAGE_SIZE);
      setHistoryHasMore(items.length > BACKTEST_HISTORY_PAGE_SIZE);
      setHistoryItems((prev) => {
        if (reset) return pageItems;
        const seen = new Set(prev.map((item) => String(item.id)));
        return [...prev, ...pageItems.filter((item) => !seen.has(String(item.id)))];
      });
    } catch (error: any) {
      setHistoryError(String(error?.response?.data?.detail || error?.message || '加载回测记录失败'));
    } finally {
      if (reset) {
        setIsLoadingHistory(false);
      } else {
        setIsLoadingMoreHistory(false);
      }
    }
  }, [instanceSearchQuery, instanceSortMode]);

  const loadHistoryDetail = async (historyId: number) => {
    setSelectedHistoryId(historyId);
    setHistoryBenchmarkKlines([]);
    try {
      const detail = await backtestApi.getResult(historyId);
      const strategyName = strategyNameById(strategies, Number(detail.strategyId), detail.strategyName);
      const detailResult = historyDetailToBacktestResult(detail, strategyName);
      setHistoryDetailResult(detailResult);
      setView('detail');
      const historyBenchmarkConfig: BacktestInstanceConfig = {
        selectedStrategy: Number(detailResult.strategyId) || null,
        runMode: detail.runMode === 'full' ? 'full' : 'quick',
        startDate: detailResult.startDate || defaultBacktestDateRange().start,
        endDate: detailResult.endDate || defaultBacktestDateRange().end,
        initialCapital: detailResult.initialCapital || 1_000_000,
        timeframeMode: 'strategy',
        timeframe: null,
        timeframes: [],
        makerFeeBps: null,
        takerFeeBps: null,
        slippageBps: null,
      };
      const benchmark = await fetchBenchmarkKlinesForResult(detailResult, historyBenchmarkConfig);
      setHistoryBenchmarkKlines(benchmark);
    } catch (error: any) {
      showThemeAlert(
        '回测详情加载失败',
        String(error?.response?.data?.detail || error?.message || '未知错误'),
        'danger',
      );
    } finally {
      setSelectedHistoryId(null);
    }
  };

  const loadFullHistoryEvidence = async () => {
    if (historyDetailResult?.id == null || isLoadingDetailEvidence) return;
    setIsLoadingDetailEvidence(true);
    try {
      const evidence = await backtestApi.getResultEvidence(Number(historyDetailResult.id));
      setHistoryDetailResult(historyDetailToBacktestResult(
        { ...historyDetailResult, ...evidence },
        historyDetailResult.strategyName || 'A股策略',
      ));
    } catch (error: any) {
      showThemeAlert('完整证据加载失败', String(error?.response?.data?.detail || error?.message || '未知错误'), 'danger');
    } finally {
      setIsLoadingDetailEvidence(false);
    }
  };

  const deleteBacktestHistory = (item: BacktestHistoryItem) => {
    setHistoryDeleteTarget({ mode: 'single', items: [item] });
  };

  const confirmDeleteBacktestHistory = async () => {
    if (!historyDeleteTarget || isDeletingHistoryBatch) return;
    const ids = historyDeleteTarget.items.map((item) => item.id);
    const idSet = new Set(ids);
    setDeletingHistoryId(ids.length === 1 ? ids[0] : null);
    setIsDeletingHistoryBatch(true);
    try {
      await Promise.all(ids.map((id) => backtestApi.deleteResult(id)));
      setHistoryItems((prev) => prev.filter((history) => !idSet.has(history.id)));
      setBacktestInstances((prev) =>
        prev.filter((instance) => !idSet.has(Number(instance.historyId ?? instance.result?.id))),
      );
      if (historyDetailResult?.isHistorical && idSet.has(Number(historyDetailResult.id))) {
        setHistoryDetailResult(null);
        setView('dashboard');
      }
      setHistoryDeleteTarget(null);
    } catch (error: any) {
      showThemeAlert(
        '删除回测记录失败',
        String(error?.response?.data?.detail || error?.message || '未知错误'),
        'danger',
      );
    } finally {
      setDeletingHistoryId(null);
      setIsDeletingHistoryBatch(false);
    }
  };

  useEffect(() => { fetchStrategies(); }, []);

  useEffect(() => {
    instancesRef.current = backtestInstances;
  }, [backtestInstances]);

  useEffect(() => {
    selectedInstanceIdRef.current = selectedInstance?.id || selectedInstanceId;
    if (!selectedInstance && backtestInstances[0]) {
      setSelectedInstanceId(backtestInstances[0].id);
    } else if (!selectedInstance && !backtestInstances[0] && selectedInstanceId) {
      setSelectedInstanceId('');
    }
  }, [backtestInstances, selectedInstance, selectedInstanceId]);

  useEffect(() => {
    void loadBacktestHistory();
  }, [loadBacktestHistory]);

  useEffect(() => {
    const recoverableInstances = backtestInstances.filter(
      (instance) =>
        (instance.status === 'interrupted' || instance.status === 'failed') &&
        !instance.resumeJobId &&
        !instance.activeJobId &&
        instance.config.selectedStrategy,
    );
    if (recoverableInstances.length === 0) return;

    let cancelled = false;
    const recoverJobs = async () => {
      try {
        const jobs = await backtestApi.getJobs({
          status: 'interrupted,failed,pending,running,cancelling',
          limit: 100,
        });
        if (cancelled) return;
        setBacktestInstances((prev) => {
          let changed = false;
          const usedJobIds = new Set(prev.map((instance) => instance.resumeJobId || instance.activeJobId).filter(Boolean));
          const next = prev.map((instance) => {
            if (
              !(
                (instance.status === 'interrupted' || instance.status === 'failed') &&
                !instance.resumeJobId &&
                !instance.activeJobId &&
                instance.config.selectedStrategy
              )
            ) {
              return instance;
            }
            const matched = jobs.find((job) => {
              if (!job.resumable || usedJobIds.has(job.jobId)) return false;
              return backtestRequestMatchesInstance(job.request, instance);
            });
            if (!matched) return instance;
            usedJobIds.add(matched.jobId);
            changed = true;
            return {
              ...instance,
              resumeJobId: matched.jobId,
              jobProgress: matched.totalBars > 0
                ? {
                    currentBar: matched.currentBar,
                    totalBars: matched.totalBars,
                    percent: matched.percent,
                  }
                : instance.jobProgress,
              errorMessage: instance.errorMessage || matched.message || matched.errorMessage || null,
            };
          });
          return changed ? next : prev;
        });
      } catch {
        /* 恢复入口是增强能力，失败不阻断页面渲染 */
      }
    };

    void recoverJobs();
    return () => {
      cancelled = true;
    };
  }, [backtestInstances]);

  useEffect(() => {
    if (strategies.length === 0) return;
    const knownStrategies = new Map(strategies.map((s) => [Number(s.id), s]));
    setBacktestInstances((prev) => {
      let changed = false;
      const next = prev.map((instance) => {
        const strategyId = instance.config.selectedStrategy;
        const strategy = knownStrategies.get(Number(strategyId));
        if (!strategyId || strategy == null || strategyIsBacktestSelectable(strategy)) return instance;
        changed = true;
        return {
          ...instance,
          status: (instance.status === 'running' ? instance.status : 'idle') as BacktestInstanceStatus,
          config: { ...instance.config, selectedStrategy: null },
          result: null,
          benchmarkKlines: [],
          errorMessage: '原策略已不再适合回测，请重新选择策略。',
          updatedAt: new Date().toISOString(),
        };
      });
      return changed ? next : prev;
    });
  }, [strategies, backtestableStrategies]);

  useEffect(() => {
    try {
      localStorage.setItem(
        BACKTEST_INSTANCES_KEY,
        JSON.stringify({
          v: 1,
          instances: persistableBacktestInstances(backtestInstances),
        }),
      );
      if (selectedInstance?.id) {
        localStorage.setItem(SELECTED_BACKTEST_INSTANCE_KEY, selectedInstance.id);
      } else {
        localStorage.removeItem(SELECTED_BACKTEST_INSTANCE_KEY);
      }
      const payload: BacktestPrefsV1 = {
        v: 1,
        selectedStrategy,
        startDate,
        initialCapital,
      };
      localStorage.setItem(BACKTEST_PREFS_KEY, JSON.stringify(payload));
      const firstRunningJob = backtestInstances.find((instance) => instance.status === 'running' && instance.activeJobId)
        ?.activeJobId;
      if (firstRunningJob) {
        sessionStorage.setItem(ACTIVE_BACKTEST_JOB_KEY, firstRunningJob);
      } else {
        sessionStorage.removeItem(ACTIVE_BACKTEST_JOB_KEY);
      }
    } catch {
      /* ignore */
    }
  }, [
    backtestInstances,
    selectedInstance?.id,
    selectedStrategy,
    startDate,
    initialCapital,
  ]);

  const runningJobKey = useMemo(
    () =>
      backtestInstances
        .filter((instance) => (instance.status === 'running' || instance.status === 'cancelling') && instance.activeJobId)
        .map((instance) => `${instance.id}:${instance.activeJobId}`)
        .join('|'),
    [backtestInstances],
  );

  useEffect(() => {
    if (!runningJobKey) return;
    let cancelled = false;

    const tick = async () => {
      const runningInstances = instancesRef.current.filter(
        (instance) => (instance.status === 'running' || instance.status === 'cancelling') && instance.activeJobId,
      );
      await Promise.all(runningInstances.map(async (instance) => {
        if (cancelled || !instance.activeJobId) return;
        try {
          const st = await backtestApi.getJob(instance.activeJobId);
          if (cancelled) return;

          const nextProgress =
            st.totalBars > 0
              ? { currentBar: st.currentBar, totalBars: st.totalBars, percent: st.percent }
              : { currentBar: 0, totalBars: 0, percent: null };

          if (st.status === 'completed' && st.result) {
            const benchmark = await fetchBenchmarkKlinesForResult(st.result, instance.config);
            if (cancelled) return;
            updateInstance(instance.id, (current) => ({
              ...current,
              status: 'completed',
              activeJobId: null,
              resumeJobId: null,
              jobProgress: null,
              result: st.result,
              benchmarkKlines: benchmark,
              errorMessage: null,
            }));
            void loadBacktestHistory();
            return;
          }

          if (st.status === 'cancelled') {
            updateInstance(instance.id, (current) => ({
              ...current,
              status: 'cancelled',
              activeJobId: null,
              resumeJobId: null,
              jobProgress: nextProgress,
              errorMessage: st.message || '回测已停止',
            }));
            if (selectedInstanceIdRef.current === instance.id) {
              showThemeAlert('回测已停止', st.message || '用户已停止回测', 'warning');
            }
            return;
          }

          if (st.status === 'failed' || st.status === 'interrupted') {
            const hint =
              st.status === 'interrupted' && st.totalBars > 0
                ? `最后进度: ${st.currentBar} / ${st.totalBars}` +
                  (st.percent != null ? `（${st.percent.toFixed(1)}%）` : '')
                : '';
            const message =
              st.status === 'failed'
                ? st.errorMessage || '未知错误'
                : [st.message, hint].filter(Boolean).join('。') || '任务已结束';
            updateInstance(instance.id, (current) => ({
              ...current,
              status: st.status as BacktestInstanceStatus,
              activeJobId: null,
              resumeJobId: st.resumable === false ? null : instance.activeJobId,
              jobProgress: null,
              errorMessage: message,
            }));
            if (selectedInstanceIdRef.current === instance.id) {
              showThemeAlert(st.status === 'failed' ? '回测失败' : '回测已中断', message, st.status === 'failed' ? 'danger' : 'warning');
            }
            return;
          }

          updateInstance(instance.id, (current) => ({
            ...current,
            status: st.status === 'cancelling' ? 'cancelling' : 'running',
            jobProgress: nextProgress,
            errorMessage: null,
          }));
        } catch (err: any) {
          if (cancelled) return;
          const message = String(err?.response?.data?.detail || err?.message || '任务查询失败');
          updateInstance(instance.id, (current) => ({
            ...current,
            status: 'failed',
            activeJobId: null,
            resumeJobId: instance.activeJobId,
            jobProgress: null,
            errorMessage: message,
          }));
          if (selectedInstanceIdRef.current === instance.id) {
            showThemeAlert('回测任务查询失败', message, 'danger');
          }
        }
      }));
    };

    void tick();
    const id = window.setInterval(() => void tick(), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [runningJobKey, updateInstance, fetchBenchmarkKlinesForResult, loadBacktestHistory]);

  const runBacktest = async (configOverride?: BacktestInstanceConfig) => {
    const runConfig = configOverride ?? selectedInstance?.config;
    if (!runConfig?.selectedStrategy) {
      showThemeAlert('提示', '请选择策略', 'warning');
      return;
    }
    const dateError = backtestDateValidationMessage(runConfig);
    if (dateError) {
      showThemeAlert('回测日期无效', dateError, 'warning');
      return;
    }

    let instanceId = selectedInstance?.id || '';
    if (configOverride) {
      const strategyInfo = backtestableStrategies.find((s) => Number(s.id) === Number(runConfig.selectedStrategy));
      const next = {
        ...createBacktestInstance(runConfig, backtestInstances.length + 1),
        name: strategyInfo?.name || `回测实例 ${backtestInstances.length + 1}`,
        status: 'running' as BacktestInstanceStatus,
      };
      instanceId = next.id;
      setBacktestInstances((prev) => [next, ...prev]);
      setSelectedInstanceId(next.id);
      setHistoryDetailResult(null);
      setView('dashboard');
      setIsCreateModalOpen(false);
    } else {
      if (!selectedInstance) {
        showThemeAlert('提示', '请先新增回测实例', 'warning');
        return;
      }
      if (selectedInstance.status === 'running' || selectedInstance.status === 'cancelling') {
        showThemeAlert('提示', '当前实例已有回测在运行，可切换其它实例继续配置新任务。', 'warning');
        return;
      }
      updateInstance(instanceId, (instance) => ({
        ...instance,
        status: 'running',
        activeJobId: null,
        resumeJobId: null,
        jobProgress: null,
        result: null,
        benchmarkKlines: [],
        errorMessage: null,
      }));
    }

    const strategyInfo = backtestableStrategies.find((s) => Number(s.id) === Number(runConfig.selectedStrategy));
    const defaults = strategyBacktestCostDefaults(strategyInfo);
    const effectiveMakerFeeBps = runConfig.makerFeeBps ?? defaults.makerFeeBps;
    const effectiveTakerFeeBps = runConfig.takerFeeBps ?? defaults.takerFeeBps;
    const effectiveSlippageBps = runConfig.slippageBps ?? defaults.slippageBps;
    const effectiveTimeframes = backtestEffectiveTimeframes(runConfig, strategyInfo);
    const effectiveTimeframe = backtestEffectiveTimeframe(runConfig, strategyInfo);

    try {
      const { jobId } = await backtestApi.runJob({
        mode: runConfig.runMode,
        strategy_id: runConfig.selectedStrategy,
        exchange: 'cn',
        timeframe_mode: runConfig.timeframeMode,
        timeframe: effectiveTimeframe,
        timeframes: runConfig.timeframeMode === 'matrix' ? effectiveTimeframes : undefined,
        start_date: runConfig.startDate,
        end_date: runConfig.endDate,
        initial_capital: runConfig.initialCapital,
        maker_fee_bps: effectiveMakerFeeBps,
        taker_fee_bps: effectiveTakerFeeBps,
        slippage_bps: effectiveSlippageBps,
      });
      try {
        sessionStorage.setItem(ACTIVE_BACKTEST_JOB_KEY, jobId);
      } catch {
        /* ignore */
      }
      updateInstance(instanceId, (instance) => ({
        ...instance,
        status: 'running',
        activeJobId: jobId,
        resumeJobId: null,
        jobProgress: { currentBar: 0, totalBars: 0, percent: null },
      }));
    } catch (error: any) {
      console.error('Backtest job start failed:', error);
      try {
        sessionStorage.removeItem(ACTIVE_BACKTEST_JOB_KEY);
      } catch {
        /* ignore */
      }
      const message = String(
        error.response?.data?.error?.message ||
          error.response?.data?.detail ||
          error.message,
      );
      updateInstance(instanceId, (instance) => ({
        ...instance,
        status: 'failed',
        activeJobId: null,
        resumeJobId: null,
        jobProgress: null,
        errorMessage: message,
      }));
      showThemeAlert('无法启动回测', message, 'danger');
    }
  };

  const cancelBacktestInstance = (instanceId: string) => {
    const target = backtestInstances.find((instance) => instance.id === instanceId);
    if (!target?.activeJobId || target.status === 'cancelling') return;
    setCancelBacktestTarget(target);
  };

  const confirmCancelBacktestInstance = async () => {
    const target = cancelBacktestTarget;
    if (!target?.activeJobId || target.status === 'cancelling') {
      setCancelBacktestTarget(null);
      return;
    }
    setCancelBacktestTarget(null);
    const instanceId = target.id;

    updateInstance(instanceId, (instance) => ({
      ...instance,
      status: 'cancelling',
      errorMessage: null,
    }));

    try {
      const st = await backtestApi.cancelJob(target.activeJobId);
      updateInstance(instanceId, (instance) => ({
        ...instance,
        status: st.status === 'cancelled' ? 'cancelled' : 'cancelling',
        activeJobId: st.status === 'cancelled' ? null : instance.activeJobId,
        jobProgress: {
          currentBar: st.currentBar || 0,
          totalBars: st.totalBars || 0,
          percent: st.percent ?? null,
        },
        errorMessage: st.message || (st.status === 'cancelled' ? '回测已停止' : null),
      }));
      if (st.status === 'cancelled') {
        try {
          if (sessionStorage.getItem(ACTIVE_BACKTEST_JOB_KEY) === target.activeJobId) {
            sessionStorage.removeItem(ACTIVE_BACKTEST_JOB_KEY);
          }
        } catch {
          /* ignore */
        }
      }
    } catch (error: any) {
      const message = String(error?.response?.data?.detail || error?.message || '停止回测失败');
      updateInstance(instanceId, (instance) => ({
        ...instance,
        status: 'running',
        errorMessage: message,
      }));
      showThemeAlert('停止回测失败', message, 'danger');
    }
  };

  const resumeBacktestInstance = async (instanceId: string) => {
    const target = backtestInstances.find((instance) => instance.id === instanceId);
    const jobId = target?.resumeJobId || target?.activeJobId;
    if (!target || target.status === 'running' || target.status === 'cancelling') return;
    if (!jobId && !target.config.selectedStrategy) {
      showThemeAlert('继续回测失败', '缺少策略配置，无法继续回测', 'warning');
      return;
    }
    const dateError = backtestDateValidationMessage(target.config);
    if (dateError) {
      showThemeAlert('回测日期无效', dateError, 'warning');
      return;
    }

    updateInstance(instanceId, (instance) => ({
      ...instance,
      status: 'running',
      activeJobId: jobId || null,
      resumeJobId: null,
      jobProgress: instance.jobProgress || { currentBar: 0, totalBars: 0, percent: null },
      errorMessage: null,
    }));

    try {
      if (!jobId) {
        const strategyInfo = backtestableStrategies.find((s) => Number(s.id) === Number(target.config.selectedStrategy));
        const defaults = strategyBacktestCostDefaults(strategyInfo);
        const effectiveTimeframes = backtestEffectiveTimeframes(target.config, strategyInfo);
        const effectiveTimeframe = backtestEffectiveTimeframe(target.config, strategyInfo);
        const { jobId: newJobId } = await backtestApi.runJob({
          mode: target.config.runMode,
          strategy_id: target.config.selectedStrategy,
          exchange: 'cn',
          timeframe_mode: target.config.timeframeMode,
          timeframe: effectiveTimeframe,
          timeframes: target.config.timeframeMode === 'matrix' ? effectiveTimeframes : undefined,
          start_date: target.config.startDate,
          end_date: target.config.endDate,
          initial_capital: target.config.initialCapital,
          maker_fee_bps: target.config.makerFeeBps ?? defaults.makerFeeBps,
          taker_fee_bps: target.config.takerFeeBps ?? defaults.takerFeeBps,
          slippage_bps: target.config.slippageBps ?? defaults.slippageBps,
        });
        try {
          sessionStorage.setItem(ACTIVE_BACKTEST_JOB_KEY, newJobId);
        } catch {
          /* ignore */
        }
        updateInstance(instanceId, (instance) => ({
          ...instance,
          status: 'running',
          activeJobId: newJobId,
          resumeJobId: null,
          jobProgress: { currentBar: 0, totalBars: 0, percent: null },
          result: null,
          benchmarkKlines: [],
          errorMessage: null,
        }));
        return;
      }

      const st = await backtestApi.resumeJob(jobId);
      try {
        sessionStorage.setItem(ACTIVE_BACKTEST_JOB_KEY, st.jobId || jobId);
      } catch {
        /* ignore */
      }
      updateInstance(instanceId, (instance) => ({
        ...instance,
        status: st.status === 'cancelling' ? 'cancelling' : 'running',
        activeJobId: st.jobId || jobId,
        resumeJobId: null,
        jobProgress: {
          currentBar: st.currentBar || 0,
          totalBars: st.totalBars || 0,
          percent: st.percent ?? null,
        },
        errorMessage: null,
      }));
    } catch (error: any) {
      const message = String(error?.response?.data?.detail || error?.message || '继续回测失败');
      updateInstance(instanceId, (instance) => ({
        ...instance,
        status: target.status,
        activeJobId: null,
        resumeJobId: jobId || null,
        errorMessage: message,
      }));
      showThemeAlert('继续回测失败', message, 'danger');
    }
  };

  const fmt = (n: number | undefined | null, d = 2) => n == null ? '-' : n.toFixed(d);
  const fmtPct = (n: number | undefined | null) => n == null ? '-' : `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;

  const hasResult = result && result.status === 'completed';
  const resultDataInvalidated = result?.dataQualityStatus === 'invalidated';
  const resultAssetClass = backtestResultAssetClass(strategies, result, selectedStrategy);
  const renderBacktestKlineReview = ({
    height = 520,
  }: { height?: number } = {}) => (
    <section className="rounded-xl border border-crypto-border bg-crypto-card/80 p-4">
      <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h4 className="text-sm font-semibold text-white">买卖点 K线复盘</h4>
          <p className="mt-1 text-xs text-gray-500">
            复用盯盘 K 线风格展示回测成交 B/S 点，K 线按策略周期读取真实历史行情。
          </p>
        </div>
        {tradeChartSymbols.length > 1 && (
          <div className="backtestKlineSymbolChips flex flex-wrap gap-2 lg:max-w-[78%] lg:justify-end">
            {tradeChartSymbols.map((symbol) => (
              <button
                key={symbol}
                type="button"
                onClick={() => setSelectedTradeChartSymbol(symbol)}
                className={clsx(
                  'inline-flex h-9 items-center rounded-full border px-4 text-xs font-semibold tabular-nums transition-colors',
                  selectedTradeChartSymbol === symbol
                    ? SELECTED_SEGMENT_BORDER_CLASS
                    : 'border-crypto-border bg-crypto-card/75 text-gray-500 hover:border-blue-500/40 hover:bg-blue-500/10 hover:text-gray-200',
                )}
              >
                {symbol}
              </button>
            ))}
          </div>
        )}
      </div>
      {tradeChartLoading ? (
        <div style={{ height }} className="flex items-center justify-center text-sm text-gray-500">
          <Loader2 className="mr-2 h-4 w-4 animate-spin text-blue-400" />
          正在加载回测 K 线...
        </div>
      ) : tradeChartError ? (
        <div className="flex h-[220px] items-center justify-center rounded-xl border border-red-500/20 bg-red-500/5 text-sm text-red-300">
          {tradeChartError}
        </div>
      ) : tradeChartKlines.length > 0 && selectedTradeChartSymbol ? (
        <Suspense fallback={<div style={{ height }} className="flex items-center justify-center text-sm text-gray-500">K 线图加载中...</div>}>
          <WatchKlineChart
            data={tradeChartKlines}
            markers={tradeChartMarkers}
            symbol={selectedTradeChartSymbol}
            timeframe={resultStrategyTimeframe}
            height={height}
          />
        </Suspense>
      ) : (
        <div className="flex h-[220px] items-center justify-center rounded-xl border border-crypto-border bg-crypto-card/60 text-sm text-gray-500">
          暂无 K 线复盘数据
        </div>
      )}
    </section>
  );

  // 计算基准收益率和贝塔 (基于benchmarkKlines)
  const benchmarkStats = useMemo(() => {
    if (!hasResult || !benchmarkKlines || benchmarkKlines.length < 2 || !result?.equityCurve?.length) {
      return { benchmarkReturn: null, beta: null, alpha: null };
    }

    const eq = [...result.equityCurve].sort((a, b) => a.timestamp - b.timestamp);
    const rangeStart = dateToStartMs(result.startDate || startDate);
    const rangeEnd = dateToEndMs(result.endDate || endDate);
    const sorted = [...benchmarkKlines]
      .filter((k) => k.timestamp >= rangeStart && k.timestamp <= rangeEnd)
      .sort((a, b) => a.timestamp - b.timestamp);
    if (sorted.length < 2) return { benchmarkReturn: null, beta: null, alpha: null };
    const firstClose = sorted[0].close;
    const lastClose = sorted[sorted.length - 1].close;
    const benchmarkReturn = ((lastClose - firstClose) / firstClose) * 100;

    const strategyTotalReturn =
      result.totalReturn ??
      (eq[0]?.equity > 0 ? ((eq[eq.length - 1].equity - eq[0].equity) / eq[0].equity) * 100 : null);
    const alpha = strategyTotalReturn == null ? null : strategyTotalReturn - benchmarkReturn;

    // 计算贝塔：用同一批 1D 基准 K 线时间点对齐策略权益，Cov(策略日收益, 基准日收益) / Var(基准日收益)
    if (eq.length < 3) return { benchmarkReturn, beta: null, alpha };

    let equityCursor = 0;
    const equityAtOrBefore = (timestamp: number): number | null => {
      while (equityCursor + 1 < eq.length && eq[equityCursor + 1].timestamp <= timestamp) {
        equityCursor += 1;
      }
      return eq[equityCursor]?.timestamp <= timestamp ? eq[equityCursor].equity : null;
    };
    const strategyReturns: number[] = [];
    const benchReturns: number[] = [];
    let prevEquity = equityAtOrBefore(sorted[0].timestamp);
    let prevClose = sorted[0].close;
    for (let i = 1; i < sorted.length; i++) {
      const currentEquity = equityAtOrBefore(sorted[i].timestamp);
      const currentClose = sorted[i].close;
      if (prevEquity != null && currentEquity != null && prevEquity > 0 && prevClose > 0) {
        strategyReturns.push((currentEquity - prevEquity) / prevEquity);
        benchReturns.push((currentClose - prevClose) / prevClose);
      }
      if (currentEquity != null) prevEquity = currentEquity;
      prevClose = currentClose;
    }

    // 协方差和方差
    const n = Math.min(strategyReturns.length, benchReturns.length);
    if (n < 2) return { benchmarkReturn, beta: null, alpha };

    const meanS = strategyReturns.slice(0, n).reduce((a, b) => a + b, 0) / n;
    const meanB = benchReturns.slice(0, n).reduce((a, b) => a + b, 0) / n;
    let cov = 0, varB = 0;
    for (let i = 0; i < n; i++) {
      cov += (strategyReturns[i] - meanS) * (benchReturns[i] - meanB);
      varB += (benchReturns[i] - meanB) ** 2;
    }
    cov /= n;
    varB /= n;

    const beta = varB > 0 ? cov / varB : 0;

    return { benchmarkReturn, beta, alpha };
  }, [hasResult, benchmarkKlines, result, startDate, endDate]);
  const performanceMetrics = useMemo(() => (
    hasResult && result ? buildBacktestPerformanceMetrics(result) : null
  ), [hasResult, result]);

  const detailStatusMeta = backtestInstanceStatusMeta(
    historyDetailResult ? 'completed' : selectedInstance?.status ?? 'idle',
  );
  const detailDataQualityMeta = backtestDataQualityStatusMeta(result?.dataQualityStatus);
  const detailStrategyName = backtestStrategyDisplayName(
    strategies,
    result?.strategyId ?? selectedStrategy,
    result?.strategyName || selectedInstance?.name,
  );
  const monthlyReturnEntries = result?.monthlyReturns
    ? Object.entries(result.monthlyReturns).sort(([left], [right]) => left.localeCompare(right))
    : [];
  const totalTradesCount = result?.totalTrades ?? result?.trades?.length ?? 0;
  const avgFeePerTrade =
    result?.totalFees != null && totalTradesCount > 0
      ? result.totalFees / totalTradesCount
      : null;
  const backtestVerdictMetrics = result ? [
    {
      label: '净收益',
      numeric: result.totalReturn ?? null,
      format: fmtPct,
      valueClassName: result.totalReturn == null ? 'text-gray-400' : (result.totalReturn >= 0 ? 'text-up' : 'text-down'),
      caption: '策略累计收益',
    },
    {
      label: '超额收益',
      numeric: benchmarkStats.alpha,
      format: fmtPct,
      valueClassName: benchmarkStats.alpha == null ? 'text-gray-400' : (benchmarkStats.alpha >= 0 ? 'text-up' : 'text-down'),
      caption: `相对 ${benchmarkSymbol}`,
    },
    {
      label: '最大回撤',
      numeric: result.maxDrawdown ?? null,
      format: (value: number) => `${value.toFixed(2)}%`,
      valueClassName: result.maxDrawdown == null ? 'text-gray-400' : 'text-down',
      caption: '权益最深回落',
    },
    {
      label: '夏普',
      numeric: result.sharpeRatio ?? null,
      format: (value: number) => value.toFixed(2),
      valueClassName: result.sharpeRatio == null ? 'text-gray-400' : (result.sharpeRatio >= 1 ? 'text-up' : 'text-down'),
      caption: '风险调整收益',
    },
  ] : [];
  const backtestMetricRows = result ? [
    {
      title: '收益',
      description: '判决带之外的资金与基准拆解。',
      icon: <DollarSign className="h-4 w-4 shrink-0" />,
      toneClassName: 'border-blue-500/40',
      titleClassName: 'text-blue-300',
      metrics: [
        {
          label: '年化收益',
          value: fmtPct(result.annualReturn),
          valueClassName: result.annualReturn == null ? 'text-gray-400' : (result.annualReturn >= 0 ? 'text-up' : 'text-down'),
          caption: '按样本天数折算',
        },
        {
          label: '期末权益',
          value: result.finalCapital != null ? `¥${fmt(result.finalCapital)}` : '-',
          valueClassName: result.finalCapital == null ? 'text-gray-400' : (result.finalCapital >= result.initialCapital ? 'text-up' : 'text-down'),
          caption: '回测结束资金',
        },
        {
          label: `${benchmarkSymbol} 同期`,
          value: benchmarkStats.benchmarkReturn != null ? fmtPct(benchmarkStats.benchmarkReturn) : '-',
          valueClassName: benchmarkStats.benchmarkReturn == null ? 'text-gray-400' : (benchmarkStats.benchmarkReturn >= 0 ? 'text-up' : 'text-down'),
          caption: '市场基准',
        },
        {
          label: '手续费',
          value: result.totalFees != null ? `¥${fmt(result.totalFees)}` : '-',
          valueClassName: result.totalFees == null ? 'text-gray-400' : 'text-gray-200',
          caption: '总交易成本',
        },
      ],
    },
    {
      title: '风险',
      description: '回撤恢复、波动和基准敏感度。',
      icon: <AlertTriangle className="h-4 w-4 shrink-0" />,
      toneClassName: 'border-amber-500/40',
      titleClassName: 'text-amber-300',
      metrics: [
        {
          label: 'Calmar',
          value: fmt(performanceMetrics?.calmarRatio),
          valueClassName: performanceMetrics?.calmarRatio == null ? 'text-gray-400' : (performanceMetrics.calmarRatio >= 1 ? 'text-up' : 'text-down'),
          caption: '年化 / 回撤',
        },
        {
          label: 'Sortino',
          value: fmt(performanceMetrics?.sortinoRatio),
          valueClassName: performanceMetrics?.sortinoRatio == null ? 'text-gray-400' : (performanceMetrics.sortinoRatio >= 1 ? 'text-up' : 'text-down'),
          caption: '下行风险调整',
        },
        {
          label: '年化波动',
          value: performanceMetrics?.annualizedVolatility != null ? `${fmt(performanceMetrics.annualizedVolatility)}%` : '-',
          valueClassName: 'text-amber-200',
          caption: '权益波动',
        },
        {
          label: 'Beta',
          value: benchmarkStats.beta != null ? fmt(benchmarkStats.beta) : '-',
          valueClassName: 'text-blue-200',
          caption: '市场敏感度',
        },
        {
          label: '回撤持续',
          value: `${result.maxDrawdownDurationDays || 0} 天`,
          valueClassName: 'text-amber-200',
          caption: '恢复压力',
        },
      ],
    },
    {
      title: '交易',
      description: '胜率、赔率和成交样本。',
      icon: <List className="h-4 w-4 shrink-0" />,
      toneClassName: 'border-emerald-500/40',
      titleClassName: 'text-emerald-300',
      metrics: [
        {
          label: '胜率',
          value: result.winRate != null ? `${fmt(result.winRate)}%` : '-',
          valueClassName: result.winRate == null ? 'text-gray-400' : 'text-blue-200',
          caption: '闭合交易',
        },
        {
          label: '盈亏比',
          value: fmt(result.profitFactor),
          valueClassName: result.profitFactor == null ? 'text-gray-400' : (result.profitFactor >= 1 ? 'text-up' : 'text-down'),
          caption: '利润因子',
        },
        {
          label: '赔率',
          value: performanceMetrics?.payoffRatio != null ? fmt(performanceMetrics.payoffRatio) : '-',
          valueClassName: (performanceMetrics?.payoffRatio ?? 0) >= 1 ? 'text-up' : 'text-down',
          caption: '盈亏幅度',
        },
        {
          label: '期望/笔',
          value: performanceMetrics?.expectancy != null ? `¥${fmt(performanceMetrics.expectancy)}` : '-',
          valueClassName: performanceMetrics?.expectancy == null ? 'text-gray-400' : (performanceMetrics.expectancy >= 0 ? 'text-up' : 'text-down'),
          caption: '单笔期望',
        },
        {
          label: '盈利/亏损',
          value: `${result.winningTrades || 0} / ${result.losingTrades || 0}`,
          valueClassName: 'text-white',
          caption: '笔数结构',
        },
        {
          label: '交易数',
          value: `${totalTradesCount} 笔`,
          valueClassName: 'text-white',
          caption: '成交样本',
        },
      ],
    },
  ] : [];
  const drawdownGateLabel = result?.maxDrawdown == null ? '样本不足' : result.maxDrawdown >= 20 ? '回撤偏深' : '回撤可接受';
  const calmarGateLabel = performanceMetrics?.calmarRatio == null ? '样本不足' : performanceMetrics.calmarRatio >= 1 ? '收益回撤比通过' : '收益回撤比偏弱';
  const sortinoGateLabel = performanceMetrics?.sortinoRatio == null ? '样本不足' : performanceMetrics.sortinoRatio >= 1 ? '下行风险通过' : '下行风险偏弱';
  const benchmarkGateLabel = resultDataInvalidated
    ? '不可采信'
    : benchmarkStats.alpha == null
      ? '基准不足'
      : benchmarkStats.alpha >= 0
        ? `跑赢 ${benchmarkSymbol}`
        : `跑输 ${benchmarkSymbol}`;
  const metricGuideItems = [
    {
      label: '夏普',
      formula: '日收益均值 / 日收益标准差 × √252',
      description: '衡量单位波动换来的收益；列表比较时用它看风险调整后的稳定性。',
    },
    {
      label: '净收益',
      formula: '策略累计收益率',
      description: '期末权益相对初始本金的涨跌幅，衡量这次回测最终赚亏了多少。',
    },
    {
      label: '年化收益',
      formula: '累计收益按样本天数折算到一年',
      description: '把本次回测收益按时间长度折算成一年口径，便于不同区间横向比较。',
    },
    {
      label: '最大回撤',
      formula: '权益峰值到之后最低点的最大跌幅',
      description: '衡量过程中最深的一段资金回落，通常越低越稳。',
    },
    {
      label: '回撤持续',
      formula: '最大回撤区间持续天数',
      description: '衡量资金从高点回落后承受压力的时间长度，越长说明资金恢复越慢。',
    },
    {
      label: 'Calmar',
      formula: '年化收益 / 最大回撤',
      description: '衡量单位回撤换来的年化收益，越高说明收益回撤比越好；最大回撤很小时该值会被放大。',
    },
    {
      label: '胜率',
      formula: '盈利闭合交易数 / 闭合交易数',
      description: '只看已闭合交易中赚钱的比例，胜率高不代表整体一定赚钱。',
    },
    {
      label: '盈亏比',
      formula: '总盈利 / 总亏损',
      description: '也叫利润因子，大于 1 表示盈利交易总额覆盖了亏损交易总额。',
    },
    {
      label: '交易数',
      formula: '回测成交样本数',
      description: '衡量样本量。交易数太少时，收益、胜率和盈亏比都更容易失真。',
    },
    {
      label: '期末权益',
      formula: '回测结束时账户权益',
      description: '包含已实现收益、剩余现金和持仓估值后的最终资金规模。',
    },
    {
      label: '手续费',
      formula: '全部成交费用合计',
      description: '回测期间累计交易成本，用来判断策略收益是否被换手成本吞掉。',
    },
    {
      label: `${benchmarkSymbol} 同期`,
      formula: '沪深300同区间收盘到收盘收益',
      description: '用同一回测起止日期的沪深300未复权日线作为市场基准。',
    },
    {
      label: '超额收益',
      formula: '策略累计收益 - 沪深300同期收益',
      description: '衡量策略是否跑赢基准，而不是只看自己绝对收益。',
    },
    {
      label: 'Beta',
      formula: 'Cov(策略日收益, 基准日收益) / Var(基准日收益)',
      description: '衡量策略对沪深300基准波动的敏感度，绝对值越大越接近市场系统性风险。',
    },
    {
      label: '年化波动',
      formula: '权益收益波动按年化折算',
      description: '衡量权益曲线抖动幅度，波动越大，持有体验和风险越不稳定。',
    },
    {
      label: 'Sortino',
      formula: '超额收益 / 下行波动',
      description: '只惩罚亏损方向波动的风险调整收益，比 Sharpe 更关注下跌风险。',
    },
    {
      label: '赔率',
      formula: '平均盈利幅度 / 平均亏损幅度',
      description: '衡量单笔赚的时候通常赚多大、亏的时候通常亏多大。',
    },
    {
      label: '期望/笔',
      formula: '单笔交易平均盈亏',
      description: '把盈利、亏损和胜率合在一起看，判断每笔交易长期平均贡献。',
    },
    {
      label: '平均盈利',
      formula: '盈利交易平均收益率',
      description: '只统计赚钱样本的平均收益，用来观察获利空间。',
    },
    {
      label: '平均亏损',
      formula: '亏损交易平均收益率',
      description: '只统计亏钱样本的平均亏损，用来观察止损和亏损尾部。',
    },
    {
      label: '盈利/亏损',
      formula: '盈利笔数 / 亏损笔数',
      description: '展示盈利亏损笔数，避免只看百分比时忽略实际数量。',
    },
    {
      label: '最大连胜/连亏',
      formula: '最长连续盈利笔数 / 最长连续亏损笔数',
      description: '衡量策略节奏和心理压力，连亏过长会影响实际执行稳定性。',
    },
    {
      label: '交易频率',
      formula: '成交笔数 / 回测天数',
      description: '衡量换手密度，频率越高越需要关注手续费、滑点和执行压力。',
    },
    {
      label: '平均持仓',
      formula: '持仓持续 K 线数均值',
      description: '衡量策略平均拿多久，单位跟本次回测周期一致。',
    },
    {
      label: '回测天数',
      formula: '结束日期 - 开始日期',
      description: '衡量样本时间长度，短窗口结果更容易受单段行情影响。',
    },
    {
      label: 'K线样本',
      formula: '参与回测的 K 线数量',
      description: '衡量行情数据规模，样本不足时统计指标可信度会下降。',
    },
    {
      label: '盈利/月亏',
      formula: '盈利月份数 / 亏损月份数',
      description: '观察收益是否集中在少数月份，还是跨月份更稳定。',
    },
    {
      label: '执行耗时',
      formula: '本次回测计算用时',
      description: '用于判断任务复杂度和性能，不代表策略收益质量。',
    },
  ];
  const metricGuideByLabel = new Map(metricGuideItems.map((item) => [item.label, item]));
  const renderMetricHelp = (label: string) => {
    const guide = metricGuideByLabel.get(label);
    if (!guide) return null;
    const helpId = `backtestMetricHelp-${label.replace(/[^\w\u4e00-\u9fa5]+/g, '-')}`;
    return (
      <span className="backtestMetricHelp group relative inline-flex shrink-0">
        <button
          type="button"
          aria-label={`${label}指标说明`}
          aria-describedby={helpId}
          className="inline-flex h-5 w-5 items-center justify-center text-gray-500 transition-colors hover:text-blue-200 focus:text-blue-100 focus:outline-none"
        >
          <HelpCircle className="h-3.5 w-3.5" />
        </button>
        <span
          id={helpId}
          role="tooltip"
          className="pointer-events-none absolute right-0 top-7 z-30 hidden w-64 rounded-lg border border-crypto-border bg-crypto-bg p-3 text-left shadow-xl shadow-black/30 group-hover:block group-focus-within:block"
        >
          <span className="block text-xs font-semibold text-white">{guide.label}</span>
          <span className="mt-1 inline-flex rounded bg-crypto-card px-1.5 py-0.5 text-[10px] font-medium text-gray-400">
            {guide.formula}
          </span>
          <span className="mt-2 block text-xs leading-5 text-gray-500">{guide.description}</span>
        </span>
      </span>
    );
  };
  const renderVerdictMetric = (
    metric: { label: string; numeric: number | null; format: (value: number) => string; valueClassName: string; caption: string },
  ) => (
    <div
      key={metric.label}
      className="backtestVerdictMetric min-w-0 rounded-xl border border-crypto-border bg-crypto-card px-4 py-3"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 text-xs font-medium leading-5 text-gray-500">{metric.label}</div>
        {renderMetricHelp(metric.label)}
      </div>
      <AnimatedNumber
        value={metric.numeric}
        format={metric.format}
        className={clsx('mt-2 block text-2xl font-bold leading-7 tabular-nums', metric.valueClassName)}
      />
      <div className="mt-1.5 text-[11px] text-gray-500">{metric.caption}</div>
    </div>
  );
  const renderMetricRow = (
    metric: { label: string; value: string; valueClassName: string; caption: string },
  ) => (
    <div
      key={metric.label}
      className="backtestDetailMetricRow flex items-start justify-between gap-3 border-b border-crypto-border/70 py-2 last:border-b-0"
    >
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-gray-500">{metric.label}</span>
          {renderMetricHelp(metric.label)}
        </div>
        <div className="mt-0.5 text-[11px] text-gray-600">{metric.caption}</div>
      </div>
      <div className={clsx('shrink-0 text-sm font-semibold tabular-nums', metric.valueClassName)}>
        {metric.value}
      </div>
    </div>
  );
  const renderFilterGroup = (
    title: string,
    options: Array<{ value: string; label: string }>,
    activeValue: string,
    counts: Record<string, number> | null,
    onSelect: (value: any) => void,
  ) => (
    <div className="rounded-xl border border-crypto-border bg-crypto-card p-3">
      <div className="mb-2 px-1 text-[11px] font-semibold tracking-wide text-gray-500">{title}</div>
      <div className="space-y-1">
        {options.map((option) => {
          const active = activeValue === option.value;
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={active}
              onClick={() => onSelect(option.value)}
              className={clsx(
                'flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors',
                active ? SELECTED_SEGMENT_CLASS : 'text-gray-400 hover:bg-white/5 hover:text-gray-200',
              )}
            >
              <span>{option.label}</span>
              {counts && (
                <span
                  className={clsx(
                    'rounded-md px-1.5 py-0.5 text-[10px] tabular-nums',
                    active ? SELECTED_SEGMENT_COUNT_CLASS : 'bg-crypto-bg text-gray-500',
                  )}
                >
                  {counts[option.value] ?? 0}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
  const renderFilterChip = (
    key: string,
    active: boolean,
    label: string,
    count: number | undefined,
    onClick: () => void,
  ) => (
    <button
      key={key}
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={clsx(
        'inline-flex shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-semibold transition-colors',
        active
          ? SELECTED_SEGMENT_BORDER_CLASS
          : 'border-crypto-border bg-crypto-card text-gray-400 hover:border-gray-600 hover:text-gray-200',
      )}
    >
      <span>{label}</span>
      {count != null && (
        <span
          className={clsx(
            'rounded-md px-1 py-0.5 text-[10px] tabular-nums',
            active ? SELECTED_SEGMENT_COUNT_CLASS : 'bg-crypto-bg text-gray-500',
          )}
        >
          {count}
        </span>
      )}
    </button>
  );
  const renderSortHeader = (label: string, field: 'return' | 'drawdown' | 'created' | 'win_rate') => {
    const direction = backtestSortDirectionFor(instanceSortMode, field);
    return (
      <button
        type="button"
        onClick={() => setInstanceSortMode(nextBacktestSortMode(instanceSortMode, field))}
        className={clsx(
          'inline-flex items-center gap-1 transition-colors',
          direction ? 'text-yellow-100' : 'hover:text-gray-300',
        )}
      >
        {label}
        <BacktestSortArrow direction={direction} />
      </button>
    );
  };

  return (
    <div className="h-full w-full min-w-0 p-6">
      {view === 'dashboard' ? (
        <div className="space-y-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
                <FlaskConical className="h-6 w-6 text-blue-400" />
                回测
              </h1>
              <p className="mt-1 text-sm text-gray-500">
                创建异步任务，在列表比较结果，打开详情复盘路径和成交。
              </p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <button
                type="button"
                aria-label="创建批量回测实例"
                onClick={() => setBatchBacktestConfirmOpen(true)}
                disabled={isBatchBacktestSubmitting}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-crypto-border bg-crypto-card px-4 py-2.5 text-sm font-semibold text-gray-200 transition-colors hover:border-blue-500/50 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isBatchBacktestSubmitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <ListChecks className="h-4 w-4" />
                )}
                批量回测
              </button>
              <button
                type="button"
                aria-label="创建回测实例"
                onClick={addBacktestInstance}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-blue-500/70 bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-blue-950/25 transition-colors hover:border-blue-400 hover:bg-blue-500"
              >
                <Plus className="h-4 w-4" />
                创建回测
              </button>
            </div>
          </div>

          {shouldRenderBacktestInstances && (
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
              {/* 移动端筛选 chips（lg 以下显示） */}
              <div className="space-y-2 lg:hidden">
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {BACKTEST_STATUS_FILTERS.map((option) =>
                    renderFilterChip(
                      option.value,
                      instanceStatusFilter === option.value,
                      option.label,
                      instanceStatusCounts[option.value],
                      () => setInstanceStatusFilter(option.value),
                    ),
                  )}
                </div>
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {HISTORY_ASSET_FILTERS.map((option) =>
                    renderFilterChip(
                      option.value,
                      instanceAssetFilter === option.value,
                      option.label,
                      instanceAssetCounts[option.value],
                      () => setInstanceAssetFilter(option.value),
                    ),
                  )}
                </div>
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {instanceTimeframeFilterOptions.map((option) =>
                    renderFilterChip(option.value, instanceTimeframeFilter === option.value, option.label, undefined, () =>
                      setInstanceTimeframeFilter(option.value),
                    ),
                  )}
                </div>
              </div>

              {/* 桌面左侧筛选栏 */}
              <aside className="hidden w-52 shrink-0 space-y-3 lg:block">
                {renderFilterGroup('状态', BACKTEST_STATUS_FILTERS, instanceStatusFilter, instanceStatusCounts, setInstanceStatusFilter)}
                {renderFilterGroup('资产', HISTORY_ASSET_FILTERS, instanceAssetFilter, instanceAssetCounts, setInstanceAssetFilter)}
                {renderFilterGroup('周期', instanceTimeframeFilterOptions, instanceTimeframeFilter, null, setInstanceTimeframeFilter)}
              </aside>

              <div className="min-w-0 flex-1 space-y-3">
                {compareSelection.length > 0 && (
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-yellow-400/40 bg-yellow-500/10 px-4 py-2.5">
                    <span className="text-xs font-semibold text-yellow-100">
                      已选择 {compareSelection.length} / 4 条 · 勾选 2–4 条可发起对比
                    </span>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setCompareOpen(true)}
                        disabled={compareSelection.length < 2}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-700 disabled:text-gray-500"
                      >
                        <Layers className="h-3.5 w-3.5" />
                        对比选中
                      </button>
                      <button
                        type="button"
                        onClick={() => setCompareSelection([])}
                        className="rounded-lg border border-crypto-border px-3 py-1.5 text-xs font-semibold text-gray-400 transition-colors hover:text-gray-200"
                      >
                        清空
                      </button>
                    </div>
                  </div>
                )}

                <div className="rounded-xl border border-crypto-border bg-crypto-card p-4">
                  <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
                      <h2 className="flex shrink-0 items-center gap-2 text-sm font-semibold text-white">
                        <Layers className="h-4 w-4 text-purple-400" />
                        回测实例
                        <span className="text-[11px] font-normal text-gray-500">{filteredBacktestInstances.length} / {unifiedBacktestInstances.length} 个</span>
                      </h2>
                      <div className="relative min-w-[220px] flex-1 sm:max-w-sm lg:max-w-md">
                        <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                        <input
                          type="search"
                          value={instanceSearchQuery}
                          onChange={(event) => setInstanceSearchQuery(event.target.value)}
                          placeholder="搜索回测实例、策略、标的、周期..."
                          className="h-10 w-full rounded-xl border border-crypto-border bg-crypto-bg/60 pl-10 pr-10 text-sm text-white outline-none transition-colors placeholder:text-gray-600 focus:border-blue-500/70 focus:ring-2 focus:ring-blue-500/10"
                          aria-label="搜索回测实例"
                        />
                        {instanceSearchQuery && (
                          <button
                            type="button"
                            aria-label="清空回测实例搜索"
                            onClick={() => setInstanceSearchQuery('')}
                            className="absolute right-2 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-lg text-gray-500 transition-colors hover:bg-white/5 hover:text-gray-200"
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => void loadBacktestHistory({ reset: true })}
                      disabled={isLoadingHistory || isLoadingMoreHistory}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-crypto-border px-3 py-2 text-xs text-gray-300 transition-colors hover:border-blue-500/60 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <RefreshCw className={clsx('h-3.5 w-3.5', isLoadingHistory && 'animate-spin')} />
                      刷新记录
                    </button>
                  </div>

                  {historyError ? (
                    <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
                      {historyError}
                    </div>
                  ) : isLoadingHistory && filteredBacktestInstances.length === 0 ? (
                    <div className="flex items-center gap-2 rounded-lg border border-crypto-border bg-crypto-bg/40 px-3 py-3 text-xs text-gray-500">
                      <Loader2 className="h-4 w-4 animate-spin text-blue-400" />
                      正在加载回测记录…
                    </div>
                  ) : filteredBacktestInstances.length === 0 ? (
                    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-crypto-border py-16 text-sm text-gray-500">
                      <FlaskConical className="mb-3 h-10 w-10 opacity-40" />
                      当前筛选下暂无回测实例。
                    </div>
                  ) : (
                    <div data-testid="backtest-history-table" className="overflow-x-auto">
                      <table className="w-full min-w-[1180px] text-left text-sm">
                        <thead className="border-b border-crypto-border text-[11px] text-gray-500">
                          <tr>
                            <th className="w-10 px-2 py-2.5 font-medium">对比</th>
                            <th className="px-2 py-2.5 font-medium">策略 / 标的</th>
                            <th className="px-2 py-2.5 font-medium">周期</th>
                            <th className="px-2 py-2.5 font-medium">区间</th>
                            <th className="px-2 py-2.5 text-right font-medium">{renderSortHeader('收益', 'return')}</th>
                            <th className="px-2 py-2.5 text-right font-medium">{renderSortHeader('回撤', 'drawdown')}</th>
                            <th className="px-2 py-2.5 text-right font-medium">夏普</th>
                            <th className="px-2 py-2.5 text-right font-medium">交易</th>
                            <th className="px-2 py-2.5 font-medium">状态</th>
                            <th className="px-2 py-2.5 font-medium">{renderSortHeader('创建时间', 'created')}</th>
                            <th className="px-2 py-2.5 text-right font-medium">操作</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-crypto-border/60">
                          {filteredBacktestInstances.map((instance, rowIndex) => {
                            const meta = backtestInstanceStatusMeta(instance.status);
                            const actionStatusLabel = backtestInstanceActionStatusLabel(instance.status);
                            const strategyInfoForInstance = backtestableStrategies.find((s) => Number(s.id) === Number(instance.config.selectedStrategy));
                            const assetClass = backtestInstanceAssetClass(backtestableStrategies, instance);
                            const strategyLabel = backtestStrategyDisplayName(
                              strategies,
                              instance.config.selectedStrategy,
                              instance.result?.strategyName || instance.name,
                            );
                            const instanceTimeframes = backtestInstanceTimeframes(instance, strategyInfoForInstance);
                            const instanceRunning = instance.status === 'running' || instance.status === 'cancelling';
                            const instanceResumable = backtestInstanceCanContinue(instance);
                            const hasBacktestError = Boolean(instance.errorMessage || instance.result?.errorMessage || instance.status === 'failed');
                            const returnPct = backtestInstanceReturn(instance);
                            const progress = instance.jobProgress;
                            const instanceDataInvalidated = instance.result?.dataQualityStatus === 'invalidated';
                            const historyRecordBusy =
                              instance.historyId != null &&
                              (selectedHistoryId === instance.historyId || deletingHistoryId === instance.historyId);
                            const selectedRecord =
                              selectedInstance?.id === instance.id ||
                              (historyDetailResult?.id != null && instance.historyId === Number(historyDetailResult.id));
                            const selectedForCompare = compareSelection.includes(instance.id);
                            return (
                              <tr
                                key={instance.id}
                                onClick={() => openBacktestRecordDetail(instance)}
                                className={clsx(
                                  'row-enter cursor-pointer transition-colors hover:bg-white/[0.03]',
                                  selectedForCompare && 'bg-yellow-500/[0.06]',
                                  selectedRecord && !selectedForCompare && 'bg-blue-500/[0.05]',
                                )}
                                style={{ animationDelay: `${Math.min(rowIndex * 25, 250)}ms` }}
                              >
                                <td className="px-2 py-2.5 align-middle" onClick={(event) => event.stopPropagation()}>
                                  <input
                                    type="checkbox"
                                    aria-label={`选择 ${strategyLabel} 参与对比`}
                                    checked={selectedForCompare}
                                    onChange={() => toggleCompareSelection(instance.id)}
                                    className="h-3.5 w-3.5 accent-blue-500"
                                  />
                                </td>
                                <td className="max-w-[320px] px-2 py-2.5 align-middle">
                                  <div className={clsx('break-words text-[13px] font-semibold leading-snug', strategyNameColorClass(assetClass))}>
                                    {strategyLabel}
                                  </div>
                                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                                    <span className={clsx('rounded border px-1.5 py-0.5 text-[10px] font-bold', strategyAssetBadgeClass(assetClass))}>
                                      {assetClass === 'etf' ? 'ETF' : '股票'}
                                    </span>
                                    {instanceDataInvalidated && (
                                      <span className="rounded-full border border-red-500/40 bg-red-500/10 px-1.5 py-0.5 text-[10px] font-bold text-red-200">
                                        数据失信
                                      </span>
                                    )}
                                    <span className="text-[10px] tabular-nums text-gray-600">
                                      {instance.isPersistedHistory ? formatDateTime(instance.createdAt) : `#${instance.name.replace('回测实例 ', '')}`}
                                    </span>
                                  </div>
                                  {instanceRunning && progress && progress.totalBars > 0 && (
                                    <div className="mt-1.5 flex items-center gap-2">
                                      <div className="h-1 w-36 overflow-hidden rounded-full bg-crypto-bg">
                                        <div
                                          className={clsx('h-full transition-all duration-300', instance.status === 'running' ? 'progress-shimmer' : 'bg-purple-500/60')}
                                          style={{ width: `${Math.min(100, progress.percent ?? 0)}%` }}
                                        />
                                      </div>
                                      <span className="text-[10px] tabular-nums text-gray-500">
                                        {progress.percent != null ? `${progress.percent.toFixed(0)}%` : '准备中'}
                                      </span>
                                    </div>
                                  )}
                                </td>
                                <td className="whitespace-nowrap px-2 py-2.5 align-middle text-xs text-gray-400">
                                  {instanceTimeframes.length > 0
                                    ? instanceTimeframes.map((timeframe) => backtestTimeframeLabel(timeframe)).join(' / ')
                                    : '-'}
                                </td>
                                <td className="whitespace-nowrap px-2 py-2.5 align-middle text-[11px] tabular-nums text-gray-500">
                                  {instance.config.startDate} ~ {instance.config.endDate}
                                </td>
                                <td className={clsx('whitespace-nowrap px-2 py-2.5 text-right align-middle text-sm font-semibold tabular-nums', returnPct == null ? 'text-gray-500' : returnPct >= 0 ? 'text-up' : 'text-down')}>
                                  {returnPct == null ? '--' : fmtPct(returnPct)}
                                </td>
                                <td className="whitespace-nowrap px-2 py-2.5 text-right align-middle text-sm tabular-nums text-down">
                                  {instance.result?.maxDrawdown == null ? '--' : `${fmt(instance.result.maxDrawdown)}%`}
                                </td>
                                <td className="whitespace-nowrap px-2 py-2.5 text-right align-middle text-sm tabular-nums text-gray-200">
                                  {fmt(instance.result?.sharpeRatio)}
                                </td>
                                <td className="whitespace-nowrap px-2 py-2.5 text-right align-middle text-sm font-semibold tabular-nums text-blue-300">
                                  {instance.result?.totalTrades ?? 0}
                                </td>
                                <td className="px-2 py-2.5 align-middle">
                                  <span className={clsx('whitespace-nowrap rounded-full border px-2 py-0.5 text-[10px] font-bold', meta.className)}>
                                    {meta.label}
                                  </span>
                                </td>
                                <td className="whitespace-nowrap px-2 py-2.5 align-middle text-[11px] tabular-nums text-gray-500">
                                  {formatDateTime(instance.createdAt)}
                                </td>
                                <td className="px-2 py-2.5 align-middle" onClick={(event) => event.stopPropagation()}>
                                  <div className="flex items-center justify-end gap-1.5">
                                    <button
                                      type="button"
                                      aria-label="打开详情"
                                      onClick={() => openBacktestRecordDetail(instance)}
                                      disabled={historyRecordBusy}
                                      className={backtestInstanceActionButtonClass('blue')}
                                    >
                                      {historyRecordBusy && selectedHistoryId === instance.historyId ? <Loader2 className="h-4 w-4 animate-spin" /> : <Eye className="h-4 w-4" />}
                                      详情
                                    </button>
                                    <button
                                      type="button"
                                      aria-label={`查看回测状态：${actionStatusLabel}`}
                                      onClick={() => setBacktestStatusTarget(instance)}
                                      className={backtestInstanceActionButtonClass(backtestInstanceActionStatusTone(instance.status))}
                                    >
                                      {backtestInstanceActionStatusIcon(instance.status)}
                                      {actionStatusLabel}
                                    </button>
                                    <button
                                      type="button"
                                      aria-label="查看日志"
                                      onClick={() => setBacktestLogTarget(instance)}
                                      className={backtestInstanceActionButtonClass(hasBacktestError ? 'red' : 'neutral')}
                                    >
                                      <FileText className="h-4 w-4" />
                                      日志
                                    </button>
                                    {instanceRunning ? (
                                      <button
                                        type="button"
                                        aria-label={instance.status === 'cancelling' ? '停止中' : '停止回测'}
                                        onClick={() => void cancelBacktestInstance(instance.id)}
                                        disabled={instance.status === 'cancelling'}
                                        className={backtestInstanceActionButtonClass('red')}
                                      >
                                        {instance.status === 'cancelling' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />}
                                        {instance.status === 'cancelling' ? '停止中' : '停止'}
                                      </button>
                                    ) : (
                                      <>
                                        {instanceResumable && (
                                          <button
                                            type="button"
                                            aria-label="继续回测"
                                            onClick={() => void resumeBacktestInstance(instance.id)}
                                            className={backtestInstanceActionButtonClass('green')}
                                          >
                                            <Play className="h-4 w-4" />
                                            继续
                                          </button>
                                        )}
                                        {!instance.isPersistedHistory && !instance.historyId && <button
                                          type="button"
                                          aria-label="删除实例"
                                          onClick={() => deleteBacktestUnifiedRecord(instance)}
                                          disabled={historyRecordBusy}
                                          title="删除本地实例"
                                          className={backtestInstanceActionButtonClass('red')}
                                        >
                                          {historyRecordBusy && deletingHistoryId === instance.historyId ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                                          删除
                                        </button>}
                                      </>
                                    )}
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {historyHasMore && filteredBacktestInstances.length > 0 && (
                    <button
                      type="button"
                      onClick={() => void loadBacktestHistory({ reset: false, offset: historyItems.length })}
                      disabled={isLoadingMoreHistory}
                      className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-crypto-border bg-crypto-bg/40 px-3 py-2 text-xs font-semibold text-blue-300 transition-colors hover:border-blue-500/60 hover:bg-blue-500/10 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {isLoadingMoreHistory ? <Loader2 className="h-4 w-4 animate-spin" /> : <Layers className="h-4 w-4" />}
                      {isLoadingMoreHistory ? '正在加载更多记录…' : '加载更多回测记录'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex items-start gap-3">
                <button
                  type="button"
                  aria-label="返回回测控制台"
                  onClick={() => {
                    setHistoryDetailResult(null);
                    setView('dashboard');
                  }}
                  className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-crypto-border bg-crypto-card text-gray-300 transition-colors hover:border-gray-600 hover:text-white"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <div className="min-w-0">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <span className={clsx('rounded border px-2 py-0.5 text-[11px] font-bold', strategyAssetBadgeClass(resultAssetClass))}>
                      {resultAssetClass === 'etf' ? 'ETF' : '股票'}
                    </span>
                    <span className={clsx('rounded-full border px-2 py-0.5 text-[11px] font-bold', detailStatusMeta.className)}>
                      {historyDetailResult ? '已完成' : detailStatusMeta.label}
                    </span>
                  </div>
                  <h1 className={clsx('break-words text-2xl font-bold leading-tight', strategyNameColorClass(resultAssetClass))}>
                    {detailStrategyName}
                  </h1>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className="rounded-md border border-crypto-border bg-crypto-card px-2.5 py-1 text-xs text-gray-400">
                  回测时间范围：{result?.startDate || startDate || '-'} 至 {result?.endDate || endDate || '-'}
                </span>
                {hasResult && (
                  <>
                    <span
                      className="rounded-md border border-crypto-border bg-crypto-card px-2.5 py-1 text-xs text-gray-400"
                      title={tradeSymbols.length > 0 ? tradeSymbols.join(', ') : feedSymbols.join(', ')}
                    >
                      交易池：{symbolScopeLabel} · {backtestTimeframeLabel(result.timeframe || selectedStrategyTimeframeLabel)}
                    </span>
                    <span className={clsx('inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-semibold', detailDataQualityMeta.className)}>
                      {detailDataQualityMeta.icon}
                      数据可信度：{detailDataQualityMeta.label}
                    </span>
                  </>
                )}
              </div>
            </div>
            {!historyDetailResult && selectedInstance && (
              <div className="flex flex-wrap items-center gap-2">
                {(selectedInstance.status === 'running' || selectedInstance.status === 'cancelling') ? (
                  <button
                    type="button"
                    onClick={() => void cancelBacktestInstance(selectedInstance.id)}
                    disabled={selectedInstance.status === 'cancelling'}
                    className="inline-flex items-center justify-center gap-2 rounded-xl border border-red-500/50 px-4 py-2 text-sm font-semibold text-red-300 hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {selectedInstance.status === 'cancelling' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />}
                    {selectedInstance.status === 'cancelling' ? '停止中' : '停止回测'}
                  </button>
                ) : (
                  <>
                    {backtestInstanceCanContinue(selectedInstance) && (
                      <button
                        type="button"
                        onClick={() => void resumeBacktestInstance(selectedInstance.id)}
                        className="inline-flex items-center justify-center gap-2 rounded-xl border border-green-500/50 px-4 py-2 text-sm font-semibold text-green-300 hover:bg-green-500/10"
                      >
                        <Play className="h-4 w-4" />
                        继续回测
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => deleteBacktestInstance(selectedInstance.id)}
                      className="inline-flex items-center justify-center gap-2 rounded-xl border border-red-500/50 px-4 py-2 text-sm font-semibold text-red-300 hover:bg-red-500/10"
                    >
                      <Trash2 className="h-4 w-4" />
                      删除实例
                    </button>
                  </>
                )}
              </div>
            )}
            {historyDetailResult && (
              <button
                type="button"
                onClick={() => void loadFullHistoryEvidence()}
                disabled={isLoadingDetailEvidence}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-blue-500/40 bg-blue-500/10 px-4 py-2 text-sm font-semibold text-blue-200 hover:bg-blue-500/15 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isLoadingDetailEvidence ? <Loader2 className="h-4 w-4 animate-spin" /> : <ListChecks className="h-4 w-4" />}
                {isLoadingDetailEvidence ? '加载证据中…' : '加载完整证据'}
              </button>
            )}
          </div>

          {!hasResult ? (
            <div className="bg-crypto-card border border-crypto-border rounded-xl flex flex-col items-center justify-center py-24 px-6 text-center">
              {isRunning ? (
                <>
                  <Loader2 className="w-14 h-14 text-blue-500 mb-4 animate-spin" />
                  <p className="text-white text-sm font-medium">{isCancelling ? '回测停止中' : '回测进行中'}</p>
                  {jobProgress && jobProgress.totalBars > 0 ? (
                    <p className="text-gray-400 text-xs mt-2 tabular-nums">
                      {jobProgress.currentBar} / {jobProgress.totalBars} 根 K 线
                      {jobProgress.percent != null ? `（${jobProgress.percent.toFixed(1)}%）` : ''}
                    </p>
                  ) : (
                    <p className="text-gray-500 text-xs mt-2">正在加载行情与初始化引擎…</p>
                  )}
                </>
              ) : (
                <>
                  {selectedInstance?.status === 'failed' ? (
                    <>
                      <FileText className="mb-4 h-16 w-16 text-red-500/50" />
                      <p className="text-sm font-medium text-red-300">回测失败</p>
                      <p className="mt-2 text-xs text-gray-500">在实例列表点击「日志」查看失败原因。</p>
                    </>
                  ) : (
                    <>
                      <FlaskConical className="w-16 h-16 text-gray-700 mb-4" />
                      <p className="text-gray-500 text-sm">选择策略并运行回测后查看绩效报告</p>
                    </>
                  )}
                </>
              )}
            </div>
          ) : (
            <>
              {/* ====== 专业回测报告壳 ====== */}
              {resultDataInvalidated && (
                <div className="rounded-xl border border-red-500/20 bg-red-500/[0.08] px-5 py-3 text-xs text-red-200">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    <div>
                      <div className="font-semibold">历史结果不可继续信任</div>
                      <div className="mt-1 text-red-200/75">
                        {result.dataQualityMessage || '该回测覆盖了已审计出的 K 线污染窗口，需要重建行情缓存后重新运行。'}
                        {result.dataQualityCheckedAt ? ` 审计时间：${formatDateTime(result.dataQualityCheckedAt)}` : ''}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {matrixPeriodResults.length > 0 && (
                <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
                  <div className="flex flex-col gap-3 border-b border-crypto-border px-5 py-4 xl:flex-row xl:items-center xl:justify-between">
                    <div>
                      <div className="text-sm font-semibold text-white">多周期矩阵</div>
                      <div className="mt-0.5 text-xs text-gray-500">下方报告已切换到当前选中的周期详情。</div>
                    </div>
                    <div className="backtestMatrixTimeframeTabs flex flex-wrap items-center gap-2">
                      <span className="text-xs font-semibold text-gray-500">周期详情</span>
                      {matrixPeriodResults.map((item) => {
                        const active = activeMatrixTimeframe === item.timeframe;
                        return (
                          <button
                            key={item.timeframe || item.status}
                            type="button"
                            aria-pressed={active}
                            onClick={() => setActiveMatrixTimeframe(item.timeframe || '')}
                            className={clsx(
                              'inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors',
                              active
                                ? SELECTED_SEGMENT_BORDER_CLASS
                                : 'border-crypto-border bg-crypto-bg/55 text-gray-500 hover:border-purple-500/40 hover:text-gray-200',
                            )}
                          >
                            <span>{backtestTimeframeLabel(item.timeframe)}</span>
                            <span className={clsx('tabular-nums', (item.totalReturn ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                              {fmtPct(item.totalReturn)}
                            </span>
                          </button>
                        );
                      })}
                      <span className="rounded bg-purple-500/10 px-2 py-1 text-xs text-purple-300">
                        {matrixPeriodResults.length} 个周期
                      </span>
                    </div>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[720px] text-left text-xs">
                      <thead className="bg-crypto-bg/45 text-gray-500">
                        <tr>
                          <th className="px-4 py-2 font-medium">周期</th>
                          <th className="px-4 py-2 font-medium">状态</th>
                          <th className="px-4 py-2 font-medium">收益率</th>
                          <th className="px-4 py-2 font-medium">最大回撤</th>
                          <th className="px-4 py-2 font-medium">胜率</th>
                          <th className="px-4 py-2 font-medium">盈亏比</th>
                          <th className="px-4 py-2 font-medium">交易数</th>
                          <th className="px-4 py-2 font-medium">执行时间</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-crypto-border">
                        {matrixPeriodResults.map((item) => (
                          <tr key={item.timeframe || item.status} className={activeMatrixTimeframe === item.timeframe ? 'bg-yellow-500/5' : undefined}>
                            <td className="px-4 py-2 font-semibold text-white">{backtestTimeframeLabel(item.timeframe)}</td>
                            <td className="px-4 py-2 text-gray-300">{item.status === 'completed' ? '完成' : item.status || '-'}</td>
                            <td className={clsx('px-4 py-2 font-semibold', (item.totalReturn ?? 0) >= 0 ? 'text-up' : 'text-down')}>{fmtPct(item.totalReturn)}</td>
                            <td className="px-4 py-2 text-down">{fmt(item.maxDrawdown)}%</td>
                            <td className="px-4 py-2 text-gray-200">{fmt(item.winRate)}%</td>
                            <td className="px-4 py-2 text-gray-200">{fmt(item.profitFactor)}</td>
                            <td className="px-4 py-2 text-gray-200">{item.totalTrades ?? 0}</td>
                            <td className="px-4 py-2 text-gray-400">{item.elapsedSeconds != null ? `${item.elapsedSeconds.toFixed(1)}s` : '-'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {/* ====== 报告主体 ====== */}
              <div className="backtestUnifiedReport space-y-5">
                <section className="backtestVerdictStrip grid grid-cols-2 gap-3 xl:grid-cols-4">
                  {backtestVerdictMetrics.map((metric) => renderVerdictMetric(metric))}
                </section>

                {result.equityCurve && result.equityCurve.length >= 2 && (
                  <section className="rounded-xl border border-crypto-border bg-crypto-card/80 p-4">
                    <h4 className="mb-3 text-sm font-semibold text-white">权益曲线</h4>
                    <Suspense
                      fallback={
                        <div style={{ height: 420 }} className="flex items-center justify-center text-sm text-gray-500">
                          权益曲线加载中...
                        </div>
                      }
                    >
                      <BacktestEquityCurve
                        equityCurve={result.equityCurve}
                        benchmarkKlines={benchmarkKlines}
                        benchmarkSymbol={benchmarkSymbol}
                        initialCapital={result.initialCapital ?? initialCapital}
                        height={420}
                      />
                    </Suspense>
                  </section>
                )}

                {renderBacktestKlineReview({ height: 560 })}

                {/* ====== 绩效诊断 ====== */}
                <section className="backtestUnifiedMetricModule backtestDiagnosticMetricSection rounded-xl border border-crypto-border bg-crypto-card/80">
                  <div className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left">
                    <span className="flex min-w-0 items-center gap-2">
                      <Activity className="h-4 w-4 shrink-0 text-blue-400" />
                      <span className="truncate text-sm font-semibold text-white">绩效明细</span>
                    </span>
                    <span className="shrink-0 text-[11px] text-gray-500">判决带之外的拆解指标</span>
                  </div>
                  <div className="backtestMetricRowStack grid gap-5 border-t border-crypto-border px-4 pb-4 pt-4 lg:grid-cols-3">
                    {backtestMetricRows.map((row) => (
                      <div
                        key={row.title}
                        className={clsx(
                          'backtestMetricCategoryRow min-w-0 border-l pl-4',
                          row.toneClassName,
                        )}
                      >
                        <div className="mb-2 flex items-baseline justify-between gap-2">
                          <div className={clsx('flex shrink-0 items-center gap-2 text-sm font-semibold', row.titleClassName)}>
                            {row.icon}
                            {row.title}
                          </div>
                          <div className="min-w-0 truncate text-[11px] text-gray-500">{row.description}</div>
                        </div>
                        <div className="backtestMetricCardGrid">
                          {row.metrics.map((metric) => renderMetricRow(metric))}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="backtestReviewAuditModule rounded-xl border border-crypto-border bg-crypto-card/80">
                  <div className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left">
                    <span className="flex min-w-0 items-center gap-2">
                      <ListChecks className="h-4 w-4 shrink-0 text-cyan-300" />
                      <span className="truncate text-sm font-semibold text-white">研究诊断与审计</span>
                    </span>
                    <span className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                      <span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[11px] font-semibold text-blue-200">
                        研究结论
                      </span>
                      <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold text-amber-200">
                        风险闸门
                      </span>
                      <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-200">
                        成本审计
                      </span>
                    </span>
                  </div>
                  <div className="border-t border-crypto-border px-4 pb-4 pt-4">
                    <div className="backtestReviewAuditGrid grid gap-5 lg:grid-cols-3">
                      <div className="backtestReviewAuditPanel min-w-0 border-l border-blue-500/40 pl-4">
                        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-blue-300">
                          <Activity className="h-4 w-4 shrink-0" />
                          研究结论
                        </div>
                        <div className="space-y-3">
                          <StatRow label="结论状态" value={resultDataInvalidated ? '不可采信' : (result.totalReturn ?? 0) >= 0 ? '收益为正' : '收益为负'} color={resultDataInvalidated ? 'text-red-300' : (result.totalReturn ?? 0) >= 0 ? 'text-up' : 'text-down'} />
                          <StatRow label={`相对 ${benchmarkSymbol}`} value={benchmarkGateLabel} color={resultDataInvalidated ? 'text-red-300' : (benchmarkStats.alpha ?? 0) >= 0 ? 'text-up' : 'text-down'} />
                          <StatRow label="样本长度" value={performanceMetrics?.durationDays != null ? `${fmt(performanceMetrics.durationDays, 1)} 天` : '-'} />
                          <StatRow label="数据可信度" value={detailDataQualityMeta.label} color={resultDataInvalidated ? 'text-red-300' : 'text-blue-300'} />
                        </div>
                      </div>
                      <div className="backtestReviewAuditPanel min-w-0 border-l border-amber-500/40 pl-4">
                        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-amber-300">
                          <AlertTriangle className="h-4 w-4 shrink-0" />
                          风险闸门
                        </div>
                        <div className="space-y-3">
                          <StatRow label="回撤闸门" value={drawdownGateLabel} color={result?.maxDrawdown != null && result.maxDrawdown >= 20 ? 'text-down' : 'text-gray-200'} />
                          <StatRow label="收益回撤比" value={calmarGateLabel} />
                          <StatRow label="下行风险" value={sortinoGateLabel} />
                          <StatRow label="样本健康" value={totalTradesCount >= 20 ? '成交样本充足' : totalTradesCount > 0 ? '成交样本偏少' : '尚无成交'} />
                        </div>
                      </div>
                      <div className="backtestReviewAuditPanel min-w-0 border-l border-emerald-500/40 pl-4">
                        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-emerald-300">
                          <DollarSign className="h-4 w-4 shrink-0" />
                          成本审计
                        </div>
                        <div className="space-y-3">
                          <StatRow label="手续费占本金" value={performanceMetrics?.feeDragPct != null ? `${fmt(performanceMetrics.feeDragPct)}%` : '-'} />
                          <StatRow label="单笔平均费用" value={avgFeePerTrade != null ? `¥${fmt(avgFeePerTrade)}` : '-'} />
                          <StatRow label="交易频率" value={performanceMetrics?.tradeFrequencyPerDay != null ? `${fmt(performanceMetrics.tradeFrequencyPerDay)} 笔/日` : '-'} />
                          <StatRow label="平均持仓" value={result.avgHoldingBars != null ? `${fmt(result.avgHoldingBars)} 个交易日` : '-'} />
                        </div>
                      </div>
                    </div>
                  </div>
                </section>

              {monthlyReturnEntries.length > 0 && (
                <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
                  <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
                    <Calendar className="h-4 w-4 text-blue-400" />
                    月度收益分布
                  </h3>
                  <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6 2xl:grid-cols-8">
                    {monthlyReturnEntries.map(([month, ret]) => (
                      <div
                        key={month}
                        className={clsx(
                          'rounded-lg border border-crypto-border/70 px-2 py-2 text-center text-xs font-medium tabular-nums',
                          ret >= 0 ? 'bg-up text-up' : 'bg-down text-down',
                        )}
                      >
                        <div className="text-[10px] text-gray-500">{month.slice(5)}</div>
                        <div>{ret >= 0 ? '+' : ''}{ret.toFixed(1)}%</div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {result.trades && result.trades.length >= 3 && (
                <section className="rounded-xl border border-crypto-border bg-crypto-card/80 p-4">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
                      <BarChart3 className="h-4 w-4 text-blue-400" />
                      交易分析
                    </h3>
                    <span className="text-[11px] text-gray-500">累计盈亏 · 单笔盈亏分布 · 交易原因结构</span>
                  </div>
                  <Suspense
                    fallback={
                      <div style={{ height: 460 }} className="flex items-center justify-center text-sm text-gray-500">
                        交易分析加载中...
                      </div>
                    }
                  >
                    <BacktestTradeAnalytics trades={result.trades} height={460} />
                  </Suspense>
                </section>
              )}

              {/* ====== 交易流水 ====== */}
              <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
                <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-white">
                  <List className="h-4 w-4 text-blue-400" />
                  交易流水
                  <span className="ml-auto text-xs font-normal text-gray-500">{result.trades?.length || 0} 笔</span>
                </h3>
                <p className="mb-3 text-xs text-gray-500">
                  默认按时间倒序显示最近 100 笔；价格为历史撮合价（含滑点），不是当前行情价。
                </p>
                {result.trades && result.trades.length > 0 ? (
                  <div className="backtestTradeLedgerFrame flex h-[520px] flex-col overflow-hidden rounded-xl border border-crypto-border bg-crypto-bg/45 md:h-[560px]">
                    <div className="min-h-0 flex-1 overflow-auto">
                      <table className="w-full min-w-[1080px] text-sm">
                        <thead className="sticky top-0 z-10 bg-crypto-bg/95 backdrop-blur">
                          <tr className="border-b border-crypto-border text-[11px] text-gray-500">
                            <th className="px-4 py-3 text-left font-medium">时间</th>
                            <th className="px-4 py-3 text-left font-medium">证券</th>
                            <th className="px-4 py-3 text-left font-medium">方向</th>
                            <th className="px-4 py-3 text-right font-medium">历史成交价</th>
                            <th className="px-4 py-3 text-right font-medium">数量</th>
                            <th className="px-4 py-3 text-right font-medium">杠杆</th>
                            <th className="px-4 py-3 text-right font-medium">保证金</th>
                            <th className="px-4 py-3 text-right font-medium">成交名义</th>
                            <th className="px-4 py-3 text-right font-medium">盈亏</th>
                            <th className="px-4 py-3 text-right font-medium">手续费</th>
                            <th className="px-4 py-3 text-left font-medium">原因</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-crypto-border/50">
                          {displayedTrades.map((trade, i) => {
                            const sideDisplay = getTradeSideDisplay(trade.side);
                            const margin = backtestTradeMargin(trade);
                            const notional = backtestTradeNotional(trade);
                            return (
                              <tr key={i} className="transition-colors hover:bg-white/[0.02]">
                                <td className="px-4 py-3 text-xs text-gray-400">{new Date(trade.timestamp).toLocaleString('zh-CN')}</td>
                                <td className="px-4 py-3 text-xs text-gray-300">{trade.symbol || '-'}</td>
                                <td className={clsx('px-4 py-3 text-xs font-semibold', sideDisplay.className)}>
                                  {sideDisplay.label}
                                </td>
                                <td className="px-4 py-3 text-right text-xs text-white" title="历史撮合价，已计入滑点假设">{trade.price.toFixed(2)}</td>
                                <td className="px-4 py-3 text-right text-xs text-white">{trade.quantity.toFixed(4)}</td>
                                <td className="px-4 py-3 text-right text-xs text-gray-300">{formatBacktestTradeLeverage(trade.leverage)}</td>
                                <td className="px-4 py-3 text-right text-xs text-gray-300">{formatBacktestTradeMoney(margin)}</td>
                                <td className="px-4 py-3 text-right text-xs text-gray-300">{formatBacktestTradeMoney(notional)}</td>
                                <td className={clsx('px-4 py-3 text-right text-xs font-medium', trade.pnl >= 0 ? 'text-up' : 'text-down')}>
                                  {trade.pnl ? `${trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)}` : '-'}
                                </td>
                                <td className="px-4 py-3 text-right text-xs text-gray-500">{trade.fee ? trade.fee.toFixed(2) : '-'}</td>
                                <td className="px-4 py-3 text-xs text-gray-500">{trade.reason || '-'}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    {result.trades.length > displayedTrades.length && (
                      <p className="shrink-0 border-t border-crypto-border px-4 py-3 text-center text-xs text-gray-500">
                        共 {result.trades.length} 笔交易（按时间倒序显示最近100笔）
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed border-crypto-border bg-crypto-bg/35 py-12 text-center text-sm text-gray-500">暂无交易记录</div>
                )}
              </section>
              </div>
            </>
          )}
        </div>
      )}

      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-2xl border border-crypto-border bg-crypto-card shadow-2xl shadow-black/40">
            <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-crypto-border bg-crypto-card/95 px-6 py-5 backdrop-blur">
              <div>
                <h2 className="flex items-center gap-2 text-lg font-bold text-white">
                  <FlaskConical className="h-5 w-5 text-blue-400" />
                  创建回测实例
                </h2>
                <p className="mt-1 text-xs text-gray-500">
                  选择策略、设置区间和成本，提交后生成独立回测实例并异步运行。
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsCreateModalOpen(false)}
                className="rounded-lg border border-crypto-border p-2 text-gray-500 hover:text-gray-300"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="px-6 py-5">
              <div className="mb-6 rounded-xl border border-crypto-border bg-crypto-bg/35 px-4 py-5">
                <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                  {BACKTEST_WIZARD_STEPS.slice(0, 3).map((step, index) => (
                    <BacktestWizardStep
                      key={step.step}
                      step={step.step}
                      title={step.title}
                      desc={step.step === 3 ? '确认并启动回测' : step.desc}
                      state={step.step < createStep ? 'done' : step.step === createStep ? 'active' : 'pending'}
                      isLast={index === 2}
                    />
                  ))}
                </div>
              </div>

              {createStep === 1 && (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {['T+1', '100股', '只做多', '快速预检不可晋级'].map((item) => (
                      <div key={item} className="rounded-lg border border-blue-500/25 bg-blue-500/10 px-3 py-2 text-center text-xs font-semibold text-blue-200">
                        {item}
                      </div>
                    ))}
                  </div>
                  <Field label="选择策略">
                    <div className="backtestStrategySearchCombobox space-y-2">
                      <div className="relative">
                        <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                        <input
                          type="search"
                          role="combobox"
                          aria-expanded="true"
                          aria-controls="backtest-strategy-search-results"
                          aria-autocomplete="list"
                          value={strategySearchQuery}
                          onChange={(event) => setStrategySearchQuery(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter' && filteredBacktestStrategyOptions[0]) {
                              event.preventDefault();
                              const firstStrategy = filteredBacktestStrategyOptions[0];
                              updateCreateDraft({ selectedStrategy: Number(firstStrategy.id) || null });
                              setStrategySearchQuery(String(firstStrategy.name || ''));
                            }
                            if (event.key === 'Escape') {
                              setStrategySearchQuery('');
                            }
                          }}
                          placeholder="搜索策略名 / 标的 / 周期 / 类型"
                          className="h-12 w-full rounded-xl border border-white/10 bg-[#0b1220]/95 pl-11 pr-12 text-sm font-semibold text-gray-100 outline-none shadow-[inset_0_1px_0_rgba(255,255,255,0.04),0_10px_28px_rgba(2,6,23,0.28)] transition duration-150 placeholder:text-gray-600 hover:border-blue-400/40 hover:bg-[#101a2b] focus:border-blue-400/70 focus:ring-2 focus:ring-blue-500/30"
                        />
                        {strategySearchQuery && (
                          <button
                            type="button"
                            aria-label="清空策略搜索"
                            onClick={() => setStrategySearchQuery('')}
                            className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg p-1 text-gray-500 transition hover:bg-white/5 hover:text-gray-200"
                          >
                            <X className="h-4 w-4" />
                          </button>
                        )}
                      </div>

                      <div
                        id="backtest-strategy-search-results"
                        role="listbox"
                        className="max-h-[320px] overflow-y-auto rounded-xl border border-crypto-border bg-crypto-bg/60 p-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
                      >
                        {filteredBacktestStrategyOptions.length === 0 ? (
                          <div className="rounded-lg border border-dashed border-white/10 px-4 py-6 text-center text-sm text-gray-500">
                            {backtestableStrategies.length === 0 ? '暂无可回测策略' : '没有匹配的策略'}
                          </div>
                        ) : (
                          <div className="space-y-2">
                            {filteredBacktestStrategyOptions.map((strategy) => {
                              const optionAssetClass = strategyAssetClass(strategy);
                              const optionSelected = Number(strategy.id) === Number(createDraft.selectedStrategy);
                              const optionSymbols = strategyTradeSymbols(strategy).length
                                ? strategyTradeSymbols(strategy)
                                : strategySymbols(strategy);
                              return (
                                <button
                                  key={strategy.id}
                                  type="button"
                                  role="option"
                                  aria-selected={optionSelected}
                                  onClick={() => {
                                    updateCreateDraft({ selectedStrategy: Number(strategy.id) || null });
                                    setStrategySearchQuery(String(strategy.name || ''));
                                  }}
                                  className={clsx(
                                    'w-full rounded-lg border px-3 py-3 text-left transition duration-150',
                                    optionSelected
                                      ? SELECTED_SEGMENT_BORDER_CLASS
                                      : 'border-white/5 bg-white/[0.025] hover:border-blue-400/35 hover:bg-white/[0.055]',
                                  )}
                                >
                                  <div className="flex items-start justify-between gap-3">
                                    <div className="min-w-0">
                                      <div className="mb-1 flex min-w-0 items-center gap-2">
                                        <span className={clsx('shrink-0 rounded border px-2 py-0.5 text-[11px] font-bold', strategyAssetBadgeClass(optionAssetClass))}>
                                          {optionAssetClass === 'etf' ? 'ETF' : '股票'}
                                        </span>
                                        <span className={clsx('truncate text-sm font-semibold', strategyNameColorClass(optionAssetClass))}>
                                          {strategy.name}
                                        </span>
                                      </div>
                                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
                                        <span>周期 <span className="text-gray-300">{strategyTimeframe(strategy) || '未定义'}</span></span>
                                        <span>范围 <span className="text-gray-300">{symbolSummary(optionSymbols)}</span></span>
                                      </div>
                                    </div>
                                    {optionSelected && (
                                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
                                    )}
                                  </div>
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    </div>
                  </Field>
                  {draftStrategyInfo && (
                    <div className="rounded-xl border border-crypto-border bg-crypto-bg/50 p-4">
                      <div className="mb-2 flex items-center gap-2">
                        <span className={clsx('rounded border px-2 py-0.5 text-[11px] font-bold', strategyAssetBadgeClass(draftAssetClass))}>
                          {draftAssetClass === 'etf' ? 'ETF' : '股票'}
                        </span>
                        <span className={clsx('truncate text-sm font-semibold', strategyNameColorClass(draftAssetClass))}>
                          {draftStrategyInfo.name}
                        </span>
                      </div>
                      <div className="grid grid-cols-1 gap-3 text-xs text-gray-500 md:grid-cols-2">
                        <div>策略周期：<span className="text-gray-300">{strategyTimeframe(draftStrategyInfo) || '未定义'}</span></div>
                        <div>交易范围：<span className="text-gray-300">{symbolSummary(strategyTradeSymbols(draftStrategyInfo).length ? strategyTradeSymbols(draftStrategyInfo) : strategySymbols(draftStrategyInfo))}</span></div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {createStep === 2 && (
                <div className="space-y-4">
                  <Field label="运行模式">
                    <div className="grid grid-cols-2 gap-2">
                      {[
                        { value: 'quick' as const, label: '快速预检', hint: '诊断用途，不可晋级 Paper' },
                        { value: 'full' as const, label: '完整协议', hint: '绑定研究协议并执行全部晋级门控' },
                      ].map((mode) => (
                        <button
                          key={mode.value}
                          type="button"
                          onClick={() => updateCreateDraft({ runMode: mode.value })}
                          className={clsx(
                            'rounded-lg border px-3 py-3 text-left transition-colors',
                            createDraft.runMode === mode.value
                              ? SELECTED_SEGMENT_BORDER_CLASS
                              : 'border-crypto-border bg-crypto-bg text-gray-400 hover:border-blue-500/40',
                          )}
                        >
                          <div className="text-xs font-semibold">{mode.label}</div>
                          <div className="mt-1 text-[10px] text-gray-500">{mode.hint}</div>
                        </button>
                      ))}
                    </div>
                  </Field>
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <Field label="开始日期">
                      <input
                        type="date"
                        value={createDraft.startDate}
                        onChange={(event) => updateCreateDraft({ startDate: event.target.value })}
                        max={todayDate}
                        className="w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 py-3 text-sm text-white"
                      />
                    </Field>
                    <Field label="结束日期">
                      <input
                        type="date"
                        value={createDraft.endDate}
                        onChange={(event) => updateCreateDraft({ endDate: event.target.value })}
                        min={createDraft.startDate}
                        max={todayDate}
                        className="w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 py-3 text-sm text-white"
                      />
                    </Field>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {[
                      [1, '最近1月'],
                      [6, '最近6月'],
                      [12, '最近1年'],
                      [24, '最近2年'],
                    ].map(([months, label]) => (
                      <button
                        key={String(months)}
                        type="button"
                        onClick={() => applyQuickRange(Number(months))}
                        className="rounded-lg border border-crypto-border px-3 py-1.5 text-xs font-semibold text-gray-400 hover:border-purple-500/50 hover:text-purple-300"
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <Field label="初始资金 (CNY)">
                      <input
                        type="number"
                        value={createDraft.initialCapital}
                        onChange={(event) => updateCreateDraft({ initialCapital: Math.max(0, Number(event.target.value)) })}
                        className="w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 py-3 text-sm text-white"
                      />
                    </Field>
                    <Field label="周期模式">
                      <div className="grid gap-2 sm:grid-cols-3">
                        {BACKTEST_TIMEFRAME_MODES.map((mode) => (
                          <button
                            key={mode.value}
                            type="button"
                            onClick={() => updateCreateDraft({ timeframeMode: mode.value })}
                            className={clsx(
                              'rounded-lg border px-3 py-2 text-left transition-colors',
                              createDraft.timeframeMode === mode.value
                                ? SELECTED_SEGMENT_BORDER_CLASS
                                : 'border-crypto-border bg-crypto-bg text-gray-400 hover:border-purple-500/40 hover:text-purple-200',
                            )}
                          >
                            <div className="text-xs font-semibold">{mode.label}</div>
                            <div className="mt-1 text-[10px] text-gray-500">{mode.hint}</div>
                          </button>
                        ))}
                      </div>
                    </Field>
                    <Field label="K线周期">
                      <div className="rounded-lg border border-crypto-border bg-crypto-bg p-2">
                        {createDraft.timeframeMode === 'strategy' ? (
                          <div className="flex min-h-[38px] items-center justify-between px-2 text-sm">
                            <span className={draftStrategyInfo ? 'text-white' : 'text-gray-500'}>
                              {draftStrategyInfo ? backtestTimeframeLabel(strategyTimeframe(draftStrategyInfo)) : '请选择策略'}
                            </span>
                            {draftStrategyInfo && <span className="rounded bg-purple-500/10 px-2 py-0.5 text-[10px] text-purple-300">策略定义</span>}
                          </div>
                        ) : (
                          <div className="flex flex-wrap gap-2">
                            {BACKTEST_TIMEFRAME_OPTIONS.map((option) => {
                              const active = createDraft.timeframeMode === 'matrix'
                                ? createDraft.timeframes.includes(option.value)
                                : createDraft.timeframe === option.value;
                              return (
                                <button
                                  key={option.value}
                                  type="button"
                                  onClick={() => {
                                    if (createDraft.timeframeMode === 'matrix') {
                                      const exists = createDraft.timeframes.includes(option.value);
                                      const next = exists
                                        ? createDraft.timeframes.filter((value) => value !== option.value)
                                        : [...createDraft.timeframes, option.value];
                                      updateCreateDraft({ timeframes: next.length > 0 ? next : [option.value] });
                                    } else {
                                      updateCreateDraft({ timeframe: option.value });
                                    }
                                  }}
                                  className={clsx(
                                    'min-w-[58px] rounded-md px-3 py-2 text-xs font-semibold transition-colors',
                                    active
                                      ? 'bg-purple-500/25 text-purple-100 ring-1 ring-purple-400/40'
                                      : 'bg-crypto-card text-gray-500 hover:text-gray-200',
                                  )}
                                >
                                  {option.label}
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    </Field>
                    <Field label="Maker 手续费 (bps)">
                      <input
                        type="number"
                        value={draftEffectiveMakerFeeBps}
                        onChange={(event) => updateCreateDraft({ makerFeeBps: Math.max(0, Number(event.target.value)) })}
                        step="0.1"
                        className="w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 py-3 text-sm text-white"
                      />
                    </Field>
                    <Field label="Taker 手续费 (bps)">
                      <input
                        type="number"
                        value={draftEffectiveTakerFeeBps}
                        onChange={(event) => updateCreateDraft({ takerFeeBps: Math.max(0, Number(event.target.value)) })}
                        step="0.1"
                        className="w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 py-3 text-sm text-white"
                      />
                    </Field>
                    <Field label="滑点 (bps)">
                      <input
                        type="number"
                        value={draftEffectiveSlippageBps}
                        onChange={(event) => updateCreateDraft({ slippageBps: Math.max(0, Number(event.target.value)) })}
                        step="0.1"
                        className="w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 py-3 text-sm text-white"
                      />
                    </Field>
                  </div>
                </div>
              )}

              {createStep === 3 && (
                <div className="rounded-xl border border-crypto-border bg-crypto-bg/50 p-4">
                  <div className="mb-3 text-sm font-semibold text-white">确认回测任务</div>
                  <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
                    <StatRow label="策略" value={draftStrategyInfo?.name || '未选择'} color={strategyNameColorClass(draftAssetClass)} />
                    <StatRow label="运行模式" value={createDraft.runMode === 'full' ? '完整协议' : '快速预检（不可晋级）'} />
                    <StatRow label="资产类型" value={draftAssetClass === 'etf' ? 'ETF' : '股票'} />
                    <StatRow label="区间" value={`${createDraft.startDate} 至 ${createDraft.endDate}`} />
                    <StatRow label="初始资金" value={`¥${fmt(createDraft.initialCapital)}`} />
                    <StatRow label="Maker/Taker" value={`${fmt(draftEffectiveMakerFeeBps)}/${fmt(draftEffectiveTakerFeeBps)} bps`} />
                    <StatRow label="滑点" value={`${fmt(draftEffectiveSlippageBps)} bps`} />
                  </div>
                </div>
              )}
            </div>

            <div className="sticky bottom-0 flex items-center justify-between gap-3 border-t border-crypto-border bg-crypto-card/95 px-6 py-4 backdrop-blur">
              <button
                type="button"
                onClick={() => setIsCreateModalOpen(false)}
                className="rounded-xl border border-crypto-border px-4 py-2 text-sm font-semibold text-gray-400 hover:text-gray-200"
              >
                取消
              </button>
              <div className="flex gap-2">
                {createStep > 1 && (
                  <button
                    type="button"
                    onClick={() => setCreateStep((step) => Math.max(1, step - 1) as 1 | 2 | 3)}
                    className="rounded-xl border border-crypto-border px-4 py-2 text-sm font-semibold text-gray-300 hover:text-white"
                  >
                    上一步
                  </button>
                )}
                {createStep < 3 ? (
                  <button
                    type="button"
                    onClick={() => {
                      if (createStep === 1 && !createDraft.selectedStrategy) {
                        showThemeAlert('提示', '请选择策略', 'warning');
                        return;
                      }
                      if (createStep === 2) {
                        const dateError = backtestDateValidationMessage(createDraft);
                        if (dateError) {
                          showThemeAlert('回测日期无效', dateError, 'warning');
                          return;
                        }
                      }
                      setCreateStep((step) => Math.min(3, step + 1) as 1 | 2 | 3);
                    }}
                    className="rounded-xl bg-blue-600 px-5 py-2 text-sm font-semibold text-white hover:bg-blue-500"
                  >
                    下一步
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => void runBacktest(createDraft)}
                    disabled={!createDraft.selectedStrategy || createDraft.initialCapital <= 0}
                    className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-2 text-sm font-semibold text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-700 disabled:text-gray-500"
                  >
                    <Play className="h-4 w-4" />
                    开始回测
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <Suspense fallback={null}>
        <BacktestCompareDialog
          open={compareOpen}
          entries={compareEntries}
          strategies={strategies}
          onClose={() => setCompareOpen(false)}
        />
      </Suspense>
      <ThemeAlertDialog
        open={themeAlert.open}
        title={themeAlert.title}
        content={themeAlert.content}
        tone={themeAlert.tone}
        onClose={() => setThemeAlert((a) => ({ ...a, open: false }))}
      />
      <ThemeDialog
        open={batchBacktestConfirmOpen}
        variant="confirm"
        tone="warning"
        title="创建批量回测实例"
        confirmText={isBatchBacktestSubmitting ? '创建中...' : '确认批量回测'}
        cancelText="取消"
        onCancel={() => {
          if (!isBatchBacktestSubmitting) setBatchBacktestConfirmOpen(false);
        }}
        onConfirm={createBatchBacktestInstances}
      >
        <div className="space-y-4 text-sm text-slate-200">
          <p>
            将为当前所有运行中的模拟策略创建回测实例；实盘、非模拟或无法解析的运行中策略会自动跳过。
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="rounded-xl border border-white/10 bg-white/[0.035] p-3">
              <div className="text-xs font-semibold text-slate-500">默认区间</div>
              <div className="mt-1 text-base font-semibold text-white">
                {batchBacktestDefaults.start} 至 {batchBacktestDefaults.end}
              </div>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.035] p-3">
              <div className="text-xs font-semibold text-slate-500">默认资金</div>
              <div className="mt-1 text-base font-semibold text-white">100 万元</div>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.035] p-3">
              <div className="text-xs font-semibold text-slate-500">策略周期</div>
              <div className="mt-1 text-base font-semibold text-white">策略定义</div>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.035] p-3">
              <div className="text-xs font-semibold text-slate-500">执行方式</div>
              <div className="mt-1 text-base font-semibold text-white">异步实例</div>
            </div>
          </div>
          <p className="text-xs leading-5 text-slate-400">
            批量默认使用 100 万元，其余佣金、印花税、过户费、滑点、日线数据、任务轮询和结果落库逻辑与普通回测保持一致。
          </p>
        </div>
      </ThemeDialog>
      <ThemeDialog
        open={Boolean(backtestStatusTarget)}
        title="回测状态"
        tone={backtestStatusTarget?.status === 'failed' ? 'danger' : 'default'}
        content={backtestStatusTarget ? backtestStatusDialogContent(backtestStatusTarget) : ''}
        onClose={() => setBacktestStatusTarget(null)}
      />
      <ThemeDialog
        open={Boolean(backtestLogTarget)}
        title="回测日志"
        tone={backtestLogTarget?.status === 'failed' ? 'danger' : 'default'}
        onClose={() => setBacktestLogTarget(null)}
      >
        <pre className="max-h-[420px] overflow-y-auto whitespace-pre-wrap rounded-xl border border-crypto-border bg-black/30 p-3 text-xs leading-6 text-gray-200">
          {backtestLogTarget ? backtestInstanceLogs(backtestLogTarget).join('\n') : ''}
        </pre>
      </ThemeDialog>
      <ThemeDialog
        open={Boolean(localBacktestDeleteTarget)}
        variant="confirm"
        tone="danger"
        title="删除本地回测实例"
        confirmText="确认删除"
        cancelText="取消"
        content={localBacktestDeleteTarget
          ? `删除本地回测实例 ${localBacktestDeleteTarget.name}？已落库的回测记录不会删除。`
          : ''}
        onCancel={() => setLocalBacktestDeleteTarget(null)}
        onConfirm={confirmDeleteLocalBacktestInstance}
      />
      <ThemeDialog
        open={Boolean(cancelBacktestTarget)}
        variant="confirm"
        tone="warning"
        title="停止当前回测"
        confirmText="确认停止"
        cancelText="取消"
        content={cancelBacktestTarget
          ? `停止 ${cancelBacktestTarget.name} 的当前回测？已完成进度会保留，但不会写入回测记录。`
          : ''}
        onCancel={() => setCancelBacktestTarget(null)}
        onConfirm={confirmCancelBacktestInstance}
      />
      <ThemeDialog
        open={Boolean(historyDeleteTarget)}
        variant="confirm"
        tone="danger"
        title={historyDeleteTarget?.mode === 'batch'
          ? `删除 ${historyDeleteTarget.items.length} 条回测记录`
          : '删除回测记录'}
        confirmText={isDeletingHistoryBatch ? '删除中...' : '确认删除'}
        cancelText="取消"
        onCancel={() => {
          if (!isDeletingHistoryBatch) setHistoryDeleteTarget(null);
        }}
        onConfirm={confirmDeleteBacktestHistory}
      >
        {historyDeleteTarget && (
          <div className="space-y-3 text-sm text-gray-300">
            <p>删除后无法恢复，已落库的回测摘要和成交记录会被移除。</p>
            <div className="max-h-56 overflow-y-auto rounded-xl border border-red-500/20 bg-red-500/5 p-3">
              {historyDeleteTarget.items.slice(0, 6).map((item) => (
                <div key={item.id} className="border-b border-red-500/10 py-2 last:border-0">
                  <div className={clsx('font-semibold', strategyNameColorClass(inferStrategyAssetClassFromName(item.strategyName) || strategyAssetClassById(strategies, item.strategyId)))}>
                    {strategyNameById(strategies, item.strategyId, item.strategyName)}
                  </div>
                  <div className="mt-1 text-xs text-gray-500">
                    {item.startDate} 至 {item.endDate} · 回测时间 {formatDateTime(item.createdAt)}
                  </div>
                </div>
              ))}
              {historyDeleteTarget.items.length > 6 && (
                <div className="pt-2 text-xs text-gray-500">
                  另有 {historyDeleteTarget.items.length - 6} 条记录将一起删除。
                </div>
              )}
            </div>
          </div>
        )}
      </ThemeDialog>
    </div>
  );
}

// ============================================
// 表单字段
// ============================================
