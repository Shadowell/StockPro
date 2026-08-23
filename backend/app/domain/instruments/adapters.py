from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Literal, Protocol

from app.domain.instruments.models import InstrumentContract


@dataclass(frozen=True)
class TradingSession:
    start: time
    end: time


@dataclass(frozen=True)
class TradingCalendar:
    code: str
    timezone: str
    sessions: tuple[TradingSession, ...]


@dataclass(frozen=True)
class ExecutionRules:
    lot_size: int
    t_plus_days: int
    shortable: bool
    price_limit_required: bool


class InstrumentAdapter(Protocol):
    asset_class: str
    def calendar(self, instrument: InstrumentContract) -> TradingCalendar: ...
    def execution_rules(self, instrument: InstrumentContract) -> ExecutionRules: ...


class AshareCashAdapter:
    asset_class = "stock"
    def calendar(self, instrument: InstrumentContract) -> TradingCalendar:
        if instrument.market != "CN" or instrument.asset_class not in {"stock", "etf", "index"}:
            raise ValueError("AshareCashAdapter only accepts CN cash instruments")
        return TradingCalendar("CN_A_SHARE", "Asia/Shanghai", (TradingSession(time(9, 30), time(11, 30)), TradingSession(time(13), time(15))))
    def execution_rules(self, instrument: InstrumentContract) -> ExecutionRules:
        return ExecutionRules(instrument.lot_size, 1, instrument.shortable, instrument.asset_class == "stock")


class CnFuturesCtpAdapter(InstrumentAdapter, Protocol):
    asset_class: Literal["future"]
    market: Literal["CN"]


class UsFuturesBrokerAdapter(InstrumentAdapter, Protocol):
    asset_class: Literal["future"]
    market: Literal["US"]
