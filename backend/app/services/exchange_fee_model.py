"""Exchange fee defaults used by research, backtests and paper execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeeSchedule:
    exchange: str
    market_type: str
    maker_fee_bps: float
    taker_fee_bps: float


_FEE_SCHEDULES = {
    ("okx", "spot"): FeeSchedule("okx", "spot", maker_fee_bps=8.0, taker_fee_bps=10.0),
    ("okx", "swap"): FeeSchedule("okx", "swap", maker_fee_bps=2.0, taker_fee_bps=5.0),
    ("binanceusdm", "swap"): FeeSchedule("binanceusdm", "swap", maker_fee_bps=1.8, taker_fee_bps=4.5),
}


def normalize_exchange_id(exchange: str | None) -> str:
    value = str(exchange or "okx").strip().lower()
    if ":" in value:
        value = value.split(":", 1)[0]
    if value in {"binance", "binance_usdm", "binance-usdm", "binanceusdsm"}:
        return "binanceusdm"
    return value or "okx"


def normalize_market_type(market_type: str | None) -> str:
    value = str(market_type or "swap").strip().lower()
    if value in {"future", "futures", "perp", "perpetual", "contract"}:
        return "swap"
    if value in {"margin"}:
        return "spot"
    return value or "swap"


def default_fee_schedule(exchange: str | None, market_type: str | None = "swap") -> FeeSchedule:
    exchange_id = normalize_exchange_id(exchange)
    market = normalize_market_type(market_type)
    schedule = _FEE_SCHEDULES.get((exchange_id, market))
    if schedule:
        return schedule
    if market == "spot":
        return _FEE_SCHEDULES[("okx", "spot")]
    return _FEE_SCHEDULES[("okx", "swap")]


def fee_bps_for_liquidity(
    exchange: str | None,
    market_type: str | None,
    liquidity: str | None,
) -> float:
    schedule = default_fee_schedule(exchange, market_type)
    return schedule.maker_fee_bps if str(liquidity or "").lower() == "maker" else schedule.taker_fee_bps


def market_order_fee_bps(exchange: str | None, market_type: str | None = "swap") -> float:
    return default_fee_schedule(exchange, market_type).taker_fee_bps
