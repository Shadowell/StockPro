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

    def get_klines_with_status(self, exchange, symbol, timeframe, limit, start=None, end=None):
        if timeframe == "1d":
            return {
                "exchange": exchange,
                "symbol": symbol,
                "timeframe": "1d",
                "items": self.get_klines(exchange, symbol, timeframe, limit, start, end),
                "data_status": "ok",
                "unavailable_reason": None,
            }
        if timeframe == "1m":
            return {
                "exchange": exchange,
                "symbol": symbol,
                "timeframe": "1m",
                "items": [
                    {
                        "timestamp": 1_700_000_060_000,
                        "datetime": "2023-11-14T09:31:00+08:00",
                        "trade_date": "2023-11-14",
                        "open": 1500.0,
                        "high": 1501.0,
                        "low": 1499.0,
                        "close": 1500.5,
                        "volume": 1200.0,
                        "quote_volume": 1_800_600.0,
                        "source": "unit-cache",
                        "source_updated_at": "2023-11-14T09:31:01+08:00",
                        "collected_at": "2023-11-14T09:31:02+08:00",
                        "freshness": {"basis": "source_updated_at", "stale": False},
                        "data_status": "ok",
                    }
                ][:limit],
                "data_status": "ok",
                "unavailable_reason": None,
            }
        return {
            "exchange": exchange,
            "symbol": symbol,
            "timeframe": timeframe,
            "items": [],
            "data_status": "empty",
            "unavailable_reason": f"no A-share {timeframe} minute bar cache for {symbol}",
        }

    def get_orderbook(self, exchange, symbol, limit):
        if limit == 5:
            return {
                "exchange": exchange,
                "symbol": symbol,
                "bids": [[1500.0, 100.0]],
                "asks": [[1500.5, 200.0]],
                "trade_date": "2023-11-14",
                "snapshot_at": "2023-11-14T09:31:03+08:00",
                "source": "unit-cache",
                "source_updated_at": "2023-11-14T09:31:03+08:00",
                "collected_at": "2023-11-14T09:31:04+08:00",
                "freshness": {"basis": "source_updated_at", "stale": False},
                "data_status": "ok",
                "unavailable_reason": None,
            }
        return {
            "exchange": exchange,
            "symbol": symbol,
            "bids": [],
            "asks": [],
            "data_status": "empty",
            "unavailable_reason": "no A-share order-book cache for 600519.SH",
        }

    def get_trades(self, exchange, symbol, limit):
        return self.get_trades_with_status(exchange, symbol, limit)["items"]

    def get_trades_with_status(self, exchange, symbol, limit):
        if limit == 3:
            return {
                "exchange": exchange,
                "symbol": symbol,
                "items": [
                    {
                        "id": "1",
                        "timestamp": 1_700_000_061_000,
                        "datetime": "2023-11-14T09:31:01+08:00",
                        "trade_date": "2023-11-14",
                        "side": "unknown",
                        "price": 1500.5,
                        "amount": 100.0,
                        "volume": 100.0,
                        "cost": 150050.0,
                        "source": "unit-cache",
                        "source_updated_at": "2023-11-14T09:31:01+08:00",
                        "collected_at": "2023-11-14T09:31:02+08:00",
                        "freshness": {"basis": "source_updated_at", "stale": False},
                        "data_status": "ok",
                    }
                ],
                "data_status": "ok",
                "unavailable_reason": None,
            }
        return {
            "exchange": exchange,
            "symbol": symbol,
            "items": [],
            "data_status": "empty",
            "unavailable_reason": "no A-share recent trade cache for 600519.SH",
        }


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


def test_market_service_exposes_intraday_cache_with_freshness_metadata():
    service = MarketDomainService(FakeAshareMarketRepository())

    payload = asyncio.run(service.get_klines_payload("SSE", "600519.SH", "1m", 100))

    assert payload["data_status"] == "ok"
    assert payload["items"][0]["trade_date"] == "2023-11-14"
    assert payload["items"][0]["source_updated_at"] == "2023-11-14T09:31:01+08:00"
    assert payload["items"][0]["freshness"]["stale"] is False


def test_market_service_non_daily_empty_cache_is_explicit_not_silent_empty():
    service = MarketDomainService(FakeAshareMarketRepository())

    payload = asyncio.run(service.get_klines_payload("SSE", "600519.SH", "5m", 100))

    assert payload["items"] == []
    assert payload["data_status"] == "empty"
    assert "no A-share 5m minute bar cache" in payload["unavailable_reason"]


def test_market_service_reads_cached_orderbook_depth():
    service = MarketDomainService(FakeAshareMarketRepository())

    orderbook = asyncio.run(service.get_orderbook("SSE", "600519.SH", 5))

    assert orderbook["data_status"] == "ok"
    assert orderbook["bids"] == [[1500.0, 100.0]]
    assert orderbook["asks"] == [[1500.5, 200.0]]
    assert orderbook["trade_date"] == "2023-11-14"


def test_market_service_recent_trades_cache_and_empty_status_are_distinct():
    service = MarketDomainService(FakeAshareMarketRepository())

    trades = asyncio.run(service.get_trades_payload("SSE", "600519.SH", 3))
    empty = asyncio.run(service.get_trades_payload("SSE", "600519.SH", 20))

    assert trades["data_status"] == "ok"
    assert trades["items"][0]["side"] == "unknown"
    assert trades["items"][0]["cost"] == 150050.0
    assert empty["items"] == []
    assert empty["data_status"] == "empty"
    assert "recent trade cache" in empty["unavailable_reason"]
