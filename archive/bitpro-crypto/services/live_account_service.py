"""DB-backed live account registry.

The frontend only receives public metadata and masked API keys. Secret values
stay server-side and are only used to instantiate per-account exchange clients.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.errors import BadRequestError
from app.db.local_db import db_instance as db
from app.exchange.binance_usdm import BinanceUsdmExchange
from app.exchange.okx import OKXExchange


_SUPPORTED_LIVE_ACCOUNT_EXCHANGES = {"okx", "binanceusdm"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask_secret(value: Optional[str]) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) <= 8:
        return "*" * len(raw)
    return f"{raw[:4]}****{raw[-4:]}"


def _slug(value: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return out[:24] or "okx"


def _exchange_for_account(row: Dict[str, Any]) -> str:
    return str(row.get("exchange") or "okx").strip().lower() or "okx"


def normalize_account_id(account_id: Optional[str]) -> str:
    value = str(account_id or "default").strip() or "default"
    return "default" if value == "okx" else value


def ensure_live_accounts_table() -> None:
    conn = db.get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS live_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            exchange TEXT NOT NULL DEFAULT 'okx',
            api_key TEXT NOT NULL,
            api_secret TEXT NOT NULL,
            passphrase TEXT,
            testnet INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            can_trade INTEGER,
            permission_checked_at TEXT,
            permission_check_detail TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    existing = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(live_accounts)").fetchall()
    }
    for column, ddl in {
        "can_trade": "ALTER TABLE live_accounts ADD COLUMN can_trade INTEGER",
        "permission_checked_at": "ALTER TABLE live_accounts ADD COLUMN permission_checked_at TEXT",
        "permission_check_detail": "ALTER TABLE live_accounts ADD COLUMN permission_check_detail TEXT",
    }.items():
        if column not in existing:
            conn.execute(ddl)
    conn.commit()


def _default_account_payload(*, reveal_secret: bool = False) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "account_id": "default",
        "name": "默认 OKX 实盘账户",
        "exchange": "okx",
        "exchange_alias": "okx",
        "is_default": True,
        "enabled": True,
        "configured": bool(settings.OKX_API_KEY and settings.OKX_API_SECRET),
        "masked_api_key": _mask_secret(settings.OKX_API_KEY),
        "can_trade": None,
        "permission_checked_at": None,
        "permission_check_detail": None,
        "testnet": bool(settings.OKX_TESTNET),
        "created_at": None,
        "updated_at": None,
    }
    if reveal_secret:
        payload.update(
            {
                "api_key": settings.OKX_API_KEY or "",
                "api_secret": settings.OKX_API_SECRET or "",
                "passphrase": settings.OKX_PASSPHRASE or "",
            }
        )
    return payload


def _default_binance_account_payload(*, reveal_secret: bool = False) -> Dict[str, Any]:
    api_key = str(settings.BINANCE_API_KEY or "").strip()
    api_secret = str(settings.BINANCE_API_SECRET or "").strip()
    payload: Dict[str, Any] = {
        "account_id": "binance",
        "name": "默认 Binance USD-M 实盘账户",
        "exchange": "binanceusdm",
        "exchange_alias": "binanceusdm:binance",
        "is_default": True,
        "enabled": True,
        "configured": bool(api_key and api_secret),
        "display_only": bool(api_key and not api_secret),
        "masked_api_key": _mask_secret(api_key),
        "can_trade": None,
        "permission_checked_at": None,
        "permission_check_detail": "仅展示 API Key；配置 Secret 后才可进行只读账户校验",
        "testnet": bool(settings.BINANCE_TESTNET),
        "created_at": None,
        "updated_at": None,
    }
    if reveal_secret:
        payload.update(
            {
                "api_key": api_key,
                "api_secret": api_secret,
                "passphrase": "",
            }
        )
    return payload


def _row_to_public(row: Dict[str, Any], *, reveal_secret: bool = False) -> Dict[str, Any]:
    account_id = str(row.get("account_id") or "")
    exchange = _exchange_for_account(row)
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "name": str(row.get("name") or account_id),
        "exchange": exchange,
        "exchange_alias": f"{exchange}:{account_id}",
        "is_default": False,
        "enabled": bool(int(row.get("enabled") or 0)),
        "configured": bool(row.get("api_key") and row.get("api_secret")),
        "display_only": bool(row.get("api_key") and not row.get("api_secret")),
        "masked_api_key": _mask_secret(row.get("api_key")),
        "can_trade": None if row.get("can_trade") is None else bool(int(row.get("can_trade") or 0)),
        "permission_checked_at": row.get("permission_checked_at"),
        "permission_check_detail": row.get("permission_check_detail"),
        "testnet": bool(int(row.get("testnet") or 0)),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    if reveal_secret:
        payload.update(
            {
                "api_key": row.get("api_key") or "",
                "api_secret": row.get("api_secret") or "",
                "passphrase": row.get("passphrase") or "",
            }
        )
    return payload


def list_accounts() -> List[Dict[str, Any]]:
    ensure_live_accounts_table()
    conn = db.get_connection()
    rows = conn.execute(
        """
        SELECT account_id, name, exchange, api_key, api_secret, passphrase,
               testnet, enabled, can_trade, permission_checked_at,
               permission_check_detail, created_at, updated_at
        FROM live_accounts
        ORDER BY id ASC
        """
    ).fetchall()
    return [_default_account_payload(), _default_binance_account_payload()] + [_row_to_public(dict(row)) for row in rows]


def get_account(account_id: Optional[str], *, reveal_secret: bool = False) -> Optional[Dict[str, Any]]:
    normalized = normalize_account_id(account_id)
    if normalized == "default":
        return _default_account_payload(reveal_secret=reveal_secret)
    if normalized == "binance":
        return _default_binance_account_payload(reveal_secret=reveal_secret)

    ensure_live_accounts_table()
    conn = db.get_connection()
    row = conn.execute(
        """
        SELECT account_id, name, exchange, api_key, api_secret, passphrase,
               testnet, enabled, can_trade, permission_checked_at,
               permission_check_detail, created_at, updated_at
        FROM live_accounts
        WHERE account_id = ?
        """,
        (normalized,),
    ).fetchone()
    if not row:
        return None
    return _row_to_public(dict(row), reveal_secret=reveal_secret)


def validate_account_id(account_id: Optional[str]) -> str:
    normalized = normalize_account_id(account_id)
    account = get_account(normalized)
    if not account:
        raise BadRequestError("实盘账户不存在，请先在顶部账户区新增 API Key")
    if not account.get("enabled"):
        raise BadRequestError("实盘账户已禁用")
    return normalized


def validate_live_deployable_account_id(account_id: Optional[str]) -> str:
    normalized = validate_account_id(account_id)
    account = get_account(normalized) or {}
    exchange = _exchange_for_account(account)
    if exchange not in _SUPPORTED_LIVE_ACCOUNT_EXCHANGES:
        raise BadRequestError(f"不支持 {exchange} 实盘账户")
    if account.get("display_only"):
        raise BadRequestError("Binance API Key 已配置但 Secret Key 缺失；该账户仅用于展示，不能读取私有账户、绑定策略或实盘部署")
    return normalized


def _looks_like_permission_denied(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in (
            "permission",
            "permiss",
            "unauthorized",
            "not authorized",
            "authentication",
            "invalid sign",
            "invalid api",
            "api key",
            "apikey",
            "passphrase",
            "ip",
        )
    )


def _looks_like_missing_order(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in (
            "not exist",
            "doesn't exist",
            "not found",
            "no order",
            "order does not exist",
            "51603",
            "51604",
        )
    )


def validate_okx_account_permissions(
    *,
    api_key: str,
    api_secret: str,
    passphrase: Optional[str] = None,
    testnet: bool = False,
) -> Dict[str, Any]:
    """Validate that the key can read account state and reach a Trade endpoint.

    The Trade probe cancels a randomly generated client order ID that BitPro has
    never created. OKX requires Trade permission for this endpoint, but the probe
    does not place an order and cannot cancel a real order unless the same random
    client order ID already exists.
    """
    exchange = OKXExchange(
        {
            "api_key": api_key,
            "api_secret": api_secret,
            "passphrase": passphrase or "",
            "testnet": bool(testnet),
        }
    )
    exchange.initialize()

    try:
        exchange.exchange.fetch_balance({"type": "trading"})
    except Exception as exc:
        raise BadRequestError(f"账户 API 读取权限测试失败：{exc}") from exc

    # OKX clOrdId rejects underscores on some private trade endpoints.
    client_order_id = f"bpperm{secrets.token_hex(8)}"
    trade_payload = {
        "instId": "BTC-USDT",
        "clOrdId": client_order_id,
    }
    try:
        response = exchange.exchange.privatePostTradeCancelOrder(trade_payload)
        response_text = str(response)
        if _looks_like_permission_denied(response_text):
            raise BadRequestError("账户 API 交易权限测试失败：当前 API Key 缺少 Trade 权限或 IP 白名单不包含本服务器")
        response_code = str(response.get("code") or "") if isinstance(response, dict) else ""
        if response_code and response_code != "0" and not _looks_like_missing_order(response_text):
            raise BadRequestError(f"账户 API 交易权限测试失败：{response_text}")
    except BadRequestError:
        raise
    except Exception as exc:
        message = str(exc)
        if not _looks_like_missing_order(message) or _looks_like_permission_denied(message):
            raise BadRequestError(f"账户 API 交易权限测试失败：{message}") from exc

    return {
        "can_read": True,
        "can_trade": True,
        "checked_at": _now(),
        "detail": "读取权限和交易权限测试通过",
    }


def validate_binance_usdm_account_permissions(
    *,
    api_key: str,
    api_secret: str,
    testnet: bool = False,
) -> Dict[str, Any]:
    """Validate Binance USER_DATA and TRADE without submitting a real order."""
    exchange = BinanceUsdmExchange(
        {
            "api_key": api_key,
            "api_secret": api_secret,
            "testnet": bool(testnet),
        }
    )
    exchange.initialize()
    try:
        exchange.fetch_balance()
    except Exception as exc:
        raise BadRequestError(f"Binance USD-M 账户 API 读取权限测试失败：{exc}") from exc

    try:
        exchange.load_markets()
        market = exchange.exchange.market("BTC/USDT:USDT")
        amount_limits = ((market.get("limits") or {}).get("amount") or {})
        min_amount = amount_limits.get("min") or 0.001
        quantity = exchange.exchange.amount_to_precision("BTC/USDT:USDT", min_amount)
        payload = {
            "symbol": str(market.get("id") or "BTCUSDT"),
            "side": "BUY",
            "type": "MARKET",
            "quantity": str(quantity),
        }
        native = exchange.exchange
        position_mode = getattr(native, "fapiPrivateGetPositionSideDual", None)
        if callable(position_mode):
            mode_response = position_mode({})
            dual_side = mode_response.get("dualSidePosition") if isinstance(mode_response, dict) else False
            if isinstance(dual_side, str):
                dual_side = dual_side.strip().lower() == "true"
            if dual_side:
                payload["positionSide"] = "LONG"
        test_order = getattr(native, "fapiPrivatePostOrderTest", None)
        if not callable(test_order):
            raise BadRequestError("当前 CCXT 客户端未暴露 Binance USD-M order/test 权限探测接口")
        test_order(payload)
    except BadRequestError:
        raise
    except Exception as exc:
        raise BadRequestError(
            "Binance USD-M 账户 API 交易权限测试失败：当前 API Key 缺少 Futures Trade 权限、IP 白名单未包含本服务器，或请求签名无效："
            f"{exc}"
        ) from exc

    return {
        "can_read": True,
        "can_trade": True,
        "checked_at": _now(),
        "detail": "Binance USD-M 读取权限和非成交 Trade 权限测试通过",
    }


def _record_permission_check(account_id: str, *, can_trade: bool, checked_at: str, detail: str) -> None:
    normalized = normalize_account_id(account_id)
    if normalized in {"default", "binance"}:
        return
    ensure_live_accounts_table()
    conn = db.get_connection()
    conn.execute(
        """
        UPDATE live_accounts
        SET can_trade = ?, permission_checked_at = ?,
            permission_check_detail = ?, updated_at = ?
        WHERE account_id = ?
        """,
        (1 if can_trade else 0, checked_at, detail, checked_at, normalized),
    )
    conn.commit()


def validate_account_trade_permission(account_id: Optional[str]) -> Dict[str, Any]:
    """Re-run the selected account's non-executing read + Trade probe."""
    normalized = validate_account_id(account_id)
    account = get_account(normalized, reveal_secret=True)
    if not account:
        raise BadRequestError("实盘账户不存在，请先在顶部账户区新增 API Key")
    api_key = str(account.get("api_key") or "").strip()
    api_secret = str(account.get("api_secret") or "").strip()
    if not api_key or not api_secret:
        raise BadRequestError("实盘账户 API Key 或 Secret Key 未配置，无法测试交易权限")

    try:
        exchange = _exchange_for_account(account)
        if exchange == "okx":
            result = validate_okx_account_permissions(
                api_key=api_key,
                api_secret=api_secret,
                passphrase=str(account.get("passphrase") or ""),
                testnet=bool(account.get("testnet")),
            )
        elif exchange == "binanceusdm":
            result = validate_binance_usdm_account_permissions(
                api_key=api_key,
                api_secret=api_secret,
                testnet=bool(account.get("testnet")),
            )
        else:
            raise BadRequestError(f"不支持 {exchange} 实盘交易权限测试")
    except BadRequestError as exc:
        detail = str(exc)
        _record_permission_check(
            normalized,
            can_trade=False,
            checked_at=_now(),
            detail=detail,
        )
        raise

    _record_permission_check(
        normalized,
        can_trade=bool(result.get("can_trade")),
        checked_at=str(result.get("checked_at") or _now()),
        detail=str(result.get("detail") or ""),
    )
    return result


def create_account(
    *,
    name: str,
    exchange: str = "okx",
    api_key: str,
    api_secret: str,
    passphrase: Optional[str] = None,
    testnet: bool = False,
) -> Dict[str, Any]:
    clean_name = str(name or "").strip()
    clean_key = str(api_key or "").strip()
    clean_secret = str(api_secret or "").strip()
    clean_exchange = str(exchange or "okx").strip().lower()
    clean_passphrase = str(passphrase or "").strip()
    if not clean_name:
        raise BadRequestError("账户名称不能为空")
    if not clean_key or not clean_secret:
        raise BadRequestError("API Key 和 Secret Key 不能为空")
    if clean_exchange not in _SUPPORTED_LIVE_ACCOUNT_EXCHANGES:
        raise BadRequestError("仅支持 OKX 或 Binance USD-M 实盘账户")

    if clean_exchange == "okx":
        permission_check = validate_okx_account_permissions(
            api_key=clean_key,
            api_secret=clean_secret,
            passphrase=clean_passphrase,
            testnet=testnet,
        )
    else:
        clean_passphrase = ""
        permission_check = validate_binance_usdm_account_permissions(
            api_key=clean_key,
            api_secret=clean_secret,
            testnet=testnet,
        )

    ensure_live_accounts_table()
    now = permission_check["checked_at"]
    account_id = f"{clean_exchange}_{_slug(clean_name)}_{secrets.token_hex(3)}"
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO live_accounts (
            account_id, name, exchange, api_key, api_secret, passphrase,
            testnet, enabled, can_trade, permission_checked_at,
            permission_check_detail, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
        """,
        (
            account_id,
            clean_name,
            clean_exchange,
            clean_key,
            clean_secret,
            clean_passphrase,
            1 if testnet else 0,
            1 if permission_check["can_trade"] else 0,
            permission_check["checked_at"],
            permission_check["detail"],
            now,
            now,
        ),
    )
    conn.commit()
    account = get_account(account_id) or {}
    account["permission_check"] = permission_check
    return account


def get_exchange_config(account_id: Optional[str]) -> Dict[str, Any]:
    normalized = validate_account_id(account_id)
    account = get_account(normalized, reveal_secret=True)
    if not account:
        raise ValueError(f"Live account {normalized} not found")
    return {
        "exchange": account.get("exchange") or "okx",
        "api_key": account.get("api_key") or "",
        "api_secret": account.get("api_secret") or "",
        "passphrase": account.get("passphrase") or "",
        "testnet": bool(account.get("testnet")),
    }


def exchange_alias_for_account(account_id: Optional[str]) -> str:
    normalized = validate_account_id(account_id)
    account = get_account(normalized) or {}
    exchange = _exchange_for_account(account)
    if normalized == "default":
        return exchange
    if normalized == "binance":
        return "binanceusdm:binance"
    return f"{exchange}:{normalized}"
