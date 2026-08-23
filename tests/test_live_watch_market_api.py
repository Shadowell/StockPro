import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import live
from app.core.errors import register_exception_handlers
from app.db.local_db import LocalDatabase
from app.services import live_account_service
from app.services.live_signal_execution_service import LiveSignalExecutionService


def build_client() -> TestClient:
    app = FastAPI()
    app.include_router(live.router, prefix="/api/v2/live")
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def _temp_db(tmp_path, monkeypatch) -> LocalDatabase:
    database = LocalDatabase(str(tmp_path / "bitpro-live-watch.db"))
    database.init_db()
    if hasattr(live, "_clear_live_private_read_cache"):
        live._clear_live_private_read_cache()
    service = LiveSignalExecutionService(database)
    monkeypatch.setattr(live, "db", database)
    monkeypatch.setattr(live_account_service, "db", database)
    monkeypatch.setattr(live, "live_signal_execution_service", service)
    monkeypatch.setattr(live_account_service, "validate_account_id", lambda account_id: account_id or "default")
    monkeypatch.setattr(
        live_account_service,
        "exchange_alias_for_account",
        lambda account_id: "okx" if (account_id or "default") == "default" else f"okx:{account_id}",
    )
    return database


def _seed_execution(
    service: LiveSignalExecutionService,
    *,
    strategy_id: int,
    account_id: str = "default",
    symbol: str = "OPENAI/USDT:USDT",
    side: str = "long",
    action: str = "open",
    status: str = "filled",
    price: float = 1575.0,
    quantity: float = 1.2,
):
    subscription = service.upsert_subscription(
        source_strategy_id=strategy_id,
        account_id=account_id,
        status="running",
    )
    event = service.insert_signal_event(
        source_strategy_id=strategy_id,
        exchange="okx",
        market_type="swap",
        action=action,
        symbol=symbol,
        side=side,
        price=price,
        quantity=quantity,
        paper_status="filled",
    )
    execution = service._insert_execution(
        event_id=event["id"],
        subscription=subscription,
        exchange="okx",
        status=status,
        live_order_id=f"order-{strategy_id}-{symbol}",
        request_payload={"client_order_id": f"bpls{strategy_id}", "action": action, "side": side},
        response_payload={
            "order_id": f"order-{strategy_id}-{symbol}",
            "client_order_id": f"bpls{strategy_id}",
            "status": status,
            "price": price,
            "filled": quantity,
        },
        error=None if status in {"filled", "closed"} else "not filled",
    )
    return event, execution


def test_live_watchlist_only_returns_bitpro_strategy_live_order_symbols(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    strategy_id = database.save_strategy(
        "[合约] Watch Source",
        "class Demo: pass",
        config={"strategy_key": "watch", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["OPENAI/USDT:USDT"],
    )
    service = live.live_signal_execution_service
    _seed_execution(service, strategy_id=strategy_id, symbol="OPENAI/USDT:USDT", status="filled")
    _seed_execution(service, strategy_id=strategy_id, symbol="OPENAI/USDT:USDT", status="skipped")
    _seed_execution(service, strategy_id=strategy_id, account_id="other", symbol="SPCX/USDT:USDT", status="filled")
    _seed_execution(service, strategy_id=strategy_id, symbol="ANTHROPIC/USDT:USDT", status="failed")

    class FakeTradingService:
        async def get_positions(self, exchange, symbol=None):
            return [{"symbol": "OPENAI/USDT:USDT", "contracts": 1.0, "side": "long"}]

    monkeypatch.setattr(live, "trading_service", FakeTradingService())

    response = build_client().get("/api/v2/live/watchlist?account_id=default")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["account_id"] == "default"
    assert [item["symbol"] for item in data["items"]] == ["OPENAI/USDT:USDT"]
    assert data["items"][0]["source_strategy_name"] == "[合约] Watch Source"
    assert data["items"][0]["order_count"] == 1


def test_live_watchlist_excludes_symbols_without_current_open_positions(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    strategy_id = database.save_strategy(
        "[合约] Watch Position Source",
        "class Demo: pass",
        config={"strategy_key": "watch", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["OPENAI/USDT:USDT", "SPCX/USDT:USDT"],
    )
    service = live.live_signal_execution_service
    _seed_execution(service, strategy_id=strategy_id, symbol="OPENAI/USDT:USDT", status="filled")
    _seed_execution(service, strategy_id=strategy_id, symbol="SPCX/USDT:USDT", status="closed")

    class FakeTradingService:
        async def get_positions(self, exchange, symbol=None):
            return [
                {"symbol": "OPENAI/USDT:USDT", "contracts": 1.0, "side": "long"},
                {"symbol": "SPCX/USDT:USDT", "contracts": 0.0, "side": "long"},
            ]

    monkeypatch.setattr(live, "trading_service", FakeTradingService())

    response = build_client().get("/api/v2/live/watchlist?account_id=default")

    assert response.status_code == 200
    assert [item["symbol"] for item in response.json()["data"]["items"]] == ["OPENAI/USDT:USDT"]


def test_live_watchlist_applies_limit_after_current_position_filter(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    strategy_id = database.save_strategy(
        "[合约] Watch Limit Source",
        "class Demo: pass",
        config={"strategy_key": "watch", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["OPENAI/USDT:USDT", "SPCX/USDT:USDT"],
    )
    service = live.live_signal_execution_service
    _seed_execution(service, strategy_id=strategy_id, symbol="OPENAI/USDT:USDT", status="filled")
    _seed_execution(service, strategy_id=strategy_id, symbol="SPCX/USDT:USDT", status="filled")

    class FakeTradingService:
        async def get_positions(self, exchange, symbol=None):
            return [{"symbol": "OPENAI/USDT:USDT", "contracts": 1.0, "side": "long"}]

    monkeypatch.setattr(live, "trading_service", FakeTradingService())

    response = build_client().get("/api/v2/live/watchlist?account_id=default&limit=1")

    assert response.status_code == 200
    assert [item["symbol"] for item in response.json()["data"]["items"]] == ["OPENAI/USDT:USDT"]


def test_live_watchlist_reuses_cached_current_positions(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    if hasattr(live, "_clear_live_private_read_cache"):
        live._clear_live_private_read_cache()
    strategy_id = database.save_strategy(
        "[合约] Watch Cached Positions",
        "class Demo: pass",
        config={"strategy_key": "watch", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["OPENAI/USDT:USDT"],
    )
    service = live.live_signal_execution_service
    _seed_execution(service, strategy_id=strategy_id, symbol="OPENAI/USDT:USDT", status="filled")
    calls = {"positions": 0}

    class FakeTradingService:
        async def get_positions(self, exchange, symbol=None):
            calls["positions"] += 1
            return [{"symbol": "OPENAI/USDT:USDT", "contracts": 1.0, "side": "long"}]

    monkeypatch.setattr(live, "trading_service", FakeTradingService())
    client = build_client()

    first = client.get("/api/v2/live/watchlist?account_id=default")
    second = client.get("/api/v2/live/watchlist?account_id=default")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["items"] == second.json()["data"]["items"]
    assert calls["positions"] == 1


def test_live_watch_markers_return_only_actual_filled_strategy_executions(tmp_path, monkeypatch):
    database = _temp_db(tmp_path, monkeypatch)
    strategy_id = database.save_strategy(
        "[合约] Marker Source",
        "class Demo: pass",
        config={"strategy_key": "watch", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["OPENAI/USDT:USDT"],
    )
    service = live.live_signal_execution_service
    _seed_execution(service, strategy_id=strategy_id, side="long", action="open", status="filled", price=1575.0)
    _seed_execution(service, strategy_id=strategy_id, side="short", action="open", status="closed", price=1600.0)
    _seed_execution(service, strategy_id=strategy_id, side="long", action="open", status="failed", price=1500.0)

    response = build_client().get(
        "/api/v2/live/watchlist/markers?account_id=default&symbol=OPENAI/USDT:USDT"
    )

    assert response.status_code == 200
    markers = response.json()["data"]["markers"]
    assert [marker["label"] for marker in markers] == ["B", "S"]
    assert [marker["action"] for marker in markers] == ["open_long", "open_short"]
    assert [marker["price"] for marker in markers] == [1575.0, 1600.0]
    assert all(marker["source_strategy_name"] == "[合约] Marker Source" for marker in markers)


def test_live_watch_market_uses_real_market_services_without_fallback_mock(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)

    class FakeMarketDomainService:
        async def get_ticker(self, exchange, symbol):
            return {"symbol": symbol, "last": 1575.0, "percentage": 5.83, "high": 1605.0, "low": 1420.3}

        async def get_klines(self, exchange, symbol, timeframe="15m", limit=200, start=None, end=None):
            return [[1, 1500.0, 1600.0, 1490.0, 1575.0, 57.2]]

        async def get_orderbook(self, exchange, symbol, limit=20):
            return {"bids": [[1574.9, 1.0]], "asks": [[1575.1, 1.0]]}

        async def get_trades(self, exchange, symbol, limit=50):
            return [{"timestamp": 1, "price": 1575.0, "amount": 0.5, "side": "buy"}]

    class FakeTradingService:
        async def get_positions(self, exchange, symbol=None):
            return [{"symbol": symbol, "contracts": 1.0, "unrealized_pnl": 12.3}]

    monkeypatch.setattr(live, "market_domain_service", FakeMarketDomainService())
    monkeypatch.setattr(live, "trading_service", FakeTradingService())

    response = build_client().get(
        "/api/v2/live/watchlist/market?account_id=default&symbol=OPENAI/USDT:USDT&timeframe=15m"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["symbol"] == "OPENAI/USDT:USDT"
    assert data["timeframe"] == "15m"
    assert data["ticker"]["last"] == 1575.0
    assert data["klines"][0][4] == 1575.0
    assert data["orderbook"]["bids"][0][0] == 1574.9
    assert data["recent_trades"][0]["side"] == "buy"
    assert data["positions"][0]["contracts"] == 1.0


def test_live_watch_market_uses_selected_binance_usdm_public_market_source(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    monkeypatch.setattr(live_account_service, "validate_live_deployable_account_id", lambda account_id: account_id)
    monkeypatch.setattr(
        live_account_service,
        "exchange_alias_for_account",
        lambda account_id: "binanceusdm:binance" if account_id == "binance" else "okx",
    )
    market_calls = []
    position_calls = []

    class FakeMarketDomainService:
        async def get_ticker(self, exchange, symbol):
            market_calls.append(("ticker", exchange, symbol))
            return {"symbol": symbol, "last": 0.28}

        async def get_klines(self, exchange, symbol, timeframe="15m", limit=200, start=None, end=None):
            market_calls.append(("klines", exchange, symbol))
            return [[1, 0.27, 0.29, 0.26, 0.28, 19.0]]

        async def get_orderbook(self, exchange, symbol, limit=20):
            market_calls.append(("orderbook", exchange, symbol))
            return {"bids": [[0.279, 19.0]], "asks": [[0.281, 19.0]]}

        async def get_trades(self, exchange, symbol, limit=50):
            market_calls.append(("trades", exchange, symbol))
            return []

    class FakeTradingService:
        async def get_positions(self, exchange, symbol=None):
            position_calls.append((exchange, symbol))
            return [{"symbol": symbol, "contracts": 19.0, "side": "long"}]

    monkeypatch.setattr(live, "market_domain_service", FakeMarketDomainService())
    monkeypatch.setattr(live, "trading_service", FakeTradingService())

    response = build_client().get(
        "/api/v2/live/watchlist/market?account_id=binance&symbol=LAB/USDT:USDT&timeframe=15m"
    )

    assert response.status_code == 200
    assert response.json()["data"]["exchange"] == "binanceusdm:binance"
    assert {exchange for _, exchange, _ in market_calls} == {"binanceusdm"}
    assert position_calls == [("binanceusdm:binance", "LAB/USDT:USDT")]


def test_live_watch_derivatives_data_returns_null_when_okx_stat_series_unavailable(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)

    class FakeFundingDomainService:
        async def get_funding_history(self, exchange, symbol, limit=100):
            return [{"timestamp": 1, "funding_rate": 0.0001, "mark_price": 1575.0}]

    class FakeMarketDomainService:
        async def get_klines(self, exchange, symbol, timeframe="15m", limit=200, start=None, end=None):
            return []

    monkeypatch.setattr(live, "funding_domain_service", FakeFundingDomainService())
    monkeypatch.setattr(live, "market_domain_service", FakeMarketDomainService())

    response = build_client().get(
        "/api/v2/live/watchlist/derivatives-data?account_id=default&symbol=OPENAI/USDT:USDT&timeframe=15m"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["funding_rate"]["points"][0]["value"] == 0.0001
    assert data["open_interest"]["points"] is None
    assert data["long_short_ratio"]["points"] is None
    assert data["taker_volume"]["points"] is None
    assert data["basis"]["points"] is None
