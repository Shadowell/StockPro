"""Built-in continuous OHLCV factor definitions."""

from __future__ import annotations

import hashlib
import json
from typing import Iterable

from app.factorlab.models import FactorDefinition


def _implementation_hash(kernel_name: str, expression: dict) -> str:
    payload = json.dumps(
        {"kernel_name": kernel_name, "expression": expression},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _definition(**kwargs) -> FactorDefinition:
    expression = kwargs["expression"]
    kernel_name = kwargs["kernel_name"]
    return FactorDefinition(
        **kwargs,
        implementation_hash=_implementation_hash(kernel_name, expression),
    )


def builtin_factor_definitions() -> Iterable[FactorDefinition]:
    definitions = [
        _definition(
            definition_id="volatility.atr_pct",
            definition_version=1,
            display_name="ATR 波动率百分比",
            family="volatility_regime",
            role="regime",
            description="Wilder ATR 相对当根收盘价的百分比，不表达方向。",
            kernel_name="atr_pct",
            expression={
                "op": "multiply",
                "args": [
                    {"op": "divide", "args": [{"op": "atr", "window": "$window"}, {"field": "close"}]},
                    {"literal": 100.0},
                ],
            },
            inputs=("high", "low", "close"),
            parameter_schema={"window": {"type": "integer", "default": 14, "minimum": 2}},
            lookback_bars=14,
            orientation="higher_is_more_volatile",
            valid_min=0.0,
            metadata={"unit": "percent"},
        ),
        _definition(
            definition_id="trend.efficiency_ratio",
            definition_version=1,
            display_name="趋势效率比",
            family="trend_quality",
            role="alpha_quality",
            description="净位移与逐根绝对路径长度之比。",
            kernel_name="efficiency_ratio",
            expression={"op": "efficiency_ratio", "field": "close", "window": "$window"},
            inputs=("close",),
            parameter_schema={"window": {"type": "integer", "default": 20, "minimum": 1}},
            lookback_bars=21,
            valid_min=0.0,
            valid_max=1.0,
            metadata={"unit": "ratio"},
        ),
        _definition(
            definition_id="trend.ema_gap_atr",
            definition_version=1,
            display_name="EMA 间距 ATR 归一化",
            family="trend_quality",
            role="alpha_quality",
            description="EMA 快慢线有向间距除以 Wilder ATR。",
            kernel_name="ema_gap_atr",
            expression={
                "op": "divide",
                "args": [
                    {
                        "op": "subtract",
                        "args": [
                            {"op": "ema", "field": "close", "window": "$fast"},
                            {"op": "ema", "field": "close", "window": "$slow"},
                        ],
                    },
                    {"op": "atr", "window": "$atr_window"},
                ],
            },
            inputs=("high", "low", "close"),
            parameter_schema={
                "fast": {"type": "integer", "default": 5, "minimum": 1},
                "slow": {"type": "integer", "default": 20, "minimum": 2},
                "atr_window": {"type": "integer", "default": 14, "minimum": 2},
            },
            lookback_bars=20,
            orientation="signed_trend_direction",
            metadata={"unit": "atr_multiple"},
        ),
        _definition(
            definition_id="chop.price_ema_cross_count",
            definition_version=1,
            display_name="价格 EMA 穿越次数",
            family="trend_quality",
            role="regime",
            description="最近窗口内价格相对 EMA 的非零符号翻转次数。",
            kernel_name="price_ema_cross_count",
            expression={
                "op": "count_cross",
                "left": {"field": "close"},
                "right": {"op": "ema", "field": "close", "window": "$ema_window"},
                "window": "$window",
            },
            inputs=("close",),
            parameter_schema={
                "ema_window": {"type": "integer", "default": 20, "minimum": 2},
                "window": {"type": "integer", "default": 100, "minimum": 2},
            },
            lookback_bars=119,
            orientation="lower_is_less_choppy",
            valid_min=0.0,
            metadata={"unit": "count"},
        ),
        _definition(
            definition_id="trend.adx",
            definition_version=1,
            display_name="ADX 趋势强度",
            family="trend_quality",
            role="alpha_quality",
            description="Wilder ADX，只衡量趋势强度，不表达多空方向。",
            kernel_name="adx",
            expression={"op": "adx", "window": "$window"},
            inputs=("high", "low", "close"),
            parameter_schema={"window": {"type": "integer", "default": 14, "minimum": 2}},
            lookback_bars=29,
            valid_min=0.0,
            valid_max=100.0,
            metadata={"unit": "index"},
        ),
    ]
    return sorted(definitions, key=lambda item: item.definition_id)
