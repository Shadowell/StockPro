from __future__ import annotations

import asyncio
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.paper.service import PaperDomainService  # noqa: E402


class FakePaperRepository:
    def __init__(self):
        self.status = "running"
        self.history = {"trades": 12, "events": 30, "equity": 50, "positions": 2}
        self.created_payload = None

    def list_instances(self):
        return [{"id": 11, "instance_uuid": "paper-uuid", "name": "A股模拟", "status": self.status, "strategy_id": 224, "strategy_name": "A股动量", "initial_cash": 1_000_000, "cash_balance": 900_000, "created_at": "2026-08-25T12:00:00+08:00", "symbols": ["600519.SH"]}]

    def get_instance(self, instance_id): return self.list_instances()[0] if int(instance_id) == 11 else None
    def positions(self, instance_id): return [{"symbol": "600519.SH", "name": "贵州茅台", "quantity": 100, "available_quantity": 100, "avg_cost": 1400, "last_price": 1500, "market_value": 150000}]
    def trades(self, instance_id, limit): return [{"id": 1, "symbol": "600519.SH", "side": "buy", "price": 1400, "quantity": 100, "commission": 5, "traded_at": "2026-08-25T12:00:00+08:00"}]
    def events(self, instance_id, limit): return [{"event_type": "cycle", "level": "info", "message": "done", "occurred_at": "2026-08-25T12:00:00+08:00"}]
    def equity_curve(self, instance_id): return [{"trade_date": "2025-01-01", "equity": 1_000_000, "drawdown": 0}, {"trade_date": "2025-01-02", "equity": 1_050_000, "drawdown": 0}]
    def list_candidates(self): return [{"strategy_id": 224, "strategy_name": "A股动量", "qualifying_backtest_run_id": "run-1", "return_pct": 12.0}]
    def create_instance(self, payload): self.created_payload = dict(payload); self.status = "draft"; return self.list_instances()[0]
    def start(self, instance_id): self.status = "running"; return self.list_instances()[0]
    def pause(self, instance_id): self.status = "paused"; return self.list_instances()[0]
    def resume(self, instance_id): self.status = "running"; return self.list_instances()[0]
    def stop(self, instance_id): self.status = "stopped"; return self.list_instances()[0]


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


def test_paper_lifecycle_creates_from_eligible_backtest_and_preserves_history():
    repository = FakePaperRepository()
    service = PaperDomainService(repository)
    candidates = asyncio.run(service.list_candidates())
    created = asyncio.run(service.create({"name": "新模拟", "qualifying_backtest_run_id": "run-1", "initial_cash": 1_000_000}, start=True))
    baseline = dict(repository.history)
    paused = asyncio.run(service.pause(11))
    resumed = asyncio.run(service.resume(11))
    stopped = asyncio.run(service.stop(11))
    assert candidates[0]["strategy_id"] == 224
    assert created["status"] == "running"
    assert paused["status"] == "paused"
    assert resumed["status"] == "running"
    assert stopped["status"] == "stopped"
    assert repository.history == baseline
    assert repository.created_payload["qualifying_backtest_run_id"] == "run-1"


def test_bitpro_paper_ui_uses_admin_lifecycle_and_a_share_candidates():
    page = (BACKEND_ROOT.parent / "frontend/src/pages/liveTrading/index.tsx").read_text()
    wizard = (BACKEND_ROOT.parent / "frontend/src/pages/liveTrading/CreateWizard.tsx").read_text()
    constants = (BACKEND_ROOT.parent / "frontend/src/pages/liveTrading/constants.ts").read_text()
    assert "const readOnly = !isAdmin" in page
    assert "liveApi.getPaperCandidates()" in page
    assert "liveApi.createPaperInstance" in page
    assert "模拟初始资金 (CNY)" in wizard
    assert "DEFAULT_PAPER_TIMEFRAME = '1d'" in constants
    assert "DEFAULT_PAPER_INITIAL_EQUITY = 1_000_000" in constants
