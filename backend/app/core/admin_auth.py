import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from typing import Annotated

from fastapi import Depends, HTTPException, status
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


def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin login required.")
    return verify_admin_token(credentials.credentials)
