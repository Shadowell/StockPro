from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.v2.endpoints import strategy  # noqa: E402
from app.core.errors import register_exception_handlers  # noqa: E402
from app.services.strategy_service import StrategyService  # noqa: E402

strategy_service_module = importlib.import_module("app.services.strategy_service")


def build_client() -> TestClient:
    app = FastAPI()
    app.include_router(strategy.router, prefix="/api/v2/strategies")
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def test_strategies_without_page_uses_default_paginated_response(monkeypatch) -> None:
    calls = []

    async def fake_list_page(**kwargs):
        calls.append(kwargs)
        return {
            "items": [{"id": 1, "name": "paged"}],
            "total": 1,
            "page": 1,
            "per_page": 18,
            "pages": 1,
            "status_counts": {},
            "asset_counts": {},
            "type_counts": {},
            "timeframe_counts": {},
            "capital_counts": {},
        }

    monkeypatch.setattr(strategy.strategy_domain_service, "list_page", fake_list_page)

    response = build_client().get("/api/v2/strategies")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["items"] == [{"id": 1, "name": "paged"}]
    assert body["data"]["page"] == 1
    assert body["data"]["per_page"] == 18
    assert calls == [
        {
            "page": 1,
            "per_page": 18,
            "search": "",
            "status": "all",
            "asset_class": "all",
            "strategy_type": "all",
            "timeframe": "all",
            "capital": "all",
        }
    ]


def test_strategies_with_page_returns_paginated_payload(monkeypatch) -> None:
    calls = []

    async def fake_list_page(**kwargs):
        calls.append(kwargs)
        return {
            "items": [{"id": 2, "name": "paged"}],
            "total": 4,
            "page": 2,
            "per_page": 1,
            "pages": 4,
            "status_counts": {"all": 4, "running": 1, "paused": 0, "not_started": 3},
            "asset_counts": {"all": 4, "spot": 1, "contract": 3},
            "type_counts": {"all": 4, "cta": 2, "martingale": 1, "ai": 1, "market_making": 0},
            "timeframe_counts": {"all": 4, "1m": 1, "5m": 0, "15m": 1, "30m": 0, "1h": 2, "4h": 0, "12h": 0, "1d": 0},
            "capital_counts": {"all": 4, "100U": 3, "1000U": 1},
        }

    monkeypatch.setattr(strategy.strategy_domain_service, "list_page", fake_list_page)

    response = build_client().get(
        "/api/v2/strategies?page=2&per_page=1&status=running&asset_class=contract"
        "&strategy_type=cta&timeframe=15m&capital=100U&search=cta"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["items"] == [{"id": 2, "name": "paged"}]
    assert body["data"]["total"] == 4
    assert body["data"]["page"] == 2
    assert body["data"]["per_page"] == 1
    assert body["data"]["pages"] == 4
    assert calls == [
        {
            "page": 2,
            "per_page": 1,
            "search": "cta",
            "status": "running",
            "asset_class": "contract",
            "strategy_type": "cta",
            "timeframe": "15m",
            "capital": "100U",
        }
    ]


def test_strategy_type_query_rejects_ctr_alias(monkeypatch) -> None:
    async def fake_list_page(**kwargs):
        raise AssertionError(f"strategy service should not receive invalid alias: {kwargs}")

    monkeypatch.setattr(strategy.strategy_domain_service, "list_page", fake_list_page)

    response = build_client().get("/api/v2/strategies?page=1&strategy_type=ctr")

    assert response.status_code == 422


def test_strategy_page_service_filters_and_counts_by_existing_asset_contracts(monkeypatch) -> None:
    class FakeDb:
        def get_strategies(self):
            return [
                {
                    "id": 1,
                    "name": "[合约][15M][CTA] BTC · EMA趋势跟踪 · 100U",
                    "status": "running",
                    "description": "cta",
                    "config": {"market_type": "swap", "timeframe": "15m", "initial_capital": 100},
                    "symbols": ["BTC/USDT"],
                },
                {
                    "id": 2,
                    "name": "[现货][1H][CTA] ETH · 趋势跟踪 · 1000U",
                    "status": "running",
                    "description": "cta",
                    "config": {"market_type": "spot", "timeframe": "1h", "initial_capital": 1000},
                    "symbols": ["ETH/USDT"],
                },
                {
                    "id": 3,
                    "name": "[合约][1M][马丁] SOL · ATR马丁网格 · 100U",
                    "status": "paused",
                    "description": "cta",
                    "config": {"inst_type": "SWAP", "timeframe": "1m", "initial_capital": 100},
                    "symbols": ["SOL/USDT"],
                },
                {
                    "id": 4,
                    "name": "[合约][AI] Top20 · AI自主 · 100U",
                    "status": "stopped",
                    "description": "cta",
                    "config": {"market_observation_mode": "ai_decides", "initial_capital": 100},
                    "symbols": ["DOGE/USDT:USDT"],
                },
                {
                    "id": 5,
                    "name": "[合约][1M][做市] SOL · 趋势过滤库存做市 · 100U",
                    "status": "running",
                    "description": "market making",
                    "config": {
                        "market_type": "swap",
                        "timeframe": "1m",
                        "strategy_type": "market_making",
                        "strategy_key": "contract_trend_filtered_market_making_sol_100u",
                        "initial_capital": 100,
                    },
                    "symbols": ["SOL/USDT:USDT"],
                },
            ]

    monkeypatch.setattr(strategy_service_module, "db", FakeDb())

    result = asyncio.run(
        StrategyService().get_strategies_page(
            page=1,
            per_page=10,
            search="cta",
            status="all",
            asset_class="contract",
            strategy_type="cta",
            timeframe="15m",
            capital="100U",
        )
    )

    assert [item["id"] for item in result["items"]] == [1]
    assert result["total"] == 1
    assert result["asset_counts"] == {"all": 1, "spot": 0, "contract": 1}
    assert result["status_counts"] == {"all": 1, "running": 1, "paused": 0, "not_started": 0}
    assert result["type_counts"] == {"all": 1, "cta": 1, "martingale": 0, "ai": 0, "market_making": 0}
    assert result["timeframe_counts"]["15m"] == 1
    assert result["capital_counts"] == {"all": 1, "100U": 1, "1000U": 0}

    invalid_ctr_result = asyncio.run(
        StrategyService().get_strategies_page(
            page=1,
            per_page=10,
            search="",
            status="all",
            asset_class="contract",
            strategy_type="ctr",
            timeframe="all",
            capital="all",
        )
    )
    assert invalid_ctr_result["items"] == []
    assert invalid_ctr_result["total"] == 0

    market_making_result = asyncio.run(
        StrategyService().get_strategies_page(
            page=1,
            per_page=10,
            search="做市 sol",
            status="all",
            asset_class="contract",
            strategy_type="market_making",
            timeframe="1m",
            capital="100U",
        )
    )
    assert [item["id"] for item in market_making_result["items"]] == [5]
    assert market_making_result["total"] == 1
    assert market_making_result["type_counts"]["market_making"] == 1


def test_strategy_search_matches_like_simulation_without_rewriting_counts(monkeypatch) -> None:
    class FakeDb:
        def get_strategies(self):
            return [
                {
                    "id": 1,
                    "name": "[合约][15M][CTA] BTC · EMA趋势跟踪 · 100U",
                    "status": "running",
                    "description": "trend",
                    "config": {"market_type": "swap", "timeframe": "15m", "initial_capital": 100},
                    "symbols": ["BTC/USDT:USDT"],
                },
                {
                    "id": 2,
                    "name": "[现货][1H][CTA] ETH · 趋势跟踪 · 1000U",
                    "status": "running",
                    "description": "trend",
                    "config": {"market_type": "spot", "timeframe": "1h", "initial_capital": 1000},
                    "symbols": ["ETH/USDT"],
                },
                {
                    "id": 3,
                    "name": "[合约][1M][马丁] SOL · ATR马丁网格 · 100U",
                    "status": "paused",
                    "description": "grid",
                    "config": {"inst_type": "SWAP", "timeframe": "1m", "initial_capital": 100},
                    "symbols": ["SOL/USDT:USDT"],
                },
                {
                    "id": 4,
                    "name": "[合约][AI] Top20 · AI自主 · 100U",
                    "status": "stopped",
                    "description": "ai",
                    "config": {"market_observation_mode": "ai_decides", "initial_capital": 100},
                    "symbols": ["DOGE/USDT:USDT"],
                },
                {
                    "id": 5,
                    "name": "[合约][1M][做市] SOL · 趋势过滤库存做市 · 100U",
                    "status": "running",
                    "description": "inventory market maker",
                    "config": {"market_type": "swap", "timeframe": "1m", "strategy_type": "market_making", "initial_capital": 100},
                    "symbols": ["SOL/USDT:USDT"],
                },
            ]

    monkeypatch.setattr(strategy_service_module, "db", FakeDb())

    result = asyncio.run(
        StrategyService().get_strategies_page(
            page=1,
            per_page=10,
            search="btc/usdt 15m",
            status="all",
            asset_class="contract",
            strategy_type="all",
            timeframe="all",
            capital="all",
        )
    )

    assert [item["id"] for item in result["items"]] == [1]
    assert result["total"] == 1
    assert result["status_counts"] == {"all": 4, "running": 2, "paused": 1, "not_started": 1}
    assert result["asset_counts"] == {"all": 5, "spot": 1, "contract": 4}
    assert result["type_counts"] == {"all": 4, "cta": 1, "martingale": 1, "ai": 1, "market_making": 1}
    assert result["timeframe_counts"]["all"] == 4
    assert result["timeframe_counts"]["1m"] == 2
    assert result["timeframe_counts"]["15m"] == 1
    assert result["capital_counts"] == {"all": 4, "100U": 4, "1000U": 0}


def test_strategy_type_bucket_uses_explicit_ai_markers() -> None:
    service = StrategyService()

    assert service._strategy_type_bucket(
        {
            "name": "[合约][15M][CTA] BTC · EMA趋势跟踪 · 100U",
            "config": {"strategy_key": "contract_trailing_stop_cta"},
        }
    ) == "cta"
    assert service._strategy_type_bucket(
        {
            "name": "[合约][AI] Top20 · AI自主 · 100U",
            "config": {"market_observation_mode": "ai_decides"},
        }
    ) == "ai"
    assert service._strategy_type_bucket(
        {
            "name": "[合约][1M][做市] SOL · 趋势过滤库存做市 · 100U",
            "config": {"strategy_type": "market_making"},
        }
    ) == "market_making"
