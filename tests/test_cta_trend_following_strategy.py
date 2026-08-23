import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState
from app.services.risk_manager import PositionInfo, RiskCheckResult, RiskLevel
from app.strategies.contract_common import atr
from app.strategies.cta_trend_following_strategy import CtaTrendFollowingStrategy


class FakeContractBroker:
    def __init__(self, equity: float = 10_000.0):
        self.equity = equity
        self.positions = {}
        self.orders = []
        self.warmup_mode = False

    async def open_contract(self, symbol: str, side: str, notional_usdt: float, leverage=None, price=None) -> OrderResult:
        self.orders.append(
            {
                "action": "open",
                "symbol": symbol,
                "side": side,
                "notional": notional_usdt,
                "leverage": leverage,
                "price": price,
            }
        )
        self.positions[(symbol, side)] = {
            "symbol": symbol,
            "pos_side": side,
            "contracts": 1.0,
            "base_qty": notional_usdt / price if price else 0.0,
            "entry_price": price,
            "mark_price": price,
            "notional_usdt": notional_usdt,
        }
        return OrderResult({"status": "filled", "side": side, "notional_usdt": notional_usdt, "price": price})

    async def close_contract(self, symbol: str, side: str, ratio: float = 1.0, contracts=None, price=None) -> OrderResult:
        self.orders.append({"action": "close", "symbol": symbol, "side": side, "ratio": ratio, "price": price})
        self.positions.pop((symbol, side), None)
        return OrderResult({"status": "filled", "side": side, "ratio": ratio, "price": price})

    async def get_contract_position(self, symbol: str, side: str):
        return self.positions.get((symbol, side))


def make_state(symbols=None) -> StrategyState:
    return StrategyState(
        strategy_id=1001,
        name="[合约] CTA test",
        exchange="okx",
        symbols=symbols or ["BTC/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 10_000.0},
    )


def make_bar(
    symbol: str,
    close: float,
    index: int,
    spread: float = 1.0,
    timeframe: str = "4h",
    interval_ms: int = 14_400_000,
    timestamp_ms: int | None = None,
) -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp_ms if timestamp_ms is not None else 1_800_000_000_000 + index * interval_ms,
        open=close,
        high=close + spread,
        low=close - spread,
        close=close,
        volume=1000.0,
    )


def init_strategy(config, symbols=None, broker=None) -> tuple[CtaTrendFollowingStrategy, FakeContractBroker]:
    broker = broker or FakeContractBroker()
    strategy = CtaTrendFollowingStrategy(make_state(symbols), broker)
    strategy.set_config(config)
    asyncio.run(strategy.on_init())
    return strategy, broker


def utc_ms(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)


def test_cta_risk_drawdown_block_warning_is_throttled(caplog, monkeypatch):
    strategy, _ = init_strategy(
        {
            "market_type": "swap",
            "min_order_notional_usdt": 1.0,
            "min_atr_ratio": 0.0,
        }
    )
    blocked = RiskCheckResult(
        approved=False,
        risk_level=RiskLevel.CIRCUIT_BREAKER,
        reasons=["熔断触发: 最大回撤达到上限"],
    )
    monkeypatch.setattr(strategy.risk_manager, "check_account_drawdown", lambda equity: blocked)

    with caplog.at_level("WARNING", logger="app.strategies.cta_trend_following_strategy"):
        for _ in range(20):
            assert strategy._risk_sized_notional("BTC/USDT:USDT", "long", 100.0, 2.0) == 0.0

    records = [record for record in caplog.records if "CTA risk check blocked order" in record.message]
    assert len(records) == 1


def bars_ending_at(
    symbol: str,
    values: list[float],
    last_timestamp_ms: int,
    *,
    timeframe: str = "15m",
    interval_ms: int = 900_000,
    spread: float = 1.0,
) -> list[BarData]:
    first_timestamp = last_timestamp_ms - (len(values) - 1) * interval_ms
    return [
        make_bar(
            symbol,
            close,
            index,
            spread=spread,
            timeframe=timeframe,
            interval_ms=interval_ms,
            timestamp_ms=first_timestamp + index * interval_ms,
        )
        for index, close in enumerate(values)
    ]


def us_semis_session_config() -> dict:
    return {
        "session_filter_enabled": True,
        "session_timezone": "America/New_York",
        "signal_sessions": [
            {
                "name": "us_premarket_core",
                "start": "07:00",
                "end": "09:25",
                "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                "entry_size_mult": 0.5,
            },
            {
                "name": "us_regular_core",
                "start": "09:45",
                "end": "15:45",
                "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                "entry_size_mult": 1.0,
            },
        ],
        "observe_sessions": [
            {
                "name": "us_early_premarket_observe",
                "start": "04:00",
                "end": "07:00",
                "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                "entry_enabled": False,
            }
        ],
    }


def session_filtered_entry_config() -> dict:
    return {
        "market_type": "swap",
        "trade_symbols": ["NVDA/USDT:USDT"],
        "trend_filter": "ema_cross",
        "fast_window": 2,
        "slow_window": 3,
        "atr_window": 2,
        "atr_stop_mult": 2.0,
        "risk_per_trade_pct": 0.001,
        "target_notional_usdt": 50,
        "min_atr_ratio": 0.0,
        "max_position_pct": 0.5,
        "max_total_notional_pct": 1.0,
        "min_order_notional_usdt": 0.5,
        "market_sma_window": 2,
        "leverage": 5,
        "strategy_diagnostic_ws": True,
        "strategy_diagnostic_every_n_bars": 1,
        **us_semis_session_config(),
    }


def test_cta_ema_cross_opens_risk_sized_long():
    strategy, broker = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "trend_filter": "ema_cross",
            "fast_window": 2,
            "slow_window": 3,
            "atr_window": 2,
            "atr_stop_mult": 2.0,
            "risk_per_trade_pct": 0.01,
            "min_atr_ratio": 0.0,
            "max_position_pct": 1.0,
            "max_total_notional_pct": 1.0,
            "min_order_notional_usdt": 1.0,
            "market_sma_window": 2,
            "leverage": 2,
        }
    )
    events = []

    async def capture_event(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture_event

    for index, close in enumerate([100.0, 99.0, 98.0, 105.0]):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", close, index, spread=1.0)))

    assert broker.orders
    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["side"] == "long"
    volatility = atr(list(strategy._bars["BTC/USDT:USDT"]), 2)
    expected, _ = strategy.risk_manager.position_sizer.atr_based(10_000.0, 0.01, volatility, 105.0, 2.0)
    assert broker.orders[-1]["notional"] == pytest.approx(expected)
    assert events[-1]["decision"] == "open_cta_position"
    assert events[-1]["decision_label"] == "CTA 开仓"
    assert events[-1]["summary"] == "CTA 趋势信号已开合约仓位"


def test_cta_session_filter_blocks_new_entries_during_early_us_premarket_observe_window():
    strategy, broker = init_strategy(
        session_filtered_entry_config(),
        symbols=["NVDA/USDT:USDT"],
        broker=FakeContractBroker(equity=100.0),
    )
    events = []

    async def capture_event(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture_event

    for bar in bars_ending_at("NVDA/USDT:USDT", [100.0, 99.0, 98.0, 105.0], utc_ms(2026, 5, 22, 10, 30)):
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders == []
    assert events[-1]["decision"] == "entry_session_closed"
    assert events[-1]["details"]["session_name"] == "us_early_premarket_observe"


def test_cta_session_filter_allows_half_size_entries_during_us_premarket_core():
    strategy, broker = init_strategy(
        session_filtered_entry_config(),
        symbols=["NVDA/USDT:USDT"],
        broker=FakeContractBroker(equity=100.0),
    )

    for bar in bars_ending_at("NVDA/USDT:USDT", [100.0, 99.0, 98.0, 105.0], utc_ms(2026, 5, 22, 12, 0)):
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders
    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["side"] == "long"
    assert broker.orders[-1]["notional"] == pytest.approx(25.0)


def test_cta_session_filter_keeps_existing_position_exits_active_outside_entry_window():
    broker = FakeContractBroker(equity=100.0)
    broker.positions[("NVDA/USDT:USDT", "long")] = {
        "symbol": "NVDA/USDT:USDT",
        "pos_side": "long",
        "base_qty": 1.0,
        "entry_price": 100.0,
        "mark_price": 100.0,
        "notional_usdt": 100.0,
    }
    cfg = {
        **session_filtered_entry_config(),
        "hard_stop_loss_pct": 0.04,
    }
    strategy, broker = init_strategy(cfg, symbols=["NVDA/USDT:USDT"], broker=broker)

    for bar in bars_ending_at("NVDA/USDT:USDT", [100.0, 100.0, 100.0, 99.0], utc_ms(2026, 5, 22, 10, 30)):
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders
    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["side"] == "long"
    assert ("NVDA/USDT:USDT", "long") not in broker.positions


def test_cta_target_notional_floor_raises_small_account_order_size():
    strategy, broker = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "trend_filter": "ema_cross",
            "fast_window": 2,
            "slow_window": 3,
            "atr_window": 2,
            "atr_stop_mult": 2.0,
            "risk_per_trade_pct": 0.001,
            "target_notional_usdt": 50,
            "min_atr_ratio": 0.0,
            "max_position_pct": 0.5,
            "max_total_notional_pct": 1.5,
            "min_order_notional_usdt": 0.5,
            "market_sma_window": 2,
            "leverage": 5,
        },
        broker=FakeContractBroker(equity=100.0),
    )

    for index, close in enumerate([100.0, 99.0, 98.0, 105.0]):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", close, index, spread=1.0)))

    assert broker.orders
    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["side"] == "long"
    assert broker.orders[-1]["notional"] == pytest.approx(50.0)
    assert broker.orders[-1]["leverage"] == 5


def test_cta_ema_state_opens_when_fast_ema_is_above_slow_ema():
    strategy, broker = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "trend_filter": "ema_state",
            "fast_window": 2,
            "slow_window": 4,
            "atr_window": 2,
            "atr_stop_mult": 1.5,
            "risk_per_trade_pct": 0.015,
            "min_atr_ratio": 0.0,
            "max_position_pct": 1.0,
            "max_total_notional_pct": 1.0,
            "min_order_notional_usdt": 1.0,
            "market_sma_window": 2,
            "leverage": 3,
        }
    )

    for index, close in enumerate([100.0, 101.0, 102.0, 103.0, 104.0]):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", close, index, spread=1.0)))

    assert broker.orders
    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["side"] == "long"
    assert broker.orders[-1]["leverage"] == 3


def test_cta_entry_adx_gate_blocks_weak_trend_and_accepts_strong_trend():
    strategy, _ = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "trend_filter": "ema_state",
            "fast_window": 5,
            "slow_window": 20,
            "entry_signal_confirm_bars": 1,
            "entry_adx_window": 14,
            "entry_min_adx": 18,
            "atr_window": 10,
            "market_sma_window": 12,
        }
    )
    weak_bars = [
        make_bar("BTC/USDT:USDT", 100.0 + (index % 2), index, spread=1.0)
        for index in range(29)
    ]
    strong_bars = [
        make_bar("BTC/USDT:USDT", 100.0 + index, index, spread=1.0)
        for index in range(29)
    ]

    assert strategy._entry_signal("BTC/USDT:USDT", weak_bars, raw_signal=1) == 0
    assert strategy._entry_signal("BTC/USDT:USDT", strong_bars, raw_signal=1) == 1


def test_cta_ema_slope_adx_signal_requires_three_ema_layers_and_trend_strength():
    strategy, _ = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["SOL/USDT:USDT"],
            "trend_filter": "ema_slope_adx",
            "fast_window": 3,
            "mid_window": 5,
            "slow_window": 8,
            "slope_lookback_bars": 2,
            "adx_window": 3,
            "min_adx": 10,
            "min_slow_slope_atr": 0.05,
            "min_fast_mid_slope_gap_atr": 0.02,
            "min_ema_spread_atr": 0.10,
            "max_price_extension_atr": 10,
            "atr_window": 3,
            "market_sma_window": 3,
        },
        symbols=["SOL/USDT:USDT"],
    )
    bars = [
        make_bar("SOL/USDT:USDT", close, index, spread=1.0)
        for index, close in enumerate([100, 101, 102, 103, 105, 108, 112, 117, 123, 130, 138, 147])
    ]

    assert strategy.trend_filter == "ema_slope_adx"
    assert strategy._trend_signal("SOL/USDT:USDT", bars) == 1


def test_cta_ema_slope_adx_signal_blocks_flat_ema_chop():
    strategy, _ = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["DOGE/USDT:USDT"],
            "trend_filter": "ema_slope_adx",
            "fast_window": 3,
            "mid_window": 5,
            "slow_window": 8,
            "slope_lookback_bars": 2,
            "adx_window": 3,
            "min_adx": 10,
            "min_slow_slope_atr": 0.05,
            "min_fast_mid_slope_gap_atr": 0.02,
            "min_ema_spread_atr": 0.10,
            "max_price_extension_atr": 10,
            "atr_window": 3,
            "market_sma_window": 3,
        },
        symbols=["DOGE/USDT:USDT"],
    )
    bars = [
        make_bar("DOGE/USDT:USDT", close, index, spread=1.0)
        for index, close in enumerate([100.0, 100.2, 99.9, 100.1, 99.8, 100.0, 100.1, 99.9, 100.0, 100.2, 100.0, 100.1])
    ]

    assert strategy._trend_signal("DOGE/USDT:USDT", bars) == 0


def test_cta_ema_slope_adx_trend_score_captures_visual_short_trend_without_fast_acceleration():
    strategy, _ = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["SOL/USDT:USDT"],
            "trend_filter": "ema_slope_adx",
            "trend_score_enabled": True,
            "trend_score_min": 6,
            "fast_window": 3,
            "mid_window": 5,
            "slow_window": 8,
            "slope_lookback_bars": 2,
            "adx_window": 3,
            "min_adx": 10,
            "min_slow_slope_atr": 0.05,
            "min_fast_mid_slope_gap_atr": 99.0,
            "min_ema_spread_atr": 0.10,
            "max_price_extension_atr": 10,
            "trend_score_structure_lookback_bars": 5,
            "trend_score_regression_lookback_bars": 6,
            "trend_score_min_r2": 0.35,
            "atr_window": 3,
            "market_sma_window": 3,
        },
        symbols=["SOL/USDT:USDT"],
    )
    bars = [
        make_bar("SOL/USDT:USDT", close, index, spread=1.0)
        for index, close in enumerate([120, 119, 118, 117, 115, 112, 109, 106, 104, 103, 102, 100, 99, 98, 97])
    ]

    assert strategy.trend_score_enabled is True
    assert strategy._trend_signal("SOL/USDT:USDT", bars) == -1


def test_cta_ema_slope_adx_trend_score_uses_ema_spread_as_score_not_hard_gate():
    strategy, _ = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["SOL/USDT:USDT"],
            "trend_filter": "ema_slope_adx",
            "trend_score_enabled": True,
            "trend_score_min": 6,
            "fast_window": 3,
            "mid_window": 5,
            "slow_window": 8,
            "slope_lookback_bars": 2,
            "adx_window": 3,
            "min_adx": 10,
            "min_slow_slope_atr": 0.05,
            "min_fast_mid_slope_gap_atr": 99.0,
            "min_ema_spread_atr": 99.0,
            "max_price_extension_atr": 100,
            "trend_score_structure_lookback_bars": 5,
            "trend_score_regression_lookback_bars": 6,
            "trend_score_min_r2": 0.35,
            "atr_window": 3,
            "market_sma_window": 3,
        },
        symbols=["SOL/USDT:USDT"],
    )
    bars = [
        make_bar("SOL/USDT:USDT", close, index, spread=1.0)
        for index, close in enumerate([120, 119, 118, 117, 115, 112, 109, 106, 104, 103, 102, 100, 99, 98, 97])
    ]

    assert strategy._trend_signal("SOL/USDT:USDT", bars) == -1


def test_cta_ema_slope_adx_trend_score_blocks_chop_without_directional_structure():
    strategy, _ = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["DOGE/USDT:USDT"],
            "trend_filter": "ema_slope_adx",
            "trend_score_enabled": True,
            "trend_score_min": 6,
            "fast_window": 3,
            "mid_window": 5,
            "slow_window": 8,
            "slope_lookback_bars": 2,
            "adx_window": 3,
            "min_adx": 10,
            "min_slow_slope_atr": 0.05,
            "min_fast_mid_slope_gap_atr": 0.02,
            "min_ema_spread_atr": 0.10,
            "max_price_extension_atr": 10,
            "trend_score_structure_lookback_bars": 5,
            "trend_score_regression_lookback_bars": 6,
            "trend_score_min_r2": 0.35,
            "atr_window": 3,
            "market_sma_window": 3,
        },
        symbols=["DOGE/USDT:USDT"],
    )
    bars = [
        make_bar("DOGE/USDT:USDT", close, index, spread=1.0)
        for index, close in enumerate([100.0, 100.3, 99.9, 100.2, 99.8, 100.1, 100.4, 99.9, 100.0, 100.2, 99.7, 100.1])
    ]

    assert strategy._trend_signal("DOGE/USDT:USDT", bars) == 0


def test_cta_ema_state_entry_confirmation_waits_for_persistent_signal():
    strategy, broker = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "trend_filter": "ema_state",
            "fast_window": 2,
            "slow_window": 3,
            "entry_signal_confirm_bars": 2,
            "atr_window": 2,
            "atr_stop_mult": 1.5,
            "risk_per_trade_pct": 0.015,
            "min_atr_ratio": 0.0,
            "max_position_pct": 1.0,
            "max_total_notional_pct": 1.0,
            "min_order_notional_usdt": 1.0,
            "market_sma_window": 2,
            "leverage": 3,
        }
    )

    for index, close in enumerate([100.0, 99.0, 98.0, 105.0]):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", close, index, spread=1.0)))

    assert broker.orders == []

    asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", 106.0, 4, spread=1.0)))

    assert broker.orders
    assert broker.orders[-1]["action"] == "open"


def test_cta_higher_timeframe_filter_blocks_15m_long_against_1h_downtrend():
    strategy, _ = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "trend_filter": "ema_state",
            "fast_window": 2,
            "slow_window": 3,
            "entry_signal_confirm_bars": 1,
            "atr_window": 2,
            "min_atr_ratio": 0.0,
            "market_sma_window": 2,
            "higher_timeframe_filter_enabled": True,
            "higher_timeframe_minutes": 60,
            "higher_timeframe_fast_window": 2,
            "higher_timeframe_slow_window": 3,
        }
    )
    closes_15m = [120, 119, 118, 117, 116, 115, 114, 113, 112, 111, 110, 109, 108, 107, 106, 105, 112]
    bars = [
        make_bar("BTC/USDT:USDT", close, index, timeframe="15m", interval_ms=900_000)
        for index, close in enumerate(closes_15m)
    ]
    raw_signal = strategy._trend_signal("BTC/USDT:USDT", bars)

    assert raw_signal == 1
    assert strategy._entry_signal("BTC/USDT:USDT", bars, raw_signal) == 0


def test_cta_ema_state_exit_uses_raw_signal_even_with_entry_confirmation():
    broker = FakeContractBroker()
    broker.positions[("BTC/USDT:USDT", "long")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "long",
        "base_qty": 1.0,
        "entry_price": 100.0,
        "mark_price": 100.0,
        "notional_usdt": 100.0,
    }
    strategy, broker = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "trend_filter": "ema_state",
            "fast_window": 2,
            "slow_window": 3,
            "entry_signal_confirm_bars": 2,
            "entry_adx_window": 14,
            "entry_min_adx": 18,
            "atr_window": 2,
            "atr_stop_mult": 10.0,
            "market_sma_window": 2,
            "min_atr_ratio": 0.0,
            "reversal_exit": True,
        },
        broker=broker,
    )

    for index, close in enumerate([100.0, 101.0, 102.0, 95.0]):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", close, index, spread=1.0)))

    assert broker.orders
    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["side"] == "long"


def test_cta_reversal_reentry_closes_and_opens_opposite_side_on_same_bar():
    broker = FakeContractBroker()
    broker.positions[("BTC/USDT:USDT", "long")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "long",
        "base_qty": 1.0,
        "entry_price": 100.0,
        "mark_price": 100.0,
        "notional_usdt": 100.0,
    }
    strategy, broker = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "trend_filter": "ema_state",
            "fast_window": 2,
            "slow_window": 3,
            "entry_signal_confirm_bars": 1,
            "atr_window": 2,
            "atr_stop_mult": 10.0,
            "market_sma_window": 2,
            "min_atr_ratio": 0.0,
            "max_position_pct": 1.0,
            "max_total_notional_pct": 1.0,
            "min_order_notional_usdt": 1.0,
            "reversal_exit": True,
            "reversal_reentry_enabled": True,
        },
        broker=broker,
    )

    for index, close in enumerate([100.0, 101.0, 102.0, 95.0]):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", close, index, spread=1.0)))

    assert [order["action"] for order in broker.orders[-2:]] == ["close", "open"]
    assert broker.orders[-2]["side"] == "long"
    assert broker.orders[-1]["side"] == "short"
    assert broker.positions[("BTC/USDT:USDT", "short")]


def test_cta_low_volatility_filter_blocks_entry():
    strategy, broker = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "trend_filter": "ema_cross",
            "fast_window": 2,
            "slow_window": 3,
            "atr_window": 2,
            "atr_stop_mult": 2.0,
            "risk_per_trade_pct": 0.01,
            "min_atr_ratio": 0.20,
            "max_position_pct": 1.0,
            "max_total_notional_pct": 1.0,
            "min_order_notional_usdt": 1.0,
            "market_sma_window": 2,
        }
    )

    for index, close in enumerate([100.0, 99.0, 98.0, 105.0]):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", close, index, spread=0.05)))

    assert broker.orders == []


def test_cta_atr_trailing_stop_closes_long_position():
    broker = FakeContractBroker()
    broker.positions[("BTC/USDT:USDT", "long")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "long",
        "base_qty": 10.0,
        "entry_price": 100.0,
        "mark_price": 100.0,
        "notional_usdt": 1000.0,
    }
    strategy, broker = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "trend_filter": "ema_cross",
            "fast_window": 2,
            "slow_window": 3,
            "atr_window": 2,
            "atr_stop_mult": 1.0,
            "market_sma_window": 2,
            "min_atr_ratio": 0.0,
        },
        broker=broker,
    )

    for index, close in enumerate([100.0, 102.0, 104.0, 105.0, 101.0]):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", close, index, spread=1.0)))

    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["side"] == "long"


def test_cta_existing_position_emits_hold_reason_when_exit_not_triggered():
    broker = FakeContractBroker()
    broker.positions[("SOL/USDT:USDT", "long")] = {
        "symbol": "SOL/USDT:USDT",
        "pos_side": "long",
        "base_qty": 10.0,
        "entry_price": 100.0,
        "mark_price": 100.0,
        "notional_usdt": 1000.0,
    }
    strategy, broker = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["SOL/USDT:USDT"],
            "trend_filter": "ema_cross",
            "fast_window": 2,
            "slow_window": 3,
            "atr_window": 2,
            "atr_stop_mult": 2.0,
            "market_sma_window": 2,
            "min_atr_ratio": 0.0,
            "strategy_diagnostic_ws": True,
            "strategy_diagnostic_every_n_bars": 10,
        },
        symbols=["SOL/USDT:USDT"],
        broker=broker,
    )
    events = []

    async def capture_event(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture_event

    for index, close in enumerate([100.0, 101.0, 102.0, 103.0], start=1):
        asyncio.run(strategy.on_bar(make_bar("SOL/USDT:USDT", close, index, spread=1.0)))

    hold_events = [event for event in events if event["decision"] == "hold_cta_position"]
    assert broker.orders == []
    assert hold_events
    assert hold_events[-1]["decision_label"] == "继续持仓"
    assert "未触发 ATR 跟踪止损" in hold_events[-1]["summary"]
    assert hold_events[-1]["details"]["trailing_stop"] is not None


def test_cta_profit_protection_moves_stop_to_breakeven_after_one_r():
    strategy, _ = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "profit_protection_enabled": True,
            "break_even_at_r": 1.0,
            "break_even_buffer_bps": 0,
        }
    )
    key = ("BTC/USDT:USDT", "long")
    info = PositionInfo(
        symbol=key[0],
        side=key[1],
        amount=1.0,
        entry_price=100.0,
        current_price=106.0,
        stop_loss=94.0,
        trailing_stop=94.0,
        highest_price=106.0,
        lowest_price=100.0,
    )
    strategy._initial_risk_price[key] = 6.0

    strategy._apply_break_even_stop(key, info)

    assert info.trailing_stop == pytest.approx(100.0)


def test_cta_profit_protection_detects_peak_pullback_after_activation():
    strategy, _ = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "profit_protection_enabled": True,
            "profit_trailing_start_r": 1.5,
            "profit_peak_pullback_pct": 0.35,
        }
    )
    key = ("BTC/USDT:USDT", "long")
    info = PositionInfo(
        symbol=key[0],
        side=key[1],
        amount=1.0,
        entry_price=100.0,
        current_price=106.0,
        stop_loss=94.0,
        trailing_stop=100.0,
        highest_price=110.0,
        lowest_price=100.0,
    )
    strategy._initial_risk_price[key] = 6.0

    reason = strategy._profit_protection_reason(key, info)

    assert reason is not None
    assert "回撤" in reason
    assert "1.67R" in reason


def test_cta_profit_protection_tightens_atr_stop_after_activation():
    strategy, _ = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "profit_protection_enabled": True,
            "profit_atr_trailing_start_r": 1.2,
            "profit_atr_stop_mult": 1.1,
        }
    )
    key = ("BTC/USDT:USDT", "long")
    info = PositionInfo(
        symbol=key[0],
        side=key[1],
        amount=1.0,
        entry_price=100.0,
        current_price=110.0,
        stop_loss=94.0,
        trailing_stop=100.0,
        highest_price=110.0,
        lowest_price=100.0,
    )
    strategy._initial_risk_price[key] = 6.0

    strategy._apply_profit_atr_stop(key, info, volatility=2.0)

    assert info.trailing_stop == pytest.approx(107.8)


def test_cta_profit_protection_uses_tighter_pullback_after_large_profit():
    strategy, _ = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "profit_protection_enabled": True,
            "profit_trailing_start_r": 1.2,
            "profit_peak_pullback_pct": 0.25,
            "profit_tighten_at_r": 2.0,
            "profit_tight_pullback_pct": 0.18,
        }
    )
    key = ("BTC/USDT:USDT", "long")
    info = PositionInfo(
        symbol=key[0],
        side=key[1],
        amount=1.0,
        entry_price=100.0,
        current_price=110.0,
        stop_loss=94.0,
        trailing_stop=100.0,
        highest_price=113.0,
        lowest_price=100.0,
    )
    strategy._initial_risk_price[key] = 6.0

    reason = strategy._profit_protection_reason(key, info)

    assert reason is not None
    assert "18%" in reason


def test_cta_profit_protection_exits_when_old_profit_decays_from_peak():
    strategy, _ = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "profit_protection_enabled": True,
            "profit_trailing_start_r": 1.2,
            "max_profit_hold_bars": 12,
            "profit_decay_exit_pct": 0.50,
        }
    )
    key = ("BTC/USDT:USDT", "long")
    info = PositionInfo(
        symbol=key[0],
        side=key[1],
        amount=1.0,
        entry_price=100.0,
        current_price=106.0,
        stop_loss=94.0,
        trailing_stop=100.0,
        highest_price=113.0,
        lowest_price=100.0,
    )
    strategy._initial_risk_price[key] = 6.0
    strategy._entry_bar_count[key] = 3
    strategy._bar_counts[key[0]] = 16

    reason = strategy._profit_protection_reason(key, info)

    assert reason is not None
    assert "时间止盈" in reason


def test_cta_hard_stop_loss_closes_long_before_other_exit_rules():
    strategy, broker = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "hard_stop_loss_pct": 0.03,
            "hard_take_profit_pct": 0.15,
        }
    )
    broker.positions[("BTC/USDT:USDT", "long")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "long",
        "base_qty": 1.0,
        "entry_price": 100.0,
        "mark_price": 96.9,
        "notional_usdt": 100.0,
    }
    events = []

    async def capture_event(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture_event

    closed = asyncio.run(strategy._manage_existing_positions("BTC/USDT:USDT", 96.9, 100.0, signal=1))

    assert closed is True
    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["side"] == "long"
    assert events[-1]["decision"] == "close_cta_hard_stop"
    assert events[-1]["decision_label"] == "保证金兜底止损平仓"
    assert "3.00%" in events[-1]["details"]["reason"]


def test_cta_hard_stop_loss_uses_margin_roi_for_leveraged_long():
    strategy, broker = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "leverage": 5,
            "hard_stop_loss_pct": 0.04,
            "hard_take_profit_pct": 0.20,
        }
    )
    broker.positions[("BTC/USDT:USDT", "long")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "long",
        "base_qty": 1.0,
        "entry_price": 100.0,
        "mark_price": 99.0,
        "notional_usdt": 100.0,
    }
    events = []

    async def capture_event(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture_event

    closed = asyncio.run(strategy._manage_existing_positions("BTC/USDT:USDT", 99.0, 100.0, signal=1))

    assert closed is True
    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["side"] == "long"
    assert events[-1]["decision"] == "close_cta_hard_stop"
    assert "保证金收益率 -5.00%" in events[-1]["details"]["reason"]
    assert "阈值 -4.00%" in events[-1]["details"]["reason"]


def test_cta_hard_take_profit_closes_short_after_original_guards_do_not_trigger():
    strategy, broker = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "hard_stop_loss_pct": 0.03,
            "hard_take_profit_pct": 0.15,
        }
    )
    broker.positions[("BTC/USDT:USDT", "short")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "short",
        "base_qty": 1.0,
        "entry_price": 100.0,
        "mark_price": 84.9,
        "notional_usdt": 100.0,
    }
    events = []

    async def capture_event(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture_event

    closed = asyncio.run(strategy._manage_existing_positions("BTC/USDT:USDT", 84.9, 100.0, signal=-1))

    assert closed is True
    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["side"] == "short"
    assert events[-1]["decision"] == "close_cta_hard_take_profit"
    assert events[-1]["decision_label"] == "保证金兜底止盈平仓"
    assert "15.00%" in events[-1]["details"]["reason"]


def test_cta_hard_take_profit_uses_margin_roi_for_leveraged_short():
    strategy, broker = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "leverage": 5,
            "hard_stop_loss_pct": 0.04,
            "hard_take_profit_pct": 0.20,
        }
    )
    broker.positions[("BTC/USDT:USDT", "short")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "short",
        "base_qty": 1.0,
        "entry_price": 100.0,
        "mark_price": 96.0,
        "notional_usdt": 100.0,
    }
    events = []

    async def capture_event(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture_event

    closed = asyncio.run(strategy._manage_existing_positions("BTC/USDT:USDT", 96.0, 100.0, signal=-1))

    assert closed is True
    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["side"] == "short"
    assert events[-1]["decision"] == "close_cta_hard_take_profit"
    assert "保证金收益率 20.00%" in events[-1]["details"]["reason"]
    assert "阈值 20.00%" in events[-1]["details"]["reason"]


def test_cta_restores_persisted_profit_lock_state_for_existing_position():
    broker = FakeContractBroker()
    broker.positions[("OPENAI/USDT:USDT", "long")] = {
        "symbol": "OPENAI/USDT:USDT",
        "pos_side": "long",
        "base_qty": 1.0,
        "entry_price": 100.0,
        "mark_price": 126.0,
        "notional_usdt": 100.0,
    }
    state = make_state(["OPENAI/USDT:USDT"])
    state.positions["_cta_risk_state"] = {
        "OPENAI/USDT:USDT|long": {
            "symbol": "OPENAI/USDT:USDT",
            "side": "long",
            "entry_price": 100.0,
            "highest_price": 130.0,
            "lowest_price": 100.0,
            "trailing_stop": 124.0,
            "initial_risk_price": 6.0,
            "entry_bar_count": 2,
        }
    }
    strategy = CtaTrendFollowingStrategy(state, broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": ["OPENAI/USDT:USDT"],
            "trend_filter": "ema_state",
            "fast_window": 2,
            "slow_window": 3,
            "atr_window": 2,
            "atr_stop_mult": 1.0,
            "market_sma_window": 2,
            "min_atr_ratio": 0.0,
            "profit_protection_enabled": True,
            "profit_atr_trailing_start_r": 1.2,
            "profit_atr_stop_mult": 1.2,
        }
    )
    asyncio.run(strategy.on_init())

    for index, close in enumerate([126.0, 127.0, 128.0, 129.0], start=1):
        asyncio.run(strategy.on_bar(make_bar("OPENAI/USDT:USDT", close, index, spread=1.0)))

    key = ("OPENAI/USDT:USDT", "long")
    assert strategy._risk_positions[key].highest_price == pytest.approx(130.0)
    assert strategy._risk_positions[key].trailing_stop >= 124.0
    assert strategy._initial_risk_price[key] == pytest.approx(6.0)
    assert strategy._entry_bar_count[key] == 2


def test_cta_persists_profit_lock_state_after_position_management():
    broker = FakeContractBroker()
    broker.positions[("OPENAI/USDT:USDT", "short")] = {
        "symbol": "OPENAI/USDT:USDT",
        "pos_side": "short",
        "base_qty": 1.0,
        "entry_price": 100.0,
        "mark_price": 92.0,
        "notional_usdt": 100.0,
    }
    strategy, _ = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["OPENAI/USDT:USDT"],
            "trend_filter": "ema_state",
            "fast_window": 2,
            "slow_window": 3,
            "atr_window": 2,
            "atr_stop_mult": 1.0,
            "market_sma_window": 2,
            "min_atr_ratio": 0.0,
            "profit_protection_enabled": True,
            "profit_atr_trailing_start_r": 1.2,
            "profit_atr_stop_mult": 1.2,
        },
        symbols=["OPENAI/USDT:USDT"],
        broker=broker,
    )

    for index, close in enumerate([99.0, 96.0, 94.0, 92.0], start=1):
        asyncio.run(strategy.on_bar(make_bar("OPENAI/USDT:USDT", close, index, spread=1.0)))

    saved = strategy.state.positions["_cta_risk_state"]["OPENAI/USDT:USDT|short"]
    assert saved["lowest_price"] == pytest.approx(92.0)
    assert saved["initial_risk_price"] > 0
    assert saved["entry_bar_count"] == strategy._entry_bar_count[("OPENAI/USDT:USDT", "short")]


def test_cta_warmup_bars_do_not_manage_restored_positions():
    broker = FakeContractBroker()
    broker.warmup_mode = True
    broker.positions[("SOL/USDT:USDT", "long")] = {
        "symbol": "SOL/USDT:USDT",
        "pos_side": "long",
        "base_qty": 10.0,
        "entry_price": 100.0,
        "mark_price": 100.0,
        "notional_usdt": 1000.0,
    }
    strategy, broker = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": ["SOL/USDT:USDT"],
            "trend_filter": "ema_cross",
            "fast_window": 2,
            "slow_window": 3,
            "atr_window": 2,
            "atr_stop_mult": 1.0,
            "market_sma_window": 2,
            "min_atr_ratio": 0.0,
            "strategy_diagnostic_ws": True,
            "strategy_diagnostic_every_n_bars": 1,
        },
        symbols=["SOL/USDT:USDT"],
        broker=broker,
    )
    events = []

    async def capture_event(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture_event

    for index, close in enumerate([100.0, 98.0, 95.0, 90.0], start=1):
        asyncio.run(strategy.on_bar(make_bar("SOL/USDT:USDT", close, index, spread=1.0)))

    assert broker.orders == []
    assert broker.positions[("SOL/USDT:USDT", "long")]
    assert events == []
    assert len(strategy._bars["SOL/USDT:USDT"]) == 4


def test_cta_market_regime_blocks_long_when_broad_market_is_below_sma():
    symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT"]
    strategy, broker = init_strategy(
        {
            "market_type": "swap",
            "trade_symbols": symbols,
            "trend_filter": "donchian",
            "fast_window": 2,
            "slow_window": 3,
            "atr_window": 2,
            "atr_stop_mult": 2.0,
            "min_atr_ratio": 0.0,
            "max_position_pct": 1.0,
            "max_total_notional_pct": 1.0,
            "min_order_notional_usdt": 1.0,
            "market_sma_window": 3,
            "market_regime_threshold": 0.8,
        },
        symbols=symbols,
    )

    for alt in symbols[1:]:
        for index, close in enumerate([100.0, 99.0, 98.0, 98.0]):
            asyncio.run(strategy.on_bar(make_bar(alt, close, index, spread=0.2)))
    for index, close in enumerate([100.0, 99.0, 98.0, 102.0]):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", close, index, spread=0.2)))

    assert broker.orders == []
    assert strategy._market_regime() == "short_only"
