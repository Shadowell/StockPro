"""
飞书自定义机器人 Webhook 推送
==============================
支持富文本消息卡片（Interactive Card），标题颜色可选:
  - blue (默认)
  - red  (风控警报)
  - green (盈利/成功)
  - orange (警告)

配置 (.env):
  FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
  ENABLE_FEISHU_NOTIFY=True
"""
import logging
import math
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None
    _HAS_PIL = False


FEISHU_TENANT_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_IMAGE_UPLOAD_URL = "https://open.feishu.cn/open-apis/im/v1/images"


class FeishuNotifier:
    """飞书 Webhook 异步单例推送器"""

    ENABLED_PUSH_KINDS = {"strategy_profit_report", "paper_liquidation_alert"}
    MAX_HISTORY = 200

    def __init__(self):
        from app.core.config import settings
        self.webhook_url: str = getattr(settings, "FEISHU_WEBHOOK_URL", "") or ""
        self.enabled: bool = getattr(settings, "ENABLE_FEISHU_NOTIFY", False)
        self._history: List[Dict[str, Any]] = []
        self._last_profit_report_delivery: Dict[str, Any] = {}

        if not self.webhook_url:
            logger.info("飞书 Webhook 未配置 (设置 FEISHU_WEBHOOK_URL 启用)")

    def _configured_webhook_url(self) -> str:
        from app.core.config import settings

        try:
            from app.db.local_db import db_instance

            saved = str(db_instance.get_feishu_webhook_url() or "").strip()
            if saved:
                return saved
        except Exception as exc:
            logger.debug("读取统一飞书 Webhook 设置失败: %s", exc)

        explicit = str(getattr(settings, "FEISHU_WEBHOOK_URL", "") or self.webhook_url or "").strip()
        if explicit:
            return explicit

        try:
            from app.db.local_db import db_instance

            return str(db_instance.get_latest_feishu_webhook_url() or "").strip()
        except Exception as exc:
            logger.debug("读取旧告警飞书 Webhook 失败: %s", exc)
            return ""

    def _configured_feishu_app_credentials(self) -> Tuple[str, str]:
        from app.core.config import settings

        app_id = str(getattr(settings, "FEISHU_APP_ID", "") or "").strip()
        app_secret = str(getattr(settings, "FEISHU_APP_SECRET", "") or "").strip()
        if not app_id or not app_secret:
            return "", ""
        return app_id, app_secret

    def _profit_report_image_enabled(self) -> bool:
        from app.core.config import settings

        return bool(getattr(settings, "FEISHU_PROFIT_CARD_IMAGE_ENABLED", True))

    def _can_send_profit_report_image(self) -> bool:
        app_id, app_secret = self._configured_feishu_app_credentials()
        return bool(
            self._profit_report_image_enabled()
            and _HAS_HTTPX
            and _HAS_PIL
            and self._profit_image_font_available()
            and app_id
            and app_secret
        )

    def _profit_report_image_unavailable_reason(self) -> Optional[str]:
        if not self._profit_report_image_enabled():
            return "image_disabled"
        if not _HAS_HTTPX:
            return "httpx_missing"
        if not _HAS_PIL:
            return "pillow_missing"
        if not self._profit_image_font_available():
            return "cjk_font_missing"
        app_id, app_secret = self._configured_feishu_app_credentials()
        if not app_id or not app_secret:
            return "feishu_app_credentials_missing"
        return None

    def get_profit_report_image_status(self) -> Dict[str, Any]:
        """Return non-secret readiness diagnostics for profit-card image delivery."""
        app_id, app_secret = self._configured_feishu_app_credentials()
        reason = self._profit_report_image_unavailable_reason()
        return {
            "enabled": bool(self._profit_report_image_enabled()),
            "ready": reason is None,
            "app_configured": bool(app_id and app_secret),
            "httpx_available": bool(_HAS_HTTPX),
            "pillow_available": bool(_HAS_PIL),
            "cjk_font_available": self._profit_image_font_available(),
            "reason": reason,
        }

    def get_last_profit_report_delivery(self) -> Dict[str, Any]:
        """Return the last profit-card delivery mode without exposing payload secrets."""
        return dict(self._last_profit_report_delivery)

    def has_webhook(self) -> bool:
        """Return whether any usable Feishu webhook is configured or saved."""
        return bool(self._configured_webhook_url())

    def get_webhook_url(self) -> str:
        """Return the effective Feishu webhook without exposing it through API responses."""
        return self._configured_webhook_url()

    def _is_ready(self, *, require_enabled: bool = True) -> bool:
        return bool(self._configured_webhook_url() and _HAS_HTTPX)

    def is_ready(self, *, require_enabled: bool = True) -> bool:
        """Return whether a real Feishu send can currently be attempted."""
        return self._is_ready(require_enabled=require_enabled)

    def is_push_kind_enabled(self, kind: str) -> bool:
        """Return whether the product currently allows this Feishu push kind."""
        return str(kind or "").strip() in self.ENABLED_PUSH_KINDS

    def _record_skipped(self, title: str, content: str = "", *, reason: str) -> None:
        self._append_history(
            {
                "time": datetime.now().isoformat(),
                "title": title,
                "content": str(content or "")[:120],
                "sent": False,
                "skipped": reason,
            }
        )

    def _append_history(self, record: Dict[str, Any]) -> None:
        self._history.append(record)
        if len(self._history) > self.MAX_HISTORY:
            del self._history[: len(self._history) - self.MAX_HISTORY]

    def _skip_disabled_push_kind(self, kind: str, title: str, content: str = "") -> bool:
        if self.is_push_kind_enabled(kind):
            return False
        logger.debug("跳过未启用的飞书推送类型: kind=%s title=%s", kind, title)
        self._record_skipped(title, content, reason=f"push_kind_disabled:{kind}")
        return True

    # ------------------------------------------------------------------
    # 核心发送
    # ------------------------------------------------------------------

    async def send_message(
        self,
        title: str,
        content: str,
        msg_type: str = "card",
        color: str = "blue",
        require_enabled: bool = True,
    ) -> bool:
        """
        发送飞书消息。

        Args:
            title:    卡片标题
            content:  正文（支持换行 \\n）
            msg_type: "card" (默认富文本卡片) 或 "text" (纯文本)
            color:    卡片标题颜色  blue / red / green / orange
        """
        record = {
            "time": datetime.now().isoformat(),
            "title": title,
            "content": content[:120],
            "sent": False,
        }

        if not self._is_ready(require_enabled=require_enabled):
            logger.info("[飞书-未启用] %s | %s", title, content[:80])
            self._append_history(record)
            return False

        payload = (
            {"msg_type": "text", "content": {"text": f"{title}\n{content}"}}
            if msg_type == "text"
            else self._build_card(title, content, color)
        )
        return await self._send_payload(payload, record, require_enabled=require_enabled)

    async def _send_payload(
        self,
        payload: Dict[str, Any],
        record: Dict[str, Any],
        *,
        require_enabled: bool = True,
    ) -> bool:
        """Send a prebuilt Feishu webhook payload."""
        if not self._is_ready(require_enabled=require_enabled):
            logger.info("[飞书-未启用] %s | %s", record.get("title"), record.get("content", "")[:80])
            self._append_history(record)
            return False

        try:
            webhook_url = self._configured_webhook_url()
            async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                resp = await client.post(webhook_url, json=payload)
                ok = resp.status_code == 200
                if ok:
                    body = resp.json()
                    if body.get("code", 0) != 0:
                        logger.warning("飞书 API 业务错误: %s", body)
                        ok = False
                record["sent"] = ok
                self._append_history(record)
                if not ok:
                    logger.warning("飞书推送失败 status=%s body=%s", resp.status_code, resp.text[:200])
                return ok
        except Exception as e:
            logger.warning("飞书推送异常: %s", e)
            self._append_history(record)
            return False

    @staticmethod
    def _build_card(title: str, content: str, color: str = "blue") -> dict:
        """构建飞书交互卡片 payload"""
        color_map = {
            "blue": "blue",
            "red": "red",
            "green": "green",
            "orange": "orange",
        }
        header_color = color_map.get(color, "blue")

        lines = content.strip().split("\n")
        elements = []
        for line in lines:
            if line.startswith("---"):
                elements.append({"tag": "hr"})
            else:
                elements.append({
                    "tag": "markdown",
                    "content": line,
                })

        elements.append({"tag": "hr"})
        elements.append({
            "tag": "note",
            "elements": [
                {"tag": "plain_text", "content": f"BitPro · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
            ],
        })

        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": header_color,
                },
                "elements": elements,
            },
        }

    # ------------------------------------------------------------------
    # 场景化通知模板
    # ------------------------------------------------------------------

    @staticmethod
    def _suppress_trade_notification(strategy: str) -> bool:
        """Return whether a trade fill is too noisy to push as an individual card."""
        return str(strategy or "").strip().lower().startswith("paper#")

    @staticmethod
    def _suppress_strategy_status_notification(status: str) -> bool:
        """Return whether a strategy lifecycle status is too noisy to push."""
        return str(status or "").strip().lower() == "running"

    async def notify_trade(
        self, strategy: str, symbol: str, side: str,
        price: float, amount: float, cost: float, fee: float, pnl: float = 0,
    ) -> bool:
        """订单成交通知"""
        if self._skip_disabled_push_kind("trade", "交易成交", f"{strategy} {symbol} {side}"):
            return False

        if self._suppress_trade_notification(strategy):
            logger.debug("跳过模拟盘成交通知: strategy=%s symbol=%s side=%s", strategy, symbol, side)
            return False

        emoji = "🟢 买入" if side.upper() == "BUY" else "🔴 卖出"
        pnl_text = f"**盈亏**: {pnl:+.2f} USDT" if side.upper() == "SELL" else ""
        return await self.send_message(
            title=f"📡 交易成交 | {emoji}",
            content=(
                f"**策略**: {strategy}\n"
                f"**币种**: {symbol}\n"
                f"**价格**: {price:,.2f} USDT\n"
                f"**数量**: {amount:.6f}\n"
                f"**成交额**: {cost:,.2f} USDT\n"
                f"**手续费**: {fee:.4f} USDT\n"
                f"{pnl_text}"
            ),
            color="green" if (side.upper() == "BUY" or pnl >= 0) else "red",
        )

    async def notify_strategy_status(self, strategy_id: int, name: str, status: str) -> bool:
        """策略启停通知"""
        if self._skip_disabled_push_kind("strategy_status", "策略状态", f"{name} {status}"):
            return False

        if self._suppress_strategy_status_notification(status):
            logger.debug("跳过策略启动状态通知: strategy_id=%s name=%s", strategy_id, name)
            return False

        emoji = "▶️" if status == "running" else "⏹️"
        color = "green" if status == "running" else "orange"
        return await self.send_message(
            title=f"{emoji} 策略{('启动' if status == 'running' else '停止')}",
            content=f"**策略**: {name} (ID: {strategy_id})\n**状态**: {status}",
            color=color,
        )

    async def notify_risk_alert(self, alert_type: str, details: str) -> bool:
        """风控/熔断告警"""
        if self._skip_disabled_push_kind("risk_alert", f"风控告警 | {alert_type}", details):
            return False

        return await self.send_message(
            title=f"🚨 风控告警 | {alert_type}",
            content=details,
            color="red",
        )

    async def notify_paper_liquidation(self, report: Dict[str, Any]) -> bool:
        """合约模拟盘强平告警。"""
        if self._skip_disabled_push_kind("paper_liquidation_alert", "合约模拟盘爆仓", str(report)):
            return False

        symbol = str(report.get("symbol") or "-")
        side = str(report.get("pos_side") or report.get("side") or "-")
        return await self.send_message(
            title="合约模拟盘爆仓",
            content=(
                f"**策略**: {report.get('strategy_name', '-')} (ID: {report.get('strategy_id', '-')})\n"
                f"**持仓**: {symbol} {side}\n"
                f"**标记价**: {float(report.get('price') or 0):,.6g} USDT\n"
                f"**强平价**: {float(report.get('liquidation_price') or 0):,.6g} USDT\n"
                f"**张数**: {float(report.get('contracts') or 0):g}\n"
                f"**杠杆**: {float(report.get('leverage') or 0):g}x\n"
                f"**强平盈亏**: {float(report.get('realized_pnl') or 0):+,.2f} USDT\n"
                f"**触发前权益**: {float(report.get('account_equity_before') or 0):,.2f} USDT\n"
                f"**维持保证金**: {float(report.get('maintenance_margin') or 0):,.2f} USDT\n"
                f"---\n"
                f"**策略已自动暂停，请复核仓位、杠杆和资金占用后再决定是否继续。**"
            ),
            color="red",
        )

    async def notify_kill_switch(self, report: Dict[str, Any]) -> bool:
        """全局 Kill Switch 熔断"""
        if self._skip_disabled_push_kind("kill_switch", "全局熔断触发", str(report)):
            return False

        failures = report.get("failures") or []
        fail_text = "\n".join(f"- {f}" for f in failures[:10]) if failures else "无"
        return await self.send_message(
            title="🛑 全局熔断触发",
            content=(
                f"**原因**: {report.get('reason', '-')}\n"
                f"**峰值权益**: {report.get('equity_peak', 0):,.2f} USDT\n"
                f"**当前权益**: {report.get('current_equity', 0):,.2f} USDT\n"
                f"**回撤**: {report.get('drawdown_pct', 0) * 100:.2f}%\n"
                f"**平仓品种**: {report.get('positions_closed', 0)}\n"
                f"**停止策略**: {report.get('strategies_paused', 0)}\n"
                f"**撤单数量**: {report.get('orders_cancelled', 0)}\n"
                f"---\n"
                f"**失败项**: {fail_text}\n"
                f"**⚠️ 系统已拒绝新的策略开仓，需人工解除熔断。**"
            ),
            color="red",
        )

    async def notify_heartbeat(self, report: Dict[str, Any]) -> bool:
        """系统心跳"""
        if self._skip_disabled_push_kind("heartbeat", "系统心跳", str(report)):
            return False

        status = report.get("status", "unknown")
        status_text = "正常" if status == "normal" else ("熔断" if status == "circuit_breaker" else status)
        return await self.send_message(
            title="💓 系统心跳",
            content=(
                f"**状态**: {status_text}\n"
                f"**运行中策略**: {report.get('strategies_running', 0)}\n"
                f"**权益**: {report.get('equity', 0):,.2f} USDT\n"
                f"**当日 PnL**: {report.get('daily_pnl', 0):+.2f} USDT"
            ),
            color="green" if status == "normal" else "red",
        )

    async def notify_strategy_profit_report(self, report: Dict[str, Any]) -> bool:
        """运行中策略收益卡片。"""
        if self._skip_disabled_push_kind("strategy_profit_report", "运行策略收益卡片", str(report)[:120]):
            return False

        strategies = list(report.get("strategies") or [])
        title = str(report.get("title") or "模拟收益卡片")
        total_pnl = float(report.get("total_pnl") or 0)
        image_status = self.get_profit_report_image_status()
        self._last_profit_report_delivery = {
            "type": "pending",
            "image_ready": image_status["ready"],
            "image_reason": image_status["reason"],
            "sent": False,
        }
        if self._can_send_profit_report_image():
            record = {
                "time": datetime.now().isoformat(),
                "title": f"{title}长图",
                "content": f"running={int(report.get('running_count') or len(strategies))} pnl={total_pnl:+.2f}",
                "sent": False,
            }
            try:
                image_bytes = self._build_strategy_profit_report_png(report)
                image_key = await self._upload_image_to_feishu(image_bytes)
                if image_key:
                    sent = await self._send_payload(
                        {"msg_type": "image", "content": {"image_key": image_key}},
                        record,
                        require_enabled=False,
                    )
                    self._last_profit_report_delivery = {
                        "type": "image",
                        "image_ready": True,
                        "image_reason": None,
                        "sent": bool(sent),
                        "error": None if sent else "webhook_send_failed",
                    }
                    return sent
            except Exception as exc:
                logger.warning("飞书收益长图发送失败，回退交互卡片: %s", exc)
                image_status = {
                    **image_status,
                    "ready": False,
                    "reason": "image_upload_failed",
                    "error": str(exc),
                }

        payload = self._build_strategy_profit_report_card(report)
        record = {
            "time": datetime.now().isoformat(),
            "title": title,
            "content": f"running={int(report.get('running_count') or len(strategies))} pnl={total_pnl:+.2f}",
            "sent": False,
        }
        sent = await self._send_payload(
            payload,
            record,
            require_enabled=False,
        )
        self._last_profit_report_delivery = {
            "type": "card",
            "image_ready": bool(image_status.get("ready")),
            "image_reason": image_status.get("reason"),
            "sent": bool(sent),
            "error": image_status.get("error"),
        }
        return sent

    async def _upload_image_to_feishu(self, image_bytes: bytes) -> str:
        """Upload a PNG to Feishu IM and return image_key for webhook image messages."""
        app_id, app_secret = self._configured_feishu_app_credentials()
        if not app_id or not app_secret:
            raise RuntimeError("飞书 App ID/Secret 未配置，无法上传收益长图")
        if not _HAS_HTTPX:
            raise RuntimeError("httpx 未安装，无法上传飞书图片")

        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            token_resp = await client.post(
                FEISHU_TENANT_TOKEN_URL,
                json={"app_id": app_id, "app_secret": app_secret},
            )
            token_body = token_resp.json()
            if token_resp.status_code != 200 or token_body.get("code", 0) != 0:
                raise RuntimeError(
                    f"飞书 tenant token 获取失败: status={token_resp.status_code} "
                    f"code={token_body.get('code')} msg={token_body.get('msg') or token_body.get('message')}"
                )
            token = str(token_body.get("tenant_access_token") or "").strip()
            if not token:
                raise RuntimeError("飞书 tenant token 响应缺少 tenant_access_token")

            upload_resp = await client.post(
                FEISHU_IMAGE_UPLOAD_URL,
                headers={"Authorization": f"Bearer {token}"},
                data={"image_type": "message"},
                files={"image": ("bitpro-strategy-profit.png", image_bytes, "image/png")},
            )
            upload_body = upload_resp.json()
            if upload_resp.status_code != 200 or upload_body.get("code", 0) != 0:
                raise RuntimeError(
                    f"飞书图片上传失败: status={upload_resp.status_code} "
                    f"code={upload_body.get('code')} msg={upload_body.get('msg') or upload_body.get('message')}"
                )
            image_key = str((upload_body.get("data") or {}).get("image_key") or "").strip()
            if not image_key:
                raise RuntimeError("飞书图片上传响应缺少 image_key")
            return image_key

    @classmethod
    def _build_strategy_profit_report_card(cls, report: Dict[str, Any]) -> Dict[str, Any]:
        strategies = list(report.get("strategies") or [])
        title = str(report.get("title") or "模拟收益卡片")
        scope = str(report.get("report_scope") or "paper").lower()
        pnl_label = cls._clean_text(
            report.get("pnl_label") or ("策略归因盈亏" if scope == "live" else "总收益")
        )
        footer = cls._clean_text(
            report.get("footer")
            or (
                "数据来自 OKX 实盘账户 + BitPro 运行中实盘订阅"
                if scope == "live"
                else "数据来自 BitPro 当前运行中策略快照"
            )
        )
        total_pnl = cls._as_float(report.get("total_pnl"))
        total_return_pct = cls._as_float(report.get("total_return_pct"))
        total_equity = cls._as_float(report.get("total_equity"))
        total_unrealized = cls._as_float(report.get("total_unrealized_pnl"))
        running_count = int(report.get("running_count") or len(strategies))
        header_color = "red" if total_pnl > 0 else ("green" if total_pnl < 0 else "blue")
        elements: List[Dict[str, Any]] = [
            {
                "tag": "column_set",
                "flex_mode": "none",
                "columns": [
                    cls._markdown_column(
                        f"**运行中策略**\n{running_count} 个",
                        weight=1,
                    ),
                    cls._markdown_column(
                        f"**账户总额**\n{cls._money(total_equity)}",
                        weight=1,
                    ),
                    cls._markdown_column(
                        f"**{pnl_label}**\n{cls._financial_usd_text(total_pnl)} ({cls._financial_text(total_return_pct, suffix='%')})",
                        weight=1,
                    ),
                    cls._markdown_column(
                        f"**浮动盈亏**\n{cls._financial_usd_text(total_unrealized)}",
                        weight=1,
                    ),
                ],
            },
            {"tag": "hr"},
        ]

        for index, item in enumerate(strategies):
            if index > 0:
                elements.append({"tag": "hr"})
            elements.extend(cls._build_strategy_profit_elements(item))

        elements.append({"tag": "hr"})
        elements.append(
            {
                "tag": "note",
                "elements": [
                    {"tag": "plain_text", "content": f"{footer} · BitPro · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
                ],
            }
        )

        return {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": header_color,
                },
                "elements": elements,
            },
        }

    @classmethod
    def _build_strategy_profit_report_png(cls, report: Dict[str, Any]) -> bytes:
        """Render the running-strategy profit report as a long PNG image."""
        if not _HAS_PIL or Image is None or ImageDraw is None:
            raise RuntimeError("Pillow 未安装，无法生成飞书收益长图")

        strategies = list(report.get("strategies") or [])
        visible_strategies = strategies
        card_heights = [cls._profit_image_card_height(item) for item in visible_strategies]
        width = 2048
        margin = 28
        gap = 24
        title_h = 68
        summary_h = 172
        footer_h = 64
        height = margin + title_h + summary_h + gap
        height += sum(card_heights) + max(0, len(card_heights) - 1) * gap
        height += footer_h

        image = Image.new("RGB", (width, height), "#141a21")
        draw = ImageDraw.Draw(image)
        fonts = cls._profit_image_fonts()
        scope = str(report.get("report_scope") or "paper").lower()
        footer = cls._clean_text(
            report.get("footer")
            or (
                "数据来自 OKX 实盘账户 + BitPro 运行中实盘订阅"
                if scope == "live"
                else "数据来自 BitPro 当前运行中策略快照"
            )
        )

        draw.text((margin, margin + 4), str(report.get("title") or "模拟收益卡片"), font=fonts["title"], fill="#f8fafc")
        generated = str(report.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        cls._draw_text_ellipsis(
            draw,
            f"BitPro · {generated}",
            (width - margin - 360, margin + 18),
            fonts["small"],
            "#8b95a5",
            360,
            anchor="ra",
        )

        y = margin + title_h
        cls._draw_profit_summary_image(draw, report, margin, y, width - margin * 2, summary_h, fonts)
        y += summary_h + gap

        for index, item in enumerate(visible_strategies):
            card_h = card_heights[index]
            cls._draw_strategy_profit_image_card(draw, item, margin, y, width - margin * 2, card_h, fonts)
            y += card_h + gap

        draw.text((margin, height - footer_h + 14), footer, font=fonts["small"], fill="#697386")

        out = BytesIO()
        image.save(out, format="PNG", optimize=True)
        return out.getvalue()

    @classmethod
    def _profit_image_fonts(cls) -> Dict[str, Any]:
        return {
            "title": cls._load_profit_image_font(34, bold=True),
            "name": cls._load_profit_image_font(30, bold=True),
            "kpi_value": cls._load_profit_image_latin_font(30, bold=True),
            "metric": cls._load_profit_image_font(24, bold=False),
            "metric_value": cls._load_profit_image_latin_font(26, bold=True),
            "pnl": cls._load_profit_image_latin_font(31, bold=True),
            "small": cls._load_profit_image_font(21, bold=False),
            "tiny": cls._load_profit_image_font(18, bold=False),
            "tag": cls._load_profit_image_latin_font(20, bold=False),
        }

    @classmethod
    def _profit_image_font_candidates(cls, *, bold: bool = False) -> List[str]:
        if bold:
            return [
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/STHeiti Medium.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        return [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]

    @classmethod
    def _profit_image_font_available(cls) -> bool:
        return any(
            Path(path).exists()
            for path in cls._profit_image_font_candidates(bold=False)
            if "DejaVu" not in path
        )

    @classmethod
    def _load_profit_image_font(cls, size: int, *, bold: bool = False) -> Any:
        if ImageFont is None:
            return None
        for path in cls._profit_image_font_candidates(bold=bold):
            if Path(path).exists():
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    @classmethod
    def _profit_image_latin_font_candidates(cls, *, bold: bool = False) -> List[str]:
        if bold:
            return [
                "/usr/share/fonts/truetype/inter/Inter-Bold.ttf",
                "/usr/share/fonts/truetype/inter-v/Inter-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            ]
        return [
            "/usr/share/fonts/truetype/inter/Inter-Regular.ttf",
            "/usr/share/fonts/truetype/inter-v/Inter-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]

    @classmethod
    def _load_profit_image_latin_font(cls, size: int, *, bold: bool = False) -> Any:
        if ImageFont is None:
            return None
        for path in cls._profit_image_latin_font_candidates(bold=bold):
            if Path(path).exists():
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
        return cls._load_profit_image_font(size, bold=bold)

    @classmethod
    def _profit_image_card_height(cls, item: Dict[str, Any]) -> int:
        positions = item.get("positions") or []
        if not isinstance(positions, list):
            positions = []
        position_rows = min(len(positions), 4)
        if not position_rows:
            return 214
        return 256 + position_rows * 42 + (18 if len(positions) > 4 else 0)

    @classmethod
    def _draw_profit_summary_image(cls, draw: Any, report: Dict[str, Any], x: int, y: int, w: int, h: int, fonts: Dict[str, Any]) -> None:
        running_count = int(report.get("running_count") or len(report.get("strategies") or []))
        total_position_notional = cls._as_float(report.get("total_position_notional_usdt"))
        total_pnl = cls._as_float(report.get("total_pnl"))
        total_return_pct = cls._as_float(report.get("total_return_pct"))
        total_unrealized = cls._as_float(report.get("total_unrealized_pnl"))
        total_trades = int(report.get("total_trades") or sum(int(item.get("total_trades") or 0) for item in report.get("strategies") or []))
        position_strategy_count = int(report.get("position_strategy_count") or 0)
        win_rate = cls._as_float(report.get("win_rate"))
        winning_trades = int(report.get("winning_trades") or 0)
        closing_trades = int(report.get("closing_trades") or 0)
        profit_factor = cls._as_float(report.get("profit_factor"))
        gross_loss = cls._as_float(report.get("gross_loss"))
        long_short_ratio = report.get("long_short_ratio")
        active_alerts = int(report.get("active_alerts") or 0)
        total_alerts = int(report.get("total_alerts") or 0)
        scope = str(report.get("report_scope") or "paper").lower()
        pnl_label = cls._clean_text(
            report.get("summary_pnl_label") or ("策略盈亏" if scope == "live" else "总盈亏")
        )
        return_basis_label = cls._clean_text(report.get("return_basis_label") or "按初始资金加权")
        trade_count_label = cls._clean_text(report.get("trade_count_label") or f"共 {total_trades} 笔交易")
        win_rate_value = f"{win_rate:.1f}%" if closing_trades > 0 or (scope != "live" and win_rate > 0) else "--"
        long_short_value = "--"
        long_short_sub = "暂无多空比"
        long_short_color = "gray"
        try:
            ratio = float(long_short_ratio)
            if math.isfinite(ratio) and ratio > 0:
                long_short_value = f"{ratio:.2f}"
                if ratio > 1:
                    long_short_sub = "多头占优"
                    long_short_color = "green"
                elif ratio < 1:
                    long_short_sub = "空头占优"
                    long_short_color = "red"
                else:
                    long_short_sub = "多空均衡"
        except (TypeError, ValueError):
            pass
        items = [
            ("持仓总金额", cls._usd_compact(total_position_notional, digits=0), "按各策略标记价估算持仓金额", "blue"),
            ("浮动盈亏", cls._signed_usd(total_unrealized), f"{position_strategy_count} 个策略有持仓" if position_strategy_count > 0 else "暂无持仓浮盈", "red" if total_unrealized > 0 else "green" if total_unrealized < 0 else "gray"),
            (pnl_label, cls._signed_usd(total_pnl), trade_count_label, "red" if total_pnl > 0 else "green" if total_pnl < 0 else "gray"),
            ("收益率", cls._signed(total_return_pct, suffix="%"), return_basis_label, "red" if total_return_pct > 0 else "green" if total_return_pct < 0 else "gray"),
            ("胜率", win_rate_value, f"{winning_trades}/{closing_trades} 笔平仓盈利" if closing_trades > 0 else "暂无平仓样本", "blue"),
            ("盈亏比", cls._ratio_text(profit_factor), "总盈利 / 总亏损" if gross_loss > 0 else "暂无亏损样本", "blue"),
            ("多空比", long_short_value, long_short_sub, long_short_color),
            ("运行中策略", str(running_count), f"{total_trades} 笔交易" if running_count > 0 else "暂无运行", "green" if running_count > 0 else "gray"),
            ("活跃告警", str(active_alerts), f"共 {total_alerts} 条规则", "yellow" if active_alerts > 0 else "gray"),
        ]
        tile_gap = 14
        tile_w = int((w - tile_gap * (len(items) - 1)) / len(items))
        for index, (label, value, secondary, theme) in enumerate(items):
            tx = x + index * (tile_w + tile_gap)
            cls._draw_profit_metric_tile(draw, label, value, secondary, theme, int(tx), y, tile_w, h, fonts)

    @classmethod
    def _draw_strategy_profit_image_card(cls, draw: Any, item: Dict[str, Any], x: int, y: int, w: int, h: int, fonts: Dict[str, Any]) -> None:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=24, fill="#090f15")
        sid = item.get("strategy_id")
        name = cls._clean_text(item.get("name") or f"策略 {sid}")
        ret = cls._as_float(item.get("return_pct"))
        pnl = cls._as_float(item.get("pnl"))
        equity = cls._as_float(item.get("equity"))
        balance = cls._as_float(item.get("balance"))
        unrealized = cls._as_float(item.get("unrealized_pnl"))
        trades = int(item.get("total_trades") or 0)
        trade_count_label = cls._clean_text(item.get("trade_count_label") or f"{trades} 笔交易")

        draw.ellipse([x + 32, y + 42, x + 48, y + 58], fill="#46d982")
        title_x = x + 64
        title_y = y + 28
        title_max = w - 420
        rendered_name = cls._draw_text_ellipsis(draw, name, (title_x, title_y), fonts["name"], "#f8fafc", title_max)
        name_width = cls._text_width(draw, rendered_name, fonts["name"])
        badge_text = cls._signed(ret, suffix="%")
        badge_x = min(title_x + name_width + 16, x + w - 360)
        cls._draw_pill(
            draw,
            badge_text,
            badge_x,
            y + 31,
            fonts["tag"],
            cls._profit_image_financial_color(ret),
            bg="#162a21" if ret < 0 else "#301922",
        )
        pnl_text = cls._signed_usd(pnl)
        cls._draw_text_ellipsis(
            draw,
            pnl_text,
            (x + w - 32, y + 30),
            fonts["pnl"],
            cls._profit_image_financial_color(pnl),
            320,
            anchor="ra",
        )

        metric_y = y + 88
        metrics = [
            ("账户总额", cls._money(equity), "#f8fafc"),
            ("可用余额", cls._money(balance), "#f8fafc"),
            ("浮动盈亏", cls._signed_usd(unrealized), cls._profit_image_financial_color(unrealized)),
        ]
        metric_cols = [x + 32, x + 400, x + 768]
        for index, (label, value, color) in enumerate(metrics):
            draw.text((metric_cols[index], metric_y), label, font=fonts["small"], fill="#8b95a5")
            cls._draw_text_ellipsis(draw, value, (metric_cols[index], metric_y + 36), fonts["metric_value"], color, 300)

        cursor_y = y + 162
        positions = item.get("positions") or []
        if not isinstance(positions, list):
            positions = []
        if positions:
            draw.line([x + 32, cursor_y, x + w - 32, cursor_y], fill="#27313b", width=1)
            cursor_y += 24
            for pos in positions[:4]:
                symbol = cls._clean_text(pos.get("symbol") or "-")
                size = cls._quantity(cls._as_float(pos.get("size")))
                entry = cls._price(cls._as_float(pos.get("entry_price")))
                pos_pnl = cls._as_float(pos.get("unrealized_pnl"))
                draw.text((x + 32, cursor_y), symbol, font=fonts["small"], fill="#a7b0be")
                cls._draw_text_ellipsis(draw, f"{size} @ {entry}", (x + 480, cursor_y), fonts["small"], "#cbd5e1", 360)
                cls._draw_text_ellipsis(
                    draw,
                    cls._signed(pos_pnl),
                    (x + w - 32, cursor_y),
                    fonts["small"],
                    cls._profit_image_financial_color(pos_pnl),
                    180,
                    anchor="ra",
                )
                cursor_y += 42
            if len(positions) > 4:
                draw.text((x + 32, cursor_y), f"另有 {len(positions) - 4} 个持仓未展示", font=fonts["small"], fill="#697386")

        tag_y = y + h - 58
        next_x = x + 32
        symbols = item.get("symbols") or []
        if not isinstance(symbols, list):
            symbols = [str(symbols)] if symbols else []
        for symbol in [cls._clean_text(s) for s in symbols[:5] if s]:
            next_x = cls._draw_outline_tag(draw, symbol, next_x, tag_y, fonts["tag"])
            if next_x > x + w - 260:
                break
            next_x += 10
        hidden_symbols = max(0, len(symbols) - 5)
        if hidden_symbols:
            cls._draw_outline_tag(draw, f"+{hidden_symbols}", next_x, tag_y, fonts["tag"])
        cls._draw_text_ellipsis(draw, trade_count_label, (x + w - 32, tag_y + 6), fonts["small"], "#8b95a5", 220, anchor="ra")

    @staticmethod
    def _profit_image_financial_color(value: float) -> str:
        if value > 0:
            return "#ff3366"
        if value < 0:
            return "#18d36b"
        return "#8b95a5"

    @staticmethod
    def _profit_image_metric_theme(theme: str) -> Tuple[str, str, str]:
        themes = {
            "blue": ("#101d2e", "#1f4678", "#58a6ff"),
            "red": ("#2a151d", "#6f2a35", "#ff6b6b"),
            "green": ("#0f2a1d", "#24633d", "#32d976"),
            "yellow": ("#2b2511", "#725e16", "#ffd21e"),
            "gray": ("#111820", "#303946", "#9aa4b2"),
        }
        return themes.get(theme, themes["gray"])

    @classmethod
    def _draw_profit_metric_tile(
        cls,
        draw: Any,
        label: str,
        value: str,
        secondary: str,
        theme: str,
        x: int,
        y: int,
        w: int,
        h: int,
        fonts: Dict[str, Any],
    ) -> None:
        fill, outline, accent = cls._profit_image_metric_theme(theme)
        draw.rounded_rectangle([x, y, x + w, y + h], radius=16, fill=fill, outline=outline, width=1)
        cls._draw_text_ellipsis(draw, label, (x + 18, y + 26), fonts["tiny"], "#8b95a5", w - 36)
        cls._draw_text_ellipsis(draw, value, (x + 18, y + 72), fonts["kpi_value"], accent, w - 36)
        cls._draw_text_ellipsis(draw, secondary, (x + 18, y + 118), fonts["tiny"], "#7c8796", w - 36)

    @staticmethod
    def _text_width(draw: Any, text: str, font: Any) -> int:
        bbox = draw.textbbox((0, 0), text, font=font)
        return int(bbox[2] - bbox[0])

    @classmethod
    def _draw_text_ellipsis(
        cls,
        draw: Any,
        text: str,
        xy: Tuple[int, int],
        font: Any,
        fill: str,
        max_width: int,
        *,
        anchor: Optional[str] = None,
    ) -> str:
        out = str(text or "")
        if max_width > 0:
            while len(out) > 1 and cls._text_width(draw, out, font) > max_width:
                out = f"{out[:-2]}…"
        draw.text(xy, out, font=font, fill=fill, anchor=anchor)
        return out

    @classmethod
    def _draw_pill(cls, draw: Any, text: str, x: int, y: int, font: Any, fill: str, *, bg: Optional[str] = None) -> int:
        pad_x = 12
        text_w = cls._text_width(draw, text, font)
        bg_color = bg or "#13241d"
        draw.rounded_rectangle([x, y, x + text_w + pad_x * 2, y + 38], radius=8, fill=bg_color)
        draw.text((x + pad_x, y + 7), text, font=font, fill=fill)
        return x + text_w + pad_x * 2

    @classmethod
    def _draw_outline_tag(cls, draw: Any, text: str, x: int, y: int, font: Any, *, filled: bool = False) -> int:
        label = str(text or "-")
        pad_x = 14
        tag_h = 38
        text_w = cls._text_width(draw, label, font)
        fill = "#243142" if filled else "#090f15"
        outline = "#2d3744"
        draw.rounded_rectangle([x, y, x + text_w + pad_x * 2, y + tag_h], radius=8, fill=fill, outline=outline, width=1)
        draw.text((x + pad_x, y + 7), label, font=font, fill="#8b95a5")
        return x + text_w + pad_x * 2

    @classmethod
    def _build_strategy_profit_elements(cls, item: Dict[str, Any]) -> List[Dict[str, Any]]:
        sid = item.get("strategy_id")
        name = cls._clean_text(item.get("name") or f"策略 {sid}")
        ret = cls._as_float(item.get("return_pct"))
        pnl = cls._as_float(item.get("pnl"))
        equity = cls._as_float(item.get("equity"))
        balance = cls._as_float(item.get("balance"))
        unrealized = cls._as_float(item.get("unrealized_pnl"))
        trades = int(item.get("total_trades") or 0)
        trade_count_label = cls._clean_text(item.get("trade_count_label") or f"{trades} 笔交易")
        symbols = item.get("symbols") or []
        if not isinstance(symbols, list):
            symbols = [str(symbols)]
        visible_symbols = [cls._clean_text(symbol) for symbol in symbols[:5] if symbol]
        symbol_badges = " ".join(f"`{symbol}`" for symbol in visible_symbols)
        hidden_symbols = max(0, len(symbols) - len(visible_symbols))
        if hidden_symbols:
            symbol_badges = f"{symbol_badges} `+{hidden_symbols}`".strip()
        if not symbol_badges:
            symbol_badges = "`-`"
        positions = item.get("positions") or []
        if not isinstance(positions, list):
            positions = []

        elements: List[Dict[str, Any]] = [
            {
                "tag": "column_set",
                "flex_mode": "none",
                "columns": [
                    cls._markdown_column(
                        f"<font color='green'>●</font> **{name}**  {cls._badge(cls._signed(ret, suffix='%'), ret)}",
                        weight=4,
                    ),
                    cls._markdown_column(
                        cls._financial_usd_text(pnl, bold=True),
                        weight=2,
                    ),
                ],
            },
            {
                "tag": "column_set",
                "flex_mode": "none",
                "columns": [
                    cls._markdown_column(f"<font color='grey'>账户总额</font>\n**{cls._money(equity)}**", weight=1),
                    cls._markdown_column(f"<font color='grey'>可用余额</font>\n**{cls._money(balance)}**", weight=1),
                    cls._markdown_column(
                        f"<font color='grey'>浮动盈亏</font>\n{cls._financial_usd_text(unrealized, bold=True)}",
                        weight=1,
                    ),
                ],
            },
        ]

        if positions:
            position_lines = []
            for pos in positions[:3]:
                symbol = cls._clean_text(pos.get("symbol") or "-")
                size = cls._quantity(cls._as_float(pos.get("size")))
                entry = cls._price(cls._as_float(pos.get("entry_price")))
                pos_pnl = cls._as_float(pos.get("unrealized_pnl"))
                position_lines.append(
                    f"<font color='grey'>{symbol}</font>　{size} @ {entry}　{cls._financial_text(pos_pnl, suffix='', bold=True)}"
                )
            if len(positions) > 3:
                position_lines.append(f"<font color='grey'>另有 {len(positions) - 3} 个持仓未展示</font>")
            elements.append({"tag": "markdown", "content": "\n".join(position_lines)})

        elements.append(
            {
                "tag": "markdown",
                "content": f"{symbol_badges}　<font color='grey'>{trade_count_label}</font>",
            }
        )
        return elements

    @staticmethod
    def _markdown_column(content: str, *, weight: int = 1) -> Dict[str, Any]:
        return {
            "tag": "column",
            "width": "weighted",
            "weight": weight,
            "elements": [{"tag": "markdown", "content": content}],
        }

    @staticmethod
    def _clean_text(value: Any) -> str:
        return str(value or "").replace("\n", " ").strip()

    @staticmethod
    def _as_float(value: Any, default: float = 0.0) -> float:
        try:
            out = float(value)
        except (TypeError, ValueError):
            return default
        return out if math.isfinite(out) else default

    @staticmethod
    def _financial_color(value: float) -> str:
        if value > 0:
            return "red"
        if value < 0:
            return "green"
        return "grey"

    @classmethod
    def _financial_text(cls, value: float, *, suffix: str = "", bold: bool = False) -> str:
        text = cls._signed(value, suffix=suffix)
        if bold:
            text = f"**{text}**"
        return f"<font color='{cls._financial_color(value)}'>{text}</font>"

    @classmethod
    def _financial_usd_text(cls, value: float, *, bold: bool = False) -> str:
        text = cls._signed_usd(value)
        if bold:
            text = f"**{text}**"
        return f"<font color='{cls._financial_color(value)}'>{text}</font>"

    @classmethod
    def _badge(cls, text: str, value: float) -> str:
        return f"<font color='{cls._financial_color(value)}'>`{text}`</font>"

    @staticmethod
    def _signed(value: float, *, suffix: str = "") -> str:
        sign = "+" if value > 0 else ""
        return f"{sign}{value:,.2f}{suffix}"

    @staticmethod
    def _usd_compact(value: float, *, signed: bool = False, digits: int = 2) -> str:
        sign = "+" if signed and value > 0 else "-" if signed and value < 0 else ""
        amount = abs(value) if signed else value
        if digits <= 0:
            return f"{sign}${amount:,.0f}"
        return f"{sign}${amount:,.{digits}f}"

    @classmethod
    def _signed_usd(cls, value: float, *, digits: int = 2) -> str:
        return cls._usd_compact(value, signed=True, digits=digits)

    @staticmethod
    def _ratio_text(value: float) -> str:
        if not math.isfinite(value) or value <= 0:
            return "--"
        return f"{value:.2f}"

    @staticmethod
    def _money(value: float) -> str:
        return f"${value:,.2f}"

    @staticmethod
    def _price(value: float) -> str:
        if abs(value) >= 100:
            return f"{value:,.2f}"
        if abs(value) >= 1:
            return f"{value:,.4f}"
        return f"{value:.6f}".rstrip("0").rstrip(".") or "0"

    @staticmethod
    def _quantity(value: float) -> str:
        if abs(value) >= 1000:
            return f"{value:,.6f}".rstrip("0").rstrip(".")
        if abs(value) >= 1:
            return f"{value:,.6f}".rstrip("0").rstrip(".")
        return f"{value:.8f}".rstrip("0").rstrip(".") or "0"

    async def notify_ai_signal(self, symbol: str, direction: str, confidence: float, analysis: str) -> bool:
        """AI 预测信号推送"""
        if self._skip_disabled_push_kind("ai_signal", f"AI 信号 | {symbol}", analysis):
            return False

        color = "green" if direction == "看涨" else ("red" if direction == "看跌" else "blue")
        return await self.send_message(
            title=f"🤖 AI 信号 | {symbol} {direction}",
            content=(
                f"**置信度**: {confidence:.0%}\n"
                f"---\n"
                f"{analysis}"
            ),
            color=color,
        )

    def get_message_history(self, limit: int = 50) -> list:
        return self._history[-limit:]


feishu_notifier = FeishuNotifier()
