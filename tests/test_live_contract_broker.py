import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.services.strategy_engine as strategy_engine_module
from app.services.strategy_engine import LiveContractBroker


def _instrument_config():
    return {
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
        }
    }


class FakeNativeOKX:
    def __init__(self, *, pos_mode="long_short_mode"):
        self.pos_mode = pos_mode
        self.account_config_calls = 0
        self.leverage_payloads = []
        self.orders = []

    def privateGetAccountConfig(self, params=None):
        self.account_config_calls += 1
        return {"code": "0", "data": [{"posMode": self.pos_mode}]}

    def privatePostAccountSetLeverage(self, payload):
        self.leverage_payloads.append(dict(payload))
        return {"code": "0", "data": [{"sCode": "0"}]}

    def create_order(self, symbol, order_type, side, amount, price=None, params=None):
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
            "id": "ord-live-1",
            "status": "closed",
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": price,
            "info": {"data": [{"ordId": "ord-live-1", "sCode": "0"}]},
        }


class FakeExchange:
    def __init__(self, native, positions=None):
        self.exchange = native
        self.positions = positions or []

    def fetch_positions(self, symbols=None):
        return self.positions

    def fetch_ticker(self, symbol):
        return {"last": 50_000.0}


async def _fake_balance(exchange_name):
    return [{"currency": "USDT", "free": 1_000.0, "total": 1_000.0, "used": 0.0}]


def test_live_contract_broker_open_long_uses_okx_swap_order_params(monkeypatch):
    native = FakeNativeOKX(pos_mode="long_short_mode")
    fake_exchange = FakeExchange(native)
    monkeypatch.setattr(strategy_engine_module.exchange_manager, "get_exchange", lambda name: fake_exchange)
    monkeypatch.setattr(strategy_engine_module.trading_service, "get_balance", _fake_balance)

    broker = LiveContractBroker(
        strategy_id=0,
        exchange_name="okx:default",
        symbols=["BTC/USDT:USDT"],
        config={**_instrument_config(), "market_type": "swap", "is_paper_trading": False, "max_leverage": 10},
    )

    result = asyncio.run(broker.open_contract("BTC/USDT:USDT", "long", 100.0, leverage=5, price=50_000.0))

    assert result["status"] == "filled"
    assert result["contracts"] == 0.2
    assert result["order_side"] == "buy"
    assert native.leverage_payloads == [
        {"instId": "BTC-USDT-SWAP", "lever": "5", "mgnMode": "isolated", "posSide": "long"}
    ]
    order = native.orders[0]
    assert order["symbol"] == "BTC/USDT:USDT"
    assert order["type"] == "market"
    assert order["side"] == "buy"
    assert order["amount"] == 0.2
    assert order["params"]["tdMode"] == "isolated"
    assert order["params"]["posSide"] == "long"
    assert order["params"]["clOrdId"].startswith("bp0")
    assert "reduceOnly" not in order["params"]


def test_live_contract_broker_open_long_net_mode_omits_pos_side(monkeypatch):
    native = FakeNativeOKX(pos_mode="net_mode")
    fake_exchange = FakeExchange(native)
    monkeypatch.setattr(strategy_engine_module.exchange_manager, "get_exchange", lambda name: fake_exchange)
    monkeypatch.setattr(strategy_engine_module.trading_service, "get_balance", _fake_balance)

    broker = LiveContractBroker(
        strategy_id=0,
        exchange_name="okx:default",
        symbols=["BTC/USDT:USDT"],
        config={**_instrument_config(), "market_type": "swap", "is_paper_trading": False, "position_mode": "net_mode"},
    )

    result = asyncio.run(broker.open_contract("BTC/USDT:USDT", "long", 100.0, leverage=5, price=50_000.0))

    assert result["status"] == "filled"
    order = native.orders[0]
    assert order["side"] == "buy"
    assert order["params"]["tdMode"] == "isolated"
    assert "posSide" not in order["params"]
    assert "reduceOnly" not in order["params"]


def test_live_contract_broker_uses_okx_account_mode_over_paper_position_mode(monkeypatch):
    native = FakeNativeOKX(pos_mode="net_mode")
    fake_exchange = FakeExchange(native)
    monkeypatch.setattr(strategy_engine_module.exchange_manager, "get_exchange", lambda name: fake_exchange)
    monkeypatch.setattr(strategy_engine_module.trading_service, "get_balance", _fake_balance)

    broker = LiveContractBroker(
        strategy_id=0,
        exchange_name="okx:default",
        symbols=["BTC/USDT:USDT"],
        config={
            **_instrument_config(),
            "market_type": "swap",
            "is_paper_trading": False,
            "position_mode": "long_short_mode",
        },
    )

    result = asyncio.run(broker.open_contract("BTC/USDT:USDT", "long", 100.0, leverage=5, price=50_000.0))

    assert result["status"] == "filled"
    assert native.account_config_calls == 1
    order = native.orders[0]
    assert order["side"] == "buy"
    assert order["params"]["tdMode"] == "isolated"
    assert "posSide" not in order["params"]
    assert "reduceOnly" not in order["params"]


def test_live_contract_broker_close_short_net_mode_omits_pos_side_and_uses_reduce_only(monkeypatch):
    native = FakeNativeOKX(pos_mode="net_mode")
    fake_exchange = FakeExchange(
        native,
        positions=[
            {
                "symbol": "BTC/USDT:USDT",
                "side": "short",
                "amount": 0.4,
                "entry_price": 51_000.0,
                "mark_price": 50_000.0,
                "leverage": 5,
            }
        ],
    )
    monkeypatch.setattr(strategy_engine_module.exchange_manager, "get_exchange", lambda name: fake_exchange)
    monkeypatch.setattr(strategy_engine_module.trading_service, "get_balance", _fake_balance)

    broker = LiveContractBroker(
        strategy_id=0,
        exchange_name="okx:default",
        symbols=["BTC/USDT:USDT"],
        config={**_instrument_config(), "market_type": "swap", "is_paper_trading": False, "position_mode": "net_mode"},
    )

    result = asyncio.run(broker.close_contract("BTC/USDT:USDT", "short", ratio=0.5, price=50_000.0))

    assert result["status"] == "filled"
    assert result["contracts"] == 0.2
    assert result["order_side"] == "buy"
    assert native.leverage_payloads == []
    order = native.orders[0]
    assert order["side"] == "buy"
    assert order["amount"] == 0.2
    assert "posSide" not in order["params"]
    assert order["params"]["reduceOnly"] is True


def test_live_contract_broker_close_short_prefers_side_when_pos_side_is_net(monkeypatch):
    native = FakeNativeOKX(pos_mode="net_mode")
    fake_exchange = FakeExchange(
        native,
        positions=[
            {
                "symbol": "BTC/USDT:USDT",
                "pos_side": "net",
                "side": "short",
                "contracts": 0.4,
                "entry_price": 51_000.0,
                "mark_price": 50_000.0,
                "leverage": 5,
            }
        ],
    )
    monkeypatch.setattr(strategy_engine_module.exchange_manager, "get_exchange", lambda name: fake_exchange)
    monkeypatch.setattr(strategy_engine_module.trading_service, "get_balance", _fake_balance)

    broker = LiveContractBroker(
        strategy_id=0,
        exchange_name="okx:default",
        symbols=["BTC/USDT:USDT"],
        config={**_instrument_config(), "market_type": "swap", "is_paper_trading": False, "position_mode": "net_mode"},
    )

    result = asyncio.run(broker.close_contract("BTC/USDT:USDT", "short", ratio=1.0, price=50_000.0))

    assert result["status"] == "filled"
    order = native.orders[0]
    assert order["side"] == "buy"
    assert order["amount"] == 0.4
    assert "posSide" not in order["params"]
    assert order["params"]["reduceOnly"] is True


def test_live_contract_broker_close_uses_position_margin_mode_over_config(monkeypatch):
    native = FakeNativeOKX(pos_mode="net_mode")
    fake_exchange = FakeExchange(
        native,
        positions=[
            {
                "symbol": "BTC/USDT:USDT",
                "side": "short",
                "amount": 0.4,
                "entry_price": 51_000.0,
                "mark_price": 50_000.0,
                "leverage": 5,
                "margin_mode": "isolated",
            }
        ],
    )
    monkeypatch.setattr(strategy_engine_module.exchange_manager, "get_exchange", lambda name: fake_exchange)
    monkeypatch.setattr(strategy_engine_module.trading_service, "get_balance", _fake_balance)

    broker = LiveContractBroker(
        strategy_id=0,
        exchange_name="okx:default",
        symbols=["BTC/USDT:USDT"],
        config={
            **_instrument_config(),
            "market_type": "swap",
            "is_paper_trading": False,
            "position_mode": "net_mode",
            "td_mode": "cross",
        },
    )

    result = asyncio.run(broker.close_contract("BTC/USDT:USDT", "short", ratio=0.5, price=50_000.0))

    assert result["status"] == "filled"
    order = native.orders[0]
    assert order["params"]["tdMode"] == "isolated"
    assert order["params"]["reduceOnly"] is True


def test_live_contract_broker_warmup_never_places_order(monkeypatch):
    native = FakeNativeOKX(pos_mode="long_short_mode")
    fake_exchange = FakeExchange(native)
    monkeypatch.setattr(strategy_engine_module.exchange_manager, "get_exchange", lambda name: fake_exchange)
    monkeypatch.setattr(strategy_engine_module.trading_service, "get_balance", _fake_balance)

    broker = LiveContractBroker(
        strategy_id=0,
        exchange_name="okx:default",
        symbols=["BTC/USDT:USDT"],
        config={**_instrument_config(), "market_type": "swap", "is_paper_trading": False},
    )
    broker.warmup_mode = True

    result = asyncio.run(broker.open_contract("BTC/USDT:USDT", "long", 100.0, leverage=5, price=50_000.0))

    assert result == {"status": "skipped", "reason": "warmup_mode"}
    assert native.orders == []
