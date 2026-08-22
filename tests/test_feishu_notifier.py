from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.services.feishu_notifier as feishu_module  # noqa: E402
from app.services.feishu_notifier import FeishuNotifier  # noqa: E402


class FakeResponse:
    status_code = 200
    text = '{"code":0}'

    def json(self):
        return {"code": 0}


class FakeAsyncClient:
    created_kwargs = None

    def __init__(self, **kwargs):
        FakeAsyncClient.created_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json):
        return FakeResponse()


class FakeJsonResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        self.text = str(body)

    def json(self):
        return self._body


class FakeFeishuImageAsyncClient:
    requests = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, **kwargs):
        self.requests.append({"url": url, "kwargs": kwargs, "client_kwargs": self.kwargs})
        if url.endswith("/auth/v3/tenant_access_token/internal"):
            return FakeJsonResponse({"code": 0, "tenant_access_token": "tenant-token"})
        if url.endswith("/im/v1/images"):
            return FakeJsonResponse({"code": 0, "data": {"image_key": "img_v3_profit"}})
        return FakeJsonResponse({"code": 0})


class RecordingNotifier(FeishuNotifier):
    def __init__(self):
        self.webhook_url = ""
        self.enabled = True
        self._history = []
        self.sent_messages = []
        self.sent_payloads = []

    async def send_message(self, *args, **kwargs):
        self.sent_messages.append({"args": args, "kwargs": kwargs})
        return True

    async def _send_payload(self, payload, record, *, require_enabled=True):
        self.sent_payloads.append(
            {"payload": payload, "record": record, "require_enabled": require_enabled}
        )
        return True


def _collect_strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(_collect_strings(item))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_collect_strings(item))
        return out
    return []


def test_feishu_send_does_not_inherit_environment_proxy(monkeypatch):
    monkeypatch.setattr(feishu_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(feishu_module, "_HAS_HTTPX", True)
    notifier = FeishuNotifier()
    notifier.webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test-token"

    sent = asyncio.run(notifier.send_message("BitPro 测试", "proxy bypass check", require_enabled=False))

    assert sent is True
    assert FakeAsyncClient.created_kwargs["trust_env"] is False


def test_paper_trade_notifications_are_suppressed():
    notifier = RecordingNotifier()

    sent = asyncio.run(
        notifier.notify_trade(
            strategy="Paper#10",
            symbol="ZKJ/USDT",
            side="BUY",
            price=0.01,
            amount=210159.964375,
            cost=2581.02,
            fee=2.581,
        )
    )

    assert sent is False
    assert notifier.sent_messages == []


def test_non_profit_trade_notifications_are_suppressed_by_push_policy():
    notifier = RecordingNotifier()

    sent = asyncio.run(
        notifier.notify_trade(
            strategy="Live#10",
            symbol="BTC/USDT",
            side="SELL",
            price=100000,
            amount=0.01,
            cost=1000,
            fee=1,
            pnl=12.5,
        )
    )

    assert sent is False
    assert notifier.sent_messages == []
    assert notifier._history[-1]["skipped"] == "push_kind_disabled:trade"


def test_strategy_running_status_notifications_are_suppressed():
    notifier = RecordingNotifier()

    sent = asyncio.run(
        notifier.notify_strategy_status(
            strategy_id=25,
            name="Kairos Path Edge · 高流动性 Top8 成本优先",
            status="running",
        )
    )

    assert sent is False
    assert notifier.sent_messages == []


def test_strategy_stop_status_notifications_are_suppressed_by_push_policy():
    notifier = RecordingNotifier()

    sent = asyncio.run(
        notifier.notify_strategy_status(
            strategy_id=25,
            name="Kairos Path Edge · 高流动性 Top8 成本优先",
            status="stopped",
        )
    )

    assert sent is False
    assert notifier.sent_messages == []
    assert notifier._history[-1]["skipped"] == "push_kind_disabled:strategy_status"


def test_paper_liquidation_alert_is_an_enabled_red_risk_card():
    notifier = RecordingNotifier()

    sent = asyncio.run(
        notifier.notify_paper_liquidation(
            {
                "strategy_id": 89,
                "strategy_name": "[合约][15M][CTA] BTC · 测试爆仓 · 100U",
                "symbol": "BTC/USDT:USDT",
                "pos_side": "long",
                "price": 40_000,
                "liquidation_price": 40_201.005,
                "contracts": 2,
                "leverage": 5,
                "realized_pnl": -200,
                "account_equity_before": 9_800,
                "maintenance_margin": 4,
            }
        )
    )

    assert sent is True
    assert notifier.sent_messages
    kwargs = notifier.sent_messages[0]["kwargs"]
    assert "合约模拟盘爆仓" in kwargs["title"]
    assert "BTC/USDT:USDT long" in kwargs["content"]
    assert "策略已自动暂停" in kwargs["content"]
    assert kwargs["color"] == "red"


def test_strategy_profit_report_uses_rich_interactive_card(monkeypatch):
    notifier = RecordingNotifier()
    monkeypatch.setattr(notifier, "_profit_image_font_available", lambda: True)

    sent = asyncio.run(
        notifier.notify_strategy_profit_report(
            {
                "running_count": 1,
                "total_equity": 10319.48,
                "total_pnl": 319.48,
                "total_return_pct": 3.19,
                "total_unrealized_pnl": 1.84,
                "strategies": [
                    {
                        "strategy_id": 14,
                        "name": "SuperPnL 高流动性小币 Top5 · 激进单仓",
                        "exchange": "okx",
                        "symbols": ["BTC/USDT", "ETH/USDT", "DOGE/USDT", "SOL/USDT", "ADA/USDT", "ZKJ/USDT"],
                        "pnl": 319.48,
                        "return_pct": 3.19,
                        "equity": 10319.48,
                        "balance": 7736.62,
                        "unrealized_pnl": 1.84,
                        "total_trades": 64,
                        "positions": [
                            {
                                "symbol": "ZKJ/USDT",
                                "size": 210159.964375,
                                "entry_price": 0.01,
                                "unrealized_pnl": 1.84,
                            }
                        ],
                    }
                ],
            }
        )
    )

    assert sent is True
    assert len(notifier.sent_payloads) == 1
    payload = notifier.sent_payloads[0]["payload"]
    assert payload["msg_type"] == "interactive"
    assert payload["card"]["config"]["wide_screen_mode"] is True
    assert payload["card"]["header"]["title"]["content"] == "模拟收益卡片"
    assert payload["card"]["header"]["template"] == "red"
    assert any(element.get("tag") == "column_set" for element in payload["card"]["elements"])
    card_text = "\n".join(_collect_strings(payload))
    assert "SuperPnL 高流动性小币 Top5 · 激进单仓" in card_text
    assert "+3.19%" in card_text
    assert "+$319.48" in card_text
    assert "$10,319.48" in card_text
    assert "319.48 USDT" not in card_text
    assert "`OKX`" not in card_text
    assert "`okx`" not in card_text
    assert "账户总额" in card_text
    assert "总权益" not in card_text
    assert "ZKJ/USDT" in card_text
    assert "210,159.964375 @ 0.01" in card_text
    assert "64 笔交易" in card_text
    delivery = notifier.get_last_profit_report_delivery()
    assert delivery["type"] == "card"
    assert delivery["image_reason"] == "feishu_app_credentials_missing"


def test_strategy_profit_report_card_includes_all_running_strategies(monkeypatch):
    notifier = RecordingNotifier()
    monkeypatch.setattr(notifier, "_profit_image_font_available", lambda: True)
    strategies = [
        {
            "strategy_id": strategy_id,
            "name": f"strategy-{strategy_id}",
            "symbols": ["BTC/USDT"],
            "pnl": strategy_id,
            "return_pct": strategy_id / 100,
            "equity": 10000 + strategy_id,
            "balance": 10000 + strategy_id,
            "unrealized_pnl": 0,
            "total_trades": strategy_id,
            "positions": [],
        }
        for strategy_id in range(1, 17)
    ]

    sent = asyncio.run(
        notifier.notify_strategy_profit_report(
            {
                "running_count": len(strategies),
                "total_equity": sum(item["equity"] for item in strategies),
                "total_pnl": sum(item["pnl"] for item in strategies),
                "total_return_pct": 0.1,
                "total_unrealized_pnl": 0,
                "strategies": strategies,
            }
        )
    )

    assert sent is True
    card_text = "\n".join(_collect_strings(notifier.sent_payloads[0]["payload"]))
    assert "strategy-1" in card_text
    assert "strategy-16" in card_text
    assert "未展示" not in card_text


def test_strategy_profit_image_matches_monitor_money_and_badge_style():
    image_card_source = inspect.getsource(FeishuNotifier._draw_strategy_profit_image_card)
    fonts_source = inspect.getsource(FeishuNotifier._profit_image_fonts)
    png_source = inspect.getsource(FeishuNotifier._build_strategy_profit_report_png)

    assert "cls._signed_usd(pnl)" in image_card_source
    assert "cls._signed_usd(unrealized)" in image_card_source
    assert "suffix=\" USDT\"" not in image_card_source
    assert "item.get(\"exchange\")" not in image_card_source
    assert "_draw_outline_tag(draw, exchange" not in image_card_source
    assert "\"kpi_value\": cls._load_profit_image_latin_font" in fonts_source
    assert "\"metric_value\": cls._load_profit_image_latin_font" in fonts_source
    assert "\"pnl\": cls._load_profit_image_latin_font" in fonts_source
    assert "report.get(\"footer\")" in png_source


def test_live_profit_report_card_labels_strategy_pnl_and_real_sources(monkeypatch):
    notifier = RecordingNotifier()
    monkeypatch.setattr(notifier, "_profit_image_font_available", lambda: True)

    sent = asyncio.run(
        notifier.notify_strategy_profit_report(
            {
                "report_scope": "live",
                "title": "实盘收益卡片",
                "footer": "数据来自 OKX 实盘账户 + BitPro 运行中实盘订阅",
                "running_count": 1,
                "total_equity": 54.87,
                "total_initial_capital": 100,
                "total_pnl": -26.24,
                "total_return_pct": -26.24,
                "total_unrealized_pnl": 0,
                "strategies": [
                    {
                        "strategy_id": 7,
                        "name": "实盘账户 默认 OKX 实盘账户",
                        "symbols": [],
                        "pnl": -26.24,
                        "return_pct": -26.24,
                        "equity": 54.87,
                        "balance": 54.87,
                        "unrealized_pnl": 0,
                        "total_trades": 75,
                        "positions": [],
                    }
                ],
            }
        )
    )

    assert sent is True
    card_text = "\n".join(_collect_strings(notifier.sent_payloads[0]["payload"]))
    assert "策略归因盈亏" in card_text
    assert "总收益" not in card_text
    assert "数据来自 OKX 实盘账户 + BitPro 运行中实盘订阅" in card_text


def test_live_profit_image_summary_uses_live_specific_labels(monkeypatch):
    captured = []

    def fake_tile(cls, draw, label, value, secondary, theme, x, y, w, h, fonts):
        captured.append((label, value, secondary, theme))

    monkeypatch.setattr(
        FeishuNotifier,
        "_draw_profit_metric_tile",
        classmethod(fake_tile),
    )

    FeishuNotifier._draw_profit_summary_image(
        None,
        {
            "report_scope": "live",
            "running_count": 1,
            "total_position_notional_usdt": 0,
            "total_pnl": -26.24,
            "total_return_pct": -26.24,
            "total_unrealized_pnl": 0,
            "total_trades": 75,
            "position_strategy_count": 0,
            "closing_trades": 0,
            "winning_trades": 0,
            "win_rate": 0,
            "profit_factor": 0,
            "gross_loss": 0,
            "active_alerts": 0,
            "total_alerts": 0,
            "summary_pnl_label": "今日策略盈亏",
            "return_basis_label": "按日初实盘订阅资金基准",
            "trade_count_label": "今日 75 笔交易",
            "strategies": [],
        },
        0,
        0,
        900,
        172,
        {},
    )

    tiles = {label: (value, secondary, theme) for label, value, secondary, theme in captured}
    assert tiles["今日策略盈亏"] == ("-$26.24", "今日 75 笔交易", "green")
    assert tiles["收益率"] == ("-26.24%", "按日初实盘订阅资金基准", "green")
    assert tiles["胜率"] == ("--", "暂无平仓样本", "blue")


def test_profit_report_money_formatter_uses_monitor_page_style():
    assert FeishuNotifier._money(10077.86) == "$10,077.86"
    assert FeishuNotifier._signed_usd(319.48) == "+$319.48"
    assert FeishuNotifier._signed_usd(-39.68) == "-$39.68"


def test_strategy_profit_image_renders_all_running_strategies(monkeypatch):
    drawn_strategy_ids = []

    def fake_draw_card(cls, draw, item, x, y, w, h, fonts):
        drawn_strategy_ids.append(item["strategy_id"])

    monkeypatch.setattr(
        FeishuNotifier,
        "_draw_strategy_profit_image_card",
        classmethod(fake_draw_card),
    )
    strategies = [
        {
            "strategy_id": strategy_id,
            "name": f"strategy-{strategy_id}",
            "symbols": ["BTC/USDT"],
            "pnl": strategy_id,
            "return_pct": strategy_id / 100,
            "equity": 10000 + strategy_id,
            "balance": 10000 + strategy_id,
            "unrealized_pnl": 0,
            "total_trades": strategy_id,
            "positions": [],
        }
        for strategy_id in range(1, 17)
    ]

    image_bytes = FeishuNotifier._build_strategy_profit_report_png(
        {
            "running_count": len(strategies),
            "total_equity": sum(item["equity"] for item in strategies),
            "total_pnl": sum(item["pnl"] for item in strategies),
            "total_return_pct": 0.1,
            "total_unrealized_pnl": 0,
            "strategies": strategies,
        }
    )

    assert image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert drawn_strategy_ids == list(range(1, 17))


def test_profit_report_image_status_explains_missing_app_credentials(monkeypatch):
    notifier = FeishuNotifier()
    monkeypatch.setattr(notifier, "_configured_feishu_app_credentials", lambda: ("", ""))
    monkeypatch.setattr(notifier, "_profit_report_image_enabled", lambda: True)
    monkeypatch.setattr(notifier, "_profit_image_font_available", lambda: True)
    monkeypatch.setattr(feishu_module, "_HAS_HTTPX", True)
    monkeypatch.setattr(feishu_module, "_HAS_PIL", True)

    status = notifier.get_profit_report_image_status()

    assert status["ready"] is False
    assert status["app_configured"] is False
    assert status["reason"] == "feishu_app_credentials_missing"


def test_profit_report_image_status_blocks_without_cjk_font(monkeypatch):
    notifier = FeishuNotifier()
    monkeypatch.setattr(notifier, "_configured_feishu_app_credentials", lambda: ("cli_test", "app-secret"))
    monkeypatch.setattr(notifier, "_profit_report_image_enabled", lambda: True)
    monkeypatch.setattr(notifier, "_profit_image_font_available", lambda: False)
    monkeypatch.setattr(feishu_module, "_HAS_HTTPX", True)
    monkeypatch.setattr(feishu_module, "_HAS_PIL", True)

    status = notifier.get_profit_report_image_status()

    assert status["ready"] is False
    assert status["app_configured"] is True
    assert status["reason"] == "cjk_font_missing"


def test_strategy_profit_report_can_upload_and_send_long_image(monkeypatch):
    FakeFeishuImageAsyncClient.requests = []
    monkeypatch.setattr(feishu_module.httpx, "AsyncClient", FakeFeishuImageAsyncClient)
    monkeypatch.setattr(feishu_module, "_HAS_HTTPX", True)

    notifier = FeishuNotifier()
    notifier.webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test-token"
    monkeypatch.setattr(notifier, "_configured_webhook_url", lambda: notifier.webhook_url)
    monkeypatch.setattr(notifier, "_configured_feishu_app_credentials", lambda: ("cli_test", "app-secret"))
    monkeypatch.setattr(notifier, "_profit_report_image_enabled", lambda: True)
    monkeypatch.setattr(notifier, "_profit_image_font_available", lambda: True)

    sent = asyncio.run(
        notifier.notify_strategy_profit_report(
            {
                "running_count": 1,
                "total_equity": 9960.32,
                "total_pnl": -39.68,
                "total_return_pct": -0.4,
                "total_unrealized_pnl": 0,
                "total_position_notional_usdt": 286085,
                "position_strategy_count": 7,
                "win_rate": 41.9,
                "closing_trades": 1158,
                "winning_trades": 485,
                "profit_factor": 0.6,
                "gross_loss": 120,
                "long_short_ratio": 0.58,
                "active_alerts": 2,
                "total_alerts": 2,
                "strategies": [
                    {
                        "strategy_id": 12,
                        "name": "Kairos 30m DCA · 每30分钟开仓",
                        "exchange": "okx",
                        "symbols": ["BTC/USDT"],
                        "pnl": -39.68,
                        "return_pct": -0.4,
                        "equity": 9960.32,
                        "balance": 9960.32,
                        "unrealized_pnl": 0,
                        "total_trades": 84,
                        "positions": [],
                    }
                ],
            }
        )
    )

    assert sent is True
    token_req = next(req for req in FakeFeishuImageAsyncClient.requests if "tenant_access_token" in req["url"])
    assert token_req["kwargs"]["json"] == {"app_id": "cli_test", "app_secret": "app-secret"}
    assert token_req["client_kwargs"]["trust_env"] is False

    upload_req = next(req for req in FakeFeishuImageAsyncClient.requests if req["url"].endswith("/im/v1/images"))
    assert upload_req["kwargs"]["headers"]["Authorization"] == "Bearer tenant-token"
    assert upload_req["kwargs"]["data"] == {"image_type": "message"}
    image_file = upload_req["kwargs"]["files"]["image"]
    assert image_file[0] == "bitpro-strategy-profit.png"
    assert image_file[1].startswith(b"\x89PNG\r\n\x1a\n")
    assert image_file[2] == "image/png"

    webhook_req = FakeFeishuImageAsyncClient.requests[-1]
    assert webhook_req["url"] == "https://open.feishu.cn/open-apis/bot/v2/hook/test-token"
    assert webhook_req["kwargs"]["json"] == {"msg_type": "image", "content": {"image_key": "img_v3_profit"}}
    delivery = notifier.get_last_profit_report_delivery()
    assert delivery["type"] == "image"
    assert delivery["sent"] is True
    assert delivery["error"] is None
