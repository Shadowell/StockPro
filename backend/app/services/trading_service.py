"""
交易服务
处理实盘交易相关逻辑
集成风控模块，所有交易指令必须经过风控检查
"""
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import logging
import json

from app.db.local_db import db_instance as db
from app.exchange import exchange_manager
from app.core.config import settings
from app.services.risk_manager import RiskManager, RiskConfig, RiskLevel
from app.services.feishu_notifier import feishu_notifier

logger = logging.getLogger(__name__)


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class TradeOrder:
    """交易订单"""
    id: Optional[str] = None
    exchange: str = "okx"
    symbol: str = ""
    side: str = ""
    type: str = "market"
    price: Optional[float] = None
    amount: float = 0
    filled: float = 0
    remaining: float = 0
    cost: float = 0
    fee: float = 0
    status: str = "pending"
    timestamp: int = 0
    

class TradingService:
    """交易服务 — 集成风控"""
    
    def __init__(self):
        self._orders: Dict[str, TradeOrder] = {}
        self._risk_manager = RiskManager(RiskConfig())
        self._risk_initialized = False
    
    def _ensure_risk_initialized(self, equity: float = 10000):
        """确保风控已初始化"""
        if not self._risk_initialized:
            self._risk_manager.initialize(equity)
            self._risk_initialized = True

    async def _notify_exchange_failure(self, op: str, exchange_name: str, symbol: str = "", exc: Exception = None):
        detail = f"{op} failed on {exchange_name}"
        if symbol:
            detail += f" symbol={symbol}"
        if exc is not None:
            detail += f" err={exc}"
        logger.error(detail)
        try:
            await feishu_notifier.notify_risk_alert("EXCHANGE_API_FAILED", detail)
        except Exception:
            pass
        
    # ============================================
    # 账户相关
    # ============================================
    
    async def get_balance(self, exchange_name: str) -> List[Dict]:
        """获取账户余额（合并）"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not available")
        
        try:
            balance = exchange.fetch_balance()
            return balance
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            await self._notify_exchange_failure("fetch_balance", exchange_name, exc=e)
            raise
    
    async def get_balance_detail(self, exchange_name: str) -> Dict:
        """获取分账户余额（trading / funding 分开列出）"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not available")

        detail_fetcher = getattr(exchange, "fetch_balance_detail", None)
        if callable(detail_fetcher):
            try:
                return detail_fetcher()
            except Exception as e:
                logger.warning(f"Failed to fetch exchange-specific balance detail: {e}")
                return {"trading": [], "funding": []}
        
        result = {"trading": [], "funding": []}
        for acct_type in ["trading", "funding"]:
            try:
                raw = exchange.exchange.fetch_balance({"type": acct_type})
                for currency, data in raw.items():
                    if currency in ("info", "timestamp", "datetime", "free", "used", "total"):
                        continue
                    if not isinstance(data, dict):
                        continue
                    total = data.get("total", 0) or 0
                    free = data.get("free", 0) or 0
                    used = data.get("used", 0) or 0
                    if total <= 0 and free <= 0:
                        continue
                    result[acct_type].append({
                        "currency": currency,
                        "free": free,
                        "used": used,
                        "total": total,
                    })
            except Exception as e:
                logger.warning(f"Failed to fetch {acct_type} balance: {e}")
        return result

    async def get_account_return_rates(self, exchange_name: str) -> Dict[str, Any]:
        """获取 OKX 账户 1日/7日/30日收益率。"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not available")

        fetcher = getattr(exchange, "fetch_account_return_rates", None)
        if not callable(fetcher):
            return {"one_day": None, "seven_day": None, "thirty_day": None, "source": "unsupported"}
        try:
            return fetcher()
        except Exception as e:
            logger.warning("Failed to fetch account return rates for %s: %s", exchange_name, e)
            return {
                "one_day": None,
                "seven_day": None,
                "thirty_day": None,
                "source": "okx",
                "error": str(e),
            }
    
    async def transfer(self, exchange_name: str, currency: str, amount: float,
                       from_account: str, to_account: str) -> Dict:
        """OKX 资金划转（funding <-> trading）"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not available")
        
        # OKX 划转 API: transfer(code, amount, fromAccount, toAccount)
        # OKX account types: 'funding' = 6, 'trading' = 18 (统一账户)
        try:
            result = exchange.exchange.transfer(currency, amount, from_account, to_account)
            logger.info(f"Transfer {amount} {currency}: {from_account} -> {to_account}")
            return {
                "currency": currency,
                "amount": amount,
                "from": from_account,
                "to": to_account,
                "id": result.get("id", ""),
            }
        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            raise
    
    async def get_positions(self, exchange_name: str, symbol: str = None) -> List[Dict]:
        """获取持仓"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not available")
        
        try:
            symbols = [symbol] if symbol else None
            positions = exchange.fetch_positions(symbols)
            return positions
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            await self._notify_exchange_failure("fetch_positions", exchange_name, symbol=symbol or "", exc=e)
            raise
    
    # ============================================
    # 现货交易
    # ============================================
    
    async def spot_market_buy(self, exchange_name: str, symbol: str, 
                              amount: float) -> Dict:
        """现货市价买入"""
        return await self._create_order(
            exchange_name, symbol, OrderSide.BUY, OrderType.MARKET, amount,
            params={'type': 'spot'}
        )
    
    async def spot_market_sell(self, exchange_name: str, symbol: str,
                               amount: float) -> Dict:
        """现货市价卖出"""
        return await self._create_order(
            exchange_name, symbol, OrderSide.SELL, OrderType.MARKET, amount,
            params={'type': 'spot'}
        )
    
    async def spot_limit_buy(self, exchange_name: str, symbol: str,
                             amount: float, price: float) -> Dict:
        """现货限价买入"""
        return await self._create_order(
            exchange_name, symbol, OrderSide.BUY, OrderType.LIMIT, amount, price,
            params={'type': 'spot'}
        )
    
    async def spot_limit_sell(self, exchange_name: str, symbol: str,
                              amount: float, price: float) -> Dict:
        """现货限价卖出"""
        return await self._create_order(
            exchange_name, symbol, OrderSide.SELL, OrderType.LIMIT, amount, price,
            params={'type': 'spot'}
        )
    
    # ============================================
    # 合约交易
    # ============================================
    
    async def futures_open_long(self, exchange_name: str, symbol: str,
                                amount: float, leverage: int = 1,
                                price: float = None) -> Dict:
        """
        合约开多
        
        Args:
            exchange_name: 交易所
            symbol: 交易对 (如 BTC/USDT:USDT)
            amount: 数量
            leverage: 杠杆倍数
            price: 限价 (None=市价)
        """
        # 设置杠杆
        await self._set_leverage(exchange_name, symbol, leverage)
        
        order_type = OrderType.LIMIT if price else OrderType.MARKET
        
        return await self._create_order(
            exchange_name, symbol, OrderSide.BUY, order_type, amount, price,
            params={'positionSide': 'LONG'}
        )
    
    async def futures_open_short(self, exchange_name: str, symbol: str,
                                 amount: float, leverage: int = 1,
                                 price: float = None) -> Dict:
        """合约开空"""
        await self._set_leverage(exchange_name, symbol, leverage)
        
        order_type = OrderType.LIMIT if price else OrderType.MARKET
        
        return await self._create_order(
            exchange_name, symbol, OrderSide.SELL, order_type, amount, price,
            params={'positionSide': 'SHORT'}
        )
    
    async def futures_close_long(self, exchange_name: str, symbol: str,
                                 amount: float, price: float = None) -> Dict:
        """合约平多"""
        order_type = OrderType.LIMIT if price else OrderType.MARKET
        
        return await self._create_order(
            exchange_name, symbol, OrderSide.SELL, order_type, amount, price,
            params={'positionSide': 'LONG', 'reduceOnly': True}
        )
    
    async def futures_close_short(self, exchange_name: str, symbol: str,
                                  amount: float, price: float = None) -> Dict:
        """合约平空"""
        order_type = OrderType.LIMIT if price else OrderType.MARKET
        
        return await self._create_order(
            exchange_name, symbol, OrderSide.BUY, order_type, amount, price,
            params={'positionSide': 'SHORT', 'reduceOnly': True}
        )
    
    async def futures_close_all(self, exchange_name: str, symbol: str) -> List[Dict]:
        """平掉指定交易对的所有仓位"""
        positions = await self.get_positions(exchange_name, symbol)
        results = []
        
        for pos in positions:
            if pos.get('amount', 0) == 0:
                continue
            
            side = pos.get('side')
            amount = abs(pos.get('amount', 0))
            
            if side == 'long':
                result = await self.futures_close_long(exchange_name, symbol, amount)
            else:
                result = await self.futures_close_short(exchange_name, symbol, amount)
            
            results.append(result)
        
        return results
    
    # ============================================
    # 订单管理
    # ============================================
    
    async def cancel_order(self, exchange_name: str, order_id: str, 
                           symbol: str) -> Dict:
        """撤销订单"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not available")
        
        try:
            result = exchange.cancel_order(order_id, symbol)
            logger.info(f"Order cancelled: {order_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            await self._notify_exchange_failure("cancel_order", exchange_name, symbol=symbol, exc=e)
            raise
    
    async def cancel_all_orders(self, exchange_name: str, symbol: str = None) -> int:
        """撤销所有订单"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not available")
        
        try:
            orders = exchange.fetch_open_orders(symbol)
            cancelled = 0
            
            for order in orders:
                try:
                    exchange.cancel_order(order['id'], order['symbol'])
                    cancelled += 1
                except:
                    pass
            
            logger.info(f"Cancelled {cancelled} orders")
            return cancelled
        except Exception as e:
            logger.error(f"Failed to cancel orders: {e}")
            await self._notify_exchange_failure("cancel_all_orders", exchange_name, symbol=symbol or "", exc=e)
            raise
    
    async def get_open_orders(self, exchange_name: str, 
                              symbol: str = None) -> List[Dict]:
        """获取未成交订单"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not available")
        
        try:
            orders = exchange.fetch_open_orders(symbol)
            return orders
        except Exception as e:
            logger.error(f"Failed to fetch open orders: {e}")
            raise
    
    async def get_order(self, exchange_name: str, order_id: str, 
                        symbol: str) -> Optional[Dict]:
        """获取订单详情"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not available")
        
        try:
            if hasattr(exchange.exchange, 'fetch_order'):
                order = exchange.exchange.fetch_order(order_id, symbol)
                return exchange._format_order(order)
        except Exception as e:
            logger.error(f"Failed to fetch order: {e}")
        
        return None
    
    async def get_order_history(self, exchange_name: str, symbol: str = None,
                                limit: int = 50) -> List[Dict]:
        """获取历史订单"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not available")
        
        try:
            if hasattr(exchange, 'fetch_order_history'):
                return exchange.fetch_order_history(symbol, limit)
            if hasattr(exchange.exchange, 'fetch_closed_orders'):
                orders = exchange.exchange.fetch_closed_orders(symbol, limit=limit)
                return [exchange._format_order(o) for o in orders]
        except Exception as e:
            logger.error(f"Failed to fetch order history: {e}")
            raise

        return []
    
    async def get_my_trades(self, exchange_name: str, symbol: str,
                            limit: int = 50) -> List[Dict]:
        """获取成交记录"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not available")
        
        try:
            trades = exchange.fetch_my_trades(symbol, limit)
            return trades
        except Exception as e:
            logger.error(f"Failed to fetch trades: {e}")
            raise
    
    # ============================================
    # 内部方法
    # ============================================
    
    async def _create_order(self, exchange_name: str, symbol: str,
                            side: OrderSide, order_type: OrderType,
                            amount: float, price: float = None,
                            params: Dict = None) -> Dict:
        """创建订单 — 所有交易必须经过风控检查"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not available")
        
        try:
            # ====== 风控前置检查 ======
            exec_price = price
            if not exec_price:
                # 市价单：先获取当前价格用于风控评估
                ticker = exchange.fetch_ticker(symbol)
                exec_price = ticker.get('last', 0)
            
            if exec_price and exec_price > 0:
                # 获取当前账户权益用于风控计算
                current_equity = await self._get_account_equity(exchange_name)
                self._ensure_risk_initialized(current_equity)
                
                # 执行风控检查
                risk_side = 'long' if side == OrderSide.BUY else 'short'
                risk_result = self._risk_manager.check_order(
                    symbol=symbol,
                    side=risk_side,
                    amount=amount,
                    price=exec_price,
                    current_equity=current_equity,
                )
                
                # 风控拒绝
                if not risk_result.approved:
                    reasons = '; '.join(risk_result.reasons)
                    logger.warning(f"Order REJECTED by risk manager: {reasons}")
                    raise ValueError(f"风控拒绝: {reasons}")
                
                # 风控调整仓位
                if risk_result.adjusted_amount is not None:
                    old_amount = amount
                    amount = risk_result.adjusted_amount
                    logger.info(
                        f"Risk adjusted amount: {old_amount:.6f} -> {amount:.6f} "
                        f"({'; '.join(risk_result.warnings)})"
                    )
                
                # 记录风控建议的止损止盈（供日志参考）
                if risk_result.stop_loss:
                    logger.info(f"Risk suggested SL: {risk_result.stop_loss:.2f}, TP: {risk_result.take_profit:.2f}")
            
            # ====== 执行下单 ======
            order = exchange.create_order(
                symbol=symbol,
                type=order_type.value,
                side=side.value,
                amount=amount,
                price=price,
                params=params or {}
            )
            
            # 记录到数据库
            self._save_order_to_db(exchange_name, order)
            
            logger.info(f"Order created: {side.value} {amount} {symbol} @ {price or 'market'}")
            return order
            
        except ValueError:
            # 风控拒绝，直接抛出不包装
            raise
        except Exception as e:
            logger.error(f"Failed to create order: {e}")
            await self._notify_exchange_failure("create_order", exchange_name, symbol=symbol, exc=e)
            raise
    
    async def _get_account_equity(self, exchange_name: str) -> float:
        """获取账户总权益 (USDT)"""
        try:
            exchange = exchange_manager.get_exchange(exchange_name)
            if not exchange:
                return 10000  # 默认值
            
            balance = exchange.fetch_balance()
            # 找 USDT 总额作为权益估算
            for item in balance:
                if isinstance(item, dict) and item.get('currency') == 'USDT':
                    return item.get('total', 10000)
            return 10000
        except Exception:
            return 10000  # 获取失败时用默认值，不阻塞交易
    
    async def _set_leverage(self, exchange_name: str, symbol: str, 
                            leverage: int) -> bool:
        """设置杠杆"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            return False
        
        try:
            if hasattr(exchange.exchange, 'set_leverage'):
                exchange.exchange.set_leverage(leverage, symbol)
                logger.info(f"Leverage set to {leverage}x for {symbol}")
                return True
        except Exception as e:
            logger.warning(f"Failed to set leverage: {e}")
        
        return False
    
    def _save_order_to_db(self, exchange_name: str, order: Dict):
        """保存订单到数据库"""
        try:
            conn = db.get_connection()
            cursor = conn.cursor()
            
            # 确保 timestamp 不为 None（OKX 市价单可能不返回 timestamp）
            ts = order.get('timestamp')
            if not ts:
                ts = int(datetime.now().timestamp() * 1000)
            
            cursor.execute('''
                INSERT INTO trades_history
                (exchange, symbol, trade_id, timestamp, side, price, quantity, quote_quantity, is_maker)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                exchange_name,
                order.get('symbol') or '',
                order.get('id') or '',
                ts,
                order.get('side') or '',
                order.get('price') or 0,
                order.get('amount', 0),
                order.get('cost', 0),
                0
            ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to save order to DB (order still executed): {e}")
    
    # ============================================
    # 风险检查
    # ============================================
    
    async def check_order_risk(self, exchange_name: str, symbol: str,
                               side: str, amount: float, 
                               price: float = None) -> Dict:
        """
        下单前风险检查
        
        Returns:
            {
                'can_trade': True/False,
                'warnings': [],
                'errors': []
            }
        """
        result = {
            'can_trade': True,
            'warnings': [],
            'errors': []
        }
        
        try:
            exchange = exchange_manager.get_exchange(exchange_name)
            if not exchange:
                result['can_trade'] = False
                result['errors'].append(f"Exchange {exchange_name} not available")
                return result
            
            # 获取当前价格
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker.get('last', 0)
            
            # 计算订单价值
            exec_price = price or current_price
            order_value = exec_price * amount
            
            # 检查1: 最小订单金额
            if order_value < 10:  # 假设最小 $10
                result['errors'].append(f"Order value ${order_value:.2f} is below minimum $10")
                result['can_trade'] = False
            
            # 检查2: 限价单价格偏离
            if price:
                deviation = abs(price - current_price) / current_price
                if deviation > 0.1:  # 偏离超过 10%
                    result['warnings'].append(
                        f"Limit price deviates {deviation*100:.1f}% from current price"
                    )
            
            # 检查3: 账户余额
            try:
                balance = exchange.fetch_balance()
                if side == 'buy':
                    # 买入检查 USDT
                    usdt_free = 0
                    for b in balance:
                        if b.get('currency') == 'USDT':
                            usdt_free = b.get('free', 0)
                            break
                    
                    if usdt_free < order_value:
                        result['warnings'].append(
                            f"Insufficient balance: need ${order_value:.2f}, have ${usdt_free:.2f}"
                        )
            except:
                pass
            
        except Exception as e:
            result['warnings'].append(f"Risk check error: {str(e)}")
        
        return result


# 全局服务实例
trading_service = TradingService()
