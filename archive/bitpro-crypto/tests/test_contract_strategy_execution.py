import asyncio
import sys
from contextlib import suppress
from datetime import datetime
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BaseStrategy, BarData, OrderResult, StrategyState
from app.services.contract_paper_account import ContractInstrument
from app.services.strategy_engine import StrategyContext, StrategyEngine, StrategyStatus
import app.services.strategy_engine as strategy_engine_module
from app.services.strategy_log_store import strategy_log_store
from app.strategies.contract_ema_atr_trend_strategy import ContractEmaAtrTrendStrategy
from app.strategies.contract_ema_atr_scalp_strategy import ContractEmaAtrScalpStrategy
from app.strategies.contract_market_neutral_top5_strategy import ContractMarketNeutralTop5Strategy
from app.strategies.contract_donchian_breakout_strategy import ContractDonchianBreakoutStrategy
from app.strategies.contract_donchian_ema_adx_strategy import ContractDonchianEmaAdxStrategy
from app.strategies.contract_bbands_rsi_reversion_strategy import ContractBbandsRsiReversionStrategy
from app.strategies.contract_atr_grid_reversion_strategy import ContractAtrGridReversionStrategy
from app.strategies.contract_martingale_grid_strategy import ContractMartingaleGridStrategy
from app.strategies.contract_shared_martingale_grid_strategy import ContractSharedMartingaleGridStrategy
from app.strategies.contract_multi_factor_rotation_strategy import ContractMultiFactorRotationStrategy
from app.strategies.contract_top5_range_reversion_strategy import ContractTop5RangeReversionStrategy
from app.strategies.contract_vwap_volume_profile_strategy import ContractVwapVolumeProfileStrategy


class FakeContractBroker:
    def __init__(self, equity: float = 10_000.0):
        self.equity = equity
        self.positions = {}
        self.orders = []

    async def open_contract(self, symbol: str, side: str, notional_usdt: float, leverage=None, price=None) -> OrderResult:
        self.orders.append({"action": "open", "symbol": symbol, "side": side, "notional": notional_usdt})
        self.positions[(symbol, side)] = {"symbol": symbol, "pos_side": side, "contracts": 1.0, "notional_usdt": notional_usdt}
        return OrderResult({"status": "filled", "side": side, "notional_usdt": notional_usdt})

    async def close_contract(self, symbol: str, side: str, ratio: float = 1.0, contracts=None, price=None) -> OrderResult:
        self.orders.append({"action": "close", "symbol": symbol, "side": side, "ratio": ratio})
        self.positions.pop((symbol, side), None)
        return OrderResult({"status": "filled", "side": side, "ratio": ratio})

    async def get_contract_position(self, symbol: str, side: str):
        return self.positions.get((symbol, side))

    async def buy(self, symbol, amount, price=None, *, order_type="market"):
        return OrderResult({"status": "unused"})

    async def sell(self, symbol, amount, price=None, *, order_type="market"):
        return OrderResult({"status": "unused"})

    async def close_position(self, symbol):
        return OrderResult({"status": "unused"})


class FakeSubmittedContractBroker(FakeContractBroker):
    async def open_contract(self, symbol: str, side: str, notional_usdt: float, leverage=None, price=None) -> OrderResult:
        await super().open_contract(symbol, side, notional_usdt, leverage=leverage, price=price)
        return OrderResult({"status": "submitted", "side": side, "notional_usdt": notional_usdt})

    async def close_contract(self, symbol: str, side: str, ratio: float = 1.0, contracts=None, price=None) -> OrderResult:
        await super().close_contract(symbol, side, ratio=ratio, contracts=contracts, price=price)
        return OrderResult({"status": "submitted", "side": side, "ratio": ratio})


class FakeMartingaleContractBroker:
    def __init__(self, equity: float = 10_000.0, min_contract_notional_by_symbol: dict[str, float] | None = None):
        self.equity = equity
        self.positions = {}
        self.orders = []
        self.last_prices = {}
        self.min_contract_notional_by_symbol = min_contract_notional_by_symbol or {}

    def update_mark_price(self, symbol: str, price: float):
        self.last_prices[symbol] = float(price)

    def min_contract_notional(self, symbol: str, price: float) -> float:
        return float(self.min_contract_notional_by_symbol.get(symbol, 0.0))

    async def open_contract(self, symbol: str, side: str, notional_usdt: float, leverage=None, price=None) -> OrderResult:
        px = float(price or self.last_prices.get(symbol) or 0.0)
        assert px > 0
        key = (symbol, side)
        base_qty = float(notional_usdt) / px
        existing = self.positions.get(key)
        if existing:
            old_qty = float(existing["base_qty"])
            new_qty = old_qty + base_qty
            existing["entry_price"] = (float(existing["entry_price"]) * old_qty + px * base_qty) / new_qty
            existing["base_qty"] = new_qty
            existing["contracts"] = new_qty
            existing["leverage"] = max(float(existing.get("leverage") or 1.0), float(leverage or 1.0))
        else:
            existing = {
                "symbol": symbol,
                "pos_side": side,
                "entry_price": px,
                "base_qty": base_qty,
                "contracts": base_qty,
                "leverage": float(leverage or 1.0),
            }
            self.positions[key] = existing
        existing["mark_price"] = px
        existing["notional_usdt"] = float(existing["base_qty"]) * px
        self.orders.append(
            {
                "action": "open",
                "symbol": symbol,
                "side": side,
                "notional": float(notional_usdt),
                "leverage": leverage,
                "price": px,
            }
        )
        return OrderResult(
            {
                "status": "filled",
                "side": side,
                "notional_usdt": float(notional_usdt),
                "leverage": leverage,
                "price": px,
            }
        )

    async def close_contract(self, symbol: str, side: str, ratio: float = 1.0, contracts=None, price=None) -> OrderResult:
        px = float(price or self.last_prices.get(symbol) or 0.0)
        position = self.positions.pop((symbol, side), None)
        self.orders.append({"action": "close", "symbol": symbol, "side": side, "ratio": ratio, "price": px})
        return OrderResult({"status": "filled", "side": side, "ratio": ratio, "price": px, "position": position})

    async def get_contract_position(self, symbol: str, side: str):
        pos = self.positions.get((symbol, side))
        if not pos:
            return None
        px = float(self.last_prices.get(symbol) or pos.get("mark_price") or pos.get("entry_price"))
        direction = 1.0 if side == "long" else -1.0
        out = dict(pos)
        out["mark_price"] = px
        out["notional_usdt"] = float(out["base_qty"]) * px
        out["unrealized_pnl"] = (px - float(out["entry_price"])) * float(out["base_qty"]) * direction
        return out

    async def buy(self, symbol, amount, price=None, *, order_type="market"):
        return OrderResult({"status": "unused"})

    async def sell(self, symbol, amount, price=None, *, order_type="market"):
        return OrderResult({"status": "unused"})

    async def close_position(self, symbol):
        return OrderResult({"status": "unused"})


class DispatchStrategy(BaseStrategy):
    async def on_bar(self, bar: BarData) -> None:
        await self.open_contract(bar.symbol, "long", 250.0, leverage=3.0)


class RuntimeFeedResolverStrategy(BaseStrategy):
    resolver_calls = []

    @classmethod
    def resolve_runtime_symbols(cls, exchange_name, config):
        cls.resolver_calls.append((exchange_name, dict(config)))
        return ["ETH-USDT-SWAP", "BTC/USDT:USDT", "ETH/USDT:USDT"]

    async def on_init(self) -> None:
        self.state.positions["_init_symbols"] = list(self.state.symbols)

    async def on_bar(self, bar: BarData) -> None:
        return None


class EmptyRuntimeFeedResolverStrategy(RuntimeFeedResolverStrategy):
    @classmethod
    def resolve_runtime_symbols(cls, exchange_name, config):
        cls.resolver_calls.append((exchange_name, dict(config)))
        return []


class FailingRuntimeFeedResolverStrategy(RuntimeFeedResolverStrategy):
    @classmethod
    def resolve_runtime_symbols(cls, exchange_name, config):
        cls.resolver_calls.append((exchange_name, dict(config)))
        raise RuntimeError("public market unavailable")


class RuntimeFeedBroker:
    initial_capital = 100.0
    balance = 100.0
    equity = 100.0
    trades = []

    def summary(self) -> str:
        return "runtime-feed-broker"


async def _noop_notify(*args, **kwargs):
    return None


def test_strategy_engine_stop_persists_operator_intent_before_task_cancel(monkeypatch):
    events = []

    def fake_update_strategy_status(strategy_id, status, **kwargs):
        events.append(("db", strategy_id, status, kwargs))

    async def long_running_task():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            events.append(("task", "cancelled"))
            raise

    async def run_case():
        engine = StrategyEngine()
        task = asyncio.create_task(long_running_task())
        await asyncio.sleep(0)
        engine._tasks[110] = task
        engine._contexts[110] = StrategyContext(
            strategy_id=110,
            name="[合约][1M][马丁] BTC · ATR马丁网格 · 100U",
            exchange="okx",
            symbols=["BTC/USDT:USDT"],
            config={"is_paper_trading": True},
            status=StrategyStatus.RUNNING,
        )

        assert await engine.stop_strategy(110) is True
        assert 110 not in engine._tasks
        assert engine._contexts[110].status == StrategyStatus.STOPPED

    monkeypatch.setattr(strategy_engine_module.db, "update_strategy_status", fake_update_strategy_status)
    monkeypatch.setattr(strategy_engine_module.feishu_notifier, "notify_strategy_status", _noop_notify)

    asyncio.run(run_case())

    assert events[0] == ("db", 110, "stopped", {"clear_run_started_at": False})
    assert ("task", "cancelled") in events
    assert events.index(("db", 110, "stopped", {"clear_run_started_at": False})) < events.index(
        ("task", "cancelled")
    )


def test_strategy_engine_stop_with_clear_metrics_clears_run_started_at(monkeypatch):
    events = []

    def fake_update_strategy_status(strategy_id, status, **kwargs):
        events.append(("db", strategy_id, status, kwargs))

    async def run_case():
        engine = StrategyEngine()
        engine._contexts[111] = StrategyContext(
            strategy_id=111,
            name="[合约][1M][马丁] BTC · ATR马丁网格 · 100U",
            exchange="okx",
            symbols=["BTC/USDT:USDT"],
            config={"is_paper_trading": True},
            status=StrategyStatus.RUNNING,
        )
        assert await engine.stop_strategy(111, clear_metrics=True) is True

    monkeypatch.setattr(strategy_engine_module.db, "update_strategy_status", fake_update_strategy_status)
    monkeypatch.setattr(strategy_engine_module.db, "clear_strategy_runtime_metrics", lambda strategy_id: None)
    monkeypatch.setattr(strategy_engine_module.feishu_notifier, "notify_strategy_status", _noop_notify)

    asyncio.run(run_case())

    assert events[0] == ("db", 111, "stopped", {"clear_run_started_at": True})


def test_strategy_engine_pause_persists_operator_intent_before_task_cancel(monkeypatch):
    events = []

    def fake_update_strategy_status(strategy_id, status, **kwargs):
        events.append(("db", strategy_id, status, kwargs))

    async def long_running_task():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            events.append(("task", "cancelled"))
            raise

    async def run_case():
        engine = StrategyEngine()
        task = asyncio.create_task(long_running_task())
        await asyncio.sleep(0)
        engine._tasks[114] = task
        engine._contexts[114] = StrategyContext(
            strategy_id=114,
            name="[合约][1M][马丁] DOGE · ATR马丁网格 · 100U",
            exchange="okx",
            symbols=["DOGE/USDT:USDT"],
            config={"is_paper_trading": True},
            status=StrategyStatus.RUNNING,
        )

        assert await engine.pause_strategy(114) is True
        assert 114 not in engine._tasks
        assert engine._contexts[114].status == StrategyStatus.PAUSED

    monkeypatch.setattr(strategy_engine_module.db, "update_strategy_status", fake_update_strategy_status)
    monkeypatch.setattr(strategy_engine_module.feishu_notifier, "notify_strategy_status", _noop_notify)

    asyncio.run(run_case())

    assert events[0] == ("db", 114, "paused", {"clear_run_started_at": False})
    assert ("task", "cancelled") in events
    assert events.index(("db", 114, "paused", {"clear_run_started_at": False})) < events.index(
        ("task", "cancelled")
    )


def test_strategy_engine_shutdown_cancel_times_out_when_task_stalls():
    events = []

    async def run_case():
        release = asyncio.Event()
        stop_task = None

        async def stubborn_task():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                events.append(("task", "cancelled"))
                while not release.is_set():
                    try:
                        await asyncio.sleep(60)
                    except asyncio.CancelledError:
                        events.append(("task", "recancelled"))
                release.set()
                raise

        engine = StrategyEngine()
        engine._task_cancel_timeout_sec = 0.01
        task = asyncio.create_task(stubborn_task())
        await asyncio.sleep(0)
        engine._tasks[118] = task
        engine._contexts[118] = StrategyContext(
            strategy_id=118,
            name="[合约][1M][CTA] BTC · 停机超时测试 · 100U",
            exchange="okx",
            symbols=["BTC/USDT:USDT"],
            config={"is_paper_trading": True},
            status=StrategyStatus.RUNNING,
        )

        try:
            stop_task = asyncio.create_task(engine.stop(persist_running_in_db=True))
            await asyncio.sleep(0.05)
            assert stop_task.done()
            await stop_task
            assert 118 not in engine._tasks
            assert 118 not in engine._contexts
            assert 118 not in engine._strategy_instances
            assert engine._running is False
            assert not task.done()
            assert ("task", "cancelled") in events
        finally:
            release.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            if stop_task is not None:
                with suppress(asyncio.CancelledError):
                    await stop_task

    asyncio.run(run_case())


def make_bar(close: float, ts: int) -> BarData:
    return BarData(
        exchange="okx",
        symbol="BTC/USDT:USDT",
        timeframe="1m",
        timestamp=ts,
        open=close,
        high=close + 10,
        low=close - 10,
        close=close,
        volume=100,
    )


def make_symbol_bar(symbol: str, close: float, ts: int, volume: float = 1000.0) -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="1m",
        timestamp=ts,
        open=close,
        high=close * 1.002,
        low=close * 0.998,
        close=close,
        volume=volume,
    )


def make_flat_bar(close: float, ts: int) -> BarData:
    return BarData(
        exchange="okx",
        symbol="BTC/USDT:USDT",
        timeframe="1m",
        timestamp=ts,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=100,
    )


def make_state(name: str = "contract smoke") -> StrategyState:
    return StrategyState(
        strategy_id=999,
        name=name,
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 10_000.0},
    )


def make_contract_state(symbol: str, name: str = "contract martingale") -> StrategyState:
    return StrategyState(
        strategy_id=1001,
        name=name,
        exchange="okx",
        symbols=[symbol],
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 10_000.0},
    )


def test_ema_atr_scalp_tracks_submitted_backtest_orders_for_protective_exits():
    broker = FakeSubmittedContractBroker(equity=100.0)
    strategy = ContractEmaAtrScalpStrategy(make_state("submitted protective exits"), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_notional_usdt": 100.0,
            "trade_notional_pct": 0.0,
            "max_total_notional_pct": 0.0,
            "leverage": 5,
            "fast_window": 2,
            "slow_window": 3,
            "atr_window": 2,
            "atr_stop_mult": 2.0,
            "risk_reward_ratio": 3.0,
        }
    )
    asyncio.run(strategy.on_init())

    result = asyncio.run(strategy._open_if_flat("BTC/USDT:USDT", "long", 100.0))
    strategy._track_open("BTC/USDT:USDT", "long", 100.0, 1.5, result)

    key = ("BTC/USDT:USDT", "long")
    assert strategy._stop_price[key] == pytest.approx(97.0)
    assert strategy._take_profit_price[key] == pytest.approx(109.0)

    asyncio.run(strategy._close_and_reset("BTC/USDT:USDT", "long", 97.0))
    assert key not in strategy._stop_price
    assert key not in strategy._take_profit_price


def test_lab_vwap_stop_loss_triggers_on_intrabar_low_before_four_hour_close() -> None:
    symbol = "LAB/USDT:USDT"
    broker = FakeContractBroker(equity=100.0)
    broker.positions[(symbol, "long")] = {
        "symbol": symbol,
        "pos_side": "long",
        "contracts": 1.0,
        "entry_price": 100.0,
    }
    strategy = ContractVwapVolumeProfileStrategy(make_contract_state(symbol, "lab vwap"), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": [symbol],
            "atr_window": 2,
            "stop_buffer_atr": 1.5,
            "risk_reward_ratio": 1.6,
            "fixed_take_profit_enabled": True,
            "profit_protection_enabled": True,
        }
    )
    asyncio.run(strategy.on_init())
    key = (symbol, "long")
    strategy._stop_price[key] = 95.0
    strategy._take_profit[key] = 110.0
    strategy._entry_price[key] = 100.0
    strategy._opened_bar[key] = 1
    strategy._bar_counts[symbol] = 2
    strategy._bars[symbol] = [
        BarData(
            exchange="okx",
            symbol=symbol,
            timeframe="4h",
            timestamp=1_800_000_000_000,
            open=100.0,
            high=102.0,
            low=94.0,
            close=100.0,
            volume=1000.0,
        )
    ]

    closed = asyncio.run(strategy._manage_existing(symbol, 100.0, None))

    assert closed is True
    assert broker.positions == {}
    assert broker.orders[-1]["action"] == "close"


def test_donchian_ema_adx_opens_only_confirmed_breakout():
    broker = FakeContractBroker(equity=100.0)
    strategy = ContractDonchianEmaAdxStrategy(make_contract_state("ETH/USDT:USDT", "eth donchian"), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": ["ETH/USDT:USDT"],
            "trade_notional_pct": 1.25,
            "trade_notional_usdt": 10,
            "max_total_notional_pct": 1.25,
            "min_order_notional_usdt": 0.5,
            "leverage": 5,
            "lookback_bars": 3,
            "ema_window": 3,
            "atr_window": 2,
            "adx_window": 2,
            "min_adx": 0,
            "atr_stop_mult": 3.0,
            "take_profit_atr_mult": 0,
            "min_stop_pct": 0.01,
            "min_holding_bars": 1,
            "max_holding_bars": 30,
        }
    )
    asyncio.run(strategy.on_init())

    prices = [100, 101, 102, 106]
    for index, price in enumerate(prices):
        asyncio.run(
            strategy.on_bar(
                make_symbol_bar("ETH/USDT:USDT", float(price), 1_800_000_000_000 + index * 86_400_000)
            )
        )

    assert broker.orders[-1] == {
        "action": "open",
        "symbol": "ETH/USDT:USDT",
        "side": "long",
        "notional": pytest.approx(125.0),
    }


def test_donchian_ema_adx_closes_on_ema_soft_exit():
    broker = FakeContractBroker(equity=100.0)
    strategy = ContractDonchianEmaAdxStrategy(make_contract_state("ETH/USDT:USDT", "eth donchian"), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": ["ETH/USDT:USDT"],
            "trade_notional_pct": 1.0,
            "max_total_notional_pct": 1.0,
            "min_order_notional_usdt": 0.5,
            "lookback_bars": 3,
            "ema_window": 3,
            "atr_window": 2,
            "adx_window": 2,
            "min_adx": 0,
            "atr_stop_mult": 10.0,
            "take_profit_atr_mult": 0,
            "min_stop_pct": 0.01,
            "min_holding_bars": 1,
            "max_holding_bars": 30,
        }
    )
    asyncio.run(strategy.on_init())
    for index, price in enumerate([100, 101, 102, 106, 99, 98]):
        asyncio.run(
            strategy.on_bar(
                make_symbol_bar("ETH/USDT:USDT", float(price), 1_800_000_000_000 + index * 86_400_000)
            )
        )

    assert {"action": "close", "symbol": "ETH/USDT:USDT", "side": "long", "ratio": 1.0} in broker.orders


def test_donchian_ema_adx_resets_stale_state_for_submitted_backtest_orders():
    broker = FakeSubmittedContractBroker(equity=100.0)
    strategy = ContractDonchianEmaAdxStrategy(make_contract_state("ETH/USDT:USDT", "eth donchian"), broker)
    strategy.set_config({"market_type": "swap", "trade_notional_pct": 1.25, "max_total_notional_pct": 1.25})
    asyncio.run(strategy.on_init())

    key = ("ETH/USDT:USDT", "long")
    strategy._trail_stop[key] = 1_000.0
    strategy._entry_price[key] = 1_500.0
    strategy._opened_bar[key] = 42

    result = asyncio.run(strategy._open_if_flat("ETH/USDT:USDT", "long", 2_000.0))
    strategy._track_open("ETH/USDT:USDT", "long", 2_000.0, result)

    assert key not in strategy._trail_stop
    assert key not in strategy._entry_price
    assert key not in strategy._opened_bar

    strategy._trail_stop[key] = 1_100.0
    strategy._entry_price[key] = 2_000.0
    strategy._opened_bar[key] = 43

    asyncio.run(strategy._close_and_reset("ETH/USDT:USDT", "long", 1_980.0))

    assert key not in strategy._trail_stop
    assert key not in strategy._entry_price
    assert key not in strategy._opened_bar


def test_donchian_ema_adx_rebuilds_restored_position_state_from_open_timestamp():
    symbol = "ETH/USDT:USDT"
    broker = FakeContractBroker(equity=100.0)
    strategy = ContractDonchianEmaAdxStrategy(make_contract_state(symbol, "eth restored donchian"), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": [symbol],
            "lookback_bars": 2,
            "ema_window": 2,
            "atr_window": 1,
            "adx_window": 1,
            "min_adx": 0,
            "atr_stop_mult": 1.0,
            "take_profit_atr_mult": 0,
            "min_stop_pct": 0.0,
            "min_holding_bars": 0,
            "max_holding_bars": 99,
            "ema_soft_exit": False,
            "reversal_exit": False,
        }
    )
    asyncio.run(strategy.on_init())

    base_ts = 1_800_000_000_000
    day_ms = 86_400_000
    opened_at = base_ts + 3 * day_ms
    key = (symbol, "short")
    broker.positions[key] = {
        "symbol": symbol,
        "pos_side": "short",
        "contracts": 1.0,
        "notional_usdt": 100.0,
        "entry_price": 100.0,
        "mark_price": 100.0,
        "opened_at": opened_at,
        "opened_bar_timestamp": opened_at,
    }

    for index, price in enumerate([120.0, 118.0, 116.0]):
        asyncio.run(strategy.on_bar(make_symbol_bar(symbol, price, base_ts + index * day_ms)))

    assert key not in strategy._opened_bar
    assert key not in strategy._trail_stop

    for offset, price in enumerate([100.0, 95.0, 90.0, 85.0], start=3):
        asyncio.run(strategy.on_bar(make_symbol_bar(symbol, price, base_ts + offset * day_ms)))

    assert strategy._opened_bar[key] == 4
    assert strategy._entry_price[key] == pytest.approx(100.0)
    assert strategy._trail_stop[key] < 100.0

    trail_stop = strategy._trail_stop[key]
    asyncio.run(strategy.on_bar(make_symbol_bar(symbol, trail_stop + 0.5, base_ts + 7 * day_ms)))

    assert {"action": "close", "symbol": symbol, "side": "short", "ratio": 1.0} in broker.orders


def test_donchian_ema_adx_closes_with_shared_profit_pullback_policy():
    symbol = "ETH/USDT:USDT"
    broker = FakeContractBroker(equity=100.0)
    strategy = ContractDonchianEmaAdxStrategy(make_contract_state(symbol, "eth donchian profit pullback"), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": [symbol],
            "lookback_bars": 2,
            "ema_window": 2,
            "atr_window": 1,
            "adx_window": 1,
            "min_adx": 0,
            "atr_stop_mult": 10.0,
            "take_profit_atr_mult": 0,
            "min_stop_pct": 0.0,
            "min_holding_bars": 0,
            "max_holding_bars": 99,
            "ema_soft_exit": False,
            "reversal_exit": False,
            "profit_protection_enabled": True,
            "profit_trailing_start_r": 2.0,
            "profit_peak_pullback_pct": 0.35,
            "profit_tighten_at_r": 3.0,
            "profit_tight_pullback_pct": 0.22,
            "profit_initial_risk_pct": 0.10,
        }
    )
    asyncio.run(strategy.on_init())

    base_ts = 1_800_000_000_000
    day_ms = 86_400_000
    key = (symbol, "long")
    broker.positions[key] = {
        "symbol": symbol,
        "pos_side": "long",
        "contracts": 1.0,
        "notional_usdt": 100.0,
        "entry_price": 100.0,
        "mark_price": 100.0,
        "opened_at": base_ts,
        "opened_bar_timestamp": base_ts,
    }

    for index, price in enumerate([100.0, 115.0, 140.0]):
        asyncio.run(strategy.on_bar(make_symbol_bar(symbol, price, base_ts + index * day_ms)))
    assert key in broker.positions

    asyncio.run(strategy.on_bar(make_symbol_bar(symbol, 130.0, base_ts + 3 * day_ms)))

    assert {"action": "close", "symbol": symbol, "side": "long", "ratio": 1.0} in broker.orders
    assert key not in strategy._exit_states


def martingale_config(symbol: str, **overrides):
    cfg = {
        "market_type": "swap",
        "target_symbol": symbol,
        "trade_symbols": [symbol],
        "max_leverage": 50,
        "leverage": 50,
        "base_notional_pct": 0.01,
        "martingale_multiplier": 2,
        "max_martingale_levels": 5,
        "max_basket_notional_pct": 0.31,
        "ema_window": 3,
        "rsi_window": 2,
        "atr_window": 2,
        "grid_atr_mult": 0,
        "min_grid_step_bps": 50,
        "max_ema_atr_deviation": 999,
        "take_profit_bps": 10,
        "min_take_profit_usdt": 0,
        "max_basket_loss_equity_pct": 0.001,
        "pause_bars_after_stop": 3,
        "max_holding_bars": 240,
        "min_order_notional_usdt": 1,
        "strategy_diagnostic_ws": False,
    }
    cfg.update(overrides)
    return cfg


def shared_martingale_config(symbols, **overrides):
    cfg = martingale_config(
        symbols[0],
        target_symbol=symbols[0],
        trade_symbols=symbols,
        base_notional_pct=0.01,
        max_symbol_notional_pct=0.31,
        max_pool_notional_pct=0.50,
        max_total_notional_pct=0.50,
        max_active_baskets=3,
        max_total_layers=10,
        max_pool_loss_equity_pct=1.0,
    )
    cfg["strategy_key"] = "contract_shared_martingale_grid"
    cfg.update(overrides)
    return cfg


def run_martingale_bar(strategy: ContractMartingaleGridStrategy, broker: FakeMartingaleContractBroker, symbol: str, close: float, index: int):
    broker.update_mark_price(symbol, close)
    asyncio.run(strategy.on_bar(make_symbol_bar(symbol, close, 1_900_000_000_000 + index * 60_000)))


def run_shared_martingale_bar(
    strategy: ContractSharedMartingaleGridStrategy,
    broker: FakeMartingaleContractBroker,
    symbol: str,
    close: float,
    index: int,
):
    broker.update_mark_price(symbol, close)
    asyncio.run(strategy.on_bar(make_symbol_bar(symbol, close, 1_900_100_000_000 + index * 60_000)))


def test_base_strategy_dispatches_contract_methods_to_broker():
    broker = FakeContractBroker()
    strategy = DispatchStrategy(make_state(), broker)

    asyncio.run(strategy.on_bar(make_bar(50_000.0, 1)))

    assert broker.orders == [{"action": "open", "symbol": "BTC/USDT:USDT", "side": "long", "notional": 250.0}]


def test_contract_strategy_base_sizes_new_orders_by_equity_percent():
    broker = FakeContractBroker(equity=12_000.0)
    strategy = ContractEmaAtrTrendStrategy(make_state("equity sizing"), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_notional_usdt": 250,
            "trade_notional_pct": 0.10,
            "max_total_notional_pct": 0.35,
            "fast_window": 1,
            "slow_window": 2,
            "atr_window": 1,
        }
    )
    asyncio.run(strategy.on_init())

    result = asyncio.run(strategy._open_if_flat("BTC/USDT:USDT", "long", 100.0))

    assert result["status"] == "filled"
    assert broker.orders[-1] == {
        "action": "open",
        "symbol": "BTC/USDT:USDT",
        "side": "long",
        "notional": 1_200.0,
    }


def test_contract_strategy_base_caps_new_orders_by_total_notional_percent():
    broker = FakeContractBroker(equity=10_000.0)
    broker.positions[("ETH/USDT:USDT", "long")] = {
        "symbol": "ETH/USDT:USDT",
        "pos_side": "long",
        "contracts": 1.0,
        "notional_usdt": 3_300.0,
    }
    strategy = ContractEmaAtrTrendStrategy(make_state("equity sizing cap"), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_notional_pct": 0.10,
            "max_total_notional_pct": 0.35,
            "min_order_notional_usdt": 50,
            "fast_window": 1,
            "slow_window": 2,
            "atr_window": 1,
        }
    )
    asyncio.run(strategy.on_init())

    result = asyncio.run(strategy._open_if_flat("BTC/USDT:USDT", "long", 100.0))

    assert result["status"] == "filled"
    assert broker.orders[-1]["notional"] == 200.0


def test_contract_martingale_grid_ignores_symbols_outside_single_target():
    symbol = "BTC/USDT:USDT"
    broker = FakeMartingaleContractBroker()
    strategy = ContractMartingaleGridStrategy(make_contract_state(symbol), broker)
    strategy.set_config(martingale_config(symbol, max_basket_loss_equity_pct=1.0))
    asyncio.run(strategy.on_init())

    for index, price in enumerate([100.0, 100.0, 100.0, 99.0, 98.0]):
        run_martingale_bar(strategy, broker, "ETH/USDT:USDT", price, index)

    assert broker.orders == []


def test_contract_martingale_grid_opens_and_adds_only_five_layers():
    symbol = "BTC/USDT:USDT"
    broker = FakeMartingaleContractBroker()
    strategy = ContractMartingaleGridStrategy(make_contract_state(symbol), broker)
    strategy.set_config(martingale_config(symbol, max_basket_loss_equity_pct=1.0))
    asyncio.run(strategy.on_init())

    for index, price in enumerate([100.0, 100.0, 100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0]):
        run_martingale_bar(strategy, broker, symbol, price, index)

    opens = [order for order in broker.orders if order["action"] == "open"]
    assert [round(order["notional"], 6) for order in opens] == [100.0, 200.0, 400.0, 800.0, 1600.0]
    assert all(order["side"] == "long" for order in opens)
    assert all(order["leverage"] == 50 for order in opens)
    assert strategy._baskets["long"]["levels"] == 5


def test_contract_martingale_grid_100u_raises_every_layer_to_contract_min_notional():
    symbol = "BTC/USDT:USDT"
    broker = FakeMartingaleContractBroker(equity=100.0, min_contract_notional_by_symbol={symbol: 8.1})
    strategy = ContractMartingaleGridStrategy(make_contract_state(symbol), broker)
    strategy.set_config(
        martingale_config(
            symbol,
            min_order_notional_usdt=0.2,
            min_first_layer_notional_usdt=5.0,
        )
    )
    asyncio.run(strategy.on_init())

    for index, price in enumerate([100.0, 100.0, 100.0, 99.0, 98.0, 97.0]):
        run_martingale_bar(strategy, broker, symbol, price, index)

    opens = [order for order in broker.orders if order["action"] == "open"]
    assert [round(order["notional"], 6) for order in opens] == [8.1, 8.1, 8.1]


def test_contract_martingale_grid_closes_full_basket_on_take_profit():
    symbol = "BTC/USDT:USDT"
    broker = FakeMartingaleContractBroker()
    strategy = ContractMartingaleGridStrategy(make_contract_state(symbol), broker)
    strategy.set_config(martingale_config(symbol, take_profit_bps=5, min_take_profit_usdt=0))
    asyncio.run(strategy.on_init())

    for index, price in enumerate([100.0, 100.0, 100.0, 99.0, 99.5]):
        run_martingale_bar(strategy, broker, symbol, price, index)

    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["side"] == "long"
    assert broker.positions == {}
    assert strategy._baskets == {}


def test_contract_martingale_grid_force_closes_and_pauses_after_max_level_loss():
    symbol = "BTC/USDT:USDT"
    broker = FakeMartingaleContractBroker()
    strategy = ContractMartingaleGridStrategy(make_contract_state(symbol), broker)
    strategy.set_config(
        martingale_config(
            symbol,
            max_basket_loss_equity_pct=0.0001,
            take_profit_bps=10_000,
            min_take_profit_usdt=10_000,
        )
    )
    asyncio.run(strategy.on_init())

    for index, price in enumerate([100.0, 100.0, 100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 80.0]):
        run_martingale_bar(strategy, broker, symbol, price, index)
    order_count_after_stop = len(broker.orders)
    run_martingale_bar(strategy, broker, symbol, 79.0, 9)

    assert broker.orders[order_count_after_stop - 1]["action"] == "close"
    assert len(broker.orders) == order_count_after_stop
    assert strategy._pause_until_bar > strategy._bar_counts[symbol]


def test_contract_shared_martingale_grid_uses_shared_active_basket_cap():
    symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    broker = FakeMartingaleContractBroker()
    strategy = ContractSharedMartingaleGridStrategy(make_contract_state(symbols[0], "shared martingale"), broker)
    strategy.set_config(shared_martingale_config(symbols, max_active_baskets=1))
    asyncio.run(strategy.on_init())

    for index, price in enumerate([100.0, 100.0, 100.0, 99.0]):
        run_shared_martingale_bar(strategy, broker, symbols[0], price, index)
    for index, price in enumerate([200.0, 200.0, 200.0, 198.0], start=10):
        run_shared_martingale_bar(strategy, broker, symbols[1], price, index)

    opens = [order for order in broker.orders if order["action"] == "open"]
    assert len(opens) == 1
    assert opens[0]["symbol"] == symbols[0]
    assert strategy._active_basket_count() == 1


def test_contract_shared_martingale_grid_caps_notional_across_pool():
    symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    broker = FakeMartingaleContractBroker()
    strategy = ContractSharedMartingaleGridStrategy(make_contract_state(symbols[0], "shared martingale"), broker)
    strategy.set_config(
        shared_martingale_config(
            symbols,
            max_active_baskets=2,
            max_pool_notional_pct=0.015,
            max_total_notional_pct=0.015,
            min_order_notional_usdt=1,
        )
    )
    asyncio.run(strategy.on_init())

    for index, price in enumerate([100.0, 100.0, 100.0, 99.0]):
        run_shared_martingale_bar(strategy, broker, symbols[0], price, index)
    for index, price in enumerate([200.0, 200.0, 200.0, 198.0], start=10):
        run_shared_martingale_bar(strategy, broker, symbols[1], price, index)

    opens = [order for order in broker.orders if order["action"] == "open"]
    assert [round(order["notional"], 6) for order in opens] == [100.0, 50.0]
    assert round(strategy._current_pool_notional(), 6) <= 150.0


def test_contract_shared_martingale_grid_keeps_symbol_baskets_independent():
    symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    broker = FakeMartingaleContractBroker()
    strategy = ContractSharedMartingaleGridStrategy(make_contract_state(symbols[0], "shared martingale"), broker)
    strategy.set_config(shared_martingale_config(symbols, max_pool_notional_pct=1.0))
    asyncio.run(strategy.on_init())

    for index, price in enumerate([100.0, 100.0, 100.0, 99.0, 98.0]):
        run_shared_martingale_bar(strategy, broker, symbols[0], price, index)
    for index, price in enumerate([200.0, 200.0, 200.0, 198.0], start=10):
        run_shared_martingale_bar(strategy, broker, symbols[1], price, index)

    assert strategy._baskets[f"{symbols[0]}:long"]["levels"] == 2
    assert strategy._baskets[f"{symbols[1]}:long"]["levels"] == 1
    assert strategy._active_layer_count() == 3


def test_contract_shared_martingale_grid_100u_raises_every_layer_to_contract_min_notional():
    symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    broker = FakeMartingaleContractBroker(
        equity=100.0,
        min_contract_notional_by_symbol={symbols[0]: 7.5, symbols[1]: 5.0},
    )
    strategy = ContractSharedMartingaleGridStrategy(make_contract_state(symbols[0], "shared martingale"), broker)
    strategy.set_config(
        shared_martingale_config(
            symbols,
            base_notional_pct=0.005,
            min_order_notional_usdt=0.2,
            min_first_layer_notional_usdt=2.0,
            max_pool_notional_pct=1.0,
            max_total_notional_pct=1.0,
        )
    )
    asyncio.run(strategy.on_init())

    for index, price in enumerate([100.0, 100.0, 100.0, 99.0, 98.0, 97.0]):
        run_shared_martingale_bar(strategy, broker, symbols[0], price, index)

    opens = [order for order in broker.orders if order["action"] == "open"]
    assert [round(order["notional"], 6) for order in opens] == [7.5, 7.5, 7.5]


def test_ema_atr_short_does_not_close_immediately_when_atr_is_zero():
    broker = FakeContractBroker()
    broker.positions[("BTC/USDT:USDT", "short")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "short",
        "contracts": 1.0,
        "notional_usdt": 250.0,
    }
    strategy = ContractEmaAtrTrendStrategy(make_state("ema zero atr"), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "fast_window": 2,
            "slow_window": 3,
            "atr_window": 2,
            "atr_stop_mult": 2.5,
            "min_atr_stop_bps": 5,
        }
    )
    asyncio.run(strategy.on_init())

    for index in range(4):
        asyncio.run(strategy.on_bar(make_flat_bar(100.0, 1_800_000_000_000 + index * 60_000)))

    assert not [order for order in broker.orders if order["action"] == "close"]


def test_ema_atr_respects_min_holding_bars_before_signal_reversal_close():
    broker = FakeContractBroker()
    strategy = ContractEmaAtrTrendStrategy(make_state("ema min hold"), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_notional_usdt": 250,
            "fast_window": 1,
            "slow_window": 2,
            "atr_window": 1,
            "atr_stop_mult": 2.5,
            "min_holding_bars": 2,
            "min_atr_stop_bps": 5,
        }
    )
    asyncio.run(strategy.on_init())

    for index, price in enumerate([100.0, 99.0, 101.0]):
        asyncio.run(strategy.on_bar(make_flat_bar(price, 1_800_000_000_000 + index * 60_000)))

    assert broker.orders == [
        {"action": "open", "symbol": "BTC/USDT:USDT", "side": "short", "notional": 250.0}
    ]


def test_atr_grid_locks_profit_with_trailing_pullback():
    broker = FakeContractBroker()
    broker.positions[("BTC/USDT:USDT", "short")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "short",
        "contracts": 1.0,
        "notional_usdt": 250.0,
        "entry_price": 100.0,
    }
    strategy = ContractAtrGridReversionStrategy(make_state("atr grid profit lock"), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "atr_window": 1,
            "trailing_start_bps": 50,
            "trailing_pullback_bps": 20,
            "take_profit_bps": 1000,
            "stop_loss_bps": 1000,
            "min_holding_bars": 0,
            "max_holding_bars": 20,
        }
    )
    asyncio.run(strategy.on_init())
    strategy._anchor["BTC/USDT:USDT"] = 80.0

    asyncio.run(strategy.on_bar(make_bar(100.0, 1_800_000_000_000)))
    asyncio.run(strategy.on_bar(make_bar(99.0, 1_800_000_060_000)))
    asyncio.run(strategy.on_bar(make_bar(99.6, 1_800_000_120_000)))

    assert broker.orders[-1] == {
        "action": "close",
        "symbol": "BTC/USDT:USDT",
        "side": "short",
        "ratio": 1.0,
    }


@pytest.mark.parametrize(
    "strategy_cls,midline",
    [
        (ContractDonchianBreakoutStrategy, 120.0),
        (ContractBbandsRsiReversionStrategy, 120.0),
    ],
)
def test_channel_and_bbands_contract_strategies_have_fixed_take_profit(strategy_cls, midline):
    strategy = strategy_cls(make_state(strategy_cls.__name__), FakeContractBroker())
    strategy.set_config(
        {
            "market_type": "swap",
            "take_profit_bps": 70,
            "stop_loss_bps": 1000,
            "trailing_start_bps": 1000,
            "min_holding_bars": 0,
            "max_holding_bars": 20,
        }
    )
    asyncio.run(strategy.on_init())

    assert strategy._should_close_position(
        "BTC/USDT:USDT",
        "long",
        {"entry_price": 100.0},
        100.8,
        midline,
    )


def test_strategy_engine_uses_contract_paper_broker_for_swap_paper_context():
    engine = StrategyEngine()
    context = StrategyContext(
        strategy_id=1,
        name="swap paper",
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
        config={
            "market_type": "swap",
            "is_paper_trading": True,
            "initial_capital": 10_000,
            "contract_instruments": {
                "BTC/USDT:USDT": {
                    "inst_id": "BTC-USDT-SWAP",
                    "ct_val": 0.01,
                    "lot_sz": 1,
                    "min_sz": 1,
                    "tick_sz": 0.1,
                    "max_leverage": 5,
                    "state": "live",
                }
            },
        },
    )

    broker = engine._build_broker_for_context(context)

    assert broker.__class__.__name__ == "ContractPaperBroker"


def test_strategy_engine_loads_contract_metadata_from_trade_symbols(monkeypatch):
    captured = []

    def fake_load_contract_instruments(exchange_name, symbols, config):
        captured.extend(symbols)
        return {
            "BTC/USDT:USDT": ContractInstrument(
                symbol="BTC/USDT:USDT",
                inst_id="BTC-USDT-SWAP",
                ct_val=0.01,
                lot_sz=1,
                min_sz=1,
                tick_sz=0.1,
                max_leverage=5,
                state="live",
            )
        }

    monkeypatch.setattr(strategy_engine_module, "load_contract_instruments", fake_load_contract_instruments)
    engine = StrategyEngine()
    context = StrategyContext(
        strategy_id=10,
        name="swap with spot signal universe",
        exchange="okx",
        symbols=["BTC/USDT", "ETH/USDT"],
        config={
            "market_type": "swap",
            "is_paper_trading": True,
            "initial_capital": 10_000,
            "trade_symbols": ["BTC-SWAP"],
        },
    )

    broker = engine._build_broker_for_context(context)

    assert broker.__class__.__name__ == "ContractPaperBroker"
    assert captured == ["BTC/USDT:USDT"]


def test_contract_paper_broker_lazily_loads_full_market_symbol_metadata(monkeypatch):
    calls = []

    def fake_load_contract_instruments(exchange_name, symbols, config):
        normalized = list(symbols)
        calls.append(normalized)
        out = {}
        for symbol in normalized:
            if "ETH" in symbol:
                out["ETH/USDT:USDT"] = ContractInstrument(
                    symbol="ETH/USDT:USDT",
                    inst_id="ETH-USDT-SWAP",
                    ct_val=0.1,
                    lot_sz=1,
                    min_sz=1,
                    tick_sz=0.01,
                    max_leverage=10,
                    state="live",
                )
            else:
                out["BTC/USDT:USDT"] = ContractInstrument(
                    symbol="BTC/USDT:USDT",
                    inst_id="BTC-USDT-SWAP",
                    ct_val=0.01,
                    lot_sz=1,
                    min_sz=1,
                    tick_sz=0.1,
                    max_leverage=10,
                    state="live",
                )
        return out

    monkeypatch.setattr(strategy_engine_module, "load_contract_instruments", fake_load_contract_instruments)
    monkeypatch.setattr(
        strategy_engine_module.db,
        "insert_strategy_trade",
        lambda strategy_id, trade: None,
    )
    broker = strategy_engine_module.ContractPaperBroker(
        initial_capital=1_000,
        strategy_id=11,
        exchange_name="okx",
        symbols=["BTC/USDT:USDT"],
        config={"market_type": "swap", "is_paper_trading": True, "max_leverage": 10},
    )

    min_notional = broker.min_contract_notional("ETH/USDT:USDT", 3_000)
    result = asyncio.run(
        broker.open_contract("ETH/USDT:USDT", "short", notional_usdt=300, leverage=10, price=3_000)
    )

    assert calls == [["BTC/USDT:USDT"], ["ETH/USDT:USDT"]]
    assert min_notional == pytest.approx(300.0)
    assert result["status"] == "filled"
    assert ("ETH/USDT:USDT", "short") in broker.account.positions


def test_contract_paper_broker_applies_slippage_bps_to_contract_fills(monkeypatch):
    monkeypatch.setattr(
        strategy_engine_module.db,
        "insert_strategy_trade",
        lambda strategy_id, trade: None,
    )
    broker = strategy_engine_module.ContractPaperBroker(
        initial_capital=1_000,
        strategy_id=12,
        exchange_name="okx",
        symbols=["BTC/USDT:USDT"],
        config={
            "market_type": "swap",
            "is_paper_trading": True,
            "max_leverage": 10,
            "taker_fee_bps": 0,
            "slippage_bps": 5,
            "contract_instruments": {
                "BTC/USDT:USDT": {
                    "inst_id": "BTC-USDT-SWAP",
                    "ct_val": 1,
                    "lot_sz": 0.001,
                    "min_sz": 0.001,
                    "tick_sz": 0.001,
                    "max_leverage": 10,
                    "state": "live",
                }
            },
        },
    )

    opened_long = asyncio.run(
        broker.open_contract("BTC/USDT:USDT", "long", notional_usdt=100, leverage=5, price=100)
    )
    closed_long = asyncio.run(
        broker.close_contract("BTC/USDT:USDT", "long", ratio=1.0, price=110)
    )
    opened_short = asyncio.run(
        broker.open_contract("BTC/USDT:USDT", "short", notional_usdt=100, leverage=5, price=100)
    )
    closed_short = asyncio.run(
        broker.close_contract("BTC/USDT:USDT", "short", ratio=1.0, price=90)
    )

    assert opened_long["price"] == pytest.approx(100.05)
    assert closed_long["price"] == pytest.approx(109.945)
    assert opened_short["price"] == pytest.approx(99.95)
    assert closed_short["price"] == pytest.approx(90.045)


def test_strategy_engine_bootstraps_runtime_feed_symbols_without_trade_symbols(monkeypatch):
    RuntimeFeedResolverStrategy.resolver_calls = []
    captured_broker_symbols = []
    captured_warmup_symbols = []

    engine = StrategyEngine()
    context = StrategyContext(
        strategy_id=510,
        name="[合约] runtime feed resolver",
        exchange="okx:live-account",
        symbols=[],
        config={
            "market_type": "swap",
            "is_paper_trading": True,
            "timeframe": "15m",
            "trade_symbols": [],
        },
        status=StrategyStatus.RUNNING,
    )

    def fake_build_broker(ctx):
        captured_broker_symbols.extend(ctx.symbols)
        return RuntimeFeedBroker()

    async def fake_warmup(ctx, strategy_instance, broker, timeframe, limit, *, order_delay_sec=0.0):
        captured_warmup_symbols.extend(ctx.symbols)
        ctx.status = StrategyStatus.STOPPED

    async def fake_broadcast(*args, **kwargs):
        return None

    monkeypatch.setattr(engine, "_build_broker_for_context", fake_build_broker)
    monkeypatch.setattr(engine, "_warmup_history", fake_warmup)
    monkeypatch.setattr(engine, "_load_strategy_runtime_state", lambda strategy_id, state: None)
    monkeypatch.setattr(engine, "_persist_strategy_runtime_state", lambda strategy_id, state: None)
    monkeypatch.setattr(engine, "_broadcast_log", fake_broadcast)

    asyncio.run(engine._run_strategy_loop(context, RuntimeFeedResolverStrategy))

    expected = ["ETH/USDT:USDT", "BTC/USDT:USDT"]
    assert RuntimeFeedResolverStrategy.resolver_calls == [
        (
            "okx:live-account",
            {
                "market_type": "swap",
                "is_paper_trading": True,
                "timeframe": "15m",
                "trade_symbols": [],
            },
        )
    ]
    assert context.symbols == expected
    assert context.config["symbols"] == expected
    assert context.config["trade_symbols"] == []
    assert captured_broker_symbols == expected
    assert captured_warmup_symbols == expected
    assert engine._strategy_instances[510].state.symbols == expected
    assert engine._strategy_instances[510].state.positions["_init_symbols"] == expected


def test_strategy_engine_persists_initial_snapshot_before_history_warmup(monkeypatch):
    engine = StrategyEngine()
    events = []
    context = StrategyContext(
        strategy_id=512,
        name="[合约][15M][CTA] Top60 · 动态池初始化快照 · 100U",
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
        config={"is_paper_trading": True, "timeframe": "15m"},
        status=StrategyStatus.RUNNING,
    )

    async def fake_warmup(ctx, strategy_instance, broker, timeframe, limit, *, order_delay_sec=0.0):
        events.append(("warmup", "_init_symbols" in strategy_instance.state.positions))
        ctx.status = StrategyStatus.STOPPED

    async def fake_broadcast(*args, **kwargs):
        return None

    def fake_persist(strategy_id, state):
        events.append(("persist", "_init_symbols" in state.positions))

    monkeypatch.setattr(engine, "_build_broker_for_context", lambda ctx: RuntimeFeedBroker())
    monkeypatch.setattr(engine, "_warmup_history", fake_warmup)
    monkeypatch.setattr(engine, "_load_strategy_runtime_state", lambda strategy_id, state: None)
    monkeypatch.setattr(engine, "_persist_strategy_runtime_state", fake_persist)
    monkeypatch.setattr(engine, "_broadcast_log", fake_broadcast)

    asyncio.run(engine._run_strategy_loop(context, RuntimeFeedResolverStrategy))

    assert events[:2] == [("persist", True), ("warmup", True)]


@pytest.mark.parametrize(
    ("strategy_cls", "expected_message"),
    [
        (EmptyRuntimeFeedResolverStrategy, "runtime symbols 解析为空"),
        (FailingRuntimeFeedResolverStrategy, "runtime symbols 解析失败"),
    ],
)
def test_strategy_engine_errors_when_runtime_symbols_cannot_bootstrap(monkeypatch, strategy_cls, expected_message):
    strategy_cls.resolver_calls = []
    broker_builds = []
    warmup_calls = []
    status_updates = []

    engine = StrategyEngine()
    context = StrategyContext(
        strategy_id=511,
        name="[合约] runtime feed resolver failure",
        exchange="okx:live-account",
        symbols=[],
        config={
            "market_type": "swap",
            "is_paper_trading": True,
            "timeframe": "15m",
            "trade_symbols": [],
        },
        status=StrategyStatus.RUNNING,
    )

    def fake_build_broker(ctx):
        broker_builds.append(ctx)
        raise AssertionError("broker must not be built when runtime symbols cannot bootstrap")

    async def fake_warmup(*args, **kwargs):
        warmup_calls.append((args, kwargs))

    async def fake_broadcast(*args, **kwargs):
        return None

    def fake_update_strategy_status(strategy_id, status, **kwargs):
        status_updates.append((strategy_id, status, kwargs))

    monkeypatch.setattr(engine, "_build_broker_for_context", fake_build_broker)
    monkeypatch.setattr(engine, "_warmup_history", fake_warmup)
    monkeypatch.setattr(engine, "_broadcast_log", fake_broadcast)
    monkeypatch.setattr(strategy_engine_module.db, "update_strategy_status", fake_update_strategy_status)

    asyncio.run(engine._run_strategy_loop(context, strategy_cls))

    assert strategy_cls.resolver_calls == [
        (
            "okx:live-account",
            {
                "market_type": "swap",
                "is_paper_trading": True,
                "timeframe": "15m",
                "trade_symbols": [],
            },
        )
    ]
    assert context.status == StrategyStatus.ERROR
    assert expected_message in (context.error_message or "")
    assert context.symbols == []
    assert broker_builds == []
    assert warmup_calls == []
    assert 511 not in engine._strategy_instances
    assert status_updates == [(511, "error", {})]


def test_strategy_engine_normalizes_autonomous_runtime_symbols_on_load(monkeypatch):
    def fake_get_strategy_by_id(strategy_id):
        assert strategy_id == 43
        return {
            "name": "[合约] AI自主交易员 · 模拟盘",
            "exchange": "okx",
            "symbols": ["BTC-SWAP"],
            "config": {
                "strategy_key": "ai_autonomous_trader",
                "market_type": "swap",
                "is_paper_trading": True,
                "contract_trade_symbols": ["BTC-SWAP", "ETH"],
            },
        }

    monkeypatch.setattr(strategy_engine_module.db, "get_strategy_by_id", fake_get_strategy_by_id)
    engine = StrategyEngine()

    context = asyncio.run(engine.load_strategy(43))

    assert context is not None
    assert context.symbols == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert context.config["symbols"] == context.symbols
    assert context.config["trade_symbols"] == context.symbols
    assert context.config["contract_trade_symbols"] == context.symbols


def test_strategy_engine_restores_persisted_strategy_runtime_state(monkeypatch):
    monkeypatch.setattr(
        strategy_engine_module.db,
        "get_app_setting",
        lambda key, default=None: (
            '{"_cta_risk_state":{"BTC/USDT:USDT|long":{"entry_price":100,"highest_price":120}}}'
            if key == "strategy_runtime_state:77"
            else default
        ),
    )
    state = StrategyState(strategy_id=77, name="[合约] test", exchange="okx", symbols=["BTC/USDT:USDT"])
    state.positions["_capital"] = 10_000.0

    StrategyEngine()._load_strategy_runtime_state(77, state)

    assert state.positions["_capital"] == 10_000.0
    assert state.positions["_cta_risk_state"]["BTC/USDT:USDT|long"]["highest_price"] == 120


def test_strategy_engine_persists_only_strategy_runtime_state(monkeypatch):
    saved = {}

    def fake_set_app_setting(key, value):
        saved[key] = value

    monkeypatch.setattr(strategy_engine_module.db, "set_app_setting", fake_set_app_setting)
    state = StrategyState(strategy_id=78, name="[合约] test", exchange="okx", symbols=["BTC/USDT:USDT"])
    state.positions["_capital"] = 10_000.0
    state.positions["BTC/USDT:USDT"] = 1.0
    state.positions["_cta_risk_state"] = {
        "BTC/USDT:USDT|long": {"entry_price": 100, "highest_price": 120}
    }

    StrategyEngine()._persist_strategy_runtime_state(78, state)

    assert saved == {
        "strategy_runtime_state:78": '{"_cta_risk_state":{"BTC/USDT:USDT|long":{"entry_price":100,"highest_price":120}}}'
    }


def test_contract_paper_broker_persists_liquidation_trade_with_notional(monkeypatch):
    inserted = []
    monkeypatch.setattr(
        strategy_engine_module.db,
        "insert_strategy_trade",
        lambda strategy_id, trade: inserted.append((strategy_id, trade)),
    )
    broker = strategy_engine_module.ContractPaperBroker(
        initial_capital=10_000,
        strategy_id=88,
        exchange_name="okx",
        symbols=["BTC/USDT:USDT"],
        config={
            "contract_instruments": {
                "BTC/USDT:USDT": {
                    "inst_id": "BTC-USDT-SWAP",
                    "ct_val": 0.01,
                    "lot_sz": 1,
                    "min_sz": 1,
                    "tick_sz": 0.1,
                    "max_leverage": 5,
                    "state": "live",
                }
            },
            "maintenance_margin_rate": 0.005,
            "taker_fee_bps": 0,
            "max_leverage": 5,
        },
    )
    broker.update_mark_price("BTC/USDT:USDT", 50_000)
    asyncio.run(broker.open_contract("BTC/USDT:USDT", "long", notional_usdt=1_000, leverage=5))

    events = broker.update_mark_price("BTC/USDT:USDT", 40_000)

    assert len(events) == 1
    assert inserted[-1][0] == 88
    trade = inserted[-1][1]
    assert trade["side"] == "liquidation_long"
    assert trade["price"] == pytest.approx(40_000)
    assert trade["quantity"] == pytest.approx(2)
    assert trade["pnl"] < 0
    meta = trade["meta"]
    assert meta["notional_usdt"] == pytest.approx(800.0)
    assert meta["margin"] == pytest.approx(200.0)
    assert meta["leverage"] == pytest.approx(5.0)
    assert meta["liquidation_price"] == pytest.approx(40_201.005, rel=1e-5)


def test_strategy_engine_records_liquidation_event_and_alerts(monkeypatch):
    status_updates = []
    sent_alerts = []
    broadcasts = []
    strategy_log_store.clear(89)

    monkeypatch.setattr(
        strategy_engine_module.db,
        "update_strategy_status",
        lambda strategy_id, status, **kwargs: status_updates.append((strategy_id, status, kwargs)),
    )

    async def fake_notify(report):
        sent_alerts.append(report)
        return True

    async def fake_broadcast(channel, exchange, strategy_id, payload):
        broadcasts.append((channel, exchange, strategy_id, payload))

    monkeypatch.setattr(strategy_engine_module.feishu_notifier, "notify_paper_liquidation", fake_notify)
    monkeypatch.setattr(strategy_engine_module.connection_manager, "broadcast", fake_broadcast)

    context = StrategyContext(
        strategy_id=89,
        name="[合约][15M][CTA] BTC · 测试爆仓 · 100U",
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
        config={"is_paper_trading": True, "market_type": "swap"},
        status=StrategyStatus.RUNNING,
    )
    event = {
        "type": "liquidation",
        "symbol": "BTC/USDT:USDT",
        "pos_side": "long",
        "price": 40_000,
        "liquidation_price": 40_201.005,
        "contracts": 2,
        "leverage": 5,
        "realized_pnl": -200,
        "account_equity_before": 9_800,
        "maintenance_margin": 4,
    }

    handled = asyncio.run(StrategyEngine()._handle_contract_liquidation_events(context, [event]))

    assert handled is True
    assert context.status == StrategyStatus.PAUSED
    assert status_updates == [(89, "paused", {"clear_run_started_at": False})]
    assert sent_alerts[0]["strategy_id"] == 89
    assert sent_alerts[0]["symbol"] == "BTC/USDT:USDT"
    assert sent_alerts[0]["pos_side"] == "long"
    assert sent_alerts[0]["price"] == 40_000
    stored = strategy_log_store.get(89, 5)
    assert stored[0]["type"] == "liquidation"
    assert "合约模拟盘爆仓" in stored[0]["message"]
    assert broadcasts[0][0] == "strategy"
    assert broadcasts[0][3]["type"] == "liquidation"


def test_strategy_engine_builds_real_money_contract_broker():
    engine = StrategyEngine()
    context = StrategyContext(
        strategy_id=2,
        name="swap live",
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
        config={
            "market_type": "swap",
            "is_paper_trading": False,
            "contract_instruments": {
                "BTC/USDT:USDT": {
                    "inst_id": "BTC-USDT-SWAP",
                    "ct_val": 0.01,
                    "lot_sz": 1,
                    "min_sz": 1,
                    "tick_sz": 0.1,
                    "max_leverage": 5,
                    "state": "live",
                }
            },
        },
    )

    broker = engine._build_broker_for_context(context)

    assert broker.__class__.__name__ == "LiveContractBroker"


@pytest.mark.parametrize(
    "strategy_cls,prices",
    [
        (ContractEmaAtrTrendStrategy, [100, 101, 102, 103, 104, 105, 106]),
        (ContractDonchianBreakoutStrategy, [100, 101, 102, 103, 104, 108, 109]),
        (ContractDonchianEmaAdxStrategy, [100, 101, 102, 103, 150, 170, 190]),
        (ContractBbandsRsiReversionStrategy, [100, 100, 100, 100, 90, 91, 92]),
        (ContractAtrGridReversionStrategy, [100, 101, 99, 102, 98, 103, 97]),
        (ContractMultiFactorRotationStrategy, [100, 101, 102, 103, 104, 106, 108, 111, 114]),
        (ContractTop5RangeReversionStrategy, [100, 100, 100, 100, 80, 79, 78]),
    ],
)
def test_builtin_contract_strategies_smoke_open_orders(strategy_cls, prices):
    broker = FakeContractBroker()
    strategy = strategy_cls(make_state(strategy_cls.__name__), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_notional_usdt": 250,
            "max_leverage": 5,
            "fast_window": 2,
            "slow_window": 4,
            "atr_window": 3,
            "lookback_bars": 4,
            "bb_window": 4,
            "rsi_window": 3,
            "grid_step_atr": 0.2,
            "momentum_window": 2,
            "donchian_window": 3,
            "volume_window": 3,
            "adx_window": 2,
            "ema_fast_window": 2,
            "ema_slow_window": 4,
            "entry_score_bps": 5,
            "entry_edge_bps": 5,
            "ema_window": 4,
            "min_adx": 0,
            "min_edge_bps": 1,
            "max_atr_bps": 5000,
            "max_band_width_bps": 5000,
            "max_trend_spread_bps": 5000,
            "max_adx": 100,
            "min_ranked_symbols": 1,
            "top_k": 1,
            "min_bar_quote_volume_usdt": 0,
        }
    )
    asyncio.run(strategy.on_init())

    for index, price in enumerate(prices):
        asyncio.run(strategy.on_bar(make_bar(float(price), 1_800_000_000_000 + index * 60_000)))

    assert any(order["action"] == "open" for order in broker.orders)


def test_contract_market_neutral_top5_opens_balanced_long_short_pair():
    symbols = [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
        "XRP/USDT:USDT",
        "DOGE/USDT:USDT",
    ]
    broker = FakeContractBroker()
    state = make_state("market neutral")
    state.symbols = symbols
    strategy = ContractMarketNeutralTop5Strategy(state, broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": symbols,
            "trade_notional_usdt": 250,
            "trade_notional_pct": 0.05,
            "max_total_notional_pct": 0.30,
            "max_leverage": 5,
            "leverage": 2,
            "fast_momentum_window": 2,
            "slow_momentum_window": 4,
            "ema_fast_window": 2,
            "ema_slow_window": 4,
            "rsi_window": 3,
            "atr_window": 2,
            "volume_window": 3,
            "min_atr_bps": 1,
            "max_atr_bps": 1000,
            "min_bar_quote_volume_usdt": 0,
            "min_abs_score_bps": 1,
            "min_pair_spread_bps": 2,
            "rebalance_interval_bars": 1,
            "stop_loss_bps": 10000,
            "take_profit_bps": 10000,
            "trailing_start_bps": 10000,
            "max_holding_bars": 10000,
            "strategy_diagnostic_ws": False,
        }
    )
    asyncio.run(strategy.on_init())
    series = {
        "BTC/USDT:USDT": [100, 101, 102, 103, 106, 109],
        "ETH/USDT:USDT": [100, 100.5, 101, 101.5, 102, 102.5],
        "SOL/USDT:USDT": [100, 100, 100, 100, 100, 100],
        "XRP/USDT:USDT": [100, 99.5, 99, 98.5, 98, 97.5],
        "DOGE/USDT:USDT": [100, 99, 98, 97, 94, 91],
    }

    for index in range(6):
        ts = 1_800_000_000_000 + index * 60_000
        for symbol in symbols:
            asyncio.run(strategy.on_bar(make_symbol_bar(symbol, float(series[symbol][index]), ts)))

    open_orders = [order for order in broker.orders if order["action"] == "open"]
    assert {order["side"] for order in open_orders} == {"long", "short"}
    assert broker.positions[("BTC/USDT:USDT", "long")]
    assert broker.positions[("DOGE/USDT:USDT", "short")]


def test_contract_top5_range_reversion_single_signal_can_open_by_default():
    broker = FakeContractBroker()
    strategy = ContractTop5RangeReversionStrategy(make_state("top5 single signal"), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_notional_usdt": 250,
            "max_leverage": 5,
            "bb_window": 4,
            "rsi_window": 3,
            "atr_window": 3,
            "volume_window": 3,
            "adx_window": 2,
            "ema_fast_window": 2,
            "ema_slow_window": 4,
            "entry_edge_bps": 5,
            "min_edge_bps": 1,
            "max_atr_bps": 5000,
            "max_band_width_bps": 5000,
            "max_trend_spread_bps": 5000,
            "max_adx": 100,
            "top_k": 1,
            "min_bar_quote_volume_usdt": 0,
            "strategy_diagnostic_ws": False,
        }
    )
    asyncio.run(strategy.on_init())

    for index, price in enumerate([100, 100, 100, 100, 80, 79, 78]):
        asyncio.run(strategy.on_bar(make_bar(float(price), 1_800_000_000_000 + index * 60_000)))

    assert any(order["action"] == "open" for order in broker.orders)


def test_contract_top5_range_reversion_explains_rank_gate_skip():
    broker = FakeContractBroker()
    strategy = ContractTop5RangeReversionStrategy(make_state("top5 rank diagnostic"), broker)
    captured = []

    async def capture(payload):
        captured.append(payload)

    strategy.broadcast_strategy_channel = capture
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_notional_usdt": 250,
            "max_leverage": 5,
            "bb_window": 4,
            "rsi_window": 3,
            "atr_window": 3,
            "volume_window": 3,
            "adx_window": 2,
            "ema_fast_window": 2,
            "ema_slow_window": 4,
            "entry_edge_bps": 5,
            "min_edge_bps": 1,
            "max_atr_bps": 5000,
            "max_band_width_bps": 5000,
            "max_trend_spread_bps": 5000,
            "max_adx": 100,
            "min_ranked_symbols": 2,
            "top_k": 1,
            "min_bar_quote_volume_usdt": 0,
            "strategy_diagnostic_ws": True,
            "strategy_diagnostic_every_n_bars": 1,
        }
    )
    asyncio.run(strategy.on_init())

    for index, price in enumerate([100, 100, 100, 100, 80, 79, 78]):
        asyncio.run(strategy.on_bar(make_bar(float(price), 1_800_000_000_000 + index * 60_000)))

    assert not broker.orders
    assert any(event["decision"] == "skip_not_enough_ranked" for event in captured)
