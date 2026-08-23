"""OKX USDT perpetual Donchian breakout with EMA and ADX confirmation."""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from app.core.execution.base_strategy import BarData
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price
from app.strategies.exit_rules import ExitContext, ExitPolicyConfig, ExitPositionState, evaluate_exit


_TIMEFRAME_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


class ContractDonchianEmaAdxStrategy(ContractStrategyBase):
    async def on_init(self) -> None:
        await super().on_init()
        self.lookback_bars = max(2, int(self.config.get("lookback_bars", 55)))
        self.ema_window = max(2, int(self.config.get("ema_window", 144)))
        self.atr_window = max(1, int(self.config.get("atr_window", 14)))
        self.adx_window = max(1, int(self.config.get("adx_window", 14)))
        self.min_adx = max(0.0, float(self.config.get("min_adx", 8.0)))
        self.atr_stop_mult = max(0.0, float(self.config.get("atr_stop_mult", 3.5)))
        self.take_profit_atr_mult = max(0.0, float(self.config.get("take_profit_atr_mult", 0.0)))
        self.min_stop_pct = max(0.0, float(self.config.get("min_stop_pct", 0.02)))
        self.min_holding_bars = max(0, int(self.config.get("min_holding_bars", 1)))
        self.max_holding_bars = max(self.min_holding_bars + 1, int(self.config.get("max_holding_bars", 30)))
        self.ema_soft_exit = bool(self.config.get("ema_soft_exit", True))
        self.reversal_exit = bool(self.config.get("reversal_exit", True))
        self._entry_price: Dict[tuple[str, str], float] = {}
        self._trail_stop: Dict[tuple[str, str], float] = {}
        self._opened_bar: Dict[tuple[str, str], int] = {}
        self.profit_protection_enabled = bool(self.config.get("profit_protection_enabled", False))
        self.profit_initial_risk_pct = max(0.0, float(self.config.get("profit_initial_risk_pct", 0.0)))
        self.exit_policy = self._build_exit_policy()
        self._exit_states: Dict[tuple[str, str], ExitPositionState] = {}

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return
        bars = self._append_bar(bar)
        if len(bars) < self._warmup_required():
            return

        price = float(bar.close)
        trend_ema = ema(closes(bars), self.ema_window)
        volatility = atr(bars, self.atr_window) or 0.0
        if trend_ema is None or volatility <= 0:
            return

        long_pos = await self.get_contract_position(bar.symbol, "long")
        short_pos = await self.get_contract_position(bar.symbol, "short")
        signal = self._signal(bars, price, trend_ema)

        if long_pos:
            if self._should_close(bar.symbol, "long", long_pos, price, trend_ema, volatility, signal, bars):
                await self._close_and_reset(bar.symbol, "long", price)
            return
        if short_pos:
            if self._should_close(bar.symbol, "short", short_pos, price, trend_ema, volatility, signal, bars):
                await self._close_and_reset(bar.symbol, "short", price)
            return

        if signal == "long":
            result = await self._open_if_flat(bar.symbol, "long", price)
            self._track_open(bar.symbol, "long", price, result)
        elif signal == "short":
            result = await self._open_if_flat(bar.symbol, "short", price)
            self._track_open(bar.symbol, "short", price, result)

    def _warmup_required(self) -> int:
        adx_required = self.adx_window * 2 + 1 if self.min_adx > 0 else 0
        return max(self.lookback_bars + 1, self.ema_window, self.atr_window + 1, adx_required)

    def _signal(self, bars: List[BarData], price: float, trend_ema: float) -> Optional[str]:
        if self.min_adx > 0:
            adx_value = self._adx(bars, self.adx_window)
            if adx_value is None or adx_value < self.min_adx:
                return None

        prev_channel = bars[-self.lookback_bars - 1:-1]
        if len(prev_channel) < self.lookback_bars:
            return None
        channel_high = max(float(item.high) for item in prev_channel)
        channel_low = min(float(item.low) for item in prev_channel)
        if price > channel_high and price > trend_ema:
            return "long"
        if price < channel_low and price < trend_ema:
            return "short"
        return None

    def _should_close(
        self,
        symbol: str,
        side: str,
        position: dict,
        price: float,
        trend_ema: float,
        volatility: float,
        signal: Optional[str],
        bars: List[BarData],
    ) -> bool:
        key = (symbol, side)
        if not self._restore_open_position_state(symbol, side, position, bars):
            return False
        self._opened_bar.setdefault(key, self._bar_counts.get(symbol, 0))
        holding_bars = max(0, int(self._bar_counts.get(symbol, 0)) - int(self._opened_bar[key]))
        entry = self._entry_price.get(key) or self._position_entry_price(position) or price
        current_bar = bars[-1] if bars else None
        state = self._exit_state_for_position(key, symbol, side, position, entry, price, volatility)
        context = ExitContext(
            symbol=symbol,
            side=side,
            price=price,
            high=float(current_bar.high) if current_bar is not None else price,
            low=float(current_bar.low) if current_bar is not None else price,
            volatility=volatility,
            bar_count=int(self._bar_counts.get(symbol, 0)),
            trigger_mode=self.exit_policy.trigger_mode,
        )
        new_state, decision = evaluate_exit(context, state, self.exit_policy)
        self._exit_states[key] = new_state
        if new_state.trailing_stop is not None:
            self._trail_stop[key] = new_state.trailing_stop
        if decision.should_close:
            return True

        if side == "long":
            if self.take_profit_atr_mult > 0 and price >= entry + volatility * self.take_profit_atr_mult:
                return True
            if holding_bars >= self.min_holding_bars and self.reversal_exit and signal == "short":
                return True
            if holding_bars >= self.min_holding_bars and self.ema_soft_exit and price < trend_ema:
                return True
        else:
            if self.take_profit_atr_mult > 0 and price <= entry - volatility * self.take_profit_atr_mult:
                return True
            if holding_bars >= self.min_holding_bars and self.reversal_exit and signal == "long":
                return True
            if holding_bars >= self.min_holding_bars and self.ema_soft_exit and price > trend_ema:
                return True
        return False

    def _track_open(self, symbol: str, side: str, price: float, result) -> None:
        status = str(result.get("status") or "").lower()
        if status not in {"filled", "submitted", "accepted"}:
            return
        key = (symbol, side)
        self._trail_stop.pop(key, None)
        self._entry_price.pop(key, None)
        self._opened_bar.pop(key, None)
        self._exit_states.pop(key, None)
        if status == "filled":
            self._entry_price[key] = price
            self._opened_bar[key] = int(self._bar_counts.get(symbol, 0))

    async def _close_and_reset(self, symbol: str, side: str, price: float) -> None:
        result = await self._close_if_present(symbol, side, price)
        if str(result.get("status") or "").lower() not in {"filled", "submitted", "accepted"}:
            return
        key = (symbol, side)
        self._entry_price.pop(key, None)
        self._opened_bar.pop(key, None)
        self._trail_stop.pop(key, None)
        self._exit_states.pop(key, None)

    def _restore_open_position_state(self, symbol: str, side: str, position: dict, bars: List[BarData]) -> bool:
        key = (symbol, side)
        if key in self._opened_bar:
            entry = self._position_entry_price(position)
            if entry > 0 and key not in self._entry_price:
                self._entry_price[key] = entry
            return True

        opened_bar_ts = self._position_timestamp(position, ("opened_bar_timestamp", "signal_bar_timestamp"))
        opened_at = self._position_timestamp(position, ("opened_at", "opened_timestamp", "open_timestamp"))
        if opened_bar_ts is None and opened_at is None:
            return True

        open_index = self._open_bar_index(bars, opened_bar_ts, opened_at)
        if open_index is None:
            return False

        current_index = len(bars) - 1
        current_count = int(self._bar_counts.get(symbol, 0))
        opened_count = current_count - max(0, current_index - open_index)
        if key not in self._opened_bar:
            self._opened_bar[key] = max(0, opened_count)

        entry = self._position_entry_price(position)
        if entry > 0 and key not in self._entry_price:
            self._entry_price[key] = entry

        if current_index <= open_index:
            return False

        if key not in self._trail_stop:
            self._replay_trailing_stop(key, side, bars, open_index, current_index)
        return True

    def _open_bar_index(
        self,
        bars: List[BarData],
        opened_bar_ts: Optional[int],
        opened_at: Optional[int],
    ) -> Optional[int]:
        if not bars:
            return None

        if opened_bar_ts is not None:
            if int(bars[-1].timestamp) < opened_bar_ts:
                return None
            for idx, bar in enumerate(bars):
                if int(bar.timestamp) >= opened_bar_ts:
                    return idx
            return 0

        if opened_at is None:
            return None

        interval_ms = self._bar_interval_ms(bars)
        tolerance_ms = max(1_000, min(60_000, interval_ms // 20))
        closed_index: Optional[int] = None
        for idx, bar in enumerate(bars):
            bar_close_ts = int(bar.timestamp) + interval_ms
            if bar_close_ts <= opened_at + tolerance_ms:
                closed_index = idx
        if closed_index is not None:
            return closed_index
        if int(bars[0].timestamp) > opened_at:
            return 0
        return None

    def _replay_trailing_stop(
        self,
        key: tuple[str, str],
        side: str,
        bars: List[BarData],
        open_index: int,
        current_index: int,
    ) -> None:
        for idx in range(open_index + 1, current_index):
            price = float(bars[idx].close)
            volatility = atr(bars[: idx + 1], self.atr_window) or 0.0
            if volatility <= 0:
                continue
            stop_distance = max(volatility * self.atr_stop_mult, price * self.min_stop_pct)
            if side == "long":
                self._trail_stop[key] = max(self._trail_stop.get(key, -float("inf")), price - stop_distance)
            else:
                self._trail_stop[key] = min(self._trail_stop.get(key, float("inf")), price + stop_distance)

    def _build_exit_policy(self) -> ExitPolicyConfig:
        return ExitPolicyConfig(
            atr_stop_mult=self.atr_stop_mult,
            min_stop_pct=self.min_stop_pct,
            max_holding_bars=self.max_holding_bars,
            min_holding_bars=self.min_holding_bars,
            break_even_at_r=self._profit_value("break_even_at_r", 0.0),
            break_even_buffer_bps=self._profit_value("break_even_buffer_bps", 0.0),
            profit_atr_trailing_start_r=self._profit_value("profit_atr_trailing_start_r", 0.0),
            profit_atr_stop_mult=self._profit_value("profit_atr_stop_mult", 0.0),
            profit_trailing_start_r=self._profit_value("profit_trailing_start_r", 0.0),
            profit_peak_pullback_pct=self._profit_value("profit_peak_pullback_pct", 0.0),
            profit_tighten_at_r=self._profit_value("profit_tighten_at_r", 0.0),
            profit_tight_pullback_pct=self._profit_value("profit_tight_pullback_pct", 0.0),
            profit_floor_start_bps=self._profit_value("profit_floor_start_bps", 0.0),
            profit_floor_bps=self._profit_value("profit_floor_bps", 0.0),
            max_profit_hold_bars=int(self._profit_value("max_profit_hold_bars", 0.0)),
            profit_decay_exit_pct=self._profit_value("profit_decay_exit_pct", 0.0),
            trigger_mode=str(self.config.get("exit_trigger_mode") or "close"),
        )

    def _profit_value(self, key: str, default: float) -> float:
        if (
            not self.profit_protection_enabled
            and (key.startswith("profit_") or key.startswith("break_even") or key.startswith("max_profit"))
        ):
            return 0.0
        try:
            return max(0.0, float(self.config.get(key, default)))
        except (TypeError, ValueError):
            return max(0.0, float(default))

    def _exit_state_for_position(
        self,
        key: tuple[str, str],
        symbol: str,
        side: str,
        position: dict,
        entry: float,
        price: float,
        volatility: float,
    ) -> ExitPositionState:
        state = self._exit_states.get(key)
        if state is not None:
            return state
        opened_bar = int(self._opened_bar.get(key, self._bar_counts.get(symbol, 0)))
        initial_risk = self._initial_exit_risk(key, entry, price, volatility)
        trailing_stop = self._trail_stop.get(key)
        return ExitPositionState(
            symbol=symbol,
            side=side,
            entry_price=entry or self._position_entry_price(position) or price,
            opened_bar=opened_bar,
            highest_price=entry or price,
            lowest_price=entry or price,
            initial_risk=initial_risk,
            trailing_stop=trailing_stop,
        )

    def _initial_exit_risk(self, key: tuple[str, str], entry: float, price: float, volatility: float) -> float:
        if entry > 0 and self.profit_initial_risk_pct > 0:
            return entry * self.profit_initial_risk_pct
        trailing_stop = self._trail_stop.get(key)
        if entry > 0 and trailing_stop is not None and math.isfinite(trailing_stop):
            risk = abs(entry - float(trailing_stop))
            if risk > 0:
                return risk
        return max(volatility * self.atr_stop_mult, price * self.min_stop_pct)

    def _position_timestamp(self, position: dict, keys: tuple[str, ...]) -> Optional[int]:
        for key in keys:
            try:
                value = float(position.get(key) or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0 and math.isfinite(value):
                return int(value)
        return None

    def _bar_interval_ms(self, bars: List[BarData]) -> int:
        for prev, cur in zip(reversed(bars[:-1]), reversed(bars[1:])):
            diff = int(cur.timestamp) - int(prev.timestamp)
            if diff > 0:
                return diff
        if bars:
            return _TIMEFRAME_MS.get(str(bars[-1].timeframe), 60_000)
        return 60_000

    def _position_entry_price(self, position: dict) -> float:
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
