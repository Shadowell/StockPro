"""OOS validation, hard gates and ranking score for FactorLab trials."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import numpy as np
import pandas as pd


class FactorValidationError(ValueError):
    """Raised when OOS evidence is malformed or incomplete."""


@dataclass(frozen=True)
class ValidationThresholds:
    min_coverage: float = 0.95
    min_folds: int = 5
    min_profit_factor: float = 1.20
    max_drawdown: float = 0.10
    min_profitable_fold_ratio: float = 0.60
    max_symbol_concentration: float = 0.60
    min_score: float = 70.0
    min_stress_return: float = -0.05
    max_stress_degradation: float = 0.15


@dataclass(frozen=True)
class ValidationReport:
    coverage: float
    fold_count: int
    total_return: float
    stress_total_return: float
    baseline_total_return: float
    profit_factor: float
    max_drawdown: float
    profitable_fold_ratio: float
    symbol_concentration: float
    directional_accuracy: float
    score: float
    hard_gate_failures: tuple[str, ...]
    accepted: bool

    def to_dict(self) -> dict:
        return {
            "coverage": self.coverage,
            "fold_count": self.fold_count,
            "total_return": self.total_return,
            "stress_total_return": self.stress_total_return,
            "baseline_total_return": self.baseline_total_return,
            "profit_factor": self.profit_factor,
            "max_drawdown": self.max_drawdown,
            "profitable_fold_ratio": self.profitable_fold_ratio,
            "symbol_concentration": self.symbol_concentration,
            "directional_accuracy": self.directional_accuracy,
            "score": self.score,
            "hard_gate_failures": list(self.hard_gate_failures),
            "accepted": self.accepted,
        }


def _compound(returns: np.ndarray) -> float:
    if np.any(returns <= -1.0):
        return -1.0
    return float(np.prod(1.0 + returns) - 1.0)


def _profit_factor(returns: np.ndarray) -> float:
    gains = float(returns[returns > 0].sum())
    losses = abs(float(returns[returns < 0].sum()))
    if losses <= 0:
        return 999.0 if gains > 0 else 0.0
    return gains / losses


def _max_drawdown(returns: np.ndarray) -> float:
    equity = np.cumprod(1.0 + returns)
    peaks = np.maximum.accumulate(np.concatenate(([1.0], equity)))
    equity_with_start = np.concatenate(([1.0], equity))
    drawdowns = 1.0 - equity_with_start / peaks
    return float(drawdowns.max())


def _selected_returns(
    frame: pd.DataFrame,
    prediction_column: str,
    long_column: str,
    short_column: str,
) -> np.ndarray:
    predictions = frame[prediction_column].to_numpy(dtype=float)
    long_returns = frame[long_column].to_numpy(dtype=float)
    short_returns = frame[short_column].to_numpy(dtype=float)
    if not (
        np.isfinite(predictions).all()
        and np.isfinite(long_returns).all()
        and np.isfinite(short_returns).all()
    ):
        raise FactorValidationError("OOS predictions and returns must be finite")
    return np.where(predictions >= 0, long_returns, short_returns)


def evaluate_oos(
    frame: pd.DataFrame,
    *,
    coverage: float,
    thresholds: ValidationThresholds | None = None,
) -> ValidationReport:
    thresholds = thresholds or ValidationThresholds()
    required = {
        "fold_index",
        "symbol",
        "decision_time",
        "prediction",
        "baseline_prediction",
        "forward_long_net_return",
        "forward_short_net_return",
        "forward_long_stress_return",
        "forward_short_stress_return",
    }
    missing = required - set(frame.columns)
    if frame.empty or missing:
        raise FactorValidationError(f"OOS evidence is empty or missing columns: {sorted(missing)}")
    if not isfinite(float(coverage)) or not 0 <= float(coverage) <= 1:
        raise FactorValidationError("coverage must be within [0, 1]")
    if frame.duplicated(subset=["symbol", "decision_time"]).any():
        raise FactorValidationError("OOS evidence contains duplicate entity/time rows")
    if int(frame.groupby("decision_time")["fold_index"].nunique().max()) > 1:
        raise FactorValidationError("one decision_time cannot belong to multiple folds")
    ordered = frame.sort_values(["decision_time", "symbol"]).reset_index(drop=True)
    candidate = _selected_returns(
        ordered,
        "prediction",
        "forward_long_net_return",
        "forward_short_net_return",
    )
    stress = _selected_returns(
        ordered,
        "prediction",
        "forward_long_stress_return",
        "forward_short_stress_return",
    )
    baseline_long = (
        "baseline_long_net_return"
        if "baseline_long_net_return" in ordered.columns
        else "forward_long_net_return"
    )
    baseline_short = (
        "baseline_short_net_return"
        if "baseline_short_net_return" in ordered.columns
        else "forward_short_net_return"
    )
    baseline = _selected_returns(
        ordered,
        "baseline_prediction",
        baseline_long,
        baseline_short,
    )
    total_return = _compound(candidate)
    stress_total_return = _compound(stress)
    baseline_total_return = _compound(baseline)
    profit_factor = _profit_factor(candidate)
    max_drawdown = _max_drawdown(candidate)
    fold_returns = [
        _compound(candidate[ordered["fold_index"].to_numpy() == fold])
        for fold in sorted(ordered["fold_index"].unique())
    ]
    fold_count = len(fold_returns)
    profitable_fold_ratio = sum(value > 0 for value in fold_returns) / fold_count
    positive_by_symbol: list[float] = []
    symbols = ordered["symbol"].astype(str).to_numpy()
    for symbol in sorted(set(symbols)):
        symbol_returns = candidate[symbols == symbol]
        positive_by_symbol.append(float(symbol_returns[symbol_returns > 0].sum()))
    total_positive = sum(positive_by_symbol)
    symbol_concentration = 1.0 if total_positive <= 0 else max(positive_by_symbol) / total_positive
    directional_accuracy = float(np.mean(candidate > 0))

    failures: list[str] = []
    if np.any(candidate <= -1.0):
        failures.append("catastrophic_loss")
    if float(coverage) < thresholds.min_coverage:
        failures.append("coverage")
    if fold_count < thresholds.min_folds:
        failures.append("fold_count")
    if total_return <= 0:
        failures.append("cost_return_non_positive")
    if profit_factor < thresholds.min_profit_factor:
        failures.append("profit_factor")
    if max_drawdown > thresholds.max_drawdown:
        failures.append("max_drawdown")
    if profitable_fold_ratio < thresholds.min_profitable_fold_ratio:
        failures.append("profitable_folds")
    if (
        stress_total_return < thresholds.min_stress_return
        or stress_total_return < total_return - thresholds.max_stress_degradation
    ):
        failures.append("stress_collapse")
    if symbol_concentration > thresholds.max_symbol_concentration:
        failures.append("symbol_concentration")
    if total_return <= baseline_total_return:
        failures.append("baseline_not_beaten")

    prediction_points = 25.0 * directional_accuracy
    profitability_points = 25.0 * (
        0.5 * min(max(total_return / 0.10, 0.0), 1.0)
        + 0.5 * min(max(profit_factor / 2.0, 0.0), 1.0)
    )
    stability_points = 20.0 * profitable_fold_ratio
    drawdown_quality = 1.0 - min(max(max_drawdown / max(thresholds.max_drawdown, 1e-12), 0.0), 1.0)
    concentration_quality = 1.0 - min(max(symbol_concentration, 0.0), 1.0)
    risk_points = 15.0 * (0.5 * drawdown_quality + 0.5 * concentration_quality)
    baseline_delta = total_return - baseline_total_return
    baseline_points = 10.0 * min(max(baseline_delta / 0.05, 0.0), 1.0)
    score = round(
        prediction_points + profitability_points + stability_points + risk_points + baseline_points + 5.0,
        6,
    )
    if score < thresholds.min_score:
        failures.append("score_below_threshold")
    if not all(isfinite(value) for value in (total_return, stress_total_return, score)):
        raise FactorValidationError("OOS metrics must be finite")
    return ValidationReport(
        coverage=round(float(coverage), 12),
        fold_count=fold_count,
        total_return=total_return,
        stress_total_return=stress_total_return,
        baseline_total_return=baseline_total_return,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        profitable_fold_ratio=profitable_fold_ratio,
        symbol_concentration=symbol_concentration,
        directional_accuracy=directional_accuracy,
        score=score,
        hard_gate_failures=tuple(failures),
        accepted=not failures,
    )
