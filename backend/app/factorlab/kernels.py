"""Stateful OHLCV kernels shared by FactorLab batch and streaming paths."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Mapping, Optional

from app.factorlab.parameters import required_bars_for


Bar = Mapping[str, Any]


class UnknownFactorKernelError(KeyError):
    """Raised when a definition references a non-allowlisted kernel."""


class FactorKernel:
    name: str

    def required_bars(self, parameters: Mapping[str, Any]) -> int:
        return required_bars_for(self.name, parameters)

    def init_state(self, parameters: Mapping[str, Any]):
        raise NotImplementedError

    def update(self, state, confirmed_bar: Bar, parameters: Mapping[str, Any]) -> Optional[float]:
        raise NotImplementedError

    def compute_batch(self, bars: list[Bar], parameters: Mapping[str, Any]) -> list[Optional[float]]:
        state = self.init_state(parameters)
        return [self.update(state, bar, parameters) for bar in bars]


@dataclass
class _EMAState:
    period: int
    count: int = 0
    seed_sum: float = 0.0
    value: Optional[float] = None

    def update(self, price: float) -> Optional[float]:
        self.count += 1
        if self.value is None:
            self.seed_sum += price
            if self.count < self.period:
                return None
            self.value = self.seed_sum / self.period
            return self.value
        alpha = 2.0 / (self.period + 1.0)
        self.value = alpha * price + (1.0 - alpha) * self.value
        return self.value


@dataclass
class _ATRState:
    period: int
    count: int = 0
    seed_sum: float = 0.0
    value: Optional[float] = None
    previous_close: Optional[float] = None

    def update(self, high: float, low: float, close: float) -> Optional[float]:
        if self.previous_close is None:
            true_range = high - low
        else:
            true_range = max(
                high - low,
                abs(high - self.previous_close),
                abs(low - self.previous_close),
            )
        self.previous_close = close
        self.count += 1
        if self.value is None:
            self.seed_sum += true_range
            if self.count < self.period:
                return None
            self.value = self.seed_sum / self.period
            return self.value
        self.value = (self.value * (self.period - 1) + true_range) / self.period
        return self.value


@dataclass
class _ATRPercentState:
    atr: _ATRState


class ATRPercentKernel(FactorKernel):
    name = "atr_pct"

    def init_state(self, parameters: Mapping[str, Any]) -> _ATRPercentState:
        return _ATRPercentState(atr=_ATRState(int(parameters["window"])))

    def update(
        self,
        state: _ATRPercentState,
        confirmed_bar: Bar,
        parameters: Mapping[str, Any],
    ) -> Optional[float]:
        close = float(confirmed_bar["close"])
        atr = state.atr.update(
            float(confirmed_bar["high"]),
            float(confirmed_bar["low"]),
            close,
        )
        if atr is None or close <= 0:
            return None
        return atr / close * 100.0


@dataclass
class _EfficiencyRatioState:
    closes: deque[float]


class EfficiencyRatioKernel(FactorKernel):
    name = "efficiency_ratio"

    def init_state(self, parameters: Mapping[str, Any]) -> _EfficiencyRatioState:
        window = int(parameters["window"])
        return _EfficiencyRatioState(closes=deque(maxlen=window + 1))

    def update(
        self,
        state: _EfficiencyRatioState,
        confirmed_bar: Bar,
        parameters: Mapping[str, Any],
    ) -> Optional[float]:
        state.closes.append(float(confirmed_bar["close"]))
        if len(state.closes) < state.closes.maxlen:
            return None
        values = list(state.closes)
        path_length = sum(abs(current - previous) for previous, current in zip(values, values[1:]))
        if path_length <= 0:
            return 0.0
        return abs(values[-1] - values[0]) / path_length


@dataclass
class _EMAGapATRState:
    fast: _EMAState
    slow: _EMAState
    atr: _ATRState


class EMAGapATRKernel(FactorKernel):
    name = "ema_gap_atr"

    def init_state(self, parameters: Mapping[str, Any]) -> _EMAGapATRState:
        return _EMAGapATRState(
            fast=_EMAState(int(parameters["fast"])),
            slow=_EMAState(int(parameters["slow"])),
            atr=_ATRState(int(parameters["atr_window"])),
        )

    def update(
        self,
        state: _EMAGapATRState,
        confirmed_bar: Bar,
        parameters: Mapping[str, Any],
    ) -> Optional[float]:
        close = float(confirmed_bar["close"])
        fast = state.fast.update(close)
        slow = state.slow.update(close)
        atr = state.atr.update(
            float(confirmed_bar["high"]),
            float(confirmed_bar["low"]),
            close,
        )
        if fast is None or slow is None or atr is None or atr <= 0:
            return None
        return (fast - slow) / atr


@dataclass
class _PriceEMACrossState:
    ema: _EMAState
    signs: deque[int]


class PriceEMACrossCountKernel(FactorKernel):
    name = "price_ema_cross_count"

    def init_state(self, parameters: Mapping[str, Any]) -> _PriceEMACrossState:
        return _PriceEMACrossState(
            ema=_EMAState(int(parameters["ema_window"])),
            signs=deque(maxlen=int(parameters["window"])),
        )

    def update(
        self,
        state: _PriceEMACrossState,
        confirmed_bar: Bar,
        parameters: Mapping[str, Any],
    ) -> Optional[float]:
        close = float(confirmed_bar["close"])
        ema = state.ema.update(close)
        if ema is None:
            return None
        difference = close - ema
        sign = 1 if difference > 0 else -1 if difference < 0 else 0
        state.signs.append(sign)
        if len(state.signs) < state.signs.maxlen:
            return None
        nonzero = [item for item in state.signs if item]
        return float(sum(previous != current for previous, current in zip(nonzero, nonzero[1:])))


@dataclass
class _ADXState:
    period: int
    bar_index: int = -1
    previous_high: Optional[float] = None
    previous_low: Optional[float] = None
    previous_close: Optional[float] = None
    true_ranges: list[float] = field(default_factory=list)
    plus_moves: list[float] = field(default_factory=list)
    minus_moves: list[float] = field(default_factory=list)
    smoothed_tr: Optional[float] = None
    smoothed_plus: Optional[float] = None
    smoothed_minus: Optional[float] = None
    dx_values: list[float] = field(default_factory=list)
    adx: Optional[float] = None


class ADXKernel(FactorKernel):
    name = "adx"

    def init_state(self, parameters: Mapping[str, Any]) -> _ADXState:
        return _ADXState(period=int(parameters["window"]))

    def update(
        self,
        state: _ADXState,
        confirmed_bar: Bar,
        parameters: Mapping[str, Any],
    ) -> Optional[float]:
        high = float(confirmed_bar["high"])
        low = float(confirmed_bar["low"])
        close = float(confirmed_bar["close"])
        state.bar_index += 1
        if state.previous_close is None:
            state.previous_high = high
            state.previous_low = low
            state.previous_close = close
            return None

        true_range = max(
            high - low,
            abs(high - state.previous_close),
            abs(low - state.previous_close),
        )
        upward_move = high - float(state.previous_high)
        downward_move = float(state.previous_low) - low
        plus_move = upward_move if upward_move > downward_move and upward_move > 0 else 0.0
        minus_move = downward_move if downward_move > upward_move and downward_move > 0 else 0.0
        state.previous_high = high
        state.previous_low = low
        state.previous_close = close

        if state.bar_index <= state.period:
            state.true_ranges.append(true_range)
            state.plus_moves.append(plus_move)
            state.minus_moves.append(minus_move)
            if state.bar_index < state.period:
                return None
            state.smoothed_tr = sum(state.true_ranges)
            state.smoothed_plus = sum(state.plus_moves)
            state.smoothed_minus = sum(state.minus_moves)
        else:
            state.smoothed_tr = float(state.smoothed_tr) - float(state.smoothed_tr) / state.period + true_range
            state.smoothed_plus = (
                float(state.smoothed_plus) - float(state.smoothed_plus) / state.period + plus_move
            )
            state.smoothed_minus = (
                float(state.smoothed_minus) - float(state.smoothed_minus) / state.period + minus_move
            )

        if not state.smoothed_tr or state.smoothed_tr <= 0:
            dx = 0.0
        else:
            plus_di = 100.0 * float(state.smoothed_plus) / state.smoothed_tr
            minus_di = 100.0 * float(state.smoothed_minus) / state.smoothed_tr
            directional_sum = plus_di + minus_di
            dx = 0.0 if directional_sum <= 0 else 100.0 * abs(plus_di - minus_di) / directional_sum
        state.dx_values.append(dx)

        first_adx_index = 2 * state.period
        if state.bar_index < first_adx_index:
            return None
        if state.adx is None:
            state.adx = sum(state.dx_values) / len(state.dx_values)
        else:
            state.adx = (state.adx * (state.period - 1) + dx) / state.period
        return state.adx if isfinite(state.adx) else None


_KERNELS: dict[str, FactorKernel] = {
    kernel.name: kernel
    for kernel in (
        ATRPercentKernel(),
        EfficiencyRatioKernel(),
        EMAGapATRKernel(),
        PriceEMACrossCountKernel(),
        ADXKernel(),
    )
}


def get_factor_kernel(name: str) -> FactorKernel:
    try:
        return _KERNELS[name]
    except KeyError as exc:
        raise UnknownFactorKernelError(f"unknown factor kernel: {name}") from exc
