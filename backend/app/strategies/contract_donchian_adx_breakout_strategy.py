"""OKX USDT perpetual Donchian/ADX breakout strategy.

This strategy is intentionally simple and causal: the Donchian channel is built
from fully confirmed bars before the current signal bar, then exits use ATR
state and EMA structure from confirmed OHLCV only.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from app.core.execution.base_strategy import BarData
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price


class ContractDonchianAdxBreakoutStrategy(ContractStrategyBase):
    """Paper-only single-symbol CTA breakout with ADX filter and ATR protection."""

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}
        self.trade_symbols = tuple(dict.fromkeys(self._configured_symbols()))
        self.lookback_bars = max(2, int(cfg.get("lookback_bars", 12)))
        self.atr_window = max(1, int(cfg.get("atr_window", 14)))
        self.adx_window = max(1, int(cfg.get("adx_window", 14)))
        self.min_adx = max(0.0, float(cfg.get("min_adx", 10.0)))
        self.breakout_atr_buffer = max(0.0, float(cfg.get("breakout_atr_buffer", 0.25)))
        self.atr_stop_mult = max(0.1, float(cfg.get("atr_stop_mult", 2.4)))
        self.trailing_atr_mult = max(0.1, float(cfg.get("trailing_atr_mult", 3.8)))
        self.exit_fast_ema = max(1, int(cfg.get("exit_fast_ema", 5)))
        self.exit_slow_ema = max(self.exit_fast_ema + 1, int(cfg.get("exit_slow_ema", 20)))
        self.min_holding_bars = max(0, int(cfg.get("min_holding_bars", 0)))
        self.max_holding_bars = max(self.min_holding_bars + 1, int(cfg.get("max_holding_bars", 96)))
        self.ema_soft_exit = bool(cfg.get("ema_soft_exit", True))
        self.reversal_exit = bool(cfg.get("reversal_exit", True))
        self.reversal_reentry_enabled = bool(cfg.get("reversal_reentry_enabled", False))
        self.cooldown_bars = max(0, int(cfg.get("cooldown_bars", 2)))
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
        if self.min_adx > 0:
            adx_value = self._adx(bars, self.adx_window)
            if adx_value is None or adx_value < self.min_adx:
                return None

        prev_channel = bars[-self.lookback_bars - 1:-1]
        if len(prev_channel) < self.lookback_bars:
            return None

        channel_high = max(float(item.high) for item in prev_channel)
        channel_low = min(float(item.low) for item in prev_channel)
        close = float(bars[-1].close)
        buffer = self.breakout_atr_buffer * volatility
        if close > channel_high + buffer:
            return "long"
        if close < channel_low - buffer:
            return "short"
        return None

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
            stop = self._update_trailing_stop(side, state, bar, volatility)
            should_stop = float(bar.low) <= stop if side == "long" else float(bar.high) >= stop
            should_reverse = self.reversal_exit and signal == ("short" if side == "long" else "long")
            should_ema_exit = self._ema_exit(symbol, side)
            should_max_hold = self._holding_bars(symbol, state) >= self.max_holding_bars

            if should_stop or should_reverse or should_ema_exit or should_max_hold:
                close_price = stop if should_stop else float(bar.close)
                result = await self._close_if_present(symbol, side, close_price)
                if self._accepted(result):
                    self._position_state.pop(key, None)
                    self._start_cooldown(symbol)
                    closed = True
        return closed

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
        if side == "long":
            trail = float(entry_price) - self.atr_stop_mult * volatility
            extreme = max(float(entry_price), float(bar.high))
        else:
            trail = float(entry_price) + self.atr_stop_mult * volatility
            extreme = min(float(entry_price), float(bar.low))
        return {
            "entry_price": float(entry_price),
            "opened_bar": float(opened_bar),
            "extreme_price": float(extreme),
            "trail_stop": float(trail),
        }

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

    def _update_trailing_stop(
        self,
        side: str,
        state: Dict[str, float],
        bar: BarData,
        volatility: float,
    ) -> float:
        if side == "long":
            state["extreme_price"] = max(float(state.get("extreme_price") or bar.high), float(bar.high))
            candidate = state["extreme_price"] - self.trailing_atr_mult * volatility
            state["trail_stop"] = max(float(state.get("trail_stop", -float("inf"))), candidate)
        else:
            state["extreme_price"] = min(float(state.get("extreme_price") or bar.low), float(bar.low))
            candidate = state["extreme_price"] + self.trailing_atr_mult * volatility
            state["trail_stop"] = min(float(state.get("trail_stop", float("inf"))), candidate)
        return float(state["trail_stop"])

    def _ema_exit(self, symbol: str, side: str) -> bool:
        if not self.ema_soft_exit:
            return False
        key = (symbol, side)
        state = self._position_state.get(key)
        if not state or self._holding_bars(symbol, state) < self.min_holding_bars:
            return False
        bars = list(self._bars.get(symbol) or [])
        values = closes(bars)
        fast = ema(values, self.exit_fast_ema)
        slow = ema(values, self.exit_slow_ema)
        if fast is None or slow is None:
            return False
        return fast < slow if side == "long" else fast > slow

    def _holding_bars(self, symbol: str, state: Dict[str, float]) -> int:
        return max(0, int(self._bar_counts.get(symbol, 0)) - int(state.get("opened_bar", 0)))

    def _start_cooldown(self, symbol: str) -> None:
        if self.cooldown_bars <= 0:
            return
        self._cooldown_until_bar[symbol] = int(self._bar_counts.get(symbol, 0)) + self.cooldown_bars

    def _entry_is_in_cooldown(self, symbol: str) -> bool:
        return int(self._bar_counts.get(symbol, 0)) <= int(self._cooldown_until_bar.get(symbol, 0))

    async def _has_symbol_position(self, symbol: str) -> bool:
        return bool(await self.get_contract_position(symbol, "long") or await self.get_contract_position(symbol, "short"))

    def _warmup_required(self) -> int:
        adx_required = self.adx_window * 2 + 1 if self.min_adx > 0 else 0
        return max(self.lookback_bars + 1, self.atr_window + 1, self.exit_slow_ema, adx_required)

    def _configured_symbols(self) -> List[str]:
        configured = self.config.get("trade_symbols") or self.config.get("symbols") or self.state.symbols
        return [normalize_contract_symbol(str(symbol)) for symbol in configured if str(symbol).strip()]

    def _position_entry_price(self, position: Dict[str, Any]) -> float:
        for key in ("entry_price", "avg_price", "avgPx", "mark_price"):
            try:
                value = float(position.get(key) or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 0.0

    def _adx(self, bars: List[BarData], window: int) -> Optional[float]:
        if window <= 0 or len(bars) < window * 2 + 1:
            return None
        plus_dm: List[float] = []
        minus_dm: List[float] = []
        true_ranges: List[float] = []
        recent = bars[-(window * 2 + 1):]
        for prev, cur in zip(recent[:-1], recent[1:]):
            up_move = float(cur.high) - float(prev.high)
            down_move = float(prev.low) - float(cur.low)
            plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
            minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
            true_ranges.append(
                max(
                    float(cur.high) - float(cur.low),
                    abs(float(cur.high) - float(prev.close)),
                    abs(float(cur.low) - float(prev.close)),
                )
            )
        dx_values: List[float] = []
        for idx in range(window, len(true_ranges) + 1):
            tr_sum = sum(true_ranges[idx - window:idx])
            if tr_sum <= 0 or not math.isfinite(tr_sum):
                continue
            plus_di = 100.0 * sum(plus_dm[idx - window:idx]) / tr_sum
            minus_di = 100.0 * sum(minus_dm[idx - window:idx]) / tr_sum
            denom = plus_di + minus_di
            if denom <= 0:
                continue
            dx_values.append(100.0 * abs(plus_di - minus_di) / denom)
        if not dx_values:
            return None
        return sum(dx_values[-window:]) / min(window, len(dx_values))

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
