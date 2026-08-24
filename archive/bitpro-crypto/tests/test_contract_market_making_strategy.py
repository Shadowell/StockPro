import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState, TickData
from app.strategies.contract_market_making_strategy import ContractTrendFilteredMarketMakingStrategy


class FakeContractBroker:
    def __init__(self):
        self.opens = []
        self.closes = []
        self.positions = {}

    async def open_contract(self, symbol, side, notional_usdt, leverage=None, price=None):
        self.opens.append(
            {
                "symbol": symbol,
                "side": side,
                "notional_usdt": notional_usdt,
                "leverage": leverage,
                "price": price,
            }
        )
        self.positions[(symbol, side)] = {"symbol": symbol, "pos_side": side, "notional_usdt": notional_usdt, "entry_price": price}
        return OrderResult({"status": "filled", "symbol": symbol, "pos_side": side, "price": price, "notional_usdt": notional_usdt})

    async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
        self.closes.append({"symbol": symbol, "side": side, "ratio": ratio, "contracts": contracts, "price": price})
        self.positions.pop((symbol, side), None)
        return OrderResult({"status": "filled", "symbol": symbol, "pos_side": side, "price": price})

    async def get_contract_position(self, symbol, side):
        return self.positions.get((symbol, side))


def make_strategy():
    state = StrategyState(
        strategy_id=901,
        name="[合约][1M][做市] SOL · 趋势过滤库存做市 · 100U",
        exchange="okx",
        symbols=["SOL/USDT:USDT"],
    )
    broker = FakeContractBroker()
    strategy = ContractTrendFilteredMarketMakingStrategy(state, broker)
    strategy.set_config(
        {
            "trade_symbols": ["SOL/USDT:USDT"],
            "quote_notional_usdt": 10,
            "max_inventory_notional_usdt": 80,
            "leverage": 5,
            "quote_mode": "join_book",
            "quote_offset_bps": 0.2,
            "base_spread_bps": 2,
            "min_exchange_spread_bps": 1,
            "quote_ttl_sec": 30,
            "trend_fast_window": 3,
            "trend_slow_window": 5,
            "max_realized_vol_bps": 200,
        }
    )
    return strategy, broker


async def warmup(strategy):
    for idx, close in enumerate([99.8, 99.9, 100.0, 100.1, 100.2, 100.3]):
        await strategy.on_bar(
            BarData(
                exchange="okx",
                symbol="SOL/USDT:USDT",
                timeframe="1m",
                timestamp=1_700_000_000_000 + idx * 60_000,
                open=close - 0.05,
                high=close + 0.1,
                low=close - 0.1,
                close=close,
                volume=1000,
            )
        )


def test_market_maker_sets_quotes_then_fills_bid_when_mid_crosses_previous_quote():
    import asyncio

    async def _run():
        strategy, broker = make_strategy()
        await strategy.on_init()
        await warmup(strategy)

        await strategy.on_tick(
            TickData(
                exchange="okx",
                symbol="SOL/USDT:USDT",
                timestamp=1_700_000_500_000,
                last=100.00,
                bid=99.98,
                ask=100.02,
                bid_depth=50_000,
                ask_depth=48_000,
            )
        )
        assert broker.opens == []
        bid_quote = strategy.state.positions["_mm_quotes"]["SOL/USDT:USDT"]["bid"]["price"]
        assert bid_quote < 100.00

        await strategy.on_tick(
            TickData(
                exchange="okx",
                symbol="SOL/USDT:USDT",
                timestamp=1_700_000_503_000,
                last=bid_quote - 0.001,
                bid=99.95,
                ask=99.99,
                bid_depth=52_000,
                ask_depth=47_000,
            )
        )

        assert len(broker.opens) == 1
        assert broker.opens[0]["side"] == "long"
        assert broker.opens[0]["price"] == bid_quote

    asyncio.run(_run())


def test_market_maker_join_book_quote_stays_close_to_best_bid():
    import asyncio

    async def _run():
        strategy, broker = make_strategy()
        await strategy.on_init()
        await warmup(strategy)

        await strategy.on_tick(
            TickData(
                exchange="okx",
                symbol="SOL/USDT:USDT",
                timestamp=1_700_000_500_000,
                last=100.00,
                bid=99.98,
                ask=100.02,
                bid_depth=50_000,
                ask_depth=48_000,
            )
        )

        assert broker.opens == []
        bid_quote = strategy.state.positions["_mm_quotes"]["SOL/USDT:USDT"]["bid"]["price"]
        assert bid_quote <= 99.98
        assert 99.97 < bid_quote

    asyncio.run(_run())


def test_market_maker_fills_existing_quote_before_narrow_spread_filter_clears_it():
    import asyncio

    async def _run():
        strategy, broker = make_strategy()
        await strategy.on_init()
        await warmup(strategy)

        await strategy.on_tick(
            TickData(
                exchange="okx",
                symbol="SOL/USDT:USDT",
                timestamp=1_700_000_500_000,
                last=100.00,
                bid=99.98,
                ask=100.02,
                bid_depth=50_000,
                ask_depth=48_000,
            )
        )
        bid_quote = strategy.state.positions["_mm_quotes"]["SOL/USDT:USDT"]["bid"]["price"]

        await strategy.on_tick(
            TickData(
                exchange="okx",
                symbol="SOL/USDT:USDT",
                timestamp=1_700_000_503_000,
                last=bid_quote - 0.001,
                bid=bid_quote - 0.001,
                ask=bid_quote,
                bid_depth=52_000,
                ask_depth=47_000,
            )
        )

        assert len(broker.opens) == 1
        assert broker.opens[0]["side"] == "long"
        assert broker.opens[0]["price"] == bid_quote

    asyncio.run(_run())


def test_market_maker_skips_quotes_when_exchange_spread_is_too_narrow():
    import asyncio

    async def _run():
        strategy, broker = make_strategy()
        await strategy.on_init()
        await warmup(strategy)

        await strategy.on_tick(
            TickData(
                exchange="okx",
                symbol="SOL/USDT:USDT",
                timestamp=1_700_000_500_000,
                last=100.00,
                bid=99.999,
                ask=100.001,
                bid_depth=50_000,
                ask_depth=48_000,
            )
        )

        assert broker.opens == []
        assert strategy.state.positions["_mm_quotes"] == {}
        assert strategy.state.positions["_mm_last_skip_reason"] == "spread_too_narrow"

    asyncio.run(_run())
