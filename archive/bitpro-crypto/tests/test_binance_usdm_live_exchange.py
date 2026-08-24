import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.exchange.binance_usdm import BinanceUsdmExchange
from app.exchange.manager import ExchangeManager


def test_exchange_manager_registers_binance_usdm_for_public_market_reads():
    assert ExchangeManager.EXCHANGE_CLASSES["binanceusdm"] is BinanceUsdmExchange


def test_binance_usdm_private_exchange_uses_future_defaults_and_testnet():
    exchange = BinanceUsdmExchange(
        {
            "api_key": "binance-api-key",
            "api_secret": "binance-secret",
            "testnet": True,
        }
    )

    exchange.initialize()

    assert exchange.name == "binanceusdm"
    assert exchange.exchange.apiKey == "binance-api-key"
    assert exchange.exchange.secret == "binance-secret"
    assert exchange.exchange.options["defaultType"] == "future"
    assert "testnet.binancefuture.com" in exchange.exchange.urls["api"]["fapiPrivate"]


def test_binance_usdm_open_orders_uses_native_account_wide_futures_endpoint():
    class NativeFuturesClient:
        def __init__(self):
            self.requests = []

        def fapiPrivateGetOpenOrders(self, params):
            self.requests.append(params)
            return [
                {
                    "orderId": "123",
                    "clientOrderId": "bitpro-open-order",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "type": "LIMIT",
                    "price": "65000.5",
                    "origQty": "0.002",
                    "executedQty": "0.001",
                    "reduceOnly": False,
                    "positionSide": "BOTH",
                    "status": "NEW",
                    "time": 1710000000000,
                }
            ]

    exchange = BinanceUsdmExchange()
    exchange.exchange = NativeFuturesClient()

    orders = exchange.fetch_open_orders()

    assert exchange.exchange.requests == [{}]
    assert orders == [
        {
            "id": "123",
            "client_order_id": "bitpro-open-order",
            "exchange": "binanceusdm",
            "instrument_id": "BTCUSDT",
            "instrument_type": "SWAP",
            "symbol": "BTC/USDT:USDT",
            "side": "buy",
            "position_side": "net",
            "position_effect": "open",
            "reduce_only": False,
            "type": "limit",
            "price": 65000.5,
            "amount": 0.002,
            "filled": 0.001,
            "remaining": 0.001,
            "status": "open",
            "timestamp": 1710000000000,
        }
    ]


def test_binance_usdm_positions_use_native_position_risk_endpoint_in_hedge_mode():
    class NativeFuturesClient:
        def __init__(self):
            self.requests = []

        def fapiPrivateV3GetPositionRisk(self, params):
            self.requests.append(("v3", params))
            return []

        def fapiPrivateV2GetPositionRisk(self, params):
            self.requests.append(("v2", params))
            return [
                {
                    "symbol": "LABUSDT",
                    "positionSide": "LONG",
                    "positionAmt": "19",
                    "notional": "5.3276",
                    "entryPrice": "0.2804",
                    "markPrice": "0.2802",
                    "liquidationPrice": "0",
                    "unRealizedProfit": "-0.0038",
                    "leverage": "5",
                    "marginType": "isolated",
                    "isolatedMargin": "1.06552",
                    "initialMargin": "1.06552",
                    "maintMargin": "0.02131",
                },
                {
                    "symbol": "BTCUSDT",
                    "positionSide": "LONG",
                    "positionAmt": "0",
                },
            ]

    exchange = BinanceUsdmExchange()
    exchange.exchange = NativeFuturesClient()

    positions = exchange.fetch_positions(["LAB/USDT:USDT"])

    assert exchange.exchange.requests == [("v2", {"symbol": "LABUSDT"})]
    assert positions == [
        {
            "exchange": "binanceusdm",
            "symbol": "LAB/USDT:USDT",
            "side": "long",
            "pos_side": "long",
            "amount": 19.0,
            "contracts": 19.0,
            "contract_size": 1.0,
            "base_amount": 19.0,
            "notional": 5.3276,
            "entry_price": 0.2804,
            "mark_price": 0.2802,
            "liquidation_price": 0.0,
            "unrealized_pnl": -0.0038,
            "unrealized_pnl_pct": None,
            "percentage": None,
            "leverage": 5.0,
            "margin_mode": "isolated",
            "margin": 1.06552,
            "initial_margin": 1.06552,
            "maintenance_margin": 0.02131,
            "margin_ratio": None,
            "collateral": 1.06552,
        }
    ]
