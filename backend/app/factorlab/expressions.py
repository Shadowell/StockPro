"""Static validation for FactorLab's structured expression metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


ALLOWED_FACTOR_FIELDS = frozenset(
    {"open", "high", "low", "close", "volume", "quote_volume"}
)
ALLOWED_FACTOR_OPERATORS = frozenset(
    {
        "ref",
        "delta",
        "return",
        "mean",
        "std",
        "min",
        "max",
        "sum",
        "ema",
        "sma",
        "adx",
        "di",
        "linear_slope",
        "r2",
        "donchian",
        "atr",
        "true_range",
        "realized_vol",
        "downside_vol",
        "ts_rank",
        "cross_section_rank",
        "percentile",
        "robust_zscore",
        "corr",
        "cov",
        "beta",
        "count_cross",
        "efficiency_ratio",
        "distance",
        "add",
        "subtract",
        "multiply",
        "divide",
        "abs",
        "sign",
        "clip",
        "where",
    }
)
_OPERATOR_KEYS = frozenset(
    {"op", "args", "left", "right", "condition", "true", "false", "field", "window", "periods"}
)


class FactorExpressionError(ValueError):
    """Raised when an expression leaves the auditable allowlist."""


def validate_factor_expression(expression: Mapping[str, Any]) -> None:
    """Reject arbitrary code, unknown fields/operators and future references."""
    _validate_node(expression, path="expression")


def _validate_node(node: Any, *, path: str) -> None:
    if isinstance(node, Mapping):
        if "literal" in node:
            if set(node) != {"literal"} or not isinstance(node["literal"], (int, float, bool)):
                raise FactorExpressionError(f"{path}: invalid literal node")
            return
        if "field" in node and "op" not in node:
            if set(node) != {"field"} or node["field"] not in ALLOWED_FACTOR_FIELDS:
                raise FactorExpressionError(f"{path}: field is not allowlisted")
            return

        operator = node.get("op")
        if operator not in ALLOWED_FACTOR_OPERATORS:
            raise FactorExpressionError(f"{path}: operator is not allowlisted: {operator!r}")
        unknown_keys = set(node) - _OPERATOR_KEYS
        if unknown_keys:
            raise FactorExpressionError(f"{path}: unsupported expression keys: {sorted(unknown_keys)}")
        if "field" in node and node["field"] not in ALLOWED_FACTOR_FIELDS:
            raise FactorExpressionError(f"{path}: field is not allowlisted")
        if operator == "ref":
            periods = node.get("periods")
            if isinstance(periods, (int, float)) and periods < 0:
                raise FactorExpressionError(f"{path}: future references are forbidden")

        for key, value in node.items():
            if key in {"op", "field", "window", "periods"}:
                _validate_parameter_reference(value, path=f"{path}.{key}")
                continue
            _validate_node(value, path=f"{path}.{key}")
        return

    if isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
        for index, value in enumerate(node):
            _validate_node(value, path=f"{path}[{index}]")
        return
    raise FactorExpressionError(f"{path}: expression values must be structured nodes")


def _validate_parameter_reference(value: Any, *, path: str) -> None:
    if isinstance(value, str) and value.startswith("$") and len(value) > 1:
        return
    if isinstance(value, (int, float)) and value >= 0:
        return
    if path.endswith(".op") and isinstance(value, str):
        return
    if path.endswith(".field") and isinstance(value, str):
        return
    raise FactorExpressionError(f"{path}: invalid parameter reference")
