"""Stateless signed sessions backed by PostgreSQL guest and audit facts."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from argon2 import PasswordHasher

from app.core.config import settings
from app.domain.auth.repository import PostgresAuthRepository


class ActiveAuthError(PermissionError):
    def __init__(self, message: str, *, status_code: int = 403) -> None:
        super().__init__(message)
        self.status_code = status_code


class ActiveAuthConfigError(RuntimeError):
    pass


def _encode(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(value: str) -> dict[str, Any]:
    raw = base64.urlsafe_b64decode(f"{value}{'=' * (-len(value) % 4)}")
    payload = json.loads(raw.decode())
    if not isinstance(payload, dict):
        raise ValueError("invalid token payload")
    return payload


class ActiveAuthService:
    def __init__(self, repository: PostgresAuthRepository | None = None, *, clock: Callable[[], datetime] | None = None) -> None:
        self.repository = repository or PostgresAuthRepository()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._hasher = PasswordHasher()

    def _now(self) -> datetime:
        current = self.clock()
        return current if current.tzinfo else current.replace(tzinfo=timezone.utc)

    @staticmethod
    def hash_password(password: str) -> str:
        return PasswordHasher().hash(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except Exception:
            return False

    @staticmethod
    def validate_admin_config(*, enabled: bool, username: str | None, password_hash: str | None) -> None:
        if enabled and (not str(username or "").strip() or not str(password_hash or "").strip()):
            raise ActiveAuthConfigError("BITPRO_AUTH_ENABLED=1 requires admin credentials")

    @staticmethod
    def _secret() -> str:
        secret = str(settings.BITPRO_AUTH_TOKEN_SECRET or settings.BITPRO_ADMIN_PASSWORD_HASH or "")
        if len(secret) < 32:
            raise ActiveAuthError("认证签名密钥未配置", status_code=503)
        return secret

    def _sign(self, encoded: str) -> str:
        digest = hmac.new(self._secret().encode(), encoded.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def _issue(self, *, role: str, subject: str, session_id: str, expires_at: datetime, guest_code_id: int | None = None) -> str:
        payload = {"sub": subject, "role": role, "sid": session_id, "iat": int(self._now().timestamp()), "exp": int(expires_at.timestamp())}
        if guest_code_id is not None:
            payload["guest_code_id"] = guest_code_id
        encoded = _encode(payload)
        return f"{encoded}.{self._sign(encoded)}"

    def _audit(self, event_type: str, *, role: str, subject_id: str | None = None, guest_code_id: int | None = None, success: bool, reason: str | None = None, ip_address: str = "", user_agent: str = "") -> None:
        self.repository.record_event(
            event_type=event_type, role=role, subject_id=subject_id, guest_code_id=guest_code_id,
            success=success, reason=reason,
            metadata={"contract": "stockpro.v1", "ip_address": ip_address, "user_agent": user_agent[:200]},
        )

    def login_admin(self, *, username: str, password: str, expected_username: str, expected_password_hash: str, ip_address: str = "", user_agent: str = "", session_hours: int = 24) -> dict:
        if not secrets.compare_digest(username, expected_username) or not self.verify_password(password, expected_password_hash):
            self._audit("admin_login", role="admin", subject_id=expected_username, success=False, reason="invalid_credentials", ip_address=ip_address, user_agent=user_agent)
            raise ActiveAuthError("管理员账号或密码错误", status_code=401)
        now = self._now(); expires_at = now + timedelta(hours=max(1, int(session_hours)))
        session_id = secrets.token_hex(16); token = self._issue(role="admin", subject=username, session_id=session_id, expires_at=expires_at)
        self._audit("admin_login", role="admin", subject_id=username, success=True, ip_address=ip_address, user_agent=user_agent)
        return {"token": token, "session_id": session_id, "role": "admin", "expires_at": expires_at.isoformat(), "max_age": max(60, int((expires_at-now).total_seconds())), "authenticated": True}

    def create_guest_code(self, *, note: str = "", expires_in_minutes: int = 60, max_backtests_per_day: int = 10, max_concurrent_backtests: int = 1, max_backtest_days: int = 365, created_by: str = "admin") -> dict:
        code = f"BP-{secrets.token_urlsafe(9).replace('_', '').replace('-', '').upper()}"
        expires_at = self._now() + timedelta(minutes=max(1, int(expires_in_minutes)))
        row = self.repository.create_guest_code(
            code_hash=hashlib.sha256(code.encode()).hexdigest(), note=str(note or "").strip(), expires_at=expires_at,
            max_backtests_per_day=max(0, int(max_backtests_per_day)), max_concurrent_backtests=max(1, int(max_concurrent_backtests)),
            max_backtest_days=max(1, int(max_backtest_days)), created_by=str(created_by or "admin"),
        )
        self._audit("guest_code_created", role="admin", guest_code_id=int(row["id"]), success=True)
        return {
            "id": int(row["id"]), "code": code, "note": row.get("note") or "",
            "expires_at": row["expires_at"], "max_backtests_per_day": int(row["max_backtests_per_day"]),
            "max_concurrent_backtests": int(row["max_concurrent_backtests"]),
            "max_backtest_days": int(row["max_backtest_days"]), "revoked_at": row.get("revoked_at"),
        }

    def list_guest_codes(self) -> list[dict]:
        return self.repository.list_guest_codes()

    def revoke_guest_code(self, code_id: int) -> dict:
        row = self.repository.revoke_guest_code(code_id, self._now())
        self._audit("guest_code_revoked", role="admin", guest_code_id=int(code_id), success=True)
        return row

    def login_guest(self, code: str, *, ip_address: str = "", user_agent: str = "") -> dict:
        normalized = str(code or "").strip()
        row = self.repository.active_guest_code(code_hash=hashlib.sha256(normalized.encode()).hexdigest(), now=self._now()) if normalized else None
        if not row:
            self._audit("guest_login", role="guest", success=False, reason="invalid_guest_code", ip_address=ip_address, user_agent=user_agent)
            raise ActiveAuthError("邀请码无效、已撤销或已过期", status_code=401)
        expires_at = row["expires_at"] if isinstance(row["expires_at"], datetime) else datetime.fromisoformat(str(row["expires_at"]))
        if expires_at.tzinfo is None: expires_at = expires_at.replace(tzinfo=timezone.utc)
        code_id = int(row["id"]); session_id = secrets.token_hex(16)
        token = self._issue(role="guest", subject=f"guest:{code_id}", session_id=session_id, expires_at=expires_at, guest_code_id=code_id)
        self.repository.touch_guest_code(code_id, self._now())
        self._audit("guest_login", role="guest", subject_id=session_id, guest_code_id=code_id, success=True, ip_address=ip_address, user_agent=user_agent)
        return {"token": token, "session_id": session_id, "role": "guest", "guest_code_id": code_id, "expires_at": expires_at.isoformat(), "max_age": max(60, int((expires_at-self._now()).total_seconds())), "authenticated": True, "max_backtests_per_day": int(row["max_backtests_per_day"]), "max_concurrent_backtests": int(row["max_concurrent_backtests"]), "max_backtest_days": int(row["max_backtest_days"])}

    def _token_payload(self, token: str, *, require_active: bool) -> dict:
        try:
            encoded, signature = token.split(".", 1)
            if not secrets.compare_digest(signature, self._sign(encoded)): raise ValueError("signature")
            payload = _decode(encoded)
            if require_active and self._now().timestamp() >= int(payload["exp"]): raise ValueError("expired")
            if self.repository.session_revoked(str(payload["sid"])): raise ValueError("revoked")
            return payload
        except (ValueError, KeyError, TypeError, UnicodeDecodeError, binascii.Error) as exc:
            raise ActiveAuthError("会话无效或已过期", status_code=401) from exc

    def get_session(self, token: str | None) -> dict | None:
        if not token: return None
        try: payload = self._token_payload(token, require_active=True)
        except ActiveAuthError: return None
        role = str(payload.get("role") or ""); session_id = str(payload["sid"]); expires_at = datetime.fromtimestamp(int(payload["exp"]),tz=timezone.utc)
        if role == "admin" and secrets.compare_digest(str(payload.get("sub") or ""), str(settings.BITPRO_ADMIN_USERNAME or "")):
            return {"authenticated": True, "role": "admin", "session_id": session_id, "expires_at": expires_at.isoformat()}
        if role != "guest": return None
        code_id = int(payload.get("guest_code_id") or 0); row = self.repository.active_guest_code(code_id=code_id, now=self._now())
        if not row: return None
        return {"authenticated": True, "role": "guest", "session_id": session_id, "guest_code_id": code_id, "expires_at": expires_at.isoformat(), "max_backtests_per_day": int(row["max_backtests_per_day"]), "max_concurrent_backtests": int(row["max_concurrent_backtests"]), "max_backtest_days": int(row["max_backtest_days"])}

    def revoke_session(self, token: str | None) -> None:
        if not token: return
        try: payload = self._token_payload(token, require_active=False)
        except ActiveAuthError: return
        self._audit("session_revoked", role=str(payload.get("role") or "guest"), subject_id=str(payload["sid"]), guest_code_id=int(payload.get("guest_code_id") or 0) or None, success=True)


active_auth_service = ActiveAuthService()
