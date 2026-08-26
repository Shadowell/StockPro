"""
WebSocket 服务
实时数据推送: 行情、资金费率、订单更新等
"""
import asyncio
import json
import logging
from typing import Dict, Set, List, Optional, Any
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ChannelType(str, Enum):
    """订阅频道类型"""
    TICKER = "ticker"           # 单个交易对实时行情
    TICKERS = "tickers"         # 批量行情（首页用）
    KLINE = "kline"             # K线更新
    ORDERBOOK = "orderbook"     # 订单簿
    TRADES = "trades"           # 成交记录
    FUNDING = "funding"         # 资金费率
    LIQUIDATION = "liquidation" # 爆仓
    STRATEGY = "strategy"       # 策略状态
    LIVE_ORDER = "live_order"   # BitPro 实盘策略订单更新


@dataclass
class Subscription:
    """订阅信息"""
    channel: ChannelType
    exchange: str
    symbol: Optional[str] = None
    params: Dict = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedSubscriptionKey:
    channel: str
    exchange: str
    symbol: Optional[str] = None
    timeframe: Optional[str] = None


def _looks_like_timeframe(value: str) -> bool:
    text = str(value or "").strip().lower()
    return len(text) >= 2 and text[:-1].isdigit() and text[-1] in {"m", "h", "d", "w"}


def parse_subscription_key(sub_key: str, *, has_timeframe: bool = False) -> ParsedSubscriptionKey:
    """Parse a subscription key while preserving OKX swap symbols.

    Contract symbols such as ``DOT/USDT:USDT`` contain ``:`` themselves, so
    kline keys must split the timeframe from the right edge instead of using
    the first colon after the exchange.
    """
    parts = str(sub_key or "").split(":", 2)
    channel = parts[0] if parts else ""
    exchange = parts[1] if len(parts) > 1 else ""
    rest = parts[2] if len(parts) > 2 else ""
    if not rest:
        return ParsedSubscriptionKey(channel=channel, exchange=exchange)
    if has_timeframe:
        if ":" in rest:
            symbol, timeframe = rest.rsplit(":", 1)
            if not _looks_like_timeframe(timeframe):
                return ParsedSubscriptionKey(channel=channel, exchange=exchange, symbol=rest or None)
            return ParsedSubscriptionKey(
                channel=channel,
                exchange=exchange,
                symbol=symbol or None,
                timeframe=timeframe or None,
            )
        return ParsedSubscriptionKey(channel=channel, exchange=exchange, symbol=rest or None)
    return ParsedSubscriptionKey(channel=channel, exchange=exchange, symbol=rest or None)


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        # websocket -> subscriptions
        self.active_connections: Dict[WebSocket, Set[str]] = {}
        # subscription_key -> set of websockets
        self.subscriptions: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        """新连接"""
        await websocket.accept()
        async with self._lock:
            self.active_connections[websocket] = set()
        logger.info(f"WebSocket connected. Total: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        """断开连接"""
        async with self._lock:
            # 清理订阅
            if websocket in self.active_connections:
                subs = self.active_connections.pop(websocket)
                for sub_key in subs:
                    if sub_key in self.subscriptions:
                        self.subscriptions[sub_key].discard(websocket)
                        if not self.subscriptions[sub_key]:
                            del self.subscriptions[sub_key]
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")

    async def subscribe(self, websocket: WebSocket, channel: str,
                       exchange: str, symbol: str = None, timeframe: str = None) -> str:
        """订阅频道"""
        sub_key = self._make_key(channel, exchange, symbol, timeframe)

        async with self._lock:
            if websocket not in self.active_connections:
                return None

            self.active_connections[websocket].add(sub_key)

            if sub_key not in self.subscriptions:
                self.subscriptions[sub_key] = set()
            self.subscriptions[sub_key].add(websocket)

        logger.debug(f"Subscribed to {sub_key}")
        return sub_key

    async def unsubscribe(self, websocket: WebSocket, channel: str,
                         exchange: str, symbol: str = None, timeframe: str = None) -> bool:
        """取消订阅"""
        sub_key = self._make_key(channel, exchange, symbol, timeframe)

        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections[websocket].discard(sub_key)

            if sub_key in self.subscriptions:
                self.subscriptions[sub_key].discard(websocket)
                if not self.subscriptions[sub_key]:
                    del self.subscriptions[sub_key]

        return True

    async def broadcast(self, channel: str, exchange: str,
                       symbol: str, data: Dict, timeframe: str = None):
        """广播数据到订阅者"""
        sub_key = self._make_key(channel, exchange, symbol, timeframe)

        if sub_key not in self.subscriptions:
            return

        message = json.dumps({
            "channel": channel,
            "exchange": exchange,
            "symbol": symbol,
            "timeframe": timeframe,
            "data": data,
            "timestamp": int(datetime.now().timestamp() * 1000)
        })

        subscribers = list(self.subscriptions[sub_key])

        async def _send_one(websocket: WebSocket):
            try:
                await websocket.send_text(message)
                return None
            except Exception as e:
                logger.warning(f"Failed to send message: {e}")
                return websocket

        results = await asyncio.gather(*(_send_one(ws) for ws in subscribers), return_exceptions=False)
        dead_connections = [ws for ws in results if ws is not None]

        # 清理失效连接
        for ws in dead_connections:
            await self.disconnect(ws)

    async def send_personal(self, websocket: WebSocket, data: Dict):
        """发送个人消息"""
        try:
            await websocket.send_json(data)
        except Exception as e:
            logger.warning(f"Failed to send personal message: {e}")

    def _make_key(self, channel: str, exchange: str, symbol: str = None, timeframe: str = None) -> str:
        """生成订阅 key"""
        if symbol:
            if timeframe:
                return f"{channel}:{exchange}:{symbol}:{timeframe}"
            return f"{channel}:{exchange}:{symbol}"
        return f"{channel}:{exchange}"

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "connections": len(self.active_connections),
            "subscriptions": {k: len(v) for k, v in self.subscriptions.items()}
        }

    async def get_subscription_keys(self, prefix: Optional[str] = None) -> List[str]:
        """获取订阅键快照，避免遍历期间字典变更。"""
        async with self._lock:
            keys = list(self.subscriptions.keys())
        if prefix:
            return [k for k in keys if k.startswith(prefix)]
        return keys


class RealtimeDataService:
    """实时数据服务"""

    def __init__(self, manager: ConnectionManager):
        self.manager = manager
        self._running = False
        self._tasks: List[asyncio.Task] = []

    async def start(self):
        """启动实时数据服务"""
        if self._running:
            return

        self._running = True

        # 启动各数据源任务
        self._tasks = [
            asyncio.create_task(self._ticker_loop()),
            asyncio.create_task(self._tickers_loop()),
            asyncio.create_task(self._funding_loop()),
            asyncio.create_task(self._kline_loop()),
            asyncio.create_task(self._orderbook_loop()),
            asyncio.create_task(self._live_order_loop()),
        ]

        logger.info("Realtime data service started")

    async def stop(self):
        """停止服务"""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        logger.info("Realtime data service stopped")

    async def _ticker_loop(self):
        """行情推送循环"""
        from app.exchange import exchange_manager

        async def _publish_one(sub_key: str):
            parsed = parse_subscription_key(sub_key)
            if not parsed.exchange or not parsed.symbol:
                return
            exchange_name, symbol = parsed.exchange, parsed.symbol
            exchange = exchange_manager.get_exchange(exchange_name)
            if not exchange:
                return
            try:
                ticker = await asyncio.to_thread(exchange.fetch_ticker, symbol)
                await self.manager.broadcast("ticker", exchange_name, symbol, ticker)
            except Exception as e:
                logger.warning(f"Failed to fetch ticker {symbol}: {e}")

        while self._running:
            try:
                ticker_subs = await self.manager.get_subscription_keys("ticker:")
                if ticker_subs:
                    await asyncio.gather(*(_publish_one(sub_key) for sub_key in ticker_subs))
                await asyncio.sleep(2)  # 2秒更新一次
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ticker loop error: {e}")
                await asyncio.sleep(5)

    async def _tickers_loop(self):
        """批量行情推送循环（首页用）

        订阅 key 格式: tickers:{exchange}
        前端订阅时不需要指定 symbol，后端会推送所有主流交易对的 ticker 数据
        """
        from app.exchange import exchange_manager

        # 主流交易对列表
        BATCH_SYMBOLS = [
            'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
            'DOGE/USDT', 'ADA/USDT', 'AVAX/USDT', 'DOT/USDT', 'LINK/USDT',
            'LTC/USDT', 'UNI/USDT', 'NEAR/USDT', 'APT/USDT', 'ARB/USDT',
            'OP/USDT', 'SUI/USDT', 'PEPE/USDT', 'FIL/USDT', 'ATOM/USDT',
            'INJ/USDT', 'FET/USDT', 'TIA/USDT', 'BCH/USDT', 'XLM/USDT',
            'WIF/USDT', 'RUNE/USDT', 'AAVE/USDT', 'MATIC/USDT', 'STX/USDT',
            'IMX/USDT', 'SEI/USDT',
        ]

        while self._running:
            try:
                tickers_subs = await self.manager.get_subscription_keys("tickers:")
                exchanges = {
                    sub_key.split(":", 2)[1]
                    for sub_key in tickers_subs
                    if len(sub_key.split(":", 2)) >= 2
                }

                async def _publish_exchange(exchange_name: str):
                    exchange = exchange_manager.get_exchange(exchange_name)
                    if not exchange:
                        return
                    try:
                        all_tickers = await asyncio.to_thread(exchange.fetch_tickers, BATCH_SYMBOLS)
                        if all_tickers:
                            await self.manager.broadcast("tickers", exchange_name, "*", all_tickers)
                    except Exception as e:
                        logger.warning(f"Failed to batch fetch tickers for {exchange_name}: {e}")

                if exchanges:
                    await asyncio.gather(*(_publish_exchange(exchange_name) for exchange_name in exchanges))
                await asyncio.sleep(3)  # 3秒批量更新一次
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Tickers loop error: {e}")
                await asyncio.sleep(5)

    async def _funding_loop(self):
        """资金费率推送循环"""
        from app.exchange import exchange_manager

        async def _publish_one(sub_key: str):
            parsed = parse_subscription_key(sub_key)
            if not parsed.exchange:
                return
            exchange_name = parsed.exchange
            symbol = parsed.symbol
            exchange = exchange_manager.get_exchange(exchange_name)
            if not exchange:
                return
            try:
                if symbol:
                    rate = await asyncio.to_thread(exchange.fetch_funding_rate, symbol)
                    if rate:
                        await self.manager.broadcast("funding", exchange_name, symbol, rate)
                    return

                rates = await asyncio.to_thread(exchange.fetch_funding_rates)
                for rate in rates[:20]:
                    await self.manager.broadcast(
                        "funding",
                        exchange_name,
                        rate.get("symbol", ""),
                        rate,
                    )
            except Exception as e:
                logger.warning(f"Failed to fetch funding: {e}")

        while self._running:
            try:
                funding_subs = await self.manager.get_subscription_keys("funding:")
                if funding_subs:
                    await asyncio.gather(*(_publish_one(sub_key) for sub_key in funding_subs))
                await asyncio.sleep(30)  # 30秒更新一次
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Funding loop error: {e}")
                await asyncio.sleep(60)

    async def _kline_loop(self):
        """K线推送循环（按订阅 timeframe）"""
        from app.exchange import exchange_manager

        async def _publish_one(sub_key: str):
            # key: kline:{exchange}:{symbol}:{timeframe}
            parsed = parse_subscription_key(sub_key, has_timeframe=True)
            if not parsed.exchange or not parsed.symbol:
                return
            exchange_name = parsed.exchange
            symbol = parsed.symbol
            timeframe = parsed.timeframe or "1m"
            exchange = exchange_manager.get_exchange(exchange_name)
            if not exchange:
                return
            try:
                bars = await asyncio.to_thread(exchange.fetch_ohlcv, symbol, timeframe, 2)
                if not bars:
                    return
                c = bars[-1]
                if isinstance(c, dict):
                    cl = float(c["close"])
                    vol = float(c.get("volume") or 0)
                    qv_raw = c.get("quote_volume")
                    qv = float(qv_raw) if qv_raw is not None else cl * vol
                    bar = {
                        "timestamp": int(c["timestamp"]),
                        "open": float(c["open"]),
                        "high": float(c["high"]),
                        "low": float(c["low"]),
                        "close": cl,
                        "volume": vol,
                        "quote_volume": qv,
                    }
                else:
                    # 兼容若某处仍为原始 OHLCV 数组
                    cl = float(c[4])
                    vol = float(c[5])
                    qv = float(c[6]) if len(c) > 6 and c[6] is not None else cl * vol
                    bar = {
                        "timestamp": int(c[0]),
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": cl,
                        "volume": vol,
                        "quote_volume": qv,
                    }
                await self.manager.broadcast("kline", exchange_name, symbol, bar, timeframe=timeframe)
            except Exception as e:
                logger.warning(f"Failed to fetch kline {symbol} {timeframe}: {e}")

        while self._running:
            try:
                subs = await self.manager.get_subscription_keys("kline:")
                if subs:
                    await asyncio.gather(*(_publish_one(sub_key) for sub_key in subs))
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Kline loop error: {e}")
                await asyncio.sleep(5)

    async def _orderbook_loop(self):
        """订单簿推送循环"""
        from app.exchange import exchange_manager

        async def _publish_one(sub_key: str):
            # key: orderbook:{exchange}:{symbol}:
            parsed = parse_subscription_key(sub_key)
            if not parsed.exchange or not parsed.symbol:
                return
            exchange_name = parsed.exchange
            symbol = parsed.symbol
            exchange = exchange_manager.get_exchange(exchange_name)
            if not exchange:
                return
            try:
                orderbook = await asyncio.to_thread(exchange.fetch_order_book, symbol, 20)
                if orderbook:
                    await self.manager.broadcast("orderbook", exchange_name, symbol, orderbook)
            except Exception as e:
                logger.warning(f"Failed to fetch orderbook {symbol}: {e}")

        while self._running:
            try:
                subs = await self.manager.get_subscription_keys("orderbook:")
                if subs:
                    await asyncio.gather(*(_publish_one(sub_key) for sub_key in subs))
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Orderbook loop error: {e}")
                await asyncio.sleep(5)

    async def _live_order_loop(self):
        """BitPro 实盘策略订单更新桥。

        订阅 key: live_order:{exchange}:{account_id}
        只读取 live_signal_executions 中已有 BitPro clOrdId/执行记录，不广播手工或外部订单。
        """
        from app.services.live_signal_execution_service import live_signal_execution_service

        last_seen: Dict[str, int] = {}

        async def _publish_one(sub_key: str):
            parsed = parse_subscription_key(sub_key)
            if not parsed.exchange or not parsed.symbol:
                return
            exchange_name = parsed.exchange
            account_id = parsed.symbol or "default"
            after_id = last_seen.get(sub_key, 0)
            updates = await asyncio.to_thread(
                live_signal_execution_service.list_live_order_updates,
                account_id=account_id,
                after_id=after_id,
                limit=100,
            )
            if not updates:
                return
            last_seen[sub_key] = max(int(item.get("id") or 0) for item in updates)
            await self.manager.broadcast("live_order", exchange_name, account_id, {"updates": updates})

        while self._running:
            try:
                subs = await self.manager.get_subscription_keys("live_order:")
                if subs:
                    await asyncio.gather(*(_publish_one(sub_key) for sub_key in subs))
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Live order loop error: {e}")
                await asyncio.sleep(5)


# 全局实例
connection_manager = ConnectionManager()
realtime_service = RealtimeDataService(connection_manager)
