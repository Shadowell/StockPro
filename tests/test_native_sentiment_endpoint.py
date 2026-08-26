"""首页加密原生数据聚合端点的离线测试。

覆盖：rubik/OI/funding 聚合查询、OI 24h 变化计算、空表安全、
symbol 别名（BTC-USDT-SWAP 与 BTC/USDT:USDT）。不访问网络。
"""

from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DAY_MS = 86_400_000
NOW_MS = 1_787_600_000_000  # fixed anchor


@pytest.fixture()
def svc(monkeypatch, tmp_path):
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "DB_PATH", str(tmp_path / "t.db"))
    local_db = importlib.import_module("app.db.local_db")
    importlib.reload(local_db)
    mod = importlib.import_module("app.api.v2.endpoints.native_sentiment")
    importlib.reload(mod)
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.executescript(
        """
        CREATE TABLE okx_rubik_stats (metric TEXT, ccy TEXT, timestamp INTEGER, value REAL, value2 REAL);
        CREATE TABLE funding_rate_history (exchange TEXT, symbol TEXT, timestamp INTEGER, funding_rate REAL);
        CREATE TABLE open_interest_history (exchange TEXT, symbol TEXT, timestamp INTEGER, open_interest REAL, open_interest_value REAL);
        """
    )
    conn.commit()
    return mod


def seed(conn, sql, rows):
    conn.executemany(sql, rows)
    conn.commit()


def test_core_aggregation_and_oi_change(svc, tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    seed(conn, "INSERT INTO okx_rubik_stats VALUES (?,?,?,?,?)", [
        ("taker_volume", "BTC", NOW_MS - DAY_MS, 100.0, 150.0),
        ("taker_volume", "BTC", NOW_MS - DAY_MS + 1, 100.0, 150.0),
    ])
    seed(conn, "INSERT INTO okx_rubik_stats VALUES (?,?,?,?,?)", [
        ("long_short_ratio", "BTC", NOW_MS - DAY_MS, 1.2, None),
    ])
    seed(conn, "INSERT INTO funding_rate_history (exchange, symbol, timestamp, funding_rate) VALUES (?,?,?,?)", [
        ("okx", "BTC-USDT-SWAP", NOW_MS - 3600_000, 0.0001),
    ])
    seed(conn, "INSERT INTO open_interest_history VALUES (?,?,?,?,?)", [
        ("binanceusdm", "BTC/USDT:USDT", NOW_MS - DAY_MS, 100.0, 200.0),
        ("binanceusdm", "BTC/USDT:USDT", NOW_MS, 110.0, 220.0),
    ])
    conn.close()

    payload = svc._core_symbol_payload("BTC")
    assert payload["taker"]["buy_ratio"] == pytest.approx(0.6)
    assert payload["long_short_ratio"]["value"] == 1.2
    assert payload["funding_rate"]["value"] == pytest.approx(0.0001)
    assert payload["oi"]["open_interest"] == 110.0
    assert payload["oi"]["change_24h_pct"] == pytest.approx(10.0)


def test_pipeline_spans(svc, tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    seed(conn, "INSERT INTO okx_rubik_stats VALUES (?,?,?,?,?)", [
        ("taker_volume", "BTC", NOW_MS, 1.0, 2.0),
    ])
    seed(conn, "INSERT INTO open_interest_history VALUES (?,?,?,?,?)", [
        ("binanceusdm", "BTC/USDT:USDT", NOW_MS, 1.0, 2.0),
    ])
    conn.close()
    pipeline = svc._pipeline_payload()
    assert pipeline["rubik_taker_volume"]["rows"] == 1
    assert pipeline["oi_binance_backfill"]["rows"] == 1
    assert pipeline["oi_okx_forward"]["rows"] == 0
    assert pipeline["funding_okx"]["rows"] == 0


def test_empty_tables_are_safe(svc):
    payload = svc._core_symbol_payload("BTC")
    assert "taker" not in payload or payload["taker"].get("buy_ratio") is None
    assert "oi" not in payload
    pipeline = svc._pipeline_payload()
    assert all(span["rows"] == 0 for span in pipeline.values())


def test_native_sentiment_endpoint_shape(svc, monkeypatch):
    import asyncio

    monkeypatch.setattr(svc, "CORE_CCYS", ["BTC"])
    result = asyncio.run(svc.native_sentiment())
    payload = result.get("data") or result
    core = payload["core"]
    assert len(core) == 1 and core[0]["ccy"] == "BTC"
    assert set(payload["pipeline"].keys()) == {
        "rubik_taker_volume", "rubik_long_short", "oi_okx_forward",
        "oi_binance_backfill", "funding_okx",
    }
