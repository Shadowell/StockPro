from __future__ import annotations

import sys
import json
import asyncio
from datetime import date
from datetime import datetime as real_datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.v2.endpoints import backtest  # noqa: E402
from app.db.local_db import LocalDatabase  # noqa: E402


def test_backtest_timeframe_normalization_accepts_12h() -> None:
    assert backtest._normalize_backtest_timeframe("12h") == "12h"
    assert backtest._normalize_backtest_timeframe("12H") == "12h"


def _client_with_temp_db(monkeypatch, tmp_path) -> tuple[TestClient, LocalDatabase]:
    temp_db = LocalDatabase(str(tmp_path / "crypto_data.db"))
    temp_db.init_db()
    monkeypatch.setattr(backtest, "db", temp_db)
    with backtest._BACKTEST_CANCEL_LOCK:
        backtest._BACKTEST_CANCEL_REQUESTS.clear()

    app = FastAPI()
    app.include_router(backtest.router, prefix="/backtest")
    return TestClient(app, raise_server_exceptions=False), temp_db


def _insert_backtest_result(
    db: LocalDatabase,
    *,
    strategy_id: int = 1,
    strategy_name: str = "[现货] 测试策略",
    symbols: str = "BTC/USDT",
    timeframe: str | None = None,
) -> int:
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR IGNORE INTO strategies (id, name, description, script_content, config, status, exchange, symbols)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (strategy_id, strategy_name, "test", "class Strategy: pass", "{}", "stopped", "okx", symbols),
    )
    cursor.execute(
        """
        INSERT INTO backtest_results (
            strategy_id, start_date, end_date, initial_capital, final_capital,
            total_return, annual_return, max_drawdown, sharpe_ratio, win_rate,
            profit_factor, total_trades, trades_detail, timeframe, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            strategy_id,
            "2026-01-01",
            "2026-02-01",
            10000,
            10100,
            1.0,
            12.0,
            2.0,
            1.2,
            55.0,
            1.4,
            8,
            "[]",
            timeframe,
            "completed",
        ),
    )
    rid = int(cursor.lastrowid)
    conn.commit()
    conn.close()
    return rid


def _insert_backtest_job(db: LocalDatabase, job_id: str, status: str = "running") -> None:
    conn = db.get_connection()
    conn.execute(
        """
        INSERT OR IGNORE INTO strategies (id, name, description, script_content, config, status, exchange, symbols)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (1, "[现货] 测试策略", "test", "class Strategy: pass", "{}", "stopped", "okx", "BTC/USDT"),
    )
    conn.execute(
        """
        INSERT INTO backtest_jobs (
            job_id, strategy_id, request_json, status, current_bar, total_bars
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            1,
            '{"strategy_id":1,"exchange":"okx","start_date":"2026-01-01","end_date":"2026-02-01","initial_capital":10000}',
            status,
            12,
            100,
        ),
    )
    conn.commit()
    conn.close()


def _insert_strategy_row(
    db: LocalDatabase,
    *,
    strategy_id: int,
    name: str,
    status: str,
    config: dict,
    symbols: list[str] | None = None,
) -> None:
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO strategies (id, name, description, script_content, config, status, exchange, symbols)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            strategy_id,
            name,
            "test",
            "class Strategy: pass",
            json.dumps(config, ensure_ascii=False),
            status,
            "okx",
            json.dumps(symbols or ["BTC/USDT:USDT"], ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()


def test_list_backtest_results_supports_offset(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    first_id = _insert_backtest_result(db)
    second_id = _insert_backtest_result(db)
    conn = db.get_connection()
    conn.execute(
        "UPDATE backtest_results SET created_at = ? WHERE id = ?",
        ("2026-01-01 00:00:00", first_id),
    )
    conn.execute(
        "UPDATE backtest_results SET created_at = ? WHERE id = ?",
        ("2026-01-02 00:00:00", second_id),
    )
    conn.commit()
    conn.close()

    response = client.get("/backtest/results?limit=1&offset=1")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [first_id]


def test_backtest_results_expose_data_quality_invalidated_status(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    result_id = _insert_backtest_result(
        db,
        strategy_id=105,
        strategy_name="[合约][1H][CTA] SOL · EMA5/20趋势跟踪对照版 · 100U",
        symbols='["SOL/USDT:USDT"]',
        timeframe="1h",
    )
    conn = db.get_connection()
    conn.execute(
        """
        UPDATE backtest_results
        SET data_quality_status = ?,
            data_quality_message = ?,
            data_quality_checked_at = ?
        WHERE id = ?
        """,
        (
            "invalidated",
            "SOL/USDT:USDT 1h 缓存存在连续跳变，结果不可继续信任",
            "2026-06-08T20:30:00",
            result_id,
        ),
    )
    conn.commit()
    conn.close()

    list_response = client.get("/backtest/results")
    detail_response = client.get(f"/backtest/result/{result_id}")

    assert list_response.status_code == 200
    item = list_response.json()[0]
    assert item["data_quality_status"] == "invalidated"
    assert "不可继续信任" in item["data_quality_message"]
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["data_quality_status"] == "invalidated"
    assert "SOL/USDT:USDT 1h" in detail["data_quality_message"]


def test_backtest_results_include_joined_strategy_name(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    named_id = _insert_backtest_result(
        db,
        strategy_id=438,
        strategy_name="ARC self-test cand_blue_7b2585",
    )
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = OFF")
    cursor.execute(
        """
        INSERT INTO backtest_results (
            strategy_id, start_date, end_date, initial_capital, final_capital,
            total_return, annual_return, max_drawdown, sharpe_ratio, win_rate,
            profit_factor, total_trades, trades_detail, timeframe, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            9999,
            "2026-01-01",
            "2026-02-01",
            10000,
            10100,
            1.0,
            12.0,
            2.0,
            1.2,
            55.0,
            1.4,
            8,
            "[]",
            None,
            "completed",
        ),
    )
    orphan_id = int(cursor.lastrowid)
    conn.commit()
    conn.close()

    listed = {item["id"]: item for item in client.get("/backtest/results").json()}
    assert listed[named_id]["strategy_name"] == "ARC self-test cand_blue_7b2585"
    assert listed[orphan_id].get("strategy_name") in (None, "")

    detail = client.get(f"/backtest/result/{named_id}").json()
    assert detail["strategy_name"] == "ARC self-test cand_blue_7b2585"

    orphan_detail = client.get(f"/backtest/result/{orphan_id}").json()
    assert orphan_detail.get("strategy_name") in (None, "")


def test_batch_running_backtest_creates_jobs_for_running_paper_strategies(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    _insert_strategy_row(
        db,
        strategy_id=101,
        name="[合约][15M][CTA] DOGE · EMA趋势跟踪 · 100U",
        status="running",
        config={"strategy_key": "paper_doge", "is_paper_trading": True, "timeframe": "15m"},
    )
    _insert_strategy_row(
        db,
        strategy_id=102,
        name="[合约][1H][CTA] ETH · 暂停策略 · 100U",
        status="paused",
        config={"strategy_key": "paper_eth", "is_paper_trading": True, "timeframe": "1h"},
    )
    _insert_strategy_row(
        db,
        strategy_id=103,
        name="[实盘][合约][15M][CTA] BTC · 真实执行 · 100U",
        status="running",
        config={"strategy_key": "live_btc", "is_paper_trading": False, "timeframe": "15m"},
    )
    _insert_strategy_row(
        db,
        strategy_id=104,
        name="[合约][5M][CTA] SOL · 无法解析 · 100U",
        status="running",
        config={"strategy_key": "missing_strategy", "is_paper_trading": True, "timeframe": "5m"},
    )

    class FixedDateTime:
        @staticmethod
        def now():
            return real_datetime(2026, 6, 8)

    def fake_strategy_for_id(strategy_id: int):
        if strategy_id != 101:
            return None
        return {
            "kind": "base_strategy",
            "strategy_class": object,
            "name": "[合约][15M][CTA] DOGE · EMA趋势跟踪 · 100U",
            "symbols": ["DOGE/USDT:USDT"],
            "db_config": {"strategy_key": "paper_doge", "timeframe": "15m", "market_type": "swap"},
        }

    def fake_schedule(job_id: str, payload: dict) -> None:
        backtest._clear_backtest_active(job_id)

    monkeypatch.setattr(backtest, "datetime", FixedDateTime)
    monkeypatch.setattr(backtest, "get_strategy_for_id", fake_strategy_for_id)
    monkeypatch.setattr(backtest, "_schedule_backtest_job_task", fake_schedule)
    monkeypatch.setattr(backtest, "_batch_backtest_data_skip_reason", lambda *_: None)

    response = client.post("/backtest/run_running_strategies")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["skipped_count"] == 2
    assert body["defaults"] == {
        "start_date": "2025-06-08",
        "end_date": "2026-06-07",
        "initial_capital": 100.0,
        "timeframe_mode": "strategy",
    }
    job = body["jobs"][0]
    assert job["strategy_id"] == 101
    assert job["strategy_name"] == "[合约][15M][CTA] DOGE · EMA趋势跟踪 · 100U"
    assert job["request"]["start_date"] == "2025-06-08"
    assert job["request"]["end_date"] == "2026-06-07"
    assert job["request"]["initial_capital"] == 100.0
    assert job["request"]["timeframe_mode"] == "strategy"
    assert job["request"]["timeframe"] == "15m"
    assert {item["strategy_id"] for item in body["skipped"]} == {103, 104}

    conn = db.get_connection()
    saved = conn.execute(
        "SELECT strategy_id, request_json FROM backtest_jobs WHERE job_id = ?",
        (job["job_id"],),
    ).fetchone()
    conn.close()
    assert saved["strategy_id"] == 101
    saved_request = json.loads(saved["request_json"])
    assert saved_request["initial_capital"] == 100.0
    assert saved_request["end_date"] == "2026-06-07"


def test_batch_running_backtest_uses_independent_scheduler(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    for strategy_id, symbol in ((201, "BTC"), (202, "ETH")):
        _insert_strategy_row(
            db,
            strategy_id=strategy_id,
            name=f"[合约][1H][CTA] {symbol} · 批量调度测试 · 100U",
            status="running",
            config={
                "strategy_key": f"paper_{symbol.lower()}",
                "is_paper_trading": True,
                "timeframe": "1h",
            },
            symbols=[f"{symbol}/USDT:USDT"],
        )

    def fake_strategy_for_id(strategy_id: int):
        symbol = "BTC" if strategy_id == 201 else "ETH"
        return {
            "kind": "base_strategy",
            "strategy_class": object,
            "name": f"[合约][1H][CTA] {symbol} · 批量调度测试 · 100U",
            "symbols": [f"{symbol}/USDT:USDT"],
            "db_config": {
                "strategy_key": f"paper_{symbol.lower()}",
                "timeframe": "1h",
                "market_type": "swap",
            },
        }

    scheduled: list[tuple[str, dict]] = []

    def fake_schedule(job_id: str, payload: dict) -> None:
        scheduled.append((job_id, payload))
        backtest._clear_backtest_active(job_id)

    original_add_task = backtest.BackgroundTasks.add_task

    def reject_serial_background_task(self, func, *args, **kwargs):
        if getattr(func, "__name__", "") == "_run_backtest_job_task":
            raise AssertionError("批量回测不能通过 FastAPI BackgroundTasks 串行执行")
        return original_add_task(self, func, *args, **kwargs)

    monkeypatch.setattr(backtest, "get_strategy_for_id", fake_strategy_for_id)
    monkeypatch.setattr(backtest, "_schedule_backtest_job_task", fake_schedule, raising=False)
    monkeypatch.setattr(backtest.BackgroundTasks, "add_task", reject_serial_background_task)
    monkeypatch.setattr(backtest, "_batch_backtest_data_skip_reason", lambda *_: None)

    response = client.post("/backtest/run_running_strategies")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    assert {payload["strategy_id"] for _, payload in scheduled} == {201, 202}


def test_batch_running_backtest_skips_uncovered_market_data(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    _insert_strategy_row(
        db,
        strategy_id=221,
        name="[合约][15M][CTA] UB · ATR Top10 EMA5/10趋势跟踪激进版 · 100U",
        status="running",
        config={"strategy_key": "paper_ub", "is_paper_trading": True, "timeframe": "15m"},
        symbols=["UB/USDT:USDT"],
    )

    def fake_strategy_for_id(strategy_id: int):
        return {
            "kind": "base_strategy",
            "strategy_class": object,
            "name": "[合约][15M][CTA] UB · ATR Top10 EMA5/10趋势跟踪激进版 · 100U",
            "symbols": ["UB/USDT:USDT"],
            "db_config": {"strategy_key": "paper_ub", "timeframe": "15m", "market_type": "swap"},
        }

    scheduled: list[tuple[str, dict]] = []

    def fake_schedule(job_id: str, payload: dict) -> None:
        scheduled.append((job_id, payload))

    def fake_data_skip_reason(strategy_info: dict, request_payload: backtest.BacktestRequest) -> str | None:
        assert request_payload.strategy_id == 221
        assert request_payload.timeframe == "15m"
        return "真实 K 线覆盖不足: okx UB/USDT:USDT 15m"

    monkeypatch.setattr(backtest, "get_strategy_for_id", fake_strategy_for_id)
    monkeypatch.setattr(backtest, "_schedule_backtest_job_task", fake_schedule)
    monkeypatch.setattr(backtest, "_batch_backtest_data_skip_reason", fake_data_skip_reason, raising=False)

    response = client.post("/backtest/run_running_strategies")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 0
    assert body["skipped_count"] == 1
    assert body["skipped"][0]["strategy_id"] == 221
    assert "真实 K 线覆盖不足" in body["skipped"][0]["reason"]
    assert scheduled == []

    conn = db.get_connection()
    job_count = conn.execute("SELECT COUNT(*) FROM backtest_jobs").fetchone()[0]
    conn.close()
    assert job_count == 0


def test_batch_backtest_data_skip_reason_describes_cached_coverage(monkeypatch) -> None:
    strategy_info = {
        "name": "[合约][15M][CTA] UB · 覆盖预检 · 100U",
        "symbols": ["UB/USDT:USDT"],
        "db_config": {"timeframe": "15m", "market_type": "swap"},
    }
    request = backtest.BacktestRequest(
        strategy_id=221,
        start_date="2025-06-08",
        end_date="2026-06-07",
        timeframe_mode="strategy",
    )

    monkeypatch.setattr(
        backtest.backtrader_engine,
        "_read_cached_dataframe",
        lambda *args, **kwargs: [object()] * 643,
    )
    monkeypatch.setattr(backtest.backtrader_engine, "_needs_fetch_for_range", lambda *args: True)
    monkeypatch.setattr(
        backtest.backtrader_engine,
        "_dataframe_ts_range",
        lambda raw_df: (1_780_000_000_000, 1_780_100_000_000),
    )
    monkeypatch.setattr(backtest.backtrader_engine, "_expected_bar_count", lambda *args: 34_945)
    monkeypatch.setattr(backtest.backtrader_engine, "_format_ts", lambda ts: f"ts:{ts}")

    reason = backtest._batch_backtest_data_skip_reason(strategy_info, request)

    assert reason is not None
    assert "UB/USDT:USDT 15m" in reason
    assert "期望约 34945 根，实际 643 根" in reason
    assert "请先同步完整历史 K 线或缩短日期后单独回测" in reason


def test_list_backtest_results_sorts_return_before_pagination(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    low_id = _insert_backtest_result(db)
    high_id = _insert_backtest_result(db)
    middle_id = _insert_backtest_result(db)
    conn = db.get_connection()
    conn.execute("UPDATE backtest_results SET total_return = ? WHERE id = ?", (-4.0, low_id))
    conn.execute("UPDATE backtest_results SET total_return = ? WHERE id = ?", (12.0, high_id))
    conn.execute("UPDATE backtest_results SET total_return = ? WHERE id = ?", (3.0, middle_id))
    conn.commit()
    conn.close()

    response = client.get("/backtest/results?sort_by=return&sort_dir=desc&limit=1")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [high_id]


def test_list_backtest_results_sorts_created_before_pagination(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    older_id = _insert_backtest_result(db)
    newer_id = _insert_backtest_result(db)
    conn = db.get_connection()
    conn.execute(
        "UPDATE backtest_results SET created_at = ? WHERE id = ?",
        ("2026-01-01 00:00:00", older_id),
    )
    conn.execute(
        "UPDATE backtest_results SET created_at = ? WHERE id = ?",
        ("2026-01-02 00:00:00", newer_id),
    )
    conn.commit()
    conn.close()

    response = client.get("/backtest/results?sort_by=created&sort_dir=asc&limit=1")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [older_id]


def test_list_backtest_results_sorts_drawdown_before_pagination(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    low_drawdown_id = _insert_backtest_result(db)
    high_drawdown_id = _insert_backtest_result(db)
    middle_drawdown_id = _insert_backtest_result(db)
    conn = db.get_connection()
    conn.execute("UPDATE backtest_results SET max_drawdown = ? WHERE id = ?", (1.5, low_drawdown_id))
    conn.execute("UPDATE backtest_results SET max_drawdown = ? WHERE id = ?", (18.0, high_drawdown_id))
    conn.execute("UPDATE backtest_results SET max_drawdown = ? WHERE id = ?", (6.0, middle_drawdown_id))
    conn.commit()
    conn.close()

    response = client.get("/backtest/results?sort_by=drawdown&sort_dir=asc&limit=1")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [low_drawdown_id]


def test_list_backtest_results_sorts_win_rate_before_pagination(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    low_win_id = _insert_backtest_result(db)
    high_win_id = _insert_backtest_result(db)
    middle_win_id = _insert_backtest_result(db)
    conn = db.get_connection()
    conn.execute("UPDATE backtest_results SET win_rate = ? WHERE id = ?", (35.0, low_win_id))
    conn.execute("UPDATE backtest_results SET win_rate = ? WHERE id = ?", (80.0, high_win_id))
    conn.execute("UPDATE backtest_results SET win_rate = ? WHERE id = ?", (52.0, middle_win_id))
    conn.commit()
    conn.close()

    response = client.get("/backtest/results?sort_by=win_rate&sort_dir=desc&limit=1")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [high_win_id]


def test_list_backtest_results_supports_fuzzy_search_before_pagination(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    _insert_backtest_result(
        db,
        strategy_id=10,
        strategy_name="[合约][1H][CTA] ETH · Heikin Ashi趋势跟踪低频版 · 100U",
        symbols='["ETH/USDT:USDT"]',
        timeframe="1h",
    )
    doge_id = _insert_backtest_result(
        db,
        strategy_id=11,
        strategy_name="[合约][1M][马丁] DOGE · ATR马丁网格 · 100U",
        symbols='["DOGE/USDT:USDT"]',
        timeframe="1m",
    )

    response = client.get("/backtest/results?q=doge%201m&limit=1")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [doge_id]


def test_list_backtest_results_can_skip_matrix_summary(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    result_id = _insert_backtest_result(db)
    conn = db.get_connection()
    conn.execute(
        "UPDATE backtest_results SET matrix_results_json = ? WHERE id = ?",
        (
            '[{"timeframe":"5m","total_return":1.0,"equity_curve":[1,2,3],"trades":[{"x":1}]}]',
            result_id,
        ),
    )
    conn.commit()
    conn.close()

    response = client.get("/backtest/results?include_matrix_summary=false")

    assert response.status_code == 200
    assert response.json()[0]["matrix_results"] == []


def test_delete_backtest_result_removes_only_history(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    result_id = _insert_backtest_result(db)

    response = client.delete(f"/backtest/result/{result_id}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "id": result_id}
    conn = db.get_connection()
    count = conn.execute("SELECT COUNT(*) FROM backtest_results WHERE id = ?", (result_id,)).fetchone()[0]
    conn.close()
    assert count == 0


def test_delete_backtest_result_returns_404_for_missing_row(monkeypatch, tmp_path) -> None:
    client, _db = _client_with_temp_db(monkeypatch, tmp_path)

    response = client.delete("/backtest/result/999")

    assert response.status_code == 404


def test_cancel_running_backtest_job_marks_cancelling(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    _insert_backtest_job(db, "job-running", "running")

    response = client.post("/backtest/job/job-running/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelling"
    assert body["current_bar"] == 12
    assert body["total_bars"] == 100
    assert backtest._is_backtest_cancel_requested("job-running")


def test_cancel_request_is_visible_from_persisted_job_state(monkeypatch, tmp_path) -> None:
    _client, db = _client_with_temp_db(monkeypatch, tmp_path)
    _insert_backtest_job(db, "job-persisted-cancel", "cancelling")
    with backtest._BACKTEST_CANCEL_LOCK:
        backtest._BACKTEST_CANCEL_REQUESTS.clear()

    assert backtest._is_backtest_cancel_requested("job-persisted-cancel")


def test_backtest_job_task_runs_in_subprocess(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def reject_to_thread(*_args, **_kwargs):
        raise AssertionError("回测任务不能在 FastAPI 进程内通过线程执行")

    class FakeProcess:
        returncode = 0

        async def wait(self) -> int:
            captured["waited"] = True
            return self.returncode

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(asyncio, "to_thread", reject_to_thread)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(backtest, "_read_backtest_job_status", lambda _job_id: "completed", raising=False)

    asyncio.run(
        backtest._run_backtest_job_task(
            "job-subprocess",
            {
                "strategy_id": 1,
                "exchange": "okx",
                "start_date": "2026-01-01",
                "end_date": "2026-02-01",
                "initial_capital": 10000,
            },
        )
    )

    args = captured["args"]
    assert args[0] == sys.executable
    assert args[1:3] == ("-m", "app.workers.backtest_job_worker")
    assert args[3] == "job-subprocess"
    assert json.loads(args[4])["strategy_id"] == 1
    assert Path(captured["kwargs"]["cwd"]).name == "backend"
    assert captured["waited"] is True


def test_cancel_completed_backtest_job_is_noop(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    _insert_backtest_job(db, "job-completed", "completed")

    response = client.post("/backtest/job/job-completed/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert not backtest._is_backtest_cancel_requested("job-completed")


def test_cancelled_worker_does_not_write_backtest_history(monkeypatch, tmp_path) -> None:
    _client, db = _client_with_temp_db(monkeypatch, tmp_path)
    _insert_backtest_job(db, "job-cancelled", "running")

    class DummyStrategy:
        pass

    monkeypatch.setattr(
        backtest,
        "get_strategy_for_id",
        lambda _strategy_id: {
            "name": "[现货] 测试策略",
            "strategy_class": DummyStrategy,
            "db_config": {"timeframe": "1m", "symbols": ["BTC/USDT"]},
        },
    )

    def fake_run_strategy(**_kwargs):
        raise backtest.BacktestCancelled("用户已停止回测")

    monkeypatch.setattr(backtest.backtrader_engine, "run_strategy", fake_run_strategy)

    backtest._run_backtest_job_worker(
        "job-cancelled",
        {
            "strategy_id": 1,
            "exchange": "okx",
            "start_date": "2026-01-01",
            "end_date": "2026-02-01",
            "initial_capital": 10000,
        },
    )

    conn = db.get_connection()
    status = conn.execute("SELECT status FROM backtest_jobs WHERE job_id = ?", ("job-cancelled",)).fetchone()[0]
    history_count = conn.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0]
    conn.close()
    assert status == "cancelled"
    assert history_count == 0


def test_matrix_backtest_job_runs_each_requested_timeframe(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    _insert_backtest_job(db, "job-matrix", "running")

    class DummyStrategy:
        pass

    monkeypatch.setattr(
        backtest,
        "get_strategy_for_id",
        lambda _strategy_id: {
            "name": "[现货] 测试策略",
            "strategy_class": DummyStrategy,
            "db_config": {"timeframe": "1m", "symbols": ["BTC/USDT"]},
        },
    )
    seen: list[tuple[str, str]] = []

    def fake_run_strategy(**kwargs):
        seen.append((kwargs["timeframe"], kwargs["strategy_config"]["timeframe"]))
        return backtest.BacktestReport(
            status="completed",
            initial_capital=10000,
            final_capital=10100,
            total_return_pct=1.0 if kwargs["timeframe"] == "5m" else 2.0,
            annual_return_pct=12.0,
            max_drawdown_pct=6.0,
            sortino_ratio=1.7,
            calmar_ratio=2.4,
            total_fees=3.5,
            avg_holding_bars=4.0,
            total_bars=10,
            elapsed_seconds=0.1,
            equity_curve=[
                {"timestamp": 1760000000000, "equity": 10000},
                {"timestamp": 1760000600000, "equity": 10100},
            ],
        )

    monkeypatch.setattr(backtest.backtrader_engine, "run_strategy", fake_run_strategy)

    backtest._run_backtest_job_worker(
        "job-matrix",
        {
            "strategy_id": 1,
            "exchange": "okx",
            "timeframe_mode": "matrix",
            "timeframes": ["5M", "15m", "5m"],
            "start_date": "2026-01-01",
            "end_date": "2026-02-01",
            "initial_capital": 10000,
        },
    )

    conn = db.get_connection()
    row = conn.execute(
        "SELECT status, result_json FROM backtest_jobs WHERE job_id = ?",
        ("job-matrix",),
    ).fetchone()
    conn.close()
    result = backtest.json.loads(row["result_json"])

    assert row["status"] == "completed"
    assert seen == [("5m", "5m"), ("15m", "15m")]
    assert result["timeframe_mode"] == "matrix"
    assert [item["timeframe"] for item in result["matrix_results"]] == ["5m", "15m"]
    assert result["timeframe"] == "15m"
    assert result["total_return"] == 2.0

    history_response = client.get("/backtest/results")
    assert history_response.status_code == 200
    history_item = history_response.json()[0]
    assert history_item["timeframe"] == "15m"
    assert history_item["timeframe_mode"] == "matrix"
    assert [item["timeframe"] for item in history_item["matrix_results"]] == ["5m", "15m"]
    assert all("equity_curve" not in item for item in history_item["matrix_results"])
    assert all("trades" not in item for item in history_item["matrix_results"])

    detail_response = client.get(f"/backtest/result/{history_item['id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["timeframe"] == "15m"
    assert detail["timeframe_mode"] == "matrix"
    assert detail["sortino_ratio"] == 1.7
    assert detail["calmar_ratio"] == 2.4
    assert detail["total_fees"] == 3.5
    assert detail["avg_holding_bars"] == 4.0
    assert detail["equity_curve"][0]["equity"] == 10000
    assert [item["timeframe"] for item in detail["matrix_results"]] == ["5m", "15m"]
    assert "equity_curve" in detail["matrix_results"][0]


def test_resume_interrupted_backtest_job_requeues_saved_request(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    _insert_backtest_job(db, "job-interrupted", "interrupted")
    captured: dict[str, object] = {}

    async def fake_run_task(job_id: str, payload: dict) -> None:
        captured["job_id"] = job_id
        captured["payload"] = payload
        backtest._update_backtest_job(job_id, status="running", message="fake resumed")
        backtest._clear_backtest_active(job_id)

    monkeypatch.setattr(backtest, "_run_backtest_job_task", fake_run_task)

    response = client.post("/backtest/job/job-interrupted/resume")

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "job-interrupted"
    assert body["status"] == "pending"
    assert body["current_bar"] == 0
    assert body["total_bars"] == 0
    assert captured["job_id"] == "job-interrupted"
    assert captured["payload"] == {
        "strategy_id": 1,
        "exchange": "okx",
        "symbol": None,
        "timeframe": None,
        "timeframe_mode": "strategy",
        "timeframes": None,
        "start_date": "2026-01-01",
        "end_date": "2026-02-01",
        "initial_capital": 10000.0,
        "commission": None,
        "slippage": None,
        "maker_fee_bps": None,
        "taker_fee_bps": None,
        "slippage_bps": None,
        "stop_loss": None,
        "take_profit": None,
        "trailing_stop": None,
    }


def test_resume_completed_backtest_job_is_rejected(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    _insert_backtest_job(db, "job-completed", "completed")

    response = client.post("/backtest/job/job-completed/resume")

    assert response.status_code == 409
    assert "已完成" in response.json()["detail"]


def test_list_backtest_jobs_exposes_request_for_resume_matching(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    _insert_backtest_job(db, "job-interrupted", "interrupted")
    conn = db.get_connection()
    conn.execute(
        "UPDATE backtest_jobs SET result_json = ? WHERE job_id = ?",
        ('{"large":"payload"}', "job-interrupted"),
    )
    conn.commit()
    conn.close()

    response = client.get("/backtest/jobs?status=interrupted&limit=5")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["job_id"] == "job-interrupted"
    assert body[0]["status"] == "interrupted"
    assert body[0]["resumable"] is True
    assert body[0]["request"]["strategy_id"] == 1
    assert body[0]["request"]["start_date"] == "2026-01-01"
    assert body[0]["request"]["end_date"] == "2026-02-01"
    assert "result" not in body[0]


def test_list_backtest_jobs_can_include_result_when_requested(monkeypatch, tmp_path) -> None:
    client, db = _client_with_temp_db(monkeypatch, tmp_path)
    _insert_backtest_job(db, "job-completed", "completed")
    conn = db.get_connection()
    conn.execute(
        "UPDATE backtest_jobs SET result_json = ? WHERE job_id = ?",
        ('{"total_return":1.23}', "job-completed"),
    )
    conn.commit()
    conn.close()

    response = client.get("/backtest/jobs?status=completed&limit=5&include_result=true")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["job_id"] == "job-completed"
    assert body[0]["result"]["total_return"] == 1.23


def test_backtest_date_validation_rejects_future_end_date() -> None:
    with pytest.raises(HTTPException) as exc:
        backtest._validate_backtest_date_range(
            "2026-05-01",
            "2026-05-09",
            today=date(2026, 5, 8),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "回测结束日期不能晚于当前日期 2026-05-08"


def test_backtest_date_validation_rejects_start_after_end() -> None:
    with pytest.raises(HTTPException) as exc:
        backtest._validate_backtest_date_range(
            "2026-05-09",
            "2026-05-08",
            today=date(2026, 5, 8),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "回测开始日期不能晚于结束日期"
