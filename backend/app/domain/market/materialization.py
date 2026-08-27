"""Pure builders for persisted A-share market research metrics."""
from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from app.domain.market.research_metrics import compute_symbol_abnormality


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _ordered_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: str(row.get("trade_date") or row.get("date") or ""))


def _industry_bars(
    daily_rows: list[dict[str, Any]],
    industry_by_symbol: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    changes: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in daily_rows:
        symbol = str(row.get("symbol") or "")
        industry = industry_by_symbol.get(symbol)
        trade_date = str(row.get("trade_date") or "")[:10]
        change = _number(row.get("change_percent"))
        if industry and trade_date and change is not None:
            changes[(industry, trade_date)].append(change)

    dates_by_industry: dict[str, list[str]] = defaultdict(list)
    for industry, trade_date in changes:
        dates_by_industry[industry].append(trade_date)

    result: dict[str, list[dict[str, Any]]] = {}
    for industry, observed_dates in dates_by_industry.items():
        level = 100.0
        bars = []
        for trade_date in sorted(set(observed_dates)):
            level *= 1.0 + mean(changes[(industry, trade_date)]) / 100.0
            bars.append({
                "trade_date": trade_date,
                "open": level,
                "high": level,
                "low": level,
                "close": level,
                "amount": 1.0,
            })
        result[industry] = bars
    return result


def build_symbol_abnormal_metrics(
    *,
    daily_rows: list[dict[str, Any]],
    benchmark_rows: list[dict[str, Any]],
    instruments: list[dict[str, Any]],
    trade_date: str,
) -> list[dict[str, Any]]:
    """Build latest-day rows ready for symbol_abnormal_metrics upsert."""
    instrument_by_symbol = {str(row.get("symbol") or ""): row for row in instruments}
    industry_by_symbol = {
        symbol: str(row.get("industry") or "").strip()
        for symbol, row in instrument_by_symbol.items()
        if str(row.get("industry") or "").strip()
    }
    bars_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in daily_rows:
        symbol = str(row.get("symbol") or "")
        if symbol:
            bars_by_symbol[symbol].append(dict(row))
    benchmark = _ordered_rows([
        dict(row)
        for row in benchmark_rows
        if str(row.get("symbol") or row.get("ts_code") or "").upper() == "000300.SH"
    ])
    sector_bars = _industry_bars(daily_rows, industry_by_symbol)

    metrics = []
    for symbol, rows in sorted(bars_by_symbol.items()):
        instrument = instrument_by_symbol.get(symbol, {})
        industry = industry_by_symbol.get(symbol)
        payload = compute_symbol_abnormality(
            _ordered_rows(rows),
            symbol=symbol,
            name=str(instrument.get("name") or "") or None,
            board=str(instrument.get("board") or "") or None,
            trade_date=trade_date,
            benchmark_bars=benchmark or None,
            sector_bars=sector_bars.get(industry or "") or None,
        )
        payload.update({
            "benchmark_code": "000300.SH",
            "sector_code": industry,
            "source_snapshot_id": None,
            "source_lineage": {
                "stock_source": "tushare.daily",
                "benchmark_source": "tushare.index_daily",
                "sector_source": "industry_member_equal_weight",
            },
        })
        metrics.append(payload)
    return metrics
