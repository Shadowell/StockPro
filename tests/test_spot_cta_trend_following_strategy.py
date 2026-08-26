import json
import math
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState
from app.services.strategy_registry import get_base_strategy_registry
from app.strategies.spot_cta_trend_following_strategy import SpotCtaTrendFollowingStrategy


class FakeSpotBroker:
    def __init__(self, initial_capital: float = 10_000.0):
        self.initial_capital = initial_capital
        self.balance = initial_capital
        self.positions = {}
        self.trades = []
        self._last_prices = {}
        self.warmup_mode = False

    @property
    def equity(self) -> float:
        total = self.balance
        for symbol, pos in self.positions.items():
            total += float(pos.get("size") or 0.0) * self._last_prices.get(symbol, float(pos.get("entry_price") or 0.0))
        return total

    async def get_available_balance(self, currency: str = "USDT") -> float:
        return self.balance if currency == "USDT" else 0.0

    def update_mark_price(self, symbol: str, price: float) -> None:
        self._last_prices[symbol] = price
        pos = self.positions.get(symbol)
        if pos:
            pos["unrealized_pnl"] = (price - pos["entry_price"]) * pos["size"]

    async def buy(self, symbol: str, amount: float, price: float = None, *, order_type: str = "market") -> OrderResult:
        exec_price = float(price or self._last_prices.get(symbol) or 0.0)
        cost = exec_price * amount
        if cost > self.balance:
            amount = self.balance / exec_price
            cost = exec_price * amount
        self.balance -= cost
        pos = self.positions.setdefault(symbol, {"size": 0.0, "entry_price": 0.0, "side": "long", "unrealized_pnl": 0.0})
        prev_size = pos["size"]
        pos["entry_price"] = exec_price if prev_size <= 0 else (pos["entry_price"] * prev_size + cost) / (prev_size + amount)
        pos["size"] = prev_size + amount
        trade = {"symbol": symbol, "side": "BUY", "price": exec_price, "amount": amount, "cost": cost, "fee": 0.0, "pnl": 0.0}
        self.trades.append(trade)
        return OrderResult(trade)

    async def sell(self, symbol: str, amount: float, price: float = None, *, order_type: str = "market") -> OrderResult:
        exec_price = float(price or self._last_prices.get(symbol) or 0.0)
        pos = self.positions.get(symbol)
        if not pos or pos["size"] <= 0:
            return OrderResult({"status": "skipped", "reason": "no_position", "symbol": symbol})
        qty = min(amount, pos["size"])
        revenue = exec_price * qty
        pnl = (exec_price - pos["entry_price"]) * qty
        pos["size"] -= qty
        if pos["size"] <= 1e-12:
            pos["size"] = 0.0
            pos["entry_price"] = 0.0
        self.balance += revenue
        trade = {"symbol": symbol, "side": "SELL", "price": exec_price, "amount": qty, "cost": revenue, "fee": 0.0, "pnl": pnl}
        self.trades.append(trade)
        return OrderResult(trade)

    async def close_position(self, symbol: str) -> OrderResult:
        pos = self.positions.get(symbol)
        if not pos:
            return OrderResult({"status": "skipped", "reason": "no_position"})
        return await self.sell(symbol, pos["size"])


def _bar(symbol: str, idx: int, close: float) -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="4h",
        timestamp=idx * 4 * 60 * 60 * 1000,
        open=close - 0.5,
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        volume=1000.0,
    )


def _strategy(symbols=None):
    symbols = symbols or ["BTC/USDT"]
    broker = FakeSpotBroker()
    state = StrategyState(strategy_id=1001, name="[现货] CTA 趋势跟踪 · 多品种4H", exchange="okx", symbols=symbols)
    strategy = SpotCtaTrendFollowingStrategy(state=state, broker=broker)
    strategy.set_config(
        {
            "strategy_key": "spot_cta_trend_following",
            "market_type": "spot",
            "timeframe": "4h",
            "initial_capital": 10_000,
            "trend_filter": "donchian",
            "fast_window": 2,
            "slow_window": 3,
            "atr_window": 2,
            "atr_stop_mult": 2.0,
            "min_atr_ratio": 0.0,
            "position_pct": 0.5,
            "max_positions": 2,
            "max_total_position_pct": 1.0,
            "min_order_notional_usdt": 10,
            "market_sma_window": 2,
            "market_regime_threshold": 0.8,
            "reversal_exit": True,
            "fee_bps": 0,
            "slippage_bps": 0,
            "strategy_diagnostic_ws": False,
            "trade_symbols": symbols,
        }
    )
    return strategy, broker


@pytest.mark.asyncio
async def test_spot_cta_opens_with_half_equity_on_long_signal():
    strategy, broker = _strategy()
    await strategy.on_init()

    for idx, close in enumerate([100.0, 101.0, 102.0, 105.0], start=1):
        await strategy.on_bar(_bar("BTC/USDT", idx, close))

    assert broker.trades[-1]["side"] == "BUY"
    assert broker.trades[-1]["symbol"] == "BTC/USDT"
    assert math.isclose(broker.trades[-1]["cost"], 5_000.0, rel_tol=1e-9)
    assert math.isclose(broker.balance, 5_000.0, rel_tol=1e-9)


@pytest.mark.asyncio
async def test_spot_cta_allows_two_half_equity_positions_across_symbols():
    strategy, broker = _strategy(["BTC/USDT", "ETH/USDT"])
    await strategy.on_init()

    for idx, close in enumerate([100.0, 101.0, 102.0, 105.0], start=1):
        await strategy.on_bar(_bar("BTC/USDT", idx, close))
    for idx, close in enumerate([50.0, 51.0, 52.0, 55.0], start=1):
        await strategy.on_bar(_bar("ETH/USDT", idx, close))

    buys = [trade for trade in broker.trades if trade["side"] == "BUY"]
    assert [trade["symbol"] for trade in buys] == ["BTC/USDT", "ETH/USDT"]
    assert math.isclose(buys[0]["cost"], 5_000.0, rel_tol=1e-9)
    assert math.isclose(buys[1]["cost"], 5_000.0, rel_tol=1e-9)
    assert math.isclose(broker.balance, 0.0, abs_tol=1e-9)


@pytest.mark.asyncio
async def test_spot_cta_closes_existing_position_on_atr_trailing_stop():
    strategy, broker = _strategy()
    await strategy.on_init()

    for idx, close in enumerate([100.0, 101.0, 102.0, 105.0], start=1):
        await strategy.on_bar(_bar("BTC/USDT", idx, close))
    await strategy.on_bar(_bar("BTC/USDT", 5, 98.0))

    assert broker.trades[-1]["side"] == "SELL"
    assert broker.positions["BTC/USDT"]["size"] == 0.0


def test_spot_cta_registry_and_seed_are_registered():
    registry = get_base_strategy_registry()
    assert registry["spot_cta_trend_following"].__name__ == "SpotCtaTrendFollowingStrategy"

    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "spot_cta_trend_following")
    cfg = entry["config"]

    assert entry["name"].startswith("[现货]")
    assert cfg["market_type"] == "spot"
    assert cfg["is_paper_trading"] is True
    assert cfg["timeframe"] == "4h"
    assert cfg["position_pct"] == 0.5
    assert cfg["max_positions"] == 2
    assert cfg["max_total_position_pct"] == 1.0
    assert cfg["allow_short"] is False
    assert cfg["trade_symbols"] == ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT"]
