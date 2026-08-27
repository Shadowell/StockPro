"""AKShare pull provider for A-share intraday bars."""
from __future__ import annotations

import math
import os
import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from app.core.config import settings

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class _CacheEntry:
    expires_at: float
    payload: Dict[str, Any]


class AkshareIntradayProvider:
    """Fetch recent A-share intraday bars from AKShare without writing storage."""

    PRIMARY_SOURCE = "akshare.stock_zh_a_hist_min_em"
    SINA_SOURCE = "akshare.stock_zh_a_minute"
    SUPPORTED_TIMEFRAMES = {"1m", "5m", "15m", "30m", "60m"}

    def __init__(
        self,
        *,
        fetcher: Optional[Callable[..., Any]] = None,
        ttl_seconds: int = 30,
        error_ttl_seconds: int = 120,
    ) -> None:
        self.fetcher = fetcher
        self.ttl_seconds = max(5, int(ttl_seconds))
        self.error_ttl_seconds = max(10, int(error_ttl_seconds))
        self._cache: Dict[Tuple[str, str, int, Optional[int], Optional[int]], _CacheEntry] = {}
        self._lock = threading.Lock()

    @staticmethod
    def canonical_symbol(raw: str) -> str:
        value = str(raw or "").strip().upper()
        if "." in value:
            return value
        if "_" in value:
            exchange, digits = value.split("_", 1)
            return f"{digits}.{exchange}"
        exchange = "SH" if value.startswith(("5", "6", "9")) else ("BJ" if value.startswith(("4", "8")) else "SZ")
        return f"{value}.{exchange}"

    @staticmethod
    def _akshare_symbol(canonical: str) -> str:
        return canonical.split(".", 1)[0]

    @staticmethod
    def _sina_symbol(canonical: str) -> str:
        digits, exchange = canonical.split(".", 1)
        prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(exchange.upper(), exchange.lower())
        return f"{prefix}{digits}"

    @staticmethod
    def _period(timeframe: str) -> str:
        return str(timeframe).strip().lower().removesuffix("m")

    @staticmethod
    def _datetime_param(value_ms: Optional[int], fallback: datetime) -> str:
        if value_ms is None:
            value = fallback
        else:
            value = datetime.fromtimestamp(int(value_ms) / 1000, tz=timezone.utc).astimezone(SHANGHAI_TZ)
        return value.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _row_get(row: Any, *keys: str) -> Any:
        if isinstance(row, dict):
            for key in keys:
                if key in row:
                    return row[key]
        else:
            for key in keys:
                try:
                    return row[key]
                except Exception:
                    continue
        return None

    @staticmethod
    def _finite_float(value: Any) -> Optional[float]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _timestamp_ms(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            dt = datetime.fromisoformat(str(value).strip())
        except ValueError:
            return None
        observed = dt if dt.tzinfo else dt.replace(tzinfo=SHANGHAI_TZ)
        return int(observed.timestamp() * 1000)

    def _rows_from_frame(self, frame: Any) -> List[Any]:
        if frame is None:
            return []
        if hasattr(frame, "to_dict"):
            try:
                return frame.to_dict("records")
            except TypeError:
                return []
        return list(frame) if isinstance(frame, list) else []

    def _fetch_frame(
        self,
        canonical: str,
        timeframe: str,
        start_date: str,
        end_date: str,
    ) -> tuple[Any, str]:
        if self.fetcher is not None:
            return (
                self.fetcher(
                    symbol=self._akshare_symbol(canonical),
                    start_date=start_date,
                    end_date=end_date,
                    period=self._period(timeframe),
                    adjust="",
                ),
                self.PRIMARY_SOURCE,
            )

        worker = r"""
import json
import sys

import akshare as ak

symbol, sina_symbol, period, start_date, end_date = sys.argv[1:6]
source = "akshare.stock_zh_a_hist_min_em"
try:
    frame = ak.stock_zh_a_hist_min_em(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        period=period,
        adjust="",
    )
except Exception:
    source = "akshare.stock_zh_a_minute"
    frame = ak.stock_zh_a_minute(symbol=sina_symbol, period=period, adjust="")

print(json.dumps(
    {"source": source, "records": frame.to_dict("records")},
    ensure_ascii=False,
    default=str,
))
"""
        env = os.environ.copy()
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env.pop(key, None)
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                worker,
                self._akshare_symbol(canonical),
                self._sina_symbol(canonical),
                self._period(timeframe),
                start_date,
                end_date,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(3, int(settings.AKSHARE_TIMEOUT)),
            env=env,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "subprocess failed").splitlines()[-1]
            raise RuntimeError(message[:240])
        output = json.loads(completed.stdout)
        return output.get("records", []), str(output.get("source") or self.PRIMARY_SOURCE)

    def fetch(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> Dict[str, Any]:
        normalized_timeframe = str(timeframe or "").strip().lower()
        canonical = self.canonical_symbol(symbol)
        bounded = max(1, min(int(limit), 1000))
        if normalized_timeframe not in self.SUPPORTED_TIMEFRAMES:
            return {
                "exchange": exchange,
                "symbol": canonical,
                "timeframe": normalized_timeframe,
                "items": [],
                "data_status": "unsupported",
                "unavailable_reason": "AKShare intraday supports only 1m/5m/15m/30m/60m",
                "provider_source": self.PRIMARY_SOURCE,
                "external_fetch": False,
            }

        cache_key = (canonical, normalized_timeframe, bounded, start, end)
        now = monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and cached.expires_at > now:
                payload = dict(cached.payload)
                payload["cache_hit"] = True
                return payload

        payload = self._fetch_uncached(exchange, canonical, normalized_timeframe, bounded, start, end)
        ttl = self.ttl_seconds if payload.get("items") else self.error_ttl_seconds
        with self._lock:
            self._cache[cache_key] = _CacheEntry(expires_at=now + ttl, payload=dict(payload))
        return payload

    def _fetch_uncached(
        self,
        exchange: str,
        canonical: str,
        timeframe: str,
        limit: int,
        start: Optional[int],
        end: Optional[int],
    ) -> Dict[str, Any]:
        now_sh = datetime.now(SHANGHAI_TZ)
        start_date = self._datetime_param(start, now_sh - timedelta(days=7))
        end_date = self._datetime_param(end, now_sh + timedelta(days=1))
        try:
            frame, used_source = self._fetch_frame(canonical, timeframe, start_date, end_date)
        except Exception as exc:
            return {
                "exchange": exchange,
                "symbol": canonical,
                "timeframe": timeframe,
                "items": [],
                "data_status": "provider_error",
                "unavailable_reason": f"AKShare intraday fetch failed: {type(exc).__name__}",
                "provider_source": self.SINA_SOURCE if self.fetcher is None else self.PRIMARY_SOURCE,
                "external_fetch": True,
                "cache_hit": False,
            }

        items: List[Dict[str, Any]] = []
        for row in self._rows_from_frame(frame):
            observed_raw = self._row_get(row, "时间", "day", "datetime")
            ts = self._timestamp_ms(observed_raw)
            open_price = self._finite_float(self._row_get(row, "开盘", "open"))
            close_price = self._finite_float(self._row_get(row, "收盘", "close"))
            high_price = self._finite_float(self._row_get(row, "最高", "high"))
            low_price = self._finite_float(self._row_get(row, "最低", "low"))
            volume_lots = self._finite_float(self._row_get(row, "成交量", "volume"))
            amount = self._finite_float(self._row_get(row, "成交额", "amount"))
            if None in (ts, open_price, close_price, high_price, low_price):
                continue
            observed = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).astimezone(SHANGHAI_TZ)
            volume = float(volume_lots or 0)
            if used_source == self.PRIMARY_SOURCE:
                volume *= 100.0
            items.append({
                "timestamp": int(ts),
                "datetime": observed.isoformat(),
                "trade_date": observed.date().isoformat(),
                "open": float(open_price),
                "high": float(high_price),
                "low": float(low_price),
                "close": float(close_price),
                "volume": volume,
                "quote_volume": float(amount or 0),
                "amount": float(amount or 0),
                "source": used_source,
                "source_updated_at": observed.isoformat(),
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "volume_unit": "share",
                "raw_volume_lots": float(volume_lots or 0) if used_source == self.PRIMARY_SOURCE else None,
                "data_status": "ok",
            })

        items.sort(key=lambda item: item["timestamp"])
        if limit > 0:
            items = items[-limit:]
        return {
            "exchange": exchange,
            "symbol": canonical,
            "timeframe": timeframe,
            "items": items,
            "data_status": "ok" if items else "empty",
            "unavailable_reason": None if items else f"AKShare returned no {timeframe} intraday bars for {canonical}",
            "provider_source": used_source,
            "external_fetch": True,
            "cache_hit": False,
        }
