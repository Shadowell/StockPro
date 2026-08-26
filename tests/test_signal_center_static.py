from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _nav_entry(path: str, icon: str, label: str) -> str:
    return f"{{ path: '{path}', icon: {icon}, label: '{label}',"


def test_signal_center_route_is_registered_but_sidebar_entry_is_hidden():
    app = _read("frontend/src/App.tsx")
    layout = _read("frontend/src/components/MainLayout.tsx")

    assert "const SignalCenter = lazy(() => import('./pages/SignalCenter'))" in app
    assert 'path="signals" element={<SignalCenter />}' in app
    assert _nav_entry("/signals", "Send", "信号") not in layout
    assert layout.index(_nav_entry("/live-real", "Rocket", "实盘")) < layout.index(
        _nav_entry("/watch", "ScanLine", "盯盘")
    ) < layout.index(_nav_entry("/monitor", "Eye", "监控")) < layout.index(
        _nav_entry("/data", "Database", "数据")
    )


def test_signal_center_frontend_api_uses_v2_signal_endpoints():
    client = _read("frontend/src/api/client.ts")

    assert "export const signalCenterApi" in client
    assert "totalPnl?: number | null" in client
    assert "returnPct?: number | null" in client
    assert "manualApprovalRequired: boolean" in client
    assert "getReq('/signals'" in client
    assert "postReq(`/signals/${signalId}/approve`" in client
    assert "postReq(`/signals/${signalId}/cancel`" in client
    assert "postReq(`/signals/${signalId}/retry`" in client
    assert "getReq('/signal-channels')" in client
    assert "postReq('/signal-channels'" in client
    assert "putReq(`/signal-channels/${channelId}`" in client
    assert "deleteReq(`/signal-channels/${channelId}`)" in client
    assert "postReq(`/signal-channels/${channelId}/test`" in client
    assert "export interface SignalChannelTestInput" in client
    assert "export interface SignalChannelTestResult" in client
    assert "responseBody?: string | null" in client
    assert "{ send: false, ...payload }" in client
    assert "listSignalStrategies" in client
    assert "getReq('/signal-strategies')" in client
    assert "setStrategySignalEnabled" in client
    assert "putReq(`/signal-strategies/${strategyId}`" in client
    assert "updateSignalStrategySettings" in client
    assert "updateChannel" in client


def test_signal_center_page_exposes_manual_approval_and_channel_controls():
    page = _read("frontend/src/pages/SignalCenter.tsx")

    assert "信号中心" in page
    assert '<h1 className="text-2xl font-bold tracking-normal">信号中心</h1>' in page
    assert "text-3xl font-bold tracking-normal" not in page
    assert "flex h-9 w-9 items-center justify-center" in page
    assert "flex h-11 w-11 items-center justify-center" not in page
    assert '<p className="mt-1 text-xs text-gray-500">' in page
    assert "策略选择" in page
    assert "formatSignedUsd" in page
    assert "formatSignedPct" in page
    assert "strategySearch" in page
    assert "搜索策略名称 / ID / 交易对" in page
    assert "grid min-w-0 gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1fr)]" in page
    assert "xl:grid-cols-[minmax(0,1fr)_minmax(420px,0.9fr)]" not in page
    assert "xl:grid-cols-[minmax(110px,0.75fr)_minmax(210px,1.45fr)_minmax(120px,0.85fr)_70px_70px_82px]" in page
    assert "保存后在右侧启用" in page
    assert "保存后在右侧通道卡片启用" not in page
    assert 'id="signal-channel-config"' in page
    assert "scroll-mt-6 min-w-0 overflow-hidden rounded-xl border border-crypto-border bg-crypto-card" in page
    assert "h-9 min-w-0 w-full truncate rounded-lg" in page
    assert "grid max-w-[980px] gap-3" not in page
    assert "mt-3 grid max-w-[190px]" not in page
    assert "grid min-h-0 gap-5 xl:grid-cols-[minmax(320px,360px)_minmax(420px,0.9fr)_minmax(420px,1fr)]" in page
    assert "flex h-[680px] min-h-0 flex-col rounded-xl" in page
    assert "min-h-0 flex-1 space-y-2 overflow-y-auto pr-1" in page
    assert "2xl:grid-cols-[340px_minmax(0,1fr)_380px]" not in page
    assert page.index("<h2 className=\"truncate text-base font-semibold\">通道配置</h2>") < page.index(
        "<h2 className=\"text-lg font-semibold\">策略选择</h2>"
    )
    assert page.index("<h2 className=\"truncate text-base font-semibold\">OKX 信号通道</h2>") < page.index(
        "<h2 className=\"text-lg font-semibold\">策略选择</h2>"
    )
    assert "candidateStrategyId" in page
    assert "selectCandidateStrategy" in page
    assert "startStrategyIntoMiddleList" in page
    assert "startSelectedCandidateStrategy" not in page
    assert "待启动策略" not in page
    assert "待添加策略" not in page
    assert "点击策略只切换查看；点击启动加入信号策略列表" in page
    assert "策略已启动信号生成，并加入信号策略列表" in page
    assert "已切换到信号策略列表，可查看策略信号和绑定通道" in page
    assert "onClick={() => void startStrategyIntoMiddleList(strategy)}" in page
    assert "启动中" in page
    assert "已启动" in page
    assert "添加到中间列表" not in page
    assert "已在中间列表" not in page
    assert "先选中策略，再点击添加进入中间策略列表" not in page
    assert "selectedStrategyIds" in page
    assert "restoredSignalStrategyIds" in page
    assert "const restored = strategies" in page
    assert "return strategies.find((strategy) => strategy.signalEnabled)?.strategyId || null" in page
    assert "return Array.from(new Set([...kept, ...restored]))" in page
    assert "addStrategyToMiddleList" in page
    assert "信号策略列表" in page
    assert "已添加策略" in page
    left_list_start = page.index("filteredSignalStrategies.map")
    left_list_end = page.index("<main className=\"min-w-0 space-y-4\">")
    left_list = page[left_list_start:left_list_end]
    assert "onClick={() => selectCandidateStrategy(strategy.strategyId)}" in left_list
    assert "onClick={() => void startStrategyIntoMiddleList(strategy)}" in left_list
    assert "onClick={() => selectStrategy(strategy.strategyId)}" not in left_list
    middle_list_start = page.index("selectedStrategies.map")
    assert page.index("onClick={() => selectStrategy(strategy.strategyId)}", middle_list_start) > middle_list_start
    assert page.index("信号策略列表") < page.index("使用的通道 Bot", middle_list_start) < page.index(
        "策略信号",
        middle_list_start,
    )
    assert "{active && (" in page
    assert "border-t border-blue-500/20 pt-2.5" in page
    assert "信号产出" in page
    assert "人工确认" in page
    assert "新信号默认自动发送到可用 Bot" in page
    assert "新信号需要人工确认后发送" in page
    assert "aria-label={strategy.manualApprovalRequired ? '关闭人工确认' : '开启人工确认'}" in page
    assert "strategy.manualApprovalRequired ? 'ON' : 'OFF'" in page
    assert page.count("inline-flex min-h-10 items-center gap-2 rounded-lg border") >= 2
    assert page.count("relative inline-flex h-7 w-16 shrink-0 items-center rounded-full border p-0.5") >= 2
    assert "absolute top-1/2 -translate-y-1/2 text-[12px] font-bold leading-none tracking-wide" in page
    assert "relative z-10 h-6 w-6 rounded-full shadow-sm transition-transform" in page
    assert "left-2 text-green-100" in page
    assert "right-2 text-gray-300" in page
    assert "translate-x-9 bg-green-200" in page
    assert "absolute bottom-0 left-0 w-full text-center" not in page
    assert "relative h-8 w-10 shrink-0" not in page
    assert "inline-flex items-center gap-1.5" in page
    assert "inline-grid min-h-10 grid-cols-[auto_auto]" not in page
    assert "justify-self-center text-[10px] font-bold leading-none tracking-wide" not in page
    assert "inline-flex h-5 min-w-8 items-center justify-center rounded-full" not in page
    assert "inline-flex h-5 w-10 shrink-0 items-center rounded-full border p-0.5" not in page
    assert "border-slate-500/45 bg-slate-500/10 text-gray-300 hover:bg-slate-500/15" in page
    assert "translate-x-0 bg-gray-300" in page
    assert "translate-x-5 bg-amber-200" not in page
    assert "translate-x-[13px]" not in page
    assert "新信号将进入待确认列表" not in page
    assert "新信号将自动发送到可用通道 Bot" not in page
    assert "onClick={() => void toggleStrategyEnabled(strategy)}" in page
    assert "onClick={() => void toggleStrategyManualApproval(strategy)}" in page
    assert "aria-label={strategy.signalEnabled ? '关闭信号产出' : '开启信号产出'}" in page
    assert "strategy.signalEnabled ? 'ON' : 'OFF'" in page
    assert "onClick={() => void toggleStrategyEnabled(selectedStrategy)}" not in page
    assert "请选择中间策略查看通道 Bot" not in page
    assert "当前查看策略" not in page
    assert "当前策略</div>" not in page
    assert "grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]" not in page
    assert "xl:col-start-2 xl:row-span-2" not in page
    assert "strategyEnabledFilters" in page
    assert "strategyEnabledFilter, setStrategyEnabledFilter] = useState<StrategyEnabledFilter>('enabled')" in page
    assert "strategySortControls" in page
    assert "strategyReturnSort" in page
    assert "strategySortDirectionFor" in page
    assert "nextStrategyReturnSort" in page
    assert "StrategySortArrow" in page
    assert "所有" in page
    assert "已启用" in page
    assert "未启用" in page
    assert "收益高→低" not in page
    assert "收益低→高" not in page
    assert "收益率" in page
    assert "inline-flex h-11 w-full items-center gap-1 rounded-xl" in page
    assert "SELECTED_SEGMENT_CLASS" in page
    assert "rightReturn - leftReturn" in page
    assert "leftReturn - rightReturn" in page
    assert "leftReturn == null" in page
    assert "filteredSignalStrategies.map" in page
    assert "没有匹配的策略" in page
    assert "启用信号" in page
    assert "关闭信号产出" in page
    assert "开启信号产出" in page
    assert "h-8 min-w-[116px] shrink-0" not in page
    assert "whitespace-nowrap" not in page
    assert "策略信号" in page
    assert "compactSignalRow" in page
    assert "产生时间" in page
    assert "formatSignalTime(signal.createdAt)" in page
    assert "grid gap-3 xl:grid-cols-[minmax(0,1fr)_auto]" in page
    assert "触发价格" not in page
    assert "点击信号策略列表中的策略后展示策略信号" in page
    assert "getSignalActionDisplay" in page
    assert "const actionDisplay = getSignalActionDisplay(signal.action)" in page
    assert "{actionDisplay.label}" in page
    assert "actionDisplay.className" in page
    signal_meta_start = page.index("<div className=\"mb-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1\">")
    signal_action_span = "className={clsx('shrink-0 text-sm font-semibold', actionDisplay.className)}"
    signal_symbol_span = '<span className="min-w-0 truncate text-sm font-semibold text-gray-50">{signal.okxInstId}</span>'
    assert page.index(signal_action_span, signal_meta_start) < page.index(signal_symbol_span, signal_meta_start)
    assert 'text-blue-200">{actionLabel[signal.action] || signal.action}</span>' not in page
    assert "Braces" in page
    assert "relative rounded-xl border border-crypto-border bg-crypto-bg/95 p-3" in page
    assert 'className="group relative"' in page
    assert "inline-flex h-8 cursor-pointer list-none items-center gap-1 rounded-lg" in page
    assert '<Braces className="h-3.5 w-3.5" />' in page
    assert "flex max-w-[220px] shrink-0 flex-wrap items-center justify-start gap-2 xl:justify-end" in page
    assert "使用的通道 Bot" in page
    assert "可用 {strategyChannels.length}/{enabledChannels.length} · 已选 {selectedChannelIds.length}" in page
    assert "botPickerStrategyId" in page
    assert "pendingBotChannelId" in page
    assert "toggleBotPicker" in page
    assert "bindPendingBotChannel" in page
    assert "aria-expanded={pickerOpen}" in page
    assert "选择 Bot 后点击绑定" in page
    assert "选择一个 Bot" in page
    assert "当前策略已选择全部可用 Bot。" in page
    assert "暂不可选 Bot，请先创建并启用通道。" not in page
    assert "暂无可选 Bot，请先创建并启用通道。" in page
    assert "jumpToCreateChannel" in page
    assert "setForm(emptyChannelForm())" in page
    assert "document.getElementById('signal-channel-config')?.scrollIntoView" in page
    assert "+ 新增 Bot" in page
    assert "rounded-lg border border-crypto-border bg-crypto-card/70 p-3" not in page
    assert "SELECTED_SEGMENT_BORDER_CLASS" in page
    assert 'type="checkbox"' not in page
    assert "aria-label={`${channel.name} ${bound ? '已绑定' : '未绑定'}`}" in page
    assert "animate-pulse bg-green-400" in page
    assert "bg-red-400 shadow-[0_0_0_4px_rgba(248,113,113,0.12),0_0_12px_rgba(248,113,113,0.45)]" in page
    assert "Boards {strategyChannels.length}" not in page
    assert "请选择中间策略查看通道 Boards" not in page
    assert "OKX 信号通道" in page
    assert "min-w-0 overflow-hidden rounded-lg border border-crypto-border bg-crypto-bg p-2.5" in page
    assert "min-w-0 truncate text-sm font-semibold text-gray-100" in page
    assert "grid min-w-0 items-center gap-1.5 text-[11px] text-gray-500 sm:grid-cols-[minmax(160px,1.35fr)_minmax(96px,0.8fr)_64px_72px_minmax(72px,0.65fr)]" in page
    assert "min-w-0 truncate rounded-md bg-white/[0.03] px-1.5 py-1" in page
    assert "grid grid-cols-2 gap-1" not in page
    assert "mt-2 grid min-w-0 grid-cols-3 gap-1.5" in page
    assert "inline-flex h-8 min-w-0 items-center justify-center gap-1 rounded-md" in page
    assert "border-sky-400/60 bg-sky-500/20" in page
    assert "border-amber-400/60 bg-amber-500/20" in page
    assert "border-red-400/60 bg-red-500/20" in page
    assert "hover:bg-sky-500/30" in page
    assert "hover:bg-amber-500/30" in page
    assert "hover:bg-red-500/30" in page
    assert 'aria-label="测试通道"' in page
    assert "待确认" in page
    assert "{ key: 'all', label: '全部' }" in page
    assert "useState('all')" in page
    assert "status: activeStatus === 'all' ? undefined : activeStatus" in page
    assert "当前策略暂无信号，只有启用后的新模拟成交会生成信号。" in page
    assert "发送到 OKX" in page
    assert "重新推送" in page
    assert "取消信号" in page
    assert "通道配置" in page
    assert "测试通道" in page
    assert "ChannelEnabledSwitch" not in page
    assert "toggleChannelEnabled" in page
    assert "通道配置已保存，请在右侧 OKX 信号通道卡片启用" in page
    assert "通道已启用" not in page
    assert "通道已停用" not in page
    assert "enabled: false" in page
    assert "enabled: form.enabled" not in page
    assert "当前 Bot 可接收人工确认后的信号" not in page
    assert "关闭后不会向该 Bot 推送信号" not in page
    assert "role=\"switch\"" in page
    assert "aria-checked={channel.enabled}" in page
    assert "aria-label={channel.enabled ? '停用通道' : '启用通道'}" in page
    assert "group inline-flex h-7 w-12 shrink-0 items-center rounded-full" in page
    assert "channel.enabled ? '已启用，点击停用' : '已停用，点击启用'" in page
    assert "translate-x-5 bg-green-300" in page
    assert "translate-x-0 bg-gray-500 group-hover:bg-gray-400" in page
    assert "group flex h-7 cursor-pointer" not in page
    assert "relative inline-flex h-3.5 w-6" not in page
    assert "h-2.5 w-2.5 rounded-full" not in page
    assert "translate-x-[10px]" not in page
    assert "relative inline-flex h-7 w-12" not in page
    assert 'aria-label="启用通道"' not in page
    assert "h-4 w-4 rounded border-crypto-border" not in page
    assert "ChannelActionSwitches" not in page
    assert "getTradeSideDisplay" in page
    assert "channelActionSideMap" in page
    assert "channelActionSwitchToneStyles" not in page
    assert "grid min-w-0 flex-1 grid-cols-2 gap-1.5 sm:grid-cols-4" not in page
    assert "allChannelActionKeys" in page
    assert "allowedActions: allChannelActionKeys" in page
    assert "defaultAllowedActions" not in page
    assert "form.allowedActions" not in page
    assert "editForm.allowedActions" not in page
    assert "splitCsv" not in page
    assert "flex h-3 w-5 shrink-0 items-center rounded-full" not in page
    assert "h-2 w-2 rounded-full" not in page
    assert "translate-x-[8px]" not in page
    assert "text-lg font-bold" not in page
    assert "允许动作" not in page
    assert "允许多头入场信号" not in page
    assert "允许空头入场信号" not in page
    assert "允许多头离场信号" not in page
    assert "允许空头离场信号" not in page
    assert "option.description" not in page
    assert "const ActionIcon" not in page
    assert "LogIn" not in page
    assert "LogOut" not in page
    assert "至少一项" not in page
    assert 'placeholder="允许 action"' not in page
    assert "修改" in page
    assert "保存修改" in page
    assert "删除" in page
    assert "确认删除" in page
    assert "ChannelTextInput" in page
    assert "grid min-w-0 gap-2 md:grid-cols-2 xl:grid-cols-[minmax(110px,0.75fr)_minmax(210px,1.45fr)_minmax(120px,0.85fr)_70px_70px_82px]" in page
    assert "grid max-w-[980px] gap-3 lg:grid-cols-[220px_minmax(300px,420px)_220px]" not in page
    assert "grid max-w-[190px] gap-2 lg:grid-cols-[88px_88px]" not in page
    assert "grid max-w-[208px] gap-2 lg:grid-cols-[100px_100px]" in page
    assert "inline-flex h-9 min-w-0 items-center justify-center rounded-lg" in page
    assert "用于在 BitPro 内识别这个 OKX 信号通道" in page
    assert "从 OKX App Signal Bot 页面复制触发地址" in page
    assert "从 OKX 自定义 JSON 的 signalToken 字段复制" in page
    assert "限制单次入场信号建议使用的保证金" in page
    assert "OKX 接收信号允许的最大延迟秒数" in page
    assert "defaultMaxMarginUsdt = '10'" in page
    assert "defaultMaxLagSec = '30'" in page
    assert "defaultOkxSignalWebhookUrl = 'https://www.okx.com/algo/signal/trigger'" in page
    assert "webhookUrl: defaultOkxSignalWebhookUrl" in page
    assert "maskedSignalTokenPlaceholder = '**********'" in page
    assert "webhookUrl: channel.webhookUrl || channel.maskedWebhookUrl || ''" in page
    assert "signalToken: channel.maskedSignalToken ? maskedSignalTokenPlaceholder : ''" in page
    assert "type?: InputHTMLAttributes<HTMLInputElement>['type'];" in page
    assert 'type="password"' in page
    assert "channel.webhookUrl || channel.maskedWebhookUrl" in page
    assert "webhookUrl === channel.maskedWebhookUrl" in page
    assert "webhookUrl === channel.webhookUrl" in page
    assert "signalToken === maskedSignalTokenPlaceholder" in page
    assert "signalToken === channel.maskedSignalToken" in page
    assert "默认 10 USDT" in page
    assert "默认 30 秒" in page
    assert "Webhook 地址" in page
    assert "信号令牌" in page
    assert "有效秒数" in page
    assert "当前地址明文展示" in page
    assert "当前令牌以隐藏状态展示" in page
    assert "placeholder={maskedSignalTokenPlaceholder}" in page
    assert "当前地址以遮罩形式展示" not in page
    assert "当前令牌显示为 *****" not in page
    assert "新 webhook 地址；留空保留当前值" not in page
    assert "新 signalToken；留空保留当前值" not in page
    assert 'placeholder="OKX webhook URL"' not in page
    assert 'placeholder="maxLag"' not in page
    assert "允许策略 ID，逗号分隔；留空代表全策略通道" not in page
    assert "允许 symbol，逗号分隔" not in page
    assert "测试通过：payload 已生成，未真实发送" in page
    assert "channelTestResults" in page
    assert "testDialogChannelId" in page
    assert "真实发送会推送到 OKX Signal Bot" in page
    assert "compactText(result.responseBody)" in page
    assert "真实测试发送失败：${responseStatus}${responseSuffix}" in page
    assert "DOGE-USDT-SWAP" in page
    assert "investmentType=margin" in page
    assert "amount=0.1 USDT" in page
    assert "真实发送测试" in page
    assert "signalCenterApi.testChannel(channelId, {" in page
    assert "editingChannelId" in page
    assert "deleteConfirmChannelId" in page
    assert "启用策略" in page
    assert "收益率" in page
    assert "收益金额" in page
    assert "会产出信号" not in page
    assert "不产出信号" not in page
    assert "strategy.returnPct" in page
    assert "strategy.totalPnl" in page
    middle_summary_end = page.index("{active && (", middle_list_start)
    middle_summary = page[middle_list_start:middle_summary_end]
    assert "getStrategyChannels(strategy.strategyId)" not in middle_summary
    assert "strategyAvailableChannels.map((channel)" not in middle_summary
    assert "暂无可用通道 Bot" not in middle_summary
    assert "使用的通道 Bot" not in middle_summary
    assert "formatSignedUsd(strategy.totalPnl)" not in middle_summary
    assert "formatSignedPct(strategy.returnPct)" not in middle_summary
    assert "收益金额" not in middle_summary
    assert "收益率" not in middle_summary
    assert "selectedStrategy.returnPct" not in page
    assert "selectedStrategy.totalPnl" not in page
    assert '<div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">' not in page
    assert "点击启动加入信号策略列表并按策略设置产出信号" in page
    assert "从左侧选中策略并点击启动后会加入这里" in page
    assert "从左侧选中策略并点击添加后会加入这里" not in page
    assert "全策略通道" in page
    assert "仅此策略" in page
    assert "{allStrategy ? '仅此策略' : explicit ? '移除' : '绑定'}" in page
    assert "未绑定" in page
    assert "unboundChannelStrategyId = -1" in page
    assert "isUnboundChannel" in page
    assert "visibleChannelStrategyIds" in page
    assert "formatChannelStrategyScope" in page
    assert "allowedStrategyIds.length === 1 && channel.allowedStrategyIds[0] === unboundChannelStrategyId" in page
    assert "nextIds.length > 0 ? nextIds : [unboundChannelStrategyId]" in page
    assert "已解除该策略与通道的绑定" in page
    assert "未绑定策略" in page
    assert "设为仅此策略" not in page
    assert "添加到策略" not in page
    assert "不能移除最后一个显式绑定策略" not in page
    assert "signalCenterApi.approveSignal" in page
    assert "signalCenterApi.retrySignal" in page
    assert "signalCenterApi.cancelSignal" in page
    assert "signalCenterApi.testChannel" in page
    assert "signalCenterApi.listSignalStrategies" in page
    assert "signalCenterApi.setStrategySignalEnabled" in page
    assert "signalCenterApi.updateSignalStrategySettings" in page
    assert "signalCenterApi.updateChannel" in page
    assert "signalCenterApi.deleteChannel" in page
    assert "strategyId: selectedStrategyId" in page
    assert "searchParams.get('strategy_id')" in page


def test_okx_signal_bot_json_format_doc_is_available():
    readme = _read("README.md")
    doc = _read("docs/integrations/okx-signal-bot-json-format.md")

    assert "docs/integrations/okx-signal-bot-json-format.md" in readme
    assert "OKX Signal Bot 自定义 JSON 格式" in doc
    assert '"action": "ENTER_LONG"' in doc
    assert '"investmentType": "percentage_balance"' in doc
    assert '"investmentType": "percentage_position"' in doc
    assert '"maxLag": "30"' in doc
    assert "最大保证金" in doc
    assert "默认 `10` USDT" in doc
