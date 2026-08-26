"""数据中心 OKX 原生数据同步的调度与配置契约测试。

覆盖：配置归一化与持久化（app_settings key）、到期判断、disabled 跳过、
rubik/OI 独立计时；不访问网络。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest


@pytest.fixture()
def svc_module(monkeypatch, tmp_path):
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "DB_PATH", str(tmp_path / "t.db"))
    local_db = importlib.import_module("app.db.local_db")
    importlib.reload(local_db)
    mod = importlib.import_module("app.services.okx_native_sync_service")
    importlib.reload(mod)
    return mod


def test_schedule_config_persists_and_clamps(svc_module):
    svc = svc_module.OkxNativeSyncService()
    result = svc.update_schedule_config({
        "enabled": True,
        "rubik_interval_minutes": 1,
        "oi_interval_minutes": 99999,
        "ccys": ["btc", "eth"],
    })
    assert result["enabled"] is True
    assert result["rubik_interval_minutes"] == 10
    assert result["oi_interval_minutes"] == 1440
    assert result["ccys"] == ["BTC", "ETH"]
    # persisted across instances
    again = svc_module.OkxNativeSyncService()
    assert again.schedule_config()["enabled"] is True
    assert again.schedule_config()["rubik_interval_minutes"] == 10


def test_run_due_disabled(svc_module):
    svc = svc_module.OkxNativeSyncService()
    import asyncio

    assert asyncio.run(svc.run_due())["skipped"] == "disabled"


def test_run_due_not_due_when_recently_ran(svc_module):
    svc = svc_module.OkxNativeSyncService()
    svc.update_schedule_config({"enabled": True})
    svc._mark("rubik", last_rubik_run_at="2100-01-01T00:00:00")
    svc._mark("oi", last_oi_run_at="2100-01-01T00:00:00")
    import asyncio

    assert asyncio.run(svc.run_due())["skipped"] == "not_due"


def test_run_due_triggers_only_oi_when_rubik_fresh(svc_module, monkeypatch):
    svc = svc_module.OkxNativeSyncService()
    svc.update_schedule_config({"enabled": True})
    svc._mark("rubik", last_rubik_run_at="2100-01-01T00:00:00")  # not due

    calls = []

    async def fake_oi():
        calls.append("oi")
        return {"ok": True, "instruments": 1}

    monkeypatch.setattr(svc, "run_oi_snapshot", fake_oi)
    import asyncio

    result = asyncio.run(svc.run_due())
    assert calls == ["oi"]
    assert result["oi"]["ok"] is True


def test_rubik_upsert_idempotent_and_counts(svc_module):
    svc = svc_module.OkxNativeSyncService()
    rows = [["1787500800000", "100.0", "90.0"]]
    assert svc._upsert_rubik("taker_volume", "BTC", rows, two_values=True) == 1
    assert svc._upsert_rubik("taker_volume", "BTC", rows, two_values=True) == 1
    assert svc.schedule_config()["rubik_row_count"] == 1


def test_oi_upsert_filters_non_usdt_and_zero(svc_module):
    svc = svc_module.OkxNativeSyncService()
    inserted = svc._upsert_oi([
        {"instId": "BTC-USDT-SWAP", "oiCcy": "10", "oiUsd": "100"},
        {"instId": "ETH-USD-SWAP", "oiCcy": "1", "oiUsd": "1"},
        {"instId": "SOL-USDT-SWAP", "oiCcy": "0", "oiUsd": "0"},
    ])
    assert inserted == 1
    assert svc._oi_counts() == (1, 1)
