from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_data_sync_client_uses_v2_sync_routes_for_data_page_actions() -> None:
    client = read_text("frontend/src/api/client.ts")
    data_sync_api = client[client.index("export const dataSyncApi = {") :]
    data_assets_api = client[client.index("export const dataAssetsApi = {") : client.index("export const dataSyncApi = {")]

    assert "getReq('/sync/assets'" in data_assets_api
    assert "postReq('/sync/quick-sync'" in data_assets_api
    assert "postReq('/sync/daily-update'" in data_sync_api
    assert "postReq('/sync/delete-data'" in data_sync_api
    assert "postReq('/sync/symbols'" in data_sync_api
    assert "deleteReq('/sync/symbols'" in data_sync_api
    assert "getReq('/sync/jobs'" in data_sync_api
    assert "getReq('/sync/schedule'" in data_sync_api
    assert "putReq('/sync/schedule'" in data_sync_api
    assert "getReq('/sync/quality'" in data_sync_api
    assert "includeItems: false" in data_sync_api
    old_prefix = "/data" + "_sync/"
    assert f"postReq('{old_prefix}daily_update'" not in data_sync_api
    assert f"postReq('{old_prefix}delete'" not in data_sync_api
    assert old_prefix not in data_assets_api


def test_data_manager_exposes_manual_data_quality_check() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    client = read_text("frontend/src/api/client.ts")
    top_section = source[source.index("{/* ========== 统计概览 ========== */") : source.index("{/* ========== 过滤和搜索 ========== */")]

    assert "export interface DataSyncQualityItem" in client
    assert "DataSyncQualityResponse" in client
    assert "getQuality" in client
    assert "qualityItems" in source
    assert "qualitySummary" in source
    assert "runQualityCheck" in source
    assert "dataSyncApi.getQuality({" in source
    assert "数据质量" in top_section
    assert "检测当前列表" in top_section
    assert "质量风险" in source
    assert "qualityMap.get(`${symbol}_${tf}`)" in source
    assert "开盘断层" in source


def test_v2_quick_sync_rejects_global_concurrency() -> None:
    source = read_text("backend/app/api/v2/endpoints/sync.py")
    quick_sync = source[source.index("def _has_running_quick_sync") : source.index('@router.get("/quick-sync/{task_id}")')]

    assert "def _has_running_quick_sync" in quick_sync
    assert "key != exclude_key and bool(info.get(\"running\"))" in quick_sync
    assert "data_sync_service.get_sync_status().get(\"is_running\")" in quick_sync
    assert "_has_running_quick_sync(exclude_key=key)" in quick_sync
    assert 'HTTPException(status_code=409, detail="已有同步任务在运行中，请稍后再试")' in quick_sync
    assert '"duplicate": True' in quick_sync


def test_data_manager_exposes_add_symbol_action_in_filter_row() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    client = read_text("frontend/src/api/client.ts")
    filter_row = source[source.index("{/* ========== 过滤和搜索 ========== */") : source.index("{/* ========== 交易对卡片列表 ========== */")]

    assert "增加交易对" in filter_row
    assert "showAddSymbolDialog" in source
    assert "addSymbolInput" in source
    assert "addSymbolSearch" in source
    assert "availableSymbols" in source
    assert "loadingAvailableSymbols" in source
    assert "handleAddSymbol" in source
    assert "marketApi.getSymbols(selectedExchange, 'USDT', 'spot')" not in source
    assert "marketApi.getSymbols(selectedExchange, 'USDT', 'swap')" in source
    assert "marketType = 'spot'" in client
    assert "marketType }" in client
    assert "dataSyncApi.addSymbol" in source
    assert "normalizeUsdtCandidate" in source
    assert "formatOkxInstrumentId" in source
    assert "addSymbolCandidates" in source
    assert "formatOkxInstrumentId(symbol).toLowerCase().includes(addSymbolSearchText)" in source
    assert "搜索交易对" in source
    assert "可添加交易对" in source
    assert "请先从列表选择交易对" in source
    assert "setConfig((prev)" in source
    assert filter_row.index("增加交易对") < filter_row.index("共 {filteredSymbols.length} 个交易对")


def test_data_manager_exposes_remove_symbol_action_without_deleting_kline_data() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    client = read_text("frontend/src/api/client.ts")
    sync_api = client[client.index("export const dataSyncApi = {") :]
    list_section = source[source.index("{/* ========== 交易对卡片列表 ========== */") : source.index("{/* ========== 说明面板 ========== */")]
    filter_row = source[source.index("{/* ========== 过滤和搜索 ========== */") : source.index("{/* ========== 交易对卡片列表 ========== */")]

    assert "removeSymbol: (data: DataSyncRemoveSymbolRequest)" in sync_api
    assert "deleteReq('/sync/symbols', { data })" in sync_api
    assert "removeSymbolTarget" in source
    assert "showRemoveSymbolDialog" in source
    assert "removeSymbolCandidates" in source
    assert "handleRemoveSymbol" in source
    assert "dataSyncApi.removeSymbol({ symbol })" in source
    assert "setScheduleSymbols((prev) => prev.filter((item) => item !== symbol))" in source
    assert "setSyncDialogSymbols((prev) => prev.filter((item) => item !== symbol))" in source
    assert "移除交易对" in source
    assert "删除交易对" in filter_row
    assert "不会删除已同步的历史 K线数据" in source
    assert "aria-label={`移除 ${coin} 交易对`}" in list_section


def test_data_manager_filter_row_has_spot_swap_switch() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    filter_row = source[source.index("{/* ========== 过滤和搜索 ========== */") : source.index("{/* ========== 交易对卡片列表 ========== */")]

    assert "type DataMarketType = 'swap' | 'spot'" in source
    assert "const [dataMarketType, setDataMarketType] = useState<DataMarketType>('swap')" in source
    assert "data-market-type-toggle" in filter_row
    assert "data-active-market={dataMarketType}" in filter_row
    assert "{ value: 'swap', label: '合约' }" in filter_row
    assert "{ value: 'spot', label: '现货' }" in filter_row
    assert "dataMarketType === 'swap' ? isUsdtSwapSymbol(s) : !isUsdtSwapSymbol(s)" in source
    assert "当前显示" in filter_row


def test_data_manager_sync_controls_are_contract_only_six_timeframes_and_ninety_days() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")

    assert "const SYNC_TIMEFRAME_ORDER = ['15m', '30m', '1h', '4h', '12h', '1d'];" in source
    assert "const SYNC_HISTORY_DAYS = 90;" in source
    assert "setSyncDialogStartDate(dateDaysAgo(SYNC_HISTORY_DAYS));" in source
    assert "setAddSymbolHistoryDays(SYNC_HISTORY_DAYS);" in source
    assert "marketApi.getSymbols(selectedExchange, 'USDT', 'spot')" not in source
    assert "marketApi.getSymbols(selectedExchange, 'USDT', 'swap')" in source


def test_data_manager_symbol_list_includes_synced_and_running_job_symbols() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    schedule_dialog = source[source.index("定时同步设置") : source.index("同步配置 · {syncDialogTitle}")]
    sync_dialog = source[source.index("同步配置 · {syncDialogTitle}") : source.index('title="增加交易对"')]

    assert "function dedupeSymbols" in source
    assert "function splitMarketSymbolCounts" in source
    assert "const configuredSymbols: string[] = config?.defaultSymbols || []" in source
    assert "const syncedSymbols = dedupeSymbols([" in source
    assert "...tableStats" in source
    assert "...syncMeta" in source
    assert "...(syncCurrentJob?.progress || [])" in source
    assert "const allSymbols: string[] = dedupeSymbols([...configuredSymbols, ...syncedSymbols])" in source
    assert "const displayedMarketSymbolCounts = splitMarketSymbolCounts(allSymbols)" in source
    assert "const configuredMarketSymbolCounts = splitMarketSymbolCounts(configuredSymbols)" in source
    assert "const configuredVisibleMarketSymbols = configuredSymbols.filter" in source
    assert "const removeSymbolCandidates = configuredVisibleMarketSymbols.filter" in source
    assert "const configuredSymbol = configuredSymbolSet.has(symbol)" in source
    assert "已同步数据，不在后续同步名单" in source
    assert "自动跟踪全部当前有效的 OKX USDT 永续合约" in schedule_dialog
    assert "SYNC_TIMEFRAME_ORDER.map((tf" in schedule_dialog
    assert "setSyncDialogSymbols(syncDialogSymbols.length === configuredSymbols.length ? [] : [...configuredSymbols])" in sync_dialog
    assert "configuredSymbols.map((sym)" in sync_dialog


def test_data_manager_top_stats_split_spot_and_swap_counts() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    client = read_text("frontend/src/api/client.ts")
    stats_section = source[source.index("{/* ========== 统计概览 ========== */") : source.index("<div className=\"bg-crypto-card border border-crypto-border rounded-xl overflow-hidden shrink-0\">")]

    assert "export interface DataSyncMarketStats" in client
    assert "marketStats: {" in client
    assert "const [marketStats, setMarketStats]" in source
    assert "setMarketStats({" in source
    assert "configuredMarketSymbolCounts" in source
    assert "displayedMarketSymbolCounts" in source
    assert "function DataMarketSplit" in source
    assert "合约" in source[source.index("function DataMarketSplit") : source.index("function formatOkxInstrumentId")]
    assert "现货" in source[source.index("function DataMarketSplit") : source.index("function formatOkxInstrumentId")]
    assert "swap={marketStats.swap.totalRecords}" in stats_section
    assert "spot={marketStats.spot.totalRecords}" in stats_section
    assert "swap={marketStats.swap.totalPairs}" in stats_section
    assert "spot={marketStats.spot.totalPairs}" in stats_section
    assert "swap={displayedMarketSymbolCounts.swap}" in stats_section
    assert "spot={displayedMarketSymbolCounts.spot}" in stats_section


def test_data_manager_add_symbol_only_submits_usdt_swap() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    dialog = source[source.index('title="增加交易对"') :]

    assert "addSymbolSelections" in source
    assert "buildAddSymbolGroups" in source
    assert "toggleAddSymbolSelection" in source
    assert "const symbolsToAdd = addSymbolSelections.filter((symbol) => !configuredSymbolSet.has(symbol))" in source
    assert "for (const symbol of symbolsToAdd)" in source
    assert "await dataSyncApi.addSymbol({ symbol })" in source
    assert "仅添加 OKX USDT 永续合约" in dialog
    assert "现货 + 合约可同时添加" not in dialog
    assert "USDT 永续" in dialog
    assert "添加 {addSymbolSelections.filter((symbol) => !configuredSymbolSet.has(symbol)).length} 个" in source


def test_data_manager_add_symbol_can_start_history_sync_for_new_pairs() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    dialog = source[source.index('title="增加交易对"') :]

    assert "syncAddedSymbolHistory" in source
    assert "addSymbolHistoryDays" in source
    assert "添加后同步历史数据" in dialog
    assert "近3月" in source
    assert "setAddSymbolHistoryDays(SYNC_HISTORY_DAYS)" in source
    assert "if (syncAddedSymbolHistory && isBusy)" in source
    assert "await dataSyncApi.startSync({" in source
    assert "symbols: symbolsToAdd" in source
    assert "timeframes: SYNC_TIMEFRAME_ORDER" in source
    assert "historyDays: addSymbolHistoryDays" in source
    assert "setSyncing(true)" in source


def test_data_manager_global_sync_actions_use_popup_date_dialog() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")

    assert "syncDialogMode" in source
    assert "openSyncDialog('daily')" in source
    assert "openSyncDialog('custom')" in source
    assert "openSyncDialog('full')" in source
    assert "submitSyncDialog" in source
    assert "同步配置" in source
    assert "开始日期" in source
    assert "结束日期" in source
    assert "fixed inset-0 z-[60]" in source
    assert "{showCustomSync && (" not in source


def test_data_manager_uses_single_sync_job_detail_module() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")

    assert "syncCurrentJob" in source
    assert "progressRows" in source
    assert "同步进度明细" not in source
    assert "currentOperationRows" not in source
    assert "renderOperationRow" in source
    assert "操作时间" in source
    assert "同步标的" in source
    assert "数据时间段" in source
    assert "执行时间" in source
    assert "formatDuration" in source
    assert "currentJob.progress" in source
    assert "elapsedSeconds" in source
    assert "{(syncCurrentJob || syncing || isRunning) && (" not in source
    assert "暂无进行中的同步" not in source
    assert "同步任务明细" in source
    assert "当前任务和最近历史任务" in source
    assert "max-h-80 overflow-auto" in source


def test_data_manager_detail_tables_default_collapsed() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")

    assert "const [jobHistoryExpanded, setJobHistoryExpanded] = useState(false)" in source
    assert "progressDetailExpanded" not in source
    assert "{jobHistoryExpanded && (" in source
    assert 'className="flex-1 min-w-0 flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-white/5 transition-colors"' in source
    assert "onClick={() => setJobHistoryExpanded((expanded) => !expanded)}" in source
    assert 'aria-controls="sync-job-history-table"' in source
    assert "{jobHistoryExpanded ? '收起' : '展开'}" in source
    assert 'border-l border-crypto-border' in source


def test_data_manager_detail_sections_do_not_flex_shrink() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")

    assert 'className="p-6 h-full min-h-0 overflow-y-auto flex flex-col gap-5"' in source
    assert 'className="grid grid-cols-6 gap-3 shrink-0"' in source
    assert 'className="bg-crypto-card border border-crypto-border rounded-xl overflow-hidden shrink-0"' in source
    assert 'className="flex items-center gap-3 shrink-0"' in source
    assert 'aria-label="交易对数据列表"' in source


def test_data_manager_symbol_list_uses_bounded_scroll_panel() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    list_section = source[source.index("{/* ========== 交易对卡片列表 ========== */") : source.index("{/* ========== 说明面板 ========== */")]

    assert 'aria-label="交易对维护面板"' in source
    assert "rounded-2xl border border-crypto-border bg-crypto-card/45 p-3" in source
    assert 'aria-label="交易对数据列表"' in list_section
    assert "min-h-[320px] max-h-[52vh] flex flex-col" in list_section
    assert "min-h-0 flex-1 overflow-y-auto p-2.5 pr-3 space-y-2.5" in list_section
    assert "filteredSymbols.length === 0" in list_section
    assert "暂无匹配的交易对" in list_section


def test_data_manager_help_copy_lives_in_top_right_hover_tooltip() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    top_bar = source[source.index("{/* ========== 顶部标题栏 ========== */") : source.index("{/* ========== 统计概览 ========== */")]
    after_list = source[source.index("{/* ========== 说明面板 ========== */") :]

    assert "dataHelpTooltip" in top_bar
    assert 'aria-label="查看数据同步说明"' in top_bar
    assert "group-hover/data-help:opacity-100" in top_bar
    assert "group-focus-within/data-help:opacity-100" in top_bar
    assert "全量同步" in top_bar
    assert "数据覆盖率" in top_bar
    assert "分区存储" in top_bar
    assert "bg-crypto-card border border-crypto-border rounded-xl p-4 shrink-0" not in after_list
    assert '<p><strong className="text-gray-300">全量同步</strong>' not in after_list


def test_data_manager_does_not_render_global_sync_notice() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    submit_handler = source[source.index("const submitSyncDialog = async") : source.index("const handleSyncOne = async")]

    assert "{/* ========== 消息提示 ========== */}" not in source
    assert "{syncMsg && (" not in source
    assert "setSyncMsg" not in source
    assert "已启动:" not in submit_handler


def test_data_manager_renders_sync_job_history_module() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")

    assert "syncJobs" in source
    assert "dataSyncApi.getJobs(20)" in source
    assert "同步任务明细" in source
    assert "当前任务和最近历史任务" in source
    assert "formatJobSymbols" in source
    assert "formatJobTimeframes" in source
    assert "formatJobOperationTime" in source
    assert "progressPercent" in source
    assert "completedItems" in source
    assert "getJobCompletedItems" in source
    assert "getJobProgressPercent" in source


def test_data_manager_initial_shell_not_blocked_by_table_stats() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    load_data = source[source.index("const loadData = useCallback(async () => {") : source.index("useEffect(() => { loadData(); }, []);")]

    assert "const [configRes, statusRes] = await Promise.all([" in load_data
    assert "dataSyncApi.getConfig()" in load_data
    assert "dataSyncApi.getStatus()" in load_data
    assert "dataSyncApi.getTableStats()" not in load_data[load_data.index("const [configRes, statusRes] = await Promise.all([") : load_data.index("setLoading(false)")]
    assert "void loadTableStats()" in load_data
    assert "const loadTableStats = useCallback(async () => {" in source
    assert "const tableStatsLoadingRef = useRef(false)" in source
    assert "if (tableStatsLoadingRef.current) return;" in source


def test_data_manager_sync_detail_tables_use_operation_granularity() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")

    assert "progressRows.map((row) => (" not in source
    assert "currentJobFallback && !currentJobAlreadyInHistory" in source
    assert "expandedJobId" not in source
    assert "job.items || []" not in source
    assert "暂无 item 明细" not in source
    assert "<th className=\"px-4 py-2 text-left font-medium\">交易对</th>" not in source
    assert "<th className=\"px-3 py-2 text-left font-medium\">交易对</th>" not in source
    assert "断点" not in source
    assert "renderOperationRow" in source
    assert "currentOperationRows.map(renderOperationRow)" not in source
    assert "syncJobRows.map(renderOperationRow)" in source


def test_data_manager_sync_job_status_badge_does_not_wrap() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    row_renderer = source[source.index("const renderOperationRow = (job: DataSyncJobSummary)") : source.index("return (", source.index("{/* ========== 顶部标题栏 ========== */"))]

    assert 'className="px-4 py-2 align-top whitespace-nowrap"' in row_renderer
    assert "min-w-[72px]" in row_renderer
    assert "whitespace-nowrap" in row_renderer
    assert "justify-center" in row_renderer
    assert "{syncStatusLabel(job.status)}" in row_renderer
    assert 'className="w-full min-w-[1180px] text-xs"' in source


def test_data_manager_current_operation_uses_same_task_detail_table() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")

    assert "currentJobIsActive" not in source
    assert "currentJob.status === 'syncing' || isRunning" not in source
    assert "currentProgressJob" not in source
    assert "filteredSyncJobs.filter((job) => job.jobId !== currentProgressJob.jobId)" not in source
    assert "const currentOperationRows = currentProgressJob ? [currentProgressJob] : []" not in source
    assert "currentJobFallback && !currentJobAlreadyInHistory" in source
    assert "当前任务和最近历史任务" in source


def test_data_manager_completed_jobs_render_complete_progress() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")

    assert "const processedItems = (job.completedItems || 0) + (job.errorItems || 0)" in source
    assert "if ((job.status === 'completed' || job.status === 'completed_with_errors') && (job.totalItems || 0) > 0)" in source
    assert "return job.totalItems || 0" in source
    assert "if (job.status === 'completed' || job.status === 'completed_with_errors') return 100" in source
    assert "const processedPercent = (((job.completedItems || 0) + (job.errorItems || 0)) / (job.totalItems || 1)) * 100" in source
    assert "const completedItems = getJobCompletedItems(job)" in source
    assert "{completedItems}/{job.totalItems || 0} 项" in source


def test_data_manager_sync_job_history_falls_back_to_current_job() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")

    assert "currentJobFallback" in source
    assert "filteredSyncJobs" in source
    assert "filteredSyncJobs.some((job) => job.jobId === currentJobFallback.jobId)" in source
    assert "[currentJobFallback, ...filteredSyncJobs]" in source
    assert "progressRows.map((row) => row.symbol)" in source
    assert "progressRows.map((row) => row.timeframe)" in source


def test_data_manager_jobs_request_does_not_block_core_status_render() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    load_data = source[source.index("const loadData = useCallback") : source.index("useEffect(() => { loadData();")]

    assert "const [configRes, statusRes] = await Promise.all" in load_data
    assert "dataSyncApi.getJobs(20)" in load_data
    assert "加载同步任务明细失败" in load_data
    assert "dataSyncApi.getTableStats()" not in load_data[load_data.index("const [configRes, statusRes] = await Promise.all") : load_data.index("setLoading(false)")]
    assert "configRes, statusRes, jobsRes" not in load_data


def test_data_manager_global_sync_buttons_track_submitted_mode() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    top_bar = source[source.index("{/* ========== 顶部标题栏 ========== */") : source.index("{/* ========== 统计概览 ========== */")]

    assert "const [syncingMode, setSyncingMode]" in source
    assert "const dailyButtonBusy = syncingMode === 'daily'" in source
    assert "const customButtonBusy = syncingMode === 'custom'" in source
    assert "const fullButtonBusy = syncingMode === 'full'" in source
    assert "{dailyButtonBusy ? <Loader2" in top_bar
    assert "{customButtonBusy ? <Loader2" in top_bar
    assert "{fullButtonBusy ? <Loader2" in top_bar
    assert "{isRunning || syncing ? <Loader2" not in top_bar


def test_data_manager_exposes_configurable_scheduled_sync_action() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    top_bar = source[source.index("{/* ========== 顶部标题栏 ========== */") : source.index("{/* ========== 统计概览 ========== */")]

    assert "定时同步" in top_bar
    assert "schedulePulseOn" in source
    assert "animate-ping" in top_bar
    assert "showScheduleDialog" in source
    assert "openScheduleDialog" in source
    assert "submitScheduleDialog" in source
    assert "dataSyncApi.getSchedule" in source
    assert "dataSyncApi.updateSchedule" in source
    assert "同步间隔" in source
    assert "同步粒度" in source
    assert "scheduleIntervalMinutes" in source
    assert "scheduleTimeframes" in source
    assert "formatDateTime(scheduleConfig?.nextRunAt)" in source
    assert "bg-purple-600/80 hover:bg-purple-500 text-white" in top_bar


def test_data_manager_single_sync_has_visible_target_feedback() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")
    handler = source[source.index("const handleSyncOne = async") : source.index("const openAddSymbolDialog")]

    assert "syncingTarget" in source
    assert "setSyncingTarget({ symbol, timeframe })" in source
    assert "await dataSyncApi.startSync({" in handler
    assert "symbols: [symbol]" in handler
    assert "timeframes: [timeframe]" in handler
    assert "startDate: startDate" in handler
    assert "endDate: endDate" in handler
    assert "setSyncing(true)" in handler
    assert "setJobHistoryExpanded(true)" in handler
    assert "setTimeout(loadData, 1000)" in handler
    assert "dataSyncApi.syncOne" not in handler
    assert "const isSyncingTarget =" in source
    assert "targetSyncFeedback" in source
    assert "setTargetSyncFeedback" in source
    assert "getSyncTargetKey(symbol, tf)" in source
    assert "targetFeedback.message" in source
    assert "正在同步" in source
    assert "animate-spin" in source
    assert "showMsg(" not in handler


def test_data_manager_missing_timeframes_submits_one_background_job() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")

    assert "handleSyncMissingTimeframes" in source
    assert "timeframes: missingTimeframes" in source
    assert "allTimeframes.forEach((tf: string) => { if (!statMap.get(`${symbol}_${tf}`)?.recordCount) handleSyncOne(symbol, tf); });" not in source


def test_data_manager_supports_30m_timeframe_when_synced_metadata_contains_it() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")

    assert "'30m': '30M'" in source
    assert "'30m': 'from-indigo-500/20 to-indigo-600/5 border-indigo-500/30'" in source
    assert "const TIMEFRAME_ORDER = ['1m', '5m', '15m', '30m', '1h', '4h', '12h', '1d']" in source
    assert "function sortTimeframes" in source
    assert "const discoveredTimeframes = sortTimeframes(dedupeSymbols([" in source
    assert "...tableStats.map((s) => s.timeframe)" in source
    assert "...syncMeta.map((m) => m.timeframe)" in source
    assert "...(syncCurrentJob?.progress || []).map((row) => row.timeframe)" in source
    assert "const allTimeframes = discoveredTimeframes.length > 0 ? discoveredTimeframes : TIMEFRAME_ORDER" in source
