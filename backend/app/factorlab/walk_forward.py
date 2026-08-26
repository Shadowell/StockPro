"""Purged expanding walk-forward splits keyed by decision time."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class WalkForwardSplitError(ValueError):
    """Raised when a requested OOS split cannot preserve time boundaries."""


@dataclass(frozen=True)
class WalkForwardFold:
    fold_index: int
    train_times: tuple[int, ...]
    validation_times: tuple[int, ...]
    test_times: tuple[int, ...]


class PurgedWalkForwardSplitter:
    def __init__(
        self,
        *,
        n_splits: int,
        purge_bars: int,
        embargo_bars: int,
        label_horizon_bars: int | None = None,
    ) -> None:
        self.n_splits = int(n_splits)
        self.purge_bars = int(purge_bars)
        self.embargo_bars = int(embargo_bars)
        self.label_horizon_bars = (
            None if label_horizon_bars is None else int(label_horizon_bars)
        )
        if self.n_splits < 2:
            raise WalkForwardSplitError("n_splits must be at least 2")
        if self.purge_bars < 0 or self.embargo_bars < 0:
            raise WalkForwardSplitError("purge and embargo must be non-negative")
        if self.label_horizon_bars is not None and (
            self.purge_bars < self.label_horizon_bars
            or self.embargo_bars < self.label_horizon_bars
        ):
            raise WalkForwardSplitError("purge and embargo must cover the label horizon")

    def split(self, decision_times: Iterable[int]) -> list[WalkForwardFold]:
        unique_times = tuple(sorted({int(value) for value in decision_times}))
        block_count = self.n_splits + 2
        if len(unique_times) < block_count:
            raise WalkForwardSplitError("insufficient unique decision times for walk-forward")
        boundaries = [index * len(unique_times) // block_count for index in range(block_count + 1)]
        blocks = [unique_times[boundaries[index] : boundaries[index + 1]] for index in range(block_count)]
        if any(not block for block in blocks):
            raise WalkForwardSplitError("insufficient unique decision times for walk-forward")

        folds: list[WalkForwardFold] = []
        for fold_index in range(self.n_splits):
            raw_train = tuple(value for block in blocks[: fold_index + 1] for value in block)
            train = raw_train[: len(raw_train) - self.purge_bars] if self.purge_bars else raw_train
            validation = blocks[fold_index + 1]
            test = blocks[fold_index + 2][self.embargo_bars :]
            if not train or not validation or not test:
                raise WalkForwardSplitError("insufficient times after purge and embargo")
            folds.append(
                WalkForwardFold(
                    fold_index=fold_index,
                    train_times=tuple(train),
                    validation_times=tuple(validation),
                    test_times=tuple(test),
                )
            )
        return folds
