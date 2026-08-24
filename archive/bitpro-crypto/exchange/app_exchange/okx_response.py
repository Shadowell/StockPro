"""Parse OKX v5 public API bodies shaped as { code, data: [ row, ... ] }."""
from __future__ import annotations

from typing import Any, Optional


def first_okx_data_row(response: Any) -> Optional[dict]:
    if isinstance(response, list) and response:
        row = response[0]
        return row if isinstance(row, dict) else None
    if not isinstance(response, dict):
        return None
    code = response.get("code")
    if code is not None and str(code) != "0":
        return None
    data = response.get("data")
    if isinstance(data, list) and data:
        row = data[0]
        return row if isinstance(row, dict) else None
    return None


def contract_size_from_market(market: dict) -> Optional[float]:
    """Linear swap: contracts * contract_size ≈ base currency amount (e.g. BTC)."""
    cs = market.get("contractSize")
    if cs is not None:
        try:
            v = float(cs)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    info = market.get("info") or {}
    for key in ("ctVal", "ctMult"):
        if key in info:
            try:
                v = float(info[key])
                if v > 0:
                    return v
            except (TypeError, ValueError):
                pass
    return None


def open_interest_base_units(oi_contracts: float, market: dict) -> Optional[float]:
    ct = contract_size_from_market(market)
    if not ct:
        return None
    return oi_contracts * ct
