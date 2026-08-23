from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class InstrumentContract:
    symbol: str
    name: str | None
    asset_class: Literal["stock", "etf", "index", "future"]
    market: Literal["CN", "US"]
    exchange: str
    currency: str
    tick_size: Decimal
    lot_size: int
    contract_multiplier: Decimal | None = None
    margin_rate: Decimal | None = None
    expiry_date: date | None = None
    last_trade_date: date | None = None
    settlement_type: str | None = None
    session_calendar: str | None = None
    shortable: bool = False

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if not self.exchange.strip():
            raise ValueError("exchange is required")
        if self.tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")
        if self.asset_class != "future" and any(
            value is not None
            for value in (
                self.contract_multiplier,
                self.margin_rate,
                self.expiry_date,
                self.last_trade_date,
                self.settlement_type,
            )
        ):
            raise ValueError("futures contract fields require asset_class=future")

    @classmethod
    def stock(
        cls,
        symbol: str,
        exchange: str,
        currency: str,
        tick_size: Decimal,
        lot_size: int,
        name: str | None = None,
    ) -> "InstrumentContract":
        return cls(
            symbol=symbol,
            name=name,
            asset_class="stock",
            market="CN",
            exchange=exchange,
            currency=currency,
            tick_size=tick_size,
            lot_size=lot_size,
            session_calendar="CN_A_SHARE",
            shortable=False,
        )
