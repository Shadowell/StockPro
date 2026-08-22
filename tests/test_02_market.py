"""
模块2: 行情数据API测试
"""
import pytest

from conftest import EXCHANGES
TEST_SYMBOL = "BTC/USDT"


class TestTicker:
    """单个行情"""

    @pytest.mark.market
    @pytest.mark.parametrize("exchange", EXCHANGES)
    def test_get_ticker(self, client, exchange):
        """获取单个交易对行情"""
        r = client.get("/market/ticker", params={"exchange": exchange, "symbol": TEST_SYMBOL})
        assert r.status_code == 200
        data = r.json()
        assert data.get("last") is not None, "缺少 last 价格"
        assert data["last"] > 0, "价格应该大于 0"
        assert "changePercent" in data or "change_percent" in data, "缺少涨跌幅"

    @pytest.mark.market
    @pytest.mark.parametrize("exchange", EXCHANGES)
    def test_ticker_has_volume(self, client, exchange):
        """行情应包含成交量"""
        r = client.get("/market/ticker", params={"exchange": exchange, "symbol": TEST_SYMBOL})
        data = r.json()
        volume = data.get("volume") or data.get("quoteVolume") or 0
        assert volume > 0, "成交量应该大于 0"


class TestKlines:
    """K线数据"""

    @pytest.mark.market
    def test_get_klines(self, client):
        """获取K线数据"""
        r = client.get("/market/klines", params={
            "exchange": "okx", "symbol": TEST_SYMBOL,
            "timeframe": "1h", "limit": 10
        })
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list), "K线应返回数组"
        assert len(data) >= 5, f"K线数量不足: {len(data)}"

    @pytest.mark.market
    def test_kline_structure(self, client):
        """K线数据结构完整"""
        r = client.get("/market/klines", params={
            "exchange": "okx", "symbol": TEST_SYMBOL,
            "timeframe": "1h", "limit": 3
        })
        data = r.json()
        assert len(data) > 0
        kline = data[0]
        required_fields = ["timestamp", "open", "high", "low", "close", "volume"]
        for field in required_fields:
            assert field in kline, f"K线缺少字段: {field}"
        assert kline["high"] >= kline["low"], "high 应 >= low"

    @pytest.mark.market
    @pytest.mark.parametrize("timeframe", ["1m", "5m", "15m", "1h", "4h", "1d"])
    def test_klines_timeframes(self, client, timeframe):
        """所有时间周期均可用"""
        r = client.get("/market/klines", params={
            "exchange": "okx", "symbol": TEST_SYMBOL,
            "timeframe": timeframe, "limit": 3
        })
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list) and len(data) > 0, f"周期 {timeframe} 无数据"


class TestOrderbook:
    """订单簿"""

    @pytest.mark.market
    def test_get_orderbook(self, client):
        """获取订单簿"""
        r = client.get("/market/orderbook", params={
            "exchange": "okx", "symbol": TEST_SYMBOL, "limit": 10
        })
        assert r.status_code == 200
        data = r.json()
        assert "bids" in data, "缺少 bids"
        assert "asks" in data, "缺少 asks"
        assert len(data["bids"]) > 0, "bids 为空"
        assert len(data["asks"]) > 0, "asks 为空"

    @pytest.mark.market
    def test_orderbook_sorted(self, client):
        """订单簿价格排序正确"""
        r = client.get("/market/orderbook", params={
            "exchange": "okx", "symbol": TEST_SYMBOL, "limit": 10
        })
        data = r.json()
        if len(data["bids"]) >= 2:
            # bids 应该降序
            assert data["bids"][0][0] >= data["bids"][1][0], "bids 应降序排列"
        if len(data["asks"]) >= 2:
            # asks 应该升序
            assert data["asks"][0][0] <= data["asks"][1][0], "asks 应升序排列"


class TestTickers:
    """批量行情"""

    @pytest.mark.market
    def test_get_tickers(self, client):
        """批量获取行情"""
        r = client.get("/market/tickers", params={"exchange": "okx"})
        assert r.status_code == 200
        data = r.json()
        # 可能返回 list 或 dict 包装
        tickers = data if isinstance(data, list) else data.get("tickers", [])
        assert len(tickers) > 10, f"行情条目过少: {len(tickers)}"


class TestSymbols:
    """交易对列表"""

    @pytest.mark.market
    @pytest.mark.parametrize("exchange", EXCHANGES)
    def test_get_symbols(self, client, exchange):
        """获取交易所支持的交易对"""
        r = client.get("/market/symbols", params={"exchange": exchange})
        assert r.status_code == 200
        data = r.json()
        symbols = data.get("symbols", [])
        assert len(symbols) > 10, f"{exchange} 交易对过少: {len(symbols)}"
        assert "BTC/USDT" in symbols, f"{exchange} 缺少 BTC/USDT"
