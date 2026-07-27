"""Normalization for the point-in-time security master and trading calendar."""
from __future__ import annotations

from datetime import date, datetime
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import psycopg2.extras

from app.services.dataset_snapshot_service import DatasetSnapshotService, canonical_hash
from app.services.tushare_catalog_service import TushareCatalogService


STOCK_BASIC_FIELDS = (
    "ts_code,symbol,name,area,industry,market,exchange,curr_type,"
    "list_status,list_date,delist_date,is_hs"
)
TRADE_CALENDAR_FIELDS = "exchange,cal_date,is_open,pretrade_date"
ADJUSTMENT_FACTOR_FIELDS = "ts_code,trade_date,adj_factor"
DAILY_VALUATION_FIELDS = (
    "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,"
    "pb,ps,ps_ttm,dv_ratio,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv,limit_status"
)
SUSPENSION_FIELDS = "ts_code,trade_date,suspend_timing,suspend_type"
PRICE_LIMIT_FIELDS = "ts_code,trade_date,pre_close,up_limit,down_limit"
BENCHMARK_FIELDS = "ts_code,trade_date,close,open,high,low,pre_close,change,pct_chg,vol,amount"
DIVIDEND_FIELDS = (
    "ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,cash_div,cash_div_tax,"
    "record_date,ex_date,pay_date,div_listdate,imp_ann_date,base_date,base_share"
)
DEFAULT_BENCHMARKS: Sequence[str] = ("000001.SH", "399001.SZ", "399006.SZ", "000300.SH")


def normalise_trade_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError("trade_date 必须为 YYYY-MM-DD 或 YYYYMMDD") from exc


def compact_trade_date(value: Any) -> str:
    return normalise_trade_date(value).replace("-", "")


def _iso_date(value: Any, default: Optional[str] = None) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return default
    try:
        return normalise_trade_date(text)
    except ValueError:
        return default


def _symbol(value: Any) -> str:
    raw_text = str(value or "").strip().upper()
    for exchange in ("SH", "SZ", "BJ"):
        prefix = f"{exchange}_"
        if raw_text.startswith(prefix):
            tail = raw_text[len(prefix):]
            legacy_prefix = "T" if tail.startswith("T") else ""
            digits = "".join(ch for ch in tail if ch.isdigit())
            return f"{exchange}_{legacy_prefix}{digits}" if len(digits) == 6 else ""
    text = raw_text.replace("_", ".")
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) != 6:
        return ""
    # TuShare uses codes such as T600018.SH for delisted historical records.
    # Collapsing them to 600018.SH would merge a retired security identity with
    # a live one, so preserve the documented legacy prefix in our canonical key.
    legacy_prefix = "T" if text.startswith("T") else ""
    if text.endswith(".SH"):
        return f"SH_{legacy_prefix}{digits}"
    if text.endswith(".BJ"):
        return f"BJ_{legacy_prefix}{digits}"
    if text.endswith(".SZ"):
        return f"SZ_{legacy_prefix}{digits}"
    if digits.startswith(("6", "9")):
        return f"SH_{legacy_prefix}{digits}"
    if digits.startswith(("4", "8")):
        return f"BJ_{legacy_prefix}{digits}"
    if digits.startswith(("0", "3")):
        return f"SZ_{legacy_prefix}{digits}"
    return ""


def provider_ts_code(value: Any) -> str:
    """Convert a supported internal or TuShare symbol into TuShare notation."""
    symbol = _symbol(value)
    if not symbol:
        raise ValueError(f"无法规范化证券代码：{value}")
    exchange, code = symbol.split("_", 1)
    return f"{code}.{exchange}"


def _normalise_range_rows(
    records: Iterable[Mapping[str, Any]],
    date_field: str,
    normalizer,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for raw in records:
        normalized_date = _iso_date(raw.get(date_field))
        if not normalized_date:
            grouped.setdefault("invalid", []).append(raw)
            continue
        grouped.setdefault(normalized_date, []).append(raw)
    rows: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    for normalized_date in sorted(key for key in grouped if key != "invalid"):
        normalized_rows, normalized_issues = normalizer(grouped[normalized_date], normalized_date)
        rows.extend(normalized_rows)
        issues.extend(normalized_issues)
    for raw in grouped.get("invalid", []):
        issues.append({
            "check_code": f"invalid_{date_field}",
            "severity": "blocking",
            "record_key": str(raw.get("ts_code") or "unknown"),
            "message": f"历史参考数据缺少合法的 {date_field}",
            "details": {date_field: raw.get(date_field)},
        })
    return rows, issues


def _finite_float(value: Any) -> Tuple[Optional[float], bool]:
    """Preserve a missing upstream value as None and reject non-finite text."""
    if value is None or str(value).strip() == "":
        return None, True
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, False
    return (number, True) if math.isfinite(number) else (None, False)


def _daily_key(
    raw: Mapping[str, Any],
    expected_trade_date: str,
    issues: List[Dict[str, Any]],
) -> Optional[Tuple[str, str]]:
    symbol = _symbol(raw.get("ts_code") or raw.get("symbol"))
    raw_date = raw.get("trade_date") or raw.get("cal_date")
    trade_date = _iso_date(raw_date)
    record_key = f"{raw.get('ts_code') or raw.get('symbol') or 'unknown'}:{raw_date or 'unknown'}"
    if not symbol:
        issues.append({
            "check_code": "invalid_daily_symbol",
            "severity": "blocking",
            "record_key": record_key,
            "message": "日频参考数据返回了无法规范化的证券代码",
            "details": {},
        })
        return None
    if trade_date != expected_trade_date:
        issues.append({
            "check_code": "unexpected_trade_date",
            "severity": "blocking",
            "record_key": record_key,
            "message": "日频参考数据交易日与请求日不一致",
            "details": {"expected": expected_trade_date, "actual": trade_date},
        })
        return None
    return symbol, trade_date


def _numeric(
    raw: Mapping[str, Any],
    field: str,
    issues: List[Dict[str, Any]],
    record_key: str,
    *,
    required: bool = False,
    positive: bool = False,
    non_negative: bool = False,
) -> Optional[float]:
    number, valid = _finite_float(raw.get(field))
    invalid = not valid or (required and number is None)
    if number is not None and positive and number <= 0:
        invalid = True
    if number is not None and non_negative and number < 0:
        invalid = True
    if invalid:
        issues.append({
            "check_code": f"invalid_{field}",
            "severity": "blocking",
            "record_key": record_key,
            "message": f"{field} 缺失、非有限数值或超出合法范围",
            "details": {field: raw.get(field)},
        })
    return number


def normalise_adjustment_factor_rows(
    records: Iterable[Mapping[str, Any]], trade_date: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    target = normalise_trade_date(trade_date)
    rows: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    for raw in records:
        key = _daily_key(raw, target, issues)
        if not key:
            continue
        if key in seen:
            issues.append({"check_code": "duplicate_adjustment_factor", "severity": "blocking", "record_key": ":".join(key), "message": "复权因子记录重复", "details": {}})
            continue
        seen.add(key)
        factor = _numeric(raw, "adj_factor", issues, ":".join(key), required=True, positive=True)
        rows.append({"symbol": key[0], "ts_code": str(raw.get("ts_code") or "").upper(), "trade_date": key[1], "adj_factor": factor})
    return rows, issues


def normalise_daily_valuation_rows(
    records: Iterable[Mapping[str, Any]], trade_date: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    target = normalise_trade_date(trade_date)
    rows: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    non_negative_fields = {
        "turnover_rate", "turnover_rate_f", "volume_ratio", "dv_ratio", "dv_ttm",
        "total_share", "float_share", "free_share", "total_mv", "circ_mv",
    }
    numeric_fields = (
        "close", "turnover_rate", "turnover_rate_f", "volume_ratio", "pe", "pe_ttm", "pb",
        "ps", "ps_ttm", "dv_ratio", "dv_ttm", "total_share", "float_share", "free_share",
        "total_mv", "circ_mv",
    )
    for raw in records:
        key = _daily_key(raw, target, issues)
        if not key:
            continue
        if key in seen:
            issues.append({"check_code": "duplicate_daily_valuation", "severity": "blocking", "record_key": ":".join(key), "message": "每日估值记录重复", "details": {}})
            continue
        seen.add(key)
        row: Dict[str, Any] = {"symbol": key[0], "ts_code": str(raw.get("ts_code") or "").upper(), "trade_date": key[1]}
        for field in numeric_fields:
            row[field] = _numeric(
                raw, field, issues, ":".join(key), required=field == "close",
                positive=field == "close", non_negative=field in non_negative_fields,
            )
        raw_limit_status = raw.get("limit_status")
        if raw_limit_status is None or str(raw_limit_status).strip() == "":
            row["limit_status"] = None
        else:
            try:
                row["limit_status"] = int(raw_limit_status)
            except (TypeError, ValueError):
                row["limit_status"] = None
            if row["limit_status"] not in range(0, 7):
                issues.append({"check_code": "invalid_limit_status", "severity": "blocking", "record_key": ":".join(key), "message": "limit_status 不在 0-6 范围", "details": {"limit_status": raw_limit_status}})
        rows.append(row)
    return rows, issues


def normalise_suspension_rows(
    records: Iterable[Mapping[str, Any]], trade_date: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    target = normalise_trade_date(trade_date)
    rows: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, str]] = set()
    for raw in records:
        daily_key = _daily_key(raw, target, issues)
        if not daily_key:
            continue
        suspend_type = str(raw.get("suspend_type") or "").strip().upper()
        key = (daily_key[0], daily_key[1], suspend_type)
        if suspend_type not in {"S", "R"}:
            issues.append({"check_code": "invalid_suspend_type", "severity": "blocking", "record_key": ":".join(key), "message": "suspend_type 必须为 S 或 R", "details": {"suspend_type": raw.get("suspend_type")}})
        if key in seen:
            issues.append({"check_code": "duplicate_suspension", "severity": "blocking", "record_key": ":".join(key), "message": "停复牌记录重复", "details": {}})
            continue
        seen.add(key)
        rows.append({
            "symbol": daily_key[0], "ts_code": str(raw.get("ts_code") or "").upper(),
            "trade_date": daily_key[1], "suspend_type": suspend_type or None,
            "suspend_timing": raw.get("suspend_timing") or None,
        })
    return rows, issues


def normalise_price_limit_rows(
    records: Iterable[Mapping[str, Any]], trade_date: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    target = normalise_trade_date(trade_date)
    rows: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    for raw in records:
        key = _daily_key(raw, target, issues)
        if not key:
            continue
        record_key = ":".join(key)
        if key in seen:
            issues.append({"check_code": "duplicate_price_limit", "severity": "blocking", "record_key": record_key, "message": "涨跌停价记录重复", "details": {}})
            continue
        seen.add(key)
        pre_close = _numeric(raw, "pre_close", issues, record_key, positive=True)
        raw_up_limit, up_valid = _finite_float(raw.get("up_limit"))
        raw_down_limit, down_valid = _finite_float(raw.get("down_limit"))
        # TuShare represents an IPO/no-limit day as 99999.99 / 0.  Research
        # consumers need an explicit semantic flag rather than treating either
        # sentinel as a tradable limit price.
        has_price_limit = not (
            up_valid and down_valid and raw_up_limit is not None and raw_down_limit is not None
            and raw_up_limit >= 99999 and raw_down_limit == 0
        )
        if has_price_limit:
            up_limit = _numeric(raw, "up_limit", issues, record_key, required=True, positive=True)
            down_limit = _numeric(raw, "down_limit", issues, record_key, required=True, positive=True)
        else:
            up_limit = None
            down_limit = None
        if has_price_limit and up_limit is not None and down_limit is not None and up_limit < down_limit:
            issues.append({"check_code": "inverted_price_limits", "severity": "blocking", "record_key": record_key, "message": "涨停价低于跌停价", "details": {"up_limit": up_limit, "down_limit": down_limit}})
        rows.append({
            "symbol": key[0], "ts_code": str(raw.get("ts_code") or "").upper(), "trade_date": key[1],
            "pre_close": pre_close, "has_price_limit": has_price_limit,
            "up_limit": up_limit, "down_limit": down_limit,
            "source_up_limit": raw_up_limit, "source_down_limit": raw_down_limit,
        })
    return rows, issues


def normalise_benchmark_bar_rows(
    records: Iterable[Mapping[str, Any]], trade_date: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    target = normalise_trade_date(trade_date)
    rows: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    for raw in records:
        key = _daily_key(raw, target, issues)
        if not key:
            continue
        record_key = ":".join(key)
        if key in seen:
            issues.append({"check_code": "duplicate_benchmark_bar", "severity": "blocking", "record_key": record_key, "message": "基准指数日线重复", "details": {}})
            continue
        seen.add(key)
        values = {
            field: _numeric(raw, field, issues, record_key, required=field in {"open", "high", "low", "close"}, positive=field in {"open", "high", "low", "close", "pre_close"}, non_negative=field in {"vol", "amount"})
            for field in ("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount")
        }
        if all(values[field] is not None for field in ("open", "high", "low", "close")):
            if values["high"] < max(values["open"], values["close"], values["low"]) or values["low"] > min(values["open"], values["close"], values["high"]):
                issues.append({"check_code": "illegal_benchmark_ohlc", "severity": "blocking", "record_key": record_key, "message": "基准指数 OHLC 约束不成立", "details": values})
        rows.append({"symbol": key[0], "ts_code": str(raw.get("ts_code") or "").upper(), "trade_date": key[1], **values})
    return rows, issues


def normalise_corporate_action_rows(
    records: Iterable[Mapping[str, Any]], ex_date: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    target = normalise_trade_date(ex_date)
    rows: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, str, str]] = set()
    numeric_fields = ("stk_div", "stk_bo_rate", "stk_co_rate", "cash_div", "cash_div_tax", "base_share")
    for raw in records:
        symbol = _symbol(raw.get("ts_code"))
        normalized_ex_date = _iso_date(raw.get("ex_date"))
        record_key = f"{raw.get('ts_code') or 'unknown'}:{raw.get('ex_date') or 'unknown'}"
        if not symbol:
            issues.append({"check_code": "invalid_corporate_action_symbol", "severity": "blocking", "record_key": record_key, "message": "公司行为证券代码无法规范化", "details": {}})
            continue
        if normalized_ex_date != target:
            issues.append({"check_code": "unexpected_corporate_action_date", "severity": "blocking", "record_key": record_key, "message": "公司行为除权除息日与请求日不一致", "details": {"expected": target, "actual": normalized_ex_date}})
            continue
        announcement_date = _iso_date(raw.get("imp_ann_date")) or _iso_date(raw.get("ann_date"))
        if not announcement_date:
            issues.append({"check_code": "missing_corporate_action_availability", "severity": "blocking", "record_key": record_key, "message": "公司行为缺少可用公告日", "details": {}})
        values = {
            field: _numeric(raw, field, issues, record_key, non_negative=True)
            for field in numeric_fields
        }
        key = (symbol, target, str(raw.get("end_date") or ""), str(raw.get("div_proc") or ""))
        if key in seen:
            issues.append({"check_code": "duplicate_corporate_action", "severity": "blocking", "record_key": record_key, "message": "公司行为记录重复", "details": {}})
            continue
        seen.add(key)
        rows.append({
            "symbol": symbol,
            "ts_code": str(raw.get("ts_code") or "").upper(),
            "end_date": _iso_date(raw.get("end_date")),
            "announcement_date": _iso_date(raw.get("ann_date")),
            "implementation_announcement_date": _iso_date(raw.get("imp_ann_date")),
            "announcement_available_at": f"{announcement_date}T09:00:00+08:00" if announcement_date else None,
            "dividend_process": raw.get("div_proc") or None,
            "record_date": _iso_date(raw.get("record_date")),
            "ex_date": target,
            "pay_date": _iso_date(raw.get("pay_date")),
            "share_list_date": _iso_date(raw.get("div_listdate")),
            "base_date": _iso_date(raw.get("base_date")),
            **values,
        })
    return rows, issues


def normalise_security_master_rows(
    records: Iterable[Mapping[str, Any]],
    as_of_date: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Normalize TuShare ``stock_basic`` rows without replacing unknown facts."""
    as_of = normalise_trade_date(as_of_date)
    rows: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in records:
        symbol = _symbol(raw.get("ts_code") or raw.get("symbol"))
        if not symbol:
            issues.append({
                "check_code": "invalid_security_symbol",
                "severity": "blocking",
                "record_key": str(raw.get("ts_code") or raw.get("symbol") or "unknown"),
                "message": "stock_basic 返回了无法规范化的证券代码",
                "details": {},
            })
            continue
        if symbol in seen:
            issues.append({
                "check_code": "duplicate_security_master",
                "severity": "blocking",
                "record_key": symbol,
                "message": "同一证券在本次证券主数据分区重复出现",
                "details": {},
            })
            continue
        seen.add(symbol)
        name = str(raw.get("name") or "").strip()
        status = str(raw.get("list_status") or "").strip().upper()
        if status not in {"L", "D", "P"}:
            issues.append({
                "check_code": "unknown_listing_status",
                "severity": "blocking",
                "record_key": symbol,
                "message": "stock_basic 缺少可识别的上市状态",
                "details": {"list_status": raw.get("list_status")},
            })
        rows.append({
            "symbol": symbol,
            "ts_code": str(raw.get("ts_code") or "").strip().upper(),
            "name": name,
            "area": raw.get("area") or None,
            "industry": raw.get("industry") or None,
            "market": raw.get("market") or None,
            "exchange": raw.get("exchange") or None,
            "currency": raw.get("curr_type") or None,
            "listing_status": status or None,
            "list_date": _iso_date(raw.get("list_date")),
            "delist_date": _iso_date(raw.get("delist_date")),
            "is_hs": raw.get("is_hs") or None,
            "as_of_date": as_of,
        })
    return rows, issues


def normalise_trade_calendar_rows(
    records: Iterable[Mapping[str, Any]],
    expected_trade_date: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    expected = normalise_trade_date(expected_trade_date)
    rows: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    for raw in records:
        cal_date = _iso_date(raw.get("cal_date") or raw.get("trade_date"))
        exchange = str(raw.get("exchange") or "SSE").strip().upper() or "SSE"
        key = (exchange, cal_date or "")
        if not cal_date:
            issues.append({
                "check_code": "invalid_calendar_date",
                "severity": "blocking",
                "record_key": exchange,
                "message": "trade_cal 返回了无法规范化的日期",
                "details": {},
            })
            continue
        if key in seen:
            issues.append({
                "check_code": "duplicate_calendar_day",
                "severity": "blocking",
                "record_key": f"{exchange}:{cal_date}",
                "message": "同一交易所日历日期重复出现",
                "details": {},
            })
            continue
        seen.add(key)
        raw_open = raw.get("is_open")
        if str(raw_open).strip() not in {"0", "1"}:
            issues.append({
                "check_code": "invalid_calendar_open_flag",
                "severity": "blocking",
                "record_key": f"{exchange}:{cal_date}",
                "message": "trade_cal 的 is_open 不是 0 或 1",
                "details": {"is_open": raw_open},
            })
        rows.append({
            "exchange": exchange,
            "trade_date": cal_date,
            "is_open": str(raw_open).strip() == "1",
            "pretrade_date": _iso_date(raw.get("pretrade_date")),
            "available_at_trade_date": expected,
        })
    if expected not in {row["trade_date"] for row in rows}:
        issues.append({
            "check_code": "missing_requested_calendar_day",
            "severity": "blocking",
            "record_key": expected,
            "message": "trade_cal 未返回请求交易日",
            "details": {},
        })
    return rows, issues


class ReferenceDatasetSyncService:
    """Fetch documented TuShare references and persist normalized partitions."""

    def __init__(
        self,
        database,
        catalog_service: Optional[TushareCatalogService] = None,
        snapshot_service: Optional[DatasetSnapshotService] = None,
    ):
        self.database = database
        self.catalog_service = catalog_service or TushareCatalogService(database)
        self.snapshot_service = snapshot_service or DatasetSnapshotService(database)

    def sync_trade_calendar_records(
        self,
        records: Sequence[Mapping[str, Any]],
        trade_date: Any,
        endpoint_run_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        target = normalise_trade_date(trade_date)
        rows, issues = normalise_trade_calendar_rows(records, target)
        return self.snapshot_service.publish_normalized_partition(
            "trade_calendar",
            f"trade_calendar:{target}:tushare",
            rows,
            start_date=target,
            end_date=target,
            request_params={
                "endpoint": "trade_cal",
                "endpoint_run_id": endpoint_run_id,
                "trade_date": compact_trade_date(target),
            },
            quality_issues=issues,
        )

    def get_universe_snapshot(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT s.id, d.code, d.rule_version, s.trade_date, s.knowledge_cutoff_at,
                           s.manifest_hash, s.status, s.sealed_at
                    FROM universe_snapshots s
                    JOIN universe_definitions d ON d.id = s.definition_id
                    WHERE s.id = %s
                    """,
                    (int(snapshot_id),),
                )
                snapshot = cursor.fetchone()
                if not snapshot:
                    return None
                cursor.execute(
                    """
                    SELECT symbol, industry_code, benchmark_weight, eligibility_flags
                    FROM universe_snapshot_members WHERE snapshot_id = %s ORDER BY symbol
                    """,
                    (int(snapshot_id),),
                )
                members = [dict(row) for row in cursor.fetchall()]
        return {**dict(snapshot), "member_count": len(members), "members": members}

    def sync_daily_auxiliary_datasets(
        self,
        trade_date: Any,
        benchmarks: Sequence[str] = DEFAULT_BENCHMARKS,
    ) -> Dict[str, Dict[str, Any]]:
        """Fetch one documented TuShare day and publish five normalized PG partitions."""
        target = normalise_trade_date(trade_date)
        compact = compact_trade_date(target)
        specifications = (
            ("adjustment_factors", "adj_factor", ADJUSTMENT_FACTOR_FIELDS, normalise_adjustment_factor_rows, False),
            ("daily_valuation", "daily_basic", DAILY_VALUATION_FIELDS, normalise_daily_valuation_rows, False),
            ("suspensions", "suspend_d", SUSPENSION_FIELDS, normalise_suspension_rows, True),
            ("price_limits", "stk_limit", PRICE_LIMIT_FIELDS, normalise_price_limit_rows, False),
            ("corporate_actions", "dividend", DIVIDEND_FIELDS, normalise_corporate_action_rows, True),
        )
        publications: Dict[str, Dict[str, Any]] = {}
        for dataset_code, endpoint, fields, normalizer, allow_empty in specifications:
            endpoint_params = {"ex_date": compact} if endpoint == "dividend" else {"trade_date": compact}
            result = self.catalog_service.sync_endpoint(
                endpoint,
                params=endpoint_params,
                fields=fields,
                include_records=True,
            )
            rows, issues = normalizer(result.get("records") or [], target)
            publications[dataset_code] = self.snapshot_service.publish_normalized_partition(
                dataset_code,
                f"{dataset_code}:{target}:tushare",
                rows,
                start_date=target,
                end_date=target,
                request_params={
                    "endpoint": endpoint,
                    "endpoint_run_id": result.get("run_id"),
                    "trade_date": compact,
                    "fields": fields,
                },
                quality_issues=issues,
                allow_empty=allow_empty,
            )
            if dataset_code == "corporate_actions":
                self._upsert_corporate_actions(
                    rows,
                    int(publications[dataset_code]["source_fetch_run_id"]),
                )

        benchmark_records: List[Mapping[str, Any]] = []
        benchmark_run_ids: List[int] = []
        requested_benchmarks = list(dict.fromkeys(str(code).strip().upper() for code in benchmarks if str(code).strip()))
        if not requested_benchmarks:
            raise ValueError("基准指数列表不能为空")
        for ts_code in requested_benchmarks:
            result = self.catalog_service.sync_endpoint(
                "index_daily",
                params={"ts_code": ts_code, "trade_date": compact},
                fields=BENCHMARK_FIELDS,
                include_records=True,
            )
            benchmark_run_ids.append(int(result["run_id"]))
            benchmark_records.extend(result.get("records") or [])
        benchmark_rows, benchmark_issues = normalise_benchmark_bar_rows(benchmark_records, target)
        returned_codes = {str(row.get("ts_code") or "").upper() for row in benchmark_rows}
        for missing_code in sorted(set(requested_benchmarks) - returned_codes):
            benchmark_issues.append({
                "check_code": "missing_benchmark_bar",
                "severity": "blocking",
                "record_key": f"{missing_code}:{target}",
                "message": "TuShare index_daily 未返回必需基准指数",
                "details": {"ts_code": missing_code, "trade_date": target},
            })
        publications["benchmark_bars"] = self.snapshot_service.publish_normalized_partition(
            "benchmark_bars",
            f"benchmark_bars:{target}:tushare",
            benchmark_rows,
            start_date=target,
            end_date=target,
            request_params={
                "endpoint": "index_daily",
                "endpoint_run_ids": benchmark_run_ids,
                "trade_date": compact,
                "benchmarks": requested_benchmarks,
                "fields": BENCHMARK_FIELDS,
            },
            quality_issues=benchmark_issues,
        )
        return publications

    def sync_historical_backtest_references(
        self,
        base_snapshot_id: int,
        start_date: Any,
        end_date: Any,
        symbols: Sequence[str],
        benchmarks: Sequence[str] = ("000300.SH",),
    ) -> Dict[str, Any]:
        """Build one sealed historical reference snapshot for provider-free backtests.

        Collection is an explicit data-management operation. A backtest only reads
        the resulting sealed PostgreSQL snapshot and never calls a provider.
        """
        start = normalise_trade_date(start_date)
        end = normalise_trade_date(end_date)
        if start > end:
            raise ValueError("start_date 不能晚于 end_date")
        requested_symbols = sorted({provider_ts_code(item) for item in symbols if str(item).strip()})
        requested_benchmarks = sorted({provider_ts_code(item) for item in benchmarks if str(item).strip()})
        if not requested_symbols or not requested_benchmarks:
            raise ValueError("历史参考同步至少需要一个股票和一个基准")
        compact_start, compact_end = compact_trade_date(start), compact_trade_date(end)

        daily_bars = self.snapshot_service.load_snapshot_dataset(
            int(base_snapshot_id), "daily_bars", symbols=[_symbol(item) for item in requested_symbols], limit=1_000_000,
        )
        expected_pairs = {
            (str(item["symbol"]), normalise_trade_date(item["trade_date"]))
            for item in daily_bars if start <= normalise_trade_date(item["trade_date"]) <= end
        }
        expected_dates = {item[1] for item in expected_pairs}
        if not expected_pairs:
            raise ValueError("基础快照在所选区间没有目标股票日线")

        raw: Dict[str, List[Mapping[str, Any]]] = {
            "adjustment_factors": [], "price_limits": [], "suspensions": [], "corporate_actions": [],
        }
        endpoint_runs: Dict[str, List[int]] = {key: [] for key in raw}
        specifications = (
            ("adjustment_factors", "adj_factor", ADJUSTMENT_FACTOR_FIELDS),
            ("price_limits", "stk_limit", PRICE_LIMIT_FIELDS),
            ("suspensions", "suspend_d", SUSPENSION_FIELDS),
        )
        for ts_code in requested_symbols:
            for dataset_code, endpoint, fields in specifications:
                result = self.catalog_service.sync_endpoint(
                    endpoint,
                    params={"ts_code": ts_code, "start_date": compact_start, "end_date": compact_end},
                    fields=fields,
                    include_records=True,
                )
                endpoint_runs[dataset_code].append(int(result["run_id"]))
                raw[dataset_code].extend(result.get("records") or [])
            dividend = self.catalog_service.sync_endpoint(
                "dividend", params={"ts_code": ts_code}, fields=DIVIDEND_FIELDS, include_records=True,
            )
            endpoint_runs["corporate_actions"].append(int(dividend["run_id"]))
            raw["corporate_actions"].extend(
                item for item in (dividend.get("records") or [])
                if item.get("ex_date") and compact_start <= str(item["ex_date"]) <= compact_end
            )

        normalizers = {
            "adjustment_factors": ("trade_date", normalise_adjustment_factor_rows, False),
            "price_limits": ("trade_date", normalise_price_limit_rows, False),
            "suspensions": ("trade_date", normalise_suspension_rows, True),
            "corporate_actions": ("ex_date", normalise_corporate_action_rows, True),
        }
        publications: Dict[str, Dict[str, Any]] = {}
        for dataset_code, (date_field, normalizer, allow_empty) in normalizers.items():
            rows, issues = _normalise_range_rows(raw[dataset_code], date_field, normalizer)
            if dataset_code in {"adjustment_factors", "price_limits"}:
                actual_pairs = {(str(item["symbol"]), str(item["trade_date"])) for item in rows}
                for symbol, trade_date in sorted(expected_pairs - actual_pairs):
                    issues.append({
                        "check_code": f"missing_historical_{dataset_code}",
                        "severity": "blocking",
                        "record_key": f"{symbol}:{trade_date}",
                        "message": f"历史回测缺少 {dataset_code} 事实",
                        "details": {},
                    })
            publications[dataset_code] = self.snapshot_service.publish_normalized_partition(
                dataset_code,
                f"{dataset_code}:{start}:{end}:tushare:{canonical_hash(requested_symbols)[:12]}",
                rows,
                start_date=start,
                end_date=end,
                request_params={
                    "endpoint_run_ids": endpoint_runs[dataset_code], "symbols": requested_symbols,
                    "start_date": compact_start, "end_date": compact_end,
                },
                quality_issues=issues,
                allow_empty=allow_empty,
            )
            if dataset_code == "corporate_actions" and rows:
                self._upsert_corporate_actions(rows, int(publications[dataset_code]["source_fetch_run_id"]))

        calendar_result = self.catalog_service.sync_endpoint(
            "trade_cal",
            params={"exchange": "SSE", "start_date": compact_start, "end_date": compact_end},
            fields=TRADE_CALENDAR_FIELDS,
            include_records=True,
        )
        calendar_rows, calendar_issues = normalise_trade_calendar_rows(calendar_result.get("records") or [], end)
        returned_open_dates = {str(item["trade_date"]) for item in calendar_rows if item.get("is_open")}
        for missing_date in sorted(expected_dates - returned_open_dates):
            calendar_issues.append({
                "check_code": "missing_historical_trade_calendar_day", "severity": "blocking",
                "record_key": missing_date, "message": "历史日线交易日未被交易日历标记为开市", "details": {},
            })
        publications["trade_calendar"] = self.snapshot_service.publish_normalized_partition(
            "trade_calendar", f"trade_calendar:{start}:{end}:tushare", calendar_rows,
            start_date=start, end_date=end,
            request_params={"endpoint_run_id": calendar_result["run_id"], "start_date": compact_start, "end_date": compact_end},
            quality_issues=calendar_issues,
        )

        benchmark_raw: List[Mapping[str, Any]] = []
        benchmark_run_ids: List[int] = []
        for ts_code in requested_benchmarks:
            result = self.catalog_service.sync_endpoint(
                "index_daily",
                params={"ts_code": ts_code, "start_date": compact_start, "end_date": compact_end},
                fields=BENCHMARK_FIELDS,
                include_records=True,
            )
            benchmark_run_ids.append(int(result["run_id"]))
            benchmark_raw.extend(result.get("records") or [])
        benchmark_rows, benchmark_issues = _normalise_range_rows(
            benchmark_raw, "trade_date", normalise_benchmark_bar_rows,
        )
        benchmark_symbols = {_symbol(item) for item in requested_benchmarks}
        actual_benchmark_pairs = {(str(item["symbol"]), str(item["trade_date"])) for item in benchmark_rows}
        for symbol in sorted(benchmark_symbols):
            for missing_date in sorted(expected_dates - {day for code, day in actual_benchmark_pairs if code == symbol}):
                benchmark_issues.append({
                    "check_code": "missing_historical_benchmark_bar", "severity": "blocking",
                    "record_key": f"{symbol}:{missing_date}", "message": "历史回测缺少基准指数日线", "details": {},
                })
        publications["benchmark_bars"] = self.snapshot_service.publish_normalized_partition(
            "benchmark_bars",
            f"benchmark_bars:{start}:{end}:tushare:{canonical_hash(requested_benchmarks)[:12]}",
            benchmark_rows,
            start_date=start,
            end_date=end,
            request_params={"endpoint_run_ids": benchmark_run_ids, "benchmarks": requested_benchmarks},
            quality_issues=benchmark_issues,
        )

        blocked = [code for code, item in publications.items() if item.get("status") != "published"]
        if blocked:
            return {"status": "failed_quality_gate", "blocked_datasets": blocked, "publications": publications}

        replaced_codes = set(publications)
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT i.partition_id,i.dataset_code FROM dataset_snapshot_items i
                    JOIN dataset_snapshots s ON s.id=i.snapshot_id
                    WHERE i.snapshot_id=%s AND s.status='sealed' ORDER BY i.partition_id
                    """,
                    (int(base_snapshot_id),),
                )
                base_items = [dict(item) for item in cursor.fetchall()]
        if not base_items:
            raise ValueError("基础数据快照不存在或未封存")
        partition_ids = [
            int(item["partition_id"]) for item in base_items if item["dataset_code"] not in replaced_codes
        ] + [int(item["partition_id"]) for item in publications.values()]
        snapshot = self.snapshot_service.create_snapshot(
            f"backtest-ready-{start}-{end}-{canonical_hash(partition_ids)[:12]}", partition_ids,
        )
        return {
            "status": "sealed", "base_snapshot_id": int(base_snapshot_id), "snapshot": snapshot,
            "start_date": start, "end_date": end, "symbols": requested_symbols,
            "benchmarks": requested_benchmarks, "publications": publications,
        }

    def publish_universe_snapshot(self, trade_date: Any) -> Dict[str, Any]:
        """Seal the effective all-A-share research universe from normalized PG facts."""
        target = normalise_trade_date(trade_date)
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT p.id
                    FROM dataset_partitions p
                    JOIN dataset_definitions d ON d.id = p.dataset_id
                    WHERE d.code = 'security_master' AND p.status = 'published' AND p.end_date <= %s
                    ORDER BY p.end_date DESC, p.created_at DESC, p.id DESC LIMIT 1
                    """,
                    (target,),
                )
                master = cursor.fetchone()
                if not master:
                    raise ValueError("缺少可用的证券主数据分区")
                cursor.execute(
                    "SELECT payload FROM dataset_partition_records WHERE partition_id = %s ORDER BY record_ordinal",
                    (master["id"],),
                )
                master_rows = [dict(row["payload"]) for row in cursor.fetchall()]
                cursor.execute(
                    """
                    SELECT r.payload
                    FROM dataset_partition_records r
                    JOIN dataset_partitions p ON p.id = r.partition_id
                    JOIN dataset_definitions d ON d.id = p.dataset_id
                    WHERE d.code = 'suspensions' AND p.status = 'published' AND p.end_date = %s
                    ORDER BY p.created_at DESC, p.id DESC, r.record_ordinal
                    """,
                    (target,),
                )
                suspension_rows = [dict(row["payload"]) for row in cursor.fetchall()]
        suspended = {
            str(row.get("symbol")) for row in suspension_rows
            if row.get("suspend_type") == "S"
        }
        members: List[Dict[str, Any]] = []
        for row in master_rows:
            if row.get("listing_status") != "L":
                continue
            list_date = row.get("list_date")
            delist_date = row.get("delist_date")
            if list_date and str(list_date) > target:
                continue
            if delist_date and str(delist_date) <= target:
                continue
            symbol = str(row.get("symbol") or "")
            if not symbol:
                continue
            name = str(row.get("name") or "")
            members.append({
                "symbol": symbol,
                "trade_date": target,
                "industry_code": row.get("industry") or None,
                "benchmark_weight": None,
                "eligibility_flags": {
                    "listed": True,
                    "is_st": name.upper().startswith(("ST", "*ST")),
                    "suspended": symbol in suspended,
                    "eligible_for_research": not name.upper().startswith(("ST", "*ST")) and symbol not in suspended,
                },
            })
        if not members:
            raise ValueError("历史证券主数据未生成任何有效研究成分")
        partition = self.snapshot_service.publish_normalized_partition(
            "universe_history",
            f"universe_history:{target}:all_a_v1",
            members,
            start_date=target,
            end_date=target,
            requested_source="derived",
            actual_source="derived_pg",
            request_params={
                "definition": "all_a_v1",
                "security_master_partition_id": int(master["id"]),
                "suspension_date": target,
            },
        )
        manifest_hash = canonical_hash(members)
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO universe_definitions(code, rule_version, description)
                    VALUES ('all_a', 'v1', '交易日已上市 A 股，保留 ST/停牌标记并提供可研究资格')
                    ON CONFLICT (code) DO UPDATE SET rule_version = EXCLUDED.rule_version, description = EXCLUDED.description
                    RETURNING id
                    """
                )
                definition_id = int(cursor.fetchone()["id"])
                cursor.execute(
                    """
                    SELECT id, knowledge_cutoff_at FROM universe_snapshots
                    WHERE definition_id = %s AND trade_date = %s AND manifest_hash = %s AND status = 'sealed'
                    ORDER BY sealed_at DESC, id DESC LIMIT 1
                    """,
                    (definition_id, target, manifest_hash),
                )
                snapshot = cursor.fetchone()
                if snapshot:
                    snapshot_id = int(snapshot["id"])
                else:
                    cursor.execute(
                        """
                        INSERT INTO universe_snapshots
                        (definition_id, trade_date, knowledge_cutoff_at, manifest_hash, status, sealed_at)
                        VALUES (%s, %s, NOW(), %s, 'sealed', NOW()) RETURNING id, knowledge_cutoff_at
                        """,
                        (definition_id, target, manifest_hash),
                    )
                    snapshot = cursor.fetchone()
                    snapshot_id = int(snapshot["id"])
                    psycopg2.extras.execute_values(
                        cursor,
                        """
                        INSERT INTO universe_snapshot_members
                        (snapshot_id, symbol, industry_code, benchmark_weight, eligibility_flags)
                        VALUES %s
                        """,
                        [
                            (
                                snapshot_id, row["symbol"], row["industry_code"], row["benchmark_weight"],
                                psycopg2.extras.Json(row["eligibility_flags"]),
                            )
                            for row in members
                        ],
                    )
        return {
            "status": "sealed",
            "universe_snapshot_id": snapshot_id,
            "trade_date": target,
            "member_count": len(members),
            "manifest_hash": manifest_hash,
            "knowledge_cutoff_at": snapshot["knowledge_cutoff_at"],
            "dataset_partition": partition,
        }

    def sync_security_master(self, as_of_date: Any) -> Dict[str, Any]:
        """Fetch L/D/P statuses so delisted and pending symbols remain research facts."""
        as_of = normalise_trade_date(as_of_date)
        all_records: List[Mapping[str, Any]] = []
        endpoint_run_ids: List[int] = []
        for listing_status in ("L", "D", "P"):
            result = self.catalog_service.sync_endpoint(
                "stock_basic",
                params={"exchange": "", "list_status": listing_status},
                fields=STOCK_BASIC_FIELDS,
                include_records=True,
            )
            endpoint_run_ids.append(int(result["run_id"]))
            all_records.extend(result.get("records") or [])
        rows, issues = normalise_security_master_rows(all_records, as_of)
        partition = self.snapshot_service.publish_normalized_partition(
            "security_master",
            f"security_master:{as_of}:tushare",
            rows,
            start_date=as_of,
            end_date=as_of,
            request_params={
                "endpoint": "stock_basic",
                "endpoint_run_ids": endpoint_run_ids,
                "list_statuses": ["L", "D", "P"],
            },
            quality_issues=issues,
        )
        self._upsert_security_history(rows, int(partition["source_fetch_run_id"]), as_of)
        return {**partition, "endpoint_run_ids": endpoint_run_ids}

    def security_master_is_due(self, as_of_date: Any, max_age_days: int = 7) -> bool:
        target = date.fromisoformat(normalise_trade_date(as_of_date))
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT p.end_date
                    FROM dataset_partitions p
                    JOIN dataset_definitions d ON d.id = p.dataset_id
                    WHERE d.code = 'security_master' AND p.status = 'published'
                    ORDER BY p.end_date DESC, p.created_at DESC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
        if not row or not row["end_date"]:
            return True
        return (target - row["end_date"]).days >= max(1, int(max_age_days))

    def _upsert_corporate_actions(self, rows: Sequence[Mapping[str, Any]], source_fetch_run_id: int) -> None:
        deduplicated: Dict[Tuple[str, str, str, str], Tuple[Any, ...]] = {}
        for row in rows:
            available_at = row.get("announcement_available_at")
            if not available_at:
                continue
            cash = row.get("cash_div_tax") if row.get("cash_div_tax") is not None else row.get("cash_div")
            shares = row.get("stk_div")
            if cash is not None and float(cash) > 0:
                key = (str(row["symbol"]), "cash_dividend", str(row["ex_date"]), str(available_at))
                deduplicated[key] = (*key, cash, None, source_fetch_run_id)
            if shares is not None and float(shares) > 0:
                key = (str(row["symbol"]), "share_distribution", str(row["ex_date"]), str(available_at))
                deduplicated[key] = (*key, None, shares, source_fetch_run_id)
        values = list(deduplicated.values())
        if not values:
            return
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO corporate_actions
                    (symbol, action_type, ex_date, announcement_available_at, cash_per_share, share_ratio, source_fetch_run_id)
                    VALUES %s
                    ON CONFLICT (symbol, action_type, ex_date, announcement_available_at) DO UPDATE SET
                        cash_per_share = EXCLUDED.cash_per_share,
                        share_ratio = EXCLUDED.share_ratio,
                        source_fetch_run_id = EXCLUDED.source_fetch_run_id
                    """,
                    values,
                )

    def _upsert_security_history(self, rows: Sequence[Mapping[str, Any]], source_fetch_run_id: int, as_of_date: str) -> None:
        values = []
        aliases = []
        for row in rows:
            listing_status = str(row.get("listing_status") or "")
            if listing_status not in {"L", "D", "P"}:
                continue
            effective_from = row.get("list_date") or as_of_date
            name = str(row.get("name") or "").strip()
            values.append((
                row["symbol"],
                effective_from,
                row.get("delist_date") or None,
                listing_status,
                name.upper().startswith(("ST", "*ST")),
                None,
                name or None,
                source_fetch_run_id,
            ))
            if name:
                aliases.append((row["symbol"], name, "name", effective_from, row.get("delist_date") or None, source_fetch_run_id))
        if not values:
            return
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO security_status_history
                    (symbol, effective_from, effective_to, listing_status, is_st, suspension_status, name, source_fetch_run_id)
                    VALUES %s
                    ON CONFLICT (symbol, effective_from, listing_status) DO UPDATE SET
                        effective_to = EXCLUDED.effective_to,
                        is_st = EXCLUDED.is_st,
                        name = EXCLUDED.name,
                        source_fetch_run_id = EXCLUDED.source_fetch_run_id
                    """,
                    values,
                )
                if aliases:
                    psycopg2.extras.execute_values(
                        cursor,
                        """
                        INSERT INTO security_alias_history
                        (symbol, alias, alias_type, effective_from, effective_to, source_fetch_run_id)
                        VALUES %s
                        ON CONFLICT (symbol, alias, alias_type, effective_from) DO UPDATE SET
                            effective_to = EXCLUDED.effective_to,
                            source_fetch_run_id = EXCLUDED.source_fetch_run_id
                        """,
                        aliases,
                    )
