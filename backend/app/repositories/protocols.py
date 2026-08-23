from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from app.domain.instruments.models import InstrumentContract
from app.domain.research.models import InstrumentDetailView, MarketOverviewView


@dataclass(frozen=True)
class StorageHealth:
    status: Literal["healthy", "error"]
    database: Literal["postgresql"]
    applied_migrations: int
    expected_migrations: int


class HealthRepository(Protocol):
    def storage_health(self) -> StorageHealth: ...


class AuthRepository(Protocol):
    def get_active_guest_code(
        self,
        code_hash: str,
        now: datetime,
    ) -> dict[str, Any] | None: ...

    def get_active_guest_code_by_id(
        self,
        code_id: int,
        now: datetime,
    ) -> dict[str, Any] | None: ...

    def touch_guest_code(self, code_id: int, now: datetime) -> None: ...

    def record_auth_event(
        self,
        *,
        event_type: str,
        role: str,
        subject_id: str | None,
        guest_code_id: int | None,
        success: bool,
        reason: str | None,
        metadata: dict[str, object],
    ) -> None: ...


class MarketRepository(Protocol):
    def market_overview(self) -> MarketOverviewView: ...

    def search_instruments(
        self,
        query: str,
        asset_class: str | None,
        limit: int,
    ) -> list[InstrumentContract]: ...

    def instrument_detail(self, symbol: str) -> InstrumentDetailView | None: ...

    def daily_bars(self, symbol: str, limit: int) -> list[dict[str, Any]]: ...

    def list_watchlist(self, owner: str) -> list[dict[str, Any]]: ...

    def upsert_watchlist(self, owner: str, symbol: str, note: str) -> dict[str, Any]: ...

    def delete_watchlist(self, owner: str, entry_id: int) -> bool: ...


class StrategyRepository(Protocol):
    """Strategy persistence contract; methods are added in Wave 3."""


class BacktestRepository(Protocol):
    """Backtest persistence contract; methods are added in Wave 3."""


class PaperRepository(Protocol):
    """Paper continuity contract; methods are added in Wave 3."""


class PoolRepository(Protocol):
    def list_pools(self) -> list[dict[str, Any]]: ...
    def get_pool(self, pool_id: str) -> dict[str, Any]: ...
    def create_pool(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def generate(self, pool_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def members(self, pool_id: str, generation_id: str | None = None) -> list[dict[str, Any]]: ...
    def seal_snapshot(self, pool_id: str, generation_id: str | None = None) -> dict[str, Any]: ...
    def list_snapshots(self, pool_id: str | None = None) -> list[dict[str, Any]]: ...
    def get_snapshot(self, snapshot_id: int) -> dict[str, Any]: ...


class FactorRepository(Protocol):
    def list_library(self) -> list[dict[str, Any]]: ...
    def create_factor(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def create_version(self, definition_id: int, payload: dict[str, Any]) -> dict[str, Any]: ...
    def validate_version(self, version_id: int) -> dict[str, Any]: ...
    def compute_factor(self, version_id: int, trade_date: str, dataset_snapshot_id: int, universe_snapshot_id: int) -> dict[str, Any]: ...
    def factor_metrics(self, factor_identifier: str) -> dict[str, Any]: ...
    def factor_values(self, factor_identifier: str, limit: int, offset: int) -> dict[str, Any]: ...
    def list_runs(self, limit: int) -> list[dict[str, Any]]: ...
    def list_correlations(self, trade_date: str | None, limit: int) -> list[dict[str, Any]]: ...
    def list_snapshots(self, limit: int) -> list[dict[str, Any]]: ...
    def get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None: ...
    def snapshot_values(self, snapshot_id: int, factor_code: str | None, limit: int) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Repositories:
    health: HealthRepository
    auth: AuthRepository
    market: MarketRepository
    pools: PoolRepository
    factors: FactorRepository
