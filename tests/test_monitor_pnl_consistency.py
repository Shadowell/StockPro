from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import strategy_engine as strategy_engine_module  # noqa: E402
from app.services.strategy_engine import (  # noqa: E402
    PaperBroker,
    StrategyContext,
    StrategyEngine,
    StrategyStatus,
)


class FakeExchange:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_ticker(self, symbol: str) -> dict[str, float]:
        self.calls.append(symbol)
        prices = {
            "PEPE/USDT": 1.2,
            "APE/USDT": 9.0,
        }
        return {"last": prices[symbol]}


def test_running_strategy_monitor_refreshes_spot_marks_and_hides_dust(monkeypatch) -> None:
    engine = StrategyEngine()
    context = StrategyContext(
        strategy_id=26,
        name="[现货] pnl monitor",
        exchange="okx",
        symbols=["PEPE/USDT", "APE/USDT"],
        config={"is_paper_trading": True},
    )
    context.status = StrategyStatus.RUNNING
    engine._contexts[26] = context

    broker = PaperBroker(
        initial_capital=10_000.0,
        commission_rate=0.0,
        slippage_rate=0.0,
        strategy_id=26,
        exchange_name="okx",
    )
    broker.balance = 9_000.0
    broker.positions["PEPE/USDT"] = {
        "size": 1_000.0,
        "entry_price": 1.0,
        "side": "long",
        "unrealized_pnl": 0.0,
    }
    broker.positions["APE/USDT"] = {
        "size": 1e-12,
        "entry_price": 9.0,
        "side": "long",
        "unrealized_pnl": 0.0,
    }
    broker._last_prices.update({"PEPE/USDT": 1.0, "APE/USDT": 9.0})
    engine._strategy_instances[26] = SimpleNamespace(broker=broker)

    fake_exchange = FakeExchange()
    monkeypatch.setattr(
        strategy_engine_module.exchange_manager,
        "get_exchange",
        lambda exchange_name: fake_exchange,
    )

    rows = engine.get_all_running(refresh_marks=True)

    assert fake_exchange.calls == ["PEPE/USDT"]
    assert len(rows) == 1
    status = rows[0]
    assert status["unrealized_pnl"] == pytest.approx(200.0)
    assert status["pnl"] == pytest.approx(200.0)
    assert status["equity"] == pytest.approx(10_200.0)
    assert status["positions"]["PEPE/USDT"]["mark_price"] == pytest.approx(1.2)
    assert status["positions"]["PEPE/USDT"]["unrealized_pnl"] == pytest.approx(200.0)
    assert "APE/USDT" not in status["positions"]


def test_running_strategy_status_exposes_exit_trade_win_rate(monkeypatch) -> None:
    engine = StrategyEngine()
    context = StrategyContext(
        strategy_id=31,
        name="[合约] monitor win rate",
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
        config={"is_paper_trading": True, "market_type": "swap"},
    )
    context.status = StrategyStatus.RUNNING
    context.started_at = datetime(2026, 5, 5, tzinfo=timezone.utc)
    engine._contexts[31] = context

    broker = PaperBroker(
        initial_capital=10_000.0,
        commission_rate=0.0,
        slippage_rate=0.0,
        strategy_id=31,
        exchange_name="okx",
    )
    engine._strategy_instances[31] = SimpleNamespace(broker=broker)

    rows = [
        {"side": "open_long", "pnl": 0},
        {"side": "close_long", "pnl": 3.2},
        {"side": "close_short", "pnl": -1.0},
        {"side": "sell", "pnl": 0.8},
    ]
    monkeypatch.setattr(
        strategy_engine_module.db,
        "get_strategy_trades_since",
        lambda strategy_id, since_ms: rows,
    )

    status = engine.get_all_running()[0]

    assert status["total_trades"] == 4
    assert status["closing_trades"] == 3
    assert status["winning_trades"] == 2
    assert status["win_rate"] == pytest.approx(66.6667)
    assert status["gross_profit"] == pytest.approx(4.0)
    assert status["gross_loss"] == pytest.approx(1.0)
    assert status["profit_factor"] == pytest.approx(4.0)


def test_running_strategy_status_marks_ai_autonomous_strategy() -> None:
    engine = StrategyEngine()
    context = StrategyContext(
        strategy_id=45,
        name="[合约] AI自主交易员 · 模拟盘 test",
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
        config={
            "strategy_key": "ai_autonomous_trader",
            "ai_autonomous_trader": True,
            "is_paper_trading": True,
            "market_type": "swap",
        },
    )
    context.status = StrategyStatus.RUNNING
    engine._contexts[45] = context

    status = engine.get_all_running()[0]

    assert status["strategy_key"] == "ai_autonomous_trader"
    assert status["is_ai_autonomous"] is True
