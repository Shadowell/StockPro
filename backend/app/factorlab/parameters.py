"""Factor parameter normalization and deterministic lookback rules."""

from __future__ import annotations

from typing import Any, Mapping

from app.factorlab.models import FactorDefinition


class FactorParameterError(ValueError):
    """Raised when a factor instance uses unsupported parameters."""


def normalize_parameters(
    definition: FactorDefinition,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    unknown = set(parameters) - set(definition.parameter_schema)
    if unknown:
        raise FactorParameterError(f"unknown factor parameters: {sorted(unknown)}")

    normalized: dict[str, Any] = {}
    for name in sorted(definition.parameter_schema):
        schema = definition.parameter_schema[name]
        value = parameters.get(name, schema.get("default"))
        if value is None:
            raise FactorParameterError(f"missing required factor parameter: {name}")
        expected_type = schema.get("type")
        if expected_type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise FactorParameterError(f"factor parameter {name} must be an integer")
            value = int(value)
        elif expected_type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise FactorParameterError(f"factor parameter {name} must be numeric")
            value = float(value)
        else:
            raise FactorParameterError(f"unsupported factor parameter type: {expected_type!r}")

        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise FactorParameterError(f"factor parameter {name} must be >= {minimum}")
        if maximum is not None and value > maximum:
            raise FactorParameterError(f"factor parameter {name} must be <= {maximum}")
        normalized[name] = value

    if definition.kernel_name == "ema_gap_atr" and normalized["fast"] >= normalized["slow"]:
        raise FactorParameterError("EMA fast window must be smaller than slow window")
    if definition.kernel_name == "macd_hist_atr" and normalized["fast"] >= normalized["slow"]:
        raise FactorParameterError("MACD fast window must be smaller than slow window")
    return normalized


def required_bars_for(kernel_name: str, parameters: Mapping[str, Any]) -> int:
    if kernel_name == "atr_pct":
        return int(parameters["window"])
    if kernel_name == "efficiency_ratio":
        return int(parameters["window"]) + 1
    if kernel_name == "ema_gap_atr":
        return max(
            int(parameters["fast"]),
            int(parameters["slow"]),
            int(parameters["atr_window"]),
        )
    if kernel_name == "price_ema_cross_count":
        return int(parameters["ema_window"]) + int(parameters["window"]) - 1
    if kernel_name == "adx":
        return 2 * int(parameters["window"]) + 1
    if kernel_name == "macd_hist_atr":
        return max(
            int(parameters["slow"]) + int(parameters["signal"]) - 1,
            int(parameters["atr_window"]),
        )
    if kernel_name == "rsi":
        return int(parameters["window"]) + 1
    if kernel_name == "kdj_j":
        return int(parameters["window"])
    if kernel_name == "roc":
        return int(parameters["window"]) + 1
    if kernel_name in {"bollinger_bandwidth", "bollinger_zscore", "obv_slope"}:
        return int(parameters["window"])
    if kernel_name == "vwap_distance_atr":
        return max(int(parameters["window"]), int(parameters["atr_window"]))
    if kernel_name == "volume_zscore":
        return int(parameters["window"])
    if kernel_name in {"mfi", "price_volume_corr"}:
        return int(parameters["window"]) + 1
    raise FactorParameterError(f"unknown factor kernel: {kernel_name}")
