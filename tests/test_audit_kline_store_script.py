from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

SCRIPT_PATH = ROOT / "scripts" / "audit_kline_store.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_kline_store", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _polluted_rows() -> pd.DataFrame:
    start = 1_752_624_000_000
    closes = [100, 150, 99, 151, 98, 152, 97, 153]
    return pd.DataFrame([
        {
            "timestamp": start + index * 3_600_000,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 10,
        }
        for index, close in enumerate(closes)
    ])


def test_fetch_okx_history_rows_uses_native_swap_history_candles(monkeypatch) -> None:
    module = _load_module()
    calls: list[dict] = []

    class FakeResponse:
        def __init__(self, payload: dict):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    payloads = [
        {
            "data": [
                ["2000000", "10", "11", "9", "10.5", "100"],
                ["1000000", "9", "10", "8", "9.5", "90"],
            ]
        },
        {"data": []},
    ]

    def fake_get(_url, *, params, timeout):
        calls.append(dict(params))
        return FakeResponse(payloads.pop(0))

    monkeypatch.setattr(module.requests, "get", fake_get)

    rows = module._fetch_okx_history_rows(
        symbol="SOL/USDT:USDT",
        timeframe="1h",
        start_ms=1_000_000,
        end_ms=2_000_000,
        max_per_request=300,
        delay_sec=0,
    )

    assert calls[0]["instId"] == "SOL-USDT-SWAP"
    assert calls[0]["bar"] == "1H"
    assert calls[0]["after"] == str(2_000_000 + module.TIMEFRAME_MS["1h"])
    assert calls[0]["limit"] == "100"
    assert [row["timestamp"] for row in rows] == [1_000_000, 2_000_000]
    assert rows[0]["open"] == 9.0


def test_audit_store_finds_polluted_file_and_marks_backtests(tmp_path) -> None:
    module = _load_module()
    kline_dir = tmp_path / "klines" / "okx" / "SOL-USDT_USDT" / "1h"
    kline_dir.mkdir(parents=True)
    _polluted_rows().to_csv(kline_dir / "202506.csv", index=False)

    findings = module.audit_store(
        root_dir=tmp_path / "klines",
        exchange="okx",
        symbols=["SOL/USDT:USDT"],
        timeframes=["1h"],
    )

    assert len(findings) == 1
    assert findings[0]["symbol"] == "SOL/USDT:USDT"
    assert findings[0]["timeframe"] == "1h"
    assert findings[0]["last_issue_timestamp"] > findings[0]["first_issue_timestamp"]
    assert findings[0]["issues"][0]["type"] == "repeated_discontinuity"

    db_path = tmp_path / "crypto_data.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE strategies (
            id INTEGER PRIMARY KEY,
            name TEXT,
            config TEXT,
            symbols TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE backtest_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id INTEGER,
            start_date TEXT,
            end_date TEXT,
            timeframe TEXT,
            data_quality_status TEXT,
            data_quality_message TEXT,
            data_quality_checked_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO strategies (id, name, config, symbols) VALUES (?, ?, ?, ?)",
        (
            105,
            "[合约][1H][CTA] SOL · EMA5/20趋势跟踪对照版 · 100U",
            json.dumps({"timeframe": "1h", "trade_symbols": ["SOL/USDT:USDT"]}),
            json.dumps(["SOL/USDT:USDT"]),
        ),
    )
    conn.execute(
        "INSERT INTO backtest_results (strategy_id, start_date, end_date, timeframe) VALUES (?, ?, ?, ?)",
        (105, "2025-06-08", "2026-06-07", "1h"),
    )
    conn.commit()
    conn.close()

    marked = module.mark_backtest_results_invalidated(db_path, findings)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT data_quality_status, data_quality_message FROM backtest_results"
    ).fetchone()
    conn.close()
    assert marked == 1
    assert row[0] == "invalidated"
    assert "SOL/USDT:USDT 1h" in row[1]
