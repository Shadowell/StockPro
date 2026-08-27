from __future__ import annotations

from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import onchain  # noqa: E402
from app.domain.fundamentals.service import FundamentalService  # noqa: E402


def test_fundamental_provider_rows_become_announcement_time_facts() -> None:
    facts = FundamentalService.build_facts(
        symbol="600519.SH",
        indicators=[{
            "ann_date": "20260815", "end_date": "20260630", "roe": 17.9543, "roa": 19.9688,
            "grossprofit_margin": 89.5552, "netprofit_margin": 50.7516,
            "or_yoy": 1.4699, "netprofit_yoy": -1.9516, "ocf_to_or": 0.7794, "debt_to_assets": 15.1931,
        }],
        holders=[{"ann_date": "20260815", "end_date": "20260630", "holder_num": 296404}],
        dividends=[{"ann_date": "20250403", "end_date": "20241231", "cash_div_tax": 27.67, "div_proc": "实施"}],
    )

    assert len(facts) == 10
    assert {item["factor_code"] for item in facts} >= {
        "fundamental.roe_ttm_pit", "fundamental.net_profit_growth_yoy_pit",
        "shareholder.holder_count", "dividend.cash_per_share",
    }
    assert all(item["announcement_available_at"].isoformat().endswith("+08:00") for item in facts)
    assert all(item["source_lineage"]["provider"].startswith("tushare.") for item in facts)


def test_fundamental_routes_are_read_only_until_explicit_admin_sync(monkeypatch) -> None:
    summary = {"status": "ready", "symbol": "600519.SH", "name": "贵州茅台", "valuation": {}, "items": [], "latest_factors": {}, "missing_inputs": [], "provider_calls": 0, "writes_performed": False, "orders_created": 0, "paper_mutated": False}
    sync = {"symbol": "600519.SH", "status": "success", "fact_count": 10, "provider_calls": 3, "orders_created": 0, "paper_mutated": False}
    monkeypatch.setattr(onchain.fundamental_service, "summary", lambda symbol, as_of=None: summary)
    monkeypatch.setattr(onchain.fundamental_service, "sync", lambda symbol, years=3: sync)
    app = FastAPI(); app.include_router(onchain.router, prefix="/api/v2/onchain"); client = TestClient(app)

    get_response = client.get("/api/v2/onchain/summary", params={"symbol": "600519.SH"})
    post_response = client.post("/api/v2/onchain/sync", json={"symbol": "600519.SH", "years": 3})

    assert get_response.status_code == 200
    assert get_response.json()["data"]["writes_performed"] is False
    assert post_response.status_code == 200
    assert post_response.json()["data"]["provider_calls"] == 3
    assert post_response.json()["data"]["paper_mutated"] is False


def test_fundamental_page_has_only_a_share_cny_and_pit_evidence() -> None:
    page = (ROOT / "frontend/src/pages/OnchainResearch.tsx").read_text(encoding="utf-8")
    market = (ROOT / "frontend/src/pages/Market.tsx").read_text(encoding="utf-8")
    router = (ROOT / "backend/app/api/v2/endpoints/onchain.py").read_text(encoding="utf-8")

    for label in ("估值与市场规模", "盈利与质量", "成长与资本结构", "股东与分红", "公告时点证据"):
        assert label in page
    for forbidden in ("DeFi", "协议研究", "收益机会", "美元", "稳定币", "链锁仓量"):
        assert forbidden not in page
    assert "onchainApi.sync" in page
    assert "availableAt" in page and "annDate" in page and "reportPeriod" in page
    assert "navigate(`/onchain?symbol=" in market
    assert '@router.post("/sync")' in router
