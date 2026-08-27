"""AKShare pull provider for the A-share symbol universe."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable, Dict, List, Optional

from app.core.config import settings


@dataclass
class _CacheEntry:
    expires_at: float
    items: List[Dict[str, Any]]


class AkshareSymbolProvider:
    """Fetch the current沪深京 A 股列表 without writing storage."""

    SOURCE = "akshare.stock_zh_a_spot_em"
    FALLBACK_SOURCE = "akshare.stock_info_a_code_name"

    def __init__(
        self,
        *,
        fetcher: Optional[Callable[[], Any]] = None,
        ttl_seconds: int = 300,
        error_ttl_seconds: int = 60,
    ) -> None:
        self.fetcher = fetcher
        self.ttl_seconds = max(30, int(ttl_seconds))
        self.error_ttl_seconds = max(10, int(error_ttl_seconds))
        self._cache: Dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _exchange_for_code(code: str) -> str:
        if code.startswith(("4", "8", "92")):
            return "BSE"
        if code.startswith("6"):
            return "SSE"
        return "SZSE"

    @staticmethod
    def _suffix_for_exchange(exchange: str) -> str:
        return {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}[exchange]

    @classmethod
    def _canonical_symbol(cls, code: Any) -> str:
        digits = str(code or "").strip()
        if digits.endswith(".0"):
            digits = digits[:-2]
        digits = digits.zfill(6)
        if len(digits) != 6 or not digits.isdigit():
            raise ValueError(f"AKShare returned invalid A-share code: {code!r}")
        exchange = cls._exchange_for_code(digits)
        return f"{digits}.{cls._suffix_for_exchange(exchange)}"

    @staticmethod
    def _rows_from_frame(frame: Any) -> List[Any]:
        if frame is None:
            return []
        if hasattr(frame, "to_dict"):
            return frame.to_dict("records")
        return list(frame) if isinstance(frame, list) else []

    def _fetch_rows(self) -> tuple[List[Any], str]:
        if self.fetcher is not None:
            return self._rows_from_frame(self.fetcher()), self.SOURCE

        worker = r"""
import json

import akshare as ak

source = "akshare.stock_zh_a_spot_em"
try:
    frame = ak.stock_zh_a_spot_em()
except Exception:
    source = "akshare.stock_info_a_code_name"
    frame = ak.stock_info_a_code_name()

print(json.dumps({"source": source, "records": frame.to_dict("records")}, ensure_ascii=False, default=str))
"""
        env = os.environ.copy()
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env.pop(key, None)
        completed = subprocess.run(
            [sys.executable, "-c", worker],
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
        return list(output.get("records") or []), str(output.get("source") or self.SOURCE)

    def _normalize(self, rows: List[Any], source: str) -> List[Dict[str, Any]]:
        instruments: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("名称") or row.get("name") or "").strip()
            if not name:
                continue
            try:
                symbol = self._canonical_symbol(row.get("代码") or row.get("code"))
            except ValueError:
                continue
            code, suffix = symbol.split(".", 1)
            exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[suffix]
            instruments[symbol] = {
                "symbol": symbol,
                "name": name,
                "display_name": f"{name} {symbol}",
                "exchange": exchange,
                "asset_class": "stock",
                "industry": None,
                "board": None,
                "list_status": "L",
                "source": source,
                "source_code": code,
            }
        return sorted(instruments.values(), key=lambda item: (item["exchange"], item["symbol"]))

    def fetch_instruments(self, asset_class: str = "stock") -> List[Dict[str, Any]]:
        normalized = str(asset_class or "stock").strip().lower()
        if normalized not in {"stock", "all"}:
            return []

        now = monotonic()
        cache_key = normalized
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and cached.expires_at > now:
                return [dict(item) for item in cached.items]

        try:
            rows, source = self._fetch_rows()
            items = self._normalize(rows, source)
        except Exception:
            items = []
            ttl = self.error_ttl_seconds
        else:
            ttl = self.ttl_seconds if items else self.error_ttl_seconds

        with self._lock:
            self._cache[cache_key] = _CacheEntry(expires_at=now + ttl, items=[dict(item) for item in items])
        return items
