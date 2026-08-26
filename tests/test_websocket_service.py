import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.websocket_service import parse_subscription_key


def test_parse_kline_subscription_keeps_swap_symbol_and_timeframe():
    parsed = parse_subscription_key("kline:okx:DOT/USDT:USDT:15m", has_timeframe=True)

    assert parsed.channel == "kline"
    assert parsed.exchange == "okx"
    assert parsed.symbol == "DOT/USDT:USDT"
    assert parsed.timeframe == "15m"


def test_parse_kline_subscription_without_timeframe_keeps_swap_symbol():
    parsed = parse_subscription_key("kline:okx:DOT/USDT:USDT", has_timeframe=True)

    assert parsed.channel == "kline"
    assert parsed.exchange == "okx"
    assert parsed.symbol == "DOT/USDT:USDT"
    assert parsed.timeframe is None


def test_parse_symbol_subscription_keeps_swap_symbol_without_timeframe():
    parsed = parse_subscription_key("orderbook:okx:DOT/USDT:USDT")

    assert parsed.channel == "orderbook"
    assert parsed.exchange == "okx"
    assert parsed.symbol == "DOT/USDT:USDT"
    assert parsed.timeframe is None
