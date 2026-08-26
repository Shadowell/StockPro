"""Deterministic, train-only-fit machine-learning models for FactorLab."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class FactorModelError(ValueError):
    """Raised when a model cannot be trained without weakening the contract."""


@dataclass(frozen=True)
class ModelPrediction:
    model_type: str
    values: tuple[float, ...]
    manifest: Mapping[str, Any]


def _load_sklearn():
    try:
        import sklearn
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression, Ridge
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise FactorModelError("scikit-learn is required for FactorLab model training") from exc
    return sklearn, SimpleImputer, LogisticRegression, Ridge, Pipeline, StandardScaler


def _feature_matrix(frame: pd.DataFrame, feature_ids: tuple[str, ...], *, name: str) -> np.ndarray:
    missing = [feature for feature in feature_ids if feature not in frame.columns]
    if missing:
        raise FactorModelError(f"{name} frame is missing feature columns: {missing}")
    try:
        matrix = frame.loc[:, list(feature_ids)].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise FactorModelError(f"{name} feature values must be numeric") from exc
    if np.isinf(matrix).any():
        raise FactorModelError(f"{name} feature values must be finite or missing")
    return matrix


def _target(frame: pd.DataFrame, column: str) -> np.ndarray:
    if column not in frame.columns:
        raise FactorModelError(f"train frame is missing target column: {column}")
    try:
        values = frame[column].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise FactorModelError("training target must be numeric") from exc
    if not np.isfinite(values).all():
        raise FactorModelError("training target must be finite")
    return values


def train_and_predict(
    model_type: str,
    train_frame: pd.DataFrame,
    test_frame: pd.DataFrame,
    feature_ids: Sequence[str],
    *,
    seed: int,
) -> ModelPrediction:
    model_name = str(model_type or "").strip().lower()
    if model_name not in {"equal_weight", "ridge", "logistic"}:
        raise FactorModelError(f"unsupported factor model: {model_type}")
    features = tuple(str(feature) for feature in feature_ids)
    if not features or len(set(features)) != len(features):
        raise FactorModelError("feature_ids must be non-empty and unique")
    if train_frame.empty or test_frame.empty:
        raise FactorModelError("train and test frames must be non-empty")
    sklearn, SimpleImputer, LogisticRegression, Ridge, Pipeline, StandardScaler = _load_sklearn()
    train_x = _feature_matrix(train_frame, features, name="train")
    test_x = _feature_matrix(test_frame, features, name="test")
    seed = int(seed)
    parameters: dict[str, Any]
    fitted_state: dict[str, Any]
    try:
        if model_name == "equal_weight":
            transformer = Pipeline(
                [
                    ("imputer", SimpleImputer(strategy="median")),
                    ("scaler", StandardScaler()),
                ]
            )
            transformer.fit(train_x)
            predictions = transformer.transform(test_x).mean(axis=1)
            parameters = {"imputer": "median", "scaler": "standard", "weights": "equal"}
            fitted_state = _fitted_transform_state(transformer)
            fitted_state.update(
                {
                    "coefficients": [1.0 / len(features)] * len(features),
                    "intercept": 0.0,
                }
            )
        elif model_name == "ridge":
            train_y = _target(train_frame, "forward_long_net_return")
            model = Pipeline(
                [
                    ("imputer", SimpleImputer(strategy="median")),
                    ("scaler", StandardScaler()),
                    ("model", Ridge(alpha=1.0)),
                ]
            )
            model.fit(train_x, train_y)
            predictions = model.predict(test_x)
            parameters = {"imputer": "median", "scaler": "standard", "alpha": 1.0}
            fitted_state = _fitted_transform_state(model)
            fitted_state.update(
                {
                    "coefficients": [float(value) for value in model.named_steps["model"].coef_],
                    "intercept": float(model.named_steps["model"].intercept_),
                }
            )
        else:
            train_y = _target(train_frame, "forward_profitable_after_cost").astype(int)
            if len(np.unique(train_y)) < 2:
                raise FactorModelError("logistic training requires at least two target classes")
            model = Pipeline(
                [
                    ("imputer", SimpleImputer(strategy="median")),
                    ("scaler", StandardScaler()),
                    (
                        "model",
                        LogisticRegression(
                            C=1.0,
                            max_iter=1000,
                            random_state=seed,
                            solver="lbfgs",
                        ),
                    ),
                ]
            )
            model.fit(train_x, train_y)
            predictions = model.predict_proba(test_x)[:, 1] * 2.0 - 1.0
            parameters = {
                "imputer": "median",
                "scaler": "standard",
                "C": 1.0,
                "solver": "lbfgs",
                "max_iter": 1000,
            }
            fitted_state = _fitted_transform_state(model)
            fitted_state.update(
                {
                    "coefficients": [
                        float(value) for value in model.named_steps["model"].coef_[0]
                    ],
                    "intercept": float(model.named_steps["model"].intercept_[0]),
                    "classes": [int(value) for value in model.named_steps["model"].classes_],
                }
            )
    except FactorModelError:
        raise
    except Exception as exc:
        raise FactorModelError(f"factor model training failed: {model_name}") from exc
    if not np.isfinite(predictions).all():
        raise FactorModelError("factor model produced non-finite predictions")
    training_end = (
        int(train_frame["decision_time"].max())
        if "decision_time" in train_frame.columns
        else None
    )
    manifest = {
        "schema_version": "factor-model-v1",
        "model_type": model_name,
        "feature_ids": list(features),
        "random_seed": seed,
        "training_rows": int(len(train_frame)),
        "training_decision_time_max": training_end,
        "parameters": parameters,
        "fitted_state": fitted_state,
        "library_versions": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
    }
    return ModelPrediction(
        model_type=model_name,
        values=tuple(float(value) for value in predictions),
        manifest=manifest,
    )


def _fitted_transform_state(pipeline: Pipeline) -> dict[str, Any]:
    imputer = pipeline.named_steps["imputer"]
    scaler = pipeline.named_steps["scaler"]
    return {
        "imputer_statistics": [float(value) for value in imputer.statistics_],
        "scaler_mean": [float(value) for value in scaler.mean_],
        "scaler_scale": [float(value) for value in scaler.scale_],
    }
