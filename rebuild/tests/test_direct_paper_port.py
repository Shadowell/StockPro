from __future__ import annotations

import asyncio
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.paper.service import PaperDomainService  # noqa: E402


class FakePaperRepository:
    def list_instances(self):
        return [{"id": 11, "instance_uuid": "paper-uuid", "name": "A股模拟", "status": "running", "strategy_id": 224, "strategy_name": "A股动量", "initial_cash": 1_000_000, "cash_balance": 900_000, "created_at": "2026-08-25T12:00:00+08:00", "symbols": ["600519.SH"]}]

    def get_instance(self, instance_id): return self.list_instances()[0] if int(instance_id) == 11 else None
    def positions(self, instance_id): return [{"symbol": "600519.SH", "name": "贵州茅台", "quantity": 100, "available_quantity": 100, "avg_cost": 1400, "last_price": 1500, "market_value": 150000}]
    def trades(self, instance_id, limit): return [{"id": 1, "symbol": "600519.SH", "side": "buy", "price": 1400, "quantity": 100, "commission": 5, "traded_at": "2026-08-25T12:00:00+08:00"}]
    def events(self, instance_id, limit): return [{"event_type": "cycle", "level": "info", "message": "done", "occurred_at": "2026-08-25T12:00:00+08:00"}]
    def equity_curve(self, instance_id): return [{"trade_date": "2025-01-01", "equity": 1_000_000, "drawdown": 0}, {"trade_date": "2025-01-02", "equity": 1_050_000, "drawdown": 0}]


def test_bitpro_live_workspace_maps_a_share_paper_instances_and_dashboard():
    service = PaperDomainService(FakePaperRepository())
    items = asyncio.run(service.list_instances())
    dashboard = asyncio.run(service.dashboard(11))

    assert items[0]["config"]["is_paper_trading"] is True
    assert items[0]["exchange"] == "CN"
    assert dashboard["system"]["mode"] == "paper"
    assert dashboard["system"]["symbol"] == "600519.SH"
    assert dashboard["equity"]["current"] == 1_050_000
    assert dashboard["performance"]["total_pnl_pct"] == 5.0
    assert dashboard["positions"][0]["symbol"] == "600519.SH"
