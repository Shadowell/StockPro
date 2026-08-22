"""
策略删除清理回归测试。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.local_db import LocalDatabase  # noqa: E402


def test_delete_strategy_removes_live_workspace_and_signal_rows(tmp_path) -> None:
    db = LocalDatabase(str(tmp_path / "strategy-delete.db"))
    db.init_db()
    strategy_id = db.save_strategy(
        name="[合约][AI][AI] Top30 · Hermes/Codex自主交易 · 100U",
        script_content="class Strategy: pass",
        config={
            "strategy_key": "ai_autonomous_trader",
            "is_paper_trading": True,
            "paper_only": True,
        },
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    conn = db.get_connection()
    now = "2026-06-04T18:39:39"
    conn.execute(
        """
        INSERT INTO live_strategy_settings
        (strategy_id, added, account_id, status, risk_config, created_at, updated_at)
        VALUES (?, 1, 'default', 'added', '{}', ?, ?)
        """,
        (strategy_id, now, now),
    )
    conn.execute(
        """
        INSERT INTO live_strategy_account_bindings
        (strategy_id, account_id, added, status, risk_config, created_at, updated_at)
        VALUES (?, 'default', 1, 'added', '{}', ?, ?)
        """,
        (strategy_id, now, now),
    )
    conn.execute(
        """
        INSERT INTO live_strategy_subscriptions
        (source_strategy_id, account_id, status, risk_config, created_at, updated_at)
        VALUES (?, 'default', 'running', '{}', ?, ?)
        """,
        (strategy_id, now, now),
    )
    event_id = conn.execute(
        """
        INSERT INTO strategy_signal_events
        (source_strategy_id, exchange, market_type, signal_action, symbol, live_dispatch_status, payload, created_at, updated_at)
        VALUES (?, 'okx', 'swap', 'buy', 'BTC/USDT:USDT', 'sent', ?, ?, ?)
        """,
        (strategy_id, json.dumps({"source": "test"}), now, now),
    ).lastrowid
    subscription_id = conn.execute(
        """
        SELECT id FROM live_strategy_subscriptions
        WHERE source_strategy_id = ? AND account_id = 'default'
        """,
        (strategy_id,),
    ).fetchone()["id"]
    conn.execute(
        """
        INSERT INTO live_signal_executions
        (signal_event_id, subscription_id, source_strategy_id, account_id, status, created_at, updated_at)
        VALUES (?, ?, ?, 'default', 'filled', ?, ?)
        """,
        (event_id, subscription_id, strategy_id, now, now),
    )
    conn.commit()

    assert db.delete_strategy(strategy_id) is True

    conn = db.get_connection()
    assert conn.execute("SELECT count(*) FROM strategies WHERE id = ?", (strategy_id,)).fetchone()[0] == 0
    for table, column in [
        ("live_signal_executions", "source_strategy_id"),
        ("live_strategy_account_bindings", "strategy_id"),
        ("live_strategy_settings", "strategy_id"),
        ("live_strategy_subscriptions", "source_strategy_id"),
        ("strategy_signal_events", "source_strategy_id"),
    ]:
        assert conn.execute(
            f'SELECT count(*) FROM "{table}" WHERE "{column}" = ?',
            (strategy_id,),
        ).fetchone()[0] == 0
