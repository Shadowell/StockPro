"""Read-only A-share PostgreSQL repository behind the original BitPro market API."""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import math
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras

from app.core.config import settings
from app.domain.market.research_metrics import (
    ABNORMALITY_DEFINITION_VERSION,
    MARKET_PHASE_DEFINITION_VERSION,
    SECTOR_RPS_DEFINITION_VERSION,
    ABNORMAL_WINDOW_KEYS,
    abnormal_rule_for,
    build_abnormal_windows,
)
from app.domain.market.overview import build_market_overview, unavailable_market_overview

SECTOR_HEATMAP_WINDOWS = ("1d", "5d", "20d")


def aggregate_sector_heatmap(
    instruments: List[Dict],
    realtime: Dict[str, Dict],
    history: Dict[str, Dict],
    window: str,
) -> Tuple[List[Dict], int]:
    """按行业聚合板块热力图（纯函数，便于单测）。

    - 等权涨跌：1d 优先实时 change_percent（缺失回退日线相邻收盘）；
      5d/20d 用 ``stock_history`` 最近第 1/6/21 个有数据交易日收盘比。
    - 无可计算涨跌的标的不进入板块（计入 total 覆盖差值）。
    返回 ``(sectors, covered_symbols)``；sectors 按标的数降序，成员按涨跌降序。
    """
    sectors: Dict[str, Dict] = {}
    covered = 0
    for instrument in instruments:
        symbol = str(instrument.get("symbol") or "")
        if not symbol:
            continue
        hist = history.get(symbol) or {}
        quote = realtime.get(symbol) or {}
        close_now = hist.get("close_now")
        change: Optional[float] = None
        if window == "1d":
            change = quote.get("change_percent")
            if change is None and close_now and hist.get("close_prev"):
                change = (float(close_now) / float(hist["close_prev"]) - 1.0) * 100.0
        elif window == "5d":
            if close_now and hist.get("close_5d"):
                change = (float(close_now) / float(hist["close_5d"]) - 1.0) * 100.0
        else:
            if close_now and hist.get("close_20d"):
                change = (float(close_now) / float(hist["close_20d"]) - 1.0) * 100.0
        if change is None or not math.isfinite(float(change)):
            continue
        covered += 1
        change = round(float(change), 2)
        industry = str(instrument.get("industry") or "").strip() or "其他"
        last_price = quote.get("last") or close_now
        try:
            last_value = float(last_price) if last_price is not None else None
        except (TypeError, ValueError):
            last_value = None
        amount = quote.get("amount")
        try:
            amount_value = float(amount) if amount is not None else None
        except (TypeError, ValueError):
            amount_value = None
        member = {
            "symbol": symbol,
            "name": str(instrument.get("name") or quote.get("name") or symbol),
            "board": instrument.get("board"),
            "last": (
                round(last_value, 2)
                if last_value is not None and math.isfinite(last_value) and last_value > 0
                else None
            ),
            "change_percent": change,
            "amount": (
                round(amount_value, 2)
                if amount_value is not None and math.isfinite(amount_value)
                else None
            ),
            "high": hist.get("high_now"),
            "low": hist.get("low_now"),
        }
        bucket = sectors.setdefault(industry, {
            "code": industry,
            "name": industry,
            "count": 0,
            "change_sum": 0.0,
            "gainers": 0,
            "losers": 0,
            "flat": 0,
            "members": [],
        })
        bucket["count"] += 1
        bucket["change_sum"] += change
        if change > 0:
            bucket["gainers"] += 1
        elif change < 0:
            bucket["losers"] += 1
        else:
            bucket["flat"] += 1
        bucket["members"].append(member)

    result: List[Dict] = []
    for bucket in sectors.values():
        members = sorted(bucket["members"], key=lambda m: m["change_percent"], reverse=True)
        result.append({
            "code": bucket["code"],
            "name": bucket["name"],
            "count": bucket["count"],
            "average_change": round(bucket["change_sum"] / bucket["count"], 2) if bucket["count"] else 0.0,
            "gainers": bucket["gainers"],
            "losers": bucket["losers"],
            "flat": bucket["flat"],
            "members": members,
        })
    result.sort(key=lambda sector: sector["count"], reverse=True)
    return result, covered


def aggregate_limit_ladder_rows(
    ladder_rows: List[Tuple],
    pool_rows: List[Tuple],
    trend_rows: List[Tuple],
) -> Dict:
    """连板梯队聚合（纯函数）。

    输入行元组：
    - ladder_rows: (today_level, code, name, price, change_percent, duration_days, reason)
    - pool_rows: (pool_kind, symbol, name, limit_times, open_times, seal_amount, industry, board, is_st)
    - trend_rows: (date, max_level, total, two_plus)
    """
    levels: Dict[int, List[Dict]] = {}
    for level, code, name, price, change_percent, duration_days, reason in ladder_rows:
        canonical = MarketRepository._canonical_symbol(code)
        levels.setdefault(int(level), []).append({
            "symbol": canonical,
            "name": str(name or canonical),
            "price": round(float(price), 2) if price is not None else None,
            "change_percent": round(float(change_percent), 2) if change_percent is not None else None,
            "duration_days": int(duration_days) if duration_days is not None else None,
            "reason": str(reason) if reason else None,
        })
    pools: Dict[str, List[Dict]] = {"up": [], "broken": [], "down": []}
    for kind, symbol, name, limit_times, open_times, seal_amount, industry, board, is_st in pool_rows:
        if kind not in pools:
            continue
        pools[kind].append({
            "symbol": MarketRepository._canonical_symbol(symbol),
            "name": str(name or symbol),
            "limit_times": int(limit_times) if limit_times is not None else None,
            "open_times": int(open_times) if open_times is not None else None,
            "seal_amount": round(float(seal_amount), 2) if seal_amount is not None else None,
            "industry": industry,
            "board": board,
            "is_st": bool(is_st) if is_st is not None else None,
        })
    for kind in pools:
        pools[kind].sort(
            key=lambda m: (m["limit_times"] or 0, m["seal_amount"] or 0), reverse=True,
        )
    trend = [
        {"date": str(row[0]), "max_height": int(row[1] or 0), "total": int(row[2] or 0), "two_plus": int(row[3] or 0)}
        for row in trend_rows
    ]
    return {"levels": levels, "pools": pools, "trend": trend}


def aggregate_concept_analysis(
    sector_rows: List[Tuple],
    rotation_rows: List[Tuple],
    hot_rows: List[Tuple],
    top_names: int = 12,
) -> Dict:
    """概念分析聚合（纯函数）。

    输入行元组：
    - sector_rows: (sector_code, sector_name, change_percent, leader_stock, leader_change, up_count, down_count, rank)
    - rotation_rows: (date, sector_name, change_percent) 近窗口内全部概念
    - hot_rows: (rank, name, change_percent, inflow, outflow, net_inflow)
    """
    sectors = [
        {
            "sector_code": code,
            "sector_name": name,
            "change_percent": round(float(change), 2) if change is not None else None,
            "leader_stock": leader,
            "leader_change": round(float(leader_change), 2) if leader_change is not None else None,
            "up_count": up,
            "down_count": down,
            "rank": rank,
        }
        for code, name, change, leader, leader_change, up, down, rank in sector_rows
        if name is not None and change is not None
    ]
    sectors.sort(key=lambda s: s["change_percent"], reverse=True)
    picks = {s["sector_name"] for s in sectors[:top_names]} | {s["sector_name"] for s in sectors[-top_names:]}
    by_name: Dict[str, Dict[str, Optional[float]]] = {}
    dates: set = set()
    for date, name, change in rotation_rows:
        if name not in picks:
            continue
        dates.add(str(date))
        by_name.setdefault(name, {})[str(date)] = round(float(change), 2) if change is not None else None
    rotation = [
        {"sector_name": name, "changes": by_name[name]}
        for name in sorted(by_name)
    ]
    rotation.sort(key=lambda r: (
        r["changes"].get(max(dates)) if dates and r["changes"].get(max(dates)) is not None else -999,
    ), reverse=True)
    hot = [
        {
            "rank": rank,
            "name": name,
            "change_percent": round(float(change), 2) if change is not None else None,
            "inflow": round(float(inflow), 2) if inflow is not None else None,
            "outflow": round(float(outflow), 2) if outflow is not None else None,
            "net_inflow": round(float(net_inflow), 2) if net_inflow is not None else None,
        }
        for rank, name, change, inflow, outflow, net_inflow in hot_rows
    ]
    return {"sectors": sectors, "rotation_dates": sorted(dates), "rotation": rotation, "hot": hot}


def aggregate_industry_analysis(
    instruments: List[Dict],
    realtime: Dict[str, Dict],
    history: Dict[str, Dict],
) -> Dict:
    """行业分析聚合（纯函数）：与热力图同口径，一次输出 1d/5d/20d 三窗口。

    涨跌口径：1d 优先实时 change_percent（缺失回退日线相邻收盘）；
    5d/20d 用 stock_history 最近第 1/6/21 个有数据交易日收盘比。
    """
    buckets: Dict[str, Dict] = {}
    for instrument in instruments:
        symbol = str(instrument.get("symbol") or "")
        if not symbol:
            continue
        hist = history.get(symbol) or {}
        quote = realtime.get(symbol) or {}
        close_now = hist.get("close_now")
        changes: Dict[str, Optional[float]] = {}
        change_1d = quote.get("change_percent")
        if change_1d is None and close_now and hist.get("close_prev"):
            change_1d = (float(close_now) / float(hist["close_prev"]) - 1.0) * 100.0
        changes["1d"] = change_1d
        for window, key in (("5d", "close_5d"), ("20d", "close_20d")):
            changes[window] = (
                (float(close_now) / float(hist[key]) - 1.0) * 100.0
                if close_now and hist.get(key) else None
            )
        if all(value is None or not math.isfinite(float(value)) for value in changes.values()):
            continue
        industry = str(instrument.get("industry") or "").strip() or "其他"
        bucket = buckets.setdefault(industry, {
            "code": industry,
            "name": industry,
            "count": 0,
            "sums": {"1d": 0.0, "5d": 0.0, "20d": 0.0},
            "counts": {"1d": 0, "5d": 0, "20d": 0},
            "gainers_1d": 0,
            "losers_1d": 0,
            "top_member": None,
        })
        bucket["count"] += 1
        change_1d_value = changes["1d"]
        if change_1d_value is not None and math.isfinite(float(change_1d_value)):
            change_1d_value = float(change_1d_value)
            bucket["sums"]["1d"] += change_1d_value
            bucket["counts"]["1d"] += 1
            if change_1d_value > 0:
                bucket["gainers_1d"] += 1
            elif change_1d_value < 0:
                bucket["losers_1d"] += 1
            top = bucket["top_member"]
            if top is None or change_1d_value > top["change_percent"]:
                bucket["top_member"] = {
                    "symbol": symbol,
                    "name": str(instrument.get("name") or symbol),
                    "change_percent": round(change_1d_value, 2),
                }
        for window in ("5d", "20d"):
            value = changes[window]
            if value is not None and math.isfinite(float(value)):
                bucket["sums"][window] += float(value)
                bucket["counts"][window] += 1

    industries: List[Dict] = []
    for bucket in buckets.values():
        def _avg(window: str) -> Optional[float]:
            count = bucket["counts"][window]
            return round(bucket["sums"][window] / count, 2) if count else None

        industries.append({
            "code": bucket["code"],
            "name": bucket["name"],
            "count": bucket["count"],
            "change_1d": _avg("1d"),
            "change_5d": _avg("5d"),
            "change_20d": _avg("20d"),
            "gainers_1d": bucket["gainers_1d"],
            "losers_1d": bucket["losers_1d"],
            "top_member": bucket["top_member"],
        })
    industries.sort(
        key=lambda row: (row["change_1d"] if row["change_1d"] is not None else -999), reverse=True,
    )
    return {"industries": industries}


class MarketRepository:
    SUPPORTED_INTRADAY_TIMEFRAMES = {"1m", "5m", "15m", "30m", "60m"}

    def __init__(
        self,
        database_url: str | None = None,
        *,
        connection_factory: Callable[..., object] = psycopg2.connect,
    ) -> None:
        self.database_url = database_url or settings.DATABASE_URL
        self.connection_factory = connection_factory

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for the A-share market port")
        connection = self.connection_factory(self.database_url)
        connection.set_session(readonly=True, autocommit=False)
        return connection

    @staticmethod
    def _canonical_symbol(raw: str) -> str:
        value = str(raw or "").strip().upper()
        if "." in value:
            return value
        if "_" in value:
            exchange, digits = value.split("_", 1)
            return f"{digits}.{exchange}"
        prefixed = re.fullmatch(r"(SH|SZ|BJ)([0-9]{6})", value)
        if prefixed:
            return f"{prefixed.group(2)}.{prefixed.group(1)}"
        exchange = "BJ" if value.startswith(("4", "8", "92")) else ("SH" if value.startswith(("5", "6", "9")) else "SZ")
        return f"{value}.{exchange}"

    @classmethod
    def _storage_symbol(cls, raw: str) -> str:
        canonical = cls._canonical_symbol(raw)
        digits, exchange = canonical.rsplit(".", 1)
        return f"{exchange}_{digits}"

    @staticmethod
    def _timestamp_ms(value: datetime | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
        observed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(observed.timestamp() * 1000)

    @staticmethod
    def _iso(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _freshness(observed_at: datetime | None, *, stale_after_seconds: int = 15 * 60) -> Dict:
        if observed_at is None:
            return {
                "basis": "source_updated_at",
                "observed_at": None,
                "age_seconds": None,
                "stale_after_seconds": stale_after_seconds,
                "stale": True,
            }
        observed = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=timezone.utc)
        age = max(0, int((datetime.now(timezone.utc) - observed).total_seconds()))
        return {
            "basis": "source_updated_at",
            "observed_at": observed.isoformat(),
            "age_seconds": age,
            "stale_after_seconds": stale_after_seconds,
            "stale": age > stale_after_seconds,
        }

    @staticmethod
    def _table_exists(cursor, table_name: str) -> bool:
        cursor.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
        return cursor.fetchone()[0] is not None

    @staticmethod
    def _side_levels(raw: Any, limit: int) -> List[List[float]]:
        if raw is None:
            return []
        rows = raw if isinstance(raw, list) else []
        levels: List[List[float]] = []
        for item in rows[: max(1, min(int(limit), 1000))]:
            try:
                if isinstance(item, dict):
                    price = item.get("price")
                    volume = item.get("volume")
                else:
                    price, volume = item[0], item[1]
                levels.append([float(price), float(volume)])
            except (TypeError, ValueError, IndexError, KeyError):
                continue
        return levels

    @staticmethod
    def _status_for_rows(rows: List[Dict], *, empty_reason: str) -> Dict:
        if rows:
            return {"data_status": "ok", "unavailable_reason": None}
        return {"data_status": "empty", "unavailable_reason": empty_reason}

    @staticmethod
    def _json_value(raw: Any, fallback: Any) -> Any:
        return fallback if raw is None else raw

    def list_symbols(self, asset_class: str, limit: int = 5000) -> List[str]:
        return [item["symbol"] for item in self.list_instruments(asset_class, limit)]

    def list_instruments(self, asset_class: str, limit: int = 10000) -> List[Dict]:
        bounded = max(1, min(int(limit), 20000))
        normalized = str(asset_class or "stock").lower()
        query = """
            SELECT symbol,name,exchange,asset_class,industry,board,list_status
            FROM instrument_definitions WHERE market='CN' AND list_status IN ('L','P')
        """
        params: list[object] = []
        if normalized != "all":
            query += " AND asset_class=%s"
            params.append(normalized)
        query += " ORDER BY exchange,symbol LIMIT %s"
        params.append(bounded)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
                if normalized == "index" and not rows and self._table_exists(cursor, "market_indices_realtime"):
                    cursor.execute(
                        """SELECT code,name FROM market_indices_realtime
                           WHERE code IS NOT NULL AND code<>'' ORDER BY id LIMIT %s""",
                        (bounded,),
                    )
                    index_rows = cursor.fetchall()
                    rows = []
                    for code, name in index_rows:
                        symbol = self._canonical_symbol(code)
                        suffix = symbol.rsplit(".", 1)[-1]
                        rows.append((
                            symbol,
                            str(name or symbol),
                            {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(suffix, "CN"),
                            "index",
                            None,
                            "指数",
                            "L",
                        ))
                if normalized == "index" and not rows:
                    snapshot = self._latest_dataset_snapshot(cursor, "benchmark_bars")
                    if snapshot:
                        for payload in self._dataset_snapshot_payloads(cursor, snapshot["id"], "benchmark_bars"):
                            raw_symbol = payload.get("symbol") or payload.get("ts_code") or payload.get("code")
                            if not raw_symbol:
                                continue
                            symbol = self._canonical_symbol(raw_symbol)
                            suffix = symbol.rsplit(".", 1)[-1]
                            name = str(payload.get("name") or {
                                "000001.SH": "上证指数",
                                "399001.SZ": "深证成指",
                                "399006.SZ": "创业板指",
                                "000300.SH": "沪深300",
                            }.get(symbol) or symbol)
                            rows.append((
                                symbol,
                                name,
                                {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(suffix, "CN"),
                                "index",
                                None,
                                "指数",
                                "L",
                            ))
        return [
            {
                "symbol": self._canonical_symbol(row[0]),
                "name": str(row[1] or ""),
                "display_name": f"{str(row[1] or '').strip()} {self._canonical_symbol(row[0])}".strip(),
                "exchange": row[2],
                "asset_class": row[3],
                "industry": row[4],
                "board": row[5],
                "list_status": row[6],
            }
            for row in rows
        ]

    def list_tickers(self, symbols: Optional[List[str]] = None) -> List[Dict]:
        requested = [self._storage_symbol(symbol) for symbol in symbols or []]
        canonical_requested = [self._canonical_symbol(symbol) for symbol in symbols or []]
        realtime_rows: List[tuple] = []
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if self._table_exists(cursor, "realtime_quotes"):
                    query = """
                        SELECT exchange,symbol,last_price,change_percent,volume,amount,
                               turnover_rate,volume_ratio,amplitude,trade_date,source,
                               source_updated_at,collected_at
                        FROM realtime_quotes
                    """
                    params: tuple[object, ...] = ()
                    if canonical_requested:
                        query += " WHERE symbol = ANY(%s)"
                        params = (canonical_requested,)
                    query += " ORDER BY exchange,symbol"
                    cursor.execute(query, params)
                    realtime_rows = cursor.fetchall()
        if realtime_rows:
            return [
                {
                    "exchange": row[0],
                    "symbol": self._canonical_symbol(row[1]),
                    "last": float(row[2] or 0),
                    "changePercent": float(row[3] or 0),
                    "change_percent": float(row[3] or 0),
                    "volume": float(row[4] or 0),
                    "quoteVolume": float(row[5] or 0),
                    "turnover_rate": float(row[6] or 0) if row[6] is not None else None,
                    "volume_ratio": float(row[7] or 0) if row[7] is not None else None,
                    "amplitude": float(row[8] or 0) if row[8] is not None else None,
                    "trade_date": str(row[9]) if row[9] else None,
                    "source": row[10],
                    "source_updated_at": self._iso(row[11]),
                    "collected_at": self._iso(row[12]),
                    "freshness": self._freshness(row[11]),
                    "timestamp": self._timestamp_ms(row[11]),
                    "data_status": "stale" if self._freshness(row[11])["stale"] else "ok",
                }
                for row in realtime_rows
            ]

        query = """
            SELECT r.code,COALESCE(NULLIF(d.name,''),r.name),r.price,r.change_percent,
                   r.volume,r.amount,r.updated_at
            FROM all_stocks_realtime r
            LEFT JOIN instrument_definitions d
              ON d.market='CN'
             AND d.symbol=(split_part(r.code,'_',2)||'.'||split_part(r.code,'_',1))
        """
        params: tuple[object, ...] = ()
        if requested:
            query += " WHERE r.code = ANY(%s)"
            params = (requested,)
        query += " ORDER BY code"
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
        return [
            {
                "exchange": self._canonical_symbol(row[0]).rsplit(".", 1)[1],
                "symbol": self._canonical_symbol(row[0]),
                "name": str(row[1] or ""),
                "display_name": f"{str(row[1] or '').strip()} {self._canonical_symbol(row[0])}".strip(),
                "last": float(row[2] or 0),
                "changePercent": float(row[3] or 0),
                "change_percent": float(row[3] or 0),
                "volume": float(row[4] or 0),
                "quoteVolume": float(row[5] or 0),
                "timestamp": self._timestamp_ms(row[6]),
                "source_updated_at": self._iso(row[6]),
                "collected_at": self._iso(row[6]),
                "freshness": self._freshness(row[6]),
                "data_status": "legacy_cache",
            }
            for row in rows
        ]

    def lookup_names(self, symbols: List[str]) -> Dict[str, str]:
        from app.domain.instruments.repository import AshareInstrumentRepository
        return AshareInstrumentRepository(self.database_url).lookup_names(symbols)

    def get_sector_heatmap(self, window: str = "1d") -> Dict:
        """板块热力图只读聚合：行业 × 实时/日线等权涨跌。

        实时优先 ``realtime_quotes``，为空回退 ``all_stocks_realtime``；
        5d/20d 窗口基于 ``stock_history`` 最近第 1/6/21 个有数据交易日的收盘。
        只读 SELECT，不调用 Provider、不写库。
        """
        normalized = window if window in SECTOR_HEATMAP_WINDOWS else "1d"
        instruments: List[Dict] = []
        realtime: Dict[str, Dict] = {}
        realtime_updated_at: Optional[datetime] = None
        realtime_source: Optional[str] = None
        history: Dict[str, Dict] = {}
        history_latest_date: Optional[str] = None
        sources: List[str] = []
        missing: List[str] = []

        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "instrument_definitions"):
                    return {
                        "window": normalized,
                        "sectors": [],
                        "covered_symbols": 0,
                        "total_symbols": 0,
                        "sector_count": 0,
                        "trade_date": None,
                        "realtime_updated_at": None,
                        "realtime_source": None,
                        "sources": [],
                        "data_status": "unavailable",
                        "unavailable_reason": "instrument_definitions table is not migrated",
                        "provider_calls": 0,
                        "writes_performed": False,
                        "paper_mutated": False,
                    }
                cursor.execute(
                    """
                    SELECT symbol,name,industry,board
                    FROM instrument_definitions
                    WHERE market='CN' AND list_status IN ('L','P') AND asset_class='stock'
                    """
                )
                for row in cursor.fetchall():
                    instruments.append({
                        "symbol": self._canonical_symbol(row[0]),
                        "name": str(row[1] or ""),
                        "industry": row[2],
                        "board": row[3],
                    })
                sources.append("instrument_definitions")

                if self._table_exists(cursor, "realtime_quotes"):
                    cursor.execute(
                        """
                        SELECT symbol,last_price,change_percent,amount,source_updated_at
                        FROM realtime_quotes
                        WHERE change_percent IS NOT NULL
                        """
                    )
                    for row in cursor.fetchall():
                        realtime[self._canonical_symbol(row[0])] = {
                            "last": row[1],
                            "change_percent": float(row[2]) if row[2] is not None else None,
                            "amount": row[3],
                            "name": None,
                        }
                        if row[4] is not None and (realtime_updated_at is None or row[4] > realtime_updated_at):
                            realtime_updated_at = row[4]
                    if realtime:
                        realtime_source = "realtime_quotes"
                if not realtime and self._table_exists(cursor, "all_stocks_realtime"):
                    cursor.execute(
                        """
                        SELECT code,name,price,change_percent,amount,updated_at
                        FROM all_stocks_realtime
                        WHERE change_percent IS NOT NULL
                        """
                    )
                    for row in cursor.fetchall():
                        realtime[self._canonical_symbol(row[0])] = {
                            "last": row[2],
                            "change_percent": float(row[3]) if row[3] is not None else None,
                            "amount": row[4],
                            "name": str(row[1] or "") or None,
                        }
                        if row[5] is not None and (realtime_updated_at is None or row[5] > realtime_updated_at):
                            realtime_updated_at = row[5]
                    if realtime:
                        realtime_source = "all_stocks_realtime"
                if realtime_source:
                    sources.append(realtime_source)
                else:
                    missing.append("实时行情缓存为空（1d 将回退日线相邻收盘）")

                if self._table_exists(cursor, "stock_history"):
                    cursor.execute(
                        """
                        WITH recent_dates AS (
                            SELECT DISTINCT date FROM stock_history ORDER BY date DESC LIMIT 21
                        ),
                        ranked AS (
                            SELECT symbol,date,close,high,low,
                                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                            FROM stock_history
                            WHERE date IN (SELECT date FROM recent_dates)
                        )
                        SELECT symbol,
                               MAX(close) FILTER (WHERE rn = 1) AS close_now,
                               MAX(close) FILTER (WHERE rn = 2) AS close_prev,
                               MAX(close) FILTER (WHERE rn = 6) AS close_5d,
                               MAX(close) FILTER (WHERE rn = 21) AS close_20d,
                               MAX(high) FILTER (WHERE rn = 1) AS high_now,
                               MIN(low) FILTER (WHERE rn = 1) AS low_now,
                               MAX(date) FILTER (WHERE rn = 1) AS latest_date
                        FROM ranked
                        GROUP BY symbol
                        """
                    )
                    for row in cursor.fetchall():
                        def _num(value: Any) -> Optional[float]:
                            try:
                                parsed = float(value) if value is not None else None
                            except (TypeError, ValueError):
                                return None
                            return parsed if parsed is not None and math.isfinite(parsed) and parsed > 0 else None

                        history[self._canonical_symbol(row[0])] = {
                            "close_now": _num(row[1]),
                            "close_prev": _num(row[2]),
                            "close_5d": _num(row[3]),
                            "close_20d": _num(row[4]),
                            "high_now": round(_num(row[5]), 2) if _num(row[5]) is not None else None,
                            "low_now": round(_num(row[6]), 2) if _num(row[6]) is not None else None,
                        }
                        if row[7] is not None:
                            observed_date = str(row[7])
                            if history_latest_date is None or observed_date > history_latest_date:
                                history_latest_date = observed_date
                    sources.append("stock_history")
                else:
                    missing.append("stock_history 表未迁移")

        sectors, covered = aggregate_sector_heatmap(instruments, realtime, history, normalized)
        payload: Dict = {
            "window": normalized,
            "sectors": sectors,
            "covered_symbols": covered,
            "total_symbols": len(instruments),
            "sector_count": len(sectors),
            "trade_date": history_latest_date,
            "realtime_updated_at": self._iso(realtime_updated_at),
            "realtime_source": realtime_source,
            "window_basis": "trading_bars",
            "sources": sources,
            "data_status": "ok" if sectors else "empty",
            "unavailable_reason": None if sectors else (
                "; ".join(missing) if missing else "无可用行业成员或涨跌事实（确认已跑每日同步）"
            ),
            "provider_calls": 0,
            "writes_performed": False,
            "paper_mutated": False,
        }
        if realtime_updated_at is not None:
            payload["realtime_freshness"] = self._freshness(realtime_updated_at)
        return payload

    def get_limit_ladder(self, trend_days: int = 30) -> Dict:
        """连板梯队只读聚合：最新梯队快照 + 涨停/炸板/跌停池 + 历史趋势。

        梯队源 `lianban_ladder_history`（旧同步管道，数据日期可能滞后），
        池源最新 `market_evidence_snapshots` 的 `limit_pool_members`。两源日期分别标注。
        """
        bounded_trend = max(5, min(int(trend_days), 120))
        ladder_date: Optional[str] = None
        pool_trade_date: Optional[str] = None
        ladder_rows: List[Tuple] = []
        pool_rows: List[Tuple] = []
        trend_rows: List[Tuple] = []
        sources: List[str] = []
        missing: List[str] = []

        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "lianban_ladder_history"):
                    missing.append("lianban_ladder_history 表未迁移")
                else:
                    cursor.execute("SELECT MAX(date) FROM lianban_ladder_history")
                    max_date = cursor.fetchone()[0]
                    if max_date is None:
                        missing.append("连板梯队历史为空（需运行旧版梯队同步）")
                    else:
                        ladder_date = str(max_date)
                        cursor.execute(
                            """
                            SELECT today_level,code,name,price,change_percent,duration_days,reason
                            FROM lianban_ladder_history WHERE date=%s
                            ORDER BY today_level DESC, code
                            """,
                            (max_date,),
                        )
                        ladder_rows = cursor.fetchall()
                        cursor.execute(
                            """
                            SELECT date,MAX(today_level),COUNT(*),
                                   SUM(CASE WHEN today_level>=2 THEN 1 ELSE 0 END)
                            FROM lianban_ladder_history
                            GROUP BY date ORDER BY date DESC LIMIT %s
                            """,
                            (bounded_trend,),
                        )
                        trend_rows = list(reversed(cursor.fetchall()))
                        sources.append("lianban_ladder_history")

                if not self._table_exists(cursor, "limit_pool_members"):
                    missing.append("limit_pool_members 表未迁移")
                else:
                    cursor.execute(
                        """
                        SELECT s.id,s.trade_date FROM market_evidence_snapshots s
                        WHERE s.id IN (SELECT DISTINCT snapshot_id FROM limit_pool_members)
                        ORDER BY s.id DESC LIMIT 1
                        """
                    )
                    snapshot = cursor.fetchone()
                    if snapshot is None:
                        missing.append("暂无含涨跌停池的市场证据快照")
                    else:
                        pool_trade_date = str(snapshot[1])
                        cursor.execute(
                            """
                            SELECT pool_kind,symbol,name,limit_times,open_times,seal_amount,industry
                            FROM limit_pool_members WHERE snapshot_id=%s
                            """,
                            (snapshot[0],),
                        )
                        pool_rows = [
                            (
                                row[0],
                                row[1],
                                row[2],
                                row[3],
                                row[4],
                                row[5],
                                row[6],
                                None,
                                "ST" in str(row[2] or "").upper(),
                            )
                            for row in cursor.fetchall()
                        ]
                        sources.append("limit_pool_members")

        aggregated = aggregate_limit_ladder_rows(ladder_rows, pool_rows, trend_rows)
        has_any = bool(
            aggregated["levels"]
            or any(aggregated["pools"].values())
            or aggregated["trend"]
        )
        return {
            "ladder_date": ladder_date,
            "pool_trade_date": pool_trade_date,
            "levels": [
                {"level": level, "members": aggregated["levels"][level]}
                for level in sorted(aggregated["levels"], reverse=True)
            ],
            "ladder_total": sum(len(v) for v in aggregated["levels"].values()),
            "pools": aggregated["pools"],
            "trend": aggregated["trend"],
            "trend_days": bounded_trend,
            "sources": sources,
            "data_status": "ok" if has_any else "empty",
            "unavailable_reason": None if has_any else ("; ".join(missing) if missing else "无梯队与涨跌停池事实"),
            "missing_inputs": missing,
            "provider_calls": 0,
            "writes_performed": False,
            "paper_mutated": False,
        }

    def get_concept_analysis(self, rotation_days: int = 20, hot_limit: int = 20) -> Dict:
        """概念分析只读聚合：最新榜单 + 近窗口轮动矩阵 + 热门概念资金流。"""
        bounded_rotation = max(5, min(int(rotation_days), 60))
        bounded_hot = max(1, min(int(hot_limit), 50))
        sector_rows: List[Tuple] = []
        rotation_rows: List[Tuple] = []
        hot_rows: List[Tuple] = []
        trade_date: Optional[str] = None
        hot_updated_at: Optional[str] = None
        sources: List[str] = []
        missing: List[str] = []

        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "daily_concept_sectors"):
                    missing.append("daily_concept_sectors 表未迁移")
                else:
                    cursor.execute(
                        """
                        SELECT sector_code,sector_name,change_percent,leader_stock,leader_change,
                               up_count,down_count,rank
                        FROM daily_concept_sectors
                        WHERE date=(SELECT MAX(date) FROM daily_concept_sectors)
                        ORDER BY change_percent DESC NULLS LAST
                        """
                    )
                    sector_rows = cursor.fetchall()
                    if sector_rows:
                        cursor.execute("SELECT MAX(date) FROM daily_concept_sectors")
                        trade_date = str(cursor.fetchone()[0])
                        sources.append("daily_concept_sectors")
                        cursor.execute(
                            """
                            SELECT date,sector_name,change_percent FROM daily_concept_sectors
                            WHERE date IN (
                                SELECT DISTINCT date FROM daily_concept_sectors
                                ORDER BY date DESC LIMIT %(days)s
                            )
                            ORDER BY date
                            """,
                            {"days": bounded_rotation},
                        )
                        rotation_rows = cursor.fetchall()
                    else:
                        missing.append("概念每日快照为空（需运行概念同步）")
                if self._table_exists(cursor, "hot_concepts_realtime"):
                    cursor.execute(
                        f"""
                        SELECT rank,name,change_percent,inflow,outflow,net_inflow,updated_at
                        FROM hot_concepts_realtime ORDER BY rank LIMIT {bounded_hot}
                        """
                    )
                    for row in cursor.fetchall():
                        hot_updated_at = self._iso(row[6]) or hot_updated_at
                        hot_rows.append(row[:6])
                    if hot_rows:
                        sources.append("hot_concepts_realtime")

        aggregated = aggregate_concept_analysis(sector_rows, rotation_rows, hot_rows)
        has_any = bool(aggregated["sectors"] or aggregated["hot"])
        return {
            "trade_date": trade_date,
            "sectors": aggregated["sectors"],
            "sector_count": len(aggregated["sectors"]),
            "rotation_dates": aggregated["rotation_dates"],
            "rotation": aggregated["rotation"],
            "rotation_days": bounded_rotation,
            "hot": aggregated["hot"],
            "hot_updated_at": hot_updated_at,
            "sources": sources,
            "data_status": "ok" if has_any else "empty",
            "unavailable_reason": None if has_any else ("; ".join(missing) if missing else "无概念事实"),
            "missing_inputs": missing,
            "provider_calls": 0,
            "writes_performed": False,
            "paper_mutated": False,
        }

    def get_industry_analysis(self) -> Dict:
        """行业分析只读聚合：与热力图同源同口径，一次输出 1d/5d/20d。"""
        instruments: List[Dict] = []
        realtime: Dict[str, Dict] = {}
        realtime_source: Optional[str] = None
        history: Dict[str, Dict] = {}
        history_latest_date: Optional[str] = None
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "instrument_definitions"):
                    return {
                        "trade_date": None,
                        "industries": [],
                        "industry_count": 0,
                        "realtime_source": None,
                        "sources": [],
                        "data_status": "unavailable",
                        "unavailable_reason": "instrument_definitions table is not migrated",
                        "provider_calls": 0,
                        "writes_performed": False,
                        "paper_mutated": False,
                    }
                cursor.execute(
                    """
                    SELECT symbol,name,industry,board
                    FROM instrument_definitions
                    WHERE market='CN' AND list_status IN ('L','P') AND asset_class='stock'
                    """
                )
                for row in cursor.fetchall():
                    instruments.append({
                        "symbol": self._canonical_symbol(row[0]),
                        "name": str(row[1] or ""),
                        "industry": row[2],
                        "board": row[3],
                    })
                if self._table_exists(cursor, "realtime_quotes"):
                    cursor.execute(
                        "SELECT symbol,last_price,change_percent,amount FROM realtime_quotes WHERE change_percent IS NOT NULL"
                    )
                    for row in cursor.fetchall():
                        realtime[self._canonical_symbol(row[0])] = {
                            "last": row[1], "change_percent": float(row[2]), "amount": row[3], "name": None,
                        }
                    if realtime:
                        realtime_source = "realtime_quotes"
                if not realtime and self._table_exists(cursor, "all_stocks_realtime"):
                    cursor.execute(
                        "SELECT code,name,price,change_percent,amount FROM all_stocks_realtime WHERE change_percent IS NOT NULL"
                    )
                    for row in cursor.fetchall():
                        realtime[self._canonical_symbol(row[0])] = {
                            "last": row[2], "change_percent": float(row[3]), "amount": row[4], "name": str(row[1] or "") or None,
                        }
                    if realtime:
                        realtime_source = "all_stocks_realtime"
                if self._table_exists(cursor, "stock_history"):
                    cursor.execute(
                        """
                        WITH recent_dates AS (
                            SELECT DISTINCT date FROM stock_history ORDER BY date DESC LIMIT 21
                        ),
                        ranked AS (
                            SELECT symbol,date,close,
                                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                            FROM stock_history
                            WHERE date IN (SELECT date FROM recent_dates)
                        )
                        SELECT symbol,
                               MAX(close) FILTER (WHERE rn = 1) AS close_now,
                               MAX(close) FILTER (WHERE rn = 2) AS close_prev,
                               MAX(close) FILTER (WHERE rn = 6) AS close_5d,
                               MAX(close) FILTER (WHERE rn = 21) AS close_20d,
                               MAX(date) FILTER (WHERE rn = 1) AS latest_date
                        FROM ranked GROUP BY symbol
                        """
                    )
                    for row in cursor.fetchall():
                        def _num(value: Any) -> Optional[float]:
                            try:
                                parsed = float(value) if value is not None else None
                            except (TypeError, ValueError):
                                return None
                            return parsed if parsed is not None and math.isfinite(parsed) and parsed > 0 else None

                        history[self._canonical_symbol(row[0])] = {
                            "close_now": _num(row[1]),
                            "close_prev": _num(row[2]),
                            "close_5d": _num(row[3]),
                            "close_20d": _num(row[4]),
                        }
                        if row[5] is not None:
                            observed = str(row[5])
                            if history_latest_date is None or observed > history_latest_date:
                                history_latest_date = observed
        aggregated = aggregate_industry_analysis(instruments, realtime, history)
        industries = aggregated["industries"]
        return {
            "trade_date": history_latest_date,
            "industries": industries,
            "industry_count": len(industries),
            "realtime_source": realtime_source,
            "sources": ["instrument_definitions", realtime_source or "daily_close_fallback", "stock_history"],
            "data_status": "ok" if industries else "empty",
            "unavailable_reason": None if industries else "无可用行业或涨跌事实（确认已跑每日同步）",
            "provider_calls": 0,
            "writes_performed": False,
            "paper_mutated": False,
        }

    def get_klines(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> List[Dict]:
        return self.get_klines_with_status(exchange, symbol, timeframe, limit, start, end)["items"]

    def get_klines_with_status(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> Dict:
        if timeframe != "1d":
            normalized_timeframe = str(timeframe or "").strip().lower()
            if normalized_timeframe not in self.SUPPORTED_INTRADAY_TIMEFRAMES:
                return {
                    "exchange": exchange,
                    "symbol": self._canonical_symbol(symbol),
                    "timeframe": normalized_timeframe,
                    "items": [],
                    "data_status": "unsupported",
                    "unavailable_reason": "A-share intraday cache supports only 1m/5m/15m/30m/60m",
                    "supported_timeframes": sorted(self.SUPPORTED_INTRADAY_TIMEFRAMES | {"1d"}),
                }
            return self._get_minute_bars(exchange, symbol, normalized_timeframe, limit, start, end)

        query = """
            SELECT date,open,high,low,close,volume,turnover
            FROM stock_history WHERE symbol=%s
        """
        params: list[object] = [self._storage_symbol(symbol)]
        if start is not None:
            query += " AND date >= %s"
            params.append(datetime.fromtimestamp(start / 1000, tz=timezone.utc).date())
        if end is not None:
            query += " AND date <= %s"
            params.append(datetime.fromtimestamp(end / 1000, tz=timezone.utc).date())
        query += " ORDER BY date DESC LIMIT %s"
        params.append(max(1, min(int(limit), 2000)))
        provider_source = "PostgreSQL stock_history"
        source_snapshot_id = None
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, tuple(params))
                rows = list(reversed(cursor.fetchall()))
                if not rows:
                    snapshot = self._latest_dataset_snapshot(cursor, "benchmark_bars")
                    if snapshot:
                        canonical = self._canonical_symbol(symbol)
                        payloads = [
                            payload for payload in self._dataset_snapshot_payloads(cursor, snapshot["id"], "benchmark_bars")
                            if self._canonical_symbol(payload.get("symbol") or payload.get("ts_code") or payload.get("code")) == canonical
                        ]
                        benchmark_rows = [
                            (
                                date.fromisoformat(str(payload.get("trade_date") or payload.get("date"))[:10]),
                                payload.get("open"), payload.get("high"), payload.get("low"), payload.get("close"),
                                payload.get("volume") or payload.get("vol"), payload.get("amount"),
                            )
                            for payload in payloads
                            if payload.get("trade_date") or payload.get("date")
                        ]
                        if benchmark_rows:
                            rows = benchmark_rows
                            provider_source = "tushare.index_daily → PostgreSQL sealed snapshot"
                            source_snapshot_id = snapshot["id"]
        items = [
            {
                "timestamp": int(datetime.combine(row[0], datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5] or 0),
                "quote_volume": float(row[6] or 0),
                "trade_date": str(row[0]),
                "source": "benchmark_bars" if source_snapshot_id is not None else "daily_bars",
                "data_status": "ok",
            }
            for row in rows
        ]
        status = self._status_for_rows(
            items,
            empty_reason=f"no sealed daily bar cache for {self._canonical_symbol(symbol)}",
        )
        return {
            "exchange": exchange,
            "symbol": self._canonical_symbol(symbol),
            "timeframe": "1d",
            "items": items,
            "row_count": len(items),
            "from_date": items[0]["trade_date"] if items else None,
            "to_date": items[-1]["trade_date"] if items else None,
            "latest_trade_date": items[-1]["trade_date"] if items else None,
            "provider_source": provider_source,
            "source_snapshot_id": source_snapshot_id,
            **status,
        }

    def _get_minute_bars(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int,
        start: Optional[int],
        end: Optional[int],
    ) -> Dict:
        canonical = self._canonical_symbol(symbol)
        bounded = max(1, min(int(limit), 5000))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "minute_bars"):
                    return {
                        "exchange": exchange,
                        "symbol": canonical,
                        "timeframe": timeframe,
                        "items": [],
                        "data_status": "unavailable",
                        "unavailable_reason": "minute_bars cache table is not migrated",
                    }
                query = """
                    SELECT trade_date,bar_time,open,high,low,close,volume,amount,
                           source,source_updated_at,collected_at
                    FROM minute_bars
                    WHERE symbol=%s AND interval=%s
                """
                params: list[object] = [canonical, timeframe]
                if start is not None:
                    query += " AND bar_time >= %s"
                    params.append(datetime.fromtimestamp(start / 1000, tz=timezone.utc))
                if end is not None:
                    query += " AND bar_time <= %s"
                    params.append(datetime.fromtimestamp(end / 1000, tz=timezone.utc))
                query += " ORDER BY bar_time DESC LIMIT %s"
                params.append(bounded)
                cursor.execute(query, tuple(params))
                rows = list(reversed(cursor.fetchall()))
        items = [
            {
                "timestamp": self._timestamp_ms(row[1]),
                "datetime": self._iso(row[1]),
                "trade_date": str(row[0]),
                "open": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "close": float(row[5]),
                "volume": float(row[6] or 0),
                "quote_volume": float(row[7] or 0),
                "amount": float(row[7] or 0),
                "source": row[8],
                "source_updated_at": self._iso(row[9]),
                "collected_at": self._iso(row[10]),
                "freshness": self._freshness(row[9]),
                "data_status": "stale" if self._freshness(row[9])["stale"] else "ok",
            }
            for row in rows
        ]
        status = self._status_for_rows(
            items,
            empty_reason=f"no A-share {timeframe} minute bar cache for {canonical}",
        )
        if items and any(row.get("data_status") == "stale" for row in items[-3:]):
            status = {"data_status": "stale", "unavailable_reason": None}
        return {
            "exchange": exchange,
            "symbol": canonical,
            "timeframe": timeframe,
            "items": items,
            **status,
        }

    def get_orderbook(self, exchange: str, symbol: str, limit: int) -> Dict:
        canonical = self._canonical_symbol(symbol)
        bounded = max(1, min(int(limit), 1000))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "orderbook_snapshots"):
                    return {
                        "exchange": exchange,
                        "symbol": canonical,
                        "bids": [],
                        "asks": [],
                        "data_status": "unavailable",
                        "unavailable_reason": "orderbook_snapshots cache table is not migrated",
                    }
                cursor.execute(
                    """
                    SELECT trade_date,snapshot_at,source,bids,asks,source_updated_at,collected_at
                    FROM orderbook_snapshots
                    WHERE symbol=%s
                    ORDER BY snapshot_at DESC,id DESC
                    LIMIT 1
                    """,
                    (canonical,),
                )
                row = cursor.fetchone()
        if not row:
            return {
                "exchange": exchange,
                "symbol": canonical,
                "bids": [],
                "asks": [],
                "data_status": "empty",
                "unavailable_reason": f"no A-share order-book cache for {canonical}",
            }
        bids = self._side_levels(row[3], bounded)
        asks = self._side_levels(row[4], bounded)
        freshness = self._freshness(row[5])
        return {
            "exchange": exchange,
            "symbol": canonical,
            "bids": bids,
            "asks": asks,
            "trade_date": str(row[0]) if row[0] else None,
            "snapshot_at": self._iso(row[1]),
            "source": row[2],
            "source_updated_at": self._iso(row[5]),
            "collected_at": self._iso(row[6]),
            "freshness": freshness,
            "data_status": "stale" if freshness["stale"] else ("ok" if bids or asks else "empty"),
            "unavailable_reason": None if bids or asks else f"latest order-book cache has no depth for {canonical}",
        }

    def get_trades(self, exchange: str, symbol: str, limit: int) -> List[Dict]:
        return self.get_trades_with_status(exchange, symbol, limit)["items"]

    def get_trades_with_status(self, exchange: str, symbol: str, limit: int) -> Dict:
        canonical = self._canonical_symbol(symbol)
        bounded = max(1, min(int(limit), 500))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "trade_ticks"):
                    return {
                        "exchange": exchange,
                        "symbol": canonical,
                        "items": [],
                        "data_status": "unavailable",
                        "unavailable_reason": "trade_ticks cache table is not migrated",
                    }
                cursor.execute(
                    """
                    SELECT id,trade_date,trade_time,price,volume,amount,side,source,
                           source_updated_at,collected_at
                    FROM trade_ticks
                    WHERE symbol=%s
                    ORDER BY trade_time DESC,id DESC
                    LIMIT %s
                    """,
                    (canonical, bounded),
                )
                rows = cursor.fetchall()
        items = [
            {
                "id": str(row[0]),
                "trade_date": str(row[1]) if row[1] else None,
                "timestamp": self._timestamp_ms(row[2]),
                "datetime": self._iso(row[2]),
                "price": float(row[3]),
                "amount": float(row[4] or 0),
                "volume": float(row[4] or 0),
                "cost": float(row[5] or 0) if row[5] is not None else None,
                "notional": float(row[5] or 0) if row[5] is not None else None,
                "side": row[6] or "unknown",
                "source": row[7],
                "source_updated_at": self._iso(row[8]),
                "collected_at": self._iso(row[9]),
                "freshness": self._freshness(row[8]),
                "data_status": "stale" if self._freshness(row[8])["stale"] else "ok",
            }
            for row in rows
        ]
        status = self._status_for_rows(
            items,
            empty_reason=f"no A-share recent trade cache for {canonical}",
        )
        if items and any(row.get("data_status") == "stale" for row in items[:3]):
            status = {"data_status": "stale", "unavailable_reason": None}
        return {
            "exchange": exchange,
            "symbol": canonical,
            "items": items,
            **status,
        }

    def market_pulse(self) -> Dict:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM instrument_definitions WHERE market='CN' AND asset_class='stock' AND list_status IN ('L','P')")
                instruments = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FILTER(WHERE change_percent>0),COUNT(*) FILTER(WHERE change_percent<0),COALESCE(SUM(amount),0),COALESCE(AVG(change_percent),0),MAX(updated_at) FROM all_stocks_realtime")
                rise, fall, turnover, average_change, updated_at = cursor.fetchone()
                cursor.execute("SELECT COUNT(*),MIN(date),MAX(date) FROM stock_history")
                daily_count, first_date, last_date = cursor.fetchone()
        return {"instrument_count": instruments, "rise_count": rise, "fall_count": fall, "turnover": turnover, "average_change_pct": average_change, "updated_at": updated_at.isoformat() if updated_at else None, "daily_bar_count": daily_count, "first_trade_date": str(first_date or ""), "trade_date": str(last_date or "")}

    @staticmethod
    def _payload_dict(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                value = json.loads(raw)
            except (TypeError, ValueError):
                return {}
            return value if isinstance(value, dict) else {}
        return {}

    def _latest_dataset_snapshot(self, cursor, dataset_code: str, trade_date: str | None = None) -> Dict[str, Any] | None:
        required_tables = {"dataset_snapshots", "dataset_snapshot_items", "dataset_partitions"}
        if any(not self._table_exists(cursor, table) for table in required_tables):
            return None
        query = """
            SELECT s.id,s.knowledge_cutoff_at,p.available_at,s.sealed_at,p.start_date,p.end_date
            FROM dataset_snapshots s
            JOIN dataset_snapshot_items i ON i.snapshot_id=s.id
            JOIN dataset_partitions p ON p.id=i.partition_id
            WHERE s.status='sealed' AND i.dataset_code=%s
        """
        params: list[object] = [dataset_code]
        if trade_date:
            query += " AND p.end_date=%s"
            params.append(trade_date)
        query += " ORDER BY p.end_date DESC NULLS LAST,s.sealed_at DESC NULLS LAST,s.id DESC LIMIT 1"
        cursor.execute(query, tuple(params))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": int(row[0]),
            "knowledge_cutoff_at": self._iso(row[1]),
            "available_at": self._iso(row[2]),
            "sealed_at": self._iso(row[3]),
            "start_date": self._iso(row[4]),
            "end_date": self._iso(row[5]),
        }

    def _dataset_snapshot_payloads(self, cursor, snapshot_id: int, dataset_code: str) -> list[Dict[str, Any]]:
        if not self._table_exists(cursor, "dataset_snapshot_items") or not self._table_exists(cursor, "dataset_partition_records"):
            return []
        cursor.execute(
            """
            SELECT r.payload
            FROM dataset_snapshot_items i
            JOIN dataset_partition_records r ON r.partition_id=i.partition_id
            WHERE i.snapshot_id=%s AND i.dataset_code=%s
            ORDER BY r.record_ordinal
            """,
            (snapshot_id, dataset_code),
        )
        return [self._payload_dict(row[0]) for row in cursor.fetchall()]

    def _overview_realtime_rows(self, cursor, trade_date: str | None) -> list[Dict[str, Any]]:
        if not self._table_exists(cursor, "realtime_quotes"):
            return []
        query = """
            SELECT r.symbol,COALESCE(NULLIF(d.name,''),r.symbol),r.exchange,
                   r.last_price,r.change_percent,r.amount,r.turnover_rate,r.volume_ratio,
                   r.trade_date,r.source,r.source_updated_at,r.collected_at
            FROM realtime_quotes r
            LEFT JOIN instrument_definitions d
              ON d.market='CN' AND d.symbol=r.symbol
             AND d.asset_class='stock' AND d.list_status IN ('L','P')
            WHERE d.symbol IS NOT NULL
        """
        params: list[object] = []
        if trade_date:
            query += " AND r.trade_date=%s"
            params.append(trade_date)
        query += " ORDER BY r.symbol"
        cursor.execute(query, tuple(params))
        return [
            {
                "symbol": row[0],
                "name": row[1],
                "exchange": row[2],
                "price": row[3],
                "change_percent": row[4],
                "amount": row[5],
                "turnover_rate": row[6],
                "volume_ratio": row[7],
                "trade_date": self._iso(row[8]),
                "source": row[9],
                "source_updated_at": self._iso(row[10]),
                "collected_at": self._iso(row[11]),
            }
            for row in cursor.fetchall()
        ]

    def _overview_daily_rows(self, cursor) -> list[Dict[str, Any]]:
        query = """
            SELECT r.code,COALESCE(NULLIF(d.name,''),r.name),COALESCE(d.exchange,'CN'),
                   r.price,r.change_percent,r.amount,r.turnover,r.volume_ratio,r.updated_at
            FROM all_stocks_realtime r
            LEFT JOIN instrument_definitions d
              ON d.market='CN'
             AND d.symbol=(split_part(r.code,'_',2)||'.'||split_part(r.code,'_',1))
            WHERE r.code ~ '^(SH|SZ|BJ)_[0-9]{6}$'
              AND (d.symbol IS NULL OR (d.asset_class='stock' AND d.list_status IN ('L','P')))
            ORDER BY r.code
        """
        cursor.execute(query)
        return [
            {
                "symbol": row[0],
                "name": row[1],
                "exchange": row[2],
                "price": row[3],
                "change_percent": row[4],
                "amount": row[5],
                "turnover_rate": row[6],
                "volume_ratio": row[7],
                "source": "tushare.daily → PostgreSQL",
                "source_updated_at": self._iso(row[8]),
                "updated_at": self._iso(row[8]),
            }
            for row in cursor.fetchall()
        ]

    def _overview_index_rows(self, cursor) -> list[Dict[str, Any]]:
        rows: list[Dict[str, Any]] = []
        if self._table_exists(cursor, "market_indices_realtime"):
            cursor.execute(
                """
                SELECT name,code,price,change_amount,change_percent,updated_at
                FROM market_indices_realtime ORDER BY id
                """
            )
            rows.extend(
                {
                    "name": row[0],
                    "code": row[1],
                    "price": row[2],
                    "change_amount": row[3],
                    "change_percent": row[4],
                    "updated_at": self._iso(row[5]),
                    "source": "PostgreSQL market_indices_realtime",
                }
                for row in cursor.fetchall()
            )
        snapshot = self._latest_dataset_snapshot(cursor, "benchmark_bars")
        if snapshot:
            for payload in self._dataset_snapshot_payloads(cursor, snapshot["id"], "benchmark_bars"):
                rows.append({
                    **payload,
                    "source_snapshot_id": snapshot["id"],
                    "available_at": snapshot["available_at"],
                    "source": payload.get("source") or "tushare.index_daily → PostgreSQL sealed snapshot",
                })
        return rows

    def _overview_trend_rows(self, cursor, trade_date: str | None) -> list[Dict[str, Any]]:
        if not self._table_exists(cursor, "stock_history"):
            return []
        query = """
            WITH recent AS (
                SELECT d.symbol,h.date,h.close,
                       ROW_NUMBER() OVER (PARTITION BY d.symbol ORDER BY h.date DESC) AS rn,
                       COUNT(*) OVER (PARTITION BY d.symbol) AS history_days
                FROM instrument_definitions d
                CROSS JOIN LATERAL (
                    SELECT deduped.date,deduped.close
                    FROM (
                        SELECT DISTINCT ON (candidates.date)
                               candidates.date,candidates.close
                        FROM (
                            SELECT current.date,current.close,0 AS source_priority
                            FROM stock_history current
                            WHERE current.symbol=d.symbol
                              AND current.close IS NOT NULL AND current.close > 0
        """
        params: list[object] = []
        if trade_date:
            query += " AND current.date<=%s"
            params.append(trade_date)
        query += """
                            UNION ALL
                            SELECT legacy.date,legacy.close,1 AS source_priority
                            FROM stock_history legacy
                            WHERE legacy.symbol=(split_part(d.symbol,'.',2)||'_'||split_part(d.symbol,'.',1))
                              AND legacy.close IS NOT NULL AND legacy.close > 0
        """
        if trade_date:
            query += " AND legacy.date<=%s"
            params.append(trade_date)
        query += """
                        ) candidates
                        ORDER BY candidates.date,candidates.source_priority
                    ) deduped
                    ORDER BY deduped.date DESC
                    LIMIT 60
                ) h
                WHERE d.market='CN'
                  AND d.asset_class='stock'
                  AND d.list_status IN ('L','P')
            )
            SELECT symbol,MAX(history_days),MAX(close) FILTER (WHERE rn=1),
                   AVG(close) FILTER (WHERE rn<=5),AVG(close) FILTER (WHERE rn<=20),
                   AVG(close) FILTER (WHERE rn<=60),MAX(close),MIN(close)
            FROM recent GROUP BY symbol ORDER BY symbol
        """
        cursor.execute(query, tuple(params))
        return [
            {
                "symbol": row[0],
                "history_days": row[1],
                "latest_close": row[2],
                "ma5": row[3],
                "ma20": row[4],
                "ma60": row[5],
                "period_high_60d": row[6],
                "period_low_60d": row[7],
            }
            for row in cursor.fetchall()
        ]

    def get_market_overview(self, trade_date: str | None = None) -> Dict[str, Any]:
        """Read all home foundation facts in one read-only database session."""
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    requested_date = trade_date
                    if not requested_date:
                        cursor.execute("SELECT MAX(date) FROM stock_history")
                        requested_date = self._iso(cursor.fetchone()[0])
                    realtime_rows = self._overview_realtime_rows(cursor, requested_date)
                    ticker_rows = realtime_rows or self._overview_daily_rows(cursor)
                    latest_updated = max(
                        (row.get("source_updated_at") or row.get("updated_at") or "" for row in ticker_rows),
                        default=None,
                    )
                    daily_snapshot = self._latest_dataset_snapshot(cursor, "daily_bars", requested_date)
                    benchmark_snapshot = self._latest_dataset_snapshot(cursor, "benchmark_bars", requested_date)
                    snapshot = daily_snapshot or benchmark_snapshot
                    suspended_symbols: set[str] = set()
                    if snapshot:
                        for payload in self._dataset_snapshot_payloads(cursor, snapshot["id"], "suspensions"):
                            symbol = self._canonical_symbol(payload.get("symbol") or payload.get("ts_code"))
                            if symbol:
                                suspended_symbols.add(symbol)
                    for row in ticker_rows:
                        if self._canonical_symbol(row.get("symbol")) in suspended_symbols:
                            row["suspended"] = True
                    index_rows = self._overview_index_rows(cursor)
                    trend_rows = self._overview_trend_rows(cursor, requested_date)
            evidence = {
                "trade_date": requested_date,
                "data_mode": "盘中实时" if realtime_rows else "盘后快照",
                "provider": "PostgreSQL · realtime_quotes" if realtime_rows else "TuShare → PostgreSQL",
                "source_snapshot_id": snapshot["id"] if snapshot else None,
                "available_at": snapshot["available_at"] if snapshot else latest_updated,
                "knowledge_cutoff_at": snapshot["knowledge_cutoff_at"] if snapshot else requested_date,
                "last_success_at": snapshot["sealed_at"] if snapshot else latest_updated,
                "status": "ready" if ticker_rows else "empty",
                "missing_inputs": [] if ticker_rows else ["没有已持久化的 A 股日线/行情事实"],
            }
            return build_market_overview(
                ticker_rows=ticker_rows,
                index_rows=index_rows,
                trend_rows=trend_rows,
                evidence=evidence,
            )
        except Exception as exc:
            return unavailable_market_overview(f"A股首页基础指标读取失败：{type(exc).__name__}")

    def get_market_phase(self, trade_date: str | None = None) -> Dict:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "market_phase_results"):
                    return {
                        "trade_date": trade_date,
                        "phase": "unknown",
                        "status": "unavailable",
                        "confidence": 0.0,
                        "reasons": [],
                        "missing_inputs": ["market_phase_results table is not migrated"],
                        "definition_version": MARKET_PHASE_DEFINITION_VERSION,
                    }
                query = """
                    SELECT trade_date,phase,status,confidence,reasons,missing_inputs,
                           source_snapshot_id,input_trade_date,definition_version,
                           available_at,knowledge_cutoff_at,computed_at
                    FROM market_phase_results
                """
                params: list[object] = []
                if trade_date:
                    query += " WHERE trade_date=%s"
                    params.append(trade_date)
                query += " ORDER BY trade_date DESC,computed_at DESC LIMIT 1"
                cursor.execute(query, tuple(params))
                row = cursor.fetchone()
        if not row:
            return {
                "trade_date": trade_date,
                "phase": "unknown",
                "status": "empty",
                "confidence": 0.0,
                "reasons": [],
                "missing_inputs": ["market phase has not been computed for this trade_date"],
                "definition_version": MARKET_PHASE_DEFINITION_VERSION,
            }
        return {
            "trade_date": str(row[0]),
            "phase": row[1],
            "status": row[2],
            "confidence": float(row[3] or 0),
            "reasons": self._json_value(row[4], []),
            "missing_inputs": self._json_value(row[5], []),
            "source_snapshot_id": row[6],
            "input_trade_date": str(row[7]) if row[7] else None,
            "definition_version": row[8],
            "available_at": self._iso(row[9]),
            "knowledge_cutoff_at": self._iso(row[10]),
            "computed_at": self._iso(row[11]),
        }

    def get_market_sentiment(self, trade_date: str | None = None) -> Dict:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "market_sentiment_results"):
                    return {
                        "trade_date": trade_date,
                        "status": "unavailable",
                        "missing_inputs": ["market_sentiment_results table is not migrated"],
                        "definition_version": "ashare-market-sentiment.v1",
                    }
                query = """
                    SELECT trade_date,status,limit_up_count,limit_down_count,failed_limit_count,
                           one_word_limit_count,seal_rate_pct,highest_streak,ladder_width,
                           promotion_rate_pct,ladder_completeness_pct,weak_market_veto,ladder,
                           price_limit_coverage,missing_inputs,source_snapshot_id,definition_version,
                           available_at,knowledge_cutoff_at,source_lineage,computed_at
                    FROM market_sentiment_results
                """
                params: list[object] = []
                if trade_date:
                    query += " WHERE trade_date=%s"
                    params.append(trade_date)
                query += " ORDER BY trade_date DESC,computed_at DESC LIMIT 1"
                cursor.execute(query, tuple(params))
                row = cursor.fetchone()
        if not row:
            return {
                "trade_date": trade_date,
                "status": "empty",
                "missing_inputs": ["market sentiment has not been computed for this trade_date"],
                "definition_version": "ashare-market-sentiment.v1",
            }
        return {
            "trade_date": str(row[0]),
            "status": row[1],
            "limit_up_count": row[2],
            "limit_down_count": row[3],
            "failed_limit_count": row[4],
            "one_word_limit_count": row[5],
            "seal_rate_pct": float(row[6]) if row[6] is not None else None,
            "highest_streak": row[7],
            "ladder_width": row[8],
            "promotion_rate_pct": float(row[9]) if row[9] is not None else None,
            "ladder_completeness_pct": float(row[10]) if row[10] is not None else None,
            "weak_market_veto": bool(row[11]),
            "ladder": self._json_value(row[12], []),
            "price_limit_coverage": float(row[13]) if row[13] is not None else None,
            "missing_inputs": self._json_value(row[14], []),
            "source_snapshot_id": row[15],
            "definition_version": row[16],
            "available_at": self._iso(row[17]),
            "knowledge_cutoff_at": self._iso(row[18]),
            "source_lineage": self._json_value(row[19], {}),
            "computed_at": self._iso(row[20]),
            "orders_created": 0,
            "paper_mutated": False,
        }

    def list_market_timeline(self, *, limit: int = 60) -> Dict[str, Any]:
        bounded = max(1, min(int(limit), 250))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "market_phase_results") or not self._table_exists(cursor, "market_sentiment_results"):
                    return {
                        "items": [],
                        "data_status": "unavailable",
                        "unavailable_reason": "market phase or sentiment table is not migrated",
                        "limit": bounded,
                    }
                cursor.execute(
                    """
                    WITH phase AS (
                        SELECT DISTINCT ON (trade_date)
                               trade_date,phase,status,confidence,reasons,missing_inputs,
                               source_snapshot_id,available_at,knowledge_cutoff_at,computed_at
                        FROM market_phase_results
                        ORDER BY trade_date DESC,computed_at DESC
                    ), sentiment AS (
                        SELECT DISTINCT ON (trade_date)
                               trade_date,status,limit_up_count,limit_down_count,failed_limit_count,
                               one_word_limit_count,seal_rate_pct,highest_streak,ladder_width,
                               promotion_rate_pct,ladder_completeness_pct,weak_market_veto,
                               ladder,price_limit_coverage,missing_inputs,source_snapshot_id,
                               available_at,knowledge_cutoff_at,computed_at
                        FROM market_sentiment_results
                        ORDER BY trade_date DESC,computed_at DESC
                    )
                    SELECT COALESCE(p.trade_date,s.trade_date),p.phase,p.status,p.confidence,p.reasons,p.missing_inputs,
                           s.status,s.limit_up_count,s.limit_down_count,s.failed_limit_count,s.one_word_limit_count,
                           s.seal_rate_pct,s.highest_streak,s.ladder_width,s.promotion_rate_pct,
                           s.ladder_completeness_pct,s.weak_market_veto,s.ladder,s.price_limit_coverage,s.missing_inputs,
                           p.source_snapshot_id,s.source_snapshot_id,
                           COALESCE(p.available_at,s.available_at),COALESCE(p.knowledge_cutoff_at,s.knowledge_cutoff_at)
                    FROM phase p FULL OUTER JOIN sentiment s ON s.trade_date=p.trade_date
                    ORDER BY COALESCE(p.trade_date,s.trade_date) DESC LIMIT %s
                    """,
                    (bounded,),
                )
                rows = cursor.fetchall()
        items = []
        for row in rows:
            phase_snapshot_id = row[20]
            sentiment_snapshot_id = row[21]
            items.append({
                "trade_date": str(row[0]),
                "phase": row[1] or "unknown",
                "phase_status": row[2] or "empty",
                "confidence": float(row[3]) if row[3] is not None else None,
                "reasons": self._json_value(row[4], []),
                "phase_missing_inputs": self._json_value(row[5], []),
                "sentiment_status": row[6] or "empty",
                "limit_up_count": row[7],
                "limit_down_count": row[8],
                "failed_limit_count": row[9],
                "one_word_limit_count": row[10],
                "seal_rate_pct": float(row[11]) if row[11] is not None else None,
                "highest_streak": row[12],
                "ladder_width": row[13],
                "promotion_rate_pct": float(row[14]) if row[14] is not None else None,
                "ladder_completeness_pct": float(row[15]) if row[15] is not None else None,
                "weak_market_veto": bool(row[16]) if row[16] is not None else None,
                "ladder": self._json_value(row[17], []),
                "price_limit_coverage": float(row[18]) if row[18] is not None else None,
                "sentiment_missing_inputs": self._json_value(row[19], []),
                "phase_snapshot_id": phase_snapshot_id,
                "sentiment_snapshot_id": sentiment_snapshot_id,
                "source_snapshot_id": phase_snapshot_id if phase_snapshot_id == sentiment_snapshot_id else None,
                "snapshot_consistent": phase_snapshot_id is not None and phase_snapshot_id == sentiment_snapshot_id,
                "available_at": self._iso(row[22]),
                "knowledge_cutoff_at": self._iso(row[23]),
            })
        return {
            "items": items,
            **self._status_for_rows(items, empty_reason="no persisted market phase timeline"),
            "limit": bounded,
            "writes_performed": False,
            "paper_mutated": False,
        }

    def list_sector_rps(
        self,
        *,
        trade_date: str | None = None,
        classification_system: str = "industry",
        limit: int = 20,
    ) -> Dict:
        bounded = max(1, min(int(limit), 1000))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "sector_rps_results"):
                    return {
                        "items": [],
                        "data_status": "unavailable",
                        "unavailable_reason": "sector_rps_results table is not migrated",
                        "definition_version": SECTOR_RPS_DEFINITION_VERSION,
                    }
                query = """
                    SELECT trade_date,classification_system,sector_code,sector_name,
                           strength_score,rps_percentile,rank,rank_change,strong_days,
                           member_coverage,leader_symbol,status,missing_inputs,source_snapshot_id,
                           definition_version,available_at,knowledge_cutoff_at,
                           return_5d,return_10d,return_20d,return_60d,amount_change_pct,
                           up_ratio,limit_up_count,member_count,leader_contribution_pct,source_lineage
                    FROM sector_rps_results
                    WHERE classification_system=%s
                """
                params: list[object] = [classification_system]
                if trade_date:
                    query += " AND trade_date=%s"
                    params.append(trade_date)
                else:
                    query += " AND trade_date=(SELECT MAX(trade_date) FROM sector_rps_results WHERE classification_system=%s)"
                    params.append(classification_system)
                query += " ORDER BY rank NULLS LAST,strength_score DESC NULLS LAST,sector_code LIMIT %s"
                params.append(bounded)
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
        items = [
            {
                "trade_date": str(row[0]),
                "classification_system": row[1],
                "sector_code": row[2],
                "sector_name": row[3],
                "strength_score": float(row[4]) if row[4] is not None else None,
                "rps_percentile": float(row[5]) if row[5] is not None else None,
                "rank": row[6],
                "rank_change": row[7],
                "strong_days": row[8],
                "member_coverage": float(row[9]) if row[9] is not None else None,
                "leader_symbol": row[10],
                "status": row[11],
                "missing_inputs": self._json_value(row[12], []),
                "source_snapshot_id": row[13],
                "definition_version": row[14],
                "available_at": self._iso(row[15]),
                "knowledge_cutoff_at": self._iso(row[16]),
                "return_5d": float(row[17]) if row[17] is not None else None,
                "return_10d": float(row[18]) if row[18] is not None else None,
                "return_20d": float(row[19]) if row[19] is not None else None,
                "return_60d": float(row[20]) if row[20] is not None else None,
                "amount_change_pct": float(row[21]) if row[21] is not None else None,
                "up_ratio": float(row[22]) if row[22] is not None else None,
                "limit_up_count": row[23],
                "member_count": row[24],
                "leader_contribution_pct": float(row[25]) if row[25] is not None else None,
                "source_lineage": self._json_value(row[26], {}),
            }
            for row in rows
        ]
        unavailable_markers = [item for item in items if str(item.get("sector_code") or "").startswith("__")]
        items = [item for item in items if item not in unavailable_markers]
        if unavailable_markers and not items:
            unavailable_reason = " · ".join(unavailable_markers[0].get("missing_inputs") or []) or "sector classification unavailable"
            status = {"data_status": "partial", "unavailable_reason": unavailable_reason}
        else:
            status = self._status_for_rows(items, empty_reason="no sector/concept RPS result for this query")
        return {
            "items": items,
            **status,
            "definition_version": SECTOR_RPS_DEFINITION_VERSION,
        }

    def get_sector_rps_history(self, sector_code: str, *, classification_system: str = "industry", limit: int = 60) -> Dict:
        bounded = max(1, min(int(limit), 250))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "sector_rps_results"):
                    return {
                        "items": [],
                        "data_status": "unavailable",
                        "unavailable_reason": "sector_rps_results table is not migrated",
                        "definition_version": SECTOR_RPS_DEFINITION_VERSION,
                    }
                cursor.execute(
                    """
                    SELECT trade_date,sector_code,sector_name,strength_score,rps_percentile,rank,rank_change,
                           status,strong_days,member_coverage,member_count,leader_symbol,
                           leader_contribution_pct,source_snapshot_id,available_at,knowledge_cutoff_at,
                           return_5d,return_10d,return_20d,return_60d,amount_change_pct,up_ratio,limit_up_count
                    FROM sector_rps_results
                    WHERE classification_system=%s AND sector_code=%s
                    ORDER BY trade_date DESC LIMIT %s
                    """,
                    (classification_system, sector_code, bounded),
                )
                rows = list(reversed(cursor.fetchall()))
        items = [
            {
                "trade_date": str(row[0]),
                "sector_code": row[1],
                "sector_name": row[2],
                "strength_score": float(row[3]) if row[3] is not None else None,
                "rps_percentile": float(row[4]) if row[4] is not None else None,
                "rank": row[5],
                "rank_change": row[6],
                "status": row[7],
                "strong_days": row[8],
                "member_coverage": float(row[9]) if row[9] is not None else None,
                "member_count": row[10],
                "leader_symbol": row[11],
                "leader_contribution_pct": float(row[12]) if row[12] is not None else None,
                "source_snapshot_id": row[13],
                "available_at": self._iso(row[14]),
                "knowledge_cutoff_at": self._iso(row[15]),
                "return_5d": float(row[16]) if row[16] is not None else None,
                "return_10d": float(row[17]) if row[17] is not None else None,
                "return_20d": float(row[18]) if row[18] is not None else None,
                "return_60d": float(row[19]) if row[19] is not None else None,
                "amount_change_pct": float(row[20]) if row[20] is not None else None,
                "up_ratio": float(row[21]) if row[21] is not None else None,
                "limit_up_count": row[22],
            }
            for row in rows
        ]
        return {
            "items": items,
            **self._status_for_rows(items, empty_reason=f"no RPS history for {sector_code}"),
            "definition_version": SECTOR_RPS_DEFINITION_VERSION,
        }

    def list_sector_members(
        self,
        sector_code: str,
        *,
        classification_system: str = "industry",
        trade_date: str | None = None,
        limit: int = 500,
    ) -> Dict[str, Any]:
        bounded = max(1, min(int(limit), 2000))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "sector_membership_snapshots"):
                    return {
                        "items": [],
                        "data_status": "unavailable",
                        "unavailable_reason": "sector_membership_snapshots table is not migrated",
                    }
                requested_date = trade_date
                if not requested_date:
                    cursor.execute(
                        """SELECT MAX(trade_date) FROM sector_membership_snapshots
                           WHERE classification_system=%s AND sector_code=%s""",
                        (classification_system, sector_code),
                    )
                    row = cursor.fetchone()
                    requested_date = str(row[0]) if row and row[0] else None
                if not requested_date:
                    return {
                        "items": [],
                        "data_status": "empty",
                        "unavailable_reason": "no sector membership snapshot for this query",
                    }
                cursor.execute(
                    """
                    SELECT m.trade_date,m.classification_system,m.sector_code,m.sector_name,
                           m.symbol,i.name,i.board,m.source_snapshot_id,m.source,m.membership_bias,m.available_at,
                           COUNT(*) OVER() AS total_count
                    FROM sector_membership_snapshots m
                    LEFT JOIN instrument_definitions i ON i.market='CN' AND i.symbol=m.symbol
                    WHERE m.trade_date=%s AND m.classification_system=%s AND m.sector_code=%s
                    ORDER BY i.name NULLS LAST,m.symbol LIMIT %s
                    """,
                    (requested_date, classification_system, sector_code, bounded),
                )
                rows = cursor.fetchall()
        items = [
            {
                "trade_date": str(row[0]),
                "classification_system": row[1],
                "sector_code": row[2],
                "sector_name": row[3],
                "symbol": row[4],
                "name": row[5],
                "board": row[6],
                "source_snapshot_id": row[7],
                "source": row[8],
                "membership_bias": row[9],
                "available_at": self._iso(row[10]),
            }
            for row in rows
        ]
        return {
            "items": items,
            **self._status_for_rows(items, empty_reason="no sector members for this query"),
            "trade_date": requested_date,
            "classification_system": classification_system,
            "sector_code": sector_code,
            "source_snapshot_id": items[0]["source_snapshot_id"] if items else None,
            "membership_bias": items[0]["membership_bias"] if items else None,
            "total": int(rows[0][11]) if rows else 0,
        }

    def list_symbol_abnormalities(self, *, trade_date: str | None = None, limit: int = 20) -> Dict:
        bounded = max(1, min(int(limit), 200))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "symbol_abnormal_metrics"):
                    return {
                        "items": [],
                        "data_status": "unavailable",
                        "unavailable_reason": "symbol_abnormal_metrics table is not migrated",
                        "definition_version": ABNORMALITY_DEFINITION_VERSION,
                    }
                query = """
                    SELECT m.symbol,m.trade_date,m.return_3d,m.return_10d,m.return_30d,
                           m.benchmark_deviation_3d,m.benchmark_deviation_10d,m.benchmark_deviation_30d,
                           m.sector_deviation_3d,m.sector_deviation_10d,m.sector_deviation_30d,
                           m.amount_ratio_5d,m.distance_to_60d_high_pct,m.distance_to_60d_low_pct,
                           m.tags,m.status,m.missing_inputs,m.definition_version,m.available_at,m.knowledge_cutoff_at,
                           m.source_snapshot_id,m.benchmark_code,m.sector_code,
                           i.name,i.board
                    FROM symbol_abnormal_metrics m
                    LEFT JOIN instrument_definitions i
                      ON i.market='CN' AND i.symbol=m.symbol
                """
                params: list[object] = []
                if trade_date:
                    query += " WHERE m.trade_date=%s"
                    params.append(trade_date)
                else:
                    query += " WHERE m.trade_date=(SELECT MAX(latest.trade_date) FROM symbol_abnormal_metrics latest)"
                query += " ORDER BY m.trade_date DESC,ABS(COALESCE(m.benchmark_deviation_3d,0)) DESC,m.symbol LIMIT %s"
                params.append(min(2000, bounded * 10))
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
        observed_items = [self._abnormality_row(row) for row in rows]
        items = sorted(
            (item for item in observed_items if item.get("eligible")),
            key=lambda item: (-float(item.get("max_closeness") or 0), str(item.get("symbol") or "")),
        )[:bounded]
        missing_inputs = sorted({
            str(missing)
            for item in observed_items
            for missing in item.get("missing_inputs") or []
            if str(missing).strip()
        })
        if items:
            data_status = "ok"
            unavailable_reason = None
        elif observed_items:
            data_status = "partial"
            unavailable_reason = "异动指标缺少完整的 3/10/30 日基准、行业或价格窗口"
        else:
            data_status = "empty"
            unavailable_reason = "no abnormality metrics for this query"
        return {
            "items": items,
            "data_status": data_status,
            "unavailable_reason": unavailable_reason,
            "observed_count": len(observed_items),
            "eligible_count": len(items),
            "missing_inputs": missing_inputs,
            "definition_version": ABNORMALITY_DEFINITION_VERSION,
        }

    def get_symbol_abnormality(self, symbol: str, *, trade_date: str | None = None) -> Dict:
        canonical = self._canonical_symbol(symbol)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "symbol_abnormal_metrics"):
                    return {
                        "symbol": canonical,
                        "data_status": "unavailable",
                        "unavailable_reason": "symbol_abnormal_metrics table is not migrated",
                        "definition_version": ABNORMALITY_DEFINITION_VERSION,
                    }
                query = """
                    SELECT m.symbol,m.trade_date,m.return_3d,m.return_10d,m.return_30d,
                           m.benchmark_deviation_3d,m.benchmark_deviation_10d,m.benchmark_deviation_30d,
                           m.sector_deviation_3d,m.sector_deviation_10d,m.sector_deviation_30d,
                           m.amount_ratio_5d,m.distance_to_60d_high_pct,m.distance_to_60d_low_pct,
                           m.tags,m.status,m.missing_inputs,m.definition_version,m.available_at,m.knowledge_cutoff_at,
                           m.source_snapshot_id,m.benchmark_code,m.sector_code,
                           i.name,i.board
                    FROM symbol_abnormal_metrics m
                    LEFT JOIN instrument_definitions i
                      ON i.market='CN' AND i.symbol=m.symbol
                    WHERE m.symbol=%s
                """
                params: list[object] = [canonical]
                if trade_date:
                    query += " AND m.trade_date=%s"
                    params.append(trade_date)
                query += " ORDER BY m.trade_date DESC LIMIT 1"
                cursor.execute(query, tuple(params))
                row = cursor.fetchone()
        if not row:
            return {
                "symbol": canonical,
                "data_status": "empty",
                "unavailable_reason": f"no abnormality metrics for {canonical}",
                "definition_version": ABNORMALITY_DEFINITION_VERSION,
            }
        payload = self._abnormality_row(row)
        return payload

    def _abnormality_row(self, row: Any) -> Dict:
        missing_inputs = list(self._json_value(row[16], []) or [])
        name = row[23] if len(row) > 23 else None
        board = row[24] if len(row) > 24 else None
        rule = abnormal_rule_for(str(row[0]), name, board)
        windows = build_abnormal_windows(
            {
                f"benchmark_deviation_{window}d": row[5 + index]
                for index, window in enumerate((3, 10, 30))
            },
            rule,
            values_are_percent=True,
        )
        if row[15] != "ok" or len(windows) != len(ABNORMAL_WINDOW_KEYS):
            if len(windows) != len(ABNORMAL_WINDOW_KEYS) and "基准偏离值窗口缺失" not in missing_inputs:
                missing_inputs.append("基准偏离值窗口缺失")
            windows = {}
        max_closeness = max((float(item["closeness"]) for item in windows.values()), default=None)
        dominant_window = max(windows, key=lambda key: windows[key]["closeness"]) if windows else None
        data_status = "ok" if row[15] == "ok" and windows else "partial"
        return {
            "symbol": row[0],
            "name": name,
            "board": rule.board,
            "st": rule.st,
            "trade_date": str(row[1]),
            "return_3d": float(row[2]) if row[2] is not None else None,
            "return_10d": float(row[3]) if row[3] is not None else None,
            "return_30d": float(row[4]) if row[4] is not None else None,
            "benchmark_deviation_3d": float(row[5]) if row[5] is not None else None,
            "benchmark_deviation_10d": float(row[6]) if row[6] is not None else None,
            "benchmark_deviation_30d": float(row[7]) if row[7] is not None else None,
            "sector_deviation_3d": float(row[8]) if row[8] is not None else None,
            "sector_deviation_10d": float(row[9]) if row[9] is not None else None,
            "sector_deviation_30d": float(row[10]) if row[10] is not None else None,
            "amount_ratio_5d": float(row[11]) if row[11] is not None else None,
            "distance_to_60d_high_pct": float(row[12]) if row[12] is not None else None,
            "distance_to_60d_low_pct": float(row[13]) if row[13] is not None else None,
            "tags": self._json_value(row[14], []),
            "status": row[15],
            "data_status": data_status,
            "missing_inputs": missing_inputs,
            "definition_version": row[17],
            "available_at": self._iso(row[18]),
            "knowledge_cutoff_at": self._iso(row[19]),
            "source_snapshot_id": row[20] if len(row) > 20 else None,
            "benchmark_code": row[21] if len(row) > 21 else None,
            "sector_code": row[22] if len(row) > 22 else None,
            "thresholds": {
                f"{window}d": {"up": rule.thresholds[window][0], "down": rule.thresholds[window][1]}
                for window in (3, 10, 30)
            },
            "windows": windows,
            "max_closeness": max_closeness,
            "abnormal_status": windows[dominant_window]["status"] if dominant_window else None,
            "eligible": data_status == "ok" and len(windows) == len(ABNORMAL_WINDOW_KEYS),
        }

    @staticmethod
    def _event_source(raw: Any) -> str:
        value = str(raw or "").strip().lower()
        return {
            "pool": "abnormal",
            "data": "price",
            "risk": "strategy",
            "system": "price",
        }.get(value, value if value in {"strategy", "signal", "price", "abnormal", "sector"} else "strategy")

    @staticmethod
    def _event_severity(raw: Any) -> str:
        value = str(raw or "").strip().lower()
        return {"warn": "warning", "error": "critical", "block": "critical"}.get(
            value,
            value if value in {"info", "warning", "critical"} else "info",
        )

    @staticmethod
    def _event_number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number == number and abs(number) != float("inf") else None

    @classmethod
    def _event_row(
        cls,
        *,
        event_id: Any,
        source: Any,
        severity: Any,
        symbol: Any = None,
        name: Any = None,
        price: Any = None,
        change_percent: Any = None,
        rule_id: Any = None,
        rule_name: Any = None,
        message: Any = None,
        source_object_type: Any = None,
        source_object_id: Any = None,
        evidence: Any = None,
        triggered_at: Any = None,
    ) -> Dict[str, Any]:
        payload = dict(evidence) if isinstance(evidence, dict) else {}
        resolved_symbol = symbol or payload.get("symbol") or payload.get("instrument")
        resolved_name = name or payload.get("name") or payload.get("symbol_name")
        resolved_price = price if price is not None else payload.get("price")
        resolved_change = change_percent
        if resolved_change is None:
            resolved_change = payload.get("change_percent", payload.get("change_pct"))
        resolved_rule_id = rule_id or payload.get("rule_id")
        resolved_rule_name = rule_name or payload.get("rule_name")
        return {
            "event_id": str(event_id),
            "source": cls._event_source(source),
            "severity": cls._event_severity(severity),
            "symbol": str(resolved_symbol).strip() if resolved_symbol else None,
            "name": str(resolved_name).strip() if resolved_name else None,
            "price": cls._event_number(resolved_price),
            "change_percent": cls._event_number(resolved_change),
            "rule_id": str(resolved_rule_id) if resolved_rule_id else None,
            "rule_name": str(resolved_rule_name) if resolved_rule_name else None,
            "message": str(message or payload.get("message") or "市场告警事件"),
            "source_object_type": str(source_object_type or payload.get("source_object_type") or "market_event"),
            "source_object_id": str(source_object_id or event_id),
            "evidence": payload,
            # This stream is alert-only by contract.  Do not trust source
            # payloads to report an order count back to the operator.
            "orders_created": 0,
            "paper_mutated": False,
            "triggered_at": cls._iso(triggered_at),
        }

    def list_market_events(
        self,
        *,
        limit: int = 10,
        source: str | None = None,
        severity: str | None = None,
    ) -> Dict[str, Any]:
        """Read the persisted alert/event stream without evaluating or writing anything."""
        bounded = max(1, min(int(limit), 100))
        normalized_source = self._event_source(source) if source else None
        normalized_severity = self._event_severity(severity) if severity else None
        events: list[Dict[str, Any]] = []
        available = False
        query_errors: list[str] = []

        with self._connect() as connection:
            with connection.cursor() as cursor:
                table_flags = {
                    table: self._table_exists(cursor, table)
                    for table in (
                        "market_alert_events",
                        "alerts",
                        "strategy_signals",
                        "paper_instance_events",
                        "risk_events",
                    )
                }
                available = any(table_flags.values())

                if table_flags["market_alert_events"]:
                    cursor.execute(
                        """
                        SELECT id::text,source,severity,symbol,name,price,change_percent,
                               rule_id,rule_name,message,source_object_type,source_object_id,
                               evidence,triggered_at
                        FROM market_alert_events
                        ORDER BY triggered_at DESC,id DESC
                        LIMIT %s
                        """,
                        (bounded * 4,),
                    )
                    for row in cursor.fetchall():
                        events.append(self._event_row(
                            event_id=row[0], source=row[1], severity=row[2], symbol=row[3], name=row[4],
                            price=row[5], change_percent=row[6], rule_id=row[7], rule_name=row[8],
                            message=row[9], source_object_type=row[10], source_object_id=row[11],
                            evidence=row[12], triggered_at=row[13],
                        ))

                if table_flags["alerts"]:
                    cursor.execute(
                        """
                        SELECT id::text,category,severity,title,message,source_object_type,
                               source_object_id,evidence,triggered_at
                        FROM alerts
                        ORDER BY triggered_at DESC,id DESC
                        LIMIT %s
                        """,
                        (bounded * 4,),
                    )
                    for row in cursor.fetchall():
                        events.append(self._event_row(
                            event_id=row[0], source=row[1], severity=row[2], rule_name=row[3],
                            message=row[4], source_object_type=row[5], source_object_id=row[6],
                            evidence=row[7], triggered_at=row[8],
                        ))

                if table_flags["strategy_signals"]:
                    cursor.execute(
                        """
                        SELECT id::text,symbol,name,signal_type,status,signal_time,price,reason,payload
                        FROM strategy_signals
                        ORDER BY signal_time DESC,id DESC
                        LIMIT %s
                        """,
                        (bounded * 4,),
                    )
                    for row in cursor.fetchall():
                        payload = dict(row[8]) if isinstance(row[8], dict) else {}
                        events.append(self._event_row(
                            event_id=row[0], source="signal", severity="warning" if row[4] == "invalidated" else "info",
                            symbol=row[1], name=row[2], price=row[6], rule_id=payload.get("rule_id"),
                            rule_name=payload.get("rule_name"), message=row[7] or f"{row[3] or 'signal'} 信号",
                            source_object_type="strategy_signal", source_object_id=row[0], evidence=payload,
                            triggered_at=row[5],
                        ))

                if table_flags["paper_instance_events"]:
                    cursor.execute(
                        """
                        SELECT id::text,event_type,level,message,payload,occurred_at
                        FROM paper_instance_events
                        ORDER BY occurred_at DESC,id DESC
                        LIMIT %s
                        """,
                        (bounded * 4,),
                    )
                    for row in cursor.fetchall():
                        events.append(self._event_row(
                            event_id=row[0], source="strategy", severity=row[2], message=row[3],
                            source_object_type="paper_instance_event", source_object_id=row[0], evidence=row[4],
                            rule_name=row[1], triggered_at=row[5],
                        ))

                if table_flags["risk_events"]:
                    cursor.execute(
                        """
                        SELECT id::text,severity,message,payload,created_at
                        FROM risk_events
                        ORDER BY created_at DESC,id DESC
                        LIMIT %s
                        """,
                        (bounded * 4,),
                    )
                    for row in cursor.fetchall():
                        events.append(self._event_row(
                            event_id=row[0], source="strategy", severity=row[1], message=row[2],
                            source_object_type="risk_event", source_object_id=row[0], evidence=row[3],
                            triggered_at=row[4],
                        ))

        events = [
            event for event in events
            if (normalized_source is None or event["source"] == normalized_source)
            and (normalized_severity is None or event["severity"] == normalized_severity)
        ]
        events.sort(key=lambda event: (event.get("triggered_at") or "", event.get("event_id") or ""), reverse=True)
        events = events[:bounded]
        if events:
            data_status = "ok"
            unavailable_reason = None
        elif available:
            data_status = "empty"
            unavailable_reason = "暂无可追溯的市场告警事件"
        else:
            data_status = "unavailable"
            unavailable_reason = "市场告警事件表尚未迁移"
        return {
            "events": events,
            "data_status": data_status,
            "unavailable_reason": unavailable_reason,
            "orders_created": 0,
            "paper_mutated": False,
            "limit": bounded,
            "query_errors": query_errors,
        }

    def append_market_alert_events(self, events: list[Dict[str, Any]]) -> int:
        """Persist explicit alert evaluation results without touching Paper ledgers.

        This write method is intentionally separate from every homepage/monitor
        GET path. Callers must provide a stable source object and dedupe key;
        the database constraints provide the final ``orders_created=0`` and
        ``paper_mutated=false`` guard.
        """
        if not events:
            return 0
        values: list[tuple[Any, ...]] = []
        for event in events:
            source = str(event.get("source") or "").strip().lower()
            severity = str(event.get("severity") or "").strip().lower()
            if source not in {"strategy", "signal", "price", "abnormal", "sector"}:
                raise ValueError("market alert event source is invalid")
            if severity not in {"info", "warning", "critical"}:
                raise ValueError("market alert event severity is invalid")
            if int(event.get("orders_created") or 0) != 0 or bool(event.get("paper_mutated")):
                raise ValueError("market alert events cannot create orders or mutate Paper")
            source_object_type = str(event.get("source_object_type") or "").strip()
            source_object_id = str(event.get("source_object_id") or "").strip()
            dedupe_key = str(event.get("dedupe_key") or f"{source}:{source_object_type}:{source_object_id}").strip()
            if not source_object_type or not source_object_id or not dedupe_key:
                raise ValueError("market alert event requires source object and dedupe key")
            evidence = event.get("evidence") if isinstance(event.get("evidence"), dict) else {}
            values.append((
                source,
                severity,
                event.get("symbol"),
                event.get("name"),
                event.get("price"),
                event.get("change_percent"),
                event.get("rule_id"),
                event.get("rule_name"),
                str(event.get("message") or "市场告警事件"),
                source_object_type,
                source_object_id,
                psycopg2.extras.Json(evidence),
                dedupe_key,
                event.get("triggered_at"),
            ))
        connection = self.connection_factory(self.database_url)
        connection.set_session(readonly=False, autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO market_alert_events(
                        source,severity,symbol,name,price,change_percent,rule_id,rule_name,
                        message,source_object_type,source_object_id,evidence,
                        orders_created,paper_mutated,dedupe_key,triggered_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,FALSE,%s,COALESCE(%s::timestamptz,NOW()))
                    ON CONFLICT(dedupe_key) DO NOTHING
                    """,
                    values,
                )
                inserted = cursor.rowcount
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return max(0, int(inserted or 0))
