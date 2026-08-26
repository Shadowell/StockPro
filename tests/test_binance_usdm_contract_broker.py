import asyncio
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.services.binance_usdm_contract_broker as broker_module
from app.api.v2.endpoints import live
from app.services.binance_usdm_contract_broker import BinanceUsdmContractBroker


class FakeNativeBinance:
    def __init__(self, *, hedge_mode=True, order_error=None):
        self.hedge_mode = hedge_mode
        self.order_error = order_error
        self.margin_calls = []
        self.leverage_calls = []
        self.orders = []

    def fapiPrivateGetPositionSideDual(self, params=None):
        return {"dualSidePosition": self.hedge_mode}

    def set_margin_mode(self, mode, symbol, params=None):
        self.margin_calls.append((mode, symbol, dict(params or {})))
        return {"code": 200}

    def set_leverage(self, leverage, symbol, params=None):
        self.leverage_calls.append((leverage, symbol, dict(params or {})))
        return {"leverage": leverage}

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
        if self.order_error:
            raise self.order_error
        return {
            "id": "binance-order-1",
            "status": "closed",
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": price,
        }


class FakeExchange:
    def __init__(self, native, positions=None):
        self.exchange = native
        self.positions = positions or []
        self.markets = {
            "BTC/USDT:USDT": {
                "id": "BTCUSDT",
                "symbol": "BTC/USDT:USDT",
                "swap": True,
                "linear": True,
                "active": True,
                "contractSize": 1.0,
                "limits": {"amount": {"min": 0.001}},
                "precision": {"amount": 0.001},
            },
            "1000SHIB/USDT:USDT": {
                "id": "1000SHIBUSDT",
                "symbol": "1000SHIB/USDT:USDT",
                "swap": True,
                "linear": True,
                "active": True,
                "contractSize": 1.0,
                "limits": {"amount": {"min": 1.0}},
                "precision": {"amount": 1.0},
            },
        }

    def load_markets(self):
        return self.markets

    def fetch_positions(self, symbols=None):
        return self.positions

    def fetch_ticker(self, symbol):
        return {"last": 50_000.0}

    def fetch_balance(self):
        return [{"currency": "USDT", "free": 1_000.0, "total": 1_000.0, "used": 0.0}]


def test_binance_usdm_open_hedge_position_uses_position_side_without_reduce_only(monkeypatch):
    native = FakeNativeBinance(hedge_mode=True)
    fake_exchange = FakeExchange(native)
    monkeypatch.setattr(broker_module.exchange_manager, "get_exchange", lambda name: fake_exchange)

    broker = BinanceUsdmContractBroker(
        strategy_id=0,
        exchange_name="binanceusdm:binance",
        symbols=["BTC/USDT:USDT"],
        config={"max_leverage": 10, "live_client_order_id": "bpls1e2abc123"},
    )

    result = asyncio.run(broker.open_contract("BTC/USDT:USDT", "long", 100.0, leverage=5, price=50_000.0))

    assert result["status"] == "filled"
    assert result["contracts"] == 0.002
    assert native.margin_calls == [("isolated", "BTC/USDT:USDT", {})]
    assert native.leverage_calls == [(5, "BTC/USDT:USDT", {})]
    order = native.orders[0]
    assert order["side"] == "buy"
    assert order["params"]["positionSide"] == "LONG"
    assert order["params"]["newClientOrderId"] == "bpls1e2abc123"
    assert "reduceOnly" not in order["params"]


def test_binance_usdm_close_one_way_position_uses_reduce_only(monkeypatch):
    native = FakeNativeBinance(hedge_mode=False)
    fake_exchange = FakeExchange(
        native,
        positions=[
            {
                "symbol": "BTC/USDT:USDT",
                "side": "short",
                "contracts": 0.004,
                "entry_price": 51_000.0,
                "mark_price": 50_000.0,
                "leverage": 5,
            }
        ],
    )
    monkeypatch.setattr(broker_module.exchange_manager, "get_exchange", lambda name: fake_exchange)

    broker = BinanceUsdmContractBroker(
        strategy_id=0,
        exchange_name="binanceusdm:binance",
        symbols=["BTC/USDT:USDT"],
        config={"max_leverage": 10},
    )

    result = asyncio.run(broker.close_contract("BTC/USDT:USDT", "short", ratio=0.5, price=50_000.0))

    assert result["status"] == "filled"
    assert result["contracts"] == 0.002
    order = native.orders[0]
    assert order["side"] == "buy"
    assert order["params"]["reduceOnly"] is True
    assert "positionSide" not in order["params"]


def test_binance_usdm_unknown_order_outcome_is_recorded_without_retry(monkeypatch):
    native = FakeNativeBinance(order_error=TimeoutError("request timeout after submission"))
    fake_exchange = FakeExchange(native)
    monkeypatch.setattr(broker_module.exchange_manager, "get_exchange", lambda name: fake_exchange)

    broker = BinanceUsdmContractBroker(
        strategy_id=0,
        exchange_name="binanceusdm:binance",
        symbols=["BTC/USDT:USDT"],
        config={"max_leverage": 10, "live_client_order_id": "bpls1e2timeout"},
    )

    result = asyncio.run(broker.open_contract("BTC/USDT:USDT", "long", 100.0, leverage=5, price=50_000.0))

    assert result["status"] == "unknown"
    assert result["client_order_id"] == "bpls1e2timeout"
    assert len(native.orders) == 1


def test_binance_usdm_maps_shib_source_signal_to_1000shib_contract(monkeypatch):
    native = FakeNativeBinance(hedge_mode=True)
    fake_exchange = FakeExchange(native)
    monkeypatch.setattr(broker_module.exchange_manager, "get_exchange", lambda name: fake_exchange)

    broker = BinanceUsdmContractBroker(
        strategy_id=0,
        exchange_name="binanceusdm:binance",
        symbols=["SHIB/USDT:USDT"],
        config={"max_leverage": 10},
    )

    result = asyncio.run(
        broker.open_contract("SHIB/USDT:USDT", "long", 54.0, leverage=5, price=0.0000054)
    )

    assert result["status"] == "filled"
    assert result["symbol"] == "1000SHIB/USDT:USDT"
    assert result["price"] == 0.0054
    assert result["contracts"] == 10_000
    assert native.orders[-1]["symbol"] == "1000SHIB/USDT:USDT"
    assert native.orders[-1]["amount"] == 10_000


def test_binance_usdm_mapped_close_uses_live_venue_position_size(monkeypatch):
    native = FakeNativeBinance(hedge_mode=False)
    fake_exchange = FakeExchange(
        native,
        positions=[
            {
                "symbol": "1000SHIB/USDT:USDT",
                "side": "long",
                "contracts": 10_000,
                "entry_price": 0.0054,
                "mark_price": 0.0055,
                "leverage": 5,
            }
        ],
    )
    monkeypatch.setattr(broker_module.exchange_manager, "get_exchange", lambda name: fake_exchange)

    broker = BinanceUsdmContractBroker(
        strategy_id=0,
        exchange_name="binanceusdm:binance",
        symbols=["SHIB/USDT:USDT"],
        config={"max_leverage": 10},
    )

    result = asyncio.run(
        broker.close_contract(
            "SHIB/USDT:USDT",
            "long",
            ratio=1.0,
            contracts=50_000_000,
            price=0.0000055,
        )
    )

    assert result["status"] == "filled"
    assert result["symbol"] == "1000SHIB/USDT:USDT"
    assert result["contracts"] == 10_000
    assert result["price"] == 0.0055
    assert native.orders[-1]["amount"] == 10_000


def test_binance_usdm_contract_precheck_resolves_shib_to_1000shib(monkeypatch):
    calls = []

    class FakeNativePrecheck:
        markets = {
            "1000SHIB/USDT:USDT": {
                "id": "1000SHIBUSDT",
                "swap": True,
                "linear": True,
                "active": True,
                "contractSize": 1.0,
                "limits": {"amount": {"min": 1}, "cost": {"min": 5}},
                "precision": {"amount": 1.0},
            }
        }

        def fapiPrivateGetPositionSideDual(self, payload):
            return {"dualSidePosition": False}

        def fapiPrivatePostOrderTest(self, payload):
            calls.append(dict(payload))
            return {}

    class FakePrecheckExchange:
        name = "binanceusdm"

        def __init__(self):
            self.exchange = FakeNativePrecheck()

        def load_markets(self):
            return None

        def fetch_ticker(self, symbol):
            assert symbol == "1000SHIB/USDT:USDT"
            return {"last": 0.0054}

    monkeypatch.setattr(live.exchange_manager, "get_exchange", lambda name: FakePrecheckExchange())

    result = asyncio.run(
        live._live_contract_account_precheck(
            exchange="binanceusdm:binance_demo",
            live_cfg={"market_type": "swap", "contract_trade_symbols": ["SHIB/USDT:USDT"]},
            symbols=["SHIB/USDT:USDT"],
        )
    )

    assert result["passed"] is True
    assert "1000SHIBUSDT" in result["detail"]
    assert calls == [
        {
            "symbol": "1000SHIBUSDT",
            "side": "BUY",
            "type": "MARKET",
            "quantity": "973.0",
        }
    ]


def test_live_order_book_depth_applies_contract_size():
    class FakeNativeOrderBook:
        markets = {
            "SHIB/USDT:USDT": {
                "contractSize": 1_000_000,
            }
        }

    class FakeOrderBookExchange:
        name = "okx"
        exchange = FakeNativeOrderBook()

        def load_markets(self):
            return None

        def fetch_order_book(self, symbol, limit=5):
            assert symbol == "SHIB/USDT:USDT"
            return {
                "bids": [[0.0000054, 10] for _ in range(5)],
                "asks": [[0.000005401, 10] for _ in range(5)],
            }

    result = asyncio.run(
        live._order_book_liquidity_check(FakeOrderBookExchange(), ["SHIB/USDT:USDT"])
    )

    assert result["passed"] is True


def test_binance_runtime_preflight_queries_open_orders_with_venue_symbol(monkeypatch):
    queried_symbols = []

    class FakeNativeRuntime:
        id = "binanceusdm"
        markets = {
            "1000SHIB/USDT:USDT": {
                "id": "1000SHIBUSDT",
                "swap": True,
                "linear": True,
                "active": True,
                "contractSize": 1.0,
                "limits": {"amount": {"min": 1}, "cost": {"min": 5}},
                "precision": {"amount": 1.0},
            }
        }

    class FakeRuntimeExchange:
        name = "binanceusdm"
        exchange = FakeNativeRuntime()

        def load_markets(self):
            return None

        def fetch_ohlcv(self, symbol, timeframe, limit=3):
            assert symbol == "1000SHIB/USDT:USDT"
            return [[int(time.time() * 1000), 0.0054, 0.0055, 0.0053, 0.0054, 1000]]

        def fetch_order_book(self, symbol, limit=5):
            assert symbol == "1000SHIB/USDT:USDT"
            return {
                "bids": [[0.0054, 10_000] for _ in range(5)],
                "asks": [[0.005401, 10_000] for _ in range(5)],
            }

    class FakeTradingService:
        async def get_balance(self, exchange):
            return [{"currency": "USDT", "free": 100.0, "total": 100.0}]

        async def get_open_orders(self, exchange, symbol=None):
            queried_symbols.append(symbol)
            return []

    monkeypatch.setattr(live.exchange_manager, "get_exchange", lambda name: FakeRuntimeExchange())
    monkeypatch.setattr(live, "trading_service", FakeTradingService())
    monkeypatch.setattr(live.strategy_engine, "get_risk_status", lambda: {"circuit_breaker": False})

    result = asyncio.run(
        live._run_preflight_checks(
            strategy_id=401,
            row={
                "id": 401,
                "symbols": ["SHIB/USDT:USDT"],
                "config": {
                    "market_type": "swap",
                    "timeframe": "1h",
                    "trade_symbols": ["SHIB/USDT:USDT"],
                    "min_order_notional_usdt": 10,
                },
            },
            exchange="binanceusdm:binance",
            timeframe="1h",
            dry_run=False,
        )
    )

    assert queried_symbols == ["1000SHIB/USDT:USDT"]
    open_order_check = next(
        check for check in result["checks"] if check["item"] == "实盘未成交挂单冲突"
    )
    assert open_order_check["passed"] is True
