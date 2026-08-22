from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.v2.endpoints import monitor  # noqa: E402
from app.services import live_profit_push_service as live_profit_push_module  # noqa: E402


class FakeLiveProfitPushService:
    async def build_snapshot(self):
        return {
            "generated_at": "2026-07-28T08:00:00+00:00",
            "statistics_timezone": "Asia/Shanghai",
            "statistics_date": "2026-07-28",
            "statistics_start": "2026-07-28T00:00:00+08:00",
            "statistics_end": "2026-07-28T16:00:00+08:00",
            "statistics_complete": False,
            "statistics_note": "1 个策略的日初浮盈基线在零点后首次建立",
            "strategies": [
                {
                    "strategy_id": 7,
                    "name": "[合约][1H][CTA] SOL · EMA5/20趋势跟踪激进版 · 100U",
                    "subscription_status": "running",
                    "return_pct": 2,
                    "pnl": 2,
                    "daily_realized_pnl": 1,
                    "daily_unrealized_change": 1,
                    "unrealized_pnl": 1.5,
                    "total_trades": 2,
                    "closing_trades": 2,
                    "winning_trades": 1,
                    "win_rate": 50,
                    "statistics_complete": False,
                    "statistics_started_at": "2026-07-28T08:00:00+00:00",
                }
            ],
            "skipped_account_ids": [],
        }


def test_live_strategy_summary_exposes_daily_statistics_contract(monkeypatch):
    monkeypatch.setattr(
        live_profit_push_module,
        "live_profit_push_service",
        FakeLiveProfitPushService(),
    )
    app = FastAPI()
    app.include_router(monitor.router, prefix="/monitor")
    client = TestClient(app)

    response = client.get("/monitor/live-strategy-summaries")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["statistics_period"] == {
        "kind": "asia_shanghai_calendar_day",
        "timezone": "Asia/Shanghai",
        "date": "2026-07-28",
        "start": "2026-07-28T00:00:00+08:00",
        "end": "2026-07-28T16:00:00+08:00",
        "complete": False,
        "note": "1 个策略的日初浮盈基线在零点后首次建立",
        "realized_order_history_limit": 1000,
    }
    strategy = payload["strategies"][0]
    assert strategy["statistics_period"]["kind"] == "asia_shanghai_calendar_day"
    assert strategy["statistics_period"]["complete"] is False
    assert strategy["total_pnl"] == 2
    assert strategy["daily_realized_pnl"] == 1
    assert strategy["daily_unrealized_change"] == 1
    assert strategy["current_unrealized_pnl"] == 1.5
    assert "latest 100" not in " ".join(payload["limitations"])
