import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_strategy_instance_cards_include_win_rate_metric():
    types = _read("frontend/src/pages/liveTrading/types.ts")
    trading_instance = re.search(
        r"export type TradingInstance = \{(?P<body>.*?)\n\};",
        types,
        flags=re.S,
    )
    assert trading_instance
    assert "winRate?: number;" in trading_instance.group("body")
    assert "profitFactor?: number;" in trading_instance.group("body")
    assert "capitalVersion?: number;" in trading_instance.group("body")
    assert "leverage?: number;" in trading_instance.group("body")
    assert "strategyType?: string | null;" in trading_instance.group("body")
    assert "strategyKey?: string | null;" in trading_instance.group("body")

    page = _read("frontend/src/pages/liveTrading/index.tsx")
    assert "winRate: finiteNumber(dash.performance?.winRate, 0)" in page
    assert "profitFactor: finiteNumber(dash.performance?.profitFactor, 0)" in page
    assert "winRate: finiteNumber(p?.winRate ?? p?.win_rate, inst.winRate ?? 0)" in page
    assert "profitFactor: finiteNumber(p?.profitFactor ?? p?.profit_factor, inst.profitFactor ?? 0)" in page

    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")
    assert "const winRate = inst.winRate;" in dashboard
    assert "const profitFactor = inst.profitFactor;" in dashboard
    assert "grid grid-cols-5" not in dashboard
    assert "grid grid-cols-4" in dashboard
    assert "夏普" in dashboard
    assert "胜率" in dashboard
    assert "盈亏比" in dashboard
    assert "交易次数" in dashboard


def test_strategy_instance_cards_show_profit_amount_first_and_sharpe():
    types = _read("frontend/src/pages/liveTrading/types.ts")
    trading_instance = re.search(
        r"export type TradingInstance = \{(?P<body>.*?)\n\};",
        types,
        flags=re.S,
    )
    assert trading_instance
    assert "totalPnl?: number;" in trading_instance.group("body")

    page = _read("frontend/src/pages/liveTrading/index.tsx")
    assert "totalPnl: finiteNumber(dash.performance?.totalPnl" in page
    assert re.search(r"totalPnl:\s+finiteNumber\(\s+p\?\.totalPnl \?\? p\?\.total_pnl", page)

    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")
    running_card = re.search(
        r"visibleInstances\.map\(\(inst\) => \{(?P<body>.*?)\n\s+\{isDryRun && !readOnly && paperInstancesCount",
        dashboard,
        flags=re.S,
    )
    assert running_card
    body = running_card.group("body")
    assert "const totalPnl = inst.totalPnl;" in body
    assert "const sharpeRatio = inst.sharpeRatio;" in body
    assert "function formatSignedUsd" in dashboard
    assert "function formatSharpe" in dashboard
    assert "formatSignedUsd(totalPnl)" in body
    assert "formatSignedUsdt(totalPnl)" not in body
    assert "formatSharpe(sharpeRatio)" in body
    assert "grid min-w-0 grid-cols-2 items-end gap-2" in body
    assert "flex min-w-0 flex-col gap-1" in body
    assert "flex min-w-0 flex-col items-end gap-1 text-right" in body
    assert "whitespace-nowrap text-[clamp(0.8125rem,0.72vw,1rem)] font-bold tabular-nums" in body
    assert "truncate text-xl" not in body
    assert "text-[10px] font-semibold text-gray-400" in body
    assert "收益金额" in body
    assert "const returnToneClass" in body
    assert "formatSignedPercent(totalReturnPct)" in body
    assert "收益率" in body
    assert "夏普" in body
    assert 'mt-1 text-[10px] font-semibold text-gray-400">交易次数' in body
    assert "grid grid-cols-4" in body
    assert "rounded-xl border border-crypto-border/70 bg-crypto-bg/35" not in body
    labels = ["收益金额", "收益率", "夏普", "胜率", "盈亏比", "交易次数"]
    metrics_body = body[body.index("收益金额") :]
    positions = [metrics_body.index(label) for label in labels]
    assert positions == sorted(positions)
    assert "回撤" not in body


def test_strategy_instance_cards_show_timeframe_and_capital_pills():
    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")
    running_card = re.search(
        r"visibleInstances\.map\(\(inst\) => \{(?P<body>.*?)\n\s+\{isDryRun && !readOnly && paperInstancesCount",
        dashboard,
        flags=re.S,
    )
    assert running_card
    body = running_card.group("body")

    assert "function formatInstanceTimeframePill" in dashboard
    assert "function formatInstanceCapitalVersionPill" in dashboard
    assert "function formatInstanceLeveragePill" in dashboard
    assert "const timeframePill = formatInstanceTimeframePill(inst.timeframe);" in body
    assert "const capitalVersionPill = formatInstanceCapitalVersionPill(inst);" in body
    assert "const leveragePill = formatInstanceLeveragePill(inst);" in body
    assert "{timeframePill}" in body
    assert "{capitalVersionPill}" in body
    assert "{leveragePill}" in body
    assert "border-blue-500/30 bg-blue-500/10" in body
    assert "border-emerald-500/30 bg-emerald-500/10" in body
    assert "border-amber-500/30 bg-amber-500/10" in body
    assert "{inst.symbol} · {inst.timeframe}" not in body


def test_instance_detail_metrics_show_profit_factor_after_win_rate():
    types = _read("frontend/src/pages/liveTrading/types.ts")
    assert "profitFactor?: number;" in types

    monitor = _read("frontend/src/pages/liveTrading/InstanceMonitor.tsx")
    assert "lg:grid-cols-9" in monitor
    top_metrics = monitor[
        monitor.index('label="账户总额"'):
        monitor.index('label="运行时间"')
    ]
    assert 'label="夏普"' in top_metrics
    assert "value={formatSharpe(perf?.sharpeRatio)}" in top_metrics
    assert 'label="盈亏比"' in monitor
    labels = ['label="收益率"', 'label="夏普"', 'label="胜率"', 'label="盈亏比"', 'label="交易次数"']
    positions = [top_metrics.index(label) for label in labels]
    assert positions == sorted(positions)


def test_create_wizard_strategy_metric_summaries_include_profit_factor_after_win_rate():
    wizard = _read("frontend/src/pages/liveTrading/CreateWizard.tsx")

    assert "bt.profitFactor" in wizard
    assert "paperResult.profitFactor ?? paperResult.profit_factor" in wizard
    strategy_labels = [
        '<div className="text-[9px] text-gray-600">胜率</div>',
        '<div className="text-[9px] text-gray-600">盈亏比</div>',
        '<div className="text-[9px] text-gray-600">最大回撤</div>',
    ]
    quick_verify_labels = [
        '<div className="text-[10px] text-gray-500">胜率</div>',
        '<div className="text-[10px] text-gray-500">盈亏比</div>',
        '<div className="text-[10px] text-gray-500">最大回撤</div>',
    ]
    assert [wizard.index(label) for label in strategy_labels] == sorted(
        wizard.index(label) for label in strategy_labels
    )
    assert [wizard.index(label) for label in quick_verify_labels] == sorted(
        wizard.index(label) for label in quick_verify_labels
    )


def test_create_wizard_runtime_parameters_hide_kline_timeframe_card():
    wizard = _read("frontend/src/pages/liveTrading/CreateWizard.tsx")

    assert "执行K线周期" not in wizard
    assert "strategyTimeframe" not in wizard
    assert "config.timeframe" not in wizard
    assert "驱动方式" in wizard


def test_live_launch_requests_do_not_submit_runtime_timeframe():
    page = _read("frontend/src/pages/liveTrading/index.tsx")

    preflight_section = page[
        page.index("const runPreFlight = async () => {"):
        page.index("const handleLaunch = async () => {")
    ]
    launch_section = page[
        page.index("const handleLaunch = async () => {"):
        page.index("const handleConfirmPromotionDeployment = async () => {")
    ]

    assert "timeframe:" not in preflight_section
    assert "timeframe:" not in launch_section
    assert "selectedStrategyTimeframe" in page
    assert "timeframe: selectedStrategyTimeframe" in page


def test_create_wizard_select_step_uses_top_actions_and_only_creatable_strategies():
    page = _read("frontend/src/pages/liveTrading/index.tsx")
    wizard = _read("frontend/src/pages/liveTrading/CreateWizard.tsx")

    assert "const creatableStrategies = useMemo" in page
    assert "!ACTIVE_INSTANCE_STATUSES.has(normalizeInstanceStatus(strategy))" in page
    assert "setSelectedStrategy(creatableStrategies[0].id)" in page
    assert "strategies={creatableStrategies}" in page

    assert "sticky top-0" in wizard
    assert "仅显示停止中的策略，运行中的策略不能重复创建模拟实例" in wizard
    assert "暂无可创建的停止策略" in wizard
    assert wizard.index("下一步: 运行参数") < wizard.index("visibleStrategies.map")


def test_create_wizard_select_step_has_fuzzy_strategy_search():
    wizard = _read("frontend/src/pages/liveTrading/CreateWizard.tsx")

    assert "Search," in wizard
    assert "useMemo, useState" in wizard
    assert "function normalizeStrategySearchText(value: unknown): string" in wizard
    assert "function strategyMatchesSearch(strategy: StrategyInfo, query: string): boolean" in wizard
    assert "collectStrategyConfigSearchValues(cfg)" in wizard
    assert "getStrategySymbols(strategy)" in wizard
    assert "getStrategyTradeSymbols(strategy)" in wizard
    assert "tokens.every((token) => haystack.includes(token))" in wizard
    assert "const [strategySearchQuery, setStrategySearchQuery] = useState('');" in wizard
    assert "const visibleStrategies = useMemo" in wizard
    assert "strategies.filter((strategy) => strategyMatchesSearch(strategy, strategySearchQuery))" in wizard
    assert 'type="search"' in wizard
    assert "搜索可创建策略" in wizard
    assert 'placeholder="搜索策略、标的、周期、类型、资金版本..."' in wizard
    assert "匹配 ${visibleStrategies.length} / ${strategies.length} 个可创建策略" in wizard
    assert "未找到匹配的可创建策略" in wizard
    assert "visibleStrategies.map((s)" in wizard


def test_create_wizard_defaults_paper_capital_from_strategy_or_100u():
    constants = _read("frontend/src/pages/liveTrading/constants.ts")
    page = _read("frontend/src/pages/liveTrading/index.tsx")
    compact_page = " ".join(page.split())
    wizard = _read("frontend/src/pages/liveTrading/CreateWizard.tsx")

    assert "export const DEFAULT_PAPER_INITIAL_EQUITY = 100;" in constants
    assert "DEFAULT_PAPER_INITIAL_EQUITY" in page
    assert "mode === 'paper' ? DEFAULT_PAPER_INITIAL_EQUITY : DEFAULT_LIVE_CONFIG.initialEquity" in compact_page
    assert "initialEquity?: number;" in page
    assert "cfg.initial_capital ?? cfg.initialCapital ?? strategy.initialCapital ?? strategy.initial_capital" in compact_page
    assert "next.initialEquity = defaults.initialEquity;" in page
    assert "模拟初始资金 (USDT)" in wizard
    assert "默认启动参数" in wizard


def test_create_wizard_configure_and_preflight_actions_are_top_aligned():
    wizard = _read("frontend/src/pages/liveTrading/CreateWizard.tsx")

    configure = wizard[
        wizard.index("const renderConfigure = () => ("):
        wizard.index("const renderPreflight = () => (")
    ]
    preflight = wizard[
        wizard.index("const renderPreflight = () => ("):
        wizard.index("<ThemeDialog")
    ]

    assert 'className="flex justify-between pt-4"' not in wizard
    assert configure.index("sticky top-0") < configure.index("grid grid-cols-1 lg:grid-cols-2")
    assert configure.index("下一步: 飞行检查") < configure.index("grid grid-cols-1 lg:grid-cols-2")
    assert preflight.index("sticky top-0") < preflight.index("配置摘要")
    assert preflight.index("启动模拟运行") < preflight.index("配置摘要")


def test_live_console_header_hides_exchange_badge_next_to_view_label():
    page = _read("frontend/src/pages/liveTrading/index.tsx")

    assert "selectedExchange.toUpperCase()" not in page
    assert "创建向导" in page


def test_live_console_and_detail_use_full_width_page_shell():
    page = _read("frontend/src/pages/liveTrading/index.tsx")

    assert 'className="p-6 h-full flex flex-col"' in page
    assert "'p-6 mx-auto'" not in page
    assert "max-w-7xl" not in page
    assert "max-w-[1920px]" not in page


def test_live_instance_cards_use_four_column_density_without_truncating_metrics():
    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")

    assert "grid grid-cols-1 gap-3 lg:grid-cols-4" in dashboard
    assert "2xl:grid-cols-6" not in dashboard
    assert "repeat(auto-fill" not in dashboard
    assert "auto-fit" not in dashboard
    assert "grid grid-cols-1 lg:grid-cols-2 gap-4" not in dashboard
    assert "grid grid-cols-1 gap-3 lg:grid-cols-2" not in dashboard
    assert "truncate text-xs font-bold" not in dashboard


def test_live_instance_card_detail_button_copy_is_concise():
    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")
    running_card = re.search(
        r"visibleInstances\.map\(\(inst\) => \{(?P<body>.*?)\n\s+\{isDryRun && !readOnly && paperInstancesCount",
        dashboard,
        flags=re.S,
    )
    assert running_card
    body = running_card.group("body")

    assert "查看监控" not in dashboard
    assert "详情" in dashboard
    assert "border border-blue-500/40 bg-blue-500/10" in body
    assert "text-blue-300 transition-colors hover:bg-blue-500/20" in body
    assert body.index("关闭交易") < body.index("详情")
    assert "mt-auto flex items-center justify-center gap-2" in body
    assert "grid w-full grid-cols-1 items-center gap-2 sm:grid-cols-3" in body
    assert "inline-flex h-8 min-w-0 w-full items-center justify-center" in body
    assert "max-w-[22rem]" not in body
    assert "min-w-[6.75rem]" not in body
    assert "Eye," in dashboard
    assert '<Eye className="h-3.5 w-3.5" />' in dashboard
    assert "inline-flex w-16 justify-center rounded-full bg-blue-500/20" not in body
    assert "inline-flex w-16 justify-center rounded-full bg-purple-500/20" not in dashboard
    assert "inline-flex h-7" not in dashboard
    assert "flex-1 flex items-center justify-center gap-1 py-2" not in dashboard
    assert "mt-auto flex items-center justify-end gap-2 border-t" not in dashboard


def test_live_instance_running_status_uses_breathing_dot():
    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")
    running_card = re.search(
        r"visibleInstances\.map\(\(inst\) => \{(?P<body>.*?)\n\s+\{isDryRun && !readOnly && paperInstancesCount",
        dashboard,
        flags=re.S,
    )
    assert running_card
    body = running_card.group("body")

    assert "animate-ping" in body
    assert "shadow-[0_0_14px_rgba(52,211,153,0.85)]" in body
    assert 'aria-label="运行中"' in body
    assert "{running ? '运行中' : paused ? '暂停' : inst.status}" not in body


def test_live_instance_card_has_pause_and_stop_trading_controls():
    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")
    page = _read("frontend/src/pages/liveTrading/index.tsx")

    assert "onPausePaperTrading: (inst: TradingInstance) => void;" in dashboard
    assert "onStopPaperTrading: (inst: TradingInstance) => void;" in dashboard
    assert "暂停交易" in dashboard
    assert "继续交易" in dashboard
    assert "关闭交易" in dashboard
    assert "onPausePaperTrading(inst)" in dashboard
    assert "onStopPaperTrading(inst)" in dashboard
    assert "event.stopPropagation()" in dashboard

    assert "const handleCardPausePaperTrading = (inst: TradingInstance) => {" in page
    assert "const handleCardStopPaperTrading = (inst: TradingInstance) => {" in page
    assert "await liveApi.pause(instanceId)" in page
    assert "await liveApi.resume(instanceId)" in page
    assert "await liveApi.stop(instanceId, false)" in page
    assert "onPausePaperTrading={handleCardPausePaperTrading}" in page
    assert "onStopPaperTrading={handleCardStopPaperTrading}" in page


def test_live_console_has_spot_contract_asset_filter():
    types = _read("frontend/src/pages/liveTrading/types.ts")
    assert "export type AssetClassFilter = 'all' | 'spot' | 'contract';" in types
    assert "assetClass: Exclude<AssetClassFilter, 'all'>;" in types

    page = _read("frontend/src/pages/liveTrading/index.tsx")
    assert "function inferAssetClass" in page
    assert "assetClass: inferAssetClass" in page
    assert "capitalVersion: finiteNumber(cfg.initial_capital ?? p.initialCapital ?? p.initial_capital, NaN)" in page
    assert "capitalVersion: finiteNumber(cfg.initial_capital ?? s.initialCapital ?? s.initial_capital, NaN)" in page
    assert "leverage: resolveInstanceLeverage(cfg)" in page
    assert "const [assetClassFilter" in page
    assert "assetClassFilter === 'all' || i.assetClass === assetClassFilter" in page
    assert "assetClassCounts={assetClassCounts}" in page

    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")
    assert "assetClassFilter" in dashboard
    assert "onAssetClassFilterChange" in dashboard
    assert "全部" in dashboard
    assert "现货" in dashboard
    assert "合约" in dashboard


def test_live_console_sorts_by_return_desc_first():
    types = _read("frontend/src/pages/liveTrading/types.ts")
    page = _read("frontend/src/pages/liveTrading/index.tsx")
    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")

    assert "export type InstanceSortMode =" in types
    for mode in [
        "'created_desc'",
        "'created_asc'",
        "'return_desc'",
        "'return_asc'",
        "'sharpe_desc'",
        "'sharpe_asc'",
        "'win_rate_desc'",
        "'win_rate_asc'",
        "'profit_factor_desc'",
        "'profit_factor_asc'",
    ]:
        assert mode in types
    assert "createdAt?: string | null;" in types
    assert "const [instanceSortMode, setInstanceSortMode] = useState<InstanceSortMode>('return_desc');" in page
    assert "function compareInstancesBySortMode" in page
    assert "function compareInstanceMetric" in page
    assert "sortMode === 'created_asc'" in page
    assert "sortMode === 'return_desc'" in page
    assert "sortMode === 'return_asc'" in page
    assert "sortMode === 'sharpe_desc'" in page
    assert "sortMode === 'sharpe_asc'" in page
    assert "sortMode === 'win_rate_desc'" in page
    assert "sortMode === 'win_rate_asc'" in page
    assert "sortMode === 'profit_factor_desc'" in page
    assert "sortMode === 'profit_factor_asc'" in page
    assert "compareInstanceMetric(a, b, 'sharpeRatio', 'desc')" in page
    assert "compareInstanceMetric(a, b, 'winRate', 'desc')" in page
    assert "compareInstanceMetric(a, b, 'profitFactor', 'desc')" in page
    assert "function compareNewestInstanceFirst" in page
    assert "timestampMs(b.createdAt) - timestampMs(a.createdAt)" in page
    assert "numericInstanceRank(b) - numericInstanceRank(a)" in page
    assert ".sort(compareInstancesBySortMode(instanceSortMode))" in page
    assert "createdAt: s.createdAt ?? s.created_at ?? null" in page
    assert "instanceSortMode={instanceSortMode}" in page
    assert "onInstanceSortModeChange={setInstanceSortMode}" in page
    assert "InstanceSortMode" in dashboard
    assert "function sortDirectionFor" in dashboard
    assert "function nextInstanceSortMode" in dashboard
    assert "创建时间" in dashboard
    assert "收益率" in dashboard
    assert "夏普" in dashboard
    assert "胜率" in dashboard
    assert "盈亏比" in dashboard
    assert dashboard.index("{ field: 'return', label: '收益率' }") < dashboard.index("{ field: 'created', label: '创建时间' }")
    assert dashboard.index("{ field: 'return', label: '收益率' }") < dashboard.index("{ field: 'sharpe', label: '夏普' }")
    assert dashboard.index("{ field: 'sharpe', label: '夏普' }") < dashboard.index("{ field: 'win_rate', label: '胜率' }")
    assert dashboard.index("{ field: 'return', label: '收益率' }") < dashboard.index("{ field: 'win_rate', label: '胜率' }")
    assert dashboard.index("{ field: 'win_rate', label: '胜率' }") < dashboard.index("{ field: 'profit_factor', label: '盈亏比' }")
    assert dashboard.index("{ field: 'profit_factor', label: '盈亏比' }") < dashboard.index("{ field: 'created', label: '创建时间' }")
    sort_direction = dashboard[
        dashboard.index("function sortDirectionFor"):
        dashboard.index("function nextInstanceSortMode")
    ]
    assert "if (field === 'return')" in sort_direction
    assert "if (field === 'sharpe')" in dashboard
    assert "if (field === 'win_rate')" in dashboard
    assert "if (field === 'profit_factor')" in dashboard
    assert "bg-purple-500/20 text-purple-200 ring-1 ring-purple-400/20" in dashboard
    assert dashboard.count("h-11 items-center") >= 2
    assert dashboard.count("h-9 items-center") >= 2
    assert "创建新→旧" not in dashboard
    assert "创建旧→新" not in dashboard
    assert "收益高→低" not in dashboard
    assert "收益低→高" not in dashboard


def test_live_console_loads_every_strategy_page_before_sorting():
    page = _read("frontend/src/pages/liveTrading/index.tsx")

    assert "const STRATEGY_PAGE_SIZE = 60;" in page
    assert "async function loadAllStrategies()" in page
    assert "liveApi.getStrategies({ page: 1, perPage: STRATEGY_PAGE_SIZE })" in page
    assert "Array.from({ length: totalPages - 1 }" in page
    assert "liveApi.getStrategies({ page: index + 2, perPage: STRATEGY_PAGE_SIZE })" in page
    assert "return [firstPage, ...remainingPages].flatMap" in page
    assert "const raw = await loadAllStrategies();" in page
    assert "liveApi.getStrategies({ page: 1, perPage: 60 })" not in page


def test_live_console_supports_persistent_favorite_strategy_view():
    types = _read("frontend/src/pages/liveTrading/types.ts")
    page = _read("frontend/src/pages/liveTrading/index.tsx")
    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")

    assert "export type InstanceListView = 'all' | 'favorites';" in types
    assert "const INSTANCE_FAVORITES_STORAGE_KEY = 'bitpro_live_instance_favorites_v1';" in page
    assert "function loadFavoriteInstanceIds()" in page
    assert "window.localStorage.getItem(INSTANCE_FAVORITES_STORAGE_KEY)" in page
    assert "window.localStorage.setItem(INSTANCE_FAVORITES_STORAGE_KEY" in page
    assert (
        "const [instanceListView, setInstanceListView] = "
        "useState<InstanceListView>('favorites');"
    ) in page
    assert "const [favoriteInstanceIds, setFavoriteInstanceIds]" in page
    assert "instanceListView === 'favorites'" in page
    assert "modeInstances.filter((instance) => preferredInstanceIds.has(instance.id))" in page
    assert "onToggleFavoriteInstance={handleToggleFavoriteInstance}" in page

    assert 'role="tablist"' in dashboard
    assert "全部策略" in dashboard
    assert "优选策略" in dashboard
    assert dashboard.index("{ value: 'favorites', label: '优选策略'") < dashboard.index(
        "{ value: 'all', label: '全部策略'"
    )
    assert "preferredInstanceIds.has(inst.id)" in dashboard
    assert "onToggleFavoriteInstance(inst)" in dashboard
    assert "aria-pressed={preferred}" in dashboard
    assert "从优选移除" in dashboard
    assert "加入优选" in dashboard
    assert "收益率超过 5% 的策略会自动进入" in dashboard


def test_live_console_auto_prefers_strategies_above_five_percent_return():
    page = _read("frontend/src/pages/liveTrading/index.tsx")
    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")

    assert "const AUTO_PREFERRED_RETURN_THRESHOLD_PCT = 5;" in page
    assert "const autoPreferredInstanceIds = useMemo(" in page
    assert "const automaticPreferredInstanceIds = useMemo(" in page
    assert "instance.totalReturnPct > AUTO_PREFERRED_RETURN_THRESHOLD_PCT" in page
    assert "instance.totalReturnPct >= AUTO_PREFERRED_RETURN_THRESHOLD_PCT" not in page
    assert "new Set([...favoriteInstanceIds, ...autoPreferredInstanceIds])" in page
    assert "autoPreferredInstanceIds={autoPreferredInstanceIds}" in page
    assert "automaticPreferredInstanceIds={automaticPreferredInstanceIds}" in page

    assert "const autoPreferred = autoPreferredInstanceIds.has(inst.id);" in dashboard
    assert "disabled={autoPreferred}" not in dashboard
    assert "收益率 > 5%，点击取消自动优选" in dashboard
    assert "恢复自动优选" in dashboard


def test_live_console_has_fuzzy_instance_search():
    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")

    assert "Search" in dashboard
    assert "useMemo, useState" in dashboard
    assert "function normalizeInstanceSearchText" in dashboard
    assert "function instanceMatchesSearch" in dashboard
    assert "inst.name" in dashboard
    assert "inst.symbol" in dashboard
    assert "inst.timeframe" in dashboard
    assert "statusLabel" in dashboard
    assert "assetClassLabel" in dashboard
    assert "tokens.every((token) => haystack.includes(token))" in dashboard
    assert "const [instanceSearchQuery, setInstanceSearchQuery] = useState('');" in dashboard
    assert "const visibleInstances = useMemo" in dashboard
    assert "leverageFilteredInstances.filter((inst) => instanceMatchesSearch(inst, instanceSearchQuery))" in dashboard
    assert 'aria-label="搜索模拟实例"' not in dashboard
    assert "搜索模拟实例" in dashboard
    assert "未找到匹配的模拟实例。" in dashboard
    assert "visibleInstances.map((inst)" in dashboard
    assert 'placeholder="搜索策略、标的、周期、杠杆..."' in dashboard


def test_live_console_handles_missing_instance_text_fields():
    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")
    page = _read("frontend/src/pages/liveTrading/index.tsx")

    assert "function normalizeInstanceSearchText(value: unknown): string" in dashboard
    assert "String(value ?? '')" in dashboard
    assert "function normalizeInstanceTimeframe(value: unknown): KlineTimeframeFilter | 'other'" in dashboard
    assert "String(value ?? '').trim().toLowerCase().replace" in dashboard
    assert "value.trim()" not in dashboard

    metrics = page[
        page.index("function dashboardMetrics"):
        page.index("function metricsFromRunningStrategyStatus")
    ]
    assert "const metrics: Partial<TradingInstance>" in metrics
    assert "const timeframe = String(dash.system?.timeframe ?? '').trim();" in metrics
    assert "if (timeframe) metrics.timeframe = timeframe;" in metrics
    assert "timeframe: dash.system?.timeframe || undefined" not in metrics


def test_live_console_has_strategy_type_and_timeframe_filters():
    types = _read("frontend/src/pages/liveTrading/types.ts")
    page = _read("frontend/src/pages/liveTrading/index.tsx")
    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")

    assert "type StrategyTypeFilter = 'all' | 'cta' | 'martin' | 'ai' | 'market_making';" in dashboard
    assert "strategyType?: string | null;" in types
    assert "strategyKey?: string | null;" in types
    assert "strategyType: optionalText(cfg.strategy_type ?? cfg.strategyType)" in page
    assert "strategyKey: optionalText(cfg.strategy_key ?? cfg.strategyKey)" in page
    assert "type KlineTimeframeFilter = 'all' | '1m' | '5m' | '15m' | '30m' | '1h' | '4h' | '12h' | '1d';" in dashboard
    assert "type CapitalVersionFilter = 'all' | '100u' | '1000u';" in dashboard
    assert "function inferInstanceStrategyType" in dashboard
    assert "inst.strategyType" in dashboard
    assert "inst.strategyKey" in dashboard
    assert "normalized.includes('做市')" in dashboard
    assert "normalized.includes('marketmaking')" in dashboard
    assert "return 'market_making';" in dashboard
    assert "normalized.includes('cta')" in dashboard
    assert "normalized.includes('ctr')" not in dashboard
    assert "normalized.includes('马丁')" in dashboard
    assert "if (inst.isAiAutonomous) return 'ai';" in dashboard
    assert "normalized.includes('[ai]')" in dashboard
    assert "function normalizeInstanceTimeframe" in dashboard
    assert "function normalizeInstanceCapitalVersion" in dashboard
    assert "const [strategyTypeFilter, setStrategyTypeFilter] = useState<StrategyTypeFilter>('all');" in dashboard
    assert "const [klineTimeframeFilter, setKlineTimeframeFilter] = useState<KlineTimeframeFilter>('all');" in dashboard
    assert "const [capitalVersionFilter, setCapitalVersionFilter] = useState<CapitalVersionFilter>('all');" in dashboard
    assert "const [leverageFilter, setLeverageFilter] = useState<LeverageFilter>('all');" in dashboard
    assert "const handleStrategyTypeFilterChange = (nextFilter: StrategyTypeFilter) => {" in dashboard
    assert "setStrategyTypeFilter(nextFilter);" in dashboard
    assert "setKlineTimeframeFilter('all');" in dashboard
    assert "setCapitalVersionFilter('all');" in dashboard
    assert "setLeverageFilter('all');" in dashboard
    assert "const handleTimeframeFilterChange = (nextFilter: KlineTimeframeFilter) => {" in dashboard
    assert "const handleCapitalVersionFilterChange = (nextFilter: CapitalVersionFilter) => {" in dashboard
    assert "const strategyTypeFilteredInstances = useMemo" in dashboard
    assert "inferInstanceStrategyType(inst) === strategyTypeFilter" in dashboard
    assert "const timeframeFilteredInstances = useMemo" in dashboard
    assert "normalizeInstanceTimeframe(inst.timeframe) === klineTimeframeFilter" in dashboard
    assert "const capitalVersionFilteredInstances = useMemo" in dashboard
    assert "normalizeInstanceCapitalVersion(inst) === capitalVersionFilter" in dashboard
    assert "const leverageFilteredInstances = useMemo" in dashboard
    assert "normalizeInstanceLeverage(inst) === leverageFilter" in dashboard
    assert "const visibleInstances = useMemo" in dashboard
    assert "leverageFilteredInstances.filter((inst) => instanceMatchesSearch(inst, instanceSearchQuery))" in dashboard

    assert "策略类型" not in dashboard
    assert "{ value: 'cta', label: 'CTA' }" in dashboard
    assert "{ value: 'market_making', label: '做市' }" in dashboard
    assert "{ value: 'ctr', label: '" + "C" + "TR" + "' }" not in dashboard
    assert "马丁" in dashboard
    assert "AI" in dashboard
    assert "做市" in dashboard
    assert '>K线</span>' not in dashboard
    assert "onClick={() => handleStrategyTypeFilterChange(option.value)}" in dashboard
    assert "onClick={() => handleTimeframeFilterChange(option.value)}" in dashboard
    for label in ["1M", "5M", "15M", "30M", "1H", "4H", "12H", "1D"]:
        assert label in dashboard
    for label in ["100U", "1000U"]:
        assert label in dashboard
    assert "{ value: '10000u', label: '10000U' }" not in dashboard
    for label in ["1X", "2X", "3X", "5X", "10X", "20X", "50X"]:
        assert label in dashboard

    assert dashboard.index("assetClassOptions.map") < dashboard.index("strategyTypeOptions.map")
    assert dashboard.index("strategyTypeOptions.map") < dashboard.index("timeframeOptions.map")
    assert dashboard.index("timeframeOptions.map") < dashboard.index("capitalVersionOptions.map")
    assert dashboard.index("capitalVersionOptions.map") < dashboard.index("leverageOptions.map")
    assert dashboard.index("leverageOptions.map") < dashboard.index("sortControls.map")
    assert "aria-pressed={active}" in dashboard
    assert "strategyTypeCounts[option.value]" in dashboard
    assert "timeframeCounts[option.value]" in dashboard
    assert "capitalVersionCounts[option.value]" in dashboard
    assert "leverageCounts[option.value]" in dashboard


def test_live_instance_card_strategy_name_uses_asset_class_colors():
    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")
    running_card = re.search(
        r"visibleInstances\.map\(\(inst\) => \{(?P<body>.*?)\n\s+\{isDryRun && !readOnly && paperInstancesCount",
        dashboard,
        flags=re.S,
    )
    assert running_card
    body = running_card.group("body")
    assert "function strategyNameColorClass" in dashboard
    assert "assetClass === 'contract'" in dashboard
    assert "text-[#FFAB73]" in dashboard
    assert "text-yellow-300" in dashboard
    assert "strategyNameColorClass(inst.assetClass)" in body
    assert "title={inst.name}" in body
    assert "aria-label={`策略名称：${inst.name}`}" in body
    assert "text-sm font-semibold text-white truncate" not in body


def test_ai_autonomous_strategy_cards_show_special_badge():
    types = _read("frontend/src/pages/liveTrading/types.ts")
    dashboard = _read("frontend/src/pages/liveTrading/InstanceDashboard.tsx")
    wizard = _read("frontend/src/pages/liveTrading/CreateWizard.tsx")
    constants = _read("frontend/src/pages/liveTrading/constants.ts")
    page = _read("frontend/src/pages/liveTrading/index.tsx")

    assert "isAiAutonomous?: boolean;" in types
    assert "AI_AUTONOMOUS_STRATEGY_KEY = 'ai_autonomous_trader'" in constants
    assert "function isAiAutonomousStrategy" in constants
    assert "isAiAutonomous: isAiAutonomousStrategy" in page
    assert "inst.isAiAutonomous" in dashboard
    assert "AI自主" in dashboard
    assert "isAiAutonomousStrategy(s)" in wizard
    assert "AI自主" in wizard


def test_live_instance_card_metric_polling_survives_strategy_list_refreshes():
    page = _read("frontend/src/pages/liveTrading/index.tsx")

    assert "const DASHBOARD_LIST_REFRESH_INTERVAL_MS = 60_000;" in page
    assert "dashboardListRefreshInFlightRef.current" in page
    assert "setInterval(refreshDashboardLists, DASHBOARD_LIST_REFRESH_INTERVAL_MS)" in page
    assert "}, 5000);" not in page
    assert "metricRefreshSignature" in page
    assert "metricRefreshTargetsRef.current" in page
    assert "}, [metricRefreshSignature, view]);" in page
    assert "}, [paperInstances, strategies, view]);" not in page


def test_live_instance_card_metrics_batch_running_paper_strategies():
    page = _read("frontend/src/pages/liveTrading/index.tsx")

    assert "monitorApi" in page
    assert "function metricsFromRunningStrategyStatus" in page
    assert "const livePaperTargets = active.filter" in page
    assert "monitorApi.getActiveStrategies()" in page
    assert "runningStatusMetricsById" in page

    refresh_start = page.index("const refreshInstanceMetrics = async () => {")
    refresh_end = page.index("setInstanceMetrics((prev) => {", refresh_start)
    refresh_body = page[refresh_start:refresh_end]
    batch_return = "if (inst.id.startsWith('live:strategy:') && inst.dryRun !== false)"
    assert batch_return in refresh_body
    assert refresh_body.index(batch_return) < refresh_body.index("liveApi.getDashboard(qid)")
