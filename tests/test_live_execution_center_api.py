import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import live  # noqa: E402
from app.core.errors import BadRequestError, register_exception_handlers  # noqa: E402
from app.db.local_db import LocalDatabase  # noqa: E402
from app.services.live_signal_execution_service import LiveSignalExecutionService  # noqa: E402
from app.services import live_account_service  # noqa: E402


class FakeLiveTradingService:
    def __init__(self, positions=None):
        self.positions = list(positions or [])

    async def get_positions(self, exchange, symbol=None):
        if symbol:
            normalized = str(symbol).replace("-", "/").upper()
            return [
                item
                for item in self.positions
                if str(item.get("symbol") or "").replace("-", "/").upper() == normalized
            ]
        return list(self.positions)

    async def get_balance(self, exchange):
        return [{"currency": "USDT", "free": 1000, "used": 0, "total": 1000}]

    async def get_balance_detail(self, exchange):
        return {"trading": [{"currency": "USDT", "free": 1000, "used": 0, "total": 1000}], "funding": []}

    async def get_account_return_rates(self, exchange):
        return {}

    async def get_open_orders(self, exchange, symbol=None):
        return []

    async def get_order_history(self, exchange, symbol=None, limit=50):
        return []


def build_client() -> TestClient:
    app = FastAPI()
    app.include_router(live.router, prefix="/api/v2/live")
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def _temp_db(tmp_path, monkeypatch) -> LocalDatabase:
    database = LocalDatabase(str(tmp_path / "bitpro-live-execution.db"))
    database.init_db()
    if hasattr(live, "_clear_live_private_read_cache"):
        live._clear_live_private_read_cache()
    monkeypatch.setattr(live, "db", database)
    monkeypatch.setattr(live_account_service, "db", database)
    monkeypatch.setattr(live, "live_signal_execution_service", LiveSignalExecutionService(database))
    monkeypatch.setattr(live, "trading_service", FakeLiveTradingService())
    monkeypatch.setattr(live, "_git_commit_ref", lambda: "test-sha")
    monkeypatch.setattr(
        live_account_service,
        "validate_okx_account_permissions",
        lambda **kwargs: {
            "can_read": True,
            "can_trade": True,
            "checked_at": "2026-05-09T00:00:00+00:00",
            "detail": "读取权限和交易权限测试通过",
        },
    )
    monkeypatch.setattr(
        live_account_service,
        "validate_binance_usdm_account_permissions",
        lambda **kwargs: {
            "can_read": True,
            "can_trade": True,
            "checked_at": "2026-07-14T00:00:00+00:00",
            "detail": "Binance USD-M 读取权限和非成交 Trade 权限测试通过",
        },
    )
    monkeypatch.setattr(
        live,
        "resolve_unified_base_strategy_class",
        lambda row: None if "Broken" in str(row.get("name") or "") else (object, row),
    )
    monkeypatch.setattr(live.strategy_engine, "get_strategy_status", lambda strategy_id: None)
    return database


def test_live_execution_strategy_settings_persist_without_deploy(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Demo Paper",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    database.save_strategy(
        "[合约] [实盘试运行] Demo",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": False, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    database.save_strategy(
        "[合约] Broken Paper",
        "class Broken: pass",
        config={"strategy_key": "broken", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["ETH/USDT:USDT"],
    )

    client = build_client()
    listed = client.get("/api/v2/live/strategies")
    assert listed.status_code == 200
    strategies = listed.json()["data"]["strategies"]
    assert [item["strategy_name"] for item in strategies] == ["[合约] Demo Paper"]

    added = client.patch(f"/api/v2/live/strategies/{paper_id}", json={"added": True})
    assert added.status_code == 200
    assert added.json()["data"]["strategy"]["added"] is True
    assert added.json()["data"]["strategy"]["deployed"] is False

    restored = client.get("/api/v2/live/strategies")
    assert restored.json()["data"]["strategies"][0]["added"] is True
    assert len(database.get_strategies()) == 3


def test_live_execution_strategy_list_batches_reads_and_caches_resolution(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    strategy_id = database.save_strategy(
        "[合约][1H][CTA] BTC · 批量读取测试 · 100U",
        "class Demo: pass",
        config={"strategy_key": "batch-demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    calls = {"rows": 0, "settings": 0, "bindings": 0, "accounts": 0, "subscriptions": 0, "resolve": 0, "to_thread": 0}
    original_get_strategies = database.get_strategies
    original_settings = live._live_strategy_settings_by_id
    original_bindings = live._live_strategy_account_bindings_by_strategy
    original_accounts = live_account_service.list_accounts
    original_subscriptions = live.live_signal_execution_service.list_subscriptions
    original_to_thread = asyncio.to_thread

    def get_strategies():
        calls["rows"] += 1
        return original_get_strategies()

    def get_settings():
        calls["settings"] += 1
        return original_settings()

    def get_bindings(settings=None):
        calls["bindings"] += 1
        assert settings is not None
        return original_bindings(settings)

    def list_accounts():
        calls["accounts"] += 1
        return original_accounts()

    def list_subscriptions(**kwargs):
        calls["subscriptions"] += 1
        assert kwargs.get("source_strategy_id") is None
        return original_subscriptions(**kwargs)

    def resolve(row):
        calls["resolve"] += 1
        return object, row

    async def tracked_to_thread(func, *args, **kwargs):
        calls["to_thread"] += 1
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(database, "get_strategies", get_strategies)
    monkeypatch.setattr(live, "_live_strategy_settings_by_id", get_settings)
    monkeypatch.setattr(live, "_live_strategy_account_bindings_by_strategy", get_bindings)
    monkeypatch.setattr(live_account_service, "list_accounts", list_accounts)
    monkeypatch.setattr(live.live_signal_execution_service, "list_subscriptions", list_subscriptions)
    monkeypatch.setattr(live, "resolve_unified_base_strategy_class", resolve)
    monkeypatch.setattr(live.asyncio, "to_thread", tracked_to_thread)

    client = build_client()
    first = client.get("/api/v2/live/strategies")
    second = client.get("/api/v2/live/strategies")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["strategies"][0]["strategy_id"] == strategy_id
    assert calls == {
        "rows": 2,
        "settings": 2,
        "bindings": 2,
        "accounts": 2,
        "subscriptions": 2,
        "resolve": 1,
        "to_thread": 2,
    }


def test_live_execution_added_strategy_can_be_removed_before_subscription(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Added Paper",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    client = build_client()
    client.patch(f"/api/v2/live/strategies/{paper_id}", json={"added": True})

    removed = client.patch(f"/api/v2/live/strategies/{paper_id}", json={"added": False})
    listed = client.get("/api/v2/live/strategies").json()["data"]["strategies"]
    restored = [item for item in listed if item["strategy_id"] == paper_id][0]

    assert removed.status_code == 200
    assert removed.json()["data"]["strategy"]["added"] is False
    assert restored["added"] is False
    assert restored["account_ids"] == []


def test_live_execution_added_strategy_restores_after_backend_restart_when_resolver_unavailable(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Restart Paper",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    client = build_client()
    added = client.patch(f"/api/v2/live/strategies/{paper_id}", json={"added": True})
    assert added.status_code == 200

    restarted = LocalDatabase(str(tmp_path / "bitpro-live-execution.db"))
    restarted.init_db()
    monkeypatch.setattr(live, "db", restarted)
    monkeypatch.setattr(live_account_service, "db", restarted)
    monkeypatch.setattr(live, "resolve_unified_base_strategy_class", lambda row: None)

    restored = build_client().get("/api/v2/live/strategies")
    assert restored.status_code == 200
    strategies = restored.json()["data"]["strategies"]
    strategy = next((item for item in strategies if item["strategy_id"] == paper_id), None)
    assert strategy is not None
    assert strategy["added"] is True
    assert strategy["deployable"] is False
    assert strategy["account_ids"] == ["default"]


def test_live_execution_strategy_can_bind_multiple_accounts(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约][1H][CTA] BTC · 多账户预检测试 · 100U",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    client = build_client()
    created = client.post(
        "/api/v2/live/accounts",
        json={
            "name": "Second Account",
            "api_key": "abcd1234efgh5678",
            "api_secret": "secret-value",
            "passphrase": "pass-value",
        },
    )
    account_id = created.json()["data"]["account"]["account_id"]

    first = client.patch(f"/api/v2/live/strategies/{paper_id}", json={"added": True, "account_id": "default"})
    second = client.patch(f"/api/v2/live/strategies/{paper_id}", json={"added": True, "account_id": account_id})
    listed = client.get("/api/v2/live/strategies")

    assert first.status_code == 200
    assert second.status_code == 200
    strategy = listed.json()["data"]["strategies"][0]
    assert strategy["added"] is True
    assert strategy["account_ids"] == ["default", account_id]
    assert [item["account_id"] for item in strategy["account_bindings"]] == ["default", account_id]

    removed = client.patch(
        f"/api/v2/live/strategies/{paper_id}",
        json={"account_id": "default", "bind_account": False},
    )
    remaining = removed.json()["data"]["strategy"]
    assert remaining["added"] is True
    assert remaining["account_ids"] == [account_id]

    removed_last = client.patch(
        f"/api/v2/live/strategies/{paper_id}",
        json={"account_id": account_id, "bind_account": False},
    )
    empty = removed_last.json()["data"]["strategy"]
    assert empty["added"] is True
    assert empty["account_ids"] == []
    assert empty["account_bindings"] == []

    restored = client.get("/api/v2/live/strategies")
    restored_strategy = next(
        item for item in restored.json()["data"]["strategies"] if item["strategy_id"] == paper_id
    )
    assert restored_strategy["added"] is True
    assert restored_strategy["account_ids"] == []


def test_live_execution_can_create_and_read_selected_binance_usdm_account(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    client = build_client()

    created = client.post(
        "/api/v2/live/accounts",
        json={
            "name": "Binance USD-M Main",
            "exchange": "binanceusdm",
            "api_key": "binance-api-key",
            "api_secret": "binance-api-secret",
        },
    )

    assert created.status_code == 200
    account = created.json()["data"]["account"]
    account_id = account["account_id"]
    assert account["exchange"] == "binanceusdm"
    assert account["exchange_alias"] == f"binanceusdm:{account_id}"
    assert account["can_trade"] is True
    assert "api_secret" not in account

    positions = client.get(f"/api/v2/live/accounts/{account_id}/positions")
    assert positions.status_code == 200
    # USD-M wallet balances must not be displayed as fabricated spot positions.
    assert positions.json()["data"]["positions"] == []


def test_binance_usdm_order_history_without_symbol_queries_known_contracts(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    client = build_client()
    created = client.post(
        "/api/v2/live/accounts",
        json={
            "name": "Binance USD-M Orders",
            "exchange": "binanceusdm",
            "api_key": "binance-api-key",
            "api_secret": "binance-api-secret",
        },
    )
    account_id = created.json()["data"]["account"]["account_id"]
    strategy_id = database.save_strategy(
        "[合约][15M][CTA] SOL/BTC · 订单历史回归 · 100U",
        "class Demo: pass",
        config={"strategy_key": "binance_history", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["SOL/USDT:USDT", "BTC/USDT:USDT"],
    )
    service = live.live_signal_execution_service
    subscription = service.upsert_subscription(
        source_strategy_id=strategy_id,
        account_id=account_id,
        status="running",
    )
    for symbol in ("SOL/USDT:USDT", "BTC/USDT:USDT"):
        event = service.insert_signal_event(
            source_strategy_id=strategy_id,
            exchange="okx",
            market_type="swap",
            action="open",
            symbol=symbol,
            side="long",
            price=100.0,
            quantity=1.0,
        )
        service._insert_execution(
            event_id=event["id"],
            subscription=subscription,
            exchange=f"binanceusdm:{account_id}",
            status="filled",
            live_order_id=f"{symbol}-order",
            request_payload={},
            response_payload={},
        )

    calls = []

    class FakeTradingService:
        async def get_positions(self, exchange, symbol=None):
            return [{"symbol": "SOL/USDT:USDT", "contracts": 1.0, "side": "long"}]

        async def get_order_history(self, exchange, symbol=None, limit=50):
            calls.append((exchange, symbol, limit))
            if not symbol:
                return []
            return [
                {
                    "id": f"{symbol}-order",
                    "symbol": symbol,
                    "status": "closed",
                    "timestamp": 200 if symbol.startswith("SOL/") else 100,
                }
            ]

    monkeypatch.setattr(live, "trading_service", FakeTradingService())

    response = client.get(f"/api/v2/live/accounts/{account_id}/orders/history?limit=100")

    assert response.status_code == 200
    orders = response.json()["data"]["orders"]
    assert [order["symbol"] for order in orders] == ["SOL/USDT:USDT", "BTC/USDT:USDT"]
    assert {symbol for _, symbol, _ in calls} == {"SOL/USDT:USDT", "BTC/USDT:USDT"}
    assert all(exchange == f"binanceusdm:{account_id}" for exchange, _, _ in calls)
    assert all(limit == 100 for _, _, limit in calls)


def test_binance_usdm_contract_precheck_uses_non_matching_order_test(monkeypatch):
    calls = []

    class FakeNativeBinance:
        markets = {
            "BTC/USDT:USDT": {
                "id": "BTCUSDT",
                "swap": True,
                "linear": True,
                "active": True,
                "limits": {"amount": {"min": 0.001}},
            }
        }

        def fapiPrivateGetPositionSideDual(self, payload):
            calls.append(("position_mode", payload))
            return {"dualSidePosition": True}

        def fapiPrivatePostOrderTest(self, payload):
            calls.append(("order_test", dict(payload)))
            return {}

    class FakeBinanceExchange:
        def __init__(self):
            self.exchange = FakeNativeBinance()

        def load_markets(self):
            calls.append(("markets", None))

    monkeypatch.setattr(live.exchange_manager, "get_exchange", lambda name: FakeBinanceExchange())

    result = asyncio.run(
        live._live_contract_account_precheck(
            exchange="binanceusdm:binance_demo",
            live_cfg={"market_type": "swap", "contract_trade_symbols": ["BTC/USDT:USDT"]},
            symbols=["BTC/USDT:USDT"],
        )
    )

    assert result["passed"] is True
    payload = next(value for name, value in calls if name == "order_test")
    assert payload == {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "MARKET",
        "quantity": "0.001",
        "positionSide": "LONG",
    }


def test_paper_position_close_endpoint_routes_to_paper_broker(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Paper Close Demo",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    calls = []

    async def fake_close_paper_position(strategy_id, *, symbol, side=None, market_type=None):
        calls.append(
            {
                "strategy_id": strategy_id,
                "symbol": symbol,
                "side": side,
                "market_type": market_type,
            }
        )
        return {"status": "filled", "symbol": symbol, "pos_side": side, "action": "close"}

    monkeypatch.setattr(live.strategy_engine, "close_paper_position", fake_close_paper_position)
    client = build_client()

    response = client.post(
        "/api/v2/live/positions/close",
        json={
            "instance_id": paper_id,
            "symbol": "BTC/USDT:USDT",
            "side": "long",
            "market_type": "swap",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["closed"] is True
    assert calls == [
        {
            "strategy_id": paper_id,
            "symbol": "BTC/USDT:USDT",
            "side": "long",
            "market_type": "swap",
        }
    ]


def test_paper_position_close_endpoint_treats_missing_position_as_stale_success(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Paper Close Already Gone",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    async def fake_close_paper_position(strategy_id, *, symbol, side=None, market_type=None):
        return {"status": "skipped", "reason": "no_position", "symbol": symbol}

    monkeypatch.setattr(live.strategy_engine, "close_paper_position", fake_close_paper_position)
    client = build_client()

    response = client.post(
        "/api/v2/live/positions/close",
        json={
            "instance_id": paper_id,
            "symbol": "BTC/USDT:USDT",
            "side": "short",
            "market_type": "swap",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["closed"] is False
    assert data["stale"] is True
    assert "已不存在" in data["message"]


def test_paper_position_close_endpoint_rejects_live_strategy(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    live_id = database.save_strategy(
        "[合约] Live Close Demo",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": False, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    calls = []

    async def fake_close_paper_position(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "filled"}

    monkeypatch.setattr(live.strategy_engine, "close_paper_position", fake_close_paper_position)
    client = build_client()

    response = client.post(
        "/api/v2/live/positions/close",
        json={"instance_id": live_id, "symbol": "BTC/USDT:USDT", "side": "long", "market_type": "swap"},
    )

    assert response.status_code == 400
    assert "仅支持模拟盘" in str(response.json())
    assert calls == []


def test_live_account_permission_check_uses_read_and_trade_probe(monkeypatch):
    calls = []

    class FakeNativeOKX:
        def fetch_balance(self, params):
            calls.append(("read", params))
            return {"USDT": {"free": 1}}

        def privatePostTradeCancelOrder(self, payload):
            calls.append(("trade", payload))
            return {"code": "1", "data": [{"sCode": "51603", "sMsg": "Order does not exist"}]}

    class FakeOKXExchange:
        def __init__(self, config):
            calls.append(("config", config))
            self.exchange = FakeNativeOKX()

        def initialize(self):
            calls.append(("initialize", None))

    monkeypatch.setattr(live_account_service, "OKXExchange", FakeOKXExchange)

    result = live_account_service.validate_okx_account_permissions(
        api_key="api-key",
        api_secret="api-secret",
        passphrase="pass",
        testnet=True,
    )

    assert result["can_read"] is True
    assert result["can_trade"] is True
    assert calls[0] == (
        "config",
        {
            "api_key": "api-key",
            "api_secret": "api-secret",
            "passphrase": "pass",
            "testnet": True,
        },
    )
    assert ("read", {"type": "trading"}) in calls
    trade_payload = next(payload for action, payload in calls if action == "trade")
    assert trade_payload["instId"] == "BTC-USDT"
    assert trade_payload["clOrdId"].startswith("bpperm")
    assert "_" not in trade_payload["clOrdId"]


def test_binance_usdm_permission_check_uses_hedge_safe_order_test(monkeypatch):
    calls = []

    class FakeNativeBinance:
        def fetch_balance(self, params):
            calls.append(("read", params))
            return {"USDT": {"free": 1}}

        def market(self, symbol):
            assert symbol == "BTC/USDT:USDT"
            return {"id": "BTCUSDT", "limits": {"amount": {"min": 0.001}}}

        def amount_to_precision(self, symbol, amount):
            return "0.001"

        def fapiPrivateGetPositionSideDual(self, payload):
            calls.append(("position_mode", payload))
            return {"dualSidePosition": True}

        def fapiPrivatePostOrderTest(self, payload):
            calls.append(("trade", dict(payload)))
            return {}

    class FakeBinanceExchange:
        def __init__(self, config):
            calls.append(("config", config))
            self.exchange = FakeNativeBinance()

        def initialize(self):
            calls.append(("initialize", None))

        def fetch_balance(self):
            return self.exchange.fetch_balance({"type": "future"})

        def load_markets(self):
            calls.append(("markets", None))

    monkeypatch.setattr(live_account_service, "BinanceUsdmExchange", FakeBinanceExchange)

    result = live_account_service.validate_binance_usdm_account_permissions(
        api_key="api-key",
        api_secret="api-secret",
        testnet=True,
    )

    assert result["can_trade"] is True
    assert ("read", {"type": "future"}) in calls
    trade_payload = next(payload for action, payload in calls if action == "trade")
    assert trade_payload == {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "MARKET",
        "quantity": "0.001",
        "positionSide": "LONG",
    }


def test_live_account_create_rejects_when_trade_permission_check_fails(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)

    def fail_permission(**kwargs):
        raise BadRequestError("账户 API 交易权限测试失败：当前 API Key 缺少 Trade 权限")

    monkeypatch.setattr(live_account_service, "validate_okx_account_permissions", fail_permission)
    client = build_client()

    created = client.post(
        "/api/v2/live/accounts",
        json={
            "name": "Read Only Account",
            "api_key": "abcd1234efgh5678",
            "api_secret": "secret-value",
            "passphrase": "pass-value",
        },
    )
    accounts = client.get("/api/v2/live/accounts")

    assert created.status_code == 400
    assert "交易权限测试失败" in str(created.json())
    account_ids = [item["account_id"] for item in accounts.json()["data"]["accounts"]]
    account_names = [item["name"] for item in accounts.json()["data"]["accounts"]]
    assert "default" in account_ids
    assert "Read Only Account" not in account_names


def test_live_execution_preflight_failure_does_not_create_live_strategy(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Demo Paper",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    async def fake_preflight(body, prepared=None):
        return {"all_passed": False, "checks": [{"item": "余额", "passed": False, "detail": "不足"}]}

    monkeypatch.setattr(live, "_run_promote_preflight", fake_preflight)
    client = build_client()
    client.patch(f"/api/v2/live/strategies/{paper_id}", json={"added": True})

    result = client.post(f"/api/v2/live/strategies/{paper_id}/preflight", json={"loop_interval": 60})

    assert result.status_code == 200
    assert result.json()["data"]["preflight"]["all_passed"] is False
    assert len(database.get_strategies()) == 1


def test_live_execution_preflight_is_account_scoped_without_requiring_or_creating_binding(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Multi Account Paper",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    seen_account_ids = []

    async def fake_preflight(body, prepared=None):
        seen_account_ids.append(body.account_id)
        return {"all_passed": True, "checks": [{"item": "账户权限", "passed": True}]}

    monkeypatch.setattr(live, "_run_promote_preflight", fake_preflight)
    monkeypatch.setattr(
        live_account_service,
        "validate_live_deployable_account_id",
        lambda account_id: account_id,
    )
    client = build_client()
    added = client.patch(
        f"/api/v2/live/strategies/{paper_id}",
        json={"added": True, "account_id": "default", "bind_account": True},
    )
    assert added.status_code == 200

    result = client.post(
        f"/api/v2/live/strategies/{paper_id}/preflight",
        json={"account_id": "binance", "exchange": "binanceusdm:binance", "loop_interval": 60},
    )

    assert result.status_code == 200
    assert result.json()["data"]["preflight"]["all_passed"] is True
    assert seen_account_ids == ["binance"]
    strategy = client.get("/api/v2/live/strategies").json()["data"]["strategies"][0]
    assert [item["account_id"] for item in strategy["account_bindings"]] == ["default"]


def test_live_execution_deploy_creates_account_subscription_without_cloning_strategy(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Demo Paper",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    async def fake_preflight(body, prepared=None):
        return {
            "all_passed": True,
            "checks": [{"item": "策略存在性", "passed": True}],
            "plan": {
                "symbol_scope": "dynamic_runtime_symbols",
                "symbols": ["BTC/USDT:USDT"],
                "excluded_symbols": ["PEPE/USDT:USDT"],
            },
        }

    monkeypatch.setattr(live, "_run_promote_preflight", fake_preflight)

    client = build_client()
    client.patch(f"/api/v2/live/strategies/{paper_id}", json={"added": True})
    before_count = len(database.get_strategies())
    deployed = client.post(
        f"/api/v2/live/strategies/{paper_id}/deploy",
        json={
            "initial_equity": 100,
            "loop_interval": 60,
            "confirm_paper_reviewed": True,
            "confirm_live_risk": True,
        },
    )

    assert deployed.status_code == 200
    data = deployed.json()["data"]
    assert data["deployed"] is True
    assert data["live_strategy_id"] is None
    assert data["live_subscription_id"] > 0
    source = database.get_strategy_by_id(paper_id)
    assert source["config"]["is_paper_trading"] is True
    assert len(database.get_strategies()) == before_count

    listed = client.get("/api/v2/live/strategies").json()["data"]["strategies"][0]
    assert listed["added"] is True
    assert listed["deployed"] is True
    assert listed["deployment_strategy_id"] is None
    assert listed["account_bindings"][0]["deployment_strategy_id"] is None
    assert listed["account_bindings"][0]["live_subscription_id"] == data["live_subscription_id"]
    assert listed["account_bindings"][0]["deployment_status"] == "running"
    subscription = live.live_signal_execution_service.get_subscription(paper_id, "default")
    assert subscription["risk_config"]["allowed_live_symbols"] == ["BTC/USDT:USDT"]
    assert subscription["risk_config"]["excluded_live_symbols"] == ["PEPE/USDT:USDT"]


def test_live_execution_workspace_add_can_skip_account_binding(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Workspace Only Paper",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    client = build_client()
    added = client.patch(
        f"/api/v2/live/strategies/{paper_id}",
        json={"added": True, "bind_account": False},
    )

    assert added.status_code == 200
    strategy = added.json()["data"]["strategy"]
    assert strategy["added"] is True
    assert strategy["account_bindings"] == []


def test_live_execution_enable_account_requires_confirmation_and_does_not_bind(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Confirmed Enable Paper",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    client = build_client()
    client.patch(
        f"/api/v2/live/strategies/{paper_id}",
        json={"added": True, "bind_account": False},
    )

    enabled = client.post(
        f"/api/v2/live/strategies/{paper_id}/enable-account",
        json={"account_id": "default", "confirm_paper_reviewed": False, "confirm_live_risk": False},
    )

    assert enabled.status_code == 400
    strategy = client.get("/api/v2/live/strategies").json()["data"]["strategies"][0]
    assert strategy["account_bindings"] == []
    assert live.live_signal_execution_service.get_subscription(paper_id, "default") is None


def test_live_execution_enable_account_preflight_failure_does_not_bind_or_subscribe(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Failed Enable Paper",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    async def fake_preflight(body, prepared=None):
        return {"all_passed": False, "checks": [{"item": "止盈止损保护", "passed": False, "detail": "缺少止损"}]}

    monkeypatch.setattr(live, "_run_promote_preflight", fake_preflight)
    client = build_client()
    client.patch(
        f"/api/v2/live/strategies/{paper_id}",
        json={"added": True, "bind_account": False},
    )

    enabled = client.post(
        f"/api/v2/live/strategies/{paper_id}/enable-account",
        json={
            "account_id": "default",
            "confirm_paper_reviewed": True,
            "confirm_live_risk": True,
        },
    )

    assert enabled.status_code == 200
    assert enabled.json()["data"]["deployed"] is False
    strategy = client.get("/api/v2/live/strategies").json()["data"]["strategies"][0]
    assert strategy["account_bindings"] == []
    assert live.live_signal_execution_service.get_subscription(paper_id, "default") is None


def test_live_execution_enable_account_binds_and_starts_subscription_after_preflight(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Enabled Account Paper",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    async def fake_preflight(body, prepared=None):
        return {
            "all_passed": True,
            "checks": [{"item": "止盈止损保护", "passed": True, "detail": "已配置"}],
            "plan": {"symbol_scope": "strategy_symbols", "symbols": ["BTC/USDT:USDT"]},
        }

    monkeypatch.setattr(live, "_run_promote_preflight", fake_preflight)
    client = build_client()
    client.patch(
        f"/api/v2/live/strategies/{paper_id}",
        json={"added": True, "bind_account": False},
    )

    enabled = client.post(
        f"/api/v2/live/strategies/{paper_id}/enable-account",
        json={
            "account_id": "default",
            "confirm_paper_reviewed": True,
            "confirm_live_risk": True,
        },
    )

    assert enabled.status_code == 200
    data = enabled.json()["data"]
    assert data["deployed"] is True
    assert data["started"] is True
    strategy = data["strategy"]
    assert strategy["account_bindings"][0]["account_id"] == "default"
    assert strategy["account_bindings"][0]["deployment_status"] == "running"
    subscription = live.live_signal_execution_service.get_subscription(paper_id, "default")
    assert subscription is not None
    assert subscription["status"] == "running"


def test_live_execution_activation_failure_stops_subscription_and_removes_binding(monkeypatch):
    binding_writes = []
    subscription_statuses = []

    monkeypatch.setattr(
        live,
        "_live_strategy_account_bindings_by_strategy",
        lambda: {},
    )
    monkeypatch.setattr(
        live,
        "_upsert_live_strategy_account_binding",
        lambda strategy_id, **kwargs: binding_writes.append({"strategy_id": strategy_id, **kwargs}),
    )
    monkeypatch.setattr(
        live.live_signal_execution_service,
        "upsert_subscription",
        lambda **kwargs: {"id": 77, "status": kwargs["status"]},
    )
    monkeypatch.setattr(
        live.live_signal_execution_service,
        "set_subscription_status",
        lambda **kwargs: subscription_statuses.append(kwargs),
    )
    monkeypatch.setattr(
        live,
        "_upsert_live_strategy_setting",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("workspace write failed")),
    )

    with pytest.raises(RuntimeError, match="workspace write failed"):
        live._activate_live_subscription(
            strategy_id=23,
            account_id="default",
            risk_config={"max_notional_usdt": 20},
            start_immediately=True,
        )

    assert subscription_statuses == [
        {"source_strategy_id": 23, "account_id": "default", "status": "stopped"}
    ]
    assert binding_writes[-1]["added"] is False
    assert binding_writes[-1]["status"] == "removed"


def test_live_execution_activation_failure_restores_existing_binding(monkeypatch):
    binding_writes = []

    monkeypatch.setattr(
        live,
        "_live_strategy_account_bindings_by_strategy",
        lambda: {
            23: {
                "default": {
                    "added": True,
                    "status": "preflight_passed",
                    "risk_config": {"max_notional_usdt": 10},
                    "deployment_strategy_id": None,
                }
            }
        },
    )
    monkeypatch.setattr(
        live,
        "_upsert_live_strategy_account_binding",
        lambda strategy_id, **kwargs: binding_writes.append({"strategy_id": strategy_id, **kwargs}),
    )
    monkeypatch.setattr(
        live.live_signal_execution_service,
        "upsert_subscription",
        lambda **kwargs: {"id": 77, "status": kwargs["status"]},
    )
    monkeypatch.setattr(live.live_signal_execution_service, "set_subscription_status", lambda **kwargs: None)
    monkeypatch.setattr(
        live,
        "_upsert_live_strategy_setting",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("workspace write failed")),
    )

    with pytest.raises(RuntimeError, match="workspace write failed"):
        live._activate_live_subscription(
            strategy_id=23,
            account_id="default",
            risk_config={"max_notional_usdt": 20},
            start_immediately=True,
        )

    restored = binding_writes[-1]
    assert restored["added"] is True
    assert restored["status"] == "preflight_passed"
    assert restored["risk_config"] == {"max_notional_usdt": 10}


def test_live_preflight_rejects_missing_exit_protection_without_source_position_gate(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Unsafe Position Paper",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    row = database.get_strategy_by_id(paper_id)
    monkeypatch.setattr(live, "resolve_unified_base_strategy_class", lambda candidate: (object, candidate))
    prepared = {
        "source": row,
        "source_cfg": {"is_paper_trading": True, "market_type": "swap"},
        "live_cfg": {
            "is_paper_trading": False,
            "market_type": "swap",
            "exchange": "okx",
            "live_account_id": "default",
            "trade_symbols": ["BTC/USDT:USDT"],
            "initial_capital": 100,
            "loop_interval_sec": 60,
        },
        "symbols": ["BTC/USDT:USDT"],
        "symbol_scope": "strategy_symbols",
        "candidate_row": row,
    }

    checks = live._promotion_matching_checks(prepared)
    by_item = {item["item"]: item for item in checks}

    assert by_item["止盈止损保护"]["passed"] is False
    assert "硬止损" in by_item["止盈止损保护"]["detail"]
    assert "源模拟策略持仓对齐" not in by_item


def test_live_execution_subscription_stop_clears_deployed_state_but_pause_keeps_it(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Stop Binding Paper",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    async def fake_preflight(body, prepared=None):
        return {"all_passed": True, "checks": [{"item": "策略存在性", "passed": True}]}

    monkeypatch.setattr(live, "_run_promote_preflight", fake_preflight)

    client = build_client()
    client.patch(f"/api/v2/live/strategies/{paper_id}", json={"added": True})
    deployed = client.post(
        f"/api/v2/live/strategies/{paper_id}/deploy",
        json={
            "initial_equity": 100,
            "loop_interval": 60,
            "confirm_paper_reviewed": True,
            "confirm_live_risk": True,
        },
    )
    subscription_id = deployed.json()["data"]["live_subscription_id"]

    paused = client.post(f"/api/v2/live/strategies/{paper_id}/pause", json={"account_id": "default"})
    after_pause = client.get("/api/v2/live/strategies").json()["data"]["strategies"][0]
    pause_binding = after_pause["account_bindings"][0]

    assert paused.status_code == 200
    assert after_pause["deployed"] is True
    assert pause_binding["deployment_strategy_id"] is None
    assert pause_binding["live_subscription_id"] == subscription_id
    assert pause_binding["deployment_status"] == "paused"

    stopped = client.post(f"/api/v2/live/strategies/{paper_id}/stop", json={"account_id": "default"})
    after_stop = client.get("/api/v2/live/strategies").json()["data"]["strategies"][0]
    stop_binding = after_stop["account_bindings"][0]

    assert stopped.status_code == 200
    assert after_stop["added"] is True
    assert after_stop["deployed"] is False
    assert after_stop["deployment_strategy_id"] is None
    assert after_stop["account_ids"] == ["default"]
    assert stop_binding["deployment_strategy_id"] is None
    assert stop_binding["deployed"] is False
    assert stop_binding["status"] == "added"


def test_live_execution_subscription_stop_requires_positionless_account(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Stop Guard Paper",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    async def fake_preflight(body, prepared=None):
        return {"all_passed": True, "checks": [{"item": "策略存在性", "passed": True}]}

    monkeypatch.setattr(live, "_run_promote_preflight", fake_preflight)
    monkeypatch.setattr(
        live,
        "trading_service",
        FakeLiveTradingService(
            [
                {
                    "symbol": "BTC/USDT:USDT",
                    "side": "long",
                    "contracts": 0.01,
                    "entryPrice": 50000,
                    "markPrice": 51000,
                }
            ]
        ),
    )

    client = build_client()
    client.patch(f"/api/v2/live/strategies/{paper_id}", json={"added": True})
    deployed = client.post(
        f"/api/v2/live/strategies/{paper_id}/deploy",
        json={
            "initial_equity": 100,
            "loop_interval": 60,
            "confirm_paper_reviewed": True,
            "confirm_live_risk": True,
        },
    )
    assert deployed.status_code == 200

    stopped = client.post(f"/api/v2/live/strategies/{paper_id}/stop", json={"account_id": "default"})
    subscription = live.live_signal_execution_service.get_subscription(paper_id, "default")

    assert stopped.status_code == 400
    assert "请先平仓" in stopped.json()["error"]["message"]
    assert subscription["status"] == "running"


def test_live_execution_subscription_controls_do_not_touch_source_paper_runtime(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Runtime Isolation Paper",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    database.update_strategy_status(paper_id, "running", clear_run_started_at=False)
    engine_calls = []

    async def fake_preflight(body, prepared=None):
        return {"all_passed": True, "checks": [{"item": "策略存在性", "passed": True}]}

    async def unexpected_pause_strategy(strategy_id):
        engine_calls.append(("pause", strategy_id))
        raise AssertionError("live subscription pause must not pause the source paper strategy")

    async def unexpected_stop_strategy(strategy_id, *args, **kwargs):
        engine_calls.append(("stop", strategy_id))
        raise AssertionError("live subscription stop must not stop the source paper strategy")

    monkeypatch.setattr(live, "_run_promote_preflight", fake_preflight)
    monkeypatch.setattr(live.strategy_engine, "pause_strategy", unexpected_pause_strategy)
    monkeypatch.setattr(live.strategy_engine, "stop_strategy", unexpected_stop_strategy)

    client = build_client()
    client.patch(f"/api/v2/live/strategies/{paper_id}", json={"added": True})
    deployed = client.post(
        f"/api/v2/live/strategies/{paper_id}/deploy",
        json={
            "initial_equity": 100,
            "loop_interval": 60,
            "confirm_paper_reviewed": True,
            "confirm_live_risk": True,
        },
    )
    assert deployed.status_code == 200

    paused = client.post(f"/api/v2/live/strategies/{paper_id}/pause", json={"account_id": "default"})
    after_pause = database.get_strategy_by_id(paper_id)
    pause_subscription = live.live_signal_execution_service.get_subscription(paper_id, "default")

    assert paused.status_code == 200
    assert after_pause["status"] == "running"
    assert pause_subscription["status"] == "paused"

    stopped = client.post(f"/api/v2/live/strategies/{paper_id}/stop", json={"account_id": "default"})
    after_stop = database.get_strategy_by_id(paper_id)
    stop_subscription = live.live_signal_execution_service.get_subscription(paper_id, "default")

    assert stopped.status_code == 200
    assert after_stop["status"] == "running"
    assert stop_subscription["status"] == "stopped"


def test_paper_pause_is_blocked_when_running_live_subscription_uses_source(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Running Live Source",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    database.update_strategy_status(paper_id, "running", clear_run_started_at=False)
    live.live_signal_execution_service.upsert_subscription(
        source_strategy_id=paper_id,
        account_id="default",
        status="running",
        risk_config={},
    )
    engine_calls = []

    async def unexpected_pause_strategy(strategy_id):
        engine_calls.append(strategy_id)
        raise AssertionError("paper pause must be blocked before touching strategy engine")

    monkeypatch.setattr(live.strategy_engine, "pause_strategy", unexpected_pause_strategy)

    response = build_client().post("/api/v2/live/pause", json={"instance_id": paper_id})

    assert response.status_code == 400
    message = response.json()["error"]["message"]
    assert "实盘订阅" in message
    assert "暂停" in message
    assert engine_calls == []


def test_paper_stop_is_blocked_when_running_live_subscription_uses_source(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Running Live Source",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    database.update_strategy_status(paper_id, "running", clear_run_started_at=False)
    live.live_signal_execution_service.upsert_subscription(
        source_strategy_id=paper_id,
        account_id="default",
        status="running",
        risk_config={},
    )
    engine_calls = []

    async def unexpected_stop_strategy(strategy_id, *args, **kwargs):
        engine_calls.append((strategy_id, kwargs))
        raise AssertionError("paper stop must be blocked before touching strategy engine")

    monkeypatch.setattr(live.strategy_engine, "stop_strategy", unexpected_stop_strategy)

    response = build_client().post("/api/v2/live/stop", json={"instance_id": paper_id})

    assert response.status_code == 400
    message = response.json()["error"]["message"]
    assert "实盘订阅" in message
    assert "关闭" in message
    assert engine_calls == []


def test_live_execution_running_or_paused_subscription_cannot_be_removed_from_workspace(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Removed Binding Paper",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["TRX/USDT:USDT"],
    )

    async def fake_preflight(body, prepared=None):
        return {"all_passed": True, "checks": [{"item": "策略存在性", "passed": True}]}

    monkeypatch.setattr(live, "_run_promote_preflight", fake_preflight)

    client = build_client()
    client.patch(f"/api/v2/live/strategies/{paper_id}", json={"added": True})
    deployed = client.post(
        f"/api/v2/live/strategies/{paper_id}/deploy",
        json={
            "initial_equity": 100,
            "loop_interval": 60,
            "confirm_paper_reviewed": True,
            "confirm_live_risk": True,
        },
    )
    assert deployed.status_code == 200

    removed_running = client.patch(f"/api/v2/live/strategies/{paper_id}", json={"added": False})
    assert removed_running.status_code == 400
    assert "实盘订阅正在运行" in str(removed_running.json())
    visible = client.get("/api/v2/live/strategies").json()["data"]["strategies"][0]
    assert visible["deployed"] is True
    assert visible["account_bindings"][0]["status"] != "removed"

    paused = client.post(f"/api/v2/live/strategies/{paper_id}/pause", json={"account_id": "default"})
    after_pause = client.get("/api/v2/live/strategies").json()["data"]["strategies"][0]
    assert paused.status_code == 200
    assert after_pause["deployed"] is True
    assert after_pause["account_bindings"][0]["added"] is True
    assert after_pause["account_bindings"][0]["deployment_status"] == "paused"

    removed_paused = client.patch(f"/api/v2/live/strategies/{paper_id}", json={"added": False})
    assert removed_paused.status_code == 400
    assert "实盘订阅已暂停" in str(removed_paused.json())

    stopped = client.post(f"/api/v2/live/strategies/{paper_id}/stop", json={"account_id": "default"})
    after_stop = client.get("/api/v2/live/strategies").json()["data"]["strategies"][0]
    assert stopped.status_code == 200
    assert after_stop["added"] is True
    assert after_stop["deployed"] is False
    assert after_stop["account_bindings"][0]["added"] is True
    assert after_stop["account_bindings"][0]["status"] == "added"

    removed_stopped = client.patch(f"/api/v2/live/strategies/{paper_id}", json={"added": False})
    assert removed_stopped.status_code == 200
    removed_payload = removed_stopped.json()["data"]["strategy"]
    assert removed_payload["added"] is False
    assert removed_payload["account_ids"] == []
    assert removed_payload["account_bindings"] == []


def test_live_execution_account_endpoints_use_selected_okx_account(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    seen = []

    class FakeTradingService:
        async def get_balance(self, exchange):
            seen.append(("balance", exchange))
            return [
                {"currency": "USDT", "free": 12, "used": 1, "total": 13},
                {"currency": "BTC", "free": 0.01, "used": 0, "total": 0.01},
            ]

        async def get_balance_detail(self, exchange):
            seen.append(("balance_detail", exchange))
            return {
                "trading": [{"currency": "BTC", "free": 0.01, "used": 0, "total": 0.01}],
                "funding": [{"currency": "USDT", "free": 12, "used": 1, "total": 13}],
            }

        async def get_account_return_rates(self, exchange):
            seen.append(("return_rates", exchange))
            return {
                "one_day": 1.2,
                "seven_day": -2.3,
                "thirty_day": 4.56,
                "source": "okx",
            }

        async def get_positions(self, exchange, symbol=None):
            seen.append(("positions", exchange))
            return [{"symbol": symbol or "BTC/USDT:USDT", "amount": 1}]

        async def get_open_orders(self, exchange, symbol=None):
            seen.append(("open", exchange))
            return [{"id": "open-1", "symbol": symbol or "BTC/USDT:USDT"}]

        async def get_order_history(self, exchange, symbol=None, limit=50):
            seen.append(("history", exchange))
            return [{"id": "hist-1", "symbol": symbol or "BTC/USDT:USDT", "limit": limit}]

    monkeypatch.setattr(live, "trading_service", FakeTradingService())
    client = build_client()

    accounts = client.get("/api/v2/live/accounts")
    created = client.post(
        "/api/v2/live/accounts",
        json={
            "name": "Main Account",
            "api_key": "abcd1234efgh5678",
            "api_secret": "secret-value",
            "passphrase": "pass-value",
        },
    )
    account = created.json()["data"]["account"]
    account_id = account["account_id"]

    default_balance = client.get("/api/v2/live/accounts/default/balance")
    balance_detail = client.get("/api/v2/live/accounts/default/balance/detail")
    positions = client.get("/api/v2/live/accounts/default/positions?symbol=BTC/USDT:USDT")
    open_orders = client.get(f"/api/v2/live/accounts/{account_id}/orders/open")
    history = client.get(f"/api/v2/live/accounts/{account_id}/orders/history?limit=5")
    unsupported = client.get("/api/v2/live/accounts/sub-account/positions")

    assert accounts.status_code == 200
    assert accounts.json()["data"]["accounts"][0]["account_id"] == "default"
    assert created.status_code == 200
    assert account["masked_api_key"] == "abcd****5678"
    assert account["can_trade"] is True
    assert account["permission_check"]["can_trade"] is True
    assert account["permission_check_detail"] == "读取权限和交易权限测试通过"
    assert "api_secret" not in account
    assert default_balance.status_code == 200
    assert balance_detail.status_code == 200
    assert balance_detail.json()["data"]["trading"][0]["currency"] == "BTC"
    assert balance_detail.json()["data"]["return_rates"] == {
        "one_day": 1.2,
        "seven_day": -2.3,
        "thirty_day": 4.56,
        "source": "okx",
    }
    assert positions.status_code == 200
    assert positions.json()["data"]["positions"][0]["symbol"] == "BTC/USDT:USDT"
    assert positions.json()["data"]["positions"][1]["symbol"] == "BTC/USDT"
    assert positions.json()["data"]["positions"][1]["asset_type"] == "spot"
    assert open_orders.status_code == 200
    assert history.json()["data"]["orders"][0]["limit"] == 5
    assert unsupported.status_code == 400
    assert ("balance", "okx") in seen
    assert ("balance_detail", "okx") in seen
    assert ("return_rates", "okx") in seen
    assert ("positions", "okx") in seen
    assert ("open", f"okx:{account_id}") in seen
    assert ("history", f"okx:{account_id}") in seen


def test_live_account_private_reads_use_short_ttl_cache(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    if hasattr(live, "_clear_live_private_read_cache"):
        live._clear_live_private_read_cache()
    calls = {"positions": 0, "balance": 0, "history": 0}

    class FakeTradingService:
        async def get_positions(self, exchange, symbol=None):
            calls["positions"] += 1
            return [{"symbol": symbol or "BTC/USDT:USDT", "contracts": 1, "side": "long"}]

        async def get_balance(self, exchange):
            calls["balance"] += 1
            return []

        async def get_order_history(self, exchange, symbol=None, limit=50):
            calls["history"] += 1
            return [{"id": f"hist-{calls['history']}", "symbol": symbol or "BTC/USDT:USDT"}]

    monkeypatch.setattr(live, "trading_service", FakeTradingService())
    client = build_client()

    first_positions = client.get("/api/v2/live/accounts/default/positions?symbol=BTC/USDT:USDT")
    second_positions = client.get("/api/v2/live/accounts/default/positions?symbol=BTC/USDT:USDT")
    first_history = client.get("/api/v2/live/accounts/default/orders/history?limit=5")
    second_history = client.get("/api/v2/live/accounts/default/orders/history?limit=5")

    assert first_positions.status_code == 200
    assert second_positions.status_code == 200
    assert first_history.status_code == 200
    assert second_history.status_code == 200
    assert first_history.json()["data"]["orders"] == second_history.json()["data"]["orders"]
    assert calls == {"positions": 1, "balance": 1, "history": 1}


def test_live_account_asset_reads_use_one_minute_ttl_cache(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    if hasattr(live, "_clear_live_private_read_cache"):
        live._clear_live_private_read_cache()
    clock = {"now": 1_000.0}
    calls = {"balance": 0, "detail": 0, "rates": 0}

    monkeypatch.setattr(live.time, "monotonic", lambda: clock["now"])

    class FakeTradingService:
        async def get_balance(self, exchange):
            calls["balance"] += 1
            return [{"currency": "USDT", "total": calls["balance"]}]

        async def get_balance_detail(self, exchange):
            calls["detail"] += 1
            return {
                "trading": [{"currency": "USDT", "total": calls["detail"]}],
                "funding": [],
            }

        async def get_account_return_rates(self, exchange):
            calls["rates"] += 1
            return {"one_day": calls["rates"], "source": "okx"}

    monkeypatch.setattr(live, "trading_service", FakeTradingService())
    client = build_client()

    first_balance = client.get("/api/v2/live/accounts/default/balance")
    first_detail = client.get("/api/v2/live/accounts/default/balance/detail")
    second_balance = client.get("/api/v2/live/accounts/default/balance")
    second_detail = client.get("/api/v2/live/accounts/default/balance/detail")
    clock["now"] += 59.0
    within_ttl_balance = client.get("/api/v2/live/accounts/default/balance")
    within_ttl_detail = client.get("/api/v2/live/accounts/default/balance/detail")
    clock["now"] += 2.0
    expired_balance = client.get("/api/v2/live/accounts/default/balance")
    expired_detail = client.get("/api/v2/live/accounts/default/balance/detail")

    assert first_balance.status_code == 200
    assert first_detail.status_code == 200
    assert second_balance.json()["data"]["balance"] == first_balance.json()["data"]["balance"]
    assert second_detail.json()["data"]["trading"] == first_detail.json()["data"]["trading"]
    assert within_ttl_balance.json()["data"]["balance"] == first_balance.json()["data"]["balance"]
    assert within_ttl_detail.json()["data"]["return_rates"] == first_detail.json()["data"]["return_rates"]
    assert expired_balance.json()["data"]["balance"][0]["total"] == 2
    assert expired_detail.json()["data"]["trading"][0]["total"] == 2
    assert expired_detail.json()["data"]["return_rates"]["one_day"] == 2
    assert calls == {"balance": 2, "detail": 2, "rates": 2}


def test_live_account_position_close_uses_live_contract_broker(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    calls = []

    class FakeLiveContractBroker:
        def __init__(self, *, strategy_id, exchange_name, symbols, config):
            calls.append(
                {
                    "strategy_id": strategy_id,
                    "exchange_name": exchange_name,
                    "symbols": symbols,
                    "config": config,
                }
            )

        async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
            calls.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "ratio": ratio,
                    "contracts": contracts,
                    "price": price,
                }
            )
            return {
                "status": "filled",
                "symbol": symbol,
                "pos_side": side,
                "order_side": "buy" if side == "short" else "sell",
            }

    monkeypatch.setattr(live, "LiveContractBroker", FakeLiveContractBroker)
    client = build_client()

    missing_confirm = client.post(
        "/api/v2/live/accounts/default/positions/close",
        json={"symbol": "DOGE/USDT:USDT", "side": "short"},
    )
    response = client.post(
        "/api/v2/live/accounts/default/positions/close",
        json={"symbol": "DOGE/USDT:USDT", "side": "short", "confirm_live_risk": True},
    )

    assert missing_confirm.status_code == 400
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["closed"] == 1
    assert data["results"][0]["status"] == "filled"
    assert calls[0]["strategy_id"] == 0
    assert calls[0]["exchange_name"] == "okx"
    assert calls[0]["symbols"] == ["DOGE/USDT:USDT"]
    assert calls[0]["config"]["live_order_type"] == "market"
    assert calls[1] == {
        "symbol": "DOGE/USDT:USDT",
        "side": "short",
        "ratio": 1.0,
        "contracts": None,
        "price": None,
    }


def test_live_account_position_market_close_all_closes_all_sides_for_symbol(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    close_calls = []

    class FakeTradingService:
        async def get_positions(self, exchange, symbol=None):
            assert exchange == "okx"
            assert symbol == "DOGE/USDT:USDT"
            return [
                {"symbol": "DOGE/USDT:USDT", "side": "long", "contracts": 0.2},
                {"symbol": "DOGE/USDT:USDT", "side": "short", "contracts": 0.3},
                {"symbol": "ETH/USDT:USDT", "side": "long", "contracts": 0.1},
            ]

    class FakeLiveContractBroker:
        def __init__(self, *, strategy_id, exchange_name, symbols, config):
            self.symbols = symbols

        async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
            close_calls.append((symbol, side, ratio))
            return {"status": "filled", "symbol": symbol, "pos_side": side}

    monkeypatch.setattr(live, "trading_service", FakeTradingService())
    monkeypatch.setattr(live, "LiveContractBroker", FakeLiveContractBroker)
    client = build_client()

    response = client.post(
        "/api/v2/live/accounts/default/positions/close",
        json={"symbol": "DOGE/USDT:USDT", "close_all": True, "confirm_live_risk": True},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["closed"] == 2
    assert close_calls == [
        ("DOGE/USDT:USDT", "long", 1.0),
        ("DOGE/USDT:USDT", "short", 1.0),
    ]


def test_live_account_position_market_close_all_uses_side_when_pos_side_is_net(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    close_calls = []

    class FakeTradingService:
        async def get_positions(self, exchange, symbol=None):
            assert exchange == "okx"
            assert symbol == "1INCH/USDT:USDT"
            return [
                {"symbol": "1INCH/USDT:USDT", "side": "short", "pos_side": "net", "contracts": 514.0},
            ]

    class FakeLiveContractBroker:
        def __init__(self, *, strategy_id, exchange_name, symbols, config):
            self.symbols = symbols

        async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
            close_calls.append((symbol, side, ratio))
            return {"status": "filled", "symbol": symbol, "pos_side": side}

    monkeypatch.setattr(live, "trading_service", FakeTradingService())
    monkeypatch.setattr(live, "LiveContractBroker", FakeLiveContractBroker)
    client = build_client()

    response = client.post(
        "/api/v2/live/accounts/default/positions/close",
        json={"symbol": "1INCH/USDT:USDT", "close_all": True, "confirm_live_risk": True},
    )

    assert response.status_code == 200
    assert close_calls == [("1INCH/USDT:USDT", "short", 1.0)]


def test_live_execution_order_history_includes_strategy_attribution(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Attribution Source",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["DOGE/USDT:USDT"],
    )
    service = live.live_signal_execution_service
    subscription = service.upsert_subscription(
        source_strategy_id=paper_id,
        account_id="default",
        status="running",
    )
    event = service.insert_signal_event(
        source_strategy_id=paper_id,
        exchange="okx",
        market_type="swap",
        action="open",
        symbol="DOGE/USDT:USDT",
        side="short",
    )
    service._insert_execution(
        event_id=event["id"],
        subscription=subscription,
        exchange="okx",
        status="filled",
        live_order_id=None,
        request_payload={"client_order_id": "bpls1e1abc"},
        response_payload={"client_order_id": "bpls1e1abc"},
    )

    class FakeTradingService:
        async def get_order_history(self, exchange, symbol=None, limit=50):
            return [
                {
                    "id": "exchange-order-1",
                    "client_order_id": "bpls1e1abc",
                    "symbol": "DOGE/USDT:USDT",
                    "status": "closed",
                },
                {
                    "id": "manual-order-1",
                    "client_order_id": "manual-client-1",
                    "symbol": "DOGE/USDT:USDT",
                    "status": "closed",
                },
            ]

    monkeypatch.setattr(live, "trading_service", FakeTradingService())
    client = build_client()
    response = client.get("/api/v2/live/accounts/default/orders/history?limit=5")

    assert response.status_code == 200
    orders = response.json()["data"]["orders"]
    assert orders[0]["bitpro_source"] == "strategy"
    assert orders[0]["bitpro_source_label"] == "[合约] Attribution Source"
    assert orders[0]["source_strategy_id"] == paper_id
    assert orders[0]["source_strategy_name"] == "[合约] Attribution Source"
    assert orders[0]["subscription_id"] == subscription["id"]
    assert orders[0]["signal_event_id"] == event["id"]
    assert orders[1]["bitpro_source"] == "external"
    assert orders[1]["bitpro_source_label"] == "手动/外部订单"
    assert orders[1]["source_strategy_id"] is None


def test_live_execution_order_history_normalizes_okx_realized_pnl_and_fee(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)

    class FakeTradingService:
        async def get_order_history(self, exchange, symbol=None, limit=50):
            return [
                {
                    "id": "okx-order-1",
                    "symbol": "ETH/USDT:USDT",
                    "status": "closed",
                    "info": {
                        "pnl": "1.57",
                        "fee": "-0.06",
                        "feeCcy": "USDT",
                        "uTime": "1783008000000",
                    },
                }
            ]

    monkeypatch.setattr(live, "trading_service", FakeTradingService())
    client = build_client()
    response = client.get("/api/v2/live/accounts/default/orders/history?limit=5")

    assert response.status_code == 200
    order = response.json()["data"]["orders"][0]
    assert order["pnl"] == 1.57
    assert order["realized_pnl"] == 1.57
    assert order["fee"] == -0.06
    assert order["fee_currency"] == "USDT"


def test_live_execution_order_history_includes_rejected_live_executions(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    paper_id = database.save_strategy(
        "[合约] Rejected Source",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["ANTHROPIC/USDT:USDT"],
    )
    service = live.live_signal_execution_service
    subscription = service.upsert_subscription(
        source_strategy_id=paper_id,
        account_id="default",
        status="running",
    )
    event = service.insert_signal_event(
        source_strategy_id=paper_id,
        exchange="okx",
        market_type="swap",
        action="open",
        symbol="ANTHROPIC/USDT:USDT",
        side="long",
        price=1554.5,
        quantity=0.01,
    )
    execution = service._insert_execution(
        event_id=event["id"],
        subscription=subscription,
        exchange="okx",
        status="failed",
        live_order_id=None,
        request_payload={"client_order_id": "bpls1e1reject", "action": "open", "side": "long"},
        response_payload={"code": "1", "data": [{"sCode": "51000", "sMsg": "Parameter posSide error"}]},
        error="OKX rejected order: 51000 Parameter posSide error",
    )

    class FakeTradingService:
        async def get_order_history(self, exchange, symbol=None, limit=50):
            return []

    monkeypatch.setattr(live, "trading_service", FakeTradingService())
    client = build_client()
    response = client.get("/api/v2/live/accounts/default/orders/history?limit=5")

    assert response.status_code == 200
    orders = response.json()["data"]["orders"]
    assert len(orders) == 1
    assert orders[0]["id"] == f"live-execution-{execution['id']}"
    assert orders[0]["status"] == "failed"
    assert orders[0]["raw_status"] == "failed"
    assert orders[0]["bitpro_source"] == "strategy"
    assert orders[0]["bitpro_source_label"] == "[合约] Rejected Source"
    assert orders[0]["source_strategy_id"] == paper_id
    assert orders[0]["subscription_id"] == subscription["id"]
    assert orders[0]["signal_event_id"] == event["id"]
    assert orders[0]["failure_log"]["error"] == "OKX rejected order: 51000 Parameter posSide error"
    assert orders[0]["failure_log"]["response_payload"]["data"][0]["sCode"] == "51000"


# ---------------------------------------------------------------------------
# /live/stop 等实例生命周期接口的目标解析：body.strategy_type 必须显式生效
# ---------------------------------------------------------------------------


def test_resolve_instance_sid_accepts_strategy_type_in_body(monkeypatch):
    from app.api.v2.endpoints.live_support import LiveInstanceBody

    monkeypatch.setattr(live, "_active_strategy_id", 107)
    body = LiveInstanceBody(strategy_type="439")
    assert live._resolve_instance_sid(body) == 439


def test_resolve_instance_sid_prefers_explicit_instance_id_over_strategy_type():
    from app.api.v2.endpoints.live_support import LiveInstanceBody

    body = LiveInstanceBody(instance_id=12, strategy_type="439")
    assert live._resolve_instance_sid(body) == 12


def test_resolve_instance_sid_rejects_non_numeric_strategy_type():
    from app.api.v2.endpoints.live_support import LiveInstanceBody

    body = LiveInstanceBody(strategy_type="not-a-number")
    with pytest.raises(BadRequestError):
        live._resolve_instance_sid(body)


def test_resolve_instance_sid_falls_back_to_active_strategy_without_body_target(monkeypatch):
    from app.api.v2.endpoints.live_support import LiveInstanceBody

    monkeypatch.setattr(live, "_active_strategy_id", 107)
    assert live._resolve_instance_sid(LiveInstanceBody()) == 107
