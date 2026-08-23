import asyncio
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import live


def _allow_trade_permission(monkeypatch, calls=None):
    def fake_permission(account_id):
        if calls is not None:
            calls.append(account_id)
        return {
            "can_read": True,
            "can_trade": True,
            "checked_at": "2026-05-09T00:00:00+00:00",
            "detail": "读取权限和交易权限测试通过",
        }

    monkeypatch.setattr(live.live_account_service, "validate_account_trade_permission", fake_permission)


def test_promote_preflight_uses_detected_live_usdt_balance(monkeypatch):
    permission_calls = []
    _allow_trade_permission(monkeypatch, permission_calls)

    class FakeExchange:
        def fetch_ohlcv(self, symbol, timeframe, limit=3):
            assert symbol == "BTC/USDT"
            now_ms = int(time.time() * 1000)
            return [[now_ms, 1, 1, 1, 1, 100]]

        def fetch_order_book(self, symbol, limit=5):
            assert symbol == "BTC/USDT"
            return {
                "bids": [[99.9, 1.0], [99.8, 1.0]],
                "asks": [[100.1, 1.0], [100.2, 1.0]],
            }

    class FakeStrategy:
        pass

    async def fake_balance(exchange):
        assert exchange == "okx"
        return [{"currency": "USDT", "free": 600.0, "used": 10.0, "total": 610.0}]

    async def fake_open_orders(exchange, symbol=None):
        assert exchange == "okx"
        assert symbol == "BTC/USDT"
        return []

    monkeypatch.setattr(live.exchange_manager, "get_exchange", lambda exchange: FakeExchange())
    monkeypatch.setattr(live.trading_service, "get_balance", fake_balance)
    monkeypatch.setattr(live.trading_service, "get_open_orders", fake_open_orders)
    monkeypatch.setattr(live.strategy_engine, "get_risk_status", lambda: {"circuit_breaker": False})
    monkeypatch.setattr(live.db, "get_strategies", lambda: [])
    monkeypatch.setattr(
        live,
        "resolve_unified_base_strategy_class",
        lambda row: (FakeStrategy, row.get("config") or {}),
    )
    monkeypatch.setattr(
        live.db,
        "get_strategy_by_id",
        lambda strategy_id: {
            "id": 9,
            "name": "Paper strategy",
            "symbols": ["BTC/USDT"],
            "config": {
                "is_paper_trading": True,
                "timeframe": "1m",
                "entry_quote_usdt": 200.0,
            },
            "script_content": "",
        },
    )

    res = asyncio.run(
        live._run_promote_preflight(
            live.PromoteToLiveBody(
                source_strategy_id=9,
                exchange="okx",
                loop_interval=60,
            )
        )
    )

    assert res["all_passed"] is True
    assert res["account"]["free_usdt"] == 600.0
    assert res["plan"]["initial_equity"] == 600.0
    assert res["plan"]["initial_equity_source"] == "live_account_free_usdt"
    assert res["plan"]["account"]["total_usdt"] == 610.0

    account_check = next(c for c in res["checks"] if c["item"] == "实盘账户权限与 USDT 余额")
    assert account_check["passed"] is True
    assert account_check["account"]["free_usdt"] == 600.0
    trade_check = next(c for c in res["checks"] if c["item"] == "账户交易权限")
    assert trade_check["passed"] is True
    assert permission_calls == ["default"]
    sizing_check = next(c for c in res["checks"] if c["item"] == "订单名义金额可执行")
    assert sizing_check["passed"] is True


def test_promote_preflight_blocks_too_small_live_order_notional(monkeypatch):
    _allow_trade_permission(monkeypatch)

    class FakeExchange:
        def fetch_ohlcv(self, symbol, timeframe, limit=3):
            now_ms = int(time.time() * 1000)
            return [[now_ms, 1, 1, 1, 1, 100]]

        def fetch_order_book(self, symbol, limit=5):
            return {
                "bids": [[99.9, 1.0], [99.8, 1.0]],
                "asks": [[100.1, 1.0], [100.2, 1.0]],
            }

    class FakeStrategy:
        pass

    async def fake_balance(exchange):
        return [{"currency": "USDT", "free": 321.5, "used": 0.0, "total": 321.5}]

    async def fake_open_orders(exchange, symbol=None):
        return []

    monkeypatch.setattr(live.exchange_manager, "get_exchange", lambda exchange: FakeExchange())
    monkeypatch.setattr(live.trading_service, "get_balance", fake_balance)
    monkeypatch.setattr(live.trading_service, "get_open_orders", fake_open_orders)
    monkeypatch.setattr(live.strategy_engine, "get_risk_status", lambda: {"circuit_breaker": False})
    monkeypatch.setattr(live.db, "get_strategies", lambda: [])
    monkeypatch.setattr(
        live,
        "resolve_unified_base_strategy_class",
        lambda row: (FakeStrategy, row.get("config") or {}),
    )
    monkeypatch.setattr(
        live.db,
        "get_strategy_by_id",
        lambda strategy_id: {
            "id": 9,
            "name": "Paper strategy",
            "symbols": ["BTC/USDT"],
            "config": {
                "is_paper_trading": True,
                "timeframe": "1m",
                "entry_quote_usdt": 5.0,
            },
            "script_content": "",
        },
    )

    res = asyncio.run(
        live._run_promote_preflight(
            live.PromoteToLiveBody(
                source_strategy_id=9,
                exchange="okx",
                loop_interval=60,
            )
        )
    )

    assert res["all_passed"] is False
    assert res["plan"]["initial_equity"] == 321.5
    sizing_check = next(c for c in res["checks"] if c["item"] == "订单名义金额可执行")
    assert sizing_check["passed"] is False
    assert "低于最小可执行名义" in sizing_check["detail"]


def test_promote_preflight_blocks_when_trade_permission_probe_fails(monkeypatch):
    class FakeStrategy:
        pass

    def fail_permission(account_id):
        raise live.BadRequestError("账户 API 交易权限测试失败：当前 API Key 缺少 Trade 权限")

    def fail_exchange_lookup(exchange):
        raise AssertionError("runtime checks should not run after trade permission failure")

    monkeypatch.setattr(live.live_account_service, "validate_account_trade_permission", fail_permission)
    monkeypatch.setattr(live.exchange_manager, "get_exchange", fail_exchange_lookup)
    monkeypatch.setattr(live.db, "get_strategies", lambda: [])
    monkeypatch.setattr(
        live,
        "resolve_unified_base_strategy_class",
        lambda row: (FakeStrategy, row.get("config") or {}),
    )
    monkeypatch.setattr(
        live.db,
        "get_strategy_by_id",
        lambda strategy_id: {
            "id": 9,
            "name": "Paper strategy",
            "symbols": ["BTC/USDT"],
            "config": {
                "is_paper_trading": True,
                "timeframe": "1m",
                "entry_quote_usdt": 200.0,
            },
            "script_content": "",
        },
    )

    res = asyncio.run(
        live._run_promote_preflight(
            live.PromoteToLiveBody(
                source_strategy_id=9,
                exchange="okx",
                loop_interval=60,
            )
        )
    )

    assert res["all_passed"] is False
    trade_check = next(c for c in res["checks"] if c["item"] == "账户交易权限")
    assert trade_check["passed"] is False
    assert "缺少 Trade 权限" in trade_check["detail"]
    assert not any(c["item"] == "实盘账户权限与 USDT 余额" for c in res["checks"])


def test_promote_preflight_checks_live_contract_account_precheck(monkeypatch):
    _allow_trade_permission(monkeypatch)
    precheck_payloads = []

    class FakeNativeOKX:
        markets = {
            "BTC/USDT:USDT": {
                "active": True,
                "limits": {"cost": {"min": 10.0}},
            }
        }

        def privateGetAccountConfig(self, params=None):
            return {"code": "0", "data": [{"posMode": "long_short_mode"}]}

        def privatePostTradeOrderPrecheck(self, payload):
            precheck_payloads.append(dict(payload))
            return {"code": "0", "data": [{"sCode": "0"}]}

    class FakeExchange:
        def __init__(self):
            self.exchange = FakeNativeOKX()

        def load_markets(self):
            return None

        def fetch_ohlcv(self, symbol, timeframe, limit=3):
            now_ms = int(time.time() * 1000)
            return [[now_ms, 1, 1, 1, 50_000, 100]]

        def fetch_order_book(self, symbol, limit=5):
            return {
                "bids": [[49_990, 1.0], [49_980, 1.0]],
                "asks": [[50_010, 1.0], [50_020, 1.0]],
            }

    class FakeStrategy:
        pass

    async def fake_balance(exchange):
        return [{"currency": "USDT", "free": 600.0, "used": 0.0, "total": 600.0}]

    async def fake_open_orders(exchange, symbol=None):
        return []

    monkeypatch.setattr(live.exchange_manager, "get_exchange", lambda exchange: FakeExchange())
    monkeypatch.setattr(live.trading_service, "get_balance", fake_balance)
    monkeypatch.setattr(live.trading_service, "get_open_orders", fake_open_orders)
    monkeypatch.setattr(live.strategy_engine, "get_risk_status", lambda: {"circuit_breaker": False})
    monkeypatch.setattr(live.db, "get_strategies", lambda: [])
    monkeypatch.setattr(
        live,
        "resolve_unified_base_strategy_class",
        lambda row: (FakeStrategy, row.get("config") or {}),
    )
    monkeypatch.setattr(
        live.db,
        "get_strategy_by_id",
        lambda strategy_id: {
            "id": 9,
            "name": "[合约] Paper strategy",
            "symbols": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
            "config": {
                "is_paper_trading": True,
                "market_type": "swap",
                "timeframe": "1h",
                "entry_quote_usdt": 20.0,
                "stop_loss_bps": 50.0,
                "take_profit_bps": 100.0,
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
            },
            "script_content": "",
        },
    )

    res = asyncio.run(
        live._run_promote_preflight(
            live.PromoteToLiveBody(
                source_strategy_id=9,
                exchange="okx",
                loop_interval=60,
            )
        )
    )

    support_check = next(c for c in res["checks"] if c["item"] == "实盘合约执行支持")
    assert support_check["passed"] is True
    assert "LiveContractBroker" in support_check["detail"]
    contract_check = next(c for c in res["checks"] if c["item"] == "账户合约交易能力")
    assert contract_check["passed"] is True
    assert "order-precheck 通过" in contract_check["detail"]
    assert precheck_payloads == [
        {
            "instId": "BTC-USDT-SWAP",
            "tdMode": "isolated",
            "side": "buy",
            "ordType": "market",
            "sz": "0.01",
            "posSide": "long",
        }
    ]


def test_promote_preflight_omits_pos_side_for_okx_net_mode_order_precheck(monkeypatch):
    _allow_trade_permission(monkeypatch)
    precheck_payloads = []

    class FakeNativeOKX:
        markets = {
            "BTC/USDT:USDT": {
                "active": True,
                "limits": {"cost": {"min": 10.0}},
            }
        }

        def privateGetAccountConfig(self, params=None):
            return {"code": "0", "data": [{"posMode": "net_mode"}]}

        def privatePostTradeOrderPrecheck(self, payload):
            precheck_payloads.append(dict(payload))
            return {"code": "0", "data": [{"sCode": "0"}]}

    class FakeExchange:
        def __init__(self):
            self.exchange = FakeNativeOKX()

        def load_markets(self):
            return None

        def fetch_ohlcv(self, symbol, timeframe, limit=3):
            now_ms = int(time.time() * 1000)
            return [[now_ms, 1, 1, 1, 50_000, 100]]

        def fetch_order_book(self, symbol, limit=5):
            return {
                "bids": [[49_990, 1.0], [49_980, 1.0]],
                "asks": [[50_010, 1.0], [50_020, 1.0]],
            }

    class FakeStrategy:
        pass

    async def fake_balance(exchange):
        return [{"currency": "USDT", "free": 600.0, "used": 0.0, "total": 600.0}]

    async def fake_open_orders(exchange, symbol=None):
        return []

    monkeypatch.setattr(live.exchange_manager, "get_exchange", lambda exchange: FakeExchange())
    monkeypatch.setattr(live.trading_service, "get_balance", fake_balance)
    monkeypatch.setattr(live.trading_service, "get_open_orders", fake_open_orders)
    monkeypatch.setattr(live.strategy_engine, "get_risk_status", lambda: {"circuit_breaker": False})
    monkeypatch.setattr(live.db, "get_strategies", lambda: [])
    monkeypatch.setattr(
        live,
        "resolve_unified_base_strategy_class",
        lambda row: (FakeStrategy, row.get("config") or {}),
    )
    monkeypatch.setattr(
        live.db,
        "get_strategy_by_id",
        lambda strategy_id: {
            "id": 9,
            "name": "[合约] Paper strategy",
            "symbols": ["BTC/USDT:USDT"],
            "config": {
                "is_paper_trading": True,
                "market_type": "swap",
                "timeframe": "1h",
                "entry_quote_usdt": 20.0,
                "stop_loss_bps": 50.0,
                "take_profit_bps": 100.0,
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
            },
            "script_content": "",
        },
    )

    res = asyncio.run(
        live._run_promote_preflight(
            live.PromoteToLiveBody(
                source_strategy_id=9,
                exchange="okx",
                loop_interval=60,
            )
        )
    )

    contract_check = next(c for c in res["checks"] if c["item"] == "账户合约交易能力")
    assert contract_check["passed"] is True
    assert precheck_payloads == [
        {
            "instId": "BTC-USDT-SWAP",
            "tdMode": "isolated",
            "side": "buy",
            "ordType": "market",
            "sz": "0.01",
        }
    ]
