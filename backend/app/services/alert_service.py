"""
告警服务
支持价格、资金费率、持仓量等告警
支持 Telegram 通知
"""
import asyncio
import httpx
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
import json
import logging

from app.db.local_db import db_instance as db
from app.exchange import exchange_manager
from app.core.config import settings
from app.services.strategy_engine import strategy_engine

logger = logging.getLogger(__name__)


def _cooldown_from_condition(condition: Dict[str, Any], default: int = 300) -> int:
    try:
        value = int(condition.get('cooldown_sec') or default)
    except (TypeError, ValueError):
        value = default
    return max(0, value)


def _symbol_from_condition(condition: Dict[str, Any], default: str = "BTC/USDT") -> str:
    if condition.get('scope') == 'strategy':
        strategy_id = condition.get('strategy_id')
        return f"strategy:{strategy_id}" if strategy_id is not None else "strategy"
    return condition.get('symbol') or default


def _default_cooldown_for_alert_type(alert_type: str) -> int:
    return 3600 if alert_type in {"strategy_return_below", "strategy_liquidation_risk"} else 300


def _alert_type_value(alert_type: Any) -> str:
    return alert_type.value if isinstance(alert_type, AlertType) else str(alert_type)


def _float_or_none(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _dict_value(record: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record.get(key) not in (None, ""):
            return record.get(key)
    return None


class AlertType(str, Enum):
    """告警类型"""
    PRICE_ABOVE = "price_above"       # 价格高于
    PRICE_BELOW = "price_below"       # 价格低于
    PRICE_CHANGE = "price_change"     # 价格变动%
    FUNDING_ABOVE = "funding_above"   # 费率高于
    FUNDING_BELOW = "funding_below"   # 费率低于
    VOLUME_SPIKE = "volume_spike"     # 成交量异常
    LIQUIDATION = "liquidation"       # 大额爆仓
    STRATEGY_RETURN_BELOW = "strategy_return_below"  # 策略收益率低于阈值
    STRATEGY_LIQUIDATION_RISK = "strategy_liquidation_risk"  # 策略持仓接近强平价


class NotificationType(str, Enum):
    """通知方式"""
    TELEGRAM = "telegram"
    WEBHOOK = "webhook"
    EMAIL = "email"  # 暂不实现


@dataclass
class Alert:
    """告警配置"""
    id: int
    name: str
    type: AlertType
    exchange: str
    symbol: str
    condition: Dict[str, Any]
    notification: Dict[str, Any]
    enabled: bool = True
    last_triggered_at: Optional[datetime] = None
    cooldown: int = 300  # 冷却时间(秒)


@dataclass
class AlertEvent:
    """告警事件"""
    alert_id: int
    alert_name: str
    type: str
    symbol: str
    message: str
    value: float
    timestamp: datetime = field(default_factory=datetime.now)


class TelegramNotifier:
    """Telegram 通知器"""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}"
    
    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """发送消息"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": parse_mode
                    },
                    timeout=10
                )
                
                if response.status_code == 200:
                    logger.info(f"Telegram message sent to {self.chat_id}")
                    return True
                else:
                    logger.error(f"Telegram error: {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    async def send_alert(self, event: AlertEvent) -> bool:
        """发送告警"""
        # 格式化消息
        emoji = "🚨" if "price" in event.type else "📊"
        
        message = f"""
{emoji} <b>BitPro 告警</b>

<b>名称:</b> {event.alert_name}
<b>类型:</b> {event.type}
<b>交易对:</b> {event.symbol}
<b>当前值:</b> {event.value}
<b>时间:</b> {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}

{event.message}
"""
        return await self.send_message(message.strip())


class WebhookNotifier:
    """Webhook 通知器"""
    
    def __init__(self, url: str, headers: Dict[str, str] = None):
        self.url = url
        self.headers = headers or {}
    
    async def send_alert(self, event: AlertEvent) -> bool:
        """发送告警"""
        try:
            if self._is_feishu_webhook():
                payload = {
                    "msg_type": "text",
                    "content": {
                        "text": (
                            f"BitPro 告警\n"
                            f"名称: {event.alert_name}\n"
                            f"类型: {event.type}\n"
                            f"交易对: {event.symbol}\n"
                            f"当前值: {event.value}\n"
                            f"时间: {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"{event.message}"
                        )
                    },
                }
            else:
                payload = {
                    "alert_id": event.alert_id,
                    "alert_name": event.alert_name,
                    "type": event.type,
                    "symbol": event.symbol,
                    "value": event.value,
                    "message": event.message,
                    "timestamp": event.timestamp.isoformat(),
                }
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.url,
                    json=payload,
                    headers=self.headers,
                    timeout=10
                )
                if response.status_code != 200:
                    logger.error("Webhook error status=%s body=%s", response.status_code, response.text[:200])
                    return False
                if self._is_feishu_webhook():
                    try:
                        body = response.json()
                    except Exception:
                        return True
                    return body.get("code", 0) == 0
                return True
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return False

    def _is_feishu_webhook(self) -> bool:
        return "open.feishu.cn/open-apis/bot" in (self.url or "")


class AlertService:
    """告警服务"""
    
    def __init__(self):
        self._alerts: Dict[int, Alert] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._telegram: Optional[TelegramNotifier] = None
        self._last_prices: Dict[str, float] = {}
    
    def init_telegram(self, bot_token: str, chat_id: str):
        """初始化 Telegram"""
        self._telegram = TelegramNotifier(bot_token, chat_id)
        logger.info("Telegram notifier initialized")
    
    async def start(self):
        """启动告警服务"""
        if self._running:
            return
        
        self._running = True
        
        # 加载告警配置
        await self._load_alerts()
        
        # 启动监控任务
        self._task = asyncio.create_task(self._monitor_loop())
        
        logger.info("Alert service started")
    
    async def stop(self):
        """停止告警服务"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Alert service stopped")
    
    async def _load_alerts(self):
        """从数据库加载告警配置"""
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, name, type, symbol, condition, notification, enabled, last_triggered_at
            FROM alerts
            WHERE enabled = 1
        ''')
        
        for row in cursor.fetchall():
            try:
                condition = json.loads(row['condition']) if row['condition'] else {}
                notification = json.loads(row['notification']) if row['notification'] else {}
                
                last_triggered_at = None
                raw_last_triggered_at = row['last_triggered_at']
                if raw_last_triggered_at:
                    try:
                        last_triggered_at = datetime.fromisoformat(str(raw_last_triggered_at))
                    except Exception:
                        last_triggered_at = None

                alert = Alert(
                    id=row['id'],
                    name=row['name'],
                    type=AlertType(row['type']),
                    exchange=condition.get('exchange', 'okx'),
                    symbol=_symbol_from_condition(condition),
                    condition=condition,
                    notification=notification,
                    enabled=bool(row['enabled']),
                    last_triggered_at=last_triggered_at,
                    cooldown=_cooldown_from_condition(
                        condition,
                        _default_cooldown_for_alert_type(str(row['type'])),
                    ),
                )
                self._alerts[alert.id] = alert
                
            except Exception as e:
                logger.warning(f"Failed to load alert {row['id']}: {e}")
        
        conn.close()
        logger.info(f"Loaded {len(self._alerts)} alerts")
    
    async def create_alert(self, name: str, alert_type: str, condition: Dict,
                          notification: Dict = None) -> int:
        """创建告警"""
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO alerts (name, type, symbol, condition, notification, enabled)
            VALUES (?, ?, ?, ?, ?, 1)
        ''', (
            name,
            alert_type,
            condition.get('symbol'),
            json.dumps(condition),
            json.dumps(notification or {})
        ))
        
        alert_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # 添加到内存
        alert = Alert(
            id=alert_id,
            name=name,
            type=AlertType(alert_type),
            exchange=condition.get('exchange', 'okx'),
            symbol=_symbol_from_condition(condition),
            condition=condition,
            notification=notification or {},
            cooldown=_cooldown_from_condition(
                condition,
                _default_cooldown_for_alert_type(str(alert_type)),
            ),
        )
        self._alerts[alert_id] = alert
        
        logger.info(f"Alert created: {name} ({alert_type})")
        return alert_id
    
    async def delete_alert(self, alert_id: int) -> bool:
        """删除告警"""
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM alerts WHERE id = ?', (alert_id,))
        conn.commit()
        conn.close()
        
        self._alerts.pop(alert_id, None)
        return True
    
    async def toggle_alert(self, alert_id: int, enabled: bool) -> bool:
        """启用/禁用告警"""
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE alerts SET enabled = ? WHERE id = ?', (int(enabled), alert_id))
        conn.commit()
        conn.close()
        
        if alert_id in self._alerts:
            self._alerts[alert_id].enabled = enabled
        
        return True
    
    def get_alerts(self) -> List[Dict]:
        """获取所有告警"""
        return [
            {
                'id': a.id,
                'name': a.name,
                'type': a.type.value,
                'exchange': a.exchange,
                'symbol': a.symbol,
                'condition': a.condition,
                'enabled': a.enabled,
                'last_triggered_at': a.last_triggered_at.isoformat() if a.last_triggered_at else None,
            }
            for a in self._alerts.values()
        ]
    
    async def _monitor_loop(self):
        """监控循环"""
        while self._running:
            try:
                for alert in list(self._alerts.values()):
                    if not alert.enabled:
                        continue
                    
                    # 检查冷却
                    if self._cooldown_active(alert):
                        continue
                    
                    # 检查告警条件
                    event = await self._check_alert(alert)
                    
                    if event:
                        await self._trigger_alert(alert, event)
                
                await asyncio.sleep(10)  # 10秒检查一次
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Alert monitor error: {e}")
                await asyncio.sleep(30)
    
    async def _check_alert(self, alert: Alert) -> Optional[AlertEvent]:
        """检查告警条件"""
        try:
            if alert.type == AlertType.STRATEGY_RETURN_BELOW:
                return await self._check_strategy_return_below_alert(alert)
            if alert.type == AlertType.STRATEGY_LIQUIDATION_RISK:
                return await self._check_strategy_liquidation_risk_alert(alert)

            exchange = exchange_manager.get_exchange(alert.exchange)
            if not exchange:
                return None
            
            if alert.type in [AlertType.PRICE_ABOVE, AlertType.PRICE_BELOW, AlertType.PRICE_CHANGE]:
                return await self._check_price_alert(alert, exchange)
            
            elif alert.type in [AlertType.FUNDING_ABOVE, AlertType.FUNDING_BELOW]:
                return await self._check_funding_alert(alert, exchange)
            
            elif alert.type == AlertType.VOLUME_SPIKE:
                return await self._check_volume_alert(alert, exchange)
            
        except Exception as e:
            logger.warning(f"Alert check failed for {alert.name}: {e}")
        
        return None

    def _cooldown_active(self, alert: Alert, now: Optional[datetime] = None) -> bool:
        """Return True when the alert is still inside its cooldown window."""
        if not alert.last_triggered_at:
            return False
        current = now or datetime.now()
        elapsed = (current - alert.last_triggered_at).total_seconds()
        return elapsed < alert.cooldown

    async def _check_strategy_return_below_alert(self, alert: Alert) -> Optional[AlertEvent]:
        """检查单策略当前运行收益率是否低于阈值。"""
        strategy_id = alert.condition.get('strategy_id')
        try:
            strategy_id_int = int(strategy_id)
        except (TypeError, ValueError):
            return None

        status = strategy_engine.get_strategy_status(strategy_id_int)
        if not status or str(status.get('status') or '').lower() != 'running':
            return None

        try:
            current_return = float(status.get('return_pct'))
        except (TypeError, ValueError):
            return None

        threshold = float(alert.condition.get('threshold', -5))
        if current_return > threshold:
            return None

        name = str(status.get('name') or alert.condition.get('strategy_name') or f'策略 #{strategy_id_int}')
        equity = float(status.get('equity') or 0)
        pnl = float(status.get('pnl') or 0)
        total_trades = int(status.get('total_trades') or 0)
        return AlertEvent(
            alert_id=alert.id,
            alert_name=alert.name,
            type=alert.type.value,
            symbol=f"strategy:{strategy_id_int}",
            value=current_return,
            message=(
                f"策略 {name} (ID: {strategy_id_int}) 当前收益率 {current_return:+.2f}% "
                f"低于阈值 {threshold:+.2f}%\n"
                f"当前权益: {equity:,.2f} USDT\n"
                f"总收益: {pnl:+,.2f} USDT\n"
                f"成交数: {total_trades}"
            ),
        )

    async def _check_strategy_liquidation_risk_alert(self, alert: Alert) -> Optional[AlertEvent]:
        """检查单策略合约持仓是否接近强平价。"""
        strategy_id = alert.condition.get('strategy_id')
        try:
            strategy_id_int = int(strategy_id)
        except (TypeError, ValueError):
            return None

        status = strategy_engine.get_strategy_status(strategy_id_int)
        if not status or str(status.get('status') or '').lower() != 'running':
            return None

        raw_positions = status.get('positions') or {}
        if isinstance(raw_positions, dict):
            positions = [
                (str(key), value)
                for key, value in raw_positions.items()
                if isinstance(value, dict)
            ]
        elif isinstance(raw_positions, list):
            positions = [
                (str(item.get('symbol') or idx), item)
                for idx, item in enumerate(raw_positions)
                if isinstance(item, dict)
            ]
        else:
            return None

        threshold = abs(float(alert.condition.get('threshold', 10)))
        nearest: Optional[Dict[str, Any]] = None
        for key, pos in positions:
            current_price = _float_or_none(
                _dict_value(pos, 'mark_price', 'markPrice', 'current_price', 'currentPrice', 'price')
            )
            liq_price = _float_or_none(
                _dict_value(pos, 'liq_price', 'liqPrice', 'liquidation_price', 'liquidationPrice')
            )
            if not current_price or current_price <= 0 or not liq_price or liq_price <= 0:
                continue

            side = str(_dict_value(pos, 'pos_side', 'posSide', 'side') or '').strip().lower()
            if 'short' in side:
                distance_pct = (liq_price - current_price) / current_price * 100
            elif 'long' in side:
                distance_pct = (current_price - liq_price) / current_price * 100
            else:
                distance_pct = abs(current_price - liq_price) / current_price * 100

            display_buffer_pct = max(distance_pct, 0.0)
            if distance_pct > threshold:
                continue
            if nearest is None or display_buffer_pct < nearest['buffer_pct']:
                nearest = {
                    'key': key,
                    'symbol': str(pos.get('symbol') or key),
                    'side': side or 'unknown',
                    'current_price': current_price,
                    'liq_price': liq_price,
                    'buffer_pct': display_buffer_pct,
                    'contracts': _float_or_none(_dict_value(pos, 'contracts', 'size')),
                    'leverage': _float_or_none(_dict_value(pos, 'leverage')),
                    'unrealized_pnl': _float_or_none(_dict_value(pos, 'unrealized_pnl', 'unrealizedPnl')),
                }

        if nearest is None:
            return None

        name = str(status.get('name') or alert.condition.get('strategy_name') or f'策略 #{strategy_id_int}')
        contracts = nearest.get('contracts')
        leverage = nearest.get('leverage')
        unrealized_pnl = nearest.get('unrealized_pnl')
        details = [
            f"策略 {name} (ID: {strategy_id_int}) 爆仓距离 {nearest['buffer_pct']:.2f}% 低于阈值 {threshold:.2f}%",
            f"持仓: {nearest['symbol']} {nearest['side']}",
            f"当前价: {nearest['current_price']:.2f} USDT",
            f"强平价: {nearest['liq_price']:.2f} USDT",
        ]
        if contracts is not None:
            details.append(f"张数/数量: {contracts:g}")
        if leverage is not None:
            details.append(f"杠杆: {leverage:g}x")
        if unrealized_pnl is not None:
            details.append(f"未实现盈亏: {unrealized_pnl:+,.2f} USDT")

        return AlertEvent(
            alert_id=alert.id,
            alert_name=alert.name,
            type=_alert_type_value(alert.type),
            symbol=f"strategy:{strategy_id_int}",
            value=round(float(nearest['buffer_pct']), 6),
            message="\n".join(details),
        )
    
    async def _check_price_alert(self, alert: Alert, exchange) -> Optional[AlertEvent]:
        """检查价格告警"""
        ticker = exchange.fetch_ticker(alert.symbol)
        current_price = ticker.get('last', 0)
        
        threshold = alert.condition.get('threshold', 0)
        
        if alert.type == AlertType.PRICE_ABOVE and current_price >= threshold:
            return AlertEvent(
                alert_id=alert.id,
                alert_name=alert.name,
                type=alert.type.value,
                symbol=alert.symbol,
                value=current_price,
                message=f"{alert.symbol} 价格突破 ${threshold}，当前 ${current_price:.2f}"
            )
        
        elif alert.type == AlertType.PRICE_BELOW and current_price <= threshold:
            return AlertEvent(
                alert_id=alert.id,
                alert_name=alert.name,
                type=alert.type.value,
                symbol=alert.symbol,
                value=current_price,
                message=f"{alert.symbol} 价格跌破 ${threshold}，当前 ${current_price:.2f}"
            )
        
        elif alert.type == AlertType.PRICE_CHANGE:
            key = f"{alert.exchange}:{alert.symbol}"
            last_price = self._last_prices.get(key)
            self._last_prices[key] = current_price
            
            if last_price:
                change = (current_price - last_price) / last_price * 100
                if abs(change) >= threshold:
                    direction = "上涨" if change > 0 else "下跌"
                    return AlertEvent(
                        alert_id=alert.id,
                        alert_name=alert.name,
                        type=alert.type.value,
                        symbol=alert.symbol,
                        value=change,
                        message=f"{alert.symbol} 价格快速{direction} {abs(change):.2f}%"
                    )
        
        return None
    
    async def _check_funding_alert(self, alert: Alert, exchange) -> Optional[AlertEvent]:
        """检查资金费率告警"""
        rate_data = exchange.fetch_funding_rate(alert.symbol)
        if not rate_data:
            return None
        
        current_rate = rate_data.get('current_rate', 0) or 0
        threshold = alert.condition.get('threshold', 0)
        
        if alert.type == AlertType.FUNDING_ABOVE and current_rate >= threshold:
            return AlertEvent(
                alert_id=alert.id,
                alert_name=alert.name,
                type=alert.type.value,
                symbol=alert.symbol,
                value=current_rate,
                message=f"{alert.symbol} 资金费率达到 {current_rate:.4%}，套利机会!"
            )
        
        elif alert.type == AlertType.FUNDING_BELOW and current_rate <= threshold:
            return AlertEvent(
                alert_id=alert.id,
                alert_name=alert.name,
                type=alert.type.value,
                symbol=alert.symbol,
                value=current_rate,
                message=f"{alert.symbol} 资金费率为 {current_rate:.4%}，低于阈值"
            )
        
        return None
    
    async def _check_volume_alert(self, alert: Alert, exchange) -> Optional[AlertEvent]:
        """检查成交量告警"""
        ticker = exchange.fetch_ticker(alert.symbol)
        volume = ticker.get('quoteVolume', 0) or ticker.get('baseVolume', 0) or 0
        
        threshold = alert.condition.get('threshold', 0)  # 24h成交额阈值
        
        if volume >= threshold:
            return AlertEvent(
                alert_id=alert.id,
                alert_name=alert.name,
                type=alert.type.value,
                symbol=alert.symbol,
                value=volume,
                message=f"{alert.symbol} 24h成交额达到 ${volume/1e6:.1f}M"
            )
        
        return None
    
    async def _trigger_alert(self, alert: Alert, event: AlertEvent):
        """触发告警"""
        logger.info(f"Alert triggered: {event.alert_name} - {event.message}")
        
        # 更新触发时间
        alert.last_triggered_at = datetime.now()
        
        # 发送通知
        notification = alert.notification
        
        if notification.get('telegram'):
            if self._telegram:
                await self._telegram.send_alert(event)
            else:
                # 使用配置的 Telegram
                tg_config = notification['telegram']
                if tg_config.get('bot_token') and tg_config.get('chat_id'):
                    notifier = TelegramNotifier(
                        tg_config['bot_token'],
                        tg_config['chat_id']
                    )
                    await notifier.send_alert(event)
        
        unified_feishu_configured = False
        feishu_alert_push_allowed = False
        try:
            from app.services.feishu_notifier import feishu_notifier

            unified_feishu_configured = feishu_notifier.has_webhook()
            feishu_alert_push_allowed = feishu_notifier.is_push_kind_enabled("monitor_alert")
            if unified_feishu_configured and feishu_alert_push_allowed:
                await feishu_notifier.send_message(
                    title=f"BitPro 告警 | {event.alert_name}",
                    content=(
                        f"**告警类型**: {event.type}\n"
                        f"**对象**: {event.symbol}\n"
                        f"**当前值**: {event.value}\n"
                        f"---\n"
                        f"{event.message}"
                    ),
                    color="red",
                    require_enabled=False,
                )
            elif unified_feishu_configured:
                logger.debug("跳过飞书告警推送: 当前仅启用收益卡片推送")
        except Exception as exc:
            logger.warning("统一飞书告警推送失败: %s", exc)

        if notification.get('webhook'):
            webhook_url = notification['webhook'].get('url')
            if "open-apis/bot" in str(webhook_url or "") and (
                unified_feishu_configured or not feishu_alert_push_allowed
            ):
                webhook_url = None
        else:
            webhook_url = None

        if webhook_url:
            webhook = WebhookNotifier(
                webhook_url,
                notification['webhook'].get('headers')
            )
            await webhook.send_alert(event)
        
        # 更新数据库
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE alerts SET last_triggered_at = ? WHERE id = ?',
            (datetime.now().isoformat(), alert.id)
        )
        conn.commit()
        conn.close()


# 全局实例
alert_service = AlertService()
