"""
行情数据服务
"""
from typing import List, Dict, Optional
import logging

from app.exchange import exchange_manager
from app.db.local_db import db_instance as db

logger = logging.getLogger(__name__)


class MarketService:
    """行情数据服务"""

    async def get_ticker(self, exchange_name: str, symbol: str) -> Dict:
        """获取单个交易对行情"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not supported")

        ticker = exchange.fetch_ticker(symbol)

        # 更新缓存
        db.update_ticker_cache(exchange_name, symbol, ticker)

        return ticker

    async def get_tickers(self, exchange_name: str, symbols: List[str] = None) -> List[Dict]:
        """获取多个交易对行情"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not supported")

        tickers = exchange.fetch_tickers(symbols)

        # 批量更新缓存
        for ticker in tickers:
            db.update_ticker_cache(exchange_name, ticker['symbol'], ticker)

        return tickers

    async def get_klines(self, exchange_name: str, symbol: str, timeframe: str = '1h',
                         limit: int = 100, start: int = None, end: int = None) -> List[Dict]:
        """获取 K 线数据"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not supported")

        # 先尝试从缓存获取
        cached = db.get_klines(exchange_name, symbol, timeframe, limit, start, end)

        # 如果缓存数据足够，直接返回
        if len(cached) >= limit:
            return cached[:limit]

        # 从交易所获取
        klines = exchange.fetch_ohlcv(symbol, timeframe, limit, start)

        # 保存到数据库
        if klines:
            db.insert_klines(exchange_name, symbol, timeframe, klines)

        return klines

    async def get_orderbook(self, exchange_name: str, symbol: str, limit: int = 20) -> Dict:
        """获取订单簿"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not supported")

        # OKX 合约仅支持特定 depth limit: 5, 10, 20, 50, 100, 500, 1000
        # 自动映射到最近的有效值
        valid_limits = [5, 10, 20, 50, 100, 500, 1000]
        adjusted_limit = min(v for v in valid_limits if v >= limit) if limit <= 1000 else 1000

        return exchange.fetch_order_book(symbol, adjusted_limit)

    async def get_trades(self, exchange_name: str, symbol: str, limit: int = 50) -> List[Dict]:
        """获取最近成交"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not supported")

        return exchange.fetch_trades(symbol, limit)

    async def get_symbols(self, exchange_name: str, quote: str = 'USDT', market_type: str = 'spot') -> List[str]:
        """获取交易对列表"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not supported")

        return exchange.get_symbols(quote, market_type)


# 全局服务实例
market_service = MarketService()
