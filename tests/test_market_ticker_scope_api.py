import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import market  # noqa: E402
from app.core.errors import register_exception_handlers  # noqa: E402


class FakeMarketDomainService:
    def __init__(self):
        self.symbol_requests: list[tuple[str, str, str]] = []
        self.ticker_requests: list[tuple[str, list[str] | None]] = []

    async def get_symbols(self, exchange: str, quote: str, market_type: str):
        self.symbol_requests.append((exchange, quote, market_type))
        return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]

    async def get_tickers(self, exchange: str, symbols: list[str] | None = None):
        self.ticker_requests.append((exchange, symbols))
        return [{"symbol": symbol} for symbol in symbols or []]


def build_client() -> TestClient:
    app = FastAPI()
    app.include_router(market.router, prefix="/api/v2/market")
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def test_ticker_scope_resolves_all_active_usdt_swaps_before_paging(monkeypatch):
    service = FakeMarketDomainService()
    monkeypatch.setattr(market, "market_domain_service", service)

    response = build_client().get(
        "/api/v2/market/tickers",
        params={"exchange": "okx", "quote": "USDT", "market_type": "swap", "offset": 1, "limit": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert service.symbol_requests == [("okx", "USDT", "swap")]
    assert service.ticker_requests == [("okx", ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"])]
    assert payload["data"] == [{
        "symbol": "ETH/USDT:USDT",
        "sector_key": "blue-chip",
        "sector_name": "主流资产",
        "taxonomy_version": "2026-08-04",
    }]
    assert payload["meta"] == {"total": 3, "offset": 1, "limit": 1}


def test_ticker_scope_rejects_conflicting_explicit_symbol_list(monkeypatch):
    service = FakeMarketDomainService()
    monkeypatch.setattr(market, "market_domain_service", service)

    response = build_client().get(
        "/api/v2/market/tickers",
        params={"exchange": "okx", "symbols": "BTC/USDT:USDT", "market_type": "swap"},
    )

    assert response.status_code == 400
    assert "不能同时" in response.json()["detail"]
    assert service.symbol_requests == []
    assert service.ticker_requests == []


def test_ticker_scope_assigns_every_symbol_to_exactly_one_sector(monkeypatch):
    service = FakeMarketDomainService()
    service.get_symbols = lambda *_args: None

    async def get_tickers(_exchange: str, _symbols: list[str] | None = None):
        return [
            {"symbol": "AAVE/USDT:USDT"},
            {"symbol": "NVDA/USDT:USDT"},
            {"symbol": "XAU/USDT:USDT"},
            {"symbol": "UNKNOWN/USDT:USDT"},
        ]

    service.get_tickers = get_tickers
    monkeypatch.setattr(market, "market_domain_service", service)

    response = build_client().get(
        "/api/v2/market/tickers",
        params={"exchange": "okx", "symbols": "AAVE/USDT:USDT,NVDA/USDT:USDT,XAU/USDT:USDT,UNKNOWN/USDT:USDT"},
    )

    assert response.status_code == 200
    rows = response.json()["data"]
    assert [(row["symbol"], row["sector_key"], row["sector_name"]) for row in rows] == [
        ("AAVE/USDT:USDT", "defi", "DeFi"),
        ("NVDA/USDT:USDT", "tradfi-semiconductor", "TradFi · 半导体"),
        ("XAU/USDT:USDT", "tradfi-commodity", "TradFi · 大宗商品"),
        ("UNKNOWN/USDT:USDT", "other", "其他"),
    ]
    assert {row["taxonomy_version"] for row in rows} == {"2026-08-04"}
