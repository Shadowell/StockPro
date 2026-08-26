from __future__ import annotations

import asyncio
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.market.service import MarketDomainService  # noqa: E402


class FakeAshareMarketRepository:
    def list_symbols(self, asset_class: str, limit: int = 5000):
        assert asset_class == "stock"
        return ["600519.SH", "000001.SZ"]

    def list_tickers(self, symbols=None):
        rows = [
            {
                "exchange": "SSE",
                "symbol": "600519.SH",
                "last": 1500.0,
                "changePercent": 1.25,
                "volume": 1000.0,
                "quoteVolume": 1500000.0,
                "timestamp": 1_700_000_000_000,
            }
        ]
        return rows if not symbols else [row for row in rows if row["symbol"] in symbols]

    def get_klines(self, exchange, symbol, timeframe, limit, start=None, end=None):
        assert (exchange, symbol, timeframe) == ("SSE", "600519.SH", "1d")
        return [
            {
                "timestamp": 1_700_000_000_000,
                "open": 1490.0,
                "high": 1510.0,
                "low": 1480.0,
                "close": 1500.0,
                "volume": 1000.0,
                "quote_volume": 1_500_000.0,
            }
        ][-limit:]

    def get_orderbook(self, exchange, symbol, limit):
        return {"exchange": exchange, "symbol": symbol, "bids": [], "asks": [], "data_status": "empty"}

    def get_trades(self, exchange, symbol, limit):
        return []


def test_bitpro_market_service_reads_a_share_repository_without_exchange_manager():
    service = MarketDomainService(FakeAshareMarketRepository())

    symbols = asyncio.run(service.get_symbols("SSE", "CNY", "stock"))
    tickers = asyncio.run(service.get_tickers("SSE", ["600519.SH"]))
    klines = asyncio.run(service.get_klines("SSE", "600519.SH", "1d", 100))
    orderbook = asyncio.run(service.get_orderbook("SSE", "600519.SH", 20))

    assert symbols == ["600519.SH", "000001.SZ"]
    assert tickers[0]["symbol"] == "600519.SH"
    assert tickers[0]["changePercent"] == 1.25
    assert klines[0]["quote_volume"] == 1_500_000.0
    assert orderbook["data_status"] == "empty"
