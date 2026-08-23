import asyncio
import sys
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BaseStrategy, BarData
from app.api.v2.endpoints.backtest import BacktestRequest, _backtest_report_to_response
from app.services import backtrader_engine as backtrader_engine_module
from app.services.backtrader_engine import BacktestCancelled, BacktestEngine
from app.strategies.contract_martingale_grid_strategy import ContractMartingaleGridStrategy
from app.strategies.contract_shared_martingale_grid_strategy import ContractSharedMartingaleGridStrategy


class ContractRoundTripStrategy(BaseStrategy):
    async def on_init(self):
        self.count = 0

    async def on_bar(self, bar: BarData) -> None:
        self.count += 1
        if self.count == 1:
            await self.open_contract(bar.symbol, "long", 1_000.0, leverage=2.0)
        elif self.count == 3:
            await self.close_contract(bar.symbol, "long")


class LeveragedLongStrategy(BaseStrategy):
    async def on_init(self):
        self.count = 0

    async def on_bar(self, bar: BarData) -> None:
        self.count += 1
        if self.count == 1:
            await self.open_contract(bar.symbol, "long", 125.0, leverage=5.0)
        elif self.count == 3:
            await self.close_contract(bar.symbol, "long")


class BrokerPositionAwareSpotStrategy(BaseStrategy):
    async def on_init(self):
        self.count = 0

    async def on_bar(self, bar: BarData) -> None:
        self.count += 1
        if self.count == 1:
            await self.buy(bar.symbol, 1.0)
            return
        if self.count >= 3:
            position = getattr(self.broker, "positions", {}).get(bar.symbol)
            if position and float(position.get("size") or 0.0) > 0:
                await self.sell(bar.symbol, float(position["size"]))


class BuyAndHoldSpotStrategy(BaseStrategy):
    async def on_init(self):
        self.count = 0

    async def on_bar(self, bar: BarData) -> None:
        self.count += 1
        if self.count == 1:
            await self.buy(bar.symbol, 1.0)


class LoopIdentityStrategy(BaseStrategy):
    observed_loops = []

    @classmethod
    def reset_observed_loops(cls) -> None:
        cls.observed_loops = []

    @classmethod
    def observe_loop(cls) -> None:
        cls.observed_loops.append(asyncio.get_running_loop())

    async def on_init(self) -> None:
        self.observe_loop()

    async def on_start(self) -> None:
        self.observe_loop()

    async def on_bar(self, bar: BarData) -> None:
        self.observe_loop()

    async def on_stop(self) -> None:
        self.observe_loop()


class FailingLoopIdentityStrategy(LoopIdentityStrategy):
    async def on_bar(self, bar: BarData) -> None:
        self.observe_loop()
        raise RuntimeError("intentional strategy failure")


class CancellableLoopIdentityStrategy(LoopIdentityStrategy):
    started = False

    @classmethod
    def reset_observed_loops(cls) -> None:
        super().reset_observed_loops()
        cls.started = False

    async def on_start(self) -> None:
        self.observe_loop()
        type(self).started = True


def _df():
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2026-01-01", periods=5, freq="min"),
            "open": [100, 101, 102, 103, 104],
            "high": [101, 102, 103, 104, 105],
            "low": [99, 100, 101, 102, 103],
            "close": [100, 101, 102, 103, 104],
            "volume": [100, 100, 100, 100, 100],
        }
    ).set_index("datetime")


def _martingale_df():
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2026-01-01", periods=8, freq="min"),
            "open": [100, 100, 100, 99, 98, 99, 100, 101],
            "high": [101, 101, 101, 100, 99, 100, 101, 102],
            "low": [99, 99, 99, 98, 97, 98, 99, 100],
            "close": [100, 100, 100, 99, 98, 99, 100, 101],
            "volume": [1000] * 8,
        }
    ).set_index("datetime")


def _run_loop_identity_backtest(monkeypatch) -> None:
    engine = BacktestEngine()
    monkeypatch.setattr(engine, "_load_dataframe", lambda *args, **kwargs: _df())
    LoopIdentityStrategy.reset_observed_loops()

    engine.run_strategy(
        LoopIdentityStrategy,
        exchange="okx",
        symbol="BTC/USDT",
        symbols=["BTC/USDT"],
        timeframe="1m",
        initial_capital=10_000,
        commission=0.0,
        slippage=0.0,
    )


def test_backtrader_reuses_one_event_loop_for_strategy_lifecycle(monkeypatch):
    _run_loop_identity_backtest(monkeypatch)

    assert len(LoopIdentityStrategy.observed_loops) == len(_df()) + 3
    assert len({id(loop) for loop in LoopIdentityStrategy.observed_loops}) == 1
    assert LoopIdentityStrategy.observed_loops[0].is_closed()


def test_backtrader_reuses_one_worker_loop_when_caller_loop_is_running(monkeypatch):
    async def run_inside_event_loop() -> None:
        _run_loop_identity_backtest(monkeypatch)

    asyncio.run(run_inside_event_loop())

    assert len(LoopIdentityStrategy.observed_loops) == len(_df()) + 3
    assert len({id(loop) for loop in LoopIdentityStrategy.observed_loops}) == 1
    assert LoopIdentityStrategy.observed_loops[0].is_closed()


def test_backtrader_closes_reused_event_loop_when_strategy_fails(monkeypatch):
    engine = BacktestEngine()
    monkeypatch.setattr(engine, "_load_dataframe", lambda *args, **kwargs: _df())
    FailingLoopIdentityStrategy.reset_observed_loops()

    with pytest.raises(RuntimeError, match="intentional strategy failure"):
        engine.run_strategy(
            FailingLoopIdentityStrategy,
            exchange="okx",
            symbol="BTC/USDT",
            symbols=["BTC/USDT"],
            timeframe="1m",
            initial_capital=10_000,
            commission=0.0,
            slippage=0.0,
        )

    assert len({id(loop) for loop in FailingLoopIdentityStrategy.observed_loops}) == 1
    assert all(loop.is_closed() for loop in FailingLoopIdentityStrategy.observed_loops)


def test_backtrader_closes_reused_event_loop_when_operator_cancels(monkeypatch):
    engine = BacktestEngine()
    monkeypatch.setattr(engine, "_load_dataframe", lambda *args, **kwargs: _df())
    CancellableLoopIdentityStrategy.reset_observed_loops()

    with pytest.raises(BacktestCancelled, match="用户已停止回测"):
        engine.run_strategy(
            CancellableLoopIdentityStrategy,
            exchange="okx",
            symbol="BTC/USDT",
            symbols=["BTC/USDT"],
            timeframe="1m",
            initial_capital=10_000,
            commission=0.0,
            slippage=0.0,
            cancel_check=lambda: CancellableLoopIdentityStrategy.started,
        )

    assert len({id(loop) for loop in CancellableLoopIdentityStrategy.observed_loops}) == 1
    assert all(loop.is_closed() for loop in CancellableLoopIdentityStrategy.observed_loops)


def test_backtrader_engine_supports_contract_open_and_close(monkeypatch):
    engine = BacktestEngine()
    df = _df()
    monkeypatch.setattr(engine, "_load_dataframe", lambda *args, **kwargs: df)

    report = engine.run_strategy(
        ContractRoundTripStrategy,
        exchange="okx",
        symbol="BTC/USDT:USDT",
        symbols=["BTC/USDT:USDT"],
        timeframe="1m",
        initial_capital=10_000,
        strategy_config={"market_type": "swap", "max_leverage": 5},
    )

    assert report.total_trades == 1
    assert report.trades[0]["side"] == "long"
    assert report.trades[0]["pnl_net"] > 0

    response = _backtest_report_to_response(
        report,
        strategy_id=1,
        strategy_name="[合约][1M][测试] BTC · Round Trip · 100U",
        request=BacktestRequest(
            strategy_id=1,
            start_date="2026-01-01",
            end_date="2026-01-02",
            initial_capital=10_000,
        ),
    )

    assert response.trades
    open_fill = next(trade for trade in response.trades if trade["reason"] == "open")
    assert open_fill["leverage"] == 2.0
    assert open_fill["notional_usdt"] > 0
    assert open_fill["margin"] == open_fill["notional_usdt"] / 2.0
    close_fill = next(trade for trade in response.trades if trade["reason"] == "close")
    assert close_fill["leverage"] == 2.0
    assert close_fill["notional_usdt"] > 0
    assert close_fill["margin"] == close_fill["notional_usdt"] / 2.0


def test_backtrader_engine_applies_contract_leverage_for_margin(monkeypatch):
    engine = BacktestEngine()
    df = _df()
    monkeypatch.setattr(engine, "_load_dataframe", lambda *args, **kwargs: df)

    report = engine.run_strategy(
        LeveragedLongStrategy,
        exchange="okx",
        symbol="BTC/USDT:USDT",
        symbols=["BTC/USDT:USDT"],
        timeframe="1m",
        initial_capital=100,
        strategy_config={"market_type": "swap", "leverage": 5, "max_leverage": 5},
    )

    assert report.orders[0]["side"] == "open_long"
    assert report.orders[0]["notional_usdt"] > 100
    assert report.orders[0]["margin"] == report.orders[0]["notional_usdt"] / 5
    assert report.total_trades == 1


def test_backtrader_engine_applies_contract_funding_cashflows(monkeypatch):
    engine = BacktestEngine()
    df = _df()
    funding_ts = int(df.index[2].tz_localize("Asia/Shanghai").timestamp() * 1000)
    monkeypatch.setattr(engine, "_load_dataframe", lambda *args, **kwargs: df)
    monkeypatch.setattr(
        engine,
        "_load_contract_funding_history",
        lambda *args, **kwargs: [
            {
                "timestamp": funding_ts,
                "funding_rate": 0.001,
                "mark_price": 101.0,
            }
        ],
    )

    unfunded = engine.run_strategy(
        LeveragedLongStrategy,
        exchange="okx",
        symbol="BTC/USDT:USDT",
        symbols=["BTC/USDT:USDT"],
        timeframe="1m",
        initial_capital=100,
        commission=0.0,
        slippage=0.0,
        strategy_config={"market_type": "swap", "leverage": 5, "max_leverage": 5},
    )
    funded = engine.run_strategy(
        LeveragedLongStrategy,
        exchange="okx",
        symbol="BTC/USDT:USDT",
        symbols=["BTC/USDT:USDT"],
        timeframe="1m",
        initial_capital=100,
        commission=0.0,
        slippage=0.0,
        strategy_config={
            "market_type": "swap",
            "leverage": 5,
            "max_leverage": 5,
            "include_funding_costs": True,
        },
    )

    assert funded.funding_events == 1
    assert funded.funding_fee < 0
    assert funded.final_capital < unfunded.final_capital

    response = _backtest_report_to_response(
        funded,
        strategy_id=1,
        strategy_name="[合约][1M][测试] BTC · Funding · 100U",
        request=BacktestRequest(
            strategy_id=1,
            start_date="2026-01-01",
            end_date="2026-01-02",
            initial_capital=100,
        ),
    )
    assert response.funding_events == 1
    assert response.funding_fee < 0


def test_okx_funding_history_fetch_uses_public_api_user_agent(monkeypatch):
    captured = {}
    inserted = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return (
                b'{"code":"0","data":[{"fundingTime":"5000",'
                b'"realizedRate":"0.0001","fundingRate":"0.0001"}]}'
            )

    def fake_urlopen(request, timeout=0):
        captured["user_agent"] = (
            request.get_header("User-agent") or request.get_header("User-Agent")
        )
        return FakeResponse()

    monkeypatch.setattr(BacktestEngine, "_urlopen_no_proxy", staticmethod(fake_urlopen))
    monkeypatch.setattr(
        backtrader_engine_module.db,
        "insert_funding_rate",
        lambda *args: inserted.append(args),
    )

    fetched = BacktestEngine._fetch_and_cache_okx_funding_history(
        "ETH/USDT:USDT",
        start_ms=5000,
        end_ms=6000,
    )

    assert fetched == 1
    assert captured["user_agent"].startswith("BitPro/")
    assert inserted[0][:3] == ("okx", "ETH-USDT-SWAP", 5000)


def test_okx_funding_history_fetch_tolerates_rate_limit(monkeypatch):
    inserted = []

    def fake_urlopen(_request, timeout=0):
        raise OSError("HTTP Error 429: Too Many Requests")

    monkeypatch.setattr(BacktestEngine, "_urlopen_no_proxy", staticmethod(fake_urlopen))
    monkeypatch.setattr(
        backtrader_engine_module.db,
        "insert_funding_rate",
        lambda *args: inserted.append(args),
    )

    fetched = BacktestEngine._fetch_and_cache_okx_funding_history(
        "ETH/USDT:USDT",
        start_ms=5000,
        end_ms=6000,
    )

    assert fetched == 0
    assert inserted == []


def test_backtrader_engine_smoke_runs_contract_martingale_grid(monkeypatch):
    engine = BacktestEngine()
    df = _martingale_df()
    monkeypatch.setattr(engine, "_load_dataframe", lambda *args, **kwargs: df)

    report = engine.run_strategy(
        ContractMartingaleGridStrategy,
        exchange="okx",
        symbol="BTC/USDT:USDT",
        symbols=["BTC/USDT:USDT"],
        timeframe="1m",
        initial_capital=10_000,
        strategy_config={
            "market_type": "swap",
            "target_symbol": "BTC/USDT:USDT",
            "trade_symbols": ["BTC/USDT:USDT"],
            "max_leverage": 50,
            "leverage": 50,
            "base_notional_pct": 0.01,
            "martingale_multiplier": 2,
            "max_martingale_levels": 5,
            "ema_window": 3,
            "rsi_window": 2,
            "atr_window": 2,
            "grid_atr_mult": 0,
            "min_grid_step_bps": 50,
            "max_ema_atr_deviation": 999,
            "take_profit_bps": 5,
            "min_take_profit_usdt": 0,
            "strategy_diagnostic_ws": False,
        },
    )

    assert [order["side"] for order in report.orders][:1] == ["open_long"]


def test_backtrader_engine_smoke_runs_contract_shared_martingale_grid(monkeypatch):
    engine = BacktestEngine()
    df = _martingale_df()
    monkeypatch.setattr(engine, "_load_dataframe", lambda *args, **kwargs: df)

    report = engine.run_strategy(
        ContractSharedMartingaleGridStrategy,
        exchange="okx",
        symbol="BTC/USDT:USDT",
        symbols=["BTC/USDT:USDT", "ETH/USDT:USDT"],
        timeframe="1m",
        initial_capital=10_000,
        strategy_config={
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
            "max_leverage": 50,
            "leverage": 50,
            "base_notional_pct": 0.01,
            "martingale_multiplier": 2,
            "max_martingale_levels": 5,
            "max_symbol_notional_pct": 0.31,
            "max_pool_notional_pct": 1.0,
            "max_active_baskets": 2,
            "max_total_layers": 10,
            "ema_window": 3,
            "rsi_window": 2,
            "atr_window": 2,
            "grid_atr_mult": 0,
            "min_grid_step_bps": 50,
            "max_ema_atr_deviation": 999,
            "take_profit_bps": 5,
            "min_take_profit_usdt": 0,
            "strategy_diagnostic_ws": False,
        },
    )

    assert [order["side"] for order in report.orders][:1] == ["open_long"]


def test_backtrader_broker_exposes_spot_positions_for_strategy_exits(monkeypatch):
    engine = BacktestEngine()
    monkeypatch.setattr(engine, "_load_dataframe", lambda *args, **kwargs: _df())

    report = engine.run_strategy(
        BrokerPositionAwareSpotStrategy,
        exchange="okx",
        symbol="BTC/USDT",
        symbols=["BTC/USDT"],
        timeframe="1m",
        initial_capital=10_000,
        commission=0.0,
        slippage=0.0,
    )

    assert report.total_trades == 1
    assert [order["side"] for order in report.orders] == ["buy", "sell"]
    assert report.trades[0]["pnl_net"] > 0


def test_backtest_response_includes_open_order_fills(monkeypatch):
    engine = BacktestEngine()
    monkeypatch.setattr(engine, "_load_dataframe", lambda *args, **kwargs: _df())

    report = engine.run_strategy(
        BuyAndHoldSpotStrategy,
        exchange="okx",
        symbol="BTC/USDT",
        symbols=["BTC/USDT"],
        timeframe="1m",
        initial_capital=10_000,
        commission=0.0,
        slippage=0.0,
    )
    response = _backtest_report_to_response(
        report,
        strategy_id=1,
        strategy_name="[现货] Buy Hold",
        request=BacktestRequest(
            strategy_id=1,
            start_date="2026-01-01",
            end_date="2026-01-02",
            initial_capital=10_000,
        ),
    )

    assert report.total_trades == 0
    assert response.trades
    assert response.trades[0]["side"] == "buy"
    assert response.trades[0]["reason"] == "open"
