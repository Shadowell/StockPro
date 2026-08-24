"""OKX USDT perpetual volatility-compression breakout strategy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean
from typing import Any, Dict, List, Optional

from app.core.execution.base_strategy import BarData
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price


@dataclass(frozen=True)
class BreakoutChannel:
    high: Optional[float] = None
    low: Optional[float] = None


@dataclass(frozen=True)
class BreakoutSignal:
    side: str
    level: float
    volatility: float
    compression_ratio: float
    volume_ratio: Optional[float] = None


def previous_breakout_channel(bars: List[BarData], *, lookback_bars: int) -> BreakoutChannel:
    """Return the previous high/low channel, excluding the current signal bar."""
    lookback = max(1, int(lookback_bars))
    if len(bars) < lookback + 1:
        return BreakoutChannel()
    sample = bars[-lookback - 1:-1]
    if not sample:
        return BreakoutChannel()
    return BreakoutChannel(
        high=max(float(bar.high) for bar in sample),
        low=min(float(bar.low) for bar in sample),
    )


def atr_compression_ratio(
    bars: List[BarData],
    *,
    compression_window: int,
    baseline_window: int,
) -> Optional[float]:
    short_atr = atr(bars, max(1, int(compression_window)))
    baseline_atr = atr(bars, max(1, int(baseline_window)))
    if short_atr is None or baseline_atr is None or baseline_atr <= 1e-12:
        return None
    return short_atr / baseline_atr


class ContractVolatilityCompressionBreakoutStrategy(ContractStrategyBase):
    """Paper-only CTA that waits for a volatility squeeze before 4H breakout entries."""

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}
        self.trade_symbols = tuple(dict.fromkeys(self._configured_symbols()))
        self.max_positions = max(1, int(cfg.get("max_positions", 1)))
        self.compression_window = max(1, int(cfg.get("compression_window", 12)))
        self.compression_baseline_window = max(
            self.compression_window + 1,
            int(cfg.get("compression_baseline_window", 60)),
        )
        self.max_compression_atr_ratio = max(0.01, float(cfg.get("max_compression_atr_ratio", 0.55)))
        self.breakout_lookback_bars = max(1, int(cfg.get("breakout_lookback_bars", 18)))
        self.atr_window = max(1, int(cfg.get("atr_window", 14)))
        self.breakout_atr_buffer = max(0.0, float(cfg.get("breakout_atr_buffer", 0.15)))
        self.max_breakout_extension_atr = max(0.0, float(cfg.get("max_breakout_extension_atr", 4.0)))
        self.require_volume_confirmation = bool(cfg.get("require_volume_confirmation", True))
        self.volume_window = max(1, int(cfg.get("volume_window", 12)))
        self.min_volume_ratio = max(0.0, float(cfg.get("min_volume_ratio", 1.15)))
        self.trend_ema_window = max(0, int(cfg.get("trend_ema_window", 34)))
        self.trend_ema_slope_bars = max(1, int(cfg.get("trend_ema_slope_bars", 3)))
        self.min_trend_ema_slope_atr = float(cfg.get("min_trend_ema_slope_atr", 0.0))
        self.initial_stop_atr_mult = max(0.1, float(cfg.get("initial_stop_atr_mult", 1.8)))
        self.trailing_atr_mult = max(0.1, float(cfg.get("trailing_atr_mult", 2.2)))
        self.min_stop_pct = max(0.0, float(cfg.get("min_stop_pct", 0.01)))
        self.failed_breakout_exit_bars = max(0, int(cfg.get("failed_breakout_exit_bars", 3)))
        self.failure_buffer_atr = max(0.0, float(cfg.get("failure_buffer_atr", 0.1)))
        self.max_holding_bars = max(0, int(cfg.get("max_holding_bars", 42)))
        self.cooldown_bars = max(0, int(cfg.get("cooldown_bars", 6)))
        self.reversal_exit = bool(cfg.get("reversal_exit", True))
        self.reversal_reentry_enabled = bool(cfg.get("reversal_reentry_enabled", False))
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

        signal = self._entry_signal(bars)
        volatility = signal.volatility if signal else self._fallback_volatility(bars)
        closed = await self._manage_existing_positions(symbol, norm_bar, volatility, signal)
        if closed and not self.reversal_reentry_enabled:
            return
        if await self._has_symbol_position(symbol):
            return
        if self._entry_is_in_cooldown(symbol):
            return
        if signal is None:
            return
        if await self._portfolio_position_count() >= self.max_positions:
            return

        result = await self._open_if_flat(symbol, signal.side, float(norm_bar.close))
        if self._accepted(result):
            self._position_state[(symbol, signal.side)] = self._new_position_state(
                symbol=symbol,
                side=signal.side,
                entry_price=float(norm_bar.close),
                bar=norm_bar,
                signal=signal,
            )

    def _entry_signal(self, bars: List[BarData]) -> Optional[BreakoutSignal]:
        if len(bars) < 2:
            return None
        history = bars[:-1]
        ratio = atr_compression_ratio(
            history,
            compression_window=self.compression_window,
            baseline_window=self.compression_baseline_window,
        )
        if ratio is None or ratio > self.max_compression_atr_ratio:
            return None

        volatility = atr(history, self.atr_window)
        if volatility is None or volatility <= 0:
            return None

        channel = previous_breakout_channel(bars, lookback_bars=self.breakout_lookback_bars)
        if channel.high is None or channel.low is None:
            return None

        volume_ratio = self._volume_ratio(history, bars[-1])
        if self.require_volume_confirmation and (volume_ratio is None or volume_ratio < self.min_volume_ratio):
            return None

        current_close = float(bars[-1].close)
        prev_close = float(bars[-2].close)
        buffer = self.breakout_atr_buffer * volatility
        long_level = float(channel.high) + buffer
        short_level = float(channel.low) - buffer

        if current_close > long_level and prev_close <= long_level:
            if not self._trend_ema_allows(closes(bars), volatility, "long"):
                return None
            if self._too_extended(current_close, long_level, volatility):
                return None
            return BreakoutSignal("long", long_level, volatility, ratio, volume_ratio)

        if current_close < short_level and prev_close >= short_level:
            if not self._trend_ema_allows(closes(bars), volatility, "short"):
                return None
            if self._too_extended(current_close, short_level, volatility):
                return None
            return BreakoutSignal("short", short_level, volatility, ratio, volume_ratio)

        return None

    def _fallback_volatility(self, bars: List[BarData]) -> float:
        if len(bars) < 2:
            return 0.0
        volatility = atr(bars, self.atr_window)
        if volatility is None:
            volatility = atr(bars, min(max(1, len(bars) - 1), self.atr_window))
        return float(volatility or 0.0)

    def _volume_ratio(self, history: List[BarData], current: BarData) -> Optional[float]:
        if len(history) < self.volume_window:
            return None
        baseline = mean(max(0.0, float(bar.volume)) for bar in history[-self.volume_window:])
        if baseline <= 1e-12:
            return None
        return max(0.0, float(current.volume)) / baseline

    def _trend_ema_allows(self, values: List[float], volatility: float, side: str) -> bool:
        if self.trend_ema_window <= 0:
            return True
        if len(values) < self.trend_ema_window + self.trend_ema_slope_bars:
            return False
        current_ema = ema(values, self.trend_ema_window)
        past_ema = ema(values[:-self.trend_ema_slope_bars], self.trend_ema_window)
        if current_ema is None or past_ema is None:
            return False
        current_close = float(values[-1])
        if volatility <= 0:
            slope = 0.0
        else:
            slope = (float(current_ema) - float(past_ema)) / (volatility * self.trend_ema_slope_bars)
        if side == "long":
            return current_close > current_ema and slope >= self.min_trend_ema_slope_atr
        return current_close < current_ema and slope <= -self.min_trend_ema_slope_atr

    def _too_extended(self, current_close: float, level: float, volatility: float) -> bool:
        if self.max_breakout_extension_atr <= 0 or volatility <= 0:
            return False
        return abs(current_close - level) > self.max_breakout_extension_atr * volatility

    async def _manage_existing_positions(
        self,
        symbol: str,
        bar: BarData,
        volatility: float,
        signal: Optional[BreakoutSignal],
    ) -> bool:
        closed = False
        for side in ("long", "short"):
            position = await self.get_contract_position(symbol, side)
            key = (symbol, side)
            if not position:
                self._position_state.pop(key, None)
                continue

            state = self._state_for_position(key, position, side, bar, signal)
            stop = self._update_trailing_stop(side, state, bar, volatility)
            hold_bars = max(0, int(self._bar_counts.get(symbol, 0)) - int(state.get("opened_bar", 0)))

            if side == "long":
                should_stop = float(bar.low) <= stop
                should_fail = self._failed_breakout(side, state, bar, volatility, hold_bars)
                should_reverse = self.reversal_exit and signal is not None and signal.side == "short"
            else:
                should_stop = float(bar.high) >= stop
                should_fail = self._failed_breakout(side, state, bar, volatility, hold_bars)
                should_reverse = self.reversal_exit and signal is not None and signal.side == "long"
            should_expire = self.max_holding_bars > 0 and hold_bars >= self.max_holding_bars

            if should_stop or should_fail or should_reverse or should_expire:
                close_price = stop if should_stop else float(bar.close)
                result = await self._close_if_present(symbol, side, close_price)
                if self._accepted(result):
                    self._position_state.pop(key, None)
                    self._start_cooldown(symbol)
                    closed = True
        return closed

    def _failed_breakout(
        self,
        side: str,
        state: Dict[str, float],
        bar: BarData,
        volatility: float,
        hold_bars: int,
    ) -> bool:
        if self.failed_breakout_exit_bars <= 0 or hold_bars < self.failed_breakout_exit_bars:
            return False
        level = float(state.get("breakout_level") or 0.0)
        if level <= 0:
            return False
        buffer = self.failure_buffer_atr * max(0.0, volatility)
        close = float(bar.close)
        if side == "long":
            return close < level - buffer
        return close > level + buffer

    def _state_for_position(
        self,
        key: tuple[str, str],
        position: Dict[str, Any],
        side: str,
        bar: BarData,
        signal: Optional[BreakoutSignal],
    ) -> Dict[str, float]:
        existing = self._position_state.get(key)
        if existing:
            return existing
        entry = self._position_entry_price(position) or float(bar.close)
        fallback_signal = signal or BreakoutSignal(side, entry, max(0.0, self._fallback_volatility([bar])), 1.0)
        state = self._new_position_state(
            symbol=key[0],
            side=side,
            entry_price=entry,
            bar=bar,
            signal=fallback_signal,
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
        signal: BreakoutSignal,
    ) -> Dict[str, float]:
        opened_bar = int(self._bar_counts.get(symbol, 0))
        stop_distance = self._stop_distance(entry_price, signal.volatility, self.initial_stop_atr_mult)
        if side == "short":
            extreme = min(float(entry_price), float(bar.low))
            trail = float(entry_price) + stop_distance
        else:
            extreme = max(float(entry_price), float(bar.high))
            trail = float(entry_price) - stop_distance
        return {
            "entry_price": float(entry_price),
            "opened_bar": float(opened_bar),
            "extreme_price": float(extreme),
            "trail_stop": float(trail),
            "breakout_level": float(signal.level),
            "atr_at_entry": float(signal.volatility),
            "compression_ratio": float(signal.compression_ratio),
        }

    def _update_trailing_stop(
        self,
        side: str,
        state: Dict[str, float],
        bar: BarData,
        volatility: float,
    ) -> float:
        effective_volatility = volatility if volatility > 0 else float(state.get("atr_at_entry") or 0.0)
        if side == "long":
            state["extreme_price"] = max(float(state.get("extreme_price") or bar.high), float(bar.high))
            candidate = state["extreme_price"] - self._stop_distance(
                state["extreme_price"],
                effective_volatility,
                self.trailing_atr_mult,
            )
            state["trail_stop"] = max(float(state.get("trail_stop", -float("inf"))), candidate)
        else:
            state["extreme_price"] = min(float(state.get("extreme_price") or bar.low), float(bar.low))
            candidate = state["extreme_price"] + self._stop_distance(
                state["extreme_price"],
                effective_volatility,
                self.trailing_atr_mult,
            )
            state["trail_stop"] = min(float(state.get("trail_stop", float("inf"))), candidate)
        return float(state["trail_stop"])

    def _stop_distance(self, price: float, volatility: float, atr_mult: float) -> float:
        atr_distance = max(0.0, float(volatility)) * max(0.1, float(atr_mult))
        floor_distance = max(0.0, float(price)) * self.min_stop_pct
        return max(atr_distance, floor_distance)

    def _start_cooldown(self, symbol: str) -> None:
        if self.cooldown_bars <= 0:
            return
        self._cooldown_until_bar[symbol] = int(self._bar_counts.get(symbol, 0)) + self.cooldown_bars

    def _entry_is_in_cooldown(self, symbol: str) -> bool:
        return int(self._bar_counts.get(symbol, 0)) <= int(self._cooldown_until_bar.get(symbol, 0))

    def _warmup_required(self) -> int:
        trend_required = self.trend_ema_window + self.trend_ema_slope_bars if self.trend_ema_window > 0 else 0
        return max(
            int(self.config.get("warmup_bars", 0) or 0),
            self.compression_baseline_window + 2,
            self.breakout_lookback_bars + 1,
            self.atr_window + 2,
            self.volume_window + 1 if self.require_volume_confirmation else 0,
            trend_required,
        )

    async def _has_symbol_position(self, symbol: str) -> bool:
        return bool(await self.get_contract_position(symbol, "long") or await self.get_contract_position(symbol, "short"))

    async def _portfolio_position_count(self) -> int:
        count = 0
        symbols = self.trade_symbols or tuple(self._bars.keys())
        for symbol in symbols:
            for side in ("long", "short"):
                if await self.get_contract_position(symbol, side):
                    count += 1
        return count

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
