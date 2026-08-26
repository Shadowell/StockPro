"""Signal-center domain service for OKX Signal Bot delivery."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

import httpx

from app.db.local_db import LocalDatabase
from app.services.contract_paper_account import normalize_contract_symbol

logger = logging.getLogger(__name__)


OKX_ACTIONS = {"ENTER_LONG", "ENTER_SHORT", "EXIT_LONG", "EXIT_SHORT"}
DEFAULT_SIGNAL_MAX_LAG_SEC = 30
DEFAULT_SIGNAL_CHANNEL_MAX_MARGIN_USDT = 10.0
LEGACY_DEFAULT_RISK_NOTE = "人工确认后才会推送 OKX Signal Bot；BitPro 不直接通过交易 API 下单。"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def okx_inst_id_from_contract_symbol(symbol: str) -> str:
    raw = normalize_contract_symbol(symbol)
    if not raw:
        raise ValueError("symbol is required")
    if raw.endswith("-SWAP") and "-" in raw:
        return raw

    clean = raw.split(":", 1)[0]
    if "/" in clean:
        base, quote = clean.split("/", 1)
        return f"{base}-{quote}-SWAP"
    if "-" in clean:
        parts = clean.split("-")
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}-SWAP"
    raise ValueError(f"unsupported contract symbol: {symbol}")


def _payload_amount(value: float) -> str:
    text = f"{round(float(value), 8):.8f}".rstrip("0").rstrip(".")
    return text or "0"


def _build_okx_signal_payload(
    *,
    action: str,
    instrument: str,
    signal_token: str,
    timestamp: str,
    max_lag_sec: int,
    investment_type: str,
    amount: float,
) -> Dict[str, Any]:
    return {
        "action": action,
        "instrument": instrument,
        "signalToken": signal_token,
        "timestamp": timestamp,
        "maxLag": str(int(max_lag_sec)),
        "orderType": "market",
        "orderPriceOffset": "",
        "investmentType": investment_type,
        "amount": _payload_amount(amount),
    }


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _normalize_list(value: Any, *, upper: bool = False) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",")]
    elif isinstance(value, Iterable):
        items = list(value)
    else:
        items = [value]
    normalized: List[Any] = []
    for item in items:
        if item is None or item == "":
            continue
        if isinstance(item, str):
            item = item.strip()
            if upper:
                item = item.upper()
        normalized.append(item)
    return normalized


def _normalize_risk_note(value: Any) -> str:
    note = str(value or "").strip()
    if note == LEGACY_DEFAULT_RISK_NOTE:
        return ""
    return note


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mask_tail(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * 8}{value[-4:]}"


def _mask_webhook_url(value: str) -> str:
    if not value:
        return ""
    if "/" not in value:
        return _mask_tail(value)
    prefix, _, _ = value.rpartition("/")
    return f"{prefix}/***"


class SignalCenterService:
    """Persists strategy signals, channel config, approval, and webhook delivery."""

    def __init__(
        self,
        db: Optional[LocalDatabase] = None,
        *,
        approval_ttl_sec: int = 180,
        default_max_lag_sec: int = DEFAULT_SIGNAL_MAX_LAG_SEC,
    ) -> None:
        self.db = db or LocalDatabase()
        self.approval_ttl_sec = int(approval_ttl_sec)
        self.default_max_lag_sec = int(default_max_lag_sec)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = self.db.get_connection()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS strategy_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_uid TEXT NOT NULL UNIQUE,
                strategy_id INTEGER NOT NULL,
                strategy_name TEXT,
                symbol TEXT NOT NULL,
                okx_inst_id TEXT NOT NULL,
                market_type TEXT NOT NULL DEFAULT 'swap',
                action TEXT NOT NULL,
                price REAL,
                suggested_investment_type TEXT NOT NULL,
                suggested_amount REAL NOT NULL,
                reason TEXT,
                confidence TEXT,
                risk_note TEXT,
                status TEXT NOT NULL DEFAULT 'pending_approval',
                dedupe_key TEXT NOT NULL UNIQUE,
                raw_context TEXT,
                okx_payload_preview TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS signal_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                webhook_url TEXT NOT NULL,
                signal_token TEXT NOT NULL,
                allowed_strategy_ids TEXT,
                allowed_symbols TEXT,
                allowed_actions TEXT,
                max_margin_usdt REAL DEFAULT 10,
                max_lag_sec INTEGER NOT NULL DEFAULT 30,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS signal_strategy_settings (
                strategy_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                manual_approval_required INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS signal_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                request_payload TEXT,
                response_status INTEGER,
                response_body TEXT,
                error TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                approved_at TEXT,
                sent_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(signal_id, channel_id)
            );

            CREATE INDEX IF NOT EXISTS idx_strategy_signals_status
                ON strategy_signals(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_strategy_signals_strategy
                ON strategy_signals(strategy_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_signal_deliveries_signal
                ON signal_deliveries(signal_id);
            CREATE INDEX IF NOT EXISTS idx_signal_deliveries_channel
                ON signal_deliveries(channel_id);
            """
        )
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(signal_strategy_settings)").fetchall()
        }
        if "manual_approval_required" not in columns:
            conn.execute(
                "ALTER TABLE signal_strategy_settings "
                "ADD COLUMN manual_approval_required INTEGER NOT NULL DEFAULT 0"
            )
        conn.commit()

    def _execute(self, sql: str, params: Sequence[Any] = ()):
        conn = self.db.get_connection()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur

    def _fetchone(self, sql: str, params: Sequence[Any] = ()):
        return self.db.get_connection().execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: Sequence[Any] = ()):
        return self.db.get_connection().execute(sql, params).fetchall()

    def _strategy_name(self, strategy_id: int, fallback: str = "") -> str:
        if fallback:
            return fallback
        try:
            row = self._fetchone("SELECT name FROM strategies WHERE id = ?", (strategy_id,))
        except Exception:
            return ""
        if row:
            return str(row["name"] or "")
        return ""

    def is_strategy_signal_enabled(self, strategy_id: int) -> bool:
        row = self._fetchone(
            "SELECT enabled FROM signal_strategy_settings WHERE strategy_id = ?",
            (int(strategy_id),),
        )
        return bool(row and int(row["enabled"] or 0) == 1)

    def is_strategy_manual_approval_required(self, strategy_id: int) -> bool:
        row = self._fetchone(
            "SELECT manual_approval_required FROM signal_strategy_settings WHERE strategy_id = ?",
            (int(strategy_id),),
        )
        return bool(row and int(row["manual_approval_required"] or 0) == 1)

    def set_strategy_signal_enabled(self, strategy_id: int, enabled: bool) -> Dict[str, Any]:
        return self.update_strategy_signal_settings(strategy_id, enabled=enabled)

    def update_strategy_signal_settings(
        self,
        strategy_id: int,
        *,
        enabled: Optional[bool] = None,
        manual_approval_required: Optional[bool] = None,
    ) -> Dict[str, Any]:
        if enabled is None and manual_approval_required is None:
            raise ValueError("至少需要更新一个策略信号设置")
        existing = self._fetchone(
            """
            SELECT enabled, manual_approval_required
            FROM signal_strategy_settings
            WHERE strategy_id = ?
            """,
            (int(strategy_id),),
        )
        next_enabled = bool(existing and int(existing["enabled"] or 0) == 1)
        next_manual_approval_required = bool(
            existing and int(existing["manual_approval_required"] or 0) == 1
        )
        if enabled is not None:
            next_enabled = bool(enabled)
        if manual_approval_required is not None:
            next_manual_approval_required = bool(manual_approval_required)

        now = isoformat_z(utc_now())
        self._execute(
            """
            INSERT INTO signal_strategy_settings (
                strategy_id, enabled, manual_approval_required, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(strategy_id) DO UPDATE SET
                enabled = excluded.enabled,
                manual_approval_required = excluded.manual_approval_required,
                updated_at = excluded.updated_at
            """,
            (
                int(strategy_id),
                1 if next_enabled else 0,
                1 if next_manual_approval_required else 0,
                now,
                now,
            ),
        )
        if enabled is not None and not next_enabled:
            self._execute(
                """
                UPDATE strategy_signals
                SET status = 'canceled', updated_at = ?
                WHERE strategy_id = ? AND status IN ('pending_approval', 'failed')
                """,
                (now, int(strategy_id)),
            )
            self._execute(
                """
                UPDATE signal_deliveries
                SET status = 'canceled', updated_at = ?
                WHERE signal_id IN (
                    SELECT id FROM strategy_signals WHERE strategy_id = ?
                )
                  AND status IN ('pending', 'approved', 'failed')
                """,
                (now, int(strategy_id)),
            )
        return self._strategy_setting_payload(int(strategy_id))

    def list_signal_strategies(self) -> List[Dict[str, Any]]:
        settings_rows = self._fetchall(
            """
            SELECT strategy_id, enabled, manual_approval_required, created_at, updated_at
            FROM signal_strategy_settings
            """
        )
        settings = {int(row["strategy_id"]): row for row in settings_rows}
        strategy_rows = self._strategy_rows_for_settings()
        if not strategy_rows:
            return [
                self._strategy_setting_payload(int(row["strategy_id"]))
                for row in settings_rows
            ]

        result: List[Dict[str, Any]] = []
        for row in strategy_rows:
            if not self._is_contract_strategy_row(row):
                continue
            strategy_id = int(row["id"])
            setting = settings.get(strategy_id)
            result.append(self._strategy_setting_payload(strategy_id, row=row, setting=setting))
        return result

    def _strategy_rows_for_settings(self) -> List[Any]:
        try:
            return self._fetchall(
                """
                SELECT id, name, status, exchange, symbols, config
                FROM strategies
                ORDER BY id DESC
                """
            )
        except Exception:
            return []

    def _strategy_row_by_id(self, strategy_id: int):
        try:
            return self._fetchone(
                """
                SELECT id, name, status, exchange, symbols, config
                FROM strategies
                WHERE id = ?
                """,
                (int(strategy_id),),
            )
        except Exception:
            return None

    def _strategy_setting_payload(
        self,
        strategy_id: int,
        *,
        row: Any = None,
        setting: Any = None,
    ) -> Dict[str, Any]:
        row = row or self._strategy_row_by_id(strategy_id)
        if setting is None:
            setting = self._fetchone(
                """
                SELECT strategy_id, enabled, manual_approval_required, created_at, updated_at
                FROM signal_strategy_settings
                WHERE strategy_id = ?
                """,
                (int(strategy_id),),
            )
        config = _json_loads(row["config"], {}) if row else {}
        if not isinstance(config, dict):
            config = {}
        symbols = _json_loads(row["symbols"], []) if row else []
        if isinstance(symbols, str):
            symbols = _normalize_list(symbols)
        metrics = self._runtime_strategy_metrics(strategy_id)
        return {
            "strategy_id": int(strategy_id),
            "strategy_name": str(row["name"] or "") if row else f"策略 #{strategy_id}",
            "signal_enabled": bool(setting and int(setting["enabled"] or 0) == 1),
            "manual_approval_required": bool(
                setting and int(setting["manual_approval_required"] or 0) == 1
            ),
            "status": str(row["status"] or "") if row else "",
            "exchange": str(row["exchange"] or "") if row else "",
            "symbols": symbols if isinstance(symbols, list) else [],
            "market_type": str(config.get("market_type") or ""),
            "total_pnl": metrics["total_pnl"],
            "return_pct": metrics["return_pct"],
            "updated_at": setting["updated_at"] if setting else None,
        }

    def _runtime_strategy_metrics(self, strategy_id: int) -> Dict[str, Optional[float]]:
        try:
            from app.services.strategy_engine import strategy_engine

            status = strategy_engine.get_strategy_status(int(strategy_id))
        except Exception as exc:
            logger.debug("signal strategy metric lookup failed for %s: %s", strategy_id, exc)
            status = None
        if not isinstance(status, dict):
            return {"total_pnl": None, "return_pct": None}
        return {
            "total_pnl": _safe_float(status.get("pnl")),
            "return_pct": _safe_float(status.get("return_pct")),
        }

    def _is_contract_strategy_row(self, row: Any) -> bool:
        name = str(row["name"] or "")
        config = _json_loads(row["config"], {})
        if not isinstance(config, dict):
            config = {}
        symbols = _json_loads(row["symbols"], [])
        if isinstance(symbols, str):
            symbols = _normalize_list(symbols)
        return (
            str(config.get("market_type") or "").lower() == "swap"
            or name.startswith("[合约]")
            or any(":USDT" in str(symbol).upper() or str(symbol).upper().endswith("-SWAP") for symbol in symbols or [])
        )

    def _row_to_signal(self, row: Any, *, include_deliveries: bool = True) -> Dict[str, Any]:
        payload_preview = _json_loads(row["okx_payload_preview"], {})
        raw_context = _json_loads(row["raw_context"], {})
        signal = {
            "id": row["id"],
            "signal_uid": row["signal_uid"],
            "strategy_id": row["strategy_id"],
            "strategy_name": row["strategy_name"],
            "symbol": row["symbol"],
            "okx_inst_id": row["okx_inst_id"],
            "market_type": row["market_type"],
            "action": row["action"],
            "price": row["price"],
            "suggested_investment_type": row["suggested_investment_type"],
            "suggested_amount": row["suggested_amount"],
            "reason": row["reason"],
            "confidence": row["confidence"],
            "risk_note": _normalize_risk_note(row["risk_note"]),
            "status": row["status"],
            "dedupe_key": row["dedupe_key"],
            "raw_context": raw_context,
            "okx_payload_preview": payload_preview,
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "updated_at": row["updated_at"],
        }
        if include_deliveries:
            signal["deliveries"] = self._list_deliveries(signal["id"])
        return signal

    def _row_to_channel(self, row: Any, *, reveal_secret: bool = False) -> Dict[str, Any]:
        allowed_strategy_ids = _json_loads(row["allowed_strategy_ids"], [])
        channel = {
            "id": row["id"],
            "name": row["name"],
            "enabled": bool(row["enabled"]),
            "allowed_strategy_ids": allowed_strategy_ids,
            "allowed_symbols": _json_loads(row["allowed_symbols"], []),
            "allowed_actions": _json_loads(row["allowed_actions"], []),
            "max_margin_usdt": row["max_margin_usdt"],
            "max_lag_sec": row["max_lag_sec"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "webhook_url": row["webhook_url"],
            "masked_webhook_url": _mask_webhook_url(row["webhook_url"]),
            "masked_signal_token": _mask_tail(row["signal_token"]),
            "signal_token": _mask_tail(row["signal_token"]),
        }
        if reveal_secret:
            channel["webhook_url"] = row["webhook_url"]
            channel["signal_token"] = row["signal_token"]
        return channel

    def _row_to_delivery(self, row: Any) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "signal_id": row["signal_id"],
            "channel_id": row["channel_id"],
            "status": row["status"],
            "request_payload": _json_loads(row["request_payload"], {}),
            "response_status": row["response_status"],
            "response_body": row["response_body"],
            "error": row["error"],
            "attempts": row["attempts"],
            "approved_at": row["approved_at"],
            "sent_at": row["sent_at"],
            "updated_at": row["updated_at"],
        }

    def _list_deliveries(self, signal_id: int) -> List[Dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT *
            FROM signal_deliveries
            WHERE signal_id = ?
            ORDER BY id ASC
            """,
            (signal_id,),
        )
        return [self._row_to_delivery(row) for row in rows]

    def _map_contract_action(self, action: str, side: str) -> str:
        normalized_action = (action or "").lower()
        normalized_side = (side or "").lower()
        if normalized_action == "open" and normalized_side == "long":
            return "ENTER_LONG"
        if normalized_action == "open" and normalized_side == "short":
            return "ENTER_SHORT"
        if normalized_action in {"close", "liquidation"} and normalized_side == "long":
            return "EXIT_LONG"
        if normalized_action in {"close", "liquidation"} and normalized_side == "short":
            return "EXIT_SHORT"
        raise ValueError(f"unsupported contract action: action={action}, side={side}")

    def record_contract_paper_signal(
        self,
        *,
        strategy_id: int,
        symbol: str,
        action: str,
        side: str,
        price: float,
        margin: float = 0.0,
        notional_usdt: float = 0.0,
        leverage: float = 1.0,
        ratio: Optional[float] = None,
        bar_ts_ms: Optional[int] = None,
        strategy_name: str = "",
        reason: str = "合约模拟盘成交生成待确认 OKX Signal Bot 信号",
        confidence: str = "paper_trade",
        risk_note: str = "",
        raw_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.is_strategy_signal_enabled(strategy_id):
            logger.debug("[SignalCenter] strategy_id=%s 未启用信号推送，跳过生成", strategy_id)
            return None
        okx_action = self._map_contract_action(action, side)
        okx_inst_id = okx_inst_id_from_contract_symbol(symbol)
        bar_time = int(bar_ts_ms or utc_now().timestamp() * 1000)
        dedupe_key = f"{strategy_id}:{symbol}:{okx_action}:{bar_time}"

        existing = self._fetchone(
            "SELECT * FROM strategy_signals WHERE dedupe_key = ?",
            (dedupe_key,),
        )
        if existing:
            return self._row_to_signal(existing)

        if okx_action.startswith("ENTER_"):
            suggested_type = "percentage_balance"
            amount = 100.0
        else:
            suggested_type = "percentage_position"
            close_ratio = 1.0 if ratio is None else max(0.0, min(float(ratio), 1.0))
            amount = close_ratio * 100.0

        created_at = utc_now()
        expires_at = created_at + timedelta(seconds=self.approval_ttl_sec)
        preview = _build_okx_signal_payload(
            action=okx_action,
            instrument=okx_inst_id,
            signal_token="<channel-signal-token>",
            timestamp=isoformat_z(created_at),
            max_lag_sec=self.default_max_lag_sec,
            investment_type=suggested_type,
            amount=amount,
        )
        raw = {
            "source": "contract_paper_trade",
            "side": side,
            "paper_action": action,
            "notional_usdt": notional_usdt,
            "margin": margin,
            "leverage": leverage,
            "ratio": ratio,
            "bar_ts_ms": bar_time,
            **(raw_context or {}),
        }

        cur = self._execute(
            """
            INSERT INTO strategy_signals (
                signal_uid, strategy_id, strategy_name, symbol, okx_inst_id,
                market_type, action, price, suggested_investment_type, suggested_amount,
                reason, confidence, risk_note, status, dedupe_key, raw_context,
                okx_payload_preview, created_at, expires_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'swap', ?, ?, ?, ?, ?, ?, ?, 'pending_approval', ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                int(strategy_id),
                self._strategy_name(int(strategy_id), strategy_name),
                symbol,
                okx_inst_id,
                okx_action,
                float(price or 0.0),
                suggested_type,
                round(float(amount), 8),
                reason,
                confidence,
                risk_note,
                dedupe_key,
                _json_dumps(raw),
                _json_dumps(preview),
                isoformat_z(created_at),
                isoformat_z(expires_at),
                isoformat_z(created_at),
            ),
        )
        row = self._fetchone("SELECT * FROM strategy_signals WHERE id = ?", (cur.lastrowid,))
        signal = self._row_to_signal(row)
        if not self.is_strategy_manual_approval_required(int(strategy_id)):
            return self._auto_approve_signal(signal)
        return signal

    def _auto_approve_signal(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        channel_ids = self._auto_channel_ids_for_signal(signal)
        if not channel_ids:
            logger.info(
                "[SignalCenter] strategy_id=%s signal_id=%s 自动发送未找到可用 Bot，保留待确认",
                signal["strategy_id"],
                signal["id"],
            )
            return signal

        async def runner() -> Dict[str, Any]:
            try:
                return await self.approve_signal(signal["id"], channel_ids)
            except Exception as exc:
                logger.warning(
                    "[SignalCenter] signal_id=%s 自动发送失败: %s",
                    signal["id"],
                    exc,
                )
                return self.get_signal(signal["id"])

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(runner())
        loop.create_task(runner())
        return signal

    def _auto_channel_ids_for_signal(self, signal: Dict[str, Any]) -> List[int]:
        strategy_id = int(signal["strategy_id"])
        channel_ids: List[int] = []
        for channel in self.list_channels():
            if not channel.get("enabled"):
                continue
            allowed_strategy_ids = [int(v) for v in channel.get("allowed_strategy_ids") or []]
            if allowed_strategy_ids == [-1]:
                continue
            if allowed_strategy_ids and strategy_id not in allowed_strategy_ids:
                continue
            channel_ids.append(int(channel["id"]))
        return channel_ids

    def list_signals(
        self,
        *,
        status: Optional[str] = None,
        strategy_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        self.expire_stale_signals()
        params: List[Any] = []
        where: List[str] = []
        joins = ""
        if status:
            where.append("s.status = ?")
            params.append(status)
        if strategy_id:
            where.append("s.strategy_id = ?")
            params.append(int(strategy_id))
        if channel_id:
            joins = "JOIN signal_deliveries d ON d.signal_id = s.id"
            where.append("d.channel_id = ?")
            params.append(int(channel_id))

        sql = f"SELECT DISTINCT s.* FROM strategy_signals s {joins}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY s.created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit or 50), 500)))
        rows = self._fetchall(sql, tuple(params))
        return [self._row_to_signal(row) for row in rows]

    def get_signal(self, signal_id: int) -> Dict[str, Any]:
        row = self._fetchone("SELECT * FROM strategy_signals WHERE id = ?", (int(signal_id),))
        if not row:
            raise ValueError("信号不存在")
        return self._row_to_signal(row)

    def create_channel(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        webhook_url = str(payload.get("webhook_url") or "").strip()
        signal_token = str(payload.get("signal_token") or "").strip()
        if not name:
            raise ValueError("通道名称不能为空")
        if not webhook_url:
            raise ValueError("webhook_url 不能为空")
        if not signal_token:
            raise ValueError("signal_token 不能为空")

        now = isoformat_z(utc_now())
        cur = self._execute(
            """
            INSERT INTO signal_channels (
                name, enabled, webhook_url, signal_token, allowed_strategy_ids,
                allowed_symbols, allowed_actions, max_margin_usdt, max_lag_sec,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                1 if payload.get("enabled", True) else 0,
                webhook_url,
                signal_token,
                _json_dumps([int(v) for v in _normalize_list(payload.get("allowed_strategy_ids"))]),
                _json_dumps(_normalize_list(payload.get("allowed_symbols"), upper=True)),
                _json_dumps(_normalize_actions(payload.get("allowed_actions"))),
                _optional_float(payload.get("max_margin_usdt", DEFAULT_SIGNAL_CHANNEL_MAX_MARGIN_USDT)),
                int(payload.get("max_lag_sec") or self.default_max_lag_sec),
                now,
                now,
            ),
        )
        return self._get_channel(cur.lastrowid)

    def update_channel(self, channel_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._get_channel(channel_id)
        fields: List[str] = []
        params: List[Any] = []
        mapping = {
            "name": lambda v: str(v).strip(),
            "enabled": lambda v: 1 if v else 0,
            "webhook_url": lambda v: str(v).strip(),
            "signal_token": lambda v: str(v).strip(),
            "allowed_strategy_ids": lambda v: _json_dumps([int(x) for x in _normalize_list(v)]),
            "allowed_symbols": lambda v: _json_dumps(_normalize_list(v, upper=True)),
            "allowed_actions": lambda v: _json_dumps(_normalize_actions(v)),
            "max_margin_usdt": _optional_float,
            "max_lag_sec": lambda v: int(v or self.default_max_lag_sec),
        }
        for key, converter in mapping.items():
            if key not in payload:
                continue
            fields.append(f"{key} = ?")
            params.append(converter(payload[key]))
        if not fields:
            return self._get_channel(channel_id)
        fields.append("updated_at = ?")
        params.append(isoformat_z(utc_now()))
        params.append(int(channel_id))
        self._execute(
            f"UPDATE signal_channels SET {', '.join(fields)} WHERE id = ?",
            tuple(params),
        )
        return self._get_channel(channel_id)

    def list_channels(self) -> List[Dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM signal_channels ORDER BY created_at DESC, id DESC")
        return [self._row_to_channel(row) for row in rows]

    def delete_channel(self, channel_id: int) -> Dict[str, Any]:
        channel = self._get_channel(channel_id)
        now = isoformat_z(utc_now())
        canceled = self._execute(
            """
            UPDATE signal_deliveries
            SET status = 'canceled', updated_at = ?
            WHERE channel_id = ? AND status IN ('pending', 'approved', 'failed')
            """,
            (now, int(channel_id)),
        )
        deleted = self._execute("DELETE FROM signal_channels WHERE id = ?", (int(channel_id),))
        if int(deleted.rowcount or 0) <= 0:
            raise ValueError("信号通道不存在")
        return {
            "deleted": True,
            "channel_id": int(channel_id),
            "channel_name": channel["name"],
            "canceled_deliveries": int(canceled.rowcount or 0),
        }

    def _get_channel(self, channel_id: int, *, reveal_secret: bool = False) -> Dict[str, Any]:
        row = self._fetchone("SELECT * FROM signal_channels WHERE id = ?", (int(channel_id),))
        if not row:
            raise ValueError("信号通道不存在")
        return self._row_to_channel(row, reveal_secret=reveal_secret)

    async def approve_signal(self, signal_id: int, channel_ids: Sequence[int]) -> Dict[str, Any]:
        if not channel_ids:
            raise ValueError("至少选择一个目标 Bot 通道")
        signal = self._load_active_signal(signal_id)
        for channel_id in channel_ids:
            channel = self._get_channel(channel_id, reveal_secret=True)
            validation_error = self._validate_channel(signal, channel)
            if validation_error:
                self._upsert_delivery(signal["id"], channel["id"], "failed", error=validation_error)
                continue
            preview = dict(signal["okx_payload_preview"])
            is_entry = str(signal["action"]).upper().startswith("ENTER_")
            payload = _build_okx_signal_payload(
                action=str(preview["action"]),
                instrument=str(preview["instrument"]),
                signal_token=str(channel["signal_token"]),
                timestamp=str(preview["timestamp"]),
                max_lag_sec=int(channel["max_lag_sec"] or self.default_max_lag_sec),
                investment_type="percentage_balance" if is_entry else "percentage_position",
                amount=100.0 if is_entry else float(signal["suggested_amount"] or 0.0),
            )
            self._upsert_delivery(signal["id"], channel["id"], "approved", request_payload=payload)
            try:
                response = await self._post_webhook(channel["webhook_url"], payload)
                status_code = int(response.get("status_code") or 0)
                if 200 <= status_code < 300:
                    self._upsert_delivery(
                        signal["id"],
                        channel["id"],
                        "sent",
                        request_payload=payload,
                        response_status=status_code,
                        response_body=str(response.get("body") or ""),
                        sent_at=isoformat_z(utc_now()),
                        increment_attempts=True,
                    )
                else:
                    self._upsert_delivery(
                        signal["id"],
                        channel["id"],
                        "failed",
                        request_payload=payload,
                        response_status=status_code,
                        response_body=str(response.get("body") or ""),
                        error=f"HTTP {status_code}",
                        increment_attempts=True,
                    )
            except Exception as exc:
                self._upsert_delivery(
                    signal["id"],
                    channel["id"],
                    "failed",
                    request_payload=payload,
                    error=str(exc),
                    increment_attempts=True,
                )

        return self._refresh_signal_status(signal["id"])

    def cancel_signal(self, signal_id: int) -> Dict[str, Any]:
        now = isoformat_z(utc_now())
        self._execute(
            """
            UPDATE strategy_signals
            SET status = 'canceled', updated_at = ?
            WHERE id = ? AND status IN ('pending_approval', 'failed')
            """,
            (now, int(signal_id)),
        )
        self._execute(
            """
            UPDATE signal_deliveries
            SET status = 'canceled', updated_at = ?
            WHERE signal_id = ? AND status IN ('pending', 'approved', 'failed')
            """,
            (now, int(signal_id)),
        )
        return self.get_signal(signal_id)

    async def retry_signal(self, signal_id: int) -> Dict[str, Any]:
        rows = self._fetchall(
            """
            SELECT channel_id
            FROM signal_deliveries
            WHERE signal_id = ? AND status = 'failed'
            ORDER BY id ASC
            """,
            (int(signal_id),),
        )
        channel_ids = [int(row["channel_id"]) for row in rows]
        if not channel_ids:
            raise ValueError("没有可重试的失败投递")
        return await self.approve_signal(signal_id, channel_ids)

    async def test_channel(
        self,
        channel_id: int,
        *,
        send: bool = False,
        action: str = "ENTER_LONG",
        instrument: str = "DOGE-USDT-SWAP",
        investment_type: str = "margin",
        amount: float = 0.1,
    ) -> Dict[str, Any]:
        channel = self._get_channel(channel_id, reveal_secret=True)
        action = str(action or "ENTER_LONG").strip().upper()
        instrument = str(instrument or "DOGE-USDT-SWAP").strip().upper()
        investment_type = str(investment_type or "margin").strip().lower()
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = 0.0

        valid_actions = {"ENTER_LONG", "ENTER_SHORT", "EXIT_LONG", "EXIT_SHORT"}
        valid_investment_types = {
            "base",
            "margin",
            "contract",
            "percentage_balance",
            "percentage_investment",
            "percentage_position",
        }
        if action not in valid_actions:
            raise ValueError("测试 action 无效")
        if not instrument:
            raise ValueError("测试 instrument 不能为空")
        if investment_type not in valid_investment_types:
            raise ValueError("测试 investmentType 无效")
        if amount <= 0:
            raise ValueError("测试 amount 必须大于 0")
        if action.startswith("ENTER_") and investment_type == "percentage_position":
            raise ValueError("开仓测试不能使用 percentage_position")
        if action.startswith("EXIT_") and investment_type not in {"base", "percentage_position"}:
            raise ValueError("平仓测试只支持 base 或 percentage_position")
        if send:
            if not channel.get("enabled"):
                raise ValueError("通道未启用，不能真实发送测试")
            allowed_actions = channel.get("allowed_actions") or []
            if allowed_actions and action not in allowed_actions:
                raise ValueError("测试 action 不在通道允许动作内")

        payload = _build_okx_signal_payload(
            action=action,
            instrument=instrument,
            signal_token=channel["signal_token"] if send else "<redacted>",
            timestamp=isoformat_z(utc_now()),
            max_lag_sec=int(channel["max_lag_sec"] or self.default_max_lag_sec),
            investment_type=investment_type,
            amount=amount,
        )
        if not send:
            return {"status": "dry_run", "payload": payload, "channel": self._get_channel(channel_id)}
        try:
            response = await self._post_webhook(channel["webhook_url"], payload)
        except httpx.RequestError as exc:
            logger.warning(
                "[SignalCenter] channel_id=%s 测试发送连接失败: %s",
                channel_id,
                exc,
            )
            return {
                "status": "failed",
                "payload": {**payload, "signalToken": "<redacted>"},
                "response_status": None,
                "response_body": f"{exc.__class__.__name__}: {exc}",
                "channel": self._get_channel(channel_id),
            }
        return {
            "status": "sent" if 200 <= int(response.get("status_code") or 0) < 300 else "failed",
            "payload": {**payload, "signalToken": "<redacted>"},
            "response_status": response.get("status_code"),
            "response_body": response.get("body"),
            "channel": self._get_channel(channel_id),
        }

    def expire_stale_signals(self) -> int:
        now = isoformat_z(utc_now())
        cur = self._execute(
            """
            UPDATE strategy_signals
            SET status = 'expired', updated_at = ?
            WHERE status IN ('pending_approval', 'failed') AND expires_at < ?
            """,
            (now, now),
        )
        self._execute(
            """
            UPDATE signal_deliveries
            SET status = 'expired', updated_at = ?
            WHERE signal_id IN (SELECT id FROM strategy_signals WHERE status = 'expired')
              AND status IN ('pending', 'approved', 'failed')
            """,
            (now,),
        )
        return int(cur.rowcount or 0)

    def _load_active_signal(self, signal_id: int) -> Dict[str, Any]:
        signal = self.get_signal(signal_id)
        if signal["status"] == "canceled":
            raise ValueError("信号已取消")
        if signal["status"] == "sent":
            raise ValueError("信号已发送")
        if not self.is_strategy_signal_enabled(int(signal["strategy_id"])):
            raise ValueError("策略未启用信号推送")
        if signal["status"] == "expired" or parse_iso_datetime(signal["expires_at"]) < utc_now():
            self._execute(
                "UPDATE strategy_signals SET status = 'expired', updated_at = ? WHERE id = ?",
                (isoformat_z(utc_now()), int(signal_id)),
            )
            raise ValueError("信号已过期")
        return signal

    def _validate_channel(self, signal: Dict[str, Any], channel: Dict[str, Any]) -> Optional[str]:
        if not channel["enabled"]:
            return "通道已禁用"
        allowed_strategy_ids = [int(v) for v in channel.get("allowed_strategy_ids") or []]
        if allowed_strategy_ids and int(signal["strategy_id"]) not in allowed_strategy_ids:
            return "策略不在通道白名单"
        allowed_symbols = [str(v).upper() for v in channel.get("allowed_symbols") or []]
        if allowed_symbols:
            symbol_options = {
                str(signal["symbol"]).upper(),
                str(signal["okx_inst_id"]).upper(),
            }
            if not symbol_options.intersection(allowed_symbols):
                return "交易品种不在通道白名单"
        allowed_actions = [str(v).upper() for v in channel.get("allowed_actions") or []]
        if allowed_actions and str(signal["action"]).upper() not in allowed_actions:
            return "交易动作不在通道白名单"
        max_margin = channel.get("max_margin_usdt")
        signal_margin = self._signal_margin_usdt(signal)
        if max_margin is not None and signal_margin is not None and signal_margin > float(max_margin):
            return "建议保证金超过通道最大保证金"
        return None

    def _signal_margin_usdt(self, signal: Dict[str, Any]) -> Optional[float]:
        if signal["suggested_investment_type"] == "margin":
            return float(signal["suggested_amount"] or 0.0)
        raw_context = signal.get("raw_context") or {}
        margin = raw_context.get("margin")
        if margin:
            return float(margin)
        notional = raw_context.get("notional_usdt")
        leverage = raw_context.get("leverage")
        if notional and leverage:
            return float(notional) / max(float(leverage), 1.0)
        return None

    def _upsert_delivery(
        self,
        signal_id: int,
        channel_id: int,
        status: str,
        *,
        request_payload: Optional[Dict[str, Any]] = None,
        response_status: Optional[int] = None,
        response_body: Optional[str] = None,
        error: Optional[str] = None,
        sent_at: Optional[str] = None,
        increment_attempts: bool = False,
    ) -> None:
        now = isoformat_z(utc_now())
        existing = self._fetchone(
            "SELECT * FROM signal_deliveries WHERE signal_id = ? AND channel_id = ?",
            (int(signal_id), int(channel_id)),
        )
        request_json = _json_dumps(request_payload) if request_payload is not None else None
        if existing:
            attempts = int(existing["attempts"] or 0) + (1 if increment_attempts else 0)
            self._execute(
                """
                UPDATE signal_deliveries
                SET status = ?, request_payload = COALESCE(?, request_payload),
                    response_status = ?, response_body = ?, error = ?,
                    attempts = ?, approved_at = COALESCE(approved_at, ?),
                    sent_at = COALESCE(?, sent_at), updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    request_json,
                    response_status,
                    response_body,
                    error,
                    attempts,
                    now if status in {"approved", "sent", "failed"} else None,
                    sent_at,
                    now,
                    existing["id"],
                ),
            )
        else:
            self._execute(
                """
                INSERT INTO signal_deliveries (
                    signal_id, channel_id, status, request_payload, response_status,
                    response_body, error, attempts, approved_at, sent_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(signal_id),
                    int(channel_id),
                    status,
                    request_json,
                    response_status,
                    response_body,
                    error,
                    1 if increment_attempts else 0,
                    now if status in {"approved", "sent", "failed"} else None,
                    sent_at,
                    now,
                ),
            )

    def _refresh_signal_status(self, signal_id: int) -> Dict[str, Any]:
        deliveries = self._list_deliveries(signal_id)
        if deliveries:
            statuses = {item["status"] for item in deliveries}
            if "sent" in statuses:
                status = "sent"
            elif statuses == {"expired"}:
                status = "expired"
            elif "failed" in statuses:
                status = "failed"
            else:
                status = "pending_approval"
            self._execute(
                "UPDATE strategy_signals SET status = ?, updated_at = ? WHERE id = ?",
                (status, isoformat_z(utc_now()), int(signal_id)),
            )
        return self.get_signal(signal_id)

    async def _post_webhook(self, webhook_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=payload)
        return {"status_code": response.status_code, "body": response.text}


def _normalize_actions(value: Any) -> List[str]:
    actions = _normalize_list(value, upper=True)
    invalid = [action for action in actions if action not in OKX_ACTIONS]
    if invalid:
        raise ValueError(f"unsupported OKX actions: {', '.join(invalid)}")
    return actions


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)


signal_center_service = SignalCenterService()
