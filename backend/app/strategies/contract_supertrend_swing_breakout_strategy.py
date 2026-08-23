"""OKX USDT perpetual Supertrend-confirmed swing breakout strategy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from app.core.execution.base_strategy import BarData
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price


@dataclass(frozen=True)
class SwingLevels:
    swing_high: Optional[float] = None
    swing_high_timestamp: Optional[int] = None
    swing_low: Optional[float] = None
    swing_low_timestamp: Optional[int] = None


def confirmed_swing_levels(
    bars: List[BarData],
    *,
    lookback_bars: int,
    confirm_bars: int,
) -> SwingLevels:
    """Return the latest confirmed swing high/low without using unconfirmed right-side bars."""
    lookback = max(1, int(lookback_bars))
    confirm = max(1, int(confirm_bars))
    last_candidate = len(bars) - confirm - 1
    if last_candidate < lookback:
        return SwingLevels()

    swing_high: Optional[float] = None
    swing_high_timestamp: Optional[int] = None
    swing_low: Optional[float] = None
    swing_low_timestamp: Optional[int] = None

    for idx in range(lookback, last_candidate + 1):
        current = bars[idx]
        left = bars[idx - lookback:idx]
        right = bars[idx + 1:idx + confirm + 1]
        if len(right) < confirm:
            continue

        high = float(current.high)
        low = float(current.low)
        if high > max(float(item.high) for item in left) and high > max(float(item.high) for item in right):
            swing_high = high
            swing_high_timestamp = int(current.timestamp)
        if low < min(float(item.low) for item in left) and low < min(float(item.low) for item in right):
            swing_low = low
            swing_low_timestamp = int(current.timestamp)

    return SwingLevels(
        swing_high=swing_high,
        swing_high_timestamp=swing_high_timestamp,
        swing_low=swing_low,
        swing_low_timestamp=swing_low_timestamp,
    )


def efficiency_ratio(values: Iterable[float], window: int) -> Optional[float]:
    sample = [float(value) for value in values]
    period = max(1, int(window))
    if len(sample) < period + 1:
        return None
    segment = sample[-period - 1:]
    net_change = abs(segment[-1] - segment[0])
    path = sum(abs(cur - prev) for prev, cur in zip(segment[:-1], segment[1:]))
    if path <= 1e-12:
        return 0.0
    return net_change / path


def supertrend_direction(bars: List[BarData], *, atr_window: int, factor: float) -> int:
    """Compute the current Supertrend direction from confirmed OHLCV bars."""
    window = max(1, int(atr_window))
    mult = max(0.01, float(factor))
    if len(bars) < window + 1:
        return 0

    final_upper: Optional[float] = None
    final_lower: Optional[float] = None
    direction = 0

    for idx in range(window, len(bars)):
        history = bars[:idx + 1]
        volatility = atr(history, window)
        if volatility is None or volatility <= 0:
            continue
        current = bars[idx]
        prev_close = float(bars[idx - 1].close)
        midpoint = (float(current.high) + float(current.low)) / 2.0
        basic_upper = midpoint + mult * volatility
        basic_lower = midpoint - mult * volatility

        if final_upper is None or final_lower is None:
            final_upper = basic_upper
            final_lower = basic_lower
            direction = 1 if float(current.close) >= prev_close else -1
            continue

        final_upper = basic_upper if basic_upper < final_upper or prev_close > final_upper else final_upper
        final_lower = basic_lower if basic_lower > final_lower or prev_close < final_lower else final_lower

        close = float(current.close)
        if direction <= 0 and close > final_upper:
            direction = 1
        elif direction >= 0 and close < final_lower:
            direction = -1
    return direction


class ContractSupertrendSwingBreakoutStrategy(ContractStrategyBase):
    """Paper-only swing breakout CTA with Supertrend confirmation and adaptive trailing stops."""

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}
        self.trade_symbols = tuple(dict.fromkeys(self._configured_symbols()))
        self.swing_lookback_bars = max(1, int(cfg.get("swing_lookback_bars", 3)))
        self.swing_confirm_bars = max(1, int(cfg.get("swing_confirm_bars", 2)))
        self.efficiency_window = max(1, int(cfg.get("efficiency_window", 20)))
        self.min_efficiency_ratio = max(0.0, float(cfg.get("min_efficiency_ratio", 0.25)))
        self.atr_window = max(1, int(cfg.get("atr_window", 10)))
        self.supertrend_factor = max(0.01, float(cfg.get("supertrend_factor", 2.4)))
        self.breakout_atr_buffer = max(0.0, float(cfg.get("breakout_atr_buffer", 0.0)))
        self.min_swing_range_atr_mult = max(0.0, float(cfg.get("min_swing_range_atr_mult", 0.0)))
        self.trend_ema_window = max(0, int(cfg.get("trend_ema_window", 0)))
        self.trend_ema_slope_bars = max(1, int(cfg.get("trend_ema_slope_bars", 4)))
        self.min_trend_ema_slope_atr = max(0.0, float(cfg.get("min_trend_ema_slope_atr", 0.0)))
        self.initial_trailing_atr_mult = max(0.1, float(cfg.get("initial_trailing_atr_mult", 1.4)))
        self.max_trailing_atr_mult = max(
            self.initial_trailing_atr_mult,
            float(cfg.get("max_trailing_atr_mult", 2.4)),
        )
        self.trailing_relax_bars = max(0, int(cfg.get("trailing_relax_bars", 12)))
        self.min_stop_pct = max(0.0, float(cfg.get("min_stop_pct", 0.006)))
        self.require_swing_pair = bool(cfg.get("require_swing_pair", True))
        self.reversal_exit = bool(cfg.get("reversal_exit", True))
        self.reversal_reentry_enabled = bool(cfg.get("reversal_reentry_enabled", False))
        self.cooldown_bars = max(0, int(cfg.get("cooldown_bars", 0)))
        self._position_state: Dict[tuple[str, str], Dict[str, float]] = {}
        self._cooldown_until_bar: Dict[str, int] = {}

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return
        symbol = normalize_contract_symbol(bar.symbol)
        if self.trade_symbols and symbol not in self.trade_symbols:
            return
        norm_bar = self._normalized_bar(bar, symbol)
        bars = self._append_bar(norm_bar)
        if getattr(self.broker, "warmup_mode", False):
            return
        if len(bars) < self._warmup_required():
            return

        volatility = atr(bars, self.atr_window)
        if volatility is None or volatility <= 0:
            return

        signal = self._entry_signal(bars, volatility)
        closed = await self._manage_existing_positions(symbol, norm_bar, volatility, signal)
        if closed and not self.reversal_reentry_enabled:
            return
        if await self._has_symbol_position(symbol):
            return
        if self._entry_is_in_cooldown(symbol):
            return
        if signal not in {"long", "short"}:
            return

        result = await self._open_if_flat(symbol, signal, float(norm_bar.close))
        if self._accepted(result):
            self._position_state[(symbol, signal)] = self._new_position_state(
                symbol=symbol,
                side=signal,
                entry_price=float(norm_bar.close),
                bar=norm_bar,
                volatility=volatility,
            )

    def _entry_signal(self, bars: List[BarData], volatility: float) -> Optional[str]:
        values = closes(bars)
        trend_dir = supertrend_direction(bars, atr_window=self.atr_window, factor=self.supertrend_factor)
        if trend_dir == 0:
            return None

        ratio = efficiency_ratio(values, self.efficiency_window)
        if ratio is None or ratio < self.min_efficiency_ratio:
            return None

        levels = confirmed_swing_levels(
            bars,
            lookback_bars=self.swing_lookback_bars,
            confirm_bars=self.swing_confirm_bars,
        )
        if self.require_swing_pair and (levels.swing_high is None or levels.swing_low is None):
            return None
        if (
            self.min_swing_range_atr_mult > 0
            and levels.swing_high is not None
            and levels.swing_low is not None
            and levels.swing_high - levels.swing_low < self.min_swing_range_atr_mult * volatility
        ):
            return None

        current_close = float(bars[-1].close)
        prev_close = float(bars[-2].close) if len(bars) >= 2 else current_close
        breakout_buffer = self.breakout_atr_buffer * volatility
        if levels.swing_high is not None and trend_dir > 0:
            long_trigger = levels.swing_high + breakout_buffer
            if current_close > long_trigger and prev_close <= long_trigger:
                if not self._trend_ema_allows(values, volatility, "long"):
                    return None
                return "long"
        if levels.swing_low is not None and trend_dir < 0:
            short_trigger = levels.swing_low - breakout_buffer
            if current_close < short_trigger and prev_close >= short_trigger:
                if not self._trend_ema_allows(values, volatility, "short"):
                    return None
                return "short"
        return None

    def _trend_ema_allows(self, values: List[float], volatility: float, side: str) -> bool:
        if self.trend_ema_window <= 0:
            return True
        if len(values) < self.trend_ema_window + self.trend_ema_slope_bars:
            return False
        current_ema = ema(values, self.trend_ema_window)
        past_ema = ema(values[:-self.trend_ema_slope_bars], self.trend_ema_window)
        if current_ema is None or past_ema is None or volatility <= 0:
            return False
        slope = (current_ema - past_ema) / (volatility * self.trend_ema_slope_bars)
        current_close = float(values[-1])
        if side == "long":
            return current_close > current_ema and slope >= self.min_trend_ema_slope_atr
        return current_close < current_ema and slope <= -self.min_trend_ema_slope_atr

    async def _manage_existing_positions(
        self,
        symbol: str,
        bar: BarData,
        volatility: float,
        signal: Optional[str],
    ) -> bool:
        closed = False
        for side in ("long", "short"):
            position = await self.get_contract_position(symbol, side)
            key = (symbol, side)
            if not position:
                self._position_state.pop(key, None)
                continue

            state = self._state_for_position(key, position, side, bar, volatility)
            stop = self._update_trailing_stop(symbol, side, state, bar, volatility)
            if side == "long":
                should_stop = float(bar.low) <= stop
                should_reverse = self.reversal_exit and signal == "short"
            else:
                should_stop = float(bar.high) >= stop
                should_reverse = self.reversal_exit and signal == "long"

            if should_stop or should_reverse:
                close_price = stop if should_stop else float(bar.close)
                result = await self._close_if_present(symbol, side, close_price)
                if self._accepted(result):
                    self._position_state.pop(key, None)
                    self._start_cooldown(symbol)
                    closed = True
        return closed

    def _start_cooldown(self, symbol: str) -> None:
        if self.cooldown_bars <= 0:
            return
        self._cooldown_until_bar[symbol] = int(self._bar_counts.get(symbol, 0)) + self.cooldown_bars

    def _entry_is_in_cooldown(self, symbol: str) -> bool:
        return int(self._bar_counts.get(symbol, 0)) <= int(self._cooldown_until_bar.get(symbol, 0))

    def _update_trailing_stop(
        self,
        symbol: str,
        side: str,
        state: Dict[str, float],
        bar: BarData,
        volatility: float,
    ) -> float:
        hold_bars = max(0, int(self._bar_counts.get(symbol, 0)) - int(state.get("opened_bar", 0)))
        mult = self._dynamic_trailing_mult(hold_bars)
        if side == "long":
            state["extreme_price"] = max(float(state.get("extreme_price") or bar.high), float(bar.high))
            candidate = state["extreme_price"] - self._stop_distance(state["extreme_price"], volatility, mult)
            state["trail_stop"] = max(float(state.get("trail_stop", -float("inf"))), candidate)
        else:
            state["extreme_price"] = min(float(state.get("extreme_price") or bar.low), float(bar.low))
            candidate = state["extreme_price"] + self._stop_distance(state["extreme_price"], volatility, mult)
            state["trail_stop"] = min(float(state.get("trail_stop", float("inf"))), candidate)
        return float(state["trail_stop"])

    def _state_for_position(
        self,
        key: tuple[str, str],
        position: Dict[str, Any],
        side: str,
        bar: BarData,
        volatility: float,
    ) -> Dict[str, float]:
        existing = self._position_state.get(key)
        if existing:
            return existing
        entry = self._position_entry_price(position) or float(bar.close)
        state = self._new_position_state(
            symbol=key[0],
            side=side,
            entry_price=entry,
            bar=bar,
            volatility=volatility,
        )
        self._position_state[key] = state
        return state

    def _new_position_state(
        self,
        *,
        symbol: str,
        side: str,
        entry_price: float,
        bar: BarData,
        volatility: float,
    ) -> Dict[str, float]:
        opened_bar = int(self._bar_counts.get(symbol, 0))
        mult = self.initial_trailing_atr_mult
        if side == "short":
            extreme = min(float(entry_price), float(bar.low))
            trail = extreme + self._stop_distance(entry_price, volatility, mult)
        else:
            extreme = max(float(entry_price), float(bar.high))
            trail = extreme - self._stop_distance(entry_price, volatility, mult)
        return {
            "entry_price": float(entry_price),
            "opened_bar": float(opened_bar),
            "extreme_price": float(extreme),
            "trail_stop": float(trail),
        }

    def _dynamic_trailing_mult(self, hold_bars: int) -> float:
        if self.trailing_relax_bars <= 0:
            return self.max_trailing_atr_mult
        progress = min(1.0, max(0.0, float(hold_bars) / float(self.trailing_relax_bars)))
        return self.initial_trailing_atr_mult + (self.max_trailing_atr_mult - self.initial_trailing_atr_mult) * progress

    def _stop_distance(self, price: float, volatility: float, atr_mult: float) -> float:
        atr_distance = max(0.0, float(volatility)) * max(0.1, float(atr_mult))
        floor_distance = max(0.0, float(price)) * self.min_stop_pct
        return max(atr_distance, floor_distance)

    def _warmup_required(self) -> int:
        swing_required = self.swing_lookback_bars + self.swing_confirm_bars + 2
        trend_required = self.trend_ema_window + self.trend_ema_slope_bars if self.trend_ema_window > 0 else 0
        return max(swing_required, self.efficiency_window + 1, self.atr_window + 1, trend_required)

    async def _has_symbol_position(self, symbol: str) -> bool:
        return bool(await self.get_contract_position(symbol, "long") or await self.get_contract_position(symbol, "short"))

    def _configured_symbols(self) -> List[str]:
        configured = self.config.get("trade_symbols") or self.config.get("symbols") or self.state.symbols
        return [normalize_contract_symbol(str(symbol)) for symbol in configured if str(symbol).strip()]

    @staticmethod
    def _normalized_bar(bar: BarData, symbol: str) -> BarData:
        return BarData(
            exchange=bar.exchange,
            symbol=symbol,
            timeframe=bar.timeframe,
            timestamp=bar.timestamp,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
        )

    @staticmethod
    def _accepted(result: Dict[str, Any]) -> bool:
        return str(result.get("status") or "").lower() in {"filled", "submitted", "accepted"}

    @staticmethod
    def _position_entry_price(position: Dict[str, Any]) -> float:
        for key in ("entry_price", "avg_price", "avgPx", "mark_price", "markPrice", "price"):
            try:
                value = float(position.get(key) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if math.isfinite(value) and value > 0:
                return value
        return 0.0
