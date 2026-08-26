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
