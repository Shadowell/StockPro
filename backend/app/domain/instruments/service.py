from __future__ import annotations

from datetime import datetime
from typing import Any


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return datetime.strptime(raw, "%Y%m%d").date().isoformat()


def _canonical_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if "." not in raw:
        raise ValueError(f"TuShare stock_basic returned invalid ts_code: {raw or '<empty>'}")
    digits, exchange = raw.rsplit(".", 1)
    numeric = digits[1:] if digits.startswith("T") else digits
    if len(numeric) != 6 or not numeric.isdigit() or exchange not in {"SH", "SZ", "BJ"}:
        raise ValueError(f"TuShare stock_basic returned invalid ts_code: {raw}")
    return f"{digits}.{exchange}"


def _normalize_instruments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        symbol = _canonical_symbol(row.get("ts_code"))
        name = str(row.get("name") or "").strip()
        if not name:
            raise ValueError(f"A-share instrument {symbol} has no Chinese name")
        suffix = symbol.rsplit(".", 1)[1]
        result.append({
            "symbol": symbol,
            "exchange": {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[suffix],
            "name": name,
            "industry": str(row.get("industry") or "").strip() or None,
            "board": str(row.get("market") or "").strip() or None,
            "list_status": str(row.get("list_status") or "L").strip().upper(),
            "list_date": _date(row.get("list_date")),
            "delist_date": _date(row.get("delist_date")),
            "is_hs": str(row.get("is_hs") or "").strip() or None,
        })
    result.sort(key=lambda item: item["symbol"])
    return result


def _normalize_daily_rows(
    rows: list[dict[str, Any]],
    daily_basic: list[dict[str, Any]],
    names: dict[str, str],
) -> list[dict[str, Any]]:
    basics = {_canonical_symbol(row.get("ts_code")): row for row in daily_basic}
    result: list[dict[str, Any]] = []
    for row in rows:
        symbol = _canonical_symbol(row.get("ts_code"))
        name = names.get(symbol, "").strip()
        if not name:
            raise ValueError(f"A-share daily row {symbol} has no Chinese name")
        suffix = symbol.rsplit(".", 1)[1]
        basic = basics.get(symbol, {})
        volume_hands = _number(row.get("vol"))
        amount_thousands = _number(row.get("amount"))
        result.append({
            "symbol": symbol,
            "storage_symbol": f"{suffix}_{symbol.split('.', 1)[0]}",
            "name": name,
            "trade_date": _date(row.get("trade_date")),
            "open": _number(row.get("open")),
            "high": _number(row.get("high")),
            "low": _number(row.get("low")),
            "close": _number(row.get("close")),
            "pre_close": _number(row.get("pre_close")),
            "change_percent": _number(row.get("pct_chg")),
            "volume": int(round(volume_hands * 100)) if volume_hands is not None else None,
            "amount": amount_thousands * 1000 if amount_thousands is not None else None,
            "turnover_rate": _number(basic.get("turnover_rate")),
            "volume_ratio": _number(basic.get("volume_ratio")),
            "pe": _number(basic.get("pe")),
            "pb": _number(basic.get("pb")),
            "total_market_cap": (_number(basic.get("total_mv")) or 0) * 10_000 if basic.get("total_mv") not in (None, "") else None,
            "float_market_cap": (_number(basic.get("circ_mv")) or 0) * 10_000 if basic.get("circ_mv") not in (None, "") else None,
        })
    result.sort(key=lambda item: item["symbol"])
    return result


class AshareInstrumentSyncService:
    def __init__(self, *, repository=None, provider=None):
        if repository is None:
            from app.domain.instruments.repository import AshareInstrumentRepository
            repository = AshareInstrumentRepository()
        self.repository = repository
        self.provider = provider

    def sync_all(self, *, trigger: str = "manual") -> dict:
        run_id = self.repository.begin_run(trigger)
        if run_id is None:
            return {"status": "locked", "trigger": trigger}
        try:
            provider = self.provider
            if provider is None:
                from app.domain.instruments.provider import TushareAshareProvider
                provider = TushareAshareProvider()
            instruments = _normalize_instruments(provider.fetch_instruments())
            if not instruments:
                raise RuntimeError("TuShare stock_basic returned no A-share instruments")
            names = {item["symbol"]: item["name"] for item in instruments}
            provider_trade_date = provider.latest_open_trade_date()
            trade_date = _date(provider_trade_date)
            daily_rows = _normalize_daily_rows(
                provider.fetch_daily(provider_trade_date),
                provider.fetch_daily_basic(provider_trade_date),
                names,
            )
            if not daily_rows:
                raise RuntimeError(f"TuShare daily returned no rows for open trade date {provider_trade_date}")
            return self.repository.complete_run(run_id, instruments, daily_rows, trade_date)
        except Exception as error:
            self.repository.fail_run(run_id, error)
            raise


instrument_sync_service = AshareInstrumentSyncService()
