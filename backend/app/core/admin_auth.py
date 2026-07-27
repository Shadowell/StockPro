import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime
import re
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

_BEARER = HTTPBearer(auto_error=False)


def _encode_json(data: dict[str, object]) -> str:
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_json(value: str) -> dict[str, object]:
    padding = "=" * (-len(value) % 4)
    raw = base64.urlsafe_b64decode(f"{value}{padding}")
    return json.loads(raw.decode("utf-8"))


def _sign(value: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), value.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _token_secret() -> str:
    return settings.ADMIN_TOKEN_SECRET or settings.ADMIN_PASSWORD


def _ensure_admin_configured() -> None:
    if not settings.ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin login is not configured.",
        )


def authenticate_admin(username: str, password: str) -> bool:
    _ensure_admin_configured()
    return secrets.compare_digest(username, settings.ADMIN_USERNAME) and secrets.compare_digest(
        password,
        settings.ADMIN_PASSWORD,
    )


def create_admin_token(username: str, now: int | None = None) -> str:
    _ensure_admin_configured()
    issued_at = int(time.time()) if now is None else now
    payload = {
        "sub": username,
        "role": "admin",
        "iat": issued_at,
        "exp": issued_at + settings.ADMIN_TOKEN_TTL_SECONDS,
    }
    encoded_payload = _encode_json(payload)
    signature = _sign(encoded_payload, _token_secret())
    return f"{encoded_payload}.{signature}"


def verify_admin_token(token: str, now: int | None = None) -> str:
    _ensure_admin_configured()
    try:
        encoded_payload, signature = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token.") from exc

    expected_signature = _sign(encoded_payload, _token_secret())
    if not secrets.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token.")

    try:
        payload = _decode_json(encoded_payload)
        username = str(payload["sub"])
        expires_at = int(payload["exp"])
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token.") from exc

    current_time = int(time.time()) if now is None else now
    if current_time >= expires_at:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin token has expired.")
    if not secrets.compare_digest(username, settings.ADMIN_USERNAME):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token.")

    return username


def create_guest_token(code: dict[str, Any], now: int | None = None) -> tuple[str, str]:
    _ensure_admin_configured()
    issued_at = int(time.time()) if now is None else now
    session_id = secrets.token_hex(16)
    expires_at = int(datetime.fromisoformat(str(code["expires_at"])).timestamp())
    payload = {
        "sub": f"guest:{code['id']}",
        "role": "guest",
        "guest_code_id": int(code["id"]),
        "session_id": session_id,
        "iat": issued_at,
        "exp": expires_at,
    }
    encoded_payload = _encode_json(payload)
    return f"{encoded_payload}.{_sign(encoded_payload, _token_secret())}", session_id


def verify_access_token(token: str, now: int | None = None) -> dict[str, Any]:
    _ensure_admin_configured()
    try:
        encoded_payload, signature = token.split(".", 1)
        if not secrets.compare_digest(signature, _sign(encoded_payload, _token_secret())):
            raise ValueError
        payload = _decode_json(encoded_payload)
        expires_at = int(payload["exp"])
        role = str(payload.get("role") or "admin")
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise HTTPException(status_code=401, detail="Invalid access token.") from exc
    current_time = int(time.time()) if now is None else now
    if current_time >= expires_at:
        raise HTTPException(status_code=401, detail="Access token has expired.")
    if role == "admin":
        username = str(payload.get("sub") or "")
        if not secrets.compare_digest(username, settings.ADMIN_USERNAME):
            raise HTTPException(status_code=401, detail="Invalid access token.")
        return {"role": "admin", "username": username, "permissions": ["read", "write", "admin"]}
    if role != "guest":
        raise HTTPException(status_code=401, detail="Invalid access token.")
    from app.db import db_instance
    from app.services.guest_access_service import GuestAccessError, GuestAccessService

    try:
        code = GuestAccessService(db_instance).get_active_code(int(payload["guest_code_id"]))
    except (GuestAccessError, KeyError, TypeError, ValueError) as exc:
        detail = str(exc) if isinstance(exc, GuestAccessError) else "Invalid access token."
        raise HTTPException(status_code=401, detail=detail) from exc
    return {
        "role": "guest",
        "guest_code_id": int(code["id"]),
        "session_id": str(payload["session_id"]),
        "expires_at": code["expires_at"],
        "permissions": ["read", "backtest:run"],
        "max_backtests_per_day": int(code["max_backtests_per_day"]),
        "max_concurrent_backtests": int(code["max_concurrent_backtests"]),
        "max_backtest_days": int(code["max_backtest_days"]),
    }


_GUEST_WRITE_PATHS = {
    "/api/backtest/quick-runs",
    "/api/backtest/runs",
    "/api/backtest/run",
}
_GUEST_JOB_WRITE_PATTERN = re.compile(
    r"^/api/backtest/jobs(?:/[0-9a-f-]+/(?:cancel|retry))?$"
)


def require_authenticated(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Login required.")
    principal = verify_access_token(credentials.credentials)
    if principal["role"] == "guest" and request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        if (
            request.url.path not in _GUEST_WRITE_PATHS
            and not _GUEST_JOB_WRITE_PATTERN.fullmatch(request.url.path)
        ):
            raise HTTPException(
                status_code=403,
                detail="访客账号为只读权限，仅允许在配额内运行回测。",
            )
    request.state.auth_principal = principal
    return principal


def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin login required.")
    principal = verify_access_token(credentials.credentials)
    if principal["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin permission required.")
    return str(principal["username"])
