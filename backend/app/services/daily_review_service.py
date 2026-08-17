"""Trade-date audit review assembled from immutable research and Paper objects."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

import psycopg2.extras

from app.services.dataset_snapshot_service import canonical_hash
from app.services.trading_date_service import TradingDateService


class DailyReviewService:
    def __init__(self, database):
        self.database = database
        self.trading_dates = TradingDateService(database)

    def available_dates(self, limit: int = 120) -> List[str]:
        requested_limit = max(1, min(int(limit), 500))
        evidence_dates = self._published_evidence_dates()
        rows = self._rows(
            """
            SELECT DISTINCT trade_date FROM (
                SELECT trade_date FROM market_evidence_snapshots
                UNION SELECT trade_date FROM stock_pool_snapshots
                UNION SELECT signal_time::date FROM strategy_signals WHERE paper_instance_id IS NOT NULL
                UNION SELECT traded_at::date FROM trades WHERE paper_instance_id IS NOT NULL
                UNION SELECT trade_date FROM paper_equity_snapshots
                UNION SELECT trade_date FROM daily_reviews
            ) dates WHERE trade_date IS NOT NULL ORDER BY trade_date DESC LIMIT %s
            """,
            (500,),
        )
        open_dates = self.trading_dates.published_open_dates()
        result: List[str] = []
        for item in rows:
            trade_date = str(item["trade_date"])[:10]
            if self._is_reviewable_date(trade_date, open_dates, evidence_dates):
                result.append(trade_date)
            if len(result) >= requested_limit:
                break
        return result

    def _published_evidence_dates(self) -> set[str]:
        rows = self._rows(
            "SELECT DISTINCT trade_date FROM market_evidence_snapshots WHERE trade_date IS NOT NULL"
        )
        return {str(item["trade_date"])[:10] for item in rows}

    def _is_reviewable_date(self, trade_date: str, open_dates: set[str], evidence_dates: set[str]) -> bool:
        if trade_date in open_dates:
            return True
        if trade_date not in evidence_dates:
            return False
        return date.fromisoformat(trade_date).weekday() < 5

    def context(self, trade_date: str, *, persist: bool = False) -> Dict[str, Any]:
        target = self._date(trade_date)
        review = self._row("SELECT * FROM daily_reviews WHERE trade_date=%s", (target,))
        if review and review["status"] == "sealed":
            return self._stored(review)
        items = self._assemble_items(target)
        metrics = self._assemble_metrics(target)
        manifest_hash = canonical_hash({"trade_date": target, "items": items, "metrics": metrics})
        if persist:
            review = self._persist(target, review, items, metrics, manifest_hash)
            return self._stored(review)
        return {
            "review": review,
            "trade_date": target,
            "status": review["status"] if review else "live",
            "items": items,
            "metrics": metrics,
            "source_manifest_hash": manifest_hash,
            "counts": self._counts(items),
        }

    def save(self, trade_date: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        target = self._date(trade_date)
        current = self._row("SELECT * FROM daily_reviews WHERE trade_date=%s", (target,))
        if current and current["status"] == "sealed":
            raise ValueError("已封存复盘不可修改")
        if not current:
            self.context(target, persist=True)
        self._execute(
            "UPDATE daily_reviews SET author_name=%s,summary=%s,next_day_plan=%s,updated_at=NOW() WHERE trade_date=%s",
            (str(payload.get("author_name") or "admin"), payload.get("summary"), payload.get("next_day_plan"), target),
        )
        return self.context(target)

    def seal(self, trade_date: str) -> Dict[str, Any]:
        target = self._date(trade_date)
        context = self.context(target, persist=True)
        review = context["review"] or {}
        if review.get("status") == "sealed":
            return {**context, "reused": True}
        self._execute("UPDATE daily_reviews SET status='sealed',sealed_at=NOW(),updated_at=NOW() WHERE id=%s", (review["id"],))
        return self.context(target)

    def list_reviews(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT r.*,(SELECT COUNT(*) FROM daily_review_items i WHERE i.daily_review_id=r.id)::INTEGER AS item_count,
                   (SELECT COUNT(*) FROM daily_review_metrics m WHERE m.daily_review_id=r.id)::INTEGER AS metric_count
            FROM daily_reviews r ORDER BY trade_date DESC LIMIT %s
            """,
            (max(1, min(int(limit), 500)),),
        )

    def resolve(self, object_type: str, object_id: str) -> Dict[str, Any]:
        targets = {
            "market_evidence_snapshot": ("market_evidence_snapshots", "id", int),
            "stock_pool_snapshot": ("stock_pool_snapshots", "id", int),
            "strategy_signal": ("strategy_signals", "id", str),
            "risk_event": ("risk_events", "id", str),
            "order": ("orders", "id", str),
            "trade": ("trades", "id", str),
            "paper_equity_snapshot": ("paper_equity_snapshots", "id", int),
            "paper_instance": ("paper_instances", "id", str),
        }
        target = targets.get(object_type)
        if not target:
            return {"status": "unavailable", "reason": "不支持的审计对象类型", "object_type": object_type, "object_id": object_id}
        table, column, convert = target
        try:
            converted = convert(object_id)
        except (TypeError, ValueError):
            return {"status": "unavailable", "reason": "对象 ID 格式无效", "object_type": object_type, "object_id": object_id}
        row = self._row(f"SELECT * FROM {table} WHERE {column}=%s", (converted,))
        return {"status": "resolved" if row else "archived", "object_type": object_type, "object_id": object_id, "object": row}

    def _assemble_items(self, target: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for row in self._rows("SELECT * FROM market_evidence_snapshots WHERE trade_date=%s ORDER BY available_at,id", (target,)):
            self._add(items, self._trade_time(target, "17:30:00"), "market", f"市场证据 · {row['snapshot_type']}", f"{row['market_scope']} · {row['status']}", "market_evidence_snapshot", row["id"], f"/market?trade_date={target}", {"content_hash": row["content_hash"], "source_map": row["source_map"], "available_at": row.get("available_at")})
        for row in self._rows("SELECT s.*,p.name AS pool_name FROM stock_pool_snapshots s JOIN stock_pools p ON p.id=s.pool_id WHERE s.trade_date=%s ORDER BY s.id", (target,)):
            occurred = self._trade_time(target, "17:31:00")
            self._add(items, occurred, "pool", f"股票池快照 · {row['pool_name']}", f"{row['member_count']} 个固定成员", "stock_pool_snapshot", row["id"], f"/pools?tab=snapshots&snapshot={row['id']}", {"manifest_hash": row["manifest_hash"], "dataset_snapshot_id": row["dataset_snapshot_id"], "factor_snapshot_id": row.get("factor_snapshot_id"), "universe_snapshot_id": row["universe_snapshot_id"]})
        for row in self._rows("SELECT * FROM strategy_signals WHERE paper_instance_id IS NOT NULL AND signal_time::date=%s ORDER BY signal_time,id", (target,)):
            self._add(items, row["signal_time"], "strategy", f"策略信号 · {row['symbol']} {row['signal_type']}", row.get("reason"), "strategy_signal", row["id"], f"/paper?tab=signals&instance={row['paper_instance_id']}", {"paper_instance_id": str(row["paper_instance_id"]), "data_available_at": row.get("data_available_at"), "strength": row.get("strength"), "status": row["status"]})
        risk_rows = self._rows("""
            SELECT r.*,o.symbol,o.side,o.filled_at,o.earliest_fill_at,o.created_at AS order_created_at
            FROM risk_events r LEFT JOIN orders o ON o.id=r.order_id
            WHERE r.paper_instance_id IS NOT NULL AND COALESCE(o.filled_at,o.earliest_fill_at,o.created_at,r.created_at)::date=%s
            ORDER BY COALESCE(o.filled_at,o.earliest_fill_at,o.created_at,r.created_at),r.id
        """, (target,))
        for row in risk_rows:
            occurred = row.get("filled_at") or row.get("earliest_fill_at") or row.get("order_created_at") or row["created_at"]
            self._add(items, occurred, "risk", f"风险决策 · {row.get('symbol') or '--'} {row.get('decision') or row['severity']}", row["message"], "risk_event", row["id"], f"/paper?tab=orders&instance={row['paper_instance_id']}", {"paper_instance_id": str(row["paper_instance_id"]), "order_id": str(row.get("order_id") or ""), "rule_id": str(row.get("rule_id") or ""), "rule_version": row.get("rule_version"), "decision": row.get("decision")})
        for row in self._rows("SELECT * FROM orders WHERE paper_instance_id IS NOT NULL AND COALESCE(filled_at,earliest_fill_at,created_at)::date=%s ORDER BY COALESCE(filled_at,earliest_fill_at,created_at),id", (target,)):
            occurred = row.get("filled_at") or row.get("earliest_fill_at") or row["created_at"]
            self._add(items, occurred, "order", f"模拟订单 · {row['symbol']} {row['side']}", f"{row['quantity']} 股 · {row['status']}", "order", row["id"], f"/paper?tab=orders&instance={row['paper_instance_id']}", {"paper_instance_id": str(row["paper_instance_id"]), "signal_id": str(row.get("signal_id") or ""), "risk_event_id": str(row.get("risk_event_id") or ""), "signal_time": row.get("signal_time"), "filled_at": row.get("filled_at")})
        for row in self._rows("SELECT * FROM trades WHERE paper_instance_id IS NOT NULL AND traded_at::date=%s ORDER BY traded_at,id", (target,)):
            self._add(items, row["traded_at"], "trade", f"模拟成交 · {row['symbol']} {row['side']}", f"{row['quantity']} 股 @ {row['price']}", "trade", row["id"], f"/paper?tab=orders&instance={row['paper_instance_id']}", {"paper_instance_id": str(row["paper_instance_id"]), "order_id": str(row.get("order_id") or ""), "commission": row["commission"], "signal_time": row.get("signal_time")})
        for row in self._rows("SELECT * FROM paper_equity_snapshots WHERE trade_date=%s ORDER BY created_at,id", (target,)):
            self._add(items, self._trade_time(target, "15:05:00"), "performance", f"Paper 权益 · NAV {float(row['nav']):.4f}", f"权益 {row['equity']} · 回撤 {float(row['drawdown']):.2%}", "paper_equity_snapshot", row["id"], f"/paper?tab=account&instance={row['paper_instance_id']}", {"paper_instance_id": str(row["paper_instance_id"]), "cash": row["cash"], "market_value": row["market_value"], "equity": row["equity"], "ledger_difference": row["ledger_difference"], "persisted_at": row["created_at"]})
        return sorted(items, key=lambda item: (str(item["occurred_at"]), item["item_key"]))

    def _assemble_metrics(self, target: str) -> List[Dict[str, Any]]:
        metrics: List[Dict[str, Any]] = []
        for row in self._rows("""
            SELECT m.snapshot_id,m.metric_code,m.value,m.unit,m.definition_version,m.source_label
            FROM market_evidence_metrics m JOIN market_evidence_snapshots s ON s.id=m.snapshot_id
            WHERE s.trade_date=%s ORDER BY m.metric_code
        """, (target,)):
            metrics.append({"metric_code": row["metric_code"], "metric_value": row["value"], "unit": row["unit"], "comparison_window": "1d", "source_object_type": "market_evidence_snapshot", "source_object_id": str(row["snapshot_id"]), "calculation_version": row["definition_version"], "evidence": {"source_label": row["source_label"]}})
        for row in self._rows("SELECT id,paper_instance_id,equity,nav,drawdown,ledger_difference FROM paper_equity_snapshots WHERE trade_date=%s ORDER BY id", (target,)):
            for code, value, unit in (("paper_equity", row["equity"], "CNY"), ("paper_nav", row["nav"], "ratio"), ("paper_drawdown", row["drawdown"], "ratio"), ("ledger_difference", row["ledger_difference"], "CNY")):
                metrics.append({"metric_code": f"{code}:{row['paper_instance_id']}", "metric_value": float(value), "unit": unit, "comparison_window": "1d", "source_object_type": "paper_equity_snapshot", "source_object_id": str(row["id"]), "calculation_version": "paper-runtime.v1", "evidence": {"paper_instance_id": str(row["paper_instance_id"])}})
        return metrics

    def _persist(self, target: str, review: Optional[Mapping[str, Any]], items: List[Dict[str, Any]], metrics: List[Dict[str, Any]], manifest_hash: str) -> Dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                if review:
                    review_id = str(review["id"])
                    cursor.execute("UPDATE daily_reviews SET source_manifest_hash=%s,updated_at=NOW() WHERE id=%s", (manifest_hash, review_id))
                    cursor.execute("DELETE FROM daily_review_items WHERE daily_review_id=%s", (review_id,))
                    cursor.execute("DELETE FROM daily_review_metrics WHERE daily_review_id=%s", (review_id,))
                else:
                    cursor.execute("INSERT INTO daily_reviews(trade_date,source_manifest_hash) VALUES (%s,%s) RETURNING id", (target, manifest_hash))
                    review_id = str(cursor.fetchone()["id"])
                if items:
                    psycopg2.extras.execute_values(cursor, """
                        INSERT INTO daily_review_items(daily_review_id,item_key,occurred_at,category,title,summary,
                            source_object_type,source_object_id,source_route,resolution_status,evidence,evidence_hash) VALUES %s
                    """, [(review_id, item["item_key"], item["occurred_at"], item["category"], item["title"], item.get("summary"), item["source_object_type"], item["source_object_id"], item.get("source_route"), item["resolution_status"], psycopg2.extras.Json(item["evidence"], dumps=self._json_dumps), item["evidence_hash"]) for item in items])
                if metrics:
                    psycopg2.extras.execute_values(cursor, """
                        INSERT INTO daily_review_metrics(daily_review_id,metric_code,metric_value,unit,comparison_window,
                            source_object_type,source_object_id,calculation_version,evidence) VALUES %s
                    """, [(review_id, item["metric_code"], item["metric_value"], item.get("unit"), item.get("comparison_window"), item["source_object_type"], item["source_object_id"], item["calculation_version"], psycopg2.extras.Json(item["evidence"], dumps=self._json_dumps)) for item in metrics])
        return self._row("SELECT * FROM daily_reviews WHERE id=%s", (review_id,)) or {}

    def _stored(self, review: Mapping[str, Any]) -> Dict[str, Any]:
        items = self._rows("SELECT * FROM daily_review_items WHERE daily_review_id=%s ORDER BY occurred_at,id", (review["id"],))
        metrics = self._rows("SELECT * FROM daily_review_metrics WHERE daily_review_id=%s ORDER BY metric_code,id", (review["id"],))
        return {"review": dict(review), "trade_date": str(review["trade_date"])[:10], "status": review["status"], "items": items, "metrics": metrics, "source_manifest_hash": review.get("source_manifest_hash"), "counts": self._counts(items)}

    @staticmethod
    def _add(items: List[Dict[str, Any]], occurred_at: Any, category: str, title: str, summary: Optional[str], object_type: str, object_id: Any, route: str, evidence: Mapping[str, Any]) -> None:
        normalized = {"category": category, "title": title, "summary": summary, "source_object_type": object_type, "source_object_id": str(object_id), "source_route": route, "evidence": dict(evidence)}
        normalized["item_key"] = canonical_hash({"object_type": object_type, "object_id": str(object_id), "category": category})
        normalized["occurred_at"] = occurred_at or datetime.now(timezone.utc)
        normalized["resolution_status"] = "resolved"
        normalized["evidence_hash"] = canonical_hash(normalized)
        items.append(normalized)

    @staticmethod
    def _counts(items: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
        counts: Dict[str, int] = {
            category: 0
            for category in (
                "market",
                "pool",
                "strategy",
                "risk",
                "order",
                "trade",
                "position",
                "performance",
                "system",
            )
        }
        for item in items:
            key = str(item["category"])
            counts[key] = counts.get(key, 0) + 1
        return counts

    @staticmethod
    def _date(value: str) -> str:
        target = str(value or "")[:10]
        datetime.strptime(target, "%Y-%m-%d")
        return target

    @staticmethod
    def _json_dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _trade_time(trade_date: str, clock: str) -> datetime:
        return datetime.fromisoformat(f"{trade_date}T{clock}+08:00")

    def _row(self, query: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
                return dict(row) if row else None

    def _rows(self, query: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(item) for item in cursor.fetchall()]

    def _execute(self, query: str, params: Sequence[Any] = ()) -> None:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
