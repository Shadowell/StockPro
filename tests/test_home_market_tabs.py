import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "frontend" / "src" / "pages" / "Home.tsx"
MARKET = ROOT / "frontend" / "src" / "pages" / "Market.tsx"
PANEL = ROOT / "frontend" / "src" / "components" / "MarketUniversePanel.tsx"
SECTOR_HEATMAP = ROOT / "frontend" / "src" / "components" / "MarketSectorHeatmap.tsx"
FRONTEND_PACKAGE = ROOT / "frontend" / "package.json"


def test_home_uses_market_universe_summary_without_trade_pair_tabs():
    text = HOME.read_text(encoding="utf-8")

    assert "市场大盘" in text
    assert "variant=\"summary\"" in text
    assert "MarketUniversePanel" in text
    assert "点击榜单标的后进入行情页查看 K 线详情" in text
    assert "MARKET_TABS" not in text
    assert "market-universe-panel" not in text
    assert "24h 区间" not in text


def test_home_has_visible_market_command_shell_and_sector_momentum_panel():
    home = HOME.read_text(encoding="utf-8")
    heatmap = SECTOR_HEATMAP.read_text(encoding="utf-8")

    assert "Market Command" in home
    assert "OKX PUBLIC DATA" in home
    assert "USDT-SWAP" in home
    assert "24H MARKET PULSE" in home
    assert "板块动量" in heatmap
    assert "强弱板块" in heatmap
    assert "topMovingSectors" in heatmap


def test_market_page_does_not_render_full_market_universe_panel_above_chart():
    text = MARKET.read_text(encoding="utf-8")
    panel = PANEL.read_text(encoding="utf-8")

    loading_pos = text.index("{loading && klines.length < MIN_KLINES_TO_RENDER")
    chart_pos = text.index("{/* K线图区域")
    assert "import MarketUniversePanel from '../components/MarketUniversePanel';" not in text
    assert "<MarketUniversePanel" not in text
    assert "marketTypeForUniverseSymbol" not in text
    assert loading_pos < chart_pos
    assert "market-universe-panel flex h-[420px] flex-col" in panel
    assert "min-h-[560px] flex-col" not in panel


def test_market_universe_tabs_have_distinct_symbol_universes_and_filters():
    text = PANEL.read_text(encoding="utf-8")

    assert "MARKET_TAB_SYMBOLS" in text
    assert "futures:" in text
    assert "spot:" in text
    assert ":USDT" in text
    assert "/BTC" in text
    assert "MARKET_TAB_SYMBOLS[activeTab]" in text
    assert "activeTab === 'crypto'" in text
    assert "quoteFromSymbol" in text
    assert "formatQuoteVolume" in text
    assert "formatPrice(t.last, t.quote)" in text


def test_market_universe_tabs_use_requested_display_order():
    text = PANEL.read_text(encoding="utf-8")

    tabs_start = text.index("const MARKET_TABS")
    tabs_end = text.index("const MARKET_TAB_META")
    tabs_block = text[tabs_start:tabs_end]

    labels = ["合约", "现货", "币币", "自选"]
    positions = [tabs_block.index(f"label: '{label}'") for label in labels]
    assert positions == sorted(positions)
    assert "useState<MarketTabKey>('futures')" in text


def test_market_universe_futures_tab_displays_contract_name_and_details():
    text = PANEL.read_text(encoding="utf-8")

    assert "isContractSymbol" in text
    assert "contractDisplayName" in text
    assert "contractDisplayDetails" in text
    assert "contractInstrumentId" in text
    assert "${base}${quote} 永续" in text
    assert "${symbol} · ${quote} 本位 · 线性永续" in text
    assert "activeTab === 'futures' ? '合约' : '币种'" in text
    assert "t.displayName" in text
    assert "t.displayDetails" in text
    assert "SWAP" in text


def test_market_universe_overview_band_summarizes_current_view():
    text = PANEL.read_text(encoding="utf-8")

    assert "MARKET_TAB_META" in text
    assert "HOME_SUMMARY_META" in text
    assert "marketOverview" in text
    assert "当前视图 {marketOverview.total} 个标的" in text
    assert "上涨家数" in text
    assert "下跌 / 平盘" in text
    assert "平均涨跌" in text
    assert "视图成交额" in text
    assert "强弱标的" in text
    assert "marketOverview.strongestLabel" in text
    assert "marketOverview.weakestLabel" in text
    assert "marketOverview.turnoverLeader?.displayName" in text


def test_market_universe_overview_renders_okx_app_style_rankings():
    text = PANEL.read_text(encoding="utf-8")

    assert "HOME_RANKING_LIMIT = 10" in text
    new_listing_start = text.index("const NEW_LISTING_SYMBOLS = [")
    new_listing_end = text.index("] as const;", new_listing_start)
    new_listing_block = text[new_listing_start:new_listing_end]
    assert new_listing_block.count("/USDT:USDT") >= 10
    assert "HOME_RANKING_TABS" in text
    assert "homeRankingKey" in text
    assert "homeRankings" in text
    assert "热门榜" in text
    assert "费率榜" in text
    assert "OKX 资金费率" in text
    assert "fundingItems" in text
    assert "formatFundingRate" in text
    assert "formatAnnualizedFunding" in text
    assert "formatFundingTime" in text
    assert "homeFundingRanking" in text
    assert "b.currentRate - a.currentRate" in text
    assert "当前资金费率" in text
    assert "年化估算" in text
    assert "下次结算" in text
    assert "榜单列表" in text
    assert "选择榜单后查看右侧明细" in text
    assert "xl:grid-cols-[260px_minmax(0,1fr)]" in text
    assert "aria-pressed={activeKey === tab.key}" in text
    assert "新币榜" in text
    assert "TradFi" in text
    assert "涨幅榜" in text
    assert "跌幅榜" in text
    assert "NEW_LISTING_SYMBOLS" in text
    assert "TRADFI_SYMBOLS" in text
    assert "b.change_percent - a.change_percent" in text
    assert "a.change_percent - b.change_percent" in text
    assert "b.quote_volume - a.quote_volume" in text
    assert "HOME_TICKER_SCOPE" in text
    assert "marketApi.getAllTickers(selectedExchange, HOME_TICKER_SCOPE)" in text
    assert "全部 USDT 永续" in text
    assert "variant === 'summary'" in text
    assert "activeHomeRankingItems" in text
    assert "items={activeHomeRankingItems}" in text
    assert "fundingItems={homeFundingRanking}" in text
    assert "HOME_TICKER_RANKING_GRID" in text
    assert "grid-cols-[minmax(300px,1.35fr)_112px_92px_120px_116px_124px_minmax(220px,0.9fr)]" in text
    assert "HOME_TICKER_RANKING_VALUE_CLASS = 'self-start pt-0.5'" in text
    assert 'className={`${HOME_TICKER_RANKING_VALUE_CLASS} font-mono text-sm tabular-nums text-gray-100`}' in text
    assert "HOME_RANKING_TABLE_HEADER_CLASS" in text
    assert "border-y border-slate-500/25 bg-slate-800/80" in text
    assert "font-semibold tracking-[0.04em] text-slate-200" in text
    assert 'className="min-w-0 flex-1 truncate text-sm font-semibold text-gray-100"' in text
    assert 'title={item.displayName}' in text
    assert 'className="shrink-0 rounded border border-amber-500/25' in text
    assert "<span>最新价</span>" in text
    assert "<span>24h 涨跌</span>" in text
    assert '<span className="text-center">24h 走势</span>' in text
    assert "<span>24h 成交量</span>" in text
    assert "<span>24h 成交额</span>" in text
    assert "<span>24h 区间</span>" in text
    assert "<SparklineChart data={item.sparkline} isUp={item.change_percent >= 0} />" in text
    assert "<RangeBar low={item.low} high={item.high} current={item.last} quote={item.quote} />" in text
    assert 'className="h-[560px] overflow-auto"' in text
    assert 'className="flex h-[520px] items-center justify-center px-4 text-center text-sm text-gray-500"' in text


def test_home_summary_fuses_market_overview_and_sentiment_index():
    text = PANEL.read_text(encoding="utf-8")

    assert "HOME_FUNDING_SYMBOLS" in text
    assert "fundingApi.getRates" in text
    assert "function HomeMarketSummaryModule" in text
    assert "overviewCards: ReactNode" in text
    assert "const homeOverviewCards" in text
    assert "overviewCards={homeOverviewCards}" in text
    assert "OKX 市场概览 · 大盘情绪指数" in text
    assert "2xl:grid-cols-[280px_repeat(5,minmax(0,1fr))]" in text
    assert "marketSentiment" in text
    assert "大盘情绪指数" in text
    assert "BitPro 大盘情绪指数" not in text
    assert "聚合市场榜单、广度指标和大盘情绪指数" not in text
    assert "由 OKX ticker 与资金费率聚合计算" not in text
    assert "综合分" in text
    assert "市场热度" in text
    assert "杠杆情绪" in text
    assert "多空拥挤" in text
    assert "风险偏好" in text
    assert "宏观事件" in text
    assert "avgFundingRate" in text
    assert "positiveFundingRatio" in text
    assert "extremeFundingCount" in text
    assert "topTurnoverConcentration" in text
    assert "成交集中 ${formatRatio(marketOverview.topTurnoverConcentration * 100)}" in text
    assert "Top5 占视图成交额" in text
    assert "${marketOverview.gainers}/${marketOverview.total} 上涨" not in text
    assert "newListingTurnoverRatio" in text


def test_home_summary_renders_sector_heatmap_from_full_ticker_scope():
    panel = PANEL.read_text(encoding="utf-8")
    heatmap = SECTOR_HEATMAP.read_text(encoding="utf-8")

    assert "MarketSectorHeatmap" in panel
    assert "sector_key: t.sectorKey ?? t.sector_key ?? 'other'" in panel
    assert "sector_name: t.sectorName ?? t.sector_name ?? '其他'" in panel
    assert "taxonomy_version: t.taxonomyVersion ?? t.taxonomy_version ?? '—'" in panel
    assert "<MarketSectorHeatmap tickers={displayedTickers}" in panel
    assert "板块热度图" in heatmap
    assert "面积 = 标的数" in heatmap
    assert "颜色 = 24h 等权涨跌" in heatmap
    assert "type: 'treemap'" in heatmap
    assert "value: sector.count" in heatmap
    assert "averageChange" in heatmap
    assert "上涨" in heatmap
    assert "下跌" in heatmap
    assert "taxonomyVersion" in heatmap


def test_sector_heatmap_click_opens_full_sector_market_quotes():
    panel = PANEL.read_text(encoding="utf-8")
    heatmap = SECTOR_HEATMAP.read_text(encoding="utf-8")

    assert "onSelectSymbol={onSelectSymbol}" in panel
    assert "chart.on('click'" in heatmap
    assert "setSelectedSectorKey" in heatmap
    assert "板块行情" in heatmap
    assert "selectedSector.members.map" in heatmap
    assert "最新价" in heatmap
    assert "24h 涨跌" in heatmap
    assert "24h 成交额" in heatmap
    assert "24h 最高" in heatmap
    assert "24h 最低" in heatmap
    assert "onSelectSymbol?.(member.symbol)" in heatmap


def test_home_summary_uses_motion_number_flow_and_animated_treemap_updates():
    panel = PANEL.read_text(encoding="utf-8")
    heatmap = SECTOR_HEATMAP.read_text(encoding="utf-8")
    package = json.loads(FRONTEND_PACKAGE.read_text(encoding="utf-8"))

    assert package["dependencies"]["motion"].startswith("^12.")
    assert package["dependencies"]["@number-flow/react"].startswith("^0.6.")
    assert "import NumberFlow from '@number-flow/react';" in panel
    assert "from 'motion/react'" in panel
    assert "<NumberFlow value={sentiment.score}" in panel
    assert "<NumberFlow value={marketOverview.gainers}" in panel
    assert "useReducedMotion" in panel
    assert "animationDurationUpdate" in heatmap
    assert "animationEasingUpdate: 'cubicOut'" in heatmap
    assert "universalTransition" in heatmap
    assert "id: sector.key" in heatmap
    assert "prefersReducedMotion" in heatmap


def test_market_universe_summary_no_longer_renders_two_column_heat_panel():
    text = PANEL.read_text(encoding="utf-8")

    assert "gainerRanking" in text
    assert "loserRanking" in text
    assert "heatRanking" not in text
    assert "热度榜" not in text
    assert "items={marketOverview.heatRanking}" not in text
    assert "items.map((item, index)" in text


def test_market_universe_category_tabs_only_use_okx_backed_filters():
    text = PANEL.read_text(encoding="utf-8")

    assert "{ key: 'all', label: '全部' }" in text
    assert "{ key: 'top', label: '热门' }" in text
    assert "CATEGORY_SYMBOLS" not in text
    assert "{ key: 'defi'" not in text
    assert "{ key: 'layer1'" not in text
    assert "{ key: 'layer2'" not in text
    assert "{ key: 'meme'" not in text
    assert "'defi':" not in text
    assert "'layer1':" not in text
    assert "'layer2':" not in text
    assert "'meme':" not in text
    assert "{ key: 'ai', label: 'AI' }" not in text
    assert "quote_volume" in text


def test_market_universe_realtime_badge_omits_connected_wifi_icon():
    text = PANEL.read_text(encoding="utf-8")

    assert "Wifi," not in text
    assert "<Wifi className" not in text
    assert "WifiOff" in text
    assert "relative flex h-1.5 w-1.5" in text
    assert "{selectedExchange.toUpperCase()} · 实时行情" in text


def test_market_universe_favorite_click_is_local_and_does_not_refetch_market_data():
    text = PANEL.read_text(encoding="utf-8")

    favorite_button_start = text.index("{/* 收藏星 */")
    favorite_button_end = text.index("<Star", favorite_button_start)
    favorite_button = text[favorite_button_start:favorite_button_end]
    map_ticker_start = text.index("const mapTickerData = useCallback")
    requested_symbols_start = text.index("const requestedSymbols = useMemo")
    map_ticker_block = text[map_ticker_start:requested_symbols_start]
    requested_symbols_end = text.index("const fetchAllTickers", requested_symbols_start)
    requested_symbols_block = text[requested_symbols_start:requested_symbols_end]

    assert 'type="button"' in favorite_button
    assert "e.preventDefault();" in favorite_button
    assert "e.stopPropagation();" in favorite_button
    assert "toggleFavorite(t.symbol)" in favorite_button
    assert "isFavorite: favorites.has(t.symbol)" not in map_ticker_block
    assert "}, [favorites]);" not in map_ticker_block
    assert "const favoritesKey = useMemo" in text
    assert "activeTab === 'favorites' ? Array.from(favorites)" in text
    assert "), [activeTab, favorites]);" in text
    assert "favoritesKey ? favoritesKey.split" in requested_symbols_block
    assert "}, [activeTab, favoritesKey, isSummary]);" in requested_symbols_block
