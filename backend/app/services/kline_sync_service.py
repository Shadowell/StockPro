"""
BitPro 风格 K 线同步服务的 A 股 PG 实现。

BitPro 的核心语义是：K 线数据有分周期存储、同步元数据、同步任务和任务项。
StockPro 使用单一 Postgres 数据通道，把这些语义全部映射到 PostgreSQL。

全市场日线优先按交易日拉取（TuShare ``daily(trade_date=...)``），避免按标的
逐一请求导致全市场 × 一年不可用。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from app.services.tushare_provider import market_data_provider as ak
import pandas as pd

from app.db import db_instance as default_db


KlineFetcher = Callable[[str, str, str, str], List[Dict[str, Any]]]
MARKET_SYMBOL = "__MARKET__"
# TuShare 积分档常见上限约 200 次/分钟；全市场按日约 250 次/年，保守限流。
MARKET_DAY_SLEEP_SECONDS = 0.35


class KlineSyncService:
    SYMBOL_NAME_FALLBACKS = {
        "SH_600000": "浦发银行",
        "SZ_000001": "平安银行",
    }

    def __init__(self, db=None, fetcher: Optional[KlineFetcher] = None):
        self.db = db or default_db
        self.fetcher = fetcher or self._fetch_from_provider

    def create_history_sync_job(
        self,
        symbols: List[str],
        timeframes: List[str],
        start_date: str,
        end_date: str,
        job_name: Optional[str] = None,
    ) -> int:
        normalized_symbols = [self._normalize_symbol(symbol) for symbol in symbols if str(symbol or "").strip()]
        normalized_symbols = list(dict.fromkeys(normalized_symbols))
        normalized_timeframes = [self._normalize_timeframe(timeframe) for timeframe in timeframes if str(timeframe or "").strip()]
        normalized_timeframes = list(dict.fromkeys(normalized_timeframes)) or ["1d"]
        if not normalized_symbols:
            raise ValueError("symbols is required")
        if any(timeframe != "1d" for timeframe in normalized_timeframes):
            raise ValueError("StockPro only supports A-share daily kline sync")
        return self.db.create_sync_job(
            job_name=job_name or f"kline-sync-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            symbols=normalized_symbols,
            timeframes=normalized_timeframes,
            start_date=start_date,
            end_date=end_date,
            source="tushare",
        )

    def create_market_daily_sync_job(
        self,
        start_date: str,
        end_date: str,
        job_name: Optional[str] = None,
        trade_dates: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create one job item per open trade date for full-market daily bars."""
        dates = list(trade_dates or [])
        if not dates:
            if not hasattr(ak, "trade_cal_open_dates"):
                raise RuntimeError("Market data provider does not expose trade_cal_open_dates")
            dates = ak.trade_cal_open_dates(start_date, end_date)
        dates = [str(value).strip()[:10] for value in dates if str(value or "").strip()]
        dates = sorted(set(dates))
        if not dates:
            raise ValueError(f"区间 {start_date} ~ {end_date} 内无交易日，无法创建全市场同步任务")
        if not hasattr(self.db, "create_market_day_sync_job"):
            raise RuntimeError("Database does not support market-day sync jobs")
        name = job_name or f"market-daily-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        job_id = self.db.create_market_day_sync_job(
            job_name=name,
            trade_dates=dates,
            source="tushare",
            market_symbol=MARKET_SYMBOL,
        )
        return {
            "jobId": job_id,
            "job_id": job_id,
            "jobName": name,
            "startDate": dates[0],
            "endDate": dates[-1],
            "tradeDates": dates,
            "tradeDateCount": len(dates),
            "mode": "market_by_trade_date",
        }

    def run_job(self, job_id: int) -> Dict[str, Any]:
        self.db.update_sync_job_status(job_id, "running", "K线历史同步运行中")
        items = self.db.get_sync_job_items(job_id)
        name_map = self._load_symbol_name_map()
        market_item_seen = False
        for item in items:
            if item["status"] not in {"pending", "running"}:
                continue
            self.db.update_sync_job_item(item["id"], status="running")
            try:
                if self._is_market_item(item["symbol"]):
                    if market_item_seen:
                        time.sleep(MARKET_DAY_SLEEP_SECONDS)
                    market_item_seen = True
                    trade_date = str(item.get("start_date") or item.get("end_date") or "")[:10]
                    records = self._fetch_market_day(trade_date, name_map=name_map)
                else:
                    records = self.fetcher(
                        item["symbol"],
                        item["timeframe"],
                        item["start_date"],
                        item["end_date"],
                    )
                self.db.insert_klines(records, timeframe=item["timeframe"], exchange=item["exchange"])
                actual_sources = {str(record.get("source") or "unknown") for record in records}
                fallback_reasons = {str(record.get("fallback_reason")) for record in records if record.get("fallback_reason")}
                self.db.update_sync_job_item(
                    item["id"],
                    status="success",
                    records_count=len(records),
                    actual_source=next(iter(actual_sources)) if len(actual_sources) == 1 else "mixed",
                    fallback_reason=";".join(sorted(fallback_reasons)) or None,
                )
            except Exception as exc:
                self.db.update_sync_metadata(
                    item["symbol"],
                    timeframe=item["timeframe"],
                    exchange=item["exchange"],
                    status="failed",
                    error_message=str(exc),
                )
                self.db.update_sync_job_item(
                    item["id"],
                    status="failed",
                    records_count=0,
                    error_message=str(exc),
                )
            self.db.refresh_sync_job_progress(job_id)
        job = self.db.refresh_sync_job_progress(job_id)
        if job and job["status"] == "success":
            self.db.update_sync_job_status(job_id, "success", "K线历史同步完成")
            job = self.db.get_sync_job(job_id)
        elif job and job["status"] in {"partial", "failed"}:
            self.db.update_sync_job_status(job_id, job["status"], "K线历史同步部分失败" if job["status"] == "partial" else "K线历史同步失败")
            job = self.db.get_sync_job(job_id)
        return job or {"id": job_id, "status": "unknown"}

    def _is_market_item(self, symbol: Any) -> bool:
        text = str(symbol or "").strip().upper()
        return text == MARKET_SYMBOL or text.startswith(f"{MARKET_SYMBOL}:")

    def _fetch_market_day(self, trade_date: str, name_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        if not trade_date:
            raise ValueError("trade_date is required for market-day sync")
        if not hasattr(ak, "daily_by_trade_date"):
            raise RuntimeError("Market data provider does not expose daily_by_trade_date")
        frame = ak.daily_by_trade_date(trade_date)
        if frame is None or getattr(frame, "empty", True):
            return []
        names = name_map or {}
        records: List[Dict[str, Any]] = []
        for _, row in frame.iterrows():
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            records.append(
                {
                    "exchange": "cn",
                    "symbol": symbol,
                    "name": names.get(symbol, ""),
                    "date": str(row.get("日期") or trade_date)[:10],
                    "open": self._float(row.get("开盘")),
                    "high": self._float(row.get("最高")),
                    "low": self._float(row.get("最低")),
                    "close": self._float(row.get("收盘")),
                    "volume": self._int(row.get("成交量")),
                    "turnover": self._float(row.get("成交额")),
                    "source": "tushare",
                }
            )
        return records

    def _fetch_from_provider(self, symbol: str, timeframe: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        if self._normalize_timeframe(timeframe) != "1d":
            raise ValueError("Only daily kline sync is supported")
        digits = "".join(ch for ch in symbol if ch.isdigit())
        if not digits:
            raise ValueError(f"Invalid A-share symbol: {symbol}")
        source = "unknown"
        fallback_reason = None
        if hasattr(ak, "stock_zh_a_hist_with_source"):
            df, source, fallback_reason = ak.stock_zh_a_hist_with_source(
                symbol=digits,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="",
            )
        else:
            df = ak.stock_zh_a_hist(
                symbol=digits,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="",
            )
        if df is None or df.empty:
            return []
        stock_name = self._resolve_symbol_name(symbol)
        records: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            row_name = str(row.get("股票简称") or row.get("名称") or "").strip()
            if not self._is_valid_symbol_name(symbol, row_name):
                row_name = stock_name
            records.append(
                {
                    "exchange": "cn",
                    "symbol": symbol,
                    "name": row_name,
                    "date": str(row.get("日期")),
                    "open": self._float(row.get("开盘")),
                    "high": self._float(row.get("最高")),
                    "low": self._float(row.get("最低")),
                    "close": self._float(row.get("收盘")),
                    "volume": self._int(row.get("成交量")),
                    "turnover": self._float(row.get("成交额")),
                    "source": source,
                    "fallback_reason": fallback_reason,
                }
            )
        return records

    def _load_symbol_name_map(self) -> Dict[str, str]:
        if not hasattr(self.db, "get_all_stocks_realtime"):
            return {}
        try:
            rows = self.db.get_all_stocks_realtime() or []
        except Exception:
            return {}
        mapping: Dict[str, str] = {}
        for row in rows:
            symbol = self._normalize_symbol(row.get("code") or row.get("symbol") or "")
            name = str(row.get("name") or "").strip()
            if symbol and name:
                mapping[symbol] = name
        return mapping

    def _normalize_symbol(self, symbol: str) -> str:
        text = str(symbol or "").strip().upper().replace(".", "_")
        if text.startswith(("SH_", "SZ_", "BJ_")):
            return text
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return text
        if digits.startswith("6"):
            return f"SH_{digits}"
        if digits.startswith(("8", "4")):
            return f"BJ_{digits}"
        return f"SZ_{digits}"

    def _resolve_symbol_name(self, symbol: str) -> str:
        normalized = self._normalize_symbol(symbol)
        candidates = [normalized]
        digits = "".join(ch for ch in normalized if ch.isdigit())
        if digits:
            candidates.append(digits)
        ph = self._placeholder()
        candidate_sql = ", ".join([ph] * len(candidates))
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            for table, column in [
                ("all_stocks_realtime", "code"),
                ("stock_fundamentals", "symbol"),
                ("stock_history", "symbol"),
                ("kline_history", "symbol"),
            ]:
                cursor.execute(
                    f"""
                    SELECT name
                    FROM {table}
                    WHERE {column} IN ({candidate_sql})
                      AND COALESCE(name, '') <> ''
                    LIMIT 1
                    """,
                    tuple(candidates),
                )
                row = cursor.fetchone()
                if row and self._is_valid_symbol_name(normalized, row[0]):
                    return str(row[0]).strip()
        except Exception:
            return self.SYMBOL_NAME_FALLBACKS.get(normalized, "")
        finally:
            conn.close()
        return self.SYMBOL_NAME_FALLBACKS.get(normalized, "")

    def _is_valid_symbol_name(self, symbol: str, name: Any) -> bool:
        clean_name = str(name or "").strip()
        if not clean_name:
            return False
        normalized = self._normalize_symbol(symbol)
        return self._normalize_symbol(clean_name) != normalized and clean_name.upper() != normalized

    def _placeholder(self) -> str:
        return "%s"

    def _normalize_timeframe(self, timeframe: str) -> str:
        text = str(timeframe or "1d").strip().lower()
        if text in {"daily", "day", "d"}:
            return "1d"
        return text

    def _float(self, value, default: float = 0.0) -> float:
        try:
            if value is None or pd.isna(value):
                return default
            return float(value)
        except Exception:
            return default

    def _int(self, value, default: int = 0) -> int:
        try:
            if value is None or pd.isna(value):
                return default
            return int(float(value))
        except Exception:
            return default
