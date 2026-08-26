import asyncio
import importlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.strategy_service import StrategyService


strategy_service_module = importlib.import_module("app.services.strategy_service")


def test_strategy_trades_infers_legacy_close_leverage_from_open_trade(monkeypatch):
    open_meta = {
        "market_type": "swap",
        "action": "open",
        "pos_side": "long",
        "contracts": 23.54,
        "leverage": 2.0,
    }
    close_meta = {
        "market_type": "swap",
        "action": "close",
        "pos_side": "long",
        "contracts": 23.54,
        "leverage": 5.0,
    }

    class FakeDb:
        def get_strategy_trades(self, strategy_id, limit):
            assert strategy_id == 41
            assert limit == 100
            return [
                {
                    "id": 2,
                    "strategy_id": strategy_id,
                    "exchange": "okx",
                    "symbol": "SOL/USDT:USDT",
                    "timestamp": 2_000,
                    "side": "close_long",
                    "type": "market",
                    "price": 88.28,
                    "quantity": 23.54,
                    "fee": 1.0391,
                    "fee_asset": "USDT",
                    "pnl": 77.58,
                    "meta": json.dumps(close_meta),
                },
                {
                    "id": 1,
                    "strategy_id": strategy_id,
                    "exchange": "okx",
                    "symbol": "SOL/USDT:USDT",
                    "timestamp": 1_000,
                    "side": "open_long",
                    "type": "market",
                    "price": 84.94,
                    "quantity": 23.54,
                    "fee": 0.9997,
                    "fee_asset": "USDT",
                    "pnl": 0.0,
                    "meta": json.dumps(open_meta),
                },
            ]

    monkeypatch.setattr(strategy_service_module, "db", FakeDb())

    trades = asyncio.run(StrategyService().get_strategy_trades(41, 100))
    repaired_close_meta = json.loads(trades[0]["meta"])

    assert repaired_close_meta["leverage"] == 2.0
    assert json.loads(trades[1]["meta"])["leverage"] == 2.0
