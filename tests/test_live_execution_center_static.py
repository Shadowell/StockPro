from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_live_preflight_result_close_blocks_hover_focus_reopen():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")

    assert "const [closedPreflightResultKey, setClosedPreflightResultKey] = useState<string | null>(null);" in page
    assert "const resultPanelDismissed = closedPreflightResultKey === currentPreflightKey && !resultPanelPinned;" in page
    assert "onMouseLeave={() => setClosedPreflightResultKey(null)}" not in page
    assert "setClosedPreflightResultKey(currentPreflightKey);" in page
    assert "!resultPanelDismissed && 'group-hover:pointer-events-auto group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:translate-y-0 group-focus-within:opacity-100'" in page


def test_live_real_nav_and_route_are_registered():
    app = _read("frontend/src/App.tsx")
    layout = _read("frontend/src/components/MainLayout.tsx")
    page = _read("frontend/src/pages/liveTrading/index.tsx")

    assert 'path="live-real" element={<LiveTrading modeScope="live" />}' in app
    live_real_nav = "{ path: '/live-real', icon: Rocket, label: '实盘', allowedRoles: ['admin', 'guest'] }"
    assert live_real_nav in layout
    assert layout.index("{ path: '/live', icon: Activity, label: '模拟', allowedRoles: ['admin', 'guest'] }") < layout.index(
        live_real_nav
    ) < layout.index("{ path: '/watch', icon: ScanLine, label: '盯盘', allowedRoles: ['admin', 'guest'] }")
    assert "import LiveExecutionCenter from './LiveExecutionCenter';" in page
    assert "return <LiveExecutionCenter />;" in page


def test_live_execution_frontend_api_uses_live_strategy_endpoints():
    client = _read("frontend/src/api/client.ts")

    assert "export interface LiveExecutionStrategy" in client
    assert "export interface LiveExecutionAccount" in client
    assert "export interface LiveExecutionAccountBinding" in client
    assert "liveSubscriptionId?: number | null" in client
    assert "instrumentType?: string | null" in client
    assert "positionSide?: string | null" in client
    assert "positionDirection?: string | null" in client
    assert "positionEffect?: string | null" in client
    assert "baseAmount?: number | null" in client
    assert "maintenanceMargin?: number | null" in client
    assert "marginRatio?: number | null" in client
    assert "marginMode?: string | null" in client
    assert "leverage?: number | string | null" in client
    assert "reduceOnly?: boolean | null" in client
    assert "tdMode?: string | null" in client
    assert "fillPrice?: number | null" in client
    assert "fillSize?: number | null" in client
    assert "feeCurrency?: string | null" in client
    assert "feeCost?: number | string | null" in client
    assert "pnl?: number | string | null" in client
    assert "realizedPnl?: number | string | null" in client
    assert "fillPnl?: number | string | null" in client
    assert "bitproSource?: 'strategy' | 'external'" in client
    assert "bitproSourceLabel?: string | null" in client
    assert "sourceStrategyId?: number | null" in client
    assert "sourceStrategyName?: string | null" in client
    assert "subscriptionId?: number | null" in client
    assert "signalEventId?: number | null" in client
    assert "accountBindings?: LiveExecutionAccountBinding[]" in client
    assert "canTrade?: boolean | null" in client
    assert "permissionCheckedAt?: string | null" in client
    assert "bindAccount?: boolean" in client
    assert "export const liveExecutionApi" in client
    assert "getReq('/live/accounts')" in client
    assert "postReq('/live/accounts', payload)" in client
    assert "getReq(`/live/accounts/${accountId}/balance`" in client
    assert "getReq(`/live/accounts/${accountId}/balance/detail`" in client
    assert "getReq('/live/strategies')" in client
    assert "api.patch(`/live/strategies/${strategyId}`" in client
    assert "postReq(`/live/strategies/${strategyId}/preflight`" in client
    assert "postReq(`/live/strategies/${strategyId}/deploy`" in client
    assert "postReq(`/live/strategies/${strategyId}/enable-account`" in client
    assert "postReq(`/live/strategies/${strategyId}/pause`" in client
    assert "postReq(`/live/strategies/${strategyId}/resume`" in client
    assert "postReq(`/live/strategies/${strategyId}/stop`" in client
    assert "getReq(`/live/accounts/${accountId}/positions`" in client
    assert "closePosition: (" in client
    assert "postReq(`/live/accounts/${accountId}/positions/close`, payload)" in client
    assert "getReq(`/live/accounts/${accountId}/orders/open`" in client
    assert "getReq(`/live/accounts/${accountId}/orders/history`" in client


def test_watch_market_loads_kline_chart_on_demand():
    page = _read("frontend/src/pages/WatchMarket.tsx")

    assert "const WatchKlineChart = lazy(() => import('../components/WatchKlineChart'));" in page
    assert "<Suspense fallback=" in page
    assert "K 线图加载中..." in page
    assert "import WatchKlineChart from '../components/WatchKlineChart';" not in page


def test_live_account_preflight_and_enable_are_scoped_per_account():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")

    assert "绑定并启用下单" in page
    assert "启用下单" in page
    assert "preflightStrategyAccount" in page
    assert "liveExecutionApi.preflightStrategy(strategy.strategyId" in page
    assert "preflights[preflightKey(strategy.strategyId, account.accountId)]" in page
    assert "if (preflightPassed) openEnableAccountConfirm(strategy, account.accountId);" in page
    assert "先对该账户执行独立预检" in page
    assert "preflightPassed ? '预检通过'" in page
    assert "accountPickerStrategyId" not in page
    assert "pendingBindAccountId" not in page
    assert "enableStrategyAccount" in page
    assert "setSelectedAccountId(accountId);" in page
    assert "confirmPaperReviewed: true" in page
    assert "confirmLiveRisk: true" in page
    assert 'aria-label="实盘部署流水线"' not in page


def test_live_account_switch_clears_stale_account_error():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")

    assert "applyLiveAssetSnapshot(EMPTY_LIVE_ASSET_SNAPSHOT);" in page
    assert "setAccountError('');\n    setAccountLoading(false);\n  }, [applyLiveAssetSnapshot, selectedAccountId]);" in page
    assert "if (assetSnapshotRequestSeqRef.current === requestSeq) setAccountError('');" in page


def test_live_strategy_list_exposes_guarded_remove_action():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")

    assert "removeStrategyFromWorkspace" in page
    assert "移出实盘列表" in page
    assert "liveExecutionApi.updateStrategy(strategy.strategyId, { added: false })" in page
    assert "仍有正在运行的实盘订阅" in page
    assert "已暂停的实盘订阅需要先停止后才能移出" in page


def test_live_execution_panel_refreshes_every_five_seconds():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")

    assert "const LIVE_PANEL_REFRESH_INTERVAL_MS = 5_000;" in page
    assert "const refreshLivePanelData = useCallback(async () => {" in page
    assert "loadStrategies({ silent: true })" in page
    assert "loadExecutionSnapshot({ silent: true })" in page
    assert "loadAccountSnapshot({ silent: true })" not in page
    assert "window.setInterval(runRefresh, LIVE_PANEL_REFRESH_INTERVAL_MS)" in page
    assert "window.clearInterval(timer)" in page


def test_live_panel_pause_copy_is_live_signal_only():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")

    assert "暂停实盘信号" in page
    assert "继续实盘信号" in page
    assert "源模拟策略继续运行并继续产生模拟盘信号" in page
    assert "aria-label={canResumeDeployment ? '继续实盘信号' : '暂停实盘信号'}" in page
    assert "title={canResumeDeployment ? '恢复当前账户的实盘信号执行' : '仅暂停当前账户实盘信号执行，源模拟策略继续运行并继续产生模拟盘信号'}" in page


def test_live_assets_use_cached_render_and_one_minute_background_refresh():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")

    assert "const LIVE_ASSET_REFRESH_INTERVAL_MS = 60_000;" in page
    assert "const LIVE_ASSET_CACHE_TTL_MS = 5 * 60_000;" in page
    assert "function liveAssetCacheKey(accountId: string): string" in page
    assert "window.sessionStorage.getItem(liveAssetCacheKey(accountId))" in page
    assert "window.sessionStorage.setItem(liveAssetCacheKey(accountId), JSON.stringify(payload))" in page
    assert "const loadAssetSnapshot = useCallback(async (options: { silent?: boolean; preferCache?: boolean } = {}) => {" in page
    assert "const cachedSnapshot = options.preferCache ? readCachedLiveAssetSnapshot(accountId) : null;" in page
    assert "applyLiveAssetSnapshot(cachedSnapshot);" in page
    assert "writeCachedLiveAssetSnapshot(accountId, nextSnapshot);" in page
    assert "void loadAccountSnapshot({ preferCache: true });" in page
    assert "window.setInterval(runAssetRefresh, LIVE_ASSET_REFRESH_INTERVAL_MS)" in page
    assert "loadAssetSnapshot({ silent: true })" in page


def test_live_account_switch_discards_empty_snapshot_cache_and_uses_binance_futures_wallet():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")

    assert "function hasRenderableLiveAssetSnapshot(snapshot: LiveAssetSnapshot): boolean" in page
    assert "const canRenderCachedSnapshot = Boolean(cachedSnapshot && hasRenderableLiveAssetSnapshot(cachedSnapshot));" in page
    assert "applyLiveAssetSnapshot(EMPTY_LIVE_ASSET_SNAPSHOT);" in page
    assert "const isBinanceUsdmAccount = selectedAccount?.exchange === 'binanceusdm';" in page
    assert "USD-M 合约账户" in page
    assert "Futures Wallet" in page


def test_live_account_management_actions_are_inline_and_filled():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")
    account_header = page[
        page.index("实盘账户管理") : page.index("{!readOnly && accountFormOpen &&", page.index("实盘账户管理"))
    ]

    assert "flex min-w-0 flex-1 flex-wrap items-center justify-end gap-2 sm:flex-nowrap" in account_header
    assert "<LiveAccountTabs" in account_header
    assert 'className="min-w-[252px] flex-1 sm:w-[360px] sm:flex-none"' in account_header
    assert "inline-flex h-8 shrink-0 items-center justify-center" in account_header
    assert "border border-blue-400/35 bg-blue-500/15" in account_header
    assert "hover:border-blue-300/55 hover:bg-blue-500/25" in account_header
    assert "border-red" not in account_header
    assert "bg-crypto-bg px-2.5" not in account_header


def test_live_account_management_defaults_to_collapsed_panel():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")

    assert "const [accountManagementOpen, setAccountManagementOpen] = useState(false);" in page
    assert "event.target instanceof Element && event.target.closest('[data-account-management-control]')" in page
    assert "setAccountManagementOpen((open) => !open);" in page
    assert "flex cursor-pointer flex-wrap items-stretch justify-between gap-3" in page
    assert "liveAccountManagementToggle" in page
    assert "group flex min-w-[240px] flex-1 items-center gap-2" in page
    assert "hover:bg-white/[0.03]" in page
    assert "rounded-lg pr-2 text-left" not in page
    assert "aria-expanded={accountManagementOpen}" in page
    assert 'aria-controls="live-account-management-panel"' in page
    assert 'id="live-account-management-panel"' in page
    assert "{accountManagementOpen && (" in page
    assert "accountManagementOpen && 'mb-3 border-b border-crypto-border pb-3'" in page
    assert page.count("data-account-management-control") >= 3


def test_live_account_management_controls_do_not_toggle_header():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")
    account_header = page[
        page.index("event.target instanceof Element && event.target.closest('[data-account-management-control]')"):
        page.index('<div id="live-account-management-panel"', page.index("实盘账户管理"))
    ]

    assert "<LiveAccountTabs" in account_header
    assert "data-account-management-control" in page[page.index("function LiveAccountTabs"):page.index("function canUseAccountForLiveDeployment")]
    add_account_button = account_header[account_header.index("增加账户") - 900:account_header.index("增加账户")]
    assert "data-account-management-control" in add_account_button


def test_live_execution_center_exposes_signal_style_workbench():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")
    summary_panels = _read("frontend/src/components/live/LiveAccountSummaryPanels.tsx")

    assert "实盘交易" in page
    assert "实盘账户管理" in page
    assert "选择账户 / 新增 OKX 或 Binance USD-M API Key" in page
    assert "增加账户" in page
    assert "真实资金" not in page
    assert "border border-blue-400/35 bg-blue-500/15" in page
    assert "border border-red-500/40 bg-crypto-bg px-2.5" not in page
    assert "border border-red-500/40 bg-red-500/10 px-2.5" not in page
    assert "border border-red-500/30 bg-crypto-bg px-2.5 py-1" not in page
    assert "border border-red-500/30 bg-red-500/10 px-2.5 py-1" not in page
    assert "当前账户详情" not in page
    assert page.index("实盘账户管理") < page.index("增加账户") < page.index("{renderTotalAssetPanel()}")
    assert "USDT 总额" not in page
    assert "border-b border-crypto-border pb-3" in page
    assert "新增实盘账户" in page
    assert "Binance USD-M 永续" in page
    assert "API Key" in page
    assert "Secret Key" in page
    assert "Passphrase" in page
    assert "交易权限测试" in page
    assert "Trade 权限" in page
    assert "测试并保存账户" in page
    assert "测试中" in page
    assert "accountFormError" in page
    assert "selectedAccount?.canTrade" not in page
    assert "liveExecutionApi.createAccount" in page
    assert "selectedAccountId" in page
    assert "function LiveAccountTabs" in page
    assert "function LiveAccountDropdown" not in page
    assert "ariaLabel = '实盘账户切换'" in page
    assert 'aria-label={ariaLabel}' in page
    assert 'role="tablist"' in page
    assert 'role="tab"' in page
    assert "onChange={setSelectedAccountId}" in page
    assert "<CryptoSelect\n                value={selectedAccountId}" not in page
    assert "selectedExchangeAlias" in page
    assert "使用的实盘账户" in page
    assert "先对该账户执行独立预检" in page
    assert "border-red-400/70 bg-crypto-bg text-red-100" not in page
    assert "border-red-500/40 bg-crypto-bg text-red-200 hover:bg-white/[0.03]" not in page
    assert "border-red-400/70 bg-red-500/25" not in page
    assert "border-crypto-border bg-crypto-bg/80 text-gray-100" in page
    assert "border-red-500/55 bg-crypto-bg/80 text-red-100" not in page
    assert "border-red-500/55 bg-red-500/10 text-red-100" not in page
    assert "const [sortMode, setSortMode] = useState<SortMode>('return_desc');" in page
    assert page.index("{ field: 'return' as const, label: '收益率' }") < page.index("{ field: 'created' as const, label: '更新时间' }")
    assert "bg-purple-500/20 text-purple-200 ring-1 ring-purple-400/20" in page
    assert "bg-amber-500/20 text-amber-100 ring-1 ring-amber-400/20" not in page
    assert "preflightStrategyAccount" in page
    assert "openEnableAccountConfirm" in page
    assert "enableStrategyAccount" in page
    assert "unbindAccountFromStrategy" in page
    assert "bindAccount: false" in page
    assert "解除账户绑定" in page
    assert "preflightPassed ? (bound ? '启用下单' : '绑定并启用') : '预检'" in page
    assert "{bound ? '移除' : '绑定'}" not in page
    assert "setSelectedStrategyId(strategy.strategyId)" in page
    assert "Array.isArray(strategy.accountIds)" in page
    assert "accountBindingFor(strategy, account.accountId)" in page
    assert "{deploymentId ? '已部署' : bound ? '已绑定' : '未绑定'}" not in page
    assert "preflightPassed ? '预检通过' : bound ? '已绑定待启用' : '未绑定'" in page
    assert "? 'bg-yellow-500/15 text-yellow-300'" in page
    assert "disabled={busy || accountDeployed || !deployableAccount}" in page
    assert "策略选择" in page
    assert "实盘策略列表" in page
    assert '<h2 className="flex items-center gap-2 text-lg font-semibold text-gray-100">' in page
    assert 'className="flex items-center gap-2 text-sm font-semibold text-gray-200"' not in page
    assert "border-blue-500/55 bg-blue-500/10" in page
    assert "border-red-500/60 bg-crypto-bg/90" not in page
    assert "border-red-500/60 bg-red-500/10" not in page
    assert "border-red-500/50 bg-crypto-bg px-2 text-[11px]" in page
    assert "border-red-500/50 bg-red-600/15" not in page
    assert "border-red-500/50 bg-crypto-bg px-3 text-xs" not in page
    assert "border-red-500/50 bg-red-500/15 px-3" not in page
    assert "模拟盘实例" in page
    assert "打开对应模拟盘实例" in page
    assert "to={`/live?mode=paper&strategyId=${strategy.strategyId}`}" in page
    assert "实盘面板" in page
    assert "当前账户尚未部署实盘策略" in page
    assert "已加入的模拟策略只用于预检和部署准备" not in page
    assert "实盘执行订阅" in page
    assert "实盘策略 ID" not in page
    assert "#{selectedDeploymentId}" not in page
    assert "currentAccountDeployments" in page
    assert "deploymentIdForAccount(strategy, selectedAccountId)" not in page
    assert "liveSubscriptionIdForAccount(strategy, selectedAccountId)" in page
    assert "deploymentStatusForAccount(strategy, selectedAccountId)" in page
    assert "filteredAccountDeployments.map(({ strategy, liveSubscriptionId, deploymentStatus })" in page
    assert "strategy.deploymentStrategyName || strategy.strategyName || '当前账户实盘策略'" in page
    assert "实盘策略 #${selectedDeploymentId}" not in page
    assert "selectedDeploymentStatus || (selectedAccountBound ? selectedStrategy.workspaceStatus" not in page
    assert "模拟收益金额" not in page
    assert "搜索策略名称 / ID / 交易对" in page
    assert "strategyFilters" in page
    assert "strategyFilterCounts" in page
    assert "strategyFilterCounts[item.key]" in page
    assert "strategyMatchesSearch(strategy, keyword)" in page
    assert "strategyMatchesFilter(strategy, filter)" in page
    assert "function isRunningStrategy(strategy: LiveExecutionStrategy): boolean" in page
    assert "function isRunningDeployableStrategy(strategy: LiveExecutionStrategy): boolean" in page
    assert "String(strategy.status || '').toLowerCase() === 'running'" in page
    assert "if (!isRunningStrategy(strategy)) return false;" in page
    assert "if (filter === 'deployable') return isRunningDeployableStrategy(strategy);" in page
    assert "isRunningStrategy(strategy) && strategyMatchesSearch(strategy, keyword)" in page
    assert "deployable: searchableStrategies.filter(isRunningDeployableStrategy).length" in page
    assert "只有运行中的模拟策略可加入实盘" in page
    assert "canAddStrategy ? '加入实盘' : '未运行'" in page
    assert "可部署" in page
    assert "已部署" in page
    assert "加入实盘" in page
    assert "setNotice" not in page
    assert "error || notice" not in page
    assert "{error && (" not in page
    assert "绑定并启用下单失败" in page
    assert "failedPreflight(" in page
    assert "绑定并启用下单" in page
    assert "查看最近启用检查" in page
    assert "实盘部署流水线" not in page
    assert "renderDeployPipeline" not in page
    assert "deploymentPipelineStepBase" not in page
    assert "const [openPreflightResultKey, setOpenPreflightResultKey] = useState<string | null>(null);" in page
    assert "const [closedPreflightResultKey, setClosedPreflightResultKey] = useState<string | null>(null);" in page
    assert "setOpenPreflightResultKey(key);" in page
    assert "const resultPanelPinned = openPreflightResultKey === currentPreflightKey;" in page
    assert "const resultPanelDismissed = closedPreflightResultKey === currentPreflightKey && !resultPanelPinned;" in page
    assert "onClick={() => {" in page
    assert "const nextPinned = !resultPanelPinned;" in page
    assert "setClosedPreflightResultKey(nextPinned ? null : currentPreflightKey);" in page
    assert "setOpenPreflightResultKey(nextPinned ? currentPreflightKey : null);" in page
    assert "setClosedPreflightResultKey(null);" in page
    assert "onMouseLeave={() => setClosedPreflightResultKey(null)}" not in page
    assert "setClosedPreflightResultKey(nextPinned ? null : currentPreflightKey);" in page
    assert "setClosedPreflightResultKey(currentPreflightKey);" in page
    assert "aria-expanded={resultPanelPinned}" in page
    assert 'role="dialog"' in page
    assert "group-hover:opacity-100" in page
    assert "group-focus-within:opacity-100" in page
    assert "!resultPanelDismissed && 'group-hover:pointer-events-auto group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:translate-y-0 group-focus-within:opacity-100'" in page
    assert "关闭启用检查结果" in page
    assert "event.stopPropagation();" in page
    assert "setClosedPreflightResultKey(currentPreflightKey);" in page
    assert "resultPanelPinned" in page
    assert "fixed left-1/2" in page
    assert "z-[80]" in page
    assert "w-[min(760px,calc(100vw-2rem))]" in page
    assert "max-h-[min(28rem,calc(100vh-13rem))]" in page
    assert "absolute left-0 top-10" not in page
    assert "preflightResultButtonTone(activePreflight)" in page
    assert "font-mono text-[11px] leading-5" in page
    assert "[{check.passed ? 'PASS' : 'FAIL'}] #{String(index + 1).padStart(2, '0')}" in page
    assert "preflightLogTone(check.passed)" in page
    assert "尚无预检结果" not in page
    assert "flex items-start gap-2 rounded-md border border-crypto-border bg-crypto-card px-2.5 py-2 text-xs" not in page
    assert "确认绑定并启用下单" in page
    assert "ThemeDialog" in page
    assert "confirmPaperReviewed: true" in page
    assert "confirmLiveRisk: true" in page
    assert "await enableStrategyAccount(strategy, accountId)" in page
    assert "将立即订阅该策略后续信号并进行真实下单" in page
    assert "实盘执行订阅" in page
    assert "将克隆独立实盘策略" not in page
    assert "preflightKey(strategy.strategyId, accountId)" in page
    assert "deployReady" not in page
    assert "deploymentPipelineDisabled" not in page
    assert "liveActionButtonWarning" in page
    assert "liveActionButtonDanger" in page
    assert "const visiblePreflight = activePreflight" in page
    assert "loadStrategies({ silent: true })" in page
    assert "window.setInterval" in page
    assert "window.clearInterval(timer)" in page
    assert "await loadAccountSnapshot()" in page
    assert "实盘操作" not in page
    assert "openDeployConfirm" not in page
    assert "deploymentStatusLightClass(deploymentStatus)" in page
    assert "deploymentStatusLabel(deploymentStatus)" in page
    assert "selectedDeploymentStatus || 'deployed'" not in page
    assert "运行状态" not in page
    assert "canToggleDeployment" in page
    assert "canStopCurrentDeployment" in page
    assert "deploymentStatus !== 'stopped'" in page
    assert "disabled={!canToggleDeployment || strategyBusy}" in page
    assert "disabled={!canStopCurrentDeployment || strategyBusy}" in page
    assert "void pauseDeployment(strategy)" in page
    assert "void resumeDeployment(strategy)" in page
    assert "openStopConfirm(strategy)" in page
    assert "border-yellow-500/40 text-yellow-300 hover:bg-yellow-500/10" in page
    assert "border-green-500/40 text-green-300 hover:bg-green-500/10" in page
    assert "border-red-500/40 text-red-300 hover:bg-red-500/10" in page
    assert "livePanelActionButtonBase" in page
    assert "暂停交易" not in page
    assert "关闭交易" not in page
    assert "继续交易" not in page
    assert "暂停" in page
    assert "停止" in page
    assert "disabled:border-crypto-border disabled:bg-white/[0.03] disabled:text-gray-500" in page
    assert "accountPanelTab" not in page
    assert "type AccountPanelTab" not in page
    assert "['assets', '资产', Wallet]" not in page
    assert "实盘摘要" not in page
    assert page.index("{renderTotalAssetPanel()}") < page.index("{renderBalancePanel('资金账户'") < page.index("{renderBalancePanel('交易账户'")
    assert "renderTotalAssetPanel()" in page
    assert "isBinanceUsdmAccount ? 'xl:grid-cols-2' : 'xl:grid-cols-3'" in page
    assert "bg-gradient-to-r from-blue-600/15 to-purple-600/15" not in page
    assert page.index("总资产（估算）") < page.index("策略选择")
    account_segment = page[page.index("总资产（估算）"):page.index("策略选择")]
    assert "account_id:" not in account_segment
    assert "API Key:" not in account_segment
    assert "OKX Mainnet" not in account_segment
    assert "交易权限：" not in account_segment
    assert "已加入</div>" not in account_segment
    panel_segment = page[page.index("实盘面板"):]
    assert panel_segment.index("已加入</div>") < panel_segment.index("selectedStrategies.length === 0 && currentAccountDeployments.length === 0")
    assert "currentAccountDeployments.length > 0" in panel_segment
    panel_header_segment = page[page.index("实盘面板"):page.index("mb-4 grid grid-cols-4")]
    assert 'to="/watch"' in panel_header_segment
    assert "打开盯盘" in panel_header_segment
    assert "合约持仓和订单明细已移至盯盘页" not in page
    assert "持仓明细、订单明细和拒单日志在盯盘页顶部第一排统一查看" not in page
    assert "总资产（估算）" in page
    assert "估算资产" in page
    assert "1日收益率" in page
    assert "7日收益率" in page
    assert "30日收益率" in page
    assert "accountReturnRates" in page
    assert "formatReturnRate" in page
    assert "资金账户" in page
    assert "交易账户" in page
    assert "合约持仓" in page
    assert 'to="/watch"' in page
    assert "renderContractPositionsPanel(contractPositions)" not in page
    assert "当前账户无合约持仓" not in page
    assert "contractDisplaySymbol(symbol)" not in page
    assert "contractSideBadge(position)" not in page
    assert "持仓量 ({base})" not in page
    assert "保证金 (USDT)" not in page
    assert "维持保证金率" not in page
    assert "开仓均价" not in page
    assert "标记价格" not in page
    assert "预估强平价" not in page
    assert "收益额 (USDT)" not in page
    assert ">止盈止损<" not in page
    assert "确认市价全平" not in page
    assert "openPositionCloseConfirm(position, false)" not in page
    assert "openPositionCloseConfirm(position, true)" not in page
    assert "closeContractPosition(position, closeAll)" not in page
    assert "confirmLiveRisk: true" in page
    assert "const closingSingle = positionClosingKey === positionActionKey(position, false);" not in page
    assert "const closingAll = positionClosingKey === positionActionKey(position, true);" not in page
    assert "disabled={closingPosition}" not in page
    assert "持仓操作需要二次确认后接入" not in page
    assert "grid-cols-[minmax(0,1.2fr)_0.65fr_0.8fr_0.8fr]" not in page
    live_api_source = _read("backend/app/api/v2/endpoints/live.py") + _read(
        "backend/app/api/v2/endpoints/live_support.py"
    )
    assert "asset_type" in live_api_source
    okx_source = _read("backend/app/exchange/okx.py")
    assert "fetch_account_return_rates" in okx_source
    assert "privateGetAssetAssetValuation" in okx_source
    assert "fetch_ohlcv" in okx_source
    assert "getAccountBalanceDetail(accountId)" in page
    assert "当前挂单" not in page
    assert "历史订单" not in page
    assert "订单明细" in page
    assert "暂无订单明细" not in page
    assert "策略来源" in summary_panels
    assert "function orderSourceLabel(order: LiveExecutionOrder)" not in page
    assert "function orderSourceLabel(order: LiveExecutionOrder)" in summary_panels
    assert "order.sourceStrategyName" in summary_panels
    assert "手动/外部订单" in summary_panels
    assert "BitPro 策略信号" in summary_panels
    assert "外部/手动" in summary_panels
    assert "listOpenOrders(selectedAccountId)" not in page
    assert "成交/委托" in summary_panels
    assert "手续费" in summary_panels
    assert "订单号" in summary_panels
    assert "日志详情" in summary_panels
    assert "orderHasFailureLog(order)" in summary_panels
    assert "OKX 拒单日志" in summary_panels
    assert "function orderFailureLogEntries(order: LiveExecutionOrder)" not in page
    assert "function orderFailureLogEntries(order: LiveExecutionOrder)" in summary_panels
    assert "if (normalized === 'failed' || normalized === 'rejected') return '失败';" not in page
    assert "import { getTradeSideDisplay } from '../../utils/tradeSide';" not in page
    assert "function orderDirection(order: LiveExecutionOrder)" not in page
    assert "return getTradeSideDisplay('open_long')" not in page
    assert "return getTradeSideDisplay('open_short')" in summary_panels
    assert "return getTradeSideDisplay('close_long')" in summary_panels
    assert "return getTradeSideDisplay('close_short')" in summary_panels
    assert "if (side === 'buy') return getTradeSideDisplay('buy');" in summary_panels
    assert "if (side === 'sell') return getTradeSideDisplay('sell');" in summary_panels
    assert "className={clsx('py-2 pr-2 text-center font-semibold', direction.className)}" in summary_panels
    assert "inline-flex min-w-[42px]" not in page
    assert "border-green-500/30 bg-green-500/10 text-green-300" not in page
    assert "border-red-500/30 bg-red-500/10 text-red-300" not in page
    assert "orderQuantity(order)" in summary_panels
    assert "orderFee(order)" in summary_panels
    assert "orderPnl(order)" in summary_panels
    assert "orderModeLabel(orderString(order, ['tdMode']))" in summary_panels
    assert "{order.side || '--'} · {order.status || '--'} · {orderPrice(order)}" not in page
    assert "撤单" not in page
    assert "void addStrategy(strategy)" in page
    assert "openEnableAccountConfirm(strategy, account.accountId)" in page


def test_live_execution_panel_status_filter_defaults_to_running():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")

    assert "const livePanelStatusFilters = [" in page
    filters_segment = page[
        page.index("const livePanelStatusFilters = ["):
        page.index("] as const;", page.index("const livePanelStatusFilters = ["))
    ]
    assert filters_segment.index("key: 'running'") < filters_segment.index("key: 'paused'") < filters_segment.index("key: 'all'")
    assert "label: '运行中'" in filters_segment
    assert "label: '暂停'" in filters_segment
    assert "label: '全部'" in filters_segment

    assert "type LivePanelStatusFilter = (typeof livePanelStatusFilters)[number]['key'];" in page
    assert "function liveDeploymentMatchesFilter(status: string, filter: LivePanelStatusFilter): boolean" in page
    assert "const [livePanelStatusFilter, setLivePanelStatusFilter] = useState<LivePanelStatusFilter>('running');" in page
    assert "const livePanelStatusCounts = useMemo(() => {" in page
    assert "all: currentAccountDeployments.length" in page
    assert "running: currentAccountDeployments.filter((item) => item.deploymentStatus === 'running').length" in page
    assert "paused: currentAccountDeployments.filter((item) => item.deploymentStatus === 'paused').length" in page
    assert "const filteredAccountDeployments = useMemo(" in page
    assert "liveDeploymentMatchesFilter(item.deploymentStatus, livePanelStatusFilter)" in page
    assert 'aria-label="实盘策略状态筛选"' in page
    assert "setLivePanelStatusFilter(item.key)" in page
    assert "livePanelStatusCounts[item.key]" in page
    assert "filteredAccountDeployments.length > 0" in page
    assert "filteredAccountDeployments.map(({ strategy, liveSubscriptionId, deploymentStatus }) => {" in page
    assert "当前筛选下暂无实盘策略" in page


def test_live_execution_panel_exposes_okx_binance_account_tabs():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")
    panel = page[page.index("实盘面板"):]
    account_tabs = panel[:panel.index('aria-label="实盘策略状态筛选"')]

    assert "<LiveAccountTabs" in account_tabs
    assert 'value={selectedAccountId}' in account_tabs
    assert 'onChange={setSelectedAccountId}' in account_tabs
    assert 'ariaLabel="实盘面板账户切换"' in account_tabs
    assert 'className="mb-3 w-full"' in account_tabs
    assert panel.index('ariaLabel="实盘面板账户切换"') < panel.index('aria-label="实盘策略状态筛选"')


def test_live_execution_panel_status_filter_uses_status_light_colors():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")

    assert "function livePanelStatusFilterButtonClass(filter: LivePanelStatusFilter, active: boolean): string" in page
    assert "function livePanelStatusFilterCountClass(filter: LivePanelStatusFilter, active: boolean): string" in page
    assert "livePanelStatusFilterButtonClass(item.key, active)" in page
    assert "livePanelStatusFilterCountClass(item.key, active)" in page
    assert "bg-green-400/[0.12] text-green-100 shadow-[inset_0_0_0_1px_rgba(74,222,128,0.34)]" in page
    assert "bg-yellow-300/[0.12] text-yellow-100 shadow-[inset_0_0_0_1px_rgba(253,224,71,0.34)]" in page
    assert "bg-green-400/[0.16] text-green-100" in page
    assert "bg-yellow-300/[0.16] text-yellow-100" in page
    assert "bg-blue-500/18 text-blue-100" not in page


def test_live_stop_prompts_to_close_positions_before_stopping():
    page = _read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")

    assert "function liveStopPositionKeys(strategy: LiveExecutionStrategy): Set<string>" in page
    assert "function liveStopRelatedContractPositions(" in page
    assert "const relatedPositions = liveStopRelatedContractPositions(strategy, contractPositions);" in page
    assert "title: '确认平仓并停止策略'" in page
    assert "confirmText: '确认平仓并停止'" in page
    assert "cancelText: '仅停止'" not in page
    assert "onCancel: async () =>" not in page
    assert "closeStrategyPositionsThenStop" in page
    assert "const closeSymbols = Array.from(" in page
    assert "for (const symbol of closeSymbols)" in page
    assert "await liveExecutionApi.closePosition(selectedAccountId" in page
    assert "closeAll: true" in page
    assert "confirmLiveRisk: true" in page
    assert "await liveExecutionApi.stopStrategy(strategy.strategyId, { accountId: selectedAccountId });" in page
