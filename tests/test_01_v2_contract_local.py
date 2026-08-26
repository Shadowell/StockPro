"""
BitPro v2 契约本地测试（无外网、mock 依赖）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.v2.endpoints import funding, monitor, sync as sync_v2, system, trading  # noqa: E402
from app.core.errors import register_exception_handlers  # noqa: E402


def test_only_v2_router_is_mounted_after_cutover() -> None:
    main_source = (PROJECT_ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    api_init_source = (PROJECT_ROOT / "backend/app/api/__init__.py").read_text(encoding="utf-8")
    v2_source = (PROJECT_ROOT / "backend/app/api/v2/api.py").read_text(encoding="utf-8")

    assert "api_router_v2" in main_source
    # Legacy v1 api_router must never be mounted; strip the v2 and public
    # router names first so their substrings cannot mask a bare reference.
    stripped_main_source = main_source.replace("api_router_v2", "").replace("public_api_router", "")
    assert "api_router" not in stripped_main_source
    assert "API_" + "V1_STR" not in main_source
    assert "app.api.endpoints" not in v2_source
    assert "api_router_v2" in api_init_source
    assert "api_router" not in api_init_source.replace("api_router_v2", "")


def build_client() -> TestClient:
    app = FastAPI()
    app.include_router(system.router, prefix="/api/v2/system")
    app.include_router(funding.router, prefix="/api/v2/funding")
    app.include_router(trading.router, prefix="/api/v2/trading")
    app.include_router(monitor.router, prefix="/api/v2/monitor")
    app.include_router(sync_v2.router, prefix="/api/v2/sync")
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def test_system_exchanges_envelope(monkeypatch) -> None:
    async def fake_exchanges():
        return {"okx": "connected"}

    monkeypatch.setattr(system.system_domain_service, "exchanges", fake_exchanges)

    client = build_client()
    r = client.get("/api/v2/system/exchanges")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["exchanges"]["okx"] == "connected"


def test_funding_rates_pagination(monkeypatch) -> None:
    async def fake_rates(exchange: str, symbols=None):
        assert exchange == "okx"
        return [
            {"symbol": "BTC/USDT", "current_rate": 0.0001},
            {"symbol": "ETH/USDT", "current_rate": 0.0002},
            {"symbol": "SOL/USDT", "current_rate": 0.0003},
        ]

    monkeypatch.setattr(funding.funding_domain_service, "get_funding_rates", fake_rates)

    client = build_client()
    r = client.get("/api/v2/funding/rates?exchange=okx&offset=1&limit=1")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["meta"] == {"total": 3, "offset": 1, "limit": 1}
    assert len(body["data"]) == 1
    assert body["data"][0]["symbol"] == "ETH/USDT"


def test_trading_balance_uses_accounts_path_only(monkeypatch) -> None:
    async def fake_balance(exchange: str):
        assert exchange == "okx"
        return [{"currency": "USDT", "free": 1000, "used": 0, "total": 1000}]

    monkeypatch.setattr(trading.trading_domain_service, "get_balance", fake_balance)

    client = build_client()
    r_accounts = client.get("/api/v2/trading/accounts/balance?exchange=okx")
    r_old_alias = client.get("/api/v2/trading/balance?exchange=okx")

    assert r_accounts.status_code == 200
    assert r_old_alias.status_code == 404
    body_accounts = r_accounts.json()
    assert body_accounts["success"] is True
    assert body_accounts["data"]["balance"][0]["currency"] == "USDT"


def test_trading_spot_order_risk_reject(monkeypatch) -> None:
    async def fake_risk(*args, **kwargs):
        return {"can_trade": False, "errors": ["risk blocked"], "warnings": []}

    monkeypatch.setattr(trading.trading_service, "check_order_risk", fake_risk)

    client = build_client()
    payload = {
        "exchange": "okx",
        "symbol": "BTC/USDT",
        "side": "buy",
        "type": "market",
        "amount": 0.01,
    }
    r = client.post("/api/v2/trading/spot/order", json=payload)
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "BAD_REQUEST"
    assert "risk blocked" in str(body["error"]["details"])


def test_trading_futures_order_endpoint_maps_to_service(monkeypatch) -> None:
    calls = []

    async def fake_open_long(*args, **kwargs):
        calls.append((args, kwargs))
        return {"id": "order-1"}

    monkeypatch.setattr(trading.trading_service, "futures_open_long", fake_open_long)

    client = build_client()
    payload = {
        "exchange": "okx",
        "symbol": "BTC/USDT:USDT",
        "side": "long",
        "action": "open",
        "amount": 0.01,
        "leverage": 1,
    }
    r = client.post("/api/v2/trading/futures/order", json=payload)

    assert r.status_code == 200
    assert calls == [(("okx", "BTC/USDT:USDT", 0.01, 1, None), {})]
    body = r.json()
    assert body["success"] is True
    assert body["data"]["order"]["id"] == "order-1"


def test_monitor_alert_not_found(monkeypatch) -> None:
    monkeypatch.setattr(monitor.alert_service, "get_alerts", lambda: [])

    client = build_client()
    r = client.put("/api/v2/monitor/alerts/99?enabled=true")
    assert r.status_code == 404
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_monitor_running_strategies(monkeypatch) -> None:
    calls = []

    async def fake_running(*, refresh_marks: bool = False):
        calls.append(refresh_marks)
        assert refresh_marks is False
        return [{"strategy_id": 1, "name": "demo", "status": "running"}]

    monkeypatch.setattr(monitor.strategy_service, "get_all_running", fake_running)

    client = build_client()
    r = client.get("/api/v2/monitor/running-strategies")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"][0]["name"] == "demo"

    r_active = client.get("/api/v2/monitor/active_strategies")
    assert r_active.status_code == 200
    assert calls == [False, False]


def test_monitor_open_interest_uses_okx_public_open_interest(monkeypatch) -> None:
    calls = []

    class FakeOkxClient:
        def market(self, symbol):
            calls.append(("market", symbol))
            return {"id": "BTC-USDT-SWAP", "contractSize": 0.01}

        def publicGetPublicOpenInterest(self, params):
            calls.append(("open_interest", params))
            return {"data": [{"oi": "1234", "oiCcy": "12.34", "ts": "1772577940000"}]}

    class FakeExchange:
        exchange = FakeOkxClient()

        def load_markets(self):
            calls.append(("load_markets", None))

    monkeypatch.setattr(monitor.exchange_manager, "get_exchange", lambda exchange: FakeExchange())

    client = build_client()
    r = client.get("/api/v2/monitor/open-interest?exchange=okx&symbol=BTC/USDT:USDT")

    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["open_interest"] == 1234.0
    assert body["data"]["open_interest_btc"] == 12.34
    assert body["data"]["timestamp"] == 1772577940000
    assert calls == [
        ("load_markets", None),
        ("market", "BTC/USDT:USDT"),
        ("open_interest", {"instType": "SWAP", "instId": "BTC-USDT-SWAP"}),
    ]


def test_sync_status_envelope(monkeypatch) -> None:
    captured: dict = {}

    def fake_status(*, include_items: bool = True):
        captured["include_items"] = include_items
        return {"is_running": False, "summary": {"total_records": 12}, "details": []}

    monkeypatch.setattr(sync_v2.sync_domain_service, "status", fake_status)

    client = build_client()
    r = client.get("/api/v2/sync/status")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["is_running"] is False
    assert body["data"]["summary"]["total_records"] == 12
    # 轮询默认剥离逐项明细，避免大任务下 2MB+ 响应
    assert captured["include_items"] is False

    r2 = client.get("/api/v2/sync/status?include_items=true")
    assert r2.status_code == 200
    assert captured["include_items"] is True


def test_sync_table_stats(monkeypatch) -> None:
    monkeypatch.setattr(
        sync_v2.sync_domain_service,
        "table_stats",
        lambda: {
            "tables": [
                {
                    "table_name": "kline_1h",
                    "timeframe": "1h",
                    "exchange": "okx",
                    "symbol": "BTC/USDT",
                    "record_count": 123,
                    "first_timestamp": 1,
                    "last_timestamp": 2,
                }
            ],
            "total_records": 123,
            "total_pairs": 1,
        },
    )

    client = build_client()
    r = client.get("/api/v2/sync/table-stats")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["total_records"] == 123
    assert body["data"]["tables"][0]["table_name"] == "kline_1h"


def test_sync_quality_contract(monkeypatch) -> None:
    def fake_quality(*, exchange: str, symbols, timeframes, max_items: int):
        assert exchange == "okx"
        assert symbols == ["ETH/USDT:USDT", "LAB/USDT:USDT"]
        assert timeframes == ["12h", "1d"]
        assert max_items == 8
        return {
            "checked_at": "2026-07-08T12:00:00Z",
            "summary": {
                "checked": 4,
                "ok": 3,
                "error": 1,
                "missing": 0,
                "issue_count": 1,
                "truncated": False,
                "max_items": 8,
            },
            "items": [],
        }

    monkeypatch.setattr(sync_v2.sync_domain_service, "quality", fake_quality)

    client = build_client()
    r = client.get(
        "/api/v2/sync/quality",
        params={
            "exchange": "okx",
            "symbols": "ETH/USDT:USDT,LAB/USDT:USDT",
            "timeframes": "12h,1d",
            "max_items": 8,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["summary"]["error"] == 1


def test_sync_jobs_contract(monkeypatch) -> None:
    def fake_jobs(*, limit: int = 20, include_items: bool = True):
        assert limit == 5
        assert include_items is True
        return {
            "jobs": [
                {
                    "job_id": "job-1",
                    "exchange": "okx",
                    "status": "running",
                    "symbols": ["ETH/USDT"],
                    "timeframes": ["1m"],
                    "total_items": 1,
                    "completed_items": 0,
                    "running_items": 1,
                    "pending_items": 0,
                    "error_items": 0,
                    "progress_percent": 0.0,
                    "total_fetched": 300,
                    "total_inserted": 288,
                    "elapsed_seconds": 12.5,
                    "items": [
                        {
                            "symbol": "ETH/USDT",
                            "timeframe": "1m",
                            "status": "running",
                            "total_fetched": 300,
                            "total_inserted": 288,
                            "elapsed_seconds": 12.5,
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(sync_v2.sync_domain_service, "jobs", fake_jobs)

    client = build_client()
    r = client.get("/api/v2/sync/jobs?limit=5&include_items=true")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["jobs"][0]["job_id"] == "job-1"
    assert body["data"]["jobs"][0]["items"][0]["status"] == "running"


def test_sync_start_returns_background_ack(monkeypatch) -> None:
    def fake_create_job(payload, *, exchange=None, history_days=365):
        assert payload["exchange"] == "okx"
        assert exchange is None
        assert history_days == 90
        return {
            "job_id": "job-1",
            "exchange": "okx",
            "symbols": ["ETH/USDT"],
            "timeframes": ["1m"],
            "history_days": 30,
            "start_date": None,
            "end_date": None,
        }

    async def fake_run_job(job_id):
        assert job_id == "job-1"
        return {"status": "completed"}

    monkeypatch.setattr(sync_v2.sync_domain_service, "status", lambda: {"is_running": False})
    monkeypatch.setattr(sync_v2.sync_domain_service, "create_job", fake_create_job)
    monkeypatch.setattr(sync_v2.sync_domain_service, "run_job", fake_run_job)

    client = build_client()
    payload = {
        "exchange": "okx",
        "symbols": ["ETH/USDT"],
        "timeframes": ["1m"],
        "history_days": 30,
    }
    r = client.post("/api/v2/sync/start", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["job_id"] == "job-1"
    assert body["data"]["message"] == "同步任务已启动"
    assert body["data"]["exchange"] == "okx"
    assert body["data"]["symbols"] == ["ETH/USDT"]
    assert body["data"]["timeframes"] == ["1m"]
    assert "status" not in body["data"]


def test_sync_add_symbol_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        sync_v2.sync_domain_service,
        "add_symbol",
        lambda payload: {
            "symbol": "PEPE/USDT",
            "added": True,
            "default_symbols": ["BTC/USDT", "PEPE/USDT"],
        },
    )

    client = build_client()
    r = client.post("/api/v2/sync/symbols", json={"symbol": "pepe"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["symbol"] == "PEPE/USDT"
    assert body["data"]["added"] is True
    assert body["data"]["default_symbols"][-1] == "PEPE/USDT"


def test_sync_daily_update_contract(monkeypatch) -> None:
    def fake_create_job(payload, *, exchange=None, history_days=365):
        assert exchange == "okx"
        assert payload == {
            "symbols": ["ETH/USDT"],
            "timeframes": ["1h"],
            "start_date": "2026-05-02",
            "end_date": "2026-05-09",
        }
        assert history_days == 90
        return {
            "job_id": "daily-job-1",
            "exchange": "okx",
            "symbols": ["ETH/USDT"],
            "timeframes": ["1h"],
            "history_days": 90,
            "start_date": "2026-05-02",
            "end_date": "2026-05-09",
        }

    async def fake_run_job(job_id):
        assert job_id == "daily-job-1"
        return {"status": "completed"}

    monkeypatch.setattr(sync_v2.sync_domain_service, "status", lambda: {"is_running": False})
    monkeypatch.setattr(sync_v2.sync_domain_service, "create_job", fake_create_job)
    monkeypatch.setattr(sync_v2.sync_domain_service, "run_job", fake_run_job)

    client = build_client()
    payload = {
        "symbols": ["ETH/USDT"],
        "timeframes": ["1h"],
        "start_date": "2026-05-02",
        "end_date": "2026-05-09",
    }
    r = client.post("/api/v2/sync/daily-update?exchange=okx", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["job_id"] == "daily-job-1"
    assert body["data"]["message"] == "增量更新已启动"
    assert body["data"]["exchange"] == "okx"
    assert body["data"]["symbols"] == ["ETH/USDT"]
    assert body["data"]["timeframes"] == ["1h"]
    assert body["data"]["history_days"] == 90
    assert body["data"]["start_date"] == "2026-05-02"
    assert body["data"]["end_date"] == "2026-05-09"


def test_sync_delete_data_contract(monkeypatch) -> None:
    def fake_delete_data(payload):
        assert payload == {"exchange": "okx", "symbol": "ETH/USDT", "timeframe": "1m"}
        return {"message": "已删除 1 个K线数据文件", "deleted": 1, "deleted_files": 1}

    monkeypatch.setattr(sync_v2.sync_domain_service, "delete_data", fake_delete_data)

    client = build_client()
    payload = {"exchange": "okx", "symbol": "ETH/USDT", "timeframe": "1m"}
    r = client.post("/api/v2/sync/delete-data", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["deleted"] == 1


def test_sync_one_contract(monkeypatch) -> None:
    async def fake_sync_one(payload):
        assert payload["symbol"] == "BTC/USDT"
        assert payload["timeframe"] == "1h"
        return {
            "exchange": "okx",
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "status": "completed",
            "total_fetched": 300,
            "total_inserted": 280,
            "error": None,
        }

    monkeypatch.setattr(sync_v2.sync_domain_service, "sync_one", fake_sync_one)
    monkeypatch.setattr(sync_v2.sync_domain_service, "is_running", lambda: False)

    client = build_client()
    payload = {"exchange": "okx", "symbol": "BTC/USDT", "timeframe": "1h"}
    r = client.post("/api/v2/sync/sync-one", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["status"] == "completed"
    assert body["data"]["total_fetched"] == 300
