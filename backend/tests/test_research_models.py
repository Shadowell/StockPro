from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.instruments.models import InstrumentContract
from app.domain.research.models import MarketOverviewView


def test_stock_instrument_keeps_futures_fields_unavailable() -> None:
    item = InstrumentContract.stock(
        symbol="600519.SH",
        exchange="SSE",
        currency="CNY",
        tick_size=Decimal("0.01"),
        lot_size=100,
        name="贵州茅台",
    )

    assert item.asset_class == "stock"
    assert item.market == "CN"
    assert item.contract_multiplier is None
    assert item.margin_rate is None
    assert item.expiry_date is None
    assert item.session_calendar == "CN_A_SHARE"
    assert item.shortable is False


def test_stock_instrument_rejects_invalid_trade_units() -> None:
    with pytest.raises(ValueError, match="tick_size"):
        InstrumentContract.stock(
            symbol="600519.SH",
            exchange="SSE",
            currency="CNY",
            tick_size=Decimal("0"),
            lot_size=100,
        )
    with pytest.raises(ValueError, match="lot_size"):
        InstrumentContract.stock(
            symbol="600519.SH",
            exchange="SSE",
            currency="CNY",
            tick_size=Decimal("0.01"),
            lot_size=0,
        )


def test_market_overview_preserves_missing_blocks() -> None:
    view = MarketOverviewView(
        indices=(),
        breadth=None,
        turnover=None,
        limit_ecology=None,
        sector_flows=(),
        source_label="PostgreSQL market cache",
        source_updated_at=None,
        trade_date=None,
        data_status="empty",
    )

    assert view.breadth is None
    assert view.turnover is None
    assert view.limit_ecology is None
    assert view.data_status == "empty"
