"""Stateful OHLCV kernels shared by FactorLab batch and streaming paths."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import isfinite, sqrt
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


@dataclass
class _MACDHistATRState:
    fast: _EMAState
    slow: _EMAState
    signal: _EMAState
    atr: _ATRState


class MACDHistATRKernel(FactorKernel):
    name = "macd_hist_atr"

    def init_state(self, parameters: Mapping[str, Any]) -> _MACDHistATRState:
        return _MACDHistATRState(
            fast=_EMAState(int(parameters["fast"])),
            slow=_EMAState(int(parameters["slow"])),
            signal=_EMAState(int(parameters["signal"])),
            atr=_ATRState(int(parameters["atr_window"])),
        )

    def update(self, state: _MACDHistATRState, confirmed_bar: Bar, parameters: Mapping[str, Any]) -> Optional[float]:
        close = float(confirmed_bar["close"])
        fast = state.fast.update(close)
        slow = state.slow.update(close)
        atr = state.atr.update(float(confirmed_bar["high"]), float(confirmed_bar["low"]), close)
        if fast is None or slow is None:
            return None
        macd = fast - slow
        signal = state.signal.update(macd)
        if signal is None or atr is None or atr <= 0:
            return None
        return (macd - signal) / atr


@dataclass
class _RSIState:
    period: int
    previous_close: Optional[float] = None
    gains: list[float] = field(default_factory=list)
    losses: list[float] = field(default_factory=list)
    average_gain: Optional[float] = None
    average_loss: Optional[float] = None


class RSIKernel(FactorKernel):
    name = "rsi"

    def init_state(self, parameters: Mapping[str, Any]) -> _RSIState:
        return _RSIState(period=int(parameters["window"]))

    def update(self, state: _RSIState, confirmed_bar: Bar, parameters: Mapping[str, Any]) -> Optional[float]:
        close = float(confirmed_bar["close"])
        if state.previous_close is None:
            state.previous_close = close
            return None
        change = close - state.previous_close
        state.previous_close = close
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        if state.average_gain is None or state.average_loss is None:
            state.gains.append(gain)
            state.losses.append(loss)
            if len(state.gains) < state.period:
                return None
            state.average_gain = sum(state.gains) / state.period
            state.average_loss = sum(state.losses) / state.period
        else:
            state.average_gain = (state.average_gain * (state.period - 1) + gain) / state.period
            state.average_loss = (state.average_loss * (state.period - 1) + loss) / state.period
        if state.average_loss <= 0:
            return 100.0 if state.average_gain > 0 else 50.0
        relative_strength = state.average_gain / state.average_loss
        return 100.0 - 100.0 / (1.0 + relative_strength)


@dataclass
class _KDJState:
    highs: deque[float]
    lows: deque[float]
    k: float = 50.0
    d: float = 50.0


class KDJJKernel(FactorKernel):
    name = "kdj_j"

    def init_state(self, parameters: Mapping[str, Any]) -> _KDJState:
        window = int(parameters["window"])
        return _KDJState(highs=deque(maxlen=window), lows=deque(maxlen=window))

    def update(self, state: _KDJState, confirmed_bar: Bar, parameters: Mapping[str, Any]) -> Optional[float]:
        state.highs.append(float(confirmed_bar["high"]))
        state.lows.append(float(confirmed_bar["low"]))
        if len(state.highs) < state.highs.maxlen:
            return None
        highest = max(state.highs)
        lowest = min(state.lows)
        close = float(confirmed_bar["close"])
        rsv = 50.0 if highest <= lowest else (close - lowest) / (highest - lowest) * 100.0
        k_smooth = int(parameters["k_smooth"])
        d_smooth = int(parameters["d_smooth"])
        state.k = (state.k * (k_smooth - 1) + rsv) / k_smooth
        state.d = (state.d * (d_smooth - 1) + state.k) / d_smooth
        return 3.0 * state.k - 2.0 * state.d


@dataclass
class _ROCState:
    closes: deque[float]


class ROCKernel(FactorKernel):
    name = "roc"

    def init_state(self, parameters: Mapping[str, Any]) -> _ROCState:
        return _ROCState(closes=deque(maxlen=int(parameters["window"]) + 1))

    def update(self, state: _ROCState, confirmed_bar: Bar, parameters: Mapping[str, Any]) -> Optional[float]:
        state.closes.append(float(confirmed_bar["close"]))
        if len(state.closes) < state.closes.maxlen:
            return None
        first = state.closes[0]
        return None if first <= 0 else (state.closes[-1] / first - 1.0) * 100.0


def _mean_and_population_std(values: deque[float]) -> tuple[float, float]:
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return mean, sqrt(max(variance, 0.0))


@dataclass
class _BollingerState:
    closes: deque[float]


class BollingerBandwidthKernel(FactorKernel):
    name = "bollinger_bandwidth"

    def init_state(self, parameters: Mapping[str, Any]) -> _BollingerState:
        return _BollingerState(closes=deque(maxlen=int(parameters["window"])))

    def update(self, state: _BollingerState, confirmed_bar: Bar, parameters: Mapping[str, Any]) -> Optional[float]:
        state.closes.append(float(confirmed_bar["close"]))
        if len(state.closes) < state.closes.maxlen:
            return None
        mean, std = _mean_and_population_std(state.closes)
        if mean <= 0:
            return None
        return 2.0 * float(parameters["std_mult"]) * std / mean * 100.0


class BollingerZScoreKernel(FactorKernel):
    name = "bollinger_zscore"

    def init_state(self, parameters: Mapping[str, Any]) -> _BollingerState:
        return _BollingerState(closes=deque(maxlen=int(parameters["window"])))

    def update(self, state: _BollingerState, confirmed_bar: Bar, parameters: Mapping[str, Any]) -> Optional[float]:
        close = float(confirmed_bar["close"])
        state.closes.append(close)
        if len(state.closes) < state.closes.maxlen:
            return None
        mean, std = _mean_and_population_std(state.closes)
        return 0.0 if std <= 0 else (close - mean) / std


@dataclass
class _OBVSlopeState:
    values: deque[float]
    volumes: deque[float]
    previous_close: Optional[float] = None
    obv: float = 0.0


class OBVSlopeKernel(FactorKernel):
    name = "obv_slope"

    def init_state(self, parameters: Mapping[str, Any]) -> _OBVSlopeState:
        window = int(parameters["window"])
        return _OBVSlopeState(values=deque(maxlen=window), volumes=deque(maxlen=window))

    def update(self, state: _OBVSlopeState, confirmed_bar: Bar, parameters: Mapping[str, Any]) -> Optional[float]:
        close = float(confirmed_bar["close"])
        volume = float(confirmed_bar["volume"])
        if state.previous_close is not None:
            if close > state.previous_close:
                state.obv += volume
            elif close < state.previous_close:
                state.obv -= volume
        state.previous_close = close
        state.values.append(state.obv)
        state.volumes.append(volume)
        if len(state.values) < state.values.maxlen:
            return None
        count = len(state.values)
        x_mean = (count - 1) / 2.0
        y_mean = sum(state.values) / count
        denominator = sum((index - x_mean) ** 2 for index in range(count))
        slope = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(state.values)) / denominator
        mean_volume = sum(state.volumes) / count
        return 0.0 if mean_volume <= 0 else slope / mean_volume


@dataclass
class _VWAPDistanceATRState:
    price_volume: deque[float]
    volumes: deque[float]
    atr: _ATRState


class VWAPDistanceATRKernel(FactorKernel):
    name = "vwap_distance_atr"

    def init_state(self, parameters: Mapping[str, Any]) -> _VWAPDistanceATRState:
        window = int(parameters["window"])
        return _VWAPDistanceATRState(
            price_volume=deque(maxlen=window),
            volumes=deque(maxlen=window),
            atr=_ATRState(int(parameters["atr_window"])),
        )

    def update(
        self,
        state: _VWAPDistanceATRState,
        confirmed_bar: Bar,
        parameters: Mapping[str, Any],
    ) -> Optional[float]:
        high = float(confirmed_bar["high"])
        low = float(confirmed_bar["low"])
        close = float(confirmed_bar["close"])
        volume = float(confirmed_bar["volume"])
        typical = (high + low + close) / 3.0
        state.price_volume.append(typical * volume)
        state.volumes.append(volume)
        atr = state.atr.update(high, low, close)
        if len(state.volumes) < state.volumes.maxlen or atr is None or atr <= 0:
            return None
        total_volume = sum(state.volumes)
        if total_volume <= 0:
            return None
        vwap = sum(state.price_volume) / total_volume
        return (close - vwap) / atr


@dataclass
class _VolumeZScoreState:
    volumes: deque[float]


class VolumeZScoreKernel(FactorKernel):
    name = "volume_zscore"

    def init_state(self, parameters: Mapping[str, Any]) -> _VolumeZScoreState:
        return _VolumeZScoreState(volumes=deque(maxlen=int(parameters["window"])))

    def update(
        self,
        state: _VolumeZScoreState,
        confirmed_bar: Bar,
        parameters: Mapping[str, Any],
    ) -> Optional[float]:
        volume = float(confirmed_bar["volume"])
        state.volumes.append(volume)
        if len(state.volumes) < state.volumes.maxlen:
            return None
        mean, std = _mean_and_population_std(state.volumes)
        return 0.0 if std <= 0 else (volume - mean) / std


@dataclass
class _MFIState:
    positive_flows: deque[float]
    negative_flows: deque[float]
    previous_typical_price: Optional[float] = None


class MFIKernel(FactorKernel):
    name = "mfi"

    def init_state(self, parameters: Mapping[str, Any]) -> _MFIState:
        window = int(parameters["window"])
        return _MFIState(
            positive_flows=deque(maxlen=window),
            negative_flows=deque(maxlen=window),
        )

    def update(
        self,
        state: _MFIState,
        confirmed_bar: Bar,
        parameters: Mapping[str, Any],
    ) -> Optional[float]:
        typical_price = (
            float(confirmed_bar["high"])
            + float(confirmed_bar["low"])
            + float(confirmed_bar["close"])
        ) / 3.0
        raw_flow = typical_price * float(confirmed_bar["volume"])
        if state.previous_typical_price is None:
            state.previous_typical_price = typical_price
            return None
        if typical_price > state.previous_typical_price:
            positive_flow, negative_flow = raw_flow, 0.0
        elif typical_price < state.previous_typical_price:
            positive_flow, negative_flow = 0.0, raw_flow
        else:
            positive_flow = negative_flow = 0.0
        state.previous_typical_price = typical_price
        state.positive_flows.append(positive_flow)
        state.negative_flows.append(negative_flow)
        if len(state.positive_flows) < state.positive_flows.maxlen:
            return None
        positive_sum = sum(state.positive_flows)
        negative_sum = sum(state.negative_flows)
        if negative_sum <= 0:
            return 100.0 if positive_sum > 0 else 50.0
        if positive_sum <= 0:
            return 0.0
        money_ratio = positive_sum / negative_sum
        return 100.0 - 100.0 / (1.0 + money_ratio)


@dataclass
class _PriceVolumeCorrState:
    price_returns: deque[float]
    volume_changes: deque[float]
    previous_close: Optional[float] = None
    previous_volume: Optional[float] = None


class PriceVolumeCorrKernel(FactorKernel):
    name = "price_volume_corr"

    def init_state(self, parameters: Mapping[str, Any]) -> _PriceVolumeCorrState:
        window = int(parameters["window"])
        return _PriceVolumeCorrState(
            price_returns=deque(maxlen=window),
            volume_changes=deque(maxlen=window),
        )

    def update(
        self,
        state: _PriceVolumeCorrState,
        confirmed_bar: Bar,
        parameters: Mapping[str, Any],
    ) -> Optional[float]:
        close = float(confirmed_bar["close"])
        volume = float(confirmed_bar["volume"])
        if state.previous_close is None or state.previous_volume is None:
            state.previous_close = close
            state.previous_volume = volume
            return None
        price_return = close / state.previous_close - 1.0
        volume_change = 0.0 if state.previous_volume <= 0 else volume / state.previous_volume - 1.0
        state.previous_close = close
        state.previous_volume = volume
        state.price_returns.append(price_return)
        state.volume_changes.append(volume_change)
        if len(state.price_returns) < state.price_returns.maxlen:
            return None
        price_mean = sum(state.price_returns) / len(state.price_returns)
        volume_mean = sum(state.volume_changes) / len(state.volume_changes)
        covariance = sum(
            (price - price_mean) * (volume_delta - volume_mean)
            for price, volume_delta in zip(state.price_returns, state.volume_changes)
        )
        price_variance = sum((price - price_mean) ** 2 for price in state.price_returns)
        volume_variance = sum(
            (volume_delta - volume_mean) ** 2 for volume_delta in state.volume_changes
        )
        denominator = sqrt(price_variance * volume_variance)
        return 0.0 if denominator <= 0 else covariance / denominator


_KERNELS: dict[str, FactorKernel] = {
    kernel.name: kernel
    for kernel in (
        ATRPercentKernel(),
        EfficiencyRatioKernel(),
        EMAGapATRKernel(),
        PriceEMACrossCountKernel(),
        ADXKernel(),
        MACDHistATRKernel(),
        RSIKernel(),
        KDJJKernel(),
        ROCKernel(),
        BollingerBandwidthKernel(),
        BollingerZScoreKernel(),
        OBVSlopeKernel(),
        VWAPDistanceATRKernel(),
        VolumeZScoreKernel(),
        MFIKernel(),
        PriceVolumeCorrKernel(),
    )
}


def get_factor_kernel(name: str) -> FactorKernel:
    try:
        return _KERNELS[name]
    except KeyError as exc:
        raise UnknownFactorKernelError(f"unknown factor kernel: {name}") from exc
