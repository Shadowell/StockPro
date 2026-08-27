from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.core.config import settings

CN_TZ = ZoneInfo("Asia/Shanghai")

SUPPORTED_BAR_MINUTES = {
    1: "1MIN",
    5: "5MIN",
    15: "15MIN",
    30: "30MIN",
    60: "60MIN",
}

DEFAULT_SYMBOLS = ["600519.SH", "000001.SZ", "300750.SZ", "510300.SH"]
CACHE_TTL_SECONDS = 6 * 60


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        return frame.to_dict(orient="records")
    if isinstance(frame, list):
        return [row for row in frame if isinstance(row, dict)]
    return []


def _float(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_symbol(symbol: str | None) -> str:
    value = (symbol or "").strip().upper()
    if not value:
        return DEFAULT_SYMBOLS[0]
    if "_" in value and "." not in value:
        market, code = value.split("_", 1)
        if market in {"SH", "SZ", "BJ"} and code:
            return f"{code}.{market}"
    return value


def _parse_bar_time(value: Any, now: datetime) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    candidates = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y%m%d %H:%M:%S",
        "%Y%m%d %H:%M",
        "%H:%M:%S",
        "%H:%M",
    ]
    for fmt in candidates:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if "%Y" not in fmt:
            parsed = parsed.replace(year=now.year, month=now.month, day=now.day)
        return parsed.replace(tzinfo=CN_TZ)
    return None


class TushareRealtimeMinuteProvider:
    def __init__(self, token: str | None = None, client: Any | None = None) -> None:
        self.token = token if token is not None else settings.TUSHARE_TOKEN
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.token)

    @property
    def client(self) -> Any:
        if self._client is None:
            if not self.token:
                raise RuntimeError("Tushare token not configured")
            import tushare as ts

            self._client = ts.pro_api(self.token)
        return self._client

    def rt_min(self, ts_code: str, freq: str) -> list[dict[str, Any]]:
        return _records(self.client.rt_min(ts_code=ts_code, freq=freq))


class RealtimeMinuteOrderflowService:
    def __init__(
        self,
        provider_factory: Callable[[], TushareRealtimeMinuteProvider] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider_factory = provider_factory or TushareRealtimeMinuteProvider
        self._clock = clock or (lambda: datetime.now(CN_TZ))
        self._cache: dict[tuple[str, str], tuple[datetime, list[dict[str, Any]]]] = {}
        self._next_provider_call_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_error: str | None = None

    def _freshness_meta(self, now: datetime, cached_at: datetime | None = None) -> dict[str, Any]:
        return {
            "last_success_at": self._last_success_at.isoformat() if self._last_success_at else None,
            "cache_age_seconds": int((now - cached_at).total_seconds()) if cached_at else None,
            "next_retry_at": self._next_provider_call_at.isoformat() if self._next_provider_call_at else None,
        }

    def stream_status(self) -> dict[str, Any]:
        provider = self._provider_factory()
        now = self._clock()
        latest_cached_at = max((entry[0] for entry in self._cache.values()), default=None)
        if not provider.configured:
            return {
                **self._base_status("unavailable", "requires_configuration"),
                **self._freshness_meta(now, latest_cached_at),
                "enabled": False,
                "connected": False,
                "last_error": "Tushare token not configured",
            }

        if self._last_error:
            return {
                **self._base_status("stale" if latest_cached_at else "unavailable", "provider_backoff"),
                **self._freshness_meta(now, latest_cached_at),
                "enabled": True,
                "connected": False,
                "last_error": self._last_error,
            }

        return {
            **self._base_status("realtime_minute_fallback", "available"),
            **self._freshness_meta(now, latest_cached_at),
            "enabled": True,
            "connected": True,
            "last_error": None,
        }

    def symbols(self) -> dict[str, Any]:
        status = self.stream_status()
        return {"items": DEFAULT_SYMBOLS, "count": len(DEFAULT_SYMBOLS), **status}

    def large_trades(self, symbol: str) -> dict[str, Any]:
        status = self.stream_status()
        return {
            "items": [],
            "count": 0,
            "symbol": normalize_symbol(symbol),
            "unavailable_reason": "Realtime minute bars do not provide tick-level large trades",
            "data_status": "tick_unavailable",
            "permission_state": "requires_tick_provider",
            "provider_source": "A-share Level-2/tick vendor",
            "frequency": "realtime_ticks",
            "tables": ["trade_ticks", "orderflow_large_trades"],
            "setup_path": "/settings",
            "last_error": "A-share tick Provider not configured",
            "minute_fallback": {
                "enabled": status["enabled"],
                "connected": status["connected"],
                "provider_source": status["provider_source"],
                "data_status": status["data_status"],
            },
        }

    def bars(self, symbol: str, bar_minutes: int, hours: int) -> dict[str, Any]:
        normalized_symbol = normalize_symbol(symbol)
        freq = SUPPORTED_BAR_MINUTES.get(bar_minutes)
        if freq is None:
            return {
                **self._base_status("unavailable", "unsupported_frequency"),
                "items": [],
                "count": 0,
                "symbol": normalized_symbol,
                "bar_minutes": bar_minutes,
                "unavailable_reason": "Supported frequencies are 1, 5, 15, 30, and 60 minutes",
                "last_error": "Unsupported realtime minute frequency",
            }

        provider = self._provider_factory()
        if not provider.configured:
            return {
                **self._base_status("unavailable", "requires_configuration"),
                "items": [],
                "count": 0,
                "symbol": normalized_symbol,
                "bar_minutes": bar_minutes,
                "unavailable_reason": "Tushare token not configured",
                "last_error": "Tushare token not configured",
            }

        now = self._clock()
        cached_at, cached_rows = self._cache.get((normalized_symbol, freq), (None, []))
        if cached_at is not None:
            cache_age = (now - cached_at).total_seconds()
            if cache_age < CACHE_TTL_SECONDS:
                items = self._bars_from_rows(cached_rows, normalized_symbol, now, hours)
                return {
                    **self._base_status(
                        "realtime_minute_fallback" if items else "empty",
                        "available",
                    ),
                    "items": items,
                    "count": len(items),
                    "symbol": normalized_symbol,
                    "bar_minutes": bar_minutes,
                    "as_of": int(now.timestamp() * 1000),
                    "cache_age_seconds": int(cache_age),
                    "last_success_at": self._last_success_at.isoformat() if self._last_success_at else cached_at.isoformat(),
                    "next_retry_at": self._next_provider_call_at.isoformat() if self._next_provider_call_at else None,
                    "last_error": None,
                    "unavailable_reason": None if items else "No cached realtime minute bars",
                }

        if self._next_provider_call_at is not None and now < self._next_provider_call_at:
            wait_seconds = int((self._next_provider_call_at - now).total_seconds())
            stale_items = self._bars_from_rows(cached_rows, normalized_symbol, now, hours) if cached_at else []
            return {
                **self._base_status("stale" if stale_items else "unavailable", "provider_backoff"),
                **self._freshness_meta(now, cached_at),
                "items": stale_items,
                "count": len(stale_items),
                "symbol": normalized_symbol,
                "bar_minutes": bar_minutes,
                "as_of": int(now.timestamp() * 1000),
                "unavailable_reason": "Using the last successful minute snapshot during Tushare rate-limit backoff" if stale_items else "Tushare realtime minute request is in rate-limit backoff",
                "last_error": self._last_error
                or f"Waiting {wait_seconds}s before the next Tushare rt_min request",
            }

        try:
            rows = provider.rt_min(ts_code=normalized_symbol, freq=freq)
        except Exception as exc:
            self._last_error = str(exc)
            self._next_provider_call_at = now + timedelta(seconds=CACHE_TTL_SECONDS)
            stale_items = self._bars_from_rows(cached_rows, normalized_symbol, now, hours) if cached_at else []
            return {
                **self._base_status("stale" if stale_items else "unavailable", "provider_error"),
                **self._freshness_meta(now, cached_at),
                "items": stale_items,
                "count": len(stale_items),
                "symbol": normalized_symbol,
                "bar_minutes": bar_minutes,
                "unavailable_reason": "Using the last successful minute snapshot after a Tushare request failure" if stale_items else "Tushare realtime minute request failed",
                "last_error": str(exc),
            }

        self._cache[(normalized_symbol, freq)] = (now, rows)
        self._next_provider_call_at = now + timedelta(seconds=CACHE_TTL_SECONDS)
        self._last_success_at = now
        self._last_error = None
        items = self._bars_from_rows(rows, normalized_symbol, now, hours)
        data_status = "realtime_minute_fallback" if items else "empty"
        return {
            **self._base_status(data_status, "available"),
            "items": items,
            "count": len(items),
            "symbol": normalized_symbol,
            "bar_minutes": bar_minutes,
            "as_of": int(now.timestamp() * 1000),
            **self._freshness_meta(now, now),
            "last_error": None,
            "unavailable_reason": None if items else "No realtime minute bars returned by Tushare",
        }

    def _bars_from_rows(
        self,
        rows: list[dict[str, Any]],
        symbol: str,
        now: datetime,
        hours: int,
    ) -> list[dict[str, Any]]:
        cutoff = now - timedelta(hours=max(1, min(hours, 24)))
        parsed: list[dict[str, Any]] = []
        for row in rows:
            bar_time = _parse_bar_time(row.get("time"), now)
            if bar_time is None or bar_time < cutoff:
                continue
            close_px = _float(row.get("close"))
            amount = _float(row.get("amount"), 0.0) or 0.0
            volume = _float(row.get("vol"), 0.0) or 0.0
            vwap = amount / volume if amount > 0 and volume > 0 else close_px
            parsed.append(
                {
                    "bar_ts": int(bar_time.timestamp() * 1000),
                    "symbol": row.get("ts_code") or symbol,
                    "open_px": _float(row.get("open")),
                    "close_px": close_px,
                    "low_px": _float(row.get("low"), 0.0) or 0.0,
                    "high_px": _float(row.get("high"), 0.0) or 0.0,
                    "volume": volume,
                    "amount": amount,
                    "vwap": vwap,
                    "buy_notional": 0.0,
                    "sell_notional": 0.0,
                    "delta": 0.0,
                    "cum_delta": 0.0,
                    "trade_count": 1,
                    "source": "tushare.rt_min",
                    "data_status": "realtime_minute_fallback",
                }
            )
        return sorted(parsed, key=lambda item: item["bar_ts"])

    def _base_status(self, data_status: str, permission_state: str) -> dict[str, Any]:
        return {
            "data_status": data_status,
            "provider_source": "tushare.rt_min",
            "permission_state": permission_state,
            "frequency": "1MIN/5MIN/15MIN/30MIN/60MIN minute bars, not tick/Level-2",
            "tables": ["minute_bars", "orderflow_bars"],
            "setup_path": "/settings",
        }
