import sys
import asyncio
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.exchange.base import BaseExchange
from app.services.exogenous_feature_service import ExogenousFeatureService


class FakeCcxtExchange:
    def __init__(self):
        self.fetch_ticker_calls = []
        self.load_markets_calls = []

    def load_markets(self, reload=False):
        self.load_markets_calls.append(reload)
        return None

    def fetch_tickers(self):
        return {
            "BTC/USDT": {
                "symbol": "BTC/USDT",
                "last": 82000,
                "baseVolume": 10,
                "quoteVolume": 820000,
                "percentage": 1.0,
            }
        }

    def fetch_ticker(self, symbol):
        self.fetch_ticker_calls.append(symbol)
        if symbol == "BTC/USDT:USDT":
            return {
                "symbol": "BTC/USDT:USDT",
                "last": 82100,
                "baseVolume": 20,
                "quoteVolume": 1642000,
                "percentage": 1.2,
            }
        raise AssertionError(f"unexpected fetch_ticker symbol: {symbol}")


class FakeExchange(BaseExchange):
    @property
    def name(self):
        return "okx"

    def _create_exchange(self):
        return FakeCcxtExchange()


def test_fetch_tickers_falls_back_to_single_ticker_for_missing_contract_symbols():
    exchange = FakeExchange()
    exchange.initialize()

    rows = exchange.fetch_tickers(["BTC/USDT:USDT"])

    assert [row["symbol"] for row in rows] == ["BTC/USDT:USDT"]
    assert rows[0]["last"] == 82100
    assert exchange.exchange.fetch_ticker_calls == ["BTC/USDT:USDT"]


def test_fetch_tickers_prefers_okx_swap_batch_for_contract_symbols():
    class SwapBatchCcxtExchange(FakeCcxtExchange):
        def __init__(self):
            super().__init__()
            self.fetch_tickers_calls = []

        def fetch_tickers(self, symbols=None, params=None):
            self.fetch_tickers_calls.append(params)
            if params == {"instType": "SWAP"}:
                return {
                    "BTC/USDT:USDT": {
                        "symbol": "BTC/USDT:USDT",
                        "last": 82100,
                        "baseVolume": 20,
                        "quoteVolume": 1642000,
                        "percentage": 1.2,
                    },
                    "ETH/USDT:USDT": {
                        "symbol": "ETH/USDT:USDT",
                        "last": 2300,
                        "baseVolume": 30,
                        "quoteVolume": 69000,
                        "percentage": -0.5,
                    },
                }
            return super().fetch_tickers()

    class SwapBatchExchange(FakeExchange):
        def _create_exchange(self):
            return SwapBatchCcxtExchange()

    exchange = SwapBatchExchange()
    exchange.initialize()

    rows = exchange.fetch_tickers(["BTC/USDT:USDT", "ETH/USDT:USDT"])

    assert [row["symbol"] for row in rows] == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert [row["last"] for row in rows] == [82100.0, 2300.0]
    assert exchange.exchange.fetch_ticker_calls == []
    assert exchange.exchange.fetch_tickers_calls == [{"instType": "SWAP"}]


def test_get_symbols_filters_spot_and_swap_markets():
    exchange = FakeExchange()
    exchange.initialize()
    exchange.exchange.markets = {
        "BTC/USDT": {"quote": "USDT", "active": True, "spot": True},
        "ETH/USDT": {"quote": "USDT", "active": True, "spot": True},
        "OPENAI/USDT:USDT": {"quote": "USDT", "active": None, "swap": True, "linear": True},
        "SPCX/USDT:USDT": {"quote": "USDT", "active": True, "swap": True, "linear": True},
        "BTC/USDC:USDC": {"quote": "USDC", "active": True, "swap": True, "linear": True},
        "OLD/USDT": {"quote": "USDT", "active": False, "spot": True},
    }

    assert exchange.get_symbols("USDT", "spot") == ["BTC/USDT", "ETH/USDT"]
    assert exchange.get_symbols("USDT", "swap") == ["OPENAI/USDT:USDT", "SPCX/USDT:USDT"]


def test_load_markets_force_reloads_exchange_metadata():
    exchange = FakeExchange()
    exchange.initialize()

    exchange.load_markets()
    exchange.load_markets(force=True)

    assert exchange.exchange.load_markets_calls == [False, True]


def test_fetch_ticker_exposes_okx_today_change_from_sod_utc0():
    class TodayTickerExchange(FakeCcxtExchange):
        def fetch_ticker(self, symbol):
            return {
                "symbol": symbol,
                "last": 1530.0,
                "high": 1605.0,
                "low": 1420.3,
                "percentage": 5.33,
                "info": {
                    "open24h": "1452.5",
                    "sodUtc0": "1470.0",
                    "sodUtc8": "1488.1",
                },
            }

    class TodayExchange(FakeExchange):
        def _create_exchange(self):
            return TodayTickerExchange()

    exchange = TodayExchange()
    exchange.initialize()

    ticker = exchange.fetch_ticker("OPENAI/USDT:USDT")

    assert ticker["change_percent"] == 5.33
    assert ticker["change_percent_24h"] == 5.33
    assert ticker["open24h"] == 1452.5
    assert ticker["sod_utc0"] == 1470.0
    assert ticker["sod_utc8"] == 1488.1
    assert ticker["change_percent_today"] == round((1530.0 - 1470.0) / 1470.0 * 100, 8)


def test_format_ticker_uses_okx_quote_currency_volume_for_turnover():
    exchange = FakeExchange()
    exchange.initialize()

    ticker = exchange._format_ticker(
        {
            "symbol": "DOGE/USDT:USDT",
            "last": 0.12,
            "baseVolume": None,
            "quoteVolume": None,
            "info": {
                "instType": "SWAP",
                "volCcy24h": "1000000",
                "volCcyQuote24h": "120000",
                "vol24h": "10000000",
            },
        }
    )

    assert ticker["volume"] == 1_000_000.0
    assert ticker["quote_volume"] == 120_000.0


def test_format_ticker_overrides_ccxt_contract_volume_with_okx_currency_volume():
    exchange = FakeExchange()
    exchange.initialize()

    ticker = exchange._format_ticker(
        {
            "symbol": "BTC/USDT:USDT",
            "last": 78222.0,
            # OKX SWAP ccxt baseVolume can mirror vol24h, whose unit is contracts.
            "baseVolume": 5_555_000.0,
            "quoteVolume": 434_000_000_000.0,
            "info": {
                "instType": "SWAP",
                "instId": "BTC-USDT-SWAP",
                "vol24h": "5555000",
                "volCcy24h": "55550",
            },
        }
    )

    assert ticker["volume"] == 55_550.0
    assert round(ticker["quote_volume"], 2) == 4_345_232_100.0


def test_format_ticker_estimates_okx_quote_turnover_from_base_volume_when_missing():
    exchange = FakeExchange()
    exchange.initialize()

    ticker = exchange._format_ticker(
        {
            "symbol": "DOGE/USDT:USDT",
            "last": 0.11097,
            "baseVolume": None,
            "quoteVolume": None,
            "info": {
                "instType": "SWAP",
                "volCcy24h": "5314000000",
                "vol24h": "5314000",
            },
        }
    )

    assert ticker["volume"] == 5_314_000_000.0
    assert round(ticker["quote_volume"], 2) == 589_694_580.0


def test_format_ticker_keeps_okx_spot_volume_semantics():
    exchange = FakeExchange()
    exchange.initialize()

    ticker = exchange._format_ticker(
        {
            "symbol": "DOGE/USDT",
            "last": 0.12,
            "baseVolume": None,
            "quoteVolume": None,
            "info": {
                "instType": "SPOT",
                "volCcy24h": "120000",
                "vol24h": "1000000",
            },
        }
    )

    assert ticker["volume"] == 1_000_000.0
    assert ticker["quote_volume"] == 120_000.0


def test_exogenous_ticker_uses_okx_quote_currency_turnover():
    class RawOkxApi:
        def publicGetMarketTicker(self, params):
            assert params == {"instId": "DOGE-USDT-SWAP"}
            return {
                "data": [
                    {
                        "last": "0.12",
                        "open24h": "0.10",
                        "bidPx": "0.119",
                        "askPx": "0.121",
                        "volCcy24h": "1000000",
                        "volCcyQuote24h": "120000",
                        "vol24h": "10000000",
                    }
                ]
            }

    class RawOkxExchange:
        exchange = RawOkxApi()

    service = ExogenousFeatureService()

    features = asyncio.run(service._fetch_ticker(RawOkxExchange(), "okx", "DOGE/USDT:USDT"))

    assert features["ticker_volume_base_24h"] == 1_000_000.0
    assert features["ticker_volume_quote_24h"] == 120_000.0
