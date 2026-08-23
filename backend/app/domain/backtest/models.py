from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping, Sequence
from uuid import UUID


@dataclass(frozen=True)
class BacktestRequest:
    strategy_version_id: UUID
    dataset_snapshot_id: int
    universe_snapshot_id: int
    factor_snapshot_id: int | None
    pool_snapshot_id: int | None
    cost_model_id: UUID
    research_protocol_id: UUID | None
    symbols: tuple[str, ...]
    start_date: date
    end_date: date
    initial_cash: Decimal
    parameters: Mapping[str, object]


@dataclass(frozen=True)
class BacktestJobView:
    job_id: UUID
    status: str
    progress: int
    run_id: UUID | None
    message: str


@dataclass(frozen=True)
class WalkForwardRequest:
    backtest: BacktestRequest
    parameter_grid: Mapping[str, Sequence[object]]
    objective: str
    train_sessions: int
    test_sessions: int
    step_sessions: int
