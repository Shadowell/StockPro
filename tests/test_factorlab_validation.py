from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.factorlab.validation import (  # noqa: E402
    FactorValidationError,
    ValidationThresholds,
    evaluate_oos,
)


def prediction_rows(
    *,
    candidate_return: float,
    stress_return: float,
    baseline_return: float,
    only_one_profitable_symbol: bool = False,
) -> pd.DataFrame:
    rows = []
    for fold in range(5):
        for index in range(20):
            symbol = "BTC/USDT:USDT" if index % 2 == 0 else "ETH/USDT:USDT"
            row_return = candidate_return
            if only_one_profitable_symbol and symbol.startswith("ETH"):
                row_return = 0.0
            rows.append(
                {
                    "fold_index": fold,
                    "symbol": symbol,
                    "decision_time": fold * 100 + index,
                    "prediction": 1.0,
                    "baseline_prediction": 1.0,
                    "forward_long_net_return": row_return,
                    "forward_short_net_return": -row_return,
                    "forward_long_stress_return": stress_return if row_return else 0.0,
                    "forward_short_stress_return": -stress_return if row_return else 0.0,
                    "baseline_long_net_return": baseline_return,
                    "baseline_short_net_return": -baseline_return,
                }
            )
    return pd.DataFrame(rows)


def test_validation_accepts_distributed_candidate_that_passes_every_hard_gate() -> None:
    report = evaluate_oos(
        prediction_rows(
            candidate_return=0.002,
            stress_return=0.001,
            baseline_return=0.0005,
        ),
        coverage=0.99,
    )

    assert report.accepted is True
    assert report.hard_gate_failures == ()
    assert report.fold_count == 5
    assert report.profitable_fold_ratio == 1.0
    assert report.total_return > report.baseline_total_return > 0
    assert report.stress_total_return > 0
    assert report.score >= 70


def test_high_score_cannot_override_symbol_concentration_hard_gate() -> None:
    report = evaluate_oos(
        prediction_rows(
            candidate_return=0.004,
            stress_return=0.003,
            baseline_return=0.0001,
            only_one_profitable_symbol=True,
        ),
        coverage=1.0,
    )

    assert report.score >= 70
    assert "symbol_concentration" in report.hard_gate_failures
    assert report.accepted is False


def test_cost_negative_and_40bps_collapse_are_rejected() -> None:
    negative = evaluate_oos(
        prediction_rows(
            candidate_return=-0.001,
            stress_return=-0.003,
            baseline_return=-0.002,
        ),
        coverage=1.0,
    )
    collapse = evaluate_oos(
        prediction_rows(
            candidate_return=0.001,
            stress_return=-0.002,
            baseline_return=0.0001,
        ),
        coverage=1.0,
    )

    assert "cost_return_non_positive" in negative.hard_gate_failures
    assert negative.accepted is False
    assert "stress_collapse" in collapse.hard_gate_failures
    assert collapse.accepted is False


def test_coverage_fold_profit_factor_and_drawdown_thresholds_fail_closed() -> None:
    rows = prediction_rows(
        candidate_return=0.002,
        stress_return=0.001,
        baseline_return=0.0005,
    )
    rows.loc[::3, "forward_long_net_return"] = -0.01
    rows.loc[::3, "forward_long_stress_return"] = -0.012
    thresholds = ValidationThresholds(
        min_coverage=0.95,
        min_folds=6,
        min_profit_factor=2.0,
        max_drawdown=0.01,
        min_profitable_fold_ratio=0.9,
        max_symbol_concentration=0.6,
        min_score=70.0,
    )

    report = evaluate_oos(rows, coverage=0.8, thresholds=thresholds)

    assert {"coverage", "fold_count", "profit_factor", "max_drawdown"} <= set(
        report.hard_gate_failures
    )
    assert report.accepted is False


@pytest.mark.parametrize("mutation", ["duplicate", "cross_fold", "coverage"])
def test_validation_rejects_duplicated_or_impossible_oos_evidence(mutation: str) -> None:
    rows = prediction_rows(
        candidate_return=0.002,
        stress_return=0.001,
        baseline_return=0.0005,
    )
    coverage = 1.0
    if mutation == "duplicate":
        rows = pd.concat([rows, rows.iloc[[0]]], ignore_index=True)
    elif mutation == "cross_fold":
        rows.loc[20, "decision_time"] = rows.loc[0, "decision_time"]
    elif mutation == "coverage":
        coverage = 1.1
    with pytest.raises(FactorValidationError):
        evaluate_oos(rows, coverage=coverage)


def test_validation_preserves_but_rejects_catastrophic_loss_evidence() -> None:
    rows = prediction_rows(
        candidate_return=0.002,
        stress_return=0.001,
        baseline_return=0.0005,
    )
    rows.loc[0, "forward_long_net_return"] = -1.2

    report = evaluate_oos(rows, coverage=1.0)

    assert "catastrophic_loss" in report.hard_gate_failures
    assert report.total_return == -1.0
    assert report.accepted is False
