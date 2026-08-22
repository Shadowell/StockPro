from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _read_ai_lab_modules() -> str:
    return "\n".join(
        _read(path)
        for path in (
            "frontend/src/pages/AILab.tsx",
            "frontend/src/pages/aiLab/aiLabSupport.tsx",
            "frontend/src/pages/aiLab/AutoAgentPanel.tsx",
            "frontend/src/pages/aiLab/OrbitPostPanel.tsx",
        )
    )


def test_ai_lab_exposes_auto_trading_agent_workspace():
    source = _read_ai_lab_modules()

    assert "type AssistantTab = 'research' | 'optimizer' | 'autonomous' | 'auto-agent' | 'orbit-post';" in source
    assert "? tabParam : 'auto-agent'" in source
    first_tab_index = source.index("switchTab('auto-agent')")
    autonomous_tab_index = source.index("switchTab('autonomous')")
    research_tab_index = source.index("switchTab('research')")
    assert first_tab_index < autonomous_tab_index
    assert autonomous_tab_index < research_tab_index
    assert "自动交易Agent" in source
    assert "自动交易 Agent 决策驾驶舱" in source
    assert "结论、操作和证据压缩到首屏" in source
    assert "Market Agent" in source
    assert "Strategy Agent" in source
    assert "Risk Agent" in source
    assert "Execution Agent" in source
    assert "Review Agent" in source
    assert "/agent/strategy-assistant/research-runs" in source
    assert "AUTO_AGENT_RUN_STORAGE_KEY" in source
    assert "auto_collect_market: true" in source
    assert "use_hermes_agent: true" in source
    assert "preferred_direction: 'auto'" in source
    assert "立即开始研发" in source
    assert "查看最近结果" in source
    assert "定时执行" in source
    assert "自动交易Agent定时执行" in source
    assert "保存并开启定时" in source
    assert "立即按定时配置执行一次" in source
    assert "/agent/strategy-assistant/scheduler" in source
    assert "/agent/strategy-assistant/scheduler/run-now" in source
    assert "服务重启后会自动续跑" in source
    assert "paper/simulation only" in source
    assert "closed_loop" in source
    assert "候选策略" in source
    assert "回测 / 闭环状态" in source
    assert "回测 / 晋级门槛" in source
    assert "实盘需人工审批" in source
    assert "本轮结论" in source
    assert "下一步操作" in source
    assert "候选拒绝原因" in source
    assert "Hermes 研究摘要" in source
    assert "Hermes / Codex" in source
    assert "trade_direction: autonomousConfig.tradeDirection" in source
    assert "llm_provider: autonomousConfig.llmProvider" in source
    assert "Top30" in source
    assert "多空双向" in source
    assert "原始结果（调试用）" in source
    assert "无通过候选，未进入回测矩阵" in source
    assert "这是风控结果，不是错误" in source
    assert "机会分" in source
    assert "EMA gap" in source


def test_instance_monitor_loads_echarts_after_detail_shell_renders():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")

    assert "import * as echarts from 'echarts'" not in source
    assert 'import("echarts")' in source or "import('echarts')" in source
    assert "const [echartsLib, setEchartsLib]" in source


def test_paper_instance_detail_hides_redundant_trade_mode_badge():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")

    assert "{!runningDryRun && (" in source
    assert "{runningDryRun ? '模拟盘' : '实盘'}" not in source
    assert "bg-red-500/20 text-red-400" in source


def test_live_page_preloads_instance_monitor_chunk():
    source = _read("frontend/src/pages/liveTrading/index.tsx")

    assert "const loadInstanceMonitor" in source
    assert "const InstanceMonitor = lazy(loadInstanceMonitor)" in source
    assert "void loadInstanceMonitor();" in source


def test_live_page_preloads_trade_kline_chart_chunk_with_instance_monitor():
    source = _read("frontend/src/pages/liveTrading/index.tsx")

    assert "let watchKlineChartPromise: Promise<typeof import('../../components/WatchKlineChart')> | null = null;" in source
    assert "const preloadWatchKlineChart = () =>" in source
    assert "watchKlineChartPromise = import('../../components/WatchKlineChart');" in source
    loader = source[source.index("const loadInstanceMonitor"):source.index("const InstanceMonitor")]
    assert "void preloadWatchKlineChart();" in loader


def test_detail_view_does_not_poll_dashboard_card_metrics():
    source = _read("frontend/src/pages/liveTrading/index.tsx")

    assert "if (view !== 'dashboard') return;" in source
    assert "metricRefreshSignature" in source
    assert "}, [metricRefreshSignature, view]);" in source


def test_live_detail_trade_refresh_normalizes_wrapped_responses_and_preserves_rows():
    source = _read("frontend/src/pages/liveTrading/index.tsx")

    assert "function normalizeStrategyTradesResponse(payload: unknown): any[]" in source
    assert "record.data" in source
    assert "record.trades" in source
    assert "record.items" in source
    assert "record.results" in source
    assert source.count("normalizeStrategyTradesResponse(") >= 3
    assert "function dashboardHasRecordedTrades(dashboard: unknown): boolean" in source
    assert "dashboardHasRecordedTrades(dash)" in source
    assert "catch (err) {" in source[source.index("const tr = await liveApi.getStrategyTrades"):]
    assert "if (!cancelled && !dashboardHasRecordedTrades(dash)) setTrades([]);" in source
    assert "const latestTrades = normalizeStrategyTradesResponse(" in source


def test_instance_monitor_prefers_backend_position_unrealized_pnl():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")

    assert "const explicitUnrealizedPnl = Number(row.unrealizedPnl);" in source
    assert "Number.isFinite(explicitUnrealizedPnl)" in source
    assert "? explicitUnrealizedPnl" in source


def test_instance_monitor_total_pnl_uses_usd_symbol():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")

    assert "function formatSignedUsd(value: number): string" in source
    assert "function formatUsd(value: unknown): string" in source
    assert "minimumFractionDigits: 2" in source
    assert "maximumFractionDigits: 2" in source
    assert 'label="总盈亏"' in source
    assert 'label="账户总额"' in source
    assert "value={formatUsd(displayEquityAmount)}" in source
    assert "value={formatSignedUsd(totalPnlAmount)}" in source
    assert "equity?.current ?? initialConfig.initialEquity).toLocaleString()" not in source
    assert "totalPnlAmount.toFixed(2)} USDT" not in source


def test_instance_monitor_labels_quantity_for_spot_and_contract_rows():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")
    metrics_source = _read("frontend/src/utils/tradeMetrics.ts")

    assert "export function isContractPosition" in metrics_source
    assert "const positionQuantityLabel = '张数/数量';" in source
    assert "const tradeQuantityLabel = '张数/数量';" in source
    assert "isContractTradeSide(trade.side) || String(trade.symbol ?? '').includes(':')" in source
    assert "{positionQuantityLabel}" in source
    assert "{tradeQuantityLabel}" in source


def test_instance_monitor_positions_and_activity_stack_as_default_open_collapsible_sections():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")

    assert "const [positionsSectionOpen, setPositionsSectionOpen] = useState(true);" in source
    assert "const [activitySectionOpen, setActivitySectionOpen] = useState(true);" in source
    assert "setPositionsSectionOpen(true);" in source
    assert "setActivitySectionOpen(true);" in source
    assert "aria-expanded={positionsSectionOpen}" in source
    assert "aria-expanded={activitySectionOpen}" in source
    assert "positionsSectionOpen &&" in source
    assert "activitySectionOpen &&" in source
    assert "成交与事件" in source
    assert "const ACTIVITY_PANEL_MAX_HEIGHT_CLASS = 'max-h-[372px]';" in source
    assert "const toggleActivitySection = useCallback(() => {" in source
    assert "const handleActivitySectionKeyDown = useCallback(" in source
    assert "onClick={toggleActivitySection}" in source
    assert "onKeyDown={handleActivitySectionKeyDown}" in source

    stack_start = source.index('className="grid grid-cols-1 gap-5"')
    stack_end = source.index('aria-expanded={simulationReviewSectionOpen}', stack_start)
    stack_section = source[stack_start:stack_end]
    assert "lg:grid-cols-2" not in stack_section
    assert "lg:min-h-[280px]" not in stack_section
    assert "max-h-[min(520px,54vh)]" not in stack_section
    assert "onClick={(event) => event.stopPropagation()}" in stack_section
    assert "onKeyDown={(event) => event.stopPropagation()}" in stack_section
    assert stack_section.index("当前持仓") < stack_section.index("成交明细")


def test_instance_monitor_risk_status_uses_description_blocks_instead_of_metric_tiles():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")

    top_metric = source[source.index('label="账户总额"'):source.index('label="运行时间"')]
    risk_panel = source[source.index('aria-label="风控说明块"'):]

    labels = ['label="收益率"', 'label="夏普"', 'label="胜率"', 'label="盈亏比"', 'label="交易次数"', 'label="30日最大回撤"']
    assert [top_metric.index(label) for label in labels] == sorted(
        top_metric.index(label) for label in labels
    )
    assert "value={formatSharpe(perf?.sharpeRatio)}" in top_metric
    assert "displayRiskMetrics.maxDrawdownPct.toFixed(1)" in top_metric
    assert "riskDescriptionItems" in source
    assert "const [riskSectionOpen, setRiskSectionOpen] = useState(true);" in source
    assert "setRiskSectionOpen(true);" in source
    assert "aria-expanded={riskSectionOpen}" in source
    assert "onClick={() => setRiskSectionOpen((value) => !value)}" in source
    assert "riskSectionOpen &&" in source
    assert "熔断保护" in source
    assert "回撤与亏损监控" in source
    assert "仓位边界" in source
    assert "通知与审计" in risk_panel
    assert "风控说明块" in risk_panel
    assert "displayRiskMetrics.maxDrawdownPct.toFixed(2)" in source
    assert "30日最大回撤" in source
    assert "status: `最大回撤 ${displayRiskMetrics.maxDrawdownPct.toFixed(2)}%`" not in source
    assert "displayRiskMetrics.dailyLossPct.toFixed(2)" in source
    assert "displayRiskMetrics.currentDrawdownPct.toFixed(2)" not in risk_panel
    assert "熔断状态" not in source
    assert "熔断状态" not in risk_panel
    assert "今日亏损" not in risk_panel
    assert '<div className="text-[10px] text-gray-500 mb-1">飞书</div>' not in risk_panel


def test_instance_monitor_primary_section_titles_share_logic_summary_font_size():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")
    dynamic_pool_source = _read("frontend/src/pages/liveTrading/DynamicPoolPanel.tsx")

    expected_titles = ["当前持仓", "成交与事件", "风控状态"]
    for title in expected_titles:
        title_index = source.index(f">{title}<")
        title_tag = source[source.rfind("<", 0, title_index):source.index(">", title_index) + 1]
        assert "text-base" in title_tag
        assert "text-sm" not in title_tag

    assert 'className="flex-1 min-w-0 flex items-center gap-2 px-4 py-3 text-left text-base font-semibold' in source
    assert '<h3 className="truncate text-base font-semibold text-white">动态标的池</h3>' in dynamic_pool_source


def test_dynamic_pool_panel_only_renders_the_unified_presentation_contract():
    source = _read("frontend/src/pages/liveTrading/DynamicPoolPanel.tsx")
    types = _read("frontend/src/pages/liveTrading/types.ts")

    assert "factorMode" not in source
    assert "ema_factor_adaptive" not in source
    assert "primaryMetric" in source
    assert ".badges" in source
    assert ".metrics" in source
    assert "pool.summary" in source
    assert "pool?.counts" in source
    assert "candidatesNear" not in source
    assert "momentumPct" not in source
    assert "scoreEnterMin" not in source
    assert "primaryMetric: DynamicPoolDisplayMetric" in types
    assert "candidates: DynamicPoolDisplayRow[]" in types
    assert "members: DynamicPoolDisplayRow[]" in types


def test_dynamic_pool_panel_uses_backend_event_copy_without_kind_switch():
    source = _read("frontend/src/pages/liveTrading/DynamicPoolPanel.tsx")
    types = _read("frontend/src/pages/liveTrading/types.ts")

    assert "event.message" in source
    assert "event.label" in source
    assert "event.tone" in source
    assert "switch (event.kind)" not in source
    assert "EVENT_META" not in source
    assert "position_open" not in source
    assert "ratchet_breach" not in source
    assert "message: string" in types
    assert "label: string" in types
    assert "tone?: DynamicPoolTone" in types


def test_instance_monitor_account_curve_uses_compact_okx_style_controls():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")

    assert "const EQUITY_RANGE_OPTIONS" in source
    assert "const [equityRange, setEquityRange] = useState<EquityRange>('1D');" in source
    assert "type EquityMetric = 'returnPct' | 'totalPnl' | 'winRate' | 'profitFactor';" in source
    assert "const [equityMetric, setEquityMetric] = useState<EquityMetric>('returnPct');" in source
    assert "收益率" in source
    assert "收益" in source
    assert "胜率" in source
    assert "盈亏比" in source
    assert "账户权益" not in source
    assert "显示回撤" not in source
    assert "按当前时间范围展示策略收益率、收益、胜率和盈亏比采样。" in source
    assert "legend:" not in source[source.index("chart.setOption({"):source.index("tooltip:")]
    assert "const selectedMetric = EQUITY_METRIC_OPTIONS.find((item) => item.value === equityMetric)" in source
    assert "function metricValueForEquityRow" in source
    assert "row.totalPnl" in source
    assert "row.winRate" in source
    assert "row.profitFactor" in source
    assert "const chartSeries = [primarySeries]" in source
    assert "const rangeWindow =" in source
    assert "const rangeAxisWindow =" in source
    assert "...rangeAxisWindow" in source
    assert "chart.setOption(" in source
    assert "{ notMerge: true }" in source
    assert "showEquityDrawdown ? drawdownData : []" not in source


def test_instance_monitor_does_not_normalize_missing_curve_metrics_to_zero():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")
    helper = source[
        source.index("function finiteOptionalNumber"):
        source.index("function normalizeEquityRows")
    ]

    assert "value == null || value === ''" in helper


def test_instance_monitor_account_curve_uses_compact_okx_style_controls():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")

    assert "const EQUITY_RANGE_OPTIONS" in source
    assert "const [equityRange, setEquityRange] = useState<EquityRange>('1D');" in source
    assert "type EquityMetric = 'returnPct' | 'totalPnl' | 'winRate' | 'profitFactor';" in source
    assert "const [equityMetric, setEquityMetric] = useState<EquityMetric>('returnPct');" in source
    assert "收益率" in source
    assert "收益" in source
    assert "胜率" in source
    assert "盈亏比" in source
    assert "账户权益" not in source
    assert "显示回撤" not in source
    assert "按当前时间范围展示策略收益率、收益、胜率和盈亏比采样。" in source
    assert "legend:" not in source[source.index("chart.setOption({"):source.index("tooltip:")]
    assert "const selectedMetric = EQUITY_METRIC_OPTIONS.find((item) => item.value === equityMetric)" in source
    assert "function metricValueForEquityRow" in source
    assert "row.totalPnl" in source
    assert "row.winRate" in source
    assert "row.profitFactor" in source
    assert "const chartSeries = [primarySeries]" in source
    assert "const rangeWindow =" in source
    assert "const rangeAxisWindow =" in source
    assert "...rangeAxisWindow" in source
    assert "chart.setOption(" in source
    assert "{ notMerge: true }" in source
    assert "showEquityDrawdown ? drawdownData : []" not in source


def test_instance_monitor_account_curve_adds_trade_kline_review():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")
    kline = _read("frontend/src/components/WatchKlineChart.tsx")
    compact_source = " ".join(source.split())

    assert "const WatchKlineChart = lazy(() => import('../../components/WatchKlineChart'));" in source
    assert "type WatchTradeMarker" in source
    assert "function buildSimulationTradeMarkers" in source
    assert "const simulationReviewSymbols" in source
    assert "const [selectedSimulationReviewSymbol, setSelectedSimulationReviewSymbol]" in source
    assert "marketApi.getKlines(" in source
    assert "simulationReviewTimeframe" in source
    assert "function compactKlineTimeframeLabel" in source
    assert "const simulationReviewTimeframeLabel" in source
    assert "setSimulationReviewKlines" in source
    assert "买卖点 K线复盘" in source
    assert "CryptoSelect" in source
    assert "selectedSimulationReviewSymbol" in source
    assert "markers={simulationReviewMarkers}" in source
    assert "timeframe={simulationReviewTimeframe}" in source
    assert "const simulationReviewMarkerTimestampKey = useMemo(" in source
    assert "simulationReviewMarkers .map((marker) => Number(marker.timestamp))" in compact_source
    assert "simulationReviewMarkerTimestampKey .split(',')" in compact_source
    assert "return `{main|${markerLabel}}`;" in kline
    assert "return `{main|${markerLabel}}\\n" not in kline
    assert "value: marker.label,\n          actionText," not in kline
    review_effect = source[
        source.index("if (!simulationReviewEnabled || !selectedSimulationReviewSymbol)"):
        source.index("if (!equitySectionOpen", source.index("if (!simulationReviewEnabled"))
    ]
    assert "simulationReviewMarkers," not in review_effect
    assert "simulationReviewMarkerTimestampKey," in review_effect
    assert "B/S 成交点" in source
    assert "const [simulationReviewSectionOpen, setSimulationReviewSectionOpen] = useState(true);" in source
    assert "const [equitySectionOpen, setEquitySectionOpen] = useState(true);" in source
    assert "setSimulationReviewSectionOpen(true);" in source
    assert "setEquitySectionOpen(true);" in source
    assert "aria-expanded={simulationReviewSectionOpen}" in source
    assert "aria-expanded={equitySectionOpen}" in source
    assert "onClick={() => setSimulationReviewSectionOpen((value) => !value)}" in source
    assert "onClick={() => setEquitySectionOpen((value) => !value)}" in source
    kline_card_start = source.index('aria-expanded={simulationReviewSectionOpen}')
    kline_card_end = source.index('aria-expanded={equitySectionOpen}', kline_card_start)
    equity_card_end = source.index("{risk && (", kline_card_end)
    kline_card = source[kline_card_start:kline_card_end]
    equity_card = source[kline_card_end:equity_card_end]
    assert "买卖点 K线复盘" in kline_card
    assert "收益曲线" not in kline_card
    assert "aria-label={`K线周期 ${simulationReviewTimeframeLabel}`}" in kline_card
    assert "aria-label={`复盘标的 ${selectedSimulationReviewSymbol}`}" in kline_card
    assert "{selectedSimulationReviewSymbol}" in kline_card
    assert "{simulationReviewTimeframeLabel}" in kline_card
    assert "flex rounded-xl border border-crypto-border bg-crypto-bg p-1" in kline_card
    assert "bg-blue-600/25 px-3 text-xs font-semibold text-blue-200" in kline_card
    assert "rounded-full border border-crypto-border bg-crypto-bg px-2.5 py-1" not in kline_card
    assert "收益曲线" in equity_card
    assert "账户曲线" not in equity_card
    assert "买卖点 K线复盘" not in equity_card


def test_instance_monitor_profit_curve_uses_red_return_line():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")
    live_page = _read("frontend/src/pages/liveTrading/index.tsx")

    assert "color: '#FF1744', fillColor: 'rgba(255,23,68,0.16)'" in source
    assert "color: '#22c55e', fillColor: 'rgba(34,197,94,0.16)'" not in source
    assert "账户曲线" not in live_page
    assert "收益曲线" in live_page


def test_instance_monitor_review_symbols_prefer_runtime_symbols_over_config_defaults():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")
    helper = source[
        source.index("function collectSimulationReviewSymbols"):
        source.index("function getStrategyLogicSummary")
    ]

    assert "const runtimeSymbols = new Set<string>();" in helper
    assert "dashboard?.positions?.forEach" in helper
    assert "runtimeSymbols.add(symbol);" in helper
    assert "if (runtimeSymbols.size > 0) return Array.from(runtimeSymbols);" in helper
    assert "const fallbackSymbols = new Set<string>();" in helper
    assert "fallbackSymbols.add(text);" in helper


def test_instance_monitor_position_rows_have_15m_market_hover_preview():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")

    assert "POSITION_PREVIEW_TIMEFRAME = '15m'" in source
    assert "POSITION_PREVIEW_LIMIT = 72" in source
    assert "marketApi.getKlines(" in source
    assert "POSITION_PREVIEW_TIMEFRAME," in source
    assert "PositionMarketPreview" in source
    assert "function buildMiniKlineCandles" in source
    assert "positionPreviewAnchor.pinned" in source
    assert "aria-label=\"关闭行情预览\"" in source
    assert "aria-label={`查看 ${row.symbol} ${POSITION_PREVIEW_TIMEFRAME_LABEL} 行情`}" in source
    assert "onMouseEnter={(event) => openPositionPreview(row.symbol, event.currentTarget)}" in source
    assert "onClick={(event) => togglePinnedPositionPreview(row.symbol, event.currentTarget, event)}" in source
    assert "onFocus={(event) => openPositionPreview(row.symbol, event.currentTarget)}" in source
    assert 'title={`${POSITION_PREVIEW_TIMEFRAME} 行情`}' not in source
    assert "pointer-events-auto" in source
    assert "pointer-events-none" in source
    assert "positionPreviewInFlightRef" in source
    assert "let shouldFetch = false" not in source
    assert "shouldFetch = true" not in source


def test_instance_monitor_position_rows_have_paper_close_action():
    source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")
    live_page_source = _read("frontend/src/pages/liveTrading/index.tsx")
    client_source = _read("frontend/src/api/client.ts")

    assert "onClosePosition?:" in source
    assert "closePositionTarget" in source
    assert "平仓当前模拟持仓" in source
    assert "aria-label={`平仓 ${row.symbol}`}" in source
    assert "onClosePosition?.({" in source
    assert "marketType: isContractPosition(row) ? 'swap' : 'spot'" in source
    assert "response?.data?.error?.message" in source
    assert "closePaperPosition:" in client_source
    assert "postReq('/live/positions/close', payload)" in client_source
    assert "handleClosePaperPosition" in live_page_source
    assert "liveApi.closePaperPosition" in live_page_source
    assert "onClosePosition={handleClosePaperPosition}" in live_page_source


def test_api_client_promotes_error_envelope_message_to_detail():
    client_source = _read("frontend/src/api/client.ts")

    assert "error.detail ?? error.message ?? error.code ?? record.error" in client_source
    assert "(error.response.data as Record<string, unknown>).detail = detail;" in client_source


def test_instance_monitor_stop_action_copy_uses_close_trading():
    monitor_source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")
    live_page_source = _read("frontend/src/pages/liveTrading/index.tsx")

    assert "关闭交易" in monitor_source
    assert "停止交易" not in monitor_source
    assert 'title="关闭交易"' in live_page_source
    assert 'confirmText="关闭"' in live_page_source
    assert 'title="停止交易"' not in live_page_source


def test_simulation_detail_renders_strategy_logic_below_metrics():
    monitor_source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")
    live_page_source = _read("frontend/src/pages/liveTrading/index.tsx")

    assert "strategyInfo?: StrategyInfo | null;" in monitor_source
    assert "function getStrategyLogicSummary" in monitor_source
    assert "selectionLogic" in monitor_source
    assert "tradingLogic" in monitor_source
    assert "核心标的与交易逻辑" in monitor_source
    assert "核心标的" in monitor_source
    assert "核心选股" not in monitor_source
    assert "交易逻辑" in monitor_source
    assert "StrategyParameterSections" in monitor_source
    assert "getStrategyParameterSections" in monitor_source
    assert "const [logicSummaryOpen, setLogicSummaryOpen] = useState(false);" in monitor_source
    assert "aria-expanded={logicSummaryOpen}" in monitor_source
    assert "{logicSummaryOpen && (" in monitor_source
    assert "策略参数配置" in _read("frontend/src/components/StrategyParameterSections.tsx")
    assert "交易逻辑参数配置" in _read("frontend/src/components/StrategyParameterSections.tsx")
    assert "风控参数配置" in _read("frontend/src/components/StrategyParameterSections.tsx")

    metrics_index = monitor_source.index('label="运行时间"')
    logic_index = monitor_source.index("核心标的与交易逻辑")
    diagnostics_index = monitor_source.index("策略运行诊断日志")
    parameter_index = monitor_source.index("<StrategyParameterSections")
    assert metrics_index < logic_index < parameter_index < diagnostics_index

    assert "const selectedRuntimeStrategy" in live_page_source
    assert "strategyInfo={selectedRuntimeStrategy}" in live_page_source


def test_strategy_diagnostic_log_defaults_collapsed():
    monitor_source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")

    assert "const [strategyDiagOpen, setStrategyDiagOpen] = useState(false);" in monitor_source
    assert "const [strategyDiagOpen, setStrategyDiagOpen] = useState(true);" not in monitor_source


def test_strategy_and_pool_event_logs_prefix_timestamp_on_one_line():
    monitor_source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")
    pool_source = _read("frontend/src/pages/liveTrading/DynamicPoolPanel.tsx")

    log_row = monitor_source[
        monitor_source.index("entry.kind === 'log'"):
        monitor_source.index(") : (", monitor_source.index("entry.kind === 'log'"))
    ]
    assert 'className="flex min-w-max items-center gap-2 whitespace-nowrap"' in log_row
    assert log_row.index("formatLogTime(entry.ts)") < log_row.index("{entry.level}") < log_row.index("{entry.text}")
    assert "whitespace-pre-wrap" not in log_row

    diag_row_start = monitor_source.index(") : (", monitor_source.index("entry.kind === 'log'"))
    diag_row_end = monitor_source.index("</div>\n                    )}", diag_row_start)
    diag_row = monitor_source[diag_row_start:diag_row_end]
    assert 'className="flex min-w-max items-center gap-2 whitespace-nowrap text-gray-400"' in diag_row
    assert diag_row.index("formatLogTime(") < diag_row.index("entry.raw.decision_label")

    event_row = pool_source[
        pool_source.index("events.map((event)"):
        pool_source.index("</motion.li>", pool_source.index("events.map((event)"))
    ]
    assert "formatEventTimestamp(event.ts)" in event_row
    assert event_row.index("formatEventTimestamp(event.ts)") < event_row.index("{event.label}") < event_row.index("{event.message}")
    assert "whitespace-nowrap" in event_row
    assert 'overflow-auto border-t border-crypto-border' in pool_source


def test_strategy_diagnostic_log_uses_backend_event_id_for_polling_deduplication():
    monitor_source = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")

    assert "evt.event_id ? `event-log-${String(evt.event_id)}`" in monitor_source
    assert "`event-log-${ts}-${idx}`" in monitor_source


def test_ai_lab_monitor_link_opens_strategy_detail_and_live_accepts_legacy_alias():
    ai_lab_source = _read_ai_lab_modules()
    live_page_source = _read("frontend/src/pages/liveTrading/index.tsx")
    route_effect = live_page_source[
        live_page_source.index("从策略中心等处跳转"):
        live_page_source.index("const loadPaperInstances")
    ]

    assert "href={`/live?strategyId=${item.strategy_id}`}" in ai_lab_source
    assert "href={`/live?instance_id=${item.strategy_id}`}" not in ai_lab_source
    assert "searchParams.get('strategyId')" in live_page_source
    assert "searchParams.get('strategy_id')" in live_page_source
    assert "searchParams.get('instance_id')" in live_page_source
    assert "searchParams.get('instanceId')" in live_page_source
    assert "const requestedMode = searchParams.get('mode')" in live_page_source
    assert "setSelectedStrategy(sid)" in live_page_source
    assert "deleteStrategyIdSearchParams(next)" not in route_effect


def test_ai_lab_autonomous_instances_have_delete_action():
    ai_lab_source = _read_ai_lab_modules()

    assert "const [autonomousDeleteTarget" in ai_lab_source
    assert "api.delete(`/agent/autonomous-trader/${strategyId}`)" in ai_lab_source
    assert "删除 AI自主交易实例" in ai_lab_source
    assert "setAutonomousDeleteTarget(item)" in ai_lab_source


def test_ai_lab_autonomous_instances_pause_resume_instead_of_stop_primary_action():
    ai_lab_source = _read_ai_lab_modules()

    assert "handlePauseAutonomousTrader" in ai_lab_source
    assert "api.post(`/agent/autonomous-trader/${strategyId}/pause`" in ai_lab_source
    assert "handleResumeAutonomousTrader" in ai_lab_source
    assert "api.post(`/agent/autonomous-trader/${strategyId}/resume`" in ai_lab_source
    assert "AI自主交易模拟盘已暂停，指标已保留，可继续运行" in ai_lab_source
    assert "itemStatus === 'running'" in ai_lab_source
    assert "['paused', 'stopped'].includes(itemStatus)" in ai_lab_source
    assert "'暂停中...'" in ai_lab_source
    assert "'继续中...'" in ai_lab_source


def test_ai_lab_autonomous_tab_uses_workbench_layout():
    ai_lab_source = _read_ai_lab_modules()

    assert "AI自主交易控制台" in ai_lab_source
    assert "实例操作台" in ai_lab_source
    assert "bg-yellow-950/45" in ai_lab_source
    assert "bg-blue-950/45" in ai_lab_source
    assert "bg-emerald-950/45" in ai_lab_source
    assert "最新日志" in ai_lab_source
    assert "const [selectedAutonomousId" in ai_lab_source
    assert "setSelectedAutonomousId(item.strategy_id)" in ai_lab_source
    assert "selectedAutonomousLogs" in ai_lab_source
    assert "autonomousLogsOpen" in ai_lab_source
    assert "{selected && (" in ai_lab_source
    assert "配置参数" in ai_lab_source
    assert "autonomousInstanceConfigItems(item.config)" in ai_lab_source
    assert "max_leverage_cap" in ai_lab_source
    assert "aria-expanded={autonomousLogsOpen}" in ai_lab_source
    assert "normalizeAutonomousNumericInput" in ai_lab_source
    assert "autonomousNumberDrafts" in ai_lab_source
    assert 'inputMode="decimal"' in ai_lab_source
    assert "AI模型" in ai_lab_source
    assert "autonomousModelOptions" in ai_lab_source
    assert "free_tier_models" in ai_lab_source
    assert "免费额度耗尽时会自动尝试下一个免费候选" in ai_lab_source
    assert "api.get('/settings/llm-model')" in ai_lab_source
    assert "api.get('/agent/model-config')" not in ai_lab_source
    assert "llm_model: selectedAutonomousModel" in ai_lab_source
    assert "const [researchModel" in ai_lab_source
    assert "const [optimizerModel" in ai_lab_source
    assert "selectedResearchModel" in ai_lab_source
    assert "selectedOptimizerModel" in ai_lab_source
    assert "llm_model: selectedResearchModel" in ai_lab_source
    assert "llm_model: selectedOptimizerModel" in ai_lab_source
    assert "Planner、策略生成、合约审查和评估都会使用该模型" in ai_lab_source
    assert "打开监控查看完整 AI 决策、成交和指标" in ai_lab_source
    assert "selectedAutonomousEvents" not in ai_lab_source
    assert "selectedAutonomousTrades" not in ai_lab_source


def test_ai_lab_autonomous_start_params_own_launch_prompt_and_symbol_limit():
    ai_lab_source = _read_ai_lab_modules()

    assert "promptText: string;" in ai_lab_source
    assert "restrictSymbols: boolean;" in ai_lab_source
    assert "提示词" in ai_lab_source
    assert "合约标的池" in ai_lab_source
    assert "限制标的" in ai_lab_source
    assert "checked={autonomousConfig.restrictSymbols}" in ai_lab_source
    assert "disabled={!autonomousConfig.restrictSymbols}" in ai_lab_source
    assert "operator_prompt: autonomousConfig.promptText.trim()" in ai_lab_source
    assert "restrict_symbols: autonomousConfig.restrictSymbols" in ai_lab_source
    assert "symbols: autonomousConfig.restrictSymbols ? symbols : []" in ai_lab_source
    assert "maxLeverageCap: 10" in ai_lab_source
    assert "maxSinglePositionPct: 60" in ai_lab_source
    assert "maxTotalExposurePct: 360" in ai_lab_source
    assert "maxPositions: 6" in ai_lab_source
    assert "最多持仓" in ai_lab_source
    assert "1-10x 杠杆" in ai_lab_source
    assert "通过 Hermes 调用 Codex" in ai_lab_source
    assert "只做 OKX USDT 永续合约模拟盘" in ai_lab_source
    assert "禁止实盘" in ai_lab_source
    assert "open_long/open_short" in ai_lab_source
    assert "小仓位试单" in ai_lab_source
    assert "5-10x" in ai_lab_source
    assert "AI 自主决定杠杆" in ai_lab_source
    assert "仓位比例" in ai_lab_source
    assert "1-3x" not in ai_lab_source
    assert "强弱分化" in ai_lab_source
    assert "提升模拟盘净收益" in ai_lab_source
    assert "最小开仓名义 50U" in ai_lab_source
    assert "if (autonomousConfig.restrictSymbols && !symbols.length)" in ai_lab_source

    params_pos = ai_lab_source.index("启动参数")
    launch_pos = ai_lab_source.index("启动新实例")
    instances_pos = ai_lab_source.index("实例操作台")
    assert params_pos < launch_pos < instances_pos


def test_ai_lab_autonomous_start_params_use_tinted_parameter_cards():
    ai_lab_source = _read_ai_lab_modules()

    assert "autonomousParameterCardClass" in ai_lab_source
    assert "bg-slate-900/70" in ai_lab_source
    assert "border-white/10" in ai_lab_source
    assert "shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]" in ai_lab_source
    assert "className={autonomousParameterCardClass}" in ai_lab_source
    assert "className={autonomousRiskParameterCardClass}" in ai_lab_source

    params_start = ai_lab_source.index("启动参数")
    model_pos = ai_lab_source.index("AI模型", params_start)
    prompt_pos = ai_lab_source.index("提示词", model_pos)
    symbols_pos = ai_lab_source.index("合约标的池", prompt_pos)
    risk_pos = ai_lab_source.index("最大杠杆", symbols_pos)
    assert ai_lab_source.rfind("className={autonomousParameterCardClass}", 0, model_pos) > -1
    assert ai_lab_source.rfind("className={autonomousParameterCardClass}", model_pos, prompt_pos) > -1
    assert ai_lab_source.rfind("className={autonomousParameterCardClass}", prompt_pos, symbols_pos) > -1
    assert ai_lab_source.index("className={autonomousRiskParameterCardClass}", risk_pos) > risk_pos


def test_ai_lab_optimizer_actions_align_with_model_select():
    ai_lab_source = (ROOT / "frontend" / "src" / "pages" / "AILab.tsx").read_text(encoding="utf-8")
    optimizer_controls_start = ai_lab_source.rindex(
        '<div className="flex flex-wrap',
        0,
        ai_lab_source.index('<span>AI模型</span>'),
    )
    optimizer_controls = ai_lab_source[
        optimizer_controls_start:ai_lab_source.index('刷新\n            </button>\n          </div>', optimizer_controls_start)
    ]

    assert 'className="flex flex-wrap items-end gap-2"' in optimizer_controls
    assert "<CryptoSelect" in optimizer_controls
    assert 'controlSize="sm"' in optimizer_controls
    assert 'className={`inline-flex h-9 items-center gap-2 rounded-lg px-4' in optimizer_controls
    assert 'className="inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600' in optimizer_controls
    assert 'className="inline-flex h-9 items-center gap-2 rounded-lg border border-crypto-border' in optimizer_controls


def test_ai_lab_autonomous_instances_support_config_editing():
    ai_lab_source = _read_ai_lab_modules()

    assert "const [autonomousEditTarget" in ai_lab_source
    assert "openAutonomousConfigEditor(item)" in ai_lab_source
    assert "编辑 AI自主交易配置" in ai_lab_source
    assert "保存配置" in ai_lab_source
    assert "api.put(`/agent/autonomous-trader/${strategyId}/config`" in ai_lab_source
    assert "llm_model: autonomousEditConfig.llmModel" in ai_lab_source
    assert "max_decision_interval_sec: autonomousEditConfig.maxDecisionIntervalSec" in ai_lab_source
    assert "probe_size_pct: autonomousEditConfig.probeSizePct" in ai_lab_source
    assert "运行中实例会在下一次 AI 决策使用新模型和风控上限" in ai_lab_source


def test_ai_lab_optimizer_latest_terminal_run_can_be_deleted():
    ai_lab_source = _read_ai_lab_modules()

    assert "const latestOptimizerRunDeletable" in ai_lab_source
    assert "最近优化结果" in ai_lab_source
    assert "setOptimizerDeleteTarget(latestOptimizerRun)" in ai_lab_source
    assert "optimizerHasActiveRun ? '当前优化' : '最近优化结果'" in ai_lab_source


def test_ai_lab_autonomous_metrics_include_profit_factor_after_win_rate():
    ai_lab_source = _read_ai_lab_modules()

    assert "item.dashboard?.profit_factor" in ai_lab_source
    labels = [
        'label="胜率" value={fmtPct(item.dashboard?.win_rate)}',
        'label="盈亏比" value={fmtNumber(item.dashboard?.profit_factor)}',
        'label="交易数" value={item.dashboard?.total_trades',
    ]
    positions = [ai_lab_source.index(label) for label in labels]
    assert positions == sorted(positions)


def test_ai_lab_autonomous_summary_includes_profit_factor_after_win_rate():
    ai_lab_source = _read_ai_lab_modules()

    labels = [
        'label="收益率" value={fmtPct(selectedAutonomousInstance?.dashboard?.return_pct)}',
        'label="胜率" value={fmtPct(selectedAutonomousInstance?.dashboard?.win_rate)}',
        'label="盈亏比" value={fmtNumber(selectedAutonomousInstance?.dashboard?.profit_factor)}',
        'label="交易数" value={selectedAutonomousInstance?.dashboard?.total_trades',
    ]
    positions = [ai_lab_source.index(label) for label in labels]
    assert positions == sorted(positions)
