"""Authentication and temporary guest-code access control."""
from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any

from argon2 import PasswordHasher

from app.db.local_db import LocalDatabase, db_instance


DEFAULT_ADMIN_SESSION_HOURS = 24 * 365 * 10


class AuthError(PermissionError):
    """Raised for authentication, authorization, and quota failures."""

    def __init__(self, message: str, *, status_code: int = 403) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthConfigError(RuntimeError):
    """Raised when auth is enabled but required admin configuration is missing."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self, db: LocalDatabase | None = None) -> None:
        self.db = db or db_instance
        self._hasher = PasswordHasher()

    def hash_password(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except Exception:
            return False

    def validate_admin_config(self, *, enabled: bool, username: str | None, password_hash: str | None) -> None:
        if enabled and (not str(username or "").strip() or not str(password_hash or "").strip()):
            raise AuthConfigError(
                "BITPRO_AUTH_ENABLED=1 requires BITPRO_ADMIN_USERNAME and BITPRO_ADMIN_PASSWORD_HASH."
            )

    def login_admin(
        self,
        *,
        username: str,
        password: str,
        expected_username: str,
        expected_password_hash: str,
        ip_address: str = "",
        user_agent: str = "",
        session_hours: int = DEFAULT_ADMIN_SESSION_HOURS,
    ) -> dict[str, Any]:
        if username != expected_username or not self.verify_password(password, expected_password_hash):
            self._audit("admin_login", role="admin", success=False, reason="invalid credentials", ip_address=ip_address, user_agent=user_agent)
            raise AuthError("管理员账号或密码错误", status_code=401)
        session = self._create_session(
            role="admin",
            guest_code_id=None,
            expires_at=_now() + timedelta(hours=max(1, int(session_hours or DEFAULT_ADMIN_SESSION_HOURS))),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._audit("admin_login", role="admin", session_id=session["session_id"], success=True, ip_address=ip_address, user_agent=user_agent)
        return session

    def create_guest_code(
        self,
        *,
        note: str = "",
        expires_in_minutes: int = 60,
        max_backtests_per_day: int = 10,
        max_concurrent_backtests: int = 1,
        max_backtest_days: int = 365,
        created_by: str = "admin",
    ) -> dict[str, Any]:
        code = f"BP-{secrets.token_urlsafe(9).replace('_', '').replace('-', '').upper()}"
        expires_at = _now() + timedelta(minutes=max(1, int(expires_in_minutes or 60)))
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO guest_access_codes
            (code_hash, note, expires_at, max_backtests_per_day, max_concurrent_backtests,
             max_backtest_days, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _hash_secret(code),
                str(note or "").strip(),
                _iso(expires_at),
                max(0, int(max_backtests_per_day or 0)),
                max(1, int(max_concurrent_backtests or 1)),
                max(1, int(max_backtest_days or 365)),
                str(created_by or "admin"),
                _iso(_now()),
            ),
        )
        code_id = int(cur.lastrowid)
        conn.commit()
        self._audit("guest_code_created", role="admin", guest_code_id=code_id, success=True)
        return {
            "id": code_id,
            "code": code,
            "note": str(note or "").strip(),
            "expires_at": _iso(expires_at),
            "max_backtests_per_day": max(0, int(max_backtests_per_day or 0)),
            "max_concurrent_backtests": max(1, int(max_concurrent_backtests or 1)),
            "max_backtest_days": max(1, int(max_backtest_days or 365)),
            "revoked_at": None,
        }

    def list_guest_codes(self) -> list[dict[str, Any]]:
        rows = self.db.get_connection().execute(
            """
            SELECT id, note, expires_at, max_backtests_per_day, max_concurrent_backtests,
                   max_backtest_days, created_by, created_at, last_used_at, revoked_at
            FROM guest_access_codes
            WHERE revoked_at IS NULL
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def revoke_guest_code(self, code_id: int) -> dict[str, Any]:
        revoked_at = _iso(_now())
        conn = self.db.get_connection()
        conn.execute("UPDATE guest_access_codes SET revoked_at = ? WHERE id = ?", (revoked_at, int(code_id)))
        conn.execute(
            "UPDATE auth_sessions SET revoked_at = ? WHERE role = 'guest' AND guest_code_id = ? AND revoked_at IS NULL",
            (revoked_at, int(code_id)),
        )
        conn.commit()
        self._audit("guest_code_revoked", role="admin", guest_code_id=int(code_id), success=True)
        return {"id": int(code_id), "revoked_at": revoked_at}

    def login_guest(
        self,
        code: str,
        *,
        ip_address: str = "",
        user_agent: str = "",
    ) -> dict[str, Any]:
        code_hash = _hash_secret(str(code or "").strip())
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM guest_access_codes WHERE code_hash = ?",
            (code_hash,),
        ).fetchone()
        if not row:
            self._audit("guest_login", role="guest", success=False, reason="invalid code", ip_address=ip_address, user_agent=user_agent)
            raise AuthError("邀请码无效", status_code=401)
        if row["revoked_at"]:
            self._audit(
                "guest_login",
                role="guest",
                guest_code_id=int(row["id"]),
                success=False,
                reason="revoked code",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise AuthError("邀请码已撤销", status_code=401)
        expires_at = _parse_dt(row["expires_at"])
        if expires_at <= _now():
            self._audit(
                "guest_login",
                role="guest",
                guest_code_id=int(row["id"]),
                success=False,
                reason="expired code",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise AuthError("邀请码已过期", status_code=401)
        session_expires = expires_at
        session = self._create_session(
            role="guest",
            guest_code_id=int(row["id"]),
            expires_at=session_expires,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        conn.execute("UPDATE guest_access_codes SET last_used_at = ? WHERE id = ?", (_iso(_now()), int(row["id"])))
        conn.commit()
        session.update(
            {
                "guest_code_id": int(row["id"]),
                "max_backtests_per_day": int(row["max_backtests_per_day"] or 0),
                "max_concurrent_backtests": int(row["max_concurrent_backtests"] or 1),
                "max_backtest_days": int(row["max_backtest_days"] or 365),
            }
        )
        self._audit("guest_login", role="guest", session_id=session["session_id"], guest_code_id=int(row["id"]), success=True, ip_address=ip_address, user_agent=user_agent)
        return session

    def get_session(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        row = self.db.get_connection().execute(
            "SELECT * FROM auth_sessions WHERE session_hash = ?",
            (_hash_secret(token),),
        ).fetchone()
        if not row or row["revoked_at"]:
            return None
        if _parse_dt(row["expires_at"]) <= _now():
            return None
        session = dict(row)
        session["session_id"] = session.pop("id")
        session["authenticated"] = True
        self.db.get_connection().execute(
            "UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?",
            (_iso(_now()), session["session_id"]),
        )
        self.db.get_connection().commit()
        if session["role"] == "guest" and session.get("guest_code_id"):
            code = self._guest_code(int(session["guest_code_id"]))
            if code:
                session.update(
                    {
                        "max_backtests_per_day": int(code["max_backtests_per_day"] or 0),
                        "max_concurrent_backtests": int(code["max_concurrent_backtests"] or 1),
                        "max_backtest_days": int(code["max_backtest_days"] or 365),
                        "guest_code_revoked_at": code["revoked_at"],
                        "guest_code_expires_at": code["expires_at"],
                    }
                )
        return session

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE auth_sessions SET revoked_at = ? WHERE session_hash = ?",
            (_iso(_now()), _hash_secret(token)),
        )
        conn.commit()

    def check_guest_backtest_quota(self, session: dict[str, Any], *, start_date: str, end_date: str) -> None:
        if session.get("role") != "guest":
            return
        guest_code_id = int(session.get("guest_code_id") or 0)

        def reject(message: str) -> None:
            self._audit(
                "guest_backtest_quota_rejected",
                role="guest",
                session_id=session.get("session_id"),
                guest_code_id=guest_code_id or None,
                success=False,
                reason=message,
            )
            raise AuthError(message)

        code = self._guest_code(guest_code_id)
        if not code or code["revoked_at"]:
            reject("邀请码已撤销")
        if _parse_dt(code["expires_at"]) <= _now():
            reject("邀请码已过期")
        start = date.fromisoformat(str(start_date))
        end = date.fromisoformat(str(end_date))
        max_days = int(code["max_backtest_days"] or 365)
        if (end - start).days > max_days:
            reject(f"访客邀请码最长回测区间为 {max_days} 天")

        conn = self.db.get_connection()
        running = conn.execute(
            """
            SELECT COUNT(*) AS count FROM backtest_jobs
            WHERE owner_role = 'guest'
              AND owner_guest_code_id = ?
              AND status IN ('pending', 'running', 'cancelling')
            """,
            (guest_code_id,),
        ).fetchone()["count"]
        max_concurrent = int(code["max_concurrent_backtests"] or 1)
        if int(running or 0) >= max_concurrent:
            reject(f"访客邀请码并发回测上限为 {max_concurrent} 个")

        daily = conn.execute(
            """
            SELECT COUNT(*) AS count FROM backtest_jobs
            WHERE owner_role = 'guest'
              AND owner_guest_code_id = ?
              AND date(created_at) = date('now')
            """,
            (guest_code_id,),
        ).fetchone()["count"]
        max_daily = int(code["max_backtests_per_day"] or 0)
        if max_daily and int(daily or 0) >= max_daily:
            reject(f"访客邀请码每日回测上限为 {max_daily} 次")

    def record_guest_backtest_job(self, session: dict[str, Any], job_id: str) -> None:
        if session.get("role") != "guest":
            return
        conn = self.db.get_connection()
        conn.execute(
            """
            UPDATE backtest_jobs
            SET owner_role = 'guest', owner_session_id = ?, owner_guest_code_id = ?
            WHERE job_id = ?
            """,
            (session.get("session_id"), int(session.get("guest_code_id") or 0), job_id),
        )
        conn.commit()

    def _guest_code(self, code_id: int) -> dict[str, Any] | None:
        row = self.db.get_connection().execute(
            "SELECT * FROM guest_access_codes WHERE id = ?",
            (int(code_id),),
        ).fetchone()
        return dict(row) if row else None

    def _create_session(
        self,
        *,
        role: str,
        guest_code_id: int | None,
        expires_at: datetime,
        ip_address: str,
        user_agent: str,
    ) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        session_id = secrets.token_hex(16)
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO auth_sessions
            (id, session_hash, role, guest_code_id, expires_at, ip_address, user_agent, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                _hash_secret(token),
                role,
                guest_code_id,
                _iso(expires_at),
                ip_address,
                user_agent[:500],
                _iso(_now()),
                _iso(_now()),
            ),
        )
        conn.commit()
        max_age = max(60, int((expires_at - _now()).total_seconds()))
        return {
            "token": token,
            "session_id": session_id,
            "role": role,
            "guest_code_id": guest_code_id,
            "expires_at": _iso(expires_at),
            "max_age": max_age,
            "authenticated": True,
        }

    def _audit(
        self,
        event_type: str,
        *,
        role: str | None = None,
        session_id: str | None = None,
        guest_code_id: int | None = None,
        success: bool,
        reason: str | None = None,
        ip_address: str = "",
        user_agent: str = "",
    ) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO auth_audit_events
            (event_type, role, session_id, guest_code_id, success, reason, ip_address, user_agent, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (event_type, role, session_id, guest_code_id, 1 if success else 0, reason, ip_address, user_agent[:500], _iso(_now())),
        )
        conn.commit()


auth_service = AuthService()
