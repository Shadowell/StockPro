"""
Telegram 信号推送
=================
Phase 5: 实盘交易信号实时推送到手机

功能:
  1. 交易信号推送 (买入/卖出/平仓)
  2. 风控告警推送 (熔断/止损触发)
  3. 每日定时报告 (日PnL/权益/仓位)
  4. 系统状态通知 (启动/停止/错误)

配置:
  在 .env 文件中添加:
    TELEGRAM_BOT_TOKEN=your_bot_token
    TELEGRAM_CHAT_ID=your_chat_id

  获取方式:
  1. 在 Telegram 中搜索 @BotFather，发送 /newbot 创建机器人
  2. 复制获得的 token
  3. 在 Telegram 中搜索 @userinfobot，获取你的 chat_id
"""
import asyncio
import logging
import os
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# 尝试导入 httpx (如果安装了)
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class TelegramNotifier:
    """Telegram 消息推送器"""

    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        self.enabled = bool(self.bot_token and self.chat_id)
        self._message_queue = []

        if not self.enabled:
            logger.info("Telegram 未配置 (设置 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID 启用)")

    async def send_message(self, text: str, parse_mode: str = 'HTML'):
        """
        发送消息到 Telegram

        Args:
            text: 消息内容 (支持HTML格式)
            parse_mode: 'HTML' 或 'Markdown'
        """
        if not self.enabled:
            # 即使未配置也记录日志
            logger.info(f"[TG-未配置] {text[:100]}...")
            self._message_queue.append({
                'time': datetime.now().isoformat(),
                'text': text,
                'sent': False,
            })
            return False

        if not HAS_HTTPX:
            logger.warning("httpx 未安装, 无法发送 Telegram 消息. pip install httpx")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': parse_mode,
        }

        try:
            proxy = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY')
            async with httpx.AsyncClient(proxy=proxy, timeout=10) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    self._message_queue.append({
                        'time': datetime.now().isoformat(),
                        'text': text[:100],
                        'sent': True,
                    })
                    return True
                else:
                    logger.warning(f"Telegram API 返回 {resp.status_code}: {resp.text}")
                    return False
        except Exception as e:
            logger.warning(f"Telegram 发送失败: {e}")
            return False

    # ============================================
    # 信号通知模板
    # ============================================

    async def notify_trade_signal(self, signal: Dict[str, Any]):
        """推送交易信号"""
        action = signal.get('action', 'unknown')
        emoji_map = {
            'buy': '🟢 买入',
            'sell': '🔴 卖出',
            'close': '⚪ 平仓',
            'hold': '⏸ 持有',
        }
        emoji = emoji_map.get(action, action)

        text = (
            f"<b>📡 交易信号</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"<b>{emoji}</b>\n"
            f"策略: {signal.get('strategy', '-')}\n"
            f"品种: {signal.get('symbol', '-')}\n"
            f"价格: <code>${signal.get('price', 0):,.2f}</code>\n"
            f"仓位: {signal.get('position_pct', 0):.0%}\n"
            f"原因: {signal.get('reason', '-')}\n"
        )

        if signal.get('stop_loss'):
            text += f"止损: <code>${signal['stop_loss']:,.2f}</code>\n"
        if signal.get('take_profit'):
            text += f"止盈: <code>${signal['take_profit']:,.2f}</code>\n"
        if signal.get('regime'):
            text += f"市场: {signal['regime']}\n"

        text += f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        await self.send_message(text)

    async def notify_risk_alert(self, alert_type: str, details: str):
        """推送风控告警"""
        text = (
            f"<b>🚨 风控告警</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"类型: <b>{alert_type}</b>\n"
            f"详情: {details}\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"\n<i>请检查并确认是否需要手动干预</i>"
        )
        await self.send_message(text)

    async def notify_kill_switch(self, report: Dict[str, Any]):
        """推送全局 Kill Switch 告警"""
        failures = report.get('failures') or []
        failure_lines = ""
        if failures:
            failure_lines = "\n失败项:\n" + "\n".join(f"- {item}" for item in failures[:10])

        text = (
            f"<b>🛑 全局熔断触发</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"原因: <b>{report.get('reason', '-')}</b>\n"
            f"峰值权益: <code>{report.get('equity_peak', 0):,.2f} USDT</code>\n"
            f"当前权益: <code>{report.get('current_equity', 0):,.2f} USDT</code>\n"
            f"当前回撤: <code>{report.get('drawdown_pct', 0) * 100:.2f}%</code>\n"
            f"平仓品种数: {report.get('positions_closed', 0)}\n"
            f"停止策略数: {report.get('strategies_paused', 0)}\n"
            f"撤单数量: {report.get('orders_cancelled', 0)}\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            f"{failure_lines}\n\n"
            f"<b>系统已拒绝新的策略开仓，需人工通过 API 解除熔断。</b>"
        )
        await self.send_message(text)

    async def notify_daily_report(self, report: Dict[str, Any]):
        """推送每日报告"""
        text = (
            f"<b>📊 每日报告</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"日期: {report.get('date', datetime.now().strftime('%Y-%m-%d'))}\n"
            f"策略: {report.get('strategy', '-')}\n"
            f"权益: <code>${report.get('equity', 0):,.2f}</code>\n"
            f"日PnL: <code>{report.get('daily_pnl', 0):+.2f}%</code>\n"
            f"总PnL: <code>{report.get('total_pnl', 0):+.2f}%</code>\n"
            f"仓位: {report.get('position', '空仓')}\n"
            f"今日交易: {report.get('trades_today', 0)}笔\n"
            f"风控状态: {report.get('risk_status', '正常')}\n"
        )
        await self.send_message(text)

    async def notify_heartbeat(self, report: Dict[str, Any]):
        """系统心跳播报（早/中/晚）"""
        status = report.get("status", "unknown")
        status_text = "正常" if status == "normal" else ("熔断" if status == "circuit_breaker" else status)
        strategies_running = report.get("strategies_running", 0)
        equity = report.get("equity", 0.0)
        daily_pnl = report.get("daily_pnl", 0.0)

        text = (
            f"<b>💓 系统心跳</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"状态: <b>{status_text}</b>\n"
            f"运行中策略: <b>{strategies_running}</b>\n"
            f"账户总权益: <code>{equity:,.2f} USDT</code>\n"
            f"当日PnL: <code>{daily_pnl:+.2f} USDT</code>\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        if report.get("note"):
            text += f"\n<i>{report['note']}</i>"

        await self.send_message(text)

    async def notify_system(self, event: str, details: str = ''):
        """推送系统通知"""
        text = (
            f"<b>⚙️ 系统通知</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"事件: {event}\n"
        )
        if details:
            text += f"详情: {details}\n"
        text += f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        await self.send_message(text)

    def get_message_history(self, limit: int = 50) -> list:
        """获取消息历史"""
        return self._message_queue[-limit:]


# 全局实例
telegram_notifier = TelegramNotifier()
