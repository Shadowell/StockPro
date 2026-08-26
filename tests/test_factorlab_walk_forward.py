from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.factorlab.walk_forward import (  # noqa: E402
    PurgedWalkForwardSplitter,
    WalkForwardSplitError,
)


def test_walk_forward_keeps_same_timestamp_entities_together_and_applies_gaps() -> None:
    decision_times = [time for time in range(24) for _symbol in ("BTC", "ETH")]
    folds = PurgedWalkForwardSplitter(
        n_splits=2,
        purge_bars=2,
        embargo_bars=2,
    ).split(decision_times)

    assert len(folds) == 2
    assert folds[0].train_times == tuple(range(0, 4))
    assert folds[0].validation_times == tuple(range(6, 12))
    assert folds[0].test_times == tuple(range(14, 18))
    assert folds[1].train_times == tuple(range(0, 10))
    assert folds[1].validation_times == tuple(range(12, 18))
    assert folds[1].test_times == tuple(range(20, 24))
    for fold in folds:
        assert not (set(fold.train_times) & set(fold.validation_times))
        assert not (set(fold.validation_times) & set(fold.test_times))
        assert not (set(fold.train_times) & set(fold.test_times))


def test_walk_forward_requires_purge_and_embargo_at_least_label_horizon() -> None:
    with pytest.raises(WalkForwardSplitError, match="horizon"):
        PurgedWalkForwardSplitter(
            n_splits=2,
            purge_bars=2,
            embargo_bars=3,
            label_horizon_bars=3,
        )


def test_walk_forward_rejects_insufficient_unique_times() -> None:
    splitter = PurgedWalkForwardSplitter(
        n_splits=3,
        purge_bars=2,
        embargo_bars=2,
    )

    with pytest.raises(WalkForwardSplitError, match="insufficient"):
        splitter.split([0, 1, 2, 3, 4, 5])
