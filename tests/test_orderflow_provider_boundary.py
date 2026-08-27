from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import orderflow  # noqa: E402
from app.domain.orderflow.realtime_minute import (  # noqa: E402
    RealtimeMinuteOrderflowService,
)


class FakeRealtimeMinuteProvider:
    configured = True
    calls = 0

    def rt_min(self, ts_code: str, freq: str) -> list[dict[str, object]]:
        type(self).calls += 1
        assert ts_code == "600519.SH"
        assert freq == "1MIN"
        return [
            {
                "ts_code": "600519.SH",
                "time": "2026-08-27 09:31:00",
                "open": 1600.0,
                "close": 1601.0,
                "high": 1602.0,
                "low": 1599.0,
                "vol": 1000.0,
                "amount": 1_601_000.0,
            }
        ]


def _client(monkeypatch) -> TestClient:
    FakeRealtimeMinuteProvider.calls = 0
    service = RealtimeMinuteOrderflowService(
        provider_factory=FakeRealtimeMinuteProvider,
        clock=lambda: datetime(2026, 8, 27, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    monkeypatch.setattr(orderflow, "realtime_minute_service", service)
    app = FastAPI()
    app.include_router(orderflow.router, prefix="/api/v2/orderflow")
    return TestClient(app)


def test_orderflow_stream_status_declares_realtime_minute_fallback(monkeypatch) -> None:
    response = _client(monkeypatch).get("/api/v2/orderflow/stream-status")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["enabled"] is True
    assert payload["connected"] is True
    assert payload["permission_state"] == "available"
    assert payload["provider_source"] == "tushare.rt_min"
    assert payload["data_status"] == "realtime_minute_fallback"
    assert "not tick/Level-2" in payload["frequency"]
    assert "minute_bars" in payload["tables"]


def test_orderflow_bars_uses_tushare_realtime_minute(monkeypatch) -> None:
    response = _client(monkeypatch).get(
        "/api/v2/orderflow/bars?inst_id=600519.SH&bar_minutes=1&hours=6"
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["count"] == 1
    assert payload["data_status"] == "realtime_minute_fallback"
    assert payload["provider_source"] == "tushare.rt_min"
    assert payload["items"][0]["symbol"] == "600519.SH"
    assert payload["items"][0]["amount"] == 1_601_000.0
    assert payload["items"][0]["close_px"] == 1601.0
    assert payload["items"][0]["delta"] == 0.0


def test_orderflow_bars_reuses_realtime_minute_cache(monkeypatch) -> None:
    client = _client(monkeypatch)

    first = client.get("/api/v2/orderflow/bars?inst_id=600519.SH&bar_minutes=1&hours=6")
    second = client.get("/api/v2/orderflow/bars?inst_id=600519.SH&bar_minutes=1&hours=6")

    assert first.status_code == 200
    assert second.status_code == 200
    assert FakeRealtimeMinuteProvider.calls == 1
    assert second.json()["data"]["cache_age_seconds"] == 0


def test_orderflow_large_trades_keeps_tick_provider_boundary(monkeypatch) -> None:
    response = _client(monkeypatch).get("/api/v2/orderflow/large-trades?inst_id=600519.SH")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["items"] == []
    assert payload["permission_state"] == "requires_tick_provider"
    assert payload["provider_source"] == "A-share Level-2/tick vendor"
    assert payload["frequency"] == "realtime_ticks"
    assert "trade_ticks" in payload["tables"]
    assert payload["minute_fallback"]["provider_source"] == "tushare.rt_min"


def test_orderflow_frontend_collapses_provider_missing_state() -> None:
    page = (ROOT / "frontend/src/pages/OrderFlow.tsx").read_text(encoding="utf-8")
    client = (ROOT / "frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "permissionState?: string" in client
    assert "providerSource?: string" in client
    assert "const providerMissing = Boolean(" in page
    assert "const minuteFallback = Boolean(" in page
    assert "TuShare 实时分钟线" in page
    assert "不是 tick/L2" in page
    assert "streamStatus.permissionState === 'requires_configuration'" in page
    assert "A 股 tick Provider 未配置" in page
    assert "{!providerMissing && (" in page
