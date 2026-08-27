"""Point-in-time A-share fundamentals backed by TuShare and sealed PostgreSQL evidence."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import math
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import settings
from app.domain.instruments.provider import TushareAshareProvider
from app.domain.market.repository import MarketRepository


CN_TZ = ZoneInfo("Asia/Shanghai")
DEFINITION_VERSION = "ashare-fundamental-pit.v1"
FACTOR_FIELDS = {
    "roe": ("fundamental.roe_ttm_pit", "ROE", "%", "profitability"),
    "roa": ("fundamental.roa_ttm_pit", "ROA", "%", "profitability"),
    "grossprofit_margin": ("fundamental.gross_margin_pit", "毛利率", "%", "profitability"),
    "netprofit_margin": ("fundamental.net_margin_pit", "净利率", "%", "profitability"),
    "or_yoy": ("fundamental.revenue_growth_yoy_pit", "营收同比", "%", "growth"),
    "netprofit_yoy": ("fundamental.net_profit_growth_yoy_pit", "净利润同比", "%", "growth"),
    "ocf_to_or": ("fundamental.ocf_quality_pit", "经营现金流/营收", "ratio", "quality"),
    "debt_to_assets": ("fundamental.debt_asset_ratio_pit", "资产负债率", "%", "leverage"),
}
FACTOR_LABELS = {value[0]: {"label": value[1], "unit": value[2], "category": value[3]} for value in FACTOR_FIELDS.values()}
FACTOR_LABELS.update({
    "shareholder.holder_count": {"label": "股东户数", "unit": "户", "category": "shareholder"},
    "dividend.cash_per_share": {"label": "每股现金分红", "unit": "CNY/股", "category": "dividend"},
})


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _day(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _available_at(ann_date: date) -> datetime:
    return datetime.combine(ann_date, time(18, 0), tzinfo=CN_TZ)


class FundamentalService:
    def __init__(self, database_url: str | None = None, provider_factory=None) -> None:
        self.database_url = database_url or settings.DATABASE_URL
        self.provider_factory = provider_factory or TushareAshareProvider

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def build_facts(
        *,
        symbol: str,
        indicators: list[dict[str, Any]],
        holders: list[dict[str, Any]],
        dividends: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        for row in indicators:
            report_period = _day(row.get("end_date"))
            ann_date = _day(row.get("ann_date"))
            if not report_period or not ann_date:
                continue
            for field, (factor_code, _label, _unit, _category) in FACTOR_FIELDS.items():
                value = _number(row.get(field))
                if value is None:
                    continue
                facts.append({
                    "symbol": symbol, "factor_code": factor_code,
                    "report_period": report_period, "ann_date": ann_date,
                    "announcement_available_at": _available_at(ann_date), "value": value,
                    "source_lineage": {"provider": "tushare.fina_indicator", "field": field},
                })
        for row in holders:
            report_period = _day(row.get("end_date")); ann_date = _day(row.get("ann_date")); value = _number(row.get("holder_num"))
            if report_period and ann_date and value is not None:
                facts.append({
                    "symbol": symbol, "factor_code": "shareholder.holder_count",
                    "report_period": report_period, "ann_date": ann_date,
                    "announcement_available_at": _available_at(ann_date), "value": value,
                    "source_lineage": {"provider": "tushare.stk_holdernumber", "field": "holder_num"},
                })
        for row in dividends:
            report_period = _day(row.get("end_date")); ann_date = _day(row.get("ann_date")); value = _number(row.get("cash_div_tax"))
            if report_period and ann_date and value is not None:
                facts.append({
                    "symbol": symbol, "factor_code": "dividend.cash_per_share",
                    "report_period": report_period, "ann_date": ann_date,
                    "announcement_available_at": _available_at(ann_date), "value": value,
                    "source_lineage": {"provider": "tushare.dividend", "field": "cash_div_tax", "div_proc": row.get("div_proc")},
                })
        return sorted(facts, key=lambda item: (item["factor_code"], item["report_period"], item["announcement_available_at"]))

    def sync(self, symbol: str, *, years: int = 3) -> dict[str, Any]:
        provider = self.provider_factory()
        start_date = (datetime.now(CN_TZ).date() - timedelta(days=max(1, min(years, 10)) * 366)).strftime("%Y%m%d")
        indicators = provider.fetch_financial_indicators(symbol, start_date)
        holders = provider.fetch_holder_counts(symbol, start_date)
        dividends = provider.fetch_dividends(symbol)
        facts = self.build_facts(symbol=symbol, indicators=indicators, holders=holders, dividends=dividends)
        values = [(
            item["symbol"], item["factor_code"], item["report_period"], item["ann_date"], item["announcement_available_at"],
            1, item["value"], Jsonb({}), Jsonb(item["source_lineage"]), DEFINITION_VERSION,
        ) for item in facts]
        with self._connect() as connection, connection.cursor() as cursor:
            if values:
                cursor.executemany(
                    """INSERT INTO fundamental_factor_facts(
                           symbol,factor_code,report_period,ann_date,announcement_available_at,
                           revision,value,quality_flags,source_lineage,definition_version
                       ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT(symbol,factor_code,report_period,announcement_available_at,revision) DO NOTHING""",
                    values,
                )
            connection.commit()
        return {
            "symbol": symbol,
            "status": "success",
            "fact_count": len(facts),
            "indicator_rows": len(indicators),
            "holder_rows": len(holders),
            "dividend_rows": len(dividends),
            "provider_calls": 3,
            "orders_created": 0,
            "paper_mutated": False,
        }

    def _valuation(self, symbol: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        repo = MarketRepository(self.database_url)
        with repo._connect() as connection, connection.cursor() as cursor:
            snapshot = repo._latest_dataset_snapshot(cursor, "daily_basic")
            rows = repo._dataset_snapshot_payloads(cursor, snapshot["id"], "daily_basic") if snapshot else []
        row = next((item for item in rows if str(item.get("symbol")) == symbol), None)
        return row, snapshot

    def summary(self, symbol: str, *, as_of: datetime | None = None) -> dict[str, Any]:
        cutoff = as_of or datetime.now(timezone.utc)
        valuation, snapshot = self._valuation(symbol)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT name,board,industry FROM instrument_definitions WHERE market='CN' AND symbol=%s", (symbol,))
            instrument = cursor.fetchone()
            cursor.execute(
                """SELECT symbol,factor_code,report_period,ann_date,announcement_available_at,
                          revision,value,quality_flags,source_lineage,definition_version
                   FROM fundamental_factor_facts
                   WHERE symbol=%s AND announcement_available_at<=%s
                   ORDER BY factor_code,report_period DESC,announcement_available_at DESC,revision DESC""",
                (symbol, cutoff),
            )
            rows = cursor.fetchall()
        items = []
        for row in rows:
            meta = FACTOR_LABELS.get(row["factor_code"], {"label": row["factor_code"], "unit": "", "category": "other"})
            items.append({
                "factor_code": row["factor_code"], **meta,
                "report_period": str(row["report_period"]),
                "ann_date": str(row["ann_date"]) if row["ann_date"] else None,
                "available_at": row["announcement_available_at"].isoformat(),
                "value": float(row["value"]) if row["value"] is not None else None,
                "revision": int(row["revision"]),
                "source": dict(row["source_lineage"] or {}).get("provider"),
                "source_lineage": dict(row["source_lineage"] or {}),
                "definition_version": row["definition_version"],
            })
        latest: dict[str, dict[str, Any]] = {}
        for item in items:
            latest.setdefault(item["factor_code"], item)
        valuation_payload = None
        if valuation:
            valuation_payload = {
                "trade_date": valuation.get("trade_date"),
                "close": valuation.get("close"),
                "pe": valuation.get("pe"), "pe_ttm": valuation.get("pe_ttm"), "pb": valuation.get("pb"),
                "ps": valuation.get("ps"), "ps_ttm": valuation.get("ps_ttm"),
                "dividend_yield": valuation.get("dv_ratio"), "dividend_yield_ttm": valuation.get("dv_ttm"),
                "total_market_cap_cny": float(valuation.get("total_mv") or 0) * 10_000 if valuation.get("total_mv") is not None else None,
                "float_market_cap_cny": float(valuation.get("circ_mv") or 0) * 10_000 if valuation.get("circ_mv") is not None else None,
                "turnover_rate": valuation.get("turnover_rate"), "volume_ratio": valuation.get("volume_ratio"),
                "source": valuation.get("source") or "tushare.daily_basic",
                "source_snapshot_id": snapshot.get("id") if snapshot else None,
                "available_at": snapshot.get("available_at") if snapshot else None,
                "knowledge_cutoff_at": snapshot.get("knowledge_cutoff_at") if snapshot else None,
            }
        status = "ready" if valuation_payload and items else "partial" if valuation_payload or items else "empty"
        missing = []
        if not valuation_payload: missing.append("缺少 sealed daily_basic 估值快照")
        if not items: missing.append("尚未同步公告时点财务/股东/分红事实")
        return {
            "status": status,
            "symbol": symbol,
            "name": str((instrument or {}).get("name") or (valuation or {}).get("name") or symbol),
            "board": (instrument or {}).get("board"), "industry": (instrument or {}).get("industry"),
            "as_of": cutoff.isoformat(),
            "valuation": valuation_payload,
            "latest_factors": latest,
            "items": items,
            "missing_inputs": missing,
            "provider_calls": 0,
            "writes_performed": False,
            "orders_created": 0,
            "paper_mutated": False,
        }


fundamental_service = FundamentalService()
