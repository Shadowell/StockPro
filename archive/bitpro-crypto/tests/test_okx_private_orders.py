from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.exchange.okx import OKXExchange  # noqa: E402


class FakeOkxClient:
    def __init__(self):
        self.history_params = []
        self.pending_params = []
        self.asset_valuation_params = []
        self.ohlcv_params = []
        self.funding_params = []
        self.markets = {"BTC/USDT": {}, "ZAMA/USDT": {}}

    def safe_symbol(self, inst_id):
        if inst_id.endswith("-SWAP"):
            base, quote, _ = inst_id.split("-", 2)
            return f"{base}/{quote}:{quote}"
        return inst_id.replace('-', '/')

    def iso8601(self, timestamp):
        return f"iso-{timestamp}"

    def privateGetTradeOrdersPending(self, params):
        self.pending_params.append(params)
        if params.get("instType") == "SWAP":
            return {
                "data": [
                    {
                        "ordId": "open-swap-1",
                        "instId": "DOGE-USDT-SWAP",
                        "instType": "SWAP",
                        "side": "sell",
                        "posSide": "net",
                        "reduceOnly": "false",
                        "tdMode": "cross",
                        "ordType": "limit",
                        "px": "0.1088",
                        "sz": "1",
                        "accFillSz": "0",
                        "state": "live",
                        "cTime": "1777782803000",
                    }
                ]
            }
        return {
            "data": [
                {
                    "ordId": "open-1",
                    "instId": "BTC-USDT",
                    "side": "buy",
                    "ordType": "limit",
                    "px": "78000",
                    "sz": "0.01",
                    "accFillSz": "0.002",
                    "state": "partially_filled",
                    "cTime": "1777782801000",
                }
            ]
        }

    def privateGetTradeOrdersHistory(self, params):
        self.history_params.append(params)
        if params.get("instType") == "SWAP":
            return {
                "data": [
                    {
                        "ordId": "closed-swap-1",
                        "clOrdId": "bitpro-live-1",
                        "instId": "DOGE-USDT-SWAP",
                        "instType": "SWAP",
                        "side": "buy",
                        "posSide": "net",
                        "reduceOnly": "true",
                        "tdMode": "cross",
                        "ordType": "market",
                        "avgPx": "0.1086",
                        "fillPx": "0.1086",
                        "fillSz": "1",
                        "accFillSz": "1",
                        "sz": "1",
                        "state": "filled",
                        "fee": "-0.00005",
                        "feeCcy": "USDT",
                        "pnl": "0.01",
                        "tradeId": "trade-1",
                        "cTime": "1777782801000",
                        "uTime": "1777782803000",
                        "fillTime": "1777782803000",
                    }
                ]
            }
        return {
            "data": [
                {
                    "ordId": "closed-1",
                    "instId": "ETH-USDT",
                    "side": "sell",
                    "ordType": "market",
                    "avgPx": "3900",
                    "sz": "0.2",
                    "accFillSz": "0.2",
                    "state": "filled",
                    "fee": "-0.31",
                    "feeCcy": "USDT",
                    "uTime": "1777782802000",
                }
            ]
        }

    def privateGetAssetAssetValuation(self, params):
        self.asset_valuation_params.append(params)
        return {"data": [{"totalBal": "132"}]}

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.ohlcv_params.append({"symbol": symbol, "timeframe": timeframe, "since": since, "limit": limit})
        return [[since or 0, 0, 0, 0, 100, 0]]

    def publicGetPublicFundingRate(self, params):
        self.funding_params.append(params)
        return {
            "data": [
                {
                    "instId": "LITE-USDT-SWAP",
                    "fundingRate": "0.00226412",
                    "nextFundingRate": "0.001",
                    "fundingTime": "1777785600000",
                },
                {
                    "instId": "BTC-USDT-SWAP",
                    "fundingRate": "0.0000516",
                    "nextFundingRate": "",
                    "fundingTime": "1777785600000",
                },
            ]
        }


class FakeOkxTickerClient:
    def __init__(self):
        self.mark_price_params = []
        self.markets = {
            "DOGE/USDT:USDT": {"id": "DOGE-USDT-SWAP", "swap": True},
            "DOGE/USDT": {"id": "DOGE-USDT", "spot": True},
        }

    def load_markets(self):
        return self.markets

    def fetch_ticker(self, symbol):
        return {
            "symbol": symbol,
            "last": 0.1121,
            "bid": 0.11209,
            "ask": 0.1121,
            "info": {"open24h": "0.10942", "sodUtc8": "0.10862"},
        }

    def market(self, symbol):
        return self.markets[symbol]

    def publicGetPublicMarkPrice(self, params):
        self.mark_price_params.append(params)
        return {"code": "0", "data": [{"instId": params["instId"], "markPx": "0.11205", "ts": "1778659618241"}]}


def test_okx_swap_ticker_includes_public_mark_price():
    ex = OKXExchange.__new__(OKXExchange)
    ex.config = {}
    ex.exchange = FakeOkxTickerClient()
    ex._markets_loaded = True

    ticker = ex.fetch_ticker("DOGE/USDT:USDT")

    assert ticker["last"] == 0.1121
    assert ticker["mark_price"] == 0.11205
    assert ticker["markPrice"] == 0.11205
    assert ex.exchange.mark_price_params == [{"instType": "SWAP", "instId": "DOGE-USDT-SWAP"}]


def make_exchange():
    ex = OKXExchange.__new__(OKXExchange)
    ex.exchange = FakeOkxClient()
    ex._markets_loaded = True
    return ex


def test_fetch_funding_rates_uses_any_inst_id_for_okx_full_market():
    ex = make_exchange()

    rates = ex.fetch_funding_rates()

    assert ex.exchange.funding_params == [{"instId": "ANY"}]
    assert [row["symbol"] for row in rates] == ["LITE/USDT:USDT", "BTC/USDT:USDT"]
    assert rates[0]["current_rate"] == 0.00226412
    assert rates[0]["predicted_rate"] == 0.001
    assert rates[1]["predicted_rate"] is None


def test_fetch_open_orders_uses_okx_pending_endpoint():
    ex = make_exchange()
    orders = ex.fetch_open_orders()

    assert ex.exchange.pending_params == [{"instType": "SPOT"}, {"instType": "SWAP"}]
    assert orders[0]["source"] == "okx"
    assert orders[0]["id"] == "open-swap-1"
    assert orders[0]["symbol"] == "DOGE/USDT:USDT"
    assert orders[0]["status"] == "open"
    assert orders[0]["instrument_type"] == "SWAP"
    assert orders[0]["position_direction"] == "short"
    assert orders[0]["position_effect"] == "open"
    assert orders[1]["remaining"] == 0.008


def test_fetch_order_history_uses_okx_spot_and_swap_history_endpoints():
    ex = make_exchange()
    orders = ex.fetch_order_history(limit=50)

    assert ex.exchange.history_params == [
        {"instType": "SPOT", "limit": "50"},
        {"instType": "SWAP", "limit": "50"},
    ]
    assert orders[0]["source"] == "okx"
    assert orders[0]["id"] == "closed-swap-1"
    assert orders[0]["symbol"] == "DOGE/USDT:USDT"
    assert orders[0]["status"] == "closed"
    assert orders[0]["instrument_type"] == "SWAP"
    assert orders[0]["position_side"] == "net"
    assert orders[0]["reduce_only"] is True
    assert orders[0]["td_mode"] == "cross"
    assert orders[0]["position_direction"] == "short"
    assert orders[0]["position_effect"] == "close"
    assert orders[0]["fill_price"] == 0.1086
    assert orders[0]["fill_size"] == 1
    assert orders[0]["pnl"] == 0.01
    assert orders[0]["trade_id"] == "trade-1"
    assert orders[0]["fee_currency"] == "USDT"
    assert orders[1]["id"] == "closed-1"


def test_fetch_account_return_rates_uses_okx_valuation_and_daily_candles():
    ex = make_exchange()
    ex.fetch_balance = lambda: [
        {"currency": "BTC", "total": 1},
        {"currency": "USDT", "total": 20},
    ]

    rates = ex.fetch_account_return_rates()

    assert ex.exchange.asset_valuation_params == [{"ccy": "USD"}]
    assert [call["timeframe"] for call in ex.exchange.ohlcv_params] == ["1d", "1d", "1d"]
    assert [call["symbol"] for call in ex.exchange.ohlcv_params] == [
        "BTC/USDT",
        "BTC/USDT",
        "BTC/USDT",
    ]
    assert rates["valuation_usd"] == 132
    assert rates["one_day"] == 10
    assert rates["seven_day"] == 10
    assert rates["thirty_day"] == 10
    assert rates["source"] == "okx"
