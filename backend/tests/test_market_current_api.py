from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.research.models import MarketOverviewView
from app.domain.instruments.models import InstrumentContract
from app.domain.research.models import InstrumentDetailView
from decimal import Decimal
from app.main import create_app


class FakeMarketRepository:
    def __init__(self, *, known_instrument: bool = False) -> None:
        self.executed_writes: list[str] = []
        self.provider_calls: list[str] = []
        self.known_instrument = known_instrument
        self.watchlist_payloads: list[tuple[str, str, str]] = []

    def market_overview(self) -> MarketOverviewView:
        return MarketOverviewView(
            indices=(),
            breadth=None,
            turnover=None,
            limit_ecology=None,
            sector_flows=(),
            source_label="PostgreSQL market cache",
            source_updated_at=None,
            trade_date=None,
            data_status="empty",
        )

    def search_instruments(self, query: str, asset_class: str | None, limit: int):
        return []

    def instrument_detail(self, symbol: str):
        if not self.known_instrument:
            return None
        return InstrumentDetailView(
            instrument=InstrumentContract.stock(
                symbol="600519.SH",
                exchange="SSE",
                currency="CNY",
                tick_size=Decimal("0.01"),
                lot_size=100,
                name="贵州茅台",
            ),
            latest_price=Decimal("1272.96"),
            change_pct=Decimal("1.2"),
            turnover=Decimal("1000000"),
            source_updated_at=None,
            trade_date=None,
            data_status="stale",
        )

    def daily_bars(self, symbol: str, limit: int):
        return []

    def list_watchlist(self, owner: str):
        return []

    def upsert_watchlist(self, owner: str, symbol: str, note: str):
        self.watchlist_payloads.append((owner, symbol, note))
        return {"id": 1, "owner": owner, "symbol": symbol, "note": note}

    def delete_watchlist(self, owner: str, entry_id: int):
        return True


def _client(repository: FakeMarketRepository) -> TestClient:
    context = SimpleNamespace(
        settings=SimpleNamespace(
            AUTH_ENABLED=False,
            ADMIN_USERNAME="admin",
            BACKEND_CORS_ORIGINS=["http://localhost:4444"],
        ),
        repositories=SimpleNamespace(
            health=repository,
            auth=repository,
            market=repository,
        ),
        clock=lambda: datetime.now(timezone.utc),
    )
    return TestClient(create_app(context))


def test_market_overview_keeps_missing_metrics_null() -> None:
    repository = FakeMarketRepository()

    response = _client(repository).get("/api/market/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["breadth"] is None
    assert payload["turnover"] is None
    assert payload["limit_ecology"] is None
    assert payload["data_status"] == "empty"
    assert repository.executed_writes == []
    assert repository.provider_calls == []


def test_market_instrument_endpoints_use_one_current_contract() -> None:
    client = _client(FakeMarketRepository())

    assert client.get("/api/market/instruments?q=600519&limit=20").status_code == 200
    assert client.get("/api/market/instruments/600519.SH").status_code == 404
    assert client.get("/api/stocks/600519.SH").status_code == 404
    assert client.get("/api/v2/market/instruments").status_code == 404


def test_watchlist_write_persists_only_symbol_and_note() -> None:
    repository = FakeMarketRepository(known_instrument=True)
    client = _client(repository)

    response = client.post(
        "/api/market/watchlist",
        json={"symbol": "600519.SH", "note": "核心观察"},
    )

    assert response.status_code == 200
    assert repository.watchlist_payloads == [("admin", "600519.SH", "核心观察")]
    assert "price" not in response.json()
