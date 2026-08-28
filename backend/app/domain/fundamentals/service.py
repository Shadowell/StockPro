"""Point-in-time A-share fundamentals backed by TuShare and sealed PostgreSQL evidence."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import math
from typing import Any, Mapping
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


def symbol_aliases(symbol: str) -> list[str]:
    raw = str(symbol or "").strip().upper()
    aliases = {raw}
    if "." in raw:
        digits, exchange = raw.rsplit(".", 1)
        aliases.update({f"{exchange}_{digits}", f"{exchange}{digits}", digits})
    elif "_" in raw:
        exchange, digits = raw.split("_", 1)
        aliases.update({f"{digits}.{exchange}", f"{exchange}{digits}", digits})
    return [item for item in aliases if item]


def _market_cap_cny(value: Any, *, wan: bool = False) -> float | None:
    amount = _number(value)
    if amount is None:
        return None
    if wan or amount < 1e10:
        amount *= 10_000
    return amount


def build_valuation_payload(
    valuation: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not valuation:
        return None
    close = _number(valuation.get("close") or valuation.get("price"))
    pe = _number(valuation.get("pe"))
    pe_ttm = _number(valuation.get("pe_ttm") or valuation.get("pe_dynamic") or pe)
    pb = _number(valuation.get("pb"))
    ps = _number(valuation.get("ps"))
    ps_ttm = _number(valuation.get("ps_ttm") or ps)
    if all(item is None for item in (close, pe, pe_ttm, pb, ps_ttm, valuation.get("total_mv"), valuation.get("total_market_cap_cny"))):
        return None
    total_cap = _number(valuation.get("total_market_cap_cny"))
    if total_cap is None:
        total_cap = _market_cap_cny(valuation.get("total_mv"), wan=True)
    float_cap = _number(valuation.get("float_market_cap_cny") or valuation.get("circ_market_cap_cny"))
    if float_cap is None:
        float_cap = _market_cap_cny(valuation.get("circ_mv"), wan=True)
    trade_date = valuation.get("trade_date") or (snapshot or {}).get("end_date")
    source = valuation.get("source") or (
        "tushare.daily_valuation" if snapshot else "all_stocks_realtime"
    )
    return {
        "trade_date": str(trade_date)[:10] if trade_date else None,
        "close": close,
        "pe": pe,
        "pe_ttm": pe_ttm,
        "pb": pb,
        "ps": ps,
        "ps_ttm": ps_ttm,
        "dividend_yield": _number(valuation.get("dv_ratio") or valuation.get("dividend_yield")),
        "dividend_yield_ttm": _number(valuation.get("dv_ttm") or valuation.get("dividend_yield_ttm")),
        "total_market_cap_cny": total_cap,
        "float_market_cap_cny": float_cap,
        "turnover_rate": _number(valuation.get("turnover_rate")),
        "volume_ratio": _number(valuation.get("volume_ratio")),
        "source": source,
        "source_snapshot_id": (snapshot or {}).get("id"),
        "available_at": (snapshot or {}).get("available_at"),
        "knowledge_cutoff_at": (snapshot or {}).get("knowledge_cutoff_at"),
    }


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
        aliases = symbol_aliases(symbol)
        repo = MarketRepository(self.database_url)
        with repo._connect() as connection, connection.cursor() as cursor:
            if repo._table_exists(cursor, "dataset_partition_records"):
                cursor.execute(
                    """
                    WITH latest AS (
                      SELECT i.partition_id, s.id AS snapshot_id, s.knowledge_cutoff_at, p.available_at, p.end_date
                      FROM dataset_snapshots s
                      JOIN dataset_snapshot_items i ON i.snapshot_id=s.id
                      JOIN dataset_partitions p ON p.id=i.partition_id
                      WHERE s.status='sealed'
                        AND i.dataset_code IN ('daily_valuation','daily_basic')
                      ORDER BY p.end_date DESC NULLS LAST, s.id DESC
                      LIMIT 1
                    )
                    SELECT r.payload, l.snapshot_id, l.knowledge_cutoff_at, l.available_at, l.end_date
                    FROM latest l
                    JOIN dataset_partition_records r ON r.partition_id=l.partition_id
                    WHERE r.payload->>'ts_code' = ANY(%s)
                       OR r.payload->>'symbol' = ANY(%s)
                    LIMIT 1
                    """,
                    (aliases, aliases),
                )
                row = cursor.fetchone()
                if row:
                    payload = dict(row[0] or {})
                    snapshot = {
                        "id": int(row[1]),
                        "knowledge_cutoff_at": row[2].isoformat() if hasattr(row[2], "isoformat") else row[2],
                        "available_at": row[3].isoformat() if hasattr(row[3], "isoformat") else row[3],
                        "end_date": str(row[4])[:10] if row[4] is not None else None,
                    }
                    return payload, snapshot
            if repo._table_exists(cursor, "all_stocks_realtime"):
                cursor.execute(
                    """
                    SELECT code,name,price,pe_dynamic,pb,total_market_cap,float_market_cap,
                           turnover,volume_ratio,updated_at
                    FROM all_stocks_realtime
                    WHERE code = ANY(%s)
                    LIMIT 1
                    """,
                    (aliases,),
                )
                live = cursor.fetchone()
                if live:
                    updated = live[9]
                    return {
                        "symbol": live[0],
                        "name": live[1],
                        "close": live[2],
                        "pe": live[3],
                        "pe_ttm": live[3],
                        "pb": live[4],
                        "total_market_cap_cny": live[5],
                        "circ_market_cap_cny": live[6],
                        "turnover_rate": live[7],
                        "volume_ratio": live[8],
                        "source": "all_stocks_realtime",
                        "trade_date": updated.date().isoformat() if hasattr(updated, "date") else str(updated or "")[:10] or None,
                    }, None
        return None, None

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
        valuation_payload = build_valuation_payload(valuation, snapshot)
        status = "ready" if valuation_payload and items else "partial" if valuation_payload or items else "empty"
        missing = []
        if not valuation_payload: missing.append("缺少 daily_valuation 估值快照与实时估值")
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
