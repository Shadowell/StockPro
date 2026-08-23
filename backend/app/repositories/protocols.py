from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class StorageHealth:
    status: Literal["healthy", "error"]
    database: Literal["postgresql"]
    applied_migrations: int
    expected_migrations: int


class HealthRepository(Protocol):
    def storage_health(self) -> StorageHealth: ...


class AuthRepository(Protocol):
    """Authentication persistence contract; methods are added in Wave 1 Task 4."""


class MarketRepository(Protocol):
    """A-share market read contract; methods are added in Wave 2."""


class StrategyRepository(Protocol):
    """Strategy persistence contract; methods are added in Wave 3."""


class BacktestRepository(Protocol):
    """Backtest persistence contract; methods are added in Wave 3."""


class PaperRepository(Protocol):
    """Paper continuity contract; methods are added in Wave 3."""


@dataclass(frozen=True)
class Repositories:
    health: HealthRepository
    auth: AuthRepository
