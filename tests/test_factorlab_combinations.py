from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.factorlab.combinations import (  # noqa: E402
    FactorCombination,
    FactorCombinationError,
)


ADX = "trend.adx@1:adx"
RSI = "momentum.rsi@1:rsi"
MACD = "trend.macd_hist_atr@1:macd"


def test_weighted_combination_evaluates_real_factor_values() -> None:
    combination = FactorCombination.from_payload(
        {
            "type": "weighted_sum",
            "terms": [
                {"weight": 0.25, "node": {"type": "factor", "instance_id": ADX}},
                {"weight": 0.75, "node": {"type": "factor", "instance_id": MACD}},
            ],
        },
        {ADX, MACD},
    )

    assert combination.evaluate_row({ADX: 20.0, MACD: 2.0}) == 6.5
    assert combination.factor_instance_ids == (ADX, MACD)


def test_equivalent_weighted_combinations_have_one_semantic_hash() -> None:
    first = FactorCombination.from_payload(
        {
            "type": "weighted_sum",
            "terms": [
                {"weight": 1, "node": {"type": "factor", "instance_id": ADX}},
                {"weight": -0.5, "node": {"type": "factor", "instance_id": RSI}},
            ],
        },
        {ADX, RSI},
    )
    second = FactorCombination.from_payload(
        {
            "terms": [
                {"node": {"instance_id": RSI, "type": "factor"}, "weight": -0.5},
                {"node": {"instance_id": ADX, "type": "factor"}, "weight": 1.0},
            ],
            "type": "weighted_sum",
        },
        {ADX, RSI},
    )

    assert first.semantic_hash == second.semantic_hash
    assert first.canonical_payload == second.canonical_payload


@pytest.mark.parametrize(
    "payload,error",
    [
        ({"type": "factor", "instance_id": "unknown"}, "allowlist"),
        ({"type": "python", "code": "open('/tmp/x')"}, "type"),
        (
            {
                "type": "weighted_sum",
                "terms": [
                    {"weight": 1.0, "node": {"type": "factor", "instance_id": ADX}}
                    for _ in range(9)
                ],
            },
            "leaves",
        ),
        (
            {
                "type": "condition",
                "factor": {"type": "factor", "instance_id": RSI},
                "operator": "exec",
                "threshold": 50,
                "if_true": {"type": "factor", "instance_id": ADX},
                "if_false": {"type": "factor", "instance_id": MACD},
            },
            "operator",
        ),
    ],
)
def test_combination_rejects_unsafe_unknown_or_over_budget_payload(payload, error) -> None:
    with pytest.raises(FactorCombinationError, match=error):
        FactorCombination.from_payload(payload, {ADX, RSI, MACD}, max_leaves=8)


def test_condition_clip_and_family_average_are_deterministic() -> None:
    combination = FactorCombination.from_payload(
        {
            "type": "condition",
            "factor": {"type": "factor", "instance_id": RSI},
            "operator": "gte",
            "threshold": 50,
            "if_true": {
                "type": "clip",
                "minimum": -1,
                "maximum": 1,
                "node": {"type": "factor", "instance_id": MACD},
            },
            "if_false": {
                "type": "family_average",
                "nodes": [
                    {"type": "factor", "instance_id": ADX},
                    {"type": "factor", "instance_id": MACD},
                ],
            },
        },
        {ADX, RSI, MACD},
    )

    assert combination.evaluate_row({RSI: 60.0, MACD: 3.0, ADX: 20.0}) == 1.0
    assert combination.evaluate_row({RSI: 40.0, MACD: 2.0, ADX: 20.0}) == 11.0


def test_combination_returns_missing_when_a_required_factor_is_missing() -> None:
    combination = FactorCombination.from_payload(
        {
            "type": "weighted_sum",
            "terms": [
                {"weight": 1, "node": {"type": "factor", "instance_id": ADX}},
                {"weight": 1, "node": {"type": "factor", "instance_id": RSI}},
            ],
        },
        {ADX, RSI},
    )

    assert combination.evaluate_row({ADX: 20.0, RSI: None}) is None
