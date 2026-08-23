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
