from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from app.domain.instruments.models import InstrumentContract


DataStatus = Literal["empty", "partial", "fresh", "stale", "error"]


@dataclass(frozen=True)
class IndexView:
    symbol: str
    name: str
    value: Decimal | None
    change_pct: Decimal | None
    source_updated_at: datetime | None


@dataclass(frozen=True)
class MarketBreadthView:
    rise_count: int | None
    flat_count: int | None
    fall_count: int | None


@dataclass(frozen=True)
class TurnoverView:
    amount: Decimal | None
    unit: str


@dataclass(frozen=True)
class LimitEcologyView:
    limit_up_count: int | None
    limit_down_count: int | None
    max_streak: int | None
    broken_board_rate: Decimal | None


@dataclass(frozen=True)
class SectorFlowView:
    sector_code: str
    sector_name: str
    net_inflow: Decimal | None
    change_pct: Decimal | None


@dataclass(frozen=True)
class MarketOverviewView:
    indices: tuple[IndexView, ...]
    breadth: MarketBreadthView | None
    turnover: TurnoverView | None
    limit_ecology: LimitEcologyView | None
    sector_flows: tuple[SectorFlowView, ...]
    source_label: str
    source_updated_at: datetime | None
    trade_date: date | None
    data_status: DataStatus


@dataclass(frozen=True)
class InstrumentDetailView:
    instrument: InstrumentContract
    latest_price: Decimal | None
    change_pct: Decimal | None
    turnover: Decimal | None
    source_updated_at: datetime | None
    trade_date: date | None
    data_status: DataStatus


@dataclass(frozen=True)
class StockPoolView:
    pool_id: str
    name: str
    status: str
    latest_snapshot_id: int | None
    latest_snapshot_status: str | None
    member_count: int | None


@dataclass(frozen=True)
class FactorView:
    factor_code: str
    name: str
    category: str
    latest_version: int | None
    latest_snapshot_id: int | None
    validation_status: str
