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
    def accounts(self): return [{"account_id": "paper:11", "name": "A股模拟", "exchange": "CN", "exchange_alias": "A股", "is_default": True, "configured": True, "enabled": True, "testnet": True, "display_only": False, "can_trade": True}]
    def account_positions(self, account_id): return [{"symbol": "600519.SH", "asset_type": "stock", "amount": 100, "free": 100, "notional": 150000, "entry_price": 1400, "mark_price": 1500, "unrealized_pnl": 10000}]
    def account_orders(self, account_id, limit): return [{"id": "order-1", "symbol": "600519.SH", "side": "buy", "status": "filled"}]
    def watchlist(self, account_id, limit): return [{"symbol": "600519.SH", "source_strategy_id": 224, "source_strategy_name": "A股动量", "order_count": 1}]
    def watch_market(self, account_id, symbol, timeframe, limit): return {"account_id": account_id, "exchange": "CN", "symbol": symbol, "timeframe": "1d", "ticker": {"last": 1500}, "klines": [{"timestamp": 1, "open": 1400, "high": 1510, "low": 1390, "close": 1500, "volume": 1000}], "orderbook": {"bids": [], "asks": []}, "recent_trades": [], "positions": self.account_positions(account_id)}
    def trade_markers(self, account_id, symbol, limit): return [{"id": 1, "label": "B", "symbol": symbol, "price": 1400, "quantity": 100, "timestamp": 1, "source_strategy_id": 224, "source_strategy_name": "A股动量", "subscription_id": 11}]


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


def test_paper_instance_symbols_are_canonical_and_deduplicated():
    repository = FakePaperRepository()
    repository.list_instances = lambda: [{
        **FakePaperRepository().list_instances()[0],
        "symbols": ["SH_600519", "600519.SH", "SZ_000333", "000333.SZ"],
    }]
    items = asyncio.run(PaperDomainService(repository).list_instances())
    assert items[0]["symbols"] == ["600519.SH", "000333.SZ"]


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
    symbol_icon = (BACKEND_ROOT.parent / "frontend/src/components/SymbolIcon.tsx").read_text()
    assert "const readOnly = !isAdmin" in page
    assert "liveApi.getPaperCandidates()" in page
    assert "liveApi.createPaperInstance" in page
    assert "liveApi.advance(qid, 1)" in page
    assert "模拟初始资金 (CNY)" in wizard
    assert "DEFAULT_PAPER_TIMEFRAME = '1d'" in constants
    assert "DEFAULT_PAPER_INITIAL_EQUITY = 1_000_000" in constants
    assert "if (isAShareSymbol) return null" in symbol_icon


def test_watch_workspace_reads_real_paper_accounts_positions_orders_and_market():
    service = PaperDomainService(FakePaperRepository())
    accounts = asyncio.run(service.accounts())
    positions = asyncio.run(service.account_positions("paper:11"))
    orders = asyncio.run(service.account_orders("paper:11", 100))
    watchlist = asyncio.run(service.watchlist("paper:11", 100))
    market = asyncio.run(service.watch_market("paper:11", "600519.SH", "1d", 180))
    markers = asyncio.run(service.trade_markers("paper:11", "600519.SH", 100))
    assert accounts[0]["exchange"] == "CN"
    assert positions[0]["symbol"] == "600519.SH" and positions[0]["free"] == 100
    assert orders[0]["status"] == "filled"
    assert watchlist[0]["order_count"] == 1
    assert market["klines"][0]["close"] == 1500
    assert markers[0]["label"] == "B"


def test_watch_workspace_returns_honest_empty_lists_when_production_has_no_paper_account():
    class EmptyPaperRepository(FakePaperRepository):
        def account_positions(self, account_id): raise ValueError("没有可用 A 股 Paper 账户")
        def account_orders(self, account_id, limit): raise ValueError("没有可用 A 股 Paper 账户")
        def watchlist(self, account_id, limit): raise ValueError("没有可用 A 股 Paper 账户")
    service = PaperDomainService(EmptyPaperRepository())
    assert asyncio.run(service.account_positions("default")) == []
    assert asyncio.run(service.account_orders("default", 50)) == []
    assert asyncio.run(service.watchlist("default", 100)) == []
