from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile, AuthToken


class AuthError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


def _encode_json(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_json(value: str) -> dict[str, Any]:
    padding = "=" * (-len(value) % 4)
    raw = base64.urlsafe_b64decode(f"{value}{padding}")
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("token payload must be an object")
    return decoded


class AuthService:
    def __init__(self, context: AppContext) -> None:
        self.context = context
        self.settings = context.settings
        self.repository = context.repositories.auth

    def _now(self) -> datetime:
        now = self.context.clock()
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)

    def _configured_secret(self) -> str:
        secret = str(getattr(self.settings, "ADMIN_TOKEN_SECRET", "") or "")
        if len(secret) < 32:
            raise AuthError("Authentication is not configured.", status_code=503)
        return secret

    def _configured_password(self) -> str:
        password = str(getattr(self.settings, "ADMIN_PASSWORD", "") or "")
        if not password:
            raise AuthError("Authentication is not configured.", status_code=503)
        return password

    def _sign(self, encoded_payload: str) -> str:
        digest = hmac.new(
            self._configured_secret().encode("utf-8"),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def _issue(
        self,
        *,
        role: str,
        subject: str,
        session_id: str,
        expires_at: datetime,
        guest_code_id: int | None = None,
    ) -> AuthToken:
        now = self._now()
        payload: dict[str, object] = {
            "sub": subject,
            "role": role,
            "sid": session_id,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        if guest_code_id is not None:
            payload["guest_code_id"] = guest_code_id
        encoded = _encode_json(payload)
        return AuthToken(
            access_token=f"{encoded}.{self._sign(encoded)}",
            token_type="bearer",
            expires_in=max(0, int((expires_at - now).total_seconds())),
        )

    def _audit(
        self,
        *,
        event_type: str,
        role: str,
        subject_id: str | None,
        guest_code_id: int | None,
        success: bool,
        reason: str | None,
    ) -> None:
        self.repository.record_auth_event(
            event_type=event_type,
            role=role,
            subject_id=subject_id,
            guest_code_id=guest_code_id,
            success=success,
            reason=reason,
            metadata={"contract": "current", "runtime_mode": "ashare_paper"},
        )

    def login_admin(self, username: str, password: str) -> tuple[AuthToken, AuthProfile]:
        configured_username = str(getattr(self.settings, "ADMIN_USERNAME", "admin"))
        configured_password = self._configured_password()
        valid = secrets.compare_digest(username, configured_username) and secrets.compare_digest(
            password,
            configured_password,
        )
        if not valid:
            self._audit(
                event_type="admin_login",
                role="admin",
                subject_id=configured_username,
                guest_code_id=None,
                success=False,
                reason="invalid_credentials",
            )
            raise AuthError("Invalid credentials.")

        now = self._now()
        ttl = int(getattr(self.settings, "AUTH_TOKEN_TTL_SECONDS", 86_400))
        if ttl < 300 or ttl > 31_536_000:
            raise AuthError("Authentication is not configured.", status_code=503)
        expires_at = datetime.fromtimestamp(int(now.timestamp()) + ttl, tz=timezone.utc)
        session_id = secrets.token_hex(16)
        token = self._issue(
            role="admin",
            subject=configured_username,
            session_id=session_id,
            expires_at=expires_at,
        )
        profile = AuthProfile(
            role="admin",
            username=configured_username,
            permissions=("read", "write", "admin"),
            session_id=session_id,
            expires_at=expires_at.isoformat(),
        )
        self._audit(
            event_type="admin_login",
            role="admin",
            subject_id=configured_username,
            guest_code_id=None,
            success=True,
            reason=None,
        )
        return token, profile

    def login_guest(self, code: str) -> tuple[AuthToken, AuthProfile]:
        normalized = code.strip()
        if not normalized or len(normalized) > 128:
            raise AuthError("Invalid credentials.")
        code_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        now = self._now()
        record = self.repository.get_active_guest_code(code_hash, now)
        if not record:
            self._audit(
                event_type="guest_login",
                role="guest",
                subject_id=None,
                guest_code_id=None,
                success=False,
                reason="invalid_guest_code",
            )
            raise AuthError("Invalid credentials.")

        code_id = int(record["id"])
        raw_expiry = record["expires_at"]
        expires_at = (
            raw_expiry
            if isinstance(raw_expiry, datetime)
            else datetime.fromisoformat(str(raw_expiry))
        )
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        session_id = secrets.token_hex(16)
        token = self._issue(
            role="guest",
            subject=f"guest:{code_id}",
            session_id=session_id,
            expires_at=expires_at,
            guest_code_id=code_id,
        )
        profile = AuthProfile(
            role="guest",
            username=None,
            permissions=("read", "backtest:run"),
            session_id=session_id,
            expires_at=expires_at.isoformat(),
            guest_code_id=code_id,
            max_backtests_per_day=int(record["max_backtests_per_day"]),
            max_concurrent_backtests=int(record["max_concurrent_backtests"]),
            max_backtest_days=int(record["max_backtest_days"]),
        )
        self.repository.touch_guest_code(code_id, now)
        self._audit(
            event_type="guest_login",
            role="guest",
            subject_id=f"guest:{code_id}",
            guest_code_id=code_id,
            success=True,
            reason=None,
        )
        return token, profile

    def resolve(self, token: str) -> AuthProfile:
        try:
            encoded, signature = token.split(".", 1)
            if not secrets.compare_digest(signature, self._sign(encoded)):
                raise ValueError("signature")
            payload = _decode_json(encoded)
            expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
            if self._now() >= expires_at:
                raise ValueError("expired")
            role = str(payload["role"])
            session_id = str(payload["sid"])
        except (ValueError, KeyError, TypeError, UnicodeDecodeError, binascii.Error) as error:
            raise AuthError("Invalid or expired access token.") from error

        if role == "admin":
            username = str(payload.get("sub") or "")
            if not secrets.compare_digest(
                username,
                str(getattr(self.settings, "ADMIN_USERNAME", "admin")),
            ):
                raise AuthError("Invalid or expired access token.")
            return AuthProfile(
                role="admin",
                username=username,
                permissions=("read", "write", "admin"),
                session_id=session_id,
                expires_at=expires_at.isoformat(),
            )
        if role != "guest":
            raise AuthError("Invalid or expired access token.")

        code_id = int(payload.get("guest_code_id") or 0)
        # Guest tokens do not contain the plaintext invite code. Resolve by ID so
        # revocation remains authoritative without storing or recovering the code.
        record = self.repository.get_active_guest_code_by_id(code_id, self._now())
        if not record:
            raise AuthError("Invalid or expired access token.")
        return AuthProfile(
            role="guest",
            username=None,
            permissions=("read", "backtest:run"),
            session_id=session_id,
            expires_at=expires_at.isoformat(),
            guest_code_id=code_id,
            max_backtests_per_day=int(record["max_backtests_per_day"]),
            max_concurrent_backtests=int(record["max_concurrent_backtests"]),
            max_backtest_days=int(record["max_backtest_days"]),
        )


def auth_response(token: AuthToken, profile: AuthProfile) -> dict[str, object]:
    return {
        **asdict(token),
        **asdict(profile),
        "auth_enabled": True,
        "authenticated": True,
    }
