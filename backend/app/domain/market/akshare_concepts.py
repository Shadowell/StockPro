"""Bounded AKShare/Eastmoney concept membership snapshot provider."""
from __future__ import annotations

import math
import re
import time
from typing import Any, Callable


CONCEPT_FILTER_VERSION = "ashare-concept-filter.v1"
_EXCLUDED_NAME_PATTERNS = (
    r"^昨日",
    r"融资融券",
    r"沪股通|深股通|陆股通",
    r"MSCI|富时罗素|标普|中证|上证|深证|沪深300|证金持股",
    r"AH股|AB股",
)


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        rows = value
    elif hasattr(value, "to_dict"):
        rows = value.to_dict("records")
    else:
        return []
    result = []
    for raw in rows:
        row = {}
        for key, item in dict(raw).items():
            row[str(key)] = None if isinstance(item, float) and math.isnan(item) else item
        result.append(row)
    return result


def _canonical_symbol(value: Any) -> str | None:
    code = str(value or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        return None
    if code.startswith(("4", "8", "92")):
        suffix = "BJ"
    elif code.startswith(("5", "6")):
        suffix = "SH"
    else:
        suffix = "SZ"
    return f"{code}.{suffix}"


def is_excluded_concept_name(name: str) -> bool:
    return any(re.search(pattern, name, re.IGNORECASE) for pattern in _EXCLUDED_NAME_PATTERNS)


class AkshareConceptMembershipProvider:
    def __init__(
        self,
        *,
        list_fetcher: Callable[[], Any] | None = None,
        member_fetcher: Callable[..., Any] | None = None,
        delay_seconds: float = 0.05,
        minimum_sectors: int = 30,
        minimum_memberships: int = 500,
    ) -> None:
        if list_fetcher is None or member_fetcher is None:
            import akshare as ak

            list_fetcher = list_fetcher or ak.stock_board_concept_name_em
            member_fetcher = member_fetcher or ak.stock_board_concept_cons_em
        self.list_fetcher = list_fetcher
        self.member_fetcher = member_fetcher
        self.delay_seconds = max(0.0, float(delay_seconds))
        self.minimum_sectors = max(1, int(minimum_sectors))
        self.minimum_memberships = max(1, int(minimum_memberships))

    def fetch_memberships(self) -> dict[str, Any]:
        raw_sectors = _records(self.list_fetcher())
        sectors: list[dict[str, str]] = []
        excluded: list[dict[str, str]] = []
        for row in raw_sectors:
            name = str(row.get("板块名称") or row.get("name") or "").strip()
            code = str(row.get("板块代码") or row.get("code") or "").strip().upper()
            if not name or not re.fullmatch(r"BK\d+", code):
                continue
            target = {"sector_code": code, "sector_name": name}
            if is_excluded_concept_name(name):
                excluded.append(target)
            else:
                sectors.append(target)
        memberships: list[dict[str, str]] = []
        failures: list[dict[str, str]] = []
        for sector in sectors:
            try:
                rows = _records(self.member_fetcher(symbol=sector["sector_code"]))
            except Exception as exc:
                failures.append({**sector, "error": type(exc).__name__})
                continue
            for row in rows:
                symbol = _canonical_symbol(row.get("代码") or row.get("symbol"))
                if symbol:
                    memberships.append({
                        **sector,
                        "symbol": symbol,
                        "symbol_name": str(row.get("名称") or row.get("name") or "").strip(),
                    })
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
        deduped = {
            (item["sector_code"], item["symbol"]): item
            for item in memberships
        }
        memberships = sorted(deduped.values(), key=lambda item: (item["sector_code"], item["symbol"]))
        successful_sector_count = len({item["sector_code"] for item in memberships})
        sector_coverage = successful_sector_count / len(sectors) if sectors else 0.0
        if successful_sector_count < self.minimum_sectors or len(memberships) < self.minimum_memberships or sector_coverage < 0.8:
            raise RuntimeError(
                f"AKShare concept membership coverage insufficient: sectors={successful_sector_count}/{len(sectors)}, memberships={len(memberships)}"
            )
        return {
            "sectors": sectors,
            "memberships": memberships,
            "excluded_sectors": excluded,
            "failed_sectors": failures,
            "source": "akshare.stock_board_concept_name_em+stock_board_concept_cons_em",
            "filter_version": CONCEPT_FILTER_VERSION,
        }


class TushareConceptMembershipProvider:
    """TuShare THS concept catalogue + current members with quota-safe pacing."""

    def __init__(
        self,
        client: Any,
        *,
        delay_seconds: float = 0.4,
        minimum_sectors: int = 30,
        minimum_memberships: int = 500,
    ) -> None:
        self.client = client
        self.delay_seconds = max(0.0, float(delay_seconds))
        self.minimum_sectors = max(1, int(minimum_sectors))
        self.minimum_memberships = max(1, int(minimum_memberships))

    def fetch_memberships(self) -> dict[str, Any]:
        raw_sectors = _records(self.client.ths_index(
            exchange="A",
            type="N",
            fields="ts_code,name,count,exchange,list_date,type",
        ))
        sectors: list[dict[str, str]] = []
        excluded: list[dict[str, str]] = []
        for row in raw_sectors:
            code = str(row.get("ts_code") or "").strip().upper()
            name = str(row.get("name") or "").strip()
            if not code or not name:
                continue
            target = {"sector_code": code, "sector_name": name}
            if is_excluded_concept_name(name):
                excluded.append(target)
            else:
                sectors.append(target)
        memberships: list[dict[str, str]] = []
        failures: list[dict[str, str]] = []
        for sector in sectors:
            try:
                rows = _records(self.client.ths_member(
                    ts_code=sector["sector_code"],
                    fields="ts_code,con_code,con_name,weight,in_date,out_date,is_new",
                ))
            except Exception as exc:
                failures.append({**sector, "error": type(exc).__name__})
                continue
            for row in rows:
                if str(row.get("is_new") or "").strip().upper() not in {"Y", "1", "TRUE"}:
                    continue
                symbol = str(row.get("con_code") or "").strip().upper()
                if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", symbol):
                    continue
                memberships.append({
                    **sector,
                    "symbol": symbol,
                    "symbol_name": str(row.get("con_name") or "").strip(),
                })
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
        deduped = {(item["sector_code"], item["symbol"]): item for item in memberships}
        memberships = sorted(deduped.values(), key=lambda item: (item["sector_code"], item["symbol"]))
        successful_sector_count = len({item["sector_code"] for item in memberships})
        sector_coverage = successful_sector_count / len(sectors) if sectors else 0.0
        if successful_sector_count < self.minimum_sectors or len(memberships) < self.minimum_memberships or sector_coverage < 0.8:
            raise RuntimeError(
                f"TuShare THS concept membership coverage insufficient: sectors={successful_sector_count}/{len(sectors)}, memberships={len(memberships)}"
            )
        return {
            "sectors": sectors,
            "memberships": memberships,
            "excluded_sectors": excluded,
            "failed_sectors": failures,
            "source": "tushare.ths_index+ths_member",
            "filter_version": CONCEPT_FILTER_VERSION,
        }
