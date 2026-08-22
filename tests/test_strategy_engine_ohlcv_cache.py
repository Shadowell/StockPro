import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.services.strategy_engine as se_mod


class FakeExchange:
    def __init__(self):
        self.calls = 0

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 2):
        self.calls += 1
        # 返回 2 根，倒数第二根视为已收盘
        return [
            [1_700_000_000_000, 1.0, 1.0, 1.0, 1.0, 1.0],
            [1_700_000_060_000, 2.0, 2.0, 2.0, 2.0, 1.0],
        ]

    def fetch_order_book(self, symbol: str, limit: int = 20):
        return {
            "bids": [[99.9, 12.0], [99.8, 8.0]],
            "asks": [[100.1, 10.0], [100.2, 7.0]],
            "timestamp": 1_700_000_070_000,
        }

    def fetch_ticker(self, symbol: str):
        return {"last": 100.0}


def test_fetch_latest_bar_dedupes_inflight_and_uses_cache(monkeypatch):
    async def _run():
        fake = FakeExchange()

        def _get_exchange(_name: str):
            return fake

        monkeypatch.setattr(se_mod.exchange_manager, "get_exchange", _get_exchange)

        engine = se_mod.StrategyEngine()

        async def call():
            return await engine._fetch_latest_bar("okx", "BTC/USDT", "1m")

        bar1, bar2 = await asyncio.gather(call(), call())
        assert bar1 is not None and bar2 is not None
        assert fake.calls == 1  # 并发去重

        bar3 = await engine._fetch_latest_bar("okx", "BTC/USDT", "1m")
        assert bar3 is not None
        assert fake.calls == 1  # TTL 缓存命中

    asyncio.run(_run())


def test_fetch_latest_bar_reuses_current_closed_bar_beyond_short_ttl(monkeypatch):
    async def _run():
        fake = FakeExchange()

        def _get_exchange(_name: str):
            return fake

        clock = {"wall": 1_700_000_068.0, "mono": 100.0}
        monkeypatch.setattr(se_mod.exchange_manager, "get_exchange", _get_exchange)
        monkeypatch.setattr(se_mod.time, "time", lambda: clock["wall"])
        monkeypatch.setattr(se_mod.time, "monotonic", lambda: clock["mono"])

        engine = se_mod.StrategyEngine()

        bar1 = await engine._fetch_latest_bar("okx", "BTC/USDT", "1m")
        assert bar1 is not None
        assert fake.calls == 1

        clock["mono"] += 20.0
        bar2 = await engine._fetch_latest_bar("okx", "BTC/USDT", "1m")
        assert bar2 is not None
        assert fake.calls == 1  # 同一根已收盘 bar 跨过短 TTL 后仍复用

        clock["wall"] += 60.0
        clock["mono"] += 60.0
        bar3 = await engine._fetch_latest_bar("okx", "BTC/USDT", "1m")
        assert bar3 is not None
        assert fake.calls == 2  # 进入下一根已收盘窗口后刷新

    asyncio.run(_run())


def test_paper_strategy_does_not_use_real_account_kill_switch(monkeypatch):
    async def _run():
        engine = se_mod.StrategyEngine()
        context = se_mod.StrategyContext(
            strategy_id=1,
            name="paper strategy",
            exchange="okx",
            symbols=["BTC/USDT"],
            config={"is_paper_trading": True},
        )
        engine._risk_manager.initialize(100.0)
        called = {"equity": 0, "kill": 0}

        async def fake_get_account_equity(_exchange_name):
            called["equity"] += 1
            return 50.0

        async def fake_activate(_exchange_name):
            called["kill"] += 1

        monkeypatch.setattr(se_mod.trading_service, "_get_account_equity", fake_get_account_equity)
        monkeypatch.setattr(engine, "_activate_global_kill_switch", fake_activate)

        await engine.run_account_risk_check("okx", context=context)

        assert called == {"equity": 0, "kill": 0}
        assert engine.get_risk_status()["circuit_breaker"] is False

    asyncio.run(_run())


def test_fetch_latest_tick_uses_orderbook_best_prices_and_depth(monkeypatch):
    async def _run():
        fake = FakeExchange()

        def _get_exchange(_name: str):
            return fake

        monkeypatch.setattr(se_mod.exchange_manager, "get_exchange", _get_exchange)

        engine = se_mod.StrategyEngine()
        tick = await engine._fetch_latest_tick("okx", "SOL/USDT:USDT", limit=20)

        assert tick is not None
        assert tick.symbol == "SOL/USDT:USDT"
        assert tick.last == 100.0
        assert tick.bid == 99.9
        assert tick.ask == 100.1
        assert tick.bid_depth == 20.0
        assert tick.ask_depth == 17.0
        assert tick.spread_bps == 20.0

    asyncio.run(_run())
