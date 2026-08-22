import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MONITOR = ROOT / "frontend" / "src" / "pages" / "Monitor.tsx"


def test_live_monitor_memos_track_full_strategy_updates() -> None:
    result = subprocess.run(
        [
            str(ROOT / "frontend" / "node_modules" / ".bin" / "eslint"),
            str(MONITOR),
            "--ext",
            "ts,tsx",
            "--rule",
            "react-hooks/exhaustive-deps:error",
            "--format",
            "json",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    reports = json.loads(result.stdout)
    memo_dependency_errors = [
        message["message"]
        for report in reports
        for message in report["messages"]
        if message.get("ruleId") == "react-hooks/exhaustive-deps"
        and "useMemo" in message["message"]
    ]

    assert not memo_dependency_errors, "\n".join(memo_dependency_errors)


def test_monitor_top_summary_includes_profit_return_and_win_rate_cards():
    text = MONITOR.read_text(encoding="utf-8")

    assert 'p-6 h-full flex flex-col' in text
    assert 'max-w-[1800px]' not in text
    assert 'p-6 max-w-7xl mx-auto' not in text
    assert "winRate?: number;" in text
    assert "profitFactor?: number;" in text
    assert "grossProfit?: number;" in text
    assert "grossLoss?: number;" in text
    assert "closingTrades?: number;" in text
    assert "winningTrades?: number;" in text
    assert "const monitorSummary = useMemo" in text
    assert "monitorOverviewGrid mb-6 grid grid-cols-1 gap-4 2xl:grid-cols-2" in text
    assert "monitor-overview-panel" in text
    assert "模拟盘总览" in text
    assert "实盘总览" in text
    assert "Paper / Simulation" not in text
    assert "Read-only Live" not in text
    assert "grid-cols-2 md:grid-cols-4 xl:grid-cols-9" not in text

    assert 'label="浮动盈亏"' in text
    assert "value={formatSignedUsd(monitorSummary.totalUnrealizedPnl)}" in text
    assert "value={formatSignedUsdt(monitorSummary.totalUnrealizedPnl)}" not in text
    assert 'label="总盈亏"' in text
    assert "value={formatSignedUsd(monitorSummary.totalPnl)}" in text
    assert "value={formatSignedUsdt(monitorSummary.totalPnl)}" not in text
    assert 'label="收益率"' in text
    assert "value={formatSignedPercent(monitorSummary.returnPct)}" in text
    assert 'label="胜率"' in text
    assert "value={formatPercent(monitorSummary.winRate)}" in text
    assert 'label="盈亏比"' in text
    assert "value={formatRatio(monitorSummary.profitFactor)}" in text
    assert "profitReportImageCjkFontAvailable?: boolean;" in text
    assert "中文字体未安装" in text
    paper_section = text[text.index("模拟盘总览"):text.index("实盘总览")]
    labels = ['label="总盈亏"', 'label="浮动盈亏"', 'label="收益率"', 'label="胜率"', 'label="盈亏比"', 'label="多空比"']
    positions = [paper_section.index(label) for label in labels]
    assert positions == sorted(positions)


def test_monitor_top_summary_includes_live_account_cards():
    text = MONITOR.read_text(encoding="utf-8")

    live_section = text[text.index("实盘总览"):text.index("monitorConfigPanel")]
    assert 'label="实盘账户"' in live_section
    assert 'label="运行中策略"' in live_section
    assert 'label="合约持仓"' in live_section
    assert 'label="持仓名义"' in live_section
    assert 'label="浮动盈亏"' in live_section
    assert 'label="今日已实现"' in live_section
    assert 'label="今日手续费"' in live_section
    assert 'label="风险提示"' in live_section
    assert "value={String(liveMonitorSummary.accountCount)}" in live_section
    assert "value={String(liveMonitorSummary.runningSubscriptionCount)}" in live_section
    assert "liveSubscriptionCount: livePanelStrategies.length" in text
    assert "runningSubscriptionCount: livePanelStrategies.filter(" in text
    assert "strategy => liveDeploymentStatusForMonitor(strategy) === 'running'," in text
    assert "共 ${liveMonitorSummary.liveSubscriptionCount} 个实盘订阅" in live_section
    assert "value={String(liveMonitorSummary.positionCount)}" in live_section
    assert "value={formatUsd(liveMonitorSummary.totalNotional, 0)}" in live_section
    assert "value={formatSignedUsd(liveMonitorSummary.totalUnrealizedPnl)}" in live_section
    assert "value={formatSignedUsd(liveMonitorSummary.todayRealizedPnl)}" in live_section
    assert "value={formatUsd(liveMonitorSummary.todayFees)}" in live_section
    assert "value={String(liveMonitorSummary.riskPositionCount)}" in live_section


def test_monitor_summary_card_captions_are_readable():
    text = MONITOR.read_text(encoding="utf-8")
    card_start = text.index("function SentimentCard")
    card_section = text[card_start:]

    assert "text-[11px] font-semibold text-gray-300/90" in card_section
    assert "mt-2 border-t border-white/5 pt-2 text-[11px] font-medium leading-snug text-gray-300/75" in card_section
    assert "font-mono text-xl font-bold leading-tight tabular-nums" in card_section
    assert "text-[10px] text-gray-500 mt-1" not in card_section


def test_monitor_live_summary_derives_today_and_risk_metrics():
    text = MONITOR.read_text(encoding="utf-8")

    assert "function livePositionLiquidationDistancePct(position: LiveExecutionPosition): number | null" in text
    assert "function isSameLocalDay" in text
    assert "function liveOrderTimestamp(order: LiveExecutionOrder): string | number | null" in text
    assert "function liveOrderIsToday(order: LiveExecutionOrder): boolean" in text
    assert "function liveOrderRealizedPnl(order: LiveExecutionOrder): number" in text
    assert "function liveOrderFee(order: LiveExecutionOrder): number" in text
    assert "order.info?.pnl" in text
    assert "order.info?.fee" in text
    assert "const todayOrders = liveOrders.filter(liveOrderIsToday);" in text
    assert "const todayFilledOrders = todayOrders.filter(order =>" in text
    assert "const todayRealizedPnl = todayOrders.reduce((sum, order) => sum + liveOrderRealizedPnl(order), 0);" in text
    assert "const todayFees = todayOrders.reduce((sum, order) => sum + Math.abs(liveOrderFee(order)), 0);" in text
    assert "const riskPositionCount = liveContractPositions.filter(position =>" in text
    assert "todayOrderCount: todayOrders.length" in text
    assert "todayFilledOrders" in text
    assert "todayRealizedPnl" in text
    assert "todayFees" in text
    assert "riskPositionCount" in text


def test_monitor_running_strategy_cards_use_dollar_amounts():
    text = MONITOR.read_text(encoding="utf-8")

    assert "const pnl = finiteNumber(s.pnl);" in text
    assert "{formatSignedUsd(pnl)}" in text
    assert "{formatUsd(s.equity)}" in text
    assert "{formatUsd(s.balance)}" in text
    assert "{formatSignedUsd(s.unrealizedPnl)}" in text
    assert "{(s.pnl || 0) >= 0 ? '+' : ''}{(s.pnl || 0).toFixed(2)} USDT" not in text
    assert "{(s.unrealizedPnl || 0) >= 0 ? '+' : ''}{formatUsdt(s.unrealizedPnl)}" not in text


def test_monitor_position_kpi_uses_total_position_amount_label():
    text = MONITOR.read_text(encoding="utf-8")

    assert 'label="持仓总金额"' in text
    assert "策略持仓金额 / OI" not in text


def test_monitor_position_kpi_uses_backend_notional_before_size_price_fallback():
    text = MONITOR.read_text(encoding="utf-8")

    assert "notionalUsdt?: number;" in text
    assert "notional_usdt?: number;" in text
    assert "baseQty?: number;" in text
    assert "base_qty?: number;" in text
    assert "function positionNotionalUsdt" in text
    assert "position.notionalUsdt ?? position.notional_usdt ?? position.notional ?? position.value" in text
    assert "position.baseQty ?? position.base_qty" in text
    assert "sum += positionNotionalUsdt(p);" in text
    assert "sum += Math.abs(p.size) * px;" not in text


def test_monitor_running_strategy_header_shows_spot_contract_counts():
    text = MONITOR.read_text(encoding="utf-8")

    assert "type RunningStrategyAssetClass = 'spot' | 'contract';" in text
    assert "type RunningStrategyAssetFilter = 'all' | RunningStrategyAssetClass;" in text
    assert "function inferRunningStrategyAssetClass" in text
    assert "const runningStrategyAssetCounts = useMemo" in text
    assert "const visibleRunningStrategies = useMemo" in text
    assert "function compareRunningStrategiesByProfitDesc" in text
    assert "return [...filtered].sort(compareRunningStrategiesByProfitDesc);" in text
    assert "useState<RunningStrategyAssetFilter>('all')" in text
    assert "setRunningStrategyAssetFilter('all')" in text
    assert "setRunningStrategyAssetFilter('spot')" in text
    assert "setRunningStrategyAssetFilter('contract')" in text
    assert "runningStrategyAssetCounts.spot" in text
    assert "runningStrategyAssetCounts.contract" in text
    assert "全部 {runningStrategyAssetCounts.total}" in text
    assert "现货" in text
    assert "合约" in text


def test_monitor_running_strategy_detail_button_has_visible_background():
    text = MONITOR.read_text(encoding="utf-8")

    assert 'aria-label="进入策略监控详情"' in text
    assert "bg-blue-600/15" in text
    assert "border-blue-500/30" in text
    assert "text-blue-300" in text
    assert "bg-gray-900/40" not in text


def test_monitor_running_strategy_cards_hide_exchange_badge():
    text = MONITOR.read_text(encoding="utf-8")

    assert "s.exchange?.toUpperCase()" not in text
    assert "visibleSymbols.map" in text
    assert "hiddenSymbolCount" in text


def test_monitor_running_strategy_cards_mark_ai_autonomous_strategies():
    text = MONITOR.read_text(encoding="utf-8")

    assert "isAiAutonomous?: boolean;" in text
    assert "strategyKey?: string;" in text
    assert "function isAiAutonomousRunningStrategy" in text
    assert "strategy.strategyKey === 'ai_autonomous_trader'" in text
    assert "isAiAutonomousRunningStrategy(s)" in text
    assert "AI自主" in text


def test_monitor_page_places_config_below_metrics_and_shows_live_monitor_beside_paper():
    text = MONITOR.read_text(encoding="utf-8")

    assert "liveExecutionApi" in text
    assert "LiveExecutionStrategy" in text
    assert "LiveExecutionPosition" in text
    assert "LiveExecutionOrder" in text
    assert "const [liveStrategies, setLiveStrategies]" in text
    assert "const [livePositions, setLivePositions]" in text
    assert "const liveMonitorSummary = useMemo" in text
    assert "const liveMonitorInFlightRef = useRef(false);" in text
    assert "if (liveMonitorInFlightRef.current)" in text
    assert "const liveMonitorInterval = setInterval(() =>" in text
    assert "}, 15000);" in text
    assert "monitorConfigPanel" in text
    assert "useState(false)" in text
    assert "aria-expanded={monitorConfigOpen}" in text
    assert "setMonitorConfigOpen(open => !open)" in text
    assert "模拟推送 {profitPush ? (profitPush.enabled ? 'ON' : 'OFF') : '--'}" in text
    assert "实盘推送 {liveProfitPush ? (liveProfitPush.enabled ? 'ON' : 'OFF') : '--'}" in text
    assert "{monitorConfigOpen && (" in text
    assert "monitorRuntimeGrid grid grid-cols-1 xl:grid-cols-2" in text
    assert "模拟盘监控" in text
    assert "实盘监控" in text
    assert "<LiveStrategyMonitorCard" in text

    metrics_pos = text.index("monitorOverviewGrid")
    config_pos = text.index("monitorConfigPanel", metrics_pos)
    runtime_pos = text.index("monitorRuntimeGrid", config_pos)
    paper_pos = text.index("模拟盘监控", runtime_pos)
    live_pos = text.index("实盘监控", paper_pos)
    assert metrics_pos < config_pos < runtime_pos < paper_pos < live_pos


def test_monitor_runtime_headers_have_matching_workbench_and_live_asset_filter():
    text = MONITOR.read_text(encoding="utf-8")

    assert "const [liveStrategyAssetFilter, setLiveStrategyAssetFilter]" in text
    assert "const [liveMonitorStatusFilter, setLiveMonitorStatusFilter] = useState<LiveMonitorStatusFilter>('running');" in text
    assert "const liveMonitorStatusFilters = [" in text
    status_filters = text[
        text.index("const liveMonitorStatusFilters = ["):
        text.index("] as const;", text.index("const liveMonitorStatusFilters = ["))
    ]
    assert status_filters.index("key: 'running'") < status_filters.index("key: 'paused'") < status_filters.index("key: 'all'")
    assert "label: '运行中'" in status_filters
    assert "label: '暂停'" in status_filters
    assert "label: '全部'" in status_filters
    assert "function liveMonitorStatusFilterButtonClass(filter: LiveMonitorStatusFilter, active: boolean): string" in text
    assert "function liveMonitorStatusFilterCountClass(filter: LiveMonitorStatusFilter, active: boolean): string" in text
    assert "const liveMonitorStatusCounts = useMemo" in text
    assert "running: livePanelStrategies.filter(strategy => liveDeploymentStatusForMonitor(strategy) === 'running').length" in text
    assert "paused: livePanelStrategies.filter(strategy => liveDeploymentStatusForMonitor(strategy) === 'paused').length" in text
    assert "aria-label=\"实盘监控策略状态筛选\"" in text
    assert "setLiveMonitorStatusFilter(item.key)" in text
    assert "liveMonitorStatusCounts[item.key]" in text
    assert "const liveStrategyAssetCounts = useMemo" in text
    assert "const liveStatusFilteredStrategies = useMemo" in text
    assert "const visibleLiveStrategies = useMemo" in text
    assert "function inferLiveStrategyAssetClass" in text
    assert "setLiveStrategyAssetFilter('all')" in text
    assert "setLiveStrategyAssetFilter('spot')" in text
    assert "setLiveStrategyAssetFilter('contract')" in text
    assert "全部 {liveStrategyAssetCounts.total}" in text
    assert "现货 {liveStrategyAssetCounts.spot}" in text
    assert "合约 {liveStrategyAssetCounts.contract}" in text
    assert "模拟工作台" in text
    assert "navigate('/live')" in text
    assert "实盘工作台" in text
    assert "navigate('/live-real')" in text
    assert "visibleLiveStrategies.map" in text
    assert "deployedLiveStrategies.map" not in text

    paper_header_pos = text.index('<h2 className="text-sm font-semibold text-white">模拟盘监控</h2>')
    paper_workbench_pos = text.index("模拟工作台", paper_header_pos)
    live_header_pos = text.index('<h2 className="text-sm font-semibold text-white">实盘监控</h2>')
    live_status_filter_pos = text.index("setLiveMonitorStatusFilter(item.key)", live_header_pos)
    live_filter_pos = text.index("setLiveStrategyAssetFilter('all')", live_header_pos)
    live_workbench_pos = text.index("实盘工作台", live_header_pos)
    assert paper_header_pos < paper_workbench_pos < live_header_pos
    assert live_header_pos < live_status_filter_pos < live_filter_pos < live_workbench_pos


def test_monitor_live_strategy_list_sorts_by_return_desc():
    text = MONITOR.read_text(encoding="utf-8")

    assert "function compareLiveStrategiesByReturnDesc" in text
    assert "const visibleLiveStrategies = useMemo" in text
    assert "return [...filtered].sort(compareLiveStrategiesByReturnDesc);" in text
    assert "const returnDiff = finiteNumber(b.returnPct) - finiteNumber(a.returnPct);" in text
    assert "returnDiff || b.strategyId - a.strategyId" in text


def test_monitor_live_runtime_panel_does_not_repeat_summary_metric_cards():
    text = MONITOR.read_text(encoding="utf-8")

    live_panel_start = text.index("{/* ====== 实盘监控 ====== */}")
    live_card_start = text.index("<LiveStrategyMonitorCard", live_panel_start)
    live_panel_before_cards = text[live_panel_start:live_card_start]

    assert "liveMonitorSummary.accountCount" not in live_panel_before_cards
    assert "liveMonitorSummary.deployedCount" not in live_panel_before_cards
    assert "liveMonitorSummary.positionCount" not in live_panel_before_cards
    assert "liveMonitorSummary.orderCount" not in live_panel_before_cards
    assert "liveMonitorSummary.totalNotional" not in live_panel_before_cards
    assert "liveMonitorSummary.totalUnrealizedPnl" not in live_panel_before_cards
    assert "text-gray-500\">实盘账户</div>" not in live_panel_before_cards
    assert "text-gray-500\">已部署策略</div>" not in live_panel_before_cards
    assert "text-gray-500\">合约持仓</div>" not in live_panel_before_cards
    assert "text-gray-500\">订单明细</div>" not in live_panel_before_cards
    assert "text-gray-500\">持仓名义</div>" not in live_panel_before_cards
    assert "text-gray-500\">浮动盈亏</div>" not in live_panel_before_cards


def test_monitor_live_strategy_card_uses_status_dot_without_running_badge():
    text = MONITOR.read_text(encoding="utf-8")

    card_start = text.index("function LiveStrategyMonitorCard")
    card_end = text.index("// ============================================\n// 情绪指标卡片", card_start)
    card_section = text[card_start:card_end]

    assert "const status = liveStrategyStatusLabel(strategy);" in card_section
    assert "status === '运行中' ? 'animate-pulse bg-green-400' : 'bg-gray-500'" in card_section
    assert "{status}" not in card_section
    assert "liveMonitorStatusFilters" in text
    assert "label: '运行中'" in text


def test_monitor_live_positions_count_contract_rows_without_strategy_fallback():
    text = MONITOR.read_text(encoding="utf-8")

    assert "function isOpenContractLivePosition(position: LiveExecutionPosition): boolean" in text
    assert "const liveContractPositions = useMemo" in text
    assert "livePositions.filter(isOpenContractLivePosition)" in text
    assert "positionCount: liveContractPositions.length" in text
    assert "const displayPositions = relatedPositions;" in text
    assert "positions.slice(0, 2)" not in text
    assert "positions={liveContractPositions}" in text


def test_monitor_live_scope_matches_live_real_panel_deployments():
    text = MONITOR.read_text(encoding="utf-8")

    assert "function liveAccountBindingFor" in text
    assert "function liveSubscriptionIdForAccount" in text
    assert "function liveDeploymentStatusForAccount" in text
    assert "function liveStrategyHasPanelDeploymentForAccount" in text
    assert "function liveStrategyForMonitorAccount" in text
    assert "const liveMonitorAccount = useMemo" in text
    assert "const livePanelStrategies = useMemo" in text
    assert "liveStrategyHasPanelDeploymentForAccount(strategy, liveMonitorAccount.accountId)" in text
    assert "liveStrategyForMonitorAccount(strategy, liveMonitorAccount.accountId)" in text
    assert "setLiveStrategies(strategies);" in text
    assert "setLiveAccounts(accounts);" in text
    assert "liveExecutionApi.listPositions(monitorAccount.accountId)" in text
    assert "liveExecutionApi.listOrderHistory(monitorAccount.accountId, undefined, 50)" in text
    assert "const deployedLiveStrategies = useMemo" not in text
    assert "liveStrategies.filter(liveStrategyIsDeployed)" not in text
    assert "deployedLiveStrategies.length" not in text


def test_monitor_live_account_tabs_scope_snapshot_to_selected_account():
    text = MONITOR.read_text(encoding="utf-8")

    assert "const [selectedLiveMonitorAccountId, setSelectedLiveMonitorAccountId] = useState('');" in text
    assert "const selectedLiveMonitorAccountIdRef = useRef('');" in text
    assert "selectedLiveMonitorAccountIdRef.current = selectedLiveMonitorAccountId;" in text
    assert "liveAccounts.find(account => account.accountId === selectedLiveMonitorAccountId" in text
    assert "pendingLiveMonitorAccountIdRef.current = requestedAccountId;" in text
    assert "void fetchLiveMonitor(nextAccountId, true);" in text
    assert "accounts.find(account => account.accountId === requestedAccountId" in text
    assert "setSelectedLiveMonitorAccountId(current => current === monitorAccount.accountId ? current : monitorAccount.accountId);" in text
    assert "function LiveMonitorAccountTabs" in text
    assert 'aria-label={ariaLabel}' in text
    assert 'ariaLabel="实盘总览账户切换"' in text
    assert 'ariaLabel="实盘监控账户切换"' in text
    assert text.count('<LiveMonitorAccountTabs') == 2
    assert 'role="tablist"' in text
    assert 'role="tab"' in text
    assert "const active = account.accountId === value;" in text
    assert "const selectLiveMonitorAccount = (nextAccountId: string) => {" in text
    assert "setSelectedLiveMonitorAccountId(nextAccountId);" in text
    assert "void fetchLiveMonitor(nextAccountId, true);" in text
    assert "liveExecutionApi.listPositions(monitorAccount.accountId)" in text
    assert "liveExecutionApi.listOrderHistory(monitorAccount.accountId, undefined, 50)" in text


def test_monitor_page_does_not_render_bottom_alert_type_summary():
    text = MONITOR.read_text(encoding="utf-8")

    assert "告警类型说明" not in text
    assert "当价格突破阈值时触发" not in text
    assert "运行策略收益率低于阈值时触发" not in text
    assert "合约持仓接近强平价时触发" not in text
    assert "xl:col-span-2" not in text
    assert "ALERT_TEMPLATES.map" in text
    assert "告警模板" in text


def test_monitor_config_exposes_paper_and_live_profit_push_controls():
    text = MONITOR.read_text(encoding="utf-8")
    client = (ROOT / "frontend" / "src" / "api" / "client.ts").read_text(encoding="utf-8")

    assert "模拟盘收益卡片推送" in text
    assert "实盘收益卡片推送" in text
    assert "const [liveProfitPush, setLiveProfitPush]" in text
    assert "const [liveProfitPushInterval, setLiveProfitPushInterval]" in text
    assert "fetchLiveProfitPushSettings" in text
    assert "updateLiveProfitPushSettings" in text
    assert "sendLiveProfitPushNow" in text
    assert 'aria-label="实盘收益卡片推送间隔分钟数"' in text
    assert "settingsApi.getLiveProfitPush" in text
    assert "settingsApi.setLiveProfitPush" in text
    assert "settingsApi.sendLiveProfitPushNow" in text
    assert "getLiveProfitPush" in client
    assert "setLiveProfitPush" in client
    assert "sendLiveProfitPushNow" in client
    assert "/settings/live-profit-push" in client


def test_monitor_profit_push_controls_are_horizontally_aligned():
    text = MONITOR.read_text(encoding="utf-8")

    assert "monitor-profit-push-stack grid grid-cols-1 gap-3" in text
    assert "grid grid-cols-1 gap-3 2xl:grid-cols-2" not in text
    assert text.count("monitor-profit-push-card") == 2
    assert text.count("monitor-profit-push-controls") == 2
    assert text.count("monitor-profit-push-toggle-row") == 2
    assert text.count("monitor-profit-push-interval-row") == 2
    assert text.count("monitor-profit-push-send-row") == 2
    assert text.count("monitor-profit-push-controls flex w-full flex-wrap items-center gap-2") == 2
    assert text.count("monitor-profit-push-toggle-row flex w-[104px] shrink-0") == 2
    assert text.count("monitor-profit-push-interval-row inline-flex h-8 w-[176px] shrink-0") == 2
    assert text.count("monitor-profit-push-send-row flex w-[136px] shrink-0") == 2
    assert "max-w-[220px] flex-col" not in text


def test_monitor_profit_push_send_buttons_share_same_primary_style():
    text = MONITOR.read_text(encoding="utf-8")

    assert text.count("'border-blue-500/30 bg-blue-600/15 text-blue-400 hover:bg-blue-600/25'") == 2
    assert "'border-green-500/30 bg-green-600/15 text-green-400 hover:bg-green-600/25'" not in text
