"""Tushare northbound + stock moneyflow for the A-share capital-flow page."""
from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.core.config import settings

CN_TZ = ZoneInfo("Asia/Shanghai")
CACHE_TTL_SECONDS = 5 * 60


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _wan_to_cny(value: Any) -> float | None:
    amount = _number(value)
    return None if amount is None else amount * 10_000


def _ymd(value: Any) -> str | None:
    raw = str(value or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    if len(raw) >= 10 and raw[4] == "-":
        return raw[:10]
    return None


def normalize_hsgt_row(row: dict[str, Any]) -> dict[str, Any] | None:
    trade_date = _ymd(row.get("trade_date") or row.get("date"))
    north = _wan_to_cny(row.get("north_money"))
    if not trade_date or north is None:
        return None
    return {
        "trade_date": trade_date,
        "north_money_cny": north,
        "south_money_cny": _wan_to_cny(row.get("south_money")),
        "hgt_cny": _wan_to_cny(row.get("hgt")),
        "sgt_cny": _wan_to_cny(row.get("sgt")),
        "ggt_ss_cny": _wan_to_cny(row.get("ggt_ss")),
        "ggt_sz_cny": _wan_to_cny(row.get("ggt_sz")),
        "source": "tushare.moneyflow_hsgt",
    }


def normalize_moneyflow_row(row: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    trade_date = _ymd(row.get("trade_date"))
    net_amount = _wan_to_cny(row.get("net_mf_amount"))
    if not trade_date:
        return None
    buy_large = _wan_to_cny(row.get("buy_lg_amount"))
    buy_elg = _wan_to_cny(row.get("buy_elg_amount"))
    sell_large = _wan_to_cny(row.get("sell_lg_amount"))
    sell_elg = _wan_to_cny(row.get("sell_elg_amount"))
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "net_amount_cny": net_amount,
        "main_in_cny": None if buy_large is None or buy_elg is None else buy_large + buy_elg,
        "main_out_cny": None if sell_large is None or sell_elg is None else sell_large + sell_elg,
        "source": "tushare.moneyflow",
    }


class CapitalFlowService:
    def __init__(self, client_factory: Callable[[], Any] | None = None) -> None:
        self._client_factory = client_factory
        self._client: Any | None = None
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def _pro(self) -> Any:
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                token = str(settings.TUSHARE_TOKEN or "").strip()
                if not token:
                    raise RuntimeError("TUSHARE_TOKEN 未配置")
                import tushare as ts
                self._client = ts.pro_api(token)
        return self._client

    def summary(self, symbol: str, *, days: int = 20) -> dict[str, Any]:
        key = f"{symbol}:{days}"
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        end = datetime.now(CN_TZ).date()
        start = end - timedelta(days=max(days * 2, 14))
        start_s, end_s = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        northbound: list[dict[str, Any]] = []
        stock_flow: list[dict[str, Any]] = []
        missing: list[str] = []
        try:
            client = self._pro()
        except Exception as exc:
            payload = {
                "status": "unavailable",
                "symbol": symbol,
                "northbound": [],
                "stock_flow": [],
                "latest": None,
                "missing_inputs": [str(exc)],
                "provider_source": "tushare.moneyflow_hsgt",
                "provider_calls": 0,
                "writes_performed": False,
            }
            return payload
        try:
            frame = client.moneyflow_hsgt(start_date=start_s, end_date=end_s)
            rows = frame.to_dict("records") if frame is not None and hasattr(frame, "to_dict") else []
            northbound = [item for item in (normalize_hsgt_row(row) for row in rows) if item]
            northbound.sort(key=lambda item: item["trade_date"], reverse=True)
        except Exception as exc:
            missing.append(f"北向资金读取失败：{exc}")
        try:
            frame = client.moneyflow(ts_code=symbol, start_date=start_s, end_date=end_s)
            rows = frame.to_dict("records") if frame is not None and hasattr(frame, "to_dict") else []
            stock_flow = [item for item in (normalize_moneyflow_row(row, symbol) for row in rows) if item]
            stock_flow.sort(key=lambda item: item["trade_date"], reverse=True)
        except Exception as exc:
            missing.append(f"个股资金流读取失败：{exc}")
        latest = northbound[0] if northbound else None
        status = "ready" if northbound or stock_flow else "empty"
        payload = {
            "status": status,
            "symbol": symbol,
            "northbound": northbound[:days],
            "stock_flow": stock_flow[:days],
            "latest": latest,
            "missing_inputs": missing,
            "provider_source": "tushare.moneyflow_hsgt + tushare.moneyflow",
            "provider_calls": 2,
            "writes_performed": False,
        }
        self._cache[key] = (now, payload)
        return payload


capital_flow_service = CapitalFlowService()
