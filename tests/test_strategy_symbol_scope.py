import sys
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import backtest
from app.api.v2.endpoints.backtest import (
    BacktestRequest,
    _strategy_cost_request_for_backtest,
    _strategy_config_for_backtest,
    _strategy_symbols_for_backtest,
    _strategy_timeframe_for_backtest,
)
from app.api.v2.endpoints import live
from app.core.execution.base_strategy import BarData, BaseStrategy
import app.services.backtrader_engine as backtrader_module
from app.services.backtrader_engine import BacktestEngine


def test_backtest_uses_strategy_symbols_before_legacy_request_symbol():
    request = BacktestRequest(
        strategy_id=9,
        symbol="BTC/USDT",
        timeframe="1m",
        start_date="2026-04-28",
        end_date="2026-04-29",
    )
    strategy_info = {
        "symbols": ["ZKJ/USDT", "BIO/USDT", "APE/USDT"],
        "db_config": {"symbols": ["BTC/USDT"]},
    }

    assert _strategy_symbols_for_backtest(strategy_info, request) == [
        "ZKJ/USDT",
        "BIO/USDT",
        "APE/USDT",
    ]


def test_contract_backtest_normalizes_feed_symbols_to_swap_market_data():
    request = BacktestRequest(
        strategy_id=9,
        symbol="XRP/USDT",
        timeframe="1m",
        start_date="2026-04-28",
        end_date="2026-04-29",
    )
    strategy_info = {
        "name": "[合约] Legacy CTA",
        "symbols": ["BTC/USDT", "ETH-USDT-SWAP"],
        "db_config": {"market_type": "swap", "inst_type": "SWAP"},
    }

    assert _strategy_symbols_for_backtest(strategy_info, request) == [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
    ]


def test_spot_backtest_normalizes_feed_symbols_to_spot_market_data():
    request = BacktestRequest(
        strategy_id=9,
        symbol="XRP/USDT:USDT",
        timeframe="1m",
        start_date="2026-04-28",
        end_date="2026-04-29",
    )
    strategy_info = {
        "name": "[现货] Spot CTA",
        "symbols": ["BTC/USDT:USDT", "ETH-USDT-SWAP"],
        "db_config": {"market_type": "spot"},
    }

    assert _strategy_symbols_for_backtest(strategy_info, request) == [
        "BTC/USDT",
        "ETH/USDT",
    ]


def test_backtest_uses_strategy_timeframe_by_default_before_legacy_request_timeframe():
    request = BacktestRequest(
        strategy_id=9,
        symbol="BTC/USDT",
        timeframe="15m",
        start_date="2026-04-28",
        end_date="2026-04-29",
    )
    strategy_info = {
        "symbols": ["BTC/USDT"],
        "db_config": {"timeframe": "1h"},
    }

    assert _strategy_timeframe_for_backtest(strategy_info, request) == "1h"


def test_backtest_single_timeframe_mode_overrides_strategy_timeframe():
    request = BacktestRequest(
        strategy_id=9,
        symbol="BTC/USDT",
        timeframe="15m",
        timeframe_mode="single",
        start_date="2026-04-28",
        end_date="2026-04-29",
    )
    strategy_info = {
        "symbols": ["BTC/USDT"],
        "db_config": {"timeframe": "1h"},
    }

    assert _strategy_timeframe_for_backtest(strategy_info, request) == "15m"


def test_backtest_matrix_timeframes_are_normalized_and_deduplicated():
    request = BacktestRequest(
        strategy_id=9,
        symbol="BTC/USDT",
        timeframe_mode="matrix",
        timeframes=["15M", "1h", "15m", "bad"],
        start_date="2026-04-28",
        end_date="2026-04-29",
    )
    strategy_info = {
        "symbols": ["BTC/USDT"],
        "db_config": {"timeframe": "5m"},
    }

    assert backtest._strategy_timeframes_for_backtest(strategy_info, request) == ["15m", "1h"]


def test_backtest_strategy_config_uses_effective_timeframe_override():
    strategy_config = {"timeframe": "1h", "kline_timeframe": "1h", "symbols": ["BTC/USDT"]}

    resolved = _strategy_config_for_backtest(strategy_config, "15m")

    assert resolved["timeframe"] == "15m"
    assert resolved["kline_timeframe"] == "15m"
    assert strategy_config["timeframe"] == "1h"


def test_backtest_timeframe_legacy_request_is_only_compatibility_fallback():
    request = BacktestRequest(
        strategy_id=9,
        symbol="BTC/USDT",
        timeframe="15m",
        start_date="2026-04-28",
        end_date="2026-04-29",
    )
    strategy_info = {
        "symbols": ["BTC/USDT"],
        "db_config": {},
    }

    assert _strategy_timeframe_for_backtest(strategy_info, request) == "15m"


def test_backtest_uses_okx_spot_fee_defaults_when_strategy_has_no_cost_config():
    request = BacktestRequest(
        strategy_id=9,
        symbol="BTC/USDT",
        start_date="2026-04-28",
        end_date="2026-04-29",
    )
    strategy_info = {
        "name": "[现货] Example",
        "symbols": ["BTC/USDT"],
        "db_config": {"market_type": "spot"},
    }

    resolved = _strategy_cost_request_for_backtest(request, strategy_info)

    assert resolved.maker_fee_bps == pytest.approx(8.0)
    assert resolved.taker_fee_bps == pytest.approx(10.0)
    assert resolved.slippage_bps == pytest.approx(1.0)
    assert resolved.commission == pytest.approx(0.001)
    assert resolved.slippage == pytest.approx(0.0001)


def test_backtest_uses_okx_swap_fee_defaults_when_strategy_is_contract():
    request = BacktestRequest(
        strategy_id=9,
        symbol="BTC/USDT:USDT",
        start_date="2026-04-28",
        end_date="2026-04-29",
    )
    strategy_info = {
        "name": "[合约] Example",
        "symbols": ["BTC/USDT:USDT"],
        "db_config": {"market_type": "swap", "inst_type": "SWAP"},
    }

    resolved = _strategy_cost_request_for_backtest(request, strategy_info)

    assert resolved.maker_fee_bps == pytest.approx(2.0)
    assert resolved.taker_fee_bps == pytest.approx(5.0)
    assert resolved.slippage_bps == pytest.approx(1.0)
    assert resolved.commission == pytest.approx(0.0005)
    assert resolved.slippage == pytest.approx(0.0001)


def test_backtest_cost_fields_override_legacy_single_rate():
    request = BacktestRequest(
        strategy_id=9,
        symbol="BTC/USDT",
        start_date="2026-04-28",
        end_date="2026-04-29",
        commission=0.0,
        slippage=0.0,
        maker_fee_bps=7.0,
        taker_fee_bps=9.0,
        slippage_bps=3.0,
    )
    strategy_info = {
        "symbols": ["BTC/USDT"],
        "db_config": {"maker_fee_bps": 8, "taker_fee_bps": 10, "slippage_bps": 5},
    }

    resolved = _strategy_cost_request_for_backtest(request, strategy_info)

    assert resolved.maker_fee_bps == pytest.approx(7.0)
    assert resolved.taker_fee_bps == pytest.approx(9.0)
    assert resolved.slippage_bps == pytest.approx(3.0)
    assert resolved.commission == pytest.approx(0.0009)
    assert resolved.slippage == pytest.approx(0.0003)


def test_backtest_legacy_percent_inputs_are_not_treated_as_decimal_rates():
    request = BacktestRequest(
        strategy_id=9,
        symbol="BTC/USDT",
        start_date="2026-04-28",
        end_date="2026-04-29",
        commission=0.08,
        slippage=0.05,
    )
    strategy_info = {
        "name": "[现货] Example",
        "symbols": ["BTC/USDT"],
        "db_config": {"market_type": "spot"},
    }

    resolved = _strategy_cost_request_for_backtest(request, strategy_info)

    assert resolved.taker_fee_bps == pytest.approx(8.0)
    assert resolved.slippage_bps == pytest.approx(5.0)
    assert resolved.commission == pytest.approx(0.0008)
    assert resolved.slippage == pytest.approx(0.0005)


def test_live_configure_preserves_strategy_defined_symbols_for_regular_strategy():
    cfg = {"selected_symbol": "BTC/USDT"}
    row = {
        "name": "Kairos 30分钟视界 DCA（1m执行）",
        "symbols": ["ETH/USDT", "SOL/USDT"],
        "config": {},
    }

    symbols = live._configured_symbols(row, cfg, selected_symbol="BTC/USDT")

    assert symbols == ["ETH/USDT", "SOL/USDT"]
    assert cfg["symbol_scope"] == "strategy_symbols"
    assert "selected_symbol" not in cfg


def test_live_configure_preserves_strategy_defined_timeframe(monkeypatch):
    class FakeCursor:
        def __init__(self):
            self.params = None

        def execute(self, sql, params):
            self.params = params

    class FakeConn:
        def __init__(self):
            self.cur = FakeCursor()

        def cursor(self):
            return self.cur

        def commit(self):
            pass

        def close(self):
            pass

    row = {
        "id": 11,
        "name": "Strategy with own timeframe",
        "symbols": ["ETH/USDT"],
        "config": {"timeframe": "1h", "strategy_key": "example"},
    }
    conn = FakeConn()

    monkeypatch.setattr(live.db, "get_strategy_by_id", lambda strategy_id: row)
    monkeypatch.setattr(live.db, "get_connection", lambda: conn)
    monkeypatch.setattr(live.db, "close_open_paper_instances", lambda strategy_id, ended_at: 0)
    monkeypatch.setattr(
        live.db,
        "create_paper_instance",
        lambda **kwargs: {
            "instance_id": "paper-test-timeframe",
            "strategy_version": kwargs["strategy_version"],
            "config_version": kwargs["config_version"],
            "configured_at": kwargs["configured_at"],
            "started_at": None,
        },
    )
    monkeypatch.setattr(live.db, "insert_paper_instance_event", lambda *args, **kwargs: 1)
    monkeypatch.setattr(live.strategy_engine, "get_strategy_status", lambda strategy_id: None)
    monkeypatch.setattr(live.strategy_engine, "drop_cached_context", lambda strategy_id: None)

    asyncio.run(
        live.live_configure(
            live.LiveConfigureBody(
                strategy_type="11",
                exchange="okx",
                initial_equity=10000,
                dry_run=True,
            )
        )
    )

    assert conn.cur.params is not None
    saved_cfg = json.loads(conn.cur.params[2])
    assert saved_cfg["timeframe"] == "1h"
    assert saved_cfg["initial_capital"] == 10000


def test_live_configure_restores_superpnl_default_universe_when_seed_row_is_incomplete():
    cfg = {"strategy_key": "superpnl_15m_low_turnover"}
    row = {"name": "SuperPnL test", "symbols": [], "config": cfg}

    symbols = live._configured_symbols(row, cfg)

    assert symbols == live._SUPERPNL_DEFAULT_SYMBOLS
    assert cfg["symbol_scope"] == "superpnl_top20_universe"


def test_live_preflight_checks_real_account_when_not_dry_run(monkeypatch):
    seen_timeframes = []

    class FakeExchange:
        def fetch_ohlcv(self, symbol, timeframe, limit=3):
            seen_timeframes.append(timeframe)
            return [[int(time.time() * 1000), 1, 1, 1, 1, 1]]

        def fetch_open_orders(self, symbol=None):
            return []

    async def fake_balance(exchange):
        return [{"currency": "USDT", "free": 88.0, "total": 100.0}]

    monkeypatch.setattr(live.exchange_manager, "get_exchange", lambda exchange: FakeExchange())
    monkeypatch.setattr(live.strategy_engine, "get_risk_status", lambda: {"circuit_breaker": False})
    monkeypatch.setattr(
        live.db,
        "get_strategy_by_id",
        lambda strategy_id: {
            "name": "Kairos test",
            "symbols": ["BTC/USDT"],
            "config": {"timeframe": "1m"},
        },
    )
    monkeypatch.setattr(live.trading_service, "get_balance", fake_balance)

    res = asyncio.run(
        live.live_pre_flight(
            live.PreFlightBody(
                strategy="1",
                exchange="okx",
                dry_run=False,
            )
        )
    )
    data = res["data"]

    account_check = next(c for c in data["checks"] if c["item"] == "实盘账户权限与 USDT 余额")
    assert account_check["passed"] is True
    assert "USDT 可用 88.00" in account_check["detail"]
    assert data["all_passed"] is True
    assert seen_timeframes == ["1m"]


def test_promote_to_live_config_creates_isolated_trial_config(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    row = {
        "id": 42,
        "name": "Paper winner",
        "config": {
            "strategy_key": "kairos_path_edge",
            "is_paper_trading": True,
            "timeframe": "1m",
            "entry_quote_usdt": 200,
            "max_position_pct": 0.2,
            "max_total_position_pct": 0.4,
        },
    }

    cfg = live._build_promoted_live_config(
        row,
        initial_equity=100,
        loop_interval=60,
        risk_config={"risk_per_trade_pct": 0.03, "max_daily_loss_pct": 0.08},
    )

    assert cfg["is_paper_trading"] is False
    assert cfg["initial_capital"] == 100
    assert cfg["entry_quote_usdt"] == 5
    assert cfg["max_position_pct"] == 0.03
    assert cfg["max_total_position_pct"] == 0.08
    assert cfg["risk_per_trade_pct"] == 0.01
    assert cfg["max_daily_loss_pct"] == 0.02
    assert cfg["promotion"]["source_strategy_id"] == 42
    assert cfg["promotion"]["code_commit"] == "abc123"


def test_promoted_live_strategy_name_has_asset_class_prefix():
    assert live._promoted_live_strategy_name({
        "id": 42,
        "name": "[现货] Paper winner",
        "config": {"market_type": "spot"},
    }) == "[现货] [实盘试运行] Paper winner"
    assert live._promoted_live_strategy_name({
        "id": 43,
        "name": "[合约] Contract winner",
        "config": {},
    }) == "[合约] [实盘试运行] Contract winner"


def test_promote_to_live_preflight_uses_real_trading_candidate(monkeypatch):
    class FakeExchange:
        def fetch_ohlcv(self, symbol, timeframe, limit=3):
            assert symbol == "BTC/USDT"
            assert timeframe == "1m"
            return [[int(time.time() * 1000), 1, 1, 1, 1, 1]]

        def fetch_open_orders(self, symbol=None):
            return []

    class FakeStrategy:
        pass

    async def fake_balance(exchange):
        assert exchange == "okx"
        return [{"currency": "USDT", "free": 88.0, "total": 100.0}]

    monkeypatch.setattr(
        live.live_account_service,
        "validate_account_trade_permission",
        lambda account_id: {
            "can_read": True,
            "can_trade": True,
            "checked_at": "2026-05-09T00:00:00+00:00",
            "detail": "读取权限和交易权限测试通过",
        },
    )
    monkeypatch.setattr(live.exchange_manager, "get_exchange", lambda exchange: FakeExchange())
    monkeypatch.setattr(live.trading_service, "get_balance", fake_balance)
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
            "id": 7,
            "name": "Paper candidate",
            "symbols": ["BTC/USDT"],
            "config": {"is_paper_trading": True, "timeframe": "1m"},
            "script_content": "",
        },
    )
    monkeypatch.setattr(live.db, "get_strategies", lambda: [])

    res = asyncio.run(
        live.promote_to_live_preflight(
            live.PromoteToLiveBody(
                source_strategy_id=7,
                exchange="okx",
                initial_equity=100,
                loop_interval=60,
            )
        )
    )
    data = res["data"]

    assert data["all_passed"] is True
    assert data["plan"]["dry_run"] is False
    assert data["plan"]["mode"] == "live"
    mode_check = next(c for c in data["checks"] if c["item"] == "真实交易路径配置")
    assert mode_check["passed"] is True
    account_check = next(c for c in data["checks"] if c["item"] == "实盘账户权限与 USDT 余额")
    assert account_check["passed"] is True


def test_promote_to_live_preflight_rejects_missing_strategy_symbols(monkeypatch):
    class FakeStrategy:
        pass

    def fail_exchange_lookup(exchange):
        raise AssertionError("runtime preflight should not run when strategy symbols are missing")

    monkeypatch.setattr(live.exchange_manager, "get_exchange", fail_exchange_lookup)
    monkeypatch.setattr(
        live,
        "resolve_unified_base_strategy_class",
        lambda row: (FakeStrategy, row.get("config") or {}),
    )
    monkeypatch.setattr(
        live.db,
        "get_strategy_by_id",
        lambda strategy_id: {
            "id": 8,
            "name": "No symbols paper",
            "symbols": [],
            "config": {"is_paper_trading": True, "timeframe": "1m"},
            "script_content": "",
        },
    )
    monkeypatch.setattr(live.db, "get_strategies", lambda: [])

    res = asyncio.run(
        live.promote_to_live_preflight(
            live.PromoteToLiveBody(
                source_strategy_id=8,
                exchange="okx",
                initial_equity=100,
                loop_interval=60,
            )
        )
    )
    data = res["data"]

    assert data["all_passed"] is False
    symbol_check = next(c for c in data["checks"] if c["item"] == "策略交易对匹配")
    assert symbol_check["passed"] is False
    assert "不能隐式改用默认币种" in symbol_check["detail"]
    assert data["plan"]["symbols"] == []


def test_promote_to_live_preflight_accepts_dynamic_runtime_symbols(monkeypatch):
    class FakeDynamicStrategy:
        @classmethod
        def resolve_runtime_symbols(cls, exchange_name, config):
            assert exchange_name == "okx:acct-1"
            assert config["is_paper_trading"] is False
            return ["BTC/USDT:USDT", "ETH/USDT:USDT"]

    monkeypatch.setattr(live.live_account_service, "validate_account_id", lambda account_id: account_id)
    monkeypatch.setattr(live.live_account_service, "exchange_alias_for_account", lambda account_id: f"okx:{account_id}")
    monkeypatch.setattr(
        live,
        "resolve_unified_base_strategy_class",
        lambda row: (FakeDynamicStrategy, row.get("config") or {}),
    )
    monkeypatch.setattr(live, "_live_subscription_for_source", lambda *args, **kwargs: None)
    monkeypatch.setattr(live, "_live_promotion_conflicts", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        live.db,
        "get_strategy_by_id",
        lambda strategy_id: {
            "id": 9,
            "name": "[合约] 动态CTA趋势跟踪 · Top15 15m 100U版",
            "symbols": [],
            "config": {
                "strategy_key": "dynamic_cta_trend_following_top15",
                "is_paper_trading": True,
                "market_type": "swap",
                "timeframe": "15m",
                "trade_symbols": [],
                "dynamic_liquidity_top_n": 50,
                "dynamic_candidate_top_n": 15,
            },
            "script_content": "",
        },
    )

    prepared = live._prepare_promoted_live_candidate(
        live.PromoteToLiveBody(
            source_strategy_id=9,
            account_id="acct-1",
            exchange="okx",
            initial_equity=100,
            loop_interval=60,
        )
    )
    checks = live._promotion_matching_checks(prepared)
    symbol_check = next(c for c in checks if c["item"] == "策略交易对匹配")

    assert prepared["symbols"] == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert prepared["symbol_scope"] == "dynamic_runtime_symbols"
    assert symbol_check["passed"] is True
    assert "动态运行币池" in symbol_check["detail"]


def test_promote_to_live_preflight_filters_low_depth_dynamic_symbols(monkeypatch):
    dynamic_symbols = [f"SYM{i}/USDT:USDT" for i in range(12)]
    low_depth = {"SYM3/USDT:USDT", "SYM9/USDT:USDT"}

    class FakeDynamicStrategy:
        @classmethod
        def resolve_runtime_symbols(cls, exchange_name, config):
            assert exchange_name == "okx:acct-1"
            assert config["is_paper_trading"] is False
            return dynamic_symbols

    class FakeExchange:
        def fetch_ohlcv(self, symbol, timeframe, limit=3):
            assert symbol in dynamic_symbols
            return [[int(time.time() * 1000), 1, 1, 1, 1, 1]]

        def fetch_open_orders(self, symbol=None):
            return []

        def fetch_order_book(self, symbol, limit=5):
            if symbol in low_depth:
                return {
                    "bids": [[1.0, 1.0] for _ in range(5)],
                    "asks": [[1.001, 1.0] for _ in range(5)],
                }
            return {
                "bids": [[1.0, 100.0] for _ in range(5)],
                "asks": [[1.001, 100.0] for _ in range(5)],
            }

    async def fake_balance(exchange):
        assert exchange == "okx:acct-1"
        return [{"currency": "USDT", "free": 1000.0, "total": 1000.0}]

    async def fake_trade_permission(account_id):
        assert account_id == "acct-1"
        return {"item": "账户交易权限", "passed": True, "detail": "读取权限和交易权限测试通过"}

    async def fake_contract_precheck(**kwargs):
        return {"item": "账户合约交易能力", "passed": True, "detail": "合约预检查通过"}

    monkeypatch.setattr(live.live_account_service, "validate_account_id", lambda account_id: account_id)
    monkeypatch.setattr(live.live_account_service, "exchange_alias_for_account", lambda account_id: f"okx:{account_id}")
    monkeypatch.setattr(live.exchange_manager, "get_exchange", lambda exchange: FakeExchange())
    monkeypatch.setattr(live.trading_service, "get_balance", fake_balance)
    monkeypatch.setattr(live.strategy_engine, "get_risk_status", lambda: {"circuit_breaker": False})
    monkeypatch.setattr(live, "_live_account_trade_permission_check", fake_trade_permission)
    monkeypatch.setattr(live, "_live_contract_account_precheck", fake_contract_precheck)
    monkeypatch.setattr(
        live,
        "resolve_unified_base_strategy_class",
        lambda row: (FakeDynamicStrategy, row.get("config") or {}),
    )
    monkeypatch.setattr(live, "_live_subscription_for_source", lambda *args, **kwargs: None)
    monkeypatch.setattr(live, "_live_promotion_conflicts", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        live.db,
        "get_strategy_by_id",
        lambda strategy_id: {
            "id": 10,
            "name": "[合约][15M][CTA] Top15 · 动态趋势跟踪 · 100U",
            "symbols": [],
            "config": {
                "strategy_key": "dynamic_cta_trend_following_top15",
                "is_paper_trading": True,
                "market_type": "swap",
                "timeframe": "15m",
                "trade_symbols": [],
                "dynamic_liquidity_top_n": 50,
                "dynamic_candidate_top_n": 15,
                "live_preflight_min_symbols": 10,
                "stop_loss_bps": 50.0,
                "take_profit_bps": 100.0,
            },
            "script_content": "",
        },
    )

    data = asyncio.run(
        live.promote_to_live_preflight(
            live.PromoteToLiveBody(
                source_strategy_id=10,
                account_id="acct-1",
                exchange="okx",
                initial_equity=100,
                loop_interval=60,
            )
        )
    )["data"]

    depth_check = next(c for c in data["checks"] if c["item"] == "订单簿点差与深度")

    assert data["all_passed"] is True
    assert depth_check["passed"] is True
    assert "已剔除 2 个低流动性标的" in depth_check["detail"]
    assert data["plan"]["symbols"] == [sym for sym in dynamic_symbols if sym not in low_depth]
    assert data["plan"]["excluded_symbols"] == ["SYM3/USDT:USDT", "SYM9/USDT:USDT"]


class MultiSymbolRoundTripStrategy(BaseStrategy):
    async def on_init(self) -> None:
        self._counts = {symbol: 0 for symbol in self.symbols()}

    async def on_bar(self, bar: BarData) -> None:
        self._counts[bar.symbol] = self._counts.get(bar.symbol, 0) + 1
        count = self._counts[bar.symbol]
        if count == 1:
            await self.buy(bar.symbol, 1.0)
        elif count == 3:
            await self.close_position(bar.symbol)


def test_backtrader_routes_orders_to_each_strategy_symbol(monkeypatch):
    def fake_load_dataframe(self, exchange, symbol, timeframe, start_date, end_date, **kwargs):
        base = 10.0 if symbol == "AAA/USDT" else 100.0
        idx = pd.date_range("2026-01-01 00:00:00", periods=6, freq="min")
        return pd.DataFrame(
            {
                "open": [base, base + 1, base + 2, base + 3, base + 4, base + 5],
                "high": [base + 1, base + 2, base + 3, base + 4, base + 5, base + 6],
                "low": [base - 1, base, base + 1, base + 2, base + 3, base + 4],
                "close": [base, base + 1, base + 2, base + 3, base + 4, base + 5],
                "volume": [100.0] * 6,
            },
            index=idx,
        )

    monkeypatch.setattr(BacktestEngine, "_load_dataframe", fake_load_dataframe)

    report = BacktestEngine().run_strategy(
        MultiSymbolRoundTripStrategy,
        exchange="okx",
        symbol="AAA/USDT",
        symbols=["AAA/USDT", "BBB/USDT"],
        timeframe="1m",
        start_date="2026-01-01",
        end_date="2026-01-02",
        initial_capital=1000.0,
        commission=0.0,
        slippage=0.0,
    )

    assert report.status == "completed"
    assert {trade["symbol"] for trade in report.trades} == {"AAA/USDT", "BBB/USDT"}


def test_backtrader_reads_sqlite_kline_cache_before_exchange_fetch(monkeypatch):
    base_ts = int(datetime.strptime("2026-01-01", "%Y-%m-%d").timestamp() * 1000)
    rows = [
        {
            "timestamp": base_ts + i * 60_000,
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.0 + i,
            "volume": 1000.0,
            "quote_volume": 100_000.0,
        }
        for i in range(1441)
    ]

    class FakeDb:
        def get_klines(self, exchange, symbol, timeframe, limit, start, end):
            assert exchange == "okx"
            assert symbol == "AAA/USDT"
            assert timeframe == "1m"
            return rows

    monkeypatch.setattr(
        backtrader_module.kline_store,
        "read_dataframe",
        lambda *args, **kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(backtrader_module, "db", FakeDb())
    monkeypatch.setattr(
        BacktestEngine,
        "_fetch_and_cache_klines",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not fetch OKX")),
    )

    report = BacktestEngine().run_strategy(
        MultiSymbolRoundTripStrategy,
        exchange="okx",
        symbol="AAA/USDT",
        symbols=["AAA/USDT"],
        timeframe="1m",
        start_date="2026-01-01",
        end_date="2026-01-02",
        initial_capital=1000.0,
        commission=0.0,
        slippage=0.0,
    )

    assert report.status == "completed"
    assert report.total_bars == 1441
    assert {trade["symbol"] for trade in report.trades} == {"AAA/USDT"}


def test_backtrader_fetches_when_cached_kline_range_is_incomplete(monkeypatch):
    start_ts = int(datetime.strptime("2026-01-01", "%Y-%m-%d").timestamp() * 1000)
    partial_rows = [
        {
            "timestamp": start_ts + (1400 + i) * 60_000,
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.0 + i,
            "volume": 1000.0,
        }
        for i in range(20)
    ]
    full_rows = [
        {
            "timestamp": start_ts + i * 60_000,
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.0 + i,
            "volume": 1000.0,
        }
        for i in range(1441)
    ]
    state = {"fetched": False}

    class FakeDb:
        def get_klines(self, exchange, symbol, timeframe, limit, start, end):
            return full_rows if state["fetched"] else partial_rows

    def fake_fetch(self, exchange, symbol, timeframe, start, end, **kwargs):
        state["fetched"] = True
        return len(full_rows)

    monkeypatch.setattr(
        backtrader_module.kline_store,
        "read_dataframe",
        lambda *args, **kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(backtrader_module, "db", FakeDb())
    monkeypatch.setattr(BacktestEngine, "_fetch_and_cache_klines", fake_fetch)

    report = BacktestEngine().run_strategy(
        MultiSymbolRoundTripStrategy,
        exchange="okx",
        symbol="AAA/USDT",
        symbols=["AAA/USDT"],
        timeframe="1m",
        start_date="2026-01-01",
        end_date="2026-01-02",
        initial_capital=1000.0,
        commission=0.0,
        slippage=0.0,
    )

    assert state["fetched"] is True
    assert report.total_bars == 1441


def test_backtrader_fetches_when_cached_kline_start_is_incomplete(monkeypatch):
    start_ts = int(datetime.strptime("2026-01-01", "%Y-%m-%d").timestamp() * 1000)
    partial_rows = [
        {
            "timestamp": start_ts + (241 + i) * 60_000,
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.0 + i,
            "volume": 1000.0,
        }
        for i in range(1200)
    ]
    full_rows = [
        {
            "timestamp": start_ts + i * 60_000,
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.0 + i,
            "volume": 1000.0,
        }
        for i in range(1441)
    ]
    state = {"fetched": False}

    class FakeDb:
        def get_klines(self, exchange, symbol, timeframe, limit, start, end):
            return full_rows if state["fetched"] else partial_rows

    def fake_fetch(self, exchange, symbol, timeframe, start, end, **kwargs):
        state["fetched"] = True
        return len(full_rows)

    monkeypatch.setattr(
        backtrader_module.kline_store,
        "read_dataframe",
        lambda *args, **kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(backtrader_module, "db", FakeDb())
    monkeypatch.setattr(BacktestEngine, "_fetch_and_cache_klines", fake_fetch)

    report = BacktestEngine().run_strategy(
        MultiSymbolRoundTripStrategy,
        exchange="okx",
        symbol="AAA/USDT",
        symbols=["AAA/USDT"],
        timeframe="1m",
        start_date="2026-01-01",
        end_date="2026-01-02",
        initial_capital=1000.0,
        commission=0.0,
        slippage=0.0,
    )

    assert state["fetched"] is True
    assert report.total_bars == 1441
    assert report.equity_curve[0]["timestamp"] == start_ts


def test_backtrader_rejects_repeated_kline_price_discontinuities(monkeypatch):
    start_ts = int(datetime.strptime("2026-03-04", "%Y-%m-%d").timestamp() * 1000)
    rows = []
    close = 1975.89
    for i in range(49):
        ts = start_ts + i * 3_600_000
        if i % 2 == 1:
            open_price = close * 10.0
            close_price = open_price * 1.005
        else:
            open_price = close * 0.10 if i else close
            close_price = open_price * 0.995
        rows.append(
            {
                "timestamp": ts,
                "open": round(open_price, 2),
                "high": round(max(open_price, close_price) * 1.01, 2),
                "low": round(min(open_price, close_price) * 0.99, 2),
                "close": round(close_price, 2),
                "volume": 1000.0,
            }
        )
        close = close_price

    class FakeDb:
        def get_klines(self, exchange, symbol, timeframe, limit, start, end):
            return []

    monkeypatch.setattr(
        backtrader_module.kline_store,
        "read_dataframe",
        lambda *args, **kwargs: pd.DataFrame(rows),
    )
    monkeypatch.setattr(backtrader_module, "db", FakeDb())
    monkeypatch.setattr(
        BacktestEngine,
        "_fetch_and_cache_klines",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("coverage is complete")),
    )

    with pytest.raises(ValueError) as exc_info:
        BacktestEngine()._load_dataframe(
            "okx",
            "ETH/USDT:USDT",
            "1h",
            "2026-03-04",
            "2026-03-06",
        )

    message = str(exc_info.value)
    assert "真实 K 线连续性异常" in message
    assert "ETH/USDT:USDT 1h" in message
    assert "2026-03-04" in message


def test_backtrader_allows_repeated_but_bounded_open_gaps() -> None:
    start_ts = int(datetime.strptime("2026-03-04", "%Y-%m-%d").timestamp() * 1000)
    rows = []
    close = 100.0
    for i in range(49):
        ts = start_ts + i * 3_600_000
        open_price = close * (1.30 if i % 2 else 0.77) if i else close
        close_price = open_price * (1.005 if i % 2 else 0.995)
        rows.append({
            "timestamp": ts,
            "open": open_price,
            "high": max(open_price, close_price) * 1.01,
            "low": min(open_price, close_price) * 0.99,
            "close": close_price,
            "volume": 1000.0,
        })
        close = close_price

    error = BacktestEngine._kline_sanity_error(
        pd.DataFrame(rows),
        "okx",
        "AXS/USDT:USDT",
        "1h",
    )

    assert error is None


def test_backtrader_prefers_file_store_rows_over_sqlite_duplicate_timestamps(monkeypatch):
    start_ts = int(datetime.strptime("2026-01-01", "%Y-%m-%d").timestamp() * 1000)
    file_rows = [
        {
            "timestamp": start_ts + i * 60_000,
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.0 + i,
            "volume": 1000.0,
        }
        for i in range(1441)
    ]
    sqlite_rows = [
        {
            "timestamp": row["timestamp"],
            "open": row["open"] * 10,
            "high": row["high"] * 10,
            "low": row["low"] * 10,
            "close": row["close"] * 10,
            "volume": row["volume"],
        }
        for row in file_rows
    ]

    class FakeDb:
        def get_klines(self, exchange, symbol, timeframe, limit, start, end):
            return sqlite_rows

    monkeypatch.setattr(
        backtrader_module.kline_store,
        "read_dataframe",
        lambda *args, **kwargs: pd.DataFrame(file_rows),
    )
    monkeypatch.setattr(backtrader_module, "db", FakeDb())
    monkeypatch.setattr(
        BacktestEngine,
        "_fetch_and_cache_klines",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not fetch OKX")),
    )

    df = BacktestEngine()._load_dataframe(
        "okx",
        "AAA/USDT",
        "1m",
        "2026-01-01",
        "2026-01-02",
    )

    assert df.iloc[0]["close"] == 100.0
    assert df.iloc[-1]["close"] == 1540.0


def test_backtrader_reports_all_missing_symbol_data(monkeypatch):
    def fail_load_dataframe(self, exchange, symbol, timeframe, start_date, end_date, **kwargs):
        raise ValueError(f"无法获取数据: {symbol}")

    monkeypatch.setattr(BacktestEngine, "_load_dataframe", fail_load_dataframe)

    with pytest.raises(ValueError) as exc_info:
        BacktestEngine().run_strategy(
            MultiSymbolRoundTripStrategy,
            exchange="okx",
            symbol="AAA/USDT",
            symbols=["AAA/USDT", "BBB/USDT"],
            timeframe="1m",
            start_date="2026-01-01",
            end_date="2026-01-02",
            initial_capital=1000.0,
            commission=0.0,
            slippage=0.0,
        )

    message = str(exc_info.value)
    assert "AAA/USDT" in message
    assert "BBB/USDT" in message
    assert "无法从交易所补齐" in message
