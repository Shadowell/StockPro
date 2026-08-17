"""Source-aware, PostgreSQL-only market research context for Sprint 05."""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence

import psycopg2.extras

_THREAD_STATE = threading.local()


SENTIMENT_KPIS = (
    "rise_count", "fall_count", "flat_count", "limit_up_count", "limit_down_count",
    "broken_board_count", "seal_rate", "highest_board", "red_market_ratio", "rise_fall_ratio",
    "new_high_count", "new_low_count",
)

_CONTEXT_CACHE: Dict[str, Any] = {}
_CONTEXT_TTL_SECONDS = 30.0


def reset_research_context_cache() -> None:
    _CONTEXT_CACHE.clear()


class MarketResearchService:
    temperature_version = "market-temperature.v1"
    temperature_weights = {
        "breadth": 0.25,
        "limit_ecology": 0.25,
        "momentum_continuity": 0.20,
        "loss_risk": 0.20,
        "liquidity_participation": 0.10,
    }

    def __init__(self, database):
        self.database = database

    def list_snapshots(
        self,
        *,
        trade_date: Optional[str] = None,
        market_scope: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if trade_date:
            clauses.append("trade_date=%s")
            params.append(str(trade_date)[:10])
        if market_scope:
            clauses.append("market_scope=%s")
            params.append(str(market_scope))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 365)))
        rows = self._rows(
            f"""
            SELECT id,trade_date,snapshot_type,market_scope,captured_at,available_at,source_map,status,content_hash,
                   CASE WHEN NOW()-captured_at > INTERVAL '36 hours' THEN 'stale' ELSE 'fresh' END AS freshness
            FROM market_evidence_snapshots {where}
            ORDER BY trade_date DESC,captured_at DESC,id DESC LIMIT %s
            """,
            params,
        )
        for row in rows:
            row["session_label"] = "盘后" if row["snapshot_type"] == "post_close" else "盘中"
        return rows

    def sentiment(self, snapshot_id: int) -> Dict[str, Any]:
        snapshot = self._snapshot(snapshot_id)
        stored = {
            item["metric_code"]: item
            for item in self._rows(
                "SELECT metric_code,value,unit,definition_version,source_label FROM market_evidence_metrics WHERE snapshot_id=%s",
                (int(snapshot_id),),
            )
        }
        definitions = {
            "rise_count": ("上涨家数", "上涨证券数量"),
            "fall_count": ("下跌家数", "下跌证券数量"),
            "flat_count": ("平盘家数", "平盘证券数量"),
            "limit_up_count": ("涨停数", "涨停池去重证券数"),
            "limit_down_count": ("跌停数", "跌停池去重证券数"),
            "broken_board_count": ("炸板数", "盘中触板但收盘未封板证券数"),
            "seal_rate": ("封板率", "涨停数/(涨停数+炸板数)"),
            "highest_board": ("最高板", "涨停池最大连续涨停天数"),
            "red_market_ratio": ("红盘率", "上涨家数/有效证券数"),
            "rise_fall_ratio": ("涨跌比", "上涨家数/下跌家数"),
            "new_high_count": ("新高数", "一年新高证券数"),
            "new_low_count": ("新低数", "一年新低证券数"),
        }
        metrics = []
        for code in SENTIMENT_KPIS:
            fact = stored.get(code) or {}
            label, definition = definitions[code]
            value = fact.get("value")
            metrics.append({
                "metric_code": code,
                "label": label,
                "value": value,
                "unit": fact.get("unit"),
                "definition": definition,
                "numerator": self._numerator(code, stored),
                "denominator": self._denominator(code, stored),
                "source_label": fact.get("source_label"),
                "publication_state": "published" if value is not None else "unavailable",
                "missing_reason": None if value is not None else "当前封存快照未包含该全市场事实",
            })
        components = self._temperature_components(stored)
        missing = [code for code, item in components.items() if item["value"] is None]
        temperature = {
            "metric_code": "market_temperature",
            "value": None if missing else sum(float(item["value"]) * self.temperature_weights[code] for code, item in components.items()),
            "formula_version": self.temperature_version,
            "normalisation": "各分量线性规范到 0-100；缺少任一必需分量则不发布",
            "weights": self.temperature_weights,
            "components": components,
            "missing_components": missing,
            "publication_state": "unavailable" if missing else "published",
        }
        return {"snapshot": snapshot, "metrics": metrics, "market_temperature": temperature}

    def limit_ecosystem(self, snapshot_id: int) -> Dict[str, Any]:
        snapshot = self._snapshot(snapshot_id)
        members = self._rows(
            """
            SELECT pool_kind,symbol,name,limit_times,first_limit_at,last_limit_at,open_times,seal_amount,
                   turnover,industry,source_label
            FROM limit_pool_members WHERE snapshot_id=%s
            ORDER BY pool_kind,limit_times DESC NULLS LAST,symbol
            """,
            (int(snapshot_id),),
        )
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in members:
            grouped[str(item["pool_kind"])].append(item)
        up = grouped.get("up", [])
        ladder = []
        for label, lower, upper in (("1板", 1, 1), ("2板", 2, 2), ("3板", 3, 3), ("4板", 4, 4), ("5+板", 5, 999)):
            rows = [item for item in up if lower <= int(item.get("limit_times") or 0) <= upper]
            ladder.append({"level": label, "count": len(rows), "members": rows})
        previous = self._row(
            """
            SELECT id,trade_date FROM market_evidence_snapshots
            WHERE market_scope=%s AND snapshot_type=%s AND trade_date<%s
            ORDER BY trade_date DESC,captured_at DESC LIMIT 1
            """,
            (snapshot["market_scope"], snapshot["snapshot_type"], snapshot["trade_date"]),
        )
        cohorts = self._cohorts(int(previous["id"]), up) if previous else []
        return {
            "snapshot": snapshot,
            "source_label": self._single_source(members),
            "ladder_method": "limit_times derived buckets",
            "ladder": ladder,
            "highest_board": max((int(item.get("limit_times") or 0) for item in up), default=0),
            "promotion_elimination": cohorts,
            "comparison_snapshot": previous,
            "pools": dict(grouped),
        }

    def sector_evidence(self, snapshot_id: int, classification: str = "tushare_limit_industry") -> Dict[str, Any]:
        snapshot = self._snapshot(snapshot_id)
        stored = self._rows(
            """
            SELECT classification_system,sector_code,sector_name,return_1d,breadth,limit_up_count,
                   leader_symbol,net_flow,source_label,raw_payload
            FROM sector_evidence_rows WHERE snapshot_id=%s AND classification_system=%s
            ORDER BY limit_up_count DESC NULLS LAST,sector_name
            """,
            (int(snapshot_id), classification),
        )
        if stored:
            return {"snapshot": snapshot, "classification_system": classification, "items": stored}
        members = self._rows(
            """
            SELECT symbol,name,limit_times,industry,seal_amount,source_label
            FROM limit_pool_members WHERE snapshot_id=%s AND pool_kind='up' AND COALESCE(industry,'')<>''
            ORDER BY industry,limit_times DESC NULLS LAST,seal_amount DESC NULLS LAST,symbol
            """,
            (int(snapshot_id),),
        )
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in members:
            grouped[str(item["industry"])].append(item)
        items = []
        for industry, rows in grouped.items():
            items.append({
                "classification_system": classification,
                "sector_code": industry,
                "sector_name": industry,
                "return_1d": None,
                "return_5d": None,
                "return_20d": None,
                "breadth": None,
                "limit_up_count": len(rows),
                "ladder_participation": sum(1 for item in rows if int(item.get("limit_times") or 0) >= 2),
                "leader_symbol": rows[0]["symbol"],
                "laggard_symbol": None,
                "persistence": None,
                "net_flow": None,
                "source_label": rows[0]["source_label"],
                "missing_fields": ["return_1d", "return_5d", "return_20d", "breadth", "net_flow"],
            })
        items.sort(key=lambda item: (-int(item["limit_up_count"]), str(item["sector_name"])))
        return {"snapshot": snapshot, "classification_system": classification, "items": items}

    def research_context(self, snapshot_id: Optional[int] = None, trade_date: Optional[str] = None, market_scope: str = "all_a") -> Dict[str, Any]:
        cache_key = f"{snapshot_id}|{trade_date or ''}|{market_scope}"
        cached = _CONTEXT_CACHE.get(cache_key)
        if cached and time.monotonic() - float(cached.get("at") or 0) < _CONTEXT_TTL_SECONDS:
            return cached["payload"]
        with self._session():
            snapshot = self._snapshot(snapshot_id) if snapshot_id else self._latest_snapshot(trade_date, market_scope)
            if not snapshot:
                payload = {"publication_state": "unavailable", "reason": "没有匹配的封存市场证据快照", "snapshot": None}
            else:
                snapshot["session_label"] = "盘后" if snapshot["snapshot_type"] == "post_close" else "盘中"
                snapshot["freshness"] = "stale" if self._is_stale(snapshot.get("captured_at")) else "fresh"
                snapshot_id = int(snapshot["id"])
                sentiment = self.sentiment(snapshot_id)
                limit_ecosystem = self.limit_ecosystem(snapshot_id)
                payload = {
                    "publication_state": "published" if snapshot["status"] == "published" else "partial",
                    "snapshot": snapshot,
                    "sentiment": sentiment,
                    "limit_ecosystem": limit_ecosystem,
                    "sector_evidence": self.sector_evidence(snapshot_id),
                    "comparisons": self._comparisons(snapshot, sentiment),
                    "evidence_summary": self._evidence_summary(snapshot, sentiment, limit_ecosystem),
                    "heat_rankings": self._rows(
                        """
                        SELECT ranking_provider,ranking_kind,rank,symbol,name,score,source_label
                        FROM heat_ranking_rows WHERE snapshot_id=%s
                        ORDER BY ranking_provider,ranking_kind,rank
                        """,
                        (snapshot_id,),
                    ),
                }
        _CONTEXT_CACHE[cache_key] = {"at": time.monotonic(), "payload": payload}
        return payload

    def _comparisons(self, snapshot: Mapping[str, Any], current: Mapping[str, Any]) -> List[Dict[str, Any]]:
        history = self._comparison_history(snapshot)
        metrics_by_id = self._metrics_for_snapshots([int(item["id"]) for item in history])
        current_metrics = {item["metric_code"]: item.get("value") for item in current["metrics"]}
        output = [
            self._offset_comparison(code, label, offset, history, current_metrics, metrics_by_id)
            for code, label, offset in (
                ("day_over_day", "较前一交易日", 1),
                ("five_day", "较5个交易日前", 5),
                ("twenty_day", "较20个交易日前", 20),
            )
        ]
        output.append(self._highest_board_percentile(current_metrics, history, metrics_by_id))
        return output

    def _comparison_history(self, snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT id,trade_date FROM (
                SELECT DISTINCT ON (trade_date) id,trade_date
                FROM market_evidence_snapshots
                WHERE market_scope=%s AND snapshot_type=%s AND trade_date<=%s
                ORDER BY trade_date DESC,captured_at DESC,id DESC
            ) AS latest_by_trade_date
            ORDER BY trade_date DESC LIMIT 242
            """,
            (snapshot["market_scope"], snapshot["snapshot_type"], snapshot["trade_date"]),
        )

    def _metrics_for_snapshots(self, snapshot_ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
        if not snapshot_ids:
            return {}
        grouped: Dict[int, Dict[str, Any]] = defaultdict(dict)
        for item in self._rows(
            "SELECT snapshot_id,metric_code,value FROM market_evidence_metrics WHERE snapshot_id = ANY(%s)",
            (list(snapshot_ids),),
        ):
            grouped[int(item["snapshot_id"])][str(item["metric_code"])] = item.get("value")
        return grouped

    @staticmethod
    def _offset_comparison(
        code: str,
        label: str,
        offset: int,
        history: Sequence[Mapping[str, Any]],
        current_metrics: Mapping[str, Any],
        metrics_by_id: Mapping[int, Mapping[str, Any]],
    ) -> Dict[str, Any]:
        if len(history) <= offset:
            return {
                "comparison_code": code, "label": label, "publication_state": "unavailable",
                "reason": "封存历史不足", "reference_snapshot": None, "deltas": {},
            }
        reference = history[offset]
        reference_metrics = metrics_by_id.get(int(reference["id"]), {})
        deltas = {
            metric: float(value) - float(reference_metrics[metric])
            for metric, value in current_metrics.items()
            if value is not None and reference_metrics.get(metric) is not None
        }
        return {
            "comparison_code": code, "label": label, "publication_state": "published",
            "reference_snapshot": reference, "deltas": deltas,
        }

    @staticmethod
    def _highest_board_percentile(
        current_metrics: Mapping[str, Any],
        history: Sequence[Mapping[str, Any]],
        metrics_by_id: Mapping[int, Mapping[str, Any]],
    ) -> Dict[str, Any]:
        highest_values = [
            float(metrics["highest_board"])
            for item in history
            if (metrics := metrics_by_id.get(int(item["id"]), {})).get("highest_board") is not None
        ]
        current_highest = current_metrics.get("highest_board")
        percentile = (
            sum(1 for value in highest_values if value <= float(current_highest)) / len(highest_values)
            if current_highest is not None and len(highest_values) >= 20 else None
        )
        return {
            "comparison_code": "one_year_percentile", "label": "一年位置",
            "publication_state": "published" if percentile is not None else "unavailable",
            "reason": None if percentile is not None else "至少需要20个封存交易日",
            "metric_code": "highest_board", "value": percentile,
        }

    @staticmethod
    def _evidence_summary(snapshot: Mapping[str, Any], sentiment: Mapping[str, Any], limit_ecosystem: Mapping[str, Any]) -> Dict[str, Any]:
        metrics = {item["metric_code"]: item.get("value") for item in sentiment["metrics"]}
        facts = [
            {"text": f"涨停 {int(metrics['limit_up_count'])} 家" if metrics.get("limit_up_count") is not None else "涨停家数缺失", "evidence_ref": f"market_evidence_snapshot:{snapshot['id']}:limit_up_count"},
            {"text": f"最高连板 {int(limit_ecosystem['highest_board'])} 板", "evidence_ref": f"market_evidence_snapshot:{snapshot['id']}:limit_pool_members"},
        ]
        inferences = []
        if metrics.get("seal_rate") is not None:
            inferences.append({"text": "封板率偏高" if float(metrics["seal_rate"]) >= 70 else "封板率偏低", "basis": "仅基于当前封板率阈值，不构成投资建议"})
        return {
            "summary_version": "evidence-summary.v1", "kind": "deterministic_ai_ready_summary",
            "facts": facts, "inferences": inferences, "evidence_snapshot_id": int(snapshot["id"]),
            "disclaimer": "事实来自封存证据；推断已单独标记且不构成交易信号",
        }

    def _temperature_components(self, metrics: Mapping[str, Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
        def value(code: str) -> Optional[float]:
            raw = (metrics.get(code) or {}).get("value")
            return float(raw) if raw is not None else None

        seal_rate = value("seal_rate")
        highest = value("highest_board")
        limit_down = value("limit_down_count")
        return {
            "breadth": {"value": value("red_market_ratio"), "raw": {"red_market_ratio": value("red_market_ratio")}},
            "limit_ecology": {"value": max(0.0, min(100.0, seal_rate if seal_rate is not None else 0.0)) if seal_rate is not None else None, "raw": {"seal_rate": seal_rate}},
            "momentum_continuity": {"value": max(0.0, min(100.0, (highest or 0) / 10 * 100)) if highest is not None else None, "raw": {"highest_board": highest}},
            "loss_risk": {"value": max(0.0, 100.0 - min(100.0, (limit_down or 0) * 2)) if limit_down is not None else None, "raw": {"limit_down_count": limit_down}},
            "liquidity_participation": {"value": value("liquidity_participation"), "raw": {"liquidity_participation": value("liquidity_participation")}},
        }

    def _cohorts(self, previous_snapshot_id: int, current_up: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        previous = self._rows(
            "SELECT symbol,limit_times FROM limit_pool_members WHERE snapshot_id=%s AND pool_kind='up'",
            (int(previous_snapshot_id),),
        )
        current_level = {str(item["symbol"]): int(item.get("limit_times") or 0) for item in current_up}
        rows = []
        for level in range(1, 5):
            cohort = {str(item["symbol"]) for item in previous if int(item.get("limit_times") or 0) == level}
            promoted = {symbol for symbol in cohort if current_level.get(symbol, 0) >= level + 1}
            rows.append({
                "from_level": level,
                "cohort_size": len(cohort),
                "promoted_count": len(promoted),
                "eliminated_count": len(cohort - promoted),
                "promotion_rate": len(promoted) / len(cohort) if cohort else None,
                "definition": "前一交易日恰为N板且本交易日进入N+1板及以上",
            })
        return rows

    def _latest_snapshot(self, trade_date: Optional[str], market_scope: str) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM market_evidence_snapshots WHERE market_scope=%s AND snapshot_type='post_close'"
        params: List[Any] = [market_scope]
        if trade_date:
            query += " AND trade_date=%s"
            params.append(str(trade_date)[:10])
        query += " ORDER BY trade_date DESC,captured_at DESC,id DESC LIMIT 1"
        return self._row(query, params)

    def _snapshot(self, snapshot_id: int) -> Dict[str, Any]:
        row = self._row("SELECT * FROM market_evidence_snapshots WHERE id=%s", (int(snapshot_id),))
        if not row:
            raise ValueError("市场证据快照不存在")
        row["session_label"] = "盘后" if row["snapshot_type"] == "post_close" else "盘中"
        row["freshness"] = "stale" if self._is_stale(row.get("captured_at")) else "fresh"
        return row

    @staticmethod
    def _is_stale(value: Any) -> bool:
        if not isinstance(value, datetime):
            return True
        timestamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds() > 36 * 3600

    @staticmethod
    def _single_source(rows: Sequence[Mapping[str, Any]]) -> Optional[str]:
        sources = sorted({str(item.get("source_label")) for item in rows if item.get("source_label")})
        return sources[0] if len(sources) == 1 else ("mixed" if sources else None)

    @staticmethod
    def _numerator(code: str, stored: Mapping[str, Mapping[str, Any]]) -> Optional[float]:
        if code == "seal_rate":
            return (stored.get("limit_up_count") or {}).get("value")
        if code == "rise_fall_ratio":
            return (stored.get("rise_count") or {}).get("value")
        return None

    @staticmethod
    def _denominator(code: str, stored: Mapping[str, Mapping[str, Any]]) -> Optional[float]:
        if code == "seal_rate":
            up = (stored.get("limit_up_count") or {}).get("value")
            broken = (stored.get("broken_board_count") or {}).get("value")
            return float(up) + float(broken) if up is not None and broken is not None else None
        if code == "rise_fall_ratio":
            return (stored.get("fall_count") or {}).get("value")
        return None

    @contextmanager
    def _session(self) -> Iterator[None]:
        previous = getattr(_THREAD_STATE, "connection", None)
        if previous is not None:
            yield
            return
        database = getattr(self, "database", None)
        if database is None:
            yield
            return
        with database.get_connection() as connection:
            _THREAD_STATE.connection = connection
            try:
                yield
            finally:
                _THREAD_STATE.connection = None

    def _row(self, query: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        rows = self._rows(query, params)
        return rows[0] if rows else None

    def _rows(self, query: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        connection = getattr(_THREAD_STATE, "connection", None)
        if connection is not None:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(item) for item in cursor.fetchall()]
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(item) for item in cursor.fetchall()]
