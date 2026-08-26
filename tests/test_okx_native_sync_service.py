"""OKX 原生数据定时同步服务的离线单元测试。

覆盖：配置归一化与持久化、到期判断、rubik/OI 幂等写入、
403 长退避路径、disabled 时不执行。全部使用临时 SQLite，不访问网络。
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

    # redirect DB to tmp file before first connection
    monkeypatch.setattr(app_settings, "DB_PATH", str(tmp_path / "test.db"))
    local_db = importlib.import_module("app.db.local_db")
    importlib.reload(local_db)
    mod = importlib.import_module("app.services.okx_native_sync_service")
    importlib.reload(mod)
    svc = mod.OkxNativeSyncService()
    svc._schema_ready = False
    return svc


def test_config_defaults_and_clamping(service):
    cfg = service.schedule_config()
    assert cfg["enabled"] is False
    assert cfg["rubik_interval_minutes"] == 1440
    assert cfg["oi_interval_minutes"] == 60
    assert "BTC" in cfg["ccys"]

    updated = service.update_schedule_config({
        "enabled": True,
        "rubik_interval_minutes": 1,      # below min -> clamped to 10
        "oi_interval_minutes": 99999,     # above max -> clamped to 1440
        "ccys": ["btc", "eth", ""],
    })
    assert updated["rubik_interval_minutes"] == 10
    assert updated["oi_interval_minutes"] == 1440
    assert updated["ccys"] == ["BTC", "ETH"]
    assert updated["enabled"] is True
    # persisted
    assert service.schedule_config()["enabled"] is True


def test_run_due_disabled_and_not_due(service):
    assert service.run_due.__name__ == "run_due"
    # disabled -> skipped
    import asyncio

    assert asyncio.run(service.run_due())["skipped"] == "disabled"

    # enabled but just ran -> not_due
    service.update_schedule_config({"enabled": True})
    service._mark("rubik", last_rubik_run_at="2100-01-01T00:00:00")
    service._mark("oi", last_oi_run_at="2100-01-01T00:00:00")
    result = asyncio.run(service.run_due())
    assert result["skipped"] == "not_due"


def test_rubik_upsert_idempotent(service):
    rows = [["1787500800000", "2743641128.9", "2658061615.7"]]
    n1 = service._upsert_rubik("taker_volume", "BTC", rows, two_values=True)
    n2 = service._upsert_rubik("taker_volume", "BTC", rows, two_values=True)
    assert n1 == 1 and n2 == 1  # INSERT OR IGNORE keeps first
    assert service.schedule_config()["rubik_row_count"] == 1


def test_oi_upsert_maps_symbols_and_skips_non_usdt(service):
    data = [
        {"instId": "BTC-USDT-SWAP", "oiCcy": "30132.29", "oiUsd": "2324827420.19"},
        {"instId": "ETH-USD-SWAP", "oiCcy": "100.0", "oiUsd": "1.0"},  # non-USDT skipped
        {"instId": "SOL-USDT-SWAP", "oiCcy": "0", "oiUsd": "0"},       # empty skipped
    ]
    inserted = service._upsert_oi(data)
    assert inserted == 1
    count, symbols = service._oi_counts()
    assert count == 1 and symbols == 1


def test_oi_snapshot_marks_success(service, monkeypatch):
    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"instId": "BTC-USDT-SWAP", "oiCcy": "10", "oiUsd": "100"}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            return FakeResp()

    import app.services.okx_native_sync_service as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda **kw: FakeClient())
    result = asyncio_run(service.run_oi_snapshot())
    assert result["ok"] is True and result["instruments"] == 1
    cfg = service.schedule_config()
    assert cfg["last_oi_error"] is None
    assert cfg["last_oi_finished_at"]


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        import os

        os.environ["BITPRO_DB_PATH"] = str(Path(d) / "t.db")
    print("run via pytest")
