import json
import sqlite3
from pathlib import Path


def _load_report_module():
    import importlib.util
    import sys

    root = Path(__file__).resolve().parents[1]
    mod_path = root / "scripts" / "superpnl_hourly_report.py"
    spec = importlib.util.spec_from_file_location("superpnl_hourly_report", mod_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def _init_db(conn: sqlite3.Connection):
    conn.executescript(
        """
        CREATE TABLE strategies (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            script_content TEXT NOT NULL,
            config TEXT,
            status TEXT DEFAULT 'stopped',
            exchange TEXT,
            symbols TEXT,
            run_started_at TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE strategy_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id INTEGER NOT NULL,
            exchange TEXT NOT NULL,
            symbol TEXT NOT NULL,
            order_id TEXT,
            timestamp INTEGER NOT NULL,
            side TEXT NOT NULL,
            type TEXT NOT NULL,
            price REAL NOT NULL,
            quantity REAL NOT NULL,
            fee REAL,
            fee_asset TEXT,
            pnl REAL
        );
        """
    )


def test_superpnl_hourly_report_aggregates_realized_pnl(tmp_path):
    report = _load_report_module()

    db_path = tmp_path / "t.db"
    conn = sqlite3.connect(str(db_path))
    try:
        _init_db(conn)
        conn.execute(
            """
            INSERT INTO strategies (id, name, script_content, config, status, exchange, run_started_at)
            VALUES (10, 'SuperPnL-10', 'pass', ?, 'running', 'okx', '2026-05-03T00:00:00Z');
            """,
            (json.dumps({"initial_capital": 10000, "is_paper_trading": True}),),
        )
        conn.execute(
            """
            INSERT INTO strategies (id, name, script_content, config, status, exchange, run_started_at)
            VALUES (11, 'SuperPnL-11', 'pass', ?, 'paused', 'okx', '2026-05-03T00:00:00Z');
            """,
            (json.dumps({"initial_capital": 10000, "is_paper_trading": False}),),
        )

        # strategy 10: one winning SELL (pnl=+12.5), one BUY (pnl null)
        conn.execute(
            """
            INSERT INTO strategy_trades
            (strategy_id, exchange, symbol, order_id, timestamp, side, type, price, quantity, fee, fee_asset, pnl)
            VALUES (10, 'okx', 'BTC/USDT', 'o1', 1777767300000, 'BUY', 'market', 100.0, 1.0, 0.0, 'USDT', NULL);
            """
        )
        conn.execute(
            """
            INSERT INTO strategy_trades
            (strategy_id, exchange, symbol, order_id, timestamp, side, type, price, quantity, fee, fee_asset, pnl)
            VALUES (10, 'okx', 'BTC/USDT', 'o2', 1777768200000, 'SELL', 'market', 110.0, 1.0, 0.0, 'USDT', 12.5);
            """
        )

        # strategy 11: one losing SELL
        conn.execute(
            """
            INSERT INTO strategy_trades
            (strategy_id, exchange, symbol, order_id, timestamp, side, type, price, quantity, fee, fee_asset, pnl)
            VALUES (11, 'okx', 'ETH/USDT', 'o3', 1777768200000, 'SELL', 'market', 90.0, 1.0, 0.0, 'USDT', -3.0);
            """
        )

        conn.commit()

        # run script main() in json-only mode to simplify assertions
        rc = report.main(
            [
                "--db",
                str(db_path),
                "--from-id",
                "10",
                "--to-id",
                "11",
                "--since-hours",
                "48",
                "--prefer-run-start",
                "--limit-trades",
                "5",
                "--json",
            ]
        )
        assert rc == 0

        # capture output by calling internal functions directly (deterministic)
        conn2 = report._connect(str(db_path))
        try:
            strategies = report._fetch_strategies(conn2, 10, 11)
            assert [s.id for s in strategies] == [10, 11]
            st10 = strategies[0]
            st11 = strategies[1]
            assert st10.paper_trading is True
            assert st11.paper_trading is False

            since_ms = report._trade_window_since_ms(st10, since_hours=48.0, prefer_run_start=True)
            agg10, _ = report._aggregate_trades(conn2, 10, since_ms, limit_recent=5)
            assert agg10["total_trades"] == 2
            assert agg10["sell_trades"] == 1
            assert agg10["winning_sells"] == 1
            assert agg10["realized_pnl"] == 12.5

            since_ms11 = report._trade_window_since_ms(st11, since_hours=48.0, prefer_run_start=True)
            agg11, _ = report._aggregate_trades(conn2, 11, since_ms11, limit_recent=5)
            assert agg11["total_trades"] == 1
            assert agg11["sell_trades"] == 1
            assert agg11["winning_sells"] == 0
            assert agg11["realized_pnl"] == -3.0
        finally:
            conn2.close()
    finally:
        conn.close()


def test_superpnl_hourly_report_estimates_paper_positions_from_trades(tmp_path):
    report = _load_report_module()

    db_path = tmp_path / "t2.db"
    conn = sqlite3.connect(str(db_path))
    try:
        _init_db(conn)
        # strategy 10: paper, buy then partial sell
        conn.execute(
            """
            INSERT INTO strategies (id, name, script_content, config, status, exchange, run_started_at)
            VALUES (10, 'SuperPnL-10', 'pass', ?, 'running', 'okx', '2026-05-03T00:00:00Z');
            """,
            (json.dumps({"initial_capital": 10000, "is_paper_trading": True}),),
        )
        conn.execute(
            """
            INSERT INTO strategy_trades
            (strategy_id, exchange, symbol, order_id, timestamp, side, type, price, quantity, fee, fee_asset, pnl)
            VALUES (10, 'okx', 'BTC/USDT', 'o1', 1777767300000, 'BUY', 'market', 100.0, 2.0, 0.0, 'USDT', NULL);
            """
        )
        conn.execute(
            """
            INSERT INTO strategy_trades
            (strategy_id, exchange, symbol, order_id, timestamp, side, type, price, quantity, fee, fee_asset, pnl)
            VALUES (10, 'okx', 'BTC/USDT', 'o2', 1777768200000, 'SELL', 'market', 110.0, 1.0, 0.0, 'USDT', 10.0);
            """
        )
        conn.commit()

        conn2 = report._connect(str(db_path))
        try:
            st = report._fetch_strategies(conn2, 10, 10)[0]
            since_ms = report._trade_window_since_ms(st, since_hours=48.0, prefer_run_start=True)
            state = report._estimate_paper_state(conn2, st, since_ms=since_ms)
            assert isinstance(state, dict)
            positions = state.get("positions") or []
            assert len(positions) == 1
            pos = positions[0]
            assert pos["symbol"] == "BTC/USDT"
            assert abs(float(pos["size"]) - 1.0) < 1e-9

            account = state.get("account") or {}
            # cash: 10000 - 200 + 110 = 9910
            assert abs(float(account.get("cash_est", 0.0)) - 9910.0) < 1e-6
            # with no kline table, mark uses last trade price 110 => notional 110
            assert abs(float(account.get("equity_est", 0.0)) - 10020.0) < 1e-6
            assert abs(float(account.get("total_pnl_est", 0.0)) - 20.0) < 1e-6
        finally:
            conn2.close()
    finally:
        conn.close()


def test_superpnl_hourly_report_config_slice_and_recent_event_summary(tmp_path):
    report = _load_report_module()

    db_path = tmp_path / "t3.db"
    conn = sqlite3.connect(str(db_path))
    try:
        _init_db(conn)
        conn.execute(
            """
            INSERT INTO strategies (id, name, script_content, config, status, exchange, run_started_at)
            VALUES (10, 'SuperPnL-10', 'pass', ?, 'running', 'okx', '2026-05-03T00:00:00Z');
            """,
            (
                json.dumps(
                    {
                        "strategy_key": "superpnl_15m_low_turnover",
                        "initial_capital": 12000,
                        "is_paper_trading": True,
                        "threshold_bps": 12.0,
                        "top_k": 2,
                        "symbols": ["BTC/USDT", "ETH/USDT"],
                        "trade_symbols": ["BTC/USDT"],
                    }
                ),
            ),
        )
        conn.commit()

        conn2 = report._connect(str(db_path))
        try:
            st = report._fetch_strategies(conn2, 10, 10)[0]
            sl = report._config_slice(st.config)
            assert sl.get("strategy_key") == "superpnl_15m_low_turnover"
            assert sl.get("initial_capital") == 12000
            assert sl.get("threshold_bps") == 12.0
            assert sl.get("top_k") == 2
            assert sl.get("symbols_count") == 2
            assert sl.get("trade_symbols_count") == 1

            summary = report._summarize_recent_events(
                [
                    {"decision": "skip_below_threshold", "timestamp": 1000, "time": "t1"},
                    {"decision": "skip_below_threshold", "timestamp": 2000, "time": "t2"},
                    {"decision": "rebalance", "timestamp": 1500, "time": "t1.5"},
                ]
            )
            assert summary is not None
            assert summary.get("latest_event_time") == "t2"
            top = summary.get("top_decisions") or []
            assert top[0]["decision"] == "skip_below_threshold"
            assert top[0]["count"] == 2
        finally:
            conn2.close()
    finally:
        conn.close()
