from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def _evidence() -> dict[str, object]:
    return {
        "trade_date": "2026-08-26",
        "data_mode": "盘后快照",
        "provider": "TuShare → PostgreSQL",
        "source_snapshot_id": 7,
        "available_at": "2026-08-26T17:30:00+08:00",
        "knowledge_cutoff_at": "2026-08-26T17:30:00+08:00",
        "last_success_at": "2026-08-26T17:30:00+08:00",
    }


def _facts() -> list[dict[str, object]]:
    return [
        {
            "symbol": "000001.SZ",
            "name": "平安银行",
            "price": 12.5,
            "change_percent": 6.0,
            "amount": 1_000_000.0,
            "turnover": 12.0,
            "volume_ratio": 2.0,
        },
        {
            "symbol": "600519.SH",
            "name": "贵州茅台",
            "price": 1500.0,
            "change_percent": -4.0,
            "amount": 800_000.0,
            "turnover": 3.0,
            "volume_ratio": 0.8,
        },
        {
            "symbol": "300750.SZ",
            "name": "宁德时代",
            "price": 200.0,
            "change_percent": 0.0,
            "amount": 900_000.0,
            "turnover": 7.0,
            "volume_ratio": 1.2,
        },
        {
            "symbol": "000002.SZ",
            "name": "无价格证券",
            "price": None,
            "change_percent": 8.0,
            "amount": 700_000.0,
            "turnover": 5.0,
            "volume_ratio": 1.0,
        },
        {
            "symbol": "600000.SH",
            "name": "坏涨跌数据",
            "price": 10.0,
            "change_percent": 1200.0,
            "amount": 600_000.0,
            "turnover": 4.0,
            "volume_ratio": 1.0,
        },
    ]


def _indices() -> list[dict[str, object]]:
    return [
        {"ts_code": "000001.SH", "name": "上证指数", "close": 3000.0, "pct_chg": 0.5},
        {"ts_code": "399001.SZ", "name": "深证成指", "close": 10000.0, "pct_chg": -0.2},
        {"ts_code": "399006.SZ", "name": "创业板指", "close": 2000.0, "pct_chg": 0.8},
        {"ts_code": "000300.SH", "name": "沪深300", "close": 3600.0, "pct_chg": 0.3},
    ]


def test_market_overview_reconciles_breadth_and_filters_invalid_ranking_rows():
    from app.domain.market.overview import build_market_overview

    overview = build_market_overview(
        ticker_rows=_facts(),
        index_rows=_indices(),
        trend_rows=[],
        evidence=_evidence(),
    )

    assert overview["indices"]["status"] == "ready"
    assert [item["symbol"] for item in overview["indices"]["items"]] == [
        "000001.SH",
        "399001.SZ",
        "399006.SZ",
        "000300.SH",
    ]

    breadth = overview["breadth"]
    assert breadth["eligible_count"] == 3
    assert breadth["gainers"] == 1
    assert breadth["losers"] == 1
    assert breadth["flat"] == 1
    assert breadth["strong_count"] == 1
    assert breadth["weak_count"] == 1
    assert breadth["mean_change_pct"] == 2 / 3
    assert breadth["median_change_pct"] == 0.0
    assert sum(bucket["count"] for bucket in overview["distribution"]["buckets"]) == 3

    rankings = overview["rankings"]
    assert [item["symbol"] for item in rankings["top_gainers"]] == ["000001.SZ", "300750.SZ", "600519.SH"]
    assert [item["symbol"] for item in rankings["top_losers"]] == ["600519.SH", "300750.SZ", "000001.SZ"]
    assert rankings["turnover_leaders"][0]["symbol"] == "000001.SZ"
    assert rankings["active_leaders"][0]["symbol"] == "000001.SZ"
    assert "000002.SZ" not in {item["symbol"] for item in rankings["top_gainers"]}
    assert "600000.SH" not in {item["symbol"] for item in rankings["top_gainers"]}

    assert overview["activity"]["total_amount_cny"] == 2_700_000.0
    assert overview["activity"]["amount_unit"] == "CNY"
    assert overview["activity"]["turnover_unit"] == "%"
    assert overview["activity"]["volume_ratio_denominator"] == "20日平均成交量"


def test_trend_strength_is_blocked_until_each_symbol_has_sixty_confirmed_days():
    from app.domain.market.overview import compute_trend_strength

    short_rows = [
        {
            "symbol": "000001.SZ",
            "date": (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
            "close": 10.0 + index,
            "high": 10.5 + index,
            "low": 9.5 + index,
        }
        for index in range(59)
    ]
    blocked = compute_trend_strength(short_rows, required_history_days=60)

    assert blocked["status"] == "blocked"
    assert blocked["above_ma5"]["count"] is None
    assert blocked["above_ma20"]["percentage"] is None
    assert blocked["new_high_60d"]["count"] is None
    assert "60" in " ".join(blocked["missing_inputs"])

    complete_rows = [
        {
            "symbol": "000001.SZ",
            "date": (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
            "close": 10.0 + index,
            "high": 10.5 + index,
            "low": 9.5 + index,
        }
        for index in range(60)
    ]
    ready = compute_trend_strength(complete_rows, required_history_days=60)

    assert ready["status"] == "ready"
    assert ready["covered_symbols"] == 1
    assert ready["above_ma5"]["count"] == 1
    assert ready["above_ma20"]["count"] == 1
    assert ready["above_ma60"]["count"] == 1
    assert ready["new_high_60d"]["count"] == 1
    assert ready["new_low_60d"]["count"] == 0


def test_market_overview_route_returns_one_read_only_foundation_contract(monkeypatch):
    from app.api.v2.endpoints import market as market_endpoint
    from app.core.errors import register_exception_handlers

    class FakeMarketOverviewService:
        async def get_market_overview(self, trade_date=None):
            return {"trade_date": trade_date or "2026-08-26", "status": "empty", "rankings": {}}

    monkeypatch.setattr(market_endpoint, "market_domain_service", FakeMarketOverviewService())
    app = FastAPI()
    app.include_router(market_endpoint.router, prefix="/api/v2/market")
    register_exception_handlers(app)

    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/v2/market/overview",
        params={"trade_date": "2026-08-26"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["trade_date"] == "2026-08-26"
