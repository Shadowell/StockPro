"""
BitPro 风格 K 线同步服务的 A 股 PG 实现。

BitPro 的核心语义是：K 线数据有分周期存储、同步元数据、同步任务和任务项。
StockPro 使用单一 Postgres 数据通道，把这些语义全部映射到 PostgreSQL。
"""
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from app.services.tushare_provider import market_data_provider as ak
import pandas as pd

from app.db import db_instance as default_db


KlineFetcher = Callable[[str, str, str, str], List[Dict[str, Any]]]


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

    def run_job(self, job_id: int) -> Dict[str, Any]:
        self.db.update_sync_job_status(job_id, "running", "K线历史同步运行中")
        items = self.db.get_sync_job_items(job_id)
        for item in items:
            if item["status"] not in {"pending", "running"}:
                continue
            self.db.update_sync_job_item(item["id"], status="running")
            try:
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
