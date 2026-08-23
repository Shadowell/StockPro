"""Point-in-time FactorLab engine for batch and confirmed-bar streaming."""

from __future__ import annotations

import time
from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Optional

from app.factorlab.kernels import FactorKernel, get_factor_kernel
from app.factorlab.models import FactorDefinition, FactorInstance
from app.factorlab.registry import FactorRegistry
from app.services.kline_file_store import TIMEFRAME_MS


class FactorInputError(ValueError):
    """Raised when factor input violates causality or market-data contracts."""


@dataclass(frozen=True)
class FactorContext:
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    dataset_revision: str


@dataclass(frozen=True)
class FactorValue:
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    instance_id: str
    event_time: int
    available_at: int
    computed_at: Optional[int]
    value: Optional[float]
    value_status: str
    dataset_revision: str


class FactorStream:
    def __init__(
        self,
        *,
        definition: FactorDefinition,
        instance: FactorInstance,
        context: FactorContext,
        kernel: FactorKernel,
    ):
        self.definition = definition
        self.instance = instance
        self.context = context
        self.kernel = kernel
        self.state = kernel.init_state(instance.parameters)
        self.last_event_time: Optional[int] = None
        self._timeframe_ms = _timeframe_ms(context.timeframe)

    def update(self, confirmed_bar: Mapping[str, Any], *, computed_at: Optional[int] = None) -> FactorValue:
        event_time = _validate_bar(
            confirmed_bar,
            inputs=self.definition.inputs,
            previous_event_time=self.last_event_time,
        )
        self.last_event_time = event_time
        raw_value = self.kernel.update(self.state, confirmed_bar, self.instance.parameters)
        value, status = _normalize_value(raw_value, self.definition)
        derived_available_at = event_time + self._timeframe_ms
        supplied_available_at = int(confirmed_bar.get("available_at") or derived_available_at)
        if supplied_available_at < derived_available_at:
            raise FactorInputError("available_at cannot be earlier than the confirmed bar close")
        return FactorValue(
            exchange=self.context.exchange,
            market_type=self.context.market_type,
            symbol=self.context.symbol,
            timeframe=self.context.timeframe,
            instance_id=self.instance.instance_id,
            event_time=event_time,
            available_at=supplied_available_at,
            computed_at=int(computed_at if computed_at is not None else time.time() * 1000),
            value=value,
            value_status=status,
            dataset_revision=self.context.dataset_revision,
        )


class FactorEngine:
    def __init__(self, registry: FactorRegistry):
        self.registry = registry

    def create_stream(self, instance: FactorInstance, context: FactorContext) -> FactorStream:
        registered = self.registry.get_instance(instance.instance_id)
        if registered != instance:
            raise FactorInputError(f"factor instance is not registered: {instance.instance_id}")
        definition = self.registry.get_definition(
            instance.definition_id,
            instance.definition_version,
        )
        kernel = get_factor_kernel(definition.kernel_name)
        if kernel.required_bars(instance.parameters) != instance.required_bars:
            raise FactorInputError(f"factor instance lookback is inconsistent: {instance.instance_id}")
        return FactorStream(
            definition=definition,
            instance=instance,
            context=context,
            kernel=kernel,
        )

    def compute_batch(
        self,
        instance: FactorInstance,
        confirmed_bars: list[Mapping[str, Any]],
        context: FactorContext,
        *,
        computed_at: Optional[int] = None,
    ) -> list[FactorValue]:
        batch_computed_at = int(computed_at if computed_at is not None else time.time() * 1000)
        stream = self.create_stream(instance, context)
        return [stream.update(bar, computed_at=batch_computed_at) for bar in confirmed_bars]


def _timeframe_ms(timeframe: str) -> int:
    value = TIMEFRAME_MS.get(str(timeframe).lower())
    if value is None:
        raise FactorInputError(f"unsupported factor timeframe: {timeframe}")
    return value


def _validate_bar(
    bar: Mapping[str, Any],
    *,
    inputs: tuple[str, ...],
    previous_event_time: Optional[int],
) -> int:
    if bar.get("confirmed") is not True:
        raise FactorInputError("factor inputs must be confirmed bars")
    if "event_time" not in bar:
        raise FactorInputError("factor input is missing event_time")
    event_time = int(bar["event_time"])
    if previous_event_time is not None and event_time <= previous_event_time:
        raise FactorInputError("factor event_time must be strictly increasing")
    missing = [name for name in inputs if name not in bar]
    if missing:
        raise FactorInputError(f"factor input is missing fields: {missing}")
    for name in inputs:
        value = float(bar[name])
        if not isfinite(value):
            raise FactorInputError(f"factor input {name} must be finite")
    price_fields = {name: float(bar[name]) for name in ("open", "high", "low", "close") if name in bar}
    if any(not isfinite(value) or value <= 0 for value in price_fields.values()):
        raise FactorInputError("factor input OHLC values must be finite and positive")
    if {"open", "high", "low", "close"} <= set(price_fields):
        open_price = price_fields["open"]
        high = price_fields["high"]
        low = price_fields["low"]
        close = price_fields["close"]
        if high < max(open_price, close) or low > min(open_price, close):
            raise FactorInputError("factor input OHLC values are inconsistent")
    elif {"high", "low", "close"} <= set(price_fields):
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        if high < max(low, close) or low > min(high, close):
            raise FactorInputError("factor input OHLC values are inconsistent")
    return event_time


def _normalize_value(
    raw_value: Optional[float],
    definition: FactorDefinition,
) -> tuple[Optional[float], str]:
    if raw_value is None:
        return None, "warming_up"
    value = float(raw_value)
    if not isfinite(value):
        return None, "invalid"
    if definition.valid_min is not None and value < definition.valid_min:
        return value, "invalid"
    if definition.valid_max is not None and value > definition.valid_max:
        return value, "invalid"
    return value, "valid"
