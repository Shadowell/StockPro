from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.market.repository import MarketRepository  # noqa: E402


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, query, params=()):
        self.query = str(query)
        self.params = params

    def fetchall(self):
        return self.rows

    def __enter__(self): return self
    def __exit__(self, *_args): return False


class _Connection:
    def __init__(self, rows):
        self.cursor_value = _Cursor(rows)

    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def set_session(self, **_kwargs): return None
    def cursor(self): return self.cursor_value


def test_daily_kline_payload_exposes_real_window_and_amount_metadata() -> None:
    from datetime import date

    connection = _Connection([
        (date(2026, 8, 27), 10.5, 12.0, 10.0, 11.5, 1200, 25_000),
        (date(2026, 8, 26), 10.0, 11.0, 9.0, 10.5, 1000, 20_000),
    ])
    repo = MarketRepository("postgresql://example.invalid/db", connection_factory=lambda *_a, **_k: connection)

    payload = repo.get_klines_with_status("SSE", "600001.SH", "1d", 500)

    assert payload["row_count"] == 2
    assert payload["from_date"] == "2026-08-26"
    assert payload["to_date"] == "2026-08-27"
    assert payload["latest_trade_date"] == "2026-08-27"
    assert payload["provider_source"] == "PostgreSQL stock_history"
    assert payload["items"][-1]["quote_volume"] == 25_000


def test_index_universe_uses_persisted_index_cache_without_stock_fallback() -> None:
    class Cursor:
        def __init__(self): self.query = ""
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def execute(self, query, params=()): self.query = str(query); self.params = params
        def fetchone(self): return ("market_indices_realtime",)
        def fetchall(self):
            if "market_indices_realtime" in self.query:
                return [("000001.SH", "上证指数"), ("399001.SZ", "深证成指")]
            return []

    class Connection:
        def __init__(self): self.value = Cursor()
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def set_session(self, **_kwargs): return None
        def cursor(self): return self.value

    repo = MarketRepository("postgresql://example.invalid/db", connection_factory=lambda *_a, **_k: Connection())

    items = repo.list_instruments("index", 100)

    assert [item["symbol"] for item in items] == ["000001.SH", "399001.SZ"]
    assert all(item["asset_class"] == "index" for item in items)
    assert all(item["board"] == "指数" for item in items)


def test_market_symbol_normalization_accepts_prefixed_indices_and_bse_920_codes() -> None:
    assert MarketRepository._canonical_symbol("SH000001") == "000001.SH"
    assert MarketRepository._canonical_symbol("SZ399001") == "399001.SZ"
    assert MarketRepository._canonical_symbol("920000") == "920000.BJ"
    assert MarketRepository._canonical_symbol("900901") == "900901.SH"


def test_market_and_data_frontends_keep_asset_types_and_full_coverage_honest() -> None:
    market = (ROOT / "frontend/src/pages/Market.tsx").read_text(encoding="utf-8")
    orderbook = (ROOT / "frontend/src/components/OrderBookChart.tsx").read_text(encoding="utf-8")
    data_manager = (ROOT / "frontend/src/pages/DataManager.tsx").read_text(encoding="utf-8")
    symbol_search = (ROOT / "frontend/src/components/SymbolSearch.tsx").read_text(encoding="utf-8")
    sync_endpoint = (ROOT / "backend/app/api/v2/endpoints/sync.py").read_text(encoding="utf-8")

    assert "useState<string>(() => defaultMarketTimeframe())" in market
    assert "allSymbols.includes(selectedSymbol)" in market
    assert "setSelectedSymbol('')" in market
    assert "marketType === 'index'" in market
    assert "指数点位 · 不可交易" in market
    assert "暂无订单簿深度，未计算价差" in orderbook
    assert "ETF 暂无真实标的" in symbol_search
    assert "disabled={fullList.length === 0}" in symbol_search
    assert "dataAssetsApi.getAssets()" in data_manager
    assert "DATA_PAGE_SIZE" in data_manager
    assert "setDataPage" in data_manager
    assert "canMutateData && configuredSymbol" in data_manager
    assert "WITH normalized_history AS" in sync_endpoint
    assert "LEFT JOIN normalized_history h ON h.symbol=d.symbol" in sync_endpoint
    assert "LIMIT 1000" not in sync_endpoint
