from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def backtest_source() -> str:
    return (
        read_text("frontend/src/pages/Backtest.tsx")
        + "\n"
        + read_text("frontend/src/pages/backtest/backtestSupport.tsx")
    )


def nav_entry_prefix(path: str, icon: str, label: str) -> str:
    return f"{{ path: '{path}', icon: {icon}, label: '{label}',"


def test_market_route_lazy_loads_heavy_kline_chart() -> None:
    source = read_text("frontend/src/pages/Market.tsx")

    assert "import KlineChart from '../components/KlineChart'" not in source
    assert "lazy(() => import('../components/KlineChart'))" in source
    assert "<Suspense" in source


def test_market_kairos_prediction_controls_are_removed() -> None:
    source = read_text("frontend/src/pages/Market.tsx")
    client = read_text("frontend/src/api/client.ts")

    assert "showPrediction" not in source
    assert "getPredictionsCompare" not in source
    assert "AI 预测" not in source
    assert "getPredictionsCompare" not in client
    assert "getKlinesWithPrediction" not in client


def test_market_current_price_uses_okx_app_change_percent_priority() -> None:
    source = read_text("frontend/src/pages/Market.tsx")

    assert "const priceChange = liveTicker?.changePercentToday ?? liveTicker?.change_percent_today ?? liveTicker?.changePercent ?? liveTicker?.change_percent ?? 0;" in source


def test_market_current_price_is_rendered_after_chart_selector_controls() -> None:
    source = read_text("frontend/src/pages/Market.tsx")
    toolbar = source[source.index("{/* 顶部工具栏 */"):source.index("{loading &&")]
    chart_start = source.index("{/* K线图区域")
    chart_header = source[chart_start:source.index('<div className="flex-1 min-h-0', chart_start)]

    controls_pos = chart_header.index("market-detail-controls")
    symbol_pos = chart_header.index("<SymbolSearch", controls_pos)
    price_pos = chart_header.index("${currentPrice.toLocaleString")
    change_pos = chart_header.index("{priceChange >= 0 ? '+' : ''}{priceChange.toFixed(2)}%")
    timeframe_controls_pos = chart_header.index("market-detail-timeframe-controls", change_pos)
    kline_count_pos = chart_header.index("共 {klines.length} 根K线")

    assert "{selectedSymbol} - {timeframe}" not in chart_header
    assert "<h2" not in chart_header
    assert controls_pos < symbol_pos < price_pos < change_pos < timeframe_controls_pos < kline_count_pos
    assert "items-baseline gap-x-3" in chart_header
    assert "${currentPrice.toLocaleString" not in toolbar
    assert "右侧工具区 — 刷新 · 连接状态" in toolbar


def test_market_symbol_controls_replace_detail_title_and_timeframes_stay_right() -> None:
    source = read_text("frontend/src/pages/Market.tsx")
    toolbar = source[source.index("{/* 顶部工具栏 */"):source.index("{loading &&")]
    chart_start = source.index("{/* K线图区域")
    chart_header = source[chart_start:source.index('<div className="flex-1 min-h-0', chart_start)]
    symbol_search = read_text("frontend/src/components/SymbolSearch.tsx")

    assert "<SymbolSearch" not in toolbar
    assert "TIMEFRAMES.map" not in toolbar
    assert "market-detail-controls" in chart_header
    assert "const [marketType, setMarketType] = useState<MarketType>('swap')" in source
    assert "marketApi.getSymbols(selectedExchange, 'USDT', marketType)" in source
    assert "market-type-toggle" in chart_header
    assert "marketType === 'swap'" in chart_header
    assert "合约" in chart_header
    assert "现货" in chart_header

    controls_pos = chart_header.index("market-detail-controls")
    market_type_pos = chart_header.index("market-type-toggle", controls_pos)
    symbol_pos = chart_header.index("<SymbolSearch", market_type_pos)
    price_pos = chart_header.index("${currentPrice.toLocaleString", symbol_pos)
    timeframe_controls_pos = chart_header.index("market-detail-timeframe-controls", price_pos)
    timeframe_pos = chart_header.index("TIMEFRAMES.map", timeframe_controls_pos)
    assert controls_pos < market_type_pos < symbol_pos < price_pos < timeframe_controls_pos < timeframe_pos
    assert "ml-auto" not in chart_header[controls_pos:price_pos]
    assert "ml-auto" in chart_header[timeframe_controls_pos:timeframe_pos]
    assert "marketType={marketType}" in chart_header[symbol_pos:timeframe_pos]
    assert "marketType?: 'spot' | 'swap'" in symbol_search
    assert "formatSymbolForMarketType(coin, marketType)" in symbol_search
    assert "symbolToOkxInstrumentId(symbol).includes(q)" in symbol_search


def test_market_waits_for_default_swap_symbol_before_first_data_fetch() -> None:
    source = read_text("frontend/src/pages/Market.tsx")
    fetch_block = source[source.index("  const fetchData = useCallback"):source.index("  // 初始加载")]

    assert "const selectedSymbolMatchesMarketType" in source
    assert "if (!selectedSymbol || !selectedSymbolMatchesMarketType) return;" in fetch_block
    assert "}, [selectedExchange, selectedSymbol, selectedSymbolMatchesMarketType, timeframe, marketType, updateMarketDataCache]);" in fetch_block


def test_ai_lab_loads_orbit_private_reads_only_for_orbit_tab() -> None:
    source = read_text("frontend/src/pages/AILab.tsx")
    refresh_start = source.index("  const refreshOrbitAutoPost = async () => {")
    effect_start = source.index("  useEffect(() => {", refresh_start)
    effect_end = source.index("  const handleSaveOrbitConfig", effect_start)
    effect_block = source[effect_start:effect_end]

    assert source.index("  const activeTab: AssistantTab") < refresh_start
    assert "if (activeTab !== 'orbit-post') return;" in effect_block
    assert "}, [activeTab]);" in effect_block
    assert "refreshOrbitAutoPost();" in effect_block


def test_market_ignores_stale_kline_fetch_responses_after_symbol_switch() -> None:
    source = read_text("frontend/src/pages/Market.tsx")

    assert "const marketDataRequestSeqRef = useRef(0);" in source
    assert "const marketLoadingRequestSeqRef = useRef(0);" in source
    assert "const requestSeq = ++marketDataRequestSeqRef.current;" in source
    assert "const isStaleMarketDataRequest = () => requestSeq !== marketDataRequestSeqRef.current;" in source
    assert "marketLoadingRequestSeqRef.current = requestSeq;" in source
    assert source.count("if (isStaleMarketDataRequest()) return;") >= 2
    assert "if (!quiet && marketLoadingRequestSeqRef.current === requestSeq) setLoading(false);" in source


def test_market_symbol_switch_renders_cached_or_kline_response_before_slow_overlays() -> None:
    source = read_text("frontend/src/pages/Market.tsx")

    assert "type MarketDataCacheEntry" in source
    assert "const marketDataCacheRef = useRef<Map<string, MarketDataCacheEntry>>(new Map());" in source
    assert "function marketDataCacheKey(" in source
    assert "function applyMarketDataCacheEntry(" in source
    assert "updateMarketDataCache(cacheKey" in source
    assert "const cachedEntry = marketDataCacheRef.current.get(cacheKey);" in source
    assert "fetchData(Boolean(cachedEntry?.klines?.length));" in source
    assert "const klineRequest = marketApi.getKlines" in source
    assert "klineRequest.then((klinesData)" in source
    assert "setKlines(klinesData);" in source
    assert "const indicatorsRequest = marketApi.getTechnicalIndicators" in source
    assert "const orderbookRequest = marketApi.getOrderbook" in source
    assert "Promise.all([\n        marketApi.getKlines" not in source
    assert "Promise.all([\n        marketApi\n          .getPredictionsCompare" not in source
    assert "setInterval(() => fetchData(true), pollMs)" in source


def test_market_toolbar_uses_compact_action_strip_without_dead_ai_analysis() -> None:
    source = read_text("frontend/src/pages/Market.tsx")
    layout = read_text("frontend/src/components/MainLayout.tsx")
    toolbar = source[source.index("{/* 顶部工具栏 */"):source.index("{loading &&")]

    assert "market-action-strip" in toolbar
    assert "market-connection-pill" in toolbar
    assert "AI 预测" not in toolbar
    assert "刷新" in toolbar
    assert "Sparkles" not in source
    assert "Brain" not in source
    assert "MessageSquare" not in source
    assert "aiPredictApi" not in source
    assert "aiAnalysis" not in source
    assert "AI 人话分析" not in source
    assert "行情页 AI 人话分析" not in layout
    assert "AI 分析 Toast" not in source
    assert "w-px h-4" not in toolbar


def test_sidebar_route_icons_match_page_header_icons() -> None:
    layout = read_text("frontend/src/components/MainLayout.tsx")
    page_expectations = [
        ("/", "LayoutDashboard", "首页", "frontend/src/pages/Home.tsx", '<LayoutDashboard className="h-5 w-5 text-blue-400" />'),
        ("/market", "TrendingUp", "行情", "frontend/src/pages/Market.tsx", '<TrendingUp className="w-6 h-6 text-blue-400" />'),
        ("/strategy", "Code2", "策略", "frontend/src/pages/Strategy.tsx", '<Code2 className="w-6 h-6 text-blue-400" />'),
        ("/backtest", "FlaskConical", "回测", "frontend/src/pages/Backtest.tsx", '<FlaskConical className="w-6 h-6 text-purple-400" />'),
        ("/live", "Activity", "模拟", "frontend/src/pages/liveTrading/InstanceDashboard.tsx", '<Activity className="w-6 h-6 text-blue-400" />'),
        ("/live-real", "Rocket", "实盘", "frontend/src/pages/liveTrading/LiveExecutionCenter.tsx", '<Rocket className="h-6 w-6 text-red-300" />'),
        ("/watch", "ScanLine", "盯盘", "frontend/src/pages/WatchMarket.tsx", '<ScanLine className="h-6 w-6 text-blue-400" />'),
        ("/monitor", "Eye", "监控", "frontend/src/pages/Monitor.tsx", '<Eye className="w-6 h-6 text-blue-400" />'),
        ("/data", "Database", "数据", "frontend/src/pages/DataManager.tsx", '<Database className="w-5 h-5 text-white" />'),
        ("/ai-lab", "Sparkles", "AI研发", "frontend/src/pages/AILab.tsx", '<Sparkles className="text-yellow-400" size={28} />'),
    ]

    for path, icon, label, page_path, page_icon in page_expectations:
        assert nav_entry_prefix(path, icon, label) in layout
        assert page_icon in read_text(page_path)

    signal_page = read_text("frontend/src/pages/SignalCenter.tsx")
    assert nav_entry_prefix("/signals", "Send", "信号") not in layout
    assert "<Send size={18} />" in signal_page


def test_kline_charts_use_trackpad_pan_and_pinch_zoom() -> None:
    market_chart = read_text("frontend/src/components/KlineChart.tsx")
    watch_chart = read_text("frontend/src/components/WatchKlineChart.tsx")
    zoom_config = read_text("frontend/src/utils/klineDataZoom.ts")
    wheel_navigation = read_text("frontend/src/utils/klineWheelNavigation.ts")

    assert "export const KLINE_TRACKPAD_DATA_ZOOM" in zoom_config
    assert "zoomOnMouseWheel: false" in zoom_config
    assert "moveOnMouseWheel: false" in zoom_config
    assert "moveOnMouseMove: true" in zoom_config
    assert "preventDefaultMouseMove: true" in zoom_config
    assert "import { KLINE_TRACKPAD_DATA_ZOOM } from '../utils/klineDataZoom';" in market_chart
    assert "import { KLINE_TRACKPAD_DATA_ZOOM } from '../utils/klineDataZoom';" in watch_chart
    assert "import { bindKlineWheelNavigation } from '../utils/klineWheelNavigation';" in market_chart
    assert "import { bindKlineWheelNavigation } from '../utils/klineWheelNavigation';" in watch_chart
    assert market_chart.count("...KLINE_TRACKPAD_DATA_ZOOM") == 1
    assert watch_chart.count("...KLINE_TRACKPAD_DATA_ZOOM") == 1
    assert market_chart.count("bindKlineWheelNavigation(inst)") == 1
    assert watch_chart.count("bindKlineWheelNavigation(inst)") == 1
    assert "addEventListener('wheel', onWheel, { passive: false, capture: true })" in wheel_navigation
    assert "event.stopImmediatePropagation()" in wheel_navigation
    assert "event.ctrlKey || event.metaKey" in wheel_navigation
    assert "Math.abs(event.deltaX)" in wheel_navigation
    assert "type: 'dataZoom'" in wheel_navigation


def test_backtest_route_does_not_statically_import_echarts() -> None:
    source = backtest_source()

    assert "import * as echarts from 'echarts'" not in source
    assert "const WatchKlineChart = lazy(() => import('../components/WatchKlineChart'));" in source
    assert "echartsLib" not in source


def test_backtest_route_uses_full_width_left_aligned_shell() -> None:
    source = backtest_source()

    assert '<div className="h-full w-full min-w-0 p-6">' in source
    assert '<div className="p-6 max-w-[1800px] mx-auto">' not in source


def test_backtest_trade_statistics_use_single_metric_headline_cards_before_diagnostics() -> None:
    source = backtest_source()

    assert "const backtestVerdictMetrics = result ? [" in source
    assert "const backtestMetricRows = result ? [" in source
    assert "title: '收益'" in source
    assert "title: '风险'" in source
    assert "title: '交易'" in source
    assert "label: '胜率'" in source
    assert "label: '盈亏比'" in source
    assert "label: '交易数'" in source
    assert "value: `${totalTradesCount} 笔`" in source
    assert "胜率 / 盈亏比" not in source
    assert "期末权益 / 手续费" not in source
    assert "headlineKpiCards.map" not in source
    assert "diagnosticMetricCards.map" not in source
    assert source.index("backtestVerdictStrip") < source.index("renderBacktestKlineReview({ height: 560 })")
    assert source.index("renderBacktestKlineReview({ height: 560 })") < source.index("backtestDiagnosticMetricSection")
    assert source.index("backtestDiagnosticMetricSection") < source.index("backtestMetricRowStack") < source.index("backtestReviewAuditModule")


def test_backtest_supports_single_and_matrix_timeframe_modes() -> None:
    source = backtest_source()

    assert "function strategyTimeframe" in source
    assert "type BacktestTimeframeMode = 'strategy' | 'single' | 'matrix'" in source
    assert "BACKTEST_TIMEFRAME_OPTIONS" in source
    assert "周期模式" in source
    assert "<select value={timeframe}" not in source
    assert "setTimeframe" not in source
    assert "策略定义" in source
    assert "指定周期" in source
    assert "多周期矩阵" in source
    assert "matrixResults" in source
    assert "timeframe_mode:" in source
    assert "timeframes:" in source
    assert "runConfig.timeframeMode" in source

    run_section = source[source.index("const runBacktest"):source.index("const fmt")]
    assert "timeframe:" in run_section
    assert "timeframes:" in run_section


def test_backtest_matrix_results_can_switch_detail_by_timeframe_tab() -> None:
    source = backtest_source()

    assert "const baseResult = historyDetailResult ?? selectedInstance?.result ?? null;" in source
    assert "const [activeMatrixTimeframe, setActiveMatrixTimeframe]" in source
    assert "const matrixPeriodResults = useMemo" in source
    assert "const activeMatrixResult = useMemo" in source
    assert "const result = activeMatrixResult ?? baseResult;" in source
    assert "backtestMatrixTimeframeTabs" in source
    assert "周期详情" in source
    assert "setActiveMatrixTimeframe(item.timeframe || '')" in source
    assert "activeMatrixTimeframe === item.timeframe" in source
    assert "matrixPeriodResults.map((item)" in source
    assert "result?.timeframe || strategyTimeframe" in source
    assert "result?.trades || []" in source
    assert "buildCryptoBacktestPerformanceMetrics(result)" in source


def test_backtest_instance_cards_render_all_timeframe_chips() -> None:
    source = backtest_source()
    card_section = source[source.index("filteredBacktestInstances.map"):source.index("instanceRunning && (")]

    assert "function backtestInstanceTimeframes" in source
    assert "backtestInstanceTimeframeChip" in source
    assert "const instanceTimeframes = backtestInstanceTimeframes(instance, strategyInfoForInstance);" in card_section
    assert "周期" in card_section
    assert "instanceTimeframes.map((timeframe)" in card_section
    assert "{backtestTimeframeLabel(timeframe)}" in card_section


def test_backtest_config_does_not_show_strategy_trade_range_card() -> None:
    source = backtest_source()

    assert 'Field label="策略交易范围"' not in source
    assert "策略交易范围" not in source


def test_backtest_selector_hides_live_trial_and_non_paper_strategies() -> None:
    source = backtest_source()

    assert "function strategyIsBacktestSelectable" in source
    assert "name.includes('[实盘试运行]')" in source
    assert "name.includes('[实盘]')" in source
    assert "isExplicitFalse(cfg.is_paper_trading)" in source
    assert "isExplicitFalse(cfg.isPaperTrading)" in source
    assert "isExplicitFalse(cfg.dry_run)" in source
    assert "isExplicitFalse(cfg.dryRun)" in source
    assert "const backtestableStrategies = useMemo" in source

    modal_section = source[source.index("创建回测实例"):source.index("确认回测任务")]
    assert "filteredBacktestStrategyOptions.map" in modal_section
    assert "strategies.map" not in modal_section


def test_backtest_strategy_selector_uses_fuzzy_search() -> None:
    source = backtest_source()
    modal_section = source[source.index("创建回测实例"):source.index("确认回测任务")]

    assert "function strategyMatchesBacktestSearch(strategy: any, query: string): boolean" in source
    assert "const [strategySearchQuery, setStrategySearchQuery]" in source
    assert "const filteredBacktestStrategyOptions = useMemo" in source
    assert "strategyMatchesBacktestSearch(strategy, strategySearchQuery)" in source
    assert 'role="combobox"' in modal_section
    assert 'role="listbox"' in modal_section
    assert 'role="option"' in modal_section
    assert 'placeholder="搜索策略名 / 标的 / 周期 / 类型"' in modal_section
    assert "CryptoSelect" not in modal_section


def test_backtest_page_exposes_persisted_history_view() -> None:
    source = backtest_source()
    client = read_text("frontend/src/api/client.ts")

    assert "interface BacktestHistoryItem" in source
    assert "function historyItemToBacktestInstance" in source
    assert "function backtestHistoryIdentity" in source
    assert "const historicalBacktestInstances = useMemo" in source
    assert "const unifiedBacktestInstances = useMemo" in source
    assert "const filteredBacktestInstances = useMemo" in source
    assert "回测历史" not in source
    assert "HISTORY_ASSET_FILTERS" in source
    assert "const loadBacktestHistory = useCallback" in source
    assert "backtestApi.getResults" in source
    assert "function backtestInstanceMatchesSearch" in source
    assert "const [instanceSearchQuery, setInstanceSearchQuery]" in source
    assert 'placeholder="搜索回测实例、策略、标的、周期..."' in source
    instance_filter_section = source[
        source.index('<div className="flex flex-wrap items-center gap-2">') :
        source.index('<div className="rounded-xl border border-crypto-border bg-crypto-card p-4">')
    ]
    instance_header_section = source[
        source.index('<div className="rounded-xl border border-crypto-border bg-crypto-card p-4">') :
        source.index("刷新记录")
    ]
    assert 'placeholder="搜索回测实例、策略、标的、周期..."' not in instance_filter_section
    assert 'placeholder="搜索回测实例、策略、标的、周期..."' in instance_header_section
    assert "query: instanceSearchQuery.trim()" in source
    assert "backtestInstanceMatchesSearch(" in source
    assert "BACKTEST_HISTORY_PAGE_SIZE" in source
    assert "includeMatrixSummary: false" in source
    assert "sortBy: backtestApiSortBy(instanceSortMode)" in source
    assert "sortDir: backtestApiSortDir(instanceSortMode)" in source
    assert "historyHasMore" in source
    assert "offset: historyItems.length" in source
    assert "加载更多回测记录" in source
    assert "backtestApi.getResult" in source
    assert "historyDetailToBacktestResult" in source
    assert "openBacktestRecordDetail(instance)" in source
    assert "deleteBacktestUnifiedRecord(instance)" in source
    assert "isPersistedHistory" in source
    assert "strategyNameColorClass(assetClass)" in source
    assert "strategyAssetBadgeClass(assetClass)" in source
    assert "现货" in source
    assert "合约" in source
    assert "getResults:" in client
    assert "getReq('/backtest/results'" in client
    assert "q: params?.query || undefined" in client
    assert "offset: params?.offset" in client
    assert "sort_by: params?.sortBy" in client
    assert "sort_dir: params?.sortDir" in client
    assert "include_matrix_summary: params?.includeMatrixSummary" in client
    assert "getResult:" in client
    assert "getReq(`/backtest/result/${id}`)" in client


def test_backtest_page_supports_history_delete_and_job_cancel() -> None:
    source = backtest_source()
    client = read_text("frontend/src/api/client.ts")

    assert "import ThemeDialog from '../components/ThemeDialog'" in source
    assert "deleteBacktestHistory" in source
    assert "confirmDeleteBacktestHistory" in source
    assert "historyDeleteTarget" in source
    assert "variant=\"confirm\"" in source
    assert "backtestApi.deleteResult" in source
    assert "删除记录" in source
    assert "删除本地实例" in source
    assert "批量删除" not in source
    assert "selectedHistoryIds" not in source
    assert "window.confirm(`删除这条回测历史" not in source
    assert "window.confirm(" not in source
    assert "localBacktestDeleteTarget" in source
    assert "cancelBacktestTarget" in source
    assert "confirmDeleteLocalBacktestInstance" in source
    assert "confirmCancelBacktestInstance" in source
    assert "删除本地回测实例" in source
    assert "停止当前回测" in source
    assert "cancelBacktestInstance" in source
    assert "backtestApi.cancelJob" in source
    assert "resumeBacktestInstance" in source
    assert "backtestApi.resumeJob" in source
    assert "backtestApi.getJobs" in source
    assert "backtestRequestMatchesInstance" in source
    assert "function backtestInstanceCanContinue(instance: BacktestInstance): boolean" in source
    assert "if (!jobId) {" in source
    assert "const { jobId: newJobId } = await backtestApi.runJob" in source
    assert "backtestInstanceCanContinue(selectedInstance)" in source
    assert "const instanceResumable = backtestInstanceCanContinue(instance)" in source
    assert "status: 'interrupted,failed,pending,running,cancelling'" in source
    assert "继续回测" in source
    assert "resumeJobId" in source
    assert "cancelling" in source
    assert "删除本地回测实例" in source
    assert "请先停止回测" in source
    assert "cancelJob:" in client
    assert "postReq(`/backtest/job/${jobId}/cancel`)" in client
    assert "resumeJob:" in client
    assert "postReq(`/backtest/job/${jobId}/resume`)" in client
    assert "getJobs:" in client
    assert "getReq('/backtest/jobs'" in client
    assert "deleteResult:" in client
    assert "deleteReq(`/backtest/result/${id}`)" in client


def test_backtest_page_supports_parallel_instances() -> None:
    source = backtest_source()

    assert "const BACKTEST_INSTANCES_KEY = 'bitpro_backtest_instances_v1'" in source
    assert "interface BacktestInstance" in source
    assert "function createBacktestInstance" in source
    assert "const [backtestInstances, setBacktestInstances]" in source
    assert "const addBacktestInstance" in source
    assert "回测" in source
    assert "创建回测实例" in source
    assert "回测实例" in source
    assert "space-y-3" in source
    assert "md:grid md:grid-cols-[minmax(320px,1.7fr)_minmax(240px,0.7fr)_minmax(200px,auto)]" in source
    assert "xl:grid-cols-[minmax(420px,1.8fr)_minmax(280px,0.7fr)_minmax(220px,auto)]" in source
    assert "break-words text-sm font-semibold leading-snug" in source
    assert "truncate text-sm font-semibold" not in source[source.index("filteredBacktestInstances.map"):source.index("instanceRunning && (")]
    assert "grid grid-cols-4 gap-2 text-center" in source
    assert 'MiniMetric label="收益"' in source
    assert 'MiniMetric label="回撤"' in source
    assert 'MiniMetric label="夏普"' in source
    assert 'MiniMetric label="交易"' in source
    assert 'MiniMetric label="年化收益"' not in source
    assert 'MiniMetric label="胜率"' not in source
    assert "p-3" in source
    assert "md:py-3" in source
    assert "md:grid md:grid-cols-2 md:items-stretch md:justify-items-stretch" in source
    assert "2xl:flex 2xl:flex-nowrap 2xl:items-center 2xl:justify-end" in source
    assert "BACKTEST_INSTANCE_ACTION_BUTTON_BASE" in source
    assert "backtestInstanceActionButton inline-flex h-9 w-full min-w-[78px]" in source
    assert "md:w-full md:min-w-0 2xl:h-10 2xl:w-auto 2xl:min-w-[92px]" in source
    assert "function backtestInstanceActionButtonClass(tone: BacktestInstanceActionTone" in source
    assert "function backtestInstanceActionStatusTone(status: BacktestInstanceStatus): BacktestInstanceActionTone" in source
    assert "type BacktestInstanceActionTone = 'blue' | 'success' | 'green' | 'red' | 'amber' | 'neutral';" in source
    assert "success: 'border-emerald-300/55 bg-emerald-400/[0.18] text-emerald-50" in source
    assert "function backtestInstanceActionStatusIcon(status: BacktestInstanceStatus)" in source
    assert "case 'completed':\n      return 'success';" in source
    assert "case 'failed':\n      return 'red';" in source
    assert "case 'completed':\n      return <CheckCircle2 className=\"h-4 w-4\" />;" in source
    assert "backtestInstanceActionStatusClass" not in source
    assert "aria-label=\"打开详情\"" in source
    assert "backtestInstanceActionStatusLabel(instance.status)" in source
    assert "aria-label={`查看回测状态：${actionStatusLabel}`}" in source
    assert "aria-label=\"查看日志\"" in source
    assert "回测日志" in source
    assert "回测状态" in source
    assert "function backtestInstanceActionStatusLabel(status: BacktestInstanceStatus)" in source
    assert "case 'completed':\n      return '成功';" in source
    assert "case 'failed':\n      return '失败';" in source
    assert "{instance.errorMessage && !instanceRunning && (" not in source
    assert "aria-label=\"继续回测\"" in source
    action_section = source[source.index("aria-label=\"打开详情\""):source.index("title={instance.isPersistedHistory || instance.historyId ? '删除落库记录' : '删除本地实例'}")]
    assert "FileText" in action_section
    assert "日志" in action_section
    assert "backtestInstanceActionButtonClass('blue')" in action_section
    assert "backtestInstanceActionButtonClass(backtestInstanceActionStatusTone(instance.status))" in action_section
    assert "{backtestInstanceActionStatusIcon(instance.status)}" in action_section
    assert "backtestInstanceActionButtonClass(hasBacktestError ? 'red' : 'neutral')" in action_section
    assert "backtestInstanceActionButtonClass('green')" in action_section
    assert "backtestInstanceActionButtonClass('red')" in action_section
    assert "inline-flex h-8 min-w-[74px]" not in action_section
    assert action_section.index("aria-label={`查看回测状态：${actionStatusLabel}`}") < action_section.index("aria-label=\"查看日志\"") < action_section.index("{instanceRunning ? (")
    assert ">状态<" not in action_section
    assert "md:flex-col" not in action_section
    assert "md:flex-row md:items-center md:justify-end" not in action_section
    assert "md:row-span-2" not in action_section
    assert "grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" not in source
    assert "const [view, setView] = useState<BacktestView>('dashboard')" in source
    assert "const [isCreateModalOpen, setIsCreateModalOpen]" in source
    assert "const [createStep, setCreateStep]" in source
    assert "打开详情" in source
    assert "BACKTEST_WIZARD_STEPS" in source
    assert "选择策略" in source
    assert "配置参数" in source
    assert "执行回测" in source
    assert "查看结果" in source
    assert "const runningJobKey = useMemo" in source
    assert "Promise.all(runningInstances.map" in source
    assert "backtestApi.getJob(instance.activeJobId)" in source


def test_watch_market_route_and_sidebar_position_are_registered() -> None:
    app = read_text("frontend/src/App.tsx")
    layout = read_text("frontend/src/components/MainLayout.tsx")

    assert "const WatchMarket = lazy(() => import('./pages/WatchMarket'))" in app
    assert '<Route path="watch" element={<WatchMarket />} />' in app

    live_pos = layout.index("{ path: '/live'")
    live_real_pos = layout.index("{ path: '/live-real'")
    watch_pos = layout.index("{ path: '/watch'")
    monitor_pos = layout.index("{ path: '/monitor'")
    data_pos = layout.index("{ path: '/data'")
    assert "{ path: '/signals'" not in layout
    assert live_pos < live_real_pos < watch_pos < monitor_pos < data_pos
    assert "label: '盯盘'" in layout


def test_watch_market_page_is_read_only_and_defaults_to_15m_with_trade_markers() -> None:
    page = read_text("frontend/src/pages/WatchMarket.tsx")
    kline = read_text("frontend/src/components/WatchKlineChart.tsx")
    client = read_text("frontend/src/api/client.ts")
    panels = read_text("frontend/src/components/live/LiveAccountSummaryPanels.tsx")

    assert "DEFAULT_TIMEFRAME = '15m'" in page
    assert "liveWatchApi.getWatchlist" in page
    assert "liveWatchApi.getWatchMarket" in page
    assert "liveWatchApi.getTradeMarkers" in page
    assert "liveExecutionApi.listAccounts()" in page
    assert "const [selectedAccountId, setSelectedAccountId] = useState('default')" in page
    assert "CryptoSelect" not in page
    assert 'aria-label="盯盘账户切换"' in page
    assert 'role="tablist"' in page
    assert 'role="tab"' in page
    assert 'aria-selected={account.accountId === selectedAccountId}' in page
    assert 'onClick={() => setSelectedAccountId(account.accountId)}' in page
    assert "liveExecutionApi.listPositions(selectedAccountId)" in page
    assert "liveExecutionApi.listOrderHistory(selectedAccountId, undefined, 100)" in page
    assert "LiveContractPositionsPanel" in page
    assert "LiveOrderDetailsPanel" in page
    assert "TRADE_MARKER_ACTION_LABELS" in kline
    assert "new Set(['open_long', 'close_long', 'open_short', 'close_short'])" in kline
    assert "function markerActionText" in kline
    assert "function markerLabelFormatter" in kline
    assert "getTradeSideDisplay(action)" not in kline
    assert "if (rawAction === 'long') return 'open_long'" in kline
    assert "if (rawAction === 'short') return 'open_short'" in kline
    assert "def _trade_marker_action" in read_text("backend/app/services/live_signal_execution_service.py")
    assert 'return f"open_{normalized_side}"' in read_text("backend/app/services/live_signal_execution_service.py")
    assert 'return f"close_{normalized_side}"' in read_text("backend/app/services/live_signal_execution_service.py")
    assert "const verticalAction = Array.from(actionText)" not in kline
    assert "return `{main|${markerLabel}}`;" in kline
    assert "return `{main|${markerLabel}}\\n" not in kline
    assert "const markerGap = '{gap| }'" not in kline
    assert "value: marker.label,\n          actionText," not in kline
    assert "action:" not in kline
    assert "fontSize: 8" not in kline
    assert "lineHeight: 8" not in kline
    assert "function WatchHeaderMetric" in page
    assert "positionMarginValue(position)" in page
    assert "contractPositionStats" in page
    assert '<WatchHeaderMetric label="仓位" value={contractPositionStats.count} tone="blue" />' in page
    assert '<WatchHeaderMetric label="保证金" value={money(contractPositionStats.margin)} />' in page
    assert 'label="浮盈"' in page
    assert "watchlistStats" in page
    assert '<WatchHeaderMetric label="标的" value={watchlistStats.symbols} tone="blue" />' in page
    assert '<WatchHeaderMetric label="订单" value={watchlistStats.orders} />' in page
    assert '<WatchHeaderMetric label="周期" value={watchlistStats.activeTimeframe} />' in page
    assert "function normalizeWatchSymbolKey" in page
    assert "orderedContractPositions" in page
    assert "watchlistOrder.get(normalizeWatchSymbolKey(left.symbol))" in page
    assert "watchlistOrder.get(normalizeWatchSymbolKey(right.symbol))" in page
    assert "watchWorkspaceLayout" in page
    assert "watchTopPanelGrid" in page
    assert "watchOrdersWidePanel" in page
    assert "watchTilesColumn" in page
    assert "watchPositionsColumn" in panels
    assert "watchPositionsColumn flex h-[min(680px,calc(100vh-180px))] min-h-[560px]" in panels
    assert "watchTilesColumn flex h-[min(680px,calc(100vh-180px))] min-h-[560px]" in page
    assert "watchTilesColumn flex h-[calc(100vh-180px)]" not in page
    assert "rounded-xl border border-crypto-border bg-crypto-bg" in page
    assert "xl:grid-cols-[minmax(520px,680px)_minmax(0,1fr)]" in page
    assert "flex min-h-0 flex-col gap-4" in page
    assert "watchTilesToolbar" in page
    assert "watchTilesBody min-h-0 flex-1 overflow-y-auto p-2.5" in page
    assert "watchOrderSummaryStats" in panels
    assert "visibleOrders.length" in panels
    assert "策略订单" in panels
    assert "外部订单" in panels
    assert "watchOrderSourceName" in panels
    assert "whitespace-normal break-words" in panels
    assert "max-w-[180px] truncate font-semibold" not in panels
    assert "flex bg-crypto-card border border-crypto-border rounded-lg overflow-hidden" in page
    assert "{ value: '1m', label: '1M' }" in page
    for label in ["5M", "15M", "1H", "4H", "1D"]:
        assert f"label: '{label}'" in page
    assert "SELECTED_SEGMENT_CLASS" in page
    assert "bg-gray-100 text-gray-950" not in page
    workspace_pos = page.index("watchWorkspaceLayout")
    top_grid_pos = page.index("watchTopPanelGrid", workspace_pos)
    positions_panel_pos = page.index("<LiveContractPositionsPanel", top_grid_pos)
    tiles_column_pos = page.index("watchTilesColumn", positions_panel_pos)
    tiles_toolbar_pos = page.index("watchTilesToolbar", tiles_column_pos)
    timeframe_controls_pos = page.index("TIMEFRAMES.map", tiles_toolbar_pos)
    grid_pos = page.index("watchTilesGrid", timeframe_controls_pos)
    orders_wide_pos = page.index("watchOrdersWidePanel", tiles_column_pos)
    orders_panel_pos = page.index("<LiveOrderDetailsPanel", orders_wide_pos)
    assert workspace_pos < top_grid_pos < positions_panel_pos < tiles_column_pos < orders_wide_pos < orders_panel_pos
    assert tiles_column_pos < tiles_toolbar_pos < timeframe_controls_pos < grid_pos
    assert tiles_column_pos < page.index("watchlist.length", tiles_column_pos)
    assert "filteredWatchlist" not in page
    assert "搜索标的或策略" not in page
    assert "const [query" not in page
    assert "liveWatchApi.getDerivativesData" not in page
    assert "useTickerWebSocket(marketExchange, symbol)" in page
    assert "useKlineWebSocket(marketExchange, symbol, timeframe)" in page
    assert "liveWatchApi.getWatchlist(selectedAccountId)" in page
    assert "subscribe('live_order', marketExchange, selectedAccountId)" in page
    assert "当前账户暂无由 BitPro 策略执行且仍持仓的标的" in page
    assert "watchTileChartStats grid w-[96px]" in page
    assert "text-lg font-black leading-5 text-blue-200" in page
    assert "text-[13px] font-bold leading-5 text-cyan-100" in page
    hooks = read_text("frontend/src/hooks/useWebSocket.ts")
    assert "msg.channel === 'ticker' && msg.exchange === exchange && msg.symbol === symbol" in hooks
    assert "msg.channel === 'kline' && msg.exchange === exchange && msg.symbol === symbol" in hooks
    assert "function tickerMark" in page
    assert "function tickerDisplayPct" in page
    assert "change_percent_today" in page
    assert "(ticker as any).changePercentToday" in page
    assert "patchLatestKlineWithPrice" in page
    assert "const displayPrice = mark ?? last" in page
    assert "标记价" in page
    assert "最新成交" in page
    assert "setKlines((current) => patchLatestKlineWithPrice(current, displayPrice))" in page
    assert "livePrice={displayPrice}" in page
    assert "WatchDataCharts" not in page
    assert "activeTab" not in page
    assert "setActiveTab" not in page
    assert "OKX 合约数据" not in page
    assert ">数据<" not in page
    assert "function WatchSymbolTile" in page
    assert "watchTilesGrid" in page
    assert "grid grid-cols-1 gap-3 lg:grid-cols-2" in page
    assert "grid-flow-col" not in page
    assert "auto-cols-[minmax(min(88vw,360px),460px)]" not in page
    assert "overflow-x-auto" not in page
    assert "snap-x snap-mandatory" not in page
    assert "snap-start" not in page
    assert "watchTileCard" in page
    assert "watchTileHeader" not in page
    assert "watchTileTitleRow" in page
    assert "watchTileChartSummary" in page
    assert "watchTileChartStats" in page
    assert "watchTilePriceStrip" not in page
    assert "watchTileMiniStats" not in page
    assert "watchTileBody space-y-2.5 p-3" in page
    assert "watchTileChartShell" in page
    assert "height={460}" in page
    assert "header={" in page
    assert "text-[28px]" in page
    assert "height={188}" not in page
    assert "height={236} compact" not in page
    assert "rounded-[22px]" not in page
    assert "text-4xl" not in page
    assert "height={360} compact" not in page
    assert "gridTemplateColumns" not in page
    assert "OKX_MOBILE_CARD_WIDTH" not in page
    assert "selectedSymbol" not in page
    assert "setSelectedSymbol" not in page
    assert "grid-cols-[320px_minmax(0,1fr)]" not in page
    assert "watchTopPanelRow" not in page
    assert "<aside" not in page
    assert "CompactOrderbookAndTrades" not in page
    assert "useOrderbookWebSocket" not in page
    assert "function MiniStats" not in page
    assert "<MiniStats" not in page
    assert "24h高" not in page
    assert "24h低" not in page
    assert "额 USDT" not in page
    assert "盘口" not in page
    assert "最近成交" not in page
    assert "下单" not in page
    assert "交易" not in page

    assert "markPoint" in kline
    assert "livePrice?: number | null" in kline
    assert "header?: ReactNode" in kline
    assert "showHeader?: boolean" in kline
    assert "header ?? (showHeader ?" in kline
    assert "currentPriceLine" in kline
    assert "markLine: currentPriceLine" in kline
    assert "type: 'dashed'" in kline
    assert "position: 'end'" in kline
    assert "currentCandleCountdown(timeframe)" in kline
    assert "marker.label === 'B'" in kline
    assert "params?.data?.value === 'S'" in kline
    assert "const BUY_MARKER_COLOR = '#ef4444';" in kline
    assert "const SELL_MARKER_COLOR = '#22c55e';" in kline
    assert "color: isBuy ? BUY_MARKER_COLOR : SELL_MARKER_COLOR" in kline
    assert "const TRADE_MARKER_WIDTH = 12" in kline
    assert "TRADE_MARKER_SIZE: [number, number] = [TRADE_MARKER_WIDTH, 16]" in kline
    assert "symbol: 'rect'" in kline
    assert "symbol: 'roundRect'" not in kline
    assert "fontSize: 10" in kline
    assert "lineHeight: 12" in kline
    assert "barWidth: TRADE_MARKER_WIDTH" in kline
    assert "type TradeMarkerLayout" in kline
    assert "const markerLayouts = Array.from(markerLayoutMap.values())" in kline
    assert "const markerLayoutMap = new Map<string, TradeMarkerLayout>()" in kline
    assert "markerTimestamp < firstTimestamp || markerTimestamp >= lastTimestamp + candleIntervalMs" in kline
    assert "existing.markerCount += 1" in kline
    assert "同K线合并" in kline
    assert "const markerPrice = finite(marker.price)" in kline
    assert "Math.min(candleLow, markerPrice) - markerLineOffset" in kline
    assert "Math.max(candleHigh, markerPrice) + markerLineOffset" in kline
    assert "const markerAxisPrices = markerLayouts.flatMap((layout) => [layout.markerPrice, layout.labelPrice])" in kline
    assert "...markerAxisPrices" in kline
    assert "min: chartMinPrice - pricePadding" in kline
    assert "max: chartMaxPrice + pricePadding" in kline
    assert "const markerGuideLines = markerLayouts" in kline
    assert "data: markerGuideLines" in kline
    assert "finite(bar?.low, markerPrice)" in kline
    assert "finite(bar?.high, markerPrice)" in kline
    assert "symbolKeepAspect: false" in kline
    assert "symbolOffset: isBuy ? [0, 14] : [0, -14]" not in kline
    assert "borderColor: 'rgba(248, 250, 252, 0.72)'" in kline
    assert "shadowBlur: 6" in kline
    assert "borderWidth: 1" in kline
    assert "B 买入" not in kline
    assert "S 卖出" not in kline
    assert "rounded-full border border-red-400/30" not in kline
    assert "rounded-full border border-green-400/30" not in kline
    assert "h-2.5 w-2.5 rounded-sm bg-red-500" in kline
    assert "h-2.5 w-2.5 rounded-sm bg-green-500" in kline
    assert "EMA5" in kline and "EMA10" in kline and "EMA20" in kline
    assert "MACD" in kline
    assert "WATCH_LINE_LEGEND_ICON = 'path://M1,5 L18,5'" in kline
    assert "{ name: 'EMA5', icon: WATCH_LINE_LEGEND_ICON }" in kline
    assert "{ name: 'DIF', icon: WATCH_LINE_LEGEND_ICON }" in kline
    assert "APP_DEFAULT_VISIBLE_CANDLES = 36" in kline
    assert "DESKTOP_DEFAULT_VISIBLE_CANDLES = 80" in kline
    assert "const visibleCandles = compact ? APP_DEFAULT_VISIBLE_CANDLES : DESKTOP_DEFAULT_VISIBLE_CANDLES" in kline
    assert "const gridRight = compact ? 76 : 68" in kline
    assert "{ left: gridLeft, right: gridRight, top: 28, height: '60%' }" in kline
    assert "100 - (visibleCandles / Math.max(1, rows.length)) * 100" in kline

    assert "export const liveWatchApi" in client
    assert "getReq('/live/watchlist'" in client
    assert "getReq('/live/watchlist/market'" in client
    assert "getReq('/live/watchlist/markers'" in client
    assert "getReq('/live/watchlist/derivatives-data'" in client


def test_watch_kline_axis_ignores_trade_markers_outside_loaded_window() -> None:
    kline = read_text("frontend/src/components/WatchKlineChart.tsx")

    assert "markers.forEach((marker) => {\n      const price = Number(marker.price);" not in kline
    assert "const markerAxisPrices = markerLayouts.flatMap((layout) => [layout.markerPrice, layout.labelPrice])" in kline
    assert "...markerAxisPrices" in kline
    assert "...basePriceValues" in kline
    assert "markerTimestamp < firstTimestamp || markerTimestamp >= lastTimestamp + candleIntervalMs" in kline
    assert kline.index("const markerLayouts = Array.from(markerLayoutMap.values())") < kline.index("const markerAxisPrices")


def test_watch_market_reuses_live_account_summary_panels_with_close_actions() -> None:
    panel = read_text("frontend/src/components/live/LiveAccountSummaryPanels.tsx")
    page = read_text("frontend/src/pages/WatchMarket.tsx")

    assert "export function LiveContractPositionsPanel" in panel
    assert "export function LiveOrderDetailsPanel" in panel
    assert "readonly?: boolean" in panel
    assert "readonly = true" in panel
    assert "headerStats?: ReactNode" in panel
    assert "{headerStats || <span className=\"text-[10px] text-gray-500\">衍生品仓位</span>}" in panel
    assert "合约持仓" in panel
    assert "订单明细" in panel
    assert "当前账户无合约持仓" in panel
    assert "暂无订单明细" in panel
    assert "visibleRows = maxRows && maxRows > 0 ? rows.slice(0, maxRows) : rows" in panel
    assert "const [orderSearchQuery, setOrderSearchQuery] = useState('')" in panel
    assert "function orderMatchesSearch(order: LiveExecutionOrder, tokens: string[]): boolean" in panel
    assert "filteredOrders = useMemo(" in panel
    assert "visibleOrders = filteredOrders.slice(0, maxRows)" in panel
    assert "placeholder=\"搜索交易对 / 策略 / 订单号...\"" in panel
    assert "未找到匹配订单" in panel
    assert "onShowLog" in panel
    assert "onClosePosition" in panel
    assert "if (readonly) return null;" in panel
    assert "liveAccountPanelShell" in panel
    assert "liveContractPositionsPanelShell" in panel
    assert "liveAccountPanelHeader" in panel
    assert "liveAccountPanelBody" in panel
    assert "flex h-[min(680px,calc(100vh-180px))] min-h-[560px] min-w-0 flex-col" in panel
    assert "min-h-0 flex-1 overflow-y-auto" in panel
    assert "overflow-x-auto" in panel
    assert "grid grid-cols-1 gap-2.5 sm:grid-cols-2" in panel
    assert "flex min-w-0 items-start justify-between gap-3" in panel
    assert "positionMetrics = [" in panel
    assert "grid grid-cols-2 gap-x-5 gap-y-3 border-t border-crypto-border/60 pt-3 sm:grid-cols-3" in panel
    assert "positionMetricCell" in panel
    assert "tabular-nums" in panel
    assert "mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-crypto-border/50 pt-3" in panel
    assert "LivePositionCloseConfirm" in page
    assert "openPositionCloseConfirm(position, false)" in page
    assert "openPositionCloseConfirm(position, true)" in page
    assert "liveExecutionApi.closePosition(selectedAccountId" in page
    assert "accountLabel={selectedAccountLabel}" in page
    assert "exchangeLabel={selectedAccountExchangeLabel}" in page
    assert "confirmLiveRisk: true" in page
    assert "onClosePosition={(position) => openPositionCloseConfirm(position, false)}" in page
    assert "onCloseAll={(position) => openPositionCloseConfirm(position, true)}" in page
    assert "<LiveContractPositionsPanel" in page
    assert "readonly={false}" in page
    assert "rows={orderedContractPositions}" in page
    assert "maxRows={4}" not in page
    assert '<LiveContractPositionsPanel rows={contractPositions} readonly' not in page
    assert "<LiveOrderDetailsPanel orders={historyOrders} maxRows={100} onShowLog={setOrderLog} />" in page


def test_backtest_page_hides_placeholder_instance_cards_when_empty() -> None:
    source = backtest_source()

    assert "function isBacktestPlaceholderInstance" in source
    assert "function isBacktestUnhydratedCompletedInstance" in source
    assert "function isPersistedBacktestStrategyName" in source
    assert "function backtestStrategyDisplayName" in source
    assert "策略加载中" in source
    assert "策略已不存在" in source
    assert "fallbackName" in source
    assert "strategyNameById(strategies, item.strategyId, item.strategyName)" in source
    assert "backtestStrategyDisplayName(" in source
    assert "instance.result?.strategyName || instance.name" in source
    assert "knownStrategies.get(Number(strategyId))" in source
    assert "strategyIsBacktestSelectable(strategy)" in source
    assert "selectableIds.has(Number(strategyId))" not in source
    assert "`策略 #${strategyId}`" not in source
    assert "const hasErrorMessage = Boolean(raw.errorMessage)" in source
    assert "status: hasErrorMessage ? 'failed' : " in source
    assert ".filter((instance) => !isBacktestPlaceholderInstance(instance))" in source
    assert ".filter((instance) => !isBacktestUnhydratedCompletedInstance(instance))" in source
    assert "return legacy.activeJobId ? [legacy] : [];" in source
    assert "const next = rest.map((instance, index) =>" in source
    assert "setSelectedInstanceId(next[0]?.id || '')" in source
    assert "localStorage.removeItem(SELECTED_BACKTEST_INSTANCE_KEY)" in source
    assert "const historicalBacktestInstances = useMemo" in source
    assert "const unifiedBacktestInstances = useMemo" in source
    assert "const shouldRenderBacktestInstances =" in source
    assert "unifiedBacktestInstances.length > 0 || isLoadingHistory || Boolean(historyError)" in source
    assert "{shouldRenderBacktestInstances && (" in source


def test_backtest_asset_badge_uses_instance_name_while_strategy_metadata_loads() -> None:
    source = backtest_source()

    assert "function inferStrategyAssetClassFromName" in source
    assert "function backtestInstanceAssetClass" in source
    assert "function backtestResultAssetClass" in source
    assert "inferStrategyAssetClassFromName(instance.name)" in source
    assert "const assetClass = backtestInstanceAssetClass(backtestableStrategies, instance);" in source
    assert "const resultAssetClass = backtestResultAssetClass(strategies, result, selectedStrategy);" in source
    assert "counts[backtestInstanceAssetClass(backtestableStrategies, instance)] += 1;" in source
    assert "backtestInstanceAssetClass(backtestableStrategies, instance) === instanceAssetFilter" in source


def test_backtest_page_uses_console_modal_detail_interaction() -> None:
    source = backtest_source()
    client = read_text("frontend/src/api/client.ts")

    assert "type BacktestView = 'dashboard' | 'detail'" in source
    assert "BACKTEST_STATUS_FILTERS" in source
    assert "BACKTEST_SORT_CONTROLS" in source
    assert "function backtestSortDirectionFor" in source
    assert "function nextBacktestSortMode" in source
    assert "function BacktestSortArrow" in source
    assert "创建时间" in source
    assert "收益率" in source
    assert "回撤" in source
    assert "胜率" in source
    assert "const [instanceSortMode, setInstanceSortMode] = useState<BacktestSortMode>('created_desc');" in source
    assert source.index("{ field: 'return', label: '收益率' }") < source.index("{ field: 'drawdown', label: '回撤' }")
    assert source.index("{ field: 'drawdown', label: '回撤' }") < source.index("{ field: 'win_rate', label: '胜率' }")
    assert source.index("{ field: 'win_rate', label: '胜率' }") < source.index("{ field: 'created', label: '创建时间' }")
    assert "function defaultBacktestSortDirection" in source
    assert "field === 'drawdown' ? 'asc' : 'desc'" in source
    assert "sortBy?: 'created' | 'return' | 'drawdown' | 'win_rate';" in client
    assert "创建新→旧" not in source
    assert "收益高→低" not in source
    assert "SELECTED_SEGMENT_CLASS" in source
    assert "instanceAssetFilter" in source
    assert "instanceStatusFilter" in source
    assert "instanceSortMode" in source
    assert "historyDetailResult" in source
    assert "setIsCreateModalOpen(true)" in source
    assert "setView('detail')" in source
    assert "返回控制台" in source
    assert "最近1月" in source
    assert "最近6月" in source
    assert "最近1年" in source
    assert "最近2年" in source


def test_backtest_result_detail_card_does_not_repeat_strategy_title_and_labels_range() -> None:
    source = backtest_source()
    detail_header = source[
        source.index("返回控制台"):
        source.index("{/* ====== 专业回测报告壳 ====== */}")
    ]

    assert "回测时间范围" in detail_header
    assert detail_header.count("回测时间范围") == 1
    assert "result.strategyName || '策略回测结果'" not in detail_header
    assert "策略名称" not in detail_header
    assert "已落库" not in detail_header


def test_backtest_detail_symbol_scope_uses_result_strategy_before_selected_strategy() -> None:
    source = backtest_source()

    assert "const detailStrategyInfo = resultStrategyInfo || selectedStrategyInfo;" in source
    assert "strategySymbols(detailStrategyInfo)" in source
    assert "strategyTradeSymbols(detailStrategyInfo)" in source
    assert "strategySymbols(selectedStrategyInfo)" not in source
    assert "strategyTradeSymbols(selectedStrategyInfo)" not in source


def test_backtest_cost_controls_use_okx_maker_taker_and_slippage_bps() -> None:
    source = backtest_source()

    assert "function strategyBacktestCostDefaults" in source
    assert "const OKX_SPOT_BACKTEST_COSTS = { makerFeeBps: 8, takerFeeBps: 10, slippageBps: 1 }" in source
    assert "const OKX_SWAP_BACKTEST_COSTS = { makerFeeBps: 2, takerFeeBps: 5, slippageBps: 1 }" in source
    defaults_section_start = source.index("function strategyBacktestCostDefaults")
    defaults_section_end = source.index("function symbolSummary")
    defaults_section = source[defaults_section_start:defaults_section_end]
    assert "cfg." not in defaults_section
    assert "makerFromConfig" not in defaults_section
    assert "Maker 手续费 (bps)" in source
    assert "Taker 手续费 (bps)" in source
    assert "滑点 (bps)" in source
    assert "maker_fee_bps" in source
    assert "taker_fee_bps" in source
    assert "slippage_bps" in source
    assert 'Field label="手续费率"' not in source

    run_section = source[source.index("const runBacktest"):source.index("const fmt")]
    assert "maker_fee_bps: effectiveMakerFeeBps" in run_section
    assert "taker_fee_bps: effectiveTakerFeeBps" in run_section
    assert "slippage_bps: effectiveSlippageBps" in run_section
    assert "commission" not in run_section
    assert "slippage:" not in run_section

    prefs_payload_start = source.index("const payload: BacktestPrefsV1 = {")
    prefs_payload_end = source.index("localStorage.setItem(BACKTEST_PREFS_KEY", prefs_payload_start)
    prefs_payload = source[prefs_payload_start:prefs_payload_end]
    assert "makerFeeBps" not in prefs_payload
    assert "takerFeeBps" not in prefs_payload
    assert "slippageBps" not in prefs_payload
    assert "strategyChanged" in source


def test_backtest_end_date_defaults_to_current_date_not_stale_preferences() -> None:
    source = backtest_source()

    assert "function dateInputValue(date: Date): string" in source
    assert "function todayDateInputValue(): string" in source
    assert "function createBacktestInstance" in source
    assert "function clampIsoDateToToday(value: string | undefined, fallback: string): string" in source
    assert "function backtestDateValidationMessage(config: BacktestInstanceConfig): string | null" in source
    assert "endDate: clampIsoDateToToday(partial.endDate, range.end)" in source
    assert "结束日期不能晚于当前日期" in source
    assert "max={todayDate}" in source
    assert "initialBt?.endDate" not in source

    prefs_payload = source[
        source.index("const payload: BacktestPrefsV1 = {"):
        source.index("localStorage.setItem(BACKTEST_PREFS_KEY")
    ]
    assert "endDate" not in prefs_payload


def test_backtest_page_exposes_running_strategy_batch_entry() -> None:
    source = backtest_source()
    client = read_text("frontend/src/api/client.ts")

    assert "创建批量回测实例" in source
    assert "const [batchBacktestConfirmOpen" in source
    assert "const [isBatchBacktestSubmitting" in source
    assert "function defaultBatchBacktestDateRange()" in source
    assert "const createBatchBacktestInstances = async ()" in source
    assert "backtestApi.runRunningStrategies" in source
    assert "runRunningStrategies" in client
    assert "initialCapital: Number(job.request?.initialCapital ?? job.request?.initial_capital ?? 100)" in source
    assert "批量默认使用 100U" in source
    assert "border border-blue-500/70 bg-blue-600" in source

    header = source[
        source.index("创建异步任务，在列表比较结果"):
        source.index("{shouldRenderBacktestInstances && (")
    ]
    assert header.index("创建批量回测实例") < header.index("创建回测实例")
    assert "批量回测" in header
    assert "创建回测" in header


def test_backtest_trade_table_shows_recent_historical_execution_prices() -> None:
    source = backtest_source()

    assert "const displayedTrades = useMemo" in source
    assert "b.timestamp - a.timestamp" in source
    assert "历史成交价" in source
    assert "历史撮合价，已计入滑点假设" in source
    assert "不是当前行情价" in source
    assert "按时间倒序显示最近100笔" in source
    assert "backtestTradeLedgerFrame flex h-[520px] flex-col overflow-hidden" in source
    assert "md:h-[560px]" in source
    assert "min-h-0 flex-1 overflow-auto" in source
    assert "sticky top-0 z-10 bg-crypto-bg/95 backdrop-blur" in source


def test_backtest_trade_table_shows_contract_execution_metrics() -> None:
    source = backtest_source()
    normalize_start = source.index("function normalizeHistoryTrades")
    normalize_end = source.index("function timeframeMs", normalize_start)
    normalize_section = source[normalize_start:normalize_end]
    trade_tab_start = source.index("{/* ====== 交易流水 ====== */}")
    trade_tab_end = source.index("</table>", trade_tab_start)
    trade_tab_section = source[trade_tab_start:trade_tab_end]

    assert "leverage?: number" in source
    assert "margin?: number" in source
    assert "notional_usdt?: number" in source
    assert "trade?.leverage" in normalize_section
    assert "trade?.margin" in normalize_section
    assert "trade?.notional_usdt" in normalize_section
    assert "杠杆" in trade_tab_section
    assert "保证金" in trade_tab_section
    assert "成交名义" in trade_tab_section
    assert "formatBacktestTradeLeverage(trade.leverage)" in trade_tab_section
    assert "backtestTradeMargin(trade)" in trade_tab_section
    assert "backtestTradeNotional(trade)" in trade_tab_section


def test_backtest_trade_records_render_kline_entry_exit_markers() -> None:
    source = backtest_source()
    kline = read_text("frontend/src/components/WatchKlineChart.tsx")

    assert "const WatchKlineChart = lazy(() => import('../components/WatchKlineChart'));" in source
    assert "function tradeRecordMarkerLabel" in source
    assert "normalized.includes('close_short')" in source
    assert "normalized.includes('close_long')" in source
    assert "function buildBacktestTradeMarkers" in source
    assert "const [selectedTradeChartSymbol, setSelectedTradeChartSymbol]" in source
    assert "const [tradeChartKlines, setTradeChartKlines]" in source
    assert "marketApi.getKlines('okx', selectedTradeChartSymbol, resultStrategyTimeframe, 1000" in source
    assert "买卖点 K线复盘" in source
    assert "<WatchKlineChart" in source
    assert "markers={tradeChartMarkers}" in source
    assert "复用盯盘 K 线风格展示回测成交 B/S 点" in source
    assert "backtestKlineSymbolChips" in source
    assert "rounded-full border px-4" in source
    assert "区间收益" not in source
    assert "区间最大回撤" not in source
    assert "return `{main|${markerLabel}}`;" in kline
    assert "return `{main|${markerLabel}}\\n" not in kline
    assert "value: marker.label,\n          actionText," not in kline


def test_backtest_benchmark_uses_selected_date_range_for_klines() -> None:
    source = backtest_source()
    client = read_text("frontend/src/api/client.ts")

    assert "const BACKTEST_BENCHMARK_SYMBOL = 'BTC/USDT';" in source
    assert "function strategyBenchmarkSymbol" in source
    assert "function dateToStartMs(date: string): number" in source
    assert "function dateToEndMs(date: string): number" in source
    assert "return BACKTEST_BENCHMARK_SYMBOL" in source
    assert "strategySymbols(strategy)[0]" not in source
    assert "const benchmark = strategyBenchmarkSymbol();" in source
    assert "const benchmarkSymbol = strategyBenchmarkSymbol();" in source
    assert "dateToStartMs(benchmarkStartDate)" in source
    assert "dateToEndMs(benchmarkEndDate)" in source
    assert ".filter((k) => k.timestamp >= rangeStart && k.timestamp <= rangeEnd)" in source
    assert "label: `${benchmarkSymbol} 同期`" in source
    assert "label: '超额收益'" in source
    assert "const alpha = strategyTotalReturn == null ? null : strategyTotalReturn - benchmarkReturn" in source
    assert "start?: number" in client
    assert "end?: number" in client
    assert "params: { exchange, symbol, timeframe, limit, start, end }" in client


def test_backtest_history_detail_loads_btc_benchmark_klines() -> None:
    source = backtest_source()

    assert "const [historyBenchmarkKlines, setHistoryBenchmarkKlines]" in source
    assert "const benchmarkKlines = historyDetailResult ? historyBenchmarkKlines : selectedInstance?.benchmarkKlines ?? [];" in source
    assert "setHistoryBenchmarkKlines([]);" in source
    assert "const benchmark = await fetchBenchmarkKlinesForResult(detailResult, historyBenchmarkConfig);" in source
    assert "setHistoryBenchmarkKlines(benchmark);" in source


def test_backtest_overview_metrics_explain_formulae_and_alpha() -> None:
    source = backtest_source()

    assert "function buildCryptoBacktestPerformanceMetrics" in source
    assert "function annualizedVolatilityFromEquityCurve" in source
    assert "function deriveBacktestTradePnlSamples" in source
    assert "function rebuildEquityCurveFromTradePnl" in source
    assert "function deriveBacktestHistoryMetrics" in source
    assert "calmarRatio: finiteNumber(detail?.calmarRatio) ?? derivedMetrics.calmarRatio" in source
    assert "sortinoRatio: finiteNumber(detail?.sortinoRatio) ?? derivedMetrics.sortinoRatio" in source
    assert "expectancy: finiteNumber(detail?.expectancy) ?? derivedMetrics.expectancy" in source
    assert "function CryptoMetricGroup" not in source
    assert "cryptoMetricGroups.map" not in source
    assert "backtestUnifiedReport" in source
    assert "绩效诊断" in source
    assert "绩效明细" in source
    assert "backtestVerdictStrip" in source
    assert "backtestMetricRowStack" in source
    assert "backtestMetricCategoryRow" in source
    assert "backtestDetailMetricRow" in source
    assert "backtestMetricRows.map" in source
    assert "基准与波动" not in source
    assert "单笔质量" not in source
    assert "交易行为" not in source
    assert "样本结构" not in source
    assert "手续费占本金" in source
    assert "期望/笔" in source
    assert "平均盈利" in source
    assert "平均亏损" in source
    assert "最大连胜/连亏" in source
    assert "value={benchmarkStats.alpha != null ? fmtPct(benchmarkStats.alpha) : fmt(result.calmarRatio)}" not in source
    assert "const alpha = strategyTotalReturn == null ? null : strategyTotalReturn - benchmarkReturn" in source
    assert "Cov(策略日收益, 基准日收益) / Var(基准日收益)" in source
    assert "text-[clamp(1rem,1.05vw,1.25rem)] font-extrabold" not in source
    assert "text-[clamp(1.15rem,1.35vw,1.55rem)] font-black" not in source


def test_backtest_detail_uses_single_professional_report_and_data_quality_badge() -> None:
    source = backtest_source()

    assert "dataQualityStatus?: string | null" in source
    assert "dataQualityMessage?: string | null" in source
    assert "const resultDataInvalidated = result?.dataQualityStatus === 'invalidated';" in source
    assert "回测研究报告" not in source
    assert "backtestMetricRowStack" in source
    assert "backtestUnifiedReportNav" not in source
    assert ">单页报告</span>" not in source
    assert ">K线复盘</span>" not in source
    assert "backtestDetailTabs" not in source
    assert "type ResultTab" not in source
    assert "resultTab" not in source
    assert "数据可信度" in source
    assert "历史结果不可继续信任" in source
    assert "研究结论" in source
    assert "风险闸门" in source
    assert "成本审计" in source
    assert "绩效诊断" in source
    assert "交易流水" in source
    assert "renderBacktestKlineReview({ height: 560 })" in source
    assert "showRangeStats" not in source
    assert "renderBacktestKlineReview({ height: 520 })" not in source
    assert "const backtestVerdictMetrics = result ? [" in source
    assert "const backtestMetricRows = result ? [" in source
    assert "backtestDetailMetricRow" in source
    assert "backtestMetricRows.map" in source
    assert "backtestUnifiedMetricModule backtestDiagnosticMetricSection rounded-xl border border-crypto-border bg-crypto-bg/30 p-4" in source
    assert "backtestMetricRowStack mt-3 grid gap-3 lg:grid-cols-3" in source
    assert "backtestMetricCategoryRow rounded-xl border p-3" in source
    assert "renderMetricRow(metric)" in source
    assert "backtestMetricHelp group relative inline-flex shrink-0" in source
    assert "aria-label={`${label}指标说明`}" in source
    assert "role=\"tooltip\"" in source
    assert "group-hover:block group-focus-within:block" in source
    assert "<HelpCircle className=\"h-3.5 w-3.5\" />" in source
    assert "BadgeInfo" not in source
    assert "rounded-md border border-crypto-border bg-crypto-bg/80" not in source
    assert "backtestDetailKpiStrip grid grid-cols-2 gap-3 border-t border-crypto-border bg-crypto-bg/20 p-5" not in source
    assert "backtestDetailKpiStrip grid grid-cols-2 gap-px bg-crypto-border" not in source
    assert "xl:grid-cols-9" not in source
    metric_module = source[source.index("backtestUnifiedMetricModule"):source.index("backtestReviewAuditModule")]
    assert "xl:grid-cols-8" not in metric_module
    assert metric_module.count("backtestMetricCategoryRow rounded-xl border p-3") == 1
    assert "三类指标分三行展示" not in metric_module
    assert "宽屏每行六张卡" not in metric_module
    verdict_rows = source[source.index("const backtestVerdictMetrics = result ? ["):source.index("const backtestMetricRows = result ? [")]
    assert "label: '净收益'" in verdict_rows
    assert "label: '超额收益'" in verdict_rows
    assert "label: '最大回撤'" in verdict_rows
    assert "label: '夏普'" in verdict_rows
    metric_rows = source[source.index("const backtestMetricRows = result ? ["):source.index("const metricGuideItems = [")]
    assert "title: '收益'" in metric_rows
    assert "title: '风险'" in metric_rows
    assert "title: '交易'" in metric_rows
    assert "label: '年化收益'" in metric_rows
    assert "label: '期末权益'" in metric_rows
    assert "label: `${benchmarkSymbol} 同期`" in metric_rows
    assert "label: '手续费'" in metric_rows
    assert "label: 'Calmar'" in metric_rows
    assert "label: 'Sortino'" in metric_rows
    assert "label: '年化波动'" in metric_rows
    assert "label: 'Beta'" in metric_rows
    assert "label: '回撤持续'" in metric_rows
    assert "label: '胜率'" in metric_rows
    assert "label: '盈亏比'" in metric_rows
    assert "label: '赔率'" in metric_rows
    assert "label: '期望/笔'" in metric_rows
    assert "label: '盈利/亏损'" in metric_rows
    assert "label: '交易数'" in metric_rows
    assert "label: '净收益'" not in metric_rows
    assert "label: '超额收益'" not in metric_rows
    assert "label: '最大回撤'" not in metric_rows
    assert "label: '夏普'" not in metric_rows
    assert "label: '平均盈利'" not in metric_rows
    assert "label: '平均亏损'" not in metric_rows
    assert "label: '最大连胜/连亏'" not in metric_rows
    assert "label: '平均持仓'" not in metric_rows
    assert "label: 'K线样本'" not in metric_rows
    assert "label: '执行耗时'" not in metric_rows
    assert "胜率 / 盈亏比" not in source
    assert "期末权益 / 手续费" not in source

    assert "backtestReviewAuditOpen" not in source
    assert "setBacktestReviewAuditOpen" not in source
    assert "ChevronDown" not in source
    assert "backtestReviewAuditModule rounded-xl border border-crypto-border bg-crypto-card/80" in source
    assert "aria-expanded={backtestReviewAuditOpen}" not in source
    assert "setBacktestReviewAuditOpen((value) => !value)" not in source
    assert "研究诊断与审计" in source
    assert "backtestReviewAuditGrid grid gap-5 lg:grid-cols-3" in source
    assert "backtestReviewAuditPanel min-w-0 border-l border-blue-500/40 pl-4" in source
    assert "backtestReviewAuditPanel min-w-0 border-l border-amber-500/40 pl-4" in source
    assert "backtestReviewAuditPanel min-w-0 border-l border-emerald-500/40 pl-4" in source
    assert "xl:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.65fr)]" not in source
    assert "回撤闸门" in source
    assert "benchmarkGateLabel" in source

    result_card_start = source.index("{/* ====== 专业回测报告壳 ====== */}")
    report_start = source.index("{/* ====== 报告主体 ====== */}", result_card_start)
    kline_start = source.index("renderBacktestKlineReview({ height: 560 })", report_start)
    performance_start = source.index("{/* ====== 绩效诊断 ====== */}", report_start)
    review_audit_start = source.index("backtestReviewAuditModule", performance_start)
    conclusion_start = source.index("研究结论", review_audit_start)
    trades_start = source.index("{/* ====== 交易流水 ====== */}", performance_start)
    assert report_start < source.index("backtestVerdictStrip", report_start) < kline_start
    assert kline_start < performance_start < review_audit_start < trades_start
    assert source.index("backtestUnifiedMetricModule", performance_start) < source.index("backtestMetricRowStack", performance_start)
    assert source.index("backtestMetricRowStack", performance_start) < review_audit_start
    assert review_audit_start < conclusion_start < trades_start


def test_backtest_metric_module_exposes_hover_metric_explanations() -> None:
    source = backtest_source()

    assert "backtestMetricGuideAnchor" not in source
    assert 'href="#backtestMetricGuide"' not in source
    assert 'id="backtestMetricGuide"' not in source
    assert "backtestMetricGuideList mt-3 grid max-h-[260px] gap-x-5 overflow-y-auto" not in source
    assert "const metricGuideByLabel = new Map(metricGuideItems.map((item) => [item.label, item]));" in source
    assert "const renderMetricHelp = (label: string) => {" in source
    assert "const helpId = `backtestMetricHelp-${label.replace" in source
    assert "aria-describedby={helpId}" in source
    assert "role=\"tooltip\"" in source
    assert "HelpCircle" in source
    assert "BadgeInfo" not in source
    assert "rounded-md border border-crypto-border bg-crypto-bg/80" not in source
    assert "年化收益 / 最大回撤" in source
    assert "最大回撤很小时该值会被放大" in source
    assert "总盈利 / 总亏损" in source
    assert "策略累计收益 - BTC/USDT 同期收益" in source
    assert "Cov(策略日收益, 基准日收益) / Var(基准日收益)" in source
    assert "只惩罚亏损方向波动的风险调整收益" in source


def test_backtest_instance_metric_labels_are_readable() -> None:
    source = backtest_source()

    mini_metric = source[source.index("function MiniMetric"):]
    assert "text-[9px] text-gray-600" not in mini_metric
    assert "mt-1 text-xs font-medium text-gray-500" in mini_metric


def test_backtest_overview_replaces_equity_curve_with_kline_review() -> None:
    source = backtest_source()

    assert "function buildBacktestChartData" not in source
    assert "rangeReturn" not in source
    assert "rangeMaxDrawdown" not in source
    assert "if (!selectedTradeChartSymbol || tradeChartMarkers.length === 0)" in source
    assert "resultTab" not in source
    assert "资金曲线" not in source
    assert "<BacktestChart" not in source
    assert "function BacktestChart" not in source
    assert "买卖点 K线复盘" in source
    assert "复用盯盘 K 线风格展示回测成交 B/S 点" in source
    assert "backtestKlineSymbolChips" in source
    assert "markers={tradeChartMarkers}" in source


def test_nginx_templates_compress_and_cache_static_assets() -> None:
    for path in ("deploy/bitpro.nginx", "deploy/setup-server.sh"):
        source = read_text(path)
        assert "gzip on;" in source
        assert "gzip_vary on;" in source
        assert "gzip_min_length 1024;" in source
        assert "application/javascript" in source
        assert "text/css" in source
        assert "Cache-Control \"public, max-age=604800, immutable\"" in source
        assert "location ~* \\.(?:js|css|json|svg)$" in source
        assert "location = /index.html" in source
        assert "try_files /index.html =404;" in source
        assert "Cache-Control \"no-store, no-cache, must-revalidate\"" in source
        assert "try_files $uri $uri/ /index.html;" in source


def test_nginx_production_domain_uses_https_and_preserves_api_websocket_routes() -> None:
    source = read_text("deploy/bitpro.nginx")

    assert "server_name bitpro.notenap.com;" in source
    assert "listen 127.0.0.1:8448 ssl;" in source
    assert "return 301 https://$host$request_uri;" in source
    assert "root /var/www/letsencrypt;" in source
    assert "/etc/letsencrypt/live/bitpro.notenap.com/fullchain.pem" in source
    assert "/etc/letsencrypt/live/bitpro.notenap.com/privkey.pem" in source
    assert "location = /api/v2/ws" in source
    assert "proxy_set_header Upgrade $http_upgrade;" in source
    assert "proxy_set_header X-Forwarded-Proto https;" in source
    assert "location /api/" in source


def test_deploy_templates_only_probe_and_proxy_v2_runtime_paths() -> None:
    deploy_script = read_text("deploy/deploy.sh")
    assert "/api/v2/system/health" in deploy_script
    assert "/api/v1/health" not in deploy_script
    assert "HEALTH_TIMEOUT_SECONDS=60" in deploy_script
    assert 'seq 1 "$HEALTH_TIMEOUT_SECONDS"' in deploy_script
    assert 'systemctl kill --kill-who=all bitpro-backend' in deploy_script
    assert 'pkill -f "uvicorn app.main:app"' not in deploy_script

    for path in ("deploy/bitpro.nginx", "deploy/setup-server.sh"):
        source = read_text(path)
        assert "location = /api/v2/ws" in source
        assert "location = /api/v1/ws" not in source


def test_data_manager_renders_shell_before_metadata_finishes() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")

    assert "if (loading) {" not in source
    assert "加载数据管理..." in source
    assert "数据管理中心" in source


def test_data_manager_uses_full_width_page_shell() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")

    assert 'className="p-6 h-full min-h-0 overflow-y-auto flex flex-col gap-5"' in source
    assert "max-w-[1400px]" not in source
    assert 'className="p-6 space-y-5 max-w-[1400px] mx-auto"' not in source
