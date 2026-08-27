from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import market as market_endpoint  # noqa: E402
from app.domain.market.service import MarketDomainService  # noqa: E402


class FakeDashboardRepository:
    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    def _record(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    def get_market_overview(self, trade_date=None):
        self._record("overview")
        return {
            "trade_date": trade_date or "2026-08-27",
            "status": "ready",
            "evidence": {"trade_date": trade_date or "2026-08-27", "source_snapshot_id": 7, "status": "ready"},
        }

    def get_market_phase(self, trade_date=None):
        self._record("phase")
        return {"trade_date": trade_date or "2026-08-27", "source_snapshot_id": 7, "status": "ok"}

    def get_market_sentiment(self, trade_date=None):
        self._record("sentiment")
        return {"trade_date": trade_date or "2026-08-27", "source_snapshot_id": 7, "status": "ok"}

    def list_sector_rps(self, *, trade_date=None, classification_system, limit):
        self._record(classification_system)
        items = [] if classification_system == "concept" else [{
            "trade_date": trade_date or "2026-08-27",
            "source_snapshot_id": 7,
            "classification_system": classification_system,
        }]
        return {"items": items, "data_status": "empty" if not items else "ok"}

    def list_symbol_abnormalities(self, *, trade_date=None, limit):
        self._record("movers")
        return {"items": [{"trade_date": trade_date or "2026-08-27", "source_snapshot_id": 7}], "data_status": "ok"}

    def list_market_events(self, *, limit, source=None, severity=None):
        self._record("events")
        return {"events": [], "data_status": "empty"}


def test_home_dashboard_singleflight_reuses_one_persisted_read_batch() -> None:
    repo = FakeDashboardRepository()
    service = MarketDomainService(repo=repo, intraday_provider=object(), symbol_provider=object())

    async def run():
        return await asyncio.gather(service.get_home_dashboard(), service.get_home_dashboard())

    first, second = asyncio.run(run())

    assert first == second
    assert first["provider_calls"] == 0
    assert first["writes_performed"] is False
    assert first["paper_mutated"] is False
    assert first["evidence"]["observed_trade_dates"]
    assert first["evidence"]["consistency_warnings"] == []
    assert all(count == 1 for count in repo.calls.values())


def test_home_dashboard_marks_old_latest_data_stale_but_labels_explicit_history() -> None:
    class StaleRepository(FakeDashboardRepository):
        def get_market_overview(self, trade_date=None):
            payload = super().get_market_overview(trade_date)
            payload["evidence"]["available_at"] = "2020-01-01T17:30:00+08:00"
            return payload

    stale_service = MarketDomainService(repo=StaleRepository(), intraday_provider=object(), symbol_provider=object())
    stale = asyncio.run(stale_service.get_home_dashboard())
    assert stale["data_status"] == "stale"
    assert stale["evidence"]["data_age_seconds"] > 36 * 60 * 60

    history_service = MarketDomainService(repo=StaleRepository(), intraday_provider=object(), symbol_provider=object())
    history = asyncio.run(history_service.get_home_dashboard("2026-08-27"))
    assert history["evidence"]["data_mode"] == "历史回看"
    assert history["data_status"] != "stale"


def test_home_dashboard_route_returns_one_read_only_contract(monkeypatch) -> None:
    class FakeService:
        async def get_home_dashboard(self, trade_date=None):
            return {
                "data_status": "partial",
                "evidence": {"trade_date": trade_date, "provider_calls": 0, "writes_performed": False},
                "sentiment": {"status": "partial"},
                "provider_calls": 0,
                "writes_performed": False,
                "paper_mutated": False,
            }

    monkeypatch.setattr(market_endpoint, "market_domain_service", FakeService())
    app = FastAPI()
    app.include_router(market_endpoint.router, prefix="/api/v2/market")

    response = TestClient(app).get("/api/v2/market/dashboard", params={"trade_date": "2026-08-27"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["evidence"]["trade_date"] == "2026-08-27"
    assert data["provider_calls"] == 0
    assert data["writes_performed"] is False
    assert data["paper_mutated"] is False


def test_sector_members_route_exposes_snapshot_bias_without_writes(monkeypatch) -> None:
    class FakeService:
        async def list_sector_members(self, sector_code, *, classification_system, trade_date, limit):
            return {
                "items": [{
                    "trade_date": trade_date or "2026-08-27",
                    "classification_system": classification_system,
                    "sector_code": sector_code,
                    "sector_name": "人工智能",
                    "symbol": "600001.SH",
                    "name": "示例",
                    "source_snapshot_id": 7,
                    "membership_bias": "current_membership_applied_to_history",
                }],
                "data_status": "ok",
                "source_snapshot_id": 7,
                "membership_bias": "current_membership_applied_to_history",
            }

    monkeypatch.setattr(market_endpoint, "market_domain_service", FakeService())
    app = FastAPI()
    app.include_router(market_endpoint.router, prefix="/api/v2/market")

    response = TestClient(app).get(
        "/api/v2/market/sector-rps/BK1001/members",
        params={"classification_system": "concept", "trade_date": "2026-08-27"},
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["symbol"] == "600001.SH"
    assert response.json()["meta"]["membership_bias"] == "current_membership_applied_to_history"
