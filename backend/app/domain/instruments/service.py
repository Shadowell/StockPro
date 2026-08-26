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


def _compact_date(value: Any) -> str:
    parsed = _date(value)
    if not parsed:
        raise ValueError(f"invalid A-share trade date: {value!r}")
    return parsed.replace("-", "")


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


def _normalize_trade_calendar(rows: list[dict[str, Any]], trade_date: str) -> list[dict[str, Any]]:
    target = _date(trade_date)
    result = []
    for row in rows:
        cal_date = _date(row.get("cal_date"))
        if not cal_date:
            raise ValueError("TuShare trade_cal returned a row without cal_date")
        result.append({
            "exchange": str(row.get("exchange") or "").strip() or "SSE",
            "trade_date": cal_date,
            "is_open": bool(int(row.get("is_open") or 0)),
            "pretrade_date": _date(row.get("pretrade_date")),
            "source": "tushare.trade_cal",
        })
    if target and not any(item["trade_date"] == target for item in result):
        raise ValueError(f"TuShare trade_cal did not return required date {target}")
    result.sort(key=lambda item: (item["trade_date"], item["exchange"]))
    return result


def _normalize_daily_basic_rows(rows: list[dict[str, Any]], names: dict[str, str], trade_date: str) -> list[dict[str, Any]]:
    target = _date(trade_date)
    numeric_fields = (
        "close", "turnover_rate", "turnover_rate_f", "volume_ratio", "pe", "pe_ttm",
        "pb", "ps", "ps_ttm", "dv_ratio", "dv_ttm", "total_mv", "circ_mv",
    )
    result = []
    for row in rows:
        symbol = _canonical_symbol(row.get("ts_code"))
        observed_date = _date(row.get("trade_date"))
        if observed_date != target:
            raise ValueError(f"TuShare daily_basic returned {symbol} for unexpected date {observed_date}")
        item = {
            "symbol": symbol,
            "name": names.get(symbol, ""),
            "trade_date": observed_date,
            "source": "tushare.daily_basic",
        }
        for field in numeric_fields:
            item[field] = _number(row.get(field))
        limit_status = row.get("limit_status")
        item["limit_status"] = int(limit_status) if str(limit_status or "").strip().lstrip("-").isdigit() else None
        result.append(item)
    result.sort(key=lambda item: item["symbol"])
    return result


def _normalize_adj_factor_rows(rows: list[dict[str, Any]], trade_date: str) -> list[dict[str, Any]]:
    target = _date(trade_date)
    result = []
    for row in rows:
        symbol = _canonical_symbol(row.get("ts_code"))
        observed_date = _date(row.get("trade_date"))
        factor = _number(row.get("adj_factor"))
        if observed_date != target:
            raise ValueError(f"TuShare adj_factor returned {symbol} for unexpected date {observed_date}")
        if factor is None or factor <= 0:
            raise ValueError(f"TuShare adj_factor returned invalid factor for {symbol}")
        result.append({"symbol": symbol, "trade_date": observed_date, "adj_factor": factor, "source": "tushare.adj_factor"})
    result.sort(key=lambda item: item["symbol"])
    return result


def _normalize_suspension_rows(rows: list[dict[str, Any]], trade_date: str) -> list[dict[str, Any]]:
    target = _date(trade_date)
    result = []
    for row in rows:
        symbol = _canonical_symbol(row.get("ts_code"))
        observed_date = _date(row.get("trade_date"))
        if observed_date != target:
            raise ValueError(f"TuShare suspend_d returned {symbol} for unexpected date {observed_date}")
        result.append({
            "symbol": symbol,
            "trade_date": observed_date,
            "suspend_timing": str(row.get("suspend_timing") or "").strip() or None,
            "suspend_type": str(row.get("suspend_type") or "").strip() or None,
            "source": "tushare.suspend_d",
        })
    result.sort(key=lambda item: item["symbol"])
    return result


def _normalize_price_limit_rows(rows: list[dict[str, Any]], trade_date: str) -> list[dict[str, Any]]:
    target = _date(trade_date)
    result = []
    for row in rows:
        symbol = _canonical_symbol(row.get("ts_code"))
        observed_date = _date(row.get("trade_date"))
        if observed_date != target:
            raise ValueError(f"TuShare stk_limit returned {symbol} for unexpected date {observed_date}")
        result.append({
            "symbol": symbol,
            "trade_date": observed_date,
            "pre_close": _number(row.get("pre_close")),
            "up_limit": _number(row.get("up_limit")),
            "down_limit": _number(row.get("down_limit")),
            "has_price_limit": row.get("up_limit") not in (None, "") and row.get("down_limit") not in (None, ""),
            "source": "tushare.stk_limit",
        })
    result.sort(key=lambda item: item["symbol"])
    return result


def _normalize_corporate_action_rows(rows: list[dict[str, Any]], trade_date: str) -> list[dict[str, Any]]:
    target = _date(trade_date)
    result = []
    for row in rows:
        symbol = _canonical_symbol(row.get("ts_code"))
        ex_date = _date(row.get("ex_date"))
        if ex_date != target:
            raise ValueError(f"TuShare dividend returned {symbol} for unexpected ex_date {ex_date}")
        announcement = _date(row.get("ann_date") or row.get("imp_ann_date") or row.get("end_date")) or ex_date
        result.append({
            "symbol": symbol,
            "action_type": "dividend",
            "ex_date": ex_date,
            "announcement_available_at": f"{announcement}T18:00:00+08:00",
            "cash_div": _number(row.get("cash_div")),
            "cash_div_tax": _number(row.get("cash_div_tax")),
            "stk_div": _number(row.get("stk_div")),
            "stk_bo_rate": _number(row.get("stk_bo_rate")),
            "stk_co_rate": _number(row.get("stk_co_rate")),
            "source": "tushare.dividend",
        })
    result.sort(key=lambda item: (item["symbol"], item["ex_date"]))
    return result


def _normalize_benchmark_rows(rows: list[dict[str, Any]], trade_date: str) -> list[dict[str, Any]]:
    target = _date(trade_date)
    result = []
    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip().upper()
        observed_date = _date(row.get("trade_date"))
        if observed_date != target:
            raise ValueError(f"TuShare index_daily returned {ts_code} for unexpected date {observed_date}")
        result.append({
            "symbol": _canonical_symbol(ts_code),
            "ts_code": ts_code,
            "trade_date": observed_date,
            "open": _number(row.get("open")),
            "high": _number(row.get("high")),
            "low": _number(row.get("low")),
            "close": _number(row.get("close")),
            "pre_close": _number(row.get("pre_close")),
            "change": _number(row.get("change")),
            "pct_chg": _number(row.get("pct_chg")),
            "vol": _number(row.get("vol")),
            "amount": _number(row.get("amount")),
            "source": "tushare.index_daily",
        })
    required = {"000001.SH", "399001.SZ", "399006.SZ", "000300.SH"}
    returned = {item["ts_code"] for item in result}
    missing = sorted(required - returned)
    if missing:
        raise ValueError(f"TuShare index_daily missing benchmark rows: {', '.join(missing)}")
    result.sort(key=lambda item: item["symbol"])
    return result
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
            compact_trade_date = _compact_date(provider_trade_date)
            trade_calendar = _normalize_trade_calendar(
                provider.fetch_trade_calendar(compact_trade_date, compact_trade_date),
                provider_trade_date,
            )
            daily_basic_raw = provider.fetch_daily_basic(provider_trade_date)
            daily_rows = _normalize_daily_rows(
                provider.fetch_daily(provider_trade_date),
                daily_basic_raw,
                names,
            )
            if not daily_rows:
                raise RuntimeError(f"TuShare daily returned no rows for open trade date {provider_trade_date}")
            daily_basic_rows = _normalize_daily_basic_rows(daily_basic_raw, names, provider_trade_date)
            auxiliary_datasets = {
                "trade_calendar": trade_calendar,
                "daily_basic": daily_basic_rows,
                "adj_factor": _normalize_adj_factor_rows(provider.fetch_adj_factor(provider_trade_date), provider_trade_date),
                "suspensions": _normalize_suspension_rows(provider.fetch_suspensions(provider_trade_date), provider_trade_date),
                "price_limits": _normalize_price_limit_rows(provider.fetch_price_limits(provider_trade_date), provider_trade_date),
                "corporate_actions": _normalize_corporate_action_rows(provider.fetch_corporate_actions(provider_trade_date), provider_trade_date),
                "benchmark_bars": _normalize_benchmark_rows(provider.fetch_benchmark_bars(provider_trade_date), provider_trade_date),
            }
            return self.repository.complete_run(run_id, instruments, daily_rows, trade_date, auxiliary_datasets=auxiliary_datasets)
        except Exception as error:
            self.repository.fail_run(run_id, error)
            raise


instrument_sync_service = AshareInstrumentSyncService()
