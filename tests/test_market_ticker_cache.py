from __future__ import annotations

import asyncio
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.domain.market.service as market_service_module  # noqa: E402
from app.domain.market.service import MarketDomainService  # noqa: E402


class MemoryTickerRepository:
    def __init__(self) -> None:
        self.cached_symbols: list[str] = []

    def update_ticker_cache(self, exchange: str, symbol: str, ticker: dict) -> None:
        self.cached_symbols.append(f"{exchange}:{symbol}")


class CountingTickerExchange:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_tickers(self, symbols: list[str] | None = None) -> list[dict]:
        self.calls += 1
        return [{"symbol": symbol, "last": 1.0} for symbol in symbols or []]


def test_market_ticker_snapshot_is_reused_for_ten_seconds(monkeypatch) -> None:
    clock = [0.0]
    exchange = CountingTickerExchange()
    service = MarketDomainService(repo=MemoryTickerRepository())
    monkeypatch.setattr(market_service_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(market_service_module.exchange_manager, "get_exchange", lambda name: exchange)

    symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    first = asyncio.run(service.get_tickers("okx", symbols))
    clock[0] = 10.0
    second = asyncio.run(service.get_tickers("okx", symbols))

    assert second == first
    assert exchange.calls == 1
