"""Shared A-share spot matching rules for backtest and paper.

Cash ledger only: commission + stamp duty + transfer fee. No margin, funding,
or contract sizing. Instrument key is ``code.market`` (for example ``600000.SH``).
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional, Sequence

LOT_SIZE = 100
DEFAULT_ASHARE_COST = {
    "commission_rate": 0.0003,
    "minimum_commission": 5.0,
    "stamp_duty_rate": 0.0005,
    "transfer_fee_rate": 0.00001,
    "slippage_rate": 0.0,
}

REJECTION_REASONS = {
    "INVALID_LOT_SIZE": "买入委托必须为 100 股整数手",
    "T1_NOT_AVAILABLE": "卖出数量超过 T+1 可用数量",
    "SUSPENDED": "证券停牌或没有可执行日线",
    "LIMIT_UP": "涨停价不接受买入",
    "LIMIT_DOWN": "跌停价不接受卖出",
    "INSUFFICIENT_CASH": "可用现金不足",
    "NOT_A_TRADING_DAY": "该日期不是交易日",
    "INVALID_EXECUTION_PRICE": "执行价格不可用",
    "INVALID_SYMBOL": "证券代码缺少交易所身份",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def instrument_key(symbol: Any) -> str:
    """Canonical A-share key: ``code.market``."""
    raw = str(symbol or "").strip().upper().replace("-", "_")
    if not raw:
        return ""
    if "." in raw and "_" not in raw.split(".", 1)[0]:
        code, market = raw.split(".", 1)
        digits = "".join(character for character in code if character.isdigit())
        market = market.replace("_", "")
        if len(digits) == 6 and market in {"SH", "SZ", "BJ"}:
            return f"{digits}.{market}"
    if raw.startswith(("SH_", "SZ_", "BJ_")):
        market, code = raw.split("_", 1)
        digits = "".join(character for character in code if character.isdigit())
        if len(digits) == 6:
            return f"{digits}.{market}"
    digits = "".join(character for character in raw if character.isdigit())
    if len(digits) != 6:
        return raw
    if digits.startswith("6"):
        return f"{digits}.SH"
    if digits.startswith(("0", "3")):
        return f"{digits}.SZ"
    if digits.startswith(("4", "8", "9")):
        return f"{digits}.BJ"
    return raw


def storage_symbol(symbol: Any) -> str:
    """Legacy sealed-snapshot form ``SH_600000``."""
    key = instrument_key(symbol)
    if "." not in key:
        return str(symbol or "").strip().upper()
    code, market = key.split(".", 1)
    return f"{market}_{code}"


def symbol_aliases(symbol: Any) -> tuple[str, ...]:
    key = instrument_key(symbol)
    stored = storage_symbol(symbol)
    aliases = {str(symbol or "").strip(), key, stored}
    return tuple(item for item in aliases if item)


def is_trading_day(trade_date: str, calendar_rows: Sequence[Mapping[str, Any]] | None) -> bool:
    if not calendar_rows:
        return True
    wanted = str(trade_date)[:10]
    for row in calendar_rows:
        date_text = str(row.get("trade_date") or row.get("cal_date") or "")[:10]
        if date_text != wanted:
            continue
        flag = row.get("is_open")
        if flag in (None, ""):
            return True
        return str(flag).strip() in {"1", "true", "True"}
    return False


def compute_fees(side: str, amount: float, cost_model: Mapping[str, Any] | None = None) -> dict[str, float]:
    cost = {**DEFAULT_ASHARE_COST, **dict(cost_model or {})}
    commission = max(amount * _number(cost.get("commission_rate")), _number(cost.get("minimum_commission"), 5.0))
    tax = amount * _number(cost.get("stamp_duty_rate")) if side == "sell" else 0.0
    transfer_fee = amount * _number(cost.get("transfer_fee_rate"))
    return {"commission": commission, "tax": tax, "transfer_fee": transfer_fee}


def cash_delta(side: str, amount: float, fees: Mapping[str, float]) -> float:
    if side == "buy":
        return -(amount + _number(fees.get("commission")) + _number(fees.get("transfer_fee")))
    return amount - _number(fees.get("commission")) - _number(fees.get("tax")) - _number(fees.get("transfer_fee"))


def buy_book_cost(amount: float, fees: Mapping[str, float]) -> float:
    return amount + _number(fees.get("commission")) + _number(fees.get("transfer_fee"))


def sell_fee_total(fees: Mapping[str, float]) -> float:
    return _number(fees.get("commission")) + _number(fees.get("tax")) + _number(fees.get("transfer_fee"))


def round_lot(quantity: int, *, explicit: bool = False) -> tuple[int, Optional[str]]:
    if quantity == 0:
        return 0, None
    if explicit and quantity % LOT_SIZE != 0:
        return 0, "INVALID_LOT_SIZE"
    return (quantity // LOT_SIZE) * LOT_SIZE, None


def reject_market_constraint(
    *,
    side: str,
    price: float,
    bar: Mapping[str, Any] | None,
    limit_rule: Mapping[str, Any] | None,
    suspended: bool,
) -> Optional[str]:
    if suspended or not bar:
        return "SUSPENDED"
    if price <= 0:
        return "INVALID_EXECUTION_PRICE"
    if not limit_rule or not bool(limit_rule.get("has_price_limit", True)):
        return None
    if side == "buy" and limit_rule.get("up_limit") is not None and price >= _number(limit_rule["up_limit"]):
        return "LIMIT_UP"
    if side == "sell" and limit_rule.get("down_limit") is not None and price <= _number(limit_rule["down_limit"]):
        return "LIMIT_DOWN"
    return None


def lookup_row(
    rows: Sequence[Mapping[str, Any]],
    *,
    trade_date: str,
    symbol: str,
) -> Optional[dict[str, Any]]:
    aliases = {item.upper() for item in symbol_aliases(symbol)}
    wanted = str(trade_date)[:10]
    for row in rows:
        date_text = str(row.get("trade_date") or "")[:10]
        row_symbol = instrument_key(row.get("symbol") or row.get("ts_code") or "")
        stored = storage_symbol(row.get("symbol") or row.get("ts_code") or "")
        if date_text == wanted and ({row_symbol, stored, str(row.get("symbol") or "").upper()} & aliases):
            return dict(row)
    return None


def is_suspended(rows: Sequence[Mapping[str, Any]], *, trade_date: str, symbol: str) -> bool:
    row = lookup_row(rows, trade_date=trade_date, symbol=symbol)
    if not row:
        return False
    return str(row.get("suspend_type") or "S").upper() == "S"


def rejection_reason(code: str) -> str:
    return REJECTION_REASONS.get(code, code)


class AShareSpotBroker:
    """Cash-ledger A-share spot broker used by paper and aligned with backtest."""

    def __init__(
        self,
        cost_model: Mapping[str, Any] | None = None,
        *,
        calendar_rows: Sequence[Mapping[str, Any]] = (),
        price_limits: Sequence[Mapping[str, Any]] = (),
        suspensions: Sequence[Mapping[str, Any]] = (),
    ):
        self.cost_model = {**DEFAULT_ASHARE_COST, **dict(cost_model or {})}
        self.calendar_rows = list(calendar_rows)
        self.price_limits = list(price_limits)
        self.suspensions = list(suspensions)

    def evaluate(
        self,
        *,
        side: str,
        symbol: str,
        quantity: int,
        price: float,
        trade_date: str,
        cash: float,
        available_quantity: int,
        bar: Mapping[str, Any] | None,
        explicit_lot: bool = False,
    ) -> dict[str, Any]:
        key = instrument_key(symbol)
        if not key or "." not in key:
            return self._reject("INVALID_SYMBOL")
        if not is_trading_day(trade_date, self.calendar_rows):
            return self._reject("NOT_A_TRADING_DAY")
        lots, lot_error = round_lot(int(quantity), explicit=explicit_lot)
        if lot_error:
            return self._reject(lot_error)
        if lots <= 0:
            return self._reject("INVALID_LOT_SIZE")
        if side == "sell" and lots > int(available_quantity or 0):
            return self._reject("T1_NOT_AVAILABLE")
        suspended = is_suspended(self.suspensions, trade_date=trade_date, symbol=key)
        limit_rule = lookup_row(self.price_limits, trade_date=trade_date, symbol=key)
        constraint = reject_market_constraint(
            side=side,
            price=price,
            bar=bar,
            limit_rule=limit_rule,
            suspended=suspended,
        )
        if constraint:
            return self._reject(constraint)
        amount = price * lots
        fees = compute_fees(side, amount, self.cost_model)
        if side == "buy" and cash + cash_delta(side, amount, fees) < -1e-9:
            return self._reject("INSUFFICIENT_CASH")
        return {
            "accepted": True,
            "symbol": key,
            "storage_symbol": storage_symbol(key),
            "side": side,
            "quantity": lots,
            "price": price,
            "amount": amount,
            "fees": fees,
            "cash_delta": cash_delta(side, amount, fees),
            "book_cost": buy_book_cost(amount, fees) if side == "buy" else None,
            "rejection_code": None,
            "rejection_reason": None,
        }

    @staticmethod
    def _reject(code: str) -> dict[str, Any]:
        return {
            "accepted": False,
            "rejection_code": code,
            "rejection_reason": rejection_reason(code),
            "fees": {"commission": 0.0, "tax": 0.0, "transfer_fee": 0.0},
            "cash_delta": 0.0,
        }

