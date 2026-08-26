"""生产 bug 修复回归（2026-08-24 review 发现）。

Bug #1: SQLite database is locked — 回测 worker 每根 K 线写一次
backtest_jobs + auth get_session 每请求 UPDATE last_seen_at，与主进程
并发导致写锁风暴。
Bug #2: GET /api/v2/sync/status 默认内嵌全部 job items（单任务 2628 行，
响应 2MB）。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import data_sync_service as data_sync_module  # noqa: E402
from app.services.data_sync_service import DataSyncService, SyncStatus  # noqa: E402
from app.db.local_db import LocalDatabase  # noqa: E402
from app.services import auth_service as auth_service_module  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402


# ---------------------------------------------------------------------------
# Bug #1a: backtest progress write throttle
# ---------------------------------------------------------------------------


def test_progress_writer_writes_first_tick_immediately() -> None:
    writer = _writer()
    assert writer.should_write(now=1_000.0) is True


def test_progress_writer_throttles_rapid_ticks(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v2.endpoints import backtest as backtest_module

    writer = backtest_module._ProgressWriter(interval_sec=1.0)
    assert writer.should_write(now=1_000.0) is True
    assert writer.should_write(now=1_000.4) is False
    assert writer.should_write(now=1_000.9) is False
    assert writer.should_write(now=1_001.1) is True


def test_progress_writer_force_write_bypasses_throttle() -> None:
    from app.api.v2.endpoints import backtest as backtest_module

    writer = backtest_module._ProgressWriter(interval_sec=1.0)
    writer.should_write(now=1_000.0)
    # 取消等状态变化必须立即落库，不受节流限制。
    assert writer.should_write(now=1_000.1, force=True) is True


def test_worker_progress_hook_limits_update_frequency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """模拟 progress_hook 高频回调：60 秒内 600 根 bar 只允许 ~61 次 DB 写。"""
    from app.api.v2.endpoints import backtest as backtest_module

    writes: list[dict[str, Any]] = []
    clock = {"now": 10_000.0}

    def fake_update(job_id: str, **fields: Any) -> None:
        writes.append(fields)

    monkeypatch.setattr(backtest_module, "_update_backtest_job", fake_update)
    monkeypatch.setattr(backtest_module.time, "monotonic", lambda: clock["now"])

    hook = backtest_module._make_progress_hook(
        job_id="job-test",
        cancel_requested=lambda: False,
        completed_before=lambda: 0,
        total_ref=lambda: 1000,
    )

    for _ in range(600):
        clock["now"] += 0.1  # 600 ticks × 100ms = 60s，每 tick 一根 bar
        hook(cur=1, total=1000)

    assert len(writes) <= 62  # 首次 + 每 1s 一次 + 容差
    assert len(writes) >= 55  # 但不能节流到完全不写


# ---------------------------------------------------------------------------
# Bug #1b: SQLite lock retry for backtest job updates
# ---------------------------------------------------------------------------


def test_sqlite_lock_retry_succeeds_after_transient_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v2.endpoints import backtest as backtest_module

    calls = {"n": 0}
    sleeps: list[float] = []

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    monkeypatch.setattr(backtest_module.time, "sleep", lambda s: sleeps.append(s))
    assert backtest_module._execute_with_sqlite_lock_retry(flaky) == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2


def test_sqlite_lock_retry_does_not_swallow_other_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v2.endpoints import backtest as backtest_module

    monkeypatch.setattr(backtest_module.time, "sleep", lambda s: None)
    with pytest.raises(sqlite3.OperationalError):
        backtest_module._execute_with_sqlite_lock_retry(
            lambda: (_ for _ in ()).throw(sqlite3.OperationalError("no such table"))
        )


def test_update_backtest_job_retries_on_locked_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """端到端：连接层注入一次 locked，验证 update 重试后成功落库。"""
    from app.api.v2.endpoints import backtest as backtest_module

    db = LocalDatabase(str(tmp_path / "bt.db"))
    db.init_db()
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO backtest_jobs (job_id, strategy_id, request_json, status)"
        " VALUES ('job-x', 1, '{}', 'queued')"
    )
    conn.commit()

    class FlakyCursor:
        def __init__(self, inner: Any, state: dict[str, int]) -> None:
            self._inner = inner
            self._state = state

        def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
            if "UPDATE backtest_jobs" in sql and self._state["locked"] < 2:
                self._state["locked"] += 1
                raise sqlite3.OperationalError("database is locked")
            return self._inner.execute(sql, *args, **kwargs)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    class FlakyConnection:
        def __init__(self, inner: Any, state: dict[str, int]) -> None:
            self._inner = inner
            self._state = state

        def cursor(self) -> FlakyCursor:
            return FlakyCursor(self._inner.cursor(), self._state)

        def close(self) -> None:
            pass  # 线程级复用连接不能真关；生产语义由 local_db 管理

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    state = {"locked": 0}
    real_conn = db.get_connection()
    sleeps: list[float] = []
    monkeypatch.setattr(backtest_module.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(
        backtest_module.db,
        "get_connection",
        lambda: FlakyConnection(real_conn, state),
    )

    backtest_module._update_backtest_job("job-x", status="running")

    assert state["locked"] == 2  # 两次 locked 后第三次成功
    assert len(sleeps) == 2
    check = real_conn.execute(
        "SELECT status FROM backtest_jobs WHERE job_id = 'job-x'"
    ).fetchone()
    assert check is not None and check[0] == "running"


def test_busy_timeout_raised_to_15s() -> None:
    src = (PROJECT_ROOT / "backend/app/db/local_db.py").read_text(encoding="utf-8")
    assert "busy_timeout=15000" in src
    assert "busy_timeout=5000" not in src


# ---------------------------------------------------------------------------
# Bug #1c: auth session last_seen_at touch throttle
# ---------------------------------------------------------------------------


def _auth_service(tmp_path: Path) -> AuthService:
    db = LocalDatabase(str(tmp_path / "auth.db"))
    db.init_db()
    return AuthService(db=db)


def test_auth_session_touch_is_throttled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = _auth_service(tmp_path)
    password_hash = service.hash_password("pw")
    session = service.login_admin(
        username="admin",
        password="pw",
        expected_username="admin",
        expected_password_hash=password_hash,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    token = session["token"]

    base = auth_service_module._now()
    clock = {"now": base}
    monkeypatch.setattr(auth_service_module, "_now", lambda: clock["now"])

    # 第一次读取建立基线（login 后立即读取，节流窗口内不重复 touch）
    loaded = service.get_session(token)
    assert loaded is not None
    first_seen = loaded["last_seen_at"]

    # 推进 30s：节流窗口内，不应再触发 UPDATE
    clock["now"] = base + auth_service_module.timedelta(seconds=30)
    loaded = service.get_session(token)
    assert loaded is not None
    assert loaded["last_seen_at"] == first_seen

    # 推进 61s：超过节流阈值，touch 应发生
    clock["now"] = base + auth_service_module.timedelta(seconds=61)
    loaded = service.get_session(token)
    assert loaded is not None
    assert loaded["last_seen_at"] != first_seen

    # 会话本身不能因节流而失效
    assert loaded["authenticated"] is True


# ---------------------------------------------------------------------------
# Bug #2: /sync/status payload slimming
# ---------------------------------------------------------------------------


def _status_service(monkeypatch: pytest.MonkeyPatch, items: list[dict[str, Any]]):
    svc = DataSyncService()
    job = {
        "id": "job-1",
        "exchange": "okx",
        "status": "completed",
        "started_at": "2026-08-24 10:00:00",
        "completed_at": "2026-08-24 11:00:00",
        "total_symbols": 438,
        "total_timeframes": 6,
        "total_records_fetched": len(items) * 100,
        "total_records_inserted": len(items) * 99,
    }
    meta_list: list[dict[str, Any]] = []

    monkeypatch.setattr(data_sync_module.db, "get_all_sync_metadata", lambda exchange=None: meta_list)
    monkeypatch.setattr(svc, "_active_job", lambda: None)
    monkeypatch.setattr(svc, "_latest_job", lambda: job)
    monkeypatch.setattr(svc, "_load_job", lambda job_id: job)
    monkeypatch.setattr(svc, "_load_job_items", lambda job_id: items)
    svc._current_job = None
    svc._last_job_id = None
    svc._current_job_id = None
    svc._running = False
    return svc


def _items(counts: dict[str, int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    idx = 0
    for status, n in counts.items():
        for i in range(n):
            rows.append({
                "id": idx,
                "exchange": "okx",
                "symbol": f"S{idx}/USDT:USDT",
                "timeframe": "1h",
                "status": status if status != "error" else "error",
                "total_fetched": 100,
                "total_inserted": 99,
                "started_at": None,
                "ended_at": None,
                "error_message": "boom" if status == "error" else None,
                "checkpoint_timestamp": None,
            })
            idx += 1
    return rows


def test_sync_status_default_excludes_completed_item_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _status_service(monkeypatch, _items({"completed": 2628}))
    payload = svc.get_sync_status()
    current = payload["current_job"]
    assert current is not None
    assert current["total_items"] == 2628
    assert current["completed_items"] == 2628
    assert current["processed_items"] == 2628
    # 已完成任务的明细行默认不再内嵌 → 响应从 ~2MB 降为几 KB
    assert current["progress"] == []


def test_sync_status_default_also_excludes_idle_rows_of_interrupted_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """中断任务的大量 pending/idle 行同样不进轮询响应（生产实测 2024 行）。"""
    svc = _status_service(
        monkeypatch, _items({"completed": 604}) + _items({"idle": 2024})
    )
    svc._current_job = None
    payload = svc.get_sync_status()
    current = payload["current_job"]
    assert current is not None
    assert len(current["progress"]) == 0
    assert current["completed_items"] == 604
    assert current["total_items"] == 2628


def test_sync_status_keeps_running_and_error_rows_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _status_service(
        monkeypatch,
        _items({"completed": 2600}) + _items({"running": 20}) + _items({"error": 8}),
    )
    payload = svc.get_sync_status()
    current = payload["current_job"]
    rows = current["progress"]
    statuses = {row["status"] for row in rows}
    assert statuses <= {"syncing", "error"}
    assert len(rows) == 28  # running + error 保留，2600 个 completed 被剥离
    assert current["completed_items"] == 2600
    assert current["error_items"] == 8


def test_sync_status_include_items_returns_full_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _status_service(monkeypatch, _items({"completed": 3}))
    payload = svc.get_sync_status(include_items=True)
    assert len(payload["current_job"]["progress"]) == 3


def test_sync_status_endpoint_accepts_include_items_query() -> None:
    src = (PROJECT_ROOT / "backend/app/api/v2/endpoints/sync.py").read_text(encoding="utf-8")
    assert "include_items" in src.split("def status")[1].split("@router")[0]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _writer():
    from app.api.v2.endpoints import backtest as backtest_module

    return backtest_module._ProgressWriter(interval_sec=1.0)


del SyncStatus
