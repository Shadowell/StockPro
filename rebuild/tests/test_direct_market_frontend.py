from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_bitpro_market_page_uses_a_share_controls_and_renders_short_real_history():
    market = (ROOT / "frontend/src/pages/Market.tsx").read_text(encoding="utf-8")
    search = (ROOT / "frontend/src/components/SymbolSearch.tsx").read_text(encoding="utf-8")
    store = (ROOT / "frontend/src/stores/useStore.ts").read_text(encoding="utf-8")

    assert "const MIN_KLINES_TO_RENDER = 1" in market
    assert "{ value: 'stock', label: '股票' }" in market
    assert "T+1 · 100股整手" in market
    assert "BTC/USDT" not in market + search + store
    assert "资金费率" not in market
    assert "暂无 K 线数据" in market
    assert "K线数据加载中" not in market


def test_home_sentiment_uses_a_share_breadth_and_never_fetches_funding():
    panel = (ROOT / "frontend/src/components/MarketUniversePanel.tsx").read_text(encoding="utf-8")
    assert "fundingApi.getRates" not in panel
    assert "label: '成交活跃'" in panel
    assert "label: '涨跌广度'" in panel
    assert "label: '交易日证据'" in panel
    assert "资金费率暂无" not in panel
