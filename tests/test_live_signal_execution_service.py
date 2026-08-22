import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import OrderResult
from app.db.local_db import LocalDatabase
from app.services.live_signal_execution_service import LiveSignalExecutionService
import app.services.strategy_engine as strategy_engine_module


def test_live_signal_execution_maps_renamed_spacex_contract_inst_id():
    assert (
        LiveSignalExecutionService._okx_instrument_id("SPACEX/USDT:USDT", "swap")
        == "SPCX-USDT-SWAP"
    )


class FakeLiveContractBroker:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def open_contract(self, symbol, side, notional_usdt, leverage=None, price=None):
        self.calls.append(
            {
                "kwargs": self.kwargs,
                "method": "open_contract",
                "symbol": symbol,
                "side": side,
                "notional_usdt": notional_usdt,
                "leverage": leverage,
                "price": price,
            }
        )
        return OrderResult(
            {
                "status": "filled",
                "order_id": "live-order-1",
                "client_order_id": self.kwargs["config"].get("live_client_order_id"),
                "symbol": symbol,
                "pos_side": side,
                "notional_usdt": notional_usdt,
                "leverage": leverage,
                "price": price,
            }
        )

    async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
        self.calls.append(
            {
                "kwargs": self.kwargs,
                "method": "close_contract",
                "symbol": symbol,
                "side": side,
                "ratio": ratio,
                "contracts": contracts,
                "price": price,
            }
        )
        return OrderResult(
            {
                "status": "filled",
                "order_id": "live-close-1",
                "client_order_id": self.kwargs["config"].get("live_client_order_id"),
                "symbol": symbol,
                "pos_side": side,
                "ratio": ratio,
                "contracts": contracts,
                "price": price,
            }
        )


class FakeNativeOKX:
    def __init__(self, *, pos_mode="net_mode"):
        self.pos_mode = pos_mode
        self.leverage_payloads = []
        self.orders = []

    def privateGetAccountConfig(self, params=None):
        return {"code": "0", "data": [{"posMode": self.pos_mode}]}

    def privatePostAccountSetLeverage(self, payload):
        self.leverage_payloads.append(dict(payload))
        return {"code": "0", "data": [{"sCode": "0"}]}

    def create_order(self, symbol, order_type, side, amount, price=None, params=None):
        order_id = f"ord-{len(self.orders) + 1}"
        self.orders.append(
            {
                "symbol": symbol,
                "type": order_type,
                "side": side,
                "amount": amount,
                "price": price,
                "params": dict(params or {}),
            }
        )
        return {
            "id": order_id,
            "status": "closed",
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": price,
            "info": {"data": [{"ordId": order_id, "sCode": "0"}]},
        }


class FakeExchange:
    def __init__(self, native):
        self.exchange = native
        self.positions = []

    def fetch_positions(self, symbols=None):
        return self.positions

    def fetch_ticker(self, symbol):
        return {"last": 50_000.0}


async def _fake_balance(exchange_name):
    return [{"currency": "USDT", "free": 1_000.0, "total": 1_000.0, "used": 0.0}]


def _db(tmp_path):
    database = LocalDatabase(str(tmp_path / "bitpro-live-signals.db"))
    database.init_db()
    return database


def _contract_config():
    return {
        "is_paper_trading": True,
        "market_type": "swap",
        "trade_symbols": ["BTC/USDT:USDT"],
        "max_leverage": 10,
        "position_mode": "net_mode",
        "contract_instruments": {
            "BTC/USDT:USDT": {
                "inst_id": "BTC-USDT-SWAP",
                "ct_val": 0.01,
                "lot_sz": 0.01,
                "min_sz": 0.01,
                "tick_sz": 0.1,
                "max_leverage": 10,
                "state": "live",
            }
        },
    }


def test_live_signal_event_dispatches_contract_intent_to_active_subscriptions(tmp_path):
    database = _db(tmp_path)
    paper_id = database.save_strategy(
        "[合约] Signal Source",
        "class Demo: pass",
        config={
            "strategy_key": "demo",
            "is_paper_trading": True,
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "max_leverage": 3,
        },
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    FakeLiveContractBroker.calls = []
    service = LiveSignalExecutionService(
        database,
        contract_broker_factory=FakeLiveContractBroker,
    )
    subscription = service.upsert_subscription(
        source_strategy_id=paper_id,
        account_id="default",
        status="running",
        risk_config={"max_notional_usdt": 100},
    )

    event = asyncio.run(
        service.record_contract_signal_and_dispatch(
            source_strategy_id=paper_id,
            exchange="okx",
            symbols=["BTC/USDT:USDT"],
            source_config={
                "is_paper_trading": True,
                "market_type": "swap",
                "td_mode": "cross",
                "trade_symbols": ["BTC/USDT:USDT"],
                "max_leverage": 3,
            },
            action="open",
            symbol="BTC/USDT:USDT",
            side="long",
            price=50_000.0,
            notional_usdt=100.0,
            leverage=2.0,
            quantity=0.002,
            margin=50.0,
            payload={"contracts": 0.002},
        )
    )

    assert event["id"] > 0
    assert event["source_strategy_id"] == paper_id
    assert event["live_dispatch_status"] == "filled"
    assert len(FakeLiveContractBroker.calls) == 1
    call = FakeLiveContractBroker.calls[0]
    client_order_id = call["kwargs"]["config"]["live_client_order_id"]
    assert client_order_id.startswith("bpls")
    assert "e" in client_order_id
    assert "_" not in client_order_id
    assert len(client_order_id) <= 32
    assert call == {
        "kwargs": {
            "strategy_id": 0,
            "exchange_name": "okx",
            "symbols": ["BTC/USDT:USDT"],
            "config": {
                "is_paper_trading": False,
                "market_type": "swap",
                "td_mode": "isolated",
                "trade_symbols": ["BTC/USDT:USDT"],
                "max_leverage": 3,
                "live_account_id": "default",
                "exchange": "okx",
                "live_client_order_id": client_order_id,
            },
        },
        "method": "open_contract",
        "symbol": "BTC/USDT:USDT",
        "side": "long",
        "notional_usdt": 100.0,
        "leverage": 2.0,
        "price": 50_000.0,
    }
    executions = service.list_signal_executions(event["id"])
    assert executions[0]["subscription_id"] == subscription["id"]
    assert executions[0]["status"] == "filled"
    assert executions[0]["live_order_id"] == "live-order-1"
    assert executions[0]["request_payload"]["client_order_id"] == client_order_id
    assert executions[0]["request_payload"]["td_mode"] == "isolated"
    assert executions[0]["response_payload"]["client_order_id"] == client_order_id


def test_live_signal_failed_execution_is_exposed_as_order_detail_row(tmp_path):
    database = _db(tmp_path)
    paper_id = database.save_strategy(
        "[合约] Rejected Source",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["ANTHROPIC/USDT:USDT"],
    )
    service = LiveSignalExecutionService(database)
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
        leverage=3,
    )
    execution = service._insert_execution(
        event_id=event["id"],
        subscription=subscription,
        exchange="okx",
        status="failed",
        live_order_id=None,
        request_payload={
            "client_order_id": "bpls1e1reject",
            "action": "open",
            "symbol": "ANTHROPIC/USDT:USDT",
            "side": "long",
            "quantity": 0.01,
            "leverage": 3,
        },
        response_payload={
            "code": "1",
            "data": [{"sCode": "51000", "sMsg": "Parameter posSide error"}],
        },
        error="OKX rejected order: 51000 Parameter posSide error",
    )

    rows = service.list_failed_execution_orders(account_id="default", limit=10)

    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == f"live-execution-{execution['id']}"
    assert row["status"] == "failed"
    assert row["raw_status"] == "failed"
    assert row["client_order_id"] == "bpls1e1reject"
    assert row["symbol"] == "ANTHROPIC/USDT:USDT"
    assert row["instrument_type"] == "SWAP"
    assert row["side"] == "buy"
    assert row["position_effect"] == "open"
    assert row["position_direction"] == "long"
    assert row["filled"] == 0.0
    assert row["amount"] == 0.01
    assert row["bitpro_source"] == "strategy"
    assert row["bitpro_source_label"] == "[合约] Rejected Source"
    assert row["source_strategy_id"] == paper_id
    assert row["subscription_id"] == subscription["id"]
    assert row["signal_event_id"] == event["id"]
    assert row["live_execution_id"] == execution["id"]
    assert row["failure_log"]["error"] == "OKX rejected order: 51000 Parameter posSide error"
    assert row["failure_log"]["response_payload"]["data"][0]["sCode"] == "51000"


def test_live_signal_dispatch_places_okx_net_mode_open_and_close_orders(monkeypatch, tmp_path):
    database = _db(tmp_path)
    paper_id = database.save_strategy(
        "[合约] Signal Source",
        "class Demo: pass",
        config=_contract_config(),
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    native = FakeNativeOKX(pos_mode="net_mode")
    fake_exchange = FakeExchange(native)
    monkeypatch.setattr(strategy_engine_module.exchange_manager, "get_exchange", lambda name: fake_exchange)
    monkeypatch.setattr(strategy_engine_module.trading_service, "get_balance", _fake_balance)
    service = LiveSignalExecutionService(database)
    service.upsert_subscription(
        source_strategy_id=paper_id,
        account_id="default",
        status="running",
    )

    event = asyncio.run(
        service.record_contract_signal_and_dispatch(
            source_strategy_id=paper_id,
            exchange="okx",
            symbols=["BTC/USDT:USDT"],
            source_config=_contract_config(),
            action="open",
            symbol="BTC/USDT:USDT",
            side="long",
            price=50_000.0,
            notional_usdt=100.0,
            leverage=5.0,
            quantity=0.2,
        )
    )
    assert event["live_dispatch_status"] == "filled"
    assert native.orders[-1]["side"] == "buy"
    assert "posSide" not in native.orders[-1]["params"]
    assert "reduceOnly" not in native.orders[-1]["params"]

    fake_exchange.positions = [
        {
            "symbol": "BTC/USDT:USDT",
            "side": "long",
            "amount": 0.2,
            "entry_price": 50_000.0,
            "mark_price": 50_000.0,
            "leverage": 5,
        }
    ]
    event = asyncio.run(
        service.record_contract_signal_and_dispatch(
            source_strategy_id=paper_id,
            exchange="okx",
            symbols=["BTC/USDT:USDT"],
            source_config=_contract_config(),
            action="close",
            symbol="BTC/USDT:USDT",
            side="long",
            price=50_000.0,
            notional_usdt=100.0,
            leverage=5.0,
            quantity=0.2,
            payload={"ratio": 1.0},
        )
    )
    assert event["live_dispatch_status"] == "filled"
    assert native.orders[-1]["side"] == "sell"
    assert "posSide" not in native.orders[-1]["params"]
    assert native.orders[-1]["params"]["reduceOnly"] is True

    event = asyncio.run(
        service.record_contract_signal_and_dispatch(
            source_strategy_id=paper_id,
            exchange="okx",
            symbols=["BTC/USDT:USDT"],
            source_config=_contract_config(),
            action="open",
            symbol="BTC/USDT:USDT",
            side="short",
            price=50_000.0,
            notional_usdt=100.0,
            leverage=5.0,
            quantity=0.2,
        )
    )
    assert event["live_dispatch_status"] == "filled"
    assert native.orders[-1]["side"] == "sell"
    assert "posSide" not in native.orders[-1]["params"]
    assert "reduceOnly" not in native.orders[-1]["params"]

    fake_exchange.positions = [
        {
            "symbol": "BTC/USDT:USDT",
            "side": "short",
            "amount": 0.2,
            "entry_price": 50_000.0,
            "mark_price": 50_000.0,
            "leverage": 5,
        }
    ]
    event = asyncio.run(
        service.record_contract_signal_and_dispatch(
            source_strategy_id=paper_id,
            exchange="okx",
            symbols=["BTC/USDT:USDT"],
            source_config=_contract_config(),
            action="close",
            symbol="BTC/USDT:USDT",
            side="short",
            price=50_000.0,
            notional_usdt=100.0,
            leverage=5.0,
            quantity=0.2,
            payload={"ratio": 1.0},
        )
    )
    assert event["live_dispatch_status"] == "filled"
    assert native.orders[-1]["side"] == "buy"
    assert "posSide" not in native.orders[-1]["params"]
    assert native.orders[-1]["params"]["reduceOnly"] is True

    assert [order["side"] for order in native.orders] == ["buy", "sell", "sell", "buy"]
    executions = service.list_signal_executions(event["id"])
    assert executions[0]["status"] == "filled"
    assert executions[0]["request_payload"]["client_order_id"].startswith("bpls")


def test_paused_live_subscription_records_signal_without_dispatching(tmp_path):
    database = _db(tmp_path)
    paper_id = database.save_strategy(
        "[合约] Paused Source",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )
    FakeLiveContractBroker.calls = []
    service = LiveSignalExecutionService(
        database,
        contract_broker_factory=FakeLiveContractBroker,
    )
    service.upsert_subscription(
        source_strategy_id=paper_id,
        account_id="default",
        status="paused",
    )

    event = asyncio.run(
        service.record_contract_signal_and_dispatch(
            source_strategy_id=paper_id,
            exchange="okx",
            symbols=["BTC/USDT:USDT"],
            source_config={"is_paper_trading": True, "market_type": "swap"},
            action="open",
            symbol="BTC/USDT:USDT",
            side="long",
            price=50_000.0,
            notional_usdt=100.0,
            leverage=2.0,
        )
    )

    assert event["live_dispatch_status"] == "no_active_subscription"
    assert FakeLiveContractBroker.calls == []
    assert service.list_signal_executions(event["id"]) == []


def test_live_subscription_rejects_symbols_filtered_by_preflight(tmp_path):
    database = _db(tmp_path)
    paper_id = database.save_strategy(
        "[合约] Dynamic Source",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT", "PEPE/USDT:USDT"],
    )
    FakeLiveContractBroker.calls = []
    service = LiveSignalExecutionService(
        database,
        contract_broker_factory=FakeLiveContractBroker,
    )
    service.upsert_subscription(
        source_strategy_id=paper_id,
        account_id="default",
        status="running",
        risk_config={
            "allowed_live_symbols": ["BTC/USDT:USDT"],
            "excluded_live_symbols": ["PEPE/USDT:USDT"],
        },
    )

    event = asyncio.run(
        service.record_contract_signal_and_dispatch(
            source_strategy_id=paper_id,
            exchange="okx",
            symbols=["BTC/USDT:USDT", "PEPE/USDT:USDT"],
            source_config={"is_paper_trading": True, "market_type": "swap"},
            action="open",
            symbol="PEPE/USDT:USDT",
            side="long",
            price=0.00001,
            notional_usdt=20.0,
            leverage=1.0,
        )
    )

    executions = service.list_signal_executions(event["id"])

    assert event["live_dispatch_status"] == "rejected"
    assert FakeLiveContractBroker.calls == []
    assert len(executions) == 1
    assert executions[0]["status"] == "rejected"
    assert "不在实盘预检通过标的内" in executions[0]["error"]
    subscription = service.get_subscription(paper_id, "default")
    assert subscription["last_error"] is None


def test_live_signal_event_dispatches_close_intent_to_active_subscriptions(tmp_path):
    database = _db(tmp_path)
    paper_id = database.save_strategy(
        "[合约] Close Source",
        "class Demo: pass",
        config={"strategy_key": "demo", "is_paper_trading": True, "market_type": "swap"},
        exchange="okx",
        symbols=["DOGE/USDT:USDT"],
    )
    FakeLiveContractBroker.calls = []
    service = LiveSignalExecutionService(
        database,
        contract_broker_factory=FakeLiveContractBroker,
    )
    service.upsert_subscription(
        source_strategy_id=paper_id,
        account_id="default",
        status="running",
    )

    event = asyncio.run(
        service.record_contract_signal_and_dispatch(
            source_strategy_id=paper_id,
            exchange="okx",
            symbols=["DOGE/USDT:USDT"],
            source_config={"is_paper_trading": True, "market_type": "swap"},
            action="close",
            symbol="DOGE/USDT:USDT",
            side="short",
            price=0.1,
            notional_usdt=0.1,
            leverage=1.0,
            quantity=1.0,
            payload={"ratio": 1.0},
        )
    )

    assert event["live_dispatch_status"] == "filled"
    assert len(FakeLiveContractBroker.calls) == 1
    call = FakeLiveContractBroker.calls[0]
    client_order_id = call["kwargs"]["config"]["live_client_order_id"]
    assert client_order_id.startswith("bpls")
    assert "_" not in client_order_id
    assert call == {
        "kwargs": {
            "strategy_id": 0,
            "exchange_name": "okx",
            "symbols": ["DOGE/USDT:USDT"],
            "config": {
                "is_paper_trading": False,
                "market_type": "swap",
                "td_mode": "isolated",
                "live_account_id": "default",
                "exchange": "okx",
                "live_client_order_id": client_order_id,
            },
        },
        "method": "close_contract",
        "symbol": "DOGE/USDT:USDT",
        "side": "short",
        "ratio": 1.0,
        "contracts": 1.0,
        "price": 0.1,
    }
    executions = service.list_signal_executions(event["id"])
    assert executions[0]["status"] == "filled"
    assert executions[0]["live_order_id"] == "live-close-1"
    assert executions[0]["request_payload"]["client_order_id"] == client_order_id
    assert executions[0]["request_payload"]["td_mode"] == "isolated"
