from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_strategy_api_exposes_paginated_list_client():
    client = _read("frontend/src/api/client.ts")

    assert "export interface StrategyPageResponse" in client
    assert "getPage: (params:" in client
    assert "getReq<StrategyPageResponse>('/strategies'" in client
    assert "page: params.page" in client
    assert "perPage: params.perPage" in client


def test_strategy_page_uses_server_pagination_for_strategy_library():
    page = _read("frontend/src/pages/Strategy.tsx")

    assert "const STRATEGY_PAGE_SIZE = 18;" in page
    assert "strategyApi.getPage({" in page
    assert "page: strategyPage" in page
    assert "perPage: STRATEGY_PAGE_SIZE" in page
    assert "status: statusFilter" in page
    assert "assetClass: assetFilter" in page
    assert "timeframe: strategyTimeframeFilter" in page
    assert "capital: strategyCapitalFilter" in page
    assert "search: normalizedSearchQuery" in page
    assert "策略分页" in page
    assert "filteredStrategies.map" not in page


def test_strategy_page_supports_console_style_filters_and_search():
    page = _read("frontend/src/pages/Strategy.tsx")

    assert "type StrategyTypeFilter = 'all' | 'cta' | 'martingale' | 'ai' | 'market_making';" in page
    assert "type StrategyTimeframeFilter = 'all' | '1m' | '5m' | '15m' | '30m' | '1h' | '4h' | '12h' | '1d';" in page
    assert "type StrategyCapitalFilter = 'all' | '100U' | '1000U';" in page
    assert "{ value: '10000U', label: '10000U' }" not in page
    assert "STRATEGY_TYPE_FILTERS" in page
    assert "{ value: 'market_making', label: '做市' }" in page
    assert "STRATEGY_TIMEFRAME_FILTERS" in page
    assert "STRATEGY_CAPITAL_FILTERS" in page
    assert "inline-flex h-11 items-center rounded-xl border border-crypto-border bg-crypto-card p-1" in page
    assert "inline-flex h-11 items-center rounded-xl border border-crypto-border bg-crypto-card/80 p-1" in page
    assert "inline-flex min-h-11 max-w-full flex-wrap items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card/80 p-1" in page
    assert "bg-crypto-card/45" not in page
    assert "border-t border-crypto-border/70 pt-3" not in page
    assert "strategyTimeframeCounts[option.value]" in page
    assert "strategyCapitalCounts[option.value]" in page
    assert "strategyTypeCounts[option.value]" in page
    assert '<span className="sr-only">搜索策略</span>' in page
    assert 'type="search"' in page
    assert 'placeholder="搜索策略、标的、周期..."' in page
    assert "搜索策略名 / 标的 / 周期 / 类型" not in page
    assert "setStrategyTimeframeFilter(option.value)" in page
    assert "setStrategyCapitalFilter(option.value)" in page
    assert "setStrategyTypeFilter(option.value)" in page
    assert page.index("ASSET_FILTERS.map") < page.index("STATUS_FILTERS.map")
    assert page.index("STATUS_FILTERS.map") < page.index("STRATEGY_TYPE_FILTERS.map")
    assert page.index("STRATEGY_TYPE_FILTERS.map") < page.index("STRATEGY_TIMEFRAME_FILTERS.map")
    assert page.index("STRATEGY_TIMEFRAME_FILTERS.map") < page.index("STRATEGY_CAPITAL_FILTERS.map")


def test_strategy_page_card_grid_uses_four_desktop_columns():
    page = _read("frontend/src/pages/Strategy.tsx")

    assert "grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4" in page
    assert "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4" in page
    assert "lg:grid-cols-3" not in page


def test_strategy_page_tab_switcher_is_content_width():
    page = _read("frontend/src/pages/Strategy.tsx")

    tab_section = page[page.index("{/* Tab + 搜索 */}"):page.index("{listTab === 'my' && (")]

    assert "inline-flex w-fit items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card p-1" in tab_section
    assert "flex items-center gap-1 bg-crypto-card border border-crypto-border rounded-xl p-1" not in tab_section


def test_strategy_header_ai_action_is_framed_button():
    page = _read("frontend/src/pages/Strategy.tsx")

    ai_button_start = page.index("<button onClick={() => setShowAiGen(!showAiGen)}")
    ai_button_end = page.index("<button onClick={() => handleCreateFromTemplate", ai_button_start)
    ai_button = page[ai_button_start:ai_button_end]

    assert "inline-flex h-11 items-center gap-2 rounded-xl border px-4 text-sm font-semibold transition-colors" in ai_button
    assert "border-purple-500/30 bg-purple-500/[0.12] text-purple-200" in ai_button
    assert "hover:bg-purple-500/[0.18]" in ai_button
    assert "bg-crypto-card text-gray-300" not in ai_button
    assert "border-transparent" not in ai_button
