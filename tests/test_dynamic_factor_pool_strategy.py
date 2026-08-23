import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState  # noqa: E402
from app.strategies.dynamic_factor_pool import (  # noqa: E402
    DynamicFactorPoolSelector,
    DynamicFactorPoolCtaStrategy,
    FactorPoolConfig,
    FactorPoolMetrics,
    compute_factor_pool_metrics,
)


def qualifying_metrics(**overrides) -> FactorPoolMetrics:
    values = {
        "atr_pct": 1.60,
        "efficiency_ratio": 0.08,
        "ema_gap_atr": 0.70,
        "price_ema_cross_count": 10,
        "ema_flip_count": 5,
        "adx": 22.0,
    }
    values.update(overrides)
    return FactorPoolMetrics(**values)


class _ContractBroker:
    def __init__(self):
        self.equity = 100.0
        self.positions = {}
        self.orders = []
        self.warmup_mode = False

    async def open_contract(self, symbol, side, notional_usdt, leverage=None, price=None):
        self.orders.append({"action": "open", "symbol": symbol, "side": side})
        return OrderResult({"status": "filled", "side": side, "price": price})

    async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
        self.orders.append({"action": "close", "symbol": symbol, "side": side})
        self.positions.pop((symbol, side), None)
        return OrderResult({"status": "filled", "side": side, "price": price})

    async def get_contract_position(self, symbol, side):
        return self.positions.get((symbol, side))


def _init_dynamic_strategy(config=None):
    symbol = "AMD/USDT:USDT"
    broker = _ContractBroker()
    state = StrategyState(
        strategy_id=2001,
        name="[合约][1H][CTA] TradFi半导体 · EMA5/20趋势跟踪动态池版 · 100U",
        exchange="okx",
        symbols=[symbol],
        created_at=datetime.now(timezone.utc),
        status="running",
        positions={"_capital": 100.0},
    )
    strategy = DynamicFactorPoolCtaStrategy(state, broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": [symbol],
            "trend_filter": "ema_state",
            "fast_window": 2,
            "slow_window": 3,
            "entry_signal_confirm_bars": 1,
            "atr_window": 2,
            "atr_stop_mult": 20.0,
            "min_atr_ratio": 0.0,
            "market_sma_window": 2,
            "entry_min_adx": 0,
            "profit_protection_enabled": False,
            "hard_stop_loss_pct": 0,
            "hard_take_profit_pct": 0,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy, broker


def _bar(close: float, index: int) -> BarData:
    return BarData(
        exchange="okx",
        symbol="AMD/USDT:USDT",
        timeframe="1h",
        timestamp=1_800_000_000_000 + index * 3_600_000,
        open=close,
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        volume=1_000.0,
    )


def test_factor_pool_activates_only_after_two_complete_qualifying_evaluations():
    selector = DynamicFactorPoolSelector(FactorPoolConfig())

    first = selector.update("AMD/USDT:USDT", qualifying_metrics())
    second = selector.update("AMD/USDT:USDT", qualifying_metrics())

    assert first.member is False
    assert first.openable is False
    assert first.enter_streak == 1
    assert second.member is True
    assert second.openable is True
    assert second.enter_streak == 0
    assert second.reasons == ()


def test_factor_pool_uses_gap_hysteresis_and_blocks_on_first_hard_reject():
    selector = DynamicFactorPoolSelector(FactorPoolConfig())
    selector.update("AMD/USDT:USDT", qualifying_metrics())
    selector.update("AMD/USDT:USDT", qualifying_metrics())

    gray_zone = selector.update("AMD/USDT:USDT", qualifying_metrics(ema_gap_atr=0.58))
    first_reject = selector.update("AMD/USDT:USDT", qualifying_metrics(ema_gap_atr=0.51))
    second_reject = selector.update("AMD/USDT:USDT", qualifying_metrics(ema_gap_atr=0.51))

    assert gray_zone.member is True
    assert gray_zone.openable is True
    assert first_reject.member is True
    assert first_reject.openable is False
    assert first_reject.exit_streak == 1
    assert first_reject.reasons == ("ema_gap_atr_below_exit",)
    assert second_reject.member is False
    assert second_reject.openable is False
    assert second_reject.exit_streak == 0


def test_dynamic_pool_gates_new_entries_before_the_original_cta_signal():
    strategy, _ = _init_dynamic_strategy()
    bars = [_bar(100.0, 0), _bar(101.0, 1), _bar(102.0, 2), _bar(103.0, 3)]

    assert strategy._entry_signal("AMD/USDT:USDT", bars, 1) == 0

    strategy._factor_pool_selector.update("AMD/USDT:USDT", qualifying_metrics())
    strategy._factor_pool_selector.update("AMD/USDT:USDT", qualifying_metrics())

    assert strategy._entry_signal("AMD/USDT:USDT", bars, 1) == 1


def test_dynamic_pool_rejection_does_not_force_close_an_existing_position():
    strategy, broker = _init_dynamic_strategy()
    broker.positions[("AMD/USDT:USDT", "long")] = {
        "symbol": "AMD/USDT:USDT",
        "pos_side": "long",
        "contracts": 1.0,
        "base_qty": 1.0,
        "entry_price": 100.0,
        "mark_price": 100.0,
        "notional_usdt": 100.0,
    }
    strategy._factor_pool_selector.update("AMD/USDT:USDT", qualifying_metrics())
    strategy._factor_pool_selector.update("AMD/USDT:USDT", qualifying_metrics())
    strategy._factor_pool_selector.update(
        "AMD/USDT:USDT",
        qualifying_metrics(price_ema_cross_count=13),
    )
    rejected = strategy._factor_pool_selector.update(
        "AMD/USDT:USDT",
        qualifying_metrics(price_ema_cross_count=13),
    )
    assert rejected.member is False

    for index, close in enumerate([100.0, 101.0, 102.0, 103.0]):
        asyncio.run(strategy.on_bar(_bar(close, index)))

    assert ("AMD/USDT:USDT", "long") in broker.positions
    assert [order for order in broker.orders if order["action"] == "close"] == []


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"atr_pct": 1.49}, "atr_pct_below_entry"),
        ({"efficiency_ratio": 0.049}, "efficiency_below_entry"),
        ({"price_ema_cross_count": 13}, "price_ema_crosses_above_exit"),
        ({"ema_flip_count": 8}, "ema_flips_above_exit"),
        ({"adx": 17.9}, "adx_below_entry"),
    ],
)
def test_factor_pool_blocks_new_entries_at_each_boundary_without_forcing_membership_loss(overrides, reason):
    selector = DynamicFactorPoolSelector(FactorPoolConfig())
    selector.update("AMD/USDT:USDT", qualifying_metrics())
    selector.update("AMD/USDT:USDT", qualifying_metrics())

    evaluation = selector.update("AMD/USDT:USDT", qualifying_metrics(**overrides))

    assert evaluation.member is True
    assert evaluation.openable is False
    assert reason in evaluation.reasons


def test_factor_pool_metrics_share_factorlab_kernels_and_need_119_confirmed_bars():
    bars = []
    for index in range(119):
        close = 100.0 + index
        bars.append(
            {
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000.0,
            }
        )

    assert compute_factor_pool_metrics(bars[:-1], FactorPoolConfig()) is None

    metrics = compute_factor_pool_metrics(bars, FactorPoolConfig())

    assert metrics is not None
    assert metrics.efficiency_ratio == pytest.approx(1.0)
    assert metrics.ema_gap_atr > 0
    assert metrics.price_ema_cross_count == 0
    assert metrics.ema_flip_count == 0
    assert metrics.adx == pytest.approx(100.0)


def test_semiconductor_dynamic_pool_seed_is_a_new_paper_strategy_and_preserves_original():
    from app.services.strategy_registry import resolve_unified_base_strategy_class

    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    by_key = {entry["strategy_key"]: entry for entry in entries}

    original = by_key["cta_trend_following_tradfi_ai_semis_1h_100u"]
    dynamic = by_key["cta_trend_following_tradfi_semis_dynamic_factor_pool_1h_100u"]
    original_cfg = original["config"]
    dynamic_cfg = dynamic["config"]

    assert original["name"] == "[合约][1H][CTA] TradFi半导体 · EMA5/20趋势跟踪激进版 · 100U"
    assert original_cfg["module_path"] == "app.strategies.cta_trend_following_strategy"
    assert original_cfg["class_name"] == "CtaTrendFollowingStrategy"
    assert original_cfg["min_atr_ratio"] == 0.0015

    assert dynamic["name"] == "[合约][1H][CTA] TradFi半导体 · EMA5/20趋势跟踪动态池版 · 100U"
    assert dynamic_cfg["module_path"] == "app.strategies.dynamic_factor_pool"
    assert dynamic_cfg["class_name"] == "DynamicFactorPoolCtaStrategy"
    assert dynamic_cfg["is_paper_trading"] is True
    assert dynamic_cfg["timeframe"] == "1h"
    assert dynamic_cfg["pool_atr_window"] == 14
    assert dynamic_cfg["pool_min_atr_pct"] == 1.5
    assert dynamic_cfg["pool_min_efficiency_ratio"] == 0.05
    assert dynamic_cfg["pool_enter_min_ema_gap_atr"] == 0.62
    assert dynamic_cfg["pool_exit_min_ema_gap_atr"] == 0.52
    assert dynamic_cfg["pool_enter_max_price_ema_crosses"] == 12
    assert dynamic_cfg["pool_exit_min_price_ema_crosses"] == 13
    assert dynamic_cfg["pool_exit_min_ema_flips"] == 8
    assert dynamic_cfg["pool_min_adx"] == 18
    assert dynamic_cfg["hard_stop_loss_pct"] > 0
    assert dynamic_cfg["hard_take_profit_pct"] > 0
    assert dynamic["symbols"] == original["symbols"]
    assert dynamic_cfg["trade_symbols"] == original_cfg["trade_symbols"]

    resolved = resolve_unified_base_strategy_class(dynamic)
    assert resolved is not None
    assert resolved[0] is DynamicFactorPoolCtaStrategy
