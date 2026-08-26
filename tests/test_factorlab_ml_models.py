from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.factorlab.ml_models import FactorModelError, train_and_predict  # noqa: E402


FEATURES = ("factor_a", "factor_b")


def regression_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    x1 = np.linspace(-2.0, 2.0, 80)
    x2 = np.cos(np.linspace(0.0, 5.0, 80))
    train = pd.DataFrame(
        {
            "factor_a": x1,
            "factor_b": x2,
            "forward_long_net_return": 0.03 * x1 - 0.01 * x2,
            "forward_profitable_after_cost": (0.03 * x1 - 0.01 * x2 > 0).astype(int),
        }
    )
    test_x1 = np.linspace(-1.5, 1.5, 24)
    test_x2 = np.sin(np.linspace(0.0, 4.0, 24))
    test = pd.DataFrame(
        {
            "factor_a": test_x1,
            "factor_b": test_x2,
            "forward_long_net_return": 0.03 * test_x1 - 0.01 * test_x2,
            "forward_profitable_after_cost": (0.03 * test_x1 - 0.01 * test_x2 > 0).astype(int),
        }
    )
    return train, test


def test_ridge_and_logistic_predictions_are_deterministic_and_ignore_test_labels() -> None:
    train, test = regression_frames()
    altered_test = test.copy()
    altered_test["forward_long_net_return"] = 999.0
    altered_test["forward_profitable_after_cost"] = 1 - altered_test["forward_profitable_after_cost"]

    first_ridge = train_and_predict("ridge", train, test, FEATURES, seed=17)
    second_ridge = train_and_predict("ridge", train, altered_test, FEATURES, seed=17)
    first_logistic = train_and_predict("logistic", train, test, FEATURES, seed=17)
    second_logistic = train_and_predict("logistic", train, altered_test, FEATURES, seed=17)

    assert first_ridge.values == second_ridge.values
    assert first_logistic.values == second_logistic.values
    assert first_ridge.manifest == second_ridge.manifest
    assert first_logistic.manifest == second_logistic.manifest
    assert first_ridge.manifest["feature_ids"] == list(FEATURES)
    assert first_ridge.manifest["random_seed"] == 17
    assert len(first_ridge.manifest["fitted_state"]["coefficients"]) == len(FEATURES)
    assert len(first_ridge.manifest["fitted_state"]["imputer_statistics"]) == len(FEATURES)
    assert len(first_ridge.manifest["fitted_state"]["scaler_mean"]) == len(FEATURES)
    assert len(first_logistic.manifest["fitted_state"]["coefficients"]) == len(FEATURES)
    assert isinstance(first_logistic.manifest["fitted_state"]["intercept"], float)


def test_train_only_scaling_is_not_changed_by_an_extreme_second_test_row() -> None:
    train, test = regression_frames()
    one_row = test.iloc[[0]].copy()
    with_extreme = pd.concat(
        [
            one_row,
            pd.DataFrame(
                {
                    "factor_a": [1_000_000.0],
                    "factor_b": [-1_000_000.0],
                    "forward_long_net_return": [0.0],
                    "forward_profitable_after_cost": [0],
                }
            ),
        ],
        ignore_index=True,
    )

    isolated = train_and_predict("ridge", train, one_row, FEATURES, seed=5)
    combined = train_and_predict("ridge", train, with_extreme, FEATURES, seed=5)

    assert np.isclose(isolated.values[0], combined.values[0], rtol=0, atol=1e-12)


def test_ridge_beats_equal_weight_on_a_known_linear_oos_signal() -> None:
    train, test = regression_frames()
    ridge = train_and_predict("ridge", train, test, FEATURES, seed=42)
    baseline = train_and_predict("equal_weight", train, test, FEATURES, seed=42)
    target = test["forward_long_net_return"].to_numpy()

    ridge_mse = float(np.mean((np.asarray(ridge.values) - target) ** 2))
    baseline_mse = float(np.mean((np.asarray(baseline.values) - target) ** 2))

    assert ridge_mse < baseline_mse * 0.1


def test_logistic_fails_closed_when_train_has_only_one_class() -> None:
    train, test = regression_frames()
    train["forward_profitable_after_cost"] = 1

    with pytest.raises(FactorModelError, match="classes"):
        train_and_predict("logistic", train, test, FEATURES, seed=42)


def test_model_rejects_unknown_type_missing_feature_and_non_finite_prediction_input() -> None:
    train, test = regression_frames()

    with pytest.raises(FactorModelError, match="model"):
        train_and_predict("deep_network", train, test, FEATURES, seed=42)
    with pytest.raises(FactorModelError, match="feature"):
        train_and_predict("ridge", train.drop(columns=["factor_b"]), test, FEATURES, seed=42)
    invalid = test.copy()
    invalid.loc[0, "factor_a"] = np.inf
    with pytest.raises(FactorModelError, match="finite"):
        train_and_predict("ridge", train, invalid, FEATURES, seed=42)
