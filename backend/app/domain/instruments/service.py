from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


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


def _iso_date(value: Any) -> str:
    raw = str(value or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return datetime.strptime(raw, "%Y%m%d").date().isoformat()
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid A-share history date: {value!r}") from exc


def _history_range(*, history_days: int, start_date: Any = None, end_date: Any = None) -> tuple[str, str]:
    try:
        days = int(history_days)
    except (TypeError, ValueError) as exc:
        raise ValueError("history_days must be an integer") from exc
    if days < 1 or days > 366:
        raise ValueError("history_days must be between 1 and 366")

    end = _iso_date(end_date) if end_date else datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    end_value = date.fromisoformat(end)
    start = _iso_date(start_date) if start_date else (end_value - timedelta(days=days - 1)).isoformat()
    if date.fromisoformat(start) > end_value:
        raise ValueError("history start_date cannot be after end_date")
    return start, end


def _open_history_trade_dates(provider: Any, start_date: str, end_date: str) -> list[str]:
    fetch_open = getattr(provider, "fetch_open_trade_dates", None)
    if callable(fetch_open):
        raw_dates = fetch_open(start_date.replace("-", ""), end_date.replace("-", ""))
        return sorted({_iso_date(value) for value in raw_dates if str(value or "").strip()})

    fetch_calendar = getattr(provider, "fetch_trade_calendar", None)
    if not callable(fetch_calendar):
        raise RuntimeError("TuShare provider does not expose trade calendar")
    try:
        rows = fetch_calendar(start_date.replace("-", ""), end_date.replace("-", ""), is_open="1")
    except TypeError:
        rows = fetch_calendar(start_date.replace("-", ""), end_date.replace("-", ""))
    dates = []
    for row in rows or []:
        value = row.get("cal_date") or row.get("trade_date") or row.get("date")
        is_open = row.get("is_open", 1)
        if str(is_open).strip().lower() not in {"1", "true", "t", "y", "yes", "open"}:
            continue
        if value:
            dates.append(_iso_date(value))
    return sorted(set(dates))


def _previous_compact_date(value: Any, *, days: int = 14) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"invalid A-share trade date: {value!r}")
    return (datetime.strptime(raw, "%Y%m%d").date() - timedelta(days=days)).strftime("%Y%m%d")


def _recent_open_trade_dates(provider: Any, latest_trade_date: str) -> list[str]:
    recent_dates = getattr(provider, "recent_open_trade_dates", None)
    if callable(recent_dates):
        dates = recent_dates()
    else:
        calendar_start = _previous_compact_date(latest_trade_date)
        try:
            rows = provider.fetch_trade_calendar(
                calendar_start,
                latest_trade_date,
                is_open="1",
            )
        except TypeError:
            dates = [latest_trade_date]
        else:
            dates = [row.get("cal_date") for row in rows]
    unique = sorted({str(item or "").strip() for item in dates if str(item or "").strip()})
    if latest_trade_date not in unique:
        unique.append(latest_trade_date)
        unique.sort()
    return unique


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
            latest_trade_date = provider.latest_open_trade_date()
            skipped_trade_dates: list[dict[str, str | None]] = []
            provider_trade_date = latest_trade_date
            daily_basic_raw: list[dict[str, Any]] = []
            daily_rows: list[dict[str, Any]] = []
            for candidate_trade_date in reversed(_recent_open_trade_dates(provider, latest_trade_date)):
                candidate_daily_basic = provider.fetch_daily_basic(candidate_trade_date)
                candidate_daily_rows = _normalize_daily_rows(
                    provider.fetch_daily(candidate_trade_date),
                    candidate_daily_basic,
                    names,
                )
                if candidate_daily_rows:
                    provider_trade_date = candidate_trade_date
                    daily_basic_raw = candidate_daily_basic
                    daily_rows = candidate_daily_rows
                    break
                skipped_trade_dates.append({
                    "trade_date": _date(candidate_trade_date),
                    "reason": "tushare_daily_empty",
                })
            if not daily_rows:
                raise RuntimeError(f"TuShare daily returned no rows for recent open trade dates through {latest_trade_date}")
            trade_date = _date(provider_trade_date)
            compact_trade_date = _compact_date(provider_trade_date)
            trade_calendar = _normalize_trade_calendar(
                provider.fetch_trade_calendar(compact_trade_date, compact_trade_date),
                provider_trade_date,
            )
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
            result = self.repository.complete_run(run_id, instruments, daily_rows, trade_date, auxiliary_datasets=auxiliary_datasets)
            if skipped_trade_dates:
                result["latest_open_trade_date"] = _date(latest_trade_date)
                result["skipped_trade_dates"] = skipped_trade_dates
            return result
        except Exception as error:
            self.repository.fail_run(run_id, error)
            raise

    def reserve_history(
        self,
        *,
        history_days: int = 180,
        start_date: str | None = None,
        end_date: str | None = None,
        trigger: str = "manual",
    ) -> dict:
        requested_start, requested_end = _history_range(
            history_days=history_days,
            start_date=start_date,
            end_date=end_date,
        )
        run_id = self.repository.begin_run(trigger)
        if run_id is None:
            return {"status": "locked", "trigger": trigger, "sync_scope": "history"}
        return {
            "run_id": run_id,
            "status": "accepted",
            "sync_scope": "history",
            "start_date": requested_start,
            "end_date": requested_end,
            "history_days": history_days,
        }

    def sync_history(
        self,
        *,
        history_days: int = 180,
        start_date: str | None = None,
        end_date: str | None = None,
        trigger: str = "manual",
        run_id: int | None = None,
    ) -> dict:
        """Fetch the full A-share daily universe by open trade date.

        Provider calls happen before the repository's single history commit. A
        missing interior open day therefore fails the run without leaving a
        partial history in PostgreSQL. The final open day may be empty while a
        provider is still publishing it intraday; that day is reported as
        skipped and the latest available day is committed instead.
        """
        requested_start, requested_end = _history_range(
            history_days=history_days,
            start_date=start_date,
            end_date=end_date,
        )
        if run_id is None:
            run_id = self.repository.begin_run(trigger)
            if run_id is None:
                return {"status": "locked", "trigger": trigger, "sync_scope": "history"}

        try:
            provider = self.provider
            if provider is None:
                from app.domain.instruments.provider import TushareAshareProvider

                provider = TushareAshareProvider()
            instruments = _normalize_instruments(provider.fetch_instruments())
            if not instruments:
                raise RuntimeError("TuShare stock_basic returned no A-share instruments")

            names = {item["symbol"]: item["name"] for item in instruments}
            trade_dates = _open_history_trade_dates(provider, requested_start, requested_end)
            if not trade_dates:
                raise RuntimeError(f"{requested_start} ~ {requested_end} 内没有 TuShare 开放交易日")

            update_progress = getattr(self.repository, "update_history_progress", None)
            if callable(update_progress):
                update_progress(
                    run_id,
                    sync_scope="history",
                    start_date=requested_start,
                    end_date=requested_end,
                    total_trade_dates=len(trade_dates),
                    processed_trade_dates=0,
                    daily_count=0,
                )

            daily_rows: list[dict[str, Any]] = []
            skipped_trade_dates: list[dict[str, str]] = []
            for index, trade_date in enumerate(trade_dates):
                raw_rows = provider.fetch_daily(trade_date.replace("-", ""))
                normalized_rows = _normalize_daily_rows(raw_rows, [], names)
                if not normalized_rows:
                    if index == len(trade_dates) - 1:
                        skipped_trade_dates.append({"trade_date": trade_date, "reason": "tushare_daily_empty"})
                    else:
                        raise RuntimeError(f"TuShare daily returned no rows for open trade date {trade_date}")
                else:
                    daily_rows.extend(normalized_rows)
                if callable(update_progress):
                    update_progress(
                        run_id,
                        sync_scope="history",
                        start_date=requested_start,
                        end_date=requested_end,
                        total_trade_dates=len(trade_dates),
                        processed_trade_dates=index + 1,
                        last_processed_trade_date=trade_date,
                        daily_count=len(daily_rows),
                    )

            if not daily_rows:
                raise RuntimeError(f"TuShare daily returned no rows for {requested_start} ~ {requested_end}")
            complete_history = getattr(self.repository, "complete_history_run", None)
            if not callable(complete_history):
                raise RuntimeError("repository does not support atomic A-share history sync")
            result = complete_history(
                run_id,
                instruments,
                daily_rows,
                requested_start,
                requested_end,
                trade_date_count=len(trade_dates),
            )
            if skipped_trade_dates:
                result["skipped_trade_dates"] = skipped_trade_dates
            return result
        except Exception as error:
            self.repository.fail_run(run_id, error)
            raise


instrument_sync_service = AshareInstrumentSyncService()
