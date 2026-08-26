import asyncio
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState
from app.services.strategy_registry import get_base_strategy_registry
from app.strategies.cta_trend_following_strategy import CTA_DECISION_LABELS
from app.strategies.dynamic_cta_selector import MarketSnapshot
from app.strategies.dynamic_cta_trend_following_strategy import DynamicCtaTrendFollowingStrategy


class FakePublicExchange:
    def __init__(
        self,
        fail_public: bool = False,
        fail_symbols: bool = False,
        fail_tickers: bool = False,
        fail_funding: bool = False,
    ):
        self.fail_public = fail_public
        self.fail_symbols = fail_symbols
        self.fail_tickers = fail_tickers
        self.fail_funding = fail_funding
        self.private_called = False
        self.symbol_calls = 0
        self.ticker_args = []
        self.funding_args = []

    def get_perpetual_symbols(self):
        self.symbol_calls += 1
        if self.fail_public or self.fail_symbols:
            raise RuntimeError("public instruments unavailable")
        return ["BTC/USDT:USDT", "ETH/USDT:USDT"]

    def fetch_tickers(self, symbols=None):
        self.ticker_args.append(symbols)
        if self.fail_public or self.fail_tickers:
            raise RuntimeError("public tickers unavailable")
        return [
            {
                "symbol": "BTC/USDT:USDT",
                "last": "100.0",
                "bid": "99.99",
                "ask": "100.01",
                "quote_volume": "1000000",
            },
            {
                "symbol": "ETH-USDT-SWAP",
                "last": 50.0,
                "bid": 49.99,
                "ask": 50.01,
                "quoteVolume24h": 900_000,
            },
            {
                "symbol": "XRP/USDT:USDT",
                "last": 1.0,
                "bid": 0.99,
                "ask": 1.01,
                "quoteVolume": 800_000,
            },
        ]

    def fetch_funding_rates(self, symbols=None):
        self.funding_args.append(symbols)
        if self.fail_public or self.fail_funding:
            raise RuntimeError("public funding unavailable")
        return [
            {"symbol": "BTC/USDT:USDT", "current_rate": "0.00001"},
            {"symbol": "ETH-USDT-SWAP", "fundingRate": 0.00002},
        ]

    def fetch_balance(self):
        self.private_called = True
        raise AssertionError("private API must not be called")


class FakeExchangeManager:
    def __init__(self, exchange):
        self.exchange = exchange
        self.names = []

    def get_exchange(self, name):
        self.names.append(name)
        return self.exchange


class FakeDynamicBroker:
    def __init__(self, equity: float = 100.0):
        self.equity = equity
        self.positions = {}
        self.orders = []
        self.warmup_mode = False
        self.private_calls = []

    async def open_contract(self, symbol: str, side: str, notional_usdt: float, leverage=None, price=None) -> OrderResult:
        self.orders.append(
            {
                "action": "open",
                "symbol": symbol,
                "side": side,
                "notional": notional_usdt,
                "leverage": leverage,
                "price": price,
            }
        )
        self.positions[(symbol, side)] = {
            "symbol": symbol,
            "pos_side": side,
            "entry_price": price,
            "mark_price": price,
            "base_qty": notional_usdt / price if price else 0.0,
            "notional_usdt": notional_usdt,
        }
        return OrderResult(
            {"status": "filled", "symbol": symbol, "side": side, "notional_usdt": notional_usdt, "price": price}
        )

    async def close_contract(self, symbol: str, side: str, ratio: float = 1.0, contracts=None, price=None) -> OrderResult:
        self.orders.append({"action": "close", "symbol": symbol, "side": side, "ratio": ratio, "price": price})
        self.positions.pop((symbol, side), None)
        return OrderResult({"status": "filled", "symbol": symbol, "side": side, "price": price})

    async def get_contract_position(self, symbol: str, side: str):
        return self.positions.get((symbol, side))

    def fetch_balance(self):
        self.private_calls.append("fetch_balance")
        raise AssertionError("dynamic CTA paper strategy must not call private account APIs")


def make_state(symbols=None) -> StrategyState:
    return StrategyState(
        strategy_id=2001,
        name="[合约] dynamic CTA test",
        exchange="okx",
        symbols=symbols or ["BTC/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 100.0},
    )


def make_bar(symbol: str, close: float, index: int, timestamp_step_ms: int = 900_000) -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="15m",
        timestamp=1_800_000_000_000 + index * timestamp_step_ms,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=10_000,
    )


def init_strategy(config=None, broker=None):
    broker = broker or FakeDynamicBroker()
    strategy = DynamicCtaTrendFollowingStrategy(make_state(), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "timeframe": "15m",
            "trend_filter": "ema_state",
            "fast_window": 2,
            "slow_window": 3,
            "entry_signal_confirm_bars": 2,
            "atr_window": 2,
            "atr_stop_mult": 1.5,
            "risk_per_trade_pct": 0.015,
            "min_atr_ratio": 0.0,
            "max_position_pct": 1.0,
            "max_total_notional_pct": 10.0,
            "min_order_notional_usdt": 0.5,
            "market_sma_window": 2,
            "market_regime_threshold": 0.67,
            "leverage": 5,
            "max_leverage": 5,
            "max_positions": 5,
            "trade_symbols": ["ETH/USDT:USDT"],
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy, broker


def prime_dynamic_market(strategy, symbols: list[str]) -> None:
    strategy.set_dynamic_market_snapshots(
        [
            MarketSnapshot(
                symbol=symbol,
                quote_volume_24h=1_000_000 - index * 10_000,
                bid=100.0,
                ask=100.01,
                last=100.0,
                funding_rate=0.0,
                open_interest_usdt=500_000,
                active=True,
            )
            for index, symbol in enumerate(symbols)
        ]
    )


def dynamic_test_config(**overrides):
    return {
        "dynamic_required_history_windows": (),
        "dynamic_min_entry_score": 0,
        **overrides,
    }


def test_dynamic_cta_strategy_is_registered():
    registry = get_base_strategy_registry()
    assert registry["dynamic_cta_trend_following_top15"].__name__ == "DynamicCtaTrendFollowingStrategy"


def test_dynamic_cta_initializes_without_static_trade_symbols():
    strategy, _ = init_strategy()
    assert strategy.trade_symbols == ()
    assert strategy.max_positions == 5


def test_dynamic_cta_initializes_default_dynamic_config_values():
    strategy, _ = init_strategy()
    selector_config = strategy._dynamic_selector.config

    assert strategy.dynamic_liquidity_top_n == 50
    assert strategy.dynamic_candidate_top_n == 15
    assert strategy.max_new_positions_per_cycle == 2
    assert strategy.dynamic_min_entry_score == 70.0
    assert strategy.dynamic_scan_interval_sec == 600
    assert strategy.dynamic_candidate_effective_timeframe_ms == 900_000
    assert strategy.dynamic_same_direction_score_addon == 10.0
    assert strategy.dynamic_daily_pause_drawdown_pct == 0.05
    assert strategy.dynamic_daily_cooldown_drawdown_pct == 0.08
    assert selector_config.liquidity_top_n == 50
    assert selector_config.candidate_top_n == 15
    assert selector_config.min_entry_score == 70.0
    assert selector_config.scan_interval_sec == 600
    assert selector_config.timeframe_ms == 900_000
    assert selector_config.fast_window == 2
    assert selector_config.slow_window == 3
    assert selector_config.entry_confirm_bars == 2
    assert selector_config.atr_window == 2
    assert selector_config.min_atr_ratio == 0.0
    assert selector_config.crowded_direction_score_addon == 10.0


def test_dynamic_cta_required_history_windows_can_be_configured():
    strategy, _ = init_strategy({"dynamic_required_history_windows": ["3d"]})

    assert strategy._dynamic_selector.config.required_history_windows == ("3d",)


def test_dynamic_cta_required_history_windows_accepts_shared_config_key():
    strategy, _ = init_strategy({"required_history_windows": ("3d", "14d")})

    assert strategy._dynamic_selector.config.required_history_windows == ("3d", "14d")


def test_dynamic_cta_window_weights_can_be_configured():
    strategy, _ = init_strategy({"dynamic_window_weights": {"3d": 1.0}})

    assert strategy._dynamic_selector.config.window_weights == {"3d": 1.0}


def test_dynamic_cta_decision_labels_are_registered():
    assert CTA_DECISION_LABELS["dynamic_cta_selection"] == "动态 CTA 候选池"
    assert CTA_DECISION_LABELS["dynamic_cta_not_selected"] == "动态 CTA 未入选"


def test_dynamic_cta_opens_at_most_two_new_positions_per_confirmed_candle():
    symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
    strategy, broker = init_strategy(dynamic_test_config(), FakeDynamicBroker(100.0))
    prime_dynamic_market(strategy, symbols)

    for index, close in enumerate([100.0, 101.0, 102.0, 103.0]):
        for symbol in symbols:
            asyncio.run(strategy.on_bar(make_bar(symbol, close, index)))

    opens = [order for order in broker.orders if order["action"] == "open"]
    assert len(opens) == 2
    assert {order["symbol"] for order in opens}.issubset(set(symbols))
    assert all(order["leverage"] == 5 for order in opens)


def test_dynamic_cta_never_exceeds_five_open_positions():
    symbols = [f"COIN{idx}/USDT:USDT" for idx in range(8)]
    strategy, broker = init_strategy(dynamic_test_config(), FakeDynamicBroker(100.0))
    prime_dynamic_market(strategy, symbols)

    for index in range(12):
        close = 100.0 + index
        for symbol in symbols:
            asyncio.run(strategy.on_bar(make_bar(symbol, close, index)))

    open_symbols = {key[0] for key in broker.positions.keys()}
    assert len(open_symbols) <= 5


def test_dynamic_cta_ranking_drop_does_not_force_close_existing_position():
    strategy, broker = init_strategy(dynamic_test_config(), FakeDynamicBroker(100.0))
    broker.positions[("OLD/USDT:USDT", "long")] = {
        "symbol": "OLD/USDT:USDT",
        "pos_side": "long",
        "entry_price": 100.0,
        "mark_price": 103.0,
        "base_qty": 1.0,
        "notional_usdt": 20.0,
    }
    prime_dynamic_market(strategy, ["NEW/USDT:USDT"])

    for index, close in enumerate([100.0, 101.0, 102.0, 103.0, 104.0]):
        asyncio.run(strategy.on_bar(make_bar("OLD/USDT:USDT", close, index)))
        asyncio.run(strategy.on_bar(make_bar("NEW/USDT:USDT", close, index)))

    assert broker.positions[("OLD/USDT:USDT", "long")]
    assert not [
        order for order in broker.orders if order["action"] == "close" and order["symbol"] == "OLD/USDT:USDT"
    ]


def test_dynamic_cta_uses_only_paper_broker_paths():
    strategy, broker = init_strategy(dynamic_test_config(), FakeDynamicBroker(100.0))
    prime_dynamic_market(strategy, ["BTC/USDT:USDT"])

    for index, close in enumerate([100.0, 101.0, 102.0, 103.0, 104.0]):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", close, index)))

    assert broker.private_calls == []


def test_dynamic_cta_loads_market_snapshots_from_public_exchange(monkeypatch):
    fake_exchange = FakePublicExchange()
    fake_manager = FakeExchangeManager(fake_exchange)

    import app.strategies.dynamic_cta_trend_following_strategy as strategy_module

    monkeypatch.setattr(strategy_module, "exchange_manager", fake_manager)

    strategy, _ = init_strategy({"dynamic_min_entry_score": 0}, FakeDynamicBroker(100.0))
    snapshots = strategy._load_public_market_snapshots()

    assert fake_manager.names == ["okx"]
    assert [row.symbol for row in snapshots] == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert fake_exchange.ticker_args == [None]
    assert fake_exchange.funding_args == [["BTC/USDT:USDT", "ETH/USDT:USDT"]]
    assert snapshots[0].quote_volume_24h == 1_000_000
    assert snapshots[0].funding_rate == 0.00001
    assert snapshots[1].quote_volume_24h == 900_000
    assert snapshots[1].funding_rate == 0.00002
    assert snapshots[0].open_interest_usdt is None
    assert fake_exchange.private_called is False


def test_dynamic_cta_public_exchange_funding_failure_keeps_ticker_snapshots(monkeypatch):
    fake_exchange = FakePublicExchange(fail_funding=True)

    import app.strategies.dynamic_cta_trend_following_strategy as strategy_module

    monkeypatch.setattr(strategy_module, "exchange_manager", FakeExchangeManager(fake_exchange))

    strategy, _ = init_strategy({"dynamic_min_entry_score": 0}, FakeDynamicBroker(100.0))
    snapshots = strategy._load_public_market_snapshots()

    assert [row.symbol for row in snapshots] == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert [row.funding_rate for row in snapshots] == [None, None]
    assert fake_exchange.ticker_args == [None]
    assert fake_exchange.private_called is False


def test_dynamic_cta_public_loader_prefers_okx_swap_ticker_endpoint(monkeypatch):
    class RawCcxt:
        def __init__(self):
            self.ticker_params = []
            self.funding_symbols = []

        def fetch_tickers(self, symbols=None, params=None):
            self.ticker_params.append(params)
            return {
                "BTC/USDT:USDT": {
                    "symbol": "BTC/USDT:USDT",
                    "last": "100.0",
                    "bid": "99.99",
                    "ask": "100.01",
                    "quoteVolume": "1000000",
                },
                "ETH/USDT:USDT": {
                    "symbol": "ETH/USDT:USDT",
                    "last": "50.0",
                    "bid": "49.99",
                    "ask": "50.01",
                    "quoteVolume": "900000",
                },
                "BTC/USD:BTC": {
                    "symbol": "BTC/USD:BTC",
                    "last": "100.0",
                    "bid": "99.99",
                    "ask": "100.01",
                    "quoteVolume": "800000",
                },
            }

        def fetch_funding_rates(self, symbols):
            self.funding_symbols.append(list(symbols))
            return {
                "BTC/USDT:USDT": {"symbol": "BTC/USDT:USDT", "fundingRate": "0.00003"},
                "ETH/USDT:USDT": {"symbol": "ETH/USDT:USDT", "fundingRate": "0.00004"},
            }

    class RawOkxExchange(FakePublicExchange):
        def __init__(self):
            super().__init__()
            self.exchange = RawCcxt()

        def fetch_tickers(self, symbols=None):
            raise AssertionError("fallback ticker endpoint should not be used")

        def fetch_funding_rates(self, symbols=None):
            raise AssertionError("fallback funding endpoint should not be used")

    fake_exchange = RawOkxExchange()

    import app.strategies.dynamic_cta_trend_following_strategy as strategy_module

    monkeypatch.setattr(strategy_module, "exchange_manager", FakeExchangeManager(fake_exchange))

    strategy, _ = init_strategy({"dynamic_min_entry_score": 0}, FakeDynamicBroker(100.0))
    snapshots = strategy._load_public_market_snapshots()

    assert [row.symbol for row in snapshots] == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert fake_exchange.exchange.ticker_params == [{"instType": "SWAP"}]
    assert fake_exchange.exchange.funding_symbols == [["BTC/USDT:USDT", "ETH/USDT:USDT"]]
    assert snapshots[0].quote_volume_24h == 1_000_000
    assert snapshots[0].funding_rate == 0.00003
    assert fake_exchange.ticker_args == []
    assert fake_exchange.funding_args == []
    assert fake_exchange.private_called is False


def test_dynamic_cta_public_loader_does_not_synthesize_swaps_when_symbol_set_unavailable(monkeypatch):
    class SpotOnlyExchange(FakePublicExchange):
        def fetch_tickers(self, symbols=None):
            self.ticker_args.append(symbols)
            return [
                {
                    "symbol": "BTC/USDT",
                    "last": "100.0",
                    "bid": "99.99",
                    "ask": "100.01",
                    "quote_volume": "1000000",
                },
                {
                    "symbol": "ETH-USDC",
                    "last": "50.0",
                    "bid": "49.99",
                    "ask": "50.01",
                    "quoteVolume24h": 900_000,
                },
            ]

    fake_exchange = SpotOnlyExchange(fail_symbols=True)

    import app.strategies.dynamic_cta_trend_following_strategy as strategy_module

    monkeypatch.setattr(strategy_module, "exchange_manager", FakeExchangeManager(fake_exchange))

    strategy, _ = init_strategy({"dynamic_min_entry_score": 0}, FakeDynamicBroker(100.0))
    snapshots = strategy._load_public_market_snapshots()
    symbols = DynamicCtaTrendFollowingStrategy.resolve_runtime_symbols("okx:live-account", {})

    assert snapshots == []
    assert symbols == []
    assert fake_exchange.ticker_args == [None, None]
    assert fake_exchange.private_called is False


def test_dynamic_cta_public_loader_filters_non_usdt_and_spot_tickers(monkeypatch):
    class MixedMarketExchange(FakePublicExchange):
        def get_perpetual_symbols(self):
            self.symbol_calls += 1
            return [
                "BTC/USDT:USDT",
                "ETH/USDC:USDC",
                "XRP/USDT:USDT",
                "LTC/USDT:USDT",
            ]

        def fetch_tickers(self, symbols=None):
            self.ticker_args.append(symbols)
            return [
                {
                    "symbol": "BTC-USDT-SWAP",
                    "last": "100.0",
                    "bid": "99.99",
                    "ask": "100.01",
                    "quote_volume": "1000000",
                },
                {
                    "symbol": "ETH-USDC-SWAP",
                    "last": "50.0",
                    "bid": "49.99",
                    "ask": "50.01",
                    "quoteVolume24h": 900_000,
                },
                {
                    "symbol": "XRP/USDT",
                    "last": "1.0",
                    "bid": "0.99",
                    "ask": "1.01",
                    "quoteVolume": 800_000,
                },
                {
                    "symbol": "LTC/USDT",
                    "info": {"instId": "LTC-USDT-SWAP"},
                    "last": "80.0",
                    "bid": "79.99",
                    "ask": "80.01",
                    "quoteVolume": 700_000,
                },
            ]

    fake_exchange = MixedMarketExchange()

    import app.strategies.dynamic_cta_trend_following_strategy as strategy_module

    monkeypatch.setattr(strategy_module, "exchange_manager", FakeExchangeManager(fake_exchange))

    strategy, _ = init_strategy({"dynamic_min_entry_score": 0}, FakeDynamicBroker(100.0))
    snapshots = strategy._load_public_market_snapshots()

    assert [row.symbol for row in snapshots] == ["BTC/USDT:USDT", "LTC/USDT:USDT"]
    assert all(row.symbol.endswith("/USDT:USDT") for row in snapshots)
    assert fake_exchange.private_called is False


def test_dynamic_cta_public_exchange_uses_default_okx_for_live_account_alias(monkeypatch):
    fake_exchange = FakePublicExchange()
    fake_manager = FakeExchangeManager(fake_exchange)

    import app.strategies.dynamic_cta_trend_following_strategy as strategy_module

    monkeypatch.setattr(strategy_module, "exchange_manager", fake_manager)

    strategy, _ = init_strategy({"exchange": "okx:live-account"}, FakeDynamicBroker(100.0))
    snapshots = strategy._load_public_market_snapshots()

    assert snapshots
    assert fake_manager.names == ["okx"]
    assert fake_exchange.private_called is False


def test_dynamic_cta_resolves_runtime_symbols_from_public_liquidity_top_n(monkeypatch):
    fake_exchange = FakePublicExchange()
    fake_manager = FakeExchangeManager(fake_exchange)

    import app.strategies.dynamic_cta_trend_following_strategy as strategy_module

    monkeypatch.setattr(strategy_module, "exchange_manager", fake_manager)

    symbols = DynamicCtaTrendFollowingStrategy.resolve_runtime_symbols(
        "okx:live-account",
        {"dynamic_liquidity_top_n": 1},
    )

    assert symbols == ["BTC/USDT:USDT"]
    assert fake_manager.names == ["okx"]
    assert fake_exchange.ticker_args == [None]
    assert fake_exchange.private_called is False


def test_dynamic_cta_refresh_loads_public_exchange_when_snapshots_absent(monkeypatch):
    fake_exchange = FakePublicExchange()

    import app.strategies.dynamic_cta_trend_following_strategy as strategy_module

    monkeypatch.setattr(strategy_module, "exchange_manager", FakeExchangeManager(fake_exchange))

    strategy, broker = init_strategy(dynamic_test_config(), FakeDynamicBroker(100.0))

    for index, close in enumerate([100.0, 101.0, 102.0, 103.0]):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", close, index)))

    assert set(strategy._dynamic_market_snapshots.keys()) == {"BTC/USDT:USDT", "ETH/USDT:USDT"}
    assert fake_exchange.private_called is False
    assert broker.private_calls == []


def test_dynamic_cta_public_exchange_failure_is_throttled_across_history_changes(monkeypatch):
    failing_exchange = FakePublicExchange(fail_tickers=True)
    fake_manager = FakeExchangeManager(failing_exchange)

    import app.strategies.dynamic_cta_trend_following_strategy as strategy_module

    monkeypatch.setattr(strategy_module, "exchange_manager", fake_manager)

    strategy, _ = init_strategy(
        dynamic_test_config(dynamic_scan_interval_sec=60),
        FakeDynamicBroker(100.0),
    )

    for index, close in enumerate([100.0, 101.0, 102.0, 103.0, 104.0, 105.0]):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", close, index, timestamp_step_ms=1_000)))

    assert fake_manager.names == ["okx"]
    assert failing_exchange.ticker_args == [None]
    assert strategy._dynamic_market_snapshots == {}
    assert failing_exchange.private_called is False


def test_dynamic_cta_refresh_keeps_manual_snapshots_without_public_reload(monkeypatch):
    fake_exchange = FakePublicExchange(fail_public=True)
    fake_manager = FakeExchangeManager(fake_exchange)

    import app.strategies.dynamic_cta_trend_following_strategy as strategy_module

    monkeypatch.setattr(strategy_module, "exchange_manager", fake_manager)

    strategy, _ = init_strategy(dynamic_test_config(), FakeDynamicBroker(100.0))
    prime_dynamic_market(strategy, ["MANUAL/USDT:USDT"])

    for index, close in enumerate([100.0, 101.0, 102.0, 103.0]):
        asyncio.run(strategy.on_bar(make_bar("MANUAL/USDT:USDT", close, index)))

    assert set(strategy._dynamic_market_snapshots.keys()) == {"MANUAL/USDT:USDT"}
    assert fake_manager.names == []
    assert fake_exchange.private_called is False


def test_dynamic_cta_public_exchange_loader_returns_empty_on_missing_or_errors(monkeypatch):
    import app.strategies.dynamic_cta_trend_following_strategy as strategy_module

    monkeypatch.setattr(strategy_module, "exchange_manager", FakeExchangeManager(None))
    missing_strategy, _ = init_strategy(dynamic_test_config(), FakeDynamicBroker(100.0))
    assert missing_strategy._load_public_market_snapshots() == []

    failing_exchange = FakePublicExchange(fail_public=True)
    monkeypatch.setattr(strategy_module, "exchange_manager", FakeExchangeManager(failing_exchange))
    failing_strategy, _ = init_strategy(dynamic_test_config(), FakeDynamicBroker(100.0))

    assert failing_strategy._load_public_market_snapshots() == []
    for index, close in enumerate([100.0, 101.0, 102.0, 103.0]):
        asyncio.run(failing_strategy.on_bar(make_bar("BTC/USDT:USDT", close, index)))

    assert failing_strategy._dynamic_market_snapshots == {}
    assert failing_exchange.private_called is False


def test_dynamic_cta_recomputes_selection_within_same_candle_bucket_for_later_symbols():
    symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    strategy, broker = init_strategy(
        dynamic_test_config(dynamic_candidate_top_n=1, dynamic_liquidity_top_n=2),
        FakeDynamicBroker(100.0),
    )
    prime_dynamic_market(strategy, symbols)

    for index in range(5):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", 100.0, index)))
        asyncio.run(strategy.on_bar(make_bar("ETH/USDT:USDT", 100.0 + index, index)))

    opens = [order for order in broker.orders if order["action"] == "open"]
    assert [order["symbol"] for order in opens] == ["ETH/USDT:USDT"]


def test_dynamic_cta_daily_drawdown_pauses_new_entries():
    strategy, broker = init_strategy(
        dynamic_test_config(dynamic_daily_pause_drawdown_pct=0.05),
        FakeDynamicBroker(100.0),
    )
    strategy.state.positions["_dynamic_cta_day_start_equity"] = 100.0
    broker.equity = 94.9
    prime_dynamic_market(strategy, ["BTC/USDT:USDT"])

    for index, close in enumerate([100.0, 101.0, 102.0, 103.0]):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", close, index)))

    assert broker.orders == []


def test_dynamic_cta_records_three_losses_and_cools_symbol():
    strategy, broker = init_strategy(
        dynamic_test_config(symbol_cooldown_loss_count=3, symbol_cooldown_hours=6),
        FakeDynamicBroker(100.0),
    )
    now = 1_800_000_000_000
    strategy._record_closed_trade_for_cooldown("BTC/USDT:USDT", -1.0, now)
    strategy._record_closed_trade_for_cooldown("BTC/USDT:USDT", -1.0, now + 1)
    strategy._record_closed_trade_for_cooldown("BTC/USDT:USDT", -1.0, now + 2)
    prime_dynamic_market(strategy, ["BTC/USDT:USDT"])

    for index, close in enumerate([100.0, 101.0, 102.0, 103.0]):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", close, index)))

    assert broker.orders == []
    assert strategy._dynamic_selection is not None
    assert strategy._dynamic_selection.row_by_symbol["BTC/USDT:USDT"].blocked_reason == "symbol_cooldown"


def test_dynamic_cta_close_path_records_losing_trade_for_cooldown():
    strategy, broker = init_strategy(
        dynamic_test_config(symbol_cooldown_loss_count=1, symbol_cooldown_hours=6),
        FakeDynamicBroker(100.0),
    )
    broker.positions[("BTC/USDT:USDT", "long")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "long",
        "entry_price": 100.0,
        "mark_price": 99.0,
        "base_qty": 1.0,
        "notional_usdt": 100.0,
    }
    strategy._append_bar(make_bar("BTC/USDT:USDT", 99.0, 0))

    result = asyncio.run(strategy._close_if_present("BTC/USDT:USDT", "long", 99.0))

    assert result["status"] == "filled"
    assert not awaitable_position_exists(strategy, "BTC/USDT:USDT", "long")
    prime_dynamic_market(strategy, ["BTC/USDT:USDT"])
    for index, close in enumerate([100.0, 101.0, 102.0, 103.0], start=1):
        asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", close, index)))

    opens = [order for order in broker.orders if order["action"] == "open"]
    assert opens == []


def awaitable_position_exists(strategy, symbol: str, side: str) -> bool:
    return bool(asyncio.run(strategy.get_contract_position(symbol, side)))
