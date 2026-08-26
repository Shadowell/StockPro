"""OKX 大单逐笔流采集服务的离线单元测试。

覆盖：名义阈值过滤（px*sz*ctVal）、side 校验、批量落库幂等
（UNIQUE(inst_id, trade_id)）、schema 创建、状态暴露。
全部使用临时 SQLite，不访问网络。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture()
def service(tmp_path, monkeypatch):
    import importlib

    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "DB_PATH", str(tmp_path / "test.db"))
    local_db = importlib.import_module("app.db.local_db")
    importlib.reload(local_db)
    mod = importlib.import_module("app.services.okx_large_trade_stream_service")
    importlib.reload(mod)
    svc = mod.OkxLargeTradeStreamService()
    svc._ensure_schema()
    svc._inst_ids = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    # 模拟已加载 ctVal（key 为 OKX 原生 instId）：BTC 0.01 / ETH 0.1 币每张
    svc._ct_val = {"BTC-USDT-SWAP": 0.01, "ETH-USDT-SWAP": 0.1}
    svc._min_notional = 50_000.0
    return svc


def _trade(trade_id, px, sz, side="buy", inst="BTC-USDT-SWAP", ts=1_700_000_000_000):
    """模拟 OKX 真实推送：instId 为原生格式（BTC-USDT-SWAP）。"""
    return {"instId": inst, "tradeId": str(trade_id), "px": str(px), "sz": str(sz), "side": side, "ts": str(ts)}


def test_ingest_filters_by_notional(service):
    # BTC 0.01 张/张：px=50000, sz=50 → 名义 50000*50*0.01 = 25000 < 5万 → 过滤
    service._ingest_trades([_trade("t1", 50000, 50)])
    assert len(service._buffer) == 0
    assert service._status["total_filtered"] == 1

    # px=50000, sz=150 → 名义 75000 ≥ 5万 → 保留
    service._ingest_trades([_trade("t2", 50000, 150)])
    assert len(service._buffer) == 1
    inst, tid, px, sz_c, sz_b, notional, side, ts, _ = service._buffer[0]
    assert inst == "BTC/USDT:USDT" and tid == "t2"
    assert notional == pytest.approx(75_000.0)
    assert sz_b == pytest.approx(1.5)
    assert side == "buy"


def test_ingest_rejects_unknown_ctval_and_bad_side(service):
    service._ingest_trades([_trade("t1", 100, 5, side="buy", inst="UNKNOWN-SWAP")])
    service._ingest_trades([_trade("t2", 50000, 150, side="open_long")])
    assert len(service._buffer) == 0
    assert service._status["total_filtered"] == 2


def test_flush_persists_and_is_idempotent(service):
    service._ingest_trades([
        _trade("a", 50000, 150),
        _trade("b", 51000, 200, side="sell"),
    ])
    service._flush_buffer()
    assert len(service._buffer) == 0

    from app.db.local_db import db_instance
    conn = db_instance.get_connection()
    rows = conn.execute("SELECT trade_id, notional_usdt FROM okx_large_trades ORDER BY trade_id").fetchall()
    assert [r["trade_id"] for r in rows] == ["a", "b"]

    # 同一批重复推送：INSERT OR IGNORE 不产生重复
    service._ingest_trades([_trade("a", 50000, 150)])
    service._flush_buffer()
    count = conn.execute("SELECT COUNT(*) AS c FROM okx_large_trades").fetchone()["c"]
    assert count == 2


def test_eth_ctval_scaling(service):
    # ETH 0.1 张/张：px=3000, sz=200 → 名义 3000*200*0.1 = 60000 ≥ 5万
    service._ingest_trades([_trade("e1", 3000, 200, inst="ETH-USDT-SWAP")])
    assert len(service._buffer) == 1
    assert service._buffer[0][5] == pytest.approx(60_000.0)


def test_status_exposes_counters(service):
    service._ingest_trades([_trade("a", 50000, 150)])
    status = service.get_status()
    assert status["total_ingested"] == 1
    assert status["buffer_size"] == 1
    assert status["min_notional_usdt"] == 50_000.0
    assert status["enabled"] is False  # start() 未调用
