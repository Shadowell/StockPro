"""Live signal-event subscriptions and execution dispatch.

This service is intentionally separate from Signal Center. Signal Center is an
operator-configured OKX Signal Bot webhook workflow, while this module records
the internal standardized strategy intent used by direct OKX API live
subscriptions.
"""
from __future__ import annotations

import copy
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.db.local_db import LocalDatabase, db_instance
from app.services.contract_paper_account import normalize_contract_symbol

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _json_loads(value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_account_id(account_id: Optional[str]) -> str:
    value = str(account_id or "default").strip() or "default"
    return "default" if value == "okx" else value


def _base36(value: Any) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    try:
        num = int(value)
    except (TypeError, ValueError):
        num = 0
    if num <= 0:
        return "0"
    out = ""
    while num:
        num, remainder = divmod(num, 36)
        out = alphabet[remainder] + out
    return out


def _live_client_order_id(subscription_id: int, event_id: int) -> str:
    suffix = _base36(int(time.time() * 1000) % (36**6)).rjust(6, "0")
    value = f"bpls{_base36(subscription_id)}e{_base36(event_id)}{suffix}"
    return value[:32]


def _compact_text(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else ""


def _normalized_symbol_set(values: Any) -> set[str]:
    raw = _json_loads(values, values)
    if isinstance(raw, str):
        raw_values = [raw]
    elif isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        raw_values = list(raw)
    else:
        raw_values = []
    return {normalize_contract_symbol(str(value)) for value in raw_values if str(value or "").strip()}


def _iso_timestamp_ms(value: Any) -> Optional[int]:
    text = _compact_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    except Exception:
        return None


def _first_compact(*values: Any) -> str:
    for value in values:
        text = _compact_text(value)
        if text:
            return text
    return ""


class LiveSignalExecutionService:
    """Persist strategy intents and fan them out to active live subscriptions."""

    ACTIVE_STATUSES = {"running", "active", "deployed"}
    DEPLOYED_STATUSES = ACTIVE_STATUSES | {"paused"}
    WATCHLIST_EXCLUDED_EXECUTION_STATUSES = {
        "failed",
        "rejected",
        "canceled",
        "cancelled",
        "skipped",
    }
    FILLED_EXECUTION_STATUSES = {"filled", "closed"}

    def __init__(
        self,
        db: Optional[LocalDatabase] = None,
        *,
        contract_broker_factory: Optional[Callable[..., Any]] = None,
        spot_broker_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.db = db or db_instance
        self.contract_broker_factory = contract_broker_factory
        self.spot_broker_factory = spot_broker_factory
        self.ensure_schema()

    def ensure_schema(self) -> None:
        conn = self.db.get_connection()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS strategy_signal_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_strategy_id INTEGER NOT NULL,
                exchange TEXT NOT NULL DEFAULT 'okx',
                market_type TEXT NOT NULL DEFAULT 'swap',
                signal_action TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT,
                price REAL,
                notional_usdt REAL,
                quantity REAL,
                leverage REAL,
                margin REAL,
                paper_trade_id TEXT,
                paper_status TEXT,
                live_dispatch_status TEXT NOT NULL DEFAULT 'pending',
                payload TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_strategy_signal_events_source
                ON strategy_signal_events(source_strategy_id, created_at);

            CREATE TABLE IF NOT EXISTS live_strategy_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_strategy_id INTEGER NOT NULL,
                account_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                risk_config TEXT,
                last_signal_event_id INTEGER,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                paused_at TEXT,
                stopped_at TEXT,
                UNIQUE(source_strategy_id, account_id)
            );

            CREATE INDEX IF NOT EXISTS idx_live_strategy_subscriptions_lookup
                ON live_strategy_subscriptions(source_strategy_id, account_id, status);

            CREATE TABLE IF NOT EXISTS live_signal_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_event_id INTEGER NOT NULL,
                subscription_id INTEGER NOT NULL,
                source_strategy_id INTEGER NOT NULL,
                account_id TEXT NOT NULL,
                exchange TEXT NOT NULL DEFAULT 'okx',
                status TEXT NOT NULL,
                live_order_id TEXT,
                request_payload TEXT,
                response_payload TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_live_signal_executions_signal
                ON live_signal_executions(signal_event_id);
            CREATE INDEX IF NOT EXISTS idx_live_signal_executions_subscription
                ON live_signal_executions(subscription_id, created_at);
            """
        )
        conn.commit()
        conn.close()

    def _row_to_subscription(self, row: Any) -> Dict[str, Any]:
        item = dict(row)
        item["id"] = int(item["id"])
        item["source_strategy_id"] = int(item["source_strategy_id"])
        item["account_id"] = _normalize_account_id(item.get("account_id"))
        item["risk_config"] = _json_loads(item.get("risk_config"), {})
        item["deployed"] = str(item.get("status") or "").lower() in self.DEPLOYED_STATUSES
        return item

    def _row_to_event(self, row: Any) -> Dict[str, Any]:
        item = dict(row)
        item["id"] = int(item["id"])
        item["source_strategy_id"] = int(item["source_strategy_id"])
        item["payload"] = _json_loads(item.get("payload"), {})
        return item

    def _row_to_execution(self, row: Any) -> Dict[str, Any]:
        item = dict(row)
        item["id"] = int(item["id"])
        item["signal_event_id"] = int(item["signal_event_id"])
        item["subscription_id"] = int(item["subscription_id"])
        item["source_strategy_id"] = int(item["source_strategy_id"])
        item["request_payload"] = _json_loads(item.get("request_payload"), {})
        item["response_payload"] = _json_loads(item.get("response_payload"), {})
        return item

    def upsert_subscription(
        self,
        *,
        source_strategy_id: int,
        account_id: str,
        status: str = "running",
        risk_config: Optional[Dict[str, Any]] = None,
        last_signal_event_id: Optional[int] = None,
        last_error: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.ensure_schema()
        normalized_account = _normalize_account_id(account_id)
        next_status = str(status or "running").lower()
        now = _now()
        conn = self.db.get_connection()
        existing = conn.execute(
            """
            SELECT created_at, risk_config
            FROM live_strategy_subscriptions
            WHERE source_strategy_id = ? AND account_id = ?
            """,
            (int(source_strategy_id), normalized_account),
        ).fetchone()
        existing_risk = _json_loads(existing["risk_config"], {}) if existing else {}
        conn.execute(
            """
            INSERT INTO live_strategy_subscriptions (
                source_strategy_id, account_id, status, risk_config,
                last_signal_event_id, last_error, created_at, updated_at,
                paused_at, stopped_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_strategy_id, account_id) DO UPDATE SET
                status = excluded.status,
                risk_config = excluded.risk_config,
                last_signal_event_id = COALESCE(excluded.last_signal_event_id, live_strategy_subscriptions.last_signal_event_id),
                last_error = excluded.last_error,
                updated_at = excluded.updated_at,
                paused_at = excluded.paused_at,
                stopped_at = excluded.stopped_at
            """,
            (
                int(source_strategy_id),
                normalized_account,
                next_status,
                _json_dumps(risk_config if risk_config is not None else existing_risk),
                int(last_signal_event_id) if last_signal_event_id is not None else None,
                last_error,
                existing["created_at"] if existing else now,
                now,
                now if next_status == "paused" else None,
                now if next_status == "stopped" else None,
            ),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT *
            FROM live_strategy_subscriptions
            WHERE source_strategy_id = ? AND account_id = ?
            """,
            (int(source_strategy_id), normalized_account),
        ).fetchone()
        conn.close()
        return self._row_to_subscription(row)

    def get_subscription(self, source_strategy_id: int, account_id: str) -> Optional[Dict[str, Any]]:
        self.ensure_schema()
        conn = self.db.get_connection()
        row = conn.execute(
            """
            SELECT *
            FROM live_strategy_subscriptions
            WHERE source_strategy_id = ? AND account_id = ?
            """,
            (int(source_strategy_id), _normalize_account_id(account_id)),
        ).fetchone()
        conn.close()
        return self._row_to_subscription(row) if row else None

    def list_subscriptions(
        self,
        *,
        source_strategy_id: Optional[int] = None,
        account_id: Optional[str] = None,
        statuses: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        self.ensure_schema()
        where: List[str] = []
        params: List[Any] = []
        if source_strategy_id is not None:
            where.append("source_strategy_id = ?")
            params.append(int(source_strategy_id))
        if account_id is not None:
            where.append("account_id = ?")
            params.append(_normalize_account_id(account_id))
        if statuses:
            normalized = [str(status).lower() for status in statuses]
            where.append(f"LOWER(status) IN ({','.join('?' for _ in normalized)})")
            params.extend(normalized)
        sql = "SELECT * FROM live_strategy_subscriptions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC, id DESC"
        conn = self.db.get_connection()
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [self._row_to_subscription(row) for row in rows]

    def set_subscription_status(
        self,
        *,
        source_strategy_id: int,
        account_id: str,
        status: str,
        last_error: Optional[str] = None,
    ) -> Dict[str, Any]:
        existing = self.get_subscription(source_strategy_id, account_id)
        if not existing:
            raise ValueError("live subscription not found")
        return self.upsert_subscription(
            source_strategy_id=source_strategy_id,
            account_id=account_id,
            status=status,
            risk_config=existing.get("risk_config") or {},
            last_signal_event_id=existing.get("last_signal_event_id"),
            last_error=last_error,
        )

    def insert_signal_event(
        self,
        *,
        source_strategy_id: int,
        exchange: str,
        market_type: str,
        action: str,
        symbol: str,
        side: Optional[str] = None,
        price: Optional[float] = None,
        notional_usdt: Optional[float] = None,
        quantity: Optional[float] = None,
        leverage: Optional[float] = None,
        margin: Optional[float] = None,
        paper_trade_id: Optional[str] = None,
        paper_status: Optional[str] = None,
        live_dispatch_status: str = "pending",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.ensure_schema()
        now = _now()
        normalized_symbol = normalize_contract_symbol(symbol) if str(market_type).lower() == "swap" else str(symbol)
        conn = self.db.get_connection()
        cur = conn.execute(
            """
            INSERT INTO strategy_signal_events (
                source_strategy_id, exchange, market_type, signal_action, symbol,
                side, price, notional_usdt, quantity, leverage, margin,
                paper_trade_id, paper_status, live_dispatch_status, payload,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(source_strategy_id),
                str(exchange or "okx"),
                str(market_type or "swap"),
                str(action or ""),
                normalized_symbol,
                side,
                price,
                notional_usdt,
                quantity,
                leverage,
                margin,
                paper_trade_id,
                paper_status,
                live_dispatch_status,
                _json_dumps(payload or {}),
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM strategy_signal_events WHERE id = ?", (cur.lastrowid,)).fetchone()
        conn.close()
        return self._row_to_event(row)

    def _update_signal_event_dispatch_status(self, event_id: int, status: str) -> Dict[str, Any]:
        conn = self.db.get_connection()
        conn.execute(
            """
            UPDATE strategy_signal_events
            SET live_dispatch_status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, _now(), int(event_id)),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM strategy_signal_events WHERE id = ?", (int(event_id),)).fetchone()
        conn.close()
        return self._row_to_event(row)

    def _insert_execution(
        self,
        *,
        event_id: int,
        subscription: Dict[str, Any],
        exchange: str,
        status: str,
        request_payload: Dict[str, Any],
        response_payload: Optional[Dict[str, Any]] = None,
        live_order_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = _now()
        conn = self.db.get_connection()
        cur = conn.execute(
            """
            INSERT INTO live_signal_executions (
                signal_event_id, subscription_id, source_strategy_id, account_id,
                exchange, status, live_order_id, request_payload, response_payload,
                error, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(event_id),
                int(subscription["id"]),
                int(subscription["source_strategy_id"]),
                _normalize_account_id(subscription["account_id"]),
                str(exchange or "okx"),
                str(status or "unknown"),
                live_order_id,
                _json_dumps(request_payload),
                _json_dumps(response_payload or {}),
                error,
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM live_signal_executions WHERE id = ?", (cur.lastrowid,)).fetchone()
        conn.close()
        return self._row_to_execution(row)

    def list_signal_executions(self, signal_event_id: int) -> List[Dict[str, Any]]:
        self.ensure_schema()
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT *
            FROM live_signal_executions
            WHERE signal_event_id = ?
            ORDER BY id ASC
            """,
            (int(signal_event_id),),
        ).fetchall()
        conn.close()
        return [self._row_to_execution(row) for row in rows]

    def enrich_orders_with_attribution(
        self,
        *,
        account_id: str,
        orders: Sequence[Dict[str, Any]],
        lookup_limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Attach BitPro strategy/subscription attribution to exchange order rows."""
        self.ensure_schema()
        normalized_account = _normalize_account_id(account_id)
        order_list = [dict(order or {}) for order in orders or []]
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT
                e.*,
                s.name AS source_strategy_name
            FROM live_signal_executions e
            LEFT JOIN strategies s ON s.id = e.source_strategy_id
            WHERE e.account_id = ?
            ORDER BY e.created_at DESC, e.id DESC
            LIMIT ?
            """,
            (normalized_account, int(max(1, lookup_limit))),
        ).fetchall()
        conn.close()

        by_order_id: Dict[str, Dict[str, Any]] = {}
        by_client_order_id: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            request_payload = _json_loads(row["request_payload"], {})
            response_payload = _json_loads(row["response_payload"], {})
            source_name = _compact_text(row["source_strategy_name"]) or "已删除策略"
            attr = {
                "bitpro_source": "strategy",
                "bitpro_source_label": source_name,
                "source_strategy_id": int(row["source_strategy_id"]),
                "source_strategy_name": source_name,
                "subscription_id": int(row["subscription_id"]),
                "signal_event_id": int(row["signal_event_id"]),
                "live_execution_id": int(row["id"]),
            }
            for key in self._execution_order_ids(row, response_payload):
                by_order_id.setdefault(key, attr)
            for key in self._execution_client_order_ids(request_payload, response_payload):
                by_client_order_id.setdefault(key, attr)

        enriched: List[Dict[str, Any]] = []
        for order in order_list:
            attr = None
            for key in self._order_row_ids(order):
                attr = by_order_id.get(key)
                if attr:
                    break
            if not attr:
                for key in self._order_row_client_order_ids(order):
                    attr = by_client_order_id.get(key)
                    if attr:
                        break
            if attr:
                enriched.append({**order, **attr})
            else:
                enriched.append(
                    {
                        **order,
                        "bitpro_source": "external",
                        "bitpro_source_label": "手动/外部订单",
                        "source_strategy_id": None,
                        "source_strategy_name": None,
                        "subscription_id": None,
                        "signal_event_id": None,
                        "live_execution_id": None,
                    }
                )
        return enriched

    def list_watchlist_items(self, *, account_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Return symbols that have BitPro strategy live execution records."""
        self.ensure_schema()
        normalized_account = _normalize_account_id(account_id)
        excluded = sorted(self.WATCHLIST_EXCLUDED_EXECUTION_STATUSES)
        placeholders = ",".join("?" for _ in excluded)
        conn = self.db.get_connection()
        rows = conn.execute(
            f"""
            SELECT
                ev.symbol AS symbol,
                ev.side AS side,
                ev.signal_action AS signal_action,
                ev.price AS price,
                ev.quantity AS quantity,
                ev.notional_usdt AS notional_usdt,
                ex.source_strategy_id AS source_strategy_id,
                s.name AS source_strategy_name,
                COUNT(*) AS order_count,
                MAX(ex.created_at) AS last_execution_at
            FROM live_signal_executions ex
            JOIN strategy_signal_events ev ON ev.id = ex.signal_event_id
            LEFT JOIN strategies s ON s.id = ex.source_strategy_id
            WHERE ex.account_id = ?
              AND LOWER(ex.status) NOT IN ({placeholders})
            GROUP BY ev.symbol
            ORDER BY MAX(ex.created_at) DESC, ev.symbol ASC
            LIMIT ?
            """,
            (normalized_account, *excluded, int(max(1, limit))),
        ).fetchall()
        conn.close()

        items: List[Dict[str, Any]] = []
        for row in rows:
            source_name = _compact_text(row["source_strategy_name"]) or "已删除策略"
            items.append(
                {
                    "symbol": normalize_contract_symbol(row["symbol"]),
                    "source_strategy_id": int(row["source_strategy_id"]),
                    "source_strategy_name": source_name,
                    "last_side": _compact_text(row["side"]),
                    "last_action": _compact_text(row["signal_action"]),
                    "last_price": _safe_float(row["price"], 0.0) if row["price"] is not None else None,
                    "last_quantity": _safe_float(row["quantity"], 0.0) if row["quantity"] is not None else None,
                    "last_notional_usdt": (
                        _safe_float(row["notional_usdt"], 0.0)
                        if row["notional_usdt"] is not None
                        else None
                    ),
                    "last_execution_at": row["last_execution_at"],
                    "order_count": int(row["order_count"] or 0),
                }
            )
        return items

    def list_trade_markers(
        self,
        *,
        account_id: str,
        symbol: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Return filled live executions as B/S chart markers."""
        self.ensure_schema()
        normalized_account = _normalize_account_id(account_id)
        normalized_symbol = normalize_contract_symbol(symbol)
        statuses = sorted(self.FILLED_EXECUTION_STATUSES)
        placeholders = ",".join("?" for _ in statuses)
        where = [
            "ex.account_id = ?",
            "ev.symbol = ?",
            f"LOWER(ex.status) IN ({placeholders})",
        ]
        params: List[Any] = [normalized_account, normalized_symbol, *statuses]
        if start is not None:
            where.append("ex.created_at >= ?")
            params.append(datetime.fromtimestamp(int(start) / 1000, timezone.utc).isoformat())
        if end is not None:
            where.append("ex.created_at <= ?")
            params.append(datetime.fromtimestamp(int(end) / 1000, timezone.utc).isoformat())
        params.append(int(max(1, limit)))
        conn = self.db.get_connection()
        rows = conn.execute(
            f"""
            SELECT
                ex.*,
                ev.symbol AS symbol,
                ev.side AS side,
                ev.signal_action AS signal_action,
                ev.price AS signal_price,
                ev.quantity AS signal_quantity,
                s.name AS source_strategy_name
            FROM live_signal_executions ex
            JOIN strategy_signal_events ev ON ev.id = ex.signal_event_id
            LEFT JOIN strategies s ON s.id = ex.source_strategy_id
            WHERE {" AND ".join(where)}
            ORDER BY ex.created_at ASC, ex.id ASC
            LIMIT ?
            """,
            params,
        ).fetchall()
        conn.close()

        markers: List[Dict[str, Any]] = []
        for row in rows:
            request_payload = _json_loads(row["request_payload"], {})
            response_payload = _json_loads(row["response_payload"], {})
            price = self._first_numeric(
                response_payload,
                request_payload,
                keys=("fill_price", "fillPrice", "avg_px", "avgPx", "average", "price"),
            )
            if price is None and row["signal_price"] is not None:
                price = _safe_float(row["signal_price"], 0.0)
            quantity = self._first_numeric(
                response_payload,
                request_payload,
                keys=("fill_size", "fillSize", "filled", "amount", "quantity", "sz"),
            )
            if quantity is None and row["signal_quantity"] is not None:
                quantity = _safe_float(row["signal_quantity"], 0.0)
            source_name = _compact_text(row["source_strategy_name"]) or "已删除策略"
            marker_action = self._trade_marker_action(
                action=row["signal_action"],
                side=row["side"],
                request_payload=request_payload,
                response_payload=response_payload,
            )
            markers.append(
                {
                    "id": int(row["id"]),
                    "label": self._trade_marker_label(
                        action=row["signal_action"],
                        side=row["side"],
                        request_payload=request_payload,
                        response_payload=response_payload,
                    ),
                    "side": _compact_text(row["side"]),
                    "action": marker_action,
                    "symbol": normalize_contract_symbol(row["symbol"]),
                    "price": price,
                    "quantity": quantity,
                    "timestamp": _iso_timestamp_ms(row["created_at"]) or 0,
                    "datetime": row["created_at"],
                    "source_strategy_id": int(row["source_strategy_id"]),
                    "source_strategy_name": source_name,
                    "subscription_id": int(row["subscription_id"]),
                    "live_order_id": _compact_text(row["live_order_id"]) or None,
                    "client_order_id": self._execution_client_order_id_from_payloads(
                        request_payload,
                        response_payload,
                    ),
                }
            )
        return markers

    def list_live_order_updates(
        self,
        *,
        account_id: str,
        after_id: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return BitPro live execution updates for the private order bridge."""
        self.ensure_schema()
        normalized_account = _normalize_account_id(account_id)
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT
                ex.*,
                ev.symbol AS symbol,
                ev.side AS side,
                ev.signal_action AS signal_action,
                ev.price AS signal_price,
                ev.quantity AS signal_quantity,
                s.name AS source_strategy_name
            FROM live_signal_executions ex
            JOIN strategy_signal_events ev ON ev.id = ex.signal_event_id
            LEFT JOIN strategies s ON s.id = ex.source_strategy_id
            WHERE ex.account_id = ? AND ex.id > ?
            ORDER BY ex.id ASC
            LIMIT ?
            """,
            (normalized_account, int(max(0, after_id)), int(max(1, limit))),
        ).fetchall()
        conn.close()
        updates: List[Dict[str, Any]] = []
        for row in rows:
            request_payload = _json_loads(row["request_payload"], {})
            response_payload = _json_loads(row["response_payload"], {})
            updates.append(
                {
                    "id": int(row["id"]),
                    "account_id": normalized_account,
                    "status": _compact_text(row["status"]),
                    "symbol": normalize_contract_symbol(row["symbol"]),
                    "side": _compact_text(row["side"]),
                    "action": _compact_text(row["signal_action"]),
                    "price": _safe_float(row["signal_price"], 0.0) if row["signal_price"] is not None else None,
                    "quantity": _safe_float(row["signal_quantity"], 0.0) if row["signal_quantity"] is not None else None,
                    "source_strategy_id": int(row["source_strategy_id"]),
                    "source_strategy_name": _compact_text(row["source_strategy_name"]) or "已删除策略",
                    "subscription_id": int(row["subscription_id"]),
                    "signal_event_id": int(row["signal_event_id"]),
                    "live_order_id": _compact_text(row["live_order_id"]) or None,
                    "client_order_id": self._execution_client_order_id_from_payloads(
                        request_payload,
                        response_payload,
                    ),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return updates

    @staticmethod
    def _first_numeric(*payloads: Dict[str, Any], keys: Sequence[str]) -> Optional[float]:
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            for value in LiveSignalExecutionService._payload_lookup(payload, keys):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _trade_marker_label(
        *,
        action: Any,
        side: Any,
        request_payload: Dict[str, Any],
        response_payload: Dict[str, Any],
    ) -> str:
        joined = " ".join(
            _compact_text(value).lower()
            for value in (
                action,
                side,
                request_payload.get("action"),
                request_payload.get("side"),
                response_payload.get("side"),
                response_payload.get("position_effect"),
                response_payload.get("positionEffect"),
            )
            if _compact_text(value)
        )
        if "exit_short" in joined or ("close" in joined and "short" in joined):
            return "B"
        if "enter_long" in joined or ("open" in joined and "long" in joined) or "buy" in joined:
            return "B"
        return "S"

    @staticmethod
    def _trade_marker_action(
        *,
        action: Any,
        side: Any,
        request_payload: Dict[str, Any],
        response_payload: Dict[str, Any],
    ) -> str:
        compact_action = _compact_text(action) or _compact_text(request_payload.get("action"))
        compact_side = _compact_text(side) or _compact_text(request_payload.get("side")) or _compact_text(response_payload.get("side"))
        normalized_action = compact_action.lower().replace("-", "_").replace(" ", "_")
        normalized_side = compact_side.lower().replace("-", "_").replace(" ", "_")
        if normalized_action in {"open", "enter"} and normalized_side in {"long", "short"}:
            return f"open_{normalized_side}"
        if normalized_action in {"close", "exit"} and normalized_side in {"long", "short"}:
            return f"close_{normalized_side}"
        if normalized_action in {"buy", "sell", "spot_buy", "spot_sell", "open_long", "open_short", "close_long", "close_short"}:
            return normalized_action
        if normalized_side in {"buy", "sell", "long", "short"}:
            return normalized_side
        return compact_action or compact_side

    def list_failed_execution_orders(
        self,
        *,
        account_id: str,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return failed/rejected live executions as order-history compatible rows.

        OKX rejects never become exchange history orders, so the execution ledger
        is the durable source for showing them in the live order-detail table.
        """
        self.ensure_schema()
        normalized_account = _normalize_account_id(account_id)
        max_rows = int(max(1, limit))
        requested_symbol = _compact_text(symbol)
        normalized_symbol = normalize_contract_symbol(requested_symbol) if requested_symbol else ""
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT
                e.*,
                s.name AS source_strategy_name,
                se.market_type AS signal_market_type,
                se.signal_action AS signal_action,
                se.symbol AS signal_symbol,
                se.side AS signal_side,
                se.price AS signal_price,
                se.notional_usdt AS signal_notional_usdt,
                se.quantity AS signal_quantity,
                se.leverage AS signal_leverage,
                se.margin AS signal_margin,
                se.payload AS signal_payload,
                se.created_at AS signal_created_at
            FROM live_signal_executions e
            LEFT JOIN strategy_signal_events se ON se.id = e.signal_event_id
            LEFT JOIN strategies s ON s.id = e.source_strategy_id
            WHERE e.account_id = ?
              AND LOWER(e.status) IN ('failed', 'rejected')
            ORDER BY e.created_at DESC, e.id DESC
            LIMIT ?
            """,
            (normalized_account, max_rows * 4 if normalized_symbol else max_rows),
        ).fetchall()
        conn.close()

        orders: List[Dict[str, Any]] = []
        for row in rows:
            order = self._failed_execution_order_from_row(row)
            if normalized_symbol and normalize_contract_symbol(str(order.get("symbol") or "")) != normalized_symbol:
                continue
            orders.append(order)
            if len(orders) >= max_rows:
                break
        return orders

    def _failed_execution_order_from_row(self, row: Any) -> Dict[str, Any]:
        request_payload = _json_loads(row["request_payload"], {})
        response_payload = _json_loads(row["response_payload"], {})
        signal_payload = _json_loads(row["signal_payload"], {})
        source_name = _compact_text(row["source_strategy_name"]) or "已删除策略"
        raw_status = str(row["status"] or "failed").lower()
        market_type = _first_compact(row["signal_market_type"], request_payload.get("market_type"), "swap").lower()
        action = _first_compact(row["signal_action"], request_payload.get("action")).lower()
        signal_side = _first_compact(row["signal_side"], request_payload.get("side")).lower()
        symbol = _first_compact(row["signal_symbol"], request_payload.get("symbol"))
        quantity = self._execution_quantity(row, request_payload, signal_payload)
        price = self._execution_price(row, request_payload, signal_payload)
        client_order_id = self._execution_client_order_id_from_payloads(request_payload, response_payload)
        order_side, position_effect, position_direction = self._order_fields_from_signal(
            action=action,
            signal_side=signal_side,
            market_type=market_type,
        )
        timestamp = _iso_timestamp_ms(row["created_at"])
        error = _first_compact(row["error"], self._response_error_text(response_payload), "实盘执行失败")

        return {
            "id": f"live-execution-{int(row['id'])}",
            "client_order_id": client_order_id or None,
            "exchange": row["exchange"],
            "instrument_id": self._okx_instrument_id(symbol, market_type),
            "instrument_type": "SWAP" if market_type in {"swap", "future", "futures"} else market_type.upper(),
            "symbol": symbol,
            "side": order_side,
            "position_side": position_direction,
            "position_direction": position_direction,
            "position_effect": position_effect,
            "reduce_only": position_effect == "close",
            "td_mode": _first_compact(request_payload.get("td_mode"), request_payload.get("tdMode"), signal_payload.get("td_mode")) or None,
            "type": _first_compact(request_payload.get("type"), request_payload.get("order_type"), "market"),
            "price": price,
            "average": price,
            "amount": quantity,
            "filled": 0.0,
            "remaining": quantity,
            "status": "failed",
            "raw_status": raw_status,
            "timestamp": timestamp,
            "datetime": row["created_at"],
            "created_timestamp": timestamp,
            "created_datetime": row["created_at"],
            "fee": 0.0,
            "fee_currency": None,
            "pnl": None,
            "bitpro_source": "strategy",
            "bitpro_source_label": source_name,
            "source_strategy_id": int(row["source_strategy_id"]),
            "source_strategy_name": source_name,
            "subscription_id": int(row["subscription_id"]),
            "signal_event_id": int(row["signal_event_id"]),
            "live_execution_id": int(row["id"]),
            "source": "bitpro_live_execution",
            "error": error,
            "failure_log": {
                "title": "OKX 拒单/实盘执行失败",
                "status": raw_status,
                "error": error,
                "request_payload": request_payload,
                "response_payload": response_payload,
                "signal_event": {
                    "id": int(row["signal_event_id"]),
                    "source_strategy_id": int(row["source_strategy_id"]),
                    "market_type": market_type,
                    "action": action,
                    "symbol": symbol,
                    "side": signal_side,
                    "price": row["signal_price"],
                    "quantity": row["signal_quantity"],
                    "notional_usdt": row["signal_notional_usdt"],
                    "leverage": row["signal_leverage"],
                    "created_at": row["signal_created_at"],
                },
                "execution": {
                    "id": int(row["id"]),
                    "subscription_id": int(row["subscription_id"]),
                    "account_id": _normalize_account_id(row["account_id"]),
                    "exchange": row["exchange"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                },
            },
            "info": {
                "source": "bitpro_live_execution",
                "status": raw_status,
                "error": error,
                "request_payload": request_payload,
                "response_payload": response_payload,
            },
        }

    @staticmethod
    def _execution_quantity(row: Any, request_payload: Dict[str, Any], signal_payload: Dict[str, Any]) -> Optional[float]:
        for value in (
            request_payload.get("quantity"),
            request_payload.get("amount"),
            request_payload.get("sz"),
            signal_payload.get("contracts") if isinstance(signal_payload, dict) else None,
            row["signal_quantity"],
        ):
            if value is not None and value != "":
                return _safe_float(value)
        return None

    @staticmethod
    def _execution_price(row: Any, request_payload: Dict[str, Any], signal_payload: Dict[str, Any]) -> Optional[float]:
        for value in (
            request_payload.get("price"),
            request_payload.get("px"),
            signal_payload.get("price") if isinstance(signal_payload, dict) else None,
            row["signal_price"],
        ):
            if value is not None and value != "":
                return _safe_float(value)
        return None

    @classmethod
    def _execution_client_order_id_from_payloads(
        cls,
        request_payload: Dict[str, Any],
        response_payload: Dict[str, Any],
    ) -> str:
        ids = cls._execution_client_order_ids(request_payload, response_payload)
        return ids[0] if ids else ""

    @staticmethod
    def _order_fields_from_signal(
        *,
        action: str,
        signal_side: str,
        market_type: str,
    ) -> tuple[str, Optional[str], Optional[str]]:
        if market_type not in {"swap", "future", "futures", "option"}:
            return ("buy" if signal_side in {"long", "buy"} else "sell"), None, None
        effect = "close" if action == "close" else "open"
        direction = "short" if signal_side in {"short", "sell"} else "long"
        if effect == "close":
            order_side = "buy" if direction == "short" else "sell"
        else:
            order_side = "sell" if direction == "short" else "buy"
        return order_side, effect, direction

    @staticmethod
    def _okx_instrument_id(symbol: str, market_type: str) -> Optional[str]:
        text = normalize_contract_symbol(symbol) if market_type in {"swap", "future", "futures"} else _compact_text(symbol)
        if not text or "/" not in text:
            return text or None
        base, rest = text.split("/", 1)
        quote = rest.split(":", 1)[0] or "USDT"
        suffix = "-SWAP" if market_type in {"swap", "future", "futures"} else ""
        return f"{base.upper()}-{quote.upper()}{suffix}"

    @staticmethod
    def _response_error_text(response_payload: Dict[str, Any]) -> str:
        if not isinstance(response_payload, dict):
            return ""
        data = response_payload.get("data")
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                code = _first_compact(item.get("sCode"), item.get("code"))
                message = _first_compact(item.get("sMsg"), item.get("msg"), item.get("message"))
                if code or message:
                    return " ".join(part for part in [code, message] if part)
        code = _first_compact(response_payload.get("sCode"), response_payload.get("code"))
        message = _first_compact(response_payload.get("sMsg"), response_payload.get("msg"), response_payload.get("message"))
        return " ".join(part for part in [code, message] if part)

    @staticmethod
    def _payload_lookup(payload: Dict[str, Any], keys: Sequence[str]) -> List[str]:
        out: List[str] = []
        if not isinstance(payload, dict):
            return out
        candidates: List[Any] = []
        for key in keys:
            candidates.append(payload.get(key))
        raw_order = payload.get("raw_order")
        if isinstance(raw_order, dict):
            for key in keys:
                candidates.append(raw_order.get(key))
            info = raw_order.get("info")
            if isinstance(info, dict):
                for key in keys:
                    candidates.append(info.get(key))
                data = info.get("data")
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            for key in keys:
                                candidates.append(item.get(key))
        info = payload.get("info")
        if isinstance(info, dict):
            for key in keys:
                candidates.append(info.get(key))
        for value in candidates:
            text = _compact_text(value)
            if text and text not in out:
                out.append(text)
        return out

    @classmethod
    def _execution_order_ids(cls, row: Any, response_payload: Dict[str, Any]) -> List[str]:
        values = [_compact_text(row["live_order_id"])]
        values.extend(cls._payload_lookup(response_payload, ("order_id", "orderId", "id", "ordId")))
        return [value for value in values if value]

    @classmethod
    def _execution_client_order_ids(
        cls,
        request_payload: Dict[str, Any],
        response_payload: Dict[str, Any],
    ) -> List[str]:
        values = cls._payload_lookup(request_payload, ("client_order_id", "clientOrderId", "clOrdId"))
        values.extend(cls._payload_lookup(response_payload, ("client_order_id", "clientOrderId", "clOrdId")))
        return [value for index, value in enumerate(values) if value and value not in values[:index]]

    @classmethod
    def _order_row_ids(cls, order: Dict[str, Any]) -> List[str]:
        return cls._payload_lookup(order, ("id", "order_id", "orderId", "ordId"))

    @classmethod
    def _order_row_client_order_ids(cls, order: Dict[str, Any]) -> List[str]:
        return cls._payload_lookup(order, ("client_order_id", "clientOrderId", "clOrdId"))

    async def record_contract_signal_and_dispatch(
        self,
        *,
        source_strategy_id: int,
        exchange: str,
        symbols: List[str],
        source_config: Dict[str, Any],
        action: str,
        symbol: str,
        side: str,
        price: Optional[float] = None,
        notional_usdt: Optional[float] = None,
        leverage: Optional[float] = None,
        quantity: Optional[float] = None,
        margin: Optional[float] = None,
        paper_trade_id: Optional[str] = None,
        paper_status: Optional[str] = "filled",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        event = self.insert_signal_event(
            source_strategy_id=source_strategy_id,
            exchange=exchange,
            market_type="swap",
            action=action,
            symbol=symbol,
            side=side,
            price=price,
            notional_usdt=notional_usdt,
            quantity=quantity,
            leverage=leverage,
            margin=margin,
            paper_trade_id=paper_trade_id,
            paper_status=paper_status,
            payload=payload or {},
        )
        subscriptions = self.list_subscriptions(
            source_strategy_id=source_strategy_id,
            statuses=sorted(self.ACTIVE_STATUSES),
        )
        if not subscriptions:
            return self._update_signal_event_dispatch_status(event["id"], "no_active_subscription")

        statuses: List[str] = []
        for subscription in subscriptions:
            execution = await self._dispatch_contract_signal(
                event=event,
                subscription=subscription,
                exchange=exchange,
                symbols=symbols,
                source_config=source_config,
                action=action,
                symbol=symbol,
                side=side,
                price=price,
                notional_usdt=notional_usdt,
                leverage=leverage,
                quantity=quantity,
                payload=payload or {},
            )
            statuses.append(str(execution.get("status") or "unknown"))

        if all(status == "filled" for status in statuses):
            final_status = "filled"
        elif any(status in {"failed", "rejected"} for status in statuses):
            final_status = "partial_failed" if len(statuses) > 1 else statuses[0]
        elif statuses:
            final_status = "submitted"
        else:
            final_status = "no_active_subscription"
        return self._update_signal_event_dispatch_status(event["id"], final_status)

    async def _dispatch_contract_signal(
        self,
        *,
        event: Dict[str, Any],
        subscription: Dict[str, Any],
        exchange: str,
        symbols: List[str],
        source_config: Dict[str, Any],
        action: str,
        symbol: str,
        side: str,
        price: Optional[float],
        notional_usdt: Optional[float],
        leverage: Optional[float],
        quantity: Optional[float],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        from app.services import live_account_service
        from app.services.strategy_engine import LiveContractBroker
        from app.services.binance_usdm_contract_broker import BinanceUsdmContractBroker

        account_id = _normalize_account_id(subscription["account_id"])
        exchange_alias = live_account_service.exchange_alias_for_account(account_id)
        if self.contract_broker_factory:
            broker_factory = self.contract_broker_factory
        elif exchange_alias.split(":", 1)[0] == "binanceusdm":
            broker_factory = BinanceUsdmContractBroker
        else:
            broker_factory = LiveContractBroker
        live_config = copy.deepcopy(source_config or {})
        live_config["is_paper_trading"] = False
        live_config["td_mode"] = "isolated"
        live_config["live_account_id"] = account_id
        live_config["exchange"] = exchange_alias
        client_order_id = _live_client_order_id(int(subscription["id"]), int(event["id"]))
        live_config["live_client_order_id"] = client_order_id
        broker_symbols = [normalize_contract_symbol(sym) for sym in symbols if str(sym).strip()]
        if not broker_symbols:
            broker_symbols = [normalize_contract_symbol(symbol)]
        request_payload = {
            "action": action,
            "client_order_id": client_order_id,
            "symbol": normalize_contract_symbol(symbol),
            "side": side,
            "price": price,
            "notional_usdt": notional_usdt,
            "quantity": quantity,
            "leverage": leverage,
            "td_mode": live_config["td_mode"],
            "payload": payload,
        }
        risk_config = subscription.get("risk_config") or {}
        allowed_symbols = _normalized_symbol_set(risk_config.get("allowed_live_symbols"))
        normalized_symbol = normalize_contract_symbol(symbol)
        if allowed_symbols and normalized_symbol not in allowed_symbols:
            error = f"{normalized_symbol} 不在实盘预检通过标的内，已阻止真实下单"
            execution = self._insert_execution(
                event_id=event["id"],
                subscription=subscription,
                exchange=exchange_alias,
                status="rejected",
                request_payload=request_payload,
                error=error,
            )
            self.upsert_subscription(
                source_strategy_id=int(subscription["source_strategy_id"]),
                account_id=account_id,
                status=str(subscription.get("status") or "running"),
                risk_config=risk_config,
                last_signal_event_id=event["id"],
                last_error=None,
            )
            return execution
        try:
            broker = broker_factory(
                strategy_id=0,
                exchange_name=exchange_alias,
                symbols=broker_symbols,
                config=live_config,
            )
            normalized_action = str(action or "").lower()
            if normalized_action == "open":
                result = await broker.open_contract(
                    symbol,
                    side,
                    float(notional_usdt or 0.0),
                    leverage=leverage,
                    price=price,
                )
            elif normalized_action == "close":
                close_contracts = quantity if quantity is not None and _safe_float(quantity) > 0 else None
                close_ratio = _safe_float(payload.get("ratio"), 1.0) if isinstance(payload, dict) else 1.0
                result = await broker.close_contract(
                    symbol,
                    side,
                    ratio=close_ratio,
                    contracts=close_contracts,
                    price=price,
                )
            else:
                raise ValueError(f"unsupported live contract signal action: {action}")

            response = dict(result)
            status = str(response.get("status") or "submitted").lower()
            live_order_id = str(response.get("order_id") or response.get("id") or "") or None
            execution = self._insert_execution(
                event_id=event["id"],
                subscription=subscription,
                exchange=exchange_alias,
                status=status,
                live_order_id=live_order_id,
                request_payload=request_payload,
                response_payload=response,
            )
            self.upsert_subscription(
                source_strategy_id=int(subscription["source_strategy_id"]),
                account_id=account_id,
                status=str(subscription.get("status") or "running"),
                risk_config=subscription.get("risk_config") or {},
                last_signal_event_id=event["id"],
                last_error=None,
            )
            return execution
        except Exception as exc:
            logger.warning(
                "[LiveSignalExecution] dispatch failed source=%s account=%s symbol=%s action=%s: %s",
                event.get("source_strategy_id"),
                account_id,
                symbol,
                action,
                exc,
            )
            execution = self._insert_execution(
                event_id=event["id"],
                subscription=subscription,
                exchange=exchange_alias,
                status="failed",
                request_payload=request_payload,
                error=str(exc),
            )
            self.upsert_subscription(
                source_strategy_id=int(subscription["source_strategy_id"]),
                account_id=account_id,
                status=str(subscription.get("status") or "running"),
                risk_config=subscription.get("risk_config") or {},
                last_signal_event_id=event["id"],
                last_error=str(exc),
            )
            return execution


live_signal_execution_service = LiveSignalExecutionService()
