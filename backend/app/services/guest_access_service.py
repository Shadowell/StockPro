from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

import psycopg2.extras


class GuestAccessError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


class GuestAccessService:
    def __init__(self, database) -> None:
        self.database = database

    def create_code(
        self,
        *,
        note: str,
        expires_in_minutes: int,
        max_backtests_per_day: int,
        max_concurrent_backtests: int,
        max_backtest_days: int,
        created_by: str,
    ) -> dict[str, Any]:
        code = f"SP-{secrets.token_urlsafe(9).replace('_', '').replace('-', '').upper()}"
        expires_at = _now() + timedelta(minutes=expires_in_minutes)
        with self.database.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO guest_access_codes
                        (code_hash, note, expires_at, max_backtests_per_day,
                         max_concurrent_backtests, max_backtest_days, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, note, expires_at, max_backtests_per_day,
                              max_concurrent_backtests, max_backtest_days,
                              created_by, created_at, last_used_at, revoked_at
                    """,
                    (
                        _hash_code(code),
                        note.strip(),
                        expires_at,
                        max_backtests_per_day,
                        max_concurrent_backtests,
                        max_backtest_days,
                        created_by,
                    ),
                )
                row = dict(cursor.fetchone())
                self._audit_cursor(
                    cursor,
                    "guest_code_created",
                    role="admin",
                    subject_id=created_by,
                    guest_code_id=int(row["id"]),
                    success=True,
                )
            conn.commit()
        row["code"] = code
        return self._serialize(row)

    def list_codes(self) -> list[dict[str, Any]]:
        with self.database.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, note, expires_at, max_backtests_per_day,
                           max_concurrent_backtests, max_backtest_days, created_by,
                           created_at, last_used_at, revoked_at
                    FROM guest_access_codes
                    ORDER BY created_at DESC, id DESC
                    """
                )
                return [self._serialize(dict(row)) for row in cursor.fetchall()]

    def revoke_code(self, code_id: int, revoked_by: str) -> dict[str, Any]:
        with self.database.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE guest_access_codes
                    SET revoked_at = COALESCE(revoked_at, NOW())
                    WHERE id = %s
                    RETURNING id, revoked_at
                    """,
                    (code_id,),
                )
                row = cursor.fetchone()
                if not row:
                    raise GuestAccessError("邀请码不存在", 404)
                self._audit_cursor(
                    cursor,
                    "guest_code_revoked",
                    role="admin",
                    subject_id=revoked_by,
                    guest_code_id=code_id,
                    success=True,
                )
            conn.commit()
        return self._serialize(dict(row))

    def authenticate_code(self, code: str) -> dict[str, Any]:
        with self.database.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM guest_access_codes WHERE code_hash = %s",
                    (_hash_code(code),),
                )
                row = cursor.fetchone()
                if not row:
                    self._audit_cursor(
                        cursor, "guest_login", role="guest", success=False, reason="invalid_code"
                    )
                    conn.commit()
                    raise GuestAccessError("邀请码无效", 401)
                code_row = dict(row)
                self._validate_active(code_row)
                cursor.execute(
                    "UPDATE guest_access_codes SET last_used_at = NOW() WHERE id = %s",
                    (code_row["id"],),
                )
                self._audit_cursor(
                    cursor,
                    "guest_login",
                    role="guest",
                    guest_code_id=int(code_row["id"]),
                    success=True,
                )
            conn.commit()
        return self._serialize(code_row)

    def get_active_code(self, code_id: int) -> dict[str, Any]:
        with self.database.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM guest_access_codes WHERE id = %s", (code_id,))
                row = cursor.fetchone()
        if not row:
            raise GuestAccessError("邀请码不存在", 401)
        result = dict(row)
        self._validate_active(result)
        return self._serialize(result)

    def reserve_backtest(
        self,
        principal: Mapping[str, Any],
        *,
        endpoint: str,
        start_date: str,
        end_date: str,
    ) -> int | None:
        if principal.get("role") != "guest":
            return None
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except ValueError as exc:
            raise GuestAccessError("回测日期格式无效") from exc
        if end < start:
            raise GuestAccessError("回测结束日期不能早于开始日期")

        code_id = int(principal["guest_code_id"])
        with self.database.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM guest_access_codes WHERE id = %s FOR UPDATE",
                    (code_id,),
                )
                row = cursor.fetchone()
                if not row:
                    raise GuestAccessError("邀请码不存在", 401)
                code = dict(row)
                self._validate_active(code)
                days = (end - start).days + 1
                max_days = int(code["max_backtest_days"])
                if days > max_days:
                    self._reject_quota(
                        cursor, principal, f"访客最长回测区间为 {max_days} 天"
                    )
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (
                            WHERE (created_at AT TIME ZONE 'Asia/Shanghai')::DATE
                                = (NOW() AT TIME ZONE 'Asia/Shanghai')::DATE
                        ) AS daily_count,
                        COUNT(*) FILTER (WHERE status = 'running') AS running_count
                    FROM guest_backtest_usage
                    WHERE guest_code_id = %s
                    """,
                    (code_id,),
                )
                usage = dict(cursor.fetchone())
                max_daily = int(code["max_backtests_per_day"])
                if max_daily and int(usage["daily_count"] or 0) >= max_daily:
                    self._reject_quota(
                        cursor, principal, f"访客每日回测上限为 {max_daily} 次"
                    )
                max_concurrent = int(code["max_concurrent_backtests"])
                if int(usage["running_count"] or 0) >= max_concurrent:
                    self._reject_quota(
                        cursor, principal, f"访客并发回测上限为 {max_concurrent} 个"
                    )
                cursor.execute(
                    """
                    INSERT INTO guest_backtest_usage
                        (guest_code_id, session_id, endpoint, start_date, end_date, status)
                    VALUES (%s, %s, %s, %s, %s, 'running')
                    RETURNING id
                    """,
                    (
                        code_id,
                        str(principal["session_id"]),
                        endpoint,
                        start,
                        end,
                    ),
                )
                usage_id = int(cursor.fetchone()["id"])
            conn.commit()
        return usage_id

    def finish_backtest(
        self,
        usage_id: int | None,
        *,
        success: bool,
        run_id: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        if usage_id is None:
            return
        with self.database.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE guest_backtest_usage
                    SET status = %s, run_id = %s, failure_reason = %s, finished_at = NOW()
                    WHERE id = %s AND status = 'running'
                    """,
                    ("success" if success else "failed", run_id, failure_reason, usage_id),
                )
            conn.commit()

    def _validate_active(self, code: Mapping[str, Any]) -> None:
        if code.get("revoked_at") is not None:
            raise GuestAccessError("邀请码已撤销", 401)
        expires_at = code["expires_at"]
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= _now():
            raise GuestAccessError("邀请码已过期", 401)

    def _reject_quota(
        self, cursor, principal: Mapping[str, Any], reason: str
    ) -> None:
        self._audit_cursor(
            cursor,
            "guest_backtest_quota_rejected",
            role="guest",
            subject_id=str(principal.get("session_id") or ""),
            guest_code_id=int(principal["guest_code_id"]),
            success=False,
            reason=reason,
        )
        cursor.connection.commit()
        raise GuestAccessError(reason, 429)

    @staticmethod
    def _audit_cursor(
        cursor,
        event_type: str,
        *,
        role: str,
        success: bool,
        subject_id: str | None = None,
        guest_code_id: int | None = None,
        reason: str | None = None,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO auth_audit_events
                (event_type, role, subject_id, guest_code_id, success, reason)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (event_type, role, subject_id, guest_code_id, success, reason),
        )

    @staticmethod
    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value.isoformat() if isinstance(value, (datetime, date)) else value
            for key, value in row.items()
        }
